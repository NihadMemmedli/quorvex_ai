'use client';
import React, { useState, useEffect, useMemo, useCallback, useRef } from 'react';
import { CheckSquare, Search, ChevronDown, ChevronRight, Edit, Trash2, Plus, X, AlertCircle, GitBranch, RefreshCw, Download, Camera, FileText, AlertTriangle, CheckCircle, Circle, Loader2, Sparkles, Copy, Merge, Link2, Unlink } from 'lucide-react';
import { useProject } from '@/contexts/ProjectContext';
import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip, AreaChart, Area, XAxis, YAxis, CartesianGrid } from 'recharts';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import GenerateSpecModal from '@/components/GenerateSpecModal';
import { API_BASE } from '@/lib/api';
import { WorkflowBreadcrumb } from '@/components/workflow/WorkflowBreadcrumb';
import { PageLayout } from '@/components/ui/page-layout';
import { PageHeader } from '@/components/ui/page-header';
import { EmptyState } from '@/components/ui/empty-state';
import { ListPageSkeleton } from '@/components/ui/page-skeleton';

// Types for Requirements tab
interface Requirement {
    id: number;
    req_code: string;
    title: string;
    description: string | null;
    category: string;
    priority: string;
    status: string;
    acceptance_criteria: string[];
    source_session_id: string | null;
    created_at: string;
    updated_at: string;
}

interface Stats {
    total: number;
    by_category: Record<string, number>;
    by_priority: Record<string, number>;
    by_status: Record<string, number>;
}

// Types for Traceability tab (RTM)
interface RtmRequirement {
    id: number;
    code: string;
    title: string;
    description: string | null;
    category: string;
    priority: string;
    status: string;
    acceptance_criteria: string[];
    tests: Array<{
        entry_id: number;
        spec_name: string;
        spec_path: string | null;
        mapping_type: string;
        confidence: number;
    }>;
    coverage_status: 'covered' | 'partial' | 'uncovered' | 'suggested';
}

interface RtmSummary {
    total_requirements: number;
    covered: number;
    partial: number;
    uncovered: number;
    coverage_percentage: number;
}

interface RtmGap {
    requirement_id: number;
    requirement_code: string;
    title: string;
    category: string;
    priority: string;
    suggested_test: {
        test_name: string;
        description: string;
        steps: string[];
    };
}

interface Snapshot {
    id: number;
    snapshot_name: string | null;
    total_requirements: number;
    covered_requirements: number;
    partial_requirements: number;
    uncovered_requirements: number;
    coverage_percentage: number;
    created_at: string;
}

interface TrendPoint {
    snapshot_id: number | null;
    snapshot_name: string | null;
    total_requirements: number;
    covered: number;
    partial: number;
    uncovered: number;
    coverage_percentage: number;
    created_at: string;
}

interface SnapshotDetail extends Snapshot {
    data: any;
}

interface SpecListItem {
    name: string;
    path?: string;
}

// Types for Deduplication
interface DuplicateMatch {
    requirement_id: number;
    req_code: string;
    title: string;
    description: string | null;
    acceptance_criteria: string[];
    similarity: number;
}

interface FindDuplicatesResponse {
    groups: DuplicateGroup[];
    total_duplicates: number;
    mode: 'semantic' | 'exact';
}

interface DuplicateGroup {
    canonical_id: number;
    canonical_code: string;
    canonical_title: string;
    duplicates: DuplicateMatch[];
    merged_criteria: string[];
}

interface CheckDuplicateResponse {
    has_exact_match: boolean;
    exact_match: Requirement | null;
    near_matches: DuplicateMatch[];
    recommendation: string;
}

type TabType = 'requirements' | 'traceability';

const priorityColors: Record<string, { bg: string; color: string }> = {
    critical: { bg: 'var(--danger-muted)', color: 'var(--danger)' },
    high: { bg: 'var(--warning-muted)', color: 'var(--warning)' },
    medium: { bg: 'var(--primary-glow)', color: 'var(--primary)' },
    low: { bg: 'rgba(156, 163, 175, 0.1)', color: 'var(--text-tertiary)' },
};

const statusColors: Record<string, { bg: string; color: string }> = {
    draft: { bg: 'rgba(156, 163, 175, 0.1)', color: 'var(--text-tertiary)' },
    approved: { bg: 'var(--success-muted)', color: 'var(--success)' },
    implemented: { bg: 'var(--primary-glow)', color: 'var(--primary)' },
    deprecated: { bg: 'var(--danger-muted)', color: 'var(--danger)' },
};

const coverageColors: Record<string, string> = {
    covered: 'var(--success)',
    partial: 'var(--warning)',
    uncovered: 'var(--danger)',
    suggested: 'var(--accent)',
};

const priorityOrder: Record<string, number> = {
    critical: 0,
    high: 1,
    medium: 2,
    low: 3
};

