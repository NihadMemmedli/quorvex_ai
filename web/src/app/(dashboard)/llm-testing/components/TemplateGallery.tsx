'use client';
import { useState } from 'react';
import { cardStyleCompact, btnPrimary, btnSecondary } from '@/lib/styles';
import { SPEC_TEMPLATES } from './templates';
import type { SpecTemplate } from './templates';

const CATEGORIES = [
    { key: 'all', label: 'All' },
    { key: 'chatbot', label: 'Chatbot' },
    { key: 'rag', label: 'RAG' },
    { key: 'summarization', label: 'Summarization' },
    { key: 'code-gen', label: 'Code Gen' },
    { key: 'classification', label: 'Classification' },
    { key: 'safety', label: 'Safety' },
] as const;

const CATEGORY_COLORS: Record<string, string> = {
    chatbot: 'var(--primary)',
    rag: 'var(--accent)',
    summarization: 'var(--warning)',
    'code-gen': 'var(--success)',
    classification: 'var(--accent)',
    safety: 'var(--danger)',
};

interface TemplateGalleryProps {
    onSelect: (markdown: string) => void;
}

export default function TemplateGallery({ onSelect }: TemplateGalleryProps) {
    const [filter, setFilter] = useState('all');
    const [preview, setPreview] = useState<SpecTemplate | null>(null);

    const filtered = filter === 'all'
        ? SPEC_TEMPLATES
        : SPEC_TEMPLATES.filter(t => t.category === filter);

    return (
        <div>
            {/* Category Filter Bar */}
            <div style={{ display: 'flex', gap: '0.4rem', marginBottom: '1rem', flexWrap: 'wrap' }}>
                {CATEGORIES.map(c => (
                    <button
                        key={c.key}
                        onClick={() => setFilter(c.key)}
                        style={{
                            padding: '0.35rem 0.75rem',
                            borderRadius: 'var(--radius)',
                            border: '1px solid var(--border)',
                            background: filter === c.key ? 'var(--primary)' : 'var(--surface)',
                            color: filter === c.key ? '#fff' : 'var(--text-secondary)',
                            cursor: 'pointer',
                            fontSize: '0.82rem',
                            fontWeight: 500,
                        }}
                    >
                        {c.label}
                    </button>
                ))}
            </div>

            {/* Template Grid */}
            <div style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(3, 1fr)',
                gap: '0.75rem',
            }}>
                {filtered.map(t => (
                    <div
                        key={t.id}
                        style={{
                            ...cardStyleCompact,
                            display: 'flex',
                            flexDirection: 'column',
                            justifyContent: 'space-between',
                            transition: 'border-color 0.15s',
                            cursor: 'default',
                        }}
                        onMouseEnter={e => (e.currentTarget.style.borderColor = CATEGORY_COLORS[t.category] || 'var(--border)')}
                        onMouseLeave={e => (e.currentTarget.style.borderColor = 'var(--border)')}
                    >
                        <div>
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '0.4rem' }}>
                                <div style={{ fontWeight: 600, fontSize: '0.9rem' }}>{t.name}</div>
                                <span style={{
                                    fontSize: '0.7rem',
                                    fontWeight: 600,
                                    padding: '0.15rem 0.45rem',
                                    borderRadius: '9999px',
                                    background: `${CATEGORY_COLORS[t.category]}18`,
                                    color: CATEGORY_COLORS[t.category],
                                    whiteSpace: 'nowrap',
                                }}>
                                    {t.category}
                                </span>
                            </div>
                            <p style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', margin: 0, lineHeight: 1.4, marginBottom: '0.5rem', display: '-webkit-box', WebkitLineClamp: 3, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}>
                                {t.description}
                            </p>
                            <div style={{ fontSize: '0.78rem', color: 'var(--text-secondary)' }}>
                                {t.caseCount} test case{t.caseCount !== 1 ? 's' : ''}
                            </div>
                        </div>
                        <div style={{ display: 'flex', gap: '0.4rem', marginTop: '0.6rem' }}>
                            <button onClick={() => setPreview(t)} style={{ ...btnSecondary, flex: 1, justifyContent: 'center', fontSize: '0.8rem', padding: '0.35rem 0.5rem' }}>
                                Preview
                            </button>
                            <button onClick={() => onSelect(t.markdown)} style={{ ...btnPrimary, flex: 1, justifyContent: 'center', fontSize: '0.8rem', padding: '0.35rem 0.5rem' }}>
                                Use Template
                            </button>
                        </div>
                    </div>
                ))}
            </div>

            {/* Preview Modal */}
            {preview && (
                <div
                    onClick={() => setPreview(null)}
                    style={{
                        position: 'fixed',
                        inset: 0,
                        background: 'rgba(0,0,0,0.5)',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        zIndex: 1000,
                    }}
                >
                    <div
                        onClick={e => e.stopPropagation()}
                        style={{
                            background: 'var(--surface)',
                            border: '1px solid var(--border)',
                            borderRadius: 'var(--radius)',
                            padding: '1.5rem',
                            width: '80%',
                            maxWidth: 720,
                            maxHeight: '80vh',
                            overflow: 'auto',
                        }}
                    >
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
                            <h3 style={{ margin: 0, fontWeight: 600 }}>{preview.name}</h3>
                            <button onClick={() => setPreview(null)} style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: '1.2rem', color: 'var(--text-secondary)' }}>
                                x
                            </button>
                        </div>
                        <pre style={{
                            fontFamily: 'monospace',
                            fontSize: '0.82rem',
                            whiteSpace: 'pre-wrap',
                            wordBreak: 'break-word',
                            background: 'var(--background)',
                            padding: '1rem',
                            borderRadius: 'var(--radius)',
                            border: '1px solid var(--border)',
                            lineHeight: 1.5,
                            maxHeight: '55vh',
                            overflow: 'auto',
                        }}>
                            {preview.markdown}
                        </pre>
                        <div style={{ display: 'flex', gap: '0.5rem', marginTop: '1rem', justifyContent: 'flex-end' }}>
                            <button onClick={() => setPreview(null)} style={btnSecondary}>Close</button>
                            <button onClick={() => { onSelect(preview.markdown); setPreview(null); }} style={btnPrimary}>
                                Use Template
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
}
