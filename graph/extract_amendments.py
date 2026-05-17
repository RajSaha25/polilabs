"""Extract AmendmentOperation reified nodes + AMENDS + TARGETS edges from bill XML.

PR4 scope (per the design decision in schema_design.md §4 + §9.3):
  - One AmendmentOperation per <quoted-block> element. quoted-block is
    the structural marker for "here is text being inserted/replaced."
  - operation_type detected via keyword classification on the surrounding
    text ('by striking', 'by inserting', 'by adding at the end', etc.).
  - target_locator: the nearest enclosing USC <external-xref> (walking
    up the section hierarchy until we find one outside any quoted-block).
  - after_text = the verbatim quoted-block content.
  - before_text = extracted from "by striking '<quote>X</quote>'" when
    present, else None.
  - target_text_unverified = True for every operation in v1 — we do not
    yet ingest OLRC USC text, so we cannot verify that the operation's
    before_text actually matches what the statute says today.

Out of scope (later refinement):
  - Non-quoted-block amendments ('is repealed', narrative-only).
  - Public-Law target amendments (no PublicLaw node type yet).
  - Internal-bill amendments (Section X amends Section Y in the same bill).
  - Multi-target operations in one paragraph (rare).
  - Structured target_locator parsing of "(b)(2)" into enum_path —
    for now we record the operation text and target the statute section
    as a whole.
"""
from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

USLM_NS = "{http://schemas.gpo.gov/xml/uslm}"

CONTAINER_LEVELS = frozenset((
    "division", "title", "subtitle", "part", "subpart", "chapter", "subchapter",
    "section", "subsection", "paragraph", "subparagraph", "clause", "subclause",
    "item", "subitem",
))

_BODY_CANDIDATES = ("legis-body", "main", "resolution-body")


# Operation classification — checked in order, first match wins.
# Patterns are matched against the text of the *immediate paragraph that
# contains the quoted-block*, walking up to the section if needed.
_OPERATION_PATTERNS = [
    (re.compile(r"\bby striking\b.*\band inserting\b", re.IGNORECASE), "strike_and_insert"),
    (re.compile(r"\bby inserting (?:after|before|in)\b", re.IGNORECASE), "insert"),
    (re.compile(r"\bby adding (?:at the end )?the following\b", re.IGNORECASE), "add_at_end"),
    (re.compile(r"\bby amending\b.*\bto read as follows\b", re.IGNORECASE), "replace"),
    (re.compile(r"\bto read as follows\b", re.IGNORECASE), "replace"),
    (re.compile(r"\bby striking\b", re.IGNORECASE), "strike"),
    (re.compile(r"\bby redesignating\b", re.IGNORECASE), "redesignate"),
    (re.compile(r"\bis repealed\b", re.IGNORECASE), "repeal"),
    (re.compile(r"\bby inserting\b", re.IGNORECASE), "insert"),
]

# "by striking '<quote>X</quote>'" — capture X as before_text.
_BEFORE_TEXT_RES = [
    re.compile(r"by striking (?:the (?:phrase|word|term|paragraph))?\s*[“\"]([^”\"]+)[”\"]", re.IGNORECASE),
    re.compile(r"by striking (?:the (?:phrase|word|term|paragraph))?\s*<quote>([^<]+)</quote>", re.IGNORECASE),
]


@dataclass(frozen=True)
class AmendmentRow:
    amendment_id: str
    source_section_id: str
    operation_type: str
    operation_text: str          # the prose surrounding the operation (≤500 chars)
    target_statute_section_id: str | None
    target_canonical_citation: str | None
    target_locator_json: str     # JSON {"code": "usc", "title": "5", "section": "552", "subdivisions": []}
    before_text: str | None
    after_text: str              # verbatim quoted-block content
    xml_ref_id: str | None


