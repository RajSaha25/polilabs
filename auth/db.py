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
    """Create the ``users`` table if missing. Idempotent — safe at boot."""
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
