"""Check that a callback really came from Ned (X-Ned-Signature = hex(HMAC-SHA256(secret, timestamp + "." + raw_body)))."""
from __future__ import annotations

import hashlib
import hmac
import time
from typing import Mapping, Optional, Union


def verify_signature(signing_secret: str, headers: Mapping[str, str], raw_body: Union[bytes, str],
                     tolerance_s: int = 300, now: Optional[float] = None) -> bool:
    h = {k.lower(): v for k, v in headers.items()}
    ts, sig = h.get("x-ned-timestamp", ""), h.get("x-ned-signature", "")
    if not ts.isdigit() or not sig:
        return False
    if abs((now if now is not None else time.time()) - int(ts)) > tolerance_s:
        return False
    body = raw_body.encode() if isinstance(raw_body, str) else raw_body
    want = hmac.new(signing_secret.encode(), ts.encode() + b"." + body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(want, sig.strip().lower())
