'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import { applyProjectDefaultUrl } from '@/lib/project-url';
import type { PrdSettings } from '../types';

const DEFAULT_SETTINGS: PrdSettings = {
    targetUrl: '',
    loginUrl: '',
    username: '',
    password: '',
    useLiveValidation: false,
    useNativeAgents: true,
    targetFeatures: 15,
    testDataRefs: '',
};

function getStorageKey(projectId: string | undefined): string {
    return `prd_settings_${projectId || 'global'}`;
}

function hasTargetUrl(targetUrl: string): boolean {
    return targetUrl.trim().length > 0;
}

export function usePrdSettings(projectId: string | undefined, projectDefaultUrl = '') {
    const [settings, setSettings] = useState<PrdSettings>(DEFAULT_SETTINGS);
    const previousProjectDefaultUrlRef = useRef('');

    // Load from localStorage when project changes
    useEffect(() => {
        if (!projectId) return;
        try {
            const saved = localStorage.getItem(getStorageKey(projectId));
            if (saved) {
                const parsed = JSON.parse(saved);
                const targetUrl = parsed.targetUrl || projectDefaultUrl;
                setSettings(prev => ({
                    ...prev,
                    targetUrl,
                    loginUrl: parsed.loginUrl || '',
                    username: parsed.username || '',
                    password: '',
                    useLiveValidation: hasTargetUrl(targetUrl),
                    useNativeAgents: parsed.useNativeAgents ?? true,
                    targetFeatures: parsed.targetFeatures || 15,
                    testDataRefs: parsed.testDataRefs || '',
                }));
            }
        } catch {
            // ignore parse errors
        }
    }, [projectId, projectDefaultUrl]);

    useEffect(() => {
        setSettings(prev => {
            const targetUrl = applyProjectDefaultUrl(
                prev.targetUrl,
                projectDefaultUrl,
                previousProjectDefaultUrlRef.current
            );
            previousProjectDefaultUrlRef.current = projectDefaultUrl;
            if (targetUrl === prev.targetUrl) return prev;
            return {
                ...prev,
                targetUrl,
                useLiveValidation: hasTargetUrl(targetUrl),
            };
        });
    }, [projectId, projectDefaultUrl]);

    // Auto-save to localStorage on change (exclude password)
    useEffect(() => {
        if (!projectId) return;
        const { password, ...persistable } = settings;
        localStorage.setItem(getStorageKey(projectId), JSON.stringify(persistable));
    }, [settings, projectId]);

    const updateSetting = useCallback(<K extends keyof PrdSettings>(key: K, value: PrdSettings[K]) => {
        setSettings(prev => {
            if (key === 'useLiveValidation') {
                return { ...prev, useLiveValidation: hasTargetUrl(prev.targetUrl) };
            }

            if (key === 'targetUrl') {
                const nextTargetUrl = String(value);
                return {
                    ...prev,
                    targetUrl: nextTargetUrl,
                    useLiveValidation: hasTargetUrl(nextTargetUrl),
                };
            }

            return { ...prev, [key]: value };
        });
    }, []);

    const resetSettings = useCallback(() => {
        setSettings(DEFAULT_SETTINGS);
    }, []);

    return { settings, updateSetting, resetSettings };
}
