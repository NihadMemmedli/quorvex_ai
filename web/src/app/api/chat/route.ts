import { streamText, stepCountIs, convertToModelMessages, createUIMessageStream, createUIMessageStreamResponse } from 'ai';
import { getActiveProvider, MODEL_ID, reportRateLimit } from '@/lib/ai/provider';
import { buildSystemPrompt } from '@/lib/ai/system-prompt';
import { createAssistantTools } from '@/lib/ai/tools';
import { backendFetch } from '@/lib/ai/backend-client';

export const maxDuration = 120;

interface RuntimeSettings {
  model_name?: string;
}

interface AgentRunSummary {
  id?: string;
  agent_type?: string;
  status?: string;
  created_at?: string;
  config?: Record<string, unknown> | string;
  summary?: string | null;
  result?: Record<string, unknown> | null;
}

function supportsExtendedThinking(modelId: string) {
  return process.env.ANTHROPIC_ENABLE_CHAT_THINKING === 'true' && (
    modelId.includes('claude-4') ||
    modelId.includes('claude-sonnet-4') ||
    modelId.includes('claude-opus-4')
  );
}

async function getRuntimeModelId(authToken?: string) {
  const settingsRes = await backendFetch<RuntimeSettings>('/settings', {
    authToken,
    timeoutMs: 5000,
  });

  return settingsRes.ok && settingsRes.data?.model_name
    ? settingsRes.data.model_name
    : MODEL_ID;
}

function extractLatestUserText(messages: any[]): string {
  const latestUser = [...messages].reverse().find((m) => m?.role === 'user');
  if (!latestUser) return '';
  if (typeof latestUser.content === 'string') return latestUser.content;
  if (Array.isArray(latestUser.parts)) {
    return latestUser.parts
      .map((part: any) => part?.type === 'text' ? part.text : '')
      .filter(Boolean)
      .join('\n');
  }
  return '';
}

function textToUIMessageResponse(text: string) {
  const stream = createUIMessageStream({
    execute({ writer }) {
      const id = 'text-1';
      writer.write({ type: 'text-start', id });
      writer.write({ type: 'text-delta', id, delta: text });
      writer.write({ type: 'text-end', id });
    },
  });

  return createUIMessageStreamResponse({ stream });
}

async function openAIChatFallbackResponse(messages: any[], systemPrompt: string, reason?: string) {
  const apiKey = (process.env.OPENAI_API_KEY || '').trim();
  if (!apiKey) {
    return null;
  }

  const baseURL = (process.env.OPENAI_BASE_URL || 'https://api.openai.com/v1').replace(/\/+$/, '');
  const model = process.env.OPENAI_CHAT_MODEL || process.env.OPENAI_MODEL || 'gpt-4o-mini';
  const modelMessages = messages
    .map((message: any) => {
      const role = ['user', 'assistant', 'system'].includes(message?.role) ? message.role : 'user';
      const content = extractMessageText(message);
      return content ? { role, content } : null;
    })
    .filter(Boolean);

  if (modelMessages.length === 0) {
    return textToUIMessageResponse('Please enter a message.');
  }

  console.info('[chat/route] routing chat through OpenAI fallback', reason ? `after: ${reason}` : '');

  try {
    const response = await fetch(`${baseURL}/chat/completions`, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${apiKey}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        model,
        messages: [
          { role: 'system', content: systemPrompt },
          ...modelMessages,
        ],
        temperature: 0.2,
        max_tokens: 2048,
      }),
      signal: AbortSignal.timeout(115000),
    });

    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      const message = payload?.error?.message || `OpenAI returned ${response.status}`;
      console.warn('[chat/route] OpenAI fallback failed:', response.status, message);
      return textToUIMessageResponse(`AI fallback is unavailable. ${message}`);
    }

    const text = payload?.choices?.[0]?.message?.content?.trim();
    return textToUIMessageResponse(text || 'AI fallback returned an empty response.');
  } catch (error) {
    console.warn('[chat/route] OpenAI fallback request failed:', error);
    return textToUIMessageResponse(extractUserMessage(error));
  }
}

