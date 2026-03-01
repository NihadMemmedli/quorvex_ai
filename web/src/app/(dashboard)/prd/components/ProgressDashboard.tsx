'use client';

import { Layers, CheckCircle, Activity, XCircle } from 'lucide-react';
import type { FeatureStats } from './types';

interface ProgressDashboardProps {
    stats: FeatureStats;
}

interface StatCardConfig {
    label: string;
    value: number;
    icon: React.ReactNode;
    color: string;
    iconBg: string;
    pulse?: boolean;
}

export function ProgressDashboard({ stats }: ProgressDashboardProps) {
    const cards: StatCardConfig[] = [
        {
            label: 'TOTAL',
            value: stats.total,
            icon: <Layers size={18} style={{ color: 'var(--text-secondary)' }} />,
            color: 'var(--text-secondary)',
            iconBg: 'rgba(126,139,168,0.1)',
        },
        {
            label: 'COMPLETED',
            value: stats.completed,
            icon: <CheckCircle size={18} style={{ color: '#4ade80' }} />,
            color: '#4ade80',
            iconBg: 'rgba(34,197,94,0.1)',
        },
        {
            label: 'IN PROGRESS',
            value: stats.running,
            icon: (
                <Activity
                    size={18}
                    style={{
                        color: '#60a5fa',
                        ...(stats.running > 0 ? { animation: 'pulse 2s ease-in-out infinite' } : {}),
                    }}
                />
            ),
            color: '#60a5fa',
            iconBg: 'rgba(59,130,246,0.1)',
            pulse: stats.running > 0,
        },
        {
            label: 'FAILED',
            value: stats.failed,
            icon: <XCircle size={18} style={{ color: '#f87171' }} />,
            color: '#f87171',
            iconBg: 'rgba(248,113,113,0.1)',
        },
    ];

    return (
        <div
            className="progress-dashboard-grid"
            style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(4, 1fr)',
                gap: '0.75rem',
            }}
        >
            <style>{`
                @media (max-width: 768px) {
                    .progress-dashboard-grid {
                        grid-template-columns: repeat(2, 1fr) !important;
                    }
                }
            `}</style>
            {cards.map((card) => (
                <div
                    key={card.label}
                    className="card-elevated"
                    style={{
                        padding: '1rem',
                        display: 'flex',
                        alignItems: 'center',
                        gap: '0.75rem',
                    }}
                >
                    {/* Icon container */}
                    <div style={{
                        width: 36,
                        height: 36,
                        borderRadius: 'var(--radius)',
                        background: card.iconBg,
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        flexShrink: 0,
                    }}>
                        {card.icon}
                    </div>

                    {/* Text */}
                    <div style={{ display: 'flex', flexDirection: 'column' }}>
                        <span style={{
                            fontSize: '1.5rem',
                            fontFamily: 'var(--font-mono)',
                            fontWeight: 800,
                            color: 'var(--text)',
                            lineHeight: 1.1,
                            fontFeatureSettings: '"tnum" 1',
                        }}>
                            {card.value}
                        </span>
                        <span style={{
                            fontSize: '0.625rem',
                            fontWeight: 600,
                            textTransform: 'uppercase',
                            letterSpacing: '0.08em',
                            color: 'var(--text-tertiary)',
                            marginTop: 2,
                        }}>
                            {card.label}
                        </span>
                    </div>
                </div>
            ))}
        </div>
    );
}
