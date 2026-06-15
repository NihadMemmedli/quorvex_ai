import inspect
import importlib.metadata as metadata
from packaging.version import Version


def test_claude_agent_sdk_dependency_health():
    import claude_agent_sdk
    from claude_agent_sdk import ClaudeAgentOptions

    installed = metadata.version("claude-agent-sdk")
    assert Version(installed) >= Version("0.2.101"), f"installed claude-agent-sdk={installed}"
    if getattr(claude_agent_sdk, "__version__", None):
        assert Version(claude_agent_sdk.__version__) >= Version("0.2.101")

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
        "hooks",
        "agents",
        "skills",
        "plugins",
        "fork_session",
        "session_store",
    ):
        assert option_name in parameters
