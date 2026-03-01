'use client';

import {
    BarChart,
    Bar,
    XAxis,
    YAxis,
    CartesianGrid,
    Tooltip,
    Legend,
    ResponsiveContainer,
    PieChart,
    Pie,
    Cell,
    LineChart,
    Line,
} from 'recharts';

// --- Types ---
export type TrendData = {
    date: string;
    passed: number;
    failed: number;
};

export type ErrorData = {
    category: string;
    count: number;
};

export type DurationData = {
    date: string;
    avg_duration: number;
};

export type SlowestTest = {
    spec_name: string;
    avg_duration: number;
    run_count: number;
    max_duration: number;
};

export type FlakyTest = {
    spec_name: string;
    passed: number;
    failed: number;
    total: number;
    flakiness_rate: number;
};

// --- New Analytics Types ---
export type ModeStats = {
    attempted: number;
    succeeded: number;
    success_rate: number;
};

export type HealingStats = {
    overall: { total_heals_attempted: number; total_heals_succeeded: number; success_rate: number };
    by_mode: { native_healer: ModeStats; ralph: ModeStats };
    avg_iterations_to_success: number;
    trend: Array<{ date: string; success_rate: number; attempts: number }>;
};

export type TimeOfDayAnalysis = {
    hourly_stats: Array<{ hour: number; total: number; passed: number; failed: number; pass_rate: number }>;
    peak_failure_hours: number[];
    best_hours: number[];
};

export type FailurePatterns = {
    common_co_failures: Array<{ tests: string[]; co_occurrence_count: number; co_occurrence_rate: number }>;
    isolated_failures: Array<{ test: string; solo_failure_rate: number }>;
};

export type TestGrowthTrends = {
    has_data: boolean;
    trend: Array<{
        date: string;
        total_specs: number;
        generated_tests: number;
        passing_tests: number;
        daily_runs: number;
    }>;
    latest: {
        total_specs: number;
        generated_tests: number;
        passing_tests: number;
    } | null;
    growth: {
        specs: number;
        generated: number;
        passing: number;
    };
};

// --- Spec Name Formatting ---
function formatSpecName(rawName: string): string {
    const name = rawName.split('/').pop() || rawName;
    return name
        .replace(/\.md$/i, '')
        .replace(/^tc-\d+-/i, '')
        .replace(/-/g, ' ')
        .replace(/\b\w/g, c => c.toUpperCase());
}

// --- Theme Constants (using design system tokens) ---
// Note: Recharts renders SVG, so CSS variables don't work — use hex equivalents from globals.css :root
const THEME = {
    axis: { stroke: '#7e8ba8', fontSize: 12 },  // --text-secondary
    grid: { stroke: '#1e2a42', strokeDasharray: '3 3' },  // --border
    tooltip: {
        contentStyle: { backgroundColor: '#151d30', borderColor: '#1e2a42', borderRadius: '10px', color: '#f0f4fc' },  // --surface, --border, --radius, --text
        itemStyle: { color: '#f0f4fc' },  // --text
        labelStyle: { color: '#7e8ba8', marginBottom: '0.25rem' }  // --text-secondary
    },
    legend: { wrapperStyle: { paddingTop: '20px' } }
};

// --- Components ---

export function PassFailTrendChart({ data }: { data: TrendData[] }) {
    if (!data || data.length === 0) return <div style={{ textAlign: 'center', padding: '1rem', color: 'var(--text-tertiary)' }}>No data available</div>;

    return (
        <ResponsiveContainer width="100%" height={350}>
            <BarChart data={data} margin={{ top: 20, right: 30, left: 20, bottom: 5 }}>
                <CartesianGrid {...THEME.grid} vertical={false} />
                <XAxis dataKey="date" {...THEME.axis} />
                <YAxis {...THEME.axis} />
                <Tooltip {...THEME.tooltip} cursor={{ fill: 'rgba(255,255,255,0.05)' }} />
                <Legend {...THEME.legend} />
                <Bar dataKey="passed" stackId="a" fill="#34d399" name="Passed" radius={[0, 0, 4, 4]} />
                <Bar dataKey="failed" stackId="a" fill="#f87171" name="Failed" radius={[4, 4, 0, 0]} />
            </BarChart>
        </ResponsiveContainer>
    );
}

