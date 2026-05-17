"""Thin client for the GPO GovInfo API at api.govinfo.gov.

Docs: https://api.govinfo.gov/docs
Auth: API key via `api_key` query param (api.data.gov key works here).

For bulk corpus ingestion, prefer the bulkdata downloads at
https://www.govinfo.gov/bulkdata over the per-package API.
"""
from __future__ import annotations

import os
from typing import Any

import requests

BASE_URL = "https://api.govinfo.gov"


class GovInfo:
    def __init__(self, api_key: str | None = None, timeout: float = 30.0):
        self.api_key = api_key or os.environ["GOVINFO_API_KEY"]
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"Accept": "application/json"})

    def _get(self, path: str, **params: Any) -> dict:
        params = {"api_key": self.api_key, **params}
        r = self.session.get(f"{BASE_URL}{path}", params=params, timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def list_collections(self) -> dict:
        return self._get("/collections")

    def list_packages(self, collection: str, last_modified_start: str, page_size: int = 100, offset_mark: str = "*") -> dict:
        """List packages in a collection modified since an ISO-8601 timestamp.

        Example: list_packages("BILLS", "2024-01-01T00:00:00Z")
        """
        return self._get(
            f"/collections/{collection}/{last_modified_start}",
            pageSize=page_size,
            offsetMark=offset_mark,
        )

    def package_summary(self, package_id: str) -> dict:
        """e.g. package_id='BILLS-118hr1ih' or 'PLAW-117publ263'."""
        return self._get(f"/packages/{package_id}/summary")

    def package_granules(self, package_id: str, page_size: int = 100, offset_mark: str = "*") -> dict:
        return self._get(f"/packages/{package_id}/granules", pageSize=page_size, offsetMark=offset_mark)
