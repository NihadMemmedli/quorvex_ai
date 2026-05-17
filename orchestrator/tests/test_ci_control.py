import os
import sys
import types
import asyncio

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-ci-control-tests")

slowapi = types.ModuleType("slowapi")
slowapi_errors = types.ModuleType("slowapi.errors")
slowapi_util = types.ModuleType("slowapi.util")


class _Limiter:
    def __init__(self, *args, **kwargs):
        self._storage = types.SimpleNamespace(expirations={})


class _RateLimitExceeded(Exception):
    retry_after = 60


slowapi.Limiter = _Limiter
slowapi_errors.RateLimitExceeded = _RateLimitExceeded
slowapi_util.get_remote_address = lambda request: "test-client"
sys.modules.setdefault("slowapi", slowapi)
sys.modules.setdefault("slowapi.errors", slowapi_errors)
sys.modules.setdefault("slowapi.util", slowapi_util)

from orchestrator.api.ci_control import (
    WorkflowGenerateRequest,
    _action_availability,
    _provider_setup,
    _safe_branch_segment,
    _serialize_workflow_change,
    _validate_workflow_request,
    _render_github_workflow,
    _validate_workflow_yaml,
)
from orchestrator.api.gitlab_ci import GitlabConfigRequest
from orchestrator.api.models_db import CiPipelineMapping, CiWorkflowChangeRequest
from orchestrator.services.github_client import GithubClient


def test_github_workflow_generation_uses_safe_defaults():
    request = WorkflowGenerateRequest(
        workflow_name="Quorvex PR Quality Gate",
        template="pr-quality-gate",
        branches=["main", "release"],
    )

    path, yaml = _render_github_workflow(request)
    errors, warnings = _validate_workflow_yaml(yaml)

    assert path == ".github/workflows/quorvex-pr-quality-gate.yml"
    assert "pull_request_target" not in yaml
    assert "permissions:" in yaml
    assert "statuses: write" in yaml
    assert "pull-requests: write" in yaml
    assert errors == []
    assert warnings == []


def test_workflow_validation_blocks_dangerous_patterns():
    yaml = """
name: unsafe
on: pull_request_target
jobs:
  bad:
    runs-on: ubuntu-latest
    steps:
      - run: curl https://example.test/install.sh | sh
"""

    errors, _warnings = _validate_workflow_yaml(yaml)

    assert any("pull_request_target" in error for error in errors)
    assert any("Pipe-to-shell" in error for error in errors)
    assert any("minimal permissions" in error for error in errors)


def test_workflow_request_validation_blocks_identifier_injection():
    request = WorkflowGenerateRequest(
        workflow_name="Bad\nName",
        api_token_secret="TOKEN }}\n- run: echo bad",
        branches=["main", "bad branch"],
    )

    errors = _validate_workflow_request(request)

    assert any("single line" in error for error in errors)
    assert any("api_token_secret" in error for error in errors)
    assert any("unsupported characters" in error for error in errors)


def test_gitlab_config_accepts_legacy_gitlab_url_alias():
    request = GitlabConfigRequest(gitlab_url="https://gitlab.example.com", token="glpat-test")

    assert request.base_url is None
    assert request.gitlab_url == "https://gitlab.example.com"


def test_action_availability_explains_pending_provider_run_id():
    mapping = CiPipelineMapping(
        project_id="project-1",
        provider="github",
        external_pipeline_id="pending-workflow-main",
        status="pending",
    )

    availability = _action_availability(mapping)

    assert availability["can_open_details"] is True
    assert availability["can_cancel"] is False
    assert availability["can_rerun"] is False
    assert availability["can_fetch_logs"] is False
    assert "Provider run ID" in availability["disabled_reason"]


def test_action_availability_allows_failed_github_rerun_failed_only():
    mapping = CiPipelineMapping(
        project_id="project-1",
        provider="github",
        external_pipeline_id="12345",
        external_url="https://github.example/run",
        status="failed",
    )

    availability = _action_availability(mapping)

    assert availability["can_open_provider"] is True
    assert availability["can_rerun"] is True
    assert availability["can_rerun_failed"] is True
    assert availability["can_cancel"] is False


