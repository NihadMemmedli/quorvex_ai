'use client';

import React from 'react';
import { WorkflowProgress } from '@/hooks/useWorkflowProgress';

interface Props {
    progress: WorkflowProgress | null;
}

export function WorkflowProgressSummary({ progress }: Props) {
    if (!progress) return null;

    const items = [
        { label: 'explorations', value: progress.explorations },
        { label: 'requirements', value: progress.requirements },
        { label: 'RTM coverage', value: progress.rtmCoverage != null ? `${Math.round(progress.rtmCoverage)}%` : '—' },
        { label: 'specs', value: progress.specs },
        { label: 'runs', value: progress.runs },
        { label: 'pass rate', value: progress.successRate > 0 ? `${Math.round(progress.successRate)}%` : '—' },
    ];

    return (
        <div style={{
            display: 'flex',
            alignItems: 'center',
            gap: '0.5rem',
            flexWrap: 'wrap',
            padding: '0.5rem 0',
            fontSize: '0.8rem',
            color: 'var(--text-secondary)',
        }}>
            {items.map((item, i) => (
                <React.Fragment key={item.label}>
                    <span>
                        <strong style={{ color: 'var(--text)', fontWeight: 600 }}>{item.value}</strong>
                        {' '}{item.label}
                    </span>
                    {i < items.length - 1 && (
                        <span style={{ opacity: 0.3 }}>|</span>
                    )}
                </React.Fragment>
            ))}
        </div>
    );
}
