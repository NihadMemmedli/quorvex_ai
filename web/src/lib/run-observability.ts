const ACTIVE_RUN_STATUSES = new Set(['queued', 'pending', 'running', 'in_progress']);
const DEFAULT_STALE_AFTER_SECONDS = 120;

export interface RunObservabilityHealth {
  last_log_at?: string | null;
  last_artifact_at?: string | null;
  last_temporal_event_at?: string | null;
  stage_started_at?: string | null;
  stage_age_seconds?: number | null;
  last_log_age_seconds?: number | null;
  last_artifact_age_seconds?: number | null;
  last_temporal_event_age_seconds?: number | null;
  has_recent_output?: boolean;
  stuck_warning?: string | null;
  warnings?: string[];
  stale_after_seconds?: number | null;
  temporal_started_activities?: Array<Record<string, any>>;
  browser_slot_owner?: string | null;
  agent_progress?: Record<string, any> | null;
}

export interface RunObservabilityInput {
  status?: string | null;
  effective_status?: string | null;
  current_stage?: string | null;
  stage_started_at?: string | null;
  health?: RunObservabilityHealth | null;
  diagnostics?: {
    temporal?: Record<string, any> | null;
    browser_pool?: Record<string, any> | null;
    agent_progress?: Record<string, any> | null;
  } | null;
  agentic_summary?: Record<string, any> | null;
}

function parseDateMs(value?: string | null): number | null {
  if (!value) return null;
  const ms = new Date(value).getTime();
  return Number.isFinite(ms) ? ms : null;
}

function ageSeconds(value: string | null | undefined, nowMs: number): number | null {
  const ms = parseDateMs(value);
  if (ms === null) return null;
  return Math.max(0, Math.floor((nowMs - ms) / 1000));
}

export function isRunActiveForObservability(run: RunObservabilityInput | null | undefined): boolean {
  const status = String(run?.status || run?.effective_status || '').toLowerCase();
  return ACTIVE_RUN_STATUSES.has(status);
}

export function formatAge(seconds?: number | null): string {
  if (seconds === null || seconds === undefined) return 'unknown';
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  return `${hours}h ${minutes % 60}m`;
}

export function resolveRunHealth(run: RunObservabilityInput | null | undefined, now: Date = new Date()): RunObservabilityHealth {
  const nowMs = now.getTime();
  const health = run?.health || {};
  const stageStartedAt = health.stage_started_at || run?.stage_started_at || null;
  const lastLogAge = health.last_log_age_seconds ?? ageSeconds(health.last_log_at, nowMs);
  const lastArtifactAge = health.last_artifact_age_seconds ?? ageSeconds(health.last_artifact_at, nowMs);
  const lastTemporalAge = health.last_temporal_event_age_seconds ?? ageSeconds(health.last_temporal_event_at, nowMs);
  const stageAge = health.stage_age_seconds ?? ageSeconds(stageStartedAt, nowMs);
  const staleAfterSeconds = health.stale_after_seconds ?? DEFAULT_STALE_AFTER_SECONDS;
  const recentAges = [lastLogAge, lastArtifactAge].filter((value): value is number => typeof value === 'number');
  const hasRecentOutput = health.has_recent_output ?? (recentAges.length > 0 && Math.min(...recentAges) <= staleAfterSeconds);

  const warnings = [...(health.warnings || [])];
  const agentProgress = health.agent_progress || run?.diagnostics?.agent_progress || null;
  const active = isRunActiveForObservability(run);
  if (active && warnings.length === 0) {
    if (lastLogAge === null && !hasRecentOutput) {
      warnings.push('No execution.log has been written while this run is active.');
    } else if (lastLogAge !== null && lastLogAge > staleAfterSeconds && !hasRecentOutput) {
      warnings.push(`No new execution.log output for ${formatAge(lastLogAge)}.`);
    }
    const startedActivities = health.temporal_started_activities || run?.diagnostics?.temporal?.activities?.filter((activity: any) => activity?.status === 'started') || [];
    if (startedActivities.length > 0 && lastTemporalAge !== null && lastTemporalAge > staleAfterSeconds && !hasRecentOutput) {
      warnings.push(`Temporal activity is started, but workflow history has not advanced for ${formatAge(lastTemporalAge)}.`);
    }
    if (health.browser_slot_owner && lastLogAge !== null && lastLogAge > staleAfterSeconds && !hasRecentOutput) {
      warnings.push('Browser slot is still held by this run while planner/tool logs are stale.');
    }
    if (agentProgress) {
      const messages = Number(agentProgress.messages_received || 0);
      const textBlocks = Number(agentProgress.text_blocks_received || 0);
      const toolCalls = Number(agentProgress.tool_calls || 0);
      const outputChars = Number(agentProgress.output_chars || 0);
      const unproductive = Boolean(agentProgress.unproductive_stream) || (
        messages >= Number(agentProgress.unproductive_stream_min_messages || 500)
        && Number(agentProgress.elapsed_seconds || 0) >= Number(agentProgress.unproductive_stream_seconds || 180)
        && textBlocks === 0
        && toolCalls === 0
        && outputChars === 0
      );
      if (unproductive) {
        warnings.push(`Planner stream received ${messages} messages but produced no parsed text, tool calls, or output.`);
      }
    }
  }

  return {
    ...health,
    stage_started_at: stageStartedAt,
    stage_age_seconds: stageAge,
    last_log_age_seconds: lastLogAge,
    last_artifact_age_seconds: lastArtifactAge,
    last_temporal_event_age_seconds: lastTemporalAge,
    has_recent_output: hasRecentOutput,
    stuck_warning: health.stuck_warning || warnings[0] || null,
    warnings,
    agent_progress: agentProgress,
    stale_after_seconds: staleAfterSeconds,
  };
}

export function extractLinkedAgentRunId(value: unknown): string | null {
  const seen = new Set<unknown>();
  const visit = (node: unknown): string | null => {
    if (!node || typeof node !== 'object' || seen.has(node)) return null;
    seen.add(node);
    const record = node as Record<string, unknown>;
    for (const key of ['agent_run_id', 'agentRunId', 'linked_agent_run_id', 'linkedAgentRunId']) {
      const candidate = record[key];
      if (typeof candidate === 'string' && candidate.trim()) return candidate.trim();
    }
    for (const child of Object.values(record)) {
      if (Array.isArray(child)) {
        for (const item of child) {
          const found = visit(item);
          if (found) return found;
        }
      } else if (child && typeof child === 'object') {
        const found = visit(child);
        if (found) return found;
      }
    }
    return null;
  };
  return visit(value);
}

export function resolveLinkedAgentRunId(run: unknown): string | null {
  if (!run || typeof run !== 'object') return null;
  const record = run as Record<string, unknown>;
  for (const key of ['linked_agent_run_id', 'linkedAgentRunId']) {
    const candidate = record[key];
    if (typeof candidate === 'string' && candidate.trim()) return candidate.trim();
  }
  return extractLinkedAgentRunId(record.agentic_summary);
}
