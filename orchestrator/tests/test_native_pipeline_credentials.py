import json
import logging
import os
import sys
from pathlib import Path

import pytest
from sqlmodel import SQLModel, Session, create_engine

os.environ.setdefault(
    "JWT_SECRET_KEY", "test-secret-key-for-native-pipeline-credentials"
)

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from orchestrator.api.models_db import Project, TestDataItem, TestDataSet
from orchestrator.services.test_data_resolver import prepare_test_data_item_storage
from orchestrator.workflows.full_native_pipeline import FullNativePipeline


def test_extract_credentials_keeps_env_placeholder_fallback(monkeypatch):
    pipeline = object.__new__(FullNativePipeline)
    pipeline.project_id = "project-1"
    monkeypatch.setattr(
        pipeline, "_extract_testdata_credentials", lambda _content: None
    )
    monkeypatch.setenv("LOGIN_USERNAME", "user@example.com")
    monkeypatch.setenv("LOGIN_PASSWORD", "env-secret")

    credentials = pipeline._extract_credentials(
        'Enter "{{LOGIN_USERNAME}}" into email\nEnter "{{LOGIN_PASSWORD}}" into password'
    )

    assert credentials == {
        "username": "user@example.com",
        "username_var": "LOGIN_USERNAME",
        "password": "env-secret",
        "password_var": "LOGIN_PASSWORD",
    }


def test_extract_credentials_loads_decrypted_testdata_into_transient_env(
    monkeypatch, tmp_path
):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'native-credentials.db'}",
        echo=False,
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Project(id="project-1", name="Project One"))
        dataset = TestDataSet(
            project_id="project-1", key="wetravel-auth", name="Wetravel Auth"
        )
        session.add(dataset)
        session.flush()
        storage = prepare_test_data_item_storage(
            data={
                "username": "farxad2026@mailinator.com",
                "email": "farxad2026@mailinator.com",
                "password": "secret-pass",
            },
            sensitive_fields=["password"],
        )
        item = TestDataItem(
            dataset_id=dataset.id,
            key="valid-user",
            name="Valid user",
            data_text=storage["text"],
        )
        item.data = storage["data"]
        item.sensitive_fields = storage["sensitive_fields"]
        item.encrypted_values = storage["encrypted_values"]
        session.add(item)
        session.commit()

    monkeypatch.setattr("orchestrator.api.db.engine", engine)
    monkeypatch.delenv("TESTDATA_WETRAVEL_AUTH_VALID_USER_PASSWORD", raising=False)

    pipeline = object.__new__(FullNativePipeline)
    pipeline.project_id = "project-1"

    credentials = pipeline._extract_credentials('@testdata "wetravel-auth.valid-user"')

    assert credentials == {
        "username": "farxad2026@mailinator.com",
        "password": "secret-pass",
        "username_field": "username",
        "password_field": "password",
        "username_var": "TESTDATA_WETRAVEL_AUTH_VALID_USER_USERNAME",
        "password_var": "TESTDATA_WETRAVEL_AUTH_VALID_USER_PASSWORD",
        "test_data_ref": "wetravel-auth.valid-user",
    }
    assert "TESTDATA_WETRAVEL_AUTH_VALID_USER_USERNAME" not in os.environ
    assert "TESTDATA_WETRAVEL_AUTH_VALID_USER_PASSWORD" not in os.environ


def test_agent_runner_queue_env_collection_ignores_dynamic_testdata(monkeypatch):
    from orchestrator.utils.agent_runner import AgentRunner

    monkeypatch.setenv("TESTDATA_WETRAVEL_AUTH_VALID_USER_USERNAME", "user@example.com")
    monkeypatch.setenv("TESTDATA_WETRAVEL_AUTH_VALID_USER_PASSWORD", "secret-pass")

    runner = AgentRunner()
    env_vars = runner._collect_api_env_vars()

    assert "TESTDATA_WETRAVEL_AUTH_VALID_USER_USERNAME" not in env_vars
    assert "TESTDATA_WETRAVEL_AUTH_VALID_USER_PASSWORD" not in env_vars


