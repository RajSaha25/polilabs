"""Parse bill XML (USLM and pre-USLM) into flat section rows.

Two input formats coexist in the v1 corpus:

1. **Pre-USLM** (188 of 191 bills) — `<bill>` root, no namespace, body is
   `<legis-body>`. Each container has `<enum>` (number), `<header>` (heading),
   and `<text>` (direct content). Sub-containers nested: section >
   subsection > paragraph > subparagraph > clause > subclause.

2. **USLM** (2 bills + 1 resolution) — `<bill xmlns="http://schemas.gpo.gov/xml/uslm">`,
   namespaced. Containers use `<num>` (number), `<heading>` (heading), and
   `<content>` for direct text. Higher groupings: division, title, subtitle.

Output: a list of `SectionRow` dataclasses ready to insert into the
`sections` table. Parent links are built during the walk; canonical
citation strings are assembled from the enum stack plus the bill citation.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

USLM_NS = "{http://schemas.gpo.gov/xml/uslm}"

# Section-like container levels, in canonical hierarchy order.
CONTAINER_LEVELS = (
    "division", "title", "subtitle", "part", "subpart", "chapter", "subchapter",
    "section", "subsection", "paragraph", "subparagraph", "clause", "subclause",
    "item", "subitem",
)

# Transparent wrappers — not section rows themselves, but bills wrap structured
# inserted text (e.g. "is amended by inserting after section X the following:")
# in these. The wrapper's container descendants should be hoisted into the
# surrounding tree so they parse as their own structured rows instead of being
# stringified into a flat blob on the parent.
STRUCTURAL_WRAPPERS = ("quoted-block", "quoted-content")


@dataclass
class SectionRow:
    section_id: str
    bill_id: str
    parent_section_id: str | None
    level: str
    enum: str | None
    heading: str | None
    text_self: str
    text_full: str
    canonical_citation: str
    ordinal: int
    xml_id: str | None


def detect_format(xml_path: Path) -> str:
    """Return 'uslm' or 'pre-uslm' based on root namespace."""
    head = xml_path.read_text(errors="replace")[:500]
    return "uslm" if "schemas.gpo.gov/xml/uslm" in head else "pre-uslm"


def _localname(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag


def _text_clean(s: str | None) -> str:
    """Collapse runs of spaces/tabs but preserve newlines.

    Newlines carry meaning in our text fields: the frontend's verbatimHtml
    turns them into <br/>. The table renderer (_table_to_text) emits one
    newline per row, and _full_text_of joins child segments with newlines.
    Both rely on us not collapsing them here.
    """
    if not s:
        return ""
    # Collapse spaces/tabs but keep \n. Also collapse multiple blank lines.
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r" *\n *", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def _text_clean_inline(s: str | None) -> str:
    """Full whitespace collapse for one-line fields (enum, heading)."""
    if not s:
        return ""
    return re.sub(r"\s+", " ", s).strip()


# Strip USLM/legacy noise from enum strings so citations are clean.
# 'SECTION 1' -> '1', 'SEC. 2.' -> '2', '(a)' -> 'a', '1.' -> '1'.
_ENUM_PREFIX_RE = re.compile(r"^\s*(SECTION|Section|SEC\.?|Sec\.?|§)\s*", re.IGNORECASE)


def _normalize_enum(raw: str) -> str:
    e = _ENUM_PREFIX_RE.sub("", raw or "").strip()
    e = e.rstrip(".").strip()
    # Drop a single set of wrapping parens but keep them in the citation builder
    if len(e) >= 2 and e.startswith("(") and e.endswith(")"):
        e = e[1:-1].strip()
    return e


def _bill_short_citation(congress: int, bill_type: str, bill_number: int) -> str:
    """Format bill citation: 'H.R. 1234, 119th Cong.' / 'S. 567, 118th Cong.'"""
    suffix_map = {
        "hr": "H.R.", "s": "S.",
        "hjres": "H.J. Res.", "sjres": "S.J. Res.",
        "hconres": "H. Con. Res.", "sconres": "S. Con. Res.",
        "hres": "H. Res.", "sres": "S. Res.",
    }
    bt = suffix_map.get(bill_type, bill_type.upper())
    ordinal_suffix = "th" if 10 <= congress % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(congress % 10, "th")
    return f"{bt} {bill_number}, {congress}{ordinal_suffix} Cong."


_META_TAGS = {"enum", "num", "header", "heading"}


def _has_container_descendant(elem: ET.Element) -> bool:
    """True if elem has any descendant tagged as a section-level container."""
    container_tags = set(CONTAINER_LEVELS)
    for d in elem.iter():
        if _localname(d.tag) in container_tags:
            return True
    return False


def _iter_container_children(elem: ET.Element):
    """Yield direct container children, descending through structural wrappers.

    Treats <quoted-block> and friends as transparent: a <section> inside a
    <quoted-block> is reported as if it were a direct child of elem.
    """
    container_tags = set(CONTAINER_LEVELS)
    wrapper_tags = set(STRUCTURAL_WRAPPERS)
    for child in elem:
        local = _localname(child.tag)
        if local in container_tags:
            yield child
        elif local in wrapper_tags:
            yield from _iter_container_children(child)


def _direct_text_of(elem: ET.Element, format: str) -> str:
    """Verbatim direct text of an element — its body content only.

    Excludes nested container-level children (those become their own section
    rows) and also excludes the element's own enum/header/num/heading
    children (those are stored in separate columns).

    Wrappers (<quoted-block>, <quoted-content>) that contain container
    descendants are skipped here too: their containers will be hoisted out
    as separate section rows, so including their text would duplicate it.
    Wrappers with no containers inside (rare — plain text amendments) keep
    their old leaf-stringification behavior.
    """
    pieces: list[str] = []
    container_tags = set(CONTAINER_LEVELS)
    wrapper_tags = set(STRUCTURAL_WRAPPERS)
    if elem.text:
        pieces.append(elem.text)
    for child in elem:
        local = _localname(child.tag)
        if local in container_tags:
            if child.tail:
                pieces.append(child.tail)
            continue
        if local in wrapper_tags and _has_container_descendant(child):
            if child.tail:
                pieces.append(child.tail)
            continue
        if local in _META_TAGS:
            if child.tail:
                pieces.append(child.tail)
            continue
        pieces.append(_stringify_leaf(child))
        if child.tail:
            pieces.append(child.tail)
    return _text_clean(" ".join(pieces))


def _stringify_leaf(elem: ET.Element) -> str:
    """Render a non-container element as plain text, recursing into its kids."""
    local = _localname(elem.tag)
    if local == "table":
        return _table_to_text(elem)
    out: list[str] = []
    if elem.text:
        out.append(elem.text)
    for c in elem:
        if _localname(c.tag) in ("br", "p"):
            out.append("\n")
        out.append(_stringify_leaf(c))
        if c.tail:
            out.append(c.tail)
    return " ".join(s for s in out if s)


def _table_to_text(table_elem: ET.Element) -> str:
    """Render an xhtml:table as line-per-row plain text with ' | ' between cells.

    Appropriations bills (NDAA et al.) carry their funding line-items as huge
    embedded HTML tables. Without this, the entire table gets stringified into
    one undifferentiated stream of dollar amounts — the wall-of-text bug.
    """
    rows: list[str] = []
    for tr in table_elem.iter():
        if _localname(tr.tag) != "tr":
            continue
        cells: list[str] = []
        for child in tr:
            if _localname(child.tag) in ("td", "th"):
                txt = " ".join(child.itertext()).strip()
                txt = re.sub(r"\s+", " ", txt)
                cells.append(txt)
        if any(cells):
            rows.append(" | ".join(cells))
    return "\n".join(rows)


def _full_text_of(elem: ET.Element, format: str) -> str:
    """Recursive accumulation: include all descendant container text too."""
    pieces: list[str] = []
    self_text = _direct_text_of(elem, format)
    if self_text:
        pieces.append(self_text)
    for child in _iter_container_children(elem):
        enum = _child_text(child, ("enum", "num"))
        head = _child_text(child, ("header", "heading"))
        descendant = _full_text_of(child, format)
        chunk_parts: list[str] = []
        if enum:
            chunk_parts.append(enum.strip())
        if head:
            chunk_parts.append(head.strip())
        if descendant:
            chunk_parts.append(descendant)
        pieces.append(" ".join(chunk_parts))
    return _text_clean("\n".join(p for p in pieces if p))


def _child_text(elem: ET.Element, names: tuple[str, ...]) -> str | None:
    for c in elem:
        if _localname(c.tag) in names:
            return _stringify_leaf(c)
    return None


def _find_body(root: ET.Element, format: str) -> ET.Element | None:
    """Locate the body that contains section-like elements."""
    candidates = ("legis-body", "main", "resolution-body")
    for name in candidates:
        for elem in root.iter():
            if _localname(elem.tag) == name:
                return elem
    return root  # fall back: scan whole document


def _walk(
    elem: ET.Element,
    *,
    bill_id: str,
    bill_citation: str,
    enum_stack: list[str],
    parent_id: str | None,
    rows: list[SectionRow],
    ordinal_in_parent: int,
    format: str,
    counter: list[int],
) -> None:
    """Recursively walk container elements, emitting one SectionRow per."""
    local = _localname(elem.tag)
    if local not in CONTAINER_LEVELS:
        for child in elem:
            _walk(
                child,
                bill_id=bill_id, bill_citation=bill_citation,
                enum_stack=enum_stack, parent_id=parent_id, rows=rows,
                ordinal_in_parent=ordinal_in_parent, format=format, counter=counter,
            )
        return

    enum_raw = _child_text(elem, ("enum", "num")) or ""
    enum = _normalize_enum(_text_clean_inline(enum_raw))
    heading = _text_clean_inline(_child_text(elem, ("header", "heading")) or "")

    xml_id = elem.get("id")
    if xml_id:
        section_id = f"{bill_id}::{xml_id}"
    else:
        counter[0] += 1
        section_id = f"{bill_id}::gen-{counter[0]}"

    new_stack = list(enum_stack) + [enum] if enum else list(enum_stack)
    citation = _build_citation(bill_citation, local, new_stack)

    text_self = _direct_text_of(elem, format)
    text_full = _full_text_of(elem, format)

    rows.append(SectionRow(
        section_id=section_id,
        bill_id=bill_id,
        parent_section_id=parent_id,
        level=local,
        enum=enum or None,
        heading=heading or None,
        text_self=text_self,
        text_full=text_full,
        canonical_citation=citation,
        ordinal=ordinal_in_parent,
        xml_id=xml_id,
    ))

    child_ordinal = 0
    for child in _iter_container_children(elem):
        _walk(
            child,
            bill_id=bill_id, bill_citation=bill_citation,
            enum_stack=new_stack, parent_id=section_id, rows=rows,
            ordinal_in_parent=child_ordinal, format=format, counter=counter,
        )
        child_ordinal += 1


def _build_citation(bill_citation: str, level: str, enum_stack: list[str]) -> str:
    """Build 'Sec. 3(a)(1) of H.R. 1736, 119th Cong.' style citation.

    The first enum is the section number; subsequent ones are wrapped in parens.
    """
    if not enum_stack:
        return bill_citation
    head = f"Sec. {enum_stack[0]}"
    tail = "".join(f"({e})" for e in enum_stack[1:])
    return f"{head}{tail} of {bill_citation}"


def parse_bill_xml(
    xml_path: Path,
    *,
    bill_id: str,
    congress: int,
    bill_type: str,
    bill_number: int,
) -> tuple[list[SectionRow], str]:
    """Parse a bill XML file into SectionRows. Returns (rows, format)."""
    fmt = detect_format(xml_path)
    tree = ET.parse(xml_path)
    root = tree.getroot()
    body = _find_body(root, fmt)
    if body is None:
        return [], fmt

    bill_citation = _bill_short_citation(congress, bill_type, bill_number)
    rows: list[SectionRow] = []
    counter = [0]  # mutable counter for generated ids
    ordinal = 0
    for child in body:
        if _localname(child.tag) in CONTAINER_LEVELS:
            _walk(
                child,
                bill_id=bill_id, bill_citation=bill_citation,
                enum_stack=[], parent_id=None, rows=rows,
                ordinal_in_parent=ordinal, format=fmt, counter=counter,
            )
            ordinal += 1
        else:
            _walk(
                child,
                bill_id=bill_id, bill_citation=bill_citation,
                enum_stack=[], parent_id=None, rows=rows,
                ordinal_in_parent=ordinal, format=fmt, counter=counter,
            )

    return rows, fmt
