'use client';
import { useState, useEffect, useMemo, useCallback, useRef } from 'react';
import { Play, Search, Tag, X, CheckCircle, Clock, XCircle, RefreshCw, Zap, AlertTriangle, Layers, ChevronRight, ChevronDown, Folder, FolderOpen, Menu } from 'lucide-react';
import { useRouter, useSearchParams } from 'next/navigation';
import Link from 'next/link';
import { useProject } from '@/contexts/ProjectContext';
import { API_BASE } from '@/lib/api';
import { PageLayout } from '@/components/ui/page-layout';
import { ListPageSkeleton } from '@/components/ui/page-skeleton';

interface AutomatedSpec {
    name: string;
    path: string;
    code_path: string;
    spec_type: string;
    test_count: number;
    categories: string[];
    tags: string[];
    last_run_status: string | null;
    last_run_id: string | null;
    last_run_at: string | null;
}

interface FolderNode {
    name: string;
    path: string;
    spec_count: number;
    children: FolderNode[];
}

interface RecentBatch {
    id: string;
    name: string | null;
    status: string;
    created_at: string;
    total_tests: number;
    passed: number;
    failed: number;
    running: number;
    success_rate: number;
}

// FolderTree Component
function FolderTree({
    folders,
    selectedFolder,
    onSelectFolder,
    expandedFolders,
    onToggleExpand,
    totalSpecs
}: {
    folders: FolderNode[];
    selectedFolder: string | null;
    onSelectFolder: (folder: string | null) => void;
    expandedFolders: Set<string>;
    onToggleExpand: (folder: string) => void;
    totalSpecs: number;
}) {
    const renderNode = (node: FolderNode, depth: number = 0) => {
        const isExpanded = expandedFolders.has(node.path);
        const isSelected = selectedFolder === node.path;
        const hasChildren = node.children.length > 0;

        return (
            <div key={node.path}>
                <div
                    style={{
                        display: 'flex',
                        alignItems: 'center',
                        padding: '0.5rem 0.75rem',
                        paddingLeft: `${0.75 + depth * 1}rem`,
                        cursor: 'pointer',
                        background: isSelected ? 'var(--primary-glow)' : 'transparent',
                        borderLeft: isSelected ? '3px solid var(--primary)' : '3px solid transparent',
                        transition: 'all 0.15s',
                        gap: '0.5rem',
                        fontSize: '0.875rem'
                    }}
                    onClick={() => onSelectFolder(node.path)}
                    onMouseOver={(e) => {
                        if (!isSelected) e.currentTarget.style.background = 'var(--surface-hover)';
                    }}
                    onMouseOut={(e) => {
                        if (!isSelected) e.currentTarget.style.background = 'transparent';
                    }}
                >
                    {hasChildren ? (
                        <span
                            onClick={(e) => {
                                e.stopPropagation();
                                onToggleExpand(node.path);
                            }}
                            style={{ display: 'flex', alignItems: 'center' }}
                        >
                            {isExpanded ? (
                                <ChevronDown size={14} color="var(--text-secondary)" />
                            ) : (
                                <ChevronRight size={14} color="var(--text-secondary)" />
                            )}
                        </span>
                    ) : (
                        <span style={{ width: 14 }} />
                    )}
                    {isExpanded || isSelected ? (
                        <FolderOpen size={16} color={isSelected ? 'var(--primary)' : 'var(--text-secondary)'} />
                    ) : (
                        <Folder size={16} color="var(--text-secondary)" />
                    )}
                    <span style={{
                        flex: 1,
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                        whiteSpace: 'nowrap',
                        color: isSelected ? 'var(--primary)' : 'var(--text)',
                        fontWeight: isSelected ? 600 : 400
                    }}>
                        {node.name}
                    </span>
                    <span style={{
                        fontSize: '0.7rem',
                        padding: '0.125rem 0.4rem',
                        borderRadius: '9999px',
                        background: isSelected ? 'var(--primary)' : 'var(--surface-hover)',
                        color: isSelected ? 'white' : 'var(--text-secondary)',
                        fontWeight: 600
                    }}>
                        {node.spec_count}
                    </span>
                </div>
                {hasChildren && isExpanded && (
                    <div>
                        {node.children.map(child => renderNode(child, depth + 1))}
                    </div>
                )}
            </div>
        );
    };

    return (
        <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
            {/* All Tests option */}
            <div
                style={{
                    display: 'flex',
                    alignItems: 'center',
                    padding: '0.75rem',
                    cursor: 'pointer',
                    background: selectedFolder === null ? 'var(--primary-glow)' : 'transparent',
                    borderLeft: selectedFolder === null ? '3px solid var(--primary)' : '3px solid transparent',
                    borderBottom: '1px solid var(--border)',
                    gap: '0.5rem',
                    fontWeight: selectedFolder === null ? 600 : 500
                }}
                onClick={() => onSelectFolder(null)}
            >
                <Layers size={16} color={selectedFolder === null ? 'var(--primary)' : 'var(--text-secondary)'} />
                <span style={{ color: selectedFolder === null ? 'var(--primary)' : 'var(--text)' }}>
                    All Tests
                </span>
                <span style={{
                    marginLeft: 'auto',
                    fontSize: '0.7rem',
                    padding: '0.125rem 0.4rem',
                    borderRadius: '9999px',
                    background: selectedFolder === null ? 'var(--primary)' : 'var(--surface-hover)',
                    color: selectedFolder === null ? 'white' : 'var(--text-secondary)',
                    fontWeight: 600
                }}>
                    {totalSpecs}
                </span>
            </div>
            {/* Folder list */}
            <div style={{ flex: 1, overflowY: 'auto' }}>
                {folders.map(folder => renderNode(folder))}
            </div>
        </div>
    );
}

