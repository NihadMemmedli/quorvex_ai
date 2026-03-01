import { streamText, stepCountIs, convertToModelMessages, createUIMessageStream, createUIMessageStreamResponse } from 'ai';
import { anthropicProvider, MODEL_ID, getActiveProvider, reportRateLimit } from '@/lib/ai/provider';
import { buildSystemPrompt } from '@/lib/ai/system-prompt';
import { createAssistantTools } from '@/lib/ai/tools';
import { backendFetch } from '@/lib/ai/backend-client';

export const maxDuration = 120;

/** Extract a user-friendly message from various error shapes */
function extractUserMessage(error: unknown): string {
  const msg = error instanceof Error ? error.message : String(error);
  const body = (error as any)?.responseBody || (error as any)?.data || '';
  const combined = `${msg} ${body}`.toLowerCase();

  // Try to extract the real provider error message from the response body.
  // Z.ai wraps errors as: {"value":{"error":{"message":"..."}}} or {"error":{"message":"..."}}
  let providerMessage = '';
  if (typeof body === 'string' && body.includes('"message"')) {
    try {
      const parsed = JSON.parse(body);
      providerMessage = parsed?.value?.error?.message || parsed?.error?.message || '';
    } catch { /* ignore parse errors */ }
  }

  // If the provider gave a clear message, surface it directly
  if (providerMessage) {
    if (/subscription|plan|access|not.*include/i.test(providerMessage))
      return `${providerMessage}. Check your provider plan or change the model in settings.`;
    if (/unknown model|model.*not.*found|invalid.*model/i.test(providerMessage))
      return `${providerMessage}. Check ANTHROPIC_DEFAULT_SONNET_MODEL in your .env.prod file.`;
    if (/rate.limit|usage.limit|quota/i.test(providerMessage))
      return `${providerMessage}. Please wait a few minutes and try again.`;
  }

  if (combined.includes('usage limit') || combined.includes('rate limit') || combined.includes('429'))
    return 'Rate limit reached. Please wait a few minutes and try again.';
  if (combined.includes('unauthorized') || combined.includes('401') || combined.includes('invalid.*key'))
    return 'Authentication failed. Please check the API key configuration.';
  if (combined.includes('timeout') || combined.includes('timed out') || combined.includes('ETIMEDOUT'))
    return 'Request timed out. The AI service may be overloaded — try again shortly.';
  if (combined.includes('ECONNREFUSED') || combined.includes('ENOTFOUND') || combined.includes('fetch failed'))
    return 'Cannot reach the AI service. Please check the network configuration.';
  if (combined.includes('typeerror') || combined.includes('typevalidation') || combined.includes('zod'))
    return 'The AI service returned an unexpected response. This usually means the provider is temporarily unavailable.';
  if (combined.includes('500') || combined.includes('internal server error'))
    return 'The AI service returned an error. Please try again.';

  // Fallback: truncate to something reasonable
  const clean = msg.length > 200 ? msg.slice(0, 200) + '...' : msg;
  return `Something went wrong: ${clean}`;
}

