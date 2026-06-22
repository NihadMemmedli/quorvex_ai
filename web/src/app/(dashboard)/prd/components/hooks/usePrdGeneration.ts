'use client';

import { useState, useCallback, useEffect, useRef } from 'react';
import { API_BASE } from '@/lib/api';
import type { GenerationResult, PrdSettings } from '../types';

const API = `${API_BASE}/api`;
const ACTIVE_GENERATION_STATUSES = new Set(['pending', 'queued', 'running']);
const MAX_POLL_FAILURES = 5;
const POLL_INTERVAL_MS = 2000;

function isActiveGenerationStatus(status: string | null | undefined): boolean {
    return ACTIVE_GENERATION_STATUSES.has(String(status || '').toLowerCase());
}

function parseUtcTimestamp(timestamp: string | null | undefined): Date | undefined {
    if (!timestamp) return undefined;
    if (!timestamp.endsWith('Z') && !timestamp.includes('+') && !timestamp.includes('-', 10)) {
        return new Date(timestamp + 'Z');
    }
    return new Date(timestamp);
}

function generationResultFromApi(gen: any): GenerationResult {
    return {
        success: gen.status === 'completed',
        createdAt: parseUtcTimestamp(gen.created_at),
        timestamp: parseUtcTimestamp(gen.completed_at),
        startedAt: parseUtcTimestamp(gen.started_at),
        completedAt: parseUtcTimestamp(gen.completed_at),
        error: gen.error_message || undefined,
        status: gen.status,
        stage: gen.current_stage || undefined,
        message: gen.stage_message || undefined,
        generationId: gen.id,
        eventsCount: gen.events_count || 0,
        latestEvent: gen.latest_event || null,
        artifacts: Array.isArray(gen.artifacts) ? gen.artifacts : [],
        latestImage: gen.latest_image || null,
        vncUrl: gen.vnc_url || null,
        browserRuntime: gen.browser_runtime || null,
        liveViewAvailable: gen.live_view_available,
        liveBrowserRequested: Boolean(gen.live_browser_requested),
        browserActivitySeen: Boolean(gen.browser_activity_seen),
        browserActive: Boolean(gen.browser_active),
        browserLastTool: gen.browser_last_tool || null,
        suspectedBrowserDialogBlock: Boolean(gen.suspected_browser_dialog_block),
        runtimeMessage: gen.runtime_message || null,
        displayDiagnostics: gen.display_diagnostics || null,
        agentTaskId: gen.agent_task_id || null,
        agentTaskStatus: gen.agent_task_status || null,
        agentWorkerId: gen.agent_worker_id || null,
        lastHeartbeatAt: parseUtcTimestamp(gen.last_heartbeat_at),
        agentQueueHealth: gen.agent_queue_health || null,
        queueTelemetry: gen.queue_telemetry || null,
        targetUrl: gen.target_url || null,
        specPath: gen.spec_path || null,
    };
}

