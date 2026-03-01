'use client';
import React, { useState, useEffect, useCallback } from 'react';
import dynamic from 'next/dynamic';
import {
    Activity, Search, Plus, X, Play, Loader2, ChevronDown, ChevronRight,
    RefreshCw, Trash2, Edit2, Save, BarChart3, TrendingUp, ArrowLeft,
} from 'lucide-react';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { vscDarkPlus } from 'react-syntax-highlighter/dist/esm/styles/prism';
import type { LoadSpec, LoadTestRun, K6ExecutionStatus, SystemLimits, TrendData } from './types';
import { LOAD_SPEC_TEMPLATE } from './types';
import { SCENARIO_TEMPLATES, type ScenarioTemplate } from './ScenarioTemplates';
import MiniSparkline from './MiniSparkline';
import { getResponseTimeColor, getErrorRateColor } from '@/lib/colors';

const CodeEditor = dynamic(() => import('@/components/CodeEditor'), { ssr: false });

interface ScenariosTabProps {
    specs: LoadSpec[];
    specsLoading: boolean;
    k6Status: K6ExecutionStatus | null;
    systemLimits: SystemLimits | null;
    onFetchSpecs: () => void;
    onCreateSpec: (name: string, content: string) => Promise<void>;
    onUpdateSpec: (name: string, content: string) => Promise<void>;
    onDeleteSpec: (name: string) => Promise<void>;
    onGenerateScript: (name: string) => Promise<void>;
    onRunFromSpec: (name: string, vus?: string, duration?: string) => Promise<void>;
    onLoadSpecContent: (name: string) => Promise<void>;
    specContents: Record<string, string>;
    latestRunsBySpec?: Record<string, LoadTestRun>;
    projectId?: string;
}

