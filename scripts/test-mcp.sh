#!/bin/bash
# Test MCP Server Connectivity
# Usage: docker exec -it playwright-agent-backend-1 bash /app/scripts/test-mcp.sh

set -e

echo "=== MCP Server Diagnostic Test ==="
echo ""

# Check environment
echo "1. Environment Check:"
echo "   DISPLAY=$DISPLAY"
echo "   HEADLESS=$HEADLESS"
echo "   Working directory: $(pwd)"
echo "   User: $(whoami)"
echo ""

# Check .mcp.json
echo "2. MCP Configuration:"
if [ -f "/app/.mcp.json" ]; then
    echo "   Found /app/.mcp.json:"
    cat /app/.mcp.json
else
    echo "   ERROR: /app/.mcp.json not found!"
fi
echo ""

# Check Node.js and npx
echo "3. Node.js Check:"
echo "   Node version: $(node --version)"
echo "   NPX available: $(which npx)"
echo ""

# Check if @playwright/mcp can be invoked
echo "4. Testing @playwright/mcp invocation:"
timeout 10 npx @playwright/mcp@latest --help 2>&1 | head -20 || echo "   MCP help command completed or timed out"
echo ""

# Check X display (for headed mode)
echo "5. Display Check (for headed browser):"
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
echo "6. Testing MCP Server Start (5 second timeout):"
cd /app
echo "   Starting MCP server with: npx @playwright/mcp@latest --browser chromium --headless"
timeout 5 npx @playwright/mcp@latest --browser chromium --headless 2>&1 &
MCP_PID=$!
sleep 3
if kill -0 $MCP_PID 2>/dev/null; then
    echo "   SUCCESS: MCP server started (PID: $MCP_PID)"
    kill $MCP_PID 2>/dev/null || true
else
    echo "   MCP server exited quickly (check for errors above)"
fi
echo ""

echo "=== Diagnostic Complete ==="
