"""Scrape the OLRC Popular Name Table (uscode.house.gov) and keep the
entries that resolve to public laws of the universe's covered Congresses.

The Popular Name Table is the official alias dictionary for enacted
acts — "CHIPS Act of 2022" -> Pub. L. 117-167. BILLSTATUS titles already
cover most of these, but the PNT adds editor-curated names (including
older-act nicknames embedded in newer laws) and is the standard lookup
tool human researchers use, so the agent should resolve at least as well.

Output: data/universe/popular_names.json (committed) —
  [{"name": ..., "public_law": "PL 117-167"}, ...]
The index build (index/build_universe_tables.py) joins on
universe_bills.public_law and adds bill_aliases rows with
source='olrc_popular_names'.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.build_universe import CONGRESSES  # noqa: E402

URL = "https://uscode.house.gov/popularnames/popularnames.htm"
OUT = Path("data/universe/popular_names.json")

ENTRY_RE = re.compile(
    r"<p class='popular-name'>(?P<name>.*?)</p>.*?"
    r"<p class='popular-name-information' content-type='cite' "
    r"t3searchkey='(?P<pl>\d+-\d+)'",
    re.DOTALL,
)
TAG_RE = re.compile(r"<[^>]+>")


def main() -> int:
    html = requests.get(URL, timeout=300).text
    covered = {str(c) for c in CONGRESSES}
    rows: list[dict] = []
    seen: set[tuple[str, str]] = set()
    total_entries = 0
    for m in ENTRY_RE.finditer(html):
        total_entries += 1
        pl = m.group("pl")
        congress = pl.split("-", 1)[0]
        if congress not in covered:
            continue
        name = TAG_RE.sub("", m.group("name")).strip()
        if not name:
            continue
        key = (name.lower(), pl)
        if key in seen:
            continue
        seen.add(key)
        rows.append({"name": name, "public_law": f"PL {pl}"})

    rows.sort(key=lambda r: (r["public_law"], r["name"]))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(rows, indent=1) + "\n")
    print(f"[pnt] {total_entries} table entries scanned; "
          f"{len(rows)} names for Congresses {sorted(covered)} -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
