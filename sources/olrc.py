"""Helpers for Office of Law Revision Counsel US Code bulk XML.

Not an API — just static downloads of versioned US Code release points.
Page: https://uscode.house.gov/download/download.shtml
Release points: https://uscode.house.gov/download/releasepoints/

A "release point" is the US Code as it stood after enacting a specific public
law. This is what lets you answer "what did the law say on date X." Each
release point has a date and a public-law number; downloads are ZIP archives
containing one USLM XML file per Title.
"""
from __future__ import annotations

import os
from pathlib import Path

import requests

BASE_URL = "https://uscode.house.gov/download"
RELEASE_POINTS_INDEX = f"{BASE_URL}/releasepoints.htm"


def release_point_url(public_law: str, year: int, archive: str = "xml_uscAll") -> str:
    """Build the download URL for a release point ZIP.

    Args:
        public_law: e.g. "118-78"
        year: enactment year, e.g. 2024
        archive: archive name; "xml_uscAll" = all titles in USLM XML
    """
    return f"{BASE_URL}/releasepoints/us/pl/{public_law}/{archive}@{public_law}.zip"


def download_release_point(url: str, dest_dir: str | Path, timeout: float = 600.0) -> Path:
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / os.path.basename(url)
    with requests.get(url, stream=True, timeout=timeout) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 20):
                f.write(chunk)
    return dest


def check_release_points_reachable(timeout: float = 10.0) -> int:
    """GET the release-points index; returns HTTP status.

    Note: the OLRC server returns 404 to HEAD requests but 200 to GET, so we
    stream a GET and close it without reading the body.
    """
    with requests.get(RELEASE_POINTS_INDEX, stream=True, timeout=timeout, allow_redirects=True) as r:
        return r.status_code
