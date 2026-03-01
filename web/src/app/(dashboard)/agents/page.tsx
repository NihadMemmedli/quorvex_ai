'use client';
import { useState, useEffect, useRef } from 'react';
import { Bot, FileText, Play, Terminal, ChevronRight, CheckCircle2, AlertTriangle, Loader2, Clock, RotateCcw, Lock, Globe, Settings, Download, List, Sparkles, Zap, ArrowRight, Info, X, RefreshCw, Scissors, ExternalLink } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import { useProject } from '@/contexts/ProjectContext';
import { API_BASE } from '@/lib/api';
import { useJobPoller } from '@/hooks/useJobPoller';
import { PageLayout } from '@/components/ui/page-layout';
import { PageHeader } from '@/components/ui/page-header';

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

export default function AgentsPage() {
    const { currentProject } = useProject();
    const [selectedAgent, setSelectedAgent] = useState<'exploratory' | 'writer'>('exploratory');

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

    useEffect(() => {
        fetchHistory();
        fetchSessions();
        return () => { if (pollInterval.current) clearInterval(pollInterval.current); }
    }, [currentProject?.id]);  // Re-fetch when project changes

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


    const handleRun = async () => {
        if (!url) {
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
            const endpoint = selectedAgent === 'exploratory'
                ? `${API_BASE}/api/agents/exploratory`
                : `${API_BASE}/api/agents/runs`;

            const body = selectedAgent === 'exploratory'
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
                                        <span style={{ fontWeight: 600, fontSize: '0.85rem', color: run.agent_type === 'writer' ? 'var(--primary)' : 'var(--warning)' }}>
                                            {run.agent_type === 'writer' ? 'Writer' : 'Explorer'}
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
                        </div>
                    </div>

                    {/* Configuration Form */}
                    <div className="card" style={{ padding: '1.25rem', flexShrink: 0 }}>
                        <div style={{ marginBottom: '1rem' }}>
                            <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 500, marginBottom: '0.5rem' }}>Target URL</label>
                            <input
                                type="text"
                                placeholder="https://example.com"
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
                                Instructions (Optional)
                            </label>
                            <textarea
                                placeholder={selectedAgent === 'exploratory' ? "Focus on checkout flow, test edge cases..." : "Generate spec for login page..."}
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
                            {activeRun ? `Result: ${activeRun.config?.url || 'Unknown'}` : 'Agent Output'}
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
                        ) : activeRun.status === 'running' ? (
                            <div style={{ height: '100%', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', color: 'var(--text-secondary)' }}>
                                <Loader2 size={48} className="spin" style={{ marginBottom: '1rem', color: 'var(--primary)' }} />
                                <p>Agent is working...</p>
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
