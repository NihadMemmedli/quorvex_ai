'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useProject } from '@/contexts/ProjectContext';
import { fetchWithAuth } from '@/contexts/AuthContext';
import { API_BASE } from '@/lib/api';

export interface DashboardStats {
    total_specs: number;
    total_runs: number;
    success_rate: number;
    pass_rate: number;
    avg_duration_seconds: number;
    flaky_test_count: number;
    last_run: string;
    slowest_tests?: Array<{ spec_name: string; avg_duration: number; run_count: number; max_duration: number }>;
    flaky_tests?: Array<{ spec_name: string; passed: number; failed: number; total: number; flakiness_rate: number }>;
    healing_stats?: {
        overall?: {
            total_heals_attempted: number;
            total_heals_succeeded: number;
            success_rate: number;
        };
    };
}

export interface AutoPilotSessionSummary {
    id: string;
    project_id: string | null;
    entry_urls: string[];
    status: string;
    current_phase: string | null;
    overall_progress: number;
    current_phase_progress: number;
    total_pages_discovered: number;
    total_flows_discovered: number;
    total_requirements_generated: number;
    total_specs_generated: number;
    total_tests_generated: number;
    total_tests_passed: number;
    total_tests_failed: number;
    coverage_percentage?: number;
    error_message: string | null;
    created_at: string;
    started_at?: string | null;
    completed_at: string | null;
    config?: {
        live_browser?: {
            active?: boolean;
            agent_task_id?: string;
            activity_label?: string;
            message?: string;
            status?: string;
        };
        [key: string]: unknown;
    };
    can_resume?: boolean;
    resume_reason?: string | null;
    failed_phase?: string | null;
}

export interface AutoPilotQuestionSummary {
    id: number;
    session_id: string;
    phase_name: string;
    question_text: string;
    status: string;
    auto_continue_at: string | null;
}

export interface AgentQueueSummary {
    mode?: 'redis' | 'browser_pool' | string;
    active?: number;
    queued?: number;
    workers_alive?: number;
    stale_running?: number;
    oldest_queued_age_seconds?: number | null;
    by_status?: Record<string, number>;
    running_tasks?: AgentQueueTaskSummary[];
}

export interface AgentQueueTaskSummary {
    id: string;
    status?: string;
    worker_id?: string | null;
    agent_type?: string | null;
    operation_type?: string | null;
    created_at?: string | null;
    started_at?: string | null;
    timeout_seconds?: number | null;
    heartbeat_alive?: boolean;
    progress?: {
        phase?: string;
        activity_label?: string;
        status?: string;
        message?: string;
        current_stage?: string;
        tool_calls?: number;
        browser_tool_calls?: number;
        interactions?: number;
        last_tool?: string;
        last_tool_label?: string;
    };
}

const DEFAULT_DASHBOARD_STATS: DashboardStats = {
    total_specs: 0,
    total_runs: 0,
    success_rate: 0,
    pass_rate: 0,
    avg_duration_seconds: 0,
    flaky_test_count: 0,
    last_run: 'Never',
    slowest_tests: [],
    flaky_tests: [],
};

const ACTIVE_STATUSES = new Set(['pending', 'running', 'awaiting_input', 'paused']);
const POLL_INTERVAL_MS = 15000;

function normalizeProgress(value: number | null | undefined): number {
    const numeric = typeof value === 'number' && Number.isFinite(value) ? value : 0;
    return Math.max(0, Math.min(100, numeric <= 1 ? numeric * 100 : numeric));
}

function isRuntimeActiveSession(session: AutoPilotSessionSummary): boolean {
    if (!ACTIVE_STATUSES.has(session.status)) return false;
    if (
        (session.status === 'pending' || session.status === 'running') &&
        session.can_resume &&
        /not active in memory/i.test(session.resume_reason || '')
    ) {
        return false;
    }
    return true;
}

