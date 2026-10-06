# Node / TypeScript

Know when your Node agent or job silently stops.

```js
import { Ned } from "@nedwatch/ned-watch";              // npm i @nedwatch/ned-watch, and set NED_CALLBACK_URL
const sync = new Ned().deadman("nightly-sync", { every: "1h" }).wrap(async () => { /* your job */ });
await sync();                                 // Ned fires if this hasn't finished cleanly for an hour
```

Zero dependencies (global `fetch`), Node 18.17 and up, ESM and CommonJS, types included.

## Setup

```bash
npm i @nedwatch/ned-watch
export NED_CALLBACK_URL=https://your-agent.example/hooks/ned
```

The first time a watch is used, the client creates your agent, saves the key to `~/.config/ned-watch/state.json`
(mode 0600, the same file the Python client uses), registers the watch with `condition.arm` so the clock starts right away.
Environment variables are the same as for [Python](https://ned.watch/integrations/python#setup); `NED_REF` defaults to the framework found in your
`package.json` (`@langchain/langgraph`, `@openai/agents`, `@anthropic-ai/claude-agent-sdk`, `@mastra/core`, `ai`, ...),
else `js`.

## Deadman

```js
import { Ned } from "@nedwatch/ned-watch";
const ned = new Ned();

const heartbeat = ned.deadman("research-agent", { every: "10m" });
for (;;) {
  await doOneTask();
  await heartbeat.checkin();
}
```

`deadman(name, { every, grace, callbackUrl })` registers on first use and reuses the same watch afterwards.
`.wrap(fn)` returns a function that checks in each time `fn` resolves without throwing.

## Overrun

```js
await ned.run("etl", { max: "20m" }, async () => {
  await loadEverything();
});
```

Starts an overrun run, runs your function, finishes the run. Add `every: "1d"` to also check in to a deadman after each
clean run. On a throw: `onError: "report"` (default) finishes the run with `status: "failed"` and a short, redacted
error, so Ned fires at once; `"leave_open"` (fires at `max`); `"finish"` (closed as ok).

## Direct calls

```js
await ned.checkin("nightly-sync");                  // by name, or "w_..." with a signing secret
await ned.start(overrun, "run-2026-10-05");         // run ids make retries safe
await ned.finish(overrun, "run-2026-10-05");       // 4th arg { failed: true, error } reports a crash
await ned.get("w_..."); await ned.watches(); await ned.cancel("w_..."); await ned.balance();
await ned.register("content", { target: "https://example.com/health", interval_s: 300, expect: { status: 200 } });
```

Errors are `NedError` (`.status`, `.detail`) and `NedConfigError`. `wrap()` and `run()` never throw for a Ned problem
unless you pass `strict: true`. Warnings go to `console.warn` (or `logger`).

CommonJS: `const { Ned } = require("@nedwatch/ned-watch");`

## Command line

```bash
npx @nedwatch/ned-watch setup --name nightly-sync --every 1h
npx @nedwatch/ned-watch checkin nightly-sync
npx -p @nedwatch/ned-watch ned-run --name backup --max 30m --every 1d -- ./backup.sh
npx @nedwatch/ned-watch doctor
```

Installed globally (`npm i -g @nedwatch/ned-watch`) the commands are `nedwatch` and `ned-run`. Same flags and state file as the
Python CLI, so either can check in to a watch the other set up.

## Verifying callbacks

```js
import { verifySignature } from "@nedwatch/ned-watch";
app.post("/hooks/ned", express.raw({ type: "application/json" }), (req, res) => {
  if (!verifySignature(process.env.NED_SIGNING_SECRET, req.headers, req.body)) return res.sendStatus(401);
  const event = JSON.parse(req.body);   // event.event is fire | clear | test | ...
  res.sendStatus(200);
});
```

## Links

- Docs: https://ned.watch/integrations/js
- API and callback contract: https://ned.watch/skill.md
- Python version: `pip install ned-watch`
- Contact: ned@ned.watch

MIT licensed.
