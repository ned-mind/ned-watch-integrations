"""LangGraph + Ned against the local Ned Watch. Run: ../../.venv-lc/bin/python -m pytest -q"""
import pytest

from nedwatch import Ned
from nedwatch.integrations.langchain import AsyncNedCallbackHandler, NedCallbackHandler
from conftest_common import harness

from agent import build


def ned_for(ned_base, hook_url, state_file):
    return Ned(base=ned_base, callback_url=hook_url, state=state_file)


def test_success_checks_in_finishes_and_tags_langgraph(ned_base, hook_url, state_file):
    ned = ned_for(ned_base, hook_url, state_file)
    h = NedCallbackHandler(every="1h", max="20m", ned=ned)
    out = build().invoke({"question": "q"}, config={"callbacks": [h]})
    assert out["answer"] == "42"
    m = h.monitor
    assert m.name == "research-agent"                       # default name: the compiled graph's name
    assert ned.get(m.deadman.id)["last_checkin"]
    assert ned.get(m.overrun.id)["run"]["last"]["status"] == "finished"
    assert harness.entry(ned_base, m.deadman.id) == "langgraph"


def test_failure_does_not_check_in(ned_base, hook_url, state_file):
    ned = ned_for(ned_base, hook_url, state_file)
    h = NedCallbackHandler("flaky-agent", every="1h", max="20m", ned=ned)
    with pytest.raises(RuntimeError):
        build(fail=True).invoke({"question": "q"}, config={"callbacks": [h]})
    m = h.monitor
    armed = ned.get(m.deadman.id)["last_checkin"]
    assert armed                                               # armed at start (the clock runs even if run 1 fails)
    with pytest.raises(RuntimeError):
        build(fail=True).invoke({"question": "q"}, config={"callbacks": [h]})
    assert ned.get(m.deadman.id)["last_checkin"] == armed      # failures never check in
    last = ned.get(m.overrun.id)["run"]["last"]                # reported as failed with the exception (v1.9)
    assert last["status"] == "failed" and last["error"] == "RuntimeError: the agent fell over"
    harness.age(ned_base, m.deadman.id, 7200)                  # two hours of nothing but failures: Ned fires
    assert harness.wait_for(lambda: "fire" in harness.events(ned_base, m.deadman.id))


def test_silence_fires(ned_base, hook_url, state_file):
    ned = ned_for(ned_base, hook_url, state_file)
    h = NedCallbackHandler("quiet-agent", every="5m", ned=ned)
    build().invoke({"question": "q"}, config={"callbacks": [h]})
    wid = h.monitor.deadman.id
    harness.age(ned_base, wid, 3600)
    assert harness.wait_for(lambda: "fire" in harness.events(ned_base, wid))


async def test_async_handler(ned_base, hook_url, state_file):
    ned = ned_for(ned_base, hook_url, state_file)
    h = AsyncNedCallbackHandler("async-agent", every="1h", max="10m", ned=ned)
    out = await build().ainvoke({"question": "q"}, config={"callbacks": [h]})
    assert out["answer"] == "42"
    assert (await ned.aget(h.monitor.deadman.id))["last_checkin"]
    assert (await ned.aget(h.monitor.overrun.id))["run"]["last"]["status"] == "finished"


async def test_sync_handler_under_ainvoke(ned_base, hook_url, state_file):
    ned = ned_for(ned_base, hook_url, state_file)
    h = NedCallbackHandler("sync-in-async", every="1h", ned=ned)
    await build().ainvoke({"question": "q"}, config={"callbacks": [h]})
    assert ned.get(h.monitor.deadman.id)["last_checkin"]


def test_checkin_node(ned_base, hook_url, state_file):
    ned = ned_for(ned_base, hook_url, state_file)
    build(with_checkin_node=True, ned=ned).invoke({"question": "q"})
    rec = ned.state.watch(ned.base, "deadman:research-agent-node")
    assert ned.get(rec["id"])["last_checkin"]
    assert harness.entry(ned_base, rec["id"]) == "langgraph"


def test_heartbeat_on_llm_reply(ned_base, hook_url, state_file):
    ned = ned_for(ned_base, hook_url, state_file)
    h = NedCallbackHandler("beats", every="1h", ned=ned, heartbeat=True, heartbeat_every=0)
    from langchain_core.language_models.fake_chat_models import FakeListChatModel
    FakeListChatModel(responses=["x"]).invoke("hi", config={"callbacks": [h]})   # a bare LLM call: top-level, so start/end too
    assert ned.get(h.monitor.deadman.id)["last_checkin"]


def test_bare_client_detects_langgraph(ned_base, hook_url, state_file):
    """Enhancement: with no ref given, the client tags new agents with the framework it finds already imported."""
    import langgraph  # noqa: F401  (imported by agent.py anyway)
    from nedwatch import detect_framework
    assert detect_framework() == "langgraph"
    ned = Ned(base=ned_base, callback_url=hook_url, state=state_file)
    assert ned.ref == "langgraph"
    assert harness.entry(ned_base, ned.deadman("auto-detected").id) == "langgraph"
