import json

import pytest

from orchestrator.utils.json_utils import (
    extract_json_from_markdown,
    load_json,
    load_json_schema,
    save_json,
    validate_json_schema,
)


def test_extract_json_from_plain_json_object_string():
    assert extract_json_from_markdown('{"name": "Checkout", "enabled": true}') == {
        "name": "Checkout",
        "enabled": True,
    }


def test_extract_json_from_json_fenced_block():
    text = 'Here is the result:\n```json\n{"status": "ok", "count": 2}\n```'

    assert extract_json_from_markdown(text) == {"status": "ok", "count": 2}


def test_extract_json_from_generic_fenced_block():
    text = '```\n{"items": ["login", "checkout"]}\n```'

    assert extract_json_from_markdown(text) == {"items": ["login", "checkout"]}


def test_extract_json_from_markdown_strips_surrounding_whitespace_and_fence_padding():
    text = '\n\n  ```json  \n  {"scope": "billing", "priority": "high"}  \n  ```  \n'

    assert extract_json_from_markdown(text) == {"scope": "billing", "priority": "high"}


def test_extract_json_from_truncated_json_repairs_missing_closers():
    text = '{"summary": "partial", "findings": ["Missing empty state"'

    assert extract_json_from_markdown(text) == {
        "summary": "partial",
        "findings": ["Missing empty state"],
    }


def test_extract_json_from_unrecoverable_json_raises_value_error():
    with pytest.raises(ValueError, match="Could not parse JSON"):
        extract_json_from_markdown('{"status": nope}')


@pytest.mark.parametrize("value", ["", None, {"status": "ok"}, 123])
def test_extract_json_from_empty_none_and_non_string_inputs_raise_input_value_error(value):
    with pytest.raises(ValueError, match="Input must be a non-empty string"):
        extract_json_from_markdown(value)


def test_extract_json_from_whitespace_only_string_raises_value_error():
    with pytest.raises(ValueError, match="Could not parse JSON"):
        extract_json_from_markdown("   ")


def test_save_json_creates_parent_directories_and_writes_pretty_json(tmp_path):
    output_path = tmp_path / "nested" / "result.json"
    data = {"name": "Regression", "checks": ["login", "checkout"]}

    save_json(data, str(output_path))

    assert output_path.exists()
    assert output_path.read_text() == json.dumps(data, indent=2)


def test_load_json_reads_saved_content(tmp_path):
    output_path = tmp_path / "result.json"
    data = {"status": "passed", "duration": 12}
    save_json(data, str(output_path))

    assert load_json(str(output_path)) == data


def test_load_json_raises_file_not_found_for_missing_file(tmp_path):
    missing_path = tmp_path / "missing.json"

    with pytest.raises(FileNotFoundError, match="JSON file not found"):
        load_json(str(missing_path))


def test_load_json_schema_reads_schema(tmp_path):
    schema_path = tmp_path / "schema.json"
    schema = {
        "type": "object",
        "required": ["name"],
        "properties": {"name": {"type": "string"}},
    }
    schema_path.write_text(json.dumps(schema))

    assert load_json_schema(str(schema_path)) == schema


def test_load_json_schema_raises_file_not_found_for_missing_file(tmp_path):
    missing_path = tmp_path / "schema.json"

    with pytest.raises(FileNotFoundError, match="Schema file not found"):
        load_json_schema(str(missing_path))


def test_validate_json_schema_returns_true_for_valid_data(tmp_path):
    schema_path = tmp_path / "schema.json"
    schema_path.write_text(
        json.dumps(
            {
                "type": "object",
                "required": ["name", "enabled"],
                "properties": {
                    "name": {"type": "string"},
                    "enabled": {"type": "boolean"},
                },
            }
        )
    )

    assert validate_json_schema({"name": "Checkout", "enabled": True}, str(schema_path)) is True


def test_validate_json_schema_raises_value_error_for_invalid_data(tmp_path):
    schema_path = tmp_path / "schema.json"
    schema_path.write_text(
        json.dumps(
            {
                "type": "object",
                "required": ["name"],
                "properties": {"name": {"type": "string"}},
            }
        )
    )

    with pytest.raises(ValueError, match="Schema validation failed"):
        validate_json_schema({"name": 42}, str(schema_path))
