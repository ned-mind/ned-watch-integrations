"""The Ned Watch client. Stdlib only (urllib); uses httpx for the async calls when it is installed.

    from nedwatch import Ned
    ned = Ned()                                     # NED_AGENT_KEY, NED_CALLBACK_URL from the environment

    @ned.deadman("nightly-sync", every="1h")        # checks in each time the function returns without raising
    def sync(): ...

    with ned.run("etl", max="20m"):                 # overrun: Ned fires if this block is still running after 20 minutes
        ...
"""
from __future__ import annotations

import asyncio
import functools
import inspect
import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request
import uuid
from typing import Any, Callable, Dict, Optional, TypeVar, Union

from . import __version__
from ._state import State, StateArg
from ._util import Duration, error_summary, fingerprint, seconds, slug
from .detect import default_name, detect_framework

log = logging.getLogger("nedwatch")

DEFAULT_BASE = "https://api.ned.watch"
REGIONS = {"us": "https://api.ned.watch", "eu": "https://api-eu.ned.watch"}
REGISTER_TIMEOUT = 75.0          # Ned delivers the signed test callback before it answers a new registration
RETRYABLE = {429, 500, 502, 503, 504}

F = TypeVar("F", bound=Callable[..., Any])


class NedError(Exception):
    """Ned answered with an error (status set), or couldn't be reached (status None)."""

    def __init__(self, message: str, status: Optional[int] = None, detail: Any = None):
        super().__init__(message)
        self.status = status
        self.detail = detail


class NedConfigError(NedError):
    """Something the caller has to supply is missing (callback URL, signing secret)."""


def _ref_clean(ref: str) -> str:
    import re
    return re.sub(r"[^a-z0-9._-]", "", ref.strip().lower()[:32]) or "python"


