'use client';
import React, { useState, useEffect, useCallback } from 'react';
import {
    Database, Server, Search, FileCode, Clock, BarChart2, CheckCircle2, Circle, ArrowRight, Table2,
} from 'lucide-react';
import { useRouter, useSearchParams } from 'next/navigation';
import { PageLayout } from '@/components/ui/page-layout';
import { PageHeader } from '@/components/ui/page-header';
import { useRequiredProject } from '@/contexts/ProjectContext';
import { useProjectRole } from '@/hooks/useProjectRole';
import { createTabStyle } from '@/lib/styles';
import { getAuthHeaders } from '@/lib/styles';
import { API_BASE, withProjectQuery } from '@/lib/api';

import ConnectionsTab from './components/ConnectionsTab';
import DbViewerTab from './components/DbViewerTab';
import AnalyzerTab from './components/AnalyzerTab';
import SpecsTab from './components/SpecsTab';
import HistoryTab from './components/HistoryTab';
import DashboardTab from './components/DashboardTab';

import type { DbConnection, DbSpec, DbTestRun, TabType } from './components/types';

export default function DatabaseTestingPage() {
    const { projectId } = useRequiredProject();
    const { canEdit } = useProjectRole(projectId);
    const router = useRouter();
    const searchParams = useSearchParams();

    const initialTab = (searchParams.get('tab') || 'connections') as TabType;
    const normalizedInitialTab = (
        ['connections', 'viewer', 'analyzer', 'specs', 'history', 'dashboard'].includes(initialTab) ? initialTab : 'connections'
    ) as TabType;
    const [activeTab, setActiveTab] = useState<TabType>(normalizedInitialTab);
    const [visited, setVisited] = useState<Set<TabType>>(new Set(['connections', normalizedInitialTab]));
    const [selectedConnectionId, setSelectedConnectionId] = useState(searchParams.get('connection') || '');
    const [selectedTableName, setSelectedTableName] = useState(searchParams.get('table') || '');

    // Shared data state
    const [connections, setConnections] = useState<DbConnection[]>([]);
    const [specs, setSpecs] = useState<DbSpec[]>([]);
    const [runs, setRuns] = useState<DbTestRun[]>([]);

    const preferredConnectionId = connections.find(c => c.id === 'dbc-demo-shop')?.id || connections[0]?.id;

    // Track visited tabs
    const updateUrlState = useCallback((updates: Record<string, string | null>) => {
        const next = new URLSearchParams(searchParams.toString());
        Object.entries(updates).forEach(([key, value]) => {
            if (value) next.set(key, value);
            else next.delete(key);
        });
        router.replace(`/database-testing?${next.toString()}`, { scroll: false });
    }, [router, searchParams]);

    const handleTabChange = useCallback((tab: TabType) => {
        setActiveTab(tab);
        updateUrlState({ tab });
        setVisited(prev => {
            if (prev.has(tab)) return prev;
            const next = new Set(prev);
            next.add(tab);
            return next;
        });
    }, [updateUrlState]);

    const handleConnectionSelect = useCallback((connectionId: string) => {
        setSelectedConnectionId(connectionId);
        updateUrlState({ connection: connectionId || null });
    }, [updateUrlState]);

    const handleTableSelect = useCallback((tableName: string) => {
        setSelectedTableName(tableName);
        updateUrlState({ table: tableName || null });
    }, [updateUrlState]);

    useEffect(() => {
        const tab = searchParams.get('tab') as TabType | null;
        if (tab && ['connections', 'viewer', 'analyzer', 'specs', 'history', 'dashboard'].includes(tab) && tab !== activeTab) {
            setActiveTab(tab);
            setVisited(prev => new Set([...prev, tab]));
        }
    }, [activeTab, searchParams]);

    // ========== Data Fetching ==========

    const fetchConnections = useCallback(async () => {
        try {
            const res = await fetch(`${API_BASE}${withProjectQuery('/database-testing/connections', projectId)}`, {
                headers: getAuthHeaders(),
            });
            if (res.ok) {
                const data = await res.json();
                setConnections(Array.isArray(data) ? data : data.connections || []);
            }
        } catch (e) { console.error('Failed to fetch connections:', e); }
    }, [projectId]);

    const fetchSpecs = useCallback(async () => {
        try {
            const res = await fetch(`${API_BASE}${withProjectQuery('/database-testing/specs', projectId)}`, {
                headers: getAuthHeaders(),
            });
            if (res.ok) {
                const data = await res.json();
                setSpecs(Array.isArray(data) ? data : data.specs || []);
            }
        } catch (e) { console.error('Failed to fetch specs:', e); }
    }, [projectId]);

    const fetchRuns = useCallback(async () => {
        try {
            const res = await fetch(`${API_BASE}${withProjectQuery('/database-testing/runs?limit=50', projectId)}`, {
                headers: getAuthHeaders(),
            });
            if (res.ok) {
                const data = await res.json();
                setRuns(Array.isArray(data) ? data : data.runs || []);
            }
        } catch (e) { console.error('Failed to fetch runs:', e); }
    }, [projectId]);

    // Refresh on tab or project change
    useEffect(() => {
        if (activeTab === 'connections') fetchConnections();
        if (activeTab === 'viewer') fetchConnections();
        if (activeTab === 'analyzer') fetchConnections();
        if (activeTab === 'specs') { fetchSpecs(); fetchConnections(); }
        if (activeTab === 'history') fetchRuns();
        if (activeTab === 'dashboard') { fetchConnections(); fetchRuns(); }
    }, [activeTab, projectId, fetchConnections, fetchSpecs, fetchRuns]);

    useEffect(() => {
        fetchConnections();
        fetchSpecs();
        fetchRuns();
    }, [projectId, fetchConnections, fetchSpecs, fetchRuns]);

    useEffect(() => {
        function handleDatabaseRefresh(event: Event) {
            const detail = (event as CustomEvent).detail || {};
            if (detail.projectId && detail.projectId !== projectId) return;
            fetchConnections();
            fetchSpecs();
            fetchRuns();
            if (detail.specName) handleTabChange('specs');
            else if (detail.runId) handleTabChange('history');
        }
        window.addEventListener('quorvex:database-refresh', handleDatabaseRefresh);
        return () => window.removeEventListener('quorvex:database-refresh', handleDatabaseRefresh);
    }, [fetchConnections, fetchRuns, fetchSpecs, handleTabChange, projectId]);

    const workflowSteps = [
        {
            label: 'Connection',
            detail: connections.length > 0 ? `${connections.length} ready` : 'Add or seed a database',
            done: connections.length > 0,
            tab: 'connections' as TabType,
            action: connections.length > 0 ? 'View' : 'Add',
        },
        {
            label: 'View DB',
            detail: connections.length > 0 ? 'Browse schema and query safely' : 'Add a connection first',
            done: connections.length > 0,
            tab: 'viewer' as TabType,
            action: 'Open',
        },
        {
            label: 'Analyze',
            detail: runs.some(r => r.run_type === 'schema_analysis') ? 'Schema run available' : 'Inspect schema health',
            done: runs.some(r => r.run_type === 'schema_analysis'),
            tab: 'analyzer' as TabType,
            action: 'Analyze',
        },
        {
            label: 'Run checks',
            detail: specs.length > 0 ? `${specs.length} spec${specs.length === 1 ? '' : 's'} ready` : 'Create or generate specs',
            done: specs.length > 0 && runs.some(r => r.run_type !== 'schema_analysis'),
            tab: 'specs' as TabType,
            action: specs.length > 0 ? 'Run' : 'Create',
        },
        {
            label: 'Review',
            detail: runs.length > 0 ? `${runs.length} run${runs.length === 1 ? '' : 's'} recorded` : 'Review failures and samples',
            done: runs.length > 0,
            tab: runs.length > 0 ? 'history' as TabType : 'dashboard' as TabType,
            action: runs.length > 0 ? 'Open' : 'Dashboard',
        },
    ];

    return (
        <PageLayout tier="wide">
            <PageHeader
                title="Database Testing"
                subtitle="Analyze schemas, generate data quality checks, and validate database integrity."
                icon={<Database size={20} />}
            />

            <div className="animate-in stagger-1" style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(5, minmax(0, 1fr))',
                gap: '0.75rem',
                marginBottom: '1.25rem',
            }}>
                {workflowSteps.map((step, index) => (
                    <button
                        key={step.label}
                        onClick={() => handleTabChange(step.tab)}
                        style={{
                            border: '1px solid var(--border)',
                            background: activeTab === step.tab ? 'rgba(59, 130, 246, 0.10)' : 'var(--surface)',
                            color: 'var(--text-primary)',
                            borderRadius: 'var(--radius)',
                            padding: '0.85rem 1rem',
                            display: 'flex',
                            alignItems: 'center',
                            gap: '0.75rem',
                            textAlign: 'left',
                            cursor: 'pointer',
                            minHeight: '78px',
                        }}
                    >
                        <span style={{
                            width: '28px',
                            height: '28px',
                            borderRadius: '50%',
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            background: step.done ? 'rgba(16, 185, 129, 0.14)' : 'rgba(148, 163, 184, 0.12)',
                            color: step.done ? 'var(--success)' : 'var(--text-secondary)',
                            flexShrink: 0,
                        }}>
                            {step.done ? <CheckCircle2 size={16} /> : <Circle size={16} />}
                        </span>
                        <span style={{ flex: 1, minWidth: 0 }}>
                            <span style={{ display: 'block', fontSize: '0.75rem', color: 'var(--text-secondary)', marginBottom: '0.2rem' }}>
                                Step {index + 1}
                            </span>
                            <span style={{ display: 'block', fontSize: '0.9rem', fontWeight: 600 }}>
                                {step.label}
                            </span>
                            <span style={{ display: 'block', fontSize: '0.75rem', color: 'var(--text-secondary)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                                {step.detail}
                            </span>
                        </span>
                        <span style={{ display: 'flex', alignItems: 'center', gap: '0.25rem', fontSize: '0.78rem', color: 'var(--primary-hover)', flexShrink: 0 }}>
                            {step.action}
                            <ArrowRight size={13} />
                        </span>
                    </button>
                ))}
            </div>

            {/* Tabs */}
            <div className="animate-in stagger-2" style={{ display: 'flex', borderBottom: '1px solid var(--border)', marginBottom: '1.5rem' }}>
                <button onClick={() => handleTabChange('connections')} style={createTabStyle(activeTab, 'connections')}>
                    <span style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                        <Server size={16} /> Connections
                    </span>
                </button>
                <button onClick={() => handleTabChange('viewer')} style={createTabStyle(activeTab, 'viewer')}>
                    <span style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                        <Table2 size={16} /> Viewer
                    </span>
                </button>
                <button onClick={() => handleTabChange('analyzer')} style={createTabStyle(activeTab, 'analyzer')}>
                    <span style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                        <Search size={16} /> Analyzer
                    </span>
                </button>
                <button onClick={() => handleTabChange('specs')} style={createTabStyle(activeTab, 'specs')}>
                    <span style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                        <FileCode size={16} /> Specs
                    </span>
                </button>
                <button onClick={() => handleTabChange('history')} style={createTabStyle(activeTab, 'history')}>
                    <span style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                        <Clock size={16} /> History
                    </span>
                </button>
                <button onClick={() => handleTabChange('dashboard')} style={createTabStyle(activeTab, 'dashboard')}>
                    <span style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                        <BarChart2 size={16} /> Dashboard
                    </span>
                </button>
            </div>

            {/* Tab Content */}
            {activeTab === 'connections' && visited.has('connections') && (
                <ConnectionsTab
                    connections={connections}
                    projectId={projectId}
                    onRefresh={fetchConnections}
                    canEdit={canEdit}
                />
            )}

            {activeTab === 'viewer' && visited.has('viewer') && (
                <DbViewerTab
                    connections={connections}
                    projectId={projectId}
                    preferredConnectionId={preferredConnectionId}
                    selectedConnectionId={selectedConnectionId}
                    selectedTableName={selectedTableName}
                    onSelectConnection={handleConnectionSelect}
                    onSelectTable={handleTableSelect}
                    canEdit={canEdit}
                />
            )}

            {activeTab === 'analyzer' && visited.has('analyzer') && (
                <AnalyzerTab
                    connections={connections}
                    projectId={projectId}
                    onSpecsSaved={fetchSpecs}
                    preferredConnectionId={preferredConnectionId}
                    initialRunId={searchParams.get('runId') || undefined}
                    canEdit={canEdit}
                />
            )}

            {activeTab === 'specs' && visited.has('specs') && (
                <SpecsTab
                    specs={specs}
                    connections={connections}
                    projectId={projectId}
                    onRefreshSpecs={fetchSpecs}
                    onRefreshRuns={fetchRuns}
                    preferredConnectionId={preferredConnectionId}
                    initialSpecName={searchParams.get('specName') || undefined}
                    canEdit={canEdit}
                />
            )}

            {activeTab === 'history' && visited.has('history') && (
                <HistoryTab
                    runs={runs}
                    projectId={projectId}
                    onRefreshRuns={fetchRuns}
                    initialRunId={searchParams.get('runId') || undefined}
                />
            )}

            {activeTab === 'dashboard' && visited.has('dashboard') && (
                <DashboardTab
                    connections={connections}
                    runs={runs}
                />
            )}

            {/* Global spinner keyframes */}
            <style>{`@keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }`}</style>
        </PageLayout>
    );
}
