'use client';
import React, { useState, useEffect, useCallback } from 'react';
import dynamic from 'next/dynamic';
import { Loader2, TrendingUp } from 'lucide-react';
import { API_BASE } from '@/lib/api';
import { useProject } from '@/contexts/ProjectContext';
import { timeAgo } from '@/lib/formatting';
import { getResponseTimeColor, getErrorRateColor } from '@/lib/colors';
import type { TrendData } from './types';

const LineChart = dynamic(() => import('recharts').then(mod => mod.LineChart), { ssr: false });
const BarChart = dynamic(() => import('recharts').then(mod => mod.BarChart), { ssr: false });
const Bar = dynamic(() => import('recharts').then(mod => mod.Bar), { ssr: false });
const Line = dynamic(() => import('recharts').then(mod => mod.Line), { ssr: false });
const XAxis = dynamic(() => import('recharts').then(mod => mod.XAxis), { ssr: false });
const YAxis = dynamic(() => import('recharts').then(mod => mod.YAxis), { ssr: false });
const CartesianGrid = dynamic(() => import('recharts').then(mod => mod.CartesianGrid), { ssr: false });
const Tooltip = dynamic(() => import('recharts').then(mod => mod.Tooltip), { ssr: false });
const Legend = dynamic(() => import('recharts').then(mod => mod.Legend), { ssr: false });
const ResponsiveContainer = dynamic(() => import('recharts').then(mod => mod.ResponsiveContainer), { ssr: false });

interface TrendViewProps {
    specName: string;
}

