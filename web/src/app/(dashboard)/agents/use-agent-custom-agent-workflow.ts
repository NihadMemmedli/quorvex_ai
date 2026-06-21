import { useCallback, useEffect, useMemo, useRef, useState, type Dispatch, type MutableRefObject, type SetStateAction } from 'react';
import { toast } from 'sonner';
import type { BrowserAuthSession } from '@/lib/browser-auth-sessions';
import {
    fetchProjectBrowserAuthSessions,
    isBrowserAuthSessionSelectable,
} from '@/lib/browser-auth-sessions';
import { validateAgentRunInput, type AgentWorkspaceView, type ReportReviewFilter } from './agents-workspace-state';
import {
    controlAgentRun as controlAgentRunApi,
    fetchAgentRuntimeSetting,
    retryAgentRun as retryAgentRunApi,
    startAgentDefinitionRun,
} from './agents-api';
import {
    defaultDefinitionForm,
    isAgentRunTerminal,
    markAgentsAction,
    queueStateLabel,
    type AgentActionIntent,
    type AgentDefinition,
    type AgentQueueStatus,
    type AgentRun,
    type AgentTool,
    type AuthType,
    type CustomResultTab,
    type TraceTab,
} from './agents-model';
import { useAgentDefinitions } from './use-agent-definitions';
import { useAgentWorkspaceQuery } from './use-agent-workspace-query';

