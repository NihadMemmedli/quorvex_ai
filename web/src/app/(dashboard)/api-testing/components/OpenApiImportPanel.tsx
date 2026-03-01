'use client';
import React, { useState, useEffect, useCallback } from 'react';
import {
    Upload, Loader2, AlertCircle, CheckCircle, RefreshCw, Clock, FileText, Globe, ChevronDown, ChevronRight,
} from 'lucide-react';
import { API_BASE } from '@/lib/api';
import { JobStatus, ImportHistoryRecord } from './types';

interface OpenApiImportPanelProps {
    projectId: string;
    activeJobs: Record<string, JobStatus>;
    setActiveJobs: React.Dispatch<React.SetStateAction<Record<string, JobStatus>>>;
    setMessage: (msg: { type: 'success' | 'error'; text: string } | null) => void;
    pollJob: (jobId: string, onComplete?: () => void) => void;
}

function timeAgo(dateStr: string): string {
    const now = Date.now();
    const then = new Date(dateStr).getTime();
    const diff = now - then;
    const seconds = Math.floor(diff / 1000);
    if (seconds < 60) return 'just now';
    const minutes = Math.floor(seconds / 60);
    if (minutes < 60) return `${minutes}m ago`;
    const hours = Math.floor(minutes / 60);
    if (hours < 24) return `${hours}h ago`;
    const days = Math.floor(hours / 24);
    return `${days}d ago`;
}

