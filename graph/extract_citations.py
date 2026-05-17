"""Extract citation edges from bill XML.

PR2 scope: USC and USC-chapter `<external-xref>` elements only.

Coverage notes (v1 corpus):
  - 985 total <external-xref> elements: 866 USC, 74 public-law, 44
    usc-chapter, 1 usc-appendix.
  - Public Law citations are skipped — no PublicLaw node type in the
    schema yet. Recorded as a known gap.
  - The 2 USLM-namespace bills (118-hr-2670, 118-hr-5009) have 0
    <external-xref> elements; they use USLM <ref> with href attributes
    instead. PR2.1 will add USLM ref extraction; PR2 prioritizes the
    pre-USLM dialect that covers 189/191 bills.

The extraction is mechanical (derivation='mechanical', confidence=1.0):
we copy the bill's own parsable-cite attribute. No NLP, no LLM, no
inferred edges.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

# Locale-namespace markers we may need to strip from tags.
USLM_NS = "{http://schemas.gpo.gov/xml/uslm}"

# Container-like elements (section-tier and above) — copied from
# index/parse_uslm.py. The walker treats these as scope boundaries:
# entering one pushes its xml_id on the section stack.
CONTAINER_LEVELS = frozenset((
    "division", "title", "subtitle", "part", "subpart", "chapter", "subchapter",
    "section", "subsection", "paragraph", "subparagraph", "clause", "subclause",
    "item", "subitem",
))

# legal-doc values we recognize → human-readable bucket
SUPPORTED_LEGAL_DOCS = {"usc", "usc-chapter", "usc-appendix"}

# Wrapper elements whose subtree is *not* part of the bill's own section
# hierarchy. <quoted-block> in particular contains amendatory payload —
# the text being inserted into a target statute. Citations inside it
# belong to the target document, not to a Section of this bill, and
# parse_uslm.py correctly skips them. PR4 will surface those citations
# back as part of AmendmentOperation.
SKIP_SUBTREE = {"quoted-block"}


@dataclass(frozen=True)
class ExternalCitation:
    """One Section → StatuteSection edge worth of data.

    `source_section_id` follows the URN scheme used in graph/build_kuzu.py:
    `bill:us/{congress}/{bill_type}/{bill_number}::{xml_id}`. It identifies
    the Section node that contains the <external-xref>.

    `target_statute_section_id` is the URN-style StatuteSection ID, e.g.
    `statute:us/usc/15/9401`. PR2 does not parse subdivisions out of the
    raw text — parsable-cite is section-level only.
    """
    source_section_id: str
    target_statute_section_id: str
    target_statute_id: str          # parent statute (e.g. statute:us/usc/15)
    target_code: str                # 'usc'
    target_title: str               # '15'
    target_section: str             # '9401'
    target_canonical_citation: str  # '15 U.S.C. 9401'
    raw_text: str
    xml_ref_id: str | None
    legal_doc: str                  # 'usc' | 'usc-chapter' | 'usc-appendix'


def _local(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag


_PARSABLE_USC_RE = re.compile(r"^usc(?:-chapter|-appendix)?/(?P<title>[^/]+)/(?P<section>.+)$")


def _parse_cite(parsable_cite: str, legal_doc: str) -> tuple[str, str, str, str] | None:
    """Parse `usc/15/9401` → ('usc', '15', '9401', canonical citation).

    Returns None for citation forms we can't structurally parse (FTCA,
    pl/..., etc.).
    """
    m = _PARSABLE_USC_RE.match(parsable_cite)
    if not m:
        return None
    title = m.group("title")
    section = m.group("section")
    # Trim trailing slashes / artifacts
    section = section.strip("/")
    if not title or not section:
        return None
    canonical = f"{title} U.S.C. {section}"
    if legal_doc == "usc-chapter":
        canonical = f"{title} U.S.C. ch. {section}"
    elif legal_doc == "usc-appendix":
        canonical = f"{title} U.S.C. App. {section}"
    return ("usc", title, section, canonical)


def statute_section_urn(code: str, title: str, section: str) -> str:
    return f"statute:us/{code}/{title}/{section}"


def statute_urn(code: str, title: str) -> str:
    return f"statute:us/{code}/{title}"


def _element_text(elem: ET.Element) -> str:
    """Verbatim text content of an element, descendants included."""
    parts: list[str] = []
    if elem.text:
        parts.append(elem.text)
    for c in elem:
        parts.append(_element_text(c))
        if c.tail:
            parts.append(c.tail)
    return re.sub(r"\s+", " ", " ".join(p for p in parts if p)).strip()


def _walk(
    elem: ET.Element,
    *,
    bill_id: str,
    section_stack: list[str],
    out: list[ExternalCitation],
) -> None:
    """Recursively walk, tracking the innermost section context."""
    local = _local(elem.tag)
    pushed = False

    if local in SKIP_SUBTREE:
        return  # do not descend; this subtree is not part of the bill's
                # own section hierarchy

    if local in CONTAINER_LEVELS:
        xml_id = elem.get("id")
        if xml_id:
            section_stack.append(xml_id)
            pushed = True

    if local == "external-xref":
        legal_doc = elem.get("legal-doc", "")
        parsable_cite = elem.get("parsable-cite", "")
        if legal_doc in SUPPORTED_LEGAL_DOCS and parsable_cite:
            parsed = _parse_cite(parsable_cite, legal_doc)
            if parsed is not None and section_stack:
                code, title, section, canonical = parsed
                source_xml_id = section_stack[-1]
                source_section_id = f"{bill_id}::{source_xml_id}"
                out.append(ExternalCitation(
                    source_section_id=source_section_id,
                    target_statute_section_id=statute_section_urn(code, title, section),
                    target_statute_id=statute_urn(code, title),
                    target_code=code,
                    target_title=title,
                    target_section=section,
                    target_canonical_citation=canonical,
                    raw_text=_element_text(elem)[:300],
                    xml_ref_id=elem.get("id"),
                    legal_doc=legal_doc,
                ))

    for child in elem:
        _walk(child, bill_id=bill_id, section_stack=section_stack, out=out)

    if pushed:
        section_stack.pop()


_BODY_CANDIDATES = ("legis-body", "main", "resolution-body")


def _find_body(root: ET.Element) -> ET.Element | None:
    """Return the first body element parse_uslm.py would walk.

    Some bills (e.g. 118-s-4394) contain TWO <legis-body> elements — an
    earlier and a later version of the bill text. parse_uslm.py returns
    the first match it finds; if the citation extractor walked the whole
    document, it would emit citations whose source Section nodes don't
    exist in the graph. We mirror parse_uslm's behavior exactly.

    Fixing parse_uslm to handle multiple <legis-body> elements is a
    bibliographic-spine concern, tracked separately.
    """
    for name in _BODY_CANDIDATES:
        for elem in root.iter():
            if _local(elem.tag) == name:
                return elem
    return None


def extract_external_citations(xml_path: Path, *, bill_id: str) -> list[ExternalCitation]:
    """Walk one bill XML, return all USC `<external-xref>` edges.

    `bill_id` is the URN-style identifier (`bill:us/119/hr/1736`); it's
    used to construct source_section_ids that match the Section nodes in
    the Kùzu graph.
    """
    tree = ET.parse(xml_path)
    body = _find_body(tree.getroot())
    if body is None:
        return []
    out: list[ExternalCitation] = []
    _walk(body, bill_id=bill_id, section_stack=[], out=out)
    return out
