"""Keyless BILLSTATUS enrichment: outcome, roll-call votes, actions,
cosponsors for any federal bill, fetched from public bulk-data endpoints.

Three public, unauthenticated sources:
  1. GovInfo bulk data   https://www.govinfo.gov/bulkdata/BILLSTATUS/...
     — per-bill status XML: actions, recorded-vote pointers, laws,
       structured sponsor/cosponsors, policy area, subjects.
  2. House Clerk         https://clerk.house.gov/evs/{year}/roll{NNN}.xml
     — per-party totals + per-member positions for House roll calls.
  3. Senate LIS          https://www.senate.gov/legislative/LIS/roll_call_votes/...
     — counts + per-member positions for Senate roll calls.

The output is one `billstatus.json` per bill directory, written NEXT TO
the existing metadata.json (never modifying it). The index build reads
billstatus.json when present and falls back to metadata.json fields
otherwise, so corpora ingested before this module exist keep working.

Why this module exists (meeting notes, 2026-06):
  - "Show negative bills that failed (why it fails?)"  → `outcome` with
    the terminal event and full action trail.
  - "A lot of legislation is passed on a bipartisan vote in a single
    bill" → per-party vote splits and a bipartisan_support metric on
    every recorded vote, so 'secret congress' patterns are queryable.
  - "How much it affected the vote" → per-member positions (with state
    and district) for passage-class votes.
"""
from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

BILLSTATUS_URL = (
    "https://www.govinfo.gov/bulkdata/BILLSTATUS/{congress}/{bill_type}/"
    "BILLSTATUS-{congress}{bill_type}{number}.xml"
)
CACHE_DIR = Path("data/cache/billstatus")

# Congresses whose final adjournment has passed. A non-enacted bill from
# one of these is dead, not pending. Update when a Congress ends.
CLOSED_CONGRESSES = frozenset(range(93, 119))  # 119th ends 2027-01-03

_SESSION = requests.Session()
_SESSION.headers.update({"User-Agent": "polilabs-ingest/1.0"})


def _http_get(url: str, *, timeout: float = 30.0) -> bytes | None:
    """GET with the govinfo quirk handled: unknown packages return a 200
    HTML page, so sniff for XML. Returns None on any miss."""
    try:
        r = _SESSION.get(url, timeout=timeout)
    except requests.RequestException:
        return None
    if r.status_code != 200:
        return None
    body = r.content.lstrip(b"\xef\xbb\xbf").lstrip()
    if not body.startswith(b"<?xml") and not body.startswith(b"<"):
        return None
    if body.startswith(b"<!DOCTYPE html") or body.startswith(b"<html"):
        return None
    return r.content


def fetch_billstatus_xml(
    congress: int, bill_type: str, number: int, *, use_cache: bool = True,
) -> bytes | None:
    """Fetch BILLSTATUS XML from bulk data, with a local file cache so
    backfills over the whole corpus are resumable and re-runnable."""
    cache_path = CACHE_DIR / f"BILLSTATUS-{congress}{bill_type}{number}.xml"
    if use_cache and cache_path.exists():
        return cache_path.read_bytes()
    raw = _http_get(BILLSTATUS_URL.format(congress=congress, bill_type=bill_type, number=number))
    if raw is not None and use_cache:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_bytes(raw)
    return raw


# ---------------------------------------------------------------- parsing

def _text(el: ET.Element | None, path: str) -> str | None:
    if el is None:
        return None
    t = el.findtext(path)
    return t.strip() if t and t.strip() else None


def _person(item: ET.Element) -> dict[str, Any]:
    return {
        "bioguideId": _text(item, "bioguideId"),
        "fullName": _text(item, "fullName"),
        "firstName": _text(item, "firstName"),
        "lastName": _text(item, "lastName"),
        "party": _text(item, "party"),
        "state": _text(item, "state"),
        "district": _text(item, "district"),
    }


