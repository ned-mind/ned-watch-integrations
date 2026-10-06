"""Start the local Ned Watch (testserver/run.py) in a subprocess for a test session.

    from harness import local_ned
    with local_ned() as base: ...            # base = "http://127.0.0.1:<port>"

Also: hooks(base), tick(base), age(base, wid, s), entry(base, wid). Stdlib only, so every venv can use it.
The server runs on the root .venv (it needs FastAPI); set NED_TEST_SERVER_PYTHON to override, or NED_TEST_BASE to reuse
a server that is already running.
"""
import contextlib, json, os, subprocess, sys, time, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SERVER_PY = os.environ.get("NED_TEST_SERVER_PYTHON", os.path.join(ROOT, ".venv", "bin", "python"))


@contextlib.contextmanager
def local_ned():
    if os.environ.get("NED_TEST_BASE"):
        yield os.environ["NED_TEST_BASE"].rstrip("/")
        return
    env = {k: v for k, v in os.environ.items() if not k.lower().endswith("_proxy")}
    p = subprocess.Popen([SERVER_PY, os.path.join(HERE, "run.py")], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env, text=True)
    base = None
    t0 = time.time()
    while time.time() - t0 < 30:
        line = p.stdout.readline()
        if not line:
            if p.poll() is not None:
                break
            continue
        if line.startswith("READY "):
            base = line.split()[1]
            break
    if not base:
        p.kill()
        raise RuntimeError("local Ned Watch didn't start")
    import threading
    threading.Thread(target=lambda: [None for _ in p.stdout], daemon=True).start()   # drain
    try:
        yield base
    finally:
        p.terminate()
        try:
            p.wait(5)
        except subprocess.TimeoutExpired:
            p.kill()


def _req(method, url, data=None):
    r = urllib.request.Request(url, method=method, data=json.dumps(data).encode() if data is not None else None,
                               headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(r, timeout=30) as resp:
        return json.loads(resp.read() or b"null")


def hooks(base):
    return _req("GET", f"{base}/_test/hooks")


def tick(base):
    return _req("POST", f"{base}/_test/tick")


def age(base, wid, s=3600):
    return _req("POST", f"{base}/_test/age/{wid}?s={s}")


def entry(base, wid):
    return _req("GET", f"{base}/_test/entry/{wid}")["entry"]


def wait_for(pred, timeout=10.0, every=0.1):
    t0 = time.time()
    while time.time() - t0 < timeout:
        v = pred()
        if v:
            return v
        time.sleep(every)
    return None


def events(base, wid):
    return [h["body"]["event"] for h in hooks(base) if h["body"].get("watch_id") == wid]



@contextlib.contextmanager
def local_mcp(api_base, python=None):
    """The remote MCP (testserver/mcp_remote) in front of a local Ned Watch. Yields its /mcp URL."""
    py = python or os.environ.get("NED_TEST_MCP_PYTHON") or os.path.join(ROOT, ".venv-mcp", "bin", "python")   # production pins mcp<2
    env = {k: v for k, v in os.environ.items() if not k.lower().endswith("_proxy")}
    p = subprocess.Popen([py, os.path.join(HERE, "mcp_remote", "run.py"), "--api", api_base], stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, env=env, text=True)
    url = None
    t0 = time.time()
    lines = []
    while time.time() - t0 < 30:
        line = p.stdout.readline()
        if not line:
            if p.poll() is not None:
                break
            continue
        lines.append(line)
        if line.startswith("READY "):
            url = line.split()[1]
            break
    if not url:
        p.kill()
        raise RuntimeError("local MCP didn't start: " + "".join(lines[-20:]))
    import threading
    threading.Thread(target=lambda: [None for _ in p.stdout], daemon=True).start()
    try:
        yield url
    finally:
        p.terminate()
        try:
            p.wait(5)
        except subprocess.TimeoutExpired:
            p.kill()


if __name__ == "__main__":
    with local_ned() as b:
        print(b)
        print(json.dumps(_req("GET", f"{b}/health?shallow=1")))
