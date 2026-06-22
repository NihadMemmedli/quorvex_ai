'use client';
import { useState, useEffect, useRef, useCallback } from 'react';
import Link from 'next/link';
import { X, Sparkles, Loader2, CheckCircle, AlertCircle, Edit3, Save, RefreshCw } from 'lucide-react';
import { useProject } from '@/contexts/ProjectContext';
import { API_BASE } from '@/lib/api';
import { useJobPoller } from '@/hooks/useJobPoller';
import { applyProjectDefaultUrl, getProjectDefaultUrl, trimUrlInput } from '@/lib/project-url';
import { LiveBrowserView } from '@/components/LiveBrowserView';
import { TestDataPicker } from '@/components/TestDataPicker';
import {
    BrowserAuthSession,
    browserAuthSessionLabel,
    fetchProjectBrowserAuthSessions,
    isBrowserAuthSessionSelectable,
} from '@/lib/browser-auth-sessions';

interface Requirement {
    id: number;
    req_code: string;
    title: string;
    description: string | null;
    category: string;
    priority: string;
    acceptance_criteria: string[];
    source_session_id: string | null;
}

interface GenerateSpecModalProps {
    requirement: Requirement;
    onClose: () => void;
    onSuccess?: (specPath: string, specName: string) => void;
    defaultUrl?: string;
}

type GenerationStatus = 'idle' | 'generating' | 'success' | 'error';
type AuthMode = 'none' | 'credentials' | 'session';
const LIVE_AGENT_STATUSES = new Set(['running', 'pending', 'queued', 'in_progress', 'waiting', 'paused']);

interface GenerationResult {
    status: string;
    spec_path: string;
    spec_name: string;
    spec_content: string;
    requirement_id: number;
    requirement_code: string;
    rtm_entry_id: number;
    generated_at: string;
    cached: boolean;
}

interface AgentArtifact {
    name: string;
    path: string;
    type: string;
    modified_at?: string | null;
}

interface AgentRun {
    id: string;
    agent_type: string;
    status: string;
    progress?: Record<string, any>;
    result?: Record<string, any> | null;
    artifacts?: AgentArtifact[];
    agent_task_id?: string | null;
}

function specPathToName(specPath: string | null | undefined): string | null {
    if (!specPath) return null;
    const normalized = specPath.replace(/\\/g, '/');
    const markerIndex = normalized.lastIndexOf('/specs/');
    if (markerIndex >= 0) return normalized.slice(markerIndex + '/specs/'.length);
    if (normalized.startsWith('specs/')) return normalized.slice('specs/'.length);
    return normalized.endsWith('.md') ? normalized : null;
}

