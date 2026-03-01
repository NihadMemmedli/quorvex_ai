'use client';
import { useState, useEffect } from 'react';
import { Clock, CheckCircle2, XCircle, PlayCircle, AlertCircle, FileText, ChevronRight, Timer, Globe, Chrome, Compass, StopCircle, Layers, Hourglass, Trash2, AlertTriangle, Search } from 'lucide-react';
import Link from 'next/link';
import { useProject } from '@/contexts/ProjectContext';
import { API_BASE } from '@/lib/api';
import { toast } from 'sonner';
import { WorkflowBreadcrumb } from '@/components/workflow/WorkflowBreadcrumb';
import { PageLayout } from '@/components/ui/page-layout';
import { PageHeader } from '@/components/ui/page-header';
import { EmptyState } from '@/components/ui/empty-state';

interface Run {
    id: string;
    timestamp: string;
    status: string;
    test_name?: string;
    steps_completed: number;
    total_steps: number;
    browser?: string;
    canStop?: boolean;
    queue_position?: number | null;
    queued_at?: string | null;
    started_at?: string | null;
    // Stage tracking for real-time UI feedback
    current_stage?: string | null;  // "planning", "generating", "testing", "healing"
    stage_started_at?: string | null;
    stage_message?: string | null;
    healing_attempt?: number | null;
}

interface PaginatedResponse {
    runs: Run[];
    total: number;
    limit: number;
    offset: number;
    has_more: boolean;
}

interface QueueStatus {
    running_count: number;
    queued_count: number;
    parallelism_limit: number;
    database_type: string;
    parallel_mode_enabled: boolean;
    orphaned_running_count?: number;
    active_process_count?: number;
    orphaned_queued_count?: number;
}

const PAGE_SIZE = 20;

