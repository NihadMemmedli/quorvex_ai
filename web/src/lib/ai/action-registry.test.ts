import { describe, expect, it } from 'vitest';
import { buildCodingAgentRunBody, getAssistantActionConfig, redactAssistantActionArgs } from './action-registry';

describe('assistant action registry', () => {
  it('builds startCodingAgent as a proposal-only coding run', () => {
    const config = getAssistantActionConfig('startCodingAgent');

    expect(config?.getPath({}, 'project-a')).toBe('/api/agents/runs');
    expect(config?.risk).toBe('medium');
    expect(config?.requiredRole).toBe('editor');
    expect(config?.confirmationRequired).toBe(true);
    expect(config?.getBody?.({ prompt: 'fix flaky locators', timeoutSeconds: 900 }, 'project-a')).toEqual({
      agent_type: 'coding',
      runtime: 'claude_sdk',
      model_tier: 'tool_deep',
      project_id: 'project-a',
      config: {
        prompt: 'fix flaky locators',
        task: 'fix flaky locators',
        source: 'chat_coding_agent',
        autonomy_mode: 'propose_diff_only',
        repo_scope: '/Users/nihadmammadli/Documents/projects/quorvex_ai',
        timeout_seconds: 900,
        runtime: 'claude_sdk',
        model_tier: 'tool_deep',
      },
    });
  });

  it('redacts long coding prompts in approval metadata', () => {
    const redacted = redactAssistantActionArgs({ prompt: 'x'.repeat(520) });

    expect(String(redacted.prompt)).toHaveLength(503);
    expect(String(redacted.prompt).endsWith('...')).toBe(true);
  });

  it('exports a reusable coding run body builder', () => {
    const body = buildCodingAgentRunBody({ task: 'update selectors' }, 'default') as Record<string, any>;

    expect(body.agent_type).toBe('coding');
    expect(body.config.prompt).toBe('update selectors');
    expect(body.config.autonomy_mode).toBe('propose_diff_only');
  });
});
