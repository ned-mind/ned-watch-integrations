"""is_up / up_state: a local stub answers like /v1/up/{host}; bad input, network failure or a bad reply is state unknown,
never an exception. Every request stays on 127.0.0.1."""
import http.server, json, threading
import pytest
from nedwatch import is_up, up_state
from nedwatch.client import REGIONS

REPLIES = {"list.example": b"[1, 2]", "null.example": b"null", "string.example": b'"up"', "garbage.example": b"not json"}


class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        host = self.path.split("/v1/up/", 1)[1]
        body = REPLIES.get(host) or json.dumps({"host": host, "state": "degraded" if host == "status.example" else "unknown", "watches": [], "ask_again_s": 300}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
    def log_message(self, *a): pass


def _serve():
    srv = http.server.HTTPServer(("127.0.0.1", 0), H); threading.Thread(target=srv.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{srv.server_address[1]}"


@pytest.fixture(autouse=True)
def _local_only(monkeypatch):
    """No test may reach the real stations: both regions point at a closed local port unless a test says otherwise."""
    monkeypatch.setitem(REGIONS, "us", "http://127.0.0.1:9"); monkeypatch.setitem(REGIONS, "eu", "http://127.0.0.1:9")
    monkeypatch.delenv("NED_API", raising=False); monkeypatch.delenv("NED_WATCH_API", raising=False)


def test_is_up_by_host_and_url():
    base = _serve()
    assert is_up("status.example", base=base)["state"] == "degraded"
    assert up_state("https://status.example/api/v2/status.json?x=1", base=base) == "degraded"
    assert up_state("HTTPS://Status.Example:8443/x#frag", base=base) == "degraded"
    assert up_state("nobody.example", base=base) == "unknown"


def test_network_failure_is_unknown_not_an_exception():
    r = is_up("api.openai.com", base="http://127.0.0.1:9", timeout=1)
    assert r["state"] == "unknown" and r["error"]
    assert is_up("", base="http://127.0.0.1:9")["state"] == "unknown"


@pytest.mark.parametrize("host", ["bad host.example", "user@status.example", "status_example", "exämple.com", "[::1]", "a" * 300, "../etc", "..", ".", "-x.example", "x.example-", "a..b"])
def test_bad_host_is_unknown(host):
    r = is_up(host, base="http://127.0.0.1:9", timeout=1)
    assert r["state"] == "unknown" and r["error"] == "bad host", (host, r)
    assert up_state(host, base="http://127.0.0.1:9") == "unknown"


@pytest.mark.parametrize("host", [None, 42, 1.5, ["status.example"], {"h": 1}, b"status.example"])
def test_non_string_host_never_raises(host):
    r = is_up(host, base="http://127.0.0.1:9", timeout=1)
    assert r["state"] == "unknown" and r["error"] in ("bad host", "host required")
    assert up_state(host) == "unknown"


def test_none_ref_and_odd_inputs_never_raise():
    base = _serve()
    assert is_up("status.example", base=base, ref=None)["state"] == "degraded"
    assert is_up("status.example", base=base, ref=12345)["state"] == "degraded"
    assert is_up("status.example", base=base, ref="x\r\nInjected: 1")["state"] == "degraded"   # control characters dropped
    assert is_up("status.example", base=12345)["state"] == "unknown"
    assert is_up("status.example", base=base, timeout="soon")["state"] == "unknown"
    assert up_state("status.example", base=base, nonsense=1) == "unknown"


def test_base_without_a_scheme_is_unknown(monkeypatch):
    r = is_up("status.example", base="127.0.0.1:9")
    assert r == {"host": "status.example", "state": "unknown", "error": "ValueError"}
    assert is_up("status.example", base="file:///etc")["state"] == "unknown"
    # NED_API without a scheme: no exception, and the next station still answers
    monkeypatch.setenv("NED_API", "127.0.0.1:9")
    monkeypatch.setitem(REGIONS, "eu", "127.0.0.1:9")
    assert is_up("status.example") == {"host": "status.example", "state": "unknown", "error": "ValueError"}
    monkeypatch.setitem(REGIONS, "eu", _serve())
    assert up_state("status.example") == "degraded"


@pytest.mark.parametrize("host,err", [("list.example", "bad reply"), ("null.example", "bad reply"), ("string.example", "bad reply"), ("garbage.example", "JSONDecodeError")])
def test_reply_that_is_not_an_object_is_unknown(host, err):
    r = is_up(host, base=_serve())
    assert r == {"host": host, "state": "unknown", "error": err}
    assert up_state(host, base=_serve()) == "unknown"
