# cron, systemd and ned.sh

- `crontab.example`: three copy-paste styles (curl after `&&`, `ned-run`, `ned.sh`)
- `backup.service` + `backup.timer`: check in from `ExecStartPost=` (runs only after a successful `ExecStart=`)
- `backup-ned-run.service`: the same job wrapped by `ned-run`
- `ned.sh`: POSIX sh + curl only: `setup`, `checkin`, `start`, `finish`, `run -- CMD`

Docs: [../../docs/cron.md](../../docs/cron.md).

Tests execute the crontab lines and unit-file commands as written (only the API URL, ids, secrets and job path are
swapped for local ones) against a local Ned Watch:

```bash
../../.venv/bin/python -m pytest -q
```

Not run under a real cron daemon or systemd (macOS here); `systemd-analyze verify` was not available.
