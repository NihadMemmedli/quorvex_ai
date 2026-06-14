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

const RESULT_TYPE_LIMITS: Record<SearchResult['type'], number> = {
    spec: 5,
    run: 5,
    requirement: 5,
    batch: 3,
    exploration: 3,
};

export function specHref(name: string): string {
    return `/specs/${name.split('/').map(encodeURIComponent).join('/')}`;
}

function requirementLabel(req: any): string {
    const code = req.req_code || req.code || req.id;
    const title = req.title || req.summary || 'Untitled requirement';
    return code ? `${code}: ${title}` : title;
}

function normalizeRequirementItems(data: any): any[] {
    if (Array.isArray(data)) return data;
    if (Array.isArray(data?.items)) return data.items;
    if (Array.isArray(data?.requirements)) return data.requirements;
    return [];
}

function dedupeAndCapResults(results: SearchResult[]): SearchResult[] {
    const seen = new Set<string>();
    const counts: Partial<Record<SearchResult['type'], number>> = {};
    const capped: SearchResult[] = [];

    for (const result of results) {
        const key = `${result.type}:${result.id}`;
        const count = counts[result.type] || 0;
        if (seen.has(key) || count >= RESULT_TYPE_LIMITS[result.type]) {
            continue;
        }

        seen.add(key);
        counts[result.type] = count + 1;
        capped.push(result);
    }

    return capped;
}

export function useCommandSearch(query: string) {
    const [results, setResults] = useState<SearchResult[]>([]);
    const [isSearching, setIsSearching] = useState(false);
    const abortRef = useRef<AbortController | null>(null);
    const { currentProject } = useProject();

    const search = useCallback(async (q: string, signal: AbortSignal) => {
        const projectParam = currentProject?.id ? `&project_id=${encodeURIComponent(currentProject.id)}` : '';
        const requirementProjectParam = currentProject?.id ? `project_id=${encodeURIComponent(currentProject.id)}` : 'project_id=default';
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

            fetchWithAuth(`${API_BASE}/requirements?${requirementProjectParam}&search=${encoded}&limit=5`, { signal })
                .then(r => r.ok ? r.json() : { items: [] })
                .then((data: any) =>
                    normalizeRequirementItems(data).slice(0, 5).map((req: any) => ({
                            id: `req-${req.id}`,
                            label: requirementLabel(req),
                            href: `/requirements?highlight=${req.id}`,
                            type: 'requirement' as const,
                            subtitle: req.category || req.status || 'requirement',
                        }))
                )
                .catch(() => [] as SearchResult[]),

            fetchWithAuth(`${API_BASE}/chat/search-entities?q=${encoded}${projectParam}&limit=8`, { signal })
                .then(r => r.ok ? r.json() : { entities: [] })
                .then((data: any) =>
                    (Array.isArray(data?.entities) ? data.entities : [])
                        .filter((entity: any) => entity.type === 'batch' || entity.type === 'exploration')
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
        return dedupeAndCapResults(all);
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
