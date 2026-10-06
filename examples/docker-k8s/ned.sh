#!/bin/sh
# ned.sh: Ned Watch from any shell, with only curl. For cron, systemd timers, containers.
#
#   ned.sh [-e ENV_FILE] <command>     -e loads NED_* variables from a file written by setup (VAR=value lines)
#   ned.sh setup NAME EVERY_SECONDS CALLBACK_URL [MAX_SECONDS]
#                               register a deadman (and an overrun if MAX_SECONDS) and write their ids and secrets to
#                               $NED_ENV_DIR/NAME.env (default ~/.config/ned-watch, mode 600). Prints the path only.
#   ned.sh checkin              POST /v1/checkin/$NED_WATCH_ID       (Bearer $NED_SIGNING_SECRET)
#   ned.sh start | finish       overrun start/finish on $NED_OVERRUN_ID (Bearer $NED_OVERRUN_SECRET), run id $NED_RUN_ID
#   ned.sh run -- CMD [ARGS]    start, run CMD, finish; check in on exit 0 if NED_WATCH_ID is set. Exits with CMD's code.
#                               A non-zero exit finishes the run as failed ("exit code N"): Ned fires at once
#                               (NED_ON_ERROR=leave_open to leave it open instead).
#
# Env: NED_API (default https://api.ned.watch), NED_REF (default cron), NED_STRICT=1 to exit non-zero when Ned can't be
# reached (default: warn on stderr and carry on, so a hiccup at Ned never fails your job).
# Secrets go only in an Authorization header; they're never echoed.
set -u
if [ "${1:-}" = "-e" ]; then               # load the env file first: it may set NED_API
  [ -r "${2:-}" ] || { echo "ned.sh: can't read env file ${2:-}" >&2; exit 2; }
  set -a; . "$2"; set +a; shift 2
fi
API="${NED_API:-https://api.ned.watch}"; API="${API%/}"
REF="${NED_REF:-cron}"
UA="ned-watch-sh/0.1"

warn() { echo "ned.sh: $*" >&2; }
soft() { warn "$*"; [ "${NED_STRICT:-0}" = "1" ] && exit 1; return 0; }

post() {  # post URL SECRET [JSON]
  _url=$1; _sec=$2; _body=${3:-}
  if [ -n "$_body" ]; then
    curl -sS -o /dev/null -w '%{http_code}' -m 20 --retry 3 --retry-connrefused --retry-delay 2 -X POST "$_url" \
      -H "Authorization: Bearer $_sec" -H "X-Ned-Ref: $REF" -H "User-Agent: $UA" -H 'Content-Type: application/json' -d "$_body"
  else
    curl -sS -o /dev/null -w '%{http_code}' -m 20 --retry 3 --retry-connrefused --retry-delay 2 -X POST "$_url" \
      -H "Authorization: Bearer $_sec" -H "X-Ned-Ref: $REF" -H "User-Agent: $UA"
  fi
}

checkin() {
  [ -n "${NED_WATCH_ID:-}" ] && [ -n "${NED_SIGNING_SECRET:-}" ] || { soft "NED_WATCH_ID / NED_SIGNING_SECRET not set"; return 0; }
  code=$(post "$API/v1/checkin/$NED_WATCH_ID" "$NED_SIGNING_SECRET") || code=000
  [ "$code" = 200 ] || soft "check-in for $NED_WATCH_ID answered HTTP $code"
}

runcall() {  # runcall start|finish [ERROR]   (an ERROR finishes the run as failed: Ned fires at once)
  [ -n "${NED_OVERRUN_ID:-}" ] && [ -n "${NED_OVERRUN_SECRET:-}" ] || { soft "NED_OVERRUN_ID / NED_OVERRUN_SECRET not set"; return 1; }
  _extra=""; [ -n "${2:-}" ] && _extra=",\"status\":\"failed\",\"error\":\"$2\""
  code=$(post "$API/v1/watches/$NED_OVERRUN_ID/$1" "$NED_OVERRUN_SECRET" "{\"run_id\":\"$NED_RUN_ID\"$_extra}") || code=000
  [ "$code" = 200 ] || { soft "$1 for $NED_OVERRUN_ID answered HTTP $code"; return 1; }
}

field() {  # field NAME < json   (flat string fields only; enough for watch_id / signing_secret / agent_key)
  sed -n "s/.*\"$1\":\"\([^\"]*\)\".*/\1/p"
}

