'use client';
import { useMemo } from 'react';

interface VersionDiffViewProps {
    oldContent: string;
    newContent: string;
    oldVersion: number;
    newVersion: number;
}

export default function VersionDiffView({ oldContent, newContent, oldVersion, newVersion }: VersionDiffViewProps) {
    const diffLines = useMemo(() => {
        const oldLines = oldContent.split('\n');
        const newLines = newContent.split('\n');
        const maxLen = Math.max(oldLines.length, newLines.length);

        const result: { oldLine: string | null; newLine: string | null; oldNum: number | null; newNum: number | null; type: 'same' | 'added' | 'removed' | 'changed' }[] = [];

        // Simple line-by-line comparison
        let oi = 0;
        let ni = 0;
        while (oi < oldLines.length || ni < newLines.length) {
            const oldL = oi < oldLines.length ? oldLines[oi] : null;
            const newL = ni < newLines.length ? newLines[ni] : null;

            if (oldL === newL) {
                result.push({ oldLine: oldL, newLine: newL, oldNum: oi + 1, newNum: ni + 1, type: 'same' });
                oi++;
                ni++;
            } else if (oldL !== null && newL !== null) {
                // Check if old line was removed (exists later in new)
                const newIdx = newLines.indexOf(oldL!, ni);
                const oldIdx = oldLines.indexOf(newL!, oi);

                if (newIdx === -1 && oldIdx === -1) {
                    // Changed line
                    result.push({ oldLine: oldL, newLine: null, oldNum: oi + 1, newNum: null, type: 'removed' });
                    result.push({ oldLine: null, newLine: newL, oldNum: null, newNum: ni + 1, type: 'added' });
                    oi++;
                    ni++;
                } else if (newIdx !== -1 && (oldIdx === -1 || newIdx - ni <= oldIdx - oi)) {
                    // Lines were added before old line appears
                    result.push({ oldLine: null, newLine: newL, oldNum: null, newNum: ni + 1, type: 'added' });
                    ni++;
                } else {
                    // Lines were removed before new line appears
                    result.push({ oldLine: oldL, newLine: null, oldNum: oi + 1, newNum: null, type: 'removed' });
                    oi++;
                }
            } else if (oldL !== null) {
                result.push({ oldLine: oldL, newLine: null, oldNum: oi + 1, newNum: null, type: 'removed' });
                oi++;
            } else {
                result.push({ oldLine: null, newLine: newL, oldNum: null, newNum: ni + 1, type: 'added' });
                ni++;
            }
        }

        return result;
    }, [oldContent, newContent]);

    const lineNumStyle: React.CSSProperties = {
        width: 40,
        minWidth: 40,
        textAlign: 'right',
        padding: '0 8px 0 4px',
        color: 'var(--text-secondary)',
        fontSize: '0.75rem',
        userSelect: 'none',
        borderRight: '1px solid var(--border)',
    };

    const lineContentStyle: React.CSSProperties = {
        flex: 1,
        padding: '0 8px',
        whiteSpace: 'pre-wrap',
        wordBreak: 'break-all',
        fontSize: '0.8rem',
        fontFamily: 'monospace',
    };

    return (
        <div>
            <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '0.75rem' }}>
                <span style={{ padding: '0.25rem 0.5rem', background: 'rgba(239,68,68,0.1)', borderRadius: 4, fontSize: '0.8rem' }}>
                    v{oldVersion}
                </span>
                <span style={{ color: 'var(--text-secondary)', fontSize: '0.8rem', lineHeight: '1.8' }}>vs</span>
                <span style={{ padding: '0.25rem 0.5rem', background: 'rgba(34,197,94,0.1)', borderRadius: 4, fontSize: '0.8rem' }}>
                    v{newVersion}
                </span>
            </div>
            <div style={{
                border: '1px solid var(--border)',
                borderRadius: 'var(--radius)',
                overflow: 'auto',
                maxHeight: 500,
                background: 'var(--background)',
            }}>
                {diffLines.map((line, i) => {
                    let bg = 'transparent';
                    let prefix = ' ';
                    if (line.type === 'added') {
                        bg = 'rgba(34,197,94,0.1)';
                        prefix = '+';
                    } else if (line.type === 'removed') {
                        bg = 'rgba(239,68,68,0.1)';
                        prefix = '-';
                    }

                    const displayText = line.type === 'removed' ? line.oldLine : line.newLine ?? line.oldLine;

                    return (
                        <div key={i} style={{ display: 'flex', background: bg, minHeight: 22, lineHeight: '22px' }}>
                            <div style={lineNumStyle}>
                                {line.oldNum ?? ''}
                            </div>
                            <div style={lineNumStyle}>
                                {line.newNum ?? ''}
                            </div>
                            <div style={{ width: 20, minWidth: 20, textAlign: 'center', fontSize: '0.75rem', fontFamily: 'monospace', color: line.type === 'added' ? 'var(--success)' : line.type === 'removed' ? 'var(--danger)' : 'var(--text-secondary)' }}>
                                {prefix}
                            </div>
                            <div style={lineContentStyle}>
                                {displayText}
                            </div>
                        </div>
                    );
                })}
                {diffLines.length === 0 && (
                    <div style={{ padding: '1rem', color: 'var(--text-secondary)', textAlign: 'center' }}>
                        No differences found.
                    </div>
                )}
            </div>
        </div>
    );
}
