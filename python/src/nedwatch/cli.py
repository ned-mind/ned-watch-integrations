"""nedwatch: command line for Ned Watch.

    nedwatch setup --callback https://you.example/hooks/ned --name nightly-sync --every 1h
    nedwatch checkin nightly-sync                 # put this at the end of your job (cron, CI, a loop)
    nedwatch run --name backup --max 30m -- ./backup.sh     (same as: ned-run --name backup --max 30m -- ./backup.sh)
    nedwatch doctor                               # key, connectivity, and a real test callback
    nedwatch status [name]

Secrets (agent key, signing secrets) are kept in the state file (~/.config/ned-watch/state.json, mode 0600) and never
printed unless you pass --show-secrets.
"""
from __future__ import annotations

import argparse
import os
import secrets
import signal
import subprocess
import sys
import time
from typing import List, Optional

from . import __version__
from .client import Ned, NedConfigError, NedError


def _ned(a: argparse.Namespace, ref: Optional[str] = None) -> Ned:
    return Ned(base=a.base, region=a.region, callback_url=getattr(a, "callback", None), ref=ref or a.ref or os.environ.get("NED_REF") or "cli",
               state=a.state)


def _common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--base", help="API base URL (default $NED_API or https://api.ned.watch)")
    p.add_argument("--region", choices=["us", "eu"], help="us (default) or eu")
    p.add_argument("--state", help="state file (default $NED_STATE or ~/.config/ned-watch/state.json)")
    p.add_argument("--ref", help="integration tag sent as X-Ned-Ref (default: cli, or cron for ned-run)")


def _ok(msg: str) -> None:
    print(f"  ok    {msg}")


def _bad(msg: str) -> None:
    print(f"  FAIL  {msg}")


def cmd_doctor(a: argparse.Namespace) -> int:
    ned = _ned(a)
    print(f"Ned Watch doctor (nedwatch {__version__})")
    print(f"  api       {ned.base}")
    print(f"  ref       {ned.ref}")
    print(f"  key       {'set' if ned.has_key else 'not set (your first registration creates one)'}")
    print(f"  callback  {ned.callback_url or 'not set (--callback or NED_CALLBACK_URL)'}")
    print(f"  state     {ned.state.path or 'memory only'}")
    fails = 0
    t0 = time.time()
    try:
        h = ned.health()
        _ok(f"reached Ned in {int((time.time() - t0) * 1000)} ms (node {h.get('node')}, db {'up' if h.get('db') else 'DOWN'})")
    except NedError as e:
        _bad(f"can't reach {ned.base}: {e}")
        return 1
    if ned.has_key:
        try:
            b = ned.balance()
            _ok(f"agent key accepted ({b.get('agent_id')}; {b.get('free_used')}/{b.get('free_watches')} free watches used, "
                f"balance {b.get('balance_cents')}c)")
        except NedError as e:
            fails += 1
            _bad(f"agent key rejected: {e}")
    if not ned.callback_url:
        print("  skip  callback test: no callback URL")
    elif not ned.has_key and not a.create:
        print("  skip  callback test: no agent key yet; run again with --create to make your agent and test the callback")
    else:
        # a throwaway deadman: Ned sends a signed test callback on every new registration; cancelled right after
        try:
            res = ned.register("deadman", interval_s=3600, condition={"label": f"doctor-{secrets.token_hex(4)}"})
            tc = res.get("test_callback") or {}
            if tc.get("delivered"):
                _ok(f"test callback delivered to your URL (HTTP {tc.get('status')})")
            else:
                fails += 1
                _bad(f"test callback not delivered: {tc.get('problem') or tc.get('status')}")
            try:
                ned.cancel(res["watch_id"])
            except NedError:
                pass
        except NedError as e:
            fails += 1
            _bad(f"couldn't register the test watch: {e}")
    for slot, rec in sorted(ned.state.watches(ned.base).items()):
        if not ned.has_key:
            break
        try:
            w = ned.get(rec["id"])
            state = "FIRED" if w.get("fired") else w.get("status")
            _ok(f"{slot:32s} {rec['id']}  {state}  last check-in {w.get('last_checkin') or '-'}")
        except NedError as e:
            _bad(f"{slot}: {e}")
    print("all good" if not fails else f"{fails} problem(s)")
    return 1 if fails else 0


def cmd_setup(a: argparse.Namespace) -> int:
    ned = _ned(a)
    try:
        if a.max:
            w = ned.overrun(a.name, a.max).ensure()
            print(f"overrun watch '{w.name}': {w.id} (fires if a run is still open after {a.max})")
            print(f"wrap your job:  ned-run --name {w.name} --max {a.max} -- <command>")
        w2 = ned.deadman(a.name, a.every).ensure()
        w2.checkin()                                     # the clock starts at the first check-in
        print(f"deadman watch '{w2.name}': {w2.id} (fires if no check-in for {a.every}); first check-in done")
        print(f"after each successful run:  nedwatch checkin {w2.name}")
        print(f"saved to {ned.state.path or 'memory'} (agent key and signing secrets; mode 0600)")
        if a.show_secrets:
            print(f"NED_AGENT_KEY={ned._key}")
            print(f"NED_WATCH_ID={w2.id}")
            print(f"NED_SIGNING_SECRET={w2.signing_secret}")
        return 0
    except NedConfigError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except NedError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


def cmd_checkin(a: argparse.Namespace) -> int:
    ned = _ned(a)
    try:
        r = ned.checkin(a.watch, signing_secret=os.environ.get("NED_SIGNING_SECRET") if a.watch.startswith("w_") else None)
        if not a.quiet:
            print(f"checked in: {r.get('watch_id')} (next deadline in {r.get('next_deadline_s')} s)")
        return 0
    except NedError as e:
        print(f"nedwatch: check-in failed: {e}", file=sys.stderr)
        return 0 if a.never_fail else 1


def cmd_status(a: argparse.Namespace) -> int:
    ned = _ned(a)
    recs = ned.state.watches(ned.base)
    if a.name:
        recs = {k: v for k, v in recs.items() if k.split(":", 1)[1] == a.name}
    if not recs:
        print("no watches in the state file")
        return 1
    for slot, rec in sorted(recs.items()):
        try:
            w = ned.get(rec["id"])
            print(f"{slot:32s} {rec['id']}  {'FIRED' if w.get('fired') else w.get('status')}  last check-in {w.get('last_checkin') or '-'}")
        except NedError as e:
            print(f"{slot:32s} {rec['id']}  error: {e}")
    return 0


def cmd_run(a: argparse.Namespace) -> int:
    cmd: List[str] = a.cmd[1:] if a.cmd and a.cmd[0] == "--" else a.cmd
    if not cmd:
        print("usage: ned-run [--name N] [--max 1h] [--every 1d] -- <command> [args...]", file=sys.stderr)
        return 2
    name = a.name or os.environ.get("NED_WATCH_NAME") or os.path.basename(cmd[0]) or "job"
    ned = _ned(a, ref=a.ref or os.environ.get("NED_REF") or "cron")
    run = ned.run(name, a.max, every=a.every, on_error=a.on_error)
    run.__enter__()
    try:
        p = subprocess.Popen(cmd)
    except OSError as e:
        print(f"ned-run: can't start {cmd[0]}: {e}", file=sys.stderr)
        run.__exit__(*_failure(f"could not start the command ({type(e).__name__})"))
        return 127
    def fwd(sig, _frame):
        try:
            p.send_signal(sig)
        except ProcessLookupError:
            pass
    for s in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(s, fwd)
    rc = p.wait()
    if rc == 0:
        run.__exit__(None, None, None)
    else:                     # only the exit status goes to Ned, never the command line (it may hold secrets)
        run.__exit__(*_failure(f"exit code {rc}" if rc > 0 else f"killed by signal {-rc}"))
    return rc if rc >= 0 else 128 - rc


class CommandFailed(Exception):
    pass


def _failure(msg: str) -> tuple:
    e = CommandFailed(msg)
    e.ned_error = msg  # type: ignore[attr-defined]
    return CommandFailed, e, None


def build() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="nedwatch", description="Ned Watch: know when your agent silently stops.")
    ap.add_argument("--version", action="version", version=f"nedwatch {__version__}")
    sub = ap.add_subparsers(dest="cmd_name", required=True)

    d = sub.add_parser("doctor", help="check key, connectivity and a real test callback")
    _common(d); d.add_argument("--callback"); d.add_argument("--create", action="store_true", help="no key yet: create your agent")
    d.set_defaults(fn=cmd_doctor)

    s = sub.add_parser("setup", help="create a deadman (and optionally an overrun) watch and do the first check-in")
    _common(s); s.add_argument("--callback"); s.add_argument("--name", default=None)
    s.add_argument("--every", default="1h"); s.add_argument("--max", default=None, help="also an overrun watch with this limit")
    s.add_argument("--show-secrets", action="store_true", help="print the key and secret as env lines (careful: logs)")
    s.set_defaults(fn=cmd_setup)

    c = sub.add_parser("checkin", help="check in to a deadman (name from setup, or w_... with NED_SIGNING_SECRET)")
    _common(c); c.add_argument("watch"); c.add_argument("-q", "--quiet", action="store_true")
    c.add_argument("--never-fail", action="store_true", help="exit 0 even if Ned can't be reached")
    c.set_defaults(fn=cmd_checkin)

    st = sub.add_parser("status", help="state of the watches in the state file")
    _common(st); st.add_argument("name", nargs="?"); st.set_defaults(fn=cmd_status)

    r = sub.add_parser("run", help="start/finish an overrun watch around a command (ned-run)")
    _add_run_args(r)
    return ap


def _add_run_args(r: argparse.ArgumentParser) -> None:
    _common(r)
    r.add_argument("--name", help="watch name (default: the command's name)")
    r.add_argument("--max", default="1h", help="fire if the command is still running after this (default 1h)")
    r.add_argument("--every", default=None, help="also a deadman: fire if no successful run within this")
    r.add_argument("--callback")
    r.add_argument("--on-error", default="report", choices=["report", "auto", "leave_open", "finish"],
                   help="report (default): finish the run as failed with the exit code; Ned fires at once")
    r.add_argument("cmd", nargs=argparse.REMAINDER)
    r.set_defaults(fn=cmd_run)


def main(argv: Optional[List[str]] = None) -> int:
    a = build().parse_args(argv)
    if a.fn is cmd_setup and not a.name:               # default name: $NED_WATCH_NAME, else this directory's name
        a.name = os.environ.get("NED_WATCH_NAME") or os.path.basename(os.getcwd()) or "agent"
    return a.fn(a)


def ned_run_main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="ned-run", description="Run a command under a Ned Watch overrun (and optional deadman) watch.")
    _add_run_args(ap)
    return cmd_run(ap.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
