'use client';
import React, { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import dynamic from 'next/dynamic';
import {
    Activity, Play, FileCode, Loader2, CheckCircle, AlertCircle,
    X, Clock, Square, BarChart2,
} from 'lucide-react';
import { PageLayout } from '@/components/ui/page-layout';
import { PageHeader } from '@/components/ui/page-header';
import { Terminal, ChevronDown, ChevronRight } from 'lucide-react';
import { useProject } from '@/contexts/ProjectContext';
import { API_BASE } from '@/lib/api';
import { timeAgo } from '@/lib/formatting';
import { createTabStyle } from '@/lib/styles';
import type {
    LoadSpec, K6Script, LoadTestRun, JobStatus, TabType,
    K6ExecutionStatus, ComparisonData, SystemLimits,
} from './components/types';

// Sub-components
import ScenariosTab from './components/ScenariosTab';
import ScriptsTab from './components/ScriptsTab';
import HistoryTab from './components/HistoryTab';
import SystemInfoPanel from './components/SystemInfoPanel';

// Lazy-load chart-heavy components (moves ~80KB Recharts out of main bundle)
const ResultsView = dynamic(() => import('./components/ResultsView'), { ssr: false });
const ComparisonView = dynamic(() => import('./components/ComparisonView'), { ssr: false });
const OverviewTab = dynamic(() => import('./components/OverviewTab'), { ssr: false });

// ========== Log Viewer (kept inline -- small, tightly coupled to job polling) ==========

function LogViewer({ jobId, isRunning }: { jobId: string; isRunning: boolean }) {
    const [logs, setLogs] = useState('');
    const [lineCount, setLineCount] = useState(0);
    const [expanded, setExpanded] = useState(true);
    const logRef = useRef<HTMLPreElement>(null);
    const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

    const fetchLogs = useCallback(async () => {
        try {
            const res = await fetch(`${API_BASE}/load-testing/jobs/${jobId}/logs?tail=200`);
            if (res.ok) {
                const data = await res.json();
                setLogs(data.logs || '');
                setLineCount(data.line_count || 0);
            }
        } catch {
            // ignore
        }
    }, [jobId]);

    useEffect(() => {
        fetchLogs();
        if (isRunning) {
            intervalRef.current = setInterval(fetchLogs, 3000);
        }
        return () => {
            if (intervalRef.current) clearInterval(intervalRef.current);
        };
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

function JobStatusPanel({ job, onStop }: { job: JobStatus; onStop?: () => void }) {
    const isRunning = job.status === 'running' || job.status === 'pending';
    const isCompleted = job.status === 'completed';

    const stageLabel = (() => {
        switch (job.stage) {
            case 'generating': return 'Generating K6 script...';
            case 'validating': return 'Validating script...';
            case 'running': return 'Running load test...';
            case 'parsing': return 'Parsing results...';
            case 'done': return isCompleted ? 'Completed' : 'Failed';
            default: return job.message || 'Processing...';
        }
    })();

    const borderColor = isRunning ? 'var(--primary)' : isCompleted ? 'var(--success)' : 'var(--danger)';
    const bgColor = isRunning ? 'rgba(59, 130, 246, 0.05)' : isCompleted ? 'rgba(16, 185, 129, 0.05)' : 'rgba(239, 68, 68, 0.05)';

    return (
        <div style={{
            marginTop: '0.75rem', padding: '0.75rem 1rem',
            background: bgColor, border: `1px solid ${borderColor}`,
            borderRadius: 'var(--radius)',
        }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                {isRunning ? (
                    <Loader2 size={16} style={{ color: 'var(--primary)', animation: 'spin 1s linear infinite' }} />
                ) : isCompleted ? (
                    <CheckCircle size={16} style={{ color: 'var(--success)' }} />
                ) : (
                    <AlertCircle size={16} style={{ color: 'var(--danger)' }} />
                )}
                <span style={{ fontSize: '0.8rem', fontWeight: 500, color: borderColor }}>
                    {stageLabel}
                </span>
                {job.worker_count && job.worker_count > 1 && (
                    <span style={{
                        padding: '0.1rem 0.4rem', borderRadius: '999px', fontSize: '0.65rem',
                        fontWeight: 600, background: 'rgba(192, 132, 252, 0.12)', color: 'var(--accent)',
                        border: '1px solid rgba(139, 92, 246, 0.2)',
                    }}>
                        {job.worker_count} workers
                    </span>
                )}
                <div style={{ display: 'flex', gap: '0.4rem', marginLeft: 'auto' }}>
                    {isRunning && onStop && (
                        <button
                            onClick={onStop}
                            style={{
                                display: 'flex', alignItems: 'center', gap: '0.25rem',
                                padding: '0.2rem 0.5rem', borderRadius: 'var(--radius)', fontSize: '0.7rem',
                                fontWeight: 600, background: 'var(--danger-muted)', color: 'var(--danger)',
                                border: '1px solid rgba(239, 68, 68, 0.2)', cursor: 'pointer',
                            }}
                        >
                            <Square size={10} /> Stop
                        </button>
                    )}
                    {!isRunning && (
                        <span style={{
                            padding: '0.15rem 0.5rem', borderRadius: '999px', fontSize: '0.7rem',
                            fontWeight: 600,
                            background: isCompleted ? 'var(--success-muted)' : 'var(--danger-muted)',
                            color: isCompleted ? 'var(--success)' : 'var(--danger)',
                        }}>
                            {isCompleted ? 'COMPLETED' : 'FAILED'}
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

// ========== Main Page ==========

export default function LoadTestingPage() {
    const { currentProject } = useProject();
    const projectId = currentProject?.id || 'default';

    const [activeTab, setActiveTab] = useState<TabType>('overview');
    const [visited, setVisited] = useState(new Set<string>(['overview']));

    // Scenarios state
    const [specs, setSpecs] = useState<LoadSpec[]>([]);
    const [specsLoading, setSpecsLoading] = useState(true);
    const [specContents, setSpecContents] = useState<Record<string, string>>({});

    // Scripts state
    const [scripts, setScripts] = useState<K6Script[]>([]);
    const [scriptsLoading, setScriptsLoading] = useState(true);
    const [scriptContents, setScriptContents] = useState<Record<string, string>>({});

    // History state
    const [runs, setRuns] = useState<LoadTestRun[]>([]);
    const [runsLoading, setRunsLoading] = useState(false);
    const [runsOffset, setRunsOffset] = useState(0);
    const [runsHasMore, setRunsHasMore] = useState(false);
    const [expandedRunId, setExpandedRunId] = useState<string | null>(null);
    const [expandedRunData, setExpandedRunData] = useState<LoadTestRun | null>(null);
    const RUNS_PAGE_SIZE = 20;

    // Comparison state
    const [compareIds, setCompareIds] = useState<Set<string>>(new Set());
    const [comparisonData, setComparisonData] = useState<ComparisonData | null>(null);
    const [comparisonLoading, setComparisonLoading] = useState(false);

    // Jobs
    const [activeJobs, setActiveJobs] = useState<Record<string, JobStatus>>({});
    const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);
    const [k6Status, setK6Status] = useState<K6ExecutionStatus | null>(null);

    // System limits
    const [systemLimits, setSystemLimits] = useState<SystemLimits | null>(null);
    const [showSystemInfo, setShowSystemInfo] = useState(false);
    const [stoppingRunId, setStoppingRunId] = useState<string | null>(null);

    // AI Analysis state
    const [analyzingRunId, setAnalyzingRunId] = useState<string | null>(null);

    // Track visited tabs
    useEffect(() => {
        setVisited(prev => new Set([...prev, activeTab]));
    }, [activeTab]);

    // ========== Data Fetching ==========

    const fetchSpecs = useCallback(async () => {
        setSpecsLoading(true);
        try {
            const res = await fetch(`${API_BASE}/load-testing/specs?project_id=${projectId}`);
            if (res.ok) setSpecs(await res.json());
        } catch (e) {
            console.error('Failed to fetch load test specs:', e);
        } finally {
            setSpecsLoading(false);
        }
    }, [projectId]);

    const fetchScripts = useCallback(async () => {
        setScriptsLoading(true);
        try {
            const res = await fetch(`${API_BASE}/load-testing/scripts`);
            if (res.ok) setScripts(await res.json());
        } catch (e) {
            console.error('Failed to fetch K6 scripts:', e);
        } finally {
            setScriptsLoading(false);
        }
    }, []);

    const fetchRuns = useCallback(async (offset = 0, append = false) => {
        setRunsLoading(true);
        try {
            const res = await fetch(`${API_BASE}/load-testing/runs?project_id=${projectId}&limit=${RUNS_PAGE_SIZE}&offset=${offset}`);
            if (res.ok) {
                const data = await res.json();
                if (append) {
                    setRuns(prev => [...prev, ...(data.runs || data)]);
                } else {
                    setRuns(data.runs || data);
                }
                setRunsHasMore(data.has_more ?? false);
                setRunsOffset(offset);
            }
        } catch (err) {
            console.error('Failed to fetch load test runs:', err);
        } finally {
            setRunsLoading(false);
        }
    }, [projectId]);

    // ========== Job Polling ==========

    const pollJob = useCallback((jobId: string, onComplete?: () => void) => {
        const interval = setInterval(async () => {
            try {
                const res = await fetch(`${API_BASE}/load-testing/jobs/${jobId}`);
                if (res.ok) {
                    const data: JobStatus = await res.json();
                    setActiveJobs(prev => ({ ...prev, [jobId]: data }));
                    if (data.status !== 'running' && data.status !== 'pending') {
                        clearInterval(interval);
                        if (data.status === 'completed') {
                            setMessage({ type: 'success', text: data.message || 'Job completed successfully' });
                        } else {
                            setMessage({ type: 'error', text: data.message || 'Job failed' });
                        }
                        fetchSpecs();
                        fetchScripts();
                        fetchRuns(0);
                        onComplete?.();
                    }
                }
            } catch {
                clearInterval(interval);
            }
        }, 3000);
        return () => clearInterval(interval);
    }, [fetchSpecs, fetchScripts, fetchRuns]);

    useEffect(() => {
        fetchSpecs();
        fetchScripts();
    }, [fetchSpecs, fetchScripts]);

    useEffect(() => {
        if (activeTab === 'history') fetchRuns(0);
    }, [activeTab, fetchRuns]);

    // K6 status polling
    useEffect(() => {
        const fetchStatus = async () => {
            try {
                const res = await fetch(`${API_BASE}/load-testing/status`);
                if (res.ok) setK6Status(await res.json());
            } catch {
                // Silently fail
            }
        };
        fetchStatus();
        const interval = setInterval(fetchStatus, 5000);
        return () => clearInterval(interval);
    }, []);

    // Fetch system limits once on mount
    useEffect(() => {
        (async () => {
            try {
                const res = await fetch(`${API_BASE}/load-testing/system-limits`);
                if (res.ok) setSystemLimits(await res.json());
            } catch {
                // Non-critical
            }
        })();
    }, []);

    // ========== Actions ==========

    const handleCreateSpec = useCallback(async (name: string, content: string) => {
        const res = await fetch(`${API_BASE}/load-testing/specs`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name, content, project_id: projectId }),
        });
        if (res.ok) {
            setMessage({ type: 'success', text: 'Load test spec created' });
            fetchSpecs();
        } else {
            const err = await res.json();
            setMessage({ type: 'error', text: err.detail || 'Failed to create spec' });
            throw new Error('create failed');
        }
    }, [projectId, fetchSpecs]);

    const handleUpdateSpec = useCallback(async (name: string, content: string) => {
        try {
            const res = await fetch(`${API_BASE}/load-testing/specs/${name}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ content }),
            });
            if (res.ok) {
                setMessage({ type: 'success', text: 'Spec updated' });
                setSpecContents(prev => ({ ...prev, [name]: content }));
            }
        } catch {
            setMessage({ type: 'error', text: 'Failed to update spec' });
        }
    }, []);

    const handleDeleteSpec = useCallback(async (name: string) => {
        if (!confirm('Delete this load test spec?')) return;
        try {
            const res = await fetch(`${API_BASE}/load-testing/specs/${name}`, { method: 'DELETE' });
            if (res.ok) {
                setMessage({ type: 'success', text: 'Spec deleted' });
                fetchSpecs();
            }
        } catch {
            setMessage({ type: 'error', text: 'Failed to delete spec' });
        }
    }, [fetchSpecs]);

    const handleGenerateScript = useCallback(async (name: string) => {
        try {
            const res = await fetch(`${API_BASE}/load-testing/generate`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ spec_name: name, project_id: projectId }),
            });
            if (res.ok) {
                const data = await res.json();
                setActiveJobs(prev => ({ ...prev, [data.job_id]: { job_id: data.job_id, status: 'running', stage: 'generating', message: data.message } }));
                pollJob(data.job_id);
            }
        } catch {
            setMessage({ type: 'error', text: 'Failed to start script generation' });
        }
    }, [projectId, pollJob]);

    const handleRunFromSpec = useCallback(async (name: string, vus?: string, duration?: string) => {
        const vusNum = vus ? parseInt(vus, 10) : 0;
        if (vusNum > 500) {
            const limitsInfo = systemLimits
                ? `\n- Max VUs: ${systemLimits.effective_max_vus.toLocaleString()} (${systemLimits.execution_mode}${systemLimits.execution_mode === 'distributed' ? `, ${systemLimits.workers_connected} workers` : ''})` +
                  `\n- Browser pool: ${systemLimits.max_browser_instances} slots will be paused`
                : '';
            const confirmed = window.confirm(
                `You are about to run a load test with ${vusNum} VUs. This will:\n` +
                `- Pause all browser operations (test runs, explorations, agents)\n` +
                `- Require significant system resources` +
                limitsInfo + `\n\nContinue?`
            );
            if (!confirmed) return;
        }
        try {
            const body: Record<string, unknown> = { spec_name: name, project_id: projectId };
            if (vus) body.vus = parseInt(vus, 10);
            if (duration) body.duration = duration;
            const res = await fetch(`${API_BASE}/load-testing/run-from-spec`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });
            if (res.status === 409) {
                const err = await res.json();
                setMessage({ type: 'error', text: err.detail || 'A load test is already running' });
                return;
            }
            if (res.ok) {
                const data = await res.json();
                setActiveJobs(prev => ({ ...prev, [data.job_id]: { job_id: data.job_id, status: 'running', stage: 'generating', message: data.message } }));
                pollJob(data.job_id);
            } else {
                const err = await res.json().catch(() => ({}));
                setMessage({ type: 'error', text: err.detail || `Run failed (${res.status})` });
            }
        } catch {
            setMessage({ type: 'error', text: 'Failed to start load test' });
        }
    }, [projectId, pollJob, systemLimits]);

    const handleRunScript = useCallback(async (scriptPath: string, vus: string, duration: string) => {
        const vusNum = vus ? parseInt(vus, 10) : 0;
        if (vusNum > 500) {
            const limitsInfo = systemLimits
                ? `\n- Max VUs: ${systemLimits.effective_max_vus.toLocaleString()} (${systemLimits.execution_mode}${systemLimits.execution_mode === 'distributed' ? `, ${systemLimits.workers_connected} workers` : ''})` +
                  `\n- Browser pool: ${systemLimits.max_browser_instances} slots will be paused`
                : '';
            const confirmed = window.confirm(
                `You are about to run a load test with ${vusNum} VUs. This will:\n` +
                `- Pause all browser operations (test runs, explorations, agents)\n` +
                `- Require significant system resources` +
                limitsInfo + `\n\nContinue?`
            );
            if (!confirmed) return;
        }
        try {
            const body: Record<string, unknown> = { script_path: scriptPath, project_id: projectId };
            if (vus) body.vus = parseInt(vus, 10);
            if (duration) body.duration = duration;
            const res = await fetch(`${API_BASE}/load-testing/run`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });
            if (res.status === 409) {
                const err = await res.json();
                setMessage({ type: 'error', text: err.detail || 'A load test is already running' });
                return;
            }
            if (res.ok) {
                const data = await res.json();
                setActiveJobs(prev => ({ ...prev, [data.job_id]: { job_id: data.job_id, status: 'running', stage: 'running', message: data.message } }));
                pollJob(data.job_id);
            } else {
                const err = await res.json().catch(() => ({}));
                setMessage({ type: 'error', text: err.detail || `Run failed (${res.status})` });
            }
        } catch {
            setMessage({ type: 'error', text: 'Failed to start script run' });
        }
    }, [projectId, pollJob, systemLimits]);

    const handleStopRun = useCallback(async (runId: string) => {
        if (stoppingRunId) return;
        setStoppingRunId(runId);
        try {
            const res = await fetch(`${API_BASE}/load-testing/runs/${runId}/stop`, { method: 'POST' });
            if (res.ok) {
                const data = await res.json();
                setMessage({ type: 'success', text: data.message || `Load test ${runId} stopped` });
            } else {
                const err = await res.json().catch(() => ({}));
                const forceRes = await fetch(`${API_BASE}/load-testing/force-unlock`, { method: 'POST' });
                if (forceRes.ok) {
                    setMessage({ type: 'success', text: 'Load test lock force-released' });
                } else {
                    setMessage({ type: 'error', text: err.detail || `Failed to stop load test (${res.status})` });
                }
            }
        } catch {
            setMessage({ type: 'error', text: 'Failed to stop load test -- network error' });
        } finally {
            setStoppingRunId(null);
        }
    }, [stoppingRunId]);

    const handleForceUnlock = useCallback(async () => {
        if (stoppingRunId) return;
        setStoppingRunId('force-unlock');
        try {
            const res = await fetch(`${API_BASE}/load-testing/force-unlock`, { method: 'POST' });
            if (res.ok) {
                const data = await res.json();
                setMessage({ type: 'success', text: data.message || 'Lock released' });
            } else {
                const err = await res.json().catch(() => ({}));
                setMessage({ type: 'error', text: err.detail || 'Failed to force-unlock' });
            }
        } catch {
            setMessage({ type: 'error', text: 'Failed to force-unlock -- network error' });
        } finally {
            setStoppingRunId(null);
        }
    }, [stoppingRunId]);

    const loadSpecContent = useCallback(async (name: string) => {
        if (specContents[name]) return;
        try {
            const res = await fetch(`${API_BASE}/load-testing/specs/${name}`);
            if (res.ok) {
                const data = await res.json();
                setSpecContents(prev => ({ ...prev, [name]: data.content }));
            }
        } catch {
            // ignore
        }
    }, [specContents]);

    const loadScriptContent = useCallback(async (name: string) => {
        if (scriptContents[name]) return;
        try {
            const res = await fetch(`${API_BASE}/load-testing/scripts/${name}`);
            if (res.ok) {
                const data = await res.json();
                setScriptContents(prev => ({ ...prev, [name]: data.content }));
            }
        } catch {
            // ignore
        }
    }, [scriptContents]);

    const loadRunDetails = useCallback(async (runId: string) => {
        setExpandedRunData(null);
        try {
            const res = await fetch(`${API_BASE}/load-testing/runs/${runId}`);
            if (res.ok) setExpandedRunData(await res.json());
        } catch {
            // ignore
        }
    }, []);

    const loadComparison = useCallback(async () => {
        const ids = Array.from(compareIds);
        if (ids.length !== 2) return;
        setComparisonLoading(true);
        try {
            const res = await fetch(`${API_BASE}/load-testing/runs/compare?run_a=${ids[0]}&run_b=${ids[1]}`);
            if (res.ok) {
                setComparisonData(await res.json());
            } else {
                setMessage({ type: 'error', text: 'Failed to load comparison data' });
            }
        } catch {
            setMessage({ type: 'error', text: 'Failed to load comparison data' });
        } finally {
            setComparisonLoading(false);
        }
    }, [compareIds]);

    const toggleCompareId = useCallback((id: string) => {
        setCompareIds(prev => {
            const next = new Set(prev);
            if (next.has(id)) next.delete(id);
            else if (next.size < 2) next.add(id);
            return next;
        });
    }, []);

    const handleSetExpandedRunId = useCallback((id: string | null) => {
        setExpandedRunId(id);
        if (!id) setExpandedRunData(null);
    }, []);

    const handleAnalyzeRun = useCallback(async (runId: string) => {
        setAnalyzingRunId(runId);
        try {
            const res = await fetch(`${API_BASE}/load-testing/runs/${runId}/analyze`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
            });
            if (res.ok) {
                const data = await res.json();
                if (data.job_id) {
                    // Poll job until complete, then refresh run details
                    pollJob(data.job_id, () => {
                        setAnalyzingRunId(null);
                        loadRunDetails(runId);
                    });
                } else {
                    // Immediate result - refresh run details
                    setAnalyzingRunId(null);
                    loadRunDetails(runId);
                }
            } else {
                const err = await res.json().catch(() => ({}));
                setMessage({ type: 'error', text: err.detail || 'Failed to start analysis' });
                setAnalyzingRunId(null);
            }
        } catch {
            setMessage({ type: 'error', text: 'Failed to start AI analysis' });
            setAnalyzingRunId(null);
        }
    }, [pollJob, loadRunDetails]);

    const handleNavigateToRun = useCallback((runId: string) => {
        setActiveTab('history');
        setExpandedRunId(runId);
        loadRunDetails(runId);
        fetchRuns(0);
    }, [loadRunDetails, fetchRuns]);

    const hasRunningJobs = Object.values(activeJobs).some(j => j.status === 'running' || j.status === 'pending');

    const tabStyle = useMemo(() => (tab: TabType) => createTabStyle(activeTab, tab), [activeTab]);

    // ========== Render ==========

    return (
        <PageLayout tier="wide">
            <PageHeader
                title="Load Testing"
                subtitle="Create K6 load test scenarios, generate scripts, and analyze performance."
                icon={<Activity size={20} />}
                actions={
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                        {k6Status && (
                            <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ${
                                k6Status.mode === 'distributed'
                                    ? 'bg-green-500/10 text-green-400 border border-green-500/20'
                                    : 'bg-yellow-500/10 text-yellow-400 border border-yellow-500/20'
                            }`}>
                                <span className={`w-1.5 h-1.5 rounded-full ${
                                    k6Status.mode === 'distributed' ? 'bg-green-400' : 'bg-yellow-400'
                                }`} />
                                {k6Status.mode === 'distributed'
                                    ? `Distributed (${k6Status.workers_connected} worker${k6Status.workers_connected !== 1 ? 's' : ''}${
                                        k6Status.load_test_active && k6Status.active_run?.vus && k6Status.workers_connected > 1
                                            ? ` × ${Math.ceil(k6Status.active_run.vus / k6Status.workers_connected)} VUs`
                                            : ''
                                    })`
                                    : 'Local'}
                            </span>
                        )}
                        {hasRunningJobs && (
                            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', color: 'var(--primary)' }}>
                                <Loader2 size={16} style={{ animation: 'spin 1s linear infinite' }} />
                                <span style={{ fontSize: '0.875rem' }}>Jobs running...</span>
                            </div>
                        )}
                    </div>
                }
            />

            {/* Status Message */}
            {message && (
                <div style={{
                    padding: '0.75rem 1rem', marginBottom: '1rem', borderRadius: 'var(--radius)',
                    background: message.type === 'success' ? 'var(--success-muted)' : 'var(--danger-muted)',
                    border: `1px solid ${message.type === 'success' ? 'var(--success)' : 'var(--danger)'}`,
                    color: message.type === 'success' ? 'var(--success)' : 'var(--danger)',
                    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                        {message.type === 'success' ? <CheckCircle size={16} /> : <AlertCircle size={16} />}
                        <span style={{ fontSize: '0.875rem' }}>{message.text}</span>
                    </div>
                    <button onClick={() => setMessage(null)} style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'inherit' }}>
                        <X size={16} />
                    </button>
                </div>
            )}

            {/* Active Load Test Banner */}
            {k6Status?.load_test_active && k6Status.active_run && (
                <div style={{
                    padding: '0.75rem 1rem', marginBottom: '1rem', borderRadius: 'var(--radius)',
                    background: 'var(--warning-muted)',
                    border: '1px solid rgba(245, 158, 11, 0.3)',
                    display: 'flex', alignItems: 'center', gap: '0.75rem',
                }}>
                    <Activity size={18} style={{ color: 'var(--warning)', flexShrink: 0 }} />
                    <div style={{ flex: 1 }}>
                        <div style={{ fontWeight: 600, color: 'var(--warning)', fontSize: '0.875rem' }}>
                            Load Test Active -- Other Operations Paused
                        </div>
                        <div style={{ color: 'var(--text-secondary)', fontSize: '0.8rem', marginTop: '0.25rem' }}>
                            Run {k6Status.active_run.run_id}
                            {k6Status.active_run.vus && ` · ${k6Status.active_run.vus} VUs`}
                            {k6Status.active_run.duration && ` · ${k6Status.active_run.duration}`}
                            {k6Status.workers_connected > 1 && k6Status.active_run.vus ? ` · ${k6Status.workers_connected} workers × ${Math.ceil(k6Status.active_run.vus / k6Status.workers_connected)} VUs each` : k6Status.workers_connected > 1 ? ` · ${k6Status.workers_connected} workers` : ''}
                            {systemLimits && ` · ${systemLimits.max_browser_instances}/${systemLimits.max_browser_instances} browser slots paused`}
                            {(() => {
                                if (!k6Status.active_run.started_at || !k6Status.active_run.duration) return null;
                                const durationStr = k6Status.active_run.duration;
                                let totalSecs = 0;
                                const mMatch = durationStr.match(/(\d+)m/);
                                const sMatch = durationStr.match(/(\d+)s/);
                                if (mMatch) totalSecs += parseInt(mMatch[1]) * 60;
                                if (sMatch) totalSecs += parseInt(sMatch[1]);
                                if (!totalSecs) return null;
                                const elapsed = Math.floor(Date.now() / 1000 - k6Status.active_run.started_at);
                                const remaining = Math.max(0, totalSecs - elapsed);
                                if (remaining <= 0) return ' · finishing...';
                                const mins = Math.floor(remaining / 60);
                                const secs = remaining % 60;
                                return ` · ~${mins > 0 ? `${mins}m ` : ''}${secs}s remaining`;
                            })()}
                        </div>
                    </div>
                    <button
                        onClick={() => k6Status.active_run?.run_id
                            ? handleStopRun(k6Status.active_run.run_id)
                            : handleForceUnlock()
                        }
                        disabled={!!stoppingRunId}
                        style={{
                            display: 'flex', alignItems: 'center', gap: '0.35rem',
                            padding: '0.4rem 0.75rem', borderRadius: 'var(--radius)', fontSize: '0.8rem',
                            fontWeight: 600, background: 'var(--danger-muted)', color: 'var(--danger)',
                            border: '1px solid rgba(239, 68, 68, 0.3)', cursor: stoppingRunId ? 'not-allowed' : 'pointer',
                            opacity: stoppingRunId ? 0.6 : 1, flexShrink: 0, whiteSpace: 'nowrap',
                        }}
                    >
                        {stoppingRunId ? (
                            <Loader2 size={13} style={{ animation: 'spin 1s linear infinite' }} />
                        ) : (
                            <Square size={13} />
                        )}
                        {stoppingRunId ? 'Cancelling...' : 'Cancel Test'}
                    </button>
                </div>
            )}

            {/* System Info Panel */}
            {systemLimits && (
                <SystemInfoPanel
                    systemLimits={systemLimits}
                    showSystemInfo={showSystemInfo}
                    onToggle={() => setShowSystemInfo(!showSystemInfo)}
                />
            )}

            {/* Tabs */}
            <div className="animate-in stagger-2" style={{ display: 'flex', gap: '0', borderBottom: '1px solid var(--border)', marginBottom: '1.5rem' }}>
                {[
                    { key: 'overview' as TabType, label: 'Overview', icon: BarChart2 },
                    { key: 'scenarios' as TabType, label: 'Scenarios', icon: FileCode, count: specs.length },
                    { key: 'scripts' as TabType, label: 'Scripts', icon: Play, count: scripts.length },
                    { key: 'history' as TabType, label: 'Run History', icon: Clock },
                ].map(tab => (
                    <button
                        key={tab.key}
                        onClick={() => setActiveTab(tab.key)}
                        style={{
                            display: 'flex', alignItems: 'center', gap: '0.5rem',
                            padding: '0.75rem 1.25rem', border: 'none',
                            borderBottom: activeTab === tab.key ? '2px solid var(--primary)' : '2px solid transparent',
                            background: 'none',
                            color: activeTab === tab.key ? 'var(--primary)' : 'var(--text-secondary)',
                            fontWeight: activeTab === tab.key ? 600 : 400,
                            cursor: 'pointer', fontSize: '0.875rem', transition: 'all 0.2s var(--ease-smooth)',
                        }}
                    >
                        <tab.icon size={16} />
                        {tab.label}
                        {tab.count !== undefined && (
                            <span style={{
                                background: activeTab === tab.key ? 'var(--primary-glow)' : 'rgba(0,0,0,0.1)',
                                padding: '0.1rem 0.5rem', borderRadius: '999px', fontSize: '0.75rem',
                            }}>
                                {tab.count}
                            </span>
                        )}
                    </button>
                ))}
            </div>

            {/* Active Jobs Panel */}
            {Object.values(activeJobs).filter(j => j.status === 'running' || j.status === 'pending').length > 0 && (
                <div style={{ marginBottom: '1rem' }}>
                    {Object.values(activeJobs)
                        .filter(j => j.status === 'running' || j.status === 'pending')
                        .map(job => (
                            <JobStatusPanel
                                key={job.job_id}
                                job={job}
                                onStop={() => handleStopRun(job.job_id)}
                            />
                        ))}
                </div>
            )}

            {/* Tab Content */}
            {activeTab === 'overview' && (
                <OverviewTab onNavigateToRun={handleNavigateToRun} />
            )}

            {activeTab === 'scenarios' && (
                <ScenariosTab
                    specs={specs}
                    specsLoading={specsLoading}
                    k6Status={k6Status}
                    systemLimits={systemLimits}
                    onFetchSpecs={fetchSpecs}
                    onCreateSpec={handleCreateSpec}
                    onUpdateSpec={handleUpdateSpec}
                    onDeleteSpec={handleDeleteSpec}
                    onGenerateScript={handleGenerateScript}
                    onRunFromSpec={handleRunFromSpec}
                    onLoadSpecContent={loadSpecContent}
                    specContents={specContents}
                />
            )}

            {activeTab === 'scripts' && (
                <ScriptsTab
                    scripts={scripts}
                    scriptsLoading={scriptsLoading}
                    k6Status={k6Status}
                    systemLimits={systemLimits}
                    onFetchScripts={fetchScripts}
                    onRunScript={handleRunScript}
                    onLoadScriptContent={loadScriptContent}
                    scriptContents={scriptContents}
                />
            )}

            {activeTab === 'history' && (
                <HistoryTab
                    runs={runs}
                    runsLoading={runsLoading}
                    runsHasMore={runsHasMore}
                    runsOffset={runsOffset}
                    RUNS_PAGE_SIZE={RUNS_PAGE_SIZE}
                    expandedRunId={expandedRunId}
                    expandedRunData={expandedRunData}
                    compareIds={compareIds}
                    comparisonData={comparisonData}
                    comparisonLoading={comparisonLoading}
                    onFetchRuns={fetchRuns}
                    onSetExpandedRunId={handleSetExpandedRunId}
                    onLoadRunDetails={loadRunDetails}
                    onToggleCompareId={toggleCompareId}
                    onSetCompareIds={setCompareIds}
                    onLoadComparison={loadComparison}
                    onSetComparisonData={setComparisonData}
                    onAnalyzeRun={handleAnalyzeRun}
                    analyzingRunId={analyzingRunId}
                    ResultsView={ResultsView}
                    ComparisonView={ComparisonView}
                />
            )}
        </PageLayout>
    );
}
