'use client';
import { useState, useEffect } from 'react';
import { useProject } from '@/contexts/ProjectContext';
import { PageLayout } from '@/components/ui/page-layout';
import { PageHeader } from '@/components/ui/page-header';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Server, FileText, Database, Play, GitCompare, History, TrendingUp, MessageSquare, Clock } from 'lucide-react';

import ProvidersTab from './components/ProvidersTab';
import SpecsTab from './components/SpecsTab';
import DatasetsTab from './components/DatasetsTab';
import RunTab from './components/RunTab';
import CompareTab from './components/CompareTab';
import HistoryTab from './components/HistoryTab';
import AnalyticsTab from './components/AnalyticsTab';
import PromptsTab from './components/PromptsTab';
import SchedulesTab from './components/SchedulesTab';

type Tab = 'providers' | 'specs' | 'datasets' | 'run' | 'compare' | 'history' | 'analytics' | 'prompts' | 'schedules';

const tabs: { key: Tab; label: string; icon: React.ReactNode }[] = [
    { key: 'providers', label: 'Providers', icon: <Server size={16} /> },
    { key: 'specs', label: 'Specs', icon: <FileText size={16} /> },
    { key: 'datasets', label: 'Datasets', icon: <Database size={16} /> },
    { key: 'run', label: 'Run', icon: <Play size={16} /> },
    { key: 'compare', label: 'Compare', icon: <GitCompare size={16} /> },
    { key: 'history', label: 'History', icon: <History size={16} /> },
    { key: 'analytics', label: 'Analytics', icon: <TrendingUp size={16} /> },
    { key: 'prompts', label: 'Prompts', icon: <MessageSquare size={16} /> },
    { key: 'schedules', label: 'Schedules', icon: <Clock size={16} /> },
];

export default function LlmTestingPage() {
    const { currentProject } = useProject();
    const projectId = currentProject?.id || 'default';
    const [tab, setTab] = useState<Tab>('providers');
    const [visited, setVisited] = useState<Set<Tab>>(new Set(['providers']));

    useEffect(() => {
        setVisited(prev => {
            if (prev.has(tab)) return prev;
            return new Set([...prev, tab]);
        });
    }, [tab]);

    return (
        <PageLayout tier="wide">
            <PageHeader
                title="LLM / AI Testing"
                subtitle="Evaluate external LLM-powered applications for quality, safety, correctness, and performance."
            />

            <Tabs value={tab} onValueChange={(v) => setTab(v as Tab)}>
                <TabsList style={{
                    background: 'transparent',
                    borderRadius: 0,
                    borderBottom: '1px solid var(--border)',
                    padding: 0,
                    width: '100%',
                    display: 'flex',
                    gap: '0.25rem',
                    marginBottom: '1.5rem',
                }}>
                    {tabs.map(t => (
                        <TabsTrigger
                            key={t.key}
                            value={t.key}
                            style={{
                                background: 'transparent',
                                borderRadius: 0,
                                borderBottom: tab === t.key ? '2px solid var(--primary)' : '2px solid transparent',
                                color: tab === t.key ? 'var(--text)' : 'var(--text-secondary)',
                                fontWeight: tab === t.key ? 600 : 400,
                                padding: '0.75rem 1.5rem',
                                display: 'flex',
                                alignItems: 'center',
                                gap: '0.5rem',
                                fontSize: '0.9rem',
                                transition: 'all 0.2s var(--ease-smooth)',
                            }}
                        >
                            {t.icon}
                            {t.label}
                        </TabsTrigger>
                    ))}
                </TabsList>
            </Tabs>

            {visited.has('providers') && <div style={{ display: tab === 'providers' ? 'block' : 'none' }}><ProvidersTab projectId={projectId} /></div>}
            {visited.has('specs') && <div style={{ display: tab === 'specs' ? 'block' : 'none' }}><SpecsTab projectId={projectId} /></div>}
            {visited.has('datasets') && <div style={{ display: tab === 'datasets' ? 'block' : 'none' }}><DatasetsTab projectId={projectId} /></div>}
            {visited.has('run') && <div style={{ display: tab === 'run' ? 'block' : 'none' }}><RunTab projectId={projectId} /></div>}
            {visited.has('compare') && <div style={{ display: tab === 'compare' ? 'block' : 'none' }}><CompareTab projectId={projectId} /></div>}
            {visited.has('history') && <div style={{ display: tab === 'history' ? 'block' : 'none' }}><HistoryTab projectId={projectId} /></div>}
            {visited.has('analytics') && <div style={{ display: tab === 'analytics' ? 'block' : 'none' }}><AnalyticsTab projectId={projectId} /></div>}
            {visited.has('prompts') && <div style={{ display: tab === 'prompts' ? 'block' : 'none' }}><PromptsTab projectId={projectId} /></div>}
            {visited.has('schedules') && <div style={{ display: tab === 'schedules' ? 'block' : 'none' }}><SchedulesTab projectId={projectId} /></div>}
        </PageLayout>
    );
}