def test_provider_setup_recommends_workflow_generation_for_github_without_default_workflow():
    class _Session:
        def exec(self, _stmt):
            return self

        def first(self):
            return None

    setup = _provider_setup(
        provider="github",
        config={"owner": "acme", "repo": "app", "default_ref": "main"},
        session=_Session(),
        project_id="project-1",
    )

    assert setup["setup_status"] == "needs_workflow"
    assert "select_or_generate_workflow" in setup["missing_requirements"]
    assert setup["recommended_next_action"]["action"] == "generate_workflow"


def test_workflow_change_can_open_pr_when_github_ready_and_yaml_valid():
    change = CiWorkflowChangeRequest(
        project_id="project-1",
        provider="github",
        workflow_name="Quorvex PR Quality Gate",
        workflow_path=".github/workflows/quorvex-pr-quality-gate.yml",
        generated_yaml="name: ci\npermissions:\n  contents: read\n",
        validation_errors=[],
        validation_warnings=[],
    )

    payload = _serialize_workflow_change(change, {"owner": "acme", "repo": "app"})

    assert payload["can_open_pr"] is True
    assert payload["install_status"] == "draft"
    assert "Open a draft pull request from Quorvex." in payload["next_actions"]


def test_workflow_change_cannot_open_pr_with_validation_errors():
    change = CiWorkflowChangeRequest(
        project_id="project-1",
        provider="github",
        workflow_name="Unsafe",
        workflow_path=".github/workflows/unsafe.yml",
        generated_yaml="name: unsafe\n",
        validation_errors=["Generated workflow must declare minimal permissions."],
        validation_warnings=[],
    )

    payload = _serialize_workflow_change(change, {"owner": "acme", "repo": "app"})

    assert payload["can_open_pr"] is False


def test_safe_branch_segment_normalizes_generated_branch_names():
    assert _safe_branch_segment("Quorvex CI: PR Quality Gate!") == "quorvex-ci-pr-quality-gate"
    assert _safe_branch_segment("quorvex//ci///workflow") == "quorvex/ci/workflow"


def test_github_client_create_or_update_file_encodes_content_and_sha():
    client = GithubClient("token")
    calls = []

    async def fake_request(method, endpoint, json=None, params=None):
        calls.append((method, endpoint, json, params))
        return {"commit": {"sha": "commit-sha"}}

    client._request = fake_request  # type: ignore[method-assign]

    result = asyncio.run(
        client.create_or_update_file(
            "acme",
            "app",
            ".github/workflows/ci.yml",
            content="name: ci\n",
            message="Add CI workflow",
            branch="quorvex/ci",
            sha="file-sha",
        )
    )

    assert result["commit"]["sha"] == "commit-sha"
    method, endpoint, payload, _params = calls[0]
    assert method == "PUT"
    assert endpoint == "repos/acme/app/contents/.github/workflows/ci.yml"
    assert payload["branch"] == "quorvex/ci"
    assert payload["sha"] == "file-sha"
    assert payload["content"] == "bmFtZTogY2kK"


def test_github_client_create_pull_request_sends_draft_flag():
    client = GithubClient("token")
    calls = []

    async def fake_request(method, endpoint, json=None, params=None):
        calls.append((method, endpoint, json, params))
        return {"number": 7, "html_url": "https://github.example/pull/7"}

    client._request = fake_request  # type: ignore[method-assign]

    result = asyncio.run(
        client.create_pull_request(
            "acme",
            "app",
            title="Add workflow",
            head="quorvex/ci",
            base="main",
            body="Generated by Quorvex",
            draft=True,
        )
    )

    assert result["number"] == 7
    method, endpoint, payload, _params = calls[0]
    assert method == "POST"
    assert endpoint == "repos/acme/app/pulls"
    assert payload["draft"] is True


def test_github_client_list_pull_requests_filters_by_head_and_base():
    client = GithubClient("token")
    calls = []

    async def fake_request(method, endpoint, json=None, params=None):
        calls.append((method, endpoint, json, params))
        return [{"number": 7}]

    client._request = fake_request  # type: ignore[method-assign]

    result = asyncio.run(client.list_pull_requests("acme", "app", head="acme:quorvex/ci", base="main"))

    assert result == [{"number": 7}]
    method, endpoint, _payload, params = calls[0]
    assert method == "GET"
    assert endpoint == "repos/acme/app/pulls"
    assert params["state"] == "open"
    assert params["head"] == "acme:quorvex/ci"
    assert params["base"] == "main"
