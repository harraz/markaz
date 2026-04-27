#!/usr/bin/env bash
set -euo pipefail

ffmpeg_pid=""
timeout_pid=""

cleanup() {
  # Only stop the child processes started by this script. Do not use "kill 0",
  # because that can signal unrelated processes in the same process group.
  if [[ -n "$timeout_pid" ]] && kill -0 "$timeout_pid" 2>/dev/null; then
    kill "$timeout_pid" 2>/dev/null || true
  fi

  if [[ -n "$ffmpeg_pid" ]] && kill -0 "$ffmpeg_pid" 2>/dev/null; then
    kill "$ffmpeg_pid" 2>/dev/null || true
  fi
}

on_signal() {
  cleanup
  exit 130
}

trap cleanup EXIT
trap on_signal INT TERM

if [ $# -lt 1 ]; then
  echo "Usage: $0 <CAM_IP> [DURATION_SEC]" >&2
  exit 1
fi

CAM_IP="$1"
DUR="${2:-10}"
OUTDIR="${OUTDIR:-$HOME/Videos}"

mkdir -p "$OUTDIR"
TS="$(date +%Y%m%d_%H%M%S)"
# sanitize CAM_IP for filename (replace non alphanum with _)
SAFE_CAM_IP="$(echo "$CAM_IP" | sed -E 's/[^a-zA-Z0-9._-]/_/g')"
OUT="$OUTDIR/esp32cam_${SAFE_CAM_IP}_${TS}.avi"

CURL_TIMEOUT=5  # Timeout for curl commands
FFMPEG_TIMEOUT="$((DUR + 1))"  # Timeout for ffmpeg command

# Control command to set frame size with timeout
curl -s --max-time "$CURL_TIMEOUT" "http://$CAM_IP/control?var=framesize&val=8" >/dev/null 2>&1 || true

# Control command to set quality with timeout
curl -s --max-time "$CURL_TIMEOUT" "http://$CAM_IP/control?var=quality&val=5" >/dev/null 2>&1 || true

ffmpeg -y -loglevel error \
  -i "http://${CAM_IP}:81/stream" \
  -t "$DUR" \
  -c:v copy "$OUT" &

ffmpeg_pid=$!

# Start a small timeout helper. If ffmpeg runs longer than expected, ask only
# that ffmpeg process to stop cleanly.
( sleep "$FFMPEG_TIMEOUT" && kill "$ffmpeg_pid" 2>/dev/null ) &
timeout_pid=$!

# ffmpeg can return a non-zero status if the stream drops or the timeout helper
# stops it. Temporarily disable "exit on error" so we can inspect that status
# and print a useful message below.
set +e
wait "$ffmpeg_pid"
status=$?
set -e

# ffmpeg finished before the timeout helper fired, so stop the helper too.
if kill -0 "$timeout_pid" 2>/dev/null; then
  kill "$timeout_pid" 2>/dev/null || true
  wait "$timeout_pid" 2>/dev/null || true
fi

if [[ $status -eq 0 ]]; then
  echo "Saved: $OUT"
  exit 0
else
  echo "ffmpeg command failed with status $status" >&2
  exit $status
fi
