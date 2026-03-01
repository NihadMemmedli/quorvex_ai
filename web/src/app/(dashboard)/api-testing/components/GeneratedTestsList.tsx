'use client';
import React, { useState, useCallback, useRef, useEffect } from 'react';
import dynamic from 'next/dynamic';
import {
    Play, Loader2, ChevronDown, ChevronRight, RefreshCw, Edit2, Save, X, Search,
    CheckCircle, XCircle, MoreVertical, Trash2, Copy, Circle,
} from 'lucide-react';
import { API_BASE } from '@/lib/api';
import { GeneratedTest, GeneratedTestsSummary, JobStatus } from './types';

const CodeEditor = dynamic(() => import('@/components/CodeEditor'), { ssr: false });

interface GeneratedTestsListProps {
    generatedTests: GeneratedTest[];
    testsLoading: boolean;
    fetchGeneratedTests: (offset?: number, append?: boolean, search?: string, sort?: string, statusFilter?: string) => Promise<void>;
    expandedTest: string | null;
    setExpandedTest: (name: string | null) => void;
    setMessage: (msg: { type: 'success' | 'error'; text: string } | null) => void;
    testsTotal: number;
    testsHasMore: boolean;
    projectId: string;
    activeJobs: Record<string, JobStatus>;
    setActiveJobs: React.Dispatch<React.SetStateAction<Record<string, JobStatus>>>;
    pollJob: (jobId: string, onComplete?: () => void) => void;
    fetchApiRuns: (offset?: number) => void;
}

type SortOption = 'modified' | 'name' | 'status' | 'last_run' | 'size';
type StatusFilter = 'all' | 'passed' | 'failed' | 'not_run';

const SORT_OPTIONS: { value: SortOption; label: string }[] = [
    { value: 'modified', label: 'Last Modified' },
    { value: 'name', label: 'Name' },
    { value: 'status', label: 'Status' },
    { value: 'last_run', label: 'Last Run' },
    { value: 'size', label: 'Size' },
];

function relativeTime(dateStr?: string | null): string {
    if (!dateStr) return '\u2014';
    const diff = Date.now() - new Date(dateStr).getTime();
    const mins = Math.floor(diff / 60000);
    if (mins < 1) return 'just now';
    if (mins < 60) return `${mins}m ago`;
    const hours = Math.floor(mins / 60);
    if (hours < 24) return `${hours}h ago`;
    const days = Math.floor(hours / 24);
    return `${days}d ago`;
}

function StatusDot({ status }: { status: 'passed' | 'failed' | 'running' | null }) {
    if (status === 'running') return <Loader2 size={14} style={{ color: 'var(--warning)', animation: 'spin 1s linear infinite' }} />;
    if (status === 'passed') return <CheckCircle size={14} style={{ color: 'var(--success)' }} />;
    if (status === 'failed') return <XCircle size={14} style={{ color: 'var(--danger)' }} />;
    return <Circle size={14} style={{ color: 'var(--text-secondary)', opacity: 0.4 }} />;
}

