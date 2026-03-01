'use client';
import React, { useState, useEffect } from 'react';
import { PieChart, Pie, Cell, Tooltip, Legend, ResponsiveContainer } from 'recharts';
import { API_BASE } from '@/lib/api';
import { getAuthHeaders } from '@/lib/styles';
import type { FailureClassificationResponse } from './types';

interface FailuresTabProps {
    projectId?: string;
    period: string;
}

const CLASSIFICATION_COLORS: Record<string, string> = {
    defect: 'var(--danger)',
    flaky: 'var(--warning)',
    environment: 'var(--primary)',
    timeout: 'var(--accent)',
};

function formatTime(dateStr: string): string {
    try {
        const d = new Date(dateStr);
        return d.toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
    } catch {
        return dateStr;
    }
}

export function FailuresTab({ projectId, period }: FailuresTabProps) {
    const [data, setData] = useState<FailureClassificationResponse | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [expandedRow, setExpandedRow] = useState<string | null>(null);

    useEffect(() => {
        setLoading(true);
        setError(null);
        const base = projectId ? `project_id=${encodeURIComponent(projectId)}&` : '';
        fetch(`${API_BASE}/analytics/failure-classification?${base}period=${period}`, {
            headers: getAuthHeaders(),
        })
            .then(res => {
                if (!res.ok) throw new Error('Failed to fetch failure classification');
                return res.json();
            })
            .then(d => { setData(d); setLoading(false); })
            .catch(err => { setError(err.message); setLoading(false); });
    }, [projectId, period]);

    if (loading) return <div style={{ textAlign: 'center', padding: '2rem', color: 'var(--text-secondary)' }}>Loading...</div>;
    if (error) return <div style={{ textAlign: 'center', padding: '2rem', color: 'var(--danger)' }}>{error}</div>;
    if (!data) return <div style={{ textAlign: 'center', padding: '3rem', color: 'var(--text-secondary)' }}>No failures in this period.</div>;

    const dist = data.distribution;
    const pieData = Object.entries(dist)
        .filter(([, v]) => v > 0)
        .map(([key, value]) => ({ name: key, value }));

    const hasDistribution = pieData.length > 0;
    const hasFailures = data.recent_failures.length > 0;

    if (!hasDistribution && !hasFailures) {
        return <div style={{ textAlign: 'center', padding: '3rem', color: 'var(--text-secondary)' }}>No failures in this period.</div>;
    }

    return (
        <div>
            {/* Pie Chart */}
            {hasDistribution && (
                <div style={{
                    background: 'var(--surface)',
                    border: '1px solid var(--border)',
                    borderRadius: 'var(--radius)',
                    padding: '1.5rem',
                    marginBottom: '2rem',
                }}>
                    <h3 style={{ fontSize: '1rem', fontWeight: 600, marginBottom: '1rem' }}>Failure Distribution</h3>
                    <ResponsiveContainer width="100%" height={300}>
                        <PieChart>
                            <Pie
                                data={pieData}
                                cx="50%"
                                cy="50%"
                                innerRadius={60}
                                outerRadius={100}
                                dataKey="value"
                                nameKey="name"
                                label={({ name, percent }) => `${name} ${((percent ?? 0) * 100).toFixed(0)}%`}
                            >
                                {pieData.map((entry) => (
                                    <Cell key={entry.name} fill={CLASSIFICATION_COLORS[entry.name] || 'var(--text-tertiary)'} />
                                ))}
                            </Pie>
                            <Tooltip />
                            <Legend />
                        </PieChart>
                    </ResponsiveContainer>
                </div>
            )}

            {/* Recent Failures table */}
            {hasFailures && (
                <div style={{
                    background: 'var(--surface)',
                    border: '1px solid var(--border)',
                    borderRadius: 'var(--radius)',
                    overflow: 'hidden',
                }}>
                    <div style={{ padding: '1.5rem 1.5rem 0' }}>
                        <h3 style={{ fontSize: '1rem', fontWeight: 600, marginBottom: '1rem' }}>Recent Failures</h3>
                    </div>
                    <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                        <thead>
                            <tr>
                                <th style={{ padding: '0.75rem', textAlign: 'left', borderBottom: '2px solid var(--border)', color: 'var(--text-secondary)', fontSize: '0.85rem' }}>Spec Name</th>
                                <th style={{ padding: '0.75rem', textAlign: 'left', borderBottom: '2px solid var(--border)', color: 'var(--text-secondary)', fontSize: '0.85rem' }}>Classification</th>
                                <th style={{ padding: '0.75rem', textAlign: 'left', borderBottom: '2px solid var(--border)', color: 'var(--text-secondary)', fontSize: '0.85rem' }}>Error Message</th>
                                <th style={{ padding: '0.75rem', textAlign: 'left', borderBottom: '2px solid var(--border)', color: 'var(--text-secondary)', fontSize: '0.85rem' }}>Time</th>
                            </tr>
                        </thead>
                        <tbody>
                            {data.recent_failures.map(f => {
                                const isExpanded = expandedRow === f.run_id;
                                const badgeColor = CLASSIFICATION_COLORS[f.classification] || 'var(--text-tertiary)';
                                const truncatedMsg = f.error_message.length > 100 ? f.error_message.slice(0, 100) + '...' : f.error_message;
                                return (
                                    <React.Fragment key={f.run_id}>
                                        <tr
                                            onClick={() => setExpandedRow(isExpanded ? null : f.run_id)}
                                            style={{ cursor: 'pointer' }}
                                        >
                                            <td style={{ padding: '0.75rem', borderBottom: isExpanded ? 'none' : '1px solid var(--border)', fontWeight: 500 }}>
                                                {f.spec_name}
                                            </td>
                                            <td style={{ padding: '0.75rem', borderBottom: isExpanded ? 'none' : '1px solid var(--border)' }}>
                                                <span style={{
                                                    display: 'inline-block',
                                                    padding: '0.2rem 0.6rem',
                                                    borderRadius: '12px',
                                                    fontSize: '0.75rem',
                                                    fontWeight: 600,
                                                    background: badgeColor,
                                                    color: '#fff',
                                                    textTransform: 'capitalize',
                                                }}>
                                                    {f.classification}
                                                </span>
                                            </td>
                                            <td style={{ padding: '0.75rem', borderBottom: isExpanded ? 'none' : '1px solid var(--border)', fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
                                                {truncatedMsg}
                                            </td>
                                            <td style={{ padding: '0.75rem', borderBottom: isExpanded ? 'none' : '1px solid var(--border)', fontSize: '0.85rem', color: 'var(--text-secondary)', whiteSpace: 'nowrap' }}>
                                                {formatTime(f.created_at)}
                                            </td>
                                        </tr>
                                        {isExpanded && (
                                            <tr>
                                                <td colSpan={4} style={{
                                                    padding: '0.75rem 1rem 1rem',
                                                    borderBottom: '1px solid var(--border)',
                                                    background: 'var(--background)',
                                                }}>
                                                    <pre style={{
                                                        margin: 0,
                                                        whiteSpace: 'pre-wrap',
                                                        wordBreak: 'break-word',
                                                        fontSize: '0.8rem',
                                                        color: 'var(--text-secondary)',
                                                        fontFamily: 'monospace',
                                                    }}>
                                                        {f.error_message}
                                                    </pre>
                                                </td>
                                            </tr>
                                        )}
                                    </React.Fragment>
                                );
                            })}
                        </tbody>
                    </table>
                </div>
            )}
        </div>
    );
}
