'use client';
import React, { useState, useEffect, useMemo, useCallback } from 'react';
import { CheckSquare, Search, ChevronDown, ChevronRight, Edit, Trash2, Plus, X, AlertCircle, GitBranch, FileText, AlertTriangle, CheckCircle, Loader2, Sparkles, Merge, SlidersHorizontal } from 'lucide-react';
import { useProject } from '@/contexts/ProjectContext';
import Link from 'next/link';
import GenerateSpecModal from '@/components/GenerateSpecModal';
import { API_BASE } from '@/lib/api';
import { WorkflowBreadcrumb } from '@/components/workflow/WorkflowBreadcrumb';
import { PageLayout } from '@/components/ui/page-layout';
import { PageHeader } from '@/components/ui/page-header';
import { EmptyState } from '@/components/ui/empty-state';
import { ListPageSkeleton } from '@/components/ui/page-skeleton';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuLabel,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';

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
    truth_state?: string | null;
    source_type?: string | null;
    confidence?: number | null;
    uncertainty_reason?: string | null;
    confirmed_by?: string | null;
    confirmed_at?: string | null;
    rejected_by?: string | null;
    rejected_at?: string | null;
    created_at: string;
    updated_at: string;
}

interface Stats {
    total: number;
    by_category: Record<string, number>;
    by_priority: Record<string, number>;
    by_status: Record<string, number>;
}

