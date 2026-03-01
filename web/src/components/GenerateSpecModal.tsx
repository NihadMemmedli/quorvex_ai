'use client';
import { useState, useEffect } from 'react';
import { X, Sparkles, Loader2, CheckCircle, AlertCircle, ExternalLink, Eye, Edit3, Save, RefreshCw } from 'lucide-react';
import { useProject } from '@/contexts/ProjectContext';
import { API_BASE } from '@/lib/api';

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

export default function GenerateSpecModal({
    requirement,
    onClose,
    onSuccess,
    defaultUrl = ''
}: GenerateSpecModalProps) {
    const { currentProject } = useProject();

    // Form state
    const [targetUrl, setTargetUrl] = useState(defaultUrl);
    const [loginUrl, setLoginUrl] = useState('');
    const [useCredentials, setUseCredentials] = useState(false);
    const [usernameVar, setUsernameVar] = useState('LOGIN_USERNAME');
    const [passwordVar, setPasswordVar] = useState('LOGIN_PASSWORD');

    // Generation state
    const [status, setStatus] = useState<GenerationStatus>('idle');
    const [error, setError] = useState<string | null>(null);
    const [result, setResult] = useState<GenerationResult | null>(null);

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

    useEffect(() => {
        checkExistingSpec();
    }, [requirement.id]);

    const checkExistingSpec = async () => {
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
    };

    const handleGenerate = async (forceRegenerate = false) => {
        if (!targetUrl.trim()) {
            setError('Target URL is required');
            return;
        }

        setStatus('generating');
        setError(null);

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

            if (useCredentials) {
                requestBody.credentials = {
                    username_var: usernameVar,
                    password_var: passwordVar
                };
            }

            const res = await fetch(
                `${API_BASE}/requirements/${requirement.id}/generate-spec${projectParam}`,
                {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(requestBody)
                }
            );

            if (res.ok) {
                const data: GenerationResult = await res.json();
                setResult(data);
                setEditedContent(data.spec_content);
                setStatus('success');
                setShowPreview(true);

                if (onSuccess) {
                    onSuccess(data.spec_path, data.spec_name);
                }
            } else {
                const errData = await res.json();
                setError(errData.detail || 'Failed to generate spec');
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
            // Save the edited content to the spec file
            const res = await fetch(`${API_BASE}/specs`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    path: result.spec_path,
                    content: editedContent
                })
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

    return (
        <div
            className="modal-overlay"
            onClick={(e) => e.target === e.currentTarget && status !== 'generating' && onClose()}
        >
            <div
                className="modal-content"
                onClick={(e) => e.stopPropagation()}
                style={{
                    width: showPreview ? '800px' : '550px',
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
                        onClick={onClose}
                        disabled={status === 'generating'}
                        style={{
                            background: 'none',
                            border: 'none',
                            cursor: status === 'generating' ? 'not-allowed' : 'pointer',
                            padding: '0.5rem',
                            color: 'var(--text-secondary)',
                            opacity: status === 'generating' ? 0.5 : 1
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
                                onClick={onClose}
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

                            {/* Credentials Section */}
                            <div>
                                <label style={{
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: '0.5rem',
                                    cursor: 'pointer',
                                    fontWeight: 500
                                }}>
                                    <input
                                        type="checkbox"
                                        checked={useCredentials}
                                        onChange={(e) => setUseCredentials(e.target.checked)}
                                        disabled={status === 'generating'}
                                    />
                                    Use credentials from environment variables
                                </label>

                                {useCredentials && (
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
                                padding: '1.5rem',
                                background: 'rgba(59, 130, 246, 0.05)',
                                borderRadius: '8px',
                                textAlign: 'center'
                            }}>
                                <Loader2 size={32} color="var(--primary)" className="spinning" style={{ margin: '0 auto 1rem' }} />
                                <div style={{ fontWeight: 600, marginBottom: '0.5rem' }}>
                                    Generating spec...
                                </div>
                                <div style={{ fontSize: '0.9rem', color: 'var(--text-secondary)' }}>
                                    AI is exploring the application and creating test cases.
                                    This may take a few moments.
                                </div>
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
                                    onClick={onClose}
                                    className="btn btn-secondary"
                                >
                                    Cancel
                                </button>
                                <button
                                    onClick={() => handleGenerate(existingSpec?.has_spec || false)}
                                    className="btn btn-primary"
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
