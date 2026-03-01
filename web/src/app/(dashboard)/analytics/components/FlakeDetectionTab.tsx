'use client';
import React, { useState, useEffect, useCallback } from 'react';
import { API_BASE } from '@/lib/api';
import { getAuthHeaders } from '@/lib/styles';
import type { FlakeDetectionResponse, FlakySpec } from './types';

interface FlakeDetectionTabProps {
    projectId?: string;
}

export function FlakeDetectionTab({ projectId }: FlakeDetectionTabProps) {
    const [data, setData] = useState<FlakeDetectionResponse | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [togglingSpec, setTogglingSpec] = useState<string | null>(null);

    const fetchData = useCallback(() => {
        setLoading(true);
        setError(null);
        const params = projectId ? `?project_id=${encodeURIComponent(projectId)}` : '';
        fetch(`${API_BASE}/analytics/flake-detection${params}`, {
            headers: getAuthHeaders(),
        })
            .then(res => {
                if (!res.ok) throw new Error('Failed to fetch flake detection data');
                return res.json();
            })
            .then(d => { setData(d); setLoading(false); })
            .catch(err => { setError(err.message); setLoading(false); });
    }, [projectId]);

    useEffect(() => { fetchData(); }, [fetchData]);

    const toggleQuarantine = async (spec: FlakySpec) => {
        setTogglingSpec(spec.spec_name);
        try {
            const encodedName = encodeURIComponent(spec.spec_name);
            const params = projectId ? `?project_id=${encodeURIComponent(projectId)}` : '';
            if (spec.is_quarantined) {
                await fetch(`${API_BASE}/analytics/quarantine/${encodedName}${params}`, {
                    method: 'DELETE',
                    headers: getAuthHeaders(),
                });
            } else {
                await fetch(`${API_BASE}/analytics/quarantine/${encodedName}${params}`, {
                    method: 'POST',
                    headers: getAuthHeaders(),
                });
            }
            fetchData();
        } catch {
            // silently fail, refetch will show current state
        } finally {
            setTogglingSpec(null);
        }
    };

    if (loading) return <div style={{ textAlign: 'center', padding: '2rem', color: 'var(--text-secondary)' }}>Loading...</div>;
    if (error) return <div style={{ textAlign: 'center', padding: '2rem', color: 'var(--danger)' }}>{error}</div>;
    if (!data || data.flaky_specs.length === 0) {
        return <div style={{ textAlign: 'center', padding: '3rem', color: 'var(--text-secondary)' }}>No specs with enough runs for flake analysis.</div>;
    }

    return (
        <div>
            {/* Summary bar */}
            <div style={{
                background: 'var(--surface)',
                border: '1px solid var(--border)',
                borderRadius: 'var(--radius)',
                padding: '1rem 1.5rem',
                marginBottom: '1.5rem',
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
            }}>
                <span style={{ fontWeight: 600 }}>
                    {data.total_flaky} flaky spec{data.total_flaky !== 1 ? 's' : ''} detected
                </span>
                <span style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
                    Threshold: {(data.threshold * 100).toFixed(0)}%
                </span>
            </div>

            {/* Table */}
            <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 'var(--radius)', overflow: 'hidden' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                    <thead>
                        <tr>
                            <th style={{ padding: '0.75rem', textAlign: 'left', borderBottom: '2px solid var(--border)', color: 'var(--text-secondary)', fontSize: '0.85rem' }}>Spec Name</th>
                            <th style={{ padding: '0.75rem', textAlign: 'left', borderBottom: '2px solid var(--border)', color: 'var(--text-secondary)', fontSize: '0.85rem' }}>Flakiness Score</th>
                            <th style={{ padding: '0.75rem', textAlign: 'left', borderBottom: '2px solid var(--border)', color: 'var(--text-secondary)', fontSize: '0.85rem' }}>Results</th>
                            <th style={{ padding: '0.75rem', textAlign: 'left', borderBottom: '2px solid var(--border)', color: 'var(--text-secondary)', fontSize: '0.85rem' }}>Recent Results</th>
                            <th style={{ padding: '0.75rem', textAlign: 'left', borderBottom: '2px solid var(--border)', color: 'var(--text-secondary)', fontSize: '0.85rem' }}>Action</th>
                        </tr>
                    </thead>
                    <tbody>
                        {data.flaky_specs.map(spec => {
                            const scorePercent = (spec.flakiness_score * 100).toFixed(1);
                            const barColor = spec.flakiness_score > 0.3 ? 'var(--danger)' : spec.flakiness_score > 0.15 ? 'var(--warning)' : 'var(--success)';
                            return (
                                <tr key={spec.spec_name} style={{
                                    borderLeft: spec.is_flaky ? '4px solid #f59e0b' : 'none',
                                }}>
                                    <td style={{ padding: '0.75rem', borderBottom: '1px solid var(--border)', fontWeight: spec.is_flaky ? 600 : 400 }}>
                                        {spec.spec_name}
                                        {spec.is_quarantined && (
                                            <span style={{
                                                marginLeft: '0.5rem',
                                                fontSize: '0.7rem',
                                                padding: '0.15rem 0.4rem',
                                                background: 'rgba(139,92,246,0.15)',
                                                color: 'var(--accent)',
                                                borderRadius: '4px',
                                                fontWeight: 600,
                                            }}>
                                                QUARANTINED
                                            </span>
                                        )}
                                    </td>
                                    <td style={{ padding: '0.75rem', borderBottom: '1px solid var(--border)', minWidth: '160px' }}>
                                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                                            <div style={{ flex: 1, height: '8px', background: 'var(--border)', borderRadius: '4px', overflow: 'hidden' }}>
                                                <div style={{ width: `${Math.min(spec.flakiness_score * 100, 100)}%`, height: '100%', background: barColor, borderRadius: '4px' }} />
                                            </div>
                                            <span style={{ fontSize: '0.8rem', fontWeight: 600, color: barColor, minWidth: '40px' }}>{scorePercent}%</span>
                                        </div>
                                    </td>
                                    <td style={{ padding: '0.75rem', borderBottom: '1px solid var(--border)', fontSize: '0.85rem' }}>
                                        <span style={{ color: 'var(--success)' }}>{spec.passed}P</span>
                                        {' / '}
                                        <span style={{ color: 'var(--danger)' }}>{spec.failed}F</span>
                                        <span style={{ color: 'var(--text-secondary)', marginLeft: '0.25rem' }}>({spec.total_runs})</span>
                                    </td>
                                    <td style={{ padding: '0.75rem', borderBottom: '1px solid var(--border)' }}>
                                        <div style={{ display: 'flex', gap: '3px', alignItems: 'center' }}>
                                            {spec.recent_results.slice(0, 10).map((result, i) => (
                                                <div
                                                    key={i}
                                                    style={{
                                                        width: '10px',
                                                        height: '10px',
                                                        borderRadius: '50%',
                                                        background: result === 'passed' ? 'var(--success)' : result === 'failed' ? 'var(--danger)' : 'var(--text-tertiary)',
                                                    }}
                                                    title={result}
                                                />
                                            ))}
                                        </div>
                                    </td>
                                    <td style={{ padding: '0.75rem', borderBottom: '1px solid var(--border)' }}>
                                        <button
                                            onClick={() => toggleQuarantine(spec)}
                                            disabled={togglingSpec === spec.spec_name}
                                            style={{
                                                padding: '0.3rem 0.75rem',
                                                fontSize: '0.8rem',
                                                borderRadius: 'var(--radius)',
                                                border: '1px solid var(--border)',
                                                background: spec.is_quarantined ? 'var(--surface)' : 'rgba(245,158,11,0.1)',
                                                color: spec.is_quarantined ? 'var(--text-secondary)' : 'var(--warning)',
                                                cursor: togglingSpec === spec.spec_name ? 'wait' : 'pointer',
                                                fontWeight: 500,
                                                opacity: togglingSpec === spec.spec_name ? 0.5 : 1,
                                            }}
                                        >
                                            {spec.is_quarantined ? 'Unquarantine' : 'Quarantine'}
                                        </button>
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
