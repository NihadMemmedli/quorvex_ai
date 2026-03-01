'use client';
import React, { useState } from 'react';
import dynamic from 'next/dynamic';
import { X, Loader2 } from 'lucide-react';
import { API_BASE } from '@/lib/api';
import { API_SPEC_TEMPLATE } from './types';

const ApiSpecBuilder = dynamic(() => import('@/components/ApiSpecBuilder'), { ssr: false });

interface ApiSpecsCreateModalProps {
    projectId: string;
    onClose: () => void;
    onCreated: () => void;
    setMessage: (msg: { type: 'success' | 'error'; text: string } | null) => void;
}

export default function ApiSpecsCreateModal({
    projectId,
    onClose,
    onCreated,
    setMessage,
}: ApiSpecsCreateModalProps) {
    const [newSpecName, setNewSpecName] = useState('');
    const [newSpecContent, setNewSpecContent] = useState(API_SPEC_TEMPLATE);
    const [creating, setCreating] = useState(false);
    const [createMode, setCreateMode] = useState<'code' | 'visual'>('visual');

    const handleCreateSpec = async () => {
        if (!newSpecName.trim()) return;
        setCreating(true);
        try {
            const res = await fetch(`${API_BASE}/api-testing/specs`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name: newSpecName, content: newSpecContent, project_id: projectId }),
            });
            if (res.ok) {
                setMessage({ type: 'success', text: 'API spec created successfully' });
                onCreated();
                onClose();
            } else {
                const err = await res.json();
                setMessage({ type: 'error', text: err.detail || 'Failed to create spec' });
            }
        } catch {
            setMessage({ type: 'error', text: 'Failed to create spec' });
        } finally {
            setCreating(false);
        }
    };

    return (
        <div
            style={{
                position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
                background: 'rgba(0,0,0,0.5)', display: 'flex', alignItems: 'center',
                justifyContent: 'center', zIndex: 1000,
            }}
            onClick={onClose}
        >
            <div
                style={{
                    background: 'var(--surface)', borderRadius: 'var(--radius)',
                    padding: '1.5rem', width: '90%', maxWidth: '900px',
                    maxHeight: '90vh', overflow: 'auto',
                    border: '1px solid var(--border)',
                }}
                onClick={e => e.stopPropagation()}
            >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
                    <h3 style={{ fontSize: '1.1rem', fontWeight: 600 }}>Create API Spec</h3>
                    <button onClick={onClose} style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-secondary)' }}>
                        <X size={20} />
                    </button>
                </div>

                <div style={{ marginBottom: '1rem' }}>
                    <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 500, marginBottom: '0.4rem', color: 'var(--text-secondary)' }}>
                        Spec Name
                    </label>
                    <input
                        type="text"
                        placeholder="e.g., user-api-tests"
                        value={newSpecName}
                        onChange={e => setNewSpecName(e.target.value)}
                        style={{
                            width: '100%', padding: '0.6rem 0.75rem',
                            background: 'var(--background)', border: '1px solid var(--border)',
                            borderRadius: 'var(--radius)', color: 'var(--text-primary)', fontSize: '0.875rem',
                        }}
                    />
                </div>

                {/* Code / Visual toggle */}
                <div style={{ display: 'flex', gap: '0', marginBottom: '0.75rem' }}>
                    {(['visual', 'code'] as const).map(mode => (
                        <button
                            key={mode}
                            onClick={() => setCreateMode(mode)}
                            style={{
                                padding: '0.4rem 1rem',
                                border: '1px solid var(--border)',
                                borderRight: mode === 'visual' ? 'none' : undefined,
                                borderRadius: mode === 'visual' ? 'var(--radius) 0 0 var(--radius)' : '0 var(--radius) var(--radius) 0',
                                background: createMode === mode ? 'var(--primary-glow)' : 'transparent',
                                color: createMode === mode ? 'var(--primary)' : 'var(--text-secondary)',
                                fontWeight: createMode === mode ? 600 : 400,
                                cursor: 'pointer',
                                fontSize: '0.8rem',
                            }}
                        >
                            {mode === 'visual' ? 'Visual' : 'Code'}
                        </button>
                    ))}
                </div>

                <div style={{ marginBottom: '1rem' }}>
                    {createMode === 'visual' ? (
                        <ApiSpecBuilder content={newSpecContent} onChange={setNewSpecContent} />
                    ) : (
                        <textarea
                            value={newSpecContent}
                            onChange={e => setNewSpecContent(e.target.value)}
                            style={{
                                width: '100%', minHeight: '350px', padding: '0.75rem',
                                background: 'var(--background)', color: 'var(--text)', border: '1px solid var(--border)',
                                borderRadius: 'var(--radius)', fontFamily: 'monospace', fontSize: '0.8rem',
                                resize: 'vertical',
                            }}
                        />
                    )}
                </div>

                <div style={{ display: 'flex', gap: '0.5rem', justifyContent: 'flex-end' }}>
                    <button
                        onClick={onClose}
                        style={{
                            padding: '0.5rem 1rem', background: 'var(--surface)',
                            color: 'var(--text-secondary)', border: '1px solid var(--border)',
                            borderRadius: 'var(--radius)', cursor: 'pointer',
                        }}
                    >
                        Cancel
                    </button>
                    <button
                        onClick={handleCreateSpec}
                        disabled={!newSpecName.trim() || creating}
                        style={{
                            padding: '0.5rem 1rem', background: 'var(--primary)', color: 'white',
                            border: 'none', borderRadius: 'var(--radius)', cursor: 'pointer',
                            fontWeight: 500, opacity: !newSpecName.trim() || creating ? 0.5 : 1,
                            display: 'flex', alignItems: 'center', gap: '0.5rem',
                        }}
                    >
                        {creating && <Loader2 size={14} style={{ animation: 'spin 1s linear infinite' }} />}
                        Create Spec
                    </button>
                </div>
            </div>
        </div>
    );
}
