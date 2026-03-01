'use client';
import React, { useState } from 'react';

interface AssertionsListProps {
    assertions: any[];
}

const layerColors: Record<string, { bg: string; border: string; label: string }> = {
    deterministic: { bg: 'rgba(59,130,246,0.08)', border: 'var(--primary)', label: 'Assertions' },
    deepeval: { bg: 'rgba(168,85,247,0.08)', border: 'var(--accent)', label: 'DeepEval' },
    judge: { bg: 'rgba(245,158,11,0.08)', border: 'var(--warning)', label: 'LLM Judge' },
};

export default React.memo(function AssertionsList({ assertions }: AssertionsListProps) {
    const [expandedIdx, setExpandedIdx] = useState<number | null>(null);

    // Group by category
    const deterministic = assertions.filter((a: any) => a.category === 'deterministic');
    const deepeval = assertions.filter((a: any) => a.category === 'deepeval');
    const judge = assertions.filter((a: any) => a.category === 'judge');

    const renderGroup = (items: any[], category: string) => {
        if (items.length === 0) return null;
        const layer = layerColors[category];
        return (
            <div key={category} style={{ marginTop: '0.5rem' }}>
                <div style={{ fontSize: '0.7rem', fontWeight: 600, color: layer.border, textTransform: 'uppercase', marginBottom: '0.2rem' }}>
                    {layer.label}
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.2rem' }}>
                    {items.map((a: any, i: number) => {
                        const globalIdx = assertions.indexOf(a);
                        const isExpanded = expandedIdx === globalIdx;
                        const hasDetail = a.explanation || a.score !== null;
                        return (
                            <div
                                key={i}
                                onClick={() => hasDetail ? setExpandedIdx(isExpanded ? null : globalIdx) : undefined}
                                style={{
                                    fontSize: '0.8rem',
                                    padding: '0.3rem 0.5rem',
                                    borderRadius: 4,
                                    background: a.passed ? 'rgba(34,197,94,0.08)' : 'rgba(239,68,68,0.08)',
                                    borderLeft: `3px solid ${a.passed ? 'var(--success)' : 'var(--danger)'}`,
                                    cursor: hasDetail ? 'pointer' : 'default',
                                }}
                            >
                                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                                    <span>
                                        <span style={{ color: a.passed ? 'var(--success)' : 'var(--danger)', fontWeight: 600, marginRight: '0.4rem' }}>
                                            {a.passed ? 'PASS' : 'FAIL'}
                                        </span>
                                        {a.name}
                                    </span>
                                    <span style={{ display: 'flex', gap: '0.4rem', alignItems: 'center' }}>
                                        {a.score !== null && a.score !== undefined && (
                                            <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
                                                score: {typeof a.score === 'number' ? a.score.toFixed(1) : a.score}
                                            </span>
                                        )}
                                        {hasDetail && (
                                            <span style={{ fontSize: '0.7rem', color: 'var(--text-secondary)' }}>{isExpanded ? '[-]' : '[+]'}</span>
                                        )}
                                    </span>
                                </div>
                                {isExpanded && a.explanation && (
                                    <div style={{
                                        marginTop: '0.3rem', paddingTop: '0.3rem',
                                        borderTop: '1px solid var(--border)',
                                        fontSize: '0.78rem', color: 'var(--text-secondary)', lineHeight: 1.4,
                                    }}>
                                        {a.explanation}
                                    </div>
                                )}
                            </div>
                        );
                    })}
                </div>
            </div>
        );
    };

    return (
        <div>
            {renderGroup(deterministic, 'deterministic')}
            {renderGroup(deepeval, 'deepeval')}
            {renderGroup(judge, 'judge')}
        </div>
    );
});
