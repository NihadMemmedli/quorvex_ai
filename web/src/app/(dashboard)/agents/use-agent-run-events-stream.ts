import { useEffect, useRef, type MutableRefObject } from 'react';
import {
    agentRunEventsStreamUrl,
} from './agents-api';
import {
    LIVE_AGENT_STATUSES,
    type AgentRun,
    type AgentRunEvent,
} from './agents-model';

export function useAgentRunEventsStream(options: {
    selectedRunId: string | null;
    activeRun: AgentRun | null;
    projectId?: string | null;
    agentEventsRef: MutableRefObject<AgentRunEvent[]>;
    fetchRun: (runId: string) => Promise<void>;
    fetchAgentEvents: (runId: string, afterSequence?: number) => Promise<void>;
    fetchAgentTrace: (runId: string) => Promise<void>;
    fetchHistory: () => Promise<void>;
    mergeAgentEvents: (incoming: AgentRunEvent[]) => void;
    mergeProgressFromAgentEvent: (event: AgentRunEvent) => void;
}) {
    const {
        selectedRunId,
        activeRun,
        projectId,
        agentEventsRef,
        fetchRun,
        fetchAgentEvents,
        fetchAgentTrace,
        fetchHistory,
        mergeAgentEvents,
        mergeProgressFromAgentEvent,
    } = options;
    const agentEventSourceRef = useRef<EventSource | null>(null);
    const agentEventReconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

    useEffect(() => {
        return () => {
            agentEventSourceRef.current?.close();
            if (agentEventReconnectTimerRef.current) clearTimeout(agentEventReconnectTimerRef.current);
        };
    }, []);

    useEffect(() => {
        if (!selectedRunId || !activeRun || !LIVE_AGENT_STATUSES.has(activeRun.status)) return;
        let cancelled = false;
        let attempts = 0;

        const backfillEvents = async () => {
            const lastSequence = agentEventsRef.current.reduce((max, item) => Math.max(max, item.sequence), 0);
            await fetchAgentEvents(selectedRunId, lastSequence);
        };

        const scheduleReconnect = () => {
            if (cancelled) return;
            if (agentEventReconnectTimerRef.current) clearTimeout(agentEventReconnectTimerRef.current);
            attempts += 1;
            const delay = Math.min(15000, 750 * Math.pow(2, Math.min(attempts, 5)));
            agentEventReconnectTimerRef.current = setTimeout(async () => {
                agentEventReconnectTimerRef.current = null;
                await backfillEvents();
                await fetchRun(selectedRunId);
                connect();
            }, delay);
        };

        const connect = () => {
            if (cancelled || agentEventSourceRef.current) return;
            const lastSequence = agentEventsRef.current.reduce((max, item) => Math.max(max, item.sequence), 0);
            const source = new EventSource(agentRunEventsStreamUrl(selectedRunId, {
                afterSequence: lastSequence,
                projectId,
            }));
            agentEventSourceRef.current = source;
            source.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data);
                    attempts = 0;
                    mergeAgentEvents([data]);
                    mergeProgressFromAgentEvent(data);
                    if (data.event_type === 'agent_note') {
                        window.setTimeout(() => {
                            void fetchRun(selectedRunId);
                        }, 250);
                    }
                } catch {
                    source.close();
                    agentEventSourceRef.current = null;
                    scheduleReconnect();
                }
            };
            source.addEventListener('complete', () => {
                source.close();
                agentEventSourceRef.current = null;
                window.setTimeout(() => {
                    void fetchRun(selectedRunId);
                    void fetchAgentTrace(selectedRunId);
                    void fetchHistory();
                }, 500);
            });
            source.onerror = () => {
                source.close();
                agentEventSourceRef.current = null;
                scheduleReconnect();
            };
        };

        void backfillEvents();
        connect();
        return () => {
            cancelled = true;
            if (agentEventReconnectTimerRef.current) clearTimeout(agentEventReconnectTimerRef.current);
            agentEventReconnectTimerRef.current = null;
            agentEventSourceRef.current?.close();
            agentEventSourceRef.current = null;
        };
    }, [activeRun?.status, agentEventsRef, fetchAgentEvents, fetchAgentTrace, fetchHistory, fetchRun, mergeAgentEvents, mergeProgressFromAgentEvent, projectId, selectedRunId]);
}
