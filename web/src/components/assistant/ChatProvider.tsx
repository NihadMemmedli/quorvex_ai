'use client';

import {
  ReactNode,
  createContext,
  useContext,
  useState,
  useCallback,
  useEffect,
  useRef,
} from 'react';
import { AssistantRuntimeProvider, useThread, useThreadRuntime, SimpleImageAttachmentAdapter } from '@assistant-ui/react';
import { useChatRuntime } from '@assistant-ui/react-ai-sdk';
import { DefaultChatTransport, type UIMessage } from 'ai';
import { fetchWithAuth, useAuth } from '@/contexts/AuthContext';
import { useProject } from '@/contexts/ProjectContext';
import { usePathname } from 'next/navigation';
import { toast } from 'sonner';
import { API_BASE } from '@/lib/api';
import {
  Conversation,
  ChatMessageRecord,
  listConversations,
  createConversation,
  deleteConversation as deleteConv,
  getMessages,
  saveMessage,
  saveMessagesBulk,
  autoTitle,
  generateSummary,
  updateMessageContentJson,
} from '@/lib/chat-api';

// Helper to generate unique IDs for UIMessage objects
let msgIdCounter = 0;
function genMsgId(): string {
  return `hist-${Date.now()}-${++msgIdCounter}`;
}

// Message type used for saving — includes content_json for round-trip fidelity
type SaveableMessage = { role: string; content: string; content_json?: string };

// Convert loaded DB messages to UIMessage format, restoring full parts from content_json
function toUIMessages(msgs: Array<{ role: string; content: string; content_json?: string | null }>): UIMessage[] {
  return msgs.map((m) => {
    // If content_json exists, restore the full parts array for round-trip fidelity
    if (m.content_json) {
      try {
        const rawParts = JSON.parse(m.content_json);
        if (Array.isArray(rawParts) && rawParts.length > 0) {
          // Normalize parts: convert any ThreadMessage format (tool-call/tool-result)
          // to UIMessage format (dynamic-tool) for correct round-trip through the SDK
          const parts = threadPartsToUIParts(rawParts);
          if (parts.length > 0) {
            return {
              id: genMsgId(),
              role: m.role as 'user' | 'assistant',
              parts,
            };
          }
        }
      } catch {
        // Fall through to plain text
      }
    }
    return {
      id: genMsgId(),
      role: m.role as 'user' | 'assistant',
      parts: [{ type: 'text' as const, text: m.content }],
    };
  });
}

// Extract text content from ThreadMessage content parts (for backwards-compatible text column)
function extractTextFromParts(contentParts: any[]): string {
  return contentParts
    .filter((p: any) => p.type === 'text')
    .map((p: any) => p.text)
    .join('\n');
}

// Convert ThreadMessage content parts (tool-call/tool-result) to UIMessage DynamicToolUIPart format.
// This bridges the format gap: @assistant-ui uses {type:'tool-call', toolName, args, result}
// while Vercel AI SDK expects {type:'dynamic-tool', toolName, state, input, output}.
// Parts already in correct format pass through unchanged.
function threadPartsToUIParts(parts: any[]): any[] {
  if (!Array.isArray(parts)) return parts;

  // Collect tool-result parts by toolCallId for merging into tool-call parts
  const resultMap = new Map<string, any>();
  for (const p of parts) {
    if (p.type === 'tool-result' && p.toolCallId) {
      resultMap.set(p.toolCallId, p.result);
    }
  }

  const converted: any[] = [];
  for (const p of parts) {
    if (p.type === 'tool-call') {
      // Convert tool-call → dynamic-tool
      const hasResult = p.result !== undefined || resultMap.has(p.toolCallId);
      const output = p.result !== undefined ? p.result : resultMap.get(p.toolCallId);
      converted.push({
        type: 'dynamic-tool',
        toolCallId: p.toolCallId,
        toolName: p.toolName,
        state: hasResult ? 'output-available' : 'input-available',
        input: p.args ?? p.input ?? {},
        output: hasResult ? output : undefined,
      });
    } else if (p.type === 'tool-result') {
      // Skip standalone tool-result if we already merged it into a tool-call above
      if (resultMap.has(p.toolCallId)) continue;
      // Orphan tool-result with no matching tool-call — convert to dynamic-tool
      converted.push({
        type: 'dynamic-tool',
        toolCallId: p.toolCallId,
        toolName: p.toolName,
        state: 'output-available',
        input: {},
        output: p.result,
      });
    } else if (p.type === 'text' && (!p.text || p.text.trim() === '')) {
      // Filter out empty text parts that could cause blank bubbles
      continue;
    } else {
      // Already correct format (dynamic-tool, text, etc.) — pass through
      converted.push(p);
    }
  }
  return converted;
}

