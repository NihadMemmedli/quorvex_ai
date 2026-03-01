'use client';
import React, { useRef, useCallback, useState } from 'react';
import { Plus, Search, RefreshCw } from 'lucide-react';
import { ApiSpecSortOption, ApiSpecStatusFilter } from './types';

interface ApiSpecsToolbarProps {
    search: string;
    onSearchChange: (value: string) => void;
    statusFilter: ApiSpecStatusFilter;
    onStatusFilterChange: (filter: ApiSpecStatusFilter) => void;
    sortBy: ApiSpecSortOption;
    onSortChange: (sort: ApiSpecSortOption) => void;
    folder: string;
    onFolderChange: (folder: string) => void;
    folders: string[];
    tags: string[];
    selectedTags: string[];
    onTagsChange: (tags: string[]) => void;
    onCreateClick: () => void;
    onRefresh: () => void;
    totalShowing: number;
    totalSpecs: number;
}

const selectStyle: React.CSSProperties = {
    padding: '0.4rem 0.6rem',
    background: 'var(--surface)',
    border: '1px solid var(--border)',
    borderRadius: 'var(--radius)',
    color: 'var(--text-primary)',
    fontSize: '0.8rem',
    cursor: 'pointer',
};

const STATUS_OPTIONS: { value: ApiSpecStatusFilter; label: string }[] = [
    { value: 'all', label: 'All Status' },
    { value: 'passed', label: 'Passed' },
    { value: 'failed', label: 'Failed' },
    { value: 'not_run', label: 'Not Run' },
    { value: 'no_tests', label: 'No Tests' },
];

const SORT_OPTIONS: { value: ApiSpecSortOption; label: string }[] = [
    { value: 'name', label: 'Name' },
    { value: 'status', label: 'Status' },
    { value: 'last_run', label: 'Last Run' },
    { value: 'test_count', label: 'Test Count' },
    { value: 'modified', label: 'Modified' },
];

export default function ApiSpecsToolbar({
    search,
    onSearchChange,
    statusFilter,
    onStatusFilterChange,
    sortBy,
    onSortChange,
    folder,
    onFolderChange,
    folders,
    onCreateClick,
    onRefresh,
    totalShowing,
    totalSpecs,
}: ApiSpecsToolbarProps) {
    const [localSearch, setLocalSearch] = useState(search);
    const searchTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

    const handleSearchInput = useCallback((value: string) => {
        setLocalSearch(value);
        if (searchTimeoutRef.current) clearTimeout(searchTimeoutRef.current);
        searchTimeoutRef.current = setTimeout(() => {
            onSearchChange(value);
        }, 300);
    }, [onSearchChange]);

    return (
        <div style={{
            display: 'flex',
            gap: '0.5rem',
            alignItems: 'center',
            flexWrap: 'wrap',
            marginBottom: '1rem',
        }}>
            {/* Create button */}
            <button
                onClick={onCreateClick}
                style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '0.5rem',
                    padding: '0.5rem 1rem',
                    background: 'var(--primary)',
                    color: 'white',
                    border: 'none',
                    borderRadius: 'var(--radius)',
                    cursor: 'pointer',
                    fontWeight: 600,
                    fontSize: '0.85rem',
                }}
            >
                <Plus size={14} /> Create
            </button>

            {/* Search input */}
            <div style={{ position: 'relative', flex: '1 1 180px', maxWidth: '250px' }}>
                <Search size={14} style={{
                    position: 'absolute', left: '0.6rem', top: '50%',
                    transform: 'translateY(-50%)', color: 'var(--text-secondary)',
                }} />
                <input
                    type="text"
                    placeholder="Search specs..."
                    value={localSearch}
                    onChange={e => handleSearchInput(e.target.value)}
                    style={{
                        width: '100%',
                        padding: '0.4rem 0.5rem 0.4rem 2rem',
                        background: 'var(--surface)',
                        border: '1px solid var(--border)',
                        borderRadius: 'var(--radius)',
                        color: 'var(--text-primary)',
                        fontSize: '0.8rem',
                    }}
                />
            </div>

            {/* Status filter */}
            <select
                value={statusFilter}
                onChange={e => onStatusFilterChange(e.target.value as ApiSpecStatusFilter)}
                style={selectStyle}
            >
                {STATUS_OPTIONS.map(opt => (
                    <option key={opt.value} value={opt.value}>{opt.label}</option>
                ))}
            </select>

            {/* Folder filter */}
            {folders.length > 0 && (
                <select
                    value={folder}
                    onChange={e => onFolderChange(e.target.value)}
                    style={selectStyle}
                >
                    <option value="">All Folders</option>
                    {folders.map(f => (
                        <option key={f} value={f}>{f}</option>
                    ))}
                </select>
            )}

            {/* Sort */}
            <select
                value={sortBy}
                onChange={e => onSortChange(e.target.value as ApiSpecSortOption)}
                style={selectStyle}
            >
                {SORT_OPTIONS.map(opt => (
                    <option key={opt.value} value={opt.value}>{opt.label}</option>
                ))}
            </select>

            {/* Refresh */}
            <button
                onClick={onRefresh}
                title="Refresh"
                style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    padding: '0.4rem',
                    background: 'var(--surface)',
                    border: '1px solid var(--border)',
                    borderRadius: 'var(--radius)',
                    cursor: 'pointer',
                    color: 'var(--text-secondary)',
                }}
            >
                <RefreshCw size={14} />
            </button>

            {/* Count */}
            <span style={{
                fontSize: '0.8rem',
                color: 'var(--text-secondary)',
                marginLeft: 'auto',
            }}>
                {totalShowing} of {totalSpecs} specs
            </span>
        </div>
    );
}
