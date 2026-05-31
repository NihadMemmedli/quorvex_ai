'use client';

import Link from 'next/link';
import { Database, ExternalLink, FileText, Loader2, RefreshCw } from 'lucide-react';

interface ImportRequirementsResult {
    created: number;
    skipped: number;
    total: number;
}

interface ProjectInfoBarProps {
    projectName: string;
    currentProjectId: string | null;
    onReset: () => void;
    onImportRequirements: () => Promise<void>;
    isImportingRequirements: boolean;
    importRequirementsResult: ImportRequirementsResult | null;
    hasRequirements: boolean;
}

export function ProjectInfoBar({
    projectName,
    currentProjectId,
    onReset,
    onImportRequirements,
    isImportingRequirements,
    importRequirementsResult,
    hasRequirements,
}: ProjectInfoBarProps) {
    const importDisabled = isImportingRequirements || !hasRequirements;
    const requirementsHref = currentProjectId
        ? `/requirements?project_id=${encodeURIComponent(currentProjectId)}`
        : '/requirements';

    return (
        <div
            className="card-elevated"
            style={{
                minHeight: 52,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                gap: '0.75rem',
                padding: '0.6rem 1.25rem',
                transform: 'none',
                flexWrap: 'wrap',
            }}
            onMouseEnter={(e) => {
                e.currentTarget.style.transform = 'none';
            }}
            onMouseLeave={(e) => {
                e.currentTarget.style.transform = 'none';
            }}
        >
            <style>{`
                .prd-project-reset:focus-visible,
                .prd-project-import:focus-visible,
                .prd-project-requirements-link:focus-visible {
                    outline: none;
                    box-shadow: 0 0 0 2px rgba(59,130,246,0.45);
                }

                .prd-project-actions {
                    display: flex;
                    align-items: center;
                    justify-content: flex-end;
                    gap: 0.5rem;
                    flex: 1 1 340px;
                    min-width: 0;
                    flex-wrap: wrap;
                }

                .prd-project-import-result {
                    color: var(--text-secondary);
                    font-size: 0.72rem;
                    line-height: 1.3;
                    white-space: nowrap;
                }

                .prd-project-requirements-link {
                    display: inline-flex;
                    align-items: center;
                    gap: 0.25rem;
                    color: var(--primary);
                    font-size: 0.72rem;
                    font-weight: 600;
                    text-decoration: none;
                    white-space: nowrap;
                }
            `}</style>
            {/* Left: Status dot + project name */}
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', minWidth: 0, flex: '1 1 220px' }}>
                {/* Pulsing green dot */}
                <div style={{ position: 'relative', width: 8, height: 8 }}>
                    <div style={{
                        position: 'absolute',
                        inset: 0,
                        borderRadius: '50%',
                        background: '#22c55e',
                    }} />
                    <div style={{
                        position: 'absolute',
                        inset: -2,
                        borderRadius: '50%',
                        background: '#22c55e',
                        opacity: 0.4,
                        animation: 'pulse 2s ease-in-out infinite',
                    }} />
                </div>

                <FileText size={15} style={{ color: 'var(--primary)', flexShrink: 0 }} />

                <span style={{
                    fontFamily: 'var(--font-mono)',
                    fontWeight: 600,
                    fontSize: '0.8rem',
                    color: 'var(--text)',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                    maxWidth: '100%',
                }}>
                    {projectName}
                </span>
            </div>

            <div className="prd-project-actions">
                {importRequirementsResult && (
                    <>
                        <span className="prd-project-import-result">
                            Imported {importRequirementsResult.created}; skipped {importRequirementsResult.skipped} of {importRequirementsResult.total}.
                        </span>
                        <Link href={requirementsHref} className="prd-project-requirements-link">
                            <ExternalLink size={12} />
                            Requirements
                        </Link>
                    </>
                )}

                <button
                    type="button"
                    onClick={onImportRequirements}
                    disabled={importDisabled}
                    title={!hasRequirements ? 'No extracted requirements to import' : undefined}
                    className="prd-project-import"
                    style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: '0.375rem',
                        padding: '0.35rem 0.75rem',
                        background: importDisabled ? 'rgba(255,255,255,0.04)' : 'rgba(37,99,235,0.16)',
                        border: '1px solid rgba(59,130,246,0.26)',
                        borderRadius: 'var(--radius-sm)',
                        color: importDisabled ? 'var(--text-tertiary)' : '#bfdbfe',
                        fontSize: '0.7rem',
                        fontWeight: 600,
                        cursor: importDisabled ? 'not-allowed' : 'pointer',
                        opacity: importDisabled ? 0.62 : 1,
                        transition: 'all 0.2s var(--ease-smooth)',
                        whiteSpace: 'nowrap',
                    }}
                    onMouseEnter={(e) => {
                        if (importDisabled) return;
                        e.currentTarget.style.background = 'rgba(37,99,235,0.24)';
                        e.currentTarget.style.borderColor = 'rgba(59,130,246,0.45)';
                        e.currentTarget.style.color = '#dbeafe';
                    }}
                    onMouseLeave={(e) => {
                        if (importDisabled) return;
                        e.currentTarget.style.background = 'rgba(37,99,235,0.16)';
                        e.currentTarget.style.borderColor = 'rgba(59,130,246,0.26)';
                        e.currentTarget.style.color = '#bfdbfe';
                    }}
                >
                    {isImportingRequirements ? <Loader2 size={12} className="animate-spin" /> : <Database size={12} />}
                    Import to Requirements
                </button>

                <button
                    type="button"
                    onClick={onReset}
                    className="prd-project-reset"
                    style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: '0.375rem',
                        padding: '0.35rem 0.75rem',
                        background: 'transparent',
                        border: '1px solid rgba(255,255,255,0.06)',
                        borderRadius: 'var(--radius-sm)',
                        color: 'var(--text-secondary)',
                        fontSize: '0.7rem',
                        fontWeight: 500,
                        cursor: 'pointer',
                        transition: 'all 0.2s var(--ease-smooth)',
                        whiteSpace: 'nowrap',
                    }}
                    onMouseEnter={(e) => {
                        e.currentTarget.style.background = 'var(--surface-hover)';
                        e.currentTarget.style.borderColor = 'var(--border-bright)';
                        e.currentTarget.style.color = 'var(--text)';
                    }}
                    onMouseLeave={(e) => {
                        e.currentTarget.style.background = 'transparent';
                        e.currentTarget.style.borderColor = 'rgba(255,255,255,0.06)';
                        e.currentTarget.style.color = 'var(--text-secondary)';
                    }}
                >
                    <RefreshCw size={12} />
                    New Project
                </button>
            </div>
        </div>
    );
}
