"""is_up / up_state: a local stub answers like /v1/up/{host}; network failure is state unknown, never an exception."""
import http.server, json, threading
from nedwatch import is_up, up_state


class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        host = self.path.split("/v1/up/", 1)[1]
        body = json.dumps({"host": host, "state": "degraded" if host == "status.example" else "unknown", "watches": [], "ask_again_s": 300}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
    def log_message(self, *a): pass


def _serve():
    srv = http.server.HTTPServer(("127.0.0.1", 0), H); threading.Thread(target=srv.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{srv.server_address[1]}"


def test_is_up_by_host_and_url():
    base = _serve()
    assert is_up("status.example", base=base)["state"] == "degraded"
    assert up_state("https://status.example/api/v2/status.json?x=1", base=base) == "degraded"
    assert up_state("nobody.example", base=base) == "unknown"


def test_network_failure_is_unknown_not_an_exception():
    r = is_up("api.openai.com", base="http://127.0.0.1:9", timeout=1)
    assert r["state"] == "unknown" and r["error"]
    assert is_up("", base="http://127.0.0.1:9")["state"] == "unknown"
