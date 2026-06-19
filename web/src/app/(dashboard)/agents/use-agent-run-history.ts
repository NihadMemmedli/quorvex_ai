import { useCallback, useEffect, useRef, useState } from 'react';
import type {
    AgentHistoryStatusFilter,
    AgentHistoryTypeFilter,
    AgentWorkspaceQueryState,
} from './agents-workspace-state';
import { EMPTY_AGENT_HISTORY_COUNTS, fetchAgentRunHistory } from './agents-api';
import type { AgentRun } from './agents-model';

type WorkspaceQueryUpdater = (patch: Partial<Record<keyof AgentWorkspaceQueryState, string | boolean | null | undefined>>) => void;

export function useAgentRunHistory(options: {
    projectId?: string | null;
    projectLoading: boolean;
    queryState: Pick<AgentWorkspaceQueryState, 'q' | 'status' | 'type'>;
    updateWorkspaceQuery: WorkspaceQueryUpdater;
}) {
    const { projectId, projectLoading, queryState, updateWorkspaceQuery } = options;
    const [history, setHistory] = useState<AgentRun[]>([]);
    const [historyTotal, setHistoryTotal] = useState(0);
    const [historyCounts, setHistoryCounts] = useState(EMPTY_AGENT_HISTORY_COUNTS);
    const [historyNextCursor, setHistoryNextCursor] = useState<string | null>(null);
    const [historyLoading, setHistoryLoading] = useState(false);
    const [historyError, setHistoryError] = useState<string | null>(null);
    const [historySearch, setHistorySearch] = useState('');
    const [debouncedHistorySearch, setDebouncedHistorySearch] = useState('');
    const [historyStatusFilter, setHistoryStatusFilter] = useState<AgentHistoryStatusFilter>('all');
    const [historyTypeFilter, setHistoryTypeFilter] = useState<AgentHistoryTypeFilter>('all');
    const historyAbortRef = useRef<AbortController | null>(null);
    const historyRequestIdRef = useRef(0);

    const fetchHistory = useCallback(async (fetchOptions: { append?: boolean; cursor?: string | null } = {}) => {
        if (projectLoading) return;
        historyAbortRef.current?.abort();
        const controller = new AbortController();
        historyAbortRef.current = controller;
        const requestId = historyRequestIdRef.current + 1;
        historyRequestIdRef.current = requestId;
        setHistoryLoading(true);
        setHistoryError(null);
        try {
            const payload = await fetchAgentRunHistory({
                projectId,
                status: historyStatusFilter,
                type: historyTypeFilter,
                query: debouncedHistorySearch,
                cursor: fetchOptions.cursor,
                signal: controller.signal,
            });
            if (controller.signal.aborted || historyRequestIdRef.current !== requestId) return;
            setHistory(prev => fetchOptions.append ? [...prev, ...(payload.items || [])] : (payload.items || []));
            setHistoryTotal(Number(payload.total || 0));
            setHistoryCounts(payload.counts || EMPTY_AGENT_HISTORY_COUNTS);
            setHistoryNextCursor(payload.next_cursor || null);
        } catch (e) {
            if (e instanceof DOMException && e.name === 'AbortError') return;
            const message = e instanceof Error ? e.message : 'Failed to fetch history';
            setHistoryError(message);
            console.error('Failed to fetch history', e);
        } finally {
            if (historyRequestIdRef.current === requestId) {
                setHistoryLoading(false);
            }
        }
    }, [debouncedHistorySearch, historyStatusFilter, historyTypeFilter, projectId, projectLoading]);

    const loadMoreHistory = useCallback(() => {
        if (!historyNextCursor || historyLoading) return;
        void fetchHistory({ append: true, cursor: historyNextCursor });
    }, [fetchHistory, historyLoading, historyNextCursor]);

    const updateHistorySearch = useCallback((value: string) => {
        setHistorySearch(value);
    }, []);

    const updateHistoryStatusFilter = useCallback((value: AgentHistoryStatusFilter) => {
        setHistoryStatusFilter(value);
        updateWorkspaceQuery({ status: value });
    }, [updateWorkspaceQuery]);

    const updateHistoryTypeFilter = useCallback((value: AgentHistoryTypeFilter) => {
        setHistoryTypeFilter(value);
        updateWorkspaceQuery({ type: value });
    }, [updateWorkspaceQuery]);

    const applyHistoryQueryState = useCallback((state: Pick<AgentWorkspaceQueryState, 'q' | 'status' | 'type'>) => {
        setHistoryStatusFilter(state.status);
        setHistoryTypeFilter(state.type);
        setHistorySearch(state.q);
        setDebouncedHistorySearch(state.q);
    }, []);

    useEffect(() => {
        applyHistoryQueryState(queryState);
    }, [applyHistoryQueryState, queryState.q, queryState.status, queryState.type]);

    useEffect(() => {
        const timer = window.setTimeout(() => {
            setDebouncedHistorySearch(historySearch);
            updateWorkspaceQuery({ q: historySearch });
        }, 300);
        return () => window.clearTimeout(timer);
    }, [historySearch, updateWorkspaceQuery]);

    useEffect(() => {
        if (projectLoading) return;
        void fetchHistory();
    }, [fetchHistory, projectLoading]);

    useEffect(() => {
        return () => {
            historyAbortRef.current?.abort();
        };
    }, []);

    return {
        history,
        setHistory,
        historyTotal,
        historyCounts,
        historyNextCursor,
        historyLoading,
        historyError,
        historySearch,
        historyStatusFilter,
        historyTypeFilter,
        fetchHistory,
        loadMoreHistory,
        updateHistorySearch,
        updateHistoryStatusFilter,
        updateHistoryTypeFilter,
        applyHistoryQueryState,
    };
}
