'use client';
import { useState, useEffect, useCallback } from 'react';
import {
    PassFailTrendChart,
    ErrorCategoryChart,
    DurationChart,
    StatCard,
    SlowestTestsCard,
    FlakyTestsCard,
    PeriodSelector,
    HealingSuccessCard,
    TimeOfDayChart,
    FailurePatternsCard,
    TestGrowthTrendsCard,
    SlowestTest,
    FlakyTest,
    HealingStats,
    TimeOfDayAnalysis,
    FailurePatterns,
    TestGrowthTrends,
} from '@/components/DashboardCharts';
import { useProject } from '@/contexts/ProjectContext';
import { API_BASE } from '@/lib/api';
import { toast } from 'sonner';
import { PageLayout } from '@/components/ui/page-layout';
import { PageHeader } from '@/components/ui/page-header';

type DashboardData = {
    trends: Array<{ date: string; passed: number; failed: number; avg_duration: number }>;
    errors: Array<{ category: string; count: number }>;
    total_runs: number;
    total_specs: number;
    pass_rate: number;
    avg_duration_seconds: number;
    slowest_test_duration: number;
    flaky_test_count: number;
    slowest_tests: SlowestTest[];
    flaky_tests: FlakyTest[];
    period: string;
    healing_stats: HealingStats;
    time_of_day_analysis: TimeOfDayAnalysis;
    failure_patterns: FailurePatterns;
    test_growth_trends: TestGrowthTrends;
};

