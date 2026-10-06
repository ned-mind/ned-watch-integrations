# Python

Know when your Python agent or job silently stops.

```python
from nedwatch import Ned                       # pip install ned-watch, and set NED_CALLBACK_URL
@Ned().deadman("nightly-sync", every="1h")     # Ned fires if this hasn't finished cleanly for an hour
def sync(): ...
```

`ned-watch` has no dependencies (it uses `urllib`). If `httpx` is installed, the async calls use it.
Python 3.9 and up.

## Setup

```bash
pip install ned-watch
export NED_CALLBACK_URL=https://your-agent.example/hooks/ned
```

That's all. The first time a watch is used, the client creates your agent, saves the agent key to
`~/.config/ned-watch/state.json` (mode 0600, never printed), registers the watch with `condition.arm` so the clock starts right away.

| Variable | Meaning |
|---|---|
| `NED_CALLBACK_URL` | where Ned POSTs signed `fire` / `clear` messages (required to register a watch) |
| `NED_AGENT_KEY` | your key, to use the same agent on another machine (else read from the state file) |
| `NED_API` / `NED_REGION` | API base, or `eu` for `https://api-eu.ned.watch` |
| `NED_STATE` | state file path |
| `NED_REF` | the tag sent as `X-Ned-Ref` when your agent is created (default: the framework detected, else `python`) |
| `NED_WATCH_NAME` | default watch name (else the script's file name) |

## Deadman: "fire if this stops succeeding"

```python
from nedwatch import Ned

ned = Ned()

@ned.deadman("nightly-sync", every="1h")        # every: "90s", "20m", "1h", "1h30m", "1d", or seconds
def sync():
    ...                                         # a return checks in; an exception doesn't
```

Or check in yourself, for example at the end of each loop of a long-running agent:

```python
heartbeat = ned.deadman("research-agent", every="10m")
while True:
    do_one_task()
    heartbeat.checkin()
```

`grace=` sets a different deadline from `every` (for example `every="1h", grace="90m"`).

## Overrun: "fire if this is still running"

```python
with ned.run("etl", max="20m"):
    load_everything()
```

`run()` starts an overrun run on entry and finishes it on a clean exit. If the block is still running 20 minutes after
it started, Ned fires once; if it finishes late, he sends `clear` with `late: true` and the runtime.

Add `every=` to get both in one go: the overrun catches hangs, the deadman catches failures and missed schedules.

```python
with ned.run("etl", max="20m", every="1d"):
    load_everything()
```

What happens when the block raises:

| `on_error=` | effect |
|---|---|
| `"report"` (default) | finish the run with `status: "failed"` and a short error (exception class + first line, credentials redacted, at most 200 chars): Ned fires at once and clears on the next clean run. No deadman check-in. |
| `"leave_open"` | never finish a failed run (Ned fires when `max` passes) |
| `"finish"` | finish it as if it succeeded (the failure is not reported) |

`ned.run(...)` also works as a decorator (a new run per call) and with `async with`.

## Async

The decorator and `run()` work on `async def` functions and with `async with`. Direct calls have `a` versions:
`await ned.acheckin(...)`, `await ned.astart(...)`, `await ned.afinish(...)`, `await ned.aget(...)`.

```python
@ned.deadman("poller", every="5m")
async def poll(): ...

async with ned.run("crawl", max="1h"):
    await crawl()
```

## Direct calls

```python
ned.checkin("nightly-sync")                    # by name (registered by this client), or by id "w_..."
ned.checkin("w_0123456789ab", signing_secret=...)
ned.start(overrun, run_id="2026-10-05")        # run_id makes retries safe
ned.finish(overrun, run_id="2026-10-05")       # failed=True, error="..." reports a crash
ned.get("w_...")  ned.watches()  ned.cancel("w_...")  ned.balance()
ned.register("http", target="https://example.com/health", interval_s=300)   # any watch type, as is
```

Errors are `NedError` (with `.status` and `.detail`); a missing callback URL or secret is `NedConfigError`.
The decorator and `run()` never raise for a Ned problem unless you made the client with `Ned(strict=True)`.

## Command line

```bash
nedwatch setup --name nightly-sync --every 1h [--max 30m]   # make the watch(es) and do the first check-in
nedwatch checkin nightly-sync                               # put at the end of a job
ned-run --name backup --max 30m --every 1d -- ./backup.sh  # wrap any command (see cron)
nedwatch doctor [--create]                                  # key, connectivity, a real test callback
nedwatch status
```

`uvx ned-watch <command>` runs the same CLI without installing anything. Secrets stay in the state file; `setup
--show-secrets` prints them as env lines if you need them elsewhere.

## Frameworks

- [LangGraph / LangChain](https://ned.watch/integrations/langgraph): `NedCallbackHandler`
- [CrewAI](https://ned.watch/integrations/crewai): `kickoff(crew, ...)`
- [OpenAI Agents SDK](https://ned.watch/integrations/openai-agents): `NedRunHooks`
- [Claude Agent SDK](https://ned.watch/integrations/claude-agent-sdk): `NedHooks`

## Verifying callbacks

```python
from nedwatch import verify_signature
if not verify_signature(signing_secret, request.headers, await request.body()):
    return Response(status_code=401)
```

## Links

- Docs: https://ned.watch/integrations/python
- API and callback contract: https://ned.watch/skill.md
- Node version: `npm i @nedwatch/ned-watch`
- MCP server: `uvx ned-watch-mcp`, or remote `https://api.ned.watch/mcp`
- Contact: ned@ned.watch

MIT licensed.
