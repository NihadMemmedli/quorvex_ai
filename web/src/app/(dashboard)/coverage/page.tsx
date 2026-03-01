'use client';

import { useState, useEffect } from 'react';
import { Target, AlertTriangle, Lightbulb, Globe, BarChart3, Zap, ChevronDown, Database } from 'lucide-react';
import { API_BASE } from '@/lib/api';
import { PageLayout } from '@/components/ui/page-layout';
import { PageHeader } from '@/components/ui/page-header';
import { EmptyState } from '@/components/ui/empty-state';
import { ListPageSkeleton } from '@/components/ui/page-skeleton';

interface CoverageGap {
    type: string;
    element_id?: string;
    element_type?: string;
    selector?: Record<string, any>;
    text?: string;
    url?: string;
    description: string;
    priority: string;
}

interface TestSuggestion {
    description: string;
    type: string;
    priority: string;
}

interface CoverageSummary {
    total_patterns: number;
    graph_stats: {
        page_count: number;
        element_count: number;
        flow_count: number;
        total_nodes: number;
        total_edges: number;
    };
}

interface Project {
    id: string;
    name: string;
    pattern_count: number;
}

export default function CoveragePage() {
    const [gaps, setGaps] = useState<CoverageGap[]>([]);
    const [suggestions, setSuggestions] = useState<TestSuggestion[]>([]);
    const [summary, setSummary] = useState<CoverageSummary | null>(null);
    const [loading, setLoading] = useState(true);
    const [activeTab, setActiveTab] = useState<'gaps' | 'suggestions'>('gaps');
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
            fetchCoverageData();
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

    const fetchCoverageData = async () => {
        if (!selectedProject) return;

        setLoading(true);
        try {
            const [gapsRes, suggestionsRes, summaryRes] = await Promise.all([
                fetch(`${API_BASE}/api/memory/coverage/gaps?project_id=${selectedProject}&max_results=20`),
                fetch(`${API_BASE}/api/memory/coverage/suggestions?project_id=${selectedProject}&max_suggestions=15`),
                fetch(`${API_BASE}/api/memory/coverage/summary?project_id=${selectedProject}`)
            ]);

            if (gapsRes.ok) {
                const gapsData = await gapsRes.json();
                setGaps(gapsData);
            }

            if (suggestionsRes.ok) {
                const suggestionsData = await suggestionsRes.json();
                setSuggestions(suggestionsData);
            }

            if (summaryRes.ok) {
                const summaryData = await summaryRes.json();
                setSummary(summaryData);
            }
        } catch (err) {
            console.error('Failed to fetch coverage data:', err);
        } finally {
            setLoading(false);
        }
    };

    const getPriorityColor = (priority: string) => {
        switch (priority) {
            case 'high': return 'var(--danger)';
            case 'medium': return 'var(--warning)';
            case 'low': return 'var(--success)';
            default: return 'var(--text-secondary)';
        }
    };

    const getPriorityIcon = (priority: string) => {
        switch (priority) {
            case 'high': return <AlertTriangle size={16} />;
            case 'medium': return <AlertTriangle size={16} />;
            default: return null;
        }
    };

    if (loading) {
        return (
            <PageLayout tier="standard">
                <ListPageSkeleton rows={4} />
            </PageLayout>
        );
    }

    const stats = summary?.graph_stats || {
        page_count: 0,
        element_count: 0,
        flow_count: 0,
        total_nodes: 0,
        total_edges: 0
    };
    const selectedProjectName = availableProjects.find(p => p.id === selectedProject)?.name || selectedProject || 'Select a project';

    return (
        <PageLayout tier="standard">
            <PageHeader
                title="Coverage"
                subtitle="Analyze test coverage gaps and get AI-powered test suggestions."
                icon={<Target size={22} />}
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

            {/* Coverage Stats */}
            {summary && (
                <div className="animate-in stagger-2" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '1rem', marginBottom: '2rem' }}>
                    <div className="card-elevated" style={{ padding: '1.5rem' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '0.5rem' }}>
                            <Globe size={20} style={{ color: 'var(--primary)' }} />
                            <span style={{ color: 'var(--text-secondary)', fontSize: '0.9rem' }}>Pages</span>
                        </div>
                        <div style={{ fontSize: '2rem', fontWeight: 700 }}>{stats.page_count || 0}</div>
                    </div>

                    <div className="card-elevated" style={{ padding: '1.5rem' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '0.5rem' }}>
                            <BarChart3 size={20} style={{ color: 'var(--primary)' }} />
                            <span style={{ color: 'var(--text-secondary)', fontSize: '0.9rem' }}>Elements</span>
                        </div>
                        <div style={{ fontSize: '2rem', fontWeight: 700 }}>{stats.element_count || 0}</div>
                    </div>

                    <div className="card-elevated" style={{ padding: '1.5rem' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '0.5rem' }}>
                            <Zap size={20} style={{ color: 'var(--primary)' }} />
                            <span style={{ color: 'var(--text-secondary)', fontSize: '0.9rem' }}>Flows</span>
                        </div>
                        <div style={{ fontSize: '2rem', fontWeight: 700 }}>{stats.flow_count || 0}</div>
                    </div>

                    <div className="card-elevated" style={{ padding: '1.5rem' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '0.5rem' }}>
                            <Target size={20} style={{ color: 'var(--success)' }} />
                            <span style={{ color: 'var(--text-secondary)', fontSize: '0.9rem' }}>Patterns</span>
                        </div>
                        <div style={{ fontSize: '2rem', fontWeight: 700 }}>{summary.total_patterns || 0}</div>
                    </div>
                </div>
            )}

            {/* Tabs */}
            <div className="card animate-in stagger-3" style={{ marginBottom: '1.5rem' }}>
                <div style={{ display: 'flex', gap: '0.5rem', borderBottom: '1px solid var(--border)' }}>
                    <button
                        onClick={() => setActiveTab('gaps')}
                        style={{
                            flex: 1,
                            padding: '1rem',
                            background: 'transparent',
                            border: 'none',
                            borderBottom: activeTab === 'gaps' ? '2px solid var(--primary)' : '2px solid transparent',
                            color: activeTab === 'gaps' ? 'var(--primary)' : 'var(--text-secondary)',
                            fontWeight: 600,
                            cursor: 'pointer',
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            gap: '0.5rem'
                        }}
                    >
                        <AlertTriangle size={18} />
                        Coverage Gaps ({gaps.length})
                    </button>
                    <button
                        onClick={() => setActiveTab('suggestions')}
                        style={{
                            flex: 1,
                            padding: '1rem',
                            background: 'transparent',
                            border: 'none',
                            borderBottom: activeTab === 'suggestions' ? '2px solid var(--primary)' : '2px solid transparent',
                            color: activeTab === 'suggestions' ? 'var(--primary)' : 'var(--text-secondary)',
                            fontWeight: 600,
                            cursor: 'pointer',
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            gap: '0.5rem'
                        }}
                    >
                        <Lightbulb size={18} />
                        Test Suggestions ({suggestions.length})
                    </button>
                </div>
            </div>

            {/* Content */}
            {activeTab === 'gaps' ? (
                <div className="card" style={{ padding: '1.5rem' }}>
                    <h3 style={{ marginBottom: '1rem', fontSize: '1.1rem' }}>Coverage Gaps</h3>
                    {gaps.length === 0 ? (
                        <EmptyState
                            icon={<Target size={32} />}
                            title="No coverage gaps detected!"
                            description="Your tests are well covered."
                        />
                    ) : (
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                            {gaps.map((gap, index) => (
                                <div
                                    key={index}
                                    style={{
                                        padding: '1rem',
                                        background: 'var(--surface)',
                                        borderRadius: 'var(--radius)',
                                        border: '1px solid var(--border)',
                                        borderLeft: `3px solid ${getPriorityColor(gap.priority)}`
                                    }}
                                >
                                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'start', marginBottom: '0.5rem' }}>
                                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                                            {getPriorityIcon(gap.priority)}
                                            <span style={{
                                                padding: '0.25rem 0.5rem',
                                                background: 'rgba(100, 116, 139, 0.1)',
                                                borderRadius: '4px',
                                                fontSize: '0.8rem',
                                                fontWeight: 600,
                                                textTransform: 'uppercase'
                                            }}>
                                                {gap.type}
                                            </span>
                                            {gap.element_type && (
                                                <span style={{ color: 'var(--text-secondary)', fontSize: '0.9rem' }}>
                                                    {gap.element_type}
                                                </span>
                                            )}
                                        </div>
                                        <span style={{
                                            padding: '0.25rem 0.5rem',
                                            background: `${getPriorityColor(gap.priority)}20`,
                                            color: getPriorityColor(gap.priority),
                                            borderRadius: '4px',
                                            fontSize: '0.8rem',
                                            fontWeight: 600
                                        }}>
                                            {gap.priority}
                                        </span>
                                    </div>
                                    <p style={{ margin: '0.5rem 0', fontSize: '0.95rem' }}>
                                        {gap.description}
                                    </p>
                                    {gap.url && (
                                        <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
                                            URL: {gap.url}
                                        </p>
                                    )}
                                </div>
                            ))}
                        </div>
                    )}
                </div>
            ) : (
                <div className="card" style={{ padding: '1.5rem' }}>
                    <h3 style={{ marginBottom: '1rem', fontSize: '1.1rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                        <Lightbulb size={20} />
                        AI-Generated Test Suggestions
                    </h3>
                    {suggestions.length === 0 ? (
                        <EmptyState
                            icon={<Lightbulb size={32} />}
                            title="No test suggestions yet"
                            description="Run more tests to get AI-powered suggestions."
                        />
                    ) : (
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                            {suggestions.map((suggestion, index) => (
                                <div
                                    key={index}
                                    style={{
                                        padding: '1rem',
                                        background: 'var(--surface)',
                                        borderRadius: 'var(--radius)',
                                        border: '1px solid var(--border)',
                                        borderLeft: `3px solid ${getPriorityColor(suggestion.priority)}`
                                    }}
                                >
                                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'start', marginBottom: '0.5rem' }}>
                                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                                            <Lightbulb size={16} style={{ color: 'var(--warning)' }} />
                                            <span style={{
                                                padding: '0.25rem 0.5rem',
                                                background: 'rgba(250, 204, 21, 0.1)',
                                                borderRadius: '4px',
                                                fontSize: '0.8rem',
                                                fontWeight: 600
                                            }}>
                                                {suggestion.type}
                                            </span>
                                        </div>
                                        <span style={{
                                            padding: '0.25rem 0.5rem',
                                            background: `${getPriorityColor(suggestion.priority)}20`,
                                            color: getPriorityColor(suggestion.priority),
                                            borderRadius: '4px',
                                            fontSize: '0.8rem',
                                            fontWeight: 600
                                        }}>
                                            {suggestion.priority}
                                        </span>
                                    </div>
                                    <p style={{ margin: '0.5rem 0', fontSize: '0.95rem' }}>
                                        {suggestion.description}
                                    </p>
                                </div>
                            ))}
                        </div>
                    )}
                </div>
            )}
        </PageLayout>
    );
}
