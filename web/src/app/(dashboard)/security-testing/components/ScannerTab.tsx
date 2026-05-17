'use client';
import React from 'react';
import { Play, Loader2, RefreshCw, ShieldCheck, ShieldOff } from 'lucide-react';
import { statusColor } from '@/lib/colors';
import { StatusBadge } from '@/components/shared';
import { cardStyle } from '@/lib/styles';
import { CredentialOption, JobStatus, SecurityCapabilities, SecurityTarget } from './types';

interface ScannerTabProps {
    scanUrl: string;
    setScanUrl: (v: string) => void;
    scanType: string;
    setScanType: (v: string) => void;
    isScanning: boolean;
    jobStatus: JobStatus | null;
    capabilities: SecurityCapabilities | null;
    targets: SecurityTarget[];
    credentials: CredentialOption[];
    activeScanLevel: string;
    setActiveScanLevel: (v: string) => void;
    authEnabled: boolean;
    setAuthEnabled: (v: boolean) => void;
    loginUrl: string;
    setLoginUrl: (v: string) => void;
    usernameKey: string;
    setUsernameKey: (v: string) => void;
    passwordKey: string;
    setPasswordKey: (v: string) => void;
    excludedPaths: string;
    setExcludedPaths: (v: string) => void;
    onRefreshCapabilities: () => void;
    onStartScan: () => void;
}

