"""
Database Schema Analyzer

AI-powered analysis of PostgreSQL schema metadata to identify
quality issues, anti-patterns, and improvement opportunities.

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


async def analyze_schema(schema_info: dict) -> dict:
    """
    Analyze a database schema and identify quality issues.

    Args:
        schema_info: Raw introspection data from DatabaseConnector.introspect_schema()

    Returns:
        dict with keys: findings (list), summary (str), health_score (int 1-100)
    """
    setup_claude_env()

    # Truncate schema info if too large (keep first 30 tables max)
    tables = schema_info.get("tables", [])
    if len(tables) > 30:
        tables = tables[:30]
        schema_info = {**schema_info, "tables": tables}

    prompt = f"""Analyze this PostgreSQL database schema and identify quality issues.

## Schema Information
```json
{json.dumps(schema_info, indent=2, default=str)[:15000]}
```

## Analysis Categories
Check for issues in these categories:
1. **Missing Indexes**: Tables with many rows but no indexes on commonly queried columns
2. **Constraint Issues**: Missing NOT NULL on required fields, missing CHECK constraints
3. **Foreign Key Gaps**: Tables that likely reference others but lack FK constraints
4. **Naming Inconsistencies**: Mixed naming conventions (camelCase vs snake_case, plural vs singular)
5. **Data Type Concerns**: Using VARCHAR when TEXT is better, wrong numeric types, missing timestamps
6. **Anti-Patterns**: God tables (too many columns), missing audit columns, EAV patterns

## Output Format
Return a JSON object with this exact structure:
```json
{{
    "findings": [
        {{
            "severity": "high",
            "category": "missing_index",
            "table_name": "orders",
            "column_name": "customer_id",
            "title": "Missing index on frequently queried FK column",
            "description": "The orders.customer_id column likely has high cardinality...",
            "recommendation": "CREATE INDEX idx_orders_customer_id ON orders (customer_id);"
        }}
    ],
    "summary": "Overall assessment of schema health...",
    "health_score": 72
}}
```

Severity levels: critical, high, medium, low, info
Categories: missing_index, constraint_issue, fk_gap, naming_inconsistency, data_type_concern, anti_pattern, missing_audit, performance

Generate 5-20 findings, prioritized by impact. Be specific with recommendations including actual SQL fixes.
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
            raise RuntimeError(f"Schema analysis timed out: {error_msg}")
        raise RuntimeError(f"Schema analysis failed: {error_msg}")

    result_text = result.output

    if not result_text or not result_text.strip():
        raise RuntimeError("Schema analysis returned empty result")

    # Parse JSON from AI response
    try:
        parsed = extract_json_from_markdown(result_text)
    except Exception as e:
        logger.warning(f"Failed to parse schema analysis as JSON: {e}")
        return {
            "findings": [],
            "summary": result_text[:500],
            "health_score": 50,
        }

    # Ensure required keys
    if isinstance(parsed, dict):
        parsed.setdefault("findings", [])
        parsed.setdefault("summary", "")
        parsed.setdefault("health_score", 50)
        return parsed

    return {
        "findings": parsed if isinstance(parsed, list) else [],
        "summary": "",
        "health_score": 50,
    }


if __name__ == "__main__":
    setup_logging()
    # Test with sample schema
    sample_schema = {
        "tables": [
            {
                "name": "orders",
                "columns": [
                    {"name": "id", "type": "integer", "nullable": False},
                    {"name": "customer_id", "type": "integer", "nullable": True},
                    {"name": "total", "type": "varchar(255)", "nullable": True},
                ],
                "indexes": [],
                "row_count": 50000,
            }
        ],
        "foreign_keys": [],
    }
    result = asyncio.run(analyze_schema(sample_schema))
    print(json.dumps(result, indent=2))
