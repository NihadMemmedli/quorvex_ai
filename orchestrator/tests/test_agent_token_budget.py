from orchestrator.utils.token_budget import (
    build_agent_token_telemetry,
    context_budget_for_stage,
    estimate_tokens,
    truncate_text_to_tokens,
)


def test_token_estimator_and_telemetry_shape(monkeypatch):
    monkeypatch.setenv("AGENT_CONTEXT_BUDGET_NATIVE_GENERATOR", "321")

    telemetry = build_agent_token_telemetry(
        prompt="hello world",
        output="done",
        memory_context="remember this selector",
        stage="native_generator",
        agent_type="NativeGenerator",
        model="test-model",
        model_tier="tool_deep",
        provider_usage={"prompt_tokens": 12, "completion_tokens": 4, "cache_read_input_tokens": 3},
    )

    assert context_budget_for_stage("native_generator", 1200) == 321
    assert estimate_tokens("hello world") >= 1
    assert telemetry["prompt_chars"] == len("hello world")
    assert telemetry["estimated_input_tokens"] >= 1
    assert telemetry["input_tokens"] == 12
    assert telemetry["output_tokens"] == 4
    assert telemetry["cached_input_tokens"] == 3
    assert telemetry["memory_chars"] == len("remember this selector")
    assert telemetry["prompt_hash"]


def test_truncate_text_to_tokens_preserves_head_and_tail():
    text = "HEAD " + ("middle " * 1000) + "TAIL"
    truncated = truncate_text_to_tokens(text, 50)

    assert "HEAD" in truncated
    assert "TAIL" in truncated
    assert "[truncated]" in truncated
    assert len(truncated) < len(text)
