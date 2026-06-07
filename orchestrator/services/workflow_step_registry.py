"""Workflow step registry metadata and validation helpers."""

from __future__ import annotations

import copy
from datetime import datetime
from typing import Any

from jsonschema import Draft202012Validator
from sqlmodel import Session, select

from orchestrator.api.models_db import WorkflowStepType


def _object_schema(required: list[str], properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": True,
    }


STANDARD_OUTPUT_TOKENS = [
    "status",
    "external_kind",
    "external_id",
    "summary",
    "artifacts",
    "metrics",
    "structured_report",
]


def _token(path: str, label: str, type_: str = "string", description: str = "", nullable: bool = True) -> dict[str, Any]:
    return {"path": path, "label": label, "type": type_, "description": description, "nullable": nullable}


def _output_schema(extra_tokens: list[str] | None = None, extra_catalog: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    tokens = list(dict.fromkeys([*STANDARD_OUTPUT_TOKENS, *(extra_tokens or [])]))
    base_catalog = [
        _token("status", "Status", description="Step or child job status."),
        _token("external_kind", "External Kind", description="Linked child job type, when the step starts or waits for a child job."),
        _token("external_id", "External ID", description="Linked child job identifier."),
        _token("summary", "Summary", description="Human-readable result summary."),
        _token("artifacts", "Artifacts", "array", "Artifacts produced by the step."),
        _token("metrics", "Metrics", "object", "Numeric or structured metrics produced by the step."),
        _token("structured_report", "Structured Report", "object", "Structured report payload produced by the step."),
    ]
    known_paths = {item["path"] for item in base_catalog}
    for token in tokens:
        if token not in known_paths:
            base_catalog.append(_token(token, token.replace("_", " ").title()))
            known_paths.add(token)
    for item in extra_catalog or []:
        if item.get("path") not in known_paths:
            base_catalog.append(item)
            known_paths.add(str(item.get("path")))
    return {
        "contract_version": 1,
        "tokens": tokens,
        "token_catalog": base_catalog,
        "json_schema": {"type": "object"},
    }


def _auto_wait(timeout_seconds: int, poll_seconds: int = 10) -> dict[str, int]:
    return {"timeout_seconds": timeout_seconds, "poll_seconds": poll_seconds}


BUILTIN_STEP_TYPES: dict[str, dict[str, Any]] = {
    "start_autopilot": {
        "type": "start_autopilot",
        "version": 1,
        "label": "Start Auto Pilot",
        "description": "Start the existing Auto Pilot pipeline.",
        "category": "Discovery",
        "risk_level": "medium",
        "is_async": True,
        "auto_wait_defaults": _auto_wait(7200, 15),
        "required": ["entry_urls"],
        "default_input": {"entry_urls": ["https://example.com"], "max_interactions": 30, "max_specs": 10},
        "input_schema": _object_schema(
            ["entry_urls"],
            {
                "entry_urls": {"type": "array", "items": {"type": "string", "minLength": 1}, "minItems": 1},
                "max_interactions": {"type": "integer", "minimum": 1},
                "max_specs": {"type": "integer", "minimum": 1},
            },
        ),
        "ui_schema": {
            "fields": [
                {"key": "entry_urls", "label": "Entry URLs", "control": "string_list", "rows": 3, "placeholder": "https://example.com"},
                {"key": "max_interactions", "label": "Max interactions", "control": "number", "min": 1},
                {"key": "max_specs", "label": "Max specs", "control": "number", "min": 1},
            ]
        },
        "handler_kind": "builtin",
        "handler_config": {"action": "start_autopilot", "external_kind": "autopilot"},
        "output_schema": _output_schema(["session_id"]),
    },
    "start_exploration": {
        "type": "start_exploration",
        "version": 1,
        "label": "Start Exploration",
        "description": "Start an exploration session.",
        "category": "Discovery",
        "risk_level": "medium",
        "is_async": True,
        "auto_wait_defaults": _auto_wait(3600, 10),
        "required": ["entry_url"],
        "default_input": {"entry_url": "https://example.com", "max_interactions": 30},
        "input_schema": _object_schema(
            ["entry_url"],
            {
                "entry_url": {"type": "string", "minLength": 1},
                "max_interactions": {"type": "integer", "minimum": 1},
                "browser_auth_session_id": {"type": "string"},
                "use_project_default_browser_auth": {"type": "boolean"},
                "skip_browser_auth": {"type": "boolean"},
            },
        ),
        "ui_schema": {
            "fields": [
                {"key": "entry_url", "label": "Entry URL", "control": "text", "placeholder": "https://example.com"},
                {"key": "max_interactions", "label": "Max interactions", "control": "number", "min": 1},
                {"key": "browser_auth_session_id", "label": "Browser auth session", "control": "text", "placeholder": "Optional session ID"},
                {"key": "use_project_default_browser_auth", "label": "Use project default auth", "control": "boolean"},
                {"key": "skip_browser_auth", "label": "Skip browser auth", "control": "boolean"},
            ],
            "recommended_next_steps": [
                {
                    "type": "generate_requirements",
                    "label": "Add Generate Requirements",
                    "description": "Use this exploration output to draft requirements.",
                    "after_wait": True,
                }
            ],
        },
        "handler_kind": "builtin",
        "handler_config": {"action": "start_exploration", "external_kind": "exploration"},
        "output_schema": _output_schema(["session_id"]),
    },
    "generate_requirements": {
        "type": "generate_requirements",
        "version": 1,
        "label": "Generate Requirements",
        "description": "Generate requirements from an exploration session.",
        "category": "Generation",
        "risk_level": "low",
        "is_async": True,
        "auto_wait_defaults": _auto_wait(1800, 10),
        "required": ["exploration_session_id"],
        "default_input": {"exploration_session_id": ""},
        "input_schema": _object_schema(["exploration_session_id"], {"exploration_session_id": {"type": "string", "minLength": 1}}),
        "ui_schema": {
            "fields": [
                {
                    "key": "exploration_session_id",
                    "label": "Exploration session ID",
                    "control": "text",
                    "placeholder": "Use Start Exploration output",
                    "token_sources": ["start_exploration"],
                }
            ],
            "recommended_next_steps": [
                {
                    "type": "review_gate",
                    "label": "Add Review",
                    "description": "Pause for review before creating more coverage.",
                    "after_wait": True,
                }
            ],
        },
        "handler_kind": "builtin",
        "handler_config": {"action": "generate_requirements", "external_kind": "requirements_job"},
        "output_schema": _output_schema(["job_id"]),
    },
    "generate_specs_from_requirements": {
        "type": "generate_specs_from_requirements",
        "version": 1,
        "label": "Generate Specs From Requirements",
        "description": "Bulk-generate specs for uncovered requirements.",
        "category": "Generation",
        "risk_level": "low",
        "is_async": True,
        "auto_wait_defaults": _auto_wait(3600, 10),
        "required": ["target_url"],
        "default_input": {"target_url": "https://example.com"},
        "input_schema": _object_schema(
            ["target_url"],
            {
                "target_url": {"type": "string", "minLength": 1},
                "login_url": {"type": "string"},
            },
        ),
        "ui_schema": {
            "fields": [
                {"key": "target_url", "label": "Target URL", "control": "text", "placeholder": "https://example.com"},
                {"key": "login_url", "label": "Login URL", "control": "text", "placeholder": "Optional"},
            ]
        },
        "handler_kind": "builtin",
        "handler_config": {"action": "generate_specs_from_requirements", "external_kind": "bulk_specs_job"},
        "output_schema": _output_schema(["job_id"]),
    },
    "run_spec": {
        "type": "run_spec",
        "version": 1,
        "label": "Run Spec",
        "description": "Run one saved spec.",
        "category": "Execution",
        "risk_level": "medium",
        "is_async": True,
        "auto_wait_defaults": _auto_wait(1800, 10),
        "required": ["spec_name"],
        "default_input": {"spec_name": "examples/hello-world.md"},
        "input_schema": _object_schema(
            ["spec_name"],
            {
                "spec_name": {"type": "string", "minLength": 1},
                "browser_auth_session_id": {"type": "string"},
                "use_project_default_browser_auth": {"type": "boolean"},
                "skip_browser_auth": {"type": "boolean"},
            },
        ),
        "ui_schema": {
            "fields": [
                {"key": "spec_name", "label": "Spec name", "control": "text", "placeholder": "examples/hello-world.md"},
                {"key": "browser_auth_session_id", "label": "Browser auth session", "control": "text", "placeholder": "Optional session ID"},
                {"key": "use_project_default_browser_auth", "label": "Use project default auth", "control": "boolean"},
                {"key": "skip_browser_auth", "label": "Skip browser auth", "control": "boolean"},
            ],
            "recommended_next_steps": [
                {
                    "type": "review_gate",
                    "label": "Add Review",
                    "description": "Review the run result before continuing.",
                    "after_wait": True,
                }
            ],
        },
        "handler_kind": "builtin",
        "handler_config": {"action": "run_spec", "external_kind": "test_run"},
        "output_schema": _output_schema(["id"]),
    },
    "run_regression_batch": {
        "type": "run_regression_batch",
        "version": 1,
        "label": "Run Regression Batch",
        "description": "Run a regression batch.",
        "category": "Execution",
        "risk_level": "medium",
        "is_async": True,
        "auto_wait_defaults": _auto_wait(7200, 15),
        "required": [],
        "default_input": {"browser": "chromium", "automated_only": True},
        "input_schema": _object_schema(
            [],
            {
                "browser": {"type": "string", "enum": ["chromium", "firefox", "webkit"]},
                "max_iterations": {"type": "integer", "minimum": 1},
                "tags": {"type": "array", "items": {"type": "string"}},
                "spec_names": {"type": "array", "items": {"type": "string"}},
                "automated_only": {"type": "boolean"},
                "hybrid": {"type": "boolean"},
                "browser_auth_session_id": {"type": "string"},
                "use_project_default_browser_auth": {"type": "boolean"},
                "skip_browser_auth": {"type": "boolean"},
            },
        ),
        "ui_schema": {
            "fields": [
                {"key": "browser", "label": "Browser", "control": "select", "options": [{"label": "Chromium", "value": "chromium"}, {"label": "Firefox", "value": "firefox"}, {"label": "WebKit", "value": "webkit"}]},
                {"key": "max_iterations", "label": "Max iterations", "control": "number", "min": 1},
                {"key": "tags", "label": "Tags", "control": "string_list", "rows": 3, "placeholder": "smoke\nrelease"},
                {"key": "spec_names", "label": "Spec names", "control": "string_list", "rows": 3, "placeholder": "examples/hello-world.md"},
                {"key": "automated_only", "label": "Automated specs only", "control": "boolean"},
                {"key": "hybrid", "label": "Hybrid healing", "control": "boolean"},
                {"key": "browser_auth_session_id", "label": "Browser auth session", "control": "text", "placeholder": "Optional session ID"},
                {"key": "use_project_default_browser_auth", "label": "Use project default auth", "control": "boolean"},
                {"key": "skip_browser_auth", "label": "Skip browser auth", "control": "boolean"},
            ],
            "recommended_next_steps": [
                {
                    "type": "review_gate",
                    "label": "Add Review",
                    "description": "Review regression results before release decisions.",
                    "after_wait": True,
                }
            ],
        },
        "handler_kind": "builtin",
        "handler_config": {"action": "run_regression_batch", "external_kind": "regression_batch"},
        "output_schema": _output_schema(["batch_id"]),
    },
    "start_custom_agent": {
        "type": "start_custom_agent",
        "version": 1,
        "label": "Start Custom Agent",
        "description": "Start a saved custom agent definition.",
        "category": "Agent",
        "risk_level": "high",
        "is_async": True,
        "auto_wait_defaults": _auto_wait(3600, 10),
        "required": ["definition_id", "prompt"],
        "default_input": {"definition_id": "", "prompt": "Inspect the target and report findings."},
        "input_schema": _object_schema(
            ["definition_id", "prompt"],
            {
                "definition_id": {"type": "string", "minLength": 1},
                "prompt": {"type": "string", "minLength": 1},
                "url": {"type": "string"},
                "config": {"type": "object"},
            },
        ),
        "ui_schema": {
            "fields": [
                {"key": "definition_id", "label": "Agent", "control": "agent_definition"},
                {"key": "url", "label": "Target URL", "control": "text", "placeholder": "Optional"},
                {"key": "prompt", "label": "Prompt", "control": "textarea", "rows": 4, "tokens": True},
            ],
            "recommended_next_steps": [
                {
                    "type": "review_gate",
                    "label": "Add Review",
                    "description": "Review the agent report before continuing.",
                    "after_wait": True,
                }
            ],
        },
        "handler_kind": "agent_run",
        "handler_config": {"external_kind": "agent_run"},
        "output_schema": _output_schema(
            ["findings", "test_ideas"],
            [
                _token("findings", "Findings", "array", "Findings extracted from the custom agent report."),
                _token("test_ideas", "Test Ideas", "array", "Test ideas extracted from the custom agent report."),
                _token("structured_report.findings", "Structured Findings", "array", "Findings inside the structured report."),
                _token("structured_report.test_ideas", "Structured Test Ideas", "array", "Test ideas inside the structured report."),
            ],
        ),
    },
    "wait_for_status": {
        "type": "wait_for_status",
        "version": 1,
        "label": "Wait For Status",
        "description": "Wait for a previously started child job to finish.",
        "category": "Utility",
        "risk_level": "low",
        "is_async": False,
        "required": ["source_step"],
        "default_input": {"source_step": "", "timeout_seconds": 3600, "poll_seconds": 10},
        "input_schema": _object_schema(
            ["source_step"],
            {
                "source_step": {"type": "string", "minLength": 1},
                "timeout_seconds": {"type": "integer", "minimum": 1},
                "poll_seconds": {"type": "integer", "minimum": 1},
            },
        ),
        "ui_schema": {
            "fields": [
                {"key": "source_step", "label": "Source step", "control": "source_step"},
                {"key": "timeout_seconds", "label": "Timeout seconds", "control": "number", "min": 1},
                {"key": "poll_seconds", "label": "Poll seconds", "control": "number", "min": 1},
            ]
        },
        "handler_kind": "wait_for_status",
        "handler_config": {},
        "output_schema": _output_schema(
            ["result", "findings", "test_ideas"],
            [
                _token("result", "Child Result", "object", "Raw child job status response."),
                _token("findings", "Findings", "array", "Findings extracted from an agent child job."),
                _token("test_ideas", "Test Ideas", "array", "Test ideas extracted from an agent child job."),
                _token("structured_report.findings", "Structured Findings", "array", "Findings inside an agent structured report."),
                _token("structured_report.test_ideas", "Structured Test Ideas", "array", "Test ideas inside an agent structured report."),
            ],
        ),
    },
    "review_gate": {
        "type": "review_gate",
        "version": 1,
        "label": "Review Gate",
        "description": "Pause until the user resumes the workflow.",
        "category": "Review",
        "risk_level": "low",
        "is_async": False,
        "required": ["question"],
        "default_input": {"question": "Review the current workflow state before continuing."},
        "input_schema": _object_schema(
            ["question"],
            {
                "question": {"type": "string", "minLength": 1},
                "suggested_answers": {"type": "array", "items": {"type": "string"}},
            },
        ),
        "ui_schema": {
            "fields": [
                {"key": "question", "label": "Review prompt", "control": "textarea", "rows": 3},
                {"key": "suggested_answers", "label": "Suggested answers", "control": "string_list", "rows": 2, "placeholder": "Continue\nRevise first"},
            ]
        },
        "handler_kind": "review_gate",
        "handler_config": {},
        "output_schema": _output_schema(["question", "suggested_answers"]),
    },
    "materialize_agent_report": {
        "type": "materialize_agent_report",
        "version": 1,
        "label": "Materialize Agent Report",
        "description": "Create candidate requirements and/or markdown specs from a completed custom agent report.",
        "category": "Generation",
        "risk_level": "medium",
        "is_async": False,
        "required": ["source_step"],
        "default_input": {
            "source_step": "wait_agent",
            "mode": "both",
            "max_items": 10,
            "priority_threshold": "medium",
        },
        "input_schema": _object_schema(
            ["source_step"],
            {
                "source_step": {"type": "string", "minLength": 1},
                "mode": {"type": "string", "enum": ["requirements", "specs", "both"]},
                "max_items": {"type": "integer", "minimum": 1, "maximum": 50},
                "priority_threshold": {"type": "string", "enum": ["critical", "high", "medium", "low", "info"]},
            },
        ),
        "ui_schema": {
            "fields": [
                {"key": "source_step", "label": "Agent report step", "control": "source_step"},
                {
                    "key": "mode",
                    "label": "Create",
                    "control": "select",
                    "options": [
                        {"label": "Requirements and specs", "value": "both"},
                        {"label": "Requirements only", "value": "requirements"},
                        {"label": "Specs only", "value": "specs"},
                    ],
                },
                {"key": "max_items", "label": "Max items", "control": "number", "min": 1, "max": 50},
                {
                    "key": "priority_threshold",
                    "label": "Minimum priority",
                    "control": "select",
                    "options": [
                        {"label": "Critical", "value": "critical"},
                        {"label": "High", "value": "high"},
                        {"label": "Medium", "value": "medium"},
                        {"label": "Low", "value": "low"},
                        {"label": "Info", "value": "info"},
                    ],
                },
            ]
        },
        "handler_kind": "materialize_agent_report",
        "handler_config": {"action": "materialize_agent_report"},
        "output_schema": _output_schema(
            ["created_requirements", "created_specs", "skipped_items"],
            [
                _token("created_requirements", "Created Requirements", "array", "Candidate requirements created from the agent report."),
                _token("created_specs", "Created Specs", "array", "Markdown specs created from the agent report."),
                _token("skipped_items", "Skipped Items", "array", "Report items skipped because of duplicates or validation issues."),
            ],
        ),
    },
}


WORKFLOW_TEMPLATES: list[dict[str, Any]] = [
    {
        "id": "autopilot-smoke-review",
        "name": "AutoPilot Smoke Review",
        "description": "Explore a target URL, generate candidate specs, then pause for human review.",
        "useCase": "Fast application smoke coverage",
        "steps": [
            {"key": "autopilot", "type": "start_autopilot", "label": "Run AutoPilot", "input": BUILTIN_STEP_TYPES["start_autopilot"]["default_input"]},
            {"key": "wait_autopilot", "type": "wait_for_status", "label": "Wait for AutoPilot", "input": {"source_step": "autopilot", "timeout_seconds": 7200, "poll_seconds": 15}},
            {"key": "review", "type": "review_gate", "label": "Review Results", "input": BUILTIN_STEP_TYPES["review_gate"]["default_input"]},
        ],
    },
    {
        "id": "custom-agent-review",
        "name": "Custom Agent Review",
        "description": "Run a saved custom agent, wait for its structured report, then pause for review.",
        "useCase": "Configurable agent task",
        "steps": [
            {"key": "agent", "type": "start_custom_agent", "label": "Run Custom Agent", "input": BUILTIN_STEP_TYPES["start_custom_agent"]["default_input"]},
            {"key": "wait_agent", "type": "wait_for_status", "label": "Wait for Agent", "input": {"source_step": "agent", "timeout_seconds": 3600, "poll_seconds": 10}},
            {"key": "review", "type": "review_gate", "label": "Review Agent Report", "input": {"question": "Review the custom agent report before continuing.", "suggested_answers": ["Accept", "Revise agent prompt"]}},
        ],
    },
    {
        "id": "agent-to-requirements-specs",
        "name": "Agent To Requirements And Specs",
        "description": "Run a saved custom agent, review its report, then create candidate requirements and markdown specs.",
        "useCase": "Chat-created QA workflow",
        "steps": [
            {
                "key": "agent",
                "type": "start_custom_agent",
                "label": "Run Custom Agent",
                "input": {
                    "definition_id": "{{inputs.agent_definition_id}}",
                    "url": "{{inputs.target_url}}",
                    "prompt": "Inspect the target app area, capture observed requirements, findings, evidence, and test ideas.",
                },
            },
            {"key": "wait_agent", "type": "wait_for_status", "label": "Wait for Agent", "input": {"source_step": "agent", "timeout_seconds": 3600, "poll_seconds": 10}},
            {"key": "review_agent", "type": "review_gate", "label": "Review Agent Report", "input": {"question": "Review the custom agent report before creating requirements and specs.", "suggested_answers": ["Create requirements and specs", "Revise agent prompt"]}},
            {"key": "materialize", "type": "materialize_agent_report", "label": "Create Requirements And Specs", "input": {"source_step": "wait_agent", "mode": "both", "max_items": 10, "priority_threshold": "medium"}},
            {"key": "review_output", "type": "review_gate", "label": "Review Created Artifacts", "input": {"question": "Review the created requirements and specs before running tests.", "suggested_answers": ["Accept", "Edit artifacts first"]}},
        ],
        "variables": [
            {"key": "agent_definition_id", "label": "Custom agent definition ID", "required": True},
            {"key": "target_url", "label": "Target URL", "required": False},
        ],
    },
    {
        "id": "explore-requirements-review",
        "name": "Explore Requirements Review",
        "description": "Run exploration, wait for completion, generate requirements, then review the generated coverage.",
        "useCase": "Discovery into requirements",
        "steps": [
            {"key": "explore", "type": "start_exploration", "label": "Explore Application", "input": BUILTIN_STEP_TYPES["start_exploration"]["default_input"]},
            {"key": "wait_explore", "type": "wait_for_status", "label": "Wait for Exploration", "input": {"source_step": "explore", "timeout_seconds": 3600, "poll_seconds": 10}},
            {"key": "requirements", "type": "generate_requirements", "label": "Generate Requirements", "input": {"exploration_session_id": "{{steps.explore.external_id}}"}},
            {"key": "wait_requirements", "type": "wait_for_status", "label": "Wait for Requirements", "input": {"source_step": "requirements", "timeout_seconds": 1800, "poll_seconds": 10}},
            {"key": "review", "type": "review_gate", "label": "Review Requirements", "input": {"question": "Review the generated requirements before generating specs.", "suggested_answers": ["Continue", "Revise requirements"]}},
        ],
    },
    {
        "id": "requirements-to-specs",
        "name": "Requirements To Specs",
        "description": "Generate specs for uncovered requirements, wait for the job, then review the result.",
        "useCase": "Turn requirements into test specs",
        "steps": [
            {"key": "bulk_specs", "type": "generate_specs_from_requirements", "label": "Generate Specs", "input": BUILTIN_STEP_TYPES["generate_specs_from_requirements"]["default_input"]},
            {"key": "wait_specs", "type": "wait_for_status", "label": "Wait for Spec Generation", "input": {"source_step": "bulk_specs", "timeout_seconds": 3600, "poll_seconds": 10}},
            {"key": "review", "type": "review_gate", "label": "Review Generated Specs", "input": {"question": "Review the generated specs before running them.", "suggested_answers": ["Run regression", "Edit specs first"]}},
        ],
    },
    {
        "id": "single-spec-smoke",
        "name": "Single Spec Smoke Run",
        "description": "Run one saved spec, wait for the test run, then review the outcome.",
        "useCase": "Validate a focused flow",
        "steps": [
            {"key": "spec_run", "type": "run_spec", "label": "Run Spec", "input": BUILTIN_STEP_TYPES["run_spec"]["default_input"]},
            {"key": "wait_spec_run", "type": "wait_for_status", "label": "Wait for Spec Run", "input": {"source_step": "spec_run", "timeout_seconds": 1800, "poll_seconds": 10}},
            {"key": "review", "type": "review_gate", "label": "Review Run Result", "input": {"question": "Review the spec run result before continuing.", "suggested_answers": ["Accept", "Retry after edits"]}},
        ],
    },
    {
        "id": "regression-review",
        "name": "Spec Or Regression Review",
        "description": "Run an automated regression batch and pause when the batch status is available.",
        "useCase": "Reusable spec or release regression",
        "steps": [
            {"key": "regression", "type": "run_regression_batch", "label": "Run Regression Batch", "input": BUILTIN_STEP_TYPES["run_regression_batch"]["default_input"]},
            {"key": "wait_regression", "type": "wait_for_status", "label": "Wait for Regression", "input": {"source_step": "regression", "timeout_seconds": 7200, "poll_seconds": 15}},
            {"key": "review", "type": "review_gate", "label": "Review Regression", "input": {"question": "Review the regression result before release decisions.", "suggested_answers": ["Release", "Investigate failures"]}},
        ],
    },
]

for order, template in enumerate(WORKFLOW_TEMPLATES, start=1):
    step_types = [str(step.get("type")) for step in template.get("steps", [])]
    categories = [
        str(BUILTIN_STEP_TYPES.get(step_type, {}).get("category") or "Utility")
        for step_type in step_types
        if step_type in BUILTIN_STEP_TYPES
    ]
    risks = [
        str(BUILTIN_STEP_TYPES.get(step_type, {}).get("risk_level") or "low")
        for step_type in step_types
        if step_type in BUILTIN_STEP_TYPES
    ]
    risk_order = {"low": 0, "medium": 1, "high": 2, "destructive": 3}
    template.setdefault("category", categories[0] if categories else "Utility")
    template.setdefault("tags", sorted(set(category.lower() for category in categories)))
    template.setdefault("risk_level", max(risks or ["low"], key=lambda risk: risk_order.get(risk, 0)))
    template.setdefault("estimated_duration_minutes", max(5, len(template.get("steps", [])) * 5))
    template.setdefault("requires", [])
    template.setdefault("variables", [])
    template.setdefault("step_types", step_types)
    template.setdefault("sort_order", order)
    template.setdefault("updated_at", "2026-05-20T00:00:00Z")


def sync_builtin_workflow_step_types(session: Session) -> list[WorkflowStepType]:
    now = datetime.utcnow()
    for metadata in BUILTIN_STEP_TYPES.values():
        existing = session.exec(
            select(WorkflowStepType).where(
                WorkflowStepType.project_id == None,
                WorkflowStepType.type == metadata["type"],
                WorkflowStepType.version == metadata["version"],
            )
        ).first()
        step_type = existing or WorkflowStepType(
            project_id=None,
            type=metadata["type"],
            version=metadata["version"],
            label=metadata["label"],
        )
        step_type.label = metadata["label"]
        step_type.description = metadata.get("description", "")
        step_type.required = list(metadata.get("required") or [])
        step_type.input_schema = copy.deepcopy(metadata.get("input_schema") or {})
        step_type.ui_schema = copy.deepcopy(metadata.get("ui_schema") or {})
        step_type.output_schema = copy.deepcopy(metadata.get("output_schema") or {})
        step_type.default_input = copy.deepcopy(metadata.get("default_input") or {})
        step_type.category = metadata.get("category") or "Utility"
        step_type.risk_level = metadata.get("risk_level") or "low"
        step_type.is_async = bool(metadata.get("is_async", False))
        step_type.auto_wait_defaults = copy.deepcopy(metadata.get("auto_wait_defaults") or {})
        step_type.handler_kind = metadata.get("handler_kind") or "builtin"
        step_type.handler_config = copy.deepcopy(metadata.get("handler_config") or {})
        step_type.status = "active"
        step_type.updated_at = now
        session.add(step_type)
    session.commit()
    return list_workflow_step_types(session)


def list_workflow_step_types(session: Session | None = None, project_id: str | None = None) -> list[dict[str, Any]]:
    if session is None:
        return [serialize_step_type(metadata) for metadata in BUILTIN_STEP_TYPES.values()]
    sync_required = not session.exec(select(WorkflowStepType).limit(1)).first()
    if sync_required:
        sync_builtin_workflow_step_types(session)
    stmt = select(WorkflowStepType).where(WorkflowStepType.status == "active").order_by(WorkflowStepType.label)
    rows = session.exec(stmt).all()
    if project_id == "default":
        rows = [row for row in rows if row.project_id in (None, "default")]
    elif project_id:
        rows = [row for row in rows if row.project_id in (None, project_id)]
    else:
        rows = [row for row in rows if row.project_id is None]
    latest: dict[str, WorkflowStepType] = {}
    for row in rows:
        current = latest.get(row.type)
        if not current or row.version > current.version or (row.project_id and not current.project_id):
            latest[row.type] = row
    return [serialize_step_type(row) for row in latest.values()]


def get_step_type_metadata(step_type: str, session: Session | None = None, project_id: str | None = None) -> dict[str, Any] | None:
    if session is None:
        metadata = BUILTIN_STEP_TYPES.get(step_type)
        return serialize_step_type(metadata) if metadata else None
    for item in list_workflow_step_types(session, project_id):
        if item["type"] == step_type:
            return item
    return None


def serialize_step_type(value: WorkflowStepType | dict[str, Any]) -> dict[str, Any]:
    if isinstance(value, WorkflowStepType):
        return {
            "type": value.type,
            "version": value.version,
            "label": value.label,
            "description": value.description,
            "required": value.required,
            "input_schema": value.input_schema,
            "ui_schema": value.ui_schema,
            "output_schema": value.output_schema,
            "default_input": value.default_input,
            "category": value.category,
            "risk_level": value.risk_level,
            "is_async": value.is_async,
            "auto_wait_defaults": value.auto_wait_defaults,
            "handler_kind": value.handler_kind,
            "handler_config": value.handler_config,
            "status": value.status,
            "project_id": value.project_id,
        }
    return copy.deepcopy(value)


def validate_input_schema(step_key: str, metadata: dict[str, Any], inputs: dict[str, Any]) -> None:
    schema = metadata.get("input_schema") or {}
    if not schema:
        return
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(inputs), key=lambda error: list(error.path))
    if errors:
        error = errors[0]
        field = ".".join(str(part) for part in error.path) or step_key
        raise ValueError(f"Step {step_key} input invalid at {field}: {error.message}")
