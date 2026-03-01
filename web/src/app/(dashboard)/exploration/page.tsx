'use client';
import { useState, useEffect, useCallback, useRef } from 'react';
import { Compass, Plus, Play, Square, Eye, FileText, Clock, Globe, Zap, Activity, X, Loader2, Bot, Terminal, ChevronRight, CheckCircle2, AlertTriangle, RotateCcw, Lock, Settings, Download, Sparkles, ArrowRight, Info, RefreshCw, Scissors, ExternalLink, Edit, Trash2, Save } from 'lucide-react';
import { useProject } from '@/contexts/ProjectContext';
import { API_BASE } from '@/lib/api';
import { useJobPoller } from '@/hooks/useJobPoller';
import { WorkflowBreadcrumb } from '@/components/workflow/WorkflowBreadcrumb';
import { PageLayout } from '@/components/ui/page-layout';
import { PageHeader } from '@/components/ui/page-header';
import { EmptyState } from '@/components/ui/empty-state';
import { ListPageSkeleton } from '@/components/ui/page-skeleton';

// ============ SESSIONS TAB TYPES ============
interface ExplorationSession {
    id: string;
    project_id: string | null;
    entry_url: string;
    status: string;
    strategy: string;
    pages_discovered: number;
    flows_discovered: number;
    elements_discovered: number;
    api_endpoints_discovered: number;
    issues_discovered: number;
    progress_data?: string | null;
    started_at: string | null;
    completed_at: string | null;
    duration_seconds: number | null;
    error_message: string | null;
    created_at: string;
}

interface Flow {
    id: number;
    flow_name: string;
    flow_category: string;
    description: string | null;
    start_url: string;
    end_url: string;
    step_count: number;
    is_success_path: boolean;
    preconditions: string[];
    postconditions: string[];
}

// ============ EXPLORATION DETAILS TYPES ============
interface PageSummary {
    url: string;
    page_type: string | null;
    visit_count: number;
    first_seen_sequence: number;
    actions_performed: string[];
}

interface ElementSummary {
    element_ref: string | null;
    element_role: string | null;
    element_name: string | null;
    action_type: string;
    action_value: string | null;
    page_url: string;
    occurrence_count: number;
}

interface FlowStep {
    id: number;
    step_number: number;
    action_type: string;
    action_description: string;
    element_ref: string | null;
    element_role: string | null;
    element_name: string | null;
    value: string | null;
}

interface FlowDetail extends Flow {
    steps: FlowStep[];
}

interface ApiEndpointDetail {
    id: number;
    method: string;
    url: string;
    response_status: number | null;
    triggered_by_action: string | null;
    call_count: number;
    request_headers: Record<string, any> | null;
    request_body_sample: string | null;
    response_body_sample: string | null;
    first_seen: string | null;
}

interface DiscoveredIssue {
    id: number;
    issue_type: string;
    severity: string;
    url: string;
    description: string;
    element: string | null;
    evidence: string | null;
    created_at: string;
}

interface ExplorationDetails {
    session: ExplorationSession;
    pages: PageSummary[];
    flows: FlowDetail[];
    elements: ElementSummary[];
    api_endpoints: ApiEndpointDetail[];
    issues: DiscoveredIssue[];
}

interface SpecGenJob {
    job_id: string;
    status: 'running' | 'completed' | 'failed';
    type: 'specs' | 'tests';
    session_id: string;
    message?: string;
    result?: { spec_files: string[]; count: number };
    endpoint_count?: number;
}

type DetailTabType = 'pages' | 'flows' | 'elements' | 'apis' | 'issues';

// ============ AGENT TAB TYPES ============
interface AgentRun {
    id: string;
    agent_type: string;
    status: string;
    created_at: string;
    config: any;
    summary?: string;
    result?: any;
    project_id?: string;
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
type TabType = 'sessions' | 'explorer';

// Tool name humanization for progress display
const toolLabels: Record<string, string> = {
    browser_navigate: "Navigating to page...",
    browser_click: "Clicking element...",
    browser_snapshot: "Analyzing page structure...",
    browser_type: "Filling form field...",
    browser_evaluate: "Extracting page data...",
    browser_hover: "Exploring navigation menu...",
    browser_wait_for: "Waiting for page load...",
    browser_network_requests: "Capturing API calls...",
    browser_select_option: "Selecting option...",
    browser_press_key: "Pressing key...",
    browser_take_screenshot: "Taking screenshot...",
    browser_console_messages: "Reading console output...",
    browser_navigate_back: "Going back...",
    browser_close: "Closing browser...",
    browser_file_upload: "Uploading file...",
    browser_handle_dialog: "Handling dialog...",
    browser_drag: "Dragging element...",
};

function parseProgress(session: ExplorationSession): {
    phase?: string;
    message?: string;
    step: number;
    max_steps: number;
    last_action: string;
    updated_at: string;
} | null {
    if (!session.progress_data) return null;
    try {
        return JSON.parse(session.progress_data);
    } catch {
        return null;
    }
}

function formatStaleness(updatedAt: string): { text: string; isStale: boolean } | null {
    if (!updatedAt) return null;
    const updatedMs = new Date(updatedAt + (updatedAt.endsWith('Z') ? '' : 'Z')).getTime();
    const nowMs = Date.now();
    const diffSec = Math.floor((nowMs - updatedMs) / 1000);
    if (diffSec < 60) return null;
    const mins = Math.floor(diffSec / 60);
    return { text: `(last update ${mins}m ago)`, isStale: true };
}

function humanizeToolName(toolName: string): string {
    if (!toolName) return "Working...";
    // Strip MCP prefix (e.g. mcp__playwright-test__browser_click -> browser_click)
    const shortName = toolName.replace(/^mcp__[^_]+__/, '');
    return toolLabels[shortName] || `Running ${shortName.replace(/_/g, ' ')}...`;
}

const statusColors: Record<string, { bg: string; color: string }> = {
    pending: { bg: 'var(--warning-muted)', color: 'var(--warning)' },
    running: { bg: 'var(--primary-glow)', color: 'var(--primary)' },
    completed: { bg: 'var(--success-muted)', color: 'var(--success)' },
    failed: { bg: 'var(--danger-muted)', color: 'var(--danger)' },
    stopped: { bg: 'rgba(156, 163, 175, 0.1)', color: 'var(--text-tertiary)' },
};

export default function DiscoveryPage() {
    const { currentProject, isLoading: projectLoading } = useProject();

    // ============ TAB STATE ============
    const [activeTab, setActiveTab] = useState<TabType>('sessions');

    // ============ SESSIONS TAB STATE ============
    const [sessions, setSessions] = useState<ExplorationSession[]>([]);
    const [loading, setLoading] = useState(true);
    const [modalOpen, setModalOpen] = useState(false);
    const [detailModalOpen, setDetailModalOpen] = useState(false);
    const [selectedSession, setSelectedSession] = useState<ExplorationSession | null>(null);
    const [sessionFlows, setSessionFlows] = useState<Flow[]>([]);
    const [entryUrl, setEntryUrl] = useState('');
    const [thoroughness, setThoroughness] = useState<'quick' | 'normal' | 'comprehensive'>('normal');
    const [loginUrl, setLoginUrl] = useState('');
    const [loginUsername, setLoginUsername] = useState('');
    const [loginPassword, setLoginPassword] = useState('');
    const [additionalInstructions, setAdditionalInstructions] = useState('');
    const [isStarting, setIsStarting] = useState(false);
    const [generatingSessionId, setGeneratingSessionId] = useState<string | null>(null);
    const [reqGenJobId, setReqGenJobId] = useState<string | null>(null);
    const [reqGenResult, setReqGenResult] = useState<{ sessionId: string; count: number } | null>(null);
    const reqGenPollRef = useRef<NodeJS.Timeout | null>(null);
    const [generatingApiTestsSessionId, setGeneratingApiTestsSessionId] = useState<string | null>(null);
    const [generatingApiSpecsSessionId, setGeneratingApiSpecsSessionId] = useState<string | null>(null);
    const [explorationMode, setExplorationMode] = useState<'general' | 'api_focused'>('general');
    const [specGenJobs, setSpecGenJobs] = useState<Record<string, SpecGenJob>>({});
    const specGenPollIntervals = useRef<Record<string, NodeJS.Timeout>>({});

    // ============ EXPLORATION DETAILS STATE ============
    const [detailTab, setDetailTab] = useState<DetailTabType>('pages');
    const [explorationDetails, setExplorationDetails] = useState<ExplorationDetails | null>(null);
    const [detailsLoading, setDetailsLoading] = useState(false);
    // Flow editing in details
    const [editingExplorationFlow, setEditingExplorationFlow] = useState<FlowDetail | null>(null);
    const [isEditingExplorationFlow, setIsEditingExplorationFlow] = useState(false);
    const [isSavingExplorationFlow, setIsSavingExplorationFlow] = useState(false);
    const [deleteExplorationFlowId, setDeleteExplorationFlowId] = useState<number | null>(null);
    // API editing in details
    const [editingApiEndpoint, setEditingApiEndpoint] = useState<ApiEndpointDetail | null>(null);
    const [isEditingApiEndpoint, setIsEditingApiEndpoint] = useState(false);
    const [isSavingApiEndpoint, setIsSavingApiEndpoint] = useState(false);
    const [deleteApiEndpointId, setDeleteApiEndpointId] = useState<number | null>(null);
    // Expand toggles
    const [expandedFlowId, setExpandedFlowId] = useState<number | null>(null);
    const [expandedApiId, setExpandedApiId] = useState<number | null>(null);

    // ============ AGENT TAB STATE ============
    const [agentUrl, setAgentUrl] = useState('');
    const [instructions, setInstructions] = useState('');
    const [timeLimitMinutes, setTimeLimitMinutes] = useState(15);
    const [authType, setAuthType] = useState<AuthType>('none');
    const [authCredentials, setAuthCredentials] = useState({ username: '', password: '', loginUrl: '/login' });
    const [agentSessionId, setAgentSessionId] = useState('');
    const [testData, setTestData] = useState('');
    const [focusAreas, setFocusAreas] = useState('');
    const [excludedPatterns, setExcludedPatterns] = useState('');
    const [history, setHistory] = useState<AgentRun[]>([]);
    const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
    const [activeRun, setActiveRun] = useState<AgentRun | null>(null);
    const [specResult, setSpecResult] = useState<SpecResult | null>(null);
    const [isAgentStarting, setIsAgentStarting] = useState(false);
    const [isSynthesizing, setIsSynthesizing] = useState(false);
    const [showAdvanced, setShowAdvanced] = useState(false);
    const [agentSessions, setAgentSessions] = useState<any[]>([]);
    const [flowModalOpen, setFlowModalOpen] = useState(false);
    const [selectedFlow, setSelectedFlow] = useState<any | null>(null);
    const [loadingFlowDetails, setLoadingFlowDetails] = useState(false);
    const [generatingSpec, setGeneratingSpec] = useState(false);
    const [generatedSpec, setGeneratedSpec] = useState<any | null>(null);
    const [specModalOpen, setSpecModalOpen] = useState(false);
    const [splittingSpec, setSplittingSpec] = useState(false);
    const [splitResult, setSplitResult] = useState<{ count: number; files: string[]; output_dir: string } | null>(null);
    const [isEditingFlow, setIsEditingFlow] = useState(false);
    const [editingFlow, setEditingFlow] = useState<any>(null);
    const [isSavingFlow, setIsSavingFlow] = useState(false);
    const [deleteFlowModalOpen, setDeleteFlowModalOpen] = useState(false);
    const [isDeletingFlow, setIsDeletingFlow] = useState(false);
    const pollInterval = useRef<NodeJS.Timeout | null>(null);
    const hasRunningRef = useRef(false);

    // ============ SPEC GEN JOB POLLING ============
    const startJobPolling = useCallback((jobId: string) => {
        // Don't double-poll
        if (specGenPollIntervals.current[jobId]) return;

        const interval = setInterval(async () => {
            try {
                const res = await fetch(`${API_BASE}/exploration/spec-gen-jobs/${jobId}`);
                if (!res.ok) return;
                const job: SpecGenJob = await res.json();
                setSpecGenJobs(prev => ({ ...prev, [jobId]: job }));

                if (job.status === 'completed' || job.status === 'failed') {
                    clearInterval(specGenPollIntervals.current[jobId]);
                    delete specGenPollIntervals.current[jobId];

                    // Auto-dismiss success banners after 30s
                    if (job.status === 'completed') {
                        setTimeout(() => {
                            setSpecGenJobs(prev => {
                                const next = { ...prev };
                                delete next[jobId];
                                return next;
                            });
                        }, 30000);
                    }
                }
            } catch (e) {
                console.error(`Failed to poll job ${jobId}:`, e);
            }
        }, 3000);

        specGenPollIntervals.current[jobId] = interval;
    }, []);

    // Cleanup all polling intervals on unmount
    useEffect(() => {
        return () => {
            Object.values(specGenPollIntervals.current).forEach(clearInterval);
            specGenPollIntervals.current = {};
        };
    }, []);

    // Helper: get active job for a session+type combo
    const getActiveJob = useCallback((sessionId: string, type: 'specs' | 'tests'): SpecGenJob | undefined => {
        return Object.values(specGenJobs).find(
            j => j.session_id === sessionId && j.type === type
        );
    }, [specGenJobs]);

    // ============ SESSIONS TAB FUNCTIONS ============
    const fetchSessions = useCallback(async () => {
        if (projectLoading) return;

        const projectParam = currentProject?.id
            ? `?project_id=${encodeURIComponent(currentProject.id)}`
            : '';

        try {
            const res = await fetch(`${API_BASE}/exploration${projectParam}`);
            const data = await res.json();
            setSessions(data);
            // Update ref for polling decisions (avoids useEffect dependency on sessions)
            hasRunningRef.current = data.some((s: ExplorationSession) =>
                s.status === 'running' || s.status === 'queued'
            );
        } catch (err) {
            console.error('Failed to fetch exploration sessions:', err);
        } finally {
            setLoading(false);
        }
    }, [currentProject?.id, projectLoading]);

    useEffect(() => {
        if (activeTab === 'sessions') {
            fetchSessions();

            // Poll at 5s interval; fetchSessions updates hasRunningRef
            const interval = setInterval(() => {
                if (hasRunningRef.current) {
                    fetchSessions();
                }
            }, 5000);
            return () => clearInterval(interval);
        }
    }, [fetchSessions, activeTab]);

    const startExploration = async () => {
        if (!entryUrl || isStarting) return;

        setIsStarting(true);

        const config: Record<string, number | string | undefined> = {};
        if (thoroughness === 'quick') {
            config.max_interactions = 20;
            config.max_depth = 5;
            config.timeout_minutes = 10;
        } else if (thoroughness === 'comprehensive') {
            config.max_interactions = 100;
            config.max_depth = 20;
            config.timeout_minutes = 60;
        } else {
            config.max_interactions = 50;
            config.max_depth = 10;
            config.timeout_minutes = 30;
        }

        try {
            const res = await fetch(`${API_BASE}/exploration/start`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    entry_url: entryUrl,
                    project_id: currentProject?.id || 'default',
                    strategy: explorationMode === 'api_focused' ? 'api_focused' : 'goal_directed',
                    login_url: loginUrl || undefined,
                    credentials: (loginUrl && loginUsername) ? {
                        username: loginUsername,
                        password: loginPassword
                    } : undefined,
                    additional_instructions: additionalInstructions || undefined,
                    ...config
                })
            });

