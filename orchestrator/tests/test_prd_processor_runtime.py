import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import orchestrator.workflows.prd_processor as prd_processor
from orchestrator.workflows.prd_processor import PRDProcessingError, PRDProcessor, PRDProcessorConfig


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

    def fake_runtime_env_vars(session=None):
        return env_vars

    def fake_claude_subprocess(self, prompt):
        captured["prompts"].append(prompt)
        captured["env_vars"] = self.env_vars
        return {"success": True, "output": json.dumps({"features": response_features})}

    monkeypatch.setattr(settings_api, "runtime_env_vars", fake_runtime_env_vars)
    monkeypatch.setattr(prd_processor._PRDAgentExtractionClient, "_run_claude_code_subprocess", fake_claude_subprocess)
    monkeypatch.setattr(
        prd_processor.httpx,
        "post",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("direct HTTP path should not run")),
    )

    processor = PRDProcessor(prds_dir=str(tmp_path / "prds"))
    features = processor._extract_features_with_llm(markdown_path)

    assert [feature.name for feature in features] == ["Room Management"]
    assert captured["env_vars"]["CLAUDE_CODE_OAUTH_TOKEN"] == "oauth-token-1234567890"
    assert len(captured["prompts"]) == 1
    assert processor._last_extraction_status["mode"] == "claude_code_direct"
    assert processor._last_extraction_status["status"] == "completed"


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


def test_prd_processor_all_chunk_failures_use_deterministic_fallback(monkeypatch, tmp_path):
    from orchestrator.api import settings as settings_api

    markdown_path = tmp_path / "content.md"
    markdown_path.write_text(
        """
## Doğum şəhadətnaməsinə müraciət xidməti
- İstifadəçi doğum şəhadətnaməsinə müraciət yaratmalıdır.
- Sistem müraciət məlumatlarını yoxlamalıdır.
"""
    )

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

    features = processor._extract_features_with_llm(markdown_path)

    assert features
    assert features[0].category == "deterministic_fallback"
    assert "müraciət yaratmalıdır" in features[0].requirements[0]


def test_prd_processor_splits_long_non_english_prd_with_configured_chunk_size(monkeypatch, tmp_path):
    markdown_path = tmp_path / "content.md"
    section = """
## Doğum şəhadətnaməsinə müraciət xidməti
- İstifadəçi doğum şəhadətnaməsinə müraciət məlumatlarını daxil etməlidir.
- Sistem müraciət üzrə API cavabını göstərməlidir.
"""
    markdown_path.write_text(section * 220, encoding="utf-8")

    class ChunkCountingClient:
        def __init__(self):
            self.extraction_prompts: list[str] = []

        def complete_json(self, prompt):
            if prompt.startswith("Analyze this section"):
                self.extraction_prompts.append(prompt)
                index = len(self.extraction_prompts)
                return json.dumps(
                    {
                        "features": [
                            {
                                "name": f"Müraciət xidməti {index}",
                                "description": "Doğum şəhadətnaməsi müraciətinin emalı.",
                                "requirements": ["İstifadəçi müraciət məlumatlarını daxil etməlidir."],
                            }
                        ]
                    }
                )
            return json.dumps(
                {
                    "features": [
                        {
                            "name": "Doğum şəhadətnaməsinə müraciət xidməti",
                            "description": "Doğum şəhadətnaməsi müraciətinin emalı.",
                            "requirements": [
                                "İstifadəçi müraciət məlumatlarını daxil etməlidir.",
                                "Sistem müraciət üzrə API cavabını göstərməlidir.",
                            ],
                            "merged_from": [],
                        }
                    ]
                }
            )

    client = ChunkCountingClient()
    processor = PRDProcessor(
        prds_dir=str(tmp_path / "prds"),
        config=PRDProcessorConfig(extraction_chunk_size=12000, overlap_size=1000),
    )
    monkeypatch.setattr(processor, "_create_prd_ai_client", lambda: client)

    features = processor._extract_features_with_llm(markdown_path)

    assert len(client.extraction_prompts) >= 3
    assert features[0].name == "Doğum şəhadətnaməsinə müraciət xidməti"
    assert features[0].slug
    assert "İstifadəçi müraciət" in features[0].requirements[0]


