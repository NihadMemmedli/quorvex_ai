'use client';
import React, { useMemo } from 'react';
import { severityColor } from '@/lib/colors';
import { formatDate } from '@/lib/formatting';
import { cardStyle } from '@/lib/styles';
import { StatusBadge } from '@/components/shared';
import type { DbConnection, DbTestRun } from './types';

interface DashboardTabProps {
    connections: DbConnection[];
    runs: DbTestRun[];
}

export default React.memo(function DashboardTab({ connections, runs }: DashboardTabProps) {
    const dashboardStats = useMemo(() => {
        const completedRuns = runs.filter(r => r.status === 'completed');
        const avgRate = completedRuns.length > 0
            ? completedRuns.reduce((sum, r) => sum + (r.pass_rate || 0), 0) / completedRuns.length
            : 0;
        const criticals = runs.reduce((sum, r) => sum + (r.critical_count || 0), 0);
        return {
            totalConnections: connections.length,
            totalRuns: runs.length,
            avgPassRate: Math.round(avgRate * 100) / 100,
            criticalIssues: criticals,
        };
    }, [connections, runs]);

    const severityTotals = useMemo(() => ({
        critical: runs.reduce((s, r) => s + (r.critical_count || 0), 0),
        high: runs.reduce((s, r) => s + (r.high_count || 0), 0),
        medium: runs.reduce((s, r) => s + (r.medium_count || 0), 0),
        low: runs.reduce((s, r) => s + (r.low_count || 0), 0),
        info: runs.reduce((s, r) => s + (r.info_count || 0), 0),
    }), [runs]);

    const severityTotal = useMemo(() =>
        Object.values(severityTotals).reduce((a, b) => a + b, 0),
    [severityTotals]);

    const recentRuns = useMemo(() => runs.slice(0, 5), [runs]);

    return (
        <div>
            {/* Summary Cards */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '1rem', marginBottom: '1.5rem' }}>
                <div style={{ ...cardStyle, padding: '1rem', textAlign: 'center', borderLeft: '3px solid #2563eb' }}>
                    <div style={{ fontSize: '1.5rem', fontWeight: 700, color: 'var(--primary-hover)' }}>
                        {dashboardStats.totalConnections}
                    </div>
                    <div style={{ fontSize: '0.75rem', color: 'var(--text-tertiary)', textTransform: 'uppercase' }}>
                        Connections
                    </div>
                </div>
                <div style={{ ...cardStyle, padding: '1rem', textAlign: 'center', borderLeft: '3px solid #6366f1' }}>
                    <div style={{ fontSize: '1.5rem', fontWeight: 700, color: 'var(--accent)' }}>
                        {dashboardStats.totalRuns}
                    </div>
                    <div style={{ fontSize: '0.75rem', color: 'var(--text-tertiary)', textTransform: 'uppercase' }}>
                        Total Runs
                    </div>
                </div>
                <div style={{ ...cardStyle, padding: '1rem', textAlign: 'center', borderLeft: `3px solid ${dashboardStats.avgPassRate >= 90 ? 'var(--success)' : dashboardStats.avgPassRate >= 70 ? 'var(--warning)' : 'var(--danger)'}` }}>
                    <div style={{ fontSize: '1.5rem', fontWeight: 700, color: dashboardStats.avgPassRate >= 90 ? 'var(--success)' : dashboardStats.avgPassRate >= 70 ? 'var(--warning)' : 'var(--danger)' }}>
                        {dashboardStats.avgPassRate}%
                    </div>
                    <div style={{ fontSize: '0.75rem', color: 'var(--text-tertiary)', textTransform: 'uppercase' }}>
                        Avg Pass Rate
                    </div>
                </div>
                <div style={{ ...cardStyle, padding: '1rem', textAlign: 'center', borderLeft: '3px solid #dc2626' }}>
                    <div style={{ fontSize: '1.5rem', fontWeight: 700, color: 'var(--danger)' }}>
                        {dashboardStats.criticalIssues}
                    </div>
                    <div style={{ fontSize: '0.75rem', color: 'var(--text-tertiary)', textTransform: 'uppercase' }}>
                        Critical Issues
                    </div>
                </div>
            </div>

            {/* Severity Distribution */}
            {runs.length > 0 && (
                <div style={{ ...cardStyle, marginBottom: '1.5rem' }}>
                    <h4 style={{ fontWeight: 600, marginBottom: '1rem' }}>Severity Distribution</h4>
                    {severityTotal === 0 ? (
                        <p style={{ color: 'var(--text-secondary)', fontSize: '0.85rem' }}>No findings across runs.</p>
                    ) : (
                        <div>
                            <div style={{ display: 'flex', height: '24px', borderRadius: '4px', overflow: 'hidden', marginBottom: '0.75rem' }}>
                                {Object.entries(severityTotals).map(([sev, count]) =>
                                    count > 0 ? (
                                        <div key={sev} style={{
                                            width: `${(count / severityTotal) * 100}%`,
                                            background: severityColor(sev),
                                            minWidth: '2px',
                                        }} title={`${sev}: ${count}`} />
                                    ) : null
                                )}
                            </div>
                            <div style={{ display: 'flex', gap: '1.5rem', flexWrap: 'wrap' }}>
                                {Object.entries(severityTotals).map(([sev, count]) => (
                                    <div key={sev} style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '0.8rem' }}>
                                        <div style={{ width: '12px', height: '12px', borderRadius: '2px', background: severityColor(sev) }} />
                                        <span style={{ textTransform: 'capitalize' }}>{sev}</span>
                                        <span style={{ fontWeight: 600 }}>{count}</span>
                                    </div>
                                ))}
                            </div>
                        </div>
                    )}
                </div>
            )}

            {/* Recent Runs */}
            <div style={cardStyle}>
                <h4 style={{ fontWeight: 600, marginBottom: '1rem' }}>Recent Runs</h4>
                {runs.length === 0 ? (
                    <p style={{ color: 'var(--text-secondary)', fontSize: '0.85rem' }}>No runs yet.</p>
                ) : (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                        {recentRuns.map(run => {
                            const passRateColor = run.pass_rate >= 90 ? 'var(--success)' : run.pass_rate >= 70 ? 'var(--warning)' : 'var(--danger)';
                            return (
                                <div key={run.id} style={{
                                    display: 'flex', alignItems: 'center', gap: '1rem',
                                    padding: '0.75rem', borderRadius: 'var(--radius)',
                                    border: '1px solid var(--border)',
                                }}>
                                    <StatusBadge status={run.status} />
                                    <span style={{ flex: 1, fontSize: '0.85rem' }}>
                                        {run.spec_name || run.run_type}
                                    </span>
                                    <span style={{ fontWeight: 600, color: passRateColor, fontSize: '0.85rem' }}>
                                        {run.pass_rate != null ? `${run.pass_rate}%` : '-'}
                                    </span>
                                    <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
                                        {run.passed_checks}/{run.total_checks} checks
                                    </span>
                                    <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
                                        {formatDate(run.created_at)}
                                    </span>
                                </div>
                            );
                        })}
                    </div>
                )}
            </div>
        </div>
    );
});
