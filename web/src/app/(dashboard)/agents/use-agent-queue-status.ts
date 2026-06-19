import { useCallback, useEffect, useState } from 'react';
import { toast } from 'sonner';
import {
    cleanStaleAgentQueue,
    fetchAgentQueueStatus,
    queueCleanupSummary,
} from './agents-api';
import type { AgentQueueStatus } from './agents-model';
import type { AgentWorkspaceView } from './agents-workspace-state';

export function useAgentQueueStatus(options: {
    projectLoading: boolean;
    workspaceView: AgentWorkspaceView;
}) {
    const { projectLoading, workspaceView } = options;
    const [queueStatus, setQueueStatus] = useState<AgentQueueStatus | null>(null);
    const [queueLoading, setQueueLoading] = useState(false);
    const [queueCleanupLoading, setQueueCleanupLoading] = useState(false);
    const [queueError, setQueueError] = useState<string | null>(null);

    const fetchQueueStatus = useCallback(async () => {
        setQueueLoading(true);
        setQueueError(null);
        try {
            setQueueStatus(await fetchAgentQueueStatus());
        } catch (e: unknown) {
            const message = e instanceof Error ? e.message : 'Failed to fetch queue status.';
            setQueueError(message);
        } finally {
            setQueueLoading(false);
        }
    }, []);

    const cleanStaleQueueTasks = useCallback(async () => {
        setQueueCleanupLoading(true);
        try {
            const data = await cleanStaleAgentQueue();
            toast.success(queueCleanupSummary(data));
            await fetchQueueStatus();
        } catch (e: unknown) {
            const message = e instanceof Error ? e.message : 'Failed to clean stale queue tasks.';
            toast.error(message);
        } finally {
            setQueueCleanupLoading(false);
        }
    }, [fetchQueueStatus]);

    useEffect(() => {
        if (projectLoading || workspaceView !== 'queue') return;
        void fetchQueueStatus();
        const interval = window.setInterval(() => void fetchQueueStatus(), 5000);
        return () => window.clearInterval(interval);
    }, [fetchQueueStatus, projectLoading, workspaceView]);

    return {
        queueStatus,
        queueLoading,
        queueCleanupLoading,
        queueError,
        fetchQueueStatus,
        cleanStaleQueueTasks,
    };
}
