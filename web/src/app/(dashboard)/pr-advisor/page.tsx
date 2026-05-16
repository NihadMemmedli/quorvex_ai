'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import {
    AlertTriangle,
    CheckCircle2,
    FileCode2,
    GitPullRequest,
    Loader2,
    Play,
    RefreshCw,
    ShieldCheck,
} from 'lucide-react';
import { useProject } from '@/contexts/ProjectContext';
import { API_BASE } from '@/lib/api';
import { PageLayout } from '@/components/ui/page-layout';
import { PageHeader } from '@/components/ui/page-header';
import { EmptyState } from '@/components/ui/empty-state';
import { ListPageSkeleton } from '@/components/ui/page-skeleton';

interface ChangedFile {
    path: string;
    status: string;
    additions: number;
    deletions: number;
    changes: number;
    area: string;
    risk_level: string;
    reason?: string;
}

interface SelectedTest {
    spec_name: string;
    test_path?: string;
    reason: string;
    confidence: string;
    risk_level: string;
    selection_source: string;
    estimated_duration_seconds?: number;
    tags: string[];
    categories: string[];
}

interface PrAnalysis {
    id: string;
    pr_number: number;
    title?: string;
    owner: string;
    repo: string;
    base_ref?: string;
    head_ref?: string;
    risk_level: string;
    confidence: string;
    summary?: string;
    fallback_reason?: string;
    changed_files_count: number;
    selected_tests_count: number;
    total_candidate_tests: number;
    estimated_duration_seconds?: number;
    saved_tests_count?: number;
    category_summary?: {
        changed_file_areas?: Record<string, number>;
        selection_sources?: Record<string, number>;
    };
    repository_index_snapshot?: string;
    batch_id?: string;
    created_at?: string;
    changed_files?: ChangedFile[];
    selected_tests?: SelectedTest[];
}

function badgeColor(value: string): string {
    switch (value) {
        case 'high':
        case 'critical':
            return 'rgba(239, 68, 68, 0.14)';
        case 'medium':
            return 'rgba(245, 158, 11, 0.14)';
        case 'low':
            return 'rgba(34, 197, 94, 0.14)';
        default:
            return 'rgba(148, 163, 184, 0.14)';
    }
}

function badgeTextColor(value: string): string {
    switch (value) {
        case 'high':
        case 'critical':
            return '#ef4444';
        case 'medium':
            return '#f59e0b';
        case 'low':
            return '#22c55e';
        default:
            return 'var(--text-secondary)';
    }
}

