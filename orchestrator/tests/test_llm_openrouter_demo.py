import os
import shutil
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session, select

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-openrouter-demo")
os.environ.setdefault("REQUIRE_AUTH", "false")

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


@pytest.fixture()
def client():
    from orchestrator.api.llm_testing import router

    app = FastAPI()
    app.include_router(router)

    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture()
def project_id():
    return f"openrouter-demo-{uuid4().hex[:8]}"


@pytest.fixture()
def project(project_id):
    from orchestrator.api.db import engine
    from orchestrator.api.models_db import Project

    with Session(engine) as session:
        session.add(Project(id=project_id, name=f"OpenRouter Demo {project_id}"))
        session.commit()

    yield project_id

    with Session(engine) as session:
        from orchestrator.api.models_db import LlmDataset, LlmDatasetCase, LlmProvider

        providers = session.exec(select(LlmProvider).where(LlmProvider.project_id == project_id)).all()
        for provider in providers:
            session.delete(provider)
        datasets = session.exec(select(LlmDataset).where(LlmDataset.project_id == project_id)).all()
        for dataset in datasets:
            cases = session.exec(select(LlmDatasetCase).where(LlmDatasetCase.dataset_id == dataset.id)).all()
            for case in cases:
                session.delete(case)
            session.delete(dataset)

        project_record = session.get(Project, project_id)
        if project_record:
            session.delete(project_record)
        session.commit()

    spec_dir = Path(__file__).resolve().parent.parent.parent / "specs" / project_id
    shutil.rmtree(spec_dir, ignore_errors=True)


def _mock_models():
    return [
        {
            "id": "openai/gpt-4o-mini",
            "name": "GPT-4o mini",
            "description": "Small OpenAI model",
            "context_length": 128000,
            "pricing": {"prompt": "0.00000015", "completion": "0.0000006"},
            "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]},
            "supported_parameters": ["temperature", "max_tokens"],
        },
        {
            "id": "anthropic/claude-3.5-haiku",
            "name": "Claude 3.5 Haiku",
            "description": "Fast Anthropic model",
            "context_length": 200000,
            "pricing": {"prompt": "0.0000008", "completion": "0.000004"},
            "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]},
            "supported_parameters": ["temperature", "max_tokens"],
        },
        {
            "id": "image-only/model",
            "name": "Image Only",
            "architecture": {"input_modalities": ["image"], "output_modalities": ["image"]},
        },
    ]


def test_openrouter_models_filters_to_text_models(client, monkeypatch):
    import orchestrator.api.llm_testing as llm_testing

    async def fake_fetch():
        return _mock_models()

    monkeypatch.setattr(llm_testing, "_fetch_openrouter_models", fake_fetch)

    response = client.get("/llm-testing/openrouter/models")

    assert response.status_code == 200
    data = response.json()
    model_ids = [m["id"] for m in data["models"]]
    assert "openai/gpt-4o-mini" in model_ids
    assert "anthropic/claude-3.5-haiku" in model_ids
    assert "image-only/model" not in model_ids


def test_openrouter_demo_setup_is_idempotent(client, monkeypatch, project):
    import orchestrator.api.llm_testing as llm_testing
    from orchestrator.api.credentials import decrypt_credential
    from orchestrator.api.db import engine
    from orchestrator.api.models_db import LlmProvider

    async def fake_fetch():
        return _mock_models()

    monkeypatch.setattr(llm_testing, "_fetch_openrouter_models", fake_fetch)

    payload = {
        "project_id": project,
        "api_key": "sk-or-v1-test",
        "model_ids": ["openai/gpt-4o-mini", "anthropic/claude-3.5-haiku"],
    }

    first = client.post("/llm-testing/openrouter/demo", json=payload)
    second = client.post("/llm-testing/openrouter/demo", json={**payload, "api_key": "sk-or-v1-updated"})

    assert first.status_code == 200
    assert first.json()["created"] == 2
    assert any(spec["name"] == "openrouter-demo-quality" for spec in first.json()["specs"])
    assert len(first.json()["datasets"]) >= 2
    assert second.status_code == 200
    assert second.json()["created"] == 0
    assert second.json()["updated"] == 2

    with Session(engine) as session:
        providers = session.exec(
            select(LlmProvider).where(
                LlmProvider.project_id == project,
                LlmProvider.base_url == llm_testing.OPENROUTER_BASE_URL,
            )
        ).all()
        assert len(providers) == 2
        assert {p.model_id for p in providers} == set(payload["model_ids"])
        assert all(decrypt_credential(p.api_key_encrypted) == "sk-or-v1-updated" for p in providers)

        for provider in providers:
            session.delete(provider)
        session.commit()


def test_openrouter_demo_rejects_too_few_models(client):
    response = client.post(
        "/llm-testing/openrouter/demo",
        json={"api_key": "sk-or-v1-test", "model_ids": ["openai/gpt-4o-mini"]},
    )

    assert response.status_code == 422


def test_demo_content_creates_specs_and_datasets(client, project):
    response = client.post("/llm-testing/demo-content", json={"project_id": project})

    assert response.status_code == 200
    data = response.json()
    assert len(data["specs"]) >= 3
    assert len(data["datasets"]) >= 2
    assert all(dataset["total_cases"] > 0 for dataset in data["datasets"])

    repeat = client.post("/llm-testing/demo-content", json={"project_id": project})
    assert repeat.status_code == 200
    assert all(not spec["created"] for spec in repeat.json()["specs"])
    assert all(not dataset["created"] for dataset in repeat.json()["datasets"])
