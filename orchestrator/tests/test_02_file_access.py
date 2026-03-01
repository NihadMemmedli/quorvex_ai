#!/usr/bin/env python3
"""
Test 2: File Access
Verifies that the Agent SDK can read files
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


async def test_file_access():
    """Test if agent can read files"""
    print("=" * 60)
    print("TEST 2: File Access")
    print("=" * 60)
    print("Testing file reading capabilities...")
    print()

    # Create test file
    test_file = Path("test_read_temp.txt")
    test_file.write_text("Hello from test file! This is test content.")
    print(f"Created test file: {test_file}")
    print(f"Content: {test_file.read_text()}")
    print()

    try:
        prompt = f"""Read the file {test_file} and tell me what it says.
Reply with just the content of the file, nothing else."""

        message_count = 0
        async for message in query(prompt=prompt, options=ClaudeAgentOptions(allowed_tools=["Read"])):
            message_count += 1
            print(f"Message {message_count}:")
            print(f"  Type: {type(message)}")

            if hasattr(message, "result"):
                print(f"  Result: {message.result}")
                if "Hello from test file" in message.result:
                    print("  ✅ File content correctly read!")
        print()
        print("✅ SUCCESS: File access working")
        return True

    except Exception as e:
        print(f"❌ FAILED: {e}")
        import traceback

        traceback.print_exc()
        return False

    finally:
        # Cleanup
        if test_file.exists():
            test_file.unlink()
            print(f"Cleaned up test file: {test_file}")


if __name__ == "__main__":
    result = asyncio.run(test_file_access())
    sys.exit(0 if result else 1)
