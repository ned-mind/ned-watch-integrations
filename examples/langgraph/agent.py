"""A small LangGraph agent watched by Ned. The model is a stub (no API key); swap in your real chat model.

    pip install ned-watch langgraph
    export NED_CALLBACK_URL=https://your-agent.example/hooks/ned     # where Ned wakes you
    python agent.py
"""
from typing import TypedDict

from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langgraph.graph import END, START, StateGraph

from nedwatch.integrations.langchain import NedCallbackHandler, checkin_node


class State(TypedDict, total=False):
    question: str
    answer: str


def build(model=None, fail: bool = False, with_checkin_node: bool = False, ned=None):
    model = model or FakeListChatModel(responses=["42"])

    def think(state: State) -> State:
        if fail:
            raise RuntimeError("the agent fell over")
        return {"answer": model.invoke(state["question"]).content}

    g = StateGraph(State)
    g.add_node("think", think)
    g.add_edge(START, "think")
    if with_checkin_node:   # alternative to the callback handler: an explicit node on the success path
        g.add_node("ned", checkin_node("research-agent-node", every="1h", ned=ned))
        g.add_edge("think", "ned")
        g.add_edge("ned", END)
    else:
        g.add_edge("think", END)
    return g.compile(name="research-agent")


if __name__ == "__main__":
    graph = build()
    ned = NedCallbackHandler(every="1h", max="20m")        # name defaults to the graph's name: research-agent
    out = graph.invoke({"question": "meaning of life?"}, config={"callbacks": [ned]})
    print(out["answer"])
