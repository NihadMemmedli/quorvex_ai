'use client';
import React, { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { ShieldAlert, Play, FileCode, Clock, Bug } from 'lucide-react';
import { PageLayout } from '@/components/ui/page-layout';
import { PageHeader } from '@/components/ui/page-header';
import { useProject } from '@/contexts/ProjectContext';
import { API_BASE } from '@/lib/api';
import { createTabStyle, getAuthHeaders, cardStyle } from '@/lib/styles';
import { severityColor } from '@/lib/colors';
import { SecuritySpec, SecurityScanRun, JobStatus, FindingSummary, TabType } from './components/types';
import ScannerTab from './components/ScannerTab';
import SpecsTab from './components/SpecsTab';
import HistoryTab from './components/HistoryTab';
import FindingsTab from './components/FindingsTab';

export default function SecurityTestingPage() {
    const { currentProject } = useProject();
    const projectId = currentProject?.id || 'default';

    const [activeTab, setActiveTab] = useState<TabType>('scanner');
    const [visitedTabs, setVisitedTabs] = useState<Set<TabType>>(new Set(['scanner']));

    // Scanner state
    const [scanUrl, setScanUrl] = useState('');
    const [scanType, setScanType] = useState('quick');
    const [isScanning, setIsScanning] = useState(false);
    const [activeJobId, setActiveJobId] = useState<string | null>(null);
    const [jobStatus, setJobStatus] = useState<JobStatus | null>(null);

    // Specs state
    const [specs, setSpecs] = useState<SecuritySpec[]>([]);

    // History state
    const [runs, setRuns] = useState<SecurityScanRun[]>([]);

    // Findings state
    const [findingSummary, setFindingSummary] = useState<FindingSummary | null>(null);

    // Polling
    const pollRef = useRef<NodeJS.Timeout | null>(null);

    // ========== Data Fetching ==========

    const fetchSpecs = useCallback(async () => {
        try {
            const res = await fetch(`${API_BASE}/security-testing/specs?project_id=${projectId}`, { headers: getAuthHeaders() });
            if (res.ok) setSpecs(await res.json());
        } catch (e) { console.error('Failed to fetch specs:', e); }
    }, [projectId]);

    const fetchRuns = useCallback(async () => {
        try {
            const res = await fetch(`${API_BASE}/security-testing/runs?project_id=${projectId}&limit=50`, { headers: getAuthHeaders() });
            if (res.ok) { const data = await res.json(); setRuns(data.runs || []); }
        } catch (e) { console.error('Failed to fetch runs:', e); }
    }, [projectId]);

    const fetchFindingSummary = useCallback(async () => {
        try {
            const res = await fetch(`${API_BASE}/security-testing/findings/summary?project_id=${projectId}`, { headers: getAuthHeaders() });
            if (res.ok) {
                const data = await res.json();
                const bySev = data.by_severity || {};
                setFindingSummary({
                    total: data.total_open || 0,
                    critical: bySev.critical || 0, high: bySev.high || 0,
                    medium: bySev.medium || 0, low: bySev.low || 0, info: bySev.info || 0,
                    open: data.total_open || 0, false_positive: 0, fixed: 0, accepted_risk: 0,
                });
            }
        } catch (e) { console.error('Failed to fetch summary:', e); }
    }, [projectId]);

    // Refresh on tab change or project change
    useEffect(() => {
        if (activeTab === 'specs') fetchSpecs();
        if (activeTab === 'history') fetchRuns();
        if (activeTab === 'findings') { fetchFindingSummary(); fetchRuns(); }
    }, [activeTab, projectId, fetchSpecs, fetchRuns, fetchFindingSummary]);

    // Track visited tabs
    useEffect(() => {
        setVisitedTabs(prev => { const next = new Set(prev); next.add(activeTab); return next; });
    }, [activeTab]);

    // Poll active job
    useEffect(() => {
        if (!activeJobId) return;
        const poll = async () => {
            try {
                const res = await fetch(`${API_BASE}/security-testing/jobs/${activeJobId}`, { headers: getAuthHeaders() });
                if (res.ok) {
                    const data = await res.json();
                    setJobStatus(data);
                    if (data.status === 'completed' || data.status === 'failed') {
                        setIsScanning(false);
                        if (pollRef.current) clearInterval(pollRef.current);
                        pollRef.current = null;
                        fetchRuns();
                        fetchFindingSummary();
                    }
                }
            } catch (e) { console.error('Poll error:', e); }
        };
        poll();
        pollRef.current = setInterval(poll, 2000);
        return () => { if (pollRef.current) clearInterval(pollRef.current); };
    }, [activeJobId, fetchRuns, fetchFindingSummary]);

    // ========== Actions ==========

    const startScan = useCallback(async () => {
        if (!scanUrl.trim()) return;
        setIsScanning(true);
        setJobStatus(null);
        try {
            const res = await fetch(`${API_BASE}/security-testing/scan/${scanType}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
                body: JSON.stringify({ target_url: scanUrl, project_id: projectId }),
            });
            if (res.ok) {
                const data = await res.json();
                setActiveJobId(data.job_id);
            } else {
                const err = await res.json().catch(() => ({ detail: 'Scan failed' }));
                setJobStatus({ job_id: '', status: 'failed', message: err.detail });
                setIsScanning(false);
            }
        } catch (e) {
            setJobStatus({ job_id: '', status: 'failed', message: String(e) });
            setIsScanning(false);
        }
    }, [scanUrl, scanType, projectId]);

    const updateFindingStatus = useCallback(async (findingId: number, newStatus: string, notes?: string) => {
        try {
            await fetch(`${API_BASE}/security-testing/findings/${findingId}/status`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
                body: JSON.stringify({ status: newStatus, notes }),
            });
            fetchFindingSummary();
        } catch (e) { console.error('Update finding status failed:', e); }
    }, [fetchFindingSummary]);

    // ========== Render ==========

    return (
        <PageLayout tier="wide">
            <PageHeader
                title="Security Testing"
                subtitle="Scan for vulnerabilities, misconfigurations, and security issues."
                icon={<ShieldAlert size={20} />}
            />

            {/* Summary Cards */}
            {findingSummary && (
                <div className="animate-in stagger-2" style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: '1rem', marginBottom: '1.5rem' }}>
                    {(['critical', 'high', 'medium', 'low', 'info'] as const).map(sev => (
                        <div key={sev} style={{
                            ...cardStyle, padding: '1rem', textAlign: 'center',
                            borderLeft: `3px solid ${severityColor(sev)}`,
                            boxShadow: 'var(--shadow-card)',
                            transition: 'all 0.15s var(--ease-smooth)',
                        }}>
                            <div style={{ fontSize: '1.5rem', fontWeight: 700, color: severityColor(sev) }}>
                                {findingSummary[sev]}
                            </div>
                            <div style={{ fontSize: '0.75rem', color: 'var(--text-tertiary)', textTransform: 'uppercase' }}>
                                {sev}
                            </div>
                        </div>
                    ))}
                </div>
            )}

            {/* Tabs */}
            <div className="animate-in stagger-3" style={{ display: 'flex', borderBottom: '1px solid var(--border)', marginBottom: '1.5rem' }}>
                <button onClick={() => setActiveTab('scanner')} style={createTabStyle(activeTab, 'scanner')}>
                    <span style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                        <Play size={16} /> Scanner
                    </span>
                </button>
                <button onClick={() => setActiveTab('specs')} style={createTabStyle(activeTab, 'specs')}>
                    <span style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                        <FileCode size={16} /> Specs
                    </span>
                </button>
                <button onClick={() => setActiveTab('history')} style={createTabStyle(activeTab, 'history')}>
                    <span style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                        <Clock size={16} /> History
                    </span>
                </button>
                <button onClick={() => setActiveTab('findings')} style={createTabStyle(activeTab, 'findings')}>
                    <span style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                        <Bug size={16} /> Findings
                        {findingSummary && findingSummary.total > 0 && (
                            <span style={{
                                background: 'var(--primary)', color: 'white',
                                borderRadius: '9999px', padding: '0 6px', fontSize: '0.7rem',
                            }}>{findingSummary.total}</span>
                        )}
                    </span>
                </button>
            </div>

            {/* Tab Content */}
            {activeTab === 'scanner' && (
                <ScannerTab
                    scanUrl={scanUrl}
                    setScanUrl={setScanUrl}
                    scanType={scanType}
                    setScanType={setScanType}
                    isScanning={isScanning}
                    jobStatus={jobStatus}
                    onStartScan={startScan}
                />
            )}

            {activeTab === 'specs' && visitedTabs.has('specs') && (
                <SpecsTab
                    projectId={projectId}
                    specs={specs}
                    fetchSpecs={fetchSpecs}
                />
            )}

            {activeTab === 'history' && visitedTabs.has('history') && (
                <HistoryTab
                    runs={runs}
                    fetchRuns={fetchRuns}
                    onStatusChange={updateFindingStatus}
                />
            )}

            {activeTab === 'findings' && visitedTabs.has('findings') && (
                <FindingsTab
                    runs={runs}
                    onStatusChange={updateFindingStatus}
                />
            )}
        </PageLayout>
    );
}