def test_agent_runner_queue_env_collection_filters_explicit_testdata(monkeypatch):
    from orchestrator.utils.agent_runner import AgentRunner

    monkeypatch.setenv(
        "TESTDATA_WETRAVEL_AUTH_VALID_USER_USERNAME", "stale@example.com"
    )

    runner = AgentRunner(
        env_vars={"TESTDATA_WETRAVEL_AUTH_VALID_USER_USERNAME": "explicit@example.com"}
    )
    env_vars = runner._collect_api_env_vars()

    assert "TESTDATA_WETRAVEL_AUTH_VALID_USER_USERNAME" not in env_vars


def test_agent_runner_queue_env_collection_includes_runtime_fixture_file(monkeypatch, tmp_path):
    from orchestrator.utils.agent_runner import AgentRunner

    fixture_file = tmp_path / "resolved-fixtures.json"
    fixture_file.write_text("{}")
    monkeypatch.setenv("QUORVEX_TEST_DATA_FILE", str(fixture_file))

    runner = AgentRunner()
    env_vars = runner._collect_api_env_vars()

    assert env_vars["QUORVEX_TEST_DATA_FILE"] == str(fixture_file)


def test_agent_runner_classifies_invalid_session_resume():
    from orchestrator.utils.agent_runner import classify_agent_error_type

    assert (
        classify_agent_error_type("No conversation found with session ID abc123")
        == "invalid_session_resume"
    )


def test_wetravel_seed_upserts_canonical_project_ref(monkeypatch, tmp_path):
    from orchestrator.scripts.seed_wetravel_test_data import (
        DEFAULT_PROJECT_ID,
        upsert_wetravel_auth_test_data,
    )
    from orchestrator.services.test_data_resolver import resolve_test_data_refs

    engine = create_engine(
        f"sqlite:///{tmp_path / 'wetravel-seed.db'}",
        echo=False,
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr("orchestrator.api.db.engine", engine)

    result = upsert_wetravel_auth_test_data(
        project_id=DEFAULT_PROJECT_ID,
        email="farxad2026@mailinator.com",
        password="secret-pass",
    )

    assert result["ref"] == "wetravel-auth.valid-user"
    with Session(engine) as session:
        resolved = resolve_test_data_refs(
            session,
            project_id=DEFAULT_PROJECT_ID,
            refs=["wetravel-auth.valid-user"],
            render_as="json",
        )
    assert resolved["missing"] == []
    assert (
        resolved["json"]["wetravel-auth.valid-user"]["data"]["password"]
        == "{{TESTDATA_WETRAVEL_AUTH_VALID_USER_PASSWORD}}"
    )


@pytest.mark.asyncio
async def test_native_pipeline_stops_on_missing_testdata(monkeypatch, tmp_path, caplog):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'missing-testdata.db'}",
        echo=False,
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Project(id="project-1", name="Project One"))
        session.commit()

    monkeypatch.setattr("orchestrator.api.db.engine", engine)

    spec_path = tmp_path / "tc-001-login.md"
    spec_path.write_text(
        "# TC-001: Login\n\n"
        "Navigate to https://example.com/user/my_trips\n\n"
        '@testdata "wetravel-auth.valid-user"\n'
    )
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    pipeline = object.__new__(FullNativePipeline)
    pipeline.project_id = "project-1"

    caplog.set_level(logging.INFO, logger="orchestrator.workflows.full_native_pipeline")

    result = await pipeline.run(str(spec_path), run_dir)

    assert result["success"] is False
    assert result["stage"] == "test_data_resolution"
    assert result["missing_test_data"][0]["ref"] == "wetravel-auth.valid-user"
    assert (run_dir / "status.txt").read_text() == "failed"
    assert "Test data not found" not in (run_dir / "spec_resolved.md").read_text()
    pipeline_error = json.loads((run_dir / "pipeline_error.json").read_text())
    assert pipeline_error["stage"] == "test_data_resolution"
    assert pipeline_error["missing_test_data"][0]["reason"] == "dataset_not_found"
    assert "wetravel-auth.valid-user" in caplog.text
    assert "dataset_not_found" in caplog.text


