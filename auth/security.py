"""Password hashing (bcrypt) and stateless session tokens (JWT).

The signing secret comes from ``POLILABS_JWT_SECRET``; if that is unset
a random secret is generated once and persisted next to the auth DB so
tokens survive a dev restart. Set the env var explicitly in production.
"""
from __future__ import annotations

import datetime as dt
import functools
import os
import secrets
from pathlib import Path

import bcrypt
import jwt

from auth.db import db_path

_ALGO = "HS256"
_TOKEN_TTL = dt.timedelta(days=7)
# bcrypt only hashes the first 72 bytes of input; recent versions raise
# rather than silently truncating, so we cap the input ourselves.
_BCRYPT_MAX_BYTES = 72


def _clip(password: str) -> bytes:
    return password.encode("utf-8")[:_BCRYPT_MAX_BYTES]


def hash_password(password: str) -> str:
    """Return a bcrypt hash (with embedded salt) for ``password``."""
    return bcrypt.hashpw(_clip(password), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """Constant-time check of ``password`` against a stored bcrypt hash."""
    try:
        return bcrypt.checkpw(_clip(password), password_hash.encode("utf-8"))
    except ValueError:
        return False


@functools.lru_cache(maxsize=1)
def _secret() -> str:
    """The JWT signing secret — env var, else a persisted random secret."""
    env = os.environ.get("POLILABS_JWT_SECRET")
    if env:
        return env
    key_file = db_path().with_name("auth_secret.key")
    if key_file.exists():
        return key_file.read_text().strip()
    key_file.parent.mkdir(parents=True, exist_ok=True)
    secret = secrets.token_hex(32)
    key_file.write_text(secret)
    return secret


def create_token(user_id: int, email: str) -> str:
    """Mint a signed JWT for a user; expires after ``_TOKEN_TTL``."""
    now = dt.datetime.now(dt.timezone.utc)
    payload = {
        "sub": str(user_id),
        "email": email,
        "iat": now,
        "exp": now + _TOKEN_TTL,
    }
    return jwt.encode(payload, _secret(), algorithm=_ALGO)


def decode_token(token: str) -> dict | None:
    """Return the token's payload, or ``None`` if invalid / expired."""
    try:
        return jwt.decode(token, _secret(), algorithms=[_ALGO])
    except jwt.PyJWTError:
        return None
