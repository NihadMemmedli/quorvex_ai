'use client';

import { type ChangeEvent, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  AlertTriangle,
  Archive,
  ArrowDown,
  ArrowUp,
  CheckCircle2,
  Clock,
  Bell,
  Copy,
  Edit3,
  ExternalLink,
  Eye,
  FileText,
  ListStart,
  Loader2,
  MoreHorizontal,
  Pause,
  Play,
  Plus,
  RefreshCw,
  RotateCcw,
  Search,
  Sparkles,
  Square,
  Trash2,
  X,
  Workflow,
} from 'lucide-react';
import { toast } from 'sonner';
import { API_BASE } from '@/lib/api';
import { useProject } from '@/contexts/ProjectContext';
import { parseDateMs, timeAgo } from '@/lib/formatting';
import { PageLayout } from '@/components/ui/page-layout';
import { PageHeader } from '@/components/ui/page-header';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Switch } from '@/components/ui/switch';
import { EmptyState } from '@/components/ui/empty-state';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Skeleton } from '@/components/ui/skeleton';
import { Progress } from '@/components/ui/progress';
import { StatusBadge } from '@/components/shared/StatusBadge';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';

type WorkflowTab = 'templates' | 'library' | 'builder' | 'runs' | 'schedules' | 'notifications';
type RunFilter = 'active' | 'failed' | 'completed' | 'all';
type LibraryStatusFilter = 'all' | 'active' | 'failed' | 'completed' | 'never_run';
type LibrarySort = 'updated' | 'last_run' | 'name';

interface WorkflowDefinition {
  id: string;
  name: string;
  description: string;
  version?: number;
  status: string;
  steps: WorkflowStep[];
  updated_at: string;
}

interface WorkflowStep {
  key: string;
  type: string;
  label?: string;
  input: Record<string, unknown>;
  continue_on_error?: boolean;
  recovery_policy?: RecoveryPolicy;
}

interface RecoveryPolicy {
  action?: 'fail' | 'retry' | 'skip' | 'pause' | 'notify';
  max_attempts?: number;
  retry_backoff_seconds?: number;
}

interface WorkflowRun {
  id: string;
  definition_id: string;
  definition_version?: number;
  revision_id?: string | null;
  status: string;
  progress: number;
  current_step_index: number;
  error_message?: string | null;
  created_at: string;
  started_at?: string | null;
  completed_at?: string | null;
  updated_at: string;
  definition?: { name?: string };
  steps?: WorkflowRunStep[];
  inputs?: Record<string, unknown>;
  context?: Record<string, unknown>;
  result?: Record<string, unknown> | null;
  trigger_type?: string | null;
  trigger_id?: string | null;
  temporal_workflow_id?: string | null;
  pause_reason?: string | null;
}

interface WorkflowSchedule {
  id: string;
  project_id?: string | null;
  definition_id: string;
  revision_id?: string | null;
  name: string;
  description?: string;
  cron_expression: string;
  timezone: string;
  inputs?: Record<string, unknown>;
  start_step_key?: string | null;
  enabled: boolean;
  status: string;
  last_error?: string | null;
  notify_on_completion?: boolean;
  notify_on_failure?: boolean;
  notify_on_review_needed?: boolean;
  next_run_at?: string | null;
  last_run_at?: string | null;
  last_run_status?: string | null;
  last_run_id?: string | null;
  total_executions: number;
  successful_executions?: number;
  failed_executions?: number;
  avg_duration_seconds?: number | null;
  success_rate: number;
}

interface WorkflowScheduleExecution {
  id: number;
  schedule_id: string;
  workflow_run_id?: string | null;
  status: string;
  trigger_type: string;
  error_message?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  duration_seconds?: number | null;
  created_at: string;
}

interface WorkflowNotification {
  id: string;
  title: string;
  body: string;
  target_url?: string | null;
  read_at?: string | null;
  delivered_at?: string | null;
  created_at: string;
}

interface WorkflowRevision {
  id: string;
  definition_id: string;
  version: number;
  name: string;
  description: string;
  steps: WorkflowStep[];
  change_summary?: string;
  created_at: string;
}

interface WorkflowAnalytics {
  runs?: number;
  active_runs?: number;
  failed_runs?: number;
  completed_runs?: number;
  success_rate?: number;
  failure_rate?: number;
  duration_seconds?: { median?: number | null; p95?: number | null };
  trigger_breakdown?: Record<string, number>;
  flakiest_steps?: { step_type: string; failures: number }[];
  slowest_steps?: { step_type: string; p95_duration_seconds?: number | null }[];
  recent_failures?: WorkflowRun[];
}

interface WorkflowRunStep {
  id: number;
  run_id?: string;
  definition_id?: string;
  step_order: number;
  step_key: string;
  step_type: string;
  label: string;
  status: string;
  continue_on_error?: boolean;
  input?: Record<string, unknown>;
  rendered_input?: Record<string, unknown>;
  context_snapshot?: Record<string, unknown>;
  input_resolution?: WorkflowInputResolution[];
  output?: Record<string, unknown> | null;
  output_validation_errors?: string[];
  step_config?: {
    output_schema?: CatalogStep['output_schema'];
    [key: string]: unknown;
  };
  external_kind?: string | null;
  external_id?: string | null;
  error_message?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  updated_at?: string | null;
}

interface WorkflowInputResolution {
  path: string;
  template: string;
  reference: string;
  resolved: unknown;
  status: string;
}

interface AutoPilotSessionSummary {
  id: string;
  status: string;
  current_phase: string | null;
  current_phase_progress: number;
  error_message?: string | null;
  failed_phase?: string | null;
  can_resume?: boolean;
  resume_reason?: string | null;
}

interface AutoPilotPhase {
  id: number;
  phase_name: string;
  phase_order: number;
  status: string;
  progress: number;
  current_step: string | null;
  items_total: number;
  items_completed: number;
  error_message?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
}

interface AutoPilotLiveArtifact {
  name: string;
  path: string;
  type: string;
  modified_at?: string | null;
  updated_at?: string | null;
}

interface AutoPilotLiveState {
  active: boolean;
  phase: string | null;
  activity_label?: string | null;
  status?: string | null;
  message?: string | null;
  run_id?: string | null;
  test_task_id?: number | null;
  spec_name?: string | null;
  current_stage?: string | null;
  last_tool_label?: string | null;
  tool_calls: number;
  browser_tool_calls: number;
  interactions: number;
  recent_tools: unknown[];
  artifacts?: AutoPilotLiveArtifact[];
  latest_image: AutoPilotLiveArtifact | null;
  updated_at?: string | null;
}

interface AutoPilotTestTask {
  id: number;
  session_id: string;
  spec_task_id: number | null;
  spec_name: string | null;
  spec_path: string | null;
  run_id: string | null;
  status: string;
  current_stage: string | null;
  generation_mode: string | null;
  healing_attempt: number;
  test_path: string | null;
  passed: boolean | null;
  error_summary: string | null;
  artifact_count: number;
  log_available: boolean;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
}

interface AutoPilotTestTaskDetail extends AutoPilotTestTask {
  run_dir: string | null;
  pipeline_error: Record<string, unknown> | null;
  agentic_summary: Record<string, unknown> | null;
  validation: Record<string, unknown> | null;
  artifacts: AutoPilotLiveArtifact[];
  report_url: string | null;
  log_excerpt: string | null;
}

interface CatalogStep {
  type: string;
  version?: number;
  label: string;
  description: string;
  category?: string;
  risk_level?: string;
  is_async?: boolean;
  auto_wait_defaults?: Record<string, unknown>;
  required: string[];
  default_input?: Record<string, unknown>;
  ui_schema?: {
    fields?: WorkflowCatalogField[];
    recommended_next_steps?: WorkflowRecommendedNextStep[];
  };
  output_schema?: {
    tokens?: string[];
    token_catalog?: WorkflowTokenCatalogItem[];
    json_schema?: Record<string, unknown>;
  };
  handler_kind?: string;
  handler_config?: Record<string, unknown>;
}

interface WorkflowTokenCatalogItem {
  path: string;
  label: string;
  type?: string;
  description?: string;
  nullable?: boolean;
}

interface WorkflowCatalogField {
  key: string;
  label: string;
  control: 'text' | 'textarea' | 'number' | 'boolean' | 'select' | 'string_list' | 'source_step' | 'agent_definition';
  placeholder?: string;
  rows?: number;
  min?: number;
  options?: { label: string; value: string }[];
  tokens?: boolean;
  token_sources?: string[];
}

interface WorkflowRecommendedNextStep {
  type: string;
  label?: string;
  description?: string;
  after_wait?: boolean;
}

interface AgentDefinition {
  id: string;
  name: string;
  description?: string;
  timeout_seconds?: number;
  tool_ids?: string[];
  tools?: AgentToolDefinition[];
  risk_level?: string;
  status?: string;
}

interface AgentToolDefinition {
  id: string;
  label: string;
  description?: string;
  category?: string;
  risk?: string;
}

interface ValidationResult {
  form?: string;
  steps: Record<number, string[]>;
  fieldErrors?: Record<number, Record<string, string[]>>;
  warnings?: Record<number, string[]>;
}

interface WorkflowTemplate {
  id: string;
  name: string;
  description: string;
  useCase: string;
  category?: string;
  tags?: string[];
  risk_level?: string;
  estimated_duration_minutes?: number;
  step_types?: string[];
  steps: WorkflowStep[];
}

interface TokenPickerState {
  stepIndex: number;
  inputKey: string;
  options: TokenOption[];
}

interface TokenOption {
  label: string;
  value: string;
  stepKey: string;
  stepLabel: string;
  path: string;
  type?: string;
  description?: string;
}

interface WorkflowBuilderDraft {
  schemaVersion: number;
  selectedDefinitionId: string;
  name: string;
  description: string;
  steps: WorkflowStep[];
  advancedOpen?: Record<number, boolean>;
  jsonDrafts?: Record<number, string>;
  updatedAt: string;
}

type DraftStatus = 'idle' | 'dirty' | 'saved' | 'restored';

const activeStatuses = ['queued', 'running', 'awaiting_input', 'paused'];
const terminalStatuses = ['completed', 'failed', 'cancelled'];
const attentionStatuses = ['failed', 'error', 'timeout', 'cancelled'];
const catalogCategoryOrder = ['Discovery', 'Generation', 'Execution', 'Agent', 'Review', 'Utility'];
const workflowDraftSchemaVersion = 1;

const AUTO_PILOT_PHASE_LABELS: Record<string, string> = {
  exploration: 'Exploration',
  requirements: 'Requirements',
  test_ideas: 'Test Ideas',
  spec_generation: 'Spec Generation',
  test_generation: 'Test Generation',
  reporting: 'Reporting',
};

function isWorkflowTab(value: string | null): value is WorkflowTab {
  return value === 'templates' || value === 'library' || value === 'builder' || value === 'runs';
}

function pretty(value: string) {
  return value.replace(/_/g, ' ');
}

function progress(value: number) {
  const numeric = Number.isFinite(value) ? value : 0;
  return Math.round(Math.max(0, Math.min(1, numeric)) * 100);
}

function elapsedDuration(startMs: number | null, endMs: number | null) {
  if (startMs === null || endMs === null) return '-';
  const seconds = Math.max(0, Math.floor((endMs - startMs) / 1000));
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ${seconds % 60}s`;
  return `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
}

function duration(run: WorkflowRun) {
  const start = parseDateMs(run.started_at || run.created_at);
  const end = terminalStatuses.includes(run.status)
    ? parseDateMs(run.completed_at || run.updated_at)
    : Date.now();
  return elapsedDuration(start, end);
}

function stepDuration(step: WorkflowRunStep) {
  if (!step.started_at) return '-';
  const start = parseDateMs(step.started_at);
  const end = step.completed_at ? parseDateMs(step.completed_at) : Date.now();
  return elapsedDuration(start, end);
}