class Ned:
    """A Ned Watch client.

    agent_key     your key (nw_...). Default: $NED_AGENT_KEY, else the one saved in the state file. With none, the first
                  registration creates your agent and the key is saved to the state file (never printed).
    base          API base URL. Default: $NED_API (or $NED_WATCH_API), else by region, else https://api.ned.watch.
    region        "us" or "eu" (https://api-eu.ned.watch). Default: $NED_REGION, else "us".
    callback_url  where Ned POSTs signed fire/clear messages. Default: $NED_CALLBACK_URL. Needed to register a watch.
    ref           which integration brought you in (sent as X-Ned-Ref). Default: $NED_REF, else the detected framework,
                  else "python".
    state         None: the default state file; False: remember nothing on disk; a path: that file.
    strict        False (default): the decorator and run() never let a Ned problem break your job; they log a warning.
                  True: they raise NedError.
    """

    def __init__(self, agent_key: Optional[str] = None, base: Optional[str] = None, *, region: Optional[str] = None,
                 callback_url: Optional[str] = None, ref: Optional[str] = None, state: StateArg = None,
                 timeout: float = 15.0, retries: int = 2, strict: bool = False):
        region = (region or os.environ.get("NED_REGION") or "us").lower()
        if region not in REGIONS:
            raise ValueError("region must be 'us' or 'eu'")
        self.base = (base or os.environ.get("NED_API") or os.environ.get("NED_WATCH_API") or REGIONS[region]).rstrip("/")
        self.state = State(state)
        self._key = agent_key or os.environ.get("NED_AGENT_KEY") or self.state.agent_key(self.base)
        self.callback_url = callback_url or os.environ.get("NED_CALLBACK_URL")
        self._ref_explicit = ref or os.environ.get("NED_REF")
        self.timeout = timeout
        self.retries = retries
        self.strict = strict
        self._lock = threading.RLock()

    # ---------- identity ----------

    @property
    def ref(self) -> str:
        return _ref_clean(self._ref_explicit or detect_framework() or "python")

    def _default_ref(self, ref: str) -> "Ned":
        """Integrations call this: their name becomes the ref unless the caller set one explicitly."""
        if not self._ref_explicit:
            self._ref_explicit = ref
        return self

    @property
    def has_key(self) -> bool:
        return bool(self._key)

    def __repr__(self) -> str:
        return f"Ned(base={self.base!r}, ref={self.ref!r}, key={'set' if self._key else 'none'})"

    # ---------- HTTP ----------

    def _headers(self, bearer: Optional[str]) -> Dict[str, str]:
        h = {"User-Agent": f"ned-watch-py/{__version__}", "X-Ned-Ref": self.ref, "Accept": "application/json"}
        if bearer:
            h["Authorization"] = f"Bearer {bearer}"
        return h

    @staticmethod
    def _parse(status: int, raw: bytes) -> Any:
        if status == 204 or not raw:
            return {}
        try:
            return json.loads(raw)
        except ValueError:
            return {"raw": raw[:500].decode("utf-8", "replace")}

    @staticmethod
    def _error(method: str, path: str, status: int, body: Any) -> NedError:
        detail = body.get("detail", body) if isinstance(body, dict) else body
        msg = detail.get("error") if isinstance(detail, dict) and detail.get("error") else detail
        return NedError(f"Ned answered HTTP {status} to {method} {path.split('?')[0]}: {msg}", status, detail)

    def _send_once(self, method: str, path: str, bearer: Optional[str], body: Optional[dict], timeout: float):
        data = json.dumps(body).encode() if body is not None else None
        h = self._headers(bearer)
        if data is not None:
            h["Content-Type"] = "application/json"
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=h)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, r.read(), r.headers.get("Retry-After")
        except urllib.error.HTTPError as e:
            return e.code, e.read(), e.headers.get("Retry-After") if e.headers else None

    def _call(self, method: str, path: str, *, bearer: Optional[str] = None, body: Optional[dict] = None,
              timeout: Optional[float] = None, retries: Optional[int] = None) -> Any:
        tries = 1 + (self.retries if retries is None else retries)
        last: Optional[Exception] = None
        for i in range(tries):
            try:
                status, raw, ra = self._send_once(method, path, bearer, body, timeout or self.timeout)
            except (urllib.error.URLError, OSError, TimeoutError) as e:
                last = NedError(f"couldn't reach Ned at {self.base}: {getattr(e, 'reason', e)}")
            else:
                parsed = self._parse(status, raw)
                if 200 <= status < 300:
                    return parsed
                last = self._error(method, path, status, parsed)
                if status not in RETRYABLE:
                    raise last
                if ra and ra.isdigit() and int(ra) > 10:
                    raise last
            if i < tries - 1:
                time.sleep(min(10.0, 0.5 * (3 ** i)))
        assert last is not None
        raise last

    async def _acall(self, method: str, path: str, *, bearer: Optional[str] = None, body: Optional[dict] = None,
                     timeout: Optional[float] = None, retries: Optional[int] = None) -> Any:
        try:
            import httpx  # optional
        except ImportError:
            return await asyncio.get_running_loop().run_in_executor(
                None, functools.partial(self._call, method, path, bearer=bearer, body=body, timeout=timeout, retries=retries))
        tries = 1 + (self.retries if retries is None else retries)
        last: Optional[Exception] = None
        async with httpx.AsyncClient(timeout=timeout or self.timeout) as c:
            for i in range(tries):
                try:
                    r = await c.request(method, self.base + path, headers=self._headers(bearer), json=body)
                except httpx.HTTPError as e:
                    last = NedError(f"couldn't reach Ned at {self.base}: {type(e).__name__}")
                else:
                    parsed = self._parse(r.status_code, r.content)
                    if 200 <= r.status_code < 300:
                        return parsed
                    last = self._error(method, path, r.status_code, parsed)
                    ra = r.headers.get("retry-after")
                    if r.status_code not in RETRYABLE or (ra and ra.isdigit() and int(ra) > 10):
                        raise last
                if i < tries - 1:
                    await asyncio.sleep(min(10.0, 0.5 * (3 ** i)))
        assert last is not None
        raise last

    # ---------- registration ----------

    def _body(self, type_: str, callback_url: Optional[str], **fields: Any) -> dict:
        cb = callback_url or self.callback_url
        if not cb:
            raise NedConfigError("no callback URL: pass callback_url= or set NED_CALLBACK_URL (a free test one: "
                                 "https://webhook.site). Ned POSTs signed fire/clear messages there.")
        body = {"type": type_, "callback_url": cb, **{k: v for k, v in fields.items() if v is not None}}
        if not self._key:
            body["meta"] = {"ref": self.ref}
        return body

    def _after_register(self, slot: Optional[str], body: dict, res: dict, old: Optional[dict], server_armed: bool = False) -> dict:
        if res.get("agent_key"):
            with self._lock:
                self._key = res["agent_key"]
                self.state.set_agent_key(self.base, self._key)
            log.info("Ned created your agent; its key is saved in %s", self.state.path or "memory")
        tc = res.get("test_callback") or {}
        if tc and not tc.get("delivered"):
            log.warning("Ned couldn't deliver the test callback for %s: %s", res.get("watch_id"), tc.get("problem") or tc.get("status"))
        rec = {"id": res["watch_id"], "secret": res["signing_secret"], "fp": fingerprint(body), "type": body["type"],
               "new": not res.get("existing")}
        if server_armed:
            rec["armed"] = True               # v1.9: condition.arm set the clock at registration (or at the original one)
        if slot:
            self.state.set_watch(self.base, slot, rec)
        return rec

    def register(self, type: str, *, callback_url: Optional[str] = None, interval_s: Optional[int] = None,
                 target: Optional[str] = None, condition: Optional[dict] = None, max_runtime_s: Optional[int] = None,
                 expect: Optional[dict] = None) -> dict:
        """POST /v1/watches as is (any type). Returns Ned's answer; agent_key from it is saved, never returned twice."""
        body = self._body(type, callback_url, interval_s=interval_s, target=target, condition=condition or None,
                          max_runtime_s=max_runtime_s, expect=expect)
        res = self._call("POST", "/v1/watches", bearer=self._key, body=body, timeout=REGISTER_TIMEOUT,
                         retries=None if self._key else 0)      # no key yet: a blind retry could make a second agent
        self._after_register(None, body, res, None)
        return res

    def _ensure(self, slot: str, body: dict, force: bool = False) -> dict:
        fp = fingerprint(body)
        old = self.state.watch(self.base, slot)
        if old and old.get("fp") == fp and not force:
            return old
        wanted = body
        if not self._key:
            body = {**body, "meta": {"ref": self.ref}}
        try:
            res = self._call("POST", "/v1/watches", bearer=self._key, body=body, timeout=REGISTER_TIMEOUT,
                             retries=None if self._key else 0)
        except NedError as e:
            body = self._without_arm(body, e)
            res = self._call("POST", "/v1/watches", bearer=self._key, body=body, timeout=REGISTER_TIMEOUT,
                             retries=None if self._key else 0)
        rec = self._after_register(slot, wanted, res, old, server_armed=bool((body.get("condition") or {}).get("arm")))
        self._retire(old, rec)
        return rec

    @staticmethod
    def _without_arm(body: dict, e: "NedError") -> dict:
        """A server that refuses condition.arm (older than v1.9 with stricter validation, or a proxy): register without
        it; the client then arms with a first check-in instead. Any other error is raised."""
        cond = body.get("condition") or {}
        if e.status != 422 or not cond.get("arm") or "arm" not in json.dumps(e.detail, default=str):
            raise e
        log.info("Ned refused condition.arm; arming with a first check-in instead")
        return {**body, "condition": {k: v for k, v in cond.items() if k != "arm"}}

    async def _aensure(self, slot: str, body: dict, force: bool = False) -> dict:
        fp = fingerprint(body)
        old = self.state.watch(self.base, slot)
        if old and old.get("fp") == fp and not force:
            return old
        wanted = body
        if not self._key:
            body = {**body, "meta": {"ref": self.ref}}
        try:
            res = await self._acall("POST", "/v1/watches", bearer=self._key, body=body, timeout=REGISTER_TIMEOUT,
                                    retries=None if self._key else 0)
        except NedError as e:
            body = self._without_arm(body, e)
            res = await self._acall("POST", "/v1/watches", bearer=self._key, body=body, timeout=REGISTER_TIMEOUT,
                                    retries=None if self._key else 0)
        rec = self._after_register(slot, wanted, res, old, server_armed=bool((body.get("condition") or {}).get("arm")))
        await asyncio.get_running_loop().run_in_executor(None, self._retire, old, rec)
        return rec

    def _retire(self, old: Optional[dict], new: dict) -> None:
        """The same name with new settings is a new watch on Ned's side; cancel the old one so it doesn't fire for
        check-ins that now go elsewhere."""
        if old and old.get("id") and old["id"] != new["id"] and self._key:
            try:
                self._call("DELETE", f"/v1/watches/{old['id']}", bearer=self._key, retries=0)
            except NedError as e:
                log.warning("couldn't cancel the previous watch %s: %s", old["id"], e)

    # ---------- handles ----------

    def deadman(self, name: Optional[str] = None, every: Duration = "1h", *, grace: Optional[Duration] = None,
                callback_url: Optional[str] = None) -> "Deadman":
        """A deadman watch named `name`: Ned fires if no check-in arrives within `every` (or `grace`). Created on first
        use, reused afterwards (same name + settings = same watch). Use it as a decorator, or call .checkin()."""
        return Deadman(self, name or default_name(), seconds(every), seconds(grace) if grace is not None else None, callback_url)

    def overrun(self, name: Optional[str] = None, max: Duration = "1h", *, callback_url: Optional[str] = None) -> "Overrun":
        """An overrun watch named `name`: Ned fires if a run is still open `max` after start()."""
        return Overrun(self, name or default_name(), seconds(max), callback_url)

    def run(self, name: Optional[str] = None, max: Duration = "1h", *, every: Optional[Duration] = None,
            run_id: Optional[str] = None, on_error: str = "report", callback_url: Optional[str] = None) -> "Run":
        """Context manager (sync or async) and decorator around one run of a job.

        start on enter, finish on a clean exit. With every=, also a deadman that is checked in after each clean run.
        On an exception:
          on_error="report"      (default) finish with status "failed" and a short error (exception class + first
                                 line, credentials redacted, <= 200 chars): Ned fires at once. No deadman check-in.
          on_error="leave_open"  leave the run open: Ned fires when max passes
          on_error="finish"      finish it as if it succeeded (the failure is not reported)
        "auto" is accepted as an alias of "report".
        """
        if on_error not in ON_ERROR:
            raise ValueError("on_error must be 'report', 'leave_open' or 'finish'")
        nm = name or default_name()
        return Run(self, self.overrun(nm, max, callback_url=callback_url),
                   self.deadman(nm, every, callback_url=callback_url) if every is not None else None, run_id, on_error)

    # ---------- direct calls ----------

    def _secret_for(self, watch: Union[str, "Deadman", "Overrun"], signing_secret: Optional[str]) -> tuple:
        if isinstance(watch, _Handle):
            rec = watch.ensure()._rec
            return rec["id"], signing_secret or rec["secret"]
        wid = str(watch)
        if not wid.startswith("w_"):                        # a name: look it up in the state file
            rec = self.state.watch(self.base, f"deadman:{slug(wid)}") or self.state.watch(self.base, f"overrun:{slug(wid)}")
            if not rec:
                raise NedConfigError(f"no watch named {wid!r} in {self.state.path or 'memory'}; register it first")
            return rec["id"], signing_secret or rec["secret"]
        if signing_secret:
            return wid, signing_secret
        rec = self.state.by_id(self.base, wid)
        if rec:
            return wid, rec["secret"]
        if os.environ.get("NED_SIGNING_SECRET") and os.environ.get("NED_WATCH_ID", wid) == wid:
            return wid, os.environ["NED_SIGNING_SECRET"]
        raise NedConfigError(f"no signing secret for {wid}: pass signing_secret= or set NED_SIGNING_SECRET")

    def checkin(self, watch: Union[str, "Deadman"], signing_secret: Optional[str] = None) -> dict:
        """POST /v1/checkin/{id}. `watch` is a watch id (w_...), a name registered by this client, or a Deadman."""
        wid, sec = self._secret_for(watch, signing_secret)
        return self._call("POST", f"/v1/checkin/{wid}", bearer=sec)

    async def acheckin(self, watch: Union[str, "Deadman"], signing_secret: Optional[str] = None) -> dict:
        if isinstance(watch, _Handle):
            await watch.aensure()
        wid, sec = self._secret_for(watch, signing_secret)
        return await self._acall("POST", f"/v1/checkin/{wid}", bearer=sec)

    def start(self, watch: Union[str, "Overrun"], run_id: Optional[str] = None, signing_secret: Optional[str] = None) -> dict:
        wid, sec = self._secret_for(watch, signing_secret)
        return self._call("POST", f"/v1/watches/{wid}/start", bearer=sec, body={"run_id": run_id} if run_id else {})

    async def astart(self, watch: Union[str, "Overrun"], run_id: Optional[str] = None, signing_secret: Optional[str] = None) -> dict:
        if isinstance(watch, _Handle):
            await watch.aensure()
        wid, sec = self._secret_for(watch, signing_secret)
        return await self._acall("POST", f"/v1/watches/{wid}/start", bearer=sec, body={"run_id": run_id} if run_id else {})

    def finish(self, watch: Union[str, "Overrun"], run_id: Optional[str] = None, signing_secret: Optional[str] = None,
               *, failed: bool = False, error: Optional[str] = None) -> dict:
        """POST /finish. failed=True reports the run as crashed (Ned fires at once, with `error`, at most 200 chars)."""
        wid, sec = self._secret_for(watch, signing_secret)
        return self._call("POST", f"/v1/watches/{wid}/finish", bearer=sec, body=_finish_body(run_id, failed, error))

    async def afinish(self, watch: Union[str, "Overrun"], run_id: Optional[str] = None, signing_secret: Optional[str] = None,
               *, failed: bool = False, error: Optional[str] = None) -> dict:
        """POST /finish. failed=True reports the run as crashed (Ned fires at once, with `error`, at most 200 chars)."""
        if isinstance(watch, _Handle):
            await watch.aensure()
        wid, sec = self._secret_for(watch, signing_secret)
        return await self._acall("POST", f"/v1/watches/{wid}/finish", bearer=sec, body=_finish_body(run_id, failed, error))

    def _need_key(self) -> str:
        if not self._key:
            raise NedConfigError("this call needs your agent key: set NED_AGENT_KEY (it is issued by your first registration)")
        return self._key

    def get(self, watch_id: str) -> dict:
        return self._call("GET", f"/v1/watches/{watch_id}", bearer=self._need_key())

    async def aget(self, watch_id: str) -> dict:
        return await self._acall("GET", f"/v1/watches/{watch_id}", bearer=self._need_key())

    def watches(self) -> list:
        return self._call("GET", "/v1/watches", bearer=self._need_key())

    def cancel(self, watch_id: str) -> None:
        self._call("DELETE", f"/v1/watches/{watch_id}", bearer=self._need_key())
        for slot, rec in self.state.watches(self.base).items():
            if rec.get("id") == watch_id:
                self.state.set_watch(self.base, slot, None)

    def balance(self) -> dict:
        return self._call("GET", "/v1/balance", bearer=self._need_key())

    def health(self) -> dict:
        return self._call("GET", "/health", retries=0)

    # ---------- fail-open ----------

    def _soft(self, what: str, fn: Callable[[], Any]) -> Any:
        try:
            return fn()
        except NedError as e:
            if self.strict:
                raise
            log.warning("Ned Watch %s failed (your job is unaffected): %s", what, e)
            return None

    async def _asoft(self, what: str, coro: Any) -> Any:
        try:
            return await coro
        except NedError as e:
            if self.strict:
                raise
            log.warning("Ned Watch %s failed (your job is unaffected): %s", what, e)
            return None


