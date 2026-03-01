'use client';

import { useState, useEffect, useRef, useCallback } from 'react';
import { fetchWithAuth } from '@/contexts/AuthContext';
import { API_BASE } from '@/lib/api';
import { useProject } from '@/contexts/ProjectContext';

export interface SearchResult {
    id: string;
    label: string;
    href: string;
    type: 'spec' | 'run' | 'requirement';
    subtitle?: string;
}

export function useCommandSearch(query: string) {
    const [results, setResults] = useState<SearchResult[]>([]);
    const [isSearching, setIsSearching] = useState(false);
    const abortRef = useRef<AbortController | null>(null);
    const { currentProject } = useProject();

    const search = useCallback(async (q: string, signal: AbortSignal) => {
        const projectParam = currentProject?.id ? `&project_id=${encodeURIComponent(currentProject.id)}` : '';
        const encoded = encodeURIComponent(q);

        const fetches = [
            fetchWithAuth(`${API_BASE}/specs?search=${encoded}${projectParam}`, { signal })
                .then(r => r.ok ? r.json() : [])
                .then((data: any[]) =>
                    (Array.isArray(data) ? data : []).slice(0, 5).map((s: any) => ({
                        id: `spec-${s.name || s.path}`,
                        label: s.name || s.path,
                        href: `/specs/${encodeURIComponent(s.path || s.name)}`,
                        type: 'spec' as const,
                        subtitle: s.spec_type || 'spec',
                    }))
                )
                .catch(() => [] as SearchResult[]),

            fetchWithAuth(`${API_BASE}/runs?search=${encoded}${projectParam}&limit=5`, { signal })
                .then(r => r.ok ? r.json() : { runs: [] })
                .then((data: any) => {
                    const runs = Array.isArray(data) ? data : (data.runs || []);
                    return runs.slice(0, 5).map((r: any) => ({
                        id: `run-${r.id}`,
                        label: r.test_name || r.id,
                        href: `/runs/${r.id}`,
                        type: 'run' as const,
                        subtitle: r.status,
                    }));
                })
                .catch(() => [] as SearchResult[]),

            currentProject?.id
                ? fetchWithAuth(`${API_BASE}/requirements/${currentProject.id}?search=${encoded}`, { signal })
                    .then(r => r.ok ? r.json() : [])
                    .then((data: any[]) =>
                        (Array.isArray(data) ? data : []).slice(0, 5).map((req: any) => ({
                            id: `req-${req.id}`,
                            label: `${req.req_code}: ${req.title}`,
                            href: `/requirements?highlight=${req.id}`,
                            type: 'requirement' as const,
                            subtitle: req.category,
                        }))
                    )
                    .catch(() => [] as SearchResult[])
                : Promise.resolve([] as SearchResult[]),
        ];

        const settled = await Promise.allSettled(fetches);
        const all = settled.flatMap(r => r.status === 'fulfilled' ? r.value : []);
        return all;
    }, [currentProject?.id]);

    useEffect(() => {
        if (query.length < 2) {
            setResults([]);
            setIsSearching(false);
            return;
        }

        setIsSearching(true);

        // Cancel previous request
        if (abortRef.current) {
            abortRef.current.abort();
        }
        abortRef.current = new AbortController();
        const signal = abortRef.current.signal;

        const timer = setTimeout(async () => {
            try {
                const data = await search(query, signal);
                if (!signal.aborted) {
                    setResults(data);
                    setIsSearching(false);
                }
            } catch {
                if (!signal.aborted) {
                    setResults([]);
                    setIsSearching(false);
                }
            }
        }, 250);

        return () => {
            clearTimeout(timer);
        };
    }, [query, search]);

    return { results, isSearching };
}
