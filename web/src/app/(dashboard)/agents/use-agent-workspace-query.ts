import { useCallback, useEffect, useMemo, useRef, type Dispatch, type SetStateAction } from 'react';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import {
    applyAgentWorkspaceQueryPatch,
    parseAgentWorkspaceQuery,
    type AgentHistoryStatusFilter,
    type AgentHistoryTypeFilter,
    type AgentTraceTab,
    type AgentWorkspaceMode,
    type AgentWorkspaceView,
    type ReportReviewFilter,
    type ReportSearchTypeFilter,
} from './agents-workspace-state';
import {
    defaultDefinitionForm,
    type AgentActionIntent,
    type CustomResultTab,
    type TraceTab,
} from './agents-model';

type WorkspaceQueryPatch = Parameters<typeof applyAgentWorkspaceQueryPatch>[1];

export function useAgentWorkspaceQuery(options: {
    agentRuntime: string;
    setWorkspaceView: Dispatch<SetStateAction<AgentWorkspaceView>>;
    setSelectedRunId: Dispatch<SetStateAction<string | null>>;
    setSelectedDefinitionId: Dispatch<SetStateAction<string>>;
    setCustomResultTab: Dispatch<SetStateAction<CustomResultTab>>;
    setTraceTab: Dispatch<SetStateAction<TraceTab>>;
    setReportStatusFilter: Dispatch<SetStateAction<ReportReviewFilter>>;
    setReportSeverityFilter: Dispatch<SetStateAction<string>>;
    setReturnToAfterSave: Dispatch<SetStateAction<string>>;
    setDefinitionForm: Dispatch<SetStateAction<ReturnType<typeof defaultDefinitionForm>>>;
    setDefinitionFormError: Dispatch<SetStateAction<string | null>>;
    setAgentActionIntent: Dispatch<SetStateAction<AgentActionIntent>>;
    setBuilderOpen: Dispatch<SetStateAction<boolean>>;
    setWorkspaceStatus: Dispatch<SetStateAction<string>>;
}) {
    const {
        agentRuntime,
        setWorkspaceView,
        setSelectedRunId,
        setSelectedDefinitionId,
        setCustomResultTab,
        setTraceTab,
        setReportStatusFilter,
        setReportSeverityFilter,
        setReturnToAfterSave,
        setDefinitionForm,
        setDefinitionFormError,
        setAgentActionIntent,
        setBuilderOpen,
        setWorkspaceStatus,
    } = options;
    const router = useRouter();
    const pathname = usePathname();
    const searchParams = useSearchParams();
    const searchParamsString = searchParams.toString();
    const workspaceQueryRef = useRef(searchParamsString);
    const queryCreateOpenRef = useRef(false);
    const queryState = useMemo(
        () => parseAgentWorkspaceQuery(new URLSearchParams(searchParamsString)),
        [searchParamsString]
    );

    const updateWorkspaceQuery = useCallback((patch: WorkspaceQueryPatch) => {
        const nextParams = applyAgentWorkspaceQueryPatch(new URLSearchParams(workspaceQueryRef.current || searchParamsString), patch);
        const query = nextParams.toString();
        workspaceQueryRef.current = query;
        router.replace(`${pathname}${query ? `?${query}` : ''}`, { scroll: false });
    }, [pathname, router, searchParamsString]);

    const selectRun = useCallback((runId: string | null) => {
        setSelectedRunId(runId);
        updateWorkspaceQuery({ runId });
    }, [setSelectedRunId, updateWorkspaceQuery]);

    const selectHistoryRun = useCallback((runId: string) => {
        setSelectedRunId(runId);
        setWorkspaceView('run');
        updateWorkspaceQuery({ runId, view: 'run' });
    }, [setSelectedRunId, setWorkspaceView, updateWorkspaceQuery]);

    const selectWorkspaceView = useCallback((view: AgentWorkspaceView) => {
        setWorkspaceView(view);
        updateWorkspaceQuery({ view });
    }, [setWorkspaceView, updateWorkspaceQuery]);

    const selectAgentMode = useCallback((mode: AgentWorkspaceMode) => {
        updateWorkspaceQuery({ agent: mode });
    }, [updateWorkspaceQuery]);

    const selectDefinition = useCallback((definitionId: string) => {
        setSelectedDefinitionId(definitionId);
        updateWorkspaceQuery({ definitionId });
    }, [setSelectedDefinitionId, updateWorkspaceQuery]);

    const selectCustomResultTab = useCallback((tab: CustomResultTab) => {
        setCustomResultTab(tab);
        updateWorkspaceQuery({ resultTab: tab });
    }, [setCustomResultTab, updateWorkspaceQuery]);

    const selectTraceTab = useCallback((tab: TraceTab) => {
        setTraceTab(tab);
        updateWorkspaceQuery({ traceTab: tab });
    }, [setTraceTab, updateWorkspaceQuery]);

    const updateReportStatusFilter = useCallback((value: ReportReviewFilter) => {
        setReportStatusFilter(value);
        updateWorkspaceQuery({ reportStatus: value });
    }, [setReportStatusFilter, updateWorkspaceQuery]);

    const updateReportSeverityFilter = useCallback((value: string) => {
        setReportSeverityFilter(value);
        updateWorkspaceQuery({ reportSeverity: value });
    }, [setReportSeverityFilter, updateWorkspaceQuery]);

    const setCreateQueryOpen = useCallback((open: boolean) => {
        queryCreateOpenRef.current = open;
    }, []);

    useEffect(() => {
        workspaceQueryRef.current = searchParamsString;
        setWorkspaceView(queryState.view);
        if (queryState.runId) setSelectedRunId(queryState.runId);
        if (queryState.definitionId) setSelectedDefinitionId(queryState.definitionId);
        setReturnToAfterSave(queryState.returnTo);
        if (queryState.create) {
            if (!queryCreateOpenRef.current) {
                setDefinitionForm(defaultDefinitionForm(agentRuntime));
                setDefinitionFormError(null);
            }
            queryCreateOpenRef.current = true;
            setAgentActionIntent({ type: 'createAgent' });
            setBuilderOpen(true);
        } else {
            queryCreateOpenRef.current = false;
        }
        if (queryState.runId && queryState.specItemId && queryState.specItemType) {
            setAgentActionIntent({
                type: 'reviewReportSpec',
                runId: queryState.runId,
                itemId: queryState.specItemId,
                itemType: queryState.specItemType,
            });
            setWorkspaceStatus(`Opening report item ${queryState.specItemId} for spec review.`);
        }
        setCustomResultTab(queryState.resultTab);
        setTraceTab(queryState.traceTab);
        setReportStatusFilter(queryState.reportStatus);
        setReportSeverityFilter(queryState.reportSeverity);
    }, [
        agentRuntime,
        queryState,
        searchParamsString,
        setAgentActionIntent,
        setBuilderOpen,
        setCustomResultTab,
        setDefinitionForm,
        setDefinitionFormError,
        setReportSeverityFilter,
        setReportStatusFilter,
        setReturnToAfterSave,
        setSelectedDefinitionId,
        setSelectedRunId,
        setTraceTab,
        setWorkspaceStatus,
        setWorkspaceView,
    ]);

    return {
        updateWorkspaceQuery,
        selectRun,
        selectHistoryRun,
        selectWorkspaceView,
        selectAgentMode,
        selectDefinition,
        selectCustomResultTab,
        selectTraceTab,
        updateReportStatusFilter,
        updateReportSeverityFilter,
        setCreateQueryOpen,
        queryState,
    };
}
