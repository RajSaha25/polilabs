# web-design-a — parallel frontend experiment

A **second, independent frontend** for polilabs, built from a Claude Design
handoff bundle ("Polilabs #2"). It does **not** replace `web/` (Andrew's
frontend) — both can run side by side against the same backend, so the two
designs can be compared directly.

## What it is

A three-zone research workspace — ranked bill list + streaming answer + prompt
on the left, a verbatim **Text** panel and a structured **Decomp** panel
(Structure / Definition / Amendment / Citation modes) on the right, with
synchronized highlighting between them.

It is a Babel-in-the-browser React prototype (no build step). The original
mock used a static `data.js`; that has been replaced by `backend.js`, which
talks to the real FastAPI backend:

- `POST /chat` (SSE) — streams the agent answer + the ranked bill list
- `GET /api/bill/{id}/...` — loads verbatim sections, defined terms, amendments
  for whichever bill you click (no agent turn — instant, free)

Every panel is filled from a backend response. No invented text.

## Sign in

The workspace is login-only. On first load you get a sign-in / create-account
screen (`auth-screen.jsx`); creating an account or signing in stores a session
token in `localStorage` and `backend.js` attaches it to every `/chat` and
`/api/*` call. A returning user with a live token lands straight in the app.
Accounts are handled by the backend's `/auth/*` routes — see the repo `auth/`
package. Sign out from the control in the app header.

## Run it

Two processes — the shared backend and this static frontend.

```bash
# 1. Backend (from the repo root; needs the built indexes + ANTHROPIC_API_KEY)
make backend                       # uvicorn server:app on :8000

# 2. This frontend (separate terminal, from the repo root)
python3 -m http.server 5174 --directory web-design-a
```

Then open <http://localhost:5174/Polilabs.html>.

CORS is open on the backend, so the frontend may be served from any port. To
point at a non-default backend, set it in the browser console:
`localStorage.setItem("polilabs_backend", "http://host:port")` and reload.

## Files

| File | Role |
|---|---|
| `Polilabs.html` | Entry point — loads React, Babel, and the components |
| `backend.js` | SSE + REST client and the mappers (backend JSON → design shapes) |
| `auth.js` | Auth client — `/auth/*` calls, session token in `localStorage` |
| `auth-screen.jsx` | The sign-in / create-account gate |
| `auth.css` | Styles for the auth screen + the header sign-out control |
| `app.jsx` | App shell + state; orchestrates the backend calls (gated by `Root`) |
| `left-rail.jsx` `bill-viewer.jsx` `text-panel.jsx` `decomp-panel.jsx` | The three-zone UI |
| `icons.jsx` `tweaks-panel.jsx` | Shared icon set + the dev tweaks panel |
| `styles.css` `design-system.css` | The Claude Design visual system |
| `Polilabs Design System.html` | Standalone design-system spec page |

## Status / known limits

- Babel-in-browser (no build) — fine for evaluation; port to Vite if this
  design is chosen.
- Citation mode lazily fetches a per-section citation graph; large bills make
  several REST calls when that tab is first opened.
- Amendment cards show "target text not yet verified" — the v1 corpus has not
  ingested the OLRC U.S. Code text, so before/after text cannot be checked
  against the live statute. This is honest, not a bug.
- Sync highlighting anchors at section granularity (the backend exposes
  section IDs, not character offsets).
