'use client';

import React from 'react';

interface StageTimelineProps {
    currentStage?: string | null;
    healingAttempt?: number | null;
    stageMessage?: string | null;
    compact?: boolean;  // Compact mode for list view
}

const stages = ['planning', 'generating', 'testing', 'healing'] as const;

const stageConfig: Record<string, { icon: string; label: string; color: string }> = {
    planning: { icon: '📋', label: 'Planning', color: 'var(--warning)' },
    generating: { icon: '🤖', label: 'Generating', color: 'var(--primary)' },
    testing: { icon: '🔍', label: 'Testing', color: 'var(--accent)' },
    healing: { icon: '🔧', label: 'Healing', color: 'var(--danger)' },
};

export function StageTimeline({ currentStage, healingAttempt, stageMessage, compact = false }: StageTimelineProps) {
    const currentIndex = currentStage ? stages.indexOf(currentStage as typeof stages[number]) : -1;

    if (compact) {
        // Compact version for list items
        const config = currentStage ? stageConfig[currentStage] : null;
        if (!config) return null;

        let label = config.label;
        if (currentStage === 'healing' && healingAttempt) {
            label = `Healing (${healingAttempt}/3)`;
        }

        return (
            <div style={{
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'flex-end',
                gap: '0.25rem'
            }}>
                <div style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '0.4rem',
                    padding: '0.35rem 0.75rem',
                    borderRadius: '999px',
                    fontSize: '0.85rem',
                    fontWeight: 600,
                    background: `${config.color}15`,
                    color: config.color,
                    border: `1px solid ${config.color}40`,
                    animation: 'stagePulse 2s ease-in-out infinite'
                }}>
                    <span>{config.icon}</span>
                    <span>{label}</span>
                </div>
                {stageMessage && (
                    <span style={{
                        fontSize: '0.75rem',
                        color: 'var(--text-secondary)',
                        maxWidth: '180px',
                        whiteSpace: 'nowrap',
                        overflow: 'hidden',
                        textOverflow: 'ellipsis'
                    }}>
                        {stageMessage}
                    </span>
                )}
                <style jsx>{`
                    @keyframes stagePulse {
                        0%, 100% { opacity: 1; }
                        50% { opacity: 0.7; }
                    }
                `}</style>
            </div>
        );
    }

    // Full timeline version for detail pages
    return (
        <div style={{
            display: 'flex',
            flexDirection: 'column',
            gap: '1rem',
            padding: '1rem',
            background: 'var(--surface)',
            borderRadius: 'var(--radius)',
            border: '1px solid var(--border)'
        }}>
            <h3 style={{
                fontSize: '0.875rem',
                fontWeight: 600,
                color: 'var(--text-secondary)',
                marginBottom: '0.5rem',
                textTransform: 'uppercase',
                letterSpacing: '0.05em'
            }}>
                Pipeline Progress
            </h3>

            <div style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                gap: '0.5rem'
            }}>
                {stages.map((stage, index) => {
                    const config = stageConfig[stage];
                    const isComplete = currentIndex > index;
                    const isCurrent = currentIndex === index;
                    const isPending = currentIndex < index;

                    let label = config.label;
                    if (stage === 'healing' && isCurrent && healingAttempt) {
                        label = `Healing (${healingAttempt}/3)`;
                    }

                    return (
                        <React.Fragment key={stage}>
                            <div style={{
                                display: 'flex',
                                flexDirection: 'column',
                                alignItems: 'center',
                                gap: '0.5rem',
                                flex: 1
                            }}>
                                <div style={{
                                    width: '48px',
                                    height: '48px',
                                    borderRadius: '50%',
                                    display: 'flex',
                                    alignItems: 'center',
                                    justifyContent: 'center',
                                    fontSize: '1.25rem',
                                    background: isComplete
                                        ? 'var(--success-muted)'
                                        : isCurrent
                                            ? `${config.color}15`
                                            : 'var(--surface-hover)',
                                    border: isComplete
                                        ? '2px solid var(--success)'
                                        : isCurrent
                                            ? `2px solid ${config.color}`
                                            : '2px solid var(--border)',
                                    animation: isCurrent ? 'stagePulse 2s ease-in-out infinite' : 'none',
                                    transition: 'all 0.3s ease'
                                }}>
                                    {isComplete ? '✓' : config.icon}
                                </div>
                                <span style={{
                                    fontSize: '0.75rem',
                                    fontWeight: isCurrent ? 600 : 400,
                                    color: isComplete
                                        ? 'var(--success)'
                                        : isCurrent
                                            ? config.color
                                            : 'var(--text-secondary)',
                                    textAlign: 'center'
                                }}>
                                    {label}
                                </span>
                            </div>

                            {/* Connector line */}
                            {index < stages.length - 1 && (
                                <div style={{
                                    flex: 0.5,
                                    height: '2px',
                                    background: isComplete
                                        ? 'var(--success)'
                                        : 'var(--border)',
                                    marginTop: '-1.5rem',
                                    transition: 'background 0.3s ease'
                                }} />
                            )}
                        </React.Fragment>
                    );
                })}
            </div>

            {stageMessage && (
                <div style={{
                    fontSize: '0.875rem',
                    color: 'var(--text-secondary)',
                    textAlign: 'center',
                    padding: '0.5rem',
                    background: 'var(--surface-hover)',
                    borderRadius: 'var(--radius-sm)'
                }}>
                    {stageMessage}
                </div>
            )}

            <style jsx>{`
                @keyframes stagePulse {
                    0%, 100% { opacity: 1; transform: scale(1); }
                    50% { opacity: 0.8; transform: scale(1.05); }
                }
            `}</style>
        </div>
    );
}

export default StageTimeline;
