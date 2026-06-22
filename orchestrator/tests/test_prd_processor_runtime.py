import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import orchestrator.workflows.prd_processor as prd_processor
from orchestrator.workflows.prd_processor import PRDProcessingError, PRDProcessor


class FakeHTTPResponse:
    def __init__(self, payload: dict, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


def _anthropic_response(features: list[dict]) -> FakeHTTPResponse:
    return FakeHTTPResponse({"content": [{"type": "text", "text": json.dumps({"features": features})}]})


def _anthropic_text_response(text: str) -> FakeHTTPResponse:
    return FakeHTTPResponse({"content": [{"type": "text", "text": text}]})


def _openai_response(features: list[dict]) -> FakeHTTPResponse:
    return FakeHTTPResponse({"choices": [{"message": {"content": json.dumps({"features": features})}}]})


def test_prd_processor_uses_settings_backed_anthropic_compatible_runtime(monkeypatch, tmp_path):
    from orchestrator.api import settings as settings_api

    markdown_path = tmp_path / "content.md"
    markdown_path.write_text("Users need room inventory, allocation, and package management.")
    env_vars = {
        "QUORVEX_LLM_PROVIDER": "anthropic_compatible",
        "QUORVEX_LLM_BASE_URL": "https://api.z.ai/api/anthropic",
        "QUORVEX_LLM_API_KEY": "settings-zai-key",
        "QUORVEX_LLM_DEEP_MODEL": "glm-5.1",
    }
    calls: list[dict] = []
    response_features = [
        {
            "name": "Room Management",
            "description": "Manage room inventory and allocations.",
            "requirements": ["Users can allocate rooms."],
            "merged_from": [],
        }
    ]

    def fake_runtime_env_vars(session=None):
        return env_vars

    def fake_post(url, headers, json, timeout):
        calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        return _anthropic_response(response_features)

    monkeypatch.setattr(settings_api, "runtime_env_vars", fake_runtime_env_vars)
    monkeypatch.setattr(prd_processor.httpx, "post", fake_post)

    processor = PRDProcessor(prds_dir=str(tmp_path / "prds"))
    features = processor._extract_features_with_llm(markdown_path)

    assert [feature.name for feature in features] == ["Room Management"]
    assert calls
    assert {call["url"] for call in calls} == {"https://api.z.ai/api/anthropic/v1/messages"}
    assert calls[0]["headers"]["x-api-key"] == "settings-zai-key"
    assert calls[0]["json"]["model"] == "glm-5.1"
    assert calls[0]["json"]["max_tokens"] == 8192


def test_prd_processor_uses_settings_backed_openai_compatible_runtime(monkeypatch, tmp_path):
    from orchestrator.api import settings as settings_api

    markdown_path = tmp_path / "content.md"
    markdown_path.write_text("Users need room inventory, allocation, and package management.")
    env_vars = {
        "QUORVEX_LLM_PROVIDER": "openai",
        "QUORVEX_LLM_BASE_URL": "https://llm.example.com/api",
        "OPENAI_BASE_URL": "https://llm.example.com/api",
        "QUORVEX_LLM_API_KEY": "settings-openai-key",
        "QUORVEX_LLM_DEEP_MODEL": "deep-json-model",
    }
    calls: list[dict] = []
    response_features = [
        {
            "name": "Package Management",
            "description": "Manage packages and accommodations.",
            "requirements": ["Users can configure packages."],
            "merged_from": [],
        }
    ]

    def fake_runtime_env_vars(session=None):
        return env_vars

    def fake_post(url, headers, json, timeout):
        calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        return _openai_response(response_features)

    monkeypatch.setattr(settings_api, "runtime_env_vars", fake_runtime_env_vars)
    monkeypatch.setattr(prd_processor.httpx, "post", fake_post)

    processor = PRDProcessor(prds_dir=str(tmp_path / "prds"))
    features = processor._extract_features_with_llm(markdown_path)

    assert [feature.name for feature in features] == ["Package Management"]
    assert calls
    assert {call["url"] for call in calls} == {"https://llm.example.com/api/v1/chat/completions"}
    assert calls[0]["headers"]["Authorization"] == "Bearer settings-openai-key"
    assert calls[0]["json"]["model"] == "deep-json-model"
    assert calls[0]["json"]["response_format"] == {"type": "json_object"}


def test_prd_processor_uses_claude_code_subscription_runtime(monkeypatch, tmp_path):
    from orchestrator.api import settings as settings_api

    markdown_path = tmp_path / "content.md"
    markdown_path.write_text("Users need room inventory, allocation, and package management.")
    env_vars = {
        "QUORVEX_LLM_AUTH_MODE": "claude_code_subscription",
        "QUORVEX_LLM_PROVIDER": "anthropic",
        "QUORVEX_LLM_BASE_URL": "https://api.anthropic.com",
        "CLAUDE_CODE_OAUTH_TOKEN": "oauth-token-1234567890",
        "QUORVEX_LLM_API_KEY": "",
        "QUORVEX_LLM_API_KEYS": "",
        "ANTHROPIC_AUTH_TOKEN": "",
        "ANTHROPIC_API_KEY": "",
        "OPENAI_API_KEY": "",
        "QUORVEX_LLM_DEEP_MODEL": "claude-opus-test",
    }
    captured: dict[str, object] = {"prompts": []}
    response_features = [
        {
            "name": "Room Management",
            "description": "Manage room inventory and allocations.",
            "requirements": ["Users can allocate rooms."],
            "merged_from": [],
        }
    ]

    class FakeAgentResult:
        success = True
        output = json.dumps({"features": response_features})

    class FakeRunner:
        def __init__(self, **kwargs):
            captured["kwargs"] = kwargs

        async def run(self, prompt):
            captured["prompts"].append(prompt)
            return FakeAgentResult()

    def fake_runtime_env_vars(session=None):
        return env_vars

    monkeypatch.setattr(settings_api, "runtime_env_vars", fake_runtime_env_vars)
    monkeypatch.setattr(prd_processor, "AgentRunner", FakeRunner)
    monkeypatch.setattr(
        prd_processor.httpx,
        "post",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("direct HTTP path should not run")),
    )

    processor = PRDProcessor(prds_dir=str(tmp_path / "prds"))
    features = processor._extract_features_with_llm(markdown_path)

    assert [feature.name for feature in features] == ["Room Management"]
    assert captured["kwargs"]["allowed_tools"] == []
    assert captured["kwargs"]["log_tools"] is False
    assert captured["kwargs"]["model_tier"] == "deep"
    assert captured["kwargs"]["env_vars"]["CLAUDE_CODE_OAUTH_TOKEN"] == "oauth-token-1234567890"
    assert len(captured["prompts"]) >= 2


