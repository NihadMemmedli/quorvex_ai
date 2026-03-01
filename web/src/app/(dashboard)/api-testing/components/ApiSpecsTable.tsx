'use client';
import React, { useState, useCallback, useRef, useEffect } from 'react';
import dynamic from 'next/dynamic';
import {
    ChevronDown, ChevronRight, Play, Loader2, MoreVertical,
    CheckCircle, XCircle, Circle, Zap, Activity, Shield, Edit2,
    Save, X, FileCode, Trash2, Copy, Terminal,
    AlertCircle, Heart,
} from 'lucide-react';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { vscDarkPlus } from 'react-syntax-highlighter/dist/esm/styles/prism';
import { API_BASE } from '@/lib/api';
import { ApiSpec, JobStatus, ApiTestRun } from './types';

const CodeEditor = dynamic(() => import('@/components/CodeEditor'), { ssr: false });
const ApiSpecBuilder = dynamic(() => import('@/components/ApiSpecBuilder'), { ssr: false });

// ========== Helpers ==========

function relativeTime(dateStr?: string | null): string {
    if (!dateStr) return '\u2014';
    const diff = Date.now() - new Date(dateStr).getTime();
    const mins = Math.floor(diff / 60000);
    if (mins < 1) return 'just now';
    if (mins < 60) return `${mins}m ago`;
    const hours = Math.floor(mins / 60);
    if (hours < 24) return `${hours}h ago`;
    const days = Math.floor(hours / 24);
    return `${days}d ago`;
}

function StatusDot({ status }: { status: 'passed' | 'failed' | 'running' | null }) {
    if (status === 'running') return <Loader2 size={14} style={{ color: 'var(--warning)', animation: 'spin 1s linear infinite' }} />;
    if (status === 'passed') return <CheckCircle size={14} style={{ color: 'var(--success)' }} />;
    if (status === 'failed') return <XCircle size={14} style={{ color: 'var(--danger)' }} />;
    return <Circle size={14} style={{ color: 'var(--text-secondary)', opacity: 0.4 }} />;
}

// ========== Log Viewer ==========