function formatDuration(seconds?: number): string {
    if (!seconds) return 'Unknown';
    if (seconds < 60) return `${seconds}s`;
    const minutes = Math.round(seconds / 60);
    if (minutes < 60) return `${minutes}m`;
    return `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
}

function formatApiError(detail: unknown): string {
    const text = typeof detail === 'string' ? detail : 'Request failed';
    const firstLine = text.split('\n')[0] || text;
    if (firstLine.includes('ForeignKeyViolation')) {
        return 'Analysis storage failed while saving recommendation details. Please retry after the backend is updated.';
    }
    return firstLine.length > 220 ? `${firstLine.slice(0, 217)}...` : firstLine;
}

function StatusBadge({ label, value }: { label: string; value: string }) {
    return (
        <span style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: '0.35rem',
            padding: '0.25rem 0.5rem',
            borderRadius: '999px',
            background: badgeColor(value),
            color: badgeTextColor(value),
            fontSize: '0.75rem',
            fontWeight: 700,
            textTransform: 'capitalize',
        }}>
            {label ? `${label}: ` : ''}{value}
        </span>
    );
}

export default function PrAdvisorPage() {
    const { currentProject } = useProject();
    const projectId = currentProject?.id || (typeof window !== 'undefined' ? localStorage.getItem('selectedProjectId') : null) || 'default';
    const pid = encodeURIComponent(projectId);

    const [configured, setConfigured] = useState<boolean | null>(null);
    const [prNumber, setPrNumber] = useState('');
    const [analyses, setAnalyses] = useState<PrAnalysis[]>([]);
    const [selected, setSelected] = useState<PrAnalysis | null>(null);
    const [loading, setLoading] = useState(true);
    const [analyzing, setAnalyzing] = useState(false);
    const [running, setRunning] = useState(false);
    const [error, setError] = useState('');

    const fetchAnalyses = useCallback(async () => {
        const res = await fetch(`${API_BASE}/github/${pid}/pr-advisor/analyses`);
        if (!res.ok) return [];
        return await res.json();
    }, [pid]);

    const loadDetail = useCallback(async (analysisId: string) => {
        const res = await fetch(`${API_BASE}/github/${pid}/pr-advisor/analyses/${analysisId}`);
        if (!res.ok) return;
        const data = await res.json();
        setSelected(data);
        setAnalyses(prev => prev.map(item => item.id === data.id ? data : item));
    }, [pid]);

    useEffect(() => {
        (async () => {
            setLoading(true);
            setError('');
            try {
                const configRes = await fetch(`${API_BASE}/github/${pid}/config`);
                if (configRes.ok) {
                    const cfg = await configRes.json();
                    setConfigured(!!cfg.configured && !!cfg.repo);
                    if (cfg.configured && cfg.repo) {
                        const list = await fetchAnalyses();
                        setAnalyses(list);
                        if (list.length > 0) {
                            await loadDetail(list[0].id);
                        } else {
                            setSelected(null);
                        }
                    }
                } else {
                    setConfigured(false);
                }
            } catch (e: any) {
                setError(e.message || 'Failed to load PR advisor');
                setConfigured(false);
            } finally {
                setLoading(false);
            }
        })();
    }, [pid, fetchAnalyses, loadDetail]);

    const analyze = async () => {
        const parsed = Number(prNumber);
        if (!Number.isInteger(parsed) || parsed <= 0) {
            setError('Enter a valid PR number');
            return;
        }
        setAnalyzing(true);
        setError('');
        try {
            const res = await fetch(`${API_BASE}/github/${pid}/pr-advisor/analyze`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ pr_number: parsed, ensure_indexed: true }),
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) {
                setError(formatApiError(data.detail || `Analysis failed (${res.status})`));
                return;
            }
            setSelected(data);
            setAnalyses(prev => [data, ...prev.filter(item => item.id !== data.id)]);
            setPrNumber('');
        } catch (e: any) {
            setError(e.message || 'Analysis failed');
        } finally {
            setAnalyzing(false);
        }
    };

    const runRecommended = async () => {
        if (!selected) return;
        setRunning(true);
        setError('');
        try {
            const res = await fetch(`${API_BASE}/github/${pid}/pr-advisor/analyses/${selected.id}/run`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ browser: 'chromium', hybrid: false, max_iterations: 20 }),
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) {
                setError(data.detail || `Run failed (${res.status})`);
                return;
            }
            setSelected(prev => prev ? { ...prev, batch_id: data.batch_id } : prev);
            window.location.href = `/regression/batches/${data.batch_id}`;
        } catch (e: any) {
            setError(e.message || 'Run failed');
        } finally {
            setRunning(false);
        }
    };

    const fileAreas = useMemo(() => {
        const areas = selected?.category_summary?.changed_file_areas || {};
        return Object.entries(areas);
    }, [selected]);

    if (loading) {
        return (
            <PageLayout tier="standard">
                <ListPageSkeleton rows={5} />
            </PageLayout>
        );
    }

    return (
        <PageLayout tier="standard">
            <PageHeader
                title="PR Advisor"
                subtitle="Analyze changed files and run the recommended regression set"
                icon={<GitPullRequest size={20} />}
                actions={
                    configured ? (
                        <button
                            onClick={() => window.location.reload()}
                            style={{
                                display: 'inline-flex',
                                alignItems: 'center',
                                gap: '0.4rem',
                                padding: '0.5rem 0.75rem',
                                border: '1px solid var(--border)',
                                borderRadius: 'var(--radius)',
                                color: 'var(--text-secondary)',
                                background: 'transparent',
                                cursor: 'pointer',
                                fontSize: '0.85rem',
                            }}
                        >
                            <RefreshCw size={14} />
                            Refresh
                        </button>
                    ) : null
                }
            />

            {!configured ? (
                <EmptyState
                    icon={<GitPullRequest size={32} />}
                    title="GitHub repository is not configured"
                    description="Set owner, repository, and token in Settings before analyzing pull requests."
                    action={<Link href="/settings" style={{ color: 'var(--primary)', fontWeight: 700 }}>Open Settings</Link>}
                />
            ) : (
                <>
                    <div style={{
                        display: 'grid',
                        gridTemplateColumns: 'minmax(260px, 360px) minmax(0, 1fr)',
                        gap: '1rem',
                        alignItems: 'start',
                    }}>
                        <section style={{
                            border: '1px solid var(--border)',
                            borderRadius: 'var(--radius)',
                            background: 'var(--surface)',
                            overflow: 'hidden',
                        }}>
                            <div style={{ padding: '1rem', borderBottom: '1px solid var(--border)' }}>
                                <label style={{ display: 'block', color: 'var(--text-secondary)', fontSize: '0.78rem', marginBottom: '0.35rem' }}>
                                    Pull request
                                </label>
                                <div style={{ display: 'flex', gap: '0.5rem' }}>
                                    <input
                                        value={prNumber}
                                        onChange={e => setPrNumber(e.target.value)}
                                        placeholder="#"
                                        inputMode="numeric"
                                        style={{
                                            flex: 1,
                                            minWidth: 0,
                                            padding: '0.55rem 0.65rem',
                                            border: '1px solid var(--border)',
                                            borderRadius: 'var(--radius)',
                                            background: 'var(--background)',
                                            color: 'var(--text)',
                                            fontSize: '0.9rem',
                                        }}
                                    />
                                    <button
                                        onClick={analyze}
                                        disabled={analyzing}
                                        style={{
                                            display: 'inline-flex',
                                            alignItems: 'center',
                                            gap: '0.4rem',
                                            padding: '0.55rem 0.75rem',
                                            border: 'none',
                                            borderRadius: 'var(--radius)',
                                            background: 'var(--primary)',
                                            color: '#fff',
                                            cursor: analyzing ? 'default' : 'pointer',
                                            fontWeight: 700,
                                            opacity: analyzing ? 0.7 : 1,
                                        }}
                                    >
                                        {analyzing ? <Loader2 size={15} className="spin" /> : <ShieldCheck size={15} />}
                                        {analyzing ? 'Indexing...' : 'Analyze'}
                                    </button>
                                </div>
                                {error && (
                                    <div style={{ marginTop: '0.75rem', color: 'var(--danger)', fontSize: '0.82rem' }}>
                                        {error}
                                    </div>
                                )}
                            </div>

                            <div style={{ maxHeight: '62vh', overflow: 'auto' }}>
                                {analyses.length === 0 ? (
                                    <div style={{ padding: '1rem', color: 'var(--text-secondary)', fontSize: '0.9rem' }}>
                                        No PR analyses yet.
                                    </div>
                                ) : analyses.map(item => (
                                    <button
                                        key={item.id}
                                        onClick={() => loadDetail(item.id)}
                                        style={{
                                            width: '100%',
                                            textAlign: 'left',
                                            padding: '0.85rem 1rem',
                                            border: 'none',
                                            borderBottom: '1px solid var(--border)',
                                            background: selected?.id === item.id ? 'rgba(59, 130, 246, 0.08)' : 'transparent',
                                            color: 'var(--text)',
                                            cursor: 'pointer',
                                        }}
                                    >
                                        <div style={{ display: 'flex', justifyContent: 'space-between', gap: '0.75rem', alignItems: 'center' }}>
                                            <strong style={{ fontSize: '0.9rem' }}>PR #{item.pr_number}</strong>
                                            <StatusBadge label="Risk" value={item.risk_level} />
                                        </div>
                                        <div style={{
                                            marginTop: '0.35rem',
                                            color: 'var(--text-secondary)',
                                            fontSize: '0.8rem',
                                            lineHeight: 1.35,
                                            overflow: 'hidden',
                                            textOverflow: 'ellipsis',
                                            whiteSpace: 'nowrap',
                                        }}>
                                            {item.title || item.summary || item.id}
                                        </div>
                                    </button>
                                ))}
                            </div>
                        </section>

                        {!selected ? (
                            <EmptyState
                                icon={<FileCode2 size={32} />}
                                title="No analysis selected"
                                description="Enter a pull request number to generate recommendations."
                            />
                        ) : (
                            <section style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                                <div style={{
                                    border: '1px solid var(--border)',
                                    borderRadius: 'var(--radius)',
                                    background: 'var(--surface)',
                                    padding: '1rem',
                                }}>
                                    <div style={{ display: 'flex', justifyContent: 'space-between', gap: '1rem', flexWrap: 'wrap' }}>
                                        <div style={{ minWidth: 0 }}>
                                            <h2 style={{ margin: 0, fontSize: '1.1rem', fontWeight: 750 }}>
                                                PR #{selected.pr_number}: {selected.title || 'Untitled'}
                                            </h2>
                                        <div style={{ marginTop: '0.35rem', color: 'var(--text-secondary)', fontSize: '0.85rem' }}>
                                            {selected.owner}/{selected.repo} · {selected.head_ref || 'head'} → {selected.base_ref || 'base'}
                                        </div>
                                        <div style={{ marginTop: '0.35rem', color: 'var(--text-secondary)', fontSize: '0.78rem' }}>
                                            Repository index: {selected.repository_index_snapshot || 'not used'}
                                        </div>
                                    </div>
                                        <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap', alignItems: 'flex-start' }}>
                                            <StatusBadge label="Confidence" value={selected.confidence} />
                                            <StatusBadge label="Risk" value={selected.risk_level} />
                                        </div>
                                    </div>

                                    <div style={{
                                        display: 'grid',
                                        gridTemplateColumns: 'repeat(4, minmax(120px, 1fr))',
                                        gap: '0.75rem',
                                        marginTop: '1rem',
                                    }}>
                                        {[
                                            ['Changed files', selected.changed_files_count],
                                            ['Recommended', `${selected.selected_tests_count}/${selected.total_candidate_tests}`],
                                            ['Skipped', selected.saved_tests_count ?? 0],
                                            ['Est. time', formatDuration(selected.estimated_duration_seconds)],
                                        ].map(([label, value]) => (
                                            <div key={label} style={{
                                                border: '1px solid var(--border)',
                                                borderRadius: 'var(--radius)',
                                                padding: '0.75rem',
                                                background: 'var(--background)',
                                            }}>
                                                <div style={{ color: 'var(--text-secondary)', fontSize: '0.75rem' }}>{label}</div>
                                                <div style={{ marginTop: '0.25rem', fontSize: '1.15rem', fontWeight: 800 }}>{value}</div>
                                            </div>
                                        ))}
                                    </div>

                                    {selected.fallback_reason && (
                                        <div style={{
                                            display: 'flex',
                                            gap: '0.55rem',
                                            alignItems: 'flex-start',
                                            marginTop: '1rem',
                                            padding: '0.75rem',
                                            borderRadius: 'var(--radius)',
                                            border: '1px solid rgba(245, 158, 11, 0.25)',
                                            background: 'rgba(245, 158, 11, 0.08)',
                                            color: '#f59e0b',
                                            fontSize: '0.85rem',
                                        }}>
                                            <AlertTriangle size={16} style={{ flexShrink: 0, marginTop: 1 }} />
                                            {selected.fallback_reason}
                                        </div>
                                    )}

                                    <div style={{ marginTop: '1rem', display: 'flex', gap: '0.6rem', flexWrap: 'wrap' }}>
                                        <button
                                            onClick={runRecommended}
                                            disabled={running || !!selected.batch_id}
                                            style={{
                                                display: 'inline-flex',
                                                alignItems: 'center',
                                                gap: '0.45rem',
                                                padding: '0.6rem 0.85rem',
                                                border: 'none',
                                                borderRadius: 'var(--radius)',
                                                background: 'var(--primary)',
                                                color: '#fff',
                                                cursor: running || selected.batch_id ? 'default' : 'pointer',
                                                fontWeight: 750,
                                                opacity: running || selected.batch_id ? 0.65 : 1,
                                            }}
                                        >
                                            {running ? <Loader2 size={16} className="spin" /> : <Play size={16} />}
                                            {selected.batch_id ? 'Batch Created' : 'Run Recommended'}
                                        </button>
                                        {selected.batch_id && (
                                            <Link href={`/regression/batches/${selected.batch_id}`} style={{
                                                display: 'inline-flex',
                                                alignItems: 'center',
                                                gap: '0.4rem',
                                                padding: '0.6rem 0.85rem',
                                                border: '1px solid var(--border)',
                                                borderRadius: 'var(--radius)',
                                                color: 'var(--primary)',
                                                textDecoration: 'none',
                                                fontWeight: 700,
                                            }}>
                                                <CheckCircle2 size={16} />
                                                View Batch
                                            </Link>
                                        )}
                                    </div>
                                </div>

                                {fileAreas.length > 0 && (
                                    <div style={{
                                        border: '1px solid var(--border)',
                                        borderRadius: 'var(--radius)',
                                        background: 'var(--surface)',
                                        padding: '1rem',
                                    }}>
                                        <h3 style={{ margin: '0 0 0.75rem', fontSize: '0.95rem' }}>Changed Areas</h3>
                                        <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
                                            {fileAreas.map(([area, count]) => (
                                                <span key={area} style={{
                                                    padding: '0.35rem 0.55rem',
                                                    borderRadius: '999px',
                                                    background: 'var(--background)',
                                                    border: '1px solid var(--border)',
                                                    fontSize: '0.8rem',
                                                    color: 'var(--text-secondary)',
                                                }}>
                                                    {area.replaceAll('_', ' ')} · {count}
                                                </span>
                                            ))}
                                        </div>
                                    </div>
                                )}

                                <div style={{
                                    display: 'grid',
                                    gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 1.2fr)',
                                    gap: '1rem',
                                }}>
                                    <div style={{
                                        border: '1px solid var(--border)',
                                        borderRadius: 'var(--radius)',
                                        background: 'var(--surface)',
                                        overflow: 'hidden',
                                    }}>
                                        <div style={{ padding: '0.85rem 1rem', borderBottom: '1px solid var(--border)', fontWeight: 750 }}>
                                            Changed Files
                                        </div>
                                        <div style={{ maxHeight: '440px', overflow: 'auto' }}>
                                            {(selected.changed_files || []).map(file => (
                                                <div key={file.path} style={{ padding: '0.8rem 1rem', borderBottom: '1px solid var(--border)' }}>
                                                    <div style={{ display: 'flex', justifyContent: 'space-between', gap: '0.75rem' }}>
                                                        <code style={{ fontSize: '0.78rem', wordBreak: 'break-word' }}>{file.path}</code>
                                                        <StatusBadge label="" value={file.risk_level} />
                                                    </div>
                                                    <div style={{ marginTop: '0.35rem', color: 'var(--text-secondary)', fontSize: '0.75rem' }}>
                                                        {file.area.replaceAll('_', ' ')} · +{file.additions} -{file.deletions}
                                                    </div>
                                                </div>
                                            ))}
                                        </div>
                                    </div>

                                    <div style={{
                                        border: '1px solid var(--border)',
                                        borderRadius: 'var(--radius)',
                                        background: 'var(--surface)',
                                        overflow: 'hidden',
                                    }}>
                                        <div style={{ padding: '0.85rem 1rem', borderBottom: '1px solid var(--border)', fontWeight: 750 }}>
                                            Recommended Tests
                                        </div>
                                        <div style={{ maxHeight: '440px', overflow: 'auto' }}>
                                            {(selected.selected_tests || []).map(test => (
                                                <div key={test.spec_name} style={{ padding: '0.9rem 1rem', borderBottom: '1px solid var(--border)' }}>
                                                    <div style={{ display: 'flex', justifyContent: 'space-between', gap: '0.75rem', alignItems: 'flex-start' }}>
                                                        <div style={{ minWidth: 0 }}>
                                                            <div style={{ fontWeight: 750, fontSize: '0.9rem', wordBreak: 'break-word' }}>{test.spec_name}</div>
                                                            {test.test_path && (
                                                                <code style={{ display: 'block', marginTop: '0.25rem', color: 'var(--text-secondary)', fontSize: '0.74rem', wordBreak: 'break-word' }}>
                                                                    {test.test_path}
                                                                </code>
                                                            )}
                                                        </div>
                                                        <StatusBadge label="Conf" value={test.confidence} />
                                                    </div>
                                                    <div style={{ marginTop: '0.5rem', color: 'var(--text-secondary)', fontSize: '0.8rem', lineHeight: 1.45 }}>
                                                        {test.reason}
                                                    </div>
                                                </div>
                                            ))}
                                        </div>
                                    </div>
                                </div>
                            </section>
                        )}
                    </div>

                    <style jsx>{`
                        @keyframes spin {
                            from { transform: rotate(0deg); }
                            to { transform: rotate(360deg); }
                        }
                        .spin {
                            animation: spin 1s linear infinite;
                        }
                        @media (max-width: 980px) {
                            section {
                                min-width: 0;
                            }
                            div[style*="grid-template-columns: minmax(260px, 360px)"] {
                                grid-template-columns: 1fr !important;
                            }
                            div[style*="grid-template-columns: repeat(4"] {
                                grid-template-columns: repeat(2, minmax(120px, 1fr)) !important;
                            }
                            div[style*="grid-template-columns: minmax(0, 1fr) minmax(0, 1.2fr)"] {
                                grid-template-columns: 1fr !important;
                            }
                        }
                    `}</style>
                </>
            )}
        </PageLayout>
    );
}
