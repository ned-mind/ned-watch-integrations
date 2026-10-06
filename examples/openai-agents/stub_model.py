"""A scripted stand-in for an OpenAI model, so the example and tests run with no API key and no network.
It calls each tool it is given once (first the one named in `call`, if any), then answers."""
import json
from typing import Any

from agents.items import ModelResponse
from agents.models.interface import Model
from agents.usage import Usage
from openai.types.responses import ResponseFunctionToolCall, ResponseOutputMessage, ResponseOutputText


class StubModel(Model):
    def __init__(self, answer: str = "All done.", call: str | None = None, args: dict | None = None, fail: bool = False):
        self.answer, self.call, self.args, self.fail = answer, call, args or {}, fail
        self.called = False
        self.tool_output: Any = None

    async def get_response(self, system_instructions, input, model_settings, tools, output_schema, handoffs, tracing,
                           *, previous_response_id=None, conversation_id=None, prompt=None, **kw) -> ModelResponse:
        if self.fail:
            raise RuntimeError("model provider is down")
        if isinstance(input, list):
            for item in input:
                if isinstance(item, dict) and item.get("type") == "function_call_output":
                    self.tool_output = item.get("output")
        if self.call and not self.called:
            self.called = True
            out = [ResponseFunctionToolCall(type="function_call", id="fc_1", call_id="call_1", name=self.call,
                                            arguments=json.dumps(self.args))]
        else:
            out = [ResponseOutputMessage(type="message", id="msg_1", role="assistant", status="completed",
                                         content=[ResponseOutputText(type="output_text", text=self.answer, annotations=[])])]
        return ModelResponse(output=out, usage=Usage(), response_id=None)

    def stream_response(self, *a, **kw):
        raise NotImplementedError
