"""Unit smoke for auth.usage — covers the policy logic without going
through Anthropic. Run after the table is migrated:

    python scripts/test_token_limit.py

The test uses a throwaway POLILABS_AUTH_DB file and a tiny limit
(POLILABS_TOKEN_LIMIT=100) so each assertion runs in milliseconds.
The actual server cap (1,000,000) is unaffected — both values are
read via env at call time, not baked into the module.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

# Override env BEFORE importing auth.* — auth.db reads POLILABS_AUTH_DB
# at module import time via db_path(), and auth.usage's limit is read
# inside get_limit() per call but we want a clean baseline for the run.
_tmpdir = tempfile.mkdtemp(prefix="polilabs-tokenlimit-test-")
os.environ["POLILABS_AUTH_DB"] = str(Path(_tmpdir) / "auth.db")
os.environ["POLILABS_TOKEN_LIMIT"] = "100"

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from auth import db, security  # noqa: E402
from auth import usage  # noqa: E402


def _setup_users() -> tuple[dict, dict]:
    """Create one exempt user and one non-exempt user. Returns both."""
    db.init_db()
    pw_hash = security.hash_password("test-password-1234")
    exempt = db.create_user("andrewdou@college.harvard.edu", pw_hash)
    normal = db.create_user("test-normal@example.com", pw_hash)
    return exempt, normal


def _assert(cond: bool, label: str) -> bool:
    print(f"  {'PASS' if cond else 'FAIL'}: {label}")
    return cond


def main() -> int:
    exempt, normal = _setup_users()
    print(f"[setup] exempt user id={exempt['id']}  normal user id={normal['id']}")
    print(f"[setup] limit={usage.get_limit()}, exempt list={sorted(usage.EXEMPT_EMAILS)}")

    results: list[bool] = []
    print("\n[exempt-bypass]")
    results.append(_assert(
        usage.is_exempt(exempt["email"]),
        "is_exempt(andrewdou@college.harvard.edu) is True",
    ))
    results.append(_assert(
        not usage.is_exempt(normal["email"]),
        "is_exempt(test-normal@example.com) is False",
    ))
    results.append(_assert(
        usage.is_exempt("RajSaha@College.Harvard.Edu"),
        "is_exempt is case-insensitive",
    ))

    print("\n[zero-usage]")
    results.append(_assert(
        usage.get_total(normal["id"]) == 0,
        "fresh user has 0 tokens",
    ))
    results.append(_assert(
        not usage.is_over_limit(normal["id"], normal["email"]),
        "fresh non-exempt is under the cap",
    ))

    print("\n[accumulate]")
    new_total = usage.add_usage(normal["id"], 30, 20)
    results.append(_assert(
        new_total == 50,
        f"30 input + 20 output → 50 (got {new_total})",
    ))
    new_total = usage.add_usage(normal["id"], 25, 0)
    results.append(_assert(
        new_total == 75,
        f"+25 input → 75 (got {new_total})",
    ))
    results.append(_assert(
        not usage.is_over_limit(normal["id"], normal["email"]),
        "still under the cap at 75/100",
    ))

    print("\n[trip-cap]")
    new_total = usage.add_usage(normal["id"], 30, 0)
    results.append(_assert(
        new_total == 105,
        f"+30 → 105 (got {new_total})",
    ))
    results.append(_assert(
        usage.is_over_limit(normal["id"], normal["email"]),
        "over the cap once total reaches 100 (>=)",
    ))

    print("\n[exempt-uncapped]")
    usage.add_usage(exempt["id"], 50_000, 50_000)
    results.append(_assert(
        usage.get_total(exempt["id"]) == 100_000,
        "exempt user accumulates usage normally",
    ))
    results.append(_assert(
        not usage.is_over_limit(exempt["id"], exempt["email"]),
        "exempt user is never over the cap (100k >> 100 limit)",
    ))

    print("\n[error-message]")
    msg = usage.limit_error_message(normal["email"])
    expected = "Error: usage limit reached for test-normal@example.com"
    results.append(_assert(
        msg == expected,
        f"limit_error_message format: {msg!r}",
    ))

    print(f"\n=========\n{sum(results)}/{len(results)} assertions passed")
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
