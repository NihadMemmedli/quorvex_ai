'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import Link from 'next/link';
import { CheckCircle2, Code2, ExternalLink, FileText, Loader2, MousePointerClick, Play, Square, Upload, XCircle } from 'lucide-react';
import { useProject } from '@/contexts/ProjectContext';
import { useProjectRole } from '@/hooks/useProjectRole';
import { API_BASE } from '@/lib/api';
import { PageHeader } from '@/components/ui/page-header';
import { PageLayout } from '@/components/ui/page-layout';

interface RecordingSession {
    id: string;
    project_id: string | null;
    status: 'starting' | 'recording' | 'completed' | 'stopped' | 'failed';
    target_url: string;
    engine: string;
    name: string | null;
    output_spec_path: string | null;
    output_code_path: string | null;
    artifact_dir: string | null;
    process_id: number | null;
    browser_url: string | null;
    error: string | null;
    config: Record<string, unknown>;
    created_at: string;
    started_at: string | null;
    completed_at: string | null;
    duration_seconds: number | null;
}

interface RecordingListResponse {
    items: RecordingSession[];
    total: number;
}

interface ImportResult {
    spec_path: string;
    code_path: string;
    parsed_steps: number;
    unsupported_lines: number;
}

const statusMeta: Record<RecordingSession['status'], { label: string; color: string; icon: ReactNode }> = {
    starting: { label: 'Starting', color: 'var(--warning)', icon: <Loader2 size={14} className="spin" /> },
    recording: { label: 'Recording', color: 'var(--primary)', icon: <MousePointerClick size={14} /> },
    completed: { label: 'Completed', color: 'var(--success)', icon: <CheckCircle2 size={14} /> },
    stopped: { label: 'Stopped', color: 'var(--text-secondary)', icon: <Square size={14} /> },
    failed: { label: 'Failed', color: 'var(--danger)', icon: <XCircle size={14} /> },
};

function getErrorMessage(err: unknown): string {
    return err instanceof Error ? err.message : 'Unexpected error';
}

function statusBadge(status: RecordingSession['status']) {
    const meta = statusMeta[status];
    return (
        <span style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: '0.35rem',
            padding: '0.3rem 0.55rem',
            borderRadius: '999px',
            background: 'rgba(255,255,255,0.04)',
            border: '1px solid var(--border)',
            color: meta.color,
            fontSize: '0.78rem',
            fontWeight: 600,
        }}>
            {meta.icon}
            {meta.label}
        </span>
    );
}

function isLocalDashboardHost(hostname: string): boolean {
    return hostname === 'localhost' || hostname === '127.0.0.1' || hostname === '::1' || hostname === '[::1]';
}

function formatLocalRecorderHost(hostname: string): string {
    return hostname === '::1' ? '[::1]' : hostname;
}

function localRecorderBrowserUrl(): string | null {
    if (typeof window === 'undefined') return null;
    const hostname = window.location.hostname;
    if (!isLocalDashboardHost(hostname)) return null;
    return `http://${formatLocalRecorderHost(hostname)}:6080/vnc.html?autoconnect=true&resize=scale`;
}

function recorderBrowserUrl(session: RecordingSession): string | null {
    if (!session.browser_url) return localRecorderBrowserUrl();
    if (typeof window === 'undefined') return session.browser_url;
    try {
        const url = new URL(session.browser_url);
        if (isLocalDashboardHost(url.hostname)) {
            url.hostname = formatLocalRecorderHost(window.location.hostname);
        }
        return url.toString();
    } catch {
        return session.browser_url;
    }
}

function optionalInput(value: string): string | undefined {
    const trimmed = value.trim();
    return trimmed ? trimmed : undefined;
}

async function jsonFetch<T>(url: string, options?: RequestInit): Promise<T> {
    const res = await fetch(url, options);
    const data = await res.json().catch(() => null);
    if (!res.ok) {
        throw new Error(data?.detail || `Request failed: ${res.status}`);
    }
    return data as T;
}

