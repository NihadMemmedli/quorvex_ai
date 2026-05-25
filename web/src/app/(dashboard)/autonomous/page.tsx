'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import type { FormEvent, ReactNode } from 'react';
import {
    AlertCircle,
    Bot,
    CalendarClock,
    ChevronDown,
    ChevronRight,
    CheckCircle,
    ClipboardCheck,
    Compass,
    DollarSign,
    FileText,
    Gauge,
    Loader2,
    Pause,
    Play,
    Plus,
    RefreshCw,
    ShieldCheck,
    Sparkles,
    Square,
    Target,
    Terminal,
    UploadCloud,
    Users,
    Workflow,
    X,
    XCircle,
} from 'lucide-react';
import { fetchWithAuth } from '@/contexts/AuthContext';
import { useProject } from '@/contexts/ProjectContext';
import { API_BASE } from '@/lib/api';
import { PageLayout } from '@/components/ui/page-layout';
import { PageHeader } from '@/components/ui/page-header';
import { ListPageSkeleton } from '@/components/ui/page-skeleton';
import { LiveBrowserView } from '@/components/LiveBrowserView';

interface MissionStatusDetails {
    status?: string | null;
    state?: string | null;
    value?: string | null;
    team_summary?: unknown;
    active_work_items?: unknown;
    blocked_work_items?: unknown;
    coverage_summary?: unknown;
}

interface Mission {
    id: string;
    name: string;
    mission_type: string;
    status: string | MissionStatusDetails;
    schedule_cron?: string | null;
    target_urls?: string[];
    autonomy_level: string;
    approval_policy: string;
    latest_run_id?: string | null;
    last_run_at?: string | null;
    next_run_at?: string | null;
    last_error?: string | null;
    health_status?: string | null;
    paused_reason?: string | null;
    consecutive_failures?: number;
    last_heartbeat_at?: string | null;
    current_stage?: string | null;
    next_action?: string | null;
    total_runs: number;
    total_findings: number;
    budget_used_usd: number;
    max_iterations?: number;
    max_runtime_minutes?: number;
    max_llm_budget_usd?: number | null;
    team_summary?: unknown;
    monitor_summary?: Record<string, unknown> | null;
    last_monitor_at?: string | null;
    diagnostics_status?: string | null;
    stale_running_count?: number | null;
    failed_validation_count?: number | null;
    duplicate_canonical_count?: number | null;
    unmapped_confirmed_requirement_count?: number | null;
    validation_artifact_count?: number | null;
    active_work_items?: unknown;
    blocked_work_items?: unknown;
    coverage_summary?: unknown;
    safety_summary?: {
        environment?: string;
        allowed_domains?: string[];
        tool_profile?: string;
        credential_scope?: string;
        write_policy?: string;
        approval_policy?: string;
    };
    created_at: string;
}

interface AutonomousDiagnostics {
    status?: string;
    requirements?: {
        total?: number;
        missing_canonical_key?: number;
        duplicate_canonical_keys?: number;
        unmapped_full_coverage?: number;
    };
    rtm?: {
        total_entries?: number;
        missing_dedupe_key?: number;
    };
    work_items?: {
        total?: number;
        stale_running?: number;
        recovered?: number;
    };
    proposals?: {
        total?: number;
        materialized?: number;
        auto_materialized?: number;
        validation_failed?: number;
        validation_blocked?: number;
        validation_not_run?: number;
    };
}

interface MissionForm {
    name: string;
    description: string;
    mission_type: string;
    target_urls: string;
    schedule_cron: string;
    timezone: string;
    max_runtime_minutes: number;
    max_iterations: number;
    max_llm_budget_usd: number;
    environment: string;
    allowed_domains: string;
    tool_profile: string;
    credential_scope: string;
}

interface FormErrors {
    name?: string;
    target_urls?: string;
}

interface Approval {
    id: string;
    mission_id: string;
    finding_id?: string | null;
    action_type: string;
    status: string;
    requested_payload?: Record<string, unknown>;
    requested_at: string;
}

interface TestProposal {
    id: string;
    title: string;
    target_url?: string | null;
    target_route?: string | null;
    route?: string | null;
    test_type: string;
    risk_level: string;
    rationale?: string | null;
    suggested_file_path?: string | null;
    approval_status: string;
    generated_spec_content?: string | null;
    materialized_file_path?: string | null;
    validation_status?: string | null;
    validation_result?: Record<string, unknown> | null;
    validation_artifacts?: Array<Record<string, unknown>> | null;
    validation_log_path?: string | null;
    validation_trace_path?: string | null;
    validated_at?: string | null;
    source_type?: string | null;
    source_id?: string | null;
    source_metadata?: Record<string, unknown> | null;
    review_context?: {
        provenance?: {
            source_type?: string | null;
            source_id?: string | null;
            finding_id?: string | null;
            coverage_gap_id?: number | null;
            confidence?: number | string | null;
            evidence?: Record<string, unknown>;
        };
        duplicate?: {
            has_warning?: boolean;
            existing_file_conflict?: boolean;
            blocking?: boolean;
            severity?: 'none' | 'warning' | 'blocking' | string;
            matches?: Array<{
                kind?: string;
                id?: string;
                path?: string | null;
                title?: string;
                status?: string;
                suggested_file_path?: string | null;
                score?: number;
                blocking?: boolean;
                reasons?: string[];
            }>;
            candidates?: Array<{
                id: string;
                kind?: string;
                path?: string | null;
                title: string;
                status?: string;
                suggested_file_path?: string | null;
                score?: number;
                blocking?: boolean;
                reasons?: string[];
            }>;
        };
        staleness?: {
            is_stale?: boolean;
            reason?: string | null;
            status?: 'fresh' | 'needs_review' | 'stale' | string;
            reasons?: Array<{
                source?: string;
                message?: string;
                confidence?: number;
                entity_id?: string | number;
                stale?: boolean;
            }>;
            last_checked_at?: string | null;
        };
        merge_gate?: string;
    };
    created_at?: string | null;
}

interface WorkItem {
    id: string;
    mission_id?: string | null;
    mission_name?: string | null;
    title?: string | null;
    summary?: string | null;
    status?: string | null;
    lane?: string | null;
    priority?: string | number | null;
    owner_agent?: string | null;
    blocked_reason?: string | null;
    progress?: Record<string, unknown> | null;
    artifacts?: Array<Record<string, unknown>> | null;
    result?: Record<string, unknown> | null;
    agent_task_id?: string | null;
    planner_key?: string | null;
    lease_until?: string | null;
    last_heartbeat_at?: string | null;
    recovery_count?: number | string | null;
    recovery_reason?: string | null;
    updated_at?: string | null;
    created_at?: string | null;
}

interface AgentEvent {
    id: string;
    mission_id: string;
    run_id?: string | null;
    work_item_id?: string | null;
    agent_task_id?: string | null;
    sequence: number;
    event_type: string;
    level: string;
    message: string;
    payload?: Record<string, unknown>;
    created_at: string;
}

interface AuditWorkItem {
    id?: string | null;
    role?: string | null;
    title?: string | null;
    objective?: string | null;
    status?: string | null;
    output_preview?: string | null;
    review_decision?: string | null;
    review_reason?: string | null;
    reviewed_by?: string | null;
    reviewed_at?: string | null;
    result?: Record<string, unknown> | null;
    progress?: Record<string, unknown> | null;
    created_at?: string | null;
    updated_at?: string | null;
}

interface AuditRequirement {
    id?: string | number | null;
    req_code?: string | null;
    title?: string | null;
    truth_state?: string | null;
    confidence?: number | string | null;
    uncertainty_reason?: string | null;
    confirmed_by?: string | null;
    confirmed_at?: string | null;
    rejected_by?: string | null;
    rejected_at?: string | null;
}

interface ProposalAudit {
    proposal: TestProposal;
    finding?: AppChangeFinding | null;
    source_work_item?: AuditWorkItem | null;
    revision_chain?: AuditWorkItem[];
    linked_requirement?: AuditRequirement | null;
    review_events?: AgentEvent[];
    timeline: Array<{
        type: string;
        at?: string | null;
        message: string;
        payload?: Record<string, unknown> | null;
    }>;
}

interface AppChangeFinding {
    id?: string | number | null;
    title?: string | null;
    summary?: string | null;
    description?: string | null;
    source_type?: string | null;
    change_type?: string | null;
    risk_level?: string | null;
    test_value?: string | number | boolean | Record<string, unknown> | null;
    uncertainty_reason?: string | null;
    category?: string | null;
    status?: string | null;
    severity?: string | null;
    confidence?: number | string | null;
    requirement_id?: string | number | null;
    requirement?: string | Record<string, unknown> | null;
    requirement_title?: string | null;
    truth_state?: string | null;
    test_proposal_id?: string | null;
    linked_proposal_id?: string | null;
    proposal_id?: string | null;
    test_proposal_status?: string | null;
    proposal_status?: string | null;
    test_proposal?: Partial<TestProposal> | null;
    proposal?: Partial<TestProposal> | null;
    memory_delta?: Record<string, unknown> | null;
    app_change?: Record<string, unknown> | null;
    evidence?: Record<string, unknown> | null;
    created_at?: string | null;
}

interface AppChangeGroup {
    key: string;
    label: string;
    findings: AppChangeFinding[];
}

interface TeamTimelineItem {
    id?: string | null;
    work_item_id?: string | null;
    mission_id?: string | null;
    role?: string | null;
    owner_agent?: string | null;
    title?: string | null;
    summary?: string | null;
    status?: string | null;
    latest_event?: string | Record<string, unknown> | null;
    output_preview?: string | null;
    blocker?: string | null;
    blocked_reason?: string | null;
    artifacts_count?: number | null;
    artifacts?: Array<Record<string, unknown>> | null;
    progress?: Record<string, unknown> | null;
    result?: Record<string, unknown> | null;
    review_decision?: string | null;
    review_reason?: string | null;
    reviewed_at?: string | null;
    reviewed_by?: string | null;
    is_revision?: boolean | null;
    revision_of_work_item_id?: string | null;
    revision_work_item_id?: string | null;
    revision_attempt?: string | number | null;
    planner_key?: string | null;
    lease_until?: string | null;
    last_heartbeat_at?: string | null;
    recovery_count?: number | string | null;
    recovery_reason?: string | null;
    review?: Record<string, unknown> | null;
    review_metadata?: Record<string, unknown> | null;
    updated_at?: string | null;
    created_at?: string | null;
}

type LiveTab = 'live' | 'browser' | 'events' | 'output' | 'runs';

const DEFAULT_FORM: MissionForm = {
    name: '',
    description: '',
    mission_type: 'exploration',
    target_urls: '',
    schedule_cron: '',
    timezone: 'UTC',
    max_runtime_minutes: 30,
    max_iterations: 0,
    max_llm_budget_usd: 5,
    environment: 'staging',
    allowed_domains: '',
    tool_profile: 'role_based',
    credential_scope: 'project',
};

const PROPOSAL_FILTERS = ['pending', 'approved', 'materialized', 'rejected', 'all', 'duplicate_risk', 'blocking', 'stale', 'needs_review', 'validation_failed', 'blocked'] as const;
type ProposalFilter = typeof PROPOSAL_FILTERS[number];

const APP_CHANGE_STATUS_FILTERS = ['active', 'awaiting_approval', 'approved', 'rejected', 'resolved', 'all'] as const;
type AppChangeStatusFilter = typeof APP_CHANGE_STATUS_FILTERS[number];

const proposalFilterSet = new Set<string>(PROPOSAL_FILTERS);
const proposalStatusFilters = new Set<string>(['pending', 'approved', 'materialized', 'rejected']);
const proposalReviewFilters = new Set<string>(['duplicate_risk', 'blocking', 'stale', 'needs_review', 'validation_failed', 'blocked']);
const hiddenAppChangeStatuses = new Set<string>(['resolved']);

const dateFormatter = new Intl.DateTimeFormat(undefined, {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
});

const currencyFormatter = new Intl.NumberFormat(undefined, {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: 2,
});

const QUICK_START_TEMPLATES: Array<{
    label: string;
    mission_type: string;
    description: string;
    schedule_cron: string;
    max_runtime_minutes: number;
    max_iterations: number;
    max_llm_budget_usd: number;
    capability: string;
    icon: ReactNode;
}> = [
    {
        label: 'Whole App Team',
        mission_type: 'mixed',
        description: 'Coordinate a compact team across app-wide discovery and coverage.',
        schedule_cron: '',
        max_runtime_minutes: 35,
        max_iterations: 0,
        max_llm_budget_usd: 8,
        capability: 'Starts a small autonomous team for whole-app discovery, active work lanes, blockers, and coverage follow-up.',
        icon: <Users size={16} />,
    },
    {
        label: 'Exploration',
        mission_type: 'exploration',
        description: 'Map key pages, flows, and interaction paths.',
        schedule_cron: '0 9 * * 1-5',
        max_runtime_minutes: 30,
        max_iterations: 0,
        max_llm_budget_usd: 5,
        capability: 'Maps known coverage gaps into reviewable exploration proposals.',
        icon: <Compass size={16} />,
    },
    {
        label: 'Continuous Watch',
        mission_type: 'mixed',
        description: 'Run around the clock with approval-gated findings.',
        schedule_cron: '',
        max_runtime_minutes: 45,
        max_iterations: 0,
        max_llm_budget_usd: 10,
        capability: 'Keeps recurring exploration, coverage review, regression watch, and flake triage alive until paused.',
        icon: <Workflow size={16} />,
    },
    {
        label: 'Coverage Gaps',
        mission_type: 'coverage',
        description: 'Look for untested routes and missing assertions.',
        schedule_cron: '0 10 * * 1-5',
        max_runtime_minutes: 25,
        max_iterations: 0,
        max_llm_budget_usd: 4,
        capability: 'Finds untested routes and turns gaps into approval-gated test proposals.',
        icon: <ClipboardCheck size={16} />,
    },
    {
        label: 'Regression Watch',
        mission_type: 'regression',
        description: 'Revisit important paths on a recurring cadence.',
        schedule_cron: '0 8 * * 1-5',
        max_runtime_minutes: 20,
        max_iterations: 0,
        max_llm_budget_usd: 3,
        capability: 'Captures a recurring regression intent while deeper execution hooks mature.',
        icon: <ShieldCheck size={16} />,
    },
    {
        label: 'Flake Triage',
        mission_type: 'flake_triage',
        description: 'Investigate unstable specs and timing-sensitive flows.',
        schedule_cron: '0 12 * * 1-5',
        max_runtime_minutes: 20,
        max_iterations: 0,
        max_llm_budget_usd: 3,
        capability: 'Records flake triage intent and keeps the approval flow ready for proposals.',
        icon: <Gauge size={16} />,
    },
];

const SCHEDULE_PRESETS = [
    { label: 'Continuous', cron: '' },
    { label: 'Business hours', cron: '0 9-17 * * 1-5' },
    { label: 'Daily', cron: '0 9 * * *' },
];

function getStoredProjectId() {
    if (typeof window === 'undefined') return null;
    return localStorage.getItem('selectedProjectId');
}

function getInitialProposalFilter(): ProposalFilter {
    if (typeof window === 'undefined') return 'pending';
    const requested = new URLSearchParams(window.location.search).get('proposalStatus');
    return requested && proposalFilterSet.has(requested) ? requested as ProposalFilter : 'pending';
}

function normalizeMissions(data: unknown): Mission[] {
    if (Array.isArray(data)) return data as Mission[];
    if (data && typeof data === 'object' && Array.isArray((data as { missions?: unknown }).missions)) {
        return (data as { missions: Mission[] }).missions;
    }
    return [];
}

function normalizeProposals(data: unknown): TestProposal[] {
    if (Array.isArray(data)) return data as TestProposal[];
    if (data && typeof data === 'object' && Array.isArray((data as { proposals?: unknown }).proposals)) {
        return (data as { proposals: TestProposal[] }).proposals;
    }
    return [];
}

function normalizeAppChanges(data: unknown): AppChangeGroup[] {
    if (!data) return [];
    if (Array.isArray(data)) return groupAppChangeFindings(data as AppChangeFinding[]);
    if (typeof data !== 'object') return [];

    const payload = data as {
        groups?: unknown;
        grouped?: unknown;
        items?: unknown;
        findings?: unknown;
        app_changes?: unknown;
        changes?: unknown;
        memory_deltas?: unknown;
    };

    if (Array.isArray(payload.groups)) {
        return payload.groups.flatMap((group, index) => {
            if (!group || typeof group !== 'object') return [];
            const record = group as { key?: unknown; label?: unknown; findings?: unknown; items?: unknown; changes?: unknown };
            const findings = record.findings || record.items || record.changes;
            if (!Array.isArray(findings)) return [];
            const key = String(record.key || record.label || `group-${index}`);
            return [{
                key,
                label: String(record.label || record.key || key).replace(/_/g, ' '),
                findings: findings as AppChangeFinding[],
            }];
        });
    }

    if (payload.grouped && typeof payload.grouped === 'object' && !Array.isArray(payload.grouped)) {
        return Object.entries(payload.grouped as Record<string, unknown>).flatMap(([key, value]) => {
            if (!Array.isArray(value)) return [];
            return [{
                key,
                label: key.replace(/_/g, ' '),
                findings: value as AppChangeFinding[],
            }];
        });
    }

    const findings = [payload.items, payload.findings, payload.app_changes, payload.changes, payload.memory_deltas]
        .find(Array.isArray) as AppChangeFinding[] | undefined;
    return groupAppChangeFindings(findings || []);
}

function groupAppChangeFindings(findings: AppChangeFinding[]): AppChangeGroup[] {
    const groups = new Map<string, AppChangeFinding[]>();
    findings.forEach(finding => {
        const key = String(finding.source_type || finding.change_type || finding.category || 'app_change');
        groups.set(key, [...(groups.get(key) || []), finding]);
    });
    return Array.from(groups.entries()).map(([key, items]) => ({
        key,
        label: key.replace(/_/g, ' '),
        findings: items,
    }));
}

function isBlockingDuplicate(proposal: TestProposal) {
    const duplicate = proposal.review_context?.duplicate;
    return Boolean(duplicate?.blocking || duplicate?.severity === 'blocking');
}

function hasDuplicateRisk(proposal: TestProposal) {
    return Boolean(proposal.review_context?.duplicate?.has_warning);
}

function getStalenessStatus(proposal: TestProposal) {
    const staleness = proposal.review_context?.staleness;
    if (staleness?.status) return staleness.status;
    return staleness?.is_stale ? 'stale' : 'fresh';
}

function proposalMatchesReviewFilter(proposal: TestProposal, filter: ProposalFilter) {
    if (filter === 'duplicate_risk') return hasDuplicateRisk(proposal);
    if (filter === 'blocking') return isBlockingDuplicate(proposal);
    if (filter === 'stale') return getStalenessStatus(proposal) === 'stale';
    if (filter === 'needs_review') return getStalenessStatus(proposal) === 'needs_review';
    if (filter === 'validation_failed') return (proposal.validation_status || '').toLowerCase() === 'failed';
    if (filter === 'blocked') return (proposal.validation_status || '').toLowerCase() === 'blocked';
    return true;
}

function proposalFilterLabel(filter: ProposalFilter) {
    return filter.replace(/_/g, ' ');
}

function normalizeWorkItems(data: unknown): WorkItem[] {
    if (Array.isArray(data)) return data as WorkItem[];
    if (data && typeof data === 'object') {
        const payload = data as { work_items?: unknown; items?: unknown };
        if (Array.isArray(payload.work_items)) return payload.work_items as WorkItem[];
        if (Array.isArray(payload.items)) return payload.items as WorkItem[];
    }
    return [];
}

function normalizeTeamTimeline(data: unknown): TeamTimelineItem[] {
    if (Array.isArray(data)) return data as TeamTimelineItem[];
    if (data && typeof data === 'object') {
        const payload = data as { team_timeline?: unknown; timeline?: unknown; items?: unknown; work_items?: unknown };
        const items = [payload.team_timeline, payload.timeline, payload.items, payload.work_items].find(Array.isArray);
        if (Array.isArray(items)) return items as TeamTimelineItem[];
    }
    return [];
}

function workItemToTeamTimelineItem(item: WorkItem): TeamTimelineItem {
    return {
        id: item.id,
        work_item_id: item.id,
        mission_id: item.mission_id,
        role: item.owner_agent || item.lane || null,
        owner_agent: item.owner_agent,
        title: item.title,
        summary: item.summary,
        status: item.status || item.lane || 'open',
        latest_event: item.progress?.message || item.progress?.phase
            ? asCompactText(item.progress?.message || item.progress?.phase, '')
            : null,
        output_preview: getFinalWorkItemOutput(item),
        blocker: item.blocked_reason || null,
        blocked_reason: item.blocked_reason,
        artifacts_count: item.artifacts?.length || 0,
        artifacts: item.artifacts,
        updated_at: item.updated_at,
        created_at: item.created_at,
    };
}

function splitTargetUrls(value: string): string[] {
    return value
        .split(/[\n,]/)
        .map(url => url.trim())
        .filter(Boolean);
}

function inferAllowedDomains(targetUrls: string[]) {
    const domains = new Set<string>();
    targetUrls.forEach(rawUrl => {
        try {
            const url = new URL(rawUrl);
            if (url.hostname) domains.add(url.hostname);
        } catch {
            // Backend validation reports malformed URLs with the final payload.
        }
    });
    return Array.from(domains);
}

function splitDomains(value: string, targetUrls: string[]) {
    const configured = value
        .split(/[\n,]/)
        .map(domain => domain.trim().toLowerCase())
        .filter(Boolean);
    return configured.length > 0 ? configured : inferAllowedDomains(targetUrls);
}

function formatDate(value?: string | null) {
    if (!value) return '-';
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? '-' : dateFormatter.format(date);
}

function formatCurrency(value: number) {
    return currencyFormatter.format(value || 0);
}

function formatLimit(value?: number | null) {
    return value === 0 ? 'Unlimited' : String(value ?? '-');
}

function formatMissionType(value: string) {
    return value.replace(/_/g, ' ');
}

function getMissionStatusText(status: Mission['status']) {
    if (typeof status === 'string') return status;
    return status.status || status.state || status.value || 'unknown';
}

function getMissionStatusDetails(mission: Mission): MissionStatusDetails {
    return typeof mission.status === 'object' && mission.status ? mission.status : {};
}

function getMissionField(mission: Mission, field: keyof Pick<MissionStatusDetails, 'team_summary' | 'active_work_items' | 'blocked_work_items' | 'coverage_summary'>) {
    return mission[field] ?? getMissionStatusDetails(mission)[field];
}

function getStatusStyle(status: Mission['status'] | string | null | undefined) {
    const normalized = getMissionStatusText(status || 'unknown').toLowerCase();
    if (['running', 'active'].includes(normalized)) {
        return { color: 'var(--primary)', background: 'var(--primary-glow)' };
    }
    if (['paused', 'waiting_approval'].includes(normalized)) {
        return { color: 'var(--warning)', background: 'var(--warning-muted)' };
    }
    if (['cancelled', 'failed', 'error'].includes(normalized)) {
        return { color: 'var(--danger)', background: 'var(--danger-muted)' };
    }
    if (['completed', 'success'].includes(normalized)) {
        return { color: 'var(--success)', background: 'var(--success-muted)' };
    }
    return { color: 'var(--text-secondary)', background: 'rgba(128,128,128,0.12)' };
}

function getHealthStyle(status?: string | null) {
    const normalized = (status || 'healthy').toLowerCase();
    if (normalized === 'healthy') {
        return { color: 'var(--success)', background: 'var(--success-muted)' };
    }
    if (normalized === 'degraded') {
        return { color: 'var(--warning)', background: 'var(--warning-muted)' };
    }
    if (normalized === 'blocked' || normalized === 'offline') {
        return { color: 'var(--danger)', background: 'var(--danger-muted)' };
    }
    return { color: 'var(--text-secondary)', background: 'rgba(128,128,128,0.12)' };
}

