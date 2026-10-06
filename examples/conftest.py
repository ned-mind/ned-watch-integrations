"""Shared by every example's tests: the local Ned Watch, and egress safety.

Egress safety: tests never need the public internet. Proxy variables point at a closed local port, so anything that
honours them and tries a public host (or production Ned) fails at once instead of connecting; 127.0.0.1 is exempt.
Framework telemetry and tracing are switched off, and no LLM is ever called (each example stubs its model)."""
import os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "testserver"))

_P = "http://127.0.0.1:9"          # closed port: fail closed
os.environ.update({
    "HTTPS_PROXY": _P, "HTTP_PROXY": _P, "https_proxy": _P, "http_proxy": _P, "ALL_PROXY": _P, "all_proxy": _P,
    "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost",
    # telemetry / tracing off
    "OTEL_SDK_DISABLED": "true", "CREWAI_DISABLE_TELEMETRY": "true", "CREWAI_DISABLE_TRACKING": "true",
    "CREWAI_TRACING_ENABLED": "false", "CREWAI_TESTING": "true", "LITELLM_LOCAL_MODEL_COST_MAP": "True",
    "OPENAI_AGENTS_DISABLE_TRACING": "1", "LANGCHAIN_TRACING_V2": "false", "LANGSMITH_TRACING": "false",
    "ANONYMIZED_TELEMETRY": "false", "DO_NOT_TRACK": "1",
})
for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "LANGSMITH_API_KEY", "LANGCHAIN_API_KEY"):
    os.environ.pop(k, None)

from conftest_common import *  # noqa: F401,F403,E402
