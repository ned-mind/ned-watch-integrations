# Zapier

Know when your Zap silently stops.

```
Add a final action step: Webhooks by Zapier > Custom Request.
  Method POST, URL https://api.ned.watch/v1/checkin/<watch_id>
  Headers: Authorization | Bearer <signing_secret>   and   X-Ned-Ref | zapier
```

Zapier stops a Zap at the first failing step, so a check-in in the last step only happens when everything before it
worked. If the Zap stops triggering, is turned off, or errors, the check-in doesn't arrive and Ned POSTs a signed
`fire` to your callback once the interval passes.

Webhooks by Zapier is a Premium app (it needs a paid Zapier plan).

## Make the watch (once)

```bash
curl -s -X POST https://api.ned.watch/v1/watches -H 'Content-Type: application/json' -H 'X-Ned-Ref: zapier' \
  -d '{"type":"deadman","interval_s":90000,"callback_url":"https://you.example/hooks/ned","condition":{"label":"my-zap","arm":true}}'
```

Keep `watch_id`, `signing_secret` and `agent_key` from the answer. Pick `interval_s` a bit longer than the gap you
expect between runs (90000 s = 25 hours for a daily Zap). `"arm": true` starts the deadman's clock at registration.

## Zaps that trigger on events, not a schedule

A deadman fits a Zap that should run at least every so often ("a new order at least once a day"). For Zaps that may
legitimately be quiet for days, set a longer interval, or put the check-in in a separate scheduled Zap
(Schedule by Zapier) that checks the thing you care about.

## Notes

- Use "Custom Request" rather than "POST": it lets you set headers and leave the body empty.
- EU: `https://api-eu.ned.watch`.
- Not tested inside Zapier (no account was used); the HTTP call is the same one tested elsewhere in this pack.
