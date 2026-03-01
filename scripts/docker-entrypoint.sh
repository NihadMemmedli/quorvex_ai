#!/bin/bash
set -e

# Docker entrypoint script that fixes volume permissions at container startup
# This runs as root to fix permissions on mounted volumes, then drops to 'agent' user

# Fix permissions on mounted volumes (runs as root)
# These directories may be Docker named volumes created with root ownership
for dir in /app/runs /app/logs /app/data /app/test-results /app/specs /app/prds /app/tests; do
    if [ -d "$dir" ]; then
        chown -R agent:agent "$dir" 2>/dev/null || true
    fi
done

# Ensure explorations subdirectory exists with correct permissions
mkdir -p /app/runs/explorations
chown -R agent:agent /app/runs/explorations

# Also fix supervisor log directory permissions
if [ -d "/var/log/supervisor" ]; then
    chown -R agent:agent /var/log/supervisor 2>/dev/null || true
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
