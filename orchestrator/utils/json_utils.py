"""
JSON extraction and validation utilities
"""

import json
import re
from pathlib import Path


def extract_json_from_markdown(text: str) -> dict:
    """
    Extract JSON from markdown code block.

    Handles:
    - ```json ... ```
    - ``` ... ```
    - Plain JSON string
    - Truncated JSON (attempts to fix)
    """
    if not text or not isinstance(text, str):
        raise ValueError("Input must be a non-empty string")

    text = text.strip()

    # Try to extract from ```json code block
    json_pattern = r"```json\s*(.*?)\s*```"
    match = re.search(json_pattern, text, re.DOTALL)
    if match:
        json_str = match.group(1).strip()
        return _parse_json_with_fallback(json_str)

    # Try to extract from ``` code block (no language specified)
    code_pattern = r"```\s*(.*?)\s*```"
    match = re.search(code_pattern, text, re.DOTALL)
    if match:
        json_str = match.group(1).strip()
        try:
            return _parse_json_with_fallback(json_str)
        except json.JSONDecodeError:
            pass  # Try next method

    # Try parsing the whole text as JSON
    try:
        return _parse_json_with_fallback(text)
    except ValueError as e:
        raise e


def _parse_json_with_fallback(json_str: str) -> dict:
    """
    Parse JSON with fallback for truncated output.
    """
    try:
        return json.loads(json_str)
    except json.JSONDecodeError as e:
        # Attempt to fix truncated JSON
        fixed = _attempt_fix_truncated_json(json_str)
        if fixed:
            try:
                return json.loads(fixed)
            except Exception:
                pass

        raise ValueError(f"Could not parse JSON. Error: {e}\nText preview: {json_str[:500]}...")


def _attempt_fix_truncated_json(json_str: str) -> str:
    """
    Attempt to fix truncated JSON by closing open brackets/quotes.
    Returns fixed string or None if fix is not possible.
    """
    # Count brackets to see what needs closing
    open_braces = json_str.count("{")
    close_braces = json_str.count("}")
    open_brackets = json_str.count("[")
    close_brackets = json_str.count("]")

    fixed = json_str.rstrip()

    # Check if we're in an incomplete string
    if fixed.count('"') % 2 != 0:
        # Odd number of quotes means we're in a string, close it
        fixed += '"'

    # Close arrays
    if open_brackets > close_brackets:
        fixed += "]" * (open_brackets - close_brackets)

    # Close objects
    if open_braces > close_braces:
        fixed += "}" * (open_braces - close_braces)

    # Remove trailing comma before closing brackets
    import re

    fixed = re.sub(r",(\s*[}\]])", r"\1", fixed)

    return fixed if fixed != json_str else None


def validate_json_schema(data: dict, schema_path: str) -> bool:
    """
    Validate JSON data against a schema file.
    """
    from jsonschema import ValidationError, validate

    schema = load_json_schema(schema_path)

    try:
        validate(instance=data, schema=schema)
        return True
    except ValidationError as e:
        raise ValueError(f"Schema validation failed: {e.message}\nPath: {' -> '.join(str(p) for p in e.path)}")


def load_json_schema(schema_path: str) -> dict:
    """Load JSON schema from file."""
    path = Path(schema_path)
    if not path.exists():
        raise FileNotFoundError(f"Schema file not found: {schema_path}")

    with open(path) as f:
        return json.load(f)


def save_json(data: dict, output_path: str) -> None:
    """Save JSON data to file with pretty formatting."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def load_json(file_path: str) -> dict:
    """Load JSON data from file."""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"JSON file not found: {file_path}")

    with open(path) as f:
        return json.load(f)
