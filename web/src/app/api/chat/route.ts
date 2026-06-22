import { streamText, stepCountIs, convertToModelMessages, createUIMessageStream, createUIMessageStreamResponse } from 'ai';
import {
  ChatRuntimeSettings,
  getActiveOpenAIProvider,
  getActiveProvider,
  hasDirectAnthropicChatCredential,
  hasOpenAIChatCredential,
  MODEL_ID,
  OPENAI_MODEL_ID,
  reportRateLimit,
  usesClaudeCodeSubscription,
} from '@/lib/ai/provider';
import { buildSystemPrompt } from '@/lib/ai/system-prompt';
import { createAssistantTools } from '@/lib/ai/tools';
import { backendFetch } from '@/lib/ai/backend-client';
import { routeAssistantIntent } from '@/lib/ai/intent-router';

export const maxDuration = 120;
const OPTIONAL_CONTEXT_TIMEOUT_MS = 1500;
const SETTINGS_TIMEOUT_MS = 1500;
const CHAT_HISTORY_MESSAGE_LIMIT = 12;
const CHAT_TOOL_STEP_LIMIT = 8;

interface AgentRunSummary {
  id?: string;
  agent_type?: string;
  status?: string;
  created_at?: string;
  config?: Record<string, unknown> | string;
  summary?: string | null;
  result?: Record<string, unknown> | null;
}

interface DatabaseConnectionSummary {
  id?: string;
  connection_id?: string;
  name?: string;
  database?: string;
  db_type?: string;
  type?: string;
  status?: string;
}

interface PrdProjectSummary {
  project?: string;
  processed_at?: string;
  feature_count?: number;
}

function supportsExtendedThinking(modelId: string) {
  return process.env.ANTHROPIC_ENABLE_CHAT_THINKING === 'true' && (
    modelId.includes('claude-4') ||
    modelId.includes('claude-sonnet-4') ||
    modelId.includes('claude-opus-4')
  );
}

async function getChatRuntimeSettings(authToken?: string): Promise<ChatRuntimeSettings | undefined> {
  const settingsRes = await backendFetch<ChatRuntimeSettings>('/settings/runtime-chat', {
    authToken,
    headers: { 'X-Quorvex-Internal-Caller': 'web-chat' },
    timeoutMs: SETTINGS_TIMEOUT_MS,
  });

  return settingsRes.ok ? settingsRes.data : undefined;
}

async function getRuntimeModelId(authToken?: string, runtime?: ChatRuntimeSettings) {
  if (runtime?.chat_model || runtime?.model_tiers?.chat || runtime?.model_name || runtime?.standard_model) {
    return runtime.chat_model || runtime.model_tiers?.chat || runtime.model_name || runtime.standard_model!;
  }

  const settingsRes = await backendFetch<ChatRuntimeSettings>('/settings', {
    authToken,
    timeoutMs: SETTINGS_TIMEOUT_MS,
  });

  return settingsRes.ok && (settingsRes.data?.chat_model || settingsRes.data?.model_tiers?.chat || settingsRes.data?.model_name)
    ? settingsRes.data.chat_model || settingsRes.data.model_tiers?.chat || settingsRes.data.model_name!
    : MODEL_ID;
}

function logTiming(label: string, startedAt: number) {
  console.info(`[chat/route] ${label} in ${Date.now() - startedAt}ms`);
}

async function timedBackendFetch<T>(
  label: string,
  path: string,
  options: Parameters<typeof backendFetch<T>>[1] = {}
) {
  const startedAt = Date.now();
  const res = await backendFetch<T>(path, options);
  logTiming(label, startedAt);
  return res;
}

