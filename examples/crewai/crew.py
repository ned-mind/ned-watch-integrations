"""A one-agent CrewAI crew watched by Ned. The LLM is a stub (no API key); use your real one in practice.

    pip install ned-watch crewai
    export NED_CALLBACK_URL=https://your-agent.example/hooks/ned
    python crew.py
"""
from typing import Any

from crewai import Agent, Crew, Task
from crewai.llms.base_llm import BaseLLM
from crewai.tools import tool

from nedwatch.integrations.crewai import kickoff


class StubLLM(BaseLLM):
    """Uses the lookup tool once, then gives a final answer, so the crew runs (one step, one task) with no provider."""
    fail: bool = False
    calls: int = 0

    def call(self, messages: Any, tools: Any = None, callbacks: Any = None, available_functions: Any = None,
             from_task: Any = None, from_agent: Any = None, response_model: Any = None) -> str:
        if self.fail:
            raise RuntimeError("model provider is down")
        self.calls += 1
        if self.calls == 1:
            return 'Thought: I should look it up\nAction: lookup\nAction Input: {"topic": "status"}'
        return "Thought: I now know the final answer\nFinal Answer: The report is done."

    def supports_function_calling(self) -> bool:
        return False

    def get_context_window_size(self) -> int:
        return 8192


@tool("lookup")
def lookup(topic: str) -> str:
    """Look up a topic."""
    return f"{topic}: all systems normal"


def build(fail: bool = False, name: str = "research-crew") -> Crew:
    llm = StubLLM(model="stub", fail=fail)
    researcher = Agent(role="Researcher", goal="Write a one-line report", backstory="Terse.", llm=llm, tools=[lookup],
                       verbose=False)
    task = Task(description="Write the report.", expected_output="One line.", agent=researcher)
    return Crew(name=name, agents=[researcher], tasks=[task], verbose=False)


if __name__ == "__main__":
    result = kickoff(build(), every="1d", max="30m")      # instead of build().kickoff()
    print(result.raw)
