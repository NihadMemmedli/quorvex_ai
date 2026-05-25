'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import {
    Rocket, Play, Pause, Square, Clock, Globe, FileText, CheckCircle2,
    AlertTriangle, Loader2, ChevronRight, ArrowLeft, RefreshCw,
    MessageCircle, Zap, BarChart2, Target, List, Monitor, Image as ImageIcon,
    Activity, ExternalLink
} from 'lucide-react';
import { useProject } from '@/contexts/ProjectContext';
import { API_BASE } from '@/lib/api';
import { toast } from 'sonner';
import { PageLayout } from '@/components/ui/page-layout';
import { EmptyState } from '@/components/ui/empty-state';
import { ListPageSkeleton } from '@/components/ui/page-skeleton';
import { LiveBrowserView } from '@/components/LiveBrowserView';

// ============ TYPES ============

interface AutoPilotSession {
    id: string;
    project_id: string | null;
    entry_urls: string[];
    status: string;
    current_phase: string | null;
    current_phase_progress: number;
    overall_progress: number;
    phases_completed: string[];
    total_pages_discovered: number;
    total_flows_discovered: number;
    total_requirements_generated: number;
    total_specs_generated: number;
    total_tests_generated: number;
    total_tests_passed: number;
    total_tests_failed: number;
    coverage_percentage: number;
    error_message: string | null;
    created_at: string;
    started_at: string | null;
    completed_at: string | null;
    instructions: string | null;
    config: Record<string, any>;
    can_resume: boolean;
    resume_reason: string | null;
    failed_phase: string | null;
}

interface Phase {
    id: number;
    session_id: string;
    phase_name: string;
    phase_order: number;
    status: string;
    progress: number;
    current_step: string | null;
    items_total: number;
    items_completed: number;
    result_summary: Record<string, any>;
    error_message: string | null;
    started_at: string | null;
    completed_at: string | null;
}

interface Question {
    id: number;
    session_id: string;
    phase_name: string;
    question_type: string;
    question_text: string;
    context: Record<string, any>;
    suggested_answers: string[];
    default_answer: string | null;
    status: string;
    answer_text: string | null;
    answered_at: string | null;
    auto_continue_at: string | null;
    created_at: string;
}

interface SpecTask {
    id: number;
    session_id: string;
    requirement_id: number | null;
    requirement_title: string | null;
    priority: string;
    status: string;
    spec_name: string | null;
    spec_path: string | null;
    error_message: string | null;
    created_at: string;
    completed_at: string | null;
}

interface TestTask {
    id: number;
    session_id: string;
    spec_task_id: number | null;
    spec_name: string | null;
    spec_path: string | null;
    run_id: string | null;
    status: string;
    current_stage: string | null;
    generation_mode: string | null;
    healing_attempt: number;
    test_path: string | null;
    passed: boolean | null;
    error_summary: string | null;
    artifact_count: number;
    log_available: boolean;
    created_at: string;
    started_at: string | null;
    completed_at: string | null;
}

interface TestTaskArtifact {
    name: string;
    path: string;
    type: string;
}

interface TestTaskDetail extends TestTask {
    run_dir: string | null;
    pipeline_error: Record<string, any> | null;
    agentic_summary: Record<string, any> | null;
    validation: Record<string, any> | null;
    artifacts: TestTaskArtifact[];
    report_url: string | null;
    log_excerpt: string | null;
}

interface AutoPilotLiveArtifact {
    name: string;
    path: string;
    type: string;
    modified_at: string | null;
}

interface AutoPilotLiveState {
    active: boolean;
    phase: string | null;
    activity_label: string | null;
    status: string | null;
    message: string | null;
    exploration_session_id: string | null;
    test_task_id: number | null;
    run_id: string | null;
    spec_name: string | null;
    current_stage: string | null;
    agent_task_id: string | null;
    last_tool: string | null;
    last_tool_label: string | null;
    tool_calls: number;
    browser_tool_calls: number;
    interactions: number;
    recent_tools: Array<{ name?: string; label?: string; at?: string }>;
    artifacts: AutoPilotLiveArtifact[];
    latest_image: AutoPilotLiveArtifact | null;
    updated_at: string | null;
}

// ============ STATUS COLORS ============

const dark = {
    canvas: '#0f1629',
    panel: '#151d30',
    panelAlt: '#0b1020',
    panelHover: '#1e2a42',
    border: '#1e2a42',
    borderStrong: '#2a3a58',
    text: '#f0f4fc',
    textSecondary: '#c7d2e8',
    textMuted: '#8d9ab8',
    textFaint: '#5f6d8f',
    neutralSoft: 'rgba(126, 139, 168, 0.12)',
    primary: '#3b82f6',
    primarySoft: 'rgba(59, 130, 246, 0.14)',
    primaryBorder: 'rgba(59, 130, 246, 0.32)',
    success: '#34d399',
    successSoft: 'rgba(52, 211, 153, 0.13)',
    warning: '#fbbf24',
    warningSoft: 'rgba(251, 191, 36, 0.12)',
    warningBorder: 'rgba(251, 191, 36, 0.32)',
    danger: '#f87171',
    dangerSoft: 'rgba(248, 113, 113, 0.12)',
    dangerBorder: 'rgba(248, 113, 113, 0.3)',
    dangerHover: 'rgba(248, 113, 113, 0.2)',
    violet: '#c084fc',
    cyan: '#22d3ee',
};

const statusColors: Record<string, { bg: string; color: string }> = {
    pending: { bg: dark.neutralSoft, color: dark.textMuted },
    running: { bg: dark.primarySoft, color: dark.primary },
    generating: { bg: dark.primarySoft, color: dark.primary },
    completed: { bg: dark.successSoft, color: dark.success },
    passed: { bg: dark.successSoft, color: dark.success },
    failed: { bg: dark.dangerSoft, color: dark.danger },
    error: { bg: dark.dangerSoft, color: dark.danger },
    skipped: { bg: dark.warningSoft, color: dark.warning },
    awaiting_input: { bg: dark.warningSoft, color: dark.warning },
    paused: { bg: dark.warningSoft, color: dark.warning },
    cancelled: { bg: dark.neutralSoft, color: dark.textMuted },
};

const PHASE_ORDER = ['exploration', 'requirements', 'test_ideas', 'spec_generation', 'test_generation', 'reporting'];
const PHASE_LABELS: Record<string, string> = {
    exploration: 'Exploration',
    requirements: 'Requirements',
    test_ideas: 'Test Ideas',
    spec_generation: 'Spec Generation',
    test_generation: 'Test Generation',
    reporting: 'Reporting',
};
const PHASE_ICONS: Record<string, typeof Globe> = {
    exploration: Globe,
    requirements: FileText,
    test_ideas: Target,
    spec_generation: List,
    test_generation: Zap,
    reporting: BarChart2,
};

// ============ HELPER FUNCTIONS ============

function formatTimeAgo(dateStr: string | null): string {
    if (!dateStr) return '-';
    const date = new Date(dateStr.endsWith('Z') ? dateStr : dateStr + 'Z');
    const now = new Date();
    const diff = Math.floor((now.getTime() - date.getTime()) / 1000);
    if (diff < 0) return 'just now';
    if (diff < 60) return 'just now';
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
    return `${Math.floor(diff / 86400)}d ago`;
}

function formatDuration(startStr: string | null, endStr: string | null): string {
    if (!startStr) return '-';
    const start = new Date(startStr.endsWith('Z') ? startStr : startStr + 'Z');
    const end = endStr ? new Date(endStr.endsWith('Z') ? endStr : endStr + 'Z') : new Date();
    const seconds = Math.floor((end.getTime() - start.getTime()) / 1000);
    if (seconds < 60) return `${seconds}s`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
    return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;
}

function getStatusStyle(status: string): { bg: string; color: string } {
    return statusColors[status] || statusColors.pending;
}

function progressPercent(value: number | null | undefined): number {
    const numeric = typeof value === 'number' && Number.isFinite(value) ? value : 0;
    return Math.max(0, Math.min(100, numeric <= 1 ? numeric * 100 : numeric));
}

function formatTime(dateStr: string | null | undefined): string {
    if (!dateStr) return '-';
    const date = new Date(dateStr.endsWith('Z') ? dateStr : `${dateStr}Z`);
    if (Number.isNaN(date.getTime())) return '-';
    return date.toLocaleTimeString();
}

async function fetchJsonWithTimeout<T>(url: string, timeoutMs = 15000): Promise<T> {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), timeoutMs);
    try {
        const res = await fetch(url, { signal: controller.signal });
        if (!res.ok) {
            let detail = `${res.status} ${res.statusText}`;
            try {
                const data = await res.json();
                detail = data.detail || data.error || detail;
            } catch {
                // Keep HTTP status when the body is not JSON.
            }
            throw new Error(detail);
        }
        return await res.json();
    } catch (err) {
        if (err instanceof DOMException && err.name === 'AbortError') {
            throw new Error('Request timed out. The backend may be busy with an Auto Pilot or agent task.');
        }
        throw err;
    } finally {
        clearTimeout(timeout);
    }
}

function isFailedTestTask(task: TestTask): boolean {
    return task.passed === false || task.status === 'failed' || task.status === 'error';
}

function taskFailureReason(task: TestTask): string {
    if (isFailedTestTask(task)) {
        return task.error_summary || 'No failure reason reported';
    }
    if (task.status === 'paused') {
        return task.error_summary || 'Paused by user';
    }
    return '-';
}

// ============ INLINE STYLE CONSTANTS ============

const cardStyle: React.CSSProperties = {
    background: dark.panel,
    border: `1px solid ${dark.border}`,
    borderRadius: '8px',
    padding: '1.25rem',
    boxShadow: '0 12px 28px rgba(0, 0, 0, 0.18)',
};

const inputStyle: React.CSSProperties = {
    width: '100%',
    minHeight: '40px',
    padding: '0.6rem 0.75rem',
    borderRadius: '8px',
    fontSize: '0.875rem',
    border: `1px solid ${dark.borderStrong}`,
    background: dark.panelAlt,
    color: dark.text,
    outline: 'none',
    transition: 'border-color 0.15s, box-shadow 0.15s',
};

const labelStyle: React.CSSProperties = {
    display: 'block',
    fontSize: '0.8rem',
    fontWeight: 600,
    marginBottom: '0.4rem',
    color: dark.textSecondary,
};

const selectStyle: React.CSSProperties = {
    ...inputStyle,
    appearance: 'none' as const,
    backgroundImage: `url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%238d9ab8' stroke-width='2'%3E%3Cpolyline points='6 9 12 15 18 9'/%3E%3C/svg%3E")`,
    backgroundRepeat: 'no-repeat',
    backgroundPosition: 'right 0.75rem center',
    paddingRight: '2rem',
};

const workspaceStyle: React.CSSProperties = {
    background: dark.canvas,
    color: dark.text,
    border: `1px solid ${dark.border}`,
    borderRadius: '8px',
    padding: '1.25rem',
    minHeight: 'calc(100vh - 5rem)',
};

