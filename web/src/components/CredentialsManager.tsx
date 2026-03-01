'use client';

import { useState, useEffect, useCallback } from 'react';
import { Key, Eye, EyeOff, Plus, Trash2, AlertCircle, CheckCircle, FileCode, HardDrive } from 'lucide-react';
import { API_BASE } from '@/lib/api';

interface Credential {
    key: string;
    masked_value: string;
    source: 'project' | 'env';
}

interface CredentialsManagerProps {
    projectId: string;
    projectName: string;
}

export function CredentialsManager({ projectId, projectName }: CredentialsManagerProps) {
    const [credentials, setCredentials] = useState<Credential[]>([]);
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [success, setSuccess] = useState<string | null>(null);

    // Form state
    const [newKey, setNewKey] = useState('');
    const [newValue, setNewValue] = useState('');
    const [showNewValue, setShowNewValue] = useState(false);

    // Deleting state
    const [deletingKey, setDeletingKey] = useState<string | null>(null);

    const fetchCredentials = useCallback(async () => {
        try {
            setLoading(true);
            const res = await fetch(`${API_BASE}/projects/${projectId}/credentials`);
            if (!res.ok) throw new Error('Failed to fetch credentials');
            const data = await res.json();
            setCredentials(data.credentials || []);
        } catch (err: any) {
            setError(err.message);
        } finally {
            setLoading(false);
        }
    }, [projectId]);

    useEffect(() => {
        fetchCredentials();
    }, [fetchCredentials]);

    const handleAddCredential = async (e: React.FormEvent) => {
        e.preventDefault();

        if (!newKey.trim() || !newValue.trim()) {
            setError('Both key and value are required');
            return;
        }

        // Validate key format
        if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(newKey)) {
            setError('Key must start with a letter or underscore and contain only alphanumeric characters and underscores');
            return;
        }

        try {
            setSaving(true);
            setError(null);

            const res = await fetch(`${API_BASE}/projects/${projectId}/credentials`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ key: newKey.toUpperCase(), value: newValue })
            });

            if (!res.ok) {
                const data = await res.json();
                throw new Error(data.detail || 'Failed to save credential');
            }

            setSuccess(`Credential "${newKey.toUpperCase()}" saved successfully`);
            setNewKey('');
            setNewValue('');
            setShowNewValue(false);
            await fetchCredentials();

            setTimeout(() => setSuccess(null), 3000);
        } catch (err: any) {
            setError(err.message);
        } finally {
            setSaving(false);
        }
    };

    const handleDeleteCredential = async (key: string) => {
        try {
            setDeletingKey(key);
            setError(null);

            const res = await fetch(`${API_BASE}/projects/${projectId}/credentials/${key}`, {
                method: 'DELETE'
            });

            if (!res.ok) {
                const data = await res.json();
                throw new Error(data.detail || 'Failed to delete credential');
            }

            setSuccess(`Credential "${key}" removed`);
            await fetchCredentials();

            setTimeout(() => setSuccess(null), 3000);
        } catch (err: any) {
            setError(err.message);
        } finally {
            setDeletingKey(null);
        }
    };

    // Common credential suggestions
    const suggestions = [
        'LOGIN_USERNAME',
        'LOGIN_PASSWORD',
        'ADMIN_USERNAME',
        'ADMIN_PASSWORD',
        'TEST_EMAIL',
        'API_TOKEN'
    ];

    const unusedSuggestions = suggestions.filter(
        s => !credentials.some(c => c.key === s)
    );

    if (loading) {
        return (
            <div style={{ display: 'flex', justifyContent: 'center', padding: '2rem' }}>
                <div className="loading-spinner"></div>
            </div>
        );
    }

    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
            {/* Header with context */}
            <div style={{
                display: 'flex',
                alignItems: 'center',
                gap: '0.75rem',
                padding: '1rem',
                background: 'var(--surface-hover)',
                borderRadius: 'var(--radius)',
                border: '1px solid var(--border)'
            }}>
                <Key size={20} color="var(--primary)" />
                <div>
                    <div style={{ fontWeight: 600 }}>Test Credentials for {projectName}</div>
                    <div style={{ fontSize: '0.875rem', color: 'var(--text-secondary)' }}>
                        Use <code style={{ background: 'var(--surface)', padding: '0.125rem 0.375rem', borderRadius: 4 }}>{'{{CREDENTIAL_NAME}}'}</code> in your spec files
                    </div>
                </div>
            </div>

            {/* Messages */}
            {error && (
                <div style={{
                    padding: '1rem',
                    borderRadius: 'var(--radius)',
                    background: 'rgba(239, 68, 68, 0.1)',
                    border: '1px solid rgba(239, 68, 68, 0.2)',
                    color: 'var(--danger)',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '0.75rem'
                }}>
                    <AlertCircle size={20} />
                    {error}
                </div>
            )}

            {success && (
                <div style={{
                    padding: '1rem',
                    borderRadius: 'var(--radius)',
                    background: 'rgba(16, 185, 129, 0.1)',
                    border: '1px solid rgba(16, 185, 129, 0.2)',
                    color: 'var(--success)',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '0.75rem'
                }}>
                    <CheckCircle size={20} />
                    {success}
                </div>
            )}

            {/* Credentials Table */}
            {credentials.length > 0 ? (
                <div style={{
                    border: '1px solid var(--border)',
                    borderRadius: 'var(--radius)',
                    overflow: 'hidden'
                }}>
                    <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                        <thead>
                            <tr style={{ background: 'var(--surface-hover)' }}>
                                <th style={{
                                    padding: '0.75rem 1rem',
                                    textAlign: 'left',
                                    fontWeight: 600,
                                    fontSize: '0.875rem',
                                    color: 'var(--text-secondary)',
                                    borderBottom: '1px solid var(--border)'
                                }}>
                                    Key
                                </th>
                                <th style={{
                                    padding: '0.75rem 1rem',
                                    textAlign: 'left',
                                    fontWeight: 600,
                                    fontSize: '0.875rem',
                                    color: 'var(--text-secondary)',
                                    borderBottom: '1px solid var(--border)'
                                }}>
                                    Value
                                </th>
                                <th style={{
                                    padding: '0.75rem 1rem',
                                    textAlign: 'left',
                                    fontWeight: 600,
                                    fontSize: '0.875rem',
                                    color: 'var(--text-secondary)',
                                    borderBottom: '1px solid var(--border)'
                                }}>
                                    Source
                                </th>
                                <th style={{
                                    padding: '0.75rem 1rem',
                                    textAlign: 'center',
                                    fontWeight: 600,
                                    fontSize: '0.875rem',
                                    color: 'var(--text-secondary)',
                                    borderBottom: '1px solid var(--border)',
                                    width: 80
                                }}>
                                    Actions
                                </th>
                            </tr>
                        </thead>
                        <tbody>
                            {credentials.map((cred, index) => (
                                <tr
                                    key={cred.key}
                                    style={{
                                        background: index % 2 === 0 ? 'transparent' : 'var(--surface)',
                                        transition: 'background 0.15s'
                                    }}
                                >
                                    <td style={{
                                        padding: '0.75rem 1rem',
                                        fontFamily: 'monospace',
                                        fontSize: '0.9rem',
                                        fontWeight: 500
                                    }}>
                                        {cred.key}
                                    </td>
                                    <td style={{
                                        padding: '0.75rem 1rem',
                                        fontFamily: 'monospace',
                                        fontSize: '0.9rem',
                                        color: 'var(--text-secondary)'
                                    }}>
                                        {cred.masked_value || '(empty)'}
                                    </td>
                                    <td style={{ padding: '0.75rem 1rem' }}>
                                        <span style={{
                                            display: 'inline-flex',
                                            alignItems: 'center',
                                            gap: '0.375rem',
                                            padding: '0.25rem 0.5rem',
                                            borderRadius: 4,
                                            fontSize: '0.75rem',
                                            fontWeight: 500,
                                            background: cred.source === 'project'
                                                ? 'rgba(99, 102, 241, 0.1)'
                                                : 'rgba(245, 158, 11, 0.1)',
                                            color: cred.source === 'project'
                                                ? 'rgb(99, 102, 241)'
                                                : 'rgb(245, 158, 11)'
                                        }}>
                                            {cred.source === 'project' ? (
                                                <><HardDrive size={12} /> Project</>
                                            ) : (
                                                <><FileCode size={12} /> .env</>
                                            )}
                                        </span>
                                    </td>
                                    <td style={{ padding: '0.75rem 1rem', textAlign: 'center' }}>
                                        {cred.source === 'project' ? (
                                            <button
                                                onClick={() => handleDeleteCredential(cred.key)}
                                                disabled={deletingKey === cred.key}
                                                style={{
                                                    padding: '0.375rem',
                                                    background: 'transparent',
                                                    border: 'none',
                                                    borderRadius: 4,
                                                    cursor: deletingKey === cred.key ? 'not-allowed' : 'pointer',
                                                    color: 'var(--danger)',
                                                    opacity: deletingKey === cred.key ? 0.5 : 1,
                                                    transition: 'background 0.15s'
                                                }}
                                                onMouseEnter={(e) => {
                                                    if (deletingKey !== cred.key) {
                                                        e.currentTarget.style.background = 'rgba(239, 68, 68, 0.1)';
                                                    }
                                                }}
                                                onMouseLeave={(e) => {
                                                    e.currentTarget.style.background = 'transparent';
                                                }}
                                                title="Delete credential"
                                            >
                                                <Trash2 size={16} />
                                            </button>
                                        ) : (
                                            <span style={{
                                                fontSize: '0.75rem',
                                                color: 'var(--text-secondary)'
                                            }}>
                                                -
                                            </span>
                                        )}
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            ) : (
                <div style={{
                    padding: '2rem',
                    textAlign: 'center',
                    color: 'var(--text-secondary)',
                    background: 'var(--surface)',
                    borderRadius: 'var(--radius)',
                    border: '1px solid var(--border)'
                }}>
                    <Key size={32} style={{ marginBottom: '0.75rem', opacity: 0.5 }} />
                    <div style={{ fontWeight: 500, marginBottom: '0.25rem' }}>No credentials configured</div>
                    <div style={{ fontSize: '0.875rem' }}>Add credentials below to use in your test specs</div>
                </div>
            )}

            {/* Add Credential Form */}
            <form onSubmit={handleAddCredential} style={{
                padding: '1.5rem',
                background: 'var(--surface)',
                borderRadius: 'var(--radius)',
                border: '1px solid var(--border)'
            }}>
                <div style={{ marginBottom: '1rem', fontWeight: 600 }}>
                    Add Credential
                </div>

                <div style={{ display: 'flex', gap: '1rem', flexWrap: 'wrap' }}>
                    {/* Key input */}
                    <div style={{ flex: '1 1 200px' }}>
                        <label style={{
                            display: 'block',
                            fontSize: '0.875rem',
                            fontWeight: 500,
                            marginBottom: '0.375rem',
                            color: 'var(--text-secondary)'
                        }}>
                            Credential Key
                        </label>
                        <input
                            type="text"
                            value={newKey}
                            onChange={(e) => setNewKey(e.target.value.toUpperCase())}
                            placeholder="LOGIN_PASSWORD"
                            className="input"
                            style={{
                                width: '100%',
                                fontFamily: 'monospace',
                                textTransform: 'uppercase'
                            }}
                        />
                    </div>

                    {/* Value input */}
                    <div style={{ flex: '2 1 300px' }}>
                        <label style={{
                            display: 'block',
                            fontSize: '0.875rem',
                            fontWeight: 500,
                            marginBottom: '0.375rem',
                            color: 'var(--text-secondary)'
                        }}>
                            Value
                        </label>
                        <div style={{ position: 'relative' }}>
                            <input
                                type={showNewValue ? 'text' : 'password'}
                                value={newValue}
                                onChange={(e) => setNewValue(e.target.value)}
                                placeholder="Enter credential value"
                                className="input"
                                style={{
                                    width: '100%',
                                    paddingRight: '2.5rem'
                                }}
                            />
                            <button
                                type="button"
                                onClick={() => setShowNewValue(!showNewValue)}
                                style={{
                                    position: 'absolute',
                                    right: '0.5rem',
                                    top: '50%',
                                    transform: 'translateY(-50%)',
                                    background: 'transparent',
                                    border: 'none',
                                    padding: '0.25rem',
                                    cursor: 'pointer',
                                    color: 'var(--text-secondary)'
                                }}
                                title={showNewValue ? 'Hide value' : 'Show value'}
                            >
                                {showNewValue ? <EyeOff size={18} /> : <Eye size={18} />}
                            </button>
                        </div>
                    </div>

                    {/* Submit button */}
                    <div style={{ flex: '0 0 auto', display: 'flex', alignItems: 'flex-end' }}>
                        <button
                            type="submit"
                            className="btn btn-primary"
                            disabled={saving || !newKey.trim() || !newValue.trim()}
                            style={{
                                minWidth: '120px',
                                justifyContent: 'center',
                                opacity: saving ? 0.7 : 1
                            }}
                        >
                            {saving ? 'Saving...' : (
                                <>
                                    <Plus size={16} />
                                    Add
                                </>
                            )}
                        </button>
                    </div>
                </div>

                {/* Quick suggestions */}
                {unusedSuggestions.length > 0 && (
                    <div style={{ marginTop: '1rem' }}>
                        <div style={{
                            fontSize: '0.75rem',
                            color: 'var(--text-secondary)',
                            marginBottom: '0.5rem'
                        }}>
                            Suggestions:
                        </div>
                        <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
                            {unusedSuggestions.slice(0, 4).map(suggestion => (
                                <button
                                    key={suggestion}
                                    type="button"
                                    onClick={() => setNewKey(suggestion)}
                                    style={{
                                        padding: '0.25rem 0.5rem',
                                        fontSize: '0.75rem',
                                        fontFamily: 'monospace',
                                        background: 'var(--surface-hover)',
                                        border: '1px solid var(--border)',
                                        borderRadius: 4,
                                        cursor: 'pointer',
                                        transition: 'all 0.15s'
                                    }}
                                    onMouseEnter={(e) => {
                                        e.currentTarget.style.borderColor = 'var(--primary)';
                                        e.currentTarget.style.color = 'var(--primary)';
                                    }}
                                    onMouseLeave={(e) => {
                                        e.currentTarget.style.borderColor = 'var(--border)';
                                        e.currentTarget.style.color = 'inherit';
                                    }}
                                >
                                    {suggestion}
                                </button>
                            ))}
                        </div>
                    </div>
                )}
            </form>

            {/* Usage hint */}
            <div style={{
                padding: '1rem',
                background: 'rgba(99, 102, 241, 0.05)',
                borderRadius: 'var(--radius)',
                border: '1px solid rgba(99, 102, 241, 0.1)',
                fontSize: '0.875rem',
                color: 'var(--text-secondary)'
            }}>
                <strong style={{ color: 'var(--text)' }}>Usage in spec files:</strong>
                <pre style={{
                    marginTop: '0.5rem',
                    padding: '0.75rem',
                    background: 'var(--surface)',
                    borderRadius: 4,
                    fontFamily: 'monospace',
                    fontSize: '0.8rem',
                    overflow: 'auto'
                }}>
{`## Steps
1. Navigate to https://example.com/login
2. Enter "{{LOGIN_USERNAME}}" into the email field
3. Enter "{{LOGIN_PASSWORD}}" into the password field
4. Click the "Sign In" button`}
                </pre>
                <div style={{ marginTop: '0.5rem' }}>
                    Generated code uses <code style={{ background: 'var(--surface)', padding: '0.125rem 0.375rem', borderRadius: 4 }}>process.env.LOGIN_PASSWORD</code> (never hardcoded).
                </div>
            </div>
        </div>
    );
}