export default function DashboardPage() {
    const { currentProject, isLoading: projectLoading } = useProject();

    const [data, setData] = useState<DashboardData>({
        trends: [],
        errors: [],
        total_runs: 0,
        total_specs: 0,
        pass_rate: 0,
        avg_duration_seconds: 0,
        slowest_test_duration: 0,
        flaky_test_count: 0,
        slowest_tests: [],
        flaky_tests: [],
        period: '7d',
        healing_stats: {
            overall: { total_heals_attempted: 0, total_heals_succeeded: 0, success_rate: 0 },
            by_mode: {
                native_healer: { attempted: 0, succeeded: 0, success_rate: 0 },
                ralph: { attempted: 0, succeeded: 0, success_rate: 0 },
            },
            avg_iterations_to_success: 0,
            trend: [],
        },
        time_of_day_analysis: {
            hourly_stats: [],
            peak_failure_hours: [],
            best_hours: [],
        },
        failure_patterns: {
            common_co_failures: [],
            isolated_failures: [],
        },
        test_growth_trends: {
            has_data: false,
            trend: [],
            latest: null,
            growth: { specs: 0, generated: 0, passing: 0 },
        },
    });
    const [loading, setLoading] = useState(true);
    const [period, setPeriod] = useState('7d');

    const fetchData = useCallback((selectedPeriod: string, projectId: string | undefined) => {
        setLoading(true);
        const projectParam = projectId ? `&project_id=${encodeURIComponent(projectId)}` : '';
        fetch(`${API_BASE}/dashboard?period=${selectedPeriod}${projectParam}`)
            .then((res) => res.json())
            .then((data) => {
                setData(data);
                setLoading(false);
            })
            .catch((err) => {
                console.error(err);
                toast.error('Failed to load reporting data');
                setLoading(false);
            });
    }, []);

    useEffect(() => {
        // Wait for project context to finish loading
        if (projectLoading) {
            return;
        }
        fetchData(period, currentProject?.id);
    }, [period, currentProject?.id, projectLoading, fetchData]);

    const handlePeriodChange = (newPeriod: string) => {
        setPeriod(newPeriod);
    };

    if (loading || projectLoading) {
        return (
            <PageLayout tier="wide">
                {/* Skeleton header */}
                <div style={{ marginBottom: '2rem' }}>
                    <div style={{ height: '2rem', width: '280px', background: 'var(--surface-hover)', borderRadius: 'var(--radius)', marginBottom: '0.75rem', animation: 'shimmer 2s infinite linear', backgroundSize: '200% 100%', backgroundImage: 'linear-gradient(90deg, var(--surface-hover) 25%, var(--surface-active) 50%, var(--surface-hover) 75%)' }} />
                    <div style={{ height: '1rem', width: '180px', background: 'var(--surface-hover)', borderRadius: 'var(--radius-sm)', animation: 'shimmer 2s infinite linear', backgroundSize: '200% 100%', backgroundImage: 'linear-gradient(90deg, var(--surface-hover) 25%, var(--surface-active) 50%, var(--surface-hover) 75%)' }} />
                </div>
                {/* Skeleton stat cards */}
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: '1rem', marginBottom: '2rem' }}>
                    {[...Array(5)].map((_, i) => (
                        <div key={i} style={{ height: '90px', background: 'var(--surface)', borderRadius: 'var(--radius-lg)', border: '1px solid var(--border-subtle)', animation: 'shimmer 2s infinite linear', animationDelay: `${i * 0.1}s`, backgroundSize: '200% 100%', backgroundImage: 'linear-gradient(90deg, var(--surface) 25%, var(--surface-hover) 50%, var(--surface) 75%)' }} />
                    ))}
                </div>
                {/* Skeleton chart cards */}
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(500px, 1fr))', gap: '2rem' }}>
                    {[...Array(2)].map((_, i) => (
                        <div key={i} style={{ height: '400px', background: 'var(--surface)', borderRadius: 'var(--radius)', border: '1px solid var(--border-subtle)', animation: 'shimmer 2s infinite linear', animationDelay: `${i * 0.15}s`, backgroundSize: '200% 100%', backgroundImage: 'linear-gradient(90deg, var(--surface) 25%, var(--surface-hover) 50%, var(--surface) 75%)' }} />
                    ))}
                </div>
            </PageLayout>
        );
    }

    return (
        <PageLayout tier="wide">
            <PageHeader
                title="Reporting Dashboard"
                subtitle={`Analytics overview for ${data.total_runs} test runs.`}
                actions={<PeriodSelector value={period} onChange={handlePeriodChange} />}
            />

            <div style={{ display: 'grid', gridTemplateColumns: '1fr', gap: '2rem' }}>
                {/* Stat Cards Row */}
                <div
                    className="animate-in stagger-2"
                    style={{
                        display: 'grid',
                        gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))',
                        gap: '1rem',
                    }}
                >
                    <StatCard label="Total Runs" value={data.total_runs} />
                    <StatCard
                        label="Pass Rate"
                        value={`${data.pass_rate}%`}
                        color={data.pass_rate >= 80 ? 'green' : data.pass_rate >= 50 ? 'yellow' : 'red'}
                    />
                    <StatCard
                        label="Avg Duration"
                        value={`${data.avg_duration_seconds}s`}
                        color="blue"
                    />
                    <StatCard
                        label="Flaky Tests"
                        value={data.flaky_test_count}
                        color={data.flaky_test_count > 0 ? 'yellow' : 'default'}
                    />
                    <StatCard
                        label="Slowest"
                        value={`${data.slowest_test_duration}s`}
                        color={data.slowest_test_duration > 60 ? 'red' : 'default'}
                    />
                </div>

                {/* Row 1: Trends and Duration Charts */}
                <div
                    className="animate-in stagger-3"
                    style={{
                        display: 'grid',
                        gridTemplateColumns: 'repeat(auto-fit, minmax(500px, 1fr))',
                        gap: '2rem',
                    }}
                >
                    <div className="card-elevated" style={{ padding: '2rem' }}>
                        <div style={{ fontSize: '0.7rem', textTransform: 'uppercase', letterSpacing: '0.08em', color: 'var(--text-tertiary)', marginBottom: '0.5rem' }}>Trend Analysis</div>
                        <h3
                            className="text-xl font-bold"
                            style={{ marginBottom: '1.5rem', color: 'var(--text)' }}
                        >
                            Pass/Fail Trends
                        </h3>
                        <PassFailTrendChart data={data.trends} />
                    </div>

                    <div className="card-elevated" style={{ padding: '2rem' }}>
                        <div style={{ fontSize: '0.7rem', textTransform: 'uppercase', letterSpacing: '0.08em', color: 'var(--text-tertiary)', marginBottom: '0.5rem' }}>Performance</div>
                        <h3
                            className="text-xl font-bold"
                            style={{ marginBottom: '1.5rem', color: 'var(--text)' }}
                        >
                            Average Duration (Daily)
                        </h3>
                        <DurationChart data={data.trends} />
                    </div>
                </div>

                {/* Row 2: Slowest and Flaky Tests */}
                <div
                    className="animate-in stagger-4"
                    style={{
                        display: 'grid',
                        gridTemplateColumns: 'repeat(auto-fit, minmax(400px, 1fr))',
                        gap: '2rem',
                    }}
                >
                    <div className="card-elevated" style={{ padding: '2rem' }}>
                        <div style={{ fontSize: '0.7rem', textTransform: 'uppercase', letterSpacing: '0.08em', color: 'var(--text-tertiary)', marginBottom: '0.5rem' }}>Bottlenecks</div>
                        <h3
                            className="text-xl font-bold"
                            style={{ marginBottom: '1.5rem', color: 'var(--text)' }}
                        >
                            Slowest Tests (Top 10)
                        </h3>
                        <SlowestTestsCard tests={data.slowest_tests} />
                    </div>

                    <div className="card-elevated" style={{ padding: '2rem' }}>
                        <div style={{ fontSize: '0.7rem', textTransform: 'uppercase', letterSpacing: '0.08em', color: 'var(--text-tertiary)', marginBottom: '0.5rem' }}>Stability</div>
                        <h3
                            className="text-xl font-bold"
                            style={{ marginBottom: '1.5rem', color: 'var(--text)' }}
                        >
                            Flaky Tests
                        </h3>
                        <FlakyTestsCard tests={data.flaky_tests} />
                    </div>
                </div>

                {/* Row 3: Errors */}
                <div className="card-elevated animate-in stagger-5" style={{ padding: '2rem' }}>
                    <div style={{ fontSize: '0.7rem', textTransform: 'uppercase', letterSpacing: '0.08em', color: 'var(--text-tertiary)', marginBottom: '0.5rem' }}>Error Breakdown</div>
                    <h3
                        className="text-xl font-bold"
                        style={{ marginBottom: '1.5rem', color: 'var(--text)' }}
                    >
                        Top Error Categories
                    </h3>
                    <div style={{ height: '400px', display: 'flex', justifyContent: 'center' }}>
                        <ErrorCategoryChart data={data.errors} />
                    </div>
                </div>

                {/* Row 4: Healing Success + Coverage Trends */}
                <div
                    className="animate-in stagger-6"
                    style={{
                        display: 'grid',
                        gridTemplateColumns: 'repeat(auto-fit, minmax(400px, 1fr))',
                        gap: '2rem',
                    }}
                >
                    <div className="card-elevated" style={{ padding: '2rem' }}>
                        <div style={{ fontSize: '0.7rem', textTransform: 'uppercase', letterSpacing: '0.08em', color: 'var(--text-tertiary)', marginBottom: '0.5rem' }}>Self-Healing</div>
                        <h3
                            className="text-xl font-bold"
                            style={{ marginBottom: '1.5rem', color: 'var(--text)' }}
                        >
                            Healing Success Rate
                        </h3>
                        <HealingSuccessCard stats={data.healing_stats} />
                    </div>

                    <div className="card-elevated" style={{ padding: '2rem' }}>
                        <div style={{ fontSize: '0.7rem', textTransform: 'uppercase', letterSpacing: '0.08em', color: 'var(--text-tertiary)', marginBottom: '0.5rem' }}>Coverage</div>
                        <h3
                            className="text-xl font-bold"
                            style={{ marginBottom: '1.5rem', color: 'var(--text)' }}
                        >
                            Test Growth
                        </h3>
                        <TestGrowthTrendsCard growth={data.test_growth_trends} />
                    </div>
                </div>

                {/* Row 5: Time of Day + Failure Patterns */}
                <div
                    className="animate-in stagger-6"
                    style={{
                        display: 'grid',
                        gridTemplateColumns: 'repeat(auto-fit, minmax(400px, 1fr))',
                        gap: '2rem',
                    }}
                >
                    <div className="card-elevated" style={{ padding: '2rem' }}>
                        <div style={{ fontSize: '0.7rem', textTransform: 'uppercase', letterSpacing: '0.08em', color: 'var(--text-tertiary)', marginBottom: '0.5rem' }}>Scheduling</div>
                        <h3
                            className="text-xl font-bold"
                            style={{ marginBottom: '1.5rem', color: 'var(--text)' }}
                        >
                            Pass Rate by Hour
                        </h3>
                        <TimeOfDayChart data={data.time_of_day_analysis} />
                    </div>

                    <div className="card-elevated" style={{ padding: '2rem' }}>
                        <div style={{ fontSize: '0.7rem', textTransform: 'uppercase', letterSpacing: '0.08em', color: 'var(--text-tertiary)', marginBottom: '0.5rem' }}>Diagnostics</div>
                        <h3
                            className="text-xl font-bold"
                            style={{ marginBottom: '1.5rem', color: 'var(--text)' }}
                        >
                            Failure Patterns
                        </h3>
                        <FailurePatternsCard patterns={data.failure_patterns} />
                    </div>
                </div>
            </div>
        </PageLayout>
    );
}