function LogViewer({ jobId, isRunning }: { jobId: string; isRunning: boolean }) {
    const [logs, setLogs] = useState('');
    const [lineCount, setLineCount] = useState(0);
    const [expanded, setExpanded] = useState(true);
    const logRef = useRef<HTMLPreElement>(null);
    const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

    const fetchLogs = useCallback(async () => {
        try {
            const res = await fetch(`${API_BASE}/api-testing/jobs/${jobId}/logs?tail=200`);
            if (res.ok) {
                const data = await res.json();
                setLogs(data.logs || '');
                setLineCount(data.line_count || 0);
            }
        } catch { /* ignore */ }
    }, [jobId]);

    useEffect(() => {
        fetchLogs();
        if (isRunning) {
            intervalRef.current = setInterval(fetchLogs, 3000);
        }
        return () => { if (intervalRef.current) clearInterval(intervalRef.current); };
    }, [fetchLogs, isRunning]);

    useEffect(() => {
        if (logRef.current && expanded) {
            logRef.current.scrollTop = logRef.current.scrollHeight;
        }
    }, [logs, expanded]);

    if (!logs && !isRunning) return null;

    return (
        <div style={{ marginTop: '0.75rem' }}>
            <button
                onClick={() => setExpanded(!expanded)}
                style={{
                    display: 'flex', alignItems: 'center', gap: '0.4rem',
                    padding: '0.3rem 0.6rem', background: 'rgba(0,0,0,0.2)',
                    border: '1px solid var(--border)', borderRadius: 'var(--radius)',
                    cursor: 'pointer', color: 'var(--text-secondary)', fontSize: '0.75rem',
                }}
            >
                <Terminal size={12} />
                Logs {lineCount > 0 && `(${lineCount} lines)`}
                {expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
            </button>
            {expanded && (
                <pre
                    ref={logRef}
                    style={{
                        marginTop: '0.5rem', padding: '0.75rem',
                        background: 'var(--background)', color: 'var(--text-secondary)',
                        borderRadius: 'var(--radius)', fontSize: '0.7rem',
                        fontFamily: 'monospace', maxHeight: '300px',
                        overflow: 'auto', whiteSpace: 'pre-wrap',
                        wordBreak: 'break-all', lineHeight: 1.5,
                    }}
                >
                    {logs || (isRunning ? 'Waiting for logs...' : 'No logs available')}
                </pre>
            )}
        </div>
    );
}

// ========== Job Status Panel ==========

function JobStatusPanel({ job }: { job: JobStatus }) {
    const isRunning = job.status === 'running';
    const passed = job.result?.passed;
    const healed = job.result?.healed;
    const attempts = job.result?.healing_attempts || 0;

    const stageLabel = (() => {
        switch (job.stage) {
            case 'queued': return 'Queued';
            case 'starting': return 'Starting pipeline...';
            case 'running': return 'Running (generate + test + heal)...';
            case 'done': return passed ? 'Passed' : 'Failed';
            case 'error': return 'Error';
            default: return job.message || 'Processing...';
        }
    })();

    const borderColor = isRunning ? 'var(--primary)' : passed ? 'var(--success)' : 'var(--danger)';
    const bgColor = isRunning ? 'rgba(59, 130, 246, 0.05)' : passed ? 'rgba(16, 185, 129, 0.05)' : 'rgba(239, 68, 68, 0.05)';

    return (
        <div style={{
            marginTop: '0.75rem', padding: '0.75rem 1rem',
            background: bgColor, border: `1px solid ${borderColor}`,
            borderRadius: 'var(--radius)',
        }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                {isRunning ? (
                    <Loader2 size={16} style={{ color: 'var(--primary)', animation: 'spin 1s linear infinite' }} />
                ) : passed ? (
                    <CheckCircle size={16} style={{ color: 'var(--success)' }} />
                ) : (
                    <AlertCircle size={16} style={{ color: 'var(--danger)' }} />
                )}
                <span style={{ fontSize: '0.8rem', fontWeight: 500, color: borderColor }}>
                    {stageLabel}
                </span>
                <div style={{ display: 'flex', gap: '0.4rem', marginLeft: 'auto' }}>
                    {healed && (
                        <span style={{
                            display: 'flex', alignItems: 'center', gap: '0.25rem',
                            padding: '0.15rem 0.5rem', borderRadius: '999px', fontSize: '0.7rem',
                            fontWeight: 600, background: 'var(--warning-muted)', color: 'var(--warning)',
                        }}>
                            <Heart size={10} /> Healed ({attempts})
                        </span>
                    )}
                    {!isRunning && (
                        <span style={{
                            padding: '0.15rem 0.5rem', borderRadius: '999px', fontSize: '0.7rem',
                            fontWeight: 600,
                            background: passed ? 'var(--success-muted)' : 'var(--danger-muted)',
                            color: passed ? 'var(--success)' : 'var(--danger)',
                        }}>
                            {passed ? 'PASSED' : 'FAILED'}
                        </span>
                    )}
                    {job.result?.run_id && (
                        <span style={{
                            padding: '0.15rem 0.5rem', borderRadius: '999px', fontSize: '0.7rem',
                            background: 'rgba(156, 163, 175, 0.1)', color: 'var(--text-secondary)',
                        }}>
                            {job.result.run_id}
                        </span>
                    )}
                </div>
            </div>
            {job.message && !isRunning && (
                <div style={{ marginTop: '0.4rem', fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
                    {job.message}
                </div>
            )}
            <LogViewer jobId={job.job_id} isRunning={isRunning} />
        </div>
    );
}

// ========== Menu Item Style ==========

const menuItemStyle: React.CSSProperties = {
    display: 'flex', alignItems: 'center', gap: '0.5rem', width: '100%',
    padding: '0.5rem 0.75rem', background: 'none', border: 'none',
    cursor: 'pointer', color: 'var(--text-primary)', fontSize: '0.8rem',
    textAlign: 'left',
};

// ========== Props ==========

interface ApiSpecsTableProps {
    specs: ApiSpec[];
    loading: boolean;
    selectedSpecs: Set<string>;
    onSelectionChange: (selected: Set<string>) => void;
    activeJobs: Record<string, JobStatus>;
    specJobMap: Record<string, string>;
    latestRuns: Record<string, ApiTestRun>;
    projectId: string;
    setMessage: (msg: { type: 'success' | 'error'; text: string } | null) => void;
    setActiveJobs: React.Dispatch<React.SetStateAction<Record<string, JobStatus>>>;
    setSpecJobMap: React.Dispatch<React.SetStateAction<Record<string, string>>>;
    pollJob: (jobId: string, onComplete?: () => void) => void;
    navigateToTest: (testName: string) => void;
    fetchApiSpecs: () => void;
    fetchGeneratedTests: () => void;
    fetchLatestRuns: () => void;
}

// ========== Main Component ==========

export default React.memo(function ApiSpecsTable({
    specs,
    loading,
    selectedSpecs,
    onSelectionChange,
    activeJobs,
    specJobMap,
    latestRuns,
    projectId,
    setMessage,
    setActiveJobs,
    setSpecJobMap,
    pollJob,
    navigateToTest,
    fetchApiSpecs,
    fetchGeneratedTests,
    fetchLatestRuns,
}: ApiSpecsTableProps) {
    const [expandedSpec, setExpandedSpec] = useState<string | null>(null);
    const [specContents, setSpecContents] = useState<Record<string, string>>({});
    const [editingSpec, setEditingSpec] = useState<string | null>(null);
    const [editContent, setEditContent] = useState('');
    const [editMode, setEditMode] = useState<'code' | 'visual'>('visual');
    const [menuOpen, setMenuOpen] = useState<string | null>(null);

    const menuRef = useRef<HTMLDivElement>(null);

    // Close menu on outside click
    useEffect(() => {
        const handler = (e: MouseEvent) => {
            if (menuRef.current && !menuRef.current.contains(e.target as Node)) setMenuOpen(null);
        };
        if (menuOpen) document.addEventListener('mousedown', handler);
        return () => document.removeEventListener('mousedown', handler);
    }, [menuOpen]);

    // Load spec content
    const loadSpecContent = useCallback(async (name: string) => {
        if (specContents[name]) return;
        try {
            const res = await fetch(`${API_BASE}/api-testing/specs/${name}?project_id=${projectId}`);
            if (res.ok) {
                const data = await res.json();
                setSpecContents(prev => ({ ...prev, [name]: data.content }));
            }
        } catch { /* ignore */ }
    }, [specContents, projectId]);

    // Selection helpers
    const toggleSelect = useCallback((path: string) => {
        const next = new Set(selectedSpecs);
        if (next.has(path)) next.delete(path);
        else next.add(path);
        onSelectionChange(next);
    }, [selectedSpecs, onSelectionChange]);

    const toggleSelectAll = useCallback(() => {
        if (selectedSpecs.size === specs.length) {
            onSelectionChange(new Set());
        } else {
            onSelectionChange(new Set(specs.map(s => s.path)));
        }
    }, [specs, selectedSpecs.size, onSelectionChange]);

    // Actions
    const handleGenerateTest = useCallback(async (specName: string) => {
        try {
            const res = await fetch(`${API_BASE}/api-testing/generate`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ spec_name: specName, project_id: projectId }),
            });
            if (res.ok) {
                const data = await res.json();
                setActiveJobs(prev => ({ ...prev, [data.job_id]: { job_id: data.job_id, status: 'running', message: data.message } }));
                pollJob(data.job_id, () => { fetchApiSpecs(); fetchGeneratedTests(); });
            }
        } catch {
            setMessage({ type: 'error', text: 'Failed to start test generation' });
        }
    }, [projectId, setActiveJobs, pollJob, fetchApiSpecs, fetchGeneratedTests, setMessage]);

    const handleRunTest = useCallback(async (specPath: string) => {
        try {
            const res = await fetch(`${API_BASE}/api-testing/run`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ spec_path: specPath, project_id: projectId }),
            });
            if (res.ok) {
                const data = await res.json();
                const job: JobStatus = {
                    job_id: data.job_id,
                    status: data.status === 'failed' ? 'failed' : 'running',
                    stage: data.status === 'failed' ? 'validation' : 'queued',
                    message: data.message,
                };
                setActiveJobs(prev => ({ ...prev, [data.job_id]: job }));
                setSpecJobMap(prev => ({ ...prev, [specPath]: data.job_id }));
                if (data.status === 'failed') {
                    setMessage({ type: 'error', text: data.message });
                } else {
                    pollJob(data.job_id, () => { fetchApiSpecs(); fetchLatestRuns(); fetchGeneratedTests(); });
                }
            }
        } catch {
            setMessage({ type: 'error', text: 'Failed to start API test run' });
        }
    }, [projectId, setActiveJobs, setSpecJobMap, pollJob, fetchApiSpecs, fetchLatestRuns, fetchGeneratedTests, setMessage]);

    const handleEdgeCases = useCallback(async (specPath: string) => {
        try {
            const res = await fetch(`${API_BASE}/api-testing/edge-cases`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ spec_path: specPath, project_id: projectId }),
            });
            if (res.ok) {
                const data = await res.json();
                setActiveJobs(prev => ({ ...prev, [data.job_id]: { job_id: data.job_id, status: 'running', message: data.message } }));
                pollJob(data.job_id, () => { fetchApiSpecs(); fetchGeneratedTests(); });
            }
        } catch {
            setMessage({ type: 'error', text: 'Failed to start edge case generation' });
        }
    }, [projectId, setActiveJobs, pollJob, fetchApiSpecs, fetchGeneratedTests, setMessage]);

    const handleRunDirect = useCallback(async (specName: string, testPath: string, specPath: string) => {
        try {
            const res = await fetch(`${API_BASE}/api-testing/run-direct`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ spec_name: specName, test_path: testPath, project_id: projectId }),
            });
            if (res.ok) {
                const data = await res.json();
                const job: JobStatus = { job_id: data.job_id, status: 'running', stage: 'running', message: 'Running test directly...' };
                setActiveJobs(prev => ({ ...prev, [data.job_id]: job }));
                setSpecJobMap(prev => ({ ...prev, [specPath]: data.job_id }));
                pollJob(data.job_id, () => { fetchApiSpecs(); fetchLatestRuns(); fetchGeneratedTests(); });
            }
        } catch {
            setMessage({ type: 'error', text: 'Failed to start direct test run' });
        }
    }, [projectId, setActiveJobs, setSpecJobMap, pollJob, fetchApiSpecs, fetchLatestRuns, fetchGeneratedTests, setMessage]);

    const handleUpdateSpec = useCallback(async (name: string) => {
        try {
            const res = await fetch(`${API_BASE}/api-testing/specs/${name}?project_id=${projectId}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ content: editContent }),
            });
            if (res.ok) {
                setMessage({ type: 'success', text: 'Spec updated' });
                setEditingSpec(null);
                setSpecContents(prev => ({ ...prev, [name]: editContent }));
            }
        } catch {
            setMessage({ type: 'error', text: 'Failed to update spec' });
        }
    }, [projectId, editContent, setMessage]);

    const handleDeleteSpec = useCallback(async (name: string, path: string) => {
        if (!confirm(`Delete spec "${name}"? This cannot be undone.`)) return;
        try {
            const res = await fetch(`${API_BASE}/api-testing/specs/${name}?project_id=${projectId}`, { method: 'DELETE' });
            if (res.ok) {
                setMessage({ type: 'success', text: `Deleted ${name}` });
                // Remove from selection
                const next = new Set(selectedSpecs);
                next.delete(path);
                onSelectionChange(next);
                fetchApiSpecs();
            } else {
                const err = await res.json();
                setMessage({ type: 'error', text: err.detail || 'Failed to delete' });
            }
        } catch {
            setMessage({ type: 'error', text: 'Failed to delete spec' });
        }
    }, [projectId, selectedSpecs, onSelectionChange, fetchApiSpecs, setMessage]);

    const handleCopyPath = useCallback((spec: ApiSpec) => {
        navigator.clipboard.writeText(spec.path);
        setMessage({ type: 'success', text: 'Path copied to clipboard' });
        setMenuOpen(null);
    }, [setMessage]);

    // Derived state
    const allSelected = specs.length > 0 && selectedSpecs.size === specs.length;

    // Get effective status for a spec
    const getEffectiveStatus = useCallback((spec: ApiSpec): 'passed' | 'failed' | 'running' | null => {
        const runJobId = specJobMap[spec.path];
        const runJob = runJobId ? activeJobs[runJobId] : undefined;
        if (runJob?.status === 'running') return 'running';
        return spec.last_run_status || null;
    }, [specJobMap, activeJobs]);

    // Loading state
    if (loading) {
        return (
            <div style={{ textAlign: 'center', padding: '3rem', color: 'var(--text-secondary)' }}>
                <Loader2 size={24} style={{ animation: 'spin 1s linear infinite', margin: '0 auto 0.5rem' }} />
                <p>Loading API specs...</p>
            </div>
        );
    }

    // Empty state
    if (specs.length === 0) {
        return (
            <div style={{
                textAlign: 'center', padding: '3rem',
                background: 'var(--surface)', borderRadius: 'var(--radius)',
                border: '1px solid var(--border)',
            }}>
                <FileCode size={40} style={{ color: 'var(--text-secondary)', margin: '0 auto 1rem' }} />
                <p style={{ color: 'var(--text-secondary)', marginBottom: '0.5rem' }}>No API specs found</p>
                <p style={{ color: 'var(--text-secondary)', fontSize: '0.8rem' }}>
                    Create an API spec or import from an OpenAPI file
                </p>
            </div>
        );
    }

    return (
        <div style={{ border: '1px solid var(--border)', borderRadius: 'var(--radius)', overflow: 'hidden' }}>
            {/* Table Header */}
            <div style={{
                display: 'grid',
                gridTemplateColumns: '36px 24px 1fr 80px 80px 100px 48px',
                alignItems: 'center',
                padding: '0.6rem 0.75rem',
                background: 'rgba(0,0,0,0.15)',
                borderBottom: '1px solid var(--border)',
                fontSize: '0.75rem',
                fontWeight: 600,
                color: 'var(--text-secondary)',
                textTransform: 'uppercase' as const,
                letterSpacing: '0.03em',
            }}>
                <div>
                    <input
                        type="checkbox"
                        checked={allSelected}
                        onChange={toggleSelectAll}
                        style={{ cursor: 'pointer', accentColor: 'var(--primary)' }}
                    />
                </div>
                <div></div>
                <div>Name</div>
                <div style={{ textAlign: 'center' }}>Tests</div>
                <div style={{ textAlign: 'center' }}>Status</div>
                <div>Last Run</div>
                <div></div>
            </div>

            {/* Table Body */}
            {specs.map(spec => {
                const isExpanded = expandedSpec === spec.name;
                const isEditing = editingSpec === spec.name;
                const isSelected = selectedSpecs.has(spec.path);
                const effectiveStatus = getEffectiveStatus(spec);
                const isRunning = effectiveStatus === 'running';
                const isMenuOpen = menuOpen === spec.name;
                const runJobId = specJobMap[spec.path];
                const runJob = runJobId ? activeJobs[runJobId] : undefined;

                return (
                    <div key={spec.path} style={{ borderBottom: '1px solid var(--border)' }}>
                        {/* Row */}
                        <div
                            style={{
                                display: 'grid',
                                gridTemplateColumns: '36px 24px 1fr 80px 80px 100px 48px',
                                alignItems: 'center',
                                padding: '0.65rem 0.75rem',
                                background: isSelected ? 'rgba(59, 130, 246, 0.05)' : isExpanded ? 'rgba(0,0,0,0.05)' : 'var(--surface)',
                                cursor: 'pointer',
                                transition: 'background 0.1s var(--ease-smooth)',
                            }}
                            onClick={() => {
                                if (isExpanded) {
                                    setExpandedSpec(null);
                                    setEditingSpec(null);
                                } else {
                                    setExpandedSpec(spec.name);
                                    loadSpecContent(spec.name);
                                }
                            }}
                        >
                            {/* Checkbox */}
                            <div onClick={e => e.stopPropagation()}>
                                <input
                                    type="checkbox"
                                    checked={isSelected}
                                    onChange={() => toggleSelect(spec.path)}
                                    style={{ cursor: 'pointer', accentColor: 'var(--primary)' }}
                                />
                            </div>

                            {/* Status dot */}
                            <div><StatusDot status={effectiveStatus} /></div>

                            {/* Name */}
                            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', minWidth: 0 }}>
                                {isExpanded
                                    ? <ChevronDown size={14} style={{ flexShrink: 0 }} />
                                    : <ChevronRight size={14} style={{ flexShrink: 0 }} />}
                                <div style={{ minWidth: 0 }}>
                                    {spec.folder && (
                                        <span style={{ color: 'var(--text-secondary)', fontSize: '0.7rem' }}>
                                            {spec.folder}/
                                        </span>
                                    )}
                                    <span style={{
                                        fontWeight: 500, fontSize: '0.875rem',
                                        overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                                        display: 'block',
                                    }}>
                                        {spec.name}
                                    </span>
                                </div>
                            </div>

                            {/* Test count */}
                            <div style={{ textAlign: 'center' }}>
                                {(spec.test_count ?? 0) > 0 ? (
                                    <span style={{
                                        padding: '0.1rem 0.45rem', borderRadius: '999px', fontSize: '0.7rem',
                                        fontWeight: 600, background: 'var(--primary-glow)', color: 'var(--primary)',
                                    }}>
                                        {spec.test_count}
                                    </span>
                                ) : (
                                    <span style={{ fontSize: '0.7rem', color: 'var(--text-secondary)', opacity: 0.5 }}>{'\u2014'}</span>
                                )}
                            </div>

                            {/* Status badge */}
                            <div style={{ textAlign: 'center' }}>
                                {spec.last_run_status === 'passed' ? (
                                    <span style={{
                                        padding: '0.1rem 0.4rem', borderRadius: '999px', fontSize: '0.65rem',
                                        fontWeight: 600, background: 'var(--success-muted)', color: 'var(--success)',
                                    }}>
                                        PASSED
                                    </span>
                                ) : spec.last_run_status === 'failed' ? (
                                    <span style={{
                                        padding: '0.1rem 0.4rem', borderRadius: '999px', fontSize: '0.65rem',
                                        fontWeight: 600, background: 'var(--danger-muted)', color: 'var(--danger)',
                                    }}>
                                        FAILED
                                    </span>
                                ) : (
                                    <span style={{ fontSize: '0.7rem', color: 'var(--text-secondary)', opacity: 0.5 }}>{'\u2014'}</span>
                                )}
                            </div>

                            {/* Last run */}
                            <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
                                {relativeTime(spec.last_run_at)}
                            </div>

                            {/* Actions menu */}
                            <div style={{ display: 'flex', justifyContent: 'flex-end' }} onClick={e => e.stopPropagation()}>
                                <div style={{ position: 'relative' }} ref={isMenuOpen ? menuRef : undefined}>
                                    <button
                                        onClick={() => setMenuOpen(isMenuOpen ? null : spec.name)}
                                        style={{
                                            display: 'flex', alignItems: 'center', justifyContent: 'center',
                                            width: '28px', height: '28px', borderRadius: 'var(--radius)',
                                            background: 'transparent', border: '1px solid transparent',
                                            cursor: 'pointer', color: 'var(--text-secondary)',
                                        }}
                                    >
                                        <MoreVertical size={14} />
                                    </button>
                                    {isMenuOpen && (
                                        <div style={{
                                            position: 'absolute', right: 0, top: '100%', zIndex: 50,
                                            minWidth: '170px', background: 'var(--surface)',
                                            border: '1px solid var(--border)', borderRadius: 'var(--radius)',
                                            boxShadow: '0 4px 12px rgba(0,0,0,0.3)', overflow: 'hidden',
                                        }}>
                                            {/* Run (if has generated test) */}
                                            {spec.has_generated_test && spec.generated_test_path && (
                                                <button
                                                    onClick={() => { setMenuOpen(null); handleRunDirect(spec.name, spec.generated_test_path!, spec.path); }}
                                                    style={menuItemStyle}
                                                    onMouseEnter={e => (e.currentTarget.style.background = 'rgba(255,255,255,0.05)')}
                                                    onMouseLeave={e => (e.currentTarget.style.background = 'none')}
                                                >
                                                    <Zap size={13} style={{ color: 'var(--success)' }} /> Run
                                                </button>
                                            )}
                                            <button
                                                onClick={() => { setMenuOpen(null); handleGenerateTest(spec.name); }}
                                                style={menuItemStyle}
                                                onMouseEnter={e => (e.currentTarget.style.background = 'rgba(255,255,255,0.05)')}
                                                onMouseLeave={e => (e.currentTarget.style.background = 'none')}
                                            >
                                                <Play size={13} style={{ color: 'var(--accent)' }} /> Generate
                                            </button>
                                            <button
                                                onClick={() => { setMenuOpen(null); handleRunTest(spec.path); }}
                                                style={menuItemStyle}
                                                onMouseEnter={e => (e.currentTarget.style.background = 'rgba(255,255,255,0.05)')}
                                                onMouseLeave={e => (e.currentTarget.style.background = 'none')}
                                            >
                                                <Activity size={13} style={{ color: 'var(--primary)' }} /> Generate & Run
                                            </button>
                                            <button
                                                onClick={() => { setMenuOpen(null); handleEdgeCases(spec.path); }}
                                                style={menuItemStyle}
                                                onMouseEnter={e => (e.currentTarget.style.background = 'rgba(255,255,255,0.05)')}
                                                onMouseLeave={e => (e.currentTarget.style.background = 'none')}
                                            >
                                                <Shield size={13} style={{ color: 'var(--warning)' }} /> Edge Cases
                                            </button>
                                            <div style={{ height: '1px', background: 'var(--border-subtle)' }} />
                                            <button
                                                onClick={() => {
                                                    setMenuOpen(null);
                                                    setExpandedSpec(spec.name);
                                                    loadSpecContent(spec.name);
                                                    setTimeout(() => {
                                                        setEditingSpec(spec.name);
                                                        setEditContent(specContents[spec.name] || '');
                                                        setEditMode('visual');
                                                    }, 100);
                                                }}
                                                style={menuItemStyle}
                                                onMouseEnter={e => (e.currentTarget.style.background = 'rgba(255,255,255,0.05)')}
                                                onMouseLeave={e => (e.currentTarget.style.background = 'none')}
                                            >
                                                <Edit2 size={13} /> Edit
                                            </button>
                                            <button
                                                onClick={() => handleCopyPath(spec)}
                                                style={menuItemStyle}
                                                onMouseEnter={e => (e.currentTarget.style.background = 'rgba(255,255,255,0.05)')}
                                                onMouseLeave={e => (e.currentTarget.style.background = 'none')}
                                            >
                                                <Copy size={13} /> Copy Path
                                            </button>
                                            <div style={{ height: '1px', background: 'var(--border-subtle)' }} />
                                            <button
                                                onClick={() => { setMenuOpen(null); handleDeleteSpec(spec.name, spec.path); }}
                                                style={{ ...menuItemStyle, color: 'var(--danger)' }}
                                                onMouseEnter={e => (e.currentTarget.style.background = 'rgba(239, 68, 68, 0.05)')}
                                                onMouseLeave={e => (e.currentTarget.style.background = 'none')}
                                            >
                                                <Trash2 size={13} /> Delete
                                            </button>
                                        </div>
                                    )}
                                </div>
                            </div>
                        </div>

                        {/* Running job status */}
                        {runJob && runJob.status === 'running' && (
                            <div style={{ padding: '0 0.75rem 0.75rem' }}>
                                <JobStatusPanel job={runJob} />
                            </div>
                        )}

                        {/* Failed job result */}
                        {runJob && runJob.status !== 'running' && runJob.result && !runJob.result.passed && (
                            <div style={{ padding: '0 0.75rem 0.75rem' }}>
                                <div style={{
                                    padding: '0.5rem 0.75rem',
                                    background: 'rgba(239, 68, 68, 0.05)',
                                    border: '1px solid rgba(239, 68, 68, 0.15)',
                                    borderRadius: 'var(--radius)',
                                    fontSize: '0.75rem',
                                    color: 'var(--danger)',
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: '0.5rem',
                                }}>
                                    <AlertCircle size={14} />
                                    <span style={{ flex: 1 }}>
                                        {runJob.result.first_failure || runJob.message || 'Test failed'}
                                    </span>
                                </div>
                            </div>
                        )}

                        {/* Expanded content */}
                        {isExpanded && (
                            <div style={{ borderTop: '1px solid var(--border)', padding: '1rem', background: 'rgba(0,0,0,0.02)' }}>
                                {isEditing ? (
                                    <div>
                                        {/* Code / Visual toggle */}
                                        <div style={{ display: 'flex', gap: '0', marginBottom: '0.75rem' }}>
                                            {(['visual', 'code'] as const).map(mode => (
                                                <button
                                                    key={mode}
                                                    onClick={() => setEditMode(mode)}
                                                    style={{
                                                        padding: '0.35rem 0.8rem',
                                                        border: '1px solid var(--border)',
                                                        borderRight: mode === 'visual' ? 'none' : undefined,
                                                        borderRadius: mode === 'visual' ? 'var(--radius) 0 0 var(--radius)' : '0 var(--radius) var(--radius) 0',
                                                        background: editMode === mode ? 'var(--primary-glow)' : 'transparent',
                                                        color: editMode === mode ? 'var(--primary)' : 'var(--text-secondary)',
                                                        fontWeight: editMode === mode ? 600 : 400,
                                                        cursor: 'pointer',
                                                        fontSize: '0.75rem',
                                                    }}
                                                >
                                                    {mode === 'visual' ? 'Visual' : 'Code'}
                                                </button>
                                            ))}
                                        </div>
                                        {editMode === 'visual' ? (
                                            <ApiSpecBuilder content={editContent} onChange={setEditContent} />
                                        ) : (
                                            <textarea
                                                value={editContent}
                                                onChange={e => setEditContent(e.target.value)}
                                                style={{
                                                    width: '100%', minHeight: '300px', padding: '0.75rem',
                                                    background: 'var(--background)', color: 'var(--text)', border: '1px solid var(--border)',
                                                    borderRadius: 'var(--radius)', fontFamily: 'monospace', fontSize: '0.8rem',
                                                    resize: 'vertical',
                                                }}
                                            />
                                        )}
                                        <div style={{ display: 'flex', gap: '0.5rem', marginTop: '0.75rem' }}>
                                            <button
                                                onClick={() => handleUpdateSpec(spec.name)}
                                                style={{
                                                    display: 'flex', alignItems: 'center', gap: '0.3rem',
                                                    padding: '0.4rem 0.8rem', background: 'var(--primary)',
                                                    color: 'white', border: 'none', borderRadius: 'var(--radius)',
                                                    cursor: 'pointer', fontSize: '0.8rem',
                                                }}
                                            >
                                                <Save size={12} /> Save
                                            </button>
                                            <button
                                                onClick={() => setEditingSpec(null)}
                                                style={{
                                                    display: 'flex', alignItems: 'center', gap: '0.3rem',
                                                    padding: '0.4rem 0.8rem', background: 'var(--surface)',
                                                    color: 'var(--text-secondary)', border: '1px solid var(--border)',
                                                    borderRadius: 'var(--radius)', cursor: 'pointer', fontSize: '0.8rem',
                                                }}
                                            >
                                                <X size={12} /> Cancel
                                            </button>
                                        </div>
                                    </div>
                                ) : (
                                    <div>
                                        {/* Tags */}
                                        {spec.tags && spec.tags.length > 0 && (
                                            <div style={{ display: 'flex', gap: '0.3rem', marginBottom: '0.75rem', flexWrap: 'wrap' }}>
                                                {spec.tags.map(tag => (
                                                    <span key={tag} style={{
                                                        padding: '0.1rem 0.4rem', borderRadius: '999px',
                                                        fontSize: '0.65rem', fontWeight: 500,
                                                        background: 'rgba(192, 132, 252, 0.12)', color: 'var(--accent)',
                                                    }}>
                                                        {tag}
                                                    </span>
                                                ))}
                                            </div>
                                        )}

                                        {/* Spec content */}
                                        <SyntaxHighlighter
                                            language="markdown"
                                            style={vscDarkPlus}
                                            customStyle={{ margin: 0, padding: '1rem', fontSize: '0.8rem', borderRadius: 'var(--radius)', maxHeight: '400px' }}
                                            showLineNumbers={true}
                                            wrapLines={true}
                                        >
                                            {specContents[spec.name] || 'Loading...'}
                                        </SyntaxHighlighter>

                                        {/* Action buttons row */}
                                        <div style={{ display: 'flex', gap: '0.5rem', marginTop: '0.75rem', flexWrap: 'wrap' }}>
                                            <button
                                                onClick={() => {
                                                    setEditingSpec(spec.name);
                                                    setEditContent(specContents[spec.name] || '');
                                                    setEditMode('visual');
                                                }}
                                                style={{
                                                    display: 'flex', alignItems: 'center', gap: '0.3rem',
                                                    padding: '0.4rem 0.8rem',
                                                    background: 'var(--surface)', color: 'var(--text-secondary)',
                                                    border: '1px solid var(--border)', borderRadius: 'var(--radius)',
                                                    cursor: 'pointer', fontSize: '0.8rem',
                                                }}
                                            >
                                                <Edit2 size={12} /> Edit Spec
                                            </button>
                                            {spec.has_generated_test && spec.generated_test_path && (
                                                <button
                                                    onClick={() => handleRunDirect(spec.name, spec.generated_test_path!, spec.path)}
                                                    disabled={isRunning}
                                                    style={{
                                                        display: 'flex', alignItems: 'center', gap: '0.3rem',
                                                        padding: '0.4rem 0.8rem',
                                                        background: 'var(--success-muted)', color: 'var(--success)',
                                                        border: '1px solid rgba(16, 185, 129, 0.2)',
                                                        borderRadius: 'var(--radius)', cursor: isRunning ? 'wait' : 'pointer',
                                                        fontSize: '0.8rem', opacity: isRunning ? 0.5 : 1,
                                                    }}
                                                >
                                                    <Zap size={12} /> Run
                                                </button>
                                            )}
                                            <button
                                                onClick={() => handleRunTest(spec.path)}
                                                disabled={isRunning}
                                                style={{
                                                    display: 'flex', alignItems: 'center', gap: '0.3rem',
                                                    padding: '0.4rem 0.8rem',
                                                    background: 'var(--primary-glow)', color: 'var(--primary)',
                                                    border: '1px solid rgba(59, 130, 246, 0.2)',
                                                    borderRadius: 'var(--radius)', cursor: isRunning ? 'wait' : 'pointer',
                                                    fontSize: '0.8rem', opacity: isRunning ? 0.5 : 1,
                                                }}
                                            >
                                                <Activity size={12} /> Generate & Run
                                            </button>
                                        </div>

                                        {/* Generated test links */}
                                        {spec.generated_tests && spec.generated_tests.length > 0 && (
                                            <div style={{ marginTop: '0.75rem' }}>
                                                <div style={{ fontSize: '0.8rem', fontWeight: 600, marginBottom: '0.4rem', color: 'var(--text-primary)' }}>
                                                    Generated Tests ({spec.generated_tests.length})
                                                </div>
                                                {spec.generated_tests.map(testRef => (
                                                    <div key={testRef.name} style={{
                                                        fontSize: '0.75rem', display: 'flex', alignItems: 'center',
                                                        gap: '0.4rem', padding: '0.2rem 0',
                                                        color: 'var(--text-secondary)',
                                                    }}>
                                                        <Play size={10} style={{ color: 'var(--success)', flexShrink: 0 }} />
                                                        <span
                                                            onClick={(e) => { e.stopPropagation(); navigateToTest(testRef.name); }}
                                                            style={{ color: 'var(--primary)', cursor: 'pointer' }}
                                                            onMouseEnter={e => (e.currentTarget.style.textDecoration = 'underline')}
                                                            onMouseLeave={e => (e.currentTarget.style.textDecoration = 'none')}
                                                        >
                                                            {testRef.name}
                                                        </span>
                                                        {testRef.test_count > 0 && (
                                                            <span style={{ color: 'var(--text-secondary)', fontSize: '0.7rem' }}>
                                                                -- {testRef.test_count} test{testRef.test_count > 1 ? 's' : ''}
                                                            </span>
                                                        )}
                                                    </div>
                                                ))}
                                            </div>
                                        )}
                                    </div>
                                )}
                            </div>
                        )}
                    </div>
                );
            })}
        </div>
    );
});
