import inspect
import importlib.metadata as metadata


def test_claude_agent_sdk_dependency_health():
    import claude_agent_sdk
    from claude_agent_sdk import ClaudeAgentOptions

    assert metadata.version("claude-agent-sdk") == "0.2.95"
    assert getattr(claude_agent_sdk, "__version__", None) == "0.2.95"

    parameters = inspect.signature(ClaudeAgentOptions).parameters
    for option_name in (
        "cwd",
        "fallback_model",
        "max_thinking_tokens",
        "include_partial_messages",
        "max_buffer_size",
        "betas",
        "user",
        "permission_prompt_tool_name",
        "enable_file_checkpointing",
        "sandbox",
        "output_format",
        "can_use_tool",
    ):
        assert option_name in parameters
