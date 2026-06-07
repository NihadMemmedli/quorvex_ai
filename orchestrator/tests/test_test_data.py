import os
import sys
import types
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import SQLModel, Session, create_engine

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-test-data")
os.environ.setdefault("REQUIRE_AUTH", "false")

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

if "slowapi" not in sys.modules:
    slowapi_module = types.ModuleType("slowapi")
    slowapi_errors = types.ModuleType("slowapi.errors")
    slowapi_util = types.ModuleType("slowapi.util")

    class _Limiter:
        def __init__(self, *args, **kwargs):
            pass

        def limit(self, *args, **kwargs):
            def decorator(func):
                return func

            return decorator

    class _RateLimitExceeded(Exception):
        pass

    slowapi_module.Limiter = _Limiter
    slowapi_errors.RateLimitExceeded = _RateLimitExceeded
    slowapi_util.get_remote_address = lambda request: "test-client"
    sys.modules["slowapi"] = slowapi_module
    sys.modules["slowapi.errors"] = slowapi_errors
    sys.modules["slowapi.util"] = slowapi_util


@pytest.fixture()
def test_data_client(tmp_path):
    from orchestrator.api import test_data
    from orchestrator.api.models_db import Project

    test_engine = create_engine(
        f"sqlite:///{tmp_path / 'test-data.db'}",
        echo=False,
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    SQLModel.metadata.create_all(test_engine)

    with Session(test_engine) as session:
        session.add(Project(id="project-1", name="Project One"))
        session.commit()

    app = FastAPI()
    app.include_router(test_data.router)

    def override_session():
        with Session(test_engine) as session:
            yield session

    app.dependency_overrides[test_data.get_session] = override_session
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


def _create_dataset(client: TestClient, *, key: str = "auth-users") -> dict:
    response = client.post(
        "/test-data/datasets",
        json={
            "project_id": "project-1",
            "key": key,
            "name": "Auth Users",
            "description": "Login fixtures",
            "tags": ["auth", "smoke"],
            "status": "active",
            "format": "json",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_item(
    client: TestClient, dataset_id: str, *, key: str = "valid-admin"
) -> dict:
    response = client.post(
        f"/test-data/datasets/{dataset_id}/items",
        json={
            "key": key,
            "name": "Valid admin",
            "description": "Admin credentials",
            "status": "active",
            "format": "json",
            "data": {"email": "admin@example.com", "password": "replace-me"},
            "sensitive_fields": ["password"],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_create_dataset_and_item_masks_sensitive_fields(test_data_client):
    dataset = _create_dataset(test_data_client)
    item = _create_item(test_data_client, dataset["id"])

    assert dataset["key"] == "auth-users"
    assert dataset["item_count"] == 0
    assert item["ref"] == "auth-users.valid-admin"
    assert item["data"]["email"] == "admin@example.com"
    assert item["data"]["password"] == "{{TESTDATA_AUTH_USERS_VALID_ADMIN_PASSWORD}}"
    assert (
        item["placeholders"]["password"]
        == "{{TESTDATA_AUTH_USERS_VALID_ADMIN_PASSWORD}}"
    )
    assert "replace-me" not in str(item)

    listed = test_data_client.get(f"/test-data/datasets/{dataset['id']}/items")
    assert listed.status_code == 200
    assert (
        listed.json()["items"][0]["data"]["password"]
        == "{{TESTDATA_AUTH_USERS_VALID_ADMIN_PASSWORD}}"
    )

    datasets = test_data_client.get("/test-data/datasets?project_id=project-1")
    assert datasets.status_code == 200
    assert datasets.json()["datasets"][0]["item_count"] == 1


def test_duplicate_keys_return_conflict(test_data_client):
    dataset = _create_dataset(test_data_client)
    duplicate_dataset = test_data_client.post(
        "/test-data/datasets",
        json={"project_id": "project-1", "key": "auth-users", "name": "Duplicate"},
    )
    assert duplicate_dataset.status_code == 409

    _create_item(test_data_client, dataset["id"])
    duplicate_item = test_data_client.post(
        f"/test-data/datasets/{dataset['id']}/items",
        json={
            "key": "valid-admin",
            "name": "Duplicate",
            "data": {"email": "dupe@example.com"},
        },
    )
    assert duplicate_item.status_code == 409


def test_invalid_keys_and_filters_return_422(test_data_client):
    invalid_dataset = test_data_client.post(
        "/test-data/datasets",
        json={"project_id": "project-1", "key": "1bad", "name": "Bad"},
    )
    assert invalid_dataset.status_code == 422
    assert "must start with a letter" in invalid_dataset.json()["detail"]

    dataset = _create_dataset(test_data_client)
    invalid_item = test_data_client.post(
        f"/test-data/datasets/{dataset['id']}/items",
        json={"key": "bad key", "name": "Bad", "data": {}},
    )
    assert invalid_item.status_code == 422

    invalid_status = test_data_client.get(
        "/test-data/datasets?project_id=project-1&status=paused"
    )
    assert invalid_status.status_code == 422

    invalid_format = test_data_client.get(
        "/test-data/datasets?project_id=project-1&format=xml"
    )
    assert invalid_format.status_code == 422


def test_resolve_and_resolve_spec_render_masked_values(test_data_client):
    dataset = _create_dataset(test_data_client)
    _create_item(test_data_client, dataset["id"])

    resolved = test_data_client.post(
        "/test-data/resolve",
        json={
            "project_id": "project-1",
            "refs": ["auth-users.valid-admin"],
            "render_as": "json",
        },
    )
    assert resolved.status_code == 200
    payload = resolved.json()
    assert (
        payload["json"]["auth-users.valid-admin"]["data"]["password"]
        == "{{TESTDATA_AUTH_USERS_VALID_ADMIN_PASSWORD}}"
    )
    assert "replace-me" not in str(payload)

    masked = test_data_client.post(
        "/test-data/resolve",
        json={
            "project_id": "project-1",
            "refs": ["auth-users.valid-admin"],
            "render_as": "masked_ui",
        },
    )
    assert masked.status_code == 200
    assert masked.json()["masked_ui"]["auth-users.valid-admin"]["placeholders"][
        "password"
    ]

    spec = test_data_client.post(
        "/test-data/resolve/spec",
        json={
            "project_id": "project-1",
            "content": 'Before\n@testdata "auth-users.valid-admin"\nAfter',
        },
    )
    assert spec.status_code == 200
    content = spec.json()["content"]
    assert "## Project Test Data" in content
    assert "admin@example.com" in content
    assert "{{TESTDATA_AUTH_USERS_VALID_ADMIN_PASSWORD}}" in content
    assert "replace-me" not in content


def test_extract_test_data_refs_from_generated_code():
    from orchestrator.services.test_data_resolver import extract_test_data_refs_from_generated_code

    code = """
    test('uses fixture', async ({ testData }) => {
      const admin = testData.get<{ email: string }>('auth-users.valid-admin');
      const password = testData.field("billing-card.primary", "number");
      testData.get('not a ref');
    });
    """

    assert extract_test_data_refs_from_generated_code(code) == [
        "auth-users.valid-admin",
        "billing-card.primary",
    ]


def test_wetravel_login_testdata_resolves_masked_and_decrypted_for_execution(tmp_path):
    from orchestrator.api.models_db import Project, TestDataItem, TestDataSet
    from orchestrator.services.test_data_resolver import (
        prepare_test_data_item_storage,
        resolve_login_credentials_from_testdata_refs,
        resolve_test_data_execution_context,
        resolve_test_data_refs,
        resolve_testdata_in_markdown,
    )

    engine = create_engine(
        f"sqlite:///{tmp_path / 'wetravel-test-data.db'}",
        echo=False,
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        session.add(Project(id="wetravel-project", name="Wetravel"))
        dataset = TestDataSet(
            project_id="wetravel-project",
            key="wetravel-auth",
            name="Wetravel Auth",
            description="Reusable Wetravel login fixtures",
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
            name="Valid Wetravel user",
            description="Valid Wetravel login account",
            data_text=storage["text"],
        )
        item.data = storage["data"]
        item.sensitive_fields = storage["sensitive_fields"]
        item.encrypted_values = storage["encrypted_values"]
        session.add(item)
        session.commit()

        masked = resolve_test_data_refs(
            session,
            project_id="wetravel-project",
            refs=["wetravel-auth.valid-user"],
            render_as="json",
            decrypt_sensitive=False,
        )
        assert (
            masked["json"]["wetravel-auth.valid-user"]["data"]["password"]
            == "{{TESTDATA_WETRAVEL_AUTH_VALID_USER_PASSWORD}}"
        )
        assert "secret-pass" not in str(masked)

        rendered = resolve_testdata_in_markdown(
            '@testdata "wetravel-auth.valid-user"',
            session=session,
            project_id="wetravel-project",
        )
        assert "farxad2026@mailinator.com" in rendered
        assert "{{TESTDATA_WETRAVEL_AUTH_VALID_USER_PASSWORD}}" in rendered
        assert "secret-pass" not in rendered

        credentials = resolve_login_credentials_from_testdata_refs(
            session,
            project_id="wetravel-project",
            refs=["wetravel-auth.valid-user"],
        )
        assert credentials == {
            "username": "farxad2026@mailinator.com",
            "password": "secret-pass",
            "username_field": "username",
            "password_field": "password",
            "username_var": "TESTDATA_WETRAVEL_AUTH_VALID_USER_USERNAME",
            "password_var": "TESTDATA_WETRAVEL_AUTH_VALID_USER_PASSWORD",
            "test_data_ref": "wetravel-auth.valid-user",
        }

        execution_context = resolve_test_data_execution_context(
            session,
            project_id="wetravel-project",
            refs=["wetravel-auth.valid-user", "wetravel-auth.valid-user"],
            markdown='Also use @testdata "wetravel-auth.valid-user"',
        )
        assert execution_context["refs"] == ["wetravel-auth.valid-user"]
        assert (
            execution_context["masked_json"]["wetravel-auth.valid-user"]["data"][
                "password"
            ]
            == "{{TESTDATA_WETRAVEL_AUTH_VALID_USER_PASSWORD}}"
        )
        assert "secret-pass" not in str(execution_context["masked_json"])
        assert "## Available Project Test Data" in execution_context["prompt_markdown"]
        assert "secret-pass" in execution_context["prompt_markdown"]
        assert execution_context["env_vars"][
            "TESTDATA_WETRAVEL_AUTH_VALID_USER_USERNAME"
        ] == "farxad2026@mailinator.com"
        assert (
            execution_context["env_vars"]["TESTDATA_WETRAVEL_AUTH_VALID_USER_PASSWORD"]
            == "secret-pass"
        )
        assert execution_context["runtime_fixtures"]["wetravel-auth.valid-user"][
            "data"
        ]["password"] == "secret-pass"
        assert execution_context["login_credentials"] == credentials
