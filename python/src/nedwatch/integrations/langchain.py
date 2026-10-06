"""LangChain / LangGraph: a callback handler, and a node for graphs.

    from nedwatch.integrations.langchain import NedCallbackHandler
    graph.invoke(inputs, config={"callbacks": [NedCallbackHandler("research-agent", every="1h")]})

The top-level run (the graph or chain you invoked) drives the watches:
  start      overrun start (when max= is set)
  end        overrun finish, deadman check-in
  error      no check-in; the overrun run is finished as failed with the error (Ned fires at once)
  progress   each LLM reply and tool result inside the run is a throttled heartbeat on the deadman (opt in with heartbeat=True: for long-lived agents; a beat counts as alive, so it can mask a run that works and then fails)
Nested chains, tools and LLM calls never start or finish anything. Sent to Ned as X-Ned-Ref: langgraph (or langchain).
"""
from __future__ import annotations

import sys
from typing import Any, Callable, Dict, Optional
from uuid import UUID

from langchain_core.callbacks import AsyncCallbackHandler, BaseCallbackHandler

from ..client import Ned
from .._util import Duration
from ._base import Monitor


def _ref() -> str:
    return "langgraph" if "langgraph" in sys.modules else "langchain"


def _hint(serialized: Optional[Dict[str, Any]], kwargs: Dict[str, Any]) -> Optional[str]:
    n = kwargs.get("name") or (serialized or {}).get("name")
    return n if n and n not in ("LangGraph", "RunnableSequence") else None


class NedCallbackHandler(BaseCallbackHandler):
    """Sync handler (also works under ainvoke: LangChain runs sync handlers in a thread there).

    name     watch name; default: the graph/chain's run name, else the script name
    every    deadman: fire if no successful run (or heartbeat) within this. Default "1h" when max is not set.
    max      overrun: fire if one run is still going after this
    """

    raise_error = False

    def __init__(self, name: Optional[str] = None, every: Optional[Duration] = None, max: Optional[Duration] = None, *,
                 ned: Optional[Ned] = None, on_error: str = "report", heartbeat: bool = False, heartbeat_every: float = 30.0,
                 callback_url: Optional[str] = None):
        self.monitor = Monitor(_ref(), name, every, max, ned, on_error, heartbeat, heartbeat_every, callback_url)

    @property
    def ned(self) -> Ned:
        return self.monitor.ned

    def on_chain_start(self, serialized: Dict[str, Any], inputs: Any, *, run_id: UUID, parent_run_id: Optional[UUID] = None, **kw: Any) -> None:
        if parent_run_id is None:
            self.monitor.started(run_id, _hint(serialized, kw))

    def on_chain_end(self, outputs: Any, *, run_id: UUID, parent_run_id: Optional[UUID] = None, **kw: Any) -> None:
        if parent_run_id is None:
            self.monitor.succeeded(run_id)

    def on_chain_error(self, error: BaseException, *, run_id: UUID, parent_run_id: Optional[UUID] = None, **kw: Any) -> None:
        if parent_run_id is None:
            self.monitor.failed(run_id, error)

    def on_llm_end(self, response: Any, **kw: Any) -> None:
        self.monitor.beat()

    def on_tool_end(self, output: Any, **kw: Any) -> None:
        self.monitor.beat()


class AsyncNedCallbackHandler(AsyncCallbackHandler):
    """The same, natively async (no thread hop) for ainvoke/astream."""

    raise_error = False

    def __init__(self, name: Optional[str] = None, every: Optional[Duration] = None, max: Optional[Duration] = None, *,
                 ned: Optional[Ned] = None, on_error: str = "report", heartbeat: bool = False, heartbeat_every: float = 30.0,
                 callback_url: Optional[str] = None):
        self.monitor = Monitor(_ref(), name, every, max, ned, on_error, heartbeat, heartbeat_every, callback_url)

    @property
    def ned(self) -> Ned:
        return self.monitor.ned

    async def on_chain_start(self, serialized: Dict[str, Any], inputs: Any, *, run_id: UUID, parent_run_id: Optional[UUID] = None, **kw: Any) -> None:
        if parent_run_id is None:
            await self.monitor.astarted(run_id, _hint(serialized, kw))

    async def on_chain_end(self, outputs: Any, *, run_id: UUID, parent_run_id: Optional[UUID] = None, **kw: Any) -> None:
        if parent_run_id is None:
            await self.monitor.asucceeded(run_id)

    async def on_chain_error(self, error: BaseException, *, run_id: UUID, parent_run_id: Optional[UUID] = None, **kw: Any) -> None:
        if parent_run_id is None:
            await self.monitor.afailed(run_id, error)

    async def on_llm_end(self, response: Any, **kw: Any) -> None:
        await self.monitor.abeat()

    async def on_tool_end(self, output: Any, **kw: Any) -> None:
        await self.monitor.abeat()


def checkin_node(name: Optional[str] = None, every: Duration = "1h", *, ned: Optional[Ned] = None,
                 callback_url: Optional[str] = None) -> Callable[[Any], Dict[str, Any]]:
    """A LangGraph node that checks in to a deadman and changes no state. Put it on the path your graph takes when a
    run succeeds:  builder.add_node("ned", checkin_node("research-agent", every="1h")); builder.add_edge("ned", END)"""
    n = (ned or Ned(ref=None))._default_ref(_ref())
    dm = n.deadman(name, every, callback_url=callback_url)

    def ned_checkin(state: Any) -> Dict[str, Any]:
        n._soft(f"check-in for {dm.name}", dm.checkin)
        return {}

    return ned_checkin
