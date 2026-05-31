'use client';

import React, { useCallback, useEffect, useMemo, useState } from 'react';

import { Badge } from '@/components/ui/badge';
import { API_BASE } from '@/lib/api';
import {
    AlertCircle,
    Check,
    CheckCircle,
    Clipboard,
    ExternalLink,
    FileCheck2,
    FileText,
    Layers,
    List,
    Loader2,
    Pencil,
    Plus,
    RefreshCw,
    Sparkles,
    Square,
    Trash2,
    X,
    XCircle,
} from 'lucide-react';
import { PrdGenerationConsole } from './PrdGenerationConsole';
import type { Feature, GenerationResult } from './types';
import { formatTimeAgo, getFeatureStatus, getStageDisplay } from './types';

interface FeatureWorkspaceProps {
    feature: Feature | null;
    generationResult: GenerationResult | undefined;
    onGenerate: (name: string) => Promise<boolean>;
    onStop: (id: number) => Promise<void>;
    isGenerating: boolean;
    generationBlockedReason?: string | null;
    currentTargetUrl?: string;
    onAddRequirement: (featureSlug: string, text: string) => Promise<void>;
    onEditRequirement: (featureSlug: string, index: number, text: string) => Promise<void>;
    onDeleteRequirement: (featureSlug: string, index: number) => Promise<void>;
}

interface LoadedSpec {
    name: string;
    content: string;
}

function specNameFromPath(specPath: string | null | undefined): string | null {
    if (!specPath) return null;
    const normalized = specPath.replaceAll('\\', '/');
    const specsIndex = normalized.lastIndexOf('/specs/');
    if (specsIndex >= 0) return normalized.slice(specsIndex + '/specs/'.length);
    if (normalized.startsWith('specs/')) return normalized.slice('specs/'.length);
    return normalized || null;
}

function statusLabel(status: ReturnType<typeof getFeatureStatus>, wasCancelled: boolean): string {
    if (wasCancelled) return 'Cancelled';
    if (status === 'completed') return 'Generated';
    if (status === 'running') return 'Generating';
    if (status === 'failed') return 'Failed';
    return 'Not generated';
}

function statusStyles(status: ReturnType<typeof getFeatureStatus>, wasCancelled: boolean) {
    if (wasCancelled) {
        return { color: '#f59e0b', background: 'rgba(245,158,11,0.1)', borderColor: 'rgba(245,158,11,0.25)' };
    }
    if (status === 'completed') {
        return { color: '#4ade80', background: 'rgba(34,197,94,0.1)', borderColor: 'rgba(34,197,94,0.25)' };
    }
    if (status === 'running') {
        return { color: '#60a5fa', background: 'rgba(59,130,246,0.1)', borderColor: 'rgba(59,130,246,0.25)' };
    }
    if (status === 'failed') {
        return { color: '#f87171', background: 'rgba(248,113,113,0.1)', borderColor: 'rgba(248,113,113,0.25)' };
    }
    return { color: 'var(--text-secondary)', background: 'rgba(126,139,168,0.08)', borderColor: 'var(--border-subtle)' };
}

const primaryActionClass =
    'prd-primary-action focus:outline-none';

const secondaryActionClass =
    'prd-secondary-action focus:outline-none';

const iconButtonClass =
    'prd-icon-action focus:outline-none';

