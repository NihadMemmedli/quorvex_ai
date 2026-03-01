'use client';
import React, { useMemo } from 'react';
import { ArrowLeft, ArrowUp, ArrowDown, Minus } from 'lucide-react';
import {
    LineChart, Line, AreaChart, Area,
    XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
} from 'recharts';
import type { LoadTestRun, ComparisonData, ComparisonDelta } from './types';

const COMPARISON_METRICS: Array<{ key: string; label: string; unit: string; lowerIsBetter: boolean }> = [
    { key: 'total_requests', label: 'Total Requests', unit: '', lowerIsBetter: false },
    { key: 'avg_response_time_ms', label: 'Avg Response Time', unit: 'ms', lowerIsBetter: true },
    { key: 'p95_response_time_ms', label: 'P95 Response Time', unit: 'ms', lowerIsBetter: true },
    { key: 'p99_response_time_ms', label: 'P99 Response Time', unit: 'ms', lowerIsBetter: true },
    { key: 'peak_rps', label: 'Peak RPS', unit: 'req/s', lowerIsBetter: false },
    { key: 'requests_per_second', label: 'Avg RPS', unit: 'req/s', lowerIsBetter: false },
    { key: 'failed_requests', label: 'Failed Requests', unit: '', lowerIsBetter: true },
    { key: 'error_rate', label: 'Error Rate', unit: '%', lowerIsBetter: true },
    { key: 'peak_vus', label: 'Peak VUs', unit: '', lowerIsBetter: false },
    { key: 'duration_seconds', label: 'Duration', unit: 's', lowerIsBetter: false },
];

interface ComparisonViewProps {
    data: ComparisonData;
    onBack: () => void;
}

