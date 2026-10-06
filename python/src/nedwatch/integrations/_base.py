"""Shared plumbing for the framework integrations: one deadman (did the agent finish / is it still alive?) and an
optional overrun (is one run taking too long?), driven by the framework's own lifecycle events. Never raises into the
framework unless the Ned client was made with strict=True."""
from __future__ import annotations

import threading
import uuid
from typing import Any, Dict, Optional

from ..client import ON_ERROR, Deadman, Ned, Overrun
from .._util import Duration, error_summary, slug
from ..detect import default_name


class Monitor:
    def __init__(self, ref: str, name: Optional[str] = None, every: Optional[Duration] = None, max: Optional[Duration] = None,
                 ned: Optional[Ned] = None, on_error: str = "report", heartbeat: bool = False, heartbeat_every: float = 30.0,
                 callback_url: Optional[str] = None):
        if on_error not in ON_ERROR:
            raise ValueError("on_error must be 'report', 'leave_open' or 'finish'")
        self.ned = (ned or Ned(ref=None))._default_ref(ref)
        self.name = slug(name) if name else None
        self.every = "1h" if every is None and max is None else every
        self.max = max
        self.on_error = on_error
        self.heartbeat = heartbeat
        self.heartbeat_every = heartbeat_every
        self.callback_url = callback_url
        self.deadman: Optional[Deadman] = None
        self.overrun: Optional[Overrun] = None
        self._open: Dict[Any, str] = {}
        self._lock = threading.Lock()

    def _handles(self, hint: Optional[str] = None) -> None:
        with self._lock:
            if self.name is None:
                self.name = slug(hint) if hint else slug(default_name())
            if self.every is not None and self.deadman is None:
                self.deadman = self.ned.deadman(self.name, self.every, callback_url=self.callback_url)
            if self.max is not None and self.overrun is None:
                self.overrun = self.ned.overrun(self.name, self.max, callback_url=self.callback_url)

    def _run_id(self) -> str:
        return f"{(self.name or 'run')[:40]}-{uuid.uuid4().hex[:12]}"

    def _close_kw(self, error: Any) -> Optional[Dict[str, Any]]:
        """finish() kwargs for a failed run, or None to leave it open. report (default): status failed + short error."""
        if self.on_error == "leave_open":
            return None
        if self.on_error == "finish":
            return {}
        return {"failed": True, "error": error_summary(error if error is not None else "run failed")}

    # ---------- sync ----------

    def started(self, key: Any, hint: Optional[str] = None) -> None:
        self._handles(hint)
        if self.deadman is not None:
            self.deadman.arm()
        ow = self.overrun
        if ow is not None:
            rid = self._run_id()
            if self.ned._soft(f"start of {self.name}", lambda: ow.start(rid)) is not None:
                self._open[key] = rid

    def succeeded(self, key: Any, hint: Optional[str] = None) -> None:
        self._handles(hint)
        rid = self._open.pop(key, None)
        ow = self.overrun
        if rid and ow is not None:
            self.ned._soft(f"finish of {self.name}", lambda: ow.finish(rid))
        if self.deadman is not None:
            self.ned._soft(f"check-in for {self.name}", self.deadman.checkin)

    def failed(self, key: Any, error: Any = None) -> None:
        rid = self._open.pop(key, None)
        ow = self.overrun
        kw = self._close_kw(error)
        if rid and ow is not None and kw is not None:
            self.ned._soft(f"finish of {self.name}", lambda: ow.finish(rid, **kw))

    def beat(self, hint: Optional[str] = None) -> None:
        if not self.heartbeat:
            return
        self._handles(hint)
        if self.deadman is not None:
            self.deadman.beat(self.heartbeat_every)

    # ---------- async ----------

    async def astarted(self, key: Any, hint: Optional[str] = None) -> None:
        self._handles(hint)
        if self.deadman is not None:
            await self.deadman.aarm()
        if self.overrun is not None:
            rid = self._run_id()
            if await self.ned._asoft(f"start of {self.name}", self.overrun.astart(rid)) is not None:
                self._open[key] = rid

    async def asucceeded(self, key: Any, hint: Optional[str] = None) -> None:
        self._handles(hint)
        rid = self._open.pop(key, None)
        if rid and self.overrun is not None:
            await self.ned._asoft(f"finish of {self.name}", self.overrun.afinish(rid))
        if self.deadman is not None:
            await self.ned._asoft(f"check-in for {self.name}", self.deadman.acheckin())

    async def afailed(self, key: Any, error: Any = None) -> None:
        rid = self._open.pop(key, None)
        ow = self.overrun
        kw = self._close_kw(error)
        if rid and ow is not None and kw is not None:
            await self.ned._asoft(f"finish of {self.name}", ow.afinish(rid, **kw))

    async def abeat(self, hint: Optional[str] = None) -> None:
        if not self.heartbeat:
            return
        self._handles(hint)
        if self.deadman is not None:
            await self.deadman.abeat(self.heartbeat_every)
