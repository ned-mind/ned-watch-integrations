# LangGraph + Ned Watch

A one-node LangGraph agent (stub chat model, no API key) watched by `NedCallbackHandler`, plus a variant that uses
`checkin_node`. Docs: [../../docs/langgraph.md](../../docs/langgraph.md).

```bash
pip install -r requirements.txt
export NED_CALLBACK_URL=https://your-agent.example/hooks/ned
python agent.py
```

Tests (against a local Ned Watch started by the test harness; no network):

```bash
../../.venv-lc/bin/python -m pytest -q
```

They check: a successful run arms, finishes the overrun and checks in; the agent is tagged `langgraph`; failed runs
never check in and the deadman fires; async (`ainvoke`) with both handlers; the check-in node; heartbeats; and that a
bare `Ned()` detects LangGraph on its own.
