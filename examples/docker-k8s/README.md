# Docker and Kubernetes

- `Dockerfile`: `ned-run` as the entrypoint, your job as the command
- `Dockerfile.curl`: alpine + curl + `ned.sh`
- `cronjob.yaml`: Secret + CronJob running the image with `ned-run`
- `schema/`: Kubernetes 1.31 JSON schemas (from yannh/kubernetes-json-schema) used by the tests

Docs: [../../docs/docker-kubernetes.md](../../docs/docker-kubernetes.md).

```bash
../../.venv/bin/python -m pytest -q
```

The tests validate the manifests against the schemas and run each container's entrypoint + command locally against a
local Ned Watch (including two "pods" with no shared state reusing one watch). No image was built and no cluster used:
both would pull from public registries outside the egress proxy.
