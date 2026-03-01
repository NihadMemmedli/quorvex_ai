"""
Database Spec Parser

Converts markdown database test specifications into structured
SQL check definitions. Supports both direct SQL and natural language specs.

If the spec contains SQL code blocks, extracts them directly.
If natural language, sends to AI to generate SQL.

Follows the same pattern as security_analyzer.py using AgentRunner.
"""

import asyncio
import json
import re
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

# Regex to extract SQL code blocks
SQL_BLOCK_PATTERN = re.compile(r"```sql\s*\n(.*?)\n```", re.DOTALL | re.IGNORECASE)
# Regex to extract check metadata from comments: -- check: name | type | severity
CHECK_META_PATTERN = re.compile(r"--\s*check:\s*(.+?)(?:\|(.+?))?(?:\|(.+?))?\s*$", re.MULTILINE)


def _extract_sql_checks(spec_content: str) -> list:
    """Extract SQL checks directly from code blocks in the spec."""
    sql_blocks = SQL_BLOCK_PATTERN.findall(spec_content)
    if not sql_blocks:
        return []

    checks = []
    for i, sql in enumerate(sql_blocks, 1):
        sql = sql.strip()
        if not sql:
            continue

        # Try to extract metadata from comment
        meta = CHECK_META_PATTERN.search(sql)
        name = f"check_{i}"
        check_type = "custom"
        severity = "medium"

        if meta:
            name = meta.group(1).strip() if meta.group(1) else name
            check_type = meta.group(2).strip() if meta.group(2) else check_type
            severity = meta.group(3).strip() if meta.group(3) else severity

        checks.append(
            {
                "check_name": name,
                "check_type": check_type,
                "table_name": "",
                "column_name": "",
                "description": f"Check from spec block {i}",
                "severity": severity,
                "sql_query": sql,
                "expected_result": "0 rows",
            }
        )

    return checks


async def parse_spec_to_checks(spec_content: str, schema_info: dict = None) -> list:
    """
    Parse a markdown spec into SQL check definitions.

    If the spec contains SQL code blocks, extracts them directly.
    If the spec is natural language, uses AI to generate SQL queries.

    Args:
        spec_content: Markdown spec content
        schema_info: Optional schema context for AI generation

    Returns:
        List of check dicts
    """
    # First try direct extraction
    direct_checks = _extract_sql_checks(spec_content)
    if direct_checks:
        logger.info(f"Extracted {len(direct_checks)} SQL checks directly from spec")
        return direct_checks

    # Natural language spec - use AI to generate SQL
    logger.info("No SQL blocks found in spec, using AI to generate checks")
    setup_claude_env()

    schema_context = ""
    if schema_info:
        schema_text = json.dumps(schema_info, indent=2, default=str)[:10000]
        schema_context = f"\n## Database Schema\n```json\n{schema_text}\n```"

    prompt = f"""Convert this natural language database test specification into SQL validation queries.

## Test Specification
```markdown
{spec_content[:5000]}
```
{schema_context}

## Requirements
- ALL queries MUST be SELECT-only
- ALL queries MUST include LIMIT 100
- Each query should return VIOLATING rows (0 rows = check PASSED)
- Generate one check per requirement/bullet point in the spec

## Output Format
Return a JSON array:
```json
[
    {{
        "check_name": "descriptive_name",
        "check_type": "null_check|uniqueness|referential|range|pattern|custom|freshness",
        "table_name": "table_name",
        "column_name": "column_name_if_applicable",
        "description": "What this check validates",
        "severity": "critical|high|medium|low|info",
        "sql_query": "SELECT ... FROM ... WHERE ... LIMIT 100",
        "expected_result": "0 rows"
    }}
]
```
"""

    runner = AgentRunner(
        timeout_seconds=90,
        allowed_tools=[],  # No tools needed for spec parsing
        log_tools=False,
    )
    result = await runner.run(prompt)

    if not result.success:
        error_msg = result.error or "Unknown error"
        if result.timed_out:
            raise RuntimeError(f"Spec parsing timed out: {error_msg}")
        raise RuntimeError(f"Spec parsing failed: {error_msg}")

    result_text = result.output

    if not result_text or not result_text.strip():
        raise RuntimeError("Spec parsing returned empty result")

    try:
        parsed = extract_json_from_markdown(result_text)
    except Exception as e:
        raise RuntimeError(f"Failed to parse spec conversion response as JSON: {e}")

    checks = parsed if isinstance(parsed, list) else parsed.get("checks", [])

    valid_checks = []
    for check in checks:
        if isinstance(check, dict) and "sql_query" in check:
            check.setdefault("check_name", "unnamed_check")
            check.setdefault("check_type", "custom")
            check.setdefault("severity", "medium")
            check.setdefault("description", "")
            check.setdefault("expected_result", "0 rows")
            check.setdefault("table_name", "")
            check.setdefault("column_name", "")
            valid_checks.append(check)

    return valid_checks


if __name__ == "__main__":
    setup_logging()
    # Test with sample spec containing SQL blocks
    sample_spec = """# Database Test: Order Integrity

## Checks

```sql
-- check: orders_have_customer | referential | high
SELECT id, created_at FROM orders WHERE customer_id IS NULL LIMIT 100
```

```sql
-- check: positive_totals | range | medium
SELECT id, total FROM orders WHERE total < 0 LIMIT 100
```
"""
    checks = asyncio.run(parse_spec_to_checks(sample_spec))
    print(json.dumps(checks, indent=2))
