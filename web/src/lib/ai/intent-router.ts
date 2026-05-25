import { generateObject, type LanguageModel } from 'ai';
import { z } from 'zod';
import { backendFetch } from './backend-client';

export type AssistantIntentName =
  | 'startExplorerAgent'
  | 'startDiscoveryExploration'
  | 'startAdhocCustomAgent'
  | 'createCustomAgentDefinition'
  | 'createWorkflow'
  | 'startAutoPilot'
  | 'importOpenApiSpec'
  | 'createAndGenerateApiTest'
  | 'generateApiTest'
  | 'generateDatabaseSpec'
  | 'prdFeatureLookup'
  | 'unknown';

export interface IntentRouterContext {
  messages: unknown[];
  projectId?: string;
  currentPage?: string;
  pageContext?: Record<string, unknown>;
  authToken?: string;
  model: LanguageModel;
}

export type AssistantIntentRoute =
  | {
      kind: 'action';
      text: string;
      intent: AssistantIntentName;
      toolName: string;
      input: Record<string, unknown>;
      confidence: number;
      reason: string;
    }
  | {
      kind: 'clarify';
      text: string;
      intent: AssistantIntentName;
      confidence: number;
      missingFields: string[];
      reason: string;
    }
  | {
      kind: 'passthrough';
      intent: AssistantIntentName;
      confidence: number;
      reason: string;
    };

const ROUTER_MIN_CONFIDENCE = 0.68;
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

const intentSchema = z.object({
  intent: z.enum([
    'startExplorerAgent',
    'startDiscoveryExploration',
    'startAdhocCustomAgent',
    'createCustomAgentDefinition',
    'createWorkflow',
    'startAutoPilot',
    'importOpenApiSpec',
    'createAndGenerateApiTest',
    'generateApiTest',
    'generateDatabaseSpec',
    'prdFeatureLookup',
    'unknown',
  ]),
  confidence: z.number().min(0).max(1),
  toolName: z.string().nullable().optional(),
  input: z.record(z.any()).default({}),
  missingFields: z.array(z.string()).default([]),
  clarifyingQuestion: z.string().nullable().optional(),
  reason: z.string().default(''),
});

type RawIntentRoute = z.infer<typeof intentSchema>;

interface DatabaseConnectionSummary {
  id?: string;
  connection_id?: string;
  name?: string;
  database?: string;
  db_type?: string;
  type?: string;
  status?: string;
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

function extractLatestUserText(messages: unknown[]): string {
  const latestUser = [...messages].reverse().find((m: any) => m?.role === 'user') as any;
  return extractMessageText(latestUser);
}

function compactConversation(messages: unknown[]) {
  return messages
    .slice(-8)
    .map((message: any) => {
      const role = typeof message?.role === 'string' ? message.role : 'unknown';
      const text = extractMessageText(message).trim();
      return text ? `${role}: ${text.slice(0, 2000)}` : '';
    })
    .filter(Boolean)
    .join('\n\n');
}

function asString(value: unknown): string | undefined {
  return typeof value === 'string' && value.trim() ? value.trim() : undefined;
}

function asStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is string => typeof item === 'string' && item.trim().length > 0).map((item) => item.trim());
}

function asNumber(value: unknown, fallback: number): number {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value === 'string' && value.trim() && Number.isFinite(Number(value))) return Number(value);
  return fallback;
}

function hostnameLabel(rawUrl: string) {
  try {
    return new URL(rawUrl).hostname.replace(/^www\./, '').slice(0, 48) || 'website';
  } catch {
    return 'website';
  }
}

function validHttpUrl(value: unknown): string | undefined {
  const raw = asString(value);
  if (!raw) return undefined;
  try {
    const url = new URL(raw);
    if (url.protocol !== 'http:' && url.protocol !== 'https:') return undefined;
    return url.toString();
  } catch {
    return undefined;
  }
}

function firstUrlFromInput(input: Record<string, unknown>) {
  const direct = validHttpUrl(input.url) || validHttpUrl(input.targetUrl) || validHttpUrl(input.openApiUrl);
  if (direct) return direct;
  const urls = Array.isArray(input.urls) ? input.urls : [];
  return urls.map(validHttpUrl).find(Boolean);
}

