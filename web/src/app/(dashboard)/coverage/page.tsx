'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import {
    AlertTriangle,
    ArrowRight,
    BarChart3,
    CheckCircle2,
    ChevronDown,
    CircleDashed,
    Database,
    GitBranch,
    Globe,
    Lightbulb,
    PlayCircle,
    SearchCheck,
    Target,
    Zap,
} from 'lucide-react';
import { API_BASE } from '@/lib/api';
import { fetchWithAuth } from '@/contexts/AuthContext';
import { useProject } from '@/contexts/ProjectContext';
import { PageLayout } from '@/components/ui/page-layout';
import { PageHeader } from '@/components/ui/page-header';
import { EmptyState } from '@/components/ui/empty-state';
import { ListPageSkeleton } from '@/components/ui/page-skeleton';

interface MemoryCoverageGap {
    type: string;
    element_id?: string;
    element_type?: string;
    selector?: Record<string, unknown>;
    text?: string;
    url?: string;
    description: string;
    priority: string;
}

interface TestSuggestion {
    description: string;
    type: string;
    priority: string;
    title?: string | null;
    suggested_steps?: string[];
}

interface MemoryCoverageSummary {
    total_patterns: number;
    graph_stats: {
        page_count?: number;
        element_count?: number;
        flow_count?: number;
        total_nodes?: number;
        total_edges?: number;
    };
}

interface MemoryProject {
    id: string;
    name: string;
    pattern_count: number;
}

interface RtmCoverageSummary {
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
    suggested_test?: {
        test_name?: string;
        description?: string;
        steps?: string[];
    };
}

interface RtmRequirement {
    id: number;
    code: string;
    title: string;
    category: string;
    priority: string;
    coverage_status: string;
}

interface ExecutionCoverage {
    total_specs: number;
    total_test_files: number;
    specs_with_tests: number;
    specs_run_at_least_once: number;
    run_coverage_percent: number;
    tags_distribution: Array<{ tag: string; count: number }>;
}

function withProject(path: string, projectId?: string | null) {
    const basePath = `${API_BASE}${path}`;
    if (!projectId) return basePath;
    const separator = path.includes('?') ? '&' : '?';
    return `${basePath}${separator}project_id=${encodeURIComponent(projectId)}`;
}

async function readJson<T>(url: string, fallback: T): Promise<T> {
    try {
        const response = await fetchWithAuth(url);
        if (!response.ok) return fallback;
        return await response.json();
    } catch (error) {
        console.error(`Failed to load ${url}:`, error);
        return fallback;
    }
}

function priorityRank(priority: string) {
    const ranks: Record<string, number> = { critical: 0, high: 1, medium: 2, low: 3 };
    return ranks[priority] ?? 4;
}

function priorityColor(priority: string) {
    if (priority === 'critical' || priority === 'high') return 'var(--danger)';
    if (priority === 'medium') return 'var(--warning)';
    return 'var(--success)';
}

