'use client';
import React, { useState, useEffect, useRef } from 'react';
import dynamic from 'next/dynamic';
import {
    Plus, Play, Save, Loader2, Trash2, Edit2, Sparkles,
} from 'lucide-react';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { vscDarkPlus } from 'react-syntax-highlighter/dist/esm/styles/prism';
import { cardStyle, inputStyle, btnPrimary, btnSecondary } from '@/lib/styles';
import { getAuthHeaders } from '@/lib/styles';
import { API_BASE, withProjectBody, withProjectQuery } from '@/lib/api';
import type { DbConnection, DbSpec } from './types';

const CodeEditor = dynamic(() => import('@/components/CodeEditor'), { ssr: false });

interface GeneratedDbCheck {
    check_name: string;
    check_type: string;
    table_name?: string;
    column_name?: string;
    description?: string;
    severity?: string;
    sql_query: string;
    expected_result?: string;
    expect_empty?: boolean;
}

interface SpecsTabProps {
    specs: DbSpec[];
    connections: DbConnection[];
    projectId: string;
    onRefreshSpecs: () => void;
    onRefreshRuns: () => void;
    preferredConnectionId?: string;
    initialSpecName?: string;
    canEdit: boolean;
}

export default function SpecsTab({ specs, connections, projectId, onRefreshSpecs, onRefreshRuns, preferredConnectionId, initialSpecName, canEdit }: SpecsTabProps) {
    const [selectedSpec, setSelectedSpec] = useState<DbSpec | null>(null);
    const [specContent, setSpecContent] = useState('');
    const [isCreatingSpec, setIsCreatingSpec] = useState(false);
    const [newSpecName, setNewSpecName] = useState('');
    const [newSpecContent, setNewSpecContent] = useState('');
    const [editingSpec, setEditingSpec] = useState(false);
    const [specConnId, setSpecConnId] = useState('');
    const [runningSpec, setRunningSpec] = useState<string | null>(null);
    const [specJobId, setSpecJobId] = useState<string | null>(null);

    // AI Generate state
    const [showAiGenerate, setShowAiGenerate] = useState(false);
    const [aiGenConnId, setAiGenConnId] = useState('');
    const [aiGenInstructions, setAiGenInstructions] = useState('');
    const [aiGenSpecName, setAiGenSpecName] = useState('');
    const [isAiGenerating, setIsAiGenerating] = useState(false);
    const [isSavingGeneratedSpec, setIsSavingGeneratedSpec] = useState(false);
    const [aiGenJobId, setAiGenJobId] = useState<string | null>(null);
    const [aiGenProgress, setAiGenProgress] = useState('');
    const [generatedChecks, setGeneratedChecks] = useState<GeneratedDbCheck[]>([]);

    const pollRef = useRef<NodeJS.Timeout | null>(null);

    useEffect(() => {
        if (specConnId || connections.length === 0) return;
        const preferred = preferredConnectionId && connections.find(c => c.id === preferredConnectionId);
        const selected = preferred || connections[0];
        setSpecConnId(selected.id);
        setAiGenConnId(selected.id);
    }, [connections, preferredConnectionId, specConnId]);

    // Poll active jobs (spec run / ai generate)
    useEffect(() => {
        const activeJob = specJobId || aiGenJobId;
        if (!activeJob) return;

        const poll = async () => {
            try {
                const res = await fetch(`${API_BASE}${withProjectQuery(`/database-testing/jobs/${activeJob}`, projectId)}`, {
                    headers: getAuthHeaders(),
                });
                if (res.ok) {
                    const data = await res.json();

                    if (activeJob === specJobId) {
                        if (data.status === 'completed' || data.status === 'failed') {
                            setRunningSpec(null);
                            if (pollRef.current) clearInterval(pollRef.current);
                            pollRef.current = null;
                            setSpecJobId(null);
                            onRefreshRuns();
                        }
                    } else if (activeJob === aiGenJobId) {
                        if (data.stage_message) {
                            setAiGenProgress(data.stage_message);
                        }
                        if (data.status === 'completed' || data.status === 'failed') {
                            if (pollRef.current) clearInterval(pollRef.current);
                            pollRef.current = null;
                            setIsAiGenerating(false);
                            setAiGenJobId(null);

                            if (data.status === 'completed' && data.result) {
                                const result = data.result as Record<string, unknown>;
                                const checks = Array.isArray(result.checks) ? result.checks as GeneratedDbCheck[] : [];
                                setGeneratedChecks(checks);
                                if (typeof result.spec_name === 'string') {
                                    setAiGenSpecName(result.spec_name);
                                }
                                if (result.execution_run_id) {
                                    onRefreshRuns();
                                }
                                setAiGenProgress(`Done: ${result.checks_count} checks generated`);
                                if (aiGenConnId) setSpecConnId(aiGenConnId);
                            } else if (data.status === 'failed') {
                                setAiGenProgress(`Failed: ${data.error || 'Unknown error'}`);
                            }
                        }
                    }
                } else if (res.status === 404) {
                    if (pollRef.current) clearInterval(pollRef.current);
                    pollRef.current = null;
                    if (activeJob === specJobId) {
                        setRunningSpec(null);
                        setSpecJobId(null);
                    } else if (activeJob === aiGenJobId) {
                        setIsAiGenerating(false);
                        setAiGenJobId(null);
                        setAiGenProgress('');
                    }
                    onRefreshRuns();
                }
            } catch (e) { console.error('Poll error:', e); }
        };

        poll();
        pollRef.current = setInterval(poll, 2000);
        return () => { if (pollRef.current) clearInterval(pollRef.current); };
    }, [specJobId, aiGenJobId, projectId, onRefreshRuns, aiGenConnId]);

    const createSpec = async () => {
        if (!canEdit) return;
        if (!newSpecName.trim() || !newSpecContent.trim()) return;
        try {
            const res = await fetch(`${API_BASE}${withProjectQuery('/database-testing/specs', projectId)}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
                body: JSON.stringify(withProjectBody({ name: newSpecName, content: newSpecContent }, projectId)),
            });
            if (res.ok) {
                setIsCreatingSpec(false);
                setNewSpecName('');
                setNewSpecContent('');
                onRefreshSpecs();
            }
        } catch (e) { console.error('Create spec failed:', e); }
    };

    const deleteSpec = async (name: string) => {
        if (!canEdit) return;
        if (!confirm(`Delete spec "${name}"?`)) return;
        try {
            await fetch(`${API_BASE}${withProjectQuery(`/database-testing/specs/${encodeURIComponent(name)}`, projectId)}`, {
                method: 'DELETE', headers: getAuthHeaders(),
            });
            onRefreshSpecs();
            if (selectedSpec?.name === name) setSelectedSpec(null);
        } catch (e) { console.error('Delete spec failed:', e); }
    };

    const updateSpec = async () => {
        if (!canEdit) return;
        if (!selectedSpec) return;
        try {
            await fetch(`${API_BASE}${withProjectQuery(`/database-testing/specs/${encodeURIComponent(selectedSpec.name)}`, projectId)}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
                body: JSON.stringify(withProjectBody({ content: specContent }, projectId)),
            });
            setEditingSpec(false);
            onRefreshSpecs();
        } catch (e) { console.error('Update spec failed:', e); }
    };

    const loadSpecContent = async (spec: DbSpec) => {
        try {
            const res = await fetch(`${API_BASE}${withProjectQuery(`/database-testing/specs/${encodeURIComponent(spec.name)}`, projectId)}`, {
                headers: getAuthHeaders(),
            });
            if (res.ok) {
                const data = await res.json();
                setSelectedSpec(spec);
                setSpecContent(data.content || '');
                setEditingSpec(false);
            }
        } catch (e) { console.error('Load spec failed:', e); }
    };

    useEffect(() => {
        if (!initialSpecName) return;
        const spec = specs.find(item => item.name === initialSpecName || item.path === initialSpecName || item.path.endsWith(initialSpecName));
        if (!spec || selectedSpec?.name === spec.name) return;
        loadSpecContent(spec);
    }, [initialSpecName, selectedSpec?.name, specs]);

    const runSpec = async (specName: string) => {
        if (!canEdit) return;
        if (!specConnId) { alert('Select a connection first'); return; }
        setRunningSpec(specName);
        try {
            const res = await fetch(`${API_BASE}${withProjectQuery(`/database-testing/run/${specConnId}`, projectId)}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
                body: JSON.stringify(withProjectBody({ spec_name: specName }, projectId)),
            });
            if (res.ok) {
                const data = await res.json();
                if (data.job_id) {
                    setSpecJobId(data.job_id);
                } else {
                    setRunningSpec(null);
                    onRefreshRuns();
                }
            } else {
                setRunningSpec(null);
            }
        } catch (e) {
            console.error('Run spec failed:', e);
            setRunningSpec(null);
        }
    };

    const generateSpecWithAi = async () => {
        if (!canEdit) return;
        if (!aiGenConnId) { alert('Select a connection'); return; }
        if (!aiGenInstructions.trim()) { alert('Describe the checks you want to generate'); return; }
        setIsAiGenerating(true);
        setGeneratedChecks([]);
        setAiGenProgress('Starting AI spec generation...');
        try {
            const body: Record<string, unknown> = withProjectBody({
                connection_id: aiGenConnId,
                instructions: aiGenInstructions.trim(),
                auto_run: false,
                preview_only: true,
            }, projectId);
            if (aiGenSpecName.trim()) body.spec_name = aiGenSpecName.trim();
            const res = await fetch(`${API_BASE}${withProjectQuery('/database-testing/generate-spec', projectId)}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
                body: JSON.stringify(body),
            });
            if (res.ok) {
                const data = await res.json();
                setAiGenJobId(data.job_id);
            } else {
                const err = await res.json().catch(() => ({ detail: 'Failed to start generation' }));
                setAiGenProgress(`Error: ${err.detail || 'Unknown error'}`);
                setIsAiGenerating(false);
            }
        } catch (e) {
            setAiGenProgress(`Error: ${String(e)}`);
            setIsAiGenerating(false);
        }
    };

    const saveGeneratedSpec = async (autoRun: boolean) => {
        if (!canEdit) return;
        if (generatedChecks.length === 0) { alert('Generate checks first'); return; }
        setIsSavingGeneratedSpec(true);
        try {
            const res = await fetch(`${API_BASE}${withProjectQuery('/database-testing/generated-specs/save', projectId)}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
                body: JSON.stringify(withProjectBody({
                    checks: generatedChecks,
                    spec_name: aiGenSpecName || undefined,
                }, projectId)),
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) throw new Error(data.detail || 'Failed to save generated spec');

            await onRefreshSpecs();
            const savedName = data.name as string;
            if (savedName) {
                await loadSpecContent({ name: savedName, path: data.path || '' });
                if (autoRun) await runSpec(savedName);
            }
            setShowAiGenerate(false);
            setGeneratedChecks([]);
            setAiGenProgress('');
            setAiGenSpecName('');
            setAiGenInstructions('');
        } catch (e) {
            setAiGenProgress(`Error: ${e instanceof Error ? e.message : String(e)}`);
        }
        setIsSavingGeneratedSpec(false);
    };

    return (
        <div>
            {/* Connection selector for running specs */}
            {canEdit && (
                <div style={{ ...cardStyle, marginBottom: '1rem', padding: '0.75rem 1rem', display: 'flex', alignItems: 'center', gap: '1rem' }}>
                    <label style={{ fontSize: '0.85rem', fontWeight: 500, whiteSpace: 'nowrap' }}>Run with connection:</label>
                    <select value={specConnId}
                        onChange={e => setSpecConnId(e.target.value)}
                        style={{ ...inputStyle, width: 'auto', flex: 1 }}>
                        <option value="">Select a connection...</option>
                        {connections.map(c => (
                            <option key={c.id} value={c.id}>{c.name} ({c.host}:{c.port}/{c.database})</option>
                        ))}
                    </select>
                </div>
            )}

            <div style={{ display: 'grid', gridTemplateColumns: '300px 1fr', gap: '1rem' }}>
                {/* Spec List */}
                <div style={cardStyle}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
                        <h3 style={{ fontWeight: 600, fontSize: '0.9rem' }}>Database Specs</h3>
                        {canEdit && (
                            <div style={{ display: 'flex', gap: '4px' }}>
                                <button onClick={() => { setShowAiGenerate(!showAiGenerate); setIsCreatingSpec(false); }} style={{
                                    background: showAiGenerate ? 'var(--accent)' : 'var(--accent)', color: 'white', border: 'none',
                                    borderRadius: 'var(--radius)', padding: '4px 8px', cursor: 'pointer',
                                    display: 'flex', alignItems: 'center', gap: '4px', fontSize: '0.8rem',
                                }}>
                                    <Sparkles size={14} /> AI Generate
                                </button>
                                <button onClick={() => { setIsCreatingSpec(true); setShowAiGenerate(false); }} style={{
                                    background: 'var(--primary)', color: 'white', border: 'none',
                                    borderRadius: 'var(--radius)', padding: '4px 8px', cursor: 'pointer',
                                    display: 'flex', alignItems: 'center', gap: '4px', fontSize: '0.8rem',
                                }}>
                                    <Plus size={14} /> New
                                </button>
                            </div>
                        )}
                    </div>

                    {/* AI Generate setup */}
                    {canEdit && showAiGenerate && (
                        <div style={{
                            background: 'rgba(139, 92, 246, 0.08)', border: '1px solid rgba(139, 92, 246, 0.25)',
                            borderRadius: 'var(--radius)', padding: '0.75rem', marginBottom: '0.75rem',
                        }}>
                            <div style={{ marginBottom: '0.5rem' }}>
                                <label style={{ fontSize: '0.75rem', fontWeight: 500, display: 'block', marginBottom: '4px' }}>Connection</label>
                                <select value={aiGenConnId} onChange={e => { setAiGenConnId(e.target.value); setSpecConnId(e.target.value); }}
                                    disabled={isAiGenerating}
                                    style={{ ...inputStyle, fontSize: '0.8rem', padding: '0.35rem 0.5rem' }}>
                                    <option value="">Select connection...</option>
                                    {connections.map(c => (
                                        <option key={c.id} value={c.id}>{c.name} ({c.database})</option>
                                    ))}
                                </select>
                            </div>
                            <div style={{ marginBottom: '0.5rem' }}>
                                <label style={{ fontSize: '0.75rem', fontWeight: 500, display: 'block', marginBottom: '4px' }}>Spec Name (optional)</label>
                                <input type="text" value={aiGenSpecName}
                                    onChange={e => setAiGenSpecName(e.target.value)}
                                    disabled={isAiGenerating}
                                    placeholder="Auto-generated if empty"
                                    style={{ ...inputStyle, fontSize: '0.8rem', padding: '0.35rem 0.5rem' }} />
                            </div>
                            <div style={{ marginBottom: '0.5rem' }}>
                                <label style={{ fontSize: '0.75rem', fontWeight: 500, display: 'block', marginBottom: '4px' }}>Request</label>
                                <textarea value={aiGenInstructions}
                                    onChange={e => setAiGenInstructions(e.target.value)}
                                    disabled={isAiGenerating}
                                    rows={5}
                                    placeholder="Example: validate active customers have valid email addresses, orders reference existing customers, and prices are never negative."
                                    style={{ ...inputStyle, fontSize: '0.8rem', padding: '0.5rem', resize: 'vertical' }} />
                            </div>
                            {isAiGenerating ? (
                                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', padding: '0.5rem 0', fontSize: '0.8rem', color: 'var(--accent)' }}>
                                    <Loader2 size={14} style={{ animation: 'spin 1s linear infinite' }} />
                                    {aiGenProgress}
                                </div>
                            ) : aiGenProgress ? (
                                <div style={{ padding: '0.5rem 0', fontSize: '0.8rem',
                                    color: aiGenProgress.startsWith('Failed') || aiGenProgress.startsWith('Error') ? 'var(--danger)' : 'var(--success)',
                                }}>
                                    {aiGenProgress}
                                </div>
                            ) : null}
                            <div style={{ display: 'flex', gap: '0.5rem', marginTop: '0.5rem' }}>
                                <button onClick={generateSpecWithAi}
                                    disabled={isAiGenerating || !aiGenConnId || !aiGenInstructions.trim()}
                                    style={{
                                        background: isAiGenerating || !aiGenConnId || !aiGenInstructions.trim() ? 'var(--border)' : 'var(--accent)',
                                        color: 'white', border: 'none', borderRadius: 'var(--radius)',
                                        padding: '4px 10px', cursor: isAiGenerating || !aiGenConnId || !aiGenInstructions.trim() ? 'not-allowed' : 'pointer',
                                        fontSize: '0.8rem', display: 'flex', alignItems: 'center', gap: '4px',
                                    }}>
                                    <Sparkles size={12} /> Generate Preview
                                </button>
                            </div>
                        </div>
                    )}

                    {specs.length === 0 && (
                        <p style={{ color: 'var(--text-secondary)', fontSize: '0.85rem' }}>No specs yet</p>
                    )}

                    {specs.map(spec => (
                        <div key={spec.name} onClick={() => loadSpecContent(spec)} style={{
                            padding: '0.5rem 0.75rem', borderRadius: 'var(--radius)', cursor: 'pointer',
                            background: selectedSpec?.name === spec.name ? 'var(--primary-glow)' : 'transparent',
                            display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                            marginBottom: '0.25rem',
                        }}>
                            <span style={{ fontSize: '0.85rem', flex: 1 }}>{spec.name}</span>
                            {canEdit && (
                                <div style={{ display: 'flex', gap: '4px' }}>
                                    <button onClick={e => { e.stopPropagation(); runSpec(spec.name); }}
                                        disabled={runningSpec === spec.name || !specConnId}
                                        style={{
                                            background: 'none', border: 'none', cursor: runningSpec === spec.name ? 'not-allowed' : 'pointer',
                                            color: specConnId ? 'var(--primary)' : 'var(--text-secondary)', padding: '2px',
                                        }}>
                                        {runningSpec === spec.name
                                            ? <Loader2 size={14} style={{ animation: 'spin 1s linear infinite' }} />
                                            : <Play size={14} />}
                                    </button>
                                    <button onClick={e => { e.stopPropagation(); deleteSpec(spec.name); }} style={{
                                        background: 'none', border: 'none', cursor: 'pointer',
                                        color: 'var(--text-secondary)', padding: '2px',
                                    }}>
                                        <Trash2 size={14} />
                                    </button>
                                </div>
                            )}
                        </div>
                    ))}
                </div>

                {/* Spec Editor */}
                <div style={cardStyle}>
                    {canEdit && isCreatingSpec ? (
                        <>
                            <h3 style={{ fontWeight: 600, marginBottom: '1rem' }}>Create New Spec</h3>
                            <input
                                type="text"
                                placeholder="Spec name (e.g., data-quality-checks)"
                                value={newSpecName}
                                onChange={e => setNewSpecName(e.target.value)}
                                style={{ ...inputStyle, marginBottom: '1rem' }}
                            />
                            <div style={{ height: '400px', marginBottom: '1rem' }}>
                                <CodeEditor
                                    value={newSpecContent}
                                    onChange={(v: string) => setNewSpecContent(v)}
                                    language="markdown"
                                />
                            </div>
                            <div style={{ display: 'flex', gap: '0.5rem' }}>
                                <button onClick={createSpec} style={btnPrimary}>
                                    <Save size={14} /> Save
                                </button>
                                <button onClick={() => setIsCreatingSpec(false)} style={btnSecondary}>
                                    Cancel
                                </button>
                            </div>
                        </>
                    ) : canEdit && showAiGenerate ? (
                        <>
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
                                <h3 style={{ fontWeight: 600 }}>Generated Spec Preview</h3>
                                {generatedChecks.length > 0 && (
                                    <div style={{ display: 'flex', gap: '0.5rem' }}>
                                        <button onClick={() => saveGeneratedSpec(false)}
                                            disabled={isSavingGeneratedSpec}
                                            style={{ ...btnPrimary, padding: '4px 12px', fontSize: '0.8rem' }}>
                                            {isSavingGeneratedSpec ? <Loader2 size={14} style={{ animation: 'spin 1s linear infinite' }} /> : <Save size={14} />}
                                            Save Spec
                                        </button>
                                        <button onClick={() => saveGeneratedSpec(true)}
                                            disabled={isSavingGeneratedSpec || !specConnId}
                                            style={{ ...btnSecondary, padding: '4px 12px', fontSize: '0.8rem' }}>
                                            <Play size={14} /> Save & Run
                                        </button>
                                    </div>
                                )}
                            </div>
                            {generatedChecks.length === 0 ? (
                                <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem' }}>
                                    Describe the checks in the AI Generate panel, then generate a preview.
                                </p>
                            ) : (
                                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                                    {generatedChecks.map((check, idx) => (
                                        <div key={`${check.check_name}-${idx}`} style={{
                                            border: '1px solid var(--border)',
                                            borderRadius: 'var(--radius)',
                                            padding: '0.85rem',
                                        }}>
                                            <div style={{ display: 'flex', justifyContent: 'space-between', gap: '1rem', marginBottom: '0.5rem' }}>
                                                <div>
                                                    <div style={{ fontWeight: 600, fontSize: '0.9rem' }}>{check.check_name || `check_${idx + 1}`}</div>
                                                    <div style={{ color: 'var(--text-secondary)', fontSize: '0.78rem' }}>
                                                        {check.check_type || 'custom'} | {check.severity || 'medium'}
                                                        {check.table_name ? ` | ${check.table_name}${check.column_name ? `.${check.column_name}` : ''}` : ''}
                                                    </div>
                                                </div>
                                                <span style={{ color: 'var(--text-secondary)', fontSize: '0.75rem' }}>
                                                    Expect empty: {String(check.expect_empty ?? true)}
                                                </span>
                                            </div>
                                            {check.description && (
                                                <p style={{ color: 'var(--text-secondary)', fontSize: '0.85rem', marginBottom: '0.5rem' }}>{check.description}</p>
                                            )}
                                            <pre style={{
                                                margin: 0,
                                                padding: '0.75rem',
                                                background: '#1e1e1e',
                                                color: '#d4d4d4',
                                                borderRadius: 'var(--radius)',
                                                overflow: 'auto',
                                                fontSize: '0.78rem',
                                            }}>{check.sql_query}</pre>
                                        </div>
                                    ))}
                                </div>
                            )}
                        </>
                    ) : selectedSpec ? (
                        <>
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
                                <h3 style={{ fontWeight: 600 }}>{selectedSpec.name}</h3>
                                {canEdit && (
                                <div style={{ display: 'flex', gap: '0.5rem' }}>
                                    {editingSpec ? (
                                        <>
                                            <button onClick={updateSpec} style={{
                                                ...btnPrimary, padding: '4px 12px', fontSize: '0.8rem',
                                            }}>
                                                <Save size={14} /> Save
                                            </button>
                                            <button onClick={() => setEditingSpec(false)} style={{
                                                ...btnSecondary, padding: '4px 12px', fontSize: '0.8rem',
                                            }}>
                                                Cancel
                                            </button>
                                        </>
                                    ) : (
                                        <>
                                            <button onClick={() => setEditingSpec(true)} style={{
                                                ...btnSecondary, padding: '4px 12px', fontSize: '0.8rem',
                                            }}>
                                                <Edit2 size={14} /> Edit
                                            </button>
                                            <button onClick={() => runSpec(selectedSpec.name)}
                                                disabled={runningSpec === selectedSpec.name || !specConnId}
                                                style={{
                                                    ...btnPrimary, padding: '4px 12px', fontSize: '0.8rem',
                                                    cursor: runningSpec === selectedSpec.name || !specConnId ? 'not-allowed' : 'pointer',
                                                    background: runningSpec === selectedSpec.name || !specConnId ? 'var(--border)' : 'var(--primary)',
                                                }}>
                                                {runningSpec === selectedSpec.name
                                                    ? <Loader2 size={14} style={{ animation: 'spin 1s linear infinite' }} />
                                                    : <Play size={14} />}
                                                Run
                                            </button>
                                        </>
                                    )}
                                </div>
                                )}
                            </div>
                            <div style={{ height: '500px' }}>
                                {editingSpec && canEdit ? (
                                    <CodeEditor
                                        value={specContent}
                                        onChange={(v: string) => setSpecContent(v)}
                                        language="markdown"
                                        readOnly={!canEdit}
                                    />
                                ) : (
                                    <SyntaxHighlighter
                                        language="markdown"
                                        style={vscDarkPlus}
                                        customStyle={{ height: '100%', margin: 0, borderRadius: 'var(--radius)' }}
                                    >
                                        {specContent}
                                    </SyntaxHighlighter>
                                )}
                            </div>
                        </>
                    ) : (
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '300px', color: 'var(--text-secondary)' }}>
                            Select a spec to view or create a new one
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}
