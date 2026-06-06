# Polilabs — security posture

What's in place on the backend, and the trust boundaries to respect when
extending it. Scope: the FastAPI app (`server.py`) + auth package.

## Authentication

- Per-user accounts: bcrypt-hashed passwords, stateless JWT sessions
  (`auth/security.py`). Credentials live in a standalone `auth.db`,
  never with the corpus.
- `/chat` and the entire `/api/*` REST surface are gated behind
  `require_user` (Bearer token). `/auth/*` is the only public surface.
- JWT signing secret: set `POLILABS_JWT_SECRET` in prod. Without it the
  app falls back to a persisted random key file — fine for a single host,
  but pin the env var for anything multi-host or reproducible.

## Network / transport

- **CORS** (`server.py`): no `*` wildcard. Set `POLILABS_CORS_ORIGINS`
  (comma-separated) in prod to pin exact frontend origins. With nothing
  set, a regex admits local dev, `*.vercel.app` (the frontend host), and
  the Fly backend origin. `allow_credentials` is `False` — auth is
  Bearer-header, never cookies.
- **Security headers** on every response: `X-Content-Type-Options:
  nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`,
  `Strict-Transport-Security` (HTTPS only). No CSP here — the frontend is
  a CDN-loaded, Babel-in-browser app served from a *different* origin
  (Vercel); a CSP belongs with that deployment.

## Abuse / rate limiting

- **Auth brute-force**: `/auth/signup` + `/auth/login` are per-IP
  rate-limited (`auth/ratelimit.py`, fixed window, in-memory). Tunables:
  `POLILABS_AUTH_RL_WINDOW` (default 300s), `POLILABS_AUTH_RL_MAX`
  (default 20). Single-process only — move to a shared store (Redis) if
  the deploy ever runs multiple workers.
- **Per-account `/chat` quota**: lifetime token cap in `auth/usage.py`
  (separate concern from the auth rate limit).

## Trust boundaries (respect when extending)

- **Verbatim statute HTML** is the one place the Text panel renders raw
  HTML (React's raw-HTML escape hatch). That HTML is produced *only* by
  the backend's own escaper (`escapeHtml`/`verbatimHtml` in `backend.js`)
  over corpus text — a controlled, server-owned source. **Never route
  agent output or user-supplied text through that path.** User note
  bodies and agent flags render as plain text / structured nodes, not raw
  HTML — keep it that way.
- **Annotations** are per-user and ownership-checked on every mutation
  (`auth/db.py`); the create route forces `source="user"` so a client
  can't forge an agent flag. When projects/sharing land, every
  `/api/annotations` row must additionally be scoped to project
  membership.
- **Per-request tool isolation**: the `/chat` tool functions close over a
  per-request `recorded` list so tool results never bleed across
  concurrent requests (`server.py`). Preserve that if you add tools.

## Before a deploy

- Set `POLILABS_CORS_ORIGINS`, `POLILABS_JWT_SECRET`, `ANTHROPIC_API_KEY`.
- Run `semgrep scan --config p/python --config p/security-audit` over
  `server.py` + `auth/` (currently clean at ERROR severity).