const buttonBaseStyle: React.CSSProperties = {
    minHeight: '40px',
    display: 'inline-flex',
    alignItems: 'center',
    justifyContent: 'center',
    gap: '0.45rem',
    padding: '0.55rem 0.95rem',
    borderRadius: '8px',
    fontWeight: 700,
    fontSize: '0.85rem',
    transition: 'background-color 0.15s, border-color 0.15s, color 0.15s, box-shadow 0.15s',
};

const secondaryButtonStyle: React.CSSProperties = {
    ...buttonBaseStyle,
    background: dark.panelAlt,
    color: dark.textSecondary,
    border: `1px solid ${dark.borderStrong}`,
};

const primaryButtonStyle: React.CSSProperties = {
    ...buttonBaseStyle,
    background: dark.primary,
    color: '#ffffff',
    border: `1px solid ${dark.primary}`,
    boxShadow: '0 10px 22px rgba(59, 130, 246, 0.24)',
};

const dangerButtonStyle: React.CSSProperties = {
    ...buttonBaseStyle,
    background: dark.dangerSoft,
    color: dark.danger,
    border: `1px solid ${dark.dangerBorder}`,
};

const tableHeaderStyle: React.CSSProperties = {
    padding: '0.65rem 1rem',
    textAlign: 'left',
    fontWeight: 700,
    color: dark.textMuted,
    fontSize: '0.7rem',
    textTransform: 'uppercase',
    letterSpacing: '0.04em',
};

const autoPilotStyles = `
    .autopilot-page button:focus-visible,
    .autopilot-page input:focus-visible,
    .autopilot-page textarea:focus-visible,
    .autopilot-page select:focus-visible {
        outline: 2px solid rgba(59, 130, 246, 0.45) !important;
        outline-offset: 2px;
    }

    .autopilot-page input:focus,
    .autopilot-page textarea:focus,
    .autopilot-page select:focus {
        border-color: ${dark.primary} !important;
        box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.18);
    }

    .autopilot-actions {
        display: flex;
        align-items: center;
        gap: 0.5rem;
        flex-wrap: wrap;
        justify-content: flex-end;
    }

    .autopilot-start-grid {
        display: grid;
        grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
        gap: 1rem;
    }

    .autopilot-stats-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(145px, 1fr));
        gap: 0.75rem;
        margin-bottom: 1rem;
    }

    .autopilot-statusbar {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
        gap: 0.75rem;
        margin-bottom: 1rem;
    }

    .autopilot-table-row:hover {
        background: ${dark.panelHover} !important;
    }

    @media (max-width: 900px) {
        .autopilot-start-grid,
        .autopilot-statusbar {
            grid-template-columns: 1fr;
        }

        .autopilot-page {
            padding: 1rem;
        }
    }

    @media (max-width: 640px) {
        .autopilot-header {
            flex-direction: column;
            align-items: stretch !important;
        }

        .autopilot-actions {
            justify-content: flex-start;
        }

        .autopilot-phase-track {
            overflow-x: auto;
            padding-bottom: 0.25rem;
        }

        .autopilot-phase-step {
            min-width: 116px;
        }
    }
`;

function AutoPilotHeader({
    title,
    subtitle,
    actions,
}: {
    title: string;
    subtitle: string;
    actions?: React.ReactNode;
}) {
    return (
        <header
            className="autopilot-header animate-in stagger-1"
            style={{
                display: 'flex',
                alignItems: 'flex-start',
                justifyContent: 'space-between',
                gap: '1rem',
                paddingBottom: '1.25rem',
                marginBottom: '1.25rem',
                borderBottom: `1px solid ${dark.border}`,
            }}
        >
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', minWidth: 0 }}>
                <div
                    style={{
                        width: '44px',
                        height: '44px',
                        borderRadius: '8px',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        background: dark.primarySoft,
                        color: dark.primary,
                        flexShrink: 0,
                    }}
                >
                    <Rocket size={22} />
                </div>
                <div style={{ minWidth: 0 }}>
                    <h1 style={{ fontSize: '1.75rem', lineHeight: 1.15, fontWeight: 800, margin: 0, color: dark.text }}>
                        {title}
                    </h1>
                    <p style={{ margin: '0.25rem 0 0', fontSize: '0.9rem', color: dark.textMuted }}>
                        {subtitle}
                    </p>
                </div>
            </div>
            {actions && <div className="autopilot-actions">{actions}</div>}
        </header>
    );
}

// ============ STATUS BADGE (stable component - defined outside to avoid remounts) ============

const StatusBadge = ({ status }: { status: string }) => {
    const style = getStatusStyle(status);
    const isPulsing = status === 'running' || status === 'generating';
    return (
        <span style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: '0.375rem',
            padding: '0.25rem 0.75rem',
            borderRadius: '9999px',
            fontSize: '0.75rem',
            fontWeight: 600,
            background: style.bg,
            color: style.color,
            textTransform: 'capitalize',
        }}>
            {isPulsing && (
                <Loader2 size={12} style={{ animation: 'spin 1s linear infinite' }} />
            )}
            {status.replace('_', ' ')}
        </span>
    );
};

interface TaskDetailDialogProps {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    selectedTask: TestTaskDetail | null;
    loading: boolean;
    error: string | null;
}

