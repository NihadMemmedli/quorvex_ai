'use client';
import React from 'react';
import { Sparkles, Loader2, AlertTriangle, Target, TrendingUp, Gauge } from 'lucide-react';
import type { LoadTestAnalysis } from './types';

interface AIAnalysisViewProps {
    analysis?: LoadTestAnalysis;
    onAnalyze: () => void;
    analyzing: boolean;
    runStatus: string;
}

const GRADE_COLORS: Record<string, string> = {
    A: 'var(--success)', B: 'var(--primary)', C: 'var(--warning)', D: 'var(--warning)', F: 'var(--danger)',
};

const SEVERITY_STYLE: Record<string, { bg: string; color: string }> = {
    critical: { bg: 'rgba(220, 38, 38, 0.1)', color: 'var(--danger)' },
    high: { bg: 'var(--danger-muted)', color: 'var(--danger)' },
    medium: { bg: 'var(--warning-muted)', color: 'var(--warning)' },
    low: { bg: 'var(--primary-glow)', color: 'var(--primary)' },
};

function Badge({ label, style: s }: { label: string; style: { bg: string; color: string } }) {
    return (
        <span style={{
            padding: '0.15rem 0.5rem', borderRadius: '999px', fontSize: '0.65rem',
            fontWeight: 600, background: s.bg, color: s.color,
            textTransform: 'uppercase', letterSpacing: '0.03em',
        }}>
            {label}
        </span>
    );
}

