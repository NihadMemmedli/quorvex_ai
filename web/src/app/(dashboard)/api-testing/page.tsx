'use client';
import React, { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { Zap, FileCode, Play, Upload, Clock, Loader2, AlertCircle, CheckCircle, X } from 'lucide-react';
import { PageLayout } from '@/components/ui/page-layout';
import { PageHeader } from '@/components/ui/page-header';
import { useRequiredProject } from '@/contexts/ProjectContext';
import { useSearchParams } from 'next/navigation';
import { API_BASE, withProjectQuery } from '@/lib/api';
import { createTabStyle } from '@/lib/styles';
import { ApiSpec, ApiSpecsSummary, GeneratedTest, GeneratedTestsSummary, JobStatus, ApiTestRun, TabType } from './components/types';
import SpecsPanel from './components/SpecsPanel';
import GeneratedTestsList from './components/GeneratedTestsList';
import HistoryPanel from './components/HistoryPanel';
import ApiRunDetailModal from './components/ApiRunDetailModal';
import OpenApiImportPanel from './components/OpenApiImportPanel';

const PAGE_SIZE = 50;
const RUNS_PAGE_SIZE = 20;

export default function ApiTestingPage() {
    const { projectId, isLoading: projectLoading, projects, setCurrentProject } = useRequiredProject();
    const searchParams = useSearchParams();
    const requestedProjectId = searchParams.get('project_id') || '';
    const requestedSpec = searchParams.get('spec') || searchParams.get('spec_name') || '';
    const requestedTab = searchParams.get('tab');

    // Tab state
    const [activeTab, setActiveTab] = useState<TabType>('specs');
    const [visitedTabs, setVisitedTabs] = useState<Set<TabType>>(new Set(['specs']));

    // Specs tab state
    const [apiSpecs, setApiSpecs] = useState<ApiSpec[]>([]);
    const [specsLoading, setSpecsLoading] = useState(true);
    const [specsTotal, setSpecsTotal] = useState(0);
    const [specsHasMore, setSpecsHasMore] = useState(false);
    const [specsOffset, setSpecsOffset] = useState(0);
    const [specsFolders, setSpecsFolders] = useState<string[]>([]);
    const [specsSummary, setSpecsSummary] = useState<ApiSpecsSummary | null>(null);

    // Generated tests tab state
    const [generatedTests, setGeneratedTests] = useState<GeneratedTest[]>([]);
    const [testsLoading, setTestsLoading] = useState(false);
    const [testsRefreshing, setTestsRefreshing] = useState(false);
    const [testsLoaded, setTestsLoaded] = useState(false);
    const [testsTotal, setTestsTotal] = useState(0);
    const [testsHasMore, setTestsHasMore] = useState(false);
    const [testsOffset, setTestsOffset] = useState(0);
    const [expandedTest, setExpandedTest] = useState<string | null>(null);
    const [generatedTestsSummary, setGeneratedTestsSummary] = useState<GeneratedTestsSummary | null>(null);

    // Job tracking
    const [activeJobs, setActiveJobs] = useState<Record<string, JobStatus>>({});
    const [specJobMap, setSpecJobMap] = useState<Record<string, string>>({});

    // Latest runs & history
    const [latestRuns, setLatestRuns] = useState<Record<string, ApiTestRun>>({});
    const [apiRuns, setApiRuns] = useState<ApiTestRun[]>([]);
    const [runsHasMore, setRunsHasMore] = useState(false);
    const [runsOffset, setRunsOffset] = useState(0);
    const [runsTotal, setRunsTotal] = useState(0);
    const [runsLoading, setRunsLoading] = useState(false);
    const [expandedRunId, setExpandedRunId] = useState<string | null>(null);
    const [showCreateModal, setShowCreateModal] = useState(false);
    const [detailRunId, setDetailRunId] = useState<string | null>(null);

    // Messages
    const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

    const pollJobRef = useRef<((jobId: string, onComplete?: () => void) => void) | null>(null);

    // ========== Data Fetching ==========

    const fetchApiSpecs = useCallback(async (
        offset = 0, append = false, search?: string,
        sort?: string, statusFilter?: string, folder?: string, tags?: string
    ) => {
        if (!projectId) return;
        setSpecsLoading(!append);
        try {
            let url = `${API_BASE}${withProjectQuery(`/api-testing/specs?limit=${PAGE_SIZE}&offset=${offset}`, projectId)}`;
            if (search) url += `&search=${encodeURIComponent(search)}`;
            if (sort) url += `&sort=${encodeURIComponent(sort)}`;
            if (statusFilter) url += `&status_filter=${encodeURIComponent(statusFilter)}`;
            if (folder) url += `&folder=${encodeURIComponent(folder)}`;
            if (tags) url += `&tags=${encodeURIComponent(tags)}`;
            const res = await fetch(url);
            if (res.ok) {
                const data = await res.json();
                if (Array.isArray(data)) {
                    setApiSpecs(data);
                    setSpecsTotal(data.length);
                    setSpecsHasMore(false);
                } else {
                    if (append) setApiSpecs(prev => [...prev, ...data.items]);
                    else setApiSpecs(data.items || []);
                    setSpecsTotal(data.total || 0);
                    setSpecsHasMore(data.has_more || false);
                    if (data.folders) setSpecsFolders(data.folders);
                    if (data.summary) setSpecsSummary(data.summary);
                }
                setSpecsOffset(offset);
            }
        } catch (e) { console.error('Failed to fetch API specs:', e); }
        finally { setSpecsLoading(false); }
    }, [projectId]);

    const fetchGeneratedTests = useCallback(async (offset = 0, append = false, search?: string, sort?: string, statusFilter?: string) => {
        if (!projectId) return;
        if (!append && !testsLoaded) setTestsLoading(true);
        else setTestsRefreshing(true);
        try {
            let url = `${API_BASE}${withProjectQuery(`/api-testing/generated-tests?limit=${PAGE_SIZE}&offset=${offset}`, projectId)}`;
            if (search) url += `&search=${encodeURIComponent(search)}`;
            if (sort) url += `&sort=${encodeURIComponent(sort)}`;
            if (statusFilter) url += `&status_filter=${encodeURIComponent(statusFilter)}`;
            const res = await fetch(url);
            if (res.ok) {
                const data = await res.json();
                if (Array.isArray(data)) {
                    setGeneratedTests(data);
                    setTestsTotal(data.length);
                    setTestsHasMore(false);
                } else {
                    if (append) setGeneratedTests(prev => [...prev, ...data.items]);
                    else setGeneratedTests(data.items || []);
                    setTestsTotal(data.total || 0);
                    setTestsHasMore(data.has_more || false);
                    if (data.summary) setGeneratedTestsSummary(data.summary);
                }
                setTestsOffset(offset);
                setTestsLoaded(true);
            }
        } catch (e) { console.error('Failed to fetch generated tests:', e); }
        finally { setTestsLoading(false); setTestsRefreshing(false); }
    }, [projectId, testsLoaded]);

    const fetchRecentJobs = useCallback(async () => {
        if (!projectId) return;
        try {
            const res = await fetch(`${API_BASE}${withProjectQuery('/api-testing/jobs?status=running', projectId)}`);
            if (res.ok) {
                const data = await res.json();
                const jobMap: Record<string, JobStatus> = {};
                const newSpecMap: Record<string, string> = {};
                for (const j of data) {
                    jobMap[j.job_id] = {
                        job_id: j.job_id,
                        status: j.status,
                        stage: j.stage,
                        message: j.message,
                        result: j.result,
                        type: j.type,
                    };
                    if (j.spec_path) newSpecMap[j.spec_path] = j.job_id;
                    if (j.status === 'running') pollJobRef.current?.(j.job_id);
                }
                const serverRunningJobIds = new Set(Object.keys(jobMap));
                setActiveJobs(prev => {
                    const next = { ...prev };
                    for (const [jobId, job] of Object.entries(next)) {
                        if (job.status === 'running' && !serverRunningJobIds.has(jobId)) {
                            delete next[jobId];
                        }
                    }
                    return { ...next, ...jobMap };
                });
                setSpecJobMap(prev => ({ ...prev, ...newSpecMap }));
            }
        } catch { /* ignore */ }
    }, [projectId]);

    const fetchLatestRuns = useCallback(async () => {
        if (!projectId) return;
        try {
            const res = await fetch(`${API_BASE}${withProjectQuery('/api-testing/runs/latest-by-spec', projectId)}`);
            if (res.ok) { const data = await res.json(); setLatestRuns(data.specs || {}); }
        } catch { /* ignore */ }
    }, [projectId]);

    const fetchApiRuns = useCallback(async (offset = 0, append = false) => {
        if (!projectId) return;
        setRunsLoading(true);
        try {
            const res = await fetch(`${API_BASE}${withProjectQuery(`/api-testing/runs?limit=${RUNS_PAGE_SIZE}&offset=${offset}`, projectId)}`);
            if (res.ok) {
                const data = await res.json();
                if (append) setApiRuns(prev => [...prev, ...data.runs]);
                else setApiRuns(data.runs || []);
                setRunsHasMore(data.has_more);
                setRunsTotal(data.total || 0);
                setRunsOffset(offset);
            }
        } catch { /* ignore */ }
        finally { setRunsLoading(false); }
    }, [projectId]);

    // ========== Job Polling ==========

    const pollJob = useCallback((jobId: string, onComplete?: () => void) => {
        let missCount = 0;
        const interval = setInterval(async () => {
            if (!projectId) return;
            try {
                const res = await fetch(`${API_BASE}${withProjectQuery(`/api-testing/jobs/${jobId}`, projectId)}`);
                if (res.ok) {
                    missCount = 0;
                    const data: JobStatus = await res.json();
                    setActiveJobs(prev => ({ ...prev, [jobId]: data }));
                    if (data.status !== 'running') {
                        clearInterval(interval);
                        setMessage({ type: data.status === 'completed' ? 'success' : 'error', text: data.message || (data.status === 'completed' ? 'Job completed successfully' : 'Job failed') });
                        fetchApiSpecs(0);
                        fetchGeneratedTests(0);
                        fetchLatestRuns();
                        onComplete?.();
                    }
                } else if (res.status === 404) {
                    // Job disappeared from memory - likely completed and was cleaned up
                    missCount++;
                    if (missCount >= 2) {
                        clearInterval(interval);
                        setActiveJobs(prev => {
                            const updated = { ...prev };
                            if (updated[jobId]) updated[jobId] = { ...updated[jobId], status: 'completed', message: 'Job finished (status expired from server)' };
                            return updated;
                        });
                        fetchApiSpecs(0);
                        fetchGeneratedTests(0);
                        fetchLatestRuns();
                        onComplete?.();
                    }
                }
            } catch {
                missCount++;
                if (missCount >= 5) {
                    clearInterval(interval);
                    setActiveJobs(prev => {
                        const updated = { ...prev };
                        if (updated[jobId]?.status === 'running') {
                            updated[jobId] = { ...updated[jobId], status: 'failed', message: 'Job status could not be confirmed' };
                        }
                        return updated;
                    });
                    fetchApiSpecs(0);
                    fetchGeneratedTests(0);
                    fetchLatestRuns();
                    onComplete?.();
                }
            }
        }, 3000);
        return () => clearInterval(interval);
    }, [projectId, fetchApiSpecs, fetchGeneratedTests, fetchLatestRuns]);

    pollJobRef.current = pollJob;
    const hasRunningJobs = Object.values(activeJobs).some(j => j.status === 'running');

    // ========== Effects ==========

    useEffect(() => {
        if (projectLoading || !requestedProjectId || requestedProjectId === projectId) return;
        const requestedProject = projects.find(project => project.id === requestedProjectId);
        if (requestedProject) setCurrentProject(requestedProject);
    }, [projectLoading, projectId, projects, requestedProjectId, setCurrentProject]);

    useEffect(() => {
        if (requestedTab === 'generated' || requestedTab === 'import' || requestedTab === 'history' || requestedTab === 'specs') {
            setActiveTab(requestedTab);
            setVisitedTabs(prev => { const next = new Set(prev); next.add(requestedTab); return next; });
        }
    }, [requestedTab]);

    useEffect(() => {
        if (projectLoading || !projectId) return;
        if (requestedProjectId && requestedProjectId !== projectId) return;
        fetchApiSpecs(0, false, requestedSpec || undefined);
        fetchRecentJobs();
        fetchLatestRuns();
    }, [projectId, projectLoading, requestedProjectId, requestedSpec, fetchApiSpecs, fetchRecentJobs, fetchLatestRuns]);

    useEffect(() => {
        if (!hasRunningJobs) return;
        const interval = setInterval(fetchRecentJobs, 5000);
        return () => clearInterval(interval);
    }, [fetchRecentJobs, hasRunningJobs]);

    useEffect(() => {
        function handleApiTestingRefresh(event: Event) {
            const detail = (event as CustomEvent<{
                projectId?: string;
                specName?: string;
                testPath?: string;
            }>).detail || {};
            if (detail.projectId && detail.projectId !== projectId) return;
            if (detail.specName) setActiveTab('specs');
            fetchApiSpecs(0, false, detail.specName || requestedSpec || undefined);
            fetchRecentJobs();
            fetchLatestRuns();
            fetchGeneratedTests(0, false, detail.testPath || undefined);
        }

        window.addEventListener('quorvex:api-testing-refresh', handleApiTestingRefresh);
        return () => window.removeEventListener('quorvex:api-testing-refresh', handleApiTestingRefresh);
    }, [projectId, requestedSpec, fetchApiSpecs, fetchGeneratedTests, fetchLatestRuns, fetchRecentJobs]);

    useEffect(() => {
        setGeneratedTests([]);
        setGeneratedTestsSummary(null);
        setTestsTotal(0);
        setTestsHasMore(false);
        setTestsOffset(0);
        setTestsLoaded(false);
        setTestsLoading(false);
        setTestsRefreshing(false);
        setExpandedTest(null);
    }, [projectId]);

    useEffect(() => {
        if (activeTab === 'generated' && !testsLoaded && !testsLoading) {
            fetchGeneratedTests(0);
        }
    }, [activeTab, testsLoaded, testsLoading, fetchGeneratedTests]);

    useEffect(() => { if (activeTab === 'history') fetchApiRuns(0); }, [activeTab, fetchApiRuns]);

    // Track visited tabs
    useEffect(() => {
        setVisitedTabs(prev => { const next = new Set(prev); next.add(activeTab); return next; });
    }, [activeTab]);

    const navigateToTest = useCallback((testName: string) => {
        setActiveTab('generated');
        setExpandedTest(testName);
    }, []);

    const handleRetryRun = useCallback(async (runId: string) => {
        if (!projectId) return;
        try {
            const res = await fetch(`${API_BASE}${withProjectQuery(`/api-testing/runs/${runId}/retry`, projectId)}`, { method: 'POST' });
            if (res.ok) {
                const data = await res.json();
                setActiveJobs(prev => ({ ...prev, [data.job_id]: { job_id: data.job_id, status: 'running', message: data.message } }));
                pollJob(data.job_id, () => { fetchApiRuns(0); });
                setDetailRunId(null);
                setMessage({ type: 'success', text: `Retry started for run ${runId}` });
            } else {
                const err = await res.json();
                setMessage({ type: 'error', text: err.detail || 'Failed to retry' });
            }
        } catch {
            setMessage({ type: 'error', text: 'Failed to start retry' });
        }
    }, [projectId, pollJob, fetchApiRuns]);

    // ========== Tab Styles ==========

    const tabs = useMemo(() => [
        { key: 'specs' as TabType, label: 'API Specs', icon: FileCode, count: specsTotal },
        { key: 'generated' as TabType, label: 'Generated Tests', icon: Play, count: testsTotal },
        { key: 'import' as TabType, label: 'OpenAPI Import', icon: Upload },
        { key: 'history' as TabType, label: 'Run History', icon: Clock },
    ], [specsTotal, testsTotal]);

    // ========== Render ==========

    return (
        <PageLayout tier="wide">
            <PageHeader
                title="API Testing"
                subtitle="Create, manage, run, and auto-heal Playwright API tests."
                icon={<Zap size={20} />}
                actions={hasRunningJobs ? (
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', color: 'var(--primary)' }}>
                        <Loader2 size={16} className="animate-spin" style={{ animation: 'spin 1s linear infinite' }} />
                        <span style={{ fontSize: '0.875rem' }}>Jobs running...</span>
                    </div>
                ) : undefined}
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

            {/* Tabs */}
            <div className="animate-in stagger-2" style={{ display: 'flex', gap: '0', borderBottom: '1px solid var(--border)', marginBottom: '1.5rem' }}>
                {tabs.map(tab => (
                    <button
                        key={tab.key}
                        onClick={() => setActiveTab(tab.key)}
                        style={{
                            ...createTabStyle(activeTab, tab.key),
                            display: 'flex', alignItems: 'center', gap: '0.5rem',
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

            {/* Tab Content */}
            {activeTab === 'specs' && (
                <SpecsPanel
                    projectId={projectId}
                    apiSpecs={apiSpecs}
                    specsLoading={specsLoading}
                    activeJobs={activeJobs}
                    specJobMap={specJobMap}
                    latestRuns={latestRuns}
                    message={message}
                    setMessage={setMessage}
                    setActiveJobs={setActiveJobs}
                    setSpecJobMap={setSpecJobMap}
                    fetchApiSpecs={fetchApiSpecs}
                    fetchGeneratedTests={fetchGeneratedTests}
                    fetchLatestRuns={fetchLatestRuns}
                    pollJob={pollJob}
                    navigateToTest={navigateToTest}
                    showCreateModal={showCreateModal}
                    setShowCreateModal={setShowCreateModal}
                    specsTotal={specsTotal}
                    specsHasMore={specsHasMore}
                    folders={specsFolders}
                    summary={specsSummary}
                    initialSearch={requestedSpec}
                />
            )}

            {activeTab === 'generated' && visitedTabs.has('generated') && (
                <GeneratedTestsList
                    generatedTests={generatedTests}
                    testsLoading={testsLoading}
                    testsRefreshing={testsRefreshing}
                    fetchGeneratedTests={fetchGeneratedTests}
                    expandedTest={expandedTest}
                    setExpandedTest={setExpandedTest}
                    setMessage={setMessage}
                    testsTotal={testsTotal}
                    testsHasMore={testsHasMore}
                    summary={generatedTestsSummary}
                    projectId={projectId}
                    activeJobs={activeJobs}
                    setActiveJobs={setActiveJobs}
                    pollJob={pollJob}
                    fetchApiRuns={fetchApiRuns}
                />
            )}

            {activeTab === 'import' && visitedTabs.has('import') && (
                <OpenApiImportPanel
                    projectId={projectId}
                    activeJobs={activeJobs}
                    setActiveJobs={setActiveJobs}
                    setMessage={setMessage}
                    pollJob={pollJob}
                />
            )}

            {activeTab === 'history' && visitedTabs.has('history') && (
                <HistoryPanel
                    apiRuns={apiRuns}
                    runsLoading={runsLoading}
                    runsHasMore={runsHasMore}
                    runsOffset={runsOffset}
                    expandedRunId={expandedRunId}
                    setExpandedRunId={setExpandedRunId}
                    fetchApiRuns={fetchApiRuns}
                    setRunsOffset={setRunsOffset}
                    RUNS_PAGE_SIZE={RUNS_PAGE_SIZE}
                    runsTotal={runsTotal}
                    onViewDetail={(runId) => setDetailRunId(runId)}
                    onRetry={(runId) => handleRetryRun(runId)}
                />
            )}

            {detailRunId && (
                <ApiRunDetailModal
                    runId={detailRunId}
                    projectId={projectId}
                    onClose={() => setDetailRunId(null)}
                    onRetry={(jobId) => {
                        setActiveJobs(prev => ({ ...prev, [jobId]: { job_id: jobId, status: 'running', message: 'Retrying...' } }));
                        pollJob(jobId, () => { fetchApiRuns(0); });
                        setDetailRunId(null);
                    }}
                />
            )}

            {/* CSS for spin animation */}
            <style jsx global>{`
                @keyframes spin {
                    from { transform: rotate(0deg); }
                    to { transform: rotate(360deg); }
                }
            `}</style>
        </PageLayout>
    );
}
