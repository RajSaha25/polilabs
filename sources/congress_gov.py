"""Thin client for the Library of Congress API at api.congress.gov.

Docs: https://api.congress.gov/
Auth: API key via `api_key` query param OR `X-API-Key` header.
Rate limit: 5,000 requests/hour.
"""
from __future__ import annotations

import os
from typing import Any

import requests

BASE_URL = "https://api.congress.gov/v3"


class CongressGov:
    def __init__(self, api_key: str | None = None, timeout: float = 30.0):
        self.api_key = api_key or os.environ["CONGRESS_GOV_API_KEY"]
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"X-API-Key": self.api_key, "Accept": "application/json"})

    def _get(self, path: str, **params: Any) -> dict:
        r = self.session.get(f"{BASE_URL}{path}", params=params, timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def list_bills(self, congress: int | None = None, limit: int = 20, offset: int = 0) -> dict:
        path = f"/bill/{congress}" if congress else "/bill"
        return self._get(path, limit=limit, offset=offset, format="json")

    def get_bill(self, congress: int, bill_type: str, bill_number: int) -> dict:
        return self._get(f"/bill/{congress}/{bill_type.lower()}/{bill_number}", format="json")

    def get_bill_text(self, congress: int, bill_type: str, bill_number: int) -> dict:
        return self._get(f"/bill/{congress}/{bill_type.lower()}/{bill_number}/text", format="json")

    def get_bill_actions(self, congress: int, bill_type: str, bill_number: int) -> dict:
        return self._get(f"/bill/{congress}/{bill_type.lower()}/{bill_number}/actions", format="json")
