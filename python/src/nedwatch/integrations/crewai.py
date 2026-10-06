"""CrewAI: a kickoff wrapper, step/task callbacks, and an event-bus listener.

    from nedwatch.integrations.crewai import kickoff
    result = kickoff(crew, inputs={...}, every="1d", max="30m")      # instead of crew.kickoff(inputs={...})

or keep calling crew.kickoff() yourself and attach the callbacks:

    ned = NedCrew("research-crew", every="1d", max="30m").attach(crew)
    ned.kickoff(crew, inputs={...})

or, for crews you don't kick off yourself (crewai run, Flows), listen on CrewAI's event bus:

    NedCrewListener("research-crew", every="1d")         # create once, at import time

What each piece does:
  kickoff start  overrun start (with max=)
  kickoff end    overrun finish, deadman check-in
  kickoff error  no check-in; the overrun run is finished as failed with the error (Ned fires at once)
  each step / task  a throttled heartbeat on the deadman (opt in with heartbeat=True: for long-lived agents; a beat counts as alive, so it can mask a run that works and then fails)
Sent to Ned as X-Ned-Ref: crewai.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from ..client import Ned
from .._util import Duration
from ._base import Monitor

REF = "crewai"


def _crew_name(crew: Any) -> Optional[str]:
    n = getattr(crew, "name", None)
    return n if n and n != "crew" else None


def _chain(first: Optional[Callable[[Any], Any]], second: Callable[[Any], Any]) -> Callable[[Any], Any]:
    if first is None:
        return second

    def both(arg: Any) -> Any:
        out = first(arg)
        second(arg)
        return out
    both.__ned__ = True  # type: ignore[attr-defined]
    return both


class NedCrew:
    """name defaults to crew.name (if you set one), else the script name. every defaults to "1h" when max is not set."""

    def __init__(self, name: Optional[str] = None, every: Optional[Duration] = None, max: Optional[Duration] = None, *,
                 ned: Optional[Ned] = None, on_error: str = "report", heartbeat: bool = False, heartbeat_every: float = 30.0,
                 callback_url: Optional[str] = None):
        self.monitor = Monitor(REF, name, every, max, ned, on_error, heartbeat, heartbeat_every, callback_url)

    @property
    def ned(self) -> Ned:
        return self.monitor.ned

    # CrewAI calls these with the agent's step (AgentAction / AgentFinish) and the TaskOutput.
    def step_callback(self, step: Any) -> None:
        self.monitor.beat()

    def task_callback(self, output: Any) -> None:
        self.monitor.beat()

    def attach(self, crew: Any) -> "NedCrew":
        """Set crew.step_callback / crew.task_callback (keeping any you already had: yours run first)."""
        if not getattr(crew.step_callback, "__ned__", False):
            crew.step_callback = _chain(crew.step_callback, self.step_callback)
        if not getattr(crew.task_callback, "__ned__", False):
            crew.task_callback = _chain(crew.task_callback, self.task_callback)
        self.monitor._handles(_crew_name(crew))
        return self

    def kickoff(self, crew: Any, inputs: Optional[Dict[str, Any]] = None, **kw: Any) -> Any:
        key = object()
        self.monitor.started(key, _crew_name(crew))
        try:
            out = crew.kickoff(inputs=inputs, **kw)
        except BaseException as e:
            self.monitor.failed(key, e)
            raise
        self.monitor.succeeded(key)
        return out

    async def akickoff(self, crew: Any, inputs: Optional[Dict[str, Any]] = None, **kw: Any) -> Any:
        key = object()
        await self.monitor.astarted(key, _crew_name(crew))
        try:
            out = await crew.kickoff_async(inputs=inputs, **kw)
        except BaseException as e:
            await self.monitor.afailed(key, e)
            raise
        await self.monitor.asucceeded(key)
        return out


def kickoff(crew: Any, inputs: Optional[Dict[str, Any]] = None, *, name: Optional[str] = None, every: Optional[Duration] = None,
            max: Optional[Duration] = None, ned: Optional[Ned] = None, on_error: str = "report", heartbeat: bool = False, **kw: Any) -> Any:
    """crew.kickoff(inputs=...) with Ned watching it (step/task heartbeats attached)."""
    return NedCrew(name, every, max, ned=ned, on_error=on_error, heartbeat=heartbeat).attach(crew).kickoff(crew, inputs, **kw)


async def akickoff(crew: Any, inputs: Optional[Dict[str, Any]] = None, *, name: Optional[str] = None, every: Optional[Duration] = None,
                   max: Optional[Duration] = None, ned: Optional[Ned] = None, on_error: str = "report", heartbeat: bool = False, **kw: Any) -> Any:
    return await NedCrew(name, every, max, ned=ned, on_error=on_error, heartbeat=heartbeat).attach(crew).akickoff(crew, inputs, **kw)


class NedCrewListener:
    """Watches every crew kickoff in this process through CrewAI's event bus (CrewKickoffStarted/Completed/FailedEvent),
    including crews started by `crewai run` or inside a Flow. Create it once. CrewAI runs bus handlers on its own worker
    threads, so the check-in lands a moment after kickoff returns."""

    def __init__(self, name: Optional[str] = None, every: Optional[Duration] = None, max: Optional[Duration] = None, *,
                 ned: Optional[Ned] = None, on_error: str = "report", callback_url: Optional[str] = None):
        from crewai.events import crewai_event_bus
        from crewai.events.types.crew_events import (CrewKickoffCompletedEvent, CrewKickoffFailedEvent,
                                                     CrewKickoffStartedEvent)
        self.monitor = Monitor(REF, name, every, max, ned, on_error, False, 30.0, callback_url)
        m = self.monitor

        @crewai_event_bus.on(CrewKickoffStartedEvent)
        def _started(source: Any, event: Any) -> None:
            m.started(id(source), _crew_name(source) or getattr(event, "crew_name", None))

        @crewai_event_bus.on(CrewKickoffCompletedEvent)
        def _completed(source: Any, event: Any) -> None:
            m.succeeded(id(source), _crew_name(source) or getattr(event, "crew_name", None))

        @crewai_event_bus.on(CrewKickoffFailedEvent)
        def _failed(source: Any, event: Any) -> None:
            m.failed(id(source), "CrewKickoffFailed: " + str(getattr(event, "error", "") or ""))

        self._handlers = (_started, _completed, _failed)

    @property
    def ned(self) -> Ned:
        return self.monitor.ned
