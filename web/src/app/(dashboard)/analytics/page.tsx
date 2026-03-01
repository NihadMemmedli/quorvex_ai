'use client';
import React, { useState } from 'react';
import { TrendingUp, BarChart3, AlertTriangle, XCircle } from 'lucide-react';
import { useProject } from '@/contexts/ProjectContext';
import { createTabStyle } from '@/lib/styles';
import { WorkflowBreadcrumb } from '@/components/workflow/WorkflowBreadcrumb';
import { PageLayout } from '@/components/ui/page-layout';
import { PageHeader } from '@/components/ui/page-header';
import { OverviewTab } from './components/OverviewTab';
import { TrendsTab } from './components/TrendsTab';
import { FlakeDetectionTab } from './components/FlakeDetectionTab';
import { FailuresTab } from './components/FailuresTab';

export default function AnalyticsPage() {
    const { currentProject } = useProject();
    const [activeTab, setActiveTab] = useState('overview');
    const [period, setPeriod] = useState('30d');
    const [testType, setTestType] = useState('all');

    const tabs = [
        { id: 'overview', label: 'Overview', icon: BarChart3 },
        { id: 'trends', label: 'Trends', icon: TrendingUp },
        { id: 'flake-detection', label: 'Flake Detection', icon: AlertTriangle },
        { id: 'failures', label: 'Failures', icon: XCircle },
    ];

    return (
        <PageLayout tier="wide">
            <WorkflowBreadcrumb />
            <PageHeader
                title="Test Analytics"
                subtitle="Reliability insights, flake detection, and failure analysis"
                icon={<BarChart3 size={20} />}
            />

            {/* Tab Navigation */}
            <div className="animate-in stagger-2" style={{ display: 'flex', borderBottom: '1px solid var(--border)', marginBottom: '1.5rem', gap: '0.5rem' }}>
                {tabs.map(tab => (
                    <button
                        key={tab.id}
                        onClick={() => setActiveTab(tab.id)}
                        style={{
                            ...createTabStyle(activeTab, tab.id),
                            display: 'flex',
                            alignItems: 'center',
                            gap: '0.5rem',
                        }}
                    >
                        <tab.icon size={16} />
                        {tab.label}
                    </button>
                ))}
            </div>

            {/* Period selector for Trends and Failures */}
            {(activeTab === 'trends' || activeTab === 'failures') && (
                <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '1.5rem' }}>
                    {['7d', '30d', '90d'].map(p => (
                        <button
                            key={p}
                            onClick={() => setPeriod(p)}
                            style={{
                                padding: '0.4rem 1rem',
                                borderRadius: 'var(--radius)',
                                border: '1px solid var(--border)',
                                background: period === p ? 'var(--primary)' : 'var(--surface)',
                                color: period === p ? '#fff' : 'var(--text-secondary)',
                                cursor: 'pointer',
                                fontSize: '0.85rem',
                                fontWeight: 500,
                                transition: 'all 0.2s var(--ease-smooth)',
                            }}
                        >
                            {p}
                        </button>
                    ))}
                </div>
            )}

            {/* Tab Content */}
            {activeTab === 'overview' && <OverviewTab projectId={currentProject?.id} />}
            {activeTab === 'trends' && (
                <TrendsTab projectId={currentProject?.id} period={period} testType={testType} setTestType={setTestType} />
            )}
            {activeTab === 'flake-detection' && <FlakeDetectionTab projectId={currentProject?.id} />}
            {activeTab === 'failures' && <FailuresTab projectId={currentProject?.id} period={period} />}
        </PageLayout>
    );
}
