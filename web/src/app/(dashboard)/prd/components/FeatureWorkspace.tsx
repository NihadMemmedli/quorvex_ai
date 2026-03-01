'use client';

import React, { useState } from 'react';

import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import {
    FileText,
    Layers,
    List,
    ChevronRight,
    Loader2,
    Sparkles,
    RefreshCw,
    Square,
    CheckCircle,
    XCircle,
    Pencil,
    Trash2,
    Plus,
    Check,
    X,
} from 'lucide-react';
import { AgentLogViewer } from './AgentLogViewer';
import type { Feature, GenerationResult } from './types';
import { getFeatureStatus, getStageDisplay, formatTimeAgo } from './types';

interface FeatureWorkspaceProps {
    feature: Feature | null;
    generationResult: GenerationResult | undefined;
    onGenerate: (name: string) => Promise<boolean>;
    onStop: (id: number) => Promise<void>;
    isGenerating: boolean;
    project: string;
    onAddRequirement: (featureSlug: string, text: string) => Promise<void>;
    onEditRequirement: (featureSlug: string, index: number, text: string) => Promise<void>;
    onDeleteRequirement: (featureSlug: string, index: number) => Promise<void>;
}

export function FeatureWorkspace({
    feature,
    generationResult,
    onGenerate,
    onStop,
    isGenerating,
    onAddRequirement,
    onEditRequirement,
    onDeleteRequirement,
}: FeatureWorkspaceProps) {
    // --- Empty State ---
    if (!feature) {
        return (
            <div className="flex-1 card-elevated flex flex-col overflow-hidden">
                <div className="flex h-full flex-col items-center justify-center gap-4">
                    <div
                        className="p-5 rounded-2xl"
                        style={{ background: 'var(--primary-glow)' }}
                    >
                        <Layers
                            className="h-10 w-10"
                            style={{
                                color: 'var(--primary)',
                                opacity: 0.5,
                                animation: 'subtleFloat 3s ease-in-out infinite',
                            }}
                        />
                    </div>
                    <div className="text-center">
                        <p
                            className="text-sm font-medium"
                            style={{ color: 'var(--text-secondary)' }}
                        >
                            Select a Feature
                        </p>
                        <p
                            className="text-xs mt-1 max-w-[240px]"
                            style={{ color: 'var(--text-tertiary)' }}
                        >
                            Choose a feature from the sidebar to view its requirements and generate test plans
                        </p>
                    </div>
                </div>
            </div>
        );
    }

    // --- Derived State ---
    const status = getFeatureStatus(generationResult);
    const hasRequirements = feature.requirements?.length > 0;
    const wasGenerated = generationResult?.success ? generationResult.timestamp : null;
    const generationError =
        generationResult?.success === false && generationResult?.status === 'failed'
            ? generationResult.error
            : null;
    const wasCancelled = generationResult?.status === 'cancelled';
    const isRunning =
        generationResult?.status === 'running' || generationResult?.status === 'pending';
    const currentStage = generationResult?.stage;
    const stageMessage = generationResult?.message;

    // --- CRUD State ---
    const [editingIndex, setEditingIndex] = useState<number | null>(null);
    const [editText, setEditText] = useState('');
    const [isAdding, setIsAdding] = useState(false);
    const [newReqText, setNewReqText] = useState('');
    const [isSaving, setIsSaving] = useState(false);

    const handleGenerate = async () => {
        await onGenerate(feature.name);
    };

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
        } catch { /* ignore */ }
        setIsSaving(false);
    };

    const handleDelete = async (index: number) => {
        if (!feature) return;
        if (!window.confirm(`Delete requirement REQ-${index + 1}?`)) return;
        try {
            await onDeleteRequirement(feature.slug, index);
            if (editingIndex === index) handleCancelEdit();
        } catch { /* ignore */ }
    };

    const handleStartAdd = () => {
        setIsAdding(true);
        setNewReqText('');
        handleCancelEdit();
    };

    const handleCancelAdd = () => {
        setIsAdding(false);
        setNewReqText('');
    };

    const handleSaveAdd = async () => {
        if (!feature || !newReqText.trim()) return;
        setIsSaving(true);
        try {
            await onAddRequirement(feature.slug, newReqText.trim());
            setIsAdding(false);
            setNewReqText('');
        } catch { /* ignore */ }
        setIsSaving(false);
    };

    // --- Generate Button Rendering ---
    const renderGenerateButton = () => {
        // No requirements: disabled slate
        if (!hasRequirements) {
            return (
                <button
                    disabled
                    className="btn whitespace-nowrap opacity-40 cursor-not-allowed"
                    style={{
                        background: 'rgba(255,255,255,0.06)',
                        color: 'var(--text-tertiary)',
                    }}
                >
                    <Sparkles className="h-4 w-4 shrink-0" />
                    <span>Create Plan</span>
                </button>
            );
        }

        // Running: blue with spinner + stage text + shimmer
        if (isRunning) {
            return (
                <button
                    disabled
                    className="btn text-white relative overflow-hidden cursor-not-allowed"
                    style={{ background: '#2563eb' }}
                >
                    <Loader2 className="h-4 w-4 shrink-0 animate-spin" />
                    <span className="max-w-[180px] truncate">
                        {getStageDisplay(currentStage, stageMessage)}
                    </span>
                    <div className="absolute inset-0 progress-shimmer" />
                </button>
            );
        }

        // Failed: red "Retry"
        if (generationError) {
            return (
                <button
                    onClick={handleGenerate}
                    disabled={isGenerating}
                    className="btn text-white disabled:opacity-50 disabled:cursor-not-allowed"
                    style={{ background: '#dc2626' }}
                    onMouseEnter={e => { if (!isGenerating) (e.currentTarget as HTMLButtonElement).style.background = '#ef4444'; }}
                    onMouseLeave={e => { (e.currentTarget as HTMLButtonElement).style.background = '#dc2626'; }}
                >
                    <RefreshCw className="h-4 w-4 shrink-0" />
                    <span>Retry</span>
                </button>
            );
        }

        // Completed: muted slate "Regenerate"
        if (wasGenerated) {
            return (
                <button
                    onClick={handleGenerate}
                    disabled={isGenerating}
                    className="btn text-white disabled:opacity-50 disabled:cursor-not-allowed"
                    style={{ background: 'rgba(255,255,255,0.08)' }}
                    onMouseEnter={e => { if (!isGenerating) (e.currentTarget as HTMLButtonElement).style.background = 'rgba(255,255,255,0.14)'; }}
                    onMouseLeave={e => { (e.currentTarget as HTMLButtonElement).style.background = 'rgba(255,255,255,0.08)'; }}
                >
                    <RefreshCw className="h-4 w-4 shrink-0" />
                    <span>Regenerate</span>
                </button>
            );
        }

        // Ready: primary blue "Create Plan"
        return (
            <button
                onClick={handleGenerate}
                disabled={isGenerating}
                className="btn btn-primary disabled:opacity-50 disabled:cursor-not-allowed"
            >
                <Sparkles className="h-4 w-4 shrink-0" />
                <span>Create Plan</span>
            </button>
        );
    };

    return (
        <div className="flex-1 card-elevated flex flex-col" style={{ padding: 0, overflow: 'hidden' }}>
            {/* Sticky Header */}
            <div
                className="px-5 pt-4 pb-3 flex items-start justify-between sticky top-0 z-10 border-b"
                style={{
                    background: 'rgba(21, 29, 48, 0.95)',
                    backdropFilter: 'blur(8px)',
                    WebkitBackdropFilter: 'blur(8px)',
                    borderColor: 'var(--border)',
                }}
            >
                {/* Left: Info */}
                <div className="min-w-0 flex-1">
                    {/* Breadcrumb */}
                    <div
                        className="flex items-center gap-2 mb-3 text-[10px] font-mono uppercase tracking-wider"
                        style={{ color: 'var(--text-tertiary)' }}
                    >
                        <FileText className="h-3 w-3" />
                        <span>Feature</span>
                        <ChevronRight className="h-3 w-3" style={{ opacity: 0.4 }} />
                        <span style={{ color: 'var(--primary)' }}>Detail</span>
                    </div>

                    {/* Feature Name */}
                    <h2 className="text-xl font-bold leading-tight" style={{ color: 'var(--text)' }}>
                        {feature.name}
                    </h2>

                    {/* Gradient Underline */}
                    <div
                        className="h-[2px] w-12 mt-1.5 rounded-full"
                        style={{
                            background: 'linear-gradient(90deg, var(--primary), var(--accent))',
                        }}
                    />

                    {/* Stats Row */}
                    <div className="flex items-center gap-3 mt-4 mb-1">
                        {/* Requirement count badge */}
                        <div className="badge badge-primary flex items-center" style={{ gap: '8px' }}>
                            <List size={12} />
                            <span>{feature.requirements?.length || 0} requirements</span>
                        </div>

                        {/* Generated badge */}
                        {status === 'completed' && (
                            <div className="flex items-center px-3 py-1 rounded-md bg-green-500/10" style={{ gap: '6px' }}>
                                <CheckCircle size={12} className="text-green-400" />
                                <span className="text-[11px] font-mono text-green-400">
                                    Generated
                                </span>
                            </div>
                        )}

                        {/* Failed badge */}
                        {status === 'failed' && !isRunning && (
                            <div className="flex items-center px-3 py-1 rounded-md bg-red-500/10" style={{ gap: '6px' }}>
                                <XCircle size={12} className="text-red-400" />
                                <span className="text-[11px] font-mono text-red-400">
                                    Failed
                                </span>
                            </div>
                        )}
                    </div>

                    {/* Running Stage Indicator */}
                    {isRunning && currentStage && (
                        <div className="flex items-center gap-2 mt-2.5 px-2.5 py-1 rounded-lg bg-blue-500/10 border border-blue-500/20 w-fit">
                            <span className="h-2 w-2 rounded-full bg-blue-500" />
                            <span className="text-xs text-blue-300">
                                {getStageDisplay(currentStage, stageMessage)}
                            </span>
                        </div>
                    )}
                </div>

                {/* Right: Action Buttons */}
                <div className="flex flex-col items-end gap-2 shrink-0 ml-4">
                    <div className="flex flex-row items-center gap-2">
                        {/* Stop Button */}
                        {isRunning && generationResult?.generationId && (
                            <Button
                                onClick={() => onStop(generationResult.generationId!)}
                                variant="destructive"
                                className="h-9 px-4 text-sm font-medium"
                            >
                                <Square className="h-4 w-4 mr-2" />
                                Stop
                            </Button>
                        )}

                        {/* Generate / Retry / Regenerate Button */}
                        {renderGenerateButton()}
                    </div>

                    {/* Status Text */}
                    {generationError && !isGenerating && !isRunning && (
                        <span className="text-[10px] text-red-400 max-w-[200px] text-right">
                            Failed:{' '}
                            {generationError.length > 50
                                ? generationError.substring(0, 50) + '...'
                                : generationError}
                        </span>
                    )}
                    {wasCancelled && !isGenerating && !isRunning && !generationError && (
                        <span className="text-[10px] text-yellow-400">Cancelled</span>
                    )}
                    {wasGenerated && !isGenerating && !isRunning && !generationError && !wasCancelled && (
                        <span className="text-[10px]" style={{ color: 'var(--text-tertiary)' }}>
                            Last generated: {formatTimeAgo(wasGenerated)}
                        </span>
                    )}
                </div>
            </div>

            {/* Agent Log Viewer */}
            <AgentLogViewer
                generationId={generationResult?.generationId}
                isRunning={isRunning}
            />

            {/* Requirements Section */}
            <div className="flex-1"
                 style={{ minHeight: 0, overflowY: 'auto', scrollbarWidth: 'thin', scrollbarColor: 'var(--surface-active) transparent' }}>
                <div className="space-y-6 max-w-2xl px-5 py-4">
                    {/* Section Header */}
                    <div>
                        <div
                            className="flex items-center gap-2 mb-3 font-medium text-sm"
                            style={{ color: 'var(--text-secondary)' }}
                        >
                            <List className="h-4 w-4" style={{ color: 'var(--primary)' }} />
                            Requirements
                        </div>

                        <div className="bg-white/[0.02] rounded-xl p-1">
                            {feature.requirements?.length > 0 ? (
                                <ul className="flex flex-col gap-1">
                                    {feature.requirements.map((req, i) => (
                                        <li
                                            key={i}
                                            className="relative flex gap-3 p-4 rounded-lg border transition-all duration-200 group hover:-translate-y-[1px]"
                                            style={{
                                                background: 'var(--surface)',
                                                borderColor: 'var(--border)',
                                            }}
                                            onMouseEnter={e => {
                                                e.currentTarget.style.borderColor = 'var(--border-bright)';
                                                e.currentTarget.style.boxShadow = 'var(--shadow-card)';
                                            }}
                                            onMouseLeave={e => {
                                                e.currentTarget.style.borderColor = 'var(--border)';
                                                e.currentTarget.style.boxShadow = 'none';
                                            }}
                                        >
                                            {/* Left accent border */}
                                            <div
                                                className="absolute left-0 top-2 bottom-2 w-[2px] rounded-full"
                                                style={{
                                                    background: 'var(--primary)',
                                                    opacity: 0.3,
                                                }}
                                            />
                                            <Badge
                                                variant="outline"
                                                className="shrink-0 h-6 px-2 text-[10px] font-mono"
                                                style={{
                                                    background:
                                                        'linear-gradient(135deg, rgba(59,130,246,0.15), rgba(192,132,252,0.1))',
                                                    borderColor: 'rgba(59,130,246,0.3)',
                                                    color: 'var(--primary)',
                                                }}
                                            >
                                                REQ-{i + 1}
                                            </Badge>
                                            {editingIndex === i ? (
                                                <div className="flex-1 flex flex-col gap-2">
                                                    <textarea
                                                        className="w-full rounded-md px-3 py-2 text-sm resize-none focus:outline-none focus:ring-1 focus:ring-blue-500/50"
                                                        style={{ border: '1px solid var(--border-bright)', background: 'rgba(0,0,0,0.25)', color: 'var(--text)' }}
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
                                                            className="flex items-center gap-1 px-2.5 py-1 rounded-md text-xs font-medium bg-blue-600 text-white hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                                                        >
                                                            <Check className="h-3 w-3" /> Save
                                                        </button>
                                                        <button
                                                            onClick={handleCancelEdit}
                                                            disabled={isSaving}
                                                            className="flex items-center gap-1 px-2.5 py-1 rounded-md text-xs font-medium hover:bg-white/10 transition-colors"
                                                            style={{ color: 'var(--text-secondary)' }}
                                                        >
                                                            <X className="h-3 w-3" /> Cancel
                                                        </button>
                                                    </div>
                                                </div>
                                            ) : (
                                                <>
                                                    <span
                                                        className="text-sm leading-relaxed flex-1"
                                                        style={{ color: 'var(--text-secondary)' }}
                                                    >
                                                        {req}
                                                    </span>
                                                    <div className="shrink-0 flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                                                        <button
                                                            onClick={() => handleStartEdit(i, req)}
                                                            className="btn-icon"
                                                            style={{ width: 28, height: 28, color: 'var(--text-secondary)' }}
                                                            title="Edit requirement"
                                                        >
                                                            <Pencil size={14} />
                                                        </button>
                                                        <button
                                                            onClick={() => handleDelete(i)}
                                                            className="btn-icon"
                                                            style={{ width: 28, height: 28, color: 'var(--danger)' }}
                                                            title="Delete requirement"
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
                                <div
                                    className="p-8 text-center italic text-sm"
                                    style={{ color: 'var(--text-tertiary)' }}
                                >
                                    No specific requirements extracted yet.
                                </div>
                            )}

                            {/* Add Requirement */}
                            {isAdding ? (
                                <div className="mt-2 p-4 rounded-lg border" style={{ borderColor: 'var(--border-bright)', background: 'var(--surface)' }}>
                                    <textarea
                                        className="w-full rounded-md px-3 py-2 text-sm resize-none focus:outline-none focus:ring-1 focus:ring-blue-500/50"
                                        style={{ border: '1px solid var(--border-bright)', background: 'rgba(0,0,0,0.25)', color: 'var(--text)' }}
                                        value={newReqText}
                                        onChange={e => setNewReqText(e.target.value)}
                                        onKeyDown={e => {
                                            if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSaveAdd(); }
                                            if (e.key === 'Escape') handleCancelAdd();
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
                                            className="flex items-center gap-1 px-2.5 py-1 rounded-md text-xs font-medium bg-blue-600 text-white hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                                        >
                                            <Check className="h-3 w-3" /> Add
                                        </button>
                                        <button
                                            onClick={handleCancelAdd}
                                            disabled={isSaving}
                                            className="flex items-center gap-1 px-2.5 py-1 rounded-md text-xs font-medium hover:bg-white/10 transition-colors"
                                            style={{ color: 'var(--text-secondary)' }}
                                        >
                                            <X className="h-3 w-3" /> Cancel
                                        </button>
                                    </div>
                                </div>
                            ) : (
                                <button
                                    onClick={handleStartAdd}
                                    className="mt-2 flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs font-medium transition-colors hover:bg-white/5"
                                    style={{ color: 'var(--text-tertiary)' }}
                                >
                                    <Plus className="h-3.5 w-3.5" />
                                    Add Requirement
                                </button>
                            )}
                        </div>
                    </div>

                    {/* Merged From Section */}
                    {feature.merged_from && feature.merged_from.length > 0 && (
                        <div>
                            <details className="group">
                                <summary
                                    className="flex items-center gap-2 mb-2 text-xs cursor-pointer transition-colors"
                                    style={{ color: 'var(--text-tertiary)' }}
                                >
                                    <ChevronRight className="h-3 w-3 group-open:rotate-90 transition-transform" />
                                    Consolidated from {feature.merged_from.length} sub-features
                                </summary>
                                <div className="ml-5 flex flex-wrap gap-2">
                                    {feature.merged_from.map((sub, i) => (
                                        <Badge
                                            key={i}
                                            variant="secondary"
                                            className="text-xs bg-slate-700/50 text-slate-400 border-slate-600"
                                        >
                                            {sub}
                                        </Badge>
                                    ))}
                                </div>
                            </details>
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}
