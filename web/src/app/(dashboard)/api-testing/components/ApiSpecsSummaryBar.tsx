'use client';
import React from 'react';
import { FileCode, CheckCircle, XCircle, BarChart2 } from 'lucide-react';
import { ApiSpecsSummary, ApiSpecStatusFilter } from './types';

interface ApiSpecsSummaryBarProps {
    summary: ApiSpecsSummary | null;
    activeFilter: ApiSpecStatusFilter;
    onFilterChange: (filter: ApiSpecStatusFilter) => void;
}

const cards = [
    { key: 'all' as ApiSpecStatusFilter, label: 'Total Specs', icon: FileCode, color: 'var(--text-primary)', getValue: (s: ApiSpecsSummary) => String(s.total_specs) },
    { key: 'passed' as ApiSpecStatusFilter, label: 'Passed', icon: CheckCircle, color: 'var(--success)', getValue: (s: ApiSpecsSummary) => String(s.passed) },
    { key: 'failed' as ApiSpecStatusFilter, label: 'Failed', icon: XCircle, color: 'var(--danger)', getValue: (s: ApiSpecsSummary) => String(s.failed) },
    { key: null, label: 'Coverage', icon: BarChart2, color: 'var(--primary)', getValue: (s: ApiSpecsSummary) => (s.coverage_pct ?? 0) + '%' },
] as const;

export default function ApiSpecsSummaryBar({ summary, activeFilter, onFilterChange }: ApiSpecsSummaryBarProps) {
    if (!summary) return null;

    return (
        <div style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(4, 1fr)',
            gap: '0.75rem',
            marginBottom: '1rem',
        }}>
            {cards.map((card, idx) => {
                const Icon = card.icon;
                const isClickable = card.key !== null;
                const isActive = isClickable && activeFilter === card.key;

                return (
                    <div
                        key={idx}
                        onClick={() => isClickable && onFilterChange(card.key!)}
                        style={{
                            padding: '0.75rem 1rem',
                            background: 'var(--surface)',
                            border: '1px solid var(--border)',
                            borderRadius: 'var(--radius)',
                            borderLeft: isActive ? `3px solid ${card.color}` : '1px solid var(--border)',
                            cursor: isClickable ? 'pointer' : 'default',
                            display: 'flex',
                            alignItems: 'center',
                            gap: '0.75rem',
                            transition: 'all 0.15s var(--ease-smooth)',
                            boxShadow: 'var(--shadow-card)',
                        }}
                    >
                        <Icon size={20} style={{ color: card.color, flexShrink: 0 }} />
                        <div>
                            <div style={{
                                fontSize: '1.25rem',
                                fontWeight: 700,
                                color: 'var(--text-primary)',
                                lineHeight: 1.2,
                            }}>
                                {card.getValue(summary)}
                            </div>
                            <div style={{
                                fontSize: '0.7rem',
                                color: 'var(--text-secondary)',
                                marginTop: '0.1rem',
                            }}>
                                {card.label}
                            </div>
                        </div>
                    </div>
                );
            })}
        </div>
    );
}
