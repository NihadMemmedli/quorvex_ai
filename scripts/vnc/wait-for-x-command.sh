#!/usr/bin/env bash
set -euo pipefail

display="${DISPLAY:-:99}"
timeout_seconds="${VNC_X_WAIT_TIMEOUT_SECONDS:-30}"
deadline=$((SECONDS + timeout_seconds))

while ! xdpyinfo -display "${display}" >/dev/null 2>&1; do
  if [ "${SECONDS}" -ge "${deadline}" ]; then
    echo "Timed out waiting for X display ${display}." >&2
    exit 1
  fi
  sleep 0.5
done

exec "$@"
