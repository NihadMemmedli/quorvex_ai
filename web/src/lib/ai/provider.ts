import { createAnthropic } from '@ai-sdk/anthropic';
import { createOpenAI } from '@ai-sdk/openai';

export interface ChatRuntimeSettings {
  route_provider?: 'anthropic' | 'openai' | string;
  llm_provider?: string;
  assistant_runtime?: string;
  agent_runtime?: string;
  auth_mode?: string;
  base_url?: string;
  api_key?: string;
  claude_code_oauth_token?: string;
  model_name?: string;
  chat_model?: string;
  standard_model?: string;
  model_tiers?: Record<string, string>;
}

/**
 * Normalize the base URL for @ai-sdk/anthropic.
 * The SDK appends "/messages" to baseURL, so the base must end with "/v1".
 * Example: "https://proxy.example.com/api/anthropic" → "https://proxy.example.com/api/anthropic/v1"
 */
function normalizeBaseURL(url?: string): string | undefined {
  if (!url) return undefined;
  const trimmed = url.replace(/\/+$/, '');
  // If it already ends with /v1, use as-is
  if (trimmed.endsWith('/v1')) return trimmed;
  // Standard Anthropic API uses /v1 as the API root.
  if (trimmed.includes('api.anthropic.com')) return `${trimmed}/v1`;
  // For proxies (OpenRouter, custom, etc.), append /v1
  return `${trimmed}/v1`;
}

function normalizeOpenAIBaseURL(url?: string): string | undefined {
  if (!url) return undefined;
  return url.replace(/\/+$/, '');
}

/**
 * Multi-key rotation state for frontend API calls.
 */
interface KeySlot {
  token: string;
  cooldownUntil: number; // Date.now() timestamp
  consecutive429s: number;
}

const _keySlots: KeySlot[] = [];
let _roundRobinIndex = 0;
let _keysInitialized = false;

function initKeys(runtime?: ChatRuntimeSettings) {
  if (runtime?.api_key) return;
  if (_keysInitialized) return;
  _keysInitialized = true;

  const tokensStr = process.env.QUORVEX_LLM_API_KEYS || process.env.ANTHROPIC_AUTH_TOKENS || '';
  const tokens = tokensStr
    ? tokensStr.split(',').map(t => t.trim()).filter(Boolean)
    : [];

  // Fall back to single key
  if (tokens.length === 0) {
    const single = process.env.QUORVEX_LLM_API_KEY || process.env.ANTHROPIC_API_KEY || process.env.ANTHROPIC_AUTH_TOKEN || '';
    if (single) tokens.push(single);
  }

  for (const token of tokens) {
    _keySlots.push({ token, cooldownUntil: 0, consecutive429s: 0 });
  }
}

function getAvailableSlot(runtime?: ChatRuntimeSettings): KeySlot | null {
  initKeys(runtime);
  if (_keySlots.length === 0) return null;

  const now = Date.now();
  const n = _keySlots.length;
  for (let offset = 0; offset < n; offset++) {
    const idx = (_roundRobinIndex + offset) % n;
    const slot = _keySlots[idx];
    if (now >= slot.cooldownUntil) {
      _roundRobinIndex = (idx + 1) % n;
      return slot;
    }
  }

  // All in cooldown — return the one with shortest remaining
  return _keySlots.reduce((best, s) =>
    s.cooldownUntil < best.cooldownUntil ? s : best
  );
}

export function usesClaudeCodeSubscription(runtime?: ChatRuntimeSettings): boolean {
  return runtime?.auth_mode === 'claude_code_subscription'
    || runtime?.llm_provider === 'claude_code_subscription'
    || process.env.QUORVEX_LLM_AUTH_MODE === 'claude_code_subscription'
    || process.env.QUORVEX_LLM_PROVIDER === 'claude_code_subscription';
}

const _COOLDOWN_SCHEDULE = [60_000, 300_000]; // 1 min, 5 min (ms)

export function reportRateLimit(slot?: KeySlot) {
  if (!slot) return;
  slot.consecutive429s += 1;
  const idx = Math.min(slot.consecutive429s - 1, _COOLDOWN_SCHEDULE.length - 1);
  const cooldownMs = _COOLDOWN_SCHEDULE[Math.max(0, idx)];
  slot.cooldownUntil = Date.now() + cooldownMs;
}

/**
 * Get an Anthropic provider using the next available API key.
 * Returns { provider, slot } so callers can report rate limits.
 */