const COLORS = ['#f87171', '#fbbf24', '#3b82f6', '#c084fc', '#ec4899', '#34d399'];  // --danger, --warning, --primary, --accent, pink, --success

export function ErrorCategoryChart({ data }: { data: ErrorData[] }) {
    if (!data || data.length === 0) return <div style={{ textAlign: 'center', padding: '1rem', color: 'var(--text-tertiary)' }}>No errors recorded</div>;

    return (
        <ResponsiveContainer width="100%" height={400}>
            <PieChart>
                <Pie
                    data={data}
                    cx="50%"
                    cy="50%"
                    labelLine={false}
                    label={({ name, percent }) => `${name} ${((percent || 0) * 100).toFixed(0)}%`}
                    innerRadius={80}  // Donut style
                    outerRadius={140} // Increased size
                    fill="#8884d8"
                    paddingAngle={2}
                    dataKey="count"
                    nameKey="category"
                >
                    {data.map((entry, index) => (
                        <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} stroke="rgba(0,0,0,0)" />
                    ))}
                </Pie>
                <Tooltip {...THEME.tooltip} />
                <Legend {...THEME.legend} />
            </PieChart>
        </ResponsiveContainer>
    );
}

export function DurationChart({ data }: { data: DurationData[] }) {
    if (!data || data.length === 0) return <div style={{ textAlign: 'center', padding: '1rem', color: 'var(--text-tertiary)' }}>No data available</div>;

    return (
        <ResponsiveContainer width="100%" height={350}>
            <LineChart data={data} margin={{ top: 20, right: 30, left: 20, bottom: 5 }}>
                <CartesianGrid {...THEME.grid} vertical={false} />
                <XAxis dataKey="date" {...THEME.axis} />
                <YAxis label={{ value: 'Seconds', ...THEME.axis, angle: -90, position: 'insideLeft' }} {...THEME.axis} />
                <Tooltip {...THEME.tooltip} />
                <Legend {...THEME.legend} />
                <Line
                    type="monotone"
                    dataKey="avg_duration"
                    stroke="#3b82f6"
                    name="Avg Duration (s)"
                    strokeWidth={3}
                    dot={{ r: 4, fill: '#3b82f6', strokeWidth: 2, stroke: '#151d30' }}
                    activeDot={{ r: 6 }}
                />
            </LineChart>
        </ResponsiveContainer>
    );
}

// --- Stat Card Component ---
type StatCardProps = {
    label: string;
    value: string | number;
    color?: 'default' | 'green' | 'yellow' | 'red' | 'blue';
    icon?: React.ReactNode;
};

const colorStyles = {
    default: { bg: 'var(--surface)', text: 'var(--text)', accent: 'var(--text-secondary)' },
    green: { bg: 'var(--success-muted)', text: 'var(--success)', accent: '#34d399' },
    yellow: { bg: 'var(--warning-muted)', text: 'var(--warning)', accent: '#fbbf24' },
    red: { bg: 'var(--danger-muted)', text: 'var(--danger)', accent: '#f87171' },
    blue: { bg: 'rgba(59, 130, 246, 0.12)', text: 'var(--primary)', accent: '#60a5fa' },
};

export function StatCard({ label, value, color = 'default' }: StatCardProps) {
    const styles = colorStyles[color];

    return (
        <div
            style={{
                backgroundColor: styles.bg,
                borderRadius: 'var(--radius-lg)',
                padding: '1.25rem',
                border: '1px solid var(--border-subtle)',
                display: 'flex',
                flexDirection: 'column',
                gap: '0.5rem',
                transition: 'all 0.3s var(--ease-smooth)',
            }}
        >
            <span style={{ color: 'var(--text-secondary)', fontSize: '0.875rem', fontWeight: 500 }}>{label}</span>
            <span style={{ color: styles.text, fontSize: '1.75rem', fontWeight: 700 }}>{value}</span>
        </div>
    );
}

