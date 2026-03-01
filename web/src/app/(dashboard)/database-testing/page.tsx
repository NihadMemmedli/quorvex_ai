'use client';
import React, { useState, useEffect, useCallback } from 'react';
import {
    Database, Server, Search, FileCode, Clock, BarChart2,
} from 'lucide-react';
import { PageLayout } from '@/components/ui/page-layout';
import { PageHeader } from '@/components/ui/page-header';
import { useProject } from '@/contexts/ProjectContext';
import { createTabStyle } from '@/lib/styles';
import { getAuthHeaders } from '@/lib/styles';
import { API_BASE } from '@/lib/api';

import ConnectionsTab from './components/ConnectionsTab';
import AnalyzerTab from './components/AnalyzerTab';
import SpecsTab from './components/SpecsTab';
import HistoryTab from './components/HistoryTab';
import DashboardTab from './components/DashboardTab';

import type { DbConnection, DbSpec, DbTestRun, TabType } from './components/types';

export default function DatabaseTestingPage() {
    const { currentProject } = useProject();
    const projectId = currentProject?.id || 'default';

    const [activeTab, setActiveTab] = useState<TabType>('connections');
    const [visited, setVisited] = useState<Set<TabType>>(new Set(['connections']));

    // Shared data state
    const [connections, setConnections] = useState<DbConnection[]>([]);
    const [specs, setSpecs] = useState<DbSpec[]>([]);
    const [runs, setRuns] = useState<DbTestRun[]>([]);

    // Track visited tabs
    const handleTabChange = useCallback((tab: TabType) => {
        setActiveTab(tab);
        setVisited(prev => {
            if (prev.has(tab)) return prev;
            const next = new Set(prev);
            next.add(tab);
            return next;
        });
    }, []);

    // ========== Data Fetching ==========

    const fetchConnections = useCallback(async () => {
        try {
            const res = await fetch(`${API_BASE}/database-testing/connections?project_id=${projectId}`, {
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
            const res = await fetch(`${API_BASE}/database-testing/specs?project_id=${projectId}`, {
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
            const res = await fetch(`${API_BASE}/database-testing/runs?project_id=${projectId}&limit=50`, {
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
        if (activeTab === 'analyzer') fetchConnections();
        if (activeTab === 'specs') { fetchSpecs(); fetchConnections(); }
        if (activeTab === 'history') fetchRuns();
        if (activeTab === 'dashboard') { fetchConnections(); fetchRuns(); }
    }, [activeTab, projectId, fetchConnections, fetchSpecs, fetchRuns]);

    return (
        <PageLayout tier="wide">
            <PageHeader
                title="Database Testing"
                subtitle="Analyze schemas, generate data quality checks, and validate database integrity."
                icon={<Database size={20} />}
            />

            {/* Tabs */}
            <div className="animate-in stagger-2" style={{ display: 'flex', borderBottom: '1px solid var(--border)', marginBottom: '1.5rem' }}>
                <button onClick={() => handleTabChange('connections')} style={createTabStyle(activeTab, 'connections')}>
                    <span style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                        <Server size={16} /> Connections
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
                />
            )}

            {activeTab === 'analyzer' && visited.has('analyzer') && (
                <AnalyzerTab
                    connections={connections}
                    projectId={projectId}
                    onSpecsSaved={fetchSpecs}
                />
            )}

            {activeTab === 'specs' && visited.has('specs') && (
                <SpecsTab
                    specs={specs}
                    connections={connections}
                    projectId={projectId}
                    onRefreshSpecs={fetchSpecs}
                    onRefreshRuns={fetchRuns}
                />
            )}

            {activeTab === 'history' && visited.has('history') && (
                <HistoryTab
                    runs={runs}
                    onRefreshRuns={fetchRuns}
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
