#!/bin/bash
set -e

# Docker entrypoint script that fixes volume permissions at container startup
# This runs as root to fix permissions on mounted volumes, then drops to 'agent' user

AGENT_UID="$(id -u agent)"
AGENT_GID="$(id -g agent)"
AGENT_OWNER="${AGENT_UID}:${AGENT_GID}"

# Fix permissions on mounted volumes (runs as root)
# These directories may be Docker named volumes created with root ownership
for dir in /app/runs /app/logs /app/data /app/test-results /app/specs /app/prds /app/tests; do
    if [ -d "$dir" ]; then
        chown -R "$AGENT_OWNER" "$dir" 2>/dev/null || true
    fi
done

# Ensure explorations subdirectory exists with correct permissions
mkdir -p /app/runs/explorations
chown -R "$AGENT_OWNER" /app/runs/explorations

# Also fix supervisor log directory permissions
if [ -d "/var/log/supervisor" ]; then
    chown -R "$AGENT_OWNER" /var/log/supervisor 2>/dev/null || true
fi

# noVNC treats uncaught errors from browser extensions as fatal page errors.
# Ignore extension-origin errors so MetaMask/other injected scripts cannot block
# the VNC viewer in the user's local browser.
NOVNC_ERROR_HANDLER="/opt/noVNC/app/error-handler.js"
if [ -f "$NOVNC_ERROR_HANDLER" ] && ! grep -q "Browser extensions can inject scripts" "$NOVNC_ERROR_HANDLER"; then
    tmp_file="$(mktemp)"
    awk '
        /function handleError\(event, err\) {/ {
            print;
            print "    // Browser extensions can inject scripts into the noVNC page.";
            print "    // Their failures are unrelated to the VNC session.";
            print "    const filename = event && (event.filename || event.target?.src || \"\");";
            print "    const message = event && event.message ? event.message : \"\";";
            print "    if (filename.startsWith(\"chrome-extension://\") || filename.startsWith(\"moz-extension://\") || message.includes(\"Failed to connect to MetaMask\")) {";
            print "        return false;";
            print "    }";
            next;
        }
        { print }
    ' "$NOVNC_ERROR_HANDLER" > "$tmp_file" && cat "$tmp_file" > "$NOVNC_ERROR_HANDLER"
    rm -f "$tmp_file"
fi

# Drop privileges and execute the command
# Exception: supervisord manages user switching per-program, so we run it as root
if [ "$(id -u)" = "0" ]; then
    if [ "$1" = "/usr/bin/supervisord" ]; then
        # supervisord will handle user switching via program config
        exec "$@"
    else
        # Drop to agent user for all other commands
        exec gosu agent "$@"
    fi
else
    # Already running as non-root (shouldn't happen but handle gracefully)
    exec "$@"
fi
