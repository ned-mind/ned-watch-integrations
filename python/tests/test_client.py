"""The Python client against a local Ned Watch (testserver/run.py): real API, SQLite, scheduler ticking."""
import asyncio
import json
import sys
from datetime import timedelta

import pytest

from nedwatch import Ned, NedConfigError, NedError, verify_signature
from nedwatch._util import seconds, slug
from conftest_common import harness


def mk(ned_base, hook_url, state_file, **kw):
    return Ned(base=ned_base, callback_url=hook_url, state=state_file, **kw)


# ---------- units ----------

def test_durations():
    assert seconds("90s") == 90 and seconds("20m") == 1200 and seconds("1h30m") == 5400 and seconds("1d") == 86400
    assert seconds(300) == 300 and seconds("300") == 300 and seconds(timedelta(minutes=2)) == 120
    with pytest.raises(ValueError):
        seconds("soon")
    assert slug("nightly sync/eu") == "nightly-sync-eu"


# ---------- deadman ----------

def test_deadman_registers_once_and_tags_entry(ned_base, hook_url, state_file):
    ned = mk(ned_base, hook_url, state_file)
    w = ned.deadman("nightly-sync", every="1h")
    wid = w.id
    assert wid.startswith("w_") and ned.has_key
    assert harness.entry(ned_base, wid) == "python"          # X-Ned-Ref / meta.ref reached _entry
    # a second client on the same state file reuses it without asking Ned again
    assert mk(ned_base, hook_url, state_file).deadman("nightly-sync", every="1h").id == wid
    # with the key but no state file, Ned's own idempotency returns the same watch
    key = json.load(open(state_file))[ned_base]["agent_key"]
    again = Ned(key, base=ned_base, callback_url=hook_url, state=False).deadman("nightly-sync", every="1h")
    assert again.id == wid
    # a different name is a different watch
    assert ned.deadman("other-job", every="1h").id != wid
    # the signed test callback arrived and verifies with the watch's secret
    h = next(h for h in harness.hooks(ned_base) if h["body"].get("watch_id") == wid and h["body"]["event"] == "test")
    assert verify_signature(w.signing_secret, h["headers"], h["raw"])
    assert not verify_signature("whs_wrong", h["headers"], h["raw"])


def test_explicit_ref(ned_base, hook_url, state_file):
    ned = mk(ned_base, hook_url, state_file, ref="Cron")
    assert harness.entry(ned_base, ned.deadman("ref-test", every="1h").id) == "cron"


def test_decorator_checks_in_only_on_success_then_fire_and_clear(ned_base, hook_url, state_file):
    ned = mk(ned_base, hook_url, state_file)
    dm = ned.deadman("decorated", every="5m")

    @dm
    def ok():
        return 42

    @dm
    def boom():
        raise RuntimeError("nope")

    assert ok() == 42
    first = ned.get(dm.id)["last_checkin"]
    assert first is not None
    with pytest.raises(RuntimeError):
        boom()
    assert ned.get(dm.id)["last_checkin"] == first                     # a failed run doesn't check in
    # silence: move the last check-in an hour back; the scheduler fires
    harness.age(ned_base, dm.id, 3600)
    assert harness.wait_for(lambda: "fire" in harness.events(ned_base, dm.id))
    ok()                                                                # check in again: Ned clears
    assert harness.wait_for(lambda: "clear" in harness.events(ned_base, dm.id))


def test_spec_change_retires_old_watch(ned_base, hook_url, state_file):
    ned = mk(ned_base, hook_url, state_file)
    a = ned.deadman("resized", every="1h").id
    b = ned.deadman("resized", every="2h").id
    assert a != b
    assert ned.get(a)["status"] == "cancelled" and ned.get(b)["status"] == "active"


def test_checkin_by_name_and_id(ned_base, hook_url, state_file):
    ned = mk(ned_base, hook_url, state_file)
    w = ned.deadman("by-name", every="1h").ensure()            # handles register on first use
    assert ned.checkin("by-name")["ok"] is True
    assert ned.checkin(w.id)["ok"] is True
    other = Ned(base=ned_base, state=False)
    with pytest.raises(NedConfigError):
        other.checkin(w.id)
    assert other.checkin(w.id, signing_secret=w.signing_secret)["ok"] is True


def test_reregisters_a_watch_cancelled_elsewhere(ned_base, hook_url, state_file):
    ned = mk(ned_base, hook_url, state_file)
    w = ned.deadman("gone", every="1h")
    old = w.id
    ned._call("DELETE", f"/v1/watches/{old}", bearer=ned._key)         # cancelled behind the client's back
    w.checkin()
    assert w.id != old and ned.get(w.id)["last_checkin"]


def test_missing_callback_is_a_config_error(ned_base, state_file):
    with pytest.raises(NedConfigError):
        Ned(base=ned_base, state=state_file).deadman("x").ensure()


