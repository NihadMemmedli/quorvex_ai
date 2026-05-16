import { ExternalLink } from 'lucide-react';
import Link from 'next/link';
import type { QualityGate } from './types';
import { QualityGateStatusBadge } from './QualityGateStatusBadge';

interface QualityGateCardProps {
    gate: QualityGate;
    selected?: boolean;
    onSelect: (gate: QualityGate) => void;
}

export function QualityGateCard({ gate, selected = false, onSelect }: QualityGateCardProps) {
    const state = gate.quality_gate?.state || 'unknown';
    const batch = gate.quality_gate?.batch;

    return (
        <div
            role="button"
            tabIndex={0}
            onClick={() => onSelect(gate)}
            onKeyDown={e => {
                if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    onSelect(gate);
                }
            }}
            style={{
                border: selected ? '1px solid var(--primary)' : '1px solid var(--border)',
                borderRadius: 'var(--radius)',
                background: selected ? 'rgba(59, 130, 246, 0.08)' : 'var(--background)',
                padding: '0.9rem',
                minWidth: 0,
                cursor: 'pointer',
                color: 'var(--text)',
                textAlign: 'left',
                boxShadow: selected ? '0 0 0 1px color-mix(in srgb, var(--primary) 35%, transparent)' : 'none',
                outline: 'none',
            }}
        >
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: '0.75rem', alignItems: 'flex-start' }}>
                <div style={{ minWidth: 0 }}>
                    <div style={{ fontWeight: 750, fontSize: '0.9rem', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        PR #{gate.pr_number}: {gate.title || 'Untitled'}
                    </div>
                    <div style={{ marginTop: '0.25rem', color: 'var(--text-secondary)', fontSize: '0.76rem', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {gate.owner}/{gate.repo} · {gate.head_ref || 'head'} → {gate.base_ref || 'base'}
                    </div>
                </div>
                <QualityGateStatusBadge state={state} />
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '0.45rem', marginTop: '0.85rem' }}>
                {[
                    ['Risk', gate.risk_level],
                    ['Selected', `${gate.selected_tests_count}/${gate.total_candidate_tests}`],
                    ['Skipped', String(gate.saved_tests_count ?? 0)],
                ].map(([label, value]) => (
                    <div key={label} style={{ border: '1px solid var(--border)', borderRadius: 'var(--radius)', padding: '0.5rem' }}>
                        <div style={{ color: 'var(--text-secondary)', fontSize: '0.68rem' }}>{label}</div>
                        <div style={{ marginTop: '0.2rem', fontWeight: 750, fontSize: '0.82rem', textTransform: label === 'Risk' ? 'capitalize' : undefined }}>{value}</div>
                    </div>
                ))}
            </div>

            {batch && (
                <div style={{ marginTop: '0.7rem', color: 'var(--text-secondary)', fontSize: '0.78rem' }}>
                    Batch: {batch.passed}/{batch.total_tests} passed
                    {batch.failed > 0 ? <span style={{ color: 'var(--danger)' }}> · {batch.failed} failed</span> : null}
                    {(batch.running > 0 || batch.queued > 0) ? ` · ${batch.running + batch.queued} active` : ''}
                </div>
            )}

            <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap', marginTop: '0.75rem' }}>
                {gate.batch_id && (
                    <Link
                        href={`/regression/batches/${gate.batch_id}`}
                        onClick={e => e.stopPropagation()}
                        style={{
                            display: 'inline-flex',
                            alignItems: 'center',
                            gap: '0.3rem',
                            color: 'var(--primary)',
                            textDecoration: 'none',
                            fontSize: '0.78rem',
                            fontWeight: 700,
                        }}
                    >
                        View Batch <ExternalLink size={12} />
                    </Link>
                )}
                <Link
                    href={`/pr-advisor?analysis=${encodeURIComponent(gate.id)}`}
                    onClick={e => e.stopPropagation()}
                    style={{
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: '0.3rem',
                        color: 'var(--text-secondary)',
                        textDecoration: 'none',
                        fontSize: '0.78rem',
                        fontWeight: 700,
                    }}
                >
                    Open PR Advisor <ExternalLink size={12} />
                </Link>
            </div>
        </div>
    );
}