def parse_billstatus(xml_bytes: bytes) -> dict[str, Any]:
    """Pull the agent-relevant slice out of a BILLSTATUS document."""
    root = ET.fromstring(xml_bytes)
    bill = root.find("bill")
    if bill is None:
        raise ValueError("no <bill> element in BILLSTATUS document")

    laws = [
        {"type": _text(l, "type"), "number": _text(l, "number")}
        for l in bill.findall(".//laws/item")
    ]

    actions: list[dict[str, Any]] = []
    for a in bill.findall("./actions/item"):
        actions.append({
            "actionDate": _text(a, "actionDate"),
            "text": _text(a, "text"),
            "type": _text(a, "type"),
            "actionCode": _text(a, "actionCode"),
            "sourceSystem": _text(a, "sourceSystem/name"),
        })

    # Recorded-vote pointers appear inside action items, frequently
    # duplicated (same roll attached to several action rows). Dedupe on
    # (chamber, congress, session, roll).
    seen: set[tuple] = set()
    recorded: list[dict[str, Any]] = []
    for rv in bill.findall(".//recordedVotes/recordedVote"):
        key = (
            _text(rv, "chamber"), _text(rv, "congress"),
            _text(rv, "sessionNumber"), _text(rv, "rollNumber"),
        )
        if key in seen:
            continue
        seen.add(key)
        recorded.append({
            "chamber": _text(rv, "chamber"),
            "congress": _text(rv, "congress"),
            "session": _text(rv, "sessionNumber"),
            "roll_number": _text(rv, "rollNumber"),
            "date": _text(rv, "date"),
            "url": _text(rv, "url"),
        })

    sponsors = [_person(s) for s in bill.findall("./sponsors/item")]
    cosponsors = [
        {**_person(c),
         "sponsorshipDate": _text(c, "sponsorshipDate"),
         "isOriginalCosponsor": _text(c, "isOriginalCosponsor")}
        for c in bill.findall("./cosponsors/item")
    ]
    subjects = sorted({
        s.findtext("name").strip()
        for s in bill.findall(".//subjects//item")
        if s.findtext("name") and s.findtext("name").strip()
    })

    return {
        "congress": int(_text(bill, "congress") or 0),
        "bill_type": (_text(bill, "type") or "").lower(),
        "bill_number": int(_text(bill, "number") or 0),
        "title": _text(bill, "title"),
        "introduced_date": _text(bill, "introducedDate"),
        "origin_chamber": _text(bill, "originChamber"),
        "policy_area": _text(bill, "policyArea/name"),
        "subjects": subjects,
        "sponsor": sponsors[0] if sponsors else None,
        "cosponsors": cosponsors,
        "laws": laws,
        "actions": actions,
        "recorded_vote_refs": recorded,
        "latest_action": {
            "actionDate": _text(bill, "latestAction/actionDate"),
            "text": _text(bill, "latestAction/text"),
        },
    }


# ------------------------------------------------------------- roll calls

PASSAGE_PATTERNS = re.compile(
    r"(on passage|suspend the rules and pass|motion to concur"
    r"|conference report|on agreeing to the resolution"
    r"|on the joint resolution|on the concurrent resolution"
    r"|on passage of the bill)",
    re.IGNORECASE,
)
CLOTURE_PATTERN = re.compile(r"cloture", re.IGNORECASE)
VETO_PATTERN = re.compile(r"(overrid\w* the veto|veto override)", re.IGNORECASE)
AMENDMENT_PATTERN = re.compile(
    r"(on the amendment|on agreeing to the amendment)", re.IGNORECASE
)


def classify_vote(question: str) -> str:
    """passage | cloture | veto_override | amendment | procedural."""
    q = question or ""
    if CLOTURE_PATTERN.search(q):
        return "cloture"
    if VETO_PATTERN.search(q):
        return "veto_override"
    if PASSAGE_PATTERNS.search(q):
        return "passage"
    if AMENDMENT_PATTERN.search(q):
        return "amendment"
    return "procedural"


@dataclass
class RollCall:
    chamber: str
    congress: int
    session: int
    roll_number: int
    date: str | None
    question: str | None
    result: str | None
    vote_type: str
    source_url: str
    totals: dict[str, dict[str, int]] = field(default_factory=dict)  # party -> counts
    yea_total: int = 0
    nay_total: int = 0
    bipartisan_support: float | None = None
    bipartisan_label: str | None = None
    members: list[dict[str, Any]] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {
            "chamber": self.chamber,
            "congress": self.congress,
            "session": self.session,
            "roll_number": self.roll_number,
            "date": self.date,
            "question": self.question,
            "result": self.result,
            "vote_type": self.vote_type,
            "source_url": self.source_url,
            "totals_by_party": self.totals,
            "yea_total": self.yea_total,
            "nay_total": self.nay_total,
            "bipartisan_support": self.bipartisan_support,
            "bipartisan_label": self.bipartisan_label,
            "members": self.members,
        }