// --- Slowest Tests Card ---
export function SlowestTestsCard({ tests }: { tests: SlowestTest[] }) {
    if (!tests || tests.length === 0) {
        return (
            <div style={{ color: 'var(--text-tertiary)', textAlign: 'center', padding: '2rem' }}>
                No test duration data available
            </div>
        );
    }

    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
            {tests.slice(0, 10).map((test, index) => (
                <div
                    key={test.spec_name}
                    style={{
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        padding: '0.75rem 1rem',
                        backgroundColor: index === 0 ? 'var(--danger-muted)' : 'var(--surface)',
                        borderRadius: 'var(--radius)',
                        border: '1px solid var(--border)',
                    }}
                >
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                        <span
                            style={{
                                color: 'var(--text-secondary)',
                                fontSize: '0.875rem',
                                fontWeight: 600,
                                minWidth: '1.5rem',
                            }}
                        >
                            {index + 1}.
                        </span>
                        <span
                            style={{
                                color: 'var(--text)',
                                fontSize: '0.9rem',
                                fontWeight: 500,
                                overflow: 'hidden',
                                textOverflow: 'ellipsis',
                                whiteSpace: 'nowrap',
                                maxWidth: '200px',
                            }}
                            title={test.spec_name}
                        >
                            {formatSpecName(test.spec_name)}
                        </span>
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
                        <span style={{ color: 'var(--text-secondary)', fontSize: '0.75rem' }}>
                            {test.run_count} run{test.run_count !== 1 ? 's' : ''}
                        </span>
                        <span
                            style={{
                                color: index === 0 ? 'var(--danger)' : 'var(--warning)',
                                fontWeight: 700,
                                fontSize: '0.9rem',
                                fontFamily: 'monospace',
                            }}
                        >
                            {test.avg_duration.toFixed(1)}s
                        </span>
                    </div>
                </div>
            ))}
        </div>
    );
}

// --- Flaky Tests Card ---
export function FlakyTestsCard({ tests }: { tests: FlakyTest[] }) {
    if (!tests || tests.length === 0) {
        return (
            <div style={{ color: 'var(--text-tertiary)', textAlign: 'center', padding: '2rem' }}>
                No flaky tests detected
            </div>
        );
    }

    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
            {tests.map((test) => (
                <div
                    key={test.spec_name}
                    style={{
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        padding: '0.75rem 1rem',
                        backgroundColor: 'var(--warning-muted)',
                        borderRadius: 'var(--radius)',
                        border: '1px solid rgba(251, 191, 36, 0.2)',
                    }}
                >
                    <span
                        style={{
                            color: 'var(--text)',
                            fontSize: '0.9rem',
                            fontWeight: 500,
                            overflow: 'hidden',
                            textOverflow: 'ellipsis',
                            whiteSpace: 'nowrap',
                            maxWidth: '200px',
                        }}
                        title={test.spec_name}
                    >
                        {formatSpecName(test.spec_name)}
                    </span>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                            <span style={{ color: 'var(--success)', fontSize: '0.75rem' }}>
                                {test.passed} passed
                            </span>
                            <span style={{ color: 'var(--text-secondary)' }}>/</span>
                            <span style={{ color: 'var(--danger)', fontSize: '0.75rem' }}>
                                {test.failed} failed
                            </span>
                        </div>
                        <span
                            style={{
                                color: 'var(--warning)',
                                fontWeight: 700,
                                fontSize: '0.9rem',
                                fontFamily: 'monospace',
                                backgroundColor: 'var(--warning-muted)',
                                padding: '0.25rem 0.5rem',
                                borderRadius: 'var(--radius-sm)',
                            }}
                        >
                            {test.flakiness_rate.toFixed(0)}%
                        </span>
                    </div>
                </div>
            ))}
        </div>
    );
}

// --- Period Selector ---
type PeriodSelectorProps = {
    value: string;
    onChange: (period: string) => void;
};

const periods = [
    { value: '24h', label: '24h' },
    { value: '7d', label: '7d' },
    { value: '30d', label: '30d' },
    { value: 'all', label: 'All Time' },
];

export function PeriodSelector({ value, onChange }: PeriodSelectorProps) {
    return (
        <div style={{ display: 'flex', gap: '0.5rem' }}>
            {periods.map((period) => (
                <button
                    key={period.value}
                    onClick={() => onChange(period.value)}
                    style={{
                        padding: '0.5rem 1rem',
                        borderRadius: 'var(--radius)',
                        border: value === period.value ? 'none' : '1px solid var(--border-subtle)',
                        cursor: 'pointer',
                        fontWeight: 600,
                        fontSize: '0.875rem',
                        backgroundColor: value === period.value ? 'var(--primary)' : 'var(--surface)',
                        color: value === period.value ? '#fff' : 'var(--text-secondary)',
                        transition: 'all 0.2s var(--ease-smooth)',
                    }}
                >
                    {period.label}
                </button>
            ))}
        </div>
    );
}