function formatReason(value?: string | null) {
    return value ? value.replace(/_/g, ' ') : null;
}

function getRiskStyle(risk: string) {
    const normalized = risk.toLowerCase();
    if (normalized === 'high') {
        return { color: 'var(--danger)', background: 'var(--danger-muted)' };
    }
    if (normalized === 'medium') {
        return { color: 'var(--warning)', background: 'var(--warning-muted)' };
    }
    if (normalized === 'low') {
        return { color: 'var(--success)', background: 'var(--success-muted)' };
    }
    return { color: 'var(--text-secondary)', background: 'rgba(128,128,128,0.12)' };
}

function canStart(status: Mission['status']) {
    return ['draft', 'created', 'idle', 'scheduled', 'completed', 'failed', 'error', 'cancelled'].includes(getMissionStatusText(status).toLowerCase());
}

function canPause(status: Mission['status']) {
    return ['running', 'active'].includes(getMissionStatusText(status).toLowerCase());
}

function canResume(status: Mission['status']) {
    return getMissionStatusText(status).toLowerCase() === 'paused';
}

function canCancel(status: Mission['status']) {
    return !['cancelled', 'completed'].includes(getMissionStatusText(status).toLowerCase());
}

function getProposalTarget(proposal: TestProposal) {
    return proposal.target_url || proposal.target_route || proposal.route || '-';
}

function getLinkedProposalId(finding: AppChangeFinding) {
    return finding.test_proposal_id
        || finding.linked_proposal_id
        || finding.proposal_id
        || finding.test_proposal?.id
        || finding.proposal?.id
        || null;
}

function getLinkedProposalStatus(finding: AppChangeFinding, proposal?: TestProposal | null) {
    return proposal?.approval_status
        || finding.test_proposal_status
        || finding.proposal_status
        || finding.test_proposal?.approval_status
        || finding.proposal?.approval_status
        || null;
}

function getFindingTruthState(finding: AppChangeFinding) {
    return finding.truth_state
        || asCompactText(finding.memory_delta?.truth_state, '')
        || asCompactText(finding.app_change?.truth_state, '')
        || null;
}

function getRequirementLabel(finding: AppChangeFinding) {
    if (finding.requirement_title) return finding.requirement_title;
    if (typeof finding.requirement === 'string') return finding.requirement;
    if (finding.requirement && typeof finding.requirement === 'object') {
        const record = finding.requirement as Record<string, unknown>;
        return asCompactText(record.title || record.name || record.statement || record.description, '');
    }
    return '';
}

function compactSpecPreview(content?: string | null) {
    if (!content) return 'No generated spec preview available.';
    const compact = content.replace(/\s+/g, ' ').trim();
    return compact.length > 260 ? `${compact.slice(0, 260)}...` : compact;
}

function asCompactText(value: unknown, fallback = '-'): string {
    if (value === null || value === undefined || value === '') return fallback;
    if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') return String(value);
    if (Array.isArray(value)) {
        if (value.length === 0) return fallback;
        return value
            .slice(0, 3)
            .map(item => asCompactText(item, ''))
            .filter(Boolean)
            .join(', ');
    }
    if (typeof value === 'object') {
        const record = value as Record<string, unknown>;
        return String(record.summary || record.label || record.title || record.description || Object.entries(record)
            .slice(0, 3)
            .map(([key, item]) => `${key}: ${asCompactText(item, '')}`)
            .join(', ') || fallback);
    }
    return fallback;
}

function clampText(value: unknown, fallback = '-', maxLength = 96) {
    const text = asCompactText(value, fallback).replace(/\s+/g, ' ').trim();
    if (!text || text === fallback) return fallback;
    return text.length > maxLength ? `${text.slice(0, maxLength - 3).trim()}...` : text;
}

function getMissionPrimaryTarget(mission: Mission) {
    const firstTarget = mission.target_urls?.[0];
    if (!firstTarget) return 'No target configured';
    const extraCount = (mission.target_urls?.length || 0) - 1;
    return extraCount > 0 ? `${firstTarget} +${extraCount}` : firstTarget;
}

function toggleSetItem(current: Set<string>, id: string) {
    const next = new Set(current);
    if (next.has(id)) {
        next.delete(id);
    } else {
        next.add(id);
    }
    return next;
}

function getWorkItemCount(value: unknown) {
    if (Array.isArray(value)) return value.length;
    if (typeof value === 'number') return value;
    if (value && typeof value === 'object') {
        const record = value as Record<string, unknown>;
        const count = record.count ?? record.total;
        if (typeof count === 'number') return count;
        if (Array.isArray(record.items)) return record.items.length;
    }
    return 0;
}

function getTeamSummaryMetric(value: unknown, key: string) {
    if (!value || typeof value !== 'object') return 0;
    const record = value as Record<string, unknown>;
    const metric = record[key];
    if (typeof metric === 'number') return metric;
    if (typeof metric === 'string') {
        const parsed = Number(metric);
        return Number.isFinite(parsed) ? parsed : 0;
    }
    return 0;
}

function getTeamSummaryFlag(value: unknown, key: string) {
    if (!value || typeof value !== 'object') return false;
    return Boolean((value as Record<string, unknown>)[key]);
}

function eventLabel(value: string) {
    return value.replace(/_/g, ' ');
}

function getEventTone(event: AgentEvent) {
    if (event.level === 'error' || event.event_type === 'error') return 'danger';
    if (event.event_type === 'browser_action') return 'primary';
    if (event.event_type === 'pause') return 'warning';
    if (event.event_type === 'resume' || event.event_type === 'complete') return 'success';
    return 'neutral';
}

function getEventStatusStyle(event: AgentEvent) {
    const tone = getEventTone(event);
    if (tone === 'danger') return getStatusStyle('failed');
    if (tone === 'warning') return getStatusStyle('paused');
    if (tone === 'success') return getStatusStyle('completed');
    if (tone === 'primary') return getStatusStyle('running');
    return getStatusStyle('unknown');
}

function buildEventOutput(events: AgentEvent[]) {
    return events
        .filter(event => event.event_type === 'assistant_output')
        .map(event => event.message)
        .join('\n\n');
}

function getFinalWorkItemOutput(item: WorkItem) {
    const resultOutput = item.result?.output;
    if (typeof resultOutput === 'string' && resultOutput.trim()) return resultOutput;
    const artifact = item.artifacts?.find(entry => typeof entry.content === 'string' && entry.content.trim());
    return typeof artifact?.content === 'string' ? artifact.content : '';
}

function getTimelineItemId(item: TeamTimelineItem) {
    return item.work_item_id || item.id || null;
}

function getTimelineRole(item: TeamTimelineItem) {
    return item.role || item.owner_agent || 'agent';
}

function getTimelineArtifactCount(item: TeamTimelineItem) {
    if (typeof item.artifacts_count === 'number') return item.artifacts_count;
    return item.artifacts?.length || 0;
}

function getTimelineOutputPreview(item: TeamTimelineItem) {
    return item.output_preview || '';
}

function getTimelineReviewField(item: TeamTimelineItem, field: 'decision' | 'reason' | 'reviewed_at' | 'reviewed_by') {
    const key = field === 'decision' ? 'review_decision' : field === 'reason' ? 'review_reason' : field;
    return asCompactText(
        item[key as keyof TeamTimelineItem]
            || item.review?.[key]
            || item.review?.[field]
            || item.review_metadata?.[key]
            || item.review_metadata?.[field],
        ''
    );
}

function getTimelineRevisionField(item: TeamTimelineItem, field: 'revision_of_work_item_id' | 'revision_work_item_id') {
    return asCompactText(
        item[field]
            || item.result?.[field]
            || item.progress?.[field]
            || item.review?.[field]
            || item.review_metadata?.[field],
        ''
    );
}

function getTimelineRecoveryField(item: TeamTimelineItem, field: 'planner_key' | 'recovery_reason' | 'recovered_from_work_item_id') {
    return asCompactText(
        item[field as keyof TeamTimelineItem]
            || item.result?.[field]
            || item.progress?.[field],
        ''
    );
}

function canRetryWorkItemStatus(status?: string | null) {
    return ['failed', 'blocked', 'cancelled', 'error', 'timeout'].includes((status || '').toLowerCase());
}

function canCancelWorkItemStatus(status?: string | null) {
    return ['queued', 'running', 'active', 'open'].includes((status || '').toLowerCase());
}

function canReviewWorkItemStatus(status?: string | null) {
    return ['completed', 'done', 'success'].includes((status || '').toLowerCase());
}

function getFindingId(finding: AppChangeFinding) {
    return finding.id === null || finding.id === undefined ? null : String(finding.id);
}

function appChangeStatusFilterLabel(filter: AppChangeStatusFilter) {
    if (filter === 'active') return 'active';
    return filter.replace(/_/g, ' ');
}

function appChangeMatchesStatusFilter(finding: AppChangeFinding, filter: AppChangeStatusFilter) {
    const status = (finding.status || 'awaiting_approval').toLowerCase();
    if (filter === 'all') return true;
    if (filter === 'active') return !hiddenAppChangeStatuses.has(status);
    return status === filter;
}

function parseSseMessages(buffer: string) {
    const chunks = buffer.split('\n\n');
    return {
        messages: chunks.slice(0, -1),
        remainder: chunks[chunks.length - 1] || '',
    };
}

