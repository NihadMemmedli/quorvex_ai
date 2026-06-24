'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import type { CSSProperties } from 'react';
import { CheckCircle, Clock, Key, Loader2, Plus, RefreshCw, ShieldCheck, SlidersHorizontal, Star, Trash2 } from 'lucide-react';
import { API_BASE } from '@/lib/api';
import { getAuthHeaders } from '@/lib/styles';

interface BrowserAuthSession {
    id: string;
    name: string;
    base_url: string;
    login_url: string;
    username_key: string;
    password_key: string;
    username_selector?: string | null;
    password_selector?: string | null;
    username_continue_selector?: string | null;
    submit_selector?: string | null;
    success_url_pattern?: string | null;
    status: string;
    is_default: boolean;
    last_validated_at?: string | null;
    expires_at?: string | null;
    failure_reason?: string | null;
    capture_backend_version?: string | null;
}

interface Credential {
    key: string;
    source: 'project' | 'env';
}

interface BrowserAuthSessionsManagerProps {
    projectId: string;
}

type CredentialMode = 'existing' | 'direct';
type SessionAction = 'validate' | 'refresh' | 'default' | 'delete';

function formatTime(value?: string | null) {
    if (!value) return 'Never';
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? 'Never' : date.toLocaleString();
}

async function readApiError(res: Response, fallback: string) {
    try {
        const data = await res.json();
        if (Array.isArray(data.detail)) {
            return data.detail.map((item: unknown) => String(item)).join(', ') || fallback;
        }
        return data.detail || fallback;
    } catch {
        return fallback;
    }
}

function jsonHeaders() {
    return { ...getAuthHeaders(), 'Content-Type': 'application/json' };
}

function friendlyCaptureError(detail: string, mode: 'capture' | 'refresh' = 'capture') {
    const lower = detail.toLowerCase();
    if (lower.includes('direct playwright capture failed') || lower.includes('mcp fallback failed')) {
        return detail;
    }
    if (
        lower.includes('llm provider api key is not configured') ||
        lower.includes('llm runtime is not authenticated') ||
        lower.includes('not logged in') ||
        lower.includes('please run /login')
    ) {
        if (mode === 'refresh') {
            return 'Refresh uses AI browser capture. Add an LLM API key in Settings or deployment secrets, then retry.';
        }
        return 'AI browser capture needs an LLM API key. Add one in Settings or deployment secrets, then retry.';
    }
    if (lower.includes('security challenge') || lower.includes('cloudflare') || lower.includes('anti-bot')) {
        return 'Login capture stopped on a security challenge. Automated capture cannot bypass Cloudflare or anti-bot checks; allowlist the capture browser or disable the challenge for this environment.';
    }
    if (lower.includes('password field not found')) {
        return 'Login capture could not find the password field after submitting the username. Add a password selector or username continue selector in Advanced selectors.';
    }
    if (lower.includes('login form not found') || lower.includes('username or password input')) {
        return 'Login capture could not find a usable login form. Check the login URL or add explicit username and password selectors in Advanced selectors.';
    }
    if (lower.includes('success_url_pattern')) {
        return detail;
    }
    return detail;
}

function modeButtonStyle(active: boolean): CSSProperties {
    return {
        minHeight: 42,
        justifyContent: 'center',
        background: active ? 'var(--primary)' : 'var(--surface)',
        color: active ? '#fff' : 'var(--text)',
        border: active ? '1px solid var(--primary)' : '1px solid var(--border)',
        boxShadow: active ? '0 0 0 1px rgba(82, 126, 247, 0.18)' : 'none',
    };
}

