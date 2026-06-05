"""FastAPI routes for polilabs auth, plus the ``require_user`` gate.

Endpoints (all under ``/auth``):
  POST /auth/signup   create an account, return a session token
  POST /auth/login    exchange credentials for a session token
  GET  /auth/me       echo the authenticated user (token probe)

``require_user`` is the dependency that other routes attach to become
login-only — see ``server.py``.
"""
from __future__ import annotations

import re
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from auth import db, ratelimit, security

router = APIRouter(prefix="/auth", tags=["auth"])

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_MIN_PASSWORD_LEN = 8
_UNAUTHORIZED = {"WWW-Authenticate": "Bearer"}


def _rate_limit(request: Request) -> None:
    """Per-IP brute-force gate for the unauthenticated auth routes.
    Raises 429 once an IP exceeds the window's attempt budget."""
    ip = request.client.host if request.client else "unknown"
    if not ratelimit.allow(ip):
        raise HTTPException(
            429,
            "Too many attempts. Please wait a few minutes and try again.",
            headers={"Retry-After": str(ratelimit.retry_after())},
        )


class Credentials(BaseModel):
    email: str = Field(description="Account email address")
    password: str = Field(description="Account password")


class AuthResponse(BaseModel):
    token: str = Field(description="Bearer token for the Authorization header")
    user: dict = Field(description="The authenticated user: {id, email}")


def _normalize_email(email: str) -> str:
    return email.strip().lower()


@router.post("/signup", response_model=AuthResponse)
def signup(creds: Credentials, request: Request) -> AuthResponse:
    """Register a new account and return a session token."""
    _rate_limit(request)
    email = _normalize_email(creds.email)
    if not _EMAIL_RE.match(email):
        raise HTTPException(422, "Enter a valid email address.")
    if len(creds.password) < _MIN_PASSWORD_LEN:
        raise HTTPException(
            422, f"Password must be at least {_MIN_PASSWORD_LEN} characters."
        )
    try:
        user = db.create_user(email, security.hash_password(creds.password))
    except ValueError:
        raise HTTPException(409, "An account with that email already exists.")
    token = security.create_token(user["id"], user["email"])
    return AuthResponse(token=token, user=user)


@router.post("/login", response_model=AuthResponse)
def login(creds: Credentials, request: Request) -> AuthResponse:
    """Verify credentials and return a session token."""
    _rate_limit(request)
    email = _normalize_email(creds.email)
    user = db.get_user_by_email(email)
    # One generic message for both "no such user" and "wrong password" —
    # don't leak which emails have accounts.
    if not user or not security.verify_password(creds.password, user["password_hash"]):
        raise HTTPException(401, "Incorrect email or password.", headers=_UNAUTHORIZED)
    token = security.create_token(user["id"], user["email"])
    return AuthResponse(token=token, user={"id": user["id"], "email": user["email"]})


def require_user(request: Request) -> dict:
    """Dependency: require a valid ``Authorization: Bearer <token>`` header.

    Returns the authenticated user dict (``{id, email}``). Raises 401 if
    the header is missing/malformed or the token is bad or expired.
    Attach via ``Depends(require_user)`` to make a route login-only.
    """
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        raise HTTPException(401, "Authentication required.", headers=_UNAUTHORIZED)
    payload = security.decode_token(header[len("Bearer "):].strip())
    if not payload:
        raise HTTPException(
            401, "Session expired — please sign in again.", headers=_UNAUTHORIZED
        )
    # Connector tokens are long-lived; honour their revocation handle so a
    # leaked token can be killed without rotating the whole signing secret.
    if payload.get("scope") == "connector":
        jti = payload.get("jti", "")
        if not jti or not db.is_connector_token_active(jti):
            raise HTTPException(401, "This connector token was revoked.", headers=_UNAUTHORIZED)
    user = db.get_user_by_id(int(payload.get("sub", 0)))
    if not user:
        raise HTTPException(401, "Account no longer exists.", headers=_UNAUTHORIZED)
    return user


@router.get("/me")
def me(user: dict = Depends(require_user)) -> dict:
    """Return the authenticated user — a cheap way for a client to probe
    whether its stored token is still valid."""
    return user


# ── connector tokens (bring-your-own-agent) ─────────────────────────────
#
# A signed-in researcher mints a long-lived token and pastes it into their
# own approved agent (a ChatGPT Action, an MCP-over-HTTP client, a script)
# so that agent can drive the read-only /api/* tools on their behalf. The
# token is shown ONCE at creation; only its id (jti) is stored, so it can
# be listed and revoked but never re-read.


class ConnectorTokenIn(BaseModel):
    label: str = Field(default="", description="A human label, e.g. 'My ChatGPT'")


@router.post("/connector-token")
def create_connector_token(body: ConnectorTokenIn,
                           user: dict = Depends(require_user)) -> dict:
    """Mint a connector token for an external agent. Returned once."""
    jti = secrets.token_hex(16)
    token = security.create_connector_token(user["id"], user["email"], jti)
    db.add_connector_token(jti, user["id"], body.label.strip())
    return {
        "token": token,
        "jti": jti,
        "label": body.label.strip(),
        "scope": "connector",
        "note": "Store this now — it is not shown again. Revoke it any time "
                "with DELETE /auth/connector-token/{jti}.",
    }


@router.get("/connector-tokens")
def list_connector_tokens(user: dict = Depends(require_user)) -> list[dict]:
    """List the caller's connector tokens (metadata only, never the token)."""
    return db.list_connector_tokens(user["id"])


@router.delete("/connector-token/{jti}")
def revoke_connector_token(jti: str, user: dict = Depends(require_user)) -> dict:
    """Revoke one of the caller's connector tokens."""
    if not db.revoke_connector_token(user["id"], jti):
        raise HTTPException(404, "No such connector token.")
    return {"ok": True, "jti": jti, "revoked": True}
