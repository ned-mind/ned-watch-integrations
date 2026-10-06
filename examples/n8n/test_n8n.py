"""n8n workflows: shape-checked against n8n's node parameters (validate.py + n8n_params.json), then executed node by
node the way n8n's HTTP Request node would send them, against the local Ned Watch. n8n itself is not run (see README).
Run: ../../.venv/bin/python -m pytest -q"""
import copy
import json
import os
import re
import urllib.error
import urllib.request

from nedwatch import Ned
from conftest_common import harness

import validate

HERE = os.path.dirname(os.path.abspath(__file__))
WATCHED = json.load(open(os.path.join(HERE, "ned-watched-workflow.json")))
SETUP = json.load(open(os.path.join(HERE, "ned-register-watches.json")))


def test_workflows_validate():
    assert validate.check(WATCHED) == [] and validate.check(SETUP) == []


def test_validator_catches_mistakes():
    wf = copy.deepcopy(WATCHED)
    wf["nodes"][1]["parameters"]["sendHeader"] = True                           # typo
    wf["nodes"][1]["typeVersion"] = 9
    wf["nodes"][3]["parameters"]["headerParameters"]["parameters"].append({"name": "Authorization", "value": "Bearer whs_0123456789abcdef"})
    wf["connections"]["Ghost"] = {"main": [[{"node": "Nowhere", "type": "main", "index": 0}]]}
    errs = " | ".join(validate.check(wf))
    for want in ("unknown parameter 'sendHeader'", "typeVersion 9", "literal Authorization", "unknown node 'Ghost'", "real-looking secret"):
        assert want in errs, errs


def order(wf):
    """Nodes in execution order along the single main chain."""
    names = {n["name"]: n for n in wf["nodes"]}
    targets = {c["node"] for o in wf["connections"].values() for b in o["main"] for c in b}
    cur = next(n for n in names if n not in targets)
    out = [names[cur]]
    while cur in wf["connections"]:
        cur = wf["connections"][cur]["main"][0][0]["node"]
        out.append(names[cur])
    return out


def fill(s, ctx):
    s = str(s)
    if not s.startswith("="):
        return s
    return re.sub(r"\{\{\s*(.*?)\s*\}\}", lambda m: str(ctx[m.group(1)]), s[1:])


def execute(wf, ned_base, subst, creds, ctx):
    """Plays the workflow's HTTP Request nodes (POST, headers, Header Auth credential, JSON body) in order."""
    results = []
    prev = {}
    for n in order(wf):
        if n["type"] != "n8n-nodes-base.httpRequest":
            continue
        p = n["parameters"]
        c = {**ctx, "$json.agent_key": prev.get("agent_key")}
        url = p["url"]
        for a, b in subst.items():
            url = url.replace(a, b)
        headers = {h["name"]: fill(h["value"], c) for h in p.get("headerParameters", {}).get("parameters", [])}
        if p.get("authentication") == "genericCredentialType":
            cred = creds[n["credentials"][p["genericAuthType"]]["name"]]
            headers[cred["name"]] = cred["value"]
        body = None
        if p.get("sendBody"):
            raw = fill(p["jsonBody"], c)
            for a, b in subst.items():
                raw = raw.replace(a, b)
            body = json.dumps(json.loads(raw)).encode()
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=body, method=p["method"], headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                prev = json.loads(r.read() or b"{}")
                results.append((n["name"], r.status, prev))
        except urllib.error.HTTPError as e:
            results.append((n["name"], e.code, json.loads(e.read() or b"{}")))
    return results


def test_register_then_watched_run(ned_base, hook_url):
    base_sub = {"https://api.ned.watch": ned_base, "https://your-agent.example/hooks/ned": hook_url}
    res = execute(SETUP, ned_base, base_sub, {}, {"$workflow.name": SETUP["name"], "$execution.id": "1"})
    (n1, s1, dm), (n2, s2, ow) = res
    assert (s1, s2) == (201, 201), res
    assert harness.entry(ned_base, dm["watch_id"]) == "n8n"                   # X-Ned-Ref: n8n reached Ned
    ned = Ned(dm["agent_key"], base=ned_base, state=False)
    assert {w["watch_id"] for w in ned.watches()} == {dm["watch_id"], ow["watch_id"]}   # one agent, both watches
    creds = {"Ned deadman secret": {"name": "Authorization", "value": f"Bearer {dm['signing_secret']}"},
             "Ned overrun secret": {"name": "Authorization", "value": f"Bearer {ow['signing_secret']}"}}
    sub = {**base_sub, "w_OVERRUN_ID": ow["watch_id"], "w_DEADMAN_ID": dm["watch_id"]}
    res = execute(WATCHED, ned_base, sub, creds, {"$execution.id": "4242"})
    assert [(n, s) for n, s, _ in res] == [("Ned: run started", 200), ("Ned: run finished", 200), ("Ned: check in", 200)], res
    run = ned.get(ow["watch_id"])["run"]["last"]
    assert run["status"] == "finished" and run["run_id"] == "n8n-4242"
    assert ned.get(dm["watch_id"])["last_checkin"]
