import { useCallback, useEffect, useRef, useState } from 'react';
import { searchAgentReports } from './agents-api';
import type {
    AgentWorkspaceQueryState,
    AgentWorkspaceView,
    ReportSearchTypeFilter,
} from './agents-workspace-state';
import type { AgentReportSearchItem } from './agents-model';

type WorkspaceQueryUpdater = (patch: Partial<Record<keyof AgentWorkspaceQueryState, string | boolean | null | undefined>>) => void;

export function useAgentReportSearch(options: {
    projectId?: string | null;
    projectLoading: boolean;
    queryState: Pick<AgentWorkspaceQueryState, 'reportQ' | 'reportSeverity' | 'reportType'>;
    workspaceView: AgentWorkspaceView;
    updateWorkspaceQuery: WorkspaceQueryUpdater;
}) {
    const { projectId, projectLoading, queryState, workspaceView, updateWorkspaceQuery } = options;
    const [reportSearchQuery, setReportSearchQuery] = useState('');
    const [reportSearchType, setReportSearchType] = useState<ReportSearchTypeFilter>('all');
    const [reportSearchSeverity, setReportSearchSeverity] = useState('all');
    const [reportSearchResults, setReportSearchResults] = useState<AgentReportSearchItem[]>([]);
    const [reportSearchLoading, setReportSearchLoading] = useState(false);
    const reportSearchAbortRef = useRef<AbortController | null>(null);

    const fetchReportSearch = useCallback(async () => {
        if (projectLoading) return;
        reportSearchAbortRef.current?.abort();
        const controller = new AbortController();
        reportSearchAbortRef.current = controller;
        setReportSearchLoading(true);
        try {
            const results = await searchAgentReports({
                projectId,
                query: reportSearchQuery,
                type: reportSearchType,
                severity: reportSearchSeverity,
                signal: controller.signal,
            });
            if (controller.signal.aborted) return;
            setReportSearchResults(results);
        } catch (e) {
            if (e instanceof DOMException && e.name === 'AbortError') return;
            console.error('Failed to search agent reports', e);
            setReportSearchResults([]);
        } finally {
            if (!controller.signal.aborted) {
                setReportSearchLoading(false);
            }
        }
    }, [projectId, projectLoading, reportSearchQuery, reportSearchSeverity, reportSearchType]);

    const updateReportSearchQuery = useCallback((value: string) => {
        setReportSearchQuery(value);
        updateWorkspaceQuery({ reportQ: value });
    }, [updateWorkspaceQuery]);

    const updateReportSearchType = useCallback((value: ReportSearchTypeFilter) => {
        setReportSearchType(value);
        updateWorkspaceQuery({ reportType: value });
    }, [updateWorkspaceQuery]);

    const updateReportSearchSeverity = useCallback((value: string) => {
        setReportSearchSeverity(value);
        updateWorkspaceQuery({ reportSeverity: value });
    }, [updateWorkspaceQuery]);

    const applyReportSearchQueryState = useCallback((state: Pick<AgentWorkspaceQueryState, 'reportQ' | 'reportSeverity' | 'reportType'>) => {
        setReportSearchQuery(state.reportQ);
        setReportSearchSeverity(state.reportSeverity);
        setReportSearchType(state.reportType);
    }, []);

    useEffect(() => {
        applyReportSearchQueryState(queryState);
    }, [applyReportSearchQueryState, queryState.reportQ, queryState.reportSeverity, queryState.reportType]);

    useEffect(() => {
        if (projectLoading || workspaceView !== 'reports') return;
        const timer = window.setTimeout(() => {
            void fetchReportSearch();
        }, 200);
        return () => window.clearTimeout(timer);
    }, [fetchReportSearch, projectLoading, workspaceView]);

    useEffect(() => {
        return () => {
            reportSearchAbortRef.current?.abort();
        };
    }, []);

    return {
        reportSearchQuery,
        reportSearchType,
        reportSearchSeverity,
        reportSearchResults,
        reportSearchLoading,
        fetchReportSearch,
        updateReportSearchQuery,
        updateReportSearchType,
        updateReportSearchSeverity,
        applyReportSearchQueryState,
    };
}
