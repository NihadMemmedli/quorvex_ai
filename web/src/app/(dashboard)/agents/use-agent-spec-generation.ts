import { useCallback, useEffect, useMemo, useState, type Dispatch, type SetStateAction } from 'react';
import { toast } from 'sonner';
import { API_BASE } from '@/lib/api';
import { useJobPoller } from '@/hooks/useJobPoller';
import type { BrowserAuthSession } from '@/lib/browser-auth-sessions';
import {
    fetchExploratoryFlowDetails,
    fetchFlowSpecAgentRun as fetchFlowSpecAgentRunApi,
    generateExploratoryFlowSpec,
    generateReportItemSpec,
    splitSpecFile,
} from './agents-api';
import {
    defaultReportSpecBrowserAuthSelection,
    findReportSpecItem,
    markAgentsAction,
    reportSpecBrowserAuthBody,
    runBrowserAuthSessionId,
    sortArtifactsByModifiedAt,
    type AgentActionIntent,
    type AgentArtifact,
    type AgentRun,
    type AgentRunEvent,
    type FlowModalData,
    type ReportFinding,
    type ReportSpecBrowserAuthMode,
    type ReportTestIdea,
} from './agents-model';
import type { ReportSpecItemType } from './agents-workspace-state';

type WorkspaceQueryPatch = {
    runId?: string | null;
    specItemId?: string;
    specItemType?: ReportSpecItemType | '';
};

interface GeneratedSpec {
    spec_content: string;
    spec_file?: string;
    filename: string;
    flow_title?: string;
    summary?: string;
    cached?: boolean;
    validated?: boolean;
    test_code?: string;
    test_file?: string;
    pipeline?: string;
    requires_auth?: boolean;
}

interface SplitResult {
    count: number;
    files: string[];
    output_dir: string;
}

