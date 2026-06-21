'use client';
import React, { useState, useEffect } from 'react';
import { Loader2 } from 'lucide-react';
import { API_BASE } from '@/lib/api';
import { getAuthHeaders, cardStyle } from '@/lib/styles';
import { SecurityScanRun, SecurityFinding } from './types';
import FindingCard from './FindingCard';

interface FindingsTabProps {
    projectId: string;
    runs: SecurityScanRun[];
    onStatusChange: (id: number, status: string, notes?: string) => void;
    initialRunId?: string;
    initialFindingId?: string;
}

export default function FindingsTab({ projectId, runs, onStatusChange, initialRunId, initialFindingId }: FindingsTabProps) {
    const [severityFilter, setSeverityFilter] = useState<string>('all');
    const [statusFilter, setStatusFilter] = useState<string>('all');
    const [scannerFilter, setScannerFilter] = useState<string>('all');
    const [expandedFinding, setExpandedFinding] = useState<number | null>(null);
    const [findings, setFindings] = useState<SecurityFinding[]>([]);
    const [total, setTotal] = useState(0);
    const [loading, setLoading] = useState(false);

    useEffect(() => {
        const loadFindings = async () => {
            setLoading(true);
            try {
                const params = new URLSearchParams({ project_id: projectId, limit: '200' });
                if (severityFilter !== 'all') params.set('severity', severityFilter);
                if (statusFilter !== 'all') params.set('status', statusFilter);
                if (scannerFilter !== 'all') params.set('scanner', scannerFilter);
                const res = await fetch(`${API_BASE}/security-testing/findings?${params}`, { headers: getAuthHeaders() });
                if (res.ok) {
                    const data = await res.json();
                    const loadedFindings = data.findings || [];
                    setFindings(initialRunId ? loadedFindings.filter((finding: SecurityFinding) => finding.scan_id === initialRunId) : loadedFindings);
                    setTotal(data.total || 0);
                }
            } catch (e) { console.error('Load findings failed:', e); }
            setLoading(false);
        };
        loadFindings();
    }, [initialRunId, projectId, runs, severityFilter, statusFilter, scannerFilter]);

    useEffect(() => {
        if (!initialFindingId) return;
        const id = Number(initialFindingId);
        if (Number.isFinite(id) && findings.some(finding => finding.id === id)) {
            setExpandedFinding(id);
        }
    }, [findings, initialFindingId]);

    return (
        <div style={cardStyle}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
                <h3 style={{ fontWeight: 600 }}>All Findings</h3>
                <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center' }}>
                    <select
                        value={severityFilter}
                        onChange={e => setSeverityFilter(e.target.value)}
                        style={{
                            padding: '0.4rem 0.75rem', borderRadius: 'var(--radius)',
                            border: '1px solid var(--border)', background: 'var(--bg)',
                            color: 'var(--text)', fontSize: '0.85rem',
                        }}
                    >
                        <option value="all">All Severities</option>
                        <option value="critical">Critical</option>
                        <option value="high">High</option>
                        <option value="medium">Medium</option>
                        <option value="low">Low</option>
                        <option value="info">Info</option>
                    </select>
                    <select
                        value={statusFilter}
                        onChange={e => setStatusFilter(e.target.value)}
                        style={{
                            padding: '0.4rem 0.75rem', borderRadius: 'var(--radius)',
                            border: '1px solid var(--border)', background: 'var(--bg)',
                            color: 'var(--text)', fontSize: '0.85rem',
                        }}
                    >
                        <option value="all">All Statuses</option>
                        <option value="open">Open</option>
                        <option value="false_positive">False Positive</option>
                        <option value="fixed">Fixed</option>
                        <option value="accepted_risk">Accepted Risk</option>
                    </select>
                    <select
                        value={scannerFilter}
                        onChange={e => setScannerFilter(e.target.value)}
                        style={{
                            padding: '0.4rem 0.75rem', borderRadius: 'var(--radius)',
                            border: '1px solid var(--border)', background: 'var(--bg)',
                            color: 'var(--text)', fontSize: '0.85rem',
                        }}
                    >
                        <option value="all">All Scanners</option>
                        <option value="quick">Quick</option>
                        <option value="nuclei">Nuclei</option>
                        <option value="zap">ZAP</option>
                    </select>
                </div>
            </div>

            {loading ? (
                <div style={{ textAlign: 'center', padding: '2rem', color: 'var(--text-secondary)' }}>
                    <Loader2 size={24} className="animate-spin" style={{ display: 'inline-block' }} /> Loading findings...
                </div>
            ) : findings.length === 0 ? (
                <p style={{ color: 'var(--text-secondary)' }}>No findings match the current filters.</p>
            ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                    <p style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '0.5rem' }}>
                        Showing {findings.length} of {total} findings
                    </p>
                    {findings.map(finding => (
                        <FindingCard
                            key={`${finding.scan_id}-${finding.id}`}
                            finding={finding}
                            onStatusChange={onStatusChange}
                            expanded={expandedFinding === finding.id}
                            onToggle={() => setExpandedFinding(expandedFinding === finding.id ? null : finding.id)}
                        />
                    ))}
                </div>
            )}
        </div>
    );
}