def test_prd_processor_claude_code_mode_without_token_is_actionable(monkeypatch, tmp_path):
    from orchestrator.api import settings as settings_api

    markdown_path = tmp_path / "content.md"
    markdown_path.write_text("Users need room inventory, allocation, and package management.")

    def fake_runtime_env_vars(session=None):
        return {
            "QUORVEX_LLM_AUTH_MODE": "claude_code_subscription",
            "QUORVEX_LLM_PROVIDER": "anthropic",
            "CLAUDE_CODE_OAUTH_TOKEN": "",
            "QUORVEX_LLM_API_KEY": "",
            "ANTHROPIC_AUTH_TOKEN": "",
            "ANTHROPIC_API_KEY": "",
        }

    monkeypatch.setattr(settings_api, "runtime_env_vars", fake_runtime_env_vars)
    processor = PRDProcessor(prds_dir=str(tmp_path / "prds"))

    with pytest.raises(PRDProcessingError) as excinfo:
        processor._extract_features_with_llm(markdown_path)

    assert excinfo.value.status_code == 400
    message = str(excinfo.value)
    assert "No AI API key is configured" in message
    assert "Claude Code subscription OAuth token" in message


def test_prd_processor_missing_settings_api_key_is_actionable(monkeypatch, tmp_path):
    from orchestrator.api import settings as settings_api

    markdown_path = tmp_path / "content.md"
    markdown_path.write_text("Users need room inventory, allocation, and package management.")

    def fake_runtime_env_vars(session=None):
        return {
            "QUORVEX_LLM_PROVIDER": "anthropic_compatible",
            "QUORVEX_LLM_BASE_URL": "https://api.z.ai/api/anthropic",
            "QUORVEX_LLM_DEEP_MODEL": "glm-5.1",
        }

    monkeypatch.setattr(settings_api, "runtime_env_vars", fake_runtime_env_vars)
    processor = PRDProcessor(prds_dir=str(tmp_path / "prds"))

    with pytest.raises(PRDProcessingError) as excinfo:
        processor._extract_features_with_llm(markdown_path)

    assert excinfo.value.status_code == 400
    assert "No AI API key is configured" in str(excinfo.value)


