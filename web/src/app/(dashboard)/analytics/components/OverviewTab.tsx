'use client';
import React, { useState, useEffect } from 'react';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';
import { API_BASE } from '@/lib/api';
import { getAuthHeaders } from '@/lib/styles';
import type { CoverageOverview } from './types';

interface OverviewTabProps {
    projectId?: string;
}

export function OverviewTab({ projectId }: OverviewTabProps) {
    const [data, setData] = useState<CoverageOverview | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        setLoading(true);
        setError(null);
        const params = projectId ? `?project_id=${encodeURIComponent(projectId)}` : '';
        fetch(`${API_BASE}/analytics/coverage-overview${params}`, {
            headers: getAuthHeaders(),
        })
            .then(res => {
                if (!res.ok) throw new Error(`Failed to fetch coverage overview`);
                return res.json();
            })
            .then(d => { setData(d); setLoading(false); })
            .catch(err => { setError(err.message); setLoading(false); });
    }, [projectId]);

    if (loading) return <div style={{ textAlign: 'center', padding: '2rem', color: 'var(--text-secondary)' }}>Loading...</div>;
    if (error) return <div style={{ textAlign: 'center', padding: '2rem', color: 'var(--danger)' }}>{error}</div>;
    if (!data || data.total_specs === 0) {
        return <div style={{ textAlign: 'center', padding: '3rem', color: 'var(--text-secondary)' }}>No data yet. Create specs and run tests to see analytics.</div>;
    }

    const specsNeverRun = data.total_specs - data.specs_run_at_least_once;

    const cards = [
        { label: 'Total Specs', value: data.total_specs },
        { label: 'Test Files', value: data.total_test_files },
        { label: 'Run Coverage', value: `${data.run_coverage_percent.toFixed(1)}%` },
        { label: 'Specs Never Run', value: specsNeverRun },
    ];

    const tagData = (data.tags_distribution || []).map(t => ({
        name: t.tag,
        count: t.count,
    }));

    return (
        <div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem', marginBottom: '2rem' }}>
                {cards.map(card => (
                    <div key={card.label} style={{
                        background: 'var(--surface)',
                        border: '1px solid var(--border)',
                        borderRadius: 'var(--radius)',
                        padding: '1.5rem',
                    }}>
                        <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: '0.5rem' }}>{card.label}</div>
                        <div style={{ fontSize: '1.75rem', fontWeight: 700 }}>{card.value}</div>
                    </div>
                ))}
            </div>

            {tagData.length > 0 && (
                <div style={{
                    background: 'var(--surface)',
                    border: '1px solid var(--border)',
                    borderRadius: 'var(--radius)',
                    padding: '1.5rem',
                }}>
                    <h3 style={{ fontSize: '1rem', fontWeight: 600, marginBottom: '1rem' }}>Tag Distribution</h3>
                    <ResponsiveContainer width="100%" height={300}>
                        <BarChart data={tagData} layout="vertical" margin={{ left: 80 }}>
                            <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                            <XAxis type="number" />
                            <YAxis type="category" dataKey="name" width={80} tick={{ fontSize: 12 }} />
                            <Tooltip />
                            <Bar dataKey="count" fill="var(--primary)" radius={[0, 4, 4, 0]} />
                        </BarChart>
                    </ResponsiveContainer>
                </div>
            )}
        </div>
    );
}
