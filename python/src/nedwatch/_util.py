"""Small helpers: durations, names, fingerprints."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import timedelta
from typing import Union

Duration = Union[int, float, str, timedelta]

_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}
_PART = re.compile(r"(\d+(?:\.\d+)?)\s*([smhdw])")


def seconds(v: Duration) -> int:
    """'90s', '20m', '1h', '1h30m', '1d', 3600 or a timedelta -> whole seconds."""
    if isinstance(v, timedelta):
        return int(v.total_seconds())
    if isinstance(v, bool):
        raise ValueError("duration must be seconds, a string like '20m', or a timedelta")
    if isinstance(v, (int, float)):
        return int(v)
    s = str(v).strip().lower().replace(" ", "")
    if s.isdigit():
        return int(s)
    parts = _PART.findall(s)
    if not parts or "".join(n + u for n, u in parts) != s:
        raise ValueError(f"can't read duration {v!r}: use e.g. '90s', '20m', '1h', '1h30m', '1d'")
    return int(sum(float(n) * _UNITS[u] for n, u in parts))


_BAD = re.compile(r"[^A-Za-z0-9._:-]+")


def slug(name: str) -> str:
    """A watch name as Ned's label rule wants it: 1-64 of A-Z a-z 0-9 . _ : -"""
    s = _BAD.sub("-", str(name)).strip("-")[:64]
    if not s:
        raise ValueError(f"watch name {name!r} has no usable characters (A-Z a-z 0-9 . _ : -)")
    return s


def fingerprint(body: dict) -> str:
    keep = {k: v for k, v in body.items() if k != "meta"}
    return hashlib.sha256(json.dumps(keep, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:16]


_SECRETS = [
    (re.compile(r"\b(nw|whs|sk|pk|rk|ghp|gho|ghs|github_pat|xox[abprs]|AKIA)[-_][A-Za-z0-9_\-]{6,}"), "[redacted]"),
    (re.compile(r"(?i)\b(bearer|basic|token)\s+[A-Za-z0-9._~+/=\-]{8,}"), r"\1 [redacted]"),
    (re.compile(r"(?i)([a-z][a-z0-9+.\-]*://)[^/\s:@]+:[^/\s@]+@"), r"\1[redacted]@"),
    (re.compile(r"(?i)([?&;](?:[a-z_]*(?:token|key|secret|password|passwd|pwd|sig|signature|auth|credential)[a-z_]*)=)[^&\s;]+"), r"\1[redacted]"),
    (re.compile(r"(?i)\b((?:[a-z_]*(?:token|secret|password|passwd|api_key|apikey))\s*[=:]\s*)\S+"), r"\1[redacted]"),
    (re.compile(r"\b[A-Za-z0-9+/_\-]{32,}={0,2}"), "[redacted]"),     # long opaque strings: keys, hashes, JWT parts
]


def redact(text: str) -> str:
    for rx, sub in _SECRETS:
        text = rx.sub(sub, text)
    return text


def error_summary(err: object, limit: int = 200) -> str:
    """What Ned is told when a run fails: the exception's class and the first line of its message, with anything that
    looks like a credential removed, at most `limit` characters. A plain string is used as is (after redaction)."""
    if isinstance(err, BaseException):
        first = (str(err).strip().splitlines() or [""])[0]
        text = f"{type(err).__name__}: {first}" if first else type(err).__name__
    else:
        text = (str(err).strip().splitlines() or [""])[0]
    text = redact(re.sub(r"[\x00-\x1f\x7f]", " ", text))
    return text if len(text) <= limit else text[: limit - 3] + "..."
