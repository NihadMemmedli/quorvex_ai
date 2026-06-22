import { useCallback, useEffect, useRef, useState, type Dispatch, type SetStateAction } from 'react';
import {
    fetchAgentRunResolvingTestRun,
    fetchAgentRunEvents,
    fetchAgentRunTrace,
    fetchExploratorySpecs,
} from './agents-api';
import {
    LIVE_AGENT_STATUSES,
    isAgentRunTerminal,
    type AgentRun,
    type AgentRunEvent,
    type AgentTraceBundle,
    type SpecResult,
} from './agents-model';

export function mergeAgentEventLists(existing: AgentRunEvent[], incoming: AgentRunEvent[]) {
    const bySequence = new Map<number, AgentRunEvent>();
    [...existing, ...incoming].forEach(item => bySequence.set(item.sequence, item));
    return [...bySequence.values()].sort((a, b) => a.sequence - b.sequence);
}

export function useAgentRunDetail(options: {
    selectedRunId: string | null;
    projectId?: string | null;
    activeRun: AgentRun | null;
    traceTab: string;
    fetchHistory: () => Promise<void>;
    setActiveRun: Dispatch<SetStateAction<AgentRun | null>>;
    setAgentEvents: Dispatch<SetStateAction<AgentRunEvent[]>>;
    setAgentTrace: Dispatch<SetStateAction<AgentTraceBundle | null>>;
    setTraceLoading: Dispatch<SetStateAction<boolean>>;
    setSpecResult: Dispatch<SetStateAction<SpecResult | null>>;
    setTraceSearch: Dispatch<SetStateAction<string>>;
    setTraceSpanType: Dispatch<SetStateAction<string>>;
    onResolvedRunId?: (runId: string) => void;
}) {
    const {
        selectedRunId,
        projectId,
        activeRun,
        traceTab,
        fetchHistory,
        setActiveRun,
        setAgentEvents,
        setAgentTrace,
        setTraceLoading,
        setSpecResult,
        setTraceSearch,
        setTraceSpanType,
        onResolvedRunId,
    } = options;
    const runDetailAbortRef = useRef<AbortController | null>(null);
    const traceRequestIdRef = useRef(0);
    const activeRunPollInFlightRef = useRef(false);
    const [runLoading, setRunLoading] = useState(false);
    const [runError, setRunError] = useState<string | null>(null);
    const activeRunId = activeRun?.id;
    const activeRunStatus = activeRun?.status;

    const mergeAgentEvents = useCallback((incoming: AgentRunEvent[]) => {
        setAgentEvents(prev => mergeAgentEventLists(prev, incoming));
    }, [setAgentEvents]);

    const fetchAgentEvents = useCallback(async (id: string, afterSequence = 0) => {
        try {
            const data = await fetchAgentRunEvents(id, { limit: 200, afterSequence, projectId });
            if (afterSequence > 0) mergeAgentEvents(data);
            else setAgentEvents(data);
        } catch (e) {
            console.error('Failed to fetch agent events', e);
        }
    }, [mergeAgentEvents, projectId, setAgentEvents]);

    const fetchAgentTrace = useCallback(async (id: string) => {
        const requestId = traceRequestIdRef.current + 1;
        traceRequestIdRef.current = requestId;
        setTraceLoading(true);
        try {
            const data = await fetchAgentRunTrace(id, projectId);
            if (traceRequestIdRef.current === requestId) {
                setAgentTrace(data);
            }
        } catch (e) {
            console.error('Failed to fetch agent trace', e);
        } finally {
            if (traceRequestIdRef.current === requestId) {
                setTraceLoading(false);
            }
        }
    }, [projectId, setAgentTrace, setTraceLoading]);

    const fetchSpecs = useCallback(async (runId: string) => {
        try {
            const data = await fetchExploratorySpecs(runId);
            if (data.specs) {
                setSpecResult(data);
            }
        } catch (e) {
            console.error('Failed to fetch specs', e);
        }
    }, [setSpecResult]);

    const fetchRun = useCallback(async (id: string, fetchOptions: { showLoading?: boolean; loadRelated?: boolean } = {}) => {
        runDetailAbortRef.current?.abort();
        const controller = new AbortController();
        runDetailAbortRef.current = controller;
        if (fetchOptions.showLoading) setRunLoading(true);
        setRunError(null);
        try {
            const data = await fetchAgentRunResolvingTestRun(id, { projectId, signal: controller.signal });
            if (controller.signal.aborted) return;
            if (data.id !== id) onResolvedRunId?.(data.id);
            setActiveRun(prev => {
                const wasActive = prev?.id === data.id && !isAgentRunTerminal(prev.status);
                const isTerminal = isAgentRunTerminal(data.status);
                if (wasActive && isTerminal) {
                    void fetchHistory();
                    void fetchAgentEvents(data.id);
                    void fetchAgentTrace(data.id);
                }
                return data;
            });
            if (fetchOptions.loadRelated) {
                void fetchAgentEvents(data.id);
                void fetchSpecs(data.id);
            }
        } catch (e) {
            if (e instanceof DOMException && e.name === 'AbortError') return;
            console.error('Failed to fetch run', e);
            setRunError('Run not found or unavailable. Check project selection.');
            setActiveRun(prev => prev?.id === id ? null : prev);
        } finally {
            if (fetchOptions.showLoading && !controller.signal.aborted) setRunLoading(false);
        }
    }, [fetchAgentEvents, fetchAgentTrace, fetchHistory, fetchSpecs, onResolvedRunId, projectId, setActiveRun]);

    useEffect(() => {
        if (!selectedRunId) {
            setRunLoading(false);
            setRunError(null);
            setActiveRun(null);
            setSpecResult(null);
            setAgentEvents([]);
            setAgentTrace(null);
            setTraceSearch('');
            setTraceSpanType('');
            return;
        }

        runDetailAbortRef.current?.abort();
        setRunError(null);
        void fetchRun(selectedRunId, { showLoading: true, loadRelated: true });

        return () => {
            runDetailAbortRef.current?.abort();
        };
    }, [fetchAgentEvents, fetchRun, fetchSpecs, selectedRunId, setActiveRun, setAgentEvents, setAgentTrace, setSpecResult, setTraceSearch, setTraceSpanType]);

    useEffect(() => {
        if (!selectedRunId || !activeRun) return;
        if (traceTab === 'timeline' && !isAgentRunTerminal(activeRun.status)) return;
        void fetchAgentTrace(selectedRunId);
    }, [activeRun, fetchAgentTrace, selectedRunId, traceTab]);

    useEffect(() => {
        if (!selectedRunId || !activeRunId || activeRunId !== selectedRunId || !LIVE_AGENT_STATUSES.has(activeRunStatus || '')) return;
        const poll = async () => {
            if (activeRunPollInFlightRef.current) return;
            activeRunPollInFlightRef.current = true;
            try {
                await fetchRun(selectedRunId);
            } finally {
                activeRunPollInFlightRef.current = false;
            }
        };
        const interval = window.setInterval(() => {
            void poll();
        }, 3000);
        return () => {
            window.clearInterval(interval);
        };
    }, [activeRunId, activeRunStatus, fetchRun, selectedRunId]);

    useEffect(() => {
        return () => {
            runDetailAbortRef.current?.abort();
        };
    }, []);

    return {
        fetchRun,
        fetchAgentEvents,
        fetchAgentTrace,
        fetchSpecs,
        mergeAgentEvents,
        runLoading,
        runError,
    };
}
