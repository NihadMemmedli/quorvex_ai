'use client';
import { useState, useEffect, useRef } from 'react';
import { Bot, FileText, Play, Terminal, ChevronRight, CheckCircle2, AlertTriangle, Loader2, Clock, RotateCcw, Lock, Globe, Settings, Download, List, Sparkles, Zap, ArrowRight, Info, X, RefreshCw, Scissors, ExternalLink, Plus, Save, Trash2, Wrench, MessageSquare, Bug, Lightbulb, Eye } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import { useProject } from '@/contexts/ProjectContext';
import { API_BASE } from '@/lib/api';
import { useJobPoller } from '@/hooks/useJobPoller';
import { PageLayout } from '@/components/ui/page-layout';
import { PageHeader } from '@/components/ui/page-header';
import { LiveBrowserView } from '@/components/LiveBrowserView';

interface AgentRun {
    id: string;
    agent_type: string;
    status: string;
    created_at: string;
    config: any;
    summary?: string;
    result?: any;
    project_id?: string;
    progress?: any;
    agent_task_id?: string | null;
    artifacts?: AgentArtifact[];
}

interface AgentArtifact {
    name: string;
    path: string;
    type: string;
    modified_at?: string | null;
}

interface AgentTool {
    id: string;
    label: string;
    description: string;
    category: string;
    tool_name: string;
    risk: 'low' | 'medium' | 'high' | 'destructive';
    requires_mcp_server?: string | null;
}

interface AgentDefinition {
    id: string;
    name: string;
    description: string;
    system_prompt: string;
    model?: string | null;
    timeout_seconds: number;
    tool_ids: string[];
    status: string;
    project_id?: string | null;
}

interface SpecResult {
    specs?: {
        happy_path?: Record<string, string>;
        edge_cases?: Record<string, string>;
    };
    summary?: string;
    total_specs?: number;
    flows_covered?: string[];
    generated_at?: string;
}

type AuthType = 'none' | 'credentials' | 'session';
type CustomResultTab = 'overview' | 'findings' | 'test_ideas' | 'evidence' | 'raw';

interface ReportPage {
    id?: string;
    url: string;
    status?: string;
    notes?: string;
}

interface ReportFinding {
    id: string;
    title: string;
    severity?: string;
    confidence?: string;
    page?: string;
    description?: string;
    evidence?: string;
    suggested_action?: string;
}

interface ReportTestIdea {
    id: string;
    title: string;
    priority?: string;
    page?: string;
    steps?: string[];
    expected?: string;
    source_finding_id?: string;
}

interface ReportEvidence {
    id?: string;
    type?: string;
    label?: string;
    value?: string;
}

interface StructuredAgentReport {
    summary?: string;
    scope?: string;
    pages_checked?: ReportPage[];
    findings?: ReportFinding[];
    test_ideas?: ReportTestIdea[];
    evidence?: ReportEvidence[];
    follow_up_actions?: { id?: string; label?: string; action?: string; target?: string }[];
    parse_status?: string;
}

function formatToolName(toolName?: string) {
    if (!toolName) return 'Waiting for first tool';
    const short = toolName.includes('__') ? toolName.split('__').pop() || toolName : toolName;
    return short.replace(/^browser_/, '').replace(/_/g, ' ');
}

function sortArtifactsByModifiedAt(artifacts: AgentArtifact[] = []) {
    return [...artifacts].sort((a, b) => {
        const bTime = b.modified_at ? new Date(b.modified_at).getTime() : 0;
        const aTime = a.modified_at ? new Date(a.modified_at).getTime() : 0;
        return bTime - aTime;
    });
}

function getArtifactUrl(artifact: AgentArtifact) {
    return `${API_BASE}${artifact.path}`;
}

function getStructuredReport(run: AgentRun): StructuredAgentReport {
    return run.result?.structured_report || {
        summary: run.result?.summary || 'Custom agent completed. Review the raw output for details.',
        scope: run.config?.prompt || run.config?.url || '',
        pages_checked: [],
        findings: [],
        test_ideas: [],
        evidence: [],
        follow_up_actions: [],
        parse_status: 'raw',
    };
}

function severityColor(value?: string) {
    const normalized = (value || '').toLowerCase();
    if (normalized === 'critical' || normalized === 'high') return 'var(--danger)';
    if (normalized === 'medium') return 'var(--warning)';
    if (normalized === 'low') return 'var(--primary)';
    return 'var(--text-secondary)';
}

function reportStatusColor(value?: string) {
    const normalized = (value || '').toLowerCase();
    if (normalized.includes('issue') || normalized.includes('failed') || normalized.includes('error')) return 'var(--danger)';
    if (normalized.includes('load') || normalized.includes('pass')) return 'var(--success)';
    return 'var(--text-secondary)';
}

function itemPrompt(run: AgentRun, item: ReportFinding | ReportTestIdea, kind: 'finding' | 'test idea') {
    const title = item.title || item.id;
    return [
        `Use custom agent run ${run.id} (${run.config?.agent_name || 'Custom Agent'}) as context.`,
        `Selected ${kind}: ${item.id} - ${title}`,
        'Create an actionable next step. If it requires changing platform state, prepare an approval action instead of doing it silently.',
    ].join('\n');
}