def test_native_prompts_include_testdata_env_mapping():
    from orchestrator.workflows.native_generator import NativeGenerator
    from orchestrator.workflows.native_healer import NativeHealer
    from orchestrator.workflows.native_planner import NativePlanner

    env_vars = {
        "TESTDATA_WETRAVEL_AUTH_VALID_USER_USERNAME": "user@example.com",
        "TESTDATA_WETRAVEL_AUTH_VALID_USER_PASSWORD": "secret-pass",
    }
    credentials = {
        "username": "user@example.com",
        "password": "secret-pass",
        "username_field": "username",
        "password_field": "password",
        "username_var": "TESTDATA_WETRAVEL_AUTH_VALID_USER_USERNAME",
        "password_var": "TESTDATA_WETRAVEL_AUTH_VALID_USER_PASSWORD",
        "test_data_ref": "wetravel-auth.valid-user",
    }

    planner = object.__new__(NativePlanner)
    planner.env_vars = env_vars
    planner.model_tier = "tool_deep"
    planner_prompt = planner._build_hybrid_prompt(
        feature_name="Login",
        feature_slug="login",
        prd_context="Use @testdata for login.",
        target_url="https://example.com/user/my_trips",
        login_url="https://example.com/login",
        credentials=credentials,
        output_path="/tmp/plan.md",
    )
    assert '@testdata "wetravel-auth.valid-user"' in planner_prompt
    assert "{{TESTDATA_WETRAVEL_AUTH_VALID_USER_USERNAME}}" in planner_prompt
    assert "{{TESTDATA_WETRAVEL_AUTH_VALID_USER_PASSWORD}}" in planner_prompt

    generator = object.__new__(NativeGenerator)
    generator.env_vars = env_vars
    generator._build_memory_context_section = lambda **_: ""
    generator_prompt = generator._build_generator_prompt(
        spec_path="/tmp/spec.md",
        spec_content="Log in as the valid Wetravel user.",
        spec_name="login",
        output_path=str(Path(__file__).resolve().parents[2] / "tests" / "generated" / "login.spec.ts"),
        target_url="https://example.com/user/my_trips",
        execution_credentials=credentials,
    )
    assert "process.env.TESTDATA_WETRAVEL_AUTH_VALID_USER_USERNAME!" not in generator_prompt
    assert "process.env.TESTDATA_WETRAVEL_AUTH_VALID_USER_PASSWORD!" not in generator_prompt
    assert "testData.get<'" not in generator_prompt
    assert "testData.get<{ username: string; password: string }>('wetravel-auth.valid-user')" in generator_prompt
    assert "import { test, expect } from '../fixtures/test-data';" in generator_prompt

    healer = object.__new__(NativeHealer)
    fixture_file = Path("/tmp/resolved-fixtures.json")
    healer.env_vars = {"QUORVEX_TEST_DATA_FILE": str(fixture_file)}
    healer._build_memory_context_section = lambda **_: ""
    healer_prompt = healer._build_healer_prompt(
        test_file="/tmp/login.spec.ts",
        test_content="test('login', async ({ page }) => {})",
        error_log="login failed",
    )
    assert "Project Test Data Fixture" in healer_prompt
    assert "process.env.TESTDATA_WETRAVEL_AUTH_VALID_USER_PASSWORD!" not in healer_prompt
    assert "Never write `process.env.TESTDATA_*`" in healer_prompt