export default function RecordingsPage() {
    const { currentProject, isLoading: projectLoading } = useProject();
    const [targetUrl, setTargetUrl] = useState('');
    const [name, setName] = useState('');
    const [viewportSize, setViewportSize] = useState('1280,720');
    const [device, setDevice] = useState('');
    const [saveHar, setSaveHar] = useState(false);
    const [saveStorage, setSaveStorage] = useState(false);
    const [sessions, setSessions] = useState<RecordingSession[]>([]);
    const [activeSession, setActiveSession] = useState<RecordingSession | null>(null);
    const [isStarting, setIsStarting] = useState(false);
    const [isStopping, setIsStopping] = useState(false);
    const [importingId, setImportingId] = useState<string | null>(null);
    const [importResult, setImportResult] = useState<ImportResult | null>(null);
    const [error, setError] = useState<string | null>(null);

    const projectId = currentProject?.id || 'default';
    const { canEdit, isLoading: roleLoading } = useProjectRole(projectId);
    const isRecording = activeSession?.status === 'starting' || activeSession?.status === 'recording';
    const activeRecorderUrl = activeSession ? recorderBrowserUrl(activeSession) : null;

    const projectParam = useMemo(() => {
        const params = new URLSearchParams();
        params.set('project_id', projectId);
        return params.toString();
    }, [projectId]);

    const loadSessions = useCallback(async () => {
        if (projectLoading) return;
        const data = await jsonFetch<RecordingListResponse>(`${API_BASE}/recordings?${projectParam}`);
        setSessions(data.items);
        const active = data.items.find(item => item.status === 'starting' || item.status === 'recording') || null;
        setActiveSession(active);
    }, [projectLoading, projectParam]);

    useEffect(() => {
        loadSessions().catch(err => setError(getErrorMessage(err)));
    }, [loadSessions]);

    useEffect(() => {
        if (!isRecording) return;
        const timer = setInterval(() => {
            loadSessions().catch(err => setError(getErrorMessage(err)));
        }, 2500);
        return () => clearInterval(timer);
    }, [isRecording, loadSessions]);

    const startRecording = async () => {
        if (!canEdit) return;
        setError(null);
        setImportResult(null);
        setIsStarting(true);
        try {
            const selectedDevice = optionalInput(device);
            const body = {
                target_url: targetUrl.trim(),
                project_id: projectId,
                name: optionalInput(name),
                viewport_size: selectedDevice ? undefined : optionalInput(viewportSize),
                device: selectedDevice,
                save_har: saveHar,
                save_storage: saveStorage,
            };
            const session = await jsonFetch<RecordingSession>(`${API_BASE}/recordings/start`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });
            setActiveSession(session);
            setSessions(prev => [session, ...prev.filter(item => item.id !== session.id)]);
        } catch (err) {
            setError(getErrorMessage(err));
        } finally {
            setIsStarting(false);
        }
    };

    const stopRecording = async (sessionId: string) => {
        if (!canEdit) return;
        setError(null);
        setIsStopping(true);
        try {
            const session = await jsonFetch<RecordingSession>(`${API_BASE}/recordings/${sessionId}/stop`, { method: 'POST' });
            setActiveSession(null);
            setSessions(prev => prev.map(item => item.id === session.id ? session : item));
        } catch (err) {
            setError(getErrorMessage(err));
        } finally {
            setIsStopping(false);
        }
    };

    const importSession = async (session: RecordingSession) => {
        if (!canEdit) return;
        setError(null);
        setImportResult(null);
        setImportingId(session.id);
        try {
            const data = await jsonFetch<{ session: RecordingSession } & ImportResult>(`${API_BASE}/recordings/${session.id}/import`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name: optionalInput(name) || session.name || undefined }),
            });
            setImportResult(data);
            setSessions(prev => prev.map(item => item.id === data.session.id ? data.session : item));
        } catch (err) {
            setError(getErrorMessage(err));
        } finally {
            setImportingId(null);
        }
    };

    return (
        <PageLayout tier="wide">
            <PageHeader
                title="Recording Mode"
                subtitle="Capture a browser flow with Playwright and import it as a Quorvex spec."
                icon={<MousePointerClick size={22} />}
            />

            <div style={{ display: 'grid', gridTemplateColumns: canEdit ? 'minmax(320px, 420px) 1fr' : '1fr', gap: '1rem', alignItems: 'start' }}>
                {canEdit && (
                    <section className="card-elevated">
                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '1rem' }}>
                            <Play size={18} color="var(--primary)" />
                            <h2 style={{ margin: 0, fontSize: '1rem' }}>New Recording</h2>
                        </div>

                        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.9rem' }}>
                            <label className="form-group">
                                <span className="label">Target URL</span>
                                <input
                                    className="input"
                                    value={targetUrl}
                                    onChange={event => setTargetUrl(event.target.value)}
                                    placeholder="https://example.com/login"
                                    disabled={isRecording || isStarting}
                                />
                            </label>

                            <label className="form-group">
                                <span className="label">Spec Name</span>
                                <input
                                    className="input"
                                    value={name}
                                    onChange={event => setName(event.target.value)}
                                    placeholder="Login happy path"
                                    disabled={isRecording || isStarting}
                                />
                            </label>

                            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem' }}>
                                <label className="form-group">
                                    <span className="label">Viewport</span>
                                    <input
                                        className="input"
                                        value={viewportSize}
                                        onChange={event => setViewportSize(event.target.value)}
                                        placeholder="1280,720"
                                        disabled={isRecording || isStarting}
                                    />
                                </label>
                                <label className="form-group">
                                    <span className="label">Device</span>
                                    <input
                                        className="input"
                                        value={device}
                                        onChange={event => setDevice(event.target.value)}
                                        placeholder="Optional preset"
                                        disabled={isRecording || isStarting}
                                    />
                                </label>
                            </div>

                            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.55rem' }}>
                                <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', color: 'var(--text-secondary)', fontSize: '0.875rem' }}>
                                    <input type="checkbox" checked={saveHar} onChange={event => setSaveHar(event.target.checked)} disabled={isRecording || isStarting} />
                                    Save HAR
                                </label>
                                <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', color: 'var(--text-secondary)', fontSize: '0.875rem' }}>
                                    <input type="checkbox" checked={saveStorage} onChange={event => setSaveStorage(event.target.checked)} disabled={isRecording || isStarting} />
                                    Save storage state
                                </label>
                            </div>

                            {error && (
                                <div style={{
                                    padding: '0.75rem',
                                    borderRadius: 'var(--radius-sm)',
                                    border: '1px solid rgba(239, 68, 68, 0.35)',
                                    background: 'rgba(239, 68, 68, 0.08)',
                                    color: 'var(--danger)',
                                    fontSize: '0.85rem',
                                }}>
                                    {error}
                                </div>
                            )}

                            <button
                                className="btn btn-primary"
                                onClick={startRecording}
                                disabled={isStarting || isRecording || !targetUrl.trim()}
                                style={{ justifyContent: 'center', cursor: isStarting || isRecording ? 'not-allowed' : 'pointer' }}
                            >
                                {isStarting ? <Loader2 size={16} className="spin" /> : <MousePointerClick size={16} />}
                                Start Recording
                            </button>
                        </div>
                    </section>
                )}

                <section style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                    {!roleLoading && !canEdit && (
                        <div className="card-elevated" style={{ color: 'var(--text-secondary)', fontSize: '0.875rem' }}>
                            You have read-only access to this project. Recording sessions and generated artifacts are visible, but recorder controls are disabled.
                        </div>
                    )}

                    {activeSession && (
                        <div className="card-elevated" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '1rem' }}>
                            <div>
                                <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', marginBottom: '0.4rem' }}>
                                    {statusBadge(activeSession.status)}
                                    <span style={{ color: 'var(--text-tertiary)', fontSize: '0.82rem' }}>PID {activeSession.process_id || '-'}</span>
                                </div>
                                <div style={{ fontWeight: 700 }}>{activeSession.name || 'Recording session'}</div>
                                <div style={{ color: 'var(--text-secondary)', fontSize: '0.85rem', marginTop: '0.25rem' }}>{activeSession.target_url}</div>
                                {canEdit && activeRecorderUrl && (
                                    <div style={{ marginTop: '0.65rem', display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
                                        <span style={{ color: 'var(--text-tertiary)', fontSize: '0.82rem' }}>
                                            The recorder browser is running in the backend display.
                                        </span>
                                        <a
                                            className="btn btn-secondary"
                                            href={activeRecorderUrl}
                                            target="_blank"
                                            rel="noreferrer"
                                            style={{ padding: '0.4rem 0.65rem', textDecoration: 'none' }}
                                        >
                                            <ExternalLink size={14} />
                                            Open Recorder
                                        </a>
                                    </div>
                                )}
                            </div>
                            {canEdit && (
                                <button
                                    className="btn btn-secondary"
                                    onClick={() => stopRecording(activeSession.id)}
                                    disabled={isStopping}
                                    style={{ cursor: isStopping ? 'not-allowed' : 'pointer' }}
                                >
                                    {isStopping ? <Loader2 size={16} className="spin" /> : <Square size={16} />}
                                    Stop
                                </button>
                            )}
                        </div>
                    )}

                    {importResult && (
                        <div className="card-elevated" style={{ borderColor: 'rgba(16, 185, 129, 0.35)' }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.6rem', color: 'var(--success)', fontWeight: 700 }}>
                                <CheckCircle2 size={18} />
                                Recording imported
                            </div>
                            <div style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap', fontSize: '0.875rem' }}>
                                <Link href={`/specs/${importResult.spec_path}`} style={{ color: 'var(--primary)', display: 'inline-flex', alignItems: 'center', gap: '0.35rem' }}>
                                    <FileText size={14} /> Open spec
                                </Link>
                                <span style={{ color: 'var(--text-secondary)' }}>{importResult.parsed_steps} parsed steps</span>
                                {importResult.unsupported_lines > 0 && <span style={{ color: 'var(--warning)' }}>{importResult.unsupported_lines} lines need review</span>}
                            </div>
                        </div>
                    )}

                    <div className="card-elevated">
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '1rem', marginBottom: '1rem' }}>
                            <div>
                                <h2 style={{ margin: 0, fontSize: '1rem' }}>Recent Recordings</h2>
                                <p style={{ margin: '0.25rem 0 0', color: 'var(--text-tertiary)', fontSize: '0.85rem' }}>{currentProject?.name || 'Current project'}</p>
                            </div>
                            <button className="btn btn-secondary" onClick={() => loadSessions()} style={{ padding: '0.55rem 0.85rem', cursor: 'pointer' }}>
                                Refresh
                            </button>
                        </div>

                        {sessions.length === 0 ? (
                            <div style={{
                                display: 'flex',
                                flexDirection: 'column',
                                alignItems: 'center',
                                justifyContent: 'center',
                                minHeight: '220px',
                                color: 'var(--text-tertiary)',
                                textAlign: 'center',
                            }}>
                                <MousePointerClick size={28} style={{ marginBottom: '0.75rem' }} />
                                <h3 style={{ margin: 0, color: 'var(--text)', fontSize: '1rem' }}>No recordings yet</h3>
                                <p style={{ margin: '0.35rem 0 0', fontSize: '0.875rem' }}>Start a session to create a recorded test flow.</p>
                            </div>
                        ) : (
                            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.65rem' }}>
                                {sessions.map(session => {
                                    const isLiveSession = session.status === 'starting' || session.status === 'recording';
                                    const rowRecorderUrl = isLiveSession ? recorderBrowserUrl(session) : null;

                                    return (
                                        <div
                                            key={session.id}
                                            style={{
                                                display: 'grid',
                                                gridTemplateColumns: '1fr auto',
                                                gap: '1rem',
                                                alignItems: 'center',
                                                padding: '0.85rem',
                                                border: '1px solid var(--border)',
                                                borderRadius: 'var(--radius-sm)',
                                                background: 'rgba(255,255,255,0.02)',
                                            }}
                                        >
                                            <div style={{ minWidth: 0 }}>
                                                <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', marginBottom: '0.45rem', flexWrap: 'wrap' }}>
                                                    {statusBadge(session.status)}
                                                    <span style={{ color: 'var(--text-tertiary)', fontSize: '0.78rem' }}>{new Date(session.created_at).toLocaleString()}</span>
                                                </div>
                                                <div style={{ fontWeight: 700, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                                    {session.name || session.id}
                                                </div>
                                                <div style={{ color: 'var(--text-secondary)', fontSize: '0.84rem', marginTop: '0.25rem', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                                    {session.target_url}
                                                </div>
                                                {session.error && <div style={{ color: 'var(--danger)', fontSize: '0.8rem', marginTop: '0.35rem' }}>{session.error}</div>}
                                            </div>
                                            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap', justifyContent: 'flex-end' }}>
                                                {canEdit && rowRecorderUrl && (
                                                    <a className="btn btn-secondary" href={rowRecorderUrl} target="_blank" rel="noreferrer" style={{ padding: '0.5rem 0.75rem', textDecoration: 'none' }}>
                                                        <ExternalLink size={14} /> Open Recorder
                                                    </a>
                                                )}
                                                {session.output_spec_path && (
                                                    <Link className="btn btn-secondary" href={`/specs/${session.output_spec_path}`} style={{ padding: '0.5rem 0.75rem', textDecoration: 'none' }}>
                                                        <FileText size={14} /> Spec
                                                    </Link>
                                                )}
                                                {session.output_code_path && (
                                                    <a className="btn btn-secondary" href={`${API_BASE}/recordings/${session.id}/code`} target="_blank" rel="noreferrer" style={{ padding: '0.5rem 0.75rem', textDecoration: 'none' }}>
                                                        <Code2 size={14} /> Code <ExternalLink size={12} />
                                                    </a>
                                                )}
                                                {canEdit && (session.status === 'completed' || session.status === 'stopped') && (
                                                    <button
                                                        className="btn btn-primary"
                                                        onClick={() => importSession(session)}
                                                        disabled={importingId === session.id}
                                                        style={{ padding: '0.5rem 0.75rem', cursor: importingId === session.id ? 'not-allowed' : 'pointer' }}
                                                    >
                                                        {importingId === session.id ? <Loader2 size={14} className="spin" /> : <Upload size={14} />}
                                                        Import
                                                    </button>
                                                )}
                                            </div>
                                        </div>
                                    );
                                })}
                            </div>
                        )}
                    </div>
                </section>
            </div>
        </PageLayout>
    );
}
