'use client';
import React, { useState, useEffect, useCallback } from 'react';
import dynamic from 'next/dynamic';
import { Activity, CheckCircle, Clock, Zap, Loader2, TrendingUp } from 'lucide-react';
import { API_BASE } from '@/lib/api';
import { useProject } from '@/contexts/ProjectContext';
import { timeAgo } from '@/lib/formatting';
import { getResponseTimeColor } from '@/lib/colors';
import type { DashboardData } from './types';

const LazyLineChart = dynamic(
    () => import('recharts').then(mod => {
        const { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } = mod;
        return {
            default: ({ data }: { data: Array<{ date: string; p95: number; count: number }> }) => (
                <ResponsiveContainer width="100%" height={220}>
                    <LineChart data={data}>
                        <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.1)" />
                        <XAxis dataKey="date" tick={{ fontSize: 10, fill: 'var(--text-secondary)' }} />
                        <YAxis tick={{ fontSize: 10, fill: 'var(--text-secondary)' }} unit="ms" />
                        <Tooltip
                            contentStyle={{ background: 'var(--background)', border: '1px solid #30363d', borderRadius: '6px', fontSize: '0.75rem' }}
                            labelStyle={{ color: 'var(--text-secondary)' }}
                        />
                        <Line type="monotone" dataKey="p95" name="Avg P95" stroke="var(--warning)" strokeWidth={2} dot={{ r: 3 }} />
                    </LineChart>
                </ResponsiveContainer>
            ),
        };
    }),
    { ssr: false, loading: () => <div style={{ height: 220, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-secondary)', fontSize: '0.8rem' }}>Loading chart...</div> }
);

interface OverviewTabProps {
    onNavigateToRun: (runId: string) => void;
}

export default function OverviewTab({ onNavigateToRun }: OverviewTabProps) {
    const { currentProject } = useProject();
    const projectId = currentProject?.id || 'default';

    const [data, setData] = useState<DashboardData | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    const fetchDashboard = useCallback(async () => {
        setLoading(true);
        setError(null);
        try {
            const res = await fetch(`${API_BASE}/load-testing/dashboard?project_id=${projectId}`);
            if (res.ok) {
                setData(await res.json());
            } else {
                setError('Failed to load dashboard data');
            }
        } catch {
            setError('Failed to connect to server');
        } finally {
            setLoading(false);
        }
    }, [projectId]);

    useEffect(() => {
        fetchDashboard();
    }, [fetchDashboard]);

    if (loading) {
        return (
            <div style={{ textAlign: 'center', padding: '3rem', color: 'var(--text-secondary)' }}>
                <Loader2 size={24} style={{ animation: 'spin 1s linear infinite', margin: '0 auto 0.5rem' }} />
                <p>Loading dashboard...</p>
            </div>
        );
    }

    if (error || !data) {
        return (
            <div style={{
                textAlign: 'center', padding: '3rem',
                background: 'var(--surface)', borderRadius: 'var(--radius)',
                border: '1px solid var(--border)',
            }}>
                <Activity size={40} style={{ color: 'var(--text-secondary)', margin: '0 auto 1rem' }} />
                <p style={{ color: 'var(--text-secondary)' }}>{error || 'No data available'}</p>
            </div>
        );
    }

    const passRateColor = data.pass_rate >= 80 ? 'var(--success)' : data.pass_rate >= 50 ? 'var(--warning)' : 'var(--danger)';

    const stats = [
        { label: 'Total Runs', value: String(data.total_runs), icon: Activity, color: 'var(--primary)' },
        { label: 'Pass Rate', value: `${data.pass_rate.toFixed(1)}%`, icon: CheckCircle, color: passRateColor },
        { label: 'Avg P95', value: data.avg_p95_ms ? `${data.avg_p95_ms.toFixed(0)}ms` : '-', icon: Clock, color: data.avg_p95_ms ? getResponseTimeColor(data.avg_p95_ms) : 'var(--text-secondary)' },
        { label: 'Avg RPS', value: data.avg_rps ? data.avg_rps.toFixed(1) : '-', icon: Zap, color: 'var(--accent)' },
    ];

    return (
        <div>
            {/* Stat Cards */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '0.75rem', marginBottom: '1.5rem' }}>
                {stats.map(stat => (
                    <div key={stat.label} style={{
                        background: 'var(--surface)', border: '1px solid var(--border)',
                        borderRadius: 'var(--radius)', padding: '1rem',
                    }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', marginBottom: '0.5rem' }}>
                            <stat.icon size={14} style={{ color: stat.color }} />
                            <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>{stat.label}</span>
                        </div>
                        <div style={{ fontSize: '1.5rem', fontWeight: 700, color: stat.color }}>
                            {stat.value}
                        </div>
                    </div>
                ))}
            </div>

            {/* Two Column: Recent Runs + P95 Trend Chart */}
            <div style={{ display: 'grid', gridTemplateColumns: '3fr 2fr', gap: '1rem', marginBottom: '1.5rem' }}>
                {/* Recent Runs */}
                <div style={{
                    background: 'var(--surface)', border: '1px solid var(--border)',
                    borderRadius: 'var(--radius)', padding: '1rem',
                }}>
                    <h4 style={{ fontSize: '0.85rem', fontWeight: 600, marginBottom: '0.75rem' }}>Recent Runs</h4>
                    {data.recent_runs.length === 0 ? (
                        <p style={{ color: 'var(--text-secondary)', fontSize: '0.8rem' }}>No runs yet</p>
                    ) : (
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.35rem' }}>
                            {data.recent_runs.map(run => {
                                const statusColor = run.status === 'completed' ? 'var(--success)'
                                    : run.status === 'failed' ? 'var(--danger)'
                                    : run.status === 'running' ? 'var(--primary)'
                                    : 'var(--text-secondary)';
                                return (
                                    <div
                                        key={run.id}
                                        onClick={() => onNavigateToRun(run.id)}
                                        style={{
                                            display: 'flex', alignItems: 'center', gap: '0.6rem',
                                            padding: '0.5rem 0.6rem', borderRadius: 'var(--radius)',
                                            cursor: 'pointer', fontSize: '0.8rem',
                                            transition: 'background 0.15s var(--ease-smooth)',
                                        }}
                                        onMouseEnter={e => (e.currentTarget.style.background = 'rgba(255,255,255,0.03)')}
                                        onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
                                    >
                                        <span style={{
                                            width: '8px', height: '8px', borderRadius: '50%',
                                            background: statusColor, flexShrink: 0,
                                        }} />
                                        <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                            {run.spec_name || run.id}
                                        </span>
                                        <span style={{ color: getResponseTimeColor(run.p95_response_time_ms || 0), fontWeight: 500, fontSize: '0.75rem' }}>
                                            {run.p95_response_time_ms ? `${run.p95_response_time_ms.toFixed(0)}ms` : '-'}
                                        </span>
                                        <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', minWidth: '55px', textAlign: 'right' }}>
                                            {run.requests_per_second ? `${run.requests_per_second.toFixed(1)} rps` : '-'}
                                        </span>
                                        {run.thresholds_passed != null && (
                                            <span style={{
                                                padding: '0.1rem 0.35rem', borderRadius: '999px', fontSize: '0.6rem',
                                                fontWeight: 600,
                                                background: run.thresholds_passed ? 'rgba(34, 197, 94, 0.1)' : 'var(--danger-muted)',
                                                color: run.thresholds_passed ? 'var(--success)' : 'var(--danger)',
                                            }}>
                                                {run.thresholds_passed ? 'PASS' : 'FAIL'}
                                            </span>
                                        )}
                                        <span style={{ fontSize: '0.7rem', color: 'var(--text-secondary)', minWidth: '50px', textAlign: 'right' }}>
                                            {timeAgo(run.created_at)}
                                        </span>
                                    </div>
                                );
                            })}
                        </div>
                    )}
                </div>

                {/* P95 Trend Chart */}
                <div style={{
                    background: 'var(--surface)', border: '1px solid var(--border)',
                    borderRadius: 'var(--radius)', padding: '1rem',
                }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', marginBottom: '0.75rem' }}>
                        <TrendingUp size={14} style={{ color: 'var(--warning)' }} />
                        <h4 style={{ fontSize: '0.85rem', fontWeight: 600 }}>P95 Response Time Trend</h4>
                    </div>
                    {data.p95_trend.length === 0 ? (
                        <p style={{ color: 'var(--text-secondary)', fontSize: '0.8rem' }}>No trend data yet</p>
                    ) : (
                        <LazyLineChart data={data.p95_trend} />
                    )}
                </div>
            </div>

            {/* Top Slow Endpoints */}
            {data.top_slow_endpoints.length > 0 && (
                <div style={{
                    background: 'var(--surface)', border: '1px solid var(--border)',
                    borderRadius: 'var(--radius)', padding: '1rem',
                }}>
                    <h4 style={{ fontSize: '0.85rem', fontWeight: 600, marginBottom: '0.75rem' }}>Top Slow Endpoints</h4>
                    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.8rem' }}>
                        <thead>
                            <tr style={{ borderBottom: '1px solid var(--border)' }}>
                                <th style={{ textAlign: 'left', padding: '0.5rem', color: 'var(--text-secondary)', fontWeight: 600 }}>Endpoint</th>
                                <th style={{ textAlign: 'right', padding: '0.5rem', color: 'var(--text-secondary)', fontWeight: 600 }}>Avg P95 (ms)</th>
                                <th style={{ textAlign: 'right', padding: '0.5rem', color: 'var(--text-secondary)', fontWeight: 600 }}>Occurrences</th>
                            </tr>
                        </thead>
                        <tbody>
                            {data.top_slow_endpoints.slice(0, 5).map((ep, i) => (
                                <tr key={i} style={{ borderBottom: '1px solid var(--border)' }}>
                                    <td style={{ padding: '0.5rem', fontFamily: 'monospace', fontSize: '0.75rem' }}>{ep.endpoint}</td>
                                    <td style={{ padding: '0.5rem', textAlign: 'right', color: getResponseTimeColor(ep.avg_p95_ms), fontWeight: 500 }}>
                                        {ep.avg_p95_ms.toFixed(0)}
                                    </td>
                                    <td style={{ padding: '0.5rem', textAlign: 'right', color: 'var(--text-secondary)' }}>{ep.occurrence_count}</td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            )}

            {/* Total Requests */}
            {data.total_requests_all_time > 0 && (
                <div style={{
                    marginTop: '1rem', padding: '0.6rem 1rem',
                    background: 'var(--surface)', border: '1px solid var(--border)',
                    borderRadius: 'var(--radius)', fontSize: '0.8rem', color: 'var(--text-secondary)',
                    textAlign: 'center',
                }}>
                    {data.total_requests_all_time.toLocaleString()} total requests processed across all load tests
                </div>
            )}
        </div>
    );
}
