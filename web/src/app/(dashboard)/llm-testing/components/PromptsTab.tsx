'use client';
import { useState, useEffect, useCallback, useMemo } from 'react';
import { API_BASE } from '@/lib/api';
import { cardStyle, cardStyleCompact, inputStyle, btnPrimary, btnSecondary, btnSmall, labelStyle } from '@/lib/styles';
import { toast } from 'sonner';
import { ConfirmDialog } from '@/components/ui/confirm-dialog';
import { usePolling } from '@/hooks/usePolling';
import VersionDiffView from './VersionDiffView';
import type { Spec, Provider, Run, SpecVersion, PromptIteration } from './types';

interface PromptsTabProps {
    projectId: string;
}

export default function PromptsTab({ projectId }: PromptsTabProps) {
    // State
    const [specs, setSpecs] = useState<Spec[]>([]);
    const [selectedSpec, setSelectedSpec] = useState('');
    const [versions, setVersions] = useState<SpecVersion[]>([]);
    const [providers, setProviders] = useState<Provider[]>([]);
    const [runs, setRuns] = useState<Run[]>([]);
    const [loading, setLoading] = useState(false);

    // Version save
    const [changeSummary, setChangeSummary] = useState('');
    const [saving, setSaving] = useState(false);

    // A/B iteration
    const [versionA, setVersionA] = useState<number | ''>('');
    const [versionB, setVersionB] = useState<number | ''>('');
    const [abProvider, setAbProvider] = useState('');
    const [abName, setAbName] = useState('');
    const [iterations, setIterations] = useState<PromptIteration[]>([]);
    const [startingAB, setStartingAB] = useState(false);

    // Diff modal
    const [diffModal, setDiffModal] = useState<{ oldContent: string; newContent: string; oldVersion: number; newVersion: number } | null>(null);

    // Suggestions
    const [selectedRunForSuggest, setSelectedRunForSuggest] = useState('');
    const [suggestions, setSuggestions] = useState<{ suggestions: string; modified_spec: string; failed_count: number } | null>(null);
    const [analyzing, setAnalyzing] = useState(false);
    const [suggestionsOpen, setSuggestionsOpen] = useState(false);

    // Confirm dialog for restore
    const [restoreConfirm, setRestoreConfirm] = useState<{ open: boolean; version: number }>({ open: false, version: 0 });

    // Auto-refresh running iterations
    const hasRunningIteration = useMemo(
        () => iterations.some(it => it.status === 'running'),
        [iterations]
    );

    usePolling(
        async () => {
            if (!selectedSpec) return;
            const res = await fetch(`${API_BASE}/llm-testing/prompt-iterations?project_id=${projectId}&spec_name=${selectedSpec}`);
            if (res.ok) {
                const it = await res.json();
                setIterations(it);
            }
        },
        { interval: 3000, enabled: hasRunningIteration }
    );

    // Load specs and providers
    useEffect(() => {
        fetch(`${API_BASE}/llm-testing/specs?project_id=${projectId}`).then(r => r.json()).then(setSpecs).catch(() => { toast.error('Failed to load specs'); });
        fetch(`${API_BASE}/llm-testing/providers?project_id=${projectId}`).then(r => r.json()).then(setProviders).catch(() => { toast.error('Failed to load providers'); });
        fetch(`${API_BASE}/llm-testing/runs?project_id=${projectId}&limit=50`).then(r => r.json()).then(setRuns).catch(() => { toast.error('Failed to load runs'); });
    }, [projectId]);

    // Load versions when spec is selected
    useEffect(() => {
        if (!selectedSpec) {
            setVersions([]);
            setIterations([]);
            return;
        }
        setLoading(true);
        Promise.all([
            fetch(`${API_BASE}/llm-testing/specs/${selectedSpec}/versions?project_id=${projectId}`).then(r => r.json()),
            fetch(`${API_BASE}/llm-testing/prompt-iterations?project_id=${projectId}&spec_name=${selectedSpec}`).then(r => r.json()),
        ]).then(([v, it]) => {
            setVersions(v);
            setIterations(it);
        }).catch(() => { toast.error('Failed to load version data'); }).finally(() => setLoading(false));
    }, [selectedSpec, projectId]);

    // Save version
    const handleSaveVersion = useCallback(async () => {
        if (!selectedSpec) return;
        setSaving(true);
        try {
            const res = await fetch(`${API_BASE}/llm-testing/specs/${selectedSpec}/versions`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ change_summary: changeSummary, project_id: projectId }),
            });
            if (res.ok) {
                setChangeSummary('');
                toast.success('Version saved');
                const v = await fetch(`${API_BASE}/llm-testing/specs/${selectedSpec}/versions?project_id=${projectId}`).then(r => r.json());
                setVersions(v);
            } else {
                toast.error('Failed to save version');
            }
        } catch {
            toast.error('Failed to save version');
        } finally {
            setSaving(false);
        }
    }, [selectedSpec, changeSummary, projectId]);

    // Restore version
    const handleRestore = useCallback(async (version: number) => {
        if (!selectedSpec) return;
        try {
            const res = await fetch(`${API_BASE}/llm-testing/specs/${selectedSpec}/versions/${version}/restore?project_id=${projectId}`, { method: 'POST' });
            if (res.ok) {
                toast.success(`Restored to version v${version}`);
                const v = await fetch(`${API_BASE}/llm-testing/specs/${selectedSpec}/versions?project_id=${projectId}`).then(r => r.json());
                setVersions(v);
            } else {
                toast.error('Failed to restore version');
            }
        } catch {
            toast.error('Failed to restore version');
        }
    }, [selectedSpec, projectId]);

    // Show diff
    const handleDiff = useCallback(async (version: number) => {
        if (!selectedSpec) return;
        try {
            const [selRes, curRes] = await Promise.all([
                fetch(`${API_BASE}/llm-testing/specs/${selectedSpec}/versions/${version}?project_id=${projectId}`).then(r => r.json()),
                fetch(`${API_BASE}/llm-testing/specs/${selectedSpec}?project_id=${projectId}`).then(r => r.json()),
            ]);
            setDiffModal({
                oldContent: selRes.content,
                newContent: curRes.content,
                oldVersion: version,
                newVersion: versions.length > 0 ? versions[0].version + 1 : version + 1,
            });
        } catch {
            toast.error('Failed to load diff');
        }
    }, [selectedSpec, projectId, versions]);

    // Start A/B test
    const handleStartAB = useCallback(async () => {
        if (!selectedSpec || versionA === '' || versionB === '' || !abProvider || versionA === versionB) return;
        setStartingAB(true);
        try {
            const res = await fetch(`${API_BASE}/llm-testing/prompt-iterations`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    spec_name: selectedSpec,
                    name: abName || undefined,
                    version_a: versionA,
                    version_b: versionB,
                    provider_id: abProvider,
                    project_id: projectId,
                }),
            });
            if (res.ok) {
                toast.success('A/B test started');
                const it = await fetch(`${API_BASE}/llm-testing/prompt-iterations?project_id=${projectId}&spec_name=${selectedSpec}`).then(r => r.json());
                setIterations(it);
            } else {
                toast.error('Failed to start A/B test');
            }
        } catch {
            toast.error('Failed to start A/B test');
        } finally {
            setStartingAB(false);
        }
    }, [selectedSpec, versionA, versionB, abProvider, abName, projectId]);

    // Suggest improvements
    const handleAnalyze = useCallback(async () => {
        if (!selectedSpec) return;
        setAnalyzing(true);
        setSuggestions(null);
        try {
            const res = await fetch(`${API_BASE}/llm-testing/specs/${selectedSpec}/suggest-improvements`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ run_id: selectedRunForSuggest || null, project_id: projectId }),
            });
            if (res.ok) {
                const data = await res.json();
                setSuggestions(data);
            } else {
                toast.error('Failed to analyze suggestions');
            }
        } catch {
            toast.error('Failed to analyze suggestions');
        } finally {
            setAnalyzing(false);
        }
    }, [selectedSpec, selectedRunForSuggest, projectId]);

    // Filter failed runs
    const failedRuns = runs.filter(r => r.failed_cases > 0 && r.status === 'completed');

    const sameVersionSelected = versionA !== '' && versionB !== '' && versionA === versionB;

    return (
        <div>
            <h2 style={{ fontSize: '1.1rem', fontWeight: 600, marginBottom: '1rem' }}>Prompt Engineering</h2>

            {/* Spec Selector */}
            <div style={{ marginBottom: '1rem' }}>
                <label style={labelStyle}>Select Spec</label>
                <select value={selectedSpec} onChange={e => setSelectedSpec(e.target.value)} style={inputStyle}>
                    <option value="">Choose a spec...</option>
                    {specs.map(s => <option key={s.name} value={s.name}>{s.name}</option>)}
                </select>
            </div>

            {selectedSpec && (
                <div style={{ display: 'flex', gap: '1rem', alignItems: 'flex-start' }}>
                    {/* Left: Version Timeline */}
                    <div style={{ width: 350, minWidth: 350, flexShrink: 0 }}>
                        <div style={{ ...cardStyle, padding: '1rem' }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.75rem' }}>
                                <h3 style={{ fontSize: '0.95rem', fontWeight: 600, margin: 0 }}>Versions</h3>
                            </div>

                            {/* Save new version */}
                            <div style={{ marginBottom: '0.75rem', display: 'flex', gap: '0.5rem' }}>
                                <input
                                    value={changeSummary}
                                    onChange={e => setChangeSummary(e.target.value)}
                                    placeholder="Change summary..."
                                    style={{ ...inputStyle, flex: 1 }}
                                />
                                <button onClick={handleSaveVersion} disabled={saving} style={{ ...btnSmall, whiteSpace: 'nowrap' }}>
                                    {saving ? '...' : 'Save'}
                                </button>
                            </div>

                            {loading && <div style={{ color: 'var(--text-secondary)', fontSize: '0.85rem' }}>Loading...</div>}

                            {/* Version list */}
                            <div style={{ maxHeight: 500, overflowY: 'auto' }}>
                                {versions.length === 0 && !loading && (
                                    <div style={{ color: 'var(--text-secondary)', fontSize: '0.85rem', textAlign: 'center', padding: '1rem' }}>
                                        No versions yet. Save one to start tracking.
                                    </div>
                                )}
                                {versions.map(v => (
                                    <div key={v.id} style={{
                                        padding: '0.6rem',
                                        borderBottom: '1px solid var(--border)',
                                        fontSize: '0.85rem',
                                    }}>
                                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                                            <span style={{ fontWeight: 600 }}>v{v.version}</span>
                                            <span style={{ color: 'var(--text-secondary)', fontSize: '0.75rem' }}>
                                                {v.created_at ? new Date(v.created_at).toLocaleDateString() : ''}
                                            </span>
                                        </div>
                                        <div style={{ color: 'var(--text-secondary)', fontSize: '0.8rem', marginTop: '0.2rem' }}>
                                            {v.change_summary || 'No description'}
                                        </div>
                                        <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', marginTop: '0.2rem', fontFamily: 'monospace' }}>
                                            hash: {v.system_prompt_hash?.substring(0, 12)}...
                                        </div>
                                        {v.run_ids.length > 0 && (
                                            <div style={{ fontSize: '0.75rem', color: 'var(--primary)', marginTop: '0.15rem' }}>
                                                {v.run_ids.length} run(s) linked
                                            </div>
                                        )}
                                        <div style={{ display: 'flex', gap: '0.5rem', marginTop: '0.4rem' }}>
                                            <button onClick={() => setRestoreConfirm({ open: true, version: v.version })} style={btnSmall}>Restore</button>
                                            <button onClick={() => handleDiff(v.version)} style={btnSmall}>Diff</button>
                                        </div>
                                    </div>
                                ))}
                            </div>
                        </div>
                    </div>

                    {/* Right: A/B Iteration Panel + Suggestions */}
                    <div style={{ flex: 1, minWidth: 0 }}>
                        {/* A/B Iteration Panel */}
                        <div style={{ ...cardStyle, marginBottom: '1rem' }}>
                            <h3 style={{ fontSize: '0.95rem', fontWeight: 600, marginBottom: '0.75rem' }}>A/B Iteration Test</h3>

                            <div style={{ display: 'flex', gap: '0.75rem', marginBottom: '0.75rem', flexWrap: 'wrap' }}>
                                <div style={{ flex: 1, minWidth: 120 }}>
                                    <label style={labelStyle}>Version A</label>
                                    <select value={versionA} onChange={e => setVersionA(e.target.value ? Number(e.target.value) : '')} style={inputStyle}>
                                        <option value="">Select...</option>
                                        {versions.map(v => <option key={v.version} value={v.version}>v{v.version}</option>)}
                                    </select>
                                </div>
                                <div style={{ flex: 1, minWidth: 120 }}>
                                    <label style={labelStyle}>Version B</label>
                                    <select value={versionB} onChange={e => setVersionB(e.target.value ? Number(e.target.value) : '')} style={inputStyle}>
                                        <option value="">Select...</option>
                                        {versions.map(v => <option key={v.version} value={v.version}>v{v.version}</option>)}
                                    </select>
                                </div>
                                <div style={{ flex: 1, minWidth: 150 }}>
                                    <label style={labelStyle}>Provider</label>
                                    <select value={abProvider} onChange={e => setAbProvider(e.target.value)} style={inputStyle}>
                                        <option value="">Select...</option>
                                        {providers.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
                                    </select>
                                </div>
                            </div>

                            {sameVersionSelected && (
                                <span style={{ color: 'var(--warning)', fontSize: '0.8rem' }}>Please select different versions for comparison</span>
                            )}

                            <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'flex-end', marginBottom: '0.75rem', marginTop: sameVersionSelected ? '0.5rem' : 0 }}>
                                <div style={{ flex: 1 }}>
                                    <label style={labelStyle}>Name (optional)</label>
                                    <input value={abName} onChange={e => setAbName(e.target.value)} placeholder="e.g. Stricter instructions" style={inputStyle} />
                                </div>
                                <button
                                    onClick={handleStartAB}
                                    disabled={startingAB || versionA === '' || versionB === '' || !abProvider || versionA === versionB}
                                    style={{ ...btnPrimary, opacity: (startingAB || versionA === '' || versionB === '' || !abProvider || versionA === versionB) ? 0.5 : 1 }}
                                >
                                    {startingAB ? 'Starting...' : 'Start A/B Test'}
                                </button>
                            </div>

                            {/* Iteration results */}
                            {iterations.length > 0 && (
                                <div style={{ marginTop: '0.75rem' }}>
                                    <h4 style={{ fontSize: '0.85rem', fontWeight: 600, marginBottom: '0.5rem', color: 'var(--text-secondary)' }}>
                                        Recent Iterations
                                    </h4>
                                    {iterations.map(it => (
                                        <div key={it.id} style={{
                                            ...cardStyleCompact,
                                            padding: '0.75rem',
                                        }}>
                                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
                                                <span style={{ fontWeight: 600, fontSize: '0.85rem' }}>{it.name || `v${it.version_a} vs v${it.version_b}`}</span>
                                                <span style={{
                                                    fontSize: '0.75rem',
                                                    padding: '0.15rem 0.5rem',
                                                    borderRadius: 4,
                                                    background: it.status === 'completed' ? 'rgba(34,197,94,0.1)' : it.status === 'running' ? 'rgba(59,130,246,0.1)' : 'rgba(239,68,68,0.1)',
                                                    color: it.status === 'completed' ? 'var(--success)' : it.status === 'running' ? 'var(--primary)' : 'var(--danger)',
                                                }}>
                                                    {it.status}
                                                </span>
                                            </div>

                                            {it.status === 'completed' && it.summary && (
                                                <div style={{ display: 'flex', gap: '1rem' }}>
                                                    {/* Version A results */}
                                                    <div style={{
                                                        flex: 1,
                                                        padding: '0.5rem',
                                                        borderRadius: 'var(--radius)',
                                                        border: `2px solid ${it.winner === 'a' ? 'var(--success)' : 'var(--border)'}`,
                                                        position: 'relative',
                                                    }}>
                                                        {it.winner === 'a' && (
                                                            <span style={{
                                                                position: 'absolute', top: -8, right: 8,
                                                                background: 'var(--success)', color: 'white',
                                                                fontSize: '0.7rem', padding: '0.1rem 0.4rem',
                                                                borderRadius: 4, fontWeight: 600,
                                                            }}>Winner</span>
                                                        )}
                                                        <div style={{ fontSize: '0.8rem', fontWeight: 600, marginBottom: '0.25rem' }}>v{it.version_a}</div>
                                                        <div style={{ fontSize: '0.8rem' }}>Pass: {it.summary.version_a?.pass_rate ?? '-'}%</div>
                                                        <div style={{ fontSize: '0.8rem' }}>Latency: {it.summary.version_a?.avg_latency_ms != null ? `${Math.round(it.summary.version_a.avg_latency_ms)}ms` : '-'}</div>
                                                        <div style={{ fontSize: '0.8rem' }}>Cost: ${it.summary.version_a?.total_cost_usd?.toFixed(4) ?? '-'}</div>
                                                    </div>

                                                    {/* Version B results */}
                                                    <div style={{
                                                        flex: 1,
                                                        padding: '0.5rem',
                                                        borderRadius: 'var(--radius)',
                                                        border: `2px solid ${it.winner === 'b' ? 'var(--success)' : 'var(--border)'}`,
                                                        position: 'relative',
                                                    }}>
                                                        {it.winner === 'b' && (
                                                            <span style={{
                                                                position: 'absolute', top: -8, right: 8,
                                                                background: 'var(--success)', color: 'white',
                                                                fontSize: '0.7rem', padding: '0.1rem 0.4rem',
                                                                borderRadius: 4, fontWeight: 600,
                                                            }}>Winner</span>
                                                        )}
                                                        <div style={{ fontSize: '0.8rem', fontWeight: 600, marginBottom: '0.25rem' }}>v{it.version_b}</div>
                                                        <div style={{ fontSize: '0.8rem' }}>Pass: {it.summary.version_b?.pass_rate ?? '-'}%</div>
                                                        <div style={{ fontSize: '0.8rem' }}>Latency: {it.summary.version_b?.avg_latency_ms != null ? `${Math.round(it.summary.version_b.avg_latency_ms)}ms` : '-'}</div>
                                                        <div style={{ fontSize: '0.8rem' }}>Cost: ${it.summary.version_b?.total_cost_usd?.toFixed(4) ?? '-'}</div>
                                                    </div>
                                                </div>
                                            )}

                                            {it.status === 'running' && (
                                                <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
                                                    Running A/B comparison...
                                                </div>
                                            )}
                                        </div>
                                    ))}
                                </div>
                            )}
                        </div>

                        {/* AI Suggestions Panel */}
                        <div style={{ ...cardStyle }}>
                            <div
                                style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', cursor: 'pointer' }}
                                onClick={() => setSuggestionsOpen(!suggestionsOpen)}
                            >
                                <h3 style={{ fontSize: '0.95rem', fontWeight: 600, margin: 0 }}>AI Suggestions</h3>
                                <span style={{ color: 'var(--text-secondary)', fontSize: '0.85rem' }}>
                                    {suggestionsOpen ? 'Collapse' : 'Expand'}
                                </span>
                            </div>

                            {suggestionsOpen && (
                                <div style={{ marginTop: '0.75rem' }}>
                                    <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'flex-end', marginBottom: '0.75rem' }}>
                                        <div style={{ flex: 1 }}>
                                            <label style={labelStyle}>Select a failed run</label>
                                            <select value={selectedRunForSuggest} onChange={e => setSelectedRunForSuggest(e.target.value)} style={inputStyle}>
                                                <option value="">All runs (no specific failures)...</option>
                                                {failedRuns.map(r => (
                                                    <option key={r.id} value={r.id}>
                                                        {r.spec_name} - {r.failed_cases} failures ({r.created_at ? new Date(r.created_at).toLocaleDateString() : ''})
                                                    </option>
                                                ))}
                                            </select>
                                        </div>
                                        <button
                                            onClick={handleAnalyze}
                                            disabled={analyzing}
                                            style={{ ...btnSecondary, opacity: analyzing ? 0.5 : 1 }}
                                        >
                                            {analyzing ? 'Analyzing...' : 'Analyze'}
                                        </button>
                                    </div>

                                    {suggestions && (
                                        <div style={{ marginTop: '0.5rem' }}>
                                            <div style={{
                                                padding: '0.75rem',
                                                background: 'var(--background)',
                                                borderRadius: 'var(--radius)',
                                                border: '1px solid var(--border)',
                                                fontSize: '0.85rem',
                                                marginBottom: '0.5rem',
                                            }}>
                                                <div style={{ fontWeight: 600, marginBottom: '0.25rem' }}>
                                                    {suggestions.failed_count} failed test case(s) analyzed
                                                </div>
                                                <div style={{ whiteSpace: 'pre-wrap', color: 'var(--text-secondary)' }}>
                                                    {suggestions.suggestions}
                                                </div>
                                            </div>
                                            {suggestions.modified_spec && (
                                                <button
                                                    onClick={() => {
                                                        navigator.clipboard.writeText(suggestions.modified_spec);
                                                        toast.success('Modified spec copied to clipboard');
                                                    }}
                                                    style={btnSmall}
                                                >
                                                    Copy Modified Spec
                                                </button>
                                            )}
                                        </div>
                                    )}
                                </div>
                            )}
                        </div>
                    </div>
                </div>
            )}

            {!selectedSpec && (
                <div style={{ textAlign: 'center', padding: '3rem', color: 'var(--text-secondary)' }}>
                    Select a spec to manage versions and run A/B prompt iterations.
                </div>
            )}

            {/* Diff Modal */}
            {diffModal && (
                <div style={{
                    position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
                    background: 'rgba(0,0,0,0.5)', display: 'flex', alignItems: 'center',
                    justifyContent: 'center', zIndex: 1000,
                }} onClick={() => setDiffModal(null)}>
                    <div style={{
                        ...cardStyle,
                        width: '90%', maxWidth: 900, maxHeight: '80vh',
                        overflow: 'auto',
                    }} onClick={e => e.stopPropagation()}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
                            <h3 style={{ fontSize: '1rem', fontWeight: 600, margin: 0 }}>Version Diff</h3>
                            <button onClick={() => setDiffModal(null)} style={btnSmall}>Close</button>
                        </div>
                        <VersionDiffView
                            oldContent={diffModal.oldContent}
                            newContent={diffModal.newContent}
                            oldVersion={diffModal.oldVersion}
                            newVersion={diffModal.newVersion}
                        />
                    </div>
                </div>
            )}

            {/* Confirm Dialog for Restore */}
            <ConfirmDialog
                open={restoreConfirm.open}
                onOpenChange={open => setRestoreConfirm(prev => ({ ...prev, open }))}
                title="Restore Version"
                description={`Restore version v${restoreConfirm.version}? This will overwrite current spec content.`}
                confirmLabel="Restore"
                variant="default"
                onConfirm={() => handleRestore(restoreConfirm.version)}
            />
        </div>
    );
}
