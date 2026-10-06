"""cron / systemd / ned.sh against the local Ned Watch. The crontab lines and unit files in this folder are executed
as written, with only the API URL, ids, secrets and job path swapped for local ones.
Run: ../../.venv/bin/python -m pytest -q"""
import json
import os
import re
import shlex
import stat
import subprocess
import sys

import pytest

from nedwatch import Ned
from conftest_common import harness

HERE = os.path.dirname(os.path.abspath(__file__))
NED_SH = os.path.join(HERE, "ned.sh")
VENV_BIN = os.path.dirname(sys.executable)


def sh(args, env=None, **kw):
    e = {**os.environ, **(env or {})}
    return subprocess.run(args, capture_output=True, text=True, env=e, timeout=120, **kw)


def load_env(path):
    out = {}
    for line in open(path):
        k, _, v = line.strip().partition("=")
        if k:
            out[k] = v
    return out


@pytest.fixture
def setup_job(ned_base, hook_url, tmp_path):
    def make(name, every=3600, max_s=None):
        args = [NED_SH, "setup", name, str(every), hook_url] + ([str(max_s)] if max_s else [])
        p = sh(args, {"NED_API": ned_base, "NED_ENV_DIR": str(tmp_path)})
        assert p.returncode == 0, p.stderr
        path = p.stdout.strip()
        env = load_env(path)
        for secret in (env["NED_SIGNING_SECRET"], env.get("NED_OVERRUN_SECRET"), env["NED_AGENT_KEY"]):
            assert not secret or secret not in p.stdout + p.stderr       # setup prints the file path, never a secret
        assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
        return path, env
    return make


def ned_for(ned_base, env):
    return Ned(env["NED_AGENT_KEY"], base=ned_base, state=False)


def test_ned_sh_setup_checkin_tags_cron(ned_base, setup_job):
    path, env = setup_job("nightly")
    ned = ned_for(ned_base, env)
    g = ned.get(env["NED_WATCH_ID"])
    first = g["last_checkin"]
    assert first and g["condition"] == {"label": "nightly", "arm": True}   # armed at registration (v1.9)
    assert harness.entry(ned_base, env["NED_WATCH_ID"]) == "cron"
    p = sh([NED_SH, "checkin"], env)
    assert p.returncode == 0, p.stderr
    assert ned.get(env["NED_WATCH_ID"])["last_checkin"] != first


def test_ned_sh_run(ned_base, setup_job):
    path, env = setup_job("etl", max_s=1800)
    ned = ned_for(ned_base, env)
    assert sh([NED_SH, "run", "--", "sh", "-c", "echo working"], env).returncode == 0
    assert ned.get(env["NED_OVERRUN_ID"])["run"]["last"]["status"] == "finished"
    before = ned.get(env["NED_WATCH_ID"])["last_checkin"]
    assert sh([NED_SH, "run", "--", "sh", "-c", "exit 3"], env).returncode == 3
    assert ned.get(env["NED_WATCH_ID"])["last_checkin"] == before        # failure: no check-in
    last = ned.get(env["NED_OVERRUN_ID"])["run"]["last"]
    assert last["status"] == "failed" and last["error"] == "exit code 3"   # reported: Ned fires at once
    assert harness.wait_for(lambda: "fire" in harness.events(ned_base, env["NED_OVERRUN_ID"]))
    only_overrun = {k: v for k, v in env.items() if k not in ("NED_WATCH_ID", "NED_SIGNING_SECRET")}
    assert sh([NED_SH, "run", "--", "false"], {**only_overrun, "NED_ON_ERROR": "leave_open"}).returncode == 1
    assert "open" in ned.get(env["NED_OVERRUN_ID"])["run"]               # leave_open: fires at the deadline instead


def test_ned_sh_never_fails_the_job_when_ned_is_down(setup_job):
    path, env = setup_job("offline")
    p = sh([NED_SH, "run", "--", "sh", "-c", "echo ran"], {**env, "NED_API": "http://127.0.0.1:9"})
    assert p.returncode == 0 and "ran" in p.stdout and "ned.sh" in p.stderr
    assert sh([NED_SH, "checkin"], {**env, "NED_API": "http://127.0.0.1:9", "NED_STRICT": "1"}).returncode == 1


def crontab_lines():
    return [l for l in open(os.path.join(HERE, "crontab.example")) if l.strip() and not l.startswith("#")]


def cron_cmd(line):
    return line.split(None, 5)[5].strip()                               # drop the 5 schedule fields