export function FeatureWorkspace({
    feature,
    generationResult,
    onGenerate,
    onStop,
    isGenerating,
    generationBlockedReason,
    currentTargetUrl = '',
    onAddRequirement,
    onEditRequirement,
    onDeleteRequirement,
}: FeatureWorkspaceProps) {
    const [editingIndex, setEditingIndex] = useState<number | null>(null);
    const [editText, setEditText] = useState('');
    const [isAdding, setIsAdding] = useState(false);
    const [newReqText, setNewReqText] = useState('');
    const [isSaving, setIsSaving] = useState(false);
    const [loadedSpec, setLoadedSpec] = useState<LoadedSpec | null>(null);
    const [specLoadError, setSpecLoadError] = useState<string | null>(null);
    const [isSpecLoading, setIsSpecLoading] = useState(false);
    const [copied, setCopied] = useState<'content' | null>(null);

    const status = getFeatureStatus(generationResult);
    const hasRequirements = Boolean(feature?.requirements?.length);
    const wasGenerated = generationResult?.success ? generationResult.timestamp : null;
    const wasCancelled = generationResult?.status === 'cancelled';
    const isRunning =
        generationResult?.status === 'running' ||
        generationResult?.status === 'pending' ||
        generationResult?.status === 'queued';
    const generationError =
        generationResult?.success === false && generationResult?.status === 'failed'
            ? generationResult.error
            : null;
    const specName = useMemo(() => specNameFromPath(generationResult?.specPath), [generationResult?.specPath]);
    const statusStyle = statusStyles(status, wasCancelled);
    useEffect(() => {
        setLoadedSpec(null);
        setSpecLoadError(null);
        setCopied(null);
    }, [feature?.slug, specName]);

    useEffect(() => {
        if (!specName || status !== 'completed') return;
        let cancelled = false;
        setIsSpecLoading(true);
        setSpecLoadError(null);

        fetch(`${API_BASE}/specs/${encodeURIComponent(specName)}`)
            .then(async (res) => {
                if (!res.ok) throw new Error(`Could not load generated plan (${res.status})`);
                return res.json();
            })
            .then((data) => {
                if (!cancelled) {
                    setLoadedSpec({
                        name: data.name || specName,
                        content: data.content || '',
                    });
                }
            })
            .catch((error: Error) => {
                if (!cancelled) setSpecLoadError(error.message || 'Could not load generated plan');
            })
            .finally(() => {
                if (!cancelled) setIsSpecLoading(false);
            });

        return () => {
            cancelled = true;
        };
    }, [specName, status]);

    const handleGenerate = async () => {
        if (!feature) return;
        await onGenerate(feature.name);
    };

    const handleCopy = useCallback((kind: 'content', value: string | undefined | null) => {
        if (!value) return;
        navigator.clipboard.writeText(value);
        setCopied(kind);
        setTimeout(() => setCopied(null), 1600);
    }, []);

    const handleStartEdit = (index: number, text: string) => {
        setEditingIndex(index);
        setEditText(text);
        setIsAdding(false);
    };

    const handleCancelEdit = () => {
        setEditingIndex(null);
        setEditText('');
    };

    const handleSaveEdit = async () => {
        if (!feature || editingIndex === null || !editText.trim()) return;
        setIsSaving(true);
        try {
            await onEditRequirement(feature.slug, editingIndex, editText.trim());
            setEditingIndex(null);
            setEditText('');
        } finally {
            setIsSaving(false);
        }
    };

    const handleDelete = async (index: number) => {
        if (!feature) return;
        if (!window.confirm(`Delete requirement REQ-${index + 1}?`)) return;
        await onDeleteRequirement(feature.slug, index);
        if (editingIndex === index) handleCancelEdit();
    };

    const handleStartAdd = () => {
        setIsAdding(true);
        setNewReqText('');
        handleCancelEdit();
    };

    const handleSaveAdd = async () => {
        if (!feature || !newReqText.trim()) return;
        setIsSaving(true);
        try {
            await onAddRequirement(feature.slug, newReqText.trim());
            setIsAdding(false);
            setNewReqText('');
        } finally {
            setIsSaving(false);
        }
    };

    const renderPrimaryAction = () => {
        if (!hasRequirements) {
            return (
                <button
                    disabled
                    className={`${primaryActionClass} cursor-not-allowed opacity-45`}
                    style={{ background: 'rgba(255,255,255,0.06)', color: 'var(--text-tertiary)' }}
                >
                    <Sparkles className="h-4 w-4 shrink-0" />
                    <span>Create Plan</span>
                </button>
            );
        }

        if (isRunning) {
            return (
                <button
                    disabled
                    className={`${primaryActionClass} relative cursor-not-allowed overflow-hidden text-white focus:ring-blue-500/40`}
                    style={{ background: '#2563eb', color: '#fff' }}
                >
                    <Loader2 className="h-4 w-4 shrink-0 animate-spin" />
                    <span className="min-w-0 max-w-[128px] truncate">
                        {getStageDisplay(generationResult?.stage, generationResult?.message)}
                    </span>
                    <div className="absolute inset-0 progress-shimmer" />
                </button>
            );
        }

        if (generationError) {
            return (
                <button
                    onClick={handleGenerate}
                    disabled={isGenerating || Boolean(generationBlockedReason)}
                    className={`${primaryActionClass} text-white disabled:cursor-not-allowed disabled:opacity-50 focus:ring-red-500/40`}
                    style={{ background: '#dc2626', color: '#fff' }}
                    title={generationBlockedReason || undefined}
                >
                    <RefreshCw className="h-4 w-4 shrink-0" />
                    <span>Retry</span>
                </button>
            );
        }

        if (wasGenerated) {
            return (
                <button
                    onClick={handleGenerate}
                    disabled={isGenerating || Boolean(generationBlockedReason)}
                    className={`${primaryActionClass} text-white disabled:cursor-not-allowed disabled:opacity-50 focus:ring-blue-500/40`}
                    style={{ background: 'rgba(255,255,255,0.08)', color: '#fff' }}
                    title={generationBlockedReason || undefined}
                >
                    <RefreshCw className="h-4 w-4 shrink-0" />
                    <span>Regenerate</span>
                </button>
            );
        }

        return (
            <button
                onClick={handleGenerate}
                disabled={isGenerating || Boolean(generationBlockedReason)}
                className={`${primaryActionClass} btn-primary disabled:cursor-not-allowed disabled:opacity-50 focus:ring-blue-500/40`}
                title={generationBlockedReason || undefined}
            >
                <Sparkles className="h-4 w-4 shrink-0" />
                <span>Create Plan</span>
            </button>
        );
    };

    if (!feature) {
        return (
            <div className="prd-feature-detail flex flex-col">
                <div className="flex h-full flex-col items-center justify-center gap-4">
                    <div className="p-5 rounded-xl" style={{ background: 'var(--primary-glow)' }}>
                        <Layers className="h-10 w-10" style={{ color: 'var(--primary)', opacity: 0.6 }} />
                    </div>
                    <div className="text-center">
                        <p className="text-sm font-medium" style={{ color: 'var(--text-secondary)' }}>
                            Select a feature
                        </p>
                        <p className="text-xs mt-1 max-w-[260px]" style={{ color: 'var(--text-tertiary)' }}>
                            Choose a feature to review requirements, generated plan status, and run details.
                        </p>
                    </div>
                </div>
            </div>
        );
    }

    return (
        <div className="prd-feature-detail flex flex-col">
            <style>{`
	                .prd-primary-action {
                    display: inline-flex;
                    align-items: center;
                    justify-content: center;
                    gap: 0.5rem;
                    height: 40px;
                    min-width: 132px;
                    max-width: 190px;
                    padding: 0 1rem;
                    border: 1px solid transparent;
                    border-radius: 8px;
                    font-size: 0.875rem;
                    font-weight: 650;
                    line-height: 1;
                    white-space: nowrap;
	                    transition: background-color 0.2s, color 0.2s, opacity 0.2s;
	                }

	                .prd-primary-action:focus-visible,
	                .prd-secondary-action:focus-visible,
	                .prd-icon-action:focus-visible {
	                    outline: none;
	                    box-shadow: 0 0 0 2px rgba(59,130,246,0.45);
	                }

	                .prd-primary-action:disabled {
	                    cursor: not-allowed;
	                    opacity: 0.5;
                }

                .prd-secondary-action {
                    display: inline-flex;
                    align-items: center;
                    justify-content: center;
                    gap: 0.375rem;
                    height: 32px;
                    padding: 0 0.625rem;
                    border: 1px solid transparent;
                    border-radius: 7px;
                    font-size: 0.75rem;
                    font-weight: 600;
                    line-height: 1;
                    white-space: nowrap;
	                    transition: background-color 0.2s, color 0.2s, opacity 0.2s;
	                }

	                .prd-secondary-outline {
	                    border-color: var(--border-subtle);
	                    color: var(--text-secondary);
	                }

	                .prd-secondary-action:hover,
	                .prd-icon-action:hover {
	                    background: rgba(255,255,255,0.05);
                }

                .prd-icon-action {
                    display: inline-flex;
                    align-items: center;
                    justify-content: center;
                    width: 32px;
                    height: 32px;
                    flex: 0 0 32px;
                    border: 1px solid transparent;
                    border-radius: 7px;
                    transition: background-color 0.2s, opacity 0.2s;
                }

                .prd-detail-header-row {
                    display: flex;
                    align-items: flex-start;
                    justify-content: space-between;
                    gap: 1rem;
                    min-width: 0;
                }

                .prd-detail-header {
                    display: flex;
                    flex-direction: column;
                    gap: 0.85rem;
                    padding: 1.15rem 1rem 0.95rem;
                    border-bottom: 1px solid var(--border);
                    background: rgba(21, 29, 48, 0.92);
                }

                .prd-detail-heading {
                    min-width: 0;
                    flex: 1 1 auto;
                }

                .prd-feature-meta-row {
                    display: flex;
                    flex-wrap: wrap;
                    align-items: center;
                    gap: 0.375rem 0.5rem;
                    margin-bottom: 0.5rem;
                }

                .prd-status-pill {
                    display: inline-flex;
                    align-items: center;
                    gap: 0.375rem;
                    height: 24px;
                    padding: 0 0.5rem;
                    border: 1px solid;
                    border-radius: 7px;
                    font-size: 0.75rem;
                    font-weight: 600;
                    line-height: 1;
                    white-space: nowrap;
                }

                .prd-detail-title {
                    margin: 0;
                    overflow: hidden;
                    text-overflow: ellipsis;
                    white-space: nowrap;
                    font-size: 1.125rem;
                    line-height: 1.25;
                    font-weight: 700;
                }

                .prd-detail-subtitle {
                    margin-top: 0.25rem;
                    max-width: 48rem;
                    overflow: hidden;
                    text-overflow: ellipsis;
                    white-space: nowrap;
                    font-size: 0.75rem;
                    line-height: 1.35;
                }

                .prd-detail-actions {
                    display: flex;
                    min-width: 0;
                    flex-direction: column;
                    align-items: flex-end;
                    gap: 0.5rem;
                    padding-top: 0.25rem;
                }

                .prd-detail-action-row {
                    display: flex;
                    flex-wrap: wrap;
                    align-items: center;
                    justify-content: flex-end;
                    gap: 0.5rem;
                }

	                .prd-requirements-heading {
	                    display: flex;
	                    align-items: center;
                    justify-content: space-between;
                    gap: 0.75rem;
                    margin-bottom: 0.7rem;
	                    padding-top: 0.15rem;
	                }

	                .prd-requirement-list {
	                    border-color: var(--border-subtle);
	                }

	                .prd-requirement-row {
	                    display: grid;
	                    grid-template-columns: 56px minmax(0, 1fr) 72px;
	                    align-items: start;
	                    gap: 0.75rem;
	                    padding: 0.65rem 0.75rem;
	                    border-color: var(--border-subtle);
	                }

	                .prd-req-label {
	                    display: block;
	                    padding-top: 0.125rem;
	                    color: var(--primary);
	                    font-family: var(--font-mono);
	                    font-size: 0.7rem;
	                    font-weight: 700;
	                    line-height: 1.5rem;
	                    white-space: nowrap;
	                }

	                .prd-req-text {
	                    min-width: 0;
	                    color: var(--text-secondary);
	                    font-size: 0.875rem;
	                    line-height: 1.5rem;
	                    overflow-wrap: anywhere;
	                }

	                .prd-req-actions {
	                    display: flex;
	                    justify-content: flex-end;
	                    gap: 0.25rem;
	                    width: 72px;
	                    opacity: 0.72;
	                    transition: opacity 0.2s;
	                }

	                .prd-requirement-row:hover .prd-req-actions,
	                .prd-requirement-row:focus-within .prd-req-actions {
	                    opacity: 1;
	                }

	                .prd-requirement-textarea {
	                    display: block;
	                    width: 100%;
	                    min-height: 4.75rem;
	                    box-sizing: border-box;
	                    resize: none;
	                    border: 1px solid var(--border-bright);
	                    border-radius: 0.375rem;
	                    background: rgba(0,0,0,0.25);
	                    color: var(--text);
	                    padding: 0.75rem 0.875rem;
	                    font: inherit;
	                    font-size: 0.875rem;
	                    line-height: 1.5rem;
	                    vertical-align: top;
	                }

	                .prd-requirement-textarea::placeholder {
	                    color: var(--text-tertiary);
	                    line-height: inherit;
	                    opacity: 1;
	                }

	                .prd-requirement-textarea:focus-visible {
	                    outline: none;
	                    box-shadow: 0 0 0 2px rgba(59,130,246,0.45);
	                }

	                .prd-generated-plan-section {
	                    overflow: hidden;
	                    border: 1px solid var(--border-subtle);
                    border-radius: 8px;
                    background: rgba(255,255,255,0.018);
                }

                .prd-generated-plan-header {
                    display: flex;
                    align-items: center;
                    justify-content: space-between;
                    gap: 1rem;
                    padding: 0.85rem 1rem;
                    border-bottom: 1px solid var(--border-subtle);
                }

                .prd-generated-plan-title-stack {
                    display: grid;
                    gap: 0.28rem;
                    min-width: 0;
                }

                .prd-generated-plan-title {
                    display: flex;
                    align-items: center;
                    gap: 0.5rem;
                    color: var(--text);
                    font-size: 0.875rem;
                    font-weight: 650;
                    line-height: 1.2;
                }

                .prd-generated-plan-path {
                    color: var(--text-tertiary);
                    font-family: var(--font-mono);
                    font-size: 0.75rem;
                    line-height: 1.35;
                    overflow: hidden;
                    text-overflow: ellipsis;
                    white-space: nowrap;
                }

                .prd-generated-plan-actions {
                    display: flex;
                    align-items: center;
                    gap: 0.5rem;
                    flex: 0 0 auto;
                }

                @media (max-width: 1120px) {
                    .prd-detail-header-row {
                        flex-direction: column;
                    }

                    .prd-detail-actions {
                        align-items: flex-start;
                    }

                    .prd-detail-action-row {
                        justify-content: flex-start;
                    }

	                    .prd-detail-actions {
	                        padding-top: 0;
	                    }

	                    .prd-generated-plan-header {
	                        align-items: flex-start;
	                    }
	                }

	                @media (max-width: 720px) {
	                    .prd-requirement-row {
	                        grid-template-columns: 52px minmax(0, 1fr);
	                    }

	                    .prd-req-actions {
	                        grid-column: 2;
	                        width: auto;
	                        justify-content: flex-start;
	                    }
	                }
	            `}</style>
            <div className="prd-detail-header">
                <div className="prd-detail-header-row">
                    <div className="prd-detail-heading">
                        <div className="prd-feature-meta-row">
                            <span
                                className="prd-status-pill"
                                style={statusStyle}
                            >
                                {status === 'completed' ? <CheckCircle className="h-3.5 w-3.5" /> : null}
                                {status === 'failed' ? <XCircle className="h-3.5 w-3.5" /> : null}
                                {status === 'running' ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
                                {status === 'pending' && !wasCancelled ? <FileText className="h-3.5 w-3.5" /> : null}
                                {statusLabel(status, wasCancelled)}
                            </span>
                            {wasGenerated && (
                                <span className="text-xs" style={{ color: 'var(--text-tertiary)', whiteSpace: 'nowrap' }}>
                                    Generated {formatTimeAgo(wasGenerated)}
                                </span>
                            )}
                        </div>
                        <h2 className="prd-detail-title" style={{ color: 'var(--text)' }}>
                            {feature.name}
                        </h2>
                        <p className="prd-detail-subtitle" style={{ color: 'var(--text-secondary)' }}>
                            Review the extracted requirements, inspect the generated plan, then regenerate only when the feature definition changes.
                        </p>
                    </div>

                    <div className="prd-detail-actions">
	                        <div className="prd-detail-action-row">
	                            {isRunning && generationResult?.generationId && (
	                                <button
	                                    onClick={() => onStop(generationResult.generationId!)}
	                                    className={`${primaryActionClass} text-white`}
	                                    style={{ background: '#dc2626', color: '#fff' }}
	                                >
	                                    <Square className="h-4 w-4 shrink-0" />
	                                    Stop
	                                </button>
	                            )}
	                            {renderPrimaryAction()}
	                        </div>
	                    </div>
	                </div>

	                {(generationBlockedReason || isRunning || generationError || wasCancelled) && (
	                    <div className="text-xs" style={{ color: generationBlockedReason || generationError ? '#f87171' : 'var(--text-tertiary)' }}>
	                        {generationBlockedReason || (wasCancelled ? 'Generation was cancelled.' : generationError || getStageDisplay(generationResult?.stage, generationResult?.message))}
	                    </div>
	                )}
	            </div>

            <div
                className="flex-1"
                style={{ minHeight: 0, overflowY: 'auto', scrollbarWidth: 'thin', scrollbarColor: 'var(--surface-active) transparent' }}
            >
                <div className="space-y-4 px-4 py-4">
                    <section>
                        <div className="prd-requirements-heading">
                            <div className="flex items-center gap-2 text-sm font-medium" style={{ color: 'var(--text-secondary)' }}>
                                <List className="h-4 w-4" style={{ color: 'var(--primary)' }} />
                                <span>Requirements</span>
                                <span className="font-mono text-[11px]" style={{ color: 'var(--text-tertiary)' }}>
                                    {feature.requirements?.length || 0}
                                </span>
                            </div>
                            {!isAdding && (
                                <button
                                    onClick={handleStartAdd}
                                    className={`${secondaryActionClass} prd-secondary-outline`}
	                                >
                                    <Plus className="h-3.5 w-3.5" />
                                    Add
                                </button>
                            )}
                        </div>

                        <div className="overflow-hidden rounded-md border" style={{ borderColor: 'var(--border-subtle)', background: 'rgba(255,255,255,0.018)' }}>
                            {feature.requirements?.length > 0 ? (
	                                <ul className="prd-requirement-list divide-y">
	                                    {feature.requirements.map((req, i) => (
	                                        <li key={i} className="prd-requirement-row group">
	                                            <span className="prd-req-label">REQ-{i + 1}</span>
	                                            {editingIndex === i ? (
	                                                <div className="flex min-w-0 flex-1 flex-col gap-2">
	                                                    <textarea
	                                                        className="prd-requirement-textarea"
	                                                        value={editText}
	                                                        onChange={e => setEditText(e.target.value)}
                                                        onKeyDown={e => {
                                                            if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSaveEdit(); }
                                                            if (e.key === 'Escape') handleCancelEdit();
                                                        }}
                                                        rows={2}
                                                        autoFocus
                                                        disabled={isSaving}
                                                    />
                                                    <div className="flex gap-1.5">
                                                        <button
                                                            onClick={handleSaveEdit}
                                                            disabled={isSaving || !editText.trim()}
                                                            className={`${secondaryActionClass} bg-blue-600 text-white hover:bg-blue-500 disabled:cursor-not-allowed disabled:opacity-40`}
                                                        >
                                                            <Check className="h-3 w-3" /> Save
                                                        </button>
                                                        <button
                                                            onClick={handleCancelEdit}
                                                            disabled={isSaving}
                                                            className={secondaryActionClass}
                                                            style={{ color: 'var(--text-secondary)' }}
                                                        >
                                                            <X className="h-3 w-3" /> Cancel
                                                        </button>
                                                    </div>
                                                </div>
                                            ) : (
	                                                <>
	                                                    <span className="prd-req-text">
	                                                        {req}
	                                                    </span>
	                                                    <div className="prd-req-actions">
	                                                        <button
	                                                            onClick={() => handleStartEdit(i, req)}
	                                                            className={iconButtonClass}
	                                                            style={{ color: 'var(--text-secondary)' }}
	                                                            aria-label={`Edit requirement ${i + 1}`}
	                                                        >
                                                            <Pencil size={14} />
                                                        </button>
	                                                        <button
	                                                            onClick={() => handleDelete(i)}
	                                                            className={iconButtonClass}
	                                                            style={{ color: 'var(--danger)' }}
	                                                            aria-label={`Delete requirement ${i + 1}`}
	                                                        >
                                                            <Trash2 size={14} />
                                                        </button>
                                                    </div>
                                                </>
                                            )}
                                        </li>
                                    ))}
                                </ul>
                            ) : (
                                <div className="p-8 text-center text-sm" style={{ color: 'var(--text-tertiary)' }}>
                                    No requirements extracted for this feature yet.
                                </div>
                            )}

	                            {isAdding && (
	                                <div className="m-3 rounded-md border p-3" style={{ borderColor: 'var(--border-bright)', background: 'var(--surface)' }}>
	                                    <textarea
	                                        className="prd-requirement-textarea"
	                                        value={newReqText}
                                        onChange={e => setNewReqText(e.target.value)}
                                        onKeyDown={e => {
                                            if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSaveAdd(); }
                                            if (e.key === 'Escape') setIsAdding(false);
                                        }}
                                        rows={2}
                                        placeholder="Enter requirement text..."
                                        autoFocus
                                        disabled={isSaving}
                                    />
                                    <div className="flex gap-1.5 mt-2">
                                        <button
                                            onClick={handleSaveAdd}
                                            disabled={isSaving || !newReqText.trim()}
                                            className={`${secondaryActionClass} bg-blue-600 text-white hover:bg-blue-500 disabled:cursor-not-allowed disabled:opacity-40`}
                                        >
                                            <Check className="h-3 w-3" /> Add
                                        </button>
                                        <button
                                            onClick={() => setIsAdding(false)}
                                            disabled={isSaving}
                                            className={secondaryActionClass}
                                            style={{ color: 'var(--text-secondary)' }}
                                        >
                                            <X className="h-3 w-3" /> Cancel
                                        </button>
                                    </div>
                                </div>
                            )}
                        </div>
                    </section>

                    {loadedSpec?.content && (
                        <section className="prd-generated-plan-section">
                            <div className="prd-generated-plan-header">
                                <div className="prd-generated-plan-title-stack">
                                    <div className="prd-generated-plan-title">
                                        <FileCheck2 className="h-4 w-4" style={{ color: '#4ade80' }} />
                                        Generated Plan
                                    </div>
                                    {specName && (
                                        <div className="prd-generated-plan-path">
                                            {specName}
                                        </div>
                                    )}
                                </div>
                                <div className="prd-generated-plan-actions">
                                    {loadedSpec?.content && (
                                        <button
	                                            onClick={() => handleCopy('content', loadedSpec.content)}
	                                            className={`${secondaryActionClass} prd-secondary-outline`}
	                                        >
                                            {copied === 'content' ? <Check className="h-3.5 w-3.5 text-green-400" /> : <Clipboard className="h-3.5 w-3.5" />}
                                            Copy
                                        </button>
                                    )}
                                    {specName && (
                                        <a
	                                            href={`/specs?file=${encodeURIComponent(specName)}`}
	                                            className={`${secondaryActionClass} prd-secondary-outline`}
	                                        >
                                            <ExternalLink className="h-3.5 w-3.5" />
                                            Open
                                        </a>
                                    )}
                                </div>
                            </div>

                            <pre
                                className="max-h-72 overflow-auto p-4 text-xs leading-5 whitespace-pre-wrap break-words"
                                style={{ color: 'var(--text-secondary)', background: 'rgba(0,0,0,0.18)' }}
                            >
                                {loadedSpec.content}
                            </pre>
                        </section>
                    )}

                    {(isSpecLoading || specLoadError) && (
                        <div className="rounded-md border px-3 py-2 text-sm" style={{ borderColor: 'var(--border-subtle)', color: isSpecLoading ? 'var(--text-secondary)' : '#f59e0b', background: 'rgba(255,255,255,0.018)' }}>
                            <div className="flex items-center gap-2">
                                {isSpecLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <AlertCircle className="h-4 w-4 shrink-0" />}
                                <span>{isSpecLoading ? 'Loading generated plan...' : `${specLoadError}. Requirements and actions are still available.`}</span>
                            </div>
                        </div>
                    )}

                    {feature.merged_from && feature.merged_from.length > 0 && (
                        <section>
                            <details className="group">
                                <summary className="flex items-center gap-2 mb-2 text-xs cursor-pointer transition-colors" style={{ color: 'var(--text-tertiary)' }}>
                                    Consolidated from {feature.merged_from.length} sub-features
                                </summary>
                                <div className="flex flex-wrap gap-2">
                                    {feature.merged_from.map((sub, i) => (
                                        <Badge key={i} variant="secondary" className="text-xs bg-slate-700/50 text-slate-400 border-slate-600">
                                            {sub}
                                        </Badge>
                                    ))}
                                </div>
                            </details>
                        </section>
                    )}

                    <PrdGenerationConsole
                        generation={generationResult}
                        isRunning={isRunning}
                        currentTargetUrl={currentTargetUrl}
                    />
                </div>
            </div>
        </div>
    );
}
