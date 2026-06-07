'use client';

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Link from 'next/link';
import {
    AlertTriangle,
    Camera,
    CheckCircle,
    ChevronDown,
    ChevronRight,
    Circle,
    Download,
    FileText,
    GitBranch,
    Link2,
    Loader2,
    RefreshCw,
    Search,
    Sparkles,
    Unlink,
    X,
} from 'lucide-react';
import { Area, AreaChart, CartesianGrid, Cell, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { toast } from 'sonner';
import GenerateSpecModal from '@/components/GenerateSpecModal';
import { useProject } from '@/contexts/ProjectContext';
import { API_BASE } from '@/lib/api';
import { WorkflowBreadcrumb } from '@/components/workflow/WorkflowBreadcrumb';
import { PageLayout } from '@/components/ui/page-layout';
import { PageHeader } from '@/components/ui/page-header';
import { EmptyState } from '@/components/ui/empty-state';
import { DashboardPageSkeleton } from '@/components/ui/page-skeleton';

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
        test_name?: string;
        description?: string;
        steps?: string[];
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
    data: {
        requirements?: Array<{
            code: string;
            title: string;
            coverage_status: string;
        }>;
    } | null;
}

interface SpecListItem {
    name: string;
    path?: string;
}

interface RequirementForSpec {
    id: number;
    req_code: string;
    title: string;
    description: string | null;
    category: string;
    priority: string;
    acceptance_criteria: string[];
    source_session_id: string | null;
}

const PAGE_SIZE = 50;

const coverageColors: Record<string, string> = {
    covered: 'var(--success)',
    partial: 'var(--warning)',
    uncovered: 'var(--danger)',
    suggested: 'var(--accent)',
};

const priorityStyles: Record<string, { bg: string; color: string }> = {
    critical: { bg: 'var(--danger-muted)', color: 'var(--danger)' },
    high: { bg: 'var(--warning-muted)', color: 'var(--warning)' },
    medium: { bg: 'var(--primary-glow)', color: 'var(--primary)' },
    low: { bg: 'rgba(156, 163, 175, 0.1)', color: 'var(--text-tertiary)' },
};

const rtmCategories = ['accessibility', 'authentication', 'data_display', 'error_handling', 'forms', 'navigation', 'other', 'performance', 'security'];
const rtmCoverageFilters = ['all', 'covered', 'partial', 'uncovered'] as const;

function projectQuery(projectId?: string) {
    return projectId ? `?project_id=${encodeURIComponent(projectId)}` : '';
}

function initialCoverageFilter(): typeof rtmCoverageFilters[number] {
    if (typeof window === 'undefined') return 'all';
    const value = new URLSearchParams(window.location.search).get('coverage_status');
    return rtmCoverageFilters.includes(value as typeof rtmCoverageFilters[number])
        ? value as typeof rtmCoverageFilters[number]
        : 'all';
}

function getCoverageIcon(status: string) {
    if (status === 'covered') return <CheckCircle size={16} color={coverageColors.covered} aria-hidden="true" />;
    if (status === 'partial') return <Circle size={16} color={coverageColors.partial} style={{ fill: coverageColors.partial, fillOpacity: 0.28 }} aria-hidden="true" />;
    return <Circle size={16} color={coverageColors.uncovered} aria-hidden="true" />;
}

function toSpecRequirement(req: RtmRequirement | RtmGap): RequirementForSpec {
    if ('requirement_id' in req) {
        return {
            id: req.requirement_id,
            req_code: req.requirement_code,
            title: req.title,
            description: req.suggested_test.description ?? null,
            category: req.category,
            priority: req.priority,
            acceptance_criteria: req.suggested_test.steps ?? [],
            source_session_id: null,
        };
    }

    return {
        id: req.id,
        req_code: req.code,
        title: req.title,
        description: req.description,
        category: req.category,
        priority: req.priority,
        acceptance_criteria: req.acceptance_criteria,
        source_session_id: null,
    };
}

function specDetailHref(test: { spec_name: string; spec_path: string | null }) {
    let routeName = test.spec_name;
    const path = test.spec_path || '';
    const marker = '/specs/';

    if (path.includes(marker)) {
        routeName = path.slice(path.indexOf(marker) + marker.length);
    } else if (path.startsWith('specs/')) {
        routeName = path.slice('specs/'.length);
    } else if (!routeName.endsWith('.md') && !routeName.includes('/')) {
        routeName = `${routeName}.md`;
    }

    const encoded = routeName
        .split('/')
        .filter(Boolean)
        .map(segment => encodeURIComponent(segment))
        .join('/');

    return `/specs/${encoded}`;
}

