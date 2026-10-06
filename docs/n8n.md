# n8n

Know when your n8n workflow silently stops.

```
Import examples/n8n/ned-register-watches.json, set your callback URL in both nodes, run it once.
Import examples/n8n/ned-watched-workflow.json, paste the two watch ids, add two Header Auth credentials.
Move your steps in between "Ned: run started" and "Ned: run finished".
```

Both files use only core nodes (Schedule Trigger, Manual Trigger, No Op, HTTP Request), so no community nodes are needed.

## The watched workflow

```
Schedule Trigger -> Ned: run started -> [your steps] -> Ned: run finished -> Ned: check in
```

| node | call | what it means |
|---|---|---|
| Ned: run started | `POST /v1/watches/<overrun id>/start` with `{"run_id": "n8n-{{ $execution.id }}"}` | overrun: Ned fires if "run finished" doesn't follow within the limit |
| Ned: run finished | `POST /v1/watches/<overrun id>/finish` with the same run id | closes the run (a late finish sends `clear` with the runtime) |
| Ned: check in | `POST /v1/checkin/<deadman id>` | deadman: Ned fires if this doesn't arrive within the interval |

"Ned: check in" is last, so it only runs when every step before it succeeded. A failing workflow therefore never checks
in, and Ned tells you once the interval passes. (To report a failure at once, an Error Trigger workflow can POST
`{"run_id": "n8n-<execution id>", "status": "failed", "error": "..."}` to the overrun's finish URL.)

Every Ned node is set to **retry 3 times** and **On Error: Continue**, so a problem reaching Ned never fails your
workflow. Each sends `X-Ned-Ref: n8n`.

## Setup, step by step

1. Import `ned-register-watches.json`. In both HTTP nodes replace `https://your-agent.example/hooks/ned` with your
   callback URL, and `my-n8n-workflow` with a name for the job. Run it once.
   - "Register deadman" answers with `watch_id`, `signing_secret` and `agent_key`. Keep all three.
   - "Register overrun" uses that `agent_key`, so both watches belong to one agent. Keep its `watch_id` and `signing_secret`.
2. Create two credentials of type **Header Auth**: name `Ned deadman secret` (Name `Authorization`, Value
   `Bearer <deadman signing_secret>`) and `Ned overrun secret` (the same with the overrun's secret). The secrets live in
   n8n's credential store, not in the workflow.
3. Import `ned-watched-workflow.json`. Replace `w_OVERRUN_ID` and `w_DEADMAN_ID` in the URLs, pick the two credentials
   in the Ned nodes, set the schedule, and put your own steps where "Your work goes here" is.
4. The deadman is registered with `"arm": true`, so its clock started at registration: a workflow that never runs is
   noticed too.

Only need one of the two? Delete the other nodes: a deadman alone is just the last node.

## Notes

- Interval: the deadman's `interval_s` (3600 in the template) should be a bit longer than your schedule.
- EU: use `https://api-eu.ned.watch` in every URL.
- The JSON was checked against parameter names taken from n8n's own node sources (HTTP Request v4.2, Schedule Trigger
  v1.2), and each HTTP call was replayed against a local Ned Watch. It hasn't been imported into a running n8n yet.
