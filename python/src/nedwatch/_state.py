"""Where the client remembers its agent key and the watches it registered, so a cron job that runs every hour
reuses the same watch instead of making a new one each time.

Default file: $NED_STATE, else ~/.config/ned-watch/state.json (mode 0600). Shared with the Node client.
Layout: {"<api base>": {"agent_key": "...", "watches": {"deadman:<name>": {"id", "secret", "fp"}}}}
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any, Dict, Optional, Union

StateArg = Union[None, bool, str, "os.PathLike[str]"]


def default_path() -> Path:
    env = os.environ.get("NED_STATE")
    if env:
        return Path(env).expanduser()
    root = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return Path(root) / "ned-watch" / "state.json"


class State:
    def __init__(self, where: StateArg = None):
        self._lock = threading.Lock()
        self._mem: Dict[str, Any] = {}
        if where is False:
            self.path: Optional[Path] = None
        elif where is None or where is True:
            self.path = default_path()
        else:
            self.path = Path(where).expanduser()

    def _load(self) -> Dict[str, Any]:
        if self.path is None:
            return self._mem
        try:
            with open(self.path, encoding="utf-8") as f:
                d = json.load(f)
            return d if isinstance(d, dict) else {}
        except (FileNotFoundError, ValueError):
            return {}

    def _save(self, d: Dict[str, Any]) -> None:
        if self.path is None:
            self._mem = d
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.path.parent, 0o700)
        except OSError:
            pass
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), prefix=".state-")
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(d, f, indent=1, sort_keys=True)
            os.replace(tmp, self.path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def agent_key(self, base: str) -> Optional[str]:
        with self._lock:
            return (self._load().get(base) or {}).get("agent_key")

    def set_agent_key(self, base: str, key: str) -> None:
        with self._lock:
            d = self._load()
            d.setdefault(base, {})["agent_key"] = key
            self._save(d)

    def watch(self, base: str, slot: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            return ((self._load().get(base) or {}).get("watches") or {}).get(slot)

    def by_id(self, base: str, watch_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            for rec in ((self._load().get(base) or {}).get("watches") or {}).values():
                if rec.get("id") == watch_id:
                    return rec
        return None

    def set_watch(self, base: str, slot: str, rec: Optional[Dict[str, Any]]) -> None:
        with self._lock:
            d = self._load()
            ws = d.setdefault(base, {}).setdefault("watches", {})
            if rec is None:
                ws.pop(slot, None)
            else:
                ws[slot] = rec
            self._save(d)

    def watches(self, base: str) -> Dict[str, Dict[str, Any]]:
        with self._lock:
            return dict((self._load().get(base) or {}).get("watches") or {})
