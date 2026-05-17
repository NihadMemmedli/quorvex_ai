import { createAnthropic } from '@ai-sdk/anthropic';
import { createOpenAI } from '@ai-sdk/openai';

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

function initKeys() {
  if (_keysInitialized) return;
  _keysInitialized = true;

  const tokensStr = process.env.ANTHROPIC_AUTH_TOKENS || '';
  const tokens = tokensStr
    ? tokensStr.split(',').map(t => t.trim()).filter(Boolean)
    : [];

  // Fall back to single key
  if (tokens.length === 0) {
    const single = process.env.ANTHROPIC_API_KEY || process.env.ANTHROPIC_AUTH_TOKEN || '';
    if (single) tokens.push(single);
  }

  for (const token of tokens) {
    _keySlots.push({ token, cooldownUntil: 0, consecutive429s: 0 });
  }
}

function getAvailableSlot(): KeySlot | null {
  initKeys();
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
export function getActiveProvider() {
  const slot = getAvailableSlot();
  const apiKey = slot?.token || process.env.ANTHROPIC_API_KEY || process.env.ANTHROPIC_AUTH_TOKEN || '';
  const authToken = apiKey ? '' : process.env.CLAUDE_CODE_OAUTH_TOKEN || '';

  const provider = createAnthropic({
    ...(apiKey ? { apiKey } : { authToken }),
    baseURL: normalizeBaseURL(process.env.ANTHROPIC_BASE_URL),
  });

  return { provider, slot };
}

export function hasDirectAnthropicChatCredential() {
  return Boolean(
    (
      process.env.ANTHROPIC_AUTH_TOKENS ||
      process.env.ANTHROPIC_API_KEY ||
      process.env.ANTHROPIC_AUTH_TOKEN ||
      ''
    ).trim()
  );
}

export function hasOpenAIChatCredential() {
  return Boolean((process.env.OPENAI_API_KEY || '').trim());
}

export function getActiveOpenAIProvider() {
  const apiKey = (process.env.OPENAI_API_KEY || '').trim();
  const provider = createOpenAI({
    apiKey,
    baseURL: normalizeOpenAIBaseURL(process.env.OPENAI_BASE_URL),
  });

  return { provider };
}

/**
 * Default provider — backward compatible export.
 * Uses the first available key from the rotation pool.
 */
export const anthropicProvider = createAnthropic({
  ...(
    process.env.ANTHROPIC_API_KEY || process.env.ANTHROPIC_AUTH_TOKEN
      ? { apiKey: process.env.ANTHROPIC_API_KEY || process.env.ANTHROPIC_AUTH_TOKEN || '' }
      : { authToken: process.env.CLAUDE_CODE_OAUTH_TOKEN || '' }
  ),
  baseURL: normalizeBaseURL(process.env.ANTHROPIC_BASE_URL),
});

export const MODEL_ID =
  process.env.ANTHROPIC_CHAT_MODEL ||
  process.env.ANTHROPIC_MODEL ||
  process.env.ANTHROPIC_DEFAULT_SONNET_MODEL ||
  'claude-sonnet-4-6';

export const OPENAI_MODEL_ID =
  process.env.OPENAI_CHAT_MODEL ||
  process.env.OPENAI_MODEL ||
  'gpt-4o-mini';
