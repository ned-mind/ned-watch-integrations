"""nedwatch / ned-run CLIs, as installed console scripts, against the local Ned Watch."""
import json
import os
import subprocess
import sys

from conftest_common import harness

BIN = os.path.dirname(sys.executable)


def run(args, ned_base, hook_url, state_file, **env):
    e = {**os.environ, "NED_API": ned_base, "NED_CALLBACK_URL": hook_url, "NED_STATE": state_file, **env}
    return subprocess.run(args, capture_output=True, text=True, env=e, timeout=120)


def secrets_in(state_file, base):
    d = json.load(open(state_file)).get(base, {})
    return [d.get("agent_key")] + [w["secret"] for w in d.get("watches", {}).values()]


def test_setup_then_checkin_never_prints_secrets(ned_base, hook_url, state_file):
    p = run([f"{BIN}/nedwatch", "setup", "--name", "cli-job", "--every", "1h", "--max", "30m"], ned_base, hook_url, state_file)
    assert p.returncode == 0, p.stderr
    out = p.stdout + p.stderr
    for s in secrets_in(state_file, ned_base):
        assert s and s not in out
    wid = json.load(open(state_file))[ned_base]["watches"]["deadman:cli-job"]["id"]
    assert harness.entry(ned_base, wid) == "cli"
    p = run([f"{BIN}/nedwatch", "checkin", "cli-job"], ned_base, hook_url, state_file)
    assert p.returncode == 0 and "checked in" in p.stdout, p.stderr


def test_doctor(ned_base, hook_url, state_file):
    p = run([f"{BIN}/nedwatch", "doctor"], ned_base, hook_url, state_file)
    assert p.returncode == 0 and "reached Ned" in p.stdout and "--create" in p.stdout, p.stdout
    p = run([f"{BIN}/nedwatch", "doctor", "--create"], ned_base, hook_url, state_file)
    assert p.returncode == 0 and "test callback delivered" in p.stdout, p.stdout
    p = run([f"{BIN}/nedwatch", "doctor"], ned_base, hook_url, state_file)
    assert "agent key accepted" in p.stdout, p.stdout
    for s in secrets_in(state_file, ned_base):
        assert s not in p.stdout
    import socket
    x = socket.socket(); x.bind(("127.0.0.1", 0)); dead = x.getsockname()[1]; x.close()
    bad = run([f"{BIN}/nedwatch", "doctor"], ned_base, f"http://127.0.0.1:{dead}/nothing", state_file)
    assert bad.returncode == 1 and "not delivered" in bad.stdout, bad.stdout
    down = run([f"{BIN}/nedwatch", "doctor", "--base", "http://127.0.0.1:9"], ned_base, hook_url, state_file)
    assert down.returncode == 1 and "can't reach" in down.stdout


def test_ned_run_success_failure_and_exit_codes(ned_base, hook_url, state_file):
    p = run([f"{BIN}/ned-run", "--name", "backup", "--max", "30m", "--every", "1d", "--", "sh", "-c", "echo hi"],
            ned_base, hook_url, state_file)
    assert p.returncode == 0 and "hi" in p.stdout, p.stderr
    st = json.load(open(state_file))[ned_base]["watches"]
    ow, dm = st["overrun:backup"]["id"], st["deadman:backup"]["id"]
    assert harness.entry(ned_base, ow) == "cron"
    key = json.load(open(state_file))[ned_base]["agent_key"]
    from nedwatch import Ned
    ned = Ned(key, base=ned_base, state=False)
    assert ned.get(ow)["run"]["last"]["status"] == "finished" and ned.get(dm)["last_checkin"]
    first = ned.get(dm)["last_checkin"]
    p = run([f"{BIN}/ned-run", "--name", "backup", "--max", "30m", "--every", "1d", "--", "sh", "-c", "exit 3"],
            ned_base, hook_url, state_file)
    assert p.returncode == 3
    assert ned.get(dm)["last_checkin"] == first                         # failed: no check-in
    assert ned.get(ow)["run"]["last"]["status"] == "failed" and ned.get(ow)["run"]["last"]["error"] == "exit code 3"
    # the command line never reaches Ned, only the exit status
    p = run([f"{BIN}/ned-run", "--max", "30m", "--", "sh", "-c", "exit 1 # password=hunter2"], ned_base, hook_url, state_file)
    assert p.returncode == 1
    ow2 = json.load(open(state_file))[ned_base]["watches"]["overrun:sh"]["id"]
    last = ned.get(ow2)["run"]["last"]
    assert last["status"] == "failed" and last["error"] == "exit code 1"
    assert harness.wait_for(lambda: [h for h in harness.hooks(ned_base) if h["body"].get("watch_id") == ow2 and h["body"]["event"] == "fire"])
    p = run([f"{BIN}/ned-run", "--", "/no/such/cmd"], ned_base, hook_url, state_file)
    assert p.returncode == 127


def test_ned_run_when_ned_is_down_still_runs_the_job(state_file, tmp_path):
    e = {**os.environ, "NED_API": "http://127.0.0.1:9", "NED_CALLBACK_URL": "http://127.0.0.1:9/h", "NED_STATE": state_file}
    p = subprocess.run([f"{BIN}/ned-run", "--name", "offline", "--", "sh", "-c", "echo ran; exit 0"], capture_output=True,
                       text=True, env=e, timeout=120)
    assert p.returncode == 0 and "ran" in p.stdout and "unaffected" in p.stderr
