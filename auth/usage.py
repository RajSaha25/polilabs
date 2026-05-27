"""Per-account token usage accounting + rate limiting.

Policy:
  - Every authenticated user has a lifetime cap of POLILABS_TOKEN_LIMIT
    tokens (default 1,000,000), counting input + output combined.
  - Exempt accounts in EXEMPT_EMAILS bypass the cap entirely.
  - The /chat handler calls is_over_limit() before the first LLM call,
    yields an error SSE event if exceeded, and otherwise proceeds.
    After each runner iteration it calls add_usage(user_id, in, out)
    and re-checks; if NOW over, it yields the error event and stops
    the agent loop on the next iteration.

Storage lives in the auth DB (data/auth.db) — the corpus DB never
sees user identity, by design.

The cap and exemption list are constants here rather than env vars so
they show up in code review and version control. Override the cap for
tests via the POLILABS_TOKEN_LIMIT env var.
"""
from __future__ import annotations

import os
import sqlite3

from auth.db import _connect


# Total input + output tokens per user, lifetime. Override via env for
# tests / staging. 1,000,000 is generous for a research-prototype agent
# at Sonnet pricing (~$3.50 lifetime cost ceiling per user).
DEFAULT_LIMIT = 1_000_000


def get_limit() -> int:
    """Read the active per-user limit, allowing env override."""
    raw = os.environ.get("POLILABS_TOKEN_LIMIT")
    if not raw:
        return DEFAULT_LIMIT
    try:
        return int(raw)
    except ValueError:
        return DEFAULT_LIMIT


# Accounts that bypass the cap. Comparison is case-insensitive — users
# table normalizes emails to lowercase on signup, so the constants
# below should also be lowercase for safety.
EXEMPT_EMAILS = frozenset({
    "andrewdou@college.harvard.edu",
    "rajsaha@college.harvard.edu",
})


def is_exempt(email: str | None) -> bool:
    """True if this email is in the exemption list (case-insensitive)."""
    if not email:
        return False
    return email.strip().lower() in EXEMPT_EMAILS


def get_total(user_id: int) -> int:
    """Return the user's lifetime input+output token total. Zero for
    users with no row yet (i.e. who haven't completed a /chat turn)."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT total_input + total_output AS total "
            "FROM user_token_usage WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    return int(row["total"]) if row else 0


def add_usage(user_id: int, input_tokens: int, output_tokens: int) -> int:
    """Accumulate one LLM call's token usage and return the new total.

    Uses UPSERT (ON CONFLICT DO UPDATE) so the first call seeds the
    row, subsequent calls increment in place. Atomic under SQLite's
    default isolation.

    Pass zero for either count to skip — _usage_of() may return None
    for cache-only or aborted iterations.
    """
    inp = max(0, int(input_tokens or 0))
    out = max(0, int(output_tokens or 0))
    if inp == 0 and out == 0:
        return get_total(user_id)
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO user_token_usage (user_id, total_input, total_output, updated_at)
            VALUES (?, ?, ?, datetime('now'))
            ON CONFLICT(user_id) DO UPDATE SET
              total_input  = total_input  + excluded.total_input,
              total_output = total_output + excluded.total_output,
              updated_at   = datetime('now')
            """,
            (user_id, inp, out),
        )
        row = conn.execute(
            "SELECT total_input + total_output AS total "
            "FROM user_token_usage WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    return int(row["total"]) if row else 0


def is_over_limit(user_id: int, email: str | None) -> bool:
    """Should this user be blocked from a new /chat call?

    Exempt accounts always return False. Non-exempt accounts return True
    once their lifetime total has reached the limit. Equality is a hit
    (>= not >) so the limit is inclusive — once you cross it the next
    call refuses.
    """
    if is_exempt(email):
        return False
    return get_total(user_id) >= get_limit()


def limit_error_message(email: str) -> str:
    """The exact user-visible error string when the cap is hit. Kept as
    a single function so the wording is consistent across the pre-call
    refusal path and the mid-stream abort path."""
    return f"Error: usage limit reached for {email}"
