"""Ask before you call: is a host up, as Ned sees it from two continents? No key, no account.

    from nedwatch import is_up, up_state
    is_up("api.openai.com")         # -> dict: state, since, reason, watches, last_change, ask_again_s
    up_state("api.openai.com")      # -> "up" | "degraded" | "down" | "reachable" | "unknown"

"unknown" means the host is not on The Watch (ned.watch/w/), never that it is down. Standard library only; a network
problem returns state "unknown" with an error field rather than raising, so a pre-flight check never breaks the call it
guards. Both stations are asked in order (US, then EU) and the first answer wins.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from .client import REGIONS

UNKNOWN = "unknown"


def is_up(host: str, *, base: str | None = None, timeout: float = 5.0, ref: str = "python") -> dict:
    h = (host or "").strip()
    if "://" in h:
        h = h.split("://", 1)[1]
    h = h.split("/", 1)[0].split("?", 1)[0].lower()
    if not h:
        return {"host": h, "state": UNKNOWN, "error": "host required"}
    bases = [base.rstrip("/")] if base else [os.environ.get("NED_API") or os.environ.get("NED_WATCH_API") or REGIONS["us"], REGIONS["eu"]]
    err = None
    for b in dict.fromkeys(bases):
        from . import __version__
        req = urllib.request.Request(f"{b}/v1/up/{h}", headers={"User-Agent": f"ned-watch-python/{__version__}", "X-Ned-Ref": ref[:32], "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            err = f"HTTP {e.code}"
        except Exception as e:  # noqa: BLE001
            err = e.__class__.__name__
    return {"host": h, "state": UNKNOWN, "error": err or "unreachable"}


def up_state(host: str, **kw) -> str:
    return str(is_up(host, **kw).get("state") or UNKNOWN)
