'use client';

import { useState, useCallback } from 'react';
import { API_BASE } from '@/lib/api';
import type { TestResult } from '../types';

const API = `${API_BASE}/api`;

export function usePrdTestRunner(targetUrl: string, useLiveValidation: boolean, useNativeAgents: boolean) {
    const [testResults, setTestResults] = useState<TestResult[]>([]);
    const [isRunning, setIsRunning] = useState(false);
    const [pipelineStatus, setPipelineStatus] = useState<'idle' | 'running' | 'complete'>('idle');

    const runTests = useCallback(async (specs: string[]) => {
        if (specs.length === 0) return;
        setIsRunning(true);
        setPipelineStatus('running');
        const results: TestResult[] = [];

        for (const spec of specs) {
            try {
                const res = await fetch(`${API}/prd/generate-test`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        spec_path: spec,
                        target_url: useLiveValidation ? targetUrl : undefined,
                    }),
                });
                const data = await res.json();

                if (useNativeAgents && data.test_path) {
                    results.push({ spec, ...data, status: 'running', native: true });
                    setTestResults([...results]);

                    try {
                        const runRes = await fetch(`${API}/prd/run-test`, {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({
                                test_path: data.test_path,
                                heal: true,
                                max_attempts: 3,
                            }),
                        });
                        const runData = await runRes.json();
                        results[results.length - 1] = {
                            spec,
                            ...data,
                            native: true,
                            status: runData.passed ? 'passed' : 'failed',
                            passed: runData.passed,
                            attempts: runData.attempts,
                            healed: runData.healed,
                            error_log: runData.error_log,
                        };
                        setTestResults([...results]);
                    } catch (runError) {
                        results[results.length - 1] = {
                            ...results[results.length - 1],
                            status: 'run_error',
                            message: String(runError),
                        };
                        setTestResults([...results]);
                    }
                } else {
                    results.push({ spec, ...data });
                    setTestResults([...results]);
                }
            } catch (e) {
                results.push({ spec, status: 'error', message: String(e) });
                setTestResults([...results]);
            }
        }

        setIsRunning(false);
        setPipelineStatus('complete');
    }, [targetUrl, useLiveValidation, useNativeAgents]);

    const resetTests = useCallback(() => {
        setTestResults([]);
        setIsRunning(false);
        setPipelineStatus('idle');
    }, []);

    return {
        testResults,
        isRunning,
        pipelineStatus,
        runTests,
        resetTests,
    };
}
