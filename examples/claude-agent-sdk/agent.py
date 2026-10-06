"""A Claude Agent SDK agent watched by Ned, with Ned's MCP tools available to Claude.

    pip install ned-watch claude-agent-sdk
    export NED_CALLBACK_URL=https://your-agent.example/hooks/ned
    python agent.py              # needs Claude Code and your Anthropic credentials, like any Agent SDK program
"""
import asyncio

from claude_agent_sdk import ClaudeAgentOptions, ResultMessage

from nedwatch.integrations.claude_agent_sdk import NedHooks, mcp_servers, query


def options(ned_hooks: NedHooks) -> ClaudeAgentOptions:
    return ClaudeAgentOptions(
        hooks=ned_hooks.hooks(),                       # start on prompt, heartbeat on tools, check in on Stop
        mcp_servers=mcp_servers(),                     # Ned's tools: mcp__ned-watch__quickstart, deadman_checkin, ...
        allowed_tools=["mcp__ned-watch__watch_get"],
    )


async def main() -> None:
    # Option 1: hooks on your own options
    opts = options(NedHooks("support-agent", every="1h", max="20m"))
    # Option 2: the wrapper, which also treats an error result as a failure
    async for msg in query(prompt="Summarise today's tickets", name="support-agent", every="1h", max="20m"):
        if isinstance(msg, ResultMessage):
            print(msg.result)


if __name__ == "__main__":
    asyncio.run(main())