// Types for the chat context
interface ChatContextType {
  conversationId: string | null;
  conversations: Conversation[];
  createNewConversation: () => void;
  switchConversation: (id: string) => void;
  deleteConversation: (id: string) => Promise<void>;
  refreshConversations: () => Promise<Conversation[] | void>;
  isLoadingHistory: boolean;
  persistToolResult: (toolCallId: string, toolName: string, result: unknown) => void;
  registerTrackedJob: (toolName: string, result: unknown, args?: Record<string, unknown>, label?: string) => boolean;
}

const ChatContext = createContext<ChatContextType | null>(null);

export function useChatContext() {
  const ctx = useContext(ChatContext);
  if (!ctx) throw new Error('useChatContext must be used within ChatProvider');
  return ctx;
}

// Child component that subscribes to thread state via useThread hook.
// Must be rendered inside AssistantRuntimeProvider.
function ThreadMessageTracker({
  onNewMessages,
}: {
  onNewMessages: (messages: SaveableMessage[]) => void;
}) {
  const thread = useThread();
  const lastSavedIndexRef = useRef(0);
  const wasRunningRef = useRef(false);
  const initializedRef = useRef(false);

  useEffect(() => {
    const { isRunning, messages } = thread;

    // On first render with pre-loaded messages (restored conversation),
    // skip already-saved messages to prevent duplicate saving
    if (!initializedRef.current && messages.length > 0) {
      initializedRef.current = true;
      if (!isRunning) {
        lastSavedIndexRef.current = messages.length;
        return;
      }
    }

    // Detect run completion: was running, now stopped
    if (wasRunningRef.current && !isRunning && messages.length > 0) {
      // Save all unsaved messages
      const unsaved: SaveableMessage[] = [];
      for (let i = lastSavedIndexRef.current; i < messages.length; i++) {
        const msg = messages[i];
        if (!msg) continue;
        const role = msg.role;
        if (role !== 'user' && role !== 'assistant') continue;
        // ThreadMessage uses `content` for parts array
        const contentParts = (msg as any).content || [];
        const textContent = extractTextFromParts(contentParts);
        // Convert ThreadMessage parts to UIMessage format before saving
        const uiParts = threadPartsToUIParts(contentParts);
        unsaved.push({
          role,
          content: textContent,
          content_json: JSON.stringify(uiParts),
        });
      }
      if (unsaved.length > 0) {
        lastSavedIndexRef.current = messages.length;
        onNewMessages(unsaved);
      }
    }

    wasRunningRef.current = isRunning;
  }, [thread, thread.isRunning, thread.messages, onNewMessages]);

  return null;
}

// Extract entity context from the current URL pathname
interface PageContext {
  section?: string;
  viewingRunId?: string;
  viewingSpecName?: string;
  viewingBatchId?: string;
  viewingSessionId?: string;
  viewingLoadRunId?: string;
  viewingSecurityRunId?: string;
  viewingDbRunId?: string;
}

type TrackedJobKind =
  | 'autopilot'
  | 'agent'
  | 'exploration'
  | 'api-job'
  | 'load-job'
  | 'security-job'
  | 'database-job'
  | 'prd-generation'
  | 'regression-batch'
  | 'test-run'
  | 'workflow-run';

interface TrackedChatJob {
  key: string;
  kind: TrackedJobKind;
  toolName: string;
  label: string;
  id: string;
  statusPath: string;
  pagePath: string;
  projectId?: string;
  conversationId?: string | null;
  createdAt: number;
  startedMessageSent?: boolean;
  lastStatus?: string;
  lastPhase?: string;
  lastQuestionId?: string;
  lastMessageKey?: string;
  terminalReported?: boolean;
  pollCount?: number;
}

interface JobSnapshot {
  status: string;
  phase?: string;
  message?: string;
  data: any;
  questions?: any[];
  specTasks?: any[];
  testTasks?: any[];
}

const TERMINAL_STATUSES = new Set([
  'completed',
  'failed',
  'cancelled',
  'canceled',
  'stopped',
  'passed',
  'error',
  'success',
]);

const ACTIVE_STATUSES = new Set(['pending', 'queued', 'running', 'in_progress', 'awaiting_input', 'generating']);

const API_JOB_TOOLS = new Set([
  'createAndGenerateApiTest',
  'importOpenApiSpec',
  'generateApiTest',
  'runApiTest',
  'runApiTestDirect',
  'generateApiEdgeCases',
]);

const LOAD_JOB_TOOLS = new Set([
  'generateLoadScript',
  'runLoadTest',
  'runLoadTestFromSpec',
  'analyzeLoadTestRun',
]);

const SECURITY_JOB_TOOLS = new Set([
  'triggerSecurityScan',
  'runSecurityScan',
  'analyzeSecurityRun',
]);

const DATABASE_JOB_TOOLS = new Set(['generateDatabaseSpec']);
const PRD_GENERATION_TOOLS = new Set(['generatePrdPlan', 'generatePrdTest', 'healPrdTest']);
const REGRESSION_BATCH_TOOLS = new Set(['runRegressionBatch', 'rerunFailedTests', 'runPrAdvisorRecommendedTests']);
const TEST_RUN_TOOLS = new Set(['runTestSpec', 'retryFailedRun', 'healFailedRun', 'runPrdTest']);

