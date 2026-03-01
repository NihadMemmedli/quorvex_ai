'use client';

import { FileText, Layers, RefreshCw } from 'lucide-react';

interface ProjectInfoBarProps {
    projectName: string;
    featureCount: number;
    completedCount: number;
    onReset: () => void;
}

export function ProjectInfoBar({
    projectName,
    featureCount,
    completedCount,
    onReset,
}: ProjectInfoBarProps) {
    const percentage = featureCount > 0
        ? Math.round((completedCount / featureCount) * 100)
        : 0;

    return (
        <div
            className="card-elevated"
            style={{
                height: 52,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                padding: '0 1.25rem',
                transform: 'none',
            }}
            onMouseEnter={(e) => {
                e.currentTarget.style.transform = 'none';
            }}
            onMouseLeave={(e) => {
                e.currentTarget.style.transform = 'none';
            }}
        >
            {/* Left: Status dot + project name */}
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
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
                    maxWidth: 240,
                }}>
                    {projectName}
                </span>
            </div>

            {/* Center-right: feature count + progress */}
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.375rem' }}>
                    <Layers size={13} style={{ color: 'var(--text-tertiary)' }} />
                    <span style={{
                        fontSize: '0.75rem',
                        fontFamily: 'var(--font-mono)',
                        color: 'var(--text-secondary)',
                    }}>
                        {completedCount}/{featureCount}
                    </span>
                </div>

                {/* Progress bar */}
                <div style={{
                    width: 120,
                    height: 4,
                    borderRadius: 9999,
                    background: 'rgba(255,255,255,0.06)',
                    overflow: 'hidden',
                    flexShrink: 0,
                }}>
                    <div style={{
                        width: `${percentage}%`,
                        height: '100%',
                        borderRadius: 9999,
                        background: 'linear-gradient(90deg, var(--primary), var(--accent))',
                        transition: 'width 0.6s var(--ease-smooth)',
                    }} />
                </div>

                <span style={{
                    fontSize: '0.7rem',
                    fontFamily: 'var(--font-mono)',
                    color: 'var(--text-tertiary)',
                    minWidth: 32,
                    textAlign: 'right',
                }}>
                    {percentage}%
                </span>
            </div>

            {/* Right: New Project button */}
            <button
                onClick={onReset}
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
