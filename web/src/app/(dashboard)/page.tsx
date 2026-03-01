'use client';
import { useState, useEffect } from 'react';
import Link from 'next/link';
import {
    AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer
} from 'recharts';
import {
    Clock, Wrench, AlertTriangle, TrendingUp,
    Plus, PlayCircle, CheckCircle2, Zap, Timer, ArrowRight,
    Compass, BarChart2
} from 'lucide-react';
import { useProject } from '@/contexts/ProjectContext';
import { API_BASE } from '@/lib/api';
import { toast } from 'sonner';
import { WorkflowPipeline } from '@/components/workflow/WorkflowPipeline';
import { useWorkflowProgress } from '@/hooks/useWorkflowProgress';
import type { HealthStatus } from '@/components/workflow/WorkflowPipeline';
import { PageLayout } from '@/components/ui/page-layout';
import { PageHeader } from '@/components/ui/page-header';

interface FlakyTest {
    spec_name: string;
    passed: number;
    failed: number;
    total: number;
    flakiness_rate: number;
}

interface SlowestTest {
    spec_name: string;
    avg_duration: number;
    run_count: number;
    max_duration: number;
}

interface HealingStats {
    overall: {
        total_heals_attempted: number;
        total_heals_succeeded: number;
        success_rate: number;
    };
    by_mode: Record<string, { attempted: number; succeeded: number; success_rate: number }>;
    avg_iterations_to_success: number;
    trend: Array<{ date: string; success_rate: number; attempts: number }>;
}

interface TestGrowthTrends {
    has_data: boolean;
    trend: Array<{ date: string; total_specs: number; generated_tests: number; passing_tests: number; daily_runs: number }>;
    latest: { total_specs: number; generated_tests: number; passing_tests: number } | null;
    growth: { specs: number; generated: number; passing: number };
}

interface Stats {
    total_specs: number;
    total_runs: number;
    success_rate: number;
    pass_rate: number;
    avg_duration_seconds: number;
    last_run: string;
    trends: Array<{ date: string; passed: number; failed: number }>;
    flaky_tests: FlakyTest[];
    flaky_test_count: number;
    slowest_tests: SlowestTest[];
    healing_stats: HealingStats;
    test_growth_trends: TestGrowthTrends;
    actual_total_tests?: number;
    total_test_files?: number;
}

const DEFAULT_STATS: Stats = {
    total_specs: 0,
    total_runs: 0,
    success_rate: 0,
    pass_rate: 0,
    avg_duration_seconds: 0,
    last_run: 'Never',
    trends: [],
    flaky_tests: [],
    flaky_test_count: 0,
    slowest_tests: [],
    healing_stats: {
        overall: { total_heals_attempted: 0, total_heals_succeeded: 0, success_rate: 0 },
        by_mode: {},
        avg_iterations_to_success: 0,
        trend: [],
    },
    test_growth_trends: {
        has_data: false,
        trend: [],
        latest: null,
        growth: { specs: 0, generated: 0, passing: 0 },
    },
};

function formatSpecName(rawName: string): string {
    const name = rawName.split('/').pop() || rawName;
    return name
        .replace(/\.md$/i, '')
        .replace(/^tc-\d+-/i, '')
        .replace(/-/g, ' ')
        .replace(/\b\w/g, c => c.toUpperCase());
}

function formatDuration(seconds: number): string {
    if (seconds === 0) return '—';
    if (seconds < 60) return `${Math.round(seconds)}s`;
    const mins = Math.floor(seconds / 60);
    const secs = Math.round(seconds % 60);
    return secs > 0 ? `${mins}m ${secs}s` : `${mins}m`;
}

