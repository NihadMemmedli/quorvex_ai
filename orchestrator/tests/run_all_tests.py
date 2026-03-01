#!/usr/bin/env python3
"""
Test Runner
Runs all API verification tests in sequence
"""

import asyncio
import os
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def run_test(test_name: str, test_func) -> bool:
    """Run a single test"""
    print("\n" + "=" * 80)
    print(f"RUNNING: {test_name}")
    print("=" * 80)
    try:
        result = await test_func()
        status = "✅ PASSED" if result else "❌ FAILED"
        print(f"\n{status}: {test_name}")
        return result
    except Exception as e:
        print(f"\n❌ EXCEPTION in {test_name}: {e}")
        import traceback

        traceback.print_exc()
        return False


async def main():
    """Run all tests"""
    print("\n" + "=" * 80)
    print("AGENT SDK API VERIFICATION TEST SUITE")
    print("=" * 80)

    # Import test functions
    from test_01_basic_query import test_basic_query
    from test_02_file_access import test_file_access
    from test_03_mcp_access import test_mcp_access
    from test_04_subagent import test_subagent

    results = {}

    # Run tests
    results["Test 1: Basic Query"] = await run_test("Test 1: Basic Query", test_basic_query)

    results["Test 2: File Access"] = await run_test("Test 2: File Access", test_file_access)

    results["Test 3: MCP Tool Access"] = await run_test("Test 3: MCP Tool Access", test_mcp_access)

    results["Test 4: Subagent Invocation"] = await run_test("Test 4: Subagent Invocation", test_subagent)

    # Summary
    print("\n" + "=" * 80)
    print("TEST SUMMARY")
    print("=" * 80)

    passed = sum(1 for v in results.values() if v)
    total = len(results)

    for test_name, result in results.items():
        status = "✅ PASSED" if result else "❌ FAILED"
        print(f"{status}: {test_name}")

    print()
    print(f"Total: {passed}/{total} tests passed")
    print("=" * 80)

    # Save results
    findings_file = Path("../API_FINDINGS.md")
    findings_content = f"""# Agent SDK API Findings

## Test Results

**Date**: {asyncio.get_event_loop().time()}
**Passed**: {passed}/{total}

### Test 1: Basic Query
Status: {"✅ PASSED" if results["Test 1: Basic Query"] else "❌ FAILED"}

### Test 2: File Access
Status: {"✅ PASSED" if results["Test 2: File Access"] else "❌ FAILED"}

### Test 3: MCP Tool Access
Status: {"✅ PASSED" if results["Test 3: MCP Tool Access"] else "❌ FAILED"}

### Test 4: Subagent Invocation
Status: {"✅ PASSED" if results["Test 4: Subagent Invocation"] else "❌ FAILED"}

## Key Findings

<!-- Update this section after running tests -->

## API Behavior Notes

<!-- Document any unexpected behavior or limitations -->

## Next Steps

<!-- Based on results, what should we do next? -->
"""
    findings_file.write_text(findings_content)
    print(f"\n📝 Findings saved to: {findings_file}")

    return passed == total


if __name__ == "__main__":
    result = asyncio.run(main())
    sys.exit(0 if result else 1)
