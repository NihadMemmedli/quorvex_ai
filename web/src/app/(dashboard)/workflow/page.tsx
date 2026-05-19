'use client';

import { type ChangeEvent, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  AlertTriangle,
  Archive,
  ArrowDown,
  ArrowUp,
  CheckCircle2,
  ChevronDown,
  CircleDot,
  Copy,
  Edit3,
  ExternalLink,
  Eye,
  FileText,
  ListStart,
  Loader2,
  Pause,
  Play,
  Plus,
  RefreshCw,
  RotateCcw,
  Sparkles,
  Square,
  Trash2,
  Workflow,
} from 'lucide-react';
import { toast } from 'sonner';
import { API_BASE } from '@/lib/api';
import { useProject } from '@/contexts/ProjectContext';
import { timeAgo } from '@/lib/formatting';
import { createTabStyle } from '@/lib/styles';
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
import { ConfirmDialog } from '@/components/ui/confirm-dialog';
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

type WorkflowTab = 'templates' | 'library' | 'builder' | 'runs';
type RunFilter = 'active' | 'failed' | 'completed' | 'all';

interface WorkflowDefinition {
  id: string;
  name: string;
  description: string;
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
}

interface WorkflowRun {
  id: string;
  definition_id: string;
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
  output?: Record<string, unknown> | null;
  external_kind?: string | null;
  external_id?: string | null;
  error_message?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  updated_at?: string | null;
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
  current_stage?: string | null;
  last_tool_label?: string | null;
  tool_calls: number;
  browser_tool_calls: number;
  interactions: number;
  recent_tools: string[];
  latest_image: AutoPilotLiveArtifact | null;
  updated_at?: string | null;
}

interface CatalogStep {
  type: string;
  label: string;
  description: string;
  required: string[];
}

interface ValidationResult {
  form?: string;
  steps: Record<number, string[]>;
}

interface WorkflowTemplate {
  id: string;
  name: string;
  description: string;
  useCase: string;
  steps: WorkflowStep[];
}

const activeStatuses = ['queued', 'running', 'awaiting_input', 'paused'];
const terminalStatuses = ['completed', 'failed', 'cancelled'];
const attentionStatuses = ['failed', 'error', 'timeout', 'cancelled'];

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

function duration(run: WorkflowRun) {
  const start = new Date(run.created_at).getTime();
  const end = terminalStatuses.includes(run.status) ? new Date(run.updated_at).getTime() : Date.now();
  if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) return '-';
  const seconds = Math.floor((end - start) / 1000);
  if (seconds < 60) return `${seconds}s`;
  return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
}

function stepDuration(step: WorkflowRunStep) {
  if (!step.started_at) return '-';
  const start = new Date(step.started_at).getTime();
  const end = step.completed_at ? new Date(step.completed_at).getTime() : Date.now();
  if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) return '-';
  const seconds = Math.floor((end - start) / 1000);
  if (seconds < 60) return `${seconds}s`;
  return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
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
  if (kind === 'test_run') return `/runs/${encodeURIComponent(id)}`;
  if (kind === 'regression_batch') return `/regression/batches/${encodeURIComponent(id)}`;
  return null;
}

function defaultInputFor(type: string): Record<string, unknown> {
  if (type === 'start_autopilot') return { entry_urls: ['https://example.com'], max_interactions: 30, max_specs: 10 };
  if (type === 'start_exploration') return { entry_url: 'https://example.com', max_interactions: 30 };
  if (type === 'generate_requirements') return { exploration_session_id: '{{steps.explore.external_id}}' };
  if (type === 'generate_specs_from_requirements') return { target_url: 'https://example.com' };
  if (type === 'run_spec') return { spec_name: 'examples/hello-world.md' };
  if (type === 'run_regression_batch') return { browser: 'chromium', automated_only: true };
  if (type === 'start_custom_agent') return { definition_id: '', prompt: 'Inspect the target and report findings.' };
  if (type === 'wait_for_status') return { source_step: 'autopilot', timeout_seconds: 3600, poll_seconds: 10 };
  if (type === 'review_gate') return { question: 'Review the current workflow state before continuing.' };
  return {};
}