function stringValue(data: any, keys: string[]): string | undefined {
  for (const key of keys) {
    const value = data?.[key];
    if (typeof value === 'string' && value.trim()) return value;
    if (typeof value === 'number') return String(value);
  }
  return undefined;
}

function normalizeStatus(value: unknown): string {
  return String(value || 'unknown').toLowerCase();
}

function projectQuery(projectId?: string) {
  return projectId ? `?project_id=${encodeURIComponent(projectId)}` : '';
}

function makeTrackedJob(
  toolName: string,
  result: unknown,
  args: Record<string, unknown> | undefined,
  label: string | undefined,
  projectId: string | undefined,
  conversationId: string | null | undefined,
  startedMessageSent = false
): TrackedChatJob | null {
  const data = result && typeof result === 'object' ? result as Record<string, any> : {};
  if (data.error || data.cancelled) return null;

  const displayLabel = label || data?._assistantAction?.label || toolName;
  let kind: TrackedJobKind | null = null;
  let id: string | undefined;
  let statusPath = '';
  let pagePath = '/';

  if (toolName === 'startAutoPilot') {
    kind = 'autopilot';
    id = stringValue(data, ['session_id', 'sessionId', 'id']);
    statusPath = `/autopilot/${encodeURIComponent(id || '')}`;
    pagePath = '/autopilot';
  } else if (['startExplorerAgent', 'startAdhocCustomAgent', 'startCustomAgentFromReport'].includes(toolName)) {
    kind = 'agent';
    id = stringValue(data, ['run_id', 'runId', 'id']);
    statusPath = `/api/agents/runs/${encodeURIComponent(id || '')}${projectQuery(projectId)}`;
    pagePath = '/agents';
  } else if (['startDiscoveryExploration', 'startExploration'].includes(toolName)) {
    kind = 'exploration';
    id = stringValue(data, ['session_id', 'sessionId', 'id']);
    statusPath = `/exploration/${encodeURIComponent(id || '')}${projectQuery(projectId)}`;
    pagePath = '/exploration';
  } else if (API_JOB_TOOLS.has(toolName)) {
    kind = 'api-job';
    id = stringValue(data, ['job_id', 'jobId']);
    statusPath = `/api-testing/jobs/${encodeURIComponent(id || '')}`;
    pagePath = '/api-testing';
  } else if (LOAD_JOB_TOOLS.has(toolName)) {
    kind = 'load-job';
    id = stringValue(data, ['job_id', 'jobId']);
    statusPath = `/load-testing/jobs/${encodeURIComponent(id || '')}`;
    pagePath = '/load-testing';
  } else if (SECURITY_JOB_TOOLS.has(toolName)) {
    kind = 'security-job';
    id = stringValue(data, ['job_id', 'jobId']);
    statusPath = `/security-testing/jobs/${encodeURIComponent(id || '')}`;
    pagePath = '/security-testing';
  } else if (DATABASE_JOB_TOOLS.has(toolName)) {
    kind = 'database-job';
    id = stringValue(data, ['job_id', 'jobId']);
    statusPath = `/database-testing/jobs/${encodeURIComponent(id || '')}`;
    pagePath = '/database-testing';
  } else if (PRD_GENERATION_TOOLS.has(toolName)) {
    kind = 'prd-generation';
    id = stringValue(data, ['generation_id', 'generationId', 'id']);
    statusPath = `/prd/generation/${encodeURIComponent(id || '')}`;
    pagePath = '/prd';
  } else if (REGRESSION_BATCH_TOOLS.has(toolName)) {
    kind = 'regression-batch';
    id = stringValue(data, ['batch_id', 'batchId', 'id']);
    statusPath = `/regression/batches/${encodeURIComponent(id || '')}`;
    pagePath = '/regression';
  } else if (TEST_RUN_TOOLS.has(toolName)) {
    kind = 'test-run';
    id = stringValue(data, ['run_id', 'runId', 'id']) || stringValue(args, ['runId']);
    statusPath = `/runs/${encodeURIComponent(id || '')}`;
    pagePath = id ? `/runs/${encodeURIComponent(id)}` : '/runs';
  } else if (toolName === 'startWorkflow') {
    kind = 'workflow-run';
    id = stringValue(data, ['run_id', 'runId', 'id']);
    statusPath = `/workflows/runs/${encodeURIComponent(id || '')}`;
    pagePath = '/workflow';
  }

  if (!kind || !id || !statusPath.includes(encodeURIComponent(id))) return null;

  return {
    key: `${toolName}:${kind}:${id}`,
    kind,
    toolName,
    label: displayLabel,
    id,
    statusPath,
    pagePath,
    projectId,
    conversationId,
    createdAt: Date.now(),
    startedMessageSent,
  };
}

