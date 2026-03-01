"""
Database Test Generator

AI-powered generation of SQL data quality checks based on
schema metadata and analysis findings.

Follows the same pattern as security_analyzer.py using AgentRunner.
"""

import asyncio
import json
import sys
from pathlib import Path

# Setup path
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from load_env import setup_claude_env
from logging_config import get_logger, setup_logging
from utils.agent_runner import AgentRunner
from utils.json_utils import extract_json_from_markdown

logger = get_logger(__name__)


def _extract_checks_from_raw_sql(text: str) -> list:
    """Fallback: extract SQL checks from raw text when the model doesn't return JSON."""
    import re

    checks = []
    # Split on SQL comment headers like "-- Check for ..."
    blocks = re.split(r"(?:^|\n)--\s*(.+)", text)
    # blocks alternates: [preamble, comment1, sql1, comment2, sql2, ...]
    i = 1
    while i < len(blocks) - 1:
        comment = blocks[i].strip()
        sql_block = blocks[i + 1].strip()
        # Extract the first SELECT statement from the block
        match = re.search(r"(SELECT\s.+?LIMIT\s+\d+)", sql_block, re.IGNORECASE | re.DOTALL)
        if match:
            sql = re.sub(r"\s+", " ", match.group(1)).strip()
            # Derive a check name slug from the comment
            slug = re.sub(r"[^a-z0-9]+", "_", comment.lower()).strip("_")[:60]
            checks.append(
                {
                    "check_name": slug or f"check_{len(checks) + 1}",
                    "check_type": "custom",
                    "table_name": "",
                    "column_name": "",
                    "description": comment,
                    "severity": "medium",
                    "sql_query": sql,
                    "expected_result": "0 rows",
                }
            )
        i += 2
    if checks:
        logger.info(f"Fallback SQL extraction recovered {len(checks)} checks from raw text")
    return checks


async def generate_tests_from_schema(schema_info: dict, findings: list = None, focus_areas: list = None) -> list:
    """
    Generate SQL data quality checks from schema metadata and analysis findings.

    Args:
        schema_info: Raw introspection data
        findings: Optional list of schema analysis findings for context
        focus_areas: Optional list of focus area strings to prioritize (e.g. ["data quality", "referential integrity"])

    Returns:
        List of check dicts with keys: check_name, check_type, table_name, column_name,
        description, severity, sql_query, expected_result
    """
    setup_claude_env()

    # Truncate inputs
    tables = schema_info.get("tables", [])[:25]
    findings_text = ""
    if findings:
        findings_text = (
            f"\n## Schema Analysis Findings\n```json\n{json.dumps(findings[:20], indent=2, default=str)[:5000]}\n```"
        )

    focus_text = ""
    if focus_areas:
        focus_text = f"\n## Focus Areas\nPrioritize generating checks for: {', '.join(focus_areas)}\n"

    schema_text = json.dumps(
        {"tables": tables, "foreign_keys": schema_info.get("foreign_keys", [])},
        indent=2,
        default=str,
    )[:12000]

    prompt = f"""Generate SQL data quality validation checks for this PostgreSQL database.

IMPORTANT: You MUST respond with ONLY a valid JSON array. No explanations, no markdown text, no raw SQL outside of JSON. Your entire response must be parseable as JSON.

## Schema
```json
{schema_text}
```
{findings_text}
{focus_text}
## Requirements
- Generate 10-25 practical SQL checks
- ALL queries MUST be SELECT-only (no INSERT/UPDATE/DELETE/DROP)
- ALL queries MUST include LIMIT 100
- Prioritize high-impact checks first

## Check Types to Generate
1. **null_check**: Find unexpected NULLs in important columns
2. **uniqueness**: Verify columns that should be unique have no duplicates
3. **referential**: Check FK integrity (orphan records)
4. **freshness**: Verify recent data exists (tables not stale)
5. **range**: Check values are within expected ranges
6. **pattern**: Validate data formats (emails, dates, etc.)
7. **custom**: Cross-table consistency checks

## Output Format
Respond with ONLY a JSON array in a ```json code block. Do NOT include any other text, explanations, or SQL outside of the JSON structure.

```json
[
    {{
        "check_name": "orders_no_null_customer",
        "check_type": "null_check",
        "table_name": "orders",
        "column_name": "customer_id",
        "description": "Verify all orders have an associated customer",
        "severity": "high",
        "sql_query": "SELECT id, created_at FROM orders WHERE customer_id IS NULL LIMIT 100",
        "expected_result": "0 rows (no orphaned orders)"
    }}
]
```

Each check's sql_query should return violating rows (rows that FAIL the check).
So 0 rows = PASSED, >0 rows = FAILED.

REMINDER: Your ENTIRE response must be a single JSON array inside a ```json code block. Nothing else.
"""

    runner = AgentRunner(
        timeout_seconds=120,
        allowed_tools=[],  # No tools needed for generation
        log_tools=False,
    )
    result = await runner.run(prompt)

    if not result.success:
        error_msg = result.error or "Unknown error"
        if result.timed_out:
            raise RuntimeError(f"Test generation timed out: {error_msg}")
        raise RuntimeError(f"Test generation failed: {error_msg}")

    result_text = result.output

    if not result_text or not result_text.strip():
        raise RuntimeError("Test generation returned empty result")

    try:
        parsed = extract_json_from_markdown(result_text)
    except Exception as e:
        # Fallback: try to extract SQL queries from raw text and build checks
        logger.warning(f"JSON parse failed, attempting SQL fallback extraction: {e}")
        parsed = _extract_checks_from_raw_sql(result_text)
        if not parsed:
            raise RuntimeError(f"Failed to parse test generation response as JSON: {e}")

    # Handle both list and dict responses
    checks = parsed if isinstance(parsed, list) else parsed.get("checks", parsed.get("tests", []))

    # Validate each check has required fields
    valid_checks = []
    required = {"check_name", "check_type", "sql_query"}
    for check in checks:
        if isinstance(check, dict) and required.issubset(check.keys()):
            check.setdefault("severity", "medium")
            check.setdefault("description", "")
            check.setdefault("expected_result", "0 rows")
            check.setdefault("table_name", "")
            check.setdefault("column_name", "")
            valid_checks.append(check)

    if not valid_checks:
        raise RuntimeError("No valid checks generated")

    return valid_checks


if __name__ == "__main__":
    setup_logging()
    # Test with sample schema
    sample_schema = {
        "tables": [
            {
                "name": "users",
                "columns": [
                    {"name": "id", "type": "integer", "nullable": False},
                    {"name": "email", "type": "varchar(255)", "nullable": True},
                    {"name": "created_at", "type": "timestamp", "nullable": True},
                ],
                "indexes": [{"name": "pk_users", "columns": ["id"]}],
                "row_count": 10000,
            }
        ],
        "foreign_keys": [],
    }
    checks = asyncio.run(generate_tests_from_schema(sample_schema))
    print(json.dumps(checks, indent=2))