export default React.memo(function ComparisonView({ data, onBack }: ComparisonViewProps) {
    const { run_a, run_b, deltas, run_a_timeseries, run_b_timeseries } = data;

    const formatDate = (d: string) => new Date(d).toLocaleDateString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });

    const getMetricValue = (run: LoadTestRun, key: string): number => {
        return (run as unknown as Record<string, number>)[key] ?? 0;
    };

    const formatMetricValue = (val: number, unit: string): string => {
        if (unit === 'ms' || unit === 'req/s' || unit === '%') return `${val.toFixed(1)}${unit}`;
        if (unit === 's') return `${val}${unit}`;
        return val.toLocaleString();
    };

    const mergedTimeseries = useMemo(() => {
        const map = new Map<number, Record<string, number>>();
        for (const p of run_a_timeseries) {
            const key = p.elapsed_seconds;
            const existing = map.get(key) || { elapsed_seconds: key };
            existing.a_response_time_avg = p.response_time_avg;
            existing.a_response_time_p95 = p.response_time_p95;
            existing.a_throughput = p.throughput;
            existing.a_vus = p.vus;
            existing.a_error_rate = p.error_rate;
            map.set(key, existing);
        }
        for (const p of run_b_timeseries) {
            const key = p.elapsed_seconds;
            const existing = map.get(key) || { elapsed_seconds: key };
            existing.b_response_time_avg = p.response_time_avg;
            existing.b_response_time_p95 = p.response_time_p95;
            existing.b_throughput = p.throughput;
            existing.b_vus = p.vus;
            existing.b_error_rate = p.error_rate;
            map.set(key, existing);
        }
        return Array.from(map.values()).sort((a, b) => a.elapsed_seconds - b.elapsed_seconds);
    }, [run_a_timeseries, run_b_timeseries]);

    const tooltipStyle = { background: 'var(--background)', border: '1px solid #30363d', borderRadius: '6px', fontSize: '0.75rem' };

    return (
        <div>
            {/* Header */}
            <div style={{ marginBottom: '1.5rem' }}>
                <button
                    onClick={onBack}
                    style={{
                        display: 'flex', alignItems: 'center', gap: '0.4rem',
                        padding: '0.4rem 0.8rem', background: 'none', border: 'none',
                        cursor: 'pointer', color: 'var(--primary)', fontSize: '0.85rem',
                        fontWeight: 500, marginBottom: '0.75rem',
                    }}
                >
                    <ArrowLeft size={16} /> Back to History
                </button>
                <div style={{
                    display: 'flex', alignItems: 'center', gap: '1rem',
                    fontSize: '0.85rem', color: 'var(--text-secondary)',
                }}>
                    <span>
                        <strong style={{ color: 'var(--primary)' }}>Run A:</strong>{' '}
                        {run_a.spec_name || run_a.script_path || run_a.id.slice(0, 8)} ({formatDate(run_a.created_at)})
                    </span>
                    <span style={{ color: 'var(--text-secondary)' }}>vs</span>
                    <span>
                        <strong style={{ color: 'var(--primary)' }}>Run B:</strong>{' '}
                        {run_b.spec_name || run_b.script_path || run_b.id.slice(0, 8)} ({formatDate(run_b.created_at)})
                    </span>
                </div>
            </div>

            {/* Delta KPI Table */}
            <div style={{
                background: 'var(--surface)', border: '1px solid var(--border)',
                borderRadius: 'var(--radius)', overflow: 'hidden', marginBottom: '1.5rem',
            }}>
                <div style={{
                    padding: '0.75rem 1rem', borderBottom: '1px solid var(--border)',
                    fontSize: '0.85rem', fontWeight: 600,
                }}>
                    Performance Delta
                </div>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.8rem' }}>
                    <thead>
                        <tr style={{ borderBottom: '1px solid var(--border)' }}>
                            <th style={{ textAlign: 'left', padding: '0.6rem 1rem', color: 'var(--text-secondary)', fontWeight: 600 }}>Metric</th>
                            <th style={{ textAlign: 'right', padding: '0.6rem 1rem', color: 'var(--primary)', fontWeight: 600 }}>Run A</th>
                            <th style={{ textAlign: 'right', padding: '0.6rem 1rem', color: 'var(--primary)', fontWeight: 600 }}>Run B</th>
                            <th style={{ textAlign: 'right', padding: '0.6rem 1rem', color: 'var(--text-secondary)', fontWeight: 600 }}>Delta</th>
                        </tr>
                    </thead>
                    <tbody>
                        {COMPARISON_METRICS.map((metric, i) => {
                            const delta = deltas[metric.key];
                            const valA = getMetricValue(run_a, metric.key);
                            const valB = getMetricValue(run_b, metric.key);
                            const deltaColor = delta
                                ? delta.improved === true ? 'var(--success)'
                                    : delta.improved === false ? 'var(--danger)'
                                    : 'var(--text-secondary)'
                                : 'var(--text-secondary)';

                            return (
                                <tr key={metric.key} style={{
                                    borderBottom: '1px solid var(--border)',
                                    background: i % 2 === 0 ? 'transparent' : 'rgba(0,0,0,0.02)',
                                }}>
                                    <td style={{ padding: '0.6rem 1rem', fontWeight: 500 }}>{metric.label}</td>
                                    <td style={{ padding: '0.6rem 1rem', textAlign: 'right', fontFamily: 'monospace' }}>
                                        {formatMetricValue(valA, metric.unit)}
                                    </td>
                                    <td style={{ padding: '0.6rem 1rem', textAlign: 'right', fontFamily: 'monospace' }}>
                                        {formatMetricValue(valB, metric.unit)}
                                    </td>
                                    <td style={{ padding: '0.6rem 1rem', textAlign: 'right' }}>
                                        {delta ? (
                                            <span style={{
                                                display: 'inline-flex', alignItems: 'center', gap: '0.25rem',
                                                color: deltaColor, fontWeight: 600, fontFamily: 'monospace',
                                            }}>
                                                {delta.direction === 'up' && <ArrowUp size={14} />}
                                                {delta.direction === 'down' && <ArrowDown size={14} />}
                                                {delta.direction === 'same' && <Minus size={14} />}
                                                {delta.pct !== null ? `${Math.abs(delta.pct).toFixed(1)}%` : formatMetricValue(Math.abs(delta.value), metric.unit)}
                                            </span>
                                        ) : (
                                            <span style={{ color: 'var(--text-secondary)' }}>-</span>
                                        )}
                                    </td>
                                </tr>
                            );
                        })}
                    </tbody>
                </table>
            </div>

            {/* Overlay Timeseries Charts */}
            {mergedTimeseries.length > 0 && (
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}>
                    {/* Chart 1: Response Time */}
                    <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 'var(--radius)', padding: '1rem' }}>
                        <h4 style={{ fontSize: '0.85rem', fontWeight: 600, marginBottom: '0.75rem' }}>Response Time (Avg)</h4>
                        <ResponsiveContainer width="100%" height={250}>
                            <LineChart data={mergedTimeseries}>
                                <CartesianGrid strokeDasharray="3 3" stroke="var(--surface-hover)" />
                                <XAxis dataKey="elapsed_seconds" label={{ value: 'Elapsed Time (s)', position: 'insideBottom', offset: -5, style: { fontSize: '0.7rem', fill: 'var(--text-secondary)' } }} tick={{ fontSize: 10, fill: 'var(--text-secondary)' }} />
                                <YAxis tick={{ fontSize: 10, fill: 'var(--text-secondary)' }} unit="ms" />
                                <Tooltip contentStyle={tooltipStyle} labelStyle={{ color: 'var(--text-secondary)' }} labelFormatter={(v) => `${v}s`} />
                                <Legend wrapperStyle={{ fontSize: '0.75rem' }} />
                                <Line type="monotone" dataKey="a_response_time_avg" name="Run A" stroke="var(--primary)" strokeWidth={2} dot={false} />
                                <Line type="monotone" dataKey="b_response_time_avg" name="Run B" stroke="var(--primary)" strokeWidth={2} dot={false} strokeDasharray="5 5" />
                            </LineChart>
                        </ResponsiveContainer>
                    </div>

                    {/* Chart 2: Throughput */}
                    <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 'var(--radius)', padding: '1rem' }}>
                        <h4 style={{ fontSize: '0.85rem', fontWeight: 600, marginBottom: '0.75rem' }}>Throughput (RPS)</h4>
                        <ResponsiveContainer width="100%" height={250}>
                            <LineChart data={mergedTimeseries}>
                                <CartesianGrid strokeDasharray="3 3" stroke="var(--surface-hover)" />
                                <XAxis dataKey="elapsed_seconds" label={{ value: 'Elapsed Time (s)', position: 'insideBottom', offset: -5, style: { fontSize: '0.7rem', fill: 'var(--text-secondary)' } }} tick={{ fontSize: 10, fill: 'var(--text-secondary)' }} />
                                <YAxis tick={{ fontSize: 10, fill: 'var(--text-secondary)' }} />
                                <Tooltip contentStyle={tooltipStyle} labelStyle={{ color: 'var(--text-secondary)' }} labelFormatter={(v) => `${v}s`} />
                                <Legend wrapperStyle={{ fontSize: '0.75rem' }} />
                                <Line type="monotone" dataKey="a_throughput" name="Run A" stroke="var(--success)" strokeWidth={2} dot={false} />
                                <Line type="monotone" dataKey="b_throughput" name="Run B" stroke="var(--success)" strokeWidth={2} dot={false} strokeDasharray="5 5" />
                            </LineChart>
                        </ResponsiveContainer>
                    </div>

                    {/* Chart 3: Virtual Users */}
                    <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 'var(--radius)', padding: '1rem' }}>
                        <h4 style={{ fontSize: '0.85rem', fontWeight: 600, marginBottom: '0.75rem' }}>Virtual Users</h4>
                        <ResponsiveContainer width="100%" height={250}>
                            <AreaChart data={mergedTimeseries}>
                                <CartesianGrid strokeDasharray="3 3" stroke="var(--surface-hover)" />
                                <XAxis dataKey="elapsed_seconds" label={{ value: 'Elapsed Time (s)', position: 'insideBottom', offset: -5, style: { fontSize: '0.7rem', fill: 'var(--text-secondary)' } }} tick={{ fontSize: 10, fill: 'var(--text-secondary)' }} />
                                <YAxis tick={{ fontSize: 10, fill: 'var(--text-secondary)' }} />
                                <Tooltip contentStyle={tooltipStyle} labelStyle={{ color: 'var(--text-secondary)' }} labelFormatter={(v) => `${v}s`} />
                                <Legend wrapperStyle={{ fontSize: '0.75rem' }} />
                                <Area type="monotone" dataKey="a_vus" name="Run A" stroke="var(--accent)" fill="var(--accent)" fillOpacity={0.2} strokeWidth={2} />
                                <Area type="monotone" dataKey="b_vus" name="Run B" stroke="var(--accent)" fill="var(--accent)" fillOpacity={0.1} strokeWidth={2} strokeDasharray="5 5" />
                            </AreaChart>
                        </ResponsiveContainer>
                    </div>

                    {/* Chart 4: Error Rate */}
                    <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 'var(--radius)', padding: '1rem' }}>
                        <h4 style={{ fontSize: '0.85rem', fontWeight: 600, marginBottom: '0.75rem' }}>Error Rate (%)</h4>
                        <ResponsiveContainer width="100%" height={250}>
                            <AreaChart data={mergedTimeseries}>
                                <CartesianGrid strokeDasharray="3 3" stroke="var(--surface-hover)" />
                                <XAxis dataKey="elapsed_seconds" label={{ value: 'Elapsed Time (s)', position: 'insideBottom', offset: -5, style: { fontSize: '0.7rem', fill: 'var(--text-secondary)' } }} tick={{ fontSize: 10, fill: 'var(--text-secondary)' }} />
                                <YAxis tick={{ fontSize: 10, fill: 'var(--text-secondary)' }} unit="%" />
                                <Tooltip contentStyle={tooltipStyle} labelStyle={{ color: 'var(--text-secondary)' }} labelFormatter={(v) => `${v}s`} />
                                <Legend wrapperStyle={{ fontSize: '0.75rem' }} />
                                <Area type="monotone" dataKey="a_error_rate" name="Run A" stroke="var(--danger)" fill="var(--danger)" fillOpacity={0.2} strokeWidth={2} />
                                <Area type="monotone" dataKey="b_error_rate" name="Run B" stroke="var(--danger)" fill="var(--danger)" fillOpacity={0.1} strokeWidth={2} strokeDasharray="5 5" />
                            </AreaChart>
                        </ResponsiveContainer>
                    </div>
                </div>
            )}
        </div>
    );
});
