"""Claude Agent SDK + Ned against the local Ned Watch. The SDK's own query()/hook machinery runs; the CLI is replaced by
a scripted Transport (fake_cli.py), so no model and no network. Run: ../../.venv-claude/bin/python -m pytest -q"""
import claude_agent_sdk
import pytest
from claude_agent_sdk import ClaudeAgentOptions, HookMatcher, ResultMessage

from nedwatch import Ned
from nedwatch.integrations.claude_agent_sdk import NedHooks, mcp_servers, query
from conftest_common import harness

from fake_cli import FakeCLI


def ned_for(ned_base, hook_url, state_file):
    return Ned(base=ned_base, callback_url=hook_url, state=state_file)


async def test_hooks_through_the_real_sdk(ned_base, hook_url, state_file):
    ned = ned_for(ned_base, hook_url, state_file)
    h = NedHooks("support-agent", every="1h", max="20m", ned=ned, heartbeat=True, heartbeat_every=0)
    cli = FakeCLI(tools=2)
    msgs = [m async for m in claude_agent_sdk.query(prompt="hi", options=ClaudeAgentOptions(hooks=h.hooks()), transport=cli)]
    assert isinstance(msgs[-1], ResultMessage)
    assert [e for e, _ in cli.fired] == ["UserPromptSubmit", "PostToolUse", "PostToolUse", "Stop"]
    assert all(s == "success" for _, s in cli.fired)
    m = h.monitor
    assert (await ned.aget(m.deadman.id))["last_checkin"]
    assert (await ned.aget(m.overrun.id))["run"]["last"]["status"] == "finished"
    assert harness.entry(ned_base, m.deadman.id) == "claude-agent-sdk"


async def test_merge_keeps_user_hooks(ned_base, hook_url, state_file):
    ned = ned_for(ned_base, hook_url, state_file)
    seen = []

    async def mine(inp, tid, ctx):
        seen.append(inp["hook_event_name"])
        return {}

    h = NedHooks("merged", every="1h", ned=ned)
    hooks = h.merge({"Stop": [HookMatcher(hooks=[mine])]})
    cli = FakeCLI(tools=0)
    [m async for m in claude_agent_sdk.query(prompt="hi", options=ClaudeAgentOptions(hooks=hooks), transport=cli)]
    assert seen == ["Stop"] and (await ned.aget(h.monitor.deadman.id))["last_checkin"]


async def test_query_wrapper_error_result_is_a_failure(ned_base, hook_url, state_file):
    ned = ned_for(ned_base, hook_url, state_file)
    msgs = [m async for m in query(prompt="hi", name="wrapped", every="1h", max="20m", ned=ned, transport=FakeCLI())]
    assert isinstance(msgs[-1], ResultMessage)
    dm = ned.state.watch(ned.base, "deadman:wrapped")
    ow = ned.state.watch(ned.base, "overrun:wrapped")
    good = (await ned.aget(dm["id"]))["last_checkin"]
    assert good and (await ned.aget(ow["id"]))["run"]["last"]["status"] == "finished"
    msgs = [m async for m in query(prompt="hi", name="wrapped", every="1h", max="20m", ned=ned, transport=FakeCLI(is_error=True))]
    assert msgs[-1].is_error
    assert (await ned.aget(dm["id"]))["last_checkin"] == good             # an error result never checks in
    last = (await ned.aget(ow["id"]))["run"]["last"]                      # reported as failed (v1.9)
    assert last["status"] == "failed" and last["error"] == "result error_during_execution"
    harness.age(ned_base, dm["id"], 7200)
    assert harness.wait_for(lambda: "fire" in harness.events(ned_base, dm["id"]))


async def test_query_wrapper_cli_dies_without_result(ned_base, hook_url, state_file):
    ned = ned_for(ned_base, hook_url, state_file)
    [m async for m in query(prompt="hi", name="crashy", max="20m", ned=ned, transport=FakeCLI(crash=True))]
    ow = ned.state.watch(ned.base, "overrun:crashy")
    last = (await ned.aget(ow["id"]))["run"]["last"]                      # no result message: reported as failed
    assert last["status"] == "failed" and last["error"] == "no result message"


def test_mcp_server_configs():
    cfg = mcp_servers(agent_key="nw_example", local=True)
    assert cfg["ned-watch"] == {"type": "http", "url": "https://api.ned.watch/mcp",
                                "headers": {"X-Ned-Ref": "claude-agent-sdk", "Authorization": "Bearer nw_example"}}
    assert cfg["ned-watch-local"] == {"type": "stdio", "command": "uvx", "args": ["ned-watch-mcp"],
                                      "env": {"NED_REF": "claude-agent-sdk", "NED_AGENT_KEY": "nw_example"}}
    assert mcp_servers() == {"ned-watch": {"type": "http", "url": "https://api.ned.watch/mcp", "headers": {"X-Ned-Ref": "claude-agent-sdk"}}}
    ClaudeAgentOptions(mcp_servers=cfg)                                   # accepted by the SDK's options type


async def test_remote_mcp_config_reaches_ned_tools(ned_base, hook_url):
    """The http config's URL/headers shape works against the remote MCP (run locally): list tools, call quickstart."""
    import httpx2
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client
    with harness.local_mcp(ned_base) as url:
        cfg = mcp_servers(url=url)["ned-watch"]
        async with httpx2.AsyncClient(headers=cfg.get("headers") or {}, trust_env=False) as hc, \
                streamable_http_client(cfg["url"], http_client=hc) as streams:
            async with ClientSession(streams[0], streams[1]) as s:
                await s.initialize()
                names = {t.name for t in (await s.list_tools()).tools}
                assert {"quickstart", "deadman_checkin", "overrun_start"} <= names
                res = await s.call_tool("quickstart", {"callback_url": hook_url, "every_minutes": 60})
                assert not res.is_error
                import json, re
                wid = re.search(r"w_[0-9a-f]{12}", json.dumps(res.model_dump(), default=str)).group(0)
    assert harness.entry(ned_base, wid) == "claude-agent-sdk"                 # X-Ned-Ref passed through (v1.9)


async def test_stdio_mcp_config_sends_ned_ref(ned_base, hook_url):
    """The stdio config's env (NED_REF) reaches Ned: run the local copy of ned-watch-mcp with that env, call quickstart."""
    import json, os, re
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    here = os.path.dirname(os.path.abspath(__file__))
    cfg = mcp_servers(local=True, remote=False)["ned-watch"]
    params = StdioServerParameters(command=os.path.join(here, "..", "..", ".venv-mcp", "bin", "python"),
                                   args=[os.path.join(here, "..", "..", "testserver", "mcp_remote", "server.py")],
                                   env={**cfg["env"], "NED_WATCH_API": ned_base, "PATH": os.environ["PATH"]})
    async with stdio_client(params) as streams:
        async with ClientSession(streams[0], streams[1]) as s:
            await s.initialize()
            res = await s.call_tool("quickstart", {"callback_url": hook_url, "every_minutes": 60, "arm": True})
            wid = re.search(r"w_[0-9a-f]{12}", json.dumps(res.model_dump(), default=str)).group(0)
    assert harness.entry(ned_base, wid) == "claude-agent-sdk"
