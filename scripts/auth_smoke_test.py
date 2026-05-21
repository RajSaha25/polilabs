"""Smoke test for the polilabs auth surface (auth/).

Exercises signup / login / token verification and the `require_user`
gate against a throwaway SQLite DB — no corpus, no Anthropic key, no
network. Run after touching anything under auth/ or the auth wiring in
server.py:

    python scripts/auth_smoke_test.py

Exits non-zero on the first failed check.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

# Point auth at a fresh throwaway DB *before* importing the package, so
# the run never touches a real data/auth.db.
_TMP = tempfile.mkdtemp(prefix="polilabs-auth-smoke-")
os.environ["POLILABS_AUTH_DB"] = str(Path(_TMP) / "auth.db")
os.environ["POLILABS_JWT_SECRET"] = "smoke-test-secret-not-for-production"

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from auth import init_db, require_user, router as auth_router

_passed = 0
_failed = 0


def check(label: str, ok: bool) -> None:
    global _passed, _failed
    mark = "ok  " if ok else "FAIL"
    print(f"  [{mark}] {label}")
    if ok:
        _passed += 1
    else:
        _failed += 1


def main() -> int:
    init_db()

    app = FastAPI()
    app.include_router(auth_router)

    # A minimal protected route — stands in for /chat and /api/*.
    @app.get("/protected")
    def protected(user: dict = Depends(require_user)) -> dict:
        return {"seen": user["email"]}

    client = TestClient(app)

    print("auth smoke test")
    print("---------------")

    # ── signup ──────────────────────────────────────────────────────
    r = client.post("/auth/signup",
                     json={"email": "Alice@Example.com", "password": "correcthorse"})
    check("signup returns 200", r.status_code == 200)
    body = r.json() if r.status_code == 200 else {}
    token = body.get("token", "")
    check("signup returns a token", bool(token))
    check("signup normalizes the email to lowercase",
          body.get("user", {}).get("email") == "alice@example.com")

    r = client.post("/auth/signup",
                     json={"email": "alice@example.com", "password": "anotherpass"})
    check("duplicate email is rejected (409)", r.status_code == 409)

    r = client.post("/auth/signup",
                     json={"email": "not-an-email", "password": "correcthorse"})
    check("malformed email is rejected (422)", r.status_code == 422)

    r = client.post("/auth/signup",
                     json={"email": "bob@example.com", "password": "short"})
    check("short password is rejected (422)", r.status_code == 422)

    # ── login ───────────────────────────────────────────────────────
    r = client.post("/auth/login",
                     json={"email": "alice@example.com", "password": "correcthorse"})
    check("login with correct credentials returns 200", r.status_code == 200)

    r = client.post("/auth/login",
                     json={"email": "alice@example.com", "password": "wrongpass"})
    check("login with wrong password returns 401", r.status_code == 401)

    r = client.post("/auth/login",
                     json={"email": "nobody@example.com", "password": "whatever"})
    check("login for unknown user returns 401", r.status_code == 401)

    # ── token verification ──────────────────────────────────────────
    auth = {"Authorization": f"Bearer {token}"}
    r = client.get("/auth/me", headers=auth)
    check("GET /auth/me with a valid token returns 200", r.status_code == 200)
    check("GET /auth/me echoes the right user",
          r.json().get("email") == "alice@example.com")

    r = client.get("/auth/me")
    check("GET /auth/me without a token returns 401", r.status_code == 401)

    r = client.get("/auth/me", headers={"Authorization": "Bearer garbage.token.here"})
    check("GET /auth/me with a bad token returns 401", r.status_code == 401)

    # ── the require_user gate on a protected route ──────────────────
    r = client.get("/protected")
    check("protected route without a token returns 401", r.status_code == 401)

    r = client.get("/protected", headers=auth)
    check("protected route with a valid token returns 200", r.status_code == 200)

    print("---------------")
    print(f"{_passed} passed, {_failed} failed")
    return 0 if _failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
