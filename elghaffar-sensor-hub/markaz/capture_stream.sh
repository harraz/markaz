#!/usr/bin/env bash
set -euo pipefail

ffmpeg_pid=""

cleanup() {
  # Stop only the ffmpeg process started by this script. Do not use "kill 0",
  # because that can signal unrelated processes in the same process group.
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

CURL_TIMEOUT=1  # Timeout for optional camera control commands

# Control command to set frame size with timeout
curl -s --max-time "$CURL_TIMEOUT" "http://$CAM_IP/control?var=framesize&val=8" >/dev/null 2>&1 || true

# Control command to set quality with timeout
curl -s --max-time "$CURL_TIMEOUT" "http://$CAM_IP/control?var=quality&val=5" >/dev/null 2>&1 || true

set +e
# Run ffmpeg as a tracked child so cleanup can stop this exact process if
# Markaz terminates the script after its outer safety timeout.
ffmpeg -y -loglevel error \
  -i "http://${CAM_IP}:81/stream" \
  -t "$DUR" \
  -c:v copy "$OUT" &
ffmpeg_pid=$!
wait "$ffmpeg_pid"
status=$?
ffmpeg_pid=""
set -e

# Only report success when ffmpeg exited cleanly and produced a non-empty file.
# Markaz has a fallback for the case where ffmpeg times out but the AVI exists.
if [[ $status -eq 0 && -s "$OUT" ]]; then
  echo "Saved: $OUT"
  exit 0
else
  echo "ffmpeg command failed with status $status; output file missing or empty: $OUT" >&2
  exit $status
fi
