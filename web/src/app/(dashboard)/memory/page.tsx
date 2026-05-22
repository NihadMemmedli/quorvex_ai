'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import {
    Archive,
    CheckCircle,
    Clock,
    Database,
    Eye,
    Filter,
    RefreshCw,
    Save,
    Search,
    ShieldCheck,
    Trash2,
    XCircle,
} from 'lucide-react';
import { API_BASE } from '@/lib/api';
import { fetchWithAuth } from '@/contexts/AuthContext';
import { useProject } from '@/contexts/ProjectContext';
import { PageLayout } from '@/components/ui/page-layout';
import { PageHeader } from '@/components/ui/page-header';
import { DashboardPageSkeleton } from '@/components/ui/page-skeleton';

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

const memoryKinds = ['project_fact', 'user_preference', 'workflow_decision', 'failure_pattern', 'agent_lesson'];
const memoryTypes = ['semantic', 'episodic', 'procedural', 'structural'];
const memoryScopes = ['global', 'project', 'user', 'agent'];

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

export default function MemoryPage() {
    const { currentProject, isLoading: projectLoading } = useProject();
    const projectId = currentProject?.id || 'default';
    const [activeTab, setActiveTab] = useState<'test' | 'agent'>('agent');

    const [patterns, setPatterns] = useState<Pattern[]>([]);
    const [stats, setStats] = useState<MemoryStats | null>(null);
    const [testLoading, setTestLoading] = useState(false);
    const [searchQuery, setSearchQuery] = useState('');
    const [actionFilter, setActionFilter] = useState('all');

    const [memories, setMemories] = useState<AgentMemory[]>([]);
    const [agentLoading, setAgentLoading] = useState(false);
    const [agentQuery, setAgentQuery] = useState('');
    const [kindFilter, setKindFilter] = useState('all');
    const [typeFilter, setTypeFilter] = useState('all');
    const [scopeFilter, setScopeFilter] = useState('all');
    const [statusMessage, setStatusMessage] = useState<string | null>(null);
    const [form, setForm] = useState<MemoryForm>(emptyForm);
    const [contextQuery, setContextQuery] = useState('Generate a reliable test for this project');
    const [contextPreview, setContextPreview] = useState('');
    const [recallQuery, setRecallQuery] = useState('');
    const [recallResults, setRecallResults] = useState<RecallResult[]>([]);

    const fetchTestMemory = useCallback(async () => {
        setTestLoading(true);
        try {
            const encodedProject = encodeURIComponent(projectId);
            const [patternsRes, statsRes] = await Promise.all([
                fetchWithAuth(`${API_BASE}/api/memory/patterns?project_id=${encodedProject}&limit=100`),
                fetchWithAuth(`${API_BASE}/api/memory/stats?project_id=${encodedProject}`),
            ]);
            if (patternsRes.ok) setPatterns(await patternsRes.json());
            if (statsRes.ok) setStats(await statsRes.json());
        } finally {
            setTestLoading(false);
        }
    }, [projectId]);

    const fetchAgentMemory = useCallback(async () => {
        setAgentLoading(true);
        try {
            const params = new URLSearchParams({ project_id: projectId, limit: '100' });
            if (agentQuery.trim()) params.set('q', agentQuery.trim());
            if (kindFilter !== 'all') params.append('kind', kindFilter);
            if (typeFilter !== 'all') params.append('memory_type', typeFilter);
            if (scopeFilter !== 'all') params.set('scope', scopeFilter);
            const res = await fetchWithAuth(`${API_BASE}/api/memory/agent?${params.toString()}`);
            if (!res.ok) throw new Error((await res.json()).detail || 'Failed to load agent memory');
            setMemories(await res.json());
        } catch (err) {
            setStatusMessage(err instanceof Error ? err.message : 'Failed to load agent memory');
        } finally {
            setAgentLoading(false);
        }
    }, [agentQuery, kindFilter, projectId, scopeFilter, typeFilter]);

    useEffect(() => {
        if (projectLoading) return;
        fetchAgentMemory();
        fetchTestMemory();
    }, [fetchAgentMemory, fetchTestMemory, projectLoading]);

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
        setStatusMessage('Memory saved.');
        fetchAgentMemory();
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
        setStatusMessage(`Memory ${action === 'delete' ? 'deleted' : action + 'd'}.`);
        fetchAgentMemory();
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
        window.scrollTo({ top: 0, behavior: 'smooth' });
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

    return (
        <PageLayout tier="wide">
            <PageHeader
                title="Memory"
                subtitle="Inspect test automation memory, curate agent memory, and preview recall context."
                icon={<Database size={20} />}
                actions={
                    <button className="btn" onClick={() => { fetchAgentMemory(); fetchTestMemory(); }}>
                        <RefreshCw size={16} />
                        Refresh
                    </button>
                }
            />

            <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '1.5rem', flexWrap: 'wrap' }}>
                <button className={activeTab === 'agent' ? 'btn btn-primary' : 'btn'} onClick={() => setActiveTab('agent')}>
                    <ShieldCheck size={16} />
                    Agent Memory
                </button>
                <button className={activeTab === 'test' ? 'btn btn-primary' : 'btn'} onClick={() => setActiveTab('test')}>
                    <Database size={16} />
                    Test Memory
                </button>
            </div>

            {statusMessage && (
                <div className="card" style={{ padding: '1rem', marginBottom: '1rem', color: statusMessage.includes('Failed') ? 'var(--danger)' : 'var(--success)' }}>
                    {statusMessage}
                </div>
            )}

            {activeTab === 'agent' ? (
                <div style={{ display: 'grid', gridTemplateColumns: 'minmax(280px, 380px) 1fr', gap: '1.5rem', alignItems: 'start' }}>
                    <section className="card" style={{ padding: '1.5rem' }}>
                        <h3 style={{ marginTop: 0 }}>{form.id ? 'Edit Memory' : 'Create Memory'}</h3>
                        <label className="label">Kind</label>
                        <select className="input" value={form.kind} onChange={event => setForm({ ...form, kind: event.target.value })}>
                            {memoryKinds.map(kind => <option key={kind} value={kind}>{kind}</option>)}
                        </select>
                        <label className="label" style={{ marginTop: '1rem' }}>Type</label>
                        <select className="input" value={form.memory_type} onChange={event => setForm({ ...form, memory_type: event.target.value })}>
                            {memoryTypes.map(type => <option key={type} value={type}>{type}</option>)}
                        </select>
                        <label className="label" style={{ marginTop: '1rem' }}>Scope</label>
                        <select className="input" value={form.scope} onChange={event => setForm({ ...form, scope: event.target.value })}>
                            {memoryScopes.map(scope => <option key={scope} value={scope}>{scope}</option>)}
                        </select>
                        <label className="label" style={{ marginTop: '1rem' }}>Summary</label>
                        <input className="input" value={form.summary} onChange={event => setForm({ ...form, summary: event.target.value })} />
                        <label className="label" style={{ marginTop: '1rem' }}>Content</label>
                        <textarea className="input" value={form.content} onChange={event => setForm({ ...form, content: event.target.value })} rows={6} />
                        <label className="label" style={{ marginTop: '1rem' }}>Tags</label>
                        <input className="input" value={form.tags} onChange={event => setForm({ ...form, tags: event.target.value })} placeholder="login, selector, preference" />
                        <label className="label" style={{ marginTop: '1rem' }}>Agent Type</label>
                        <input className="input" value={form.agent_type} onChange={event => setForm({ ...form, agent_type: event.target.value })} placeholder="assistant" />
                        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem', marginTop: '1rem' }}>
                            <label className="label">Confidence
                                <input className="input" type="number" min="0" max="1" step="0.05" value={form.confidence} onChange={event => setForm({ ...form, confidence: Number(event.target.value) })} />
                            </label>
                            <label className="label">Importance
                                <input className="input" type="number" min="0" max="1" step="0.05" value={form.importance} onChange={event => setForm({ ...form, importance: Number(event.target.value) })} />
                            </label>
                        </div>
                        <label style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', marginTop: '1rem' }}>
                            <input type="checkbox" checked={form.review_required} onChange={event => setForm({ ...form, review_required: event.target.checked })} />
                            Require review before prompt injection
                        </label>
                        <div style={{ display: 'flex', gap: '0.75rem', marginTop: '1rem', flexWrap: 'wrap' }}>
                            <button className="btn btn-primary" onClick={saveMemory} disabled={!form.content.trim()}>
                                <Save size={16} />
                                Save
                            </button>
                            {form.id && <button className="btn" onClick={() => setForm(emptyForm)}>Cancel</button>}
                        </div>
                    </section>

                    <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
                        <section style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: '1rem' }}>
                            {[
                                ['Total', memoryCounts.total],
                                ['Ready', memoryCounts.active],
                                ['Needs Review', memoryCounts.review],
                                ['Archived', memoryCounts.archived],
                            ].map(([label, value]) => (
                                <div className="card-elevated" style={{ padding: '1rem' }} key={label}>
                                    <div style={{ color: 'var(--text-tertiary)', fontSize: '0.85rem' }}>{label}</div>
                                    <strong style={{ fontSize: '1.8rem' }}>{value}</strong>
                                </div>
                            ))}
                        </section>

                        <section className="card" style={{ padding: '1.5rem' }}>
                            <div style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap', marginBottom: '1rem' }}>
                                <input className="input" style={{ flex: '1 1 220px' }} value={agentQuery} onChange={event => setAgentQuery(event.target.value)} placeholder="Search memories..." />
                                <select className="input" value={kindFilter} onChange={event => setKindFilter(event.target.value)} style={{ width: 180 }}>
                                    <option value="all">All kinds</option>
                                    {memoryKinds.map(kind => <option key={kind} value={kind}>{kind}</option>)}
                                </select>
                                <select className="input" value={typeFilter} onChange={event => setTypeFilter(event.target.value)} style={{ width: 150 }}>
                                    <option value="all">All types</option>
                                    {memoryTypes.map(type => <option key={type} value={type}>{type}</option>)}
                                </select>
                                <select className="input" value={scopeFilter} onChange={event => setScopeFilter(event.target.value)} style={{ width: 150 }}>
                                    <option value="all">All scopes</option>
                                    {memoryScopes.map(scope => <option key={scope} value={scope}>{scope}</option>)}
                                </select>
                                <button className="btn" onClick={fetchAgentMemory}>
                                    <Filter size={16} />
                                    Apply
                                </button>
                            </div>

                            {agentLoading ? <p>Loading agent memory...</p> : memories.length === 0 ? (
                                <p style={{ color: 'var(--text-secondary)' }}>No agent memories found for this project.</p>
                            ) : (
                                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                                    {memories.map(memory => (
                                        <article key={memory.id} style={{ border: '1px solid var(--border)', borderRadius: 'var(--radius)', padding: '1rem', background: 'var(--surface)' }}>
                                            <div style={{ display: 'flex', justifyContent: 'space-between', gap: '1rem', alignItems: 'start' }}>
                                                <div>
                                                    <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap', marginBottom: '0.5rem' }}>
                                                        <strong>{memory.summary || memory.content.slice(0, 90)}</strong>
                                                        {memory.review_required && <span style={{ color: 'var(--warning)' }}>Needs review</span>}
                                                        {memory.status !== 'active' && <span style={{ color: 'var(--text-tertiary)' }}>{memory.status}</span>}
                                                    </div>
                                                    <p style={{ margin: 0, color: 'var(--text-secondary)' }}>{memory.content}</p>
                                                </div>
                                                <div style={{ display: 'flex', gap: '0.4rem', flexWrap: 'wrap', justifyContent: 'flex-end' }}>
                                                    <button className="btn" onClick={() => editMemory(memory)}>Edit</button>
                                                    {memory.review_required && <button className="btn" onClick={() => memoryAction(memory, 'approve')}><CheckCircle size={14} />Approve</button>}
                                                    <button className="btn" onClick={() => memoryAction(memory, 'verify')}><ShieldCheck size={14} />Verify</button>
                                                    <button className="btn" onClick={() => memoryAction(memory, 'archive')}><Archive size={14} />Archive</button>
                                                    <button className="btn" onClick={() => memoryAction(memory, 'delete')}><Trash2 size={14} />Delete</button>
                                                </div>
                                            </div>
                                            <div style={{ display: 'flex', gap: '1rem', flexWrap: 'wrap', marginTop: '0.75rem', fontSize: '0.85rem', color: 'var(--text-tertiary)' }}>
                                                <span>{memory.kind}</span>
                                                <span>{memory.memory_type}</span>
                                                <span>{memory.scope}</span>
                                                <span>Confidence {pct(memory.confidence)}</span>
                                                <span>Importance {pct(memory.importance)}</span>
                                                <span>Used {memory.use_count}</span>
                                                <span>Verified {formatDate(memory.last_verified_at)}</span>
                                                {memory.source_type && <span>Source {memory.source_type}{memory.source_id ? `:${memory.source_id}` : ''}</span>}
                                            </div>
                                        </article>
                                    ))}
                                </div>
                            )}
                        </section>

                        <section className="card" style={{ padding: '1.5rem' }}>
                            <h3 style={{ marginTop: 0 }}>Context Preview</h3>
                            <div style={{ display: 'flex', gap: '0.75rem' }}>
                                <input className="input" value={contextQuery} onChange={event => setContextQuery(event.target.value)} />
                                <button className="btn" onClick={previewContext}><Eye size={16} />Preview</button>
                            </div>
                            {contextPreview && <pre style={{ whiteSpace: 'pre-wrap', marginTop: '1rem', color: 'var(--text-secondary)' }}>{contextPreview}</pre>}
                        </section>

                        <section className="card" style={{ padding: '1.5rem' }}>
                            <h3 style={{ marginTop: 0 }}>Session Recall</h3>
                            <div style={{ display: 'flex', gap: '0.75rem' }}>
                                <input className="input" value={recallQuery} onChange={event => setRecallQuery(event.target.value)} placeholder="Search prior conversations, or leave blank for recent..." />
                                <button className="btn" onClick={searchRecall}><Search size={16} />Recall</button>
                            </div>
                            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem', marginTop: '1rem' }}>
                                {recallResults.map(result => (
                                    <div key={`${result.conversation_id}-${result.match_message_id || 'recent'}`} style={{ border: '1px solid var(--border)', borderRadius: 'var(--radius)', padding: '1rem' }}>
                                        <strong>{result.title}</strong>
                                        <p style={{ color: 'var(--text-secondary)', margin: '0.5rem 0' }}>{result.snippet || 'Recent conversation'}</p>
                                        <small style={{ color: 'var(--text-tertiary)' }}>{formatDate(result.updated_at)}{result.match_message_id ? ` · anchor ${result.match_message_id}` : ''}</small>
                                    </div>
                                ))}
                            </div>
                        </section>
                    </div>
                </div>
            ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
                    {testLoading ? <DashboardPageSkeleton /> : (
                        <>
                            {stats && (
                                <section style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '1rem' }}>
                                    <div className="card-elevated" style={{ padding: '1.5rem' }}>
                                        <Database size={22} style={{ color: 'var(--primary)' }} />
                                        <div style={{ color: 'var(--text-tertiary)', marginTop: '0.5rem' }}>Total Patterns</div>
                                        <strong style={{ fontSize: '2rem' }}>{stats.total_patterns}</strong>
                                    </div>
                                    <div className="card-elevated" style={{ padding: '1.5rem' }}>
                                        <CheckCircle size={22} style={{ color: 'var(--success)' }} />
                                        <div style={{ color: 'var(--text-tertiary)', marginTop: '0.5rem' }}>Success Rate</div>
                                        <strong style={{ fontSize: '2rem' }}>{stats.avg_success_rate.toFixed(1)}%</strong>
                                    </div>
                                </section>
                            )}

                            {Object.keys(actionCounts).length > 0 && (
                                <section className="card" style={{ padding: '1.5rem' }}>
                                    <h3 style={{ marginTop: 0 }}>Action Breakdown</h3>
                                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.75rem' }}>
                                        {Object.entries(actionCounts).map(([action, count]) => (
                                            <button key={action} className={actionFilter === action ? 'btn btn-primary' : 'btn'} onClick={() => setActionFilter(actionFilter === action ? 'all' : action)}>
                                                {action}: {count}
                                            </button>
                                        ))}
                                    </div>
                                </section>
                            )}

                            <section className="card" style={{ padding: '1.5rem' }}>
                                <h3 style={{ marginTop: 0, display: 'flex', alignItems: 'center', gap: '0.5rem' }}><Search size={18} />Semantic Search</h3>
                                <div style={{ display: 'flex', gap: '0.75rem' }}>
                                    <input className="input" style={{ flex: 1 }} value={searchQuery} onChange={event => setSearchQuery(event.target.value)} onKeyDown={event => event.key === 'Enter' && handlePatternSearch()} placeholder="Describe what you want to test..." />
                                    <button className="btn btn-primary" onClick={handlePatternSearch}><Search size={16} />Search</button>
                                </div>
                            </section>

                            <section className="card" style={{ padding: '1.5rem' }}>
                                <h3 style={{ marginTop: 0 }}>Stored Patterns ({filteredPatterns.length})</h3>
                                {filteredPatterns.length === 0 ? (
                                    <p style={{ color: 'var(--text-secondary)' }}>No patterns found for this project.</p>
                                ) : (
                                    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                                        {filteredPatterns.map(pattern => (
                                            <article key={pattern.id} style={{ padding: '1rem', background: 'var(--surface)', borderRadius: 'var(--radius)', border: '1px solid var(--border)' }}>
                                                <div style={{ display: 'flex', justifyContent: 'space-between', gap: '1rem' }}>
                                                    <strong>{pattern.action}: {pattern.target}</strong>
                                                    <span style={{ color: pattern.success_rate >= 0.9 ? 'var(--success)' : 'var(--danger)' }}>
                                                        {pattern.success_rate >= 0.9 ? <CheckCircle size={16} /> : <XCircle size={16} />} {(pattern.success_rate * 100).toFixed(0)}%
                                                    </span>
                                                </div>
                                                <div style={{ display: 'flex', gap: '1rem', flexWrap: 'wrap', marginTop: '0.5rem', color: 'var(--text-secondary)', fontSize: '0.85rem' }}>
                                                    <span><Clock size={14} /> {pattern.avg_duration.toFixed(0)}ms avg</span>
                                                    <span>Test: {pattern.test_name}</span>
                                                </div>
                                            </article>
                                        ))}
                                    </div>
                                )}
                            </section>
                        </>
                    )}
                </div>
            )}
        </PageLayout>
    );
}
