"""SQLite-backed user store for polilabs auth.

A standalone database (``data/auth.db`` by default, override with
``POLILABS_AUTH_DB``) — deliberately separate from the corpus index
(``data/polilabs.db``) so user credentials never travel with the
committed corpus and the two stores have independent lifecycles.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

_DEFAULT_DB = "data/auth.db"


def db_path() -> Path:
    """Filesystem location of the auth DB (env-overridable)."""
    return Path(os.environ.get("POLILABS_AUTH_DB", _DEFAULT_DB))


def _connect() -> sqlite3.Connection:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create the ``users`` and ``user_token_usage`` tables if missing.
    Idempotent — safe at boot."""
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                email         TEXT    NOT NULL UNIQUE COLLATE NOCASE,
                password_hash TEXT    NOT NULL,
                created_at    TEXT    NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        # Lifetime per-user token accounting, used by auth.usage to enforce
        # the per-account cap on /chat. One row per user_id; updated_at
        # is for ops visibility only. The cap policy itself (limit value,
        # exemption list) lives in auth.usage so the DB layer stays
        # mechanical.
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS user_token_usage (
                user_id      INTEGER PRIMARY KEY
                             REFERENCES users(id) ON DELETE CASCADE,
                total_input  INTEGER NOT NULL DEFAULT 0,
                total_output INTEGER NOT NULL DEFAULT 0,
                updated_at   TEXT    NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        # Per-user, in-bill annotations (highlight + note). Lives on the
        # auth DB, never with the committed corpus, so a researcher's
        # private notes have the same lifecycle as their credentials.
        # `section_id` anchors the note to a bill section/block (the
        # frontend's data-anchor); NULL means a bill-level note. `quote`
        # is the verbatim text the user selected, kept so the note still
        # reads sensibly if the anchor can't be re-located. `source`
        # distinguishes a human note ('user') from an agent-flagged span
        # ('agent') — both render through the same highlight machinery.
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS annotations (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER NOT NULL
                            REFERENCES users(id) ON DELETE CASCADE,
                bill_id     TEXT    NOT NULL,
                section_id  TEXT,
                quote       TEXT    NOT NULL DEFAULT '',
                body        TEXT    NOT NULL DEFAULT '',
                color       TEXT    NOT NULL DEFAULT 'yellow',
                source      TEXT    NOT NULL DEFAULT 'user',
                created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
                updated_at  TEXT    NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_annotations_user_bill "
            "ON annotations(user_id, bill_id)"
        )
        # Long-lived "connector" tokens — a user mints one and pastes it
        # into their own external agent (e.g. a ChatGPT Action) so that
        # agent can drive the read-only /api/* tool surface on their
        # behalf. We store only the JWT id (`jti`), never the token, so
        # the row is a revocation handle, not a credential. require_user
        # rejects a connector JWT whose jti is missing or revoked here.
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS connector_tokens (
                jti        TEXT    PRIMARY KEY,
                user_id    INTEGER NOT NULL
                           REFERENCES users(id) ON DELETE CASCADE,
                label      TEXT    NOT NULL DEFAULT '',
                created_at TEXT    NOT NULL DEFAULT (datetime('now')),
                revoked    INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_connector_tokens_user "
            "ON connector_tokens(user_id)"
        )


# ── annotations ─────────────────────────────────────────────────────────
_ANN_COLS = "id, bill_id, section_id, quote, body, color, source, created_at, updated_at"


def list_annotations(user_id: int, bill_id: str) -> list[dict]:
    """All of a user's annotations for one bill, oldest first."""
    with _connect() as conn:
        rows = conn.execute(
            f"SELECT {_ANN_COLS} FROM annotations "
            "WHERE user_id = ? AND bill_id = ? ORDER BY id ASC",
            (user_id, bill_id),
        ).fetchall()
    return [dict(r) for r in rows]


def create_annotation(
    user_id: int,
    bill_id: str,
    section_id: str | None,
    quote: str,
    body: str,
    color: str,
    source: str,
) -> dict:
    """Insert one annotation and return the stored row."""
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO annotations "
            "(user_id, bill_id, section_id, quote, body, color, source) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user_id, bill_id, section_id, quote, body, color, source),
        )
        row = conn.execute(
            f"SELECT {_ANN_COLS} FROM annotations WHERE id = ?",
            (cur.lastrowid,),
        ).fetchone()
    return dict(row)


