'use client';
import React, { useState, useEffect, useMemo } from 'react';
import {
    ComposedChart, Line, Bar, BarChart, AreaChart, Area,
    XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer
} from 'recharts';
import { API_BASE } from '@/lib/api';
import { cardStyle, getAuthHeaders } from '@/lib/styles';
import { toast } from 'sonner';
import { Trophy, Star, TrendingUp, TrendingDown, Minus, Database } from 'lucide-react';
import type {
    Provider, Spec, Dataset,
    AnalyticsOverview, TrendDataPoint,
    LatencyDistribution, CostDataPoint, Regression,
    GoldenDashboardEntry, DatasetPerformance,
} from './types';

interface AnalyticsTabProps {
    projectId: string;
}

const PERIODS = ['7d', '30d', '90d'] as const;

const PROVIDER_COLORS = [
    'var(--primary)',      // blue
    'var(--success)',      // green
    'var(--warning)',      // yellow/amber
    'var(--danger)',       // red
    'var(--accent)',       // accent
    '#f472b6',            // pink
    '#38bdf8',            // sky
    '#fb923c',            // orange
    '#a3e635',            // lime
    '#2dd4bf',            // teal
];

function formatDate(dateStr: string): string {
    try {
        const d = new Date(dateStr);
        return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
    } catch {
        return dateStr;
    }
}

function passRateColor(rate: number): string {
    if (rate >= 80) return 'var(--success)';
    if (rate >= 50) return 'var(--warning)';
    return 'var(--danger)';
}

const CustomTooltip = ({ active, payload, label }: any) => {
    if (!active || !payload?.length) return null;
    return (
        <div style={{
            background: 'var(--surface)',
            border: '1px solid var(--border)',
            borderRadius: 'var(--radius)',
            padding: '0.75rem',
            boxShadow: 'var(--shadow-card)',
            fontSize: '0.85rem',
        }}>
            <div style={{ fontWeight: 600, marginBottom: '0.25rem', color: 'var(--text)' }}>{label}</div>
            {payload.map((entry: any, i: number) => (
                <div key={i} style={{ color: entry.color, display: 'flex', justifyContent: 'space-between', gap: '1rem' }}>
                    <span>{entry.name}</span>
                    <span style={{ fontWeight: 500 }}>{typeof entry.value === 'number' ? entry.value.toFixed(1) : entry.value}</span>
                </div>
            ))}
        </div>
    );
};

