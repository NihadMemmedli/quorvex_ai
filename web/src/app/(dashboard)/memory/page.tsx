'use client';

import { useState, useEffect } from 'react';
import { Database, Search, CheckCircle, XCircle, Clock, TrendingUp, Filter, ChevronDown } from 'lucide-react';
import { API_BASE } from '@/lib/api';
import { PageLayout } from '@/components/ui/page-layout';
import { PageHeader } from '@/components/ui/page-header';
import { EmptyState } from '@/components/ui/empty-state';
import { DashboardPageSkeleton } from '@/components/ui/page-skeleton';

interface Pattern {
    id: string;
    action: string;
    target: string;
    success_rate: number;
    avg_duration: number;
    test_name: string;
}

interface MemoryStats {
    total_patterns: number;
    avg_success_rate: number;
    action_breakdown: Record<string, number>;
    project_id: string;
}

interface Project {
    id: string;
    name: string;
    pattern_count: number;
}

export default function MemoryPage() {
    const [patterns, setPatterns] = useState<Pattern[]>([]);
    const [stats, setStats] = useState<MemoryStats | null>(null);
    const [loading, setLoading] = useState(true);
    const [searchQuery, setSearchQuery] = useState('');
    const [actionFilter, setActionFilter] = useState('all');
    const [availableProjects, setAvailableProjects] = useState<Project[]>([]);
    const [selectedProject, setSelectedProject] = useState<string | null>(null);
    const [showProjectDropdown, setShowProjectDropdown] = useState(false);

    // Fetch available projects on mount
    useEffect(() => {
        fetchProjects();
    }, []);

    // Fetch data when selected project changes
    useEffect(() => {
        if (selectedProject) {
            fetchData();
        }
    }, [selectedProject]);

    const fetchProjects = async () => {
        try {
            const res = await fetch(`${API_BASE}/api/memory/projects`);
            if (res.ok) {
                const data = await res.json();
                const projects = data.projects || [];

                // Sort by pattern count (descending)
                projects.sort((a: Project, b: Project) => b.pattern_count - a.pattern_count);

                setAvailableProjects(projects);

                // Set default to the project with most patterns
                if (projects.length > 0 && !selectedProject) {
                    setSelectedProject(projects[0].id);
                } else if (projects.length === 0) {
                    setLoading(false);
                }
            }
        } catch (err) {
            console.error('Failed to fetch projects:', err);
            // Fallback to demo if fetch fails
            setAvailableProjects([{ id: 'demo', name: 'Demo', pattern_count: 0 }]);
            setSelectedProject('demo');
        }
    };

    const fetchData = async () => {
        if (!selectedProject) return;

        setLoading(true);
        try {
            const [patternsRes, statsRes] = await Promise.all([
                fetch(`${API_BASE}/api/memory/patterns?project_id=${selectedProject}&limit=100`),
                fetch(`${API_BASE}/api/memory/stats?project_id=${selectedProject}`)
            ]);

            if (patternsRes.ok) {
                const patternsData = await patternsRes.json();
                setPatterns(patternsData);
            }

            if (statsRes.ok) {
                const statsData = await statsRes.json();
                setStats(statsData);
            }
        } catch (err) {
            console.error('Failed to fetch memory data:', err);
        } finally {
            setLoading(false);
        }
    };

    const handleSearch = async () => {
        if (!searchQuery.trim()) {
            fetchData();
            return;
        }

        try {
            const res = await fetch(`${API_BASE}/api/memory/similar`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    description: searchQuery,
                    n_results: 10,
                    min_success_rate: 0.0
                })
            });

            if (res.ok) {
                const data = await res.json();
                setPatterns(data);
            }
        } catch (err) {
            console.error('Search failed:', err);
        }
    };

    const filteredPatterns = patterns.filter(p =>
        actionFilter === 'all' || p.action === actionFilter
    );

    if (loading) {
        return (
            <PageLayout tier="wide">
                <DashboardPageSkeleton />
            </PageLayout>
        );
    }

    const actionCounts = stats?.action_breakdown || {};
    const selectedProjectName = availableProjects.find(p => p.id === selectedProject)?.name || selectedProject || 'Select a project';

    return (
        <PageLayout tier="wide">
            <PageHeader
                title="Memory"
                subtitle="View stored test patterns and search for similar tests using semantic search."
                icon={<Database size={20} />}
                actions={
                    <div style={{ position: 'relative' }}>
                        <button
                            onClick={() => setShowProjectDropdown(!showProjectDropdown)}
                            className="btn"
                            style={{
                                display: 'flex',
                                alignItems: 'center',
                                gap: '0.5rem',
                                padding: '0.5rem 1rem',
                                border: '1px solid var(--border)',
                                borderRadius: 'var(--radius)',
                                background: 'var(--surface)',
                                cursor: 'pointer'
                            }}
                        >
                            <Database size={16} />
                            {selectedProjectName}
                            <ChevronDown size={16} />
                        </button>

                        {showProjectDropdown && (
                            <div style={{
                                position: 'absolute',
                                top: '100%',
                                right: 0,
                                marginTop: '0.5rem',
                                background: 'var(--surface)',
                                border: '1px solid var(--border)',
                                borderRadius: 'var(--radius)',
                                boxShadow: 'var(--shadow-card)',
                                zIndex: 100,
                                minWidth: '250px',
                                maxHeight: '400px',
                                overflowY: 'auto'
                            }}>
                                {availableProjects.length === 0 ? (
                                    <div style={{ padding: '1rem', color: 'var(--text-secondary)' }}>
                                        No projects found
                                    </div>
                                ) : (
                                    availableProjects.map(project => (
                                        <button
                                            key={project.id}
                                            onClick={() => {
                                                setSelectedProject(project.id);
                                                setShowProjectDropdown(false);
                                            }}
                                            style={{
                                                display: 'flex',
                                                justifyContent: 'space-between',
                                                alignItems: 'center',
                                                width: '100%',
                                                padding: '0.75rem 1rem',
                                                background: 'transparent',
                                                border: 'none',
                                                textAlign: 'left',
                                                cursor: 'pointer',
                                                color: selectedProject === project.id ? 'var(--primary)' : 'var(--text)'
                                            }}
                                        >
                                            <span>{project.name}</span>
                                            <span style={{
                                                fontSize: '0.8rem',
                                                background: 'var(--primary)',
                                                color: 'white',
                                                padding: '0.1rem 0.4rem',
                                                borderRadius: '10px',
                                                minWidth: '24px',
                                                textAlign: 'center'
                                            }}>
                                                {project.pattern_count}
                                            </span>
                                        </button>
                                    ))
                                )}
                            </div>
                        )}
                    </div>
                }
            />

            {/* Stats Cards */}
            {stats && (
                <div className="animate-in stagger-2" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(250px, 1fr))', gap: '1rem', marginBottom: '2rem' }}>
                    <div className="card-elevated" style={{ padding: '1.5rem' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', marginBottom: '0.5rem' }}>
                            <Database size={24} style={{ color: 'var(--primary)' }} />
                            <span style={{ color: 'var(--text-tertiary)', fontSize: '0.9rem' }}>Total Patterns</span>
                        </div>
                        <div style={{ fontSize: '2.5rem', fontWeight: 700, color: 'var(--text)' }}>
                            {stats.total_patterns}
                        </div>
                    </div>

                    <div className="card-elevated" style={{ padding: '1.5rem' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', marginBottom: '0.5rem' }}>
                            <CheckCircle size={24} style={{ color: 'var(--success)' }} />
                            <span style={{ color: 'var(--text-tertiary)', fontSize: '0.9rem' }}>Success Rate</span>
                        </div>
                        <div style={{ fontSize: '2.5rem', fontWeight: 700, color: 'var(--text)' }}>
                            {stats.avg_success_rate.toFixed(1)}%
                        </div>
                    </div>

                    <div className="card-elevated" style={{ padding: '1.5rem' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', marginBottom: '0.5rem' }}>
                            <TrendingUp size={24} style={{ color: 'var(--warning)' }} />
                            <span style={{ color: 'var(--text-tertiary)', fontSize: '0.9rem' }}>Project ID</span>
                        </div>
                        <div style={{ fontSize: '1.2rem', fontWeight: 700, color: 'var(--text)', wordBreak: 'break-all' }}>
                            {stats.project_id}
                        </div>
                    </div>
                </div>
            )}

            {/* Action Breakdown */}
            {Object.keys(actionCounts).length > 0 && (
                <div className="card" style={{ padding: '1.5rem', marginBottom: '2rem' }}>
                    <h3 style={{ marginBottom: '1rem', fontSize: '1.1rem' }}>Action Breakdown</h3>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '1rem' }}>
                        {Object.entries(actionCounts).map(([action, count]) => (
                            <div
                                key={action}
                                onClick={() => setActionFilter(actionFilter === action ? 'all' : action)}
                                style={{
                                    padding: '0.5rem 1rem',
                                    background: actionFilter === action ? 'var(--primary)' : 'var(--surface)',
                                    color: actionFilter === action ? 'white' : 'var(--text)',
                                    borderRadius: 'var(--radius)',
                                    cursor: 'pointer',
                                    border: '1px solid var(--border)',
                                    fontSize: '0.9rem'
                                }}
                            >
                                {action}: {count}
                            </div>
                        ))}
                    </div>
                </div>
            )}

            {/* Search */}
            <div className="card animate-in stagger-3" style={{ padding: '1.5rem', marginBottom: '2rem' }}>
                <h3 style={{ marginBottom: '1rem', fontSize: '1.1rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                    <Search size={20} />
                    Semantic Search
                </h3>
                <div style={{ display: 'flex', gap: '1rem' }}>
                    <input
                        type="text"
                        value={searchQuery}
                        onChange={(e) => setSearchQuery(e.target.value)}
                        onKeyPress={(e) => e.key === 'Enter' && handleSearch()}
                        placeholder="Describe what you want to test... (e.g., 'click on checkboxes and select dropdown options')"
                        className="input"
                        style={{ flex: 1 }}
                    />
                    <button onClick={handleSearch} className="btn btn-primary">
                        <Search size={18} />
                        Search
                    </button>
                </div>
                <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem', marginTop: '0.5rem' }}>
                    Uses AI semantic search to find similar test patterns from memory
                </p>
            </div>

            {/* Patterns List */}
            <div className="card animate-in stagger-4" style={{ padding: '1.5rem' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
                    <h3 style={{ margin: 0, fontSize: '1.1rem' }}>Stored Patterns ({filteredPatterns.length})</h3>
                    {actionFilter !== 'all' && (
                        <button
                            onClick={() => setActionFilter('all')}
                            className="btn"
                            style={{ fontSize: '0.9rem', padding: '0.5rem 1rem' }}
                        >
                            Clear Filter
                        </button>
                    )}
                </div>

                {filteredPatterns.length === 0 ? (
                    <div style={{ textAlign: 'center', padding: '3rem', color: 'var(--text-secondary)' }}>
                        <Database size={48} style={{ marginBottom: '1rem', opacity: 0.5 }} />
                        <p>No patterns found for this project</p>
                        <p style={{ fontSize: '0.9rem' }}>Run the exploratory agent to populate memory</p>
                    </div>
                ) : (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                        {filteredPatterns.map((pattern) => (
                            <div
                                key={pattern.id}
                                style={{
                                    padding: '1rem',
                                    background: 'var(--surface)',
                                    borderRadius: 'var(--radius)',
                                    border: '1px solid var(--border)'
                                }}
                            >
                                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'start', marginBottom: '0.5rem' }}>
                                    <div>
                                        <span style={{
                                            padding: '0.25rem 0.5rem',
                                            background: 'var(--primary)',
                                            color: 'white',
                                            borderRadius: '4px',
                                            fontSize: '0.8rem',
                                            fontWeight: 600,
                                            textTransform: 'uppercase'
                                        }}>
                                            {pattern.action}
                                        </span>
                                        <span style={{ marginLeft: '0.75rem', fontWeight: 500 }}>
                                            {pattern.target}
                                        </span>
                                    </div>
                                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '0.85rem' }}>
                                        {pattern.success_rate >= 0.9 ? (
                                            <CheckCircle size={16} style={{ color: 'var(--success)' }} />
                                        ) : (
                                            <XCircle size={16} style={{ color: 'var(--danger)' }} />
                                        )}
                                        {(pattern.success_rate * 100).toFixed(0)}%
                                    </div>
                                </div>
                                <div style={{ display: 'flex', gap: '1.5rem', fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
                                    <span style={{ display: 'flex', alignItems: 'center', gap: '0.25rem' }}>
                                        <Clock size={14} />
                                        {pattern.avg_duration.toFixed(0)}ms avg
                                    </span>
                                    <span>Test: {pattern.test_name}</span>
                                </div>
                            </div>
                        ))}
                    </div>
                )}
            </div>
        </PageLayout>
    );
}
