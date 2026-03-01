'use client';
import React, { useState } from 'react';
import {
    Play, FileCode, Loader2, ChevronDown, ChevronRight,
    RefreshCw, Download,
} from 'lucide-react';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { vscDarkPlus } from 'react-syntax-highlighter/dist/esm/styles/prism';
import { API_BASE } from '@/lib/api';
import type { K6Script, K6ExecutionStatus, SystemLimits } from './types';

interface ScriptsTabProps {
    scripts: K6Script[];
    scriptsLoading: boolean;
    k6Status: K6ExecutionStatus | null;
    systemLimits: SystemLimits | null;
    onFetchScripts: () => void;
    onRunScript: (scriptPath: string, vus: string, duration: string) => Promise<void>;
    onLoadScriptContent: (name: string) => Promise<void>;
    scriptContents: Record<string, string>;
}

export default function ScriptsTab({
    scripts,
    scriptsLoading,
    k6Status,
    systemLimits,
    onFetchScripts,
    onRunScript,
    onLoadScriptContent,
    scriptContents,
}: ScriptsTabProps) {
    const [expandedScript, setExpandedScript] = useState<string | null>(null);
    const [runVUs, setRunVUs] = useState('');
    const [runDuration, setRunDuration] = useState('');

    return (
        <div>
            <div style={{ display: 'flex', gap: '0.75rem', marginBottom: '1rem', alignItems: 'center' }}>
                <button
                    onClick={() => onFetchScripts()}
                    style={{
                        display: 'flex', alignItems: 'center', gap: '0.5rem',
                        padding: '0.5rem 0.75rem', background: 'var(--surface)',
                        border: '1px solid var(--border)', borderRadius: 'var(--radius)',
                        cursor: 'pointer', color: 'var(--text-secondary)', fontSize: '0.875rem',
                    }}
                >
                    <RefreshCw size={14} /> Refresh
                </button>
                <span style={{ color: 'var(--text-secondary)', fontSize: '0.875rem' }}>
                    {scripts.length} script{scripts.length !== 1 ? 's' : ''}
                </span>
            </div>

            {scriptsLoading ? (
                <div style={{ textAlign: 'center', padding: '3rem', color: 'var(--text-secondary)' }}>
                    <Loader2 size={24} style={{ animation: 'spin 1s linear infinite', margin: '0 auto 0.5rem' }} />
                    <p>Loading scripts...</p>
                </div>
            ) : scripts.length === 0 ? (
                <div style={{
                    textAlign: 'center', padding: '3rem',
                    background: 'var(--surface)', borderRadius: 'var(--radius)',
                    border: '1px solid var(--border)',
                }}>
                    <Play size={40} style={{ color: 'var(--text-secondary)', margin: '0 auto 1rem' }} />
                    <p style={{ color: 'var(--text-secondary)', marginBottom: '0.5rem' }}>No K6 scripts yet</p>
                    <p style={{ color: 'var(--text-secondary)', fontSize: '0.8rem' }}>Create a scenario and generate a script to see it here</p>
                </div>
            ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                    {scripts.map(script => {
                        const isExpanded = expandedScript === script.name;
                        return (
                            <div key={script.name} style={{
                                background: 'var(--surface)', border: '1px solid var(--border)',
                                borderRadius: 'var(--radius)', overflow: 'hidden',
                            }}>
                                <div
                                    style={{
                                        display: 'flex', alignItems: 'center', padding: '0.75rem 1rem',
                                        gap: '0.75rem', cursor: 'pointer',
                                    }}
                                    onClick={() => {
                                        if (isExpanded) {
                                            setExpandedScript(null);
                                        } else {
                                            setExpandedScript(script.name);
                                            onLoadScriptContent(script.name);
                                        }
                                    }}
                                >
                                    {isExpanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                                    <FileCode size={16} style={{ color: 'var(--success)' }} />
                                    <div style={{ flex: 1 }}>
                                        <span style={{ fontWeight: 500, fontSize: '0.875rem' }}>{script.name}</span>
                                        {script.spec_name && (
                                            <span style={{ fontSize: '0.7rem', color: 'var(--text-secondary)', marginLeft: '0.5rem' }}>
                                                from {script.spec_name}
                                            </span>
                                        )}
                                    </div>
                                    <span style={{ color: 'var(--text-secondary)', fontSize: '0.75rem' }}>
                                        {(script.size_bytes / 1024).toFixed(1)} KB
                                    </span>
                                    <span style={{ color: 'var(--text-secondary)', fontSize: '0.75rem' }}>
                                        {new Date(script.modified_at).toLocaleDateString()}
                                    </span>
                                    <div style={{ display: 'flex', gap: '0.25rem' }} onClick={e => e.stopPropagation()}>
                                        <button
                                            onClick={() => onRunScript(script.path, '', '')}
                                            disabled={!!k6Status?.load_test_active}
                                            title={k6Status?.load_test_active ? 'Load test in progress' : ''}
                                            style={{
                                                display: 'flex', alignItems: 'center', gap: '0.25rem',
                                                padding: '0.3rem 0.6rem', background: 'var(--primary-glow)',
                                                color: 'var(--primary)', border: '1px solid rgba(59, 130, 246, 0.2)',
                                                borderRadius: 'var(--radius)', cursor: 'pointer', fontSize: '0.75rem',
                                                opacity: k6Status?.load_test_active ? 0.5 : 1,
                                            }}
                                        >
                                            <Play size={12} /> Run
                                        </button>
                                        <a
                                            href={`${API_BASE}/load-testing/scripts/${script.name}/download`}
                                            style={{
                                                display: 'flex', alignItems: 'center', gap: '0.25rem',
                                                padding: '0.3rem 0.6rem', background: 'rgba(156, 163, 175, 0.1)',
                                                color: 'var(--text-secondary)', border: '1px solid var(--border)',
                                                borderRadius: 'var(--radius)', cursor: 'pointer', fontSize: '0.75rem',
                                                textDecoration: 'none',
                                            }}
                                        >
                                            <Download size={12} /> Download
                                        </a>
                                    </div>
                                </div>

                                {isExpanded && (
                                    <div style={{ borderTop: '1px solid var(--border)', padding: '1rem' }}>
                                        {/* VU/Duration overrides */}
                                        <div style={{ display: 'flex', gap: '0.75rem', marginBottom: '0.75rem', alignItems: 'flex-start' }}>
                                            <div>
                                                <label style={{ fontSize: '0.7rem', color: 'var(--text-secondary)' }}>VUs Override</label>
                                                <input
                                                    type="number"
                                                    placeholder={systemLimits ? `Max: ${systemLimits.effective_max_vus.toLocaleString()}` : 'e.g., 10'}
                                                    value={runVUs}
                                                    onChange={e => setRunVUs(e.target.value)}
                                                    style={{
                                                        display: 'block', width: '130px', padding: '0.3rem 0.5rem',
                                                        background: 'var(--background)',
                                                        border: `1px solid ${
                                                            runVUs && systemLimits
                                                                ? parseInt(runVUs) > systemLimits.effective_max_vus
                                                                    ? 'var(--danger)'
                                                                    : parseInt(runVUs) > systemLimits.effective_max_vus * 0.8
                                                                        ? 'var(--warning)'
                                                                        : 'var(--border)'
                                                                : 'var(--border)'
                                                        }`,
                                                        borderRadius: 'var(--radius)', color: 'var(--text-primary)', fontSize: '0.8rem',
                                                    }}
                                                />
                                                {systemLimits && runVUs && parseInt(runVUs) > systemLimits.effective_max_vus && (
                                                    <div style={{ fontSize: '0.65rem', color: 'var(--danger)', marginTop: '0.2rem' }}>
                                                        Exceeds max ({systemLimits.effective_max_vus.toLocaleString()} VUs) — will be capped
                                                    </div>
                                                )}
                                                {systemLimits && runVUs && parseInt(runVUs) > systemLimits.effective_max_vus * 0.8 && parseInt(runVUs) <= systemLimits.effective_max_vus && (
                                                    <div style={{ fontSize: '0.65rem', color: 'var(--warning)', marginTop: '0.2rem' }}>
                                                        Approaching limit ({systemLimits.effective_max_vus.toLocaleString()} max)
                                                    </div>
                                                )}
                                                {systemLimits && !runVUs && (
                                                    <div style={{ fontSize: '0.65rem', color: 'var(--text-secondary)', marginTop: '0.2rem' }}>
                                                        Up to {systemLimits.effective_max_vus.toLocaleString()} VUs{systemLimits.execution_mode === 'distributed' ? ` (${systemLimits.k6_max_vus.toLocaleString()}/worker)` : ''}
                                                    </div>
                                                )}
                                            </div>
                                            <div>
                                                <label style={{ fontSize: '0.7rem', color: 'var(--text-secondary)' }}>Duration Override</label>
                                                <input
                                                    type="text"
                                                    placeholder={systemLimits ? `Max: ${systemLimits.k6_max_duration}` : 'e.g., 30s'}
                                                    value={runDuration}
                                                    onChange={e => setRunDuration(e.target.value)}
                                                    style={{
                                                        display: 'block', width: '130px', padding: '0.3rem 0.5rem',
                                                        background: 'var(--background)', border: '1px solid var(--border)',
                                                        borderRadius: 'var(--radius)', color: 'var(--text-primary)', fontSize: '0.8rem',
                                                    }}
                                                />
                                                {systemLimits && !runDuration && (
                                                    <div style={{ fontSize: '0.65rem', color: 'var(--text-secondary)', marginTop: '0.2rem' }}>
                                                        Max: {systemLimits.k6_max_duration}
                                                    </div>
                                                )}
                                            </div>
                                            <button
                                                onClick={() => onRunScript(script.path, runVUs, runDuration)}
                                                disabled={!!k6Status?.load_test_active}
                                                title={k6Status?.load_test_active ? 'Load test in progress' : ''}
                                                style={{
                                                    display: 'flex', alignItems: 'center', gap: '0.25rem',
                                                    padding: '0.4rem 0.8rem', background: 'var(--primary)', color: 'white',
                                                    border: 'none', borderRadius: 'var(--radius)', cursor: 'pointer',
                                                    fontSize: '0.8rem', marginTop: '1rem',
                                                    opacity: k6Status?.load_test_active ? 0.5 : 1,
                                                }}
                                            >
                                                <Play size={14} /> Run with Overrides
                                            </button>
                                        </div>

                                        <SyntaxHighlighter
                                            language="javascript"
                                            style={vscDarkPlus}
                                            customStyle={{ margin: 0, padding: '1rem', fontSize: '0.75rem', borderRadius: 'var(--radius)', maxHeight: '500px' }}
                                            showLineNumbers={true}
                                            wrapLines={true}
                                        >
                                            {scriptContents[script.name] || 'Loading...'}
                                        </SyntaxHighlighter>
                                    </div>
                                )}
                            </div>
                        );
                    })}
                </div>
            )}
        </div>
    );
}