function buildClarification(route: RawIntentRoute, missingFields: string[]) {
  const question = asString(route.clarifyingQuestion);
  if (question) return question;
  if (missingFields.includes('url')) return 'Which target URL should I use?';
  if (missingFields.includes('connectionId')) return 'Which database connection should I use?';
  if (missingFields.includes('specName')) return 'Which spec name should I use?';
  return 'Can you clarify the missing input before I prepare an action card?';
}

function passthrough(route: RawIntentRoute): AssistantIntentRoute {
  return {
    kind: 'passthrough',
    intent: route.intent,
    confidence: route.confidence,
    reason: route.reason,
  };
}

function clarify(route: RawIntentRoute, missingFields: string[]): AssistantIntentRoute {
  return {
    kind: 'clarify',
    text: buildClarification(route, missingFields),
    intent: route.intent,
    confidence: route.confidence,
    missingFields,
    reason: route.reason,
  };
}

function action(
  route: RawIntentRoute,
  toolName: string,
  input: Record<string, unknown>,
  text: string
): AssistantIntentRoute {
  return {
    kind: 'action',
    text,
    intent: route.intent,
    toolName,
    input,
    confidence: route.confidence,
    reason: route.reason,
  };
}

function normalizeDatabaseConnections(data: unknown): DatabaseConnectionSummary[] {
  if (Array.isArray(data)) return data as DatabaseConnectionSummary[];
  if (!data || typeof data !== 'object') return [];
  const record = data as Record<string, unknown>;
  const list = record.connections || record.items || record.data || record.results;
  return Array.isArray(list) ? list as DatabaseConnectionSummary[] : [];
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

async function resolveDatabaseConnection(
  route: RawIntentRoute,
  ctx: IntentRouterContext,
  baseInput: Record<string, unknown>
): Promise<AssistantIntentRoute> {
  const explicitConnectionId = asString(baseInput.connectionId) || asString(baseInput.connection_id);
  if (explicitConnectionId) {
    return action(
      route,
      'generateDatabaseSpec',
      {
        connectionId: explicitConnectionId,
        instructions: asString(baseInput.instructions) || extractLatestUserText(ctx.messages) || 'Generate a database testing spec from this connection.',
        specName: asString(baseInput.specName) || undefined,
      },
      'I prepared the database spec generation action below. Approve it to generate the spec without auto-running it.'
    );
  }

  const params = new URLSearchParams();
  if (ctx.projectId) params.set('project_id', ctx.projectId);
  const res = await backendFetch<unknown>(`/database-testing/connections${params.toString() ? `?${params}` : ''}`, {
    authToken: ctx.authToken,
    timeoutMs: 1500,
  });

  if (!res.ok) {
    return {
      kind: 'clarify',
      text: `I need a database connection before I can prepare that action, but I could not load the connection list: ${res.error || 'unknown error'}.`,
      intent: route.intent,
      confidence: route.confidence,
      missingFields: ['connectionId'],
      reason: route.reason,
    };
  }

  const connections = normalizeDatabaseConnections(res.data).filter(databaseConnectionId);
  if (connections.length === 1) {
    return action(
      route,
      'generateDatabaseSpec',
      {
        connectionId: databaseConnectionId(connections[0]),
        instructions: asString(baseInput.instructions) || extractLatestUserText(ctx.messages) || 'Generate a database testing spec from this connection.',
        specName: asString(baseInput.specName) || undefined,
      },
      'I found one database connection and prepared the spec generation action below. Approve it to generate the spec without auto-running it.'
    );
  }

  if (connections.length === 0) {
    return {
      kind: 'clarify',
      text: 'I do not see any configured database connections. Add one on /database-testing, then ask me to generate the database spec again.',
      intent: route.intent,
      confidence: route.confidence,
      missingFields: ['connectionId'],
      reason: route.reason,
    };
  }

  const choices = connections.slice(0, 10).map((connection) => `- ${databaseConnectionLabel(connection)}`).join('\n');
  return {
    kind: 'clarify',
    text: `Which database connection should I use?\n\n${choices}\n\nReply with the connection ID and I will prepare the approval action.`,
    intent: route.intent,
    confidence: route.confidence,
    missingFields: ['connectionId'],
    reason: route.reason,
  };
}

function buildApiSpecName(input: Record<string, unknown>, fallback: string) {
  const requested = asString(input.specName);
  if (requested) return requested.endsWith('.md') ? requested : `${requested}.md`;
  const slug = fallback
    .toLowerCase()
    .replace(/https?:\/\//g, '')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 48);
  return `${slug || 'chat-api-test'}-${Date.now()}.md`;
}

function slugLabel(value: string, fallback = 'workflow') {
  const slug = value
    .toLowerCase()
    .replace(/https?:\/\//g, '')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 48);
  return slug || fallback;
}

function buildWorkflowSteps(input: Record<string, unknown>, latestUserText: string, url?: string) {
  const agentDefinitionId = asString(input.agentDefinitionId)
    || asString(input.agent_definition_id)
    || '{{inputs.agent_definition_id}}';
  const targetUrl = url || asString(input.targetUrl) || asString(input.url) || '{{inputs.target_url}}';
  const prompt = asString(input.prompt)
    || asString(input.instructions)
    || latestUserText
    || 'Inspect the target app area, capture observed requirements, findings, evidence, and test ideas.';
  const mode = asString(input.mode) || 'both';
  const priorityThreshold = asString(input.priorityThreshold) || 'medium';
  const maxItems = asNumber(input.maxItems, 10);

  return [
    {
      key: 'agent',
      type: 'start_custom_agent',
      label: 'Run Custom Agent',
      input: {
        definition_id: agentDefinitionId,
        url: targetUrl,
        prompt,
      },
    },
    {
      key: 'wait_agent',
      type: 'wait_for_status',
      label: 'Wait for Agent',
      input: {
        source_step: 'agent',
        timeout_seconds: asNumber(input.timeoutSeconds, 3600),
        poll_seconds: 10,
      },
    },
    {
      key: 'review_agent',
      type: 'review_gate',
      label: 'Review Agent Report',
      input: {
        question: 'Review the custom agent report before creating requirements and specs.',
        suggested_answers: ['Create requirements and specs', 'Revise agent prompt'],
      },
    },
    {
      key: 'materialize',
      type: 'materialize_agent_report',
      label: 'Create Requirements And Specs',
      input: {
        source_step: 'wait_agent',
        mode: ['requirements', 'specs', 'both'].includes(mode) ? mode : 'both',
        max_items: maxItems,
        priority_threshold: ['critical', 'high', 'medium', 'low', 'info'].includes(priorityThreshold) ? priorityThreshold : 'medium',
      },
    },
    {
      key: 'review_output',
      type: 'review_gate',
      label: 'Review Created Artifacts',
      input: {
        question: 'Review the created requirements and specs before running tests.',
        suggested_answers: ['Accept', 'Edit artifacts first'],
      },
    },
  ];
}

function normalizeRoute(route: RawIntentRoute, ctx: IntentRouterContext): Promise<AssistantIntentRoute> | AssistantIntentRoute {
  if (route.intent === 'unknown' || route.intent === 'prdFeatureLookup') return passthrough(route);

  const missingFields = [...route.missingFields];
  if (route.confidence < ROUTER_MIN_CONFIDENCE) {
    return clarify(route, missingFields.length > 0 ? missingFields : ['intent']);
  }

  const input = route.input || {};
  const url = firstUrlFromInput(input);
  const latestUserText = extractLatestUserText(ctx.messages);

  if (['startExplorerAgent', 'startDiscoveryExploration', 'startAdhocCustomAgent', 'createCustomAgentDefinition', 'startAutoPilot', 'importOpenApiSpec'].includes(route.intent) && !url) {
    return clarify(route, Array.from(new Set([...missingFields, 'url'])));
  }

  if (route.intent === 'startExplorerAgent') {
    return action(
      route,
      'startExplorerAgent',
      {
        url,
        timeLimitMinutes: asNumber(input.timeLimitMinutes, 15),
        instructions: asString(input.instructions) || latestUserText || `Explore ${url} and identify meaningful test ideas from observed behavior.`,
        authType: asString(input.authType) || 'none',
        focusAreas: asStringArray(input.focusAreas),
      },
      'I prepared the Explorer Agent start action below. Approve it to start the run from the chatbot.'
    );
  }

  if (route.intent === 'startDiscoveryExploration') {
    return action(
      route,
      'startDiscoveryExploration',
      {
        url,
        instructions: asString(input.instructions) || latestUserText || `Explore ${url} and identify meaningful test ideas from observed behavior.`,
        strategy: asString(input.strategy) || 'goal_directed',
        maxInteractions: asNumber(input.maxInteractions, 50),
        maxDepth: asNumber(input.maxDepth, 10),
        timeoutMinutes: asNumber(input.timeoutMinutes, 30),
        focusAreas: asStringArray(input.focusAreas),
      },
      'I prepared the Discovery exploration start action below. Approve it to start the run from the chatbot.'
    );
  }

  if (route.intent === 'startAdhocCustomAgent') {
    const host = hostnameLabel(url || '');
    return action(
      route,
      'startAdhocCustomAgent',
      {
        url,
        agentName: asString(input.agentName) || `QA Agent - ${host}`,
        description: asString(input.description) || `Chat-created custom QA agent for ${url}.`,
        systemPrompt: asString(input.systemPrompt) || 'You are a focused QA automation agent. Inspect observable UI behavior and report concise findings, test ideas, evidence, and follow-up actions.',
        prompt: asString(input.prompt) || latestUserText || `Inspect ${url} and report useful QA findings.`,
        toolIds: asStringArray(input.toolIds).length > 0 ? asStringArray(input.toolIds) : DEFAULT_CHAT_CUSTOM_AGENT_TOOL_IDS,
        focusAreas: asStringArray(input.focusAreas),
        timeoutSeconds: asNumber(input.timeoutSeconds, 1800),
      },
      'I prepared an editable custom agent start action below. Review the prompt and tools, then approve to create the agent and start the run.'
    );
  }

  if (route.intent === 'createCustomAgentDefinition') {
    const host = hostnameLabel(url || '');
    return action(
      route,
      'createCustomAgentDefinition',
      {
        url,
        agentName: asString(input.agentName) || `QA Agent - ${host}`,
        description: asString(input.description) || `Chat-created reusable QA agent for ${url}.`,
        systemPrompt: asString(input.systemPrompt) || 'You are a focused QA automation agent. Inspect observable UI behavior and report concise findings, requirements, test ideas, evidence, and follow-up actions.',
        prompt: asString(input.prompt) || latestUserText || `Inspect ${url} and report useful QA findings.`,
        toolIds: asStringArray(input.toolIds).length > 0 ? asStringArray(input.toolIds) : DEFAULT_CHAT_CUSTOM_AGENT_TOOL_IDS,
        focusAreas: asStringArray(input.focusAreas),
        timeoutSeconds: asNumber(input.timeoutSeconds, 1800),
      },
      'I prepared an editable custom agent definition below. Review the prompt and tools, then approve to save it.'
    );
  }

  if (route.intent === 'createWorkflow') {
    const name = asString(input.name)
      || `Agent requirements workflow - ${url ? hostnameLabel(url) : slugLabel(latestUserText, 'custom')}`;
    const description = asString(input.description)
      || 'Chat-created workflow that runs a browser QA agent, waits for its report, pauses for review, and creates candidate requirements and markdown specs.';
    return action(
      route,
      'createWorkflow',
      {
        name,
        description,
        steps: buildWorkflowSteps(input, latestUserText, url),
        trigger: { type: 'manual', source: 'chat' },
        config: {
          requiresRuntimeInputs: {
            agent_definition_id: !asString(input.agentDefinitionId) && !asString(input.agent_definition_id),
            target_url: !url && !asString(input.targetUrl) && !asString(input.url),
          },
          output: 'requirements_and_specs',
        },
      },
      'I prepared a reusable custom workflow approval action below. Approve it to save the workflow; when run, it will execute a saved custom agent, review the report, then create requirements and specs.'
    );
  }

  if (route.intent === 'startAutoPilot') {
    return action(
      route,
      'startAutoPilot',
      {
        urls: [url],
        instructions: asString(input.instructions) || latestUserText || `Find important test cases from ${url}.`,
        strategy: asString(input.strategy) || 'goal_directed',
        maxInteractions: asNumber(input.maxInteractions, 50),
        maxDepth: asNumber(input.maxDepth, 10),
        timeoutMinutes: asNumber(input.timeoutMinutes, 30),
        reactiveMode: input.reactiveMode !== false,
        priorityThreshold: asString(input.priorityThreshold) || 'low',
        maxSpecs: asNumber(input.maxSpecs, 50),
        parallelGeneration: asNumber(input.parallelGeneration, 2),
        hybridHealing: Boolean(input.hybridHealing),
      },
      'I prepared the real Auto Pilot start action below. Approve it to start the run from the chatbot.'
    );
  }

  if (route.intent === 'importOpenApiSpec') {
    return action(route, 'importOpenApiSpec', { url }, 'I prepared an OpenAPI import action below. Approve it to import the spec and generate API tests.');
  }

  if (route.intent === 'generateApiTest') {
    const specName = asString(input.specName);
    if (!specName) return clarify(route, Array.from(new Set([...missingFields, 'specName'])));
    return action(route, 'generateApiTest', { specName }, 'I prepared the API test generation action below. Approve it to generate Playwright API tests from the existing spec.');
  }

  if (route.intent === 'createAndGenerateApiTest') {
    const content = asString(input.content);
    if (!content) return clarify(route, Array.from(new Set([...missingFields, 'content'])));
    return action(
      route,
      'createAndGenerateApiTest',
      {
        specName: buildApiSpecName(input, url || 'chat-api-test'),
        content,
      },
      'I prepared an API spec and generation action below. Approve it to create the spec and generate Playwright API tests.'
    );
  }

  if (route.intent === 'generateDatabaseSpec') {
    return resolveDatabaseConnection(route, ctx, input);
  }

  return passthrough(route);
}

export async function routeAssistantIntent(ctx: IntentRouterContext): Promise<AssistantIntentRoute | null> {
  const latestUserText = extractLatestUserText(ctx.messages);
  if (!latestUserText.trim()) return null;

  try {
    const { object } = await generateObject({
      model: ctx.model,
      schema: intentSchema,
      temperature: 0,
      maxOutputTokens: 1200,
      system: [
        'You classify Quorvex AI chatbot requests into structured intents.',
        'Only classify a mutating or start/generate intent when the user explicitly asks to create, generate, import, run, start, launch, or proceed.',
        'Use createCustomAgentDefinition when the user asks to save, define, or build a reusable custom agent without starting it now.',
        'Use createWorkflow when the user asks to create, save, define, or build a reusable workflow/process/pipeline that runs a custom agent and turns its report into requirements or specs.',
        'For normal questions, status questions, explanations, analysis requests, and vague asks, use intent "unknown" so the main assistant can answer.',
        'Never invent required identifiers. If a required URL, spec name, or database connection is missing, set missingFields and write one concise clarifyingQuestion.',
        'Return tool input using camelCase keys expected by the UI action cards.',
        'For API spec creation, include a complete markdown spec in input.content only when the user provided enough endpoint or demo intent to create one.',
      ].join(' '),
      prompt: [
        `Current page: ${ctx.currentPage || 'unknown'}`,
        `Page context: ${JSON.stringify(ctx.pageContext || {})}`,
        '',
        'Recent conversation:',
        compactConversation(ctx.messages),
        '',
        'Latest user message:',
        latestUserText,
      ].join('\n'),
    });

    return normalizeRoute(object, ctx);
  } catch (error) {
    console.warn('[chat/intent-router] routing skipped:', error);
    return null;
  }
}
