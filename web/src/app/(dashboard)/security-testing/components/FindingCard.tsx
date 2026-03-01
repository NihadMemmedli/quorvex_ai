'use client';
import React from 'react';
import { ChevronDown, ChevronRight, ExternalLink } from 'lucide-react';
import { severityColor } from '@/lib/colors';
import { SeverityBadge } from '@/components/shared';
import { SecurityFinding } from './types';

interface FindingCardProps {
    finding: SecurityFinding;
    onStatusChange: (id: number, status: string, notes?: string) => void;
    expanded: boolean;
    onToggle: () => void;
}

export default React.memo(function FindingCard({
    finding, onStatusChange, expanded, onToggle,
}: FindingCardProps) {
    let refUrls: string[] = [];
    try { refUrls = JSON.parse(finding.reference_urls_json || '[]'); } catch { /* ignore */ }

    return (
        <div style={{
            border: '1px solid var(--border)', borderRadius: 'var(--radius)',
            borderLeft: `3px solid ${severityColor(finding.severity)}`,
            overflow: 'hidden',
        }}>
            <div onClick={onToggle} style={{
                padding: '0.75rem 1rem', cursor: 'pointer',
                display: 'flex', alignItems: 'center', gap: '0.75rem',
                background: expanded ? 'rgba(59, 130, 246, 0.03)' : 'transparent',
            }}>
                {expanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                <SeverityBadge severity={finding.severity} />
                <span style={{ flex: 1, fontSize: '0.9rem', fontWeight: 500 }}>{finding.title}</span>
                <span style={{
                    fontSize: '0.7rem', padding: '1px 6px', borderRadius: '4px',
                    background: 'rgba(99, 102, 241, 0.1)', color: 'var(--accent)',
                }}>
                    {finding.scanner}
                </span>
                <span style={{
                    fontSize: '0.7rem', padding: '1px 6px', borderRadius: '4px',
                    background: finding.status === 'open' ? 'rgba(220, 38, 38, 0.1)' : 'rgba(22, 163, 74, 0.1)',
                    color: finding.status === 'open' ? 'var(--danger)' : 'var(--success)',
                }}>
                    {finding.status}
                </span>
            </div>

            {expanded && (
                <div style={{ padding: '1rem', borderTop: '1px solid var(--border)', fontSize: '0.85rem' }}>
                    <p style={{ marginBottom: '0.75rem', lineHeight: 1.5 }}>{finding.description}</p>

                    {finding.url && (
                        <div style={{ marginBottom: '0.5rem' }}>
                            <strong>URL:</strong>{' '}
                            <a href={finding.url} target="_blank" rel="noopener noreferrer"
                                style={{ color: 'var(--primary)', textDecoration: 'none' }}>
                                {finding.url} <ExternalLink size={12} style={{ display: 'inline' }} />
                            </a>
                        </div>
                    )}

                    {finding.evidence && (
                        <div style={{ marginBottom: '0.5rem' }}>
                            <strong>Evidence:</strong>
                            <pre style={{
                                background: 'var(--bg)', padding: '0.5rem', borderRadius: '4px',
                                fontSize: '0.8rem', overflow: 'auto', marginTop: '4px',
                            }}>
                                {finding.evidence}
                            </pre>
                        </div>
                    )}

                    {finding.remediation && (
                        <div style={{ marginBottom: '0.5rem' }}>
                            <strong>Remediation:</strong>
                            <p style={{ color: 'var(--text-secondary)', marginTop: '2px' }}>{finding.remediation}</p>
                        </div>
                    )}

                    {refUrls.length > 0 && (
                        <div style={{ marginBottom: '0.75rem' }}>
                            <strong>References:</strong>
                            <ul style={{ margin: '4px 0', paddingLeft: '1.5rem' }}>
                                {refUrls.map((url, i) => (
                                    <li key={i}>
                                        <a href={url} target="_blank" rel="noopener noreferrer"
                                            style={{ color: 'var(--primary)', fontSize: '0.8rem' }}>
                                            {url}
                                        </a>
                                    </li>
                                ))}
                            </ul>
                        </div>
                    )}

                    {/* Status Actions */}
                    <div style={{ display: 'flex', gap: '0.5rem', marginTop: '0.75rem', borderTop: '1px solid var(--border)', paddingTop: '0.75rem' }}>
                        <span style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginRight: '0.5rem' }}>Mark as:</span>
                        {['open', 'false_positive', 'fixed', 'accepted_risk'].map(status => (
                            <button
                                key={status}
                                onClick={() => onStatusChange(finding.id, status)}
                                disabled={finding.status === status}
                                style={{
                                    fontSize: '0.75rem', padding: '3px 8px', borderRadius: '4px',
                                    border: '1px solid var(--border)', cursor: finding.status === status ? 'default' : 'pointer',
                                    background: finding.status === status ? 'var(--primary)' : 'transparent',
                                    color: finding.status === status ? 'white' : 'var(--text-secondary)',
                                    opacity: finding.status === status ? 1 : 0.8,
                                }}
                            >
                                {status.replace('_', ' ')}
                            </button>
                        ))}
                    </div>
                </div>
            )}
        </div>
    );
});
