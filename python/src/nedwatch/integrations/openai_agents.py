"""OpenAI Agents SDK: RunHooks / AgentHooks, a Runner.run wrapper, and MCP configs for Ned's own tools.

    from nedwatch.integrations.openai_agents import NedRunHooks
    result = await Runner.run(agent, "...", hooks=NedRunHooks("triage-agent", every="1h", max="15m"))

  first agent starts   overrun start (with max=)      (one run = one RunContextWrapper; handoffs don't restart it)
  final output         overrun finish, deadman check-in
  each LLM reply/tool  a throttled heartbeat on the deadman (opt in with heartbeat=True: for long-lived agents; a beat counts as alive, so it can mask a run that works and then fails)
  an exception         the SDK has no error hook: no check-in (the deadman fires), and the open overrun fires at its
                       deadline. Use run() below to report the failure at once (finish with status failed + error).
Sent to Ned as X-Ned-Ref: openai-agents.
"""
from __future__ import annotations

import os
from typing import Any, Dict, Optional

from agents import AgentHooks, RunHooks

from ..client import Ned
from .._util import Duration
from ._base import Monitor

REF = "openai-agents"
NED_MCP_URL = "https://api.ned.watch/mcp"


def _key(context: Any) -> int:
    # A new AgentHookContext is made per hook call, but they all share the run's Usage object.
    return id(getattr(context, "usage", None) or context)


class NedRunHooks(RunHooks):
    """name defaults to the first agent's name. every defaults to "1h" when max is not set."""

    def __init__(self, name: Optional[str] = None, every: Optional[Duration] = None, max: Optional[Duration] = None, *,
                 ned: Optional[Ned] = None, on_error: str = "report", heartbeat: bool = False, heartbeat_every: float = 30.0,
                 callback_url: Optional[str] = None):
        self.monitor = Monitor(REF, name, every, max, ned, on_error, heartbeat, heartbeat_every, callback_url)
        self._live: Dict[int, bool] = {}

    @property
    def ned(self) -> Ned:
        return self.monitor.ned

    async def on_agent_start(self, context: Any, agent: Any) -> None:
        k = _key(context)
        if k not in self._live:                      # handoffs call this again for the next agent: same run
            self._live[k] = True
            await self.monitor.astarted(k, getattr(agent, "name", None))

    async def on_agent_end(self, context: Any, agent: Any, output: Any) -> None:
        k = _key(context)
        self._live.pop(k, None)
        await self.monitor.asucceeded(k, getattr(agent, "name", None))

    async def on_llm_end(self, context: Any, agent: Any, response: Any) -> None:
        await self.monitor.abeat(getattr(agent, "name", None))

    async def on_tool_end(self, context: Any, agent: Any, tool: Any, result: Any) -> None:
        await self.monitor.abeat(getattr(agent, "name", None))

    async def fail_open_runs(self, error: Any = None) -> None:
        for k in list(self._live):
            self._live.pop(k, None)
            await self.monitor.afailed(k, error)


class NedAgentHooks(AgentHooks):
    """Per agent (agent.hooks = NedAgentHooks(...)): a watch for one specific agent, wherever it runs."""

    def __init__(self, name: Optional[str] = None, every: Optional[Duration] = None, max: Optional[Duration] = None, *,
                 ned: Optional[Ned] = None, on_error: str = "report", heartbeat: bool = False, heartbeat_every: float = 30.0,
                 callback_url: Optional[str] = None):
        self.monitor = Monitor(REF, name, every, max, ned, on_error, heartbeat, heartbeat_every, callback_url)

    @property
    def ned(self) -> Ned:
        return self.monitor.ned

    async def on_start(self, context: Any, agent: Any) -> None:
        await self.monitor.astarted(_key(context), getattr(agent, "name", None))

    async def on_end(self, context: Any, agent: Any, output: Any) -> None:
        await self.monitor.asucceeded(_key(context), getattr(agent, "name", None))

    async def on_llm_end(self, context: Any, agent: Any, response: Any) -> None:
        await self.monitor.abeat(getattr(agent, "name", None))

    async def on_tool_end(self, context: Any, agent: Any, tool: Any, result: Any) -> None:
        await self.monitor.abeat(getattr(agent, "name", None))


async def run(agent: Any, input: Any, *, name: Optional[str] = None, every: Optional[Duration] = None,
              max: Optional[Duration] = None, ned: Optional[Ned] = None, on_error: str = "report", hooks: Optional[NedRunHooks] = None,
              **kw: Any) -> Any:
    """Runner.run(agent, input, hooks=NedRunHooks(...)) that also reports a raised run as failed (Ned fires at once)."""
    from agents import Runner
    h = hooks or NedRunHooks(name, every, max, ned=ned, on_error=on_error)
    try:
        return await Runner.run(agent, input, hooks=h, **kw)
    except BaseException as e:
        await h.fail_open_runs(e)
        raise


# ---------- MCP: give the agent Ned's own tools (register watches, check in) ----------

def mcp_server(agent_key: Optional[str] = None, url: str = NED_MCP_URL, **kw: Any) -> Any:
    """Ned's remote MCP as an agents.mcp server (your process connects): Agent(mcp_servers=[mcp_server()]).
    Use it inside `async with`. With no key, the agent's first watch_register/quickstart call issues one."""
    from agents.mcp import MCPServerStreamableHttp
    key = agent_key or os.environ.get("NED_AGENT_KEY")
    params: Dict[str, Any] = {"url": url, "headers": {"X-Ned-Ref": REF}}      # Ned's MCP passes the ref through (v1.9)
    if key:
        params["headers"]["Authorization"] = f"Bearer {key}"
    return MCPServerStreamableHttp(params=params, name="ned-watch", cache_tools_list=True, **kw)


def mcp_server_stdio(agent_key: Optional[str] = None, command: str = "uvx", args: Optional[list] = None, **kw: Any) -> Any:
    """Ned's MCP server as a local stdio process (uvx ned-watch-mcp): Agent(mcp_servers=[mcp_server_stdio()])."""
    from agents.mcp import MCPServerStdio
    key = agent_key or os.environ.get("NED_AGENT_KEY")
    env = {"NED_REF": REF, **({"NED_AGENT_KEY": key} if key else {})}
    for k in ("PATH", "HOME", "NED_WATCH_API"):                      # stdio servers get a bare environment otherwise
        if os.environ.get(k):
            env.setdefault(k, os.environ[k])
    return MCPServerStdio(params={"command": command, "args": args if args is not None else ["ned-watch-mcp"], "env": env},
                          name="ned-watch", cache_tools_list=True, **kw)


def hosted_mcp_tool(agent_key: Optional[str] = None, url: str = NED_MCP_URL) -> Any:
    """Ned's remote MCP as a HostedMCPTool (OpenAI's servers connect to it; nothing runs in your process)."""
    from agents import HostedMCPTool
    key = agent_key or os.environ.get("NED_AGENT_KEY")
    cfg: Dict[str, Any] = {"type": "mcp", "server_label": "ned_watch", "server_url": url, "require_approval": "never",
                           "headers": {"X-Ned-Ref": REF}}
    if key:
        cfg["headers"]["Authorization"] = f"Bearer {key}"
    return HostedMCPTool(tool_config=cfg)  # type: ignore[arg-type]
