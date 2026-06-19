"""Standard output contract helpers for custom workflow steps."""

from __future__ import annotations

import copy
from typing import Any

from jsonschema import Draft202012Validator

STANDARD_OUTPUT_CONTRACT_VERSION = 1

STANDARD_OUTPUT_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "contract_version": {"type": "integer"},
        "status": {"type": ["string", "null"]},
        "external_kind": {"type": ["string", "null"]},
        "external_id": {"type": ["string", "null"]},
        "summary": {"type": ["string", "null"]},
        "artifacts": {"type": "array"},
        "metrics": {"type": "object"},
        "structured_report": {},
        "diagnostics": {"type": "object"},
        "data": {"type": "object"},
        "raw": {},
    },
    "required": ["contract_version", "status", "artifacts", "metrics", "diagnostics", "data"],
    "additionalProperties": True,
}


def normalize_step_output(
    raw: dict[str, Any] | None,
    *,
    status: str | None = None,
    external_kind: str | None = None,
    external_id: str | None = None,
    summary: str | None = None,
) -> dict[str, Any]:
    """Return a workflow output envelope while preserving legacy top-level keys."""
    payload = copy.deepcopy(raw or {})
    diagnostics = payload.get("diagnostics") if isinstance(payload.get("diagnostics"), dict) else {}
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    raw_payload = payload.get("raw") if "raw" in payload else copy.deepcopy(payload)

    normalized: dict[str, Any] = {
        "contract_version": STANDARD_OUTPUT_CONTRACT_VERSION,
        "status": status or payload.get("status") or "completed",
        "external_kind": external_kind if external_kind is not None else payload.get("external_kind"),
        "external_id": external_id if external_id is not None else payload.get("external_id"),
        "summary": summary if summary is not None else payload.get("summary"),
        "artifacts": payload.get("artifacts") if isinstance(payload.get("artifacts"), list) else [],
        "metrics": payload.get("metrics") if isinstance(payload.get("metrics"), dict) else {},
        "structured_report": payload.get("structured_report"),
        "diagnostics": {
            "child_status": diagnostics.get("child_status") or payload.get("child_status"),
            "warnings": diagnostics.get("warnings") if isinstance(diagnostics.get("warnings"), list) else [],
            "error_message": diagnostics.get("error_message") or payload.get("error_message"),
        },
        "data": data,
        "raw": raw_payload,
    }
    # Preserve existing token paths and child response shape for saved workflows
    # and downstream references that predate the formal output contract.
    normalized.update(payload)
    for key, value in normalized.items():
        if key not in payload:
            payload[key] = value
    return payload


def validate_output_contract(output: dict[str, Any] | None) -> list[str]:
    validator = Draft202012Validator(STANDARD_OUTPUT_JSON_SCHEMA)
    errors = sorted(validator.iter_errors(output or {}), key=lambda error: list(error.path))
    return [
        f"{'.'.join(str(part) for part in error.path) or 'output'}: {error.message}"
        for error in errors
    ]