// --- Healing Success Card ---
export function HealingSuccessCard({ stats }: { stats: HealingStats }) {
    if (!stats || stats.overall.total_heals_attempted === 0) {
        return (
            <div style={{ color: 'var(--text-tertiary)', textAlign: 'center', padding: '2rem' }}>
                No healing data available
            </div>
        );
    }

    const successRate = stats.overall.success_rate;
    const rateColor = successRate >= 80 ? 'var(--success)' : successRate >= 50 ? 'var(--warning)' : 'var(--danger)';
    const rateBg = successRate >= 80 ? 'var(--success-muted)' : successRate >= 50 ? 'var(--warning-muted)' : 'var(--danger-muted)';

    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
            {/* Main Success Rate */}
            <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
                <div
                    style={{
                        backgroundColor: rateBg,
                        borderRadius: '12px',
                        padding: '1rem 1.5rem',
                        display: 'flex',
                        flexDirection: 'column',
                        alignItems: 'center',
                        minWidth: '120px',
                    }}
                >
                    <span style={{ color: rateColor, fontSize: '2.5rem', fontWeight: 700 }}>
                        {successRate}%
                    </span>
                    <span style={{ color: 'var(--text-secondary)', fontSize: '0.75rem' }}>Success Rate</span>
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                    <div style={{ color: 'var(--text)', fontSize: '0.9rem' }}>
                        <strong>{stats.overall.total_heals_succeeded}</strong>
                        <span style={{ color: 'var(--text-secondary)' }}> / {stats.overall.total_heals_attempted} heals successful</span>
                    </div>
                    {stats.avg_iterations_to_success > 0 && (
                        <div
                            style={{
                                backgroundColor: 'rgba(59, 130, 246, 0.12)',
                                color: 'var(--primary)',
                                padding: '0.25rem 0.75rem',
                                borderRadius: '9999px',
                                fontSize: '0.75rem',
                                fontWeight: 600,
                                display: 'inline-block',
                                width: 'fit-content',
                            }}
                        >
                            Avg {stats.avg_iterations_to_success} iterations to success
                        </div>
                    )}
                </div>
            </div>

            {/* Mode Breakdown */}
            <div style={{ display: 'flex', gap: '1rem' }}>
                {(['native_healer', 'ralph'] as const).map((mode) => {
                    const modeStats = stats.by_mode[mode];
                    if (modeStats.attempted === 0) return null;
                    const modeName = mode === 'native_healer' ? 'Native Healer' : 'Ralph';
                    return (
                        <div
                            key={mode}
                            style={{
                                flex: 1,
                                backgroundColor: 'var(--surface)',
                                borderRadius: 'var(--radius)',
                                padding: '0.75rem 1rem',
                                border: '1px solid var(--border)',
                            }}
                        >
                            <div style={{ color: 'var(--text-secondary)', fontSize: '0.75rem', marginBottom: '0.25rem' }}>
                                {modeName}
                            </div>
                            <div style={{ display: 'flex', alignItems: 'baseline', gap: '0.5rem' }}>
                                <span style={{ color: 'var(--text)', fontSize: '1.25rem', fontWeight: 700 }}>
                                    {modeStats.success_rate}%
                                </span>
                                <span style={{ color: 'var(--text-tertiary)', fontSize: '0.75rem' }}>
                                    ({modeStats.succeeded}/{modeStats.attempted})
                                </span>
                            </div>
                        </div>
                    );
                })}
            </div>

            {/* Mini Trend Chart */}
            {stats.trend.length > 1 && (
                <div style={{ height: '100px' }}>
                    <ResponsiveContainer width="100%" height="100%">
                        <LineChart data={stats.trend} margin={{ top: 5, right: 5, left: 5, bottom: 5 }}>
                            <Line
                                type="monotone"
                                dataKey="success_rate"
                                stroke="#34d399"
                                strokeWidth={2}
                                dot={false}
                            />
                            <Tooltip
                                contentStyle={{ backgroundColor: '#151d30', borderColor: '#1e2a42', borderRadius: '10px' }}
                                labelStyle={{ color: '#7e8ba8' }}
                                formatter={(value) => [`${value}%`, 'Success Rate']}
                            />
                        </LineChart>
                    </ResponsiveContainer>
                </div>
            )}
        </div>
    );
}