def test_crontab_line_1_curl(ned_base, setup_job, tmp_path):
    path, env = setup_job("backup")
    home = tmp_path / "home"
    (home / ".config" / "ned-watch").mkdir(parents=True)
    (home / ".config" / "ned-watch" / "backup.secret").write_text(env["NED_SIGNING_SECRET"])
    cmd = cron_cmd(crontab_lines()[0]).replace("https://api.ned.watch", ned_base).replace("w_0123456789ab", env["NED_WATCH_ID"]) \
        .replace("/usr/local/bin/backup.sh", "true")
    ned = ned_for(ned_base, env)
    before = ned.get(env["NED_WATCH_ID"])["last_checkin"]
    p = sh(["/bin/sh", "-c", cmd], {"HOME": str(home)})
    assert p.returncode == 0, p.stderr
    assert ned.get(env["NED_WATCH_ID"])["last_checkin"] != before
    p = sh(["/bin/sh", "-c", cmd.replace("true &&", "false &&", 1)], {"HOME": str(home)})
    assert p.returncode != 0                                            # job failed: curl never ran


def test_crontab_line_2_ned_run(ned_base, hook_url, tmp_path):
    cmd = cron_cmd(crontab_lines()[1]).replace("/usr/local/bin/backup.sh", "true").replace("ned-run", os.path.join(VENV_BIN, "ned-run"), 1)
    state = str(tmp_path / "state.json")
    p = sh(["/bin/sh", "-c", cmd], {"NED_API": ned_base, "NED_CALLBACK_URL": hook_url, "NED_STATE": state})
    assert p.returncode == 0, p.stderr
    d = json.load(open(state))[ned_base]
    ned = Ned(d["agent_key"], base=ned_base, state=False)
    assert ned.get(d["watches"]["deadman:backup"]["id"])["last_checkin"]
    assert ned.get(d["watches"]["overrun:backup"]["id"])["run"]["last"]["status"] == "finished"


def test_crontab_line_3_ned_sh(ned_base, setup_job, tmp_path):
    path, env = setup_job("backup3", max_s=1800)
    cmd = cron_cmd(crontab_lines()[2]).replace("$HOME/.config/ned-watch/backup.env", path) \
        .replace("/usr/local/bin/ned.sh", NED_SH).replace("/usr/local/bin/backup.sh", "true")
    p = sh(["/bin/sh", "-c", cmd])
    assert p.returncode == 0, p.stderr
    assert ned_for(ned_base, env).get(env["NED_OVERRUN_ID"])["run"]["last"]["status"] == "finished"


def unit(name):
    out = {}
    for line in open(os.path.join(HERE, name)):
        if "=" in line and not line.startswith(("#", "[")):
            k, _, v = line.strip().partition("=")
            out.setdefault(k, []).append(v)
    return out


def systemd_expand(cmd, env):
    """systemd's ${VAR} substitution, then its quote-aware word splitting (no shell)."""
    return shlex.split(re.sub(r"\$\{(\w+)\}", lambda m: env.get(m.group(1), ""), cmd))


def test_systemd_execstartpost(ned_base, setup_job):
    path, env = setup_job("backup-systemd")
    u = unit("backup.service")
    assert u["Type"] == ["oneshot"] and u["EnvironmentFile"] == ["/etc/ned-watch/backup.env"]
    post = u["ExecStartPost"][0]
    assert post.startswith("-")                                         # a failed check-in never fails the unit
    argv = systemd_expand(post[1:].replace("https://api.ned.watch", ned_base), env)
    argv[0] = "curl"
    ned = ned_for(ned_base, env)
    before = ned.get(env["NED_WATCH_ID"])["last_checkin"]
    p = sh(argv)
    assert p.returncode == 0, p.stderr
    assert ned.get(env["NED_WATCH_ID"])["last_checkin"] != before
    t = unit("backup.timer")
    assert t["OnCalendar"] == ["*-*-* 03:00:00"] and t["WantedBy"] == ["timers.target"]


def test_systemd_ned_run_unit(ned_base, hook_url, tmp_path):
    u = unit("backup-ned-run.service")
    argv = systemd_expand(u["ExecStart"][0], {})
    assert argv[0] == "/usr/local/bin/ned-run"
    argv[0] = os.path.join(VENV_BIN, "ned-run")
    argv[-1] = "true"
    state = str(tmp_path / "state.json")
    p = sh(argv, {"NED_API": ned_base, "NED_CALLBACK_URL": hook_url, "NED_STATE": state})
    assert p.returncode == 0, p.stderr
    d = json.load(open(state))[ned_base]
    assert harness.entry(ned_base, d["watches"]["deadman:backup"]["id"]) == "systemd"