function trackedJobsFromMessages(
  messages: Array<{ role: string; content: string; content_json?: string | null }>,
  projectId: string | undefined,
  conversationId: string
): TrackedChatJob[] {
  const jobs = new Map<string, TrackedChatJob>();
  const conversationText = messages.map((message) => message.content || '').join('\n');
  for (const message of messages) {
    if (message.role !== 'assistant' || !message.content_json) continue;
    let parts: any[];
    try {
      parts = JSON.parse(message.content_json);
    } catch {
      continue;
    }
    if (!Array.isArray(parts)) continue;
    for (const part of parts) {
      const toolName = part?.toolName;
      if (!toolName) continue;
      const output = part.output ?? part.result;
      const input = part.input ?? part.args;
      const job = makeTrackedJob(toolName, output, input, undefined, projectId, conversationId, true);
      if (job) {
        job.terminalReported = conversationText.includes(`ID: ${job.id}`)
          && /\b(completed|failed|cancelled|canceled|stopped|passed|error|success)\b/i.test(conversationText);
        jobs.set(job.key, job);
      }
    }
  }
  return [...jobs.values()];
}

async function fetchJson(path: string) {
  const res = await fetchWithAuth(`${API_BASE}${path}`);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data?.detail || data?.error || `Status request failed with ${res.status}`);
  }
  return data;
}

async function fetchJobSnapshot(job: TrackedChatJob): Promise<JobSnapshot> {
  const data = await fetchJson(job.statusPath);
  if (job.kind === 'autopilot') {
    const [questions, specTasks, testTasks] = await Promise.all([
      fetchJson(`/autopilot/${encodeURIComponent(job.id)}/questions`).catch(() => []),
      fetchJson(`/autopilot/${encodeURIComponent(job.id)}/spec-tasks`).catch(() => []),
      fetchJson(`/autopilot/${encodeURIComponent(job.id)}/test-tasks`).catch(() => []),
    ]);
    return {
      data,
      questions: Array.isArray(questions) ? questions : questions?.questions || [],
      specTasks: Array.isArray(specTasks) ? specTasks : [],
      testTasks: Array.isArray(testTasks) ? testTasks : [],
      status: normalizeStatus(data.status),
      phase: data.current_phase || undefined,
      message: data.error_message || undefined,
    };
  }

  return {
    data,
    status: normalizeStatus(data.status || data.final_status || data.state),
    phase: data.stage || data.current_stage || data.current_phase || undefined,
    message: data.message || data.error || data.error_message || data.detail || undefined,
  };
}

function statusLabel(status: string) {
  return status.replace(/_/g, ' ');
}

function formatAutoPilotTerminal(job: TrackedChatJob, snapshot: JobSnapshot) {
  const data = snapshot.data || {};
  const testTasks = snapshot.testTasks || [];
  const failedTasks = testTasks.filter((task) => ['failed', 'error'].includes(normalizeStatus(task.status)) || task.passed === false);
  const lines = [
    `Auto Pilot ${statusLabel(snapshot.status)}.`,
    `ID: ${job.id}`,
    '',
    `- Requirements: ${data.total_requirements_generated ?? 0}`,
    `- Specs: ${data.total_specs_generated ?? snapshot.specTasks?.filter((task) => normalizeStatus(task.status) === 'completed').length ?? 0}`,
    `- Tests generated: ${data.total_tests_generated ?? testTasks.length}`,
    `- Tests passed: ${data.total_tests_passed ?? testTasks.filter((task) => task.passed === true).length}`,
    `- Tests failed: ${data.total_tests_failed ?? failedTasks.length}`,
    `- Coverage: ${typeof data.coverage_percentage === 'number' ? `${Math.round(data.coverage_percentage)}%` : 'not available'}`,
  ];
  if (snapshot.message) lines.push('', `Note: ${snapshot.message}`);
  lines.push('', `[Open Auto Pilot](${job.pagePath})`);
  return lines.join('\n');
}

