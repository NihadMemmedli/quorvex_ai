'use client';

import type { ReactNode } from 'react';

interface PageHeaderProps {
    title: string;
    subtitle?: string;
    gradient?: boolean;
    icon?: ReactNode;
    actions?: ReactNode;
    breadcrumb?: ReactNode;
    className?: string;
}

/**
 * Standardized page header with optional gradient title, icon, and action buttons.
 * Uses the .page-header CSS class for consistent bottom border and spacing.
 */
export function PageHeader({
    title,
    subtitle,
    gradient = true,
    icon,
    actions,
    breadcrumb,
    className = '',
}: PageHeaderProps) {
    return (
        <>
            {breadcrumb && (
                <div className="animate-in" style={{ marginBottom: '0.75rem' }}>
                    {breadcrumb}
                </div>
            )}
            <header className={`page-header animate-in stagger-1 ${className}`}>
                <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: '1rem' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                        {icon && (
                            <div style={{
                                width: '40px',
                                height: '40px',
                                borderRadius: 'var(--radius)',
                                display: 'flex',
                                alignItems: 'center',
                                justifyContent: 'center',
                                background: 'var(--primary-glow)',
                                color: 'var(--primary)',
                                flexShrink: 0,
                            }}>
                                {icon}
                            </div>
                        )}
                        <div>
                            <h1>
                                {gradient ? (
                                    <span className="gradient-text">{title}</span>
                                ) : (
                                    title
                                )}
                            </h1>
                            {subtitle && <p>{subtitle}</p>}
                        </div>
                    </div>
                    {actions && (
                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexShrink: 0 }}>
                            {actions}
                        </div>
                    )}
                </div>
            </header>
        </>
    );
}