export default function RegressionPage() {
    const router = useRouter();
    const searchParams = useSearchParams();
    const { currentProject, isLoading: projectLoading } = useProject();

    // Core state
    const [specs, setSpecs] = useState<AutomatedSpec[]>([]);
    const [loading, setLoading] = useState(true);
    const [searchTerm, setSearchTerm] = useState('');
    const [selectedTags, setSelectedTags] = useState<string[]>([]);
    const [selectedSpecs, setSelectedSpecs] = useState<Set<string>>(new Set());
    const [selectedBrowser, setSelectedBrowser] = useState('chromium');
    const [hybridHealing, setHybridHealing] = useState(false);
    const [running, setRunning] = useState(false);
    const [recentBatches, setRecentBatches] = useState<RecentBatch[]>([]);

    // Folder tree state
    const [folders, setFolders] = useState<FolderNode[]>([]);
    const [totalSpecs, setTotalSpecs] = useState(0);
    const [selectedFolder, setSelectedFolder] = useState<string | null>(null);
    const [expandedFolders, setExpandedFolders] = useState<Set<string>>(new Set());
    const [sidebarOpen, setSidebarOpen] = useState(true);

    // Pagination state
    const [offset, setOffset] = useState(0);
    const [hasMore, setHasMore] = useState(true);
    const [isLoadingMore, setIsLoadingMore] = useState(false);
    const [totalFiltered, setTotalFiltered] = useState(0);
    const loadMoreRef = useRef<HTMLDivElement>(null);
    const LIMIT = 50;

    // Initialize from URL params
    useEffect(() => {
        const folderParam = searchParams.get('folder');
        if (folderParam) {
            setSelectedFolder(folderParam);
            // Auto-expand parent folders
            const parts = folderParam.split('/');
            const expanded = new Set<string>();
            for (let i = 0; i < parts.length; i++) {
                expanded.add(parts.slice(0, i + 1).join('/'));
            }
            setExpandedFolders(expanded);
        }
    }, [searchParams]);

    // Fetch folder tree when project changes
    useEffect(() => {
        if (!projectLoading) {
            fetchFolders();
        }
    }, [currentProject?.id, projectLoading]);

    // Fetch recent batches when project changes
    useEffect(() => {
        if (!projectLoading) {
            fetchRecentBatches();
        }
    }, [currentProject?.id, projectLoading]);

    // Fetch specs when folder/tags/search/project changes (reset pagination)
    // Wait for project context to finish loading before fetching
    useEffect(() => {
        // Don't fetch until project context is ready
        if (projectLoading) {
            return;
        }

        setSpecs([]);
        setOffset(0);
        setHasMore(true);
        fetchSpecs(0, true);

        // Update URL
        const url = new URL(window.location.href);
        if (selectedFolder) {
            url.searchParams.set('folder', selectedFolder);
        } else {
            url.searchParams.delete('folder');
        }
        window.history.replaceState({}, '', url.toString());
    }, [selectedFolder, selectedTags, currentProject?.id, projectLoading]);

    // Intersection Observer for infinite scroll
    useEffect(() => {
        const observer = new IntersectionObserver(
            (entries) => {
                if (entries[0].isIntersecting && hasMore && !isLoadingMore && !loading) {
                    loadMore();
                }
            },
            { threshold: 0.1 }
        );

        if (loadMoreRef.current) {
            observer.observe(loadMoreRef.current);
        }

        return () => observer.disconnect();
    }, [hasMore, isLoadingMore, loading, offset]);

    const fetchFolders = async () => {
        try {
            let url = `${API_BASE}/specs/folders`;
            if (currentProject?.id) {
                url += `?project_id=${encodeURIComponent(currentProject.id)}`;
            }
            const res = await fetch(url);
            const data = await res.json();
            setFolders(data.folders || []);
            setTotalSpecs(data.total_specs || 0);
        } catch (err) {
            console.error('Failed to fetch folders:', err);
        }
    };

    const fetchSpecs = async (newOffset: number, reset: boolean = false) => {
        if (reset) {
            setLoading(true);
        } else {
            setIsLoadingMore(true);
        }

        try {
            const params = new URLSearchParams();
            params.set('limit', LIMIT.toString());
            params.set('offset', newOffset.toString());
            if (selectedFolder) {
                params.set('folder', selectedFolder);
            }
            if (selectedTags.length > 0) {
                params.set('tags', selectedTags.join(','));
            }
            if (currentProject?.id) {
                params.set('project_id', currentProject.id);
            }

            const res = await fetch(`${API_BASE}/specs/automated?${params}`);
            const data = await res.json();

            if (reset) {
                setSpecs(data.specs || []);
            } else {
                setSpecs(prev => [...prev, ...(data.specs || [])]);
            }

            setHasMore(data.has_more);
            setTotalFiltered(data.total);
            setOffset(newOffset + LIMIT);
        } catch (err) {
            console.error('Failed to fetch specs:', err);
        } finally {
            setLoading(false);
            setIsLoadingMore(false);
        }
    };

    const loadMore = useCallback(() => {
        if (!isLoadingMore && hasMore) {
            fetchSpecs(offset, false);
        }
    }, [offset, isLoadingMore, hasMore]);

    const fetchRecentBatches = async () => {
        try {
            let url = `${API_BASE}/regression/batches?limit=3`;
            if (currentProject?.id) {
                url += `&project_id=${encodeURIComponent(currentProject.id)}`;
            }
            const res = await fetch(url);
            const data = await res.json();
            setRecentBatches(data.batches || []);
        } catch (err) {
            console.error('Failed to fetch recent batches:', err);
        }
    };

    // Get all unique tags from loaded specs
    const allTags = useMemo(() => {
        const tags = new Set<string>();
        specs.forEach(spec => {
            spec.tags?.forEach(tag => tags.add(tag));
        });
        return Array.from(tags).sort();
    }, [specs]);

    // Count specs per tag (from loaded specs)
    const tagCounts = useMemo(() => {
        const counts: Record<string, number> = {};
        allTags.forEach(tag => {
            counts[tag] = specs.filter(s => s.tags?.includes(tag)).length;
        });
        return counts;
    }, [specs, allTags]);

    // Filter specs based on search (client-side for loaded specs)
    const filteredSpecs = useMemo(() => {
        return specs.filter(s => s.name.toLowerCase().includes(searchTerm.toLowerCase()));
    }, [specs, searchTerm]);

    const toggleTagFilter = (tag: string) => {
        if (selectedTags.includes(tag)) {
            setSelectedTags(selectedTags.filter(t => t !== tag));
        } else {
            setSelectedTags([...selectedTags, tag]);
        }
        setSelectedSpecs(new Set()); // Clear selection on filter change
    };

    const toggleSpecSelection = (specName: string) => {
        const next = new Set(selectedSpecs);
        if (next.has(specName)) {
            next.delete(specName);
        } else {
            next.add(specName);
        }
        setSelectedSpecs(next);
    };

    const selectAll = () => {
        setSelectedSpecs(new Set(filteredSpecs.map(s => s.name)));
    };

    const clearSelection = () => {
        setSelectedSpecs(new Set());
    };

    const handleFolderSelect = (folder: string | null) => {
        setSelectedFolder(folder);
        setSelectedSpecs(new Set()); // Clear selection on folder change
    };

    const toggleFolderExpand = (folder: string) => {
        const next = new Set(expandedFolders);
        if (next.has(folder)) {
            next.delete(folder);
        } else {
            next.add(folder);
        }
        setExpandedFolders(next);
    };

    const runTests = async (specsToRun: string[]) => {
        if (specsToRun.length === 0) {
            alert('No tests to run');
            return;
        }

        setRunning(true);
        try {
            const res = await fetch(`${API_BASE}/runs/bulk`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    spec_names: specsToRun,
                    browser: selectedBrowser,
                    hybrid: hybridHealing,
                    project_id: currentProject?.id
                })
            });

            const data = await res.json();
            if (data.batch_id) {
                clearSelection();
                router.push(`/regression/batches/${data.batch_id}`);
            } else if (data.run_ids) {
                clearSelection();
                router.push('/runs');
            } else if (data.detail) {
                alert(`Error: ${data.detail}`);
            }
        } catch (e) {
            console.error('Failed to start regression tests:', e);
            alert('Failed to start regression tests');
        } finally {
            setRunning(false);
        }
    };

    const runFiltered = () => runTests(filteredSpecs.map(s => s.name));
    const runSelected = () => runTests(Array.from(selectedSpecs));

    const getStatusIcon = (status: string | null) => {
        switch (status) {
            case 'passed':
            case 'completed':
                return <CheckCircle size={16} color="var(--success)" />;
            case 'failed':
                return <XCircle size={16} color="var(--danger)" />;
            case 'running':
            case 'in_progress':
                return <RefreshCw size={16} color="var(--primary)" className="spin" />;
            default:
                return <Clock size={16} color="var(--text-secondary)" />;
        }
    };

    const formatTimestamp = (timestamp: string | null) => {
        if (!timestamp) return 'Never';
        const date = new Date(timestamp);
        const now = new Date();
        const diffMs = now.getTime() - date.getTime();
        const diffMins = Math.floor(diffMs / 60000);
        const diffHours = Math.floor(diffMs / 3600000);
        const diffDays = Math.floor(diffMs / 86400000);

        if (diffMins < 1) return 'Just now';
        if (diffMins < 60) return `${diffMins}m ago`;
        if (diffHours < 24) return `${diffHours}h ago`;
        return `${diffDays}d ago`;
    };

    // Get display name based on folder selection
    const getDisplayName = (name: string) => {
        if (selectedFolder && name.startsWith(selectedFolder + '/')) {
            return name.substring(selectedFolder.length + 1);
        }
        return name;
    };

    if ((loading || projectLoading) && specs.length === 0) {
        return (
            <PageLayout tier="full" style={{ paddingTop: 0 }}>
                <ListPageSkeleton rows={8} />
            </PageLayout>
        );
    }

    return (
        <PageLayout tier="full" style={{ display: 'flex', height: 'calc(100vh - 60px)', overflow: 'hidden', paddingTop: 0 }}>
            {/* Sidebar */}
            <aside style={{
                width: sidebarOpen ? 260 : 0,
                minWidth: sidebarOpen ? 260 : 0,
                borderRight: sidebarOpen ? '1px solid var(--border)' : 'none',
                background: 'var(--surface)',
                transition: 'all 0.2s',
                overflow: 'hidden',
                display: 'flex',
                flexDirection: 'column'
            }}>
                <div style={{
                    padding: '1rem',
                    borderBottom: '1px solid var(--border)',
                    fontWeight: 600,
                    fontSize: '0.85rem',
                    color: 'var(--text-secondary)',
                    textTransform: 'uppercase',
                    letterSpacing: '0.05em',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '0.5rem'
                }}>
                    <Folder size={16} />
                    Folders
                </div>
                <FolderTree
                    folders={folders}
                    selectedFolder={selectedFolder}
                    onSelectFolder={handleFolderSelect}
                    expandedFolders={expandedFolders}
                    onToggleExpand={toggleFolderExpand}
                    totalSpecs={totalSpecs}
                />
            </aside>

            {/* Main Content */}
            <main style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
                {/* Header */}
                <header className="animate-in stagger-1" style={{ padding: '1.5rem', borderBottom: '1px solid var(--border)' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '1rem' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
                            <button
                                onClick={() => setSidebarOpen(!sidebarOpen)}
                                style={{
                                    background: 'none',
                                    border: '1px solid var(--border)',
                                    borderRadius: '6px',
                                    padding: '0.5rem',
                                    cursor: 'pointer',
                                    display: 'flex',
                                    alignItems: 'center',
                                    justifyContent: 'center'
                                }}
                                title={sidebarOpen ? 'Hide folders' : 'Show folders'}
                            >
                                <Menu size={18} color="var(--text-secondary)" />
                            </button>
                            <div>
                                <h1 style={{ fontSize: '1.5rem', fontWeight: 700, marginBottom: '0.25rem' }}>
                                    Regression Testing
                                </h1>
                                <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem' }}>
                                    {selectedFolder ? (
                                        <>
                                            <span style={{ opacity: 0.7 }}>Folder: </span>
                                            <span style={{ fontWeight: 500 }}>{selectedFolder}</span>
                                            <span style={{ opacity: 0.7 }}> • </span>
                                        </>
                                    ) : null}
                                    {totalFiltered} tests{hasMore ? '+' : ''}
                                    {selectedSpecs.size > 0 && (
                                        <span style={{ color: 'var(--primary)', fontWeight: 500 }}>
                                            {' • '}{selectedSpecs.size} selected
                                        </span>
                                    )}
                                </p>
                            </div>
                        </div>
                        <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center' }}>
                            <select
                                value={selectedBrowser}
                                onChange={(e) => setSelectedBrowser(e.target.value)}
                                className="input"
                                style={{ padding: '0.5rem 1rem', width: 'auto' }}
                            >
                                <option value="chromium">Chrome</option>
                                <option value="firefox">Firefox</option>
                                <option value="webkit">Safari</option>
                            </select>
                            <button
                                className="btn"
                                onClick={() => setHybridHealing(!hybridHealing)}
                                style={{
                                    background: hybridHealing ? 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)' : 'var(--surface-hover)',
                                    color: hybridHealing ? 'white' : 'var(--text)',
                                    border: hybridHealing ? 'none' : '1px solid var(--border)'
                                }}
                                title={hybridHealing ? 'Extended Recovery Mode' : 'Automated Repair Mode'}
                            >
                                <Zap size={16} />
                                {hybridHealing ? 'Extended' : 'Standard'}
                            </button>
                        </div>
                    </div>

                    {/* Tag Filters */}
                    {allTags.length > 0 && (
                        <div style={{ marginBottom: '1rem' }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.5rem' }}>
                                <Tag size={14} color="var(--text-secondary)" />
                                <span style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Filter by tags:</span>
                            </div>
                            <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
                                {allTags.map(tag => {
                                    const isSelected = selectedTags.includes(tag);
                                    return (
                                        <button
                                            key={tag}
                                            onClick={() => toggleTagFilter(tag)}
                                            style={{
                                                padding: '0.375rem 0.75rem',
                                                borderRadius: '9999px',
                                                border: isSelected ? '2px solid var(--primary)' : '1px solid var(--border)',
                                                background: isSelected ? 'var(--primary-glow)' : 'transparent',
                                                color: isSelected ? 'var(--primary)' : 'var(--text-secondary)',
                                                fontSize: '0.8rem',
                                                fontWeight: 500,
                                                cursor: 'pointer',
                                                display: 'flex',
                                                alignItems: 'center',
                                                gap: '0.25rem'
                                            }}
                                        >
                                            {tag}
                                            <span style={{
                                                padding: '0 0.3rem',
                                                borderRadius: '9999px',
                                                background: isSelected ? 'var(--primary)' : 'var(--surface-hover)',
                                                color: isSelected ? 'white' : 'var(--text-secondary)',
                                                fontSize: '0.65rem',
                                                fontWeight: 600
                                            }}>
                                                {tagCounts[tag]}
                                            </span>
                                            {isSelected && <X size={12} />}
                                        </button>
                                    );
                                })}
                            </div>
                        </div>
                    )}

                    {/* Search and Actions */}
                    <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center' }}>
                        <div className="input-group" style={{ flex: 1 }}>
                            <div className="input-icon">
                                <Search size={18} />
                            </div>
                            <input
                                type="text"
                                placeholder="Search tests..."
                                value={searchTerm}
                                onChange={(e) => setSearchTerm(e.target.value)}
                                className="input has-icon"
                            />
                        </div>
                        <button
                            className="btn btn-primary"
                            onClick={runFiltered}
                            disabled={running || filteredSpecs.length === 0}
                            style={{ whiteSpace: 'nowrap' }}
                        >
                            <Play size={16} fill="currentColor" />
                            Run All ({filteredSpecs.length})
                        </button>
                    </div>
                </header>

                {/* Test List with infinite scroll */}
                <div style={{ flex: 1, overflow: 'auto' }}>
                    {/* Table Header */}
                    <div style={{
                        display: 'flex',
                        alignItems: 'center',
                        padding: '0.625rem 1rem',
                        borderBottom: '1px solid var(--border)',
                        background: 'var(--surface)',
                        fontSize: '0.75rem',
                        fontWeight: 600,
                        color: 'var(--text-secondary)',
                        textTransform: 'uppercase',
                        letterSpacing: '0.05em',
                        position: 'sticky',
                        top: 0,
                        zIndex: 10
                    }}>
                        <div style={{ width: 36, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                            <input
                                type="checkbox"
                                checked={selectedSpecs.size === filteredSpecs.length && filteredSpecs.length > 0}
                                onChange={() => selectedSpecs.size === filteredSpecs.length ? clearSelection() : selectAll()}
                                style={{ accentColor: 'var(--primary)' }}
                            />
                        </div>
                        <div style={{ flex: 1 }}>Test Name</div>
                        <div style={{ width: 140, textAlign: 'center' }}>Tags</div>
                        <div style={{ width: 90, textAlign: 'center' }}>Last Run</div>
                        <div style={{ width: 70, textAlign: 'center' }}>Status</div>
                    </div>

                    {filteredSpecs.length === 0 && !loading ? (
                        <div style={{ padding: '3rem', textAlign: 'center', color: 'var(--text-secondary)' }}>
                            <AlertTriangle size={32} style={{ marginBottom: '1rem', opacity: 0.5 }} />
                            <p>No automated tests found matching your criteria.</p>
                        </div>
                    ) : (
                        <>
                            {filteredSpecs.map(spec => {
                                const isSelected = selectedSpecs.has(spec.name);
                                return (
                                    <div
                                        key={spec.name}
                                        style={{
                                            display: 'flex',
                                            alignItems: 'center',
                                            padding: '0.625rem 1rem',
                                            borderBottom: '1px solid var(--border)',
                                            background: isSelected ? 'rgba(59, 130, 246, 0.04)' : 'transparent',
                                            cursor: 'pointer',
                                            transition: 'background 0.15s'
                                        }}
                                        onClick={() => toggleSpecSelection(spec.name)}
                                        onMouseOver={(e) => {
                                            if (!isSelected) e.currentTarget.style.background = 'var(--surface-hover)';
                                        }}
                                        onMouseOut={(e) => {
                                            e.currentTarget.style.background = isSelected ? 'rgba(59, 130, 246, 0.04)' : 'transparent';
                                        }}
                                    >
                                        <div style={{ width: 36, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                                            <input
                                                type="checkbox"
                                                checked={isSelected}
                                                onChange={() => toggleSpecSelection(spec.name)}
                                                onClick={(e) => e.stopPropagation()}
                                                style={{ accentColor: 'var(--primary)' }}
                                            />
                                        </div>
                                        <div style={{ flex: 1, minWidth: 0 }}>
                                            <Link
                                                href={`/specs/${spec.name}`}
                                                onClick={(e) => e.stopPropagation()}
                                                style={{
                                                    color: 'var(--text)',
                                                    textDecoration: 'none',
                                                    fontWeight: 500,
                                                    fontSize: '0.9rem',
                                                    display: 'block',
                                                    overflow: 'hidden',
                                                    textOverflow: 'ellipsis',
                                                    whiteSpace: 'nowrap'
                                                }}
                                                title={spec.name}
                                            >
                                                {getDisplayName(spec.name)}
                                            </Link>
                                        </div>
                                        <div style={{ width: 140, display: 'flex', gap: '0.25rem', flexWrap: 'wrap', justifyContent: 'center' }}>
                                            {spec.tags?.slice(0, 2).map(tag => (
                                                <span
                                                    key={tag}
                                                    style={{
                                                        fontSize: '0.65rem',
                                                        padding: '0.1rem 0.4rem',
                                                        borderRadius: '9999px',
                                                        background: 'var(--primary-glow)',
                                                        color: 'var(--primary)',
                                                        fontWeight: 500
                                                    }}
                                                >
                                                    {tag}
                                                </span>
                                            ))}
                                            {(spec.tags?.length || 0) > 2 && (
                                                <span style={{ fontSize: '0.65rem', color: 'var(--text-secondary)' }}>
                                                    +{(spec.tags?.length || 0) - 2}
                                                </span>
                                            )}
                                        </div>
                                        <div style={{ width: 90, textAlign: 'center', fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                                            {formatTimestamp(spec.last_run_at)}
                                        </div>
                                        <div style={{ width: 70, display: 'flex', justifyContent: 'center' }}>
                                            {getStatusIcon(spec.last_run_status)}
                                        </div>
                                    </div>
                                );
                            })}

                            {/* Load More Sentinel */}
                            <div ref={loadMoreRef} style={{ padding: '1rem', textAlign: 'center' }}>
                                {isLoadingMore && (
                                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '0.5rem', color: 'var(--text-secondary)' }}>
                                        <div className="loading-spinner" style={{ width: 20, height: 20 }}></div>
                                        <span>Loading more...</span>
                                    </div>
                                )}
                                {!hasMore && specs.length > 0 && (
                                    <span style={{ color: 'var(--text-secondary)', fontSize: '0.85rem' }}>
                                        All {totalFiltered} tests loaded
                                    </span>
                                )}
                            </div>
                        </>
                    )}
                </div>

                {/* Recent Batches (shown when sidebar is collapsed or on smaller screens) */}
                {recentBatches.length > 0 && (
                    <div style={{
                        borderTop: '1px solid var(--border)',
                        padding: '1rem',
                        background: 'var(--surface)'
                    }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.75rem' }}>
                            <h3 style={{ fontSize: '0.85rem', fontWeight: 600, color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                                <Layers size={14} />
                                Recent Batches
                            </h3>
                            <Link
                                href="/regression/batches"
                                style={{
                                    fontSize: '0.8rem',
                                    color: 'var(--primary)',
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: '0.25rem'
                                }}
                            >
                                View All <ChevronRight size={12} />
                            </Link>
                        </div>
                        <div style={{ display: 'flex', gap: '0.75rem', overflowX: 'auto' }}>
                            {recentBatches.map(batch => (
                                <Link
                                    key={batch.id}
                                    href={`/regression/batches/${batch.id}`}
                                    style={{
                                        padding: '0.75rem 1rem',
                                        borderRadius: '8px',
                                        border: '1px solid var(--border)',
                                        background: 'var(--background)',
                                        textDecoration: 'none',
                                        display: 'flex',
                                        alignItems: 'center',
                                        gap: '0.75rem',
                                        color: 'var(--text)',
                                        minWidth: '200px',
                                        flexShrink: 0
                                    }}
                                >
                                    {batch.status === 'completed' ? (
                                        <CheckCircle size={18} color={batch.failed > 0 ? 'var(--warning)' : 'var(--success)'} />
                                    ) : batch.status === 'running' ? (
                                        <RefreshCw size={18} color="var(--primary)" className="spin" />
                                    ) : (
                                        <Clock size={18} color="var(--text-secondary)" />
                                    )}
                                    <div style={{ flex: 1, minWidth: 0 }}>
                                        <div style={{ fontWeight: 600, fontSize: '0.85rem', marginBottom: '0.125rem', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                            {batch.name || batch.id.slice(0, 8)}
                                        </div>
                                        <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
                                            {batch.passed}/{batch.total_tests} passed
                                        </div>
                                    </div>
                                    {batch.status === 'completed' && (
                                        <span style={{
                                            padding: '0.2rem 0.5rem',
                                            borderRadius: '9999px',
                                            background: batch.success_rate >= 90 ? 'var(--success-muted)' : batch.success_rate >= 70 ? 'var(--warning-muted)' : 'var(--danger-muted)',
                                            color: batch.success_rate >= 90 ? 'var(--success)' : batch.success_rate >= 70 ? 'var(--warning)' : 'var(--danger)',
                                            fontWeight: 600,
                                            fontSize: '0.75rem'
                                        }}>
                                            {batch.success_rate}%
                                        </span>
                                    )}
                                </Link>
                            ))}
                        </div>
                    </div>
                )}
            </main>

            {/* Selection Action Bar */}
            {selectedSpecs.size > 0 && (
                <div style={{
                    position: 'fixed',
                    bottom: '1.5rem',
                    left: '50%',
                    transform: 'translateX(-50%)',
                    background: 'var(--surface)',
                    border: '1px solid var(--success)',
                    borderRadius: '12px',
                    padding: '0.875rem 1.5rem',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '1.5rem',
                    boxShadow: '0 20px 25px -5px rgba(0, 0, 0, 0.3)',
                    zIndex: 100,
                    animation: 'slideUp 0.3s ease-out'
                }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                        <span style={{
                            background: 'var(--success)',
                            color: 'white',
                            padding: '0.15rem 0.5rem',
                            borderRadius: '6px',
                            fontWeight: 700,
                            fontSize: '0.85rem'
                        }}>
                            {selectedSpecs.size}
                        </span>
                        <span style={{ fontWeight: 600, fontSize: '0.9rem' }}>
                            Tests Selected
                            {hasMore && <span style={{ color: 'var(--text-secondary)', fontWeight: 400 }}> (of {filteredSpecs.length} loaded)</span>}
                        </span>
                    </div>

                    <div style={{ height: '20px', width: '1px', background: 'var(--border)' }}></div>

                    <div style={{ display: 'flex', gap: '0.75rem' }}>
                        <button
                            className="btn btn-secondary"
                            onClick={clearSelection}
                            style={{ padding: '0.4rem 0.875rem', fontSize: '0.85rem' }}
                        >
                            Clear
                        </button>
                        <button
                            className="btn"
                            onClick={runSelected}
                            disabled={running}
                            style={{
                                background: 'var(--success)',
                                color: 'white',
                                display: 'flex',
                                alignItems: 'center',
                                gap: '0.4rem',
                                padding: '0.4rem 0.875rem',
                                fontSize: '0.85rem'
                            }}
                        >
                            <Play size={14} fill="currentColor" />
                            Run Selected
                        </button>
                    </div>
                </div>
            )}

            <style jsx>{`
                @keyframes slideUp {
                    from { transform: translate(-50%, 100%); opacity: 0; }
                    to { transform: translate(-50%, 0); opacity: 1; }
                }
                .spin {
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