export function BrowserAuthSessionsManager({ projectId }: BrowserAuthSessionsManagerProps) {
    const [sessions, setSessions] = useState<BrowserAuthSession[]>([]);
    const [credentials, setCredentials] = useState<Credential[]>([]);
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);
    const [busyId, setBusyId] = useState<string | null>(null);
    const [busyAction, setBusyAction] = useState<SessionAction | null>(null);
    const [message, setMessage] = useState<{ type: 'success' | 'error' | 'info'; text: string } | null>(null);
    const [credentialMode, setCredentialMode] = useState<CredentialMode>('existing');
    const [form, setForm] = useState({
        name: '',
        base_url: '',
        login_url: '',
        username_key: '',
        password_key: '',
        make_default: true,
        username_value: '',
        password_value: '',
        direct_username_key: 'LOGIN_USERNAME',
        direct_password_key: 'LOGIN_PASSWORD',
        username_selector: '',
        password_selector: '',
        username_continue_selector: '',
        submit_selector: '',
        success_url_pattern: '',
    });

    const credentialKeys = useMemo(() => credentials.map(item => item.key), [credentials]);

    const load = useCallback(async (preserveMessage = false) => {
        setLoading(true);
        if (!preserveMessage) setMessage(null);
        try {
            const pid = encodeURIComponent(projectId);
            const [sessionsRes, credentialsRes] = await Promise.all([
                fetch(`${API_BASE}/projects/${pid}/browser-auth-sessions`, { headers: getAuthHeaders() }),
                fetch(`${API_BASE}/projects/${pid}/credentials?include_env=true`, { headers: getAuthHeaders() }),
            ]);
            if (!sessionsRes.ok) {
                throw new Error(await readApiError(sessionsRes, 'Failed to load browser login sessions'));
            }
            if (!credentialsRes.ok) {
                throw new Error(await readApiError(credentialsRes, 'Failed to load credential keys'));
            }
            const sessionsData = await sessionsRes.json();
            const credentialsData = await credentialsRes.json();
            const loadedCredentials = credentialsData.credentials || [];
            setSessions(sessionsData.sessions || []);
            setCredentials(loadedCredentials);
            setForm(prev => ({
                ...prev,
                username_key: prev.username_key || loadedCredentials.find((item: Credential) => /USER|EMAIL|LOGIN/i.test(item.key))?.key || '',
                password_key: prev.password_key || loadedCredentials.find((item: Credential) => /PASSWORD/i.test(item.key))?.key || '',
            }));
            return true;
        } catch (err: any) {
            setMessage({ type: 'error', text: err.message || 'Failed to load browser login sessions' });
            return false;
        } finally {
            setLoading(false);
        }
    }, [projectId]);

    useEffect(() => {
        load();
    }, [load]);

    const saveCredential = async (key: string, value: string) => {
        const res = await fetch(`${API_BASE}/projects/${encodeURIComponent(projectId)}/credentials`, {
            method: 'POST',
            headers: jsonHeaders(),
            body: JSON.stringify({ key, value }),
        });
        if (!res.ok) throw new Error(await readApiError(res, `Failed to save credential ${key}`));
    };

    const createSession = async (event: React.FormEvent) => {
        event.preventDefault();
        const baseUrl = form.base_url.trim();
        const loginUrl = form.login_url.trim();
        const usernameKey = credentialMode === 'direct' ? form.direct_username_key.trim() : form.username_key;
        const passwordKey = credentialMode === 'direct' ? form.direct_password_key.trim() : form.password_key;

        if (!baseUrl || !loginUrl || !usernameKey || !passwordKey) {
            setMessage({ type: 'error', text: 'Base URL, login URL, username key, and password key are required.' });
            return;
        }
        if (credentialMode === 'direct' && (!form.username_value.trim() || !form.password_value)) {
            setMessage({ type: 'error', text: 'Username and password are required when entering credentials.' });
            return;
        }

        setSaving(true);
        setMessage({ type: 'info', text: 'Opening the login page and capturing reusable browser state...' });
        try {
            if (credentialMode === 'direct') {
                await saveCredential(usernameKey, form.username_value.trim());
                await saveCredential(passwordKey, form.password_value);
            }

            const res = await fetch(`${API_BASE}/projects/${encodeURIComponent(projectId)}/browser-auth-sessions`, {
                method: 'POST',
                headers: jsonHeaders(),
                body: JSON.stringify({
                    name: form.name.trim() || undefined,
                    base_url: baseUrl,
                    login_url: loginUrl,
                    username_key: usernameKey,
                    password_key: passwordKey,
                    username_selector: form.username_selector.trim() || undefined,
                    password_selector: form.password_selector.trim() || undefined,
                    username_continue_selector: form.username_continue_selector.trim() || undefined,
                    submit_selector: form.submit_selector.trim() || undefined,
                    success_url_pattern: form.success_url_pattern.trim() || undefined,
                    make_default: form.make_default,
                }),
            });
            if (!res.ok) {
                const detail = await readApiError(res, 'Failed to create browser login session');
                await load(true);
                if (res.status === 404 && /^not found$/i.test(detail)) {
                    throw new Error('Browser login session API is not available on the running backend. Restart or rebuild the backend so the browser-auth-sessions route is registered.');
                }
                throw new Error(res.status === 400 ? `Login capture failed. ${friendlyCaptureError(detail)}` : detail);
            }
            const created = await res.json();
            setForm(prev => ({
                ...prev,
                name: '',
                username_key: credentialMode === 'direct' ? usernameKey : prev.username_key,
                password_key: credentialMode === 'direct' ? passwordKey : prev.password_key,
                username_value: '',
                password_value: '',
                username_selector: '',
                password_selector: '',
                username_continue_selector: '',
                submit_selector: '',
                success_url_pattern: '',
            }));
            const reloaded = await load(true);
            if (reloaded) setMessage({ type: 'success', text: `Browser login session created. Capture backend ${created.capture_backend_version || 'MCP storage capture'}.` });
        } catch (err: any) {
            setMessage({ type: 'error', text: err.message || 'Failed to create browser login session' });
        } finally {
            setSaving(false);
        }
    };

    const runSessionAction = async (id: string, action: SessionAction) => {
        setBusyId(id);
        setBusyAction(action);
        setMessage(null);
        const method = action === 'default' ? 'PATCH' : action === 'delete' ? 'DELETE' : 'POST';
        const suffix = action === 'delete' ? '' : `/${action}`;
        try {
            const res = await fetch(`${API_BASE}/projects/${encodeURIComponent(projectId)}/browser-auth-sessions/${encodeURIComponent(id)}${suffix}`, {
                method,
                headers: getAuthHeaders(),
            });
            if (!res.ok) {
                const detail = await readApiError(res, `Failed to ${action} browser login session`);
                throw new Error(action === 'refresh' ? friendlyCaptureError(detail, 'refresh') : detail);
            }
            const reloaded = await load(true);
            if (reloaded) setMessage({ type: 'success', text: action === 'delete' ? 'Browser login session revoked.' : 'Browser login session updated.' });
        } catch (err: any) {
            if (action === 'refresh') await load(true);
            setMessage({ type: 'error', text: err.message || `Failed to ${action} browser login session` });
        } finally {
            setBusyId(null);
            setBusyAction(null);
        }
    };

    if (loading) {
        return (
            <div style={{ display: 'flex', justifyContent: 'center', padding: '2rem' }}>
                <div className="loading-spinner" />
            </div>
        );
    }

    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
            <div style={{
                display: 'flex',
                gap: '0.75rem',
                alignItems: 'flex-start',
                padding: '1rem',
                border: '1px solid var(--border)',
                borderRadius: 'var(--radius)',
                background: 'var(--surface)'
            }}>
                <Key size={20} style={{ color: 'var(--primary)', marginTop: 2, flexShrink: 0 }} />
                <div style={{ color: 'var(--text-secondary)', fontSize: '0.875rem', lineHeight: 1.5 }}>
                    Capture reusable browser state for later agent, live-browser, and exploration runs so protected pages open already signed in. Validate checks that stored state can be decrypted; Refresh opens the login page and captures a new state.
                </div>
            </div>

            {message && (
                <div style={{
                    padding: '1rem',
                    borderRadius: 'var(--radius)',
                    background: message.type === 'success' ? 'rgba(16, 185, 129, 0.1)' : message.type === 'info' ? 'rgba(82, 126, 247, 0.1)' : 'rgba(239, 68, 68, 0.1)',
                    border: `1px solid ${message.type === 'success' ? 'rgba(16, 185, 129, 0.2)' : message.type === 'info' ? 'rgba(82, 126, 247, 0.2)' : 'rgba(239, 68, 68, 0.2)'}`,
                    color: message.type === 'success' ? 'var(--success)' : message.type === 'info' ? 'var(--primary)' : 'var(--danger)',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '0.75rem'
                }}>
                    {message.type === 'success' ? <CheckCircle size={20} /> : message.type === 'info' ? <Loader2 size={20} className="animate-spin" /> : <ShieldCheck size={20} />}
                    {message.text}
                </div>
            )}

            <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
                <button
                    type="button"
                    className="btn"
                    aria-pressed={credentialMode === 'existing'}
                    onClick={() => setCredentialMode('existing')}
                    style={modeButtonStyle(credentialMode === 'existing')}
                >
                    Use existing keys
                </button>
                <button
                    type="button"
                    className="btn"
                    aria-pressed={credentialMode === 'direct'}
                    onClick={() => setCredentialMode('direct')}
                    style={modeButtonStyle(credentialMode === 'direct')}
                >
                    Enter credentials
                </button>
            </div>

            <form onSubmit={createSession} style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '1rem', alignItems: 'end' }}>
                    <div className="form-group">
                        <label className="label">Name</label>
                        <input className="input" value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} placeholder="Staging login" />
                    </div>
                    <div className="form-group">
                        <label className="label">Base URL</label>
                        <input className="input" value={form.base_url} onChange={e => setForm({ ...form, base_url: e.target.value })} placeholder="https://app.example.com" />
                    </div>
                    <div className="form-group">
                        <label className="label">Login URL</label>
                        <input className="input" value={form.login_url} onChange={e => setForm({ ...form, login_url: e.target.value })} placeholder="https://app.example.com/login" />
                    </div>
                    {credentialMode === 'existing' ? (
                        <>
                            <div className="form-group">
                                <label className="label">Username Key</label>
                                <select className="input" value={form.username_key} onChange={e => setForm({ ...form, username_key: e.target.value })}>
                                    <option value="">Select key</option>
                                    {credentials.map(credential => <option key={credential.key} value={credential.key}>{credential.key} ({credential.source})</option>)}
                                </select>
                            </div>
                            <div className="form-group">
                                <label className="label">Password Key</label>
                                <select className="input" value={form.password_key} onChange={e => setForm({ ...form, password_key: e.target.value })}>
                                    <option value="">Select key</option>
                                    {credentials.map(credential => <option key={credential.key} value={credential.key}>{credential.key} ({credential.source})</option>)}
                                </select>
                            </div>
                        </>
                    ) : (
                        <>
                            <div className="form-group">
                                <label className="label">Username</label>
                                <input className="input" value={form.username_value} onChange={e => setForm({ ...form, username_value: e.target.value })} placeholder="user@example.com" autoComplete="username" />
                            </div>
                            <div className="form-group">
                                <label className="label">Password</label>
                                <input className="input" type="password" value={form.password_value} onChange={e => setForm({ ...form, password_value: e.target.value })} placeholder="Password" autoComplete="current-password" />
                            </div>
                            <div className="form-group">
                                <label className="label">Username Key</label>
                                <input className="input" value={form.direct_username_key} onChange={e => setForm({ ...form, direct_username_key: e.target.value })} placeholder="LOGIN_USERNAME" autoComplete="off" />
                            </div>
                            <div className="form-group">
                                <label className="label">Password Key</label>
                                <input className="input" value={form.direct_password_key} onChange={e => setForm({ ...form, direct_password_key: e.target.value })} placeholder="LOGIN_PASSWORD" autoComplete="off" />
                            </div>
                        </>
                    )}
                    <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', minHeight: 42 }}>
                        <input type="checkbox" checked={form.make_default} onChange={e => setForm({ ...form, make_default: e.target.checked })} />
                        <span style={{ fontSize: '0.875rem' }}>Default</span>
                    </label>
                    <button className="btn btn-primary" type="submit" disabled={saving || (credentialMode === 'existing' && !credentialKeys.length)} style={{ minHeight: 42, justifyContent: 'center' }}>
                        {saving ? <Loader2 size={18} className="animate-spin" /> : <Plus size={18} />}
                        {saving ? 'Creating session...' : 'Create'}
                    </button>
                </div>
                <details style={{ border: '1px solid var(--border)', borderRadius: 'var(--radius)', padding: '0.875rem 1rem', background: 'var(--surface)' }}>
                    <summary style={{ cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '0.5rem', fontWeight: 600 }}>
                        <SlidersHorizontal size={16} />
                        Advanced selectors
                    </summary>
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '1rem', marginTop: '1rem' }}>
                        <div className="form-group">
                            <label className="label">Username Selector</label>
                            <input className="input" value={form.username_selector} onChange={e => setForm({ ...form, username_selector: e.target.value })} placeholder="#email" autoComplete="off" />
                        </div>
                        <div className="form-group">
                            <label className="label">Password Selector</label>
                            <input className="input" value={form.password_selector} onChange={e => setForm({ ...form, password_selector: e.target.value })} placeholder="#password" autoComplete="off" />
                        </div>
                        <div className="form-group">
                            <label className="label">Username Continue Selector</label>
                            <input className="input" value={form.username_continue_selector} onChange={e => setForm({ ...form, username_continue_selector: e.target.value })} placeholder="button.next" autoComplete="off" />
                        </div>
                        <div className="form-group">
                            <label className="label">Submit Selector</label>
                            <input className="input" value={form.submit_selector} onChange={e => setForm({ ...form, submit_selector: e.target.value })} placeholder="button[type=submit]" autoComplete="off" />
                        </div>
                        <div className="form-group">
                            <label className="label">Success URL Pattern</label>
                            <input className="input" value={form.success_url_pattern} onChange={e => setForm({ ...form, success_url_pattern: e.target.value })} placeholder="/dashboard$" autoComplete="off" />
                        </div>
                    </div>
                </details>
            </form>

            <div style={{ border: '1px solid var(--border)', borderRadius: 'var(--radius)', overflow: 'hidden' }}>
                {sessions.length === 0 ? (
                    <div style={{ padding: '1.5rem', color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                        <Key size={20} />
                        No browser login sessions.
                    </div>
                ) : (
                    sessions.map(session => (
                        <div key={session.id} data-testid="browser-auth-session-row" style={{ padding: '1rem', borderBottom: '1px solid var(--border)', display: 'grid', gridTemplateColumns: '1fr auto', gap: '1rem', alignItems: 'center' }}>
                            <div style={{ minWidth: 0 }}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
                                    <strong>{session.name}</strong>
                                    {session.is_default && <span style={{ fontSize: '0.75rem', color: 'var(--primary)', display: 'inline-flex', alignItems: 'center', gap: 4 }}><Star size={14} /> Default</span>}
                                    <span style={{ fontSize: '0.75rem', color: session.status === 'active' ? 'var(--success)' : 'var(--warning)' }}>{session.status}</span>
                                </div>
                                <div style={{ fontSize: '0.875rem', color: 'var(--text-secondary)', marginTop: '0.25rem', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                                    {session.base_url} · {session.username_key} / {session.password_key}
                                </div>
                                {(session.username_selector || session.password_selector || session.success_url_pattern) && (
                                    <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', marginTop: '0.25rem', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                                        {session.username_selector || 'auto username'} · {session.password_selector || 'auto password'}{session.success_url_pattern ? ` · ${session.success_url_pattern}` : ''}
                                    </div>
                                )}
                                <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', marginTop: '0.25rem', display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
                                    <Clock size={14} /> Validated {formatTime(session.last_validated_at)}
                                </div>
                                {session.failure_reason && <div style={{ color: 'var(--danger)', fontSize: '0.8rem', marginTop: '0.35rem' }}>{session.failure_reason}</div>}
                                {session.capture_backend_version && (
                                    <div style={{ fontSize: '0.72rem', color: 'var(--text-secondary)', marginTop: '0.25rem' }}>
                                        Capture backend {session.capture_backend_version}
                                    </div>
                                )}
                            </div>
                            <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap', justifyContent: 'flex-end' }}>
                                <button className="btn btn-sm browser-auth-action browser-auth-action--validate" type="button" disabled={busyId === session.id} onClick={() => runSessionAction(session.id, 'validate')} title="Validate stored state" aria-label={`Validate ${session.name}`}>
                                    {busyId === session.id && busyAction === 'validate' ? <Loader2 size={16} className="animate-spin" /> : <ShieldCheck size={16} />}
                                    <span>Validate</span>
                                </button>
                                <button className="btn btn-sm browser-auth-action browser-auth-action--refresh" type="button" disabled={busyId === session.id} onClick={() => runSessionAction(session.id, 'refresh')} title="Refresh with AI browser capture" aria-label={`Refresh ${session.name}`}>
                                    {busyId === session.id && busyAction === 'refresh' ? <Loader2 size={16} className="animate-spin" /> : <RefreshCw size={16} />}
                                    <span>{busyId === session.id && busyAction === 'refresh' ? 'Refreshing' : 'Refresh'}</span>
                                </button>
                                <button className="btn btn-sm browser-auth-action browser-auth-action--default" type="button" disabled={busyId === session.id || session.is_default} onClick={() => runSessionAction(session.id, 'default')} title="Set default" aria-label={`Set ${session.name} as default`}>
                                    {busyId === session.id && busyAction === 'default' ? <Loader2 size={16} className="animate-spin" /> : <Star size={16} />}
                                    <span>Default</span>
                                </button>
                                <button className="btn btn-sm browser-auth-action browser-auth-action--revoke" type="button" disabled={busyId === session.id} onClick={() => runSessionAction(session.id, 'delete')} title="Revoke" aria-label={`Revoke ${session.name}`}>
                                    {busyId === session.id && busyAction === 'delete' ? <Loader2 size={16} className="animate-spin" /> : <Trash2 size={16} />}
                                    <span>Revoke</span>
                                </button>
                            </div>
                        </div>
                    ))
                )}
            </div>
        </div>
    );
}