function compactJson(value: unknown) {
  if (value === undefined || value === null) return '';
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function externalStatusFromStep(step: WorkflowRunStep) {
  const output = step.output || {};
  const status = output.status;
  return typeof status === 'string' ? status.toLowerCase() : '';
}

function needsAttention(step: WorkflowRunStep) {
  return step.status === 'failed' || attentionStatuses.includes(externalStatusFromStep(step));
}

function externalLabel(kind?: string | null) {
  if (!kind) return 'Child job';
  if (kind === 'autopilot') return 'AutoPilot session';
  if (kind === 'exploration') return 'Exploration session';
  if (kind === 'requirements_job') return 'Requirements job';
  if (kind === 'bulk_specs_job') return 'Bulk spec job';
  if (kind === 'test_run') return 'Test run';
  if (kind === 'regression_batch') return 'Regression batch';
  if (kind === 'agent_run') return 'Agent run';
  return pretty(kind);
}

function externalHref(kind?: string | null, id?: string | null) {
  if (!kind || !id) return null;
  if (kind === 'autopilot') return `/autopilot?sessionId=${encodeURIComponent(id)}`;
  if (kind === 'test_run') return `/runs/${encodeURIComponent(id)}`;
  if (kind === 'regression_batch') return `/regression/batches/${encodeURIComponent(id)}`;
  return null;
}

function timestamp(value?: string | null) {
  return parseDateMs(value) ?? 0;
}

function isRunActive(run?: WorkflowRun | null) {
  return Boolean(run && activeStatuses.includes(run.status));
}

function isRunFailed(run?: WorkflowRun | null) {
  return Boolean(run && ['failed', 'error', 'timeout'].includes(run.status));
}

function isRunCompleted(run?: WorkflowRun | null) {
  return Boolean(run && run.status === 'completed');
}

function normalizeSearch(value: string) {
  return value.trim().toLowerCase();
}

function defaultInputFor(type: string, catalog: CatalogStep[] = []): Record<string, unknown> {
  const catalogDefault = catalog.find(item => item.type === type)?.default_input;
  if (catalogDefault) return JSON.parse(JSON.stringify(catalogDefault)) as Record<string, unknown>;
  return {};
}

function preferredTokenPathsForField(key: string) {
  if (key.endsWith('_session_id') || key.endsWith('_job_id') || key.endsWith('_run_id')) {
    return ['external_id', 'session_id', 'job_id', 'id'];
  }
  return [];
}

function contextualDefaultInputFor(type: string, catalog: CatalogStep[], previousSteps: WorkflowStep[]) {
  const input = defaultInputFor(type, catalog);
  const fields = catalog.find(item => item.type === type)?.ui_schema?.fields || [];

  fields.forEach(field => {
    if (!field.token_sources || hasInputValue(input, field.key)) return;
    const source = [...previousSteps].reverse().find(step => field.token_sources?.includes(step.type));
    if (!source) return;

    const sourceMetadata = catalog.find(item => item.type === source.type);
    const outputPaths = [
      ...((sourceMetadata?.output_schema?.token_catalog || []).map(token => token.path)),
      ...(sourceMetadata?.output_schema?.tokens || []),
    ].map(String);
    const preferredPath = preferredTokenPathsForField(field.key).find(path => outputPaths.includes(path)) || outputPaths[0];
    if (preferredPath) {
      input[field.key] = `{{steps.${source.key}.${preferredPath}}}`;
    }
  });

  return input;
}

function defaultLabelFor(type: string, catalog: CatalogStep[]) {
  return catalog.find(item => item.type === type)?.label || pretty(type);
}

function stepKeyFor(type: string, index: number) {
  return `${type.replace(/^start_/, '').replace(/_for_status$/, '').replace(/[^A-Za-z0-9_-]/g, '_')}_${index}`;
}

function uniqueStepKeyFor(type: string, steps: WorkflowStep[]) {
  const existing = new Set(steps.map(step => step.key));
  let index = steps.length + 1;
  let key = stepKeyFor(type, index);
  while (existing.has(key)) {
    index += 1;
    key = stepKeyFor(type, index);
  }
  return key;
}

function uniqueStepKeyFromBase(baseKey: string, steps: WorkflowStep[]) {
  const existing = new Set(steps.map(step => step.key));
  if (!existing.has(baseKey)) return baseKey;
  let index = 2;
  let key = `${baseKey}_${index}`;
  while (existing.has(key)) {
    index += 1;
    key = `${baseKey}_${index}`;
  }
  return key;
}

function inputString(input: Record<string, unknown>, key: string, fallback = '') {
  const value = input[key];
  return typeof value === 'string' ? value : fallback;
}

function inputNumber(input: Record<string, unknown>, key: string, fallback: number) {
  const value = input[key];
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback;
}

function inputList(input: Record<string, unknown>, key: string) {
  const value = input[key];
  return Array.isArray(value) ? value.map(item => String(item)).join('\n') : '';
}

function inputBoolean(input: Record<string, unknown>, key: string, fallback = false) {
  const value = input[key];
  return typeof value === 'boolean' ? value : fallback;
}

function defaultWorkflowSteps(catalog: CatalogStep[], templates: WorkflowTemplate[]) {
  const preferredTemplate = templates.find(template => template.id === 'autopilot-smoke-review') || templates[0];
  if (preferredTemplate) return cloneWorkflowSteps(preferredTemplate.steps);
  const firstType = catalog[0]?.type;
  return firstType ? [{ key: stepKeyFor(firstType, 1), type: firstType, label: defaultLabelFor(firstType, catalog), input: defaultInputFor(firstType, catalog) }] : [];
}

function createEmptyValidation(): ValidationResult {
  return { steps: {}, fieldErrors: {}, warnings: {} };
}

function definitionName(definitions: WorkflowDefinition[], run: WorkflowRun) {
  return run.definition?.name || definitions.find(item => item.id === run.definition_id)?.name || run.definition_id;
}

function cloneWorkflowSteps(source: WorkflowStep[]) {
  return source.map(step => ({
    ...step,
    input: JSON.parse(JSON.stringify(step.input || {})) as Record<string, unknown>,
  }));
}

function cloneRecord<T>(value: T): T {
  return JSON.parse(JSON.stringify(value || {})) as T;
}

function workflowDraftStorageKey(projectId: string | undefined, definitionId: string) {
  return `workflow-builder-draft:${projectId || 'default'}:${definitionId || 'new'}`;
}

function hasInputValue(input: Record<string, unknown>, key: string) {
  const value = input[key];
  if (Array.isArray(value)) return value.length > 0;
  if (typeof value === 'string') return value.trim().length > 0;
  return value !== undefined && value !== null && value !== '';
}

function validationMessagesForStep(validation: ValidationResult, index: number) {
  return Array.from(new Set([
    ...(validation.steps[index] || []),
    ...Object.values(validation.fieldErrors?.[index] || {}).flat(),
  ]));
}

function validationFieldMessages(validation: ValidationResult, index: number, key: string) {
  return validation.fieldErrors?.[index]?.[key] || [];
}

function workflowValidationMessage(message: string, field?: string, stepType?: string) {
  const normalized = message.toLowerCase();
  if (
    field === 'definition_id' &&
    (stepType === 'start_custom_agent' || normalized.includes('definition_id')) &&
    (normalized.includes('should be non-empty') || normalized.includes('missing required input') || normalized.includes('required'))
  ) {
    return 'Choose an agent before creating this workflow.';
  }
  if (stepType === 'generate_requirements' && field === 'exploration_session_id') {
    return 'Add Start Exploration before Generate Requirements, then insert its External ID token.';
  }
  if (stepType === 'wait_for_status' && field === 'source_step') {
    return 'Choose the earlier step this wait should monitor.';
  }
  return message;
}

function Section({
  title,
  description,
  action,
  children,
}: {
  title: string;
  description?: string;
  action?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section className="card-elevated workflow-section">
      <div className="workflow-section-header">
        <div>
          <h2>{title}</h2>
          {description && (
            <p>
              {description}
            </p>
          )}
        </div>
        {action}
      </div>
      <div className="workflow-section-body">{children}</div>
    </section>
  );
}

function FieldError({ children }: { children?: React.ReactNode }) {
  if (!children) return null;
  return <div style={{ color: 'var(--danger)', fontSize: '0.78rem', marginTop: '0.35rem' }}>{children}</div>;
}

const workflowMetaPillStyle: React.CSSProperties = {
  display: 'inline-flex',
  alignItems: 'center',
  minHeight: 22,
  border: '1px solid var(--border-subtle)',
  borderRadius: 999,
  padding: '0.12rem 0.5rem',
  background: 'rgba(255,255,255,0.02)',
};

const workflowIconButtonStyle: React.CSSProperties = {
  width: 34,
  height: 34,
  flexShrink: 0,
};

const workflowFilterStyle: React.CSSProperties = {
  height: 30,
  borderRadius: 8,
  padding: '0 0.65rem',
  color: 'var(--text-secondary)',
  background: 'transparent',
  borderColor: 'transparent',
};

const workflowFilterActiveStyle: React.CSSProperties = {
  ...workflowFilterStyle,
  color: 'var(--text)',
  background: 'var(--primary-glow)',
  borderColor: 'rgba(59,130,246,0.45)',
};

function createWorkflowTabStyle(activeTab: string, tab: string): React.CSSProperties {
  const isActive = activeTab === tab;
  return {
    height: 44,
    padding: '0 20px',
    cursor: 'pointer',
    borderTop: 'none',
    borderRight: 'none',
    borderLeft: 'none',
    borderBottom: isActive ? '2px solid var(--primary)' : '2px solid transparent',
    color: isActive ? 'var(--text)' : 'var(--text-secondary)',
    fontWeight: isActive ? 700 : 500,
    background: 'transparent',
    fontSize: '0.9rem',
    transition: 'all 0.2s var(--ease-smooth)',
    whiteSpace: 'nowrap',
  };
}

function WorkflowSkeleton() {
  return (
    <div style={{ display: 'grid', gap: '0.85rem' }}>
      {Array.from({ length: 4 }).map((_, index) => (
        <div key={index} className="card-elevated" style={{ padding: '1rem' }}>
          <Skeleton style={{ width: '42%', height: 18 }} />
          <Skeleton style={{ width: '70%', height: 12, marginTop: '0.7rem' }} />
          <Skeleton style={{ width: '30%', height: 30, marginTop: '1rem' }} />
        </div>
      ))}
    </div>
  );
}

export default function WorkflowPage() {
  const { currentProject } = useProject();
  const [definitions, setDefinitions] = useState<WorkflowDefinition[]>([]);
  const [runs, setRuns] = useState<WorkflowRun[]>([]);
  const [schedules, setSchedules] = useState<WorkflowSchedule[]>([]);
  const [scheduleExecutions, setScheduleExecutions] = useState<Record<string, WorkflowScheduleExecution[]>>({});
  const [notifications, setNotifications] = useState<WorkflowNotification[]>([]);
  const [revisionsByDefinition, setRevisionsByDefinition] = useState<Record<string, WorkflowRevision[]>>({});
  const [analytics, setAnalytics] = useState<WorkflowAnalytics | null>(null);
  const [catalog, setCatalog] = useState<CatalogStep[]>([]);
  const [workflowTemplates, setWorkflowTemplates] = useState<WorkflowTemplate[]>([]);
  const [agentDefinitions, setAgentDefinitions] = useState<AgentDefinition[]>([]);
  const [selectedDefinitionId, setSelectedDefinitionId] = useState('');
  const [activeTab, setActiveTab] = useState<WorkflowTab>('library');
  const [runFilter, setRunFilter] = useState<RunFilter>('active');
  const [librarySearch, setLibrarySearch] = useState('');
  const [catalogSearch, setCatalogSearch] = useState('');
  const [catalogCategory, setCatalogCategory] = useState('All');
  const [templateSearch, setTemplateSearch] = useState('');
  const [templateCategory, setTemplateCategory] = useState('All');
  const [autoAddWaitSteps, setAutoAddWaitSteps] = useState(true);
  const [libraryStatusFilter, setLibraryStatusFilter] = useState<LibraryStatusFilter>('all');
  const [librarySort, setLibrarySort] = useState<LibrarySort>('updated');
  const [name, setName] = useState('Smoke workflow');
  const [description, setDescription] = useState('Reusable workflow created from the UI.');
  const [steps, setSteps] = useState<WorkflowStep[]>([]);
  const [advancedOpen, setAdvancedOpen] = useState<Record<number, boolean>>({});
  const [jsonDrafts, setJsonDrafts] = useState<Record<number, string>>({});
  const [jsonErrors, setJsonErrors] = useState<Record<number, string>>({});
  const [validation, setValidation] = useState<ValidationResult>(createEmptyValidation());
  const [draftStatus, setDraftStatus] = useState<DraftStatus>('idle');
  const [draftUpdatedAt, setDraftUpdatedAt] = useState('');
  const [validating, setValidating] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [catalogError, setCatalogError] = useState<string | null>(null);
  const [runStepsById, setRunStepsById] = useState<Record<string, WorkflowRunStep[]>>({});
  const [selectedRunId, setSelectedRunId] = useState('');
  const [selectedRunStepId, setSelectedRunStepId] = useState<number | null>(null);
  const [selectedRunDetails, setSelectedRunDetails] = useState<WorkflowRun | null>(null);
  const [runDetailLoading, setRunDetailLoading] = useState(false);
  const [scheduleDialogDefinition, setScheduleDialogDefinition] = useState<WorkflowDefinition | null>(null);
  const [scheduleForm, setScheduleForm] = useState({
    name: '',
    description: '',
    cron_expression: '0 8 * * 1-5',
    timezone: 'UTC',
    start_step_key: '',
    enabled: true,
    notify_on_completion: false,
    notify_on_failure: true,
    notify_on_review_needed: true,
  });
  const [selectedRevisionDefinitionId, setSelectedRevisionDefinitionId] = useState('');
  const [autoPilotSession, setAutoPilotSession] = useState<AutoPilotSessionSummary | null>(null);
  const [autoPilotPhases, setAutoPilotPhases] = useState<AutoPilotPhase[]>([]);
  const [autoPilotLive, setAutoPilotLive] = useState<AutoPilotLiveState | null>(null);
  const [autoPilotTestTasks, setAutoPilotTestTasks] = useState<AutoPilotTestTask[]>([]);
  const [autoPilotTaskDetail, setAutoPilotTaskDetail] = useState<AutoPilotTestTaskDetail | null>(null);
  const [autoPilotTaskLoading, setAutoPilotTaskLoading] = useState(false);
  const [autoPilotError, setAutoPilotError] = useState<string | null>(null);
  const [tokenPicker, setTokenPicker] = useState<TokenPickerState | null>(null);
  const [tokenSearch, setTokenSearch] = useState('');
  const importInputRef = useRef<HTMLInputElement | null>(null);
  const urlStateReady = useRef(false);
  const draftHydratedKeys = useRef<Set<string>>(new Set());
  const draftRestoring = useRef(false);

  const projectParam = useMemo(
    () => currentProject?.id ? `?project_id=${encodeURIComponent(currentProject.id)}` : '',
    [currentProject?.id],
  );
  const draftKey = useMemo(
    () => workflowDraftStorageKey(currentProject?.id, selectedDefinitionId),
    [currentProject?.id, selectedDefinitionId],
  );

  const activeRuns = useMemo(() => runs.filter(run => activeStatuses.includes(run.status)), [runs]);
  const unreadNotifications = useMemo(() => notifications.filter(item => !item.read_at).length, [notifications]);

  const selectedRun = useMemo(
    () => selectedRunDetails || runs.find(run => run.id === selectedRunId) || null,
    [runs, selectedRunDetails, selectedRunId],
  );

  const selectedRunSteps = useMemo(
    () => selectedRunId ? runStepsById[selectedRunId] || selectedRun?.steps || [] : [],
    [runStepsById, selectedRun?.steps, selectedRunId],
  );

  const attentionStep = useMemo(
    () => selectedRunSteps.find(step => step.status === 'failed') || selectedRunSteps.find(needsAttention) || null,
    [selectedRunSteps],
  );

  const selectedRunStep = useMemo(
    () => selectedRunSteps.find(step => step.id === selectedRunStepId) || attentionStep,
    [attentionStep, selectedRunStepId, selectedRunSteps],
  );

  const autoPilotStep = useMemo(
    () => selectedRunSteps.find(step => step.external_kind === 'autopilot' && step.external_id)
      || selectedRunSteps.find(step => step.output?.external_kind === 'autopilot' && step.output?.external_id)
      || null,
    [selectedRunSteps],
  );

  const autoPilotSessionId = useMemo(() => {
    if (!autoPilotStep) return '';
    if (autoPilotStep.external_kind === 'autopilot' && autoPilotStep.external_id) return autoPilotStep.external_id;
    const output = autoPilotStep.output || {};
    return output.external_kind === 'autopilot' && typeof output.external_id === 'string' ? output.external_id : '';
  }, [autoPilotStep]);

  const filteredRuns = useMemo(() => {
    if (runFilter === 'active') return runs.filter(run => activeStatuses.includes(run.status));
    if (runFilter === 'failed') return runs.filter(run => run.status === 'failed');
    if (runFilter === 'completed') return runs.filter(run => run.status === 'completed');
    return runs;
  }, [runFilter, runs]);

  const latestRunByDefinition = useMemo(() => {
    const latest = new Map<string, WorkflowRun>();
    runs.forEach(run => {
      const existing = latest.get(run.definition_id);
      if (!existing || timestamp(run.created_at) > timestamp(existing.created_at)) {
        latest.set(run.definition_id, run);
      }
    });
    return latest;
  }, [runs]);

  const schedulesByDefinition = useMemo(() => {
    const grouped = new Map<string, WorkflowSchedule[]>();
    schedules.forEach(schedule => {
      const existing = grouped.get(schedule.definition_id) || [];
      existing.push(schedule);
      grouped.set(schedule.definition_id, existing);
    });
    return grouped;
  }, [schedules]);

  const visibleDefinitions = useMemo(() => {
    const query = normalizeSearch(librarySearch);
    const matchesStatus = (definition: WorkflowDefinition) => {
      const lastRun = latestRunByDefinition.get(definition.id);
      if (libraryStatusFilter === 'all') return true;
      if (libraryStatusFilter === 'active') return isRunActive(lastRun);
      if (libraryStatusFilter === 'failed') return isRunFailed(lastRun);
      if (libraryStatusFilter === 'completed') return isRunCompleted(lastRun);
      return !lastRun;
    };

    const matchesQuery = (definition: WorkflowDefinition) => {
      if (!query) return true;
      const fields = [
        definition.name,
        definition.description,
        ...(definition.steps || []).flatMap(step => [step.key, step.type, step.label || '']),
      ];
      return fields.some(field => field.toLowerCase().includes(query));
    };

    return definitions
      .filter(definition => matchesStatus(definition) && matchesQuery(definition))
      .sort((a, b) => {
        if (librarySort === 'name') return a.name.localeCompare(b.name);
        if (librarySort === 'last_run') {
          return timestamp(latestRunByDefinition.get(b.id)?.created_at) - timestamp(latestRunByDefinition.get(a.id)?.created_at);
        }
        return timestamp(b.updated_at) - timestamp(a.updated_at);
      });
  }, [definitions, latestRunByDefinition, librarySearch, librarySort, libraryStatusFilter]);

  const load = useCallback(async (initial = false) => {
    setError(null);
    setCatalogError(null);
    if (initial) setLoading(true);

    const [defsResult, runsResult, catalogResult, agentDefsResult] = await Promise.allSettled([
      fetch(`${API_BASE}/workflows/definitions${projectParam}`),
      fetch(`${API_BASE}/workflows/runs${projectParam}`),
      fetch(`${API_BASE}/workflows/catalog${projectParam}`),
      fetch(`${API_BASE}/api/agents/definitions${projectParam}`),
    ]);
    const [schedulesResult, analyticsResult, notificationsResult] = await Promise.allSettled([
      fetch(`${API_BASE}/workflows/schedules${projectParam}`),
      fetch(`${API_BASE}/workflows/analytics${projectParam}`),
      fetch(`${API_BASE}/workflows/notifications${projectParam}`),
    ]);

    if (defsResult.status !== 'fulfilled' || !defsResult.value.ok) {
      throw new Error('Failed to load workflow definitions');
    }
    if (runsResult.status !== 'fulfilled' || !runsResult.value.ok) {
      throw new Error('Failed to load workflow runs');
    }

    setDefinitions(await defsResult.value.json());
    setRuns(await runsResult.value.json());
    if (schedulesResult.status === 'fulfilled' && schedulesResult.value.ok) {
      setSchedules(await schedulesResult.value.json());
    }
    if (analyticsResult.status === 'fulfilled' && analyticsResult.value.ok) {
      setAnalytics(await analyticsResult.value.json());
    }
    if (notificationsResult.status === 'fulfilled' && notificationsResult.value.ok) {
      setNotifications(await notificationsResult.value.json());
    }

    if (catalogResult.status === 'fulfilled' && catalogResult.value.ok) {
      const catalogData = await catalogResult.value.json();
      setCatalog(Array.isArray(catalogData.steps) ? catalogData.steps : []);
      setWorkflowTemplates(Array.isArray(catalogData.templates) ? catalogData.templates : []);
    } else {
      setCatalog([]);
      setWorkflowTemplates([]);
      setCatalogError('Step catalog is unavailable. Existing workflows and runs can still be used.');
    }
    if (agentDefsResult.status === 'fulfilled' && agentDefsResult.value.ok) {
      const agentData = await agentDefsResult.value.json();
      setAgentDefinitions(Array.isArray(agentData) ? agentData : []);
    } else {
      setAgentDefinitions([]);
    }
    setLoading(false);
  }, [projectParam]);

  useEffect(() => {
    let cancelled = false;
    load(true).catch((err) => {
      if (!cancelled) {
        setError(err instanceof Error ? err.message : 'Failed to load workflows');
        setLoading(false);
      }
    });
    const interval = setInterval(() => {
      if (!cancelled) load(false).catch(() => {});
    }, 10000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [load]);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    const params = new URLSearchParams(window.location.search);
    const tab = params.get('tab');
    const runId = params.get('runId');
    if (isWorkflowTab(tab)) setActiveTab(tab);
    if (runId) {
      setSelectedRunId(runId);
      setActiveTab('runs');
      void getRunDetail(runId, { quiet: true });
    }
    urlStateReady.current = true;
  }, []);

  useEffect(() => {
    if (!urlStateReady.current || typeof window === 'undefined') return;
    const params = new URLSearchParams(window.location.search);
    if (activeTab === 'library') params.delete('tab');
    else params.set('tab', activeTab);
    if (selectedRunId && activeTab === 'runs') params.set('runId', selectedRunId);
    else params.delete('runId');
    const next = `${window.location.pathname}${params.toString() ? `?${params.toString()}` : ''}`;
    window.history.replaceState(null, '', next);
  }, [activeTab, selectedRunId]);

  useEffect(() => {
    if (typeof window === 'undefined' || loading || draftHydratedKeys.current.has(draftKey)) return;
    draftHydratedKeys.current.add(draftKey);
    const raw = window.localStorage.getItem(draftKey);
    if (!raw) return;
    try {
      const draft = JSON.parse(raw) as WorkflowBuilderDraft;
      if (draft.schemaVersion !== workflowDraftSchemaVersion || !Array.isArray(draft.steps)) return;
      draftRestoring.current = true;
      setSelectedDefinitionId(draft.selectedDefinitionId || '');
      setName(draft.name || 'Smoke workflow');
      setDescription(draft.description || '');
      setSteps(cloneWorkflowSteps(draft.steps));
      setAdvancedOpen(draft.advancedOpen || {});
      setJsonDrafts(draft.jsonDrafts || {});
      setJsonErrors({});
      setValidation(createEmptyValidation());
      setDraftUpdatedAt(draft.updatedAt || '');
      setDraftStatus('restored');
    } catch {
      window.localStorage.removeItem(draftKey);
    } finally {
      window.setTimeout(() => {
        draftRestoring.current = false;
      }, 0);
    }
  }, [draftKey, loading]);

  useEffect(() => {
    if (typeof window === 'undefined' || activeTab !== 'builder' || loading || steps.length === 0) return;
    if (Object.keys(jsonErrors).length > 0) return;
    if (draftRestoring.current) return;
    setDraftStatus('dirty');
    const timeout = window.setTimeout(() => {
      const updatedAt = new Date().toISOString();
      const draft: WorkflowBuilderDraft = {
        schemaVersion: workflowDraftSchemaVersion,
        selectedDefinitionId,
        name,
        description,
        steps: cloneWorkflowSteps(steps),
        advancedOpen: cloneRecord(advancedOpen),
        jsonDrafts: cloneRecord(jsonDrafts),
        updatedAt,
      };
      window.localStorage.setItem(draftKey, JSON.stringify(draft));
      setDraftUpdatedAt(updatedAt);
      setDraftStatus('saved');
    }, 500);
    return () => window.clearTimeout(timeout);
  }, [activeTab, advancedOpen, description, draftKey, jsonDrafts, jsonErrors, loading, name, selectedDefinitionId, steps]);

  useEffect(() => {
    if (!selectedRunId) {
      setSelectedRunDetails(null);
      setSelectedRunStepId(null);
      return;
    }
    setSelectedRunStepId(null);
    let cancelled = false;
    const refresh = async (quiet = true) => {
      try {
        const detail = await getRunDetail(selectedRunId, { quiet });
        if (!cancelled && detail.status && terminalStatuses.includes(detail.status)) {
          await load(false).catch(() => {});
        }
      } catch {
        // The global error banner already communicates request failures.
      }
    };
    void refresh(false);
    const interval = setInterval(() => {
      if (!selectedRun?.status || !terminalStatuses.includes(selectedRun.status)) void refresh(true);
    }, 3000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [selectedRun?.status, selectedRunId, load]);

  useEffect(() => {
    if (activeTab !== 'builder' || loading || steps.length === 0) return;
    if (Object.keys(jsonErrors).length > 0) return;
    const timeout = window.setTimeout(() => {
      void validateWorkflowOnServer({ quiet: true });
    }, 650);
    return () => window.clearTimeout(timeout);
    // validateWorkflowOnServer intentionally reads the latest builder state captured by this effect.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTab, currentProject?.id, description, jsonErrors, loading, name, steps]);

  const loadAutoPilotDiagnostics = useCallback(async (sessionId: string, quiet = true) => {
    if (!quiet) setAutoPilotError(null);
    try {
      const [sessionResult, phasesResult, liveResult, testTasksResult] = await Promise.allSettled([
        fetch(`${API_BASE}/autopilot/${encodeURIComponent(sessionId)}`),
        fetch(`${API_BASE}/autopilot/${encodeURIComponent(sessionId)}/phases`),
        fetch(`${API_BASE}/autopilot/${encodeURIComponent(sessionId)}/live`),
        fetch(`${API_BASE}/autopilot/${encodeURIComponent(sessionId)}/test-tasks`),
      ]);

      if (sessionResult.status === 'fulfilled' && sessionResult.value.ok) {
        setAutoPilotSession(await sessionResult.value.json());
      } else {
        setAutoPilotSession(null);
      }

      if (phasesResult.status === 'fulfilled' && phasesResult.value.ok) {
        const phaseData = await phasesResult.value.json();
        setAutoPilotPhases(Array.isArray(phaseData) ? phaseData : []);
      } else {
        setAutoPilotPhases([]);
      }

      if (liveResult.status === 'fulfilled' && liveResult.value.ok) {
        setAutoPilotLive(await liveResult.value.json());
      } else {
        setAutoPilotLive(null);
      }

      if (testTasksResult.status === 'fulfilled' && testTasksResult.value.ok) {
        const taskData = await testTasksResult.value.json();
        setAutoPilotTestTasks(Array.isArray(taskData) ? taskData : []);
      } else {
        setAutoPilotTestTasks([]);
      }
    } catch (err) {
      setAutoPilotError(err instanceof Error ? err.message : 'Failed to load AutoPilot diagnostics');
      setAutoPilotSession(null);
      setAutoPilotPhases([]);
      setAutoPilotLive(null);
      setAutoPilotTestTasks([]);
    }
  }, []);

  useEffect(() => {
    if (!autoPilotSessionId) {
      setAutoPilotSession(null);
      setAutoPilotPhases([]);
      setAutoPilotLive(null);
      setAutoPilotTestTasks([]);
      setAutoPilotTaskDetail(null);
      setAutoPilotError(null);
      return;
    }
    let cancelled = false;
    const refresh = async () => {
      if (!cancelled) await loadAutoPilotDiagnostics(autoPilotSessionId);
    };
    void refresh();
    const interval = setInterval(() => {
      const status = autoPilotSession?.status || autoPilotLive?.status || selectedRun?.status;
      if (!status || !terminalStatuses.includes(status)) void refresh();
    }, 3500);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [autoPilotSessionId, loadAutoPilotDiagnostics, autoPilotSession?.status, autoPilotLive?.status, selectedRun?.status]);

  useEffect(() => {
    const taskId = autoPilotLive?.test_task_id || autoPilotTestTasks.find(task => task.run_id === autoPilotLive?.run_id)?.id || null;
    if (!autoPilotSessionId || !taskId) {
      setAutoPilotTaskDetail(null);
      setAutoPilotTaskLoading(false);
      return;
    }

    let cancelled = false;
    setAutoPilotTaskLoading(true);
    fetch(`${API_BASE}/autopilot/${encodeURIComponent(autoPilotSessionId)}/test-tasks/${encodeURIComponent(String(taskId))}`)
      .then(async res => {
        if (!res.ok) throw new Error('Failed to load AutoPilot task details');
        return await res.json() as AutoPilotTestTaskDetail;
      })
      .then(detail => {
        if (!cancelled) setAutoPilotTaskDetail(detail);
      })
      .catch(() => {
        if (!cancelled) setAutoPilotTaskDetail(null);
      })
      .finally(() => {
        if (!cancelled) setAutoPilotTaskLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [autoPilotLive?.run_id, autoPilotLive?.test_task_id, autoPilotSessionId, autoPilotTestTasks]);

  function clearDraft(key = draftKey) {
    if (typeof window !== 'undefined') window.localStorage.removeItem(key);
    setDraftStatus('idle');
    setDraftUpdatedAt('');
  }

  function confirmReplaceDraft(action: string) {
    if (draftStatus === 'idle' || steps.length === 0 || typeof window === 'undefined') return true;
    return window.confirm(`Discard the current workflow draft and ${action}?`);
  }

  function resetBuilder(
    nextSteps = defaultWorkflowSteps(catalog, workflowTemplates),
    metadata?: { name?: string; description?: string },
    options?: { skipPrompt?: boolean; preserveDraft?: boolean },
  ) {
    if (!options?.skipPrompt && !confirmReplaceDraft('start a new workflow')) return;
    if (!options?.preserveDraft) clearDraft();
    setSelectedDefinitionId('');
    setName(metadata?.name || 'Smoke workflow');
    setDescription(metadata?.description || 'Reusable workflow created from the UI.');
    setSteps(cloneWorkflowSteps(nextSteps));
    setAdvancedOpen({});
    setJsonDrafts({});
    setJsonErrors({});
    setValidation(createEmptyValidation());
    setActiveTab('builder');
    setDraftStatus('dirty');
  }

  function applyTemplate(template: WorkflowTemplate) {
    if (!confirmReplaceDraft('use this template')) return;
    resetBuilder(template.steps, {
      name: template.name,
      description: template.description,
    }, { skipPrompt: true });
  }

  function selectDefinition(definition: WorkflowDefinition) {
    if (!confirmReplaceDraft('open another workflow')) return;
    clearDraft();
    setSelectedDefinitionId(definition.id);
    setName(definition.name);
    setDescription(definition.description || '');
    setSteps(definition.steps || []);
    setAdvancedOpen({});
    setJsonDrafts({});
    setJsonErrors({});
    setValidation(createEmptyValidation());
    setActiveTab('builder');
    setDraftStatus('idle');
  }

  function updateStep(index: number, patch: Partial<WorkflowStep>) {
    setSteps(prev => {
      const current = prev[index];
      const next = prev.map((step, i) => i === index ? { ...step, ...patch } : step);
      if (current && patch.key && patch.key !== current.key) {
        const maybeWait = next[index + 1];
        if (maybeWait?.type === 'wait_for_status' && maybeWait.input?.source_step === current.key) {
          next[index + 1] = {
            ...maybeWait,
            key: maybeWait.key === `wait_${current.key}` ? `wait_${patch.key}` : maybeWait.key,
            input: { ...(maybeWait.input || {}), source_step: patch.key },
          };
        }
      }
      return next;
    });
  }

  function updateStepInput(index: number, key: string, value: unknown) {
    setSteps(prev => prev.map((step, i) => {
      if (i !== index) return step;
      return { ...step, input: { ...(step.input || {}), [key]: value } };
    }));
    setJsonDrafts(prev => {
      const next = { ...prev };
      delete next[index];
      return next;
    });
  }

  function updateStepRecovery(index: number, patch: Partial<RecoveryPolicy>) {
    setSteps(prev => prev.map((step, i) => {
      if (i !== index) return step;
      const current = step.recovery_policy || { action: 'fail', max_attempts: 1, retry_backoff_seconds: 0 };
      const next = { ...current, ...patch };
      if (next.action !== 'retry') {
        next.max_attempts = next.max_attempts || 1;
        next.retry_backoff_seconds = next.retry_backoff_seconds || 0;
      }
      return { ...step, recovery_policy: next };
    }));
  }

  function buildStepWithOptionalWait(type: string, previousSteps: WorkflowStep[], keyScope = previousSteps) {
    const nextKey = uniqueStepKeyFor(type, keyScope);
    const nextStep: WorkflowStep = {
      key: nextKey,
      type,
      label: defaultLabelFor(type, catalog),
      input: contextualDefaultInputFor(type, catalog, previousSteps),
    };
    const catalogItem = catalog.find(item => item.type === type);
    const waitType = catalog.find(item => item.type === 'wait_for_status');
    if (!autoAddWaitSteps || !catalogItem?.is_async || !waitType) return [nextStep];
    const waitDefaults = catalogItem.auto_wait_defaults || {};
    const waitKey = uniqueStepKeyFromBase(`wait_${nextKey}`, [...keyScope, nextStep]);
    const waitStep: WorkflowStep = {
      key: waitKey,
      type: 'wait_for_status',
      label: `Wait for ${catalogItem.label}`,
      input: {
        source_step: nextKey,
        timeout_seconds: waitDefaults.timeout_seconds ?? 3600,
        poll_seconds: waitDefaults.poll_seconds ?? 10,
      },
    };
    return [nextStep, waitStep];
  }

  function addStep(type = 'review_gate') {
    setSteps(prev => {
      const created = buildStepWithOptionalWait(type, prev);
      const catalogItem = catalog.find(item => item.type === type);
      const waitStep = created.find(step => step.type === 'wait_for_status');
      if (catalogItem?.is_async && waitStep) {
        toast.success(`Added ${catalogItem.label} and wait step`, {
          action: {
            label: 'Undo',
            onClick: () => setSteps(current => current.filter(step => !created.some(item => item.key === step.key))),
          },
        });
      }
      return [...prev, ...created];
    });
    setActiveTab('builder');
  }

  function insertStepAfter(index: number, type: string) {
    setSteps(prev => {
      const before = prev.slice(0, index + 1);
      const created = buildStepWithOptionalWait(type, before, prev);
      return [...before, ...created, ...prev.slice(index + 1)];
    });
    setJsonDrafts({});
    setJsonErrors({});
    setActiveTab('builder');
  }

  function duplicateStep(index: number) {
    setSteps(prev => {
      const source = prev[index];
      if (!source) return prev;
      const clone = {
        ...source,
        key: `${source.key}_copy`,
        input: { ...(source.input || {}) },
      };
      return [...prev.slice(0, index + 1), clone, ...prev.slice(index + 1)];
    });
  }

  function moveStep(index: number, direction: -1 | 1) {
    setSteps(prev => {
      const target = index + direction;
      if (target < 0 || target >= prev.length) return prev;
      const next = [...prev];
      const [item] = next.splice(index, 1);
      next.splice(target, 0, item);
      return next;
    });
    setJsonDrafts({});
    setJsonErrors({});
  }

  function removeStep(index: number) {
    setSteps(prev => {
      const source = prev[index];
      const pairedWait = source && prev[index + 1]?.type === 'wait_for_status' && prev[index + 1]?.input?.source_step === source.key;
      const removedKeys = pairedWait ? new Set([source.key, prev[index + 1].key]) : new Set([source?.key]);
      const next = prev.filter(step => !removedKeys.has(step.key));
      if (pairedWait) {
        toast.success('Removed paired wait step', {
          action: {
            label: 'Undo',
            onClick: () => setSteps(prev),
          },
        });
      }
      return next;
    });
    setJsonDrafts({});
    setJsonErrors({});
  }

  function handleAdvancedJson(index: number, value: string) {
    setJsonDrafts(prev => ({ ...prev, [index]: value }));
    try {
      const parsed = JSON.parse(value || '{}');
      setJsonErrors(prev => {
        const next = { ...prev };
        delete next[index];
        return next;
      });
      updateStep(index, { input: parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {} });
    } catch (err) {
      setJsonErrors(prev => ({ ...prev, [index]: err instanceof Error ? err.message : 'Invalid JSON' }));
    }
  }

  function validateWorkflow() {
    const result = createEmptyValidation();
    const keys = new Map<string, number>();

    if (!name.trim()) result.form = 'Workflow name is required.';
    if (steps.length === 0) result.form = 'Add at least one step before saving.';

    steps.forEach((step, index) => {
      const errors: string[] = [];
      if (!step.key.trim()) errors.push('Step key is required.');
      if (step.key.trim() && keys.has(step.key.trim())) errors.push('Step key must be unique.');
      if (step.key.trim()) keys.set(step.key.trim(), index);
      if (!step.type) errors.push('Choose a step type.');
      if (jsonErrors[index]) errors.push('Advanced JSON must be valid.');
      const catalogItem = catalog.find(item => item.type === step.type);
      const missingRequired = (catalogItem?.required || []).filter(key => !hasInputValue(step.input || {}, key));
      missingRequired.forEach(key => {
        const field = catalogItem?.ui_schema?.fields?.find(item => item.key === key);
        const previousSource = field?.token_sources
          ? steps.slice(0, index).find(candidate => field.token_sources?.includes(candidate.type))
          : undefined;
        const message = previousSource
          ? `Use ${previousSource.label || defaultLabelFor(previousSource.type, catalog)} output for ${field?.label || key}.`
          : workflowValidationMessage(`Missing required input: ${key}.`, key, step.type);
        errors.push(message);
        result.fieldErrors = result.fieldErrors || {};
        result.fieldErrors[index] = result.fieldErrors[index] || {};
        result.fieldErrors[index][key] = [...(result.fieldErrors[index][key] || []), message];
      });
      if (step.type === 'wait_for_status') {
        const sourceStep = inputString(step.input || {}, 'source_step');
        if (!sourceStep) errors.push(workflowValidationMessage('Missing required input: source_step.', 'source_step', step.type));
        if (sourceStep && !steps.slice(0, index).some(candidate => candidate.key === sourceStep)) {
          errors.push('Choose an earlier step for this wait step.');
        }
      }
      const referenceErrors = validateStepReferences(step, index);
      errors.push(...referenceErrors);
      if (errors.length) result.steps[index] = errors;
    });

    setValidation(result);
    return !result.form && Object.keys(result.steps).length === 0;
  }

  async function validateWorkflowOnServer(options?: { quiet?: boolean }) {
    if (!options?.quiet) setValidating(true);
    try {
      const res = await fetch(`${API_BASE}/workflows/validate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, description, project_id: currentProject?.id || 'default', steps }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || data.error || 'Failed to validate workflow');
      const next = createEmptyValidation();
      const stepErrors = data.step_errors || {};
      Object.entries(stepErrors).forEach(([indexKey, rawErrors]) => {
        const index = Number(indexKey);
        const errors = Array.isArray(rawErrors) ? rawErrors : [];
        const stepType = steps[index]?.type;
        next.steps[index] = errors.map((item: unknown) => {
          if (item && typeof item === 'object' && 'message' in item) {
            const error = item as { field?: unknown; message?: unknown };
            return workflowValidationMessage(String(error.message || 'Invalid step'), String(error.field || ''), stepType);
          }
          return workflowValidationMessage(String(item), undefined, stepType);
        });
        errors.forEach((item: unknown) => {
          if (!item || typeof item !== 'object') return;
          const field = String((item as { field?: unknown }).field || 'input');
          const message = String((item as { message?: unknown }).message || 'Invalid field');
          next.fieldErrors = next.fieldErrors || {};
          next.fieldErrors[index] = next.fieldErrors[index] || {};
          next.fieldErrors[index][field] = Array.from(new Set([
            ...(next.fieldErrors[index][field] || []),
            workflowValidationMessage(message, field, stepType),
          ]));
        });
      });
      const warnings = data.warnings || {};
      Object.entries(warnings).forEach(([indexKey, rawWarnings]) => {
        const index = Number(indexKey);
        const values = Array.isArray(rawWarnings) ? rawWarnings : [];
        next.warnings = next.warnings || {};
        next.warnings[index] = values.map((item: unknown) => {
          if (item && typeof item === 'object' && 'message' in item) return String((item as { message?: unknown }).message || 'Warning');
          return String(item);
        });
      });
      const formErrors = Array.isArray(data.form_errors) ? data.form_errors : [];
      if (formErrors.length > 0) {
        next.form = formErrors.map((item: unknown) => {
          if (item && typeof item === 'object' && 'message' in item) return String((item as { message?: unknown }).message || 'Invalid workflow');
          return String(item);
        }).join(' ');
      }
      setValidation(next);
      return Boolean(data.valid);
    } catch (err) {
      if (!options?.quiet) setError(err instanceof Error ? err.message : 'Failed to validate workflow');
      return false;
    } finally {
      if (!options?.quiet) setValidating(false);
    }
  }

  function validateStepReferences(step: WorkflowStep, index: number) {
    const errors: string[] = [];
    const previous = steps.slice(0, index);
    const previousByKey = new Map(previous.map(item => [item.key, item]));
    const refs = extractTemplateRefs(step.input || {});
    refs.forEach(ref => {
      const parts = ref.split('.').map(part => part.trim()).filter(Boolean);
      if (parts.length < 3 || parts[0] !== 'steps') return;
      const source = previousByKey.get(parts[1]);
      if (!source) {
        errors.push(`This step uses a token from "${parts[1]}", but that step is not earlier in the workflow. Add the source step first or remove the token.`);
        return;
      }
      const tokens = catalog.find(item => item.type === source.type)?.output_schema?.tokens || [];
      if (tokens.length > 0 && !tokens.includes(parts[2])) {
        errors.push(`This step uses an output token that "${parts[1]}" does not provide: ${parts[2]}.`);
      }
    });
    return errors;
  }

  function extractTemplateRefs(value: unknown): string[] {
    if (Array.isArray(value)) return value.flatMap(item => extractTemplateRefs(item));
    if (value && typeof value === 'object') return Object.values(value).flatMap(item => extractTemplateRefs(item));
    if (typeof value !== 'string') return [];
    return Array.from(value.matchAll(/{{\s*([^{}]+?)\s*}}/g), match => match[1]);
  }

  async function saveDefinition() {
    if (!validateWorkflow()) return;
    const serverValid = await validateWorkflowOnServer();
    if (!serverValid) return;
    setSaving(true);
    setError(null);
    const savedDraftKey = draftKey;
    try {
      const path = selectedDefinitionId
        ? `${API_BASE}/workflows/definitions/${encodeURIComponent(selectedDefinitionId)}${projectParam}`
        : `${API_BASE}/workflows/definitions`;
      const res = await fetch(path, {
        method: selectedDefinitionId ? 'PUT' : 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, description, project_id: currentProject?.id || 'default', steps }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || data.error || 'Failed to save workflow');
      clearDraft(savedDraftKey);
      setSelectedDefinitionId(data.id);
      await load(false);
      setActiveTab('library');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save workflow');
    } finally {
      setSaving(false);
    }
  }

  async function startWorkflow(definitionId: string, startStepKey?: string) {
    setError(null);
    const res = await fetch(`${API_BASE}/workflows/definitions/${encodeURIComponent(definitionId)}/runs${projectParam}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ inputs: {}, triggered_by: 'ui', start_step_key: startStepKey }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      setError(data.detail || data.error || 'Failed to start workflow');
      return;
    }
    if (data.run_id) {
      setSelectedRunId(String(data.run_id));
      void getRunDetail(String(data.run_id), { quiet: true });
    }
    await load(false);
    setActiveTab('runs');
    toast.success(startStepKey ? 'Workflow started from selected step' : 'Workflow started');
  }

  function openScheduleDialog(definition: WorkflowDefinition) {
    const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
    setScheduleDialogDefinition(definition);
    setScheduleForm({
      name: `${definition.name} schedule`,
      description: '',
      cron_expression: '0 8 * * 1-5',
      timezone,
      start_step_key: '',
      enabled: true,
      notify_on_completion: false,
      notify_on_failure: true,
      notify_on_review_needed: true,
    });
  }

  async function submitSchedule() {
    const definition = scheduleDialogDefinition;
    if (!definition) return;
    const res = await fetch(`${API_BASE}/workflows/schedules`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        definition_id: definition.id,
        name: scheduleForm.name.trim() || `${definition.name} schedule`,
        description: scheduleForm.description.trim(),
        cron_expression: scheduleForm.cron_expression.trim(),
        timezone: scheduleForm.timezone.trim() || 'UTC',
        inputs: {},
        start_step_key: scheduleForm.start_step_key || undefined,
        enabled: scheduleForm.enabled,
        notify_on_completion: scheduleForm.notify_on_completion,
        notify_on_failure: scheduleForm.notify_on_failure,
        notify_on_review_needed: scheduleForm.notify_on_review_needed,
      }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      setError(data.detail || data.error || 'Failed to schedule workflow');
      toast.error('Failed to schedule workflow');
      return;
    }
    setScheduleDialogDefinition(null);
    await load(false);
    toast.success('Workflow schedule created');
  }

  async function runScheduleNow(schedule: WorkflowSchedule) {
    const res = await fetch(`${API_BASE}/workflows/schedules/${encodeURIComponent(schedule.id)}/run-now`, { method: 'POST' });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      setError(data.detail || data.error || 'Failed to run workflow schedule');
      toast.error('Failed to run workflow schedule');
      return;
    }
    await load(false);
    toast.success('Scheduled workflow queued');
  }

  async function controlRun(runId: string, action: 'pause' | 'resume' | 'cancel') {
    const res = await fetch(`${API_BASE}/workflows/runs/${encodeURIComponent(runId)}/${action}`, { method: 'POST' });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      setError(data.detail || data.error || `Failed to ${action} workflow`);
      return;
    }
    await load(false);
    if (selectedRunId === runId) void getRunDetail(runId, { quiet: true });
  }

  async function skipStep(run: WorkflowRun, step: WorkflowRunStep) {
    setError(null);
    const res = await fetch(`${API_BASE}/workflows/runs/${encodeURIComponent(run.id)}/steps/${step.id}/skip`, { method: 'POST' });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      setError(data.detail || data.error || 'Failed to skip workflow step');
      return;
    }
    setRunStepsById(prev => {
      const next = { ...prev };
      delete next[run.id];
      return next;
    });
    await load(false);
    void getRunDetail(run.id, { quiet: true });
    toast.success('Workflow step skipped');
  }

  async function loadScheduleExecutions(scheduleId: string) {
    const res = await fetch(`${API_BASE}/workflows/schedules/${encodeURIComponent(scheduleId)}/executions`);
    const data = await res.json().catch(() => []);
    if (!res.ok) {
      setError(data.detail || data.error || 'Failed to load schedule executions');
      return;
    }
    setScheduleExecutions(prev => ({ ...prev, [scheduleId]: Array.isArray(data) ? data : [] }));
  }

  async function loadRevisions(definitionId: string) {
    const res = await fetch(`${API_BASE}/workflows/definitions/${encodeURIComponent(definitionId)}/revisions${projectParam}`);
    const data = await res.json().catch(() => []);
    if (!res.ok) {
      setError(data.detail || data.error || 'Failed to load workflow revisions');
      return;
    }
    setSelectedRevisionDefinitionId(definitionId);
    setRevisionsByDefinition(prev => ({ ...prev, [definitionId]: Array.isArray(data) ? data : [] }));
  }

  async function rollbackRevision(definitionId: string, version: number) {
    const res = await fetch(`${API_BASE}/workflows/definitions/${encodeURIComponent(definitionId)}/revisions/${version}/rollback${projectParam}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ change_summary: `Rollback to version ${version}` }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      setError(data.detail || data.error || 'Failed to rollback workflow');
      return;
    }
    await load(false);
    await loadRevisions(definitionId);
    toast.success(`Workflow rolled back to v${version}`);
  }

  async function markNotificationRead(notificationId: string) {
    const res = await fetch(`${API_BASE}/workflows/notifications/${encodeURIComponent(notificationId)}/read`, { method: 'POST' });
    if (!res.ok) return;
    setNotifications(prev => prev.map(item => item.id === notificationId ? { ...item, read_at: new Date().toISOString() } : item));
  }

  function openRunDetails(runId: string) {
    setSelectedRunId(runId);
    setActiveTab('runs');
    void getRunDetail(runId, { quiet: true });
  }

  function resetLibraryFilters() {
    setLibrarySearch('');
    setLibraryStatusFilter('all');
    setLibrarySort('updated');
  }

  async function duplicateWorkflow(definition: WorkflowDefinition) {
    setError(null);
    const res = await fetch(`${API_BASE}/workflows/definitions/${encodeURIComponent(definition.id)}/duplicate${projectParam}`, {
      method: 'POST',
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      setError(data.detail || data.error || 'Failed to duplicate workflow');
      return;
    }
    await load(false);
    toast.success('Workflow duplicated');
  }

  async function archiveWorkflow(definition: WorkflowDefinition) {
    setError(null);
    const res = await fetch(`${API_BASE}/workflows/definitions/${encodeURIComponent(definition.id)}${projectParam}`, {
      method: 'DELETE',
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      setError(data.detail || data.error || 'Failed to archive workflow');
      return;
    }
    if (selectedDefinitionId === definition.id) resetBuilder();
    setDefinitions(prev => prev.filter(item => item.id !== definition.id));
    await load(false);
    toast.success('Workflow archived');
  }

  async function exportWorkflow(definition: WorkflowDefinition) {
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/workflows/definitions/${encodeURIComponent(definition.id)}/export${projectParam}`);
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || data.error || 'Failed to export workflow');
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `${definition.name.replace(/[^A-Za-z0-9_-]+/g, '-').replace(/^-|-$/g, '') || 'workflow'}.json`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to export workflow');
    }
  }

  async function importWorkflowFile(file: File | null) {
    if (!file) return;
    setError(null);
    try {
      const raw = await file.text();
      const workflow = JSON.parse(raw);
      const res = await fetch(`${API_BASE}/workflows/import`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ project_id: currentProject?.id || 'default', workflow }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || data.error || 'Failed to import workflow');
      await load(false);
      setActiveTab('library');
      toast.success('Workflow imported');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to import workflow');
    } finally {
      if (importInputRef.current) importInputRef.current.value = '';
    }
  }

  async function getRunSteps(runId: string, options?: { force?: boolean }) {
    if (!options?.force && runStepsById[runId]) return runStepsById[runId];
    const res = await fetch(`${API_BASE}/workflows/runs/${encodeURIComponent(runId)}/steps`);
    const data = await res.json().catch(() => []);
    if (!res.ok) {
      const detail = data?.detail || data?.error || 'Failed to load workflow steps';
      setError(detail);
      throw new Error(detail);
    }
    const steps = Array.isArray(data) ? data : [];
    setRunStepsById(prev => ({ ...prev, [runId]: steps }));
    return steps;
  }

  async function getRunDetail(runId: string, options?: { quiet?: boolean }) {
    if (!options?.quiet) setRunDetailLoading(true);
    try {
      const res = await fetch(`${API_BASE}/workflows/runs/${encodeURIComponent(runId)}`);
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        const detail = data?.detail || data?.error || 'Failed to load workflow run';
        setError(detail);
        throw new Error(detail);
      }
      setSelectedRunDetails(data);
      if (Array.isArray(data.steps)) {
        setRunStepsById(prev => ({ ...prev, [runId]: data.steps }));
      }
      return data as WorkflowRun;
    } finally {
      if (!options?.quiet) setRunDetailLoading(false);
    }
  }

  async function retryFailedStep(run: WorkflowRun) {
    setError(null);
    try {
      const steps = await getRunSteps(run.id);
      const failedStep = steps.find(step => step.status === 'failed');
      if (!failedStep) {
        setError('No failed step found for this workflow run');
        return;
      }
      const res = await fetch(`${API_BASE}/workflows/runs/${encodeURIComponent(run.id)}/steps/${failedStep.id}/retry`, { method: 'POST' });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setError(data.detail || data.error || 'Failed to retry workflow step');
        return;
      }
      setRunStepsById(prev => {
        const next = { ...prev };
        delete next[run.id];
        return next;
      });
      await load(false);
      void getRunDetail(run.id, { quiet: true });
      toast.success('Failed step queued for retry');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to retry workflow step');
    }
  }

  function tokenOptionsFor(index: number, kinds?: string[], preferredPaths: string[] = []) {
    return steps.slice(0, index).flatMap(step => {
      if (kinds && !kinds.includes(step.type)) return [];
      const outputSchema = catalog.find(item => item.type === step.type)?.output_schema;
      const catalogTokens = outputSchema?.token_catalog || [];
      const fallbackTokens = outputSchema?.tokens || ['external_id'];
      const tokenItems: WorkflowTokenCatalogItem[] = catalogTokens.length > 0
        ? catalogTokens
        : fallbackTokens.map(token => ({ path: String(token), label: String(token).replace(/_/g, ' ') }));
      const filteredTokens = preferredPaths.length > 0
        ? tokenItems.filter(token => preferredPaths.includes(String(token.path)))
        : tokenItems;
      return filteredTokens.map(token => ({
        label: preferredPaths.length > 0 ? `Use ${step.label || defaultLabelFor(step.type, catalog)} output` : `${step.key} ${String(token.label || token.path).replace(/_/g, ' ')}`,
        value: `{{steps.${step.key}.${token.path}}}`,
        stepKey: step.key,
        stepLabel: step.label || defaultLabelFor(step.type, catalog),
        path: token.path,
        type: token.type,
        description: token.description,
      }));
    });
  }

  function recommendedNextStepsFor(step: WorkflowStep, index: number) {
    const sourceStep = step.type === 'wait_for_status'
      ? steps.find(candidate => candidate.key === inputString(step.input || {}, 'source_step'))
      : step;
    if (!sourceStep) return [];
    const metadata = catalog.find(item => item.type === sourceStep.type);
    const recommendations = metadata?.ui_schema?.recommended_next_steps || [];
    const afterWait = step.type === 'wait_for_status';
    return recommendations
      .filter(item => Boolean(item.after_wait) === afterWait)
      .filter(item => steps[index + 1]?.type !== item.type);
  }

  function renderRecommendedNextSteps(step: WorkflowStep, index: number) {
    const recommendations = recommendedNextStepsFor(step, index);
    if (recommendations.length === 0) return null;
    return (
      <div className="workflow-next-step-panel">
        <div>
          <div className="workflow-next-step-title">Recommended next step</div>
          <div className="workflow-next-step-description">
            Continue the workflow without rebuilding the dependency chain manually.
          </div>
        </div>
        <div className="workflow-next-step-actions">
          {recommendations.map(recommendation => (
            <Button
              key={`${step.key}-${recommendation.type}`}
              type="button"
              size="sm"
              variant="outline"
              onClick={() => insertStepAfter(index, recommendation.type)}
            >
              <Plus size={14} /> {recommendation.label || `Add ${defaultLabelFor(recommendation.type, catalog)}`}
            </Button>
          ))}
        </div>
      </div>
    );
  }

  function renderDraftIndicator() {
    if (draftStatus === 'idle') return null;
    const label = draftStatus === 'dirty'
      ? 'Unsaved changes'
      : draftStatus === 'restored'
        ? 'Draft restored'
        : 'Draft saved';
    return (
      <div className="workflow-draft-indicator">
        <span>{label}</span>
        {draftUpdatedAt && <span>{timeAgo(draftUpdatedAt)}</span>}
        <Button type="button" size="sm" variant="ghost" onClick={() => clearDraft()}>Discard draft</Button>
      </div>
    );
  }

  function renderTokenButtons(index: number, inputKey: string, options = tokenOptionsFor(index)) {
    if (options.length === 0) return null;
    return (
      <div style={{ display: 'flex', gap: '0.35rem', flexWrap: 'wrap', marginTop: '0.4rem' }}>
        {options.slice(0, 5).map(option => (
          <Button
            key={`${inputKey}-${option.value}`}
            type="button"
            size="sm"
            variant="outline"
            onClick={() => insertToken(index, inputKey, option.value)}
            style={{ fontSize: '0.72rem', minHeight: 28 }}
          >
            {option.label}
          </Button>
        ))}
        <Button
          type="button"
          size="sm"
          variant="ghost"
          onClick={() => {
            setTokenPicker({ stepIndex: index, inputKey, options });
            setTokenSearch('');
          }}
          style={{ fontSize: '0.72rem', minHeight: 28 }}
        >
          Browse tokens
        </Button>
      </div>
    );
  }

  function insertToken(index: number, inputKey: string, token: string) {
    const current = steps[index]?.input?.[inputKey];
    if (typeof current === 'string' && current.trim()) {
      updateStepInput(index, inputKey, `${current}${current.endsWith(' ') || current.endsWith('\n') ? '' : ' '}${token}`);
    } else {
      updateStepInput(index, inputKey, token);
    }
    setTokenPicker(null);
  }

  function renderTokenBrowser() {
    if (!tokenPicker) return null;
    const query = normalizeSearch(tokenSearch);
    const options = tokenPicker.options.filter(option => {
      if (!query) return true;
      return [option.stepKey, option.stepLabel, option.path, option.label, option.description || '', option.type || '']
        .some(value => value.toLowerCase().includes(query));
    });
    const grouped = options.reduce<Record<string, TokenOption[]>>((acc, option) => {
      acc[option.stepKey] = [...(acc[option.stepKey] || []), option];
      return acc;
    }, {});
    return (
      <div style={tokenBrowserOverlayStyle}>
        <div style={tokenBrowserPanelStyle}>
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: '0.75rem', alignItems: 'center' }}>
            <div>
              <div style={{ fontWeight: 750 }}>Previous step outputs</div>
              <div style={{ color: 'var(--text-secondary)', fontSize: '0.78rem' }}>Insert a token into this field.</div>
            </div>
            <Button size="sm" variant="ghost" onClick={() => setTokenPicker(null)}>Close</Button>
          </div>
          <Input
            value={tokenSearch}
            onChange={event => setTokenSearch(event.target.value)}
            placeholder="Search tokens"
            aria-label="Search workflow output tokens"
          />
          <div style={{ display: 'grid', gap: '0.7rem', maxHeight: 420, overflow: 'auto' }}>
            {Object.entries(grouped).length === 0 ? (
              <div style={emptyDiagnosticStyle}>No previous output tokens match this search.</div>
            ) : Object.entries(grouped).map(([stepKey, items]) => (
              <div key={stepKey} style={{ display: 'grid', gap: '0.4rem' }}>
                <div style={diagnosticLabelStyle}>{stepKey}</div>
                {items.map(option => (
                  <button
                    key={option.value}
                    type="button"
                    onClick={() => insertToken(tokenPicker.stepIndex, tokenPicker.inputKey, option.value)}
                    style={tokenOptionStyle}
                  >
                    <span style={{ fontWeight: 750 }}>{option.label}</span>
                    <code style={inlineCodeStyle}>{option.value}</code>
                    <span style={{ color: 'var(--text-secondary)', fontSize: '0.76rem' }}>
                      {[option.type, option.description].filter(Boolean).join(' - ')}
                    </span>
                  </button>
                ))}
              </div>
            ))}
          </div>
        </div>
      </div>
    );
  }

  function renderSchemaInputs(step: WorkflowStep, index: number) {
    const fields = catalog.find(item => item.type === step.type)?.ui_schema?.fields || [];
    if (fields.length === 0) return null;
    const input = step.input || {};
    const stepLabelForKey = (key: string) => {
      const source = steps.find(candidate => candidate.key === key);
      if (!source) return key;
      return source.label || defaultLabelFor(source.type, catalog) || source.key;
    };
    const missingTokenSourceHelper = (field: WorkflowCatalogField, options: TokenOption[]) => {
      if (!field.token_sources) return null;
      const sourceLabels = field.token_sources.map(type => defaultLabelFor(type, catalog)).join(' or ');
      if (options.length > 0 && !hasInputValue(input, field.key)) {
        return (
          <div className="workflow-field-helper">
            Click “{options[0].label}” below to connect this field.
          </div>
        );
      }
      if (options.length > 0) return null;
      return (
        <div className="workflow-field-helper">
          Add {sourceLabels} before this step, then use its output here.
        </div>
      );
    };

    return (
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '0.75rem' }}>
        {fields.map(field => {
          const value = input[field.key];
          const sourceTokenOptions = field.token_sources ? tokenOptionsFor(index, field.token_sources, preferredTokenPathsForField(field.key)) : [];
          if (field.control === 'textarea') {
            return (
              <div key={field.key} style={{ gridColumn: '1 / -1' }}>
                <Label>{field.label}</Label>
                <textarea
                  value={inputString(input, field.key, field.placeholder || '')}
                  onChange={(event: ChangeEvent<HTMLTextAreaElement>) => updateStepInput(index, field.key, event.target.value)}
                  rows={field.rows || 3}
                  placeholder={field.placeholder}
                  style={textareaStyle}
                />
                {field.tokens && renderTokenButtons(index, field.key)}
                {field.token_sources && renderTokenButtons(index, field.key, sourceTokenOptions)}
                {missingTokenSourceHelper(field, sourceTokenOptions)}
                <FieldError>{validationFieldMessages(validation, index, field.key).join(' ')}</FieldError>
              </div>
            );
          }
          if (field.control === 'string_list') {
            return (
              <div key={field.key}>
                <Label>{field.label}</Label>
                <textarea
                  value={inputList(input, field.key)}
                  onChange={(event: ChangeEvent<HTMLTextAreaElement>) => updateStepInput(index, field.key, event.target.value.split('\n').map(item => item.trim()).filter(Boolean))}
                  rows={field.rows || 3}
                  placeholder={field.placeholder}
                  style={textareaStyle}
                />
                <FieldError>{validationFieldMessages(validation, index, field.key).join(' ')}</FieldError>
              </div>
            );
          }
          if (field.control === 'number') {
            return (
              <div key={field.key}>
                <Label>{field.label}</Label>
                <Input
                  type="number"
                  min={field.min ?? 0}
                  value={inputNumber(input, field.key, Number(value ?? field.min ?? 0))}
                  onChange={event => updateStepInput(index, field.key, Number(event.target.value || 0))}
                />
                <FieldError>{validationFieldMessages(validation, index, field.key).join(' ')}</FieldError>
              </div>
            );
          }
          if (field.control === 'boolean') {
            return (
              <label key={field.key} style={switchRowStyle}>
                <Switch checked={inputBoolean(input, field.key)} onCheckedChange={checked => updateStepInput(index, field.key, checked)} />
                <span>{field.label}</span>
              </label>
            );
          }
          if (field.control === 'select') {
            return (
              <div key={field.key}>
                <Label>{field.label}</Label>
                <Select value={inputString(input, field.key)} onValueChange={next => updateStepInput(index, field.key, next)}>
                  <SelectTrigger><SelectValue placeholder={field.placeholder || 'Choose option'} /></SelectTrigger>
                  <SelectContent>
                    {(field.options || []).map(option => <SelectItem key={option.value} value={option.value}>{option.label}</SelectItem>)}
                  </SelectContent>
                </Select>
                <FieldError>{validationFieldMessages(validation, index, field.key).join(' ')}</FieldError>
              </div>
            );
          }
          if (field.control === 'source_step') {
            const sourceSteps = steps.slice(0, index).filter(candidate => candidate.key.trim());
            const sourceKey = inputString(input, field.key);
            return (
              <div key={field.key}>
                <Label>{field.label}</Label>
                {sourceSteps.length > 0 ? (
                  <Select value={inputString(input, field.key)} onValueChange={next => updateStepInput(index, field.key, next)}>
                    <SelectTrigger><SelectValue placeholder="Choose source" /></SelectTrigger>
                    <SelectContent>
                      {sourceSteps.map(source => (
                        <SelectItem key={source.key} value={source.key}>{source.label || defaultLabelFor(source.type, catalog)}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                ) : (
                  <Input value={inputString(input, field.key)} onChange={event => updateStepInput(index, field.key, event.target.value)} placeholder={field.placeholder || 'source_step'} />
                )}
                {sourceSteps.length === 0 && (
                  <div className="workflow-field-helper">Add a step that starts a job before this wait step.</div>
                )}
                {sourceKey && (
                  <div className="workflow-dependency-hint">Waits for: {stepLabelForKey(sourceKey)}</div>
                )}
                <FieldError>{validationFieldMessages(validation, index, field.key).join(' ')}</FieldError>
              </div>
            );
          }
          if (field.control === 'agent_definition') {
            const selectedAgent = agentDefinitions.find(agent => agent.id === inputString(input, field.key));
            return (
              <div key={field.key}>
                <Label>{field.label}</Label>
                {agentDefinitions.length > 0 ? (
                  <>
                    <Select value={inputString(input, field.key)} onValueChange={next => updateStepInput(index, field.key, next)}>
                      <SelectTrigger><SelectValue placeholder="Choose agent" /></SelectTrigger>
                      <SelectContent>
                        {agentDefinitions.map(agent => <SelectItem key={agent.id} value={agent.id}>{agent.name}</SelectItem>)}
                      </SelectContent>
                    </Select>
                    {!selectedAgent && (
                      <div className="workflow-field-helper">Select an agent definition to continue.</div>
                    )}
                  </>
                ) : (
                  <div className="workflow-agent-empty-state">
                    <div>
                      <strong>No agents available</strong>
                      <p>Create or activate an agent definition before using this step.</p>
                    </div>
                    <a href="/agents" className="workflow-inline-link">Manage agents</a>
                  </div>
                )}
                {selectedAgent && (
                  <div style={{ marginTop: '0.55rem', display: 'grid', gap: '0.45rem', color: 'var(--text-secondary)', fontSize: '0.78rem', lineHeight: 1.45 }}>
                    {selectedAgent.description && <div>{selectedAgent.description}</div>}
                    <div style={{ display: 'flex', gap: '0.4rem', flexWrap: 'wrap' }}>
                      <span style={workflowMetaPillStyle}>{Math.ceil((selectedAgent.timeout_seconds || 1800) / 60)} min timeout</span>
                      <span style={workflowMetaPillStyle}>{pretty(selectedAgent.risk_level || 'low')} risk</span>
                      <span style={workflowMetaPillStyle}>{selectedAgent.tools?.length || selectedAgent.tool_ids?.length || 0} tools</span>
                    </div>
                    {selectedAgent.tools && selectedAgent.tools.length > 0 && (
                      <div style={{ display: 'flex', gap: '0.35rem', flexWrap: 'wrap' }}>
                        {selectedAgent.tools.map(tool => (
                          <span key={tool.id} style={workflowMetaPillStyle}>{tool.label}</span>
                        ))}
                      </div>
                    )}
                  </div>
                )}
                <FieldError>{validationFieldMessages(validation, index, field.key).join(' ')}</FieldError>
              </div>
            );
          }
          if (field.token_sources && sourceTokenOptions.length > 0) {
            const current = typeof value === 'string' ? value : '';
            const currentOption = sourceTokenOptions.find(option => option.value === current);
            return (
              <div key={field.key}>
                <Label>{field.label}</Label>
                <Select value={currentOption ? current : ''} onValueChange={next => updateStepInput(index, field.key, next)}>
                  <SelectTrigger><SelectValue placeholder={`Use output from ${sourceTokenOptions[0]?.stepLabel || 'previous step'}`} /></SelectTrigger>
                  <SelectContent>
                    {sourceTokenOptions.map(option => (
                      <SelectItem key={option.value} value={option.value}>{option.label}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <div className="workflow-field-helper">
                  {currentOption ? `Connected to ${currentOption.stepLabel}.` : 'Choose a previous step output for this field.'}
                </div>
                <Button
                  type="button"
                  size="sm"
                  variant="ghost"
                  onClick={() => {
                    setTokenPicker({ stepIndex: index, inputKey: field.key, options: sourceTokenOptions });
                    setTokenSearch('');
                  }}
                  style={{ justifySelf: 'start', marginTop: '0.4rem' }}
                >
                  Browse outputs
                </Button>
                <FieldError>{validationFieldMessages(validation, index, field.key).join(' ')}</FieldError>
              </div>
            );
          }
          return (
            <div key={field.key}>
              <Label>{field.label}</Label>
              <Input
                value={typeof value === 'string' ? value : ''}
                onChange={event => updateStepInput(index, field.key, event.target.value)}
                placeholder={field.placeholder}
              />
              {field.token_sources && renderTokenButtons(index, field.key, sourceTokenOptions)}
              {missingTokenSourceHelper(field, sourceTokenOptions)}
              <FieldError>{validationFieldMessages(validation, index, field.key).join(' ')}</FieldError>
            </div>
          );
        })}
      </div>
    );
  }

  function renderTypedInputs(step: WorkflowStep, index: number) {
    const schemaInputs = renderSchemaInputs(step, index);
    if (schemaInputs) return schemaInputs;

    return (
      <div style={{ color: 'var(--text-secondary)', fontSize: '0.84rem' }}>
        This step type is missing registry UI schema. Use advanced JSON for its inputs.
      </div>
    );
  }

  function renderStepCatalog() {
    const query = normalizeSearch(catalogSearch);
    const searched = catalog.filter(item => {
      if (!query) return true;
      return [item.label, item.description, item.type, item.category || ''].some(value => value.toLowerCase().includes(query));
    });
    const categories = Array.from(new Set(searched.map(item => item.category || 'Utility')))
      .sort((a, b) => {
        const ai = catalogCategoryOrder.indexOf(a);
        const bi = catalogCategoryOrder.indexOf(b);
        if (ai !== -1 || bi !== -1) return (ai === -1 ? 999 : ai) - (bi === -1 ? 999 : bi);
        return a.localeCompare(b);
      });
    const filtered = catalogCategory === 'All' ? searched : searched.filter(item => (item.category || 'Utility') === catalogCategory);
    const grouped = filtered.reduce<Record<string, CatalogStep[]>>((acc, item) => {
      const category = item.category || 'Utility';
      acc[category] = [...(acc[category] || []), item];
      return acc;
    }, {});

    if (catalog.length === 0) {
      return (
        <Alert>
          <AlertTriangle size={16} />
          <AlertTitle>Step catalog unavailable</AlertTitle>
          <AlertDescription>Builder authoring is limited until the backend registry is available.</AlertDescription>
        </Alert>
      );
    }

    return (
      <div className="workflow-catalog">
        <div className="workflow-catalog-toolbar">
          <div className="workflow-catalog-filter-row" role="group" aria-label="Step category filter">
            {['All', ...categories].map(category => {
              const count = category === 'All' ? searched.length : searched.filter(item => (item.category || 'Utility') === category).length;
              const isActive = catalogCategory === category;
              return (
                <button
                  key={category}
                  type="button"
                  className={isActive ? 'workflow-catalog-filter is-active' : 'workflow-catalog-filter'}
                  aria-pressed={isActive}
                  onClick={() => setCatalogCategory(category)}
                >
                  <span className="workflow-catalog-filter-label">{category}</span>
                  <span className="workflow-catalog-filter-count">{count}</span>
                </button>
              );
            })}
          </div>
          <label className="workflow-catalog-wait-toggle">
            <Switch checked={autoAddWaitSteps} onCheckedChange={setAutoAddWaitSteps} />
            <span>Include wait step for async actions</span>
          </label>
        </div>
        <div className="workflow-catalog-search">
          <Search size={15} className="workflow-catalog-search-icon" />
          <Input
            value={catalogSearch}
            onChange={event => setCatalogSearch(event.target.value)}
            placeholder="Search step catalog"
            aria-label="Search step catalog"
            style={{ paddingLeft: 34 }}
          />
        </div>
        {filtered.length === 0 ? (
          <EmptyState
            title="No matching steps"
            description="No registered step types match this search or category."
            icon={<Search size={28} />}
          />
        ) : Object.entries(grouped).map(([category, items]) => (
          <div key={category} className="workflow-catalog-group">
            <div className="workflow-catalog-group-title">{category}</div>
            <div className="workflow-catalog-grid">
              {items.map(item => (
                <button
                  key={item.type}
                  type="button"
                  onClick={() => addStep(item.type)}
                  className="workflow-catalog-step"
                  data-risk={normalizeSearch(item.risk_level || 'low')}
                >
                  <div className="workflow-catalog-step-header">
                    <strong className="workflow-catalog-step-title">{item.label}</strong>
                    <span className="workflow-catalog-risk">{pretty(item.risk_level || 'low')}</span>
                  </div>
                  <div className="workflow-catalog-step-description">{item.description}</div>
                  <div className="workflow-catalog-meta-row">
                    <span className="workflow-catalog-meta">{item.required?.length || 0} required</span>
                    {item.is_async && <span className="workflow-catalog-meta workflow-catalog-meta-accent">{autoAddWaitSteps ? 'Adds wait step' : 'Async'}</span>}
                  </div>
                </button>
              ))}
            </div>
          </div>
        ))}
      </div>
    );
  }

  function renderTemplates() {
    const query = normalizeSearch(templateSearch);
    const categories = Array.from(new Set(workflowTemplates.map(template => template.category || 'General'))).sort();
    const visibleTemplates = workflowTemplates
      .filter(template => templateCategory === 'All' || (template.category || 'General') === templateCategory)
      .filter(template => {
        if (!query) return true;
        const fields = [
          template.name,
          template.description,
          template.useCase,
          template.category || '',
          ...(template.tags || []),
          ...(template.step_types || []),
        ];
        return fields.some(field => field.toLowerCase().includes(query));
      });
    if (workflowTemplates.length === 0) {
      return (
        <EmptyState
          title="No workflow templates"
          description="Templates cover common paths like exploration, agents, and regression. Use the manual step catalog when your sequence is custom."
          icon={<FileText size={28} />}
        />
      );
    }
    return (
      <div style={{ display: 'grid', gap: '1rem' }}>
        <div style={{ display: 'grid', gap: '0.65rem' }}>
          <div style={{ position: 'relative' }}>
            <Search size={15} style={{ position: 'absolute', left: 12, top: '50%', transform: 'translateY(-50%)', color: 'var(--text-secondary)' }} />
            <Input
              value={templateSearch}
              onChange={event => setTemplateSearch(event.target.value)}
              placeholder="Search templates"
              aria-label="Search workflow templates"
              style={{ paddingLeft: 34 }}
            />
          </div>
          <div style={{ display: 'flex', gap: '0.45rem', flexWrap: 'wrap' }}>
            {['All', ...categories].map(category => (
              <Button
                key={category}
                type="button"
                size="sm"
                variant={templateCategory === category ? 'default' : 'outline'}
                onClick={() => setTemplateCategory(category)}
              >
                {category}
              </Button>
            ))}
          </div>
        </div>
        {visibleTemplates.length === 0 ? (
          <EmptyState title="No matching templates" description="No workflow templates match this search or category." icon={<Search size={28} />} />
        ) : (
          <div className="workflow-card-grid workflow-template-grid">
        {visibleTemplates.map(template => (
          <article
            key={template.id}
            className="card-elevated workflow-template-card"
          >
            <div className="workflow-template-content">
              <div className="workflow-card-header">
                <div style={{ minWidth: 0 }}>
                  <h3 className="workflow-card-title">{template.name}</h3>
                  <div className="workflow-template-use-case">
                    {template.useCase}
                  </div>
                </div>
                <div className="workflow-template-icon">
                  <FileText size={17} />
                </div>
              </div>
              <p className="workflow-card-description">
                {template.description}
              </p>
              <div className="workflow-meta-row">
                <span style={workflowMetaPillStyle}>{template.steps.length} steps</span>
                {template.category && <span style={workflowMetaPillStyle}>{template.category}</span>}
                {template.risk_level && <span style={workflowMetaPillStyle}>{pretty(template.risk_level)} risk</span>}
                {template.estimated_duration_minutes && <span style={workflowMetaPillStyle}>{template.estimated_duration_minutes} min</span>}
                {template.steps.slice(0, 3).map(step => (
                  <span key={`${template.id}-${step.key}`} style={workflowMetaPillStyle}>{step.label || defaultLabelFor(step.type, catalog)}</span>
                ))}
              </div>
            </div>
            <Button onClick={() => applyTemplate(template)} style={{ justifySelf: 'start' }}>
              <Sparkles size={15} /> Use template
            </Button>
          </article>
        ))}
          </div>
        )}
      </div>
    );
  }

  function renderLibrary() {
    const selectedRevisionDefinition = definitions.find(item => item.id === selectedRevisionDefinitionId);
    const selectedRevisions = selectedRevisionDefinitionId ? revisionsByDefinition[selectedRevisionDefinitionId] || [] : [];
    if (loading) return <WorkflowSkeleton />;
    if (definitions.length === 0) {
      return (
        <EmptyState
          title="No workflows"
          description="Create a reusable automation flow from backend templates or build a custom sequence."
          icon={<Workflow size={28} />}
          action={
            <div style={{ display: 'flex', gap: '0.5rem', justifyContent: 'center', flexWrap: 'wrap' }}>
              <Button onClick={() => setActiveTab('templates')} variant="outline"><Sparkles size={15} /> Browse templates</Button>
              <Button onClick={() => resetBuilder()}><Plus size={15} /> Create workflow</Button>
            </div>
          }
        />
      );
    }

    return (
      <div className="workflow-stack">
        {selectedRevisionDefinition && (
          <Section
            title={`Versions: ${selectedRevisionDefinition.name}`}
            description="Rollback creates a new version from the selected snapshot."
            action={<Button size="sm" variant="ghost" onClick={() => setSelectedRevisionDefinitionId('')}><X size={14} /> Close</Button>}
          >
            {selectedRevisions.length === 0 ? (
              <div style={emptyDiagnosticStyle}>No revisions loaded.</div>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Version</TableHead>
                    <TableHead>Summary</TableHead>
                    <TableHead>Steps</TableHead>
                    <TableHead>Created</TableHead>
                    <TableHead style={{ textAlign: 'right' }}>Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {selectedRevisions.map(revision => (
                    <TableRow key={revision.id}>
                      <TableCell>v{revision.version}</TableCell>
                      <TableCell>{revision.change_summary || '-'}</TableCell>
                      <TableCell>{revision.steps?.length || 0}</TableCell>
                      <TableCell>{timeAgo(revision.created_at)}</TableCell>
                      <TableCell style={{ textAlign: 'right' }}>
                        <Button
                          size="sm"
                          variant="outline"
                          disabled={revision.version === selectedRevisionDefinition.version}
                          onClick={() => rollbackRevision(selectedRevisionDefinition.id, revision.version)}
                        >
                          <RotateCcw size={14} /> Rollback
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </Section>
        )}
        <div className="workflow-library-controls" style={libraryControlsStyle}>
          <div className="workflow-library-search">
            <Search size={15} style={{ position: 'absolute', left: 12, top: '50%', transform: 'translateY(-50%)', color: 'var(--text-secondary)' }} />
            <Input
              value={librarySearch}
              onChange={event => setLibrarySearch(event.target.value)}
              placeholder="Search workflows"
              aria-label="Search workflows"
              style={{ paddingLeft: 34 }}
            />
          </div>
          <Select value={libraryStatusFilter} onValueChange={value => setLibraryStatusFilter(value as LibraryStatusFilter)}>
            <SelectTrigger className="workflow-library-select workflow-library-select-status"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All statuses</SelectItem>
              <SelectItem value="active">Has active run</SelectItem>
              <SelectItem value="failed">Last failed</SelectItem>
              <SelectItem value="completed">Last completed</SelectItem>
              <SelectItem value="never_run">Never run</SelectItem>
            </SelectContent>
          </Select>
          <Select value={librarySort} onValueChange={value => setLibrarySort(value as LibrarySort)}>
            <SelectTrigger className="workflow-library-select workflow-library-select-sort"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="updated">Recently updated</SelectItem>
              <SelectItem value="last_run">Last run</SelectItem>
              <SelectItem value="name">Name</SelectItem>
            </SelectContent>
          </Select>
          {(librarySearch || libraryStatusFilter !== 'all' || librarySort !== 'updated') && (
            <Button size="sm" variant="ghost" onClick={resetLibraryFilters}>
              <X size={14} /> Reset
            </Button>
          )}
        </div>

        {visibleDefinitions.length === 0 ? (
          <EmptyState
            title="No workflows match"
            description="No workflows match this search or filter."
            icon={<Search size={28} />}
            action={<Button onClick={resetLibraryFilters} variant="outline">Reset filters</Button>}
          />
        ) : (
          <div className="workflow-card-grid workflow-library-grid">
            {visibleDefinitions.map(definition => {
              const lastRun = latestRunByDefinition.get(definition.id);
              const workflowSchedules = schedulesByDefinition.get(definition.id) || [];
              const nextSchedule = workflowSchedules.find(schedule => schedule.enabled && schedule.next_run_at);
              return (
                <article
                  key={definition.id}
                  className="card-elevated workflow-library-card"
                >
                  <div className="workflow-library-card-body">
                    <div className="workflow-card-header">
                      <div style={{ minWidth: 0 }}>
                        <h3
                          title={definition.name}
                          className="workflow-card-title workflow-card-title-clamped"
                        >
                          {definition.name}
                        </h3>
                        <p
                          className="workflow-card-description workflow-card-description-clamped"
                        >
                          {definition.description || 'No description'}
                        </p>
                      </div>
                      {lastRun ? <StatusBadge status={lastRun.status} /> : <span style={workflowMetaPillStyle}>Never run</span>}
                    </div>
                    <div className="workflow-meta-row">
                      <span style={workflowMetaPillStyle}>{definition.steps?.length || 0} steps</span>
                      <span style={workflowMetaPillStyle}>v{definition.version || 1}</span>
                      <span style={workflowMetaPillStyle}>{workflowSchedules.length} schedules</span>
                      <span style={workflowMetaPillStyle}>Updated {definition.updated_at ? timeAgo(definition.updated_at) : '-'}</span>
                      <span style={workflowMetaPillStyle}>{lastRun ? `Last run ${timeAgo(lastRun.created_at)}` : 'Never run'}</span>
                    </div>
                    {nextSchedule?.next_run_at && (
                      <div style={{ color: 'var(--text-secondary)', fontSize: '0.78rem' }}>
                        Next schedule: {timeAgo(nextSchedule.next_run_at)} · {nextSchedule.cron_expression}
                      </div>
                    )}
                    {lastRun?.error_message && (
                      <div style={{ color: 'var(--danger)', fontSize: '0.78rem', lineHeight: 1.4, overflow: 'hidden', display: '-webkit-box', WebkitBoxOrient: 'vertical', WebkitLineClamp: 2 }}>
                        {lastRun.error_message}
                      </div>
                    )}
                  </div>
                  <div
                    className="workflow-card-footer"
                  >
                    <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap', minWidth: 0 }}>
                      <Button size="sm" onClick={() => startWorkflow(definition.id)} style={{ minWidth: 92 }}>
                        <Play size={14} /> Run Now
                      </Button>
                      {nextSchedule && (
                        <Button size="sm" variant="outline" onClick={() => runScheduleNow(nextSchedule)}>
                          <Clock size={14} /> Run schedule
                        </Button>
                      )}
                      {lastRun && isRunFailed(lastRun) && (
                        <Button size="sm" variant="outline" onClick={() => openRunDetails(lastRun.id)}>
                          <Eye size={14} /> Open failed run
                        </Button>
                      )}
                    </div>
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button size="icon" variant="outline" title="Run from a specific step and workflow actions" aria-label="Run from a specific step and workflow actions" style={workflowIconButtonStyle}>
                          <MoreHorizontal size={15} />
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent
                        align="end"
                        side="bottom"
                        sideOffset={8}
                        collisionPadding={16}
                        className="workflow-action-menu"
                        style={{
                          zIndex: 1000,
                          background: 'var(--background-raised)',
                          border: '1px solid var(--border)',
                          boxShadow: '0 18px 45px rgba(0,0,0,0.42)',
                        }}
                      >
                        <DropdownMenuLabel style={{ color: 'var(--text-secondary)', fontSize: '0.72rem', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
                          Run From Step
                        </DropdownMenuLabel>
                        {(definition.steps || []).map((step, index) => (
                          <DropdownMenuItem
                            className="workflow-action-menu-item"
                            key={`${definition.id}-${step.key}`}
                            onSelect={() => startWorkflow(definition.id, step.key)}
                            style={{ cursor: 'pointer' }}
                          >
                            <span style={{ width: 20, color: 'var(--text-secondary)', fontVariantNumeric: 'tabular-nums', flexShrink: 0 }}>{index + 1}</span>
                            <ListStart size={14} style={{ color: 'var(--primary)' }} />
                            <span className="workflow-action-menu-text">
                              {step.label || step.key}
                            </span>
                          </DropdownMenuItem>
                        ))}
                        <DropdownMenuSeparator />
                        <DropdownMenuItem className="workflow-action-menu-item" onSelect={() => selectDefinition(definition)} style={{ cursor: 'pointer' }}>
                          <Edit3 size={14} /> Edit workflow
                        </DropdownMenuItem>
                        <DropdownMenuItem className="workflow-action-menu-item" onSelect={() => openScheduleDialog(definition)} style={{ cursor: 'pointer' }}>
                          <Clock size={14} /> Schedule workflow
                        </DropdownMenuItem>
                        <DropdownMenuItem className="workflow-action-menu-item" onSelect={() => loadRevisions(definition.id)} style={{ cursor: 'pointer' }}>
                          <RotateCcw size={14} /> Version history
                        </DropdownMenuItem>
                        <DropdownMenuItem className="workflow-action-menu-item" onSelect={() => duplicateWorkflow(definition)} style={{ cursor: 'pointer' }}>
                          <Copy size={14} /> Duplicate workflow
                        </DropdownMenuItem>
                        <DropdownMenuItem className="workflow-action-menu-item" onSelect={() => exportWorkflow(definition)} style={{ cursor: 'pointer' }}>
                          <FileText size={14} /> Export JSON
                        </DropdownMenuItem>
                        <DropdownMenuItem className="workflow-action-menu-item" onSelect={() => archiveWorkflow(definition)} style={{ cursor: 'pointer', color: 'var(--danger)' }}>
                          <Archive size={14} /> Archive workflow
                        </DropdownMenuItem>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </div>
                </article>
              );
            })}
          </div>
        )}
      </div>
    );
  }

  function renderRecoveryControls(step: WorkflowStep, index: number) {
    const policy = step.recovery_policy || { action: 'fail', max_attempts: 1, retry_backoff_seconds: 0 };
    const action = policy.action || 'fail';
    return (
      <div className="workflow-advanced-panel" style={{ marginTop: '0.75rem' }}>
        <div className="workflow-step-fields-grid">
          <div>
            <Label>On failure</Label>
            <Select value={action} onValueChange={value => updateStepRecovery(index, { action: value as RecoveryPolicy['action'] })}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="fail">Fail workflow</SelectItem>
                <SelectItem value="retry">Retry step</SelectItem>
                <SelectItem value="skip">Skip step</SelectItem>
                <SelectItem value="pause">Pause workflow</SelectItem>
                <SelectItem value="notify">Notify and fail</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div>
            <Label>Max attempts</Label>
            <Input
              type="number"
              min={1}
              value={String(policy.max_attempts ?? 1)}
              disabled={action !== 'retry'}
              onChange={event => updateStepRecovery(index, { max_attempts: Number(event.target.value || 1) })}
            />
          </div>
          <div>
            <Label>Backoff seconds</Label>
            <Input
              type="number"
              min={0}
              value={String(policy.retry_backoff_seconds ?? 0)}
              disabled={action !== 'retry'}
              onChange={event => updateStepRecovery(index, { retry_backoff_seconds: Number(event.target.value || 0) })}
            />
          </div>
        </div>
      </div>
    );
  }

  function renderBuilder() {
    return (
      <div className="workflow-stack">
        <Section
          title={selectedDefinitionId ? 'Edit workflow' : 'Create workflow'}
          description="Configure the workflow metadata and ordered automation steps."
          action={
            <div className="workflow-builder-actions">
              {renderDraftIndicator()}
              <Button size="sm" variant="outline" onClick={() => resetBuilder()}><Plus size={14} /> New</Button>
            </div>
          }
        >
          <div className="workflow-builder-meta-grid">
            <div>
              <Label>Name</Label>
              <Input value={name} onChange={event => setName(event.target.value)} />
            </div>
            <div>
              <Label>Description</Label>
              <textarea
                value={description}
                onChange={(event: ChangeEvent<HTMLTextAreaElement>) => setDescription(event.target.value)}
                rows={2}
                style={textareaStyle}
              />
            </div>
          </div>
          <FieldError>{validation.form}</FieldError>
        </Section>

        <Section
          title="Step catalog"
          description="Available steps are loaded from the backend registry."
        >
          {renderStepCatalog()}
        </Section>

        <Section
          title="Steps"
          description="Build a reusable sequence. Raw JSON is available under advanced options."
          action={
            <Button size="sm" variant="outline" onClick={() => addStep(catalog[0]?.type || 'review_gate')} disabled={catalog.length === 0 && !steps.length}>
              <Plus size={14} /> Step
            </Button>
          }
        >
          {catalogError && (
            <Alert style={{ marginBottom: '1rem' }}>
              <AlertTriangle size={16} />
              <AlertTitle>Catalog unavailable</AlertTitle>
              <AlertDescription>{catalogError}</AlertDescription>
            </Alert>
          )}

          <div className="workflow-step-list">
            {steps.map((step, index) => {
              const stepErrors = validationMessagesForStep(validation, index);
              const stepWarnings = validation.warnings?.[index] || [];
              const jsonValue = jsonDrafts[index] ?? JSON.stringify(step.input || {}, null, 2);
              const continueOnError = Boolean(step.continue_on_error);
              const continueOnErrorId = `workflow-step-${index}-continue-on-error`;
              const continueOnErrorLabelId = `${continueOnErrorId}-label`;
              const isWaitStep = step.type === 'wait_for_status';
              const waitSourceKey = isWaitStep ? inputString(step.input || {}, 'source_step') : '';
              const waitSourceStep = waitSourceKey ? steps.find(candidate => candidate.key === waitSourceKey) : undefined;
              const waitSourceLabel = waitSourceStep ? waitSourceStep.label || defaultLabelFor(waitSourceStep.type, catalog) : waitSourceKey;
              const catalogDescription = catalog.find(item => item.type === step.type)?.description || 'Custom workflow step';
              return (
                <article key={`workflow-step-${index}`} className={isWaitStep ? 'workflow-step-card workflow-step-card-dependent' : 'workflow-step-card'}>
                  <div className="workflow-step-card-header">
                    <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'flex-start', minWidth: 0 }}>
                      <div className="workflow-step-index">
                        {index + 1}
                      </div>
                      <div style={{ minWidth: 0 }}>
                        <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', flexWrap: 'wrap' }}>
                          <strong>{step.label || defaultLabelFor(step.type, catalog)}</strong>
                          {stepErrors.length > 0 ? (
                            <span className="workflow-step-status workflow-step-status-error">Needs setup</span>
                          ) : stepWarnings.length > 0 ? (
                            <span className="workflow-step-status workflow-step-status-warning">Warning</span>
                          ) : validating ? (
                            <span className="workflow-step-status">Checking</span>
                          ) : (
                            <span className="workflow-step-status workflow-step-status-valid">Valid</span>
                          )}
                        </div>
                        <div className="workflow-step-description">
                          <span>{catalogDescription}</span>
                        </div>
                        {isWaitStep && waitSourceLabel && (
                          <div className="workflow-dependency-hint">Depends on: {waitSourceLabel}</div>
                        )}
                      </div>
                    </div>
                    <div className="workflow-step-actions">
                      <Button size="icon" variant="ghost" title="Move step up" aria-label="Move step up" onClick={() => moveStep(index, -1)} disabled={index === 0}><ArrowUp size={15} /></Button>
                      <Button size="icon" variant="ghost" title="Move step down" aria-label="Move step down" onClick={() => moveStep(index, 1)} disabled={index === steps.length - 1}><ArrowDown size={15} /></Button>
                      <Button size="icon" variant="ghost" title="Duplicate step" aria-label="Duplicate step" onClick={() => duplicateStep(index)}><Copy size={15} /></Button>
                      <Button size="icon" variant="ghost" title="Remove step" aria-label="Remove step" onClick={() => removeStep(index)}><Trash2 size={15} /></Button>
                    </div>
                  </div>

                  <div className="workflow-step-card-body">
                    <div className="workflow-step-fields-grid">
                      <div>
                        <Label>Key</Label>
                        <Input value={step.key} onChange={event => updateStep(index, { key: event.target.value })} />
                      </div>
                      <div>
                        <Label>Type</Label>
                        {catalog.length > 0 ? (
                          <Select value={step.type} onValueChange={value => updateStep(index, { type: value, input: contextualDefaultInputFor(value, catalog, steps.slice(0, index)), label: defaultLabelFor(value, catalog) })}>
                            <SelectTrigger><SelectValue /></SelectTrigger>
                            <SelectContent>
                              {catalog.map(item => <SelectItem key={item.type} value={item.type}>{item.label}</SelectItem>)}
                            </SelectContent>
                          </Select>
                        ) : (
                          <Input value={pretty(step.type)} disabled />
                        )}
                      </div>
                    </div>

                    <div style={continueOnError ? { ...switchRowStyle, ...switchRowActiveStyle } : switchRowStyle}>
                      <Switch
                        id={continueOnErrorId}
                        checked={continueOnError}
                        onCheckedChange={checked => updateStep(index, { continue_on_error: checked })}
                        aria-labelledby={continueOnErrorLabelId}
                      />
                      <label id={continueOnErrorLabelId} htmlFor={continueOnErrorId} style={switchLabelStyle}>
                        Continue if this step fails
                      </label>
                    </div>

                    {renderRecoveryControls(step, index)}
                    {renderTypedInputs(step, index)}
                    {renderRecommendedNextSteps(step, index)}

                    <div className="workflow-advanced-panel">
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        className="workflow-advanced-toggle"
                        onClick={() => setAdvancedOpen(prev => ({ ...prev, [index]: !prev[index] }))}
                        aria-expanded={Boolean(advancedOpen[index])}
                      >
                        {advancedOpen[index] ? 'Hide advanced' : 'Advanced'}
                      </Button>
                      <div className="workflow-advanced-summary">Edit raw step input JSON.</div>
                      {advancedOpen[index] && (
                        <div className="workflow-advanced-body">
                          <textarea
                            value={jsonValue}
                            rows={7}
                            onChange={(event: ChangeEvent<HTMLTextAreaElement>) => handleAdvancedJson(index, event.target.value)}
                            style={{ ...textareaStyle, fontFamily: 'monospace', fontSize: '0.82rem' }}
                          />
                          <FieldError>{jsonErrors[index]}</FieldError>
                        </div>
                      )}
                    </div>

                    {stepErrors.length > 0 && (
                      <Alert variant="destructive">
                        <AlertTriangle size={16} />
                        <AlertTitle>Step needs attention</AlertTitle>
                        <AlertDescription>{stepErrors.join(' ')}</AlertDescription>
                      </Alert>
                    )}
                    {stepErrors.length === 0 && stepWarnings.length > 0 && (
                      <Alert>
                        <AlertTriangle size={16} />
                        <AlertTitle>Step warning</AlertTitle>
                        <AlertDescription>{stepWarnings.join(' ')}</AlertDescription>
                      </Alert>
                    )}
                  </div>
                </article>
              );
            })}
          </div>

          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '0.75rem', marginTop: '1rem', flexWrap: 'wrap' }}>
            <div style={{ color: 'var(--text-secondary)', fontSize: '0.82rem' }}>
              {steps.length} step{steps.length === 1 ? '' : 's'} configured
            </div>
            <div style={{ display: 'flex', gap: '0.6rem', flexWrap: 'wrap' }}>
              <Button variant="outline" onClick={() => addStep('review_gate')}><Plus size={15} /> Review gate</Button>
              <Button onClick={saveDefinition} disabled={saving || validating || Object.keys(validation.steps).length > 0 || Object.keys(validation.fieldErrors || {}).length > 0}>
                {saving || validating ? <Loader2 size={15} style={{ animation: 'spin 1s linear infinite' }} /> : <CheckCircle2 size={15} />}
                {selectedDefinitionId ? 'Save Changes' : 'Create Workflow'}
              </Button>
            </div>
          </div>
        </Section>
      </div>
    );
  }

  function renderExternalReference(step: WorkflowRunStep) {
    const kind = step.external_kind || (typeof step.output?.external_kind === 'string' ? step.output.external_kind : null);
    const id = step.external_id || (typeof step.output?.external_id === 'string' ? step.output.external_id : null);
    if (!kind && !id) return null;
    const href = externalHref(kind, id);
    return (
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.45rem', flexWrap: 'wrap', color: 'var(--text-secondary)', fontSize: '0.78rem' }}>
        <span>{externalLabel(kind)}</span>
        {id && <code style={inlineCodeStyle}>{id}</code>}
        {href && (
          <a href={href} style={linkActionStyle}>
            Open <ExternalLink size={12} />
          </a>
        )}
      </div>
    );
  }

  function renderStepDiagnostics(step: WorkflowRunStep) {
    const outputStatus = externalStatusFromStep(step);
    const outputText = compactJson(step.output);
    const inputText = compactJson(step.input);
    const renderedInputText = compactJson(step.rendered_input);
    const contextText = compactJson(step.context_snapshot);
    const resolutionText = compactJson(step.input_resolution);
    const contractText = compactJson({
      output_schema: step.step_config?.output_schema,
      validation_errors: step.output_validation_errors || [],
    });
    return (
      <div style={diagnosticBoxStyle}>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: '0.75rem', flexWrap: 'wrap' }}>
          <div>
            <div style={{ fontWeight: 750, color: 'var(--text)' }}>{step.label || step.step_key}</div>
            <div style={{ color: 'var(--text-secondary)', fontSize: '0.78rem', marginTop: '0.15rem' }}>
              Step {step.step_order + 1} - {pretty(step.step_type)}
            </div>
          </div>
          <div style={{ display: 'flex', gap: '0.4rem', alignItems: 'center', flexWrap: 'wrap' }}>
            <StatusBadge status={outputStatus || step.status} />
            {selectedRun && ['failed', 'pending', 'running', 'awaiting_input'].includes(step.status) && (
              <Button size="sm" variant="outline" onClick={() => skipStep(selectedRun, step)}>
                <ListStart size={14} /> Skip
              </Button>
            )}
          </div>
        </div>
        {step.error_message && (
          <Alert variant="destructive" style={{ marginTop: '0.75rem' }}>
            <AlertTriangle size={15} />
            <AlertTitle>Step failed</AlertTitle>
            <AlertDescription>{step.error_message}</AlertDescription>
          </Alert>
        )}
        {!step.error_message && outputStatus && attentionStatuses.includes(outputStatus) && (
          <Alert variant="destructive" style={{ marginTop: '0.75rem' }}>
            <AlertTriangle size={15} />
            <AlertTitle>Child job reported {pretty(outputStatus)}</AlertTitle>
            <AlertDescription>The workflow step completed, but the child job it waited on reported a terminal problem.</AlertDescription>
          </Alert>
        )}
        <div style={{ display: 'grid', gap: '0.6rem', marginTop: '0.75rem' }}>
          {renderExternalReference(step)}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '0.75rem' }}>
            <details style={detailDisclosureStyle} open>
              <summary style={summaryStyle}>Resolved Input</summary>
              <pre style={preStyle}>{renderedInputText || 'No resolved input captured.'}</pre>
            </details>
            <details style={detailDisclosureStyle}>
              <summary style={summaryStyle}>Declared Input</summary>
              <pre style={preStyle}>{inputText || '{}'}</pre>
            </details>
            <details style={detailDisclosureStyle} open={Boolean(step.output && (step.error_message || outputStatus))}>
              <summary style={summaryStyle}>Output</summary>
              <pre style={preStyle}>{outputText || 'No output captured.'}</pre>
            </details>
            <details style={detailDisclosureStyle}>
              <summary style={summaryStyle}>Context Snapshot</summary>
              <pre style={preStyle}>{contextText || 'No context snapshot captured.'}</pre>
            </details>
            <details style={detailDisclosureStyle}>
              <summary style={summaryStyle}>Input Resolution</summary>
              <pre style={preStyle}>{resolutionText || 'No template references resolved.'}</pre>
            </details>
            <details style={detailDisclosureStyle}>
              <summary style={summaryStyle}>Output Contract</summary>
              <pre style={preStyle}>{contractText || 'No output contract metadata captured.'}</pre>
            </details>
          </div>
        </div>
      </div>
    );
  }

  function renderArtifactLinks(artifacts: AutoPilotLiveArtifact[]) {
    if (artifacts.length === 0) {
      return (
        <div style={emptyDiagnosticStyle}>
          No task artifacts were captured for this child run.
        </div>
      );
    }
    return (
      <div style={{ display: 'flex', gap: '0.45rem', flexWrap: 'wrap' }}>
        {artifacts.slice(0, 8).map(artifact => (
          <a
            key={`${artifact.path}-${artifact.name}`}
            href={`${API_BASE}${artifact.path}`}
            target="_blank"
            rel="noreferrer"
            style={artifactLinkStyle}
          >
            {artifact.type} - {artifact.name}
          </a>
        ))}
      </div>
    );
  }

  function renderAutoPilotTaskDiagnostics() {
    const currentTask = autoPilotTaskDetail
      || autoPilotTestTasks.find(task => task.id === autoPilotLive?.test_task_id)
      || autoPilotTestTasks.find(task => task.run_id === autoPilotLive?.run_id)
      || null;

    if (autoPilotTaskLoading && !currentTask) {
      return (
        <div style={liveActivityStyle}>
          <Loader2 size={15} className="spin" /> Loading child test task...
        </div>
      );
    }

    if (!currentTask) {
      return (
        <div style={liveActivityStyle}>
          <div style={{ fontWeight: 750, marginBottom: '0.4rem' }}>Child Test Run</div>
          <div style={emptyDiagnosticStyle}>
            No child test run is linked yet. It appears after AutoPilot starts generating or executing a test.
          </div>
        </div>
      );
    }

    const detail = autoPilotTaskDetail;
    const artifacts = detail?.artifacts || [];
    return (
      <div style={liveActivityStyle}>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: '0.75rem', alignItems: 'flex-start', flexWrap: 'wrap' }}>
          <div style={{ minWidth: 0 }}>
            <div style={{ fontWeight: 750 }}>Child Test Run</div>
            <div style={{ color: 'var(--text-secondary)', fontSize: '0.78rem', marginTop: '0.2rem', overflowWrap: 'anywhere' }}>
              {currentTask.spec_name || currentTask.test_path || 'AutoPilot test task'}
            </div>
          </div>
          <StatusBadge status={currentTask.passed === true ? 'passed' : currentTask.passed === false ? 'failed' : currentTask.status} />
        </div>

        <div style={{ display: 'flex', gap: '0.45rem', flexWrap: 'wrap', marginTop: '0.7rem' }}>
          {currentTask.run_id ? (
            <a href={`/runs/${encodeURIComponent(currentTask.run_id)}`} style={linkActionStyle}>
              Open run <ExternalLink size={12} />
            </a>
          ) : (
            <span style={emptyDiagnosticStyle}>No child run ID captured.</span>
          )}
          {detail?.report_url && (
            <a href={`${API_BASE}${detail.report_url}`} target="_blank" rel="noreferrer" style={linkActionStyle}>
              HTML report <ExternalLink size={12} />
            </a>
          )}
        </div>

        {(currentTask.error_summary || detail?.pipeline_error) && (
          <Alert variant="destructive" style={{ marginTop: '0.75rem' }}>
            <AlertTriangle size={15} />
            <AlertTitle>Child run diagnostic</AlertTitle>
            <AlertDescription>
              {currentTask.error_summary || 'Pipeline error details are available in the task payload.'}
            </AlertDescription>
          </Alert>
        )}

        <div style={{ marginTop: '0.75rem', display: 'grid', gap: '0.65rem' }}>
          <div>
            <div style={diagnosticLabelStyle}>Artifacts</div>
            {renderArtifactLinks(artifacts)}
          </div>
          <div>
            <div style={diagnosticLabelStyle}>Log Excerpt</div>
            {detail?.log_excerpt ? (
              <pre style={{ ...preStyle, maxHeight: 180 }}>{detail.log_excerpt}</pre>
            ) : (
              <div style={emptyDiagnosticStyle}>
                No execution log was captured for this child run.
              </div>
            )}
          </div>
        </div>
      </div>
    );
  }

  function renderAutoPilotDiagnostics() {
    if (!autoPilotSessionId) return null;
    const failedPhase = autoPilotPhases.find(phase => phase.status === 'failed');
    const currentPhase = autoPilotPhases.find(phase => phase.phase_name === autoPilotSession?.current_phase)
      || failedPhase
      || autoPilotPhases.find(phase => phase.status === 'running');
    return (
      <div style={diagnosticBoxStyle}>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: '1rem', alignItems: 'flex-start', flexWrap: 'wrap' }}>
          <div>
            <h3 style={{ margin: 0, fontSize: '0.96rem' }}>AutoPilot Diagnostics</h3>
            <div style={{ color: 'var(--text-secondary)', fontSize: '0.78rem', marginTop: '0.25rem' }}>
              Session <code style={inlineCodeStyle}>{autoPilotSessionId}</code>
            </div>
          </div>
          <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', flexWrap: 'wrap' }}>
            <a href={`/autopilot?sessionId=${encodeURIComponent(autoPilotSessionId)}`} style={linkActionStyle}>
              Open AutoPilot <ExternalLink size={12} />
            </a>
            <StatusBadge status={autoPilotSession?.status || autoPilotLive?.status || 'unknown'} />
          </div>
        </div>
        {autoPilotError && <FieldError>{autoPilotError}</FieldError>}
        {autoPilotSession?.error_message && (
          <Alert variant="destructive" style={{ marginTop: '0.75rem' }}>
            <AlertTriangle size={15} />
            <AlertTitle>AutoPilot failed</AlertTitle>
            <AlertDescription>{autoPilotSession.error_message}</AlertDescription>
          </Alert>
        )}
        {currentPhase && (
          <div style={{ marginTop: '0.85rem', display: 'grid', gap: '0.45rem' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '0.75rem', flexWrap: 'wrap' }}>
              <div>
                <div style={{ fontWeight: 750 }}>
                  {AUTO_PILOT_PHASE_LABELS[currentPhase.phase_name] || pretty(currentPhase.phase_name)}
                </div>
                {currentPhase.current_step && (
                  <div style={{ color: 'var(--text-secondary)', fontSize: '0.8rem', marginTop: '0.15rem' }}>
                    {currentPhase.current_step}
                  </div>
                )}
              </div>
              <StatusBadge status={currentPhase.status} />
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
              <Progress value={progress(currentPhase.progress)} style={{ height: 6, maxWidth: 360, minWidth: 160 }} />
              <div style={{ color: 'var(--text-secondary)', fontSize: '0.76rem' }}>
                AutoPilot phase progress - {currentPhase.items_completed} / {currentPhase.items_total} items - {progress(currentPhase.progress)}%
              </div>
            </div>
            {currentPhase.error_message && <FieldError>{currentPhase.error_message}</FieldError>}
          </div>
        )}
        <div style={{ marginTop: '0.9rem', display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: '0.85rem' }}>
          <div style={liveActivityStyle}>
            <div style={{ fontWeight: 750, marginBottom: '0.4rem' }}>Live Activity</div>
            <div style={{ color: 'var(--text-secondary)', fontSize: '0.82rem', lineHeight: 1.45 }}>
              {autoPilotLive?.activity_label || autoPilotLive?.message || 'Waiting for live AutoPilot activity.'}
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: '0.45rem', marginTop: '0.75rem' }}>
              <MetricMini label="Phase" value={autoPilotLive?.phase ? AUTO_PILOT_PHASE_LABELS[autoPilotLive.phase] || pretty(autoPilotLive.phase) : '-'} />
              <MetricMini label="Tool" value={autoPilotLive?.last_tool_label || autoPilotLive?.current_stage || '-'} />
              <MetricMini label="Tool Calls" value={String(autoPilotLive?.tool_calls ?? 0)} />
              <MetricMini label="Browser Actions" value={String(autoPilotLive?.browser_tool_calls ?? autoPilotLive?.interactions ?? 0)} />
            </div>
          </div>
          {renderAutoPilotTaskDiagnostics()}
          <div style={liveActivityStyle}>
            <div style={{ fontWeight: 750, marginBottom: '0.4rem' }}>Latest Screenshot</div>
            {autoPilotLive?.latest_image?.path ? (
              <a href={`${API_BASE}${autoPilotLive.latest_image.path}`} target="_blank" rel="noreferrer" style={{ display: 'block', color: 'inherit', textDecoration: 'none' }}>
                <img
                  src={`${API_BASE}${autoPilotLive.latest_image.path}`}
                  alt="Latest AutoPilot browser screenshot"
                  style={{ width: '100%', maxHeight: 260, objectFit: 'contain', borderRadius: 8, border: '1px solid var(--border-subtle)', background: 'var(--background)' }}
                />
              </a>
            ) : (
              <div style={emptyDiagnosticStyle}>
                {autoPilotLive?.artifacts?.length
                  ? 'AutoPilot has artifacts, but no screenshot image was captured.'
                  : 'No screenshot artifact was captured for this AutoPilot session yet.'}
              </div>
            )}
          </div>
        </div>
      </div>
    );
  }

  function renderRunDetailPanel() {
    if (!selectedRunId) return null;
    if (!selectedRun && runDetailLoading) {
      return (
        <div style={runDetailPanelStyle}>
          <Loader2 size={16} className="spin" /> Loading run details...
        </div>
      );
    }
    if (!selectedRun) return null;
    const percentage = progress(selectedRun.progress);
    const diagnosticStep = selectedRunStep;
    const totalSteps = selectedRunSteps.length;
    const currentStep = selectedRunSteps.find(step => step.step_order === selectedRun.current_step_index) || diagnosticStep;
    const currentStepNumber = totalSteps
      ? Math.min(Math.max((currentStep?.step_order ?? selectedRun.current_step_index) + 1, 1), totalSteps)
      : null;
    const currentStepName = currentStep?.label || currentStep?.step_key || 'Step records pending';
    const progressDetail = totalSteps ? `Step ${currentStepNumber} of ${totalSteps} - ${currentStepName}` : 'Step records pending';
    const runStartedLabel = selectedRun.started_at ? 'Started' : 'Queued';
    const runStartedAt = selectedRun.started_at || selectedRun.created_at;
    return (
      <div style={runDetailPanelStyle}>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: '1rem', alignItems: 'flex-start', flexWrap: 'wrap' }}>
          <div style={{ minWidth: 0 }}>
            <div style={{ display: 'flex', gap: '0.55rem', alignItems: 'center', flexWrap: 'wrap' }}>
              <h3 style={{ margin: 0, fontSize: '1rem' }}>{definitionName(definitions, selectedRun)}</h3>
              <StatusBadge status={selectedRun.status} />
            </div>
            <div style={{ color: 'var(--text-secondary)', fontSize: '0.76rem', marginTop: '0.25rem', display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
              <code style={inlineCodeStyle}>{selectedRun.id}</code>
              <span>{runStartedLabel} {timeAgo(runStartedAt)}</span>
              <span>Duration {duration(selectedRun)}</span>
            </div>
          </div>
          <div style={{ display: 'flex', gap: '0.4rem', flexWrap: 'wrap' }}>
            {selectedRun.status === 'failed' && (
              <Button size="sm" variant="outline" onClick={() => retryFailedStep(selectedRun)}>
                <RotateCcw size={14} /> Retry Failed Step
              </Button>
            )}
            <Button size="sm" variant="outline" onClick={() => getRunDetail(selectedRun.id)}>
              <RefreshCw size={14} /> Refresh
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setSelectedRunId('')}>
              Close
            </Button>
          </div>
        </div>
        {selectedRun.error_message && (
          <Alert variant="destructive" style={{ marginTop: '0.85rem' }}>
            <AlertTriangle size={15} />
            <AlertTitle>Workflow failed</AlertTitle>
            <AlertDescription>{selectedRun.error_message}</AlertDescription>
          </Alert>
        )}
        <div style={{ marginTop: '0.9rem', display: 'grid', gap: '0.5rem' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', color: 'var(--text-secondary)', fontSize: '0.78rem' }}>
            <span>Workflow progress</span>
            <span>{percentage}%</span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
            <Progress value={percentage} style={{ height: 6, maxWidth: 520, minWidth: 220 }} />
            <span style={{ color: 'var(--text-secondary)', fontSize: '0.76rem' }}>{progressDetail}</span>
          </div>
        </div>
        <div style={stepTimelineStyle}>
          {selectedRunSteps.length === 0 ? (
            <div style={{ color: 'var(--text-secondary)', fontSize: '0.84rem' }}>
              No step records have been captured for this run yet.
            </div>
          ) : selectedRunSteps.map(step => {
            const selected = diagnosticStep?.id === step.id;
            const status = externalStatusFromStep(step) || step.status;
            const attention = step.status === 'failed' || attentionStatuses.includes(status);
            return (
              <button
                key={step.id}
                type="button"
                onClick={() => setSelectedRunStepId(step.id)}
                style={{
                  ...stepChipStyle,
                  borderColor: selected ? 'var(--primary)' : attention ? 'rgba(248,113,113,0.55)' : step.status === 'running' ? 'rgba(59,130,246,0.55)' : 'var(--border-subtle)',
                  background: selected ? 'var(--primary-glow)' : attention ? 'rgba(248,113,113,0.08)' : step.status === 'running' ? 'rgba(59,130,246,0.08)' : 'rgba(255,255,255,0.018)',
                }}
              >
                <span style={{ color: 'var(--text-secondary)', fontVariantNumeric: 'tabular-nums' }}>{step.step_order + 1}</span>
                <span style={{ minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{step.label || step.step_key}</span>
                <StatusBadge status={status} />
                <span style={{ color: 'var(--text-secondary)', fontSize: '0.72rem' }}>{stepDuration(step)}</span>
              </button>
            );
          })}
        </div>
        {diagnosticStep ? (
          renderStepDiagnostics(diagnosticStep)
        ) : (
          <div style={{ marginTop: '0.85rem', color: 'var(--text-secondary)', fontSize: '0.84rem' }}>
            No failed step detected. Select a running workflow to follow progress, or open the child job linked from each step when available.
          </div>
        )}
        {renderAutoPilotDiagnostics()}
      </div>
    );
  }

  function renderAnalyticsPanel() {
    if (!analytics) return null;
    const triggerEntries = Object.entries(analytics.trigger_breakdown || {});
    const flakiest = analytics.flakiest_steps || [];
    const slowest = analytics.slowest_steps || [];
    return (
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '0.75rem', marginBottom: '1rem' }}>
        <div style={liveActivityStyle}>
          <div style={{ fontWeight: 750, marginBottom: '0.5rem' }}>Trigger Mix</div>
          {triggerEntries.length === 0 ? <div style={emptyDiagnosticStyle}>No trigger data yet.</div> : triggerEntries.map(([key, value]) => (
            <MetricMini key={key} label={pretty(key)} value={String(value)} />
          ))}
        </div>
        <div style={liveActivityStyle}>
          <div style={{ fontWeight: 750, marginBottom: '0.5rem' }}>Flakiest Steps</div>
          {flakiest.length === 0 ? <div style={emptyDiagnosticStyle}>No step failures yet.</div> : flakiest.slice(0, 4).map(item => (
            <MetricMini key={item.step_type} label={pretty(item.step_type)} value={`${item.failures} failures`} />
          ))}
        </div>
        <div style={liveActivityStyle}>
          <div style={{ fontWeight: 750, marginBottom: '0.5rem' }}>Slowest Steps</div>
          {slowest.length === 0 ? <div style={emptyDiagnosticStyle}>No timing data yet.</div> : slowest.slice(0, 4).map(item => (
            <MetricMini key={item.step_type} label={pretty(item.step_type)} value={`p95 ${item.p95_duration_seconds ?? '-'}s`} />
          ))}
        </div>
      </div>
    );
  }

  function renderSchedules() {
    if (loading) return <WorkflowSkeleton />;
    return (
      <Section
        title="Workflow schedules"
        description="Recurring triggers, schedule health, and recent scheduled executions."
        action={<Button size="sm" variant="outline" onClick={() => load(false)}><RefreshCw size={14} /> Refresh</Button>}
      >
        {schedules.length === 0 ? (
          <EmptyState
            title="No workflow schedules"
            description="Create a schedule from a workflow in the library."
            icon={<Clock size={28} />}
            action={<Button onClick={() => setActiveTab('library')}>Open library</Button>}
          />
        ) : (
          <div className="workflow-stack">
            {schedules.map(schedule => {
              const definition = definitions.find(item => item.id === schedule.definition_id);
              const executions = scheduleExecutions[schedule.id] || [];
              return (
                <article key={schedule.id} className="card-elevated" style={{ padding: '1rem', display: 'grid', gap: '0.75rem' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', gap: '1rem', flexWrap: 'wrap' }}>
                    <div>
                      <h3 style={{ margin: 0, fontSize: '1rem' }}>{schedule.name}</h3>
                      <div style={{ color: 'var(--text-secondary)', fontSize: '0.78rem', marginTop: '0.25rem' }}>
                        {definition?.name || schedule.definition_id} · {schedule.cron_expression} · {schedule.timezone}
                      </div>
                    </div>
                    <div style={{ display: 'flex', gap: '0.4rem', flexWrap: 'wrap' }}>
                      <StatusBadge status={schedule.enabled ? schedule.status : 'paused'} />
                      <Button size="sm" variant="outline" onClick={() => runScheduleNow(schedule)}><Play size={14} /> Run now</Button>
                      <Button size="sm" variant="outline" onClick={() => loadScheduleExecutions(schedule.id)}><Clock size={14} /> Executions</Button>
                    </div>
                  </div>
                  <div className="workflow-meta-row">
                    <span style={workflowMetaPillStyle}>Next {schedule.next_run_at ? timeAgo(schedule.next_run_at) : '-'}</span>
                    <span style={workflowMetaPillStyle}>Last {schedule.last_run_at ? timeAgo(schedule.last_run_at) : '-'}</span>
                    <span style={workflowMetaPillStyle}>{schedule.success_rate ?? 0}% success</span>
                    <span style={workflowMetaPillStyle}>{schedule.total_executions ?? 0} executions</span>
                    <span style={workflowMetaPillStyle}>pinned {schedule.revision_id ? 'revision' : 'latest'}</span>
                  </div>
                  {schedule.last_error && <FieldError>{schedule.last_error}</FieldError>}
                  {executions.length > 0 && (
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>Status</TableHead>
                          <TableHead>Trigger</TableHead>
                          <TableHead>Run</TableHead>
                          <TableHead>Duration</TableHead>
                          <TableHead>Created</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {executions.slice(0, 5).map(execution => (
                          <TableRow key={execution.id}>
                            <TableCell><StatusBadge status={execution.status} /></TableCell>
                            <TableCell>{pretty(execution.trigger_type)}</TableCell>
                            <TableCell>
                              {execution.workflow_run_id ? (
                                <Button size="sm" variant="ghost" onClick={() => openRunDetails(String(execution.workflow_run_id))}>
                                  <Eye size={14} /> Open
                                </Button>
                              ) : '-'}
                            </TableCell>
                            <TableCell>{execution.duration_seconds ? `${execution.duration_seconds}s` : '-'}</TableCell>
                            <TableCell>{timeAgo(execution.created_at)}</TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  )}
                </article>
              );
            })}
          </div>
        )}
      </Section>
    );
  }

  function renderNotifications() {
    return (
      <Section
        title="Workflow notifications"
        description={`${unreadNotifications} unread workflow notification${unreadNotifications === 1 ? '' : 's'}`}
        action={<Button size="sm" variant="outline" onClick={() => load(false)}><RefreshCw size={14} /> Refresh</Button>}
      >
        {notifications.length === 0 ? (
          <EmptyState title="No workflow notifications" description="Completion, failure, and review alerts will appear here." icon={<Bell size={28} />} />
        ) : (
          <div className="workflow-stack">
            {notifications.map(notification => (
              <article key={notification.id} className="card-elevated" style={{ padding: '1rem', display: 'grid', gap: '0.5rem', borderColor: notification.read_at ? 'var(--border-subtle)' : 'var(--primary)' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: '1rem', flexWrap: 'wrap' }}>
                  <div>
                    <h3 style={{ margin: 0, fontSize: '0.95rem' }}>{notification.title}</h3>
                    <div style={{ color: 'var(--text-secondary)', fontSize: '0.78rem', marginTop: '0.25rem' }}>{timeAgo(notification.created_at)}</div>
                  </div>
                  {!notification.read_at && (
                    <Button size="sm" variant="outline" onClick={() => markNotificationRead(notification.id)}>
                      <CheckCircle2 size={14} /> Mark read
                    </Button>
                  )}
                </div>
                <div style={{ color: 'var(--text-secondary)', fontSize: '0.84rem', lineHeight: 1.45 }}>{notification.body}</div>
              </article>
            ))}
          </div>
        )}
      </Section>
    );
  }

  function renderRuns() {
    if (loading) return <WorkflowSkeleton />;
    return (
      <Section
        title="Recent runs"
        description={`${activeRuns.length} active workflow${activeRuns.length === 1 ? '' : 's'}`}
        action={
          <div className="workflow-run-filters">
            {(['active', 'failed', 'completed', 'all'] as RunFilter[]).map(filter => (
              <Button
                key={filter}
                size="sm"
                variant="outline"
                onClick={() => setRunFilter(filter)}
                style={runFilter === filter ? workflowFilterActiveStyle : workflowFilterStyle}
              >
                {pretty(filter)}
              </Button>
            ))}
          </div>
        }
      >
        {renderAnalyticsPanel()}
        {renderRunDetailPanel()}
        {runs.length === 0 ? (
          <EmptyState
            title="No workflow runs yet"
            description="Run a workflow from the library to monitor execution progress here."
            icon={<Play size={28} />}
            action={<Button onClick={() => setActiveTab('library')}>Open library</Button>}
          />
        ) : filteredRuns.length === 0 ? (
          <div style={{ padding: '2rem', textAlign: 'center', color: 'var(--text-secondary)' }}>
            No runs match the current filter.
          </div>
        ) : (
          <Table className="workflow-runs-table">
            <TableHeader>
              <TableRow>
                <TableHead>Workflow</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Progress</TableHead>
                <TableHead>Current step</TableHead>
                <TableHead>Duration</TableHead>
                <TableHead>Created</TableHead>
                <TableHead style={{ textAlign: 'right' }}>Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filteredRuns.slice(0, 20).map(run => {
                const percentage = progress(run.progress);
                const definition = definitions.find(item => item.id === run.definition_id);
                const currentStep = run.steps?.[run.current_step_index];
                const definitionStep = definition?.steps?.[run.current_step_index];
                return (
                  <TableRow key={run.id}>
                    <TableCell>
                      <div style={{ fontWeight: 600 }}>{definitionName(definitions, run)}</div>
                      <div style={{ color: 'var(--text-secondary)', fontSize: '0.72rem', fontFamily: 'monospace', marginTop: '0.2rem' }}>{run.id}</div>
                      {run.error_message && <FieldError>{run.error_message}</FieldError>}
                    </TableCell>
                    <TableCell><StatusBadge status={run.status} /></TableCell>
                    <TableCell style={{ minWidth: 150 }}>
                      <Progress value={percentage} style={{ height: 8 }} />
                      <div style={{ color: 'var(--text-secondary)', fontSize: '0.75rem', marginTop: '0.35rem' }}>{percentage}%</div>
                    </TableCell>
                    <TableCell>{currentStep?.label || currentStep?.step_key || definitionStep?.label || definitionStep?.key || '-'}</TableCell>
                    <TableCell>{duration(run)}</TableCell>
                    <TableCell>{timeAgo(run.created_at)}</TableCell>
                    <TableCell>
                      <div className="workflow-run-actions">
                        <Button
                          className="workflow-run-details-button"
                          size="sm"
                          variant={selectedRunId === run.id ? 'default' : 'outline'}
                          title="View workflow run details"
                          aria-label="View workflow run details"
                          onClick={() => openRunDetails(run.id)}
                        >
                          <Eye size={14} /> Details
                        </Button>
                        {run.status === 'paused' || run.status === 'awaiting_input' ? (
                          <Button size="icon" variant="outline" title="Resume workflow" aria-label="Resume workflow" onClick={() => controlRun(run.id, 'resume')}><Play size={14} /></Button>
                        ) : ['queued', 'running'].includes(run.status) ? (
                          <Button size="icon" variant="outline" title="Pause workflow" aria-label="Pause workflow" onClick={() => controlRun(run.id, 'pause')}><Pause size={14} /></Button>
                        ) : null}
                        {!terminalStatuses.includes(run.status) && (
                          <Button size="icon" variant="outline" title="Cancel workflow" aria-label="Cancel workflow" onClick={() => controlRun(run.id, 'cancel')}><Square size={14} /></Button>
                        )}
                        {run.status === 'failed' && (
                          <Button size="icon" variant="outline" title="Retry failed step" aria-label="Retry failed step" onClick={() => retryFailedStep(run)}><RotateCcw size={14} /></Button>
                        )}
                      </div>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        )}
      </Section>
    );
  }

  function renderScheduleDialog() {
    const definition = scheduleDialogDefinition;
    if (!definition) return null;
    return (
      <div style={modalBackdropStyle} role="dialog" aria-modal="true" aria-label="Schedule workflow">
        <div style={modalPanelStyle}>
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: '1rem', alignItems: 'flex-start' }}>
            <div>
              <h2 style={{ margin: 0, fontSize: '1.05rem' }}>Schedule workflow</h2>
              <div style={{ color: 'var(--text-secondary)', fontSize: '0.82rem', marginTop: '0.25rem' }}>{definition.name}</div>
            </div>
            <Button size="icon" variant="ghost" onClick={() => setScheduleDialogDefinition(null)} aria-label="Close schedule dialog"><X size={16} /></Button>
          </div>
          <div className="workflow-step-fields-grid" style={{ marginTop: '1rem' }}>
            <div>
              <Label>Name</Label>
              <Input value={scheduleForm.name} onChange={event => setScheduleForm(prev => ({ ...prev, name: event.target.value }))} />
            </div>
            <div>
              <Label>Cron</Label>
              <Input value={scheduleForm.cron_expression} onChange={event => setScheduleForm(prev => ({ ...prev, cron_expression: event.target.value }))} />
            </div>
            <div>
              <Label>Timezone</Label>
              <Input value={scheduleForm.timezone} onChange={event => setScheduleForm(prev => ({ ...prev, timezone: event.target.value }))} />
            </div>
            <div>
              <Label>Start step</Label>
              <Select value={scheduleForm.start_step_key || '__first__'} onValueChange={value => setScheduleForm(prev => ({ ...prev, start_step_key: value === '__first__' ? '' : value }))}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="__first__">First step</SelectItem>
                  {(definition.steps || []).map(step => (
                    <SelectItem key={step.key} value={step.key}>{step.label || step.key}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
          <div style={{ marginTop: '0.75rem' }}>
            <Label>Description</Label>
            <textarea
              value={scheduleForm.description}
              onChange={(event: ChangeEvent<HTMLTextAreaElement>) => setScheduleForm(prev => ({ ...prev, description: event.target.value }))}
              rows={2}
              style={textareaStyle}
            />
          </div>
          <div style={{ display: 'grid', gap: '0.5rem', marginTop: '0.85rem' }}>
            {([
              ['enabled', 'Enabled'],
              ['notify_on_completion', 'Notify on completion'],
              ['notify_on_failure', 'Notify on failure'],
              ['notify_on_review_needed', 'Notify when review is needed'],
            ] as const).map(([key, label]) => (
              <div key={key} style={scheduleForm[key] ? { ...switchRowStyle, ...switchRowActiveStyle } : switchRowStyle}>
                <Switch
                  checked={Boolean(scheduleForm[key])}
                  onCheckedChange={checked => setScheduleForm(prev => ({ ...prev, [key]: checked }))}
                />
                <span style={switchLabelStyle}>{label}</span>
              </div>
            ))}
          </div>
          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.5rem', marginTop: '1rem' }}>
            <Button variant="ghost" onClick={() => setScheduleDialogDefinition(null)}>Cancel</Button>
            <Button onClick={() => void submitSchedule()}><Clock size={14} /> Create schedule</Button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <PageLayout tier="wide" className="workflow-page">
      <PageHeader
        className="workflow-page-header"
        title="Custom Workflows"
        subtitle="Create guided automation sequences and monitor reusable runs from one workspace."
        icon={<Workflow size={20} />}
        actions={
          <>
            <Button onClick={() => load(false)} variant="outline"><RefreshCw size={15} /> Refresh</Button>
            <Button onClick={() => setActiveTab('templates')} variant="outline"><Sparkles size={15} /> Templates</Button>
            <Button onClick={() => importInputRef.current?.click()} variant="outline"><FileText size={15} /> Import JSON</Button>
            <Button onClick={() => resetBuilder()}><Plus size={15} /> New workflow</Button>
          </>
        }
      />
      <input
        ref={importInputRef}
        type="file"
        accept="application/json,.json"
        style={{ display: 'none' }}
        onChange={event => void importWorkflowFile(event.target.files?.[0] || null)}
      />

      {error && (
        <Alert variant="destructive" style={{ marginBottom: '1rem' }}>
          <AlertTriangle size={16} />
          <AlertTitle>Workflow data unavailable</AlertTitle>
          <AlertDescription style={{ display: 'flex', justifyContent: 'space-between', gap: '1rem', alignItems: 'center', flexWrap: 'wrap' }}>
            <span>{error}</span>
            <Button size="sm" variant="outline" onClick={() => load(true)}>Retry</Button>
          </AlertDescription>
        </Alert>
      )}

      {analytics && (
        <div className="workflow-meta-row" style={{ marginBottom: '1rem', gap: '0.5rem', flexWrap: 'wrap' }}>
          <span style={workflowMetaPillStyle}>{analytics.active_runs ?? 0} active runs</span>
          <span style={workflowMetaPillStyle}>{analytics.failed_runs ?? 0} failed runs</span>
          <span style={workflowMetaPillStyle}>{analytics.completed_runs ?? 0} completed runs</span>
          <span style={workflowMetaPillStyle}>{analytics.success_rate ?? 0}% success</span>
          <span style={workflowMetaPillStyle}>p95 {analytics.duration_seconds?.p95 ?? '-'}s</span>
        </div>
      )}

      <div className="workflow-tabs">
        {([
          ['templates', `Templates (${workflowTemplates.length})`],
          ['library', `Library (${definitions.length})`],
          ['builder', selectedDefinitionId ? 'Builder: edit' : 'Builder'],
          ['runs', `Runs (${activeRuns.length} active)`],
          ['schedules', `Schedules (${schedules.length})`],
          ['notifications', `Alerts (${unreadNotifications})`],
        ] as const).map(([tab, label]) => (
          <button key={tab} onClick={() => setActiveTab(tab)} style={createWorkflowTabStyle(activeTab, tab)}>
            {label}
          </button>
        ))}
      </div>

      {activeTab === 'templates' && (
        <Section
          title="Workflow templates"
          description="Use templates for common end-to-end paths; use the manual step catalog for custom chains."
          action={<Button size="sm" variant="outline" onClick={() => resetBuilder()}><Plus size={14} /> Blank workflow</Button>}
        >
          {renderTemplates()}
        </Section>
      )}
      {activeTab === 'library' && (
        <Section
          title="Workflow library"
          description="Run saved workflows or open one in the guided builder."
          action={<Button size="sm" variant="outline" onClick={() => resetBuilder()}><Plus size={14} /> Create</Button>}
        >
          {renderLibrary()}
        </Section>
      )}
      {activeTab === 'builder' && renderBuilder()}
      {activeTab === 'runs' && renderRuns()}
      {activeTab === 'schedules' && renderSchedules()}
      {activeTab === 'notifications' && renderNotifications()}
      {renderTokenBrowser()}
      {renderScheduleDialog()}
    </PageLayout>
  );
}

function MetricMini({ label, value }: { label: string; value: string }) {
  return (
    <div style={metricMiniStyle}>
      <div style={{ color: 'var(--text-secondary)', fontSize: '0.68rem', textTransform: 'uppercase', letterSpacing: '0.04em' }}>{label}</div>
      <div style={{ color: 'var(--text)', fontSize: '0.78rem', fontWeight: 750, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{value}</div>
    </div>
  );
}

const runDetailPanelStyle: React.CSSProperties = {
  border: '1px solid var(--border)',
  borderRadius: 10,
  background: 'rgba(255,255,255,0.018)',
  padding: '1rem',
  marginBottom: '1rem',
  display: 'grid',
  gap: '0.85rem',
};

const stepTimelineStyle: React.CSSProperties = {
  display: 'grid',
  gridTemplateColumns: 'repeat(auto-fit, minmax(210px, 1fr))',
  gap: '0.55rem',
  marginTop: '0.85rem',
};

const stepChipStyle: React.CSSProperties = {
  display: 'grid',
  gridTemplateColumns: '24px minmax(0, 1fr) auto auto',
  alignItems: 'center',
  gap: '0.5rem',
  minHeight: 40,
  border: '1px solid var(--border-subtle)',
  borderRadius: 10,
  padding: '0.45rem 0.65rem',
  color: 'var(--text)',
  textAlign: 'left',
  cursor: 'pointer',
};

const diagnosticBoxStyle: React.CSSProperties = {
  border: '1px solid var(--border-subtle)',
  borderRadius: 10,
  background: 'var(--background)',
  padding: '1rem',
};

const detailDisclosureStyle: React.CSSProperties = {
  border: '1px solid var(--border-subtle)',
  borderRadius: 10,
  padding: '0.65rem 0.75rem',
  background: 'rgba(255,255,255,0.015)',
  minWidth: 0,
};

const summaryStyle: React.CSSProperties = {
  cursor: 'pointer',
  color: 'var(--text-secondary)',
  fontSize: '0.78rem',
  fontWeight: 750,
};

const preStyle: React.CSSProperties = {
  margin: '0.6rem 0 0',
  maxHeight: 260,
  overflow: 'auto',
  whiteSpace: 'pre-wrap',
  wordBreak: 'break-word',
  color: 'var(--text-secondary)',
  fontSize: '0.74rem',
  lineHeight: 1.5,
};

const inlineCodeStyle: React.CSSProperties = {
  color: 'var(--text)',
  background: 'rgba(255,255,255,0.04)',
  border: '1px solid var(--border-subtle)',
  borderRadius: 6,
  padding: '0.12rem 0.35rem',
  fontSize: '0.72rem',
};

const linkActionStyle: React.CSSProperties = {
  display: 'inline-flex',
  alignItems: 'center',
  gap: '0.25rem',
  color: 'var(--primary)',
  textDecoration: 'none',
  fontWeight: 750,
};

const liveActivityStyle: React.CSSProperties = {
  border: '1px solid var(--border-subtle)',
  borderRadius: 10,
  background: 'rgba(255,255,255,0.014)',
  padding: '1rem',
  minWidth: 0,
};

const metricMiniStyle: React.CSSProperties = {
  border: '1px solid var(--border-subtle)',
  borderRadius: 10,
  padding: '0.5rem',
  minWidth: 0,
};

const libraryControlsStyle: React.CSSProperties = {
  display: 'flex',
  gap: '0.65rem',
  alignItems: 'center',
  flexWrap: 'wrap',
};

const diagnosticLabelStyle: React.CSSProperties = {
  color: 'var(--text-secondary)',
  fontSize: '0.72rem',
  fontWeight: 750,
  textTransform: 'uppercase',
  letterSpacing: '0.04em',
  marginBottom: '0.35rem',
};

const emptyDiagnosticStyle: React.CSSProperties = {
  color: 'var(--text-secondary)',
  fontSize: '0.82rem',
  lineHeight: 1.45,
};

const artifactLinkStyle: React.CSSProperties = {
  display: 'inline-flex',
  alignItems: 'center',
  border: '1px solid var(--border-subtle)',
  borderRadius: 8,
  padding: '0.32rem 0.5rem',
  color: 'var(--primary)',
  textDecoration: 'none',
  fontSize: '0.76rem',
  fontWeight: 750,
  maxWidth: '100%',
  overflowWrap: 'anywhere',
};

const tokenBrowserOverlayStyle: React.CSSProperties = {
  position: 'fixed',
  inset: 0,
  zIndex: 1200,
  background: 'rgba(0,0,0,0.48)',
  display: 'grid',
  placeItems: 'center',
  padding: 16,
};

const tokenBrowserPanelStyle: React.CSSProperties = {
  width: 'min(760px, 100%)',
  maxHeight: 'min(720px, calc(100vh - 32px))',
  overflow: 'hidden',
  border: '1px solid var(--border)',
  borderRadius: 10,
  background: 'var(--background-raised)',
  boxShadow: '0 24px 70px rgba(0,0,0,0.48)',
  padding: '1rem',
  display: 'grid',
  gap: '0.85rem',
};

const modalBackdropStyle: React.CSSProperties = {
  position: 'fixed',
  inset: 0,
  zIndex: 1300,
  background: 'rgba(0,0,0,0.52)',
  display: 'grid',
  placeItems: 'center',
  padding: 16,
};

const modalPanelStyle: React.CSSProperties = {
  width: 'min(720px, 100%)',
  maxHeight: 'min(760px, calc(100vh - 32px))',
  overflow: 'auto',
  border: '1px solid var(--border)',
  borderRadius: 10,
  background: 'var(--background-raised)',
  boxShadow: '0 24px 70px rgba(0,0,0,0.48)',
  padding: '1rem',
};

const tokenOptionStyle: React.CSSProperties = {
  display: 'grid',
  gap: '0.35rem',
  textAlign: 'left',
  border: '1px solid var(--border-subtle)',
  borderRadius: 8,
  padding: '0.65rem',
  background: 'rgba(255,255,255,0.018)',
  color: 'var(--text)',
  cursor: 'pointer',
};

const textareaStyle: React.CSSProperties = {
  width: '100%',
  border: '1px solid var(--border-subtle)',
  borderRadius: 10,
  padding: '10px 12px',
  background: 'var(--background)',
  color: 'var(--text)',
  resize: 'vertical',
  lineHeight: 1.5,
};

const switchRowStyle: React.CSSProperties = {
  display: 'inline-flex',
  alignItems: 'center',
  gap: '0.55rem',
  color: 'var(--text-secondary)',
  fontSize: '0.82rem',
  width: 'fit-content',
  minHeight: 34,
  padding: '0.2rem 0.45rem 0.2rem 0',
  borderRadius: 8,
  transition: 'color 0.2s var(--ease-smooth), background 0.2s var(--ease-smooth)',
};

const switchRowActiveStyle: React.CSSProperties = {
  color: 'var(--text)',
};

const switchLabelStyle: React.CSSProperties = {
  cursor: 'pointer',
  lineHeight: 1.35,
};