def _bipartisan_metrics(totals: dict[str, dict[str, int]]) -> tuple[float | None, str | None]:
    """bipartisan_support = min over the two major parties of that
    party's yes-share among its yes+no votes. 1.0 = both parties
    unanimous yes; 0.0 = at least one party unanimous no.

    Labels: party_line (<0.10), cross_party (<0.50),
    bipartisan (<0.90), near_unanimous (>=0.90). Calibrated against
    known votes: CHIPS final House concurrence (24 R yeas, 0.11) reads
    cross_party; the earlier party-line COMPETES vote (1 R yea, 0.005)
    reads party_line; PACT Act Senate (86-11) reads bipartisan.
    """
    shares = []
    for party in ("D", "R"):
        c = totals.get(party)
        if not c:
            continue
        denom = c.get("yea", 0) + c.get("nay", 0)
        if denom == 0:
            continue
        shares.append(c.get("yea", 0) / denom)
    if len(shares) < 2:
        return None, None
    support = min(shares)
    if support >= 0.90:
        label = "near_unanimous"
    elif support >= 0.50:
        label = "bipartisan"
    elif support >= 0.10:
        label = "cross_party"
    else:
        label = "party_line"
    return round(support, 4), label


_PARTY_NORMALIZE = {
    "Republican": "R", "Democratic": "D", "Democrat": "D",
    "Independent": "I", "Independent Democrat": "ID",
}
_POSITION_NORMALIZE = {
    "yea": "yea", "aye": "yea", "yes": "yea",
    "nay": "nay", "no": "nay",
    "present": "present", "present, giving live pair": "present",
    "not voting": "not_voting", "absent": "not_voting",
    "guilty": "yea", "not guilty": "nay",  # impeachment edge case
}


def _norm_position(raw: str | None) -> str:
    return _POSITION_NORMALIZE.get((raw or "").strip().lower(), "other")


def parse_house_rollcall(xml_bytes: bytes) -> dict[str, Any]:
    t = ET.fromstring(xml_bytes)
    meta = t.find(".//vote-metadata")
    totals: dict[str, dict[str, int]] = {}
    for tp in t.findall(".//totals-by-party"):
        party_raw = tp.findtext("party") or ""
        party = _PARTY_NORMALIZE.get(party_raw, party_raw[:1] or "?")
        totals[party] = {
            "yea": int(tp.findtext("yea-total") or 0),
            "nay": int(tp.findtext("nay-total") or 0),
            "present": int(tp.findtext("present-total") or 0),
            "not_voting": int(tp.findtext("not-voting-total") or 0),
        }
    members = []
    for rv in t.findall(".//recorded-vote"):
        leg = rv.find("legislator")
        if leg is None:
            continue
        members.append({
            "name": (leg.text or leg.get("unaccented-name") or "").strip(),
            "bioguide_id": leg.get("name-id"),
            "party": leg.get("party"),
            "state": leg.get("state"),
            "position": _norm_position(rv.findtext("vote")),
        })
    return {
        "question": _text(meta, "vote-question"),
        "result": _text(meta, "vote-result"),
        "totals": totals,
        "members": members,
    }


def parse_senate_rollcall(xml_bytes: bytes) -> dict[str, Any]:
    t = ET.fromstring(xml_bytes)
    members = []
    totals: dict[str, dict[str, int]] = {}
    for m in t.findall(".//members/member"):
        party = _text(m, "party") or "?"
        pos = _norm_position(_text(m, "vote_cast"))
        members.append({
            "name": _text(m, "member_full") or f"{_text(m, 'last_name')}",
            "lis_member_id": _text(m, "lis_member_id"),
            "party": party,
            "state": _text(m, "state"),
            "position": pos,
        })
        bucket = totals.setdefault(party, {"yea": 0, "nay": 0, "present": 0, "not_voting": 0})
        if pos in bucket:
            bucket[pos] += 1
    question = _text(t, "vote_question_text") or _text(t, "question")
    return {
        "question": question,
        "result": _text(t, "vote_result"),
        "totals": totals,
        "members": members,
    }


