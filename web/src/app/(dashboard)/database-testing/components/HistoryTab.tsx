'use client';
import React, { useState, useCallback } from 'react';
import { Loader2, RefreshCw } from 'lucide-react';
import { formatDate, formatDuration } from '@/lib/formatting';
import { cardStyle, btnSecondary } from '@/lib/styles';
import { getAuthHeaders } from '@/lib/styles';
import { SeverityBadge, StatusBadge } from '@/components/shared';
import { API_BASE } from '@/lib/api';
import CheckResultRow from './CheckResultRow';
import type { DbTestRun, DbTestCheck, SchemaFinding } from './types';

interface HistoryTabProps {
    runs: DbTestRun[];
    onRefreshRuns: () => void;
}

export default function HistoryTab({ runs, onRefreshRuns }: HistoryTabProps) {
    const [selectedRun, setSelectedRun] = useState<DbTestRun | null>(null);
    const [runChecks, setRunChecks] = useState<DbTestCheck[]>([]);
    const [runFindings, setRunFindings] = useState<SchemaFinding[]>([]);
    const [expandedCheckId, setExpandedCheckId] = useState<number | null>(null);
    const [runDataLoaded, setRunDataLoaded] = useState(false);

    const fetchRunChecks = useCallback(async (runId: string, runType?: string) => {
        setRunDataLoaded(false);
        setRunChecks([]);
        setRunFindings([]);
        try {
            if (runType === 'schema_analysis') {
                const res = await fetch(`${API_BASE}/database-testing/runs/${runId}/schema`, {
                    headers: getAuthHeaders(),
                });
                if (res.ok) {
                    const data = await res.json();
                    const sf = data.schema_findings;
                    if (sf) {
                        const findings = sf.findings || (Array.isArray(sf) ? sf : []);
                        setRunFindings(findings as SchemaFinding[]);
                    }
                }
            } else {
                const res = await fetch(`${API_BASE}/database-testing/runs/${runId}/checks`, {
                    headers: getAuthHeaders(),
                });
                if (res.ok) {
                    const data = await res.json();
                    setRunChecks(Array.isArray(data) ? data : data.checks || []);
                }
            }
        } catch (e) { console.error('Failed to fetch run data:', e); }
        setRunDataLoaded(true);
    }, []);

    return (
        <div style={cardStyle}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
                <h3 style={{ fontWeight: 600 }}>Run History</h3>
                <button onClick={onRefreshRuns} style={{
                    ...btnSecondary, padding: '4px 12px', fontSize: '0.8rem',
                }}>
                    <RefreshCw size={14} /> Refresh
                </button>
            </div>

            {runs.length === 0 ? (
                <p style={{ color: 'var(--text-secondary)' }}>No runs yet. Run a spec or analyze a schema to get started.</p>
            ) : (
                <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                    <thead>
                        <tr style={{ borderBottom: '1px solid var(--border)' }}>
                            <th style={{ textAlign: 'left', padding: '0.75rem 0.5rem', fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Status</th>
                            <th style={{ textAlign: 'left', padding: '0.75rem 0.5rem', fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Spec / Type</th>
                            <th style={{ textAlign: 'left', padding: '0.75rem 0.5rem', fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Run Type</th>
                            <th style={{ textAlign: 'center', padding: '0.75rem 0.5rem', fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Pass Rate</th>
                            <th style={{ textAlign: 'center', padding: '0.75rem 0.5rem', fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Checks</th>
                            <th style={{ textAlign: 'left', padding: '0.75rem 0.5rem', fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Duration</th>
                            <th style={{ textAlign: 'left', padding: '0.75rem 0.5rem', fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Date</th>
                        </tr>
                    </thead>
                    <tbody>
                        {runs.map(run => {
                            const isSelected = selectedRun?.id === run.id;
                            const passRateColor = run.pass_rate >= 90 ? 'var(--success)' : run.pass_rate >= 70 ? 'var(--warning)' : 'var(--danger)';
                            return (
                                <React.Fragment key={run.id}>
                                    <tr
                                        onClick={() => {
                                            if (isSelected) {
                                                setSelectedRun(null);
                                                setRunChecks([]);
                                                setRunFindings([]);
                                                setRunDataLoaded(false);
                                            } else {
                                                setSelectedRun(run);
                                                fetchRunChecks(run.id, run.run_type);
                                            }
                                        }}
                                        style={{
                                            borderBottom: '1px solid var(--border)',
                                            cursor: 'pointer',
                                            background: isSelected ? 'rgba(59, 130, 246, 0.05)' : 'transparent',
                                        }}
                                    >
                                        <td style={{ padding: '0.75rem 0.5rem' }}><StatusBadge status={run.status} /></td>
                                        <td style={{ padding: '0.75rem 0.5rem', fontSize: '0.85rem' }}>
                                            {run.spec_name || '-'}
                                        </td>
                                        <td style={{ padding: '0.75rem 0.5rem' }}>
                                            <span style={{
                                                fontSize: '0.75rem', padding: '2px 8px', borderRadius: '4px',
                                                background: 'rgba(99, 102, 241, 0.1)', color: 'var(--accent)',
                                            }}>
                                                {run.run_type}
                                            </span>
                                        </td>
                                        <td style={{ padding: '0.75rem 0.5rem', textAlign: 'center' }}>
                                            {run.run_type === 'schema_analysis' ? (
                                                <span style={{ fontWeight: 600, color: 'var(--text-secondary)' }}>-</span>
                                            ) : (
                                                <span style={{ fontWeight: 600, color: passRateColor }}>
                                                    {run.pass_rate != null ? `${run.pass_rate}%` : '-'}
                                                </span>
                                            )}
                                        </td>
                                        <td style={{ padding: '0.75rem 0.5rem', textAlign: 'center', fontSize: '0.85rem' }}>
                                            {run.run_type === 'schema_analysis' ? (
                                                <span style={{ color: 'var(--text-secondary)' }}>
                                                    {run.stage_message?.match(/(\d+) tables/)?.[1] || '-'} tables
                                                </span>
                                            ) : (
                                                <>
                                                    <span style={{ color: 'var(--success)' }}>{run.passed_checks}</span>
                                                    <span style={{ color: 'var(--text-secondary)' }}> / {run.total_checks}</span>
                                                    {run.failed_checks > 0 && <span style={{ color: 'var(--danger)', marginLeft: '4px' }}>({run.failed_checks} failed)</span>}
                                                </>
                                            )}
                                        </td>
                                        <td style={{ padding: '0.75rem 0.5rem', fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
                                            {formatDuration(run.duration_seconds)}
                                        </td>
                                        <td style={{ padding: '0.75rem 0.5rem', fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                                            {formatDate(run.created_at)}
                                        </td>
                                    </tr>

                                    {/* Expanded check results */}
                                    {isSelected && (
                                        <tr>
                                            <td colSpan={7} style={{ padding: 0 }}>
                                                <div style={{ padding: '1rem 1.5rem', background: 'rgba(0,0,0,0.02)', borderBottom: '1px solid var(--border)' }}>
                                                    {run.ai_summary && (
                                                        <div style={{
                                                            padding: '0.75rem', marginBottom: '1rem',
                                                            background: 'rgba(59, 130, 246, 0.05)',
                                                            border: '1px solid rgba(59, 130, 246, 0.1)',
                                                            borderRadius: 'var(--radius)', fontSize: '0.85rem',
                                                        }}>
                                                            <strong>AI Summary:</strong> {run.ai_summary}
                                                        </div>
                                                    )}

                                                    {/* Severity breakdown */}
                                                    <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '1rem', flexWrap: 'wrap' }}>
                                                        {run.critical_count > 0 && <SeverityBadge severity="critical" count={run.critical_count} />}
                                                        {run.high_count > 0 && <SeverityBadge severity="high" count={run.high_count} />}
                                                        {run.medium_count > 0 && <SeverityBadge severity="medium" count={run.medium_count} />}
                                                        {run.low_count > 0 && <SeverityBadge severity="low" count={run.low_count} />}
                                                        {run.info_count > 0 && <SeverityBadge severity="info" count={run.info_count} />}
                                                    </div>

                                                    {!runDataLoaded ? (
                                                        <p style={{ color: 'var(--text-secondary)', fontSize: '0.85rem' }}>
                                                            <Loader2 size={14} style={{ display: 'inline', animation: 'spin 1s linear infinite', marginRight: '0.5rem' }} />
                                                            Loading...
                                                        </p>
                                                    ) : run.run_type === 'schema_analysis' && runFindings.length > 0 ? (
                                                        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                                                            <h5 style={{ fontSize: '0.85rem', fontWeight: 600, marginBottom: '0.25rem' }}>
                                                                Schema Findings ({runFindings.length})
                                                            </h5>
                                                            {runFindings.map((finding, idx) => (
                                                                <div key={idx} style={{
                                                                    padding: '0.5rem 0.75rem',
                                                                    border: '1px solid var(--border)',
                                                                    borderRadius: 'var(--radius)',
                                                                    fontSize: '0.8rem',
                                                                }}>
                                                                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.25rem' }}>
                                                                        <SeverityBadge severity={finding.severity} />
                                                                        <span style={{ fontWeight: 500 }}>{finding.title}</span>
                                                                        {finding.table_name && (
                                                                            <span style={{ color: 'var(--text-secondary)', fontSize: '0.75rem' }}>
                                                                                {finding.table_name}{finding.column_name ? `.${finding.column_name}` : ''}
                                                                            </span>
                                                                        )}
                                                                    </div>
                                                                    <p style={{ color: 'var(--text-secondary)', margin: 0 }}>{finding.description}</p>
                                                                    {finding.recommendation && (
                                                                        <p style={{ color: 'var(--accent)', margin: '0.25rem 0 0', fontFamily: 'monospace', fontSize: '0.75rem' }}>
                                                                            {finding.recommendation}
                                                                        </p>
                                                                    )}
                                                                </div>
                                                            ))}
                                                        </div>
                                                    ) : run.run_type === 'schema_analysis' && runFindings.length === 0 ? (
                                                        <p style={{ color: 'var(--text-secondary)', fontSize: '0.85rem' }}>
                                                            No findings for this analysis run.
                                                        </p>
                                                    ) : runChecks.length === 0 ? (
                                                        <p style={{ color: 'var(--text-secondary)', fontSize: '0.85rem' }}>
                                                            No checks recorded for this run.
                                                        </p>
                                                    ) : (
                                                        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                                                            <thead>
                                                                <tr style={{ borderBottom: '1px solid var(--border)' }}>
                                                                    <th style={{ textAlign: 'left', padding: '0.5rem', fontSize: '0.75rem', color: 'var(--text-secondary)' }}>Status</th>
                                                                    <th style={{ textAlign: 'left', padding: '0.5rem', fontSize: '0.75rem', color: 'var(--text-secondary)' }}>Check</th>
                                                                    <th style={{ textAlign: 'left', padding: '0.5rem', fontSize: '0.75rem', color: 'var(--text-secondary)' }}>Type</th>
                                                                    <th style={{ textAlign: 'left', padding: '0.5rem', fontSize: '0.75rem', color: 'var(--text-secondary)' }}>Table</th>
                                                                    <th style={{ textAlign: 'left', padding: '0.5rem', fontSize: '0.75rem', color: 'var(--text-secondary)' }}>Severity</th>
                                                                    <th style={{ textAlign: 'right', padding: '0.5rem', fontSize: '0.75rem', color: 'var(--text-secondary)' }}>Duration</th>
                                                                </tr>
                                                            </thead>
                                                            <tbody>
                                                                {runChecks.map(check => (
                                                                    <CheckResultRow
                                                                        key={check.id}
                                                                        check={check}
                                                                        isExpanded={expandedCheckId === check.id}
                                                                        onToggle={() => setExpandedCheckId(expandedCheckId === check.id ? null : check.id)}
                                                                    />
                                                                ))}
                                                            </tbody>
                                                        </table>
                                                    )}

                                                    {run.error_message && (
                                                        <div style={{ marginTop: '0.5rem', padding: '0.5rem', background: 'rgba(220, 38, 38, 0.05)', borderRadius: '4px', fontSize: '0.8rem', color: 'var(--danger)' }}>
                                                            <strong>Error:</strong> {run.error_message}
                                                        </div>
                                                    )}
                                                </div>
                                            </td>
                                        </tr>
                                    )}
                                </React.Fragment>
                            );
                        })}
                    </tbody>
                </table>
            )}
        </div>
    );
}