export default function RunsPage() {
    const { currentProject, isLoading: projectLoading } = useProject();
    const [runs, setRuns] = useState<Run[]>([]);
    const [loading, setLoading] = useState(true);
    const [loadingMore, setLoadingMore] = useState(false);
    const [hasMore, setHasMore] = useState(false);
    const [total, setTotal] = useState(0);
    const [stoppingRuns, setStoppingRuns] = useState<Set<string>>(new Set());
    const [confirmStop, setConfirmStop] = useState<string | null>(null);
    const [queueStatus, setQueueStatus] = useState<QueueStatus | null>(null);
    const [confirmClearQueue, setConfirmClearQueue] = useState(false);
    const [clearingQueue, setClearingQueue] = useState(false);
    const [includeRunningInClear, setIncludeRunningInClear] = useState(false);
    const [confirmStopAll, setConfirmStopAll] = useState(false);
    const [stoppingAll, setStoppingAll] = useState(false);
    const [statusFilter, setStatusFilter] = useState<string>('all');
    const [searchQuery, setSearchQuery] = useState('');
    const [debouncedSearch, setDebouncedSearch] = useState('');
    const [deletingRuns, setDeletingRuns] = useState<Set<string>>(new Set());
    const [confirmDelete, setConfirmDelete] = useState<string | null>(null);

    const fetchQueueStatus = () => {
        fetch(`${API_BASE}/queue-status`)
            .then(res => res.json())
            .then((data: QueueStatus) => setQueueStatus(data))
            .catch(console.error);
    };

    // Debounce search input
    useEffect(() => {
        const timer = setTimeout(() => setDebouncedSearch(searchQuery), 300);
        return () => clearTimeout(timer);
    }, [searchQuery]);

    const fetchRuns = (offset: number = 0, append: boolean = false) => {
        const isInitialLoad = offset === 0 && !append;
        if (isInitialLoad) {
            setLoading(true);
        } else {
            setLoadingMore(true);
        }

        // Build URL with optional project filter and search/status filters
        let runsUrl = `${API_BASE}/runs?limit=${PAGE_SIZE}&offset=${offset}`;
        if (currentProject?.id) {
            runsUrl += `&project_id=${encodeURIComponent(currentProject.id)}`;
        }
        if (statusFilter !== 'all') {
            runsUrl += `&status=${encodeURIComponent(statusFilter)}`;
        }
        if (debouncedSearch) {
            runsUrl += `&search=${encodeURIComponent(debouncedSearch)}`;
        }

        Promise.all([
            fetch(runsUrl).then(res => res.json()),
            fetch(`${API_BASE}/queue-status`).then(res => res.json())
        ])
            .then(([runsData, queueData]: [PaginatedResponse, QueueStatus]) => {
                if (append) {
                    setRuns(prev => [...prev, ...runsData.runs]);
                } else {
                    setRuns(runsData.runs);
                }
                setHasMore(runsData.has_more);
                setTotal(runsData.total);
                setQueueStatus(queueData);
                setLoading(false);
                setLoadingMore(false);
            })
            .catch(err => {
                console.error(err);
                toast.error('Failed to load test runs');
                setLoading(false);
                setLoadingMore(false);
            });
    };

    const loadMore = () => {
        if (!loadingMore && hasMore) {
            fetchRuns(runs.length, true);
        }
    };

    useEffect(() => {
        // Wait for project context to finish loading
        if (projectLoading) {
            return;
        }
        fetchRuns();
    }, [currentProject?.id, projectLoading, statusFilter, debouncedSearch]); // Re-fetch when project or filters change

    useEffect(() => {
        // Auto-refresh every 3 seconds if there are running or queued tests
        const interval = setInterval(() => {
            const hasRunning = runs.some(r =>
                r.status === 'running' ||
                r.status === 'in_progress' ||
                r.status === 'pending' ||
                r.status === 'queued'
            );
            if (hasRunning) {
                // Build URL with optional project filter and search/status filters
                let runsUrl = `${API_BASE}/runs?limit=${PAGE_SIZE}&offset=0`;
                if (currentProject?.id) {
                    runsUrl += `&project_id=${encodeURIComponent(currentProject.id)}`;
                }
                if (statusFilter !== 'all') {
                    runsUrl += `&status=${encodeURIComponent(statusFilter)}`;
                }
                if (debouncedSearch) {
                    runsUrl += `&search=${encodeURIComponent(debouncedSearch)}`;
                }

                // Refresh runs and queue status
                Promise.all([
                    fetch(runsUrl).then(res => res.json()),
                    fetch(`${API_BASE}/queue-status`).then(res => res.json())
                ])
                    .then(([runsData, queueData]: [PaginatedResponse, QueueStatus]) => {
                        // Update only the runs we have loaded, preserving order
                        setRuns(prev => {
                            const newRuns = [...prev];
                            runsData.runs.forEach(newRun => {
                                const idx = newRuns.findIndex(r => r.id === newRun.id);
                                if (idx !== -1) {
                                    newRuns[idx] = newRun;
                                }
                            });
                            return newRuns;
                        });
                        setTotal(runsData.total);
                        setQueueStatus(queueData);
                    })
                    .catch(console.error);
            }
        }, 3000);

        return () => clearInterval(interval);
    }, [runs.length > 0 ? runs.some(r => ['running', 'in_progress', 'pending', 'queued'].includes(r.status)) : false, currentProject?.id]);

    const handleStopRun = async (runId: string, e: React.MouseEvent) => {
        e.preventDefault();
        e.stopPropagation();
        setConfirmStop(runId);
    };

    const confirmStopRun = async () => {
        if (!confirmStop) return;

        setStoppingRuns(prev => new Set(prev).add(confirmStop));

        try {
            const res = await fetch(`${API_BASE}/runs/${confirmStop}/stop`, {
                method: 'POST'
            });

            if (res.ok) {
                toast.success('Run stopped successfully');
                fetchRuns(); // Refresh immediately
            } else {
                toast.error('Failed to stop run');
            }
        } catch (err) {
            toast.error('Error stopping run');
        } finally {
            setStoppingRuns(prev => {
                const next = new Set(prev);
                next.delete(confirmStop);
                return next;
            });
            setConfirmStop(null);
        }
    };

    const handleStopAll = async () => {
        setStoppingAll(true);
        try {
            const res = await fetch(`${API_BASE}/stop-all`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
            });
            if (res.ok) {
                const data = await res.json();
                const total = (data.stopped_processes || 0) + (data.cancelled_autopilot || 0) +
                             (data.cancelled_explorations || 0) + (data.cleaned_db_entries || 0);
                toast.success(`Stopped ${total} jobs/entries`);
                fetchRuns();
            } else {
                toast.error('Failed to stop all jobs');
            }
        } catch (err) {
            toast.error('Error stopping all jobs');
        } finally {
            setStoppingAll(false);
            setConfirmStopAll(false);
        }
    };

    const handleClearQueue = async () => {
        setClearingQueue(true);
        try {
            const res = await fetch(`${API_BASE}/queue/clear`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    include_queued: true,
                    include_running: includeRunningInClear
                })
            });

            if (res.ok) {
                const data = await res.json();
                toast.success(`Cleared ${data.cleared_count} queue entries`);
                fetchRuns(); // Refresh immediately
            } else {
                toast.error('Failed to clear queue');
            }
        } catch (err) {
            toast.error('Error clearing queue');
        } finally {
            setClearingQueue(false);
            setConfirmClearQueue(false);
            setIncludeRunningInClear(false);
        }
    };

    const handleDeleteRun = async (runId: string, e: React.MouseEvent) => {
        e.preventDefault();
        e.stopPropagation();
        setConfirmDelete(runId);
    };

    const confirmDeleteRun = async () => {
        if (!confirmDelete) return;

        setDeletingRuns(prev => new Set(prev).add(confirmDelete));

        try {
            const res = await fetch(`${API_BASE}/runs/${confirmDelete}`, {
                method: 'DELETE'
            });

            if (res.ok || res.status === 204) {
                toast.success('Run deleted successfully');
                setRuns(prev => prev.filter(r => r.id !== confirmDelete));
                setTotal(prev => prev - 1);
            } else {
                const data = await res.json().catch(() => ({}));
                toast.error(data.detail || 'Failed to delete run');
            }
        } catch (err) {
            toast.error('Error deleting run');
        } finally {
            setDeletingRuns(prev => {
                const next = new Set(prev);
                next.delete(confirmDelete);
                return next;
            });
            setConfirmDelete(null);
        }
    };

    const getStatusConfig = (status: string, queuePosition?: number | null) => {
        switch (status) {
            case 'completed':
            case 'passed':
            case 'success':
                return {
                    icon: <CheckCircle2 size={24} />,
                    color: 'var(--success)',
                    bg: 'var(--success-muted)',
                    borderColor: 'rgba(52, 211, 153, 0.2)',
                    label: 'Passed'
                };
            case 'failed':
            case 'failure':
                return {
                    icon: <XCircle size={24} />,
                    color: 'var(--danger)',
                    bg: 'var(--danger-muted)',
                    borderColor: 'rgba(248, 113, 113, 0.2)',
                    label: 'Failed'
                };
            case 'stopped':
                return {
                    icon: <StopCircle size={24} />,
                    color: 'var(--warning)',
                    bg: 'var(--warning-muted)',
                    borderColor: 'rgba(251, 191, 36, 0.2)',
                    label: 'Stopped'
                };
            case 'in_progress':
            case 'running':
                return {
                    icon: <PlayCircle size={24} />,
                    color: 'var(--primary)',
                    bg: 'var(--primary-glow)',
                    borderColor: 'rgba(59, 130, 246, 0.25)',
                    label: 'Running'
                };
            case 'queued':
                return {
                    icon: <Hourglass size={24} />,
                    color: 'var(--warning)',
                    bg: 'var(--warning-muted)',
                    borderColor: 'rgba(251, 191, 36, 0.2)',
                    label: queuePosition ? `Queued #${queuePosition}` : 'Queued'
                };
            case 'pending':
                return {
                    icon: <Clock size={24} />,
                    color: 'var(--text-secondary)',
                    bg: 'var(--surface)',
                    borderColor: 'var(--border)',
                    label: 'Pending'
                };
            case 'error':
                return {
                    icon: <AlertCircle size={24} />,
                    color: 'var(--danger)',
                    bg: 'var(--danger-muted)',
                    borderColor: 'rgba(248, 113, 113, 0.2)',
                    label: 'Error'
                };
            default: return {
                icon: <AlertCircle size={24} />,
                color: 'var(--text-secondary)',
                bg: 'var(--surface)',
                borderColor: 'var(--border)',
                label: status
            };
        }
    };

    const getBrowserIcon = (browser?: string) => {
        switch (browser) {
            case 'firefox':
                return <Globe size={16} color="#FF7139" />; // Firefox orange
            case 'webkit':
                return <Compass size={16} color="#007AFF" />; // Safari blue
            case 'chromium':
            default:
                return <Chrome size={16} color="#4285F4" />; // Chrome blue
        }
    };

    // Get stage display for running tests
    const getStageDisplay = (run: Run) => {
        if (run.status !== 'running' && run.status !== 'in_progress') {
            return null;
        }

        const stageIcons: Record<string, string> = {
            planning: '📋',
            generating: '🤖',
            testing: '🔍',
            healing: '🔧'
        };

        const stageLabels: Record<string, string> = {
            planning: 'Planning',
            generating: 'Generating',
            testing: 'Testing',
            healing: 'Healing'
        };

        const stage = run.current_stage || 'running';
        const icon = stageIcons[stage] || '⏳';
        let label = stageLabels[stage] || 'Running';

        // Add healing attempt info
        if (stage === 'healing' && run.healing_attempt) {
            label = `Healing (${run.healing_attempt}/3)`;
        }

        return { icon, label, message: run.stage_message };
    };

    const formatTimestamp = (ts: string) => {
        try {
            // ts is in format 2026-01-07_22-12-37
            const [datePart, timePart] = ts.split('_');
            const [year, month, day] = datePart.split('-').map(Number);
            const [hour, min, sec] = timePart.split('-').map(Number);

            const date = new Date(year, month - 1, day, hour, min, sec);
            return date.toLocaleString('en-US', {
                month: 'short',
                day: 'numeric',
                year: 'numeric',
                hour: 'numeric',
                minute: '2-digit',
                hour12: true
            });
        } catch (e) {
            return ts;
        }
    };

    const formatRunId = (id: string) => {
        try {
            // Extract time portion from format 2026-01-07_22-12-37
            const timePart = id.split('_')[1];
            if (timePart) {
                // Remove dashes and create a compact ID like #221237
                return `#${timePart.replace(/-/g, '')}`;
            }
            // Fallback to last 6 characters
            return `#${id.slice(-6)}`;
        } catch (e) {
            return `#${id.substring(0, 6)}`;
        }
    };

    // Skeleton loading component for run items
    const SkeletonRunItem = () => (
        <div className="list-item" style={{ pointerEvents: 'none' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '1.25rem' }}>
                <div className="status-icon-wrapper" style={{
                    background: 'var(--surface-hover)',
                    border: '1px solid var(--border)',
                    animation: 'pulse 1.5s ease-in-out infinite'
                }}>
                    <div style={{ width: 24, height: 24, borderRadius: 4, background: 'var(--border)' }} />
                </div>
                <div>
                    <div style={{
                        width: 200,
                        height: 18,
                        borderRadius: 4,
                        background: 'var(--surface-hover)',
                        marginBottom: '0.65rem',
                        animation: 'pulse 1.5s ease-in-out infinite'
                    }} />
                    <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
                        <div style={{
                            width: 60,
                            height: 14,
                            borderRadius: 4,
                            background: 'var(--surface-hover)',
                            animation: 'pulse 1.5s ease-in-out infinite'
                        }} />
                        <span style={{ color: 'var(--border)' }}>•</span>
                        <div style={{
                            width: 80,
                            height: 14,
                            borderRadius: 4,
                            background: 'var(--surface-hover)',
                            animation: 'pulse 1.5s ease-in-out infinite'
                        }} />
                        <span style={{ color: 'var(--border)' }}>•</span>
                        <div style={{
                            width: 120,
                            height: 14,
                            borderRadius: 4,
                            background: 'var(--surface-hover)',
                            animation: 'pulse 1.5s ease-in-out infinite'
                        }} />
                    </div>
                </div>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '2rem' }}>
                <div style={{
                    width: 80,
                    height: 14,
                    borderRadius: 4,
                    background: 'var(--surface-hover)',
                    animation: 'pulse 1.5s ease-in-out infinite'
                }} />
                <div style={{
                    width: 100,
                    height: 28,
                    borderRadius: 999,
                    background: 'var(--surface-hover)',
                    animation: 'pulse 1.5s ease-in-out infinite'
                }} />
                <div style={{
                    width: 20,
                    height: 20,
                    borderRadius: 4,
                    background: 'var(--surface-hover)',
                    animation: 'pulse 1.5s ease-in-out infinite'
                }} />
            </div>
        </div>
    );

    if (loading || projectLoading) return (
        <PageLayout tier="standard">
            <PageHeader title="Test Runs" subtitle="History of your automated test executions." />

            <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                {[...Array(6)].map((_, i) => <SkeletonRunItem key={i} />)}
            </div>

            <style jsx>{`
                @keyframes pulse {
                    0%, 100% { opacity: 1; }
                    50% { opacity: 0.4; }
                }
            `}</style>
        </PageLayout>
    );

    return (
        <PageLayout tier="standard">
            <PageHeader
                title="Test Runs"
                subtitle="History of your automated test executions."
                breadcrumb={<WorkflowBreadcrumb />}
            />

            {/* Queue Status Bar */}
            {queueStatus && (queueStatus.running_count > 0 || queueStatus.queued_count > 0 || (queueStatus.orphaned_running_count ?? 0) > 0 || (queueStatus.orphaned_queued_count ?? 0) > 0) && (
                <div className="animate-in stagger-2" style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '1.5rem',
                    padding: '1rem 1.25rem',
                    marginBottom: '1.5rem',
                    borderRadius: 'var(--radius)',
                    background: 'var(--surface)',
                    border: `1px solid ${(queueStatus.orphaned_running_count && queueStatus.orphaned_running_count > 0) || (queueStatus.orphaned_queued_count && queueStatus.orphaned_queued_count > 0) ? 'rgba(251, 191, 36, 0.5)' : 'var(--border)'}`
                }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                        <Layers size={20} color="var(--primary)" />
                        <span style={{ fontWeight: 600 }}>Queue Status</span>
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                        <PlayCircle size={16} color="var(--primary)" />
                        <span style={{ fontSize: '0.9rem' }}>
                            <strong>{queueStatus.running_count}</strong> / {queueStatus.parallelism_limit} running
                        </span>
                    </div>
                    {queueStatus.queued_count > 0 && (
                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                            <Hourglass size={16} color="var(--warning)" />
                            <span style={{ fontSize: '0.9rem', color: 'var(--warning)' }}>
                                <strong>{queueStatus.queued_count}</strong> queued
                            </span>
                        </div>
                    )}
                    {/* Orphan warning - running */}
                    {queueStatus.orphaned_running_count !== undefined && queueStatus.orphaned_running_count > 0 && (
                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                            <AlertTriangle size={16} color="var(--warning)" />
                            <span style={{ fontSize: '0.9rem', color: 'var(--warning)' }}>
                                <strong>{queueStatus.orphaned_running_count}</strong> stuck running
                            </span>
                        </div>
                    )}
                    {/* Orphan warning - queued */}
                    {queueStatus.orphaned_queued_count !== undefined && queueStatus.orphaned_queued_count > 0 && (
                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                            <AlertTriangle size={16} color="var(--warning)" />
                            <span style={{ fontSize: '0.9rem', color: 'var(--warning)' }}>
                                <strong>{queueStatus.orphaned_queued_count}</strong> stuck queued
                            </span>
                        </div>
                    )}
                    {/* Stop All + Clear Queue buttons */}
                    <div style={{ marginLeft: 'auto', display: 'flex', gap: '0.5rem' }}>
                        <button
                            onClick={() => setConfirmStopAll(true)}
                            style={{
                                padding: '0.4rem 0.75rem',
                                borderRadius: '6px',
                                border: '1px solid rgba(239, 68, 68, 0.3)',
                                background: 'rgba(239, 68, 68, 0.1)',
                                color: '#ef4444',
                                cursor: 'pointer',
                                fontSize: '0.85rem',
                                display: 'flex',
                                alignItems: 'center',
                                gap: '0.4rem',
                                transition: 'all 0.2s var(--ease-smooth)'
                            }}
                            onMouseEnter={(e) => {
                                e.currentTarget.style.background = 'rgba(239, 68, 68, 0.2)';
                            }}
                            onMouseLeave={(e) => {
                                e.currentTarget.style.background = 'rgba(239, 68, 68, 0.1)';
                            }}
                        >
                            <StopCircle size={14} />
                            Stop All Jobs
                        </button>
                        <button
                            onClick={() => setConfirmClearQueue(true)}
                            style={{
                                padding: '0.4rem 0.75rem',
                                borderRadius: '6px',
                                border: '1px solid var(--border)',
                                background: 'transparent',
                                color: 'var(--text-secondary)',
                                cursor: 'pointer',
                                fontSize: '0.85rem',
                                display: 'flex',
                                alignItems: 'center',
                                gap: '0.4rem',
                                transition: 'all 0.2s var(--ease-smooth)'
                            }}
                            onMouseEnter={(e) => {
                                e.currentTarget.style.background = 'var(--surface-hover)';
                                e.currentTarget.style.color = 'var(--text)';
                            }}
                            onMouseLeave={(e) => {
                                e.currentTarget.style.background = 'transparent';
                                e.currentTarget.style.color = 'var(--text-secondary)';
                            }}
                        >
                            <Trash2 size={14} />
                            Clear Queue
                        </button>
                    </div>
                </div>
            )}

            {/* Filter Bar */}
            <div style={{
                display: 'flex',
                alignItems: 'center',
                gap: '1rem',
                marginBottom: '1.5rem',
                flexWrap: 'wrap',
            }}>
                {/* Search Input */}
                <div style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '0.5rem',
                    padding: '0.5rem 0.75rem',
                    borderRadius: 'var(--radius)',
                    border: '1px solid var(--border)',
                    background: 'var(--surface)',
                    flex: '1',
                    maxWidth: '320px',
                }}>
                    <Search size={16} color="var(--text-secondary)" />
                    <input
                        type="text"
                        placeholder="Search test names..."
                        value={searchQuery}
                        onChange={(e) => setSearchQuery(e.target.value)}
                        style={{
                            background: 'transparent',
                            border: 'none',
                            outline: 'none',
                            color: 'var(--text)',
                            fontSize: '0.875rem',
                            width: '100%',
                        }}
                    />
                </div>

                {/* Status Filter Pills */}
                <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
                    {[
                        { value: 'all', label: 'All' },
                        { value: 'passed', label: 'Passed' },
                        { value: 'failed', label: 'Failed' },
                        { value: 'running', label: 'Running' },
                        { value: 'error', label: 'Error' },
                        { value: 'stopped', label: 'Stopped' },
                    ].map(filter => (
                        <button
                            key={filter.value}
                            onClick={() => { setStatusFilter(filter.value); setRuns([]); }}
                            style={{
                                padding: '0.35rem 0.75rem',
                                borderRadius: '999px',
                                fontSize: '0.8rem',
                                fontWeight: statusFilter === filter.value ? 600 : 500,
                                background: statusFilter === filter.value ? 'var(--primary)' : 'var(--surface)',
                                color: statusFilter === filter.value ? 'white' : 'var(--text-secondary)',
                                border: `1px solid ${statusFilter === filter.value ? 'var(--primary)' : 'var(--border)'}`,
                                cursor: 'pointer',
                                transition: 'all 0.15s',
                            }}
                        >
                            {filter.label}
                        </button>
                    ))}
                </div>
            </div>

            {runs.length === 0 ? (
                <EmptyState
                    icon={<FileText size={32} />}
                    title={statusFilter !== 'all' || debouncedSearch ? 'No matching runs' : 'No runs found yet'}
                    description={statusFilter !== 'all' || debouncedSearch ? 'Try adjusting your filters or search query.' : 'Execute your first test to see runs here.'}
                />
            ) : (
                <div className="animate-in stagger-3" style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                    {/* Show count */}
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
                        <span style={{ color: 'var(--text-secondary)', fontSize: '0.9rem' }}>
                            Showing {runs.length} of {total} runs
                        </span>
                    </div>

                    {runs.map(run => {
                        const status = getStatusConfig(run.status, run.queue_position);
                        return (
                            <Link key={run.id} href={`/runs/${run.id}`} className="list-item">
                                <div style={{ display: 'flex', alignItems: 'center', gap: '1.25rem', minWidth: 0, flex: 1 }}>
                                    <div className="status-icon-wrapper" style={{
                                        color: status.color,
                                        background: status.bg,
                                        border: `1px solid ${status.borderColor}`
                                    }}>
                                        {status.icon}
                                    </div>
                                    <div style={{ minWidth: 0 }}>
                                        <h3 style={{ fontWeight: 600, fontSize: '1.1rem', marginBottom: '0.65rem', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                            {run.test_name || 'Unnamed Test Execution'}
                                        </h3>
                                        <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', fontSize: '0.875rem', color: 'var(--text-secondary)' }}>
                                            <span style={{ fontFamily: 'var(--font-mono)', opacity: 0.7 }}>{formatRunId(run.id)}</span>
                                            <span>•</span>
                                            <span style={{ display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
                                                {getBrowserIcon(run.browser)}
                                                <span style={{ textTransform: 'capitalize' }}>{run.browser || 'chromium'}</span>
                                            </span>
                                            <span>•</span>
                                            <span style={{ display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
                                                <Clock size={14} />
                                                {formatTimestamp(run.timestamp)}
                                            </span>
                                        </div>
                                    </div>
                                </div>
                                <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', flexShrink: 0 }}>
                                    {run.total_steps > 0 ? (
                                        <div style={{
                                            display: 'flex',
                                            alignItems: 'center',
                                            justifyContent: 'flex-end',
                                            gap: '0.5rem',
                                            color: 'var(--text-secondary)',
                                            fontSize: '0.875rem',
                                            width: '120px'
                                        }}>
                                            <span style={{ fontWeight: 600, color: 'var(--text)' }}>
                                                {run.steps_completed}/{run.total_steps}
                                            </span>
                                            <span>steps</span>
                                        </div>
                                    ) : (
                                        <div style={{ width: '120px' }}></div>
                                    )}
                                    {/* Status badge with stage info for running tests */}
                                    {(() => {
                                        const stageInfo = getStageDisplay(run);
                                        if (stageInfo) {
                                            return (
                                                <div style={{
                                                    display: 'flex',
                                                    flexDirection: 'column',
                                                    alignItems: 'flex-end',
                                                    gap: '0.25rem',
                                                    minWidth: '120px'
                                                }}>
                                                    <div style={{
                                                        display: 'flex',
                                                        alignItems: 'center',
                                                        gap: '0.4rem',
                                                        padding: '0.35rem 0.75rem',
                                                        borderRadius: '999px',
                                                        fontSize: '0.85rem',
                                                        fontWeight: 600,
                                                        background: status.bg,
                                                        color: status.color,
                                                        border: `1px solid ${status.borderColor}`,
                                                        animation: 'pulse 2s ease-in-out infinite'
                                                    }}>
                                                        <span>{stageInfo.icon}</span>
                                                        <span>{stageInfo.label}</span>
                                                    </div>
                                                    {stageInfo.message && (
                                                        <span style={{
                                                            fontSize: '0.75rem',
                                                            color: 'var(--text-secondary)',
                                                            maxWidth: '180px',
                                                            whiteSpace: 'nowrap',
                                                            overflow: 'hidden',
                                                            textOverflow: 'ellipsis'
                                                        }}>
                                                            {stageInfo.message}
                                                        </span>
                                                    )}
                                                </div>
                                            );
                                        }
                                        return (
                                            <div style={{
                                                width: '100px',
                                                display: 'flex',
                                                justifyContent: 'center',
                                                padding: '0.35rem 0',
                                                borderRadius: '999px',
                                                fontSize: '0.85rem',
                                                fontWeight: 600,
                                                background: status.bg,
                                                color: status.color,
                                                border: `1px solid ${status.borderColor}`
                                            }}>
                                                {status.label}
                                            </div>
                                        );
                                    })()}

                                    {/* Stop button for running tests */}
                                    {run.canStop && (
                                        <button
                                            onClick={(e) => handleStopRun(run.id, e)}
                                            disabled={stoppingRuns.has(run.id)}
                                            title={stoppingRuns.has(run.id) ? 'Stopping...' : 'Stop test'}
                                            style={{
                                                padding: '0.4rem',
                                                borderRadius: '6px',
                                                border: '1px solid var(--danger)',
                                                background: stoppingRuns.has(run.id) ? 'var(--surface-hover)' : 'transparent',
                                                color: 'var(--danger)',
                                                cursor: stoppingRuns.has(run.id) ? 'not-allowed' : 'pointer',
                                                display: 'flex',
                                                alignItems: 'center',
                                                justifyContent: 'center',
                                                transition: 'all 0.2s',
                                                opacity: stoppingRuns.has(run.id) ? 0.5 : 1,
                                                flexShrink: 0
                                            }}
                                            onMouseEnter={(e) => {
                                                if (!stoppingRuns.has(run.id)) {
                                                    e.currentTarget.style.background = 'var(--danger-muted)';
                                                }
                                            }}
                                            onMouseLeave={(e) => {
                                                e.currentTarget.style.background = stoppingRuns.has(run.id) ? 'var(--surface-hover)' : 'transparent';
                                            }}
                                        >
                                            <StopCircle size={18} />
                                        </button>
                                    )}

                                    {/* Delete button for non-active runs */}
                                    {!['running', 'in_progress', 'queued', 'pending'].includes(run.status) && (
                                        <button
                                            onClick={(e) => handleDeleteRun(run.id, e)}
                                            disabled={deletingRuns.has(run.id)}
                                            title="Delete run"
                                            style={{
                                                padding: '0.4rem',
                                                borderRadius: '6px',
                                                border: '1px solid transparent',
                                                background: 'transparent',
                                                color: 'var(--text-secondary)',
                                                cursor: deletingRuns.has(run.id) ? 'not-allowed' : 'pointer',
                                                display: 'flex',
                                                alignItems: 'center',
                                                justifyContent: 'center',
                                                transition: 'all 0.2s',
                                                opacity: deletingRuns.has(run.id) ? 0.5 : 0.6,
                                                flexShrink: 0
                                            }}
                                            onMouseEnter={(e) => {
                                                if (!deletingRuns.has(run.id)) {
                                                    e.currentTarget.style.color = 'var(--danger)';
                                                    e.currentTarget.style.opacity = '1';
                                                }
                                            }}
                                            onMouseLeave={(e) => {
                                                e.currentTarget.style.color = 'var(--text-secondary)';
                                                e.currentTarget.style.opacity = deletingRuns.has(run.id) ? '0.5' : '0.6';
                                            }}
                                        >
                                            <Trash2 size={16} />
                                        </button>
                                    )}

                                    <ChevronRight size={20} color="var(--text-secondary)" />
                                </div>
                            </Link>
                        );
                    })}

                    {/* Load More Button */}
                    {hasMore && (
                        <div style={{ display: 'flex', justifyContent: 'center', marginTop: '1rem' }}>
                            <button
                                onClick={loadMore}
                                disabled={loadingMore}
                                className="btn btn-secondary"
                                style={{
                                    padding: '0.75rem 2rem',
                                    fontSize: '0.95rem',
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: '0.5rem'
                                }}
                            >
                                {loadingMore ? (
                                    <>
                                        <div className="loading-spinner" style={{ width: 16, height: 16 }} />
                                        Loading...
                                    </>
                                ) : (
                                    <>Load More ({total - runs.length} remaining)</>
                                )}
                            </button>
                        </div>
                    )}
                </div>
            )}

            {/* Stop Run Confirmation Modal */}
            {confirmStop && (
                <div style={{
                    position: 'fixed',
                    top: 0,
                    left: 0,
                    right: 0,
                    bottom: 0,
                    background: 'rgba(0, 0, 0, 0.5)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    zIndex: 1000,
                    backdropFilter: 'blur(4px)'
                }} onClick={() => setConfirmStop(null)}>
                    <div className="card" style={{
                        maxWidth: '450px',
                        padding: '2rem',
                        animation: 'slideUp 0.2s ease-out'
                    }} onClick={(e) => e.stopPropagation()}>
                        <div style={{
                            width: 48,
                            height: 48,
                            borderRadius: '50%',
                            background: 'var(--danger-muted)',
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            marginBottom: '1rem',
                            border: '1px solid rgba(248, 113, 113, 0.2)'
                        }}>
                            <StopCircle size={24} color="var(--danger)" />
                        </div>
                        <h3 style={{ fontSize: '1.3rem', marginBottom: '0.75rem', fontWeight: 600 }}>
                            Stop Test Run?
                        </h3>
                        <p style={{ color: 'var(--text-secondary)', marginBottom: '2rem', lineHeight: 1.6 }}>
                            This will terminate the currently running test execution. The test will be marked as stopped and any partial results will be saved.
                        </p>
                        <div style={{ display: 'flex', gap: '1rem', justifyContent: 'flex-end' }}>
                            <button
                                className="btn btn-secondary"
                                onClick={() => setConfirmStop(null)}
                                style={{ minWidth: '100px' }}
                            >
                                Cancel
                            </button>
                            <button
                                className="btn btn-primary"
                                onClick={confirmStopRun}
                                style={{
                                    minWidth: '100px',
                                    background: 'var(--danger)',
                                    borderColor: 'var(--danger)'
                                }}
                            >
                                Stop Run
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {/* Clear Queue Confirmation Modal */}
            {confirmClearQueue && (
                <div style={{
                    position: 'fixed',
                    top: 0,
                    left: 0,
                    right: 0,
                    bottom: 0,
                    background: 'rgba(0, 0, 0, 0.5)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    zIndex: 1000,
                    backdropFilter: 'blur(4px)'
                }} onClick={() => { setConfirmClearQueue(false); setIncludeRunningInClear(false); }}>
                    <div className="card" style={{
                        maxWidth: '500px',
                        padding: '2rem',
                        animation: 'slideUp 0.2s ease-out'
                    }} onClick={(e) => e.stopPropagation()}>
                        <div style={{
                            width: 48,
                            height: 48,
                            borderRadius: '50%',
                            background: 'var(--warning-muted)',
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            marginBottom: '1rem',
                            border: '1px solid rgba(251, 191, 36, 0.2)'
                        }}>
                            <Trash2 size={24} color="var(--warning)" />
                        </div>
                        <h3 style={{ fontSize: '1.3rem', marginBottom: '0.75rem', fontWeight: 600 }}>
                            Clear Queue?
                        </h3>
                        <p style={{ color: 'var(--text-secondary)', marginBottom: '1.5rem', lineHeight: 1.6 }}>
                            This will mark all queued tests as stopped. They will need to be re-run manually.
                        </p>
                        {queueStatus && queueStatus.orphaned_running_count !== undefined && queueStatus.orphaned_running_count > 0 && (
                            <label style={{
                                display: 'flex',
                                alignItems: 'center',
                                gap: '0.75rem',
                                padding: '1rem',
                                marginBottom: '1.5rem',
                                borderRadius: 'var(--radius)',
                                background: 'var(--warning-muted)',
                                border: '1px solid rgba(251, 191, 36, 0.2)',
                                cursor: 'pointer'
                            }}>
                                <input
                                    type="checkbox"
                                    checked={includeRunningInClear}
                                    onChange={(e) => setIncludeRunningInClear(e.target.checked)}
                                    style={{ width: 18, height: 18, cursor: 'pointer' }}
                                />
                                <div>
                                    <span style={{ fontWeight: 500 }}>Also clear stuck "running" entries</span>
                                    <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', margin: '0.25rem 0 0 0' }}>
                                        {queueStatus.orphaned_running_count} test(s) show as running but have no active process
                                    </p>
                                </div>
                            </label>
                        )}
                        <div style={{ display: 'flex', gap: '1rem', justifyContent: 'flex-end' }}>
                            <button
                                className="btn btn-secondary"
                                onClick={() => { setConfirmClearQueue(false); setIncludeRunningInClear(false); }}
                                style={{ minWidth: '100px' }}
                                disabled={clearingQueue}
                            >
                                Cancel
                            </button>
                            <button
                                className="btn btn-primary"
                                onClick={handleClearQueue}
                                disabled={clearingQueue}
                                style={{
                                    minWidth: '120px',
                                    background: 'var(--warning)',
                                    borderColor: 'var(--warning)',
                                    display: 'flex',
                                    alignItems: 'center',
                                    justifyContent: 'center',
                                    gap: '0.5rem'
                                }}
                            >
                                {clearingQueue ? (
                                    <>
                                        <div className="loading-spinner" style={{ width: 16, height: 16 }} />
                                        Clearing...
                                    </>
                                ) : (
                                    'Clear Queue'
                                )}
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {/* Stop All Jobs Confirmation Modal */}
            {confirmStopAll && (
                <div style={{
                    position: 'fixed',
                    inset: 0,
                    background: 'rgba(0,0,0,0.6)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    zIndex: 1000,
                }}>
                    <div style={{
                        background: 'var(--surface)',
                        borderRadius: '12px',
                        padding: '1.5rem',
                        maxWidth: '400px',
                        width: '90%',
                        border: '1px solid var(--border)',
                    }}>
                        <h3 style={{ margin: '0 0 0.75rem 0', fontSize: '1rem' }}>
                            Stop All Jobs?
                        </h3>
                        <p style={{ margin: '0 0 1rem 0', fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
                            This will stop all running test processes, cancel all autopilot sessions,
                            cancel all explorations, and clear the queue. This action cannot be undone.
                        </p>
                        <div style={{ display: 'flex', gap: '0.5rem', justifyContent: 'flex-end' }}>
                            <button
                                onClick={() => setConfirmStopAll(false)}
                                style={{
                                    padding: '0.5rem 1rem',
                                    borderRadius: '6px',
                                    border: '1px solid var(--border)',
                                    background: 'transparent',
                                    color: 'var(--text)',
                                    cursor: 'pointer',
                                }}
                            >
                                Cancel
                            </button>
                            <button
                                onClick={handleStopAll}
                                disabled={stoppingAll}
                                style={{
                                    padding: '0.5rem 1rem',
                                    borderRadius: '6px',
                                    border: 'none',
                                    background: '#ef4444',
                                    color: 'white',
                                    cursor: stoppingAll ? 'not-allowed' : 'pointer',
                                    opacity: stoppingAll ? 0.7 : 1,
                                }}
                            >
                                {stoppingAll ? 'Stopping...' : 'Stop All Jobs'}
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {/* Delete Run Confirmation Modal */}
            {confirmDelete && (
                <div style={{
                    position: 'fixed',
                    top: 0,
                    left: 0,
                    right: 0,
                    bottom: 0,
                    background: 'rgba(0, 0, 0, 0.5)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    zIndex: 1000,
                    backdropFilter: 'blur(4px)'
                }} onClick={() => setConfirmDelete(null)}>
                    <div className="card" style={{
                        maxWidth: '450px',
                        padding: '2rem',
                        animation: 'slideUp 0.2s ease-out'
                    }} onClick={(e) => e.stopPropagation()}>
                        <div style={{
                            width: 48,
                            height: 48,
                            borderRadius: '50%',
                            background: 'var(--danger-muted)',
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            marginBottom: '1rem',
                            border: '1px solid rgba(248, 113, 113, 0.2)'
                        }}>
                            <Trash2 size={24} color="var(--danger)" />
                        </div>
                        <h3 style={{ fontSize: '1.3rem', marginBottom: '0.75rem', fontWeight: 600 }}>
                            Delete Test Run?
                        </h3>
                        <p style={{ color: 'var(--text-secondary)', marginBottom: '2rem', lineHeight: 1.6 }}>
                            This will permanently delete this test run record. This action cannot be undone.
                        </p>
                        <div style={{ display: 'flex', gap: '1rem', justifyContent: 'flex-end' }}>
                            <button
                                className="btn btn-secondary"
                                onClick={() => setConfirmDelete(null)}
                                style={{ minWidth: '100px' }}
                            >
                                Cancel
                            </button>
                            <button
                                className="btn btn-primary"
                                onClick={confirmDeleteRun}
                                style={{
                                    minWidth: '100px',
                                    background: 'var(--danger)',
                                    borderColor: 'var(--danger)'
                                }}
                            >
                                Delete
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </PageLayout>
    );
}
