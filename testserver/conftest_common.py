"""pytest fixtures shared by every Python test in the pack:
    ned_base   the local Ned Watch, once per session
    hook_url   its callback sink
    state_file a fresh state file per test (so each test starts with no agent key and no watches)
Import in a conftest.py:  from conftest_common import *  (after putting testserver/ on sys.path)."""
import os, sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402

_P = "http://127.0.0.1:9"     # tests never need the public internet: proxies point at a closed port (fail closed)
os.environ.update({"HTTPS_PROXY": _P, "HTTP_PROXY": _P, "https_proxy": _P, "http_proxy": _P, "ALL_PROXY": _P,
                   "all_proxy": _P, "NO_PROXY": "127.0.0.1,localhost", "no_proxy": "127.0.0.1,localhost"})
for _k in ("NED_AGENT_KEY", "NED_API", "NED_WATCH_API", "NED_CALLBACK_URL", "NED_REF", "NED_STATE", "NED_REGION",
           "NED_SIGNING_SECRET", "NED_WATCH_ID", "NED_WATCH_NAME"):
    os.environ.pop(_k, None)


@pytest.fixture(scope="session")
def ned_base():
    with harness.local_ned() as base:
        yield base


@pytest.fixture
def hook_url(ned_base):
    return f"{ned_base}/_test/hook"


@pytest.fixture
def state_file(tmp_path):
    return str(tmp_path / "state.json")


__all__ = ["ned_base", "hook_url", "state_file", "harness"]
