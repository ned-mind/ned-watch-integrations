# CrewAI

Know when your crew silently stops.

```python
from nedwatch.integrations.crewai import kickoff      # pip install ned-watch; set NED_CALLBACK_URL
result = kickoff(crew, inputs={"topic": "..."}, every="1d", max="30m")    # instead of crew.kickoff(...)
```

| event | what Ned gets |
|---|---|
| kickoff starts | the deadman is armed; an overrun run starts (with `max=`) |
| kickoff returns | the overrun run finishes; the deadman checks in |
| kickoff raises | no check-in (the deadman fires when `every` passes); the overrun run is finished as failed with the error, so Ned fires at once |
| each agent step / task (with `heartbeat=True`) | a check-in, at most one per 30 s |

The watch name defaults to `crew.name` when you set one (`Crew(name="research-crew", ...)`), else the script name.
`akickoff(...)` wraps `crew.kickoff_async`.

## Keep calling crew.kickoff() yourself

```python
from nedwatch.integrations.crewai import NedCrew

ned = NedCrew("research-crew", every="1d", max="30m", heartbeat=True).attach(crew)   # sets step/task callbacks
result = ned.kickoff(crew, inputs={...})
```

`attach()` sets `crew.step_callback` and `crew.task_callback`, keeping any you already had (yours run first). With
`heartbeat=True` each step and finished task counts as "alive", which suits crews that run for hours. Leave it off for
scheduled crews: a crew that works for a while and then fails would otherwise look alive.

## Crews you don't kick off yourself

For `crewai run`, Flows, or crews deep inside other code, listen on CrewAI's event bus instead. Create the listener once:

```python
from nedwatch.integrations.crewai import NedCrewListener
NedCrewListener("research-crew", every="1d", max="30m")
```

It reacts to `CrewKickoffStartedEvent`, `CrewKickoffCompletedEvent` and `CrewKickoffFailedEvent`. CrewAI runs bus
handlers on worker threads, so the check-in lands a moment after kickoff returns.

## Options

`name`, `every` (default `"1h"` when `max` isn't set), `max`, `on_error` (`"report"`, `"leave_open"`, `"finish"`),
`heartbeat`, `ned` (a `nedwatch.Ned` for key/region/callback in code). New agents are tagged `crewai`.

## Example

`examples/crewai/` has a one-agent crew with a stub LLM and a tool, and tests against a local Ned Watch.