def fetch_rollcall(ref: dict[str, Any]) -> RollCall | None:
    """Resolve one BILLSTATUS recorded-vote ref to a full RollCall.
    Returns None when the source XML can't be fetched or parsed —
    callers keep the bare ref so coverage gaps stay visible."""
    url = ref.get("url")
    if not url:
        return None
    raw = _http_get(url)
    if raw is None:
        return None
    chamber = (ref.get("chamber") or "").strip()
    try:
        parsed = (
            parse_house_rollcall(raw) if chamber.lower() == "house"
            else parse_senate_rollcall(raw)
        )
    except ET.ParseError:
        return None

    totals = parsed["totals"]
    yea = sum(c.get("yea", 0) for c in totals.values())
    nay = sum(c.get("nay", 0) for c in totals.values())
    support, label = _bipartisan_metrics(totals)
    vote_type = classify_vote(parsed.get("question") or "")
    rc = RollCall(
        chamber=chamber,
        congress=int(ref.get("congress") or 0),
        session=int(ref.get("session") or 0),
        roll_number=int(ref.get("roll_number") or 0),
        date=ref.get("date"),
        question=parsed.get("question"),
        result=parsed.get("result"),
        vote_type=vote_type,
        source_url=url,
        totals=totals,
        yea_total=yea,
        nay_total=nay,
        bipartisan_support=support,
        bipartisan_label=label,
        # Per-member positions only for outcome-determining votes; the
        # party totals above cover amendments/procedural votes. Keeps
        # billstatus.json bounded on amendment-heavy bills (NDAAs).
        members=parsed["members"] if vote_type in ("passage", "cloture", "veto_override") else [],
    )
    return rc


# ---------------------------------------------------------------- outcome

# Ordered probes over action text. First match per action wins.
_PASSED_HOUSE = re.compile(r"passed[ /]agreed to in house|^passed house|on passage passed", re.IGNORECASE)
_PASSED_SENATE = re.compile(r"passed[ /]agreed to in senate|^passed senate", re.IGNORECASE)
_FAILED_PASSAGE = re.compile(r"failed of passage|on passage failed|failed passage", re.IGNORECASE)
_FAILED_CLOTURE = re.compile(r"cloture(?: on the )?.*not invoked|cloture motion .* rejected", re.IGNORECASE)
_VETOED = re.compile(r"vetoed by president", re.IGNORECASE)
_REPORTED = re.compile(r"reported (?:to|by)|placed on .* calendar", re.IGNORECASE)


