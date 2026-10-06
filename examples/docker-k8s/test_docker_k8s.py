"""Docker and Kubernetes recipes. No image is built and no cluster is used (that would pull from public registries
outside the egress proxy); instead:
  - the manifests are validated against the Kubernetes 1.31 JSON schemas (schema/, from yannh/kubernetes-json-schema)
  - each container's entrypoint + command runs locally against the local Ned Watch, with the env the manifest gives it.
Run: ../../.venv/bin/python -m pytest -q"""
import json
import os
import shlex
import subprocess
import sys

import jsonschema
import yaml

from nedwatch import Ned
from conftest_common import harness

HERE = os.path.dirname(os.path.abspath(__file__))
VENV_BIN = os.path.dirname(sys.executable)


def docs():
    return list(yaml.safe_load_all(open(os.path.join(HERE, "cronjob.yaml"))))


def schema(name):
    return json.load(open(os.path.join(HERE, "schema", name)))


def test_manifests_match_kubernetes_schema():
    secret, cron = docs()
    jsonschema.validate(secret, schema("secret-v1.json"))
    jsonschema.validate(cron, schema("cronjob-batch-v1.json"))
    c = cron["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"][0]
    assert c["envFrom"][0]["secretRef"]["name"] == secret["metadata"]["name"]
    assert set(secret["stringData"]) == {"NED_AGENT_KEY", "NED_CALLBACK_URL"}


def dockerfile(name):
    out = {}
    for line in open(os.path.join(HERE, name)):
        if line.strip() and not line.startswith("#"):
            k, _, v = line.strip().partition(" ")
            out.setdefault(k, []).append(v)
    return out


def run(argv, env):
    return subprocess.run(argv, capture_output=True, text=True, timeout=120, env={**os.environ, **env})


def agent_key(ned_base, hook_url, tmp_path):
    st = str(tmp_path / "s.json")
    Ned(base=ned_base, callback_url=hook_url, state=st).deadman("bootstrap").ensure()
    return json.load(open(st))[ned_base]["agent_key"]


def test_k8s_container_command(ned_base, hook_url, tmp_path):
    secret, cron = docs()
    c = cron["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"][0]
    key = agent_key(ned_base, hook_url, tmp_path)
    env = {"NED_AGENT_KEY": key, "NED_CALLBACK_URL": hook_url, "NED_API": ned_base, "NED_STATE": str(tmp_path / "pod1.json")}
    argv = [os.path.join(VENV_BIN, c["command"][0])] + c["command"][1:] + [os.path.join(HERE, "job.sh")]
    p = run(argv, env)
    assert p.returncode == 0 and "report generated" in p.stdout, p.stderr
    # a second pod: fresh filesystem (new state file), same key -> same watches, no re-arm
    p = run(argv, {**env, "NED_STATE": str(tmp_path / "pod2.json")})
    assert p.returncode == 0, p.stderr
    a = json.load(open(tmp_path / "pod1.json"))[ned_base]["watches"]
    b = json.load(open(tmp_path / "pod2.json"))[ned_base]["watches"]
    assert a["deadman:nightly-report"]["id"] == b["deadman:nightly-report"]["id"]
    ned = Ned(key, base=ned_base, state=False)
    assert ned.get(a["overrun:nightly-report"]["id"])["run"]["last"]["status"] == "finished"


def test_k8s_ref_tags_new_agents(ned_base, hook_url, tmp_path):
    secret, cron = docs()
    c = cron["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"][0]
    env = {"NED_CALLBACK_URL": hook_url, "NED_API": ned_base, "NED_STATE": str(tmp_path / "p.json")}   # no key: a new agent
    p = run([os.path.join(VENV_BIN, c["command"][0])] + c["command"][1:] + ["true"], env)
    assert p.returncode == 0, p.stderr
    wid = json.load(open(tmp_path / "p.json"))[ned_base]["watches"]["deadman:nightly-report"]["id"]
    assert harness.entry(ned_base, wid) == "k8s"


def test_dockerfile_entrypoint(ned_base, hook_url, tmp_path):
    d = dockerfile("Dockerfile")
    entry, cmd = json.loads(d["ENTRYPOINT"][0]), json.loads(d["CMD"][0])
    assert cmd == ["/app/job.sh"] and entry[0] == "ned-run"
    env = {"NED_CALLBACK_URL": hook_url, "NED_API": ned_base, "NED_STATE": str(tmp_path / "d.json"),
           "NED_REF": dict(x.split("=", 1) for x in d["ENV"])["NED_REF"]}
    p = run([os.path.join(VENV_BIN, entry[0])] + entry[1:] + [os.path.join(HERE, "job.sh")], env)
    assert p.returncode == 0 and "report generated" in p.stdout, p.stderr
    wid = json.load(open(tmp_path / "d.json"))[ned_base]["watches"]["deadman:nightly-report"]["id"]
    assert harness.entry(ned_base, wid) == "docker"


def test_dockerfile_curl_entrypoint(ned_base, hook_url, tmp_path):
    d = dockerfile("Dockerfile.curl")
    entry = json.loads(d["ENTRYPOINT"][0])
    assert entry[:2] == ["/usr/local/bin/ned.sh", "run"]
    p = run([os.path.join(HERE, "ned.sh"), "setup", "curl-job", "86400", hook_url, "1800"],
            {"NED_API": ned_base, "NED_ENV_DIR": str(tmp_path), "NED_REF": "docker"})
    assert p.returncode == 0, p.stderr
    envfile = p.stdout.strip()
    env = dict(l.strip().split("=", 1) for l in open(envfile) if "=" in l)
    p = run([os.path.join(HERE, "ned.sh")] + entry[1:] + [os.path.join(HERE, "job.sh")], env)    # docker run --env-file
    assert p.returncode == 0 and "report generated" in p.stdout, p.stderr
    ned = Ned(env["NED_AGENT_KEY"], base=ned_base, state=False)
    assert ned.get(env["NED_OVERRUN_ID"])["run"]["last"]["status"] == "finished"
    assert harness.entry(ned_base, env["NED_WATCH_ID"]) == "docker"
