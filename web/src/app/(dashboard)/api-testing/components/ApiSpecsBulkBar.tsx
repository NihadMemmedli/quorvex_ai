'use client';
import React from 'react';
import { X, Play, Zap, Trash2 } from 'lucide-react';

interface ApiSpecsBulkBarProps {
    selectedCount: number;
    onClear: () => void;
    onBulkRun: () => void;
    onBulkGenerate: () => void;
    onBulkDelete: () => void;
    isRunning: boolean;
}

export default function ApiSpecsBulkBar({
    selectedCount,
    onClear,
    onBulkRun,
    onBulkGenerate,
    onBulkDelete,
    isRunning,
}: ApiSpecsBulkBarProps) {
    if (selectedCount === 0) return null;

    return (
        <div style={{
            position: 'fixed',
            bottom: '1.5rem',
            left: '50%',
            transform: 'translateX(-50%)',
            display: 'flex',
            alignItems: 'center',
            gap: '0.75rem',
            padding: '0.75rem 1.25rem',
            background: 'var(--surface)',
            border: '1px solid var(--border)',
            borderRadius: '999px',
            boxShadow: '0 4px 24px rgba(0,0,0,0.3)',
            zIndex: 100,
        }}>
            <span style={{ fontWeight: 600, fontSize: '0.85rem', color: 'var(--text-primary)' }}>
                {selectedCount} spec{selectedCount !== 1 ? 's' : ''} selected
            </span>

            {/* Clear */}
            <button
                onClick={onClear}
                style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '0.3rem',
                    padding: '0.35rem 0.65rem',
                    background: 'transparent',
                    border: '1px solid var(--border)',
                    borderRadius: 'var(--radius)',
                    cursor: 'pointer',
                    color: 'var(--text-secondary)',
                    fontSize: '0.8rem',
                }}
            >
                <X size={13} /> Clear
            </button>

            {/* Generate All */}
            <button
                onClick={onBulkGenerate}
                disabled={isRunning}
                style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '0.3rem',
                    padding: '0.35rem 0.75rem',
                    background: 'rgba(139, 92, 246, 0.9)',
                    border: 'none',
                    borderRadius: 'var(--radius)',
                    cursor: isRunning ? 'not-allowed' : 'pointer',
                    color: '#fff',
                    fontSize: '0.8rem',
                    fontWeight: 600,
                    opacity: isRunning ? 0.5 : 1,
                }}
            >
                <Zap size={13} /> Generate All
            </button>

            {/* Run All */}
            <button
                onClick={onBulkRun}
                disabled={isRunning}
                style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '0.3rem',
                    padding: '0.35rem 0.75rem',
                    background: 'var(--success)',
                    border: 'none',
                    borderRadius: 'var(--radius)',
                    cursor: isRunning ? 'not-allowed' : 'pointer',
                    color: '#fff',
                    fontSize: '0.8rem',
                    fontWeight: 600,
                    opacity: isRunning ? 0.5 : 1,
                }}
            >
                <Play size={13} /> Run All
            </button>

            {/* Delete */}
            <button
                onClick={onBulkDelete}
                disabled={isRunning}
                style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '0.3rem',
                    padding: '0.35rem 0.75rem',
                    background: 'rgba(239, 68, 68, 0.9)',
                    border: 'none',
                    borderRadius: 'var(--radius)',
                    cursor: isRunning ? 'not-allowed' : 'pointer',
                    color: '#fff',
                    fontSize: '0.8rem',
                    fontWeight: 600,
                    opacity: isRunning ? 0.5 : 1,
                }}
            >
                <Trash2 size={13} /> Delete
            </button>
        </div>
    );
}
