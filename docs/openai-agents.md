# OpenAI Agents SDK

Know when your agent silently stops.

```python
from nedwatch.integrations.openai_agents import NedRunHooks          # pip install ned-watch; set NED_CALLBACK_URL
result = await Runner.run(agent, "Triage today's tickets", hooks=NedRunHooks(every="1h", max="15m"))
```

| event | what Ned gets |
|---|---|
| the first agent starts | the deadman is armed; an overrun run starts (with `max=`). Handoffs don't start a new run. |
| the run produces its final output | the overrun run finishes; the deadman checks in |
| an LLM reply / tool result (with `heartbeat=True`) | a check-in, at most one per 30 s |
| the run raises | the SDK has no error hook, so nothing is sent: no check-in (the deadman fires), and the open overrun fires at its deadline |

The watch name defaults to the first agent's name.

To report a raised run as failed (Ned fires at once, with the error), use the wrapper:

```python
from nedwatch.integrations.openai_agents import run
result = await run(agent, "Triage today's tickets", every="1h", max="15m")
```

## Per agent

`AgentHooks` watch one agent wherever it runs:

```python
from nedwatch.integrations.openai_agents import NedAgentHooks
billing_agent.hooks = NedAgentHooks("billing-agent", every="1h")
```

## Give the agent Ned's own tools (MCP)

Ned has an MCP server, so an agent can register its own watches and check in by itself.

```python
from nedwatch.integrations.openai_agents import mcp_server, hosted_mcp_tool

async with mcp_server() as ned_mcp:                       # your process connects to https://api.ned.watch/mcp
    agent = Agent(name="ops", instructions="...", mcp_servers=[ned_mcp])

agent = Agent(name="ops", instructions="...", tools=[hosted_mcp_tool()])   # or OpenAI's servers connect for you
```

Both send `X-Ned-Ref: openai-agents` (Ned's MCP passes it on) and `Authorization: Bearer $NED_AGENT_KEY` when it's set.
`mcp_server_stdio()` runs `uvx ned-watch-mcp` locally with `NED_REF=openai-agents`. With no key, the agent's first `quickstart` or
`watch_register` call creates one. Tools: `quickstart`, `deadman_checkin`, `overrun_watch`, `overrun_start`,
`overrun_finish`, `content_watch`, `watch_register`, `watch_get`, `watch_cancel`, `balance`, `pricing`.

The same config by hand:

```python
MCPServerStreamableHttp(params={"url": "https://api.ned.watch/mcp", "headers": {"X-Ned-Ref": "openai-agents", "Authorization": f"Bearer {key}"}})
HostedMCPTool(tool_config={"type": "mcp", "server_label": "ned_watch", "server_url": "https://api.ned.watch/mcp",
                           "require_approval": "never", "headers": {"X-Ned-Ref": "openai-agents", "Authorization": f"Bearer {key}"}})
```

## Options

`name`, `every` (default `"1h"` when `max` isn't set), `max`, `on_error`, `heartbeat`, `ned`. New agents are tagged
`openai-agents`.

## Example

`examples/openai-agents/` runs an agent with a scripted stand-in model (no API key), including a handoff and an agent
that calls Ned's MCP `quickstart` tool, against a local Ned Watch and a local copy of the MCP server.