def _finish_body(run_id: Optional[str], failed: bool, error: Optional[str]) -> dict:
    b: Dict[str, Any] = {"run_id": run_id} if run_id else {}
    if failed:
        b["status"] = "failed"
        if error:
            b["error"] = error_summary(error)
    return b


ON_ERROR = ("report", "auto", "leave_open", "finish")


class _Handle:
    kind = ""

    def __init__(self, ned: Ned, name: str, callback_url: Optional[str]):
        self.ned = ned
        self.name = slug(name)
        self.callback_url = callback_url
        self._rec: Optional[dict] = None
        self._lock = threading.Lock()

    @property
    def slot(self) -> str:
        return f"{self.kind}:{self.name}"

    def body(self) -> dict:
        raise NotImplementedError

    def ensure(self, force: bool = False):
        """Register the watch if this client hasn't yet (or reuse the identical one). Returns self."""
        with self._lock:
            if self._rec is None or force:
                self._rec = self.ned._ensure(self.slot, self.ned._body(self.kind, self.callback_url, **self.body()), force)
        return self

    async def aensure(self, force: bool = False):
        if self._rec is None or force:
            self._rec = await self.ned._aensure(self.slot, self.ned._body(self.kind, self.callback_url, **self.body()), force)
        return self

    @property
    def id(self) -> str:
        return self.ensure()._rec["id"]  # type: ignore[index]

    @property
    def signing_secret(self) -> str:
        return self.ensure()._rec["secret"]  # type: ignore[index]

    def cancel(self) -> None:
        self.ned.cancel(self.id)
        self._rec = None

    def _retry_gone(self, fn: Callable[[], Any]) -> Any:
        """A watch cancelled elsewhere answers 404: register it again once and retry."""
        try:
            return fn()
        except NedError as e:
            if e.status != 404:
                raise
            self.ensure(force=True)
            return fn()

    async def _aretry_gone(self, fn: Callable[[], Any]) -> Any:
        try:
            return await fn()
        except NedError as e:
            if e.status != 404:
                raise
            await self.aensure(force=True)
            return await fn()

    def __repr__(self) -> str:
        return f"{type(self).__name__}(name={self.name!r}, id={self._rec['id'] if self._rec else None!r})"


