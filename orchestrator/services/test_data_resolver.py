"""Project-scoped test data resolver and renderer."""

from __future__ import annotations

import ast
import json
import re
from copy import deepcopy
from typing import Any

from sqlmodel import Session, select

from orchestrator.api.credentials import decrypt_credential, encrypt_credential
from orchestrator.api.models_db import TestDataItem, TestDataSet

VALID_REF_RE = re.compile(r"^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$")
TESTDATA_DIRECTIVE_RE = re.compile(r'^[ \t]*@testdata\s+"([^"]+)"[ \t]*$', re.MULTILINE)
TESTDATA_FRONTMATTER_RE = re.compile(r"^test_data_refs:\s*(.+?)\s*$", re.MULTILINE)
SECRET_TEXT_PATH = "$text"


def normalize_test_data_key(value: str, *, label: str = "key") -> str:
    key = str(value or "").strip()
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,79}", key):
        raise ValueError(
            f"{label} must start with a letter and use only letters, numbers, dashes, or underscores"
        )
    return key


def normalize_test_data_format(value: str | None) -> str:
    fmt = str(value or "json").strip().lower()
    if fmt not in {"json", "text", "mixed"}:
        raise ValueError("format must be one of: json, text, mixed")
    return fmt


def normalize_test_data_status(value: str | None) -> str:
    status = str(value or "active").strip().lower()
    if status not in {"active", "archived"}:
        raise ValueError("status must be one of: active, archived")
    return status


def prepare_test_data_item_storage(
    *,
    data: Any = None,
    text: str | None = None,
    sensitive_fields: list[str] | None = None,
) -> dict[str, Any]:
    """Return public data/text plus encrypted sensitive values for storage."""

    fields = [
        str(field).strip() for field in (sensitive_fields or []) if str(field).strip()
    ]
    public_data = deepcopy(data) if data is not None else None
    public_text = text
    encrypted_values: dict[str, str] = {}

    for field in fields:
        if field == SECRET_TEXT_PATH:
            if text is not None:
                encrypted_values[field] = _encrypt_value(text)
                public_text = _placeholder("text", field)
            continue
        if public_data is None:
            continue
        found, value = _get_path(public_data, field)
        if not found:
            continue
        encrypted_values[field] = _encrypt_value(value)
        _set_path(public_data, field, _placeholder("json", field))

    return {
        "data": public_data,
        "text": public_text,
        "sensitive_fields": fields,
        "encrypted_values": encrypted_values,
    }


def resolve_test_data_refs(
    session: Session,
    *,
    project_id: str,
    refs: list[str],
    render_as: str = "json",
    include_archived: bool = False,
    decrypt_sensitive: bool = False,
) -> dict[str, Any]:
    normalized_refs = _dedupe_refs(refs)
    resolved: dict[str, Any] = {}
    missing: list[dict[str, str]] = []

    for ref in normalized_refs:
        dataset_key, item_key = ref.split(".", 1)
        dataset = session.exec(
            select(TestDataSet)
            .where(TestDataSet.project_id == project_id)
            .where(TestDataSet.key == dataset_key)
        ).first()
        if not dataset or (not include_archived and dataset.status == "archived"):
            missing.append({"ref": ref, "reason": "dataset_not_found"})
            continue
        item = session.exec(
            select(TestDataItem)
            .where(TestDataItem.dataset_id == dataset.id)
            .where(TestDataItem.key == item_key)
        ).first()
        if not item or (not include_archived and item.status == "archived"):
            missing.append({"ref": ref, "reason": "item_not_found"})
            continue
        resolved[ref] = _item_payload(
            dataset, item, decrypt_sensitive=decrypt_sensitive
        )

    result = {
        "project_id": project_id,
        "refs": normalized_refs,
        "items": resolved,
        "missing": missing,
        "render_as": render_as,
    }
    if render_as == "markdown":
        result["markdown"] = render_test_data_markdown(resolved)
    elif render_as == "env":
        result["env"] = render_test_data_env_placeholders(resolved)
    else:
        result["json"] = {
            ref: _json_context_payload(payload) for ref, payload in resolved.items()
        }
    return result