def _local(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag


def _find_body(root: ET.Element) -> ET.Element | None:
    for name in _BODY_CANDIDATES:
        for elem in root.iter():
            if _local(elem.tag) == name:
                return elem
    return None


def _full_text_skip_quoted_blocks(elem: ET.Element) -> str:
    """Recursive text content, but DO NOT descend into <quoted-block>."""
    parts: list[str] = []
    if elem.text:
        parts.append(elem.text)
    for c in elem:
        if _local(c.tag) == "quoted-block":
            if c.tail:
                parts.append(c.tail)
            continue
        parts.append(_full_text_skip_quoted_blocks(c))
        if c.tail:
            parts.append(c.tail)
    return re.sub(r"\s+", " ", " ".join(p for p in parts if p)).strip()


def _quoted_block_text(elem: ET.Element) -> str:
    """Verbatim text content of a quoted-block, descendants included."""
    parts: list[str] = []
    if elem.text:
        parts.append(elem.text)
    for c in elem:
        parts.append(_quoted_block_text(c))
        if c.tail:
            parts.append(c.tail)
    return re.sub(r"\s+", " ", " ".join(p for p in parts if p)).strip()


def _classify_operation(text: str) -> str:
    for pat, op in _OPERATION_PATTERNS:
        if pat.search(text):
            return op
    return "other"


def _extract_before_text(text: str) -> str | None:
    for pat in _BEFORE_TEXT_RES:
        m = pat.search(text)
        if m:
            return m.group(1).strip()
    return None


_USC_PARSABLE_RE = re.compile(r"^usc(?:-chapter|-appendix)?/([^/]+)/(.+)$")


def _statute_target_from_xref(xref: ET.Element) -> tuple[str, str, dict] | None:
    pc = xref.get("parsable-cite", "")
    m = _USC_PARSABLE_RE.match(pc)
    if not m:
        return None
    title, section = m.groups()
    section = section.strip("/")
    if not title or not section:
        return None
    sid = f"statute:us/usc/{title}/{section}"
    canonical = f"{title} U.S.C. {section}"
    locator = {"code": "usc", "title": title, "section": section, "subdivisions": []}
    return (sid, canonical, locator)


def _find_target_xref(ancestors: list[ET.Element]) -> ET.Element | None:
    """Walk up the ancestor chain looking for a USC <external-xref>
    that's outside any quoted-block. Returns the closest such xref."""
    for a in reversed(ancestors):
        # Scan immediate children + descendants of `a` — but skip subtrees
        # under quoted-block elements.
        def _scan(elem: ET.Element) -> ET.Element | None:
            for c in elem:
                local = _local(c.tag)
                if local == "quoted-block":
                    continue
                if local == "external-xref":
                    ldoc = c.get("legal-doc", "")
                    if ldoc.startswith("usc"):
                        return c
                result = _scan(c)
                if result is not None:
                    return result
            return None
        found = _scan(a)
        if found is not None:
            return found
    return None


def _enclosing_section_id(ancestors: list[ET.Element], bill_id: str) -> str | None:
    """Closest ancestor with a container-level tag + xml_id."""
    for a in reversed(ancestors):
        if _local(a.tag) in CONTAINER_LEVELS and a.get("id"):
            return f"{bill_id}::{a.get('id')}"
    return None


def _walk(
    elem: ET.Element,
    *,
    bill_id: str,
    ancestors: list[ET.Element],
    out: list[AmendmentRow],
    counter: list[int],
) -> None:
    local = _local(elem.tag)
    if local == "quoted-block":
        # We found an amendment payload. Synthesize a row.
        source_section_id = _enclosing_section_id(ancestors, bill_id)
        if source_section_id is None:
            return  # quoted-block outside any section — skip
        target_xref = _find_target_xref(ancestors)
        target_sid: str | None = None
        target_canon: str | None = None
        locator: dict
        if target_xref is not None:
            parsed = _statute_target_from_xref(target_xref)
            if parsed is not None:
                target_sid, target_canon, locator = parsed
            else:
                locator = {"code": "unknown", "raw": target_xref.get("parsable-cite", "")}
        else:
            locator = {"code": "unknown", "raw": None}

        # Surrounding prose: text of the closest enclosing paragraph/section
        # (skipping descent into the quoted-block itself).
        op_text = ""
        for a in reversed(ancestors):
            if _local(a.tag) in CONTAINER_LEVELS:
                op_text = _full_text_skip_quoted_blocks(a)
                if op_text:
                    break
        op_text = op_text[:500]
        operation_type = _classify_operation(op_text)
        before_text = _extract_before_text(op_text)
        after_text = _quoted_block_text(elem)[:4000]
        counter[0] += 1
        amend_id = f"{source_section_id}::amend/{counter[0]}"
        out.append(AmendmentRow(
            amendment_id=amend_id,
            source_section_id=source_section_id,
            operation_type=operation_type,
            operation_text=op_text,
            target_statute_section_id=target_sid,
            target_canonical_citation=target_canon,
            target_locator_json=json.dumps(locator),
            before_text=before_text,
            after_text=after_text,
            xml_ref_id=elem.get("id"),
        ))
        return  # do not descend into quoted-block

    for child in elem:
        _walk(child, bill_id=bill_id, ancestors=ancestors + [elem], out=out, counter=counter)


def extract_amendments(xml_path: Path, *, bill_id: str) -> list[AmendmentRow]:
    """Walk one bill XML, return all AmendmentOperation rows.

    `bill_id` is URN-form (`bill:us/119/hr/1736`).
    """
    tree = ET.parse(xml_path)
    body = _find_body(tree.getroot())
    if body is None:
        return []
    out: list[AmendmentRow] = []
    counter = [0]
    _walk(body, bill_id=bill_id, ancestors=[], out=out, counter=counter)
    return out
