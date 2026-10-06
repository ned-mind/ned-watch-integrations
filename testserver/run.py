#!/usr/bin/env python3
"""A local Ned Watch for the integration tests: the real API (a snapshot of nedwatch/app, copied unmodified into
testserver/app) on 127.0.0.1, SQLite, with the scheduler ticking in-process every half second.

    .venv/bin/python testserver/run.py [--port 0] [--db PATH]
    prints "READY http://127.0.0.1:<port>" when it answers /health.

Test-only extras live under /_test/ (they are added here, never in the app):
    POST /_test/hook            a callback sink (records headers + body)
    GET  /_test/hooks           what the sink received
    POST /_test/age/{wid}?s=N   move a deadman's last check-in N seconds into the past (simulate silence)
    POST /_test/tick            run one scheduler pass now
    GET  /_test/entry/{wid}     the entry attribution (X-Ned-Ref) of the agent that owns the watch
No public network: NED_ALLOW_PRIVATE=1 (honoured only with SQLite) lets callbacks reach 127.0.0.1.
"""
import argparse, json, os, socket, sys, tempfile, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--db", default=None)
    ap.add_argument("--tick", type=float, default=0.5)
    a = ap.parse_args()
    dbp = a.db or os.path.join(tempfile.mkdtemp(prefix="nedtest-"), "ned.db")
    port = a.port
    if not port:
        s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    base = f"http://127.0.0.1:{port}"
    os.environ.update(DATABASE_URL=f"sqlite:///{dbp}", NED_ALLOW_PRIVATE="1", INTERNAL_TOKEN="local-test-only",
                      PUBLIC_BASE=base, NODE_NAME="watch-local", SELF_API=base)
    for k in ("PEER_URL", "CDP_API_KEY_ID", "CDP_API_KEY_SECRET"):
        os.environ.pop(k, None)
    sys.path.insert(0, HERE)

    from sqlalchemy.dialects import postgresql
    from sqlalchemy.ext.compiler import compiles

    @compiles(postgresql.JSONB, "sqlite")
    def _jsonb_sqlite(type_, compiler, **kw):
        return "JSON"

    from datetime import timedelta
    from fastapi import Request
    from app.main import app, LIMITER
    from app import callbacks, db, scheduler

    callbacks.RETRIES = (0,)                 # one attempt per delivery; tests don't wait 35 s
    received: list[dict] = []
    lock = threading.Lock()

    @app.post("/_test/hook", include_in_schema=False)
    async def _hook(request: Request):
        raw = await request.body()
        with lock:
            received.append({"headers": {k.lower(): v for k, v in request.headers.items()}, "raw": raw.decode(), "body": json.loads(raw or b"{}")})
        return {"ok": True}

    @app.get("/_test/hooks", include_in_schema=False)
    def _hooks():
        with lock:
            return list(received)

    @app.post("/_test/age/{wid}", include_in_schema=False)
    def _age(wid: str, s: int = 3600):
        with db.SessionLocal() as ss:
            w = ss.get(db.Watch, wid)
            if w.last_checkin:
                w.last_checkin = db.aware(w.last_checkin) - timedelta(seconds=s)
            w.next_run = db.now()
            ss.commit()
        return {"ok": True}

    @app.post("/_test/tick", include_in_schema=False)
    def _tick():
        return {"checked": scheduler.tick()}

    @app.get("/_test/entry/{wid}", include_in_schema=False)
    def _entry(wid: str):
        with db.SessionLocal() as ss:
            w = ss.get(db.Watch, wid)
            ag = ss.get(db.Agent, w.agent_id) if w else None
            return {"agent_id": ag.id if ag else None, "entry": (ag.meta or {}).get("entry") if ag else None}

    LIMITER.check = lambda *a, **k: 0        # tests register many watches from one IP; the limits are tested upstream
    LIMITER.peek = lambda *a, **k: False

    def loop():
        while True:
            time.sleep(a.tick)
            try:
                scheduler.tick(block_s=2)
            except Exception as e:   # keep ticking; the API tests surface real problems
                print("tick error", type(e).__name__, e, file=sys.stderr, flush=True)

    import uvicorn
    db.init_db()
    threading.Thread(target=loop, daemon=True).start()

    def ready():
        import urllib.request
        for _ in range(200):
            try:
                urllib.request.urlopen(base + "/health?shallow=1", timeout=1).read()
                print(f"READY {base}", flush=True)
                return
            except Exception:
                time.sleep(0.05)
    threading.Thread(target=ready, daemon=True).start()
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