function buildJobMessage(job: TrackedChatJob, snapshot: JobSnapshot): { key: string; text: string; terminal?: boolean; toast?: string } | null {
  const status = snapshot.status;
  const terminal = TERMINAL_STATUSES.has(status);

  if (job.kind === 'autopilot') {
    const pendingQuestion = (snapshot.questions || []).find((question) => normalizeStatus(question.status) === 'pending');
    if (pendingQuestion && status === 'awaiting_input') {
      const questionId = String(pendingQuestion.id);
      const suggestions = Array.isArray(pendingQuestion.suggested_answers)
        ? pendingQuestion.suggested_answers
        : [];
      return {
        key: `question:${questionId}`,
        toast: 'Auto Pilot needs your input',
        text: [
          'Auto Pilot needs your input.',
          `ID: ${job.id}`,
          '',
          `**Question**: ${pendingQuestion.question_text}`,
          suggestions.length > 0 ? `\nSuggested answers:\n${suggestions.map((answer: string) => `- ${answer}`).join('\n')}` : '',
          pendingQuestion.auto_continue_at ? `\nAuto-continues at: ${pendingQuestion.auto_continue_at}` : '',
          '',
          `[Open Auto Pilot](${job.pagePath})`,
        ].filter(Boolean).join('\n'),
      };
    }

    if (terminal) {
      return {
        key: `terminal:${status}`,
        terminal: true,
        toast: `Auto Pilot ${statusLabel(status)}`,
        text: formatAutoPilotTerminal(job, snapshot),
      };
    }

    if (job.lastStatus && (job.lastStatus !== status || job.lastPhase !== snapshot.phase) && ACTIVE_STATUSES.has(status)) {
      return {
        key: `status:${status}:${snapshot.phase || ''}`,
        toast: `Auto Pilot ${statusLabel(status)}`,
        text: [
          `Auto Pilot is ${statusLabel(status)}${snapshot.phase ? ` in ${snapshot.phase}` : ''}.`,
          `ID: ${job.id}`,
          snapshot.message ? `\n${snapshot.message}` : '',
          '',
          `[Open Auto Pilot](${job.pagePath})`,
        ].filter(Boolean).join('\n'),
      };
    }
    return null;
  }

  if (terminal) {
    return {
      key: `terminal:${status}`,
      terminal: true,
      toast: `${job.label} ${statusLabel(status)}`,
      text: [
        `${job.label} ${statusLabel(status)}.`,
        `ID: ${job.id}`,
        snapshot.message ? `\n${snapshot.message}` : '',
        '',
        `[Open in dashboard](${job.pagePath})`,
      ].filter(Boolean).join('\n'),
    };
  }

  if (job.lastStatus && (job.lastStatus !== status || job.lastPhase !== snapshot.phase) && ACTIVE_STATUSES.has(status)) {
    return {
      key: `status:${status}:${snapshot.phase || ''}`,
      toast: `${job.label} ${statusLabel(status)}`,
      text: [
        `${job.label} is ${statusLabel(status)}${snapshot.phase ? ` (${snapshot.phase})` : ''}.`,
        `ID: ${job.id}`,
        snapshot.message ? `\n${snapshot.message}` : '',
        '',
        `[Open in dashboard](${job.pagePath})`,
      ].filter(Boolean).join('\n'),
    };
  }

  return null;
}

function usePageContext(pathname: string): PageContext {
  const ctx: PageContext = {};

  // Detect section from URL
  const segments = pathname.split('/').filter(Boolean);
  if (segments.length > 0) {
    ctx.section = segments[0];
  }

  // Extract entity IDs from URL patterns
  const patterns: Array<{ regex: RegExp; key: keyof PageContext }> = [
    { regex: /^\/runs\/([^/]+)/, key: 'viewingRunId' },
    { regex: /^\/specs\/([^/]+)/, key: 'viewingSpecName' },
    { regex: /^\/regression\/batches\/([^/]+)/, key: 'viewingBatchId' },
    { regex: /^\/exploration\/([^/]+)/, key: 'viewingSessionId' },
    { regex: /^\/load-testing\/runs\/([^/]+)/, key: 'viewingLoadRunId' },
    { regex: /^\/security-testing\/runs\/([^/]+)/, key: 'viewingSecurityRunId' },
    { regex: /^\/database-testing\/runs\/([^/]+)/, key: 'viewingDbRunId' },
  ];

  for (const { regex, key } of patterns) {
    const match = pathname.match(regex);
    if (match && match[1]) {
      ctx[key] = decodeURIComponent(match[1]);
      break;
    }
  }

  return ctx;
}

// Inner component that manages the assistant-ui runtime.
// Keyed by conversationId so it remounts when conversation changes.
function RuntimeProvider({
  children,
  conversationId,
  initialMessages,
  onNewMessages,
  trackedJobs,
  onTrackedJobPatch,
  onTrackedJobComplete,
  saveAssistantFollowup,
}: {
  children: ReactNode;
  conversationId: string | null;
  initialMessages?: Array<{ role: string; content: string; content_json?: string | null }>;
  onNewMessages?: (messages: SaveableMessage[]) => void;
  trackedJobs: TrackedChatJob[];
  onTrackedJobPatch: (key: string, patch: Partial<TrackedChatJob>) => void;
  onTrackedJobComplete: (key: string) => void;
  saveAssistantFollowup: (content: string, conversationId?: string | null) => Promise<void>;
}) {
  const { getAccessToken } = useAuth();
  const { currentProject } = useProject();
  const pathname = usePathname();
  const pageContext = usePageContext(pathname);

  // Convert DB messages to UIMessage format (with content_json restoration)
  const uiMessages = initialMessages ? toUIMessages(initialMessages) : undefined;

  const runtime = useChatRuntime({
    transport: new DefaultChatTransport({
      api: '/api/chat',
      body: {
        projectId: currentProject?.id,
        projectName: currentProject?.name,
        currentPage: pathname,
        conversationId,
        pageContext,
      },
      headers: (): Record<string, string> => {
        const token = getAccessToken();
        return token ? { Authorization: `Bearer ${token}` } : {};
      },
    }),
    adapters: {
      attachments: new SimpleImageAttachmentAdapter(),
    },
    messages: uiMessages,
  });

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <ChatJobWatcher
        jobs={trackedJobs}
        onJobPatch={onTrackedJobPatch}
        onJobComplete={onTrackedJobComplete}
        saveAssistantFollowup={saveAssistantFollowup}
      />
      {onNewMessages && <ThreadMessageTracker onNewMessages={onNewMessages} />}
      {children}
    </AssistantRuntimeProvider>
  );
}