class Deadman(_Handle):
    kind = "deadman"

    def __init__(self, ned: Ned, name: str, every_s: int, grace_s: Optional[int], callback_url: Optional[str]):
        super().__init__(ned, name, callback_url)
        self.every_s, self.grace_s = every_s, grace_s
        self._last_beat = -1e18

    def body(self) -> dict:
        cond: Dict[str, Any] = {"label": self.name, "arm": True}       # v1.9: the clock starts at registration
        if self.grace_s is not None:
            cond["grace_s"] = self.grace_s
        return {"interval_s": self.every_s, "condition": cond}

    def checkin(self) -> dict:
        self.ensure()
        out = self._retry_gone(lambda: self.ned.checkin(self))
        self._mark_armed()
        return out

    async def acheckin(self) -> dict:
        await self.aensure()
        out = await self._aretry_gone(lambda: self.ned.acheckin(self))
        self._mark_armed()
        return out

    def _mark_armed(self) -> None:
        if self._rec is not None and not self._rec.get("armed"):
            self._rec = {**self._rec, "armed": True}
            self.ned.state.set_watch(self.ned.base, self.slot, self._rec)

    def arm(self) -> "Deadman":
        """Make sure the watch exists and its clock is running. Ned's clock starts at the first check-in, so a job whose
        very first run fails would otherwise never be noticed. Checks in once, the first time only; never raises."""
        def go() -> None:
            self.ensure()
            if not self._needs_arming():
                return
            if (self._rec or {}).get("new") or self.ned.get(self.id).get("last_checkin") is None:
                self.checkin()
            else:
                self._mark_armed()        # an existing watch that has checked in before (e.g. a container with no state file)
        self.ned._soft(f"arming {self.name}", go)
        return self

    def _needs_arming(self) -> bool:
        return not (self._rec or {}).get("armed")

    async def aarm(self) -> "Deadman":
        async def go() -> None:
            await self.aensure()
            if not self._needs_arming():
                return
            if (self._rec or {}).get("new") or (await self.ned.aget(self.id)).get("last_checkin") is None:
                await self.acheckin()
            else:
                self._mark_armed()
        await self.ned._asoft(f"arming {self.name}", go())
        return self

    def beat(self, min_interval: float = 30.0) -> Optional[dict]:
        """A throttled, never-raising check-in for progress events (each tool call, step, LLM reply): proves the agent is
        alive while it works. At most one call per `min_interval` seconds (Ned allows 60 check-ins a minute)."""
        now = time.monotonic()
        with self._lock:
            if now - self._last_beat < min_interval:
                return None
            self._last_beat = now
        try:
            return self.checkin()
        except NedError as e:
            log.warning("Ned Watch heartbeat for %s failed (your job is unaffected): %s", self.name, e)
            return None

    async def abeat(self, min_interval: float = 30.0) -> Optional[dict]:
        now = time.monotonic()
        with self._lock:
            if now - self._last_beat < min_interval:
                return None
            self._last_beat = now
        try:
            return await self.acheckin()
        except NedError as e:
            log.warning("Ned Watch heartbeat for %s failed (your job is unaffected): %s", self.name, e)
            return None

    def __call__(self, fn: F) -> F:
        """Decorator: check in each time `fn` returns without raising. Works on sync and async functions."""
        if inspect.iscoroutinefunction(fn):
            @functools.wraps(fn)
            async def awrapper(*a: Any, **k: Any) -> Any:
                await self.aarm()
                out = await fn(*a, **k)
                await self.ned._asoft(f"check-in for {self.name}", self.acheckin())
                return out
            return awrapper  # type: ignore[return-value]

        @functools.wraps(fn)
        def wrapper(*a: Any, **k: Any) -> Any:
            self.arm()
            out = fn(*a, **k)
            self.ned._soft(f"check-in for {self.name}", self.checkin)
            return out
        return wrapper  # type: ignore[return-value]


