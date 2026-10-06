#!/usr/bin/env python3
"""Writes the two importable workflows. Edit here, then: python tools/make_workflows.py"""
import json, os, uuid

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API = "https://api.ned.watch"
NS = uuid.UUID("6f1d3a52-9c1e-4a5b-8f7e-2b9d0c4e1a77")
nid = lambda name: str(uuid.uuid5(NS, name))           # stable ids, so diffs stay readable

REF_HEADER = {"parameters": [{"name": "X-Ned-Ref", "value": "n8n"}]}
SAFE = {"retryOnFail": True, "maxTries": 3, "waitBetweenTries": 2000, "onError": "continueRegularOutput"}  # Ned never breaks the flow


def http(name, url, pos, cred_name=None, body=None, notes=None, headers=None):
    hp = {"parameters": REF_HEADER["parameters"] + (headers or [])}
    p = {"method": "POST", "url": url, "sendHeaders": True, "headerParameters": hp,
         "options": {"timeout": 20000}}
    if cred_name:
        p = {"method": "POST", "url": url, "authentication": "genericCredentialType", "genericAuthType": "httpHeaderAuth",
             "sendHeaders": True, "headerParameters": REF_HEADER, "options": {"timeout": 20000}}
    if body is not None:
        p.update({"sendBody": True, "specifyBody": "json", "jsonBody": body})
    n = {"parameters": p, "id": nid(name), "name": name, "type": "n8n-nodes-base.httpRequest", "typeVersion": 4.2,
         "position": pos, **SAFE}
    if cred_name:
        n["credentials"] = {"httpHeaderAuth": {"id": "REPLACE_WITH_YOUR_CREDENTIAL_ID", "name": cred_name}}
    if notes:
        n["notes"] = notes
    return n


def link(*names):
    return {a: {"main": [[{"node": b, "type": "main", "index": 0}]]} for a, b in zip(names, names[1:])}


run_id = '={\n  "run_id": "n8n-{{ $execution.id }}"\n}'
watched = {
    "name": "Ned Watch: watched workflow (deadman + overrun)",
    "nodes": [
        {"parameters": {"rule": {"interval": [{"field": "hours", "hoursInterval": 1}]}}, "id": nid("Schedule Trigger"),
         "name": "Schedule Trigger", "type": "n8n-nodes-base.scheduleTrigger", "typeVersion": 1.2, "position": [0, 0]},
        http("Ned: run started", f"{API}/v1/watches/w_OVERRUN_ID/start", [220, 0], "Ned overrun secret", run_id,
             "Overrun: Ned fires if this run doesn't reach 'run finished' within max_runtime_s."),
        {"parameters": {}, "id": nid("Your work goes here"), "name": "Your work goes here", "type": "n8n-nodes-base.noOp",
         "typeVersion": 1, "position": [440, 0], "notes": "Replace with your workflow's real steps."},
        http("Ned: run finished", f"{API}/v1/watches/w_OVERRUN_ID/finish", [660, 0], "Ned overrun secret", run_id),
        http("Ned: check in", f"{API}/v1/checkin/w_DEADMAN_ID", [880, 0], "Ned deadman secret", None,
             "Deadman: Ned fires if this check-in doesn't arrive within interval_s. Keep it last: it runs only when every step before it succeeded."),
    ],
    "connections": link("Schedule Trigger", "Ned: run started", "Your work goes here", "Ned: run finished", "Ned: check in"),
    "settings": {"executionOrder": "v1"},
    "pinData": {},
    "meta": {"templateCredsSetupCompleted": False},
    "tags": [],
}

register_body = ('={\n  "type": "deadman",\n  "interval_s": 3600,\n  "callback_url": "https://your-agent.example/hooks/ned",\n'
                 '  "condition": {"label": "my-n8n-workflow", "arm": true},\n  "meta": {"ref": "n8n"}\n}')
overrun_body = ('={\n  "type": "overrun",\n  "max_runtime_s": 1800,\n  "callback_url": "https://your-agent.example/hooks/ned",\n'
                '  "condition": {"label": "my-n8n-workflow"}\n}')
setup = {
    "name": "Ned Watch: register watches (run once)",
    "nodes": [
        {"parameters": {}, "id": nid("Run once"), "name": "Run once", "type": "n8n-nodes-base.manualTrigger",
         "typeVersion": 1, "position": [0, 0]},
        http("Register deadman", f"{API}/v1/watches", [220, 0], None, register_body,
             "Returns watch_id, signing_secret and (first time only) agent_key. Save them; make a Header Auth credential "
             "'Ned deadman secret' with Name=Authorization, Value=Bearer <signing_secret>."),
        http("Register overrun", f"{API}/v1/watches", [440, 0], None, overrun_body,
             "Uses the agent_key from the step before, so both watches belong to one agent. Save its signing_secret as a "
             "Header Auth credential 'Ned overrun secret' (Name=Authorization, Value=Bearer <signing_secret>).",
             headers=[{"name": "Authorization", "value": "=Bearer {{ $json.agent_key }}"}]),
    ],
    "connections": link("Run once", "Register deadman", "Register overrun"),
    "settings": {"executionOrder": "v1"},
    "pinData": {},
    "tags": [],
}
for fn, wf in (("ned-watched-workflow.json", watched), ("ned-register-watches.json", setup)):
    with open(os.path.join(HERE, fn), "w") as f:
        json.dump(wf, f, indent=2)
        f.write("\n")
print("wrote ned-watched-workflow.json, ned-register-watches.json")
