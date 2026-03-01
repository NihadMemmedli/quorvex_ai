'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import { useProject } from '@/contexts/ProjectContext';
import { API_BASE } from '@/lib/api';
import { fetchWithAuth } from '@/contexts/AuthContext';

export interface WorkflowProgress {
    explorations: number;
    requirements: number;
    rtmCoverage: number | null; // percentage or null if no RTM
    specs: number;
    runs: number;
    successRate: number;
}

const CACHE_TTL = 60_000; // 60 seconds

let cachedData: { progress: WorkflowProgress; projectId: string | null; timestamp: number } | null = null;

export function useWorkflowProgress() {
    const { currentProject } = useProject();
    const [progress, setProgress] = useState<WorkflowProgress | null>(null);
    const [isLoading, setIsLoading] = useState(true);
    const fetchingRef = useRef(false);

    const fetchProgress = useCallback(async () => {
        const projectId = currentProject?.id || null;

        // Check cache
        if (cachedData && cachedData.projectId === projectId && Date.now() - cachedData.timestamp < CACHE_TTL) {
            setProgress(cachedData.progress);
            setIsLoading(false);
            return;
        }

        if (fetchingRef.current) return;
        fetchingRef.current = true;

        const projectParam = projectId ? `?project_id=${encodeURIComponent(projectId)}` : '';

        try {
            const results = await Promise.allSettled([
                // Dashboard stats (specs, runs, success rate)
                fetchWithAuth(`${API_BASE}/dashboard${projectParam}`)
                    .then(r => r.ok ? r.json() : null)
                    .catch(() => null),

                // Exploration count
                fetchWithAuth(`${API_BASE}/exploration${projectParam}`)
                    .then(r => r.ok ? r.json() : [])
                    .catch(() => []),

                // Requirements stats
                fetchWithAuth(`${API_BASE}/requirements/stats${projectParam}`)
                    .then(r => r.ok ? r.json() : null)
                    .catch(() => null),

                // RTM coverage
                fetchWithAuth(`${API_BASE}/rtm/coverage${projectParam}`)
                    .then(r => r.ok ? r.json() : null)
                    .catch(() => null),
            ]);

            const dashboard = results[0].status === 'fulfilled' ? results[0].value : null;
            const explorations = results[1].status === 'fulfilled' ? results[1].value : [];
            const reqStats = results[2].status === 'fulfilled' ? results[2].value : null;
            const rtmData = results[3].status === 'fulfilled' ? results[3].value : null;

            const newProgress: WorkflowProgress = {
                explorations: Array.isArray(explorations) ? explorations.length : 0,
                requirements: reqStats?.total ?? 0,
                rtmCoverage: rtmData?.coverage_percentage ?? null,
                specs: dashboard?.total_specs ?? 0,
                runs: dashboard?.total_runs ?? 0,
                successRate: dashboard?.success_rate ?? 0,
            };

            cachedData = { progress: newProgress, projectId, timestamp: Date.now() };
            setProgress(newProgress);
        } catch {
            // Keep previous state
        } finally {
            setIsLoading(false);
            fetchingRef.current = false;
        }
    }, [currentProject?.id]);

    useEffect(() => {
        fetchProgress();
    }, [fetchProgress]);

    return { progress, isLoading, refresh: fetchProgress };
}
