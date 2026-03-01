'use client';

import { useState, useEffect, useCallback } from 'react';
import { usePathname } from 'next/navigation';

const STORAGE_KEY = 'command-palette-recent-pages';
const MAX_RECENT = 8;

export interface RecentPage {
    href: string;
    label: string;
    visitedAt: number;
}

function loadRecent(): RecentPage[] {
    if (typeof window === 'undefined') return [];
    try {
        const stored = localStorage.getItem(STORAGE_KEY);
        return stored ? JSON.parse(stored) : [];
    } catch {
        return [];
    }
}

function saveRecent(pages: RecentPage[]) {
    try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(pages));
    } catch {
        // localStorage full or unavailable
    }
}

/** Map pathname to a human-readable label */
function pathToLabel(path: string): string {
    const map: Record<string, string> = {
        '/': 'Overview',
        '/dashboard': 'Reporting',
        '/assistant': 'AI Assistant',
        '/prd': 'PRD',
        '/specs': 'Test Specs',
        '/specs/new': 'New Spec',
        '/runs': 'Test Runs',
        '/regression': 'Regression',
        '/regression/batches': 'Batch Reports',
        '/exploration': 'Discovery',
        '/requirements': 'Requirements',
        '/api-testing': 'API Testing',
        '/load-testing': 'Load Testing',
        '/security-testing': 'Security Testing',
        '/database-testing': 'Database Testing',
        '/llm-testing': 'LLM Testing',
        '/analytics': 'Analytics',
        '/schedules': 'Schedules',
        '/ci-cd': 'CI/CD',
        '/settings': 'Settings',
        '/admin/users': 'User Management',
    };

    if (map[path]) return map[path];

    // Generate label from path segments
    const segments = path.split('/').filter(Boolean);
    return segments.map(s => s.charAt(0).toUpperCase() + s.slice(1).replace(/-/g, ' ')).join(' > ');
}

export function useRecentPages() {
    const pathname = usePathname();
    const [recentPages, setRecentPages] = useState<RecentPage[]>(loadRecent);

    // Track page visits
    useEffect(() => {
        if (!pathname) return;

        setRecentPages(prev => {
            const filtered = prev.filter(p => p.href !== pathname);
            const updated: RecentPage[] = [
                { href: pathname, label: pathToLabel(pathname), visitedAt: Date.now() },
                ...filtered,
            ].slice(0, MAX_RECENT);
            saveRecent(updated);
            return updated;
        });
    }, [pathname]);

    const clearRecent = useCallback(() => {
        setRecentPages([]);
        saveRecent([]);
    }, []);

    return { recentPages, clearRecent };
}
