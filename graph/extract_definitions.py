"""Extract DefinedTerm nodes and DEFINES / BY_REFERENCE edges from bill XML.

PR3 scope:
  - Find Definitions sections (container with heading like 'Definitions',
    'Definition', 'Definitions and rules of construction', ...).
  - For each child container, extract one DefinedTerm:
      * surface_form from the first <quote> or <term> in the child's text
      * definition_text = full recursive text of the child
      * definition_type ∈ {direct, by_reference}
      * if by_reference and an <external-xref legal-doc='usc'> appears in
        the definition, link DefinedTerm → StatuteSection via
        BY_REFERENCE.
  - Scope is signaled by the parent's 'In this [section|title|Act]:' hint.

Deferred to PR3.1:
  - Use-site resolution (RESOLVED_TO / UnresolvedTermUse). Walking body
    text to match defined terms is a different problem from XML walking
    and merits its own pass with explicit fail-closed semantics.
  - Public-Law by_reference targets (no PublicLaw node type yet).
  - USLM <ref href='...'> handling (covers 2 bills).
"""
from __future__ import annotations

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

# Subtree skip list (matches extract_citations.py).
SKIP_SUBTREE = {"quoted-block"}

_BODY_CANDIDATES = ("legis-body", "main", "resolution-body")

# A heading qualifies as a Definitions container if it starts with one of
# these tokens. Trailing words ("Definitions and rules of construction",
# "Definitions; references") are accepted.
_DEFINITIONS_HEADING_RE = re.compile(r"^\s*Definitions?\b", re.IGNORECASE)

# Hint text that signals scope. The hint usually appears as a child <text>
# element directly under the Definitions container.
_SCOPE_HINT_RES = [
    (re.compile(r"\bIn this Act\b", re.IGNORECASE), "bill_local"),
    (re.compile(r"\bIn this title\b", re.IGNORECASE), "title_local"),
    (re.compile(r"\bIn this subtitle\b", re.IGNORECASE), "title_local"),
    (re.compile(r"\bIn this section\b", re.IGNORECASE), "section_local"),
    (re.compile(r"\bIn this part\b", re.IGNORECASE), "section_local"),
]

# Detect by-reference definitions. The canonical formulation is "has the
# meaning given such term in ..." or "has the meaning given the term ...".
_BY_REFERENCE_RES = [
    re.compile(r"\bhas the meaning given (?:such term|the term|that term|to such term)\b", re.IGNORECASE),
    re.compile(r"\bhas the same meaning as\b", re.IGNORECASE),
    re.compile(r"\bshall have the meaning given (?:such term|the term)\b", re.IGNORECASE),
]


@dataclass(frozen=True)
class DefinedTermRow:
    """One DefinedTerm node + its DEFINES / BY_REFERENCE edges worth of data."""
    defined_term_id: str
    surface_form: str
    defining_section_id: str       # the child container (e.g. paragraph) that holds this term
    container_section_id: str      # the Definitions section/subsection itself
    scope: str                     # 'section_local' | 'title_local' | 'bill_local'
    definition_text: str
    definition_type: str           # 'direct' | 'by_reference'
    by_reference_statute_section_id: str | None  # target StatuteSection.statute_section_id
    by_reference_canonical: str | None