export default React.memo(function GeneratedTestsList({
    generatedTests,
    testsLoading,
    fetchGeneratedTests,
    expandedTest,
    setExpandedTest,
    setMessage,
    testsTotal,
    testsHasMore,
    projectId,
    activeJobs,
    setActiveJobs,
    pollJob,
    fetchApiRuns,
}: GeneratedTestsListProps) {
    // Existing state
    const [testContents, setTestContents] = useState<Record<string, string>>({});
    const [editingTest, setEditingTest] = useState<string | null>(null);
    const [editTestContent, setEditTestContent] = useState('');
    const [savingTest, setSavingTest] = useState(false);

    // New state
    const [testsSearch, setTestsSearch] = useState('');
    const [sortBy, setSortBy] = useState<SortOption>('modified');
    const [statusFilter, setStatusFilter] = useState<StatusFilter>('all');
    const [selectedTests, setSelectedTests] = useState<Set<string>>(new Set());
    const [summary, setSummary] = useState<GeneratedTestsSummary | null>(null);
    const [runningTests, setRunningTests] = useState<Record<string, string>>({}); // testPath -> jobId
    const [menuOpen, setMenuOpen] = useState<string | null>(null);
    const [currentOffset, setCurrentOffset] = useState(0);

    const searchTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
    const menuRef = useRef<HTMLDivElement>(null);

    // Fetch summary
    const fetchSummary = useCallback(async () => {
        try {
            const res = await fetch(`${API_BASE}/api-testing/generated-tests/summary?project_id=${projectId}`);
            if (res.ok) setSummary(await res.json());
        } catch { /* ignore */ }
    }, [projectId]);

    useEffect(() => { fetchSummary(); }, [fetchSummary]);

    // Close menu on outside click
    useEffect(() => {
        const handler = (e: MouseEvent) => {
            if (menuRef.current && !menuRef.current.contains(e.target as Node)) setMenuOpen(null);
        };
        if (menuOpen) document.addEventListener('mousedown', handler);
        return () => document.removeEventListener('mousedown', handler);
    }, [menuOpen]);

    // Refresh helper
    const refreshTests = useCallback((newOffset = 0, append = false) => {
        setCurrentOffset(newOffset);
        fetchGeneratedTests(
            newOffset, append,
            testsSearch || undefined,
            sortBy,
            statusFilter === 'all' ? undefined : statusFilter,
        );
    }, [fetchGeneratedTests, testsSearch, sortBy, statusFilter]);

    const handleSearchChange = useCallback((value: string) => {
        setTestsSearch(value);
        if (searchTimeoutRef.current) clearTimeout(searchTimeoutRef.current);
        searchTimeoutRef.current = setTimeout(() => {
            setCurrentOffset(0);
            fetchGeneratedTests(0, false, value || undefined, sortBy, statusFilter === 'all' ? undefined : statusFilter);
        }, 300);
    }, [fetchGeneratedTests, sortBy, statusFilter]);

    const handleSortChange = useCallback((newSort: SortOption) => {
        setSortBy(newSort);
        setCurrentOffset(0);
        fetchGeneratedTests(0, false, testsSearch || undefined, newSort, statusFilter === 'all' ? undefined : statusFilter);
    }, [fetchGeneratedTests, testsSearch, statusFilter]);

    const handleStatusFilterChange = useCallback((newFilter: StatusFilter) => {
        const resolved = newFilter === 'all' ? 'all' : (newFilter === statusFilter ? 'all' : newFilter);
        setStatusFilter(resolved);
        setCurrentOffset(0);
        setSelectedTests(new Set());
        fetchGeneratedTests(0, false, testsSearch || undefined, sortBy, resolved === 'all' ? undefined : resolved);
    }, [fetchGeneratedTests, testsSearch, sortBy, statusFilter]);

    const handleLoadMore = useCallback(() => {
        const newOffset = currentOffset + 20;
        setCurrentOffset(newOffset);
        fetchGeneratedTests(newOffset, true, testsSearch || undefined, sortBy, statusFilter === 'all' ? undefined : statusFilter);
    }, [fetchGeneratedTests, currentOffset, testsSearch, sortBy, statusFilter]);

    // Test content loading
    const loadTestContent = async (name: string) => {
        if (testContents[name]) return;
        try {
            const res = await fetch(`${API_BASE}/api-testing/generated-tests/${name}?project_id=${projectId}`);
            if (res.ok) {
                const data = await res.json();
                setTestContents(prev => ({ ...prev, [name]: data.content }));
            }
        } catch { console.error('Failed to load test content'); }
    };

    const handleSaveTest = async (testName: string) => {
        setSavingTest(true);
        try {
            const res = await fetch(`${API_BASE}/api-testing/generated-tests/${testName}?project_id=${projectId}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ content: editTestContent }),
            });
            if (res.ok) {
                setTestContents(prev => ({ ...prev, [testName]: editTestContent }));
                setEditingTest(null);
                setMessage({ type: 'success', text: 'Test file saved successfully' });
            } else {
                const err = await res.json();
                setMessage({ type: 'error', text: err.detail || 'Failed to save test file' });
            }
        } catch { setMessage({ type: 'error', text: 'Failed to save test file' }); }
        finally { setSavingTest(false); }
    };

    // Run a single test
    const handleRunTest = useCallback(async (test: GeneratedTest) => {
        try {
            const res = await fetch(`${API_BASE}/api-testing/run-direct`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    test_path: test.path,
                    spec_name: test.source_spec || test.name,
                    project_id: projectId,
                }),
            });
            if (res.ok) {
                const data = await res.json();
                setRunningTests(prev => ({ ...prev, [test.path]: data.job_id }));
                setActiveJobs(prev => ({ ...prev, [data.job_id]: { job_id: data.job_id, status: 'running', message: data.message } }));
                pollJob(data.job_id, () => {
                    setRunningTests(prev => { const next = { ...prev }; delete next[test.path]; return next; });
                    refreshTests(0);
                    fetchSummary();
                    fetchApiRuns(0);
                });
            } else {
                const err = await res.json();
                setMessage({ type: 'error', text: err.detail || 'Failed to start test' });
            }
        } catch { setMessage({ type: 'error', text: 'Failed to start test run' }); }
    }, [projectId, setActiveJobs, pollJob, refreshTests, fetchSummary, fetchApiRuns, setMessage]);

    // Run selected tests
    const handleRunSelected = useCallback(async () => {
        const testsToRun = generatedTests.filter(t => selectedTests.has(t.path));
        if (testsToRun.length === 0) return;
        setMessage({ type: 'success', text: `Starting ${testsToRun.length} test run(s)...` });
        for (const test of testsToRun) {
            await handleRunTest(test);
        }
        setSelectedTests(new Set());
    }, [generatedTests, selectedTests, handleRunTest, setMessage]);

    // Run all visible tests
    const handleRunAll = useCallback(async () => {
        if (generatedTests.length === 0) return;
        setMessage({ type: 'success', text: `Starting ${generatedTests.length} test run(s)...` });
        for (const test of generatedTests) {
            await handleRunTest(test);
        }
    }, [generatedTests, handleRunTest, setMessage]);

    // Delete test
    const handleDeleteTest = useCallback(async (test: GeneratedTest) => {
        if (!confirm(`Delete ${test.name}? This cannot be undone.`)) return;
        try {
            const res = await fetch(`${API_BASE}/api-testing/generated-tests/${test.name}?project_id=${projectId}`, { method: 'DELETE' });
            if (res.ok) {
                setMessage({ type: 'success', text: `Deleted ${test.name}` });
                refreshTests(0);
                fetchSummary();
            } else {
                const err = await res.json();
                setMessage({ type: 'error', text: err.detail || 'Failed to delete' });
            }
        } catch { setMessage({ type: 'error', text: 'Failed to delete test' }); }
    }, [refreshTests, fetchSummary, setMessage]);

    // Copy path
    const handleCopyPath = useCallback((test: GeneratedTest) => {
        navigator.clipboard.writeText(test.path);
        setMessage({ type: 'success', text: 'Path copied to clipboard' });
        setMenuOpen(null);
    }, [setMessage]);

    // Selection helpers
    const toggleSelect = useCallback((path: string) => {
        setSelectedTests(prev => {
            const next = new Set(prev);
            if (next.has(path)) next.delete(path);
            else next.add(path);
            return next;
        });
    }, []);

    const toggleSelectAll = useCallback(() => {
        if (selectedTests.size === generatedTests.length) {
            setSelectedTests(new Set());
        } else {
            setSelectedTests(new Set(generatedTests.map(t => t.path)));
        }
    }, [generatedTests, selectedTests.size]);

    // Determine effective status for a test (running state overrides DB status)
    const getEffectiveStatus = useCallback((test: GeneratedTest): 'passed' | 'failed' | 'running' | null => {
        if (runningTests[test.path]) return 'running';
        for (const job of Object.values(activeJobs)) {
            if (job.status === 'running' && job.result?.test_path === test.path) {
                return 'running';
            }
        }
        return (test.last_run_status as ('passed' | 'failed' | null)) || null;
    }, [runningTests, activeJobs]);

    const allSelected = generatedTests.length > 0 && selectedTests.size === generatedTests.length;
    const hasRunning = Object.keys(runningTests).length > 0;

    return (
        <div style={{ position: 'relative' }}>
            {/* Status Summary Bar */}
            {summary && (
                <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '1rem', flexWrap: 'wrap', alignItems: 'center' }}>
                    {([
                        { key: 'all' as StatusFilter, label: `${summary.total_files} Total`, color: 'var(--text-primary)', bg: 'var(--surface)' },
                        { key: 'passed' as StatusFilter, label: `${summary.passed} Passed`, color: 'var(--success)', bg: 'var(--success-muted)' },
                        { key: 'failed' as StatusFilter, label: `${summary.failed} Failed`, color: 'var(--danger)', bg: 'var(--danger-muted)' },
                        { key: 'not_run' as StatusFilter, label: `${summary.not_run} Not Run`, color: 'var(--text-secondary)', bg: 'rgba(156, 163, 175, 0.1)' },
                    ] as const).map(pill => (
                        <button
                            key={pill.key}
                            onClick={() => handleStatusFilterChange(pill.key)}
                            style={{
                                padding: '0.4rem 0.85rem', borderRadius: '999px', fontSize: '0.8rem',
                                fontWeight: 600, border: '1px solid',
                                borderColor: statusFilter === pill.key ? pill.color : 'transparent',
                                background: pill.bg, color: pill.color,
                                cursor: 'pointer', transition: 'all 0.15s var(--ease-smooth)',
                                opacity: statusFilter !== 'all' && statusFilter !== pill.key ? 0.6 : 1,
                            }}
                        >
                            {pill.label}
                        </button>
                    ))}
                    {summary.total_tests > 0 && (
                        <span style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginLeft: '0.5rem' }}>
                            {summary.total_tests} test case{summary.total_tests !== 1 ? 's' : ''} total
                        </span>
                    )}
                </div>
            )}

            {/* Toolbar */}
            <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '1rem', alignItems: 'center', flexWrap: 'wrap' }}>
                <div style={{ position: 'relative', flex: '1 1 200px', maxWidth: '300px' }}>
                    <Search size={16} style={{ position: 'absolute', left: '0.75rem', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-secondary)' }} />
                    <input
                        type="text"
                        placeholder="Search tests..."
                        value={testsSearch}
                        onChange={e => handleSearchChange(e.target.value)}
                        style={{
                            width: '100%', padding: '0.5rem 0.5rem 0.5rem 2.25rem',
                            background: 'var(--surface)', border: '1px solid var(--border)',
                            borderRadius: 'var(--radius)', color: 'var(--text-primary)', fontSize: '0.875rem',
                        }}
                    />
                </div>
                <select
                    value={sortBy}
                    onChange={e => handleSortChange(e.target.value as SortOption)}
                    style={{
                        padding: '0.5rem 0.75rem', background: 'var(--surface)',
                        border: '1px solid var(--border)', borderRadius: 'var(--radius)',
                        color: 'var(--text-secondary)', fontSize: '0.875rem', cursor: 'pointer',
                    }}
                >
                    {SORT_OPTIONS.map(opt => (
                        <option key={opt.value} value={opt.value}>{opt.label}</option>
                    ))}
                </select>
                <button
                    onClick={() => { refreshTests(0); fetchSummary(); }}
                    style={{
                        display: 'flex', alignItems: 'center', gap: '0.4rem',
                        padding: '0.5rem 0.75rem', background: 'var(--surface)',
                        border: '1px solid var(--border)', borderRadius: 'var(--radius)',
                        cursor: 'pointer', color: 'var(--text-secondary)', fontSize: '0.875rem',
                    }}
                >
                    <RefreshCw size={14} /> Refresh
                </button>
                <button
                    onClick={handleRunAll}
                    disabled={generatedTests.length === 0 || hasRunning}
                    style={{
                        display: 'flex', alignItems: 'center', gap: '0.4rem',
                        padding: '0.5rem 0.85rem', background: 'var(--success)',
                        border: 'none', borderRadius: 'var(--radius)',
                        cursor: generatedTests.length === 0 || hasRunning ? 'not-allowed' : 'pointer',
                        color: '#fff', fontSize: '0.875rem', fontWeight: 600,
                        opacity: generatedTests.length === 0 || hasRunning ? 0.5 : 1,
                    }}
                >
                    <Play size={14} /> Run All
                </button>
                <span style={{ color: 'var(--text-secondary)', fontSize: '0.875rem', marginLeft: 'auto' }}>
                    {generatedTests.length} of {testsTotal} file{testsTotal !== 1 ? 's' : ''}
                </span>
            </div>

            {/* Test Table */}
            {testsLoading ? (
                <div style={{ textAlign: 'center', padding: '3rem', color: 'var(--text-secondary)' }}>
                    <Loader2 size={24} style={{ animation: 'spin 1s linear infinite', margin: '0 auto 0.5rem' }} />
                    <p>Loading generated tests...</p>
                </div>
            ) : generatedTests.length === 0 ? (
                <div style={{
                    textAlign: 'center', padding: '3rem',
                    background: 'var(--surface)', borderRadius: 'var(--radius)',
                    border: '1px solid var(--border)',
                }}>
                    <Play size={40} style={{ color: 'var(--text-secondary)', margin: '0 auto 1rem' }} />
                    <p style={{ color: 'var(--text-secondary)', marginBottom: '0.5rem' }}>
                        {statusFilter !== 'all' ? 'No tests match the current filter' : 'No generated API tests yet'}
                    </p>
                    <p style={{ color: 'var(--text-secondary)', fontSize: '0.8rem' }}>
                        {statusFilter !== 'all' ? 'Try changing the filter or search' : 'Create an API spec and generate tests to see them here'}
                    </p>
                </div>
            ) : (
                <div style={{ border: '1px solid var(--border)', borderRadius: 'var(--radius)', overflow: 'hidden' }}>
                    {/* Table Header */}
                    <div style={{
                        display: 'grid',
                        gridTemplateColumns: '40px 30px 1fr 150px 70px 90px 80px',
                        alignItems: 'center',
                        padding: '0.6rem 0.75rem',
                        background: 'rgba(0,0,0,0.15)',
                        borderBottom: '1px solid var(--border)',
                        fontSize: '0.75rem',
                        fontWeight: 600,
                        color: 'var(--text-secondary)',
                        textTransform: 'uppercase' as const,
                        letterSpacing: '0.03em',
                    }}>
                        <div>
                            <input
                                type="checkbox"
                                checked={allSelected}
                                onChange={toggleSelectAll}
                                style={{ cursor: 'pointer', accentColor: 'var(--primary)' }}
                            />
                        </div>
                        <div></div>
                        <div>Test Name</div>
                        <div>Source Spec</div>
                        <div style={{ textAlign: 'center' }}>Tests</div>
                        <div>Last Run</div>
                        <div style={{ textAlign: 'right' }}>Actions</div>
                    </div>

                    {/* Table Rows */}
                    {generatedTests.map(test => {
                        const isExpanded = expandedTest === test.name;
                        const isSelected = selectedTests.has(test.path);
                        const effectiveStatus = getEffectiveStatus(test);
                        const isRunning = effectiveStatus === 'running';
                        const isMenuOpen = menuOpen === test.name;

                        return (
                            <div key={test.path} style={{ borderBottom: '1px solid var(--border)' }}>
                                {/* Row */}
                                <div
                                    style={{
                                        display: 'grid',
                                        gridTemplateColumns: '40px 30px 1fr 150px 70px 90px 80px',
                                        alignItems: 'center',
                                        padding: '0.65rem 0.75rem',
                                        background: isSelected ? 'rgba(59, 130, 246, 0.05)' : isExpanded ? 'rgba(0,0,0,0.05)' : 'var(--surface)',
                                        cursor: 'pointer',
                                        transition: 'background 0.1s var(--ease-smooth)',
                                    }}
                                    onClick={() => {
                                        if (isExpanded) setExpandedTest(null);
                                        else { setExpandedTest(test.name); loadTestContent(test.name); }
                                    }}
                                >
                                    <div onClick={e => e.stopPropagation()}>
                                        <input
                                            type="checkbox"
                                            checked={isSelected}
                                            onChange={() => toggleSelect(test.path)}
                                            style={{ cursor: 'pointer', accentColor: 'var(--primary)' }}
                                        />
                                    </div>
                                    <div><StatusDot status={effectiveStatus} /></div>
                                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', minWidth: 0 }}>
                                        {isExpanded
                                            ? <ChevronDown size={14} style={{ flexShrink: 0 }} />
                                            : <ChevronRight size={14} style={{ flexShrink: 0 }} />}
                                        <span style={{
                                            fontWeight: 500, fontSize: '0.875rem',
                                            overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                                        }}>
                                            {test.name}
                                        </span>
                                    </div>
                                    <div style={{
                                        fontSize: '0.75rem', color: 'var(--text-secondary)',
                                        overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                                    }}>
                                        {test.source_spec || '\u2014'}
                                    </div>
                                    <div style={{ textAlign: 'center' }}>
                                        {test.test_count != null && test.test_count > 0 && (
                                            <span style={{
                                                padding: '0.1rem 0.45rem', borderRadius: '999px', fontSize: '0.7rem',
                                                fontWeight: 600, background: 'var(--primary-glow)', color: 'var(--primary)',
                                            }}>
                                                {test.test_count}
                                            </span>
                                        )}
                                    </div>
                                    <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
                                        {relativeTime(test.last_run_at)}
                                    </div>
                                    <div style={{ display: 'flex', gap: '0.25rem', justifyContent: 'flex-end' }} onClick={e => e.stopPropagation()}>
                                        <button
                                            onClick={() => handleRunTest(test)}
                                            disabled={isRunning}
                                            title="Run test"
                                            style={{
                                                display: 'flex', alignItems: 'center', justifyContent: 'center',
                                                width: '28px', height: '28px', borderRadius: 'var(--radius)',
                                                background: isRunning ? 'var(--warning-muted)' : 'var(--success-muted)',
                                                border: `1px solid ${isRunning ? 'rgba(245, 158, 11, 0.2)' : 'rgba(16, 185, 129, 0.2)'}`,
                                                cursor: isRunning ? 'wait' : 'pointer',
                                                color: isRunning ? 'var(--warning)' : 'var(--success)',
                                            }}
                                        >
                                            {isRunning
                                                ? <Loader2 size={13} style={{ animation: 'spin 1s linear infinite' }} />
                                                : <Play size={13} />}
                                        </button>
                                        <div style={{ position: 'relative' }} ref={isMenuOpen ? menuRef : undefined}>
                                            <button
                                                onClick={() => setMenuOpen(isMenuOpen ? null : test.name)}
                                                style={{
                                                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                                                    width: '28px', height: '28px', borderRadius: 'var(--radius)',
                                                    background: 'transparent', border: '1px solid transparent',
                                                    cursor: 'pointer', color: 'var(--text-secondary)',
                                                }}
                                            >
                                                <MoreVertical size={14} />
                                            </button>
                                            {isMenuOpen && (
                                                <div style={{
                                                    position: 'absolute', right: 0, top: '100%', zIndex: 50,
                                                    minWidth: '150px', background: 'var(--surface)',
                                                    border: '1px solid var(--border)', borderRadius: 'var(--radius)',
                                                    boxShadow: '0 4px 12px rgba(0,0,0,0.3)', overflow: 'hidden',
                                                }}>
                                                    <button
                                                        onClick={() => {
                                                            setExpandedTest(test.name);
                                                            loadTestContent(test.name);
                                                            setMenuOpen(null);
                                                            setTimeout(() => {
                                                                setEditingTest(test.name);
                                                                setEditTestContent(testContents[test.name] || '');
                                                            }, 100);
                                                        }}
                                                        style={menuItemStyle}
                                                        onMouseEnter={e => (e.currentTarget.style.background = 'rgba(255,255,255,0.05)')}
                                                        onMouseLeave={e => (e.currentTarget.style.background = 'none')}
                                                    >
                                                        <Edit2 size={13} /> Edit Code
                                                    </button>
                                                    <button
                                                        onClick={() => handleCopyPath(test)}
                                                        style={menuItemStyle}
                                                        onMouseEnter={e => (e.currentTarget.style.background = 'rgba(255,255,255,0.05)')}
                                                        onMouseLeave={e => (e.currentTarget.style.background = 'none')}
                                                    >
                                                        <Copy size={13} /> Copy Path
                                                    </button>
                                                    <div style={{ height: '1px', background: 'var(--border-subtle)' }} />
                                                    <button
                                                        onClick={() => { setMenuOpen(null); handleDeleteTest(test); }}
                                                        style={{ ...menuItemStyle, color: 'var(--danger)' }}
                                                        onMouseEnter={e => (e.currentTarget.style.background = 'rgba(239, 68, 68, 0.05)')}
                                                        onMouseLeave={e => (e.currentTarget.style.background = 'none')}
                                                    >
                                                        <Trash2 size={13} /> Delete
                                                    </button>
                                                </div>
                                            )}
                                        </div>
                                    </div>
                                </div>

                                {/* Expanded Code View */}
                                {isExpanded && (
                                    <div style={{ borderTop: '1px solid var(--border)', padding: '1rem', background: 'rgba(0,0,0,0.02)' }}>
                                        <div style={{
                                            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                                            marginBottom: '0.5rem', padding: '0.4rem 0.6rem',
                                            background: 'rgba(0,0,0,0.2)', borderRadius: 'var(--radius)',
                                        }}>
                                            <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', fontFamily: 'monospace' }}>
                                                {test.path}
                                            </span>
                                            <div style={{ display: 'flex', gap: '0.4rem' }}>
                                                <button
                                                    onClick={() => handleRunTest(test)}
                                                    disabled={isRunning}
                                                    style={{
                                                        display: 'flex', alignItems: 'center', gap: '0.3rem',
                                                        padding: '0.25rem 0.6rem', fontSize: '0.75rem',
                                                        background: 'var(--success-muted)', color: 'var(--success)',
                                                        border: '1px solid rgba(16, 185, 129, 0.2)',
                                                        borderRadius: 'var(--radius)', cursor: isRunning ? 'wait' : 'pointer',
                                                        opacity: isRunning ? 0.6 : 1,
                                                    }}
                                                >
                                                    {isRunning
                                                        ? <Loader2 size={12} style={{ animation: 'spin 1s linear infinite' }} />
                                                        : <Play size={12} />}
                                                    Run
                                                </button>
                                                {editingTest === test.name ? (
                                                    <>
                                                        <button
                                                            onClick={() => handleSaveTest(test.name)}
                                                            disabled={savingTest}
                                                            style={{
                                                                display: 'flex', alignItems: 'center', gap: '0.3rem',
                                                                padding: '0.25rem 0.6rem', fontSize: '0.75rem',
                                                                background: 'var(--success-muted)', color: 'var(--success)',
                                                                border: '1px solid rgba(16, 185, 129, 0.2)',
                                                                borderRadius: 'var(--radius)', cursor: savingTest ? 'wait' : 'pointer',
                                                                opacity: savingTest ? 0.6 : 1,
                                                            }}
                                                        >
                                                            {savingTest ? <Loader2 size={12} style={{ animation: 'spin 1s linear infinite' }} /> : <Save size={12} />}
                                                            Save
                                                        </button>
                                                        <button
                                                            onClick={() => setEditingTest(null)}
                                                            style={{
                                                                display: 'flex', alignItems: 'center', gap: '0.3rem',
                                                                padding: '0.25rem 0.6rem', fontSize: '0.75rem',
                                                                background: 'rgba(156, 163, 175, 0.1)', color: 'var(--text-secondary)',
                                                                border: '1px solid var(--border)',
                                                                borderRadius: 'var(--radius)', cursor: 'pointer',
                                                            }}
                                                        >
                                                            <X size={12} /> Cancel
                                                        </button>
                                                    </>
                                                ) : (
                                                    <button
                                                        onClick={() => {
                                                            setEditingTest(test.name);
                                                            setEditTestContent(testContents[test.name] || '');
                                                        }}
                                                        disabled={!testContents[test.name]}
                                                        style={{
                                                            display: 'flex', alignItems: 'center', gap: '0.3rem',
                                                            padding: '0.25rem 0.6rem', fontSize: '0.75rem',
                                                            background: 'var(--primary-glow)', color: 'var(--primary)',
                                                            border: '1px solid rgba(59, 130, 246, 0.2)',
                                                            borderRadius: 'var(--radius)', cursor: testContents[test.name] ? 'pointer' : 'not-allowed',
                                                            opacity: testContents[test.name] ? 1 : 0.4,
                                                        }}
                                                    >
                                                        <Edit2 size={12} /> Edit
                                                    </button>
                                                )}
                                            </div>
                                        </div>
                                        <div style={{ height: '500px', borderRadius: 'var(--radius)', overflow: 'hidden' }}>
                                            {testContents[test.name] ? (
                                                <CodeEditor
                                                    value={editingTest === test.name ? editTestContent : testContents[test.name]}
                                                    onChange={(val: string) => setEditTestContent(val)}
                                                    language="typescript"
                                                    readOnly={editingTest !== test.name}
                                                />
                                            ) : (
                                                <div style={{
                                                    height: '100%', display: 'flex', alignItems: 'center',
                                                    justifyContent: 'center', background: 'var(--background)', color: 'var(--text-secondary)',
                                                }}>
                                                    <Loader2 size={20} style={{ animation: 'spin 1s linear infinite' }} />
                                                </div>
                                            )}
                                        </div>
                                    </div>
                                )}
                            </div>
                        );
                    })}

                    {/* Load More */}
                    {testsHasMore && (
                        <div style={{ padding: '0.75rem', textAlign: 'center', background: 'var(--surface)' }}>
                            <button
                                onClick={handleLoadMore}
                                disabled={testsLoading}
                                style={{
                                    padding: '0.4rem 1rem', background: 'var(--background)',
                                    border: '1px solid var(--border)', borderRadius: 'var(--radius)',
                                    cursor: testsLoading ? 'wait' : 'pointer', color: 'var(--text-secondary)',
                                    fontSize: '0.8rem', opacity: testsLoading ? 0.6 : 1,
                                }}
                            >
                                {testsLoading ? 'Loading...' : 'Load More'}
                            </button>
                        </div>
                    )}
                </div>
            )}

            {/* Floating Selection Bar */}
            {selectedTests.size > 0 && (
                <div style={{
                    position: 'fixed', bottom: '1.5rem', left: '50%', transform: 'translateX(-50%)',
                    display: 'flex', alignItems: 'center', gap: '1rem',
                    padding: '0.75rem 1.25rem', background: 'var(--surface)',
                    border: '1px solid var(--border)', borderRadius: 'var(--radius)',
                    boxShadow: '0 8px 24px rgba(0,0,0,0.4)', zIndex: 100,
                }}>
                    <span style={{ fontWeight: 600, fontSize: '0.875rem', color: 'var(--text-primary)' }}>
                        {selectedTests.size} Test{selectedTests.size !== 1 ? 's' : ''} Selected
                    </span>
                    <div style={{ width: '1px', height: '20px', background: 'var(--border-subtle)' }} />
                    <button
                        onClick={() => setSelectedTests(new Set())}
                        style={{
                            padding: '0.35rem 0.75rem', background: 'rgba(156, 163, 175, 0.1)',
                            border: '1px solid var(--border)', borderRadius: 'var(--radius)',
                            cursor: 'pointer', color: 'var(--text-secondary)', fontSize: '0.8rem',
                        }}
                    >
                        Clear
                    </button>
                    <button
                        onClick={handleRunSelected}
                        style={{
                            display: 'flex', alignItems: 'center', gap: '0.4rem',
                            padding: '0.35rem 0.85rem', background: 'var(--success)',
                            border: 'none', borderRadius: 'var(--radius)',
                            cursor: 'pointer', color: '#fff', fontSize: '0.8rem', fontWeight: 600,
                        }}
                    >
                        <Play size={13} /> Run Selected
                    </button>
                </div>
            )}
        </div>
    );
});

const menuItemStyle: React.CSSProperties = {
    display: 'flex', alignItems: 'center', gap: '0.5rem', width: '100%',
    padding: '0.5rem 0.75rem', background: 'none', border: 'none',
    cursor: 'pointer', color: 'var(--text-primary)', fontSize: '0.8rem',
    textAlign: 'left',
};