function ChatJobWatcher({
  jobs,
  onJobPatch,
  onJobComplete,
  saveAssistantFollowup,
}: {
  jobs: TrackedChatJob[];
  onJobPatch: (key: string, patch: Partial<TrackedChatJob>) => void;
  onJobComplete: (key: string) => void;
  saveAssistantFollowup: (content: string, conversationId?: string | null) => Promise<void>;
}) {
  const runtime = useThreadRuntime();
  const jobsRef = useRef(jobs);
  const failureCountsRef = useRef(new Map<string, number>());

  useEffect(() => {
    jobsRef.current = jobs;
  }, [jobs]);

  const appendFollowup = useCallback(async (job: TrackedChatJob, text: string, toastText?: string) => {
    runtime.append({
      role: 'assistant',
      content: [{ type: 'text', text }],
    });
    if (toastText) toast.info(toastText);
    await saveAssistantFollowup(text, job.conversationId);
  }, [runtime, saveAssistantFollowup]);

  useEffect(() => {
    if (jobs.length === 0) return;

    let cancelled = false;
    let timeout: ReturnType<typeof setTimeout> | undefined;

    async function pollOne(job: TrackedChatJob) {
      const ageMs = Date.now() - job.createdAt;
      if (ageMs > 2 * 60 * 60 * 1000) {
        onJobComplete(job.key);
        return;
      }

      if (!job.startedMessageSent) {
        const text = [
          `I started ${job.label} and I am watching it from this chat.`,
          `ID: ${job.id}`,
          '',
          `[Open in dashboard](${job.pagePath})`,
        ].join('\n');
        await appendFollowup(job, text, `${job.label} started`);
        onJobPatch(job.key, {
          startedMessageSent: true,
          lastMessageKey: 'started',
        });
      }

      try {
        const snapshot = await fetchJobSnapshot(job);
        failureCountsRef.current.delete(job.key);

        if (job.terminalReported && TERMINAL_STATUSES.has(snapshot.status)) {
          onJobComplete(job.key);
          return;
        }

        const patch: Partial<TrackedChatJob> = {
          lastStatus: snapshot.status,
          lastPhase: snapshot.phase,
          pollCount: (job.pollCount || 0) + 1,
        };
        const pendingQuestion = (snapshot.questions || []).find((question) => normalizeStatus(question.status) === 'pending');
        if (pendingQuestion) patch.lastQuestionId = String(pendingQuestion.id);

        const message = buildJobMessage(job, snapshot);
        if (message && message.key !== job.lastMessageKey) {
          await appendFollowup(job, message.text, message.toast);
          patch.lastMessageKey = message.key;
        }

        onJobPatch(job.key, patch);
        if (message?.terminal || TERMINAL_STATUSES.has(snapshot.status)) {
          onJobComplete(job.key);
        }
      } catch (error) {
        const failures = (failureCountsRef.current.get(job.key) || 0) + 1;
        failureCountsRef.current.set(job.key, failures);
        onJobPatch(job.key, { pollCount: (job.pollCount || 0) + 1 });

        if (failures === 3 && job.lastMessageKey !== 'poll-error') {
          const text = [
            `I lost live status updates for ${job.label}.`,
            '',
            error instanceof Error ? error.message : 'The status endpoint returned an error.',
            '',
            `[Open in dashboard](${job.pagePath})`,
          ].join('\n');
          await appendFollowup(job, text, `${job.label} status unavailable`);
          onJobPatch(job.key, { lastMessageKey: 'poll-error' });
        }

        if (failures >= 5) onJobComplete(job.key);
      }
    }

    async function tick() {
      const activeJobs = jobsRef.current;
      for (const job of activeJobs) {
        if (cancelled) return;
        await pollOne(job);
      }

      if (!cancelled && jobsRef.current.length > 0) {
        const fastest = jobsRef.current.some((job) => (job.pollCount || 0) < 12);
        timeout = setTimeout(tick, fastest ? 5000 : 15000);
      }
    }

    void tick();

    return () => {
      cancelled = true;
      if (timeout) clearTimeout(timeout);
    };
  }, [jobs.length, appendFollowup, onJobComplete, onJobPatch]);

  return null;
}

