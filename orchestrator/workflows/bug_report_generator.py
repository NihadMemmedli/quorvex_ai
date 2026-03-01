"""
Bug Report Generator - AI-powered bug report creation from test failure data.

Uses Claude agent to analyze test failures and generate structured bug reports
suitable for Jira issue creation.

Follows the same pattern as security_analyzer.py using AgentRunner.
"""

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

# Setup path
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from load_env import setup_claude_env
from logging_config import get_logger, setup_logging
from utils.agent_runner import AgentRunner
from utils.json_utils import extract_json_from_markdown

logger = get_logger(__name__)


async def generate_bug_report(
    spec_name: str,
    target_url: str,
    error_message: str = "",
    validation_data: dict[str, Any] | None = None,
    run_data: dict[str, Any] | None = None,
    execution_log: str = "",
    generated_code: str = "",
) -> dict[str, Any]:
    """Generate an AI-powered bug report from test failure data.

    Args:
        spec_name: Name of the failed test specification
        target_url: URL being tested
        error_message: Primary error message from the failure
        validation_data: Contents of validation.json if available
        run_data: Contents of run.json if available
        execution_log: Last portion of execution.log
        generated_code: The generated test code that failed

    Returns:
        Dict matching the bug report JSON schema
    """
    setup_claude_env()

    # Build context sections
    sections = []

    sections.append(f"## Test Specification\n- Name: {spec_name}\n- Target URL: {target_url}")

    if error_message:
        sections.append(f"## Error Message\n```\n{error_message[:2000]}\n```")

    if validation_data:
        val_text = json.dumps(validation_data, indent=2)[:3000]
        sections.append(f"## Validation Results\n```json\n{val_text}\n```")

    if run_data:
        # Extract key fields
        run_summary = {
            k: run_data[k]
            for k in ["status", "duration", "browser", "error_message", "healing_attempts"]
            if k in run_data
        }
        run_text = json.dumps(run_summary, indent=2)
        sections.append(f"## Run Summary\n```json\n{run_text}\n```")

    if execution_log:
        # Last 2000 chars of log
        log_excerpt = execution_log[-2000:] if len(execution_log) > 2000 else execution_log
        sections.append(f"## Execution Log (last portion)\n```\n{log_excerpt}\n```")

    if generated_code:
        code_excerpt = generated_code[:3000]
        sections.append(f"## Generated Test Code\n```typescript\n{code_excerpt}\n```")

    context = "\n\n".join(sections)

    prompt = f"""Analyze the following test failure data and generate a structured bug report.

{context}

## Instructions
Create a bug report as a JSON object with the following structure:

```json
{{
    "title": "Clear, concise bug title describing the symptom",
    "description": "Detailed description of the bug including context",
    "steps_to_reproduce": [
        "Step 1: Navigate to ...",
        "Step 2: Click ...",
        "Step 3: ..."
    ],
    "expected_behavior": "What should have happened",
    "actual_behavior": "What actually happened (include error message)",
    "environment": {{
        "browser": "chromium",
        "url": "{target_url}",
        "test_spec": "{spec_name}"
    }},
    "error_details": {{
        "error_type": "Category of error (e.g., ElementNotFound, Timeout, AssertionFailed)",
        "error_message": "The exact error message",
        "stack_trace_summary": "Key lines from the stack trace if available"
    }},
    "priority": "P1|P2|P3|P4",
    "severity": "critical|high|medium|low",
    "suggested_labels": ["bug", "automated-test", ...],
    "suggested_components": ["component names if identifiable"]
}}
```

Be specific and factual. Use the actual error data provided — do not invent details.
"""

    runner = AgentRunner(
        timeout_seconds=120,
        allowed_tools=[],  # No tools needed for analysis
        log_tools=False,
    )
    result = await runner.run(prompt)

    if not result.success:
        error_msg = result.error or "Unknown error"
        if result.timed_out:
            raise RuntimeError(f"Bug report generation timed out: {error_msg}")
        raise RuntimeError(f"Bug report generation failed: {error_msg}")

    result_text = result.output

    if not result_text or not result_text.strip():
        raise RuntimeError("AI returned empty bug report")

    try:
        parsed = extract_json_from_markdown(result_text)
        if isinstance(parsed, dict):
            # Ensure required fields exist
            parsed.setdefault("title", f"Test failure: {spec_name}")
            parsed.setdefault("description", error_message or "Test failed")
            parsed.setdefault("steps_to_reproduce", [])
            parsed.setdefault("expected_behavior", "Test should pass")
            parsed.setdefault("actual_behavior", error_message or "Test failed")
            parsed.setdefault("priority", "P3")
            parsed.setdefault("severity", "medium")
            parsed.setdefault("suggested_labels", ["bug", "automated-test"])
            parsed.setdefault("suggested_components", [])
            parsed.setdefault(
                "environment",
                {
                    "browser": "chromium",
                    "url": target_url,
                    "test_spec": spec_name,
                },
            )
            parsed.setdefault(
                "error_details",
                {
                    "error_type": "Unknown",
                    "error_message": error_message,
                    "stack_trace_summary": "",
                },
            )
            return parsed
    except Exception as e:
        logger.warning(f"Failed to parse bug report as JSON: {e}")

    # Fallback: return raw text as description
    return {
        "title": f"Test failure: {spec_name}",
        "description": result_text[:2000],
        "steps_to_reproduce": [],
        "expected_behavior": "Test should pass",
        "actual_behavior": error_message or "Test failed",
        "environment": {
            "browser": "chromium",
            "url": target_url,
            "test_spec": spec_name,
        },
        "error_details": {
            "error_type": "Unknown",
            "error_message": error_message,
            "stack_trace_summary": "",
        },
        "priority": "P3",
        "severity": "medium",
        "suggested_labels": ["bug", "automated-test"],
        "suggested_components": [],
    }


if __name__ == "__main__":
    setup_logging()
    result = asyncio.run(
        generate_bug_report(
            spec_name="test-login.md",
            target_url="https://example.com/login",
            error_message="Timeout waiting for selector 'button[type=submit]'",
        )
    )
    print(json.dumps(result, indent=2))