export default function RtmPage() {
    const { currentProject, isLoading: projectLoading } = useProject();
    const [requirements, setRequirements] = useState<RtmRequirement[]>([]);
    const [summary, setSummary] = useState<RtmSummary | null>(null);
    const [gaps, setGaps] = useState<RtmGap[]>([]);
    const [trend, setTrend] = useState<TrendPoint[]>([]);
    const [totalCount, setTotalCount] = useState(0);
    const [hasMore, setHasMore] = useState(false);
    const [loading, setLoading] = useState(true);
    const [loadingMore, setLoadingMore] = useState(false);
    const [generating, setGenerating] = useState(false);
    const [generationJobId, setGenerationJobId] = useState<string | null>(null);
    const [generationNotice, setGenerationNotice] = useState<{
        tone: 'success' | 'warning' | 'error';
        title: string;
        detail: string;
    } | null>(null);
    const [searchTerm, setSearchTerm] = useState('');
    const [debouncedSearch, setDebouncedSearch] = useState('');
    const [coverageFilter, setCoverageFilter] = useState<typeof rtmCoverageFilters[number]>(initialCoverageFilter);
    const [categoryFilter, setCategoryFilter] = useState('');
    const [priorityFilter, setPriorityFilter] = useState('');
    const [expandedRows, setExpandedRows] = useState<Set<number>>(new Set());
    const [linkingReqId, setLinkingReqId] = useState<number | null>(null);
    const [unlinkingEntryId, setUnlinkingEntryId] = useState<number | null>(null);
    const [specSearchTerm, setSpecSearchTerm] = useState('');
    const [availableSpecs, setAvailableSpecs] = useState<SpecListItem[]>([]);
    const [specsLoading, setSpecsLoading] = useState(false);
    const [snapshotModalOpen, setSnapshotModalOpen] = useState(false);
    const [snapshotName, setSnapshotName] = useState('');
    const [snapshots, setSnapshots] = useState<Snapshot[]>([]);
    const [snapshotsLoading, setSnapshotsLoading] = useState(false);
    const [creatingSnapshot, setCreatingSnapshot] = useState(false);
    const [selectedSnapshot, setSelectedSnapshot] = useState<SnapshotDetail | null>(null);
    const [snapshotDetailLoading, setSnapshotDetailLoading] = useState(false);
    const [exportMenuOpen, setExportMenuOpen] = useState(false);
    const [showGaps, setShowGaps] = useState(true);
    const [generateSpecFor, setGenerateSpecFor] = useState<RequirementForSpec | null>(null);
    const searchDebounceRef = useRef<NodeJS.Timeout | null>(null);
    const generationPollRef = useRef<NodeJS.Timeout | null>(null);

    const projectId = currentProject?.id;

    const fetchRtm = useCallback(async (offset = 0, append = false) => {
        if (projectLoading) return;

        const params = new URLSearchParams();
        if (projectId) params.set('project_id', projectId);
        params.set('limit', String(PAGE_SIZE));
        params.set('offset', String(offset));
        if (debouncedSearch) params.set('search', debouncedSearch);
        if (coverageFilter !== 'all') params.set('coverage_status', coverageFilter);
        if (categoryFilter) params.set('category', categoryFilter);
        if (priorityFilter) params.set('priority', priorityFilter);

        try {
            if (append) setLoadingMore(true);
            else setLoading(true);

            const res = await fetch(`${API_BASE}/rtm?${params.toString()}`);
            if (!res.ok) throw new Error('Failed to load RTM');
            const data = await res.json();

            setRequirements(prev => append ? [...prev, ...data.items] : data.items);
            setTotalCount(data.total);
            setHasMore(data.has_more);
            if (!append) setSummary(data.summary);
        } catch (error) {
            console.error('Failed to fetch RTM:', error);
            toast.error('Failed to load RTM data');
        } finally {
            setLoading(false);
            setLoadingMore(false);
        }
    }, [categoryFilter, coverageFilter, debouncedSearch, priorityFilter, projectId, projectLoading]);

    const fetchGaps = useCallback(async () => {
        if (projectLoading) return;

        try {
            const res = await fetch(`${API_BASE}/rtm/gaps${projectQuery(projectId)}`);
            if (!res.ok) throw new Error('Failed to load gaps');
            const data = await res.json();
            setGaps(data);
        } catch (error) {
            console.error('Failed to fetch RTM gaps:', error);
            toast.error('Failed to load coverage gaps');
        }
    }, [projectId, projectLoading]);

    const fetchTrend = useCallback(async () => {
        if (projectLoading) return;

        try {
            const res = await fetch(`${API_BASE}/rtm/trend${projectQuery(projectId)}`);
            if (res.ok) setTrend(await res.json());
        } catch (error) {
            console.error('Failed to fetch RTM trend:', error);
        }
    }, [projectId, projectLoading]);

    const refreshAll = useCallback(async () => {
        await Promise.all([fetchRtm(0, false), fetchGaps(), fetchTrend()]);
    }, [fetchGaps, fetchRtm, fetchTrend]);

    useEffect(() => {
        if (searchDebounceRef.current) clearTimeout(searchDebounceRef.current);
        searchDebounceRef.current = setTimeout(() => setDebouncedSearch(searchTerm), 300);
        return () => {
            if (searchDebounceRef.current) clearTimeout(searchDebounceRef.current);
        };
    }, [searchTerm]);

    useEffect(() => {
        refreshAll();
    }, [refreshAll]);

    useEffect(() => {
        const urlCoverageFilter = initialCoverageFilter();
        if (urlCoverageFilter !== coverageFilter) {
            setCoverageFilter(urlCoverageFilter);
        }
        // Run once after hydration so dashboard deep links initialize client state.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    useEffect(() => {
        return () => {
            if (generationPollRef.current) clearInterval(generationPollRef.current);
        };
    }, []);

    const chartData = useMemo(() => {
        if (!summary) return [];
        return [
            { name: 'Covered', value: summary.covered, color: coverageColors.covered },
            { name: 'Partial', value: summary.partial, color: coverageColors.partial },
            { name: 'Uncovered', value: summary.uncovered, color: coverageColors.uncovered },
        ].filter(item => item.value > 0);
    }, [summary]);

    const highPriorityGaps = useMemo(
        () => gaps.filter(gap => gap.priority === 'critical' || gap.priority === 'high').length,
        [gaps],
    );

    const filteredSpecs = useMemo(() => {
        const query = specSearchTerm.trim().toLowerCase();
        if (!query) return availableSpecs;
        return availableSpecs.filter(spec => spec.name.toLowerCase().includes(query));
    }, [availableSpecs, specSearchTerm]);

    const toggleExpanded = (id: number) => {
        setExpandedRows(prev => {
            const next = new Set(prev);
            if (next.has(id)) next.delete(id);
            else next.add(id);
            return next;
        });
    };

    const generateRtm = async () => {
        setGenerating(true);
        setGenerationNotice(null);
        try {
            const res = await fetch(`${API_BASE}/rtm/generate${projectQuery(projectId)}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ use_ai_matching: true }),
            });

            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.detail || 'Failed to generate RTM');
            }

            const data = await res.json();
            if (!data.job_id) {
                await refreshAll();
                setGenerating(false);
                setGenerationNotice({
                    tone: 'success',
                    title: 'RTM refreshed',
                    detail: 'The traceability matrix was refreshed successfully.',
                });
                toast.success('RTM generated');
                return;
            }

            setGenerationJobId(data.job_id);
            const pollStartedAt = Date.now();
            generationPollRef.current = setInterval(async () => {
                try {
                    if (Date.now() - pollStartedAt > 10 * 60 * 1000) {
                        if (generationPollRef.current) clearInterval(generationPollRef.current);
                        generationPollRef.current = null;
                        setGenerationJobId(null);
                        setGenerating(false);
                        setGenerationNotice({
                            tone: 'error',
                            title: 'RTM generation timed out',
                            detail: 'The background job did not finish within 10 minutes. Try again or check backend logs.',
                        });
                        toast.error('RTM generation timed out');
                        return;
                    }

                    const pollRes = await fetch(`${API_BASE}/rtm/generate-jobs/${data.job_id}`);
                    if (!pollRes.ok) {
                        if (generationPollRef.current) clearInterval(generationPollRef.current);
                        generationPollRef.current = null;
                        setGenerationJobId(null);
                        setGenerating(false);
                        setGenerationNotice({
                            tone: 'error',
                            title: 'RTM generation status was lost',
                            detail: 'The background job could not be found. Refresh the page and try generating again.',
                        });
                        toast.error('RTM generation status was lost');
                        return;
                    }
                    const pollData = await pollRes.json();

                    if (pollData.status === 'completed') {
                        if (generationPollRef.current) clearInterval(generationPollRef.current);
                        generationPollRef.current = null;
                        setGenerationJobId(null);
                        setGenerating(false);
                        await refreshAll();
                        const result = pollData.result;
                        if (result?.total_requirements === 0) {
                            setGenerationNotice({
                                tone: 'warning',
                                title: 'No requirements found',
                                detail: 'RTM generation ran, but there are no requirements to map yet. Generate or add requirements first.',
                            });
                            toast.warning('No requirements found for RTM');
                        } else {
                            setGenerationNotice({
                                tone: 'success',
                                title: 'RTM generated',
                                detail: `${result?.covered ?? 0} covered, ${result?.partial ?? 0} partial, ${result?.uncovered ?? 0} uncovered. ${result?.mappings_created ?? 0} mapping${result?.mappings_created === 1 ? '' : 's'} created.`,
                            });
                            toast.success('RTM generated');
                        }
                    } else if (pollData.status === 'failed') {
                        if (generationPollRef.current) clearInterval(generationPollRef.current);
                        generationPollRef.current = null;
                        setGenerationJobId(null);
                        setGenerating(false);
                        setGenerationNotice({
                            tone: 'error',
                            title: 'RTM generation failed',
                            detail: pollData.error || 'The backend could not generate the traceability matrix.',
                        });
                        toast.error(pollData.error || 'Failed to generate RTM');
                    }
                } catch (error) {
                    console.error('RTM generation poll failed:', error);
                    if (generationPollRef.current) clearInterval(generationPollRef.current);
                    generationPollRef.current = null;
                    setGenerationJobId(null);
                    setGenerating(false);
                    setGenerationNotice({
                        tone: 'error',
                        title: 'RTM generation polling failed',
                        detail: 'The browser could not read the generation status. Check the API connection and try again.',
                    });
                    toast.error('RTM generation polling failed');
                }
            }, 2000);
        } catch (error) {
            console.error('Failed to generate RTM:', error);
            setGenerating(false);
            setGenerationNotice({
                tone: 'error',
                title: 'Could not start RTM generation',
                detail: error instanceof Error ? error.message : 'The generation request failed before a job was created.',
            });
            toast.error(error instanceof Error ? error.message : 'Failed to generate RTM');
        }
    };

    const exportRtm = async (format: 'markdown' | 'csv' | 'html') => {
        setExportMenuOpen(false);
        try {
            const res = await fetch(`${API_BASE}/rtm/export/${format}${projectQuery(projectId)}`);
            if (!res.ok) throw new Error('Failed to export RTM');
            const blob = await res.blob();
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `rtm.${format === 'markdown' ? 'md' : format}`;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            window.URL.revokeObjectURL(url);
        } catch (error) {
            console.error('Failed to export RTM:', error);
            toast.error('Failed to export RTM');
        }
    };

    const fetchSnapshots = async () => {
        setSnapshotsLoading(true);
        try {
            const res = await fetch(`${API_BASE}/rtm/snapshots${projectQuery(projectId)}`);
            if (!res.ok) throw new Error('Failed to fetch snapshots');
            setSnapshots(await res.json());
        } catch (error) {
            console.error('Failed to fetch snapshots:', error);
            toast.error('Failed to load snapshots');
        } finally {
            setSnapshotsLoading(false);
        }
    };

    const createSnapshot = async () => {
        setCreatingSnapshot(true);
        const separator = projectId ? '&' : '?';
        const nameParam = snapshotName.trim() ? `${separator}name=${encodeURIComponent(snapshotName.trim())}` : '';

        try {
            const res = await fetch(`${API_BASE}/rtm/snapshot${projectQuery(projectId)}${nameParam}`, { method: 'POST' });
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.detail || 'Failed to create snapshot');
            }
            setSnapshotModalOpen(false);
            setSnapshotName('');
            setSelectedSnapshot(null);
            await fetchTrend();
            toast.success('RTM snapshot created');
        } catch (error) {
            console.error('Failed to create snapshot:', error);
            toast.error(error instanceof Error ? error.message : 'Failed to create snapshot');
        } finally {
            setCreatingSnapshot(false);
        }
    };

    const fetchSnapshotDetail = async (snapshotId: number) => {
        setSnapshotDetailLoading(true);
        try {
            const res = await fetch(`${API_BASE}/rtm/snapshot/${snapshotId}${projectQuery(projectId)}`);
            if (!res.ok) throw new Error('Failed to load snapshot');
            setSelectedSnapshot(await res.json());
        } catch (error) {
            console.error('Failed to fetch snapshot detail:', error);
            toast.error('Failed to load snapshot');
        } finally {
            setSnapshotDetailLoading(false);
        }
    };

    const fetchSpecs = useCallback(async () => {
        setSpecsLoading(true);
        const params = new URLSearchParams();
        if (projectId) params.set('project_id', projectId);
        params.set('limit', '200');

        try {
            const res = await fetch(`${API_BASE}/specs/list?${params.toString()}`);
            if (!res.ok) throw new Error('Failed to fetch specs');
            const data = await res.json();
            setAvailableSpecs(data.items || data.specs || data || []);
        } catch (error) {
            console.error('Failed to fetch specs:', error);
            toast.error('Failed to load specs');
        } finally {
            setSpecsLoading(false);
        }
    }, [projectId]);

    const startLinking = (requirementId: number) => {
        setLinkingReqId(prev => prev === requirementId ? null : requirementId);
        if (availableSpecs.length === 0) fetchSpecs();
    };

    const linkTest = async (requirementId: number, spec: SpecListItem) => {
        try {
            const res = await fetch(`${API_BASE}/rtm/entry${projectQuery(projectId)}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    requirement_id: requirementId,
                    test_spec_name: spec.name,
                    test_spec_path: spec.path,
                    mapping_type: 'full',
                    confidence: 1.0,
                    coverage_notes: 'Manually linked from RTM dashboard',
                }),
            });
            if (!res.ok) throw new Error('Failed to link test');
            setLinkingReqId(null);
            setSpecSearchTerm('');
            await refreshAll();
            toast.success('Test linked');
        } catch (error) {
            console.error('Failed to link test:', error);
            toast.error('Failed to link test');
        }
    };

    const unlinkTest = async (entryId: number) => {
        try {
            const res = await fetch(`${API_BASE}/rtm/entry/${entryId}${projectQuery(projectId)}`, { method: 'DELETE' });
            if (!res.ok) throw new Error('Failed to unlink test');
            setUnlinkingEntryId(null);
            await refreshAll();
            toast.success('Test unlinked');
        } catch (error) {
            console.error('Failed to unlink test:', error);
            toast.error('Failed to unlink test');
        }
    };

    const openSnapshotModal = async () => {
        setSnapshotModalOpen(true);
        setSelectedSnapshot(null);
        await fetchSnapshots();
    };

    const actions = (
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap', justifyContent: 'flex-end' }}>
            <button className="btn btn-secondary" onClick={refreshAll} disabled={loading || projectLoading}>
                <RefreshCw size={16} className={loading ? 'spinning' : ''} />
                Refresh
            </button>
            <button className="btn btn-primary" onClick={generateRtm} disabled={generating || projectLoading}>
                {generating ? <Loader2 size={16} className="spinning" /> : <GitBranch size={16} />}
                {generationJobId ? 'Generating...' : 'Generate RTM'}
            </button>
            <div style={{ position: 'relative' }}>
                <button className="btn btn-secondary" onClick={() => setExportMenuOpen(prev => !prev)} aria-expanded={exportMenuOpen} aria-haspopup="menu">
                    <Download size={16} />
                    Export
                    <ChevronDown size={14} />
                </button>
                {exportMenuOpen && (
                    <div
                        role="menu"
                        style={{
                            position: 'absolute',
                            top: 'calc(100% + 0.35rem)',
                            right: 0,
                            zIndex: 1002,
                            minWidth: 150,
                            border: '1px solid var(--border)',
                            borderRadius: 8,
                            background: 'var(--surface)',
                            boxShadow: 'var(--shadow-lg)',
                            padding: '0.35rem',
                        }}
                    >
                        {(['markdown', 'csv', 'html'] as const).map(format => (
                            <button
                                key={format}
                                role="menuitem"
                                onClick={() => exportRtm(format)}
                                style={{
                                    display: 'block',
                                    width: '100%',
                                    border: 0,
                                    borderRadius: 6,
                                    background: 'transparent',
                                    color: 'var(--text)',
                                    cursor: 'pointer',
                                    fontSize: '0.86rem',
                                    padding: '0.55rem 0.7rem',
                                    textAlign: 'left',
                                }}
                                onMouseEnter={event => { event.currentTarget.style.background = 'var(--surface-hover)'; }}
                                onMouseLeave={event => { event.currentTarget.style.background = 'transparent'; }}
                            >
                                {format === 'markdown' ? 'Markdown' : format.toUpperCase()}
                            </button>
                        ))}
                    </div>
                )}
            </div>
            <button className="btn btn-secondary" onClick={openSnapshotModal} disabled={projectLoading}>
                <Camera size={16} />
                Snapshot
            </button>
        </div>
    );

    if (projectLoading || (loading && !summary)) {
        return (
            <PageLayout tier="wide">
                <DashboardPageSkeleton />
            </PageLayout>
        );
    }

    return (
        <PageLayout tier="wide">
            <PageHeader
                title="RTM"
                subtitle="Track coverage and traceability."
                icon={<GitBranch size={22} />}
                actions={actions}
                breadcrumb={<WorkflowBreadcrumb />}
            />

            {generationNotice && (
                <div className={`rtm-notice rtm-notice-${generationNotice.tone}`} role={generationNotice.tone === 'error' ? 'alert' : 'status'}>
                    <div>
                        <strong>{generationNotice.title}</strong>
                        <span>{generationNotice.detail}</span>
                    </div>
                    <button onClick={() => setGenerationNotice(null)} aria-label="Dismiss RTM generation message">
                        <X size={16} />
                    </button>
                </div>
            )}

            {summary?.total_requirements === 0 ? (
                <EmptyState
                    icon={<GitBranch size={42} />}
                    title="No requirements to trace"
                    description="RTM maps existing requirements to existing test specs. Add or generate requirements first, then build the traceability matrix."
                    action={<Link className="btn btn-primary" href="/requirements">Open Requirements</Link>}
                />
            ) : (
                <div className="rtm-dashboard">
                    <aside className="rtm-sidebar">
                        <section className="card rtm-card">
                            <div className="rtm-section-title">Coverage Overview</div>
                            <div className="rtm-donut">
                                <ResponsiveContainer>
                                    <PieChart>
                                        <Pie data={chartData} cx="50%" cy="50%" innerRadius={58} outerRadius={78} paddingAngle={2} dataKey="value">
                                            {chartData.map(entry => <Cell key={entry.name} fill={entry.color} />)}
                                        </Pie>
                                        <Tooltip
                                            formatter={(value) => [value, 'Requirements']}
                                            contentStyle={{
                                                background: 'var(--surface)',
                                                border: '1px solid var(--border)',
                                                borderRadius: '6px',
                                            }}
                                        />
                                    </PieChart>
                                </ResponsiveContainer>
                                <div className="rtm-donut-label">
                                    <strong>{summary?.coverage_percentage.toFixed(0)}%</strong>
                                    <span>Coverage</span>
                                </div>
                            </div>
                            <div className="rtm-kpis" aria-label="RTM coverage totals">
                                <Kpi label="Total" value={summary?.total_requirements ?? 0} />
                                <Kpi label="Covered" value={summary?.covered ?? 0} color={coverageColors.covered} />
                                <Kpi label="Partial" value={summary?.partial ?? 0} color={coverageColors.partial} />
                                <Kpi label="Uncovered" value={summary?.uncovered ?? 0} color={coverageColors.uncovered} />
                                <Kpi label="High Risk Gaps" value={highPriorityGaps} color={highPriorityGaps > 0 ? 'var(--danger)' : 'var(--success)'} />
                            </div>
                        </section>

                        {trend.length >= 2 && (
                            <section className="card rtm-card">
                                <div className="rtm-section-title">Coverage Trend</div>
                                <div style={{ width: '100%', height: 170 }}>
                                    <ResponsiveContainer>
                                        <AreaChart data={trend} margin={{ top: 5, right: 8, bottom: 5, left: -18 }}>
                                            <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                                            <XAxis
                                                dataKey="created_at"
                                                tick={{ fontSize: 10, fill: 'var(--text-secondary)' }}
                                                tickFormatter={(value) => new Date(value).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}
                                            />
                                            <YAxis tick={{ fontSize: 10, fill: 'var(--text-secondary)' }} />
                                            <Tooltip
                                                labelFormatter={(value) => new Date(value).toLocaleDateString()}
                                                contentStyle={{
                                                    background: 'var(--surface)',
                                                    border: '1px solid var(--border)',
                                                    borderRadius: '6px',
                                                    fontSize: '0.8rem',
                                                }}
                                            />
                                            <Area type="monotone" dataKey="covered" stackId="1" stroke="#34d399" fill="#34d399" fillOpacity={0.6} name="Covered" />
                                            <Area type="monotone" dataKey="partial" stackId="1" stroke="#fbbf24" fill="#fbbf24" fillOpacity={0.6} name="Partial" />
                                            <Area type="monotone" dataKey="uncovered" stackId="1" stroke="#f87171" fill="#f87171" fillOpacity={0.6} name="Uncovered" />
                                        </AreaChart>
                                    </ResponsiveContainer>
                                </div>
                            </section>
                        )}

                        <section className="card rtm-card">
                            <button className="rtm-collapse-button" onClick={() => setShowGaps(prev => !prev)} aria-expanded={showGaps}>
                                <span>
                                    <AlertTriangle size={18} color={coverageColors.uncovered} aria-hidden="true" />
                                    Coverage Gaps ({gaps.length})
                                </span>
                                {showGaps ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                            </button>
                            {showGaps && gaps.length > 0 && (
                                <div className="rtm-gap-mini-list">
                                    {gaps.slice(0, 5).map(gap => (
                                        <button
                                            key={gap.requirement_id}
                                            onClick={() => {
                                                setCoverageFilter('uncovered');
                                                setSearchTerm(gap.requirement_code);
                                            }}
                                        >
                                            <strong>{gap.requirement_code}</strong>
                                            <span>{gap.title}</span>
                                        </button>
                                    ))}
                                    {gaps.length > 5 && <div className="rtm-muted">+{gaps.length - 5} more gaps below</div>}
                                </div>
                            )}
                        </section>
                    </aside>

                    <main className="rtm-main">
                        <section className="card rtm-matrix">
                            <div className="rtm-toolbar">
                                <div className="rtm-search">
                                    <Search size={15} color="var(--text-secondary)" aria-hidden="true" />
                                    <input
                                        type="search"
                                        placeholder="Search requirements..."
                                        value={searchTerm}
                                        onChange={event => setSearchTerm(event.target.value)}
                                    />
                                </div>
                                <div className="rtm-segmented" aria-label="Coverage filter">
                                    {rtmCoverageFilters.map(status => (
                                        <button
                                            key={status}
                                            onClick={() => setCoverageFilter(status)}
                                            aria-pressed={coverageFilter === status}
                                        >
                                            {status}
                                        </button>
                                    ))}
                                </div>
                                <select value={categoryFilter} onChange={event => setCategoryFilter(event.target.value)} aria-label="Filter by category">
                                    <option value="">All Categories</option>
                                    {rtmCategories.map(category => <option key={category} value={category}>{category}</option>)}
                                </select>
                                <select value={priorityFilter} onChange={event => setPriorityFilter(event.target.value)} aria-label="Filter by priority">
                                    <option value="">All Priorities</option>
                                    <option value="critical">Critical</option>
                                    <option value="high">High</option>
                                    <option value="medium">Medium</option>
                                    <option value="low">Low</option>
                                </select>
                                <span className="rtm-count">Showing {requirements.length} of {totalCount}</span>
                            </div>

                            <div className="rtm-table-head" aria-hidden="true">
                                <span>Requirement</span>
                                <span>Category</span>
                                <span>Priority</span>
                                <span>Coverage</span>
                            </div>

                            {requirements.length === 0 ? (
                                <div className="rtm-empty">No requirements match the current filters.</div>
                            ) : (
                                requirements.map(req => (
                                    <RequirementRow
                                        key={req.id}
                                        req={req}
                                        isExpanded={expandedRows.has(req.id)}
                                        linkingReqId={linkingReqId}
                                        unlinkingEntryId={unlinkingEntryId}
                                        specsLoading={specsLoading}
                                        filteredSpecs={filteredSpecs}
                                        specSearchTerm={specSearchTerm}
                                        onToggle={() => toggleExpanded(req.id)}
                                        onGenerateSpec={() => setGenerateSpecFor(toSpecRequirement(req))}
                                        onStartLinking={() => startLinking(req.id)}
                                        onCancelLinking={() => {
                                            setLinkingReqId(null);
                                            setSpecSearchTerm('');
                                        }}
                                        onSpecSearch={setSpecSearchTerm}
                                        onLinkSpec={(spec) => linkTest(req.id, spec)}
                                        onRequestUnlink={setUnlinkingEntryId}
                                        onCancelUnlink={() => setUnlinkingEntryId(null)}
                                        onConfirmUnlink={unlinkTest}
                                    />
                                ))
                            )}

                            {hasMore && requirements.length > 0 && (
                                <div className="rtm-load-more">
                                    <button className="btn btn-secondary" onClick={() => fetchRtm(requirements.length, true)} disabled={loadingMore}>
                                        {loadingMore ? <Loader2 size={16} className="spinning" /> : null}
                                        {loadingMore ? 'Loading...' : `Load More (${requirements.length} of ${totalCount})`}
                                    </button>
                                </div>
                            )}
                        </section>

                        {showGaps && gaps.length > 0 && (
                            <section className="rtm-gaps" aria-labelledby="rtm-gaps-title">
                                <div className="rtm-gaps-header">
                                    <h2 id="rtm-gaps-title">
                                        <AlertTriangle size={20} color={coverageColors.uncovered} aria-hidden="true" />
                                        Coverage Gaps
                                    </h2>
                                    <span>{gaps.length} uncovered requirement{gaps.length === 1 ? '' : 's'}</span>
                                </div>
                                <div className="rtm-gap-list">
                                    {gaps.map(gap => (
                                        <article key={gap.requirement_id} className="card rtm-gap-card">
                                            <div>
                                                <div className="rtm-gap-title">
                                                    <span>{gap.requirement_code}</span>
                                                    <strong>{gap.title}</strong>
                                                </div>
                                                <div className="rtm-gap-meta">
                                                    <Badge label={gap.priority} tone={gap.priority} />
                                                    <Badge label={gap.category} tone="category" />
                                                </div>
                                                {gap.suggested_test.description && (
                                                    <p>{gap.suggested_test.description}</p>
                                                )}
                                                {gap.suggested_test.steps && gap.suggested_test.steps.length > 0 && (
                                                    <ol>
                                                        {gap.suggested_test.steps.slice(0, 4).map((step, index) => <li key={`${gap.requirement_id}-${index}`}>{step}</li>)}
                                                    </ol>
                                                )}
                                            </div>
                                            <div className="rtm-gap-actions">
                                                <button className="btn btn-primary btn-sm" onClick={() => setGenerateSpecFor(toSpecRequirement(gap))}>
                                                    <Sparkles size={14} />
                                                    Generate Spec
                                                </button>
                                                <Link className="btn btn-secondary btn-sm" href={`/specs/new?requirement_id=${gap.requirement_id}&requirement_code=${encodeURIComponent(gap.requirement_code)}`}>
                                                    <FileText size={14} />
                                                    Create Manually
                                                </Link>
                                                <button className="btn btn-secondary btn-sm" onClick={() => startLinking(gap.requirement_id)}>
                                                    <Link2 size={14} />
                                                    Link Existing
                                                </button>
                                            </div>
                                        </article>
                                    ))}
                                </div>
                            </section>
                        )}
                    </main>
                </div>
            )}

            {snapshotModalOpen && (
                <SnapshotModal
                    summary={summary}
                    snapshots={snapshots}
                    snapshotsLoading={snapshotsLoading}
                    selectedSnapshot={selectedSnapshot}
                    snapshotDetailLoading={snapshotDetailLoading}
                    snapshotName={snapshotName}
                    creatingSnapshot={creatingSnapshot}
                    onSnapshotName={setSnapshotName}
                    onClose={() => {
                        if (!creatingSnapshot) {
                            setSnapshotModalOpen(false);
                            setSelectedSnapshot(null);
                        }
                    }}
                    onCreate={createSnapshot}
                    onSelectSnapshot={fetchSnapshotDetail}
                    onBack={() => setSelectedSnapshot(null)}
                />
            )}

            {generateSpecFor && (
                <GenerateSpecModal
                    requirement={generateSpecFor}
                    onClose={() => setGenerateSpecFor(null)}
                    onSuccess={async () => {
                        setGenerateSpecFor(null);
                        await refreshAll();
                    }}
                />
            )}

            {exportMenuOpen && (
                <button
                    aria-label="Close export menu"
                    onClick={() => setExportMenuOpen(false)}
                    style={{
                        position: 'fixed',
                        inset: 0,
                        zIndex: 1001,
                        border: 0,
                        background: 'transparent',
                        cursor: 'default',
                    }}
                />
            )}

            <style jsx>{`
                .rtm-dashboard {
                    display: grid;
                    grid-template-columns: 300px minmax(0, 1fr);
                    gap: 1.5rem;
                    align-items: start;
                }

                .rtm-notice {
                    display: flex;
                    align-items: flex-start;
                    justify-content: space-between;
                    gap: 1rem;
                    margin-bottom: 1rem;
                    padding: 0.85rem 1rem;
                    border-radius: 8px;
                    border: 1px solid var(--border);
                    background: var(--surface);
                }

                .rtm-notice div {
                    display: grid;
                    gap: 0.2rem;
                }

                .rtm-notice strong {
                    font-size: 0.9rem;
                }

                .rtm-notice span {
                    color: var(--text-secondary);
                    font-size: 0.84rem;
                }

                .rtm-notice button {
                    border: 0;
                    background: transparent;
                    color: var(--text-secondary);
                    cursor: pointer;
                    padding: 0.1rem;
                }

                .rtm-notice-success {
                    border-color: rgba(34, 197, 94, 0.25);
                    background: rgba(34, 197, 94, 0.08);
                }

                .rtm-notice-warning {
                    border-color: rgba(251, 191, 36, 0.28);
                    background: rgba(251, 191, 36, 0.09);
                }

                .rtm-notice-error {
                    border-color: rgba(248, 113, 113, 0.28);
                    background: rgba(248, 113, 113, 0.09);
                }

                .rtm-sidebar {
                    display: flex;
                    flex-direction: column;
                    gap: 1rem;
                }

                .rtm-card {
                    padding: 1.25rem;
                }

                .rtm-section-title {
                    font-size: 0.82rem;
                    font-weight: 700;
                    color: var(--text-secondary);
                    text-transform: uppercase;
                    margin-bottom: 1rem;
                }

                .rtm-donut {
                    height: 185px;
                    position: relative;
                }

                .rtm-donut-label {
                    position: absolute;
                    inset: 0;
                    display: flex;
                    flex-direction: column;
                    align-items: center;
                    justify-content: center;
                    pointer-events: none;
                }

                .rtm-donut-label strong {
                    color: var(--success);
                    font-size: 1.85rem;
                    line-height: 1;
                }

                .rtm-donut-label span,
                .rtm-muted {
                    color: var(--text-secondary);
                    font-size: 0.78rem;
                }

                .rtm-kpis {
                    display: grid;
                    grid-template-columns: repeat(2, minmax(0, 1fr));
                    gap: 0.5rem;
                    margin-top: 1rem;
                }

                .rtm-main {
                    min-width: 0;
                }

                .rtm-matrix {
                    padding: 0;
                    overflow: hidden;
                }

                .rtm-toolbar {
                    display: flex;
                    align-items: center;
                    gap: 0.75rem;
                    padding: 0.85rem 1rem;
                    border-bottom: 1px solid var(--border);
                    flex-wrap: wrap;
                }

                .rtm-search {
                    min-width: 220px;
                    flex: 1;
                    display: flex;
                    align-items: center;
                    gap: 0.5rem;
                    padding: 0.45rem 0.65rem;
                    border: 1px solid var(--border);
                    border-radius: 6px;
                    background: var(--surface);
                }

                .rtm-search input {
                    border: 0;
                    outline: 0;
                    background: transparent;
                    color: var(--text);
                    width: 100%;
                    font-size: 0.87rem;
                }

                .rtm-segmented {
                    display: flex;
                    gap: 2px;
                    padding: 2px;
                    border-radius: 6px;
                    background: var(--surface-hover);
                }

                .rtm-segmented button {
                    border: 0;
                    border-radius: 4px;
                    background: transparent;
                    color: var(--text-secondary);
                    cursor: pointer;
                    font-size: 0.76rem;
                    font-weight: 600;
                    padding: 0.36rem 0.65rem;
                    text-transform: capitalize;
                }

                .rtm-segmented button[aria-pressed="true"] {
                    background: var(--surface);
                    color: var(--text);
                    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.12);
                }

                .rtm-toolbar select {
                    border: 1px solid var(--border);
                    border-radius: 6px;
                    background: var(--surface);
                    color: var(--text);
                    cursor: pointer;
                    font-size: 0.8rem;
                    padding: 0.42rem 0.55rem;
                }

                .rtm-count {
                    color: var(--text-secondary);
                    font-size: 0.76rem;
                }

                .rtm-table-head,
                .rtm-row-button {
                    display: grid;
                    grid-template-columns: minmax(260px, 1fr) 120px 95px 110px;
                    gap: 1rem;
                    align-items: center;
                }

                .rtm-table-head {
                    padding: 0.8rem 1rem;
                    background: var(--surface-hover);
                    border-bottom: 1px solid var(--border);
                    color: var(--text-secondary);
                    font-size: 0.74rem;
                    font-weight: 700;
                    text-transform: uppercase;
                }

                .rtm-empty,
                .rtm-load-more {
                    padding: 2rem;
                    text-align: center;
                    color: var(--text-secondary);
                }

                .rtm-collapse-button {
                    display: flex;
                    align-items: center;
                    justify-content: space-between;
                    width: 100%;
                    border: 0;
                    background: none;
                    color: var(--text);
                    cursor: pointer;
                    padding: 0;
                }

                .rtm-collapse-button span {
                    display: flex;
                    align-items: center;
                    gap: 0.5rem;
                    font-weight: 700;
                    font-size: 0.9rem;
                }

                .rtm-gap-mini-list {
                    display: flex;
                    flex-direction: column;
                    gap: 0.4rem;
                    margin-top: 0.85rem;
                }

                .rtm-gap-mini-list button {
                    display: grid;
                    gap: 0.2rem;
                    text-align: left;
                    border: 1px solid var(--border);
                    border-radius: 6px;
                    background: var(--surface);
                    color: var(--text);
                    cursor: pointer;
                    padding: 0.55rem;
                }

                .rtm-gap-mini-list strong {
                    color: var(--primary);
                    font-size: 0.75rem;
                }

                .rtm-gap-mini-list span {
                    font-size: 0.82rem;
                    overflow: hidden;
                    text-overflow: ellipsis;
                    white-space: nowrap;
                }

                .rtm-gaps {
                    margin-top: 1.5rem;
                }

                .rtm-gaps-header {
                    display: flex;
                    align-items: center;
                    justify-content: space-between;
                    gap: 1rem;
                    margin-bottom: 1rem;
                }

                .rtm-gaps-header h2 {
                    display: flex;
                    align-items: center;
                    gap: 0.5rem;
                    font-size: 1.05rem;
                    margin: 0;
                }

                .rtm-gaps-header span {
                    color: var(--text-secondary);
                    font-size: 0.85rem;
                }

                .rtm-gap-list {
                    display: flex;
                    flex-direction: column;
                    gap: 0.75rem;
                }

                .rtm-gap-card {
                    display: grid;
                    grid-template-columns: minmax(0, 1fr) auto;
                    gap: 1rem;
                    padding: 1rem;
                    border-left: 4px solid var(--danger);
                }

                .rtm-gap-title {
                    display: flex;
                    align-items: center;
                    gap: 0.5rem;
                    flex-wrap: wrap;
                    margin-bottom: 0.45rem;
                }

                .rtm-gap-title span {
                    color: var(--primary);
                    font-size: 0.78rem;
                    font-weight: 700;
                }

                .rtm-gap-meta,
                .rtm-gap-actions {
                    display: flex;
                    align-items: center;
                    gap: 0.5rem;
                    flex-wrap: wrap;
                }

                .rtm-gap-card p {
                    color: var(--text-secondary);
                    font-size: 0.86rem;
                    margin: 0.65rem 0 0;
                }

                .rtm-gap-card ol {
                    color: var(--text-secondary);
                    font-size: 0.82rem;
                    margin: 0.65rem 0 0;
                    padding-left: 1.2rem;
                }

                .rtm-gap-actions {
                    justify-content: flex-end;
                    align-content: start;
                }

                @media (max-width: 1100px) {
                    .rtm-dashboard {
                        grid-template-columns: 1fr;
                    }

                    .rtm-sidebar {
                        display: grid;
                        grid-template-columns: repeat(2, minmax(0, 1fr));
                    }
                }

                @media (max-width: 760px) {
                    .rtm-sidebar,
                    .rtm-gap-card {
                        grid-template-columns: 1fr;
                    }

                    .rtm-table-head {
                        display: none;
                    }

                    .rtm-row-button {
                        grid-template-columns: 1fr;
                        gap: 0.75rem;
                    }

                    .rtm-gap-actions {
                        justify-content: flex-start;
                    }
                }
            `}</style>
        </PageLayout>
    );
}

