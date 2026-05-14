'use client';

import { useState, useEffect, useRef, useCallback } from 'react';
import { fetchWithAuth } from '@/contexts/AuthContext';
import { API_BASE } from '@/lib/api';
import { useProject } from '@/contexts/ProjectContext';

export interface SearchResult {
    id: string;
    label: string;
    href: string;
    type: 'spec' | 'run' | 'requirement' | 'batch' | 'exploration';
    subtitle?: string;
}

function specHref(name: string): string {
    return `/specs/${name.split('/').map(encodeURIComponent).join('/')}`;
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
            fetchWithAuth(`${API_BASE}/specs/list?search=${encoded}&limit=5${projectParam}`, { signal })
                .then(r => r.ok ? r.json() : { items: [] })
                .then((data: any) =>
                    (Array.isArray(data?.items) ? data.items : []).slice(0, 5).map((s: any) => ({
                        id: `spec-${s.name}`,
                        label: s.name,
                        href: specHref(s.name),
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

            fetchWithAuth(`${API_BASE}/search-entities?q=${encoded}${projectParam}&limit=8`, { signal })
                .then(r => r.ok ? r.json() : { entities: [] })
                .then((data: any) =>
                    (Array.isArray(data?.entities) ? data.entities : [])
                        .filter((entity: any) => entity.type === 'batch' || entity.type === 'exploration')
                        .slice(0, 4)
                        .map((entity: any) => ({
                            id: `${entity.type}-${entity.id}`,
                            label: entity.label || entity.id,
                            href: entity.type === 'batch'
                                ? `/regression/batches/${encodeURIComponent(entity.id)}`
                                : '/exploration',
                            type: entity.type as 'batch' | 'exploration',
                            subtitle: entity.description,
                        }))
                )
                .catch(() => [] as SearchResult[]),
        ];

        const settled = await Promise.allSettled(fetches);
        const all = settled.flatMap(r => r.status === 'fulfilled' ? r.value : []);
        return all;
    }, [currentProject?.id]);

    useEffect(() => {
        if (query.length < 2) {
            abortRef.current?.abort();
            setResults([]);
            setIsSearching(false);
            return;
        }

        setIsSearching(true);

        // Cancel previous request
        if (abortRef.current) {
            abortRef.current.abort();
        }
        const controller = new AbortController();
        abortRef.current = controller;
        const signal = controller.signal;

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
            controller.abort();
        };
    }, [query, search]);

    return { results, isSearching };
}