def test_native_planner_split_tc001_prompt_preserves_one_scenario():
    from orchestrator.workflows.native_planner import NativePlanner

    credentials = {
        "username": "user@example.com",
        "password": "secret-pass",
        "username_var": "TESTDATA_WETRAVEL_AUTH_VALID_USER_USERNAME",
        "password_var": "TESTDATA_WETRAVEL_AUTH_VALID_USER_PASSWORD",
        "test_data_ref": "wetravel-auth.valid-user",
    }
    planner = object.__new__(NativePlanner)
    planner.env_vars = {}
    planner.model_tier = "tool_deep"

    prompt = planner._build_hybrid_prompt(
        feature_name="TC-001: Login with valid credentials and reach dashboard",
        feature_slug="tc-001-login-with-valid-credentials-and-reach-dashboard",
        prd_context=(
            "### Source Spec File\n"
            "tc-001-login-with-valid-credentials-and-reach-dashboard.md\n\n"
            '@testdata "wetravel-auth.valid-user"'
        ),
        target_url="https://example.com/user/my_trips",
        login_url="https://example.com/login",
        credentials=credentials,
        output_path="/tmp/tc-001-login.md",
    )

    assert "Preserve exactly one scenario" in prompt
    assert "Do not generate extra negative/login-reset/mobile/accessibility/responsive/regression cases" in prompt
    assert "wrong-password exploration belongs only in a different negative TC" in prompt
    assert '@testdata "wetravel-auth.valid-user"' in prompt
    assert "Prefer 6-12 scenarios" not in prompt


def test_native_pipeline_writes_runtime_fixture_file(tmp_path, caplog):
    pipeline = object.__new__(FullNativePipeline)
    pipeline.project_id = "project-1"
    context = {
        "project_id": "project-1",
        "refs": ["wetravel-auth.valid-user"],
        "runtime_fixtures": {
            "wetravel-auth.valid-user": {
                "data": {"username": "user@example.com", "password": "secret-pass"},
                "text": None,
                "format": "json",
                "sensitive_fields": ["password"],
            }
        },
    }

    fixture_file = pipeline._write_test_data_fixture_file(tmp_path / "run", context)
    pipeline._apply_test_data_execution_context(context)
    caplog.set_level(logging.INFO, logger="orchestrator.workflows.full_native_pipeline")
    pipeline._log_test_data_fixture_context(context, fixture_file)

    assert fixture_file is not None
    assert fixture_file.exists()
    assert context["runtime_fixture_file"] == str(fixture_file.resolve())
    payload = fixture_file.read_text()
    assert '"wetravel-auth.valid-user"' in payload
    assert "secret-pass" in payload
    assert (fixture_file.stat().st_mode & 0o777) == 0o600
    assert "QUORVEX_TEST_DATA_FILE" not in caplog.text
    assert "env_injected=True" in caplog.text
    assert "secret-pass" not in caplog.text


def test_native_subprocess_receives_runtime_fixture_file_only(monkeypatch, tmp_path):
    monkeypatch.setenv("TESTDATA_WETRAVEL_AUTH_VALID_USER_USERNAME", "stale@example.com")
    monkeypatch.setenv("TESTDATA_WETRAVEL_AUTH_VALID_USER_PASSWORD", "stale-secret")
    pipeline = object.__new__(FullNativePipeline)
    pipeline.test_data_env_vars = {
        "QUORVEX_TEST_DATA_FILE": str(tmp_path / "resolved-fixtures.json"),
    }
    pipeline._read_json_file = lambda _path: None
    pipeline._summarize_error = lambda _output: "failed"

    captured = {}

    class Result:
        returncode = 0
        stdout = "1 passed"
        stderr = ""

    def fake_run(*args, **kwargs):
        captured.update(kwargs)
        return Result()

    monkeypatch.setattr("subprocess.run", fake_run)

    result = pipeline._run_test("tests/generated/login.spec.ts", str(tmp_path), "chromium")

    assert result.passed is True
    assert captured["env"]["QUORVEX_TEST_DATA_FILE"] == str(
        tmp_path / "resolved-fixtures.json"
    )
    assert "TESTDATA_WETRAVEL_AUTH_VALID_USER_USERNAME" not in captured["env"]
    assert "TESTDATA_WETRAVEL_AUTH_VALID_USER_PASSWORD" not in captured["env"]