async function claudeCodeBackendResponse(messages: any[], systemPrompt: string, authToken?: string) {
  const prompt = extractLatestUserText(messages);
  console.info('[chat/route] routing chat through backend Claude Code bridge');

  if (!prompt.trim()) {
    return textToUIMessageResponse('Please enter a message.');
  }

  const claudeCodeRes = await backendFetch<{ text: string }>('/chat/claude-code', {
    method: 'POST',
    authToken,
    timeoutMs: 115000,
    body: {
      prompt,
      system_prompt: systemPrompt,
      timeout_seconds: 110,
    },
  });

  if (!claudeCodeRes.ok || !claudeCodeRes.data?.text) {
    const detail = claudeCodeRes.error ? ` ${claudeCodeRes.error}` : '';
    console.warn('[chat/route] backend Claude Code bridge failed:', claudeCodeRes.status, claudeCodeRes.error);
    const fallback = await openAIChatFallbackResponse(messages, systemPrompt, claudeCodeRes.error);
    if (fallback) {
      return fallback;
    }
    return textToUIMessageResponse(
      `AI backend chat is not configured or unavailable.${detail}`
    );
  }

  return textToUIMessageResponse(claudeCodeRes.data.text);
}

function toolInputUIMessageResponse(text: string, toolName: string, input: Record<string, unknown>) {
  const stream = createUIMessageStream({
    execute({ writer }) {
      const textId = 'text-1';
      writer.write({ type: 'text-start', id: textId });
      writer.write({ type: 'text-delta', id: textId, delta: text });
      writer.write({ type: 'text-end', id: textId });
      writer.write({
        type: 'tool-input-available',
        toolCallId: `manual-${toolName}-${Date.now()}`,
        toolName,
        input,
        dynamic: true,
      });
    },
  });

  return createUIMessageStreamResponse({ stream });
}

function extractMessageText(message: any): string {
  if (!message) return '';
  if (typeof message.content === 'string') return message.content;
  const parts = Array.isArray(message.parts) ? message.parts : Array.isArray(message.content) ? message.content : [];
  return parts
    .map((part: any) => part?.type === 'text' ? part.text : '')
    .filter(Boolean)
    .join('\n');
}