export function usePrdGeneration(projectName: string | undefined, settings: PrdSettings) {
    const [results, setResults] = useState<Record<string, GenerationResult>>({});
    const [generatedSpecs, setGeneratedSpecs] = useState<string[]>([]);
    const pollingRef = useRef<Set<number>>(new Set());

    // Polling for a single generation
    const pollGeneration = useCallback((generationId: number, featureName: string) => {
        if (pollingRef.current.has(generationId)) return;
        pollingRef.current.add(generationId);

        let failures = 0;
        let stopped = false;

        function applyPollingUnavailable(message: string) {
            setResults(prev => ({
                ...prev,
                [featureName]: {
                    ...(prev[featureName] || {}),
                    success: false,
                    status: isActiveGenerationStatus(prev[featureName]?.status) ? prev[featureName]?.status : 'running',
                    stage: 'status_unavailable',
                    message,
                    generationId,
                },
            }));
        }

        function scheduleNextPoll() {
            if (!stopped) setTimeout(poll, POLL_INTERVAL_MS);
        }

        async function poll() {
            if (stopped) return;
            try {
                const res = await fetch(`${API}/prd/generation/${generationId}`);
                if (!res.ok) {
                    failures++;
                    if (failures >= MAX_POLL_FAILURES) {
                        applyPollingUnavailable('Generation status unavailable; reconnecting to backend status...');
                    }
                    scheduleNextPoll();
                    return;
                }

                failures = 0;
                const data = await res.json();
                const result = generationResultFromApi(data);

                setResults(prev => ({
                    ...prev,
                    [featureName]: result,
                }));

                if (isActiveGenerationStatus(data.status)) {
                    scheduleNextPoll();
                } else {
                    stopped = true;
                    pollingRef.current.delete(generationId);
                    if (data.status === 'completed' && data.spec_path) {
                        setGeneratedSpecs(prev =>
                            prev.includes(data.spec_path) ? prev : [...prev, data.spec_path]
                        );
                    }
                }
            } catch (err) {
                console.error('Polling error:', err);
                failures++;
                if (failures >= MAX_POLL_FAILURES) {
                    applyPollingUnavailable('Generation status unavailable; reconnecting to backend status...');
                }
                scheduleNextPoll();
            }
        }

        poll();
    }, []);

    // Fetch generation history on project load
    useEffect(() => {
        if (!projectName) {
            setResults({});
            setGeneratedSpecs([]);
            return;
        }

        const fetchHistory = async () => {
            try {
                const res = await fetch(`${API}/prd/${projectName}/generations`);
                if (!res.ok) return;
                const data = await res.json();
                const historyMap: Record<string, GenerationResult> = {};
                const specs: string[] = [];
                const activeGenerations: Array<{ id: number; featureName: string }> = [];
                for (const gen of data) {
                    if (!historyMap[gen.feature_name]) {
                        historyMap[gen.feature_name] = generationResultFromApi(gen);
                        if (gen.status === 'completed' && gen.spec_path) {
                            specs.push(gen.spec_path);
                        }
                        if (gen.id && isActiveGenerationStatus(gen.status)) {
                            activeGenerations.push({ id: gen.id, featureName: gen.feature_name });
                        }
                    }
                }
                setResults(historyMap);
                setGeneratedSpecs(specs);
                activeGenerations.forEach(({ id, featureName }) => pollGeneration(id, featureName));
            } catch (err) {
                console.error('Failed to fetch generation history:', err);
            }
        };

        fetchHistory();
    }, [projectName, pollGeneration]);

    // Generate plan for a single feature
    const generate = useCallback(async (featureName: string): Promise<boolean> => {
        if (!projectName) return false;
        const targetUrl = settings.targetUrl.trim();
        const liveBrowserRequested = targetUrl.length > 0;
        try {
            const res = await fetch(`${API}/prd/${projectName}/generate-plan`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    feature: featureName,
                    target_url: liveBrowserRequested ? targetUrl : undefined,
                    login_url: liveBrowserRequested && settings.loginUrl ? settings.loginUrl : undefined,
                    credentials: liveBrowserRequested && settings.username && settings.password
                        ? { username: settings.username, password: settings.password }
                        : undefined,
                    test_data_refs: settings.testDataRefs
                        ? settings.testDataRefs.split(',').map(item => item.trim()).filter(Boolean)
                        : [],
                }),
            });
            const data = await res.json();
            if (!res.ok) {
                const msg = data.detail || `Generation failed (HTTP ${res.status})`;
                setResults(prev => ({
                    ...prev,
                    [featureName]: { success: false, error: msg, status: 'failed' },
                }));
                return false;
            }
            if (data.generation_id) {
                setResults(prev => ({
                    ...prev,
                    [featureName]: {
                        success: false,
                        status: 'running',
                        stage: 'queued',
                        message: 'Generation queued...',
                        generationId: data.generation_id,
                        artifacts: [],
                        latestImage: null,
                        targetUrl: data.target_url || null,
                        liveBrowserRequested: Boolean(data.live_browser_requested),
                        liveViewAvailable: data.live_view_available ?? false,
                        browserActivitySeen: false,
                        browserActive: false,
                        browserLastTool: null,
                        suspectedBrowserDialogBlock: Boolean(data.suspected_browser_dialog_block),
                        runtimeMessage: data.runtime_message || null,
                        agentTaskId: null,
                        agentTaskStatus: null,
                        agentWorkerId: null,
                        lastHeartbeatAt: undefined,
                        agentQueueHealth: null,
                        queueTelemetry: null,
                    },
                }));
                pollGeneration(data.generation_id, featureName);
                return true;
            }
            if (data.spec_path) {
                setGeneratedSpecs(prev =>
                    prev.includes(data.spec_path) ? prev : [...prev, data.spec_path]
                );
                setResults(prev => ({
                    ...prev,
                    [featureName]: { success: true, timestamp: new Date(), status: 'completed' },
                }));
            }
            return true;
        } catch (err: any) {
            const msg = err.message || 'Failed to generate test plans';
            setResults(prev => ({
                ...prev,
                [featureName]: { success: false, error: msg, status: 'failed' },
            }));
            return false;
        }
    }, [projectName, settings, pollGeneration]);

    // Batch generate all pending features
    const batchGenerate = useCallback(async (features: { name: string }[]) => {
        const pending = features.filter(f => {
            const r = results[f.name];
            return !r || (r.status !== 'completed' && r.status !== 'running' && r.status !== 'pending' && !r.success);
        });

        // Mark all as pending first
        const updates: Record<string, GenerationResult> = {};
        for (const f of pending) {
            updates[f.name] = { success: false, status: 'pending', message: 'Queued...' };
        }
        setResults(prev => ({ ...prev, ...updates }));

        for (const f of pending) {
            await generate(f.name);
            await new Promise(r => setTimeout(r, 500));
        }
    }, [results, generate]);

    // Stop a generation
    const stop = useCallback(async (generationId: number) => {
        try {
            const res = await fetch(`${API}/prd/generation/${generationId}/stop`, { method: 'POST' });
            if (!res.ok) {
                const d = await res.json();
                throw new Error(d.detail || 'Failed to stop');
            }
            setResults(prev => {
                const next = { ...prev };
                for (const [name, result] of Object.entries(next)) {
                    if (result.generationId === generationId) {
                        next[name] = {
                            ...result,
                            success: false,
                            status: 'cancelled',
                            stage: 'cancelled',
                            message: 'Cancelled by user',
                        };
                        break;
                    }
                }
                return next;
            });
            pollingRef.current.delete(generationId);
        } catch (err: any) {
            console.error('Failed to stop generation:', err);
        }
    }, []);

    // Reset
    const resetGeneration = useCallback(() => {
        setResults({});
        setGeneratedSpecs([]);
        pollingRef.current.clear();
    }, []);

    return {
        results,
        generatedSpecs,
        generate,
        batchGenerate,
        stop,
        resetGeneration,
    };
}
