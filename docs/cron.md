# cron and systemd timers

Know when your cron job silently stops.

```cron
0 3 * * * /usr/local/bin/backup.sh && curl -fsS -m 20 --retry 3 -X POST https://api.ned.watch/v1/checkin/w_0123456789ab -H "Authorization: Bearer $(cat $HOME/.config/ned-watch/backup.secret)" -H "X-Ned-Ref: cron" >/dev/null
```

The `&&` means the check-in runs only when the job exits 0. If the job fails, hangs, or cron stops running it, the
check-in doesn't arrive and Ned POSTs a signed `fire` to your callback once the interval has passed.

## 1. Make the watch (once)

With curl:

```bash
curl -s -X POST https://api.ned.watch/v1/watches -H 'Content-Type: application/json' -H 'X-Ned-Ref: cron' \
  -d '{"type":"deadman","interval_s":90000,"callback_url":"https://you.example/hooks/ned","condition":{"label":"backup","arm":true}}'
```

Keep `watch_id`, `signing_secret` and `agent_key` from the answer. Put the secret in a file only you can read:
`umask 077; echo whs_... > ~/.config/ned-watch/backup.secret`. `"arm": true` starts the clock now, so even a job that never
runs is noticed. A daily job with `interval_s` of 25 hours gives it an hour's slack.

Or with the CLI, which does all of that and keeps the secrets in its state file:

```bash
uvx ned-watch setup --callback https://you.example/hooks/ned --name backup --every 25h
```

Or with `ned.sh`, a curl-only script (in `examples/cron/`):

```bash
ned.sh setup backup 90000 https://you.example/hooks/ned 1800     # deadman 25 h, overrun 30 min; writes ~/.config/ned-watch/backup.env
```

## 2. Pick a crontab style

```cron
# curl only: check in after success (above)
0 3 * * * /usr/local/bin/backup.sh && curl -fsS -m 20 --retry 3 -X POST https://api.ned.watch/v1/checkin/w_0123456789ab -H "Authorization: Bearer $(cat $HOME/.config/ned-watch/backup.secret)" -H "X-Ned-Ref: cron" >/dev/null

# ned-run (pip install ned-watch, or npm i -g @nedwatch/ned-watch): overrun around the job, deadman on success
0 3 * * * ned-run --name backup --max 30m --every 25h -- /usr/local/bin/backup.sh

# ned.sh (curl only), overrun + deadman from the env file setup wrote
0 3 * * * /usr/local/bin/ned.sh -e $HOME/.config/ned-watch/backup.env run -- /usr/local/bin/backup.sh
```

`ned-run` starts an overrun run, runs your command, finishes the run and checks in to the deadman if the command
exited 0. It exits with your command's exit code and passes signals through. If Ned can't be reached it prints a
warning and runs your command anyway. A non-zero exit finishes the run as failed with `exit code N` (never the command
line), so Ned fires at once, and skips the deadman check-in.

Cron runs with a small `PATH` and no profile: use full paths, and set `NED_CALLBACK_URL` / `NED_AGENT_KEY` at the top
of the crontab if `ned-run` needs them (it reads its state file from `~/.config/ned-watch/` otherwise). Avoid `%` in
crontab lines; cron treats it as a newline.

## systemd timers

`ExecStartPost=` runs only after `ExecStart=` succeeded, which is exactly when to check in:

```ini
# /etc/systemd/system/backup.service
[Service]
Type=oneshot
EnvironmentFile=/etc/ned-watch/backup.env
ExecStart=/usr/local/bin/backup.sh
ExecStartPost=-/usr/bin/curl -fsS -m 20 --retry 3 -X POST https://api.ned.watch/v1/checkin/${NED_WATCH_ID} -H "Authorization: Bearer ${NED_SIGNING_SECRET}" -H "X-Ned-Ref: systemd"
```

```ini
# /etc/systemd/system/backup.timer      (systemctl enable --now backup.timer)
[Timer]
OnCalendar=*-*-* 03:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

The leading `-` keeps a failed check-in from marking the job failed. `/etc/ned-watch/backup.env` (mode 600) holds
`NED_WATCH_ID=...` and `NED_SIGNING_SECRET=...`; `ned.sh setup` writes a file in that format.

Or wrap the job:

```ini
[Service]
Type=oneshot
EnvironmentFile=/etc/ned-watch/ned.env
Environment=NED_STATE=/var/lib/ned-watch/state.json
ExecStart=/usr/local/bin/ned-run --ref systemd --name backup --max 30m --every 1d -- /usr/local/bin/backup.sh
```

## ned.sh reference

```
ned.sh [-e ENV_FILE] setup NAME EVERY_SECONDS CALLBACK_URL [MAX_SECONDS]
ned.sh [-e ENV_FILE] checkin                 # NED_WATCH_ID, NED_SIGNING_SECRET
ned.sh [-e ENV_FILE] start | finish          # NED_OVERRUN_ID, NED_OVERRUN_SECRET, NED_RUN_ID
ned.sh [-e ENV_FILE] run -- CMD [ARGS...]
```

POSIX `sh` and `curl` only. Secrets go only into an `Authorization` header; the script never prints them.
`NED_STRICT=1` makes it exit non-zero when Ned can't be reached (by default it warns and carries on).