export default function TrendView({ specName }: TrendViewProps) {
    const { currentProject } = useProject();
    const projectId = currentProject?.id || 'default';

    const [runs, setRuns] = useState<TrendData[]>([]);
    const [loading, setLoading] = useState(true);

    const fetchTrends = useCallback(async () => {
        setLoading(true);
        try {
            const res = await fetch(
                `${API_BASE}/load-testing/runs/trends?spec_name=${encodeURIComponent(specName)}&limit=20&project_id=${projectId}`
            );
            if (res.ok) {
                const data = await res.json();
                setRuns(Array.isArray(data) ? data : data.runs || []);
            }
        } catch {
            // ignore
        } finally {
            setLoading(false);
        }
    }, [specName, projectId]);

    useEffect(() => {
        fetchTrends();
    }, [fetchTrends]);

    if (loading) {
        return (
            <div style={{ textAlign: 'center', padding: '3rem', color: 'var(--text-secondary)' }}>
                <Loader2 size={24} style={{ animation: 'spin 1s linear infinite', margin: '0 auto 0.5rem' }} />
                <p>Loading trend data...</p>
            </div>
        );
    }

    if (runs.length === 0) {
        return (
            <div style={{
                textAlign: 'center', padding: '3rem',
                background: 'var(--surface)', borderRadius: 'var(--radius)',
                border: '1px solid var(--border)',
            }}>
                <TrendingUp size={40} style={{ color: 'var(--text-secondary)', margin: '0 auto 1rem' }} />
                <p style={{ color: 'var(--text-secondary)' }}>No trend data available for {specName}</p>
            </div>
        );
    }

    const chartData = runs.map((r, i) => ({
        index: i + 1,
        date: r.created_at ? new Date(r.created_at).toLocaleDateString([], { month: 'short', day: 'numeric' }) : `#${i + 1}`,
        p95: r.p95_response_time_ms || 0,
        avg: r.avg_response_time_ms || 0,
        rps: r.requests_per_second || 0,
        error_rate: r.error_rate ?? 0,
        vus: r.vus || 0,
        status: r.status,
    }));

    const tooltipStyle = { background: 'var(--background)', border: '1px solid #30363d', borderRadius: '6px', fontSize: '0.75rem' };

    return (
        <div>
            <h4 style={{ fontSize: '0.9rem', fontWeight: 600, marginBottom: '1rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <TrendingUp size={16} style={{ color: 'var(--primary)' }} />
                Trends for {specName}
            </h4>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem', marginBottom: '1.5rem' }}>
                {/* Response Time Trend */}
                <div style={{
                    background: 'var(--surface)', border: '1px solid var(--border)',
                    borderRadius: 'var(--radius)', padding: '1rem',
                }}>
                    <h5 style={{ fontSize: '0.8rem', fontWeight: 600, marginBottom: '0.75rem' }}>Response Time Trend</h5>
                    <ResponsiveContainer width="100%" height={220}>
                        <LineChart data={chartData}>
                            <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.1)" />
                            <XAxis dataKey="date" tick={{ fontSize: 10, fill: 'var(--text-secondary)' }} />
                            <YAxis tick={{ fontSize: 10, fill: 'var(--text-secondary)' }} unit="ms" />
                            <Tooltip contentStyle={tooltipStyle} labelStyle={{ color: 'var(--text-secondary)' }} />
                            <Legend wrapperStyle={{ fontSize: '0.75rem' }} />
                            <Line type="monotone" dataKey="p95" name="P95" stroke="var(--warning)" strokeWidth={2} dot={{ r: 3 }} />
                            <Line type="monotone" dataKey="avg" name="Avg" stroke="var(--primary)" strokeWidth={2} dot={{ r: 3 }} />
                        </LineChart>
                    </ResponsiveContainer>
                </div>

                {/* RPS Trend */}
                <div style={{
                    background: 'var(--surface)', border: '1px solid var(--border)',
                    borderRadius: 'var(--radius)', padding: '1rem',
                }}>
                    <h5 style={{ fontSize: '0.8rem', fontWeight: 600, marginBottom: '0.75rem' }}>Throughput Trend (RPS)</h5>
                    <ResponsiveContainer width="100%" height={220}>
                        <LineChart data={chartData}>
                            <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.1)" />
                            <XAxis dataKey="date" tick={{ fontSize: 10, fill: 'var(--text-secondary)' }} />
                            <YAxis tick={{ fontSize: 10, fill: 'var(--text-secondary)' }} />
                            <Tooltip contentStyle={tooltipStyle} labelStyle={{ color: 'var(--text-secondary)' }} />
                            <Line type="monotone" dataKey="rps" name="RPS" stroke="var(--success)" strokeWidth={2} dot={{ r: 3 }} />
                        </LineChart>
                    </ResponsiveContainer>
                </div>

                {/* Error Rate Trend */}
                <div style={{
                    background: 'var(--surface)', border: '1px solid var(--border)',
                    borderRadius: 'var(--radius)', padding: '1rem',
                }}>
                    <h5 style={{ fontSize: '0.8rem', fontWeight: 600, marginBottom: '0.75rem' }}>Error Rate Trend (%)</h5>
                    <ResponsiveContainer width="100%" height={220}>
                        <BarChart data={chartData}>
                            <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.1)" />
                            <XAxis dataKey="date" tick={{ fontSize: 10, fill: 'var(--text-secondary)' }} />
                            <YAxis tick={{ fontSize: 10, fill: 'var(--text-secondary)' }} unit="%" />
                            <Tooltip contentStyle={tooltipStyle} labelStyle={{ color: 'var(--text-secondary)' }} />
                            <Bar dataKey="error_rate" name="Error Rate" radius={[4, 4, 0, 0]} fill="var(--danger)" />
                        </BarChart>
                    </ResponsiveContainer>
                </div>
            </div>

            {/* Run Summary Table */}
            <div style={{
                background: 'var(--surface)', border: '1px solid var(--border)',
                borderRadius: 'var(--radius)', padding: '1rem',
            }}>
                <h5 style={{ fontSize: '0.8rem', fontWeight: 600, marginBottom: '0.75rem' }}>Run History</h5>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.8rem' }}>
                    <thead>
                        <tr style={{ borderBottom: '1px solid var(--border)' }}>
                            <th style={{ textAlign: 'left', padding: '0.5rem', color: 'var(--text-secondary)', fontWeight: 600 }}>Date</th>
                            <th style={{ textAlign: 'center', padding: '0.5rem', color: 'var(--text-secondary)', fontWeight: 600 }}>Status</th>
                            <th style={{ textAlign: 'right', padding: '0.5rem', color: 'var(--text-secondary)', fontWeight: 600 }}>VUs</th>
                            <th style={{ textAlign: 'right', padding: '0.5rem', color: 'var(--text-secondary)', fontWeight: 600 }}>P95 (ms)</th>
                            <th style={{ textAlign: 'right', padding: '0.5rem', color: 'var(--text-secondary)', fontWeight: 600 }}>RPS</th>
                            <th style={{ textAlign: 'right', padding: '0.5rem', color: 'var(--text-secondary)', fontWeight: 600 }}>Error Rate %</th>
                        </tr>
                    </thead>
                    <tbody>
                        {runs.map((run, i) => {
                            const statusColor = run.status === 'completed' ? 'var(--success)'
                                : run.status === 'failed' ? 'var(--danger)'
                                : 'var(--text-secondary)';
                            const statusBg = run.status === 'completed' ? 'rgba(34, 197, 94, 0.1)'
                                : run.status === 'failed' ? 'var(--danger-muted)'
                                : 'rgba(156, 163, 175, 0.1)';
                            const errRate = run.error_rate ?? 0;
                            return (
                                <tr key={run.run_id || i} style={{
                                    borderBottom: '1px solid var(--border)',
                                    background: i % 2 === 0 ? 'transparent' : 'rgba(0,0,0,0.02)',
                                }}>
                                    <td style={{ padding: '0.5rem', color: 'var(--text-secondary)', fontSize: '0.75rem' }}>
                                        {run.created_at ? timeAgo(run.created_at) : '-'}
                                    </td>
                                    <td style={{ padding: '0.5rem', textAlign: 'center' }}>
                                        <span style={{
                                            padding: '0.15rem 0.5rem', borderRadius: '999px', fontSize: '0.65rem',
                                            fontWeight: 600, background: statusBg, color: statusColor,
                                        }}>
                                            {run.status}
                                        </span>
                                    </td>
                                    <td style={{ padding: '0.5rem', textAlign: 'right' }}>{run.vus || '-'}</td>
                                    <td style={{ padding: '0.5rem', textAlign: 'right', color: getResponseTimeColor(run.p95_response_time_ms || 0), fontWeight: 500 }}>
                                        {run.p95_response_time_ms ? run.p95_response_time_ms.toFixed(0) : '-'}
                                    </td>
                                    <td style={{ padding: '0.5rem', textAlign: 'right' }}>
                                        {run.requests_per_second ? run.requests_per_second.toFixed(1) : '-'}
                                    </td>
                                    <td style={{ padding: '0.5rem', textAlign: 'right', color: getErrorRateColor(errRate) }}>
                                        {errRate.toFixed(2)}%
                                    </td>
                                </tr>
                            );
                        })}
                    </tbody>
                </table>
            </div>
        </div>
    );
}
