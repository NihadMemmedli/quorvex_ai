'use client';
import React, { useState, useEffect } from 'react';
import { ComposedChart, Line, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';
import { TrendingUp, TrendingDown, Minus } from 'lucide-react';
import { API_BASE } from '@/lib/api';
import { getAuthHeaders } from '@/lib/styles';
import type { PassRateTrendsResponse, SpecPerformance } from './types';

interface TrendsTabProps {
    projectId?: string;
    period: string;
    testType: string;
    setTestType: (t: string) => void;
}

function formatDate(dateStr: string): string {
    try {
        const d = new Date(dateStr);
        return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
    } catch {
        return dateStr;
    }
}

function TrendIcon({ trend }: { trend: 'up' | 'down' | 'flat' }) {
    if (trend === 'up') return <TrendingUp size={14} style={{ color: 'var(--success)' }} />;
    if (trend === 'down') return <TrendingDown size={14} style={{ color: 'var(--danger)' }} />;
    return <Minus size={14} style={{ color: 'var(--text-secondary)' }} />;
}

export function TrendsTab({ projectId, period, testType, setTestType }: TrendsTabProps) {
    const [trends, setTrends] = useState<PassRateTrendsResponse | null>(null);
    const [specs, setSpecs] = useState<SpecPerformance[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        setLoading(true);
        setError(null);
        const base = projectId ? `project_id=${encodeURIComponent(projectId)}&` : '';
        const typeParam = testType !== 'all' ? `&test_type=${testType}` : '';

        Promise.all([
            fetch(`${API_BASE}/analytics/pass-rate-trends?${base}period=${period}${typeParam}`, { headers: getAuthHeaders() })
                .then(r => { if (!r.ok) throw new Error('Failed to fetch trends'); return r.json(); }),
            fetch(`${API_BASE}/analytics/spec-performance?${base}period=${period}${typeParam}`, { headers: getAuthHeaders() })
                .then(r => { if (!r.ok) throw new Error('Failed to fetch spec performance'); return r.json(); }),
        ])
            .then(([trendsData, specsData]) => {
                setTrends(trendsData);
                setSpecs(specsData.specs || []);
                setLoading(false);
            })
            .catch(err => { setError(err.message); setLoading(false); });
    }, [projectId, period, testType]);

    if (loading) return <div style={{ textAlign: 'center', padding: '2rem', color: 'var(--text-secondary)' }}>Loading...</div>;
    if (error) return <div style={{ textAlign: 'center', padding: '2rem', color: 'var(--danger)' }}>{error}</div>;

    const chartData = (trends?.data_points || []).map(dp => ({
        ...dp,
        date: formatDate(dp.date),
    }));

    const summary = trends?.summary;

    return (
        <div>
            {/* Test type filter */}
            <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '1.5rem' }}>
                {['all', 'api', 'browser'].map(t => (
                    <button
                        key={t}
                        onClick={() => setTestType(t)}
                        style={{
                            padding: '0.4rem 1rem',
                            borderRadius: 'var(--radius)',
                            border: '1px solid var(--border)',
                            background: testType === t ? 'var(--primary)' : 'var(--surface)',
                            color: testType === t ? '#fff' : 'var(--text-secondary)',
                            cursor: 'pointer',
                            fontSize: '0.85rem',
                            fontWeight: 500,
                            textTransform: 'capitalize',
                        }}
                    >
                        {t === 'all' ? 'All' : t === 'api' ? 'API' : 'Browser'}
                    </button>
                ))}
            </div>

            {/* Summary cards */}
            {summary && (
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '1rem', marginBottom: '1.5rem' }}>
                    <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 'var(--radius)', padding: '1.5rem' }}>
                        <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: '0.5rem' }}>Avg Pass Rate</div>
                        <div style={{ fontSize: '1.75rem', fontWeight: 700, color: 'var(--success)' }}>{summary.avg_pass_rate.toFixed(1)}%</div>
                    </div>
                    <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 'var(--radius)', padding: '1.5rem' }}>
                        <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: '0.5rem' }}>Total Runs</div>
                        <div style={{ fontSize: '1.75rem', fontWeight: 700 }}>{summary.total_runs}</div>
                    </div>
                    <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 'var(--radius)', padding: '1.5rem' }}>
                        <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: '0.5rem' }}>Trend</div>
                        <div style={{ fontSize: '1.75rem', fontWeight: 700, display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                            <TrendIcon trend={summary.trend_direction} />
                            <span style={{ textTransform: 'capitalize' }}>{summary.trend_direction}</span>
                        </div>
                    </div>
                </div>
            )}

            {/* Chart */}
            {chartData.length > 0 ? (
                <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 'var(--radius)', padding: '1.5rem', marginBottom: '2rem' }}>
                    <h3 style={{ fontSize: '1rem', fontWeight: 600, marginBottom: '1rem' }}>Pass Rate & Run Volume</h3>
                    <ResponsiveContainer width="100%" height={350}>
                        <ComposedChart data={chartData}>
                            <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                            <XAxis dataKey="date" tick={{ fontSize: 12 }} />
                            <YAxis yAxisId="left" domain={[0, 100]} tick={{ fontSize: 12 }} label={{ value: 'Pass Rate %', angle: -90, position: 'insideLeft', style: { fontSize: 12 } }} />
                            <YAxis yAxisId="right" orientation="right" tick={{ fontSize: 12 }} label={{ value: 'Total Runs', angle: 90, position: 'insideRight', style: { fontSize: 12 } }} />
                            <Tooltip />
                            <Bar yAxisId="right" dataKey="total_runs" fill="rgba(59,130,246,0.3)" radius={[4, 4, 0, 0]} />
                            <Line yAxisId="left" type="monotone" dataKey="pass_rate" stroke="var(--success)" strokeWidth={2} dot={{ r: 3 }} />
                        </ComposedChart>
                    </ResponsiveContainer>
                </div>
            ) : (
                <div style={{ textAlign: 'center', padding: '3rem', color: 'var(--text-secondary)', background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 'var(--radius)', marginBottom: '2rem' }}>
                    No trend data available for this period.
                </div>
            )}

            {/* Spec Performance table */}
            <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 'var(--radius)', padding: '1.5rem' }}>
                <h3 style={{ fontSize: '1rem', fontWeight: 600, marginBottom: '1rem' }}>Spec Performance</h3>
                {specs.length > 0 ? (
                    <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                        <thead>
                            <tr>
                                <th style={{ padding: '0.75rem', textAlign: 'left', borderBottom: '2px solid var(--border)', color: 'var(--text-secondary)', fontSize: '0.85rem' }}>Name</th>
                                <th style={{ padding: '0.75rem', textAlign: 'left', borderBottom: '2px solid var(--border)', color: 'var(--text-secondary)', fontSize: '0.85rem' }}>Runs</th>
                                <th style={{ padding: '0.75rem', textAlign: 'left', borderBottom: '2px solid var(--border)', color: 'var(--text-secondary)', fontSize: '0.85rem' }}>Pass Rate</th>
                                <th style={{ padding: '0.75rem', textAlign: 'left', borderBottom: '2px solid var(--border)', color: 'var(--text-secondary)', fontSize: '0.85rem' }}>Last Run</th>
                                <th style={{ padding: '0.75rem', textAlign: 'left', borderBottom: '2px solid var(--border)', color: 'var(--text-secondary)', fontSize: '0.85rem' }}>Trend</th>
                            </tr>
                        </thead>
                        <tbody>
                            {specs.map(spec => {
                                const rateColor = spec.pass_rate > 80 ? 'var(--success)' : spec.pass_rate > 50 ? 'var(--warning)' : 'var(--danger)';
                                return (
                                    <tr key={spec.spec_name}>
                                        <td style={{ padding: '0.75rem', borderBottom: '1px solid var(--border)', fontWeight: 500 }}>{spec.spec_name}</td>
                                        <td style={{ padding: '0.75rem', borderBottom: '1px solid var(--border)' }}>{spec.total_runs}</td>
                                        <td style={{ padding: '0.75rem', borderBottom: '1px solid var(--border)', color: rateColor, fontWeight: 600 }}>{spec.pass_rate.toFixed(1)}%</td>
                                        <td style={{ padding: '0.75rem', borderBottom: '1px solid var(--border)', color: 'var(--text-secondary)', fontSize: '0.85rem' }}>
                                            {spec.last_run_at ? formatDate(spec.last_run_at) : '-'}
                                        </td>
                                        <td style={{ padding: '0.75rem', borderBottom: '1px solid var(--border)' }}>
                                            <TrendIcon trend={spec.trend} />
                                        </td>
                                    </tr>
                                );
                            })}
                        </tbody>
                    </table>
                ) : (
                    <div style={{ textAlign: 'center', padding: '2rem', color: 'var(--text-secondary)' }}>No spec performance data available.</div>
                )}
            </div>
        </div>
    );
}
