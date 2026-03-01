'use client';
import React, { useState, useEffect, useRef } from 'react';
import {
    Search, Loader2, ChevronDown, ChevronRight, AlertTriangle, Save,
} from 'lucide-react';
import { severityColor } from '@/lib/colors';
import { cardStyle, inputStyle, btnPrimary } from '@/lib/styles';
import { getAuthHeaders } from '@/lib/styles';
import { SeverityBadge, StatusBadge } from '@/components/shared';
import { API_BASE } from '@/lib/api';
import type { DbConnection, SchemaFinding, AiSuggestion, JobStatus } from './types';

interface AnalyzerTabProps {
    connections: DbConnection[];
    projectId: string;
    onSpecsSaved: () => void;
}

export default function AnalyzerTab({ connections, projectId, onSpecsSaved }: AnalyzerTabProps) {
    const [analyzerConnId, setAnalyzerConnId] = useState('');
    const [isAnalyzing, setIsAnalyzing] = useState(false);
    const [analyzeJobId, setAnalyzeJobId] = useState<string | null>(null);
    const [analyzeJobStatus, setAnalyzeJobStatus] = useState<JobStatus | null>(null);
    const [analyzeRunId, setAnalyzeRunId] = useState<string | null>(null);
    const [schemaFindings, setSchemaFindings] = useState<SchemaFinding[]>([]);
    const [expandedFindingIdx, setExpandedFindingIdx] = useState<number | null>(null);
    const [suggestions, setSuggestions] = useState<AiSuggestion[]>([]);
    const [isGeneratingSuggestions, setIsGeneratingSuggestions] = useState(false);
    const [suggestJobId, setSuggestJobId] = useState<string | null>(null);
    const [savingSpec, setSavingSpec] = useState(false);

    const pollRef = useRef<NodeJS.Timeout | null>(null);

    // Poll active jobs
    useEffect(() => {
        const activeJob = analyzeJobId || suggestJobId;
        if (!activeJob) return;

        const poll = async () => {
            try {
                const res = await fetch(`${API_BASE}/database-testing/jobs/${activeJob}`, {
                    headers: getAuthHeaders(),
                });
                if (res.ok) {
                    const data = await res.json();

                    if (activeJob === analyzeJobId) {
                        setAnalyzeJobStatus(data);
                        if (data.status === 'completed' || data.status === 'failed') {
                            setIsAnalyzing(false);
                            if (pollRef.current) clearInterval(pollRef.current);
                            pollRef.current = null;
                            if (data.status === 'completed' && data.run_id) {
                                setAnalyzeRunId(data.run_id);
                                const findings = (data.result as Record<string, unknown>)?.findings;
                                if (Array.isArray(findings) && findings.length > 0) {
                                    setSchemaFindings(findings as SchemaFinding[]);
                                } else {
                                    try {
                                        const schemaRes = await fetch(`${API_BASE}/database-testing/runs/${data.run_id}/schema`, {
                                            headers: getAuthHeaders(),
                                        });
                                        if (schemaRes.ok) {
                                            const schemaData = await schemaRes.json();
                                            const sf = schemaData.schema_findings;
                                            if (sf) {
                                                const sfFindings = sf.findings || (Array.isArray(sf) ? sf : []);
                                                if (sfFindings.length > 0) {
                                                    setSchemaFindings(sfFindings as SchemaFinding[]);
                                                }
                                            }
                                        }
                                    } catch (e) {
                                        console.error('Failed to fetch schema findings:', e);
                                    }
                                }
                                const aiError = (data.result as Record<string, unknown>)?.ai_error;
                                if (aiError) {
                                    setAnalyzeJobStatus({ ...data, error: `AI analysis failed: ${aiError}` });
                                }
                            }
                            setAnalyzeJobId(null);
                        }
                    } else if (activeJob === suggestJobId) {
                        if (data.status === 'completed' || data.status === 'failed') {
                            setIsGeneratingSuggestions(false);
                            if (pollRef.current) clearInterval(pollRef.current);
                            pollRef.current = null;
                            if (data.status === 'completed' && data.result) {
                                const suggs = (data.result as Record<string, unknown>)?.suggestions;
                                if (Array.isArray(suggs)) {
                                    setSuggestions(suggs.map((s: Record<string, unknown>) => ({ ...s, approved: true } as AiSuggestion)));
                                }
                            }
                            setSuggestJobId(null);
                        }
                    }
                } else if (res.status === 404) {
                    if (pollRef.current) clearInterval(pollRef.current);
                    pollRef.current = null;
                    if (activeJob === analyzeJobId) {
                        setIsAnalyzing(false);
                        setAnalyzeJobId(null);
                        setAnalyzeJobStatus(null);
                    } else if (activeJob === suggestJobId) {
                        setIsGeneratingSuggestions(false);
                        setSuggestJobId(null);
                    }
                }
            } catch (e) { console.error('Poll error:', e); }
        };

        poll();
        pollRef.current = setInterval(poll, 2000);
        return () => { if (pollRef.current) clearInterval(pollRef.current); };
    }, [analyzeJobId, suggestJobId]);

    const startAnalysis = async () => {
        if (!analyzerConnId) return;
        setIsAnalyzing(true);
        setAnalyzeJobStatus(null);
        setSchemaFindings([]);
        setSuggestions([]);
        setAnalyzeRunId(null);
        try {
            const res = await fetch(`${API_BASE}/database-testing/analyze/${analyzerConnId}?project_id=${encodeURIComponent(projectId)}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
            });
            if (res.ok) {
                const data = await res.json();
                setAnalyzeJobId(data.job_id);
            } else {
                const err = await res.json().catch(() => ({ detail: 'Analysis failed' }));
                setAnalyzeJobStatus({ job_id: '', status: 'failed', error: err.detail });
                setIsAnalyzing(false);
            }
        } catch (e) {
            setAnalyzeJobStatus({ job_id: '', status: 'failed', error: String(e) });
            setIsAnalyzing(false);
        }
    };

    const generateSuggestions = async () => {
        if (!analyzeRunId) return;
        setIsGeneratingSuggestions(true);
        setSuggestions([]);
        try {
            const res = await fetch(`${API_BASE}/database-testing/suggest/${analyzeRunId}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
            });
            if (res.ok) {
                const data = await res.json();
                if (data.job_id) {
                    setSuggestJobId(data.job_id);
                } else if (data.suggestions) {
                    setSuggestions(data.suggestions.map((s: Record<string, unknown>) => ({ ...s, approved: true } as AiSuggestion)));
                    setIsGeneratingSuggestions(false);
                }
            } else {
                setIsGeneratingSuggestions(false);
            }
        } catch (e) {
            console.error('Generate suggestions failed:', e);
            setIsGeneratingSuggestions(false);
        }
    };

    const saveSuggestionsAsSpec = async () => {
        if (!analyzeRunId) return;
        const approved = suggestions.filter(s => s.approved);
        if (approved.length === 0) { alert('Select at least one suggestion'); return; }
        setSavingSpec(true);
        try {
            const res = await fetch(`${API_BASE}/database-testing/runs/${analyzeRunId}/approve-suggestions`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
                body: JSON.stringify({ suggestions: approved, project_id: projectId }),
            });
            if (res.ok) {
                alert('Spec saved successfully');
                onSpecsSaved();
            } else {
                const err = await res.json().catch(() => ({ detail: 'Failed to save spec' }));
                alert(err.detail || 'Failed to save spec');
            }
        } catch (e) { console.error('Save spec failed:', e); }
        setSavingSpec(false);
    };

    const toggleSuggestion = (idx: number) => {
        setSuggestions(prev => prev.map((s, i) => i === idx ? { ...s, approved: !s.approved } : s));
    };

    const statusColorFn = (status: string) => {
        const colors: Record<string, string> = {
            pending: 'var(--text-tertiary)', running: 'var(--primary-hover)', completed: 'var(--success)',
            failed: 'var(--danger)', passed: 'var(--success)', error: 'var(--warning)',
        };
        return colors[status?.toLowerCase()] || 'var(--text-tertiary)';
    };

    return (
        <div>
            <div style={cardStyle}>
                <h3 style={{ fontWeight: 600, marginBottom: '1rem' }}>Schema Analyzer</h3>
                <div style={{ display: 'flex', gap: '1rem', marginBottom: '1rem', alignItems: 'flex-end' }}>
                    <div style={{ flex: 1 }}>
                        <label style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '4px', display: 'block' }}>Connection</label>
                        <select value={analyzerConnId}
                            onChange={e => setAnalyzerConnId(e.target.value)}
                            style={inputStyle}>
                            <option value="">Select a connection...</option>
                            {connections.map(c => (
                                <option key={c.id} value={c.id}>{c.name} ({c.host}:{c.port}/{c.database})</option>
                            ))}
                        </select>
                    </div>
                    <button
                        onClick={startAnalysis}
                        disabled={isAnalyzing || !analyzerConnId}
                        style={{
                            ...btnPrimary,
                            cursor: isAnalyzing || !analyzerConnId ? 'not-allowed' : 'pointer',
                            background: isAnalyzing || !analyzerConnId ? 'var(--border)' : 'var(--primary)',
                        }}
                    >
                        {isAnalyzing ? <Loader2 size={16} style={{ animation: 'spin 1s linear infinite' }} /> : <Search size={16} />}
                        {isAnalyzing ? 'Analyzing...' : 'Analyze Schema'}
                    </button>
                </div>

                <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                    Analyzes schema structure, constraints, indexes, and data patterns to find potential issues.
                </div>
            </div>

            {/* Analysis Progress / Error */}
            {analyzeJobStatus && (analyzeJobStatus.status !== 'completed' || analyzeJobStatus.error) && (
                <div style={{
                    ...cardStyle, marginTop: '1rem',
                    borderLeft: `3px solid ${analyzeJobStatus.error ? 'var(--danger)' : statusColorFn(analyzeJobStatus.status)}`,
                }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                        <StatusBadge status={analyzeJobStatus.error ? 'failed' : analyzeJobStatus.status} />
                        {analyzeJobStatus.error && (
                            <span style={{ fontSize: '0.85rem', color: 'var(--danger)' }}>{analyzeJobStatus.error}</span>
                        )}
                    </div>
                </div>
            )}

            {/* Schema Findings */}
            {schemaFindings.length > 0 && (
                <div style={{ marginTop: '1.5rem' }}>
                    <h4 style={{ fontWeight: 600, marginBottom: '1rem' }}>
                        Schema Findings ({schemaFindings.length})
                    </h4>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                        {schemaFindings.map((finding, idx) => (
                            <div key={idx} style={{
                                border: '1px solid var(--border)', borderRadius: 'var(--radius)',
                                borderLeft: `3px solid ${severityColor(finding.severity)}`,
                                overflow: 'hidden',
                            }}>
                                <div onClick={() => setExpandedFindingIdx(expandedFindingIdx === idx ? null : idx)}
                                    style={{
                                        padding: '0.75rem 1rem', cursor: 'pointer',
                                        display: 'flex', alignItems: 'center', gap: '0.75rem',
                                        background: expandedFindingIdx === idx ? 'rgba(59, 130, 246, 0.03)' : 'transparent',
                                    }}>
                                    {expandedFindingIdx === idx ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                                    <SeverityBadge severity={finding.severity} />
                                    <span style={{ flex: 1, fontSize: '0.9rem', fontWeight: 500 }}>{finding.title}</span>
                                    {finding.category && (
                                        <span style={{
                                            fontSize: '0.7rem', padding: '1px 6px', borderRadius: '4px',
                                            background: 'rgba(99, 102, 241, 0.1)', color: 'var(--accent)',
                                        }}>
                                            {finding.category}
                                        </span>
                                    )}
                                    {finding.table_name && (
                                        <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
                                            {finding.table_name}{finding.column_name ? `.${finding.column_name}` : ''}
                                        </span>
                                    )}
                                </div>
                                {expandedFindingIdx === idx && (
                                    <div style={{ padding: '1rem', borderTop: '1px solid var(--border)', fontSize: '0.85rem' }}>
                                        <p style={{ marginBottom: '0.5rem', lineHeight: 1.5 }}>{finding.description}</p>
                                        {finding.recommendation && (
                                            <div style={{ marginTop: '0.5rem' }}>
                                                <strong>Recommendation:</strong>
                                                <p style={{ color: 'var(--text-secondary)', marginTop: '2px' }}>{finding.recommendation}</p>
                                            </div>
                                        )}
                                    </div>
                                )}
                            </div>
                        ))}
                    </div>

                    {/* Generate Suggestions Button */}
                    <div style={{ marginTop: '1.5rem' }}>
                        <button
                            onClick={generateSuggestions}
                            disabled={isGeneratingSuggestions || !analyzeRunId}
                            style={{
                                ...btnPrimary,
                                cursor: isGeneratingSuggestions ? 'not-allowed' : 'pointer',
                                background: isGeneratingSuggestions ? 'var(--border)' : 'var(--primary)',
                            }}
                        >
                            {isGeneratingSuggestions
                                ? <Loader2 size={16} style={{ animation: 'spin 1s linear infinite' }} />
                                : <AlertTriangle size={16} />}
                            {isGeneratingSuggestions ? 'Generating...' : 'Generate Test Suggestions'}
                        </button>
                    </div>
                </div>
            )}

            {/* AI Suggestions */}
            {suggestions.length > 0 && (
                <div style={{ ...cardStyle, marginTop: '1.5rem' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
                        <h4 style={{ fontWeight: 600 }}>AI Test Suggestions ({suggestions.length})</h4>
                        <button
                            onClick={saveSuggestionsAsSpec}
                            disabled={savingSpec || suggestions.filter(s => s.approved).length === 0}
                            style={{
                                ...btnPrimary, fontSize: '0.8rem',
                                cursor: savingSpec ? 'not-allowed' : 'pointer',
                                background: savingSpec ? 'var(--border)' : 'var(--primary)',
                            }}
                        >
                            {savingSpec ? <Loader2 size={14} style={{ animation: 'spin 1s linear infinite' }} /> : <Save size={14} />}
                            Save as Spec ({suggestions.filter(s => s.approved).length} selected)
                        </button>
                    </div>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                        {suggestions.map((sugg, idx) => (
                            <div key={idx} style={{
                                border: '1px solid var(--border)', borderRadius: 'var(--radius)',
                                padding: '0.75rem 1rem', display: 'flex', alignItems: 'flex-start', gap: '0.75rem',
                                background: sugg.approved ? 'rgba(59, 130, 246, 0.03)' : 'transparent',
                            }}>
                                <input type="checkbox" checked={sugg.approved || false}
                                    onChange={() => toggleSuggestion(idx)}
                                    style={{ marginTop: '3px', flexShrink: 0 }} />
                                <div style={{ flex: 1 }}>
                                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '4px' }}>
                                        <SeverityBadge severity={sugg.severity} />
                                        <span style={{ fontWeight: 500, fontSize: '0.9rem' }}>{sugg.check_name}</span>
                                    </div>
                                    <p style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '4px' }}>
                                        {sugg.description}
                                    </p>
                                    <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
                                        <span style={{ marginRight: '1rem' }}>Table: <strong>{sugg.table_name}</strong></span>
                                        {sugg.column_name && <span style={{ marginRight: '1rem' }}>Column: <strong>{sugg.column_name}</strong></span>}
                                        <span>Type: {sugg.check_type}</span>
                                    </div>
                                    <pre style={{
                                        background: 'var(--bg)', padding: '0.4rem 0.6rem', borderRadius: '4px',
                                        fontSize: '0.75rem', marginTop: '0.5rem', overflow: 'auto', maxHeight: '80px',
                                    }}>
                                        {sugg.sql_query}
                                    </pre>
                                </div>
                            </div>
                        ))}
                    </div>
                </div>
            )}
        </div>
    );
}
