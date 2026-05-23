'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import {
    Activity,
    Archive,
    CheckCircle,
    Clock,
    Database,
    Edit3,
    Eye,
    Filter,
    GitBranch,
    MessageSquareText,
    Plus,
    RefreshCw,
    Save,
    Search,
    ShieldCheck,
    Sparkles,
    Trash2,
    X,
    XCircle,
} from 'lucide-react';
import { API_BASE } from '@/lib/api';
import { fetchWithAuth } from '@/contexts/AuthContext';
import { useProject } from '@/contexts/ProjectContext';
import { PageLayout } from '@/components/ui/page-layout';
import { PageHeader } from '@/components/ui/page-header';
import { DashboardPageSkeleton } from '@/components/ui/page-skeleton';
import { ConfirmDialog } from '@/components/ui/confirm-dialog';

interface Pattern {
    id: string;
    action: string;
    target: string;
    success_rate: number;
    avg_duration: number;
    test_name: string;
}

interface MemoryStats {
    total_patterns: number;
    avg_success_rate: number;
    action_breakdown: Record<string, number>;
    project_id: string;
}

interface BrowserMemoryState {
    id: string;
    url: string;
    page_key?: string;
    state_key?: string;
    source_fidelity?: string;
    visit_count?: number;
    last_seen_at?: string | null;
}

interface BrowserMemoryElement {
    id: string;
    state_id: string;
    role?: string | null;
    name?: string | null;
    tested_count?: number;
    success_count?: number;
    failure_count?: number;
    stability_score?: number;
    importance_score?: number;
    source_fidelity?: string;
    best_locator?: {
        strategy?: string;
        locator?: string;
        score?: number;
        durable?: boolean;
    };
    last_seen_at?: string | null;
}

interface BrowserFrontierItem {
    id: string;
    state_id: string;
    state_url?: string | null;
    state_url_template?: string | null;
    state_source_fidelity?: string;
    element_id?: string | null;
    role?: string | null;
    name?: string | null;
    text?: string | null;
    action_type: string;
    risk_level?: string;
    status: string;
    attempts?: number;
    rank_score?: number;
    priority_score?: number;
    best_locator?: {
        strategy?: string;
        locator?: string;
        score?: number;
        durable?: boolean;
    };
}

interface BrowserMemoryBundle {
    project_id: string;
    states: BrowserMemoryState[];
    elements: BrowserMemoryElement[];
    frontier: BrowserFrontierItem[];
}

interface AgentMemory {
    id: string;
    project_id?: string | null;
    user_id?: string | null;
    kind: string;
    memory_type: string;
    scope: string;
    content: string;
    summary?: string | null;
    tags: string[];
    confidence: number;
    importance: number;
    source_type?: string | null;
    source_id?: string | null;
    agent_type?: string | null;
    status: string;
    valid_from?: string | null;
    valid_until?: string | null;
    supersedes_id?: string | null;
    review_required: boolean;
    last_verified_at?: string | null;
    created_at: string;
    updated_at: string;
    last_used_at?: string | null;
    use_count: number;
}

interface RecallResult {
    conversation_id: string;
    title: string;
    project_id?: string | null;
    updated_at: string;
    match_message_id?: number | null;
    snippet?: string | null;
}

interface AgentFilters {
    q: string;
    kind: string;
    type: string;
    scope: string;
}

interface MemoryInjectionEvent {
    id: string;
    project_id?: string | null;
    actor_type: string;
    stage: string;
    source_type?: string | null;
    source_id?: string | null;
    query: string;
    memory_ids: string[];
    context_preview: string;
    outcome: string;
    extra_data?: Record<string, unknown> | null;
    created_at: string;
}

interface MemoryGraphNode {
    id: string;
    project_id?: string | null;
    node_type: string;
    label: string;
    memory_id?: string | null;
    entity_key: string;
    confidence: number;
    status: string;
    extra_data?: Record<string, unknown>;
    created_at: string;
    updated_at: string;
}

interface MemoryGraphEdge {
    id: string;
    project_id?: string | null;
    source_node_id: string;
    target_node_id: string;
    relationship_type: string;
    weight: number;
    evidence_memory_id?: string | null;
    status: string;
    extra_data?: Record<string, unknown>;
    created_at: string;
    updated_at: string;
}

interface MemoryKnowledgeGraph {
    nodes: MemoryGraphNode[];
    edges: MemoryGraphEdge[];
    stats: {
        node_count: number;
        edge_count: number;
        node_types: Record<string, number>;
        relationship_types: Record<string, number>;
    };
}

interface MemoryGraphReviewEdge extends MemoryGraphEdge {
    source_node?: MemoryGraphNode | null;
    target_node?: MemoryGraphNode | null;
}

interface TelemetryFilters {
    stage: string;
    outcome: string;
    sourceType: string;
}

const memoryKinds = ['project_fact', 'user_preference', 'workflow_decision', 'failure_pattern', 'agent_lesson'];
const memoryTypes = ['semantic', 'episodic', 'procedural', 'structural'];
const memoryScopes = ['global', 'project', 'user', 'agent'];
const knownTelemetryStages = ['planner', 'native_generator', 'native_healer', 'assistant'];
const knownTelemetryOutcomes = ['injected', 'skipped', 'error'];
const knownTelemetrySources = ['spec', 'test_file', 'chat', 'manual_dashboard'];

const emptyForm = {
    id: '',
    kind: 'project_fact',
    memory_type: 'semantic',
    scope: 'project',
    content: '',
    summary: '',
    tags: '',
    confidence: 0.7,
    importance: 0.5,
    agent_type: '',
    review_required: false,
};

const defaultAgentFilters: AgentFilters = {
    q: '',
    kind: 'all',
    type: 'all',
    scope: 'all',
};

const defaultTelemetryFilters: TelemetryFilters = {
    stage: 'all',
    outcome: 'all',
    sourceType: 'all',
};

type MemoryForm = typeof emptyForm;

function pct(value: number) {
    return `${Math.round(value * 100)}%`;
}

function formatDate(value?: string | null) {
    if (!value) return 'Never';
    return new Date(value).toLocaleString();
}

function parseTags(value: string) {
    return value.split(',').map(tag => tag.trim()).filter(Boolean);
}

function compactLabel(value: string) {
    return value.replace(/_/g, ' ');
}

function uniqueSorted(values: Array<string | null | undefined>) {
    return Array.from(new Set(values.filter((value): value is string => Boolean(value)))).sort();
}

function isFailureMessage(message: string) {
    return /failed|error|unable/i.test(message);
}

function telemetryOutcomeTone(outcome: string): 'success' | 'warning' | 'danger' | 'muted' {
    if (/error|failed/i.test(outcome)) return 'danger';
    if (/skip|miss|empty/i.test(outcome)) return 'warning';
    if (/inject|success/i.test(outcome)) return 'success';
    return 'muted';
}

function MetricCard({
    label,
    value,
    tone = 'default',
}: {
    label: string;
    value: string | number;
    tone?: 'default' | 'success' | 'warning' | 'muted';
}) {
    const color = tone === 'success'
        ? 'var(--success)'
        : tone === 'warning'
            ? 'var(--warning)'
            : tone === 'muted'
                ? 'var(--text-secondary)'
                : 'var(--text)';

    return (
        <div className="memory-metric">
            <span>{label}</span>
            <strong style={{ color }}>{value}</strong>
        </div>
    );
}

function Pill({
    children,
    tone = 'default',
}: {
    children: React.ReactNode;
    tone?: 'default' | 'success' | 'warning' | 'danger' | 'muted';
}) {
    return <span className={`memory-pill memory-pill-${tone}`}>{children}</span>;
}

function Field({
    label,
    children,
}: {
    label: string;
    children: React.ReactNode;
}) {
    return (
        <label className="memory-field">
            <span>{label}</span>
            {children}
        </label>
    );
}

function EmptyPanel({
    icon,
    title,
    description,
    action,
}: {
    icon: React.ReactNode;
    title: string;
    description: string;
    action?: React.ReactNode;
}) {
    return (
        <div className="memory-empty">
            <div className="memory-empty-icon">{icon}</div>
            <strong>{title}</strong>
            <p>{description}</p>
            {action}
        </div>
    );
}