function CustomAgentReportView({
    run,
    activeTab,
    onTabChange,
    onAskAssistant,
}: {
    run: AgentRun;
    activeTab: CustomResultTab;
    onTabChange: (tab: CustomResultTab) => void;
    onAskAssistant: (prompt: string) => void;
}) {
    const report = getStructuredReport(run);
    const findings = report.findings || [];
    const testIdeas = report.test_ideas || [];
    const pages = report.pages_checked || [];
    const evidence = report.evidence || [];
    const tabs: { key: CustomResultTab; label: string }[] = [
        { key: 'overview', label: 'Overview' },
        { key: 'findings', label: `Findings ${findings.length}` },
        { key: 'test_ideas', label: `Test Ideas ${testIdeas.length}` },
        { key: 'evidence', label: `Evidence ${evidence.length}` },
        { key: 'raw', label: 'Raw Output' },
    ];
    const basePrompt = `Analyze custom agent run ${run.id} (${run.config?.agent_name || 'Custom Agent'}). Focus on findings, test ideas, and useful follow-up actions.`;

    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
            <div style={{ padding: '1rem', background: 'var(--surface-hover)', borderRadius: '8px', border: '1px solid var(--border)' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: '1rem', alignItems: 'flex-start', flexWrap: 'wrap' }}>
                    <div style={{ minWidth: 0 }}>
                        <h3 style={{ fontWeight: 700, fontSize: '1rem', margin: '0 0 0.35rem' }}>
                            {run.config?.agent_name || 'Custom Agent'}
                        </h3>
                        <p style={{ margin: 0, color: 'var(--text-secondary)', fontSize: '0.85rem' }}>
                            {run.result?.duration_seconds ? `Completed in ${run.result.duration_seconds.toFixed(1)} seconds` : 'Completed'}
                            {report.parse_status ? ` · ${report.parse_status} report` : ''}
                        </p>
                    </div>
                    <button
                        onClick={() => onAskAssistant(basePrompt)}
                        style={{ border: '1px solid var(--border)', background: 'var(--background)', color: 'var(--text)', borderRadius: '6px', padding: '0.45rem 0.7rem', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '0.4rem', fontSize: '0.82rem', fontWeight: 600 }}
                    >
                        <MessageSquare size={14} /> Ask Assistant
                    </button>
                </div>
                {report.summary && (
                    <p style={{ margin: '0.85rem 0 0', color: 'var(--text)', lineHeight: 1.55, fontSize: '0.92rem' }}>
                        {report.summary}
                    </p>
                )}
            </div>

            <div style={{ display: 'flex', gap: '0.4rem', flexWrap: 'wrap', borderBottom: '1px solid var(--border)', paddingBottom: '0.6rem' }}>
                {tabs.map(tab => (
                    <button
                        key={tab.key}
                        onClick={() => onTabChange(tab.key)}
                        style={{
                            border: '1px solid var(--border)',
                            background: activeTab === tab.key ? 'var(--primary-glow)' : 'var(--background)',
                            color: activeTab === tab.key ? 'var(--primary)' : 'var(--text-secondary)',
                            borderRadius: '6px',
                            padding: '0.4rem 0.65rem',
                            cursor: 'pointer',
                            fontSize: '0.8rem',
                            fontWeight: 600,
                        }}
                    >
                        {tab.label}
                    </button>
                ))}
            </div>

            {activeTab === 'overview' && (
                <div style={{ display: 'grid', gap: '1rem' }}>
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: '0.75rem' }}>
                        {[
                            { label: 'Pages Checked', value: pages.length, icon: Eye },
                            { label: 'Findings', value: findings.length, icon: Bug },
                            { label: 'Test Ideas', value: testIdeas.length, icon: Lightbulb },
                            { label: 'Tool Calls', value: run.result?.tool_calls?.length || 0, icon: Wrench },
                        ].map(item => {
                            const Icon = item.icon;
                            return (
                                <div key={item.label} style={{ padding: '0.9rem', border: '1px solid var(--border)', borderRadius: '8px', background: 'var(--background)' }}>
                                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.45rem', color: 'var(--text-secondary)', fontSize: '0.75rem', marginBottom: '0.45rem' }}>
                                        <Icon size={14} /> {item.label}
                                    </div>
                                    <div style={{ fontWeight: 800, fontSize: '1.4rem' }}>{item.value}</div>
                                </div>
                            );
                        })}
                    </div>
                    {report.scope && (
                        <div style={{ padding: '0.9rem', border: '1px solid var(--border)', borderRadius: '8px', background: 'var(--background)' }}>
                            <div style={{ fontWeight: 700, fontSize: '0.85rem', marginBottom: '0.35rem' }}>Scope</div>
                            <p style={{ margin: 0, color: 'var(--text-secondary)', fontSize: '0.85rem', lineHeight: 1.5 }}>{report.scope}</p>
                        </div>
                    )}
                    {pages.length > 0 && (
                        <div style={{ border: '1px solid var(--border)', borderRadius: '8px', overflow: 'hidden', background: 'var(--background)' }}>
                            <div style={{ padding: '0.7rem 0.9rem', borderBottom: '1px solid var(--border)', fontWeight: 700, fontSize: '0.85rem' }}>Pages Checked</div>
                            {pages.slice(0, 12).map((page, i) => (
                                <div key={`${page.url}-${i}`} style={{ padding: '0.65rem 0.9rem', borderBottom: i === Math.min(pages.length, 12) - 1 ? 'none' : '1px solid var(--border)', display: 'grid', gridTemplateColumns: '1fr auto', gap: '0.8rem', fontSize: '0.82rem' }}>
                                    <span style={{ overflowWrap: 'anywhere' }}>{page.url}</span>
                                    <span style={{ color: reportStatusColor(page.status), fontWeight: 700, textTransform: 'capitalize' }}>{page.status || 'unknown'}</span>
                                </div>
                            ))}
                        </div>
                    )}
                </div>
            )}

            {activeTab === 'findings' && (
                <div style={{ display: 'grid', gap: '0.75rem' }}>
                    {findings.length === 0 ? (
                        <EmptyReportState text="No structured findings were reported." />
                    ) : findings.map(finding => (
                        <div key={finding.id} style={{ padding: '0.9rem', border: '1px solid var(--border)', borderRadius: '8px', background: 'var(--background)' }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', gap: '0.75rem', flexWrap: 'wrap', marginBottom: '0.45rem' }}>
                                <div style={{ fontWeight: 700, fontSize: '0.92rem' }}>{finding.id}: {finding.title}</div>
                                <span style={{ color: severityColor(finding.severity), fontWeight: 800, fontSize: '0.78rem', textTransform: 'uppercase' }}>{finding.severity || 'info'}</span>
                            </div>
                            {finding.page && <div style={{ fontSize: '0.78rem', color: 'var(--primary)', marginBottom: '0.35rem', overflowWrap: 'anywhere' }}>{finding.page}</div>}
                            {finding.description && <p style={{ margin: '0 0 0.45rem', color: 'var(--text-secondary)', fontSize: '0.85rem', lineHeight: 1.5 }}>{finding.description}</p>}
                            {finding.evidence && <p style={{ margin: '0 0 0.7rem', color: 'var(--text)', fontSize: '0.82rem', lineHeight: 1.45 }}><strong>Evidence:</strong> {finding.evidence}</p>}
                            <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
                                <ReportActionButton onClick={() => onAskAssistant(itemPrompt(run, finding, 'finding'))} label="Use in Assistant" icon={MessageSquare} />
                                <ReportActionButton onClick={() => onAskAssistant(`Create a Playwright markdown test spec from custom agent finding ${finding.id} in run ${run.id}. Include concrete steps and expected results. Use an approval action before creating it.`)} label="Create Spec" icon={FileText} />
                                <ReportActionButton onClick={() => onAskAssistant(`Start a follow-up custom agent from finding ${finding.id} in run ${run.id}. Verify whether this issue still reproduces and collect evidence. Use approval before starting the agent.`)} label="Follow Up Agent" icon={Bot} />
                            </div>
                        </div>
                    ))}
                </div>
            )}

            {activeTab === 'test_ideas' && (
                <div style={{ display: 'grid', gap: '0.75rem' }}>
                    {testIdeas.length === 0 ? (
                        <EmptyReportState text="No structured test ideas were reported." />
                    ) : testIdeas.map(idea => (
                        <div key={idea.id} style={{ padding: '0.9rem', border: '1px solid var(--border)', borderRadius: '8px', background: 'var(--background)' }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', gap: '0.75rem', flexWrap: 'wrap', marginBottom: '0.45rem' }}>
                                <div style={{ fontWeight: 700, fontSize: '0.92rem' }}>{idea.id}: {idea.title}</div>
                                <span style={{ color: severityColor(idea.priority), fontWeight: 800, fontSize: '0.78rem', textTransform: 'uppercase' }}>{idea.priority || 'medium'}</span>
                            </div>
                            {idea.page && <div style={{ fontSize: '0.78rem', color: 'var(--primary)', marginBottom: '0.35rem', overflowWrap: 'anywhere' }}>{idea.page}</div>}
                            {idea.steps && idea.steps.length > 0 && (
                                <ol style={{ margin: '0.35rem 0 0.55rem 1.15rem', color: 'var(--text-secondary)', fontSize: '0.84rem', lineHeight: 1.45 }}>
                                    {idea.steps.map((step, i) => <li key={`${idea.id}-step-${i}`}>{step}</li>)}
                                </ol>
                            )}
                            {idea.expected && <p style={{ margin: '0 0 0.7rem', color: 'var(--text)', fontSize: '0.82rem' }}><strong>Expected:</strong> {idea.expected}</p>}
                            <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
                                <ReportActionButton onClick={() => onAskAssistant(itemPrompt(run, idea, 'test idea'))} label="Use in Assistant" icon={MessageSquare} />
                                <ReportActionButton onClick={() => onAskAssistant(`Create a Playwright markdown test spec from custom agent test idea ${idea.id} in run ${run.id}. Use approval before creating it.`)} label="Create Spec" icon={FileText} />
                            </div>
                        </div>
                    ))}
                </div>
            )}

            {activeTab === 'evidence' && (
                <div style={{ display: 'grid', gap: '0.6rem' }}>
                    {evidence.length === 0 ? (
                        <EmptyReportState text="No structured evidence was reported." />
                    ) : evidence.map((item, i) => (
                        <div key={item.id || `${item.label}-${i}`} style={{ padding: '0.75rem 0.9rem', border: '1px solid var(--border)', borderRadius: '8px', background: 'var(--background)', display: 'grid', gap: '0.3rem' }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', gap: '0.75rem', fontSize: '0.84rem' }}>
                                <strong>{item.label || item.id || `Evidence ${i + 1}`}</strong>
                                <span style={{ color: 'var(--text-secondary)', textTransform: 'capitalize' }}>{item.type || 'note'}</span>
                            </div>
                            {item.value && (
                                item.value.startsWith('/api/') ? (
                                    <a href={`${API_BASE}${item.value}`} target="_blank" rel="noreferrer" style={{ color: 'var(--primary)', fontSize: '0.8rem', overflowWrap: 'anywhere' }}>{item.value}</a>
                                ) : (
                                    <span style={{ color: 'var(--text-secondary)', fontSize: '0.8rem', overflowWrap: 'anywhere' }}>{item.value}</span>
                                )
                            )}
                        </div>
                    ))}
                </div>
            )}

            {activeTab === 'raw' && (
                <div style={{ display: 'grid', gap: '1rem' }}>
                    <div style={{ background: '#111827', padding: '1rem', borderRadius: '8px', border: '1px solid var(--border)' }}>
                        <pre style={{ whiteSpace: 'pre-wrap', fontFamily: 'monospace', fontSize: '0.84rem', color: '#e5e7eb', margin: 0 }}>
                            {run.result?.output || JSON.stringify(run.result, null, 2)}
                        </pre>
                    </div>
                    {run.result?.tool_calls?.length > 0 && (
                        <details>
                            <summary style={{ cursor: 'pointer', fontWeight: 600, fontSize: '0.9rem' }}>
                                Tool Calls ({run.result.tool_calls.length})
                            </summary>
                            <div style={{ marginTop: '0.5rem', display: 'grid', gap: '0.4rem' }}>
                                {run.result.tool_calls.map((call: any, i: number) => (
                                    <div key={`${call.name}-${i}`} style={{ padding: '0.5rem', background: 'var(--surface-hover)', border: '1px solid var(--border)', borderRadius: '6px', fontSize: '0.78rem' }}>
                                        <strong>{call.name}</strong>
                                        {call.duration_ms !== undefined && <span style={{ color: 'var(--text-secondary)' }}> · {Math.round(call.duration_ms)}ms</span>}
                                        {call.error && <div style={{ color: 'var(--danger)', marginTop: '0.25rem' }}>{call.error}</div>}
                                    </div>
                                ))}
                            </div>
                        </details>
                    )}
                </div>
            )}
        </div>
    );
}

function EmptyReportState({ text }: { text: string }) {
    return (
        <div style={{ padding: '1.25rem', border: '1px solid var(--border)', borderRadius: '8px', background: 'var(--background)', color: 'var(--text-secondary)', textAlign: 'center', fontSize: '0.86rem' }}>
            {text}
        </div>
    );
}

function ReportActionButton({ onClick, label, icon: Icon }: { onClick: () => void; label: string; icon: any }) {
    return (
        <button
            onClick={onClick}
            style={{ border: '1px solid var(--border)', background: 'var(--surface-hover)', color: 'var(--text)', borderRadius: '6px', padding: '0.38rem 0.6rem', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '0.35rem', fontSize: '0.78rem', fontWeight: 600 }}
        >
            <Icon size={13} /> {label}
        </button>
    );
}

export default function AgentsPage() {
    const { currentProject } = useProject();
    const [selectedAgent, setSelectedAgent] = useState<'exploratory' | 'writer' | 'custom'>('exploratory');

    // Basic config
    const [url, setUrl] = useState('');
    const [instructions, setInstructions] = useState('');

    // Enhanced exploratory config
    const [timeLimitMinutes, setTimeLimitMinutes] = useState(15);
    const [authType, setAuthType] = useState<AuthType>('none');
    const [authCredentials, setAuthCredentials] = useState({ username: '', password: '', loginUrl: '/login' });
    const [sessionId, setSessionId] = useState('');
    const [testData, setTestData] = useState('');
    const [focusAreas, setFocusAreas] = useState('');
    const [excludedPatterns, setExcludedPatterns] = useState('');

    // History & results
    const [history, setHistory] = useState<AgentRun[]>([]);
    const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
    const [activeRun, setActiveRun] = useState<AgentRun | null>(null);
    const [specResult, setSpecResult] = useState<SpecResult | null>(null);

    // UI state
    const [isStarting, setIsStarting] = useState(false);
    const [isSynthesizing, setIsSynthesizing] = useState(false);
    const [showAdvanced, setShowAdvanced] = useState(false);
    const [sessions, setSessions] = useState<any[]>([]);
    const [flowModalOpen, setFlowModalOpen] = useState(false);
    const [selectedFlow, setSelectedFlow] = useState<any | null>(null);
    const [loadingFlowDetails, setLoadingFlowDetails] = useState(false);
    const [generatingSpec, setGeneratingSpec] = useState(false);
    const [generatedSpec, setGeneratedSpec] = useState<any | null>(null);
    const [specModalOpen, setSpecModalOpen] = useState(false);
    const [splittingSpec, setSplittingSpec] = useState(false);
    const [splitResult, setSplitResult] = useState<{ count: number; files: string[]; output_dir: string } | null>(null);
    const [agentDefinitions, setAgentDefinitions] = useState<AgentDefinition[]>([]);
    const [toolCatalog, setToolCatalog] = useState<AgentTool[]>([]);
    const [selectedDefinitionId, setSelectedDefinitionId] = useState<string>('');
    const [customResultTab, setCustomResultTab] = useState<CustomResultTab>('overview');
    const [builderOpen, setBuilderOpen] = useState(false);
    const [savingDefinition, setSavingDefinition] = useState(false);
    const [definitionForm, setDefinitionForm] = useState({
        id: '',
        name: '',
        description: '',
        system_prompt: 'You are a focused QA automation agent. Use the selected tools to inspect the target, report findings clearly, and avoid actions outside the requested task.',
        timeout_seconds: 1800,
        tool_ids: ['read_file', 'list_files', 'browser_navigate', 'browser_snapshot', 'browser_network', 'browser_console'],
    });
    const pollInterval = useRef<NodeJS.Timeout | null>(null);

    // Fetch history (filtered by project)
    const fetchHistory = async () => {
        try {
            const projectParam = currentProject?.id
                ? `?project_id=${encodeURIComponent(currentProject.id)}`
                : '';
            const res = await fetch(`${API_BASE}/api/agents/runs${projectParam}`);
            if (res.ok) {
                const data = await res.json();
                setHistory(data);
            }
        } catch (e) { console.error("Failed to fetch history", e); }
    };

    // Fetch sessions
    const fetchSessions = async () => {
        try {
            const res = await fetch(`${API_BASE}/api/agents/sessions`);
            if (res.ok) {
                const data = await res.json();
                setSessions(data.sessions || []);
            }
        } catch (e) { console.error("Failed to fetch sessions", e); }
    };

    const fetchToolCatalog = async () => {
        try {
            const res = await fetch(`${API_BASE}/api/agents/tools/catalog`);
            if (res.ok) {
                const data = await res.json();
                setToolCatalog(data.tools || []);
            }
        } catch (e) { console.error("Failed to fetch agent tool catalog", e); }
    };

    const fetchAgentDefinitions = async () => {
        try {
            const projectParam = currentProject?.id
                ? `?project_id=${encodeURIComponent(currentProject.id)}`
                : '';
            const res = await fetch(`${API_BASE}/api/agents/definitions${projectParam}`);
            if (res.ok) {
                const data = await res.json();
                setAgentDefinitions(data || []);
                if (!selectedDefinitionId && data?.length) {
                    setSelectedDefinitionId(data[0].id);
                }
            }
        } catch (e) { console.error("Failed to fetch agent definitions", e); }
    };

    useEffect(() => {
        fetchHistory();
        fetchSessions();
        fetchToolCatalog();
        fetchAgentDefinitions();
        return () => { if (pollInterval.current) clearInterval(pollInterval.current); }
    }, [currentProject?.id]);  // Re-fetch when project changes

    useEffect(() => {
        setCustomResultTab('overview');
    }, [activeRun?.id]);

    const openAssistantWithPrompt = (prompt: string) => {
        window.dispatchEvent(new CustomEvent('open-ai-assistant'));
        setTimeout(() => {
            window.dispatchEvent(new CustomEvent('assistant-prefill', { detail: { prompt } }));
        }, 50);
    };

    // Fetch single run
    const fetchRun = async (id: string) => {
        try {
            const res = await fetch(`${API_BASE}/api/agents/runs/${id}`);
            if (res.ok) {
                const data = await res.json();
                setActiveRun(data);

                // If actively running, keep polling
                if (data.status === 'running' || data.status === 'pending') {
                    // Continue polling
                } else {
                    // Run completed or failed - do one final fetch to get the result
                    if (pollInterval.current && selectedRunId === id) {
                        clearInterval(pollInterval.current);
                        pollInterval.current = null;

                        // Fetch one more time after a short delay to ensure result is saved
                        setTimeout(async () => {
                            const finalRes = await fetch(`${API_BASE}/api/agents/runs/${id}`);
                            if (finalRes.ok) {
                                const finalData = await finalRes.json();
                                setActiveRun(finalData);
                            }
                            fetchHistory(); // Refresh list to update status
                        }, 500);
                    }
                }
            }
        } catch (e) {
            console.error("Failed to fetch run", e);
        }
    };

    // Fetch specs for exploration run
    const fetchSpecs = async (runId: string) => {
        try {
            const res = await fetch(`${API_BASE}/api/agents/exploratory/${runId}/specs`);
            if (res.ok) {
                const data = await res.json();
                if (data.specs) {
                    setSpecResult(data);
                }
            }
        } catch (e) {
            console.error("Failed to fetch specs", e);
        }
    };

    // Fetch flow details from the API
    const fetchFlowDetails = async (flowId: string) => {
        if (!activeRun?.id) return;

        setLoadingFlowDetails(true);
        try {
            const res = await fetch(`${API_BASE}/api/agents/exploratory/${activeRun.id}/flows/${flowId}`);
            if (res.ok) {
                const data = await res.json();
                setSelectedFlow(data.flow);
                setFlowModalOpen(true);
            } else {
                const error = await res.json();
                alert(`Failed to load flow details: ${error.detail || 'Unknown error'}`);
            }
        } catch (e) {
            console.error("Failed to fetch flow details", e);
            alert("Failed to load flow details. Please try again.");
        } finally {
            setLoadingFlowDetails(false);
        }
    };

    // Flow spec generation with async job polling
    const flowSpecPoller = useJobPoller({
        apiBase: API_BASE,
        urlPattern: '/api/agents/exploratory/flow-spec-jobs/{jobId}',
        interval: 3000,
        onComplete: (result) => {
            if (result) {
                setGeneratedSpec({
                    spec_content: result.spec_content as string,
                    spec_file: result.spec_file as string,
                    filename: result.spec_file ? (result.spec_file as string).split('/').pop() : 'spec.md',
                    flow_title: result.flow_title as string,
                    summary: 'Generated with Intelligent Pipeline',
                    cached: false,
                    validated: result.validated as boolean || false,
                    test_code: result.test_code as string,
                    test_file: result.test_file as string,
                    pipeline: result.pipeline as string,
                    requires_auth: result.requires_auth as boolean,
                });
                setSpecModalOpen(true);
            }
            setGeneratingSpec(false);
        },
        onFailed: (message) => {
            setGeneratingSpec(false);
            alert(`Failed to generate spec: ${message || 'Unknown error'}`);
        },
    });

    // Generate spec for a single flow using Intelligent Pipeline
    const generateFlowSpec = async (flowId: string, forceRegenerate: boolean = false) => {
        if (!activeRun?.id) return;

        setGeneratingSpec(true);
        setSplitResult(null);
        try {
            const url = forceRegenerate
                ? `${API_BASE}/api/agents/exploratory/${activeRun.id}/flows/${flowId}/generate?force_regenerate=true`
                : `${API_BASE}/api/agents/exploratory/${activeRun.id}/flows/${flowId}/generate`;

            const res = await fetch(url, { method: 'POST' });
            if (!res.ok) {
                const error = await res.json().catch(() => ({}));
                throw new Error(error.detail || `HTTP ${res.status}`);
            }
            const data = await res.json();

            // Cached result → show immediately
            if (data.cached || data.status === 'success') {
                setGeneratedSpec({
                    spec_content: data.spec_content,
                    spec_file: data.spec_file,
                    filename: data.spec_file ? data.spec_file.split('/').pop() : 'spec.md',
                    flow_title: data.flow_title,
                    summary: data.status === 'success' ? 'Generated with Intelligent Pipeline' : data.status,
                    cached: data.cached || false,
                    validated: data.validated || false,
                    test_code: data.test_code,
                    test_file: data.test_file,
                    pipeline: data.pipeline,
                    requires_auth: data.requires_auth
                });
                setSpecModalOpen(true);
                setGeneratingSpec(false);
                return;
            }

            // Async job → start polling
            if (data.job_id) {
                flowSpecPoller.startPolling(data.job_id);
                return; // generatingSpec stays true until poll resolves
            }

            throw new Error('Unexpected response from server');
        } catch (e: unknown) {
            const message = e instanceof Error ? e.message : 'Please try again.';
            alert(`Failed to generate spec: ${message}`);
            setGeneratingSpec(false);
        }
    };

    // Download generated spec as file
    const downloadSpec = (content?: string, filename?: string) => {
        // If no arguments provided, use state (for new flow spec generation)
        const specContent = content || generatedSpec?.spec_content;
        const specFilename = filename || generatedSpec?.filename || 'spec.md';

        if (!specContent) return;

        const blob = new Blob([specContent], { type: 'text/markdown' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = specFilename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    };

    // Split spec into individual tests
    const splitSpec = async () => {
        if (!generatedSpec?.spec_file) return;

        setSplittingSpec(true);
        setSplitResult(null);
        try {
            // Extract spec name relative to specs directory
            const specFile = generatedSpec.spec_file;
            const specsIndex = specFile.indexOf('/specs/');
            const specName = specsIndex !== -1 ? specFile.substring(specsIndex + 7) : specFile.split('/').slice(-2).join('/');

            const res = await fetch(`${API_BASE}/specs/split`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ spec_name: specName })
            });

            if (res.ok) {
                const data = await res.json();
                setSplitResult(data);
            } else {
                const error = await res.json();
                alert(`Failed to split spec: ${error.detail || 'Unknown error'}`);
            }
        } catch (e) {
            console.error("Failed to split spec", e);
            alert("Failed to split spec. Please try again.");
        } finally {
            setSplittingSpec(false);
        }
    };

    // When selection changes
    useEffect(() => {
        if (!selectedRunId) {
            setActiveRun(null);
            setSpecResult(null);
            return;
        }

        // Clear existing poll
        if (pollInterval.current) clearInterval(pollInterval.current);

        // Initial fetch
        fetchRun(selectedRunId);
        fetchSpecs(selectedRunId);

        // Start polling
        pollInterval.current = setInterval(() => {
            fetchRun(selectedRunId);
        }, 2000); // 2s poll

        return () => {
            if (pollInterval.current) clearInterval(pollInterval.current);
        };
    }, [selectedRunId]);


    const selectedDefinition = agentDefinitions.find(agent => agent.id === selectedDefinitionId);
    const toolsByCategory = toolCatalog.reduce<Record<string, AgentTool[]>>((acc, tool) => {
        acc[tool.category] = acc[tool.category] || [];
        acc[tool.category].push(tool);
        return acc;
    }, {});

    const resetDefinitionForm = () => {
        setDefinitionForm({
            id: '',
            name: '',
            description: '',
            system_prompt: 'You are a focused QA automation agent. Use the selected tools to inspect the target, report findings clearly, and avoid actions outside the requested task.',
            timeout_seconds: 1800,
            tool_ids: ['read_file', 'list_files', 'browser_navigate', 'browser_snapshot', 'browser_network', 'browser_console'],
        });
        setBuilderOpen(true);
    };

    const editDefinition = (definition: AgentDefinition) => {
        setDefinitionForm({
            id: definition.id,
            name: definition.name,
            description: definition.description || '',
            system_prompt: definition.system_prompt,
            timeout_seconds: definition.timeout_seconds || 1800,
            tool_ids: definition.tool_ids || [],
        });
        setBuilderOpen(true);
    };

    const toggleDefinitionTool = (toolId: string) => {
        setDefinitionForm(prev => ({
            ...prev,
            tool_ids: prev.tool_ids.includes(toolId)
                ? prev.tool_ids.filter(id => id !== toolId)
                : [...prev.tool_ids, toolId],
        }));
    };

    const toggleCategoryTools = (tools: AgentTool[]) => {
        const ids = tools.map(tool => tool.id);
        const allSelected = ids.every(id => definitionForm.tool_ids.includes(id));
        setDefinitionForm(prev => ({
            ...prev,
            tool_ids: allSelected
                ? prev.tool_ids.filter(id => !ids.includes(id))
                : Array.from(new Set([...prev.tool_ids, ...ids])),
        }));
    };

    const saveDefinition = async () => {
        if (!definitionForm.name.trim()) {
            alert('Agent name is required');
            return;
        }
        if (!definitionForm.system_prompt.trim()) {
            alert('System prompt is required');
            return;
        }
        if (definitionForm.tool_ids.length === 0) {
            alert('Select at least one tool');
            return;
        }

        setSavingDefinition(true);
        try {
            const isEdit = Boolean(definitionForm.id);
            const url = isEdit
                ? `${API_BASE}/api/agents/definitions/${definitionForm.id}${currentProject?.id ? `?project_id=${encodeURIComponent(currentProject.id)}` : ''}`
                : `${API_BASE}/api/agents/definitions`;
            const res = await fetch(url, {
                method: isEdit ? 'PUT' : 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    name: definitionForm.name,
                    description: definitionForm.description,
                    system_prompt: definitionForm.system_prompt,
                    timeout_seconds: definitionForm.timeout_seconds,
                    tool_ids: definitionForm.tool_ids,
                    project_id: currentProject?.id,
                }),
            });
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.detail || 'Failed to save agent');
            }
            const saved = await res.json();
            await fetchAgentDefinitions();
            setSelectedDefinitionId(saved.id);
            setSelectedAgent('custom');
            setBuilderOpen(false);
        } catch (e: any) {
            alert(e.message || 'Failed to save agent');
        } finally {
            setSavingDefinition(false);
        }
    };

    const archiveDefinition = async (definition: AgentDefinition) => {
        if (!confirm(`Archive "${definition.name}"? Existing run history will remain.`)) return;
        try {
            const res = await fetch(`${API_BASE}/api/agents/definitions/${definition.id}${currentProject?.id ? `?project_id=${encodeURIComponent(currentProject.id)}` : ''}`, {
                method: 'DELETE',
            });
            if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.detail || 'Failed to archive agent');
            }
            await fetchAgentDefinitions();
            if (selectedDefinitionId === definition.id) setSelectedDefinitionId('');
        } catch (e: any) {
            alert(e.message || 'Failed to archive agent');
        }
    };

    const handleRun = async () => {
        if (selectedAgent === 'custom' && !selectedDefinitionId) {
            alert("Select or create a custom agent first");
            return;
        }
        if (selectedAgent !== 'custom' && !url) {
            alert("URL is required");
            return;
        }

        setIsStarting(true);
        try {
            // Build auth config
            let authConfig: any = null;
            if (authType !== 'none') {
                authConfig = { type: authType };
                if (authType === 'credentials') {
                    authConfig.credentials = {
                        username: authCredentials.username,
                        password: authCredentials.password
                    };
                    authConfig.login_url = authCredentials.loginUrl;
                } else if (authType === 'session') {
                    authConfig.session_id = sessionId;
                }
            }

            // Build test data from JSON
            let testDataObj = {};
            if (testData.trim()) {
                try {
                    testDataObj = JSON.parse(testData);
                } catch (e) {
                    alert("Invalid JSON in test data");
                    setIsStarting(false);
                    return;
                }
            }

            // Build focus areas
            const focusAreasList = focusAreas ? focusAreas.split(',').map(s => s.trim()).filter(s => s) : [];

            // Build excluded patterns
            const excludedPatternsList = excludedPatterns ? excludedPatterns.split(',').map(s => s.trim()).filter(s => s) : [];

            // Use new enhanced endpoint for exploratory agent
            const endpoint = selectedAgent === 'custom'
                ? `${API_BASE}/api/agents/definitions/${selectedDefinitionId}/runs`
                : selectedAgent === 'exploratory'
                ? `${API_BASE}/api/agents/exploratory`
                : `${API_BASE}/api/agents/runs`;

            const body = selectedAgent === 'custom'
                ? {
                    prompt: instructions || `Inspect ${url || 'the current application context'} and report useful QA findings.`,
                    url: url || undefined,
                    config: {
                        auth: authConfig,
                        test_data: Object.keys(testDataObj).length > 0 ? testDataObj : undefined,
                        focus_areas: focusAreasList,
                        excluded_patterns: excludedPatternsList,
                    },
                    project_id: currentProject?.id,
                }
                : selectedAgent === 'exploratory'
                ? {
                    url,
                    time_limit_minutes: timeLimitMinutes,
                    instructions,
                    auth: authConfig,
                    test_data: Object.keys(testDataObj).length > 0 ? testDataObj : undefined,
                    focus_areas: focusAreasList.length > 0 ? focusAreasList : undefined,
                    excluded_patterns: excludedPatternsList.length > 0 ? excludedPatternsList : undefined,
                    project_id: currentProject?.id  // Associate generated specs with current project
                }
                : {
                    agent_type: 'writer',
                    config: {
                        url,
                        instructions,
                        max_steps: 10
                    },
                    project_id: currentProject?.id  // Project isolation for writer agent
                };

            const res = await fetch(endpoint, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body)
            });

            if (!res.ok) {
                const err = await res.json();
                throw new Error(err.detail || 'Agent run failed');
            }

            const data = await res.json();
            // Refresh history but select the new run
            await fetchHistory();
            setSelectedRunId(data.run_id);

        } catch (e: any) {
            alert(e.message);
        } finally {
            setIsStarting(false);
        }
    };

    const handleSynthesize = async () => {
        if (!selectedRunId || !activeRun || activeRun.agent_type !== 'exploratory') {
            alert("Please select a completed exploratory run");
            return;
        }

        if (activeRun.status !== 'completed') {
            alert("Please wait for the exploration to complete");
            return;
        }

        setIsSynthesizing(true);
        try {
            const res = await fetch(`${API_BASE}/api/agents/exploratory/${selectedRunId}/synthesize`, {
                method: 'POST'
            });

            if (!res.ok) {
                const err = await res.json();
                throw new Error(err.detail || 'Spec synthesis failed');
            }

            const data = await res.json();

            // Poll for specs
            setTimeout(() => {
                fetchSpecs(selectedRunId!);
                setIsSynthesizing(false);
            }, 2000);

        } catch (e: any) {
            alert(e.message);
            setIsSynthesizing(false);
        }
    };

    const formatDate = (iso: string) => {
        return new Date(iso).toLocaleString('en-US', { hour: 'numeric', minute: 'numeric', day: 'numeric', month: 'short' });
    };

    return (
        <PageLayout tier="wide" style={{ paddingBottom: '4rem', height: '100vh', display: 'flex', flexDirection: 'column' }}>
            <PageHeader
                title="Autonomous Agents"
                subtitle="Deploy AI agents to explore, test, and specify your application autonomously."
                icon={<Bot size={20} />}
            />

            <div style={{ display: 'grid', gridTemplateColumns: '280px 350px 1fr', gap: '1.5rem', flex: 1, minHeight: 0 }}>

                {/* History Sidebar */}
                <div className="card" style={{ padding: '0', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
                    <div style={{ padding: '1rem', borderBottom: '1px solid var(--border)', background: 'var(--surface-hover)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <h3 style={{ fontWeight: 600, fontSize: '0.9rem' }}>Run History</h3>
                        <button onClick={fetchHistory} style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-secondary)' }}>
                            <RotateCcw size={14} />
                        </button>
                    </div>
                    <div style={{ flex: 1, overflowY: 'auto' }}>
                        {history.length === 0 ? (
                            <div style={{ padding: '2rem', textAlign: 'center', color: 'var(--text-secondary)', fontSize: '0.85rem' }}>
                                No runs yet.
                            </div>
                        ) : (
                            history.map(run => (
                                <div
                                    key={run.id}
                                    onClick={() => setSelectedRunId(run.id)}
                                    style={{
                                        padding: '0.75rem 1rem',
                                        borderBottom: '1px solid var(--border)',
                                        cursor: 'pointer',
                                        background: selectedRunId === run.id ? 'rgba(59, 130, 246, 0.06)' : 'transparent',
                                        borderLeft: selectedRunId === run.id ? '3px solid var(--primary)' : '3px solid transparent'
                                    }}
                                >
                                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.25rem' }}>
                                        <span style={{ fontWeight: 600, fontSize: '0.85rem', color: run.agent_type === 'custom' ? 'var(--success)' : run.agent_type === 'writer' ? 'var(--primary)' : 'var(--warning)' }}>
                                            {run.agent_type === 'custom' ? (run.config?.agent_name || 'Custom') : run.agent_type === 'writer' ? 'Writer' : 'Explorer'}
                                        </span>
                                        <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>{formatDate(run.created_at)}</span>
                                    </div>
                                    <div style={{ fontSize: '0.8rem', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', color: 'var(--text)' }}>
                                        {run.config?.url?.replace('https://', '') || 'No URL'}
                                    </div>
                                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.25rem', marginTop: '0.25rem' }}>
                                        {run.status === 'running' ? <Loader2 size={12} className="spin" color="var(--primary)" /> :
                                            run.status === 'failed' ? <AlertTriangle size={12} color="var(--danger)" /> :
                                                <CheckCircle2 size={12} color="var(--success)" />}
                                        <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', textTransform: 'capitalize' }}>{run.status}</span>
                                    </div>
                                </div>
                            ))
                        )}
                    </div>
                </div>

                {/* Left Column: Configuration */}
                <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem', overflowY: 'auto' }}>

                    {/* Agent Selection */}
                    <div className="card" style={{ padding: '0', overflow: 'hidden', flexShrink: 0 }}>
                        <div style={{ padding: '1rem', borderBottom: '1px solid var(--border)', background: 'var(--surface-hover)' }}>
                            <h3 style={{ fontWeight: 600, fontSize: '0.9rem' }}>New Run</h3>
                        </div>
                        <div style={{ padding: '0.5rem' }}>
                            <div
                                onClick={() => setSelectedAgent('exploratory')}
                                style={{
                                    padding: '0.75rem',
                                    cursor: 'pointer',
                                    background: selectedAgent === 'exploratory' ? 'var(--primary-glow)' : 'transparent',
                                    border: selectedAgent === 'exploratory' ? '1px solid var(--primary)' : '1px solid transparent',
                                    borderRadius: '8px',
                                    marginBottom: '0.5rem',
                                    display: 'flex', gap: '0.75rem'
                                }}
                            >
                                <Terminal size={20} color={selectedAgent === 'exploratory' ? 'var(--primary)' : 'var(--text-secondary)'} />
                                <div>
                                    <h4 style={{ fontWeight: 600, fontSize: '0.9rem', color: selectedAgent === 'exploratory' ? 'var(--primary)' : 'var(--text)' }}>Enhanced Explorer</h4>
                                    <p style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
                                        15-min autonomous exploration
                                    </p>
                                </div>
                            </div>

                            <div
                                onClick={() => setSelectedAgent('custom')}
                                style={{
                                    padding: '0.75rem',
                                    cursor: 'pointer',
                                    background: selectedAgent === 'custom' ? 'var(--primary-glow)' : 'transparent',
                                    border: selectedAgent === 'custom' ? '1px solid var(--primary)' : '1px solid transparent',
                                    borderRadius: '8px',
                                    display: 'flex', gap: '0.75rem'
                                }}
                            >
                                <Wrench size={20} color={selectedAgent === 'custom' ? 'var(--primary)' : 'var(--text-secondary)'} />
                                <div>
                                    <h4 style={{ fontWeight: 600, fontSize: '0.9rem', color: selectedAgent === 'custom' ? 'var(--primary)' : 'var(--text)' }}>Custom Agent</h4>
                                    <p style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
                                        User-defined tools and prompt
                                    </p>
                                </div>
                            </div>
                        </div>
                    </div>

                    {/* Custom Agent Builder */}
                    <div className="card" style={{ padding: '1rem', flexShrink: 0 }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.75rem' }}>
                            <h3 style={{ fontWeight: 600, fontSize: '0.9rem' }}>Custom Agents</h3>
                            <button
                                onClick={resetDefinitionForm}
                                title="Create agent"
                                style={{ border: '1px solid var(--border)', background: 'var(--surface-hover)', borderRadius: '6px', padding: '0.35rem', cursor: 'pointer', color: 'var(--text)' }}
                            >
                                <Plus size={15} />
                            </button>
                        </div>

                        {agentDefinitions.length === 0 ? (
                            <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '0.75rem' }}>
                                No custom agents yet.
                            </div>
                        ) : (
                            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem', marginBottom: '0.75rem' }}>
                                {agentDefinitions.map(definition => (
                                    <div
                                        key={definition.id}
                                        onClick={() => { setSelectedDefinitionId(definition.id); setSelectedAgent('custom'); }}
                                        style={{
                                            padding: '0.65rem',
                                            border: selectedDefinitionId === definition.id ? '1px solid var(--primary)' : '1px solid var(--border)',
                                            borderRadius: '6px',
                                            background: selectedDefinitionId === definition.id ? 'var(--primary-glow)' : 'var(--surface-hover)',
                                            cursor: 'pointer'
                                        }}
                                    >
                                        <div style={{ display: 'flex', justifyContent: 'space-between', gap: '0.5rem' }}>
                                            <div style={{ minWidth: 0 }}>
                                                <div style={{ fontSize: '0.85rem', fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{definition.name}</div>
                                                <div style={{ fontSize: '0.72rem', color: 'var(--text-secondary)' }}>{definition.tool_ids.length} tools</div>
                                            </div>
                                            <div style={{ display: 'flex', gap: '0.25rem' }}>
                                                <button
                                                    onClick={(e) => { e.stopPropagation(); editDefinition(definition); }}
                                                    title="Edit agent"
                                                    style={{ border: 'none', background: 'transparent', color: 'var(--text-secondary)', cursor: 'pointer' }}
                                                >
                                                    <Settings size={14} />
                                                </button>
                                                <button
                                                    onClick={(e) => { e.stopPropagation(); archiveDefinition(definition); }}
                                                    title="Archive agent"
                                                    style={{ border: 'none', background: 'transparent', color: 'var(--danger)', cursor: 'pointer' }}
                                                >
                                                    <Trash2 size={14} />
                                                </button>
                                            </div>
                                        </div>
                                    </div>
                                ))}
                            </div>
                        )}

                        {builderOpen && (
                            <div style={{ borderTop: '1px solid var(--border)', paddingTop: '0.75rem' }}>
                                <label style={{ fontSize: '0.75rem', fontWeight: 500 }}>Name</label>
                                <input
                                    value={definitionForm.name}
                                    onChange={e => setDefinitionForm({ ...definitionForm, name: e.target.value })}
                                    placeholder="API explorer"
                                    style={{ width: '100%', padding: '0.5rem', borderRadius: '6px', fontSize: '0.85rem', border: '1px solid var(--input-border)', background: 'var(--input-bg)', color: 'var(--text)', margin: '0.25rem 0 0.65rem' }}
                                />
                                <label style={{ fontSize: '0.75rem', fontWeight: 500 }}>Description</label>
                                <input
                                    value={definitionForm.description}
                                    onChange={e => setDefinitionForm({ ...definitionForm, description: e.target.value })}
                                    placeholder="Explores pages and reports API calls"
                                    style={{ width: '100%', padding: '0.5rem', borderRadius: '6px', fontSize: '0.85rem', border: '1px solid var(--input-border)', background: 'var(--input-bg)', color: 'var(--text)', margin: '0.25rem 0 0.65rem' }}
                                />
                                <label style={{ fontSize: '0.75rem', fontWeight: 500 }}>System Prompt</label>
                                <textarea
                                    value={definitionForm.system_prompt}
                                    onChange={e => setDefinitionForm({ ...definitionForm, system_prompt: e.target.value })}
                                    rows={4}
                                    style={{ width: '100%', padding: '0.5rem', borderRadius: '6px', fontSize: '0.8rem', border: '1px solid var(--input-border)', background: 'var(--input-bg)', color: 'var(--text)', resize: 'vertical', margin: '0.25rem 0 0.65rem' }}
                                />
                                <label style={{ fontSize: '0.75rem', fontWeight: 500 }}>Timeout seconds</label>
                                <input
                                    type="number"
                                    min={60}
                                    max={7200}
                                    value={definitionForm.timeout_seconds}
                                    onChange={e => setDefinitionForm({ ...definitionForm, timeout_seconds: parseInt(e.target.value) || 1800 })}
                                    style={{ width: '100%', padding: '0.5rem', borderRadius: '6px', fontSize: '0.85rem', border: '1px solid var(--input-border)', background: 'var(--input-bg)', color: 'var(--text)', margin: '0.25rem 0 0.65rem' }}
                                />
                                <div style={{ display: 'flex', justifyContent: 'space-between', gap: '0.5rem', alignItems: 'center', marginBottom: '0.5rem' }}>
                                    <div style={{ fontSize: '0.75rem', fontWeight: 600 }}>Tools</div>
                                    <div style={{ fontSize: '0.72rem', color: 'var(--text-secondary)' }}>
                                        {definitionForm.tool_ids.length} of {toolCatalog.length} selected
                                    </div>
                                </div>
                                <div style={{ maxHeight: '260px', overflowY: 'auto', border: '1px solid var(--border)', borderRadius: '6px', padding: '0.5rem' }}>
                                    {Object.entries(toolsByCategory).map(([category, tools]) => (
                                        <div key={category} style={{ marginBottom: '0.75rem' }}>
                                            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '0.5rem', marginBottom: '0.35rem' }}>
                                                <div style={{ fontSize: '0.72rem', color: 'var(--text-secondary)', fontWeight: 700, textTransform: 'uppercase' }}>
                                                    {category} ({tools.length})
                                                </div>
                                                <button
                                                    type="button"
                                                    onClick={() => toggleCategoryTools(tools)}
                                                    style={{ fontSize: '0.68rem', border: 'none', background: 'transparent', color: 'var(--primary)', cursor: 'pointer', padding: 0 }}
                                                >
                                                    {tools.every(tool => definitionForm.tool_ids.includes(tool.id)) ? 'Clear' : 'Select all'}
                                                </button>
                                            </div>
                                            {tools.map(tool => (
                                                <label key={tool.id} style={{ display: 'flex', gap: '0.45rem', alignItems: 'flex-start', fontSize: '0.78rem', marginBottom: '0.4rem', cursor: 'pointer' }}>
                                                    <input
                                                        type="checkbox"
                                                        checked={definitionForm.tool_ids.includes(tool.id)}
                                                        onChange={() => toggleDefinitionTool(tool.id)}
                                                        style={{ marginTop: '0.15rem' }}
                                                    />
                                                    <span style={{ flex: 1 }}>
                                                        <span style={{ fontWeight: 600 }}>{tool.label}</span>
                                                        <span style={{ marginLeft: '0.35rem', fontSize: '0.68rem', color: tool.risk === 'high' ? 'var(--danger)' : tool.risk === 'medium' ? 'var(--warning)' : 'var(--success)' }}>{tool.risk}</span>
                                                        <span style={{ display: 'block', color: 'var(--text-secondary)', lineHeight: 1.35 }}>{tool.description}</span>
                                                    </span>
                                                </label>
                                            ))}
                                        </div>
                                    ))}
                                </div>
                                <div style={{ display: 'flex', gap: '0.5rem', marginTop: '0.75rem' }}>
                                    <button
                                        onClick={saveDefinition}
                                        disabled={savingDefinition}
                                        style={{ flex: 1, padding: '0.6rem', borderRadius: '6px', background: 'var(--primary)', color: 'white', border: 'none', fontWeight: 600, cursor: savingDefinition ? 'not-allowed' : 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '0.4rem' }}
                                    >
                                        {savingDefinition ? <Loader2 className="spin" size={14} /> : <Save size={14} />} Save
                                    </button>
                                    <button
                                        onClick={() => setBuilderOpen(false)}
                                        style={{ padding: '0.6rem 0.75rem', borderRadius: '6px', background: 'var(--surface-hover)', color: 'var(--text)', border: '1px solid var(--border)', cursor: 'pointer' }}
                                    >
                                        Cancel
                                    </button>
                                </div>
                            </div>
                        )}
                    </div>

                    {/* Configuration Form */}
                    <div className="card" style={{ padding: '1.25rem', flexShrink: 0 }}>
                        {selectedAgent === 'custom' && (
                            <div style={{ marginBottom: '1rem', padding: '0.75rem', background: 'var(--surface-hover)', borderRadius: '8px', border: '1px solid var(--border)' }}>
                                <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 500, marginBottom: '0.5rem' }}>Runnable Agent</label>
                                <select
                                    value={selectedDefinitionId}
                                    onChange={e => setSelectedDefinitionId(e.target.value)}
                                    style={{ width: '100%', padding: '0.6rem', borderRadius: '6px', fontSize: '0.9rem', border: '1px solid var(--input-border)', background: 'var(--input-bg)', color: 'var(--text)' }}
                                >
                                    <option value="">Select an agent</option>
                                    {agentDefinitions.map(definition => (
                                        <option key={definition.id} value={definition.id}>{definition.name}</option>
                                    ))}
                                </select>
                                {selectedDefinition && (
                                    <p style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', margin: '0.5rem 0 0' }}>
                                        {selectedDefinition.description || `${selectedDefinition.tool_ids.length} selected tools`}
                                    </p>
                                )}
                            </div>
                        )}

                        <div style={{ marginBottom: '1rem' }}>
                            <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 500, marginBottom: '0.5rem' }}>Target URL</label>
                            <input
                                type="text"
                                placeholder={selectedAgent === 'custom' ? 'Optional target URL' : 'https://example.com'}
                                value={url}
                                onChange={e => setUrl(e.target.value)}
                                style={{
                                    width: '100%', padding: '0.6rem', borderRadius: '6px', fontSize: '0.9rem',
                                    border: '1px solid var(--input-border)', background: 'var(--input-bg)', color: 'var(--text)'
                                }}
                            />
                        </div>

                        {selectedAgent === 'exploratory' && (
                            <>
                                <div style={{ marginBottom: '1rem' }}>
                                    <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 500, marginBottom: '0.5rem' }}>Time Limit (minutes)</label>
                                    <input
                                        type="number"
                                        min="2"
                                        max="60"
                                        value={timeLimitMinutes}
                                        onChange={e => setTimeLimitMinutes(parseInt(e.target.value) || 15)}
                                        style={{
                                            width: '100%', padding: '0.6rem', borderRadius: '6px', fontSize: '0.9rem',
                                            border: '1px solid var(--input-border)', background: 'var(--input-bg)', color: 'var(--text)'
                                        }}
                                    />
                                </div>

                                <div style={{ marginBottom: '1rem' }}>
                                    <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '0.8rem', fontWeight: 500, marginBottom: '0.5rem' }}>
                                        <Lock size={14} /> Authentication
                                    </label>
                                    <select
                                        value={authType}
                                        onChange={e => setAuthType(e.target.value as AuthType)}
                                        style={{
                                            width: '100%', padding: '0.6rem', borderRadius: '6px', fontSize: '0.9rem',
                                            border: '1px solid var(--input-border)', background: 'var(--input-bg)', color: 'var(--text)'
                                        }}
                                    >
                                        <option value="none">No Authentication</option>
                                        <option value="credentials">Credentials (Login Form)</option>
                                        <option value="session">Session (Saved)</option>
                                    </select>
                                </div>

                                {authType === 'credentials' && (
                                    <div style={{ marginBottom: '1rem', padding: '0.75rem', background: 'var(--surface-hover)', borderRadius: '6px' }}>
                                        <div style={{ marginBottom: '0.5rem' }}>
                                            <label style={{ fontSize: '0.75rem', fontWeight: 500 }}>Login URL</label>
                                            <input
                                                type="text"
                                                placeholder="/login"
                                                value={authCredentials.loginUrl}
                                                onChange={e => setAuthCredentials({ ...authCredentials, loginUrl: e.target.value })}
                                                style={{
                                                    width: '100%', padding: '0.5rem', borderRadius: '4px', fontSize: '0.85rem',
                                                    border: '1px solid var(--input-border)', background: 'var(--input-bg)', color: 'var(--text)'
                                                }}
                                            />
                                        </div>
                                        <div style={{ marginBottom: '0.5rem' }}>
                                            <label style={{ fontSize: '0.75rem', fontWeight: 500 }}>Username</label>
                                            <input
                                                type="text"
                                                placeholder="testuser"
                                                value={authCredentials.username}
                                                onChange={e => setAuthCredentials({ ...authCredentials, username: e.target.value })}
                                                style={{
                                                    width: '100%', padding: '0.5rem', borderRadius: '4px', fontSize: '0.85rem',
                                                    border: '1px solid var(--input-border)', background: 'var(--input-bg)', color: 'var(--text)'
                                                }}
                                            />
                                        </div>
                                        <div>
                                            <label style={{ fontSize: '0.75rem', fontWeight: 500 }}>Password</label>
                                            <input
                                                type="password"
                                                placeholder="••••••••"
                                                value={authCredentials.password}
                                                onChange={e => setAuthCredentials({ ...authCredentials, password: e.target.value })}
                                                style={{
                                                    width: '100%', padding: '0.5rem', borderRadius: '4px', fontSize: '0.85rem',
                                                    border: '1px solid var(--input-border)', background: 'var(--input-bg)', color: 'var(--text)'
                                                }}
                                            />
                                        </div>
                                    </div>
                                )}

                                {authType === 'session' && (
                                    <div style={{ marginBottom: '1rem', padding: '0.75rem', background: 'var(--surface-hover)', borderRadius: '6px' }}>
                                        <label style={{ fontSize: '0.75rem', fontWeight: 500, marginBottom: '0.5rem', display: 'block' }}>Session ID</label>
                                        <input
                                            type="text"
                                            placeholder="my-session"
                                            value={sessionId}
                                            onChange={e => setSessionId(e.target.value)}
                                            list="sessions-list"
                                            style={{
                                                width: '100%', padding: '0.5rem', borderRadius: '4px', fontSize: '0.85rem',
                                                border: '1px solid var(--input-border)', background: 'var(--input-bg)', color: 'var(--text)'
                                            }}
                                        />
                                        <datalist id="sessions-list">
                                            {sessions.map(s => (
                                                <option key={s.session_id} value={s.session_id} />
                                            ))}
                                        </datalist>
                                        <p style={{ fontSize: '0.7rem', color: 'var(--text-secondary)', marginTop: '0.5rem' }}>
                                            {sessions.length} saved session{sessions.length !== 1 ? 's' : ''} available
                                        </p>
                                    </div>
                                )}
                            </>
                        )}

                        <div style={{ marginBottom: '1.25rem' }}>
                            <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 500, marginBottom: '0.5rem' }}>
                                {selectedAgent === 'custom' ? 'Task Prompt' : 'Instructions (Optional)'}
                            </label>
                            <textarea
                                placeholder={selectedAgent === 'custom' ? "Inspect the API calls triggered by the login and checkout flows." : selectedAgent === 'exploratory' ? "Focus on checkout flow, test edge cases..." : "Generate spec for login page..."}
                                value={instructions}
                                onChange={e => setInstructions(e.target.value)}
                                rows={3}
                                style={{
                                    width: '100%', padding: '0.6rem', borderRadius: '6px', fontSize: '0.9rem',
                                    border: '1px solid var(--input-border)', background: 'var(--input-bg)', color: 'var(--text)',
                                    resize: 'vertical'
                                }}
                            />
                        </div>

                        {selectedAgent === 'exploratory' && (
                            <button
                                onClick={() => setShowAdvanced(!showAdvanced)}
                                style={{
                                    width: '100%', padding: '0.5rem', marginBottom: '0.75rem', borderRadius: '6px', fontSize: '0.85rem',
                                    background: 'var(--surface-hover)', color: 'var(--text)', fontWeight: 500, border: '1px solid var(--border)',
                                    display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '0.5rem', cursor: 'pointer'
                                }}
                            >
                                <Settings size={14} /> {showAdvanced ? 'Hide' : 'Show'} Advanced Options
                            </button>
                        )}

                        {showAdvanced && selectedAgent === 'exploratory' && (
                            <>
                                <div style={{ marginBottom: '1rem' }}>
                                    <label style={{ fontSize: '0.8rem', fontWeight: 500, marginBottom: '0.5rem', display: 'block' }}>
                                        Test Data (JSON)
                                    </label>
                                    <textarea
                                        placeholder='{"usernames": ["testuser", "admin"], "emails": ["test@example.com", ""]}'
                                        value={testData}
                                        onChange={e => setTestData(e.target.value)}
                                        rows={3}
                                        style={{
                                            width: '100%', padding: '0.6rem', borderRadius: '6px', fontSize: '0.85rem',
                                            border: '1px solid var(--input-border)', background: 'var(--input-bg)', color: 'var(--text)',
                                            resize: 'vertical', fontFamily: 'monospace'
                                        }}
                                    />
                                </div>

                                <div style={{ marginBottom: '1rem' }}>
                                    <label style={{ fontSize: '0.8rem', fontWeight: 500, marginBottom: '0.5rem', display: 'block' }}>
                                        Focus Areas (comma-separated)
                                    </label>
                                    <input
                                        type="text"
                                        placeholder="checkout, user-profile, search"
                                        value={focusAreas}
                                        onChange={e => setFocusAreas(e.target.value)}
                                        style={{
                                            width: '100%', padding: '0.6rem', borderRadius: '6px', fontSize: '0.9rem',
                                            border: '1px solid var(--input-border)', background: 'var(--input-bg)', color: 'var(--text)'
                                        }}
                                    />
                                </div>

                                <div style={{ marginBottom: '1rem' }}>
                                    <label style={{ fontSize: '0.8rem', fontWeight: 500, marginBottom: '0.5rem', display: 'block' }}>
                                        Excluded URL Patterns (comma-separated)
                                    </label>
                                    <input
                                        type="text"
                                        placeholder="/logout, /delete-account"
                                        value={excludedPatterns}
                                        onChange={e => setExcludedPatterns(e.target.value)}
                                        style={{
                                            width: '100%', padding: '0.6rem', borderRadius: '6px', fontSize: '0.9rem',
                                            border: '1px solid var(--input-border)', background: 'var(--input-bg)', color: 'var(--text)'
                                        }}
                                    />
                                </div>
                            </>
                        )}

                        <button
                            onClick={handleRun}
                            disabled={isStarting}
                            style={{
                                width: '100%', padding: '0.75rem', borderRadius: '6px', fontSize: '0.9rem',
                                background: 'var(--primary)', color: 'white', fontWeight: 600, border: 'none', cursor: isStarting ? 'not-allowed' : 'pointer',
                                display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '0.5rem',
                                opacity: isStarting ? 0.7 : 1
                            }}
                        >
                            {isStarting ? <><Loader2 className="spin" size={16} /> Starting...</> : <><Play size={16} /> Start Agent</>}
                        </button>
                    </div>
                </div>

                {/* Right Column: Output */}
                <div className="card" style={{ padding: '0', display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>
                    <div style={{ padding: '0.75rem 1rem', borderBottom: '1px solid var(--border)', background: 'var(--surface-hover)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <h3 style={{ fontWeight: 600, fontSize: '0.9rem' }}>
                            {activeRun ? `Result: ${activeRun.config?.agent_name || activeRun.config?.url || 'Unknown'}` : 'Agent Output'}
                        </h3>
                        {activeRun && (
                            <span style={{
                                fontSize: '0.75rem', padding: '0.2rem 0.6rem', borderRadius: '12px',
                                background: activeRun.status === 'completed' ? 'var(--success-muted)' : activeRun.status === 'failed' ? 'var(--danger-muted)' : 'var(--primary-glow)',
                                color: activeRun.status === 'completed' ? 'var(--success)' : activeRun.status === 'failed' ? 'var(--danger)' : 'var(--primary)'
                            }}>
                                {activeRun.status}
                            </span>
                        )}
                    </div>

                    <div style={{ padding: '1.5rem', flex: 1, overflowY: 'auto', background: 'var(--surface)' }}>
                        {!activeRun ? (
                            <div style={{ height: '100%', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', color: 'var(--text-secondary)', opacity: 0.5 }}>
                                <Bot size={64} style={{ marginBottom: '1rem' }} />
                                <p>Select a run from history or start a new one.</p>
                            </div>
                        ) : ['running', 'pending', 'queued'].includes(activeRun.status) && activeRun.agent_type === 'custom' ? (
                            (() => {
                                const progress = activeRun.progress || {};
                                const selectedTools = activeRun.config?.selected_tools || [];
                                const hasBrowserTools = Boolean(progress.has_browser_tools) || selectedTools.some((tool: AgentTool) => tool.tool_name?.startsWith('mcp__playwright'));
                                const latestImage = sortArtifactsByModifiedAt((activeRun.artifacts || []).filter(artifact => artifact.type === 'image'))[0];
                                const recentTools = progress.recent_tools || [];
                                return (
                                    <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                                        <div style={{
                                            display: 'grid',
                                            gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))',
                                            gap: '0.75rem',
                                            padding: '1rem',
                                            background: 'var(--surface-hover)',
                                            border: '1px solid var(--border)',
                                            borderRadius: '10px'
                                        }}>
                                            <div>
                                                <div style={{ fontSize: '0.72rem', color: 'var(--text-secondary)', textTransform: 'uppercase', marginBottom: '0.25rem' }}>Status</div>
                                                <div style={{ fontWeight: 700, textTransform: 'capitalize' }}>{activeRun.status}</div>
                                            </div>
                                            <div>
                                                <div style={{ fontSize: '0.72rem', color: 'var(--text-secondary)', textTransform: 'uppercase', marginBottom: '0.25rem' }}>Current Tool</div>
                                                <div style={{ fontWeight: 600, overflowWrap: 'anywhere' }}>{progress.last_tool_label || formatToolName(progress.last_tool)}</div>
                                            </div>
                                            <div>
                                                <div style={{ fontSize: '0.72rem', color: 'var(--text-secondary)', textTransform: 'uppercase', marginBottom: '0.25rem' }}>Tool Calls</div>
                                                <div style={{ fontWeight: 700 }}>{progress.tool_calls ?? 0}</div>
                                            </div>
                                            <div>
                                                <div style={{ fontSize: '0.72rem', color: 'var(--text-secondary)', textTransform: 'uppercase', marginBottom: '0.25rem' }}>Browser Actions</div>
                                                <div style={{ fontWeight: 700 }}>{progress.browser_tool_calls ?? 0}</div>
                                            </div>
                                        </div>

                                        {hasBrowserTools ? (
                                            <LiveBrowserView runId={activeRun.id} isActive={true} showHeader />
                                        ) : (
                                            <div style={{ padding: '1.25rem', background: 'var(--surface-hover)', border: '1px solid var(--border)', borderRadius: '10px', color: 'var(--text-secondary)', textAlign: 'center' }}>
                                                This custom agent does not have browser tools selected. Follow its tool activity below.
                                            </div>
                                        )}

                                        <div style={{ border: '1px solid var(--border)', borderRadius: '10px', overflow: 'hidden', background: 'var(--background)' }}>
                                            <div style={{ padding: '0.75rem 1rem', borderBottom: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', gap: '1rem' }}>
                                                <h4 style={{ margin: 0, fontSize: '0.95rem', fontWeight: 600 }}>Latest Screenshot</h4>
                                                {latestImage?.modified_at && (
                                                    <span style={{ fontSize: '0.78rem', color: 'var(--text-secondary)' }}>
                                                        {new Date(latestImage.modified_at).toLocaleTimeString()}
                                                    </span>
                                                )}
                                            </div>
                                            {latestImage ? (
                                                <a href={getArtifactUrl(latestImage)} target="_blank" rel="noreferrer" style={{ display: 'block' }}>
                                                    <img
                                                        src={getArtifactUrl(latestImage)}
                                                        alt="Latest custom agent screenshot"
                                                        style={{ width: '100%', display: 'block', maxHeight: '420px', objectFit: 'contain', background: '#000' }}
                                                    />
                                                </a>
                                            ) : (
                                                <div style={{ padding: '1.5rem', textAlign: 'center', color: 'var(--text-secondary)', fontSize: '0.9rem' }}>
                                                    No screenshots have been captured yet. Select the Screenshot tool for visual fallback.
                                                </div>
                                            )}
                                        </div>

                                        <div style={{ border: '1px solid var(--border)', borderRadius: '10px', overflow: 'hidden' }}>
                                            <div style={{ padding: '0.75rem 1rem', borderBottom: '1px solid var(--border)', fontWeight: 600 }}>
                                                Live Activity
                                            </div>
                                            {recentTools.length > 0 ? (
                                                <div style={{ display: 'grid' }}>
                                                    {recentTools.slice().reverse().map((tool: any, i: number) => (
                                                        <div key={`${tool.name}-${tool.at}-${i}`} style={{ padding: '0.65rem 1rem', borderBottom: i === recentTools.length - 1 ? 'none' : '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', gap: '1rem', fontSize: '0.85rem' }}>
                                                            <span style={{ fontWeight: 600 }}>{tool.label || formatToolName(tool.name)}</span>
                                                            {tool.at && <span style={{ color: 'var(--text-secondary)' }}>{new Date(tool.at).toLocaleTimeString()}</span>}
                                                        </div>
                                                    ))}
                                                </div>
                                            ) : (
                                                <div style={{ padding: '1rem', color: 'var(--text-secondary)', fontSize: '0.9rem' }}>
                                                    Waiting for the agent to use its first tool.
                                                </div>
                                            )}
                                        </div>

                                        <p style={{ margin: 0, color: 'var(--text-secondary)', fontSize: '0.85rem', textAlign: 'center' }}>
                                            {progress.message || `This may take up to ${Math.ceil((activeRun.config?.timeout_seconds || 1800) / 60)} minutes.`}
                                        </p>
                                    </div>
                                );
                            })()
                        ) : ['running', 'pending', 'queued'].includes(activeRun.status) ? (
                            <div style={{ height: '100%', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', color: 'var(--text-secondary)' }}>
                                <Loader2 size={48} className="spin" style={{ marginBottom: '1rem', color: 'var(--primary)' }} />
                                <p>Agent is working...</p>
                                <p style={{ fontSize: '0.9rem', marginTop: '0.5rem' }}>
                                    This may take up to {activeRun.agent_type === 'custom' ? Math.ceil((activeRun.config?.timeout_seconds || 1800) / 60) : timeLimitMinutes} minutes.
                                </p>
                            </div>
                        ) : activeRun.status === 'failed' ? (
                            <div style={{ padding: '1rem', background: 'var(--danger-muted)', color: 'var(--danger)', borderRadius: '8px', border: '1px solid rgba(248, 113, 113, 0.2)' }}>
                                <h4 style={{ fontWeight: 600, display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                                    <AlertTriangle size={18} /> Run Failed
                                </h4>
                                <p style={{ marginTop: '0.5rem', fontFamily: 'monospace' }}>
                                    {activeRun.result?.error || "Unknown error occurred"}
                                </p>
                            </div>
                        ) : (
                            // Completed successfully
                            <div className="markdown-content">
                                {activeRun.agent_type === 'writer' ? (
                                    <>
                                        <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: '1rem' }}>
                                            <button
                                                onClick={() => downloadSpec(activeRun.result.spec_content || '', 'spec.md')}
                                                style={{ fontSize: '0.85rem', padding: '0.4rem 0.8rem', background: 'var(--primary)', color: 'white', border: 'none', borderRadius: '4px', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '0.5rem' }}
                                            >
                                                <Download size={14} /> Download Spec
                                            </button>
                                        </div>
                                        <div style={{ background: '#1e1e1e', padding: '1.5rem', borderRadius: '8px', border: '1px solid var(--border)' }}>
                                            <pre style={{ whiteSpace: 'pre-wrap', fontFamily: 'monospace', fontSize: '0.9rem', color: '#e5e5e5' }}>
                                                {activeRun.result.spec_content || JSON.stringify(activeRun.result, null, 2)}
                                            </pre>
                                        </div>
                                    </>
                                ) : activeRun.agent_type === 'custom' ? (
                                    <CustomAgentReportView
                                        run={activeRun}
                                        activeTab={customResultTab}
                                        onTabChange={setCustomResultTab}
                                        onAskAssistant={openAssistantWithPrompt}
                                    />
                                ) : (
                                    // Exploratory Result - User Friendly Display
                                    <div style={{ display: 'flex', flexDirection: 'column', gap: '2rem' }}>
                                        {!activeRun.result ? (
                                            <div style={{ padding: '2rem', background: 'var(--primary-glow)', borderRadius: '12px', color: 'var(--primary)', textAlign: 'center' }}>
                                                <Loader2 size={32} className="spin" style={{ marginBottom: '1rem' }} />
                                                <p style={{ fontSize: '1rem', fontWeight: 500 }}>Loading exploration results...</p>
                                                <p style={{ fontSize: '0.9rem', color: 'var(--text-secondary)', marginTop: '0.5rem' }}>
                                                    This may take a moment while we compile the findings.
                                                </p>
                                            </div>
                                        ) : (
                                            <>
                                                {/* Main Summary Card */}
                                                <div style={{ padding: '1.5rem', background: 'linear-gradient(135deg, var(--primary-glow) 0%, rgba(192, 132, 252, 0.1) 100%)', borderRadius: '12px', border: '1px solid rgba(59, 130, 246, 0.2)' }}>
                                                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '1rem' }}>
                                                        <div style={{ width: '40px', height: '40px', borderRadius: '10px', background: 'var(--primary)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                                                            <Sparkles size={20} style={{ color: 'white' }} />
                                                        </div>
                                                        <div>
                                                            <h3 style={{ fontWeight: 700, fontSize: '1.2rem', margin: 0 }}>Exploration Complete!</h3>
                                                            <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', margin: '0.5rem 0 0 0' }}>
                                                                {activeRun.result.elapsed_time_minutes ? `Completed in ${activeRun.result.elapsed_time_minutes.toFixed(1)} minutes` : 'Completed'}
                                                            </p>
                                                        </div>
                                                    </div>
                                                    <p style={{ fontSize: '1rem', lineHeight: '1.6', margin: 0 }}>
                                                        {activeRun.result.summary || 'The agent explored the application and discovered user flows.'}
                                                    </p>
                                                </div>

                                                {/* Key Metrics */}
                                                {activeRun.result.coverage && (
                                                    <div>
                                                        <h4 style={{ fontWeight: 600, fontSize: '1rem', marginBottom: '1rem', color: 'var(--text)' }}>
                                                            📊 What Was Explored
                                                        </h4>
                                                        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: '1rem' }}>
                                                            <div style={{ padding: '1rem', background: 'var(--surface-hover)', borderRadius: '10px', border: '1px solid var(--border)' }}>
                                                                <div style={{ fontSize: '2rem', fontWeight: 700, color: 'var(--primary)' }}>
                                                                    {activeRun.result.coverage.pages_visited || 0}
                                                                </div>
                                                                <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginTop: '0.25rem' }}>
                                                                    Pages Visited
                                                                </div>
                                                            </div>
                                                            <div style={{ padding: '1rem', background: 'var(--surface-hover)', borderRadius: '10px', border: '1px solid var(--border)' }}>
                                                                <div style={{ fontSize: '2rem', fontWeight: 700, color: 'var(--success)' }}>
                                                                    {activeRun.result.coverage.flows_discovered || 0}
                                                                </div>
                                                                <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginTop: '0.25rem' }}>
                                                                    User Flows Found
                                                                </div>
                                                            </div>
                                                            <div style={{ padding: '1rem', background: 'var(--surface-hover)', borderRadius: '10px', border: '1px solid var(--border)' }}>
                                                                <div style={{ fontSize: '2rem', fontWeight: 700, color: 'var(--warning)' }}>
                                                                    {activeRun.result.coverage.forms_interacted || 0}
                                                                </div>
                                                                <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginTop: '0.25rem' }}>
                                                                    Forms Tested
                                                                </div>
                                                            </div>
                                                            {activeRun.result.coverage.errors_found !== undefined && (
                                                                <div style={{ padding: '1rem', background: 'var(--surface-hover)', borderRadius: '10px', border: '1px solid var(--border)' }}>
                                                                    <div style={{ fontSize: '2rem', fontWeight: 700, color: activeRun.result.coverage.errors_found > 0 ? 'var(--danger)' : 'var(--success)' }}>
                                                                        {activeRun.result.coverage.errors_found || 0}
                                                                    </div>
                                                                    <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginTop: '0.25rem' }}>
                                                                        Issues Found
                                                                    </div>
                                                                </div>
                                                            )}
                                                        </div>
                                                        {activeRun.result.coverage.coverage_score !== undefined && (
                                                            <div style={{ marginTop: '1rem', padding: '0.75rem', background: activeRun.result.coverage.coverage_score > 0.7 ? 'var(--success-muted)' : 'var(--warning-muted)', borderRadius: '8px', border: `1px solid ${activeRun.result.coverage.coverage_score > 0.7 ? 'rgba(52, 211, 153, 0.2)' : 'rgba(251, 191, 36, 0.2)'}` }}>
                                                                <span style={{ fontSize: '0.85rem', fontWeight: 500 }}>
                                                                    Coverage Score: <strong>{(activeRun.result.coverage.coverage_score * 100).toFixed(0)}%</strong>
                                                                    {activeRun.result.coverage.coverage_score > 0.7 ? ' ✅ Good coverage' : ' ⚠️ Consider exploring more'}
                                                                </span>
                                                            </div>
                                                        )}
                                                    </div>
                                                )}

                                                {/* Discovered Flows - Clear Display */}
                                                {activeRun.result.discovered_flow_summaries && activeRun.result.discovered_flow_summaries.length > 0 ? (
                                                    <div>
                                                        <h4 style={{ fontWeight: 600, fontSize: '1rem', marginBottom: '1rem', color: 'var(--text)' }}>
                                                            🔍 Discovered User Flows ({activeRun.result.total_flows_discovered || activeRun.result.discovered_flow_summaries.length})
                                                        </h4>
                                                        <p style={{ fontSize: '0.9rem', color: 'var(--text-secondary)', marginBottom: '1rem' }}>
                                                            These are the complete user journeys the agent found. Each one can be turned into a test.
                                                        </p>
                                                        <div style={{ display: 'grid', gap: '1rem' }}>
                                                            {activeRun.result.discovered_flow_summaries.map((flow: any, i: number) => (
                                                                <div key={i} style={{
                                                                    padding: '1rem',
                                                                    background: 'var(--surface)',
                                                                    borderRadius: '10px',
                                                                    border: '1px solid var(--border)',
                                                                    transition: 'all 0.2s'
                                                                }}>
                                                                    <div style={{ display: 'flex', alignItems: 'flex-start', gap: '0.75rem' }}>
                                                                        <div style={{
                                                                            width: '32px',
                                                                            height: '32px',
                                                                            borderRadius: '8px',
                                                                            background: 'var(--primary-glow)',
                                                                            display: 'flex',
                                                                            alignItems: 'center',
                                                                            justifyContent: 'center',
                                                                            flexShrink: 0,
                                                                            fontSize: '1.2rem'
                                                                        }}>
                                                                            {i + 1}
                                                                        </div>
                                                                        <div style={{ flex: 1 }}>
                                                                            <h5 style={{ fontWeight: 600, fontSize: '1rem', margin: '0 0 0.5rem 0' }}>
                                                                                {flow.title}
                                                                            </h5>
                                                                            <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '0.5rem' }}>
                                                                                <span style={{ fontWeight: 500 }}>{flow.steps_count} steps</span>
                                                                                {flow.entry_point && <span> • Starts: {flow.entry_point}</span>}
                                                                                {flow.exit_point && <span> • Ends: {flow.exit_point}</span>}
                                                                            </div>
                                                                            {flow.pages && flow.pages.length > 0 && (
                                                                                <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '0.5rem' }}>
                                                                                    <span style={{ fontWeight: 500 }}>Pages:</span> {flow.pages.join(' → ')}
                                                                                </div>
                                                                            )}
                                                                            {flow.has_edge_cases && (
                                                                                <div style={{ marginTop: '0.5rem', padding: '0.5rem', background: 'var(--warning-muted)', borderRadius: '6px' }}>
                                                                                    <div style={{ fontSize: '0.75rem', fontWeight: 500, color: 'var(--warning)' }}>
                                                                                        ⚠️ Includes edge cases
                                                                                    </div>
                                                                                </div>
                                                                            )}
                                                                        </div>
                                                                        <button
                                                                            onClick={() => fetchFlowDetails(flow.id)}
                                                                            disabled={loadingFlowDetails}
                                                                            style={{
                                                                                padding: '0.5rem 1rem',
                                                                                background: 'var(--primary)',
                                                                                color: 'white',
                                                                                border: 'none',
                                                                                borderRadius: '6px',
                                                                                fontSize: '0.85rem',
                                                                                fontWeight: 500,
                                                                                cursor: loadingFlowDetails ? 'not-allowed' : 'pointer',
                                                                                opacity: loadingFlowDetails ? 0.6 : 1,
                                                                                whiteSpace: 'nowrap'
                                                                            }}
                                                                        >
                                                                            {loadingFlowDetails ? 'Loading...' : 'View Details'}
                                                                        </button>
                                                                    </div>
                                                                </div>
                                                            ))}
                                                        </div>
                                                    </div>
                                                ) : (
                                                    <div style={{ padding: '2rem', background: 'var(--warning-muted)', borderRadius: '12px', textAlign: 'center' }}>
                                                        <h4 style={{ margin: '0 0 0.5rem 0' }}>No flows discovered</h4>
                                                        <p style={{ fontSize: '0.9rem', color: 'var(--text-secondary)', margin: 0 }}>
                                                            The agent didn't find any complete user flows. Try increasing the time limit or exploring a different area.
                                                        </p>
                                                    </div>
                                                )}

                                            {/* Next Steps */}
                                            <div style={{ marginTop: '1.5rem', padding: '1.25rem', background: 'linear-gradient(135deg, var(--success-muted) 0%, var(--primary-glow) 100%)', borderRadius: '12px', border: '1px solid rgba(52, 211, 153, 0.2)' }}>
                                                <h4 style={{ fontWeight: 600, fontSize: '1rem', marginBottom: '0.75rem', display: 'flex', alignItems: 'center', gap: '0.5rem', color: 'var(--text)' }}>
                                                    <ArrowRight size={18} style={{ color: 'var(--success)' }} /> Next Steps
                                                </h4>
                                                <div style={{ fontSize: '0.9rem', lineHeight: '1.6' }}>
                                                    <p style={{ margin: '0 0 0.5rem 0', color: 'var(--text)' }}>
                                                        <strong>1. Review the discovered flows above</strong> - Make sure they capture the user journeys you want to test
                                                    </p>
                                                    <p style={{ margin: '0 0 0.5rem 0', color: 'var(--text)' }}>
                                                        <strong>2. Click "Generate Test Specs" below</strong> - This creates detailed test specifications for each flow
                                                    </p>
                                                    <p style={{ margin: '0 0 0.75rem 0', color: 'var(--text)' }}>
                                                        <strong>3. Download and run the specs</strong> - Use them with the existing pipeline to generate Playwright tests
                                                    </p>
                                                    <div style={{ padding: '0.75rem', background: 'var(--primary-glow)', borderRadius: '8px', fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
                                                        <Info size={14} style={{ marginRight: '0.5rem', display: 'inline', verticalAlign: 'middle' }} />
                                                        <span style={{ fontStyle: 'italic' }}>Tip: Each discovered flow becomes a separate test spec. You can edit them before running if needed.</span>
                                                    </div>
                                                </div>
                                            </div>

                                            {/* Spec Synthesis Button */}
                                            {activeRun.agent_type === 'exploratory' && (
                                            <div style={{ display: 'flex', gap: '0.5rem' }}>
                                                <button
                                                    onClick={handleSynthesize}
                                                    disabled={isSynthesizing}
                                                    style={{
                                                        flex: 1, padding: '0.75rem', borderRadius: '6px', fontSize: '0.9rem',
                                                        background: 'var(--primary)', color: 'white', fontWeight: 600, border: 'none',
                                                        cursor: isSynthesizing ? 'not-allowed' : 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '0.5rem',
                                                        opacity: isSynthesizing ? 0.7 : 1
                                                    }}
                                                >
                                                    {isSynthesizing ? <><Loader2 className="spin" size={16} /> Generating...</> : <><Sparkles size={16} /> Generate Test Specs</>}
                                                </button>
                                            </div>
                                        )}

                                        {/* Generated Specs */}
                                        {specResult && specResult.specs && (
                                            <div>
                                                <h4 style={{ fontWeight: 600, marginBottom: '0.5rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                                                    <FileText size={18} /> Generated Specs ({specResult.total_specs || 0})
                                                </h4>
                                                <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: '1rem' }}>{specResult.summary}</p>

                                                {/* Happy Path Specs */}
                                                {specResult.specs.happy_path && Object.keys(specResult.specs.happy_path).length > 0 && (
                                                    <div style={{ marginBottom: '1rem' }}>
                                                        <h5 style={{ fontSize: '0.85rem', color: 'var(--success)', marginBottom: '0.5rem' }}>Happy Path Specs</h5>
                                                        {Object.entries(specResult.specs.happy_path).map(([filename, content]) => (
                                                            <div key={filename} style={{ marginBottom: '0.5rem' }}>
                                                                <button
                                                                    onClick={() => downloadSpec(content, filename)}
                                                                    style={{
                                                                        fontSize: '0.8rem', padding: '0.3rem 0.6rem', background: 'var(--surface-hover)',
                                                                        border: '1px solid var(--border)', borderRadius: '4px', cursor: 'pointer',
                                                                        display: 'flex', alignItems: 'center', gap: '0.5rem', width: '100%'
                                                                    }}
                                                                >
                                                                    <Download size={12} /> {filename}
                                                                </button>
                                                            </div>
                                                        ))}
                                                    </div>
                                                )}

                                                {/* Edge Case Specs */}
                                                {specResult.specs.edge_cases && Object.keys(specResult.specs.edge_cases).length > 0 && (
                                                    <div>
                                                        <h5 style={{ fontSize: '0.85rem', color: 'var(--warning)', marginBottom: '0.5rem' }}>Edge Case Specs</h5>
                                                        {Object.entries(specResult.specs.edge_cases).map(([filename, content]) => (
                                                            <div key={filename} style={{ marginBottom: '0.5rem' }}>
                                                                <button
                                                                    onClick={() => downloadSpec(content, filename)}
                                                                    style={{
                                                                        fontSize: '0.8rem', padding: '0.3rem 0.6rem', background: 'var(--surface-hover)',
                                                                        border: '1px solid var(--border)', borderRadius: '4px', cursor: 'pointer',
                                                                        display: 'flex', alignItems: 'center', gap: '0.5rem', width: '100%'
                                                                    }}
                                                                >
                                                                    <Download size={12} /> {filename}
                                                                </button>
                                                            </div>
                                                        ))}
                                                    </div>
                                                )}
                                            </div>
                                        )}

                                        {/* Action Trace */}
                                        {activeRun.result.action_trace && activeRun.result.action_trace.length > 0 && (
                                            <details style={{ marginTop: '1.5rem' }}>
                                                <summary style={{ cursor: 'pointer', fontWeight: 600, fontSize: '0.9rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                                                    <Terminal size={16} /> What the Agent Did ({activeRun.result.action_trace.length} actions)
                                                </summary>
                                                <div style={{ marginTop: '0.5rem', background: '#0f0f0f', padding: '1rem', borderRadius: '8px', fontSize: '0.85rem', fontFamily: 'monospace', maxHeight: '250px', overflowY: 'auto' }}>
                                                    {activeRun.result.action_trace.map((action: any, i: number) => (
                                                        <div key={i} style={{ marginBottom: '0.25rem', color: '#a3a3a3', lineHeight: '1.4' }}>
                                                            <span style={{ color: 'var(--primary)', fontWeight: 500 }}>[{action.step}]</span> {action.action} {action.target} - {action.outcome}
                                                            {action.is_new_discovery && <span style={{ color: 'var(--success)', marginLeft: '0.5rem' }}>✨ New Discovery</span>}
                                                        </div>
                                                    ))}
                                                </div>
                                                <p style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginTop: '0.5rem', fontStyle: 'italic' }}>
                                                    This shows every action the agent took during exploration. "New Discovery" means the agent found something new.
                                                </p>
                                            </details>
                                        )}
                                        </>
                                    )}
                                    </div>
                                )}
                            </div>
                        )}
                    </div>
                </div>

                {/* Flow Details Modal */}
                {flowModalOpen && selectedFlow && (
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
                        padding: '1rem'
                    }}>
                        <div style={{
                            background: 'var(--surface)',
                            borderRadius: '12px',
                            maxWidth: '700px',
                            maxHeight: '80vh',
                            overflowY: 'auto',
                            padding: '1.5rem',
                            position: 'relative',
                            border: '1px solid var(--border)'
                        }}>
                            <button
                                onClick={() => setFlowModalOpen(false)}
                                style={{
                                    position: 'absolute',
                                    top: '1rem',
                                    right: '1rem',
                                    background: 'transparent',
                                    border: 'none',
                                    cursor: 'pointer',
                                    color: 'var(--text-secondary)'
                                }}
                            >
                                <X size={20} />
                            </button>

                            <h3 style={{ margin: '0 0 1rem 0', fontSize: '1.3rem', fontWeight: 600 }}>
                                {selectedFlow.title}
                            </h3>

                            {selectedFlow.pages && selectedFlow.pages.length > 0 && (
                                <div style={{ marginBottom: '1rem' }}>
                                    <h4 style={{ fontSize: '0.9rem', fontWeight: 600, marginBottom: '0.5rem' }}>Pages</h4>
                                    <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
                                        {selectedFlow.pages.map((page: string, i: number) => (
                                            <span key={i} style={{
                                                padding: '0.25rem 0.5rem',
                                                background: 'var(--surface-hover)',
                                                borderRadius: '4px',
                                                fontSize: '0.8rem'
                                            }}>
                                                {page}
                                            </span>
                                        ))}
                                    </div>
                                </div>
                            )}

                            {selectedFlow.happy_path && (
                                <div style={{ marginBottom: '1rem' }}>
                                    <h4 style={{ fontSize: '0.9rem', fontWeight: 600, marginBottom: '0.5rem', color: 'var(--success)' }}>Happy Path</h4>
                                    <p style={{ fontSize: '0.9rem', lineHeight: '1.5', margin: 0 }}>
                                        {selectedFlow.happy_path}
                                    </p>
                                </div>
                            )}

                            {selectedFlow.edge_cases && selectedFlow.edge_cases.length > 0 && (
                                <div style={{ marginBottom: '1rem' }}>
                                    <h4 style={{ fontSize: '0.9rem', fontWeight: 600, marginBottom: '0.5rem', color: 'var(--warning)' }}>Edge Cases</h4>
                                    <ul style={{ margin: 0, paddingLeft: '1.5rem' }}>
                                        {selectedFlow.edge_cases.map((ec: string, i: number) => (
                                            <li key={i} style={{ fontSize: '0.9rem', marginBottom: '0.25rem' }}>{ec}</li>
                                        ))}
                                    </ul>
                                </div>
                            )}

                            {selectedFlow.test_ideas && selectedFlow.test_ideas.length > 0 && (
                                <div style={{ marginBottom: '1rem' }}>
                                    <h4 style={{ fontSize: '0.9rem', fontWeight: 600, marginBottom: '0.5rem' }}>Test Ideas</h4>
                                    <ul style={{ margin: 0, paddingLeft: '1.5rem' }}>
                                        {selectedFlow.test_ideas.map((idea: string, i: number) => (
                                            <li key={i} style={{ fontSize: '0.9rem', marginBottom: '0.25rem' }}>{idea}</li>
                                        ))}
                                    </ul>
                                </div>
                            )}

                            {selectedFlow.entry_point && (
                                <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '1rem' }}>
                                    Entry: {selectedFlow.entry_point}
                                    {selectedFlow.exit_point && ` → Exit: ${selectedFlow.exit_point}`}
                                </div>
                            )}

                            <div style={{ display: 'flex', gap: '0.75rem', marginTop: '1rem', paddingTop: '1rem', borderTop: '1px solid var(--border)' }}>
                                <button
                                    onClick={() => generateFlowSpec(selectedFlow.id)}
                                    disabled={generatingSpec}
                                    style={{
                                        flex: 1,
                                        padding: '0.75rem 1rem',
                                        background: 'var(--primary)',
                                        color: 'white',
                                        border: 'none',
                                        borderRadius: '8px',
                                        fontSize: '0.9rem',
                                        fontWeight: 500,
                                        cursor: generatingSpec ? 'not-allowed' : 'pointer',
                                        opacity: generatingSpec ? 0.6 : 1,
                                        display: 'flex',
                                        alignItems: 'center',
                                        justifyContent: 'center',
                                        gap: '0.5rem'
                                    }}
                                >
                                    {generatingSpec ? (
                                        <>
                                            <Loader2 size={16} className="spin" />
                                            {flowSpecPoller.status?.message || 'Generating...'}
                                        </>
                                    ) : selectedFlow.generated_spec ? (
                                        <>
                                            <FileText size={16} />
                                            View Test Spec
                                        </>
                                    ) : (
                                        <>
                                            <FileText size={16} />
                                            Generate Test Spec
                                        </>
                                    )}
                                </button>
                                <button
                                    onClick={() => setFlowModalOpen(false)}
                                    style={{
                                        padding: '0.75rem 1.5rem',
                                        background: 'transparent',
                                        color: 'var(--text-secondary)',
                                        border: '1px solid var(--border)',
                                        borderRadius: '8px',
                                        fontSize: '0.9rem',
                                        fontWeight: 500,
                                        cursor: 'pointer'
                                    }}
                                >
                                    Close
                                </button>
                            </div>
                        </div>
                    </div>
                )}

                {/* Generated Spec Modal */}
                {specModalOpen && generatedSpec && (
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
                        zIndex: 1001,
                        padding: '1rem'
                    }}>
                        <div style={{
                            background: 'var(--surface)',
                            borderRadius: '12px',
                            maxWidth: '800px',
                            maxHeight: '85vh',
                            width: '100%',
                            overflow: 'hidden',
                            display: 'flex',
                            flexDirection: 'column',
                            border: '1px solid var(--border)'
                        }}>
                            <div style={{
                                padding: '1.25rem 1.5rem',
                                borderBottom: '1px solid var(--border)',
                                display: 'flex',
                                alignItems: 'center',
                                justifyContent: 'space-between'
                            }}>
                                <div>
                                    <h3 style={{ margin: 0, fontSize: '1.2rem', fontWeight: 600 }}>
                                        {generatedSpec.flow_title}
                                    </h3>
                                    <div style={{ margin: '0.5rem 0 0 0', display: 'flex', gap: '0.5rem', alignItems: 'center', flexWrap: 'wrap' }}>
                                        {generatedSpec.cached && (
                                            <span style={{ background: 'var(--primary-glow)', color: 'var(--primary)', padding: '2px 8px', borderRadius: '4px', fontSize: '0.75rem' }}>Cached</span>
                                        )}
                                        {generatedSpec.pipeline === 'native_planner_generator' && (
                                            <span style={{ background: 'var(--success-muted)', color: 'var(--success)', padding: '2px 8px', borderRadius: '4px', fontSize: '0.75rem' }}>Intelligent Pipeline</span>
                                        )}
                                        {generatedSpec.validated && (
                                            <span style={{ background: 'var(--success-muted)', color: 'var(--success)', padding: '2px 8px', borderRadius: '4px', fontSize: '0.75rem' }}>✓ Validated</span>
                                        )}
                                        {generatedSpec.requires_auth && (
                                            <span style={{ background: 'var(--warning-muted)', color: 'var(--warning)', padding: '2px 8px', borderRadius: '4px', fontSize: '0.75rem' }}>Auth Required</span>
                                        )}
                                    </div>
                                    <p style={{ margin: '0.25rem 0 0 0', fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                                        {generatedSpec.cached
                                            ? 'Previously generated spec'
                                            : 'Generated with real browser exploration'}
                                    </p>
                                </div>
                                <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
                                    {generatedSpec.cached && (
                                        <button
                                            onClick={() => {
                                                if (selectedFlow) {
                                                    generateFlowSpec(selectedFlow.id, true);
                                                }
                                            }}
                                            disabled={generatingSpec}
                                            style={{
                                                padding: '0.5rem 0.75rem',
                                                background: 'transparent',
                                                color: 'var(--text)',
                                                border: '1px solid var(--border)',
                                                borderRadius: '6px',
                                                fontSize: '0.8rem',
                                                fontWeight: 500,
                                                cursor: generatingSpec ? 'not-allowed' : 'pointer',
                                                display: 'flex',
                                                alignItems: 'center',
                                                gap: '0.4rem'
                                            }}
                                            title="Generate new version"
                                        >
                                            <RefreshCw size={14} />
                                            Regenerate
                                        </button>
                                    )}
                                    <button
                                        onClick={() => setSpecModalOpen(false)}
                                        style={{
                                            background: 'transparent',
                                            border: 'none',
                                            cursor: 'pointer',
                                            color: 'var(--text-secondary)'
                                        }}
                                    >
                                        <X size={20} />
                                    </button>
                                </div>
                            </div>

                            <div style={{
                                padding: '1.5rem',
                                overflowY: 'auto',
                                flex: 1,
                                background: 'var(--code-bg)',
                                borderRadius: '8px',
                                margin: '1rem',
                                fontSize: '0.85rem',
                                lineHeight: '1.6',
                                whiteSpace: 'pre-wrap',
                                wordBreak: 'break-word',
                                fontFamily: 'var(--font-mono)'
                            }}>
                                {generatedSpec.spec_content}
                            </div>

                            {/* Split Results Section */}
                            {splitResult && (
                                <div style={{
                                    margin: '0 1rem 1rem 1rem',
                                    padding: '1rem',
                                    background: 'var(--success-muted)',
                                    borderRadius: '8px',
                                    border: '1px solid rgba(52, 211, 153, 0.2)'
                                }}>
                                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.75rem' }}>
                                        <CheckCircle2 size={16} style={{ color: 'var(--success)' }} />
                                        <span style={{ fontWeight: 600, color: 'var(--success)' }}>
                                            Split into {splitResult.count} individual test specs
                                        </span>
                                    </div>
                                    <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '0.5rem' }}>
                                        Output: specs/{splitResult.output_dir}/
                                    </div>
                                    <div style={{ maxHeight: '150px', overflowY: 'auto' }}>
                                        {splitResult.files.map((file, i) => (
                                            <div key={i} style={{
                                                display: 'flex',
                                                alignItems: 'center',
                                                gap: '0.5rem',
                                                padding: '0.35rem 0',
                                                fontSize: '0.8rem',
                                                borderBottom: i < splitResult.files.length - 1 ? '1px solid var(--border)' : 'none'
                                            }}>
                                                <FileText size={14} style={{ color: 'var(--primary)', flexShrink: 0 }} />
                                                <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                                    {file.split('/').pop()}
                                                </span>
                                                <a
                                                    href={`/specs?file=${encodeURIComponent(file)}`}
                                                    target="_blank"
                                                    rel="noopener noreferrer"
                                                    style={{
                                                        color: 'var(--primary)',
                                                        display: 'flex',
                                                        alignItems: 'center',
                                                        gap: '0.25rem',
                                                        fontSize: '0.75rem',
                                                        textDecoration: 'none'
                                                    }}
                                                >
                                                    <ExternalLink size={12} />
                                                    View
                                                </a>
                                            </div>
                                        ))}
                                    </div>
                                </div>
                            )}

                            <div style={{
                                padding: '1rem 1.5rem',
                                borderTop: '1px solid var(--border)',
                                display: 'flex',
                                gap: '0.75rem',
                                justifyContent: 'space-between',
                                flexWrap: 'wrap'
                            }}>
                                {/* Left side - Split button */}
                                <button
                                    onClick={splitSpec}
                                    disabled={splittingSpec || !generatedSpec.spec_file}
                                    style={{
                                        padding: '0.6rem 1rem',
                                        background: splitResult ? 'var(--success-muted)' : 'rgba(192, 132, 252, 0.1)',
                                        color: splitResult ? 'var(--success)' : '#a855f7',
                                        border: `1px solid ${splitResult ? 'rgba(52, 211, 153, 0.3)' : 'rgba(192, 132, 252, 0.3)'}`,
                                        borderRadius: '6px',
                                        fontSize: '0.85rem',
                                        fontWeight: 500,
                                        cursor: splittingSpec ? 'not-allowed' : 'pointer',
                                        opacity: splittingSpec ? 0.6 : 1,
                                        display: 'flex',
                                        alignItems: 'center',
                                        gap: '0.5rem'
                                    }}
                                    title="Split this multi-test spec into individual test files for easier automation"
                                >
                                    {splittingSpec ? (
                                        <>
                                            <Loader2 size={16} className="spin" />
                                            Splitting...
                                        </>
                                    ) : splitResult ? (
                                        <>
                                            <CheckCircle2 size={16} />
                                            Split Complete
                                        </>
                                    ) : (
                                        <>
                                            <Scissors size={16} />
                                            Split into Individual Tests
                                        </>
                                    )}
                                </button>

                                {/* Right side - Copy and Download */}
                                <div style={{ display: 'flex', gap: '0.75rem' }}>
                                    <button
                                        onClick={() => {
                                            navigator.clipboard.writeText(generatedSpec.spec_content);
                                            alert('Spec copied to clipboard!');
                                        }}
                                        style={{
                                            padding: '0.6rem 1rem',
                                            background: 'transparent',
                                            color: 'var(--text)',
                                            border: '1px solid var(--border)',
                                            borderRadius: '6px',
                                            fontSize: '0.85rem',
                                            fontWeight: 500,
                                            cursor: 'pointer'
                                        }}
                                    >
                                        Copy
                                    </button>
                                    <button
                                        onClick={() => downloadSpec()}
                                        style={{
                                            padding: '0.6rem 1rem',
                                            background: 'var(--primary)',
                                            color: 'white',
                                            border: 'none',
                                            borderRadius: '6px',
                                            fontSize: '0.85rem',
                                            fontWeight: 500,
                                            cursor: 'pointer',
                                            display: 'flex',
                                            alignItems: 'center',
                                            gap: '0.5rem'
                                        }}
                                    >
                                        <Download size={16} />
                                        Download
                                    </button>
                                </div>
                            </div>
                        </div>
                    </div>
                )}
            </div>
        </PageLayout>
    );
}