# ---------- overrun / run ----------

def test_run_context_starts_and_finishes(ned_base, hook_url, state_file):
    ned = mk(ned_base, hook_url, state_file)
    with ned.run("etl", max="20m") as r:
        assert r.started and r.started["deadline"]
        wid = r.overrun.id
        assert ned.get(wid)["run"]["open"]["run_id"] == r.run_id
    st = ned.get(wid)["run"]
    assert "open" not in st and st["last"]["status"] == "finished" and st["last"]["run_id"] == r.run_id
    assert harness.entry(ned_base, wid) == "python"


def fires(ned_base, wid):
    return [h["body"] for h in harness.hooks(ned_base) if h["body"].get("watch_id") == wid and h["body"]["event"] == "fire"]


def test_run_failure_is_reported_at_once(ned_base, hook_url, state_file):
    """v1.9: an exception finishes the run with status failed and a short, redacted error; Ned fires at once."""
    ned = mk(ned_base, hook_url, state_file)
    with pytest.raises(ValueError):
        with ned.run("etl-fail", max="20m") as r:
            raise ValueError("db login failed for postgres://etl:hunter2@db/x token=abc123secretvalue\nsecond line")
    last = ned.get(r.overrun.id)["run"]["last"]
    assert last["status"] == "failed" and last["run_id"] == r.run_id
    assert last["error"].startswith("ValueError: db login failed for postgres://[redacted]@db/x token=[redacted]")
    assert "hunter2" not in last["error"] and "second line" not in last["error"]
    f = harness.wait_for(lambda: fires(ned_base, r.overrun.id))
    assert f and "reported failure: ValueError" in f[0]["reason"]
    with ned.run("etl-fail", max="20m"):                          # the next good run clears it
        pass
    assert harness.wait_for(lambda: "clear" in harness.events(ned_base, r.overrun.id))


def test_run_failure_leave_open_and_finish_options(ned_base, hook_url, state_file):
    ned = mk(ned_base, hook_url, state_file)
    with pytest.raises(ValueError):
        with ned.run("keep-open", max="20m", on_error="leave_open") as r:
            raise ValueError("x")
    assert ned.get(r.overrun.id)["run"]["open"]["run_id"] == r.run_id
    with pytest.raises(ValueError):
        with ned.run("close-ok", max="20m", on_error="finish") as r2:
            raise ValueError("x")
    assert ned.get(r2.overrun.id)["run"]["last"]["status"] == "finished"


def test_run_failure_with_deadman_finishes_and_skips_checkin(ned_base, hook_url, state_file):
    ned = mk(ned_base, hook_url, state_file)
    with ned.run("etl-both", max="20m", every="1d") as r:
        pass
    assert ned.get(r.deadman.id)["last_checkin"]
    first = ned.get(r.deadman.id)["last_checkin"]
    with pytest.raises(ValueError):
        with ned.run("etl-both", max="20m", every="1d") as r2:
            raise ValueError("crash")
    assert ned.get(r2.overrun.id)["run"]["last"]["status"] == "failed"    # reported: Ned fires at once
    assert ned.get(r2.deadman.id)["last_checkin"] == first                # no check-in: the deadman fires


def test_run_as_decorator_new_run_each_call(ned_base, hook_url, state_file):
    ned = mk(ned_base, hook_url, state_file)
    seen = []

    @ned.run("decorated-run", max="10m")
    def job(x):
        return x * 2

    assert job(2) == 4 and job(3) == 6
    w = ned.overrun("decorated-run", max="10m")
    assert ned.get(w.id)["run"]["last"]["status"] == "finished"


# ---------- fail-open ----------

def test_fail_open_and_strict(state_file):
    dead = Ned(base="http://127.0.0.1:9", callback_url="http://127.0.0.1:9/h", state=state_file, retries=0, timeout=1)

    @dead.deadman("unreachable", every="1h")
    def job():
        return "done"

    assert job() == "done"                       # Ned being down never breaks the job
    with dead.run("unreachable-run", max="5m") as r:
        pass
    assert r.started is None
    strict = Ned(base="http://127.0.0.1:9", callback_url="http://127.0.0.1:9/h", state=False, retries=0, timeout=1, strict=True)
    with pytest.raises(NedError):
        strict.deadman("x", every="1h")(lambda: 1)()


def test_bad_secret_is_401(ned_base, hook_url, state_file):
    ned = mk(ned_base, hook_url, state_file)
    w = ned.deadman("auth", every="1h")
    with pytest.raises(NedError) as e:
        ned.checkin(w.id, signing_secret="whs_not_it")
    assert e.value.status == 401


# ---------- async ----------

