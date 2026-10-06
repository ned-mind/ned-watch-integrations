"""OpenAI Agents SDK + Ned against the local Ned Watch (and the remote MCP, run locally).
Run: ../../.venv-oai/bin/python -m pytest -q"""
import json

import pytest
from agents import Agent, Runner, set_tracing_disabled

from nedwatch import Ned
from nedwatch.integrations.openai_agents import NedAgentHooks, NedRunHooks, hosted_mcp_tool, mcp_server, run
from conftest_common import harness

from agent import build
from stub_model import StubModel

set_tracing_disabled(True)


def ned_for(ned_base, hook_url, state_file):
    return Ned(base=ned_base, callback_url=hook_url, state=state_file)


async def test_run_hooks_success(ned_base, hook_url, state_file):
    ned = ned_for(ned_base, hook_url, state_file)
    hooks = NedRunHooks(every="1h", max="15m", ned=ned, heartbeat_every=0)
    res = await Runner.run(build(), "Status?", hooks=hooks)
    assert res.final_output == "All done."
    m = hooks.monitor
    assert m.name == "triage-agent"
    assert (await ned.aget(m.deadman.id))["last_checkin"]
    assert (await ned.aget(m.overrun.id))["run"]["last"]["status"] == "finished"
    assert harness.entry(ned_base, m.deadman.id) == "openai-agents"


async def test_handoff_is_one_run(ned_base, hook_url, state_file):
    ned = ned_for(ned_base, hook_url, state_file)
    specialist = Agent(name="specialist", instructions="x", model=StubModel(answer="specialist answer"))
    triage = Agent(name="handoff-triage", instructions="x", handoffs=[specialist],
                   model=StubModel(call="transfer_to_specialist"))
    hooks = NedRunHooks(every="1h", max="15m", ned=ned)
    res = await Runner.run(triage, "go", hooks=hooks)
    assert res.final_output == "specialist answer"
    run_state = (await ned.aget(hooks.monitor.overrun.id))["run"]
    assert run_state["last"]["status"] == "finished" and "open" not in run_state      # one start, one finish


async def test_failure_with_run_wrapper(ned_base, hook_url, state_file):
    ned = ned_for(ned_base, hook_url, state_file)
    with pytest.raises(RuntimeError):
        await run(build(model=StubModel(fail=True), name="failing-agent"), "x", every="1h", max="15m", ned=ned)
    dm = ned.state.watch(ned.base, "deadman:failing-agent")
    ow = ned.state.watch(ned.base, "overrun:failing-agent")
    armed = (await ned.aget(dm["id"]))["last_checkin"]
    assert armed
    last = (await ned.aget(ow["id"]))["run"]["last"]                  # run() reports the failure (v1.9)
    assert last["status"] == "failed" and last["error"] == "RuntimeError: model provider is down"
    harness.age(ned_base, dm["id"], 7200)
    assert harness.wait_for(lambda: "fire" in harness.events(ned_base, dm["id"]))


async def test_failure_with_plain_hooks_leaves_overrun_open(ned_base, hook_url, state_file):
    ned = ned_for(ned_base, hook_url, state_file)
    hooks = NedRunHooks("plain-fail", max="15m", ned=ned)
    with pytest.raises(RuntimeError):
        await Runner.run(build(model=StubModel(fail=True)), "x", hooks=hooks)
    assert "open" in (await ned.aget(hooks.monitor.overrun.id))["run"]    # fires at the deadline


async def test_agent_hooks(ned_base, hook_url, state_file):
    ned = ned_for(ned_base, hook_url, state_file)
    a = build(name="hooked-agent")
    a.hooks = NedAgentHooks(every="1h", ned=ned)
    await Runner.run(a, "x")
    assert (await ned.aget(a.hooks.monitor.deadman.id))["last_checkin"]


async def test_mcp_server_config_against_local_remote_mcp(ned_base, hook_url, state_file):
    """The agent gets Ned's own MCP tools: the stub model calls quickstart through the remote MCP (run locally)."""
    with harness.local_mcp(ned_base) as url:
        server = mcp_server(url=url)
        async with server:
            names = {t.name for t in await server.list_tools()}
            assert {"quickstart", "deadman_checkin", "overrun_start", "watch_register"} <= names
            model = StubModel(call="quickstart", args={"callback_url": hook_url, "every_minutes": 60}, answer="watched")
            agent = Agent(name="self-registering", instructions="x", model=model, mcp_servers=[server])
            res = await Runner.run(agent, "watch yourself")
            assert res.final_output == "watched"
            import re
            wid = re.search(r"w_[0-9a-f]{12}", json.dumps(model.tool_output)).group(0)   # the tool's answer reached the model
            assert harness.entry(ned_base, wid) == "openai-agents"     # X-Ned-Ref passed through the MCP (v1.9)


def test_hosted_mcp_tool_shape():
    t = hosted_mcp_tool(agent_key="nw_example")
    assert t.tool_config["server_url"] == "https://api.ned.watch/mcp" and t.tool_config["type"] == "mcp"
    assert t.tool_config["headers"] == {"X-Ned-Ref": "openai-agents", "Authorization": "Bearer nw_example"}
    assert hosted_mcp_tool().tool_config["headers"] == {"X-Ned-Ref": "openai-agents"}


async def test_stdio_mcp_server_sends_ned_ref(ned_base, hook_url):
    """mcp_server_stdio() sets NED_REF; the stdio server (local copy of ned-watch-mcp) sends it as X-Ned-Ref."""
    import os, re
    from nedwatch.integrations.openai_agents import mcp_server_stdio
    here = os.path.dirname(os.path.abspath(__file__))
    py = os.path.join(here, "..", "..", ".venv-mcp", "bin", "python")
    srv = os.path.join(here, "..", "..", "testserver", "mcp_remote", "server.py")
    os.environ["NED_WATCH_API"] = ned_base
    try:
        server = mcp_server_stdio(command=py, args=[srv])
        assert server.params.env["NED_REF"] == "openai-agents"
        async with server:
            res = await server.call_tool("quickstart", {"callback_url": hook_url, "every_minutes": 60, "arm": True})
            wid = re.search(r"w_[0-9a-f]{12}", json.dumps(res.model_dump(), default=str)).group(0)
        assert harness.entry(ned_base, wid) == "openai-agents"
    finally:
        os.environ.pop("NED_WATCH_API", None)
