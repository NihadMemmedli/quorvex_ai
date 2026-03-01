'use client';

import { useState, useEffect, useCallback } from 'react';
import type { PrdSettings } from '../types';

const DEFAULT_SETTINGS: PrdSettings = {
    targetUrl: '',
    loginUrl: '',
    username: '',
    password: '',
    useLiveValidation: false,
    useNativeAgents: true,
    targetFeatures: 15,
};

function getStorageKey(projectId: string | undefined): string {
    return `prd_settings_${projectId || 'global'}`;
}

export function usePrdSettings(projectId: string | undefined) {
    const [settings, setSettings] = useState<PrdSettings>(DEFAULT_SETTINGS);

    // Load from localStorage when project changes
    useEffect(() => {
        if (!projectId) return;
        try {
            const saved = localStorage.getItem(getStorageKey(projectId));
            if (saved) {
                const parsed = JSON.parse(saved);
                setSettings(prev => ({
                    ...prev,
                    targetUrl: parsed.targetUrl || '',
                    loginUrl: parsed.loginUrl || '',
                    username: parsed.username || '',
                    password: '',
                    useLiveValidation: parsed.useLiveValidation || false,
                    useNativeAgents: parsed.useNativeAgents ?? true,
                    targetFeatures: parsed.targetFeatures || 15,
                }));
            }
        } catch {
            // ignore parse errors
        }
    }, [projectId]);

    // Auto-save to localStorage on change (exclude password)
    useEffect(() => {
        if (!projectId) return;
        const { password, ...persistable } = settings;
        localStorage.setItem(getStorageKey(projectId), JSON.stringify(persistable));
    }, [settings, projectId]);

    const updateSetting = useCallback(<K extends keyof PrdSettings>(key: K, value: PrdSettings[K]) => {
        setSettings(prev => ({ ...prev, [key]: value }));
    }, []);

    const resetSettings = useCallback(() => {
        setSettings(DEFAULT_SETTINGS);
    }, []);

    return { settings, updateSetting, resetSettings };
}