register() {  # register JSON -> response body on stdout
  _auth=""
  [ -n "${NED_AGENT_KEY:-}" ] && _auth="Authorization: Bearer $NED_AGENT_KEY"
  curl -sS -m 90 -X POST "$API/v1/watches" -H 'Content-Type: application/json' -H "X-Ned-Ref: $REF" -H "User-Agent: $UA" \
    ${_auth:+-H "$_auth"} -d "$1"
}

setup() {
  name=$1; every=$2; cb=$3; max=${4:-}
  dir="${NED_ENV_DIR:-$HOME/.config/ned-watch}"; mkdir -p "$dir"; chmod 700 "$dir"
  envf="$dir/$name.env"; umask 077
  [ -f "$envf" ] && . "$envf"
  # condition.arm (v1.9) starts the clock now, so a job that never runs still fires; older servers may refuse it
  resp=$(register "{\"type\":\"deadman\",\"interval_s\":$every,\"callback_url\":\"$cb\",\"condition\":{\"label\":\"$name\",\"arm\":true},\"meta\":{\"ref\":\"$REF\"}}")
  armed=1
  if [ -z "$(printf %s "$resp" | field watch_id)" ] && printf %s "$resp" | grep -q arm; then
    armed=0
    resp=$(register "{\"type\":\"deadman\",\"interval_s\":$every,\"callback_url\":\"$cb\",\"condition\":{\"label\":\"$name\"},\"meta\":{\"ref\":\"$REF\"}}")
  fi
  wid=$(printf %s "$resp" | field watch_id); sec=$(printf %s "$resp" | field signing_secret)
  key=$(printf %s "$resp" | field agent_key); [ -n "$key" ] && NED_AGENT_KEY=$key
  [ -n "$wid" ] || { warn "registration failed: $(printf %s "$resp" | head -c 300)"; exit 1; }
  { echo "NED_API=$API"; echo "NED_AGENT_KEY=${NED_AGENT_KEY:-}"; echo "NED_WATCH_ID=$wid"; echo "NED_SIGNING_SECRET=$sec"; } > "$envf.tmp"
  if [ -n "$max" ]; then
    resp=$(register "{\"type\":\"overrun\",\"max_runtime_s\":$max,\"callback_url\":\"$cb\",\"condition\":{\"label\":\"$name\"}}")
    oid=$(printf %s "$resp" | field watch_id); osec=$(printf %s "$resp" | field signing_secret)
    [ -n "$oid" ] || { warn "overrun registration failed: $(printf %s "$resp" | head -c 300)"; rm -f "$envf.tmp"; exit 1; }
    { echo "NED_OVERRUN_ID=$oid"; echo "NED_OVERRUN_SECRET=$osec"; } >> "$envf.tmp"
  fi
  mv "$envf.tmp" "$envf"
  [ $armed = 1 ] || NED_WATCH_ID=$wid NED_SIGNING_SECRET=$sec checkin    # no arm: the clock starts at the first check-in
  echo "$envf"
}

cmd=${1:-}; [ $# -gt 0 ] && shift
case "$cmd" in
  setup)   [ $# -ge 3 ] || { warn "usage: ned.sh setup NAME EVERY_SECONDS CALLBACK_URL [MAX_SECONDS]"; exit 2; }; setup "$@" ;;
  checkin) checkin ;;
  start|finish) NED_RUN_ID="${NED_RUN_ID:-sh-$(date +%s)-$$}"; runcall "$cmd" || true ;;
  run)
    [ "${1:-}" = "--" ] && shift
    [ $# -gt 0 ] || { warn "usage: ned.sh run -- CMD [ARGS]"; exit 2; }
    NED_RUN_ID="${NED_RUN_ID:-sh-$(date +%s)-$$}"; started=0
    if [ -n "${NED_OVERRUN_ID:-}" ]; then runcall start && started=1; fi
    "$@"; rc=$?
    if [ $rc -eq 0 ]; then
      [ $started = 1 ] && { runcall finish || true; }
      [ -n "${NED_WATCH_ID:-}" ] && checkin
    elif [ $started = 1 ] && [ "${NED_ON_ERROR:-report}" != leave_open ]; then
      runcall finish "exit code $rc" || true    # reported as failed: Ned fires at once (only the exit code is sent)
    fi
    exit $rc ;;
  *) sed -n '2,19p' "$0"; exit 2 ;;
esac
