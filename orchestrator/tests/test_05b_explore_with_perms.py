#!/usr/bin/env python3
"""
Test 5b: Explore Demo Sites with Auto-Permission
"""

import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claude_agent_sdk import ClaudeAgentOptions, query

pytestmark = pytest.mark.integration


async def test_simple_navigation():
    """Test simple navigation with permissions"""
    print("=" * 80)
    print("TEST: Simple Navigation to Example.com")
    print("=" * 80)

    prompt = """Navigate to https://example.com using Playwright MCP.
Tell me what you see on the page."""

    try:
        # Try with bypassPermissions
        async for message in query(
            prompt=prompt,
            options=ClaudeAgentOptions(
                allowed_tools=["*"],
                setting_sources=["project"],
                permission_mode="bypassPermissions",  # Auto-approve all tools
            ),
        ):
            if hasattr(message, "result"):
                print(f"\nResult:\n{message.result}\n")
                return True
    except Exception as e:
        print(f"Error with bypassPermissions: {e}")

    try:
        # Try with acceptEdits
        async for message in query(
            prompt=prompt,
            options=ClaudeAgentOptions(
                allowed_tools=["*"],
                setting_sources=["project"],
                permission_mode="acceptEdits",
            ),
        ):
            if hasattr(message, "result"):
                print(f"\nResult:\n{message.result}\n")
                return True
    except Exception as e:
        print(f"Error with acceptEdits: {e}")

    return False


if __name__ == "__main__":
    result = asyncio.run(test_simple_navigation())
    print(f"\nTest {'PASSED' if result else 'FAILED'}")
    sys.exit(0 if result else 1)