            if (res.ok) {
                setModalOpen(false);
                setEntryUrl('');
                setLoginUrl('');
                setLoginUsername('');
                setLoginPassword('');
                setAdditionalInstructions('');
                setThoroughness('normal');
                setExplorationMode('general');
                fetchSessions();
            } else {
                const err = await res.json();
                alert(`Failed to start exploration: ${err.detail}`);
            }
        } catch (e) {
            console.error('Failed to start exploration:', e);
            alert('Failed to start exploration');
        } finally {
            setIsStarting(false);
        }
    };

    const stopExploration = async (sessionId: string) => {
        const projectParam = currentProject?.id
            ? `?project_id=${encodeURIComponent(currentProject.id)}`
            : '';

        try {
            const res = await fetch(`${API_BASE}/exploration/${sessionId}/stop${projectParam}`, {
                method: 'POST'
            });
            if (res.ok) {
                fetchSessions();
            }
        } catch (e) {
            console.error('Failed to stop exploration:', e);
        }
    };

    const viewDetails = async (session: ExplorationSession) => {
        setSelectedSession(session);
        setDetailsLoading(true);
        setDetailTab('pages');
        setExplorationDetails(null);
        setExpandedFlowId(null);
        setExpandedApiId(null);
        setIsEditingExplorationFlow(false);
        setEditingExplorationFlow(null);
        setIsEditingApiEndpoint(false);
        setEditingApiEndpoint(null);
        setDetailModalOpen(true);

        const projectParam = currentProject?.id
            ? `?project_id=${encodeURIComponent(currentProject.id)}`
            : '';

        try {
            const res = await fetch(`${API_BASE}/exploration/${session.id}/details${projectParam}`);
            if (res.ok) {
                const data = await res.json();
                setExplorationDetails(data);
            } else {
                console.error('Failed to fetch details:', res.status);
            }
        } catch (e) {
            console.error('Failed to fetch exploration details:', e);
        } finally {
            setDetailsLoading(false);
        }
    };

    const generateRequirements = async (sessionId: string) => {
        setGeneratingSessionId(sessionId);
        setReqGenResult(null);

        const projectParam = currentProject?.id
            ? `?project_id=${encodeURIComponent(currentProject.id)}`
            : '';

        try {
            const res = await fetch(`${API_BASE}/requirements/generate${projectParam}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    exploration_session_id: sessionId
                })
            });

            if (res.ok) {
                const data = await res.json();
                if (data.job_id) {
                    // Async mode: poll for completion
                    setReqGenJobId(data.job_id);
                    const pollInterval = setInterval(async () => {
                        try {
                            const pollRes = await fetch(`${API_BASE}/requirements/generate-jobs/${data.job_id}`);
                            if (pollRes.ok) {
                                const pollData = await pollRes.json();
                                if (pollData.status === 'completed') {
                                    clearInterval(pollInterval);
                                    reqGenPollRef.current = null;
                                    setReqGenJobId(null);
                                    setGeneratingSessionId(null);
                                    const total = pollData.result?.total_requirements || 0;
                                    setReqGenResult({ sessionId, count: total });
                                } else if (pollData.status === 'failed') {
                                    clearInterval(pollInterval);
                                    reqGenPollRef.current = null;
                                    setReqGenJobId(null);
                                    setGeneratingSessionId(null);
                                    alert(`Requirements generation failed: ${pollData.error || 'Unknown error'}`);
                                }
                            }
                        } catch {
                            // Polling error, keep trying
                        }
                    }, 2000);
                    reqGenPollRef.current = pollInterval;
                } else if (data.total_requirements !== undefined) {
                    // Sync fallback
                    setReqGenResult({ sessionId, count: data.total_requirements });
                    setGeneratingSessionId(null);
                }
            } else {
                let errorMessage = `HTTP ${res.status}`;
                try {
                    const err = await res.json();
                    errorMessage = err.detail || JSON.stringify(err);
                } catch {
                    errorMessage = `HTTP ${res.status}: ${res.statusText}`;
                }
                console.error('Requirements generation failed:', errorMessage);
                alert(`Failed to generate requirements: ${errorMessage}`);
                setGeneratingSessionId(null);
            }
        } catch (e) {
            console.error('Failed to generate requirements:', e);
            alert(`Failed to generate requirements: ${e instanceof Error ? e.message : 'Network error'}`);
            setGeneratingSessionId(null);
        }
    };

    // Cleanup polling on unmount
    useEffect(() => {
        return () => {
            if (reqGenPollRef.current) {
                clearInterval(reqGenPollRef.current);
            }
        };
    }, []);

    const generateApiTests = async (sessionId: string) => {
        setGeneratingApiTestsSessionId(sessionId);

        const projectParam = currentProject?.id
            ? `?project_id=${encodeURIComponent(currentProject.id)}`
            : '';

        try {
            const res = await fetch(`${API_BASE}/exploration/${sessionId}/generate-api-tests${projectParam}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
            });

            if (res.ok) {
                const data = await res.json();
                if (data.job_id) {
                    // Initialize job in state and start polling
                    const job: SpecGenJob = {
                        job_id: data.job_id,
                        status: 'running',
                        type: 'tests',
                        session_id: sessionId,
                        message: data.message,
                        endpoint_count: data.endpoint_count,
                    };
                    setSpecGenJobs(prev => ({ ...prev, [data.job_id]: job }));
                    startJobPolling(data.job_id);
                }
            } else {
                let errorMessage = `HTTP ${res.status}`;
                try {
                    const err = await res.json();
                    errorMessage = err.detail || JSON.stringify(err);
                } catch {
                    errorMessage = `HTTP ${res.status}: ${res.statusText}`;
                }
                // Show inline error via specGenJobs
                const errorJobId = `error-tests-${sessionId}-${Date.now()}`;
                setSpecGenJobs(prev => ({
                    ...prev,
                    [errorJobId]: {
                        job_id: errorJobId,
                        status: 'failed',
                        type: 'tests',
                        session_id: sessionId,
                        message: errorMessage,
                    }
                }));
            }
        } catch (e) {
            console.error('Failed to generate API tests:', e);
            const errorJobId = `error-tests-${sessionId}-${Date.now()}`;
            setSpecGenJobs(prev => ({
                ...prev,
                [errorJobId]: {
                    job_id: errorJobId,
                    status: 'failed',
                    type: 'tests',
                    session_id: sessionId,
                    message: e instanceof Error ? e.message : 'Network error',
                }
            }));
        } finally {
            setGeneratingApiTestsSessionId(null);
        }
    };

    const generateApiSpecs = async (sessionId: string) => {
        setGeneratingApiSpecsSessionId(sessionId);

        const projectParam = currentProject?.id
            ? `?project_id=${encodeURIComponent(currentProject.id)}`
            : '';

        try {
            const res = await fetch(`${API_BASE}/exploration/${sessionId}/generate-api-specs${projectParam}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
            });

            if (res.ok) {
                const data = await res.json();
                if (data.job_id) {
                    // Initialize job in state and start polling
                    const job: SpecGenJob = {
                        job_id: data.job_id,
                        status: 'running',
                        type: 'specs',
                        session_id: sessionId,
                        message: data.message,
                        endpoint_count: data.endpoint_count,
                    };
                    setSpecGenJobs(prev => ({ ...prev, [data.job_id]: job }));
                    startJobPolling(data.job_id);
                }
            } else {
                let errorMessage = `HTTP ${res.status}`;
                try {
                    const err = await res.json();
                    errorMessage = err.detail || JSON.stringify(err);
                } catch {
                    errorMessage = `HTTP ${res.status}: ${res.statusText}`;
                }
                // Show inline error via specGenJobs
                const errorJobId = `error-specs-${sessionId}-${Date.now()}`;
                setSpecGenJobs(prev => ({
                    ...prev,
                    [errorJobId]: {
                        job_id: errorJobId,
                        status: 'failed',
                        type: 'specs',
                        session_id: sessionId,
                        message: errorMessage,
                    }
                }));
            }
        } catch (e) {
            console.error('Failed to generate API specs:', e);
            const errorJobId = `error-specs-${sessionId}-${Date.now()}`;
            setSpecGenJobs(prev => ({
                ...prev,
                [errorJobId]: {
                    job_id: errorJobId,
                    status: 'failed',
                    type: 'specs',
                    session_id: sessionId,
                    message: e instanceof Error ? e.message : 'Network error',
                }
            }));
        } finally {
            setGeneratingApiSpecsSessionId(null);
        }
    };

    // ============ EXPLORATION DETAILS CRUD ============
    const saveExplorationFlow = async (flow: FlowDetail) => {
        if (!selectedSession || !explorationDetails) return;
        setIsSavingExplorationFlow(true);
        const projectParam = currentProject?.id
            ? `?project_id=${encodeURIComponent(currentProject.id)}`
            : '';
        try {
            const res = await fetch(`${API_BASE}/exploration/${selectedSession.id}/flows/${flow.id}${projectParam}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    flow_name: editingExplorationFlow?.flow_name,
                    flow_category: editingExplorationFlow?.flow_category,
                    description: editingExplorationFlow?.description,
                    is_success_path: editingExplorationFlow?.is_success_path,
                    preconditions: editingExplorationFlow?.preconditions,
                    postconditions: editingExplorationFlow?.postconditions,
                })
            });
            if (res.ok) {
                const data = await res.json();
                const updatedFlow = data.flow;
                setExplorationDetails({
                    ...explorationDetails,
                    flows: explorationDetails.flows.map(f =>
                        f.id === flow.id ? { ...f, ...updatedFlow } : f
                    )
                });
                setIsEditingExplorationFlow(false);
                setEditingExplorationFlow(null);
            } else {
                const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
                alert(`Failed to save flow: ${err.detail}`);
            }
        } catch (e) {
            alert(`Failed to save flow: ${e instanceof Error ? e.message : 'Network error'}`);
        } finally {
            setIsSavingExplorationFlow(false);
        }
    };

    const deleteExplorationFlow = async (flowId: number) => {
        if (!selectedSession || !explorationDetails) return;
        const projectParam = currentProject?.id
            ? `?project_id=${encodeURIComponent(currentProject.id)}`
            : '';
        try {
            const res = await fetch(`${API_BASE}/exploration/${selectedSession.id}/flows/${flowId}${projectParam}`, {
                method: 'DELETE'
            });
            if (res.ok) {
                setExplorationDetails({
                    ...explorationDetails,
                    flows: explorationDetails.flows.filter(f => f.id !== flowId)
                });
                setDeleteExplorationFlowId(null);
                if (expandedFlowId === flowId) setExpandedFlowId(null);
            } else {
                const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
                alert(`Failed to delete flow: ${err.detail}`);
            }
        } catch (e) {
            alert(`Failed to delete flow: ${e instanceof Error ? e.message : 'Network error'}`);
        }
    };

    const saveApiEndpoint = async (endpoint: ApiEndpointDetail) => {
        if (!selectedSession || !explorationDetails) return;
        setIsSavingApiEndpoint(true);
        const projectParam = currentProject?.id
            ? `?project_id=${encodeURIComponent(currentProject.id)}`
            : '';
        try {
            const res = await fetch(`${API_BASE}/exploration/${selectedSession.id}/apis/${endpoint.id}${projectParam}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    method: editingApiEndpoint?.method,
                    url: editingApiEndpoint?.url,
                    response_status: editingApiEndpoint?.response_status,
                    triggered_by_action: editingApiEndpoint?.triggered_by_action,
                    request_body_sample: editingApiEndpoint?.request_body_sample,
                    response_body_sample: editingApiEndpoint?.response_body_sample,
                })
            });
            if (res.ok) {
                const data = await res.json();
                const updatedEndpoint = data.endpoint;
                setExplorationDetails({
                    ...explorationDetails,
                    api_endpoints: explorationDetails.api_endpoints.map(e =>
                        e.id === endpoint.id ? { ...e, ...updatedEndpoint } : e
                    )
                });
                setIsEditingApiEndpoint(false);
                setEditingApiEndpoint(null);
            } else {
                const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
                alert(`Failed to save endpoint: ${err.detail}`);
            }
        } catch (e) {
            alert(`Failed to save endpoint: ${e instanceof Error ? e.message : 'Network error'}`);
        } finally {
            setIsSavingApiEndpoint(false);
        }
    };

    const deleteApiEndpoint = async (endpointId: number) => {
        if (!selectedSession || !explorationDetails) return;
        const projectParam = currentProject?.id
            ? `?project_id=${encodeURIComponent(currentProject.id)}`
            : '';
        try {
            const res = await fetch(`${API_BASE}/exploration/${selectedSession.id}/apis/${endpointId}${projectParam}`, {
                method: 'DELETE'
            });
            if (res.ok) {
                setExplorationDetails({
                    ...explorationDetails,
                    api_endpoints: explorationDetails.api_endpoints.filter(e => e.id !== endpointId)
                });
                setDeleteApiEndpointId(null);
                if (expandedApiId === endpointId) setExpandedApiId(null);
            } else {
                const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
                alert(`Failed to delete endpoint: ${err.detail}`);
            }
        } catch (e) {
            alert(`Failed to delete endpoint: ${e instanceof Error ? e.message : 'Network error'}`);
        }
    };

    const formatDuration = (seconds: number | null) => {
        if (!seconds) return '-';
        if (seconds < 60) return `${seconds}s`;
        if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
        return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;
    };

    const formatTimeAgo = (dateStr: string | null) => {
        if (!dateStr) return '-';
        const date = new Date(dateStr.endsWith('Z') ? dateStr : dateStr + 'Z');
        const now = new Date();
        const diff = Math.floor((now.getTime() - date.getTime()) / 1000);

        if (diff < 0) return 'just now';
        if (diff < 60) return 'just now';
        if (diff < 3600) return `${Math.floor(diff / 60)} min ago`;
        if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
        return `${Math.floor(diff / 86400)}d ago`;
    };

    // ============ AGENT TAB FUNCTIONS ============
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

    const fetchAgentSessions = async () => {
        try {
            const res = await fetch(`${API_BASE}/api/agents/sessions`);
            if (res.ok) {
                const data = await res.json();
                setAgentSessions(data.sessions || []);
            }
        } catch (e) { console.error("Failed to fetch sessions", e); }
    };

    useEffect(() => {
        if (activeTab === 'explorer') {
            fetchHistory();
            fetchAgentSessions();
        }
        return () => { if (pollInterval.current) clearInterval(pollInterval.current); }
    }, [currentProject?.id, activeTab]);

    const fetchRun = async (id: string) => {
        try {
            const res = await fetch(`${API_BASE}/api/agents/runs/${id}`);
            if (res.ok) {
                const data = await res.json();
                setActiveRun(data);

                if (data.status !== 'running' && data.status !== 'pending') {
                    if (pollInterval.current && selectedRunId === id) {
                        clearInterval(pollInterval.current);
                        pollInterval.current = null;

                        setTimeout(async () => {
                            const finalRes = await fetch(`${API_BASE}/api/agents/runs/${id}`);
                            if (finalRes.ok) {
                                const finalData = await finalRes.json();
                                setActiveRun(finalData);
                            }
                            fetchHistory();
                        }, 500);
                    }
                }
            }
        } catch (e) {
            console.error("Failed to fetch run", e);
        }
    };

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

    const downloadSpec = (content?: string, filename?: string) => {
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

    const splitSpec = async () => {
        if (!generatedSpec?.spec_file) return;

        setSplittingSpec(true);
        setSplitResult(null);
        try {
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

    const startEditingFlow = () => {
        setEditingFlow({ ...selectedFlow });
        setIsEditingFlow(true);
    };

    const cancelEditingFlow = () => {
        setIsEditingFlow(false);
        setEditingFlow(null);
    };

    const saveFlowEdit = async () => {
        if (!activeRun?.id || !editingFlow) return;

        setIsSavingFlow(true);
        try {
            const flowId = editingFlow.id || editingFlow.flow_id;
            const projectParam = currentProject?.id
                ? `?project_id=${encodeURIComponent(currentProject.id)}`
                : '';

            const res = await fetch(`${API_BASE}/api/agents/exploratory/${activeRun.id}/flows/${flowId}${projectParam}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(editingFlow)
            });

            if (res.ok) {
                const data = await res.json();
                const updatedFlow = data.flow || data;
                setSelectedFlow(updatedFlow);
                setIsEditingFlow(false);
                setEditingFlow(null);
                // Update the flow in activeRun's discovered_flow_summaries
                if (activeRun?.result?.discovered_flow_summaries) {
                    const summaries = activeRun.result.discovered_flow_summaries;
                    const idx = summaries.findIndex((f: any) => f.id === flowId);
                    if (idx !== -1) {
                        summaries[idx] = { ...summaries[idx], title: updatedFlow.title };
                    }
                }
            } else {
                let errorMessage = `HTTP ${res.status}`;
                try {
                    const err = await res.json();
                    errorMessage = err.detail || JSON.stringify(err);
                } catch {
                    errorMessage = `HTTP ${res.status}: ${res.statusText}`;
                }
                alert(`Failed to save flow: ${errorMessage}`);
            }
        } catch (e) {
            console.error('Failed to save flow:', e);
            alert(`Failed to save flow: ${e instanceof Error ? e.message : 'Network error'}`);
        } finally {
            setIsSavingFlow(false);
        }
    };

    const confirmDeleteFlow = async () => {
        if (!activeRun?.id || !selectedFlow) return;

        setIsDeletingFlow(true);
        try {
            const flowId = selectedFlow.id || selectedFlow.flow_id;
            const projectParam = currentProject?.id
                ? `?project_id=${encodeURIComponent(currentProject.id)}`
                : '';

            const res = await fetch(`${API_BASE}/api/agents/exploratory/${activeRun.id}/flows/${flowId}${projectParam}`, {
                method: 'DELETE'
            });

            if (res.ok) {
                // Remove the flow from activeRun's discovered_flow_summaries
                if (activeRun?.result?.discovered_flow_summaries) {
                    const summaries = activeRun.result.discovered_flow_summaries;
                    const idx = summaries.findIndex((f: any) => f.id === flowId);
                    if (idx !== -1) {
                        summaries.splice(idx, 1);
                    }
                }
                setDeleteFlowModalOpen(false);
                setFlowModalOpen(false);
                setSelectedFlow(null);
                setIsEditingFlow(false);
                setEditingFlow(null);
            } else {
                let errorMessage = `HTTP ${res.status}`;
                try {
                    const err = await res.json();
                    errorMessage = err.detail || JSON.stringify(err);
                } catch {
                    errorMessage = `HTTP ${res.status}: ${res.statusText}`;
                }
                alert(`Failed to delete flow: ${errorMessage}`);
            }
        } catch (e) {
            console.error('Failed to delete flow:', e);
            alert(`Failed to delete flow: ${e instanceof Error ? e.message : 'Network error'}`);
        } finally {
            setIsDeletingFlow(false);
        }
    };

    useEffect(() => {
        if (!selectedRunId) {
            setActiveRun(null);
            setSpecResult(null);
            return;
        }

        if (pollInterval.current) clearInterval(pollInterval.current);

        fetchRun(selectedRunId);
        fetchSpecs(selectedRunId);

        pollInterval.current = setInterval(() => {
            fetchRun(selectedRunId);
        }, 2000);

        return () => {
            if (pollInterval.current) clearInterval(pollInterval.current);
        };
    }, [selectedRunId]);

    const handleAgentRun = async () => {
        if (!agentUrl) {
            alert("URL is required");
            return;
        }

        setIsAgentStarting(true);
        try {
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
                    authConfig.session_id = agentSessionId;
                }
            }

            let testDataObj = {};
            if (testData.trim()) {
                try {
                    testDataObj = JSON.parse(testData);
                } catch (e) {
                    alert("Invalid JSON in test data");
                    setIsAgentStarting(false);
                    return;
                }
            }

            const focusAreasList = focusAreas ? focusAreas.split(',').map(s => s.trim()).filter(s => s) : [];
            const excludedPatternsList = excludedPatterns ? excludedPatterns.split(',').map(s => s.trim()).filter(s => s) : [];

            const endpoint = `${API_BASE}/api/agents/exploratory`;

            const body = {
                    url: agentUrl,
                    time_limit_minutes: timeLimitMinutes,
                    instructions,
                    auth: authConfig,
                    test_data: Object.keys(testDataObj).length > 0 ? testDataObj : undefined,
                    focus_areas: focusAreasList.length > 0 ? focusAreasList : undefined,
                    excluded_patterns: excludedPatternsList.length > 0 ? excludedPatternsList : undefined,
                    project_id: currentProject?.id
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
            await fetchHistory();
            setSelectedRunId(data.run_id);

        } catch (e: any) {
            alert(e.message);
        } finally {
            setIsAgentStarting(false);
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

    // ============ SKELETON LOADER ============
    const SkeletonCard = () => (
        <div className="card" style={{ padding: '1.5rem', marginBottom: '1rem' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                <div style={{ flex: 1 }}>
                    <div style={{ height: 20, width: '60%', background: 'var(--surface-hover)', borderRadius: 4, marginBottom: '0.75rem', animation: 'pulse 1.5s ease-in-out infinite' }} />
                    <div style={{ height: 14, width: '40%', background: 'var(--surface-hover)', borderRadius: 4, animation: 'pulse 1.5s ease-in-out infinite' }} />
                </div>
                <div style={{ height: 28, width: 80, background: 'var(--surface-hover)', borderRadius: 14, animation: 'pulse 1.5s ease-in-out infinite' }} />
            </div>
            <div style={{ marginTop: '1rem', display: 'flex', gap: '2rem' }}>
                {[1, 2, 3, 4].map(i => (
                    <div key={i} style={{ height: 14, width: 60, background: 'var(--surface-hover)', borderRadius: 4, animation: 'pulse 1.5s ease-in-out infinite' }} />
                ))}
            </div>
        </div>
    );

    if (loading || projectLoading) {
        return (
            <PageLayout tier="wide">
                <ListPageSkeleton rows={3} />
            </PageLayout>
        );
    }

    // ============ RENDER ============
    return (
        <PageLayout tier="wide" style={{ paddingBottom: '4rem' }}>
            <PageHeader
                title="Discovery"
                subtitle="AI-powered app exploration, test discovery, and spec generation."
                icon={<Compass size={22} />}
                breadcrumb={<WorkflowBreadcrumb />}
                actions={activeTab === 'sessions' ? (
                    <button
                        className="btn btn-primary"
                        onClick={() => setModalOpen(true)}
                        style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}
                    >
                        <Plus size={18} />
                        New Exploration
                    </button>
                ) : undefined}
            />

            {/* Tab Navigation */}
            <div className="animate-in stagger-2" style={{ display: 'flex', gap: '0.5rem', marginBottom: '1.5rem', borderBottom: '1px solid var(--border-subtle)', paddingBottom: '1rem' }}>
                {[
                    { id: 'sessions' as TabType, label: 'Sessions', icon: Compass },
                    { id: 'explorer' as TabType, label: 'Explorer Agent', icon: Bot }
                ].map(tab => (
                    <button
                        key={tab.id}
                        onClick={() => setActiveTab(tab.id)}
                        style={{
                            display: 'flex',
                            alignItems: 'center',
                            gap: '0.5rem',
                            padding: '0.75rem 1.25rem',
                            borderRadius: 'var(--radius)',
                            border: activeTab === tab.id ? '2px solid var(--primary)' : '1px solid var(--border)',
                            background: activeTab === tab.id ? 'var(--primary-glow)' : 'transparent',
                            color: activeTab === tab.id ? 'var(--primary)' : 'var(--text-secondary)',
                            fontWeight: activeTab === tab.id ? 600 : 500,
                            fontSize: '0.9rem',
                            cursor: 'pointer',
                            transition: 'all 0.2s var(--ease-smooth)'
                        }}
                    >
                        <tab.icon size={18} />
                        {tab.label}
                    </button>
                ))}
            </div>

            {/* Sessions Tab Content */}
            {activeTab === 'sessions' && (
                <div className="animate-in stagger-3">
                    {sessions.length === 0 ? (
                        <EmptyState
                            icon={<Compass size={40} />}
                            title="No explorations yet"
                            description="Start an AI-powered exploration to discover app features, user flows, and API endpoints."
                            action={
                                <button
                                    className="btn btn-primary"
                                    onClick={() => setModalOpen(true)}
                                    style={{ display: 'inline-flex', alignItems: 'center', gap: '0.5rem' }}
                                >
                                    <Plus size={18} />
                                    Start First Exploration
                                </button>
                            }
                        />
                    ) : (
                        <div>
                            {sessions.map(session => (
                                <div
                                    key={session.id}
                                    className="card"
                                    style={{
                                        padding: '1.5rem',
                                        marginBottom: '1rem',
                                        border: session.status === 'running' ? '2px solid var(--primary)' : '1px solid var(--border)'
                                    }}
                                >
                                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '1rem' }}>
                                        <div style={{ flex: 1 }}>
                                            <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '0.5rem' }}>
                                                <Globe size={18} color="var(--text-secondary)" />
                                                <span style={{ fontWeight: 600, fontSize: '1.1rem' }}>{session.entry_url}</span>
                                            </div>
                                            <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
                                                <span style={{
                                                    textTransform: 'capitalize',
                                                    ...(session.strategy === 'api_focused' ? { color: 'var(--primary)', fontWeight: 500 } : {})
                                                }}>
                                                    {session.strategy === 'api_focused' ? 'API Focused' : session.strategy.replace('_', ' ')}
                                                </span>
                                                <span>|</span>
                                                <span style={{ display: 'flex', alignItems: 'center', gap: '0.25rem' }}>
                                                    <Clock size={14} />
                                                    {session.status === 'running'
                                                        ? `Started ${formatTimeAgo(session.started_at)}`
                                                        : session.completed_at
                                                            ? `Completed ${formatTimeAgo(session.completed_at)}`
                                                            : `Created ${formatTimeAgo(session.created_at)}`
                                                    }
                                                </span>
                                            </div>
                                        </div>
                                        <span style={{
                                            padding: '0.375rem 0.875rem',
                                            borderRadius: '9999px',
                                            fontSize: '0.8rem',
                                            fontWeight: 600,
                                            background: statusColors[session.status]?.bg || statusColors.pending.bg,
                                            color: statusColors[session.status]?.color || statusColors.pending.color,
                                            display: 'flex',
                                            alignItems: 'center',
                                            gap: '0.375rem'
                                        }}>
                                            {session.status === 'running' && <Loader2 size={14} className="spinning" />}
                                            {session.status.charAt(0).toUpperCase() + session.status.slice(1)}
                                        </span>
                                    </div>

                                    {/* Live progress bar for running/queued sessions */}
                                    {(session.status === 'running' || session.status === 'queued') && (() => {
                                        const progress = parseProgress(session);

                                        // Phase: running with actual steps — show progress bar + staleness
                                        if (progress && progress.phase === 'running' && progress.step > 0) {
                                            const pct = Math.min(100, Math.round((progress.step / progress.max_steps) * 100));
                                            const staleness = formatStaleness(progress.updated_at);
                                            return (
                                                <div style={{ marginBottom: '1rem' }}>
                                                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem', fontSize: '0.85rem' }}>
                                                        <span style={{ color: 'var(--text-secondary)' }}>
                                                            Step <strong>{progress.step}</strong> of {progress.max_steps}
                                                            {staleness && (
                                                                <span style={{ color: '#f59e0b', marginLeft: '0.5rem', fontSize: '0.8rem' }}>
                                                                    {staleness.text}
                                                                </span>
                                                            )}
                                                        </span>
                                                        <span style={{ color: 'var(--text-tertiary)', fontSize: '0.8rem' }}>
                                                            {humanizeToolName(progress.last_action)}
                                                        </span>
                                                    </div>
                                                    <div style={{
                                                        height: '6px',
                                                        background: 'var(--bg-tertiary)',
                                                        borderRadius: '3px',
                                                        overflow: 'hidden',
                                                    }}>
                                                        <div style={{
                                                            height: '100%',
                                                            width: `${pct}%`,
                                                            background: staleness ? '#f59e0b' : 'var(--primary)',
                                                            borderRadius: '3px',
                                                            transition: 'width 0.5s ease',
                                                        }} />
                                                    </div>
                                                </div>
                                            );
                                        }

                                        // Phase message (queued/starting/enqueued/retrying/running with step=0)
                                        if (progress && progress.phase) {
                                            const isRetrying = progress.phase === 'retrying';
                                            return (
                                                <div style={{
                                                    marginBottom: '1rem',
                                                    fontSize: '0.85rem',
                                                    color: isRetrying ? '#f59e0b' : 'var(--text-tertiary)',
                                                    display: 'flex',
                                                    alignItems: 'center',
                                                    gap: '0.5rem',
                                                }}>
                                                    <span style={{
                                                        display: 'inline-block',
                                                        width: '8px',
                                                        height: '8px',
                                                        borderRadius: '50%',
                                                        background: isRetrying ? '#f59e0b' : 'var(--primary)',
                                                        animation: 'pulse-dot 1.5s ease-in-out infinite',
                                                    }} />
                                                    {progress.message || 'Initializing exploration agent...'}
                                                </div>
                                            );
                                        }

                                        // No progress data at all — original fallback
                                        return (
                                            <div style={{
                                                marginBottom: '1rem',
                                                fontSize: '0.85rem',
                                                color: 'var(--text-tertiary)',
                                                display: 'flex',
                                                alignItems: 'center',
                                                gap: '0.5rem',
                                            }}>
                                                <span style={{
                                                    display: 'inline-block',
                                                    width: '8px',
                                                    height: '8px',
                                                    borderRadius: '50%',
                                                    background: 'var(--primary)',
                                                    animation: 'pulse-dot 1.5s ease-in-out infinite',
                                                }} />
                                                Initializing exploration agent...
                                            </div>
                                        );
                                    })()}

                                    {/* Counts row — shown always but most useful after completion */}
                                    {session.status !== 'running' && (
                                    <div style={{ display: 'flex', gap: '2rem', marginBottom: '1rem', fontSize: '0.9rem' }}>
                                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                                            <FileText size={16} color="var(--primary)" />
                                            <span><strong>{session.pages_discovered}</strong> pages</span>
                                        </div>
                                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                                            <Zap size={16} color="#f59e0b" />
                                            <span><strong>{session.flows_discovered}</strong> flows</span>
                                        </div>
                                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                                            <Activity size={16} color="#8b5cf6" />
                                            <span><strong>{session.elements_discovered}</strong> elements</span>
                                        </div>
                                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                                            <Globe size={16} color="#10b981" />
                                            <span><strong>{session.api_endpoints_discovered}</strong> APIs</span>
                                        </div>
                                        {(session.issues_discovered > 0) && (
                                            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                                                <AlertTriangle size={16} color="#ef4444" />
                                                <span><strong>{session.issues_discovered}</strong> issues</span>
                                            </div>
                                        )}
                                    </div>
                                    )}

                                    {session.error_message && (
                                        <div style={{
                                            padding: '0.75rem 1rem',
                                            background: 'var(--danger-muted)',
                                            borderRadius: '6px',
                                            marginBottom: '1rem',
                                            fontSize: '0.85rem',
                                            color: 'var(--danger)'
                                        }}>
                                            {session.error_message}
                                        </div>
                                    )}

                                    <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.75rem' }}>
                                        {session.status === 'running' && (
                                            <button
                                                className="btn btn-secondary"
                                                onClick={() => stopExploration(session.id)}
                                                style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}
                                            >
                                                <Square size={16} />
                                                Stop
                                            </button>
                                        )}
                                        {session.status === 'completed' && session.flows_discovered > 0 && (
                                            <button
                                                className="btn btn-secondary"
                                                onClick={() => generateRequirements(session.id)}
                                                disabled={generatingSessionId === session.id}
                                                style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}
                                            >
                                                {generatingSessionId === session.id ? (
                                                    <>
                                                        <Loader2 size={16} className="spinning" />
                                                        Generating...
                                                    </>
                                                ) : (
                                                    <>
                                                        <FileText size={16} />
                                                        Generate Reqs
                                                    </>
                                                )}
                                            </button>
                                        )}
                                        {session.status === 'completed' && session.api_endpoints_discovered > 0 && (
                                            <>
                                                <button
                                                    className="btn btn-secondary"
                                                    onClick={() => generateApiSpecs(session.id)}
                                                    disabled={!!getActiveJob(session.id, 'specs') && getActiveJob(session.id, 'specs')?.status === 'running'}
                                                    style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}
                                                >
                                                    {getActiveJob(session.id, 'specs')?.status === 'running' ? (
                                                        <>
                                                            <Loader2 size={16} className="spinning" />
                                                            Generating...
                                                        </>
                                                    ) : (
                                                        <>
                                                            <FileText size={16} />
                                                            Generate API Specs
                                                        </>
                                                    )}
                                                </button>
                                                <button
                                                    className="btn btn-secondary"
                                                    onClick={() => generateApiTests(session.id)}
                                                    disabled={!!getActiveJob(session.id, 'tests') && getActiveJob(session.id, 'tests')?.status === 'running'}
                                                    style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}
                                                >
                                                    {getActiveJob(session.id, 'tests')?.status === 'running' ? (
                                                        <>
                                                            <Loader2 size={16} className="spinning" />
                                                            Generating...
                                                        </>
                                                    ) : (
                                                        <>
                                                            <Zap size={16} />
                                                            Generate API Tests
                                                        </>
                                                    )}
                                                </button>
                                            </>
                                        )}
                                        <button
                                            className="btn btn-primary"
                                            onClick={() => viewDetails(session)}
                                            style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}
                                        >
                                            <Eye size={16} />
                                            View
                                        </button>
                                    </div>
                                    {/* Requirements generation success banner with navigation link */}
                                    {reqGenResult && reqGenResult.sessionId === session.id && (
                                        <div
                                            style={{
                                                marginTop: '0.5rem',
                                                padding: '0.5rem 0.75rem',
                                                borderRadius: '6px',
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
                                                <CheckCircle2 size={16} style={{ color: '#22c55e' }} />
                                                Generated {reqGenResult.count} requirements!
                                            </span>
                                            <a
                                                href={`/requirements${currentProject?.id ? `?project_id=${encodeURIComponent(currentProject.id)}` : ''}`}
                                                style={{
                                                    display: 'flex',
                                                    alignItems: 'center',
                                                    gap: '0.25rem',
                                                    color: 'var(--primary)',
                                                    textDecoration: 'none',
                                                    fontWeight: 500,
                                                }}
                                            >
                                                View Requirements <ArrowRight size={14} />
                                            </a>
                                        </div>
                                    )}
                                    {/* Inline status banners for spec/test generation jobs */}
                                    {Object.values(specGenJobs)
                                        .filter(j => j.session_id === session.id)
                                        .map(job => (
                                            <div
                                                key={job.job_id}
                                                style={{
                                                    marginTop: '0.5rem',
                                                    padding: '0.5rem 0.75rem',
                                                    borderRadius: '6px',
                                                    fontSize: '0.8rem',
                                                    display: 'flex',
                                                    alignItems: 'center',
                                                    gap: '0.5rem',
                                                    ...(job.status === 'running' ? {
                                                        background: 'var(--primary-glow)',
                                                        border: '1px solid rgba(59, 130, 246, 0.2)',
                                                        color: 'var(--primary)',
                                                    } : job.status === 'completed' ? {
                                                        background: 'var(--success-muted)',
                                                        border: '1px solid rgba(52, 211, 153, 0.2)',
                                                        color: 'var(--success)',
                                                    } : {
                                                        background: 'var(--danger-muted)',
                                                        border: '1px solid rgba(248, 113, 113, 0.2)',
                                                        color: 'var(--danger)',
                                                    }),
                                                }}
                                            >
                                                {job.status === 'running' && <Loader2 size={14} className="spinning" />}
                                                {job.status === 'completed' && <CheckCircle2 size={14} />}
                                                {job.status === 'failed' && <AlertTriangle size={14} />}
                                                <span style={{ flex: 1 }}>
                                                    {job.status === 'running' && (
                                                        <>Generating API {job.type}...</>
                                                    )}
                                                    {job.status === 'completed' && (
                                                        <>Generated {job.result?.count || 0} {job.type === 'specs' ? 'spec' : 'test'} file(s)</>
                                                    )}
                                                    {job.status === 'failed' && (
                                                        <>{job.message || 'Generation failed'}</>
                                                    )}
                                                </span>
                                                {job.status === 'completed' && (
                                                    <a
                                                        href="/api-testing"
                                                        style={{
                                                            color: 'var(--success)',
                                                            textDecoration: 'none',
                                                            fontWeight: 500,
                                                            display: 'flex',
                                                            alignItems: 'center',
                                                            gap: '0.25rem',
                                                        }}
                                                    >
                                                        View in API Testing <ArrowRight size={12} />
                                                    </a>
                                                )}
                                                {job.status === 'failed' && (
                                                    <button
                                                        onClick={() => setSpecGenJobs(prev => {
                                                            const next = { ...prev };
                                                            delete next[job.job_id];
                                                            return next;
                                                        })}
                                                        style={{
                                                            background: 'none',
                                                            border: 'none',
                                                            cursor: 'pointer',
                                                            color: 'var(--danger)',
                                                            padding: '2px',
                                                        }}
                                                    >
                                                        <X size={14} />
                                                    </button>
                                                )}
                                            </div>
                                        ))
                                    }
                                </div>
                            ))}
                        </div>
                    )}
                </div>
            )}

            {/* Explorer Agent Tab Content */}
            {activeTab === 'explorer' && (
                <div className="animate-in stagger-3" style={{ display: 'grid', gridTemplateColumns: '280px 350px 1fr', gap: '1.5rem', minHeight: '70vh' }}>
                    {/* History Sidebar */}
                    <div className="card" style={{ padding: '0', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
                        <div style={{ padding: '1rem', borderBottom: '1px solid var(--border)', background: 'var(--surface-hover)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                            <h3 style={{ fontWeight: 600, fontSize: '0.9rem' }}>Run History</h3>
                            <button onClick={fetchHistory} style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-secondary)' }}>
                                <RotateCcw size={14} />
                            </button>
                        </div>
                        <div style={{ flex: 1, overflowY: 'auto' }}>
                            {history.filter(r => r.agent_type === 'exploratory').length === 0 ? (
                                <div style={{ padding: '2rem', textAlign: 'center', color: 'var(--text-secondary)', fontSize: '0.85rem' }}>
                                    No explorer runs yet.
                                </div>
                            ) : (
                                history.filter(r => r.agent_type === 'exploratory').map(run => (
                                    <div
                                        key={run.id}
                                        onClick={() => setSelectedRunId(run.id)}
                                        style={{
                                            padding: '0.75rem 1rem',
                                            borderBottom: '1px solid var(--border)',
                                            cursor: 'pointer',
                                            background: selectedRunId === run.id ? 'rgba(59, 130, 246, 0.05)' : 'transparent',
                                            borderLeft: selectedRunId === run.id ? '3px solid var(--primary)' : '3px solid transparent'
                                        }}
                                    >
                                        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.25rem' }}>
                                            <span style={{ fontWeight: 600, fontSize: '0.85rem', color: 'var(--warning)' }}>Explorer</span>
                                            <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>{formatDate(run.created_at)}</span>
                                        </div>
                                        <div style={{ fontSize: '0.8rem', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', color: 'var(--text)' }}>
                                            {run.config?.url?.replace('https://', '') || 'No URL'}
                                        </div>
                                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.25rem', marginTop: '0.25rem' }}>
                                            {run.status === 'running' ? <Loader2 size={12} className="spin" color="var(--primary)" /> :
                                                run.status === 'failed' ? <AlertTriangle size={12} color="#ef4444" /> :
                                                    <CheckCircle2 size={12} color="var(--success)" />}
                                            <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', textTransform: 'capitalize' }}>{run.status}</span>
                                        </div>
                                    </div>
                                ))
                            )}
                        </div>
                    </div>

                    {/* Configuration Form */}
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem', overflowY: 'auto' }}>
                        <div className="card" style={{ padding: '1.25rem', flexShrink: 0 }}>
                            <h3 style={{ fontWeight: 600, fontSize: '0.9rem', marginBottom: '1rem' }}>Explorer Agent Configuration</h3>

                            <div style={{ marginBottom: '1rem' }}>
                                <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 500, marginBottom: '0.5rem' }}>Target URL</label>
                                <input
                                    type="text"
                                    placeholder="https://example.com"
                                    value={agentUrl}
                                    onChange={e => setAgentUrl(e.target.value)}
                                    style={{
                                        width: '100%', padding: '0.6rem', borderRadius: '6px', fontSize: '0.9rem',
                                        border: '1px solid var(--input-border)', background: 'var(--input-bg)', color: 'var(--text)'
                                    }}
                                />
                            </div>

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
                                            placeholder="********"
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
                                        value={agentSessionId}
                                        onChange={e => setAgentSessionId(e.target.value)}
                                        list="sessions-list"
                                        style={{
                                            width: '100%', padding: '0.5rem', borderRadius: '4px', fontSize: '0.85rem',
                                            border: '1px solid var(--input-border)', background: 'var(--input-bg)', color: 'var(--text)'
                                        }}
                                    />
                                    <datalist id="sessions-list">
                                        {agentSessions.map(s => (
                                            <option key={s.session_id} value={s.session_id} />
                                        ))}
                                    </datalist>
                                    <p style={{ fontSize: '0.7rem', color: 'var(--text-secondary)', marginTop: '0.5rem' }}>
                                        {agentSessions.length} saved session{agentSessions.length !== 1 ? 's' : ''} available
                                    </p>
                                </div>
                            )}

                            <div style={{ marginBottom: '1.25rem' }}>
                                <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 500, marginBottom: '0.5rem' }}>
                                    Instructions (Optional)
                                </label>
                                <textarea
                                    placeholder="Focus on checkout flow, test edge cases..."
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

                            {showAdvanced && (
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
                                onClick={handleAgentRun}
                                disabled={isAgentStarting}
                                style={{
                                    width: '100%', padding: '0.75rem', borderRadius: '6px', fontSize: '0.9rem',
                                    background: 'var(--primary)', color: 'white', fontWeight: 600, border: 'none', cursor: isAgentStarting ? 'not-allowed' : 'pointer',
                                    display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '0.5rem',
                                    opacity: isAgentStarting ? 0.7 : 1
                                }}
                            >
                                {isAgentStarting ? <><Loader2 className="spin" size={16} /> Starting...</> : <><Play size={16} /> Start Explorer</>}
                            </button>
                        </div>
                    </div>

                    {/* Results Panel */}
                    <div className="card" style={{ padding: '0', display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>
                        <div style={{ padding: '0.75rem 1rem', borderBottom: '1px solid var(--border)', background: 'var(--surface-hover)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                            <h3 style={{ fontWeight: 600, fontSize: '0.9rem' }}>
                                {activeRun ? `Result: ${activeRun.config?.url || 'Unknown'}` : 'Explorer Output'}
                            </h3>
                            {activeRun && (
                                <span style={{
                                    fontSize: '0.75rem', padding: '0.2rem 0.6rem', borderRadius: '12px',
                                    background: activeRun.status === 'completed' ? 'rgba(16, 185, 129, 0.1)' : activeRun.status === 'failed' ? 'rgba(239, 68, 68, 0.1)' : 'rgba(59, 130, 246, 0.1)',
                                    color: activeRun.status === 'completed' ? 'var(--success)' : activeRun.status === 'failed' ? '#ef4444' : 'var(--primary)'
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
                            ) : activeRun.status === 'running' ? (
                                <div style={{ height: '100%', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', color: 'var(--text-secondary)' }}>
                                    <Loader2 size={48} className="spin" style={{ marginBottom: '1rem', color: 'var(--primary)' }} />
                                    <p>Explorer agent is working...</p>
                                    <p style={{ fontSize: '0.9rem', marginTop: '0.5rem' }}>This may take up to {timeLimitMinutes} minutes.</p>
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
                            ) : activeRun.agent_type === 'exploratory' && activeRun.result ? (
                                <ExplorerResults
                                    activeRun={activeRun}
                                    timeLimitMinutes={timeLimitMinutes}
                                    fetchFlowDetails={fetchFlowDetails}
                                    loadingFlowDetails={loadingFlowDetails}
                                    handleSynthesize={handleSynthesize}
                                    isSynthesizing={isSynthesizing}
                                    specResult={specResult}
                                    downloadSpec={downloadSpec}
                                />
                            ) : null}
                        </div>
                    </div>
                </div>
            )}

            {/* Sessions Tab Modals */}
            {modalOpen && (
                <div className="modal-overlay" onClick={() => !isStarting && setModalOpen(false)}>
                    <div className="modal-content" onClick={e => e.stopPropagation()} style={{ width: '500px', maxHeight: '85vh', overflowY: 'auto' }}>
                        <h2 style={{ marginBottom: '1.5rem', display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                            <Compass size={24} color="var(--primary)" />
                            New Exploration
                        </h2>

                        <div style={{ marginBottom: '1.5rem' }}>
                            <label style={{ display: 'block', marginBottom: '0.5rem', fontWeight: 500 }}>
                                Entry URL <span style={{ color: 'var(--danger)' }}>*</span>
                            </label>
                            <input
                                type="url"
                                className="input"
                                placeholder="https://example.com"
                                value={entryUrl}
                                onChange={e => setEntryUrl(e.target.value)}
                                style={{ width: '100%' }}
                            />
                            <p style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginTop: '0.375rem' }}>
                                The starting URL for AI exploration
                            </p>
                        </div>

                        <div style={{ marginBottom: '1.5rem' }}>
                            <label style={{ display: 'block', marginBottom: '0.75rem', fontWeight: 500 }}>
                                Exploration Mode
                            </label>
                            <div style={{ display: 'flex', gap: '0.75rem' }}>
                                {[
                                    { value: 'general' as const, label: 'General', desc: 'Discover pages, flows, elements & APIs', icon: Compass },
                                    { value: 'api_focused' as const, label: 'API Focused', desc: 'Rich API data with headers & bodies', icon: Activity },
                                ].map(opt => (
                                    <button
                                        key={opt.value}
                                        onClick={() => setExplorationMode(opt.value)}
                                        style={{
                                            flex: 1,
                                            padding: '1rem',
                                            borderRadius: '8px',
                                            border: explorationMode === opt.value ? '2px solid var(--primary)' : '1px solid var(--border)',
                                            background: explorationMode === opt.value ? 'rgba(59, 130, 246, 0.1)' : 'transparent',
                                            cursor: 'pointer',
                                            textAlign: 'center'
                                        }}
                                    >
                                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '0.4rem', marginBottom: '0.25rem' }}>
                                            <opt.icon size={16} color={explorationMode === opt.value ? 'var(--primary)' : 'var(--text-secondary)'} />
                                            <span style={{ fontWeight: 600, color: explorationMode === opt.value ? 'var(--primary)' : 'var(--text)' }}>
                                                {opt.label}
                                            </span>
                                        </div>
                                        <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
                                            {opt.desc}
                                        </div>
                                    </button>
                                ))}
                            </div>
                            {explorationMode === 'api_focused' && (
                                <p style={{ fontSize: '0.8rem', color: 'var(--primary)', marginTop: '0.5rem', display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                                    <Info size={14} />
                                    Captures full request/response details for each API endpoint discovered
                                </p>
                            )}
                        </div>

                        <div style={{ marginBottom: '1.5rem' }}>
                            <label style={{ display: 'block', marginBottom: '0.75rem', fontWeight: 500 }}>
                                Thoroughness Level
                            </label>
                            <div style={{ display: 'flex', gap: '0.75rem' }}>
                                {[
                                    { value: 'quick', label: 'Quick', desc: 'Fast scan, main features' },
                                    { value: 'normal', label: 'Normal', desc: 'Balanced exploration' },
                                    { value: 'comprehensive', label: 'Comprehensive', desc: 'Deep exploration' }
                                ].map(opt => (
                                    <button
                                        key={opt.value}
                                        onClick={() => setThoroughness(opt.value as typeof thoroughness)}
                                        style={{
                                            flex: 1,
                                            padding: '1rem',
                                            borderRadius: '8px',
                                            border: thoroughness === opt.value ? '2px solid var(--primary)' : '1px solid var(--border)',
                                            background: thoroughness === opt.value ? 'rgba(59, 130, 246, 0.1)' : 'transparent',
                                            cursor: 'pointer',
                                            textAlign: 'center'
                                        }}
                                    >
                                        <div style={{ fontWeight: 600, marginBottom: '0.25rem', color: thoroughness === opt.value ? 'var(--primary)' : 'var(--text)' }}>
                                            {opt.label}
                                        </div>
                                        <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
                                            {opt.desc}
                                        </div>
                                    </button>
                                ))}
                            </div>
                        </div>

                        <div style={{ marginBottom: '1.5rem' }}>
                            <label style={{ display: 'block', marginBottom: '0.5rem', fontWeight: 500 }}>
                                Login URL <span style={{ color: 'var(--text-secondary)', fontWeight: 400 }}>(optional)</span>
                            </label>
                            <input
                                type="url"
                                className="input"
                                placeholder="https://example.com/login"
                                value={loginUrl}
                                onChange={e => setLoginUrl(e.target.value)}
                                style={{ width: '100%' }}
                            />
                            <p style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginTop: '0.375rem' }}>
                                For auth-protected apps
                            </p>
                        </div>

                        {/* Credentials - shown when Login URL is provided */}
                        {loginUrl && (
                            <div style={{
                                marginBottom: '1.5rem',
                                padding: '1rem',
                                background: 'var(--surface-hover)',
                                borderRadius: '8px',
                                border: '1px solid var(--border)'
                            }}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '1rem' }}>
                                    <Lock size={16} style={{ color: 'var(--primary)' }} />
                                    <span style={{ fontWeight: 500 }}>Login Credentials</span>
                                </div>
                                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}>
                                    <div>
                                        <label style={{ display: 'block', marginBottom: '0.375rem', fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
                                            Username / Email
                                        </label>
                                        <input
                                            type="text"
                                            className="input"
                                            placeholder="user@example.com"
                                            value={loginUsername}
                                            onChange={e => setLoginUsername(e.target.value)}
                                            style={{ width: '100%' }}
                                        />
                                    </div>
                                    <div>
                                        <label style={{ display: 'block', marginBottom: '0.375rem', fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
                                            Password
                                        </label>
                                        <input
                                            type="password"
                                            className="input"
                                            placeholder="••••••••"
                                            value={loginPassword}
                                            onChange={e => setLoginPassword(e.target.value)}
                                            style={{ width: '100%' }}
                                        />
                                    </div>
                                </div>
                                <p style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', marginTop: '0.75rem' }}>
                                    Credentials are used by the AI to log in before exploring
                                </p>
                            </div>
                        )}

                        {/* Additional Instructions */}
                        <div style={{ marginBottom: '1.5rem' }}>
                            <label style={{ display: 'block', marginBottom: '0.5rem', fontWeight: 500 }}>
                                Additional Instructions <span style={{ color: 'var(--text-secondary)', fontWeight: 400 }}>(optional)</span>
                            </label>
                            <textarea
                                value={additionalInstructions}
                                onChange={(e) => setAdditionalInstructions(e.target.value)}
                                placeholder="E.g., Login with username 'demo' and password from .env, focus on the checkout flow, skip the admin section..."
                                rows={4}
                                style={{
                                    width: '100%',
                                    padding: '0.75rem 1rem',
                                    borderRadius: '8px',
                                    border: '1px solid var(--border)',
                                    background: 'var(--surface-hover)',
                                    color: 'var(--text)',
                                    fontSize: '0.9rem',
                                    resize: 'vertical',
                                    fontFamily: 'inherit'
                                }}
                            />
                            <p style={{ marginTop: '0.5rem', fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                                Provide hints for the AI: credentials, areas to focus on, sections to skip, etc.
                            </p>
                        </div>

                        <div style={{
                            padding: '1rem',
                            background: 'rgba(59, 130, 246, 0.06)',
                            border: '1px solid rgba(59, 130, 246, 0.2)',
                            borderRadius: '8px',
                            marginBottom: '1.5rem',
                            fontSize: '0.85rem',
                            color: 'var(--text-secondary)'
                        }}>
                            {explorationMode === 'api_focused'
                                ? 'The AI agent will focus on discovering API endpoints with full request/response details, including headers, bodies, and authentication patterns.'
                                : 'The AI agent will autonomously explore the application, discovering pages, user flows, form interactions, and API endpoints.'
                            }
                        </div>

                        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '1rem' }}>
                            <button
                                className="btn btn-secondary"
                                onClick={() => setModalOpen(false)}
                                disabled={isStarting}
                            >
                                Cancel
                            </button>
                            <button
                                className="btn btn-primary"
                                onClick={startExploration}
                                disabled={!entryUrl || isStarting}
                                style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}
                            >
                                {isStarting ? <Loader2 size={16} className="spinning" /> : <Play size={16} />}
                                {isStarting ? 'Starting...' : 'Start Exploration'}
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {detailModalOpen && selectedSession && (
                <div className="modal-overlay" onClick={() => setDetailModalOpen(false)}>
                    <div className="modal-content" onClick={e => e.stopPropagation()} style={{ width: '900px', maxHeight: '85vh', overflow: 'auto' }}>
                        {/* Header */}
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '1.5rem' }}>
                            <div>
                                <h2 style={{ marginBottom: '0.5rem' }}>Exploration Details</h2>
                                <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem' }}>{selectedSession.entry_url}</p>
                                {selectedSession.duration_seconds && (
                                    <p style={{ color: 'var(--text-secondary)', fontSize: '0.8rem', marginTop: '0.25rem' }}>
                                        Duration: {formatDuration(selectedSession.duration_seconds)}
                                    </p>
                                )}
                            </div>
                            <button
                                onClick={() => setDetailModalOpen(false)}
                                style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-secondary)' }}
                            >
                                <X size={24} />
                            </button>
                        </div>

                        {detailsLoading ? (
                            <div style={{ padding: '3rem', textAlign: 'center' }}>
                                <Loader2 size={32} className="spinning" style={{ color: 'var(--primary)' }} />
                                <p style={{ marginTop: '1rem', color: 'var(--text-secondary)' }}>Loading exploration data...</p>
                            </div>
                        ) : explorationDetails ? (
                            <>
                                {/* Summary stats - clickable */}
                                <div style={{ display: 'grid', gridTemplateColumns: `repeat(${(explorationDetails.issues?.length || 0) > 0 ? 5 : 4}, 1fr)`, gap: '0.75rem', marginBottom: '1.5rem' }}>
                                    {[
                                        { label: 'Pages', value: explorationDetails.pages.length || explorationDetails.session.pages_discovered || 0, color: 'var(--primary)', tab: 'pages' as DetailTabType },
                                        { label: 'Flows', value: explorationDetails.flows.length || explorationDetails.session.flows_discovered || 0, color: 'var(--warning)', tab: 'flows' as DetailTabType },
                                        { label: 'Elements', value: explorationDetails.elements.length || explorationDetails.session.elements_discovered || 0, color: 'var(--accent)', tab: 'elements' as DetailTabType },
                                        { label: 'APIs', value: explorationDetails.api_endpoints.length || explorationDetails.session.api_endpoints_discovered || 0, color: 'var(--success)', tab: 'apis' as DetailTabType },
                                        ...((explorationDetails.issues?.length || 0) > 0 ? [{ label: 'Issues', value: explorationDetails.issues.length, color: 'var(--danger)', tab: 'issues' as DetailTabType }] : [])
                                    ].map(stat => (
                                        <div
                                            key={stat.label}
                                            onClick={() => setDetailTab(stat.tab)}
                                            style={{
                                                textAlign: 'center',
                                                padding: '0.75rem',
                                                background: detailTab === stat.tab ? `${stat.color}15` : 'var(--surface-hover)',
                                                borderRadius: '8px',
                                                cursor: 'pointer',
                                                border: detailTab === stat.tab ? `2px solid ${stat.color}` : '2px solid transparent',
                                                transition: 'all 0.2s var(--ease-smooth)'
                                            }}
                                        >
                                            <div style={{ fontSize: '1.5rem', fontWeight: 700, color: stat.color }}>{stat.value}</div>
                                            <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>{stat.label}</div>
                                        </div>
                                    ))}
                                </div>

                                {/* Tab bar */}
                                <div style={{ display: 'flex', gap: '0.25rem', marginBottom: '1.5rem', borderBottom: '1px solid var(--border)', paddingBottom: '0' }}>
                                    {[
                                        { key: 'pages' as DetailTabType, label: 'Pages', count: explorationDetails.pages.length },
                                        { key: 'flows' as DetailTabType, label: 'Flows', count: explorationDetails.flows.length },
                                        { key: 'elements' as DetailTabType, label: 'Elements', count: explorationDetails.elements.length },
                                        { key: 'apis' as DetailTabType, label: 'APIs', count: explorationDetails.api_endpoints.length },
                                        ...((explorationDetails.issues?.length || 0) > 0 ? [{ key: 'issues' as DetailTabType, label: 'Issues', count: explorationDetails.issues.length }] : []),
                                    ].map(tab => (
                                        <button
                                            key={tab.key}
                                            onClick={() => setDetailTab(tab.key)}
                                            style={{
                                                padding: '0.6rem 1rem',
                                                background: 'transparent',
                                                border: 'none',
                                                borderBottom: detailTab === tab.key ? '2px solid var(--primary)' : '2px solid transparent',
                                                color: detailTab === tab.key ? 'var(--primary)' : 'var(--text-secondary)',
                                                fontWeight: detailTab === tab.key ? 600 : 400,
                                                cursor: 'pointer',
                                                fontSize: '0.9rem',
                                                transition: 'all 0.2s var(--ease-smooth)'
                                            }}
                                        >
                                            {tab.label} ({tab.count})
                                        </button>
                                    ))}
                                </div>

                                {/* ===== PAGES TAB ===== */}
                                {detailTab === 'pages' && (
                                    <div>
                                        {explorationDetails.pages.length === 0 ? (
                                            <div style={{ padding: '2rem', textAlign: 'center', color: 'var(--text-secondary)', background: 'var(--surface-hover)', borderRadius: '8px' }}>
                                                No pages discovered
                                            </div>
                                        ) : (
                                            <div style={{ overflowX: 'auto' }}>
                                                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.85rem' }}>
                                                    <thead>
                                                        <tr style={{ borderBottom: '1px solid var(--border)' }}>
                                                            <th style={{ textAlign: 'left', padding: '0.5rem', color: 'var(--text-secondary)', fontWeight: 600 }}>URL</th>
                                                            <th style={{ textAlign: 'left', padding: '0.5rem', color: 'var(--text-secondary)', fontWeight: 600 }}>Type</th>
                                                            <th style={{ textAlign: 'center', padding: '0.5rem', color: 'var(--text-secondary)', fontWeight: 600 }}>Visits</th>
                                                            <th style={{ textAlign: 'left', padding: '0.5rem', color: 'var(--text-secondary)', fontWeight: 600 }}>Actions</th>
                                                        </tr>
                                                    </thead>
                                                    <tbody>
                                                        {explorationDetails.pages.map((page, i) => (
                                                            <tr key={i} style={{ borderBottom: '1px solid var(--border)' }}>
                                                                <td style={{ padding: '0.5rem', maxWidth: '350px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={page.url}>
                                                                    {page.url}
                                                                </td>
                                                                <td style={{ padding: '0.5rem' }}>
                                                                    {page.page_type && (
                                                                        <span style={{ padding: '0.15rem 0.5rem', borderRadius: '4px', fontSize: '0.75rem', background: 'var(--primary-glow)', color: 'var(--primary)' }}>
                                                                            {page.page_type}
                                                                        </span>
                                                                    )}
                                                                </td>
                                                                <td style={{ padding: '0.5rem', textAlign: 'center' }}>{page.visit_count}</td>
                                                                <td style={{ padding: '0.5rem' }}>
                                                                    <div style={{ display: 'flex', gap: '0.25rem', flexWrap: 'wrap' }}>
                                                                        {page.actions_performed.map((action, j) => (
                                                                            <span key={j} style={{ padding: '0.1rem 0.4rem', borderRadius: '3px', fontSize: '0.7rem', background: 'rgba(192, 132, 252, 0.12)', color: 'var(--accent)' }}>
                                                                                {action}
                                                                            </span>
                                                                        ))}
                                                                    </div>
                                                                </td>
                                                            </tr>
                                                        ))}
                                                    </tbody>
                                                </table>
                                            </div>
                                        )}
                                    </div>
                                )}

                                {/* ===== FLOWS TAB ===== */}
                                {detailTab === 'flows' && (
                                    <div>
                                        {explorationDetails.flows.length === 0 ? (
                                            <div style={{ padding: '2rem', textAlign: 'center', color: 'var(--text-secondary)', background: 'var(--surface-hover)', borderRadius: '8px' }}>
                                                No flows discovered
                                            </div>
                                        ) : (
                                            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                                                {explorationDetails.flows.map(flow => (
                                                    <div key={flow.id} style={{ background: 'var(--surface-hover)', borderRadius: '8px', border: '1px solid var(--border)', overflow: 'hidden' }}>
                                                        {/* Flow header - always visible */}
                                                        <div
                                                            style={{ padding: '1rem', cursor: 'pointer', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}
                                                            onClick={() => setExpandedFlowId(expandedFlowId === flow.id ? null : flow.id)}
                                                        >
                                                            <div style={{ flex: 1 }}>
                                                                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.25rem' }}>
                                                                    <ChevronRight size={16} style={{ transform: expandedFlowId === flow.id ? 'rotate(90deg)' : 'none', transition: 'transform 0.2s' }} />
                                                                    <span style={{ fontWeight: 600 }}>{flow.flow_name}</span>
                                                                    <span style={{ padding: '0.15rem 0.5rem', borderRadius: '4px', fontSize: '0.7rem', background: 'rgba(192, 132, 252, 0.12)', color: 'var(--accent)' }}>
                                                                        {flow.flow_category}
                                                                    </span>
                                                                    <span style={{ padding: '0.15rem 0.5rem', borderRadius: '4px', fontSize: '0.7rem', background: flow.is_success_path ? 'rgba(16, 185, 129, 0.1)' : 'rgba(245, 158, 11, 0.1)', color: flow.is_success_path ? '#10b981' : '#f59e0b' }}>
                                                                        {flow.is_success_path ? 'Success' : 'Alternative'}
                                                                    </span>
                                                                </div>
                                                                {flow.description && (
                                                                    <p style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', margin: '0 0 0 1.5rem' }}>{flow.description}</p>
                                                                )}
                                                            </div>
                                                            <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
                                                                <span style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>{flow.step_count} steps</span>
                                                                <button
                                                                    onClick={(e) => { e.stopPropagation(); setEditingExplorationFlow({ ...flow }); setIsEditingExplorationFlow(true); }}
                                                                    style={{ padding: '0.3rem', background: 'transparent', border: '1px solid var(--border)', borderRadius: '4px', cursor: 'pointer', color: 'var(--text-secondary)', display: 'flex' }}
                                                                    title="Edit flow"
                                                                >
                                                                    <Edit size={14} />
                                                                </button>
                                                                <button
                                                                    onClick={(e) => { e.stopPropagation(); setDeleteExplorationFlowId(flow.id); }}
                                                                    style={{ padding: '0.3rem', background: 'transparent', border: '1px solid var(--border)', borderRadius: '4px', cursor: 'pointer', color: 'var(--danger)', display: 'flex' }}
                                                                    title="Delete flow"
                                                                >
                                                                    <Trash2 size={14} />
                                                                </button>
                                                            </div>
                                                        </div>

                                                        {/* Expanded flow details */}
                                                        {expandedFlowId === flow.id && !isEditingExplorationFlow && (
                                                            <div style={{ padding: '0 1rem 1rem', borderTop: '1px solid var(--border)' }}>
                                                                {flow.preconditions.length > 0 && (
                                                                    <div style={{ marginTop: '0.75rem' }}>
                                                                        <h4 style={{ fontSize: '0.8rem', fontWeight: 600, marginBottom: '0.25rem', color: 'var(--text-secondary)' }}>Preconditions</h4>
                                                                        <ul style={{ margin: 0, paddingLeft: '1.5rem', fontSize: '0.8rem' }}>
                                                                            {flow.preconditions.map((p, i) => <li key={i}>{p}</li>)}
                                                                        </ul>
                                                                    </div>
                                                                )}
                                                                <div style={{ marginTop: '0.75rem' }}>
                                                                    <h4 style={{ fontSize: '0.8rem', fontWeight: 600, marginBottom: '0.5rem', color: 'var(--text-secondary)' }}>Steps</h4>
                                                                    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.4rem' }}>
                                                                        {flow.steps.map(step => (
                                                                            <div key={step.id} style={{ display: 'flex', alignItems: 'flex-start', gap: '0.5rem', fontSize: '0.8rem', padding: '0.4rem 0.5rem', background: 'var(--surface)', borderRadius: '4px' }}>
                                                                                <span style={{ fontWeight: 600, color: 'var(--primary)', minWidth: '1.5rem' }}>{step.step_number}.</span>
                                                                                <span style={{ padding: '0.1rem 0.3rem', borderRadius: '3px', fontSize: '0.7rem', background: 'var(--primary-glow)', color: 'var(--primary)', flexShrink: 0 }}>{step.action_type}</span>
                                                                                <span style={{ flex: 1 }}>{step.action_description}</span>
                                                                                {step.value && <span style={{ color: 'var(--text-secondary)', fontStyle: 'italic' }}>"{step.value}"</span>}
                                                                            </div>
                                                                        ))}
                                                                    </div>
                                                                </div>
                                                                {flow.postconditions.length > 0 && (
                                                                    <div style={{ marginTop: '0.75rem' }}>
                                                                        <h4 style={{ fontSize: '0.8rem', fontWeight: 600, marginBottom: '0.25rem', color: 'var(--text-secondary)' }}>Postconditions</h4>
                                                                        <ul style={{ margin: 0, paddingLeft: '1.5rem', fontSize: '0.8rem' }}>
                                                                            {flow.postconditions.map((p, i) => <li key={i}>{p}</li>)}
                                                                        </ul>
                                                                    </div>
                                                                )}
                                                            </div>
                                                        )}

                                                        {/* Inline edit form for this flow */}
                                                        {isEditingExplorationFlow && editingExplorationFlow?.id === flow.id && (
                                                            <div style={{ padding: '1rem', borderTop: '1px solid var(--border)', background: 'rgba(59, 130, 246, 0.02)' }}>
                                                                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem', marginBottom: '0.75rem' }}>
                                                                    <div>
                                                                        <label style={{ fontSize: '0.8rem', fontWeight: 600, display: 'block', marginBottom: '0.25rem' }}>Flow Name</label>
                                                                        <input type="text" value={editingExplorationFlow.flow_name} onChange={e => setEditingExplorationFlow({ ...editingExplorationFlow, flow_name: e.target.value })} style={{ width: '100%', padding: '0.4rem 0.6rem', background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: '6px', fontSize: '0.85rem', color: 'var(--text)', outline: 'none', boxSizing: 'border-box' }} />
                                                                    </div>
                                                                    <div>
                                                                        <label style={{ fontSize: '0.8rem', fontWeight: 600, display: 'block', marginBottom: '0.25rem' }}>Category</label>
                                                                        <input type="text" value={editingExplorationFlow.flow_category} onChange={e => setEditingExplorationFlow({ ...editingExplorationFlow, flow_category: e.target.value })} style={{ width: '100%', padding: '0.4rem 0.6rem', background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: '6px', fontSize: '0.85rem', color: 'var(--text)', outline: 'none', boxSizing: 'border-box' }} />
                                                                    </div>
                                                                </div>
                                                                <div style={{ marginBottom: '0.75rem' }}>
                                                                    <label style={{ fontSize: '0.8rem', fontWeight: 600, display: 'block', marginBottom: '0.25rem' }}>Description</label>
                                                                    <textarea value={editingExplorationFlow.description || ''} onChange={e => setEditingExplorationFlow({ ...editingExplorationFlow, description: e.target.value })} rows={2} style={{ width: '100%', padding: '0.4rem 0.6rem', background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: '6px', fontSize: '0.85rem', color: 'var(--text)', outline: 'none', resize: 'vertical', fontFamily: 'inherit', boxSizing: 'border-box' }} />
                                                                </div>
                                                                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.75rem' }}>
                                                                    <input type="checkbox" checked={editingExplorationFlow.is_success_path} onChange={e => setEditingExplorationFlow({ ...editingExplorationFlow, is_success_path: e.target.checked })} id="success-path-check" />
                                                                    <label htmlFor="success-path-check" style={{ fontSize: '0.85rem' }}>Success path</label>
                                                                </div>
                                                                <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.5rem' }}>
                                                                    <button onClick={() => { setIsEditingExplorationFlow(false); setEditingExplorationFlow(null); }} style={{ padding: '0.4rem 0.8rem', background: 'transparent', border: '1px solid var(--border)', borderRadius: '6px', cursor: 'pointer', fontSize: '0.85rem', color: 'var(--text-secondary)' }}>Cancel</button>
                                                                    <button onClick={() => saveExplorationFlow(flow)} disabled={isSavingExplorationFlow} style={{ padding: '0.4rem 0.8rem', background: 'var(--primary)', color: 'white', border: 'none', borderRadius: '6px', cursor: 'pointer', fontSize: '0.85rem', display: 'flex', alignItems: 'center', gap: '0.3rem', opacity: isSavingExplorationFlow ? 0.7 : 1 }}>
                                                                        {isSavingExplorationFlow ? <Loader2 size={14} className="spinning" /> : <Save size={14} />}
                                                                        Save
                                                                    </button>
                                                                </div>
                                                            </div>
                                                        )}
                                                    </div>
                                                ))}
                                            </div>
                                        )}

                                        {/* Delete flow confirmation */}
                                        {deleteExplorationFlowId !== null && (
                                            <div style={{ marginTop: '1rem', padding: '1rem', background: 'rgba(248, 113, 113, 0.06)', border: '1px solid rgba(248, 113, 113, 0.2)', borderRadius: '8px' }}>
                                                <p style={{ marginBottom: '0.75rem', fontSize: '0.9rem' }}>Delete this flow? This cannot be undone.</p>
                                                <div style={{ display: 'flex', gap: '0.5rem', justifyContent: 'flex-end' }}>
                                                    <button onClick={() => setDeleteExplorationFlowId(null)} style={{ padding: '0.4rem 0.8rem', background: 'transparent', border: '1px solid var(--border)', borderRadius: '6px', cursor: 'pointer', fontSize: '0.85rem' }}>Cancel</button>
                                                    <button onClick={() => deleteExplorationFlow(deleteExplorationFlowId)} style={{ padding: '0.4rem 0.8rem', background: 'var(--danger)', color: 'white', border: 'none', borderRadius: '6px', cursor: 'pointer', fontSize: '0.85rem' }}>Delete</button>
                                                </div>
                                            </div>
                                        )}
                                    </div>
                                )}

                                {/* ===== ELEMENTS TAB ===== */}
                                {detailTab === 'elements' && (
                                    <div>
                                        {explorationDetails.elements.length === 0 ? (
                                            <div style={{ padding: '2rem', textAlign: 'center', color: 'var(--text-secondary)', background: 'var(--surface-hover)', borderRadius: '8px' }}>
                                                No elements discovered
                                            </div>
                                        ) : (
                                            <div style={{ overflowX: 'auto' }}>
                                                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.85rem' }}>
                                                    <thead>
                                                        <tr style={{ borderBottom: '1px solid var(--border)' }}>
                                                            <th style={{ textAlign: 'left', padding: '0.5rem', color: 'var(--text-secondary)', fontWeight: 600 }}>Element</th>
                                                            <th style={{ textAlign: 'left', padding: '0.5rem', color: 'var(--text-secondary)', fontWeight: 600 }}>Role</th>
                                                            <th style={{ textAlign: 'left', padding: '0.5rem', color: 'var(--text-secondary)', fontWeight: 600 }}>Action</th>
                                                            <th style={{ textAlign: 'left', padding: '0.5rem', color: 'var(--text-secondary)', fontWeight: 600 }}>Value</th>
                                                            <th style={{ textAlign: 'left', padding: '0.5rem', color: 'var(--text-secondary)', fontWeight: 600 }}>Page</th>
                                                            <th style={{ textAlign: 'center', padding: '0.5rem', color: 'var(--text-secondary)', fontWeight: 600 }}>Count</th>
                                                        </tr>
                                                    </thead>
                                                    <tbody>
                                                        {explorationDetails.elements.map((el, i) => (
                                                            <tr key={i} style={{ borderBottom: '1px solid var(--border)' }}>
                                                                <td style={{ padding: '0.5rem', fontWeight: 500 }}>{el.element_name || el.element_ref || '\u2014'}</td>
                                                                <td style={{ padding: '0.5rem' }}>
                                                                    {el.element_role && (
                                                                        <span style={{ padding: '0.1rem 0.4rem', borderRadius: '3px', fontSize: '0.7rem', background: 'rgba(192, 132, 252, 0.12)', color: 'var(--accent)' }}>{el.element_role}</span>
                                                                    )}
                                                                </td>
                                                                <td style={{ padding: '0.5rem' }}>
                                                                    <span style={{ padding: '0.1rem 0.4rem', borderRadius: '3px', fontSize: '0.7rem', background: 'var(--primary-glow)', color: 'var(--primary)' }}>{el.action_type}</span>
                                                                </td>
                                                                <td style={{ padding: '0.5rem', color: 'var(--text-secondary)', fontStyle: el.action_value ? 'italic' : 'normal', maxWidth: '150px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={el.action_value || ''}>
                                                                    {el.action_value || '\u2014'}
                                                                </td>
                                                                <td style={{ padding: '0.5rem', maxWidth: '200px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', color: 'var(--text-secondary)' }} title={el.page_url}>
                                                                    {el.page_url}
                                                                </td>
                                                                <td style={{ padding: '0.5rem', textAlign: 'center', fontWeight: 600 }}>{el.occurrence_count}</td>
                                                            </tr>
                                                        ))}
                                                    </tbody>
                                                </table>
                                            </div>
                                        )}
                                    </div>
                                )}

                                {/* ===== APIS TAB ===== */}
                                {detailTab === 'apis' && (
                                    <div>
                                        {explorationDetails.api_endpoints.length === 0 ? (
                                            <div style={{ padding: '2rem', textAlign: 'center', color: 'var(--text-secondary)', background: 'var(--surface-hover)', borderRadius: '8px' }}>
                                                No API endpoints discovered
                                            </div>
                                        ) : (
                                            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                                                {explorationDetails.api_endpoints.map(endpoint => {
                                                    const methodColors: Record<string, string> = { GET: 'var(--success)', POST: 'var(--primary)', PUT: 'var(--warning)', PATCH: 'var(--warning)', DELETE: 'var(--danger)' };
                                                    const methodColor = methodColors[endpoint.method] || 'var(--text-secondary)';
                                                    return (
                                                        <div key={endpoint.id} style={{ background: 'var(--surface-hover)', borderRadius: '8px', border: '1px solid var(--border)', overflow: 'hidden' }}>
                                                            <div
                                                                style={{ padding: '0.75rem 1rem', cursor: 'pointer', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}
                                                                onClick={() => setExpandedApiId(expandedApiId === endpoint.id ? null : endpoint.id)}
                                                            >
                                                                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flex: 1, overflow: 'hidden' }}>
                                                                    <ChevronRight size={16} style={{ transform: expandedApiId === endpoint.id ? 'rotate(90deg)' : 'none', transition: 'transform 0.2s', flexShrink: 0 }} />
                                                                    <span style={{ padding: '0.15rem 0.5rem', borderRadius: '4px', fontSize: '0.75rem', fontWeight: 700, background: `${methodColor}15`, color: methodColor, flexShrink: 0 }}>{endpoint.method}</span>
                                                                    <span style={{ fontSize: '0.85rem', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={endpoint.url}>{endpoint.url}</span>
                                                                </div>
                                                                <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', flexShrink: 0 }}>
                                                                    {endpoint.response_status && (
                                                                        <span style={{ fontSize: '0.75rem', color: endpoint.response_status < 400 ? '#10b981' : '#ef4444' }}>{endpoint.response_status}</span>
                                                                    )}
                                                                    <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>{endpoint.call_count}x</span>
                                                                    <button onClick={(e) => { e.stopPropagation(); setEditingApiEndpoint({ ...endpoint }); setIsEditingApiEndpoint(true); }} style={{ padding: '0.3rem', background: 'transparent', border: '1px solid var(--border)', borderRadius: '4px', cursor: 'pointer', color: 'var(--text-secondary)', display: 'flex' }} title="Edit">
                                                                        <Edit size={14} />
                                                                    </button>
                                                                    <button onClick={(e) => { e.stopPropagation(); setDeleteApiEndpointId(endpoint.id); }} style={{ padding: '0.3rem', background: 'transparent', border: '1px solid var(--border)', borderRadius: '4px', cursor: 'pointer', color: 'var(--danger)', display: 'flex' }} title="Delete">
                                                                        <Trash2 size={14} />
                                                                    </button>
                                                                </div>
                                                            </div>

                                                            {/* Expanded API details */}
                                                            {expandedApiId === endpoint.id && !isEditingApiEndpoint && (
                                                                <div style={{ padding: '0 1rem 1rem', borderTop: '1px solid var(--border)', fontSize: '0.8rem' }}>
                                                                    {endpoint.triggered_by_action && (
                                                                        <div style={{ marginTop: '0.75rem' }}>
                                                                            <span style={{ fontWeight: 600, color: 'var(--text-secondary)' }}>Triggered by: </span>
                                                                            <span>{endpoint.triggered_by_action}</span>
                                                                        </div>
                                                                    )}
                                                                    {endpoint.request_headers && Object.keys(endpoint.request_headers).length > 0 && (
                                                                        <div style={{ marginTop: '0.75rem' }}>
                                                                            <h4 style={{ fontSize: '0.8rem', fontWeight: 600, marginBottom: '0.25rem', color: 'var(--text-secondary)' }}>Request Headers</h4>
                                                                            <pre style={{ margin: 0, padding: '0.5rem', background: 'var(--surface)', borderRadius: '4px', fontSize: '0.75rem', overflow: 'auto', maxHeight: '150px' }}>{JSON.stringify(endpoint.request_headers, null, 2)}</pre>
                                                                        </div>
                                                                    )}
                                                                    {endpoint.request_body_sample && (
                                                                        <div style={{ marginTop: '0.75rem' }}>
                                                                            <h4 style={{ fontSize: '0.8rem', fontWeight: 600, marginBottom: '0.25rem', color: 'var(--text-secondary)' }}>Request Body</h4>
                                                                            <pre style={{ margin: 0, padding: '0.5rem', background: 'var(--surface)', borderRadius: '4px', fontSize: '0.75rem', overflow: 'auto', maxHeight: '150px' }}>{endpoint.request_body_sample}</pre>
                                                                        </div>
                                                                    )}
                                                                    {endpoint.response_body_sample && (
                                                                        <div style={{ marginTop: '0.75rem' }}>
                                                                            <h4 style={{ fontSize: '0.8rem', fontWeight: 600, marginBottom: '0.25rem', color: 'var(--text-secondary)' }}>Response Body</h4>
                                                                            <pre style={{ margin: 0, padding: '0.5rem', background: 'var(--surface)', borderRadius: '4px', fontSize: '0.75rem', overflow: 'auto', maxHeight: '150px' }}>{endpoint.response_body_sample}</pre>
                                                                        </div>
                                                                    )}
                                                                </div>
                                                            )}

                                                            {/* Inline edit form */}
                                                            {isEditingApiEndpoint && editingApiEndpoint?.id === endpoint.id && (
                                                                <div style={{ padding: '1rem', borderTop: '1px solid var(--border)', background: 'rgba(59, 130, 246, 0.02)' }}>
                                                                    <div style={{ display: 'grid', gridTemplateColumns: '100px 1fr 100px', gap: '0.75rem', marginBottom: '0.75rem' }}>
                                                                        <div>
                                                                            <label style={{ fontSize: '0.8rem', fontWeight: 600, display: 'block', marginBottom: '0.25rem' }}>Method</label>
                                                                            <select value={editingApiEndpoint.method} onChange={e => setEditingApiEndpoint({ ...editingApiEndpoint, method: e.target.value })} style={{ width: '100%', padding: '0.4rem', background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: '6px', fontSize: '0.85rem', color: 'var(--text)' }}>
                                                                                {['GET', 'POST', 'PUT', 'PATCH', 'DELETE'].map(m => <option key={m} value={m}>{m}</option>)}
                                                                            </select>
                                                                        </div>
                                                                        <div>
                                                                            <label style={{ fontSize: '0.8rem', fontWeight: 600, display: 'block', marginBottom: '0.25rem' }}>URL</label>
                                                                            <input type="text" value={editingApiEndpoint.url} onChange={e => setEditingApiEndpoint({ ...editingApiEndpoint, url: e.target.value })} style={{ width: '100%', padding: '0.4rem 0.6rem', background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: '6px', fontSize: '0.85rem', color: 'var(--text)', outline: 'none', boxSizing: 'border-box' }} />
                                                                        </div>
                                                                        <div>
                                                                            <label style={{ fontSize: '0.8rem', fontWeight: 600, display: 'block', marginBottom: '0.25rem' }}>Status</label>
                                                                            <input type="number" value={editingApiEndpoint.response_status || ''} onChange={e => setEditingApiEndpoint({ ...editingApiEndpoint, response_status: e.target.value ? parseInt(e.target.value) : null })} style={{ width: '100%', padding: '0.4rem 0.6rem', background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: '6px', fontSize: '0.85rem', color: 'var(--text)', outline: 'none', boxSizing: 'border-box' }} />
                                                                        </div>
                                                                    </div>
                                                                    <div style={{ marginBottom: '0.75rem' }}>
                                                                        <label style={{ fontSize: '0.8rem', fontWeight: 600, display: 'block', marginBottom: '0.25rem' }}>Triggered By</label>
                                                                        <input type="text" value={editingApiEndpoint.triggered_by_action || ''} onChange={e => setEditingApiEndpoint({ ...editingApiEndpoint, triggered_by_action: e.target.value })} style={{ width: '100%', padding: '0.4rem 0.6rem', background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: '6px', fontSize: '0.85rem', color: 'var(--text)', outline: 'none', boxSizing: 'border-box' }} />
                                                                    </div>
                                                                    <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.5rem' }}>
                                                                        <button onClick={() => { setIsEditingApiEndpoint(false); setEditingApiEndpoint(null); }} style={{ padding: '0.4rem 0.8rem', background: 'transparent', border: '1px solid var(--border)', borderRadius: '6px', cursor: 'pointer', fontSize: '0.85rem', color: 'var(--text-secondary)' }}>Cancel</button>
                                                                        <button onClick={() => saveApiEndpoint(endpoint)} disabled={isSavingApiEndpoint} style={{ padding: '0.4rem 0.8rem', background: 'var(--primary)', color: 'white', border: 'none', borderRadius: '6px', cursor: 'pointer', fontSize: '0.85rem', display: 'flex', alignItems: 'center', gap: '0.3rem', opacity: isSavingApiEndpoint ? 0.7 : 1 }}>
                                                                            {isSavingApiEndpoint ? <Loader2 size={14} className="spinning" /> : <Save size={14} />}
                                                                            Save
                                                                        </button>
                                                                    </div>
                                                                </div>
                                                            )}
                                                        </div>
                                                    );
                                                })}
                                            </div>
                                        )}

                                        {/* Delete API endpoint confirmation */}
                                        {deleteApiEndpointId !== null && (
                                            <div style={{ marginTop: '1rem', padding: '1rem', background: 'rgba(248, 113, 113, 0.06)', border: '1px solid rgba(248, 113, 113, 0.2)', borderRadius: '8px' }}>
                                                <p style={{ marginBottom: '0.75rem', fontSize: '0.9rem' }}>Delete this API endpoint? This cannot be undone.</p>
                                                <div style={{ display: 'flex', gap: '0.5rem', justifyContent: 'flex-end' }}>
                                                    <button onClick={() => setDeleteApiEndpointId(null)} style={{ padding: '0.4rem 0.8rem', background: 'transparent', border: '1px solid var(--border)', borderRadius: '6px', cursor: 'pointer', fontSize: '0.85rem' }}>Cancel</button>
                                                    <button onClick={() => deleteApiEndpoint(deleteApiEndpointId)} style={{ padding: '0.4rem 0.8rem', background: 'var(--danger)', color: 'white', border: 'none', borderRadius: '6px', cursor: 'pointer', fontSize: '0.85rem' }}>Delete</button>
                                                </div>
                                            </div>
                                        )}
                                    </div>
                                )}

                                {/* ===== ISSUES TAB ===== */}
                                {detailTab === 'issues' && (
                                    <div>
                                        {(!explorationDetails.issues || explorationDetails.issues.length === 0) ? (
                                            <div style={{ padding: '2rem', textAlign: 'center', color: 'var(--text-secondary)', background: 'var(--surface-hover)', borderRadius: '8px' }}>
                                                No issues discovered
                                            </div>
                                        ) : (
                                            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                                                {explorationDetails.issues.map(issue => {
                                                    const severityColors: Record<string, string> = { critical: '#dc2626', high: '#ef4444', medium: '#f59e0b', low: '#6b7280' };
                                                    const severityColor = severityColors[issue.severity] || '#6b7280';
                                                    return (
                                                        <div key={issue.id} style={{ background: 'var(--surface-hover)', borderRadius: '8px', border: '1px solid var(--border)', padding: '1rem' }}>
                                                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '0.5rem' }}>
                                                                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                                                                    <span style={{ padding: '0.15rem 0.5rem', borderRadius: '4px', fontSize: '0.7rem', fontWeight: 700, background: `${severityColor}15`, color: severityColor, textTransform: 'uppercase' }}>{issue.severity}</span>
                                                                    <span style={{ padding: '0.15rem 0.5rem', borderRadius: '4px', fontSize: '0.7rem', fontWeight: 600, background: 'var(--surface)', color: 'var(--text-secondary)' }}>{issue.issue_type.replace(/_/g, ' ')}</span>
                                                                </div>
                                                            </div>
                                                            <p style={{ fontSize: '0.9rem', marginBottom: '0.5rem', lineHeight: 1.4 }}>{issue.description}</p>
                                                            {issue.url && (
                                                                <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '0.25rem' }}>
                                                                    <strong>URL:</strong> <a href={issue.url} target="_blank" rel="noopener noreferrer" style={{ color: 'var(--primary)' }}>{issue.url}</a>
                                                                </div>
                                                            )}
                                                            {issue.element && (
                                                                <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '0.25rem' }}>
                                                                    <strong>Element:</strong> {issue.element}
                                                                </div>
                                                            )}
                                                            {issue.evidence && (
                                                                <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                                                                    <strong>Evidence:</strong> {issue.evidence}
                                                                </div>
                                                            )}
                                                        </div>
                                                    );
                                                })}
                                            </div>
                                        )}
                                    </div>
                                )}
                            </>
                        ) : (
                            <div style={{ padding: '2rem', textAlign: 'center', color: 'var(--text-secondary)' }}>
                                Failed to load exploration details
                            </div>
                        )}

                        <div style={{ marginTop: '1.5rem', display: 'flex', justifyContent: 'flex-end' }}>
                            <button className="btn btn-secondary" onClick={() => setDetailModalOpen(false)}>
                                Close
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {/* Flow Details Modal (for Explorer Agent) */}
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
                        width: '100%',
                        maxHeight: '80vh',
                        overflowY: 'auto',
                        padding: '1.5rem',
                        position: 'relative',
                        border: '1px solid var(--border)'
                    }}>
                        <button
                            onClick={() => { setFlowModalOpen(false); setIsEditingFlow(false); setEditingFlow(null); }}
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

                        {!isEditingFlow ? (
                            <>
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
                                        {selectedFlow.exit_point && ` -> Exit: ${selectedFlow.exit_point}`}
                                    </div>
                                )}

                                <div style={{ display: 'flex', gap: '0.75rem', marginTop: '1rem', paddingTop: '1rem', borderTop: '1px solid var(--border)', flexWrap: 'wrap' }}>
                                    <button
                                        onClick={startEditingFlow}
                                        style={{
                                            padding: '0.75rem 1rem',
                                            background: 'transparent',
                                            color: 'var(--primary)',
                                            border: '1px solid var(--primary)',
                                            borderRadius: '8px',
                                            fontSize: '0.9rem',
                                            fontWeight: 500,
                                            cursor: 'pointer',
                                            display: 'flex',
                                            alignItems: 'center',
                                            gap: '0.5rem'
                                        }}
                                    >
                                        <Edit size={16} /> Edit
                                    </button>
                                    <button
                                        onClick={() => setDeleteFlowModalOpen(true)}
                                        style={{
                                            padding: '0.75rem 1rem',
                                            background: 'transparent',
                                            color: 'var(--danger)',
                                            border: '1px solid #ef4444',
                                            borderRadius: '8px',
                                            fontSize: '0.9rem',
                                            fontWeight: 500,
                                            cursor: 'pointer',
                                            display: 'flex',
                                            alignItems: 'center',
                                            gap: '0.5rem'
                                        }}
                                    >
                                        <Trash2 size={16} /> Delete
                                    </button>
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
                                        onClick={() => { setFlowModalOpen(false); setIsEditingFlow(false); setEditingFlow(null); }}
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
                            </>
                        ) : editingFlow && (
                            <>
                                <div style={{ marginBottom: '1rem' }}>
                                    <h4 style={{ fontSize: '0.9rem', fontWeight: 600, marginBottom: '0.5rem' }}>Title</h4>
                                    <input
                                        type="text"
                                        value={editingFlow.title || ''}
                                        onChange={(e) => setEditingFlow({ ...editingFlow, title: e.target.value })}
                                        style={{
                                            width: '100%',
                                            padding: '0.5rem 0.75rem',
                                            background: 'var(--surface-hover)',
                                            border: '1px solid var(--border)',
                                            borderRadius: '8px',
                                            fontSize: '0.9rem',
                                            color: 'var(--text)',
                                            outline: 'none',
                                            boxSizing: 'border-box'
                                        }}
                                    />
                                </div>

                                <div style={{ marginBottom: '1rem' }}>
                                    <h4 style={{ fontSize: '0.9rem', fontWeight: 600, marginBottom: '0.5rem' }}>Pages</h4>
                                    {(editingFlow.pages || []).map((page: string, i: number) => (
                                        <div key={i} style={{ display: 'flex', gap: '0.5rem', marginBottom: '0.5rem' }}>
                                            <input
                                                type="text"
                                                value={page}
                                                onChange={(e) => {
                                                    const newPages = [...(editingFlow.pages || [])];
                                                    newPages[i] = e.target.value;
                                                    setEditingFlow({ ...editingFlow, pages: newPages });
                                                }}
                                                style={{
                                                    flex: 1,
                                                    padding: '0.5rem 0.75rem',
                                                    background: 'var(--surface-hover)',
                                                    border: '1px solid var(--border)',
                                                    borderRadius: '8px',
                                                    fontSize: '0.85rem',
                                                    color: 'var(--text)',
                                                    outline: 'none'
                                                }}
                                            />
                                            <button
                                                onClick={() => {
                                                    const newPages = [...(editingFlow.pages || [])];
                                                    newPages.splice(i, 1);
                                                    setEditingFlow({ ...editingFlow, pages: newPages });
                                                }}
                                                style={{
                                                    padding: '0.5rem',
                                                    background: 'transparent',
                                                    border: '1px solid var(--border)',
                                                    borderRadius: '8px',
                                                    cursor: 'pointer',
                                                    color: 'var(--danger)',
                                                    display: 'flex',
                                                    alignItems: 'center'
                                                }}
                                            >
                                                <X size={14} />
                                            </button>
                                        </div>
                                    ))}
                                    <button
                                        onClick={() => setEditingFlow({ ...editingFlow, pages: [...(editingFlow.pages || []), ''] })}
                                        style={{
                                            padding: '0.4rem 0.75rem',
                                            background: 'transparent',
                                            color: 'var(--primary)',
                                            border: '1px dashed var(--border)',
                                            borderRadius: '8px',
                                            fontSize: '0.8rem',
                                            cursor: 'pointer'
                                        }}
                                    >
                                        + Add Page
                                    </button>
                                </div>

                                <div style={{ marginBottom: '1rem' }}>
                                    <h4 style={{ fontSize: '0.9rem', fontWeight: 600, marginBottom: '0.5rem', color: 'var(--success)' }}>Happy Path</h4>
                                    <textarea
                                        value={editingFlow.happy_path || ''}
                                        onChange={(e) => setEditingFlow({ ...editingFlow, happy_path: e.target.value })}
                                        rows={4}
                                        style={{
                                            width: '100%',
                                            padding: '0.5rem 0.75rem',
                                            background: 'var(--surface-hover)',
                                            border: '1px solid var(--border)',
                                            borderRadius: '8px',
                                            fontSize: '0.9rem',
                                            color: 'var(--text)',
                                            outline: 'none',
                                            resize: 'vertical',
                                            fontFamily: 'inherit',
                                            boxSizing: 'border-box'
                                        }}
                                    />
                                </div>

                                <div style={{ marginBottom: '1rem' }}>
                                    <h4 style={{ fontSize: '0.9rem', fontWeight: 600, marginBottom: '0.5rem', color: 'var(--warning)' }}>Edge Cases</h4>
                                    {(editingFlow.edge_cases || []).map((ec: string, i: number) => (
                                        <div key={i} style={{ display: 'flex', gap: '0.5rem', marginBottom: '0.5rem' }}>
                                            <input
                                                type="text"
                                                value={ec}
                                                onChange={(e) => {
                                                    const newEdgeCases = [...(editingFlow.edge_cases || [])];
                                                    newEdgeCases[i] = e.target.value;
                                                    setEditingFlow({ ...editingFlow, edge_cases: newEdgeCases });
                                                }}
                                                style={{
                                                    flex: 1,
                                                    padding: '0.5rem 0.75rem',
                                                    background: 'var(--surface-hover)',
                                                    border: '1px solid var(--border)',
                                                    borderRadius: '8px',
                                                    fontSize: '0.85rem',
                                                    color: 'var(--text)',
                                                    outline: 'none'
                                                }}
                                            />
                                            <button
                                                onClick={() => {
                                                    const newEdgeCases = [...(editingFlow.edge_cases || [])];
                                                    newEdgeCases.splice(i, 1);
                                                    setEditingFlow({ ...editingFlow, edge_cases: newEdgeCases });
                                                }}
                                                style={{
                                                    padding: '0.5rem',
                                                    background: 'transparent',
                                                    border: '1px solid var(--border)',
                                                    borderRadius: '8px',
                                                    cursor: 'pointer',
                                                    color: 'var(--danger)',
                                                    display: 'flex',
                                                    alignItems: 'center'
                                                }}
                                            >
                                                <X size={14} />
                                            </button>
                                        </div>
                                    ))}
                                    <button
                                        onClick={() => setEditingFlow({ ...editingFlow, edge_cases: [...(editingFlow.edge_cases || []), ''] })}
                                        style={{
                                            padding: '0.4rem 0.75rem',
                                            background: 'transparent',
                                            color: 'var(--primary)',
                                            border: '1px dashed var(--border)',
                                            borderRadius: '8px',
                                            fontSize: '0.8rem',
                                            cursor: 'pointer'
                                        }}
                                    >
                                        + Add Edge Case
                                    </button>
                                </div>

                                <div style={{ marginBottom: '1rem' }}>
                                    <h4 style={{ fontSize: '0.9rem', fontWeight: 600, marginBottom: '0.5rem' }}>Test Ideas</h4>
                                    {(editingFlow.test_ideas || []).map((idea: string, i: number) => (
                                        <div key={i} style={{ display: 'flex', gap: '0.5rem', marginBottom: '0.5rem' }}>
                                            <input
                                                type="text"
                                                value={idea}
                                                onChange={(e) => {
                                                    const newTestIdeas = [...(editingFlow.test_ideas || [])];
                                                    newTestIdeas[i] = e.target.value;
                                                    setEditingFlow({ ...editingFlow, test_ideas: newTestIdeas });
                                                }}
                                                style={{
                                                    flex: 1,
                                                    padding: '0.5rem 0.75rem',
                                                    background: 'var(--surface-hover)',
                                                    border: '1px solid var(--border)',
                                                    borderRadius: '8px',
                                                    fontSize: '0.85rem',
                                                    color: 'var(--text)',
                                                    outline: 'none'
                                                }}
                                            />
                                            <button
                                                onClick={() => {
                                                    const newTestIdeas = [...(editingFlow.test_ideas || [])];
                                                    newTestIdeas.splice(i, 1);
                                                    setEditingFlow({ ...editingFlow, test_ideas: newTestIdeas });
                                                }}
                                                style={{
                                                    padding: '0.5rem',
                                                    background: 'transparent',
                                                    border: '1px solid var(--border)',
                                                    borderRadius: '8px',
                                                    cursor: 'pointer',
                                                    color: 'var(--danger)',
                                                    display: 'flex',
                                                    alignItems: 'center'
                                                }}
                                            >
                                                <X size={14} />
                                            </button>
                                        </div>
                                    ))}
                                    <button
                                        onClick={() => setEditingFlow({ ...editingFlow, test_ideas: [...(editingFlow.test_ideas || []), ''] })}
                                        style={{
                                            padding: '0.4rem 0.75rem',
                                            background: 'transparent',
                                            color: 'var(--primary)',
                                            border: '1px dashed var(--border)',
                                            borderRadius: '8px',
                                            fontSize: '0.8rem',
                                            cursor: 'pointer'
                                        }}
                                    >
                                        + Add Test Idea
                                    </button>
                                </div>

                                <div style={{ display: 'flex', gap: '1rem', marginBottom: '1rem' }}>
                                    <div style={{ flex: 1 }}>
                                        <h4 style={{ fontSize: '0.9rem', fontWeight: 600, marginBottom: '0.5rem' }}>Entry Point</h4>
                                        <input
                                            type="text"
                                            value={editingFlow.entry_point || ''}
                                            onChange={(e) => setEditingFlow({ ...editingFlow, entry_point: e.target.value })}
                                            style={{
                                                width: '100%',
                                                padding: '0.5rem 0.75rem',
                                                background: 'var(--surface-hover)',
                                                border: '1px solid var(--border)',
                                                borderRadius: '8px',
                                                fontSize: '0.85rem',
                                                color: 'var(--text)',
                                                outline: 'none',
                                                boxSizing: 'border-box'
                                            }}
                                        />
                                    </div>
                                    <div style={{ flex: 1 }}>
                                        <h4 style={{ fontSize: '0.9rem', fontWeight: 600, marginBottom: '0.5rem' }}>Exit Point</h4>
                                        <input
                                            type="text"
                                            value={editingFlow.exit_point || ''}
                                            onChange={(e) => setEditingFlow({ ...editingFlow, exit_point: e.target.value })}
                                            style={{
                                                width: '100%',
                                                padding: '0.5rem 0.75rem',
                                                background: 'var(--surface-hover)',
                                                border: '1px solid var(--border)',
                                                borderRadius: '8px',
                                                fontSize: '0.85rem',
                                                color: 'var(--text)',
                                                outline: 'none',
                                                boxSizing: 'border-box'
                                            }}
                                        />
                                    </div>
                                </div>

                                <div style={{ marginBottom: '1rem' }}>
                                    <h4 style={{ fontSize: '0.9rem', fontWeight: 600, marginBottom: '0.5rem' }}>Complexity</h4>
                                    <select
                                        value={editingFlow.complexity || 'medium'}
                                        onChange={(e) => setEditingFlow({ ...editingFlow, complexity: e.target.value })}
                                        style={{
                                            width: '100%',
                                            padding: '0.5rem 0.75rem',
                                            background: 'var(--surface-hover)',
                                            border: '1px solid var(--border)',
                                            borderRadius: '8px',
                                            fontSize: '0.9rem',
                                            color: 'var(--text)',
                                            outline: 'none',
                                            boxSizing: 'border-box'
                                        }}
                                    >
                                        <option value="low">Low</option>
                                        <option value="medium">Medium</option>
                                        <option value="high">High</option>
                                    </select>
                                </div>

                                <div style={{ display: 'flex', gap: '0.75rem', marginTop: '1rem', paddingTop: '1rem', borderTop: '1px solid var(--border)' }}>
                                    <button
                                        onClick={saveFlowEdit}
                                        disabled={isSavingFlow}
                                        style={{
                                            flex: 1,
                                            padding: '0.75rem 1rem',
                                            background: 'var(--primary)',
                                            color: 'white',
                                            border: 'none',
                                            borderRadius: '8px',
                                            fontSize: '0.9rem',
                                            fontWeight: 500,
                                            cursor: isSavingFlow ? 'not-allowed' : 'pointer',
                                            opacity: isSavingFlow ? 0.6 : 1,
                                            display: 'flex',
                                            alignItems: 'center',
                                            justifyContent: 'center',
                                            gap: '0.5rem'
                                        }}
                                    >
                                        {isSavingFlow ? (
                                            <><Loader2 size={16} className="spin" /> Saving...</>
                                        ) : (
                                            <><Save size={16} /> Save Changes</>
                                        )}
                                    </button>
                                    <button
                                        onClick={cancelEditingFlow}
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
                                        Cancel
                                    </button>
                                </div>
                            </>
                        )}
                    </div>
                </div>
            )}

            {/* Delete Flow Confirmation Modal */}
            {deleteFlowModalOpen && selectedFlow && (
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
                        maxWidth: '400px',
                        width: '100%',
                        padding: '1.5rem',
                        border: '1px solid var(--border)'
                    }}>
                        <h3 style={{ margin: '0 0 0.75rem 0', fontSize: '1.1rem', fontWeight: 600 }}>Delete Flow</h3>
                        <p style={{ fontSize: '0.9rem', color: 'var(--text-secondary)', margin: '0 0 1.5rem 0' }}>
                            Are you sure you want to delete &quot;{selectedFlow.title}&quot;? This action cannot be undone.
                        </p>
                        <div style={{ display: 'flex', gap: '0.75rem', justifyContent: 'flex-end' }}>
                            <button
                                onClick={() => setDeleteFlowModalOpen(false)}
                                disabled={isDeletingFlow}
                                style={{
                                    padding: '0.5rem 1rem',
                                    background: 'transparent',
                                    color: 'var(--text-secondary)',
                                    border: '1px solid var(--border)',
                                    borderRadius: '8px',
                                    fontSize: '0.9rem',
                                    cursor: 'pointer'
                                }}
                            >
                                Cancel
                            </button>
                            <button
                                onClick={confirmDeleteFlow}
                                disabled={isDeletingFlow}
                                style={{
                                    padding: '0.5rem 1rem',
                                    background: 'var(--danger)',
                                    color: 'white',
                                    border: 'none',
                                    borderRadius: '8px',
                                    fontSize: '0.9rem',
                                    fontWeight: 500,
                                    cursor: isDeletingFlow ? 'not-allowed' : 'pointer',
                                    opacity: isDeletingFlow ? 0.6 : 1,
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: '0.5rem'
                                }}
                            >
                                {isDeletingFlow ? (
                                    <><Loader2 size={16} className="spin" /> Deleting...</>
                                ) : (
                                    <><Trash2 size={16} /> Delete</>
                                )}
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
                                        <span style={{ background: 'var(--success-muted)', color: 'var(--success)', padding: '2px 8px', borderRadius: '4px', fontSize: '0.75rem' }}>Validated</span>
                                    )}
                                    {generatedSpec.requires_auth && (
                                        <span style={{ background: 'rgba(234, 179, 8, 0.1)', color: 'var(--warning)', padding: '2px 8px', borderRadius: '4px', fontSize: '0.75rem' }}>Auth Required</span>
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
                            <button
                                onClick={splitSpec}
                                disabled={splittingSpec || !generatedSpec.spec_file}
                                style={{
                                    padding: '0.6rem 1rem',
                                    background: splitResult ? 'rgba(16, 185, 129, 0.1)' : 'rgba(168, 85, 247, 0.1)',
                                    color: splitResult ? '#10b981' : '#a855f7',
                                    border: `1px solid ${splitResult ? 'rgba(16, 185, 129, 0.3)' : 'rgba(168, 85, 247, 0.3)'}`,
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
                :global(.spin) {
                    animation: spin 1s linear infinite;
                }
                @keyframes spin {
                    from { transform: rotate(0deg); }
                    to { transform: rotate(360deg); }
                }
                @keyframes pulse-dot {
                    0%, 100% { opacity: 1; transform: scale(1); }
                    50% { opacity: 0.4; transform: scale(0.8); }
                }
            `}</style>
        </PageLayout>
    );
}

// ============ EXPLORER RESULTS COMPONENT ============
function ExplorerResults({
    activeRun,
    timeLimitMinutes,
    fetchFlowDetails,
    loadingFlowDetails,
    handleSynthesize,
    isSynthesizing,
    specResult,
    downloadSpec
}: {
    activeRun: AgentRun;
    timeLimitMinutes: number;
    fetchFlowDetails: (flowId: string) => void;
    loadingFlowDetails: boolean;
    handleSynthesize: () => void;
    isSynthesizing: boolean;
    specResult: SpecResult | null;
    downloadSpec: (content?: string, filename?: string) => void;
}) {
    if (!activeRun.result) {
        return (
            <div style={{ padding: '2rem', background: 'var(--primary-glow)', borderRadius: '12px', color: 'var(--primary)', textAlign: 'center' }}>
                <Loader2 size={32} className="spin" style={{ marginBottom: '1rem' }} />
                <p style={{ fontSize: '1rem', fontWeight: 500 }}>Loading exploration results...</p>
                <p style={{ fontSize: '0.9rem', color: 'var(--text-secondary)', marginTop: '0.5rem' }}>
                    This may take a moment while we compile the findings.
                </p>
            </div>
        );
    }

    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '2rem' }}>
            {/* Main Summary Card */}
            <div style={{ padding: '1.5rem', background: 'linear-gradient(135deg, rgba(59, 130, 246, 0.1) 0%, rgba(147, 51, 234, 0.1) 100%)', borderRadius: '12px', border: '1px solid rgba(59, 130, 246, 0.2)' }}>
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
                        What Was Explored
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
                                <div style={{ fontSize: '2rem', fontWeight: 700, color: activeRun.result.coverage.errors_found > 0 ? '#ef4444' : '#10b981' }}>
                                    {activeRun.result.coverage.errors_found || 0}
                                </div>
                                <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginTop: '0.25rem' }}>
                                    Issues Found
                                </div>
                            </div>
                        )}
                    </div>
                    {activeRun.result.coverage.coverage_score !== undefined && (
                        <div style={{ marginTop: '1rem', padding: '0.75rem', background: activeRun.result.coverage.coverage_score > 0.7 ? 'rgba(16, 185, 129, 0.1)' : 'rgba(245, 158, 11, 0.1)', borderRadius: '8px', border: `1px solid ${activeRun.result.coverage.coverage_score > 0.7 ? 'rgba(16, 185, 129, 0.2)' : 'rgba(245, 158, 11, 0.2)'}` }}>
                            <span style={{ fontSize: '0.85rem', fontWeight: 500 }}>
                                Coverage Score: <strong>{(activeRun.result.coverage.coverage_score * 100).toFixed(0)}%</strong>
                                {activeRun.result.coverage.coverage_score > 0.7 ? ' Good coverage' : ' Consider exploring more'}
                            </span>
                        </div>
                    )}
                </div>
            )}

            {/* Discovered Flows */}
            {activeRun.result.discovered_flow_summaries && activeRun.result.discovered_flow_summaries.length > 0 ? (
                <div>
                    <h4 style={{ fontWeight: 600, fontSize: '1rem', marginBottom: '1rem', color: 'var(--text)' }}>
                        Discovered User Flows ({activeRun.result.total_flows_discovered || activeRun.result.discovered_flow_summaries.length})
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
                                transition: 'all 0.2s var(--ease-smooth)'
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
                                            {flow.entry_point && <span> | Starts: {flow.entry_point}</span>}
                                            {flow.exit_point && <span> | Ends: {flow.exit_point}</span>}
                                        </div>
                                        {flow.pages && flow.pages.length > 0 && (
                                            <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '0.5rem' }}>
                                                <span style={{ fontWeight: 500 }}>Pages:</span> {flow.pages.join(' -> ')}
                                            </div>
                                        )}
                                        {flow.has_edge_cases && (
                                            <div style={{ marginTop: '0.5rem', padding: '0.5rem', background: 'var(--warning-muted)', borderRadius: '6px' }}>
                                                <div style={{ fontSize: '0.75rem', fontWeight: 500, color: 'var(--warning)' }}>
                                                    Includes edge cases
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
            <div style={{ marginTop: '1.5rem', padding: '1.25rem', background: 'linear-gradient(135deg, rgba(16, 185, 129, 0.1) 0%, rgba(59, 130, 246, 0.1) 100%)', borderRadius: '12px', border: '1px solid rgba(52, 211, 153, 0.2)' }}>
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

            {/* Generated Specs */}
            {specResult && specResult.specs && (
                <div>
                    <h4 style={{ fontWeight: 600, marginBottom: '0.5rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                        <FileText size={18} /> Generated Specs ({specResult.total_specs || 0})
                    </h4>
                    <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: '1rem' }}>{specResult.summary}</p>

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
                    <div style={{ marginTop: '0.5rem', background: 'var(--background)', padding: '1rem', borderRadius: '8px', fontSize: '0.85rem', fontFamily: 'monospace', maxHeight: '250px', overflowY: 'auto' }}>
                        {activeRun.result.action_trace.map((action: any, i: number) => (
                            <div key={i} style={{ marginBottom: '0.25rem', color: '#a3a3a3', lineHeight: '1.4' }}>
                                <span style={{ color: 'var(--primary)', fontWeight: 500 }}>[{action.step}]</span> {action.action} {action.target} - {action.outcome}
                                {action.is_new_discovery && <span style={{ color: 'var(--success)', marginLeft: '0.5rem' }}>New Discovery</span>}
                            </div>
                        ))}
                    </div>
                    <p style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginTop: '0.5rem', fontStyle: 'italic' }}>
                        This shows every action the agent took during exploration. "New Discovery" means the agent found something new.
                    </p>
                </details>
            )}
        </div>
    );
}
