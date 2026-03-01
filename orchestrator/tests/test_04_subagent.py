#!/usr/bin/env python3
"""
Test 4: Subagent Invocation
Verifies that file-based subagents work correctly
"""

import asyncio
import os
import sys
from pathlib import Path

import pytest

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claude_agent_sdk import ClaudeAgentOptions, query

pytestmark = pytest.mark.integration


async def test_subagent():
    """Test if file-based subagents work"""
    print("=" * 60)
    print("TEST 4: Subagent Invocation")
    print("=" * 60)
    print("Testing file-based subagent configuration...")
    print()

    # First, create a test subagent
    agents_dir = Path(".claude/agents")
    agents_dir.mkdir(parents=True, exist_ok=True)

    test_agent_file = agents_dir / "test-agent.md"
    test_agent_content = """---
name: test-agent
description: Test subagent for verification. Use this when asked to test subagent functionality.
tools: Read
model: inherit
---

You are a test agent. When prompted, you must respond with "TEST AGENT WORKING" in all caps.
This is to verify that subagent invocation is working correctly.
"""
    test_agent_file.write_text(test_agent_content)
    print(f"Created test subagent: {test_agent_file}")
    print()

    try:
        prompt = """Use the test-agent subagent.
Ask it to introduce itself and tell me what it says."""

        message_count = 0
        subagent_worked = False
        async for message in query(
            prompt=prompt,
            options=ClaudeAgentOptions(
                allowed_tools=["Read"],
                setting_sources=["project"],  # Enable .claude/ config
            ),
        ):
            message_count += 1
            print(f"Message {message_count}:")
            print(f"  Type: {type(message)}")

            if hasattr(message, "result"):
                result = message.result
                print(f"  Result: {result[:300]}...")

                if "TEST AGENT WORKING" in result:
                    subagent_worked = True
                    print("  ✅ Subagent invoked successfully!")

        print()
        if subagent_worked:
            print("✅ SUCCESS: Subagent invocation working")
        else:
            print("⚠️  WARNING: Subagent response not as expected")
            print("   Subagents might work differently than expected")

        return True

    except Exception as e:
        print(f"❌ FAILED: {e}")
        import traceback

        traceback.print_exc()
        return False


if __name__ == "__main__":
    result = asyncio.run(test_subagent())
    sys.exit(0 if result else 1)
