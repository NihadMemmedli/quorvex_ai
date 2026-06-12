#!/usr/bin/env bash
set -euo pipefail

display="${DISPLAY:-:99}"
display_number="${display#:}"
lock_file="/tmp/.X${display_number}-lock"
socket_file="/tmp/.X11-unix/X${display_number}"

if xdpyinfo -display "${display}" >/dev/null 2>&1; then
  echo "X display ${display} is already available; keeping supervisor program alive."
  exec sleep infinity
fi

if [ -f "${lock_file}" ]; then
  lock_pid="$(tr -d '[:space:]' < "${lock_file}" || true)"
  if [ -z "${lock_pid}" ] || ! kill -0 "${lock_pid}" >/dev/null 2>&1; then
    echo "Removing stale X lock ${lock_file}."
    rm -f "${lock_file}" "${socket_file}"
  fi
fi

exec /usr/bin/Xvfb "${display}" -screen 0 1920x1080x24
