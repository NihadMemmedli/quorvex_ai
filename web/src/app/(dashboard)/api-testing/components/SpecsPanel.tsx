'use client';
import React, { useState, useCallback, useMemo } from 'react';
import { Loader2, Zap } from 'lucide-react';
import { API_BASE } from '@/lib/api';
import { ApiSpec, ApiSpecsSummary, ApiSpecSortOption, ApiSpecStatusFilter, JobStatus, ApiTestRun } from './types';

import ApiSpecsSummaryBar from './ApiSpecsSummaryBar';
import ApiSpecsToolbar from './ApiSpecsToolbar';
import ApiSpecsTable from './ApiSpecsTable';
import ApiSpecsFolderTree from './ApiSpecsFolderTree';
import ApiSpecsBulkBar from './ApiSpecsBulkBar';
import ApiSpecsCreateModal from './ApiSpecsCreateModal';
import ApiSpecsPagination from './ApiSpecsPagination';

// ========== Props ==========

interface SpecsPanelProps {
    projectId: string;
    apiSpecs: ApiSpec[];
    specsLoading: boolean;
    activeJobs: Record<string, JobStatus>;
    specJobMap: Record<string, string>;
    latestRuns: Record<string, ApiTestRun>;
    message: { type: 'success' | 'error'; text: string } | null;
    setMessage: (msg: { type: 'success' | 'error'; text: string } | null) => void;
    setActiveJobs: React.Dispatch<React.SetStateAction<Record<string, JobStatus>>>;
    setSpecJobMap: React.Dispatch<React.SetStateAction<Record<string, string>>>;
    fetchApiSpecs: (offset?: number, append?: boolean, search?: string, sort?: string, statusFilter?: string, folder?: string, tags?: string) => Promise<void>;
    fetchGeneratedTests: (offset?: number, append?: boolean, search?: string) => Promise<void>;
    fetchLatestRuns: () => Promise<void>;
    pollJob: (jobId: string, onComplete?: () => void) => void;
    navigateToTest: (testName: string) => void;
    showCreateModal: boolean;
    setShowCreateModal: (v: boolean) => void;
    specsTotal: number;
    specsHasMore: boolean;
    // New enriched data from backend
    folders: string[];
    summary: ApiSpecsSummary | null;
}

const PAGE_SIZE_DEFAULT = 50;

