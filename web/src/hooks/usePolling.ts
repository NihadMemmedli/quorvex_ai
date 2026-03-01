import { useEffect, useRef, useCallback, useState } from 'react';

interface UsePollingOptions {
    /** Polling interval in ms (default: 2000) */
    interval?: number;
    /** Whether polling is enabled (default: true) */
    enabled?: boolean;
    /** Max consecutive errors before stopping (default: 10) */
    maxErrors?: number;
    /** Max backoff interval in ms (default: 30000) */
    maxBackoff?: number;
}

interface UsePollingReturn {
    isPolling: boolean;
    attemptCount: number;
    errorCount: number;
    reset: () => void;
    stop: () => void;
}

/**
 * Generic polling hook with auto-cleanup, skip-if-inflight, and exponential backoff.
 */
export function usePolling(
    pollFn: () => Promise<void>,
    options: UsePollingOptions = {}
): UsePollingReturn {
    const {
        interval = 2000,
        enabled = true,
        maxErrors = 10,
        maxBackoff = 30000,
    } = options;

    const [isPolling, setIsPolling] = useState(false);
    const [attemptCount, setAttemptCount] = useState(0);
    const [errorCount, setErrorCount] = useState(0);

    const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
    const inflightRef = useRef(false);
    const errorCountRef = useRef(0);
    const stoppedRef = useRef(false);
    const pollFnRef = useRef(pollFn);
    pollFnRef.current = pollFn;

    const clearTimer = useCallback(() => {
        if (timerRef.current) {
            clearTimeout(timerRef.current);
            timerRef.current = null;
        }
    }, []);

    const scheduleNext = useCallback(() => {
        if (stoppedRef.current) return;
        const backoff = errorCountRef.current > 0
            ? Math.min(interval * Math.pow(2, errorCountRef.current), maxBackoff)
            : interval;
        timerRef.current = setTimeout(async () => {
            if (inflightRef.current || stoppedRef.current) {
                scheduleNext();
                return;
            }
            inflightRef.current = true;
            setAttemptCount(c => c + 1);
            try {
                await pollFnRef.current();
                errorCountRef.current = 0;
                setErrorCount(0);
            } catch {
                errorCountRef.current += 1;
                setErrorCount(errorCountRef.current);
                if (errorCountRef.current >= maxErrors) {
                    stoppedRef.current = true;
                    setIsPolling(false);
                    inflightRef.current = false;
                    return;
                }
            }
            inflightRef.current = false;
            scheduleNext();
        }, backoff);
    }, [interval, maxBackoff, maxErrors]);

    const stop = useCallback(() => {
        stoppedRef.current = true;
        clearTimer();
        setIsPolling(false);
    }, [clearTimer]);

    const reset = useCallback(() => {
        stoppedRef.current = false;
        errorCountRef.current = 0;
        setErrorCount(0);
        setAttemptCount(0);
        clearTimer();
        if (enabled) {
            setIsPolling(true);
            scheduleNext();
        }
    }, [enabled, clearTimer, scheduleNext]);

    useEffect(() => {
        if (enabled) {
            stoppedRef.current = false;
            setIsPolling(true);
            scheduleNext();
        } else {
            stop();
        }
        return () => {
            clearTimer();
            inflightRef.current = false;
        };
    }, [enabled, scheduleNext, stop, clearTimer]);

    return { isPolling, attemptCount, errorCount, reset, stop };
}