export default function GenerateSpecModal({
    requirement,
    onClose,
    onSuccess,
    defaultUrl = ''
}: GenerateSpecModalProps) {
    const { currentProject } = useProject();
    const projectDefaultUrl = trimUrlInput(defaultUrl) || getProjectDefaultUrl(currentProject);
    const previousProjectDefaultUrlRef = useRef('');

    // Form state
    const [targetUrl, setTargetUrl] = useState(projectDefaultUrl);
    const [loginUrl, setLoginUrl] = useState('');
    const [authMode, setAuthMode] = useState<AuthMode>('none');
    const [usernameVar, setUsernameVar] = useState('LOGIN_USERNAME');
    const [passwordVar, setPasswordVar] = useState('LOGIN_PASSWORD');
    const [browserAuthSessions, setBrowserAuthSessions] = useState<BrowserAuthSession[]>([]);
    const [selectedBrowserAuthSessionId, setSelectedBrowserAuthSessionId] = useState('');
    const [loadingBrowserAuthSessions, setLoadingBrowserAuthSessions] = useState(false);
    const [browserAuthError, setBrowserAuthError] = useState<string | null>(null);
    const [selectedTestDataRefs, setSelectedTestDataRefs] = useState<string[]>([]);

    // Generation state
    const [status, setStatus] = useState<GenerationStatus>('idle');
    const [error, setError] = useState<string | null>(null);
    const [result, setResult] = useState<GenerationResult | null>(null);
    const [agentRunId, setAgentRunId] = useState<string | null>(null);
    const [agentRun, setAgentRun] = useState<AgentRun | null>(null);

    // Preview state
    const [showPreview, setShowPreview] = useState(false);
    const [editMode, setEditMode] = useState(false);
    const [editedContent, setEditedContent] = useState('');

    // Check if spec already exists
    const [existingSpec, setExistingSpec] = useState<{
        has_spec: boolean;
        spec_path?: string;
        spec_name?: string;
    } | null>(null);
    const [checkingStatus, setCheckingStatus] = useState(true);

    const showGenerationBrowser = status === 'generating' && Boolean(agentRunId);
    const generationRunActive = agentRun
        ? LIVE_AGENT_STATUSES.has(agentRun.status) && agentRun.status !== 'paused'
        : status === 'generating';

    const normalizeGenerationResult = (data: Record<string, unknown>): GenerationResult => ({
        status: String(data.status || 'generated'),
        spec_path: String(data.spec_path || ''),
        spec_name: String(data.spec_name || 'spec.md'),
        spec_content: String(data.spec_content || ''),
        requirement_id: Number(data.requirement_id || requirement.id),
        requirement_code: String(data.requirement_code || requirement.req_code),
        rtm_entry_id: Number(data.rtm_entry_id || 0),
        generated_at: String(data.generated_at || new Date().toISOString()),
        cached: Boolean(data.cached),
    });

    const formatApiError = (detail: unknown, fallback: string) => {
        if (!detail) return fallback;
        if (typeof detail === 'string') return detail;
        if (typeof detail === 'object' && detail !== null) {
            const maybeMessage = (detail as { message?: unknown }).message;
            if (typeof maybeMessage === 'string') return maybeMessage;
        }
        try {
            return JSON.stringify(detail);
        } catch {
            return fallback;
        }
    };

    const completeWithResult = (data: GenerationResult) => {
        setResult(data);
        setEditedContent(data.spec_content);
        setStatus('success');
        setShowPreview(true);
        setAgentRunId(null);
        setAgentRun(null);
        if (onSuccess) {
            onSuccess(data.spec_path, data.spec_name);
        }
    };

    const generateSpecPoller = useJobPoller({
        apiBase: API_BASE,
        urlPattern: '/requirements/generate-spec-jobs/{jobId}',
        interval: 3000,
        onComplete: (pollResult, pollStatus) => {
            const embeddedRun = pollStatus.agent_run as AgentRun | undefined;
            if (embeddedRun?.id) {
                setAgentRun(embeddedRun);
                setAgentRunId(embeddedRun.id);
            }
            if (pollResult) {
                completeWithResult(normalizeGenerationResult(pollResult));
            } else {
                setStatus('error');
                setError('Spec generation completed without a result.');
            }
        },
        onFailed: (message, pollStatus) => {
            const embeddedRun = pollStatus.agent_run as AgentRun | undefined;
            if (embeddedRun?.id) {
                setAgentRun(embeddedRun);
                setAgentRunId(embeddedRun.id);
            }
            const runError = embeddedRun?.result?.error || embeddedRun?.progress?.message;
            setError(String(message || runError || 'Spec generation failed.'));
            setStatus('error');
        },
    });
    const generateSpecPollerStatus = generateSpecPoller.status;
    const clearGenerateSpecPolling = generateSpecPoller.clear;
    const startGenerateSpecPolling = generateSpecPoller.startPolling;

    const checkExistingSpec = useCallback(async () => {
        setCheckingStatus(true);
        try {
            const projectParam = currentProject?.id
                ? `?project_id=${encodeURIComponent(currentProject.id)}`
                : '';

            const res = await fetch(
                `${API_BASE}/requirements/${requirement.id}/spec-status${projectParam}`
            );

            if (res.ok) {
                const data = await res.json();
                setExistingSpec(data);
            }
        } catch (err) {
            console.error('Failed to check spec status:', err);
        } finally {
            setCheckingStatus(false);
        }
    }, [currentProject?.id, requirement.id]);

    useEffect(() => {
        checkExistingSpec();
    }, [checkExistingSpec]);

    useEffect(() => {
        const nextAgentRunId = generateSpecPollerStatus?.agent_run_id;
        if (nextAgentRunId && nextAgentRunId !== agentRunId) {
            setAgentRunId(nextAgentRunId);
        }
        const nextAgentRun = generateSpecPollerStatus?.agent_run as AgentRun | undefined;
        if (nextAgentRun?.id) {
            setAgentRun(nextAgentRun);
        }
    }, [generateSpecPollerStatus, agentRunId]);

    useEffect(() => {
        return () => {
            clearGenerateSpecPolling();
        };
    }, [clearGenerateSpecPolling]);

    useEffect(() => {
        setTargetUrl(prev => applyProjectDefaultUrl(prev, projectDefaultUrl, previousProjectDefaultUrlRef.current));
        previousProjectDefaultUrlRef.current = projectDefaultUrl;
    }, [projectDefaultUrl]);

    useEffect(() => {
        if (!currentProject?.id) {
            setBrowserAuthSessions([]);
            setSelectedBrowserAuthSessionId('');
            return;
        }

        setLoadingBrowserAuthSessions(true);
        setBrowserAuthError(null);
        fetchProjectBrowserAuthSessions(currentProject.id)
            .then(sessions => {
                setBrowserAuthSessions(sessions);
                const selectable = sessions.filter(isBrowserAuthSessionSelectable);
                setSelectedBrowserAuthSessionId(prev => {
                    if (prev && selectable.some(session => session.id === prev)) return prev;
                    return selectable.find(session => session.is_default)?.id || selectable[0]?.id || '';
                });
            })
            .catch(err => {
                console.error('Failed to load browser auth sessions:', err);
                setBrowserAuthSessions([]);
                setSelectedBrowserAuthSessionId('');
                setBrowserAuthError('Browser login sessions could not be loaded.');
            })
            .finally(() => setLoadingBrowserAuthSessions(false));
    }, [currentProject?.id]);

    const addTestDataRef = (ref: string) => {
        const trimmed = ref.trim();
        if (!trimmed) return;
        setSelectedTestDataRefs(prev => prev.includes(trimmed) ? prev : [...prev, trimmed]);
    };

    const removeTestDataRef = (ref: string) => {
        setSelectedTestDataRefs(prev => prev.filter(item => item !== ref));
    };

    const handleGenerate = async (forceRegenerate = false) => {
        if (!targetUrl.trim()) {
            setError('Target URL is required');
            return;
        }

        if (authMode === 'session' && !selectedBrowserAuthSessionId) {
            setError('Select an active browser login session or choose another authentication option.');
            return;
        }

        setStatus('generating');
        setError(null);
        setResult(null);
        setShowPreview(false);
        setEditMode(false);
        setAgentRunId(null);
        setAgentRun(null);
        clearGenerateSpecPolling();

        try {
            const projectParam = currentProject?.id
                ? `?project_id=${encodeURIComponent(currentProject.id)}`
                : '';

            const requestBody: any = {
                target_url: targetUrl.trim(),
                force_regenerate: forceRegenerate
            };

            if (loginUrl.trim()) {
                requestBody.login_url = loginUrl.trim();
            }

            if (authMode === 'credentials') {
                requestBody.credentials = {
                    username_var: usernameVar,
                    password_var: passwordVar
                };
            }

            if (authMode === 'session' && selectedBrowserAuthSessionId) {
                requestBody.browser_auth_session_id = selectedBrowserAuthSessionId;
            }

            if (selectedTestDataRefs.length > 0) {
                requestBody.test_data_refs = selectedTestDataRefs;
            }

            const res = await fetch(
                `${API_BASE}/requirements/${requirement.id}/generate-spec-jobs${projectParam}`,
                {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(requestBody)
                }
            );

            if (res.ok) {
                const data = await res.json();
                if (data.status === 'cached' && data.result) {
                    completeWithResult(normalizeGenerationResult(data.result));
                    return;
                }
                if (data.status === 'running' && data.job_id) {
                    if (data.agent_run_id) {
                        setAgentRunId(data.agent_run_id);
                    }
                    startGenerateSpecPolling(data.job_id);
                    return;
                }
                setError(data.message || 'Unexpected response from spec generation.');
                setStatus('error');
            } else {
                const errData = await res.json().catch(() => ({}));
                setError(formatApiError(errData.detail, 'Failed to generate spec'));
                setStatus('error');
            }
        } catch (err) {
            setError('Network error. Please try again.');
            setStatus('error');
        }
    };

    const handleSaveEdits = async () => {
        if (!result) return;

        try {
            const specName = specPathToName(result.spec_path) || result.spec_name;
            const encodedSpecName = specName.split('/').map(encodeURIComponent).join('/');
            const projectParam = currentProject?.id
                ? `?project_id=${encodeURIComponent(currentProject.id)}`
                : '';
            const res = await fetch(`${API_BASE}/specs/${encodedSpecName}${projectParam}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ content: editedContent })
            });

            if (res.ok) {
                setEditMode(false);
                setResult({ ...result, spec_content: editedContent });
            } else {
                alert('Failed to save changes');
            }
        } catch (err) {
            alert('Failed to save changes');
        }
    };

    const handleClose = () => {
        clearGenerateSpecPolling();
        onClose();
    };

    return (
        <div
            className="modal-overlay"
            onClick={(e) => e.target === e.currentTarget && handleClose()}
        >
            <div
                className="modal-content"
                onClick={(e) => e.stopPropagation()}
                style={{
                    width: showPreview ? '800px' : showGenerationBrowser ? '1040px' : '550px',
                    maxWidth: '95vw',
                    maxHeight: '90vh',
                    overflow: 'auto',
                    transition: 'width 0.3s ease'
                }}
            >
                {/* Header */}
                <div style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'flex-start',
                    marginBottom: '1.5rem'
                }}>
                    <div>
                        <h2 style={{
                            display: 'flex',
                            alignItems: 'center',
                            gap: '0.75rem',
                            marginBottom: '0.5rem'
                        }}>
                            <Sparkles size={24} color="var(--primary)" />
                            Generate Test Spec
                        </h2>
                        <div style={{ fontSize: '0.9rem', color: 'var(--text-secondary)' }}>
                            <span style={{
                                fontWeight: 600,
                                color: 'var(--primary)',
                                marginRight: '0.5rem'
                            }}>
                                {requirement.req_code}
                            </span>
                            {requirement.title}
                        </div>
                    </div>
                    <button
                        onClick={handleClose}
                        style={{
                            background: 'none',
                            border: 'none',
                            cursor: 'pointer',
                            padding: '0.5rem',
                            color: 'var(--text-secondary)',
                        }}
                    >
                        <X size={20} />
                    </button>
                </div>

                {/* Existing Spec Warning */}
                {!checkingStatus && existingSpec?.has_spec && status === 'idle' && (
                    <div style={{
                        padding: '1rem',
                        background: 'rgba(245, 158, 11, 0.1)',
                        border: '1px solid rgba(245, 158, 11, 0.3)',
                        borderRadius: '8px',
                        marginBottom: '1.5rem',
                        display: 'flex',
                        alignItems: 'flex-start',
                        gap: '0.75rem'
                    }}>
                        <AlertCircle size={20} color="#f59e0b" style={{ flexShrink: 0, marginTop: '2px' }} />
                        <div>
                            <div style={{ fontWeight: 600, marginBottom: '0.25rem' }}>
                                Spec already exists
                            </div>
                            <div style={{ fontSize: '0.9rem', color: 'var(--text-secondary)' }}>
                                A spec ({existingSpec.spec_name}) is already linked to this requirement.
                                Generating again will overwrite the existing spec.
                            </div>
                        </div>
                    </div>
                )}

                {/* Success State with Preview */}
                {status === 'success' && result && showPreview ? (
                    <div>
                        {/* Success Banner */}
                        <div style={{
                            padding: '1rem',
                            background: result.cached ? 'rgba(59, 130, 246, 0.1)' : 'rgba(16, 185, 129, 0.1)',
                            border: `1px solid ${result.cached ? 'rgba(59, 130, 246, 0.3)' : 'rgba(16, 185, 129, 0.3)'}`,
                            borderRadius: '8px',
                            marginBottom: '1rem',
                            display: 'flex',
                            alignItems: 'center',
                            gap: '0.75rem'
                        }}>
                            <CheckCircle size={20} color={result.cached ? '#3b82f6' : '#10b981'} />
                            <div>
                                <div style={{ fontWeight: 600 }}>
                                    {result.cached ? 'Using existing spec' : 'Spec generated successfully'}
                                </div>
                                <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
                                    {result.spec_name}
                                </div>
                            </div>
                        </div>

                        {/* Preview Toggle */}
                        <div style={{
                            display: 'flex',
                            justifyContent: 'space-between',
                            alignItems: 'center',
                            marginBottom: '0.75rem'
                        }}>
                            <div style={{ fontWeight: 600 }}>Spec Content</div>
                            <div style={{ display: 'flex', gap: '0.5rem' }}>
                                {editMode ? (
                                    <button
                                        onClick={handleSaveEdits}
                                        className="btn btn-sm btn-primary"
                                        style={{ display: 'flex', alignItems: 'center', gap: '0.375rem' }}
                                    >
                                        <Save size={14} /> Save
                                    </button>
                                ) : (
                                    <button
                                        onClick={() => setEditMode(true)}
                                        className="btn btn-sm btn-secondary"
                                        style={{ display: 'flex', alignItems: 'center', gap: '0.375rem' }}
                                    >
                                        <Edit3 size={14} /> Edit
                                    </button>
                                )}
                                <button
                                    onClick={() => handleGenerate(true)}
                                    className="btn btn-sm btn-secondary"
                                    style={{ display: 'flex', alignItems: 'center', gap: '0.375rem' }}
                                >
                                    <RefreshCw size={14} /> Regenerate
                                </button>
                            </div>
                        </div>

                        {/* Content Preview/Editor */}
                        <div style={{
                            background: 'var(--code-bg)',
                            borderRadius: '8px',
                            border: '1px solid var(--border)',
                            maxHeight: '400px',
                            overflow: 'auto'
                        }}>
                            {editMode ? (
                                <textarea
                                    value={editedContent}
                                    onChange={(e) => setEditedContent(e.target.value)}
                                    style={{
                                        width: '100%',
                                        minHeight: '400px',
                                        padding: '1rem',
                                        background: 'transparent',
                                        border: 'none',
                                        color: 'var(--text)',
                                        fontFamily: 'monospace',
                                        fontSize: '0.85rem',
                                        lineHeight: '1.6',
                                        resize: 'none',
                                        outline: 'none'
                                    }}
                                />
                            ) : (
                                <pre style={{
                                    padding: '1rem',
                                    margin: 0,
                                    fontFamily: 'monospace',
                                    fontSize: '0.85rem',
                                    lineHeight: '1.6',
                                    whiteSpace: 'pre-wrap',
                                    wordBreak: 'break-word'
                                }}>
                                    {result.spec_content}
                                </pre>
                            )}
                        </div>

                        {/* Actions */}
                        <div style={{
                            display: 'flex',
                            justifyContent: 'flex-end',
                            gap: '0.75rem',
                            marginTop: '1.5rem'
                        }}>
                            <button
                                onClick={handleClose}
                                className="btn btn-primary"
                            >
                                Done
                            </button>
                        </div>
                    </div>
                ) : (
                    <>
                        {/* Form */}
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
                            {/* Target URL */}
                            <div>
                                <label style={{
                                    display: 'block',
                                    marginBottom: '0.375rem',
                                    fontWeight: 500
                                }}>
                                    Target URL <span style={{ color: '#ef4444' }}>*</span>
                                </label>
                                <input
                                    type="url"
                                    className="input"
                                    value={targetUrl}
                                    onChange={(e) => setTargetUrl(e.target.value)}
                                    placeholder="https://app.example.com/feature"
                                    disabled={status === 'generating'}
                                    style={{ width: '100%' }}
                                />
                                <p style={{
                                    marginTop: '0.375rem',
                                    fontSize: '0.8rem',
                                    color: 'var(--text-secondary)'
                                }}>
                                    URL of the page/feature to test
                                </p>
                            </div>

                            {/* Login URL */}
                            <div>
                                <label style={{
                                    display: 'block',
                                    marginBottom: '0.375rem',
                                    fontWeight: 500
                                }}>
                                    Login URL (optional)
                                </label>
                                <input
                                    type="url"
                                    className="input"
                                    value={loginUrl}
                                    onChange={(e) => setLoginUrl(e.target.value)}
                                    placeholder="https://app.example.com/login"
                                    disabled={status === 'generating'}
                                    style={{ width: '100%' }}
                                />
                                <p style={{
                                    marginTop: '0.375rem',
                                    fontSize: '0.8rem',
                                    color: 'var(--text-secondary)'
                                }}>
                                    If authentication is required, provide the login page URL
                                </p>
                            </div>

                            {/* Authentication Section */}
                            <div>
                                <div style={{
                                    display: 'flex',
                                    justifyContent: 'space-between',
                                    alignItems: 'center',
                                    gap: '1rem',
                                    marginBottom: '0.5rem'
                                }}>
                                    <label style={{ fontWeight: 600 }}>Authentication</label>
                                    <Link href="/settings" style={{ color: 'var(--primary)', fontSize: '0.8rem', fontWeight: 600 }}>
                                        Settings
                                    </Link>
                                </div>
                                <div style={{ display: 'grid', gap: '0.5rem' }}>
                                    {[
                                        { value: 'none', label: 'No auth' },
                                        { value: 'credentials', label: 'Environment credentials' },
                                        { value: 'session', label: 'Browser login session' },
                                    ].map(option => (
                                        <label
                                            key={option.value}
                                            style={{
                                                display: 'flex',
                                                alignItems: 'center',
                                                gap: '0.5rem',
                                                cursor: status === 'generating' ? 'not-allowed' : 'pointer',
                                                fontSize: '0.9rem'
                                            }}
                                        >
                                            <input
                                                type="radio"
                                                name="generate-spec-auth-mode"
                                                value={option.value}
                                                checked={authMode === option.value}
                                                onChange={() => setAuthMode(option.value as AuthMode)}
                                                disabled={status === 'generating'}
                                            />
                                            {option.label}
                                        </label>
                                    ))}
                                </div>

                                {authMode === 'credentials' && (
                                    <div style={{
                                        marginTop: '0.75rem',
                                        padding: '1rem',
                                        background: 'var(--surface-hover)',
                                        borderRadius: '8px',
                                        display: 'flex',
                                        gap: '1rem'
                                    }}>
                                        <div style={{ flex: 1 }}>
                                            <label style={{
                                                display: 'block',
                                                marginBottom: '0.25rem',
                                                fontSize: '0.85rem'
                                            }}>
                                                Username Variable
                                            </label>
                                            <input
                                                type="text"
                                                className="input"
                                                value={usernameVar}
                                                onChange={(e) => setUsernameVar(e.target.value)}
                                                placeholder="LOGIN_USERNAME"
                                                disabled={status === 'generating'}
                                                style={{ width: '100%' }}
                                            />
                                        </div>
                                        <div style={{ flex: 1 }}>
                                            <label style={{
                                                display: 'block',
                                                marginBottom: '0.25rem',
                                                fontSize: '0.85rem'
                                            }}>
                                                Password Variable
                                            </label>
                                            <input
                                                type="text"
                                                className="input"
                                                value={passwordVar}
                                                onChange={(e) => setPasswordVar(e.target.value)}
                                                placeholder="LOGIN_PASSWORD"
                                                disabled={status === 'generating'}
                                                style={{ width: '100%' }}
                                            />
                                        </div>
                                    </div>
                                )}

                                {authMode === 'session' && (
                                    <div style={{
                                        marginTop: '0.75rem',
                                        padding: '1rem',
                                        background: 'var(--surface-hover)',
                                        borderRadius: '8px',
                                        display: 'grid',
                                        gap: '0.75rem'
                                    }}>
                                        {loadingBrowserAuthSessions ? (
                                            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', color: 'var(--text-secondary)', fontSize: '0.9rem' }}>
                                                <Loader2 size={16} className="spinning" /> Loading browser login sessions...
                                            </div>
                                        ) : browserAuthError ? (
                                            <div style={{ color: '#ef4444', fontSize: '0.9rem' }}>{browserAuthError}</div>
                                        ) : browserAuthSessions.some(isBrowserAuthSessionSelectable) ? (
                                            <>
                                                <select
                                                    className="input"
                                                    value={selectedBrowserAuthSessionId}
                                                    onChange={(event) => setSelectedBrowserAuthSessionId(event.target.value)}
                                                    disabled={status === 'generating'}
                                                    style={{ width: '100%' }}
                                                >
                                                    {browserAuthSessions.map(session => (
                                                        <option
                                                            key={session.id}
                                                            value={session.id}
                                                            disabled={!isBrowserAuthSessionSelectable(session)}
                                                        >
                                                            {browserAuthSessionLabel(session)}
                                                        </option>
                                                    ))}
                                                </select>
                                                <p style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', margin: 0 }}>
                                                    The planner will treat this saved session as already authenticated.
                                                </p>
                                            </>
                                        ) : (
                                            <div style={{ fontSize: '0.9rem', color: 'var(--text-secondary)' }}>
                                                No active browser login sessions are saved for this project.{' '}
                                                <Link href="/settings" style={{ color: 'var(--primary)', fontWeight: 600 }}>
                                                    Add one in Settings
                                                </Link>
                                                .
                                            </div>
                                        )}
                                    </div>
                                )}
                            </div>

                            {/* Project Test Data */}
                            <div>
                                <div style={{
                                    display: 'flex',
                                    justifyContent: 'space-between',
                                    alignItems: 'center',
                                    gap: '1rem',
                                    marginBottom: '0.5rem'
                                }}>
                                    <label style={{ fontWeight: 600 }}>Project Test Data</label>
                                    <Link href="/test-data" style={{ color: 'var(--primary)', fontSize: '0.8rem', fontWeight: 600 }}>
                                        Manage Test Data
                                    </Link>
                                </div>
                                <TestDataPicker
                                    projectId={currentProject?.id}
                                    mode="ref"
                                    compact
                                    insertLabel="Add"
                                    onInsert={addTestDataRef}
                                />
                                {selectedTestDataRefs.length > 0 ? (
                                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem', marginTop: '0.75rem' }}>
                                        {selectedTestDataRefs.map(ref => (
                                            <span
                                                key={ref}
                                                style={{
                                                    display: 'inline-flex',
                                                    alignItems: 'center',
                                                    gap: '0.35rem',
                                                    border: '1px solid var(--border)',
                                                    borderRadius: '999px',
                                                    padding: '0.25rem 0.55rem',
                                                    fontSize: '0.8rem',
                                                    background: 'var(--surface-hover)'
                                                }}
                                            >
                                                {ref}
                                                <button
                                                    type="button"
                                                    aria-label={`Remove ${ref}`}
                                                    onClick={() => removeTestDataRef(ref)}
                                                    disabled={status === 'generating'}
                                                    style={{
                                                        border: 'none',
                                                        background: 'transparent',
                                                        color: 'var(--text-secondary)',
                                                        cursor: status === 'generating' ? 'not-allowed' : 'pointer',
                                                        padding: 0,
                                                        display: 'inline-flex'
                                                    }}
                                                >
                                                    <X size={13} />
                                                </button>
                                            </span>
                                        ))}
                                    </div>
                                ) : (
                                    <p style={{
                                        marginTop: '0.5rem',
                                        fontSize: '0.8rem',
                                        color: 'var(--text-secondary)'
                                    }}>
                                        Optional project test data refs will be resolved by the backend for the generated spec.
                                    </p>
                                )}
                            </div>
                        </div>

                        {/* Error Display */}
                        {error && (
                            <div style={{
                                marginTop: '1rem',
                                padding: '1rem',
                                background: 'rgba(239, 68, 68, 0.1)',
                                border: '1px solid rgba(239, 68, 68, 0.3)',
                                borderRadius: '8px',
                                display: 'flex',
                                alignItems: 'flex-start',
                                gap: '0.75rem'
                            }}>
                                <AlertCircle size={20} color="#ef4444" style={{ flexShrink: 0, marginTop: '2px' }} />
                                <div style={{ fontSize: '0.9rem', color: '#ef4444' }}>{error}</div>
                            </div>
                        )}

                        {/* Generating State */}
                        {status === 'generating' && (
                            <div style={{
                                marginTop: '1.5rem',
                                padding: showGenerationBrowser ? '1rem' : '1.5rem',
                                background: showGenerationBrowser ? 'var(--surface)' : 'rgba(59, 130, 246, 0.05)',
                                border: showGenerationBrowser ? '1px solid var(--border)' : 'none',
                                borderRadius: '8px',
                                textAlign: showGenerationBrowser ? 'left' : 'center'
                            }}>
                                {showGenerationBrowser && agentRunId ? (
                                    <div style={{ display: 'grid', gap: '0.85rem' }}>
                                        <LiveBrowserView
                                            runId={agentRunId}
                                            isActive={generationRunActive}
                                            showHeader
                                            artifacts={agentRun?.artifacts || []}
                                            statusMessage={(agentRun?.progress?.message as string | undefined) || generateSpecPoller.status?.message}
                                            liveViewAvailable={Boolean(agentRun?.progress?.live_view_available ?? true)}
                                            runtimeMessage={agentRun?.progress?.runtime_message as string | undefined}
                                            vncUrl={agentRun?.progress?.vnc_url as string | undefined}
                                            browserActivitySeen={Boolean(agentRun?.progress?.browser_tool_calls)}
                                            browserActive={agentRun?.progress?.phase === 'tool_use'}
                                            browserLastTool={agentRun?.progress?.last_tool as string | undefined}
                                            suspectedBrowserDialogBlock={agentRun?.progress?.suspected_browser_dialog_block === true}
                                        />
                                        <div style={{
                                            display: 'flex',
                                            alignItems: 'center',
                                            gap: '0.5rem',
                                            fontSize: '0.9rem',
                                            color: 'var(--text-secondary)'
                                        }}>
                                            <Loader2 size={16} color="var(--primary)" className="spinning" />
                                            <span>{(agentRun?.progress?.message as string | undefined) || generateSpecPoller.status?.message || 'Generating spec...'}</span>
                                        </div>
                                    </div>
                                ) : (
                                    <>
                                        <Loader2 size={32} color="var(--primary)" className="spinning" style={{ margin: '0 auto 1rem' }} />
                                        <div style={{ fontWeight: 600, marginBottom: '0.5rem' }}>
                                            Generating spec...
                                        </div>
                                        <div style={{ fontSize: '0.9rem', color: 'var(--text-secondary)' }}>
                                            AI is exploring the application and creating test cases.
                                            This may take a few moments.
                                        </div>
                                    </>
                                )}
                            </div>
                        )}

                        {/* Actions */}
                        {status !== 'generating' && (
                            <div style={{
                                display: 'flex',
                                justifyContent: 'flex-end',
                                gap: '0.75rem',
                                marginTop: '1.5rem',
                                paddingTop: '1rem',
                                borderTop: '1px solid var(--border)'
                            }}>
                                <button
                                    onClick={handleClose}
                                    className="btn btn-secondary"
                                >
                                    Cancel
                                </button>
                                <button
                                    onClick={() => handleGenerate(existingSpec?.has_spec || false)}
                                    className="btn btn-primary"
                                    disabled={authMode === 'session' && !selectedBrowserAuthSessionId}
                                    style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}
                                >
                                    <Sparkles size={18} />
                                    {existingSpec?.has_spec ? 'Regenerate Spec' : 'Generate Spec'}
                                </button>
                            </div>
                        )}
                    </>
                )}
            </div>

            <style jsx>{`
                @keyframes spin {
                    from { transform: rotate(0deg); }
                    to { transform: rotate(360deg); }
                }
                :global(.spinning) {
                    animation: spin 1s linear infinite;
                }
            `}</style>
        </div>
    );
}
