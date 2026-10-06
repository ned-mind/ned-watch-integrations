# n8n

- `ned-register-watches.json`: run once; registers a deadman and an overrun (tagged `X-Ned-Ref: n8n`)
- `ned-watched-workflow.json`: Schedule Trigger -> run started -> your steps -> run finished -> check in
- `validate.py` + `n8n_params.json`: checks a workflow's shape and node parameters against names extracted from
  n8n's own node sources (`tools/extract_n8n_params.py`, commit recorded in the JSON)
- `tools/make_workflows.py`: generates the two JSON files

Docs: [../../docs/n8n.md](../../docs/n8n.md).

```bash
../../.venv/bin/python validate.py ned-watched-workflow.json ned-register-watches.json
../../.venv/bin/python -m pytest -q
```

The test replays each HTTP Request node (method, URL, headers, Header Auth credential, JSON body with expressions
filled) in connection order against a local Ned Watch. n8n itself was not run: importing into a live n8n is unverified.