export default function SpecsPanel({
    projectId,
    apiSpecs,
    specsLoading,
    activeJobs,
    specJobMap,
    latestRuns,
    setMessage,
    setActiveJobs,
    setSpecJobMap,
    fetchApiSpecs,
    fetchGeneratedTests,
    fetchLatestRuns,
    pollJob,
    navigateToTest,
    showCreateModal,
    setShowCreateModal,
    specsTotal,
    folders,
    summary,
}: SpecsPanelProps) {
    // Local filter/sort state
    const [search, setSearch] = useState('');
    const [statusFilter, setStatusFilter] = useState<ApiSpecStatusFilter>('all');
    const [sortBy, setSortBy] = useState<ApiSpecSortOption>('name');
    const [folder, setFolder] = useState('');
    const [selectedTags, setSelectedTags] = useState<string[]>([]);
    const [selectedSpecs, setSelectedSpecs] = useState<Set<string>>(new Set());
    const [currentPage, setCurrentPage] = useState(1);
    const [pageSize, setPageSize] = useState(PAGE_SIZE_DEFAULT);

    // Compute all unique tags from specs
    const allTags = useMemo(() => {
        const tagSet = new Set<string>();
        apiSpecs.forEach(s => s.tags?.forEach(t => tagSet.add(t)));
        return Array.from(tagSet).sort();
    }, [apiSpecs]);

    // Compute folder spec counts
    const folderCounts = useMemo(() => {
        const counts: Record<string, number> = {};
        apiSpecs.forEach(s => {
            const f = s.folder || '';
            if (f) counts[f] = (counts[f] || 0) + 1;
        });
        return counts;
    }, [apiSpecs]);

    // Refresh with current filters
    const refresh = useCallback((page = 1, newPageSize?: number) => {
        const size = newPageSize ?? pageSize;
        const offset = (page - 1) * size;
        fetchApiSpecs(
            offset, false,
            search || undefined,
            sortBy,
            statusFilter === 'all' ? undefined : statusFilter,
            folder || undefined,
            selectedTags.length > 0 ? selectedTags.join(',') : undefined,
        );
    }, [fetchApiSpecs, search, sortBy, statusFilter, folder, selectedTags, pageSize]);

    const handleSearchChange = useCallback((value: string) => {
        setSearch(value);
        setCurrentPage(1);
        setSelectedSpecs(new Set());
        fetchApiSpecs(
            0, false, value || undefined, sortBy,
            statusFilter === 'all' ? undefined : statusFilter,
            folder || undefined,
            selectedTags.length > 0 ? selectedTags.join(',') : undefined,
        );
    }, [fetchApiSpecs, sortBy, statusFilter, folder, selectedTags]);

    const handleStatusFilterChange = useCallback((newFilter: ApiSpecStatusFilter) => {
        const resolved = newFilter === statusFilter ? 'all' : newFilter;
        setStatusFilter(resolved);
        setCurrentPage(1);
        setSelectedSpecs(new Set());
        fetchApiSpecs(
            0, false, search || undefined, sortBy,
            resolved === 'all' ? undefined : resolved,
            folder || undefined,
            selectedTags.length > 0 ? selectedTags.join(',') : undefined,
        );
    }, [fetchApiSpecs, search, sortBy, statusFilter, folder, selectedTags]);

    const handleSortChange = useCallback((newSort: ApiSpecSortOption) => {
        setSortBy(newSort);
        setCurrentPage(1);
        fetchApiSpecs(
            0, false, search || undefined, newSort,
            statusFilter === 'all' ? undefined : statusFilter,
            folder || undefined,
            selectedTags.length > 0 ? selectedTags.join(',') : undefined,
        );
    }, [fetchApiSpecs, search, statusFilter, folder, selectedTags]);

    const handleFolderChange = useCallback((newFolder: string) => {
        setFolder(newFolder);
        setCurrentPage(1);
        setSelectedSpecs(new Set());
        fetchApiSpecs(
            0, false, search || undefined, sortBy,
            statusFilter === 'all' ? undefined : statusFilter,
            newFolder || undefined,
            selectedTags.length > 0 ? selectedTags.join(',') : undefined,
        );
    }, [fetchApiSpecs, search, sortBy, statusFilter, selectedTags]);

    const handlePageChange = useCallback((page: number) => {
        setCurrentPage(page);
        setSelectedSpecs(new Set());
        const offset = (page - 1) * pageSize;
        fetchApiSpecs(
            offset, false, search || undefined, sortBy,
            statusFilter === 'all' ? undefined : statusFilter,
            folder || undefined,
            selectedTags.length > 0 ? selectedTags.join(',') : undefined,
        );
    }, [fetchApiSpecs, pageSize, search, sortBy, statusFilter, folder, selectedTags]);

    const handlePageSizeChange = useCallback((newSize: number) => {
        setPageSize(newSize);
        setCurrentPage(1);
        setSelectedSpecs(new Set());
        fetchApiSpecs(
            0, false, search || undefined, sortBy,
            statusFilter === 'all' ? undefined : statusFilter,
            folder || undefined,
            selectedTags.length > 0 ? selectedTags.join(',') : undefined,
        );
    }, [fetchApiSpecs, search, sortBy, statusFilter, folder, selectedTags]);

    const handleRefresh = useCallback(() => {
        refresh(currentPage);
        fetchLatestRuns();
    }, [refresh, currentPage, fetchLatestRuns]);

    // Bulk actions
    const hasRunningJobs = Object.values(activeJobs).some(j => j.status === 'running');

    const handleBulkRun = useCallback(async () => {
        const specPaths = apiSpecs.filter(s => selectedSpecs.has(s.path)).map(s => s.path);
        if (specPaths.length === 0) return;
        try {
            const res = await fetch(`${API_BASE}/api-testing/specs/bulk-run`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ spec_paths: specPaths, project_id: projectId }),
            });
            if (res.ok) {
                const data = await res.json();
                if (data.job_ids) {
                    for (const jobId of data.job_ids) {
                        setActiveJobs(prev => ({ ...prev, [jobId]: { job_id: jobId, status: 'running', message: 'Running...' } }));
                        pollJob(jobId);
                    }
                }
                setMessage({ type: 'success', text: `Started ${specPaths.length} test run(s)` });
                setSelectedSpecs(new Set());
            }
        } catch {
            setMessage({ type: 'error', text: 'Failed to start bulk run' });
        }
    }, [apiSpecs, selectedSpecs, projectId, setActiveJobs, pollJob, setMessage]);

    const handleBulkGenerate = useCallback(async () => {
        const specNames = apiSpecs.filter(s => selectedSpecs.has(s.path)).map(s => s.name);
        if (specNames.length === 0) return;
        try {
            const res = await fetch(`${API_BASE}/api-testing/specs/bulk-generate`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ spec_names: specNames, project_id: projectId }),
            });
            if (res.ok) {
                const data = await res.json();
                if (data.job_ids) {
                    for (const jobId of data.job_ids) {
                        setActiveJobs(prev => ({ ...prev, [jobId]: { job_id: jobId, status: 'running', message: 'Generating...' } }));
                        pollJob(jobId);
                    }
                }
                setMessage({ type: 'success', text: `Started generation for ${specNames.length} spec(s)` });
                setSelectedSpecs(new Set());
            }
        } catch {
            setMessage({ type: 'error', text: 'Failed to start bulk generate' });
        }
    }, [apiSpecs, selectedSpecs, projectId, setActiveJobs, pollJob, setMessage]);

    const handleBulkDelete = useCallback(async () => {
        const toDelete = apiSpecs.filter(s => selectedSpecs.has(s.path));
        if (toDelete.length === 0) return;
        if (!confirm(`Delete ${toDelete.length} spec(s)? This cannot be undone.`)) return;
        let deleted = 0;
        for (const spec of toDelete) {
            try {
                const res = await fetch(`${API_BASE}/api-testing/specs/${spec.name}?project_id=${projectId}`, { method: 'DELETE' });
                if (res.ok) deleted++;
            } catch { /* continue */ }
        }
        setMessage({ type: 'success', text: `Deleted ${deleted} spec(s)` });
        setSelectedSpecs(new Set());
        refresh(1);
    }, [apiSpecs, selectedSpecs, projectId, setMessage, refresh]);

    const totalPages = Math.max(1, Math.ceil(specsTotal / pageSize));

    return (
        <>
            {/* Summary Stats */}
            <ApiSpecsSummaryBar
                summary={summary}
                activeFilter={statusFilter}
                onFilterChange={handleStatusFilterChange}
            />

            {/* Toolbar */}
            <ApiSpecsToolbar
                search={search}
                onSearchChange={handleSearchChange}
                statusFilter={statusFilter}
                onStatusFilterChange={handleStatusFilterChange}
                sortBy={sortBy}
                onSortChange={handleSortChange}
                folder={folder}
                onFolderChange={handleFolderChange}
                folders={folders}
                tags={allTags}
                selectedTags={selectedTags}
                onTagsChange={setSelectedTags}
                onCreateClick={() => setShowCreateModal(true)}
                onRefresh={handleRefresh}
                totalShowing={apiSpecs.length}
                totalSpecs={specsTotal}
            />

            {/* Main content: optional folder tree + table */}
            <div style={{ display: 'flex', gap: '1rem' }}>
                {/* Folder tree sidebar */}
                {folders.length > 0 && (
                    <ApiSpecsFolderTree
                        folders={folders}
                        activeFolder={folder}
                        onFolderChange={handleFolderChange}
                        specCounts={folderCounts}
                        totalCount={specsTotal}
                        projectId={projectId}
                        setMessage={setMessage}
                    />
                )}

                {/* Table */}
                <div style={{ flex: 1, minWidth: 0 }}>
                    <ApiSpecsTable
                        specs={apiSpecs}
                        loading={specsLoading}
                        selectedSpecs={selectedSpecs}
                        onSelectionChange={setSelectedSpecs}
                        activeJobs={activeJobs}
                        specJobMap={specJobMap}
                        latestRuns={latestRuns}
                        projectId={projectId}
                        setMessage={setMessage}
                        setActiveJobs={setActiveJobs}
                        setSpecJobMap={setSpecJobMap}
                        pollJob={pollJob}
                        navigateToTest={navigateToTest}
                        fetchApiSpecs={() => refresh(currentPage)}
                        fetchGeneratedTests={() => fetchGeneratedTests(0)}
                        fetchLatestRuns={fetchLatestRuns}
                    />

                    {/* Pagination */}
                    <ApiSpecsPagination
                        currentPage={currentPage}
                        totalPages={totalPages}
                        pageSize={pageSize}
                        totalItems={specsTotal}
                        onPageChange={handlePageChange}
                        onPageSizeChange={handlePageSizeChange}
                    />
                </div>
            </div>

            {/* Bulk action bar */}
            <ApiSpecsBulkBar
                selectedCount={selectedSpecs.size}
                onClear={() => setSelectedSpecs(new Set())}
                onBulkRun={handleBulkRun}
                onBulkGenerate={handleBulkGenerate}
                onBulkDelete={handleBulkDelete}
                isRunning={hasRunningJobs}
            />

            {/* Create modal */}
            {showCreateModal && (
                <ApiSpecsCreateModal
                    projectId={projectId}
                    onClose={() => setShowCreateModal(false)}
                    onCreated={() => {
                        setShowCreateModal(false);
                        refresh(1);
                    }}
                    setMessage={setMessage}
                />
            )}
        </>
    );
}
