#!/usr/bin/env python3
"""
Test 3: MCP Tool Access
Verifies that the Agent SDK can access MCP tools (especially Playwright)
"""

import asyncio
import os
import sys

import pytest

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claude_agent_sdk import ClaudeAgentOptions, query

pytestmark = pytest.mark.integration


async def test_mcp_access():
    """Test if agent can access MCP tools"""
    print("=" * 60)
    print("TEST 3: MCP Tool Access")
    print("=" * 60)
    print("Testing MCP tool availability...")
    print()

    try:
        prompt = """List all available tools that you have access to.
Tell me:
1. What built-in tools you can use
2. What MCP tools are available (if any)
3. Whether you see any Playwright-related tools

Be specific and list tool names."""

        message_count = 0
        playwright_found = False
        async for message in query(
            prompt=prompt,
            options=ClaudeAgentOptions(
                allowed_tools=["*"],  # Try to get all tools
                setting_sources=["project"],  # Enable .claude/ config
            ),
        ):
            message_count += 1
            print(f"Message {message_count}:")
            print(f"  Type: {type(message)}")

            if hasattr(message, "result"):
                result = message.result
                print(f"  Result preview: {result[:500]}...")

                # Check for Playwright
                if "playwright" in result.lower():
                    playwright_found = True
                    print("  ✅ Playwright MCP tools detected!")

        print()
        if playwright_found:
            print("✅ SUCCESS: MCP tools (including Playwright) are accessible")
        else:
            print("⚠️  WARNING: Playwright not explicitly mentioned")
            print("   This might mean MCP tools need different configuration")

        return True

    except Exception as e:
        print(f"❌ FAILED: {e}")
        import traceback

        traceback.print_exc()
        return False


if __name__ == "__main__":
    result = asyncio.run(test_mcp_access())
    sys.exit(0 if result else 1)
