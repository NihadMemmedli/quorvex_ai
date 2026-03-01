'use client';
import React, { useState } from 'react';
import { RefreshCw } from 'lucide-react';
import { formatDate, formatDuration } from '@/lib/formatting';
import { cardStyle } from '@/lib/styles';
import { StatusBadge, SeverityBadge } from '@/components/shared';
import { SecurityScanRun, SecurityFinding } from './types';
import FindingCard from './FindingCard';
import { API_BASE } from '@/lib/api';
import { getAuthHeaders } from '@/lib/styles';

interface HistoryTabProps {
    runs: SecurityScanRun[];
    fetchRuns: () => Promise<void>;
    onStatusChange: (id: number, status: string, notes?: string) => void;
}

export default function HistoryTab({ runs, fetchRuns, onStatusChange }: HistoryTabProps) {
    const [selectedRun, setSelectedRun] = useState<SecurityScanRun | null>(null);
    const [runFindings, setRunFindings] = useState<SecurityFinding[]>([]);
    const [expandedFinding, setExpandedFinding] = useState<number | null>(null);

    const fetchRunFindings = async (runId: string) => {
        try {
            const url = `${API_BASE}/security-testing/runs/${runId}/findings`;
            const res = await fetch(url, { headers: getAuthHeaders() });
            if (res.ok) setRunFindings(await res.json());
        } catch (e) { console.error('Failed to fetch run findings:', e); }
    };

    return (
        <div style={cardStyle}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
                <h3 style={{ fontWeight: 600 }}>Scan History</h3>
                <button onClick={fetchRuns} style={{
                    background: 'var(--border)', color: 'var(--text)', border: 'none',
                    borderRadius: 'var(--radius)', padding: '4px 12px', cursor: 'pointer',
                    display: 'flex', alignItems: 'center', gap: '4px', fontSize: '0.8rem',
                }}>
                    <RefreshCw size={14} /> Refresh
                </button>
            </div>

            {runs.length === 0 ? (
                <p style={{ color: 'var(--text-secondary)' }}>No scans yet. Run your first scan from the Scanner tab.</p>
            ) : (
                <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                    <thead>
                        <tr style={{ borderBottom: '1px solid var(--border)' }}>
                            <th style={{ textAlign: 'left', padding: '0.75rem 0.5rem', fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Target</th>
                            <th style={{ textAlign: 'left', padding: '0.75rem 0.5rem', fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Type</th>
                            <th style={{ textAlign: 'left', padding: '0.75rem 0.5rem', fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Status</th>
                            <th style={{ textAlign: 'center', padding: '0.75rem 0.5rem', fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Findings</th>
                            <th style={{ textAlign: 'left', padding: '0.75rem 0.5rem', fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Duration</th>
                            <th style={{ textAlign: 'left', padding: '0.75rem 0.5rem', fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Date</th>
                        </tr>
                    </thead>
                    <tbody>
                        {runs.map(run => (
                            <tr
                                key={run.id}
                                onClick={() => {
                                    setSelectedRun(run);
                                    fetchRunFindings(run.id);
                                }}
                                style={{
                                    borderBottom: '1px solid var(--border)',
                                    cursor: 'pointer',
                                    background: selectedRun?.id === run.id ? 'rgba(59, 130, 246, 0.05)' : 'transparent',
                                }}
                            >
                                <td style={{ padding: '0.75rem 0.5rem', fontSize: '0.85rem' }}>
                                    {run.target_url.length > 40 ? run.target_url.substring(0, 40) + '...' : run.target_url}
                                </td>
                                <td style={{ padding: '0.75rem 0.5rem' }}>
                                    <span style={{
                                        fontSize: '0.75rem', padding: '2px 8px', borderRadius: '4px',
                                        background: 'rgba(99, 102, 241, 0.1)', color: 'var(--accent)',
                                    }}>
                                        {run.scan_type}
                                    </span>
                                </td>
                                <td style={{ padding: '0.75rem 0.5rem' }}><StatusBadge status={run.status} /></td>
                                <td style={{ padding: '0.75rem 0.5rem', textAlign: 'center' }}>
                                    <div style={{ display: 'flex', gap: '4px', justifyContent: 'center', flexWrap: 'wrap' }}>
                                        {run.critical_count > 0 && <SeverityBadge severity="critical" count={run.critical_count} />}
                                        {run.high_count > 0 && <SeverityBadge severity="high" count={run.high_count} />}
                                        {run.medium_count > 0 && <SeverityBadge severity="medium" count={run.medium_count} />}
                                        {run.low_count > 0 && <SeverityBadge severity="low" count={run.low_count} />}
                                        {run.info_count > 0 && <SeverityBadge severity="info" count={run.info_count} />}
                                        {run.total_findings === 0 && <span style={{ color: 'var(--text-secondary)', fontSize: '0.8rem' }}>-</span>}
                                    </div>
                                </td>
                                <td style={{ padding: '0.75rem 0.5rem', fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
                                    {formatDuration(run.duration_seconds)}
                                </td>
                                <td style={{ padding: '0.75rem 0.5rem', fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                                    {formatDate(run.created_at)}
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            )}

            {/* Selected Run Details */}
            {selectedRun && (
                <div style={{ marginTop: '1.5rem', borderTop: '1px solid var(--border)', paddingTop: '1.5rem' }}>
                    <h4 style={{ fontWeight: 600, marginBottom: '1rem' }}>
                        Findings for {selectedRun.target_url}
                        <span style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', fontWeight: 400, marginLeft: '0.5rem' }}>
                            ({selectedRun.id})
                        </span>
                    </h4>

                    {runFindings.length === 0 ? (
                        <p style={{ color: 'var(--text-secondary)' }}>No findings for this scan.</p>
                    ) : (
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                            {runFindings.map(finding => (
                                <FindingCard key={finding.id} finding={finding} onStatusChange={onStatusChange}
                                    expanded={expandedFinding === finding.id}
                                    onToggle={() => setExpandedFinding(expandedFinding === finding.id ? null : finding.id)}
                                />
                            ))}
                        </div>
                    )}
                </div>
            )}
        </div>
    );
}