def derive_outcome(status: dict[str, Any], rollcalls: list[RollCall]) -> dict[str, Any]:
    """Summarize a bill's fate from its BILLSTATUS record.

    outcome ∈ {enacted, vetoed, failed_passage, failed_cloture,
               passed_house_only, passed_senate_only, passed_both,
               died_in_committee, reported_no_floor_vote, pending}

    `events` keeps the per-event evidence so an agent can answer "why
    did it fail?" with dates instead of a bare label.
    """
    events: list[dict[str, str | None]] = []
    seen_events: set[tuple[str, str | None]] = set()
    passed_house = passed_senate = reported = False
    failed_passage = failed_cloture = vetoed = False

    def _add_event(event: str, date: str | None, evidence: str) -> None:
        # BILLSTATUS carries the same event from multiple source systems
        # (House floor feed + Library of Congress); keep one per day.
        key = (event, date)
        if key in seen_events:
            return
        seen_events.add(key)
        events.append({"event": event, "date": date, "evidence": evidence})

    for a in status.get("actions", []):
        text = a.get("text") or ""
        date = a.get("actionDate")
        if _PASSED_HOUSE.search(text):
            passed_house = True
            _add_event("passed_house", date, text)
        elif _PASSED_SENATE.search(text):
            passed_senate = True
            _add_event("passed_senate", date, text)
        elif _FAILED_CLOTURE.search(text):
            failed_cloture = True
            _add_event("failed_cloture", date, text)
        elif _FAILED_PASSAGE.search(text):
            failed_passage = True
            _add_event("failed_passage", date, text)
        elif _VETOED.search(text):
            vetoed = True
            _add_event("vetoed", date, text)
        elif _REPORTED.search(text):
            reported = True

    # Failed-vote evidence from the roll calls themselves (some failures
    # never produce a distinctive action string).
    for rc in rollcalls:
        result = (rc.result or "").lower()
        rc_date = (rc.date or "")[:10] or None
        if rc.vote_type == "passage" and ("fail" in result or "rejected" in result):
            failed_passage = True
            _add_event(
                "failed_passage", rc_date,
                f"{rc.chamber} roll {rc.roll_number}: {rc.result} ({rc.yea_total}-{rc.nay_total})",
            )
        if rc.vote_type == "cloture" and ("rejected" in result or "not invoked" in result):
            failed_cloture = True
            _add_event(
                "failed_cloture", rc_date,
                f"{rc.chamber} roll {rc.roll_number}: {rc.result} ({rc.yea_total}-{rc.nay_total})",
            )

    laws = status.get("laws") or []
    congress_closed = status.get("congress") in CLOSED_CONGRESSES

    if laws:
        outcome = "enacted"
    elif vetoed:
        outcome = "vetoed"
    elif failed_passage and congress_closed:
        outcome = "failed_passage"
    elif failed_cloture and congress_closed:
        outcome = "failed_cloture"
    elif passed_house and passed_senate:
        outcome = "passed_both" if not congress_closed else "died_after_passing_both"
    elif passed_house:
        outcome = "passed_house_only" if not congress_closed else "died_after_passing_house"
    elif passed_senate:
        outcome = "passed_senate_only" if not congress_closed else "died_after_passing_senate"
    elif not congress_closed:
        outcome = "pending"
    elif reported:
        outcome = "reported_no_floor_vote"
    else:
        outcome = "died_in_committee"

    public_law = None
    if laws:
        first = laws[0]
        if first.get("number"):
            prefix = "PL" if (first.get("type") or "").startswith("Public") else "PVTL"
            public_law = f"{prefix} {first['number']}"

    return {
        "outcome": outcome,
        "public_law": public_law,
        "events": events,
        "latest_action": status.get("latest_action"),
    }


# -------------------------------------------------------------- top level

def enrich_bill_dir(
    bill_dir: Path,
    *,
    force: bool = False,
    fetch_votes: bool = True,
) -> str:
    """Write billstatus.json into one corpus bill directory.

    Returns a status string: 'added' | 'skipped-exists' | 'no-billstatus'
    | 'no-metadata'. Never touches metadata.json or bill.xml.
    """
    out_path = bill_dir / "billstatus.json"
    if out_path.exists() and not force:
        return "skipped-exists"
    meta_path = bill_dir / "metadata.json"
    if not meta_path.exists():
        return "no-metadata"
    meta = json.loads(meta_path.read_text())
    congress, bill_type, number = meta["congress"], meta["bill_type"], meta["bill_number"]

    raw = fetch_billstatus_xml(congress, bill_type, number)
    if raw is None:
        return "no-billstatus"
    status = parse_billstatus(raw)

    rollcalls: list[RollCall] = []
    unresolved_refs: list[dict[str, Any]] = []
    if fetch_votes:
        for ref in status["recorded_vote_refs"]:
            rc = fetch_rollcall(ref)
            if rc is not None:
                rollcalls.append(rc)
            else:
                unresolved_refs.append(ref)

    outcome = derive_outcome(status, rollcalls)

    payload = {
        "bill_id": meta["bill_id"],
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "source": BILLSTATUS_URL.format(congress=congress, bill_type=bill_type, number=number),
        "title": status["title"],
        "policy_area": status["policy_area"],
        "subjects": status["subjects"],
        "sponsor": status["sponsor"],
        "cosponsors": status["cosponsors"],
        "actions": status["actions"],
        "outcome": outcome,
        "votes": [rc.to_json() for rc in rollcalls],
        "unresolved_vote_refs": unresolved_refs,
    }
    out_path.write_text(json.dumps(payload, indent=2) + "\n")
    return "added"