// --- Time of Day Chart ---
export function TimeOfDayChart({ data }: { data: TimeOfDayAnalysis }) {
    if (!data || !data.hourly_stats || data.hourly_stats.every(h => h.total === 0)) {
        return (
            <div style={{ color: 'var(--text-tertiary)', textAlign: 'center', padding: '2rem' }}>
                No time-of-day data available
            </div>
        );
    }

    const chartData = data.hourly_stats.map((h) => ({
        ...h,
        label: `${h.hour.toString().padStart(2, '0')}:00`,
    }));

    const getBarColor = (passRate: number) => {
        if (passRate >= 80) return '#34d399';  // --success
        if (passRate >= 50) return '#fbbf24';  // --warning
        return '#f87171';  // --danger
    };

    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
            <ResponsiveContainer width="100%" height={250}>
                <BarChart data={chartData} margin={{ top: 10, right: 10, left: 10, bottom: 20 }}>
                    <CartesianGrid {...THEME.grid} vertical={false} />
                    <XAxis
                        dataKey="label"
                        {...THEME.axis}
                        interval={2}
                        tick={{ fontSize: 10 }}
                    />
                    <YAxis
                        {...THEME.axis}
                        domain={[0, 100]}
                        tickFormatter={(v) => `${v}%`}
                    />
                    <Tooltip
                        {...THEME.tooltip}
                        formatter={(value, name) => {
                            if (name === 'pass_rate') return [`${value}%`, 'Pass Rate'];
                            return [value, name];
                        }}
                        labelFormatter={(label) => `Hour: ${label}`}
                    />
                    <Bar
                        dataKey="pass_rate"
                        name="Pass Rate"
                        radius={[4, 4, 0, 0]}
                        fill="#3b82f6"
                    >
                        {chartData.map((entry, index) => (
                            <Cell key={`cell-${index}`} fill={entry.total > 0 ? getBarColor(entry.pass_rate) : '#1e2a42'} />
                        ))}
                    </Bar>
                </BarChart>
            </ResponsiveContainer>

            {/* Highlights */}
            <div style={{ display: 'flex', gap: '1rem', flexWrap: 'wrap' }}>
                {data.best_hours.length > 0 && (
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                        <span style={{ color: 'var(--success)', fontSize: '0.75rem' }}>Best hours:</span>
                        {data.best_hours.slice(0, 3).map((h) => (
                            <span
                                key={h}
                                style={{
                                    backgroundColor: 'var(--success-muted)',
                                    color: 'var(--success)',
                                    padding: '0.125rem 0.5rem',
                                    borderRadius: 'var(--radius-sm)',
                                    fontSize: '0.75rem',
                                    fontWeight: 600,
                                }}
                            >
                                {h.toString().padStart(2, '0')}:00
                            </span>
                        ))}
                    </div>
                )}
                {data.peak_failure_hours.length > 0 && (
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                        <span style={{ color: 'var(--danger)', fontSize: '0.75rem' }}>Peak failures:</span>
                        {data.peak_failure_hours.slice(0, 3).map((h) => (
                            <span
                                key={h}
                                style={{
                                    backgroundColor: 'var(--danger-muted)',
                                    color: 'var(--danger)',
                                    padding: '0.125rem 0.5rem',
                                    borderRadius: 'var(--radius-sm)',
                                    fontSize: '0.75rem',
                                    fontWeight: 600,
                                }}
                            >
                                {h.toString().padStart(2, '0')}:00
                            </span>
                        ))}
                    </div>
                )}
            </div>
        </div>
    );
}

