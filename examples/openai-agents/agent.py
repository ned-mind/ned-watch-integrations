"""An OpenAI Agents SDK agent watched by Ned (RunHooks), with Ned's MCP tools available to it.
The model is a stub here; drop `model=` to use your OpenAI model.

    pip install ned-watch openai-agents
    export NED_CALLBACK_URL=https://your-agent.example/hooks/ned
    python agent.py
"""
import asyncio

from agents import Agent, Runner, function_tool

from nedwatch.integrations.openai_agents import NedRunHooks
from stub_model import StubModel


@function_tool
def lookup(topic: str) -> str:
    """Look up a topic."""
    return f"{topic}: normal"


def build(model=None, name: str = "triage-agent") -> Agent:
    return Agent(name=name, instructions="Be brief.", tools=[lookup], model=model or StubModel(call="lookup", args={"topic": "x"}))


async def main() -> None:
    hooks = NedRunHooks(every="1h", max="15m")              # name defaults to the agent's name
    result = await Runner.run(build(), "Status?", hooks=hooks)
    print(result.final_output)


if __name__ == "__main__":
    asyncio.run(main())
