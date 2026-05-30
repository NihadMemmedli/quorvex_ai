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
        border: 'none',
    },
    secondary: {
        background: 'var(--surface)',
        color: 'var(--text)',
        border: '1px solid var(--border)',
    },
    success: {
        background: 'var(--success)',
        color: '#fff',
        border: 'none',
    },
    danger: {
        background: 'var(--danger)',
        color: '#fff',
        border: 'none',
    },
    accent: {
        background: 'var(--accent)',
        color: '#fff',
        border: 'none',
    },
};

const barStyle: React.CSSProperties = {
    position: 'fixed',
    left: '50%',
    bottom: 'max(1rem, env(safe-area-inset-bottom))',
    transform: 'translateX(-50%)',
    zIndex: 100,
    width: 'min(calc(100vw - 2rem), 980px)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    flexWrap: 'wrap',
    gap: '0.75rem',
    padding: '0.75rem',
    border: '1px solid var(--primary)',
    borderRadius: '8px',
    background: 'var(--surface)',
    boxShadow: '0 20px 35px rgba(0, 0, 0, 0.28)',
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
        <aside
            className={className}
            style={{ ...barStyle, ...style }}
            aria-label="Bulk spec actions"
            aria-live="polite"
        >
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', minWidth: 0 }}>
                <Badge
                    variant="default"
                    style={{
                        minWidth: '2rem',
                        justifyContent: 'center',
                        borderRadius: '6px',
                        padding: '0.3rem 0.55rem',
                        fontSize: '0.85rem',
                    }}
                >
                    {selectedCount}
                </Badge>
                <div style={{ display: 'grid', gap: '0.2rem', minWidth: 0 }}>
                    <strong style={{ color: 'var(--text)', fontSize: '0.9rem', whiteSpace: 'nowrap' }}>
                        {label}
                    </strong>
                    {selectedAutomatedCount > 0 && (
                        <span
                            style={{
                                display: 'inline-flex',
                                alignItems: 'center',
                                gap: '0.35rem',
                                color: 'var(--success)',
                                fontSize: '0.78rem',
                                whiteSpace: 'nowrap',
                            }}
                        >
                            <CheckCircle size={13} />
                            {selectedAutomatedCount} automated
                        </span>
                    )}
                </div>
            </div>

            <div
                style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'flex-end',
                    gap: '0.5rem',
                    flexWrap: 'wrap',
                }}
            >
                <Button
                    type="button"
                    variant="secondary"
                    size="sm"
                    onClick={onClear}
                    disabled={disabled}
                    title="Clear selection"
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
                            style={variantStyle[variant]}
                        >
                            {action.icon}
                            {action.label}
                        </Button>
                    );
                })}
            </div>
        </aside>
    );
}
