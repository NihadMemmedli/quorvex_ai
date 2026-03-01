'use client';

import React from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { pipelineNodes, getNodeForPath } from '@/lib/workflow';

export function WorkflowBreadcrumb() {
    const pathname = usePathname();
    const currentNodeId = getNodeForPath(pathname);

    if (!currentNodeId) return null;

    const currentIndex = pipelineNodes.findIndex(n => n.id === currentNodeId);

    return (
        <div style={{
            display: 'flex',
            alignItems: 'center',
            gap: '0.35rem',
            marginBottom: '1rem',
        }}>
            {pipelineNodes.map((node, index) => {
                const isCurrent = node.id === currentNodeId;
                const isPast = index < currentIndex;

                return (
                    <React.Fragment key={node.id}>
                        <Link
                            href={node.href}
                            title={node.label}
                            style={{
                                display: 'flex',
                                alignItems: 'center',
                                gap: '0.3rem',
                                padding: '0.2rem 0.5rem',
                                borderRadius: '4px',
                                fontSize: '0.7rem',
                                fontWeight: isCurrent ? 600 : 400,
                                color: isCurrent ? node.color : isPast ? 'var(--text-secondary)' : 'var(--text-secondary)',
                                background: isCurrent ? `${node.color}15` : 'transparent',
                                textDecoration: 'none',
                                opacity: isCurrent ? 1 : isPast ? 0.8 : 0.4,
                                transition: 'opacity 0.15s',
                                whiteSpace: 'nowrap',
                            }}
                            onMouseOver={e => { e.currentTarget.style.opacity = '1'; }}
                            onMouseOut={e => { e.currentTarget.style.opacity = isCurrent ? '1' : isPast ? '0.8' : '0.4'; }}
                        >
                            <node.icon size={12} />
                            {node.shortLabel}
                        </Link>
                        {index < pipelineNodes.length - 1 && (
                            <span style={{
                                color: 'var(--text-secondary)',
                                opacity: 0.2,
                                fontSize: '0.7rem',
                            }}>
                                &rsaquo;
                            </span>
                        )}
                    </React.Fragment>
                );
            })}
        </div>
    );
}
