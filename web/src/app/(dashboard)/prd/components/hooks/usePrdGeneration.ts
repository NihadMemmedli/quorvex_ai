'use client';

import { useState, useCallback, useEffect, useRef } from 'react';
import { API_BASE } from '@/lib/api';
import type { GenerationResult, PrdSettings } from '../types';

const API = `${API_BASE}/api`;

function parseUtcTimestamp(timestamp: string | null | undefined): Date | undefined {
    if (!timestamp) return undefined;
    if (!timestamp.endsWith('Z') && !timestamp.includes('+') && !timestamp.includes('-', 10)) {
        return new Date(timestamp + 'Z');
    }
    return new Date(timestamp);
}

export function usePrdGeneration(projectName: string | undefined, settings: PrdSettings) {
    const [results, setResults] = useState<Record<string, GenerationResult>>({});
    const [generatedSpecs, setGeneratedSpecs] = useState<string[]>([]);
    const pollingRef = useRef<Set<number>>(new Set());

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
                for (const gen of data) {
                    if (!historyMap[gen.feature_name]) {
                        historyMap[gen.feature_name] = {
                            success: gen.status === 'completed',
                            timestamp: parseUtcTimestamp(gen.completed_at),
                            error: gen.error_message || undefined,
                            status: gen.status,
                            stage: gen.current_stage || undefined,
                            message: gen.stage_message || undefined,
                            generationId: gen.id,
                        };
                        if (gen.status === 'completed' && gen.spec_path) {
                            specs.push(gen.spec_path);
                        }
                    }
                }
                setResults(historyMap);
                setGeneratedSpecs(specs);
            } catch (err) {
                console.error('Failed to fetch generation history:', err);
            }
        };

        fetchHistory();
    }, [projectName]);

    // Polling for a single generation
    const pollGeneration = useCallback((generationId: number, featureName: string) => {
        if (pollingRef.current.has(generationId)) return;
        pollingRef.current.add(generationId);

        let polls = 0;
        const maxPolls = 300;
        const interval = 2000;

        const poll = async () => {
            try {
                const res = await fetch(`${API}/prd/generation/${generationId}`);
                if (!res.ok) return;
                const data = await res.json();

                setResults(prev => ({
                    ...prev,
                    [featureName]: {
                        success: data.status === 'completed',
                        timestamp: parseUtcTimestamp(data.completed_at),
                        error: data.error_message || undefined,
                        status: data.status,
                        stage: data.current_stage,
                        message: data.stage_message,
                        generationId: data.id,
                    },
                }));

                if (data.status === 'pending' || data.status === 'running') {
                    polls++;
                    if (polls < maxPolls) setTimeout(poll, interval);
                    else pollingRef.current.delete(generationId);
                } else {
                    pollingRef.current.delete(generationId);
                    if (data.status === 'completed' && data.spec_path) {
                        setGeneratedSpecs(prev =>
                            prev.includes(data.spec_path) ? prev : [...prev, data.spec_path]
                        );
                    }
                }
            } catch (err) {
                console.error('Polling error:', err);
                pollingRef.current.delete(generationId);
            }
        };

        poll();
    }, []);

    // Generate plan for a single feature
    const generate = useCallback(async (featureName: string): Promise<boolean> => {
        if (!projectName) return false;
        try {
            const res = await fetch(`${API}/prd/${projectName}/generate-plan`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    feature: featureName,
                    target_url: settings.useLiveValidation ? settings.targetUrl : undefined,
                    login_url: settings.useLiveValidation && settings.loginUrl ? settings.loginUrl : undefined,
                    credentials: settings.useLiveValidation && settings.username && settings.password
                        ? { username: settings.username, password: settings.password }
                        : undefined,
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