export function useAgentSpecGeneration(options: {
    activeRun: AgentRun | null;
    projectId?: string | null;
    sessions: BrowserAuthSession[];
    sessionId: string;
    activeBrowserAuthSessions: BrowserAuthSession[];
    projectDefaultBrowserAuthSession?: BrowserAuthSession;
    agentActionIntent: AgentActionIntent;
    setAgentActionIntent: Dispatch<SetStateAction<AgentActionIntent>>;
    setWorkspaceStatus: Dispatch<SetStateAction<string>>;
    updateWorkspaceQuery: (patch: WorkspaceQueryPatch) => void;
}) {
    const {
        activeRun,
        projectId,
        sessions,
        sessionId,
        activeBrowserAuthSessions,
        projectDefaultBrowserAuthSession,
        agentActionIntent,
        setAgentActionIntent,
        setWorkspaceStatus,
        updateWorkspaceQuery,
    } = options;

    const [flowModalOpen, setFlowModalOpen] = useState(false);
    const [selectedFlow, setSelectedFlow] = useState<FlowModalData | null>(null);
    const [loadingFlowDetails, setLoadingFlowDetails] = useState(false);
    const [generatingSpec, setGeneratingSpec] = useState(false);
    const [flowSpecAgentRunId, setFlowSpecAgentRunId] = useState<string | null>(null);
    const [flowSpecAgentRun, setFlowSpecAgentRun] = useState<AgentRun | null>(null);
    const [flowSpecAgentEvents, setFlowSpecAgentEvents] = useState<AgentRunEvent[]>([]);
    const [flowSpecError, setFlowSpecError] = useState<string | null>(null);
    const [reportSpecAuthMode, setReportSpecAuthMode] = useState<ReportSpecBrowserAuthMode>('none');
    const [reportSpecAuthSessionId, setReportSpecAuthSessionId] = useState('');
    const [generatedSpec, setGeneratedSpec] = useState<GeneratedSpec | null>(null);
    const [specModalOpen, setSpecModalOpen] = useState(false);
    const [splittingSpec, setSplittingSpec] = useState(false);
    const [splitResult, setSplitResult] = useState<SplitResult | null>(null);

    const fetchFlowSpecAgentRun = useCallback(async (id: string) => {
        try {
            const data = await fetchFlowSpecAgentRunApi(id);
            setFlowSpecAgentRun(data.run);
            setFlowSpecAgentEvents(data.events);
        } catch (e) {
            console.error('Failed to fetch spec generation run', e);
        }
    }, []);

    const resetFlowSpecRunState = useCallback(() => {
        setFlowSpecAgentRunId(null);
        setFlowSpecAgentRun(null);
        setFlowSpecAgentEvents([]);
        setFlowSpecError(null);
    }, []);

    const setGeneratedSpecFromResponse = useCallback((data: Record<string, any>, summary: string) => {
        setGeneratedSpec({
            spec_content: String(data.spec_content || ''),
            spec_file: data.spec_file,
            filename: data.spec_file ? String(data.spec_file).split('/').pop() || 'spec.md' : 'spec.md',
            flow_title: data.flow_title,
            summary,
            cached: data.cached || false,
            validated: data.validated || false,
            test_code: data.test_code,
            test_file: data.test_file,
            pipeline: data.pipeline,
            requires_auth: data.requires_auth,
        });
    }, []);

    const flowSpecPoller = useJobPoller({
        apiBase: API_BASE,
        urlPattern: '/api/agents/exploratory/flow-spec-jobs/{jobId}',
        interval: 3000,
        onComplete: (result, status) => {
            setFlowSpecError(null);
            if (result) {
                setGeneratedSpecFromResponse(result, 'Generated with Intelligent Pipeline');
                setSpecModalOpen(true);
                setWorkspaceStatus('Test spec generated.');
            }
            const agentRunId = status.agent_run_id || flowSpecAgentRunId;
            if (agentRunId) {
                setFlowSpecAgentRunId(agentRunId);
                void fetchFlowSpecAgentRun(agentRunId);
            }
            setGeneratingSpec(false);
        },
        onFailed: (message, status) => {
            setGeneratingSpec(false);
            setFlowSpecError(message || 'Unknown error');
            setWorkspaceStatus(`Spec generation failed: ${message || 'Unknown error'}`);
            const agentRunId = status.agent_run_id || flowSpecAgentRunId;
            if (agentRunId) {
                setFlowSpecAgentRunId(agentRunId);
                void fetchFlowSpecAgentRun(agentRunId);
            }
        },
    });

    useEffect(() => {
        if (!flowSpecAgentRunId || !flowModalOpen) return;
        void fetchFlowSpecAgentRun(flowSpecAgentRunId);
        const interval = window.setInterval(() => void fetchFlowSpecAgentRun(flowSpecAgentRunId), 3000);
        return () => window.clearInterval(interval);
    }, [fetchFlowSpecAgentRun, flowModalOpen, flowSpecAgentRunId]);

    useEffect(() => {
        const agentRunId = flowSpecPoller.status?.agent_run_id;
        if (agentRunId && agentRunId !== flowSpecAgentRunId) {
            setFlowSpecAgentRunId(agentRunId);
        }
        const agentRun = flowSpecPoller.status?.agent_run as AgentRun | undefined;
        if (agentRun?.id) {
            setFlowSpecAgentRun(agentRun);
        }
    }, [flowSpecPoller.status, flowSpecAgentRunId]);

    useEffect(() => {
        if (agentActionIntent.type === 'reviewReportSpec') {
            setFlowModalOpen(true);
        }
    }, [agentActionIntent]);

    const fetchFlowDetails = useCallback(async (flowId: string) => {
        if (!activeRun?.id) return;

        setLoadingFlowDetails(true);
        flowSpecPoller.clear();
        resetFlowSpecRunState();
        try {
            const data = await fetchExploratoryFlowDetails(activeRun.id, flowId);
            setSelectedFlow(data.flow);
            setAgentActionIntent({ type: 'none' });
            updateWorkspaceQuery({ specItemId: '', specItemType: '' });
            setFlowModalOpen(true);
        } catch (e) {
            console.error('Failed to fetch flow details', e);
            const message = e instanceof Error ? e.message : 'Please try again.';
            toast.error(`Failed to load flow details: ${message}`);
        } finally {
            setLoadingFlowDetails(false);
        }
    }, [activeRun?.id, flowSpecPoller, resetFlowSpecRunState, setAgentActionIntent, updateWorkspaceQuery]);

    const generateFlowSpec = useCallback(async (flowId: string, forceRegenerate = false) => {
        if (!activeRun?.id) return;

        setGeneratingSpec(true);
        setSplitResult(null);
        flowSpecPoller.clear();
        resetFlowSpecRunState();
        try {
            const data = await generateExploratoryFlowSpec(activeRun.id, flowId, forceRegenerate);

            if (data.cached || data.status === 'success') {
                setGeneratedSpecFromResponse(
                    data,
                    data.status === 'success' ? 'Generated with Intelligent Pipeline' : data.status
                );
                setSpecModalOpen(true);
                setGeneratingSpec(false);
                return;
            }

            if (data.job_id) {
                if (data.agent_run_id) {
                    setFlowSpecAgentRunId(data.agent_run_id);
                    void fetchFlowSpecAgentRun(data.agent_run_id);
                }
                flowSpecPoller.startPolling(data.job_id);
                return;
            }

            throw new Error('Unexpected response from server');
        } catch (e: unknown) {
            const message = e instanceof Error ? e.message : 'Please try again.';
            setFlowSpecError(message);
            setGeneratingSpec(false);
        }
    }, [activeRun?.id, fetchFlowSpecAgentRun, flowSpecPoller, resetFlowSpecRunState, setGeneratedSpecFromResponse]);

    const openSpecFromReportItem = useCallback((item: ReportFinding | ReportTestIdea, kind: 'finding' | 'test_idea') => {
        markAgentsAction({ action: 'reviewReportSpec', runId: activeRun?.id, itemId: item?.id, itemType: kind, phase: 'click' });
        if (!activeRun?.id) {
            const message = 'Select a completed custom agent run before creating a spec.';
            setWorkspaceStatus(message);
            setFlowSpecError(message);
            setAgentActionIntent({ type: 'none' });
            toast.error(message);
            markAgentsAction({ action: 'reviewReportSpec', runId: null, itemId: item?.id, itemType: kind, phase: 'missing-run' });
            return;
        }
        if (!item?.id) {
            const message = 'This report item is missing an id and cannot be used to create a spec.';
            setWorkspaceStatus(message);
            setFlowSpecError(message);
            setAgentActionIntent({ type: 'none' });
            toast.error(message);
            markAgentsAction({ action: 'reviewReportSpec', runId: activeRun.id, itemId: null, itemType: kind, phase: 'missing-item-id' });
            return;
        }
        const defaultSelection = defaultReportSpecBrowserAuthSelection(sessions, sessionId);
        setReportSpecAuthMode(defaultSelection.mode);
        setReportSpecAuthSessionId(defaultSelection.sessionId);
        setSelectedFlow(null);
        setAgentActionIntent({ type: 'reviewReportSpec', runId: activeRun.id, itemId: item.id, itemType: kind });
        setFlowModalOpen(true);
        setWorkspaceStatus(`Reviewing ${kind === 'finding' ? 'finding' : 'test idea'} ${item.id} for spec generation.`);
        updateWorkspaceQuery({ runId: activeRun.id, specItemId: item.id, specItemType: kind });
        setGeneratingSpec(false);
        setSplitResult(null);
        flowSpecPoller.clear();
        resetFlowSpecRunState();
        markAgentsAction({ action: 'reviewReportSpec', runId: activeRun.id, itemId: item.id, itemType: kind, phase: 'modal-open' });
    }, [
        activeRun?.id,
        flowSpecPoller,
        resetFlowSpecRunState,
        sessionId,
        sessions,
        setAgentActionIntent,
        setWorkspaceStatus,
        updateWorkspaceQuery,
    ]);

    const closeFlowModal = useCallback(() => {
        setFlowModalOpen(false);
        setGeneratingSpec(false);
        setFlowSpecError(null);
        setSelectedFlow(null);
        if (agentActionIntent.type === 'reviewReportSpec') {
            setAgentActionIntent({ type: 'none' });
            updateWorkspaceQuery({ specItemId: '', specItemType: '' });
        }
        flowSpecPoller.clear();
        resetFlowSpecRunState();
        markAgentsAction({ action: 'flowModal', phase: 'closed' });
    }, [agentActionIntent, flowSpecPoller, resetFlowSpecRunState, setAgentActionIntent, updateWorkspaceQuery]);

    const createSpecFromReportItem = useCallback(async (item: ReportFinding | ReportTestIdea, kind: 'finding' | 'test_idea') => {
        markAgentsAction({ action: 'generateReportSpec', runId: activeRun?.id, itemId: item?.id, itemType: kind, phase: 'click' });
        if (!activeRun?.id) {
            const message = 'Select a completed custom agent run before generating a spec.';
            setWorkspaceStatus(message);
            setFlowSpecError(message);
            toast.error(message);
            return;
        }
        if (!item?.id) {
            const message = 'This report item is missing an id and cannot be used to generate a spec.';
            setWorkspaceStatus(message);
            setFlowSpecError(message);
            toast.error(message);
            return;
        }
        if (reportSpecAuthMode === 'session') {
            const selected = activeBrowserAuthSessions.find(session => session.id === reportSpecAuthSessionId);
            if (!selected) {
                setFlowSpecError('Select an active browser login session or choose No auth.');
                return;
            }
        }
        if (reportSpecAuthMode === 'project_default' && !projectDefaultBrowserAuthSession) {
            setFlowSpecError('Set an active project default browser login session or choose No auth.');
            return;
        }
        setGeneratingSpec(true);
        setSplitResult(null);
        flowSpecPoller.clear();
        resetFlowSpecRunState();
        setWorkspaceStatus(`Generating test spec from ${kind === 'finding' ? 'finding' : 'test idea'} ${item.id}.`);
        try {
            const data = await generateReportItemSpec({
                runId: activeRun.id,
                itemId: item.id,
                itemType: kind,
                projectId,
                body: reportSpecBrowserAuthBody(reportSpecAuthMode, reportSpecAuthSessionId),
            });
            if (data.agent_run_id) {
                setFlowSpecAgentRunId(data.agent_run_id);
                void fetchFlowSpecAgentRun(data.agent_run_id);
            }
            if (data.job_id) {
                flowSpecPoller.startPolling(data.job_id);
                markAgentsAction({ action: 'generateReportSpec', runId: activeRun.id, itemId: item.id, itemType: kind, phase: 'polling-started', jobId: data.job_id });
                return;
            }
            throw new Error('Unexpected response from server');
        } catch (e: unknown) {
            const message = e instanceof Error ? e.message : 'Please try again.';
            setFlowSpecError(message);
            setWorkspaceStatus(`Spec generation failed: ${message}`);
            setGeneratingSpec(false);
            markAgentsAction({ action: 'generateReportSpec', runId: activeRun.id, itemId: item.id, itemType: kind, phase: 'failed', message });
        }
    }, [
        activeBrowserAuthSessions,
        activeRun?.id,
        fetchFlowSpecAgentRun,
        flowSpecPoller,
        projectDefaultBrowserAuthSession,
        projectId,
        reportSpecAuthMode,
        reportSpecAuthSessionId,
        resetFlowSpecRunState,
        setWorkspaceStatus,
    ]);

    const downloadSpec = useCallback((content?: string, filename?: string) => {
        const specContent = content || generatedSpec?.spec_content;
        const specFilename = filename || generatedSpec?.filename || 'spec.md';

        if (!specContent) return;

        const blob = new Blob([specContent], { type: 'text/markdown' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = specFilename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    }, [generatedSpec]);

    const splitSpec = useCallback(async () => {
        if (!generatedSpec?.spec_file) return;

        setSplittingSpec(true);
        setSplitResult(null);
        try {
            const data = await splitSpecFile(generatedSpec.spec_file);
            setSplitResult(data);
            setWorkspaceStatus(`Split spec into ${data.count} files.`);
            toast.success('Spec split into individual tests');
        } catch (e) {
            console.error('Failed to split spec', e);
            const message = e instanceof Error ? e.message : 'Please try again.';
            toast.error(`Failed to split spec: ${message}`);
        } finally {
            setSplittingSpec(false);
        }
    }, [generatedSpec?.spec_file, setWorkspaceStatus]);

    const reportSpecReview = useMemo(() => {
        if (agentActionIntent.type !== 'reviewReportSpec') return null;
        if (activeRun?.id !== agentActionIntent.runId) return null;
        return findReportSpecItem(activeRun, agentActionIntent.itemId, agentActionIntent.itemType);
    }, [activeRun, agentActionIntent]);

    const activeFlow = agentActionIntent.type === 'reviewReportSpec'
        ? reportSpecReview?.flow || null
        : selectedFlow;
    const flowModalVisible = flowModalOpen && (Boolean(activeFlow) || agentActionIntent.type === 'reviewReportSpec');
    const missingReportSpecItemMessage = agentActionIntent.type === 'reviewReportSpec' && activeRun?.id === agentActionIntent.runId && activeRun.result && !reportSpecReview
        ? `Report item ${agentActionIntent.itemId} was not found in the refreshed agent report.`
        : '';

    useEffect(() => {
        if (!missingReportSpecItemMessage) return;
        setWorkspaceStatus(missingReportSpecItemMessage);
        setFlowSpecError(missingReportSpecItemMessage);
        markAgentsAction({
            action: 'reviewReportSpec',
            runId: agentActionIntent.type === 'reviewReportSpec' ? agentActionIntent.runId : null,
            itemId: agentActionIntent.type === 'reviewReportSpec' ? agentActionIntent.itemId : null,
            itemType: agentActionIntent.type === 'reviewReportSpec' ? agentActionIntent.itemType : null,
            phase: 'item-not-found',
        });
    }, [agentActionIntent, missingReportSpecItemMessage, setWorkspaceStatus]);

    useEffect(() => {
        if (agentActionIntent.type !== 'reviewReportSpec' || !reportSpecReview?.item) return;
        const kind = agentActionIntent.itemType === 'finding' ? 'finding' : 'test idea';
        setWorkspaceStatus(`Reviewing ${kind} ${reportSpecReview.item.id} for spec generation.`);
    }, [agentActionIntent, reportSpecReview, setWorkspaceStatus]);

    const flowSpecLatestImage = sortArtifactsByModifiedAt((flowSpecAgentRun?.artifacts || []).filter((artifact: AgentArtifact) => artifact.type === 'image'))[0];
    const sourceRunBrowserAuthSessionId = runBrowserAuthSessionId(activeRun?.config);
    const inheritedBrowserAuthUnavailable = Boolean(
        activeFlow?.source_type === 'custom_report' &&
        sourceRunBrowserAuthSessionId &&
        !activeBrowserAuthSessions.some(item => item.id === sourceRunBrowserAuthSessionId)
    );
    const flowSpecBrowserAuthFailure = Boolean(
        flowSpecAgentRun?.progress?.browser_auth_failure ||
        flowSpecAgentRun?.result?.browser_auth_failure
    );

    return {
        flowModalOpen,
        setFlowModalOpen,
        loadingFlowDetails,
        generatingSpec,
        flowSpecAgentRunId,
        flowSpecAgentRun,
        flowSpecAgentEvents,
        flowSpecError,
        setFlowSpecError,
        reportSpecAuthMode,
        setReportSpecAuthMode,
        reportSpecAuthSessionId,
        setReportSpecAuthSessionId,
        generatedSpec,
        specModalOpen,
        setSpecModalOpen,
        splittingSpec,
        splitResult,
        flowSpecPoller,
        fetchFlowDetails,
        generateFlowSpec,
        openSpecFromReportItem,
        closeFlowModal,
        createSpecFromReportItem,
        downloadSpec,
        splitSpec,
        reportSpecReview,
        activeFlow,
        flowModalVisible,
        missingReportSpecItemMessage,
        flowSpecLatestImage,
        inheritedBrowserAuthUnavailable,
        flowSpecBrowserAuthFailure,
    };
}
