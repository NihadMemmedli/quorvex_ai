'use client';

import React, { useState, useMemo } from 'react';

import { Input } from '@/components/ui/input';
import { Search, Layers, CheckCircle, Loader2, XCircle, Minus, Play } from 'lucide-react';
import type { Feature, GenerationResult } from './types';
import { getFeatureStatus } from './types';

interface FeatureSidebarProps {
    features: Feature[];
    selectedFeature: Feature | null;
    onSelect: (f: Feature) => void;
    generationResults: Record<string, GenerationResult>;
    onBatchGenerate: () => void;
    isGenerating: boolean;
    generationBlockedReason?: string | null;
}

type StatusKey = 'completed' | 'running' | 'failed' | 'pending';

const statusBorderColor: Record<StatusKey, string> = {
    completed: '#34d399',
    running: '#3b82f6',
    failed: '#f87171',
    pending: 'transparent',
};

const statusIcon: Record<StatusKey, React.ReactNode> = {
    completed: <CheckCircle className="h-3.5 w-3.5 text-green-400" />,
    running: <Loader2 className="h-3.5 w-3.5 text-blue-400 animate-spin" />,
    failed: <XCircle className="h-3.5 w-3.5 text-red-400" />,
    pending: <Minus className="h-3.5 w-3.5" style={{ color: 'var(--text-tertiary)' }} />,
};

const statusIconBg: Record<StatusKey, string> = {
    completed: 'rgba(52, 211, 153, 0.1)',
    running: 'rgba(59, 130, 246, 0.1)',
    failed: 'rgba(248, 113, 113, 0.1)',
    pending: 'rgba(100, 116, 139, 0.1)',
};

