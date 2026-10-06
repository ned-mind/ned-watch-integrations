# LangGraph and LangChain

Know when your LangGraph agent silently stops.

```python
from nedwatch.integrations.langchain import NedCallbackHandler      # pip install ned-watch; set NED_CALLBACK_URL
graph.invoke(inputs, config={"callbacks": [NedCallbackHandler(every="1h", max="20m")]})
```

The handler watches the run you invoke (the graph or chain at the top), not each node inside it:

| event | what Ned gets |
|---|---|
| the top-level run starts | the deadman is armed; an overrun run starts (with `max=`) |
| it ends | the overrun run finishes; the deadman checks in |
| it raises | no check-in (the deadman fires when `every` passes); the overrun run is finished as failed with the error, so Ned fires at once |

The watch name defaults to the compiled graph's name (`builder.compile(name="research-agent")`), else the script name.
Pass a name to choose: `NedCallbackHandler("research-agent", every="1h")`.

## Options

```python
NedCallbackHandler(
    name=None,              # watch name
    every="1h",             # deadman: fire if no successful run for this long (default when max isn't set)
    max=None,               # overrun: fire if one run takes longer than this
    on_error="report",      # "report" (failed + error) | "leave_open" | "finish"
    heartbeat=False,        # True: each LLM reply / tool result also checks in (throttled to one per 30 s)
    ned=None,               # a nedwatch.Ned, to set the key, region or callback in code
)
```

`heartbeat=True` suits long-lived agents that run for hours: the deadman then means "no progress for `every`". It can
hide a run that does some work and then fails, so leave it off for scheduled runs.

Use `AsyncNedCallbackHandler` with `ainvoke` / `astream` to stay on the event loop (the sync handler also works there;
LangChain runs it in a thread).

## A check-in node instead

If you'd rather see it in the graph, add a node on the success path:

```python
from nedwatch.integrations.langchain import checkin_node
builder.add_node("ned", checkin_node("research-agent", every="1h"))
builder.add_edge("summarise", "ned")
builder.add_edge("ned", END)
```

It checks in and changes no state.

## Plain LangChain

The same handler works on any runnable: `chain.invoke(x, config={"callbacks": [NedCallbackHandler("summariser")]})`.
New agents are tagged `langgraph` when LangGraph is imported, else `langchain`.

## Example

`examples/langgraph/` has a runnable graph (with a stub model) and tests that run it against a local Ned Watch.
