import { afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('@ai-sdk/anthropic', () => ({
  createAnthropic: vi.fn(() => vi.fn()),
}));

vi.mock('@ai-sdk/openai', () => ({
  createOpenAI: vi.fn(() => vi.fn()),
}));

describe('chat provider routing', () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it('does not treat Claude Code subscription tokens as direct Anthropic chat credentials', async () => {
    const { hasDirectAnthropicChatCredential, usesClaudeCodeSubscription } = await import('./provider');
    const runtime = {
      route_provider: 'anthropic',
      llm_provider: 'claude_code_subscription',
      auth_mode: 'claude_code_subscription',
      api_key: '',
      claude_code_oauth_token: 'oauth-token-secret',
    };

    expect(usesClaudeCodeSubscription(runtime)).toBe(true);
    expect(hasDirectAnthropicChatCredential(runtime)).toBe(false);
  });

  it('keeps API-key Anthropic runtimes on the direct SDK path', async () => {
    const { hasDirectAnthropicChatCredential, usesClaudeCodeSubscription } = await import('./provider');
    const runtime = {
      route_provider: 'anthropic',
      llm_provider: 'anthropic',
      auth_mode: 'api_key',
      api_key: 'sk-ant-api-key',
      claude_code_oauth_token: '',
    };

    expect(usesClaudeCodeSubscription(runtime)).toBe(false);
    expect(hasDirectAnthropicChatCredential(runtime)).toBe(true);
  });
});
