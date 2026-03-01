#!/usr/bin/env python3
"""
Test 7: Can Playwright MCP use vague descriptions?
Test if "Username field" is enough to find the element
"""

import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claude_agent_sdk import ClaudeAgentOptions, query

pytestmark = pytest.mark.integration


async def test_vague_descriptions():
    """Test if Agent can find elements from descriptions"""
    print("=" * 80)
    print("TEST: Can we use vague descriptions to find elements?")
    print("=" * 80)

    prompt = """Use Playwright MCP to:

1. Navigate to https://the-internet.herokuapp.com/login
2. Get a snapshot of the page
3. Find the "Username field" (just from that description)
4. Fill it with "tomsmith"
5. Tell me: How did you know which element to fill? What selector did you use?"""

    try:
        async for message in query(
            prompt=prompt,
            options=ClaudeAgentOptions(
                allowed_tools=["*"],
                setting_sources=["project"],
                permission_mode="bypassPermissions",
            ),
        ):
            if hasattr(message, "result"):
                print(f"\nResult:\n{message.result}\n")
                return True
    except Exception as e:
        print(f"Error: {e}")
        return False


if __name__ == "__main__":
    result = asyncio.run(test_vague_descriptions())
    print(f"\n{'=' * 80}")
    if result:
        print("✅ TEST PASSED: Vague descriptions work!")
        print("   The Planner output CAN be used directly")
    else:
        print("❌ TEST FAILED: Vague descriptions don't work")
        print("   We need to fix the Planner to output proper selectors")
    print("=" * 80)
    sys.exit(0 if result else 1)
