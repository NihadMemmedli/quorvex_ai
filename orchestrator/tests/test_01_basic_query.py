#!/usr/bin/env python3
"""
Test 1: Basic Query
Verifies that the Agent SDK can perform a simple query
"""

import asyncio
import os
import sys

import pytest

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claude_agent_sdk import ClaudeAgentOptions, query

pytestmark = pytest.mark.integration


async def test_basic_query():
    """Test if basic query() works"""
    print("=" * 60)
    print("TEST 1: Basic Query")
    print("=" * 60)
    print("Testing basic Agent SDK query() function...")
    print()

    try:
        message_count = 0
        async for message in query(
            prompt="What is 2+2? Reply with just the number.",
            options=ClaudeAgentOptions(allowed_tools=[]),
        ):
            message_count += 1
            print(f"Message {message_count}:")
            print(f"  Type: {type(message)}")
            print(f"  Content: {message}")
            print()

            # Check different possible attributes
            if hasattr(message, "result"):
                print(f"  ✅ Has 'result' attribute: {message.result}")
            if hasattr(message, "content"):
                print(f"  ✅ Has 'content' attribute: {message.content}")
            if hasattr(message, "text"):
                print(f"  ✅ Has 'text' attribute: {message.text}")

        print()
        print(f"✅ SUCCESS: Received {message_count} message(s)")
        return True

    except Exception as e:
        print(f"❌ FAILED: {e}")
        import traceback

        traceback.print_exc()
        return False


if __name__ == "__main__":
    result = asyncio.run(test_basic_query())
    sys.exit(0 if result else 1)
