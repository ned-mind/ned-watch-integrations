# CrewAI + Ned Watch

A one-agent crew with a stub LLM (it calls one tool, then answers) watched three ways: the `kickoff()` wrapper,
`NedCrew(...).attach(crew)` step/task callbacks, and the `NedCrewListener` event-bus listener.
Docs: [../../docs/crewai.md](../../docs/crewai.md).

```bash
pip install -r requirements.txt
export NED_CALLBACK_URL=https://your-agent.example/hooks/ned
python crew.py
```

Tests (local Ned Watch; CrewAI telemetry and tracing switched off; no network):

```bash
../../.venv-crewai/bin/python -m pytest -q
```