const LAST_CONVERSATION_KEY = 'chat-last-conversation-id';

export function ChatProvider({ children }: { children: ReactNode }) {
  const { currentProject } = useProject();
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [initialMessages, setInitialMessages] = useState<
    Array<{ role: string; content: string; content_json?: string | null }> | undefined
  >(undefined);
  const [isLoadingHistory, setIsLoadingHistory] = useState(false);
  const [trackedJobs, setTrackedJobs] = useState<TrackedChatJob[]>([]);
  const [runtimeKey, setRuntimeKey] = useState<string>('new');
  const conversationCreatedRef = useRef(false);
  const creatingRef = useRef(false);
  const autoResumedRef = useRef(false);

  // Persist conversationId to localStorage whenever it changes
  useEffect(() => {
    if (conversationId) {
      try { localStorage.setItem(LAST_CONVERSATION_KEY, conversationId); } catch { /* noop */ }
    }
  }, [conversationId]);

  const refreshConversations = useCallback(async () => {
    try {
      const data = await listConversations(currentProject?.id);
      setConversations(data.conversations);
      return data.conversations;
    } catch (err) {
      console.error('Failed to load conversations:', err);
      toast.error('Failed to load conversations');
      return [];
    }
  }, [currentProject?.id]);

  const switchConversation = useCallback(async (id: string) => {
    setIsLoadingHistory(true);
    try {
      const data = await getMessages(id);
      // Preserve content_json for round-trip fidelity
      const msgs = data.messages.map((m: ChatMessageRecord) => ({
        role: m.role as 'user' | 'assistant',
        content: m.content,
        content_json: m.content_json || undefined,
      }));
      setConversationId(id);
      setInitialMessages(msgs);
      setTrackedJobs(trackedJobsFromMessages(msgs, currentProject?.id, id));
      setRuntimeKey(`conv-${id}`);
      conversationCreatedRef.current = true;
    } catch (err) {
      console.error('Failed to load conversation history:', err);
      toast.error('Failed to load conversation history');
      setConversationId(id);
      setInitialMessages(undefined);
      setTrackedJobs([]);
      setRuntimeKey(`conv-${id}`);
      conversationCreatedRef.current = true;
    } finally {
      setIsLoadingHistory(false);
    }
  }, [currentProject?.id]);

  // Load conversations on mount and auto-resume last conversation
  useEffect(() => {
    (async () => {
      const convos = await refreshConversations();
      if (autoResumedRef.current) return;
      autoResumedRef.current = true;
      try {
        const lastId = localStorage.getItem(LAST_CONVERSATION_KEY);
        if (lastId && convos.some((c: Conversation) => c.id === lastId)) {
          await switchConversation(lastId);
        }
      } catch (err) {
        console.error('Failed to auto-resume conversation:', err);
      }
    })();
  }, [refreshConversations, switchConversation]);

  const createNewConversation = useCallback(() => {
    setConversationId(null);
    setInitialMessages(undefined);
    setTrackedJobs([]);
    setRuntimeKey(`new-${Date.now()}`);
    conversationCreatedRef.current = false;
    try { localStorage.removeItem(LAST_CONVERSATION_KEY); } catch { /* noop */ }
  }, []);

  const handleDeleteConversation = useCallback(async (id: string) => {
    try {
      await deleteConv(id);
      setConversations((prev) => prev.filter((c) => c.id !== id));
      if (conversationId === id) {
        createNewConversation();
      }
      // Clear stored ID if the deleted conversation was the last one
      try {
        if (localStorage.getItem(LAST_CONVERSATION_KEY) === id) {
          localStorage.removeItem(LAST_CONVERSATION_KEY);
        }
      } catch { /* noop */ }
    } catch (err) {
      console.error('Failed to delete conversation:', err);
      toast.error('Failed to delete conversation');
    }
  }, [conversationId, createNewConversation]);

  // Handle new messages: auto-create conversation and save with content_json
  const handleNewMessages = useCallback(async (messages: SaveableMessage[]) => {
    if (conversationCreatedRef.current) {
      // Already have a conversation, just save new messages
      if (conversationId) {
        try {
          await saveMessagesBulk(conversationId, messages);
        } catch (err) {
          console.error('Failed to save messages:', err);
          toast.error('Failed to save message');
        }
      }
      return;
    }

    // Prevent double-creation if called rapidly
    if (creatingRef.current) return;
    creatingRef.current = true;

    // Step 1: Create conversation
    let conv: { id: string } | null = null;
    try {
      conv = await createConversation('New Conversation', currentProject?.id);
    } catch (err) {
      console.error('Failed to create conversation:', err);
      toast.error('Failed to create conversation');
      creatingRef.current = false;
      return; // conversationCreatedRef stays false — allows retry
    }

    // Step 2: Mark as created (only after success) and update state
    conversationCreatedRef.current = true;
    creatingRef.current = false;
    setConversationId(conv.id);
    setTrackedJobs((prev) => prev.map((job) => (
      job.conversationId ? job : { ...job, conversationId: conv!.id }
    )));

    // Step 3: Save messages
    try {
      await saveMessagesBulk(conv.id, messages);
    } catch (err) {
      console.error('Failed to save messages:', err);
      toast.error('Failed to save messages');
    }

    // Step 4: Auto-title (cosmetic, silent failure)
    try {
      await autoTitle(conv.id);
    } catch (err) {
      console.error('Failed to auto-title conversation:', err);
    }

    // Step 4b: Auto-generate summary (cosmetic, silent failure)
    try {
      await generateSummary(conv.id);
    } catch (err) {
      console.error('Failed to generate summary:', err);
    }

    // Step 5: Refresh conversation list (silent failure)
    try {
      await refreshConversations();
    } catch (err) {
      console.error('Failed to refresh conversations:', err);
    }
  }, [conversationId, currentProject?.id, refreshConversations]);

  // Persist a tool result to the database immediately (for approve/reject durability)
  const persistToolResult = useCallback(async (toolCallId: string, toolName: string, result: unknown) => {
    if (!conversationId) return; // New conversation not yet created — ThreadMessageTracker will save later
    try {
      const data = await getMessages(conversationId);
      // Find the assistant message whose content_json contains a part with this toolCallId
      for (const msg of data.messages) {
        if (msg.role !== 'assistant' || !msg.content_json) continue;
        let parts: any[];
        try { parts = JSON.parse(msg.content_json); } catch { continue; }
        if (!Array.isArray(parts)) continue;

        let found = false;
        for (const part of parts) {
          if (part.toolCallId === toolCallId) {
            part.output = result;
            part.state = 'output-available';
            // Also update tool-call format if present
            if (part.type === 'tool-call') {
              part.result = result;
            }
            found = true;
            break;
          }
        }
        if (found) {
          await updateMessageContentJson(conversationId, msg.id, JSON.stringify(parts));
          return;
        }
      }
    } catch (err) {
      console.error('Failed to persist tool result:', err);
      // Non-fatal — ThreadMessageTracker will save at run completion as fallback
    }
  }, [conversationId]);

  const saveAssistantFollowup = useCallback(async (content: string, targetConversationId?: string | null) => {
    const targetId = targetConversationId || conversationId;
    if (!targetId) return;
    try {
      await saveMessage(targetId, {
        role: 'assistant',
        content,
        content_json: JSON.stringify([{ type: 'text', text: content }]),
      });
      await refreshConversations();
    } catch (err) {
      console.error('Failed to save assistant follow-up:', err);
      toast.error('Failed to save assistant follow-up');
    }
  }, [conversationId, refreshConversations]);

  const registerTrackedJob = useCallback((
    toolName: string,
    result: unknown,
    args?: Record<string, unknown>,
    label?: string
  ) => {
    const job = makeTrackedJob(toolName, result, args, label, currentProject?.id, conversationId);
    if (!job) return false;

    setTrackedJobs((prev) => {
      if (prev.some((existing) => existing.key === job.key)) return prev;
      return [...prev, job];
    });
    return true;
  }, [conversationId, currentProject?.id]);

  const patchTrackedJob = useCallback((key: string, patch: Partial<TrackedChatJob>) => {
    setTrackedJobs((prev) => prev.map((job) => (
      job.key === key ? { ...job, ...patch } : job
    )));
  }, []);

  const completeTrackedJob = useCallback((key: string) => {
    setTrackedJobs((prev) => prev.filter((job) => job.key !== key));
  }, []);

  // Global keyboard shortcuts
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      // Cmd+N or Ctrl+N: new chat
      if ((e.metaKey || e.ctrlKey) && e.key === 'n') {
        e.preventDefault();
        createNewConversation();
      }
      // Cmd+K or Ctrl+K: focus search
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        window.dispatchEvent(new CustomEvent('focus-chat-search'));
      }
    }
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [createNewConversation]);

  const contextValue: ChatContextType = {
    conversationId,
    conversations,
    createNewConversation,
    switchConversation,
    deleteConversation: handleDeleteConversation,
    refreshConversations,
    isLoadingHistory,
    persistToolResult,
    registerTrackedJob,
  };

  return (
    <ChatContext.Provider value={contextValue}>
      <RuntimeProvider
        key={runtimeKey}
        conversationId={conversationId}
        initialMessages={initialMessages}
        onNewMessages={handleNewMessages}
        trackedJobs={trackedJobs}
        onTrackedJobPatch={patchTrackedJob}
        onTrackedJobComplete={completeTrackedJob}
        saveAssistantFollowup={saveAssistantFollowup}
      >
        {children}
      </RuntimeProvider>
    </ChatContext.Provider>
  );
}
