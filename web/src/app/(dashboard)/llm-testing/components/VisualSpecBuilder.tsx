'use client';
import { useState, useEffect, useCallback } from 'react';
import { inputStyle, btnPrimary, btnSecondary, cardStyleCompact } from '@/lib/styles';
import { markdownToVisualSpec, visualSpecToMarkdown } from './specConverter';
import { toast } from 'sonner';
import { ConfirmDialog } from '@/components/ui/confirm-dialog';
import type { VisualSpec, VisualTestCase, VisualAssertion } from './specConverter';

const ASSERTION_TYPES = [
    'contains', 'not-contains', 'regex', 'json-valid',
    'latency-ms', 'max-tokens', 'cost-max',
    'min-length', 'max-length',
];

interface VisualSpecBuilderProps {
    content: string;
    onChange: (md: string) => void;
}

export default function VisualSpecBuilder({ content, onChange }: VisualSpecBuilderProps) {
    const [spec, setSpec] = useState<VisualSpec>(() => markdownToVisualSpec(content));
    const [collapsedCases, setCollapsedCases] = useState<Set<string>>(new Set());
    const [confirmRemove, setConfirmRemove] = useState<{ open: boolean; index: number; name: string }>({ open: false, index: -1, name: '' });

    // Re-parse when content changes externally
    useEffect(() => {
        setSpec(markdownToVisualSpec(content));
    }, [content]);

    const emitChange = useCallback((updated: VisualSpec) => {
        setSpec(updated);
        onChange(visualSpecToMarkdown(updated));
    }, [onChange]);

    const updateField = (field: keyof VisualSpec, value: any) => {
        emitChange({ ...spec, [field]: value });
    };

    const updateDefault = (key: string, value: any) => {
        emitChange({ ...spec, defaults: { ...spec.defaults, [key]: value } });
    };

    const updateTestCase = (index: number, updates: Partial<VisualTestCase>) => {
        const cases = [...spec.testCases];
        cases[index] = { ...cases[index], ...updates };
        emitChange({ ...spec, testCases: cases });
    };

    const addTestCase = () => {
        const nextNum = spec.testCases.length + 1;
        const id = `TC-${String(nextNum).padStart(3, '0')}`;
        const newCase: VisualTestCase = {
            id,
            name: 'New Test Case',
            inputPrompt: '',
            expectedOutput: '',
            context: [],
            assertions: [],
            metrics: {},
        };
        emitChange({ ...spec, testCases: [...spec.testCases, newCase] });
    };

    const removeTestCase = (index: number) => {
        const cases = spec.testCases.filter((_, i) => i !== index);
        emitChange({ ...spec, testCases: cases });
        toast.success('Test case removed');
    };

    const addAssertion = (caseIndex: number) => {
        const cases = [...spec.testCases];
        cases[caseIndex] = {
            ...cases[caseIndex],
            assertions: [...cases[caseIndex].assertions, { type: 'contains', value: '' }],
        };
        emitChange({ ...spec, testCases: cases });
    };

    const updateAssertion = (caseIndex: number, assertIndex: number, updates: Partial<VisualAssertion>) => {
        const cases = [...spec.testCases];
        const assertions = [...cases[caseIndex].assertions];
        assertions[assertIndex] = { ...assertions[assertIndex], ...updates };
        cases[caseIndex] = { ...cases[caseIndex], assertions };
        emitChange({ ...spec, testCases: cases });
    };

    const removeAssertion = (caseIndex: number, assertIndex: number) => {
        const cases = [...spec.testCases];
        cases[caseIndex] = {
            ...cases[caseIndex],
            assertions: cases[caseIndex].assertions.filter((_, i) => i !== assertIndex),
        };
        emitChange({ ...spec, testCases: cases });
    };

    const toggleCollapse = (id: string) => {
        setCollapsedCases(prev => {
            const next = new Set(prev);
            if (next.has(id)) next.delete(id);
            else next.add(id);
            return next;
        });
    };

    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
            {/* Suite Metadata */}
            <div style={cardStyleCompact}>
                <label style={labelSm}>Suite Name</label>
                <input
                    value={spec.name}
                    onChange={e => updateField('name', e.target.value)}
                    style={inputStyle}
                    placeholder="My Test Suite"
                />
                <label style={{ ...labelSm, marginTop: '0.75rem' }}>Description</label>
                <textarea
                    value={spec.description}
                    onChange={e => updateField('description', e.target.value)}
                    style={{ ...inputStyle, height: 60, fontFamily: 'inherit' }}
                    placeholder="What does this test suite validate?"
                />
                <label style={{ ...labelSm, marginTop: '0.75rem' }}>System Prompt</label>
                <textarea
                    value={spec.systemPrompt}
                    onChange={e => updateField('systemPrompt', e.target.value)}
                    style={{ ...inputStyle, height: 80, fontFamily: 'monospace', fontSize: '0.85rem' }}
                    placeholder="You are a helpful assistant..."
                />
            </div>

            {/* Defaults */}
            <div style={cardStyleCompact}>
                <div style={{ fontWeight: 600, fontSize: '0.9rem', marginBottom: '0.5rem' }}>Defaults</div>
                <div style={{ display: 'flex', gap: '1.5rem', alignItems: 'center', flexWrap: 'wrap' }}>
                    <div>
                        <label style={labelSm}>Temperature: {spec.defaults.temperature ?? 0.7}</label>
                        <input
                            type="range"
                            min={0}
                            max={2}
                            step={0.1}
                            value={spec.defaults.temperature ?? 0.7}
                            onChange={e => updateDefault('temperature', parseFloat(e.target.value))}
                            style={{ width: 180 }}
                        />
                    </div>
                    <div>
                        <label style={labelSm}>Max Tokens</label>
                        <input
                            type="number"
                            value={spec.defaults.max_tokens ?? 1024}
                            onChange={e => updateDefault('max_tokens', parseInt(e.target.value) || 1024)}
                            style={{ ...inputStyle, width: 120 }}
                        />
                    </div>
                </div>
            </div>

            {/* Test Cases */}
            <div style={{ fontWeight: 600, fontSize: '0.95rem' }}>
                Test Cases ({spec.testCases.length})
            </div>

            {spec.testCases.map((tc, ci) => {
                const isCollapsed = collapsedCases.has(tc.id);
                return (
                    <div key={tc.id} style={{ ...cardStyleCompact, position: 'relative' }}>
                        <div
                            style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', cursor: 'pointer' }}
                            onClick={() => toggleCollapse(tc.id)}
                        >
                            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                                <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', userSelect: 'none' }}>
                                    {isCollapsed ? '\u25B6' : '\u25BC'}
                                </span>
                                <span style={{ fontWeight: 600, fontSize: '0.9rem' }}>{tc.id}: {tc.name}</span>
                                <span style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                                    ({tc.assertions.length} assertion{tc.assertions.length !== 1 ? 's' : ''})
                                </span>
                            </div>
                            <button
                                onClick={e => {
                                    e.stopPropagation();
                                    setConfirmRemove({ open: true, index: ci, name: spec.testCases[ci].name });
                                }}
                                style={{ background: 'none', border: 'none', color: 'var(--danger)', cursor: 'pointer', fontSize: '0.85rem', fontWeight: 600 }}
                            >
                                Remove
                            </button>
                        </div>

                        {!isCollapsed && (
                            <div style={{ marginTop: '0.75rem', display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                                <div style={{ display: 'flex', gap: '0.75rem' }}>
                                    <div style={{ width: 100, flexShrink: 0 }}>
                                        <label style={labelSm}>ID</label>
                                        <input
                                            value={tc.id}
                                            onChange={e => updateTestCase(ci, { id: e.target.value })}
                                            style={{ ...inputStyle, fontFamily: 'monospace', fontSize: '0.85rem' }}
                                        />
                                    </div>
                                    <div style={{ flex: 1 }}>
                                        <label style={labelSm}>Name</label>
                                        <input
                                            value={tc.name}
                                            onChange={e => updateTestCase(ci, { name: e.target.value })}
                                            style={inputStyle}
                                        />
                                    </div>
                                </div>

                                <div>
                                    <label style={labelSm}>Input Prompt</label>
                                    <textarea
                                        value={tc.inputPrompt}
                                        onChange={e => updateTestCase(ci, { inputPrompt: e.target.value })}
                                        style={{ ...inputStyle, height: 60, fontFamily: 'monospace', fontSize: '0.85rem' }}
                                    />
                                </div>

                                <div>
                                    <label style={labelSm}>Expected Output</label>
                                    <textarea
                                        value={tc.expectedOutput}
                                        onChange={e => updateTestCase(ci, { expectedOutput: e.target.value })}
                                        style={{ ...inputStyle, height: 60, fontFamily: 'monospace', fontSize: '0.85rem' }}
                                    />
                                </div>

                                {/* Assertions */}
                                <div>
                                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.25rem' }}>
                                        <label style={labelSm}>Assertions</label>
                                        <button onClick={() => addAssertion(ci)} style={{ ...btnSecondary, padding: '0.2rem 0.5rem', fontSize: '0.8rem' }}>
                                            + Add Assertion
                                        </button>
                                    </div>
                                    {tc.assertions.map((a, ai) => (
                                        <div key={ai} style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', marginBottom: '0.35rem' }}>
                                            <select
                                                value={a.type}
                                                onChange={e => updateAssertion(ci, ai, { type: e.target.value })}
                                                style={{ ...inputStyle, width: 160, flexShrink: 0 }}
                                            >
                                                {ASSERTION_TYPES.map(t => (
                                                    <option key={t} value={t}>{t}</option>
                                                ))}
                                            </select>
                                            <input
                                                value={a.value}
                                                onChange={e => updateAssertion(ci, ai, { value: e.target.value })}
                                                style={{ ...inputStyle, flex: 1 }}
                                                placeholder="Value..."
                                            />
                                            <button
                                                onClick={() => removeAssertion(ci, ai)}
                                                style={{ background: 'none', border: 'none', color: 'var(--danger)', cursor: 'pointer', fontSize: '1rem', padding: '0.25rem', flexShrink: 0 }}
                                            >
                                                x
                                            </button>
                                        </div>
                                    ))}
                                    {tc.assertions.length === 0 && (
                                        <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', fontStyle: 'italic' }}>
                                            No assertions yet. Add one to validate outputs.
                                        </div>
                                    )}
                                </div>
                            </div>
                        )}
                    </div>
                );
            })}

            <button onClick={addTestCase} style={{ ...btnPrimary, alignSelf: 'flex-start' }}>
                + Add Test Case
            </button>

            <ConfirmDialog
                open={confirmRemove.open}
                onOpenChange={(open) => setConfirmRemove(s => ({ ...s, open }))}
                title="Remove Test Case"
                description={`Remove test case "${confirmRemove.name}"? This action cannot be undone.`}
                confirmLabel="Remove"
                variant="danger"
                onConfirm={() => removeTestCase(confirmRemove.index)}
            />
        </div>
    );
}

const labelSm: React.CSSProperties = {
    display: 'block',
    fontSize: '0.8rem',
    fontWeight: 500,
    color: 'var(--text-secondary)',
    marginBottom: '0.2rem',
};