def test_prd_processor_zero_usable_ai_features_use_deterministic_fallback(monkeypatch, tmp_path):
    markdown_path = tmp_path / "content.md"
    markdown_path.write_text(
        """
## API tələbləri
- Sistem müraciət statusu üçün API cavabı qaytarmalıdır.
- İstifadəçi ssenari üzrə məlumatları görməlidir.
""",
        encoding="utf-8",
    )

    class EmptyRequirementClient:
        def complete_json(self, prompt):
            return json.dumps(
                {
                    "features": [
                        {
                            "name": "API",
                            "description": "Shell feature without testable requirements.",
                            "requirements": [],
                        }
                    ]
                }
            )

    processor = PRDProcessor(prds_dir=str(tmp_path / "prds"))
    monkeypatch.setattr(processor, "_create_prd_ai_client", lambda: EmptyRequirementClient())

    features = processor._extract_features_with_llm(markdown_path)

    assert features
    assert features[0].category == "deterministic_fallback"
    assert "API cavabı" in features[0].requirements[0]


def test_prd_processor_preserves_markdown_tables_in_extraction_chunks(tmp_path):
    processor = PRDProcessor(
        prds_dir=str(tmp_path / "prds"),
        config=PRDProcessorConfig(extraction_chunk_size=220, overlap_size=0),
    )
    table = processor._markdown_table(
        [
            ["Xidmət", "Tələb"],
            ["Doğum şəhadətnaməsi", "İstifadəçi müraciət yaratmalıdır."],
            ["API", "Sistem müraciət statusunu qaytarmalıdır."],
        ]
    )
    assert "| Xidmət | Tələb |" in table
    assert "| Doğum şəhadətnaməsi | İstifadəçi müraciət yaratmalıdır. |" in table

    content = f"""
<!-- quorvex-prd-parser:2 -->
<!-- page:1 -->
## Xidmət cədvəli

{table}

## Digər tələblər
Sistem əlavə məlumatları yoxlamalıdır.
"""
    chunks = processor._split_prd_content_for_extraction(content)

    assert chunks
    assert any("| Doğum şəhadətnaməsi | İstifadəçi müraciət yaratmalıdır. |" in chunk for chunk in chunks)
    assert not any("| Xidmət | Tələb |" in chunk and "| API |" not in chunk for chunk in chunks)


def test_prd_processor_slow_ai_times_out_to_deterministic_fallback(monkeypatch, tmp_path):
    markdown_path = tmp_path / "content.md"
    markdown_path.write_text(
        """
## Xidmət tələbləri
- Sistem müraciət məlumatlarını qəbul etməlidir.
- İstifadəçi müraciət statusunu görməlidir.
""",
        encoding="utf-8",
    )

    class SlowClient:
        def complete_json(self, prompt):
            time.sleep(0.2)
            return json.dumps({"features": []})

    processor = PRDProcessor(
        prds_dir=str(tmp_path / "prds"),
        config=PRDProcessorConfig(extraction_chunk_size=1000, overlap_size=0, ai_extraction_timeout_seconds=0.01),
    )
    monkeypatch.setattr(processor, "_create_prd_ai_client", lambda: SlowClient())

    started = time.monotonic()
    features = processor._extract_features_with_llm(markdown_path)

    assert time.monotonic() - started < 0.15
    assert features
    assert features[0].category == "deterministic_fallback"


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
    parsed_path.write_text("Overview\nThis document introduces the product context without functional statements.")

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
    assert saved_metadata["config"]["extraction"]["status"] == "completed"
    assert saved_metadata["config"]["extraction"]["mode"] == "provider_json"


def test_process_prd_writes_metadata_when_vector_indexing_fails(monkeypatch, tmp_path):
    class NativeVectorStorePanic(BaseException):
        pass

    pdf_path = tmp_path / "prd.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    parsed_path = tmp_path / "content.md"
    parsed_path.write_text("Room Management\nUsers can allocate rooms and manage availability.")

    monkeypatch.setattr(PRDProcessor, "_parse_pdf", lambda self, pdf, output_dir: parsed_path)
    monkeypatch.setattr(
        PRDProcessor,
        "_extract_features_with_llm",
        lambda self, markdown_path: [
            prd_processor.Feature(
                name="Room Management",
                slug="room-management",
                content="Users can allocate rooms.",
                requirements=["Users can allocate rooms."],
            )
        ],
    )

    def fail_store_chunks(self, chunks, project_name):
        raise NativeVectorStorePanic("embedding endpoint unavailable")

    monkeypatch.setattr(PRDProcessor, "_store_chunks", fail_store_chunks)

    processor = PRDProcessor(prds_dir=str(tmp_path / "prds"))
    metadata = processor.process_prd(str(pdf_path), "runtime-prd", target_feature_count=8)

    metadata_path = tmp_path / "prds" / "runtime-prd" / "metadata.json"
    saved_metadata = json.loads(metadata_path.read_text())
    assert metadata["features"]
    assert saved_metadata["features"][0]["name"] == "Room Management"
    assert saved_metadata["config"]["retrieval_indexing"]["status"] == "degraded"
    assert "embedding endpoint unavailable" in saved_metadata["config"]["retrieval_indexing"]["error"]