def resolve_test_data_execution_context(
    session: Session,
    *,
    project_id: str,
    refs: list[str] | None = None,
    markdown: str | None = None,
    include_archived: bool = False,
) -> dict[str, Any]:
    """Resolve project test data for execution prompts and subprocess env.

    This intentionally returns decrypted values for agent/runtime execution paths.
    UI/API display paths should keep using ``resolve_test_data_refs`` with masked
    sensitive fields.
    """

    normalized_refs = _dedupe_refs(
        [
            *(refs or []),
            *extract_test_data_refs_from_markdown(markdown or ""),
        ]
    )
    masked = resolve_test_data_refs(
        session,
        project_id=project_id,
        refs=normalized_refs,
        render_as="json",
        include_archived=include_archived,
        decrypt_sensitive=False,
    )
    plaintext = resolve_test_data_refs(
        session,
        project_id=project_id,
        refs=normalized_refs,
        render_as="markdown",
        include_archived=include_archived,
        decrypt_sensitive=True,
    )
    items = plaintext.get("items") or {}
    env_vars = render_test_data_env_vars(items)
    login_credentials = _login_credentials_from_items(items)
    prompt_markdown = render_test_data_execution_markdown(
        items,
        env_vars=env_vars,
        missing=plaintext.get("missing") or [],
    )
    return {
        "project_id": project_id,
        "refs": normalized_refs,
        "prompt_markdown": prompt_markdown,
        "markdown": prompt_markdown,
        "masked_json": masked.get("json", {}),
        "runtime_fixtures": render_test_data_runtime_fixtures(items),
        "env_vars": env_vars,
        "missing": plaintext.get("missing") or masked.get("missing") or [],
        "login_credentials": login_credentials,
    }


def render_test_data_markdown(items: dict[str, Any]) -> str:
    if not items:
        return ""
    lines = ["## Project Test Data"]
    for ref, payload in items.items():
        lines.append("")
        lines.append(f"### {ref}")
        description = payload.get("description") or payload.get("dataset_description")
        if description:
            lines.append(str(description))
            lines.append("")
        if payload.get("data") is not None:
            lines.append("```json")
            lines.append(json.dumps(payload["data"], indent=2, ensure_ascii=False))
            lines.append("```")
        if payload.get("text"):
            lines.append(str(payload["text"]))
        placeholders = payload.get("placeholders") or {}
        if placeholders:
            lines.append("")
            lines.append("Sensitive values are available only as placeholders:")
            for path, placeholder in placeholders.items():
                lines.append(f"- `{path}` -> `{placeholder}`")
    return "\n".join(lines).strip()


def render_test_data_env_placeholders(items: dict[str, Any]) -> dict[str, str]:
    env: dict[str, str] = {}
    for payload in items.values():
        for placeholder in (payload.get("placeholders") or {}).values():
            env_name = placeholder.strip("{}")
            env[env_name] = placeholder
    return env


def render_test_data_env_vars(items: dict[str, Any]) -> dict[str, str]:
    """Render deterministic TESTDATA_* env vars with decrypted execution values."""

    env: dict[str, str] = {}
    for ref, payload in items.items():
        dataset_key = str(payload.get("dataset_key") or ref.split(".", 1)[0])
        item_key = str(payload.get("item_key") or ref.split(".", 1)[1])
        data = payload.get("data")
        if isinstance(data, dict):
            for path, value in _flatten_scalar_paths(data).items():
                env_name = _placeholder_ref(dataset_key, item_key, path).strip("{}")
                env[env_name] = str(value)
        text = payload.get("text")
        if text:
            env_name = _placeholder_ref(dataset_key, item_key, "text").strip("{}")
            env[env_name] = str(text)
    return env


def render_test_data_runtime_fixtures(items: dict[str, Any]) -> dict[str, Any]:
    """Render decrypted ref-keyed payloads for a run-local Playwright fixture file."""

    fixtures: dict[str, Any] = {}
    for ref, payload in items.items():
        fixtures[ref] = {
            "data": deepcopy(payload.get("data")),
            "text": payload.get("text"),
            "format": payload.get("format"),
            "sensitive_fields": list(payload.get("sensitive_fields") or []),
        }
    return fixtures