export default function ScenariosTab({
    specs,
    specsLoading,
    k6Status,
    systemLimits,
    onFetchSpecs,
    onCreateSpec,
    onUpdateSpec,
    onDeleteSpec,
    onGenerateScript,
    onRunFromSpec,
    onLoadSpecContent,
    specContents,
    latestRunsBySpec,
    projectId,
}: ScenariosTabProps) {
    const [specsSearch, setSpecsSearch] = useState('');
    const [showCreateModal, setShowCreateModal] = useState(false);
    const [newSpecName, setNewSpecName] = useState('');
    const [newSpecContent, setNewSpecContent] = useState(LOAD_SPEC_TEMPLATE);
    const [creating, setCreating] = useState(false);
    const [expandedSpec, setExpandedSpec] = useState<string | null>(null);
    const [editingSpec, setEditingSpec] = useState<string | null>(null);
    const [editContent, setEditContent] = useState('');
    const [specRunVUs, setSpecRunVUs] = useState('');
    const [specRunDuration, setSpecRunDuration] = useState('');
    const [templateStep, setTemplateStep] = useState<'pick' | 'edit'>('pick');
    const [trendsBySpec, setTrendsBySpec] = useState<Record<string, number[]>>({});
    const [showTrendSpec, setShowTrendSpec] = useState<string | null>(null);

    const filteredSpecs = specs.filter(s =>
        s.name.toLowerCase().includes(specsSearch.toLowerCase())
    );

    // Fetch trend data for all specs
    const fetchTrends = useCallback(async () => {
        if (specs.length === 0) return;
        try {
            const results = await Promise.all(
                specs.map(async (spec) => {
                    try {
                        const params = new URLSearchParams({ spec_name: spec.name, limit: '10' });
                        if (projectId) params.set('project_id', projectId);
                        const res = await fetch(`/api/load-testing/runs/trends?${params}`);
                        if (!res.ok) return { name: spec.name, p95s: [] as number[] };
                        const data: TrendData[] = await res.json();
                        const p95s = data
                            .filter((d) => d.p95_response_time_ms != null)
                            .map((d) => d.p95_response_time_ms as number);
                        return { name: spec.name, p95s };
                    } catch {
                        return { name: spec.name, p95s: [] as number[] };
                    }
                })
            );
            const map: Record<string, number[]> = {};
            for (const r of results) {
                map[r.name] = r.p95s;
            }
            setTrendsBySpec(map);
        } catch {
            // silently fail
        }
    }, [specs, projectId]);

    useEffect(() => {
        fetchTrends();
    }, [fetchTrends]);

    const handleCreate = async () => {
        if (!newSpecName.trim()) return;
        setCreating(true);
        try {
            await onCreateSpec(newSpecName, newSpecContent);
            setShowCreateModal(false);
            setNewSpecName('');
            setNewSpecContent(LOAD_SPEC_TEMPLATE);
            setTemplateStep('pick');
        } catch {
            // error handled by parent
        } finally {
            setCreating(false);
        }
    };

    const handleSave = async (name: string) => {
        await onUpdateSpec(name, editContent);
        setEditingSpec(null);
    };

    const handleOpenCreateModal = () => {
        setTemplateStep('pick');
        setNewSpecName('');
        setNewSpecContent(LOAD_SPEC_TEMPLATE);
        setShowCreateModal(true);
    };

    const handleSelectTemplate = (template: ScenarioTemplate) => {
        setNewSpecContent(template.content);
        setTemplateStep('edit');
    };

    const handleStartFromScratch = () => {
        setNewSpecContent(LOAD_SPEC_TEMPLATE);
        setTemplateStep('edit');
    };

    const getStatusDot = (run?: LoadTestRun) => {
        if (!run) return { color: 'var(--text-tertiary)', title: 'No runs yet' };
        if (run.status === 'failed') return { color: 'var(--danger)', title: 'Last run failed' };
        if (run.status === 'completed' && run.thresholds_passed) return { color: 'var(--success)', title: 'Passed' };
        if (run.status === 'completed' && run.thresholds_passed === false) return { color: 'var(--warning)', title: 'Thresholds failed' };
        if (run.status === 'running') return { color: 'var(--primary)', title: 'Running' };
        return { color: 'var(--text-tertiary)', title: run.status };
    };

    return (
        <div>
            <div style={{ display: 'flex', gap: '0.75rem', marginBottom: '1rem', alignItems: 'center' }}>
                <button
                    onClick={handleOpenCreateModal}
                    style={{
                        display: 'flex', alignItems: 'center', gap: '0.5rem',
                        padding: '0.5rem 1rem', background: 'var(--primary)', color: 'white',
                        border: 'none', borderRadius: 'var(--radius)', cursor: 'pointer',
                        fontWeight: 500, fontSize: '0.875rem',
                    }}
                >
                    <Plus size={16} /> Create Scenario
                </button>
                <div style={{ position: 'relative', flex: 1, maxWidth: '300px' }}>
                    <Search size={16} style={{ position: 'absolute', left: '0.75rem', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-secondary)' }} />
                    <input
                        type="text"
                        placeholder="Search scenarios..."
                        value={specsSearch}
                        onChange={e => setSpecsSearch(e.target.value)}
                        style={{
                            width: '100%', padding: '0.5rem 0.5rem 0.5rem 2.25rem',
                            background: 'var(--surface)', border: '1px solid var(--border)',
                            borderRadius: 'var(--radius)', color: 'var(--text-primary)', fontSize: '0.875rem',
                        }}
                    />
                </div>
                <button
                    onClick={() => onFetchSpecs()}
                    style={{
                        display: 'flex', alignItems: 'center', gap: '0.5rem',
                        padding: '0.5rem 0.75rem', background: 'var(--surface)',
                        border: '1px solid var(--border)', borderRadius: 'var(--radius)',
                        cursor: 'pointer', color: 'var(--text-secondary)', fontSize: '0.875rem',
                    }}
                >
                    <RefreshCw size={14} /> Refresh
                </button>
            </div>

            {specsLoading ? (
                <div style={{ textAlign: 'center', padding: '3rem', color: 'var(--text-secondary)' }}>
                    <Loader2 size={24} style={{ animation: 'spin 1s linear infinite', margin: '0 auto 0.5rem' }} />
                    <p>Loading scenarios...</p>
                </div>
            ) : filteredSpecs.length === 0 ? (
                <div style={{
                    textAlign: 'center', padding: '3rem',
                    background: 'var(--surface)', borderRadius: 'var(--radius)',
                    border: '1px solid var(--border)',
                }}>
                    <Activity size={40} style={{ color: 'var(--text-secondary)', margin: '0 auto 1rem' }} />
                    <p style={{ color: 'var(--text-secondary)', marginBottom: '1rem' }}>No load test scenarios found</p>
                    <button
                        onClick={handleOpenCreateModal}
                        style={{
                            padding: '0.5rem 1rem', background: 'var(--primary)', color: 'white',
                            border: 'none', borderRadius: 'var(--radius)', cursor: 'pointer',
                        }}
                    >
                        Create your first scenario
                    </button>
                </div>
            ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                    {filteredSpecs.map(spec => {
                        const isExpanded = expandedSpec === spec.name;
                        const isEditing = editingSpec === spec.name;
                        const latestRun = latestRunsBySpec?.[spec.name];
                        const statusDot = getStatusDot(latestRun);
                        const sparklineData = trendsBySpec[spec.name] || [];
                        const errorRate = latestRun?.total_requests && latestRun.total_requests > 0
                            ? ((latestRun.failed_requests || 0) / latestRun.total_requests) * 100
                            : null;

                        return (
                            <div key={spec.name} style={{
                                background: 'var(--surface)', border: '1px solid var(--border)',
                                borderRadius: 'var(--radius)', overflow: 'hidden',
                            }}>
                                <div
                                    style={{
                                        display: 'flex', alignItems: 'center', padding: '0.75rem 1rem',
                                        gap: '0.75rem', cursor: 'pointer',
                                    }}
                                    onClick={() => {
                                        if (isExpanded) {
                                            setExpandedSpec(null);
                                            setEditingSpec(null);
                                        } else {
                                            setExpandedSpec(spec.name);
                                            setSpecRunVUs('');
                                            setSpecRunDuration('');
                                            onLoadSpecContent(spec.name);
                                        }
                                    }}
                                >
                                    {isExpanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                                    <Activity size={16} style={{ color: 'var(--primary)' }} />
                                    <span style={{ fontWeight: 500, fontSize: '0.875rem' }}>{spec.name}</span>

                                    {/* Inline stats from latest run */}
                                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flex: 1, marginLeft: '0.25rem' }}>
                                        <span
                                            title={statusDot.title}
                                            style={{
                                                width: 8, height: 8, borderRadius: '50%',
                                                background: statusDot.color, flexShrink: 0,
                                            }}
                                        />
                                        {latestRun?.p95_response_time_ms != null && (
                                            <span style={{
                                                fontSize: '0.7rem', fontWeight: 500,
                                                color: getResponseTimeColor(latestRun.p95_response_time_ms),
                                            }}>
                                                P95: {Math.round(latestRun.p95_response_time_ms)}ms
                                            </span>
                                        )}
                                        {latestRun?.requests_per_second != null && (
                                            <span style={{ fontSize: '0.7rem', color: 'var(--text-secondary)' }}>
                                                {latestRun.requests_per_second.toFixed(1)} rps
                                            </span>
                                        )}
                                        {errorRate != null && (
                                            <span style={{
                                                fontSize: '0.7rem', fontWeight: 500,
                                                color: getErrorRateColor(errorRate),
                                            }}>
                                                {errorRate.toFixed(1)}% err
                                            </span>
                                        )}
                                        {sparklineData.length > 1 && (
                                            <MiniSparkline
                                                data={sparklineData}
                                                width={64}
                                                height={20}
                                                color={latestRun?.p95_response_time_ms != null
                                                    ? getResponseTimeColor(latestRun.p95_response_time_ms)
                                                    : 'var(--primary)'}
                                            />
                                        )}
                                    </div>

                                    <div style={{ display: 'flex', gap: '0.25rem' }} onClick={e => e.stopPropagation()}>
                                        <button
                                            onClick={() => setShowTrendSpec(showTrendSpec === spec.name ? null : spec.name)}
                                            title="View trends"
                                            style={{
                                                display: 'flex', alignItems: 'center', gap: '0.25rem',
                                                padding: '0.3rem 0.6rem', background: 'var(--success-muted)',
                                                color: 'var(--success)', border: '1px solid rgba(16, 185, 129, 0.2)',
                                                borderRadius: 'var(--radius)', cursor: 'pointer', fontSize: '0.75rem',
                                            }}
                                        >
                                            <TrendingUp size={12} /> Trends
                                        </button>
                                        <button
                                            onClick={() => onRunFromSpec(spec.name)}
                                            disabled={!!k6Status?.load_test_active}
                                            title={k6Status?.load_test_active ? 'Load test in progress' : ''}
                                            style={{
                                                display: 'flex', alignItems: 'center', gap: '0.25rem',
                                                padding: '0.3rem 0.6rem', background: 'var(--primary-glow)',
                                                color: 'var(--primary)', border: '1px solid rgba(59, 130, 246, 0.2)',
                                                borderRadius: 'var(--radius)', cursor: 'pointer', fontSize: '0.75rem',
                                                opacity: k6Status?.load_test_active ? 0.5 : 1,
                                            }}
                                        >
                                            <Play size={12} /> Run
                                        </button>
                                        <button
                                            onClick={() => onGenerateScript(spec.name)}
                                            style={{
                                                display: 'flex', alignItems: 'center', gap: '0.25rem',
                                                padding: '0.3rem 0.6rem', background: 'rgba(192, 132, 252, 0.12)',
                                                color: 'var(--accent)', border: '1px solid rgba(139, 92, 246, 0.2)',
                                                borderRadius: 'var(--radius)', cursor: 'pointer', fontSize: '0.75rem',
                                            }}
                                        >
                                            <BarChart3 size={12} /> Generate Script
                                        </button>
                                        <button
                                            onClick={() => onDeleteSpec(spec.name)}
                                            style={{
                                                display: 'flex', alignItems: 'center', gap: '0.25rem',
                                                padding: '0.3rem 0.6rem', background: 'var(--danger-muted)',
                                                color: 'var(--danger)', border: '1px solid rgba(239, 68, 68, 0.2)',
                                                borderRadius: 'var(--radius)', cursor: 'pointer', fontSize: '0.75rem',
                                            }}
                                        >
                                            <Trash2 size={12} />
                                        </button>
                                    </div>
                                </div>

                                {/* Trend mini-view */}
                                {showTrendSpec === spec.name && sparklineData.length > 0 && (
                                    <div style={{
                                        borderTop: '1px solid var(--border)', padding: '0.75rem 1rem',
                                        background: 'var(--background)',
                                    }}>
                                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.5rem' }}>
                                            <TrendingUp size={14} style={{ color: 'var(--text-secondary)' }} />
                                            <span style={{ fontSize: '0.75rem', fontWeight: 500, color: 'var(--text-secondary)' }}>
                                                P95 Response Time Trend (last {sparklineData.length} runs)
                                            </span>
                                        </div>
                                        <MiniSparkline
                                            data={sparklineData}
                                            width={400}
                                            height={48}
                                            color="var(--primary)"
                                            strokeWidth={2}
                                        />
                                        <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: '0.25rem' }}>
                                            <span style={{ fontSize: '0.65rem', color: 'var(--text-secondary)' }}>
                                                Min: {Math.round(Math.min(...sparklineData))}ms
                                            </span>
                                            <span style={{ fontSize: '0.65rem', color: 'var(--text-secondary)' }}>
                                                Max: {Math.round(Math.max(...sparklineData))}ms
                                            </span>
                                        </div>
                                    </div>
                                )}

                                {isExpanded && (
                                    <div style={{ borderTop: '1px solid var(--border)', padding: '1rem' }}>
                                        {/* VU/Duration overrides */}
                                        <div style={{ display: 'flex', gap: '0.75rem', marginBottom: '0.75rem', alignItems: 'flex-start' }}>
                                            <div>
                                                <label style={{ fontSize: '0.7rem', color: 'var(--text-secondary)' }}>VUs Override</label>
                                                <input
                                                    type="number"
                                                    placeholder={systemLimits ? `Max: ${systemLimits.effective_max_vus.toLocaleString()}` : 'e.g., 10'}
                                                    value={specRunVUs}
                                                    onChange={e => setSpecRunVUs(e.target.value)}
                                                    style={{
                                                        display: 'block', width: '130px', padding: '0.3rem 0.5rem',
                                                        background: 'var(--background)',
                                                        border: `1px solid ${
                                                            specRunVUs && systemLimits
                                                                ? parseInt(specRunVUs) > systemLimits.effective_max_vus
                                                                    ? 'var(--danger)'
                                                                    : parseInt(specRunVUs) > systemLimits.effective_max_vus * 0.8
                                                                        ? 'var(--warning)'
                                                                        : 'var(--border)'
                                                                : 'var(--border)'
                                                        }`,
                                                        borderRadius: 'var(--radius)', color: 'var(--text-primary)', fontSize: '0.8rem',
                                                    }}
                                                />
                                                {systemLimits && specRunVUs && parseInt(specRunVUs) > systemLimits.effective_max_vus && (
                                                    <div style={{ fontSize: '0.65rem', color: 'var(--danger)', marginTop: '0.2rem' }}>
                                                        Exceeds max ({systemLimits.effective_max_vus.toLocaleString()} VUs) — will be capped
                                                    </div>
                                                )}
                                                {systemLimits && specRunVUs && parseInt(specRunVUs) > systemLimits.effective_max_vus * 0.8 && parseInt(specRunVUs) <= systemLimits.effective_max_vus && (
                                                    <div style={{ fontSize: '0.65rem', color: 'var(--warning)', marginTop: '0.2rem' }}>
                                                        Approaching limit ({systemLimits.effective_max_vus.toLocaleString()} max)
                                                    </div>
                                                )}
                                                {systemLimits && !specRunVUs && (
                                                    <div style={{ fontSize: '0.65rem', color: 'var(--text-secondary)', marginTop: '0.2rem' }}>
                                                        Up to {systemLimits.effective_max_vus.toLocaleString()} VUs{systemLimits.execution_mode === 'distributed' ? ` (${systemLimits.k6_max_vus.toLocaleString()}/worker)` : ''}
                                                    </div>
                                                )}
                                            </div>
                                            <div>
                                                <label style={{ fontSize: '0.7rem', color: 'var(--text-secondary)' }}>Duration Override</label>
                                                <input
                                                    type="text"
                                                    placeholder={systemLimits ? `Max: ${systemLimits.k6_max_duration}` : 'e.g., 30s'}
                                                    value={specRunDuration}
                                                    onChange={e => setSpecRunDuration(e.target.value)}
                                                    style={{
                                                        display: 'block', width: '130px', padding: '0.3rem 0.5rem',
                                                        background: 'var(--background)', border: '1px solid var(--border)',
                                                        borderRadius: 'var(--radius)', color: 'var(--text-primary)', fontSize: '0.8rem',
                                                    }}
                                                />
                                                {systemLimits && !specRunDuration && (
                                                    <div style={{ fontSize: '0.65rem', color: 'var(--text-secondary)', marginTop: '0.2rem' }}>
                                                        Max: {systemLimits.k6_max_duration}
                                                    </div>
                                                )}
                                            </div>
                                            <button
                                                onClick={() => onRunFromSpec(spec.name, specRunVUs, specRunDuration)}
                                                disabled={!!k6Status?.load_test_active || (!specRunVUs && !specRunDuration)}
                                                title={k6Status?.load_test_active ? 'Load test in progress' : (!specRunVUs && !specRunDuration) ? 'Enter VUs or Duration to override' : ''}
                                                style={{
                                                    display: 'flex', alignItems: 'center', gap: '0.25rem',
                                                    padding: '0.4rem 0.8rem', background: 'var(--primary)', color: 'white',
                                                    border: 'none', borderRadius: 'var(--radius)', cursor: 'pointer',
                                                    fontSize: '0.8rem', marginTop: '1rem',
                                                    opacity: (k6Status?.load_test_active || (!specRunVUs && !specRunDuration)) ? 0.5 : 1,
                                                }}
                                            >
                                                <Play size={14} /> Run with Overrides
                                            </button>
                                        </div>

                                        {isEditing ? (
                                            <div>
                                                <div style={{ height: '400px', border: '1px solid var(--border)', borderRadius: 'var(--radius)', overflow: 'hidden' }}>
                                                    <CodeEditor
                                                        value={editContent}
                                                        onChange={setEditContent}
                                                        language="markdown"
                                                    />
                                                </div>
                                                <div style={{ display: 'flex', gap: '0.5rem', marginTop: '0.75rem' }}>
                                                    <button
                                                        onClick={() => handleSave(spec.name)}
                                                        style={{
                                                            display: 'flex', alignItems: 'center', gap: '0.3rem',
                                                            padding: '0.4rem 0.8rem', background: 'var(--primary)',
                                                            color: 'white', border: 'none', borderRadius: 'var(--radius)',
                                                            cursor: 'pointer', fontSize: '0.8rem',
                                                        }}
                                                    >
                                                        <Save size={14} /> Save
                                                    </button>
                                                    <button
                                                        onClick={() => setEditingSpec(null)}
                                                        style={{
                                                            padding: '0.4rem 0.8rem', background: 'var(--surface)',
                                                            color: 'var(--text-secondary)', border: '1px solid var(--border)',
                                                            borderRadius: 'var(--radius)', cursor: 'pointer', fontSize: '0.8rem',
                                                        }}
                                                    >
                                                        Cancel
                                                    </button>
                                                </div>
                                            </div>
                                        ) : (
                                            <div>
                                                <SyntaxHighlighter
                                                    language="markdown"
                                                    style={vscDarkPlus}
                                                    customStyle={{ margin: 0, padding: '1rem', fontSize: '0.8rem', borderRadius: 'var(--radius)', maxHeight: '400px' }}
                                                    showLineNumbers={true}
                                                    wrapLines={true}
                                                >
                                                    {specContents[spec.name] || 'Loading...'}
                                                </SyntaxHighlighter>
                                                <button
                                                    onClick={() => {
                                                        setEditingSpec(spec.name);
                                                        setEditContent(specContents[spec.name] || '');
                                                    }}
                                                    style={{
                                                        display: 'flex', alignItems: 'center', gap: '0.3rem',
                                                        marginTop: '0.75rem', padding: '0.4rem 0.8rem',
                                                        background: 'var(--surface)', color: 'var(--text-secondary)',
                                                        border: '1px solid var(--border)', borderRadius: 'var(--radius)',
                                                        cursor: 'pointer', fontSize: '0.8rem',
                                                    }}
                                                >
                                                    <Edit2 size={14} /> Edit Spec
                                                </button>
                                            </div>
                                        )}
                                    </div>
                                )}
                            </div>
                        );
                    })}
                </div>
            )}

            {/* Create Modal */}
            {showCreateModal && (
                <div style={{
                    position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
                    background: 'rgba(0,0,0,0.5)', display: 'flex', alignItems: 'center',
                    justifyContent: 'center', zIndex: 1000,
                }}>
                    <div style={{
                        background: 'var(--surface)', border: '1px solid var(--border)',
                        borderRadius: 'var(--radius)', padding: '1.5rem', width: '700px',
                        maxHeight: '80vh', overflow: 'auto',
                    }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
                            <h3 style={{ fontSize: '1rem', fontWeight: 600 }}>Create Load Test Scenario</h3>
                            <button onClick={() => setShowCreateModal(false)} style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-secondary)' }}>
                                <X size={20} />
                            </button>
                        </div>

                        {templateStep === 'pick' ? (
                            <div>
                                <p style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '1rem' }}>
                                    Choose a template to get started quickly, or start from scratch.
                                </p>
                                <div style={{
                                    display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem',
                                    marginBottom: '1rem',
                                }}>
                                    {SCENARIO_TEMPLATES.map(template => (
                                        <div
                                            key={template.name}
                                            onClick={() => handleSelectTemplate(template)}
                                            style={{
                                                padding: '1rem', background: 'var(--background)',
                                                border: '1px solid var(--border)', borderRadius: 'var(--radius)',
                                                cursor: 'pointer', transition: 'border-color 0.15s',
                                            }}
                                            onMouseEnter={e => (e.currentTarget.style.borderColor = 'var(--primary)')}
                                            onMouseLeave={e => (e.currentTarget.style.borderColor = 'var(--border)')}
                                        >
                                            <div style={{ fontWeight: 600, fontSize: '0.85rem', marginBottom: '0.35rem' }}>
                                                {template.name}
                                            </div>
                                            <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', marginBottom: '0.5rem', lineHeight: 1.4 }}>
                                                {template.description}
                                            </div>
                                            <div style={{ display: 'flex', gap: '0.5rem' }}>
                                                <span style={{
                                                    fontSize: '0.65rem', padding: '0.15rem 0.4rem',
                                                    background: 'var(--primary-glow)', color: 'var(--primary)',
                                                    borderRadius: '4px', fontWeight: 500,
                                                }}>
                                                    {template.vus} VUs
                                                </span>
                                                <span style={{
                                                    fontSize: '0.65rem', padding: '0.15rem 0.4rem',
                                                    background: 'rgba(192, 132, 252, 0.12)', color: 'var(--accent)',
                                                    borderRadius: '4px', fontWeight: 500,
                                                }}>
                                                    {template.duration}
                                                </span>
                                            </div>
                                        </div>
                                    ))}
                                </div>
                                <div style={{ textAlign: 'center' }}>
                                    <button
                                        onClick={handleStartFromScratch}
                                        style={{
                                            background: 'none', border: 'none', cursor: 'pointer',
                                            color: 'var(--primary)', fontSize: '0.8rem', textDecoration: 'underline',
                                        }}
                                    >
                                        Start from scratch
                                    </button>
                                </div>
                            </div>
                        ) : (
                            <div>
                                <button
                                    onClick={() => setTemplateStep('pick')}
                                    style={{
                                        display: 'flex', alignItems: 'center', gap: '0.3rem',
                                        background: 'none', border: 'none', cursor: 'pointer',
                                        color: 'var(--text-secondary)', fontSize: '0.8rem',
                                        marginBottom: '0.75rem', padding: 0,
                                    }}
                                >
                                    <ArrowLeft size={14} /> Back to templates
                                </button>
                                <div style={{ marginBottom: '1rem' }}>
                                    <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 500, marginBottom: '0.4rem', color: 'var(--text-secondary)' }}>
                                        Scenario Name
                                    </label>
                                    <input
                                        type="text"
                                        placeholder="e.g., homepage-load-test"
                                        value={newSpecName}
                                        onChange={e => setNewSpecName(e.target.value)}
                                        style={{
                                            width: '100%', padding: '0.6rem 0.75rem',
                                            background: 'var(--background)', border: '1px solid var(--border)',
                                            borderRadius: 'var(--radius)', color: 'var(--text-primary)', fontSize: '0.875rem',
                                        }}
                                    />
                                </div>
                                <div style={{ marginBottom: '1rem' }}>
                                    <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 500, marginBottom: '0.4rem', color: 'var(--text-secondary)' }}>
                                        Scenario Definition
                                    </label>
                                    <div style={{ height: '350px', border: '1px solid var(--border)', borderRadius: 'var(--radius)', overflow: 'hidden' }}>
                                        <CodeEditor
                                            value={newSpecContent}
                                            onChange={setNewSpecContent}
                                            language="markdown"
                                        />
                                    </div>
                                </div>
                                <div style={{ display: 'flex', gap: '0.5rem', justifyContent: 'flex-end' }}>
                                    <button
                                        onClick={() => setShowCreateModal(false)}
                                        style={{
                                            padding: '0.5rem 1rem', background: 'var(--surface)',
                                            color: 'var(--text-secondary)', border: '1px solid var(--border)',
                                            borderRadius: 'var(--radius)', cursor: 'pointer', fontSize: '0.875rem',
                                        }}
                                    >
                                        Cancel
                                    </button>
                                    <button
                                        onClick={handleCreate}
                                        disabled={!newSpecName.trim() || creating}
                                        style={{
                                            display: 'flex', alignItems: 'center', gap: '0.5rem',
                                            padding: '0.5rem 1rem', background: 'var(--primary)', color: 'white',
                                            border: 'none', borderRadius: 'var(--radius)', cursor: 'pointer',
                                            fontWeight: 500, fontSize: '0.875rem',
                                            opacity: (!newSpecName.trim() || creating) ? 0.5 : 1,
                                        }}
                                    >
                                        {creating && <Loader2 size={14} style={{ animation: 'spin 1s linear infinite' }} />}
                                        Create Scenario
                                    </button>
                                </div>
                            </div>
                        )}
                    </div>
                </div>
            )}
        </div>
    );
}
