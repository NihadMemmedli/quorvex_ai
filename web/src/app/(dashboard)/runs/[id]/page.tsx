'use client';
import { useState, useEffect } from 'react';
import {
    ArrowLeft, CheckCircle, Copy, Check, Image as ImageIcon, Video as VideoIcon,
    ExternalLink, Code, Layout, FileText, Eye, Globe, Chrome, Compass, Clock, XCircle, Square, Monitor,
    Bug, Loader2, X, Edit3
} from 'lucide-react';
import Link from 'next/link';
import { useParams } from 'next/navigation';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { vscDarkPlus } from 'react-syntax-highlighter/dist/esm/styles/prism';
import { useProject } from '@/contexts/ProjectContext';
import { LiveBrowserView } from '@/components/LiveBrowserView';
import { API_BASE } from '@/lib/api';
import { PageLayout } from '@/components/ui/page-layout';
import { PageHeader } from '@/components/ui/page-header';

interface Artifact {
    name: string;
    path: string;
    type: 'image' | 'video';
}

interface VisualDiff {
    name: string;
    diff?: Artifact;
    expected?: Artifact;
    actual?: Artifact;
}

export default function RunDetailPage() {
    const params = useParams();
    const id = params?.id as string;
    const { currentProject } = useProject();
    const [data, setData] = useState<any>(null);
    const [loading, setLoading] = useState(true);
    const [copied, setCopied] = useState(false);
    const [streamingLog, setStreamingLog] = useState<string>('');
    const [isStreaming, setIsStreaming] = useState(false);
    const [viewMode, setViewMode] = useState<'browser' | 'log'>('log'); // Default to log (VNC may not be available)
    const [vncAvailable, setVncAvailable] = useState<boolean | null>(null);

    // Jira bug report state
    const [jiraIssue, setJiraIssue] = useState<{ exists: boolean; jira_issue_key?: string; jira_url?: string; summary?: string } | null>(null);
    const [bugReportLoading, setBugReportLoading] = useState(false);
    const [bugReportModal, setBugReportModal] = useState(false);
    const [bugReport, setBugReport] = useState<any>(null);
    const [bugReportTitle, setBugReportTitle] = useState('');
    const [bugReportDescription, setBugReportDescription] = useState('');
    const [bugReportPriority, setBugReportPriority] = useState('P3');
    const [bugReportLabels, setBugReportLabels] = useState<string[]>([]);
    const [creatingIssue, setCreatingIssue] = useState(false);
    const [jiraConfig, setJiraConfig] = useState<{ configured: boolean; project_key?: string; issue_type_id?: string } | null>(null);

    // Check if VNC is available (runs once on mount)
    useEffect(() => {
        const vncHost = typeof window !== 'undefined' ? window.location.hostname : 'localhost';
        const vncUrl = `ws://${vncHost}:6080/websockify`;

        const checkVnc = async () => {
            try {
                const ws = new WebSocket(vncUrl);
                const available = await new Promise<boolean>((resolve) => {
                    const timeout = setTimeout(() => {
                        ws.close();
                        resolve(false);
                    }, 2000);

                    ws.onopen = () => {
                        clearTimeout(timeout);
                        ws.close();
                        resolve(true);
                    };

                    ws.onerror = () => {
                        clearTimeout(timeout);
                        resolve(false);
                    };
                });
                setVncAvailable(available);
                // If VNC is available, switch to browser view
                if (available) {
                    setViewMode('browser');
                }
            } catch {
                setVncAvailable(false);
            }
        };

        checkVnc();
    }, []);

    // Build project query param for API calls
    const projectParam = currentProject?.id ? `?project_id=${encodeURIComponent(currentProject.id)}` : '';

    const fetchRunData = () => {
        fetch(`${API_BASE}/runs/${id}${projectParam}`)
            .then(res => res.json())
            .then(d => {
                setData(d);
                setLoading(false);
            })
            .catch(err => {
                console.error(err);
                setLoading(false);
            });
    };

    useEffect(() => {
        if (!id) return;
        fetchRunData();
    }, [id, projectParam]);

    // Check if Jira issue exists for this run + load Jira config
    useEffect(() => {
        if (!id || !currentProject?.id) return;
        const pid = encodeURIComponent(currentProject.id);

        fetch(`${API_BASE}/jira/${pid}/issues/${id}`)
            .then(res => res.json())
            .then(d => setJiraIssue(d))
            .catch(() => {});

        fetch(`${API_BASE}/jira/${pid}/config`)
            .then(res => res.json())
            .then(d => setJiraConfig(d))
            .catch(() => {});
    }, [id, currentProject?.id]);

    // Set up live log streaming for running tests
    useEffect(() => {
        if (!data || !id) return;

        const isRunning = data.effective_status === 'running' ||
            data.effective_status === 'in_progress' ||
            data.run?.status === 'running' ||
            data.run?.status === 'in_progress';

        if (!isRunning) {
            setIsStreaming(false);
            return;
        }

        setIsStreaming(true);
        setStreamingLog(''); // Reset streaming log

        const eventSource = new EventSource(`${API_BASE}/runs/${id}/log/stream`);

        eventSource.onmessage = (event) => {
            try {
                const eventData = JSON.parse(event.data);

                if (eventData.log) {
                    setStreamingLog(prev => prev + eventData.log);
                }

                if (eventData.status === 'complete') {
                    setIsStreaming(false);
                    eventSource.close();
                    // Refresh data to get final state
                    fetchRunData();
                }

                if (eventData.status === 'error' || eventData.status === 'timeout') {
                    setIsStreaming(false);
                    eventSource.close();
                }
            } catch (e) {
                console.error('Error parsing SSE data:', e);
            }
        };

        eventSource.onerror = (err) => {
            console.error('EventSource error:', err);
            setIsStreaming(false);
            eventSource.close();
        };

        return () => {
            eventSource.close();
        };
    }, [data?.effective_status, data?.run?.status, id]);

    if (loading) return (
        <PageLayout tier="standard">
            <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: '60vh' }}>
                <div className="loading-spinner"></div>
            </div>
        </PageLayout>
    );
    if (!data) return <PageLayout tier="standard"><div style={{ paddingTop: '2rem' }}>Run not found.</div></PageLayout>;

    // Process Artifacts for Visual Regression
    const artifacts: Artifact[] = data.artifacts || [];
    const visualDiffs: VisualDiff[] = [];
    const standardArtifacts: Artifact[] = [];

    // Group related screenshots
    const processedIndices = new Set<number>();

    artifacts.forEach((art, index) => {
        if (processedIndices.has(index)) return;

        if (art.name.endsWith('-diff.png')) {
            const baseName = art.name.replace('-diff.png', '');
            const expected = artifacts.find(a => a.name === `${baseName}-expected.png`);
            const actual = artifacts.find(a => a.name === `${baseName}-actual.png`);

            visualDiffs.push({
                name: baseName,
                diff: art,
                expected,
                actual
            });

            processedIndices.add(index);
            if (expected) processedIndices.add(artifacts.indexOf(expected));
            if (actual) processedIndices.add(artifacts.indexOf(actual));
        } else if (!art.name.match(/-(expected|actual)\.png$/)) {
            // Only add if not part of a diff set (handled above)
            standardArtifacts.push(art);
        }
    });

    // Add orphan actual/expected if diff is missing (edge case)
    artifacts.forEach((art, index) => {
        if (!processedIndices.has(index) && !standardArtifacts.includes(art)) {
            standardArtifacts.push(art);
        }
    });

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

    const handleStop = async () => {
        if (!confirm('Are you sure you want to stop this run?')) return;

        try {
            const res = await fetch(`${API_BASE}/runs/${id}/stop${projectParam}`, { method: 'POST' });
            const json = await res.json();
            if (json.status === 'stopped') {
                // Refresh data
                const res2 = await fetch(`${API_BASE}/runs/${id}${projectParam}`);
                const d = await res2.json();
                setData(d);
            } else {
                alert('Failed to stop run: ' + (json.message || 'Unknown error'));
            }
        } catch (e) {
            console.error(e);
            alert('Error stopping run');
        }
    };

    const handleGenerateBugReport = async () => {
        if (!currentProject?.id) return;
        setBugReportLoading(true);

        try {
            const pid = encodeURIComponent(currentProject.id);
            const res = await fetch(`${API_BASE}/jira/${pid}/generate-bug-report/${id}`, { method: 'POST' });
            const { job_id } = await res.json();

            // Poll for completion
            const poll = async () => {
                const pollRes = await fetch(`${API_BASE}/jira/${pid}/bug-report-jobs/${job_id}`);
                const pollData = await pollRes.json();

                if (pollData.status === 'completed') {
                    const report = pollData.result;
                    setBugReport(report);
                    setBugReportTitle(report.title || '');

                    // Build description from structured data
                    const descParts = [];
                    if (report.description) descParts.push(report.description);
                    if (report.steps_to_reproduce?.length) {
                        descParts.push('\n*Steps to Reproduce:*\n' + report.steps_to_reproduce.map((s: string, i: number) => `${i + 1}. ${s}`).join('\n'));
                    }
                    if (report.expected_behavior) descParts.push('\n*Expected:*\n' + report.expected_behavior);
                    if (report.actual_behavior) descParts.push('\n*Actual:*\n' + report.actual_behavior);
                    if (report.error_details?.error_message) {
                        descParts.push('\n*Error:*\n{noformat}' + report.error_details.error_message + '{noformat}');
                    }
                    if (report.environment) {
                        descParts.push('\n*Environment:*\n- Browser: ' + (report.environment.browser || 'chromium') + '\n- URL: ' + (report.environment.url || '') + '\n- Spec: ' + (report.environment.test_spec || ''));
                    }
                    setBugReportDescription(descParts.join('\n'));
                    setBugReportPriority(report.priority || 'P3');
                    setBugReportLabels(report.suggested_labels || ['bug', 'automated-test']);
                    setBugReportLoading(false);
                    setBugReportModal(true);
                } else if (pollData.status === 'failed') {
                    setBugReportLoading(false);
                    alert('Bug report generation failed: ' + (pollData.error || 'Unknown error'));
                } else {
                    setTimeout(poll, 2000);
                }
            };

            setTimeout(poll, 2000);
        } catch (e) {
            setBugReportLoading(false);
            alert('Failed to start bug report generation');
        }
    };

    const handleCreateJiraIssue = async () => {
        if (!currentProject?.id || !jiraConfig?.project_key || !jiraConfig?.issue_type_id) return;
        setCreatingIssue(true);

        try {
            const pid = encodeURIComponent(currentProject.id);
            // Map priority name for Jira (P1->Highest, P2->High, P3->Medium, P4->Low)
            const priorityMap: Record<string, string> = { P1: 'Highest', P2: 'High', P3: 'Medium', P4: 'Low' };

            const res = await fetch(`${API_BASE}/jira/${pid}/create-issue`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    run_id: id,
                    title: bugReportTitle,
                    description: bugReportDescription,
                    project_key: jiraConfig.project_key,
                    issue_type_id: jiraConfig.issue_type_id,
                    priority_name: priorityMap[bugReportPriority] || 'Medium',
                    labels: bugReportLabels,
                    attach_screenshots: true,
                }),
            });

            if (res.ok) {
                const result = await res.json();
                setJiraIssue({
                    exists: true,
                    jira_issue_key: result.issue_key,
                    jira_url: result.issue_url,
                    summary: bugReportTitle,
                });
                setBugReportModal(false);
            } else {
                const err = await res.json();
                alert('Failed to create Jira issue: ' + (err.detail || 'Unknown error'));
            }
        } catch (e) {
            alert('Error creating Jira issue');
        } finally {
            setCreatingIssue(false);
        }
    };


    return (
        <PageLayout tier="standard">
            <PageHeader
                title={data.plan?.testName || 'Test Run'}
                subtitle={`Run ID: ${formatRunId(id)}`}
                breadcrumb={
                    <Link href="/runs" className="btn btn-ghost" style={{ display: 'inline-flex', alignItems: 'center', gap: '0.5rem', paddingLeft: 0 }}>
                        <ArrowLeft size={16} /> Back to Runs
                    </Link>
                }
                actions={
                    <div style={{ display: 'flex', gap: '1rem', alignItems: 'center' }}>
                        {(data.run?.status === 'running' || data.run?.status === 'pending') && (
                            <button
                                onClick={handleStop}
                                className="btn btn-danger"
                                style={{ display: 'inline-flex', alignItems: 'center', gap: '0.5rem', fontSize: '0.9rem', padding: '0.5rem 1rem' }}
                            >
                                <Square size={16} fill="currentColor" /> Stop Run
                            </button>
                        )}
                        {data.effective_status === 'failed' && jiraConfig?.configured && (
                            jiraIssue?.exists ? (
                                <a
                                    href={jiraIssue.jira_url}
                                    target="_blank"
                                    rel="noreferrer"
                                    className="btn btn-secondary"
                                    style={{ display: 'inline-flex', alignItems: 'center', gap: '0.5rem', fontSize: '0.9rem', padding: '0.5rem 1rem' }}
                                >
                                    <ExternalLink size={16} /> {jiraIssue.jira_issue_key}
                                </a>
                            ) : (
                                <button
                                    onClick={handleGenerateBugReport}
                                    disabled={bugReportLoading}
                                    className="btn btn-secondary"
                                    style={{ display: 'inline-flex', alignItems: 'center', gap: '0.5rem', fontSize: '0.9rem', padding: '0.5rem 1rem' }}
                                >
                                    {bugReportLoading ? (
                                        <><Loader2 size={16} style={{ animation: 'spin 1s linear infinite' }} /> Generating...</>
                                    ) : (
                                        <><Bug size={16} /> Create Bug Report</>
                                    )}
                                </button>
                            )
                        )}
                        <div className={`badge badge-${data.effective_status === 'passed' ? 'success' : data.effective_status === 'failed' ? 'danger' : 'secondary'}`} style={{ fontSize: '1rem', padding: '0.5rem 1rem' }}>
                            {data.effective_status === 'passed' ? 'Passed' :
                             data.effective_status === 'failed' ? 'Failed' :
                             data.effective_status || 'Unknown Status'}
                        </div>
                    </div>
                }
            />

            <header className="animate-in stagger-1" style={{ marginBottom: '3rem' }}>

                {/* Run Metadata Bar */}
                <div style={{
                    display: 'flex',
                    gap: '1.5rem',
                    flexWrap: 'wrap',
                    padding: '1rem 1.5rem',
                    background: 'rgba(255,255,255,0.03)',
                    borderRadius: 'var(--radius)',
                    border: '1px solid var(--border)'
                }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                        <Clock size={16} color="var(--text-secondary)" />
                        <span style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>Duration:</span>
                        <span style={{ fontWeight: 600 }}>{data.run?.duration ? `${data.run.duration.toFixed(2)}s` : 'N/A'}</span>
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                        {(() => {
                            const browser = data.run?.browser;
                            switch (browser) {
                                case 'firefox':
                                    return <Globe size={16} color="#FF7139" />;
                                case 'webkit':
                                    return <Compass size={16} color="#007AFF" />;
                                case 'chromium':
                                default:
                                    return <Chrome size={16} color="#4285F4" />;
                            }
                        })()}
                        <span style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>Browser:</span>
                        <span style={{ fontWeight: 600, textTransform: 'capitalize' }}>{data.run?.browser || 'chromium'}</span>
                    </div>
                    {data.validation?.status && (
                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                            {data.validation.status === 'success' ? <CheckCircle size={16} color="var(--success)" /> : <XCircle size={16} color="var(--danger)" />}
                            <span style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>Validation:</span>
                            <span style={{ fontWeight: 600, color: data.validation.status === 'success' ? 'var(--success)' : 'inherit' }}>
                                {data.validation.status === 'success' ? 'Passed' : data.validation.status}
                            </span>
                        </div>
                    )}
                    {data.report_url && (
                        <div style={{ marginLeft: 'auto' }}>
                            <a
                                href={`${API_BASE}${data.report_url}`}
                                target="_blank"
                                rel="noreferrer"
                                className="btn btn-secondary"
                                style={{ fontSize: '0.85rem', padding: '0.4rem 0.9rem', height: 'auto', display: 'inline-flex', gap: '0.5rem', alignItems: 'center' }}
                            >
                                <ExternalLink size={14} /> View HTML Report
                            </a>
                        </div>
                    )}
                </div>

                {/* Error Message Banner */}
                {(data.effective_status === 'error' || data.effective_status === 'failed' || data.effective_status === 'stopped') && (data.run?.error_message || data.error_message) && (
                    <div style={{
                        marginTop: '1.5rem',
                        padding: '1rem 1.25rem',
                        background: data.effective_status === 'stopped' ? 'rgba(251, 191, 36, 0.08)' : 'rgba(239, 68, 68, 0.08)',
                        border: `1px solid ${data.effective_status === 'stopped' ? 'rgba(251, 191, 36, 0.3)' : 'rgba(239, 68, 68, 0.3)'}`,
                        borderRadius: 'var(--radius)',
                        display: 'flex',
                        alignItems: 'flex-start',
                        gap: '0.75rem'
                    }}>
                        <XCircle size={20} style={{ color: data.effective_status === 'stopped' ? 'var(--warning)' : 'var(--danger)', flexShrink: 0, marginTop: '2px' }} />
                        <div style={{ flex: 1 }}>
                            <div style={{ fontWeight: 600, marginBottom: '0.25rem', color: data.effective_status === 'stopped' ? 'var(--warning)' : 'var(--danger)' }}>
                                {data.effective_status === 'error' ? 'Pipeline Error' : data.effective_status === 'failed' ? 'Test Failed' : 'Run Stopped'}
                            </div>
                            <div style={{
                                fontFamily: 'var(--font-mono)',
                                fontSize: '0.85rem',
                                lineHeight: 1.5,
                                color: 'var(--text)',
                                whiteSpace: 'pre-wrap',
                                wordBreak: 'break-word'
                            }}>
                                {data.run?.error_message || data.error_message}
                            </div>
                        </div>
                    </div>
                )}

                {data.run?.notes?.some((note: string) => note.includes('Reused existing code')) && (
                    <div style={{
                        marginTop: '1.5rem',
                        padding: '1rem',
                        background: 'var(--success-muted)',
                        border: '1px solid rgba(52, 211, 153, 0.3)',
                        borderRadius: 'var(--radius)',
                        color: 'var(--success)',
                        display: 'flex',
                        alignItems: 'center',
                        gap: '0.75rem'
                    }}>
                        <CheckCircle size={20} />
                        <div>
                            <strong>Smart Run Active:</strong> Reused existing test code.
                        </div>
                    </div>
                )}
            </header>

            <div className="animate-in stagger-2" style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>

                    {/* Visual Regression Section */}
                    {visualDiffs.length > 0 && (
                        <section className="card">
                            <h2 style={{ fontSize: '1.25rem', marginBottom: '1.5rem', display: 'flex', alignItems: 'center', gap: '0.75rem', fontWeight: 600 }}>
                                <Eye size={20} className="text-primary" /> Visual Regression Failures
                            </h2>
                            <div style={{ display: 'flex', flexDirection: 'column', gap: '2rem' }}>
                                {visualDiffs.map((diff, i) => (
                                    <div key={i} style={{ background: 'var(--background)', padding: '1rem', borderRadius: 'var(--radius)' }}>
                                        <h3 style={{ fontSize: '1rem', marginBottom: '1rem', fontWeight: 600 }}>{diff.name}</h3>
                                        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '1rem' }}>
                                            {diff.expected && (
                                                <div>
                                                    <div style={{ marginBottom: '0.5rem', fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Expected</div>
                                                    <a href={`${API_BASE}${diff.expected.path}`} target="_blank" rel="noreferrer">
                                                        <img src={`${API_BASE}${diff.expected.path}`} style={{ width: '100%', borderRadius: '4px', border: '1px solid var(--border)' }} />
                                                    </a>
                                                </div>
                                            )}
                                            {diff.actual && (
                                                <div>
                                                    <div style={{ marginBottom: '0.5rem', fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Actual</div>
                                                    <a href={`${API_BASE}${diff.actual.path}`} target="_blank" rel="noreferrer">
                                                        <img src={`${API_BASE}${diff.actual.path}`} style={{ width: '100%', borderRadius: '4px', border: '1px solid var(--border)' }} />
                                                    </a>
                                                </div>
                                            )}
                                            {diff.diff && (
                                                <div>
                                                    <div style={{ marginBottom: '0.5rem', fontSize: '0.8rem', color: 'var(--danger)' }}>Diff</div>
                                                    <a href={`${API_BASE}${diff.diff.path}`} target="_blank" rel="noreferrer">
                                                        <img src={`${API_BASE}${diff.diff.path}`} style={{ width: '100%', borderRadius: '4px', border: '1px solid var(--danger)' }} />
                                                    </a>
                                                </div>
                                            )}
                                        </div>
                                    </div>
                                ))}
                            </div>
                        </section>
                    )}

                    <section className="card">
                        <h2 style={{ fontSize: '1.25rem', marginBottom: '1.5rem', display: 'flex', alignItems: 'center', gap: '0.75rem', fontWeight: 600 }}>
                            <Layout size={20} /> Execution Plan
                        </h2>
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                            {data.plan?.steps?.map((step: any, i: number) => (
                                <div key={i} style={{
                                    padding: '1rem',
                                    background: 'var(--surface-hover)',
                                    borderRadius: 'var(--radius)',
                                    borderLeft: '4px solid var(--primary)'
                                }}>
                                    <div style={{ fontWeight: 600, marginBottom: '0.25rem' }}>Step {i + 1}</div>
                                    <div style={{ lineHeight: 1.5 }}>{step.description}</div>
                                    <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginTop: '0.5rem', fontFamily: 'monospace', background: 'rgba(0,0,0,0.2)', padding: '0.25rem', display: 'inline-block', borderRadius: '4px' }}>
                                        {step.action} {step.params?.selector || step.params?.url || ''}
                                    </div>
                                </div>
                            ))}
                        </div>
                    </section>

                    <section className="card">
                        <h2 style={{ fontSize: '1.25rem', marginBottom: '1.5rem', display: 'flex', alignItems: 'center', gap: '0.75rem', fontWeight: 600 }}>
                            <Code size={20} /> Generated Code
                        </h2>
                        {data.export?.testFilePath && (
                            <div>
                                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
                                    <p style={{ margin: 0, fontSize: '0.9rem' }}>File: <code style={{ background: 'var(--surface-hover)', padding: '0.2rem 0.5rem', borderRadius: '4px', fontFamily: 'var(--font-mono)' }}>{data.export.testFilePath}</code></p>
                                    <button
                                        className="btn btn-secondary"
                                        onClick={() => {
                                            if (data.generated_code) {
                                                navigator.clipboard.writeText(data.generated_code);
                                                setCopied(true);
                                                setTimeout(() => setCopied(false), 2000);
                                            }
                                        }}
                                        style={{ fontSize: '0.8rem', padding: '0.35rem 0.75rem', height: 'auto' }}
                                    >
                                        {copied ? <><Check size={14} /> Copied</> : <><Copy size={14} /> Copy</>}
                                    </button>
                                </div>
                                <div style={{
                                    borderRadius: 'var(--radius)',
                                    overflow: 'hidden',
                                    border: '1px solid var(--border)'
                                }}>
                                    <SyntaxHighlighter
                                        language="typescript"
                                        style={vscDarkPlus}
                                        customStyle={{ margin: 0, padding: '1.5rem', fontSize: '0.9rem', background: 'var(--background)' }}
                                        showLineNumbers={true}
                                    >
                                        {data.generated_code || '// Code content not available'}
                                    </SyntaxHighlighter>
                                </div>
                            </div>
                        )}
                    </section>

                    {/* Live View / Execution Log Section */}
                    <section className="card">
                        {/* Section Header with View Toggle */}
                        <div style={{
                            display: 'flex',
                            justifyContent: 'space-between',
                            alignItems: 'center',
                            marginBottom: '1rem'
                        }}>
                            <h2 style={{ fontSize: '1.25rem', display: 'flex', alignItems: 'center', gap: '0.75rem', fontWeight: 600, margin: 0 }}>
                                {viewMode === 'browser' ? (
                                    <><Monitor size={20} /> Live Browser View</>
                                ) : (
                                    <><FileText size={20} /> Execution Log</>
                                )}
                                {isStreaming && (
                                    <span style={{
                                        display: 'inline-flex',
                                        alignItems: 'center',
                                        gap: '0.5rem',
                                        padding: '0.25rem 0.75rem',
                                        borderRadius: '999px',
                                        fontSize: '0.75rem',
                                        fontWeight: 600,
                                        background: 'var(--primary-glow)',
                                        color: 'var(--primary)',
                                        border: '1px solid rgba(59, 130, 246, 0.25)'
                                    }}>
                                        <span style={{
                                            width: '8px',
                                            height: '8px',
                                            borderRadius: '50%',
                                            background: 'var(--primary)',
                                            animation: 'pulse 1s ease-in-out infinite'
                                        }} />
                                        Live
                                    </span>
                                )}
                            </h2>

                            {/* View Mode Toggle */}
                            <div style={{
                                display: 'flex',
                                gap: '0.25rem',
                                background: 'var(--surface-hover)',
                                padding: '0.25rem',
                                borderRadius: 'var(--radius)'
                            }}>
                                <button
                                    onClick={() => setViewMode('browser')}
                                    title={vncAvailable === false ? 'VNC not available (Docker production only)' : 'Live browser view'}
                                    style={{
                                        padding: '0.4rem 0.75rem',
                                        borderRadius: 'calc(var(--radius) - 2px)',
                                        border: 'none',
                                        background: viewMode === 'browser' ? 'var(--primary)' : 'transparent',
                                        color: viewMode === 'browser' ? 'white' : 'var(--text-secondary)',
                                        fontSize: '0.8rem',
                                        fontWeight: 500,
                                        cursor: 'pointer',
                                        display: 'flex',
                                        alignItems: 'center',
                                        gap: '0.4rem',
                                        transition: 'all 0.15s ease',
                                        opacity: vncAvailable === false ? 0.6 : 1
                                    }}
                                >
                                    <Monitor size={14} /> Browser
                                    {vncAvailable === false && (
                                        <span style={{
                                            fontSize: '0.65rem',
                                            padding: '0.1rem 0.3rem',
                                            background: 'rgba(251, 191, 36, 0.2)',
                                            color: 'var(--warning)',
                                            borderRadius: '3px',
                                            marginLeft: '0.2rem'
                                        }}>
                                            N/A
                                        </span>
                                    )}
                                </button>
                                <button
                                    onClick={() => setViewMode('log')}
                                    style={{
                                        padding: '0.4rem 0.75rem',
                                        borderRadius: 'calc(var(--radius) - 2px)',
                                        border: 'none',
                                        background: viewMode === 'log' ? 'var(--primary)' : 'transparent',
                                        color: viewMode === 'log' ? 'white' : 'var(--text-secondary)',
                                        fontSize: '0.8rem',
                                        fontWeight: 500,
                                        cursor: 'pointer',
                                        display: 'flex',
                                        alignItems: 'center',
                                        gap: '0.4rem',
                                        transition: 'all 0.15s ease'
                                    }}
                                >
                                    <FileText size={14} /> Log
                                </button>
                            </div>
                        </div>

                        {/* Live Browser View */}
                        {viewMode === 'browser' && (
                            <LiveBrowserView
                                runId={id}
                                isActive={isStreaming || data.effective_status === 'running' || data.effective_status === 'in_progress'}
                            />
                        )}

                        {/* Execution Log */}
                        {viewMode === 'log' && (
                            <div
                                style={{
                                    background: 'var(--background)',
                                    padding: '1rem',
                                    borderRadius: 'var(--radius)',
                                    maxHeight: '500px',
                                    overflow: 'auto',
                                    fontFamily: 'monospace',
                                    fontSize: '0.85rem',
                                    whiteSpace: 'pre-wrap',
                                    color: 'var(--text)',
                                    border: `1px solid ${isStreaming ? 'var(--primary)' : 'var(--border)'}`,
                                    transition: 'border-color 0.3s'
                                }}
                                ref={(el) => {
                                    // Auto-scroll to bottom when streaming
                                    if (el && isStreaming) {
                                        el.scrollTop = el.scrollHeight;
                                    }
                                }}
                            >
                                {isStreaming ? (streamingLog || 'Waiting for output...') : (data.log || 'No logs available.')}
                            </div>
                        )}

                        <style jsx>{`
                            @keyframes pulse {
                                0%, 100% { opacity: 1; }
                                50% { opacity: 0.5; }
                            }
                        `}</style>
                    </section>

                    {standardArtifacts.length > 0 && (
                        <section className="card">
                            <h2 style={{ fontSize: '1.25rem', marginBottom: '1.5rem', display: 'flex', alignItems: 'center', gap: '0.75rem', fontWeight: 600 }}>
                                <ImageIcon size={20} /> Other Artifacts
                            </h2>
                            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: '1rem' }}>
                                {standardArtifacts.map((art: any, i: number) => (
                                    <div key={i} style={{ borderRadius: 'var(--radius)', overflow: 'hidden', background: 'var(--background)', border: '1px solid var(--border)' }}>
                                        {art.type === 'image' ? (
                                            <a href={`${API_BASE}${art.path}`} target="_blank" rel="noreferrer">
                                                <img
                                                    src={`${API_BASE}${art.path}`}
                                                    alt={art.name}
                                                    style={{ width: '100%', aspectRatio: '16/9', objectFit: 'cover' }}
                                                />
                                            </a>
                                        ) : (
                                            <video
                                                controls
                                                src={`${API_BASE}${art.path}`}
                                                style={{ width: '100%' }}
                                            />
                                        )}
                                        <div style={{ padding: '0.5rem', fontSize: '0.8rem', color: 'var(--text-secondary)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                                            {art.name}
                                        </div>
                                    </div>
                                ))}
                            </div>
                        </section>
                    )}

                </div>

            </div>

            {/* Bug Report Modal */}
            {bugReportModal && (
                <div style={{
                    position: 'fixed',
                    top: 0,
                    left: 0,
                    right: 0,
                    bottom: 0,
                    background: 'rgba(0, 0, 0, 0.7)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    zIndex: 1000,
                    padding: '2rem',
                }}>
                    <div style={{
                        background: 'var(--surface)',
                        borderRadius: 'var(--radius)',
                        border: '1px solid var(--border)',
                        maxWidth: '700px',
                        width: '100%',
                        maxHeight: '90vh',
                        overflow: 'auto',
                        padding: '2rem',
                    }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.5rem' }}>
                            <h2 style={{ fontSize: '1.5rem', fontWeight: 700, display: 'flex', alignItems: 'center', gap: '0.5rem', margin: 0 }}>
                                <Bug size={24} /> Create Bug Report
                            </h2>
                            <button
                                onClick={() => setBugReportModal(false)}
                                style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-secondary)', padding: '0.25rem' }}
                            >
                                <X size={20} />
                            </button>
                        </div>

                        <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
                            {/* Title */}
                            <div className="form-group">
                                <label className="label">Title</label>
                                <input
                                    type="text"
                                    value={bugReportTitle}
                                    onChange={e => setBugReportTitle(e.target.value)}
                                    className="input"
                                    style={{ width: '100%' }}
                                />
                            </div>

                            {/* Description */}
                            <div className="form-group">
                                <label className="label">Description</label>
                                <textarea
                                    value={bugReportDescription}
                                    onChange={e => setBugReportDescription(e.target.value)}
                                    style={{
                                        width: '100%',
                                        minHeight: '250px',
                                        padding: '0.75rem',
                                        borderRadius: 'var(--radius)',
                                        border: '1px solid var(--border)',
                                        background: 'var(--surface-hover)',
                                        color: 'var(--text-primary)',
                                        fontFamily: 'var(--font-mono)',
                                        fontSize: '0.875rem',
                                        resize: 'vertical',
                                    }}
                                />
                            </div>

                            {/* Priority */}
                            <div className="form-group">
                                <label className="label">Priority</label>
                                <select
                                    value={bugReportPriority}
                                    onChange={e => setBugReportPriority(e.target.value)}
                                    className="input"
                                    style={{ width: '200px' }}
                                >
                                    <option value="P1">P1 - Blocker</option>
                                    <option value="P2">P2 - Critical</option>
                                    <option value="P3">P3 - Major</option>
                                    <option value="P4">P4 - Minor</option>
                                </select>
                            </div>

                            {/* Labels */}
                            <div className="form-group">
                                <label className="label">Labels</label>
                                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem' }}>
                                    {bugReportLabels.map((label, i) => (
                                        <span key={i} style={{
                                            padding: '0.25rem 0.75rem',
                                            borderRadius: '999px',
                                            background: 'var(--primary-glow)',
                                            color: 'var(--primary)',
                                            fontSize: '0.8rem',
                                            fontWeight: 500,
                                            display: 'inline-flex',
                                            alignItems: 'center',
                                            gap: '0.4rem',
                                        }}>
                                            {label}
                                            <button
                                                onClick={() => setBugReportLabels(prev => prev.filter((_, j) => j !== i))}
                                                style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--primary)', padding: 0, lineHeight: 1 }}
                                            >
                                                <X size={12} />
                                            </button>
                                        </span>
                                    ))}
                                </div>
                            </div>

                            {/* Screenshots note */}
                            <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', margin: 0 }}>
                                Screenshots from the test run will be automatically attached to the Jira issue.
                            </p>

                            {/* Actions */}
                            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '0.75rem', paddingTop: '1rem', borderTop: '1px solid var(--border)' }}>
                                <button
                                    onClick={() => setBugReportModal(false)}
                                    className="btn"
                                    style={{ background: 'transparent', border: '1px solid var(--border)' }}
                                >
                                    Cancel
                                </button>
                                <button
                                    onClick={handleCreateJiraIssue}
                                    disabled={creatingIssue || !bugReportTitle || !jiraConfig?.project_key || !jiraConfig?.issue_type_id}
                                    className="btn btn-primary"
                                    style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', opacity: creatingIssue ? 0.7 : 1 }}
                                >
                                    {creatingIssue ? (
                                        <><Loader2 size={16} style={{ animation: 'spin 1s linear infinite' }} /> Creating...</>
                                    ) : (
                                        <><ExternalLink size={16} /> Create in Jira</>
                                    )}
                                </button>
                            </div>

                            {!jiraConfig?.project_key && (
                                <p style={{ fontSize: '0.85rem', color: 'var(--danger)', margin: 0 }}>
                                    Please configure a default Jira project in Settings first.
                                </p>
                            )}
                        </div>

                        <style jsx>{`
                            @keyframes spin {
                                from { transform: rotate(0deg); }
                                to { transform: rotate(360deg); }
                            }
                        `}</style>
                    </div>
                </div>
            )}
        </PageLayout>
    );
}