function Kpi({ label, value, color = 'var(--text)' }: { label: string; value: number; color?: string }) {
    return (
        <div style={{ padding: '0.55rem', border: '1px solid var(--border)', borderRadius: 6, background: 'var(--surface)' }}>
            <div style={{ fontSize: '0.72rem', color: 'var(--text-secondary)', marginBottom: '0.2rem' }}>{label}</div>
            <div style={{ fontSize: '1.1rem', fontWeight: 700, color }}>{value}</div>
        </div>
    );
}

function Badge({ label, tone }: { label: string; tone: string }) {
    const style = priorityStyles[tone] ?? { bg: 'rgba(192, 132, 252, 0.12)', color: 'var(--accent)' };
    return (
        <span style={{
            display: 'inline-flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: '0.23rem 0.5rem',
            borderRadius: 4,
            fontSize: '0.72rem',
            fontWeight: 700,
            textTransform: tone === 'category' ? 'none' : 'uppercase',
            background: style.bg,
            color: style.color,
        }}>
            {label}
        </span>
    );
}

function RequirementRow({
    req,
    isExpanded,
    linkingReqId,
    unlinkingEntryId,
    specsLoading,
    filteredSpecs,
    specSearchTerm,
    onToggle,
    onGenerateSpec,
    onStartLinking,
    onCancelLinking,
    onSpecSearch,
    onLinkSpec,
    onRequestUnlink,
    onCancelUnlink,
    onConfirmUnlink,
}: {
    req: RtmRequirement;
    isExpanded: boolean;
    linkingReqId: number | null;
    unlinkingEntryId: number | null;
    specsLoading: boolean;
    filteredSpecs: SpecListItem[];
    specSearchTerm: string;
    onToggle: () => void;
    onGenerateSpec: () => void;
    onStartLinking: () => void;
    onCancelLinking: () => void;
    onSpecSearch: (value: string) => void;
    onLinkSpec: (spec: SpecListItem) => void;
    onRequestUnlink: (entryId: number) => void;
    onCancelUnlink: () => void;
    onConfirmUnlink: (entryId: number) => void;
}) {
    return (
        <div className="rtm-row">
            <button className="rtm-row-button" onClick={onToggle} aria-expanded={isExpanded}>
                <span className="rtm-row-title">
                    {isExpanded ? <ChevronDown size={16} aria-hidden="true" /> : <ChevronRight size={16} aria-hidden="true" />}
                    <span>
                        <span className="rtm-code">{req.code}</span>
                        <strong>{req.title}</strong>
                        {req.tests.length > 0 && <small>{req.tests.length} linked test{req.tests.length === 1 ? '' : 's'}</small>}
                    </span>
                </span>
                <Badge label={req.category} tone="category" />
                <Badge label={req.priority} tone={req.priority} />
                <span className="rtm-coverage">
                    {getCoverageIcon(req.coverage_status)}
                    <span>{req.coverage_status}</span>
                </span>
            </button>

            {isExpanded && (
                <div className="rtm-row-detail">
                    {req.description && <p>{req.description}</p>}
                    {req.acceptance_criteria.length > 0 && (
                        <div className="rtm-criteria">
                            <div>Acceptance Criteria</div>
                            <ul>
                                {req.acceptance_criteria.map((criterion, index) => <li key={`${req.id}-${index}`}>{criterion}</li>)}
                            </ul>
                        </div>
                    )}

                    <div className="rtm-linked-header">
                        <strong>Linked Tests</strong>
                        <button className="btn btn-secondary btn-sm" onClick={onStartLinking}>
                            <Link2 size={14} />
                            Link Test
                        </button>
                    </div>

                    {req.tests.length > 0 ? (
                        <div className="rtm-linked-list">
                            {req.tests.map(test => (
                                <div key={test.entry_id} className="rtm-linked-test">
                                    <Link className="rtm-linked-test-link" href={specDetailHref(test)}>
                                        <span className="rtm-linked-test-icon-wrap">
                                            <FileText size={14} color="var(--primary)" aria-hidden="true" />
                                        </span>
                                        <span className="rtm-linked-test-name" title={test.spec_name}>{test.spec_name}</span>
                                    </Link>
                                    <div className="rtm-linked-test-meta">
                                        <small className="rtm-linked-test-match">{(test.confidence * 100).toFixed(0)}% match</small>
                                        {unlinkingEntryId === test.entry_id ? (
                                            <div className="rtm-confirm">
                                                <button onClick={() => onConfirmUnlink(test.entry_id)}>Confirm</button>
                                                <button onClick={onCancelUnlink}>Cancel</button>
                                            </div>
                                        ) : (
                                            <button className="rtm-icon-button" onClick={() => onRequestUnlink(test.entry_id)} aria-label={`Unlink ${test.spec_name}`}>
                                                <Unlink size={14} />
                                            </button>
                                        )}
                                    </div>
                                </div>
                            ))}
                        </div>
                    ) : (
                        <div className="rtm-uncovered-panel">
                            <AlertTriangle size={16} color="var(--danger)" aria-hidden="true" />
                            <div>
                                <strong>No tests linked</strong>
                                <span>Create or link a spec to cover this requirement.</span>
                            </div>
                            <button className="btn btn-primary btn-sm" onClick={onGenerateSpec}>
                                <Sparkles size={14} />
                                Generate Spec
                            </button>
                            <Link className="btn btn-secondary btn-sm" href={`/specs/new?requirement_id=${req.id}&requirement_code=${encodeURIComponent(req.code)}`}>
                                <FileText size={14} />
                                Create Manually
                            </Link>
                        </div>
                    )}

                    {linkingReqId === req.id && (
                        <div className="rtm-link-panel">
                            <div className="rtm-link-panel-head">
                                <strong>Select a spec to link</strong>
                                <button onClick={onCancelLinking} aria-label="Close link test panel"><X size={16} /></button>
                            </div>
                            <input
                                value={specSearchTerm}
                                onChange={event => onSpecSearch(event.target.value)}
                                placeholder="Search specs..."
                            />
                            <div className="rtm-link-results">
                                {specsLoading ? (
                                    <div className="rtm-muted">Loading specs...</div>
                                ) : filteredSpecs.length === 0 ? (
                                    <div className="rtm-muted">No specs found</div>
                                ) : (
                                    filteredSpecs.map(spec => (
                                        <div key={spec.path || spec.name}>
                                            <span>{spec.name}</span>
                                            <button onClick={() => onLinkSpec(spec)}>Link</button>
                                        </div>
                                    ))
                                )}
                            </div>
                        </div>
                    )}
                </div>
            )}

            <style jsx>{`
                .rtm-row {
                    border-bottom: 1px solid var(--border);
                }

                .rtm-row-button {
                    display: grid;
                    grid-template-columns: minmax(260px, 1fr) 120px 95px 110px;
                    gap: 1rem;
                    align-items: center;
                    width: 100%;
                    border: 0;
                    background: ${isExpanded ? 'var(--surface-hover)' : 'transparent'};
                    color: var(--text);
                    cursor: pointer;
                    padding: 1rem;
                    text-align: left;
                }

                .rtm-row-button:hover {
                    background: var(--surface-hover);
                }

                .rtm-row-title {
                    display: flex;
                    align-items: center;
                    gap: 0.7rem;
                    min-width: 0;
                }

                .rtm-row-title > span {
                    display: grid;
                    gap: 0.18rem;
                    min-width: 0;
                }

                .rtm-code {
                    color: var(--primary);
                    font-size: 0.78rem;
                    font-weight: 700;
                }

                .rtm-row-title strong {
                    font-size: 0.92rem;
                    overflow: hidden;
                    text-overflow: ellipsis;
                    white-space: nowrap;
                }

                .rtm-row-title small,
                .rtm-linked-test small {
                    color: var(--text-secondary);
                    font-size: 0.75rem;
                }

                .rtm-coverage {
                    display: inline-flex;
                    align-items: center;
                    justify-content: center;
                    gap: 0.4rem;
                    color: ${coverageColors[req.coverage_status]};
                    font-size: 0.82rem;
                    font-weight: 700;
                    text-transform: capitalize;
                }

                .rtm-row-detail {
                    padding: 1rem 1.25rem 1.25rem 3rem;
                    border-top: 1px solid var(--border);
                    background: var(--surface-hover);
                }

                .rtm-row-detail p {
                    color: var(--text-secondary);
                    font-size: 0.9rem;
                    margin: 0 0 1rem;
                }

                .rtm-criteria {
                    margin-bottom: 1rem;
                }

                .rtm-criteria div,
                .rtm-linked-header strong,
                .rtm-link-panel-head strong {
                    color: var(--text-secondary);
                    font-size: 0.78rem;
                    font-weight: 700;
                    text-transform: uppercase;
                }

                .rtm-criteria ul {
                    margin: 0.45rem 0 0;
                    padding-left: 1.2rem;
                    color: var(--text-secondary);
                    font-size: 0.86rem;
                }

                .rtm-linked-header {
                    display: flex;
                    align-items: center;
                    justify-content: space-between;
                    gap: 1rem;
                    margin-bottom: 0.6rem;
                }

                .rtm-linked-list {
                    display: grid;
                    gap: 0.5rem;
                }

                .rtm-linked-test {
                    display: grid;
                    grid-template-columns: minmax(0, 1fr) auto;
                    align-items: center;
                    gap: 1.25rem;
                    min-height: 54px;
                    padding: 0.7rem 0.8rem;
                    background: var(--surface);
                    border: 1px solid var(--border);
                    border-radius: 6px;
                }

                .rtm-linked-test :global(.rtm-linked-test-link) {
                    display: grid;
                    grid-template-columns: 22px minmax(0, 1fr);
                    align-items: center;
                    column-gap: 0.65rem;
                    min-width: 0;
                    color: var(--text);
                    text-decoration: none;
                    font-size: 0.92rem;
                    font-weight: 600;
                }

                .rtm-linked-test :global(.rtm-linked-test-icon-wrap) {
                    display: inline-flex;
                    align-items: center;
                    justify-content: center;
                    width: 22px;
                    height: 22px;
                }

                .rtm-linked-test :global(.rtm-linked-test-name) {
                    display: block;
                    min-width: 0;
                    overflow: hidden;
                    text-overflow: ellipsis;
                    white-space: nowrap;
                }

                .rtm-linked-test-meta {
                    display: inline-flex;
                    align-items: center;
                    justify-content: flex-end;
                    gap: 1rem;
                    min-width: 172px;
                }

                .rtm-linked-test-match {
                    flex: 0 0 auto;
                    display: inline-flex;
                    align-items: center;
                    min-height: 22px;
                    padding: 0 0.5rem;
                    border-radius: 999px;
                    background: var(--surface-hover);
                    line-height: 1;
                    white-space: nowrap;
                }

                .rtm-icon-button,
                .rtm-link-panel-head button {
                    display: inline-flex;
                    align-items: center;
                    justify-content: center;
                    width: 28px;
                    height: 28px;
                    border: 0;
                    border-radius: 4px;
                    background: transparent;
                    color: var(--text-secondary);
                    cursor: pointer;
                }

                .rtm-icon-button:hover {
                    background: var(--danger-muted);
                    color: var(--danger);
                }

                .rtm-confirm {
                    display: flex;
                    gap: 0.3rem;
                }

                .rtm-confirm button,
                .rtm-link-results button {
                    border: 0;
                    border-radius: 4px;
                    cursor: pointer;
                    font-size: 0.72rem;
                    padding: 0.25rem 0.5rem;
                }

                .rtm-confirm button:first-child {
                    background: var(--danger);
                    color: white;
                }

                .rtm-confirm button:last-child {
                    background: var(--surface);
                    border: 1px solid var(--border);
                    color: var(--text-secondary);
                }

                .rtm-uncovered-panel {
                    display: flex;
                    align-items: center;
                    gap: 0.75rem;
                    flex-wrap: wrap;
                    padding: 0.85rem;
                    border: 1px solid rgba(239, 68, 68, 0.22);
                    border-radius: 6px;
                    background: rgba(239, 68, 68, 0.05);
                }

                .rtm-uncovered-panel div {
                    display: grid;
                    gap: 0.1rem;
                    flex: 1;
                    min-width: 180px;
                }

                .rtm-uncovered-panel span {
                    color: var(--text-secondary);
                    font-size: 0.82rem;
                }

                .rtm-link-panel {
                    margin-top: 0.75rem;
                    padding: 0.85rem;
                    border: 1px solid var(--border);
                    border-radius: 6px;
                    background: var(--surface);
                }

                .rtm-link-panel-head {
                    display: flex;
                    align-items: center;
                    justify-content: space-between;
                    gap: 1rem;
                    margin-bottom: 0.55rem;
                }

                .rtm-link-panel input {
                    width: 100%;
                    border: 1px solid var(--border);
                    border-radius: 4px;
                    background: var(--surface);
                    color: var(--text);
                    font-size: 0.82rem;
                    outline: 0;
                    padding: 0.45rem 0.6rem;
                    margin-bottom: 0.55rem;
                }

                .rtm-link-results {
                    display: grid;
                    max-height: 210px;
                    overflow: auto;
                }

                .rtm-link-results > div {
                    display: flex;
                    align-items: center;
                    justify-content: space-between;
                    gap: 0.75rem;
                    border-radius: 4px;
                    padding: 0.45rem 0.5rem;
                }

                .rtm-link-results > div:hover {
                    background: var(--surface-hover);
                }

                .rtm-link-results span {
                    font-size: 0.84rem;
                    overflow: hidden;
                    text-overflow: ellipsis;
                    white-space: nowrap;
                }

                .rtm-link-results button {
                    background: var(--primary);
                    color: white;
                }

                .rtm-muted {
                    color: var(--text-secondary);
                    font-size: 0.82rem;
                    padding: 0.65rem;
                }

                @media (max-width: 760px) {
                    .rtm-row-button {
                        grid-template-columns: 1fr;
                        gap: 0.75rem;
                    }

                    .rtm-row-detail {
                        padding: 1rem;
                    }

                    .rtm-row-title strong {
                        white-space: normal;
                    }
                }
            `}</style>
        </div>
    );
}