def test_prd_processor_all_chunk_failures_are_actionable(monkeypatch, tmp_path):
    from orchestrator.api import settings as settings_api

    markdown_path = tmp_path / "content.md"
    markdown_path.write_text("Users need room inventory, allocation, and package management.")

    def fake_runtime_env_vars(session=None):
        return {
            "QUORVEX_LLM_PROVIDER": "anthropic_compatible",
            "QUORVEX_LLM_BASE_URL": "https://api.z.ai/api/anthropic",
            "QUORVEX_LLM_API_KEY": "settings-zai-key",
            "QUORVEX_LLM_DEEP_MODEL": "glm-5.1",
        }

    def fake_post(url, headers, json, timeout):
        return FakeHTTPResponse({"content": [{"type": "text", "text": "not json"}]})

    monkeypatch.setattr(settings_api, "runtime_env_vars", fake_runtime_env_vars)
    monkeypatch.setattr(prd_processor.httpx, "post", fake_post)
    processor = PRDProcessor(prds_dir=str(tmp_path / "prds"))

    with pytest.raises(PRDProcessingError) as excinfo:
        processor._extract_features_with_llm(markdown_path)

    assert "AI feature extraction failed for every PRD chunk" in str(excinfo.value)


def test_prd_processor_parses_fenced_json_from_zai(monkeypatch, tmp_path):
    from orchestrator.api import settings as settings_api

    markdown_path = tmp_path / "content.md"
    markdown_path.write_text("Users need room inventory, allocation, and package management.")
    env_vars = {
        "QUORVEX_LLM_PROVIDER": "zai",
        "QUORVEX_LLM_BASE_URL": "https://api.z.ai/api/anthropic",
        "QUORVEX_LLM_API_KEY": "settings-zai-key",
        "QUORVEX_LLM_DEEP_MODEL": "glm-5.1",
    }
    response_features = [
        {
            "name": "Room Management",
            "description": "Manage room inventory and allocations.",
            "requirements": ["Users can allocate rooms."],
            "merged_from": [],
        }
    ]

    def fake_runtime_env_vars(session=None):
        return env_vars

    def fake_post(url, headers, json, timeout):
        return _anthropic_text_response(f"```json\n{json_module.dumps({'features': response_features})}\n```")

    json_module = json
    monkeypatch.setattr(settings_api, "runtime_env_vars", fake_runtime_env_vars)
    monkeypatch.setattr(prd_processor.httpx, "post", fake_post)

    processor = PRDProcessor(prds_dir=str(tmp_path / "prds"))
    features = processor._extract_features_with_llm(markdown_path)

    assert [feature.name for feature in features] == ["Room Management"]


def test_prd_processor_parses_raw_feature_array():
    class RawArrayClient:
        def complete_json(self, prompt):
            return json.dumps(
                [
                    {
                        "name": "Package Management",
                        "description": "Manage packages.",
                        "requirements": ["Users can configure packages."],
                    }
                ]
            )

    processor = PRDProcessor()

    features = processor._extract_chunk_features(RawArrayClient(), "Package requirements")

    assert features[0]["name"] == "Package Management"


def test_prd_processor_embeddings_use_settings_backed_model(monkeypatch):
    from orchestrator.api import settings as settings_api

    seen: dict[str, object] = {}

    def fake_runtime_env_vars(session=None):
        return {"QUORVEX_EMBEDDING_MODEL": "settings-embedding-model"}

    class FakeEmbeddings:
        def create(self, model, input):
            seen["model"] = model
            seen["input"] = input
            return type(
                "EmbeddingResponse",
                (),
                {"data": [type("EmbeddingItem", (), {"embedding": [1.0, 0.0]})()]},
            )()

    class FakeClient:
        embeddings = FakeEmbeddings()

    monkeypatch.setattr(settings_api, "runtime_env_vars", fake_runtime_env_vars)
    processor = PRDProcessor()

    embeddings = processor._get_embeddings(FakeClient(), ["feature text"])

    assert embeddings == [[1.0, 0.0]]
    assert seen["model"] == "settings-embedding-model"


