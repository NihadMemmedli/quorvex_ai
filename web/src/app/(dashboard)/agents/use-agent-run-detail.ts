import { useCallback, useEffect, useRef, type Dispatch, type SetStateAction } from 'react';
import {
    fetchAgentRun,
    fetchAgentRunEvents,
    fetchAgentRunTrace,
    fetchExploratorySpecs,
} from './agents-api';
import {
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
    } = options;
    const runDetailAbortRef = useRef<AbortController | null>(null);
    const traceRequestIdRef = useRef(0);

    const mergeAgentEvents = useCallback((incoming: AgentRunEvent[]) => {
        setAgentEvents(prev => mergeAgentEventLists(prev, incoming));
    }, [setAgentEvents]);

    const fetchAgentEvents = useCallback(async (id: string, afterSequence = 0) => {
        try {
            const data = await fetchAgentRunEvents(id, { limit: 200, afterSequence });
            if (afterSequence > 0) mergeAgentEvents(data);
            else setAgentEvents(data);
        } catch (e) {
            console.error('Failed to fetch agent events', e);
        }
    }, [mergeAgentEvents, setAgentEvents]);

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

    const fetchRun = useCallback(async (id: string) => {
        runDetailAbortRef.current?.abort();
        const controller = new AbortController();
        runDetailAbortRef.current = controller;
        try {
            const data = await fetchAgentRun(id, { projectId, signal: controller.signal });
            if (controller.signal.aborted) return;
            setActiveRun(prev => {
                const wasActive = prev?.id === id && !isAgentRunTerminal(prev.status);
                const isTerminal = isAgentRunTerminal(data.status);
                if (wasActive && isTerminal) {
                    void fetchHistory();
                    void fetchAgentEvents(id);
                    void fetchAgentTrace(id);
                }
                return data;
            });
        } catch (e) {
            if (e instanceof DOMException && e.name === 'AbortError') return;
            console.error('Failed to fetch run', e);
        }
    }, [fetchAgentEvents, fetchAgentTrace, fetchHistory, projectId, setActiveRun]);

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

    useEffect(() => {
        if (!selectedRunId) {
            setActiveRun(null);
            setSpecResult(null);
            setAgentEvents([]);
            setAgentTrace(null);
            setTraceSearch('');
            setTraceSpanType('');
            return;
        }

        runDetailAbortRef.current?.abort();
        void fetchRun(selectedRunId);
        void fetchAgentEvents(selectedRunId);
        void fetchSpecs(selectedRunId);

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
    };
}