function extractUrls(text: string): string[] {
  return [...text.matchAll(/https?:\/\/[^\s"'<>),]+/g)]
    .map(match => match[0].replace(/[.,;:!?]+$/, ''));
}

function buildDiscoveryAgentStartAction(
  messages: any[],
  currentPage?: string,
  pageContext?: { section?: string }
): { text: string; toolName: string; input: Record<string, unknown> } | null {
  const latestUserText = extractLatestUserText(messages);
  const conversationText = messages.map(extractMessageText).filter(Boolean).join('\n');
  const targetUrl = extractUrls(conversationText).at(-1);
  if (!targetUrl) return null;

  const pageIsDiscovery = currentPage === '/exploration' || pageContext?.section === 'exploration';
  const startIntent = /\b(run|start|launch|kick off|begin|execute)\b/i.test(latestUserText);
  const confirmedStart = /\b(confirm(ed)?|yes|start it|go ahead|proceed|ok|okay|run with this)\b/i.test(latestUserText)
    || (startIntent && Boolean(targetUrl));
  const explorerIntent = /\bexplorer\s+agent\b/i.test(latestUserText)
    || (confirmedStart && /\bexplorer\s+agent\b/i.test(conversationText))
    || (pageIsDiscovery && /\bagent\b/i.test(latestUserText) && startIntent);
  const discoveryIntent = /\b(new\s+exploration|discovery\s+(session|exploration)|start\s+exploration|run\s+exploration)\b/i.test(latestUserText)
    || (confirmedStart && /\b(new\s+exploration|discovery\s+(session|exploration)|start\s+exploration|run\s+exploration)\b/i.test(conversationText));

  if (!confirmedStart || (!explorerIntent && !discoveryIntent)) return null;
  if (/auto\s*pilot|autopilot/i.test(latestUserText)) return null;

  const deepRun = /\b(longer|deep|deeper|crawl|linked services|inside other services|sub-services|go inside|deep testing)\b/i.test(conversationText);
  const avoidPrevious = /\b(not\s+.*\b(tested|covered)\s+before|avoid\s+.*\b(tested|covered|previous|existing|duplicate)|new\s+(paths|flows|coverage)|not\s+duplicate)\b/i.test(conversationText);
  const publicOnly = /\b(without credentials|no credentials|public|unauthenticated)\b/i.test(conversationText);

  const instructions = [
    `Explore ${targetUrl} and identify meaningful test ideas from observed behavior.`,
    deepRun
      ? 'Run deep testing: spend more time on linked pages, alternate paths, edge cases, negative states, and reachable service flows.'
      : 'Stay focused on the target page and directly related flows.',
    avoidPrevious
      ? 'Avoid duplicating previously covered flows or generic smoke checks; prioritize newly discovered paths, edge cases, and flows not already represented in prior runs for this URL.'
      : '',
    publicOnly
      ? 'Do not use credentials; explore public unauthenticated pages only.'
      : 'Use public pages unless credentials are explicitly provided.',
  ].filter(Boolean).join(' ');

  if (explorerIntent) {
    return {
      text: 'I prepared the Explorer Agent start action below. Approve it to start the run from the chatbot.',
      toolName: 'startExplorerAgent',
      input: {
        url: targetUrl,
        timeLimitMinutes: deepRun ? 30 : 15,
        instructions,
        authType: 'none',
      },
    };
  }

  return {
    text: 'I prepared the Discovery exploration start action below. Approve it to start the run from the chatbot.',
    toolName: 'startDiscoveryExploration',
    input: {
      url: targetUrl,
      instructions,
      strategy: 'goal_directed',
      maxInteractions: deepRun ? 100 : 50,
      maxDepth: deepRun ? 20 : 10,
      timeoutMinutes: deepRun ? 60 : 30,
    },
  };
}

function isExplorerAgentConversation(text: string): boolean {
  return /\bexplorer\s+agent\b/i.test(text);
}

function buildExplorerAgentMissingUrlResponse(messages: any[]): Response | null {
  const latestUserText = extractLatestUserText(messages);
  const conversationText = messages.map(extractMessageText).filter(Boolean).join('\n');
  if (!isExplorerAgentConversation(conversationText)) return null;
  if (extractUrls(conversationText).length > 0) return null;
  if (!/\b(run|start|launch|kick off|begin|execute)\b/i.test(latestUserText)) return null;

  return textToUIMessageResponse(
    'Send the target URL and I will show a real Explorer Agent approval action. The run will only start after you click Approve.'
  );
}

function buildExplorerAgentStatusIntent(messages: any[]): { targetUrl?: string } | null {
  const latestUserText = extractLatestUserText(messages);
  const conversationText = messages.map(extractMessageText).filter(Boolean).join('\n');
  if (!isExplorerAgentConversation(conversationText)) return null;
  if (!/\b(so|status|progress|running|started|anything|check|ui|see|where|what happened)\b/i.test(latestUserText)) {
    return null;
  }
  return { targetUrl: extractUrls(conversationText).at(-1) };
}

function runConfigUrl(run: AgentRunSummary): string {
  const cfg = run.config;
  if (!cfg) return '';
  if (typeof cfg === 'string') {
    try {
      const parsed = JSON.parse(cfg);
      return typeof parsed?.url === 'string' ? parsed.url : '';
    } catch {
      return '';
    }
  }
  return typeof cfg.url === 'string' ? cfg.url : '';
}

async function explorerAgentStatusResponse(
  messages: any[],
  projectId?: string,
  authToken?: string
): Promise<Response | null> {
  const intent = buildExplorerAgentStatusIntent(messages);
  if (!intent) return null;

  const params = new URLSearchParams();
  params.set('limit', '20');
  if (projectId) params.set('project_id', projectId);

  const res = await backendFetch<AgentRunSummary[]>(`/api/agents/runs?${params.toString()}`, {
    authToken,
    timeoutMs: 10000,
  });

  if (!res.ok) {
    return textToUIMessageResponse(`I checked the real Explorer Agent run history, but the backend returned an error: ${res.error || 'unknown error'}`);
  }

  const runs = Array.isArray(res.data) ? res.data : [];
  const explorerRuns = runs.filter((run) => run.agent_type === 'exploratory');
  const matchingRuns = intent.targetUrl
    ? explorerRuns.filter((run) => runConfigUrl(run) === intent.targetUrl)
    : explorerRuns;
  const latestRun = matchingRuns[0];

  if (!latestRun) {
    const target = intent.targetUrl ? ` for ${intent.targetUrl}` : '';
    return textToUIMessageResponse(
      `I checked the real Explorer Agent run history and I do not see an Explorer Agent run${target}. It has not started yet. Ask me to run Explorer Agent with the URL, then click Approve on the action card.`
    );
  }

  const runUrl = runConfigUrl(latestRun);
  const summary = latestRun.summary ? `\nSummary: ${latestRun.summary}` : '';
  return textToUIMessageResponse(
    [
      'I checked the real Explorer Agent run history.',
      `Run: ${latestRun.id || 'unknown'}`,
      `Status: ${latestRun.status || 'unknown'}`,
      runUrl ? `URL: ${runUrl}` : '',
      latestRun.created_at ? `Created: ${latestRun.created_at}` : '',
      summary,
      'Open Discovery > Explorer Agent to view the run details.',
    ].filter(Boolean).join('\n')
  );
}

function buildAutoPilotStartInput(messages: any[]): Record<string, unknown> | null {
  const latestUserText = extractLatestUserText(messages);
  const conversationText = messages.map(extractMessageText).filter(Boolean).join('\n');

  const urls = extractUrls(conversationText);
  const targetUrl = urls[urls.length - 1];
  if (!targetUrl) return null;

  const directStart = /auto\s*pilot|autopilot/i.test(latestUserText)
    && /\b(run|start|launch|kick off|begin)\b/i.test(latestUserText);
  const confirmedStart = /\b(confirm(ed)?|yes|start it|go ahead|proceed|ok|okay)\b/i.test(latestUserText)
    && /auto\s*pilot|autopilot/i.test(conversationText)
    && Boolean(targetUrl);

  if (!directStart && !confirmedStart) return null;

  const deepRun = /\b(longer|deep|deeper|crawl|linked services|inside other services|sub-services|go inside)\b/i.test(conversationText);
  const explicitPriorityOnly = /\b(only|just|exclusively)\s+(critical|high|medium|low)\b/i.test(conversationText)
    || /\b(critical|high|medium|low)\s+(only|priority only)\b/i.test(conversationText)
    || /\b(exclude|skip|ignore)\s+(medium|low|medium and low|low and medium)\b/i.test(conversationText);
  const criticalOnly = /\b(only|just|exclusively)\s+critical\b/i.test(conversationText)
    || /\bcritical\s+(only|priority only)\b/i.test(conversationText);
  const highOnly = /\b(only|just|exclusively)\s+(critical and high|high)\b/i.test(conversationText)
    || /\b(critical and high|high)\s+(only|priority only)\b/i.test(conversationText);
  const mediumOnly = /\b(only|just|exclusively)\s+medium\b/i.test(conversationText)
    || /\bmedium\s+(only|priority only)\b/i.test(conversationText);
  const excludesMedium = /\b(exclude|skip|ignore)\s+(medium|medium and low|low and medium)\b/i.test(conversationText);
  const excludesLow = /\b(exclude|skip|ignore)\s+(low|medium and low|low and medium)\b/i.test(conversationText);
  const priorityGuidance = /high[^.\n]*(medium)|medium[^.\n]*(high)/i.test(conversationText)
    ? 'high and medium'
    : /\bcritical\b/i.test(conversationText)
      ? 'critical'
      : /\bhigh\b/i.test(conversationText)
        ? 'high'
        : /\bmedium\b/i.test(conversationText)
          ? 'medium'
          : 'all';
  const priorityThreshold = explicitPriorityOnly
    ? criticalOnly
      ? 'critical'
      : highOnly || excludesMedium
        ? 'high'
        : mediumOnly || excludesLow
          ? 'medium'
          : 'low'
    : 'low';
  const publicOnly = /\b(without credentials|no credentials|public|unauthenticated)\b/i.test(conversationText);

  return {
    urls: [targetUrl],
    instructions: [
      priorityGuidance === 'all'
        ? `Find important test cases from ${targetUrl}.`
        : `Prioritize ${priorityGuidance} priority test cases from ${targetUrl}, but keep the run broad unless explicitly restricted.`,
      deepRun ? 'Explore linked services reachable from the entities page.' : 'Stay focused on the target page and directly related flows.',
      publicOnly ? 'Do not use credentials; explore public unauthenticated pages only.' : 'Use public pages unless credentials are explicitly provided.',
    ].join(' '),
    strategy: 'goal_directed',
    maxInteractions: deepRun ? 100 : 50,
    maxDepth: deepRun ? 20 : 10,
    timeoutMinutes: deepRun ? 60 : 30,
    reactiveMode: true,
    priorityThreshold,
    maxSpecs: 50,
    parallelGeneration: 2,
    hybridHealing: false,
  };
}

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
      return `${providerMessage}. Check ANTHROPIC_MODEL in your .env.prod file.`;
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
  const modelId = await getRuntimeModelId(authToken);

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

  const missingExplorerUrl = buildExplorerAgentMissingUrlResponse(messages);
  if (missingExplorerUrl) return missingExplorerUrl;

  const discoveryAgentAction = buildDiscoveryAgentStartAction(messages, currentPage, pageContext);
  if (discoveryAgentAction) {
    return toolInputUIMessageResponse(
      discoveryAgentAction.text,
      discoveryAgentAction.toolName,
      discoveryAgentAction.input
    );
  }

  const explorerStatus = await explorerAgentStatusResponse(messages, projectId, authToken);
  if (explorerStatus) return explorerStatus;

  const autoPilotStartInput = buildAutoPilotStartInput(messages);
  if (autoPilotStartInput) {
    return toolInputUIMessageResponse(
      'I prepared the real Auto Pilot start action below. Approve it to start the run from the chatbot.',
      'startAutoPilot',
      autoPilotStartInput
    );
  }

  const hasApiKey = Boolean(
    (process.env.ANTHROPIC_API_KEY || process.env.ANTHROPIC_AUTH_TOKEN || '').trim()
  );
  if (!hasApiKey) {
    return claudeCodeBackendResponse(messages, systemPrompt, authToken);
  }

  const tools = createAssistantTools(authToken, projectId);

  try {
    const modelMessages = await convertToModelMessages(messages);

    // Enable extended thinking for models that support it
    const supportsThinking = supportsExtendedThinking(modelId);

    // Use multi-key provider
    const { provider, slot } = getActiveProvider();
    console.info('[chat/route] routing chat through Anthropic SDK provider');

    const result = streamText({
      model: provider(modelId),
      system: systemPrompt,
      messages: modelMessages,
      maxOutputTokens: 2048,
      tools,
      stopWhen: stepCountIs(25),
      ...(supportsThinking && {
        providerOptions: {
          anthropic: {
            thinking: { type: 'enabled', budgetTokens: 1024 },
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
        const supportsThinking = supportsExtendedThinking(modelId);

        const retryResult = streamText({
          model: retryProvider(modelId),
          system: systemPrompt,
          messages: modelMessages,
          maxOutputTokens: 2048,
          tools,
          stopWhen: stepCountIs(25),
          ...(supportsThinking && {
            providerOptions: {
              anthropic: {
                    thinking: { type: 'enabled', budgetTokens: 1024 },
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
