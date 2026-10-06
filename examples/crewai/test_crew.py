"""CrewAI + Ned against the local Ned Watch. Run: ../../.venv-crewai/bin/python -m pytest -q"""
import pytest

from nedwatch import Ned
from nedwatch.integrations.crewai import NedCrew, NedCrewListener, akickoff, kickoff
from conftest_common import harness

from crew import build


def ned_for(ned_base, hook_url, state_file):
    return Ned(base=ned_base, callback_url=hook_url, state=state_file)


def test_kickoff_wrapper(ned_base, hook_url, state_file):
    ned = ned_for(ned_base, hook_url, state_file)
    out = kickoff(build(), every="1d", max="30m", ned=ned)
    assert "report is done" in out.raw
    dm = ned.state.watch(ned.base, "deadman:research-crew")         # default name: crew.name
    ow = ned.state.watch(ned.base, "overrun:research-crew")
    assert ned.get(dm["id"])["last_checkin"]
    assert ned.get(ow["id"])["run"]["last"]["status"] == "finished"
    assert harness.entry(ned_base, dm["id"]) == "crewai"


def test_step_and_task_callbacks_heartbeat(ned_base, hook_url, state_file):
    ned = ned_for(ned_base, hook_url, state_file)
    seen = []
    crew = build(name="beat-crew")
    crew.task_callback = lambda out: seen.append("mine")             # the user's own callback keeps working
    n = NedCrew(every="1h", ned=ned, heartbeat=True, heartbeat_every=0).attach(crew)
    beats = []
    orig = n.monitor.deadman.beat
    n.monitor.deadman.beat = lambda min_interval=30.0: beats.append(1) or orig(min_interval)
    crew.kickoff()                                                   # plain kickoff: only the callbacks are active
    assert seen == ["mine"] and len(beats) >= 2                      # >= one step + one task
    assert ned.get(n.monitor.deadman.id)["last_checkin"]


def test_failure_no_checkin(ned_base, hook_url, state_file):
    ned = ned_for(ned_base, hook_url, state_file)
    with pytest.raises(Exception):
        kickoff(build(fail=True, name="broken-crew"), every="1h", max="30m", ned=ned, heartbeat=False)
    dm = ned.state.watch(ned.base, "deadman:broken-crew")
    ow = ned.state.watch(ned.base, "overrun:broken-crew")
    armed = ned.get(dm["id"])["last_checkin"]
    assert armed                                                     # armed when the kickoff started
    with pytest.raises(Exception):
        kickoff(build(fail=True, name="broken-crew"), every="1h", max="30m", ned=ned, heartbeat=False)
    assert ned.get(dm["id"])["last_checkin"] == armed
    last = ned.get(ow["id"])["run"]["last"]
    assert last["status"] == "failed" and "model provider is down" in last["error"]
    harness.age(ned_base, dm["id"], 7200)
    assert harness.wait_for(lambda: "fire" in harness.events(ned_base, dm["id"]))


async def test_async_kickoff(ned_base, hook_url, state_file):
    ned = ned_for(ned_base, hook_url, state_file)
    out = await akickoff(build(name="async-crew"), every="1h", ned=ned)
    assert "report is done" in out.raw
    assert ned.get(ned.state.watch(ned.base, "deadman:async-crew")["id"])["last_checkin"]


def test_event_bus_listener(ned_base, hook_url, state_file):
    from crewai.events import crewai_event_bus
    ned = ned_for(ned_base, hook_url, state_file)
    with crewai_event_bus.scoped_handlers():
        NedCrewListener(every="1h", max="15m", ned=ned)
        build(name="listened-crew").kickoff()
        crewai_event_bus.flush()
    dm = ned.state.watch(ned.base, "deadman:listened-crew")
    ow = ned.state.watch(ned.base, "overrun:listened-crew")
    assert harness.wait_for(lambda: ned.get(dm["id"])["last_checkin"])
    assert harness.wait_for(lambda: ned.get(ow["id"])["run"].get("last", {}).get("status") == "finished")