export default function AIAnalysisView({ analysis, onAnalyze, analyzing, runStatus }: AIAnalysisViewProps) {
    if (!analysis) {
        return (
            <div style={{
                marginTop: '1.5rem', padding: '1.5rem',
                background: 'var(--surface)', border: '1px solid var(--border)',
                borderRadius: 'var(--radius)', textAlign: 'center',
            }}>
                {analyzing ? (
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '0.75rem', color: 'var(--text-secondary)' }}>
                        <Loader2 size={20} style={{ animation: 'spin 1s linear infinite' }} />
                        <span style={{ fontSize: '0.875rem' }}>Analyzing performance data with AI...</span>
                    </div>
                ) : runStatus === 'completed' ? (
                    <>
                        <p style={{ color: 'var(--text-secondary)', fontSize: '0.875rem', marginBottom: '0.75rem' }}>
                            Get AI-powered insights on performance bottlenecks and optimization recommendations.
                        </p>
                        <button
                            onClick={onAnalyze}
                            style={{
                                display: 'inline-flex', alignItems: 'center', gap: '0.5rem',
                                padding: '0.5rem 1rem', background: 'linear-gradient(135deg, #8B5CF6, #6366F1)',
                                color: 'white', border: 'none', borderRadius: 'var(--radius)',
                                cursor: 'pointer', fontWeight: 600, fontSize: '0.85rem',
                            }}
                        >
                            <Sparkles size={16} /> Analyze with AI
                        </button>
                    </>
                ) : (
                    <p style={{ color: 'var(--text-secondary)', fontSize: '0.85rem' }}>
                        AI analysis is available after the run completes.
                    </p>
                )}
            </div>
        );
    }

    const gradeColor = GRADE_COLORS[analysis.performance_grade] || 'var(--text-secondary)';

    return (
        <div style={{ marginTop: '1.5rem' }}>
            <h4 style={{ fontSize: '0.9rem', fontWeight: 600, marginBottom: '1rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <Sparkles size={16} style={{ color: 'var(--accent)' }} />
                AI Performance Analysis
            </h4>

            {/* Performance Grade + Summary */}
            <div style={{
                display: 'flex', gap: '1rem', marginBottom: '1rem',
            }}>
                <div style={{
                    display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
                    padding: '1.25rem 1.5rem',
                    background: 'var(--surface)', border: '1px solid var(--border)',
                    borderRadius: 'var(--radius)', minWidth: '100px',
                }}>
                    <div style={{ fontSize: '0.7rem', color: 'var(--text-tertiary)', marginBottom: '0.4rem', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                        Grade
                    </div>
                    <div style={{
                        fontSize: '2.5rem', fontWeight: 800, color: gradeColor,
                        lineHeight: 1,
                    }}>
                        {analysis.performance_grade}
                    </div>
                </div>
                <div style={{
                    flex: 1, padding: '1rem',
                    background: 'var(--surface)', border: '1px solid var(--border)',
                    borderRadius: 'var(--radius)',
                }}>
                    <p style={{ fontSize: '0.85rem', color: 'var(--text-primary)', lineHeight: 1.6, margin: 0 }}>
                        {analysis.summary}
                    </p>
                </div>
            </div>

            {/* Bottlenecks */}
            {analysis.bottlenecks && analysis.bottlenecks.length > 0 && (
                <div style={{
                    padding: '1rem', background: 'var(--surface)',
                    border: '1px solid var(--border)', borderRadius: 'var(--radius)',
                    marginBottom: '1rem',
                }}>
                    <h5 style={{ fontSize: '0.85rem', fontWeight: 600, marginBottom: '0.75rem', display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                        <AlertTriangle size={14} style={{ color: 'var(--warning)' }} />
                        Bottlenecks ({analysis.bottlenecks.length})
                    </h5>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.6rem' }}>
                        {analysis.bottlenecks.map((b, i) => {
                            const sev = SEVERITY_STYLE[b.severity] || SEVERITY_STYLE.medium;
                            return (
                                <div key={i} style={{
                                    padding: '0.75rem', background: 'rgba(0,0,0,0.02)',
                                    border: '1px solid var(--border)', borderRadius: 'var(--radius)',
                                }}>
                                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.35rem' }}>
                                        <Badge label={b.severity} style={sev} />
                                        <span style={{ fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-primary)' }}>
                                            {b.area}
                                        </span>
                                    </div>
                                    <p style={{ fontSize: '0.78rem', color: 'var(--text-secondary)', margin: '0 0 0.3rem', lineHeight: 1.5 }}>
                                        {b.issue}
                                    </p>
                                    {b.recommendation && (
                                        <p style={{ fontSize: '0.75rem', color: 'var(--success)', margin: 0, lineHeight: 1.4 }}>
                                            Fix: {b.recommendation}
                                        </p>
                                    )}
                                </div>
                            );
                        })}
                    </div>
                </div>
            )}

            {/* Anomalies */}
            {analysis.anomalies && analysis.anomalies.length > 0 && (
                <div style={{
                    padding: '1rem', background: 'var(--surface)',
                    border: '1px solid var(--border)', borderRadius: 'var(--radius)',
                    marginBottom: '1rem',
                }}>
                    <h5 style={{ fontSize: '0.85rem', fontWeight: 600, marginBottom: '0.75rem', display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                        <TrendingUp size={14} style={{ color: 'var(--warning)' }} />
                        Anomalies ({analysis.anomalies.length})
                    </h5>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.6rem' }}>
                        {analysis.anomalies.map((a, i) => (
                            <div key={i} style={{
                                padding: '0.75rem', background: 'rgba(0,0,0,0.02)',
                                border: '1px solid var(--border)', borderRadius: 'var(--radius)',
                            }}>
                                <div style={{ fontSize: '0.8rem', fontWeight: 600, marginBottom: '0.25rem', color: 'var(--text-primary)' }}>
                                    {a.metric}
                                </div>
                                <p style={{ fontSize: '0.78rem', color: 'var(--text-secondary)', margin: '0 0 0.2rem', lineHeight: 1.5 }}>
                                    {a.observation}
                                </p>
                                <p style={{ fontSize: '0.75rem', color: 'var(--warning)', margin: 0, lineHeight: 1.4 }}>
                                    Possible cause: {a.possible_cause}
                                </p>
                            </div>
                        ))}
                    </div>
                </div>
            )}

            {/* Recommendations */}
            {analysis.recommendations && analysis.recommendations.length > 0 && (
                <div style={{
                    padding: '1rem', background: 'var(--surface)',
                    border: '1px solid var(--border)', borderRadius: 'var(--radius)',
                    marginBottom: '1rem',
                }}>
                    <h5 style={{ fontSize: '0.85rem', fontWeight: 600, marginBottom: '0.75rem', display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                        <Target size={14} style={{ color: 'var(--success)' }} />
                        Recommendations ({analysis.recommendations.length})
                    </h5>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.6rem' }}>
                        {analysis.recommendations.map((r, i) => (
                            <div key={i} style={{
                                padding: '0.75rem', background: 'rgba(0,0,0,0.02)',
                                border: '1px solid var(--border)', borderRadius: 'var(--radius)',
                            }}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.3rem' }}>
                                    <span style={{
                                        display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                                        width: '20px', height: '20px', borderRadius: '50%',
                                        background: 'rgba(192, 132, 252, 0.12)', color: 'var(--accent)',
                                        fontSize: '0.7rem', fontWeight: 700,
                                    }}>
                                        {typeof r.priority === 'number' ? r.priority : i + 1}
                                    </span>
                                    <span style={{ fontSize: '0.8rem', fontWeight: 600 }}>{r.title}</span>
                                </div>
                                <p style={{ fontSize: '0.78rem', color: 'var(--text-secondary)', margin: '0 0 0.2rem', lineHeight: 1.5 }}>
                                    {r.description}
                                </p>
                                {r.expected_impact && (
                                    <p style={{ fontSize: '0.75rem', color: 'var(--primary)', margin: 0, lineHeight: 1.4 }}>
                                        Expected impact: {r.expected_impact}
                                    </p>
                                )}
                            </div>
                        ))}
                    </div>
                </div>
            )}

            {/* Capacity Estimate */}
            {analysis.capacity_estimate && analysis.capacity_estimate.current_max_rps > 0 && (
                <div style={{
                    padding: '1rem', background: 'var(--surface)',
                    border: '1px solid var(--border)', borderRadius: 'var(--radius)',
                }}>
                    <h5 style={{ fontSize: '0.85rem', fontWeight: 600, marginBottom: '0.75rem', display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                        <Gauge size={14} style={{ color: 'var(--accent)' }} />
                        Capacity Estimate
                    </h5>
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '0.75rem' }}>
                        <div style={{
                            padding: '0.75rem', background: 'rgba(0,0,0,0.02)',
                            border: '1px solid var(--border)', borderRadius: 'var(--radius)', textAlign: 'center',
                        }}>
                            <div style={{ fontSize: '0.7rem', color: 'var(--text-secondary)', marginBottom: '0.3rem' }}>Current Max RPS</div>
                            <div style={{ fontSize: '1.25rem', fontWeight: 700, color: 'var(--success)' }}>
                                {analysis.capacity_estimate.current_max_rps.toLocaleString()}
                            </div>
                        </div>
                        <div style={{
                            padding: '0.75rem', background: 'rgba(0,0,0,0.02)',
                            border: '1px solid var(--border)', borderRadius: 'var(--radius)', textAlign: 'center',
                        }}>
                            <div style={{ fontSize: '0.7rem', color: 'var(--text-secondary)', marginBottom: '0.3rem' }}>Est. Breaking Point</div>
                            <div style={{ fontSize: '1.25rem', fontWeight: 700, color: 'var(--warning)' }}>
                                {analysis.capacity_estimate.estimated_breaking_point_vus.toLocaleString()} VUs
                            </div>
                        </div>
                        <div style={{
                            padding: '0.75rem', background: 'rgba(0,0,0,0.02)',
                            border: '1px solid var(--border)', borderRadius: 'var(--radius)', textAlign: 'center',
                        }}>
                            <div style={{ fontSize: '0.7rem', color: 'var(--text-secondary)', marginBottom: '0.3rem' }}>Confidence</div>
                            <div style={{
                                fontSize: '1rem', fontWeight: 600, textTransform: 'capitalize',
                                color: analysis.capacity_estimate.confidence === 'high' ? 'var(--success)'
                                    : analysis.capacity_estimate.confidence === 'medium' ? 'var(--warning)'
                                    : 'var(--danger)',
                            }}>
                                {analysis.capacity_estimate.confidence}
                            </div>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
}