def render_test_data_execution_markdown(
    items: dict[str, Any],
    *,
    env_vars: dict[str, str] | None = None,
    missing: list[dict[str, str]] | None = None,
) -> str:
    if not items and not missing:
        return ""
    lines = ["## Available Project Test Data"]
    if items:
        rendered = render_test_data_markdown(items)
        if rendered:
            lines.append(rendered.replace("## Project Test Data", "").strip())
    if env_vars:
        lines.extend(
            [
                "",
                "### Generated Test Fixture Usage",
                "Generated Playwright tests must use the `testData` fixture by canonical ref. Do not write `process.env.TESTDATA_*` in generated code.",
            ]
        )
        for ref in sorted(items):
            lines.append(f"- `testData.get('{ref}')` returns the resolved fixture data")
    if missing:
        lines.extend(["", "### Missing Test Data Refs"])
        for item in missing:
            lines.append(
                f"- `{item.get('ref')}` ({item.get('reason') or 'not_found'})"
            )
    return "\n".join(lines).strip()


def resolve_login_credentials_from_testdata_refs(
    session: Session,
    *,
    project_id: str,
    refs: list[str],
) -> dict[str, str] | None:
    """Resolve the first @testdata item shaped like login credentials."""

    resolved = resolve_test_data_refs(
        session,
        project_id=project_id,
        refs=refs,
        render_as="json",
        decrypt_sensitive=True,
    )
    return _login_credentials_from_items(resolved.get("items") or {})


def _login_credentials_from_items(items: dict[str, Any]) -> dict[str, str] | None:
    for ref, payload in items.items():
        data = payload.get("data")
        if not isinstance(data, dict):
            continue
        username_field, username = _first_present(data, ("username", "email"))
        password_field, password = _first_present(data, ("password",))
        if not username or not password:
            continue
        dataset_key = str(payload.get("dataset_key") or ref.split(".", 1)[0])
        item_key = str(payload.get("item_key") or ref.split(".", 1)[1])
        username_var = _placeholder_ref(dataset_key, item_key, username_field).strip(
            "{}"
        )
        password_var = _placeholder_ref(dataset_key, item_key, password_field).strip(
            "{}"
        )
        return {
            "username": str(username),
            "password": str(password),
            "username_field": username_field,
            "password_field": password_field,
            "username_var": username_var,
            "password_var": password_var,
            "test_data_ref": ref,
        }
    return None


def extract_test_data_refs_from_markdown(content: str) -> list[str]:
    refs = TESTDATA_DIRECTIVE_RE.findall(content or "")
    frontmatter_match = TESTDATA_FRONTMATTER_RE.search(content or "")
    if frontmatter_match:
        refs.extend(_parse_refs_value(frontmatter_match.group(1)))
    return _dedupe_refs(refs)


def resolve_testdata_in_markdown(
    content: str,
    *,
    session: Session,
    project_id: str,
    include_frontmatter_refs: bool = True,
) -> str:
    directive_refs = TESTDATA_DIRECTIVE_RE.findall(content or "")

    def replace(match: re.Match[str]) -> str:
        ref = match.group(1)
        resolved = resolve_test_data_refs(
            session,
            project_id=project_id,
            refs=[ref],
            render_as="markdown",
            decrypt_sensitive=False,
        )
        if resolved["missing"]:
            return f"<!-- Test data not found: {ref} -->"
        return resolved.get("markdown") or ""

    resolved_content = TESTDATA_DIRECTIVE_RE.sub(replace, content or "")
    if include_frontmatter_refs:
        extra_refs = [
            ref
            for ref in extract_test_data_refs_from_markdown(content or "")
            if ref not in directive_refs
        ]
        if extra_refs:
            resolved = resolve_test_data_refs(
                session,
                project_id=project_id,
                refs=extra_refs,
                render_as="markdown",
                decrypt_sensitive=False,
            )
            if resolved.get("markdown"):
                resolved_content = (
                    f"{resolved_content.rstrip()}\n\n{resolved['markdown']}\n"
                )
    return resolved_content


def _item_payload(
    dataset: TestDataSet, item: TestDataItem, *, decrypt_sensitive: bool
) -> dict[str, Any]:
    data = deepcopy(item.data)
    text = item.data_text
    placeholders: dict[str, str] = {}
    secret_values: dict[str, Any] = {}
    for path in item.sensitive_fields:
        placeholder = _placeholder_ref(dataset.key, item.key, path)
        placeholders[path] = placeholder
        if path == SECRET_TEXT_PATH:
            if decrypt_sensitive:
                secret_values[path] = _decrypt_value(
                    item.encrypted_values.get(path, "")
                )
                text = secret_values[path]
            else:
                text = placeholder
            continue
        if data is not None:
            if decrypt_sensitive:
                secret_values[path] = _decrypt_value(
                    item.encrypted_values.get(path, "")
                )
                _set_path(data, path, secret_values[path])
            else:
                _set_path(data, path, placeholder)

    return {
        "dataset_id": dataset.id,
        "dataset_key": dataset.key,
        "dataset_name": dataset.name,
        "dataset_description": dataset.description,
        "item_id": item.id,
        "item_key": item.key,
        "name": item.name,
        "description": item.description,
        "format": item.format,
        "status": item.status,
        "data": data,
        "text": text,
        "sensitive_fields": item.sensitive_fields,
        "placeholders": placeholders,
        "secret_values": secret_values if decrypt_sensitive else {},
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
    }


