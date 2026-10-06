# Docker and Kubernetes

Know when your batch container silently stops.

```dockerfile
RUN pip install --no-cache-dir ned-watch
ENTRYPOINT ["ned-run", "--name", "nightly-report", "--max", "30m", "--every", "1d", "--"]
CMD ["/app/job.sh"]
```

Run it with `NED_AGENT_KEY` and `NED_CALLBACK_URL` in the environment. Each run starts an overrun run, runs your
command, finishes the run, and checks in to the deadman if the command exited 0. The container exits with your
command's exit code.

## No state file? No problem

Containers start with an empty filesystem, so the client can't remember which watch it registered. It doesn't need to:
with `NED_AGENT_KEY` set, registering the same name and settings returns the same watch every time. The deadman is
armed once, at its first registration (`condition.arm`), so later runs never "re-arm" it (which would hide a job that
always fails). A non-zero exit is reported as a failed run (`exit code N`), so Ned fires at once.

Without `NED_AGENT_KEY`, every container would create a new agent. Run `uvx ned-watch setup` once on your machine, and
copy the key from `~/.config/ned-watch/state.json` into your secret store.

## Kubernetes CronJob

```yaml
apiVersion: v1
kind: Secret
metadata: { name: ned-watch }
type: Opaque
stringData:
  NED_AGENT_KEY: "nw_..."
  NED_CALLBACK_URL: "https://your-agent.example/hooks/ned"
---
apiVersion: batch/v1
kind: CronJob
metadata: { name: nightly-report }
spec:
  schedule: "0 3 * * *"
  concurrencyPolicy: Forbid
  jobTemplate:
    spec:
      backoffLimit: 0
      template:
        spec:
          restartPolicy: Never
          containers:
            - name: report
              image: registry.example.com/nightly-report:latest
              command: ["ned-run", "--ref", "k8s", "--name", "nightly-report", "--max", "30m", "--every", "1d", "--"]
              args: ["/app/job.sh"]
              envFrom: [{ secretRef: { name: ned-watch } }]
```

The deadman catches what Kubernetes won't tell you on its own: the CronJob was suspended, the schedule stopped firing,
the image can't be pulled, or every run fails. The overrun catches a run that hangs (set it below
`activeDeadlineSeconds` if you use that, so Ned tells you before Kubernetes kills the pod).

## Smallest image: curl only

```dockerfile
FROM alpine:3.20
RUN apk add --no-cache curl
COPY ned.sh /usr/local/bin/ned.sh
ENTRYPOINT ["/usr/local/bin/ned.sh", "run", "--"]
CMD ["/app/job.sh"]
```

Pass `NED_WATCH_ID`, `NED_SIGNING_SECRET` (deadman) and `NED_OVERRUN_ID`, `NED_OVERRUN_SECRET` (overrun) as env vars,
for example `docker run --env-file backup.env`. `ned.sh setup` writes that file. See [cron](cron.md#nedsh-reference).

Files: `examples/docker-k8s/` (`Dockerfile`, `Dockerfile.curl`, `cronjob.yaml`).
