'use client';

import type { ReactNode } from 'react';

interface EmptyStateProps {
    icon: ReactNode;
    title: string;
    description?: string;
    action?: ReactNode;
    className?: string;
}

/**
 * Reusable empty state component for zero-data views.
 * Uses the .empty-state CSS class for consistent centering and spacing.
 */
export function EmptyState({
    icon,
    title,
    description,
    action,
    className = '',
}: EmptyStateProps) {
    return (
        <div className={`card-elevated animate-in stagger-3 ${className}`}>
            <div className="empty-state">
                <div className="empty-icon">{icon}</div>
                <h3>{title}</h3>
                {description && <p>{description}</p>}
                {action && <div style={{ marginTop: '0.75rem' }}>{action}</div>}
            </div>
        </div>
    );
}