export default function OpenApiImportPanel({
    projectId,
    activeJobs,
    setActiveJobs,
    setMessage,
    pollJob,
}: OpenApiImportPanelProps) {
    const [importUrl, setImportUrl] = useState('');
    const [importFile, setImportFile] = useState<File | null>(null);
    const [featureFilter, setFeatureFilter] = useState('');
    const [importMode, setImportMode] = useState<'url' | 'file'>('url');

    // Import history state
    const [history, setHistory] = useState<ImportHistoryRecord[]>([]);
    const [historyTotal, setHistoryTotal] = useState(0);
    const [historyLoading, setHistoryLoading] = useState(false);
    const [historyOffset, setHistoryOffset] = useState(0);
    const HISTORY_PAGE_SIZE = 10;
    const [expandedRows, setExpandedRows] = useState<Set<string>>(new Set());

    const toggleRow = (id: string) => {
        setExpandedRows(prev => {
            const next = new Set(prev);
            if (next.has(id)) next.delete(id); else next.add(id);
            return next;
        });
    };

    const fetchHistory = useCallback(async (offset = 0, append = false) => {
        setHistoryLoading(true);
        try {
            const res = await fetch(
                `${API_BASE}/api-testing/import-history?project_id=${projectId}&limit=${HISTORY_PAGE_SIZE}&offset=${offset}`
            );
            if (res.ok) {
                const data = await res.json();
                setHistory(prev => append ? [...prev, ...data.items] : data.items);
                setHistoryTotal(data.total);
                setHistoryOffset(offset + data.items.length);
            }
        } catch {
            // silent
        } finally {
            setHistoryLoading(false);
        }
    }, [projectId]);

    useEffect(() => {
        fetchHistory(0, false);
    }, [fetchHistory]);

    const handleImport = async () => {
        if (importMode === 'url') {
            if (!importUrl.trim()) return;
            try {
                const res = await fetch(`${API_BASE}/api-testing/import-openapi`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ url: importUrl, feature_filter: featureFilter || undefined, project_id: projectId }),
                });
                if (res.ok) {
                    const data = await res.json();
                    setActiveJobs(prev => ({ ...prev, [data.job_id]: { job_id: data.job_id, status: 'running', message: data.message } }));
                    pollJob(data.job_id, () => fetchHistory(0, false));
                    setMessage({ type: 'success', text: 'OpenAPI import started' });
                } else {
                    const err = await res.json();
                    setMessage({ type: 'error', text: err.detail || 'Import failed' });
                }
            } catch {
                setMessage({ type: 'error', text: 'Failed to start import' });
            }
        } else {
            if (!importFile) return;
            const formData = new FormData();
            formData.append('file', importFile);
            const params = new URLSearchParams();
            params.set('project_id', projectId);
            if (featureFilter) params.set('feature_filter', featureFilter);
            try {
                const res = await fetch(`${API_BASE}/api-testing/import-openapi-file?${params}`, {
                    method: 'POST',
                    body: formData,
                });
                if (res.ok) {
                    const data = await res.json();
                    setActiveJobs(prev => ({ ...prev, [data.job_id]: { job_id: data.job_id, status: 'running', message: data.message } }));
                    pollJob(data.job_id, () => fetchHistory(0, false));
                    setMessage({ type: 'success', text: 'OpenAPI file import started' });
                } else {
                    const err = await res.json();
                    setMessage({ type: 'error', text: err.detail || 'Import failed' });
                }
            } catch {
                setMessage({ type: 'error', text: 'Failed to start file import' });
            }
        }
    };

    const handleReimport = async (record: ImportHistoryRecord) => {
        if (record.source_type !== 'url' || !record.source_url) return;
        setImportUrl(record.source_url);
        setFeatureFilter(record.feature_filter || '');
        setImportMode('url');

        try {
            const res = await fetch(`${API_BASE}/api-testing/import-openapi`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ url: record.source_url, feature_filter: record.feature_filter || undefined, project_id: projectId }),
            });
            if (res.ok) {
                const data = await res.json();
                setActiveJobs(prev => ({ ...prev, [data.job_id]: { job_id: data.job_id, status: 'running', message: data.message } }));
                pollJob(data.job_id, () => fetchHistory(0, false));
                setMessage({ type: 'success', text: 'Re-import started' });
            } else {
                const err = await res.json();
                setMessage({ type: 'error', text: err.detail || 'Re-import failed' });
            }
        } catch {
            setMessage({ type: 'error', text: 'Failed to start re-import' });
        }
    };

    const statusBadge = (status: string) => {
        const colors: Record<string, { bg: string; fg: string }> = {
            completed: { bg: 'var(--success-muted)', fg: 'var(--success)' },
            running: { bg: 'var(--primary-glow)', fg: 'var(--primary)' },
            failed: { bg: 'var(--danger-muted)', fg: 'var(--danger)' },
        };
        const c = colors[status] || colors.failed;
        return (
            <span style={{
                fontSize: '0.7rem', padding: '0.15rem 0.5rem', borderRadius: '999px',
                background: c.bg, color: c.fg, fontWeight: 500,
            }}>
                {status}
            </span>
        );
    };

    return (
        <div style={{ maxWidth: '800px' }}>
            <div style={{
                background: 'var(--surface)', border: '1px solid var(--border)',
                borderRadius: 'var(--radius)', padding: '1.5rem',
            }}>
                <h3 style={{ fontSize: '1rem', fontWeight: 600, marginBottom: '1rem' }}>Import OpenAPI / Swagger Specification</h3>

                {/* Mode toggle */}
                <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '1.25rem' }}>
                    <button
                        onClick={() => setImportMode('url')}
                        style={{
                            padding: '0.4rem 0.8rem', borderRadius: 'var(--radius)',
                            border: importMode === 'url' ? '1px solid var(--primary)' : '1px solid var(--border)',
                            background: importMode === 'url' ? 'var(--primary-glow)' : 'transparent',
                            color: importMode === 'url' ? 'var(--primary)' : 'var(--text-secondary)',
                            cursor: 'pointer', fontSize: '0.8rem', fontWeight: 500,
                        }}
                    >
                        From URL
                    </button>
                    <button
                        onClick={() => setImportMode('file')}
                        style={{
                            padding: '0.4rem 0.8rem', borderRadius: 'var(--radius)',
                            border: importMode === 'file' ? '1px solid var(--primary)' : '1px solid var(--border)',
                            background: importMode === 'file' ? 'var(--primary-glow)' : 'transparent',
                            color: importMode === 'file' ? 'var(--primary)' : 'var(--text-secondary)',
                            cursor: 'pointer', fontSize: '0.8rem', fontWeight: 500,
                        }}
                    >
                        Upload File
                    </button>
                </div>

                {importMode === 'url' ? (
                    <div style={{ marginBottom: '1rem' }}>
                        <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 500, marginBottom: '0.4rem', color: 'var(--text-secondary)' }}>
                            OpenAPI Spec URL
                        </label>
                        <input
                            type="text"
                            placeholder="https://api.example.com/openapi.json"
                            value={importUrl}
                            onChange={e => setImportUrl(e.target.value)}
                            style={{
                                width: '100%', padding: '0.6rem 0.75rem',
                                background: 'var(--background)', border: '1px solid var(--border)',
                                borderRadius: 'var(--radius)', color: 'var(--text-primary)', fontSize: '0.875rem',
                            }}
                        />
                    </div>
                ) : (
                    <div style={{ marginBottom: '1rem' }}>
                        <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 500, marginBottom: '0.4rem', color: 'var(--text-secondary)' }}>
                            Upload JSON or YAML File
                        </label>
                        <input
                            type="file"
                            accept=".json,.yaml,.yml"
                            onChange={e => setImportFile(e.target.files?.[0] || null)}
                            style={{
                                width: '100%', padding: '0.6rem 0.75rem',
                                background: 'var(--background)', border: '1px solid var(--border)',
                                borderRadius: 'var(--radius)', color: 'var(--text-primary)', fontSize: '0.875rem',
                            }}
                        />
                    </div>
                )}

                <div style={{ marginBottom: '1.25rem' }}>
                    <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 500, marginBottom: '0.4rem', color: 'var(--text-secondary)' }}>
                        Feature Filter (optional)
                    </label>
                    <input
                        type="text"
                        placeholder="e.g., users, auth, orders"
                        value={featureFilter}
                        onChange={e => setFeatureFilter(e.target.value)}
                        style={{
                            width: '100%', padding: '0.6rem 0.75rem',
                            background: 'var(--background)', border: '1px solid var(--border)',
                            borderRadius: 'var(--radius)', color: 'var(--text-primary)', fontSize: '0.875rem',
                        }}
                    />
                    <p style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', marginTop: '0.3rem' }}>
                        Comma-separated tags or path prefixes to focus on specific API areas
                    </p>
                </div>

                <button
                    onClick={handleImport}
                    disabled={importMode === 'url' ? !importUrl.trim() : !importFile}
                    style={{
                        display: 'flex', alignItems: 'center', gap: '0.5rem',
                        padding: '0.6rem 1.25rem', background: 'var(--primary)', color: 'white',
                        border: 'none', borderRadius: 'var(--radius)', cursor: 'pointer',
                        fontWeight: 500, fontSize: '0.875rem',
                        opacity: (importMode === 'url' ? !importUrl.trim() : !importFile) ? 0.5 : 1,
                    }}
                >
                    <Upload size={16} /> Import & Generate Tests
                </button>
            </div>

            {/* Active import jobs */}
            {Object.entries(activeJobs).filter(([_, j]) => j.message?.includes('import') || j.message?.includes('OpenAPI')).length > 0 && (
                <div style={{ marginTop: '1rem' }}>
                    <h4 style={{ fontSize: '0.875rem', fontWeight: 600, marginBottom: '0.5rem' }}>Import Jobs</h4>
                    {Object.entries(activeJobs)
                        .filter(([_, j]) => j.message?.toLowerCase().includes('import') || j.message?.toLowerCase().includes('openapi'))
                        .map(([id, job]) => (
                            <div key={id} style={{
                                padding: '0.75rem', background: 'var(--surface)',
                                border: '1px solid var(--border)', borderRadius: 'var(--radius)',
                                display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '0.5rem',
                            }}>
                                {job.status === 'running' ? (
                                    <Loader2 size={16} style={{ color: 'var(--primary)', animation: 'spin 1s linear infinite' }} />
                                ) : job.status === 'completed' ? (
                                    <CheckCircle size={16} style={{ color: 'var(--success)' }} />
                                ) : (
                                    <AlertCircle size={16} style={{ color: 'var(--danger)' }} />
                                )}
                                <div style={{ flex: 1 }}>
                                    <div style={{ fontSize: '0.8rem', fontWeight: 500 }}>{job.message}</div>
                                    {job.result?.files && (
                                        <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', marginTop: '0.25rem' }}>
                                            Files: {job.result.files.join(', ')}
                                        </div>
                                    )}
                                </div>
                                <span style={{
                                    fontSize: '0.7rem', padding: '0.15rem 0.5rem', borderRadius: '999px',
                                    background: job.status === 'running' ? 'var(--primary-glow)' : job.status === 'completed' ? 'var(--success-muted)' : 'var(--danger-muted)',
                                    color: job.status === 'running' ? 'var(--primary)' : job.status === 'completed' ? 'var(--success)' : 'var(--danger)',
                                }}>
                                    {job.status}
                                </span>
                            </div>
                        ))}
                </div>
            )}

            {/* Import History */}
            <div style={{ marginTop: '1.5rem' }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.75rem' }}>
                    <h4 style={{ fontSize: '0.875rem', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                        <Clock size={14} /> Import History
                        {historyTotal > 0 && (
                            <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', fontWeight: 400 }}>
                                ({historyTotal})
                            </span>
                        )}
                    </h4>
                    <button
                        onClick={() => fetchHistory(0, false)}
                        disabled={historyLoading}
                        style={{
                            display: 'flex', alignItems: 'center', gap: '0.3rem',
                            padding: '0.3rem 0.6rem', fontSize: '0.75rem',
                            background: 'transparent', border: '1px solid var(--border)',
                            borderRadius: 'var(--radius)', cursor: 'pointer',
                            color: 'var(--text-secondary)',
                        }}
                    >
                        <RefreshCw size={12} style={historyLoading ? { animation: 'spin 1s linear infinite' } : {}} /> Refresh
                    </button>
                </div>

                {history.length === 0 && !historyLoading ? (
                    <div style={{
                        padding: '2rem', textAlign: 'center', color: 'var(--text-secondary)',
                        background: 'var(--surface)', border: '1px solid var(--border)',
                        borderRadius: 'var(--radius)', fontSize: '0.85rem',
                    }}>
                        No imports yet. Import an OpenAPI spec above to get started.
                    </div>
                ) : (
                    <div style={{
                        background: 'var(--surface)', border: '1px solid var(--border)',
                        borderRadius: 'var(--radius)', overflow: 'hidden',
                    }}>
                        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.8rem' }}>
                            <thead>
                                <tr style={{ borderBottom: '1px solid var(--border)' }}>
                                    <th style={{ padding: '0.6rem 0.75rem', textAlign: 'left', fontWeight: 600, color: 'var(--text-secondary)', fontSize: '0.75rem' }}>Source</th>
                                    <th style={{ padding: '0.6rem 0.75rem', textAlign: 'left', fontWeight: 600, color: 'var(--text-secondary)', fontSize: '0.75rem' }}>Filter</th>
                                    <th style={{ padding: '0.6rem 0.75rem', textAlign: 'center', fontWeight: 600, color: 'var(--text-secondary)', fontSize: '0.75rem' }}>Status</th>
                                    <th style={{ padding: '0.6rem 0.75rem', textAlign: 'center', fontWeight: 600, color: 'var(--text-secondary)', fontSize: '0.75rem' }}>Files</th>
                                    <th style={{ padding: '0.6rem 0.75rem', textAlign: 'right', fontWeight: 600, color: 'var(--text-secondary)', fontSize: '0.75rem' }}>Date</th>
                                    <th style={{ padding: '0.6rem 0.75rem', textAlign: 'center', fontWeight: 600, color: 'var(--text-secondary)', fontSize: '0.75rem' }}></th>
                                </tr>
                            </thead>
                            <tbody>
                                {history.map(record => {
                                    const isExpanded = expandedRows.has(record.id);
                                    const hasFiles = record.generated_paths && record.generated_paths.length > 0;
                                    return (
                                        <React.Fragment key={record.id}>
                                            <tr style={{ borderBottom: isExpanded ? 'none' : '1px solid var(--border)' }}>
                                                <td style={{ padding: '0.6rem 0.75rem', maxWidth: '300px' }}>
                                                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                                                        {record.source_type === 'url' ? (
                                                            <Globe size={13} style={{ color: 'var(--primary)', flexShrink: 0 }} />
                                                        ) : (
                                                            <FileText size={13} style={{ color: 'var(--text-secondary)', flexShrink: 0 }} />
                                                        )}
                                                        <span style={{
                                                            overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                                                            fontSize: '0.8rem',
                                                        }} title={record.source_url || record.source_filename || ''}>
                                                            {record.source_type === 'url'
                                                                ? record.source_url
                                                                : record.source_filename || 'uploaded file'}
                                                        </span>
                                                    </div>
                                                </td>
                                                <td style={{ padding: '0.6rem 0.75rem', color: 'var(--text-secondary)', fontSize: '0.8rem' }}>
                                                    {record.feature_filter || '\u2014'}
                                                </td>
                                                <td style={{ padding: '0.6rem 0.75rem', textAlign: 'center' }}>
                                                    {statusBadge(record.status)}
                                                </td>
                                                <td style={{ padding: '0.6rem 0.75rem', textAlign: 'center' }}>
                                                    {hasFiles ? (
                                                        <button
                                                            onClick={() => toggleRow(record.id)}
                                                            style={{
                                                                display: 'inline-flex', alignItems: 'center', gap: '0.2rem',
                                                                background: 'none', border: 'none', cursor: 'pointer',
                                                                color: 'var(--primary)', fontSize: '0.8rem', fontVariantNumeric: 'tabular-nums',
                                                                padding: '0.1rem 0.3rem', borderRadius: 'var(--radius)',
                                                            }}
                                                            title="Click to see generated files"
                                                        >
                                                            {record.files_generated}
                                                            {isExpanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                                                        </button>
                                                    ) : (
                                                        <span style={{ fontVariantNumeric: 'tabular-nums' }}>{record.files_generated}</span>
                                                    )}
                                                </td>
                                                <td style={{ padding: '0.6rem 0.75rem', textAlign: 'right', color: 'var(--text-secondary)', whiteSpace: 'nowrap' }}
                                                    title={record.created_at ? new Date(record.created_at).toLocaleString() : ''}>
                                                    {record.created_at ? timeAgo(record.created_at) : '\u2014'}
                                                </td>
                                                <td style={{ padding: '0.6rem 0.75rem', textAlign: 'center' }}>
                                                    {record.source_type === 'url' && record.source_url && (
                                                        <button
                                                            onClick={() => handleReimport(record)}
                                                            title="Re-import from this URL"
                                                            style={{
                                                                display: 'inline-flex', alignItems: 'center', gap: '0.3rem',
                                                                padding: '0.25rem 0.5rem', fontSize: '0.7rem',
                                                                background: 'transparent', border: '1px solid var(--border)',
                                                                borderRadius: 'var(--radius)', cursor: 'pointer',
                                                                color: 'var(--primary)',
                                                            }}
                                                        >
                                                            <RefreshCw size={11} /> Re-import
                                                        </button>
                                                    )}
                                                </td>
                                            </tr>
                                            {isExpanded && hasFiles && (
                                                <tr style={{ borderBottom: '1px solid var(--border)' }}>
                                                    <td colSpan={6} style={{ padding: '0 0.75rem 0.6rem 2.2rem', background: 'var(--background)' }}>
                                                        <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', marginBottom: '0.3rem', fontWeight: 500 }}>
                                                            Generated files:
                                                        </div>
                                                        {record.generated_paths.map((p, i) => {
                                                            const fileName = p.split('/').pop() || p;
                                                            return (
                                                                <div key={i} style={{
                                                                    display: 'flex', alignItems: 'center', gap: '0.4rem',
                                                                    fontSize: '0.75rem', padding: '0.15rem 0',
                                                                    color: 'var(--text-primary)',
                                                                }}>
                                                                    <FileText size={11} style={{ color: 'var(--text-secondary)', flexShrink: 0 }} />
                                                                    <span title={p}>{fileName}</span>
                                                                </div>
                                                            );
                                                        })}
                                                    </td>
                                                </tr>
                                            )}
                                        </React.Fragment>
                                    );
                                })}
                            </tbody>
                        </table>

                        {/* Load More */}
                        {historyOffset < historyTotal && (
                            <div style={{ padding: '0.75rem', textAlign: 'center', borderTop: '1px solid var(--border)' }}>
                                <button
                                    onClick={() => fetchHistory(historyOffset, true)}
                                    disabled={historyLoading}
                                    style={{
                                        padding: '0.4rem 1rem', fontSize: '0.8rem',
                                        background: 'transparent', border: '1px solid var(--border)',
                                        borderRadius: 'var(--radius)', cursor: 'pointer',
                                        color: 'var(--text-secondary)',
                                    }}
                                >
                                    {historyLoading ? 'Loading...' : `Load More (${historyTotal - historyOffset} remaining)`}
                                </button>
                            </div>
                        )}
                    </div>
                )}
            </div>
        </div>
    );
}
