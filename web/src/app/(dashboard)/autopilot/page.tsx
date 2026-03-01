'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import {
    Rocket, Play, Pause, Square, Clock, Globe, FileText, CheckCircle2,
    AlertTriangle, Loader2, ChevronRight, X, ArrowLeft, RefreshCw,
    MessageCircle, Zap, BarChart2, Target, List
} from 'lucide-react';
import { useProject } from '@/contexts/ProjectContext';
import { API_BASE } from '@/lib/api';
import { toast } from 'sonner';
import { PageLayout } from '@/components/ui/page-layout';
import { PageHeader } from '@/components/ui/page-header';
import { EmptyState } from '@/components/ui/empty-state';
import { ListPageSkeleton } from '@/components/ui/page-skeleton';

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
    run_id: string | null;
    status: string;
    current_stage: string | null;
    healing_attempt: number;
    test_path: string | null;
    passed: boolean | null;
    error_summary: string | null;
    created_at: string;
    started_at: string | null;
    completed_at: string | null;
}

// ============ STATUS COLORS ============

const statusColors: Record<string, { bg: string; color: string }> = {
    pending: { bg: 'rgba(156, 163, 175, 0.1)', color: 'rgba(255,255,255,0.5)' },
    running: { bg: 'rgba(59, 130, 246, 0.1)', color: '#3b82f6' },
    generating: { bg: 'rgba(59, 130, 246, 0.1)', color: '#3b82f6' },
    completed: { bg: 'rgba(34, 197, 94, 0.1)', color: '#22c55e' },
    passed: { bg: 'rgba(34, 197, 94, 0.1)', color: '#22c55e' },
    failed: { bg: 'rgba(239, 68, 68, 0.1)', color: '#ef4444' },
    error: { bg: 'rgba(239, 68, 68, 0.1)', color: '#ef4444' },
    skipped: { bg: 'rgba(245, 158, 11, 0.1)', color: '#f59e0b' },
    awaiting_input: { bg: 'rgba(245, 158, 11, 0.1)', color: '#f59e0b' },
    paused: { bg: 'rgba(245, 158, 11, 0.1)', color: '#f59e0b' },
    cancelled: { bg: 'rgba(156, 163, 175, 0.1)', color: 'rgba(255,255,255,0.5)' },
};

const PHASE_ORDER = ['exploration', 'requirements', 'spec_generation', 'test_generation', 'reporting'];
const PHASE_LABELS: Record<string, string> = {
    exploration: 'Exploration',
    requirements: 'Requirements',
    spec_generation: 'Spec Generation',
    test_generation: 'Test Generation',
    reporting: 'Reporting',
};
const PHASE_ICONS: Record<string, typeof Globe> = {
    exploration: Globe,
    requirements: FileText,
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

function formatDate(iso: string): string {
    const date = new Date(iso.endsWith('Z') ? iso : iso + 'Z');
    return date.toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: 'numeric' });
}

function getStatusStyle(status: string): { bg: string; color: string } {
    return statusColors[status] || statusColors.pending;
}

// ============ INLINE STYLE CONSTANTS ============

const cardStyle: React.CSSProperties = {
    background: '#12121a',
    border: '1px solid rgba(255,255,255,0.06)',
    borderRadius: '12px',
    padding: '1.25rem',
};

const inputStyle: React.CSSProperties = {
    width: '100%',
    padding: '0.6rem 0.75rem',
    borderRadius: '8px',
    fontSize: '0.875rem',
    border: '1px solid rgba(255,255,255,0.08)',
    background: '#0a0a0f',
    color: '#fff',
    outline: 'none',
    transition: 'border-color 0.2s',
};

const labelStyle: React.CSSProperties = {
    display: 'block',
    fontSize: '0.8rem',
    fontWeight: 500,
    marginBottom: '0.4rem',
    color: 'rgba(255,255,255,0.7)',
};