function defaultLabelFor(type: string, catalog: CatalogStep[]) {
  return catalog.find(item => item.type === type)?.label || pretty(type);
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

function newAutopilotWorkflow(): WorkflowStep[] {
  return [
    { key: 'autopilot', type: 'start_autopilot', label: 'Run AutoPilot', input: defaultInputFor('start_autopilot') },
    { key: 'wait_autopilot', type: 'wait_for_status', label: 'Wait for AutoPilot', input: { source_step: 'autopilot', timeout_seconds: 7200, poll_seconds: 15 } },
    { key: 'review', type: 'review_gate', label: 'Review Results', input: defaultInputFor('review_gate') },
  ];
}

const WORKFLOW_TEMPLATES: WorkflowTemplate[] = [
  {
    id: 'autopilot-smoke-review',
    name: 'AutoPilot Smoke Review',
    description: 'Explore a target URL, generate candidate specs, then pause for human review.',
    useCase: 'Fast application smoke coverage',
    steps: newAutopilotWorkflow(),
  },
  {
    id: 'explore-to-requirements',
    name: 'Explore To Requirements',
    description: 'Run exploration, wait for completion, generate requirements, then review the generated coverage.',
    useCase: 'Discovery into requirements',
    steps: [
      { key: 'explore', type: 'start_exploration', label: 'Explore Application', input: defaultInputFor('start_exploration') },
      { key: 'wait_explore', type: 'wait_for_status', label: 'Wait for Exploration', input: { source_step: 'explore', timeout_seconds: 3600, poll_seconds: 10 } },
      { key: 'requirements', type: 'generate_requirements', label: 'Generate Requirements', input: { exploration_session_id: '{{steps.explore.external_id}}' } },
      { key: 'wait_requirements', type: 'wait_for_status', label: 'Wait for Requirements', input: { source_step: 'requirements', timeout_seconds: 1800, poll_seconds: 10 } },
      { key: 'review', type: 'review_gate', label: 'Review Requirements', input: { question: 'Review the generated requirements before generating specs.', suggested_answers: ['Continue', 'Revise requirements'] } },
    ],
  },
  {
    id: 'requirements-to-specs',
    name: 'Requirements To Specs',
    description: 'Generate specs for uncovered requirements, wait for the job, then review the result.',
    useCase: 'Turn requirements into test specs',
    steps: [
      { key: 'bulk_specs', type: 'generate_specs_from_requirements', label: 'Generate Specs', input: defaultInputFor('generate_specs_from_requirements') },
      { key: 'wait_specs', type: 'wait_for_status', label: 'Wait for Spec Generation', input: { source_step: 'bulk_specs', timeout_seconds: 3600, poll_seconds: 10 } },
      { key: 'review', type: 'review_gate', label: 'Review Generated Specs', input: { question: 'Review the generated specs before running them.', suggested_answers: ['Run regression', 'Edit specs first'] } },
    ],
  },
  {
    id: 'single-spec-smoke',
    name: 'Single Spec Smoke Run',
    description: 'Run one saved spec, wait for the test run, then review the outcome.',
    useCase: 'Validate a focused flow',
    steps: [
      { key: 'spec_run', type: 'run_spec', label: 'Run Spec', input: defaultInputFor('run_spec') },
      { key: 'wait_spec_run', type: 'wait_for_status', label: 'Wait for Spec Run', input: { source_step: 'spec_run', timeout_seconds: 1800, poll_seconds: 10 } },
      { key: 'review', type: 'review_gate', label: 'Review Run Result', input: { question: 'Review the spec run result before continuing.', suggested_answers: ['Accept', 'Retry after edits'] } },
    ],
  },
  {
    id: 'regression-review',
    name: 'Regression Batch Review',
    description: 'Run an automated regression batch and pause when the batch status is available.',
    useCase: 'Reusable release regression',
    steps: [
      { key: 'regression', type: 'run_regression_batch', label: 'Run Regression Batch', input: defaultInputFor('run_regression_batch') },
      { key: 'wait_regression', type: 'wait_for_status', label: 'Wait for Regression', input: { source_step: 'regression', timeout_seconds: 7200, poll_seconds: 15 } },
      { key: 'review', type: 'review_gate', label: 'Review Regression', input: { question: 'Review the regression result before release decisions.', suggested_answers: ['Release', 'Investigate failures'] } },
    ],
  },
];

function createEmptyValidation(): ValidationResult {
  return { steps: {} };
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

function hasInputValue(input: Record<string, unknown>, key: string) {
  const value = input[key];
  if (Array.isArray(value)) return value.length > 0;
  if (typeof value === 'string') return value.trim().length > 0;
  return value !== undefined && value !== null && value !== '';
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
    <section className="card-elevated" style={{ padding: 0, overflow: 'hidden' }}>
      <div
        style={{
          padding: '1rem 1.15rem',
          borderBottom: '1px solid var(--border-subtle)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: '1rem',
        }}
      >
        <div>
          <h2 style={{ fontSize: '1rem', fontWeight: 700, margin: 0 }}>{title}</h2>
          {description && (
            <p style={{ margin: '0.25rem 0 0', color: 'var(--text-secondary)', fontSize: '0.82rem' }}>
              {description}
            </p>
          )}
        </div>
        {action}
      </div>
      <div style={{ padding: '1rem 1.15rem' }}>{children}</div>
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
  minHeight: 24,
  border: '1px solid var(--border-subtle)',
  borderRadius: 999,
  padding: '0.18rem 0.55rem',
  background: 'rgba(255,255,255,0.02)',
};

const workflowIconButtonStyle: React.CSSProperties = {
  width: 34,
  height: 34,
  flexShrink: 0,
};

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
  const [catalog, setCatalog] = useState<CatalogStep[]>([]);
  const [selectedDefinitionId, setSelectedDefinitionId] = useState('');
  const [activeTab, setActiveTab] = useState<WorkflowTab>('library');
  const [runFilter, setRunFilter] = useState<RunFilter>('active');
  const [name, setName] = useState('Smoke workflow');
  const [description, setDescription] = useState('Reusable workflow created from the UI.');
  const [steps, setSteps] = useState<WorkflowStep[]>(newAutopilotWorkflow());
  const [advancedOpen, setAdvancedOpen] = useState<Record<number, boolean>>({});
  const [jsonDrafts, setJsonDrafts] = useState<Record<number, string>>({});
  const [jsonErrors, setJsonErrors] = useState<Record<number, string>>({});
  const [validation, setValidation] = useState<ValidationResult>(createEmptyValidation());
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [catalogError, setCatalogError] = useState<string | null>(null);
  const [archiveTarget, setArchiveTarget] = useState<WorkflowDefinition | null>(null);
  const [runStepsById, setRunStepsById] = useState<Record<string, WorkflowRunStep[]>>({});
  const [selectedRunId, setSelectedRunId] = useState('');
  const [selectedRunStepId, setSelectedRunStepId] = useState<number | null>(null);
  const [selectedRunDetails, setSelectedRunDetails] = useState<WorkflowRun | null>(null);
  const [runDetailLoading, setRunDetailLoading] = useState(false);
  const [autoPilotSession, setAutoPilotSession] = useState<AutoPilotSessionSummary | null>(null);
  const [autoPilotPhases, setAutoPilotPhases] = useState<AutoPilotPhase[]>([]);
  const [autoPilotLive, setAutoPilotLive] = useState<AutoPilotLiveState | null>(null);
  const [autoPilotError, setAutoPilotError] = useState<string | null>(null);
  const urlStateReady = useRef(false);

  const projectParam = useMemo(
    () => currentProject?.id ? `?project_id=${encodeURIComponent(currentProject.id)}` : '',
    [currentProject?.id],
  );

  const activeRuns = useMemo(() => runs.filter(run => activeStatuses.includes(run.status)), [runs]);

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

  const load = useCallback(async (initial = false) => {
    setError(null);
    setCatalogError(null);
    if (initial) setLoading(true);

    const [defsResult, runsResult, catalogResult] = await Promise.allSettled([
      fetch(`${API_BASE}/workflows/definitions${projectParam}`),
      fetch(`${API_BASE}/workflows/runs${projectParam}`),
      fetch(`${API_BASE}/workflows/catalog`),
    ]);

    if (defsResult.status !== 'fulfilled' || !defsResult.value.ok) {
      throw new Error('Failed to load workflow definitions');
    }
    if (runsResult.status !== 'fulfilled' || !runsResult.value.ok) {
      throw new Error('Failed to load workflow runs');
    }

    setDefinitions(await defsResult.value.json());
    setRuns(await runsResult.value.json());

    if (catalogResult.status === 'fulfilled' && catalogResult.value.ok) {
      const catalogData = await catalogResult.value.json();
      setCatalog(Array.isArray(catalogData.steps) ? catalogData.steps : []);
    } else {
      setCatalog([]);
      setCatalogError('Step catalog is unavailable. Existing workflows and runs can still be used.');
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

  const loadAutoPilotDiagnostics = useCallback(async (sessionId: string, quiet = true) => {
    if (!quiet) setAutoPilotError(null);
    try {
      const [sessionResult, phasesResult, liveResult] = await Promise.allSettled([
        fetch(`${API_BASE}/autopilot/${encodeURIComponent(sessionId)}`),
        fetch(`${API_BASE}/autopilot/${encodeURIComponent(sessionId)}/phases`),
        fetch(`${API_BASE}/autopilot/${encodeURIComponent(sessionId)}/live`),
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
    } catch (err) {
      setAutoPilotError(err instanceof Error ? err.message : 'Failed to load AutoPilot diagnostics');
      setAutoPilotSession(null);
      setAutoPilotPhases([]);
      setAutoPilotLive(null);
    }
  }, []);

  useEffect(() => {
    if (!autoPilotSessionId) {
      setAutoPilotSession(null);
      setAutoPilotPhases([]);
      setAutoPilotLive(null);
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

  function resetBuilder(nextSteps = newAutopilotWorkflow(), metadata?: { name?: string; description?: string }) {
    setSelectedDefinitionId('');
    setName(metadata?.name || 'Smoke workflow');
    setDescription(metadata?.description || 'Reusable workflow created from the UI.');
    setSteps(cloneWorkflowSteps(nextSteps));
    setAdvancedOpen({});
    setJsonDrafts({});
    setJsonErrors({});
    setValidation(createEmptyValidation());
    setActiveTab('builder');
  }

  function applyTemplate(template: WorkflowTemplate) {
    resetBuilder(template.steps, {
      name: template.name,
      description: template.description,
    });
  }

  function selectDefinition(definition: WorkflowDefinition) {
    setSelectedDefinitionId(definition.id);
    setName(definition.name);
    setDescription(definition.description || '');
    setSteps(definition.steps || []);
    setAdvancedOpen({});
    setJsonDrafts({});
    setJsonErrors({});
    setValidation(createEmptyValidation());
    setActiveTab('builder');
  }

  function updateStep(index: number, patch: Partial<WorkflowStep>) {
    setSteps(prev => prev.map((step, i) => i === index ? { ...step, ...patch } : step));
    setValidation(createEmptyValidation());
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

  function addStep(type = 'review_gate') {
    setSteps(prev => [
      ...prev,
      {
        key: `${type.replace(/^start_/, '').replace(/_for_status$/, '')}_${prev.length + 1}`,
        type,
        label: defaultLabelFor(type, catalog),
        input: defaultInputFor(type),
      },
    ]);
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
    setSteps(prev => prev.filter((_, i) => i !== index));
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
      if (missingRequired.length > 0) errors.push(`Missing required input: ${missingRequired.join(', ')}.`);
      if (step.type === 'wait_for_status') {
        const sourceStep = inputString(step.input || {}, 'source_step');
        if (!sourceStep) errors.push('Choose a source step to wait for.');
        if (sourceStep && !steps.some((candidate, candidateIndex) => candidateIndex !== index && candidate.key === sourceStep)) {
          errors.push('Source step must reference another existing step.');
        }
      }
      if (step.type === 'start_autopilot' && !inputList(step.input || {}, 'entry_urls').trim()) {
        errors.push('Add at least one entry URL.');
      }
      if (errors.length) result.steps[index] = errors;
    });

    setValidation(result);
    return !result.form && Object.keys(result.steps).length === 0;
  }

  async function saveDefinition() {
    if (!validateWorkflow()) return;
    setSaving(true);
    setError(null);
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

  async function controlRun(runId: string, action: 'pause' | 'resume' | 'cancel') {
    const res = await fetch(`${API_BASE}/workflows/runs/${encodeURIComponent(runId)}/${action}`, { method: 'POST' });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      setError(data.detail || data.error || `Failed to ${action} workflow`);
      return;
    }
    await load(false);
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
    await load(false);
    toast.success('Workflow archived');
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
      toast.success('Failed step queued for retry');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to retry workflow step');
    }
  }

  function tokenOptionsFor(index: number, kinds?: string[]) {
    return steps
      .slice(0, index)
      .filter(step => !kinds || kinds.includes(step.type))
      .map(step => ({
        label: `${step.key} external id`,
        value: `{{steps.${step.key}.external_id}}`,
      }));
  }

  function renderTokenButtons(index: number, inputKey: string, options = tokenOptionsFor(index)) {
    if (options.length === 0) return null;
    return (
      <div style={{ display: 'flex', gap: '0.35rem', flexWrap: 'wrap', marginTop: '0.4rem' }}>
        {options.map(option => (
          <Button
            key={`${inputKey}-${option.value}`}
            type="button"
            size="sm"
            variant="outline"
            onClick={() => updateStepInput(index, inputKey, option.value)}
            style={{ fontSize: '0.72rem', minHeight: 28 }}
          >
            {option.label}
          </Button>
        ))}
      </div>
    );
  }

  function renderTypedInputs(step: WorkflowStep, index: number) {
    const input = step.input || {};
    if (step.type === 'start_autopilot') {
      return (
        <div style={{ display: 'grid', gap: '0.75rem' }}>
          <div>
            <Label>Entry URLs</Label>
            <textarea
              value={inputList(input, 'entry_urls')}
              onChange={(event: ChangeEvent<HTMLTextAreaElement>) => updateStepInput(index, 'entry_urls', event.target.value.split('\n').map(item => item.trim()).filter(Boolean))}
              rows={3}
              placeholder="https://example.com"
              style={textareaStyle}
            />
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '0.75rem' }}>
            <div>
              <Label>Max interactions</Label>
              <Input type="number" min={1} value={inputNumber(input, 'max_interactions', 30)} onChange={event => updateStepInput(index, 'max_interactions', Number(event.target.value || 0))} />
            </div>
            <div>
              <Label>Max specs</Label>
              <Input type="number" min={1} value={inputNumber(input, 'max_specs', 10)} onChange={event => updateStepInput(index, 'max_specs', Number(event.target.value || 0))} />
            </div>
          </div>
        </div>
      );
    }

    if (step.type === 'wait_for_status') {
      const sourceSteps = steps.filter((candidate, candidateIndex) => candidateIndex !== index && candidate.key.trim());
      return (
        <div style={{ display: 'grid', gridTemplateColumns: 'minmax(180px, 1.2fr) repeat(2, minmax(140px, 0.8fr))', gap: '0.75rem' }}>
          <div>
            <Label>Source step</Label>
            {sourceSteps.length > 0 ? (
              <Select value={inputString(input, 'source_step')} onValueChange={value => updateStepInput(index, 'source_step', value)}>
                <SelectTrigger><SelectValue placeholder="Choose source" /></SelectTrigger>
                <SelectContent>
                  {sourceSteps.map(source => <SelectItem key={source.key} value={source.key}>{source.key}</SelectItem>)}
                </SelectContent>
              </Select>
            ) : (
              <Input value={inputString(input, 'source_step')} onChange={event => updateStepInput(index, 'source_step', event.target.value)} placeholder="source_step" />
            )}
          </div>
          <div>
            <Label>Timeout seconds</Label>
            <Input type="number" min={1} value={inputNumber(input, 'timeout_seconds', 3600)} onChange={event => updateStepInput(index, 'timeout_seconds', Number(event.target.value || 0))} />
          </div>
          <div>
            <Label>Poll seconds</Label>
            <Input type="number" min={1} value={inputNumber(input, 'poll_seconds', 10)} onChange={event => updateStepInput(index, 'poll_seconds', Number(event.target.value || 0))} />
          </div>
        </div>
      );
    }

    if (step.type === 'review_gate') {
      return (
        <div style={{ display: 'grid', gap: '0.75rem' }}>
          <div>
            <Label>Review prompt</Label>
            <textarea
              value={inputString(input, 'question', 'Review the current workflow state before continuing.')}
              onChange={(event: ChangeEvent<HTMLTextAreaElement>) => updateStepInput(index, 'question', event.target.value)}
              rows={3}
              style={textareaStyle}
            />
          </div>
          <div>
            <Label>Suggested answers</Label>
            <textarea
              value={inputList(input, 'suggested_answers')}
              onChange={(event: ChangeEvent<HTMLTextAreaElement>) => updateStepInput(index, 'suggested_answers', event.target.value.split('\n').map(item => item.trim()).filter(Boolean))}
              rows={2}
              placeholder={'Continue\nRevise first'}
              style={textareaStyle}
            />
          </div>
        </div>
      );
    }

    if (step.type === 'start_exploration') {
      return (
        <div style={{ display: 'grid', gridTemplateColumns: 'minmax(220px, 1fr) minmax(160px, 0.5fr)', gap: '0.75rem' }}>
          <div>
            <Label>Entry URL</Label>
            <Input value={inputString(input, 'entry_url', 'https://example.com')} onChange={event => updateStepInput(index, 'entry_url', event.target.value)} />
          </div>
          <div>
            <Label>Max interactions</Label>
            <Input type="number" min={1} value={inputNumber(input, 'max_interactions', 30)} onChange={event => updateStepInput(index, 'max_interactions', Number(event.target.value || 0))} />
          </div>
        </div>
      );
    }

    if (step.type === 'generate_requirements') {
      return (
        <div>
          <Label>Exploration session ID</Label>
          <Input
            value={inputString(input, 'exploration_session_id', '{{steps.explore.external_id}}')}
            onChange={event => updateStepInput(index, 'exploration_session_id', event.target.value)}
            placeholder="{{steps.explore.external_id}}"
          />
          {renderTokenButtons(index, 'exploration_session_id', tokenOptionsFor(index, ['start_exploration']))}
        </div>
      );
    }

    if (step.type === 'generate_specs_from_requirements') {
      return (
        <div style={{ display: 'grid', gap: '0.75rem' }}>
          <div>
            <Label>Target URL</Label>
            <Input value={inputString(input, 'target_url', 'https://example.com')} onChange={event => updateStepInput(index, 'target_url', event.target.value)} />
          </div>
          <div>
            <Label>Login URL</Label>
            <Input value={inputString(input, 'login_url')} onChange={event => updateStepInput(index, 'login_url', event.target.value)} placeholder="Optional" />
          </div>
        </div>
      );
    }

    if (step.type === 'run_spec') {
      return (
        <div>
          <Label>Spec name</Label>
          <Input value={inputString(input, 'spec_name', 'examples/hello-world.md')} onChange={event => updateStepInput(index, 'spec_name', event.target.value)} />
        </div>
      );
    }

    if (step.type === 'run_regression_batch') {
      return (
        <div style={{ display: 'grid', gap: '0.75rem' }}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: '0.75rem' }}>
            <div>
              <Label>Browser</Label>
              <Select value={inputString(input, 'browser', 'chromium')} onValueChange={value => updateStepInput(index, 'browser', value)}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="chromium">Chromium</SelectItem>
                  <SelectItem value="firefox">Firefox</SelectItem>
                  <SelectItem value="webkit">WebKit</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label>Max iterations</Label>
              <Input type="number" min={1} value={inputNumber(input, 'max_iterations', 20)} onChange={event => updateStepInput(index, 'max_iterations', Number(event.target.value || 0))} />
            </div>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '0.75rem' }}>
            <div>
              <Label>Tags</Label>
              <textarea
                value={inputList(input, 'tags')}
                onChange={(event: ChangeEvent<HTMLTextAreaElement>) => updateStepInput(index, 'tags', event.target.value.split('\n').map(item => item.trim()).filter(Boolean))}
                rows={3}
                placeholder={'smoke\nrelease'}
                style={textareaStyle}
              />
            </div>
            <div>
              <Label>Spec names</Label>
              <textarea
                value={inputList(input, 'spec_names')}
                onChange={(event: ChangeEvent<HTMLTextAreaElement>) => updateStepInput(index, 'spec_names', event.target.value.split('\n').map(item => item.trim()).filter(Boolean))}
                rows={3}
                placeholder="examples/hello-world.md"
                style={textareaStyle}
              />
            </div>
          </div>
          <div style={{ display: 'flex', gap: '1rem', flexWrap: 'wrap' }}>
            <label style={switchRowStyle}>
              <Switch checked={inputBoolean(input, 'automated_only', true)} onCheckedChange={checked => updateStepInput(index, 'automated_only', checked)} />
              <span>Automated specs only</span>
            </label>
            <label style={switchRowStyle}>
              <Switch checked={inputBoolean(input, 'hybrid', false)} onCheckedChange={checked => updateStepInput(index, 'hybrid', checked)} />
              <span>Hybrid healing</span>
            </label>
          </div>
        </div>
      );
    }

    if (step.type === 'start_custom_agent') {
      return (
        <div style={{ display: 'grid', gap: '0.75rem' }}>
          <div>
            <Label>Agent definition ID</Label>
            <Input value={inputString(input, 'definition_id')} onChange={event => updateStepInput(index, 'definition_id', event.target.value)} placeholder="Saved custom agent ID" />
          </div>
          <div>
            <Label>Prompt</Label>
            <textarea
              value={inputString(input, 'prompt', 'Inspect the target and report findings.')}
              onChange={(event: ChangeEvent<HTMLTextAreaElement>) => updateStepInput(index, 'prompt', event.target.value)}
              rows={4}
              style={textareaStyle}
            />
            {renderTokenButtons(index, 'prompt')}
          </div>
        </div>
      );
    }

    return (
      <div style={{ color: 'var(--text-secondary)', fontSize: '0.84rem' }}>
        This step type uses advanced JSON for its inputs.
      </div>
    );
  }

  function renderTemplates() {
    return (
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '1rem' }}>
        {WORKFLOW_TEMPLATES.map(template => (
          <article
            key={template.id}
            className="card-elevated"
            style={{
              padding: '1rem',
              display: 'grid',
              gap: '0.85rem',
              alignContent: 'space-between',
              minHeight: 218,
            }}
          >
            <div style={{ display: 'grid', gap: '0.7rem' }}>
              <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: '0.75rem' }}>
                <div style={{ minWidth: 0 }}>
                  <h3 style={{ margin: 0, fontSize: '0.98rem', lineHeight: 1.3 }}>{template.name}</h3>
                  <div style={{ color: 'var(--primary)', fontSize: '0.76rem', fontWeight: 700, marginTop: '0.3rem' }}>
                    {template.useCase}
                  </div>
                </div>
                <div style={{ width: 34, height: 34, borderRadius: 8, background: 'var(--primary-glow)', color: 'var(--primary)', display: 'grid', placeItems: 'center', flexShrink: 0 }}>
                  <FileText size={17} />
                </div>
              </div>
              <p style={{ margin: 0, color: 'var(--text-secondary)', fontSize: '0.82rem', lineHeight: 1.45 }}>
                {template.description}
              </p>
              <div style={{ display: 'flex', gap: '0.4rem', flexWrap: 'wrap', color: 'var(--text-secondary)', fontSize: '0.74rem' }}>
                <span style={workflowMetaPillStyle}>{template.steps.length} steps</span>
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
    );
  }

  function renderLibrary() {
    if (loading) return <WorkflowSkeleton />;
    if (definitions.length === 0) {
      return (
        <EmptyState
          title="No workflows"
          description="Create a reusable automation flow from the AutoPilot preset or build a custom sequence."
          icon={<Workflow size={28} />}
          action={
            <div style={{ display: 'flex', gap: '0.5rem', justifyContent: 'center', flexWrap: 'wrap' }}>
              <Button onClick={() => setActiveTab('templates')} variant="outline"><Sparkles size={15} /> Browse templates</Button>
              <Button onClick={() => resetBuilder()}><Plus size={15} /> Create workflow</Button>
              <Button variant="outline" onClick={() => resetBuilder(newAutopilotWorkflow())}><CircleDot size={15} /> AutoPilot preset</Button>
            </div>
          }
        />
      );
    }

    return (
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(340px, 1fr))', gap: '1rem', alignItems: 'stretch' }}>
        {definitions.map(definition => {
          const lastRun = runs.find(run => run.definition_id === definition.id);
          return (
            <article
              key={definition.id}
              className="card-elevated"
              style={{
                padding: 0,
                display: 'grid',
                gridTemplateRows: '1fr auto',
                minHeight: 178,
                overflow: 'hidden',
              }}
            >
              <div style={{ padding: '1rem 1rem 0.85rem', display: 'grid', gap: '0.8rem' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: '0.85rem', alignItems: 'flex-start' }}>
                <div style={{ minWidth: 0 }}>
                  <h3
                    title={definition.name}
                    style={{
                      margin: 0,
                      fontSize: '0.98rem',
                      lineHeight: 1.3,
                      minHeight: '1.3em',
                      overflow: 'hidden',
                      display: '-webkit-box',
                      WebkitBoxOrient: 'vertical',
                      WebkitLineClamp: 2,
                      wordBreak: 'break-word',
                    }}
                  >
                    {definition.name}
                  </h3>
                  <p
                    style={{
                      margin: '0.35rem 0 0',
                      color: 'var(--text-secondary)',
                      fontSize: '0.82rem',
                      lineHeight: 1.45,
                      overflow: 'hidden',
                      display: '-webkit-box',
                      WebkitBoxOrient: 'vertical',
                      WebkitLineClamp: 2,
                    }}
                  >
                    {definition.description || 'No description'}
                  </p>
                </div>
                {lastRun && <StatusBadge status={lastRun.status} />}
              </div>
              <div style={{ display: 'flex', gap: '0.45rem', color: 'var(--text-secondary)', fontSize: '0.75rem', flexWrap: 'wrap' }}>
                <span style={workflowMetaPillStyle}>{definition.steps?.length || 0} steps</span>
                <span style={workflowMetaPillStyle}>Updated {definition.updated_at ? timeAgo(definition.updated_at) : '-'}</span>
                {lastRun && <span style={workflowMetaPillStyle}>Last run {timeAgo(lastRun.created_at)}</span>}
              </div>
              </div>
              <div
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  gap: '0.65rem',
                  flexWrap: 'wrap',
                  padding: '0.75rem 1rem',
                  borderTop: '1px solid var(--border-subtle)',
                  background: 'rgba(255,255,255,0.018)',
                }}
              >
                <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap', minWidth: 0 }}>
                  <Button size="sm" onClick={() => startWorkflow(definition.id)} style={{ minWidth: 92 }}>
                    <Play size={14} /> Run Now
                  </Button>
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <Button size="sm" variant="outline" title="Run from a specific step" aria-label="Run from a specific step" style={{ minWidth: 112 }}>
                        <ListStart size={14} /> From Step <ChevronDown size={13} />
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent
                      align="start"
                      sideOffset={8}
                      collisionPadding={16}
                      style={{
                        minWidth: 280,
                        zIndex: 1000,
                        background: 'var(--background-raised)',
                        border: '1px solid var(--border)',
                        boxShadow: '0 18px 45px rgba(0,0,0,0.42)',
                      }}
                    >
                      <DropdownMenuLabel style={{ color: 'var(--text-secondary)', fontSize: '0.72rem', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
                        Run From Step
                      </DropdownMenuLabel>
                      <DropdownMenuSeparator />
                      {(definition.steps || []).map((step, index) => (
                        <DropdownMenuItem
                          key={`${definition.id}-${step.key}`}
                          onSelect={() => startWorkflow(definition.id, step.key)}
                          style={{ padding: '0.55rem 0.65rem', cursor: 'pointer', alignItems: 'flex-start' }}
                        >
                          <span style={{ width: 20, color: 'var(--text-secondary)', fontVariantNumeric: 'tabular-nums', flexShrink: 0 }}>{index + 1}</span>
                          <Play size={14} style={{ marginTop: 2, color: 'var(--primary)' }} />
                          <span style={{ minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                            {step.label || step.key}
                          </span>
                        </DropdownMenuItem>
                      ))}
                    </DropdownMenuContent>
                  </DropdownMenu>
                </div>
                <div style={{ display: 'flex', gap: '0.4rem', flexWrap: 'wrap' }}>
                  <Button size="icon" variant="outline" title="Edit workflow" aria-label="Edit workflow" onClick={() => selectDefinition(definition)} style={workflowIconButtonStyle}><Edit3 size={14} /></Button>
                  <Button size="icon" variant="outline" title="Duplicate workflow" aria-label="Duplicate workflow" onClick={() => duplicateWorkflow(definition)} style={workflowIconButtonStyle}><Copy size={14} /></Button>
                  <Button size="icon" variant="outline" title="Archive workflow" aria-label="Archive workflow" onClick={() => setArchiveTarget(definition)} style={workflowIconButtonStyle}><Archive size={14} /></Button>
                </div>
              </div>
            </article>
          );
        })}
      </div>
    );
  }

  function renderBuilder() {
    return (
      <div style={{ display: 'grid', gap: '1rem' }}>
        <Section
          title={selectedDefinitionId ? 'Edit workflow' : 'Create workflow'}
          description="Configure the workflow metadata and ordered automation steps."
          action={<Button size="sm" variant="outline" onClick={() => resetBuilder()}><Plus size={14} /> New</Button>}
        >
          <div style={{ display: 'grid', gridTemplateColumns: 'minmax(220px, 0.8fr) minmax(260px, 1.2fr)', gap: '0.85rem' }}>
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

          <div style={{ display: 'grid', gap: '0.85rem' }}>
            {steps.map((step, index) => {
              const stepErrors = validation.steps[index] || [];
              const jsonValue = jsonDrafts[index] ?? JSON.stringify(step.input || {}, null, 2);
              return (
                <article key={`${step.key}-${index}`} style={{ border: '1px solid var(--border-subtle)', borderRadius: 8, background: 'var(--surface)', overflow: 'hidden' }}>
                  <div style={{ padding: '0.9rem 1rem', display: 'flex', gap: '0.8rem', justifyContent: 'space-between', alignItems: 'flex-start', borderBottom: '1px solid var(--border-subtle)' }}>
                    <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'flex-start', minWidth: 0 }}>
                      <div style={{ width: 30, height: 30, borderRadius: 999, background: 'var(--primary-glow)', color: 'var(--primary)', display: 'grid', placeItems: 'center', fontWeight: 700, flexShrink: 0 }}>
                        {index + 1}
                      </div>
                      <div style={{ minWidth: 0 }}>
                        <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', flexWrap: 'wrap' }}>
                          <strong>{step.label || defaultLabelFor(step.type, catalog)}</strong>
                          <span style={{ fontSize: '0.72rem', border: '1px solid var(--border-subtle)', borderRadius: 999, padding: '0.1rem 0.45rem', color: 'var(--text-secondary)' }}>
                            {pretty(step.type)}
                          </span>
                        </div>
                        <div style={{ marginTop: '0.25rem', color: 'var(--text-secondary)', fontSize: '0.78rem' }}>
                          {catalog.find(item => item.type === step.type)?.description || 'Custom workflow step'}
                        </div>
                      </div>
                    </div>
                    <div style={{ display: 'flex', gap: '0.35rem', flexShrink: 0 }}>
                      <Button size="icon" variant="ghost" title="Move step up" aria-label="Move step up" onClick={() => moveStep(index, -1)} disabled={index === 0}><ArrowUp size={15} /></Button>
                      <Button size="icon" variant="ghost" title="Move step down" aria-label="Move step down" onClick={() => moveStep(index, 1)} disabled={index === steps.length - 1}><ArrowDown size={15} /></Button>
                      <Button size="icon" variant="ghost" title="Duplicate step" aria-label="Duplicate step" onClick={() => duplicateStep(index)}><Copy size={15} /></Button>
                      <Button size="icon" variant="ghost" title="Remove step" aria-label="Remove step" onClick={() => removeStep(index)}><Trash2 size={15} /></Button>
                    </div>
                  </div>

                  <div style={{ padding: '1rem', display: 'grid', gap: '0.85rem' }}>
                    <div style={{ display: 'grid', gridTemplateColumns: 'minmax(160px, 0.7fr) minmax(220px, 1fr)', gap: '0.75rem' }}>
                      <div>
                        <Label>Key</Label>
                        <Input value={step.key} onChange={event => updateStep(index, { key: event.target.value })} />
                      </div>
                      <div>
                        <Label>Type</Label>
                        {catalog.length > 0 ? (
                          <Select value={step.type} onValueChange={value => updateStep(index, { type: value, input: defaultInputFor(value), label: defaultLabelFor(value, catalog) })}>
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

                    <label style={switchRowStyle}>
                      <Switch checked={Boolean(step.continue_on_error)} onCheckedChange={checked => updateStep(index, { continue_on_error: checked })} />
                      <span>Continue if this step fails</span>
                    </label>

                    {renderTypedInputs(step, index)}

                    <div>
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        onClick={() => setAdvancedOpen(prev => ({ ...prev, [index]: !prev[index] }))}
                      >
                        Advanced JSON
                      </Button>
                      {advancedOpen[index] && (
                        <div style={{ marginTop: '0.7rem' }}>
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
              <Button onClick={saveDefinition} disabled={saving}>
                {saving ? <Loader2 size={15} style={{ animation: 'spin 1s linear infinite' }} /> : <CheckCircle2 size={15} />}
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
    return (
      <div style={diagnosticBoxStyle}>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: '0.75rem', flexWrap: 'wrap' }}>
          <div>
            <div style={{ fontWeight: 750, color: 'var(--text)' }}>{step.label || step.step_key}</div>
            <div style={{ color: 'var(--text-secondary)', fontSize: '0.78rem', marginTop: '0.15rem' }}>
              Step {step.step_order + 1} - {pretty(step.step_type)}
            </div>
          </div>
          <StatusBadge status={outputStatus || step.status} />
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
            <details style={detailDisclosureStyle}>
              <summary style={summaryStyle}>Input</summary>
              <pre style={preStyle}>{inputText || '{}'}</pre>
            </details>
            <details style={detailDisclosureStyle} open={Boolean(step.output && (step.error_message || outputStatus))}>
              <summary style={summaryStyle}>Output</summary>
              <pre style={preStyle}>{outputText || 'No output captured.'}</pre>
            </details>
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
          <StatusBadge status={autoPilotSession?.status || autoPilotLive?.status || 'unknown'} />
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
            <Progress value={progress(currentPhase.progress)} style={{ height: 8 }} />
            <div style={{ color: 'var(--text-secondary)', fontSize: '0.76rem' }}>
              {currentPhase.items_completed} / {currentPhase.items_total} items - {progress(currentPhase.progress)}%
            </div>
            {currentPhase.error_message && <FieldError>{currentPhase.error_message}</FieldError>}
          </div>
        )}
        <div style={{ marginTop: '0.9rem', display: 'grid', gridTemplateColumns: 'minmax(220px, 0.9fr) minmax(260px, 1.1fr)', gap: '0.85rem' }}>
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
              <div style={{ color: 'var(--text-secondary)', fontSize: '0.82rem' }}>
                No live screenshot captured yet.
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
              <span>Started {selectedRun.started_at ? timeAgo(selectedRun.started_at) : timeAgo(selectedRun.created_at)}</span>
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
            <span>Overall Progress</span>
            <span>{percentage}%</span>
          </div>
          <Progress value={percentage} style={{ height: 8 }} />
        </div>
        <div style={stepTimelineStyle}>
          {selectedRunSteps.length === 0 ? (
            <div style={{ color: 'var(--text-secondary)', fontSize: '0.84rem' }}>
              No step records have been captured for this run yet.
            </div>
          ) : selectedRunSteps.map(step => {
            const selected = diagnosticStep?.id === step.id;
            return (
              <button
                key={step.id}
                type="button"
                onClick={() => setSelectedRunStepId(step.id)}
                style={{
                  ...stepChipStyle,
                  borderColor: selected ? 'rgba(248,113,113,0.55)' : step.status === 'running' ? 'rgba(59,130,246,0.55)' : 'var(--border-subtle)',
                  background: selected ? 'rgba(248,113,113,0.08)' : step.status === 'running' ? 'rgba(59,130,246,0.08)' : 'rgba(255,255,255,0.018)',
                }}
              >
                <span style={{ color: 'var(--text-secondary)', fontVariantNumeric: 'tabular-nums' }}>{step.step_order + 1}</span>
                <span style={{ minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{step.label || step.step_key}</span>
                <StatusBadge status={externalStatusFromStep(step) || step.status} />
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

  function renderRuns() {
    if (loading) return <WorkflowSkeleton />;
    return (
      <Section
        title="Recent runs"
        description={`${activeRuns.length} active workflow${activeRuns.length === 1 ? '' : 's'}`}
        action={
          <div style={{ display: 'flex', gap: '0.35rem', flexWrap: 'wrap' }}>
            {(['active', 'failed', 'completed', 'all'] as RunFilter[]).map(filter => (
              <Button
                key={filter}
                size="sm"
                variant={runFilter === filter ? 'default' : 'outline'}
                onClick={() => setRunFilter(filter)}
              >
                {pretty(filter)}
              </Button>
            ))}
          </div>
        }
      >
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
          <Table>
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
                      <div style={{ display: 'flex', gap: '0.35rem', justifyContent: 'flex-end' }}>
                        <Button
                          size="sm"
                          variant={selectedRunId === run.id ? 'default' : 'outline'}
                          title="View workflow run details"
                          aria-label="View workflow run details"
                          onClick={() => {
                            setSelectedRunId(run.id);
                            setActiveTab('runs');
                          }}
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

  return (
    <PageLayout tier="wide">
      <PageHeader
        title="Custom Workflows"
        subtitle="Create guided automation sequences and monitor reusable runs from one workspace."
        icon={<Workflow size={20} />}
        actions={
          <>
            <Button onClick={() => load(false)} variant="outline"><RefreshCw size={15} /> Refresh</Button>
            <Button onClick={() => setActiveTab('templates')} variant="outline"><Sparkles size={15} /> Templates</Button>
            <Button onClick={() => resetBuilder()}><Plus size={15} /> New workflow</Button>
          </>
        }
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

      <div style={{ display: 'flex', gap: '0.25rem', borderBottom: '1px solid var(--border-subtle)', marginBottom: '1rem', overflowX: 'auto' }}>
        {([
          ['templates', `Templates (${WORKFLOW_TEMPLATES.length})`],
          ['library', `Library (${definitions.length})`],
          ['builder', selectedDefinitionId ? 'Builder: edit' : 'Builder'],
          ['runs', `Runs (${activeRuns.length} active)`],
        ] as const).map(([tab, label]) => (
          <button key={tab} onClick={() => setActiveTab(tab)} style={createTabStyle(activeTab, tab)}>
            {label}
          </button>
        ))}
      </div>

      {activeTab === 'templates' && (
        <Section
          title="Workflow templates"
          description="Start with an editable QA pipeline, then tailor every step in the builder."
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
      <ConfirmDialog
        open={Boolean(archiveTarget)}
        onOpenChange={open => {
          if (!open) setArchiveTarget(null);
        }}
        title="Archive workflow"
        description={`Archive ${archiveTarget?.name || 'this workflow'}? It will be hidden from the workflow library.`}
        confirmLabel="Archive"
        variant="danger"
        onConfirm={() => {
          if (archiveTarget) void archiveWorkflow(archiveTarget);
          setArchiveTarget(null);
        }}
      />
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
  borderRadius: 8,
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
  minHeight: 42,
  border: '1px solid var(--border-subtle)',
  borderRadius: 8,
  padding: '0.5rem 0.65rem',
  color: 'var(--text)',
  textAlign: 'left',
  cursor: 'pointer',
};

const diagnosticBoxStyle: React.CSSProperties = {
  border: '1px solid var(--border-subtle)',
  borderRadius: 8,
  background: 'var(--background)',
  padding: '0.85rem',
};

const detailDisclosureStyle: React.CSSProperties = {
  border: '1px solid var(--border-subtle)',
  borderRadius: 8,
  padding: '0.65rem',
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
  borderRadius: 8,
  background: 'rgba(255,255,255,0.014)',
  padding: '0.75rem',
  minWidth: 0,
};

const metricMiniStyle: React.CSSProperties = {
  border: '1px solid var(--border-subtle)',
  borderRadius: 8,
  padding: '0.5rem',
  minWidth: 0,
};

const textareaStyle: React.CSSProperties = {
  width: '100%',
  border: '1px solid var(--border-subtle)',
  borderRadius: 8,
  padding: '0.6rem',
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
};
