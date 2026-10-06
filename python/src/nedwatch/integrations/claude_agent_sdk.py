"""Claude Agent SDK (Python): hooks, a query() wrapper, and MCP server configs for Ned's own tools.

    from claude_agent_sdk import ClaudeAgentOptions, query
    from nedwatch.integrations.claude_agent_sdk import NedHooks

    ned = NedHooks("support-agent", every="1h", max="20m")
    options = ClaudeAgentOptions(hooks=ned.hooks())             # or ned.merge(your_hooks)

  UserPromptSubmit   overrun start (with max=)          keyed by session_id
  PostToolUse        a throttled heartbeat on the deadman (opt in with heartbeat=True: for long-lived agents; a beat counts as alive, so it can mask a run that works and then fails)
  Stop               overrun finish, deadman check-in   (Claude finished its turn)

The query() wrapper below also reads the final ResultMessage: is_error=True (max turns, an API error, an execution
error) counts as a failure, so no check-in is sent. Sent to Ned as X-Ned-Ref: claude-agent-sdk.
"""
from __future__ import annotations

import os
from typing import Any, AsyncIterator, Dict, List, Optional

from claude_agent_sdk import HookMatcher

from ..client import Ned
from .._util import Duration
from ._base import Monitor

REF = "claude-agent-sdk"
NED_MCP_URL = "https://api.ned.watch/mcp"


class NedHooks:
    """name defaults to the script name. every defaults to "1h" when max is not set."""

    def __init__(self, name: Optional[str] = None, every: Optional[Duration] = None, max: Optional[Duration] = None, *,
                 ned: Optional[Ned] = None, on_error: str = "report", heartbeat: bool = False, heartbeat_every: float = 30.0,
                 callback_url: Optional[str] = None):
        self.monitor = Monitor(REF, name, every, max, ned, on_error, heartbeat, heartbeat_every, callback_url)
        self._open: Dict[str, bool] = {}

    @property
    def ned(self) -> Ned:
        return self.monitor.ned

    # HookCallback signature: (input, tool_use_id, context) -> HookJSONOutput. {} changes nothing.
    async def on_user_prompt_submit(self, input: Dict[str, Any], tool_use_id: Optional[str], context: Any) -> Dict[str, Any]:
        sid = str(input.get("session_id") or "")
        if sid not in self._open:
            self._open[sid] = True
            await self.monitor.astarted(sid)
        return {}

    async def on_post_tool_use(self, input: Dict[str, Any], tool_use_id: Optional[str], context: Any) -> Dict[str, Any]:
        await self.monitor.abeat()
        return {}

    async def on_stop(self, input: Dict[str, Any], tool_use_id: Optional[str], context: Any) -> Dict[str, Any]:
        sid = str(input.get("session_id") or "")
        self._open.pop(sid, None)
        await self.monitor.asucceeded(sid)
        return {}

    def hooks(self, start: bool = True, stop: bool = True) -> Dict[str, List[HookMatcher]]:
        """For ClaudeAgentOptions(hooks=...). start/stop=False leave the start and check-in to the query() wrapper."""
        h: Dict[str, List[HookMatcher]] = {"PostToolUse": [HookMatcher(hooks=[self.on_post_tool_use])]}
        if start:
            h["UserPromptSubmit"] = [HookMatcher(hooks=[self.on_user_prompt_submit])]
        if stop:
            h["Stop"] = [HookMatcher(hooks=[self.on_stop])]
        return h

    def merge(self, existing: Optional[Dict[str, List[HookMatcher]]] = None, start: bool = True,
              stop: bool = True) -> Dict[str, List[HookMatcher]]:
        """Your hooks plus Ned's (yours run first)."""
        out: Dict[str, List[HookMatcher]] = {k: list(v) for k, v in (existing or {}).items()}
        for k, v in self.hooks(start, stop).items():
            out.setdefault(k, []).extend(v)
        return out


async def query(*, prompt: Any, options: Any = None, name: Optional[str] = None, every: Optional[Duration] = None,
                max: Optional[Duration] = None, ned: Optional[Ned] = None, on_error: str = "report", heartbeat: bool = False,
                transport: Any = None) -> AsyncIterator[Any]:
    """claude_agent_sdk.query() with Ned watching the whole call. Yields the same messages.
    Success = a ResultMessage with is_error False. Anything else (is_error, an exception, no result) is a failure."""
    import claude_agent_sdk as sdk
    from claude_agent_sdk import ClaudeAgentOptions, ResultMessage

    h = NedHooks(name, every, max, ned=ned, on_error=on_error, heartbeat=heartbeat)
    opts = options or ClaudeAgentOptions()
    opts.hooks = h.merge(opts.hooks, start=False, stop=False)   # heartbeats only; the wrapper starts, the result decides
    key = object()
    await h.monitor.astarted(key)
    ok = False
    why: Any = "no result message"
    try:
        kw = {"transport": transport} if transport is not None else {}
        async for msg in sdk.query(prompt=prompt, options=opts, **kw):
            if isinstance(msg, ResultMessage):
                ok = not msg.is_error
                if not ok:
                    why = f"result {msg.subtype}" + (f" (API {msg.api_error_status})" if getattr(msg, "api_error_status", None) else "")
            yield msg
    except BaseException as e:
        why = e
        raise
    finally:
        if ok:
            await h.monitor.asucceeded(key)
        else:
            await h.monitor.afailed(key, why)


# ---------- MCP: give Claude Ned's own tools ----------

def mcp_servers(agent_key: Optional[str] = None, *, remote: bool = True, local: bool = False,
                url: str = NED_MCP_URL) -> Dict[str, Dict[str, Any]]:
    """For ClaudeAgentOptions(mcp_servers=...). remote: https://api.ned.watch/mcp over HTTP (no install).
    local: the stdio server from PyPI (uvx ned-watch-mcp). The tools show up as mcp__ned-watch__<tool>."""
    key = agent_key or os.environ.get("NED_AGENT_KEY")
    out: Dict[str, Dict[str, Any]] = {}
    if remote:
        cfg: Dict[str, Any] = {"type": "http", "url": url, "headers": {"X-Ned-Ref": REF}}   # passed through by Ned's MCP (v1.9)
        if key:
            cfg["headers"]["Authorization"] = f"Bearer {key}"
        out["ned-watch"] = cfg
    if local:
        st: Dict[str, Any] = {"type": "stdio", "command": "uvx", "args": ["ned-watch-mcp"], "env": {"NED_REF": REF}}
        if key:
            st["env"]["NED_AGENT_KEY"] = key
        out["ned-watch-local" if remote else "ned-watch"] = st
    return out
