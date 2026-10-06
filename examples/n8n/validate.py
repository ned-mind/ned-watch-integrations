#!/usr/bin/env python3
"""Checks an n8n workflow export against n8n's workflow shape and the node parameters in n8n_params.json (extracted
from n8n's own node sources at the commit it names). Exit 0 when clean.

    python validate.py ned-watched-workflow.json ned-register-watches.json
What it can't check: credentials resolving, expressions evaluating, and the n8n UI accepting the import."""
import json, os, re, sys, uuid

HERE = os.path.dirname(os.path.abspath(__file__))
P = json.load(open(os.path.join(HERE, "n8n_params.json")))
BY_TYPE = {P[k]["type"]: P[k] for k in ("httpRequest", "scheduleTrigger", "noOp", "manualTrigger")}


def check(wf: dict) -> list:
    errs = []
    e = errs.append
    for k in ("name", "nodes", "connections"):
        if k not in wf:
            e(f"missing top-level '{k}'")
    nodes = wf.get("nodes", [])
    names = [n.get("name") for n in nodes]
    if len(set(names)) != len(names):
        e("node names must be unique")
    ids = [n.get("id") for n in nodes]
    if len(set(ids)) != len(ids):
        e("node ids must be unique")
    for n in nodes:
        where = f"node '{n.get('name')}'"
        for k in ("parameters", "id", "name", "type", "typeVersion", "position"):
            if k not in n:
                e(f"{where}: missing '{k}'")
        try:
            uuid.UUID(str(n.get("id")))
        except ValueError:
            e(f"{where}: id is not a UUID")
        pos = n.get("position")
        if not (isinstance(pos, list) and len(pos) == 2 and all(isinstance(x, (int, float)) for x in pos)):
            e(f"{where}: position must be [x, y]")
        spec = BY_TYPE.get(n.get("type"))
        if not spec:
            e(f"{where}: type {n.get('type')} not in the checked set"); continue
        if float(n.get("typeVersion", -1)) not in [float(v) for v in spec["versions"]]:
            e(f"{where}: typeVersion {n.get('typeVersion')} not one of {spec['versions']}")
        for k in n:
            if k not in ("parameters", "id", "name", "type", "typeVersion", "position", "credentials", "webhookId") and k not in P["nodeSettings"]:
                e(f"{where}: unknown node key '{k}'")
        if "onError" in n and n["onError"] not in P["onError"]:
            e(f"{where}: onError {n['onError']}")
        p = n.get("parameters", {})
        if spec is P["httpRequest"]:
            h = P["httpRequest"]
            for k in p:
                if k not in h["parameters"]:
                    e(f"{where}: unknown parameter '{k}'")
            for k in p.get("options", {}):
                if k not in h["options"]:
                    e(f"{where}: unknown option '{k}'")
            if p.get("method", "GET") not in h["methods"]:
                e(f"{where}: method {p.get('method')}")
            if not str(p.get("url", "")).strip():
                e(f"{where}: url is empty")
            auth = p.get("authentication", "none")
            if auth not in h["authentication"]:
                e(f"{where}: authentication {auth}")
            if auth == "genericCredentialType":
                gat = p.get("genericAuthType")
                if not gat or gat not in (n.get("credentials") or {}):
                    e(f"{where}: genericAuthType {gat} needs a matching credentials entry")
            if p.get("sendHeaders"):
                hp = p.get("headerParameters", {}).get("parameters")
                if p.get("specifyHeaders", "keypair") == "keypair" and not (isinstance(hp, list) and all({"name", "value"} <= set(x) for x in hp)):
                    e(f"{where}: headerParameters.parameters must be a list of {{name, value}}")
                for x in hp or []:
                    if x["name"].lower() == "authorization" and not str(x["value"]).startswith("="):
                        e(f"{where}: a literal Authorization header puts a secret in the workflow; use a credential")
            if p.get("sendBody"):
                if p.get("contentType", "json") not in h["contentType"] or p.get("specifyBody", "keypair") not in h["specify"]:
                    e(f"{where}: body settings")
                if p.get("specifyBody") == "json":
                    body = re.sub(r"\{\{.*?\}\}", "X", str(p.get("jsonBody", "")).lstrip("="))
                    try:
                        json.loads(body)
                    except ValueError as ex:
                        e(f"{where}: jsonBody isn't JSON once expressions are filled: {ex}")
        if spec is P["scheduleTrigger"]:
            for iv in p.get("rule", {}).get("interval", []):
                if iv.get("field", "days") not in P["scheduleTrigger"]["fields"]:
                    e(f"{where}: interval field {iv.get('field')}")
                for k in iv:
                    if k not in P["scheduleTrigger"]["intervalParameters"]:
                        e(f"{where}: unknown interval parameter '{k}'")
    for src, outs in wf.get("connections", {}).items():
        if src not in names:
            e(f"connection from unknown node '{src}'")
        for branch in outs.get("main", []):
            for c in branch:
                if c.get("node") not in names or c.get("type") != "main" or not isinstance(c.get("index"), int):
                    e(f"bad connection {src} -> {c}")
    blob = json.dumps(wf)
    if re.search(r"whs_[0-9a-f]{8}|nw_[0-9a-f]{8}", blob):
        e("a real-looking secret is embedded in the workflow")
    return errs


if __name__ == "__main__":
    bad = 0
    for f in sys.argv[1:]:
        errs = check(json.load(open(f)))
        print(f"{f}: {'ok' if not errs else str(len(errs)) + ' problem(s)'}")
        for x in errs:
            print("  -", x)
        bad += len(errs)
    sys.exit(1 if bad else 0)
