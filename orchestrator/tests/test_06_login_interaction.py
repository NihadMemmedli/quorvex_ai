#!/usr/bin/env python3
"""
Test 6: Login Form Interaction
Test actual form filling and submission
"""

import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claude_agent_sdk import ClaudeAgentOptions, query

pytestmark = pytest.mark.integration


async def test_login_form():
    """Test filling and submitting login form"""
    print("=" * 80)
    print("TEST: Login Form Interaction")
    print("=" * 80)
    print("URL: https://the-internet.herokuapp.com/login")
    print("Credentials: tomsmith / SuperSecretPassword!")
    print()

    prompt = """Use Playwright MCP to:

1. Navigate to https://the-internet.herokuapp.com/login
2. Get a snapshot and tell me what form fields you see
3. Fill in the username field with "tomsmith"
4. Fill in the password field with "SuperSecretPassword!"
5. Click the Login button
6. Tell me what happens after clicking

Be very specific about each step."""

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
                print(f"Result:\n{message.result}\n")
                return True
    except Exception as e:
        print(f"Error: {e}")
        import traceback

        traceback.print_exc()
        return False


if __name__ == "__main__":
    result = asyncio.run(test_login_form())
    print(f"\n{'=' * 80}")
    print(f"Test {'PASSED ✅' if result else 'FAILED ❌'}")
    print("=" * 80)
    sys.exit(0 if result else 1)