export function FeatureSidebar({
    features,
    selectedFeature,
    onSelect,
    generationResults,
    onBatchGenerate,
    isGenerating,
    generationBlockedReason,
}: FeatureSidebarProps) {
    const [searchTerm, setSearchTerm] = useState('');

    const testableFeatures = useMemo(
        () => features.filter(f => f.requirements && f.requirements.length > 0),
        [features]
    );

    const filteredFeatures = useMemo(
        () =>
            searchTerm
                ? testableFeatures.filter(f =>
                      f.name.toLowerCase().includes(searchTerm.toLowerCase())
                  )
                : testableFeatures,
        [testableFeatures, searchTerm]
    );

    const pendingCount = useMemo(
        () => testableFeatures.filter(f => getFeatureStatus(generationResults[f.name]) === 'pending').length,
        [testableFeatures, generationResults]
    );

    const isDisabled = Boolean(generationBlockedReason) || isGenerating || pendingCount === 0;

    return (
        <div className="prd-feature-sidebar flex flex-col">
            <style>{`
                .prd-sidebar-count {
                    display: inline-flex;
                    align-items: center;
                    justify-content: center;
                    height: 18px;
                    min-width: 18px;
                    padding: 0 0.375rem;
                    border-radius: 999px;
                    font-size: 10px;
                    font-family: var(--font-mono);
                    font-weight: 600;
                }

                .prd-sidebar-batch {
                    display: inline-flex;
                    align-items: center;
                    justify-content: center;
                    gap: 0.375rem;
                    height: 32px;
                    padding: 0 0.625rem;
                    border: 1px solid transparent;
                    border-radius: 7px;
                    font-size: 0.75rem;
                    font-weight: 700;
                    line-height: 1;
                    white-space: nowrap;
                }

                .prd-sidebar-batch:disabled {
                    pointer-events: none;
                    opacity: 0.45;
                }

                .prd-sidebar-batch:focus-visible,
                .prd-feature-row:focus-visible {
                    outline: none;
                    box-shadow: 0 0 0 2px rgba(59,130,246,0.45);
                }

                .prd-feature-row:focus-visible {
                    outline: 2px solid rgba(59,130,246,0.55);
                    outline-offset: -2px;
                }

                .prd-sidebar-search {
                    position: relative;
                }

                .prd-sidebar-search-icon {
                    position: absolute;
                    left: 0.625rem;
                    top: 50%;
                    z-index: 1;
                    transform: translateY(-50%);
                    pointer-events: none;
                }

                .prd-feature-list {
                    display: flex;
                    flex-direction: column;
                    gap: 0.25rem;
                    padding: 0.625rem;
                }

                .prd-feature-row {
                    position: relative;
                    width: 100%;
                    padding: 0.625rem;
                    border: 0;
                    border-radius: 7px;
                    text-align: left;
                    transition: background-color 0.2s, box-shadow 0.2s;
                }

                .prd-feature-row:hover {
                    background: rgba(255,255,255,0.03);
                }

                .prd-status-dot {
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    width: 24px;
                    height: 24px;
                    flex: 0 0 24px;
                    border-radius: 999px;
                }
            `}</style>
            {/* Sticky Header */}
            <div
                className="border-b p-3"
                style={{ borderColor: 'var(--border-subtle)' }}
            >
                {/* Title Row */}
                <div className="mb-3 flex items-center justify-between gap-2">
                    <h3
                        className="font-semibold text-xs flex min-w-0 items-center uppercase tracking-wider"
                        style={{ color: 'var(--text-secondary)' }}
                    >
                        <Layers size={14} style={{ color: 'var(--primary)', marginRight: '8px' }} className="shrink-0" />
                        <span>Features</span>
                        <span
                            className="prd-sidebar-count"
                            style={{
                                background: 'rgba(59,130,246,0.12)',
                                color: 'var(--primary)',
                                marginLeft: '8px',
                            }}
                        >
                            {filteredFeatures.length}
                        </span>
                    </h3>

                    {/* Batch Generate Button */}
                    <button
                        type="button"
                        onClick={onBatchGenerate}
                        disabled={isDisabled}
                        className={`prd-sidebar-batch ${isDisabled ? '' : 'btn-primary'}`}
                        style={isDisabled ? { background: 'rgba(255,255,255,0.06)', color: 'var(--text-tertiary)' } : undefined}
                        title={generationBlockedReason || undefined}
                    >
                        <Play size={13} fill="currentColor" className="shrink-0" />
                        <span>Generate All</span>
                        <span className="text-[11px] font-mono opacity-70">
                            {pendingCount}
                        </span>
                    </button>
                </div>

                {/* Search Input */}
                <div className="prd-sidebar-search">
                    <Search
                        size={14}
                        className="prd-sidebar-search-icon"
                        style={{ color: 'var(--text-tertiary)' }}
                    />
                    <Input
                        placeholder="Search features..."
                        value={searchTerm}
                        onChange={e => setSearchTerm(e.target.value)}
                        className="text-xs border-white/[0.06] focus:shadow-[0_0_0_2px_rgba(59,130,246,0.1)] backdrop-blur-sm"
                        style={{
                            height: 32,
                            paddingLeft: '2rem',
                            background: 'rgba(255,255,255,0.03)',
                        }}
                    />
                </div>
            </div>

            {/* Feature List */}
            <div className="flex-1"
                 style={{ minHeight: 0, overflowY: 'auto', scrollbarWidth: 'thin', scrollbarColor: 'var(--surface-active) transparent' }}>
                <div className="prd-feature-list">
                    {filteredFeatures.map(f => {
                        const isSelected = selectedFeature?.slug === f.slug;
                        const status = getFeatureStatus(generationResults[f.name]);

                        return (
                            <button
                                key={f.slug}
                                onClick={() => onSelect(f)}
                                className="prd-feature-row"
                                style={{
                                    borderLeft: `2px solid ${isSelected ? 'var(--primary)' : statusBorderColor[status]}`,
                                    ...(isSelected
                                        ? {
                                              background: 'rgba(59,130,246,0.08)',
                                              boxShadow: '0 0 0 1px rgba(59,130,246,0.15)',
                                          }
                                        : {}),
                                }}
                            >
                                <div className="flex items-center justify-between gap-2">
                                    {/* Feature Name */}
                                    <div className="min-w-0 flex-1">
                                        <div
                                            className="text-sm font-medium truncate"
                                            style={{
                                                color: isSelected ? 'var(--text)' : 'var(--text-secondary)',
                                            }}
                                        >
                                            {f.name}
                                        </div>
                                        <div
                                            className="text-[10px] font-mono mt-0.5"
                                            style={{
                                                color: isSelected ? 'var(--primary)' : 'var(--text-tertiary)',
                                            }}
                                        >
                                            {f.requirements?.length || 0} requirements
                                        </div>
                                    </div>

                                    {/* Status Icon Circle */}
                                    <div
                                        className="prd-status-dot"
                                        style={{ background: statusIconBg[status] }}
                                    >
                                        {statusIcon[status]}
                                    </div>
                                </div>
                            </button>
                        );
                    })}

                    {/* Empty search state */}
                    {filteredFeatures.length === 0 && searchTerm && (
                        <div
                            className="p-8 text-center text-sm"
                            style={{ color: 'var(--text-tertiary)' }}
                        >
                            No features match &quot;{searchTerm}&quot;
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}
