'use client';
import React, { useState } from 'react';
import dynamic from 'next/dynamic';
import { Plus, Trash2, Edit2, Save } from 'lucide-react';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { vscDarkPlus } from 'react-syntax-highlighter/dist/esm/styles/prism';
import { API_BASE } from '@/lib/api';
import { getAuthHeaders, cardStyle } from '@/lib/styles';
import { SecuritySpec } from './types';

const CodeEditor = dynamic(() => import('@/components/CodeEditor'), { ssr: false });

interface SpecsTabProps {
    projectId: string;
    specs: SecuritySpec[];
    fetchSpecs: () => Promise<void>;
}

export default function SpecsTab({ projectId, specs, fetchSpecs }: SpecsTabProps) {
    const [selectedSpec, setSelectedSpec] = useState<SecuritySpec | null>(null);
    const [specContent, setSpecContent] = useState('');
    const [isCreatingSpec, setIsCreatingSpec] = useState(false);
    const [newSpecName, setNewSpecName] = useState('');
    const [newSpecContent, setNewSpecContent] = useState('');
    const [editingSpec, setEditingSpec] = useState(false);

    const loadSpecContent = async (spec: SecuritySpec) => {
        try {
            const res = await fetch(`${API_BASE}/security-testing/specs/${encodeURIComponent(spec.name)}?project_id=${projectId}`, {
                headers: getAuthHeaders(),
            });
            if (res.ok) {
                const data = await res.json();
                setSelectedSpec(spec);
                setSpecContent(data.content || '');
                setEditingSpec(false);
            }
        } catch (e) { console.error('Load spec failed:', e); }
    };

    const createSpec = async () => {
        if (!newSpecName.trim() || !newSpecContent.trim()) return;
        try {
            const res = await fetch(`${API_BASE}/security-testing/specs`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
                body: JSON.stringify({ name: newSpecName, content: newSpecContent, project_id: projectId }),
            });
            if (res.ok) {
                setIsCreatingSpec(false);
                setNewSpecName('');
                setNewSpecContent('');
                fetchSpecs();
            }
        } catch (e) { console.error('Create spec failed:', e); }
    };

    const deleteSpec = async (name: string) => {
        if (!confirm(`Delete spec "${name}"?`)) return;
        try {
            await fetch(`${API_BASE}/security-testing/specs/${encodeURIComponent(name)}?project_id=${projectId}`, {
                method: 'DELETE', headers: getAuthHeaders(),
            });
            fetchSpecs();
            if (selectedSpec?.name === name) setSelectedSpec(null);
        } catch (e) { console.error('Delete spec failed:', e); }
    };

    const updateSpec = async () => {
        if (!selectedSpec) return;
        try {
            await fetch(`${API_BASE}/security-testing/specs/${encodeURIComponent(selectedSpec.name)}?project_id=${projectId}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
                body: JSON.stringify({ content: specContent }),
            });
            setEditingSpec(false);
            fetchSpecs();
        } catch (e) { console.error('Update spec failed:', e); }
    };

    return (
        <div style={{ display: 'grid', gridTemplateColumns: '300px 1fr', gap: '1rem' }}>
            {/* Spec List */}
            <div style={cardStyle}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
                    <h3 style={{ fontWeight: 600, fontSize: '0.9rem' }}>Security Specs</h3>
                    <button onClick={() => setIsCreatingSpec(true)} style={{
                        background: 'var(--primary)', color: 'white', border: 'none',
                        borderRadius: 'var(--radius)', padding: '4px 8px', cursor: 'pointer',
                        display: 'flex', alignItems: 'center', gap: '4px', fontSize: '0.8rem',
                    }}>
                        <Plus size={14} /> New
                    </button>
                </div>

                {specs.length === 0 && (
                    <p style={{ color: 'var(--text-secondary)', fontSize: '0.85rem' }}>No specs yet</p>
                )}

                {specs.map(spec => (
                    <div key={spec.name} onClick={() => loadSpecContent(spec)} style={{
                        padding: '0.5rem 0.75rem', borderRadius: 'var(--radius)', cursor: 'pointer',
                        background: selectedSpec?.name === spec.name ? 'var(--primary-glow)' : 'transparent',
                        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                        marginBottom: '0.25rem',
                    }}>
                        <span style={{ fontSize: '0.85rem' }}>{spec.name}</span>
                        <button onClick={e => { e.stopPropagation(); deleteSpec(spec.name); }} style={{
                            background: 'none', border: 'none', cursor: 'pointer',
                            color: 'var(--text-secondary)', padding: '2px',
                        }}>
                            <Trash2 size={14} />
                        </button>
                    </div>
                ))}
            </div>

            {/* Spec Editor */}
            <div style={cardStyle}>
                {isCreatingSpec ? (
                    <>
                        <h3 style={{ fontWeight: 600, marginBottom: '1rem' }}>Create New Spec</h3>
                        <input
                            type="text"
                            placeholder="Spec name (e.g., auth-security-scan)"
                            value={newSpecName}
                            onChange={e => setNewSpecName(e.target.value)}
                            style={{
                                width: '100%', padding: '0.5rem', marginBottom: '1rem',
                                borderRadius: 'var(--radius)', border: '1px solid var(--border)',
                                background: 'var(--bg)', color: 'var(--text)',
                            }}
                        />
                        <div style={{ height: '400px', marginBottom: '1rem' }}>
                            <CodeEditor
                                value={newSpecContent}
                                onChange={(v: string) => setNewSpecContent(v)}
                                language="markdown"
                            />
                        </div>
                        <div style={{ display: 'flex', gap: '0.5rem' }}>
                            <button onClick={createSpec} style={{
                                background: 'var(--primary)', color: 'white', border: 'none',
                                borderRadius: 'var(--radius)', padding: '0.5rem 1rem', cursor: 'pointer',
                                display: 'flex', alignItems: 'center', gap: '4px',
                            }}>
                                <Save size={14} /> Save
                            </button>
                            <button onClick={() => setIsCreatingSpec(false)} style={{
                                background: 'var(--border)', color: 'var(--text)', border: 'none',
                                borderRadius: 'var(--radius)', padding: '0.5rem 1rem', cursor: 'pointer',
                            }}>
                                Cancel
                            </button>
                        </div>
                    </>
                ) : selectedSpec ? (
                    <>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
                            <h3 style={{ fontWeight: 600 }}>{selectedSpec.name}</h3>
                            <div style={{ display: 'flex', gap: '0.5rem' }}>
                                {editingSpec ? (
                                    <>
                                        <button onClick={updateSpec} style={{
                                            background: 'var(--primary)', color: 'white', border: 'none',
                                            borderRadius: 'var(--radius)', padding: '4px 12px', cursor: 'pointer',
                                            display: 'flex', alignItems: 'center', gap: '4px', fontSize: '0.8rem',
                                        }}>
                                            <Save size={14} /> Save
                                        </button>
                                        <button onClick={() => setEditingSpec(false)} style={{
                                            background: 'var(--border)', color: 'var(--text)', border: 'none',
                                            borderRadius: 'var(--radius)', padding: '4px 12px', cursor: 'pointer',
                                            fontSize: '0.8rem',
                                        }}>
                                            Cancel
                                        </button>
                                    </>
                                ) : (
                                    <button onClick={() => setEditingSpec(true)} style={{
                                        background: 'var(--border)', color: 'var(--text)', border: 'none',
                                        borderRadius: 'var(--radius)', padding: '4px 12px', cursor: 'pointer',
                                        display: 'flex', alignItems: 'center', gap: '4px', fontSize: '0.8rem',
                                    }}>
                                        <Edit2 size={14} /> Edit
                                    </button>
                                )}
                            </div>
                        </div>
                        <div style={{ height: '500px' }}>
                            {editingSpec ? (
                                <CodeEditor
                                    value={specContent}
                                    onChange={(v: string) => setSpecContent(v)}
                                    language="markdown"
                                />
                            ) : (
                                <SyntaxHighlighter
                                    language="markdown"
                                    style={vscDarkPlus}
                                    customStyle={{ height: '100%', margin: 0, borderRadius: 'var(--radius)' }}
                                >
                                    {specContent}
                                </SyntaxHighlighter>
                            )}
                        </div>
                    </>
                ) : (
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '300px', color: 'var(--text-secondary)' }}>
                        Select a spec to view or create a new one
                    </div>
                )}
            </div>
        </div>
    );
}