export default function CoveragePage() {
    const { currentProject, isLoading: projectLoading } = useProject();
    const [memoryGaps, setMemoryGaps] = useState<MemoryCoverageGap[]>([]);
    const [suggestions, setSuggestions] = useState<TestSuggestion[]>([]);
    const [memorySummary, setMemorySummary] = useState<MemoryCoverageSummary | null>(null);
    const [rtmSummary, setRtmSummary] = useState<RtmCoverageSummary | null>(null);
    const [rtmGaps, setRtmGaps] = useState<RtmGap[]>([]);
    const [partialRequirements, setPartialRequirements] = useState<RtmRequirement[]>([]);
    const [executionCoverage, setExecutionCoverage] = useState<ExecutionCoverage | null>(null);
    const [loading, setLoading] = useState(true);
    const [availableProjects, setAvailableProjects] = useState<MemoryProject[]>([]);
    const [selectedMemoryProject, setSelectedMemoryProject] = useState<string | null>(null);
    const [showProjectDropdown, setShowProjectDropdown] = useState(false);

    useEffect(() => {
        let cancelled = false;

        async function fetchProjects() {
            const data = await readJson<{ projects?: MemoryProject[] }>(`${API_BASE}/api/memory/projects`, { projects: [] });
            if (cancelled) return;

            const projects = [...(data.projects || [])].sort((a, b) => b.pattern_count - a.pattern_count);
            setAvailableProjects(projects);
            setSelectedMemoryProject(prev => prev || projects[0]?.id || currentProject?.id || 'demo');
        }

        fetchProjects();
        return () => {
            cancelled = true;
        };
    }, [currentProject?.id]);

    const fetchCoverageData = useCallback(async () => {
        if (projectLoading || !selectedMemoryProject) return;

        const intelligenceProjectId = currentProject?.id || selectedMemoryProject;
        setLoading(true);

        const [
            memoryGapsData,
            suggestionsData,
            memorySummaryData,
            rtmSummaryData,
            rtmGapsData,
            partialData,
            executionData,
        ] = await Promise.all([
            readJson<MemoryCoverageGap[]>(withProject('/api/memory/coverage/gaps?max_results=20', selectedMemoryProject), []),
            readJson<TestSuggestion[]>(withProject('/api/memory/coverage/suggestions?max_suggestions=15', selectedMemoryProject), []),
            readJson<MemoryCoverageSummary | null>(withProject('/api/memory/coverage/summary', selectedMemoryProject), null),
            readJson<RtmCoverageSummary | null>(withProject('/rtm/coverage', intelligenceProjectId), null),
            readJson<RtmGap[]>(withProject('/rtm/gaps?limit=20', intelligenceProjectId), []),
            readJson<{ items?: RtmRequirement[] }>(withProject('/rtm?limit=10&coverage_status=partial', intelligenceProjectId), { items: [] }),
            readJson<ExecutionCoverage | null>(withProject('/analytics/coverage-overview', intelligenceProjectId), null),
        ] as [
            Promise<MemoryCoverageGap[]>,
            Promise<TestSuggestion[]>,
            Promise<MemoryCoverageSummary | null>,
            Promise<RtmCoverageSummary | null>,
            Promise<RtmGap[]>,
            Promise<{ items?: RtmRequirement[] }>,
            Promise<ExecutionCoverage | null>,
        ]);

        setMemoryGaps([...memoryGapsData].sort((a, b) => priorityRank(a.priority) - priorityRank(b.priority)));
        setSuggestions(suggestionsData);
        setMemorySummary(memorySummaryData);
        setRtmSummary(rtmSummaryData);
        setRtmGaps([...rtmGapsData].sort((a, b) => priorityRank(a.priority) - priorityRank(b.priority)));
        setPartialRequirements(partialData.items || []);
        setExecutionCoverage(executionData);
        setLoading(false);
    }, [currentProject?.id, projectLoading, selectedMemoryProject]);

    useEffect(() => {
        fetchCoverageData();
    }, [fetchCoverageData]);

    const selectedProjectName = availableProjects.find(project => project.id === selectedMemoryProject)?.name || selectedMemoryProject || 'Discovery project';
    const stats = memorySummary?.graph_stats || {};
    const highPriorityRtmGaps = useMemo(
        () => rtmGaps.filter(gap => gap.priority === 'critical' || gap.priority === 'high'),
        [rtmGaps],
    );
    const specsNeverRun = Math.max(0, (executionCoverage?.total_specs ?? 0) - (executionCoverage?.specs_run_at_least_once ?? 0));
    const specsWithoutTests = Math.max(0, (executionCoverage?.total_specs ?? 0) - (executionCoverage?.specs_with_tests ?? 0));

    if (loading || projectLoading) {
        return (
            <PageLayout tier="standard">
                <ListPageSkeleton rows={4} />
            </PageLayout>
        );
    }

    return (
        <PageLayout tier="wide">
            <PageHeader
                title="Coverage Intelligence"
                subtitle="Separate requirement traceability, discovered app coverage, and run coverage signals."
                icon={<Target size={22} />}
                actions={
                    <div style={{ position: 'relative' }}>
                        <button
                            type="button"
                            onClick={() => setShowProjectDropdown(prev => !prev)}
                            className="btn"
                            style={{
                                display: 'flex',
                                alignItems: 'center',
                                gap: '0.5rem',
                                padding: '0.5rem 1rem',
                                border: '1px solid var(--border)',
                                borderRadius: 'var(--radius)',
                                background: 'var(--surface)',
                                color: 'var(--text)',
                                cursor: 'pointer',
                            }}
                        >
                            <Database size={16} />
                            {selectedProjectName}
                            <ChevronDown size={16} />
                        </button>

                        {showProjectDropdown && (
                            <div className="coverage-project-menu">
                                {availableProjects.length === 0 ? (
                                    <div style={{ padding: '1rem', color: 'var(--text-secondary)' }}>
                                        No discovery projects found
                                    </div>
                                ) : (
                                    availableProjects.map(project => (
                                        <button
                                            key={project.id}
                                            type="button"
                                            onClick={() => {
                                                setSelectedMemoryProject(project.id);
                                                setShowProjectDropdown(false);
                                            }}
                                            className="coverage-project-option"
                                            style={{ color: selectedMemoryProject === project.id ? 'var(--primary)' : 'var(--text)' }}
                                        >
                                            <span>{project.name}</span>
                                            <span>{project.pattern_count}</span>
                                        </button>
                                    ))
                                )}
                            </div>
                        )}
                    </div>
                }
            />

            <section className="coverage-lenses" aria-label="Coverage lenses">
                <LensCard
                    icon={<GitBranch size={20} />}
                    title="RTM Requirement Coverage"
                    value={rtmSummary ? `${Math.round(rtmSummary.coverage_percentage)}%` : '-'}
                    detail={rtmSummary ? `${rtmSummary.total_requirements} requirement${rtmSummary.total_requirements === 1 ? '' : 's'} traced to specs` : 'No RTM data returned'}
                    metrics={[
                        ['Covered', rtmSummary?.covered ?? 0],
                        ['Partial', rtmSummary?.partial ?? 0],
                        ['Uncovered', rtmSummary?.uncovered ?? 0],
                    ]}
                    action={<Link href="/rtm?coverage_status=uncovered">Open RTM</Link>}
                />
                <LensCard
                    icon={<SearchCheck size={20} />}
                    title="Discovered App Coverage"
                    value={stats.total_nodes ?? 0}
                    detail={`${stats.page_count ?? 0} pages, ${stats.element_count ?? 0} elements, ${stats.flow_count ?? 0} flows in memory`}
                    metrics={[
                        ['Pages', stats.page_count ?? 0],
                        ['Elements', stats.element_count ?? 0],
                        ['Flows', stats.flow_count ?? 0],
                    ]}
                    action={<Link href="/memory">Open Memory</Link>}
                />
                <LensCard
                    icon={<PlayCircle size={20} />}
                    title="Execution Coverage"
                    value={executionCoverage ? `${executionCoverage.run_coverage_percent.toFixed(1)}%` : '-'}
                    detail={executionCoverage ? `${executionCoverage.specs_run_at_least_once} of ${executionCoverage.total_specs} specs have run at least once` : 'No executed spec data returned'}
                    metrics={[
                        ['Specs', executionCoverage?.total_specs ?? 0],
                        ['Test files', executionCoverage?.total_test_files ?? 0],
                        ['Never run', specsNeverRun],
                    ]}
                    action={<Link href="/analytics">Open Analytics</Link>}
                />
            </section>

            <section className="coverage-queues" aria-label="Coverage action queues">
                <ActionQueue
                    title="Primary Queue"
                    subtitle="High-priority uncovered RTM requirements"
                    icon={<AlertTriangle size={20} />}
                    emptyTitle={rtmSummary?.total_requirements === 0 ? 'No requirements yet' : 'No high-priority RTM gaps'}
                    emptyDescription={rtmSummary?.total_requirements === 0 ? 'Add or generate requirements before closing RTM coverage.' : 'Critical and high-priority requirements are not currently uncovered.'}
                >
                    {highPriorityRtmGaps.slice(0, 6).map(gap => (
                        <QueueItem
                            key={gap.requirement_id}
                            tone={priorityColor(gap.priority)}
                            eyebrow={`${gap.requirement_code} - ${gap.priority}`}
                            title={gap.title}
                            detail={gap.suggested_test?.description || gap.category}
                            href={`/specs/new?requirement_id=${gap.requirement_id}&requirement_code=${encodeURIComponent(gap.requirement_code)}`}
                            actionLabel="Create spec"
                        />
                    ))}
                </ActionQueue>

                <ActionQueue
                    title="Secondary Queue"
                    subtitle="Partial RTM mappings needing stronger tests"
                    icon={<CircleDashed size={20} />}
                    emptyTitle={rtmSummary?.total_requirements === 0 ? 'No requirements yet' : 'No partial RTM mappings'}
                    emptyDescription={rtmSummary?.total_requirements === 0 ? 'Partial mappings will appear after requirements exist.' : 'Mapped requirements are either fully covered or still uncovered.'}
                >
                    {partialRequirements.slice(0, 6).map(req => (
                        <QueueItem
                            key={req.id}
                            tone="var(--warning)"
                            eyebrow={`${req.code} - ${req.priority}`}
                            title={req.title}
                            detail={req.category}
                            href="/rtm?coverage_status=partial"
                            actionLabel="Open RTM"
                        />
                    ))}
                </ActionQueue>

                <ActionQueue
                    title="Discovery Queue"
                    subtitle="Untested elements, orphan pages, and memory graph gaps"
                    icon={<Globe size={20} />}
                    emptyTitle="No memory gaps"
                    emptyDescription="Discovery memory has no untested page, element, or flow gaps for the selected project."
                >
                    {memoryGaps.slice(0, 6).map((gap, index) => (
                        <QueueItem
                            key={`${gap.type}-${gap.element_id || gap.url || index}`}
                            tone={priorityColor(gap.priority)}
                            eyebrow={`${gap.type} - ${gap.priority}`}
                            title={gap.description}
                            detail={gap.url || gap.element_type || gap.text || 'Discovery memory gap'}
                            href="/memory"
                            actionLabel="Inspect"
                        />
                    ))}
                </ActionQueue>

                <ActionQueue
                    title="Execution Queue"
                    subtitle="Specs that need generated tests or first execution"
                    icon={<BarChart3 size={20} />}
                    emptyTitle={executionCoverage?.total_specs === 0 ? 'No executed specs data' : 'Execution coverage is complete'}
                    emptyDescription={executionCoverage?.total_specs === 0 ? 'Create specs and run tests to populate execution coverage.' : 'All specs have generated tests and at least one run.'}
                >
                    {specsWithoutTests > 0 && (
                        <QueueItem
                            tone="var(--warning)"
                            eyebrow="Generated tests"
                            title={`${specsWithoutTests} spec${specsWithoutTests === 1 ? '' : 's'} without generated tests`}
                            detail="Create or generate tests for specs that only exist as source requirements."
                            href="/specs"
                            actionLabel="Open specs"
                        />
                    )}
                    {specsNeverRun > 0 && (
                        <QueueItem
                            tone="var(--danger)"
                            eyebrow="Run history"
                            title={`${specsNeverRun} spec${specsNeverRun === 1 ? '' : 's'} never run`}
                            detail="Execute specs at least once before trusting run coverage."
                            href="/analytics"
                            actionLabel="Open analytics"
                        />
                    )}
                </ActionQueue>
            </section>

            <section className="coverage-supporting">
                <div className="card coverage-section">
                    <div className="coverage-section-title">
                        <Lightbulb size={19} />
                        Discovery Test Suggestions
                    </div>
                    {suggestions.length === 0 ? (
                        <EmptyState
                            icon={<Lightbulb size={32} />}
                            title="No discovery suggestions"
                            description="Run more discovery or memory analysis to generate test ideas."
                        />
                    ) : (
                        <div className="coverage-list">
                            {suggestions.slice(0, 8).map((suggestion, index) => (
                                <QueueItem
                                    key={`${suggestion.type}-${index}`}
                                    tone={priorityColor(suggestion.priority)}
                                    eyebrow={`${suggestion.type} - ${suggestion.priority}`}
                                    title={suggestion.title || suggestion.description}
                                    detail={suggestion.title ? suggestion.description : suggestion.suggested_steps?.[0] || 'AI-generated discovery suggestion'}
                                    href="/specs/new"
                                    actionLabel="Create spec"
                                />
                            ))}
                        </div>
                    )}
                </div>

                <div className="card coverage-section">
                    <div className="coverage-section-title">
                        <Zap size={19} />
                        Data Health
                    </div>
                    <div className="coverage-health-grid">
                        <HealthRow label="Requirements" value={rtmSummary?.total_requirements ?? 0} emptyText="No requirements" />
                        <HealthRow label="Memory gaps" value={memoryGaps.length} emptyText="No memory gaps" />
                        <HealthRow label="Executed specs" value={executionCoverage?.specs_run_at_least_once ?? 0} emptyText="No executed specs" />
                        <HealthRow label="Discovery patterns" value={memorySummary?.total_patterns ?? 0} emptyText="No patterns" />
                    </div>
                </div>
            </section>

            <style jsx>{`
                .coverage-lenses {
                    display: grid;
                    grid-template-columns: repeat(3, minmax(0, 1fr));
                    gap: 1rem;
                    margin-bottom: 1rem;
                }

                .coverage-queues {
                    display: grid;
                    grid-template-columns: repeat(2, minmax(0, 1fr));
                    gap: 1rem;
                    margin-bottom: 1rem;
                }

                .coverage-supporting {
                    display: grid;
                    grid-template-columns: minmax(0, 1.25fr) minmax(300px, 0.75fr);
                    gap: 1rem;
                }

                .coverage-project-menu {
                    position: absolute;
                    top: 100%;
                    right: 0;
                    margin-top: 0.5rem;
                    background: var(--surface);
                    border: 1px solid var(--border);
                    border-radius: var(--radius);
                    box-shadow: var(--shadow-card);
                    z-index: 100;
                    min-width: 250px;
                    max-height: 400px;
                    overflow-y: auto;
                }

                .coverage-project-option {
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                    width: 100%;
                    padding: 0.75rem 1rem;
                    background: transparent;
                    border: 0;
                    text-align: left;
                    cursor: pointer;
                }

                .coverage-project-option span:last-child {
                    font-size: 0.8rem;
                    background: var(--primary);
                    color: white;
                    padding: 0.1rem 0.4rem;
                    border-radius: 10px;
                    min-width: 24px;
                    text-align: center;
                }

                .coverage-section {
                    padding: 1.2rem;
                }

                .coverage-section-title {
                    display: flex;
                    align-items: center;
                    gap: 0.55rem;
                    margin-bottom: 1rem;
                    font-size: 0.98rem;
                    font-weight: 800;
                }

                .coverage-list {
                    display: flex;
                    flex-direction: column;
                    gap: 0.75rem;
                }

                .coverage-health-grid {
                    display: grid;
                    gap: 0.75rem;
                }

                @media (max-width: 1120px) {
                    .coverage-lenses,
                    .coverage-queues,
                    .coverage-supporting {
                        grid-template-columns: 1fr;
                    }
                }
            `}</style>
        </PageLayout>
    );
}

