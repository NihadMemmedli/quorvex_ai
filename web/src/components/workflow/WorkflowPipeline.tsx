'use client';

import React from 'react';
import Link from 'next/link';
import { pipelineNodes } from '@/lib/workflow';
import { WorkflowProgress } from '@/hooks/useWorkflowProgress';
import { ArrowRight } from 'lucide-react';

export type HealthStatus = 'good' | 'warning' | 'critical' | 'inactive';

interface Props {
    progress: WorkflowProgress | null;
    healthStatus?: Record<string, HealthStatus>;
}

function getCountForNode(nodeId: string, progress: WorkflowProgress | null): string {
    if (!progress) return '0';
    switch (nodeId) {
        case 'exploration': return String(progress.explorations);
        case 'requirements': return String(progress.requirements);
        case 'rtm': return progress.rtmCoverage != null ? `${Math.round(progress.rtmCoverage)}%` : '\u2014';
        case 'specs': return String(progress.specs);
        case 'runs': return String(progress.runs);
        case 'analytics': return progress.successRate > 0 ? `${Math.round(progress.successRate)}%` : '\u2014';
        default: return '0';
    }
}

function getCountLabel(nodeId: string): string {
    switch (nodeId) {
        case 'exploration': return 'sessions';
        case 'requirements': return 'total';
        case 'rtm': return 'coverage';
        case 'specs': return 'total';
        case 'runs': return 'total';
        case 'analytics': return 'pass rate';
        default: return '';
    }
}

function isNodeActive(nodeId: string, progress: WorkflowProgress | null): boolean {
    if (!progress) return false;
    switch (nodeId) {
        case 'exploration': return progress.explorations > 0;
        case 'requirements': return progress.requirements > 0;
        case 'rtm': return progress.rtmCoverage != null && progress.rtmCoverage > 0;
        case 'specs': return progress.specs > 0;
        case 'runs': return progress.runs > 0;
        case 'analytics': return progress.runs > 0;
        default: return false;
    }
}

const STATUS_DOT_COLORS: Record<HealthStatus, string> = {
    good: '#10b981',
    warning: '#f59e0b',
    critical: '#ef4444',
    inactive: 'var(--text-secondary)',
};

export function WorkflowPipeline({ progress, healthStatus }: Props) {
    return (
        <div style={{
            display: 'flex',
            alignItems: 'center',
            gap: '0.5rem',
            overflowX: 'auto',
            padding: '1rem 0.75rem',
            background: 'var(--background-raised)',
            border: '1px solid var(--border-subtle)',
            borderRadius: 'var(--radius-lg)',
        }}>
            {pipelineNodes.map((node, index) => {
                const active = isNodeActive(node.id, progress);
                const count = getCountForNode(node.id, progress);
                const Icon = node.icon;
                const status = healthStatus?.[node.id] ?? (active ? 'good' : 'inactive');
                const dotColor = STATUS_DOT_COLORS[status];
                const nextNode = index < pipelineNodes.length - 1 ? pipelineNodes[index + 1] : null;

                return (
                    <React.Fragment key={node.id}>
                        <Link
                            href={node.href}
                            className={`animate-in stagger-${index + 1}`}
                            style={{
                                display: 'flex',
                                flexDirection: 'column',
                                alignItems: 'center',
                                gap: '0.4rem',
                                padding: '0.75rem 1rem',
                                borderRadius: 'var(--radius)',
                                border: '1px solid',
                                borderColor: active ? `${node.color}30` : 'var(--border-subtle)',
                                background: active
                                    ? `linear-gradient(145deg, ${node.color}10, ${node.color}08, transparent)`
                                    : 'var(--surface)',
                                opacity: active ? 1 : 0.55,
                                textDecoration: 'none',
                                color: 'inherit',
                                minWidth: '90px',
                                transition: 'all 0.25s var(--ease-smooth)',
                                flex: '1 1 0',
                                position: 'relative',
                            }}
                            onMouseOver={e => {
                                e.currentTarget.style.borderColor = `${node.color}60`;
                                e.currentTarget.style.opacity = '1';
                                e.currentTarget.style.transform = 'translateY(-3px)';
                                e.currentTarget.style.boxShadow = `0 8px 25px ${node.color}15`;
                            }}
                            onMouseOut={e => {
                                e.currentTarget.style.borderColor = active ? `${node.color}30` : 'var(--border-subtle)';
                                e.currentTarget.style.opacity = active ? '1' : '0.55';
                                e.currentTarget.style.transform = 'translateY(0)';
                                e.currentTarget.style.boxShadow = 'none';
                            }}
                        >
                            {/* Health status dot */}
                            <div style={{
                                position: 'absolute',
                                top: '0.4rem',
                                right: '0.4rem',
                                width: '8px',
                                height: '8px',
                                borderRadius: '50%',
                                background: dotColor,
                                boxShadow: status !== 'inactive' ? `0 0 6px ${dotColor}90` : 'none',
                                animation: status !== 'inactive' ? 'dotPulse 2s ease-in-out infinite' : 'none',
                            }} />

                            <div style={{
                                display: 'flex',
                                alignItems: 'center',
                                gap: '0.4rem',
                            }}>
                                <Icon size={15} style={{ color: active ? node.color : 'var(--text-secondary)' }} />
                                <span style={{
                                    fontSize: '0.75rem',
                                    fontWeight: 600,
                                    letterSpacing: '-0.01em',
                                    color: active ? 'var(--text)' : 'var(--text-secondary)',
                                    whiteSpace: 'nowrap',
                                }}>
                                    {node.shortLabel}
                                </span>
                            </div>
                            <div style={{ textAlign: 'center' }}>
                                <span style={{
                                    fontSize: '1.3rem',
                                    fontWeight: 800,
                                    letterSpacing: '-0.02em',
                                    color: active ? node.color : 'var(--text-secondary)',
                                }}>
                                    {count}
                                </span>
                                <span style={{
                                    display: 'block',
                                    fontSize: '0.6rem',
                                    textTransform: 'uppercase',
                                    letterSpacing: '0.08em',
                                    color: 'var(--text-tertiary)',
                                    marginTop: '0.1rem',
                                }}>
                                    {getCountLabel(node.id)}
                                </span>
                            </div>
                        </Link>

                        {index < pipelineNodes.length - 1 && (
                            <div style={{
                                display: 'flex',
                                alignItems: 'center',
                                flexShrink: 0,
                                position: 'relative',
                            }}>
                                <div style={{
                                    width: '20px',
                                    height: '2px',
                                    background: `linear-gradient(90deg, ${node.color}40, ${nextNode!.color}40)`,
                                    borderRadius: '1px',
                                }} />
                                <ArrowRight
                                    size={12}
                                    style={{
                                        color: 'var(--text-secondary)',
                                        opacity: 0.15,
                                        position: 'absolute',
                                        right: '-4px',
                                    }}
                                />
                            </div>
                        )}
                    </React.Fragment>
                );
            })}
        </div>
    );
}
