import { CheckCircle, Clipboard, Code2, ExternalLink, GitPullRequest, Loader2, Sparkles, X } from 'lucide-react';
import type { CSSProperties } from 'react';
import { useState } from 'react';

interface WorkflowGeneratorPanelProps {
    onClose?: () => void;
    onOpenPr: (changeRequestId: string) => Promise<WorkflowDraftResult>;
    onGenerate: (payload: {
        provider: 'github';
        workflow_name: string;
        template: string;
        prompt?: string;
        branches: string[];
        browsers: string[];
        artifact_retention_days: number;
    }) => Promise<WorkflowDraftResult | null>;
}

interface WorkflowDraftResult {
    id?: string;
    change_request_id?: string;
    workflow_path: string;
    generated_yaml: string;
    validation_errors: string[];
    validation_warnings: string[];
    install_status?: string;
    status?: string;
    can_open_pr?: boolean;
    next_actions?: string[];
    pull_request_url?: string;
    pull_request_number?: number;
    branch?: string;
    commit_sha?: string;
}

export function WorkflowGeneratorPanel({ onGenerate, onOpenPr, onClose }: WorkflowGeneratorPanelProps) {
    const [workflowName, setWorkflowName] = useState('Quorvex PR Quality Gate');
    const [template, setTemplate] = useState('pr-quality-gate');
    const [prompt, setPrompt] = useState('');
    const [branches, setBranches] = useState('main');
    const [browsers, setBrowsers] = useState('chromium');
    const [retention, setRetention] = useState(14);
    const [loading, setLoading] = useState(false);
    const [openingPr, setOpeningPr] = useState(false);
    const [openPrError, setOpenPrError] = useState('');
    const [copied, setCopied] = useState(false);
    const [result, setResult] = useState<Awaited<ReturnType<typeof onGenerate>>>(null);

    const generate = async () => {
        setLoading(true);
        const next = await onGenerate({
            provider: 'github',
            workflow_name: workflowName,
            template,
            prompt: prompt || undefined,
            branches: branches.split(',').map(item => item.trim()).filter(Boolean),
            browsers: browsers.split(',').map(item => item.trim()).filter(Boolean),
            artifact_retention_days: retention,
        });
        setOpenPrError('');
        setResult(next);
        setLoading(false);
    };

    const openPr = async () => {
        const changeId = result?.id || result?.change_request_id;
        if (!changeId) return;
        setOpeningPr(true);
        setOpenPrError('');
        try {
            const opened = await onOpenPr(changeId);
            setResult(prev => ({ ...(prev || opened), ...opened }));
        } catch (e: any) {
            setOpenPrError(e.message || 'Failed to open pull request');
        } finally {
            setOpeningPr(false);
        }
    };

    const copyYaml = async () => {
        if (!result?.generated_yaml) return;
        await navigator.clipboard.writeText(result.generated_yaml);
        setCopied(true);
        window.setTimeout(() => setCopied(false), 1600);
    };

    return (
        <section className="animate-in stagger-2" style={{
            border: '1px solid var(--border)',
            borderRadius: 'var(--radius)',
            background: 'var(--surface)',
            marginBottom: '1.5rem',
            overflow: 'hidden',
        }}>
            <div style={{ padding: '1rem 1.25rem', borderBottom: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', gap: '1rem', flexWrap: 'wrap' }}>
                <div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontWeight: 800 }}>
                        <Sparkles size={17} />
                        Generate CI Workflow
                    </div>
                    <div style={{ marginTop: '0.2rem', color: 'var(--text-secondary)', fontSize: '0.82rem' }}>
                        Creates a validated GitHub Actions draft. It does not install or push changes yet.
                    </div>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                    <button
                        type="button"
                        onClick={generate}
                        disabled={loading || openingPr || !workflowName.trim()}
                        style={primaryButtonStyle(loading || openingPr)}
                    >
                        {loading ? <Loader2 size={15} className="spin" /> : <Code2 size={15} />}
                        Generate Draft
                    </button>
                    {onClose && (
                        <button type="button" onClick={onClose} aria-label="Close workflow generator" style={iconButtonStyle}>
                            <X size={15} />
                        </button>
                    )}
                </div>
            </div>

            <div style={{ padding: '1rem 1.25rem', display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '0.85rem' }}>
                <label style={{ display: 'flex', flexDirection: 'column', gap: '0.35rem', fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                    Workflow name
                    <input value={workflowName} onChange={e => setWorkflowName(e.target.value)} disabled={loading || openingPr} style={inputStyle} />
                </label>
                <label style={{ display: 'flex', flexDirection: 'column', gap: '0.35rem', fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                    Template
                    <select value={template} onChange={e => setTemplate(e.target.value)} disabled={loading || openingPr} style={inputStyle}>
                        <option value="pr-quality-gate">PR quality gate</option>
                        <option value="playwright-smoke">Playwright smoke</option>
                        <option value="nightly-regression">Nightly regression</option>
                        <option value="release-gate">Release gate</option>
                    </select>
                </label>
                <label style={{ display: 'flex', flexDirection: 'column', gap: '0.35rem', fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                    Branches
                    <input value={branches} onChange={e => setBranches(e.target.value)} disabled={loading || openingPr} style={inputStyle} />
                </label>
                <label style={{ display: 'flex', flexDirection: 'column', gap: '0.35rem', fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                    Browsers
                    <input value={browsers} onChange={e => setBrowsers(e.target.value)} disabled={loading || openingPr} style={inputStyle} />
                </label>
                <label style={{ display: 'flex', flexDirection: 'column', gap: '0.35rem', fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                    Artifact retention
                    <input type="number" min={1} max={90} value={retention} onChange={e => setRetention(Math.max(1, Number(e.target.value) || 14))} disabled={loading || openingPr} style={inputStyle} />
                </label>
                <label style={{ display: 'flex', flexDirection: 'column', gap: '0.35rem', fontSize: '0.8rem', color: 'var(--text-secondary)', gridColumn: '1 / -1' }}>
                    Intent
                    <textarea value={prompt} onChange={e => setPrompt(e.target.value)} rows={3} disabled={loading || openingPr} style={{ ...inputStyle, resize: 'vertical' }} placeholder="Optional notes for this workflow draft" />
                </label>
            </div>

            {result && (
                <div style={{ borderTop: '1px solid var(--border)', padding: '1rem 1.25rem' }}>
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '0.75rem', flexWrap: 'wrap' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.45rem', fontWeight: 750 }}>
                            <CheckCircle size={16} color={result.validation_errors.length ? 'var(--warning)' : 'var(--success)'} />
                            {result.workflow_path}
                            {result.install_status && <span style={draftBadgeStyle}>{result.install_status}</span>}
                        </div>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.45rem', flexWrap: 'wrap' }}>
                            {result.pull_request_url ? (
                                <a href={result.pull_request_url} target="_blank" rel="noopener noreferrer" style={linkButtonStyle}>
                                    <ExternalLink size={14} />
                                    Open PR
                                </a>
                            ) : (
                                <button type="button" onClick={openPr} disabled={!result.can_open_pr || result.validation_errors.length > 0 || openingPr} style={primaryButtonStyle(openingPr || !result.can_open_pr || result.validation_errors.length > 0)}>
                                    {openingPr ? <Loader2 size={14} className="spin" /> : <GitPullRequest size={14} />}
                                    {openingPr ? 'Opening PR...' : 'Open Draft PR'}
                                </button>
                            )}
                            <button type="button" onClick={copyYaml} disabled={!result.generated_yaml || openingPr} style={secondaryButtonStyle}>
                                <Clipboard size={14} />
                                {copied ? 'Copied' : 'Copy YAML'}
                            </button>
                        </div>
                    </div>
                    {result.pull_request_url && (
                        <div style={{ marginTop: '0.75rem', padding: '0.7rem 0.8rem', border: '1px solid rgba(34, 197, 94, 0.25)', background: 'rgba(34, 197, 94, 0.08)', borderRadius: 'var(--radius)', color: 'var(--text)', fontSize: '0.84rem' }}>
                            PR opened{result.pull_request_number ? ` #${result.pull_request_number}` : ''}{result.branch ? ` from ${result.branch}` : ''}.
                        </div>
                    )}
                    {openPrError && (
                        <div style={{ marginTop: '0.75rem', padding: '0.7rem 0.8rem', border: '1px solid rgba(248, 113, 113, 0.25)', background: 'var(--danger-muted)', color: 'var(--danger)', borderRadius: 'var(--radius)', fontSize: '0.84rem' }}>
                            {openPrError}
                        </div>
                    )}
                    {(!result.can_open_pr && result.validation_errors.length === 0 && !result.pull_request_url) && (
                        <div style={{ marginTop: '0.75rem', color: 'var(--text-secondary)', fontSize: '0.82rem' }}>
                            Open PR is unavailable until GitHub repository configuration is complete.
                        </div>
                    )}
                    {(result.next_actions || []).length > 0 && (
                        <div style={{ marginTop: '0.75rem', display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(210px, 1fr))', gap: '0.5rem' }}>
                            {(result.next_actions || []).map((action, index) => (
                                <div key={action} style={{ padding: '0.55rem 0.65rem', border: '1px solid var(--border)', borderRadius: 'var(--radius)', background: 'var(--background)', color: 'var(--text-secondary)', fontSize: '0.8rem' }}>
                                    <strong style={{ color: 'var(--text)' }}>{index + 1}.</strong> {action}
                                </div>
                            ))}
                        </div>
                    )}
                    {result.validation_errors.length > 0 && (
                        <div style={{ marginTop: '0.5rem', color: 'var(--danger)', fontSize: '0.82rem' }}>
                            {result.validation_errors.join(' ')}
                        </div>
                    )}
                    {result.validation_warnings.length > 0 && (
                        <div style={{ marginTop: '0.5rem', color: 'var(--warning)', fontSize: '0.82rem' }}>
                            {result.validation_warnings.join(' ')}
                        </div>
                    )}
                    <pre style={{
                        margin: '0.85rem 0 0',
                        padding: '0.85rem',
                        maxHeight: 360,
                        overflow: 'auto',
                        border: '1px solid var(--border)',
                        borderRadius: 'var(--radius)',
                        background: 'var(--background)',
                        color: 'var(--text-secondary)',
                        fontSize: '0.78rem',
                        lineHeight: 1.45,
                    }}><code>{result.generated_yaml}</code></pre>
                </div>
            )}

            <style jsx>{`
                .spin {
                    animation: spin 1s linear infinite;
                }
                @keyframes spin {
                    from { transform: rotate(0deg); }
                    to { transform: rotate(360deg); }
                }
            `}</style>
        </section>
    );
}

const inputStyle: CSSProperties = {
    width: '100%',
    padding: '0.48rem 0.55rem',
    border: '1px solid var(--border)',
    borderRadius: 'var(--radius)',
    background: 'var(--background)',
    color: 'var(--text)',
    fontSize: '0.85rem',
};

function primaryButtonStyle(disabled?: boolean): CSSProperties {
    return {
        display: 'inline-flex',
        alignItems: 'center',
        gap: '0.45rem',
        padding: '0.55rem 0.8rem',
        border: 'none',
        borderRadius: 'var(--radius)',
        background: 'var(--primary)',
        color: '#fff',
        cursor: disabled ? 'default' : 'pointer',
        fontWeight: 750,
        opacity: disabled ? 0.7 : 1,
    };
}

const secondaryButtonStyle: CSSProperties = {
    display: 'inline-flex',
    alignItems: 'center',
    gap: '0.4rem',
    padding: '0.45rem 0.65rem',
    border: '1px solid var(--border)',
    borderRadius: 'var(--radius)',
    background: 'var(--background)',
    color: 'var(--text)',
    cursor: 'pointer',
    fontWeight: 750,
    fontSize: '0.8rem',
};

const linkButtonStyle: CSSProperties = {
    display: 'inline-flex',
    alignItems: 'center',
    gap: '0.4rem',
    padding: '0.45rem 0.65rem',
    border: '1px solid var(--border)',
    borderRadius: 'var(--radius)',
    background: 'var(--background)',
    color: 'var(--primary)',
    textDecoration: 'none',
    cursor: 'pointer',
    fontWeight: 750,
    fontSize: '0.8rem',
};

const iconButtonStyle: CSSProperties = {
    width: 34,
    height: 34,
    display: 'inline-flex',
    alignItems: 'center',
    justifyContent: 'center',
    border: '1px solid var(--border)',
    borderRadius: 'var(--radius)',
    background: 'var(--background)',
    color: 'var(--text-secondary)',
    cursor: 'pointer',
};

const draftBadgeStyle: CSSProperties = {
    padding: '0.15rem 0.4rem',
    borderRadius: '999px',
    background: 'rgba(59, 130, 246, 0.1)',
    color: 'var(--primary)',
    fontSize: '0.68rem',
    fontWeight: 800,
    textTransform: 'uppercase',
};
