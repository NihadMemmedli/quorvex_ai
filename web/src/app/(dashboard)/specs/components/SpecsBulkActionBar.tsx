'use client';

import * as React from 'react';
import { CheckCircle, X } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';

export type SpecsBulkActionVariant = 'primary' | 'secondary' | 'success' | 'danger' | 'accent';

export interface SpecsBulkAction {
    id: string;
    label: string;
    onClick: () => void;
    icon?: React.ReactNode;
    variant?: SpecsBulkActionVariant;
    disabled?: boolean;
    hidden?: boolean;
    title?: string;
}

export interface SpecsBulkActionBarProps {
    selectedCount: number;
    selectedAutomatedCount?: number;
    onClear: () => void;
    actions: SpecsBulkAction[];
    label?: string;
    disabled?: boolean;
    className?: string;
    style?: React.CSSProperties;
}

const variantStyle: Record<SpecsBulkActionVariant, React.CSSProperties> = {
    primary: {
        background: 'var(--primary)',
        color: '#fff',
        border: '1px solid transparent',
    },
    secondary: {
        background: 'transparent',
        color: 'var(--text)',
        border: '1px solid var(--border)',
    },
    success: {
        background: 'var(--success)',
        color: '#fff',
        border: '1px solid transparent',
    },
    danger: {
        background: 'var(--danger)',
        color: '#fff',
        border: '1px solid transparent',
    },
    accent: {
        background: 'var(--accent)',
        color: '#fff',
        border: '1px solid transparent',
    },
};

const barStyle: React.CSSProperties = {
    position: 'fixed',
    left: '50%',
    bottom: '2rem',
    transform: 'translateX(-50%)',
    zIndex: 100,
    width: 'fit-content',
    maxWidth: 'calc(100vw - 2rem)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    gap: '1.25rem',
    padding: '1rem 1.25rem',
    border: '1px solid var(--primary)',
    borderRadius: '12px',
    background: 'var(--surface)',
    boxShadow: '0 20px 25px -5px rgba(0, 0, 0, 0.3)',
    animation: 'slideUp 0.3s ease-out',
};

const actionButtonStyle: React.CSSProperties = {
    minHeight: 40,
    padding: '0.625rem 1rem',
    borderRadius: '10px',
    fontSize: '0.875rem',
    fontWeight: 650,
    lineHeight: 1,
    gap: '0.5rem',
    boxShadow: '0 8px 18px rgba(0, 0, 0, 0.14)',
};

const clearButtonStyle: React.CSSProperties = {
    ...actionButtonStyle,
    minWidth: 120,
    color: 'var(--text)',
    background: 'rgba(148, 163, 184, 0.08)',
    border: '1px solid var(--border)',
    boxShadow: 'none',
};

export function SpecsBulkActionBar({
    selectedCount,
    selectedAutomatedCount = 0,
    onClear,
    actions,
    label = 'Specs selected',
    disabled = false,
    className,
    style,
}: SpecsBulkActionBarProps) {
    const visibleActions = actions.filter(action => !action.hidden);

    if (selectedCount <= 0) return null;

    return (
        <>
            <aside
                className={['specs-bulk-action-bar', className].filter(Boolean).join(' ')}
                data-testid="specs-bulk-action-bar"
                style={{ ...barStyle, ...style }}
                aria-label="Bulk spec actions"
                aria-live="polite"
            >
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.875rem', minWidth: 0 }}>
                    <Badge
                        variant="default"
                        style={{
                            minWidth: '2rem',
                            justifyContent: 'center',
                            borderRadius: '6px',
                            padding: '0.2rem 0.6rem',
                            fontSize: '0.9rem',
                            fontWeight: 700,
                        }}
                    >
                        {selectedCount}
                    </Badge>
                    <strong style={{ color: 'var(--text)', fontSize: '0.9rem', whiteSpace: 'nowrap', fontWeight: 600 }}>
                        {label}
                    </strong>
                    {selectedAutomatedCount > 0 && (
                        <span
                            style={{
                                display: 'inline-flex',
                                alignItems: 'center',
                                gap: '0.35rem',
                                color: 'var(--success)',
                                fontSize: '0.9rem',
                                fontWeight: 600,
                                whiteSpace: 'nowrap',
                            }}
                        >
                            <CheckCircle size={13} />
                            ({selectedAutomatedCount} automated)
                        </span>
                    )}
                </div>

                <div style={{ height: '24px', width: '1px', background: 'var(--border)', flexShrink: 0, margin: '0 0.25rem' }} />

                <div
                    style={{
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'flex-end',
                        gap: '0.75rem',
                        minWidth: 0,
                    }}
                >
                    <Button
                        type="button"
                        variant="secondary"
                        size="sm"
                        onClick={onClear}
                        disabled={disabled}
                        title="Clear selection"
                        style={clearButtonStyle}
                    >
                        <X size={15} />
                        Clear
                    </Button>

                    {visibleActions.map(action => {
                        const variant = action.variant ?? 'primary';
                        return (
                            <Button
                                key={action.id}
                                type="button"
                                size="sm"
                                onClick={action.onClick}
                                disabled={disabled || action.disabled}
                                title={action.title ?? action.label}
                                style={{
                                    ...actionButtonStyle,
                                    ...variantStyle[variant],
                                    display: 'flex',
                                    alignItems: 'center',
                                }}
                            >
                                {action.icon}
                                {action.label}
                            </Button>
                        );
                    })}
                </div>
            </aside>

            <style jsx>{`
                :global(.specs-bulk-action-bar) {
                    flex-wrap: nowrap;
                }

                @media (max-width: 760px) {
                    :global(.specs-bulk-action-bar) {
                        align-items: flex-start !important;
                        flex-wrap: wrap;
                        gap: 0.75rem !important;
                        padding: 1rem !important;
                    }
                }
            `}</style>
        </>
    );
}
