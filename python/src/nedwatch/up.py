"""Ask before you call: is a host up, as Ned sees it from two continents? No key, no account.

    from nedwatch import is_up, up_state
    is_up("api.openai.com")         # -> dict: state, since, reason, watches, last_change, ask_again_s
    up_state("api.openai.com")      # -> "up" | "degraded" | "down" | "reachable" | "unknown"

"unknown" means the host is not on The Watch (ned.watch/w/), never that it is down. Standard library only; bad input
(no host, a host that isn't a hostname, a NED_API without a scheme), a network problem or a reply that isn't a JSON object
returns state "unknown" with an error field rather than raising, so a pre-flight check never breaks the call it guards.
Both stations are asked in order (US, then EU) and the first answer wins.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request

from .client import REGIONS

UNKNOWN = "unknown"
_HOST = re.compile(r"(?!.*\.\.)[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?")   # [a-z0-9.-], alnum at both ends, no ".."


def _host(host) -> tuple[str, str | None]:
    """Reduce a host or URL to a bare lowercase hostname; (host, None) if it is one, else ("" or the input, error)."""
    if host is None:
        return "", "host required"
    if not isinstance(host, str):
        return "", "bad host"
    h = host.strip()
    if "://" in h:
        h = h.split("://", 1)[1]
    for sep in ("/", "?", "#"):
        h = h.split(sep, 1)[0]
    h = h.split(":", 1)[0].lower()                     # port
    if not h:
        return "", "host required"
    if not _HOST.fullmatch(h):
        return h[:253], "bad host"
    return h, None


def is_up(host: str, *, base: str | None = None, timeout: float = 5.0, ref: str = "python") -> dict:
    h = ""
    try:
        h, bad = _host(host)
        if bad:
            return {"host": h, "state": UNKNOWN, "error": bad}
        err = None
        bases = [base] if base else [os.environ.get("NED_API") or os.environ.get("NED_WATCH_API") or REGIONS["us"], REGIONS["eu"]]
        for b in dict.fromkeys(bases):
            try:
                from . import __version__
                url = f"{str(b).rstrip('/')}/v1/up/{h}"
                if not url.lower().startswith(("http://", "https://")):
                    raise ValueError("base must be http(s)")
                req = urllib.request.Request(url, headers={"User-Agent": f"ned-watch-python/{__version__}", "X-Ned-Ref": re.sub(r"[^\x20-\x7e]", "", str(ref or "python"))[:32] or "python", "Accept": "application/json"})
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    reply = json.load(r)
                if isinstance(reply, dict):
                    return reply
                err = "bad reply"
            except urllib.error.HTTPError as e:
                err = f"HTTP {e.code}"
            except Exception as e:  # noqa: BLE001
                err = e.__class__.__name__
        return {"host": h, "state": UNKNOWN, "error": err or "unreachable"}
    except Exception as e:  # noqa: BLE001 -- a pre-flight check never raises
        return {"host": h, "state": UNKNOWN, "error": e.__class__.__name__}


def up_state(host: str, **kw) -> str:
    try:
        return str(is_up(host, **kw).get("state") or UNKNOWN)
    except Exception:  # noqa: BLE001 -- e.g. an unexpected keyword
        return UNKNOWN
