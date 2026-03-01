'use client';
import React, { useState, useEffect, useMemo } from 'react';
import { Loader2, CheckCircle, AlertCircle } from 'lucide-react';
import {
    LineChart, Line, AreaChart, Area, BarChart, Bar,
    XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
    PieChart, Pie, Cell,
} from 'recharts';
import { formatBytes, formatTimestamp } from '@/lib/formatting';
import { getResponseTimeColor, getErrorRateColor, getStatusColor } from '@/lib/colors';
import { API_BASE } from '@/lib/api';
import type { LoadTestRun, TimeseriesPoint, TimeseriesData } from './types';
import AIAnalysisView from './AIAnalysisView';

interface ResultsViewProps {
    run: LoadTestRun;
    onAnalyze?: () => void;
    analyzing?: boolean;
}

export default React.memo(function ResultsView({ run, onAnalyze, analyzing }: ResultsViewProps) {
    const [timeseries, setTimeseries] = useState<TimeseriesPoint[]>([]);
    const [tsLoading, setTsLoading] = useState(false);

    useEffect(() => {
        let cancelled = false;
        const fetchTs = async () => {
            setTsLoading(true);
            try {
                const res = await fetch(`${API_BASE}/load-testing/runs/${run.id}/timeseries`);
                if (res.ok && !cancelled) {
                    const data: TimeseriesData = await res.json();
                    setTimeseries(data.timeseries || []);
                }
            } catch {
                // ignore
            } finally {
                if (!cancelled) setTsLoading(false);
            }
        };
        fetchTs();
        return () => { cancelled = true; };
    }, [run.id]);

    const errorRate = run.error_rate ?? (run.total_requests ? ((run.failed_requests || 0) / run.total_requests) * 100 : 0);
    const dataReceived = run.data_received_bytes || 0;
    const dataSent = run.data_sent_bytes || 0;

    const kpis = useMemo(() => [
        { label: 'Total Requests', value: (run.total_requests ?? 0).toLocaleString(), color: 'var(--text-primary)' },
        { label: 'Failed Requests', value: `${(run.failed_requests ?? 0).toLocaleString()} (${errorRate.toFixed(1)}%)`, color: getErrorRateColor(errorRate) },
        { label: 'Avg Response Time', value: `${(run.avg_response_time_ms ?? 0).toFixed(0)}ms`, color: getResponseTimeColor(run.avg_response_time_ms ?? 0) },
        { label: 'P95 Response Time', value: `${(run.p95_response_time_ms ?? 0).toFixed(0)}ms`, color: getResponseTimeColor((run.p95_response_time_ms ?? 0) > 500 ? 501 : (run.p95_response_time_ms ?? 0)) },
        { label: 'P99 Response Time', value: `${(run.p99_response_time_ms ?? 0).toFixed(0)}ms`, color: getResponseTimeColor((run.p99_response_time_ms ?? 0) > 500 ? 501 : (run.p99_response_time_ms ?? 0)) },
        { label: 'Peak RPS', value: `${(run.peak_rps ?? 0).toFixed(1)} req/s`, color: 'var(--text-primary)' },
        { label: 'Test Duration', value: `${run.duration_seconds ?? 0}s`, color: 'var(--text-primary)' },
        { label: 'Peak VUs', value: `${run.peak_vus ?? run.vus ?? 0}`, color: 'var(--text-primary)' },
        { label: 'Data Transferred', value: `${formatBytes(dataReceived)} / ${formatBytes(dataSent)}`, color: 'var(--text-primary)' },
    ], [run, errorRate, dataReceived, dataSent]);

    const histogramData = useMemo(() => {
        if (!timeseries.length) return [];
        const buckets: Record<string, number> = { '0-100': 0, '100-200': 0, '200-300': 0, '300-500': 0, '500-1000': 0, '1000+': 0 };
        for (const p of timeseries) {
            const ms = p.response_time_avg;
            if (ms < 100) buckets['0-100']++;
            else if (ms < 200) buckets['100-200']++;
            else if (ms < 300) buckets['200-300']++;
            else if (ms < 500) buckets['300-500']++;
            else if (ms < 1000) buckets['500-1000']++;
            else buckets['1000+']++;
        }
        return Object.entries(buckets).map(([range, count]) => ({ range, count }));
    }, [timeseries]);

    const statusData = useMemo(() => {
        if (!run.http_status_counts) return [];
        return Object.entries(run.http_status_counts).map(([code, count]) => ({
            name: code, value: count, color: getStatusColor(code),
        }));
    }, [run.http_status_counts]);

    const chartTimeseries = useMemo(() =>
        timeseries.map(p => ({ ...p, time: formatTimestamp(p.timestamp) })),
    [timeseries]);

    const tooltipStyle = { background: 'var(--background)', border: '1px solid #30363d', borderRadius: '6px', fontSize: '0.75rem' };

    return (
        <div style={{ padding: '1rem 0' }}>
            {/* KPI Cards */}
            <div style={{
                display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '0.75rem',
                marginBottom: '1.5rem',
            }}>
                {kpis.map(kpi => (
                    <div key={kpi.label} style={{
                        background: 'var(--surface)', border: '1px solid var(--border)',
                        borderRadius: 'var(--radius)', padding: '1rem',
                    }}>
                        <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', marginBottom: '0.25rem' }}>
                            {kpi.label}
                        </div>
                        <div style={{ fontSize: '1.25rem', fontWeight: 700, color: kpi.color }}>
                            {kpi.value}
                        </div>
                    </div>
                ))}
            </div>

            {/* Charts */}
            {tsLoading ? (
                <div style={{ textAlign: 'center', padding: '2rem', color: 'var(--text-secondary)' }}>
                    <Loader2 size={20} style={{ animation: 'spin 1s linear infinite', margin: '0 auto 0.5rem' }} />
                    <p>Loading timeseries data...</p>
                </div>
            ) : timeseries.length > 0 ? (
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem', marginBottom: '1.5rem' }}>
                    {/* Chart 1: Response Time Over Time */}
                    <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 'var(--radius)', padding: '1rem' }}>
                        <h4 style={{ fontSize: '0.85rem', fontWeight: 600, marginBottom: '0.75rem' }}>Response Time Over Time</h4>
                        <ResponsiveContainer width="100%" height={250}>
                            <LineChart data={chartTimeseries}>
                                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.1)" />
                                <XAxis dataKey="time" tick={{ fontSize: 10, fill: 'var(--text-secondary)' }} />
                                <YAxis tick={{ fontSize: 10, fill: 'var(--text-secondary)' }} unit="ms" />
                                <Tooltip contentStyle={tooltipStyle} labelStyle={{ color: 'var(--text-secondary)' }} />
                                <Legend wrapperStyle={{ fontSize: '0.75rem' }} />
                                <Line type="monotone" dataKey="response_time_avg" name="Avg" stroke="var(--primary)" strokeWidth={2} dot={false} />
                                <Line type="monotone" dataKey="response_time_p95" name="P95" stroke="var(--warning)" strokeWidth={2} dot={false} />
                            </LineChart>
                        </ResponsiveContainer>
                    </div>

                    {/* Chart 2: Throughput */}
                    <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 'var(--radius)', padding: '1rem' }}>
                        <h4 style={{ fontSize: '0.85rem', fontWeight: 600, marginBottom: '0.75rem' }}>Throughput (RPS)</h4>
                        <ResponsiveContainer width="100%" height={250}>
                            <LineChart data={chartTimeseries}>
                                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.1)" />
                                <XAxis dataKey="time" tick={{ fontSize: 10, fill: 'var(--text-secondary)' }} />
                                <YAxis tick={{ fontSize: 10, fill: 'var(--text-secondary)' }} />
                                <Tooltip contentStyle={tooltipStyle} labelStyle={{ color: 'var(--text-secondary)' }} />
                                <Line type="monotone" dataKey="throughput" name="RPS" stroke="var(--success)" strokeWidth={2} dot={false} />
                            </LineChart>
                        </ResponsiveContainer>
                    </div>

                    {/* Chart 3: Virtual Users */}
                    <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 'var(--radius)', padding: '1rem' }}>
                        <h4 style={{ fontSize: '0.85rem', fontWeight: 600, marginBottom: '0.75rem' }}>Virtual Users</h4>
                        <ResponsiveContainer width="100%" height={250}>
                            <AreaChart data={chartTimeseries}>
                                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.1)" />
                                <XAxis dataKey="time" tick={{ fontSize: 10, fill: 'var(--text-secondary)' }} />
                                <YAxis tick={{ fontSize: 10, fill: 'var(--text-secondary)' }} />
                                <Tooltip contentStyle={tooltipStyle} labelStyle={{ color: 'var(--text-secondary)' }} />
                                <Area type="monotone" dataKey="vus" name="VUs" stroke="var(--primary)" fill="var(--primary)" fillOpacity={0.3} />
                            </AreaChart>
                        </ResponsiveContainer>
                    </div>

                    {/* Chart 4: Error Rate */}
                    <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 'var(--radius)', padding: '1rem' }}>
                        <h4 style={{ fontSize: '0.85rem', fontWeight: 600, marginBottom: '0.75rem' }}>Error Rate (%)</h4>
                        <ResponsiveContainer width="100%" height={250}>
                            <AreaChart data={chartTimeseries}>
                                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.1)" />
                                <XAxis dataKey="time" tick={{ fontSize: 10, fill: 'var(--text-secondary)' }} />
                                <YAxis tick={{ fontSize: 10, fill: 'var(--text-secondary)' }} unit="%" />
                                <Tooltip contentStyle={tooltipStyle} labelStyle={{ color: 'var(--text-secondary)' }} />
                                <Area type="monotone" dataKey="error_rate" name="Error Rate" stroke="var(--danger)" fill="var(--danger)" fillOpacity={0.3} />
                            </AreaChart>
                        </ResponsiveContainer>
                    </div>

                    {/* Chart 5: HTTP Status Codes */}
                    {statusData.length > 0 && (
                        <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 'var(--radius)', padding: '1rem' }}>
                            <h4 style={{ fontSize: '0.85rem', fontWeight: 600, marginBottom: '0.75rem' }}>HTTP Status Codes</h4>
                            <ResponsiveContainer width="100%" height={250}>
                                <PieChart>
                                    <Pie data={statusData} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={80} label={({ name, value }) => `${name}: ${value}`}>
                                        {statusData.map((entry, index) => (
                                            <Cell key={`cell-${index}`} fill={entry.color} />
                                        ))}
                                    </Pie>
                                    <Tooltip contentStyle={tooltipStyle} />
                                    <Legend wrapperStyle={{ fontSize: '0.75rem' }} />
                                </PieChart>
                            </ResponsiveContainer>
                        </div>
                    )}

                    {/* Chart 6: Response Time Distribution */}
                    {histogramData.length > 0 && (
                        <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 'var(--radius)', padding: '1rem' }}>
                            <h4 style={{ fontSize: '0.85rem', fontWeight: 600, marginBottom: '0.75rem' }}>Response Time Distribution</h4>
                            <ResponsiveContainer width="100%" height={250}>
                                <BarChart data={histogramData}>
                                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.1)" />
                                    <XAxis dataKey="range" tick={{ fontSize: 10, fill: 'var(--text-secondary)' }} />
                                    <YAxis tick={{ fontSize: 10, fill: 'var(--text-secondary)' }} />
                                    <Tooltip contentStyle={tooltipStyle} labelStyle={{ color: 'var(--text-secondary)' }} />
                                    <Bar dataKey="count" name="Samples" fill="var(--primary)" radius={[4, 4, 0, 0]} />
                                </BarChart>
                            </ResponsiveContainer>
                        </div>
                    )}
                </div>
            ) : null}

            {/* Per-Endpoint Table */}
            {run.metrics_summary?.per_endpoint && run.metrics_summary.per_endpoint.length > 0 && (
                <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 'var(--radius)', padding: '1rem', marginBottom: '1rem' }}>
                    <h4 style={{ fontSize: '0.85rem', fontWeight: 600, marginBottom: '0.75rem' }}>Per-Endpoint Performance</h4>
                    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.8rem' }}>
                        <thead>
                            <tr style={{ borderBottom: '1px solid var(--border)' }}>
                                <th style={{ textAlign: 'left', padding: '0.5rem', color: 'var(--text-secondary)', fontWeight: 600 }}>Endpoint</th>
                                <th style={{ textAlign: 'right', padding: '0.5rem', color: 'var(--text-secondary)', fontWeight: 600 }}>Count</th>
                                <th style={{ textAlign: 'right', padding: '0.5rem', color: 'var(--text-secondary)', fontWeight: 600 }}>Avg ms</th>
                                <th style={{ textAlign: 'right', padding: '0.5rem', color: 'var(--text-secondary)', fontWeight: 600 }}>P95 ms</th>
                                <th style={{ textAlign: 'right', padding: '0.5rem', color: 'var(--text-secondary)', fontWeight: 600 }}>Error Rate %</th>
                            </tr>
                        </thead>
                        <tbody>
                            {run.metrics_summary.per_endpoint
                                .sort((a, b) => b.p95_ms - a.p95_ms)
                                .map((ep, i) => (
                                    <tr key={i} style={{
                                        borderBottom: '1px solid var(--border)',
                                        background: i % 2 === 0 ? 'transparent' : 'rgba(0,0,0,0.05)',
                                    }}>
                                        <td style={{ padding: '0.5rem', fontFamily: 'monospace', fontSize: '0.75rem' }}>{ep.endpoint}</td>
                                        <td style={{ padding: '0.5rem', textAlign: 'right' }}>{ep.count}</td>
                                        <td style={{ padding: '0.5rem', textAlign: 'right', color: getResponseTimeColor(ep.avg_ms) }}>{ep.avg_ms.toFixed(0)}</td>
                                        <td style={{ padding: '0.5rem', textAlign: 'right', color: getResponseTimeColor(ep.p95_ms) }}>{ep.p95_ms.toFixed(0)}</td>
                                        <td style={{ padding: '0.5rem', textAlign: 'right', color: getErrorRateColor(ep.error_rate) }}>{ep.error_rate.toFixed(2)}%</td>
                                    </tr>
                                ))}
                        </tbody>
                    </table>
                </div>
            )}

            {/* Threshold Results */}
            {run.thresholds_detail && run.thresholds_detail.length > 0 && (
                <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 'var(--radius)', padding: '1rem', marginBottom: '1rem' }}>
                    <h4 style={{ fontSize: '0.85rem', fontWeight: 600, marginBottom: '0.75rem' }}>Threshold Results</h4>
                    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.8rem' }}>
                        <thead>
                            <tr style={{ borderBottom: '1px solid var(--border)' }}>
                                <th style={{ textAlign: 'left', padding: '0.5rem', color: 'var(--text-secondary)', fontWeight: 600 }}>Threshold</th>
                                <th style={{ textAlign: 'right', padding: '0.5rem', color: 'var(--text-secondary)', fontWeight: 600 }}>Value</th>
                                <th style={{ textAlign: 'right', padding: '0.5rem', color: 'var(--text-secondary)', fontWeight: 600 }}>Limit</th>
                                <th style={{ textAlign: 'center', padding: '0.5rem', color: 'var(--text-secondary)', fontWeight: 600 }}>Status</th>
                            </tr>
                        </thead>
                        <tbody>
                            {run.thresholds_detail.map((t, i) => (
                                <tr key={i} style={{ borderBottom: '1px solid var(--border)' }}>
                                    <td style={{ padding: '0.5rem', fontFamily: 'monospace', fontSize: '0.75rem' }}>{t.name}</td>
                                    <td style={{ padding: '0.5rem', textAlign: 'right' }}>{typeof t.value === 'number' ? t.value.toFixed(2) : t.value}</td>
                                    <td style={{ padding: '0.5rem', textAlign: 'right' }}>{typeof t.limit === 'number' ? t.limit.toFixed(2) : t.limit}</td>
                                    <td style={{ padding: '0.5rem', textAlign: 'center' }}>
                                        {t.passed ? <CheckCircle size={16} style={{ color: 'var(--success)' }} /> : <AlertCircle size={16} style={{ color: 'var(--danger)' }} />}
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            )}

            {/* Check Results */}
            {run.checks && run.checks.length > 0 && (
                <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 'var(--radius)', padding: '1rem' }}>
                    <h4 style={{ fontSize: '0.85rem', fontWeight: 600, marginBottom: '0.75rem' }}>Check Results</h4>
                    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.8rem' }}>
                        <thead>
                            <tr style={{ borderBottom: '1px solid var(--border)' }}>
                                <th style={{ textAlign: 'left', padding: '0.5rem', color: 'var(--text-secondary)', fontWeight: 600 }}>Check</th>
                                <th style={{ textAlign: 'right', padding: '0.5rem', color: 'var(--text-secondary)', fontWeight: 600 }}>Passes</th>
                                <th style={{ textAlign: 'right', padding: '0.5rem', color: 'var(--text-secondary)', fontWeight: 600 }}>Fails</th>
                                <th style={{ textAlign: 'left', padding: '0.5rem', color: 'var(--text-secondary)', fontWeight: 600, width: '200px' }}>Pass Rate</th>
                            </tr>
                        </thead>
                        <tbody>
                            {run.checks.map((c, i) => {
                                const rate = c.rate * 100;
                                return (
                                    <tr key={i} style={{ borderBottom: '1px solid var(--border)' }}>
                                        <td style={{ padding: '0.5rem' }}>{c.name}</td>
                                        <td style={{ padding: '0.5rem', textAlign: 'right', color: 'var(--success)' }}>{c.passes}</td>
                                        <td style={{ padding: '0.5rem', textAlign: 'right', color: c.fails > 0 ? 'var(--danger)' : 'var(--text-secondary)' }}>{c.fails}</td>
                                        <td style={{ padding: '0.5rem' }}>
                                            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                                                <div style={{ flex: 1, height: '8px', background: 'rgba(0,0,0,0.2)', borderRadius: '4px', overflow: 'hidden' }}>
                                                    <div style={{
                                                        width: `${rate}%`, height: '100%',
                                                        background: rate >= 95 ? 'var(--success)' : rate >= 80 ? 'var(--warning)' : 'var(--danger)',
                                                        borderRadius: '4px',
                                                    }} />
                                                </div>
                                                <span style={{ fontSize: '0.7rem', color: 'var(--text-secondary)', minWidth: '3rem', textAlign: 'right' }}>
                                                    {rate.toFixed(1)}%
                                                </span>
                                            </div>
                                        </td>
                                    </tr>
                                );
                            })}
                        </tbody>
                    </table>
                </div>
            )}

            {/* AI Analysis */}
            <AIAnalysisView
                analysis={run.ai_analysis}
                onAnalyze={() => onAnalyze?.()}
                analyzing={analyzing || false}
                runStatus={run.status}
            />
        </div>
    );
});
