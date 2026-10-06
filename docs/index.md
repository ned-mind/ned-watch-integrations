# Integrations

Know when your agent silently stops. Each page below starts with a quick start of three lines or fewer.

The headline is the **deadman**: you promise to check in every so often, and if a check-in doesn't arrive in time, Ned
POSTs a signed `fire` to your callback URL. When you check in again, he sends `clear`. An **overrun** is the other side:
it fires when a run you started is still going past its limit.

| Page | Use it for |
|------|-----------|
| [Python](python.md) | `pip install ned-watch`: decorator, context manager, async, `ned-run`, `nedwatch doctor` |
| [Node / TypeScript](js.md) | `npm i @nedwatch/ned-watch`: same API for Node, zero dependencies |
| [LangGraph / LangChain](langgraph.md) | a callback handler, or a check-in node |
| [CrewAI](crewai.md) | kickoff wrapper, step and task callbacks, event-bus listener |
| [OpenAI Agents SDK](openai-agents.md) | `RunHooks` / `AgentHooks`, and Ned's MCP tools for the agent |
| [Claude Agent SDK](claude-agent-sdk.md) | hooks, a `query()` wrapper, and Ned's MCP tools for Claude |
| [cron and systemd timers](cron.md) | one line in a crontab or a unit file |
| [Docker and Kubernetes](docker-kubernetes.md) | `ned-run` as the entrypoint; a CronJob manifest |
| [n8n](n8n.md) | importable workflows using HTTP Request nodes |
| [Make](make.md), [Zapier](zapier.md), [Pipedream](pipedream.md) | an HTTP step at the end of a scenario / Zap / workflow |
| GitHub Actions | `uses: ned-mind/deadman-action@v1` ([repo](https://github.com/ned-mind/deadman-action)) |
| MCP | remote `https://api.ned.watch/mcp`, or `uvx ned-watch-mcp` ([skill.md](https://ned.watch/skill.md#mcp)) |

## Things every integration does the same way

- **Callback URL.** Ned needs somewhere to POST. Set `NED_CALLBACK_URL` (any public HTTPS endpoint that accepts a POST;
  [webhook.site](https://webhook.site) works for trying it). Every POST is signed; see [verifying callbacks](#verifying-callbacks).
- **No account.** Your first registration creates your agent and returns an agent key. The clients save it in
  `~/.config/ned-watch/state.json` (mode 0600) and never print it. Set `NED_AGENT_KEY` to use the same agent elsewhere.
- **Same name, same watch.** Registering a watch with the same name and settings returns the same watch, so a job that
  runs every hour reuses one watch. Change the settings and the clients retire the old watch for you.
- **The clock starts at registration.** The clients register deadmen with `condition.arm: true`, so a job that never
  runs, or fails on its very first run, is still noticed. (Against a server that refuses `arm`, they check in once instead.)
- **Ned never breaks your job.** If Ned can't be reached, the clients log a warning and carry on. Pass `strict=True`
  (Python) or `strict: true` (Node) if you'd rather they raise.
- **Failures.** A failed run never checks in, so the deadman fires when the interval passes. An overrun run that fails is
  finished with `status: "failed"` and a short error (exception class + first line, credentials redacted), so Ned fires
  at once; the next run that finishes cleanly sends `clear`.
- **Attribution.** New agents are tagged with the integration that created them (`X-Ned-Ref: langgraph`, `cron`, ...),
  so Ned can see which integrations people use. It's a short tag, nothing else.
- **Pricing.** Your first 5 watches are free at intervals of 5 minutes or more. After that, a deadman or overrun costs
  1 cent a day. See [pricing](https://api.ned.watch/v1/pricing).

## Verifying callbacks

Every POST from Ned carries `X-Ned-Event`, `X-Ned-Timestamp` and `X-Ned-Signature =
hex(HMAC-SHA256(signing_secret, timestamp + "." + raw_body))`.

```python
from nedwatch import verify_signature
ok = verify_signature(signing_secret, request.headers, raw_body)    # also checks the timestamp is within 5 minutes
```

```js
import { verifySignature } from "@nedwatch/ned-watch";
const ok = verifySignature(signingSecret, req.headers, rawBody);
```

## Check your setup

```bash
uvx ned-watch doctor        # or: npx @nedwatch/ned-watch doctor
```

It checks that Ned answers, that your agent key works, and (with a callback URL set) that a real signed test callback
reaches your endpoint. It also lists the watches in your state file and whether any has fired.
