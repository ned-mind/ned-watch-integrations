# Claude Agent SDK (Python)

Know when your Claude agent silently stops.

```python
from nedwatch.integrations.claude_agent_sdk import NedHooks          # pip install ned-watch; set NED_CALLBACK_URL
options = ClaudeAgentOptions(hooks=NedHooks("support-agent", every="1h", max="20m").hooks())
```

| hook | what Ned gets |
|---|---|
| `UserPromptSubmit` | the deadman is armed; an overrun run starts (with `max=`), keyed by session |
| `PostToolUse` (with `heartbeat=True`) | a check-in, at most one per 30 s |
| `Stop` | the overrun run finishes; the deadman checks in |

Already have hooks? `NedHooks(...).merge(your_hooks)` returns both (yours run first).

## Count error results as failures

`Stop` fires when Claude finishes a turn, including turns that end in an error. To check in only on success, use the
wrapper around `query()`. It reads the final `ResultMessage`: `is_error=True` (max turns, an API error, an execution
error), an exception, or no result at all counts as a failure: no check-in, and the overrun run is finished as failed
with a short reason (for example `result error_max_turns`), so Ned fires at once.

```python
from nedwatch.integrations.claude_agent_sdk import query

async for message in query(prompt="Summarise today's tickets", options=options, name="support-agent", every="1h", max="20m"):
    ...
```

It yields the same messages as `claude_agent_sdk.query`.

## Give Claude Ned's own tools (MCP)

```python
from nedwatch.integrations.claude_agent_sdk import mcp_servers
options = ClaudeAgentOptions(mcp_servers=mcp_servers(), allowed_tools=["mcp__ned-watch__quickstart", "mcp__ned-watch__deadman_checkin"])
```

`mcp_servers()` gives the remote server, `{"ned-watch": {"type": "http", "url": "https://api.ned.watch/mcp",
"headers": {"X-Ned-Ref": "claude-agent-sdk", "Authorization": "Bearer <NED_AGENT_KEY>"}}}`. `mcp_servers(local=True,
remote=False)` gives the stdio package instead: `{"type": "stdio", "command": "uvx", "args": ["ned-watch-mcp"], "env":
{"NED_REF": "claude-agent-sdk", "NED_AGENT_KEY": ...}}`. Either way Ned sees which integration the agent came from.
The tools appear as `mcp__ned-watch__<tool>`.

## Options

`name` (default: the script name), `every` (default `"1h"` when `max` isn't set), `max`, `on_error`, `heartbeat`, `ned`.
New agents are tagged `claude-agent-sdk`.

## Example

`examples/claude-agent-sdk/` runs the SDK's real `query()` and hook machinery against a scripted stand-in for the
Claude Code CLI (no model, no network), plus the MCP config against a local copy of Ned's MCP server.