function computeHealthStatus(
    progress: ReturnType<typeof useWorkflowProgress>['progress'],
    stats: Stats
): Record<string, HealthStatus> {
    const h: Record<string, HealthStatus> = {};
    const passRate = stats.pass_rate ?? stats.success_rate ?? 0;

    h.exploration = (progress?.explorations ?? 0) > 0 ? 'good' : 'inactive';
    h.requirements = (progress?.requirements ?? 0) > 0 ? 'good' : 'inactive';

    // RTM: red <30%, amber <60%, green >=60%
    const rtm = progress?.rtmCoverage;
    if (rtm == null || rtm === 0) {
        h.rtm = 'inactive';
    } else if (rtm < 30) {
        h.rtm = 'critical';
    } else if (rtm < 60) {
        h.rtm = 'warning';
    } else {
        h.rtm = 'good';
    }

    h.specs = (progress?.specs ?? 0) > 0 ? 'good' : 'inactive';
    h.runs = (progress?.runs ?? 0) > 0 ? 'good' : 'inactive';

    // Analytics (pass rate): red <50%, amber <70%, green >=70%
    if (stats.total_runs === 0) {
        h.analytics = 'inactive';
    } else if (passRate < 50) {
        h.analytics = 'critical';
    } else if (passRate < 70) {
        h.analytics = 'warning';
    } else {
        h.analytics = 'good';
    }

    return h;
}

/* Skeleton block for loading state */
function SkeletonBlock({ width, height, borderRadius = '8px' }: { width: string; height: string; borderRadius?: string }) {
    return (
        <div style={{
            width,
            height,
            borderRadius,
            background: 'linear-gradient(90deg, var(--surface) 25%, var(--surface-hover) 50%, var(--surface) 75%)',
            backgroundSize: '200% 100%',
            animation: 'shimmer 2s infinite',
        }} />
    );
}

function computeQuickActions(stats: Stats, progress: ReturnType<typeof useWorkflowProgress>['progress']) {
    const actions: Array<{
        label: string;
        description: string;
        href: string;
        icon: React.ReactNode;
        accentColor: string;
        urgency: number;
    }> = [];

    if (stats.total_specs === 0) {
        actions.push({ label: 'Create First Spec', description: 'Write a test using natural language', href: '/specs/new', icon: <Plus size={18} />, accentColor: '#3b82f6', urgency: 10 });
    }
    if (stats.total_runs === 0 && stats.total_specs > 0) {
        actions.push({ label: 'Run Your Tests', description: 'Execute your first test spec', href: '/specs', icon: <PlayCircle size={18} />, accentColor: '#10b981', urgency: 9 });
    }
    if (stats.flaky_test_count > 0) {
        actions.push({ label: 'Review Flaky Tests', description: `${stats.flaky_test_count} flaky test${stats.flaky_test_count > 1 ? 's' : ''} detected`, href: '/dashboard', icon: <AlertTriangle size={18} />, accentColor: '#f59e0b', urgency: 8 });
    }
    const rtmCov = progress?.rtmCoverage ?? 0;
    if (rtmCov < 30 && (progress?.requirements ?? 0) > 0) {
        actions.push({ label: 'Map Requirements', description: 'Improve traceability coverage', href: '/requirements', icon: <CheckCircle2 size={18} />, accentColor: '#8b5cf6', urgency: 7 });
    }
    if ((progress?.explorations ?? 0) === 0) {
        actions.push({ label: 'Explore Your App', description: 'AI-powered app discovery', href: '/exploration', icon: <Compass size={18} />, accentColor: '#06b6d4', urgency: 6 });
    }
    // Always available fallbacks
    actions.push({ label: 'Create New Spec', description: 'Write a test using natural language', href: '/specs/new', icon: <Plus size={18} />, accentColor: '#3b82f6', urgency: 3 });
    actions.push({ label: 'View Test Runs', description: 'Check results of recent executions', href: '/runs', icon: <PlayCircle size={18} />, accentColor: '#10b981', urgency: 2 });
    actions.push({ label: 'View Reports', description: 'Analytics and reporting dashboard', href: '/dashboard', icon: <BarChart2 size={18} />, accentColor: '#f59e0b', urgency: 1 });

    // Sort by urgency desc, take top 4, deduplicate by href
    const seen = new Set<string>();
    return actions
        .sort((a, b) => b.urgency - a.urgency)
        .filter(a => { if (seen.has(a.href)) return false; seen.add(a.href); return true; })
        .slice(0, 4);
}

