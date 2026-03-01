'use client';
import React, { useState } from 'react';
import {
    Plus, X, Save, Loader2, Server, Link2, Trash2, CheckCircle, AlertCircle,
} from 'lucide-react';
import { formatDate } from '@/lib/formatting';
import { cardStyle, inputStyle, btnPrimary, btnSecondary } from '@/lib/styles';
import { getAuthHeaders } from '@/lib/styles';
import { API_BASE } from '@/lib/api';
import type { DbConnection } from './types';

interface ConnectionsTabProps {
    connections: DbConnection[];
    projectId: string;
    onRefresh: () => void;
}

const INITIAL_FORM = {
    name: '', host: 'localhost', port: 5432, database: '', username: '',
    password: '', ssl_mode: 'prefer', schema_name: 'public', is_read_only: true,
};

export default function ConnectionsTab({ connections, projectId, onRefresh }: ConnectionsTabProps) {
    const [showConnForm, setShowConnForm] = useState(false);
    const [connForm, setConnForm] = useState(INITIAL_FORM);
    const [testingConnId, setTestingConnId] = useState<string | null>(null);
    const [connTestResult, setConnTestResult] = useState<{ id: string; success: boolean; error?: string } | null>(null);

    const createConnection = async () => {
        if (!connForm.name.trim() || !connForm.host.trim() || !connForm.database.trim()) return;
        try {
            const res = await fetch(`${API_BASE}/database-testing/connections`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
                body: JSON.stringify({ ...connForm, project_id: projectId }),
            });
            if (res.ok) {
                setShowConnForm(false);
                setConnForm(INITIAL_FORM);
                onRefresh();
            } else {
                const err = await res.json().catch(() => ({ detail: 'Failed to create connection' }));
                alert(err.detail || 'Failed to create connection');
            }
        } catch (e) { console.error('Create connection failed:', e); }
    };

    const testConnection = async (connId: string) => {
        setTestingConnId(connId);
        setConnTestResult(null);
        try {
            const res = await fetch(`${API_BASE}/database-testing/connections/${connId}/test`, {
                method: 'POST',
                headers: getAuthHeaders(),
            });
            const data = await res.json();
            setConnTestResult({ id: connId, success: data.success ?? res.ok, error: data.error || data.detail });
            onRefresh();
        } catch (e) {
            setConnTestResult({ id: connId, success: false, error: String(e) });
        }
        setTestingConnId(null);
    };

    const deleteConnection = async (connId: string) => {
        if (!confirm('Delete this connection?')) return;
        try {
            await fetch(`${API_BASE}/database-testing/connections/${connId}`, {
                method: 'DELETE', headers: getAuthHeaders(),
            });
            onRefresh();
        } catch (e) { console.error('Delete connection failed:', e); }
    };

    return (
        <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
                <h3 style={{ fontWeight: 600 }}>Database Connections</h3>
                <button onClick={() => setShowConnForm(true)} style={btnPrimary}>
                    <Plus size={16} /> Add Connection
                </button>
            </div>

            {/* Connection Form */}
            {showConnForm && (
                <div style={{ ...cardStyle, marginBottom: '1.5rem' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
                        <h4 style={{ fontWeight: 600 }}>New Connection</h4>
                        <button onClick={() => setShowConnForm(false)} style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-secondary)' }}>
                            <X size={18} />
                        </button>
                    </div>
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}>
                        <div>
                            <label style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '4px', display: 'block' }}>Name *</label>
                            <input type="text" placeholder="My Database" value={connForm.name}
                                onChange={e => setConnForm({ ...connForm, name: e.target.value })} style={inputStyle} />
                        </div>
                        <div>
                            <label style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '4px', display: 'block' }}>Host *</label>
                            <input type="text" placeholder="localhost" value={connForm.host}
                                onChange={e => setConnForm({ ...connForm, host: e.target.value })} style={inputStyle} />
                        </div>
                        <div>
                            <label style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '4px', display: 'block' }}>Port</label>
                            <input type="number" value={connForm.port}
                                onChange={e => setConnForm({ ...connForm, port: parseInt(e.target.value) || 5432 })} style={inputStyle} />
                        </div>
                        <div>
                            <label style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '4px', display: 'block' }}>Database *</label>
                            <input type="text" placeholder="mydb" value={connForm.database}
                                onChange={e => setConnForm({ ...connForm, database: e.target.value })} style={inputStyle} />
                        </div>
                        <div>
                            <label style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '4px', display: 'block' }}>Username</label>
                            <input type="text" placeholder="postgres" value={connForm.username}
                                onChange={e => setConnForm({ ...connForm, username: e.target.value })} style={inputStyle} />
                        </div>
                        <div>
                            <label style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '4px', display: 'block' }}>Password</label>
                            <input type="password" placeholder="********" value={connForm.password}
                                onChange={e => setConnForm({ ...connForm, password: e.target.value })} style={inputStyle} />
                        </div>
                        <div>
                            <label style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '4px', display: 'block' }}>SSL Mode</label>
                            <select value={connForm.ssl_mode}
                                onChange={e => setConnForm({ ...connForm, ssl_mode: e.target.value })}
                                style={inputStyle}>
                                <option value="disable">disable</option>
                                <option value="allow">allow</option>
                                <option value="prefer">prefer</option>
                                <option value="require">require</option>
                                <option value="verify-ca">verify-ca</option>
                                <option value="verify-full">verify-full</option>
                            </select>
                        </div>
                        <div>
                            <label style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '4px', display: 'block' }}>Schema</label>
                            <input type="text" placeholder="public" value={connForm.schema_name}
                                onChange={e => setConnForm({ ...connForm, schema_name: e.target.value })} style={inputStyle} />
                        </div>
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginTop: '1rem' }}>
                        <input type="checkbox" id="is_read_only" checked={connForm.is_read_only}
                            onChange={e => setConnForm({ ...connForm, is_read_only: e.target.checked })} />
                        <label htmlFor="is_read_only" style={{ fontSize: '0.85rem' }}>Read-only mode (recommended)</label>
                    </div>
                    <div style={{ display: 'flex', gap: '0.5rem', marginTop: '1rem' }}>
                        <button onClick={createConnection} style={btnPrimary}>
                            <Save size={14} /> Save Connection
                        </button>
                        <button onClick={() => setShowConnForm(false)} style={btnSecondary}>Cancel</button>
                    </div>
                </div>
            )}

            {/* Connection List */}
            {connections.length === 0 && !showConnForm ? (
                <div style={{ ...cardStyle, textAlign: 'center', padding: '3rem' }}>
                    <Server size={40} style={{ color: 'var(--text-secondary)', marginBottom: '1rem' }} />
                    <p style={{ color: 'var(--text-secondary)' }}>No connections configured. Add your first database connection.</p>
                </div>
            ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                    {connections.map(conn => (
                        <div key={conn.id} style={{
                            ...cardStyle, padding: '1rem',
                            display: 'flex', alignItems: 'center', gap: '1rem',
                        }}>
                            <div style={{
                                width: '10px', height: '10px', borderRadius: '50%',
                                background: conn.last_test_success === true ? 'var(--success)'
                                    : conn.last_test_success === false ? 'var(--danger)' : 'var(--text-tertiary)',
                                flexShrink: 0,
                            }} />
                            <div style={{ flex: 1 }}>
                                <div style={{ fontWeight: 600, fontSize: '0.95rem' }}>{conn.name}</div>
                                <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                                    {conn.host}:{conn.port}/{conn.database}
                                    {conn.schema_name !== 'public' && ` (${conn.schema_name})`}
                                    {conn.is_read_only && <span style={{ marginLeft: '0.5rem', color: 'var(--primary-hover)' }}>[read-only]</span>}
                                </div>
                                {conn.last_test_error && (
                                    <div style={{ fontSize: '0.75rem', color: 'var(--danger)', marginTop: '2px' }}>
                                        {conn.last_test_error}
                                    </div>
                                )}
                            </div>
                            {conn.last_tested_at && (
                                <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', textAlign: 'right' }}>
                                    Last tested<br />{formatDate(conn.last_tested_at)}
                                </div>
                            )}
                            <div style={{ display: 'flex', gap: '0.5rem' }}>
                                <button
                                    onClick={() => testConnection(conn.id)}
                                    disabled={testingConnId === conn.id}
                                    style={{
                                        ...btnSecondary, padding: '0.4rem 0.75rem', fontSize: '0.8rem',
                                        cursor: testingConnId === conn.id ? 'not-allowed' : 'pointer',
                                    }}
                                >
                                    {testingConnId === conn.id
                                        ? <Loader2 size={14} style={{ animation: 'spin 1s linear infinite' }} />
                                        : <Link2 size={14} />}
                                    Test
                                </button>
                                <button onClick={() => deleteConnection(conn.id)} style={{
                                    background: 'none', border: '1px solid var(--border)',
                                    borderRadius: 'var(--radius)', padding: '0.4rem 0.6rem',
                                    cursor: 'pointer', color: 'var(--danger)',
                                }}>
                                    <Trash2 size={14} />
                                </button>
                            </div>
                        </div>
                    ))}
                </div>
            )}

            {/* Inline test result toast */}
            {connTestResult && (
                <div style={{
                    position: 'fixed', bottom: '2rem', right: '2rem',
                    padding: '1rem 1.5rem', borderRadius: 'var(--radius)',
                    background: connTestResult.success ? 'var(--success)' : 'var(--danger)',
                    color: 'white', fontSize: '0.9rem', zIndex: 1000,
                    display: 'flex', alignItems: 'center', gap: '0.5rem',
                    boxShadow: '0 4px 12px rgba(0,0,0,0.3)',
                }}>
                    {connTestResult.success ? <CheckCircle size={16} /> : <AlertCircle size={16} />}
                    {connTestResult.success ? 'Connection successful' : `Connection failed: ${connTestResult.error}`}
                    <button onClick={() => setConnTestResult(null)} style={{
                        background: 'none', border: 'none', color: 'white', cursor: 'pointer', marginLeft: '0.5rem',
                    }}><X size={14} /></button>
                </div>
            )}
        </div>
    );
}
