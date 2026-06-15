"""Claude Agent SDK runtime adapter."""

from __future__ import annotations

from orchestrator.utils.agent_runner import AgentResult, AgentRunner

from .base import AgentRuntime, AgentRuntimeContext


class ClaudeAgentSdkRuntime(AgentRuntime):
    name = "claude_sdk"

    async def run(self, prompt: str, context: AgentRuntimeContext) -> AgentResult:
        runner = AgentRunner(
            timeout_seconds=context.timeout_seconds,
            allowed_tools=context.allowed_tools,
            tools=context.tools,
            disallowed_tools=context.disallowed_tools,
            permission_mode=context.permission_mode,
            strict_mcp_config=context.strict_mcp_config,
            max_budget_usd=context.max_budget_usd,
            task_budget=context.task_budget,
            include_hook_events=context.include_hook_events,
            include_partial_messages=context.include_partial_messages,
            output_format=context.output_format,
            resume_session_id=context.resume_session_id,
            continue_conversation=context.continue_conversation,
            max_turns=context.max_turns,
            session_dir=context.session_dir,
            on_task_enqueued=context.on_task_enqueued,
            on_tool_use=context.on_tool_use,
            tool_permission_guard=context.tool_permission_guard,
            on_progress=context.on_progress,
            is_cancelled=context.is_cancelled,
            cwd=context.cwd,
            owner_type=context.owner_type,
            owner_id=context.owner_id,
            owner_label=context.owner_label,
            memory_project_id=context.memory_project_id,
            memory_agent_type=context.memory_agent_type,
            memory_source_type=context.memory_source_type,
            memory_source_id=context.memory_source_id,
            memory_stage=context.memory_stage,
            inject_memory=context.inject_memory,
            capture_memory=context.capture_memory,
            force_direct_execution=context.force_direct_execution,
            model=context.model,
            fallback_model=context.fallback_model,
            model_tier=context.model_tier,  # type: ignore[arg-type]
            reasoning_budget=context.reasoning_budget,
            max_buffer_size=context.max_buffer_size,
            betas=context.betas,
            user=context.user,
            permission_prompt_tool_name=context.permission_prompt_tool_name,
            enable_file_checkpointing=context.enable_file_checkpointing,
            sandbox=context.sandbox,
            hooks=context.hooks,
            agents=context.agents,
            skills=context.skills,
            plugins=context.plugins,
            session_store=context.session_store,
            fork_session=context.fork_session,
            tool_search_policy=context.tool_search_policy,
            env_vars=context.env_vars,
            trace_id=context.trace_id,
            trace_prompt_hash=context.prompt_hash,
            trace_agent_run_id=context.agent_run_id or context.owner_id,
        )
        return await runner.run(prompt)