export async function POST(req: Request) {
  const { messages, projectId, projectName, currentPage, pageContext } = await req.json();

  // Extract auth token from request headers
  const authHeader = req.headers.get('authorization');
  const authToken = authHeader?.replace('Bearer ', '') || undefined;

  // Fetch project context for proactive prompts
  let projectStats: {
    recent_runs?: number;
    recent_failures?: number;
    total_requirements?: number;
    recent_explorations?: number;
    flaky_tests?: Array<{ spec_name: string; pass_count: number; fail_count: number }>;
    pass_rate_7d?: number;
    pass_rate_prior_7d?: number;
    stale_specs_count?: number;
    uncovered_requirements_count?: number;
  } | undefined;
  try {
    const ctxRes = await backendFetch<{ recent_runs: number; recent_failures: number; total_requirements: number; recent_explorations: number }>(
      `/chat/project-context${projectId ? `?project_id=${projectId}` : ''}`,
      { authToken }
    );
    if (ctxRes.ok && ctxRes.data) {
      projectStats = ctxRes.data;
    }
  } catch {
    // silently skip - proactive prompts are optional
  }

  // Fetch recent conversation summaries for context memory
  let recentSummaries: Array<{ title: string; first_message: string; last_message: string }> = [];
  try {
    const summRes = await backendFetch<{ summaries: Array<{ title: string; first_message: string; last_message: string }> }>(
      `/chat/conversations/recent-summaries${projectId ? `?project_id=${projectId}` : ''}`,
      { authToken }
    );
    if (summRes.ok && summRes.data) {
      recentSummaries = summRes.data.summaries || [];
    }
  } catch {
    // optional feature
  }

  const systemPrompt = buildSystemPrompt({
    projectName,
    projectId,
    currentPage,
    projectStats,
    conversationHistory: recentSummaries,
    pageContext,
  });

  if (!messages || !Array.isArray(messages)) {
    return new Response('Missing messages', { status: 400 });
  }

  const tools = createAssistantTools(authToken, projectId);

  try {
    const modelMessages = await convertToModelMessages(messages);

    // Enable extended thinking for models that support it
    const supportsThinking = MODEL_ID.includes('claude-4') ||
      MODEL_ID.includes('claude-sonnet-4') ||
      MODEL_ID.includes('claude-opus-4');

    // Use multi-key provider
    const { provider, slot } = getActiveProvider();

    const result = streamText({
      model: provider(MODEL_ID),
      system: systemPrompt,
      messages: modelMessages,
      tools,
      stopWhen: stepCountIs(25),
      ...(supportsThinking && {
        providerOptions: {
          anthropic: {
            thinking: { type: 'enabled', budgetTokens: 10000 },
          },
        },
      }),
      onError({ error }) {
        console.error('[chat/route] streamText error:', error);
      },
    });

    return result.toUIMessageStreamResponse({
      sendReasoning: true,
      onError(error) {
        // This transforms the error into a user-friendly string that the SDK
        // sends as {type:"error", errorText:...} in the SSE stream.
        // The frontend runtime picks this up and sets message.status.reason = "error".
        console.error('[chat/route] stream error:', error);
        return extractUserMessage(error);
      },
    });
  } catch (error) {
    // On rate limit, report and retry once with the next key
    const errMsg = error instanceof Error ? error.message : String(error);
    const isRateLimit = /429|rate.limit|usage.limit|quota/i.test(errMsg);

    if (isRateLimit) {
      const { provider: firstProvider, slot: firstSlot } = getActiveProvider();
      reportRateLimit(firstSlot ?? undefined);

      try {
        console.warn('[chat/route] Rate limit hit, retrying with next key');
        const { provider: retryProvider, slot: retrySlot } = getActiveProvider();
        const modelMessages = await convertToModelMessages(messages);
        const supportsThinking = MODEL_ID.includes('claude-4') ||
          MODEL_ID.includes('claude-sonnet-4') ||
          MODEL_ID.includes('claude-opus-4');

        const retryResult = streamText({
          model: retryProvider(MODEL_ID),
          system: systemPrompt,
          messages: modelMessages,
          tools,
          stopWhen: stepCountIs(25),
          ...(supportsThinking && {
            providerOptions: {
              anthropic: {
                thinking: { type: 'enabled', budgetTokens: 10000 },
              },
            },
          }),
          onError({ error }) {
            console.error('[chat/route] retry streamText error:', error);
          },
        });

        return retryResult.toUIMessageStreamResponse({
          sendReasoning: true,
          onError(error) {
            console.error('[chat/route] retry stream error:', error);
            return extractUserMessage(error);
          },
        });
      } catch (retryError) {
        // Retry also failed — fall through to error stream below
        console.error('[chat/route] retry also failed:', retryError);
      }
    }

    // Synchronous failure (e.g. provider construction, first API call)
    // Return a proper SSE stream with an error chunk so the frontend
    // handles it the same way as in-stream errors.
    console.error('[chat/route] synchronous error:', error);
    const friendlyMessage = extractUserMessage(error);

    const stream = createUIMessageStream({
      execute({ writer }) {
        writer.write({ type: 'error', errorText: friendlyMessage });
      },
    });

    return createUIMessageStreamResponse({ stream });
  }
}