def update_annotation(
    user_id: int, ann_id: int, body: str | None, color: str | None
) -> dict | None:
    """Patch a user's own annotation. Returns the row, or None if it
    isn't theirs / doesn't exist. Only non-None fields are written."""
    sets, params = [], []
    if body is not None:
        sets.append("body = ?"); params.append(body)
    if color is not None:
        sets.append("color = ?"); params.append(color)
    if not sets:
        # nothing to change — just return the current row (ownership-checked)
        with _connect() as conn:
            row = conn.execute(
                f"SELECT {_ANN_COLS} FROM annotations WHERE id = ? AND user_id = ?",
                (ann_id, user_id),
            ).fetchone()
        return dict(row) if row else None
    sets.append("updated_at = datetime('now')")
    params.extend([ann_id, user_id])
    with _connect() as conn:
        cur = conn.execute(
            f"UPDATE annotations SET {', '.join(sets)} "
            "WHERE id = ? AND user_id = ?",
            params,
        )
        if cur.rowcount == 0:
            return None
        row = conn.execute(
            f"SELECT {_ANN_COLS} FROM annotations WHERE id = ?", (ann_id,)
        ).fetchone()
    return dict(row)


def delete_annotation(user_id: int, ann_id: int) -> bool:
    """Delete a user's own annotation. True if a row was removed."""
    with _connect() as conn:
        cur = conn.execute(
            "DELETE FROM annotations WHERE id = ? AND user_id = ?",
            (ann_id, user_id),
        )
        return cur.rowcount > 0


# ── connector tokens ────────────────────────────────────────────────────
def add_connector_token(jti: str, user_id: int, label: str) -> dict:
    """Record a freshly minted connector token's id (revocation handle)."""
    with _connect() as conn:
        conn.execute(
            "INSERT INTO connector_tokens (jti, user_id, label) VALUES (?, ?, ?)",
            (jti, user_id, label),
        )
        row = conn.execute(
            "SELECT jti, label, created_at, revoked FROM connector_tokens WHERE jti = ?",
            (jti,),
        ).fetchone()
    return dict(row)


def list_connector_tokens(user_id: int) -> list[dict]:
    """A user's connector tokens (metadata only — never the token)."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT jti, label, created_at, revoked FROM connector_tokens "
            "WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def revoke_connector_token(user_id: int, jti: str) -> bool:
    """Revoke one of a user's own connector tokens. True if one changed."""
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE connector_tokens SET revoked = 1 WHERE jti = ? AND user_id = ?",
            (jti, user_id),
        )
        return cur.rowcount > 0


def is_connector_token_active(jti: str) -> bool:
    """True if this connector jti exists and is not revoked. Used by the
    auth gate to make connector JWTs revocable despite being stateless."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT revoked FROM connector_tokens WHERE jti = ?", (jti,)
        ).fetchone()
    return bool(row) and row["revoked"] == 0


def create_user(email: str, password_hash: str) -> dict:
    """Insert a new user. Raise ``ValueError`` if the email is taken."""
    try:
        with _connect() as conn:
            cur = conn.execute(
                "INSERT INTO users (email, password_hash) VALUES (?, ?)",
                (email, password_hash),
            )
            return {"id": cur.lastrowid, "email": email}
    except sqlite3.IntegrityError as exc:
        raise ValueError("email already registered") from exc


def get_user_by_email(email: str) -> dict | None:
    """Look up a user (including ``password_hash``) by email, case-insensitively."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT id, email, password_hash FROM users WHERE email = ? COLLATE NOCASE",
            (email,),
        ).fetchone()
    return dict(row) if row else None


def get_user_by_id(user_id: int) -> dict | None:
    """Look up the public fields (``id``, ``email``) of a user by id."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT id, email FROM users WHERE id = ?", (user_id,)
        ).fetchone()
    return dict(row) if row else None