function LensCard({
    icon,
    title,
    value,
    detail,
    metrics,
    action,
}: {
    icon: React.ReactNode;
    title: string;
    value: string | number;
    detail: string;
    metrics: Array<[string, string | number]>;
    action: React.ReactNode;
}) {
    return (
        <article className="card-elevated" style={{ padding: '1.2rem', minHeight: 210 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: '0.8rem', alignItems: 'flex-start', marginBottom: '1rem' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', color: 'var(--primary)', fontWeight: 800 }}>
                    {icon}
                    <span style={{ color: 'var(--text)' }}>{title}</span>
                </div>
                <div style={{ color: 'var(--primary)', fontWeight: 800, fontSize: '1.35rem', lineHeight: 1 }}>{value}</div>
            </div>
            <p style={{ color: 'var(--text-secondary)', margin: '0 0 1rem', fontSize: '0.88rem', lineHeight: 1.45 }}>
                {detail}
            </p>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: '0.55rem', marginBottom: '1rem' }}>
                {metrics.map(([label, metric]) => (
                    <div key={label} style={{ padding: '0.65rem', border: '1px solid var(--border-subtle)', borderRadius: 8, background: 'var(--surface)' }}>
                        <div style={{ color: 'var(--text-secondary)', fontSize: '0.72rem', marginBottom: '0.2rem' }}>{label}</div>
                        <div style={{ fontWeight: 800 }}>{metric}</div>
                    </div>
                ))}
            </div>
            <div style={{ fontSize: '0.84rem', fontWeight: 750 }}>
                {action}
            </div>
        </article>
    );
}

