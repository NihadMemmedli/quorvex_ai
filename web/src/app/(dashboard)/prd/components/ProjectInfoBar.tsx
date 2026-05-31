'use client';

import { FileText, RefreshCw } from 'lucide-react';

interface ProjectInfoBarProps {
    projectName: string;
    onReset: () => void;
}

export function ProjectInfoBar({
    projectName,
    onReset,
}: ProjectInfoBarProps) {
    return (
        <div
            className="card-elevated"
            style={{
                minHeight: 52,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                gap: '0.75rem',
                padding: '0.6rem 1.25rem',
                transform: 'none',
                flexWrap: 'wrap',
            }}
            onMouseEnter={(e) => {
                e.currentTarget.style.transform = 'none';
            }}
            onMouseLeave={(e) => {
                e.currentTarget.style.transform = 'none';
            }}
        >
            <style>{`
                .prd-project-reset:focus-visible {
                    outline: none;
                    box-shadow: 0 0 0 2px rgba(59,130,246,0.45);
                }
            `}</style>
            {/* Left: Status dot + project name */}
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', minWidth: 0, flex: '1 1 220px' }}>
                {/* Pulsing green dot */}
                <div style={{ position: 'relative', width: 8, height: 8 }}>
                    <div style={{
                        position: 'absolute',
                        inset: 0,
                        borderRadius: '50%',
                        background: '#22c55e',
                    }} />
                    <div style={{
                        position: 'absolute',
                        inset: -2,
                        borderRadius: '50%',
                        background: '#22c55e',
                        opacity: 0.4,
                        animation: 'pulse 2s ease-in-out infinite',
                    }} />
                </div>

                <FileText size={15} style={{ color: 'var(--primary)', flexShrink: 0 }} />

                <span style={{
                    fontFamily: 'var(--font-mono)',
                    fontWeight: 600,
                    fontSize: '0.8rem',
                    color: 'var(--text)',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                    maxWidth: '100%',
                }}>
                    {projectName}
                </span>
            </div>

            {/* Right: New Project button */}
            <button
                type="button"
                onClick={onReset}
                className="prd-project-reset"
                style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '0.375rem',
                    padding: '0.35rem 0.75rem',
                    background: 'transparent',
                    border: '1px solid rgba(255,255,255,0.06)',
                    borderRadius: 'var(--radius-sm)',
                    color: 'var(--text-secondary)',
                    fontSize: '0.7rem',
                    fontWeight: 500,
                    cursor: 'pointer',
                    transition: 'all 0.2s var(--ease-smooth)',
                    whiteSpace: 'nowrap',
                }}
                onMouseEnter={(e) => {
                    e.currentTarget.style.background = 'var(--surface-hover)';
                    e.currentTarget.style.borderColor = 'var(--border-bright)';
                    e.currentTarget.style.color = 'var(--text)';
                }}
                onMouseLeave={(e) => {
                    e.currentTarget.style.background = 'transparent';
                    e.currentTarget.style.borderColor = 'rgba(255,255,255,0.06)';
                    e.currentTarget.style.color = 'var(--text-secondary)';
                }}
            >
                <RefreshCw size={12} />
                New Project
            </button>
        </div>
    );
}