interface SpecStatusResponse {
    has_spec: boolean;
    spec_path?: string;
    spec_name?: string;
    truth_state?: string | null;
    generation_warning?: string | null;
    generation_allowed?: boolean;
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

type RequirementTruthAction = 'confirm' | 'reject' | 'mark-stale';
type TruthActionStyle = { bg: string; color: string; border: string };

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

const truthStateColors: Record<string, { bg: string; color: string }> = {
    candidate_requirement: { bg: 'rgba(156, 163, 175, 0.1)', color: 'var(--text-tertiary)' },
    observed_behavior: { bg: 'var(--primary-glow)', color: 'var(--primary)' },
    manual_requirement: { bg: 'rgba(192, 132, 252, 0.12)', color: 'var(--accent)' },
    confirmed_requirement: { bg: 'var(--success-muted)', color: 'var(--success)' },
    rejected_requirement: { bg: 'var(--danger-muted)', color: 'var(--danger)' },
    stale_requirement: { bg: 'var(--warning-muted)', color: 'var(--warning)' },
};

const truthStateLabels: Record<string, string> = {
    candidate_requirement: 'Candidate',
    observed_behavior: 'Observed',
    manual_requirement: 'Manual',
    confirmed_requirement: 'Confirmed',
    rejected_requirement: 'Rejected',
    stale_requirement: 'Stale',
};

const terminalReviewTruthStates = new Set([
    'confirmed_requirement',
    'rejected_requirement',
    'stale_requirement',
]);

const truthStateMirroredStatuses: Record<string, string> = {
    confirmed_requirement: 'confirmed',
    rejected_requirement: 'rejected',
    stale_requirement: 'stale',
};

const truthActionStyles: Record<RequirementTruthAction, TruthActionStyle> = {
    confirm: {
        bg: 'var(--success-muted)',
        color: 'var(--success)',
        border: 'color-mix(in srgb, var(--success) 45%, transparent)',
    },
    reject: {
        bg: 'var(--danger-muted)',
        color: 'var(--danger)',
        border: 'color-mix(in srgb, var(--danger) 45%, transparent)',
    },
    'mark-stale': {
        bg: 'var(--warning-muted)',
        color: 'var(--warning)',
        border: 'color-mix(in srgb, var(--warning) 45%, transparent)',
    },
};

const getTruthActionButtonStyle = (action: RequirementTruthAction, disabled: boolean): React.CSSProperties => {
    const style = truthActionStyles[action];

    return {
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        gap: '0.25rem',
        height: 32,
        minHeight: 32,
        padding: '0 0.625rem',
        borderRadius: 6,
        border: `1px solid ${disabled ? 'var(--border)' : style.border}`,
        background: disabled ? 'var(--surface-hover)' : style.bg,
        color: disabled ? 'var(--text-secondary)' : style.color,
        fontSize: '0.75rem',
        fontWeight: 600,
        lineHeight: 1,
        whiteSpace: 'nowrap',
        opacity: disabled ? 0.72 : 1,
        cursor: disabled ? 'not-allowed' : 'pointer',
    };
};

const priorityOrder: Record<string, number> = {
    critical: 0,
    high: 1,
    medium: 2,
    low: 3
};

const FILTER_ALL_VALUE = '__all';
const priorityFilterOptions = ['critical', 'high', 'medium', 'low'];
const statusFilterOptions = ['draft', 'approved', 'implemented', 'deprecated'];
const truthStateFilterOptions = [
    'candidate_requirement',
    'observed_behavior',
    'manual_requirement',
    'confirmed_requirement',
    'rejected_requirement',
    'stale_requirement',
];

const formatFilterLabel = (value: string) => {
    return value
        .replace(/_/g, ' ')
        .replace(/\b\w/g, char => char.toUpperCase());
};

export default function RequirementsPage() {
    const { currentProject, isLoading: projectLoading } = useProject();

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
    const [truthStateFilter, setTruthStateFilter] = useState<string>('');

    const [expandedReqs, setExpandedReqs] = useState<Set<number>>(new Set());
    const [editModalOpen, setEditModalOpen] = useState(false);
    const [editingReq, setEditingReq] = useState<Requirement | null>(null);
    const [deleteModalOpen, setDeleteModalOpen] = useState(false);
    const [deletingReq, setDeletingReq] = useState<Requirement | null>(null);
    const [isDeleting, setIsDeleting] = useState(false);
    const [isSaving, setIsSaving] = useState(false);
    const [reviewingTruthReq, setReviewingTruthReq] = useState<Requirement | null>(null);
    const [truthAction, setTruthAction] = useState<RequirementTruthAction | null>(null);
    const [truthComment, setTruthComment] = useState('');
    const [truthActionLoading, setTruthActionLoading] = useState<string | null>(null);

    const [createModalOpen, setCreateModalOpen] = useState(false);
    const [newReq, setNewReq] = useState({
        title: '',
        description: '',
        category: 'other',
        priority: 'medium',
        acceptance_criteria: ['']
    });
    const [isCreating, setIsCreating] = useState(false);

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
    const [selectedReqForSpec, setSelectedReqForSpec] = useState<Requirement | null>(null);
    const [createSpecDropdownOpen, setCreateSpecDropdownOpen] = useState<number | null>(null);
    const [specPreflightLoadingId, setSpecPreflightLoadingId] = useState<number | null>(null);
    const [specPreflightWarning, setSpecPreflightWarning] = useState<{
        requirement: Requirement;
        truthState: string;
        warning: string;
        generationAllowed: boolean;
    } | null>(null);

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
        if (truthStateFilter) params.append('truth_state', truthStateFilter);
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
    }, [currentProject?.id, projectLoading, categoryFilter, priorityFilter, statusFilter, truthStateFilter, searchTerm]);

    // Load more handler
    const loadMore = () => {
        if (isLoadingMore || !hasMore) return;
        fetchData(requirements.length, true);
    };

    useEffect(() => {
        // Reset to first page when filters change
        setLoading(true);
        fetchData(0, false);
    }, [fetchData]);

    // Requirements are now filtered server-side, so we just use them directly
    // Note: All filtering is done via API query params for pagination support
    const filteredRequirements = requirements;

    const toggleExpanded = (id: number) => {
        const next = new Set(expandedReqs);
        if (next.has(id)) next.delete(id);
        else next.add(id);
        setExpandedReqs(next);
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

    const openTruthReview = (req: Requirement, action: RequirementTruthAction) => {
        if (action === 'confirm') {
            applyTruthDecision(req, action);
            return;
        }
        setReviewingTruthReq(req);
        setTruthAction(action);
        setTruthComment('');
    };

    const closeTruthReview = (force = false) => {
        if (truthActionLoading && !force) return;
        setReviewingTruthReq(null);
        setTruthAction(null);
        setTruthComment('');
    };

    const applyTruthDecision = async (req: Requirement, action: RequirementTruthAction, comment?: string) => {
        const trimmedComment = comment?.trim() || '';
        if ((action === 'reject' || action === 'mark-stale') && !trimmedComment) return;

        const projectParam = currentProject?.id
            ? `?project_id=${encodeURIComponent(currentProject.id)}`
            : '';
        const actionKey = `${req.id}:${action}`;

        setTruthActionLoading(actionKey);
        try {
            const res = await fetch(`${API_BASE}/requirements/${req.id}/${action}${projectParam}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: action === 'confirm' ? undefined : JSON.stringify({ comment: trimmedComment })
            });

            if (res.ok) {
                closeTruthReview(true);
                await fetchData(0, false);
            } else {
                const err = await res.json().catch(() => ({}));
                alert(`Failed to update truth state: ${err.detail || res.statusText}`);
            }
        } catch (e) {
            console.error('Failed to update requirement truth state:', e);
            alert('Failed to update truth state');
        } finally {
            setTruthActionLoading(null);
        }
    };

    const submitTruthReview = async () => {
        if (!reviewingTruthReq || !truthAction) return;
        await applyTruthDecision(reviewingTruthReq, truthAction, truthComment);
    };

    // Original createRequirement is replaced by createRequirementWithCheck
    const createRequirement = () => createRequirementWithCheck(false);

    const getGenerationWarning = (requirement: Requirement, status?: SpecStatusResponse | null) => {
        const truthState = status?.truth_state || requirement.truth_state || 'candidate_requirement';
        const truthLabel = truthStateLabels[truthState] || truthState.replace(/_/g, ' ');
        const warning = status?.generation_warning || requirement.uncertainty_reason;

        if (warning) return { truthState, warning };
        if (truthState !== 'confirmed_requirement') {
            return {
                truthState,
                warning: `This requirement is ${truthLabel.toLowerCase()}, not confirmed. Generated specs may encode assumptions that have not been approved.`
            };
        }

        return null;
    };

    // Generate Spec functions
    const openGenerateSpecModal = (req: Requirement) => {
        setSelectedReqForSpec(req);
        setGenerateSpecModalOpen(true);
        setCreateSpecDropdownOpen(null);
    };

    const openGenerateSpecWithPreflight = async (requirement: Requirement) => {
        const projectParam = currentProject?.id
            ? `?project_id=${encodeURIComponent(currentProject.id)}`
            : '';

        setSpecPreflightLoadingId(requirement.id);
        try {
            const res = await fetch(`${API_BASE}/requirements/${requirement.id}/spec-status${projectParam}`);
            const data: SpecStatusResponse | null = res.ok ? await res.json() : null;
            const warning = getGenerationWarning(requirement, data);

            if (warning) {
                setSpecPreflightWarning({
                    requirement,
                    truthState: warning.truthState,
                    warning: warning.warning,
                    generationAllowed: data?.generation_allowed !== false
                });
                setCreateSpecDropdownOpen(null);
                return;
            }

            openGenerateSpecModal(requirement);
        } catch (err) {
            console.error('Failed to check requirement spec status:', err);
            const warning = getGenerationWarning(requirement, null);

            if (warning) {
                setSpecPreflightWarning({
                    requirement,
                    truthState: warning.truthState,
                    warning: warning.warning,
                    generationAllowed: true
                });
                setCreateSpecDropdownOpen(null);
                return;
            }

            openGenerateSpecModal(requirement);
        } finally {
            setSpecPreflightLoadingId(null);
        }
    };

    const continueGenerateSpecAfterWarning = () => {
        if (!specPreflightWarning) return;
        openGenerateSpecModal(specPreflightWarning.requirement);
        setSpecPreflightWarning(null);
    };

    // Create Spec Dropdown Component
    const CreateSpecDropdown = ({ req, variant = 'inline' }: { req: Requirement; variant?: 'inline' | 'button' }) => {
        const reqId = req.id;
        const isOpen = createSpecDropdownOpen === reqId;
        const reqCode = req.req_code;

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
                                    void openGenerateSpecWithPreflight(req);
                                }}
                                disabled={specPreflightLoadingId === reqId}
                                style={{
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: '0.75rem',
                                    width: '100%',
                                    padding: '0.75rem 1rem',
                                    border: 'none',
                                    textAlign: 'left',
                                    cursor: specPreflightLoadingId === reqId ? 'wait' : 'pointer',
                                    color: 'var(--text)',
                                    fontSize: '0.9rem',
                                    borderBottom: '1px solid var(--border)',
                                    opacity: specPreflightLoadingId === reqId ? 0.7 : 1
                                }}
                            >
                                {specPreflightLoadingId === reqId ? (
                                    <Loader2 size={16} color="var(--primary)" className="spinning" />
                                ) : (
                                    <Sparkles size={16} color="var(--primary)" />
                                )}
                                <div>
                                    <div style={{ fontWeight: 500 }}>{specPreflightLoadingId === reqId ? 'Checking...' : 'AI Generate'}</div>
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

    const checkForDuplicates = async (title: string, description: string): Promise<boolean> => {
        if (!title.trim()) return false;

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
                    return true;
                } else {
                    setDuplicateWarning(null);
                    return false;
                }
            }
        } catch (e) {
            console.error('Failed to check duplicates:', e);
        } finally {
            setCheckingDuplicate(false);
        }

        return false;
    };

    const createRequirementWithCheck = async (forceCreate: boolean = false) => {
        if (!newReq.title) return;

        // If not forcing create and we haven't checked yet, check first
        if (!forceCreate && !duplicateWarning) {
            const duplicateFound = await checkForDuplicates(newReq.title, newReq.description);
            // If warning shows up, user will need to confirm
            if (duplicateFound) return;
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
        return [...new Set([...requirements.map(r => r.category), categoryFilter].filter(Boolean))].sort();
    }, [requirements, categoryFilter]);

    const activeFilterCount = [
        categoryFilter,
        priorityFilter,
        statusFilter,
        truthStateFilter,
    ].filter(Boolean).length;
    const hasActiveFilters = Boolean(searchTerm || activeFilterCount);
    const priorityAllCount = typeof stats?.total === 'number' ? stats.total : null;
    const getPriorityCount = (priority: string) => {
        const count = stats?.by_priority?.[priority];
        return typeof count === 'number' ? count : null;
    };
    const clearAllFilters = () => {
        setSearchTerm('');
        setCategoryFilter('');
        setPriorityFilter('');
        setStatusFilter('');
        setTruthStateFilter('');
    };
    const activeFilterChips = [
        categoryFilter
            ? { key: 'category', label: `Category: ${categoryFilter}`, onRemove: () => setCategoryFilter('') }
            : null,
        priorityFilter
            ? { key: 'priority', label: `Priority: ${formatFilterLabel(priorityFilter)}`, onRemove: () => setPriorityFilter('') }
            : null,
        statusFilter
            ? { key: 'status', label: `Status: ${formatFilterLabel(statusFilter)}`, onRemove: () => setStatusFilter('') }
            : null,
        truthStateFilter
            ? { key: 'truth-state', label: `Truth: ${truthStateLabels[truthStateFilter] || formatFilterLabel(truthStateFilter)}`, onRemove: () => setTruthStateFilter('') }
            : null,
    ].filter((chip): chip is { key: string; label: string; onRemove: () => void } => Boolean(chip));

    // Loading state
    if (loading || projectLoading) {
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
                subtitle="Manage requirements."
                icon={<CheckSquare size={22} />}
                breadcrumb={<WorkflowBreadcrumb />}
                actions={
                    <div style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap' }}>
                        <Link
                            className="btn btn-secondary"
                            href="/rtm"
                            style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', textDecoration: 'none' }}
                        >
                            <GitBranch size={16} />
                            Open RTM
                        </Link>
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
                }
            />

            <div className="animate-in stagger-2" style={{ marginBottom: '1.5rem' }}>
                <div className="card" style={{ padding: '1rem 1.25rem', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '1rem', flexWrap: 'wrap' }}>
                    <div>
                        <div style={{ fontWeight: 600, marginBottom: '0.25rem' }}>Traceability moved to RTM</div>
                        <div style={{ fontSize: '0.9rem', color: 'var(--text-secondary)' }}>
                            Track coverage, gaps, snapshots, exports, and manual links in the dedicated RTM workspace.
                        </div>
                    </div>
                    <Link className="btn btn-secondary" href="/rtm" style={{ display: 'inline-flex', alignItems: 'center', gap: '0.5rem', textDecoration: 'none' }}>
                        <GitBranch size={16} />
                        Open RTM
                    </Link>
                </div>
            </div>

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
                    <div className="requirements-filter-shell">
                        <div className="requirements-filter-toolbar">
                            <div className="requirements-search input-group">
                                <div className="input-icon">
                                    <Search size={18} />
                                </div>
                                <Input
                                    type="text"
                                    aria-label="Search requirements"
                                    className="has-icon"
                                    placeholder="Search requirements..."
                                    value={searchTerm}
                                    onChange={e => setSearchTerm(e.target.value)}
                                    style={{ width: '100%', paddingLeft: '2.5rem' }}
                                />
                            </div>

                            <div className="requirements-priority-segment" role="group" aria-label="Filter requirements by priority">
                                <button
                                    type="button"
                                    aria-label={`Show all priorities${priorityAllCount !== null ? `, ${priorityAllCount} requirements` : ''}`}
                                    aria-pressed={!priorityFilter}
                                    className="requirements-priority-button"
                                    data-active={!priorityFilter}
                                    onClick={() => setPriorityFilter('')}
                                >
                                    <span>All</span>
                                    {priorityAllCount !== null && <span className="requirements-priority-count">{priorityAllCount}</span>}
                                </button>
                                {priorityFilterOptions.map(priority => {
                                    const count = getPriorityCount(priority);
                                    const label = formatFilterLabel(priority);

                                    return (
                                        <button
                                            key={priority}
                                            type="button"
                                            aria-label={`Filter by ${priority} priority${count !== null ? `, ${count} requirements` : ''}`}
                                            aria-pressed={priorityFilter === priority}
                                            className="requirements-priority-button"
                                            data-active={priorityFilter === priority}
                                            onClick={() => setPriorityFilter(priorityFilter === priority ? '' : priority)}
                                        >
                                            <span>{label}</span>
                                            {count !== null && <span className="requirements-priority-count">{count}</span>}
                                        </button>
                                    );
                                })}
                            </div>

                            <DropdownMenu>
                                <DropdownMenuTrigger asChild>
                                    <Button
                                        variant="secondary"
                                        aria-label="Open requirement filters"
                                        className="requirements-filter-trigger"
                                    >
                                        <SlidersHorizontal size={16} />
                                        Filters
                                        {activeFilterCount > 0 && (
                                            <Badge
                                                variant="secondary"
                                                style={{
                                                    padding: '0 0.375rem',
                                                    minWidth: 20,
                                                    height: 20,
                                                    justifyContent: 'center',
                                                    background: 'var(--surface-active)',
                                                    color: 'var(--text)',
                                                    border: '1px solid var(--border-bright)'
                                                }}
                                            >
                                                {activeFilterCount}
                                            </Badge>
                                        )}
                                    </Button>
                                </DropdownMenuTrigger>
                                <DropdownMenuContent
                                    align="end"
                                    sideOffset={8}
                                    className="requirements-filter-menu"
                                    style={{
                                        width: 300,
                                        maxWidth: 'calc(100vw - 2rem)',
                                        padding: '0.75rem',
                                        zIndex: 1100,
                                        background: 'var(--surface)',
                                        borderColor: 'var(--border)',
                                        borderRadius: 'var(--radius)',
                                        color: 'var(--text)',
                                        boxShadow: 'var(--shadow-card)'
                                    }}
                                >
                                    <DropdownMenuLabel style={{ padding: '0 0 0.625rem', color: 'var(--text)' }}>
                                        Filters
                                    </DropdownMenuLabel>

                                    <div className="requirements-dropdown-fields">
                                        <div className="requirements-dropdown-field requirements-mobile-priority">
                                            <label htmlFor="requirements-priority-filter">Priority</label>
                                            <Select
                                                value={priorityFilter || FILTER_ALL_VALUE}
                                                onValueChange={value => setPriorityFilter(value === FILTER_ALL_VALUE ? '' : value)}
                                            >
                                                <SelectTrigger id="requirements-priority-filter" aria-label="Filter by priority">
                                                    <SelectValue placeholder="All Priorities" />
                                                </SelectTrigger>
                                                <SelectContent className="requirements-filter-select-content">
                                                    <SelectItem value={FILTER_ALL_VALUE}>All Priorities</SelectItem>
                                                    {priorityFilterOptions.map(priority => (
                                                        <SelectItem key={priority} value={priority}>
                                                            {formatFilterLabel(priority)}
                                                        </SelectItem>
                                                    ))}
                                                </SelectContent>
                                            </Select>
                                        </div>

                                        <div className="requirements-dropdown-field">
                                            <label htmlFor="requirements-category-filter">Category</label>
                                            <Select
                                                value={categoryFilter || FILTER_ALL_VALUE}
                                                onValueChange={value => setCategoryFilter(value === FILTER_ALL_VALUE ? '' : value)}
                                            >
                                                <SelectTrigger id="requirements-category-filter" aria-label="Filter by category">
                                                    <SelectValue placeholder="All Categories" />
                                                </SelectTrigger>
                                                <SelectContent className="requirements-filter-select-content">
                                                    <SelectItem value={FILTER_ALL_VALUE}>All Categories</SelectItem>
                                                    {categories.map(cat => (
                                                        <SelectItem key={cat} value={cat}>{cat}</SelectItem>
                                                    ))}
                                                </SelectContent>
                                            </Select>
                                        </div>

                                        <div className="requirements-dropdown-field">
                                            <label htmlFor="requirements-status-filter">Status</label>
                                            <Select
                                                value={statusFilter || FILTER_ALL_VALUE}
                                                onValueChange={value => setStatusFilter(value === FILTER_ALL_VALUE ? '' : value)}
                                            >
                                                <SelectTrigger id="requirements-status-filter" aria-label="Filter by status">
                                                    <SelectValue placeholder="All Statuses" />
                                                </SelectTrigger>
                                                <SelectContent className="requirements-filter-select-content">
                                                    <SelectItem value={FILTER_ALL_VALUE}>All Statuses</SelectItem>
                                                    {statusFilterOptions.map(status => (
                                                        <SelectItem key={status} value={status}>
                                                            {formatFilterLabel(status)}
                                                        </SelectItem>
                                                    ))}
                                                </SelectContent>
                                            </Select>
                                        </div>

                                        <div className="requirements-dropdown-field">
                                            <label htmlFor="requirements-truth-state-filter">Truth State</label>
                                            <Select
                                                value={truthStateFilter || FILTER_ALL_VALUE}
                                                onValueChange={value => setTruthStateFilter(value === FILTER_ALL_VALUE ? '' : value)}
                                            >
                                                <SelectTrigger id="requirements-truth-state-filter" aria-label="Filter by truth state">
                                                    <SelectValue placeholder="All Truth States" />
                                                </SelectTrigger>
                                                <SelectContent className="requirements-filter-select-content">
                                                    <SelectItem value={FILTER_ALL_VALUE}>All Truth States</SelectItem>
                                                    {truthStateFilterOptions.map(truthState => (
                                                        <SelectItem key={truthState} value={truthState}>
                                                            {truthStateLabels[truthState] || formatFilterLabel(truthState)}
                                                        </SelectItem>
                                                    ))}
                                                </SelectContent>
                                            </Select>
                                        </div>
                                    </div>

                                    {hasActiveFilters && (
                                        <>
                                            <DropdownMenuSeparator style={{ margin: '0.75rem 0' }} />
                                            <Button
                                                type="button"
                                                variant="ghost"
                                                size="sm"
                                                aria-label="Clear all requirement filters"
                                                onClick={clearAllFilters}
                                                style={{ width: '100%', justifyContent: 'center' }}
                                            >
                                                <X size={14} />
                                                Clear filters
                                            </Button>
                                        </>
                                    )}
                                </DropdownMenuContent>
                            </DropdownMenu>

                            {hasActiveFilters && (
                                <Button
                                    type="button"
                                    variant="ghost"
                                    size="sm"
                                    className="requirements-clear-toolbar"
                                    aria-label="Clear all requirement filters"
                                    onClick={clearAllFilters}
                                >
                                    <X size={14} />
                                    Clear filters
                                </Button>
                            )}
                        </div>

                        {activeFilterChips.length > 0 && (
                            <div className="requirements-filter-chips" aria-label="Active filters">
                                {activeFilterChips.map(chip => (
                                    <Badge key={chip.key} variant="secondary" className="requirements-filter-chip">
                                        <span>{chip.label}</span>
                                        <button
                                            type="button"
                                            aria-label={`Remove ${chip.label} filter`}
                                            onClick={chip.onRemove}
                                        >
                                            <X size={12} />
                                        </button>
                                    </Badge>
                                ))}
                            </div>
                        )}
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
                                const truthState = req.truth_state || 'candidate_requirement';
                                const truthStyle = truthStateColors[truthState] || truthStateColors.candidate_requirement;
                                const truthLabel = truthStateLabels[truthState] || truthState.replace(/_/g, ' ');
                                const confidence = typeof req.confidence === 'number' ? `${Math.round(req.confidence * 100)}%` : null;
                                const isTerminalReviewState = terminalReviewTruthStates.has(truthState);
                                const mirroredStatus = truthStateMirroredStatuses[truthState];
                                const showStatusBadge = !mirroredStatus || req.status.toLowerCase() !== mirroredStatus;
                                const isAnyTruthActionLoading = truthActionLoading?.startsWith(`${req.id}:`) ?? false;
                                const truthActionsDisabled = isTerminalReviewState || isAnyTruthActionLoading;
                                const confirmDisabled = truthActionsDisabled;
                                const rejectDisabled = truthActionsDisabled;
                                const staleDisabled = truthActionsDisabled;
                                return (
                                    <div key={req.id} style={{ borderBottom: '1px solid var(--border)' }}>
                                        <div
                                            style={{
                                                padding: '1rem 1.25rem',
                                                display: 'flex',
                                                alignItems: 'center',
                                                flexWrap: 'wrap',
                                                gap: '1rem',
                                                cursor: 'pointer',
                                                background: isExpanded ? 'var(--surface-hover)' : 'transparent'
                                            }}
                                            onClick={() => toggleExpanded(req.id)}
                                        >
                                            <span style={{ color: 'var(--text-secondary)' }}>
                                                {isExpanded ? <ChevronDown size={18} /> : <ChevronRight size={18} />}
                                            </span>

                                            <div style={{ flex: 1, minWidth: 180 }}>
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

                                            {showStatusBadge && (
                                                <span style={{
                                                    padding: '0.25rem 0.625rem',
                                                    borderRadius: '4px',
                                                    fontSize: '0.75rem',
                                                    fontWeight: 500,
                                                    ...statusColors[req.status]
                                                }}>
                                                    {req.status}
                                                </span>
                                            )}

                                            <span
                                                title={req.uncertainty_reason || undefined}
                                                style={{
                                                    padding: '0.25rem 0.625rem',
                                                    borderRadius: '4px',
                                                    fontSize: '0.75rem',
                                                    fontWeight: 600,
                                                    textTransform: 'capitalize',
                                                    ...truthStyle
                                                }}
                                            >
                                                {truthLabel}
                                            </span>

                                            <div style={{ display: 'flex', gap: '0.375rem', alignItems: 'center', justifyContent: 'flex-end', flexWrap: 'wrap' }} onClick={e => e.stopPropagation()}>
                                                <button
                                                    className="btn btn-sm"
                                                    onClick={() => openTruthReview(req, 'confirm')}
                                                    disabled={confirmDisabled}
                                                    style={getTruthActionButtonStyle('confirm', confirmDisabled)}
                                                >
                                                    {truthActionLoading === `${req.id}:confirm` ? <Loader2 size={13} className="spinning" /> : <CheckCircle size={13} />}
                                                    Confirm
                                                </button>
                                                <button
                                                    className="btn btn-sm"
                                                    onClick={() => openTruthReview(req, 'reject')}
                                                    disabled={rejectDisabled}
                                                    style={getTruthActionButtonStyle('reject', rejectDisabled)}
                                                >
                                                    <X size={13} />
                                                    Reject
                                                </button>
                                                <button
                                                    className="btn btn-sm"
                                                    onClick={() => openTruthReview(req, 'mark-stale')}
                                                    disabled={staleDisabled}
                                                    style={getTruthActionButtonStyle('mark-stale', staleDisabled)}
                                                >
                                                    <AlertTriangle size={13} />
                                                    Stale
                                                </button>
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

                                                {(req.source_type || confidence || req.uncertainty_reason || req.confirmed_at || req.rejected_at) && (
                                                    <div style={{ marginTop: '1rem', display: 'flex', flexWrap: 'wrap', gap: '0.75rem', fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                                                        {req.source_type && (
                                                            <span>Source: <strong style={{ color: 'var(--text)' }}>{req.source_type}</strong></span>
                                                        )}
                                                        {confidence && (
                                                            <span>Confidence: <strong style={{ color: 'var(--text)' }}>{confidence}</strong></span>
                                                        )}
                                                        {req.uncertainty_reason && (
                                                            <span>Uncertainty: <strong style={{ color: 'var(--text)' }}>{req.uncertainty_reason}</strong></span>
                                                        )}
                                                        {req.confirmed_at && (
                                                            <span>Confirmed: <strong style={{ color: 'var(--text)' }}>{new Date(req.confirmed_at).toLocaleString()}</strong>{req.confirmed_by ? ` by ${req.confirmed_by}` : ''}</span>
                                                        )}
                                                        {req.rejected_at && (
                                                            <span>Rejected: <strong style={{ color: 'var(--text)' }}>{new Date(req.rejected_at).toLocaleString()}</strong>{req.rejected_by ? ` by ${req.rejected_by}` : ''}</span>
                                                        )}
                                                    </div>
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

            {/* Truth Review Modal */}
            {reviewingTruthReq && truthAction && (
                <div className="modal-overlay" onClick={() => closeTruthReview()}>
                    <div className="modal-content" onClick={e => e.stopPropagation()} style={{ width: '480px', maxHeight: '80vh', overflow: 'auto' }}>
                        <h2 style={{ marginBottom: '1rem', display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                            {truthAction === 'reject' ? (
                                <X size={24} color="var(--danger)" />
                            ) : (
                                <AlertTriangle size={24} color="var(--warning)" />
                            )}
                            {truthAction === 'reject' ? 'Reject Requirement' : 'Mark Requirement Stale'}
                        </h2>

                        <div style={{ padding: '0.75rem', background: 'var(--surface-hover)', borderRadius: '6px', marginBottom: '1rem' }}>
                            <strong>{reviewingTruthReq.req_code}</strong>: {reviewingTruthReq.title}
                        </div>

                        <label style={{ display: 'block', marginBottom: '0.375rem', fontWeight: 500 }}>
                            Review comment <span style={{ color: 'var(--danger)' }}>*</span>
                        </label>
                        <textarea
                            className="input"
                            value={truthComment}
                            onChange={e => setTruthComment(e.target.value)}
                            placeholder={truthAction === 'reject' ? 'Why is this requirement not true?' : 'What changed or needs re-validation?'}
                            rows={3}
                            disabled={Boolean(truthActionLoading)}
                            style={{ width: '100%', resize: 'vertical', marginBottom: '1.5rem' }}
                        />

                        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '1rem' }}>
                            <button className="btn btn-secondary" onClick={() => closeTruthReview()} disabled={Boolean(truthActionLoading)}>
                                Cancel
                            </button>
                            <button
                                className="btn"
                                onClick={submitTruthReview}
                                disabled={Boolean(truthActionLoading) || !truthComment.trim()}
                                style={{
                                    background: truthAction === 'reject' ? 'var(--danger)' : 'var(--warning)',
                                    color: 'white',
                                    display: 'inline-flex',
                                    alignItems: 'center',
                                    gap: '0.5rem'
                                }}
                            >
                                {truthActionLoading ? <Loader2 size={16} className="spinning" /> : null}
                                {truthAction === 'reject' ? 'Reject' : 'Mark Stale'}
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {/* Spec Generation Truth Warning */}
            {specPreflightWarning && (
                <div
                    className="modal-overlay"
                    onClick={(e) => {
                        if (e.target === e.currentTarget) {
                            setSpecPreflightWarning(null);
                        }
                    }}
                >
                    <div
                        className="modal-content"
                        onClick={(e) => e.stopPropagation()}
                        style={{ width: '520px', maxWidth: '95vw' }}
                    >
                        <div style={{ display: 'flex', alignItems: 'flex-start', gap: '0.875rem', marginBottom: '1rem' }}>
                            <AlertTriangle size={24} color="var(--warning)" style={{ flexShrink: 0, marginTop: '0.125rem' }} />
                            <div style={{ flex: 1 }}>
                                <h2 style={{ marginBottom: '0.375rem' }}>Generate from unconfirmed requirement?</h2>
                                <div style={{ fontSize: '0.9rem', color: 'var(--text-secondary)' }}>
                                    Review the requirement truth state before creating a test spec.
                                </div>
                            </div>
                            <button
                                onClick={() => setSpecPreflightWarning(null)}
                                style={{
                                    background: 'none',
                                    border: 'none',
                                    cursor: 'pointer',
                                    padding: '0.25rem',
                                    color: 'var(--text-secondary)'
                                }}
                            >
                                <X size={20} />
                            </button>
                        </div>

                        <div style={{
                            padding: '1rem',
                            background: 'rgba(245, 158, 11, 0.1)',
                            border: '1px solid rgba(245, 158, 11, 0.3)',
                            borderRadius: '8px',
                            display: 'flex',
                            alignItems: 'flex-start',
                            gap: '0.75rem',
                            marginBottom: '1rem'
                        }}>
                            <AlertCircle size={20} color="#f59e0b" style={{ flexShrink: 0, marginTop: '2px' }} />
                            <div>
                                <div style={{ fontWeight: 600, marginBottom: '0.25rem' }}>
                                    Non-confirmed requirement
                                </div>
                                <div style={{ fontSize: '0.9rem', color: 'var(--text-secondary)', lineHeight: 1.5 }}>
                                    {specPreflightWarning.warning}
                                </div>
                            </div>
                        </div>

                        <div style={{ marginBottom: '1.25rem' }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.5rem' }}>
                                <span style={{ fontWeight: 600, color: 'var(--primary)', fontSize: '0.85rem' }}>
                                    {specPreflightWarning.requirement.req_code}
                                </span>
                                <span style={{ fontWeight: 500 }}>{specPreflightWarning.requirement.title}</span>
                            </div>
                            <span style={{
                                display: 'inline-flex',
                                padding: '0.25rem 0.625rem',
                                borderRadius: '4px',
                                fontSize: '0.75rem',
                                fontWeight: 600,
                                textTransform: 'capitalize',
                                ...(truthStateColors[specPreflightWarning.truthState] || truthStateColors.candidate_requirement)
                            }}>
                                {truthStateLabels[specPreflightWarning.truthState] || specPreflightWarning.truthState.replace(/_/g, ' ')}
                            </span>
                            {!specPreflightWarning.generationAllowed && (
                                <p style={{ marginTop: '0.75rem', fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
                                    The status response marked generation as not allowed, but the action remains available for this workflow.
                                </p>
                            )}
                        </div>

                        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.75rem', paddingTop: '1rem', borderTop: '1px solid var(--border)' }}>
                            <button
                                className="btn btn-secondary"
                                onClick={() => setSpecPreflightWarning(null)}
                            >
                                Cancel
                            </button>
                            <button
                                className="btn btn-primary"
                                onClick={continueGenerateSpecAfterWarning}
                                style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}
                            >
                                <Sparkles size={16} />
                                Continue to Generate
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
                        req_code: selectedReqForSpec.req_code,
                        title: selectedReqForSpec.title,
                        description: selectedReqForSpec.description,
                        category: selectedReqForSpec.category,
                        priority: selectedReqForSpec.priority,
                        acceptance_criteria: selectedReqForSpec.acceptance_criteria,
                        source_session_id: selectedReqForSpec.source_session_id
                    }}
                    onClose={() => {
                        setGenerateSpecModalOpen(false);
                        setSelectedReqForSpec(null);
                    }}
                />
            )}

            <style jsx>{`
                :global(.requirements-filter-shell) {
                    display: flex;
                    flex-direction: column;
                    gap: 0.625rem;
                    margin-bottom: 1rem;
                }
                :global(.requirements-filter-toolbar) {
                    display: flex;
                    align-items: center;
                    gap: 0.75rem;
                    width: 100%;
                    min-width: 0;
                }
                :global(.requirements-search) {
                    flex: 1 1 320px;
                    min-width: 220px;
                    position: relative;
                }
                :global(.requirements-priority-segment) {
                    display: inline-flex;
                    align-items: center;
                    min-height: 40px;
                    padding: 3px;
                    border: 1px solid var(--border);
                    border-radius: var(--radius);
                    background: var(--surface);
                    flex: 0 0 auto;
                }
                :global(.requirements-priority-button) {
                    display: inline-flex;
                    align-items: center;
                    justify-content: center;
                    gap: 0.375rem;
                    min-height: 32px;
                    padding: 0 0.625rem;
                    border: 0;
                    border-radius: 6px;
                    background: transparent;
                    color: var(--text-secondary);
                    font-size: 0.8rem;
                    font-weight: 600;
                    line-height: 1;
                    cursor: pointer;
                    transition: all 0.16s var(--ease-smooth);
                    white-space: nowrap;
                }
                :global(.requirements-priority-button:hover) {
                    color: var(--text);
                    background: var(--surface-hover);
                }
                :global(.requirements-priority-button:focus-visible) {
                    outline: 2px solid var(--primary);
                    outline-offset: 2px;
                }
                :global(.requirements-priority-button[data-active="true"]) {
                    background: var(--surface-active);
                    color: var(--text);
                    box-shadow: inset 0 0 0 1px var(--border-bright);
                }
                :global(.requirements-priority-count) {
                    display: inline-flex;
                    align-items: center;
                    justify-content: center;
                    min-width: 1.25rem;
                    height: 1.25rem;
                    padding: 0 0.35rem;
                    border-radius: 999px;
                    background: var(--background-raised);
                    color: inherit;
                    border: 1px solid transparent;
                    font-size: 0.72rem;
                    font-weight: 700;
                }
                :global(.requirements-priority-button[data-active="true"] .requirements-priority-count) {
                    background: var(--background-raised);
                    border-color: var(--border-bright);
                    color: var(--text);
                }
                :global(.requirements-filter-trigger) {
                    flex: 0 0 auto;
                    min-height: 40px;
                }
                :global(.requirements-filter-menu) {
                    z-index: 1100 !important;
                }
                :global(.requirements-filter-select-content) {
                    z-index: 1200 !important;
                }
                :global(.requirements-dropdown-fields) {
                    display: flex;
                    flex-direction: column;
                    gap: 0.75rem;
                }
                :global(.requirements-dropdown-field) {
                    display: flex;
                    flex-direction: column;
                    gap: 0.375rem;
                }
                :global(.requirements-dropdown-field label) {
                    color: var(--text-secondary);
                    font-size: 0.75rem;
                    font-weight: 600;
                }
                :global(.requirements-mobile-priority) {
                    display: none;
                }
                :global(.requirements-clear-toolbar) {
                    flex: 0 0 auto;
                    color: var(--text-secondary);
                    min-height: 36px;
                    padding: 0 0.75rem;
                }
                :global(.requirements-filter-chips) {
                    display: flex;
                    align-items: center;
                    gap: 0.5rem;
                    flex-wrap: wrap;
                }
                :global(.requirements-filter-chip) {
                    gap: 0.375rem;
                    border-radius: 999px;
                    background: var(--surface-hover) !important;
                    color: var(--text-secondary) !important;
                    border: 1px solid var(--border) !important;
                    padding-right: 0.25rem;
                }
                :global(.requirements-filter-chip button) {
                    display: inline-flex;
                    align-items: center;
                    justify-content: center;
                    width: 1.25rem;
                    height: 1.25rem;
                    padding: 0;
                    border: 0;
                    border-radius: 999px;
                    background: transparent;
                    color: var(--text-tertiary);
                    cursor: pointer;
                }
                :global(.requirements-filter-chip button:hover) {
                    background: var(--background-raised);
                    color: var(--text);
                }
                :global(.requirements-filter-chip button:focus-visible) {
                    outline: 2px solid var(--primary);
                    outline-offset: 1px;
                }
                @media (max-width: 900px) {
                    :global(.requirements-priority-segment) {
                        display: none;
                    }
                    :global(.requirements-mobile-priority) {
                        display: flex;
                    }
                }
                @media (max-width: 640px) {
                    :global(.requirements-filter-toolbar) {
                        gap: 0.5rem;
                        flex-wrap: wrap;
                    }
                    :global(.requirements-search) {
                        flex: 1 1 calc(100% - 9rem);
                        min-width: 0;
                    }
                    :global(.requirements-filter-trigger) {
                        min-width: 7.25rem;
                    }
                    :global(.requirements-clear-toolbar) {
                        order: 3;
                        width: 100%;
                    }
                }
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
