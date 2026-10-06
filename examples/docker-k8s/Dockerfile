# A batch job image whose every run is watched by Ned: ned-run starts an overrun run, runs your command, finishes the
# run, and checks in to a deadman when the command exits 0. The exit code is your command's.
#   docker build -t nightly-report .
#   docker run --rm -e NED_AGENT_KEY -e NED_CALLBACK_URL nightly-report
FROM python:3.12-slim
RUN pip install --no-cache-dir ned-watch
COPY job.sh /app/job.sh
# No state file in a container: with NED_AGENT_KEY set, Ned's idempotent registration returns the same watches each run.
ENV NED_REF=docker
ENTRYPOINT ["ned-run", "--name", "nightly-report", "--max", "30m", "--every", "1d", "--"]
CMD ["/app/job.sh"]
