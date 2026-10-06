# Pipedream

Know when your Pipedream workflow silently stops.

```js
// last step, Node.js. Env vars NED_WATCH_ID and NED_SIGNING_SECRET set in Pipedream's Environment Variables.
export default defineComponent({ async run() { await fetch(`https://api.ned.watch/v1/checkin/${process.env.NED_WATCH_ID}`,
  { method: "POST", headers: { Authorization: `Bearer ${process.env.NED_SIGNING_SECRET}`, "X-Ned-Ref": "pipedream" } }); } });
```

A Pipedream workflow stops at the first step that throws, so a check-in in the last step only runs when the steps
before it succeeded. If the workflow stops running or fails, the check-in doesn't arrive and Ned POSTs a signed `fire`
to your callback once the interval passes.

## Make the watch (once)

```bash
curl -s -X POST https://api.ned.watch/v1/watches -H 'Content-Type: application/json' -H 'X-Ned-Ref: pipedream' \
  -d '{"type":"deadman","interval_s":3900,"callback_url":"https://you.example/hooks/ned","condition":{"label":"my-workflow","arm":true}}'
```

Save `watch_id` and `signing_secret` as Pipedream environment variables (`NED_WATCH_ID`, `NED_SIGNING_SECRET`) and keep
`agent_key`. `"arm": true` starts the clock at registration, so a workflow that never runs is noticed too.

## With the ned-watch package

Pipedream installs npm packages you import, so the client works in a Node.js step:

```js
import { Ned } from "ned-watch";

export default defineComponent({
  async run({ steps }) {
    const ned = new Ned({ state: false, ref: "pipedream" });        // reads NED_AGENT_KEY, NED_CALLBACK_URL
    await ned.deadman("my-workflow", { every: "65m" }).checkin();   // same name + settings = the same watch every time
  },
});
```

With `NED_AGENT_KEY` and `NED_CALLBACK_URL` set, this registers the watch on its first run and reuses it after that.

## Overrun

Wrap the work in one step: `await ned.run("my-workflow", { max: "10m", every: "65m" }, async () => { ... })` (a throw
is reported as a failed run, so Ned fires at once), or put a
`start` call in the first step and `finish` in the last, both with `run_id: steps.trigger.context.id`.

Not tested inside Pipedream (no account was used); the client and the HTTP calls are tested in this pack.