function TaskDetailDialog({
    open,
    onOpenChange,
    selectedTask,
    loading,
    error,
}: TaskDetailDialogProps) {
    if (!open) return null;

    return (
        <div
            role="presentation"
            onMouseDown={() => onOpenChange(false)}
            style={{
                position: 'fixed',
                inset: 0,
                zIndex: 10000,
                background: 'rgba(0, 0, 0, 0.82)',
                backdropFilter: 'blur(4px)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                padding: '1.5rem',
            }}
        >
            <div
                role="dialog"
                aria-modal="true"
                aria-labelledby="autopilot-task-detail-title"
                onMouseDown={(event) => event.stopPropagation()}
                style={{
                    width: 'min(56rem, 100%)',
                    maxHeight: '85vh',
                    overflowY: 'auto',
                    background: dark.panel,
                    border: `1px solid ${dark.borderStrong}`,
                    borderRadius: '8px',
                    boxShadow: '0 24px 80px rgba(0, 0, 0, 0.55)',
                    color: dark.text,
                    padding: '1.5rem',
                    position: 'relative',
                }}
            >
                <button
                    type="button"
                    onClick={() => onOpenChange(false)}
                    aria-label="Close task details"
                    style={{
                        position: 'absolute',
                        top: '0.85rem',
                        right: '0.85rem',
                        border: `1px solid ${dark.borderStrong}`,
                        background: dark.panelAlt,
                        color: dark.textSecondary,
                        borderRadius: '6px',
                        padding: '0.25rem 0.5rem',
                        fontSize: '0.75rem',
                        fontWeight: 700,
                        cursor: 'pointer',
                    }}
                >
                    Close
                </button>

                <div style={{ marginBottom: '1rem', paddingRight: '4rem' }}>
                    <h2
                        id="autopilot-task-detail-title"
                        style={{ color: dark.text, fontSize: '1.05rem', fontWeight: 800, margin: 0 }}
                    >
                        Test Task Details
                    </h2>
                    <div style={{ color: dark.textMuted, fontSize: '0.82rem', marginTop: '0.3rem' }}>
                        {selectedTask?.spec_name || 'Auto Pilot test generation task'}
                    </div>
                </div>

                {!selectedTask ? (
                    <div style={{ color: dark.textMuted, fontSize: '0.85rem' }}>No task selected.</div>
                ) : (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                        {error && (
                            <div style={{
                                border: `1px solid ${dark.dangerBorder}`,
                                borderRadius: '8px',
                                background: dark.dangerSoft,
                                color: dark.danger,
                                padding: '0.75rem',
                                fontSize: '0.82rem',
                                fontWeight: 600,
                            }}>
                                {error}
                            </div>
                        )}

                        <div style={{
                            display: 'grid',
                            gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))',
                            gap: '0.75rem',
                        }}>
                            {[
                                ['Status', <StatusBadge key="status" status={selectedTask.passed === true ? 'passed' : selectedTask.passed === false ? 'failed' : selectedTask.status} />],
                                ['Mode', selectedTask.generation_mode === 'conservative_smoke' ? 'Smoke' : selectedTask.generation_mode === 'native_e2e' ? 'Native E2E' : '-'],
                                ['Stage', selectedTask.current_stage?.replace('_', ' ') || '-'],
                                ['Healing', selectedTask.healing_attempt > 0 ? `${selectedTask.healing_attempt} attempt${selectedTask.healing_attempt > 1 ? 's' : ''}` : '-'],
                                ['Duration', formatDuration(selectedTask.started_at, selectedTask.completed_at)],
                            ].map(([label, value]) => (
                                <div key={String(label)} style={{
                                    border: `1px solid ${dark.border}`,
                                    borderRadius: '8px',
                                    padding: '0.75rem',
                                    background: dark.panelAlt,
                                }}>
                                    <div style={{
                                        color: dark.textMuted,
                                        fontSize: '0.68rem',
                                        fontWeight: 700,
                                        marginBottom: '0.35rem',
                                        textTransform: 'uppercase',
                                    }}>
                                        {label}
                                    </div>
                                    <div style={{ color: dark.textSecondary, fontSize: '0.82rem' }}>{value}</div>
                                </div>
                            ))}
                        </div>

                        <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
                            {selectedTask.run_id && (
                                <a href={`/runs/${encodeURIComponent(selectedTask.run_id)}`} style={secondaryButtonStyle}>
                                    <FileText size={14} />
                                    View Run
                                </a>
                            )}
                            {selectedTask.report_url && (
                                <a href={`${API_BASE}${selectedTask.report_url}`} target="_blank" rel="noreferrer" style={secondaryButtonStyle}>
                                    <FileText size={14} />
                                    Report
                                </a>
                            )}
                        </div>

                        <div>
                            <div style={{ color: dark.text, fontSize: '0.85rem', fontWeight: 700, marginBottom: '0.4rem' }}>
                                Reason
                            </div>
                            <pre style={{
                                whiteSpace: 'pre-wrap',
                                wordBreak: 'break-word',
                                margin: 0,
                                border: `1px solid ${dark.border}`,
                                borderRadius: '8px',
                                background: dark.panelAlt,
                                color: isFailedTestTask(selectedTask) ? dark.danger : dark.textSecondary,
                                padding: '0.75rem',
                                fontSize: '0.78rem',
                                lineHeight: 1.5,
                            }}>
                                {taskFailureReason(selectedTask)}
                            </pre>
                        </div>

                        {selectedTask.pipeline_error && (
                            <div>
                                <div style={{ color: dark.text, fontSize: '0.85rem', fontWeight: 700, marginBottom: '0.4rem' }}>
                                    Pipeline Error
                                </div>
                                <pre style={{
                                    whiteSpace: 'pre-wrap',
                                    wordBreak: 'break-word',
                                    margin: 0,
                                    border: `1px solid ${dark.border}`,
                                    borderRadius: '8px',
                                    background: dark.panelAlt,
                                    color: dark.textSecondary,
                                    padding: '0.75rem',
                                    fontSize: '0.72rem',
                                    lineHeight: 1.45,
                                    maxHeight: '12rem',
                                    overflow: 'auto',
                                }}>
                                    {JSON.stringify(selectedTask.pipeline_error, null, 2)}
                                </pre>
                            </div>
                        )}

                        <div>
                            <div style={{ color: dark.text, fontSize: '0.85rem', fontWeight: 700, marginBottom: '0.4rem' }}>
                                Logs
                            </div>
                            {loading ? (
                                <div style={{ color: dark.textMuted, fontSize: '0.82rem' }}>Loading task details...</div>
                            ) : selectedTask.log_excerpt ? (
                                <pre style={{
                                    whiteSpace: 'pre-wrap',
                                    wordBreak: 'break-word',
                                    margin: 0,
                                    border: `1px solid ${dark.border}`,
                                    borderRadius: '8px',
                                    background: '#050914',
                                    color: dark.textSecondary,
                                    padding: '0.75rem',
                                    fontSize: '0.72rem',
                                    lineHeight: 1.45,
                                    maxHeight: '16rem',
                                    overflow: 'auto',
                                }}>
                                    {selectedTask.log_excerpt}
                                </pre>
                            ) : (
                                <div style={{
                                    border: `1px solid ${dark.border}`,
                                    borderRadius: '8px',
                                    background: dark.panelAlt,
                                    color: dark.textMuted,
                                    padding: '0.75rem',
                                    fontSize: '0.82rem',
                                }}>
                                    Run logs unavailable for this task.
                                </div>
                            )}
                        </div>

                        <div>
                            <div style={{ color: dark.text, fontSize: '0.85rem', fontWeight: 700, marginBottom: '0.4rem' }}>
                                Artifacts
                            </div>
                            {selectedTask.artifacts.length > 0 ? (
                                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.4rem' }}>
                                    {selectedTask.artifacts.slice(0, 12).map(artifact => (
                                        <a
                                            key={`${artifact.path}-${artifact.name}`}
                                            href={`${API_BASE}${artifact.path}`}
                                            target="_blank"
                                            rel="noreferrer"
                                            style={{
                                                color: dark.primary,
                                                fontSize: '0.78rem',
                                                textDecoration: 'none',
                                                fontFamily: 'monospace',
                                            }}
                                        >
                                            {artifact.name}
                                        </a>
                                    ))}
                                </div>
                            ) : (
                                <div style={{ color: dark.textMuted, fontSize: '0.82rem' }}>No artifacts reported.</div>
                            )}
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
}

// ============ MAIN COMPONENT ============

export default function AutoPilotPage() {
    const { currentProject, isLoading: projectLoading } = useProject();

    // View state
    const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
    const [sessions, setSessions] = useState<AutoPilotSession[]>([]);
    const [session, setSession] = useState<AutoPilotSession | null>(null);
    const [phases, setPhases] = useState<Phase[]>([]);
    const [questions, setQuestions] = useState<Question[]>([]);
    const [specTasks, setSpecTasks] = useState<SpecTask[]>([]);
    const [testTasks, setTestTasks] = useState<TestTask[]>([]);
    const [liveState, setLiveState] = useState<AutoPilotLiveState | null>(null);
    const [loading, setLoading] = useState(true);
    const [starting, setStarting] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [loadError, setLoadError] = useState<string | null>(null);
    const [selectedTask, setSelectedTask] = useState<TestTaskDetail | null>(null);
    const [taskDetailOpen, setTaskDetailOpen] = useState(false);
    const [taskDetailLoading, setTaskDetailLoading] = useState(false);
    const [taskDetailError, setTaskDetailError] = useState<string | null>(null);

    // Form state
    const [formUrls, setFormUrls] = useState('');
    const [formLoginUrl, setFormLoginUrl] = useState('');
    const [formUsername, setFormUsername] = useState('');
    const [formPassword, setFormPassword] = useState('');
    const [formInstructions, setFormInstructions] = useState('');
    const [formReactiveMode, setFormReactiveMode] = useState(true);
    const [formStrategy, setFormStrategy] = useState('goal_directed');
    const [formMaxSpecs, setFormMaxSpecs] = useState(50);
    const [formPriorityThreshold, setFormPriorityThreshold] = useState('low');
    const [formParallel, setFormParallel] = useState(2);
    const [formHybridHealing, setFormHybridHealing] = useState(false);

    // Question answer state
    const [customAnswer, setCustomAnswer] = useState('');
    const [answeringQuestionId, setAnsweringQuestionId] = useState<number | null>(null);
    const [submittedQuestionIds, setSubmittedQuestionIds] = useState<Set<number>>(() => new Set());
    const submittedQuestionIdsRef = useRef<Set<number>>(new Set());
    const urlStateReady = useRef(false);

    // Countdown timer ref
    const countdownRef = useRef<NodeJS.Timeout | null>(null);
    const [countdown, setCountdown] = useState<number | null>(null);

    // ============ DATA FETCHING ============

    const fetchSessions = useCallback(async () => {
        if (projectLoading) return;
        const projectParam = currentProject?.id
            ? `?project_id=${encodeURIComponent(currentProject.id)}`
            : '';
        try {
            const data = await fetchJsonWithTimeout<AutoPilotSession[] | { sessions?: AutoPilotSession[] }>(`${API_BASE}/autopilot/sessions${projectParam}`);
            setSessions(Array.isArray(data) ? data : data.sessions || []);
            setLoadError(null);
        } catch (err) {
            console.error('Failed to fetch autopilot sessions:', err);
            setLoadError(err instanceof Error ? err.message : 'Failed to load Auto Pilot sessions');
        } finally {
            setLoading(false);
        }
    }, [currentProject?.id, projectLoading]);

    const fetchSessionDetail = useCallback(async (sessionId: string) => {
        try {
            const [sessionData, phasesData, questionsData, specTasksData, testTasksData, liveData] = await Promise.all([
                fetchJsonWithTimeout<AutoPilotSession>(`${API_BASE}/autopilot/${sessionId}`),
                fetchJsonWithTimeout<Phase[] | { phases?: Phase[] }>(`${API_BASE}/autopilot/${sessionId}/phases`),
                fetchJsonWithTimeout<Question[] | { questions?: Question[] }>(`${API_BASE}/autopilot/${sessionId}/questions`),
                fetchJsonWithTimeout<SpecTask[] | { tasks?: SpecTask[] }>(`${API_BASE}/autopilot/${sessionId}/spec-tasks`),
                fetchJsonWithTimeout<TestTask[] | { tasks?: TestTask[] }>(`${API_BASE}/autopilot/${sessionId}/test-tasks`),
                fetchJsonWithTimeout<AutoPilotLiveState>(`${API_BASE}/autopilot/${sessionId}/live`).catch(err => {
                    console.debug('Auto Pilot live state unavailable:', err);
                    return null;
                }),
            ]);

            setSession(sessionData);
            setPhases(Array.isArray(phasesData) ? phasesData : phasesData.phases || []);
            setQuestions(Array.isArray(questionsData) ? questionsData : questionsData.questions || []);
            setSpecTasks(Array.isArray(specTasksData) ? specTasksData : specTasksData.tasks || []);
            setTestTasks(Array.isArray(testTasksData) ? testTasksData : testTasksData.tasks || []);
            setLiveState(liveData);
            setLoadError(null);
        } catch (err) {
            console.error('Failed to fetch session detail:', err);
            setLoadError(err instanceof Error ? err.message : 'Failed to load Auto Pilot session details');
        }
    }, []);

    // Initial load
    useEffect(() => {
        fetchSessions();
    }, [fetchSessions]);

    const sessionStatus = session?.status;

    useEffect(() => {
        if (typeof window === 'undefined') return;
        const params = new URLSearchParams(window.location.search);
        const sessionId = params.get('sessionId') || params.get('session');
        if (sessionId) {
            setActiveSessionId(sessionId);
            void fetchSessionDetail(sessionId);
        }
        urlStateReady.current = true;
    }, [fetchSessionDetail]);

    useEffect(() => {
        if (!urlStateReady.current || typeof window === 'undefined') return;
        const params = new URLSearchParams(window.location.search);
        if (activeSessionId) params.set('sessionId', activeSessionId);
        else params.delete('sessionId');
        const next = `${window.location.pathname}${params.toString() ? `?${params.toString()}` : ''}`;
        window.history.replaceState(null, '', next);
    }, [activeSessionId]);

    // Polling for active session
    useEffect(() => {
        if (!activeSessionId) return;

        fetchSessionDetail(activeSessionId);

        const isActive = sessionStatus === 'running' || sessionStatus === 'awaiting_input';
        if (!isActive && sessionStatus) return;

        const pollMs = sessionStatus === 'running' ? 3000 : 10000;
        const interval = setInterval(() => fetchSessionDetail(activeSessionId), pollMs);
        return () => clearInterval(interval);
    }, [activeSessionId, sessionStatus, fetchSessionDetail]);

    useEffect(() => {
        submittedQuestionIdsRef.current.clear();
        setSubmittedQuestionIds(new Set());
        setAnsweringQuestionId(null);
    }, [activeSessionId]);

    // Countdown timer for auto-continue questions
    useEffect(() => {
        if (countdownRef.current) {
            clearInterval(countdownRef.current);
            countdownRef.current = null;
        }

        const pendingQuestion = questions.find(q => q.status === 'pending' && q.auto_continue_at);
        if (!pendingQuestion?.auto_continue_at) {
            setCountdown(null);
            return;
        }

        const updateCountdown = () => {
            const target = new Date(pendingQuestion.auto_continue_at!.endsWith('Z')
                ? pendingQuestion.auto_continue_at!
                : pendingQuestion.auto_continue_at! + 'Z');
            const remaining = Math.max(0, Math.floor((target.getTime() - Date.now()) / 1000));
            setCountdown(remaining);
            if (remaining <= 0 && countdownRef.current) {
                clearInterval(countdownRef.current);
                countdownRef.current = null;
            }
        };

        updateCountdown();
        countdownRef.current = setInterval(updateCountdown, 1000);
        return () => {
            if (countdownRef.current) clearInterval(countdownRef.current);
        };
    }, [questions]);

    // ============ ACTIONS ============

    const startAutoPilot = async () => {
        const urls = formUrls.split('\n').map(u => u.trim()).filter(Boolean);
        if (urls.length === 0) {
            setError('Please enter at least one URL');
            return;
        }
        setStarting(true);
        setError(null);

        try {
            const body: Record<string, any> = {
                entry_urls: urls,
                project_id: currentProject?.id || 'default',
                reactive_mode: formReactiveMode,
                strategy: formStrategy,
                max_specs: formMaxSpecs,
                priority_threshold: formPriorityThreshold,
                parallel_generation: formParallel,
                hybrid_healing: formHybridHealing,
            };
            if (formLoginUrl) body.login_url = formLoginUrl;
            if (formUsername) body.credentials = { username: formUsername, password: formPassword };
            if (formInstructions) body.instructions = formInstructions;

            const res = await fetch(`${API_BASE}/autopilot/start`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });

            if (res.ok) {
                const data = await res.json();
                const newId = data.session_id || data.id;
                setActiveSessionId(newId);
                // Reset form
                setFormUrls('');
                setFormLoginUrl('');
                setFormUsername('');
                setFormPassword('');
                setFormInstructions('');
                fetchSessions();
            } else {
                const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
                setError(err.detail || 'Failed to start Auto Pilot');
            }
        } catch (e) {
            setError(e instanceof Error ? e.message : 'Network error');
        } finally {
            setStarting(false);
        }
    };

    const answerQuestion = async (questionId: number, answer: string) => {
        if (!activeSessionId) return;
        if (answeringQuestionId === questionId || submittedQuestionIdsRef.current.has(questionId)) return;
        submittedQuestionIdsRef.current.add(questionId);
        setAnsweringQuestionId(questionId);
        setSubmittedQuestionIds(prev => {
            const next = new Set(prev);
            next.add(questionId);
            return next;
        });
        try {
            const res = await fetch(`${API_BASE}/autopilot/${activeSessionId}/answer`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ question_id: questionId, answer_text: answer }),
            });
            if (res.ok) {
                setCustomAnswer('');
                fetchSessionDetail(activeSessionId);
            } else {
                const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }));
                submittedQuestionIdsRef.current.delete(questionId);
                setSubmittedQuestionIds(prev => {
                    const next = new Set(prev);
                    next.delete(questionId);
                    return next;
                });
                toast.error(err.detail || 'Failed to submit answer');
            }
        } catch (e) {
            submittedQuestionIdsRef.current.delete(questionId);
            setSubmittedQuestionIds(prev => {
                const next = new Set(prev);
                next.delete(questionId);
                return next;
            });
            toast.error(`Failed to submit answer: ${e instanceof Error ? e.message : 'Network error'}`);
        } finally {
            setAnsweringQuestionId(null);
        }
    };

    const pauseSession = async () => {
        if (!activeSessionId) return;
        try {
            const res = await fetch(`${API_BASE}/autopilot/${activeSessionId}/pause`, { method: 'POST' });
            if (!res.ok) {
                const data = await res.json().catch(() => ({}));
                toast.error(data.detail || 'Failed to pause');
                return;
            }
            toast.success('Auto Pilot paused');
            fetchSessionDetail(activeSessionId);
        } catch (e) {
            console.error('Failed to pause:', e);
            toast.error('Failed to pause');
        }
    };

    const resumeSession = async () => {
        if (!activeSessionId) return;
        try {
            const res = await fetch(`${API_BASE}/autopilot/${activeSessionId}/resume`, { method: 'POST' });
            if (!res.ok) {
                const data = await res.json().catch(() => ({}));
                toast.error(data.detail || 'Failed to resume');
                return;
            }
            toast.success('Auto Pilot resumed');
            fetchSessionDetail(activeSessionId);
        } catch (e) {
            console.error('Failed to resume:', e);
            toast.error('Failed to resume');
        }
    };

    const cancelSession = async () => {
        if (!activeSessionId) return;
        try {
            await fetch(`${API_BASE}/autopilot/${activeSessionId}/cancel`, { method: 'POST' });
            fetchSessionDetail(activeSessionId);
            fetchSessions();
        } catch (e) {
            console.error('Failed to cancel:', e);
        }
    };

    const stopTestTask = async (taskId: number) => {
        if (!activeSessionId) return;
        try {
            const res = await fetch(
                `${API_BASE}/autopilot/${activeSessionId}/test-tasks/${taskId}/stop`,
                { method: 'POST', headers: { 'Content-Type': 'application/json' } }
            );
            if (res.ok) {
                toast.success(`Test task ${taskId} stopped`);
                fetchSessionDetail(activeSessionId);
            } else {
                const data = await res.json().catch(() => ({}));
                toast.error(data.detail || 'Failed to stop task');
            }
        } catch (err) {
            toast.error('Error stopping task');
        }
    };

    const openTaskDetails = async (task: TestTask) => {
        if (!activeSessionId) return;
        setTaskDetailOpen(true);
        setTaskDetailLoading(true);
        setTaskDetailError(null);
        setSelectedTask({
            ...task,
            run_dir: null,
            pipeline_error: null,
            agentic_summary: null,
            validation: null,
            artifacts: [],
            report_url: null,
            log_excerpt: null,
        });

        try {
            const res = await fetch(`${API_BASE}/autopilot/${activeSessionId}/test-tasks/${task.id}`);
            if (!res.ok) {
                const data = await res.json().catch(() => ({}));
                const message = data.detail || 'Failed to load task details';
                setTaskDetailError(message);
                toast.error(message);
                return;
            }
            setSelectedTask(await res.json());
        } catch (e) {
            const message = `Failed to load task details: ${e instanceof Error ? e.message : 'Network error'}`;
            setTaskDetailError(message);
            toast.error(message);
        } finally {
            setTaskDetailLoading(false);
        }
    };

    const setTaskDetailDialogOpen = (open: boolean) => {
        setTaskDetailOpen(open);
        if (!open) {
            setTaskDetailError(null);
            setTaskDetailLoading(false);
        }
    };

    const viewSession = (s: AutoPilotSession) => {
        setActiveSessionId(s.id);
        setSession(s);
        setPhases([]);
        setQuestions([]);
        setSpecTasks([]);
        setTestTasks([]);
        setLiveState(null);
        setSelectedTask(null);
        setTaskDetailOpen(false);
        setTaskDetailError(null);
    };

    const backToList = () => {
        setActiveSessionId(null);
        setSession(null);
        setPhases([]);
        setQuestions([]);
        setSpecTasks([]);
        setTestTasks([]);
        setLiveState(null);
        fetchSessions();
    };

    // ============ RENDER HELPERS (called as functions, NOT as JSX components) ============
    // Defining components inside a render function creates new references each render,
    // causing React to unmount/remount them — destroying input focus on every keystroke.
    // These are called as renderX() instead of <X /> to avoid that issue.

    // -- Phase Timeline --
    const renderPhaseTimeline = () => {
        if (!session) return null;
        const completedPhases = session.phases_completed || [];
        const currentPhase = session.current_phase;

        return (
            <div style={{ ...cardStyle, marginBottom: '1rem' }}>
                <div className="autopilot-phase-track" style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    marginBottom: '1rem',
                }}>
                    {PHASE_ORDER.map((phase, idx) => {
                        const isCompleted = completedPhases.includes(phase);
                        const isCurrent = currentPhase === phase;
                        const isFailed = phases.find(p => p.phase_name === phase)?.status === 'failed';
                        const PhaseIcon = PHASE_ICONS[phase] || Globe;

                        let dotBg = dark.panelAlt;
                        let dotBorder = dark.borderStrong;
                        let dotColor = dark.textFaint;
                        let labelColor = dark.textMuted;

                        if (isCompleted) {
                            dotBg = dark.successSoft;
                            dotBorder = dark.success;
                            dotColor = dark.success;
                            labelColor = dark.success;
                        } else if (isFailed) {
                            dotBg = dark.dangerSoft;
                            dotBorder = dark.danger;
                            dotColor = dark.danger;
                            labelColor = dark.danger;
                        } else if (isCurrent) {
                            dotBg = dark.primarySoft;
                            dotBorder = dark.primary;
                            dotColor = dark.primary;
                            labelColor = dark.primary;
                        }

                        return (
                            <div key={phase} className="autopilot-phase-step" style={{
                                display: 'flex',
                                flexDirection: 'column',
                                alignItems: 'center',
                                flex: 1,
                                position: 'relative',
                            }}>
                                {idx > 0 && (
                                    <div style={{
                                        position: 'absolute',
                                        top: '18px',
                                        right: '50%',
                                        width: '100%',
                                        height: '2px',
                                        background: isCompleted ? dark.success : dark.border,
                                        zIndex: 0,
                                    }} />
                                )}
                                <div style={{
                                    width: '36px',
                                    height: '36px',
                                    borderRadius: '50%',
                                    display: 'flex',
                                    alignItems: 'center',
                                    justifyContent: 'center',
                                    background: dotBg,
                                    border: `2px solid ${dotBorder}`,
                                    position: 'relative',
                                    zIndex: 1,
                                    transition: 'background-color 0.2s, border-color 0.2s, box-shadow 0.2s',
                                    ...(isCurrent ? {
                                        boxShadow: '0 0 0 4px rgba(59, 130, 246, 0.18)',
                                        animation: 'pulse 2s ease-in-out infinite',
                                    } : {}),
                                }}>
                                    {isCompleted ? (
                                        <CheckCircle2 size={16} style={{ color: dotColor }} />
                                    ) : isFailed ? (
                                        <AlertTriangle size={16} style={{ color: dotColor }} />
                                    ) : isCurrent ? (
                                        <Loader2 size={16} style={{ color: dotColor, animation: 'spin 1.5s linear infinite' }} />
                                    ) : (
                                        <PhaseIcon size={16} style={{ color: dotColor }} />
                                    )}
                                </div>
                                <span style={{
                                    marginTop: '0.5rem',
                                    fontSize: '0.7rem',
                                    fontWeight: 600,
                                    color: labelColor,
                                    textAlign: 'center',
                                    letterSpacing: '0.02em',
                                }}>
                                    {PHASE_LABELS[phase]}
                                </span>
                            </div>
                        );
                    })}
                </div>

                {/* Overall progress bar */}
                <div style={{
                    height: '6px',
                    background: dark.border,
                    borderRadius: '3px',
                    overflow: 'hidden',
                }}>
                    <div style={{
                        height: '100%',
                        width: `${progressPercent(session.overall_progress)}%`,
                        background: `linear-gradient(90deg, ${dark.primary}, ${dark.success})`,
                        borderRadius: '3px',
                        transition: 'width 0.5s ease',
                    }} />
                </div>
                <div style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    marginTop: '0.375rem',
                    fontSize: '0.7rem',
                    color: dark.textMuted,
                }}>
                    <span>Overall Progress</span>
                    <span>{Math.round(progressPercent(session.overall_progress))}%</span>
                </div>
            </div>
        );
    };

    // -- Question Panel --
    const renderQuestionPanel = () => {
        const pendingQuestion = questions.find(q => q.status === 'pending' && !submittedQuestionIds.has(q.id));
        if (!pendingQuestion || session?.status !== 'awaiting_input') return null;
        const isSubmittingAnswer = answeringQuestionId === pendingQuestion.id || submittedQuestionIds.has(pendingQuestion.id);

        return (
            <div style={{
                ...cardStyle,
                marginBottom: '1rem',
                border: `1px solid ${dark.warningBorder}`,
                background: dark.warningSoft,
            }}>
                <div style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '0.5rem',
                    marginBottom: '0.75rem',
                }}>
                    <MessageCircle size={18} style={{ color: dark.warning }} />
                    <span style={{ fontWeight: 700, fontSize: '0.9rem', color: dark.warning }}>
                        Input Required
                    </span>
                    {countdown !== null && countdown > 0 && (
                        <span style={{
                            marginLeft: 'auto',
                            fontSize: '0.75rem',
                            color: dark.textMuted,
                            display: 'flex',
                            alignItems: 'center',
                            gap: '0.25rem',
                        }}>
                            <Clock size={12} />
                            Auto-continuing in {countdown}s
                        </span>
                    )}
                </div>

                <p style={{
                    fontSize: '0.9rem',
                    color: dark.text,
                    marginBottom: '1rem',
                    lineHeight: 1.5,
                }}>
                    {pendingQuestion.question_text}
                </p>

                {pendingQuestion.suggested_answers.length > 0 && (
                    <div style={{
                        display: 'flex',
                        flexWrap: 'wrap',
                        gap: '0.5rem',
                        marginBottom: '0.75rem',
                    }}>
                        {pendingQuestion.suggested_answers.map((answer, i) => (
                            <button
                                key={i}
                                onClick={() => answerQuestion(pendingQuestion.id, answer)}
                                disabled={isSubmittingAnswer}
                                style={{
                                    padding: '0.5rem 1rem',
                                    borderRadius: '8px',
                                    border: `1px solid ${dark.warningBorder}`,
                                    background: dark.warningSoft,
                                    color: dark.warning,
                                    fontSize: '0.8rem',
                                    fontWeight: 500,
                                    cursor: isSubmittingAnswer ? 'not-allowed' : 'pointer',
                                    transition: 'background-color 0.15s, border-color 0.15s, color 0.15s',
                                    opacity: isSubmittingAnswer ? 0.5 : 1,
                                }}
                            >
                                {answer}
                            </button>
                        ))}
                    </div>
                )}

                <div style={{ display: 'flex', gap: '0.5rem' }}>
                    <input
                        type="text"
                        placeholder="Type a custom answer..."
                        value={customAnswer}
                        onChange={e => setCustomAnswer(e.target.value)}
                        disabled={isSubmittingAnswer}
                        onKeyDown={e => {
                            if (e.key === 'Enter' && customAnswer.trim() && !isSubmittingAnswer) {
                                answerQuestion(pendingQuestion.id, customAnswer.trim());
                            }
                        }}
                        style={{
                            ...inputStyle,
                            flex: 1,
                            borderColor: 'rgba(245, 158, 11, 0.2)',
                        }}
                    />
                    <button
                        onClick={() => {
                            if (customAnswer.trim() && !isSubmittingAnswer) {
                                answerQuestion(pendingQuestion.id, customAnswer.trim());
                            }
                        }}
                        disabled={!customAnswer.trim() || isSubmittingAnswer}
                        style={{
                            padding: '0.5rem 1rem',
                            borderRadius: '8px',
                            border: 'none',
                            background: dark.warning,
                            color: '#ffffff',
                            fontWeight: 600,
                            fontSize: '0.8rem',
                            cursor: !customAnswer.trim() || isSubmittingAnswer ? 'not-allowed' : 'pointer',
                            opacity: !customAnswer.trim() || isSubmittingAnswer ? 0.5 : 1,
                        }}
                    >
                        {isSubmittingAnswer ? (
                            <Loader2 size={14} style={{ animation: 'spin 1s linear infinite' }} />
                        ) : 'Submit'}
                    </button>
                </div>
            </div>
        );
    };

    // -- Live Browser --
    const renderLiveBrowserPanel = () => {
        if (!session || !activeSessionId) return null;

        const browserPhase = liveState?.phase === 'exploration' || liveState?.phase === 'test_generation';
        const active = Boolean(liveState?.active && browserPhase && session.status === 'running');
        const recentTools = liveState?.recent_tools || [];
        const latestImage = liveState?.latest_image;
        const title = liveState?.activity_label || (
            browserPhase
                ? PHASE_LABELS[liveState?.phase || ''] || 'Browser activity'
                : 'Browser idle'
        );

        return (
            <div style={{ ...cardStyle, marginBottom: '1rem', padding: 0, overflow: 'hidden' }}>
                <div style={{
                    padding: '1rem 1.25rem',
                    borderBottom: `1px solid ${dark.border}`,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    gap: '1rem',
                    flexWrap: 'wrap',
                }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', minWidth: 0 }}>
                        <Monitor size={18} style={{ color: active ? dark.primary : dark.textMuted, flex: '0 0 auto' }} />
                        <div style={{ minWidth: 0 }}>
                            <div style={{ color: dark.text, fontSize: '0.95rem', fontWeight: 800 }}>Live Browser</div>
                            <div style={{ color: dark.textSecondary, fontSize: '0.8rem', overflowWrap: 'anywhere' }}>
                                {title}
                            </div>
                        </div>
                    </div>
                    <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', flexWrap: 'wrap' }}>
                        <StatusBadge status={active ? 'running' : (liveState?.status || session.status)} />
                        {liveState?.updated_at && (
                            <span style={{ color: dark.textMuted, fontSize: '0.78rem' }}>
                                {formatTime(liveState.updated_at)}
                            </span>
                        )}
                    </div>
                </div>

                <div style={{
                    display: 'grid',
                    gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))',
                    gap: '0.75rem',
                    padding: '1rem 1.25rem',
                    borderBottom: `1px solid ${dark.border}`,
                    background: 'rgba(255,255,255,0.015)',
                }}>
                    {[
                        { label: 'Phase', value: liveState?.phase ? PHASE_LABELS[liveState.phase] || liveState.phase : '-' },
                        { label: 'Current Tool', value: liveState?.last_tool_label || liveState?.current_stage || '-' },
                        { label: 'Tool Calls', value: liveState?.tool_calls ?? 0 },
                        { label: 'Browser Actions', value: liveState?.browser_tool_calls ?? liveState?.interactions ?? 0 },
                    ].map(item => (
                        <div key={item.label}>
                            <div style={{
                                color: dark.textMuted,
                                fontSize: '0.68rem',
                                fontWeight: 800,
                                textTransform: 'uppercase',
                                letterSpacing: '0.04em',
                                marginBottom: '0.25rem',
                            }}>
                                {item.label}
                            </div>
                            <div style={{ color: dark.text, fontSize: '0.9rem', fontWeight: 700, overflowWrap: 'anywhere' }}>
                                {item.value}
                            </div>
                        </div>
                    ))}
                </div>

                {browserPhase ? (
                    <div style={{ padding: '1rem 1.25rem', display: 'grid', gap: '1rem' }}>
                        <LiveBrowserView runId={activeSessionId} isActive={active} showHeader />

                        <div style={{
                            display: 'grid',
                            gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))',
                            gap: '1rem',
                        }}>
                            <div style={{ border: `1px solid ${dark.border}`, borderRadius: '8px', overflow: 'hidden' }}>
                                <div style={{
                                    padding: '0.75rem 1rem',
                                    borderBottom: `1px solid ${dark.border}`,
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: '0.5rem',
                                    fontWeight: 700,
                                    fontSize: '0.88rem',
                                }}>
                                    <Activity size={15} style={{ color: dark.primary }} />
                                    Live Activity
                                </div>
                                {recentTools.length > 0 ? (
                                    <div>
                                        {recentTools.slice().reverse().map((tool, i) => (
                                            <div
                                                key={`${tool.name || 'tool'}-${tool.at || i}`}
                                                style={{
                                                    padding: '0.65rem 1rem',
                                                    borderBottom: i === recentTools.length - 1 ? 'none' : `1px solid ${dark.border}`,
                                                    display: 'flex',
                                                    justifyContent: 'space-between',
                                                    gap: '1rem',
                                                    fontSize: '0.82rem',
                                                }}
                                            >
                                                <span style={{ color: dark.text, fontWeight: 650, overflowWrap: 'anywhere' }}>
                                                    {tool.label || tool.name || 'Tool'}
                                                </span>
                                                <span style={{ color: dark.textMuted, whiteSpace: 'nowrap' }}>
                                                    {formatTime(tool.at)}
                                                </span>
                                            </div>
                                        ))}
                                    </div>
                                ) : (
                                    <div style={{ padding: '1rem', color: dark.textMuted, fontSize: '0.85rem' }}>
                                        {liveState?.message || 'Waiting for browser activity.'}
                                    </div>
                                )}
                            </div>

                            <div style={{ border: `1px solid ${dark.border}`, borderRadius: '8px', overflow: 'hidden' }}>
                                <div style={{
                                    padding: '0.75rem 1rem',
                                    borderBottom: `1px solid ${dark.border}`,
                                    display: 'flex',
                                    alignItems: 'center',
                                    justifyContent: 'space-between',
                                    gap: '0.75rem',
                                    fontWeight: 700,
                                    fontSize: '0.88rem',
                                }}>
                                    <span style={{ display: 'inline-flex', alignItems: 'center', gap: '0.5rem' }}>
                                        <ImageIcon size={15} style={{ color: dark.cyan }} />
                                        Latest Screenshot
                                    </span>
                                    {latestImage && (
                                        <a
                                            href={`${API_BASE}${latestImage.path}`}
                                            target="_blank"
                                            rel="noreferrer"
                                            style={{ color: dark.primary, display: 'inline-flex', alignItems: 'center', gap: '0.25rem' }}
                                            title="Open artifact"
                                        >
                                            <ExternalLink size={14} />
                                        </a>
                                    )}
                                </div>
                                {latestImage ? (
                                    <a href={`${API_BASE}${latestImage.path}`} target="_blank" rel="noreferrer" style={{ display: 'block' }}>
                                        <img
                                            src={`${API_BASE}${latestImage.path}`}
                                            alt="Latest Auto Pilot browser screenshot"
                                            style={{
                                                width: '100%',
                                                height: '220px',
                                                objectFit: 'contain',
                                                background: '#000',
                                                display: 'block',
                                            }}
                                        />
                                    </a>
                                ) : (
                                    <div style={{
                                        height: '220px',
                                        display: 'flex',
                                        alignItems: 'center',
                                        justifyContent: 'center',
                                        textAlign: 'center',
                                        color: dark.textMuted,
                                        fontSize: '0.85rem',
                                        padding: '1rem',
                                    }}>
                                        No screenshots captured yet.
                                    </div>
                                )}
                            </div>
                        </div>
                    </div>
                ) : (
                    <div style={{ padding: '1.25rem', color: dark.textMuted, fontSize: '0.86rem' }}>
                        {liveState?.message || 'The current Auto Pilot phase does not use the browser.'}
                    </div>
                )}
            </div>
        );
    };

    // -- Stats Cards --
    const renderStatsCards = () => {
        if (!session) return null;
        const stats = [
            { label: 'Pages', value: session.total_pages_discovered, icon: Globe, color: dark.primary },
            { label: 'Flows', value: session.total_flows_discovered, icon: Zap, color: dark.warning },
            { label: 'Requirements', value: session.total_requirements_generated, icon: FileText, color: dark.violet },
            { label: 'Specs', value: session.total_specs_generated, icon: List, color: dark.cyan },
            { label: 'Passed', value: session.total_tests_passed, icon: CheckCircle2, color: dark.success },
            { label: 'Failed', value: session.total_tests_failed, icon: AlertTriangle, color: dark.danger },
            { label: 'Coverage', value: `${Math.round(session.coverage_percentage)}%`, icon: Target, color: dark.success },
        ];

        return (
            <div className="autopilot-stats-grid">
                {stats.map(stat => {
                    const Icon = stat.icon;
                    return (
                        <div key={stat.label} style={{
                            ...cardStyle,
                            padding: '1rem',
                            display: 'flex',
                            flexDirection: 'column',
                            gap: '0.5rem',
                        }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                                <Icon size={14} style={{ color: stat.color }} />
                                <span style={{
                                    fontSize: '0.7rem',
                                    fontWeight: 700,
                                    color: dark.textMuted,
                                    textTransform: 'uppercase',
                                    letterSpacing: '0.04em',
                                }}>
                                    {stat.label}
                                </span>
                            </div>
                            <span style={{
                                fontSize: '1.5rem',
                                fontWeight: 700,
                                color: stat.color,
                            }}>
                                {stat.value}
                            </span>
                        </div>
                    );
                })}
            </div>
        );
    };

    // -- Phase Detail --
    const renderPhaseDetail = () => {
        const currentPhaseData = phases.find(p => p.phase_name === session?.current_phase);
        if (!currentPhaseData) return null;

        return (
            <div style={{ ...cardStyle, marginBottom: '1rem' }}>
                <div style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    marginBottom: '0.75rem',
                }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                        <span style={{ fontWeight: 700, fontSize: '0.95rem', color: dark.text }}>
                            {PHASE_LABELS[currentPhaseData.phase_name] || currentPhaseData.phase_name}
                        </span>
                        <StatusBadge status={currentPhaseData.status} />
                    </div>
                    <span style={{ fontSize: '0.75rem', color: dark.textMuted }}>
                        {currentPhaseData.items_completed} / {currentPhaseData.items_total} items
                    </span>
                </div>

                {currentPhaseData.current_step && (
                    <p style={{
                        fontSize: '0.8rem',
                        color: dark.textSecondary,
                        marginBottom: '0.75rem',
                        fontStyle: 'italic',
                    }}>
                        {currentPhaseData.current_step}
                    </p>
                )}

                {/* Phase progress bar */}
                <div style={{
                    height: '4px',
                    background: dark.border,
                    borderRadius: '2px',
                    overflow: 'hidden',
                    marginBottom: '0.5rem',
                }}>
                    <div style={{
                        height: '100%',
                        width: `${progressPercent(currentPhaseData.progress)}%`,
                        background: dark.primary,
                        borderRadius: '2px',
                        transition: 'width 0.5s ease',
                    }} />
                </div>

                {currentPhaseData.error_message && (
                    <div style={{
                        padding: '0.5rem 0.75rem',
                        background: dark.dangerSoft,
                        borderRadius: '6px',
                        fontSize: '0.8rem',
                        color: dark.danger,
                        marginTop: '0.5rem',
                    }}>
                        {currentPhaseData.error_message}
                    </div>
                )}
            </div>
        );
    };

    // -- Spec Tasks Table --
    const renderSpecTasksTable = () => {
        if (specTasks.length === 0) return null;

        return (
            <div style={{ ...cardStyle, marginBottom: '1rem', padding: 0, overflow: 'hidden' }}>
                <div style={{
                    padding: '1rem 1.25rem',
                    borderBottom: `1px solid ${dark.border}`,
                    display: 'flex',
                    alignItems: 'center',
                    gap: '0.5rem',
                }}>
                    <List size={16} style={{ color: dark.cyan }} />
                    <span style={{ fontWeight: 600, fontSize: '0.9rem' }}>Spec Generation Tasks</span>
                    <span style={{
                        marginLeft: 'auto',
                        fontSize: '0.75rem',
                        color: dark.textMuted,
                    }}>
                        {specTasks.filter(t => t.status === 'completed').length}/{specTasks.length} completed
                    </span>
                </div>
                <div style={{ overflowX: 'auto' }}>
                    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.8rem' }}>
                        <thead>
                            <tr style={{ borderBottom: `1px solid ${dark.border}` }}>
                                {['Priority', 'Requirement', 'Status', 'Spec Name'].map(h => (
                                    <th key={h} style={tableHeaderStyle}>
                                        {h}
                                    </th>
                                ))}
                            </tr>
                        </thead>
                        <tbody>
                            {specTasks.map(task => (
                                <tr key={task.id} className="autopilot-table-row" style={{
                                    borderBottom: `1px solid ${dark.border}`,
                                    transition: 'background-color 0.15s',
                                }}>
                                    <td style={{ padding: '0.6rem 1rem' }}>
                                        <span style={{
                                            padding: '0.15rem 0.5rem',
                                            borderRadius: '9999px',
                                            fontSize: '0.7rem',
                                            fontWeight: 600,
                                            background: task.priority === 'critical' ? dark.dangerSoft :
                                                task.priority === 'high' ? dark.warningSoft :
                                                    task.priority === 'medium' ? dark.primarySoft :
                                                        dark.neutralSoft,
                                            color: task.priority === 'critical' ? dark.danger :
                                                task.priority === 'high' ? dark.warning :
                                                    task.priority === 'medium' ? dark.primary :
                                                        dark.textMuted,
                                            textTransform: 'capitalize',
                                        }}>
                                            {task.priority}
                                        </span>
                                    </td>
                                    <td style={{ padding: '0.6rem 1rem', color: dark.textSecondary }}>
                                        {task.requirement_title || '-'}
                                    </td>
                                    <td style={{ padding: '0.6rem 1rem' }}>
                                        <StatusBadge status={task.status} />
                                    </td>
                                    <td style={{
                                        padding: '0.6rem 1rem',
                                        fontFamily: 'monospace',
                                        fontSize: '0.75rem',
                                        color: dark.textMuted,
                                    }}>
                                        {task.spec_name || '-'}
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            </div>
        );
    };

    // -- Test Tasks Table --
    const renderTestTasksTable = () => {
        if (testTasks.length === 0) return null;

        return (
            <div style={{ ...cardStyle, marginBottom: '1rem', padding: 0, overflow: 'hidden' }}>
                <div style={{
                    padding: '1rem 1.25rem',
                    borderBottom: `1px solid ${dark.border}`,
                    display: 'flex',
                    alignItems: 'center',
                    gap: '0.5rem',
                }}>
                    <Zap size={16} style={{ color: dark.warning }} />
                    <span style={{ fontWeight: 600, fontSize: '0.9rem' }}>Test Generation Tasks</span>
                    <span style={{
                        marginLeft: 'auto',
                        fontSize: '0.75rem',
                        color: dark.textMuted,
                    }}>
                        {testTasks.filter(t => t.passed === true).length} passed /
                        {testTasks.filter(t => t.passed === false).length} failed /
                        {testTasks.length} total
                    </span>
                </div>
                <div style={{ overflowX: 'auto' }}>
                    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.8rem' }}>
                        <thead>
                            <tr style={{ borderBottom: `1px solid ${dark.border}` }}>
                                {['Spec Name', 'Status', 'Reason', 'Mode', 'Stage', 'Artifact', 'Healing', 'Duration', 'Actions'].map(h => (
                                    <th key={h} style={tableHeaderStyle}>
                                        {h}
                                    </th>
                                ))}
                            </tr>
                        </thead>
                        <tbody>
                            {testTasks.map(task => (
                                <tr key={task.id} className="autopilot-table-row" style={{
                                    borderBottom: `1px solid ${dark.border}`,
                                    transition: 'background-color 0.15s',
                                }}>
                                    <td style={{
                                        padding: '0.6rem 1rem',
                                        fontFamily: 'monospace',
                                        fontSize: '0.75rem',
                                        color: dark.textSecondary,
                                    }}>
                                        {task.spec_name || '-'}
                                    </td>
                                    <td style={{ padding: '0.6rem 1rem' }}>
                                        <StatusBadge status={task.passed === true ? 'passed' : task.passed === false ? 'failed' : task.status} />
                                    </td>
                                    <td style={{
                                        padding: '0.6rem 1rem',
                                        fontSize: '0.75rem',
                                        color: isFailedTestTask(task) ? dark.danger : task.status === 'paused' ? dark.warning : dark.textFaint,
                                        maxWidth: '18rem',
                                        overflow: 'hidden',
                                        textOverflow: 'ellipsis',
                                        whiteSpace: 'nowrap',
                                    }} title={taskFailureReason(task)}>
                                        {taskFailureReason(task)}
                                    </td>
                                    <td style={{ padding: '0.6rem 1rem' }}>
                                        {task.generation_mode ? (
                                            <span style={{
                                                padding: '0.15rem 0.5rem',
                                                borderRadius: '9999px',
                                                fontSize: '0.7rem',
                                                fontWeight: 600,
                                                background: task.generation_mode === 'conservative_smoke' ? dark.warningSoft : dark.successSoft,
                                                color: task.generation_mode === 'conservative_smoke' ? dark.warning : dark.success,
                                                whiteSpace: 'nowrap',
                                            }}>
                                                {task.generation_mode === 'conservative_smoke' ? 'Smoke' : 'Native E2E'}
                                            </span>
                                        ) : '-'}
                                    </td>
                                    <td style={{
                                        padding: '0.6rem 1rem',
                                        fontSize: '0.75rem',
                                        color: dark.textMuted,
                                        textTransform: 'capitalize',
                                    }}>
                                        {task.current_stage?.replace('_', ' ') || '-'}
                                    </td>
                                    <td style={{
                                        padding: '0.6rem 1rem',
                                        fontFamily: 'monospace',
                                        fontSize: '0.7rem',
                                        color: task.test_path ? dark.textSecondary : dark.textFaint,
                                        maxWidth: '16rem',
                                        overflow: 'hidden',
                                        textOverflow: 'ellipsis',
                                        whiteSpace: 'nowrap',
                                    }} title={task.test_path || undefined}>
                                        {task.test_path ? task.test_path.split('/').pop() : '-'}
                                    </td>
                                    <td style={{
                                        padding: '0.6rem 1rem',
                                        fontSize: '0.75rem',
                                        color: task.healing_attempt > 0 ? dark.warning : dark.textFaint,
                                    }}>
                                        {task.healing_attempt > 0 ? `${task.healing_attempt} attempt${task.healing_attempt > 1 ? 's' : ''}` : '-'}
                                    </td>
                                    <td style={{
                                        padding: '0.6rem 1rem',
                                        fontSize: '0.75rem',
                                        color: dark.textMuted,
                                    }}>
                                        {formatDuration(task.started_at, task.completed_at)}
                                    </td>
                                    <td style={{ padding: '0.6rem 1rem' }}>
                                        <div style={{ display: 'flex', gap: '0.45rem', alignItems: 'center', flexWrap: 'wrap' }}>
                                            <button
                                                type="button"
                                                onClick={(event) => {
                                                    event.stopPropagation();
                                                    openTaskDetails(task);
                                                }}
                                                style={{
                                                    padding: '0.2rem 0.5rem',
                                                    borderRadius: '4px',
                                                    border: `1px solid ${dark.borderStrong}`,
                                                    background: dark.neutralSoft,
                                                    color: dark.textSecondary,
                                                    cursor: 'pointer',
                                                    fontSize: '0.7rem',
                                                    fontWeight: 600,
                                                    display: 'inline-flex',
                                                    alignItems: 'center',
                                                    gap: '0.25rem',
                                                }}
                                            >
                                                <FileText size={12} />
                                                Details
                                            </button>
                                        {(task.status === 'running' || task.status === 'pending') && (
                                            <button
                                                onClick={() => stopTestTask(task.id)}
                                                style={{
                                                    padding: '0.2rem 0.5rem',
                                                    borderRadius: '4px',
                                                    border: `1px solid ${dark.dangerBorder}`,
                                                    background: dark.dangerSoft,
                                                    color: dark.danger,
                                                    cursor: 'pointer',
                                                    fontSize: '0.7rem',
                                                    fontWeight: 600,
                                                }}
                                                onMouseEnter={(e) => {
                                                    e.currentTarget.style.background = dark.dangerHover;
                                                }}
                                                onMouseLeave={(e) => {
                                                    e.currentTarget.style.background = dark.dangerSoft;
                                                }}
                                            >
                                                Stop
                                            </button>
                                        )}
                                        </div>
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            </div>
        );
    };

    // -- Session History Table --
    const renderSessionHistory = () => {
        if (sessions.length === 0) {
            return (
                <EmptyState
                    icon={<Rocket size={40} />}
                    title="No Auto Pilot sessions yet"
                    description="Start your first Auto Pilot session to automatically explore, generate requirements, create test specs, and run tests."
                />
            );
        }

        return (
            <div style={{ ...cardStyle, padding: 0, overflow: 'hidden' }}>
                <div style={{
                    padding: '1rem 1.25rem',
                    borderBottom: `1px solid ${dark.border}`,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                }}>
                    <span style={{ fontWeight: 600, fontSize: '0.95rem' }}>Session History</span>
                    <button
                        onClick={fetchSessions}
                        style={{
                            background: 'none',
                            border: 'none',
                            cursor: 'pointer',
                            color: dark.textMuted,
                            padding: '0.25rem',
                        }}
                        aria-label="Refresh sessions"
                    >
                        <RefreshCw size={14} />
                    </button>
                </div>
                <div style={{ overflowX: 'auto' }}>
                    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.8rem' }}>
                        <thead>
                            <tr style={{ borderBottom: `1px solid ${dark.border}` }}>
                                {['URLs', 'Status', 'Progress', 'Phases', 'Tests', 'Coverage', 'Created', 'Duration'].map(h => (
                                    <th key={h} style={{
                                        ...tableHeaderStyle,
                                        whiteSpace: 'nowrap',
                                    }}>
                                        {h}
                                    </th>
                                ))}
                            </tr>
                        </thead>
                        <tbody>
                            {sessions.map(s => (
                                <tr
                                    key={s.id}
                                    onClick={() => viewSession(s)}
                                    className="autopilot-table-row"
                                    style={{
                                        borderBottom: `1px solid ${dark.border}`,
                                        cursor: 'pointer',
                                        transition: 'background-color 0.15s',
                                    }}
                                    onMouseEnter={e => (e.currentTarget.style.background = dark.panelHover)}
                                    onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
                                >
                                    <td style={{
                                        padding: '0.75rem 1rem',
                                        maxWidth: '250px',
                                    }}>
                                        <div style={{
                                            display: 'flex',
                                            flexDirection: 'column',
                                            gap: '0.15rem',
                                        }}>
                                            {s.entry_urls.slice(0, 2).map((url, i) => (
                                                <span key={i} style={{
                                                    fontSize: '0.8rem',
                                                    color: dark.textSecondary,
                                                    whiteSpace: 'nowrap',
                                                    overflow: 'hidden',
                                                    textOverflow: 'ellipsis',
                                                    display: 'block',
                                                }}>
                                                    {url.replace(/^https?:\/\//, '')}
                                                </span>
                                            ))}
                                            {s.entry_urls.length > 2 && (
                                                <span style={{ fontSize: '0.7rem', color: dark.textFaint }}>
                                                    +{s.entry_urls.length - 2} more
                                                </span>
                                            )}
                                        </div>
                                    </td>
                                    <td style={{ padding: '0.75rem 1rem' }}>
                                        <StatusBadge status={s.status} />
                                    </td>
                                    <td style={{ padding: '0.75rem 1rem' }}>
                                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                                            <div style={{
                                                width: '60px',
                                                height: '4px',
                                                background: dark.border,
                                                borderRadius: '2px',
                                                overflow: 'hidden',
                                            }}>
                                                <div style={{
                                                    height: '100%',
                                                    width: `${progressPercent(s.overall_progress)}%`,
                                                    background: dark.primary,
                                                    borderRadius: '2px',
                                                }} />
                                            </div>
                                            <span style={{ fontSize: '0.75rem', color: dark.textMuted }}>
                                                {Math.round(progressPercent(s.overall_progress))}%
                                            </span>
                                        </div>
                                    </td>
                                    <td style={{ padding: '0.75rem 1rem', fontSize: '0.75rem', color: dark.textMuted }}>
                                        {s.phases_completed.length}/{PHASE_ORDER.length}
                                    </td>
                                    <td style={{ padding: '0.75rem 1rem' }}>
                                        <div style={{ display: 'flex', gap: '0.5rem', fontSize: '0.75rem' }}>
                                            <span style={{ color: dark.success }}>{s.total_tests_passed} pass</span>
                                            <span style={{ color: dark.textFaint }}>/</span>
                                            <span style={{ color: dark.danger }}>{s.total_tests_failed} fail</span>
                                        </div>
                                    </td>
                                    <td style={{ padding: '0.75rem 1rem' }}>
                                        <span style={{
                                            fontSize: '0.8rem',
                                            fontWeight: 600,
                                            color: s.coverage_percentage >= 80 ? dark.success :
                                                s.coverage_percentage >= 50 ? dark.warning : dark.danger,
                                        }}>
                                            {Math.round(s.coverage_percentage)}%
                                        </span>
                                    </td>
                                    <td style={{
                                        padding: '0.75rem 1rem',
                                        fontSize: '0.75rem',
                                        color: dark.textMuted,
                                        whiteSpace: 'nowrap',
                                    }}>
                                        {formatTimeAgo(s.created_at)}
                                    </td>
                                    <td style={{
                                        padding: '0.75rem 1rem',
                                        fontSize: '0.75rem',
                                        color: dark.textMuted,
                                        whiteSpace: 'nowrap',
                                    }}>
                                        {formatDuration(s.started_at, s.completed_at)}
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            </div>
        );
    };

    // -- Start Form --
    const renderStartForm = () => (
        <div style={{ ...cardStyle, marginBottom: '1.5rem' }}>
            <div style={{
                display: 'flex',
                alignItems: 'center',
                gap: '0.5rem',
                marginBottom: '1.25rem',
            }}>
                <Rocket size={20} style={{ color: dark.primary }} />
                <span style={{ fontWeight: 700, fontSize: '1rem' }}>Start New Session</span>
            </div>

            <div className="autopilot-start-grid">
                {/* Left column */}
                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                    <div>
                        <label style={labelStyle}>Target URLs (one per line) *</label>
                        <textarea
                            value={formUrls}
                            onChange={e => setFormUrls(e.target.value)}
                            placeholder={'https://example.com\nhttps://example.com/app'}
                            rows={3}
                            style={{
                                ...inputStyle,
                                resize: 'vertical',
                                fontFamily: 'monospace',
                                fontSize: '0.8rem',
                            }}
                        />
                    </div>

                    <div>
                        <label style={labelStyle}>Login URL (optional)</label>
                        <input
                            type="text"
                            value={formLoginUrl}
                            onChange={e => setFormLoginUrl(e.target.value)}
                            placeholder="https://example.com/login"
                            style={inputStyle}
                        />
                    </div>

                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem' }}>
                        <div>
                            <label style={labelStyle}>Username</label>
                            <input
                                type="text"
                                value={formUsername}
                                onChange={e => setFormUsername(e.target.value)}
                                placeholder="user@example.com"
                                style={inputStyle}
                            />
                        </div>
                        <div>
                            <label style={labelStyle}>Password</label>
                            <input
                                type="password"
                                value={formPassword}
                                onChange={e => setFormPassword(e.target.value)}
                                placeholder="Password"
                                style={inputStyle}
                            />
                        </div>
                    </div>

                    <div>
                        <label style={labelStyle}>Instructions (optional)</label>
                        <textarea
                            value={formInstructions}
                            onChange={e => setFormInstructions(e.target.value)}
                            placeholder="Focus on the checkout flow, ignore admin pages..."
                            rows={2}
                            style={{
                                ...inputStyle,
                                resize: 'vertical',
                            }}
                        />
                    </div>
                </div>

                {/* Right column */}
                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                    <div>
                        <label style={labelStyle}>Strategy</label>
                        <select
                            value={formStrategy}
                            onChange={e => setFormStrategy(e.target.value)}
                            style={selectStyle}
                        >
                            <option value="goal_directed">Goal Directed</option>
                            <option value="breadth_first">Breadth First</option>
                            <option value="depth_first">Depth First</option>
                        </select>
                    </div>

                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem' }}>
                        <div>
                            <label style={labelStyle}>Max Specs</label>
                            <input
                                type="number"
                                value={formMaxSpecs}
                                onChange={e => setFormMaxSpecs(parseInt(e.target.value) || 50)}
                                min={1}
                                max={200}
                                style={inputStyle}
                            />
                        </div>
                        <div>
                            <label style={labelStyle}>Parallel</label>
                            <input
                                type="number"
                                value={formParallel}
                                onChange={e => setFormParallel(parseInt(e.target.value) || 2)}
                                min={1}
                                max={5}
                                style={inputStyle}
                            />
                        </div>
                    </div>

                    <div>
                        <label style={labelStyle}>Priority Threshold</label>
                        <select
                            value={formPriorityThreshold}
                            onChange={e => setFormPriorityThreshold(e.target.value)}
                            style={selectStyle}
                        >
                            <option value="critical">Critical only</option>
                            <option value="high">High and above</option>
                            <option value="medium">Medium and above</option>
                            <option value="low">All priorities</option>
                        </select>
                    </div>

                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem', marginTop: '0.25rem' }}>
                        <label style={{
                            display: 'flex',
                            alignItems: 'center',
                            gap: '0.5rem',
                            cursor: 'pointer',
                            fontSize: '0.85rem',
                            color: dark.textSecondary,
                        }}>
                            <input
                                type="checkbox"
                                checked={formReactiveMode}
                                onChange={e => setFormReactiveMode(e.target.checked)}
                                style={{
                                    accentColor: dark.primary,
                                    width: '16px',
                                    height: '16px',
                                }}
                            />
                            Reactive Mode
                            <span style={{
                                fontSize: '0.7rem',
                                color: dark.textMuted,
                                marginLeft: '0.25rem',
                            }}>
                                (ask questions between phases)
                            </span>
                        </label>

                        <label style={{
                            display: 'flex',
                            alignItems: 'center',
                            gap: '0.5rem',
                            cursor: 'pointer',
                            fontSize: '0.85rem',
                            color: dark.textSecondary,
                        }}>
                            <input
                                type="checkbox"
                                checked={formHybridHealing}
                                onChange={e => setFormHybridHealing(e.target.checked)}
                                style={{
                                    accentColor: dark.primary,
                                    width: '16px',
                                    height: '16px',
                                }}
                            />
                            Hybrid Healing
                            <span style={{
                                fontSize: '0.7rem',
                                color: dark.textMuted,
                                marginLeft: '0.25rem',
                            }}>
                                (Native + Ralph escalation)
                            </span>
                        </label>
                    </div>
                </div>
            </div>

            {error && (
                <div style={{
                    marginTop: '1rem',
                    padding: '0.5rem 0.75rem',
                    background: dark.dangerSoft,
                    borderRadius: '6px',
                    fontSize: '0.8rem',
                    color: dark.danger,
                    display: 'flex',
                    alignItems: 'center',
                    gap: '0.375rem',
                }}>
                    <AlertTriangle size={14} />
                    {error}
                </div>
            )}

            <div style={{ marginTop: '1.25rem', display: 'flex', justifyContent: 'flex-end' }}>
                <button
                    onClick={startAutoPilot}
                    disabled={starting || !formUrls.trim()}
                    style={{
                        ...primaryButtonStyle,
                        padding: '0.65rem 1.5rem',
                        opacity: starting || !formUrls.trim() ? 0.55 : 1,
                        cursor: starting || !formUrls.trim() ? 'not-allowed' : 'pointer',
                        boxShadow: starting || !formUrls.trim() ? 'none' : primaryButtonStyle.boxShadow,
                    }}
                >
                    {starting ? (
                        <>
                            <Loader2 size={18} style={{ animation: 'spin 1s linear infinite' }} />
                            Starting...
                        </>
                    ) : (
                        <>
                            <Rocket size={18} />
                            Start Auto Pilot
                        </>
                    )}
                </button>
            </div>
        </div>
    );

    // ============ LOADING STATE ============
    if (loading || projectLoading) {
        return (
            <PageLayout tier="wide">
                <ListPageSkeleton rows={4} />
            </PageLayout>
        );
    }

    if (loadError && sessions.length === 0 && !session) {
        return (
            <PageLayout tier="wide" style={{ paddingBottom: '4rem' }}>
                <style>{autoPilotStyles}</style>
                <div className="autopilot-page" style={workspaceStyle}>
                    <AutoPilotHeader
                        title="Auto Pilot"
                        subtitle="End-to-end automated pipeline: explore, generate requirements, create test specs, and run tests."
                    />
                    <EmptyState
                        icon={<AlertTriangle size={28} />}
                        title="Auto Pilot data did not load"
                        description={loadError}
                        action={
                            <button onClick={fetchSessions} style={primaryButtonStyle}>
                                <RefreshCw size={16} />
                                Retry
                            </button>
                        }
                    />
                </div>
            </PageLayout>
        );
    }

    // ============ ACTIVE SESSION VIEW ============
    if (activeSessionId && session) {
        const isRunning = session.status === 'running';
        const isPaused = session.status === 'paused';
        const isAwaitingInput = session.status === 'awaiting_input';
        const canResume = session.can_resume && !isRunning;
        const isActive = isRunning || isPaused || isAwaitingInput;

        return (
            <PageLayout tier="wide" style={{ paddingBottom: '4rem' }}>
                <style>{autoPilotStyles}</style>
                <div className="autopilot-page" style={workspaceStyle}>
                    <AutoPilotHeader
                        title="Auto Pilot"
                        subtitle={`Session ${session.id.slice(0, 8)}... - ${session.entry_urls[0]?.replace(/^https?:\/\//, '') || 'Unknown'}`}
                        actions={
                        <>
                            {isRunning && (
                                <button
                                    onClick={pauseSession}
                                    style={secondaryButtonStyle}
                                >
                                    <Pause size={16} />
                                    Pause
                                </button>
                            )}
                            {canResume && (
                                <button
                                    onClick={resumeSession}
                                    style={primaryButtonStyle}
                                    title={session.resume_reason || 'Resume Auto Pilot'}
                                >
                                    <Play size={16} />
                                    {session.status === 'failed' ? 'Retry Phase' : 'Resume'}
                                </button>
                            )}
                            {isActive && (
                                <button
                                    onClick={cancelSession}
                                    style={dangerButtonStyle}
                                >
                                    <Square size={14} />
                                    Cancel
                                </button>
                            )}
                            <button
                                onClick={backToList}
                                style={secondaryButtonStyle}
                            >
                                <ArrowLeft size={16} />
                                Back
                            </button>
                        </>
                    }
                    />

                {/* Session status bar */}
                    <div className="autopilot-statusbar animate-in stagger-1">
                        {[
                            { label: 'Status', value: <StatusBadge status={session.status} /> },
                            { label: 'Started', value: formatTimeAgo(session.started_at) },
                            { label: 'Duration', value: formatDuration(session.started_at, session.completed_at) },
                            { label: 'Overall progress', value: `${Math.round(progressPercent(session.overall_progress))}%` },
                            ...(session.failed_phase ? [{ label: 'Failed phase', value: PHASE_LABELS[session.failed_phase] || session.failed_phase }] : []),
                        ].map(item => (
                            <div key={item.label} style={{ ...cardStyle, padding: '0.85rem 1rem' }}>
                                <div style={{
                                    fontSize: '0.68rem',
                                    fontWeight: 700,
                                    color: dark.textMuted,
                                    textTransform: 'uppercase',
                                    letterSpacing: '0.04em',
                                    marginBottom: '0.35rem',
                                }}>
                                    {item.label}
                                </div>
                                <div style={{ color: dark.text, fontSize: '0.92rem', fontWeight: 700 }}>
                                    {item.value}
                                </div>
                            </div>
                        ))}
                    </div>

                    {session.error_message && (
                        <div className="animate-in stagger-1" style={{
                            ...cardStyle,
                            marginBottom: '1rem',
                            border: `1px solid ${dark.dangerBorder}`,
                            background: dark.dangerSoft,
                            color: dark.danger,
                            fontSize: '0.85rem',
                            fontWeight: 600,
                        }}>
                            {session.error_message}
                            {session.can_resume && session.resume_reason && (
                                <div style={{ marginTop: '0.4rem', color: dark.textSecondary, fontWeight: 500 }}>
                                    {session.resume_reason}
                                </div>
                            )}
                        </div>
                    )}

                    {isPaused && (
                        <div className="animate-in stagger-1" style={{
                            ...cardStyle,
                            marginBottom: '1rem',
                            border: `1px solid ${dark.warningBorder}`,
                            background: dark.warningSoft,
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'space-between',
                            gap: '1rem',
                            flexWrap: 'wrap',
                        }}>
                            <div>
                                <div style={{
                                    color: dark.warning,
                                    fontSize: '0.9rem',
                                    fontWeight: 800,
                                    marginBottom: '0.25rem',
                                }}>
                                    Auto Pilot paused
                                </div>
                                <div style={{ color: dark.textSecondary, fontSize: '0.82rem' }}>
                                    {session.resume_reason || 'The pipeline is paused and can be resumed.'}
                                </div>
                            </div>
                            <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
                                <button
                                    onClick={resumeSession}
                                    disabled={!session.can_resume}
                                    style={{
                                        ...primaryButtonStyle,
                                        opacity: session.can_resume ? 1 : 0.55,
                                        cursor: session.can_resume ? 'pointer' : 'not-allowed',
                                    }}
                                >
                                    <Play size={16} />
                                    Resume
                                </button>
                                <button onClick={cancelSession} style={dangerButtonStyle}>
                                    <Square size={14} />
                                    Cancel
                                </button>
                            </div>
                        </div>
                    )}

                {/* Phase Timeline */}
                <div className="animate-in stagger-2">
                    {renderPhaseTimeline()}
                </div>

                {/* Question Panel */}
                <div className="animate-in stagger-3">
                    {renderQuestionPanel()}
                </div>

                {/* Live Browser */}
                <div className="animate-in stagger-3">
                    {renderLiveBrowserPanel()}
                </div>

                {/* Stats Cards */}
                <div className="animate-in stagger-3">
                    {renderStatsCards()}
                </div>

                {/* Phase Detail */}
                <div className="animate-in stagger-4">
                    {renderPhaseDetail()}
                </div>

                {/* Task Tables */}
                <div className="animate-in stagger-4">
                    {renderSpecTasksTable()}
                    {renderTestTasksTable()}
                </div>

                {/* Answered Questions History */}
                {questions.filter(q => q.status === 'answered').length > 0 && (
                    <div className="animate-in stagger-4" style={{ ...cardStyle, marginBottom: '1rem', padding: 0, overflow: 'hidden' }}>
                        <div style={{
                            padding: '1rem 1.25rem',
                            borderBottom: `1px solid ${dark.border}`,
                            display: 'flex',
                            alignItems: 'center',
                            gap: '0.5rem',
                        }}>
                            <MessageCircle size={16} style={{ color: dark.violet }} />
                            <span style={{ fontWeight: 600, fontSize: '0.9rem' }}>Question History</span>
                        </div>
                        <div style={{ padding: '0.5rem 0' }}>
                            {questions.filter(q => q.status === 'answered').map(q => (
                                <div key={q.id} style={{
                                    padding: '0.75rem 1.25rem',
                                    borderBottom: `1px solid ${dark.border}`,
                                }}>
                                    <div style={{
                                        fontSize: '0.8rem',
                                        color: dark.textSecondary,
                                        marginBottom: '0.375rem',
                                    }}>
                                        <span style={{ color: dark.textMuted, marginRight: '0.5rem' }}>
                                            [{PHASE_LABELS[q.phase_name] || q.phase_name}]
                                        </span>
                                        {q.question_text}
                                    </div>
                                    <div style={{
                                        fontSize: '0.8rem',
                                        color: dark.success,
                                        display: 'flex',
                                        alignItems: 'center',
                                        gap: '0.375rem',
                                    }}>
                                        <ChevronRight size={12} />
                                        {q.answer_text}
                                    </div>
                                </div>
                            ))}
                        </div>
                    </div>
                )}
                    <TaskDetailDialog
                        open={taskDetailOpen}
                        onOpenChange={setTaskDetailDialogOpen}
                        selectedTask={selectedTask}
                        loading={taskDetailLoading}
                        error={taskDetailError}
                    />
                </div>
            </PageLayout>
        );
    }

    // ============ DEFAULT VIEW (List + Form) ============
    return (
        <PageLayout tier="wide" style={{ paddingBottom: '4rem' }}>
            <style>{autoPilotStyles}</style>
            <div className="autopilot-page" style={workspaceStyle}>
                <AutoPilotHeader
                    title="Auto Pilot"
                    subtitle="End-to-end automated pipeline: explore, generate requirements, create test specs, and run tests."
                    actions={
                    <button
                        onClick={fetchSessions}
                        style={secondaryButtonStyle}
                    >
                        <RefreshCw size={16} />
                        Refresh
                    </button>
                }
                />

                {loadError && (
                    <div style={{
                        ...cardStyle,
                        marginBottom: '1rem',
                        borderColor: dark.dangerBorder,
                        background: dark.dangerSoft,
                        color: dark.danger,
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        gap: '1rem',
                    }}>
                        <span style={{ display: 'inline-flex', alignItems: 'center', gap: '0.5rem' }}>
                            <AlertTriangle size={16} />
                            {loadError}
                        </span>
                        <button onClick={fetchSessions} style={secondaryButtonStyle}>
                            <RefreshCw size={14} />
                            Retry
                        </button>
                    </div>
                )}

            {/* Start Form */}
                <div className="animate-in stagger-2">
                    {renderStartForm()}
                </div>

            {/* Session History */}
                <div className="animate-in stagger-3">
                    {renderSessionHistory()}
                </div>
            </div>
        </PageLayout>
    );
}