// --- Failure Patterns Card ---
export function FailurePatternsCard({ patterns }: { patterns: FailurePatterns }) {
    const hasCoFailures = patterns?.common_co_failures?.length > 0;
    const hasIsolatedFailures = patterns?.isolated_failures?.length > 0;

    if (!hasCoFailures && !hasIsolatedFailures) {
        return (
            <div style={{ color: 'var(--text-tertiary)', textAlign: 'center', padding: '2rem' }}>
                No failure patterns detected
            </div>
        );
    }

    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
            {/* Co-failures */}
            {hasCoFailures && (
                <div>
                    <div style={{ color: 'var(--text-secondary)', fontSize: '0.75rem', marginBottom: '0.75rem', fontWeight: 600 }}>
                        Tests That Fail Together
                    </div>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                        {patterns.common_co_failures.slice(0, 5).map((item, index) => (
                            <div
                                key={index}
                                style={{
                                    display: 'flex',
                                    alignItems: 'center',
                                    justifyContent: 'space-between',
                                    padding: '0.5rem 0.75rem',
                                    backgroundColor: 'var(--surface)',
                                    borderRadius: 'var(--radius-sm)',
                                    border: '1px solid var(--border)',
                                }}
                            >
                                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem', flex: 1, minWidth: 0 }}>
                                    {item.tests.map((test, idx) => (
                                        <span
                                            key={idx}
                                            style={{
                                                color: 'var(--text)',
                                                fontSize: '0.8rem',
                                                overflow: 'hidden',
                                                textOverflow: 'ellipsis',
                                                whiteSpace: 'nowrap',
                                            }}
                                            title={test}
                                        >
                                            {test}
                                        </span>
                                    ))}
                                </div>
                                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginLeft: '0.5rem' }}>
                                    <span
                                        style={{
                                            backgroundColor: 'var(--danger-muted)',
                                            color: 'var(--danger)',
                                            padding: '0.125rem 0.5rem',
                                            borderRadius: 'var(--radius-sm)',
                                            fontSize: '0.7rem',
                                            fontWeight: 600,
                                        }}
                                    >
                                        {item.co_occurrence_count}x together
                                    </span>
                                    <span
                                        style={{
                                            color: 'var(--warning)',
                                            fontSize: '0.75rem',
                                            fontWeight: 600,
                                        }}
                                    >
                                        {item.co_occurrence_rate}%
                                    </span>
                                </div>
                            </div>
                        ))}
                    </div>
                </div>
            )}

            {/* Isolated failures */}
            {hasIsolatedFailures && (
                <div>
                    <div style={{ color: 'var(--text-secondary)', fontSize: '0.75rem', marginBottom: '0.75rem', fontWeight: 600 }}>
                        Isolated Failures (fail alone)
                    </div>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem' }}>
                        {patterns.isolated_failures.slice(0, 6).map((item, index) => (
                            <div
                                key={index}
                                style={{
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: '0.5rem',
                                    padding: '0.375rem 0.75rem',
                                    backgroundColor: 'var(--surface)',
                                    borderRadius: 'var(--radius-sm)',
                                    border: '1px solid var(--border)',
                                }}
                            >
                                <span
                                    style={{
                                        color: 'var(--text)',
                                        fontSize: '0.8rem',
                                        maxWidth: '150px',
                                        overflow: 'hidden',
                                        textOverflow: 'ellipsis',
                                        whiteSpace: 'nowrap',
                                    }}
                                    title={item.test}
                                >
                                    {item.test}
                                </span>
                                <span
                                    style={{
                                        backgroundColor: 'var(--warning-muted)',
                                        color: 'var(--warning)',
                                        padding: '0.125rem 0.375rem',
                                        borderRadius: 'var(--radius-sm)',
                                        fontSize: '0.7rem',
                                        fontWeight: 600,
                                    }}
                                >
                                    {item.solo_failure_rate}% solo
                                </span>
                            </div>
                        ))}
                    </div>
                </div>
            )}
        </div>
    );
}

