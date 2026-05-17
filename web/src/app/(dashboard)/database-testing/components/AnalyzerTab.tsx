'use client';
import React, { useState, useEffect, useMemo, useRef } from 'react';
import {
    Brain, CheckCircle2, ChevronDown, ChevronRight, Code2,
    Database, FileCheck2, Loader2, Save, Search, ShieldCheck, Wand2,
} from 'lucide-react';
import { severityBg, severityColor } from '@/lib/colors';
import { cardStyle, inputStyle, btnPrimary, btnSecondary } from '@/lib/styles';
import { getAuthHeaders } from '@/lib/styles';
import { SeverityBadge, StatusBadge } from '@/components/shared';
import { API_BASE } from '@/lib/api';
import type { DbConnection, SchemaFinding, AiSuggestion, JobStatus } from './types';

interface AnalyzerTabProps {
    connections: DbConnection[];
    projectId: string;
    onSpecsSaved: () => void;
    preferredConnectionId?: string;
}

export default function AnalyzerTab({ connections, projectId, onSpecsSaved, preferredConnectionId }: AnalyzerTabProps) {
    const [analyzerConnId, setAnalyzerConnId] = useState('');
    const [isAnalyzing, setIsAnalyzing] = useState(false);
    const [analyzeJobId, setAnalyzeJobId] = useState<string | null>(null);
    const [analyzeJobStatus, setAnalyzeJobStatus] = useState<JobStatus | null>(null);
    const [analyzeRunId, setAnalyzeRunId] = useState<string | null>(null);
    const [schemaFindings, setSchemaFindings] = useState<SchemaFinding[]>([]);
    const [expandedFindingIdx, setExpandedFindingIdx] = useState<number | null>(null);
    const [suggestions, setSuggestions] = useState<AiSuggestion[]>([]);
    const [expandedSqlIdx, setExpandedSqlIdx] = useState<number | null>(null);
    const [isGeneratingSuggestions, setIsGeneratingSuggestions] = useState(false);
    const [suggestJobId, setSuggestJobId] = useState<string | null>(null);
    const [savingSpec, setSavingSpec] = useState(false);
    const [analysisSummary, setAnalysisSummary] = useState('');
    const [analysisHealthScore, setAnalysisHealthScore] = useState<number | null>(null);
    const [tablesFound, setTablesFound] = useState<number | null>(null);

    const pollRef = useRef<NodeJS.Timeout | null>(null);

    const selectedConnection = useMemo(
        () => connections.find(c => c.id === analyzerConnId),
        [analyzerConnId, connections],
    );

    const severityCounts = useMemo(() => {
        const counts = { critical: 0, high: 0, medium: 0, low: 0, info: 0 };
        schemaFindings.forEach(finding => {
            const severity = finding.severity?.toLowerCase() as keyof typeof counts;
            if (severity in counts) counts[severity] += 1;
        });
        return counts;
    }, [schemaFindings]);

    const completedAnalysis = analyzeJobStatus?.status === 'completed' && Boolean(analyzeRunId);
    const selectedSuggestionsCount = suggestions.filter(s => s.approved).length;

    useEffect(() => {
        if (analyzerConnId || connections.length === 0) return;
        const preferred = preferredConnectionId && connections.find(c => c.id === preferredConnectionId);
        setAnalyzerConnId((preferred || connections[0]).id);
    }, [analyzerConnId, connections, preferredConnectionId]);

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
                                const result = (data.result as Record<string, unknown>) || {};
                                const findings = result.findings;
                                setAnalysisSummary(typeof result.summary === 'string' ? result.summary : '');
                                setAnalysisHealthScore(typeof result.health_score === 'number' ? result.health_score : null);
                                setTablesFound(typeof result.tables_found === 'number' ? result.tables_found : null);
                                if (Array.isArray(findings) && findings.length > 0) {
                                    setSchemaFindings(findings as SchemaFinding[]);
                                } else {
                                    setSchemaFindings([]);
                                    try {
                                        const schemaRes = await fetch(`${API_BASE}/database-testing/runs/${data.run_id}/schema`, {
                                            headers: getAuthHeaders(),
                                        });
                                        if (schemaRes.ok) {
                                            const schemaData = await schemaRes.json();
                                            const sf = schemaData.schema_findings;
                                            if (sf) {
                                                const sfFindings = sf.findings || (Array.isArray(sf) ? sf : []);
                                                setSchemaFindings(sfFindings as SchemaFinding[]);
                                                if (typeof result.summary !== 'string' && typeof sf.summary === 'string') setAnalysisSummary(sf.summary);
                                                if (typeof result.health_score !== 'number' && typeof sf.health_score === 'number') setAnalysisHealthScore(sf.health_score);
                                            }
                                        }
                                    } catch (e) {
                                        console.error('Failed to fetch schema findings:', e);
                                    }
                                }
                                const aiError = result.ai_error;
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
                                } else if (analyzeRunId) {
                                    const suggestionsRes = await fetch(`${API_BASE}/database-testing/runs/${analyzeRunId}/suggestions`, {
                                        headers: getAuthHeaders(),
                                    });
                                    if (suggestionsRes.ok) {
                                        const suggestionsData = await suggestionsRes.json();
                                        const recovered = suggestionsData.suggestions;
                                        if (Array.isArray(recovered)) {
                                            setSuggestions(recovered.map((s: Record<string, unknown>) => ({ ...s, approved: true } as AiSuggestion)));
                                        }
                                    }
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
    }, [analyzeJobId, suggestJobId, analyzeRunId]);

    const startAnalysis = async () => {
        if (!analyzerConnId) return;
        setIsAnalyzing(true);
        setAnalyzeJobStatus(null);
        setSchemaFindings([]);
        setSuggestions([]);
        setAnalyzeRunId(null);
        setAnalysisSummary('');
        setAnalysisHealthScore(null);
        setTablesFound(null);
        setExpandedFindingIdx(null);
        setExpandedSqlIdx(null);
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
                body: JSON.stringify({ project_id: projectId }),
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
                body: JSON.stringify({ suggestions: approved, project_id: projectId, spec_name: `schema-suggestions-${analyzeRunId}` }),
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

    const healthColor = analysisHealthScore == null
        ? 'var(--text-secondary)'
        : analysisHealthScore >= 80
            ? 'var(--success)'
            : analysisHealthScore >= 60
                ? 'var(--warning)'
                : 'var(--danger)';

    const analysisMessage = analyzeJobStatus?.stage_message
        || (isAnalyzing
            ? 'AI is reading the database structure and looking for risky patterns.'
            : completedAnalysis
                ? `Review complete${tablesFound != null ? ` - ${tablesFound} tables inspected` : ''}.`
                : 'Choose a connection and start a read-only AI review.');

    const reviewSteps = [
        {
            title: 'Read structure',
            text: 'Quorvex reads table names, columns, relationships, indexes, and constraints.',
            icon: Database,
        },
        {
            title: 'AI review',
            text: 'AI looks for missing relationships, weak constraints, risky data types, and performance gaps.',
            icon: Brain,
        },
        {
            title: 'Create checks',
            text: 'Turn findings into SQL checks that can be saved and run again later.',
            icon: FileCheck2,
        },
    ];

    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
            <section style={cardStyle}>
                <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: '1rem', marginBottom: '1.25rem' }}>
                    <div>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.65rem', marginBottom: '0.35rem' }}>
                            <Brain size={20} color="var(--primary)" />
                            <h3 style={{ fontWeight: 700, fontSize: '1.1rem' }}>AI Database Review</h3>
                        </div>
                        <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem', lineHeight: 1.55, maxWidth: '760px' }}>
                            Quorvex reviews your database design before checks are created. It reads structure only:
                            table names, columns, relationships, indexes, and constraints.
                        </p>
                    </div>
                    <div style={{
                        display: 'flex', alignItems: 'center', gap: '0.4rem', color: 'var(--success)',
                        fontSize: '0.8rem', fontWeight: 600, flexShrink: 0,
                    }}>
                        <ShieldCheck size={16} />
                        Read-only analysis
                    </div>
                </div>

                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(210px, 1fr))', gap: '0.85rem' }}>
                    {reviewSteps.map((step, idx) => {
                        const StepIcon = step.icon;
                        return (
                            <div key={step.title} style={{
                                border: '1px solid var(--border-subtle)',
                                borderRadius: 'var(--radius)',
                                padding: '0.85rem',
                                background: idx === 1 ? 'rgba(59, 130, 246, 0.06)' : 'var(--background-raised)',
                            }}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: '0.55rem', marginBottom: '0.35rem' }}>
                                    <StepIcon size={16} color={idx === 1 ? 'var(--primary)' : 'var(--text-secondary)'} />
                                    <strong style={{ fontSize: '0.85rem' }}>{step.title}</strong>
                                </div>
                                <p style={{ color: 'var(--text-secondary)', fontSize: '0.78rem', lineHeight: 1.45 }}>{step.text}</p>
                            </div>
                        );
                    })}
                </div>
            </section>

            <section style={cardStyle}>
                <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: '1rem', marginBottom: '1rem' }}>
                    <div>
                        <h4 style={{ fontWeight: 650, marginBottom: '0.35rem' }}>1. Choose database and start review</h4>
                        <p style={{ color: 'var(--text-secondary)', fontSize: '0.85rem', lineHeight: 1.5 }}>
                            The AI review explains what may break data quality or slow future queries. It does not edit schema or data.
                        </p>
                    </div>
                    {analyzeJobStatus && (
                        <StatusBadge status={analyzeJobStatus.error ? 'failed' : analyzeJobStatus.status} />
                    )}
                </div>

                <div style={{ display: 'flex', gap: '1rem', alignItems: 'flex-end', flexWrap: 'wrap' }}>
                    <div style={{ flex: '1 1 360px' }}>
                        <label style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '4px', display: 'block' }}>Database connection</label>
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
                            minHeight: '40px',
                            cursor: isAnalyzing || !analyzerConnId ? 'not-allowed' : 'pointer',
                            background: isAnalyzing || !analyzerConnId ? 'var(--border)' : 'var(--primary)',
                        }}
                    >
                        {isAnalyzing ? <Loader2 size={16} style={{ animation: 'spin 1s linear infinite' }} /> : <Search size={16} />}
                        {isAnalyzing ? 'Reviewing...' : 'Start AI Review'}
                    </button>
                </div>

                <div style={{
                    marginTop: '1rem',
                    border: `1px solid ${analyzeJobStatus?.error ? 'var(--danger)' : 'var(--border-subtle)'}`,
                    borderLeft: `3px solid ${analyzeJobStatus?.error ? 'var(--danger)' : statusColorFn(analyzeJobStatus?.status || 'pending')}`,
                    borderRadius: 'var(--radius)',
                    padding: '0.85rem 1rem',
                    background: 'var(--background-raised)',
                }}>
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '1rem', flexWrap: 'wrap' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.65rem' }}>
                            {isAnalyzing ? <Loader2 size={16} style={{ animation: 'spin 1s linear infinite', color: 'var(--primary)' }} /> : <CheckCircle2 size={16} color={completedAnalysis ? 'var(--success)' : 'var(--text-secondary)'} />}
                            <span style={{ fontSize: '0.85rem', color: analyzeJobStatus?.error ? 'var(--danger)' : 'var(--text-secondary)' }}>
                                {analyzeJobStatus?.error || analysisMessage}
                            </span>
                        </div>
                        {selectedConnection && (
                            <span style={{ fontSize: '0.78rem', color: 'var(--text-tertiary)' }}>
                                {selectedConnection.name} - {selectedConnection.schema_name || 'public'}
                            </span>
                        )}
                    </div>
                </div>
            </section>

            {completedAnalysis && (
                <section style={cardStyle}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', gap: '1rem', alignItems: 'flex-start', marginBottom: '1rem', flexWrap: 'wrap' }}>
                        <div>
                            <h4 style={{ fontWeight: 650, marginBottom: '0.35rem' }}>2. Review AI findings</h4>
                            <p style={{ color: 'var(--text-secondary)', fontSize: '0.85rem', lineHeight: 1.5 }}>
                                These findings are AI-generated recommendations based on database structure. Review them before creating checks.
                            </p>
                        </div>
                        <div style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap' }}>
                            <div style={{ minWidth: '96px' }}>
                                <div style={{ color: healthColor, fontSize: '1.35rem', fontWeight: 750 }}>
                                    {analysisHealthScore != null ? analysisHealthScore : '-'}
                                </div>
                                <div style={{ color: 'var(--text-tertiary)', fontSize: '0.72rem', textTransform: 'uppercase' }}>
                                    AI health score
                                </div>
                            </div>
                            <div style={{ minWidth: '96px' }}>
                                <div style={{ color: 'var(--text)', fontSize: '1.35rem', fontWeight: 750 }}>
                                    {tablesFound != null ? tablesFound : '-'}
                                </div>
                                <div style={{ color: 'var(--text-tertiary)', fontSize: '0.72rem', textTransform: 'uppercase' }}>
                                    Tables read
                                </div>
                            </div>
                            <div style={{ minWidth: '96px' }}>
                                <div style={{ color: schemaFindings.length > 0 ? 'var(--warning)' : 'var(--success)', fontSize: '1.35rem', fontWeight: 750 }}>
                                    {schemaFindings.length}
                                </div>
                                <div style={{ color: 'var(--text-tertiary)', fontSize: '0.72rem', textTransform: 'uppercase' }}>
                                    Findings
                                </div>
                            </div>
                        </div>
                    </div>

                    {analysisSummary && (
                        <p style={{
                            border: '1px solid var(--border-subtle)',
                            borderRadius: 'var(--radius)',
                            padding: '0.85rem 1rem',
                            color: 'var(--text-secondary)',
                            fontSize: '0.85rem',
                            lineHeight: 1.55,
                            marginBottom: '1rem',
                            background: 'var(--background-raised)',
                        }}>
                            {analysisSummary}
                        </p>
                    )}

                    {schemaFindings.length > 0 && (
                        <div style={{ display: 'flex', gap: '0.6rem', flexWrap: 'wrap', marginBottom: '1rem' }}>
                            {Object.entries(severityCounts).map(([severity, count]) => (
                                count > 0 ? (
                                    <span key={severity} style={{
                                        display: 'inline-flex', alignItems: 'center', gap: '0.35rem',
                                        borderRadius: '999px', padding: '0.25rem 0.6rem',
                                        background: severityBg(severity), color: severityColor(severity),
                                        fontSize: '0.76rem', fontWeight: 650, textTransform: 'capitalize',
                                    }}>
                                        {severity} {count}
                                    </span>
                                ) : null
                            ))}
                        </div>
                    )}

                    {schemaFindings.length === 0 ? (
                        <div style={{
                            border: '1px solid var(--border-subtle)',
                            borderRadius: 'var(--radius)',
                            padding: '1rem',
                            background: 'rgba(52, 211, 153, 0.08)',
                            display: 'flex',
                            gap: '0.75rem',
                            alignItems: 'flex-start',
                        }}>
                            <CheckCircle2 size={18} color="var(--success)" />
                            <div>
                                <strong style={{ fontSize: '0.9rem' }}>No major database risks found.</strong>
                                <p style={{ color: 'var(--text-secondary)', fontSize: '0.82rem', marginTop: '0.25rem', lineHeight: 1.45 }}>
                                    You can still generate checks for ongoing monitoring and regression coverage.
                                </p>
                            </div>
                        </div>
                    ) : (
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.65rem' }}>
                            {schemaFindings.map((finding, idx) => (
                                <div key={`${finding.title}-${idx}`} style={{
                                    border: '1px solid var(--border)',
                                    borderRadius: 'var(--radius)',
                                    borderLeft: `3px solid ${severityColor(finding.severity)}`,
                                    overflow: 'hidden',
                                }}>
                                    <button type="button" onClick={() => setExpandedFindingIdx(expandedFindingIdx === idx ? null : idx)}
                                        style={{
                                            width: '100%',
                                            padding: '0.85rem 1rem',
                                            cursor: 'pointer',
                                            display: 'flex',
                                            alignItems: 'center',
                                            gap: '0.75rem',
                                            border: 'none',
                                            background: expandedFindingIdx === idx ? 'rgba(59, 130, 246, 0.05)' : 'transparent',
                                            color: 'var(--text)',
                                            textAlign: 'left',
                                        }}>
                                        {expandedFindingIdx === idx ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                                        <SeverityBadge severity={finding.severity} />
                                        <span style={{ flex: 1, fontSize: '0.9rem', fontWeight: 600 }}>{finding.title}</span>
                                        {finding.category && (
                                            <span style={{
                                                fontSize: '0.7rem', padding: '2px 7px', borderRadius: '999px',
                                                background: 'rgba(99, 102, 241, 0.1)', color: 'var(--accent)',
                                            }}>
                                                {finding.category.replaceAll('_', ' ')}
                                            </span>
                                        )}
                                        {finding.table_name && (
                                            <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', whiteSpace: 'nowrap' }}>
                                                {finding.table_name}{finding.column_name ? `.${finding.column_name}` : ''}
                                            </span>
                                        )}
                                    </button>
                                    {expandedFindingIdx === idx && (
                                        <div style={{ padding: '1rem', borderTop: '1px solid var(--border)', fontSize: '0.85rem' }}>
                                            <div style={{ marginBottom: '0.75rem' }}>
                                                <strong>Why it matters</strong>
                                                <p style={{ marginTop: '0.25rem', color: 'var(--text-secondary)', lineHeight: 1.5 }}>{finding.description}</p>
                                            </div>
                                            {finding.recommendation && (
                                                <div>
                                                    <strong>Recommended fix</strong>
                                                    <p style={{ color: 'var(--text-secondary)', marginTop: '0.25rem', lineHeight: 1.5 }}>{finding.recommendation}</p>
                                                </div>
                                            )}
                                        </div>
                                    )}
                                </div>
                            ))}
                        </div>
                    )}

                    <div style={{ marginTop: '1.25rem' }}>
                        <button
                            onClick={generateSuggestions}
                            disabled={isGeneratingSuggestions || !analyzeRunId}
                            style={{
                                ...btnPrimary,
                                cursor: isGeneratingSuggestions || !analyzeRunId ? 'not-allowed' : 'pointer',
                                background: isGeneratingSuggestions || !analyzeRunId ? 'var(--border)' : 'var(--primary)',
                            }}
                        >
                            {isGeneratingSuggestions
                                ? <Loader2 size={16} style={{ animation: 'spin 1s linear infinite' }} />
                                : <Wand2 size={16} />}
                            {isGeneratingSuggestions ? 'Generating checks...' : 'Generate Checks from Findings'}
                        </button>
                    </div>
                </section>
            )}

            {suggestions.length > 0 && (
                <section style={cardStyle}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '1rem', marginBottom: '1rem', flexWrap: 'wrap' }}>
                        <div>
                            <h4 style={{ fontWeight: 650, marginBottom: '0.35rem' }}>3. Save suggested database checks</h4>
                            <p style={{ color: 'var(--text-secondary)', fontSize: '0.85rem', lineHeight: 1.5 }}>
                                Select the checks you want to keep. Saved checks become runnable database test specs.
                            </p>
                        </div>
                        <button
                            onClick={saveSuggestionsAsSpec}
                            disabled={savingSpec || selectedSuggestionsCount === 0}
                            style={{
                                ...btnPrimary,
                                fontSize: '0.8rem',
                                cursor: savingSpec || selectedSuggestionsCount === 0 ? 'not-allowed' : 'pointer',
                                background: savingSpec || selectedSuggestionsCount === 0 ? 'var(--border)' : 'var(--primary)',
                            }}
                        >
                            {savingSpec ? <Loader2 size={14} style={{ animation: 'spin 1s linear infinite' }} /> : <Save size={14} />}
                            Save Selected Checks ({selectedSuggestionsCount})
                        </button>
                    </div>

                    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.65rem' }}>
                        {suggestions.map((sugg, idx) => (
                            <div key={`${sugg.check_name}-${idx}`} style={{
                                border: '1px solid var(--border)',
                                borderRadius: 'var(--radius)',
                                padding: '0.85rem 1rem',
                                display: 'flex',
                                alignItems: 'flex-start',
                                gap: '0.75rem',
                                background: sugg.approved ? 'rgba(59, 130, 246, 0.04)' : 'transparent',
                            }}>
                                <input
                                    aria-label={`Select ${sugg.check_name}`}
                                    type="checkbox"
                                    checked={Boolean(sugg.approved)}
                                    onChange={() => toggleSuggestion(idx)}
                                    style={{ marginTop: '3px', flexShrink: 0 }}
                                />
                                <div style={{ flex: 1, minWidth: 0 }}>
                                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '4px', flexWrap: 'wrap' }}>
                                        <SeverityBadge severity={sugg.severity} />
                                        <span style={{ fontWeight: 600, fontSize: '0.9rem' }}>{sugg.check_name}</span>
                                    </div>
                                    <p style={{ fontSize: '0.82rem', color: 'var(--text-secondary)', marginBottom: '0.45rem', lineHeight: 1.45 }}>
                                        {sugg.description}
                                    </p>
                                    <div style={{ fontSize: '0.76rem', color: 'var(--text-secondary)', display: 'flex', gap: '0.85rem', flexWrap: 'wrap' }}>
                                        <span>Table: <strong>{sugg.table_name}</strong></span>
                                        {sugg.column_name && <span>Column: <strong>{sugg.column_name}</strong></span>}
                                        <span>Type: {sugg.check_type}</span>
                                    </div>
                                    <button
                                        type="button"
                                        onClick={() => setExpandedSqlIdx(expandedSqlIdx === idx ? null : idx)}
                                        style={{ ...btnSecondary, marginTop: '0.65rem', padding: '0.35rem 0.65rem', fontSize: '0.76rem' }}
                                    >
                                        <Code2 size={14} />
                                        {expandedSqlIdx === idx ? 'Hide SQL' : 'View SQL'}
                                    </button>
                                    {expandedSqlIdx === idx && (
                                        <pre style={{
                                            background: 'var(--bg)',
                                            padding: '0.65rem 0.75rem',
                                            borderRadius: '4px',
                                            fontSize: '0.75rem',
                                            marginTop: '0.5rem',
                                            overflow: 'auto',
                                            maxHeight: '140px',
                                        }}>
                                            {sugg.sql_query}
                                        </pre>
                                    )}
                                </div>
                            </div>
                        ))}
                    </div>
                </section>
            )}
        </div>
    );
}