function getRecentMessages(messages: any[]): any[] {
  if (messages.length <= CHAT_HISTORY_MESSAGE_LIMIT) return messages;
  return messages.slice(-CHAT_HISTORY_MESSAGE_LIMIT);
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

function buildClaudeCodeBridgePrompt(messages: any[]): string {
  return messages
    .map((message) => {
      const role = typeof message?.role === 'string' ? message.role : 'message';
      const text = extractMessageText(message);
      return text ? `${role.toUpperCase()}:\n${text}` : '';
    })
    .filter(Boolean)
    .join('\n\n');
}

function claudeCodeSubscriptionErrorMessage(error?: string) {
  const detail = error ? ` Backend detail: ${error}` : '';
  return `Claude Code subscription token is configured, but Claude rejected the request. Check subscription availability or run claude setup-token again.${detail}`;
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

const HTTP_METHODS = ['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS', 'TRACE'];

function inferHttpMethodFilter(text: string): string[] {
  const found = new Set<string>();
  for (const method of HTTP_METHODS) {
    if (!new RegExp(`\\b${method}\\b`, 'i').test(text)) continue;
    if (method === 'GET' && !/\bGET\b/.test(text)) {
      const contextualGet = /\bget\s+(commands?|endpoints?|operations?|requests?|methods?)\b/i.test(text)
        || /\b(commands?|endpoints?|operations?|requests?|methods?)\s+get\b/i.test(text)
        || /\bonly\s+get\b/i.test(text);
      if (!contextualGet) continue;
    }
    found.add(method);
  }
  return Array.from(found);
}

type OpenApiImportMode = 'evidence_specs' | 'plan_only' | 'tests_only' | 'plan_and_tests';

function inferOpenApiImportMode(text: string): OpenApiImportMode {
  if (/\bplan\s+only\b/i.test(text)) return 'plan_only';
  if (/\b(tests?|code)\s+only\b/i.test(text)) return 'tests_only';
  if (/\bplan\b/i.test(text) && !/\b(tests?|playwright|runnable|code)\b/i.test(text.replace(/\btest\s+plan\b/gi, 'plan'))) return 'plan_only';
  if (/\b(tests?|playwright|runnable|code)\b/i.test(text)) return 'plan_and_tests';
  return 'plan_and_tests';
}

function openApiImportActionText(mode: OpenApiImportMode) {
  if (mode === 'evidence_specs') {
    return 'I prepared an OpenAPI import action below. Approve it to execute documented operations and write evidence-backed API specs.';
  }
  if (mode === 'plan_only') {
    return 'I prepared an OpenAPI import action below. Approve it to import the spec and generate a review plan.';
  }
  if (mode === 'tests_only') {
    return 'I prepared an OpenAPI import action below. Approve it to import the spec and generate API tests.';
  }
  return 'I prepared an OpenAPI import action below. Approve it to import the spec and generate API specs plus Playwright API tests.';
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

function isAdhocCustomAgentConversation(text: string): boolean {
  return /\bcustom\s+agent\b/i.test(text)
    && /\b(test ideas?|qa|testing|inspect|explore|findings?|website|site|url|run|start|create)\b/i.test(text)
    && !/\b(from report|agent report|finding\s+[a-z0-9_-]+|test idea\s+[a-z0-9_-]+|source run)\b/i.test(text);
}

function extractFocusAreas(text: string): string[] {
  const match = text.match(/\bfocus(?:ing)?\s+(?:on|areas?:?)\s+([^.\n]+)/i);
  if (!match?.[1]) return [];
  return match[1]
    .split(/,|\band\b/i)
    .map((area) => area.trim())
    .filter(Boolean)
    .slice(0, 5);
}

const DEFAULT_CHAT_CUSTOM_AGENT_TOOL_IDS = [
  'browser_navigate',
  'browser_snapshot',
  'browser_click',
  'browser_type',
  'browser_select',
  'browser_press_key',
  'browser_hover',
  'browser_network',
  'browser_console',
  'browser_screenshot',
  'browser_wait',
  'browser_navigate_back',
  'browser_close',
];

const EXPLICIT_HIGH_RISK_TOOL_IDS: Array<{ pattern: RegExp; toolIds: string[] }> = [
  { pattern: /\b(write|create|save|modify|edit)\s+(files?|specs?|tests?|code|artifact)\b/i, toolIds: ['write_file', 'edit_file'] },
  { pattern: /\b(shell|bash|command line|terminal|npm|pytest|playwright test)\b/i, toolIds: ['bash'] },
  { pattern: /\b(upload|attach file|file upload)\b/i, toolIds: ['browser_upload'] },
  { pattern: /\b(javascript|evaluate|localstorage|sessionstorage|dom script)\b/i, toolIds: ['browser_evaluate'] },
];

function hostnameLabel(rawUrl: string) {
  try {
    return new URL(rawUrl).hostname.replace(/^www\./, '').slice(0, 48) || 'website';
  } catch {
    return 'website';
  }
}

function extractMinimumServiceCount(text: string): number | undefined {
  const numeric = text.match(/\b(?:at\s+least|minimum|min\.?|no\s+fewer\s+than)\s+(\d+)\s+(?:services?|flows?|scenarios?|pages?)\b/i);
  if (numeric?.[1]) return Number(numeric[1]);

  const direct = text.match(/\b(\d+)\s+(?:services?|flows?|scenarios?|pages?)\b/i);
  if (direct?.[1] && /\b(deep|deeper|inside|analy[sz]e|inspect|explore)\b/i.test(text)) {
    return Number(direct[1]);
  }
  return undefined;
}

function inferCustomAgentToolIds(text: string): string[] {
  const toolIds = new Set(DEFAULT_CHAT_CUSTOM_AGENT_TOOL_IDS);
  for (const rule of EXPLICIT_HIGH_RISK_TOOL_IDS) {
    if (rule.pattern.test(text)) {
      rule.toolIds.forEach((toolId) => toolIds.add(toolId));
    }
  }
  if (/\b(assert|verify|validate|locator|selector)\b/i.test(text)) {
    toolIds.add('browser_generate_locator');
    toolIds.add('browser_verify_element');
    toolIds.add('browser_verify_text');
  }
  if (/\b(trace|tracing)\b/i.test(text)) {
    toolIds.add('browser_start_tracing');
    toolIds.add('browser_stop_tracing');
  }
  return Array.from(toolIds);
}

function buildCustomAgentSystemPrompt(text: string) {
  const mustNotInvent = /\b(do\s+not|don't|dont|without)\s+(invent|assume|hallucinate|make up)|\bnot invent\b/i.test(text);
  return [
    'You are a focused QA automation agent.',
    'Use only the granted tools and stay within the requested scope.',
    'Inspect the target from observable UI, network, console, and page behavior.',
    'Use public unauthenticated pages only unless credentials are explicitly provided.',
    mustNotInvent
      ? 'Do not invent requirements, flows, pages, findings, data, or expected behavior. Mark unknowns as unknown and cite observed evidence.'
      : 'Base findings and test ideas on observed behavior and clearly separate evidence from assumptions.',
    'Report pages checked, flows/scenarios observed, findings, test ideas, evidence, requirements inferred from observations, and follow-up actions.',
    'Do not modify external data unless the user explicitly requested that action.',
  ].join(' ');
}

function buildCustomAgentRunPrompt(targetUrl: string, text: string, focusAreas: string[]) {
  const targetServiceCount = extractMinimumServiceCount(text);
  const wantsRequirements = /\brequirements?\b/i.test(text);
  const wantsScenarios = /\b(flows?|scenarios?|journeys?)\b/i.test(text);
  const mustNotInvent = /\b(do\s+not|don't|dont|without)\s+(invent|assume|hallucinate|make up)|\bnot invent\b/i.test(text);
  const deepRun = /\b(longer|deep|deeper|crawl|inside|at least|minimum|many|different)\b/i.test(text);

  const lines = [
    `Inspect ${targetUrl}.`,
    targetServiceCount ? `Go deeper into at least ${targetServiceCount} observed services or service-category paths before summarizing.` : '',
    deepRun && !targetServiceCount ? 'Go deeper than a smoke check: inspect linked pages, alternate paths, edge cases, and negative states where observable.' : '',
    wantsScenarios ? 'Analyze different observed flows, scenarios, branches, and failure/empty states.' : '',
    wantsRequirements ? 'Extract requirements only when they are directly supported by observed UI text, behavior, network calls, or page structure.' : '',
    mustNotInvent ? 'Do not invent anything. If a requirement, expected result, or scenario is not observable, mark it as unknown or a follow-up.' : '',
    'Use public unauthenticated pages only unless credentials are explicitly provided.',
    focusAreas.length > 0 ? `Focus areas: ${focusAreas.join(', ')}.` : '',
    'Capture pages checked, observed flows, findings, test ideas, evidence, inferred requirements, and follow-up actions.',
    '',
    'Original user request:',
    text.trim().slice(0, 3000),
  ];

  return lines.filter(Boolean).join('\n');
}

function customAgentSaveOnlyIntent(text: string): boolean {
  const saveIntent = /\b(save|store|create|build|define)\b.*\b(custom\s+agent|agent definition|reusable agent|template)\b/i.test(text)
    || /\b(custom\s+agent|agent definition|reusable agent|template)\b.*\b(save|store|create|build|define)\b/i.test(text);
  const runIntent = /\b(run|start|launch|kick off|begin|execute|inspect now|go ahead|approve)\b/i.test(text);
  return saveIntent && !runIntent;
}

function buildAdhocCustomAgentStartAction(messages: any[]): { text: string; toolName: string; input: Record<string, unknown> } | null {
  const latestUserText = extractLatestUserText(messages);
  const conversationText = messages.map(extractMessageText).filter(Boolean).join('\n');
  const targetUrl = extractUrls(conversationText).at(-1);
  const customIntent = isAdhocCustomAgentConversation(conversationText);
  if (!customIntent || !targetUrl) return null;
  if (/\b(auto\s*pilot|autopilot|explorer\s+agent|discovery\s+(session|exploration)|new\s+exploration)\b/i.test(latestUserText)) {
    return null;
  }

  const latestHasUrl = extractUrls(latestUserText).length > 0;
  const startIntent = /\b(create|run|start|launch|kick off|begin|execute|proceed|confirm(ed)?|yes|go ahead|ok|okay)\b/i.test(latestUserText);
  if (!startIntent && !latestHasUrl) return null;

  const focusAreas = extractFocusAreas(conversationText);
  const promptSource = latestUserText.trim() || conversationText.trim();
  const targetServiceCount = extractMinimumServiceCount(promptSource);
  const prompt = buildCustomAgentRunPrompt(targetUrl, promptSource, focusAreas);
  const saveOnly = customAgentSaveOnlyIntent(latestUserText);
  const agentName = `QA Agent - ${hostnameLabel(targetUrl)}`;

  return {
    text: saveOnly
      ? 'I prepared an editable custom agent definition below. Review the prompt and tools, then approve to save it.'
      : 'I prepared an editable custom agent start action below. Review the prompt and tools, then approve to create the agent and start the run.',
    toolName: saveOnly ? 'createCustomAgentDefinition' : 'startAdhocCustomAgent',
    input: {
      url: targetUrl,
      agentName,
      description: `Chat-created custom QA agent for ${targetUrl}.`,
      systemPrompt: buildCustomAgentSystemPrompt(promptSource),
      prompt,
      toolIds: inferCustomAgentToolIds(promptSource),
      focusAreas: focusAreas.length > 0 ? focusAreas : undefined,
      targetServiceCount,
      requireObservedEvidence: true,
      publicOnly: true,
      outputGoals: ['pages_checked', 'flows', 'scenarios', 'findings', 'test_ideas', 'evidence', 'requirements', 'follow_up_actions'],
      timeoutSeconds: targetServiceCount && targetServiceCount >= 7 ? 3600 : 1800,
    },
  };
}

function buildAdhocCustomAgentMissingUrlResponse(messages: any[]): Response | null {
  const latestUserText = extractLatestUserText(messages);
  const conversationText = messages.map(extractMessageText).filter(Boolean).join('\n');
  if (!isAdhocCustomAgentConversation(conversationText)) return null;
  if (extractUrls(conversationText).length > 0) return null;
  if (!/\b(create|run|start|launch|kick off|begin|execute)\b/i.test(latestUserText)) return null;

  return textToUIMessageResponse(
    'Send the target website URL and I will show a real custom agent approval action. The run will only start after you click Approve.'
  );
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

function slugifySpecName(input: string, fallback: string) {
  const slug = input
    .toLowerCase()
    .replace(/https?:\/\//g, '')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 48);
  return `${slug || fallback}-${Date.now()}.md`;
}

function extractApiSpecName(text: string): string | null {
  const match = text.match(/\b([a-z0-9][a-z0-9._/-]*api[a-z0-9._/-]*\.md|[a-z0-9][a-z0-9._/-]*\.md)\b/i);
  return match?.[1] || null;
}

function extractHttpOperations(text: string): string[] {
  const matches = [...text.matchAll(/\b(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s+(\/[^\s,.;)]+)/gi)];
  return matches.map((match) => `${match[1].toUpperCase()} ${match[2]}`);
}

function buildDemoApiSpecContent(): string {
  return `# Test: HTTPBin Demo API

## Type: API
## Base URL: https://httpbin.org
## Auth: None

## Description
Demo API coverage for stable HTTPBin endpoints. This verifies common request/response behavior without needing user credentials.

## Steps
1. GET /get
2. Verify response status is 200
3. Verify response body has "url" field
4. POST /post with body {"name": "Quorvex Demo", "source": "chatbot"}
5. Verify response status is 200
6. Verify response body.json.name equals "Quorvex Demo"
7. GET /status/204
8. Verify response status is 204
9. GET /status/404
10. Verify response status is 404

## Expected Outcome
- The API accepts GET and POST requests.
- JSON request bodies are echoed correctly.
- Success and error status endpoints return the expected status codes.
`;
}

function buildApiSpecFromPromptContent(text: string, baseUrl: string, operations: string[]): string {
  const steps = operations.length > 0
    ? operations.flatMap((operation, index) => [
        `${index * 2 + 1}. ${operation}`,
        `${index * 2 + 2}. Verify response status is between 200 and 299`,
      ])
    : [
        `1. GET /`,
        `2. Verify response status is between 200 and 299`,
      ];

  return `# Test: Chatbot API Test

## Type: API
## Base URL: ${baseUrl}
## Auth: None

## Description
API test generated from the chatbot request.

## Source Request
${text.trim() || 'Create API coverage from chatbot input.'}

## Steps
${steps.join('\n')}

## Expected Outcome
- The API endpoints respond successfully according to the requested behavior.
- Response status codes and payloads are validated by the generated Playwright API test.
`;
}

function buildApiTestAction(messages: any[]): { text: string; toolName: string; input: Record<string, unknown> } | null {
  const latestUserText = extractLatestUserText(messages);
  const conversationText = messages.map(extractMessageText).filter(Boolean).join('\n');
  const combinedText = `${conversationText}\n${latestUserText}`;

  const apiIntent = /\b(api|openapi|swagger|endpoint|http\s+request|rest)\b/i.test(combinedText)
    && /\b(test|tests|testing|generate|create|import|demo|random)\b/i.test(combinedText);
  if (!apiIntent) return null;
  if (/auto\s*pilot|autopilot|explorer\s+agent|exploration/i.test(latestUserText)) return null;

  const startIntent = /\b(generate|create|make|import|build|start|proceed|confirm(ed)?|yes|go ahead|ok|okay)\b/i.test(latestUserText);
  if (!startIntent && !/\b(random|demo)\b/i.test(latestUserText)) return null;

  const urls = extractUrls(combinedText);
  const targetUrl = urls.at(-1);
  const looksLikeOpenApi = Boolean(targetUrl)
    && /\b(openapi|swagger)\b/i.test(combinedText);
  if (looksLikeOpenApi && targetUrl) {
    const methodFilter = inferHttpMethodFilter(latestUserText);
    const mode = inferOpenApiImportMode(latestUserText);
    return {
      text: openApiImportActionText(mode),
      toolName: 'importOpenApiSpec',
      input: {
        url: targetUrl,
        methodFilter: methodFilter.length > 0 ? methodFilter : undefined,
        mode,
      },
    };
  }

  const explicitSpecName = extractApiSpecName(latestUserText) || extractApiSpecName(conversationText);
  const mentionsExistingSpec = /\b(existing|from|for|using)\b/i.test(latestUserText)
    && explicitSpecName
    && !/\b(random|demo|new)\b/i.test(latestUserText);
  if (mentionsExistingSpec && explicitSpecName) {
    return {
      text: 'I prepared the API test generation action below. Approve it to generate Playwright API tests from the existing spec.',
      toolName: 'generateApiTest',
      input: { specName: explicitSpecName },
    };
  }

  const wantsDemo = /\b(random|demo|sample|example)\b/i.test(combinedText);
  if (wantsDemo) {
    return {
      text: 'I prepared a demo API spec and generation action below. Approve it to create the spec and generate Playwright API tests.',
      toolName: 'createAndGenerateApiTest',
      input: {
        specName: slugifySpecName('demo-httpbin-api', 'demo-api'),
        content: buildDemoApiSpecContent(),
      },
    };
  }

  const operations = extractHttpOperations(combinedText);
  if (targetUrl || operations.length > 0) {
    const baseUrl = targetUrl || 'https://httpbin.org';
    return {
      text: 'I prepared an API spec and generation action below. Approve it to create the spec and generate Playwright API tests.',
      toolName: 'createAndGenerateApiTest',
      input: {
        specName: slugifySpecName(targetUrl || operations[0] || 'chatbot-api-test', 'api-test'),
        content: buildApiSpecFromPromptContent(latestUserText || conversationText, baseUrl, operations),
      },
    };
  }

  return null;
}

function isDatabaseSpecGenerationIntent(text: string): boolean {
  const databaseIntent = /\b(db|database|sql|postgres|postgresql|mysql|sqlite|mssql|oracle|schema)\b/i.test(text);
  const specIntent = /\b(spec|test spec|testing spec|quality checks?|data quality|validation checks?)\b/i.test(text);
  const generationIntent = /\b(generate|create|make|build|draft|prepare)\b/i.test(text);
  return databaseIntent && specIntent && generationIntent;
}

function extractDatabaseConnectionId(text: string): string | null {
  const explicit = text.match(/\b(?:connection|conn)(?:\s+id)?\s*(?:is|=|:|#)\s*["'`]?([a-z0-9][a-z0-9_-]{2,})["'`]?/i)
    || text.match(/\b(?:connection|conn)\s+id\s+["'`]?([a-z0-9][a-z0-9_-]{2,})["'`]?/i);
  if (explicit?.[1]) {
    return explicit[1];
  }

  const uuid = text.match(/\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b/i);
  return uuid?.[0] || null;
}

function extractDatabaseSpecName(text: string): string | null {
  const fileName = text.match(/\b[a-z0-9][a-z0-9._/-]*\.md\b/i);
  if (fileName?.[0]) return fileName[0];

  const explicit = text.match(/\b(?:spec\s+name|name\s+it|called|named)\s*(?:is|=|:)?\s*["'`]?([a-z0-9][a-z0-9._/-]{2,})["'`]?/i);
  return explicit?.[1] || null;
}

function normalizeDatabaseConnections(data: unknown): DatabaseConnectionSummary[] {
  if (Array.isArray(data)) return data as DatabaseConnectionSummary[];
  if (!data || typeof data !== 'object') return [];
  const record = data as Record<string, unknown>;
  const list = record.connections || record.items || record.data || record.results;
  return Array.isArray(list) ? list as DatabaseConnectionSummary[] : [];
}

function normalizePrdProjects(data: unknown): PrdProjectSummary[] {
  if (Array.isArray(data)) return data as PrdProjectSummary[];
  if (!data || typeof data !== 'object') return [];
  const record = data as Record<string, unknown>;
  const list = record.projects || record.items || record.data || record.results;
  return Array.isArray(list) ? list as PrdProjectSummary[] : [];
}

function prdProjectId(project: PrdProjectSummary): string {
  return String(project.project || '').trim();
}

function isPrdFeatureReadIntent(
  latestUserText: string,
  currentPage?: string,
  pageContext?: { section?: string }
) {
  const text = latestUserText.toLowerCase();
  const prdContext = currentPage === '/prd'
    || pageContext?.section?.toLowerCase() === 'prd'
    || /\bprd\b/.test(text);
  const wantsFeatures = /\b(features?|requirements?)\b/.test(text);
  const readIntent = /\b(show|list|view|get|retrieve|display|see|current|existing)\b/.test(text);
  const existingProject = /\b(existing|current)\s+project\b/.test(text);
  return prdContext && wantsFeatures && (readIntent || existingProject);
}

function featureLabel(feature: unknown, index: number): string {
  if (!feature || typeof feature !== 'object') return `Feature ${index + 1}`;
  const record = feature as Record<string, unknown>;
  const name = record.name || record.title || record.feature || record.slug || `Feature ${index + 1}`;
  const requirements = Array.isArray(record.requirements) ? record.requirements.length : undefined;
  const requirementText = requirements !== undefined ? ` - ${requirements} requirement${requirements === 1 ? '' : 's'}` : '';
  return `${String(name)}${requirementText}`;
}

async function prdFeaturesShortcutResponse(
  latestUserText: string,
  projectId: string | undefined,
  currentPage: string | undefined,
  pageContext: { section?: string } | undefined,
  authToken: string | undefined
): Promise<Response | null> {
  if (!isPrdFeatureReadIntent(latestUserText, currentPage, pageContext)) return null;

  const params = new URLSearchParams();
  if (projectId) params.set('project_id', projectId);
  const projectsPath = `/api/prd/projects${params.toString() ? `?${params.toString()}` : ''}`;
  const projectsRes = await backendFetch<unknown>(projectsPath, {
    authToken,
    timeoutMs: 10000,
  });

  if (!projectsRes.ok) {
    return textToUIMessageResponse(
      `I tried to load PRD projects, but the backend returned an error: ${projectsRes.error || 'unknown error'}.`
    );
  }

  const projects = normalizePrdProjects(projectsRes.data).filter((project) => prdProjectId(project));
  if (projects.length === 0) {
    return textToUIMessageResponse('I do not see any PRD projects for the current project.');
  }

  if (projects.length > 1) {
    const choices = projects
      .slice(0, 10)
      .map((project) => {
        const id = prdProjectId(project);
        const count = typeof project.feature_count === 'number' ? ` - ${project.feature_count} features` : '';
        return `- ${id}${count}`;
      })
      .join('\n');
    return textToUIMessageResponse(
      `I found multiple PRD projects. Reply with the PRD project name to show its features.\n\n${choices}`
    );
  }

  const selectedProject = prdProjectId(projects[0]);
  const featuresRes = await backendFetch<{ features?: unknown[]; total?: number }>(
    `/api/prd/${encodeURIComponent(selectedProject)}/features`,
    { authToken, timeoutMs: 10000 }
  );

  if (!featuresRes.ok) {
    return textToUIMessageResponse(
      `I found PRD project "${selectedProject}", but loading its features failed: ${featuresRes.error || 'unknown error'}.`
    );
  }

  const features = Array.isArray(featuresRes.data?.features) ? featuresRes.data.features : [];
  if (features.length === 0) {
    return textToUIMessageResponse(`PRD project "${selectedProject}" has no testable features yet.`);
  }

  const shown = features.slice(0, 20).map(featureLabel).join('\n- ');
  const suffix = features.length > 20 ? `\n\nShowing 20 of ${features.length} features.` : '';
  return textToUIMessageResponse(
    `Features in PRD project "${selectedProject}":\n\n- ${shown}${suffix}`
  );
}

function databaseConnectionId(connection: DatabaseConnectionSummary): string {
  return String(connection.id || connection.connection_id || '');
}

function databaseConnectionLabel(connection: DatabaseConnectionSummary): string {
  const id = databaseConnectionId(connection);
  const name = connection.name || connection.database || 'Unnamed connection';
  const type = connection.db_type || connection.type;
  const status = connection.status ? ` (${connection.status})` : '';
  return `${name}${type ? ` [${type}]` : ''}${id ? ` - ${id}` : ''}${status}`;
}

async function buildDatabaseSpecGenerationResponse(
  messages: any[],
  projectId?: string,
  authToken?: string
): Promise<Response | null> {
  const latestUserText = extractLatestUserText(messages);
  const conversationText = messages.map(extractMessageText).filter(Boolean).join('\n');
  const combinedText = `${conversationText}\n${latestUserText}`;
  if (!isDatabaseSpecGenerationIntent(combinedText)) return null;
  if (/\b(api|openapi|swagger|endpoint|http\s+request|rest)\b/i.test(latestUserText)) return null;

  const mentionedConnectionId = extractDatabaseConnectionId(combinedText);
  const specName = extractDatabaseSpecName(combinedText);
  const instructions = latestUserText.trim() || 'Generate a database testing spec from this connection.';

  if (mentionedConnectionId) {
    return toolInputUIMessageResponse(
      'I prepared the database spec generation action below. Approve it to generate the spec without auto-running it.',
      'generateDatabaseSpec',
      {
        connectionId: mentionedConnectionId,
        instructions,
        specName: specName || undefined,
      }
    );
  }

  const params = new URLSearchParams();
  if (projectId) params.set('project_id', projectId);
  const path = `/database-testing/connections${params.toString() ? `?${params}` : ''}`;
  const res = await backendFetch<unknown>(path, {
    authToken,
    timeoutMs: OPTIONAL_CONTEXT_TIMEOUT_MS,
  });

  if (!res.ok) {
    return textToUIMessageResponse(
      `I need a database connection before I can prepare that approval action, but I could not load the connection list: ${res.error || 'unknown error'}.`
    );
  }

  const connections = normalizeDatabaseConnections(res.data).filter(databaseConnectionId);
  if (connections.length === 1) {
    return toolInputUIMessageResponse(
      'I found one database connection and prepared the spec generation action below. Approve it to generate the spec without auto-running it.',
      'generateDatabaseSpec',
      {
        connectionId: databaseConnectionId(connections[0]),
        instructions,
        specName: specName || undefined,
      }
    );
  }

  if (connections.length === 0) {
    return textToUIMessageResponse(
      'I do not see any configured database connections. Add a connection on /database-testing, then ask me to generate the database spec again.'
    );
  }

  const choices = connections
    .slice(0, 10)
    .map((connection) => `- ${databaseConnectionLabel(connection)}`)
    .join('\n');
  return textToUIMessageResponse(
    `Which database connection should I use?\n\n${choices}\n\nReply with the connection ID and I will prepare the approval action.`
  );
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
      return `${providerMessage}. Check the chat model in Settings, or env fallback values if Settings is unavailable.`;
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
  const startedAt = Date.now();
  const { messages, projectId, projectName, currentPage, pageContext } = await req.json();

  if (!messages || !Array.isArray(messages)) {
    return new Response('Missing messages', { status: 400 });
  }

  // Extract auth token from request headers
  const authHeader = req.headers.get('authorization');
  const authToken = authHeader?.replace('Bearer ', '') || undefined;
  const latestUserText = extractLatestUserText(messages);
  const runtimeSettings = await getChatRuntimeSettings(authToken);
  const useClaudeCode = usesClaudeCodeSubscription(runtimeSettings);
  const useAnthropic = !useClaudeCode && hasDirectAnthropicChatCredential(runtimeSettings);
  const useOpenAI = !useAnthropic && hasOpenAIChatCredential(runtimeSettings);
  let routedModelId: string | undefined;

  if (useAnthropic || useOpenAI) {
    routedModelId = useAnthropic
      ? await getRuntimeModelId(authToken, runtimeSettings)
      : runtimeSettings?.chat_model || runtimeSettings?.model_tiers?.chat || runtimeSettings?.standard_model || OPENAI_MODEL_ID;
    const { provider } = useAnthropic
      ? getActiveProvider(runtimeSettings)
      : getActiveOpenAIProvider(runtimeSettings);
    const intentRoute = await routeAssistantIntent({
      messages,
      projectId,
      currentPage,
      pageContext,
      authToken,
      model: provider(routedModelId),
    });

    if (intentRoute?.kind === 'clarify') {
      return textToUIMessageResponse(intentRoute.text);
    }

    if (intentRoute?.kind === 'action') {
      return toolInputUIMessageResponse(intentRoute.text, intentRoute.toolName, intentRoute.input);
    }
  }

  const [modelId, ctxRes, summRes, memoryRes] = await Promise.all([
    routedModelId ? Promise.resolve(routedModelId) : getRuntimeModelId(authToken, runtimeSettings),
    timedBackendFetch<{
      recent_runs?: number;
      recent_failures?: number;
      total_requirements?: number;
      recent_explorations?: number;
      flaky_tests?: Array<{ spec_name: string; pass_count: number; fail_count: number }>;
      pass_rate_7d?: number;
      pass_rate_prior_7d?: number;
      stale_specs_count?: number;
      uncovered_requirements_count?: number;
    }>(
      'project context',
      `/chat/project-context${projectId ? `?project_id=${projectId}` : ''}`,
      { authToken, timeoutMs: OPTIONAL_CONTEXT_TIMEOUT_MS }
    ).catch(() => null),
    timedBackendFetch<{ summaries: Array<{ title: string; first_message: string; last_message: string }> }>(
      'recent summaries',
      `/chat/conversations/recent-summaries${projectId ? `?project_id=${projectId}` : ''}`,
      { authToken, timeoutMs: OPTIONAL_CONTEXT_TIMEOUT_MS }
    ).catch(() => null),
    timedBackendFetch<{
      context?: string;
      memories: Array<{ kind: string; summary?: string | null; content?: string; confidence?: number }>;
    }>(
      'agent memory',
      `/api/memory/agent/context?${new URLSearchParams({
        ...(projectId ? { project_id: projectId } : {}),
        q: latestUserText || currentPage || '',
        agent_type: 'assistant',
        limit: '8',
      }).toString()}`,
      { authToken, timeoutMs: OPTIONAL_CONTEXT_TIMEOUT_MS }
    ).catch(() => null),
  ]);

  const projectStats = ctxRes?.ok ? ctxRes.data : undefined;
  const recentSummaries = summRes?.ok ? summRes.data?.summaries || [] : [];
  const agentMemory = memoryRes?.ok ? memoryRes.data?.memories || [] : [];
  const agentMemoryContext = memoryRes?.ok ? memoryRes.data?.context || '' : '';
  const systemPrompt = buildSystemPrompt({
    projectName,
    projectId,
    currentPage,
    projectStats,
    conversationHistory: recentSummaries,
    agentMemory,
    agentMemoryContext,
    pageContext,
  });

  const tools = createAssistantTools(authToken, projectId);
  const recentMessages = getRecentMessages(messages);

  if (useClaudeCode) {
    const bridgeRes = await backendFetch<{ text?: string }>('/chat/claude-code', {
      method: 'POST',
      authToken,
      timeoutMs: 120000,
      body: {
        prompt: buildClaudeCodeBridgePrompt(recentMessages) || latestUserText,
        system_prompt: systemPrompt,
        timeout_seconds: 120,
      },
    });

    if (bridgeRes.ok && bridgeRes.data?.text) {
      return textToUIMessageResponse(bridgeRes.data.text);
    }

    return textToUIMessageResponse(claudeCodeSubscriptionErrorMessage(bridgeRes.error));
  }

  if (!useAnthropic && !useOpenAI) {
    return textToUIMessageResponse(
      'AI chat tools are not configured. Save an API key in Settings first. If the backend settings service is unavailable, set QUORVEX_LLM_API_KEY or OPENAI_API_KEY for this server.'
    );
  }

  try {
    const modelMessages = await convertToModelMessages(recentMessages);
    const { provider, selectedModelId, providerName } = useAnthropic
      ? { ...getActiveProvider(runtimeSettings), selectedModelId: modelId, providerName: 'Anthropic' }
      : {
          ...getActiveOpenAIProvider(runtimeSettings),
          selectedModelId: runtimeSettings?.chat_model || runtimeSettings?.model_tiers?.chat || runtimeSettings?.standard_model || OPENAI_MODEL_ID,
          providerName: 'OpenAI',
        };
    const supportsThinking = useAnthropic && supportsExtendedThinking(selectedModelId);

    console.info(
      `[chat/route] routing chat through ${providerName} SDK provider model=${selectedModelId} messages=${recentMessages.length}/${messages.length}`
    );

    const result = streamText({
      model: provider(selectedModelId),
      system: systemPrompt,
      messages: modelMessages,
      maxOutputTokens: 2048,
      tools,
      stopWhen: stepCountIs(CHAT_TOOL_STEP_LIMIT),
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

    logTiming('stream created', startedAt);

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

    if (isRateLimit && useAnthropic) {
      const { slot: firstSlot } = getActiveProvider(runtimeSettings);
      reportRateLimit(firstSlot ?? undefined);

      try {
        console.warn('[chat/route] Rate limit hit, retrying with next key');
        const { provider: retryProvider } = getActiveProvider(runtimeSettings);
        const modelMessages = await convertToModelMessages(recentMessages);
        const supportsThinking = supportsExtendedThinking(modelId);

        const retryResult = streamText({
          model: retryProvider(modelId),
          system: systemPrompt,
          messages: modelMessages,
          maxOutputTokens: 2048,
          tools,
          stopWhen: stepCountIs(CHAT_TOOL_STEP_LIMIT),
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
