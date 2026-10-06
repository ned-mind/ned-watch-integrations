# Make (formerly Integromat)

Know when your Make scenario silently stops.

```
Add an HTTP > "Make a request" module as the last module of your scenario:
  POST https://api.ned.watch/v1/checkin/<watch_id>   header Authorization: Bearer <signing_secret>   header X-Ned-Ref: make
Right-click it > Add error handler > Ignore, so a problem reaching Ned never stops your scenario.
```

Because it's the last module, it only runs when every module before it succeeded. If the scenario stops running, is
turned off, or fails, the check-in doesn't arrive and Ned POSTs a signed `fire` to your callback once the interval passes.

## Make the watch (once)

From a terminal:

```bash
curl -s -X POST https://api.ned.watch/v1/watches -H 'Content-Type: application/json' -H 'X-Ned-Ref: make' \
  -d '{"type":"deadman","interval_s":3900,"callback_url":"https://you.example/hooks/ned","condition":{"label":"my-scenario","arm":true}}'
```

Or from Make itself: a one-off scenario with one "Make a request" module, method POST, that URL, header
`X-Ned-Ref: make`, body type Raw / JSON with the same body. Run it once and copy `watch_id`, `signing_secret` and
`agent_key` from the output bundle.

Set `interval_s` a little longer than the scenario's schedule (3900 s for an hourly scenario). `"arm": true` starts the clock
at registration, so a scenario that never runs is noticed too.

## The check-in module

| field | value |
|---|---|
| URL | `https://api.ned.watch/v1/checkin/<watch_id>` |
| Method | POST |
| Headers | `Authorization` = `Bearer <signing_secret>`, `X-Ned-Ref` = `make` |
| Body | none |
| Error handler | Ignore |

Keep the secret out of the module if you can: store it in a Make data store or a custom variable (on plans that have
them) and map it into the header.

## Long scenarios: an overrun too

Register an overrun watch (`{"type":"overrun","max_runtime_s":1800,...}`), then add a "Make a request" module **first**
(`POST .../v1/watches/<overrun id>/start`, header `Authorization: Bearer <overrun signing_secret>`) and one just before
the check-in (`POST .../finish`, same header). Ned fires if a run is still going 30 minutes after it started. To report a failure at once, add an error-handler route
that calls finish with body `{"status": "failed", "error": "scenario failed"}`. To make
retries safe, send the same `{"run_id": "..."}` body to both, mapping the scenario's execution ID from Make's system
variables (the exact variable name wasn't checked).

Not tested inside Make (no account was used); the HTTP calls are the same ones tested elsewhere in this pack.