export function useCommandCenterData() {
    const { currentProject } = useProject();
    const [dashboard, setDashboard] = useState<DashboardStats>(DEFAULT_DASHBOARD_STATS);
    const [sessions, setSessions] = useState<AutoPilotSessionSummary[]>([]);
    const [questionsBySession, setQuestionsBySession] = useState<Record<string, AutoPilotQuestionSummary[]>>({});
    const [queue, setQueue] = useState<AgentQueueSummary | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const shouldPollRef = useRef(false);
    const hasLoadedRef = useRef(false);

    const load = useCallback(async (options?: { silent?: boolean }) => {
        const projectParam = currentProject?.id ? `?project_id=${encodeURIComponent(currentProject.id)}` : '';
        const silent = options?.silent === true || hasLoadedRef.current;

        if (!silent) {
            setLoading(true);
        }
        if (!silent) {
            setError(null);
        }

        try {
            const [dashboardRes, sessionsRes, queueRes] = await Promise.all([
                fetchWithAuth(`${API_BASE}/dashboard${projectParam}`),
                fetchWithAuth(`${API_BASE}/autopilot/sessions${projectParam}`),
                fetchWithAuth(`${API_BASE}/api/agents/queue-status`),
            ]);

            const dashboardData = dashboardRes.ok ? await dashboardRes.json() : DEFAULT_DASHBOARD_STATS;
            const sessionsData = sessionsRes.ok ? await sessionsRes.json() : [];
            const queueData = queueRes.ok ? await queueRes.json() : null;
            const visibleSessions: AutoPilotSessionSummary[] = Array.isArray(sessionsData) ? sessionsData.slice(0, 12) : [];
            const liveSessions = visibleSessions.some(isRuntimeActiveSession);
            const liveQueue = Boolean((queueData?.active ?? 0) > 0 || (queueData?.queued ?? 0) > 0);

            const questionPairs = await Promise.all(
                visibleSessions
                    .filter(isRuntimeActiveSession)
                    .map(async session => {
                        const res = await fetchWithAuth(`${API_BASE}/autopilot/${session.id}/questions?status=pending`);
                        const questions = res.ok ? await res.json() : [];
                        return [session.id, Array.isArray(questions) ? questions : []] as const;
                    })
            );

            setDashboard({ ...DEFAULT_DASHBOARD_STATS, ...dashboardData });
            setSessions(visibleSessions.map(session => ({
                ...session,
                overall_progress: normalizeProgress(session.overall_progress),
                current_phase_progress: normalizeProgress(session.current_phase_progress),
            })));
            setQuestionsBySession(Object.fromEntries(questionPairs));
            setQueue(queueData);
            shouldPollRef.current = liveSessions || liveQueue;
            hasLoadedRef.current = true;
        } catch (err) {
            console.error(err);
            if (!silent) {
                setError('Failed to load command center data');
            }
        } finally {
            setLoading(false);
        }
    }, [currentProject?.id]);

    useEffect(() => {
        let cancelled = false;

        hasLoadedRef.current = false;
        shouldPollRef.current = false;

        load({ silent: false }).catch(() => {
            if (!cancelled) {
                setError('Failed to load command center data');
                setLoading(false);
            }
        });

        const interval = setInterval(() => {
            if (cancelled || !shouldPollRef.current) return;
            if (typeof document !== 'undefined' && document.visibilityState !== 'visible') return;
            load({ silent: true }).catch(() => {});
        }, POLL_INTERVAL_MS);

        return () => {
            cancelled = true;
            clearInterval(interval);
        };
    }, [load]);

    const derived = useMemo(() => {
        const activeSessions = sessions.filter(isRuntimeActiveSession);
        const failedSessions = sessions.filter(session => session.status === 'failed');
        const completedSessions = sessions.filter(session => session.status === 'completed');
        const pendingQuestions = Object.values(questionsBySession).flat().filter(question => question.status === 'pending');
        const awaitingInput = activeSessions.filter(session => session.status === 'awaiting_input' || questionsBySession[session.id]?.length > 0);

        return {
            activeSessions,
            failedSessions,
            completedSessions,
            pendingQuestions,
            awaitingInput,
            hasAnySessions: sessions.length > 0,
        };
    }, [questionsBySession, sessions]);

    return {
        dashboard,
        sessions,
        questionsBySession,
        queue,
        loading,
        error,
        reload: load,
        ...derived,
    };
}