export default function ScannerTab({
    scanUrl, setScanUrl, scanType, setScanType,
    isScanning, jobStatus, capabilities, targets, credentials,
    activeScanLevel, setActiveScanLevel,
    authEnabled, setAuthEnabled, loginUrl, setLoginUrl,
    usernameKey, setUsernameKey, passwordKey, setPasswordKey,
    excludedPaths, setExcludedPaths, onRefreshCapabilities, onStartScan,
}: ScannerTabProps) {
    const modeAvailable = Boolean(scanType === 'quick'
        || (scanType === 'nuclei' && capabilities?.nuclei.available)
        || (scanType === 'zap' && capabilities?.zap.available)
        || (scanType === 'full' && (capabilities?.quick.available || capabilities?.nuclei.available || capabilities?.zap.available)));
    const authReady = !authEnabled || Boolean(loginUrl.trim() && usernameKey && passwordKey);
    const canStart = Boolean(!isScanning && scanUrl.trim() && modeAvailable && authReady);

    return (
        <div style={cardStyle}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
                <h3 style={{ fontWeight: 600 }}>Run Security Scan</h3>
                <button onClick={onRefreshCapabilities} style={{
                    background: 'var(--border)', color: 'var(--text)', border: 'none',
                    borderRadius: 'var(--radius)', padding: '4px 10px', cursor: 'pointer',
                    display: 'flex', alignItems: 'center', gap: '4px', fontSize: '0.8rem',
                }}>
                    <RefreshCw size={14} /> Check scanners
                </button>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: '0.75rem', marginBottom: '1rem' }}>
                {[
                    ['quick', capabilities?.quick.available, capabilities?.quick.message || 'Built-in checks'],
                    ['nuclei', capabilities?.nuclei.available, capabilities?.nuclei.message || 'Template scanner'],
                    ['zap', capabilities?.zap.available, capabilities?.zap.message || 'OWASP ZAP daemon'],
                ].map(([name, available, message]) => (
                    <div key={String(name)} style={{
                        border: '1px solid var(--border)', borderRadius: 'var(--radius)',
                        padding: '0.75rem', display: 'flex', gap: '0.6rem', alignItems: 'flex-start',
                    }}>
                        {available ? <ShieldCheck size={16} color="var(--success)" /> : <ShieldOff size={16} color="var(--text-tertiary)" />}
                        <div>
                            <div style={{ fontSize: '0.8rem', fontWeight: 600, textTransform: 'uppercase' }}>{name}</div>
                            <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>{String(message)}</div>
                        </div>
                    </div>
                ))}
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 180px 170px auto', gap: '1rem', marginBottom: '1rem' }}>
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
                    <option value="nuclei" disabled={capabilities ? !capabilities.nuclei.available : false}>Nuclei Scan</option>
                    <option value="zap" disabled={capabilities ? !capabilities.zap.available : false}>ZAP DAST</option>
                    <option value="full">Full Scan</option>
                </select>
                <select
                    value={activeScanLevel}
                    onChange={e => setActiveScanLevel(e.target.value)}
                    style={{
                        padding: '0.75rem', borderRadius: 'var(--radius)',
                        border: '1px solid var(--border)', background: 'var(--bg)',
                        color: 'var(--text)',
                    }}
                >
                    <option value="passive">Passive</option>
                    <option value="safe">Safe</option>
                    <option value="full">Full active</option>
                </select>
                <button
                    onClick={onStartScan}
                    disabled={!canStart}
                    style={{
                        display: 'flex', alignItems: 'center', gap: '0.5rem',
                        padding: '0.75rem 1.5rem', borderRadius: 'var(--radius)',
                        background: canStart ? 'var(--primary)' : 'var(--border)',
                        color: 'white', border: 'none', cursor: canStart ? 'pointer' : 'not-allowed',
                        fontWeight: 600,
                    }}
                >
                    {isScanning ? <Loader2 size={16} className="animate-spin" /> : <Play size={16} />}
                    {isScanning ? 'Scanning...' : 'Start Scan'}
                </button>
            </div>

            {targets.length > 0 && (
                <div style={{ marginBottom: '1rem' }}>
                    <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', marginBottom: '0.4rem' }}>Suggested targets</div>
                    <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
                        {targets.slice(0, 8).map(target => (
                            <button key={target.url} onClick={() => setScanUrl(target.url)} style={{
                                border: '1px solid var(--border)', background: scanUrl === target.url ? 'var(--primary-glow)' : 'transparent',
                                color: 'var(--text)', borderRadius: 'var(--radius)', padding: '4px 8px',
                                fontSize: '0.78rem', cursor: 'pointer',
                            }}>
                                {target.host} {target.endpoint_count > 0 ? `(${target.endpoint_count})` : ''}
                            </button>
                        ))}
                    </div>
                </div>
            )}

            <div style={{ display: 'grid', gridTemplateColumns: authEnabled ? '180px 1fr 180px 180px' : '180px 1fr', gap: '1rem', marginBottom: '1rem', alignItems: 'start' }}>
                <label style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
                    <input type="checkbox" checked={authEnabled} onChange={e => setAuthEnabled(e.target.checked)} />
                    Authenticated
                </label>
                {authEnabled ? (
                    <>
                        <input
                            type="text"
                            placeholder="Login URL"
                            value={loginUrl}
                            onChange={e => setLoginUrl(e.target.value)}
                            style={{ padding: '0.65rem', borderRadius: 'var(--radius)', border: '1px solid var(--border)', background: 'var(--bg)', color: 'var(--text)' }}
                        />
                        <select value={usernameKey} onChange={e => setUsernameKey(e.target.value)}
                            style={{ padding: '0.65rem', borderRadius: 'var(--radius)', border: '1px solid var(--border)', background: 'var(--bg)', color: 'var(--text)' }}>
                            <option value="">Username key</option>
                            {credentials.map(c => <option key={c.key} value={c.key}>{c.key} ({c.source})</option>)}
                        </select>
                        <select value={passwordKey} onChange={e => setPasswordKey(e.target.value)}
                            style={{ padding: '0.65rem', borderRadius: 'var(--radius)', border: '1px solid var(--border)', background: 'var(--bg)', color: 'var(--text)' }}>
                            <option value="">Password key</option>
                            {credentials.map(c => <option key={c.key} value={c.key}>{c.key} ({c.source})</option>)}
                        </select>
                    </>
                ) : (
                    <div style={{ fontSize: '0.8rem', color: 'var(--text-tertiary)' }}>Public scan only</div>
                )}
            </div>

            <textarea
                value={excludedPaths}
                onChange={e => setExcludedPaths(e.target.value)}
                placeholder="Excluded paths, one per line (optional)"
                rows={3}
                style={{
                    width: '100%', padding: '0.65rem', borderRadius: 'var(--radius)',
                    border: '1px solid var(--border)', background: 'var(--bg)',
                    color: 'var(--text)', fontSize: '0.85rem', marginBottom: '1rem',
                }}
            />

            <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '1rem' }}>
                <strong>Quick:</strong> Headers, cookies, SSL, CORS, info disclosure (~10-30s) &nbsp;|&nbsp;
                <strong>Nuclei:</strong> Template-based vulnerability scan (~1-5min) &nbsp;|&nbsp;
                <strong>ZAP:</strong> Spider + passive scan by default; full active only when selected &nbsp;|&nbsp;
                <strong>Full:</strong> Runs available scanners sequentially
            </div>

            {!modeAvailable && (
                <p style={{ color: 'var(--warning)', fontSize: '0.85rem', marginBottom: '1rem' }}>
                    Selected scan mode is unavailable. Start ZAP or install Nuclei, then check scanners again.
                </p>
            )}
            {!authReady && (
                <p style={{ color: 'var(--warning)', fontSize: '0.85rem', marginBottom: '1rem' }}>
                    Authenticated scans need a login URL plus username and password credential keys.
                </p>
            )}

            {/* Job Status */}
            {jobStatus && (
                <div style={{
                    ...cardStyle, marginTop: '1rem',
                    borderLeft: `3px solid ${statusColor(jobStatus.status)}`,
                }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '0.5rem' }}>
                        <StatusBadge status={jobStatus.status} />
                        {(jobStatus.stage || jobStatus.current_stage) && (
                            <span style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
                                Stage: {jobStatus.stage || jobStatus.current_stage}
                            </span>
                        )}
                    </div>
                    {(jobStatus.message || jobStatus.stage_message || jobStatus.error || jobStatus.error_message) && (
                        <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
                            {jobStatus.message || jobStatus.stage_message || jobStatus.error || jobStatus.error_message}
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