export default function AnalyticsTab({ projectId }: AnalyticsTabProps) {
    const [period, setPeriod] = useState<string>('30d');
    const [providerFilter, setProviderFilter] = useState<string>('');
    const [specFilter, setSpecFilter] = useState<string>('');
    const [datasetFilter, setDatasetFilter] = useState<string>('');

    const [providers, setProviders] = useState<Provider[]>([]);
    const [specs, setSpecs] = useState<Spec[]>([]);
    const [datasets, setDatasets] = useState<Dataset[]>([]);

    const [overview, setOverview] = useState<AnalyticsOverview | null>(null);
    const [trends, setTrends] = useState<TrendDataPoint[]>([]);
    const [latencyDist, setLatencyDist] = useState<LatencyDistribution[]>([]);
    const [costData, setCostData] = useState<CostDataPoint[]>([]);
    const [regressions, setRegressions] = useState<Regression[]>([]);
    const [goldenDashboard, setGoldenDashboard] = useState<GoldenDashboardEntry[]>([]);
    const [datasetPerformance, setDatasetPerformance] = useState<DatasetPerformance[]>([]);

    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    // Fetch providers, specs, and datasets once
    useEffect(() => {
        const h = getAuthHeaders();
        fetch(`${API_BASE}/llm-testing/providers?project_id=${projectId}`, { headers: h })
            .then(r => r.json()).then(setProviders).catch(() => { toast.error('Failed to load providers'); });
        fetch(`${API_BASE}/llm-testing/specs?project_id=${projectId}`, { headers: h })
            .then(r => r.json()).then(setSpecs).catch(() => { toast.error('Failed to load specs'); });
        fetch(`${API_BASE}/llm-testing/datasets?project_id=${projectId}`, { headers: h })
            .then(r => r.json()).then(setDatasets).catch(() => {});
    }, [projectId]);

    // Fetch analytics data when filters change
    useEffect(() => {
        setLoading(true);
        setError(null);
        const h = getAuthHeaders();
        const base = `project_id=${encodeURIComponent(projectId)}&period=${period}`;
        const provParam = providerFilter ? `&provider_id=${encodeURIComponent(providerFilter)}` : '';
        const specParam = specFilter ? `&spec_name=${encodeURIComponent(specFilter)}` : '';
        const datasetParam = datasetFilter ? `&dataset_id=${encodeURIComponent(datasetFilter)}` : '';

        Promise.all([
            fetch(`${API_BASE}/llm-testing/analytics/overview?${base}`, { headers: h })
                .then(r => { if (!r.ok) throw new Error('Failed to fetch overview'); return r.json(); }),
            fetch(`${API_BASE}/llm-testing/analytics/trends?${base}${provParam}${specParam}${datasetParam}`, { headers: h })
                .then(r => { if (!r.ok) throw new Error('Failed to fetch trends'); return r.json(); }),
            fetch(`${API_BASE}/llm-testing/analytics/latency-distribution?${base}${provParam}`, { headers: h })
                .then(r => { if (!r.ok) throw new Error('Failed to fetch latency'); return r.json(); }),
            fetch(`${API_BASE}/llm-testing/analytics/cost-tracking?${base}`, { headers: h })
                .then(r => { if (!r.ok) throw new Error('Failed to fetch costs'); return r.json(); }),
            fetch(`${API_BASE}/llm-testing/analytics/regressions?${base}`, { headers: h })
                .then(r => { if (!r.ok) throw new Error('Failed to fetch regressions'); return r.json(); }),
            fetch(`${API_BASE}/llm-testing/analytics/golden-dashboard?project_id=${encodeURIComponent(projectId)}`, { headers: h })
                .then(r => r.ok ? r.json() : []).catch(() => []),
            fetch(`${API_BASE}/llm-testing/analytics/dataset-performance?${base}`, { headers: h })
                .then(r => r.ok ? r.json() : []).catch(() => []),
        ])
            .then(([overviewData, trendsData, latencyData, costRes, regData, goldenData, perfData]) => {
                setOverview(overviewData);
                setTrends(trendsData.data_points || []);
                setLatencyDist(latencyData.providers || []);
                setCostData(costRes.daily_costs || []);
                setRegressions(regData.regressions || []);
                setGoldenDashboard(goldenData || []);
                setDatasetPerformance(perfData || []);
                setLoading(false);
            })
            .catch(err => { toast.error('Failed to load analytics'); setError(err.message); setLoading(false); });
    }, [projectId, period, providerFilter, specFilter, datasetFilter]);

    // Provider name lookup
    const providerName = useMemo(() => {
        const m: Record<string, string> = {};
        providers.forEach(p => { m[p.id] = p.name; });
        return m;
    }, [providers]);

    // Build cost chart data with per-provider columns
    const costChartData = useMemo(() => {
        const allProviderIds = new Set<string>();
        costData.forEach(d => {
            Object.keys(d.by_provider).forEach(pid => allProviderIds.add(pid));
        });
        return costData.map(d => {
            const row: Record<string, any> = { date: formatDate(d.date), total_cost: d.total_cost };
            allProviderIds.forEach(pid => {
                row[pid] = d.by_provider[pid] || 0;
            });
            return row;
        });
    }, [costData]);

    const costProviderIds = useMemo(() => {
        const ids = new Set<string>();
        costData.forEach(d => Object.keys(d.by_provider).forEach(pid => ids.add(pid)));
        return Array.from(ids);
    }, [costData]);

    // Chart data for trends
    const trendChartData = useMemo(() =>
        trends.map(dp => ({ ...dp, date: formatDate(dp.date) })),
    [trends]);

    // Determine if there's any data at all
    const hasData = overview && overview.total_runs > 0;

    if (loading) {
        return <div style={{ textAlign: 'center', padding: '2rem', color: 'var(--text-secondary)' }}>Loading analytics...</div>;
    }
    if (error) {
        return <div style={{ textAlign: 'center', padding: '2rem', color: 'var(--danger)' }}>{error}</div>;
    }

    if (!hasData) {
        return (
            <div style={{ textAlign: 'center', padding: '4rem 2rem', color: 'var(--text-secondary)', ...cardStyle }}>
                No analytics data yet. Run some LLM tests to see trends here.
            </div>
        );
    }

    return (
        <div>
            {/* Filter Bar */}
            <div style={{ display: 'flex', gap: '0.75rem', marginBottom: '1.5rem', flexWrap: 'wrap', alignItems: 'center' }}>
                <div style={{ display: 'flex', gap: '0.25rem' }}>
                    {PERIODS.map(p => (
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
                            }}
                        >
                            {p}
                        </button>
                    ))}
                </div>
                <select
                    value={providerFilter}
                    onChange={e => setProviderFilter(e.target.value)}
                    style={{
                        padding: '0.4rem 0.75rem',
                        borderRadius: 'var(--radius)',
                        border: '1px solid var(--border)',
                        background: 'var(--surface)',
                        color: 'var(--text)',
                        fontSize: '0.85rem',
                    }}
                >
                    <option value="">All Providers</option>
                    {providers.map(p => (
                        <option key={p.id} value={p.id}>{p.name}</option>
                    ))}
                </select>
                <select
                    value={specFilter}
                    onChange={e => setSpecFilter(e.target.value)}
                    style={{
                        padding: '0.4rem 0.75rem',
                        borderRadius: 'var(--radius)',
                        border: '1px solid var(--border)',
                        background: 'var(--surface)',
                        color: 'var(--text)',
                        fontSize: '0.85rem',
                    }}
                >
                    <option value="">All Specs</option>
                    {specs.map(s => (
                        <option key={s.name} value={s.name}>{s.title || s.name}</option>
                    ))}
                </select>
                <select
                    value={datasetFilter}
                    onChange={e => setDatasetFilter(e.target.value)}
                    style={{
                        padding: '0.4rem 0.75rem',
                        borderRadius: 'var(--radius)',
                        border: '1px solid var(--border)',
                        background: 'var(--surface)',
                        color: 'var(--text)',
                        fontSize: '0.85rem',
                    }}
                >
                    <option value="">All Datasets</option>
                    {datasets.map(d => (
                        <option key={d.id} value={d.id}>{d.name}</option>
                    ))}
                </select>
            </div>

            {/* Golden Baselines */}
            {goldenDashboard.length > 0 && (
                <div style={{ ...cardStyle, marginBottom: '1.5rem' }}>
                    <h3 style={{ fontSize: '1rem', fontWeight: 600, marginBottom: '1rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                        <Star size={16} style={{ color: '#f59e0b' }} />
                        Golden Baselines
                    </h3>
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))', gap: '0.75rem' }}>
                        {goldenDashboard.map(entry => (
                            <div key={entry.dataset_id} style={{
                                padding: '0.75rem 1rem',
                                borderRadius: 'var(--radius)',
                                border: '1px solid var(--border-subtle)',
                                background: 'var(--background-raised)',
                            }}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', marginBottom: '0.5rem' }}>
                                    <Star size={14} style={{ color: '#f59e0b', fill: '#f59e0b' }} />
                                    <span style={{ fontWeight: 600, fontSize: '0.9rem', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                        {entry.dataset_name}
                                    </span>
                                </div>
                                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                                    <span style={{ fontSize: '1.25rem', fontWeight: 700, color: passRateColor(entry.latest_pass_rate) }}>
                                        {entry.latest_pass_rate.toFixed(1)}%
                                    </span>
                                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.25rem' }}>
                                        {entry.trend === 'improving' && <TrendingUp size={14} style={{ color: 'var(--success)' }} />}
                                        {entry.trend === 'degrading' && <TrendingDown size={14} style={{ color: 'var(--danger)' }} />}
                                        {entry.trend === 'stable' && <Minus size={14} style={{ color: 'var(--text-secondary)' }} />}
                                        <span style={{
                                            fontSize: '0.78rem', fontWeight: 500,
                                            color: entry.trend === 'improving' ? 'var(--success)' : entry.trend === 'degrading' ? 'var(--danger)' : 'var(--text-secondary)',
                                        }}>
                                            {entry.trend}
                                        </span>
                                    </div>
                                </div>
                                <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', marginTop: '0.35rem' }}>
                                    {entry.total_runs} runs
                                    {entry.last_run_at && ` | Last: ${new Date(entry.last_run_at).toLocaleDateString()}`}
                                </div>
                            </div>
                        ))}
                    </div>
                </div>
            )}

            {/* Overview Cards */}
            {overview && (
                <div style={{ display: 'grid', gridTemplateColumns: overview.top_provider ? 'repeat(5, 1fr)' : 'repeat(4, 1fr)', gap: '1rem', marginBottom: '1.5rem' }}>
                    <div style={cardStyle}>
                        <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: '0.5rem' }}>Total Runs</div>
                        <div style={{ fontSize: '1.75rem', fontWeight: 700 }}>{overview.total_runs}</div>
                    </div>
                    <div style={cardStyle}>
                        <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: '0.5rem' }}>Avg Pass Rate</div>
                        <div style={{ fontSize: '1.75rem', fontWeight: 700, color: passRateColor(overview.avg_pass_rate), display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                            {overview.avg_pass_rate.toFixed(1)}%
                            {overview.recent_regression && (
                                <span style={{ fontSize: '0.75rem', color: 'var(--danger)', fontWeight: 500 }}>REGRESSION</span>
                            )}
                        </div>
                    </div>
                    <div style={cardStyle}>
                        <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: '0.5rem' }}>Avg Latency</div>
                        <div style={{ fontSize: '1.75rem', fontWeight: 700 }}>
                            {overview.avg_latency != null ? `${overview.avg_latency.toFixed(0)}ms` : '-'}
                        </div>
                    </div>
                    <div style={cardStyle}>
                        <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: '0.5rem' }}>Total Cost</div>
                        <div style={{ fontSize: '1.75rem', fontWeight: 700 }}>
                            ${overview.total_cost.toFixed(2)}
                        </div>
                    </div>
                    {overview.top_provider && (
                        <div style={cardStyle}>
                            <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: '0.5rem', display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
                                <Trophy size={14} />
                                Top Provider
                            </div>
                            <div style={{ fontSize: '1.25rem', fontWeight: 700 }}>
                                {providerName[overview.top_provider] || overview.top_provider}
                            </div>
                        </div>
                    )}
                </div>
            )}

            {/* Pass Rate Trend Chart */}
            {trendChartData.length > 0 && (
                <div style={{ ...cardStyle, marginBottom: '1.5rem' }}>
                    <h3 style={{ fontSize: '1rem', fontWeight: 600, marginBottom: '1rem' }}>Pass Rate & Run Volume</h3>
                    <ResponsiveContainer width="100%" height={350}>
                        <ComposedChart data={trendChartData}>
                            <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                            <XAxis dataKey="date" tick={{ fontSize: 12 }} />
                            <YAxis yAxisId="left" domain={[0, 100]} tick={{ fontSize: 12 }} label={{ value: 'Pass Rate %', angle: -90, position: 'insideLeft', style: { fontSize: 12 } }} />
                            <YAxis yAxisId="right" orientation="right" tick={{ fontSize: 12 }} label={{ value: 'Runs', angle: 90, position: 'insideRight', style: { fontSize: 12 } }} />
                            <Tooltip content={<CustomTooltip />} />
                            <Legend />
                            <Bar yAxisId="right" dataKey="runs" name="Run Count" fill="rgba(59,130,246,0.3)" radius={[4, 4, 0, 0]} />
                            <Line yAxisId="left" type="monotone" dataKey="pass_rate" name="Pass Rate" stroke="var(--success)" strokeWidth={2} dot={{ r: 3 }} />
                        </ComposedChart>
                    </ResponsiveContainer>
                </div>
            )}

            {/* Latency Distribution Chart */}
            {latencyDist.length > 0 && (
                <div style={{ ...cardStyle, marginBottom: '1.5rem' }}>
                    <h3 style={{ fontSize: '1rem', fontWeight: 600, marginBottom: '1rem' }}>Latency Distribution</h3>
                    <div style={{ display: 'grid', gridTemplateColumns: latencyDist.length > 1 ? '1fr 1fr' : '1fr', gap: '1rem', marginBottom: '1rem' }}>
                        {latencyDist.map((prov, i) => (
                            <div key={prov.provider_id} style={{ border: '1px solid var(--border)', borderRadius: 'var(--radius)', padding: '1rem' }}>
                                <div style={{ fontWeight: 600, marginBottom: '0.5rem' }}>{prov.provider_name}</div>
                                <div style={{ display: 'flex', gap: '1rem', fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '0.75rem', flexWrap: 'wrap' }}>
                                    <span>p50: {prov.percentiles.p50}ms</span>
                                    <span>p75: {prov.percentiles.p75}ms</span>
                                    <span>p90: {prov.percentiles.p90}ms</span>
                                    <span>p95: {prov.percentiles.p95}ms</span>
                                    <span>p99: {prov.percentiles.p99}ms</span>
                                </div>
                                <ResponsiveContainer width="100%" height={200}>
                                    <BarChart data={prov.histogram}>
                                        <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                                        <XAxis dataKey="bucket" tick={{ fontSize: 10 }} />
                                        <YAxis tick={{ fontSize: 10 }} />
                                        <Tooltip content={<CustomTooltip />} />
                                        <Bar dataKey="count" fill={PROVIDER_COLORS[i % PROVIDER_COLORS.length]} radius={[4, 4, 0, 0]} />
                                    </BarChart>
                                </ResponsiveContainer>
                            </div>
                        ))}
                    </div>
                </div>
            )}

            {/* Cost Tracking Chart */}
            {costChartData.length > 0 && (
                <div style={{ ...cardStyle, marginBottom: '1.5rem' }}>
                    <h3 style={{ fontSize: '1rem', fontWeight: 600, marginBottom: '1rem' }}>Daily Cost by Provider</h3>
                    <ResponsiveContainer width="100%" height={300}>
                        <AreaChart data={costChartData}>
                            <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                            <XAxis dataKey="date" tick={{ fontSize: 12 }} />
                            <YAxis tick={{ fontSize: 12 }} tickFormatter={v => `$${v}`} />
                            <Tooltip content={<CustomTooltip />} />
                            <Legend />
                            {costProviderIds.map((pid, i) => (
                                <Area
                                    key={pid}
                                    type="monotone"
                                    dataKey={pid}
                                    name={providerName[pid] || pid}
                                    stackId="cost"
                                    fill={PROVIDER_COLORS[i % PROVIDER_COLORS.length]}
                                    stroke={PROVIDER_COLORS[i % PROVIDER_COLORS.length]}
                                    fillOpacity={0.6}
                                />
                            ))}
                        </AreaChart>
                    </ResponsiveContainer>
                </div>
            )}

            {/* Dataset Performance */}
            {datasetPerformance.length > 0 && (
                <div style={{ ...cardStyle, marginBottom: '1.5rem' }}>
                    <h3 style={{ fontSize: '1rem', fontWeight: 600, marginBottom: '1rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                        <Database size={16} style={{ color: 'var(--text-secondary)' }} />
                        Dataset Performance
                    </h3>
                    <div style={{ overflowX: 'auto' }}>
                        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.85rem' }}>
                            <thead>
                                <tr>
                                    <th style={{ padding: '0.5rem 0.75rem', textAlign: 'left', borderBottom: '2px solid var(--border-subtle)', fontWeight: 600, color: 'var(--text-secondary)' }}>Dataset</th>
                                    <th style={{ padding: '0.5rem 0.75rem', textAlign: 'right', borderBottom: '2px solid var(--border-subtle)', fontWeight: 600, color: 'var(--text-secondary)' }}>Runs</th>
                                    <th style={{ padding: '0.5rem 0.75rem', textAlign: 'right', borderBottom: '2px solid var(--border-subtle)', fontWeight: 600, color: 'var(--text-secondary)' }}>Avg Pass Rate</th>
                                    <th style={{ padding: '0.5rem 0.75rem', textAlign: 'right', borderBottom: '2px solid var(--border-subtle)', fontWeight: 600, color: 'var(--text-secondary)' }}>Avg Latency</th>
                                    <th style={{ padding: '0.5rem 0.75rem', textAlign: 'right', borderBottom: '2px solid var(--border-subtle)', fontWeight: 600, color: 'var(--text-secondary)' }}>Total Cost</th>
                                    <th style={{ padding: '0.5rem 0.75rem', textAlign: 'left', borderBottom: '2px solid var(--border-subtle)', fontWeight: 600, color: 'var(--text-secondary)' }}>Best Provider</th>
                                </tr>
                            </thead>
                            <tbody>
                                {datasetPerformance.map(dp => (
                                    <tr key={dp.dataset_id}>
                                        <td style={{ padding: '0.5rem 0.75rem', borderBottom: '1px solid var(--border-subtle)' }}>
                                            <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
                                                {dp.is_golden && <Star size={12} style={{ color: '#f59e0b', fill: '#f59e0b' }} />}
                                                <span style={{ fontWeight: 500 }}>{dp.dataset_name}</span>
                                            </div>
                                        </td>
                                        <td style={{ padding: '0.5rem 0.75rem', borderBottom: '1px solid var(--border-subtle)', textAlign: 'right' }}>{dp.total_runs}</td>
                                        <td style={{ padding: '0.5rem 0.75rem', borderBottom: '1px solid var(--border-subtle)', textAlign: 'right' }}>
                                            <span style={{ fontWeight: 600, color: passRateColor(dp.avg_pass_rate) }}>
                                                {dp.avg_pass_rate.toFixed(1)}%
                                            </span>
                                        </td>
                                        <td style={{ padding: '0.5rem 0.75rem', borderBottom: '1px solid var(--border-subtle)', textAlign: 'right' }}>
                                            {dp.avg_latency_ms != null ? `${Math.round(dp.avg_latency_ms)}ms` : '-'}
                                        </td>
                                        <td style={{ padding: '0.5rem 0.75rem', borderBottom: '1px solid var(--border-subtle)', textAlign: 'right' }}>
                                            ${dp.total_cost.toFixed(2)}
                                        </td>
                                        <td style={{ padding: '0.5rem 0.75rem', borderBottom: '1px solid var(--border-subtle)' }}>
                                            {dp.best_provider_name || '-'}
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                </div>
            )}

            {/* Regression Alerts */}
            {regressions.length > 0 && (
                <div style={{ ...cardStyle }}>
                    <h3 style={{ fontSize: '1rem', fontWeight: 600, marginBottom: '1rem' }}>Regression Alerts</h3>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                        {regressions.map((reg, i) => {
                            const severe = reg.drop_percentage > 50;
                            return (
                                <div
                                    key={i}
                                    style={{
                                        padding: '0.75rem 1rem',
                                        borderRadius: 'var(--radius)',
                                        background: severe ? 'rgba(239,68,68,0.1)' : 'rgba(245,158,11,0.1)',
                                        border: `1px solid ${severe ? 'rgba(239,68,68,0.3)' : 'rgba(245,158,11,0.3)'}`,
                                        display: 'flex',
                                        justifyContent: 'space-between',
                                        alignItems: 'center',
                                        flexWrap: 'wrap',
                                        gap: '0.5rem',
                                    }}
                                >
                                    <div>
                                        <span style={{ fontWeight: 600 }}>{reg.spec_name}</span>
                                        <span style={{ color: 'var(--text-secondary)', fontSize: '0.85rem', marginLeft: '0.5rem' }}>
                                            ({providerName[reg.provider_id] || reg.provider_id})
                                        </span>
                                    </div>
                                    <div style={{ display: 'flex', gap: '1rem', alignItems: 'center', fontSize: '0.85rem' }}>
                                        <span style={{ color: 'var(--text-secondary)' }}>{reg.previous_pass_rate.toFixed(1)}%</span>
                                        <span style={{ color: severe ? 'var(--danger)' : 'var(--warning)', fontWeight: 600 }}>
                                            → {reg.current_pass_rate.toFixed(1)}%
                                        </span>
                                        <span style={{ color: severe ? 'var(--danger)' : 'var(--warning)', fontWeight: 700 }}>
                                            -{reg.drop_percentage.toFixed(1)}%
                                        </span>
                                    </div>
                                </div>
                            );
                        })}
                    </div>
                </div>
            )}
        </div>
    );
}