// --- Test Growth Trends Card ---
export function TestGrowthTrendsCard({ growth }: { growth: TestGrowthTrends }) {
    if (!growth || !growth.has_data) {
        return (
            <div style={{ color: 'var(--text-tertiary)', textAlign: 'center', padding: '2rem' }}>
                <div style={{ marginBottom: '0.5rem' }}>No test growth data available</div>
                <div style={{ fontSize: '0.75rem' }}>
                    Growth tracking requires specs, generated tests, or test runs
                </div>
            </div>
        );
    }

    const GrowthBadge = ({ value, label }: { value: number; label: string }) => {
        if (value === 0) return null;
        const color = value > 0 ? 'var(--success)' : 'var(--danger)';
        const icon = value > 0 ? '↑' : '↓';
        return (
            <span
                style={{
                    color,
                    fontSize: '0.7rem',
                    fontWeight: 600,
                    marginLeft: '0.5rem',
                }}
            >
                {icon}{Math.abs(value)} {label}
            </span>
        );
    };

    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
            {/* Summary Stats */}
            {growth.latest && (
                <div style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap' }}>
                    <div
                        style={{
                            flex: 1,
                            minWidth: '100px',
                            backgroundColor: 'rgba(59, 130, 246, 0.12)',
                            borderRadius: 'var(--radius)',
                            padding: '0.75rem',
                            textAlign: 'center',
                        }}
                    >
                        <div style={{ color: 'var(--primary)', fontSize: '1.5rem', fontWeight: 700 }}>
                            {growth.latest.total_specs}
                        </div>
                        <div style={{ color: 'var(--text-secondary)', fontSize: '0.7rem' }}>
                            Specs
                            <GrowthBadge value={growth.growth.specs} label="new" />
                        </div>
                    </div>
                    <div
                        style={{
                            flex: 1,
                            minWidth: '100px',
                            backgroundColor: 'var(--success-muted)',
                            borderRadius: 'var(--radius)',
                            padding: '0.75rem',
                            textAlign: 'center',
                        }}
                    >
                        <div style={{ color: 'var(--success)', fontSize: '1.5rem', fontWeight: 700 }}>
                            {growth.latest.generated_tests}
                        </div>
                        <div style={{ color: 'var(--text-secondary)', fontSize: '0.7rem' }}>
                            Generated
                            <GrowthBadge value={growth.growth.generated} label="new" />
                        </div>
                    </div>
                    <div
                        style={{
                            flex: 1,
                            minWidth: '100px',
                            backgroundColor: 'var(--surface-hover)',
                            borderRadius: 'var(--radius)',
                            padding: '0.75rem',
                            textAlign: 'center',
                        }}
                    >
                        <div style={{ color: 'var(--text-secondary)', fontSize: '1.5rem', fontWeight: 700 }}>
                            {growth.latest.passing_tests}
                        </div>
                        <div style={{ color: 'var(--text-secondary)', fontSize: '0.7rem' }}>
                            Passing Runs
                            <GrowthBadge value={growth.growth.passing} label="new" />
                        </div>
                    </div>
                </div>
            )}

            {/* Trend Chart */}
            {growth.trend.length > 1 && (
                <div style={{ height: '150px' }}>
                    <ResponsiveContainer width="100%" height="100%">
                        <LineChart data={growth.trend} margin={{ top: 10, right: 10, left: 10, bottom: 10 }}>
                            <CartesianGrid {...THEME.grid} vertical={false} />
                            <XAxis dataKey="date" {...THEME.axis} tick={{ fontSize: 10 }} />
                            <YAxis {...THEME.axis} tick={{ fontSize: 10 }} />
                            <Tooltip
                                {...THEME.tooltip}
                                formatter={(value, name) => {
                                    const labels: Record<string, string> = {
                                        total_specs: 'Specs',
                                        generated_tests: 'Generated',
                                        passing_tests: 'Passing',
                                    };
                                    return [value, labels[name as string] || name];
                                }}
                            />
                            <Legend {...THEME.legend} />
                            <Line
                                type="monotone"
                                dataKey="total_specs"
                                stroke="#3b82f6"
                                strokeWidth={2}
                                dot={{ r: 2, fill: '#3b82f6' }}
                                name="Specs"
                            />
                            <Line
                                type="monotone"
                                dataKey="generated_tests"
                                stroke="#34d399"
                                strokeWidth={2}
                                dot={{ r: 2, fill: '#34d399' }}
                                name="Generated"
                            />
                            <Line
                                type="monotone"
                                dataKey="passing_tests"
                                stroke="#7e8ba8"
                                strokeWidth={2}
                                dot={{ r: 2, fill: '#7e8ba8' }}
                                name="Passing"
                            />
                        </LineChart>
                    </ResponsiveContainer>
                </div>
            )}
        </div>
    );
}
