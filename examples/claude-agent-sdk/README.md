# Claude Agent SDK + Ned Watch

`NedHooks` on `ClaudeAgentOptions`, the `query()` wrapper, and MCP server configs for Ned's tools.
Docs: [../../docs/claude-agent-sdk.md](../../docs/claude-agent-sdk.md).

`agent.py` is the real-world shape (it needs Claude Code and your Anthropic credentials, like any Agent SDK program).

Tests run the SDK's own `query()` and hook machinery, but replace the Claude Code CLI with `fake_cli.py`, a Transport
that speaks the SDK's control protocol (initialize, hook_callback) and plays UserPromptSubmit, PostToolUse, Stop and a
result message. No model, no CLI, no network:

```bash
../../.venv-claude/bin/python -m pytest -q
```

The MCP test connects an MCP client to a local copy of Ned's remote MCP server with the URL and headers
`mcp_servers()` produces, lists the tools and calls `quickstart`.
