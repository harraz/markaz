#!/usr/bin/env bash
set -euo pipefail

trap "exit" INT TERM ERR
trap "kill 0" EXIT

if [ $# -lt 1 ]; then
  echo "Usage: $0 <CAM_IP> [DURATION_SEC]" >&2
  exit 1
fi

CAM_IP="$1"
DUR="${2:-10}"
OUTDIR="${OUTDIR:-/home/harraz/Videos}"

mkdir -p "$OUTDIR"
TS="$(date +%Y%m%d_%H%M%S)"
OUT="$OUTDIR/esp32cam_${CAM_IP}_${TS}.avi"

CURL_TIMEOUT=5  # Timeout for curl commands
FFMPEG_TIMEOUT="$((DUR + 1))"  # Timeout for ffmpeg command

# Control command to set frame size with timeout
#curl -s --max-time "$CURL_TIMEOUT" "http://$CAM_IP/control?var=framesize&val=7" >/dev/null 2>&1

# Control command to set quality with timeout
#curl -s --max-time "$CURL_TIMEOUT" "http://$CAM_IP/control?var=quality&val=10" >/dev/null 2>&1

ffmpeg -y -loglevel error \
  -i "http://${CAM_IP}:81/stream" \
  -t "$DUR" \
  -c:v copy "$OUT" &

pid=$!
( sleep "$FFMPEG_TIMEOUT" && kill -HUP "$pid" ) 2>/dev/null &
wait "$pid"

if [[ $? -eq 0 ]]; then
  echo "Saved: $OUT"
else
  echo "ffmpeg command timed out" >&2
fi
