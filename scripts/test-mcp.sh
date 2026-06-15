#!/bin/bash
# Test MCP Server Connectivity
# Usage: docker exec -it playwright-agent-backend-1 bash /app/scripts/test-mcp.sh

set -e

APP_DIR="${APP_DIR:-$(pwd)}"
export npm_config_cache="${npm_config_cache:-/tmp/quorvex-npm-cache}"

echo "=== MCP Server Diagnostic Test ==="
echo ""

# Check environment
echo "1. Environment Check:"
echo "   DISPLAY=$DISPLAY"
echo "   HEADLESS=$HEADLESS"
echo "   Working directory: $(pwd)"
echo "   App directory: $APP_DIR"
echo "   npm cache: $npm_config_cache"
echo "   User: $(whoami)"
echo ""

# Check .mcp.json
echo "2. MCP Configuration:"
if [ -f "$APP_DIR/.mcp.json" ]; then
    echo "   Found $APP_DIR/.mcp.json:"
    cat "$APP_DIR/.mcp.json"
else
    echo "   ERROR: $APP_DIR/.mcp.json not found!"
fi
echo ""

# Check Node.js and npx
echo "3. Node.js Check:"
echo "   Node version: $(node --version)"
echo "   NPX available: $(which npx)"
echo ""

# Check if @playwright/mcp can be invoked
echo "4. Testing @playwright/mcp invocation:"
timeout 10 npx @playwright/mcp@0.0.76 --help 2>&1 | head -20 || echo "   MCP help command completed or timed out"
echo ""

# Check if appium-mcp can be invoked
echo "5. Testing appium-mcp invocation:"
timeout 10 npx appium-mcp --help 2>&1 | head -20 || echo "   Appium MCP command completed or timed out"
echo ""

# Check X display (for headed mode)
echo "6. Display Check (for headed browser):"
if [ -n "$DISPLAY" ]; then
    if xdpyinfo -display $DISPLAY >/dev/null 2>&1; then
        echo "   X display $DISPLAY is accessible"
    else
        echo "   WARNING: X display $DISPLAY is NOT accessible"
        echo "   Headed browser mode may fail"
    fi
else
    echo "   WARNING: DISPLAY not set, browser will run headless"
fi
echo ""

# Quick MCP server start test
echo "7. Testing Playwright MCP Server Start (5 second timeout):"
cd "$APP_DIR"
echo "   Starting MCP server with: npx @playwright/mcp@0.0.76 --browser chromium --headless"
timeout 5 npx @playwright/mcp@0.0.76 --browser chromium --headless 2>&1 &
MCP_PID=$!
sleep 3
if kill -0 $MCP_PID 2>/dev/null; then
    echo "   SUCCESS: MCP server started (PID: $MCP_PID)"
    kill $MCP_PID 2>/dev/null || true
else
    echo "   MCP server exited quickly (check for errors above)"
fi
echo ""

echo "8. Appium Mobile Preflight (no server required):"
python - <<'PY' || true
from orchestrator.workflows.mobile_appium import AppiumPreflightChecker, MobileAppiumConfig
result = AppiumPreflightChecker(MobileAppiumConfig.from_env()).run(require_server=False)
print(f"   Ready: {result.ready}")
if result.udid:
    print(f"   Device UDID: {result.udid}")
if result.device_name:
    print(f"   Device: {result.device_name}")
for error in result.errors[:5]:
    print(f"   ERROR: {error}")
PY
echo ""

echo "=== Diagnostic Complete ==="