export default function RequirementsPage() {
    const { currentProject, isLoading: projectLoading } = useProject();
    const searchParams = useSearchParams();

    // Tab state
    const [activeTab, setActiveTab] = useState<TabType>('requirements');

    // Requirements tab state
    const [requirements, setRequirements] = useState<Requirement[]>([]);
    const [stats, setStats] = useState<Stats | null>(null);
    const [loading, setLoading] = useState(true);

    // Pagination state
    const [totalCount, setTotalCount] = useState(0);
    const [hasMore, setHasMore] = useState(true);
    const [isLoadingMore, setIsLoadingMore] = useState(false);
    const PAGE_SIZE = 50;

    const [searchTerm, setSearchTerm] = useState('');
    const [categoryFilter, setCategoryFilter] = useState<string>('');
    const [priorityFilter, setPriorityFilter] = useState<string>('');
    const [statusFilter, setStatusFilter] = useState<string>('');

    const [expandedReqs, setExpandedReqs] = useState<Set<number>>(new Set());
    const [editModalOpen, setEditModalOpen] = useState(false);
    const [editingReq, setEditingReq] = useState<Requirement | null>(null);
    const [deleteModalOpen, setDeleteModalOpen] = useState(false);
    const [deletingReq, setDeletingReq] = useState<Requirement | null>(null);
    const [isDeleting, setIsDeleting] = useState(false);
    const [isSaving, setIsSaving] = useState(false);

    const [createModalOpen, setCreateModalOpen] = useState(false);
    const [newReq, setNewReq] = useState({
        title: '',
        description: '',
        category: 'other',
        priority: 'medium',
        acceptance_criteria: ['']
    });
    const [isCreating, setIsCreating] = useState(false);

    // Traceability (RTM) tab state
    const [rtmRequirements, setRtmRequirements] = useState<RtmRequirement[]>([]);
    const [rtmSummary, setRtmSummary] = useState<RtmSummary | null>(null);
    const [rtmGaps, setRtmGaps] = useState<RtmGap[]>([]);
    const [rtmLoading, setRtmLoading] = useState(true);
    const [generating, setGenerating] = useState(false);
    const [rtmGenJobId, setRtmGenJobId] = useState<string | null>(null);
    const [rtmGenSuccess, setRtmGenSuccess] = useState(false);
    const rtmGenPollRef = useRef<NodeJS.Timeout | null>(null);
    const [expandedRtmReqs, setExpandedRtmReqs] = useState<Set<number>>(new Set());
    const [showGaps, setShowGaps] = useState(true);
    const [rtmTotalCount, setRtmTotalCount] = useState(0);
    const [rtmHasMore, setRtmHasMore] = useState(true);
    const [rtmIsLoadingMore, setRtmIsLoadingMore] = useState(false);
    const rtmSearchDebounceRef = useRef<NodeJS.Timeout | null>(null);
    const [debouncedRtmSearch, setDebouncedRtmSearch] = useState('');
    const rtmGapsLoadedRef = useRef(false);

    const [exportMenuOpen, setExportMenuOpen] = useState(false);
    const [snapshotModalOpen, setSnapshotModalOpen] = useState(false);
    const [snapshotName, setSnapshotName] = useState('');
    const [creatingSnapshot, setCreatingSnapshot] = useState(false);
    const [snapshots, setSnapshots] = useState<Snapshot[]>([]);
    const [snapshotsLoading, setSnapshotsLoading] = useState(false);

    // RTM Filtering
    const [rtmSearchTerm, setRtmSearchTerm] = useState('');
    const [rtmCoverageFilter, setRtmCoverageFilter] = useState<string>('all');
    const [rtmCategoryFilter, setRtmCategoryFilter] = useState<string>('');
    const [rtmPriorityFilter, setRtmPriorityFilter] = useState<string>('');

    // Manual linking
    const [linkingReqId, setLinkingReqId] = useState<number | null>(null);
    const [specSearchTerm, setSpecSearchTerm] = useState('');
    const [availableSpecs, setAvailableSpecs] = useState<SpecListItem[]>([]);
    const [specsLoading, setSpecsLoading] = useState(false);

    // Unlinking
    const [unlinkingEntryId, setUnlinkingEntryId] = useState<number | null>(null);

    // Trend data
    const [trendData, setTrendData] = useState<TrendPoint[]>([]);
    const [trendLoading, setTrendLoading] = useState(false);

    // Snapshot detail
    const [selectedSnapshot, setSelectedSnapshot] = useState<SnapshotDetail | null>(null);
    const [snapshotDetailLoading, setSnapshotDetailLoading] = useState(false);

    // Deduplication state
    const [duplicateGroups, setDuplicateGroups] = useState<DuplicateGroup[]>([]);
    const [duplicateMode, setDuplicateMode] = useState<'semantic' | 'exact'>('exact');
    const [findingDuplicates, setFindingDuplicates] = useState(false);
    const [duplicateModalOpen, setDuplicateModalOpen] = useState(false);
    const [mergingGroup, setMergingGroup] = useState<DuplicateGroup | null>(null);
    const [isMerging, setIsMerging] = useState(false);
    const [duplicateWarning, setDuplicateWarning] = useState<CheckDuplicateResponse | null>(null);
    const [checkingDuplicate, setCheckingDuplicate] = useState(false);

    // Generate spec modal state
    const [generateSpecModalOpen, setGenerateSpecModalOpen] = useState(false);
    const [selectedReqForSpec, setSelectedReqForSpec] = useState<Requirement | RtmRequirement | null>(null);
    const [createSpecDropdownOpen, setCreateSpecDropdownOpen] = useState<number | null>(null);

    useEffect(() => {
        const tab = searchParams.get('tab');
        if (tab === 'traceability') setActiveTab('traceability');
    }, [searchParams]);

    // Fetch Requirements data with pagination
    const fetchData = useCallback(async (offset = 0, append = false) => {
        if (projectLoading) return;

        // Build query params
        const params = new URLSearchParams();
        if (currentProject?.id) params.append('project_id', currentProject.id);
        params.append('limit', PAGE_SIZE.toString());
        params.append('offset', offset.toString());
        if (categoryFilter) params.append('category', categoryFilter);
        if (priorityFilter) params.append('priority', priorityFilter);
        if (statusFilter) params.append('status', statusFilter);
        if (searchTerm) params.append('search', searchTerm);

        const queryString = params.toString();
        const projectParam = currentProject?.id
            ? `?project_id=${encodeURIComponent(currentProject.id)}`
            : '';

        try {
            if (append) {
                setIsLoadingMore(true);
            }

            const [reqsRes, statsRes] = await Promise.all([
                fetch(`${API_BASE}/requirements?${queryString}`),
                // Only fetch stats on initial load, not on "load more"
                append ? Promise.resolve(null) : fetch(`${API_BASE}/requirements/stats${projectParam}`)
            ]);

            const reqsData = await reqsRes.json();

            if (append) {
                setRequirements(prev => [...prev, ...reqsData.items]);
            } else {
                setRequirements(reqsData.items);
            }

            setTotalCount(reqsData.total);
            setHasMore(reqsData.has_more);

            if (!append && statsRes) {
                const statsData = await statsRes.json();
                setStats(statsData);
            }
        } catch (err) {
            console.error('Failed to fetch requirements:', err);
        } finally {
            setLoading(false);
            setIsLoadingMore(false);
        }
    }, [currentProject?.id, projectLoading, categoryFilter, priorityFilter, statusFilter, searchTerm]);

    // Load more handler
    const loadMore = () => {
        if (isLoadingMore || !hasMore) return;
        fetchData(requirements.length, true);
    };

    // Fetch RTM data with server-side pagination and filtering
    const fetchRtm = useCallback(async (offset = 0, append = false) => {
        if (projectLoading) return;

        const params = new URLSearchParams();
        if (currentProject?.id) params.append('project_id', currentProject.id);
        params.append('limit', PAGE_SIZE.toString());
        params.append('offset', offset.toString());
        if (debouncedRtmSearch) params.append('search', debouncedRtmSearch);
        if (rtmCoverageFilter && rtmCoverageFilter !== 'all') params.append('coverage_status', rtmCoverageFilter);
        if (rtmCategoryFilter) params.append('category', rtmCategoryFilter);
        if (rtmPriorityFilter) params.append('priority', rtmPriorityFilter);

        try {
            if (append) {
                setRtmIsLoadingMore(true);
            } else {
                setRtmLoading(true);
            }

            const res = await fetch(`${API_BASE}/rtm?${params.toString()}`);
            const data = await res.json();

            if (append) {
                setRtmRequirements(prev => [...prev, ...data.items]);
            } else {
                setRtmRequirements(data.items);
                rtmGapsLoadedRef.current = false;
            }

            setRtmTotalCount(data.total);
            setRtmHasMore(data.has_more);

            if (!append) {
                setRtmSummary(data.summary);
            }
        } catch (err) {
            console.error('Failed to fetch RTM:', err);
        } finally {
            setRtmLoading(false);
            setRtmIsLoadingMore(false);
        }
    }, [currentProject?.id, projectLoading, debouncedRtmSearch, rtmCoverageFilter, rtmCategoryFilter, rtmPriorityFilter]);

    // Load more RTM handler
    const loadMoreRtm = () => {
        if (rtmIsLoadingMore || !rtmHasMore) return;
        fetchRtm(rtmRequirements.length, true);
    };

    // Fetch RTM gaps lazily
    const fetchGaps = useCallback(async () => {
        if (projectLoading) return;
        const projectParam = currentProject?.id
            ? `?project_id=${encodeURIComponent(currentProject.id)}`
            : '';
        try {
            const res = await fetch(`${API_BASE}/rtm/gaps${projectParam}`);
            const data = await res.json();
            setRtmGaps(data);
            rtmGapsLoadedRef.current = true;
        } catch (err) {
            console.error('Failed to fetch gaps:', err);
        }
    }, [currentProject?.id, projectLoading]);

    const fetchTrend = useCallback(async () => {
        if (projectLoading) return;
        const projectParam = currentProject?.id
            ? `?project_id=${encodeURIComponent(currentProject.id)}`
            : '';
        setTrendLoading(true);
        try {
            const res = await fetch(`${API_BASE}/rtm/trend${projectParam}`);
            if (res.ok) {
                const data = await res.json();
                setTrendData(data);
            }
        } catch (err) {
            console.error('Failed to fetch trend:', err);
        } finally {
            setTrendLoading(false);
        }
    }, [currentProject?.id, projectLoading]);

    useEffect(() => {
        // Reset to first page when filters change
        setLoading(true);
        fetchData(0, false);
    }, [fetchData]);

    useEffect(() => {
        if (activeTab === 'traceability') {
            fetchRtm(0, false);
            fetchTrend();
        }
    }, [activeTab, fetchRtm, fetchTrend]);

    // Debounce RTM search
    useEffect(() => {
        if (rtmSearchDebounceRef.current) {
            clearTimeout(rtmSearchDebounceRef.current);
        }
        rtmSearchDebounceRef.current = setTimeout(() => {
            setDebouncedRtmSearch(rtmSearchTerm);
        }, 300);
        return () => {
            if (rtmSearchDebounceRef.current) {
                clearTimeout(rtmSearchDebounceRef.current);
            }
        };
    }, [rtmSearchTerm]);

    // Lazy-load gaps when toggled on
    useEffect(() => {
        if (showGaps && activeTab === 'traceability' && !rtmGapsLoadedRef.current) {
            fetchGaps();
        }
    }, [showGaps, activeTab, fetchGaps]);

    // Requirements are now filtered server-side, so we just use them directly
    // Note: All filtering is done via API query params for pagination support
    const filteredRequirements = requirements;

    const toggleExpanded = (id: number) => {
        const next = new Set(expandedReqs);
        if (next.has(id)) next.delete(id);
        else next.add(id);
        setExpandedReqs(next);
    };

    const toggleRtmExpanded = (id: number) => {
        const next = new Set(expandedRtmReqs);
        if (next.has(id)) next.delete(id);
        else next.add(id);
        setExpandedRtmReqs(next);
    };

    const openEditModal = (req: Requirement) => {
        setEditingReq({ ...req });
        setEditModalOpen(true);
    };

    const saveEdit = async () => {
        if (!editingReq) return;
        setIsSaving(true);

        const projectParam = currentProject?.id
            ? `?project_id=${encodeURIComponent(currentProject.id)}`
            : '';

        try {
            const res = await fetch(`${API_BASE}/requirements/${editingReq.id}${projectParam}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    title: editingReq.title,
                    description: editingReq.description,
                    category: editingReq.category,
                    priority: editingReq.priority,
                    status: editingReq.status,
                    acceptance_criteria: editingReq.acceptance_criteria
                })
            });

            if (res.ok) {
                const updated = await res.json();
                setRequirements(requirements.map(r => r.id === updated.id ? updated : r));
                setEditModalOpen(false);
                setEditingReq(null);
            } else {
                const err = await res.json();
                alert(`Failed to update: ${err.detail}`);
            }
        } catch (e) {
            console.error('Failed to update requirement:', e);
            alert('Failed to update requirement');
        } finally {
            setIsSaving(false);
        }
    };

    const confirmDelete = async () => {
        if (!deletingReq) return;
        setIsDeleting(true);

        const projectParam = currentProject?.id
            ? `?project_id=${encodeURIComponent(currentProject.id)}`
            : '';

        try {
            const res = await fetch(`${API_BASE}/requirements/${deletingReq.id}${projectParam}`, {
                method: 'DELETE'
            });

            if (res.ok) {
                setRequirements(requirements.filter(r => r.id !== deletingReq.id));
                setTotalCount(prev => prev - 1);
                setDeleteModalOpen(false);
                setDeletingReq(null);
            } else {
                const err = await res.json();
                alert(`Failed to delete: ${err.detail}`);
            }
        } catch (e) {
            console.error('Failed to delete requirement:', e);
            alert('Failed to delete requirement');
        } finally {
            setIsDeleting(false);
        }
    };

    // Original createRequirement is replaced by createRequirementWithCheck
    const createRequirement = () => createRequirementWithCheck(false);

    // Cleanup RTM polling on unmount
    useEffect(() => {
        return () => {
            if (rtmGenPollRef.current) {
                clearInterval(rtmGenPollRef.current);
            }
        };
    }, []);

    // RTM functions
    const generateRtm = async () => {
        setGenerating(true);
        setRtmGenSuccess(false);

        const projectParam = currentProject?.id
            ? `?project_id=${encodeURIComponent(currentProject.id)}`
            : '';

        try {
            const res = await fetch(`${API_BASE}/rtm/generate${projectParam}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ use_ai_matching: true })
            });

            if (res.ok) {
                const data = await res.json();
                if (data.job_id) {
                    // Async mode: poll for completion
                    setRtmGenJobId(data.job_id);
                    const pollInterval = setInterval(async () => {
                        try {
                            const pollRes = await fetch(`${API_BASE}/rtm/generate-jobs/${data.job_id}`);
                            if (pollRes.ok) {
                                const pollData = await pollRes.json();
                                if (pollData.status === 'completed') {
                                    clearInterval(pollInterval);
                                    rtmGenPollRef.current = null;
                                    setRtmGenJobId(null);
                                    setGenerating(false);
                                    setRtmGenSuccess(true);
                                    await fetchRtm();
                                } else if (pollData.status === 'failed') {
                                    clearInterval(pollInterval);
                                    rtmGenPollRef.current = null;
                                    setRtmGenJobId(null);
                                    setGenerating(false);
                                    alert(`Failed to generate RTM: ${pollData.error || 'Unknown error'}`);
                                }
                            }
                        } catch {
                            // Polling error, keep trying
                        }
                    }, 2000);
                    rtmGenPollRef.current = pollInterval;
                } else {
                    // Sync fallback
                    await fetchRtm();
                    setGenerating(false);
                    setRtmGenSuccess(true);
                }
            } else {
                const err = await res.json();
                alert(`Failed to generate RTM: ${err.detail}`);
                setGenerating(false);
            }
        } catch (e) {
            console.error('Failed to generate RTM:', e);
            alert('Failed to generate RTM');
            setGenerating(false);
        }
    };

    const exportRtm = async (format: 'markdown' | 'csv' | 'html') => {
        const projectParam = currentProject?.id
            ? `?project_id=${encodeURIComponent(currentProject.id)}`
            : '';

        try {
            const res = await fetch(`${API_BASE}/rtm/export/${format}${projectParam}`);
            const blob = await res.blob();

            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `rtm.${format === 'markdown' ? 'md' : format}`;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            window.URL.revokeObjectURL(url);
        } catch (e) {
            console.error('Failed to export RTM:', e);
            alert('Failed to export RTM');
        }

        setExportMenuOpen(false);
    };

    const fetchSnapshots = async () => {
        setSnapshotsLoading(true);
        const projectParam = currentProject?.id
            ? `?project_id=${encodeURIComponent(currentProject.id)}`
            : '';

        try {
            const res = await fetch(`${API_BASE}/rtm/snapshots${projectParam}`);
            const data = await res.json();
            setSnapshots(data);
        } catch (e) {
            console.error('Failed to fetch snapshots:', e);
        } finally {
            setSnapshotsLoading(false);
        }
    };

    const createSnapshot = async () => {
        setCreatingSnapshot(true);

        const projectParam = currentProject?.id
            ? `?project_id=${encodeURIComponent(currentProject.id)}`
            : '';

        const nameParam = snapshotName ? `&name=${encodeURIComponent(snapshotName)}` : '';

        try {
            const res = await fetch(`${API_BASE}/rtm/snapshot${projectParam}${nameParam}`, {
                method: 'POST'
            });

            if (res.ok) {
                setSnapshotModalOpen(false);
                setSnapshotName('');
                alert('Snapshot created successfully!');
            } else {
                const err = await res.json();
                alert(`Failed to create snapshot: ${err.detail}`);
            }
        } catch (e) {
            console.error('Failed to create snapshot:', e);
            alert('Failed to create snapshot');
        } finally {
            setCreatingSnapshot(false);
        }
    };

    const getCoverageIcon = (status: string) => {
        switch (status) {
            case 'covered':
                return <CheckCircle size={16} color={coverageColors.covered} />;
            case 'partial':
                return <Circle size={16} color={coverageColors.partial} style={{ fill: coverageColors.partial, fillOpacity: 0.3 }} />;
            default:
                return <Circle size={16} color={coverageColors.uncovered} />;
        }
    };

    // Generate Spec functions
    const openGenerateSpecModal = (req: Requirement | RtmRequirement) => {
        // Convert RtmRequirement to Requirement format if needed
        const requirement: Requirement = 'req_code' in req ? req : {
            id: req.id,
            req_code: req.code,
            title: req.title,
            description: req.description,
            category: req.category,
            priority: req.priority,
            status: req.status,
            acceptance_criteria: req.acceptance_criteria,
            source_session_id: null,
            created_at: '',
            updated_at: ''
        };
        setSelectedReqForSpec(requirement);
        setGenerateSpecModalOpen(true);
        setCreateSpecDropdownOpen(null);
    };

    const handleSpecGenerated = (specPath: string, specName: string) => {
        // Refresh RTM data if we're on the traceability tab
        if (activeTab === 'traceability') {
            fetchRtm();
        }
    };

    const fetchSpecs = useCallback(async () => {
        const projectParam = currentProject?.id
            ? `project_id=${encodeURIComponent(currentProject.id)}`
            : '';
        setSpecsLoading(true);
        try {
            const res = await fetch(`${API_BASE}/specs/list?${projectParam}&limit=200`);
            if (res.ok) {
                const data = await res.json();
                setAvailableSpecs(data.items || data.specs || data || []);
            }
        } catch (err) {
            console.error('Failed to fetch specs:', err);
        } finally {
            setSpecsLoading(false);
        }
    }, [currentProject?.id]);

    const linkTest = async (requirementId: number, specName: string) => {
        const projectParam = currentProject?.id
            ? `?project_id=${encodeURIComponent(currentProject.id)}`
            : '';
        try {
            const res = await fetch(`${API_BASE}/rtm/entry${projectParam}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    requirement_id: requirementId,
                    test_spec_name: specName,
                    mapping_type: 'full',
                    confidence: 1.0
                })
            });
            if (res.ok) {
                setLinkingReqId(null);
                setSpecSearchTerm('');
                await fetchRtm();
            }
        } catch (err) {
            console.error('Failed to link test:', err);
        }
    };

    const unlinkTest = async (entryId: number) => {
        const projectParam = currentProject?.id
            ? `?project_id=${encodeURIComponent(currentProject.id)}`
            : '';
        try {
            const res = await fetch(`${API_BASE}/rtm/entry/${entryId}${projectParam}`, {
                method: 'DELETE'
            });
            if (res.ok) {
                setUnlinkingEntryId(null);
                await fetchRtm();
            }
        } catch (err) {
            console.error('Failed to unlink test:', err);
        }
    };

    const fetchSnapshotDetail = async (snapshotId: number) => {
        const projectParam = currentProject?.id
            ? `?project_id=${encodeURIComponent(currentProject.id)}`
            : '';
        setSnapshotDetailLoading(true);
        try {
            const res = await fetch(`${API_BASE}/rtm/snapshot/${snapshotId}${projectParam}`);
            if (res.ok) {
                const data = await res.json();
                setSelectedSnapshot(data);
            }
        } catch (err) {
            console.error('Failed to fetch snapshot:', err);
        } finally {
            setSnapshotDetailLoading(false);
        }
    };

    // Create Spec Dropdown Component
    const CreateSpecDropdown = ({ req, variant = 'inline' }: { req: Requirement | RtmRequirement; variant?: 'inline' | 'button' }) => {
        const reqId = req.id;
        const isOpen = createSpecDropdownOpen === reqId;
        const reqCode = 'req_code' in req ? req.req_code : req.code;

        const handleButtonClick = (e: React.MouseEvent<HTMLButtonElement>) => {
            e.stopPropagation();
            if (!isOpen) {
                setCreateSpecDropdownOpen(reqId);
            } else {
                setCreateSpecDropdownOpen(null);
            }
        };

        return (
            <div style={{ position: 'relative' }}>
                <button
                    onClick={handleButtonClick}
                    className={variant === 'button' ? 'btn btn-primary btn-sm' : 'btn btn-sm'}
                    style={{
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: '0.375rem',
                        ...(variant === 'inline' ? {
                            padding: '0.375rem 0.75rem',
                            fontSize: '0.8rem',
                            background: 'var(--primary)',
                            color: 'white',
                            borderRadius: '6px',
                            border: 'none',
                            cursor: 'pointer'
                        } : {
                            textDecoration: 'none'
                        })
                    }}
                >
                    <Plus size={14} />
                    Create Spec
                    <ChevronDown size={12} />
                </button>

                {isOpen && (
                    <>
                        {/* Backdrop to close dropdown */}
                        <div
                            style={{ position: 'fixed', inset: 0, zIndex: 99 }}
                            onClick={(e) => {
                                e.stopPropagation();
                                setCreateSpecDropdownOpen(null);
                            }}
                        />
                        <div style={{
                            position: 'absolute',
                            top: '100%',
                            left: 0,
                            marginTop: '4px',
                            background: 'var(--surface)',
                            border: '1px solid var(--border)',
                            borderRadius: '8px',
                            boxShadow: '0 10px 25px rgba(0,0,0,0.2)',
                            zIndex: 100,
                            minWidth: '200px',
                            overflow: 'hidden'
                        }}>
                            <button
                                className="dropdown-item"
                                onClick={(e) => {
                                    e.stopPropagation();
                                    openGenerateSpecModal(req);
                                }}
                                style={{
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: '0.75rem',
                                    width: '100%',
                                    padding: '0.75rem 1rem',
                                    border: 'none',
                                    textAlign: 'left',
                                    cursor: 'pointer',
                                    color: 'var(--text)',
                                    fontSize: '0.9rem',
                                    borderBottom: '1px solid var(--border)'
                                }}
                            >
                                <Sparkles size={16} color="var(--primary)" />
                                <div>
                                    <div style={{ fontWeight: 500 }}>AI Generate</div>
                                    <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
                                        Auto-create with browser AI
                                    </div>
                                </div>
                            </button>
                            <Link
                                className="dropdown-item"
                                href={`/specs/new?requirement_id=${reqId}&requirement_code=${encodeURIComponent(reqCode)}`}
                                onClick={(e) => {
                                    e.stopPropagation();
                                    setCreateSpecDropdownOpen(null);
                                }}
                                style={{
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: '0.75rem',
                                    width: '100%',
                                    padding: '0.75rem 1rem',
                                    textDecoration: 'none',
                                    color: 'var(--text)',
                                    fontSize: '0.9rem'
                                }}
                            >
                                <FileText size={16} color="var(--text-secondary)" />
                                <div>
                                    <div style={{ fontWeight: 500 }}>Create Manually</div>
                                    <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
                                        Write spec from scratch
                                    </div>
                                </div>
                            </Link>
                        </div>
                    </>
                )}
            </div>
        );
    };

    // Deduplication functions
    const findDuplicates = async () => {
        setFindingDuplicates(true);

        const projectParam = currentProject?.id
            ? `?project_id=${encodeURIComponent(currentProject.id)}`
            : '';

        try {
            const res = await fetch(`${API_BASE}/requirements/duplicates${projectParam}`);
            const data: FindDuplicatesResponse = await res.json();

            setDuplicateGroups(data.groups || []);
            setDuplicateMode(data.mode || 'exact');
            setDuplicateModalOpen(true);
        } catch (e) {
            console.error('Failed to find duplicates:', e);
            alert('Failed to find duplicates');
        } finally {
            setFindingDuplicates(false);
        }
    };

    const mergeGroup = async (group: DuplicateGroup) => {
        setIsMerging(true);
        setMergingGroup(group);

        const projectParam = currentProject?.id
            ? `?project_id=${encodeURIComponent(currentProject.id)}`
            : '';

        try {
            const res = await fetch(`${API_BASE}/requirements/merge${projectParam}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    canonical_id: group.canonical_id,
                    duplicate_ids: group.duplicates.map(d => d.requirement_id),
                    merge_acceptance_criteria: true
                })
            });

            if (res.ok) {
                // Refresh requirements list
                await fetchData();
                // Remove merged group from list
                setDuplicateGroups(groups => groups.filter(g => g.canonical_id !== group.canonical_id));
            } else {
                const err = await res.json();
                alert(`Failed to merge: ${err.detail}`);
            }
        } catch (e) {
            console.error('Failed to merge requirements:', e);
            alert('Failed to merge requirements');
        } finally {
            setIsMerging(false);
            setMergingGroup(null);
        }
    };

    const checkForDuplicates = async (title: string, description: string) => {
        if (!title.trim()) return;

        setCheckingDuplicate(true);

        const projectParam = currentProject?.id
            ? `?project_id=${encodeURIComponent(currentProject.id)}`
            : '';

        try {
            const res = await fetch(`${API_BASE}/requirements/check-duplicate${projectParam}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ title, description: description || null })
            });

            if (res.ok) {
                const data = await res.json();
                if (data.has_exact_match || data.near_matches.length > 0) {
                    setDuplicateWarning(data);
                } else {
                    setDuplicateWarning(null);
                }
            }
        } catch (e) {
            console.error('Failed to check duplicates:', e);
        } finally {
            setCheckingDuplicate(false);
        }
    };

    const createRequirementWithCheck = async (forceCreate: boolean = false) => {
        if (!newReq.title) return;

        // If not forcing create and we haven't checked yet, check first
        if (!forceCreate && !duplicateWarning) {
            await checkForDuplicates(newReq.title, newReq.description);
            // If warning shows up, user will need to confirm
            return;
        }

        // If warning exists and not forcing, don't create
        if (duplicateWarning && !forceCreate) {
            return;
        }

        // Proceed with creation
        setIsCreating(true);

        const projectParam = currentProject?.id
            ? `?project_id=${encodeURIComponent(currentProject.id)}`
            : '';

        try {
            const res = await fetch(`${API_BASE}/requirements${projectParam}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    title: newReq.title,
                    description: newReq.description || null,
                    category: newReq.category,
                    priority: newReq.priority,
                    acceptance_criteria: newReq.acceptance_criteria.filter(ac => ac.trim())
                })
            });

            if (res.ok) {
                // Refresh the list from the beginning to get accurate pagination
                await fetchData(0, false);
                setCreateModalOpen(false);
                setNewReq({
                    title: '',
                    description: '',
                    category: 'other',
                    priority: 'medium',
                    acceptance_criteria: ['']
                });
                setDuplicateWarning(null);
            } else {
                const err = await res.json();
                alert(`Failed to create: ${err.detail}`);
            }
        } catch (e) {
            console.error('Failed to create requirement:', e);
            alert('Failed to create requirement');
        } finally {
            setIsCreating(false);
        }
    };

    const categories = useMemo(() => {
        return [...new Set(requirements.map(r => r.category))].sort();
    }, [requirements]);

    // Memoize chart data for RTM to avoid recreation on every render
    const chartData = useMemo(() => {
        if (!rtmSummary) return [];
        return [
            { name: 'Covered', value: rtmSummary.covered, color: coverageColors.covered },
            { name: 'Partial', value: rtmSummary.partial, color: coverageColors.partial },
            { name: 'Uncovered', value: rtmSummary.uncovered, color: coverageColors.uncovered },
        ].filter(d => d.value > 0);
    }, [rtmSummary]);

    const rtmCategories = ['accessibility', 'authentication', 'data_display', 'error_handling', 'forms', 'navigation', 'other', 'performance', 'security'];

    // RTM data is now filtered and sorted server-side

    // Skeleton components
    const SkeletonRow = () => (
        <div style={{ padding: '1rem', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', gap: '1rem' }}>
            <div style={{ width: 20, height: 20, background: 'var(--surface-hover)', borderRadius: 4, animation: 'pulse 1.5s ease-in-out infinite' }} />
            <div style={{ flex: 1 }}>
                <div style={{ height: 16, width: '60%', background: 'var(--surface-hover)', borderRadius: 4, marginBottom: '0.5rem', animation: 'pulse 1.5s ease-in-out infinite' }} />
                <div style={{ height: 12, width: '40%', background: 'var(--surface-hover)', borderRadius: 4, animation: 'pulse 1.5s ease-in-out infinite' }} />
            </div>
            <div style={{ display: 'flex', gap: '0.5rem' }}>
                {[1, 2, 3].map(i => (
                    <div key={i} style={{ height: 24, width: 60, background: 'var(--surface-hover)', borderRadius: 12, animation: 'pulse 1.5s ease-in-out infinite' }} />
                ))}
            </div>
        </div>
    );

    const RtmSkeletonRow = () => (
        <div style={{ padding: '1rem', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', gap: '1rem' }}>
            <div style={{ width: 16, height: 16, background: 'var(--surface-hover)', borderRadius: '50%', animation: 'pulse 1.5s ease-in-out infinite' }} />
            <div style={{ flex: 1 }}>
                <div style={{ height: 16, width: '50%', background: 'var(--surface-hover)', borderRadius: 4, marginBottom: '0.5rem', animation: 'pulse 1.5s ease-in-out infinite' }} />
                <div style={{ height: 12, width: '30%', background: 'var(--surface-hover)', borderRadius: 4, animation: 'pulse 1.5s ease-in-out infinite' }} />
            </div>
            <div style={{ height: 24, width: 70, background: 'var(--surface-hover)', borderRadius: 4, animation: 'pulse 1.5s ease-in-out infinite' }} />
        </div>
    );

    // Loading state
    if ((loading && activeTab === 'requirements') || projectLoading) {
        return (
            <PageLayout tier="wide">
                <ListPageSkeleton rows={5} />
            </PageLayout>
        );
    }

    return (
        <PageLayout tier="wide">
            <PageHeader
                title="Requirements"
                subtitle="Manage requirements and track test coverage traceability."
                icon={<CheckSquare size={22} />}
                breadcrumb={<WorkflowBreadcrumb />}
                actions={
                    <>
                        {activeTab === 'requirements' && (
                            <div style={{ display: 'flex', gap: '0.75rem' }}>
                                <button
                                    className="btn btn-secondary"
                                    onClick={findDuplicates}
                                    disabled={findingDuplicates || requirements.length < 2}
                                    style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}
                                    title="Find and merge duplicate requirements"
                                >
                                    {findingDuplicates ? <Loader2 size={16} className="spinning" /> : <Sparkles size={16} />}
                                    Optimize
                                </button>
                                <button
                                    className="btn btn-primary"
                                    onClick={() => setCreateModalOpen(true)}
                                    style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}
                                >
                                    <Plus size={18} />
                                    Add Requirement
                                </button>
                            </div>
                        )}
                        {activeTab === 'traceability' && (
                            <div style={{ display: 'flex', gap: '0.75rem' }}>
                                <button
                                    className="btn btn-secondary"
                                    onClick={generateRtm}
                                    disabled={generating}
                                    style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}
                                >
                                    {generating ? <Loader2 size={16} className="spinning" /> : <RefreshCw size={16} />}
                                    {generating ? 'Generating...' : 'Generate RTM'}
                                </button>

                                <div style={{ position: 'relative' }}>
                                    <button
                                        className="btn btn-secondary"
                                        onClick={() => setExportMenuOpen(!exportMenuOpen)}
                                        style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}
                                    >
                                        <Download size={16} />
                                        Export
                                        <ChevronDown size={14} />
                                    </button>

                                    {exportMenuOpen && (
                                        <div style={{
                                            position: 'absolute',
                                            top: '100%',
                                            right: 0,
                                            marginTop: '0.5rem',
                                            background: 'var(--surface)',
                                            border: '1px solid var(--border)',
                                            borderRadius: '8px',
                                            boxShadow: '0 10px 25px rgba(0,0,0,0.2)',
                                            zIndex: 100,
                                            minWidth: '150px'
                                        }}>
                                            {['markdown', 'csv', 'html'].map(format => (
                                                <button
                                                    key={format}
                                                    onClick={() => exportRtm(format as 'markdown' | 'csv' | 'html')}
                                                    style={{
                                                        display: 'block',
                                                        width: '100%',
                                                        padding: '0.75rem 1rem',
                                                        border: 'none',
                                                        background: 'transparent',
                                                        textAlign: 'left',
                                                        cursor: 'pointer',
                                                        color: 'var(--text)'
                                                    }}
                                                >
                                                    Export as .{format === 'markdown' ? 'md' : format}
                                                </button>
                                            ))}
                                        </div>
                                    )}
                                </div>

                                <button
                                    className="btn btn-primary"
                                    onClick={() => { setSnapshotModalOpen(true); fetchSnapshots(); }}
                                    style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}
                                >
                                    <Camera size={16} />
                                    Snapshot
                                </button>
                            </div>
                        )}
                    </>
                }
            />

            {/* Close export menu when clicking outside */}
            {exportMenuOpen && (
                <div
                    style={{ position: 'fixed', inset: 0, zIndex: 99 }}
                    onClick={() => setExportMenuOpen(false)}
                />
            )}

            {/* Tab Navigation */}
            <div className="animate-in stagger-2" style={{ display: 'flex', gap: '0.5rem', marginBottom: '1.5rem', borderBottom: '1px solid var(--border-subtle)', paddingBottom: '1rem' }}>
                {[
                    { id: 'requirements' as TabType, label: 'Requirements', icon: CheckSquare },
                    { id: 'traceability' as TabType, label: 'Traceability', icon: GitBranch }
                ].map(tab => (
                    <button
                        key={tab.id}
                        onClick={() => setActiveTab(tab.id)}
                        style={{
                            display: 'flex',
                            alignItems: 'center',
                            gap: '0.5rem',
                            padding: '0.75rem 1.25rem',
                            border: 'none',
                            borderRadius: 'var(--radius)',
                            background: activeTab === tab.id ? 'var(--primary-glow)' : 'transparent',
                            color: activeTab === tab.id ? 'var(--primary)' : 'var(--text-secondary)',
                            cursor: 'pointer',
                            fontWeight: 500,
                            fontSize: '0.95rem',
                            transition: 'all 0.2s var(--ease-smooth)'
                        }}
                    >
                        <tab.icon size={18} />
                        {tab.label}
                    </button>
                ))}
            </div>

            {/* Requirements Tab Content */}
            {activeTab === 'requirements' && (
                <div className="animate-in stagger-3">
                    {/* Stats Bar */}
                    {stats && stats.by_priority && (
                        <div style={{ display: 'flex', gap: '1.5rem', marginBottom: '1.5rem', flexWrap: 'wrap' }}>
                            <div style={{ fontWeight: 600 }}>
                                Total: <span style={{ color: 'var(--primary)' }}>{stats.total}</span>
                            </div>
                            {['critical', 'high', 'medium', 'low'].map(priority => (
                                stats.by_priority[priority] ? (
                                    <div key={priority} style={{ display: 'flex', alignItems: 'center', gap: '0.375rem' }}>
                                        <span style={{
                                            width: 8,
                                            height: 8,
                                            borderRadius: '50%',
                                            background: priorityColors[priority]?.color
                                        }} />
                                        <span style={{ textTransform: 'capitalize' }}>{priority}:</span>
                                        <span style={{ fontWeight: 600 }}>{stats.by_priority[priority]}</span>
                                    </div>
                                ) : null
                            ))}
                        </div>
                    )}

                    {/* Filters */}
                    <div style={{ display: 'flex', gap: '1rem', marginBottom: '1.5rem', flexWrap: 'wrap' }}>
                        <div className="input-group" style={{ flex: 1, minWidth: '200px' }}>
                            <div className="input-icon">
                                <Search size={18} />
                            </div>
                            <input
                                type="text"
                                className="input has-icon"
                                placeholder="Search requirements..."
                                value={searchTerm}
                                onChange={e => setSearchTerm(e.target.value)}
                                style={{ width: '100%' }}
                            />
                        </div>

                        <select
                            value={categoryFilter}
                            onChange={e => setCategoryFilter(e.target.value)}
                            className="input"
                            style={{ minWidth: '140px' }}
                        >
                            <option value="">All Categories</option>
                            {categories.map(cat => (
                                <option key={cat} value={cat}>{cat}</option>
                            ))}
                        </select>

                        <select
                            value={priorityFilter}
                            onChange={e => setPriorityFilter(e.target.value)}
                            className="input"
                            style={{ minWidth: '140px' }}
                        >
                            <option value="">All Priorities</option>
                            <option value="critical">Critical</option>
                            <option value="high">High</option>
                            <option value="medium">Medium</option>
                            <option value="low">Low</option>
                        </select>

                        <select
                            value={statusFilter}
                            onChange={e => setStatusFilter(e.target.value)}
                            className="input"
                            style={{ minWidth: '140px' }}
                        >
                            <option value="">All Statuses</option>
                            <option value="draft">Draft</option>
                            <option value="approved">Approved</option>
                            <option value="implemented">Implemented</option>
                            <option value="deprecated">Deprecated</option>
                        </select>
                    </div>

                    {/* Requirements List */}
                    <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
                        {filteredRequirements.length === 0 ? (
                            <EmptyState
                                icon={<CheckSquare size={32} />}
                                title={requirements.length === 0 ? 'No requirements yet' : 'No matching requirements'}
                                description={requirements.length === 0
                                    ? 'Generate from an exploration or add manually.'
                                    : 'No requirements match your filters.'
                                }
                            />
                        ) : (
                            <>
                            {filteredRequirements.map(req => {
                                const isExpanded = expandedReqs.has(req.id);
                                return (
                                    <div key={req.id} style={{ borderBottom: '1px solid var(--border)' }}>
                                        <div
                                            style={{
                                                padding: '1rem 1.25rem',
                                                display: 'flex',
                                                alignItems: 'center',
                                                gap: '1rem',
                                                cursor: 'pointer',
                                                background: isExpanded ? 'var(--surface-hover)' : 'transparent'
                                            }}
                                            onClick={() => toggleExpanded(req.id)}
                                        >
                                            <span style={{ color: 'var(--text-secondary)' }}>
                                                {isExpanded ? <ChevronDown size={18} /> : <ChevronRight size={18} />}
                                            </span>

                                            <div style={{ flex: 1 }}>
                                                <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '0.25rem' }}>
                                                    <span style={{ fontWeight: 600, color: 'var(--primary)', fontSize: '0.85rem' }}>{req.req_code}</span>
                                                    <span style={{ fontWeight: 500 }}>{req.title}</span>
                                                </div>
                                                <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                                                    {req.acceptance_criteria.length} acceptance criteria
                                                </div>
                                            </div>

                                            <span style={{
                                                padding: '0.25rem 0.625rem',
                                                borderRadius: '4px',
                                                fontSize: '0.75rem',
                                                fontWeight: 500,
                                                background: 'rgba(192, 132, 252, 0.12)',
                                                color: 'var(--accent)'
                                            }}>
                                                {req.category}
                                            </span>

                                            <span style={{
                                                padding: '0.25rem 0.625rem',
                                                borderRadius: '4px',
                                                fontSize: '0.75rem',
                                                fontWeight: 600,
                                                textTransform: 'uppercase',
                                                ...priorityColors[req.priority]
                                            }}>
                                                {req.priority}
                                            </span>

                                            <span style={{
                                                padding: '0.25rem 0.625rem',
                                                borderRadius: '4px',
                                                fontSize: '0.75rem',
                                                fontWeight: 500,
                                                ...statusColors[req.status]
                                            }}>
                                                {req.status}
                                            </span>

                                            <div style={{ display: 'flex', gap: '0.375rem' }} onClick={e => e.stopPropagation()}>
                                                <button
                                                    className="btn-icon"
                                                    onClick={() => openEditModal(req)}
                                                    style={{ width: 32, height: 32, color: 'var(--text-secondary)', background: 'var(--surface-hover)' }}
                                                >
                                                    <Edit size={14} />
                                                </button>
                                                <button
                                                    className="btn-icon"
                                                    onClick={() => { setDeletingReq(req); setDeleteModalOpen(true); }}
                                                    style={{ width: 32, height: 32, color: 'var(--danger)', background: 'var(--danger-muted)' }}
                                                >
                                                    <Trash2 size={14} />
                                                </button>
                                            </div>
                                        </div>

                                        {isExpanded && (
                                            <div style={{ padding: '1rem 1.25rem 1.25rem', paddingLeft: '3.5rem', background: 'var(--surface-hover)', borderTop: '1px solid var(--border)' }}>
                                                {req.description && (
                                                    <div style={{ marginBottom: '1rem' }}>
                                                        <div style={{ fontSize: '0.8rem', fontWeight: 600, marginBottom: '0.375rem', color: 'var(--text-secondary)' }}>
                                                            Description
                                                        </div>
                                                        <p style={{ fontSize: '0.9rem' }}>{req.description}</p>
                                                    </div>
                                                )}

                                                <div style={{ fontSize: '0.8rem', fontWeight: 600, marginBottom: '0.5rem', color: 'var(--text-secondary)' }}>
                                                    Acceptance Criteria
                                                </div>
                                                {req.acceptance_criteria.length === 0 ? (
                                                    <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', fontStyle: 'italic' }}>No acceptance criteria defined</p>
                                                ) : (
                                                    <ul style={{ margin: 0, paddingLeft: '1.25rem' }}>
                                                        {req.acceptance_criteria.map((ac, idx) => (
                                                            <li key={idx} style={{ fontSize: '0.9rem', marginBottom: '0.375rem' }}>{ac}</li>
                                                        ))}
                                                    </ul>
                                                )}
                                            </div>
                                        )}
                                    </div>
                                );
                            })}

                            {/* Load More Button */}
                            {hasMore && (
                                <div style={{
                                    padding: '1rem',
                                    textAlign: 'center',
                                    borderTop: '1px solid var(--border)'
                                }}>
                                    <button
                                        className="btn btn-secondary"
                                        onClick={loadMore}
                                        disabled={isLoadingMore}
                                        style={{
                                            display: 'inline-flex',
                                            alignItems: 'center',
                                            gap: '0.5rem'
                                        }}
                                    >
                                        {isLoadingMore ? (
                                            <>
                                                <Loader2 size={16} className="spinning" />
                                                Loading...
                                            </>
                                        ) : (
                                            <>
                                                Load More ({requirements.length} of {totalCount})
                                            </>
                                        )}
                                    </button>
                                </div>
                            )}
                            </>
                        )}
                    </div>
                </div>
            )}

            {/* Traceability Tab Content */}
            {activeTab === 'traceability' && (
                <div className="animate-in stagger-3">
                    {rtmGenSuccess && (
                        <div
                            style={{
                                marginBottom: '1rem',
                                padding: '0.75rem 1rem',
                                borderRadius: '8px',
                                fontSize: '0.85rem',
                                display: 'flex',
                                alignItems: 'center',
                                justifyContent: 'space-between',
                                background: 'rgba(34, 197, 94, 0.08)',
                                border: '1px solid rgba(34, 197, 94, 0.2)',
                                color: 'var(--text-primary)',
                            }}
                        >
                            <span style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                                <CheckCircle size={16} style={{ color: '#22c55e' }} />
                                RTM generated successfully!
                            </span>
                            <div style={{ display: 'flex', gap: '1rem' }}>
                                <Link
                                    href="/rtm"
                                    style={{
                                        display: 'flex',
                                        alignItems: 'center',
                                        gap: '0.25rem',
                                        color: 'var(--primary)',
                                        textDecoration: 'none',
                                        fontWeight: 500,
                                    }}
                                >
                                    View Full RTM <ChevronRight size={14} />
                                </Link>
                                <button
                                    onClick={() => setRtmGenSuccess(false)}
                                    style={{
                                        background: 'none',
                                        border: 'none',
                                        cursor: 'pointer',
                                        color: 'var(--text-secondary)',
                                        padding: '0.125rem',
                                    }}
                                >
                                    <X size={14} />
                                </button>
                            </div>
                        </div>
                    )}
                    {rtmLoading ? (
                        <div style={{ display: 'grid', gridTemplateColumns: '280px 1fr', gap: '2rem' }}>
                            <div className="card" style={{ padding: '1.5rem', height: 'fit-content' }}>
                                <div style={{ width: 180, height: 180, margin: '0 auto', background: 'var(--surface-hover)', borderRadius: '50%', animation: 'pulse 1.5s ease-in-out infinite' }} />
                            </div>
                            <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
                                {[1, 2, 3, 4, 5].map(i => <RtmSkeletonRow key={i} />)}
                            </div>
                        </div>
                    ) : rtmSummary && rtmSummary.total_requirements === 0 ? (
                        <EmptyState
                            icon={<GitBranch size={40} />}
                            title="No requirements to trace"
                            description="Add requirements first using the Requirements tab, then come back to see the traceability matrix."
                            action={
                                <button className="btn btn-primary" onClick={() => setActiveTab('requirements')}>
                                    Go to Requirements
                                </button>
                            }
                        />
                    ) : (
                        <div style={{ display: 'grid', gridTemplateColumns: '280px 1fr', gap: '2rem' }}>
                            {/* Coverage Summary Card */}
                            <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                                <div className="card" style={{ padding: '1.5rem' }}>
                                    <h3 style={{ fontSize: '0.9rem', fontWeight: 600, marginBottom: '1rem', color: 'var(--text-secondary)' }}>Coverage Overview</h3>

                                    {/* Donut Chart */}
                                    <div style={{ width: '100%', height: 180, position: 'relative' }}>
                                        <ResponsiveContainer>
                                            <PieChart>
                                                <Pie
                                                    data={chartData}
                                                    cx="50%"
                                                    cy="50%"
                                                    innerRadius={55}
                                                    outerRadius={75}
                                                    paddingAngle={2}
                                                    dataKey="value"
                                                >
                                                    {chartData.map((entry, index) => (
                                                        <Cell key={`cell-${index}`} fill={entry.color} />
                                                    ))}
                                                </Pie>
                                                <Tooltip
                                                    formatter={(value) => [value, 'Requirements']}
                                                    contentStyle={{
                                                        background: 'var(--surface)',
                                                        border: '1px solid var(--border)',
                                                        borderRadius: '6px'
                                                    }}
                                                />
                                            </PieChart>
                                        </ResponsiveContainer>

                                        {/* Center label */}
                                        <div style={{
                                            position: 'absolute',
                                            top: '50%',
                                            left: '50%',
                                            transform: 'translate(-50%, -50%)',
                                            textAlign: 'center'
                                        }}>
                                            <div style={{ fontSize: '1.75rem', fontWeight: 700, color: coverageColors.covered }}>
                                                {rtmSummary?.coverage_percentage.toFixed(0)}%
                                            </div>
                                            <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>Coverage</div>
                                        </div>
                                    </div>

                                    {/* Stats */}
                                    <div style={{ marginTop: '1rem', display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                                        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.9rem' }}>
                                            <span>Total Requirements</span>
                                            <span style={{ fontWeight: 600 }}>{rtmSummary?.total_requirements}</span>
                                        </div>
                                        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.9rem' }}>
                                            <span style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                                                <span style={{ width: 10, height: 10, borderRadius: '50%', background: coverageColors.covered }} />
                                                Covered
                                            </span>
                                            <span style={{ fontWeight: 600, color: coverageColors.covered }}>{rtmSummary?.covered}</span>
                                        </div>
                                        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.9rem' }}>
                                            <span style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                                                <span style={{ width: 10, height: 10, borderRadius: '50%', background: coverageColors.partial }} />
                                                Partial
                                            </span>
                                            <span style={{ fontWeight: 600, color: coverageColors.partial }}>{rtmSummary?.partial}</span>
                                        </div>
                                        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.9rem' }}>
                                            <span style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                                                <span style={{ width: 10, height: 10, borderRadius: '50%', background: coverageColors.uncovered }} />
                                                Uncovered
                                            </span>
                                            <span style={{ fontWeight: 600, color: coverageColors.uncovered }}>{rtmSummary?.uncovered}</span>
                                        </div>
                                    </div>
                                </div>

                                {/* Coverage Trend */}
                                {trendData.length >= 2 && (
                                    <div className="card" style={{ padding: '1.25rem' }}>
                                        <h3 style={{ fontSize: '0.9rem', fontWeight: 600, marginBottom: '1rem', color: 'var(--text-secondary)' }}>Coverage Trend</h3>
                                        <div style={{ width: '100%', height: 160 }}>
                                            <ResponsiveContainer>
                                                <AreaChart data={trendData} margin={{ top: 5, right: 5, bottom: 5, left: -20 }}>
                                                    <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                                                    <XAxis
                                                        dataKey="created_at"
                                                        tick={{ fontSize: 10 }}
                                                        tickFormatter={(val) => new Date(val).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}
                                                    />
                                                    <YAxis tick={{ fontSize: 10 }} />
                                                    <Tooltip
                                                        labelFormatter={(val) => new Date(val).toLocaleDateString()}
                                                        contentStyle={{
                                                            background: 'var(--surface)',
                                                            border: '1px solid var(--border)',
                                                            borderRadius: '6px',
                                                            fontSize: '0.8rem'
                                                        }}
                                                    />
                                                    <Area type="monotone" dataKey="covered" stackId="1" stroke="#34d399" fill="#34d399" fillOpacity={0.6} name="Covered" />
                                                    <Area type="monotone" dataKey="partial" stackId="1" stroke="#fbbf24" fill="#fbbf24" fillOpacity={0.6} name="Partial" />
                                                    <Area type="monotone" dataKey="uncovered" stackId="1" stroke="#f87171" fill="#f87171" fillOpacity={0.6} name="Uncovered" />
                                                </AreaChart>
                                            </ResponsiveContainer>
                                        </div>
                                    </div>
                                )}

                                {/* Gaps Summary */}
                                {rtmGaps.length > 0 && (
                                    <div className="card" style={{ padding: '1.25rem' }}>
                                        <button
                                            onClick={() => setShowGaps(!showGaps)}
                                            style={{
                                                display: 'flex',
                                                alignItems: 'center',
                                                justifyContent: 'space-between',
                                                width: '100%',
                                                background: 'none',
                                                border: 'none',
                                                cursor: 'pointer',
                                                color: 'var(--text)'
                                            }}
                                        >
                                            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                                                <AlertTriangle size={18} color={coverageColors.uncovered} />
                                                <span style={{ fontWeight: 600, fontSize: '0.9rem' }}>Coverage Gaps ({rtmGaps.length})</span>
                                            </div>
                                            {showGaps ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                                        </button>
                                    </div>
                                )}
                            </div>

                            {/* RTM Table */}
                            <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
                                {/* Header */}
                                <div style={{
                                    display: 'grid',
                                    gridTemplateColumns: '1fr 100px 90px 90px',
                                    gap: '1rem',
                                    padding: '0.875rem 1.25rem',
                                    background: 'var(--surface-hover)',
                                    borderBottom: '1px solid var(--border)',
                                    fontSize: '0.8rem',
                                    fontWeight: 600,
                                    color: 'var(--text-secondary)',
                                    textTransform: 'uppercase',
                                    letterSpacing: '0.05em'
                                }}>
                                    <span>Requirement</span>
                                    <span>Category</span>
                                    <span>Priority</span>
                                    <span>Coverage</span>
                                </div>

                                {/* Filter Bar */}
                                <div style={{
                                    padding: '0.75rem 1.25rem',
                                    borderBottom: '1px solid var(--border)',
                                    display: 'flex',
                                    gap: '0.75rem',
                                    alignItems: 'center',
                                    flexWrap: 'wrap',
                                    background: 'var(--surface)'
                                }}>
                                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flex: 1, minWidth: '180px' }}>
                                        <Search size={14} color="var(--text-secondary)" />
                                        <input
                                            type="text"
                                            placeholder="Search requirements..."
                                            value={rtmSearchTerm}
                                            onChange={e => setRtmSearchTerm(e.target.value)}
                                            style={{
                                                border: 'none',
                                                background: 'transparent',
                                                outline: 'none',
                                                fontSize: '0.85rem',
                                                color: 'var(--text)',
                                                width: '100%'
                                            }}
                                        />
                                    </div>

                                    <div style={{ display: 'flex', gap: '2px', background: 'var(--surface-hover)', borderRadius: '6px', padding: '2px' }}>
                                        {['all', 'covered', 'partial', 'uncovered'].map(status => (
                                            <button
                                                key={status}
                                                onClick={() => setRtmCoverageFilter(status)}
                                                style={{
                                                    padding: '0.25rem 0.625rem',
                                                    borderRadius: '4px',
                                                    border: 'none',
                                                    fontSize: '0.75rem',
                                                    fontWeight: 500,
                                                    cursor: 'pointer',
                                                    textTransform: 'capitalize',
                                                    background: rtmCoverageFilter === status ? 'var(--surface)' : 'transparent',
                                                    color: rtmCoverageFilter === status ? 'var(--text)' : 'var(--text-secondary)',
                                                    boxShadow: rtmCoverageFilter === status ? '0 1px 3px rgba(0,0,0,0.1)' : 'none'
                                                }}
                                            >
                                                {status}
                                            </button>
                                        ))}
                                    </div>

                                    <select
                                        value={rtmCategoryFilter}
                                        onChange={e => setRtmCategoryFilter(e.target.value)}
                                        style={{
                                            padding: '0.3rem 0.5rem',
                                            borderRadius: '6px',
                                            border: '1px solid var(--border)',
                                            fontSize: '0.8rem',
                                            background: 'var(--surface)',
                                            color: 'var(--text)',
                                            cursor: 'pointer'
                                        }}
                                    >
                                        <option value="">All Categories</option>
                                        {rtmCategories.map(cat => (
                                            <option key={cat} value={cat}>{cat}</option>
                                        ))}
                                    </select>

                                    <select
                                        value={rtmPriorityFilter}
                                        onChange={e => setRtmPriorityFilter(e.target.value)}
                                        style={{
                                            padding: '0.3rem 0.5rem',
                                            borderRadius: '6px',
                                            border: '1px solid var(--border)',
                                            fontSize: '0.8rem',
                                            background: 'var(--surface)',
                                            color: 'var(--text)',
                                            cursor: 'pointer'
                                        }}
                                    >
                                        <option value="">All Priorities</option>
                                        <option value="critical">Critical</option>
                                        <option value="high">High</option>
                                        <option value="medium">Medium</option>
                                        <option value="low">Low</option>
                                    </select>

                                    {rtmTotalCount > 0 && (
                                        <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
                                            Showing {rtmRequirements.length} of {rtmTotalCount}
                                        </span>
                                    )}
                                </div>

                                {/* Rows */}
                                {rtmRequirements.length === 0 ? (
                                    <div style={{ padding: '3rem 2rem', textAlign: 'center', color: 'var(--text-secondary)' }}>
                                        No requirements found. Generate RTM to map requirements to tests.
                                    </div>
                                ) : (
                                    rtmRequirements.map(req => {
                                            const isExpanded = expandedRtmReqs.has(req.id);
                                            return (
                                                <div key={req.id} style={{ borderBottom: '1px solid var(--border)' }}>
                                                    <div
                                                        style={{
                                                            display: 'grid',
                                                            gridTemplateColumns: '1fr 100px 90px 90px',
                                                            gap: '1rem',
                                                            padding: '1rem 1.25rem',
                                                            alignItems: 'center',
                                                            cursor: 'pointer',
                                                            background: isExpanded ? 'var(--surface-hover)' : 'transparent'
                                                        }}
                                                        onClick={() => toggleRtmExpanded(req.id)}
                                                    >
                                                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                                                            <span style={{ color: 'var(--text-secondary)' }}>
                                                                {isExpanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                                                            </span>
                                                            <div>
                                                                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.25rem' }}>
                                                                    <span style={{ fontWeight: 600, color: 'var(--primary)', fontSize: '0.8rem' }}>{req.code}</span>
                                                                    <span style={{ fontWeight: 500 }}>{req.title}</span>
                                                                </div>
                                                                {req.tests.length > 0 && (
                                                                    <span style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                                                                        {req.tests.length} test{req.tests.length !== 1 ? 's' : ''}
                                                                    </span>
                                                                )}
                                                            </div>
                                                        </div>

                                                        <span style={{
                                                            padding: '0.25rem 0.5rem',
                                                            borderRadius: '4px',
                                                            fontSize: '0.75rem',
                                                            background: 'rgba(192, 132, 252, 0.12)',
                                                            color: 'var(--accent)',
                                                            textAlign: 'center'
                                                        }}>
                                                            {req.category}
                                                        </span>

                                                        <span style={{
                                                            padding: '0.25rem 0.5rem',
                                                            borderRadius: '4px',
                                                            fontSize: '0.75rem',
                                                            fontWeight: 600,
                                                            textTransform: 'uppercase',
                                                            textAlign: 'center',
                                                            background: req.priority === 'critical' ? 'var(--danger-muted)' :
                                                                req.priority === 'high' ? 'var(--warning-muted)' :
                                                                    req.priority === 'medium' ? 'var(--primary-glow)' : 'rgba(156, 163, 175, 0.1)',
                                                            color: req.priority === 'critical' ? 'var(--danger)' :
                                                                req.priority === 'high' ? 'var(--warning)' :
                                                                    req.priority === 'medium' ? 'var(--primary)' : 'var(--text-tertiary)'
                                                        }}>
                                                            {req.priority}
                                                        </span>

                                                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', justifyContent: 'center' }}>
                                                            {getCoverageIcon(req.coverage_status)}
                                                            <span style={{
                                                                fontSize: '0.8rem',
                                                                fontWeight: 500,
                                                                textTransform: 'capitalize',
                                                                color: coverageColors[req.coverage_status]
                                                            }}>
                                                                {req.coverage_status}
                                                            </span>
                                                        </div>
                                                    </div>

                                                    {/* Expanded Content */}
                                                    {isExpanded && (
                                                        <div style={{ padding: '1rem 1.25rem 1.25rem', paddingLeft: '3rem', background: 'var(--surface-hover)', borderTop: '1px solid var(--border)' }}>
                                                            {req.description && (
                                                                <p style={{ fontSize: '0.9rem', marginBottom: '1rem', color: 'var(--text-secondary)' }}>
                                                                    {req.description}
                                                                </p>
                                                            )}

                                                            {req.tests.length > 0 ? (
                                                                <div>
                                                                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
                                                                        <div style={{ fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-secondary)' }}>
                                                                            Linked Tests
                                                                        </div>
                                                                        <button
                                                                            onClick={(e) => {
                                                                                e.stopPropagation();
                                                                                if (linkingReqId === req.id) {
                                                                                    setLinkingReqId(null);
                                                                                } else {
                                                                                    setLinkingReqId(req.id);
                                                                                    if (availableSpecs.length === 0) fetchSpecs();
                                                                                }
                                                                            }}
                                                                            style={{
                                                                                display: 'inline-flex',
                                                                                alignItems: 'center',
                                                                                gap: '0.25rem',
                                                                                padding: '0.25rem 0.5rem',
                                                                                fontSize: '0.75rem',
                                                                                border: '1px solid var(--border)',
                                                                                borderRadius: '4px',
                                                                                background: 'var(--surface)',
                                                                                color: 'var(--text-secondary)',
                                                                                cursor: 'pointer'
                                                                            }}
                                                                        >
                                                                            <Link2 size={12} />
                                                                            Link Test
                                                                        </button>
                                                                    </div>
                                                                    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                                                                        {req.tests.map((test, idx) => (
                                                                            <div
                                                                                key={idx}
                                                                                style={{
                                                                                    display: 'flex',
                                                                                    alignItems: 'center',
                                                                                    gap: '0.5rem',
                                                                                    padding: '0.5rem 0.75rem',
                                                                                    background: 'var(--surface)',
                                                                                    borderRadius: '6px'
                                                                                }}
                                                                            >
                                                                                <Link
                                                                                    href={`/specs/${test.spec_name}`}
                                                                                    style={{
                                                                                        display: 'flex',
                                                                                        alignItems: 'center',
                                                                                        gap: '0.5rem',
                                                                                        flex: 1,
                                                                                        textDecoration: 'none',
                                                                                        color: 'var(--text)'
                                                                                    }}
                                                                                >
                                                                                    <FileText size={14} color="var(--primary)" />
                                                                                    <span style={{ flex: 1, fontSize: '0.85rem' }}>{test.spec_name}</span>
                                                                                    <span style={{
                                                                                        fontSize: '0.7rem',
                                                                                        padding: '0.125rem 0.375rem',
                                                                                        borderRadius: '4px',
                                                                                        background: 'var(--primary-glow)',
                                                                                        color: 'var(--primary)'
                                                                                    }}>
                                                                                        {(test.confidence * 100).toFixed(0)}% match
                                                                                    </span>
                                                                                </Link>
                                                                                {unlinkingEntryId === test.entry_id ? (
                                                                                    <div style={{ display: 'flex', gap: '0.25rem' }} onClick={e => e.stopPropagation()}>
                                                                                        <button
                                                                                            onClick={() => unlinkTest(test.entry_id)}
                                                                                            style={{
                                                                                                padding: '0.125rem 0.375rem',
                                                                                                fontSize: '0.7rem',
                                                                                                border: 'none',
                                                                                                borderRadius: '3px',
                                                                                                background: 'var(--danger)',
                                                                                                color: 'white',
                                                                                                cursor: 'pointer'
                                                                                            }}
                                                                                        >
                                                                                            Confirm
                                                                                        </button>
                                                                                        <button
                                                                                            onClick={() => setUnlinkingEntryId(null)}
                                                                                            style={{
                                                                                                padding: '0.125rem 0.375rem',
                                                                                                fontSize: '0.7rem',
                                                                                                border: '1px solid var(--border)',
                                                                                                borderRadius: '3px',
                                                                                                background: 'var(--surface)',
                                                                                                color: 'var(--text-secondary)',
                                                                                                cursor: 'pointer'
                                                                                            }}
                                                                                        >
                                                                                            Cancel
                                                                                        </button>
                                                                                    </div>
                                                                                ) : (
                                                                                    <button
                                                                                        onClick={(e) => {
                                                                                            e.stopPropagation();
                                                                                            e.preventDefault();
                                                                                            setUnlinkingEntryId(test.entry_id);
                                                                                        }}
                                                                                        title="Unlink test"
                                                                                        style={{
                                                                                            width: 20,
                                                                                            height: 20,
                                                                                            display: 'flex',
                                                                                            alignItems: 'center',
                                                                                            justifyContent: 'center',
                                                                                            border: 'none',
                                                                                            background: 'transparent',
                                                                                            color: 'var(--text-secondary)',
                                                                                            cursor: 'pointer',
                                                                                            borderRadius: '3px',
                                                                                            flexShrink: 0
                                                                                        }}
                                                                                        onMouseEnter={e => { (e.target as HTMLElement).style.color = 'var(--danger)'; (e.target as HTMLElement).style.background = 'rgba(239, 68, 68, 0.1)'; }}
                                                                                        onMouseLeave={e => { (e.target as HTMLElement).style.color = 'var(--text-secondary)'; (e.target as HTMLElement).style.background = 'transparent'; }}
                                                                                    >
                                                                                        <X size={14} />
                                                                                    </button>
                                                                                )}
                                                                            </div>
                                                                        ))}
                                                                    </div>
                                                                </div>
                                                            ) : (
                                                                <div style={{
                                                                    padding: '1rem',
                                                                    background: 'rgba(239, 68, 68, 0.05)',
                                                                    borderRadius: '6px',
                                                                    border: '1px solid rgba(239, 68, 68, 0.2)'
                                                                }}>
                                                                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.5rem' }}>
                                                                        <AlertTriangle size={16} color="var(--danger)" />
                                                                        <span style={{ fontWeight: 600, fontSize: '0.9rem' }}>No tests linked</span>
                                                                    </div>
                                                                    <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: '0.75rem' }}>
                                                                        Create a test spec to cover this requirement.
                                                                    </p>
                                                                    <div style={{ display: 'flex', gap: '0.5rem' }}>
                                                                        <CreateSpecDropdown req={req} variant="inline" />
                                                                        <button
                                                                            onClick={(e) => {
                                                                                e.stopPropagation();
                                                                                setLinkingReqId(req.id);
                                                                                if (availableSpecs.length === 0) fetchSpecs();
                                                                            }}
                                                                            style={{
                                                                                display: 'inline-flex',
                                                                                alignItems: 'center',
                                                                                gap: '0.375rem',
                                                                                padding: '0.375rem 0.75rem',
                                                                                fontSize: '0.8rem',
                                                                                border: '1px solid var(--border)',
                                                                                borderRadius: '6px',
                                                                                background: 'var(--surface)',
                                                                                color: 'var(--text)',
                                                                                cursor: 'pointer'
                                                                            }}
                                                                        >
                                                                            <Link2 size={14} />
                                                                            Link Test
                                                                        </button>
                                                                    </div>
                                                                </div>
                                                            )}

                                                            {/* Inline Link Test Panel */}
                                                            {linkingReqId === req.id && (
                                                                <div style={{
                                                                    marginTop: '0.75rem',
                                                                    padding: '0.75rem',
                                                                    background: 'var(--surface)',
                                                                    borderRadius: '6px',
                                                                    border: '1px solid var(--border)'
                                                                }} onClick={e => e.stopPropagation()}>
                                                                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
                                                                        <span style={{ fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-secondary)' }}>Select a spec to link</span>
                                                                        <button
                                                                            onClick={() => { setLinkingReqId(null); setSpecSearchTerm(''); }}
                                                                            style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-secondary)' }}
                                                                        >
                                                                            <X size={16} />
                                                                        </button>
                                                                    </div>
                                                                    <input
                                                                        type="text"
                                                                        placeholder="Search specs..."
                                                                        value={specSearchTerm}
                                                                        onChange={e => setSpecSearchTerm(e.target.value)}
                                                                        style={{
                                                                            width: '100%',
                                                                            padding: '0.375rem 0.625rem',
                                                                            fontSize: '0.8rem',
                                                                            border: '1px solid var(--border)',
                                                                            borderRadius: '4px',
                                                                            background: 'var(--surface)',
                                                                            color: 'var(--text)',
                                                                            marginBottom: '0.5rem',
                                                                            outline: 'none'
                                                                        }}
                                                                    />
                                                                    <div style={{ maxHeight: '200px', overflow: 'auto' }}>
                                                                        {specsLoading ? (
                                                                            <div style={{ padding: '1rem', textAlign: 'center', color: 'var(--text-secondary)', fontSize: '0.85rem' }}>Loading specs...</div>
                                                                        ) : availableSpecs
                                                                            .filter(s => !specSearchTerm || s.name.toLowerCase().includes(specSearchTerm.toLowerCase()))
                                                                            .length === 0 ? (
                                                                            <div style={{ padding: '1rem', textAlign: 'center', color: 'var(--text-secondary)', fontSize: '0.85rem' }}>No specs found</div>
                                                                        ) : (
                                                                            availableSpecs
                                                                                .filter(s => !specSearchTerm || s.name.toLowerCase().includes(specSearchTerm.toLowerCase()))
                                                                                .map(spec => (
                                                                                    <div
                                                                                        key={spec.name}
                                                                                        style={{
                                                                                            display: 'flex',
                                                                                            justifyContent: 'space-between',
                                                                                            alignItems: 'center',
                                                                                            padding: '0.375rem 0.5rem',
                                                                                            borderRadius: '4px',
                                                                                            cursor: 'pointer'
                                                                                        }}
                                                                                        onMouseEnter={e => { (e.currentTarget as HTMLElement).style.background = 'var(--surface-hover)'; }}
                                                                                        onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = 'transparent'; }}
                                                                                    >
                                                                                        <span style={{ fontSize: '0.85rem' }}>{spec.name}</span>
                                                                                        <button
                                                                                            onClick={() => linkTest(req.id, spec.name)}
                                                                                            style={{
                                                                                                padding: '0.125rem 0.5rem',
                                                                                                fontSize: '0.7rem',
                                                                                                border: 'none',
                                                                                                borderRadius: '4px',
                                                                                                background: 'var(--primary)',
                                                                                                color: 'white',
                                                                                                cursor: 'pointer'
                                                                                            }}
                                                                                        >
                                                                                            Link
                                                                                        </button>
                                                                                    </div>
                                                                                ))
                                                                        )}
                                                                    </div>
                                                                </div>
                                                            )}
                                                        </div>
                                                    )}
                                                </div>
                                            );
                                        })
                                )}

                                {/* Load More RTM Button */}
                                {rtmHasMore && rtmRequirements.length > 0 && (
                                    <div style={{ padding: '1.5rem', textAlign: 'center', borderTop: '1px solid var(--border)' }}>
                                        <button
                                            onClick={loadMoreRtm}
                                            disabled={rtmIsLoadingMore}
                                            style={{
                                                padding: '0.625rem 2rem',
                                                borderRadius: '8px',
                                                border: '1px solid var(--border)',
                                                background: 'var(--surface)',
                                                color: 'var(--text)',
                                                fontSize: '0.85rem',
                                                fontWeight: 500,
                                                cursor: rtmIsLoadingMore ? 'not-allowed' : 'pointer',
                                                display: 'inline-flex',
                                                alignItems: 'center',
                                                gap: '0.5rem'
                                            }}
                                        >
                                            {rtmIsLoadingMore ? (
                                                <>
                                                    <Loader2 size={14} style={{ animation: 'spin 1s linear infinite' }} />
                                                    Loading...
                                                </>
                                            ) : (
                                                `Load More (${rtmRequirements.length} of ${rtmTotalCount})`
                                            )}
                                        </button>
                                    </div>
                                )}
                            </div>
                        </div>
                    )}

                    {/* Gaps Section */}
                    {showGaps && rtmGaps.length > 0 && !rtmLoading && (
                        <div style={{ marginTop: '2rem' }}>
                            <h3 style={{ fontSize: '1.1rem', fontWeight: 600, marginBottom: '1rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                                <AlertTriangle size={20} color={coverageColors.uncovered} />
                                Coverage Gaps ({rtmGaps.length} uncovered requirements)
                            </h3>

                            <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                                {rtmGaps.map(gap => (
                                    <div
                                        key={gap.requirement_id}
                                        className="card"
                                        style={{
                                            padding: '1.25rem',
                                            borderLeft: `4px solid ${gap.priority === 'critical' ? 'var(--danger)' : gap.priority === 'high' ? 'var(--warning)' : 'var(--primary)'}`
                                        }}
                                    >
                                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '0.75rem' }}>
                                            <div>
                                                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.25rem' }}>
                                                    <span style={{ fontWeight: 600, color: 'var(--primary)' }}>{gap.requirement_code}</span>
                                                    <span style={{
                                                        padding: '0.125rem 0.375rem',
                                                        borderRadius: '4px',
                                                        fontSize: '0.7rem',
                                                        fontWeight: 600,
                                                        textTransform: 'uppercase',
                                                        background: gap.priority === 'critical' ? 'var(--danger-muted)' : gap.priority === 'high' ? 'var(--warning-muted)' : 'var(--primary-glow)',
                                                        color: gap.priority === 'critical' ? 'var(--danger)' : gap.priority === 'high' ? 'var(--warning)' : 'var(--primary)'
                                                    }}>
                                                        {gap.priority}
                                                    </span>
                                                </div>
                                                <h4 style={{ fontWeight: 500, marginBottom: '0.5rem' }}>{gap.title}</h4>
                                            </div>
                                            <CreateSpecDropdown
                                                req={{
                                                    id: gap.requirement_id,
                                                    code: gap.requirement_code,
                                                    title: gap.title,
                                                    description: null,
                                                    category: gap.category,
                                                    priority: gap.priority,
                                                    status: 'draft',
                                                    acceptance_criteria: [],
                                                    tests: [],
                                                    coverage_status: 'uncovered'
                                                }}
                                                variant="button"
                                            />
                                        </div>

                                        {gap.suggested_test && (
                                            <div style={{ padding: '0.75rem', background: 'var(--surface-hover)', borderRadius: '6px', fontSize: '0.85rem' }}>
                                                <div style={{ fontWeight: 600, marginBottom: '0.375rem' }}>Suggested Test: {gap.suggested_test.test_name}</div>
                                                <p style={{ color: 'var(--text-secondary)', marginBottom: '0.5rem' }}>{gap.suggested_test.description}</p>
                                                {gap.suggested_test.steps && gap.suggested_test.steps.length > 0 && (
                                                    <div style={{ color: 'var(--text-secondary)' }}>
                                                        Steps: {gap.suggested_test.steps.slice(0, 3).join(' → ')}
                                                        {gap.suggested_test.steps.length > 3 && '...'}
                                                    </div>
                                                )}
                                            </div>
                                        )}
                                    </div>
                                ))}
                            </div>
                        </div>
                    )}
                </div>
            )}

            {/* Create Modal */}
            {createModalOpen && (
                <div className="modal-overlay" onClick={() => !isCreating && setCreateModalOpen(false)}>
                    <div className="modal-content" onClick={e => e.stopPropagation()} style={{ width: '550px', maxHeight: '80vh', overflow: 'auto' }}>
                        <h2 style={{ marginBottom: '1.5rem', display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                            <Plus size={24} color="var(--primary)" />
                            Add Requirement
                        </h2>

                        <div style={{ marginBottom: '1rem' }}>
                            <label style={{ display: 'block', marginBottom: '0.375rem', fontWeight: 500 }}>
                                Title <span style={{ color: 'var(--danger)' }}>*</span>
                            </label>
                            <input
                                type="text"
                                className="input"
                                value={newReq.title}
                                onChange={e => setNewReq({ ...newReq, title: e.target.value })}
                                placeholder="User can log in with email and password"
                                style={{ width: '100%' }}
                            />
                        </div>

                        <div style={{ marginBottom: '1rem' }}>
                            <label style={{ display: 'block', marginBottom: '0.375rem', fontWeight: 500 }}>Description</label>
                            <textarea
                                className="input"
                                value={newReq.description}
                                onChange={e => setNewReq({ ...newReq, description: e.target.value })}
                                placeholder="Detailed description..."
                                rows={3}
                                style={{ width: '100%', resize: 'vertical' }}
                            />
                        </div>

                        <div style={{ display: 'flex', gap: '1rem', marginBottom: '1rem' }}>
                            <div style={{ flex: 1 }}>
                                <label style={{ display: 'block', marginBottom: '0.375rem', fontWeight: 500 }}>Category</label>
                                <input
                                    type="text"
                                    className="input"
                                    value={newReq.category}
                                    onChange={e => setNewReq({ ...newReq, category: e.target.value })}
                                    placeholder="auth, navigation, etc."
                                    style={{ width: '100%' }}
                                />
                            </div>
                            <div style={{ flex: 1 }}>
                                <label style={{ display: 'block', marginBottom: '0.375rem', fontWeight: 500 }}>Priority</label>
                                <select
                                    className="input"
                                    value={newReq.priority}
                                    onChange={e => setNewReq({ ...newReq, priority: e.target.value })}
                                    style={{ width: '100%' }}
                                >
                                    <option value="critical">Critical</option>
                                    <option value="high">High</option>
                                    <option value="medium">Medium</option>
                                    <option value="low">Low</option>
                                </select>
                            </div>
                        </div>

                        <div style={{ marginBottom: '1.5rem' }}>
                            <label style={{ display: 'block', marginBottom: '0.375rem', fontWeight: 500 }}>Acceptance Criteria</label>
                            {newReq.acceptance_criteria.map((ac, idx) => (
                                <div key={idx} style={{ display: 'flex', gap: '0.5rem', marginBottom: '0.5rem' }}>
                                    <input
                                        type="text"
                                        className="input"
                                        value={ac}
                                        onChange={e => {
                                            const updated = [...newReq.acceptance_criteria];
                                            updated[idx] = e.target.value;
                                            setNewReq({ ...newReq, acceptance_criteria: updated });
                                        }}
                                        placeholder={`Criterion ${idx + 1}`}
                                        style={{ flex: 1 }}
                                    />
                                    {newReq.acceptance_criteria.length > 1 && (
                                        <button
                                            className="btn-icon"
                                            onClick={() => {
                                                setNewReq({
                                                    ...newReq,
                                                    acceptance_criteria: newReq.acceptance_criteria.filter((_, i) => i !== idx)
                                                });
                                            }}
                                            style={{ color: 'var(--danger)' }}
                                        >
                                            <X size={16} />
                                        </button>
                                    )}
                                </div>
                            ))}
                            <button
                                className="btn btn-secondary btn-sm"
                                onClick={() => setNewReq({ ...newReq, acceptance_criteria: [...newReq.acceptance_criteria, ''] })}
                                style={{ marginTop: '0.5rem' }}
                            >
                                + Add Criterion
                            </button>
                        </div>

                        {/* Duplicate Warning */}
                        {duplicateWarning && (
                            <div style={{
                                padding: '1rem',
                                background: 'var(--warning-muted)',
                                border: '1px solid rgba(245, 158, 11, 0.3)',
                                borderRadius: '8px',
                                marginBottom: '1.5rem'
                            }}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.75rem' }}>
                                    <AlertTriangle size={18} color="var(--warning)" />
                                    <span style={{ fontWeight: 600 }}>
                                        {duplicateWarning.has_exact_match
                                            ? 'Exact duplicate found!'
                                            : `${duplicateWarning.near_matches.length} similar requirement${duplicateWarning.near_matches.length > 1 ? 's' : ''} found`
                                        }
                                    </span>
                                </div>

                                {duplicateWarning.exact_match && (
                                    <div style={{ padding: '0.75rem', background: 'var(--surface)', borderRadius: '6px', marginBottom: '0.75rem' }}>
                                        <strong>{duplicateWarning.exact_match.req_code}</strong>: {duplicateWarning.exact_match.title}
                                        <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginTop: '0.25rem' }}>
                                            {duplicateWarning.exact_match.acceptance_criteria.length} acceptance criteria
                                        </div>
                                    </div>
                                )}

                                {!duplicateWarning.has_exact_match && duplicateWarning.near_matches.slice(0, 3).map(match => (
                                    <div key={match.requirement_id} style={{ padding: '0.75rem', background: 'var(--surface)', borderRadius: '6px', marginBottom: '0.5rem' }}>
                                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                                            <span><strong>{match.req_code}</strong>: {match.title}</span>
                                            <span style={{ fontSize: '0.75rem', color: 'var(--warning)', fontWeight: 600 }}>
                                                {(match.similarity * 100).toFixed(0)}% similar
                                            </span>
                                        </div>
                                    </div>
                                ))}

                                <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginTop: '0.75rem' }}>
                                    {duplicateWarning.recommendation === 'update_existing'
                                        ? 'Consider updating the existing requirement instead of creating a new one.'
                                        : 'Consider reviewing these similar requirements before creating a new one.'
                                    }
                                </p>
                            </div>
                        )}

                        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '1rem' }}>
                            <button className="btn btn-secondary" onClick={() => { setCreateModalOpen(false); setDuplicateWarning(null); }} disabled={isCreating}>
                                Cancel
                            </button>
                            {duplicateWarning ? (
                                <button
                                    className="btn btn-primary"
                                    onClick={() => createRequirementWithCheck(true)}
                                    disabled={isCreating}
                                >
                                    {isCreating ? 'Creating...' : 'Create Anyway'}
                                </button>
                            ) : (
                                <button
                                    className="btn btn-primary"
                                    onClick={createRequirement}
                                    disabled={!newReq.title || isCreating || checkingDuplicate}
                                >
                                    {checkingDuplicate ? 'Checking...' : isCreating ? 'Creating...' : 'Create Requirement'}
                                </button>
                            )}
                        </div>
                    </div>
                </div>
            )}

            {/* Duplicate Groups Modal */}
            {duplicateModalOpen && (
                <div className="modal-overlay" onClick={() => !isMerging && setDuplicateModalOpen(false)}>
                    <div className="modal-content" onClick={e => e.stopPropagation()} style={{ width: '650px', maxHeight: '80vh', overflow: 'auto' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.5rem' }}>
                            <div>
                                <h2 style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '0.5rem' }}>
                                    <Sparkles size={24} color="var(--primary)" />
                                    Optimize Requirements
                                </h2>
                                <span style={{
                                    display: 'inline-flex',
                                    alignItems: 'center',
                                    gap: '0.375rem',
                                    padding: '0.25rem 0.625rem',
                                    borderRadius: '9999px',
                                    fontSize: '0.75rem',
                                    fontWeight: 500,
                                    background: duplicateMode === 'semantic' ? 'var(--success-muted)' : 'var(--primary-glow)',
                                    color: duplicateMode === 'semantic' ? 'var(--success)' : 'var(--primary)'
                                }}>
                                    {duplicateMode === 'semantic' ? (
                                        <>AI-powered (semantic matching)</>
                                    ) : (
                                        <>Exact title matching</>
                                    )}
                                </span>
                            </div>
                            <button
                                onClick={() => setDuplicateModalOpen(false)}
                                style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-secondary)' }}
                            >
                                <X size={24} />
                            </button>
                        </div>

                        {duplicateGroups.length === 0 ? (
                            <div style={{ textAlign: 'center', padding: '3rem 2rem' }}>
                                <div style={{
                                    width: 64,
                                    height: 64,
                                    background: 'var(--success-muted)',
                                    borderRadius: '50%',
                                    display: 'flex',
                                    alignItems: 'center',
                                    justifyContent: 'center',
                                    margin: '0 auto 1rem'
                                }}>
                                    <CheckCircle size={32} color="var(--success)" />
                                </div>
                                <h3 style={{ fontSize: '1.1rem', fontWeight: 600, marginBottom: '0.5rem' }}>No duplicates found</h3>
                                <p style={{ color: 'var(--text-secondary)' }}>
                                    Your requirements are clean and well-organized.
                                </p>
                            </div>
                        ) : (
                            <>
                                <p style={{ marginBottom: '1.5rem', color: 'var(--text-secondary)' }}>
                                    Found <strong>{duplicateGroups.length}</strong> group{duplicateGroups.length > 1 ? 's' : ''} of similar requirements.
                                    Merge duplicates to keep your requirements clean and consolidate acceptance criteria.
                                </p>

                                <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                                    {duplicateGroups.map(group => (
                                        <div
                                            key={group.canonical_id}
                                            style={{
                                                padding: '1.25rem',
                                                background: 'var(--surface-hover)',
                                                borderRadius: '8px',
                                                border: '1px solid var(--border)'
                                            }}
                                        >
                                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '1rem' }}>
                                                <div>
                                                    <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', marginBottom: '0.25rem' }}>
                                                        Keep (canonical)
                                                    </div>
                                                    <div style={{ fontWeight: 600 }}>
                                                        <span style={{ color: 'var(--primary)' }}>{group.canonical_code}</span>: {group.canonical_title}
                                                    </div>
                                                </div>
                                                <button
                                                    className="btn btn-primary btn-sm"
                                                    onClick={() => mergeGroup(group)}
                                                    disabled={isMerging}
                                                    style={{ display: 'flex', alignItems: 'center', gap: '0.375rem' }}
                                                >
                                                    {isMerging && mergingGroup?.canonical_id === group.canonical_id
                                                        ? <Loader2 size={14} className="spinning" />
                                                        : <Merge size={14} />
                                                    }
                                                    Merge
                                                </button>
                                            </div>

                                            <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', marginBottom: '0.5rem' }}>
                                                Duplicates to merge ({group.duplicates.length})
                                            </div>
                                            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                                                {group.duplicates.map(dup => (
                                                    <div
                                                        key={dup.requirement_id}
                                                        style={{
                                                            padding: '0.75rem',
                                                            background: 'var(--surface)',
                                                            borderRadius: '6px',
                                                            display: 'flex',
                                                            justifyContent: 'space-between',
                                                            alignItems: 'center'
                                                        }}
                                                    >
                                                        <div>
                                                            <span style={{ color: 'var(--text-secondary)' }}>{dup.req_code}:</span> {dup.title}
                                                            <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
                                                                {dup.acceptance_criteria.length} criteria
                                                            </div>
                                                        </div>
                                                        <span style={{
                                                            padding: '0.25rem 0.5rem',
                                                            borderRadius: '4px',
                                                            fontSize: '0.7rem',
                                                            fontWeight: 600,
                                                            background: 'var(--primary-glow)',
                                                            color: 'var(--primary)'
                                                        }}>
                                                            {(dup.similarity * 100).toFixed(0)}% match
                                                        </span>
                                                    </div>
                                                ))}
                                            </div>

                                            {group.merged_criteria.length > 0 && (
                                                <div style={{ marginTop: '1rem', padding: '0.75rem', background: 'rgba(16, 185, 129, 0.05)', borderRadius: '6px', border: '1px solid rgba(16, 185, 129, 0.2)' }}>
                                                    <div style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--success)', marginBottom: '0.5rem' }}>
                                                        Merged criteria preview ({group.merged_criteria.length} unique)
                                                    </div>
                                                    <ul style={{ margin: 0, paddingLeft: '1.25rem', fontSize: '0.85rem' }}>
                                                        {group.merged_criteria.slice(0, 4).map((crit, idx) => (
                                                            <li key={idx} style={{ marginBottom: '0.25rem' }}>{crit}</li>
                                                        ))}
                                                        {group.merged_criteria.length > 4 && (
                                                            <li style={{ color: 'var(--text-secondary)' }}>
                                                                +{group.merged_criteria.length - 4} more...
                                                            </li>
                                                        )}
                                                    </ul>
                                                </div>
                                            )}
                                        </div>
                                    ))}
                                </div>
                            </>
                        )}

                        <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: '1.5rem' }}>
                            <button className="btn btn-secondary" onClick={() => setDuplicateModalOpen(false)}>
                                Close
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {/* Edit Modal */}
            {editModalOpen && editingReq && (
                <div className="modal-overlay" onClick={() => !isSaving && setEditModalOpen(false)}>
                    <div className="modal-content" onClick={e => e.stopPropagation()} style={{ width: '550px', maxHeight: '80vh', overflow: 'auto' }}>
                        <h2 style={{ marginBottom: '1.5rem', display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                            <Edit size={24} color="var(--primary)" />
                            Edit Requirement
                        </h2>

                        <div style={{ marginBottom: '1rem' }}>
                            <label style={{ display: 'block', marginBottom: '0.375rem', fontWeight: 500 }}>Title</label>
                            <input
                                type="text"
                                className="input"
                                value={editingReq.title}
                                onChange={e => setEditingReq({ ...editingReq, title: e.target.value })}
                                style={{ width: '100%' }}
                            />
                        </div>

                        <div style={{ marginBottom: '1rem' }}>
                            <label style={{ display: 'block', marginBottom: '0.375rem', fontWeight: 500 }}>Description</label>
                            <textarea
                                className="input"
                                value={editingReq.description || ''}
                                onChange={e => setEditingReq({ ...editingReq, description: e.target.value })}
                                rows={3}
                                style={{ width: '100%', resize: 'vertical' }}
                            />
                        </div>

                        <div style={{ display: 'flex', gap: '1rem', marginBottom: '1rem' }}>
                            <div style={{ flex: 1 }}>
                                <label style={{ display: 'block', marginBottom: '0.375rem', fontWeight: 500 }}>Category</label>
                                <input
                                    type="text"
                                    className="input"
                                    value={editingReq.category}
                                    onChange={e => setEditingReq({ ...editingReq, category: e.target.value })}
                                    style={{ width: '100%' }}
                                />
                            </div>
                            <div style={{ flex: 1 }}>
                                <label style={{ display: 'block', marginBottom: '0.375rem', fontWeight: 500 }}>Priority</label>
                                <select
                                    className="input"
                                    value={editingReq.priority}
                                    onChange={e => setEditingReq({ ...editingReq, priority: e.target.value })}
                                    style={{ width: '100%' }}
                                >
                                    <option value="critical">Critical</option>
                                    <option value="high">High</option>
                                    <option value="medium">Medium</option>
                                    <option value="low">Low</option>
                                </select>
                            </div>
                        </div>

                        <div style={{ marginBottom: '1rem' }}>
                            <label style={{ display: 'block', marginBottom: '0.375rem', fontWeight: 500 }}>Status</label>
                            <select
                                className="input"
                                value={editingReq.status}
                                onChange={e => setEditingReq({ ...editingReq, status: e.target.value })}
                                style={{ width: '100%' }}
                            >
                                <option value="draft">Draft</option>
                                <option value="approved">Approved</option>
                                <option value="implemented">Implemented</option>
                                <option value="deprecated">Deprecated</option>
                            </select>
                        </div>

                        <div style={{ marginBottom: '1.5rem' }}>
                            <label style={{ display: 'block', marginBottom: '0.375rem', fontWeight: 500 }}>Acceptance Criteria</label>
                            {editingReq.acceptance_criteria.map((ac, idx) => (
                                <div key={idx} style={{ display: 'flex', gap: '0.5rem', marginBottom: '0.5rem' }}>
                                    <input
                                        type="text"
                                        className="input"
                                        value={ac}
                                        onChange={e => {
                                            const updated = [...editingReq.acceptance_criteria];
                                            updated[idx] = e.target.value;
                                            setEditingReq({ ...editingReq, acceptance_criteria: updated });
                                        }}
                                        style={{ flex: 1 }}
                                    />
                                    <button
                                        className="btn-icon"
                                        onClick={() => {
                                            setEditingReq({
                                                ...editingReq,
                                                acceptance_criteria: editingReq.acceptance_criteria.filter((_, i) => i !== idx)
                                            });
                                        }}
                                        style={{ color: 'var(--danger)' }}
                                    >
                                        <X size={16} />
                                    </button>
                                </div>
                            ))}
                            <button
                                className="btn btn-secondary btn-sm"
                                onClick={() => setEditingReq({ ...editingReq, acceptance_criteria: [...editingReq.acceptance_criteria, ''] })}
                                style={{ marginTop: '0.5rem' }}
                            >
                                + Add Criterion
                            </button>
                        </div>

                        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '1rem' }}>
                            <button className="btn btn-secondary" onClick={() => setEditModalOpen(false)} disabled={isSaving}>
                                Cancel
                            </button>
                            <button className="btn btn-primary" onClick={saveEdit} disabled={isSaving}>
                                {isSaving ? 'Saving...' : 'Save Changes'}
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {/* Delete Modal */}
            {deleteModalOpen && deletingReq && (
                <div className="modal-overlay" onClick={() => !isDeleting && setDeleteModalOpen(false)}>
                    <div className="modal-content" onClick={e => e.stopPropagation()} style={{ width: '400px', maxHeight: '80vh', overflow: 'auto' }}>
                        <h2 style={{ marginBottom: '1rem', display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                            <AlertCircle size={24} color="var(--danger)" />
                            Delete Requirement
                        </h2>

                        <p style={{ marginBottom: '1rem' }}>Are you sure you want to delete this requirement?</p>

                        <div style={{ padding: '0.75rem', background: 'var(--surface-hover)', borderRadius: '6px', marginBottom: '1.5rem' }}>
                            <strong>{deletingReq.req_code}</strong>: {deletingReq.title}
                        </div>

                        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '1rem' }}>
                            <button className="btn btn-secondary" onClick={() => setDeleteModalOpen(false)} disabled={isDeleting}>
                                Cancel
                            </button>
                            <button
                                className="btn"
                                onClick={confirmDelete}
                                disabled={isDeleting}
                                style={{ background: 'var(--danger)', color: 'white' }}
                            >
                                {isDeleting ? 'Deleting...' : 'Delete'}
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {/* Snapshot Modal */}
            {snapshotModalOpen && (
                <div className="modal-overlay" onClick={() => !creatingSnapshot && setSnapshotModalOpen(false)}>
                    <div className="modal-content" onClick={e => e.stopPropagation()} style={{ width: '500px', maxHeight: '80vh', overflow: 'auto' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.5rem' }}>
                            <h2 style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                                <Camera size={24} color="var(--primary)" />
                                Create RTM Snapshot
                            </h2>
                            <button
                                onClick={() => setSnapshotModalOpen(false)}
                                style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-secondary)' }}
                            >
                                <X size={24} />
                            </button>
                        </div>

                        <div style={{ marginBottom: '1.5rem' }}>
                            <label style={{ display: 'block', marginBottom: '0.5rem', fontWeight: 500 }}>
                                Snapshot Name <span style={{ color: 'var(--text-secondary)', fontWeight: 400 }}>(optional)</span>
                            </label>
                            <input
                                type="text"
                                className="input"
                                placeholder="e.g., Release 1.0 baseline"
                                value={snapshotName}
                                onChange={e => setSnapshotName(e.target.value)}
                                style={{ width: '100%' }}
                            />
                        </div>

                        {rtmSummary && (
                            <div style={{
                                padding: '1rem',
                                background: 'var(--surface-hover)',
                                borderRadius: '8px',
                                marginBottom: '1.5rem'
                            }}>
                                <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: '0.5rem' }}>Current Coverage</div>
                                <div style={{ display: 'flex', gap: '1.5rem', fontSize: '0.9rem' }}>
                                    <span><strong>{rtmSummary.total_requirements}</strong> total</span>
                                    <span style={{ color: coverageColors.covered }}><strong>{rtmSummary.covered}</strong> covered</span>
                                    <span style={{ color: coverageColors.partial }}><strong>{rtmSummary.partial}</strong> partial</span>
                                    <span style={{ color: coverageColors.uncovered }}><strong>{rtmSummary.uncovered}</strong> uncovered</span>
                                </div>
                                <div style={{ marginTop: '0.5rem', fontSize: '1.25rem', fontWeight: 700, color: coverageColors.covered }}>
                                    {rtmSummary.coverage_percentage.toFixed(1)}% coverage
                                </div>
                            </div>
                        )}

                        {/* Previous Snapshots */}
                        {snapshots.length > 0 && !selectedSnapshot && (
                            <div style={{ marginBottom: '1.5rem' }}>
                                <div style={{ fontSize: '0.85rem', fontWeight: 600, marginBottom: '0.75rem', color: 'var(--text-secondary)' }}>
                                    Recent Snapshots (click to view)
                                </div>
                                <div style={{ maxHeight: '200px', overflow: 'auto', display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                                    {snapshotsLoading ? (
                                        <div style={{ textAlign: 'center', padding: '1rem', color: 'var(--text-secondary)' }}>Loading...</div>
                                    ) : (
                                        snapshots.slice(0, 5).map(snap => (
                                            <div
                                                key={snap.id}
                                                onClick={() => fetchSnapshotDetail(snap.id)}
                                                style={{
                                                    padding: '0.75rem',
                                                    background: 'var(--surface)',
                                                    borderRadius: '6px',
                                                    border: '1px solid var(--border)',
                                                    display: 'flex',
                                                    justifyContent: 'space-between',
                                                    alignItems: 'center',
                                                    cursor: 'pointer'
                                                }}
                                                onMouseEnter={e => { (e.currentTarget as HTMLElement).style.borderColor = 'var(--primary)'; }}
                                                onMouseLeave={e => { (e.currentTarget as HTMLElement).style.borderColor = 'var(--border)'; }}
                                            >
                                                <div>
                                                    <div style={{ fontWeight: 500, fontSize: '0.9rem' }}>
                                                        {snap.snapshot_name || new Date(snap.created_at).toLocaleDateString()}
                                                    </div>
                                                    <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                                                        {new Date(snap.created_at).toLocaleString()}
                                                    </div>
                                                </div>
                                                <span style={{ fontWeight: 600, color: coverageColors.covered }}>
                                                    {snap.coverage_percentage.toFixed(0)}%
                                                </span>
                                            </div>
                                        ))
                                    )}
                                </div>
                            </div>
                        )}

                        {/* Snapshot Detail */}
                        {selectedSnapshot && (
                            <div style={{ marginBottom: '1.5rem' }}>
                                <button
                                    onClick={() => setSelectedSnapshot(null)}
                                    style={{
                                        display: 'flex',
                                        alignItems: 'center',
                                        gap: '0.375rem',
                                        background: 'none',
                                        border: 'none',
                                        cursor: 'pointer',
                                        color: 'var(--primary)',
                                        fontSize: '0.85rem',
                                        padding: 0,
                                        marginBottom: '0.75rem'
                                    }}
                                >
                                    <ChevronRight size={14} style={{ transform: 'rotate(180deg)' }} />
                                    Back to snapshots
                                </button>
                                <div style={{
                                    padding: '1rem',
                                    background: 'var(--surface-hover)',
                                    borderRadius: '8px',
                                    border: '1px solid var(--border)'
                                }}>
                                    <div style={{ fontWeight: 600, marginBottom: '0.5rem' }}>
                                        {selectedSnapshot.snapshot_name || 'Snapshot'}
                                    </div>
                                    <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '0.75rem' }}>
                                        {new Date(selectedSnapshot.created_at).toLocaleString()}
                                    </div>
                                    <div style={{ display: 'flex', gap: '1rem', fontSize: '0.85rem', marginBottom: '0.75rem' }}>
                                        <span style={{ color: coverageColors.covered }}>
                                            <strong>{selectedSnapshot.covered_requirements}</strong> covered
                                        </span>
                                        <span style={{ color: coverageColors.partial }}>
                                            <strong>{selectedSnapshot.partial_requirements}</strong> partial
                                        </span>
                                        <span style={{ color: coverageColors.uncovered }}>
                                            <strong>{selectedSnapshot.uncovered_requirements}</strong> uncovered
                                        </span>
                                    </div>
                                    <div style={{ fontSize: '1.1rem', fontWeight: 700, color: coverageColors.covered }}>
                                        {selectedSnapshot.coverage_percentage.toFixed(1)}% coverage
                                    </div>
                                    {selectedSnapshot.data && selectedSnapshot.data.requirements && (
                                        <div style={{ marginTop: '0.75rem', maxHeight: '200px', overflow: 'auto' }}>
                                            <div style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-secondary)', marginBottom: '0.5rem' }}>
                                                Requirements ({selectedSnapshot.data.requirements.length})
                                            </div>
                                            {selectedSnapshot.data.requirements.slice(0, 20).map((r: any, idx: number) => (
                                                <div
                                                    key={idx}
                                                    style={{
                                                        display: 'flex',
                                                        justifyContent: 'space-between',
                                                        alignItems: 'center',
                                                        padding: '0.375rem 0',
                                                        borderBottom: '1px solid var(--border)',
                                                        fontSize: '0.8rem'
                                                    }}
                                                >
                                                    <span style={{ display: 'flex', alignItems: 'center', gap: '0.375rem' }}>
                                                        <span style={{ fontWeight: 600, color: 'var(--primary)', fontSize: '0.75rem' }}>{r.code}</span>
                                                        <span style={{ color: 'var(--text)' }}>{r.title}</span>
                                                    </span>
                                                    <span style={{
                                                        fontSize: '0.7rem',
                                                        textTransform: 'capitalize',
                                                        color: r.coverage_status === 'covered' ? coverageColors.covered
                                                            : r.coverage_status === 'partial' ? coverageColors.partial
                                                            : coverageColors.uncovered
                                                    }}>
                                                        {r.coverage_status}
                                                    </span>
                                                </div>
                                            ))}
                                            {selectedSnapshot.data.requirements.length > 20 && (
                                                <div style={{ padding: '0.5rem 0', fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
                                                    +{selectedSnapshot.data.requirements.length - 20} more...
                                                </div>
                                            )}
                                        </div>
                                    )}
                                </div>
                            </div>
                        )}

                        {snapshotDetailLoading && (
                            <div style={{ textAlign: 'center', padding: '1rem', color: 'var(--text-secondary)', marginBottom: '1rem' }}>
                                <Loader2 size={20} className="spinning" style={{ display: 'inline-block' }} /> Loading snapshot...
                            </div>
                        )}

                        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '1rem' }}>
                            <button className="btn btn-secondary" onClick={() => { setSnapshotModalOpen(false); setSelectedSnapshot(null); }} disabled={creatingSnapshot}>
                                Cancel
                            </button>
                            <button className="btn btn-primary" onClick={createSnapshot} disabled={creatingSnapshot}>
                                {creatingSnapshot ? 'Creating...' : 'Create Snapshot'}
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {/* Generate Spec Modal */}
            {generateSpecModalOpen && selectedReqForSpec && (
                <GenerateSpecModal
                    requirement={{
                        id: selectedReqForSpec.id,
                        req_code: 'req_code' in selectedReqForSpec ? selectedReqForSpec.req_code : (selectedReqForSpec as RtmRequirement).code,
                        title: selectedReqForSpec.title,
                        description: selectedReqForSpec.description,
                        category: selectedReqForSpec.category,
                        priority: selectedReqForSpec.priority,
                        acceptance_criteria: selectedReqForSpec.acceptance_criteria,
                        source_session_id: 'source_session_id' in selectedReqForSpec ? selectedReqForSpec.source_session_id : null
                    }}
                    onClose={() => {
                        setGenerateSpecModalOpen(false);
                        setSelectedReqForSpec(null);
                    }}
                    onSuccess={handleSpecGenerated}
                />
            )}

            <style jsx>{`
                .modal-overlay {
                    position: fixed;
                    top: 0; left: 0; right: 0; bottom: 0;
                    background: rgba(0,0,0,0.5);
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    z-index: 1000;
                    backdrop-filter: blur(2px);
                }
                .modal-content {
                    background: var(--surface);
                    padding: 2rem;
                    border-radius: 12px;
                    border: 1px solid var(--border);
                    box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.1), 0 10px 10px -5px rgba(0, 0, 0, 0.04);
                }
                @keyframes pulse {
                    0%, 100% { opacity: 1; }
                    50% { opacity: 0.4; }
                }
                :global(.spinning) {
                    animation: spin 1s linear infinite;
                }
                @keyframes spin {
                    from { transform: rotate(0deg); }
                    to { transform: rotate(360deg); }
                }
            `}</style>
        </PageLayout>
    );
}