def test_prd_processor_rejects_valid_json_with_no_features():
    class EmptyFeatureClient:
        def complete_json(self, prompt):
            return '{"features": []}'

    processor = PRDProcessor()

    with pytest.raises(PRDProcessingError) as excinfo:
        processor._extract_chunk_features(EmptyFeatureClient(), "No useful output")

    assert "no feature objects" in str(excinfo.value)


def test_process_prd_does_not_write_success_metadata_on_empty_extraction(monkeypatch, tmp_path):
    from orchestrator.api import settings as settings_api

    pdf_path = tmp_path / "prd.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    parsed_path = tmp_path / "content.md"
    parsed_path.write_text("Room Management\nUsers can allocate rooms and manage availability.")

    def fake_runtime_env_vars(session=None):
        return {
            "QUORVEX_LLM_PROVIDER": "zai",
            "QUORVEX_LLM_BASE_URL": "https://api.z.ai/api/anthropic",
            "QUORVEX_LLM_API_KEY": "settings-zai-key",
            "QUORVEX_LLM_DEEP_MODEL": "glm-5.1",
        }

    def fake_post(url, headers, json, timeout):
        return _anthropic_text_response('{"features": []}')

    monkeypatch.setattr(settings_api, "runtime_env_vars", fake_runtime_env_vars)
    monkeypatch.setattr(prd_processor.httpx, "post", fake_post)
    monkeypatch.setattr(PRDProcessor, "_parse_pdf", lambda self, pdf, output_dir: parsed_path)

    processor = PRDProcessor(prds_dir=str(tmp_path / "prds"))

    with pytest.raises(PRDProcessingError):
        processor.process_prd(str(pdf_path), "runtime-prd", target_feature_count=8)

    assert not (tmp_path / "prds" / "runtime-prd" / "metadata.json").exists()


def test_process_prd_writes_non_empty_metadata_with_settings_runtime(monkeypatch, tmp_path):
    from orchestrator.api import settings as settings_api

    pdf_path = tmp_path / "prd.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    parsed_path = tmp_path / "content.md"
    parsed_path.write_text("Room Management\nUsers can allocate rooms and manage availability.")
    env_vars = {
        "QUORVEX_LLM_PROVIDER": "anthropic_compatible",
        "QUORVEX_LLM_BASE_URL": "https://api.z.ai/api/anthropic",
        "QUORVEX_LLM_API_KEY": "settings-zai-key",
        "QUORVEX_LLM_DEEP_MODEL": "glm-5.1",
    }
    response_features = [
        {
            "name": "Room Management",
            "description": "Manage room inventory and allocations.",
            "requirements": ["Users can allocate rooms."],
            "merged_from": [],
        }
    ]

    def fake_runtime_env_vars(session=None):
        return env_vars

    def fake_post(url, headers, json, timeout):
        return _anthropic_response(response_features)

    monkeypatch.setattr(settings_api, "runtime_env_vars", fake_runtime_env_vars)
    monkeypatch.setattr(prd_processor.httpx, "post", fake_post)
    monkeypatch.setattr(PRDProcessor, "_parse_pdf", lambda self, pdf, output_dir: parsed_path)
    monkeypatch.setattr(PRDProcessor, "_store_chunks", lambda self, chunks, project_name: None)

    processor = PRDProcessor(prds_dir=str(tmp_path / "prds"))
    stale_dir = tmp_path / "prds" / "runtime-prd"
    stale_dir.mkdir(parents=True)
    (stale_dir / "metadata.json").write_text(json.dumps({"features": [], "total_chunks": 0}))

    metadata = processor.process_prd(str(pdf_path), "runtime-prd", target_feature_count=8)

    metadata_path = tmp_path / "prds" / "runtime-prd" / "metadata.json"
    saved_metadata = json.loads(metadata_path.read_text())
    assert metadata["features"]
    assert saved_metadata["features"]
    assert saved_metadata["features"][0]["name"] == "Room Management"
    assert saved_metadata["total_chunks"] > 0
