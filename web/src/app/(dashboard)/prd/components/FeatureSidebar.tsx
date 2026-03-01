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

    const completedCount = useMemo(
        () => testableFeatures.filter(f => getFeatureStatus(generationResults[f.name]) === 'completed').length,
        [testableFeatures, generationResults]
    );

    const pendingCount = useMemo(
        () => testableFeatures.filter(f => getFeatureStatus(generationResults[f.name]) === 'pending').length,
        [testableFeatures, generationResults]
    );

    const isDisabled = isGenerating || pendingCount === 0;

    return (
        <div className="card-elevated w-[300px] shrink-0 flex flex-col" style={{ padding: 0, overflow: 'hidden' }}>
            {/* Sticky Header */}
            <div
                className="p-4 border-b"
                style={{ borderColor: 'var(--border)' }}
            >
                {/* Title Row */}
                <div className="flex items-center justify-between mb-1.5">
                    <h3
                        className="font-semibold text-xs flex items-center uppercase tracking-wider"
                        style={{ color: 'var(--text-secondary)' }}
                    >
                        <Layers size={14} style={{ color: 'var(--primary)', marginRight: '8px' }} className="shrink-0" />
                        <span>Features</span>
                        <span
                            className="inline-flex items-center justify-center h-[18px] min-w-[18px] px-1.5 rounded-full text-[10px] font-mono font-medium"
                            style={{
                                background: 'rgba(59,130,246,0.12)',
                                color: 'var(--primary)',
                                marginLeft: '8px',
                            }}
                        >
                            {filteredFeatures.length}/{testableFeatures.length}
                        </span>
                    </h3>
                </div>

                {/* Completed Count */}
                <div className="flex items-center justify-between mb-3">
                    <span
                        className="text-[10px] font-mono"
                        style={{ color: 'var(--text-tertiary)' }}
                    >
                        {completedCount}/{testableFeatures.length} completed
                    </span>

                    {/* Batch Generate Button */}
                    <button
                        onClick={onBatchGenerate}
                        disabled={isDisabled}
                        className={`btn btn-primary shrink-0 whitespace-nowrap disabled:opacity-40 disabled:pointer-events-none ${isDisabled ? '!bg-white/[0.06] !text-slate-500' : ''}`}
                        style={{ padding: '0.4rem 0.85rem', fontSize: '0.8rem' }}
                    >
                        <Play size={14} fill="currentColor" className="shrink-0" />
                        <span>Generate All</span>
                        <span className="text-[11px] font-mono opacity-70">
                            {pendingCount}
                        </span>
                    </button>
                </div>

                {/* Search Input */}
                <div className="relative">
                    <Search
                        size={14}
                        className="absolute left-2.5 top-1/2 -translate-y-1/2 z-10"
                        style={{ color: 'var(--text-tertiary)' }}
                    />
                    <Input
                        placeholder="Search features..."
                        value={searchTerm}
                        onChange={e => setSearchTerm(e.target.value)}
                        className="h-8 text-xs border-white/[0.06] focus:shadow-[0_0_0_2px_rgba(59,130,246,0.1)] backdrop-blur-sm"
                        style={{
                            paddingLeft: '2rem',
                            background: 'rgba(255,255,255,0.03)',
                        }}
                    />
                </div>
            </div>

            {/* Feature List */}
            <div className="flex-1"
                 style={{ minHeight: 0, overflowY: 'auto', scrollbarWidth: 'thin', scrollbarColor: 'var(--surface-active) transparent' }}>
                <div className="p-3 flex flex-col gap-1">
                    {filteredFeatures.map(f => {
                        const isSelected = selectedFeature?.slug === f.slug;
                        const status = getFeatureStatus(generationResults[f.name]);

                        return (
                            <button
                                key={f.slug}
                                onClick={() => onSelect(f)}
                                className={`
                                    w-full text-left p-3 rounded-lg transition-all duration-200 relative
                                    ${isSelected ? '' : 'hover:bg-white/[0.03]'}
                                `}
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
                                        className="shrink-0 w-6 h-6 rounded-full flex items-center justify-center"
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