function SnapshotModal({
    summary,
    snapshots,
    snapshotsLoading,
    selectedSnapshot,
    snapshotDetailLoading,
    snapshotName,
    creatingSnapshot,
    onSnapshotName,
    onClose,
    onCreate,
    onSelectSnapshot,
    onBack,
}: {
    summary: RtmSummary | null;
    snapshots: Snapshot[];
    snapshotsLoading: boolean;
    selectedSnapshot: SnapshotDetail | null;
    snapshotDetailLoading: boolean;
    snapshotName: string;
    creatingSnapshot: boolean;
    onSnapshotName: (value: string) => void;
    onClose: () => void;
    onCreate: () => void;
    onSelectSnapshot: (id: number) => void;
    onBack: () => void;
}) {
    return (
        <div className="modal-overlay" onClick={onClose}>
            <div className="modal-content" onClick={event => event.stopPropagation()} style={{ width: '540px', maxWidth: '94vw', maxHeight: '84vh', overflow: 'auto' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.25rem' }}>
                    <h2 style={{ display: 'flex', alignItems: 'center', gap: '0.65rem', margin: 0 }}>
                        <Camera size={22} color="var(--primary)" />
                        RTM Snapshot
                    </h2>
                    <button className="btn-icon" onClick={onClose} aria-label="Close snapshot modal">
                        <X size={20} />
                    </button>
                </div>

                {!selectedSnapshot && (
                    <>
                        <label style={{ display: 'grid', gap: '0.45rem', marginBottom: '1rem', fontWeight: 600 }}>
                            Snapshot Name <span style={{ color: 'var(--text-secondary)', fontWeight: 400 }}>(optional)</span>
                            <input className="input" value={snapshotName} onChange={event => onSnapshotName(event.target.value)} placeholder="e.g., Release 1.0 baseline" />
                        </label>

                        {summary && (
                            <div style={{ padding: '1rem', borderRadius: 8, background: 'var(--surface-hover)', marginBottom: '1.25rem' }}>
                                <div style={{ color: 'var(--text-secondary)', fontSize: '0.82rem', marginBottom: '0.5rem' }}>Current Coverage</div>
                                <div style={{ display: 'flex', gap: '1rem', flexWrap: 'wrap', fontSize: '0.88rem' }}>
                                    <span><strong>{summary.total_requirements}</strong> total</span>
                                    <span style={{ color: coverageColors.covered }}><strong>{summary.covered}</strong> covered</span>
                                    <span style={{ color: coverageColors.partial }}><strong>{summary.partial}</strong> partial</span>
                                    <span style={{ color: coverageColors.uncovered }}><strong>{summary.uncovered}</strong> uncovered</span>
                                </div>
                                <div style={{ marginTop: '0.5rem', fontSize: '1.25rem', fontWeight: 800, color: coverageColors.covered }}>
                                    {summary.coverage_percentage.toFixed(1)}% coverage
                                </div>
                            </div>
                        )}

                        <div style={{ marginBottom: '1.25rem' }}>
                            <div style={{ fontSize: '0.82rem', fontWeight: 700, color: 'var(--text-secondary)', marginBottom: '0.65rem' }}>Recent Snapshots</div>
                            <div style={{ display: 'grid', gap: '0.5rem', maxHeight: 220, overflow: 'auto' }}>
                                {snapshotsLoading ? (
                                    <div style={{ color: 'var(--text-secondary)', padding: '0.75rem' }}>Loading snapshots...</div>
                                ) : snapshots.length === 0 ? (
                                    <div style={{ color: 'var(--text-secondary)', padding: '0.75rem' }}>No snapshots yet</div>
                                ) : (
                                    snapshots.slice(0, 8).map(snapshot => (
                                        <button
                                            key={snapshot.id}
                                            onClick={() => onSelectSnapshot(snapshot.id)}
                                            style={{
                                                display: 'flex',
                                                alignItems: 'center',
                                                justifyContent: 'space-between',
                                                gap: '1rem',
                                                padding: '0.75rem',
                                                border: '1px solid var(--border)',
                                                borderRadius: 6,
                                                background: 'var(--surface)',
                                                color: 'var(--text)',
                                                cursor: 'pointer',
                                                textAlign: 'left',
                                            }}
                                        >
                                            <span>
                                                <strong>{snapshot.snapshot_name || new Date(snapshot.created_at).toLocaleDateString()}</strong>
                                                <small style={{ display: 'block', color: 'var(--text-secondary)' }}>{new Date(snapshot.created_at).toLocaleString()}</small>
                                            </span>
                                            <strong style={{ color: coverageColors.covered }}>{snapshot.coverage_percentage.toFixed(0)}%</strong>
                                        </button>
                                    ))
                                )}
                            </div>
                        </div>
                    </>
                )}

                {selectedSnapshot && (
                    <div style={{ marginBottom: '1.25rem' }}>
                        <button className="btn btn-secondary btn-sm" onClick={onBack} style={{ marginBottom: '0.75rem' }}>
                            <ChevronRight size={14} style={{ transform: 'rotate(180deg)' }} />
                            Back
                        </button>
                        <div style={{ padding: '1rem', borderRadius: 8, background: 'var(--surface-hover)', border: '1px solid var(--border)' }}>
                            <strong>{selectedSnapshot.snapshot_name || 'Snapshot'}</strong>
                            <div style={{ color: 'var(--text-secondary)', fontSize: '0.82rem', marginTop: '0.2rem' }}>{new Date(selectedSnapshot.created_at).toLocaleString()}</div>
                            <div style={{ display: 'flex', gap: '1rem', flexWrap: 'wrap', marginTop: '0.75rem', fontSize: '0.86rem' }}>
                                <span style={{ color: coverageColors.covered }}><strong>{selectedSnapshot.covered_requirements}</strong> covered</span>
                                <span style={{ color: coverageColors.partial }}><strong>{selectedSnapshot.partial_requirements}</strong> partial</span>
                                <span style={{ color: coverageColors.uncovered }}><strong>{selectedSnapshot.uncovered_requirements}</strong> uncovered</span>
                            </div>
                            <div style={{ marginTop: '0.5rem', fontSize: '1.2rem', fontWeight: 800, color: coverageColors.covered }}>
                                {selectedSnapshot.coverage_percentage.toFixed(1)}% coverage
                            </div>
                            {selectedSnapshot.data?.requirements && (
                                <div style={{ marginTop: '0.9rem', maxHeight: 220, overflow: 'auto' }}>
                                    {selectedSnapshot.data.requirements.slice(0, 20).map((req, index) => (
                                        <div key={`${req.code}-${index}`} style={{ display: 'flex', justifyContent: 'space-between', gap: '0.75rem', padding: '0.35rem 0', borderBottom: '1px solid var(--border)', fontSize: '0.8rem' }}>
                                            <span><strong style={{ color: 'var(--primary)' }}>{req.code}</strong> {req.title}</span>
                                            <span style={{ color: coverageColors[req.coverage_status] ?? 'var(--text-secondary)' }}>{req.coverage_status}</span>
                                        </div>
                                    ))}
                                </div>
                            )}
                        </div>
                    </div>
                )}

                {snapshotDetailLoading && (
                    <div style={{ color: 'var(--text-secondary)', marginBottom: '1rem' }}>
                        <Loader2 size={16} className="spinning" /> Loading snapshot...
                    </div>
                )}

                <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.75rem' }}>
                    <button className="btn btn-secondary" onClick={onClose} disabled={creatingSnapshot}>Cancel</button>
                    {!selectedSnapshot && (
                        <button className="btn btn-primary" onClick={onCreate} disabled={creatingSnapshot}>
                            {creatingSnapshot ? <Loader2 size={16} className="spinning" /> : <Camera size={16} />}
                            {creatingSnapshot ? 'Creating...' : 'Create Snapshot'}
                        </button>
                    )}
                </div>
            </div>
        </div>
    );
}