class Overrun(_Handle):
    kind = "overrun"

    def __init__(self, ned: Ned, name: str, max_s: int, callback_url: Optional[str]):
        super().__init__(ned, name, callback_url)
        self.max_s = max_s

    def body(self) -> dict:
        return {"max_runtime_s": self.max_s, "condition": {"label": self.name}}

    def start(self, run_id: Optional[str] = None) -> dict:
        self.ensure()
        return self._retry_gone(lambda: self.ned.start(self, run_id))

    def finish(self, run_id: Optional[str] = None, *, failed: bool = False, error: Optional[str] = None) -> dict:
        self.ensure()
        return self.ned.finish(self, run_id, failed=failed, error=error)

    async def astart(self, run_id: Optional[str] = None) -> dict:
        await self.aensure()
        return await self._aretry_gone(lambda: self.ned.astart(self, run_id))

    async def afinish(self, run_id: Optional[str] = None, *, failed: bool = False, error: Optional[str] = None) -> dict:
        await self.aensure()
        return await self.ned.afinish(self, run_id, failed=failed, error=error)


class Run:
    """One run of a job. Use with `with`, `async with`, or as a decorator (a new run per call)."""

    def __init__(self, ned: Ned, overrun: Overrun, deadman: Optional[Deadman], run_id: Optional[str], on_error: str):
        self.ned, self.overrun, self.deadman = ned, overrun, deadman
        self._fixed_run_id = run_id
        self.on_error = on_error
        self.run_id: Optional[str] = None
        self.started: Optional[dict] = None
        self.finished: Optional[dict] = None

    def _new_id(self) -> str:
        return self._fixed_run_id or f"{self.overrun.name[:40]}-{uuid.uuid4().hex[:12]}"

    def _close(self, et: Any, ev: Any) -> Optional[Dict[str, Any]]:
        """finish() kwargs for this exit, or None to leave the run open."""
        if et is None or self.on_error == "finish":
            return {}
        if self.on_error == "leave_open":
            return None
        return {"failed": True, "error": getattr(ev, "ned_error", None) or error_summary(ev if ev is not None else et.__name__)}

    def __enter__(self) -> "Run":
        if self.deadman is not None:
            self.deadman.arm()
        self.run_id = self._new_id()
        self.started = self.ned._soft(f"start of {self.overrun.name}", lambda: self.overrun.start(self.run_id))
        return self

    def __exit__(self, et, ev, tb) -> bool:
        kw = self._close(et, ev)
        if self.started is not None and kw is not None:
            self.finished = self.ned._soft(f"finish of {self.overrun.name}", lambda: self.overrun.finish(self.run_id, **kw))
        if et is None and self.deadman is not None:
            self.ned._soft(f"check-in for {self.deadman.name}", self.deadman.checkin)
        return False

    async def __aenter__(self) -> "Run":
        if self.deadman is not None:
            await self.deadman.aarm()
        self.run_id = self._new_id()
        self.started = await self.ned._asoft(f"start of {self.overrun.name}", self.overrun.astart(self.run_id))
        return self

    async def __aexit__(self, et, ev, tb) -> bool:
        kw = self._close(et, ev)
        if self.started is not None and kw is not None:
            self.finished = await self.ned._asoft(f"finish of {self.overrun.name}", self.overrun.afinish(self.run_id, **kw))
        if et is None and self.deadman is not None:
            await self.ned._asoft(f"check-in for {self.deadman.name}", self.deadman.acheckin())
        return False

    def _fresh(self) -> "Run":
        return Run(self.ned, self.overrun, self.deadman, self._fixed_run_id, self.on_error)

    def __call__(self, fn: F) -> F:
        if inspect.iscoroutinefunction(fn):
            @functools.wraps(fn)
            async def awrapper(*a: Any, **k: Any) -> Any:
                async with self._fresh():
                    return await fn(*a, **k)
            return awrapper  # type: ignore[return-value]

        @functools.wraps(fn)
        def wrapper(*a: Any, **k: Any) -> Any:
            with self._fresh():
                return fn(*a, **k)
        return wrapper  # type: ignore[return-value]
