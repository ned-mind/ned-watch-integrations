"""Which agent framework is this process running? Used to tag new agents (X-Ned-Ref) and to pick a default watch name.
Looks only at modules already imported; it never imports anything itself."""
from __future__ import annotations

import os
import sys
from typing import Optional

# (ref, module, attribute that proves it's the framework and not a same-named module)
FRAMEWORKS = (
    ("langgraph", "langgraph", None),
    ("crewai", "crewai", "Crew"),
    ("openai-agents", "agents", "RunHooks"),
    ("claude-agent-sdk", "claude_agent_sdk", None),
    ("langchain", "langchain_core", None),
    ("llamaindex", "llama_index.core", None),
    ("autogen", "autogen_agentchat", None),
    ("pydantic-ai", "pydantic_ai", None),
    ("smolagents", "smolagents", None),
)


def detect_framework() -> Optional[str]:
    for ref, mod, attr in FRAMEWORKS:
        m = sys.modules.get(mod)
        if m is not None and (attr is None or hasattr(m, attr)):
            return ref
    return None


def default_name() -> str:
    """$NED_WATCH_NAME, else the running script's name (nightly_sync.py -> nightly_sync), else 'agent'."""
    env = os.environ.get("NED_WATCH_NAME")
    if env:
        return env
    main = sys.modules.get("__main__")
    path = getattr(main, "__file__", None) or (sys.argv[0] if sys.argv and sys.argv[0] not in ("", "-c") else "")
    stem = os.path.splitext(os.path.basename(path or ""))[0]
    if stem and stem not in ("__main__", "pytest", "ipykernel_launcher", "-m"):
        return stem
    return "agent"
