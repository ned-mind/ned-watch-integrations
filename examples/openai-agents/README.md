# OpenAI Agents SDK + Ned Watch

An agent with one function tool, run with `NedRunHooks`. `stub_model.py` is a scripted stand-in for the model (no API
key, no network). Docs: [../../docs/openai-agents.md](../../docs/openai-agents.md).

```bash
pip install -r requirements.txt
export NED_CALLBACK_URL=https://your-agent.example/hooks/ned
python agent.py          # uses the stub model; remove model= in build() to use your OpenAI model
```

Tests:

```bash
../../.venv-oai/bin/python -m pytest -q
```

They cover RunHooks (success, handoff counted as one run, failure), the `run()` wrapper, AgentHooks, and Ned's MCP
tools: the stub model calls `quickstart` through `MCPServerStreamableHttp` connected to a local copy of Ned's remote
MCP server (`testserver/mcp_remote`, run on the `.venv-mcp` venv because production pins `mcp<2`). Tracing is disabled.
