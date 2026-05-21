"""polilabs auth — self-hosted per-user accounts.

Credentials live in a standalone SQLite DB, passwords are bcrypt-hashed,
and sessions are stateless JWTs. The package exposes two things to
``server.py``:

  * ``router``        — the ``/auth/signup``, ``/auth/login``, ``/auth/me`` routes
  * ``require_user``  — a FastAPI dependency that gates a route behind a
                        valid Bearer token

Nothing here depends on the corpus or the agent, so the auth surface can
be reasoned about (and tested) in isolation.
"""
from auth.db import init_db
from auth.routes import require_user, router

__all__ = ["router", "require_user", "init_db"]