async def test_async_decorator_and_run(ned_base, hook_url, state_file):
    ned = mk(ned_base, hook_url, state_file)
    dm = ned.deadman("async-job", every="1h")

    @dm
    async def work():
        await asyncio.sleep(0)
        return "ok"

    assert await work() == "ok"
    assert (await ned.aget(dm.id))["last_checkin"]
    async with ned.run("async-etl", max="15m") as r:
        await asyncio.sleep(0)
    assert (await ned.aget(r.overrun.id))["run"]["last"]["status"] == "finished"
    assert (await ned.acheckin(dm))["ok"] is True


async def test_async_without_httpx(ned_base, hook_url, state_file, monkeypatch):
    monkeypatch.setitem(sys.modules, "httpx", None)          # import httpx -> ImportError: stdlib path in a thread
    ned = mk(ned_base, hook_url, state_file)
    w = ned.deadman("async-stdlib", every="1h")
    assert (await w.acheckin())["ok"] is True


def test_first_run_failure_is_still_noticed(ned_base, hook_url, state_file):
    """Ned's clock starts at the first check-in; the decorator arms the watch before the job runs, so a job that fails
    on its very first run (and never checks in) still fires."""
    ned = mk(ned_base, hook_url, state_file)
    dm = ned.deadman("fails-from-day-one", every="5m")

    @dm
    def job():
        raise RuntimeError("misconfigured")

    with pytest.raises(RuntimeError):
        job()
    armed = ned.get(dm.id)["last_checkin"]
    assert armed
    with pytest.raises(RuntimeError):
        job()
    assert ned.get(dm.id)["last_checkin"] == armed            # armed once only
    harness.age(ned_base, dm.id, 3600)
    assert harness.wait_for(lambda: "fire" in harness.events(ned_base, dm.id))


def test_stateless_container_does_not_rearm(ned_base, hook_url, state_file):
    """A container with no state file re-registers each run (Ned returns the same watch). Arming must not check in
    again, or a job that always fails would keep its deadman quiet."""
    first = mk(ned_base, hook_url, state_file)
    first.deadman("container-job", every="1h").ensure()
    key = json.load(open(state_file))[ned_base]["agent_key"]

    def run_once():
        ned = Ned(key, base=ned_base, callback_url=hook_url, state=False)

        @ned.deadman("container-job", every="1h")
        def job():
            raise RuntimeError("always fails")
        with pytest.raises(RuntimeError):
            job()
        return ned

    ned = run_once()
    wid = ned.deadman("container-job", every="1h").id
    armed = ned.get(wid)["last_checkin"]
    assert armed                                    # never checked in before: armed once
    run_once()
    run_once()
    assert ned.get(wid)["last_checkin"] == armed    # later stateless runs see it was armed and stay quiet


def test_deadman_armed_at_registration_and_idempotent(ned_base, hook_url, state_file):
    """v1.9: condition.arm=true starts the clock at registration; it is part of the condition, so the same name +
    settings still return the same watch."""
    ned = mk(ned_base, hook_url, state_file)
    w = ned.deadman("armed-at-birth", every="5m").ensure()
    g = ned.get(w.id)
    assert g["last_checkin"] and g["condition"] == {"label": "armed-at-birth", "arm": True}
    key = json.load(open(state_file))[ned_base]["agent_key"]
    assert Ned(key, base=ned_base, callback_url=hook_url, state=False).deadman("armed-at-birth", every="5m").id == w.id
    harness.age(ned_base, w.id, 3600)                               # a job that never runs at all still fires
    assert harness.wait_for(lambda: "fire" in harness.events(ned_base, w.id))


def test_arm_fallback_when_server_rejects_arm(ned_base, hook_url, state_file, monkeypatch):
    ned = mk(ned_base, hook_url, state_file)
    real = ned._call

    def picky(method, path, **kw):                                 # a server that refuses condition.arm
        body = kw.get("body") or {}
        if path == "/v1/watches" and (body.get("condition") or {}).get("arm"):
            raise NedError("422", 422, {"error": "unknown condition key arm"})
        return real(method, path, **kw)
    monkeypatch.setattr(ned, "_call", picky)
    dm = ned.deadman("old-server", every="1h")

    @dm
    def job():
        raise RuntimeError("fails")
    with pytest.raises(RuntimeError):
        job()
    g = ned.get(dm.id)
    assert g["condition"] == {"label": "old-server"} and g["last_checkin"]     # registered without arm, armed by a check-in
    again = mk(ned_base, hook_url, state_file)
    monkeypatch.setattr(again, "_call", picky)
    assert again.deadman("old-server", every="1h").id == dm.id                 # state file hit: no re-registration


def test_error_summary_redacts():
    from nedwatch._util import error_summary
    e = RuntimeError("call failed: Authorization: Bearer nw_" + "a" * 48 + " key=whs_" + "b" * 48)
    out = error_summary(e)
    assert out.startswith("RuntimeError: call failed") and "a" * 20 not in out and "b" * 20 not in out
    assert len(error_summary("x" * 500)) <= 200