export default function Home() {
    const { currentProject, isLoading: projectLoading } = useProject();
    const { progress: workflowProgress } = useWorkflowProgress();

    const [stats, setStats] = useState<Stats>(DEFAULT_STATS);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        if (projectLoading) return;

        const projectParam = currentProject?.id ? `?project_id=${encodeURIComponent(currentProject.id)}` : '';
        fetch(`${API_BASE}/dashboard${projectParam}`)
            .then(res => res.json())
            .then(data => {
                setStats({ ...DEFAULT_STATS, ...data });
                setLoading(false);
            })
            .catch(err => {
                console.error(err);
                toast.error('Failed to load dashboard data');
                setLoading(false);
            });
    }, [currentProject?.id, projectLoading]);

    if (loading || projectLoading) return (
        <PageLayout tier="standard">
            {/* Skeleton header */}
            <div style={{ marginBottom: '2rem' }}>
                <SkeletonBlock width="220px" height="32px" borderRadius="6px" />
                <div style={{ marginTop: '0.5rem' }}>
                    <SkeletonBlock width="300px" height="16px" borderRadius="4px" />
                </div>
            </div>

            {/* Skeleton pipeline */}
            <div style={{ marginBottom: '2rem' }}>
                <SkeletonBlock width="100%" height="64px" />
            </div>

            {/* Skeleton health signal cards */}
            <div style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(4, 1fr)',
                gap: '1rem',
                marginBottom: '2rem',
            }}>
                {[0, 1, 2, 3].map(i => (
                    <div key={i} className="card-elevated" style={{ padding: '1.25rem', position: 'relative' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.875rem' }}>
                            <SkeletonBlock width="40px" height="40px" borderRadius="10px" />
                            <div style={{ flex: 1 }}>
                                <SkeletonBlock width="70px" height="10px" borderRadius="4px" />
                                <div style={{ marginTop: '0.5rem' }}>
                                    <SkeletonBlock width="50px" height="24px" borderRadius="4px" />
                                </div>
                            </div>
                        </div>
                    </div>
                ))}
            </div>

            {/* Skeleton chart + attention */}
            <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: '1.5rem', marginBottom: '2rem' }}>
                <div className="card-elevated" style={{ padding: '1.25rem 1.5rem', minHeight: '400px' }}>
                    <SkeletonBlock width="150px" height="18px" borderRadius="4px" />
                    <div style={{ marginTop: '1.5rem' }}>
                        <SkeletonBlock width="100%" height="300px" borderRadius="8px" />
                    </div>
                </div>
                <div className="card-elevated" style={{ padding: '1.25rem 1.5rem' }}>
                    <SkeletonBlock width="140px" height="18px" borderRadius="4px" />
                    <div style={{ marginTop: '1.25rem', display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                        {[0, 1, 2].map(i => (
                            <SkeletonBlock key={i} width="100%" height="52px" borderRadius="8px" />
                        ))}
                    </div>
                </div>
            </div>

            {/* Skeleton quick actions */}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}>
                {[0, 1].map(i => (
                    <div key={i} className="card-elevated" style={{ padding: '1.25rem', display: 'flex', alignItems: 'center', gap: '1rem' }}>
                        <SkeletonBlock width="40px" height="40px" borderRadius="10px" />
                        <div style={{ flex: 1 }}>
                            <SkeletonBlock width="120px" height="14px" borderRadius="4px" />
                            <div style={{ marginTop: '0.375rem' }}>
                                <SkeletonBlock width="200px" height="12px" borderRadius="4px" />
                            </div>
                        </div>
                    </div>
                ))}
            </div>
        </PageLayout>
    );

    const passRate = stats.pass_rate ?? stats.success_rate ?? 0;
    const healingRate = stats.healing_stats?.overall?.success_rate ?? 0;
    const healingAttempted = stats.healing_stats?.overall?.total_heals_attempted ?? 0;
    const specGrowth = stats.test_growth_trends?.growth?.specs ?? 0;
    const healthStatus = computeHealthStatus(workflowProgress, stats);

    // Build "Needs Attention" items
    const attentionItems: Array<{
        label: string;
        detail: string;
        severity: 'critical' | 'warning';
        href: string;
    }> = [];

    // Top 3 flaky tests
    if (stats.flaky_tests?.length > 0) {
        stats.flaky_tests.slice(0, 3).forEach(t => {
            attentionItems.push({
                label: formatSpecName(t.spec_name),
                detail: `${t.flakiness_rate}% flaky`,
                severity: t.flakiness_rate >= 50 ? 'critical' : 'warning',
                href: '/analytics',
            });
        });
    }

    // Top 2 slowest tests
    if (stats.slowest_tests?.length > 0) {
        stats.slowest_tests.slice(0, 2).forEach(t => {
            attentionItems.push({
                label: formatSpecName(t.spec_name),
                detail: `avg ${formatDuration(t.avg_duration)}`,
                severity: 'warning',
                href: '/analytics',
            });
        });
    }

    // Healing rate alert
    if (healingAttempted > 0 && healingRate < 80) {
        attentionItems.push({
            label: 'Low healing success rate',
            detail: `${healingRate}% (${healingAttempted} attempts)`,
            severity: healingRate < 50 ? 'critical' : 'warning',
            href: '/dashboard',
        });
    }

    // Health signal card config
    const healthCards: Array<{
        label: string;
        value: string;
        icon: React.ReactNode;
        accentColor: string;
        glowColor: string;
        gradientColors: string;
        extra?: React.ReactNode;
    }> = [
        {
            label: 'Avg Duration',
            value: formatDuration(stats.avg_duration_seconds),
            icon: <Clock size={18} style={{ color: '#8b5cf6' }} />,
            accentColor: '#8b5cf6',
            glowColor: 'rgba(139, 92, 246, 0.15)',
            gradientColors: 'linear-gradient(90deg, rgba(139, 92, 246, 0.6), rgba(139, 92, 246, 0))',
        },
        {
            label: 'Healing Rate',
            value: healingAttempted > 0 ? `${healingRate}%` : '—',
            icon: <Wrench size={18} style={{ color: '#10b981' }} />,
            accentColor: '#10b981',
            glowColor: 'rgba(16, 185, 129, 0.15)',
            gradientColors: 'linear-gradient(90deg, rgba(16, 185, 129, 0.6), rgba(16, 185, 129, 0))',
            extra: healingAttempted > 0 ? (
                <div style={{
                    flex: 1,
                    height: '4px',
                    background: 'var(--surface-hover)',
                    borderRadius: '2px',
                    overflow: 'hidden',
                    maxWidth: '60px',
                }}>
                    <div style={{
                        width: `${healingRate}%`,
                        height: '100%',
                        background: healingRate >= 80 ? '#10b981' : healingRate >= 50 ? '#f59e0b' : '#ef4444',
                        borderRadius: '2px',
                    }} />
                </div>
            ) : undefined,
        },
        {
            label: 'Flaky Tests',
            value: String(stats.flaky_test_count),
            icon: <AlertTriangle size={18} style={{ color: stats.flaky_test_count > 0 ? '#f59e0b' : '#10b981' }} />,
            accentColor: stats.flaky_test_count > 0 ? '#f59e0b' : '#10b981',
            glowColor: stats.flaky_test_count > 0 ? 'rgba(245, 158, 11, 0.15)' : 'rgba(16, 185, 129, 0.15)',
            gradientColors: stats.flaky_test_count > 0
                ? 'linear-gradient(90deg, rgba(245, 158, 11, 0.6), rgba(245, 158, 11, 0))'
                : 'linear-gradient(90deg, rgba(16, 185, 129, 0.6), rgba(16, 185, 129, 0))',
            extra: stats.flaky_test_count > 0 ? (
                <span style={{
                    fontSize: '0.6rem',
                    fontWeight: 600,
                    color: '#f59e0b',
                    background: 'rgba(245, 158, 11, 0.1)',
                    padding: '0.1rem 0.4rem',
                    borderRadius: '9999px',
                    letterSpacing: '0.02em',
                }}>
                    needs review
                </span>
            ) : undefined,
        },
        {
            label: 'Test Growth',
            value: specGrowth > 0 ? `+${specGrowth}` : specGrowth === 0 ? '—' : String(specGrowth),
            icon: <TrendingUp size={18} style={{ color: '#3b82f6' }} />,
            accentColor: '#3b82f6',
            glowColor: 'rgba(59, 130, 246, 0.15)',
            gradientColors: 'linear-gradient(90deg, rgba(59, 130, 246, 0.6), rgba(59, 130, 246, 0))',
            extra: (
                <span style={{
                    fontSize: '0.6rem',
                    fontWeight: 500,
                    color: 'var(--text-tertiary)',
                    letterSpacing: '0.02em',
                }}>
                    last 7d
                </span>
            ),
        },
    ];

    return (
        <PageLayout tier="standard">
            <PageHeader title="Dashboard" subtitle="Overview of your test automation suite." />

            {/* Section 1: Testing Pipeline */}
            <section className="animate-in stagger-2" style={{ marginBottom: '2rem' }}>
                <h2 style={{
                    fontSize: '0.7rem',
                    fontWeight: 500,
                    marginBottom: '0.375rem',
                    color: 'var(--text-secondary)',
                    textTransform: 'uppercase',
                    letterSpacing: '0.08em',
                }}>
                    Testing Pipeline
                </h2>
                <WorkflowPipeline progress={workflowProgress} healthStatus={healthStatus} />
            </section>

            {/* Section 2: Health Signals */}
            <section className="animate-in stagger-3" style={{ marginBottom: '2rem' }}>
                <div style={{
                    display: 'grid',
                    gridTemplateColumns: 'repeat(4, 1fr)',
                    gap: '1rem',
                }}>
                    {healthCards.map((card, idx) => (
                        <div key={idx} className="card-elevated" style={{
                            padding: '1.25rem',
                            display: 'flex',
                            alignItems: 'center',
                            gap: '0.875rem',
                            position: 'relative',
                            overflow: 'hidden',
                        }}>
                            {/* Top accent gradient line */}
                            <div style={{
                                position: 'absolute',
                                top: 0,
                                left: 0,
                                right: 0,
                                height: '1px',
                                background: card.gradientColors,
                            }} />

                            {/* Icon with glow */}
                            <div style={{
                                width: 40,
                                height: 40,
                                borderRadius: '10px',
                                background: `${card.accentColor}14`,
                                display: 'flex',
                                alignItems: 'center',
                                justifyContent: 'center',
                                flexShrink: 0,
                                boxShadow: `0 0 20px ${card.glowColor}`,
                            }}>
                                {card.icon}
                            </div>

                            {/* Content */}
                            <div style={{ minWidth: 0, flex: 1 }}>
                                <p style={{
                                    fontSize: '0.7rem',
                                    textTransform: 'uppercase',
                                    letterSpacing: '0.06em',
                                    color: 'var(--text-tertiary)',
                                    fontWeight: 500,
                                    marginBottom: '0.125rem',
                                }}>
                                    {card.label}
                                </p>
                                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                                    <p style={{
                                        fontSize: '1.5rem',
                                        fontWeight: 800,
                                        letterSpacing: '-0.02em',
                                    }}>
                                        {card.value}
                                    </p>
                                    {card.extra}
                                </div>
                            </div>
                        </div>
                    ))}
                </div>
            </section>

            {/* RTM Coverage Explainer */}
            {workflowProgress?.rtmCoverage != null && workflowProgress.rtmCoverage > 0 && workflowProgress.rtmCoverage < 30 && (
                <div className="animate-in" style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '0.75rem',
                    padding: '0.75rem 1rem',
                    marginBottom: '1.5rem',
                    borderRadius: 'var(--radius)',
                    background: 'rgba(139, 92, 246, 0.06)',
                    border: '1px solid rgba(139, 92, 246, 0.15)',
                    fontSize: '0.8rem',
                }}>
                    <span style={{ color: '#8b5cf6', fontWeight: 600 }}>Low RTM Coverage ({workflowProgress.rtmCoverage}%)</span>
                    <span style={{ color: 'var(--text-secondary)' }}>—</span>
                    <span style={{ color: 'var(--text-secondary)' }}>Map your requirements to test specs for better traceability.</span>
                    <Link href="/requirements" style={{ color: '#8b5cf6', fontWeight: 600, textDecoration: 'none', marginLeft: 'auto', whiteSpace: 'nowrap', display: 'flex', alignItems: 'center', gap: '0.25rem' }}>
                        Map requirements now <ArrowRight size={14} />
                    </Link>
                </div>
            )}

            {/* Section 3: Execution Trends + Needs Attention */}
            <section className="animate-in stagger-4" style={{ marginBottom: '2rem' }}>
                <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: '1.5rem' }}>
                    {/* Execution Trends */}
                    <div className="card-elevated" style={{ padding: '1.25rem 1.5rem', minHeight: '400px' }}>
                        <h3 style={{ fontWeight: 600, marginBottom: '1.5rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                            Execution Trends
                        </h3>
                        {stats.trends && stats.trends.length > 0 ? (
                            <div style={{ height: '300px', width: '100%' }}>
                                <ResponsiveContainer width="100%" height="100%">
                                    <AreaChart data={stats.trends}>
                                        <defs>
                                            <linearGradient id="colorPassed" x1="0" y1="0" x2="0" y2="1">
                                                <stop offset="5%" stopColor="#34d399" stopOpacity={0.4} />
                                                <stop offset="95%" stopColor="#34d399" stopOpacity={0} />
                                            </linearGradient>
                                            <linearGradient id="colorFailed" x1="0" y1="0" x2="0" y2="1">
                                                <stop offset="5%" stopColor="#f87171" stopOpacity={0.4} />
                                                <stop offset="95%" stopColor="#f87171" stopOpacity={0} />
                                            </linearGradient>
                                        </defs>
                                        <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
                                        <XAxis
                                            dataKey="date"
                                            stroke="var(--text-secondary)"
                                            fontSize={12}
                                            tickLine={false}
                                            axisLine={false}
                                            tickFormatter={(val) => val.slice(5)}
                                        />
                                        <YAxis
                                            stroke="var(--text-secondary)"
                                            fontSize={12}
                                            tickLine={false}
                                            axisLine={false}
                                        />
                                        <Tooltip
                                            contentStyle={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: '8px' }}
                                            itemStyle={{ color: 'var(--text)' }}
                                        />
                                        <Area
                                            type="monotone"
                                            dataKey="passed"
                                            stroke="#34d399"
                                            strokeWidth={2}
                                            fillOpacity={1}
                                            fill="url(#colorPassed)"
                                            name="Passed"
                                        />
                                        <Area
                                            type="monotone"
                                            dataKey="failed"
                                            stroke="#f87171"
                                            strokeWidth={2}
                                            fillOpacity={1}
                                            fill="url(#colorFailed)"
                                            name="Failed"
                                        />
                                    </AreaChart>
                                </ResponsiveContainer>
                            </div>
                        ) : (
                            <div style={{ height: '300px', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', color: 'var(--text-secondary)' }}>
                                <p>Not enough data for trends</p>
                            </div>
                        )}
                    </div>

                    {/* Needs Attention */}
                    <div className="card-elevated" style={{ padding: '1.25rem 1.5rem' }}>
                        <h3 style={{ fontWeight: 600, marginBottom: '1.25rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                            <Zap size={16} style={{ color: '#f59e0b' }} />
                            Needs Attention
                            {attentionItems.length > 0 && (
                                <span style={{
                                    fontSize: '0.7rem',
                                    fontWeight: 600,
                                    color: '#f59e0b',
                                    background: 'rgba(245, 158, 11, 0.1)',
                                    padding: '0.1rem 0.4rem',
                                    borderRadius: '9999px',
                                    animation: 'glowPulse 2s ease-in-out infinite',
                                }}>
                                    {attentionItems.length}
                                </span>
                            )}
                        </h3>

                        {attentionItems.length > 0 ? (
                            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.625rem', maxHeight: '320px', overflowY: 'auto' }}>
                                {attentionItems.map((item, i) => (
                                    <Link
                                        key={i}
                                        href={item.href}
                                        style={{
                                            display: 'block',
                                            padding: '0.625rem 0.75rem',
                                            background: 'var(--surface-hover)',
                                            borderRadius: '8px',
                                            borderLeft: `3px solid ${item.severity === 'critical' ? '#ef4444' : '#f59e0b'}`,
                                            textDecoration: 'none',
                                            color: 'inherit',
                                            transition: 'background 0.15s, transform 0.15s var(--ease-spring)',
                                        }}
                                        onMouseOver={e => {
                                            e.currentTarget.style.background = 'var(--border)';
                                            e.currentTarget.style.transform = 'translateX(2px)';
                                        }}
                                        onMouseOut={e => {
                                            e.currentTarget.style.background = 'var(--surface-hover)';
                                            e.currentTarget.style.transform = 'translateX(0)';
                                        }}
                                    >
                                        <div style={{ fontSize: '0.8rem', fontWeight: 500, marginBottom: '0.25rem', wordBreak: 'break-word' }}>
                                            {item.label}
                                        </div>
                                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.375rem', fontSize: '0.7rem', color: 'var(--text-secondary)' }}>
                                            {item.detail.includes('flaky') && <AlertTriangle size={11} style={{ color: item.severity === 'critical' ? '#ef4444' : '#f59e0b' }} />}
                                            {item.detail.includes('avg') && <Timer size={11} style={{ color: '#f59e0b' }} />}
                                            {item.detail.includes('healing') && <Wrench size={11} style={{ color: item.severity === 'critical' ? '#ef4444' : '#f59e0b' }} />}
                                            <span style={{
                                                fontWeight: 600,
                                                color: item.severity === 'critical' ? '#ef4444' : '#f59e0b',
                                            }}>
                                                {item.detail}
                                            </span>
                                        </div>
                                    </Link>
                                ))}
                            </div>
                        ) : (
                            <div style={{
                                height: '300px',
                                display: 'flex',
                                flexDirection: 'column',
                                alignItems: 'center',
                                justifyContent: 'center',
                                color: 'var(--text-secondary)',
                                gap: '0.75rem',
                            }}>
                                <div style={{
                                    padding: '0.875rem',
                                    background: 'rgba(52, 211, 153, 0.1)',
                                    borderRadius: '50%',
                                    color: 'var(--success)',
                                    boxShadow: '0 0 24px rgba(52, 211, 153, 0.2)',
                                    animation: 'subtleFloat 3s ease-in-out infinite',
                                }}>
                                    <CheckCircle2 size={28} />
                                </div>
                                <p style={{ fontWeight: 500 }}>All clear</p>
                                <p style={{ fontSize: '0.75rem', textAlign: 'center' }}>No flaky tests, slow tests, or healing issues detected</p>
                            </div>
                        )}
                    </div>
                </div>
            </section>

            {/* Section 4: Quick Actions */}
            <section className="animate-in stagger-5" style={{ marginBottom: '2rem' }}>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1.25rem' }}>
                    {computeQuickActions(stats, workflowProgress).map((action, i) => (
                        <Link
                            key={action.href + i}
                            href={action.href}
                            className="card-elevated"
                            style={{
                                textDecoration: 'none',
                                display: 'flex',
                                alignItems: 'center',
                                gap: '1.25rem',
                                color: 'inherit',
                                padding: '1.25rem',
                                cursor: 'pointer',
                                position: 'relative',
                                overflow: 'hidden',
                            }}
                            onMouseOver={e => {
                                const arrow = e.currentTarget.querySelector('[data-arrow]') as HTMLElement;
                                if (arrow) arrow.style.transform = 'translateX(4px)';
                            }}
                            onMouseOut={e => {
                                const arrow = e.currentTarget.querySelector('[data-arrow]') as HTMLElement;
                                if (arrow) arrow.style.transform = 'translateX(0)';
                            }}
                        >
                            {/* Accent line */}
                            <div style={{ position: 'absolute', top: 0, left: 0, right: 0, height: '2px', background: `linear-gradient(90deg, ${action.accentColor}, transparent)` }} />
                            <div style={{
                                width: 40, height: 40,
                                background: `${action.accentColor}14`,
                                borderRadius: '10px',
                                display: 'flex', alignItems: 'center', justifyContent: 'center',
                                flexShrink: 0,
                                color: action.accentColor,
                            }}>
                                {action.icon}
                            </div>
                            <div style={{ flex: 1 }}>
                                <h3 style={{ fontWeight: 600, fontSize: '0.9rem' }}>{action.label}</h3>
                                <p style={{ color: 'var(--text-secondary)', fontSize: '0.8rem' }}>{action.description}</p>
                            </div>
                            <div data-arrow style={{ color: 'var(--text-tertiary)', transition: 'transform 0.2s var(--ease-spring)', flexShrink: 0 }}>
                                <ArrowRight size={16} />
                            </div>
                        </Link>
                    ))}
                </div>
            </section>
        </PageLayout>
    );
}
