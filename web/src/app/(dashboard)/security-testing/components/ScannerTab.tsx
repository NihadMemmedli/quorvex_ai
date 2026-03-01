'use client';
import React from 'react';
import { Play, Loader2 } from 'lucide-react';
import { statusColor } from '@/lib/colors';
import { StatusBadge } from '@/components/shared';
import { cardStyle } from '@/lib/styles';
import { JobStatus } from './types';

interface ScannerTabProps {
    scanUrl: string;
    setScanUrl: (v: string) => void;
    scanType: string;
    setScanType: (v: string) => void;
    isScanning: boolean;
    jobStatus: JobStatus | null;
    onStartScan: () => void;
}

export default function ScannerTab({
    scanUrl, setScanUrl, scanType, setScanType,
    isScanning, jobStatus, onStartScan,
}: ScannerTabProps) {
    return (
        <div style={cardStyle}>
            <h3 style={{ marginBottom: '1rem', fontWeight: 600 }}>Run Security Scan</h3>

            <div style={{ display: 'flex', gap: '1rem', marginBottom: '1rem' }}>
                <input
                    type="text"
                    placeholder="https://example.com"
                    value={scanUrl}
                    onChange={e => setScanUrl(e.target.value)}
                    style={{
                        flex: 1, padding: '0.75rem', borderRadius: 'var(--radius)',
                        border: '1px solid var(--border)', background: 'var(--bg)',
                        color: 'var(--text)', fontSize: '0.9rem',
                    }}
                />
                <select
                    value={scanType}
                    onChange={e => setScanType(e.target.value)}
                    style={{
                        padding: '0.75rem', borderRadius: 'var(--radius)',
                        border: '1px solid var(--border)', background: 'var(--bg)',
                        color: 'var(--text)', minWidth: '150px',
                    }}
                >
                    <option value="quick">Quick Scan</option>
                    <option value="nuclei">Nuclei Scan</option>
                    <option value="zap">ZAP DAST</option>
                    <option value="full">Full Scan</option>
                </select>
                <button
                    onClick={onStartScan}
                    disabled={isScanning || !scanUrl.trim()}
                    style={{
                        display: 'flex', alignItems: 'center', gap: '0.5rem',
                        padding: '0.75rem 1.5rem', borderRadius: 'var(--radius)',
                        background: isScanning ? 'var(--border)' : 'var(--primary)',
                        color: 'white', border: 'none', cursor: isScanning ? 'not-allowed' : 'pointer',
                        fontWeight: 600,
                    }}
                >
                    {isScanning ? <Loader2 size={16} className="animate-spin" /> : <Play size={16} />}
                    {isScanning ? 'Scanning...' : 'Start Scan'}
                </button>
            </div>

            <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '1rem' }}>
                <strong>Quick:</strong> Headers, cookies, SSL, CORS, info disclosure (~10-30s) &nbsp;|&nbsp;
                <strong>Nuclei:</strong> Template-based vulnerability scan (~1-5min) &nbsp;|&nbsp;
                <strong>ZAP:</strong> Full DAST with spider + active scan (~5-30min) &nbsp;|&nbsp;
                <strong>Full:</strong> All scanners sequentially
            </div>

            {/* Job Status */}
            {jobStatus && (
                <div style={{
                    ...cardStyle, marginTop: '1rem',
                    borderLeft: `3px solid ${statusColor(jobStatus.status)}`,
                }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '0.5rem' }}>
                        <StatusBadge status={jobStatus.status} />
                        {jobStatus.stage && (
                            <span style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
                                Stage: {jobStatus.stage}
                            </span>
                        )}
                    </div>
                    {jobStatus.message && (
                        <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
                            {jobStatus.message}
                        </p>
                    )}
                    {jobStatus.result && (
                        <p style={{ fontSize: '0.85rem', marginTop: '0.5rem' }}>
                            Found <strong>{(jobStatus.result as Record<string, number>).total_findings || 0}</strong> issues
                        </p>
                    )}
                </div>
            )}
        </div>
    );
}