def _local(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag


def _slug(s: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "_", s.lower()).strip("_")
    return s or "unnamed"


def _find_body(root: ET.Element) -> ET.Element | None:
    for name in _BODY_CANDIDATES:
        for elem in root.iter():
            if _local(elem.tag) == name:
                return elem
    return None


def _child_by_name(elem: ET.Element, names: tuple[str, ...]) -> ET.Element | None:
    for c in elem:
        if _local(c.tag) in names:
            return c
    return None


def _full_text(elem: ET.Element) -> str:
    parts: list[str] = []
    if elem.text:
        parts.append(elem.text)
    for c in elem:
        if _local(c.tag) in SKIP_SUBTREE:
            if c.tail:
                parts.append(c.tail)
            continue
        parts.append(_full_text(c))
        if c.tail:
            parts.append(c.tail)
    return re.sub(r"\s+", " ", " ".join(p for p in parts if p)).strip()


def _direct_text(elem: ET.Element) -> str:
    """Text of this element plus immediate non-container children (no recursion into containers)."""
    parts: list[str] = []
    if elem.text:
        parts.append(elem.text)
    for c in elem:
        local = _local(c.tag)
        if local in CONTAINER_LEVELS or local in SKIP_SUBTREE:
            if c.tail:
                parts.append(c.tail)
            continue
        parts.append(_full_text(c))
        if c.tail:
            parts.append(c.tail)
    return re.sub(r"\s+", " ", " ".join(p for p in parts if p)).strip()


def _is_definitions_container(elem: ET.Element) -> bool:
    if _local(elem.tag) not in CONTAINER_LEVELS:
        return False
    header = _child_by_name(elem, ("header", "heading"))
    if header is None:
        return False
    htext = (_full_text(header) or "").strip()
    return bool(_DEFINITIONS_HEADING_RE.match(htext))


def _container_scope(elem: ET.Element) -> str:
    """Inspect direct text children for an 'In this X:' scope hint.

    Defaults to 'section_local' if no hint is present (the most common
    and the most conservative — won't widen scope without evidence).
    """
    text = _direct_text(elem)
    for pat, scope in _SCOPE_HINT_RES:
        if pat.search(text):
            return scope
    return "section_local"


def _extract_surface_form(child: ET.Element, header_text: str) -> str:
    """Pull the defined term's surface form.

    Priority:
      1. First <term> element inside (USLM/legacy)
      2. First <quote> element inside (legacy convention)
      3. Fall back to the child's header text
    """
    for tag in ("term", "quote"):
        for sub in child.iter():
            if _local(sub.tag) == tag:
                t = _full_text(sub)
                if t:
                    return t
    return header_text.strip()


def _classify_by_reference(full_text: str) -> bool:
    return any(p.search(full_text) for p in _BY_REFERENCE_RES)


def _first_usc_xref_in(elem: ET.Element) -> ET.Element | None:
    """Locate the first <external-xref legal-doc='usc*'> inside elem (or any descendant).

    Skips quoted-block subtrees (amendatory payload — not the bill's
    own statement).
    """
    for sub in elem.iter():
        local = _local(sub.tag)
        if local == "external-xref":
            ldoc = sub.get("legal-doc", "")
            if ldoc.startswith("usc"):
                # Confirm it's not inside a quoted-block by walking back up.
                # ElementTree doesn't expose parent pointers, so this is a
                # best-effort check — in practice quoted-blocks are rare
                # inside Definitions containers.
                return sub
    return None


def _statute_section_urn_from_xref(xref: ET.Element) -> tuple[str, str] | None:
    """Return (statute_section_id, canonical_citation) for a USC xref."""
    pc = xref.get("parsable-cite", "")
    m = re.match(r"^usc(?:-chapter|-appendix)?/([^/]+)/(.+)$", pc)
    if not m:
        return None
    title, section = m.groups()
    section = section.strip("/")
    if not title or not section:
        return None
    legal_doc = xref.get("legal-doc", "usc")
    sid = f"statute:us/{legal_doc}/{title}/{section}".replace("statute:us/usc-chapter/", "statute:us/usc/")
    # Normalize: usc-chapter/usc-appendix still share the statute_section_id
    # namespace by parsing back through the canonical form. We keep the
    # canonical_citation distinct for human readability.
    sid_norm = f"statute:us/usc/{title}/{section}"
    canonical = f"{title} U.S.C. {section}"
    if legal_doc == "usc-chapter":
        canonical = f"{title} U.S.C. ch. {section}"
    elif legal_doc == "usc-appendix":
        canonical = f"{title} U.S.C. App. {section}"
    return (sid_norm, canonical)


def _defined_term_urn(container_id: str, surface_form: str) -> str:
    """Stable URN: {container_section_id}::term/{slug}."""
    return f"{container_id}::term/{_slug(surface_form)}"


def _walk_defs(
    elem: ET.Element,
    *,
    bill_id: str,
    out: list[DefinedTermRow],
) -> None:
    """Find every Definitions container in the subtree and extract its terms."""
    local = _local(elem.tag)
    if local in SKIP_SUBTREE:
        return

    if _is_definitions_container(elem):
        container_xml_id = elem.get("id")
        if container_xml_id:
            container_section_id = f"{bill_id}::{container_xml_id}"
            scope = _container_scope(elem)
            # Each child container (paragraph or section, depending on
            # the level of the Definitions block) is one defined term.
            for child in elem:
                clocal = _local(child.tag)
                if clocal not in CONTAINER_LEVELS:
                    continue
                child_xml_id = child.get("id")
                if not child_xml_id:
                    continue
                header = _child_by_name(child, ("header", "heading"))
                header_text = _full_text(header) if header is not None else ""
                surface_form = _extract_surface_form(child, header_text)
                if not surface_form:
                    continue
                definition_text = _full_text(child)
                # Strip the surface_form + leading enum noise from the
                # start of the definition for cleanliness; harmless if
                # the slice doesn't match.
                by_ref = _classify_by_reference(definition_text)
                br_target_sid = None
                br_canonical = None
                if by_ref:
                    xref = _first_usc_xref_in(child)
                    if xref is not None:
                        parsed = _statute_section_urn_from_xref(xref)
                        if parsed is not None:
                            br_target_sid, br_canonical = parsed
                out.append(DefinedTermRow(
                    defined_term_id=_defined_term_urn(container_section_id, surface_form),
                    surface_form=surface_form,
                    defining_section_id=f"{bill_id}::{child_xml_id}",
                    container_section_id=container_section_id,
                    scope=scope,
                    definition_text=definition_text[:4000],  # cap for storage
                    definition_type="by_reference" if by_ref else "direct",
                    by_reference_statute_section_id=br_target_sid,
                    by_reference_canonical=br_canonical,
                ))
        # Don't recurse — nested Definitions containers are rare and a
        # follow-up concern.
        return

    for child in elem:
        _walk_defs(child, bill_id=bill_id, out=out)


def extract_defined_terms(xml_path: Path, *, bill_id: str) -> list[DefinedTermRow]:
    """Walk a bill XML and return all DefinedTerm rows.

    `bill_id` is URN-form (`bill:us/119/hr/1736`); used to construct
    defining_section_id values that match Section nodes in Kùzu.
    """
    tree = ET.parse(xml_path)
    body = _find_body(tree.getroot())
    if body is None:
        return []
    out: list[DefinedTermRow] = []
    _walk_defs(body, bill_id=bill_id, out=out)
    return out