function ActionQueue({
    title,
    subtitle,
    icon,
    emptyTitle,
    emptyDescription,
    children,
}: {
    title: string;
    subtitle: string;
    icon: React.ReactNode;
    emptyTitle: string;
    emptyDescription: string;
    children: React.ReactNode;
}) {
    const childArray = Array.isArray(children) ? children.filter(Boolean) : children ? [children] : [];

    return (
        <section className="card" style={{ padding: '1.2rem' }}>
            <div style={{ display: 'flex', alignItems: 'flex-start', gap: '0.65rem', marginBottom: '1rem' }}>
                <div style={{ color: 'var(--primary)', marginTop: '0.1rem' }}>{icon}</div>
                <div>
                    <h2 style={{ margin: 0, fontSize: '1rem', fontWeight: 850 }}>{title}</h2>
                    <p style={{ margin: '0.25rem 0 0', color: 'var(--text-secondary)', fontSize: '0.84rem' }}>{subtitle}</p>
                </div>
            </div>
            {childArray.length === 0 ? (
                <EmptyState icon={<CheckCircle2 size={30} />} title={emptyTitle} description={emptyDescription} />
            ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>{children}</div>
            )}
        </section>
    );
}

function QueueItem({
    tone,
    eyebrow,
    title,
    detail,
    href,
    actionLabel,
}: {
    tone: string;
    eyebrow: string;
    title: string;
    detail: string;
    href: string;
    actionLabel: string;
}) {
    return (
        <Link
            href={href}
            style={{
                display: 'grid',
                gridTemplateColumns: 'minmax(0, 1fr) auto',
                gap: '1rem',
                alignItems: 'center',
                padding: '0.9rem 1rem',
                border: '1px solid var(--border-subtle)',
                borderLeft: `3px solid ${tone}`,
                borderRadius: 8,
                color: 'inherit',
                textDecoration: 'none',
                background: 'var(--surface)',
            }}
        >
            <div style={{ minWidth: 0 }}>
                <div style={{ color: tone, fontSize: '0.74rem', fontWeight: 850, textTransform: 'uppercase', marginBottom: '0.25rem' }}>{eyebrow}</div>
                <div style={{ fontWeight: 800, marginBottom: '0.25rem' }}>{title}</div>
                <div style={{ color: 'var(--text-secondary)', fontSize: '0.82rem', lineHeight: 1.4 }}>{detail}</div>
            </div>
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: '0.4rem', color: 'var(--primary)', fontSize: '0.82rem', fontWeight: 800, whiteSpace: 'nowrap' }}>
                {actionLabel}
                <ArrowRight size={14} />
            </span>
        </Link>
    );
}

function HealthRow({ label, value, emptyText }: { label: string; value: number; emptyText: string }) {
    const isEmpty = value === 0;
    return (
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '1rem', padding: '0.85rem 1rem', border: '1px solid var(--border-subtle)', borderRadius: 8, background: 'var(--surface)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.55rem', color: isEmpty ? 'var(--warning)' : 'var(--success)', fontWeight: 800 }}>
                {isEmpty ? <AlertTriangle size={16} /> : <CheckCircle2 size={16} />}
                <span style={{ color: 'var(--text)' }}>{label}</span>
            </div>
            <span style={{ color: isEmpty ? 'var(--text-secondary)' : 'var(--text)', fontWeight: 800 }}>
                {isEmpty ? emptyText : value}
            </span>
        </div>
    );
}