export default function AutonomousMissionsPage() {
    const { currentProject, isLoading: projectLoading } = useProject();
    const projectId = currentProject?.id || getStoredProjectId() || 'default';
    const encodedProjectId = encodeURIComponent(projectId);
    const missionsUrl = `${API_BASE}/autonomous/${encodedProjectId}/missions`;
    const proposalsUrl = `${API_BASE}/autonomous/${encodedProjectId}/proposals`;
    const workItemsUrl = `${API_BASE}/autonomous/${encodedProjectId}/work-items?limit=8`;

    const [missions, setMissions] = useState<Mission[]>([]);
    const [approvals, setApprovals] = useState<Approval[]>([]);
    const [proposals, setProposals] = useState<TestProposal[]>([]);
    const [workItems, setWorkItems] = useState<WorkItem[]>([]);
    const [teamTimelineItems, setTeamTimelineItems] = useState<TeamTimelineItem[]>([]);
    const [teamTimelineLoading, setTeamTimelineLoading] = useState(false);
    const [teamTimelineError, setTeamTimelineError] = useState<string | null>(null);
    const [teamTimelineFallback, setTeamTimelineFallback] = useState(false);
    const [appChangeGroups, setAppChangeGroups] = useState<AppChangeGroup[]>([]);
    const [appChangesLoading, setAppChangesLoading] = useState(false);
    const [appChangesError, setAppChangesError] = useState<string | null>(null);
    const [appChangeStatusFilter, setAppChangeStatusFilter] = useState<AppChangeStatusFilter>('active');
    const [appChangeComments, setAppChangeComments] = useState<Record<string, string>>({});
    const [workItemReviewReasons, setWorkItemReviewReasons] = useState<Record<string, string>>({});
    const [proposalFilter, setProposalFilter] = useState<ProposalFilter>(getInitialProposalFilter);
    const [proposalLoadError, setProposalLoadError] = useState<string | null>(null);
    const [approvalsLoadError, setApprovalsLoadError] = useState<string | null>(null);
    const [materializeProposal, setMaterializeProposal] = useState<TestProposal | null>(null);
    const [materializePath, setMaterializePath] = useState('');
    const [materializeOverwrite, setMaterializeOverwrite] = useState(false);
    const [materializeOverrideDuplicate, setMaterializeOverrideDuplicate] = useState(false);
    const [materializeOverrideReason, setMaterializeOverrideReason] = useState('');
    const [auditProposal, setAuditProposal] = useState<TestProposal | null>(null);
    const [auditDetail, setAuditDetail] = useState<ProposalAudit | null>(null);
    const [auditLoading, setAuditLoading] = useState(false);
    const [reviewRefreshing, setReviewRefreshing] = useState<string | null>(null);
    const [diagnostics, setDiagnostics] = useState<AutonomousDiagnostics | null>(null);
    const [diagnosticsLoading, setDiagnosticsLoading] = useState(false);
    const [loading, setLoading] = useState(true);
    const [refreshing, setRefreshing] = useState(false);
    const [showCreate, setShowCreate] = useState(false);
    const [createStep, setCreateStep] = useState(1);
    const [form, setForm] = useState<MissionForm>(DEFAULT_FORM);
    const [formErrors, setFormErrors] = useState<FormErrors>({});
    const [selectedTemplateLabel, setSelectedTemplateLabel] = useState(QUICK_START_TEMPLATES[0]?.label || '');
    const [expandedMissionIds, setExpandedMissionIds] = useState<Set<string>>(new Set());
    const [expandedProposalIds, setExpandedProposalIds] = useState<Set<string>>(new Set());
    const [selectedMissionId, setSelectedMissionId] = useState<string | null>(null);
    const [liveTab, setLiveTab] = useState<LiveTab>('live');
    const [missionEvents, setMissionEvents] = useState<AgentEvent[]>([]);
    const [streamStatus, setStreamStatus] = useState<'idle' | 'connecting' | 'connected' | 'closed' | 'error'>('idle');
    const [streamError, setStreamError] = useState<string | null>(null);
    const [creating, setCreating] = useState(false);
    const [actionLoading, setActionLoading] = useState<string | null>(null);
    const [error, setError] = useState<string | null>(null);

    const fetchMissions = useCallback(async () => {
        setError(null);
        try {
            const response = await fetchWithAuth(missionsUrl);
            if (!response.ok) {
                throw new Error(await response.text() || 'Failed to load missions');
            }
            const data = await response.json();
            setMissions(normalizeMissions(data));
        } catch (err) {
            console.error('Failed to load autonomous missions:', err);
            setError(err instanceof Error ? err.message : 'Failed to load missions');
        }
    }, [missionsUrl]);

    const fetchApprovals = useCallback(async () => {
        setApprovalsLoadError(null);
        try {
            const response = await fetchWithAuth(`${API_BASE}/autonomous/${encodedProjectId}/approvals?status=pending`);
            if (!response.ok) {
                throw new Error(await response.text() || 'Failed to load approvals');
            }
            const data = await response.json();
            setApprovals(Array.isArray(data) ? data : []);
        } catch (err) {
            console.error('Failed to load autonomous approvals:', err);
            setApprovalsLoadError(err instanceof Error ? err.message : 'Failed to load approvals');
        }
    }, [encodedProjectId]);

    const fetchProposals = useCallback(async () => {
        setProposalLoadError(null);
        try {
            const url = proposalStatusFilters.has(proposalFilter) ? `${proposalsUrl}?status=${proposalFilter}` : proposalsUrl;
            const response = await fetchWithAuth(url);
            if (!response.ok) {
                throw new Error(await response.text() || 'Failed to load generated test proposals');
            }
            const data = await response.json();
            const normalized = normalizeProposals(data);
            setProposals(proposalReviewFilters.has(proposalFilter)
                ? normalized.filter(proposal => proposalMatchesReviewFilter(proposal, proposalFilter))
                : normalized);
        } catch (err) {
            console.error('Failed to load autonomous test proposals:', err);
            setProposalLoadError(err instanceof Error ? err.message : 'Failed to load generated test proposals');
        }
    }, [proposalFilter, proposalsUrl]);

    const fetchDiagnostics = useCallback(async () => {
        try {
            const response = await fetchWithAuth(`${API_BASE}/autonomous/${encodedProjectId}/diagnostics`);
            if (!response.ok) {
                throw new Error(await response.text() || 'Failed to load autonomous diagnostics');
            }
            setDiagnostics(await response.json());
        } catch (err) {
            console.error('Failed to load autonomous diagnostics:', err);
        }
    }, [encodedProjectId]);

    const fetchWorkItems = useCallback(async () => {
        try {
            const response = await fetchWithAuth(workItemsUrl);
            if (response.status === 404 || response.status === 405) {
                setWorkItems([]);
                return;
            }
            if (!response.ok) {
                throw new Error(await response.text() || 'Failed to load work items');
            }
            const data = await response.json();
            setWorkItems(normalizeWorkItems(data));
        } catch (err) {
            console.error('Failed to load autonomous work items:', err);
            setWorkItems([]);
        }
    }, [workItemsUrl]);

    const fetchAppChanges = useCallback(async (missionId: string) => {
        setAppChangesLoading(true);
        setAppChangesError(null);
        try {
            const response = await fetchWithAuth(`${missionsUrl}/${encodeURIComponent(missionId)}/app-changes`);
            if (response.status === 404 || response.status === 405) {
                setAppChangeGroups([]);
                return;
            }
            if (!response.ok) {
                throw new Error(await response.text() || 'Failed to load app changes');
            }
            const data = await response.json();
            setAppChangeGroups(normalizeAppChanges(data));
        } catch (err) {
            console.error('Failed to load autonomous app changes:', err);
            setAppChangesError(err instanceof Error ? err.message : 'Failed to load app changes');
            setAppChangeGroups([]);
        } finally {
            setAppChangesLoading(false);
        }
    }, [missionsUrl]);

    const fetchTeamTimeline = useCallback(async (missionId: string, fallbackWorkItems: WorkItem[]) => {
        setTeamTimelineLoading(true);
        setTeamTimelineError(null);
        setTeamTimelineFallback(false);
        try {
            const response = await fetchWithAuth(`${missionsUrl}/${encodeURIComponent(missionId)}/team-timeline`);
            if (response.status === 404 || response.status === 405) {
                setTeamTimelineItems(fallbackWorkItems.map(workItemToTeamTimelineItem));
                setTeamTimelineFallback(true);
                return;
            }
            if (!response.ok) {
                throw new Error(await response.text() || 'Failed to load team timeline');
            }
            const data = await response.json();
            setTeamTimelineItems(normalizeTeamTimeline(data));
        } catch (err) {
            console.error('Failed to load autonomous team timeline:', err);
            setTeamTimelineError(err instanceof Error ? err.message : 'Failed to load team timeline');
            setTeamTimelineItems(fallbackWorkItems.map(workItemToTeamTimelineItem));
            setTeamTimelineFallback(true);
        } finally {
            setTeamTimelineLoading(false);
        }
    }, [missionsUrl]);

    const refreshAll = useCallback(async () => {
        await Promise.all([fetchMissions(), fetchApprovals(), fetchProposals(), fetchWorkItems(), fetchDiagnostics()]);
    }, [fetchApprovals, fetchDiagnostics, fetchMissions, fetchProposals, fetchWorkItems]);

    useEffect(() => {
        setLoading(true);
        refreshAll().finally(() => setLoading(false));
    }, [refreshAll]);

    useEffect(() => {
        if (!selectedMissionId) {
            setMissionEvents([]);
            setStreamStatus('idle');
            setStreamError(null);
            setAppChangeGroups([]);
            setAppChangesError(null);
            setTeamTimelineItems([]);
            setTeamTimelineError(null);
            setTeamTimelineFallback(false);
            return;
        }

        const controller = new AbortController();
        let cancelled = false;
        const missionId = selectedMissionId;

        async function connectEventStream() {
            setMissionEvents([]);
            setStreamStatus('connecting');
            setStreamError(null);
            try {
                const response = await fetchWithAuth(
                    `${missionsUrl}/${encodeURIComponent(missionId)}/events/stream`,
                    { signal: controller.signal }
                );
                if (!response.ok) {
                    throw new Error(await response.text() || 'Failed to connect to mission event stream');
                }
                if (!response.body) {
                    throw new Error('Mission event stream is unavailable');
                }

                setStreamStatus('connected');
                const reader = response.body.getReader();
                const decoder = new TextDecoder();
                let buffer = '';

                while (!cancelled) {
                    const { done, value } = await reader.read();
                    if (done) break;
                    buffer += decoder.decode(value, { stream: true });
                    const parsed = parseSseMessages(buffer);
                    buffer = parsed.remainder;
                    parsed.messages.forEach(message => {
                        const dataLine = message
                            .split('\n')
                            .find(line => line.startsWith('data:'));
                        if (!dataLine) return;
                        try {
                            const payload = JSON.parse(dataLine.slice(5).trim());
                            if (payload.status === 'connected') {
                                setStreamStatus('connected');
                            } else if (payload.status === 'complete') {
                                setStreamStatus('closed');
                            } else if (payload.status === 'error') {
                                setStreamStatus('error');
                                setStreamError(payload.message || 'Mission event stream failed');
                            } else if (payload.event) {
                                const event = payload.event as AgentEvent;
                                setMissionEvents(prev => {
                                    if (prev.some(existing => existing.id === event.id)) return prev;
                                    return [...prev, event].sort((a, b) => a.sequence - b.sequence).slice(-500);
                                });
                            }
                        } catch (err) {
                            console.error('Failed to parse autonomous event stream payload:', err);
                        }
                    });
                }
                if (!cancelled) setStreamStatus(current => current === 'connected' ? 'closed' : current);
            } catch (err) {
                if (controller.signal.aborted || cancelled) return;
                console.error('Autonomous event stream failed:', err);
                setStreamStatus('error');
                setStreamError(err instanceof Error ? err.message : 'Mission event stream failed');
            }
        }

        connectEventStream();
        return () => {
            cancelled = true;
            controller.abort();
        };
    }, [missionsUrl, selectedMissionId]);

    useEffect(() => {
        if (!selectedMissionId) return;
        void fetchAppChanges(selectedMissionId);
    }, [fetchAppChanges, selectedMissionId]);

    useEffect(() => {
        if (!selectedMissionId) return;
        const fallbackWorkItems = workItems.filter(item => item.mission_id === selectedMissionId);
        void fetchTeamTimeline(selectedMissionId, fallbackWorkItems);
    }, [fetchTeamTimeline, selectedMissionId, workItems]);

    useEffect(() => {
        if (!showCreate && !materializeProposal && !auditProposal) return;
        const handleKeyDown = (event: KeyboardEvent) => {
            if (event.key === 'Escape') {
                setShowCreate(false);
                setMaterializeProposal(null);
                setMaterializeOverrideDuplicate(false);
                setMaterializeOverrideReason('');
                setAuditProposal(null);
                setAuditDetail(null);
            }
        };
        window.addEventListener('keydown', handleKeyDown);
        return () => window.removeEventListener('keydown', handleKeyDown);
    }, [auditProposal, materializeProposal, showCreate]);

    const handleRefresh = async () => {
        setRefreshing(true);
        await refreshAll().finally(() => setRefreshing(false));
    };

    const handleDiagnosticsAction = async (action: 'monitor' | 'recover' | 'backfill-dry-run' | 'backfill') => {
        setDiagnosticsLoading(true);
        setError(null);
        const endpoint = action === 'monitor'
            ? 'monitor'
            : action === 'recover'
                ? 'recover'
                : `backfill?dry_run=${action === 'backfill-dry-run' ? 'true' : 'false'}`;
        try {
            const response = await fetchWithAuth(`${API_BASE}/autonomous/${encodedProjectId}/diagnostics/${endpoint}`, {
                method: 'POST',
            });
            if (!response.ok) {
                throw new Error(await response.text() || 'Failed to run diagnostics action');
            }
            const data = await response.json();
            setDiagnostics((data.diagnostics || data) as AutonomousDiagnostics);
            await refreshAll();
        } catch (err) {
            console.error('Failed to run autonomous diagnostics action:', err);
            setError(err instanceof Error ? err.message : 'Failed to run diagnostics action');
        } finally {
            setDiagnosticsLoading(false);
        }
    };

    const handleRefreshReviews = async () => {
        setReviewRefreshing('all');
        setError(null);
        try {
            const response = await fetchWithAuth(`${API_BASE}/autonomous/${encodedProjectId}/proposals/refresh-reviews`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ limit: 200 }),
            });
            if (!response.ok) {
                throw new Error(await response.text() || 'Failed to refresh proposal reviews');
            }
            await refreshAll();
        } catch (err) {
            console.error('Failed to refresh autonomous proposal reviews:', err);
            setError(err instanceof Error ? err.message : 'Failed to refresh proposal reviews');
        } finally {
            setReviewRefreshing(null);
        }
    };

    const handleRefreshProposalReview = async (proposal: TestProposal) => {
        setReviewRefreshing(proposal.id);
        setError(null);
        try {
            const response = await fetchWithAuth(`${API_BASE}/autonomous/${encodedProjectId}/proposals/${encodeURIComponent(proposal.id)}/refresh-review`, {
                method: 'POST',
            });
            if (!response.ok) {
                throw new Error(await response.text() || 'Failed to refresh proposal review');
            }
            await refreshAll();
        } catch (err) {
            console.error('Failed to refresh autonomous proposal review:', err);
            setError(err instanceof Error ? err.message : 'Failed to refresh proposal review');
        } finally {
            setReviewRefreshing(null);
        }
    };

    const handleProposalFilterChange = (filter: ProposalFilter) => {
        setProposalFilter(filter);
        if (typeof window === 'undefined') return;
        const params = new URLSearchParams(window.location.search);
        if (filter === 'pending') {
            params.delete('proposalStatus');
        } else {
            params.set('proposalStatus', filter);
        }
        const query = params.toString();
        window.history.replaceState(null, '', `${window.location.pathname}${query ? `?${query}` : ''}`);
    };

    const applyMissionTemplate = (template: typeof QUICK_START_TEMPLATES[number]) => {
        setForm(prev => ({
            ...prev,
            name: prev.name || `${template.label} mission`,
            mission_type: template.mission_type,
            description: prev.description || template.description,
            schedule_cron: template.schedule_cron,
            timezone: 'UTC',
            max_runtime_minutes: template.max_runtime_minutes,
            max_iterations: template.max_iterations,
            max_llm_budget_usd: template.max_llm_budget_usd,
        }));
        setFormErrors({});
        setSelectedTemplateLabel(template.label);
        setCreateStep(2);
        setShowCreate(true);
    };

    const totals = useMemo(() => {
        return missions.reduce(
            (acc, mission) => {
                acc.runs += mission.total_runs || 0;
                acc.findings += mission.total_findings || 0;
                acc.budget += mission.budget_used_usd || 0;
                if (canPause(mission.status)) acc.running += 1;
                acc.activeWorkItems += getWorkItemCount(getMissionField(mission, 'active_work_items'));
                acc.blockedWorkItems += getWorkItemCount(getMissionField(mission, 'blocked_work_items'));
                return acc;
            },
            { runs: 0, findings: 0, budget: 0, running: 0, activeWorkItems: 0, blockedWorkItems: 0 }
        );
    }, [missions]);

    const hasMissions = missions.length > 0;
    const selectedMission = missions.find(mission => mission.id === selectedMissionId) || null;
    const selectedMissionWorkItems = workItems.filter(item => item.mission_id === selectedMissionId);
    const selectedMissionActiveWorkItems = selectedMissionWorkItems.filter(item => ['queued', 'running'].includes((item.status || '').toLowerCase()));
    const filteredAppChangeGroups = appChangeGroups
        .map(group => ({
            ...group,
            findings: group.findings.filter(finding => appChangeMatchesStatusFilter(finding, appChangeStatusFilter)),
        }))
        .filter(group => group.findings.length > 0);
    const visibleAppChangeCount = filteredAppChangeGroups.reduce((count, group) => count + group.findings.length, 0);
    const totalAppChangeCount = appChangeGroups.reduce((count, group) => count + group.findings.length, 0);
    const selectedMissionFinalOutputs = selectedMissionWorkItems
        .map(item => ({ item, output: getFinalWorkItemOutput(item) }))
        .filter(entry => entry.output.trim());
    const latestEvent = missionEvents[missionEvents.length - 1];
    const liveAgentOutput = buildEventOutput(missionEvents);
    const latestBrowserEvent = [...missionEvents].reverse().find(event => event.event_type === 'browser_action');
    const selectedTemplate = QUICK_START_TEMPLATES.find(template => template.label === selectedTemplateLabel)
        || QUICK_START_TEMPLATES.find(template => template.mission_type === form.mission_type)
        || QUICK_START_TEMPLATES[0];
    const degradedMissions = missions.filter(mission => {
        const health = (mission.health_status || 'healthy').toLowerCase();
        return health !== 'healthy' || Boolean(mission.last_error) || Boolean(mission.paused_reason);
    });
    const approvedProposals = proposals.filter(proposal => (proposal.approval_status || '').toLowerCase() === 'approved');
    const dashboardStats = [
        { label: 'Running', value: totals.running, icon: <Play size={16} /> },
        { label: 'Blocked', value: totals.blockedWorkItems, icon: <AlertCircle size={16} /> },
        { label: 'Approvals', value: approvals.length, icon: <CheckCircle size={16} /> },
        { label: 'Proposals', value: proposals.length, icon: <FileText size={16} /> },
        { label: 'Budget', value: formatCurrency(totals.budget), icon: <DollarSign size={16} /> },
    ];
    const attentionItems = [
        {
            label: 'Pending approvals',
            value: approvals.length,
            detail: approvals.length > 0 ? 'Approve or reject requested actions' : 'No approval queue',
            icon: <CheckCircle size={16} />,
            tone: approvals.length > 0 ? 'warning' : 'neutral',
        },
        {
            label: 'Blocked work',
            value: totals.blockedWorkItems,
            detail: totals.blockedWorkItems > 0 ? 'Agent lanes need review' : 'No blockers reported',
            icon: <AlertCircle size={16} />,
            tone: totals.blockedWorkItems > 0 ? 'danger' : 'neutral',
        },
        {
            label: 'Mission health',
            value: degradedMissions.length,
            detail: degradedMissions.length > 0 ? 'Missions need attention' : 'All missions healthy',
            icon: <ShieldCheck size={16} />,
            tone: degradedMissions.length > 0 ? 'warning' : 'neutral',
        },
        {
            label: 'Ready to materialize',
            value: approvedProposals.length,
            detail: approvedProposals.length > 0 ? 'Approved tests can become files' : 'Nothing ready',
            icon: <UploadCloud size={16} />,
            tone: approvedProposals.length > 0 ? 'primary' : 'neutral',
        },
    ];

    const handleCreate = async (event: FormEvent) => {
        event.preventDefault();
        const targetUrls = splitTargetUrls(form.target_urls);
        const nextFormErrors: FormErrors = {};
        if (!form.name.trim()) {
            nextFormErrors.name = 'Give this mission a short, recognizable name.';
        }
        if (targetUrls.length === 0) {
            nextFormErrors.target_urls = 'Add at least one URL the backend can reach.';
        }
        setFormErrors(nextFormErrors);
        if (Object.keys(nextFormErrors).length > 0) {
            setError(null);
            return;
        }

        setCreating(true);
        setError(null);
        try {
            const isWholeAppTeam = selectedTemplate?.label === 'Whole App Team';
            const safetyConfig = {
                environment: form.environment || 'staging',
                allowed_domains: splitDomains(form.allowed_domains, targetUrls),
                tool_profile: form.tool_profile || 'role_based',
                credential_scope: form.credential_scope || 'project',
                write_policy: 'proposals_only',
            };
            const payload = {
                name: form.name.trim(),
                description: form.description.trim() || undefined,
                mission_type: form.mission_type,
                target_urls: targetUrls,
                schedule_cron: form.schedule_cron.trim() || undefined,
                timezone: form.timezone || 'UTC',
                max_runtime_minutes: form.max_runtime_minutes,
                max_iterations: form.max_iterations,
                max_llm_budget_usd: form.max_llm_budget_usd,
                autonomy_level: 'draft_validate',
                approval_policy: 'approval_required',
                config: {
                    ...safetyConfig,
                    ...(isWholeAppTeam ? {
                        whole_app_team: true,
                        team_mode: 'whole_app',
                        mission_template: 'whole_app_team',
                        max_parallel_agents: 2,
                        loop_delay_seconds: 300,
                        max_pending_approvals: 25,
                        roles: [
                            'surface_mapper',
                            'explorer',
                            'requirements_analyst',
                            'rtm_mapper',
                            'spec_writer',
                            'regression_scout',
                            'flake_triager',
                        ],
                        completion_target: {
                            rtm_coverage_percentage: 95,
                            critical_gaps: 0,
                        },
                    } : {}),
                },
            };

            const response = await fetchWithAuth(missionsUrl, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });
            if (!response.ok) {
                throw new Error(await response.text() || 'Failed to create mission');
            }
            setForm(DEFAULT_FORM);
            setFormErrors({});
            setSelectedTemplateLabel(QUICK_START_TEMPLATES[0]?.label || '');
            setCreateStep(1);
            setShowCreate(false);
            await refreshAll();
        } catch (err) {
            console.error('Failed to create autonomous mission:', err);
            setError(err instanceof Error ? err.message : 'Failed to create mission');
        } finally {
            setCreating(false);
        }
    };

    const handleMissionAction = async (mission: Mission, action: 'start' | 'pause' | 'resume' | 'cancel') => {
        const label = `${mission.id}:${action}`;
        setActionLoading(label);
        setError(null);
        try {
            const response = await fetchWithAuth(`${missionsUrl}/${encodeURIComponent(mission.id)}/${action}`, {
                method: 'POST',
            });
            if (!response.ok) {
                throw new Error(await response.text() || `Failed to ${action} mission`);
            }
            await refreshAll();
        } catch (err) {
            console.error(`Failed to ${action} autonomous mission:`, err);
            setError(err instanceof Error ? err.message : `Failed to ${action} mission`);
        } finally {
            setActionLoading(null);
        }
    };

    const handleApproval = async (approval: Approval, decision: 'approve' | 'reject') => {
        const label = `${approval.id}:${decision}`;
        setActionLoading(label);
        setError(null);
        try {
            const response = await fetchWithAuth(`${API_BASE}/autonomous/${encodedProjectId}/approvals/${approval.id}/${decision}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ comment: `Decision from Autonomous Missions dashboard: ${decision}` }),
            });
            if (!response.ok) {
                throw new Error(await response.text() || `Failed to ${decision} approval`);
            }
            await refreshAll();
        } catch (err) {
            console.error(`Failed to ${decision} autonomous approval:`, err);
            setError(err instanceof Error ? err.message : `Failed to ${decision} approval`);
        } finally {
            setActionLoading(null);
        }
    };

    const handleProposalAction = async (proposal: TestProposal, action: 'approve' | 'reject') => {
        const label = `${proposal.id}:${action}`;
        setActionLoading(label);
        setError(null);
        try {
            const response = await fetchWithAuth(`${API_BASE}/autonomous/${encodedProjectId}/proposals/${encodeURIComponent(proposal.id)}/${action}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ comment: `Decision from Autonomous Missions dashboard: ${action}` }),
            });
            if (!response.ok) {
                throw new Error(await response.text() || `Failed to ${action} proposal`);
            }
            await refreshAll();
        } catch (err) {
            console.error(`Failed to ${action} autonomous test proposal:`, err);
            setError(err instanceof Error ? err.message : `Failed to ${action} proposal`);
        } finally {
            setActionLoading(null);
        }
    };

    const handleRequirementTruthAction = async (finding: AppChangeFinding, action: 'confirm' | 'reject' | 'mark-stale') => {
        if (!finding.requirement_id) return;
        const comment = action === 'confirm'
            ? ''
            : window.prompt(action === 'reject' ? 'Why should this requirement be rejected?' : 'Why is this requirement stale?', '')?.trim();
        if (action !== 'confirm' && !comment) return;

        const requirementId = String(finding.requirement_id);
        const label = `requirement:${requirementId}:${action}`;
        setActionLoading(label);
        setError(null);
        try {
            const response = await fetchWithAuth(`${API_BASE}/requirements/${encodeURIComponent(requirementId)}/${action}?project_id=${encodedProjectId}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(comment ? { comment } : {}),
            });
            if (!response.ok) {
                throw new Error(await response.text() || `Failed to ${action} requirement`);
            }
            if (selectedMissionId) await fetchAppChanges(selectedMissionId);
        } catch (err) {
            console.error(`Failed to ${action} requirement from app changes:`, err);
            setError(err instanceof Error ? err.message : `Failed to ${action} requirement`);
        } finally {
            setActionLoading(null);
        }
    };

    const handleAppChangeFindingAction = async (finding: AppChangeFinding, action: 'approve' | 'reject' | 'resolve') => {
        const findingId = getFindingId(finding);
        if (!findingId || !selectedMissionId) return;
        const comment = (appChangeComments[findingId] || '').trim();
        if ((action === 'reject' || action === 'resolve') && !comment) {
            setError(`${action === 'reject' ? 'Rejecting' : 'Resolving'} an app-change finding requires a comment.`);
            return;
        }

        const label = `app-change:${findingId}:${action}`;
        setActionLoading(label);
        setError(null);
        try {
            const response = await fetchWithAuth(`${API_BASE}/autonomous/${encodedProjectId}/missions/${encodeURIComponent(selectedMissionId)}/findings/${encodeURIComponent(findingId)}/${action}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(comment ? { comment } : {}),
            });
            if (!response.ok) {
                throw new Error(await response.text() || `Failed to ${action} finding`);
            }
            setAppChangeComments(prev => {
                const next = { ...prev };
                delete next[findingId];
                return next;
            });
            await fetchAppChanges(selectedMissionId);
            await refreshAll();
        } catch (err) {
            console.error(`Failed to ${action} autonomous app-change finding:`, err);
            setError(err instanceof Error ? err.message : `Failed to ${action} finding`);
        } finally {
            setActionLoading(null);
        }
    };

    const handleWorkItemAction = async (item: TeamTimelineItem, action: 'retry' | 'cancel') => {
        const workItemId = getTimelineItemId(item);
        if (!workItemId) return;
        const label = `work-item:${workItemId}:${action}`;
        setActionLoading(label);
        setError(null);
        try {
            const response = await fetchWithAuth(`${API_BASE}/autonomous/${encodedProjectId}/work-items/${encodeURIComponent(workItemId)}/${action}`, {
                method: 'POST',
            });
            if (!response.ok) {
                throw new Error(await response.text() || `Failed to ${action} work item`);
            }
            await refreshAll();
            if (selectedMissionId) {
                const fallbackWorkItems = workItems.filter(workItem => workItem.mission_id === selectedMissionId);
                await fetchTeamTimeline(selectedMissionId, fallbackWorkItems);
            }
        } catch (err) {
            console.error(`Failed to ${action} autonomous work item:`, err);
            setError(err instanceof Error ? err.message : `Failed to ${action} work item`);
        } finally {
            setActionLoading(null);
        }
    };

    const handleWorkItemReview = async (item: TeamTimelineItem, decision: 'accept' | 'reject' | 'needs_revision') => {
        const workItemId = getTimelineItemId(item);
        if (!workItemId) return;
        const reason = (workItemReviewReasons[workItemId] || '').trim();
        if ((decision === 'reject' || decision === 'needs_revision') && !reason) {
            setError(`${decision === 'reject' ? 'Rejecting' : 'Requesting revision for'} completed work requires a reason.`);
            return;
        }

        const action = decision === 'accept' ? 'accept' : decision === 'reject' ? 'reject' : 'needs-revision';
        const label = `work-item:${workItemId}:review:${decision}`;
        setActionLoading(label);
        setError(null);
        try {
            const response = await fetchWithAuth(`${API_BASE}/autonomous/${encodedProjectId}/work-items/${encodeURIComponent(workItemId)}/${action}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    comment: reason || undefined,
                }),
            });
            if (!response.ok) {
                throw new Error(await response.text() || `Failed to record ${decision.replace(/_/g, ' ')} review`);
            }
            setWorkItemReviewReasons(prev => {
                const next = { ...prev };
                delete next[workItemId];
                return next;
            });
            await refreshAll();
            if (selectedMissionId) {
                const fallbackWorkItems = workItems.filter(workItem => workItem.mission_id === selectedMissionId);
                await fetchTeamTimeline(selectedMissionId, fallbackWorkItems);
            }
        } catch (err) {
            console.error(`Failed to record autonomous work item review ${decision}:`, err);
            setError(err instanceof Error ? err.message : `Failed to record ${decision.replace(/_/g, ' ')} review`);
        } finally {
            setActionLoading(null);
        }
    };

    const openMaterializeDialog = (proposal: TestProposal) => {
        setMaterializeProposal(proposal);
        setMaterializePath(proposal.suggested_file_path || '');
        setMaterializeOverwrite(false);
        setMaterializeOverrideDuplicate(false);
        setMaterializeOverrideReason('');
        setError(null);
    };

    const handleMaterializeConfirm = async (event: FormEvent) => {
        event.preventDefault();
        if (!materializeProposal) return;
        const label = `${materializeProposal.id}:materialize`;
        setActionLoading(label);
        setError(null);
        try {
            const response = await fetchWithAuth(`${API_BASE}/autonomous/${encodedProjectId}/proposals/${encodeURIComponent(materializeProposal.id)}/materialize`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    file_path: materializePath.trim() || undefined,
                    overwrite: materializeOverwrite,
                    override_blocking_duplicate: materializeOverrideDuplicate,
                    override_reason: materializeOverrideReason.trim() || undefined,
                    comment: 'Materialized from Autonomous Missions dashboard',
                }),
            });
            if (!response.ok) {
                throw new Error(await response.text() || 'Failed to materialize proposal');
            }
            setMaterializeProposal(null);
            setMaterializePath('');
            setMaterializeOverwrite(false);
            setMaterializeOverrideDuplicate(false);
            setMaterializeOverrideReason('');
            await refreshAll();
        } catch (err) {
            console.error('Failed to materialize autonomous test proposal:', err);
            const message = err instanceof Error ? err.message : 'Failed to materialize proposal';
            setError(message);
            if (message.includes('already exists')) {
                setMaterializeOverwrite(true);
            }
            if (message.includes('Blocking duplicate')) {
                setMaterializeOverrideDuplicate(true);
            }
        } finally {
            setActionLoading(null);
        }
    };

    const openAuditDialog = async (proposal: TestProposal) => {
        setAuditProposal(proposal);
        setAuditDetail(null);
        setAuditLoading(true);
        setError(null);
        try {
            const response = await fetchWithAuth(`${API_BASE}/autonomous/${encodedProjectId}/proposals/${encodeURIComponent(proposal.id)}/audit`);
            if (!response.ok) {
                throw new Error(await response.text() || 'Failed to load proposal audit');
            }
            setAuditDetail(await response.json());
        } catch (err) {
            console.error('Failed to load proposal audit:', err);
            setError(err instanceof Error ? err.message : 'Failed to load proposal audit');
        } finally {
            setAuditLoading(false);
        }
    };

    const materializeHasBlockingDuplicate = materializeProposal ? isBlockingDuplicate(materializeProposal) : false;
    const materializeOverrideReady = !materializeHasBlockingDuplicate
        || (materializeOverrideDuplicate && materializeOverrideReason.trim().length >= 8);

    if (loading || projectLoading) {
        return (
            <PageLayout tier="wide">
                <ListPageSkeleton rows={5} />
            </PageLayout>
        );
    }

    return (
        <PageLayout tier="wide">
            <PageHeader
                title="Autonomous Missions"
                subtitle="Create and control recurring agent missions for the current project"
                icon={<Bot size={20} />}
                actions={
                    <div className="am-header-actions" style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
                        <button
                            type="button"
                            className="am-header-button"
                            onClick={handleRefresh}
                            disabled={refreshing}
                            style={{
                                padding: '0.5rem 0.75rem',
                                background: 'transparent',
                                border: '1px solid var(--border)',
                                borderRadius: 'var(--radius)',
                                cursor: refreshing ? 'not-allowed' : 'pointer',
                                color: 'var(--text-secondary)',
                                display: 'flex',
                                alignItems: 'center',
                                gap: '0.4rem',
                                fontSize: '0.85rem',
                                opacity: refreshing ? 0.7 : 1,
                            }}
                        >
                            <RefreshCw size={14} className={refreshing ? 'am-spin' : undefined} />
                            Refresh
                        </button>
                        <button
                            type="button"
                            className="am-header-button"
                            onClick={() => {
                                setCreateStep(1);
                                setShowCreate(true);
                            }}
                            style={{
                                padding: '0.5rem 1rem',
                                background: 'var(--primary)',
                                color: 'white',
                                border: 'none',
                                borderRadius: 'var(--radius)',
                                cursor: 'pointer',
                                fontWeight: 600,
                                fontSize: '0.85rem',
                                display: 'flex',
                                alignItems: 'center',
                                gap: '0.5rem',
                            }}
                        >
                            <Plus size={16} />
                            New Mission
                        </button>
                    </div>
                }
            />

            <div aria-live="polite">
                {error && (
                    <div className="am-alert am-alert-danger">
                        <AlertCircle size={16} />
                        <span>{error}</span>
                    </div>
                )}
            </div>

            {hasMissions && (
                <div className="am-stat-grid">
                    <div className="am-stat-card am-stat-card-primary">
                        <div className="am-stat-icon"><Target size={16} /></div>
                        <div>
                            <div className="am-stat-value">{missions.length}</div>
                            <div className="am-stat-label">Missions</div>
                        </div>
                    </div>
                    {dashboardStats.map(item => (
                        <div key={item.label} className="am-stat-card">
                            <div className="am-stat-icon">{item.icon}</div>
                            <div>
                                <div className="am-stat-value">{item.value}</div>
                                <div className="am-stat-label">{item.label}</div>
                            </div>
                        </div>
                    ))}
                </div>
            )}

            {hasMissions && (
                <section className="am-attention-strip" aria-label="Needs attention">
                    {attentionItems.map(item => (
                        <div key={item.label} className={`am-attention-card am-attention-${item.tone}`}>
                            <div className="am-attention-icon">{item.icon}</div>
                            <div className="am-attention-copy">
                                <strong>{item.value}</strong>
                                <span>{item.label}</span>
                                <small>{item.detail}</small>
                            </div>
                        </div>
                    ))}
                </section>
            )}

            {hasMissions && (
                <section className="am-panel" aria-label="Autonomous diagnostics">
                    <div className="am-section-title-row">
                        <div className="am-section-heading">
                            <Gauge size={17} style={{ color: 'var(--primary)' }} />
                            <div>
                                <h2>Mission Health</h2>
                                <p>{diagnostics?.status ? diagnostics.status.replace(/_/g, ' ') : 'Diagnostics pending'}</p>
                            </div>
                        </div>
                        <div className="am-action-group">
                            <MissionActionButton
                                icon={<RefreshCw size={13} className={diagnosticsLoading ? 'am-spin' : undefined} />}
                                label="Diagnostics"
                                color="var(--primary)"
                                loading={diagnosticsLoading}
                                onClick={() => void handleDiagnosticsAction('monitor')}
                            />
                            <MissionActionButton
                                icon={<Workflow size={13} />}
                                label="Recover"
                                color="var(--warning)"
                                loading={diagnosticsLoading}
                                onClick={() => void handleDiagnosticsAction('recover')}
                            />
                            <MissionActionButton
                                icon={<ClipboardCheck size={13} />}
                                label="Dry run"
                                color="var(--text-secondary)"
                                loading={diagnosticsLoading}
                                onClick={() => void handleDiagnosticsAction('backfill-dry-run')}
                            />
                            <MissionActionButton
                                icon={<CheckCircle size={13} />}
                                label="Safe backfill"
                                color="var(--success)"
                                loading={diagnosticsLoading}
                                onClick={() => void handleDiagnosticsAction('backfill')}
                            />
                        </div>
                    </div>
                    <div className="am-team-timeline-grid">
                        <div>
                            <span>Stale work</span>
                            <strong>{diagnostics?.work_items?.stale_running ?? 0}</strong>
                        </div>
                        <div>
                            <span>Recovered</span>
                            <strong>{diagnostics?.work_items?.recovered ?? 0}</strong>
                        </div>
                        <div>
                            <span>Failed validations</span>
                            <strong>{diagnostics?.proposals?.validation_failed ?? 0}</strong>
                        </div>
                        <div>
                            <span>Blocked validations</span>
                            <strong>{diagnostics?.proposals?.validation_blocked ?? 0}</strong>
                        </div>
                        <div>
                            <span>Duplicate keys</span>
                            <strong>{diagnostics?.requirements?.duplicate_canonical_keys ?? 0}</strong>
                        </div>
                        <div>
                            <span>Unmapped reqs</span>
                            <strong>{diagnostics?.requirements?.unmapped_full_coverage ?? 0}</strong>
                        </div>
                    </div>
                </section>
            )}

            {approvalsLoadError && (
                <div className="am-alert am-alert-danger">
                    {approvalsLoadError}
                </div>
            )}

            {approvals.length > 0 && (
                <section className="am-panel am-queue-panel">
                    <div className="am-section-title-row">
                        <div className="am-section-heading">
                            <CheckCircle size={17} style={{ color: 'var(--warning)' }} />
                            <div>
                                <h2>Approval Queue</h2>
                                <p>{approvals.length} pending action{approvals.length === 1 ? '' : 's'}</p>
                            </div>
                        </div>
                    </div>
                    <div className="am-inline-list">
                        {approvals.slice(0, 4).map(approval => (
                            <div key={approval.id} className="am-inline-item">
                                <div className="am-inline-copy">
                                    <strong>{approval.action_type.replace(/_/g, ' ')}</strong>
                                    <span>{clampText(approval.requested_payload?.action || approval.requested_payload?.suggested_test || approval.finding_id || approval.id, 'Approval request', 110)}</span>
                                </div>
                                <div className="am-action-group">
                                    <MissionActionButton
                                        icon={<CheckCircle size={13} />}
                                        label="Approve"
                                        color="var(--success)"
                                        loading={actionLoading === `${approval.id}:approve`}
                                        onClick={() => handleApproval(approval, 'approve')}
                                    />
                                    <MissionActionButton
                                        icon={<XCircle size={13} />}
                                        label="Reject"
                                        color="var(--danger)"
                                        loading={actionLoading === `${approval.id}:reject`}
                                        onClick={() => handleApproval(approval, 'reject')}
                                    />
                                </div>
                            </div>
                        ))}
                    </div>
                </section>
            )}

            {!hasMissions ? (
                <section className="am-panel am-empty-state">
                    <div className="am-empty-icon"><Bot size={24} /></div>
                    <h2>No Autonomous Missions Yet</h2>
                    <p>Create a mission to start recurring exploration, coverage review, and approval-gated test proposals for this project.</p>
                    <button
                        type="button"
                        className="am-button am-button-primary"
                        onClick={() => {
                            setCreateStep(1);
                            setShowCreate(true);
                        }}
                    >
                        <Plus size={15} />
                        New Mission
                    </button>
                </section>
            ) : (
                <section className="am-panel am-mission-panel">
                    <div className="am-section-title-row">
                        <div>
                            <div className="am-kicker">Mission control</div>
                            <h2>Active Missions</h2>
                            <p>Scan health, timing, blockers, and the next action without opening every mission.</p>
                        </div>
                    </div>
                    <div className="am-mission-list">
                        {missions.map(mission => {
                            const statusStyle = getStatusStyle(mission.status);
                            const healthStyle = getHealthStyle(mission.health_status);
                            const statusText = getMissionStatusText(mission.status);
                            const teamSummary = getMissionField(mission, 'team_summary');
                            const activeWorkItems = getMissionField(mission, 'active_work_items');
                            const blockedWorkItems = getMissionField(mission, 'blocked_work_items');
                            const coverageSummary = getMissionField(mission, 'coverage_summary');
                            const pendingRevisions = getTeamSummaryMetric(teamSummary, 'pending_revision_count');
                            const acceptedRevisions = getTeamSummaryMetric(teamSummary, 'accepted_revision_count');
                            const totalRevisions = getTeamSummaryMetric(teamSummary, 'revision_count');
                            const revisionAttention = getTeamSummaryFlag(teamSummary, 'revision_attention') || pendingRevisions > 0;
                            const hasTeamStatus = Boolean(teamSummary || activeWorkItems || blockedWorkItems || coverageSummary);
                            const expanded = expandedMissionIds.has(mission.id);
                            return (
                                <article key={mission.id} className="am-mission-row">
                                    <div className="am-mission-row-main">
                                        <div className="am-mission-identity">
                                            <button
                                                type="button"
                                                className="am-expand-button"
                                                aria-label={`${expanded ? 'Collapse' : 'Expand'} ${mission.name}`}
                                                aria-expanded={expanded}
                                                onClick={() => setExpandedMissionIds(current => toggleSetItem(current, mission.id))}
                                            >
                                                {expanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                                            </button>
                                            <div className="am-mission-title-block">
                                                <h3>{mission.name}</h3>
                                                <div className="am-row-subtitle">{formatMissionType(mission.mission_type)}</div>
                                            </div>
                                        </div>
                                        <div className="am-mission-target" title={getMissionPrimaryTarget(mission)}>
                                            {getMissionPrimaryTarget(mission)}
                                        </div>
                                        <div className="am-mission-statuses">
                                            <span className="am-pill" style={{ color: healthStyle.color, background: healthStyle.background }}>
                                                {mission.health_status || 'healthy'}
                                            </span>
                                            <span className="am-pill" style={{ color: statusStyle.color, background: statusStyle.background }}>
                                                {statusText.replace(/_/g, ' ')}
                                            </span>
                                            {revisionAttention && (
                                                <span className="am-pill" style={{ color: 'var(--warning)', background: 'var(--warning-muted)' }}>
                                                    {pendingRevisions} revision{pendingRevisions === 1 ? '' : 's'}
                                                </span>
                                            )}
                                        </div>
                                        <div className="am-row-metrics">
                                            <div>
                                                <span>Stage</span>
                                                <strong>{formatReason(mission.current_stage) || 'idle'}</strong>
                                            </div>
                                            <div>
                                                <span>Next Run</span>
                                                <strong>{formatDate(mission.next_run_at)}</strong>
                                            </div>
                                            <div>
                                                <span>Findings</span>
                                                <strong>{mission.total_findings || 0}</strong>
                                            </div>
                                        </div>
                                        <div className="am-card-actions">
                                            <MissionActionButton
                                                icon={<Terminal size={13} />}
                                                label="Live"
                                                color="var(--primary)"
                                                loading={false}
                                                onClick={() => {
                                                    setSelectedMissionId(mission.id);
                                                    setLiveTab('live');
                                                }}
                                            />
                                            {canStart(mission.status) && (
                                                <MissionActionButton
                                                    icon={<Play size={13} />}
                                                    label="Start"
                                                    color="var(--success)"
                                                    loading={actionLoading === `${mission.id}:start`}
                                                    onClick={() => handleMissionAction(mission, 'start')}
                                                />
                                            )}
                                            {canPause(mission.status) && (
                                                <MissionActionButton
                                                    icon={<Pause size={13} />}
                                                    label="Pause"
                                                    color="var(--warning)"
                                                    loading={actionLoading === `${mission.id}:pause`}
                                                    onClick={() => handleMissionAction(mission, 'pause')}
                                                />
                                            )}
                                            {canResume(mission.status) && (
                                                <MissionActionButton
                                                    icon={<Play size={13} />}
                                                    label="Resume"
                                                    color="var(--success)"
                                                    loading={actionLoading === `${mission.id}:resume`}
                                                    onClick={() => handleMissionAction(mission, 'resume')}
                                                />
                                            )}
                                            {canCancel(mission.status) && (
                                                <MissionActionButton
                                                    icon={<Square size={13} />}
                                                    label="Cancel"
                                                    color="var(--danger)"
                                                    loading={actionLoading === `${mission.id}:cancel`}
                                                    onClick={() => handleMissionAction(mission, 'cancel')}
                                                />
                                            )}
                                        </div>
                                    </div>

                                    {expanded && (
                                        <div className="am-mission-details">
                                            <div className="am-health-panel">
                                                <div>
                                                    <span>Last Run</span>
                                                    <strong>{formatDate(mission.last_run_at)}</strong>
                                                </div>
                                                <div>
                                                    <span>Heartbeat</span>
                                                    <strong>{formatDate(mission.last_heartbeat_at)}</strong>
                                                </div>
                                                <div>
                                                    <span>Budget</span>
                                                    <strong>{formatCurrency(mission.budget_used_usd || 0)}</strong>
                                                </div>
                                                <div>
                                                    <span>Runs / Limit</span>
                                                    <strong>{mission.total_runs || 0} / {formatLimit(mission.max_iterations)}</strong>
                                                </div>
                                                <div>
                                                    <span>Failures</span>
                                                    <strong>{mission.consecutive_failures || 0}</strong>
                                                </div>
                                            </div>

                                            {hasTeamStatus && (
                                                <div className="am-team-panel">
                                                    <div className="am-team-summary">
                                                        <Users size={14} />
                                                        <span>{clampText(teamSummary, 'Team status pending', 160)}</span>
                                                    </div>
                                                    <div className="am-work-lanes">
                                                        <div>
                                                            <span>Active</span>
                                                            <strong>{getWorkItemCount(activeWorkItems)}</strong>
                                                            <small>{clampText(activeWorkItems, 'No active items', 90)}</small>
                                                        </div>
                                                        <div>
                                                            <span>Blocked</span>
                                                            <strong>{getWorkItemCount(blockedWorkItems)}</strong>
                                                            <small>{clampText(blockedWorkItems, 'No blockers', 90)}</small>
                                                        </div>
                                                        <div>
                                                            <span>Coverage</span>
                                                            <strong>{clampText(coverageSummary, 'Pending', 110)}</strong>
                                                        </div>
                                                        <div>
                                                            <span>Revisions</span>
                                                            <strong>{pendingRevisions} pending</strong>
                                                            <small>{acceptedRevisions} accepted / {totalRevisions} total</small>
                                                        </div>
                                                    </div>
                                                </div>
                                            )}

                                            {(mission.paused_reason || mission.next_action) && (
                                                <div className="am-mission-note">
                                                    <Workflow size={14} />
                                                    <span>
                                                        {formatReason(mission.paused_reason) || mission.next_action}
                                                        {mission.paused_reason && mission.next_action ? `: ${mission.next_action}` : ''}
                                                    </span>
                                                </div>
                                            )}

                                            {mission.last_error && (
                                                <div className="am-mission-error">
                                                    <AlertCircle size={14} />
                                                    <span>{clampText(mission.last_error, 'Mission error', 220)}</span>
                                                </div>
                                            )}

                                            <div className="am-metadata-row">
                                                <span>{mission.autonomy_level}</span>
                                                <span>{mission.approval_policy}</span>
                                                {mission.safety_summary?.environment && <span>{mission.safety_summary.environment}</span>}
                                                {mission.safety_summary?.tool_profile && <span>{mission.safety_summary.tool_profile.replace(/_/g, ' ')}</span>}
                                                {mission.schedule_cron && <span>{mission.schedule_cron}</span>}
                                                {mission.latest_run_id && <span>Run {clampText(mission.latest_run_id, '-', 28)}</span>}
                                            </div>
                                        </div>
                                    )}
                                </article>
                            );
                        })}
                    </div>
                </section>
            )}

            {selectedMission && (
                <section className="am-panel am-live-panel" aria-label="Live mission debug panel">
                    <div className="am-section-title-row">
                        <div className="am-section-heading">
                            <Terminal size={17} style={{ color: 'var(--primary)' }} />
                            <div>
                                <h2>{selectedMission.name}</h2>
                                <p>
                                    {streamStatus === 'connected' ? 'Live stream connected' : streamStatus === 'closed' ? 'Stream closed' : streamStatus}
                                    {latestEvent ? ` · ${eventLabel(latestEvent.event_type)} · ${formatDate(latestEvent.created_at)}` : ''}
                                </p>
                            </div>
                        </div>
                        <div className="am-action-group">
                            {canPause(selectedMission.status) && (
                                <MissionActionButton
                                    icon={<Pause size={13} />}
                                    label="Pause"
                                    color="var(--warning)"
                                    loading={actionLoading === `${selectedMission.id}:pause`}
                                    onClick={() => handleMissionAction(selectedMission, 'pause')}
                                />
                            )}
                            {canResume(selectedMission.status) && (
                                <MissionActionButton
                                    icon={<Play size={13} />}
                                    label="Resume"
                                    color="var(--success)"
                                    loading={actionLoading === `${selectedMission.id}:resume`}
                                    onClick={() => handleMissionAction(selectedMission, 'resume')}
                                />
                            )}
                            {canCancel(selectedMission.status) && (
                                <MissionActionButton
                                    icon={<Square size={13} />}
                                    label="Cancel"
                                    color="var(--danger)"
                                    loading={actionLoading === `${selectedMission.id}:cancel`}
                                    onClick={() => handleMissionAction(selectedMission, 'cancel')}
                                />
                            )}
                            <button
                                type="button"
                                className="am-icon-button"
                                aria-label="Close live mission panel"
                                onClick={() => setSelectedMissionId(null)}
                            >
                                <X size={16} />
                            </button>
                        </div>
                    </div>

                    <div className="am-live-tabs" role="tablist" aria-label="Live mission debug views">
                        {(['live', 'browser', 'events', 'output', 'runs'] as LiveTab[]).map(tab => (
                            <button
                                key={tab}
                                type="button"
                                role="tab"
                                aria-selected={liveTab === tab}
                                className={liveTab === tab ? 'am-live-tab is-active' : 'am-live-tab'}
                                onClick={() => setLiveTab(tab)}
                            >
                                {tab}
                            </button>
                        ))}
                    </div>

                    {streamError && (
                        <div className="am-alert am-alert-danger">
                            <AlertCircle size={16} />
                            <span>{streamError}</span>
                        </div>
                    )}

                    {liveTab === 'live' && (
                        <div className="am-live-grid">
                            <div className="am-live-summary">
                                <div>
                                    <span>Status</span>
                                    <strong>{getMissionStatusText(selectedMission.status)}</strong>
                                </div>
                                <div>
                                    <span>Stage</span>
                                    <strong>{formatReason(selectedMission.current_stage) || 'idle'}</strong>
                                </div>
                                <div>
                                    <span>Heartbeat</span>
                                    <strong>{formatDate(selectedMission.last_heartbeat_at)}</strong>
                                </div>
                                <div>
                                    <span>Active work</span>
                                    <strong>{selectedMissionActiveWorkItems.length}</strong>
                                </div>
                                <div>
                                    <span>Last tool</span>
                                    <strong>{clampText(latestEvent?.payload?.short_name || latestEvent?.payload?.tool_name, 'None', 44)}</strong>
                                </div>
                                <div>
                                    <span>Browser</span>
                                    <strong>{latestBrowserEvent ? eventLabel(String(latestBrowserEvent.payload?.short_name || latestBrowserEvent.message)) : 'No action'}</strong>
                                </div>
                            </div>
                            <pre className="am-live-output">
                                {liveAgentOutput || latestEvent?.message || 'Waiting for live agent output...'}
                            </pre>
                        </div>
                    )}

                    {liveTab === 'browser' && (
                        <div className="am-browser-panel">
                            <LiveBrowserView
                                runId={selectedMission.latest_run_id || selectedMission.id}
                                isActive={canPause(selectedMission.status)}
                                showHeader
                            />
                        </div>
                    )}

                    {liveTab === 'events' && (
                        <div className="am-event-list">
                            {missionEvents.length === 0 ? (
                                <div className="am-empty-inline">Waiting for mission events...</div>
                            ) : missionEvents.slice(-120).map(event => {
                                const style = getEventStatusStyle(event);
                                return (
                                    <div key={event.id} className="am-event-row">
                                        <span className="am-event-sequence">#{event.sequence}</span>
                                        <span className="am-pill" style={{ color: style.color, background: style.background }}>
                                            {eventLabel(event.event_type)}
                                        </span>
                                        <div className="am-event-copy">
                                            <strong>{clampText(event.message, 'Event', 180)}</strong>
                                            <span>{formatDate(event.created_at)}{event.work_item_id ? ` · ${event.work_item_id}` : ''}</span>
                                        </div>
                                    </div>
                                );
                            })}
                        </div>
                    )}

                    {liveTab === 'output' && (
                        <div className="am-output-list">
                            {selectedMissionFinalOutputs.length === 0 ? (
                                <pre className="am-live-output">{liveAgentOutput || 'Final agent output will appear after work items complete.'}</pre>
                            ) : selectedMissionFinalOutputs.map(({ item, output }) => (
                                <div key={item.id} className="am-output-card">
                                    <div className="am-output-title">{item.owner_agent || item.title || item.id}</div>
                                    <pre className="am-live-output">{output}</pre>
                                </div>
                            ))}
                        </div>
                    )}

                    {liveTab === 'runs' && (
                        <div className="am-live-summary">
                            <div>
                                <span>Latest run</span>
                                <strong>{selectedMission.latest_run_id || '-'}</strong>
                            </div>
                            <div>
                                <span>Total runs</span>
                                <strong>{selectedMission.total_runs || 0}</strong>
                            </div>
                            <div>
                                <span>Runtime limit</span>
                                <strong>{selectedMission.max_runtime_minutes || '-'} min</strong>
                            </div>
                            <div>
                                <span>Budget</span>
                                <strong>{formatCurrency(selectedMission.budget_used_usd || 0)}</strong>
                            </div>
                            <div>
                                <span>Next action</span>
                                <strong>{clampText(selectedMission.next_action, 'None', 120)}</strong>
                            </div>
                        </div>
                    )}
                </section>
            )}

            {selectedMission && (
                <section className="am-panel" aria-label="App changes review">
                    <div className="am-section-title-row">
                        <div className="am-section-heading">
                            <Sparkles size={17} style={{ color: 'var(--primary)' }} />
                            <div>
                                <h2>App Changes</h2>
                                <p>{visibleAppChangeCount} of {totalAppChangeCount} finding{totalAppChangeCount === 1 ? '' : 's'} for {selectedMission.name}</p>
                            </div>
                        </div>
                        <div className="am-action-group">
                            <div className="am-filter-row am-filter-row-inline" role="group" aria-label="App change status filter">
                                {APP_CHANGE_STATUS_FILTERS.map(filter => (
                                    <button
                                        key={filter}
                                        type="button"
                                        aria-pressed={appChangeStatusFilter === filter}
                                        onClick={() => setAppChangeStatusFilter(filter)}
                                        className={appChangeStatusFilter === filter ? 'am-filter is-active' : 'am-filter'}
                                    >
                                        {appChangeStatusFilterLabel(filter)}
                                    </button>
                                ))}
                            </div>
                            <MissionActionButton
                                icon={<RefreshCw size={13} className={appChangesLoading ? 'am-spin' : undefined} />}
                                label="Refresh"
                                color="var(--primary)"
                                loading={appChangesLoading}
                                onClick={() => void fetchAppChanges(selectedMission.id)}
                            />
                        </div>
                    </div>

                    {appChangesError ? (
                        <div className="am-alert am-alert-danger">
                            <AlertCircle size={16} />
                            <span>{appChangesError}</span>
                        </div>
                    ) : appChangesLoading && appChangeGroups.length === 0 ? (
                        <div className="am-empty-inline">Loading app changes...</div>
                    ) : appChangeGroups.length === 0 ? (
                        <div className="am-empty-inline">No memory deltas or app-change findings are waiting for review.</div>
                    ) : filteredAppChangeGroups.length === 0 ? (
                        <div className="am-empty-inline">No app-change findings match this status filter.</div>
                    ) : (
                        <div className="am-change-group-list">
                            {filteredAppChangeGroups.map(group => (
                                <div key={group.key} className="am-change-group">
                                    <div className="am-change-group-heading">
                                        <strong>{group.label}</strong>
                                        <span>{group.findings.length}</span>
                                    </div>
                                    <div className="am-inline-list">
                                        {group.findings.map((finding, index) => {
                                            const findingId = getFindingId(finding);
                                            const linkedProposalId = getLinkedProposalId(finding);
                                            const linkedProposal = linkedProposalId
                                                ? proposals.find(proposal => proposal.id === linkedProposalId)
                                                    || (finding.proposal as TestProposal | undefined)
                                                    || (finding.test_proposal as TestProposal | undefined)
                                                    || null
                                                : null;
                                            const proposalStatus = getLinkedProposalStatus(finding, linkedProposal);
                                            const status = proposalStatus || finding.status || (linkedProposalId ? 'proposal_linked' : 'unlinked');
                                            const statusStyle = getStatusStyle(status);
                                            const changeType = finding.change_type || finding.category || finding.source_type || 'app_change';
                                            const risk = finding.risk_level || finding.severity || 'unknown';
                                            const riskStyle = getRiskStyle(risk);
                                            const truthState = getFindingTruthState(finding);
                                            const requirementLabel = getRequirementLabel(finding);
                                            const statusLower = (linkedProposal?.approval_status || '').toLowerCase();
                                            const canDecideProposal = Boolean(linkedProposal && statusLower === 'pending');
                                            const canMaterializeProposal = Boolean(linkedProposal && statusLower === 'approved');
                                            const requirementActionKey = finding.requirement_id ? String(finding.requirement_id) : '';
                                            const findingStatusLower = (finding.status || '').toLowerCase();
                                            const canDecideFinding = Boolean(findingId && !['approved', 'rejected', 'resolved'].includes(findingStatusLower));
                                            const findingComment = findingId ? appChangeComments[findingId] || '' : '';
                                            const findingCommentRequired = findingComment.trim().length === 0;

                                            return (
                                                <div key={`${finding.id || group.key}:${index}`} className="am-change-item">
                                                    <div className="am-inline-copy">
                                                        <strong>{finding.title || requirementLabel || finding.change_type || 'App change finding'}</strong>
                                                        <span>{clampText(finding.summary || finding.description || finding.evidence || finding.memory_delta || finding.app_change, 'No summary provided', 180)}</span>
                                                        <div className="am-change-field-grid">
                                                            <div>
                                                                <span>Change</span>
                                                                <strong>{formatReason(changeType) || '-'}</strong>
                                                            </div>
                                                            <div>
                                                                <span>Risk</span>
                                                                <strong>{formatReason(risk) || '-'}</strong>
                                                            </div>
                                                            <div>
                                                                <span>Test value</span>
                                                                <strong>{clampText(finding.test_value, 'Not scored', 80)}</strong>
                                                            </div>
                                                            <div>
                                                                <span>Uncertainty</span>
                                                                <strong>{clampText(finding.uncertainty_reason, 'None noted', 90)}</strong>
                                                            </div>
                                                        </div>
                                                        {requirementLabel && (
                                                            <div className="am-change-requirement">
                                                                <span>Requirement</span>
                                                                <strong>{clampText(requirementLabel, 'Requirement', 160)}</strong>
                                                            </div>
                                                        )}
                                                        <div className="am-metadata-row">
                                                            {finding.requirement_id && <span>Req {finding.requirement_id}</span>}
                                                            {truthState && <span>{truthState.replace(/_/g, ' ')}</span>}
                                                            {typeof finding.confidence !== 'undefined' && finding.confidence !== null && <span>{String(finding.confidence)} confidence</span>}
                                                            {linkedProposalId && <span>Proposal {clampText(linkedProposalId, '-', 28)}</span>}
                                                            {finding.created_at && <span>{formatDate(finding.created_at)}</span>}
                                                        </div>
                                                    </div>
                                                    <div className="am-change-side">
                                                        <div className="am-mission-statuses">
                                                            <span className="am-pill" style={{ color: riskStyle.color, background: riskStyle.background }}>
                                                                {risk.replace(/_/g, ' ')}
                                                            </span>
                                                            <span className="am-pill" style={{ color: 'var(--primary)', background: 'var(--primary-glow)' }}>
                                                                {changeType.replace(/_/g, ' ')}
                                                            </span>
                                                            <span className="am-pill" style={{ color: statusStyle.color, background: statusStyle.background }}>
                                                                {status.replace(/_/g, ' ')}
                                                            </span>
                                                        </div>
                                                        {findingId && (
                                                            <div className="am-change-review">
                                                                <label className="am-field am-comment-field">
                                                                    <span>Review comment</span>
                                                                    <input
                                                                        value={findingComment}
                                                                        onChange={event => {
                                                                            const value = event.target.value;
                                                                            setAppChangeComments(prev => ({ ...prev, [findingId]: value }));
                                                                        }}
                                                                        placeholder="Required for reject or resolve"
                                                                    />
                                                                </label>
                                                                <div className="am-proposal-actions am-change-actions">
                                                                    {canDecideFinding && (
                                                                        <MissionActionButton
                                                                            icon={<CheckCircle size={13} />}
                                                                            label="Approve"
                                                                            color="var(--success)"
                                                                            loading={actionLoading === `app-change:${findingId}:approve`}
                                                                            onClick={() => void handleAppChangeFindingAction(finding, 'approve')}
                                                                        />
                                                                    )}
                                                                    {findingStatusLower !== 'rejected' && (
                                                                        <MissionActionButton
                                                                            icon={<XCircle size={13} />}
                                                                            label="Reject"
                                                                            color="var(--danger)"
                                                                            loading={actionLoading === `app-change:${findingId}:reject`}
                                                                            disabled={findingCommentRequired}
                                                                            onClick={() => void handleAppChangeFindingAction(finding, 'reject')}
                                                                        />
                                                                    )}
                                                                    {findingStatusLower !== 'resolved' && (
                                                                        <MissionActionButton
                                                                            icon={<ClipboardCheck size={13} />}
                                                                            label="Resolve"
                                                                            color="var(--primary)"
                                                                            loading={actionLoading === `app-change:${findingId}:resolve`}
                                                                            disabled={findingCommentRequired}
                                                                            onClick={() => void handleAppChangeFindingAction(finding, 'resolve')}
                                                                        />
                                                                    )}
                                                                </div>
                                                            </div>
                                                        )}
                                                        {finding.requirement_id && (
                                                            <div className="am-proposal-actions am-change-actions">
                                                                <MissionActionButton
                                                                    icon={<CheckCircle size={13} />}
                                                                    label="Truth"
                                                                    color="var(--success)"
                                                                    loading={actionLoading === `requirement:${requirementActionKey}:confirm`}
                                                                    onClick={() => void handleRequirementTruthAction(finding, 'confirm')}
                                                                />
                                                                <MissionActionButton
                                                                    icon={<XCircle size={13} />}
                                                                    label="Reject"
                                                                    color="var(--danger)"
                                                                    loading={actionLoading === `requirement:${requirementActionKey}:reject`}
                                                                    onClick={() => void handleRequirementTruthAction(finding, 'reject')}
                                                                />
                                                                <MissionActionButton
                                                                    icon={<AlertCircle size={13} />}
                                                                    label="Stale"
                                                                    color="var(--warning)"
                                                                    loading={actionLoading === `requirement:${requirementActionKey}:mark-stale`}
                                                                    onClick={() => void handleRequirementTruthAction(finding, 'mark-stale')}
                                                                />
                                                            </div>
                                                        )}
                                                        {linkedProposal ? (
                                                            <div className="am-proposal-actions am-change-actions">
                                                                <MissionActionButton
                                                                    icon={<FileText size={13} />}
                                                                    label="Audit"
                                                                    color="var(--text-secondary)"
                                                                    loading={auditLoading && auditProposal?.id === linkedProposal.id}
                                                                    onClick={() => void openAuditDialog(linkedProposal)}
                                                                />
                                                                <MissionActionButton
                                                                    icon={<RefreshCw size={13} className={reviewRefreshing === linkedProposal.id ? 'am-spin' : undefined} />}
                                                                    label="Review"
                                                                    color="var(--primary)"
                                                                    loading={reviewRefreshing === linkedProposal.id}
                                                                    onClick={() => void handleRefreshProposalReview(linkedProposal)}
                                                                />
                                                                {canDecideProposal && (
                                                                    <>
                                                                        <MissionActionButton
                                                                            icon={<CheckCircle size={13} />}
                                                                            label="Approve"
                                                                            color="var(--success)"
                                                                            loading={actionLoading === `${linkedProposal.id}:approve`}
                                                                            onClick={() => handleProposalAction(linkedProposal, 'approve')}
                                                                        />
                                                                        <MissionActionButton
                                                                            icon={<XCircle size={13} />}
                                                                            label="Reject"
                                                                            color="var(--danger)"
                                                                            loading={actionLoading === `${linkedProposal.id}:reject`}
                                                                            onClick={() => handleProposalAction(linkedProposal, 'reject')}
                                                                        />
                                                                    </>
                                                                )}
                                                                {canMaterializeProposal && (
                                                                    <MissionActionButton
                                                                        icon={<UploadCloud size={13} />}
                                                                        label="Materialize"
                                                                        color="var(--primary)"
                                                                        loading={actionLoading === `${linkedProposal.id}:materialize`}
                                                                        onClick={() => openMaterializeDialog(linkedProposal)}
                                                                    />
                                                                )}
                                                            </div>
                                                        ) : linkedProposalId ? (
                                                            <div className="am-empty-inline am-change-note">Linked proposal is outside the current proposal filter.</div>
                                                        ) : null}
                                                    </div>
                                                </div>
                                            );
                                        })}
                                    </div>
                                </div>
                            ))}
                        </div>
                    )}
                </section>
            )}

            {selectedMission && (
                <section className="am-panel" aria-label="Mission team timeline">
                    <div className="am-section-title-row">
                        <div className="am-section-heading">
                            <Users size={17} style={{ color: 'var(--primary)' }} />
                            <div>
                                <h2>Team Timeline</h2>
                                <p>
                                    {teamTimelineItems.length} lane update{teamTimelineItems.length === 1 ? '' : 's'} for {selectedMission.name}
                                    {teamTimelineFallback ? ' · work item fallback' : ''}
                                </p>
                            </div>
                        </div>
                        <MissionActionButton
                            icon={<RefreshCw size={13} className={teamTimelineLoading ? 'am-spin' : undefined} />}
                            label="Refresh"
                            color="var(--primary)"
                            loading={teamTimelineLoading}
                            onClick={() => void fetchTeamTimeline(selectedMission.id, selectedMissionWorkItems)}
                        />
                    </div>

                    {teamTimelineError && (
                        <div className="am-alert am-alert-warning">
                            <AlertCircle size={16} />
                            <span>{teamTimelineError}. Showing available work items.</span>
                        </div>
                    )}

                    {teamTimelineLoading && teamTimelineItems.length === 0 ? (
                        <div className="am-empty-inline">Loading team timeline...</div>
                    ) : teamTimelineItems.length === 0 ? (
                        <div className="am-empty-inline">No team activity is available for this mission yet.</div>
                    ) : (
                        <div className="am-team-timeline-list">
                            {teamTimelineItems.map((item, index) => {
                                const itemId = getTimelineItemId(item);
                                const status = item.status || 'open';
                                const statusStyle = getStatusStyle(status);
                                const latestEventText = clampText(item.latest_event, 'No event yet', 140);
                                const outputPreview = getTimelineOutputPreview(item);
                                const blocker = item.blocker || item.blocked_reason;
                                const artifactCount = getTimelineArtifactCount(item);
                                const canRetry = Boolean(itemId && canRetryWorkItemStatus(status));
                                const canCancel = Boolean(itemId && canCancelWorkItemStatus(status));
                                const canReview = Boolean(itemId && canReviewWorkItemStatus(status));
                                const reviewDecision = getTimelineReviewField(item, 'decision');
                                const reviewReason = getTimelineReviewField(item, 'reason');
                                const reviewedAt = getTimelineReviewField(item, 'reviewed_at');
                                const reviewedBy = getTimelineReviewField(item, 'reviewed_by');
                                const revisionOfId = getTimelineRevisionField(item, 'revision_of_work_item_id');
                                const revisionWorkItemId = getTimelineRevisionField(item, 'revision_work_item_id');
                                const plannerKey = getTimelineRecoveryField(item, 'planner_key');
                                const recoveryReason = getTimelineRecoveryField(item, 'recovery_reason');
                                const recoveredFromId = getTimelineRecoveryField(item, 'recovered_from_work_item_id');
                                const reviewReasonInput = itemId ? workItemReviewReasons[itemId] || '' : '';
                                const reviewReasonRequired = reviewReasonInput.trim().length === 0;

                                return (
                                    <div key={itemId || `${item.mission_id || selectedMission.id}:timeline:${index}`} className="am-team-timeline-item">
                                        <div className="am-timeline-rail" aria-hidden="true">
                                            <span />
                                        </div>
                                        <div className="am-team-timeline-main">
                                            <div className="am-team-timeline-top">
                                                <div className="am-inline-copy">
                                                    <strong>{clampText(item.title || item.summary || getTimelineRole(item), 'Team lane', 110)}</strong>
                                                    <span>{latestEventText}</span>
                                                </div>
                                                <div className="am-mission-statuses">
                                                    <span className="am-pill" style={{ color: 'var(--primary)', background: 'var(--primary-glow)' }}>
                                                        {getTimelineRole(item).replace(/_/g, ' ')}
                                                    </span>
                                                    <span className="am-pill" style={{ color: statusStyle.color, background: statusStyle.background }}>
                                                        {status.replace(/_/g, ' ')}
                                                    </span>
                                                    {reviewDecision && (
                                                        <span className="am-pill" style={getStatusStyle(reviewDecision)}>
                                                            {reviewDecision.replace(/_/g, ' ')}
                                                        </span>
                                                    )}
                                                    {recoveryReason && (
                                                        <span className="am-pill" style={{ color: 'var(--warning)', background: 'var(--warning-muted)' }}>
                                                            recovered
                                                        </span>
                                                    )}
                                                </div>
                                            </div>
                                            <div className="am-team-timeline-grid">
                                                <div>
                                                    <span>Output</span>
                                                    <strong>{clampText(outputPreview, 'No output yet', 120)}</strong>
                                                </div>
                                                <div>
                                                    <span>Blocker</span>
                                                    <strong>{clampText(blocker, 'None', 100)}</strong>
                                                </div>
                                                <div>
                                                    <span>Artifacts</span>
                                                    <strong>{artifactCount}</strong>
                                                </div>
                                                <div>
                                                    <span>Updated</span>
                                                    <strong>{formatDate(item.updated_at || item.created_at)}</strong>
                                                </div>
                                                <div>
                                                    <span>Planner</span>
                                                    <strong>{clampText(plannerKey, '-', 80)}</strong>
                                                </div>
                                                <div>
                                                    <span>Lease</span>
                                                    <strong>{formatDate(item.lease_until || item.last_heartbeat_at)}</strong>
                                                </div>
                                            </div>
                                            {(reviewDecision || reviewReason || reviewedAt || reviewedBy || revisionOfId || revisionWorkItemId || recoveryReason || recoveredFromId) && (
                                                <div className="am-review-metadata">
                                                    {reviewDecision && <span>Decision: <strong>{reviewDecision.replace(/_/g, ' ')}</strong></span>}
                                                    {reviewReason && <span>Reason: <strong>{clampText(reviewReason, 'None', 140)}</strong></span>}
                                                    {reviewedBy && <span>By: <strong>{reviewedBy}</strong></span>}
                                                    {reviewedAt && <span>At: <strong>{formatDate(reviewedAt)}</strong></span>}
                                                    {revisionOfId && <span>Revision of: <strong>{clampText(revisionOfId, '-', 32)}</strong></span>}
                                                    {revisionWorkItemId && <span>Follow-up: <strong>{clampText(revisionWorkItemId, '-', 32)}</strong></span>}
                                                    {recoveryReason && <span>Recovery: <strong>{recoveryReason.replace(/_/g, ' ')}</strong></span>}
                                                    {recoveredFromId && <span>Recovered from: <strong>{clampText(recoveredFromId, '-', 32)}</strong></span>}
                                                </div>
                                            )}
                                            {canReview && itemId && (
                                                <div className="am-timeline-review-gate">
                                                    <label className="am-field am-comment-field">
                                                        <span>Review reason</span>
                                                        <input
                                                            value={reviewReasonInput}
                                                            onChange={event => {
                                                                const value = event.target.value;
                                                                setWorkItemReviewReasons(prev => ({ ...prev, [itemId]: value }));
                                                            }}
                                                            placeholder="Required for reject or needs revision"
                                                        />
                                                    </label>
                                                    <div className="am-team-timeline-actions">
                                                        <MissionActionButton
                                                            icon={<CheckCircle size={13} />}
                                                            label="Accept"
                                                            color="var(--success)"
                                                            loading={actionLoading === `work-item:${itemId}:review:accept`}
                                                            onClick={() => void handleWorkItemReview(item, 'accept')}
                                                        />
                                                        <MissionActionButton
                                                            icon={<XCircle size={13} />}
                                                            label="Reject"
                                                            color="var(--danger)"
                                                            loading={actionLoading === `work-item:${itemId}:review:reject`}
                                                            disabled={reviewReasonRequired}
                                                            onClick={() => void handleWorkItemReview(item, 'reject')}
                                                        />
                                                        <MissionActionButton
                                                            icon={<AlertCircle size={13} />}
                                                            label="Needs Revision"
                                                            color="var(--warning)"
                                                            loading={actionLoading === `work-item:${itemId}:review:needs_revision`}
                                                            disabled={reviewReasonRequired}
                                                            onClick={() => void handleWorkItemReview(item, 'needs_revision')}
                                                        />
                                                    </div>
                                                </div>
                                            )}
                                            {(canRetry || canCancel) && (
                                                <div className="am-team-timeline-actions">
                                                    {canRetry && (
                                                        <MissionActionButton
                                                            icon={<RefreshCw size={13} />}
                                                            label="Retry"
                                                            color="var(--primary)"
                                                            loading={actionLoading === `work-item:${itemId}:retry`}
                                                            onClick={() => void handleWorkItemAction(item, 'retry')}
                                                        />
                                                    )}
                                                    {canCancel && (
                                                        <MissionActionButton
                                                            icon={<Square size={13} />}
                                                            label="Cancel"
                                                            color="var(--danger)"
                                                            loading={actionLoading === `work-item:${itemId}:cancel`}
                                                            onClick={() => void handleWorkItemAction(item, 'cancel')}
                                                        />
                                                    )}
                                                </div>
                                            )}
                                        </div>
                                    </div>
                                );
                            })}
                        </div>
                    )}
                </section>
            )}

            {workItems.length > 0 && (
                <section className="am-panel">
                    <div className="am-section-title-row">
                        <div className="am-section-heading">
                            <Workflow size={17} style={{ color: 'var(--primary)' }} />
                            <div>
                                <h2>Recent Work Items</h2>
                                <p>{workItems.length} latest team lane update{workItems.length === 1 ? '' : 's'}</p>
                            </div>
                        </div>
                    </div>
                    <div className="am-work-item-list">
                        {workItems.map((item, index) => {
                            const status = item.status || item.lane || 'open';
                            const statusStyle = getStatusStyle(status);
                            const missionName = item.mission_name || missions.find(mission => mission.id === item.mission_id)?.name;
                            return (
                                <div key={item.id || `${item.mission_id || 'work'}:${index}`} className="am-work-item">
                                    <div style={{ minWidth: 0 }}>
                                        <div className="am-work-item-title">
                                            {clampText(item.title || item.summary, 'Untitled work item', 120)}
                                        </div>
                                        <div className="am-work-item-meta">
                                            {missionName && <span>{missionName}</span>}
                                            {item.owner_agent && <span>{item.owner_agent}</span>}
                                            {item.priority && <span>{item.priority}</span>}
                                            <span>{formatDate(item.updated_at || item.created_at)}</span>
                                        </div>
                                        {item.blocked_reason && (
                                            <div className="am-work-item-blocker">
                                                {clampText(item.blocked_reason, 'Blocked', 160)}
                                            </div>
                                        )}
                                    </div>
                                    <span className="am-pill" style={{ color: statusStyle.color, background: statusStyle.background }}>
                                        {status.replace(/_/g, ' ')}
                                    </span>
                                </div>
                            );
                        })}
                    </div>
                </section>
            )}

            {(hasMissions || proposals.length > 0 || proposalLoadError) && (
                <section className="am-panel">
                    <div className="am-section-title-row">
                        <div className="am-section-heading">
                            <FileText size={17} style={{ color: 'var(--primary)' }} />
                            <div>
                                <h2>Generated Test Proposals</h2>
                                <p>{proposals.length} total</p>
                            </div>
                        </div>
                        <MissionActionButton
                            icon={<RefreshCw size={13} className={reviewRefreshing === 'all' ? 'am-spin' : undefined} />}
                            label="Refresh Reviews"
                            color="var(--primary)"
                            loading={reviewRefreshing === 'all'}
                            onClick={() => void handleRefreshReviews()}
                        />
                    </div>
                    <div className="am-filter-row" role="group" aria-label="Proposal status filter">
                        {PROPOSAL_FILTERS.map(filter => (
                            <button
                                key={filter}
                                type="button"
                                aria-pressed={proposalFilter === filter}
                                onClick={() => handleProposalFilterChange(filter)}
                                className={proposalFilter === filter ? 'am-filter is-active' : 'am-filter'}
                            >
                                {proposalFilterLabel(filter)}
                            </button>
                        ))}
                    </div>

                    {proposalLoadError ? (
                        <div className="am-alert am-alert-danger">
                            {proposalLoadError}
                        </div>
                    ) : proposals.length === 0 ? (
                        <div className="am-empty-inline">
                            No generated test proposals for this filter.
                        </div>
                    ) : (
                        <div className="am-proposal-list">
                            {proposals.map(proposal => {
                                const approvalStatus = proposal.approval_status || 'unknown';
                                const riskLevel = proposal.risk_level || 'unknown';
                                const statusStyle = getStatusStyle(approvalStatus);
                                const riskStyle = getRiskStyle(riskLevel);
                                const status = approvalStatus.toLowerCase();
                                const canDecideProposal = status === 'pending';
                                const canMaterializeProposal = status === 'approved';
                                const expanded = expandedProposalIds.has(proposal.id);
                                const duplicateWarning = hasDuplicateRisk(proposal);
                                const blockingDuplicate = isBlockingDuplicate(proposal);
                                const stalenessStatus = getStalenessStatus(proposal);
                                const staleWarning = stalenessStatus === 'stale';
                                const needsReview = stalenessStatus === 'needs_review';
                                const validationStatus = (proposal.validation_status || 'not_run').toLowerCase();
                                const validationStyle = getStatusStyle(validationStatus);
                                const mergeGate = proposal.review_context?.merge_gate;
                                const provenance = proposal.review_context?.provenance;

                                return (
                                    <article key={proposal.id} className="am-proposal-card">
                                        <div className="am-proposal-main">
                                            <button
                                                type="button"
                                                className="am-expand-button"
                                                aria-label={`${expanded ? 'Collapse' : 'Expand'} ${proposal.title || 'proposal'}`}
                                                aria-expanded={expanded}
                                                onClick={() => setExpandedProposalIds(current => toggleSetItem(current, proposal.id))}
                                            >
                                                {expanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                                            </button>
                                            <div className="am-proposal-copy">
                                                <h3>{proposal.title || 'Untitled proposal'}</h3>
                                                <div className="am-truncate" title={getProposalTarget(proposal)}>
                                                    {getProposalTarget(proposal)}
                                                </div>
                                            </div>
                                            <div className="am-mission-statuses">
                                                {duplicateWarning && (
                                                    <span className="am-pill" style={{ color: blockingDuplicate ? 'var(--danger)' : 'var(--warning)', background: blockingDuplicate ? 'var(--danger-muted)' : 'var(--warning-muted)' }}>
                                                        {blockingDuplicate ? 'blocking duplicate' : 'duplicate risk'}
                                                    </span>
                                                )}
                                                {staleWarning && (
                                                    <span className="am-pill" style={{ color: 'var(--danger)', background: 'var(--danger-muted)' }}>
                                                        stale
                                                    </span>
                                                )}
                                                {needsReview && (
                                                    <span className="am-pill" style={{ color: 'var(--warning)', background: 'var(--warning-muted)' }}>
                                                        needs review
                                                    </span>
                                                )}
                                                <span className="am-pill" style={{ color: riskStyle.color, background: riskStyle.background }}>
                                                    {riskLevel}
                                                </span>
                                                <span className="am-pill" style={{ color: statusStyle.color, background: statusStyle.background }}>
                                                    {approvalStatus.replace(/_/g, ' ')}
                                                </span>
                                                {validationStatus !== 'not_run' && (
                                                    <span className="am-pill" style={{ color: validationStyle.color, background: validationStyle.background }}>
                                                        validation {validationStatus.replace(/_/g, ' ')}
                                                    </span>
                                                )}
                                            </div>
                                            <div className="am-proposal-actions">
                                                <MissionActionButton
                                                    icon={<FileText size={13} />}
                                                    label="Audit"
                                                    color="var(--text-secondary)"
                                                    loading={auditLoading && auditProposal?.id === proposal.id}
                                                    onClick={() => void openAuditDialog(proposal)}
                                                />
                                                <MissionActionButton
                                                    icon={<RefreshCw size={13} className={reviewRefreshing === proposal.id ? 'am-spin' : undefined} />}
                                                    label="Review"
                                                    color="var(--primary)"
                                                    loading={reviewRefreshing === proposal.id}
                                                    onClick={() => void handleRefreshProposalReview(proposal)}
                                                />
                                                {canDecideProposal && (
                                                    <>
                                                        <MissionActionButton
                                                            icon={<CheckCircle size={13} />}
                                                            label="Approve"
                                                            color="var(--success)"
                                                            loading={actionLoading === `${proposal.id}:approve`}
                                                            onClick={() => handleProposalAction(proposal, 'approve')}
                                                        />
                                                        <MissionActionButton
                                                            icon={<XCircle size={13} />}
                                                            label="Reject"
                                                            color="var(--danger)"
                                                            loading={actionLoading === `${proposal.id}:reject`}
                                                            onClick={() => handleProposalAction(proposal, 'reject')}
                                                        />
                                                    </>
                                                )}
                                                {canMaterializeProposal && (
                                                    <MissionActionButton
                                                        icon={<UploadCloud size={13} />}
                                                        label="Materialize"
                                                        color="var(--primary)"
                                                        loading={actionLoading === `${proposal.id}:materialize`}
                                                        onClick={() => openMaterializeDialog(proposal)}
                                                    />
                                                )}
                                            </div>
                                        </div>

                                        {expanded && (
                                            <div className="am-proposal-details">
                                                <div className="am-proposal-meta">
                                                    <div>
                                                        <span>Type: </span>
                                                        <strong>{proposal.test_type || '-'}</strong>
                                                    </div>
                                                    <div>
                                                        <span>Source: </span>
                                                        <strong>{provenance?.source_type || proposal.source_type || '-'}</strong>
                                                    </div>
                                                    <div>
                                                        <span>Gate: </span>
                                                        <strong>{mergeGate ? mergeGate.replace(/_/g, ' ') : '-'}</strong>
                                                    </div>
                                                    {provenance?.confidence !== undefined && provenance?.confidence !== null && (
                                                        <div>
                                                            <span>Confidence: </span>
                                                            <strong>{String(provenance.confidence)}</strong>
                                                        </div>
                                                    )}
                                                    <div>
                                                        <span>File: </span>
                                                        <strong>{proposal.suggested_file_path || '-'}</strong>
                                                    </div>
                                                    {proposal.materialized_file_path && (
                                                        <div>
                                                            <span>Materialized: </span>
                                                            <strong>{proposal.materialized_file_path}</strong>
                                                        </div>
                                                    )}
                                                    <div>
                                                        <span>Validation: </span>
                                                        <strong>{validationStatus.replace(/_/g, ' ')}</strong>
                                                    </div>
                                                    {proposal.validated_at && (
                                                        <div>
                                                            <span>Validated: </span>
                                                            <strong>{formatDate(proposal.validated_at)}</strong>
                                                        </div>
                                                    )}
                                                </div>
                                                {validationStatus === 'failed' && (
                                                    <div className="am-mission-error">
                                                        <AlertCircle size={14} />
                                                        <span>
                                                            {clampText(
                                                                asCompactText(proposal.validation_result?.stderr || proposal.validation_result?.stdout || proposal.validation_result?.reason, 'Validation failed.'),
                                                                'Validation failed.',
                                                                360
                                                            )}
                                                        </span>
                                                    </div>
                                                )}
                                                {validationStatus === 'blocked' && (
                                                    <div className="am-mission-error">
                                                        <AlertCircle size={14} />
                                                        <span>
                                                            {clampText(asCompactText(proposal.validation_result?.reason || proposal.validation_result?.error, 'Validation blocked.'), 'Validation blocked.', 280)}
                                                        </span>
                                                    </div>
                                                )}
                                                {(proposal.validation_artifacts || []).length > 0 && (
                                                    <div className="am-review-metadata">
                                                        {(proposal.validation_artifacts || []).slice(0, 6).map((artifact, index) => {
                                                            const path = asCompactText(artifact.path, '');
                                                            return (
                                                                <span key={`${proposal.id}:validation-artifact:${index}`}>
                                                                    {asCompactText(artifact.type || artifact.label, 'artifact')}: <strong>{path ? <a href={path} target="_blank" rel="noreferrer">{clampText(path, path, 64)}</a> : '-'}</strong>
                                                                </span>
                                                            );
                                                        })}
                                                    </div>
                                                )}
                                                {proposal.rationale && (
                                                    <p className="am-proposal-rationale">
                                                        {proposal.rationale}
                                                    </p>
                                                )}
                                                {duplicateWarning && (
                                                    <div className="am-mission-error">
                                                        <AlertCircle size={14} />
                                                        <span>
                                                            {blockingDuplicate
                                                                ? 'Blocking duplicate must be overridden before materialization.'
                                                                : proposal.review_context?.duplicate?.existing_file_conflict
                                                                    ? 'Suggested file already exists.'
                                                                    : 'Similar proposal or spec found.'}
                                                        </span>
                                                    </div>
                                                )}
                                                {(proposal.review_context?.duplicate?.matches || proposal.review_context?.duplicate?.candidates || []).length > 0 && (
                                                    <div className="am-inline-list">
                                                        {(proposal.review_context?.duplicate?.matches || proposal.review_context?.duplicate?.candidates || []).slice(0, 4).map((candidate, index) => (
                                                            <div key={`${candidate.id || candidate.path || 'match'}:${index}`} className="am-inline-item">
                                                                <div className="am-inline-copy">
                                                                    <strong>{candidate.title || candidate.id || candidate.path}</strong>
                                                                    <span>
                                                                        {[
                                                                            candidate.kind,
                                                                            candidate.status,
                                                                            candidate.suggested_file_path || candidate.path || candidate.id,
                                                                            (candidate.reasons || []).join(', '),
                                                                        ].filter(Boolean).join(' · ')}
                                                                    </span>
                                                                </div>
                                                                <span className="am-pill">{Math.round((candidate.score || 0) * 100)}%</span>
                                                            </div>
                                                        ))}
                                                    </div>
                                                )}
                                                {(proposal.review_context?.staleness?.reasons || []).length > 0 && (
                                                    <div className="am-inline-list">
                                                        {(proposal.review_context?.staleness?.reasons || []).slice(0, 4).map((reason, index) => (
                                                            <div key={`${reason.source || 'stale'}:${index}`} className="am-inline-item">
                                                                <div className="am-inline-copy">
                                                                    <strong>{reason.source ? reason.source.replace(/_/g, ' ') : 'staleness signal'}</strong>
                                                                    <span>{reason.message || proposal.review_context?.staleness?.reason || 'Review this proposal against current app behavior.'}</span>
                                                                </div>
                                                                {typeof reason.confidence === 'number' && (
                                                                    <span className="am-pill">{Math.round(reason.confidence * 100)}%</span>
                                                                )}
                                                            </div>
                                                        ))}
                                                    </div>
                                                )}
                                                <pre className="am-spec-preview">
                                                    {compactSpecPreview(proposal.generated_spec_content)}
                                                </pre>
                                            </div>
                                        )}
                                    </article>
                                );
                            })}
                        </div>
                    )}
                </section>
            )}

            {showCreate && (
                <div
                    className="am-drawer-backdrop"
                    role="presentation"
                    onMouseDown={event => {
                        if (event.target === event.currentTarget) setShowCreate(false);
                    }}
                >
                    <aside
                        className="am-create-drawer"
                        role="dialog"
                        aria-modal="true"
                        aria-labelledby="create-mission-title"
                    >
                        <form onSubmit={handleCreate} className="am-create-form">
                            <div className="am-drawer-header">
                                <div>
                                    <div className="am-kicker">Mission setup</div>
                                    <h2 id="create-mission-title">Create Mission</h2>
                                    <p>New missions are created with approval gates and can be started from Mission Control.</p>
                                </div>
                                <button
                                    type="button"
                                    className="am-icon-button"
                                    aria-label="Close create mission"
                                    onClick={() => setShowCreate(false)}
                                >
                                    <X size={18} />
                                </button>
                            </div>

                            <div className="am-stepper" aria-label="Create mission steps">
                                {['Template', 'Target', 'Schedule'].map((label, index) => (
                                    <button
                                        key={label}
                                        type="button"
                                        className={createStep === index + 1 ? 'am-step is-active' : 'am-step'}
                                        onClick={() => setCreateStep(index + 1)}
                                    >
                                        <span>{index + 1}</span>
                                        {label}
                                    </button>
                                ))}
                            </div>

                            {createStep === 1 && (
                                <div className="am-drawer-section">
                                    <div className="am-step-heading">
                                        <span>1</span>
                                        <div>
                                            <strong>Choose a quick start</strong>
                                            <small>Select the mission shape that best matches the work you want the agents to do.</small>
                                        </div>
                                    </div>
                                    <div className="am-template-picker" role="radiogroup" aria-label="Mission quick starts">
                                        {QUICK_START_TEMPLATES.map(template => {
                                            const isSelected = selectedTemplate?.label === template.label;
                                            return (
                                                <button
                                                    key={template.label}
                                                    type="button"
                                                    role="radio"
                                                    aria-checked={isSelected}
                                                    className={isSelected ? 'am-template-choice is-active' : 'am-template-choice'}
                                                    onClick={() => applyMissionTemplate(template)}
                                                >
                                                    <span className="am-template-icon">{template.icon}</span>
                                                    <span>
                                                        <strong>{template.label}</strong>
                                                        <small>{template.description}</small>
                                                    </span>
                                                </button>
                                            );
                                        })}
                                    </div>
                                </div>
                            )}

                            {createStep === 2 && (
                                <div className="am-drawer-section">
                                    <div className="am-form-grid">
                                        <label className="am-field">
                                            <span>Name</span>
                                            <input
                                                name="mission-name"
                                                value={form.name}
                                                aria-invalid={Boolean(formErrors.name)}
                                                autoComplete="off"
                                                onChange={event => {
                                                    setForm(prev => ({ ...prev, name: event.target.value }));
                                                    setFormErrors(prev => ({ ...prev, name: undefined }));
                                                }}
                                                placeholder="Checkout coverage scout"
                                            />
                                            {formErrors.name && <small className="am-field-error">{formErrors.name}</small>}
                                        </label>
                                        <label className="am-field">
                                            <span>Type</span>
                                            <select
                                                name="mission-type"
                                                value={form.mission_type}
                                                onChange={event => {
                                                    const nextType = event.target.value;
                                                    setForm(prev => ({ ...prev, mission_type: nextType }));
                                                    const matchingTemplate = QUICK_START_TEMPLATES.find(template => template.mission_type === nextType);
                                                    if (matchingTemplate) setSelectedTemplateLabel(matchingTemplate.label);
                                                }}
                                            >
                                                <option value="exploration">Exploration</option>
                                                <option value="coverage">Coverage Gaps</option>
                                                <option value="regression">Regression Watch</option>
                                                <option value="flake_triage">Flake Triage</option>
                                                <option value="mixed">Mixed Mission</option>
                                            </select>
                                        </label>
                                    </div>

                                    <label className="am-field">
                                        <span>Description</span>
                                        <textarea
                                            name="mission-description"
                                            value={form.description}
                                            onChange={event => setForm(prev => ({ ...prev, description: event.target.value }))}
                                            placeholder="Focus on checkout, payment error states, and account recovery paths."
                                            rows={3}
                                        />
                                    </label>

                                    <label className="am-field">
                                        <span>Target URLs</span>
                                        <textarea
                                            name="mission-target-urls"
                                            value={form.target_urls}
                                            aria-invalid={Boolean(formErrors.target_urls)}
                                            inputMode="url"
                                            autoComplete="off"
                                            onChange={event => {
                                                setForm(prev => ({ ...prev, target_urls: event.target.value }));
                                                setFormErrors(prev => ({ ...prev, target_urls: undefined }));
                                            }}
                                            placeholder={'https://example.com\nhttps://example.com/checkout'}
                                            rows={5}
                                        />
                                        {formErrors.target_urls && <small className="am-field-error">{formErrors.target_urls}</small>}
                                    </label>
                                </div>
                            )}

                            {createStep === 3 && (
                                <div className="am-drawer-section">
                                    <div className="am-summary-card">
                                        <div className="am-summary-header">
                                            <span className="am-template-icon">{selectedTemplate?.icon}</span>
                                            <div>
                                                <div className="am-kicker">Selected quick start</div>
                                                <h3>{selectedTemplate?.label || 'Custom mission'}</h3>
                                            </div>
                                        </div>
                                        <p>{selectedTemplate?.capability || 'Runs with draft validation and approval gates.'}</p>
                                    </div>

                                    <div className="am-fieldset">
                                        <div className="am-fieldset-heading">
                                            <CalendarClock size={15} />
                                            <span>Schedule</span>
                                        </div>
                                        <div className="am-preset-row" aria-label="Schedule presets">
                                            {SCHEDULE_PRESETS.map(preset => (
                                                <button
                                                    key={preset.label}
                                                    type="button"
                                                    className={form.schedule_cron === preset.cron ? 'am-preset is-active' : 'am-preset'}
                                                    onClick={() => setForm(prev => ({ ...prev, schedule_cron: preset.cron }))}
                                                >
                                                    {preset.label}
                                                </button>
                                            ))}
                                        </div>
                                        <div className="am-form-grid am-form-grid-compact">
                                            <label className="am-field">
                                                <span>Cron</span>
                                                <input
                                                    name="mission-cron"
                                                    value={form.schedule_cron}
                                                    autoComplete="off"
                                                    onChange={event => setForm(prev => ({ ...prev, schedule_cron: event.target.value }))}
                                                    placeholder="0 9 * * 1-5"
                                                />
                                            </label>
                                            <label className="am-field">
                                                <span>Timezone</span>
                                                <input
                                                    name="mission-timezone"
                                                    value={form.timezone}
                                                    autoComplete="off"
                                                    onChange={event => setForm(prev => ({ ...prev, timezone: event.target.value || 'UTC' }))}
                                                />
                                            </label>
                                        </div>
                                    </div>

                                    <div className="am-fieldset">
                                        <div className="am-fieldset-heading">
                                            <Gauge size={15} />
                                            <span>Limits</span>
                                        </div>
                                        <div className="am-form-grid am-form-grid-compact">
                                            <label className="am-field">
                                                <span>Max Runtime <small>minutes</small></span>
                                                <input
                                                    name="mission-max-runtime"
                                                    type="number"
                                                    min={1}
                                                    value={form.max_runtime_minutes}
                                                    onChange={event => setForm(prev => ({ ...prev, max_runtime_minutes: Number(event.target.value) }))}
                                                />
                                            </label>
                                            <label className="am-field">
                                                <span>Max Iterations <small>0 = unlimited</small></span>
                                                <input
                                                    name="mission-max-iterations"
                                                    type="number"
                                                    min={0}
                                                    value={form.max_iterations}
                                                    onChange={event => setForm(prev => ({ ...prev, max_iterations: Number(event.target.value) }))}
                                                />
                                            </label>
                                            <label className="am-field">
                                                <span>LLM Budget <small>USD</small></span>
                                                <input
                                                    name="mission-budget"
                                                    type="number"
                                                    min={0}
                                                    step="0.5"
                                                    value={form.max_llm_budget_usd}
                                                    onChange={event => setForm(prev => ({ ...prev, max_llm_budget_usd: Number(event.target.value) }))}
                                                />
                                            </label>
                                        </div>
                                    </div>

                                    <div className="am-fieldset">
                                        <div className="am-fieldset-heading">
                                            <ShieldCheck size={15} />
                                            <span>Safety</span>
                                        </div>
                                        <div className="am-form-grid am-form-grid-compact">
                                            <label className="am-field">
                                                <span>Environment</span>
                                                <select
                                                    name="mission-environment"
                                                    value={form.environment}
                                                    onChange={event => setForm(prev => ({ ...prev, environment: event.target.value }))}
                                                >
                                                    <option value="staging">Staging</option>
                                                    <option value="development">Development</option>
                                                    <option value="production">Production</option>
                                                </select>
                                            </label>
                                            <label className="am-field">
                                                <span>Tool Profile</span>
                                                <select
                                                    name="mission-tool-profile"
                                                    value={form.tool_profile}
                                                    onChange={event => setForm(prev => ({ ...prev, tool_profile: event.target.value }))}
                                                >
                                                    <option value="role_based">Role based</option>
                                                    <option value="read_only">Read only</option>
                                                </select>
                                            </label>
                                            <label className="am-field">
                                                <span>Credential Scope</span>
                                                <select
                                                    name="mission-credential-scope"
                                                    value={form.credential_scope}
                                                    onChange={event => setForm(prev => ({ ...prev, credential_scope: event.target.value }))}
                                                >
                                                    <option value="project">Project</option>
                                                    <option value="environment">Environment</option>
                                                </select>
                                            </label>
                                        </div>
                                        <label className="am-field" style={{ marginTop: '0.75rem' }}>
                                            <span>Allowed Domains</span>
                                            <textarea
                                                name="mission-allowed-domains"
                                                value={form.allowed_domains}
                                                onChange={event => setForm(prev => ({ ...prev, allowed_domains: event.target.value }))}
                                                placeholder="Leave empty to use hostnames from target URLs"
                                                rows={3}
                                            />
                                        </label>
                                    </div>

                                    <div className="am-guardrail">
                                        <ShieldCheck size={16} />
                                        <span>Approval is required before proposals become repository files.</span>
                                    </div>
                                </div>
                            )}

                            <div className="am-drawer-footer">
                                <button
                                    type="button"
                                    className="am-button am-button-secondary"
                                    onClick={() => createStep === 1 ? setShowCreate(false) : setCreateStep(step => Math.max(1, step - 1))}
                                >
                                    {createStep === 1 ? 'Cancel' : 'Back'}
                                </button>
                                {createStep < 3 ? (
                                    <button
                                        type="button"
                                        className="am-button am-button-primary"
                                        onClick={() => setCreateStep(step => Math.min(3, step + 1))}
                                    >
                                        Next
                                    </button>
                                ) : (
                                    <button
                                        type="submit"
                                        disabled={creating}
                                        className="am-button am-button-primary"
                                    >
                                        {creating ? <Loader2 size={15} className="am-spin" /> : <Plus size={15} />}
                                        Create Mission
                                    </button>
                                )}
                            </div>
                        </form>
                    </aside>
                </div>
            )}

            {materializeProposal && (
                <div
                    className="am-modal-backdrop"
                    role="presentation"
                    onMouseDown={event => {
                        if (event.target === event.currentTarget) setMaterializeProposal(null);
                    }}
                >
                    <form
                        onSubmit={handleMaterializeConfirm}
                        role="dialog"
                        aria-modal="true"
                        aria-labelledby="materialize-title"
                        style={{
                            width: 'min(560px, 100%)',
                            background: 'var(--surface)',
                            border: '1px solid var(--border)',
                            borderRadius: 'var(--radius)',
                            padding: '1rem',
                            boxShadow: '0 20px 60px rgba(0,0,0,0.35)',
                        }}
                    >
                        <div style={{ display: 'flex', justifyContent: 'space-between', gap: '1rem', marginBottom: '0.85rem' }}>
                            <div>
                                <h2 id="materialize-title" style={{ margin: 0, fontSize: '1rem', fontWeight: 700 }}>Materialize Test Proposal</h2>
                                <p style={{ margin: '0.25rem 0 0', color: 'var(--text-secondary)', fontSize: '0.82rem' }}>
                                    This writes the generated spec into the repository.
                                </p>
                            </div>
                            <button
                                type="button"
                                aria-label="Close materialize dialog"
                                onClick={() => setMaterializeProposal(null)}
                                style={{
                                    background: 'transparent',
                                    border: 'none',
                                    color: 'var(--text-secondary)',
                                    cursor: 'pointer',
                                    height: '2rem',
                                }}
                            >
                                <X size={18} />
                            </button>
                        </div>

                        <label style={{ display: 'flex', flexDirection: 'column', gap: '0.35rem', color: 'var(--text-secondary)', fontSize: '0.8rem' }}>
                            Target file path
                            <input
                                name="materialize-path"
                                value={materializePath}
                                onChange={event => setMaterializePath(event.target.value)}
                                style={{
                                    padding: '0.6rem 0.75rem',
                                    background: 'var(--background)',
                                    border: '1px solid var(--border)',
                                    borderRadius: 'var(--radius-sm)',
                                    color: 'var(--text)',
                                    fontFamily: 'monospace',
                                    fontSize: '0.82rem',
                                }}
                            />
                        </label>

                        <label style={{
                            display: 'flex',
                            alignItems: 'center',
                            gap: '0.5rem',
                            marginTop: '0.85rem',
                            color: 'var(--text-secondary)',
                            fontSize: '0.82rem',
                        }}>
                            <input
                                name="materialize-overwrite"
                                type="checkbox"
                                checked={materializeOverwrite}
                                onChange={event => setMaterializeOverwrite(event.target.checked)}
                            />
                            Overwrite existing file
                        </label>

                        {materializeHasBlockingDuplicate && (
                            <div className="am-alert am-alert-danger" style={{ marginTop: '0.85rem' }}>
                                Blocking duplicate review is active. Add an override reason before writing this proposal.
                            </div>
                        )}

                        {materializeHasBlockingDuplicate && (
                            <>
                                <label style={{
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: '0.5rem',
                                    marginTop: '0.85rem',
                                    color: 'var(--text-secondary)',
                                    fontSize: '0.82rem',
                                }}>
                                    <input
                                        name="materialize-override-duplicate"
                                        type="checkbox"
                                        checked={materializeOverrideDuplicate}
                                        onChange={event => setMaterializeOverrideDuplicate(event.target.checked)}
                                    />
                                    Override blocking duplicate
                                </label>

                                <label style={{ display: 'flex', flexDirection: 'column', gap: '0.35rem', marginTop: '0.85rem', color: 'var(--text-secondary)', fontSize: '0.8rem' }}>
                                    Override reason
                                    <input
                                        name="materialize-override-reason"
                                        value={materializeOverrideReason}
                                        onChange={event => setMaterializeOverrideReason(event.target.value)}
                                        placeholder="Explain why this duplicate is intentional"
                                        style={{
                                            padding: '0.6rem 0.75rem',
                                            background: 'var(--background)',
                                            border: '1px solid var(--border)',
                                            borderRadius: 'var(--radius-sm)',
                                            color: 'var(--text)',
                                            fontSize: '0.82rem',
                                        }}
                                    />
                                </label>
                            </>
                        )}

                        <pre style={{
                            margin: '0.85rem 0 0',
                            padding: '0.65rem',
                            background: 'var(--background)',
                            border: '1px solid var(--border)',
                            borderRadius: 'var(--radius-sm)',
                            color: 'var(--text-secondary)',
                            fontSize: '0.74rem',
                            whiteSpace: 'pre-wrap',
                            overflowWrap: 'anywhere',
                            maxHeight: '8rem',
                            overflow: 'auto',
                        }}>
                            {compactSpecPreview(materializeProposal.generated_spec_content)}
                        </pre>

                        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.5rem', marginTop: '1rem' }}>
                            <button
                                type="button"
                                onClick={() => setMaterializeProposal(null)}
                                style={{
                                    padding: '0.5rem 0.75rem',
                                    background: 'transparent',
                                    border: '1px solid var(--border)',
                                    borderRadius: 'var(--radius)',
                                    color: 'var(--text-secondary)',
                                    cursor: 'pointer',
                                }}
                            >
                                Cancel
                            </button>
                            <button
                                type="submit"
                                disabled={actionLoading === `${materializeProposal.id}:materialize` || !materializeOverrideReady}
                                style={{
                                    padding: '0.5rem 0.9rem',
                                    background: 'var(--primary)',
                                    color: 'white',
                                    border: 'none',
                                    borderRadius: 'var(--radius)',
                                    cursor: actionLoading === `${materializeProposal.id}:materialize` || !materializeOverrideReady ? 'not-allowed' : 'pointer',
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: '0.45rem',
                                    fontWeight: 700,
                                    opacity: actionLoading === `${materializeProposal.id}:materialize` || !materializeOverrideReady ? 0.7 : 1,
                                }}
                            >
                                {actionLoading === `${materializeProposal.id}:materialize` ? <Loader2 size={14} className="am-spin" /> : <UploadCloud size={14} />}
                                Materialize
                            </button>
                        </div>
                    </form>
                </div>
            )}

            {auditProposal && (
                <div
                    className="am-modal-backdrop"
                    role="presentation"
                    onMouseDown={event => {
                        if (event.target === event.currentTarget) {
                            setAuditProposal(null);
                            setAuditDetail(null);
                        }
                    }}
                >
                    <section
                        role="dialog"
                        aria-modal="true"
                        aria-labelledby="audit-title"
                        style={{
                            width: 'min(720px, 100%)',
                            maxHeight: 'min(80vh, 760px)',
                            overflow: 'auto',
                            background: 'var(--surface)',
                            border: '1px solid var(--border)',
                            borderRadius: 'var(--radius)',
                            padding: '1rem',
                            boxShadow: '0 20px 60px rgba(0,0,0,0.35)',
                        }}
                    >
                        <div style={{ display: 'flex', justifyContent: 'space-between', gap: '1rem', marginBottom: '0.85rem' }}>
                            <div>
                                <h2 id="audit-title" style={{ margin: 0, fontSize: '1rem', fontWeight: 700 }}>Proposal Audit</h2>
                                <p style={{ margin: '0.25rem 0 0', color: 'var(--text-secondary)', fontSize: '0.82rem' }}>
                                    {auditProposal.title}
                                </p>
                            </div>
                            <button
                                type="button"
                                aria-label="Close audit dialog"
                                onClick={() => {
                                    setAuditProposal(null);
                                    setAuditDetail(null);
                                }}
                                style={{ background: 'transparent', border: 'none', color: 'var(--text-secondary)', cursor: 'pointer', height: '2rem' }}
                            >
                                <X size={18} />
                            </button>
                        </div>
                        {auditLoading ? (
                            <div className="am-empty-inline">Loading audit trail...</div>
                        ) : !auditDetail ? (
                            <div className="am-empty-inline">No audit trail loaded.</div>
                        ) : (
                            <div className="am-audit-body">
                                <div className="am-audit-summary-grid">
                                    <div>
                                        <span>Finding</span>
                                        <strong>{clampText(auditDetail.finding?.title || auditDetail.finding?.id, 'No linked finding', 120)}</strong>
                                        <small>{clampText(auditDetail.finding?.status, 'No status', 48)}</small>
                                    </div>
                                    <div>
                                        <span>Source Agent</span>
                                        <strong>{clampText(auditDetail.source_work_item?.role, 'No source work item', 80)}</strong>
                                        <small>{clampText(auditDetail.source_work_item?.review_decision, 'No review decision', 80)}</small>
                                    </div>
                                    <div>
                                        <span>Requirement</span>
                                        <strong>{clampText(auditDetail.linked_requirement?.req_code || auditDetail.linked_requirement?.title, 'No linked requirement', 120)}</strong>
                                        <small>{clampText(auditDetail.linked_requirement?.truth_state, 'No truth state', 80)}</small>
                                    </div>
                                </div>

                                {auditDetail.linked_requirement?.uncertainty_reason && (
                                    <div className="am-alert am-alert-warning">
                                        <AlertCircle size={15} />
                                        <span>{auditDetail.linked_requirement.uncertainty_reason}</span>
                                    </div>
                                )}

                                {(auditDetail.revision_chain || []).length > 0 && (
                                    <div className="am-audit-section">
                                        <h3>Revision Chain</h3>
                                        <div className="am-review-metadata">
                                            {(auditDetail.revision_chain || []).map(item => (
                                                <span key={item.id || item.created_at || item.role || 'revision'}>
                                                    {clampText(item.role, 'agent', 32)}: <strong>{clampText(item.id, '-', 30)}</strong>
                                                </span>
                                            ))}
                                        </div>
                                    </div>
                                )}

                                {(auditDetail.review_events || []).length > 0 && (
                                    <div className="am-audit-section">
                                        <h3>Review Events</h3>
                                        <div className="am-event-list">
                                            {(auditDetail.review_events || []).slice(-8).map((event, index) => (
                                                <div key={`${event.id || event.sequence || index}`} className="am-event-row">
                                                    <span className="am-event-sequence">#{event.sequence || index + 1}</span>
                                                    <span className="am-pill">{event.event_type.replace(/_/g, ' ')}</span>
                                                    <div className="am-event-copy">
                                                        <strong>{clampText(event.message, 'Review event', 180)}</strong>
                                                        <span>{formatDate(event.created_at)}</span>
                                                    </div>
                                                </div>
                                            ))}
                                        </div>
                                    </div>
                                )}

                                <div className="am-audit-section">
                                    <h3>Timeline</h3>
                                    <div className="am-event-list">
                                        {auditDetail.timeline.map((entry, index) => (
                                            <div key={`${entry.type}:${entry.at || index}`} className="am-event-row">
                                                <span className="am-event-sequence">#{index + 1}</span>
                                                <span className="am-pill">{entry.type.replace(/_/g, ' ')}</span>
                                                <div className="am-event-copy">
                                                    <strong>{clampText(entry.message, 'Audit event', 220)}</strong>
                                                    <span>{formatDate(entry.at)}</span>
                                                </div>
                                            </div>
                                        ))}
                                    </div>
                                </div>
                            </div>
                        )}
                    </section>
                </div>
            )}

            <style jsx>{`
                .am-alert {
                    margin-bottom: 1rem;
                    padding: 0.85rem 1rem;
                    border-radius: var(--radius);
                    display: flex;
                    align-items: center;
                    gap: 0.5rem;
                    font-size: 0.9rem;
                }

                .am-alert-danger {
                    background: var(--danger-muted);
                    border: 1px solid rgba(239, 68, 68, 0.25);
                    color: var(--danger);
                }

                .am-alert-warning {
                    background: var(--warning-muted);
                    border: 1px solid rgba(251, 191, 36, 0.25);
                    color: var(--warning);
                }

                .am-stat-grid {
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
                    gap: 0.75rem;
                    margin-bottom: 1.25rem;
                }

                .am-stat-card {
                    padding: 1rem;
                    background: var(--surface);
                    border: 1px solid var(--border);
                    border-radius: var(--radius);
                    display: flex;
                    align-items: center;
                    gap: 0.75rem;
                    min-width: 0;
                }

                .am-stat-card-primary {
                    border-color: rgba(59, 130, 246, 0.28);
                    background: linear-gradient(135deg, rgba(59, 130, 246, 0.12), var(--surface));
                }

                .am-stat-icon,
                .am-template-icon {
                    width: 34px;
                    height: 34px;
                    border-radius: var(--radius-sm);
                    background: var(--primary-glow);
                    color: var(--primary);
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    flex-shrink: 0;
                }

                .am-stat-value {
                    font-size: 1.1rem;
                    font-weight: 750;
                    color: var(--text);
                }

                .am-stat-label,
                .am-kicker {
                    font-size: 0.72rem;
                    color: var(--text-secondary);
                }

                .am-kicker {
                    text-transform: uppercase;
                    letter-spacing: 0.08em;
                    font-weight: 750;
                    margin-bottom: 0.35rem;
                }

                .am-panel {
                    padding: 1rem;
                    background: var(--surface);
                    border: 1px solid var(--border);
                    border-radius: var(--radius);
                    margin-bottom: 1rem;
                }

                .am-create-panel {
                    background:
                        linear-gradient(135deg, rgba(59, 130, 246, 0.08), transparent 38%),
                        var(--surface);
                }

                .am-create-grid {
                    display: grid;
                    grid-template-columns: minmax(0, 1.45fr) minmax(280px, 0.75fr);
                    gap: 1.1rem;
                    align-items: start;
                }

                .am-create-main {
                    display: grid;
                    gap: 0.9rem;
                    min-width: 0;
                }

                .am-setup-flow,
                .am-setup-summary {
                    display: grid;
                    gap: 0.85rem;
                    min-width: 0;
                }

                .am-step-heading {
                    display: grid;
                    grid-template-columns: auto minmax(0, 1fr);
                    gap: 0.6rem;
                    align-items: start;
                    color: var(--text);
                }

                .am-step-heading > span {
                    width: 1.55rem;
                    height: 1.55rem;
                    border-radius: var(--radius-sm);
                    background: var(--primary-glow);
                    color: var(--primary);
                    display: inline-flex;
                    align-items: center;
                    justify-content: center;
                    font-size: 0.78rem;
                    font-weight: 800;
                }

                .am-step-heading strong,
                .am-step-heading small {
                    display: block;
                    min-width: 0;
                }

                .am-step-heading strong {
                    font-size: 0.9rem;
                    font-weight: 750;
                }

                .am-step-heading small {
                    margin-top: 0.18rem;
                    color: var(--text-secondary);
                    font-size: 0.78rem;
                    line-height: 1.35;
                }

                .am-section-heading,
                .am-section-title-row {
                    display: flex;
                    align-items: flex-start;
                    justify-content: space-between;
                    gap: 0.75rem;
                    min-width: 0;
                }

                .am-section-heading {
                    align-items: center;
                    justify-content: flex-start;
                    margin-bottom: 0.85rem;
                }

                .am-section-title-row {
                    margin-bottom: 0.75rem;
                }

                .am-section-title-row h2,
                .am-section-heading h2 {
                    margin: 0;
                    font-size: 1rem;
                    font-weight: 750;
                    color: var(--text);
                }

                .am-section-title-row p,
                .am-section-heading p {
                    margin: 0.25rem 0 0;
                    color: var(--text-secondary);
                    font-size: 0.83rem;
                    line-height: 1.45;
                }

                .am-soft-badge {
                    display: inline-flex;
                    align-items: center;
                    gap: 0.35rem;
                    color: var(--primary);
                    background: var(--primary-glow);
                    border: 1px solid rgba(59, 130, 246, 0.2);
                    border-radius: var(--radius-sm);
                    padding: 0.35rem 0.55rem;
                    font-size: 0.76rem;
                    font-weight: 750;
                    white-space: nowrap;
                }

                .am-fieldset {
                    border: 1px solid var(--border);
                    border-radius: var(--radius-sm);
                    background: rgba(255, 255, 255, 0.018);
                    padding: 0.75rem;
                }

                .am-fieldset-heading {
                    display: flex;
                    align-items: center;
                    gap: 0.4rem;
                    color: var(--text);
                    font-size: 0.83rem;
                    font-weight: 750;
                    margin-bottom: 0.6rem;
                }

                .am-preset-row {
                    display: flex;
                    gap: 0.4rem;
                    flex-wrap: wrap;
                    margin-bottom: 0.65rem;
                }

                .am-preset {
                    padding: 0.28rem 0.55rem;
                    border: 1px solid var(--border);
                    border-radius: var(--radius-sm);
                    background: transparent;
                    color: var(--text-secondary);
                    font-size: 0.72rem;
                    font-weight: 700;
                    cursor: pointer;
                }

                .am-preset.is-active {
                    color: var(--primary);
                    background: var(--primary-glow);
                    border-color: rgba(59, 130, 246, 0.28);
                }

                .am-form-grid {
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
                    gap: 0.75rem;
                }

                .am-form-grid-compact {
                    grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
                }

                .am-field {
                    display: flex;
                    flex-direction: column;
                    gap: 0.35rem;
                    font-size: 0.8rem;
                    color: var(--text-secondary);
                    min-width: 0;
                }

                .am-field > span {
                    display: inline-flex;
                    align-items: baseline;
                    gap: 0.35rem;
                    flex-wrap: wrap;
                }

                .am-field > span small {
                    color: var(--text-tertiary);
                    font-size: 0.72rem;
                    font-weight: 500;
                }

                .am-field input,
                .am-field select,
                .am-field textarea {
                    width: 100%;
                    padding: 0.55rem 0.7rem;
                    background: var(--background);
                    border: 1px solid var(--border);
                    border-radius: var(--radius-sm);
                    color: var(--text);
                    font: inherit;
                    outline: none;
                    min-width: 0;
                }

                .am-field input[aria-invalid="true"],
                .am-field textarea[aria-invalid="true"] {
                    border-color: rgba(239, 68, 68, 0.55);
                    box-shadow: 0 0 0 2px rgba(239, 68, 68, 0.12);
                }

                .am-field textarea {
                    resize: vertical;
                    line-height: 1.45;
                }

                .am-field-error {
                    color: var(--danger);
                    font-size: 0.74rem;
                    line-height: 1.35;
                }

                .am-field input:focus,
                .am-field select:focus,
                .am-field textarea:focus,
                .am-button:focus-visible,
                .am-filter:focus-visible,
                .am-preset:focus-visible,
                .am-template-button:focus-visible,
                .am-template-choice:focus-visible {
                    border-color: var(--primary);
                    box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.22);
                    outline: none;
                }

                .am-template-picker {
                    display: grid;
                    grid-template-columns: repeat(2, minmax(0, 1fr));
                    gap: 0.65rem;
                }

                .am-template-button,
                .am-template-choice {
                    width: 100%;
                    padding: 0.65rem;
                    border: 1px solid var(--border);
                    border-radius: var(--radius-sm);
                    background: rgba(255, 255, 255, 0.018);
                    color: var(--text);
                    display: grid;
                    grid-template-columns: auto minmax(0, 1fr);
                    gap: 0.65rem;
                    text-align: left;
                    transition: border-color 0.2s, background 0.2s;
                    cursor: pointer;
                }

                .am-template-button:hover,
                .am-template-choice:hover {
                    background: rgba(255, 255, 255, 0.035);
                    border-color: var(--border-bright);
                }

                .am-template-choice.is-active {
                    background: rgba(59, 130, 246, 0.1);
                    border-color: rgba(59, 130, 246, 0.38);
                    box-shadow: inset 0 0 0 1px rgba(59, 130, 246, 0.08);
                }

                .am-template-button strong,
                .am-template-button small,
                .am-template-choice strong,
                .am-template-choice small {
                    display: block;
                    min-width: 0;
                }

                .am-template-button strong,
                .am-template-choice strong {
                    font-size: 0.86rem;
                    font-weight: 750;
                }

                .am-template-button small,
                .am-template-choice small {
                    margin-top: 0.2rem;
                    color: var(--text-secondary);
                    font-size: 0.72rem;
                    line-height: 1.3;
                }

                .am-summary-card {
                    padding: 0.85rem;
                    border: 1px solid rgba(59, 130, 246, 0.24);
                    border-radius: var(--radius-sm);
                    background: rgba(59, 130, 246, 0.06);
                    min-width: 0;
                }

                .am-summary-header {
                    display: grid;
                    grid-template-columns: auto minmax(0, 1fr);
                    gap: 0.65rem;
                    align-items: center;
                    min-width: 0;
                }

                .am-summary-header h3 {
                    margin: 0;
                    color: var(--text);
                    font-size: 0.95rem;
                    font-weight: 750;
                }

                .am-summary-card p {
                    margin: 0.75rem 0;
                    color: var(--text-secondary);
                    font-size: 0.8rem;
                    line-height: 1.45;
                }

                .am-summary-list {
                    display: grid;
                    gap: 0.5rem;
                }

                .am-summary-list div {
                    display: flex;
                    align-items: center;
                    justify-content: space-between;
                    gap: 0.75rem;
                    padding: 0.5rem 0;
                    border-top: 1px solid rgba(255, 255, 255, 0.06);
                    min-width: 0;
                }

                .am-summary-list span {
                    color: var(--text-tertiary);
                    font-size: 0.74rem;
                }

                .am-summary-list strong {
                    color: var(--text);
                    font-size: 0.78rem;
                    font-weight: 700;
                    text-align: right;
                    overflow-wrap: anywhere;
                }

                .am-guardrail {
                    display: flex;
                    align-items: center;
                    gap: 0.5rem;
                    padding: 0.65rem;
                    border-radius: var(--radius-sm);
                    background: var(--success-muted);
                    color: var(--success);
                    font-size: 0.78rem;
                    font-weight: 650;
                }

                .am-form-actions,
                .am-action-group,
                .am-card-actions,
                .am-filter-row {
                    display: flex;
                    gap: 0.5rem;
                    flex-wrap: wrap;
                }

                .am-form-actions {
                    justify-content: space-between;
                    align-items: center;
                    margin-top: 1rem;
                    padding-top: 0.9rem;
                    border-top: 1px solid var(--border);
                }

                .am-action-group {
                    justify-content: flex-end;
                }

                .am-next-step {
                    display: inline-flex;
                    align-items: center;
                    gap: 0.45rem;
                    color: var(--text-secondary);
                    font-size: 0.8rem;
                    min-width: 0;
                }

                .am-button {
                    min-height: 2.35rem;
                    padding: 0.5rem 0.9rem;
                    border-radius: var(--radius);
                    display: inline-flex;
                    align-items: center;
                    justify-content: center;
                    gap: 0.45rem;
                    border: 1px solid transparent;
                    font-weight: 700;
                    font-size: 0.85rem;
                }

                .am-button-primary {
                    background: var(--primary);
                    color: white;
                }

                .am-button-secondary {
                    background: transparent;
                    border-color: var(--border);
                    color: var(--text-secondary);
                }

                .am-button:disabled {
                    cursor: not-allowed;
                    opacity: 0.7;
                }

                .am-inline-item,
                .am-proposal-card {
                    display: grid;
                    grid-template-columns: minmax(0, 1fr) auto;
                    gap: 0.75rem;
                    align-items: center;
                    padding: 0.75rem;
                    border: 1px solid var(--border);
                    border-radius: var(--radius-sm);
                    background: rgba(255, 255, 255, 0.018);
                    min-width: 0;
                }

                .am-mission-error {
                    display: grid;
                    grid-template-columns: auto minmax(0, 1fr);
                    gap: 0.45rem;
                    align-items: start;
                    padding: 0.6rem;
                    border: 1px solid rgba(239, 68, 68, 0.24);
                    border-radius: var(--radius-sm);
                    background: var(--danger-muted);
                    color: var(--danger);
                    font-size: 0.76rem;
                    line-height: 1.35;
                    overflow-wrap: anywhere;
                }

                .am-mission-note {
                    display: grid;
                    grid-template-columns: auto minmax(0, 1fr);
                    gap: 0.45rem;
                    align-items: start;
                    padding: 0.6rem;
                    border: 1px solid rgba(59, 130, 246, 0.24);
                    border-radius: var(--radius-sm);
                    background: var(--primary-glow);
                    color: var(--primary);
                    font-size: 0.76rem;
                    line-height: 1.35;
                    overflow-wrap: anywhere;
                }

                .am-work-item-list {
                    display: grid;
                    gap: 0.6rem;
                }

                .am-work-item {
                    display: grid;
                    grid-template-columns: minmax(0, 1fr) auto;
                    gap: 0.75rem;
                    align-items: start;
                    padding: 0.75rem;
                    border: 1px solid var(--border);
                    border-radius: var(--radius-sm);
                    background: rgba(255, 255, 255, 0.018);
                    min-width: 0;
                }

                .am-work-item-title {
                    color: var(--text);
                    font-size: 0.88rem;
                    font-weight: 750;
                    overflow-wrap: anywhere;
                }

                .am-work-item-meta {
                    display: flex;
                    flex-wrap: wrap;
                    gap: 0.45rem;
                    margin-top: 0.25rem;
                    color: var(--text-tertiary);
                    font-size: 0.74rem;
                }

                .am-work-item-blocker {
                    margin-top: 0.45rem;
                    color: var(--danger);
                    font-size: 0.76rem;
                    line-height: 1.35;
                    overflow-wrap: anywhere;
                }

                .am-team-timeline-list {
                    display: grid;
                    gap: 0.6rem;
                    min-width: 0;
                }

                .am-team-timeline-item {
                    display: grid;
                    grid-template-columns: 1.35rem minmax(0, 1fr);
                    gap: 0.65rem;
                    padding: 0.72rem;
                    border: 1px solid var(--border);
                    border-radius: var(--radius-sm);
                    background: rgba(255, 255, 255, 0.018);
                    min-width: 0;
                }

                .am-timeline-rail {
                    position: relative;
                    display: flex;
                    justify-content: center;
                    min-height: 100%;
                }

                .am-timeline-rail::before {
                    content: "";
                    position: absolute;
                    top: 1.1rem;
                    bottom: -0.72rem;
                    width: 1px;
                    background: var(--border);
                }

                .am-team-timeline-item:last-child .am-timeline-rail::before {
                    display: none;
                }

                .am-timeline-rail span {
                    position: relative;
                    z-index: 1;
                    width: 0.62rem;
                    height: 0.62rem;
                    margin-top: 0.25rem;
                    border-radius: 999px;
                    background: var(--primary);
                    box-shadow: 0 0 0 4px var(--primary-glow);
                }

                .am-team-timeline-main {
                    display: grid;
                    gap: 0.55rem;
                    min-width: 0;
                }

                .am-team-timeline-top {
                    display: grid;
                    grid-template-columns: minmax(0, 1fr) auto;
                    gap: 0.75rem;
                    align-items: start;
                    min-width: 0;
                }

                .am-team-timeline-grid,
                .am-change-field-grid {
                    display: grid;
                    grid-template-columns: repeat(4, minmax(0, 1fr));
                    gap: 0.45rem;
                    min-width: 0;
                }

                .am-team-timeline-grid > div,
                .am-change-field-grid > div {
                    min-width: 0;
                    padding: 0.48rem 0.55rem;
                    border: 1px solid rgba(255, 255, 255, 0.06);
                    border-radius: var(--radius-sm);
                    background: rgba(0, 0, 0, 0.08);
                }

                .am-team-timeline-grid span,
                .am-team-timeline-grid strong,
                .am-change-field-grid span,
                .am-change-field-grid strong,
                .am-change-requirement span,
                .am-change-requirement strong {
                    display: block;
                    min-width: 0;
                }

                .am-team-timeline-grid span,
                .am-change-field-grid span,
                .am-change-requirement span {
                    color: var(--text-tertiary);
                    font-size: 0.66rem;
                    font-weight: 750;
                    text-transform: uppercase;
                }

                .am-team-timeline-grid strong,
                .am-change-field-grid strong,
                .am-change-requirement strong {
                    margin-top: 0.12rem;
                    color: var(--text-secondary);
                    font-size: 0.74rem;
                    font-weight: 700;
                    overflow: hidden;
                    text-overflow: ellipsis;
                    white-space: nowrap;
                }

                .am-team-timeline-actions {
                    display: flex;
                    flex-wrap: wrap;
                    gap: 0.4rem;
                    justify-content: flex-end;
                }

                .am-review-metadata {
                    display: flex;
                    flex-wrap: wrap;
                    gap: 0.45rem;
                    color: var(--text-tertiary);
                    font-size: 0.72rem;
                }

                .am-review-metadata span {
                    padding: 0.3rem 0.45rem;
                    border: 1px solid rgba(255, 255, 255, 0.06);
                    border-radius: var(--radius-sm);
                    background: rgba(0, 0, 0, 0.08);
                    overflow-wrap: anywhere;
                }

                .am-review-metadata strong {
                    color: var(--text-secondary);
                    font-weight: 700;
                }

                .am-timeline-review-gate {
                    display: grid;
                    gap: 0.45rem;
                    justify-items: stretch;
                    min-width: 0;
                    padding: 0.55rem;
                    border: 1px solid rgba(59, 130, 246, 0.18);
                    border-radius: var(--radius-sm);
                    background: rgba(59, 130, 246, 0.045);
                }

                .am-change-group-list,
                .am-change-group {
                    display: grid;
                    gap: 0.75rem;
                    min-width: 0;
                }

                .am-change-group {
                    padding: 0.75rem;
                    border: 1px solid var(--border);
                    border-radius: var(--radius);
                    background: rgba(255, 255, 255, 0.014);
                }

                .am-change-group-heading {
                    display: flex;
                    align-items: center;
                    justify-content: space-between;
                    gap: 0.75rem;
                    color: var(--text);
                    font-size: 0.82rem;
                    font-weight: 800;
                    text-transform: capitalize;
                }

                .am-change-group-heading span {
                    min-width: 1.45rem;
                    height: 1.45rem;
                    padding: 0 0.35rem;
                    border-radius: 999px;
                    display: inline-flex;
                    align-items: center;
                    justify-content: center;
                    background: var(--primary-glow);
                    color: var(--primary);
                    font-size: 0.72rem;
                    font-weight: 800;
                }

                .am-change-item {
                    display: grid;
                    grid-template-columns: minmax(0, 1fr) minmax(220px, auto);
                    gap: 0.75rem;
                    align-items: start;
                    padding: 0.7rem;
                    border: 1px solid var(--border);
                    border-radius: var(--radius-sm);
                    background: rgba(0, 0, 0, 0.08);
                    min-width: 0;
                }

                .am-change-side {
                    display: grid;
                    gap: 0.5rem;
                    justify-items: end;
                    min-width: 0;
                }

                .am-change-review {
                    display: grid;
                    gap: 0.45rem;
                    justify-items: end;
                    min-width: 0;
                }

                .am-comment-field {
                    width: min(260px, 100%);
                }

                .am-comment-field input {
                    padding: 0.42rem 0.55rem;
                    font-size: 0.75rem;
                }

                .am-change-requirement {
                    margin-top: 0.5rem;
                    padding: 0.5rem 0.55rem;
                    border: 1px solid rgba(59, 130, 246, 0.2);
                    border-radius: var(--radius-sm);
                    background: var(--primary-glow);
                    min-width: 0;
                }

                .am-change-actions {
                    align-items: flex-end;
                }

                .am-change-note {
                    padding: 0.45rem 0.55rem;
                    font-size: 0.72rem;
                    max-width: 220px;
                }

                .am-mission-grid {
                    display: grid;
                    grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
                    gap: 1rem;
                }

                .am-mission-card {
                    padding: 1.1rem;
                    border: 1px solid var(--border);
                    border-radius: var(--radius);
                    background: rgba(255, 255, 255, 0.018);
                    display: flex;
                    flex-direction: column;
                    gap: 0.9rem;
                    min-width: 0;
                }

                .am-card-header {
                    display: flex;
                    align-items: flex-start;
                    justify-content: space-between;
                    gap: 0.75rem;
                    min-width: 0;
                }

                .am-mini-stat {
                    padding: 0.65rem;
                    border: 1px solid var(--border);
                    border-radius: var(--radius-sm);
                    background: rgba(255, 255, 255, 0.018);
                    min-width: 0;
                }

                .am-health-panel {
                    display: grid;
                    grid-template-columns: repeat(4, minmax(0, 1fr));
                    gap: 0.5rem;
                    padding: 0.65rem;
                    border: 1px solid var(--border);
                    border-radius: var(--radius-sm);
                    background: rgba(255, 255, 255, 0.018);
                }

                .am-health-panel span,
                .am-health-panel strong {
                    display: block;
                    min-width: 0;
                }

                .am-health-panel span {
                    color: var(--text-tertiary);
                    font-size: 0.7rem;
                }

                .am-health-panel strong {
                    margin-top: 0.15rem;
                    color: var(--text-secondary);
                    font-size: 0.74rem;
                    font-weight: 650;
                    overflow-wrap: anywhere;
                    text-transform: capitalize;
                }

                .am-team-panel {
                    display: grid;
                    gap: 0.55rem;
                    padding: 0.7rem;
                    border: 1px solid rgba(59, 130, 246, 0.2);
                    border-radius: var(--radius-sm);
                    background: rgba(59, 130, 246, 0.055);
                }

                .am-team-summary {
                    display: grid;
                    grid-template-columns: auto minmax(0, 1fr);
                    gap: 0.45rem;
                    align-items: start;
                    color: var(--text-secondary);
                    font-size: 0.78rem;
                    line-height: 1.4;
                    overflow-wrap: anywhere;
                }

                .am-work-lanes {
                    display: grid;
                    grid-template-columns: repeat(4, minmax(0, 1fr));
                    gap: 0.5rem;
                }

                .am-work-lanes > div {
                    min-width: 0;
                    padding: 0.55rem;
                    border: 1px solid rgba(255, 255, 255, 0.06);
                    border-radius: var(--radius-sm);
                    background: rgba(0, 0, 0, 0.08);
                }

                .am-work-lanes span,
                .am-work-lanes strong,
                .am-work-lanes small {
                    display: block;
                    min-width: 0;
                }

                .am-work-lanes span {
                    color: var(--text-tertiary);
                    font-size: 0.68rem;
                    font-weight: 700;
                    text-transform: uppercase;
                    letter-spacing: 0.04em;
                }

                .am-work-lanes strong {
                    margin-top: 0.16rem;
                    color: var(--text);
                    font-size: 0.82rem;
                    font-weight: 750;
                    overflow-wrap: anywhere;
                }

                .am-work-lanes small {
                    margin-top: 0.16rem;
                    color: var(--text-secondary);
                    font-size: 0.7rem;
                    line-height: 1.3;
                    overflow-wrap: anywhere;
                }

                .am-filter-row {
                    margin-bottom: 0.85rem;
                }

                .am-filter-row-inline {
                    margin-bottom: 0;
                    align-items: center;
                    justify-content: flex-end;
                }

                .am-filter {
                    padding: 0.3rem 0.65rem;
                    border: 1px solid var(--border);
                    border-radius: var(--radius-sm);
                    background: transparent;
                    color: var(--text-secondary);
                    font-size: 0.76rem;
                    font-weight: 650;
                    text-transform: capitalize;
                }

                .am-filter.is-active {
                    color: var(--primary);
                    background: var(--primary-glow);
                    border-color: rgba(59, 130, 246, 0.28);
                }

                .am-empty-inline {
                    padding: 0.9rem;
                    border: 1px dashed var(--border);
                    border-radius: var(--radius-sm);
                    color: var(--text-secondary);
                    font-size: 0.85rem;
                }

                .am-proposal-card {
                    align-items: start;
                    gap: 1rem;
                }

                .am-truncate {
                    margin-top: 0.25rem;
                    color: var(--text-secondary);
                    font-size: 0.78rem;
                    white-space: nowrap;
                    overflow: hidden;
                    text-overflow: ellipsis;
                    min-width: 0;
                }

                .am-pill {
                    padding: 0.16rem 0.5rem;
                    border-radius: 999px;
                    font-size: 0.7rem;
                    font-weight: 750;
                    text-transform: capitalize;
                }

                .am-proposal-meta {
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
                    gap: 0.55rem;
                    color: var(--text-tertiary);
                    font-size: 0.76rem;
                    margin-bottom: 0.65rem;
                }

                .am-proposal-meta strong {
                    color: var(--text-secondary);
                    font-weight: 500;
                    overflow-wrap: anywhere;
                    text-transform: capitalize;
                }

                .am-proposal-rationale {
                    margin: 0 0 0.65rem;
                    color: var(--text-secondary);
                    font-size: 0.8rem;
                    line-height: 1.45;
                }

                .am-spec-preview {
                    margin: 0;
                    padding: 0.65rem;
                    background: var(--background);
                    border: 1px solid var(--border);
                    border-radius: var(--radius-sm);
                    color: var(--text-secondary);
                    font-size: 0.74rem;
                    line-height: 1.45;
                    white-space: pre-wrap;
                    overflow-wrap: anywhere;
                    max-height: 5.5rem;
                    overflow: hidden;
                }

                .am-proposal-actions {
                    display: flex;
                    flex-direction: column;
                    gap: 0.4rem;
                    align-items: flex-end;
                }

                .am-attention-strip {
                    display: grid;
                    grid-template-columns: repeat(4, minmax(0, 1fr));
                    gap: 0.75rem;
                    margin-bottom: 1rem;
                }

                .am-attention-card {
                    display: grid;
                    grid-template-columns: auto minmax(0, 1fr);
                    gap: 0.75rem;
                    align-items: start;
                    padding: 0.85rem;
                    border: 1px solid var(--border);
                    border-radius: var(--radius);
                    background: rgba(255, 255, 255, 0.018);
                    min-width: 0;
                }

                .am-attention-primary {
                    border-color: rgba(59, 130, 246, 0.28);
                    background: rgba(59, 130, 246, 0.08);
                }

                .am-attention-warning {
                    border-color: rgba(251, 191, 36, 0.28);
                    background: rgba(251, 191, 36, 0.08);
                }

                .am-attention-danger {
                    border-color: rgba(248, 113, 113, 0.28);
                    background: rgba(248, 113, 113, 0.08);
                }

                .am-attention-icon {
                    width: 2rem;
                    height: 2rem;
                    border-radius: var(--radius-sm);
                    color: var(--primary);
                    background: var(--primary-glow);
                    display: flex;
                    align-items: center;
                    justify-content: center;
                }

                .am-attention-copy {
                    min-width: 0;
                }

                .am-attention-copy strong,
                .am-attention-copy span,
                .am-attention-copy small {
                    display: block;
                    min-width: 0;
                }

                .am-attention-copy strong {
                    color: var(--text);
                    font-size: 1.05rem;
                    font-weight: 800;
                    font-variant-numeric: tabular-nums;
                }

                .am-attention-copy span {
                    margin-top: 0.1rem;
                    color: var(--text);
                    font-size: 0.8rem;
                    font-weight: 750;
                }

                .am-attention-copy small {
                    margin-top: 0.15rem;
                    color: var(--text-secondary);
                    font-size: 0.72rem;
                    line-height: 1.35;
                    overflow-wrap: anywhere;
                }

                .am-inline-list,
                .am-proposal-list,
                .am-mission-list {
                    display: grid;
                    gap: 0.7rem;
                }

                .am-inline-copy {
                    min-width: 0;
                }

                .am-inline-copy strong,
                .am-inline-copy span {
                    display: block;
                    min-width: 0;
                    overflow-wrap: anywhere;
                }

                .am-inline-copy strong {
                    color: var(--text);
                    font-size: 0.88rem;
                    font-weight: 750;
                    text-transform: capitalize;
                }

                .am-inline-copy span {
                    margin-top: 0.2rem;
                    color: var(--text-secondary);
                    font-size: 0.78rem;
                    line-height: 1.35;
                }

                .am-empty-state {
                    min-height: 320px;
                    display: flex;
                    flex-direction: column;
                    align-items: center;
                    justify-content: center;
                    text-align: center;
                    gap: 0.75rem;
                }

                .am-empty-state h2 {
                    margin: 0;
                    color: var(--text);
                    font-size: 1.15rem;
                    font-weight: 800;
                }

                .am-empty-state p {
                    max-width: 540px;
                    margin: 0;
                    color: var(--text-secondary);
                    font-size: 0.9rem;
                    line-height: 1.55;
                }

                .am-empty-icon {
                    width: 3rem;
                    height: 3rem;
                    border-radius: var(--radius);
                    background: var(--primary-glow);
                    color: var(--primary);
                    display: flex;
                    align-items: center;
                    justify-content: center;
                }

                .am-mission-panel {
                    padding: 0.95rem;
                }

                .am-mission-row {
                    border: 1px solid var(--border);
                    border-radius: var(--radius);
                    background: rgba(255, 255, 255, 0.018);
                    overflow: hidden;
                }

                .am-mission-row-main {
                    display: grid;
                    grid-template-columns: minmax(220px, 1.15fr) minmax(160px, 0.8fr) minmax(130px, 0.55fr) minmax(250px, 1.05fr) minmax(82px, auto);
                    gap: 0.85rem;
                    align-items: center;
                    padding: 0.85rem;
                    min-width: 0;
                }

                .am-mission-identity,
                .am-proposal-main {
                    display: grid;
                    grid-template-columns: auto minmax(0, 1fr);
                    gap: 0.65rem;
                    align-items: center;
                    min-width: 0;
                }

                .am-expand-button,
                .am-icon-button {
                    width: 2rem;
                    height: 2rem;
                    border-radius: var(--radius-sm);
                    border: 1px solid var(--border);
                    background: transparent;
                    color: var(--text-secondary);
                    display: inline-flex;
                    align-items: center;
                    justify-content: center;
                    flex-shrink: 0;
                }

                .am-expand-button:hover,
                .am-icon-button:hover {
                    color: var(--text);
                    background: var(--surface-hover);
                }

                .am-action-button:hover,
                .am-button:hover,
                .am-filter:hover,
                .am-preset:hover {
                    border-color: var(--border-bright);
                    background: rgba(255, 255, 255, 0.035);
                }

                .am-button-primary:hover {
                    background: var(--primary-hover);
                }

                .am-action-button:focus-visible,
                .am-header-button:focus-visible,
                .am-button:focus-visible,
                .am-filter:focus-visible,
                .am-preset:focus-visible,
                .am-template-choice:focus-visible,
                .am-expand-button:focus-visible,
                .am-icon-button:focus-visible,
                .am-step:focus-visible {
                    outline: none;
                    border-color: var(--primary);
                    box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.24);
                }

                .am-mission-title-block,
                .am-proposal-copy {
                    min-width: 0;
                }

                .am-mission-title-block h3,
                .am-proposal-copy h3 {
                    margin: 0;
                    color: var(--text);
                    font-size: 0.92rem;
                    font-weight: 800;
                    overflow-wrap: anywhere;
                }

                .am-row-subtitle {
                    margin-top: 0.2rem;
                    color: var(--text-secondary);
                    font-size: 0.76rem;
                    text-transform: capitalize;
                }

                .am-mission-target {
                    min-width: 0;
                    color: var(--text-secondary);
                    font-size: 0.78rem;
                    white-space: nowrap;
                    overflow: hidden;
                    text-overflow: ellipsis;
                }

                .am-mission-statuses {
                    display: flex;
                    gap: 0.4rem;
                    flex-wrap: wrap;
                    justify-content: flex-start;
                    min-width: 120px;
                }

                .am-row-metrics {
                    display: grid;
                    grid-template-columns: repeat(3, minmax(0, 1fr));
                    gap: 0.55rem;
                    min-width: 0;
                }

                .am-row-metrics div {
                    min-width: 0;
                }

                .am-row-metrics span,
                .am-row-metrics strong {
                    display: block;
                    min-width: 0;
                }

                .am-row-metrics span {
                    color: var(--text-tertiary);
                    font-size: 0.68rem;
                    font-weight: 700;
                }

                .am-row-metrics strong {
                    margin-top: 0.12rem;
                    color: var(--text-secondary);
                    font-size: 0.76rem;
                    font-weight: 700;
                    overflow: hidden;
                    text-overflow: ellipsis;
                    white-space: nowrap;
                    text-transform: capitalize;
                }

                .am-mission-details,
                .am-proposal-details {
                    display: grid;
                    gap: 0.75rem;
                    padding: 0 0.85rem 0.85rem 3.5rem;
                    border-top: 1px solid var(--border);
                }

                .am-mission-details {
                    padding-top: 0.85rem;
                }

                .am-metadata-row {
                    display: flex;
                    flex-wrap: wrap;
                    gap: 0.45rem;
                    color: var(--text-tertiary);
                    font-size: 0.74rem;
                }

                .am-metadata-row span {
                    max-width: 220px;
                    overflow: hidden;
                    text-overflow: ellipsis;
                    white-space: nowrap;
                }

                .am-proposal-card {
                    display: block;
                    padding: 0;
                    border: 1px solid var(--border);
                    border-radius: var(--radius);
                    background: rgba(255, 255, 255, 0.018);
                    overflow: hidden;
                }

                .am-proposal-main {
                    grid-template-columns: auto minmax(220px, 1fr) auto auto;
                    padding: 0.8rem;
                }

                .am-proposal-details {
                    padding-top: 0.85rem;
                }

                .am-drawer-backdrop,
                .am-modal-backdrop {
                    position: fixed;
                    inset: 0;
                    z-index: 50;
                    background: rgba(0, 0, 0, 0.58);
                    display: flex;
                    justify-content: flex-end;
                    padding: 0;
                }

                .am-modal-backdrop {
                    align-items: center;
                    justify-content: center;
                    padding: 1rem;
                }

                .am-create-drawer {
                    width: min(620px, 100%);
                    height: 100%;
                    background: var(--surface);
                    border-left: 1px solid var(--border);
                    box-shadow: -24px 0 70px rgba(0, 0, 0, 0.38);
                    overflow: hidden;
                }

                .am-create-form {
                    height: 100%;
                    display: flex;
                    flex-direction: column;
                    min-width: 0;
                }

                .am-drawer-header {
                    display: flex;
                    justify-content: space-between;
                    gap: 1rem;
                    padding: 1rem;
                    border-bottom: 1px solid var(--border);
                }

                .am-drawer-header h2 {
                    margin: 0;
                    color: var(--text);
                    font-size: 1.05rem;
                    font-weight: 800;
                }

                .am-drawer-header p {
                    margin: 0.25rem 0 0;
                    color: var(--text-secondary);
                    font-size: 0.82rem;
                    line-height: 1.45;
                }

                .am-stepper {
                    display: grid;
                    grid-template-columns: repeat(3, minmax(0, 1fr));
                    gap: 0.5rem;
                    padding: 0.8rem 1rem;
                    border-bottom: 1px solid var(--border);
                }

                .am-step {
                    min-width: 0;
                    padding: 0.5rem;
                    border: 1px solid var(--border);
                    border-radius: var(--radius-sm);
                    background: transparent;
                    color: var(--text-secondary);
                    display: inline-flex;
                    align-items: center;
                    justify-content: center;
                    gap: 0.4rem;
                    font-size: 0.78rem;
                    font-weight: 750;
                }

                .am-step span {
                    width: 1.25rem;
                    height: 1.25rem;
                    border-radius: 999px;
                    display: inline-flex;
                    align-items: center;
                    justify-content: center;
                    background: var(--surface-hover);
                    color: var(--text-secondary);
                    font-size: 0.7rem;
                }

                .am-step.is-active {
                    color: var(--primary);
                    background: var(--primary-glow);
                    border-color: rgba(59, 130, 246, 0.32);
                }

                .am-step.is-active span {
                    background: var(--primary);
                    color: white;
                }

                .am-drawer-section {
                    display: grid;
                    gap: 0.9rem;
                    padding: 1rem;
                    overflow: auto;
                    min-height: 0;
                }

                .am-drawer-footer {
                    margin-top: auto;
                    padding: 1rem;
                    border-top: 1px solid var(--border);
                    display: flex;
                    justify-content: space-between;
                    gap: 0.75rem;
                    background: var(--surface);
                }

                .am-live-panel {
                    gap: 0.85rem;
                }

                .am-live-tabs {
                    display: flex;
                    flex-wrap: wrap;
                    gap: 0.4rem;
                    border-bottom: 1px solid var(--border);
                    padding-bottom: 0.7rem;
                }

                .am-live-tab {
                    border: 1px solid var(--border);
                    border-radius: var(--radius-sm);
                    background: transparent;
                    color: var(--text-secondary);
                    cursor: pointer;
                    font-size: 0.78rem;
                    font-weight: 750;
                    padding: 0.4rem 0.7rem;
                    text-transform: capitalize;
                }

                .am-live-tab.is-active {
                    border-color: rgba(59, 130, 246, 0.34);
                    background: var(--primary-glow);
                    color: var(--primary);
                }

                .am-live-grid {
                    display: grid;
                    grid-template-columns: minmax(240px, 0.42fr) minmax(0, 1fr);
                    gap: 0.85rem;
                    min-width: 0;
                }

                .am-live-summary {
                    display: grid;
                    grid-template-columns: repeat(3, minmax(0, 1fr));
                    gap: 0.65rem;
                }

                .am-live-summary > div {
                    min-width: 0;
                    padding: 0.7rem;
                    border: 1px solid var(--border);
                    border-radius: var(--radius);
                    background: rgba(255, 255, 255, 0.018);
                }

                .am-live-summary span {
                    display: block;
                    color: var(--text-tertiary);
                    font-size: 0.68rem;
                    font-weight: 750;
                    text-transform: uppercase;
                }

                .am-live-summary strong {
                    display: block;
                    margin-top: 0.2rem;
                    color: var(--text);
                    font-size: 0.82rem;
                    overflow: hidden;
                    text-overflow: ellipsis;
                    white-space: nowrap;
                }

                .am-live-output {
                    min-height: 260px;
                    max-height: 520px;
                    overflow: auto;
                    margin: 0;
                    padding: 0.8rem;
                    border: 1px solid var(--border);
                    border-radius: var(--radius);
                    background: #070b13;
                    color: var(--text-secondary);
                    font-size: 0.78rem;
                    line-height: 1.55;
                    white-space: pre-wrap;
                    word-break: break-word;
                }

                .am-browser-panel {
                    overflow: hidden;
                    border-radius: var(--radius);
                }

                .am-audit-body,
                .am-audit-section {
                    display: grid;
                    gap: 0.75rem;
                    min-width: 0;
                }

                .am-audit-section h3 {
                    margin: 0;
                    color: var(--text);
                    font-size: 0.86rem;
                    font-weight: 800;
                }

                .am-audit-summary-grid {
                    display: grid;
                    grid-template-columns: repeat(3, minmax(0, 1fr));
                    gap: 0.65rem;
                }

                .am-audit-summary-grid > div {
                    min-width: 0;
                    display: grid;
                    gap: 0.25rem;
                    padding: 0.7rem;
                    border: 1px solid var(--border);
                    border-radius: var(--radius);
                    background: rgba(255, 255, 255, 0.018);
                }

                .am-audit-summary-grid span,
                .am-audit-summary-grid small {
                    color: var(--text-secondary);
                    font-size: 0.72rem;
                    overflow: hidden;
                    text-overflow: ellipsis;
                    white-space: nowrap;
                }

                .am-audit-summary-grid strong {
                    color: var(--text);
                    font-size: 0.82rem;
                    overflow: hidden;
                    text-overflow: ellipsis;
                    white-space: nowrap;
                }

                .am-event-list,
                .am-output-list {
                    display: grid;
                    gap: 0.55rem;
                    min-width: 0;
                }

                .am-event-row {
                    display: grid;
                    grid-template-columns: auto auto minmax(0, 1fr);
                    align-items: center;
                    gap: 0.6rem;
                    padding: 0.65rem 0.75rem;
                    border: 1px solid var(--border);
                    border-radius: var(--radius);
                    background: rgba(255, 255, 255, 0.018);
                }

                .am-event-sequence {
                    color: var(--text-tertiary);
                    font-size: 0.72rem;
                    font-weight: 750;
                }

                .am-event-copy {
                    min-width: 0;
                    display: grid;
                    gap: 0.15rem;
                }

                .am-event-copy strong,
                .am-event-copy span {
                    overflow: hidden;
                    text-overflow: ellipsis;
                    white-space: nowrap;
                }

                .am-event-copy strong {
                    color: var(--text);
                    font-size: 0.82rem;
                }

                .am-event-copy span,
                .am-empty-inline {
                    color: var(--text-secondary);
                    font-size: 0.76rem;
                }

                .am-output-card {
                    display: grid;
                    gap: 0.5rem;
                }

                .am-output-title {
                    color: var(--text);
                    font-size: 0.84rem;
                    font-weight: 800;
                }

                .am-spin {
                    animation: spin 1s linear infinite;
                }

                @keyframes spin {
                    from { transform: rotate(0deg); }
                    to { transform: rotate(360deg); }
                }

                @media (prefers-reduced-motion: reduce) {
                    .am-spin,
                    [style*="spin"] {
                        animation: none !important;
                    }
                }

                @media (max-width: 900px) {
                    .am-create-grid,
                    .am-work-item,
                    .am-change-item,
                    .am-proposal-card,
                    .am-inline-item,
                    .am-live-grid {
                        grid-template-columns: 1fr;
                    }

                    .am-attention-strip {
                        grid-template-columns: repeat(2, minmax(0, 1fr));
                    }

                    .am-mission-row-main,
                    .am-proposal-main {
                        grid-template-columns: 1fr;
                        align-items: stretch;
                    }

                    .am-mission-identity {
                        grid-template-columns: auto minmax(0, 1fr);
                    }

                    .am-proposal-main {
                        grid-template-columns: auto minmax(0, 1fr);
                    }

                    .am-proposal-main .am-mission-statuses,
                    .am-proposal-main .am-proposal-actions {
                        grid-column: 1 / -1;
                    }

                    .am-mission-statuses,
                    .am-card-actions,
                    .am-proposal-actions,
                    .am-change-side,
                    .am-team-timeline-actions {
                        justify-content: flex-start;
                        justify-items: start;
                    }

                    .am-team-timeline-top,
                    .am-team-timeline-grid,
                    .am-change-field-grid,
                    .am-audit-summary-grid {
                        grid-template-columns: 1fr;
                    }

                    .am-mission-details,
                    .am-proposal-details {
                        padding-left: 0.85rem;
                    }

                    .am-proposal-actions {
                        align-items: flex-start;
                        flex-direction: row;
                        flex-wrap: wrap;
                    }
                }

                @media (max-width: 640px) {
                    .am-stat-grid,
                    .am-mission-grid,
                    .am-attention-strip,
                    .am-health-panel,
                    .am-work-lanes,
                    .am-row-metrics,
                    .am-live-summary,
                    .am-template-picker,
                    .am-team-timeline-grid,
                    .am-change-field-grid {
                        grid-template-columns: 1fr;
                    }

                    .am-event-row {
                        grid-template-columns: 1fr;
                        align-items: start;
                    }

                    .am-section-title-row,
                    .am-card-header {
                        flex-direction: column;
                    }

                    .am-form-actions {
                        align-items: stretch;
                        flex-direction: column;
                    }

                    .am-action-group {
                        flex-direction: column;
                    }

                    .am-button {
                        width: 100%;
                    }

                    .am-header-actions {
                        width: 100%;
                    }

                    .am-header-actions > button {
                        flex: 1 1 150px;
                        justify-content: center;
                    }

                    .am-create-drawer {
                        width: 100%;
                    }

                    .am-stepper {
                        grid-template-columns: 1fr;
                    }

                    .am-drawer-footer {
                        flex-direction: column;
                    }
                }
            `}</style>
        </PageLayout>
    );
}

function MissionActionButton({
    icon,
    label,
    color,
    loading,
    disabled = false,
    onClick,
}: {
    icon: ReactNode;
    label: string;
    color: string;
    loading: boolean;
    disabled?: boolean;
    onClick: () => void;
}) {
    const isDisabled = loading || disabled;
    return (
        <button
            type="button"
            className="am-action-button"
            onClick={onClick}
            disabled={isDisabled}
            aria-busy={loading}
            style={{
                padding: '0.35rem 0.6rem',
                background: 'transparent',
                border: '1px solid var(--border)',
                borderRadius: 'var(--radius)',
                cursor: isDisabled ? 'not-allowed' : 'pointer',
                color,
                fontSize: '0.8rem',
                display: 'flex',
                alignItems: 'center',
                gap: '0.35rem',
                opacity: isDisabled ? 0.55 : 1,
            }}
        >
            {loading ? <Loader2 size={13} className="am-spin" /> : icon}
            {label}
        </button>
    );
}
