#!/bin/bash
# Health Monitor for Playwright Agent
# Schedule: */5 * * * * /opt/playwright-agent/scripts/health-monitor.sh
#
# Checks:
#   1. Backend API health endpoint
#   2. Backup age (alerts if > 48 hours)
#   3. Disk usage (alerts if > 80%)
#
# Logs to: /var/log/playwright-health.log
# Alerts are written to log with [ALERT] prefix for easy grep-based monitoring.

set -euo pipefail

LOG_FILE="${HEALTH_LOG:-/var/log/playwright-health.log}"
API_URL="${API_URL:-http://localhost:8001}"
DISK_THRESHOLD="${DISK_THRESHOLD:-80}"
BACKUP_MAX_AGE_HOURS="${BACKUP_MAX_AGE_HOURS:-48}"
APP_DIR="${APP_DIR:-/opt/playwright-agent}"

timestamp() {
    date '+%Y-%m-%d %H:%M:%S'
}

log() {
    echo "$(timestamp) $1" >> "$LOG_FILE"
}

alert() {
    echo "$(timestamp) [ALERT] $1" >> "$LOG_FILE"
}

# Ensure log file exists and is writable
mkdir -p "$(dirname "$LOG_FILE")" 2>/dev/null || true
touch "$LOG_FILE" 2>/dev/null || {
    # Fall back to app directory if /var/log is not writable
    LOG_FILE="$APP_DIR/logs/health-monitor.log"
    mkdir -p "$(dirname "$LOG_FILE")" 2>/dev/null || true
}

# --- Check 1: Backend API Health ---
http_code=$(curl -sf -o /dev/null -w "%{http_code}" "$API_URL/health" 2>/dev/null || echo "000")

if [ "$http_code" = "200" ]; then
    log "[OK] Backend API healthy (HTTP $http_code)"
else
    alert "Backend API unhealthy (HTTP $http_code) - $API_URL/health"
fi

# --- Check 2: Backup Age ---
backup_response=$(curl -sf "$API_URL/health/backup" 2>/dev/null || echo "")

if [ -n "$backup_response" ]; then
    # Extract backup_age_hours using python (available on most systems)
    backup_age=$(echo "$backup_response" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    val = data.get('backup_age_hours')
    print(val if val is not None else -1)
except:
    print(-1)
" 2>/dev/null || echo "-1")

    if [ "$backup_age" = "-1" ] || [ "$backup_age" = "None" ]; then
        log "[WARN] No backup has run yet"
    elif python3 -c "exit(0 if float('$backup_age') > $BACKUP_MAX_AGE_HOURS else 1)" 2>/dev/null; then
        alert "Backup is ${backup_age}h old (threshold: ${BACKUP_MAX_AGE_HOURS}h)"
    else
        log "[OK] Backup age: ${backup_age}h"
    fi
else
    if [ "$http_code" != "200" ]; then
        # Already alerted about API being down, skip duplicate
        :
    else
        alert "Backup health endpoint returned empty response"
    fi
fi

# --- Check 3: Disk Usage ---
if [ -d "$APP_DIR" ]; then
    disk_usage=$(df "$APP_DIR" | tail -1 | awk '{print $5}' | tr -d '%')

    if [ "$disk_usage" -ge "$DISK_THRESHOLD" ]; then
        alert "Disk usage at ${disk_usage}% (threshold: ${DISK_THRESHOLD}%) on $APP_DIR"
    else
        log "[OK] Disk usage: ${disk_usage}%"
    fi
else
    log "[OK] Disk check skipped ($APP_DIR not found - likely running locally)"
fi

# --- Check 4: Docker containers running ---
if command -v docker &>/dev/null; then
    running=$(docker ps --filter "name=playwright" --format "{{.Names}}" 2>/dev/null | wc -l | tr -d ' ')

    if [ "$running" -ge 4 ]; then
        log "[OK] Docker: $running playwright containers running"
    elif [ "$running" -gt 0 ]; then
        alert "Only $running playwright containers running (expected >= 4)"
    else
        alert "No playwright containers running"
    fi
fi
