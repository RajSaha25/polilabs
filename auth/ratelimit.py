"""In-process, per-IP rate limiting for the public auth endpoints.

A fixed-window counter held in memory — brute-force defence for
``/auth/signup`` and ``/auth/login`` (which are unauthenticated and
hit a bcrypt verify, so they're the natural target). This is *not* the
per-account API quota; that's :mod:`auth.usage`.

Adequate for the current single-process uvicorn / Fly deploy. If polilabs
ever runs multiple workers, move the counter to a shared store (Redis) so
the window is global rather than per-process.

Tunables (env):
  POLILABS_AUTH_RL_WINDOW   window length in seconds   (default 300)
  POLILABS_AUTH_RL_MAX      attempts per window per IP (default 20)
"""
from __future__ import annotations

import os
import threading
import time
from collections import defaultdict

_WINDOW_S = float(os.environ.get("POLILABS_AUTH_RL_WINDOW", "300"))
_MAX = int(os.environ.get("POLILABS_AUTH_RL_MAX", "20"))

_lock = threading.Lock()
_hits: dict[str, list[float]] = defaultdict(list)


def allow(key: str) -> bool:
    """Record one attempt for ``key`` (an IP); return ``True`` while the
    caller is still under the limit for the current window."""
    now = time.time()
    cutoff = now - _WINDOW_S
    with _lock:
        bucket = [t for t in _hits[key] if t >= cutoff]
        bucket.append(now)
        _hits[key] = bucket
        # Opportunistic cleanup so a stream of distinct IPs can't grow the
        # map without bound.
        if len(_hits) > 10_000:
            for k in [k for k, v in list(_hits.items()) if not v or v[-1] < cutoff]:
                _hits.pop(k, None)
        return len(bucket) <= _MAX


def retry_after() -> int:
    """Seconds a blocked caller should wait — the window length."""
    return int(_WINDOW_S)
