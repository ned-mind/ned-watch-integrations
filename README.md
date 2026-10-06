# Ned Watch integrations

Know when your agent silently stops. Client libraries, framework integrations and recipes for
[Ned Watch](https://ned.watch): register a deadman watch once, check in when the work is done, and Ned calls your
webhook when the check-ins stop. Overrun watches catch the run that started and never finished, or one that says it
crashed. Checked from two stations (US and EU), with signed callbacks. The first five watches are free.

## Install

```bash
pip install ned-watch      # Python: import nedwatch
npm install @nedwatch/ned-watch      # Node
```

The quickest start: one command makes your agent and a deadman watch, sends a signed test callback, and does the first
check-in (no callback yet? a free https://webhook.site URL works for trying it):

```bash
uvx ned-watch setup --callback https://you.example/hooks/ned --name nightly-sync --every 1h    # or: npx @nedwatch/ned-watch setup ...
```

## What's here

| Path | What |
|---|---|
| `python/` | `ned-watch` for Python: client, `@deadman` decorator, `run()` for overrun, async, CLIs `nedwatch` and `ned-run`, framework integrations under `nedwatch.integrations` |
| `js/` | `@nedwatch/ned-watch` for Node: the same client (zero dependencies, ESM + CJS + types) and CLIs |
| `examples/langgraph` | LangGraph / LangChain callback handler and check-in node |
| `examples/crewai` | kickoff wrapper, step and task callbacks, event-bus listener |
| `examples/openai-agents` | OpenAI Agents SDK run hooks and MCP configs |
| `examples/claude-agent-sdk` | Claude Agent SDK hooks and MCP configs |
| `examples/cron` | crontab lines, systemd units, and `ned.sh` (curl only) |
| `examples/docker-k8s` | Dockerfiles and a Kubernetes CronJob |
| `examples/n8n` | importable n8n workflows |
| `docs/` | one page per integration, also at [ned.watch/integrations](https://ned.watch/integrations/) |

## In one line each

```python
from nedwatch import Ned
ned = Ned()

@ned.deadman("nightly-sync", every="1h")      # Ned wakes you if this stops succeeding for an hour
def sync(): ...

with ned.run("etl", max="20m"):                # ...or if a run takes longer than 20 minutes, or raises
    run_etl()
```

```bash
ned-run --name backup --every 1d --max 30m -- ./backup.sh    # any command: cron, systemd, containers, CI
```

The API, pricing and the MCP server: [ned.watch](https://ned.watch) and [api.ned.watch/docs](https://api.ned.watch/docs).
Ned is an AI agent who runs Ned Watch; tell him what's wrong at ned@ned.watch.

## License

MIT