export default function MemoryPage() {
    const { currentProject, isLoading: projectLoading } = useProject();
    const projectId = currentProject?.id || 'default';
    const [activeTab, setActiveTab] = useState<'test' | 'agent' | 'graph' | 'telemetry'>('agent');

    const [patterns, setPatterns] = useState<Pattern[]>([]);
    const [stats, setStats] = useState<MemoryStats | null>(null);
    const [browserMemory, setBrowserMemory] = useState<BrowserMemoryBundle | null>(null);
    const [testLoading, setTestLoading] = useState(false);
    const [searchQuery, setSearchQuery] = useState('');
    const [actionFilter, setActionFilter] = useState('all');

    const [memories, setMemories] = useState<AgentMemory[]>([]);
    const [agentLoading, setAgentLoading] = useState(false);
    const [agentFilters, setAgentFilters] = useState<AgentFilters>(defaultAgentFilters);
    const [draftFilters, setDraftFilters] = useState<AgentFilters>(defaultAgentFilters);
    const [statusMessage, setStatusMessage] = useState<string | null>(null);
    const [form, setForm] = useState<MemoryForm>(emptyForm);
    const [editorOpen, setEditorOpen] = useState(false);
    const [deleteTarget, setDeleteTarget] = useState<AgentMemory | null>(null);
    const [contextQuery, setContextQuery] = useState('Generate a reliable test for this project');
    const [contextPreview, setContextPreview] = useState('');
    const [recallQuery, setRecallQuery] = useState('');
    const [recallResults, setRecallResults] = useState<RecallResult[]>([]);
    const [injections, setInjections] = useState<MemoryInjectionEvent[]>([]);
    const [telemetryLoading, setTelemetryLoading] = useState(false);
    const [telemetryFilters, setTelemetryFilters] = useState<TelemetryFilters>(defaultTelemetryFilters);
    const [expandedInjectionId, setExpandedInjectionId] = useState<string | null>(null);
    const [knowledgeGraph, setKnowledgeGraph] = useState<MemoryKnowledgeGraph | null>(null);
    const [graphReviewEdges, setGraphReviewEdges] = useState<MemoryGraphReviewEdge[]>([]);
    const [graphLoading, setGraphLoading] = useState(false);

    const fetchTestMemory = useCallback(async () => {
        setTestLoading(true);
        try {
            const encodedProject = encodeURIComponent(projectId);
            const [patternsRes, statsRes, browserRes] = await Promise.all([
                fetchWithAuth(`${API_BASE}/api/memory/patterns?project_id=${encodedProject}&limit=100`),
                fetchWithAuth(`${API_BASE}/api/memory/stats?project_id=${encodedProject}`),
                fetchWithAuth(`${API_BASE}/api/memory/browser?project_id=${encodedProject}&limit=10`),
            ]);
            if (patternsRes.ok) setPatterns(await patternsRes.json());
            if (statsRes.ok) setStats(await statsRes.json());
            if (browserRes.ok) setBrowserMemory(await browserRes.json());
        } finally {
            setTestLoading(false);
        }
    }, [projectId]);

    const fetchAgentMemory = useCallback(async (filters: AgentFilters = agentFilters) => {
        setAgentLoading(true);
        try {
            const params = new URLSearchParams({ project_id: projectId, limit: '100' });
            if (filters.q.trim()) params.set('q', filters.q.trim());
            if (filters.kind !== 'all') params.append('kind', filters.kind);
            if (filters.type !== 'all') params.append('memory_type', filters.type);
            if (filters.scope !== 'all') params.set('scope', filters.scope);
            const res = await fetchWithAuth(`${API_BASE}/api/memory/agent?${params.toString()}`);
            if (!res.ok) throw new Error((await res.json()).detail || 'Failed to load agent memory');
            setMemories(await res.json());
        } catch (err) {
            setStatusMessage(err instanceof Error ? err.message : 'Failed to load agent memory');
        } finally {
            setAgentLoading(false);
        }
    }, [agentFilters, projectId]);

    const fetchTelemetry = useCallback(async (filters: TelemetryFilters = telemetryFilters) => {
        setTelemetryLoading(true);
        try {
            const params = new URLSearchParams({ project_id: projectId, limit: '100' });
            if (filters.stage !== 'all') params.set('stage', filters.stage);
            if (filters.outcome !== 'all') params.set('outcome', filters.outcome);
            if (filters.sourceType !== 'all') params.set('source_type', filters.sourceType);
            const res = await fetchWithAuth(`${API_BASE}/api/memory/injections?${params.toString()}`);
            if (!res.ok) throw new Error((await res.json()).detail || 'Failed to load memory telemetry');
            setInjections(await res.json());
        } catch (err) {
            setStatusMessage(err instanceof Error ? err.message : 'Failed to load memory telemetry');
        } finally {
            setTelemetryLoading(false);
        }
    }, [projectId, telemetryFilters]);

    const fetchKnowledgeGraph = useCallback(async () => {
        setGraphLoading(true);
        try {
            const params = new URLSearchParams({ project_id: projectId, limit: '200' });
            const res = await fetchWithAuth(`${API_BASE}/api/memory/graph/knowledge?${params.toString()}`);
            if (!res.ok) throw new Error((await res.json()).detail || 'Failed to load memory graph');
            setKnowledgeGraph(await res.json());
        } catch (err) {
            setStatusMessage(err instanceof Error ? err.message : 'Failed to load memory graph');
        } finally {
            setGraphLoading(false);
        }
    }, [projectId]);

    const fetchGraphReview = useCallback(async () => {
        try {
            const params = new URLSearchParams({ project_id: projectId, limit: '100' });
            const res = await fetchWithAuth(`${API_BASE}/api/memory/graph/review?${params.toString()}`);
            if (!res.ok) throw new Error((await res.json()).detail || 'Failed to load graph review queue');
            const data = await res.json();
            setGraphReviewEdges(data.edges || []);
        } catch (err) {
            setStatusMessage(err instanceof Error ? err.message : 'Failed to load graph review queue');
        }
    }, [projectId]);

    useEffect(() => {
        if (projectLoading) return;
        fetchAgentMemory(agentFilters);
        fetchTestMemory();
        fetchTelemetry(telemetryFilters);
        fetchKnowledgeGraph();
        fetchGraphReview();
    }, [agentFilters, fetchAgentMemory, fetchGraphReview, fetchKnowledgeGraph, fetchTelemetry, fetchTestMemory, projectLoading, telemetryFilters]);

    const filteredPatterns = useMemo(
        () => patterns.filter(pattern => actionFilter === 'all' || pattern.action === actionFilter),
        [patterns, actionFilter]
    );

    const memoryCounts = useMemo(() => ({
        total: memories.length,
        review: memories.filter(memory => memory.review_required).length,
        active: memories.filter(memory => memory.status === 'active' && !memory.review_required).length,
        archived: memories.filter(memory => memory.status !== 'active').length,
    }), [memories]);

    const activeFilterCount = useMemo(() => {
        return [
            agentFilters.q.trim(),
            agentFilters.kind !== 'all',
            agentFilters.type !== 'all',
            agentFilters.scope !== 'all',
        ].filter(Boolean).length;
    }, [agentFilters]);

    const telemetryCounts = useMemo(() => {
        const uniqueMemoryIds = new Set(injections.flatMap(event => event.memory_ids || []));
        const stageCounts = injections.reduce<Record<string, number>>((acc, event) => {
            acc[event.stage] = (acc[event.stage] || 0) + 1;
            return acc;
        }, {});
        const topStage = Object.entries(stageCounts).sort((a, b) => b[1] - a[1])[0]?.[0];
        return {
            total: injections.length,
            uniqueMemories: uniqueMemoryIds.size,
            last: injections[0]?.created_at,
            topStage,
        };
    }, [injections]);

    const telemetryOptions = useMemo(() => ({
        stages: uniqueSorted([
            ...knownTelemetryStages,
            telemetryFilters.stage !== 'all' ? telemetryFilters.stage : null,
            ...injections.map(event => event.stage),
        ]),
        outcomes: uniqueSorted([
            ...knownTelemetryOutcomes,
            telemetryFilters.outcome !== 'all' ? telemetryFilters.outcome : null,
            ...injections.map(event => event.outcome),
        ]),
        sourceTypes: uniqueSorted([
            ...knownTelemetrySources,
            telemetryFilters.sourceType !== 'all' ? telemetryFilters.sourceType : null,
            ...injections.map(event => event.source_type),
        ]),
    }), [injections, telemetryFilters]);

    const graphNodeById = useMemo(() => {
        return new Map((knowledgeGraph?.nodes || []).map(node => [node.id, node]));
    }, [knowledgeGraph]);

    const graphTopNodes = useMemo(() => {
        return [...(knowledgeGraph?.nodes || [])]
            .sort((a, b) => (b.confidence || 0) - (a.confidence || 0))
            .slice(0, 12);
    }, [knowledgeGraph]);

    async function rebuildKnowledgeGraph() {
        setGraphLoading(true);
        try {
            const params = new URLSearchParams({ project_id: projectId });
            const res = await fetchWithAuth(`${API_BASE}/api/memory/graph/rebuild?${params.toString()}`, { method: 'POST' });
            if (!res.ok) throw new Error((await res.json()).detail || 'Failed to rebuild memory graph');
            const result = await res.json();
            setStatusMessage(`Rebuilt graph from ${result.memories} memories`);
            await fetchKnowledgeGraph();
            await fetchGraphReview();
        } catch (err) {
            setStatusMessage(err instanceof Error ? err.message : 'Failed to rebuild memory graph');
        } finally {
            setGraphLoading(false);
        }
    }

    async function graphReviewAction(edge: MemoryGraphReviewEdge, action: 'approve' | 'reject') {
        setStatusMessage(null);
        const params = new URLSearchParams({ project_id: projectId });
        const res = await fetchWithAuth(`${API_BASE}/api/memory/graph/review/${encodeURIComponent(edge.id)}/${action}?${params.toString()}`, { method: 'PATCH' });
        if (!res.ok) {
            const error = await res.json().catch(() => ({}));
            setStatusMessage(error.detail || `Failed to ${action} graph relationship`);
            return;
        }
        setStatusMessage(`Graph relationship ${action === 'approve' ? 'approved' : 'rejected'}.`);
        await fetchKnowledgeGraph();
        await fetchGraphReview();
    }

    async function handlePatternSearch() {
        if (!searchQuery.trim()) {
            fetchTestMemory();
            return;
        }
        const res = await fetchWithAuth(`${API_BASE}/api/memory/similar`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                description: searchQuery,
                n_results: 10,
                min_success_rate: 0,
                project_id: projectId,
            }),
        });
        if (res.ok) setPatterns(await res.json());
    }

    async function saveMemory() {
        setStatusMessage(null);
        const payload = {
            kind: form.kind,
            memory_type: form.memory_type,
            scope: form.scope,
            content: form.content,
            summary: form.summary || undefined,
            tags: parseTags(form.tags),
            confidence: Number(form.confidence),
            importance: Number(form.importance),
            agent_type: form.agent_type || undefined,
            review_required: form.review_required,
            project_id: form.scope === 'global' ? undefined : projectId,
            source_type: form.id ? undefined : 'manual_dashboard',
        };
        const url = form.id
            ? `${API_BASE}/api/memory/agent/${encodeURIComponent(form.id)}?project_id=${encodeURIComponent(projectId)}`
            : `${API_BASE}/api/memory/agent`;
        const res = await fetchWithAuth(url, {
            method: form.id ? 'PATCH' : 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        if (!res.ok) {
            const error = await res.json().catch(() => ({}));
            setStatusMessage(error.detail || 'Failed to save memory');
            return;
        }
        setForm(emptyForm);
        setEditorOpen(false);
        setStatusMessage('Memory saved.');
        fetchAgentMemory(agentFilters);
    }

    async function memoryAction(memory: AgentMemory, action: 'approve' | 'verify' | 'archive' | 'delete') {
        setStatusMessage(null);
        const guard = `project_id=${encodeURIComponent(projectId)}`;
        const method = action === 'delete' ? 'DELETE' : 'PATCH';
        const suffix = action === 'delete' ? '' : `/${action}`;
        const res = await fetchWithAuth(`${API_BASE}/api/memory/agent/${encodeURIComponent(memory.id)}${suffix}?${guard}`, { method });
        if (!res.ok) {
            const error = await res.json().catch(() => ({}));
            setStatusMessage(error.detail || `Failed to ${action} memory`);
            return;
        }
        setStatusMessage(`Memory ${action === 'delete' ? 'deleted' : `${action}d`}.`);
        fetchAgentMemory(agentFilters);
    }

    function startCreateMemory() {
        setForm(emptyForm);
        setEditorOpen(true);
    }

    function editMemory(memory: AgentMemory) {
        setForm({
            id: memory.id,
            kind: memory.kind,
            memory_type: memory.memory_type,
            scope: memory.scope,
            content: memory.content,
            summary: memory.summary || '',
            tags: (memory.tags || []).join(', '),
            confidence: memory.confidence,
            importance: memory.importance,
            agent_type: memory.agent_type || '',
            review_required: memory.review_required,
        });
        setEditorOpen(true);
    }

    function closeEditor() {
        setEditorOpen(false);
        setForm(emptyForm);
    }

    function applyFilters() {
        setAgentFilters(draftFilters);
    }

    function clearFilters() {
        setDraftFilters(defaultAgentFilters);
        setAgentFilters(defaultAgentFilters);
    }

    async function previewContext() {
        const params = new URLSearchParams({
            project_id: projectId,
            q: contextQuery,
            agent_type: 'assistant',
            limit: '8',
        });
        const res = await fetchWithAuth(`${API_BASE}/api/memory/context-preview?${params.toString()}`);
        if (!res.ok) {
            setContextPreview('Failed to load context preview.');
            return;
        }
        const data = await res.json();
        setContextPreview(data.context || 'No memory would be injected for this query.');
    }

    async function searchRecall() {
        const params = new URLSearchParams({ project_id: projectId, limit: '8' });
        const endpoint = recallQuery.trim()
            ? `/api/memory/session-recall/search?${new URLSearchParams({ ...Object.fromEntries(params), q: recallQuery.trim() }).toString()}`
            : `/api/memory/session-recall/recent?${params.toString()}`;
        const res = await fetchWithAuth(`${API_BASE}${endpoint}`);
        if (res.ok) setRecallResults(await res.json());
    }

    if (projectLoading) {
        return (
            <PageLayout tier="wide">
                <DashboardPageSkeleton />
            </PageLayout>
        );
    }

    const actionCounts = stats?.action_breakdown || {};
    const browserStateCount = browserMemory?.states.length ?? 0;
    const browserElementCount = browserMemory?.elements.length ?? 0;
    const browserFrontierCount = browserMemory?.frontier.length ?? 0;

    return (
        <PageLayout tier="wide" className="memory-page">
            <PageHeader
                title="Memory"
                subtitle="Curate prompt-ready agent memory, inspect test patterns, and preview recall context."
                icon={<Database size={20} />}
                actions={
                    <div className="memory-header-actions">
                        {activeTab === 'agent' && (
                            <button className="btn btn-primary" onClick={startCreateMemory}>
                                <Plus size={16} />
                                New memory
                            </button>
                        )}
                        <button className="btn" onClick={() => { fetchAgentMemory(agentFilters); fetchTestMemory(); fetchTelemetry(telemetryFilters); fetchKnowledgeGraph(); fetchGraphReview(); }}>
                            <RefreshCw size={16} />
                            Refresh
                        </button>
                    </div>
                }
            />

            <div className="memory-tabs" role="tablist" aria-label="Memory sections">
                <button
                    className={activeTab === 'agent' ? 'memory-tab active' : 'memory-tab'}
                    onClick={() => setActiveTab('agent')}
                    role="tab"
                    aria-selected={activeTab === 'agent'}
                >
                    <ShieldCheck size={16} />
                    Agent Memory
                </button>
                <button
                    className={activeTab === 'test' ? 'memory-tab active' : 'memory-tab'}
                    onClick={() => setActiveTab('test')}
                    role="tab"
                    aria-selected={activeTab === 'test'}
                >
                    <Database size={16} />
                    Test Memory
                </button>
                <button
                    className={activeTab === 'graph' ? 'memory-tab active' : 'memory-tab'}
                    onClick={() => setActiveTab('graph')}
                    role="tab"
                    aria-selected={activeTab === 'graph'}
                >
                    <GitBranch size={16} />
                    Graph
                </button>
                <button
                    className={activeTab === 'telemetry' ? 'memory-tab active' : 'memory-tab'}
                    onClick={() => setActiveTab('telemetry')}
                    role="tab"
                    aria-selected={activeTab === 'telemetry'}
                >
                    <Activity size={16} />
                    Telemetry
                </button>
            </div>

            {statusMessage && (
                <div className={isFailureMessage(statusMessage) ? 'memory-alert danger' : 'memory-alert success'} role="status">
                    {statusMessage}
                </div>
            )}

            {activeTab === 'agent' ? (
                <div className="memory-agent-stack">
                    <section className="memory-metrics" aria-label="Agent memory summary">
                        <MetricCard label="Total" value={memoryCounts.total} />
                        <MetricCard label="Ready" value={memoryCounts.active} tone="success" />
                        <MetricCard label="Needs review" value={memoryCounts.review} tone="warning" />
                        <MetricCard label="Archived" value={memoryCounts.archived} tone="muted" />
                    </section>

                    <div className={editorOpen ? 'memory-curation-grid editor-open' : 'memory-curation-grid'}>
                        <main className="memory-main">
                            <section className="memory-panel">
                                <div className="memory-panel-heading">
                                    <div>
                                        <h2>Agent memories</h2>
                                        <p>
                                            {activeFilterCount > 0
                                                ? `${activeFilterCount} active filter${activeFilterCount === 1 ? '' : 's'}`
                                                : 'Project-scoped memories ready for curation'}
                                        </p>
                                    </div>
                                </div>

                                <div className="memory-toolbar">
                                    <div className="memory-search">
                                        <Search size={16} />
                                        <input
                                            className="input"
                                            value={draftFilters.q}
                                            onChange={event => setDraftFilters({ ...draftFilters, q: event.target.value })}
                                            onKeyDown={event => event.key === 'Enter' && applyFilters()}
                                            aria-label="Search agent memories"
                                            placeholder="Search memories..."
                                        />
                                    </div>
                                    <select
                                        className="input"
                                        value={draftFilters.kind}
                                        onChange={event => setDraftFilters({ ...draftFilters, kind: event.target.value })}
                                        aria-label="Filter by memory kind"
                                    >
                                        <option value="all">All kinds</option>
                                        {memoryKinds.map(kind => <option key={kind} value={kind}>{compactLabel(kind)}</option>)}
                                    </select>
                                    <select
                                        className="input"
                                        value={draftFilters.type}
                                        onChange={event => setDraftFilters({ ...draftFilters, type: event.target.value })}
                                        aria-label="Filter by memory type"
                                    >
                                        <option value="all">All types</option>
                                        {memoryTypes.map(type => <option key={type} value={type}>{type}</option>)}
                                    </select>
                                    <select
                                        className="input"
                                        value={draftFilters.scope}
                                        onChange={event => setDraftFilters({ ...draftFilters, scope: event.target.value })}
                                        aria-label="Filter by memory scope"
                                    >
                                        <option value="all">All scopes</option>
                                        {memoryScopes.map(scope => <option key={scope} value={scope}>{scope}</option>)}
                                    </select>
                                    <button className="btn" onClick={applyFilters}>
                                        <Filter size={16} />
                                        Apply
                                    </button>
                                    <button className="btn memory-quiet-button" onClick={clearFilters}>
                                        Clear
                                    </button>
                                </div>

                                {agentLoading ? (
                                    <div className="memory-loading">Loading agent memory...</div>
                                ) : memories.length === 0 ? (
                                    <EmptyPanel
                                        icon={<ShieldCheck size={22} />}
                                        title={activeFilterCount > 0 ? 'No matching memories' : 'No agent memories yet'}
                                        description={activeFilterCount > 0
                                            ? 'Clear filters or broaden the search to see more memories.'
                                            : 'Create a memory to make durable project knowledge available to the assistant.'}
                                        action={
                                            activeFilterCount > 0 ? (
                                                <button className="btn" onClick={clearFilters}>Clear filters</button>
                                            ) : (
                                                <button className="btn btn-primary" onClick={startCreateMemory}>
                                                    <Plus size={16} />
                                                    New memory
                                                </button>
                                            )
                                        }
                                    />
                                ) : (
                                    <div className="memory-list">
                                        {memories.map(memory => {
                                            const title = memory.summary || memory.content.slice(0, 120);
                                            return (
                                                <article key={memory.id} className="memory-card">
                                                    <div className="memory-card-body">
                                                        <div className="memory-card-title-row">
                                                            <h3>{title}</h3>
                                                            <div className="memory-card-status">
                                                                {memory.review_required && <Pill tone="warning">Needs review</Pill>}
                                                                {memory.status !== 'active' && <Pill tone="muted">{memory.status}</Pill>}
                                                            </div>
                                                        </div>
                                                        <p>{memory.content}</p>
                                                        <div className="memory-card-chips">
                                                            <Pill>{compactLabel(memory.kind)}</Pill>
                                                            <Pill>{memory.memory_type}</Pill>
                                                            <Pill>{memory.scope}</Pill>
                                                            <Pill tone={memory.confidence >= 0.75 ? 'success' : 'muted'}>Confidence {pct(memory.confidence)}</Pill>
                                                            <Pill tone={memory.importance >= 0.75 ? 'warning' : 'muted'}>Importance {pct(memory.importance)}</Pill>
                                                        </div>
                                                        <div className="memory-card-meta">
                                                            <span>Used {memory.use_count}</span>
                                                            <span>Verified {formatDate(memory.last_verified_at)}</span>
                                                            <span>Updated {formatDate(memory.updated_at)}</span>
                                                            {memory.source_type && (
                                                                <span>Source {memory.source_type}{memory.source_id ? `:${memory.source_id}` : ''}</span>
                                                            )}
                                                        </div>
                                                        {memory.tags?.length > 0 && (
                                                            <div className="memory-tags">
                                                                {memory.tags.map(tag => <span key={tag}>#{tag}</span>)}
                                                            </div>
                                                        )}
                                                    </div>
                                                    <div className="memory-card-actions" aria-label={`Actions for ${title}`}>
                                                        <button className="btn memory-action-button" onClick={() => editMemory(memory)}>
                                                            <Edit3 size={14} />
                                                            Edit
                                                        </button>
                                                        {memory.review_required && (
                                                            <button className="btn memory-action-button" onClick={() => memoryAction(memory, 'approve')}>
                                                                <CheckCircle size={14} />
                                                                Approve
                                                            </button>
                                                        )}
                                                        <button className="btn memory-action-button" onClick={() => memoryAction(memory, 'verify')}>
                                                            <ShieldCheck size={14} />
                                                            Verify
                                                        </button>
                                                        <button className="btn memory-action-button" onClick={() => memoryAction(memory, 'archive')}>
                                                            <Archive size={14} />
                                                            Archive
                                                        </button>
                                                        <button className="btn memory-action-button danger" onClick={() => setDeleteTarget(memory)}>
                                                            <Trash2 size={14} />
                                                            Delete
                                                        </button>
                                                    </div>
                                                </article>
                                            );
                                        })}
                                    </div>
                                )}
                            </section>
                        </main>

                        {editorOpen && (
                            <aside className="memory-editor-panel" aria-label={form.id ? 'Edit memory' : 'Create memory'}>
                                <div className="memory-editor-header">
                                    <div>
                                        <h2>{form.id ? 'Edit memory' : 'Create memory'}</h2>
                                        <p>{form.id ? 'Update the selected memory before it is reused.' : 'Add durable project knowledge for future assistant context.'}</p>
                                    </div>
                                    <button className="btn-icon memory-close-button" onClick={closeEditor} aria-label="Close editor">
                                        <X size={18} />
                                    </button>
                                </div>

                                <div className="memory-form-grid">
                                    <Field label="Kind">
                                        <select className="input" value={form.kind} onChange={event => setForm({ ...form, kind: event.target.value })}>
                                            {memoryKinds.map(kind => <option key={kind} value={kind}>{compactLabel(kind)}</option>)}
                                        </select>
                                    </Field>
                                    <Field label="Type">
                                        <select className="input" value={form.memory_type} onChange={event => setForm({ ...form, memory_type: event.target.value })}>
                                            {memoryTypes.map(type => <option key={type} value={type}>{type}</option>)}
                                        </select>
                                    </Field>
                                    <Field label="Scope">
                                        <select className="input" value={form.scope} onChange={event => setForm({ ...form, scope: event.target.value })}>
                                            {memoryScopes.map(scope => <option key={scope} value={scope}>{scope}</option>)}
                                        </select>
                                    </Field>
                                    <Field label="Agent type">
                                        <input className="input" value={form.agent_type} onChange={event => setForm({ ...form, agent_type: event.target.value })} placeholder="assistant" />
                                    </Field>
                                </div>

                                <Field label="Summary">
                                    <input className="input" value={form.summary} onChange={event => setForm({ ...form, summary: event.target.value })} placeholder="Short recall label" />
                                </Field>
                                <Field label="Content">
                                    <textarea className="input memory-textarea" value={form.content} onChange={event => setForm({ ...form, content: event.target.value })} rows={7} placeholder="What should the assistant remember?" />
                                </Field>
                                <Field label="Tags">
                                    <input className="input" value={form.tags} onChange={event => setForm({ ...form, tags: event.target.value })} placeholder="login, selector, preference" />
                                </Field>

                                <div className="memory-form-grid">
                                    <Field label={`Confidence ${pct(Number(form.confidence))}`}>
                                        <input className="input memory-range" type="range" min="0" max="1" step="0.05" value={form.confidence} onChange={event => setForm({ ...form, confidence: Number(event.target.value) })} />
                                    </Field>
                                    <Field label={`Importance ${pct(Number(form.importance))}`}>
                                        <input className="input memory-range" type="range" min="0" max="1" step="0.05" value={form.importance} onChange={event => setForm({ ...form, importance: Number(event.target.value) })} />
                                    </Field>
                                </div>

                                <label className="memory-checkbox">
                                    <input type="checkbox" checked={form.review_required} onChange={event => setForm({ ...form, review_required: event.target.checked })} />
                                    <span>Require review before prompt injection</span>
                                </label>

                                <div className="memory-editor-actions">
                                    <button className="btn btn-primary" onClick={saveMemory} disabled={!form.content.trim()}>
                                        <Save size={16} />
                                        Save memory
                                    </button>
                                    <button className="btn" onClick={closeEditor}>Cancel</button>
                                </div>
                            </aside>
                        )}
                    </div>

                    <section className="memory-support-grid">
                        <div className="memory-panel">
                            <div className="memory-tool-heading">
                                <Eye size={18} />
                                <div>
                                    <h2>Context preview</h2>
                                    <p>Check what memory would be injected for a prompt.</p>
                                </div>
                            </div>
                            <div className="memory-inline-form">
                                <input className="input" value={contextQuery} onChange={event => setContextQuery(event.target.value)} aria-label="Context preview prompt" />
                                <button className="btn" onClick={previewContext}>
                                    <Eye size={16} />
                                    Preview
                                </button>
                            </div>
                            {contextPreview && <pre className="memory-preview">{contextPreview}</pre>}
                        </div>

                        <div className="memory-panel">
                            <div className="memory-tool-heading">
                                <MessageSquareText size={18} />
                                <div>
                                    <h2>Session recall</h2>
                                    <p>Find recent or matching conversations for the project.</p>
                                </div>
                            </div>
                            <div className="memory-inline-form">
                                <input
                                    className="input"
                                    value={recallQuery}
                                    onChange={event => setRecallQuery(event.target.value)}
                                    onKeyDown={event => event.key === 'Enter' && searchRecall()}
                                    aria-label="Search session recall"
                                    placeholder="Search prior conversations, or leave blank for recent..."
                                />
                                <button className="btn" onClick={searchRecall}>
                                    <Search size={16} />
                                    Recall
                                </button>
                            </div>
                            <div className="memory-recall-list">
                                {recallResults.map(result => (
                                    <div key={`${result.conversation_id}-${result.match_message_id || 'recent'}`} className="memory-recall-item">
                                        <strong>{result.title}</strong>
                                        <p>{result.snippet || 'Recent conversation'}</p>
                                        <small>{formatDate(result.updated_at)}{result.match_message_id ? ` - anchor ${result.match_message_id}` : ''}</small>
                                    </div>
                                ))}
                            </div>
                        </div>
                    </section>
                </div>
            ) : activeTab === 'test' ? (
                <div className="memory-test-stack">
                    {testLoading ? <DashboardPageSkeleton /> : (
                        <>
                            <section className="memory-metrics" aria-label="Test memory summary">
                                <MetricCard label="Total patterns" value={stats?.total_patterns ?? patterns.length} />
                                <MetricCard label="Success rate" value={stats ? `${stats.avg_success_rate.toFixed(1)}%` : 'No data'} tone="success" />
                                <MetricCard label="Actions tracked" value={Object.keys(actionCounts).length} tone="muted" />
                                <MetricCard label="Browser states" value={browserStateCount} tone={browserStateCount ? 'success' : 'muted'} />
                            </section>

                            {Object.keys(actionCounts).length > 0 && (
                                <section className="memory-panel">
                                    <div className="memory-panel-heading">
                                        <div>
                                            <h2>Action breakdown</h2>
                                            <p>Filter stored patterns by automation action.</p>
                                        </div>
                                        {actionFilter !== 'all' && (
                                            <button className="btn memory-quiet-button" onClick={() => setActionFilter('all')}>Show all</button>
                                        )}
                                    </div>
                                    <div className="memory-action-chips">
                                        {Object.entries(actionCounts).map(([action, count]) => (
                                            <button key={action} className={actionFilter === action ? 'memory-chip active' : 'memory-chip'} onClick={() => setActionFilter(actionFilter === action ? 'all' : action)}>
                                                {action}
                                                <span>{count}</span>
                                            </button>
                                        ))}
                                    </div>
                                </section>
                            )}

                            <section className="memory-panel">
                                <div className="memory-tool-heading">
                                    <Sparkles size={18} />
                                    <div>
                                        <h2>Semantic search</h2>
                                        <p>Find proven test patterns by describing the test goal.</p>
                                    </div>
                                </div>
                                <div className="memory-inline-form">
                                    <input
                                        className="input"
                                        value={searchQuery}
                                        onChange={event => setSearchQuery(event.target.value)}
                                        onKeyDown={event => event.key === 'Enter' && handlePatternSearch()}
                                        aria-label="Search test memory patterns"
                                        placeholder="Describe what you want to test..."
                                    />
                                    <button className="btn btn-primary" onClick={handlePatternSearch}>
                                        <Search size={16} />
                                        Search
                                    </button>
                                </div>
                            </section>

                            <section className="memory-panel">
                                <div className="memory-panel-heading">
                                    <div>
                                        <h2>Browser exploration memory</h2>
                                        <p>{browserStateCount} states, {browserElementCount} elements, {browserFrontierCount} frontier items</p>
                                    </div>
                                    <Pill tone={browserFrontierCount ? 'success' : 'muted'}>
                                        {browserFrontierCount ? 'Frontier ready' : 'No frontier'}
                                    </Pill>
                                </div>
                                {!browserMemory || (browserStateCount === 0 && browserElementCount === 0 && browserFrontierCount === 0) ? (
                                    <EmptyPanel
                                        icon={<Database size={22} />}
                                        title="No browser memory yet"
                                        description="Run an exploration with live browser snapshots, then refresh this page to inspect states, locators, and frontier work."
                                    />
                                ) : (
                                    <div className="memory-pattern-list">
                                        {browserMemory.frontier.slice(0, 6).map(item => {
                                            const locator = item.best_locator?.locator || 'Rediscover from live snapshot';
                                            const score = item.rank_score ?? item.priority_score ?? 0;
                                            return (
                                                <article key={item.id} className="memory-pattern-card">
                                                    <div>
                                                        <h3>{item.action_type}: {item.name || item.text || item.role || 'frontier item'}</h3>
                                                        <p>{locator}</p>
                                                        <div className="memory-card-meta">
                                                            <span>URL: {item.state_url || item.state_url_template || 'Unknown'}</span>
                                                            <span>Source: {item.state_source_fidelity || 'unknown'}</span>
                                                            <span>Attempts: {item.attempts ?? 0}</span>
                                                        </div>
                                                    </div>
                                                    <div className="memory-card-status">
                                                        <Pill tone={item.risk_level === 'high' ? 'danger' : item.risk_level === 'medium' ? 'warning' : 'success'}>
                                                            {item.risk_level || 'low'}
                                                        </Pill>
                                                        <Pill tone="muted">{Math.round(score * 100)} rank</Pill>
                                                    </div>
                                                </article>
                                            );
                                        })}
                                        {browserMemory.frontier.length === 0 && browserMemory.elements.slice(0, 6).map(element => {
                                            const locator = element.best_locator?.locator || 'No locator captured';
                                            return (
                                                <article key={element.id} className="memory-pattern-card">
                                                    <div>
                                                        <h3>{element.role || 'element'}: {element.name || 'Unnamed element'}</h3>
                                                        <p>{locator}</p>
                                                        <div className="memory-card-meta">
                                                            <span>Source: {element.source_fidelity || 'unknown'}</span>
                                                            <span>Seen: {formatDate(element.last_seen_at)}</span>
                                                            <span>Tested: {element.tested_count ?? 0}</span>
                                                        </div>
                                                    </div>
                                                    <Pill tone="muted">{Math.round((element.importance_score ?? 0) * 100)} importance</Pill>
                                                </article>
                                            );
                                        })}
                                    </div>
                                )}
                            </section>

                            <section className="memory-panel">
                                <div className="memory-panel-heading">
                                    <div>
                                        <h2>Stored patterns</h2>
                                        <p>{filteredPatterns.length} pattern{filteredPatterns.length === 1 ? '' : 's'} visible</p>
                                    </div>
                                </div>
                                {filteredPatterns.length === 0 ? (
                                    <EmptyPanel
                                        icon={<Database size={22} />}
                                        title="No patterns found"
                                        description="Run an exploration or broaden the semantic search to populate reusable test patterns."
                                    />
                                ) : (
                                    <div className="memory-pattern-list">
                                        {filteredPatterns.map(pattern => {
                                            const healthy = pattern.success_rate >= 0.9;
                                            return (
                                                <article key={pattern.id} className="memory-pattern-card">
                                                    <div>
                                                        <h3>{pattern.action}: {pattern.target}</h3>
                                                        <div className="memory-card-meta">
                                                            <span><Clock size={14} /> {pattern.avg_duration.toFixed(0)}ms avg</span>
                                                            <span>Test: {pattern.test_name}</span>
                                                        </div>
                                                    </div>
                                                    <Pill tone={healthy ? 'success' : 'danger'}>
                                                        {healthy ? <CheckCircle size={14} /> : <XCircle size={14} />}
                                                        {(pattern.success_rate * 100).toFixed(0)}%
                                                    </Pill>
                                                </article>
                                            );
                                        })}
                                    </div>
                                )}
                            </section>
                        </>
                    )}
                </div>
            ) : activeTab === 'graph' ? (
                <div className="memory-graph-stack">
                    <section className="memory-metrics" aria-label="Memory graph summary">
                        <MetricCard label="Nodes" value={knowledgeGraph?.stats.node_count ?? 0} tone={(knowledgeGraph?.stats.node_count ?? 0) ? 'success' : 'muted'} />
                        <MetricCard label="Edges" value={knowledgeGraph?.stats.edge_count ?? 0} tone={(knowledgeGraph?.stats.edge_count ?? 0) ? 'success' : 'muted'} />
                        <MetricCard label="Memory nodes" value={knowledgeGraph?.stats.node_types.memory ?? 0} tone="muted" />
                        <MetricCard label="Pending review" value={graphReviewEdges.length} tone={graphReviewEdges.length ? 'warning' : 'muted'} />
                    </section>

                    <section className="memory-panel">
                        <div className="memory-panel-heading">
                            <div>
                                <h2>LLM relationship review</h2>
                                <p>Risky LLM-inferred graph relationships wait here before they affect retrieval.</p>
                            </div>
                            <button className="btn" onClick={fetchGraphReview}>
                                <RefreshCw size={16} />
                                Refresh
                            </button>
                        </div>

                        {graphReviewEdges.length === 0 ? (
                            <EmptyPanel
                                icon={<ShieldCheck size={22} />}
                                title="No pending graph relationships"
                                description="LLM-inferred contradictions, supersedes links, and root-cause links will appear here for review."
                            />
                        ) : (
                            <div className="memory-graph-review-list">
                                {graphReviewEdges.map(edge => (
                                    <article key={edge.id} className="memory-graph-review-card">
                                        <div className="memory-graph-review-main">
                                            <div className="memory-card-title-row">
                                                <h3>{compactLabel(edge.relationship_type)}</h3>
                                                <div className="memory-card-status">
                                                    <Pill tone="warning">Pending</Pill>
                                                    <Pill tone="muted">{Math.round((edge.weight || 0) * 100)} confidence</Pill>
                                                </div>
                                            </div>
                                            <p>{edge.source_node?.label || edge.source_node_id}{' -> '}{edge.target_node?.label || edge.target_node_id}</p>
                                            {typeof edge.extra_data?.evidence === 'string' && edge.extra_data.evidence && (
                                                <pre className="memory-review-evidence">{edge.extra_data.evidence}</pre>
                                            )}
                                            <div className="memory-card-meta">
                                                <span>Extractor {String(edge.extra_data?.extractor || 'llm')}</span>
                                                <span>Rule {String(edge.extra_data?.rule || 'llm_extraction')}</span>
                                                {edge.evidence_memory_id && <span>Evidence {edge.evidence_memory_id.slice(0, 8)}</span>}
                                                <span>{formatDate(edge.updated_at)}</span>
                                            </div>
                                        </div>
                                        <div className="memory-card-actions">
                                            <button className="btn memory-action-button" onClick={() => graphReviewAction(edge, 'approve')}>
                                                <CheckCircle size={14} />
                                                Approve
                                            </button>
                                            <button className="btn memory-action-button danger" onClick={() => graphReviewAction(edge, 'reject')}>
                                                <XCircle size={14} />
                                                Reject
                                            </button>
                                        </div>
                                    </article>
                                ))}
                            </div>
                        )}
                    </section>

                    <section className="memory-panel">
                        <div className="memory-panel-heading">
                            <div>
                                <h2>Knowledge graph</h2>
                                <p>Typed links between memories, topics, pages, workflows, failures, and selector evidence.</p>
                            </div>
                            <button className="btn" onClick={rebuildKnowledgeGraph} disabled={graphLoading}>
                                <RefreshCw size={16} />
                                Rebuild
                            </button>
                        </div>

                        {graphLoading ? (
                            <div className="memory-loading">Loading memory graph...</div>
                        ) : !knowledgeGraph || knowledgeGraph.nodes.length === 0 ? (
                            <EmptyPanel
                                icon={<GitBranch size={22} />}
                                title="No graph nodes yet"
                                description="Create or approve agent memories, then rebuild the graph to inspect relationships."
                            />
                        ) : (
                            <div className="memory-graph-layout">
                                <div className="memory-graph-column">
                                    <h3>High-confidence nodes</h3>
                                    <div className="memory-graph-list">
                                        {graphTopNodes.map(node => (
                                            <article key={node.id} className="memory-graph-card">
                                                <div>
                                                    <div className="memory-card-title-row">
                                                        <h4>{node.label}</h4>
                                                        <Pill tone={node.node_type === 'memory' ? 'success' : node.node_type === 'failure' ? 'danger' : 'muted'}>
                                                            {compactLabel(node.node_type)}
                                                        </Pill>
                                                    </div>
                                                    <div className="memory-card-meta">
                                                        <span>{Math.round((node.confidence || 0) * 100)} confidence</span>
                                                        {node.memory_id && <span>Memory {node.memory_id.slice(0, 8)}</span>}
                                                        <span>{formatDate(node.updated_at)}</span>
                                                    </div>
                                                </div>
                                            </article>
                                        ))}
                                    </div>
                                </div>
                                <div className="memory-graph-column">
                                    <h3>Relationships</h3>
                                    <div className="memory-graph-list">
                                        {knowledgeGraph.edges.slice(0, 16).map(edge => {
                                            const source = graphNodeById.get(edge.source_node_id);
                                            const target = graphNodeById.get(edge.target_node_id);
                                            return (
                                                <article key={edge.id} className="memory-graph-card">
                                                    <div>
                                                        <div className="memory-card-title-row">
                                                            <h4>{compactLabel(edge.relationship_type)}</h4>
                                                            <Pill tone="muted">{Math.round((edge.weight || 0) * 100)} weight</Pill>
                                                        </div>
                                                        <p>{source?.label || edge.source_node_id}{' -> '}{target?.label || edge.target_node_id}</p>
                                                        <div className="memory-card-meta">
                                                            {edge.evidence_memory_id && <span>Evidence {edge.evidence_memory_id.slice(0, 8)}</span>}
                                                            <span>{formatDate(edge.updated_at)}</span>
                                                        </div>
                                                    </div>
                                                </article>
                                            );
                                        })}
                                    </div>
                                </div>
                            </div>
                        )}
                    </section>
                </div>
            ) : (
                <div className="memory-telemetry-stack">
                    <section className="memory-metrics" aria-label="Memory telemetry summary">
                        <MetricCard label="Total injections" value={telemetryCounts.total} />
                        <MetricCard label="Last injection" value={telemetryCounts.last ? new Date(telemetryCounts.last).toLocaleDateString() : 'Never'} tone={telemetryCounts.last ? 'success' : 'muted'} />
                        <MetricCard label="Unique memories" value={telemetryCounts.uniqueMemories} tone={telemetryCounts.uniqueMemories ? 'success' : 'muted'} />
                        <MetricCard label="Top stage" value={telemetryCounts.topStage ? compactLabel(telemetryCounts.topStage) : 'No data'} tone={telemetryCounts.topStage ? 'warning' : 'muted'} />
                    </section>

                    <section className="memory-panel">
                        <div className="memory-panel-heading">
                            <div>
                                <h2>Memory injection telemetry</h2>
                                <p>Recent prompt context injections for the current project.</p>
                            </div>
                        </div>

                        <div className="memory-telemetry-toolbar">
                            <select
                                className="input"
                                value={telemetryFilters.stage}
                                onChange={event => setTelemetryFilters({ ...telemetryFilters, stage: event.target.value })}
                                aria-label="Filter telemetry by stage"
                            >
                                <option value="all">All stages</option>
                                {telemetryOptions.stages.map(stage => <option key={stage} value={stage}>{compactLabel(stage)}</option>)}
                            </select>
                            <select
                                className="input"
                                value={telemetryFilters.outcome}
                                onChange={event => setTelemetryFilters({ ...telemetryFilters, outcome: event.target.value })}
                                aria-label="Filter telemetry by outcome"
                            >
                                <option value="all">All outcomes</option>
                                {telemetryOptions.outcomes.map(outcome => <option key={outcome} value={outcome}>{compactLabel(outcome)}</option>)}
                            </select>
                            <select
                                className="input"
                                value={telemetryFilters.sourceType}
                                onChange={event => setTelemetryFilters({ ...telemetryFilters, sourceType: event.target.value })}
                                aria-label="Filter telemetry by source type"
                            >
                                <option value="all">All sources</option>
                                {telemetryOptions.sourceTypes.map(sourceType => <option key={sourceType} value={sourceType}>{compactLabel(sourceType)}</option>)}
                            </select>
                            <button className="btn" onClick={() => setTelemetryFilters(defaultTelemetryFilters)}>
                                Clear
                            </button>
                            <button className="btn" onClick={() => fetchTelemetry(telemetryFilters)}>
                                <RefreshCw size={16} />
                                Refresh
                            </button>
                        </div>

                        {telemetryLoading ? (
                            <div className="memory-loading">Loading memory telemetry...</div>
                        ) : injections.length === 0 ? (
                            <EmptyPanel
                                icon={<Activity size={22} />}
                                title="No telemetry events"
                                description="Run a planner, generator, healer, or assistant workflow that injects memory, then refresh this page."
                            />
                        ) : (
                            <div className="memory-telemetry-list">
                                {injections.map(event => {
                                    const expanded = expandedInjectionId === event.id;
                                    const source = event.source_type
                                        ? `${event.source_type}${event.source_id ? `:${event.source_id}` : ''}`
                                        : 'No source';
                                    const graphMemoryIds = Array.isArray(event.extra_data?.graph_expanded_memory_ids)
                                        ? event.extra_data.graph_expanded_memory_ids.map(String)
                                        : [];
                                    return (
                                        <article key={event.id} className="memory-telemetry-card">
                                            <div className="memory-telemetry-row">
                                                <div className="memory-telemetry-main">
                                                    <div className="memory-card-title-row">
                                                        <h3>{compactLabel(event.stage)}</h3>
                                                        <div className="memory-card-status">
                                                            <Pill tone={telemetryOutcomeTone(event.outcome)}>{compactLabel(event.outcome)}</Pill>
                                                            <Pill tone="muted">{event.memory_ids.length} memories</Pill>
                                                        </div>
                                                    </div>
                                                    <p>{event.query || 'No query captured for this injection.'}</p>
                                                    <div className="memory-card-meta">
                                                        <span>{formatDate(event.created_at)}</span>
                                                        <span>Actor {event.actor_type}</span>
                                                        <span>Source {source}</span>
                                                    </div>
                                                </div>
                                                <button
                                                    className="btn memory-action-button memory-telemetry-detail-button"
                                                    onClick={() => setExpandedInjectionId(expanded ? null : event.id)}
                                                    aria-expanded={expanded}
                                                >
                                                    <Eye size={14} />
                                                    {expanded ? 'Hide' : 'Details'}
                                                </button>
                                            </div>

                                            {expanded && (
                                                <div className="memory-telemetry-detail">
                                                    <div>
                                                        <strong>Memory IDs</strong>
                                                        <p>{event.memory_ids.length ? event.memory_ids.join(', ') : 'None recorded'}</p>
                                                    </div>
                                                    {graphMemoryIds.length > 0 && (
                                                        <div>
                                                            <strong>Graph-expanded memories</strong>
                                                            <p>{graphMemoryIds.join(', ')}</p>
                                                        </div>
                                                    )}
                                                    <div>
                                                        <strong>Context preview</strong>
                                                        <pre className="memory-preview">{event.context_preview || 'No context preview recorded.'}</pre>
                                                    </div>
                                                    <div>
                                                        <strong>Extra data</strong>
                                                        <pre className="memory-preview">{JSON.stringify(event.extra_data || {}, null, 2)}</pre>
                                                    </div>
                                                </div>
                                            )}
                                        </article>
                                    );
                                })}
                            </div>
                        )}
                    </section>
                </div>
            )}

            <ConfirmDialog
                open={Boolean(deleteTarget)}
                onOpenChange={open => {
                    if (!open) setDeleteTarget(null);
                }}
                title="Delete memory?"
                description="This permanently removes the selected memory from the project context."
                confirmLabel="Delete"
                variant="danger"
                onConfirm={() => {
                    if (deleteTarget) memoryAction(deleteTarget, 'delete');
                    setDeleteTarget(null);
                }}
            />

            <style jsx global>{`
                .memory-page {
                    color: var(--text);
                    letter-spacing: 0;
                }

                .memory-header-actions,
                .memory-tabs,
                .memory-toolbar,
                .memory-card-actions,
                .memory-card-status,
                .memory-card-chips,
                .memory-card-meta,
                .memory-tags,
                .memory-inline-form,
                .memory-action-chips {
                    display: flex;
                    align-items: center;
                    gap: 0.75rem;
                    flex-wrap: wrap;
                }

                .memory-page .btn {
                    min-height: 2.5rem;
                    padding: 0.65rem 0.95rem;
                    color: var(--text);
                    background: var(--background-raised);
                    border: 1px solid var(--border);
                    border-radius: var(--radius-sm);
                    box-shadow: none;
                    line-height: 1;
                }

                .memory-page .btn:hover {
                    color: var(--text);
                    background: var(--surface-hover);
                    border-color: var(--border-bright);
                    transform: none;
                }

                .memory-page .btn:focus-visible,
                .memory-tab:focus-visible,
                .memory-chip:focus-visible,
                .memory-close-button:focus-visible {
                    outline: 2px solid var(--primary);
                    outline-offset: 2px;
                }

                .memory-page .btn-primary {
                    color: #fff;
                    background: var(--primary);
                    border-color: var(--primary);
                    box-shadow: 0 10px 24px -16px rgba(59, 130, 246, 0.85);
                }

                .memory-page .btn-primary:hover {
                    color: #fff;
                    background: var(--primary-hover);
                    border-color: var(--primary-hover);
                }

                .memory-tabs {
                    align-items: stretch;
                    width: fit-content;
                    padding: 0.2rem;
                    margin-bottom: 1rem;
                    background: var(--background-raised);
                    border: 1px solid var(--border);
                    border-radius: var(--radius-sm);
                }

                .memory-tab {
                    display: inline-flex;
                    align-items: center;
                    justify-content: center;
                    gap: 0.5rem;
                    min-height: 2.35rem;
                    padding: 0 0.95rem;
                    color: var(--text-secondary);
                    background: transparent;
                    border: 0;
                    border-radius: calc(var(--radius-sm) - 1px);
                    font-weight: 700;
                    line-height: 1;
                    transition: background 0.18s var(--ease-smooth), color 0.18s var(--ease-smooth);
                }

                .memory-tab:hover {
                    color: var(--text);
                    background: rgba(255, 255, 255, 0.03);
                }

                .memory-tab.active {
                    color: white;
                    background: var(--primary);
                }

                .memory-alert,
                .memory-panel,
                .memory-editor-panel,
                .memory-metric,
                .memory-card,
                .memory-pattern-card,
                .memory-empty {
                    border: 1px solid var(--border);
                    border-radius: var(--radius);
                    background: linear-gradient(180deg, rgba(21, 29, 48, 0.98), rgba(15, 22, 41, 0.98));
                    box-shadow: var(--shadow-card);
                }

                .memory-alert {
                    padding: 0.75rem 0.95rem;
                    margin-bottom: 1rem;
                    font-weight: 600;
                    font-size: 0.9rem;
                }

                .memory-alert.success {
                    color: var(--success);
                    background: var(--success-muted);
                    border-color: rgba(52, 211, 153, 0.28);
                }

                .memory-alert.danger {
                    color: var(--danger);
                    background: var(--danger-muted);
                    border-color: rgba(248, 113, 113, 0.3);
                }

                .memory-agent-stack,
                .memory-test-stack,
                .memory-graph-stack,
                .memory-telemetry-stack {
                    display: flex;
                    flex-direction: column;
                    gap: 1rem;
                }

                .memory-metrics {
                    display: grid;
                    grid-template-columns: repeat(4, minmax(0, 1fr));
                    gap: 0.75rem;
                }

                .memory-metric {
                    position: relative;
                    min-height: 4.6rem;
                    padding: 0.9rem 1rem;
                    overflow: hidden;
                }

                .memory-metric::before {
                    content: '';
                    position: absolute;
                    inset: 0 auto 0 0;
                    width: 3px;
                    background: var(--border-bright);
                }

                .memory-metric span,
                .memory-panel-heading p,
                .memory-tool-heading p,
                .memory-editor-header p,
                .memory-empty p,
                .memory-card p,
                .memory-recall-item p {
                    color: var(--text-secondary);
                }

                .memory-metric span {
                    display: block;
                    margin-bottom: 0.45rem;
                    font-size: 0.72rem;
                    font-weight: 700;
                    text-transform: uppercase;
                    letter-spacing: 0.04em;
                }

                .memory-metric strong {
                    display: block;
                    font-size: 1.55rem;
                    line-height: 1;
                }

                .memory-curation-grid {
                    display: grid;
                    grid-template-columns: minmax(0, 1fr);
                    gap: 1rem;
                    align-items: start;
                }

                .memory-curation-grid.editor-open {
                    grid-template-columns: minmax(0, 1fr) minmax(340px, 400px);
                }

                .memory-main {
                    min-width: 0;
                }

                .memory-panel,
                .memory-editor-panel {
                    padding: 1rem;
                }

                .memory-panel-heading,
                .memory-editor-header,
                .memory-tool-heading {
                    display: flex;
                    align-items: flex-start;
                    justify-content: space-between;
                    gap: 1rem;
                    margin-bottom: 0.9rem;
                }

                .memory-tool-heading {
                    justify-content: flex-start;
                    align-items: center;
                }

                .memory-panel-heading h2,
                .memory-editor-header h2,
                .memory-tool-heading h2 {
                    margin: 0;
                    color: var(--text);
                    font-size: 1rem;
                    font-weight: 800;
                    line-height: 1.2;
                }

                .memory-panel-heading p,
                .memory-editor-header p,
                .memory-tool-heading p {
                    margin: 0.25rem 0 0;
                    font-size: 0.82rem;
                    line-height: 1.4;
                }

                .memory-toolbar {
                    display: grid;
                    grid-template-columns: minmax(260px, 1fr) repeat(3, minmax(140px, 170px)) minmax(92px, auto) minmax(80px, auto);
                    align-items: center;
                    gap: 0.6rem;
                    margin-bottom: 0.9rem;
                    padding: 0.75rem;
                    background: rgba(10, 15, 26, 0.42);
                    border: 1px solid var(--border-subtle);
                    border-radius: var(--radius);
                }

                .memory-telemetry-toolbar {
                    display: grid;
                    grid-template-columns: repeat(3, minmax(150px, 1fr)) minmax(86px, auto) minmax(112px, auto);
                    align-items: center;
                    gap: 0.6rem;
                    margin-bottom: 0.9rem;
                    padding: 0.75rem;
                    background: rgba(10, 15, 26, 0.42);
                    border: 1px solid var(--border-subtle);
                    border-radius: var(--radius);
                }

                .memory-search {
                    position: relative;
                    min-width: 0;
                }

                .memory-search svg {
                    position: absolute;
                    left: 0.85rem;
                    top: 50%;
                    transform: translateY(-50%);
                    color: var(--text-secondary);
                }

                .memory-search .input {
                    padding-left: 2.5rem;
                }

                .memory-page .input {
                    min-height: 2.6rem;
                    color: var(--text);
                    background-color: #090e19;
                    border-color: var(--border-bright);
                    border-radius: var(--radius-sm);
                    box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.025);
                    letter-spacing: 0;
                }

                .memory-page .input:hover {
                    border-color: #344561;
                }

                .memory-page .input::placeholder {
                    color: var(--text-secondary);
                    opacity: 0.72;
                }

                .memory-quiet-button {
                    background: transparent;
                    color: var(--text-secondary);
                    border: 1px solid var(--border);
                }

                .memory-loading {
                    min-height: 12rem;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    padding: 2rem 1rem;
                    color: var(--text-secondary);
                    text-align: center;
                    background: rgba(10, 15, 26, 0.3);
                    border: 1px dashed var(--border);
                    border-radius: var(--radius);
                }

                .memory-list,
                .memory-pattern-list,
                .memory-graph-list,
                .memory-graph-review-list,
                .memory-recall-list,
                .memory-telemetry-list {
                    display: flex;
                    flex-direction: column;
                    gap: 0.7rem;
                }

                .memory-card {
                    display: grid;
                    grid-template-columns: minmax(0, 1fr) minmax(116px, 128px);
                    gap: 0.9rem;
                    padding: 0.9rem;
                    transition: border-color 0.18s var(--ease-smooth), background 0.18s var(--ease-smooth);
                }

                .memory-telemetry-card {
                    padding: 0.9rem;
                    border: 1px solid var(--border);
                    border-radius: var(--radius);
                    background: var(--background-raised);
                }

                .memory-graph-layout {
                    display: grid;
                    grid-template-columns: repeat(2, minmax(0, 1fr));
                    gap: 1rem;
                }

                .memory-graph-column {
                    min-width: 0;
                }

                .memory-graph-column h3 {
                    margin: 0 0 0.7rem;
                    font-size: 0.92rem;
                    color: var(--text-secondary);
                }

                .memory-graph-card {
                    padding: 0.85rem;
                    border: 1px solid var(--border);
                    border-radius: var(--radius-sm);
                    background: var(--background-raised);
                }

                .memory-graph-review-card {
                    display: grid;
                    grid-template-columns: minmax(0, 1fr) minmax(104px, 124px);
                    gap: 0.9rem;
                    padding: 0.9rem;
                    border: 1px solid rgba(251, 191, 36, 0.24);
                    border-radius: var(--radius-sm);
                    background: rgba(251, 191, 36, 0.06);
                }

                .memory-graph-review-main {
                    min-width: 0;
                }

                .memory-graph-review-card h3 {
                    margin: 0;
                    color: var(--text);
                    font-size: 0.94rem;
                    font-weight: 800;
                    line-height: 1.35;
                }

                .memory-graph-review-card p {
                    margin: 0.45rem 0 0;
                    color: var(--text-secondary);
                    font-size: 0.86rem;
                    line-height: 1.45;
                    overflow-wrap: anywhere;
                }

                .memory-review-evidence {
                    margin: 0.65rem 0 0;
                    max-height: 7.5rem;
                    overflow: auto;
                    white-space: pre-wrap;
                    color: var(--text-secondary);
                    background: rgba(9, 14, 25, 0.72);
                    border: 1px solid var(--border);
                    border-radius: var(--radius-sm);
                    padding: 0.7rem;
                    font-size: 0.78rem;
                    line-height: 1.5;
                }

                .memory-graph-card h4 {
                    margin: 0;
                    min-width: 0;
                    color: var(--text);
                    font-size: 0.9rem;
                    line-height: 1.35;
                    overflow-wrap: anywhere;
                }

                .memory-graph-card p {
                    margin: 0.55rem 0 0;
                    color: var(--text-secondary);
                    font-size: 0.82rem;
                    line-height: 1.45;
                    overflow-wrap: anywhere;
                }

                .memory-telemetry-row {
                    display: grid;
                    grid-template-columns: minmax(0, 1fr) minmax(96px, 120px);
                    gap: 0.9rem;
                    align-items: flex-start;
                }

                .memory-telemetry-main {
                    min-width: 0;
                }

                .memory-telemetry-main p {
                    margin: 0;
                    display: -webkit-box;
                    overflow: hidden;
                    -webkit-box-orient: vertical;
                    -webkit-line-clamp: 2;
                    color: var(--text-secondary);
                    font-size: 0.9rem;
                    line-height: 1.5;
                }

                .memory-telemetry-detail-button {
                    width: 100%;
                }

                .memory-telemetry-detail {
                    display: grid;
                    grid-template-columns: minmax(0, 1fr);
                    gap: 0.75rem;
                    margin-top: 0.9rem;
                    padding-top: 0.9rem;
                    border-top: 1px solid var(--border);
                }

                .memory-telemetry-detail strong {
                    display: block;
                    margin-bottom: 0.35rem;
                    color: var(--text);
                    font-size: 0.78rem;
                }

                .memory-telemetry-detail p {
                    margin: 0;
                    color: var(--text-secondary);
                    font-size: 0.82rem;
                    line-height: 1.45;
                    overflow-wrap: anywhere;
                }

                .memory-card:hover {
                    border-color: var(--border-bright);
                    background: linear-gradient(180deg, rgba(21, 29, 48, 1), rgba(17, 25, 45, 1));
                }

                .memory-card-body {
                    min-width: 0;
                }

                .memory-card-title-row {
                    display: flex;
                    align-items: flex-start;
                    justify-content: space-between;
                    gap: 0.75rem;
                    margin-bottom: 0.45rem;
                }

                .memory-card h3,
                .memory-telemetry-card h3,
                .memory-pattern-card h3,
                .memory-recall-item strong {
                    margin: 0;
                    color: var(--text);
                    font-size: 0.94rem;
                    font-weight: 800;
                    line-height: 1.35;
                }

                .memory-card p {
                    margin: 0;
                    display: -webkit-box;
                    overflow: hidden;
                    -webkit-box-orient: vertical;
                    -webkit-line-clamp: 3;
                    line-height: 1.5;
                    font-size: 0.9rem;
                }

                .memory-card-chips {
                    margin-top: 0.75rem;
                    gap: 0.4rem;
                }

                .memory-card-meta {
                    margin-top: 0.65rem;
                    gap: 0.7rem;
                    color: var(--text-secondary);
                    font-size: 0.76rem;
                }

                .memory-card-meta span {
                    display: inline-flex;
                    align-items: center;
                    gap: 0.35rem;
                    min-width: 0;
                }

                .memory-tags {
                    margin-top: 0.65rem;
                    gap: 0.4rem;
                    color: #8ab4ff;
                    font-size: 0.76rem;
                    font-weight: 700;
                }

                .memory-card-actions {
                    width: 100%;
                    align-items: stretch;
                    align-content: flex-start;
                    justify-content: flex-start;
                    gap: 0.45rem;
                }

                .memory-action-button {
                    width: 100%;
                    min-height: 2.15rem;
                    justify-content: flex-start;
                    padding: 0.5rem 0.65rem;
                    background: var(--background-raised);
                    color: var(--text-secondary);
                    border: 1px solid var(--border);
                    font-size: 0.78rem;
                    font-weight: 700;
                }

                .memory-action-button:hover {
                    color: var(--text);
                    border-color: var(--border-bright);
                }

                .memory-action-button.danger {
                    color: var(--danger);
                    background: rgba(248, 113, 113, 0.08);
                    border-color: rgba(248, 113, 113, 0.22);
                }

                .memory-pill {
                    display: inline-flex;
                    align-items: center;
                    gap: 0.35rem;
                    min-height: 1.45rem;
                    padding: 0.18rem 0.5rem;
                    border: 1px solid var(--border);
                    border-radius: 999px;
                    color: var(--text-secondary);
                    background: var(--background-raised);
                    font-size: 0.7rem;
                    font-weight: 700;
                    line-height: 1;
                    white-space: nowrap;
                }

                .memory-pill-success {
                    color: var(--success);
                    background: var(--success-muted);
                    border-color: rgba(52, 211, 153, 0.25);
                }

                .memory-pill-warning {
                    color: var(--warning);
                    background: var(--warning-muted);
                    border-color: rgba(251, 191, 36, 0.28);
                }

                .memory-pill-danger {
                    color: var(--danger);
                    background: var(--danger-muted);
                    border-color: rgba(248, 113, 113, 0.28);
                }

                .memory-pill-muted {
                    color: var(--text-tertiary);
                    background: var(--surface-hover);
                }

                .memory-editor-panel {
                    position: sticky;
                    top: 0.75rem;
                    max-height: calc(100vh - 2rem);
                    overflow: auto;
                }

                .memory-close-button {
                    width: 2.2rem;
                    height: 2.2rem;
                    color: var(--text-secondary);
                    border: 1px solid var(--border);
                    background: var(--background-raised);
                }

                .memory-form-grid {
                    display: grid;
                    grid-template-columns: 1fr 1fr;
                    column-gap: 0.75rem;
                    row-gap: 0;
                }

                .memory-field {
                    display: flex;
                    flex-direction: column;
                    gap: 0.4rem;
                    margin-bottom: 0.75rem;
                }

                .memory-field span {
                    color: var(--text);
                    font-size: 0.78rem;
                    font-weight: 700;
                }

                .memory-textarea {
                    min-height: 140px;
                    resize: vertical;
                }

                .memory-range {
                    padding: 0.55rem 0;
                    accent-color: var(--primary);
                }

                .memory-checkbox {
                    display: flex;
                    align-items: center;
                    gap: 0.65rem;
                    margin: 0.25rem 0 1rem;
                    color: var(--text-secondary);
                    font-size: 0.85rem;
                    line-height: 1.4;
                }

                .memory-checkbox input {
                    width: 1rem;
                    height: 1rem;
                    accent-color: var(--primary);
                }

                .memory-editor-actions {
                    display: flex;
                    gap: 0.6rem;
                    flex-wrap: wrap;
                    padding-top: 0.15rem;
                }

                .memory-support-grid {
                    display: grid;
                    grid-template-columns: repeat(2, minmax(0, 1fr));
                    gap: 1rem;
                }

                .memory-inline-form {
                    align-items: stretch;
                    gap: 0.6rem;
                }

                .memory-inline-form .input {
                    flex: 1 1 260px;
                }

                .memory-preview {
                    margin: 1rem 0 0;
                    max-height: 320px;
                    overflow: auto;
                    white-space: pre-wrap;
                    color: var(--text-secondary);
                    background: var(--code-bg);
                    border: 1px solid var(--border);
                    border-radius: var(--radius-sm);
                    padding: 0.9rem;
                    font-size: 0.82rem;
                    line-height: 1.55;
                }

                .memory-recall-list {
                    margin-top: 1rem;
                }

                .memory-recall-item {
                    padding: 0.8rem;
                    border: 1px solid var(--border);
                    border-radius: var(--radius-sm);
                    background: var(--background-raised);
                }

                .memory-recall-item p {
                    margin: 0.4rem 0;
                    line-height: 1.45;
                    font-size: 0.86rem;
                }

                .memory-recall-item small {
                    color: var(--text-tertiary);
                }

                .memory-empty {
                    display: flex;
                    min-height: 200px;
                    flex-direction: column;
                    align-items: center;
                    justify-content: center;
                    padding: 1.75rem;
                    text-align: center;
                    background: rgba(10, 15, 26, 0.34);
                    border-style: dashed;
                }

                .memory-empty-icon {
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    width: 2.75rem;
                    height: 2.75rem;
                    margin-bottom: 0.7rem;
                    color: var(--primary);
                    background: var(--primary-glow);
                    border-radius: var(--radius);
                }

                .memory-empty strong {
                    font-size: 1rem;
                }

                .memory-empty p {
                    max-width: 34rem;
                    margin: 0.4rem 0 1rem;
                    line-height: 1.5;
                }

                .memory-action-chips {
                    gap: 0.5rem;
                }

                .memory-chip {
                    display: inline-flex;
                    align-items: center;
                    gap: 0.55rem;
                    min-height: 2.25rem;
                    padding: 0 0.75rem;
                    color: var(--text-secondary);
                    background: var(--background-raised);
                    border: 1px solid var(--border);
                    border-radius: var(--radius-sm);
                    font-weight: 700;
                    transition: background 0.18s var(--ease-smooth), border-color 0.18s var(--ease-smooth), color 0.18s var(--ease-smooth);
                }

                .memory-chip:hover {
                    color: var(--text);
                    border-color: var(--border-bright);
                }

                .memory-chip.active {
                    color: white;
                    background: var(--primary);
                    border-color: var(--primary);
                }

                .memory-chip span {
                    color: inherit;
                    opacity: 0.75;
                }

                .memory-pattern-card {
                    display: flex;
                    align-items: flex-start;
                    justify-content: space-between;
                    gap: 1rem;
                    padding: 0.9rem;
                }

                @media (max-width: 1180px) {
                    .memory-curation-grid.editor-open {
                        grid-template-columns: 1fr;
                    }

                    .memory-editor-panel {
                        position: static;
                        order: -1;
                        max-height: none;
                    }

                    .memory-toolbar {
                        grid-template-columns: minmax(220px, 1fr) repeat(2, minmax(130px, 1fr));
                    }

                    .memory-telemetry-toolbar {
                        grid-template-columns: repeat(3, minmax(130px, 1fr));
                    }
                }

                @media (max-width: 900px) {
                    .memory-metrics,
                    .memory-support-grid,
                    .memory-graph-layout {
                        grid-template-columns: repeat(2, minmax(0, 1fr));
                    }

                    .memory-toolbar {
                        grid-template-columns: 1fr 1fr;
                    }

                    .memory-telemetry-toolbar {
                        grid-template-columns: 1fr 1fr;
                    }

                    .memory-card,
                    .memory-graph-review-card,
                    .memory-telemetry-row {
                        grid-template-columns: 1fr;
                    }

                    .memory-card-actions {
                        width: 100%;
                        justify-content: flex-start;
                        flex-direction: row;
                    }

                    .memory-action-button {
                        width: auto;
                        min-width: 6.25rem;
                    }
                }

                @media (max-width: 640px) {
                    .memory-tabs,
                    .memory-header-actions {
                        width: 100%;
                    }

                    .memory-tab,
                    .memory-header-actions .btn {
                        flex: 1 1 0;
                    }

                    .memory-header-actions {
                        gap: 0.5rem;
                    }

                    .memory-support-grid,
                    .memory-graph-layout,
                    .memory-toolbar,
                    .memory-telemetry-toolbar,
                    .memory-form-grid {
                        grid-template-columns: 1fr;
                    }

                    .memory-panel,
                    .memory-editor-panel {
                        padding: 0.9rem;
                    }

                    .memory-card-title-row,
                    .memory-pattern-card {
                        flex-direction: column;
                    }

                    .memory-card-actions {
                        display: grid;
                        grid-template-columns: 1fr 1fr;
                    }

                    .memory-action-button {
                        width: 100%;
                        min-width: 0;
                    }

                    .memory-inline-form .btn {
                        width: 100%;
                    }
                }

                @media (max-width: 420px) {
                    .memory-card-actions {
                        grid-template-columns: 1fr;
                    }
                }
            `}</style>
        </PageLayout>
    );
}
