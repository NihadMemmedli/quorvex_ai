#!/usr/bin/env python3
"""
Test 5: Explore Demo Sites with Playwright MCP
Document the actual page structure and elements
"""

import asyncio
import os
import sys

import pytest

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from claude_agent_sdk import ClaudeAgentOptions, query

pytestmark = pytest.mark.integration


async def explore_site(site_url: str, test_name: str):
    """Explore a site and document what we find"""
    print(f"\n{'=' * 80}")
    print(f"EXPLORING: {test_name}")
    print(f"URL: {site_url}")
    print("=" * 80)

    prompt = f"""Use Playwright MCP to:

1. Navigate to {site_url}
2. Get a snapshot of the page (accessibility tree)
3. Tell me:
   - What elements are on the page?
   - What roles are available?
   - What text/labels do you see?
   - Take a screenshot and save it as {test_name.replace(" ", "_").lower()}.png

Be very specific about element roles, labels, and IDs."""

    try:
        async for message in query(
            prompt=prompt,
            options=ClaudeAgentOptions(allowed_tools=["*"], setting_sources=["project"]),
        ):
            if hasattr(message, "result"):
                print(message.result)
        return True
    except Exception as e:
        print(f"❌ Error: {e}")
        return False


async def main():
    """Explore all demo sites"""
    print("\n" + "=" * 80)
    print("DEMO SITE EXPLORATION WITH PLAYWRIGHT MCP")
    print("=" * 80)

    sites = [
        ("https://example.com", "Example.com"),
        ("https://the-internet.herokuapp.com", "The Internet Home"),
        ("https://the-internet.herokuapp.com/login", "Login Page"),
        ("https://the-internet.herokuapp.com/dynamic_loading/1", "Dynamic Loading"),
    ]

    results = {}
    for url, name in sites:
        results[name] = await explore_site(url, name)

    # Summary
    print("\n" + "=" * 80)
    print("EXPLORATION SUMMARY")
    print("=" * 80)
    for name, success in results.items():
        status = "✅ SUCCESS" if success else "❌ FAILED"
        print(f"{status}: {name}")

    return all(results.values())


if __name__ == "__main__":
    result = asyncio.run(main())
    sys.exit(0 if result else 1)