const selectStyle: React.CSSProperties = {
    ...inputStyle,
    appearance: 'none' as const,
    backgroundImage: `url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='rgba(255,255,255,0.5)' stroke-width='2'%3E%3Cpolyline points='6 9 12 15 18 9'/%3E%3C/svg%3E")`,
    backgroundRepeat: 'no-repeat',
    backgroundPosition: 'right 0.75rem center',
    paddingRight: '2rem',
};

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
    const [loading, setLoading] = useState(true);
    const [starting, setStarting] = useState(false);
    const [error, setError] = useState<string | null>(null);

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
            const res = await fetch(`${API_BASE}/autopilot/sessions${projectParam}`);
            if (res.ok) {
                const data = await res.json();
                setSessions(Array.isArray(data) ? data : data.sessions || []);
            }
        } catch (err) {
            console.error('Failed to fetch autopilot sessions:', err);
        } finally {
            setLoading(false);
        }
    }, [currentProject?.id, projectLoading]);

    const fetchSessionDetail = useCallback(async (sessionId: string) => {
        try {
            const [sessionRes, phasesRes, questionsRes, specTasksRes, testTasksRes] = await Promise.all([
                fetch(`${API_BASE}/autopilot/${sessionId}`),
                fetch(`${API_BASE}/autopilot/${sessionId}/phases`),
                fetch(`${API_BASE}/autopilot/${sessionId}/questions`),
                fetch(`${API_BASE}/autopilot/${sessionId}/spec-tasks`),
                fetch(`${API_BASE}/autopilot/${sessionId}/test-tasks`),
            ]);

            if (sessionRes.ok) {
                const data = await sessionRes.json();
                setSession(data);
            }
            if (phasesRes.ok) {
                const data = await phasesRes.json();
                setPhases(Array.isArray(data) ? data : data.phases || []);
            }
            if (questionsRes.ok) {
                const data = await questionsRes.json();
                setQuestions(Array.isArray(data) ? data : data.questions || []);
            }
            if (specTasksRes.ok) {
                const data = await specTasksRes.json();
                setSpecTasks(Array.isArray(data) ? data : data.tasks || []);
            }
            if (testTasksRes.ok) {
                const data = await testTasksRes.json();
                setTestTasks(Array.isArray(data) ? data : data.tasks || []);
            }
        } catch (err) {
            console.error('Failed to fetch session detail:', err);
        }
    }, []);

    // Initial load
    useEffect(() => {
        fetchSessions();
    }, [fetchSessions]);

    // Polling for active session
    useEffect(() => {
        if (!activeSessionId) return;

        fetchSessionDetail(activeSessionId);

        const isActive = session?.status === 'running' || session?.status === 'awaiting_input';
        if (!isActive && session) return;

        const pollMs = session?.status === 'running' ? 3000 : 10000;
        const interval = setInterval(() => fetchSessionDetail(activeSessionId), pollMs);
        return () => clearInterval(interval);
    }, [activeSessionId, session?.status, fetchSessionDetail]);

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
                config: {
                    strategy: formStrategy,
                    max_specs: formMaxSpecs,
                    priority_threshold: formPriorityThreshold,
                    parallel_generation: formParallel,
                    hybrid_healing: formHybridHealing,
                },
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
        setAnsweringQuestionId(questionId);
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
                alert(`Failed to submit answer: ${err.detail}`);
            }
        } catch (e) {
            alert(`Failed to submit answer: ${e instanceof Error ? e.message : 'Network error'}`);
        } finally {
            setAnsweringQuestionId(null);
        }
    };

    const pauseSession = async () => {
        if (!activeSessionId) return;
        try {
            await fetch(`${API_BASE}/autopilot/${activeSessionId}/pause`, { method: 'POST' });
            fetchSessionDetail(activeSessionId);
        } catch (e) {
            console.error('Failed to pause:', e);
        }
    };

    const resumeSession = async () => {
        if (!activeSessionId) return;
        try {
            await fetch(`${API_BASE}/autopilot/${activeSessionId}/resume`, { method: 'POST' });
            fetchSessionDetail(activeSessionId);
        } catch (e) {
            console.error('Failed to resume:', e);
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

    const viewSession = (s: AutoPilotSession) => {
        setActiveSessionId(s.id);
        setSession(s);
        setPhases([]);
        setQuestions([]);
        setSpecTasks([]);
        setTestTasks([]);
    };

    const backToList = () => {
        setActiveSessionId(null);
        setSession(null);
        setPhases([]);
        setQuestions([]);
        setSpecTasks([]);
        setTestTasks([]);
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
                <div style={{
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

                        let dotBg = 'rgba(255,255,255,0.1)';
                        let dotBorder = 'rgba(255,255,255,0.15)';
                        let dotColor = 'rgba(255,255,255,0.3)';
                        let labelColor = 'rgba(255,255,255,0.4)';

                        if (isCompleted) {
                            dotBg = 'rgba(34, 197, 94, 0.15)';
                            dotBorder = '#22c55e';
                            dotColor = '#22c55e';
                            labelColor = '#22c55e';
                        } else if (isFailed) {
                            dotBg = 'rgba(239, 68, 68, 0.15)';
                            dotBorder = '#ef4444';
                            dotColor = '#ef4444';
                            labelColor = '#ef4444';
                        } else if (isCurrent) {
                            dotBg = 'rgba(59, 130, 246, 0.15)';
                            dotBorder = '#3b82f6';
                            dotColor = '#3b82f6';
                            labelColor = '#3b82f6';
                        }

                        return (
                            <div key={phase} style={{
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
                                        background: isCompleted ? '#22c55e' : 'rgba(255,255,255,0.08)',
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
                                    transition: 'all 0.3s',
                                    ...(isCurrent ? {
                                        boxShadow: '0 0 12px rgba(59, 130, 246, 0.3)',
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
                    background: 'rgba(255,255,255,0.06)',
                    borderRadius: '3px',
                    overflow: 'hidden',
                }}>
                    <div style={{
                        height: '100%',
                        width: `${session.overall_progress}%`,
                        background: 'linear-gradient(90deg, #3b82f6, #22c55e)',
                        borderRadius: '3px',
                        transition: 'width 0.5s ease',
                    }} />
                </div>
                <div style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    marginTop: '0.375rem',
                    fontSize: '0.7rem',
                    color: 'rgba(255,255,255,0.4)',
                }}>
                    <span>Overall Progress</span>
                    <span>{Math.round(session.overall_progress)}%</span>
                </div>
            </div>
        );
    };

    // -- Question Panel --
    const renderQuestionPanel = () => {
        const pendingQuestion = questions.find(q => q.status === 'pending');
        if (!pendingQuestion || session?.status !== 'awaiting_input') return null;

        return (
            <div style={{
                ...cardStyle,
                marginBottom: '1rem',
                border: '1px solid rgba(245, 158, 11, 0.3)',
                background: 'linear-gradient(135deg, rgba(245, 158, 11, 0.05), #12121a)',
            }}>
                <div style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '0.5rem',
                    marginBottom: '0.75rem',
                }}>
                    <MessageCircle size={18} style={{ color: '#f59e0b' }} />
                    <span style={{ fontWeight: 600, fontSize: '0.9rem', color: '#f59e0b' }}>
                        Input Required
                    </span>
                    {countdown !== null && countdown > 0 && (
                        <span style={{
                            marginLeft: 'auto',
                            fontSize: '0.75rem',
                            color: 'rgba(255,255,255,0.5)',
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
                    color: 'rgba(255,255,255,0.85)',
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
                                disabled={answeringQuestionId === pendingQuestion.id}
                                style={{
                                    padding: '0.5rem 1rem',
                                    borderRadius: '8px',
                                    border: '1px solid rgba(245, 158, 11, 0.3)',
                                    background: 'rgba(245, 158, 11, 0.08)',
                                    color: '#f59e0b',
                                    fontSize: '0.8rem',
                                    fontWeight: 500,
                                    cursor: 'pointer',
                                    transition: 'all 0.2s',
                                    opacity: answeringQuestionId === pendingQuestion.id ? 0.5 : 1,
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
                        onKeyDown={e => {
                            if (e.key === 'Enter' && customAnswer.trim()) {
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
                            if (customAnswer.trim()) {
                                answerQuestion(pendingQuestion.id, customAnswer.trim());
                            }
                        }}
                        disabled={!customAnswer.trim() || answeringQuestionId === pendingQuestion.id}
                        style={{
                            padding: '0.5rem 1rem',
                            borderRadius: '8px',
                            border: 'none',
                            background: '#f59e0b',
                            color: '#000',
                            fontWeight: 600,
                            fontSize: '0.8rem',
                            cursor: 'pointer',
                            opacity: !customAnswer.trim() || answeringQuestionId === pendingQuestion.id ? 0.5 : 1,
                        }}
                    >
                        {answeringQuestionId === pendingQuestion.id ? (
                            <Loader2 size={14} style={{ animation: 'spin 1s linear infinite' }} />
                        ) : 'Submit'}
                    </button>
                </div>
            </div>
        );
    };

    // -- Stats Cards --
    const renderStatsCards = () => {
        if (!session) return null;
        const stats = [
            { label: 'Pages', value: session.total_pages_discovered, icon: Globe, color: '#3b82f6' },
            { label: 'Flows', value: session.total_flows_discovered, icon: Zap, color: '#f59e0b' },
            { label: 'Requirements', value: session.total_requirements_generated, icon: FileText, color: '#8b5cf6' },
            { label: 'Specs', value: session.total_specs_generated, icon: List, color: '#06b6d4' },
            { label: 'Passed', value: session.total_tests_passed, icon: CheckCircle2, color: '#22c55e' },
            { label: 'Failed', value: session.total_tests_failed, icon: AlertTriangle, color: '#ef4444' },
            { label: 'Coverage', value: `${Math.round(session.coverage_percentage)}%`, icon: Target, color: '#10b981' },
        ];

        return (
            <div style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))',
                gap: '0.75rem',
                marginBottom: '1rem',
            }}>
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
                                    fontWeight: 500,
                                    color: 'rgba(255,255,255,0.5)',
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
                        <span style={{ fontWeight: 600, fontSize: '0.95rem', color: '#fff' }}>
                            {PHASE_LABELS[currentPhaseData.phase_name] || currentPhaseData.phase_name}
                        </span>
                        <StatusBadge status={currentPhaseData.status} />
                    </div>
                    <span style={{ fontSize: '0.75rem', color: 'rgba(255,255,255,0.5)' }}>
                        {currentPhaseData.items_completed} / {currentPhaseData.items_total} items
                    </span>
                </div>

                {currentPhaseData.current_step && (
                    <p style={{
                        fontSize: '0.8rem',
                        color: 'rgba(255,255,255,0.6)',
                        marginBottom: '0.75rem',
                        fontStyle: 'italic',
                    }}>
                        {currentPhaseData.current_step}
                    </p>
                )}

                {/* Phase progress bar */}
                <div style={{
                    height: '4px',
                    background: 'rgba(255,255,255,0.06)',
                    borderRadius: '2px',
                    overflow: 'hidden',
                    marginBottom: '0.5rem',
                }}>
                    <div style={{
                        height: '100%',
                        width: `${currentPhaseData.progress}%`,
                        background: '#3b82f6',
                        borderRadius: '2px',
                        transition: 'width 0.5s ease',
                    }} />
                </div>

                {currentPhaseData.error_message && (
                    <div style={{
                        padding: '0.5rem 0.75rem',
                        background: 'rgba(239, 68, 68, 0.08)',
                        borderRadius: '6px',
                        fontSize: '0.8rem',
                        color: '#ef4444',
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
                    borderBottom: '1px solid rgba(255,255,255,0.06)',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '0.5rem',
                }}>
                    <List size={16} style={{ color: '#06b6d4' }} />
                    <span style={{ fontWeight: 600, fontSize: '0.9rem' }}>Spec Generation Tasks</span>
                    <span style={{
                        marginLeft: 'auto',
                        fontSize: '0.75rem',
                        color: 'rgba(255,255,255,0.5)',
                    }}>
                        {specTasks.filter(t => t.status === 'completed').length}/{specTasks.length} completed
                    </span>
                </div>
                <div style={{ overflowX: 'auto' }}>
                    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.8rem' }}>
                        <thead>
                            <tr style={{ borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
                                {['Priority', 'Requirement', 'Status', 'Spec Name'].map(h => (
                                    <th key={h} style={{
                                        padding: '0.6rem 1rem',
                                        textAlign: 'left',
                                        fontWeight: 600,
                                        color: 'rgba(255,255,255,0.5)',
                                        fontSize: '0.7rem',
                                        textTransform: 'uppercase',
                                        letterSpacing: '0.05em',
                                    }}>
                                        {h}
                                    </th>
                                ))}
                            </tr>
                        </thead>
                        <tbody>
                            {specTasks.map(task => (
                                <tr key={task.id} style={{
                                    borderBottom: '1px solid rgba(255,255,255,0.04)',
                                    transition: 'background 0.15s',
                                }}>
                                    <td style={{ padding: '0.6rem 1rem' }}>
                                        <span style={{
                                            padding: '0.15rem 0.5rem',
                                            borderRadius: '9999px',
                                            fontSize: '0.7rem',
                                            fontWeight: 600,
                                            background: task.priority === 'critical' ? 'rgba(239,68,68,0.1)' :
                                                task.priority === 'high' ? 'rgba(245,158,11,0.1)' :
                                                    task.priority === 'medium' ? 'rgba(59,130,246,0.1)' :
                                                        'rgba(156,163,175,0.1)',
                                            color: task.priority === 'critical' ? '#ef4444' :
                                                task.priority === 'high' ? '#f59e0b' :
                                                    task.priority === 'medium' ? '#3b82f6' :
                                                        'rgba(255,255,255,0.5)',
                                            textTransform: 'capitalize',
                                        }}>
                                            {task.priority}
                                        </span>
                                    </td>
                                    <td style={{ padding: '0.6rem 1rem', color: 'rgba(255,255,255,0.8)' }}>
                                        {task.requirement_title || '-'}
                                    </td>
                                    <td style={{ padding: '0.6rem 1rem' }}>
                                        <StatusBadge status={task.status} />
                                    </td>
                                    <td style={{
                                        padding: '0.6rem 1rem',
                                        fontFamily: 'monospace',
                                        fontSize: '0.75rem',
                                        color: 'rgba(255,255,255,0.6)',
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
                    borderBottom: '1px solid rgba(255,255,255,0.06)',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '0.5rem',
                }}>
                    <Zap size={16} style={{ color: '#f59e0b' }} />
                    <span style={{ fontWeight: 600, fontSize: '0.9rem' }}>Test Generation Tasks</span>
                    <span style={{
                        marginLeft: 'auto',
                        fontSize: '0.75rem',
                        color: 'rgba(255,255,255,0.5)',
                    }}>
                        {testTasks.filter(t => t.passed === true).length} passed /
                        {testTasks.filter(t => t.passed === false).length} failed /
                        {testTasks.length} total
                    </span>
                </div>
                <div style={{ overflowX: 'auto' }}>
                    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.8rem' }}>
                        <thead>
                            <tr style={{ borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
                                {['Spec Name', 'Status', 'Stage', 'Healing', 'Duration', 'Actions'].map(h => (
                                    <th key={h} style={{
                                        padding: '0.6rem 1rem',
                                        textAlign: 'left',
                                        fontWeight: 600,
                                        color: 'rgba(255,255,255,0.5)',
                                        fontSize: '0.7rem',
                                        textTransform: 'uppercase',
                                        letterSpacing: '0.05em',
                                    }}>
                                        {h}
                                    </th>
                                ))}
                            </tr>
                        </thead>
                        <tbody>
                            {testTasks.map(task => (
                                <tr key={task.id} style={{
                                    borderBottom: '1px solid rgba(255,255,255,0.04)',
                                    transition: 'background 0.15s',
                                }}>
                                    <td style={{
                                        padding: '0.6rem 1rem',
                                        fontFamily: 'monospace',
                                        fontSize: '0.75rem',
                                        color: 'rgba(255,255,255,0.8)',
                                    }}>
                                        {task.spec_name || '-'}
                                    </td>
                                    <td style={{ padding: '0.6rem 1rem' }}>
                                        <StatusBadge status={task.passed === true ? 'passed' : task.passed === false ? 'failed' : task.status} />
                                    </td>
                                    <td style={{
                                        padding: '0.6rem 1rem',
                                        fontSize: '0.75rem',
                                        color: 'rgba(255,255,255,0.6)',
                                        textTransform: 'capitalize',
                                    }}>
                                        {task.current_stage?.replace('_', ' ') || '-'}
                                    </td>
                                    <td style={{
                                        padding: '0.6rem 1rem',
                                        fontSize: '0.75rem',
                                        color: task.healing_attempt > 0 ? '#f59e0b' : 'rgba(255,255,255,0.4)',
                                    }}>
                                        {task.healing_attempt > 0 ? `${task.healing_attempt} attempt${task.healing_attempt > 1 ? 's' : ''}` : '-'}
                                    </td>
                                    <td style={{
                                        padding: '0.6rem 1rem',
                                        fontSize: '0.75rem',
                                        color: 'rgba(255,255,255,0.5)',
                                    }}>
                                        {formatDuration(task.started_at, task.completed_at)}
                                    </td>
                                    <td style={{ padding: '0.6rem 1rem' }}>
                                        {(task.status === 'running' || task.status === 'pending') && (
                                            <button
                                                onClick={() => stopTestTask(task.id)}
                                                style={{
                                                    padding: '0.2rem 0.5rem',
                                                    borderRadius: '4px',
                                                    border: '1px solid rgba(239, 68, 68, 0.3)',
                                                    background: 'rgba(239, 68, 68, 0.1)',
                                                    color: '#ef4444',
                                                    cursor: 'pointer',
                                                    fontSize: '0.7rem',
                                                    fontWeight: 600,
                                                }}
                                                onMouseEnter={(e) => {
                                                    e.currentTarget.style.background = 'rgba(239, 68, 68, 0.2)';
                                                }}
                                                onMouseLeave={(e) => {
                                                    e.currentTarget.style.background = 'rgba(239, 68, 68, 0.1)';
                                                }}
                                            >
                                                Stop
                                            </button>
                                        )}
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
                    borderBottom: '1px solid rgba(255,255,255,0.06)',
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
                            color: 'rgba(255,255,255,0.5)',
                            padding: '0.25rem',
                        }}
                    >
                        <RefreshCw size={14} />
                    </button>
                </div>
                <div style={{ overflowX: 'auto' }}>
                    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.8rem' }}>
                        <thead>
                            <tr style={{ borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
                                {['URLs', 'Status', 'Progress', 'Phases', 'Tests', 'Coverage', 'Created', 'Duration'].map(h => (
                                    <th key={h} style={{
                                        padding: '0.6rem 1rem',
                                        textAlign: 'left',
                                        fontWeight: 600,
                                        color: 'rgba(255,255,255,0.5)',
                                        fontSize: '0.7rem',
                                        textTransform: 'uppercase',
                                        letterSpacing: '0.05em',
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
                                    style={{
                                        borderBottom: '1px solid rgba(255,255,255,0.04)',
                                        cursor: 'pointer',
                                        transition: 'background 0.15s',
                                    }}
                                    onMouseEnter={e => (e.currentTarget.style.background = 'rgba(255,255,255,0.02)')}
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
                                                    color: 'rgba(255,255,255,0.8)',
                                                    whiteSpace: 'nowrap',
                                                    overflow: 'hidden',
                                                    textOverflow: 'ellipsis',
                                                    display: 'block',
                                                }}>
                                                    {url.replace(/^https?:\/\//, '')}
                                                </span>
                                            ))}
                                            {s.entry_urls.length > 2 && (
                                                <span style={{ fontSize: '0.7rem', color: 'rgba(255,255,255,0.4)' }}>
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
                                                background: 'rgba(255,255,255,0.06)',
                                                borderRadius: '2px',
                                                overflow: 'hidden',
                                            }}>
                                                <div style={{
                                                    height: '100%',
                                                    width: `${s.overall_progress}%`,
                                                    background: '#3b82f6',
                                                    borderRadius: '2px',
                                                }} />
                                            </div>
                                            <span style={{ fontSize: '0.75rem', color: 'rgba(255,255,255,0.5)' }}>
                                                {Math.round(s.overall_progress)}%
                                            </span>
                                        </div>
                                    </td>
                                    <td style={{ padding: '0.75rem 1rem', fontSize: '0.75rem', color: 'rgba(255,255,255,0.6)' }}>
                                        {s.phases_completed.length}/5
                                    </td>
                                    <td style={{ padding: '0.75rem 1rem' }}>
                                        <div style={{ display: 'flex', gap: '0.5rem', fontSize: '0.75rem' }}>
                                            <span style={{ color: '#22c55e' }}>{s.total_tests_passed} pass</span>
                                            <span style={{ color: 'rgba(255,255,255,0.2)' }}>/</span>
                                            <span style={{ color: '#ef4444' }}>{s.total_tests_failed} fail</span>
                                        </div>
                                    </td>
                                    <td style={{ padding: '0.75rem 1rem' }}>
                                        <span style={{
                                            fontSize: '0.8rem',
                                            fontWeight: 600,
                                            color: s.coverage_percentage >= 80 ? '#22c55e' :
                                                s.coverage_percentage >= 50 ? '#f59e0b' : '#ef4444',
                                        }}>
                                            {Math.round(s.coverage_percentage)}%
                                        </span>
                                    </td>
                                    <td style={{
                                        padding: '0.75rem 1rem',
                                        fontSize: '0.75rem',
                                        color: 'rgba(255,255,255,0.5)',
                                        whiteSpace: 'nowrap',
                                    }}>
                                        {formatTimeAgo(s.created_at)}
                                    </td>
                                    <td style={{
                                        padding: '0.75rem 1rem',
                                        fontSize: '0.75rem',
                                        color: 'rgba(255,255,255,0.5)',
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
                <Rocket size={20} style={{ color: '#3b82f6' }} />
                <span style={{ fontWeight: 700, fontSize: '1rem' }}>Start New Session</span>
            </div>

            <div style={{
                display: 'grid',
                gridTemplateColumns: '1fr 1fr',
                gap: '1rem',
            }}>
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
                            color: 'rgba(255,255,255,0.7)',
                        }}>
                            <input
                                type="checkbox"
                                checked={formReactiveMode}
                                onChange={e => setFormReactiveMode(e.target.checked)}
                                style={{
                                    accentColor: '#3b82f6',
                                    width: '16px',
                                    height: '16px',
                                }}
                            />
                            Reactive Mode
                            <span style={{
                                fontSize: '0.7rem',
                                color: 'rgba(255,255,255,0.4)',
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
                            color: 'rgba(255,255,255,0.7)',
                        }}>
                            <input
                                type="checkbox"
                                checked={formHybridHealing}
                                onChange={e => setFormHybridHealing(e.target.checked)}
                                style={{
                                    accentColor: '#3b82f6',
                                    width: '16px',
                                    height: '16px',
                                }}
                            />
                            Hybrid Healing
                            <span style={{
                                fontSize: '0.7rem',
                                color: 'rgba(255,255,255,0.4)',
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
                    background: 'rgba(239, 68, 68, 0.08)',
                    borderRadius: '6px',
                    fontSize: '0.8rem',
                    color: '#ef4444',
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
                        display: 'flex',
                        alignItems: 'center',
                        gap: '0.5rem',
                        padding: '0.65rem 1.5rem',
                        borderRadius: '10px',
                        border: 'none',
                        background: starting || !formUrls.trim()
                            ? 'rgba(59, 130, 246, 0.3)'
                            : 'linear-gradient(135deg, #3b82f6, #2563eb)',
                        color: '#fff',
                        fontWeight: 600,
                        fontSize: '0.9rem',
                        cursor: starting || !formUrls.trim() ? 'not-allowed' : 'pointer',
                        transition: 'all 0.2s',
                        boxShadow: starting || !formUrls.trim() ? 'none' : '0 2px 12px rgba(59, 130, 246, 0.25)',
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

    // ============ ACTIVE SESSION VIEW ============
    if (activeSessionId && session) {
        const isRunning = session.status === 'running';
        const isPaused = session.status === 'paused';
        const isAwaitingInput = session.status === 'awaiting_input';
        const isActive = isRunning || isPaused || isAwaitingInput;

        return (
            <PageLayout tier="wide" style={{ paddingBottom: '4rem' }}>
                <PageHeader
                    title="Auto Pilot"
                    subtitle={`Session ${session.id.slice(0, 8)}... - ${session.entry_urls[0]?.replace(/^https?:\/\//, '') || 'Unknown'}`}
                    icon={<Rocket size={22} />}
                    actions={
                        <div style={{ display: 'flex', gap: '0.5rem' }}>
                            {isRunning && (
                                <button
                                    onClick={pauseSession}
                                    className="btn btn-secondary"
                                    style={{ display: 'flex', alignItems: 'center', gap: '0.375rem' }}
                                >
                                    <Pause size={16} />
                                    Pause
                                </button>
                            )}
                            {isPaused && (
                                <button
                                    onClick={resumeSession}
                                    className="btn btn-primary"
                                    style={{ display: 'flex', alignItems: 'center', gap: '0.375rem' }}
                                >
                                    <Play size={16} />
                                    Resume
                                </button>
                            )}
                            {isActive && (
                                <button
                                    onClick={cancelSession}
                                    style={{
                                        display: 'flex',
                                        alignItems: 'center',
                                        gap: '0.375rem',
                                        padding: '0.5rem 1rem',
                                        borderRadius: '8px',
                                        border: '1px solid rgba(239, 68, 68, 0.3)',
                                        background: 'rgba(239, 68, 68, 0.08)',
                                        color: '#ef4444',
                                        fontWeight: 600,
                                        fontSize: '0.85rem',
                                        cursor: 'pointer',
                                    }}
                                >
                                    <Square size={14} />
                                    Cancel
                                </button>
                            )}
                            <button
                                onClick={backToList}
                                className="btn btn-secondary"
                                style={{ display: 'flex', alignItems: 'center', gap: '0.375rem' }}
                            >
                                <ArrowLeft size={16} />
                                Back
                            </button>
                        </div>
                    }
                />

                {/* Session status bar */}
                <div className="animate-in stagger-1" style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '1rem',
                    marginBottom: '1rem',
                    padding: '0.75rem 1rem',
                    ...cardStyle,
                }}>
                    <StatusBadge status={session.status} />
                    <span style={{ fontSize: '0.8rem', color: 'rgba(255,255,255,0.5)' }}>
                        Started {formatTimeAgo(session.started_at)}
                    </span>
                    <span style={{ fontSize: '0.8rem', color: 'rgba(255,255,255,0.3)' }}>|</span>
                    <span style={{ fontSize: '0.8rem', color: 'rgba(255,255,255,0.5)' }}>
                        Duration: {formatDuration(session.started_at, session.completed_at)}
                    </span>
                    {session.error_message && (
                        <>
                            <span style={{ fontSize: '0.8rem', color: 'rgba(255,255,255,0.3)' }}>|</span>
                            <span style={{ fontSize: '0.8rem', color: '#ef4444' }}>
                                {session.error_message}
                            </span>
                        </>
                    )}
                </div>

                {/* Phase Timeline */}
                <div className="animate-in stagger-2">
                    {renderPhaseTimeline()}
                </div>

                {/* Question Panel */}
                <div className="animate-in stagger-3">
                    {renderQuestionPanel()}
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
                            borderBottom: '1px solid rgba(255,255,255,0.06)',
                            display: 'flex',
                            alignItems: 'center',
                            gap: '0.5rem',
                        }}>
                            <MessageCircle size={16} style={{ color: '#8b5cf6' }} />
                            <span style={{ fontWeight: 600, fontSize: '0.9rem' }}>Question History</span>
                        </div>
                        <div style={{ padding: '0.5rem 0' }}>
                            {questions.filter(q => q.status === 'answered').map(q => (
                                <div key={q.id} style={{
                                    padding: '0.75rem 1.25rem',
                                    borderBottom: '1px solid rgba(255,255,255,0.04)',
                                }}>
                                    <div style={{
                                        fontSize: '0.8rem',
                                        color: 'rgba(255,255,255,0.6)',
                                        marginBottom: '0.375rem',
                                    }}>
                                        <span style={{ color: 'rgba(255,255,255,0.4)', marginRight: '0.5rem' }}>
                                            [{PHASE_LABELS[q.phase_name] || q.phase_name}]
                                        </span>
                                        {q.question_text}
                                    </div>
                                    <div style={{
                                        fontSize: '0.8rem',
                                        color: '#22c55e',
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
            </PageLayout>
        );
    }

    // ============ DEFAULT VIEW (List + Form) ============
    return (
        <PageLayout tier="wide" style={{ paddingBottom: '4rem' }}>
            <PageHeader
                title="Auto Pilot"
                subtitle="End-to-end automated pipeline: Explore, generate requirements, create test specs, and run tests."
                icon={<Rocket size={22} />}
                actions={
                    <button
                        onClick={fetchSessions}
                        className="btn btn-secondary"
                        style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}
                    >
                        <RefreshCw size={16} />
                        Refresh
                    </button>
                }
            />

            {/* Start Form */}
            <div className="animate-in stagger-2">
                {renderStartForm()}
            </div>

            {/* Session History */}
            <div className="animate-in stagger-3">
                {renderSessionHistory()}
            </div>
        </PageLayout>
    );
}
