#!/usr/bin/env python3
"""Pull the parameter vocabulary the validator checks against out of n8n's own node sources.

    # fetch (through the egress proxy) from n8n-io/n8n at a commit, then:
    python tools/extract_n8n_params.py <dir with the .ts files> <commit sha> > n8n_params.json

Files: HttpRequest.node.ts, V3/HttpRequestV3.node.ts, V3/Description.ts, Schedule/ScheduleTrigger.node.ts, NoOp/NoOp.node.ts,
ManualTrigger is not fetched (its only parameter-less shape is stable). Only names and versions are kept, no n8n code."""
import json, re, sys

d, sha = sys.argv[1], sys.argv[2]
read = lambda f: open(f"{d}/{f}", encoding="utf-8").read()

desc = read("Description.ts")
top = sorted(set(re.findall(r"^\t\tname: '(\w+)'", desc, re.M)))
opts_block = desc[desc.index("name: 'options'"):]
options = sorted(set(re.findall(r"^\t\t\t\tname: '(\w+)'", opts_block, re.M)))
methods = re.findall(r"value: '(DELETE|GET|HEAD|OPTIONS|PATCH|POST|PUT)'", desc)
http_versions = [float(x) for x in re.search(r"version: \[([\d., ]+)\]", read("HttpRequestV3.node.ts")).group(1).split(",")]
sched = read("ScheduleTrigger.node.ts")
sched_versions = [float(x) for x in re.search(r"version: \[([\d., ]+)\]", sched).group(1).split(",")]
fields = sorted(set(re.findall(r"field: \['(\w+)'\]", sched)))
interval_params = sorted(set(re.findall(r"^\t\t\t\t\t\t\t\tname: '(\w+)'", sched, re.M)))
noop_version = int(re.search(r"version: (\d+)", read("NoOp.node.ts")).group(1))
json.dump({
    "source": f"https://github.com/n8n-io/n8n/tree/{sha}/packages/nodes-base/nodes",
    "httpRequest": {"type": "n8n-nodes-base.httpRequest", "versions": http_versions, "parameters": top,
                    "options": options, "methods": sorted(set(methods)),
                    "authentication": ["none", "predefinedCredentialType", "genericCredentialType"],
                    "specify": ["keypair", "json"], "contentType": ["form-urlencoded", "multipart-form-data", "json", "binaryData", "raw"]},
    "scheduleTrigger": {"type": "n8n-nodes-base.scheduleTrigger", "versions": sched_versions, "fields": fields,
                        "intervalParameters": interval_params},
    "noOp": {"type": "n8n-nodes-base.noOp", "versions": [noop_version]},
    "manualTrigger": {"type": "n8n-nodes-base.manualTrigger", "versions": [1]},
    "nodeSettings": ["retryOnFail", "maxTries", "waitBetweenTries", "onError", "alwaysOutputData", "executeOnce", "notes",
                     "notesInFlow", "disabled"],
    "onError": ["stopWorkflow", "continueRegularOutput", "continueErrorOutput"],
}, sys.stdout, indent=1)