export function useAgentCustomAgentWorkflow(options: {
    projectId?: string | null;
    projectLoading: boolean;
    workspaceView: AgentWorkspaceView;
    setWorkspaceView: Dispatch<SetStateAction<AgentWorkspaceView>>;
    activeRun: AgentRun | null;
    setActiveRun: Dispatch<SetStateAction<AgentRun | null>>;
    setSelectedRunId: Dispatch<SetStateAction<string | null>>;
    setCustomResultTab: Dispatch<SetStateAction<CustomResultTab>>;
    setTraceTab: Dispatch<SetStateAction<TraceTab>>;
    setReportStatusFilter: Dispatch<SetStateAction<ReportReviewFilter>>;
    setReportSeverityFilter: Dispatch<SetStateAction<string>>;
    setAgentActionIntent: Dispatch<SetStateAction<AgentActionIntent>>;
    setWorkspaceStatus: Dispatch<SetStateAction<string>>;
    fetchHistoryRef: MutableRefObject<() => Promise<unknown>>;
    queueStatus?: AgentQueueStatus | null;
}) {
    const {
        projectId,
        projectLoading,
        workspaceView,
        setWorkspaceView,
        activeRun,
        setActiveRun,
        setSelectedRunId,
        setCustomResultTab,
        setTraceTab,
        setReportStatusFilter,
        setReportSeverityFilter,
        setAgentActionIntent,
        setWorkspaceStatus,
        fetchHistoryRef,
        queueStatus,
    } = options;

    const [url, setUrl] = useState('');
    const [instructions, setInstructions] = useState('');
    const [authType, setAuthType] = useState<AuthType>('none');
    const [sessionId, setSessionId] = useState('');
    const [testDataRefs, setTestDataRefs] = useState('');
    const [isStarting, setIsStarting] = useState(false);
    const [runControlPending, setRunControlPending] = useState<'pause' | 'resume' | 'cancel' | 'retry' | null>(null);
    const [sessions, setSessions] = useState<BrowserAuthSession[]>([]);
    const [agentDefinitions, setAgentDefinitions] = useState<AgentDefinition[]>([]);
    const [toolCatalog, setToolCatalog] = useState<AgentTool[]>([]);
    const [selectedDefinitionId, setSelectedDefinitionId] = useState<string>('');
    const [runFormError, setRunFormError] = useState<string | null>(null);
    const [definitionFormError, setDefinitionFormError] = useState<string | null>(null);
    const [openDefinitionMenuId, setOpenDefinitionMenuId] = useState<string | null>(null);
    const [archiveCandidate, setArchiveCandidate] = useState<AgentDefinition | null>(null);
    const [cancelRunDialogOpen, setCancelRunDialogOpen] = useState(false);
    const [returnToAfterSave, setReturnToAfterSave] = useState('');
    const [agentRuntime, setAgentRuntime] = useState('claude_sdk');
    const [builderOpen, setBuilderOpen] = useState(false);
    const [savingDefinition, setSavingDefinition] = useState(false);
    const [definitionRuntimeOpen, setDefinitionRuntimeOpen] = useState(false);
    const [runSetupReady, setRunSetupReady] = useState(false);
    const [definitionForm, setDefinitionForm] = useState(() => defaultDefinitionForm('claude_sdk'));
    const targetUrlRef = useRef('');

    const activeBrowserAuthSessions = useMemo(
        () => sessions.filter(isBrowserAuthSessionSelectable),
        [sessions]
    );
    const projectDefaultBrowserAuthSession = useMemo(
        () => activeBrowserAuthSessions.find(item => item.is_default),
        [activeBrowserAuthSessions]
    );

    const {
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
    } = useAgentWorkspaceQuery({
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
    });

    const {
        resetAgentLibraryLoadedProjects,
        loadAgentDefinitionsFresh: fetchAgentDefinitionsFresh,
        ensureAgentLibraryData,
        saveDefinitionRecord,
        archiveDefinitionRecord,
    } = useAgentDefinitions({
        projectId,
        projectLoading,
        agentDefinitionsLength: agentDefinitions.length,
        toolCatalogLength: toolCatalog.length,
        selectedDefinitionId,
        setAgentDefinitions,
        setToolCatalog,
        setSelectedDefinitionId,
    });

    const fetchRuntimeSettings = useCallback(async () => {
        try {
            const runtime = await fetchAgentRuntimeSetting();
            if (!runtime) return;
            setAgentRuntime(runtime);
            setDefinitionForm(prev => prev.id ? prev : { ...prev, runtime });
        } catch (e) {
            console.error('Failed to fetch runtime settings', e);
        }
    }, []);

    const fetchSessions = useCallback(async () => {
        if (!projectId) {
            setSessions([]);
            setSessionId('');
            return;
        }
        try {
            setSessions(await fetchProjectBrowserAuthSessions(projectId));
        } catch (e) {
            console.error('Failed to fetch browser login sessions', e);
        }
    }, [projectId]);

    useEffect(() => {
        if (projectLoading) return;
        resetAgentLibraryLoadedProjects();
        setToolCatalog([]);
        setAgentDefinitions([]);
        setSelectedDefinitionId('');
        setSessions([]);
        setSessionId('');
    }, [projectId, projectLoading, resetAgentLibraryLoadedProjects]);

    useEffect(() => {
        if (projectLoading) return;
        void fetchRuntimeSettings();
    }, [fetchRuntimeSettings, projectId, projectLoading]);

    useEffect(() => {
        if (projectLoading) return;
        if (!['run', 'library'].includes(workspaceView) && !builderOpen) return;
        void ensureAgentLibraryData();
    }, [builderOpen, ensureAgentLibraryData, projectLoading, workspaceView]);

    useEffect(() => {
        if (projectLoading) return;
        if (workspaceView !== 'run' && !builderOpen) return;
        void fetchSessions();
    }, [builderOpen, fetchSessions, projectLoading, workspaceView]);

    useEffect(() => {
        setRunSetupReady(true);
    }, []);

    useEffect(() => {
        const rememberTargetUrl = (event: Event) => {
            const target = event.target as HTMLInputElement | null;
            if (target?.name === 'targetUrl' || target?.id === 'agents-target-url') {
                targetUrlRef.current = target.value;
            }
        };
        document.addEventListener('input', rememberTargetUrl, true);
        document.addEventListener('change', rememberTargetUrl, true);
        return () => {
            document.removeEventListener('input', rememberTargetUrl, true);
            document.removeEventListener('change', rememberTargetUrl, true);
        };
    }, []);

    const definitionById = useMemo(() => new Map(agentDefinitions.map(definition => [definition.id, definition])), [agentDefinitions]);
    const selectedDefinition = useMemo(() => definitionById.get(selectedDefinitionId), [definitionById, selectedDefinitionId]);
    const toolsByCategory = useMemo(() => toolCatalog.reduce<Record<string, AgentTool[]>>((acc, tool) => {
        acc[tool.category] = acc[tool.category] || [];
        acc[tool.category].push(tool);
        return acc;
    }, {}), [toolCatalog]);
    const toolById = useMemo(() => new Map(toolCatalog.map(tool => [tool.id, tool])), [toolCatalog]);
    const selectedDefinitionHasBrowserTools = useMemo(() => {
        if (!selectedDefinition) return false;
        return (selectedDefinition.tool_ids || []).some(toolId => {
            const tool = toolById.get(toolId);
            return toolId.startsWith('browser_')
                || tool?.category === 'Browser'
                || (tool?.tool_name || '').includes('__browser_')
                || (tool?.tool_name || '').startsWith('browser_');
        });
    }, [selectedDefinition, toolById]);

    const resetDefinitionForm = useCallback(() => {
        setDefinitionForm(defaultDefinitionForm(agentRuntime));
        setDefinitionFormError(null);
        setDefinitionRuntimeOpen(false);
    }, [agentRuntime]);

    const openCreateAgentBuilder = useCallback(() => {
        resetDefinitionForm();
        selectAgentMode('custom');
        setAgentActionIntent({ type: 'createAgent' });
        setCreateQueryOpen(true);
        setBuilderOpen(true);
        setWorkspaceStatus('Opening custom agent builder.');
        updateWorkspaceQuery({ agent: 'custom', create: true });
        markAgentsAction({ action: 'createAgent', phase: 'modal-open' });
    }, [resetDefinitionForm, selectAgentMode, setAgentActionIntent, setCreateQueryOpen, setWorkspaceStatus, updateWorkspaceQuery]);

    const editDefinition = useCallback((definition: AgentDefinition) => {
        setDefinitionForm({
            id: definition.id,
            name: definition.name,
            description: definition.description || '',
            system_prompt: definition.system_prompt,
            runtime: definition.runtime || 'claude_sdk',
            timeout_seconds: definition.timeout_seconds || 1800,
            tool_ids: definition.tool_ids || [],
            test_data_refs: (definition.test_data_refs || []).join(', '),
        });
        setDefinitionFormError(null);
        setBuilderOpen(true);
    }, []);

    const closeCustomAgentBuilder = useCallback(() => {
        setBuilderOpen(false);
        setDefinitionRuntimeOpen(false);
        setDefinitionFormError(null);
        setAgentActionIntent(prev => prev.type === 'createAgent' ? { type: 'none' } : prev);
        setCreateQueryOpen(false);
        updateWorkspaceQuery({ create: false });
        markAgentsAction({ action: 'createAgent', phase: 'closed' });
    }, [setAgentActionIntent, setCreateQueryOpen, updateWorkspaceQuery]);

    const editDefinitionFromMenu = useCallback((definition: AgentDefinition, event?: Event) => {
        event?.preventDefault();
        event?.stopPropagation();
        setOpenDefinitionMenuId(null);
        editDefinition(definition);
    }, [editDefinition]);

    const archiveDefinitionFromMenu = useCallback((definition: AgentDefinition, event?: Event) => {
        event?.preventDefault();
        event?.stopPropagation();
        setOpenDefinitionMenuId(null);
        setArchiveCandidate(definition);
    }, []);

    const toggleDefinitionTool = useCallback((toolId: string) => {
        setDefinitionForm(prev => ({
            ...prev,
            tool_ids: prev.tool_ids.includes(toolId)
                ? prev.tool_ids.filter(id => id !== toolId)
                : [...prev.tool_ids, toolId],
        }));
    }, []);

    const toggleCategoryTools = useCallback((tools: AgentTool[]) => {
        const ids = tools.map(tool => tool.id);
        const allSelected = ids.every(id => definitionForm.tool_ids.includes(id));
        setDefinitionForm(prev => ({
            ...prev,
            tool_ids: allSelected
                ? prev.tool_ids.filter(id => !ids.includes(id))
                : Array.from(new Set([...prev.tool_ids, ...ids])),
        }));
    }, [definitionForm.tool_ids]);

    const saveDefinition = useCallback(async () => {
        setDefinitionFormError(null);
        if (!definitionForm.name.trim()) {
            setDefinitionFormError('Agent name is required.');
            return;
        }
        if (!definitionForm.system_prompt.trim()) {
            setDefinitionFormError('System prompt is required.');
            return;
        }
        if (definitionForm.tool_ids.length === 0) {
            setDefinitionFormError('Select at least one tool.');
            return;
        }

        setSavingDefinition(true);
        try {
            const isEdit = Boolean(definitionForm.id);
            const saved = await saveDefinitionRecord(definitionForm.id || null, {
                name: definitionForm.name,
                description: definitionForm.description,
                system_prompt: definitionForm.system_prompt,
                runtime: definitionForm.runtime,
                timeout_seconds: definitionForm.timeout_seconds,
                tool_ids: definitionForm.tool_ids,
                test_data_refs: definitionForm.test_data_refs.split(',').map(s => s.trim()).filter(Boolean),
                project_id: projectId || undefined,
            });
            await fetchAgentDefinitionsFresh();
            selectDefinition(saved.id);
            selectAgentMode('custom');
            const nextView = isEdit && workspaceView === 'library' ? 'library' : 'run';
            setWorkspaceView(nextView);
            updateWorkspaceQuery({ create: false, view: nextView });
            setBuilderOpen(false);
            setWorkspaceStatus(`Saved ${saved.name || 'custom agent'}.`);
            toast.success('Custom agent saved');
        } catch (e: any) {
            const message = e.message || 'Failed to save agent';
            setDefinitionFormError(message);
            toast.error(message);
        } finally {
            setSavingDefinition(false);
        }
    }, [definitionForm, fetchAgentDefinitionsFresh, projectId, saveDefinitionRecord, selectAgentMode, selectDefinition, setWorkspaceStatus, setWorkspaceView, updateWorkspaceQuery, workspaceView]);

    const archiveDefinition = useCallback(async (definition: AgentDefinition) => {
        try {
            await archiveDefinitionRecord(definition.id);
            await fetchAgentDefinitionsFresh();
            if (selectedDefinitionId === definition.id) selectDefinition('');
            setWorkspaceStatus(`Archived ${definition.name}.`);
            toast.success('Custom agent archived');
        } catch (e: any) {
            const message = e.message || 'Failed to archive agent';
            toast.error(message);
        }
    }, [archiveDefinitionRecord, fetchAgentDefinitionsFresh, selectDefinition, selectedDefinitionId, setWorkspaceStatus]);

    const handleRun = useCallback(async (submittedTargetUrl?: string) => {
        const targetUrl = (submittedTargetUrl || '').trim() || url.trim() || targetUrlRef.current.trim() || (typeof document !== 'undefined'
            ? ((document.getElementById('agents-target-url') as HTMLInputElement | null)?.value || '').trim()
            : '');
        const validationError = validateAgentRunInput({
            selectedAgent: 'custom',
            selectedDefinitionId,
            url: targetUrl,
            authType,
            sessionId,
            testData: '',
            customAgentHasBrowserTools: selectedDefinitionHasBrowserTools,
        });
        setRunFormError(validationError);
        if (validationError) {
            return;
        }

        setIsStarting(true);
        setWorkspaceStatus('Starting agent run...');
        try {
            const selectedBrowserAuthSessionId = authType === 'session' ? sessionId.trim() : '';
            const selectedBrowserAuthSession = selectedBrowserAuthSessionId
                ? sessions.find(session => session.id === selectedBrowserAuthSessionId)
                : undefined;
            if (selectedBrowserAuthSessionId && (!selectedBrowserAuthSession || !isBrowserAuthSessionSelectable(selectedBrowserAuthSession))) {
                setRunFormError('Select an active browser login session.');
                setIsStarting(false);
                return;
            }

            const testDataRefsList = testDataRefs ? testDataRefs.split(',').map(s => s.trim()).filter(Boolean) : [];

            const selectedRuntime = selectedDefinition?.runtime || agentRuntime;
            const body = {
                prompt: instructions || `Inspect ${targetUrl || 'the current application context'} and report useful QA findings.`,
                url: targetUrl || undefined,
                runtime: selectedRuntime,
                test_data_refs: testDataRefsList,
                config: {
                    browser_auth_session_id: selectedBrowserAuthSessionId || undefined,
                    test_data_refs: testDataRefsList.length > 0 ? testDataRefsList : undefined,
                },
                project_id: projectId || undefined,
            };

            const data = await startAgentDefinitionRun(selectedDefinitionId, body);
            await fetchHistoryRef.current();
            selectRun(data.run_id);
            setWorkspaceStatus('Agent run started.');
            toast.success('Agent run started');
        } catch (e: any) {
            const message = e.message || 'Failed to start agent run.';
            setRunFormError(message);
            toast.error(message);
        } finally {
            setIsStarting(false);
        }
    }, [agentRuntime, authType, fetchHistoryRef, instructions, projectId, selectRun, selectedDefinition?.runtime, selectedDefinitionHasBrowserTools, selectedDefinitionId, sessionId, sessions, setWorkspaceStatus, testDataRefs, url]);

    const controlAgentRun = useCallback(async (action: 'pause' | 'resume' | 'cancel') => {
        if (!activeRun) return;
        setRunControlPending(action);
        try {
            const data = await controlAgentRunApi(activeRun.id, action, projectId);
            setActiveRun(data);
            await fetchHistoryRef.current();
            setWorkspaceStatus(`Run ${action} request sent.`);
            toast.success(`Run ${action} request sent`);
        } catch (e: any) {
            toast.error(e.message || `Failed to ${action} agent run`);
        } finally {
            setRunControlPending(null);
        }
    }, [activeRun, fetchHistoryRef, projectId, setActiveRun, setWorkspaceStatus]);

    const retryAgentRun = useCallback(async () => {
        if (!activeRun || !isAgentRunTerminal(activeRun.status)) return;
        setRunControlPending('retry');
        try {
            const data = await retryAgentRunApi(activeRun.id, projectId);
            setActiveRun(data);
            await fetchHistoryRef.current();
            selectRun(activeRun.id);
            setWorkspaceStatus('Retrying in same run using saved browser auth/session artifacts.');
            toast.success('Retrying in same run');
        } catch (e: any) {
            toast.error(e.message || 'Failed to retry agent run');
        } finally {
            setRunControlPending(null);
        }
    }, [activeRun, fetchHistoryRef, projectId, selectRun, setActiveRun, setWorkspaceStatus]);

    const selectedDefinitionToolLabels = useMemo(() => {
        if (!selectedDefinition) return [];
        return selectedDefinition.tool_ids.map(toolId => toolById.get(toolId)?.label || toolId);
    }, [selectedDefinition, toolById]);
    const visibleTestDataRefs = useMemo(() => {
        const explicitRefs = testDataRefs.split(',').map(ref => ref.trim()).filter(Boolean);
        if (explicitRefs.length > 0) return explicitRefs;
        return selectedDefinition?.test_data_refs || [];
    }, [selectedDefinition?.test_data_refs, testDataRefs]);
    const testDataRefsSummary = visibleTestDataRefs.length === 0
        ? 'No refs selected'
        : `${visibleTestDataRefs.length} ref${visibleTestDataRefs.length === 1 ? '' : 's'} selected`;
    const runPlanRows = useMemo(() => {
        const authMode = authType === 'session'
            ? (sessions.find(session => session.id === sessionId)?.name || sessionId || 'Session required')
            : 'No auth';
        const runtime = selectedDefinition?.runtime || agentRuntime;
        const timeout = `${Math.ceil((selectedDefinition?.timeout_seconds || 1800) / 60)} minutes`;
        return [
            ['Agent', selectedDefinition?.name || 'Custom agent required'],
            ['Runtime', 'Claude SDK'],
            ['Target', url.trim() || 'Optional'],
            ['Auth', authMode],
            ['Timeout', timeout],
            ['Tools', selectedDefinitionToolLabels.slice(0, 4).join(', ') || 'Select a saved agent'],
            ['Test data refs', testDataRefs.trim() || selectedDefinition?.test_data_refs?.join(', ') || 'None'],
            ['Queue', queueStatus ? `${queueStatus.active ?? 0} active, ${queueStatus.queued ?? 0} queued · ${queueStateLabel(queueStatus)}` : 'Not loaded'],
        ];
    }, [agentRuntime, authType, queueStatus, selectedDefinition, selectedDefinitionToolLabels, sessionId, sessions, testDataRefs, url]);

    return {
        queryState,
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
        url,
        setUrl,
        instructions,
        setInstructions,
        authType,
        setAuthType,
        sessionId,
        setSessionId,
        testDataRefs,
        setTestDataRefs,
        isStarting,
        runControlPending,
        sessions,
        activeBrowserAuthSessions,
        projectDefaultBrowserAuthSession,
        agentDefinitions,
        toolCatalog,
        selectedDefinitionId,
        selectedDefinition,
        runFormError,
        definitionFormError,
        openDefinitionMenuId,
        setOpenDefinitionMenuId,
        archiveCandidate,
        setArchiveCandidate,
        cancelRunDialogOpen,
        setCancelRunDialogOpen,
        returnToAfterSave,
        agentRuntime,
        builderOpen,
        setBuilderOpen,
        savingDefinition,
        definitionRuntimeOpen,
        setDefinitionRuntimeOpen,
        runSetupReady,
        definitionForm,
        setDefinitionForm,
        targetUrlRef,
        toolsByCategory,
        testDataRefsSummary,
        runPlanRows,
        openCreateAgentBuilder,
        closeCustomAgentBuilder,
        editDefinitionFromMenu,
        archiveDefinitionFromMenu,
        toggleDefinitionTool,
        toggleCategoryTools,
        saveDefinition,
        archiveDefinition,
        handleRun,
        controlAgentRun,
        retryAgentRun,
    };
}
