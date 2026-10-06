"""A scripted stand-in for the Claude Code CLI, used as the SDK's Transport in tests: it speaks the SDK's control
protocol (initialize, hook_callback, control_response) and the message stream, so the SDK's real hook machinery runs
without the CLI, a model, or the network. It plays: UserPromptSubmit -> PostToolUse (x tools) -> Stop -> result."""
import asyncio
import json
from typing import Any, AsyncIterator, Dict

from claude_agent_sdk._internal.transport import Transport


class FakeCLI(Transport):
    def __init__(self, session_id: str = "sess-1", tools: int = 1, is_error: bool = False, crash: bool = False):
        self.sid, self.tools, self.is_error, self.crash = session_id, tools, is_error, crash
        self.hooks: Dict[str, Any] = {}
        self.q: asyncio.Queue = asyncio.Queue()
        self.pending: Dict[str, asyncio.Future] = {}
        self.fired: list = []
        self.n = 0
        self._ready = False

    async def connect(self) -> None:
        self._ready = True

    def is_ready(self) -> bool:
        return self._ready

    async def write(self, data: str) -> None:
        for line in filter(None, data.splitlines()):
            m = json.loads(line)
            if m.get("type") == "control_request" and m["request"].get("subtype") == "initialize":
                self.hooks = m["request"].get("hooks") or {}
                await self.q.put({"type": "control_response", "response": {"subtype": "success", "request_id": m["request_id"],
                                                                           "response": {"commands": []}}})
            elif m.get("type") == "control_response":
                fut = self.pending.pop(m["response"]["request_id"], None)
                if fut and not fut.done():
                    fut.set_result(m["response"])
            elif m.get("type") == "user":
                asyncio.get_running_loop().create_task(self._play())

    async def _hook(self, event: str, extra: Dict[str, Any], tool_use_id: Any = None) -> None:
        for matcher in self.hooks.get(event, []):
            for cb in matcher["hookCallbackIds"]:
                self.n += 1
                rid = f"cli_{self.n}"
                fut = asyncio.get_running_loop().create_future()
                self.pending[rid] = fut
                inp = {"session_id": self.sid, "transcript_path": "/tmp/t.jsonl", "cwd": "/tmp", "hook_event_name": event, **extra}
                await self.q.put({"type": "control_request", "request_id": rid,
                                  "request": {"subtype": "hook_callback", "callback_id": cb, "input": inp, "tool_use_id": tool_use_id}})
                resp = await asyncio.wait_for(fut, 30)
                self.fired.append((event, resp.get("subtype")))

    async def _play(self) -> None:
        await self._hook("UserPromptSubmit", {"prompt": "do the thing"})
        for i in range(self.tools):
            await self._hook("PostToolUse", {"tool_name": "Bash", "tool_input": {"command": "true"}, "tool_response": "",
                                             "tool_use_id": f"tu_{i}"}, f"tu_{i}")
        if self.crash:
            await self.q.put(None)
            return
        await self._hook("Stop", {"stop_hook_active": False})
        await self.q.put({"type": "result", "subtype": "error_during_execution" if self.is_error else "success",
                          "duration_ms": 5, "duration_api_ms": 3, "is_error": self.is_error, "num_turns": 1,
                          "session_id": self.sid, "result": "done"})

    async def read_messages(self) -> AsyncIterator[Dict[str, Any]]:
        while True:
            m = await self.q.get()
            if m is None:
                return
            yield m

    async def end_input(self) -> None:
        await self.q.put(None)

    async def close(self) -> None:
        self._ready = False
        await self.q.put(None)
