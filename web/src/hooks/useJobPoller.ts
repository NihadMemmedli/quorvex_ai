import { useState, useCallback, useRef, useEffect } from 'react';
import { usePolling } from './usePolling';

interface JobStatus {
    job_id: string;
    status: 'pending' | 'running' | 'completed' | 'failed';
    stage?: string;
    message?: string;
    result?: Record<string, unknown>;
}

interface UseJobPollerOptions {
    /** API base URL */
    apiBase: string;
    /** URL path pattern, e.g. '/load-testing/jobs/{jobId}/status' - {jobId} will be replaced */
    urlPattern: string;
    /** Polling interval in ms (default: 2000) */
    interval?: number;
    /** Called when job completes */
    onComplete?: (result: Record<string, unknown> | undefined) => void;
    /** Called when job fails */
    onFailed?: (message: string | undefined) => void;
    /** Extra headers for requests */
    headers?: Record<string, string>;
}

interface UseJobPollerReturn {
    jobId: string | null;
    status: JobStatus | null;
    isRunning: boolean;
    isCompleted: boolean;
    isFailed: boolean;
    startPolling: (jobId: string) => void;
    clear: () => void;
}

/**
 * Specialized hook for polling job status endpoints.
 * Auto-starts when jobId is set, auto-stops on terminal states.
 */
export function useJobPoller(options: UseJobPollerOptions): UseJobPollerReturn {
    const { apiBase, urlPattern, interval = 2000, onComplete, onFailed, headers } = options;

    const [jobId, setJobId] = useState<string | null>(null);
    const [status, setStatus] = useState<JobStatus | null>(null);
    const onCompleteRef = useRef(onComplete);
    const onFailedRef = useRef(onFailed);
    onCompleteRef.current = onComplete;
    onFailedRef.current = onFailed;

    const terminalRef = useRef(false);

    const pollFn = useCallback(async () => {
        if (!jobId || terminalRef.current) return;
        const url = `${apiBase}${urlPattern.replace('{jobId}', jobId)}`;
        const res = await fetch(url, { headers });
        if (!res.ok) throw new Error(`Poll failed: ${res.status}`);
        const data: JobStatus = await res.json();
        setStatus(data);

        if (data.status === 'completed') {
            terminalRef.current = true;
            onCompleteRef.current?.(data.result);
        } else if (data.status === 'failed') {
            terminalRef.current = true;
            onFailedRef.current?.(data.message);
        }
    }, [jobId, apiBase, urlPattern, headers]);

    const { stop, reset } = usePolling(pollFn, {
        interval,
        enabled: !!jobId && !terminalRef.current,
    });

    const startPolling = useCallback((newJobId: string) => {
        terminalRef.current = false;
        setStatus(null);
        setJobId(newJobId);
    }, []);

    const clear = useCallback(() => {
        stop();
        terminalRef.current = true;
        setJobId(null);
        setStatus(null);
    }, [stop]);

    // Reset polling when jobId changes
    useEffect(() => {
        if (jobId && !terminalRef.current) {
            reset();
        }
    }, [jobId, reset]);

    const isRunning = status?.status === 'running' || status?.status === 'pending';
    const isCompleted = status?.status === 'completed';
    const isFailed = status?.status === 'failed';

    return { jobId, status, isRunning, isCompleted, isFailed, startPolling, clear };
}