def _json_context_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "data": payload.get("data"),
        "text": payload.get("text"),
        "format": payload.get("format"),
        "placeholders": payload.get("placeholders") or {},
        "sensitive_fields": payload.get("sensitive_fields") or [],
    }


def _encrypt_value(value: Any) -> str:
    return encrypt_credential(json.dumps({"value": value}, ensure_ascii=False))


def _decrypt_value(encrypted: str) -> Any:
    raw = decrypt_credential(encrypted)
    if not raw:
        return ""
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict) and "value" in parsed:
            return parsed["value"]
    except json.JSONDecodeError:
        pass
    return raw


def _placeholder(kind: str, path: str) -> str:
    del kind
    return f"{{{{TESTDATA_SECRET_{_safe_env(path)}}}}}"


def _placeholder_ref(dataset_key: str, item_key: str, path: str) -> str:
    return f"{{{{TESTDATA_{_safe_env(dataset_key)}_{_safe_env(item_key)}_{_safe_env(path)}}}}}"


def _safe_env(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_").upper()
    return cleaned or "VALUE"


def _dedupe_refs(refs: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for raw in refs or []:
        ref = str(raw or "").strip()
        if not ref or ref in seen:
            continue
        if not VALID_REF_RE.fullmatch(ref):
            continue
        result.append(ref)
        seen.add(ref)
    return result


def _parse_refs_value(raw: str) -> list[str]:
    value = raw.strip()
    try:
        parsed = ast.literal_eval(value)
        if isinstance(parsed, str):
            return [parsed]
        if isinstance(parsed, list):
            return [str(item) for item in parsed]
    except (SyntaxError, ValueError):
        pass
    return re.findall(r'"([^"]+)"', value)


def _first_present(data: dict[str, Any], keys: tuple[str, ...]) -> tuple[str, Any]:
    for key in keys:
        value = data.get(key)
        if value is not None and str(value) != "":
            return key, value
    return "", ""


def _flatten_scalar_paths(data: Any, prefix: str = "") -> dict[str, Any]:
    flattened: dict[str, Any] = {}
    if isinstance(data, dict):
        for key, value in data.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            flattened.update(_flatten_scalar_paths(value, path))
    elif isinstance(data, list):
        for index, value in enumerate(data):
            path = f"{prefix}[{index}]" if prefix else f"[{index}]"
            flattened.update(_flatten_scalar_paths(value, path))
    elif data is not None and prefix:
        flattened[prefix] = data
    return flattened


def _split_path(path: str) -> list[str | int]:
    parts: list[str | int] = []
    for part in path.split("."):
        match = re.fullmatch(r"([A-Za-z0-9_-]+)(?:\[(\d+)])?", part)
        if not match:
            parts.append(part)
            continue
        parts.append(match.group(1))
        if match.group(2) is not None:
            parts.append(int(match.group(2)))
    return parts


def _get_path(data: Any, path: str) -> tuple[bool, Any]:
    current = data
    for part in _split_path(path):
        if isinstance(part, int):
            if not isinstance(current, list) or part >= len(current):
                return False, None
            current = current[part]
        else:
            if not isinstance(current, dict) or part not in current:
                return False, None
            current = current[part]
    return True, current


def _set_path(data: Any, path: str, value: Any) -> bool:
    current = data
    parts = _split_path(path)
    for part in parts[:-1]:
        if isinstance(part, int):
            if not isinstance(current, list) or part >= len(current):
                return False
            current = current[part]
        else:
            if not isinstance(current, dict) or part not in current:
                return False
            current = current[part]
    leaf = parts[-1] if parts else None
    if isinstance(leaf, int):
        if not isinstance(current, list) or leaf >= len(current):
            return False
        current[leaf] = value
        return True
    if isinstance(current, dict) and isinstance(leaf, str):
        current[leaf] = value
        return True
    return False