export function getActiveProvider(runtime?: ChatRuntimeSettings) {
  const useClaudeCode = usesClaudeCodeSubscription(runtime);
  const slot = runtime?.api_key || useClaudeCode ? null : getAvailableSlot(runtime);
  const apiKey = useClaudeCode
    ? ''
    : runtime?.api_key || slot?.token || process.env.QUORVEX_LLM_API_KEY || process.env.ANTHROPIC_API_KEY || process.env.ANTHROPIC_AUTH_TOKEN || '';
  const authToken = apiKey ? '' : runtime?.claude_code_oauth_token || process.env.CLAUDE_CODE_OAUTH_TOKEN || '';

  const provider = createAnthropic({
    ...(apiKey ? { apiKey } : { authToken }),
    baseURL: normalizeBaseURL(runtime?.base_url || process.env.QUORVEX_LLM_BASE_URL || process.env.ANTHROPIC_BASE_URL),
  });

  return { provider, slot };
}

export function hasDirectAnthropicChatCredential(runtime?: ChatRuntimeSettings) {
  if (runtime) {
    return runtime.route_provider === 'anthropic'
      && !usesClaudeCodeSubscription(runtime)
      && Boolean((runtime.api_key || '').trim());
  }
  const explicitAssistantRuntime = getExplicitAssistantRuntime(runtime);
  if (explicitAssistantRuntime === 'openai') return false;
  if (usesClaudeCodeSubscription(runtime)) return false;

  return Boolean(
    (
      process.env.QUORVEX_LLM_API_KEYS ||
      process.env.QUORVEX_LLM_API_KEY ||
      process.env.ANTHROPIC_AUTH_TOKENS ||
      process.env.ANTHROPIC_API_KEY ||
      process.env.ANTHROPIC_AUTH_TOKEN ||
      process.env.CLAUDE_CODE_OAUTH_TOKEN ||
      ''
    ).trim()
  );
}

export function hasOpenAIChatCredential(runtime?: ChatRuntimeSettings) {
  if (runtime) {
    return runtime.route_provider === 'openai' && Boolean((runtime.api_key || process.env.OPENAI_API_KEY || '').trim());
  }
  const explicitAssistantRuntime = getExplicitAssistantRuntime(runtime);
  if (explicitAssistantRuntime === 'claude_sdk') return false;
  return Boolean((process.env.OPENAI_API_KEY || process.env.QUORVEX_LLM_API_KEY || '').trim());
}

function getExplicitAssistantRuntime(runtime?: ChatRuntimeSettings) {
  return (runtime?.assistant_runtime || process.env.QUORVEX_ASSISTANT_RUNTIME || '').trim().toLowerCase();
}

export function getAssistantRuntime(runtime?: ChatRuntimeSettings) {
  return (
    runtime?.assistant_runtime ||
    runtime?.agent_runtime ||
    process.env.QUORVEX_ASSISTANT_RUNTIME ||
    process.env.QUORVEX_AGENT_RUNTIME ||
    ''
  ).trim().toLowerCase();
}

export function getActiveOpenAIProvider(runtime?: ChatRuntimeSettings) {
  const apiKey = (runtime?.api_key || process.env.OPENAI_API_KEY || process.env.QUORVEX_LLM_API_KEY || '').trim();
  const provider = createOpenAI({
    apiKey,
    baseURL: normalizeOpenAIBaseURL(runtime?.base_url || process.env.OPENAI_BASE_URL || process.env.QUORVEX_LLM_BASE_URL),
  });

  return { provider };
}

/**
 * Default provider — backward compatible export.
 * Uses the first available key from the rotation pool.
 */
export const anthropicProvider = createAnthropic({
  ...(
    process.env.QUORVEX_LLM_API_KEY || process.env.ANTHROPIC_API_KEY || process.env.ANTHROPIC_AUTH_TOKEN
      ? { apiKey: process.env.QUORVEX_LLM_API_KEY || process.env.ANTHROPIC_API_KEY || process.env.ANTHROPIC_AUTH_TOKEN || '' }
      : { authToken: process.env.CLAUDE_CODE_OAUTH_TOKEN || '' }
  ),
  baseURL: normalizeBaseURL(process.env.QUORVEX_LLM_BASE_URL || process.env.ANTHROPIC_BASE_URL),
});

export const MODEL_ID =
  process.env.QUORVEX_LLM_CHAT_MODEL ||
  process.env.QUORVEX_LLM_STANDARD_MODEL ||
  process.env.ANTHROPIC_CHAT_MODEL ||
  process.env.ANTHROPIC_MODEL ||
  process.env.ANTHROPIC_DEFAULT_SONNET_MODEL ||
  'glm-5-turbo';

export const OPENAI_MODEL_ID =
  process.env.QUORVEX_LLM_CHAT_MODEL ||
  process.env.QUORVEX_OPENAI_MODEL ||
  process.env.OPENAI_CHAT_MODEL ||
  process.env.OPENAI_MODEL ||
  'gpt-4o-mini';
