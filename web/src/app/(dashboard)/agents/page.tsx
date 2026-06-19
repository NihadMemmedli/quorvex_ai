'use client';
import { useState, useEffect, useMemo, useRef, useCallback } from 'react';
import dynamic from 'next/dynamic';
import Link from 'next/link';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import Bot from 'lucide-react/dist/esm/icons/bot';
import FileText from 'lucide-react/dist/esm/icons/file-text';
import Play from 'lucide-react/dist/esm/icons/play';
import Pause from 'lucide-react/dist/esm/icons/pause';
import Terminal from 'lucide-react/dist/esm/icons/terminal';
import ChevronRight from 'lucide-react/dist/esm/icons/chevron-right';
import CheckCircle2 from 'lucide-react/dist/esm/icons/check-circle-2';
import AlertTriangle from 'lucide-react/dist/esm/icons/alert-triangle';
import Loader2 from 'lucide-react/dist/esm/icons/loader-2';
import Clock from 'lucide-react/dist/esm/icons/clock';
import RotateCcw from 'lucide-react/dist/esm/icons/rotate-ccw';
import Globe from 'lucide-react/dist/esm/icons/globe';
import Settings from 'lucide-react/dist/esm/icons/settings';
import Download from 'lucide-react/dist/esm/icons/download';
import List from 'lucide-react/dist/esm/icons/list';
import Sparkles from 'lucide-react/dist/esm/icons/sparkles';
import Zap from 'lucide-react/dist/esm/icons/zap';
import ArrowRight from 'lucide-react/dist/esm/icons/arrow-right';
import Info from 'lucide-react/dist/esm/icons/info';
import X from 'lucide-react/dist/esm/icons/x';
import RefreshCw from 'lucide-react/dist/esm/icons/refresh-cw';
import Scissors from 'lucide-react/dist/esm/icons/scissors';
import ExternalLink from 'lucide-react/dist/esm/icons/external-link';
import Plus from 'lucide-react/dist/esm/icons/plus';
import Save from 'lucide-react/dist/esm/icons/save';
import Trash2 from 'lucide-react/dist/esm/icons/trash-2';
import Wrench from 'lucide-react/dist/esm/icons/wrench';
import MessageSquare from 'lucide-react/dist/esm/icons/message-square';
import Bug from 'lucide-react/dist/esm/icons/bug';
import Lightbulb from 'lucide-react/dist/esm/icons/lightbulb';
import Eye from 'lucide-react/dist/esm/icons/eye';
import VideoIcon from 'lucide-react/dist/esm/icons/video';
import Monitor from 'lucide-react/dist/esm/icons/monitor';
import ImageIcon from 'lucide-react/dist/esm/icons/image';
import Copy from 'lucide-react/dist/esm/icons/copy';
import Search from 'lucide-react/dist/esm/icons/search';
import Database from 'lucide-react/dist/esm/icons/database';
import Cpu from 'lucide-react/dist/esm/icons/cpu';
import PackageOpen from 'lucide-react/dist/esm/icons/package-open';
import MoreHorizontal from 'lucide-react/dist/esm/icons/more-horizontal';
import Archive from 'lucide-react/dist/esm/icons/archive';
import SlidersHorizontal from 'lucide-react/dist/esm/icons/sliders-horizontal';
import ChevronDown from 'lucide-react/dist/esm/icons/chevron-down';
import Pencil from 'lucide-react/dist/esm/icons/pencil';
import { toast } from 'sonner';
import { useProject } from '@/contexts/ProjectContext';
import { API_BASE } from '@/lib/api';
import { useJobPoller } from '@/hooks/useJobPoller';
import { PageLayout } from '@/components/ui/page-layout';
import { PageHeader } from '@/components/ui/page-header';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Label } from '@/components/ui/label';
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from '@/components/ui/select';
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from '@/components/ui/dialog';
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import { ConfirmDialog } from '@/components/ui/confirm-dialog';
import { StatusBadge } from '@/components/shared/StatusBadge';
import type { BrowserAuthSession } from '@/lib/browser-auth-sessions';
import {
    browserAuthSessionLabel,
    fetchProjectBrowserAuthSessions,
    isBrowserAuthSessionSelectable,
} from '@/lib/browser-auth-sessions';
import {
    applyAgentWorkspaceQueryPatch,
    parseAgentWorkspaceQuery,
    validateAgentRunInput,
    type AgentHistoryStatusFilter,
    type AgentHistoryTypeFilter,
    type AgentTraceTab,
    type AgentWorkspaceMode,
    type AgentWorkspaceView,
    type ReportReviewFilter,
    type ReportSpecItemType,
    type ReportSearchTypeFilter,
} from './agents-workspace-state';
import {
    AGENT_HISTORY_STATUS_FILTER_LABELS,
    AGENT_HISTORY_TYPE_FILTER_LABELS,
    LIVE_AGENT_STATUSES,
    REPORT_PRIORITY_OPTIONS,
    REPORT_SELECT_EMPTY_VALUE,
    REPORT_SEVERITY_OPTIONS,
    TOOL_RISK_PILL_STYLES,
    agentRunDisplayName,
    agentRunResultTitle,
    agentStatusTone,
    customAgentCurrentActivity,
    customAgentExecutionStarted,
    customAgentWorkerMessage,
    defaultDefinitionForm,
    defaultReportSpecBrowserAuthSelection,
    findReportSpecItem,
    formatQueueAge,
    formatToolName,
    getArtifactUrl,
    getStructuredReport,
    isAgentRunTerminal,
    itemPrompt,
    linesToText,
    markAgentsAction,
    normalizeReportPatchResponse,
    queueStateLabel,
    reportEditDialogTitle,
    reportItemReviewState,
    reportItemSeverity,
    reportItemToFlow,
    reportSearchResultHref,
    reportSpecBrowserAuthBody,
    reportStatusColor,
    runBrowserAuthSessionId,
    severityColor,
    sortArtifactsByModifiedAt,
    textToLines,
    type AgentActionIntent,
    type AgentArtifact,
    type AgentDefinition,
    type AgentHistoryCounts,
    type AgentQueueStatus,
    type AgentReportSearchItem,
    type AgentRun,
    type AgentRunEvent,
    type AgentTool,
    type AgentTraceBundle,
    type AuthType,
    type CustomResultTab,
    type FlowModalData,
    type ReportEditTarget,
    type ReportEditableItemType,
    type ReportFinding,
    type ReportRequirement,
    type ReportSpecBrowserAuthMode,
    type ReportTestIdea,
    type SpecResult,
    type StructuredAgentReport,
    type TraceTab,
} from './agents-model';
import {
    EMPTY_AGENT_HISTORY_COUNTS,
    agentRunTraceExportUrl,
    cleanStaleAgentQueue,
    controlAgentRun as controlAgentRunApi,
    fetchExploratoryFlowDetails,
    fetchFlowSpecAgentRun as fetchFlowSpecAgentRunApi,
    fetchAgentQueueStatus,
    fetchAgentRunHistory,
    fetchAgentRuntimeSetting,
    generateExploratoryFlowSpec,
    queueCleanupSummary,
    retryAgentRun as retryAgentRunApi,
    searchAgentReports,
    splitSpecFile,
    startAgentDefinitionRun,
    synthesizeExploratorySpecs,
} from './agents-api';
import { useAgentDefinitions } from './use-agent-definitions';
import { useAgentReportActions } from './use-agent-report-actions';
import { useAgentRunDetail } from './use-agent-run-detail';
import { useAgentRunEventsStream } from './use-agent-run-events-stream';

const LiveBrowserView = dynamic<any>(() => import('@/components/LiveBrowserView').then(mod => mod.LiveBrowserView), { ssr: false });
const TestDataPicker = dynamic<any>(() => import('@/components/TestDataPicker').then(mod => mod.TestDataPicker), { ssr: false });

import {
    AgentRunCapturePanel,
    AgentRunObservabilityPanel,
    CustomAgentReportView,
    QueueStatusPanel,
    ReportsSearchWorkspace,
    SpecGenerationRunPanel,
} from './agents-panels';

export default function AgentsPage() {
    const { currentProject, isLoading: projectLoading } = useProject();
    const router = useRouter();
    const pathname = usePathname();
    const searchParams = useSearchParams();
    const searchParamsString = searchParams.toString();
    const [workspaceView, setWorkspaceView] = useState<AgentWorkspaceView>('run');
    // Basic config
    const [url, setUrl] = useState('');
    const [instructions, setInstructions] = useState('');

    // Enhanced exploratory config
    const [timeLimitMinutes] = useState(15);
    const [authType, setAuthType] = useState<AuthType>('none');
    const [sessionId, setSessionId] = useState('');
    const [testDataRefs, setTestDataRefs] = useState('');

    // History & results
    const [history, setHistory] = useState<AgentRun[]>([]);
    const [historyTotal, setHistoryTotal] = useState(0);
    const [historyCounts, setHistoryCounts] = useState<AgentHistoryCounts>({
        status: { all: 0, active: 0, completed: 0, failed: 0, cancelled: 0, paused: 0 },
        type: { all: 0, exploratory: 0, custom: 0, writer: 0, spec_generation: 0 },
    });
    const [historyNextCursor, setHistoryNextCursor] = useState<string | null>(null);
    const [historyLoading, setHistoryLoading] = useState(false);
    const [historyError, setHistoryError] = useState<string | null>(null);
    const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
    const [activeRun, setActiveRun] = useState<AgentRun | null>(null);
    const [agentEvents, setAgentEvents] = useState<AgentRunEvent[]>([]);
    const [agentTrace, setAgentTrace] = useState<AgentTraceBundle | null>(null);
    const [traceLoading, setTraceLoading] = useState(false);
    const [traceSearch, setTraceSearch] = useState('');
    const [traceSpanType, setTraceSpanType] = useState('');
    const [specResult, setSpecResult] = useState<SpecResult | null>(null);
    const [historySearch, setHistorySearch] = useState('');
    const [debouncedHistorySearch, setDebouncedHistorySearch] = useState('');
    const [historyStatusFilter, setHistoryStatusFilter] = useState<AgentHistoryStatusFilter>('all');
    const [historyTypeFilter, setHistoryTypeFilter] = useState<AgentHistoryTypeFilter>('all');

    // UI state
    const [isStarting, setIsStarting] = useState(false);
    const [runControlPending, setRunControlPending] = useState<'pause' | 'resume' | 'cancel' | 'retry' | null>(null);
    const [isSynthesizing, setIsSynthesizing] = useState(false);
    const [sessions, setSessions] = useState<BrowserAuthSession[]>([]);
    const [flowModalOpen, setFlowModalOpen] = useState(false);
    const [selectedFlow, setSelectedFlow] = useState<FlowModalData | null>(null);
    const [agentActionIntent, setAgentActionIntent] = useState<AgentActionIntent>({ type: 'none' });
    const [loadingFlowDetails, setLoadingFlowDetails] = useState(false);
    const [generatingSpec, setGeneratingSpec] = useState(false);
    const [flowSpecAgentRunId, setFlowSpecAgentRunId] = useState<string | null>(null);
    const [flowSpecAgentRun, setFlowSpecAgentRun] = useState<AgentRun | null>(null);
    const [flowSpecAgentEvents, setFlowSpecAgentEvents] = useState<AgentRunEvent[]>([]);
    const [flowSpecError, setFlowSpecError] = useState<string | null>(null);
    const [reportSpecAuthMode, setReportSpecAuthMode] = useState<ReportSpecBrowserAuthMode>('none');
    const [reportSpecAuthSessionId, setReportSpecAuthSessionId] = useState('');
    const [generatedSpec, setGeneratedSpec] = useState<any | null>(null);
    const [specModalOpen, setSpecModalOpen] = useState(false);
    const [splittingSpec, setSplittingSpec] = useState(false);
    const [splitResult, setSplitResult] = useState<{ count: number; files: string[]; output_dir: string } | null>(null);
    const [agentDefinitions, setAgentDefinitions] = useState<AgentDefinition[]>([]);
    const [toolCatalog, setToolCatalog] = useState<AgentTool[]>([]);
    const [selectedDefinitionId, setSelectedDefinitionId] = useState<string>('');
    const [customResultTab, setCustomResultTab] = useState<CustomResultTab>('overview');
    const [traceTab, setTraceTab] = useState<TraceTab>('timeline');
    const [reportStatusFilter, setReportStatusFilter] = useState<ReportReviewFilter>('all');
    const [reportSeverityFilter, setReportSeverityFilter] = useState('all');
    const [reportSearchQuery, setReportSearchQuery] = useState('');
    const [reportSearchType, setReportSearchType] = useState<ReportSearchTypeFilter>('all');
    const [reportSearchSeverity, setReportSearchSeverity] = useState('all');
    const [reportSearchResults, setReportSearchResults] = useState<AgentReportSearchItem[]>([]);
    const [reportSearchLoading, setReportSearchLoading] = useState(false);
    const [queueStatus, setQueueStatus] = useState<AgentQueueStatus | null>(null);
    const [queueLoading, setQueueLoading] = useState(false);
    const [queueCleanupLoading, setQueueCleanupLoading] = useState(false);
    const [queueError, setQueueError] = useState<string | null>(null);
    const [runFormError, setRunFormError] = useState<string | null>(null);
    const [definitionFormError, setDefinitionFormError] = useState<string | null>(null);
    const [workspaceStatus, setWorkspaceStatus] = useState('');
    const [setupOpen, setSetupOpen] = useState(true);
    const [contextDataOpen, setContextDataOpen] = useState(false);
    const [runPlanDetailsOpen, setRunPlanDetailsOpen] = useState(false);
    const [openDefinitionMenuId, setOpenDefinitionMenuId] = useState<string | null>(null);
    const [archiveCandidate, setArchiveCandidate] = useState<AgentDefinition | null>(null);
    const [cancelRunDialogOpen, setCancelRunDialogOpen] = useState(false);
    const [returnToAfterSave, setReturnToAfterSave] = useState('');
    const [importingRequirementIds, setImportingRequirementIds] = useState<string[]>([]);
    const [reportImportError, setReportImportError] = useState<string | null>(null);
    const [reportEditTarget, setReportEditTarget] = useState<ReportEditTarget | null>(null);
    const [reportEditForm, setReportEditForm] = useState<Record<string, string>>({});
    const [reportEditError, setReportEditError] = useState<string | null>(null);
    const [savingReportEdit, setSavingReportEdit] = useState(false);
    const [agentRuntime, setAgentRuntime] = useState('claude_sdk');
    const [builderOpen, setBuilderOpen] = useState(false);
    const [savingDefinition, setSavingDefinition] = useState(false);
    const [definitionRuntimeOpen, setDefinitionRuntimeOpen] = useState(false);
    const [runSetupReady, setRunSetupReady] = useState(false);
    const [definitionForm, setDefinitionForm] = useState(() => defaultDefinitionForm('claude_sdk'));
    const targetUrlRef = useRef('');
    const historyAbortRef = useRef<AbortController | null>(null);
    const reportSearchAbortRef = useRef<AbortController | null>(null);
    const historyRequestIdRef = useRef(0);
    const agentEventsRef = useRef<AgentRunEvent[]>([]);
    const workspaceQueryRef = useRef(searchParamsString);
    const queryCreateOpenRef = useRef(false);
    const activeBrowserAuthSessions = useMemo(
        () => sessions.filter(isBrowserAuthSessionSelectable),
        [sessions]
    );
    const projectDefaultBrowserAuthSession = useMemo(
        () => activeBrowserAuthSessions.find(item => item.is_default),
        [activeBrowserAuthSessions]
    );

    const updateWorkspaceQuery = useCallback((patch: Parameters<typeof applyAgentWorkspaceQueryPatch>[1]) => {
        const nextParams = applyAgentWorkspaceQueryPatch(new URLSearchParams(workspaceQueryRef.current || searchParamsString), patch);
        const query = nextParams.toString();
        workspaceQueryRef.current = query;
        router.replace(`${pathname}${query ? `?${query}` : ''}`, { scroll: false });
    }, [pathname, router, searchParamsString]);

    const selectRun = useCallback((runId: string | null) => {
        setSelectedRunId(runId);
        updateWorkspaceQuery({ runId });
    }, [updateWorkspaceQuery]);

    const selectHistoryRun = useCallback((runId: string) => {
        setSelectedRunId(runId);
        setWorkspaceView('run');
        updateWorkspaceQuery({ runId, view: 'run' });
    }, [updateWorkspaceQuery]);

    const selectWorkspaceView = useCallback((view: AgentWorkspaceView) => {
        setWorkspaceView(view);
        updateWorkspaceQuery({ view });
    }, [updateWorkspaceQuery]);

    const selectAgentMode = useCallback((mode: AgentWorkspaceMode) => {
        updateWorkspaceQuery({ agent: mode });
    }, [updateWorkspaceQuery]);

    const selectDefinition = useCallback((definitionId: string) => {
        setSelectedDefinitionId(definitionId);
        updateWorkspaceQuery({ definitionId });
    }, [updateWorkspaceQuery]);

    const selectCustomResultTab = useCallback((tab: CustomResultTab) => {
        setCustomResultTab(tab);
        updateWorkspaceQuery({ resultTab: tab });
    }, [updateWorkspaceQuery]);

    const selectTraceTab = useCallback((tab: TraceTab) => {
        setTraceTab(tab);
        updateWorkspaceQuery({ traceTab: tab });
    }, [updateWorkspaceQuery]);

    const updateReportStatusFilter = useCallback((value: ReportReviewFilter) => {
        setReportStatusFilter(value);
        updateWorkspaceQuery({ reportStatus: value });
    }, [updateWorkspaceQuery]);

    const updateReportSeverityFilter = useCallback((value: string) => {
        setReportSeverityFilter(value);
        updateWorkspaceQuery({ reportSeverity: value });
    }, [updateWorkspaceQuery]);

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

    const updateHistorySearch = useCallback((value: string) => {
        setHistorySearch(value);
    }, []);

    const updateHistoryStatusFilter = useCallback((value: AgentHistoryStatusFilter) => {
        setHistoryStatusFilter(value);
        updateWorkspaceQuery({ status: value });
    }, [updateWorkspaceQuery]);

    const updateHistoryTypeFilter = useCallback((value: AgentHistoryTypeFilter) => {
        setHistoryTypeFilter(value);
        updateWorkspaceQuery({ type: value });
    }, [updateWorkspaceQuery]);

    const fetchRuntimeSettings = async () => {
        try {
            const runtime = await fetchAgentRuntimeSetting();
            if (!runtime) return;
            setAgentRuntime(runtime);
            setDefinitionForm(prev => prev.id ? prev : { ...prev, runtime });
        } catch (e) {
            console.error('Failed to fetch runtime settings', e);
        }
    };

    // Fetch history summaries (filtered and paged by the API).
    const fetchHistory = useCallback(async (options: { append?: boolean; cursor?: string | null } = {}) => {
        if (projectLoading) return;
        historyAbortRef.current?.abort();
        const controller = new AbortController();
        historyAbortRef.current = controller;
        const requestId = historyRequestIdRef.current + 1;
        historyRequestIdRef.current = requestId;
        setHistoryLoading(true);
        setHistoryError(null);
        try {
            const payload = await fetchAgentRunHistory({
                projectId: currentProject?.id,
                status: historyStatusFilter,
                type: historyTypeFilter,
                query: debouncedHistorySearch,
                cursor: options.cursor,
                signal: controller.signal,
            });
            if (controller.signal.aborted || historyRequestIdRef.current !== requestId) return;
            setHistory(prev => options.append ? [...prev, ...(payload.items || [])] : (payload.items || []));
            setHistoryTotal(Number(payload.total || 0));
            setHistoryCounts(payload.counts || EMPTY_AGENT_HISTORY_COUNTS);
            setHistoryNextCursor(payload.next_cursor || null);
        } catch (e) {
            if (e instanceof DOMException && e.name === 'AbortError') return;
            const message = e instanceof Error ? e.message : 'Failed to fetch history';
            setHistoryError(message);
            console.error("Failed to fetch history", e);
        } finally {
            if (historyRequestIdRef.current === requestId) {
                setHistoryLoading(false);
            }
        }
    }, [currentProject?.id, debouncedHistorySearch, historyStatusFilter, historyTypeFilter, projectLoading]);

    const loadMoreHistory = useCallback(() => {
        if (!historyNextCursor || historyLoading) return;
        void fetchHistory({ append: true, cursor: historyNextCursor });
    }, [fetchHistory, historyLoading, historyNextCursor]);

    const fetchSessions = async () => {
        if (!currentProject?.id) {
            setSessions([]);
            setSessionId('');
            return;
        }
        try {
            setSessions(await fetchProjectBrowserAuthSessions(currentProject.id));
        } catch (e) { console.error("Failed to fetch browser login sessions", e); }
    };

    const {
        resetAgentLibraryLoadedProjects,
        loadAgentDefinitionsFresh: fetchAgentDefinitionsFresh,
        ensureAgentLibraryData,
        saveDefinitionRecord,
        archiveDefinitionRecord,
    } = useAgentDefinitions({
        projectId: currentProject?.id,
        projectLoading,
        agentDefinitionsLength: agentDefinitions.length,
        toolCatalogLength: toolCatalog.length,
        selectedDefinitionId,
        setAgentDefinitions,
        setToolCatalog,
        setSelectedDefinitionId,
    });

    const {
        saveReportPatch,
        importRequirements,
        generateItemSpec,
    } = useAgentReportActions(currentProject?.id);

    const fetchQueueStatus = async () => {
        setQueueLoading(true);
        setQueueError(null);
        try {
            setQueueStatus(await fetchAgentQueueStatus());
        } catch (e: unknown) {
            const message = e instanceof Error ? e.message : 'Failed to fetch queue status.';
            setQueueError(message);
        } finally {
            setQueueLoading(false);
        }
    };

    const cleanStaleQueueTasks = async () => {
        setQueueCleanupLoading(true);
        try {
            const data = await cleanStaleAgentQueue();
            toast.success(queueCleanupSummary(data));
            await fetchQueueStatus();
        } catch (e: unknown) {
            const message = e instanceof Error ? e.message : 'Failed to clean stale queue tasks.';
            toast.error(message);
        } finally {
            setQueueCleanupLoading(false);
        }
    };

    const fetchReportSearch = async () => {
        if (projectLoading) return;
        reportSearchAbortRef.current?.abort();
        const controller = new AbortController();
        reportSearchAbortRef.current = controller;
        setReportSearchLoading(true);
        try {
            const results = await searchAgentReports({
                projectId: currentProject?.id,
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
    };

    useEffect(() => {
        workspaceQueryRef.current = searchParamsString;
        const queryState = parseAgentWorkspaceQuery(new URLSearchParams(searchParamsString));
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
            setFlowModalOpen(true);
            setWorkspaceStatus(`Opening report item ${queryState.specItemId} for spec review.`);
        }
        setCustomResultTab(queryState.resultTab);
        setTraceTab(queryState.traceTab);
        setReportStatusFilter(queryState.reportStatus);
        setReportSeverityFilter(queryState.reportSeverity);
        setReportSearchQuery(queryState.reportQ);
        setReportSearchSeverity(queryState.reportSeverity);
        setReportSearchType(queryState.reportType);
        setHistoryStatusFilter(queryState.status);
        setHistoryTypeFilter(queryState.type);
        setHistorySearch(queryState.q);
        setDebouncedHistorySearch(queryState.q);
    }, [agentRuntime, searchParamsString]);

    useEffect(() => {
        const timer = window.setTimeout(() => {
            setDebouncedHistorySearch(historySearch);
            updateWorkspaceQuery({ q: historySearch });
        }, 300);
        return () => window.clearTimeout(timer);
    }, [historySearch, updateWorkspaceQuery]);

    useEffect(() => {
        if (projectLoading) return;
        resetAgentLibraryLoadedProjects();
        setToolCatalog([]);
        setAgentDefinitions([]);
        setSelectedDefinitionId('');
        setSessions([]);
        setSessionId('');
    }, [currentProject?.id, projectLoading, resetAgentLibraryLoadedProjects]);

    useEffect(() => {
        if (projectLoading) return;
        void fetchRuntimeSettings();
    }, [currentProject?.id, projectLoading]);

    useEffect(() => {
        if (projectLoading) return;
        void fetchHistory();
    }, [fetchHistory, projectLoading]);

    useEffect(() => {
        if (projectLoading) return;
        if (!['run', 'library'].includes(workspaceView) && !builderOpen) return;
        void ensureAgentLibraryData();
    }, [builderOpen, ensureAgentLibraryData, projectLoading, workspaceView]);

    useEffect(() => {
        if (projectLoading) return;
        const needsSessions =
            workspaceView === 'run' ||
            flowModalOpen ||
            builderOpen;
        if (!needsSessions) return;
        void fetchSessions();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [builderOpen, currentProject?.id, flowModalOpen, projectLoading, workspaceView]);

    useEffect(() => {
        setRunSetupReady(true);
    }, []);

    useEffect(() => {
        return () => {
            historyAbortRef.current?.abort();
            reportSearchAbortRef.current?.abort();
        }
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

    useEffect(() => {
        if (typeof window !== 'undefined' && new URLSearchParams(window.location.search).has('resultTab')) return;
        setCustomResultTab('overview');
    }, [activeRun?.id]);

    useEffect(() => {
        if (projectLoading || workspaceView !== 'reports') return;
        const timer = window.setTimeout(() => {
            void fetchReportSearch();
        }, 200);
        return () => window.clearTimeout(timer);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [workspaceView, currentProject?.id, reportSearchQuery, reportSearchType, reportSearchSeverity, projectLoading]);

    useEffect(() => {
        if (projectLoading || workspaceView !== 'queue') return;
        void fetchQueueStatus();
        const interval = window.setInterval(() => void fetchQueueStatus(), 5000);
        return () => window.clearInterval(interval);
    }, [workspaceView, projectLoading]);

    useEffect(() => {
        agentEventsRef.current = agentEvents;
    }, [agentEvents]);

    const openAssistantWithPrompt = (prompt: string) => {
        window.dispatchEvent(new CustomEvent('open-ai-assistant'));
        setTimeout(() => {
            window.dispatchEvent(new CustomEvent('assistant-prefill', { detail: { prompt } }));
        }, 50);
    };

    const mergeProgressFromAgentEvent = useCallback((event: AgentRunEvent) => {
        if (!event || !['tool_call', 'browser_action'].includes(event.event_type)) return;
        const payload = event.payload || {};
        const eventRunId = event.run_id || selectedRunId;
        const toolName = payload.tool_name || payload.current_tool || payload.last_tool;
        const toolLabel = payload.tool_label || payload.current_tool_label || payload.last_tool_label || payload.short_name;
        const events = [...agentEventsRef.current, event];
        const uniqueEvents = [...new Map(events.map(item => [item.sequence, item])).values()];
        const toolEventCount = uniqueEvents.filter(item => ['tool_call', 'browser_action'].includes(item.event_type)).length;
        const browserEventCount = uniqueEvents.filter(item => item.event_type === 'browser_action').length;

        setActiveRun(prev => {
            if (!prev || prev.id !== eventRunId) return prev;
            const currentProgress = prev.progress || {};
            return {
                ...prev,
                progress: {
                    ...currentProgress,
                    phase: currentProgress.phase || 'tool_use',
                    last_tool: toolName || currentProgress.last_tool,
                    current_tool: toolName || currentProgress.current_tool,
                    last_tool_label: toolLabel || currentProgress.last_tool_label,
                    current_tool_label: toolLabel || currentProgress.current_tool_label,
                    tool_calls: Math.max(Number(currentProgress.tool_calls ?? 0), toolEventCount),
                    browser_tool_calls: Math.max(Number(currentProgress.browser_tool_calls ?? currentProgress.interactions ?? 0), browserEventCount),
                    updated_at: event.created_at || currentProgress.updated_at,
                },
            };
        });
    }, [selectedRunId]);

    const {
        fetchRun,
        fetchAgentEvents,
        fetchAgentTrace,
        fetchSpecs,
        mergeAgentEvents,
    } = useAgentRunDetail({
        selectedRunId,
        projectId: currentProject?.id,
        activeRun,
        traceTab,
        fetchHistory,
        setActiveRun,
        setAgentEvents,
        setAgentTrace,
        setTraceLoading,
        setSpecResult,
        setTraceSearch,
        setTraceSpanType,
    });

    useAgentRunEventsStream({
        selectedRunId,
        activeRun,
        projectId: currentProject?.id,
        agentEventsRef,
        fetchRun,
        fetchAgentEvents,
        fetchAgentTrace,
        fetchHistory,
        mergeAgentEvents,
        mergeProgressFromAgentEvent,
    });

    const fetchFlowSpecAgentRun = async (id: string) => {
        try {
            const data = await fetchFlowSpecAgentRunApi(id);
            setFlowSpecAgentRun(data.run);
            setFlowSpecAgentEvents(data.events);
        } catch (e) {
            console.error("Failed to fetch spec generation run", e);
        }
    };

    useEffect(() => {
        if (!flowSpecAgentRunId || !flowModalOpen) return;
        fetchFlowSpecAgentRun(flowSpecAgentRunId);
        const interval = window.setInterval(() => fetchFlowSpecAgentRun(flowSpecAgentRunId), 3000);
        return () => window.clearInterval(interval);
    }, [flowSpecAgentRunId, flowModalOpen]);

    // Fetch flow details from the API
    const fetchFlowDetails = async (flowId: string) => {
        if (!activeRun?.id) return;

        setLoadingFlowDetails(true);
        flowSpecPoller.clear();
        setFlowSpecAgentRunId(null);
        setFlowSpecAgentRun(null);
        setFlowSpecAgentEvents([]);
        setFlowSpecError(null);
        try {
            const data = await fetchExploratoryFlowDetails(activeRun.id, flowId);
            setSelectedFlow(data.flow);
            setAgentActionIntent({ type: 'none' });
            updateWorkspaceQuery({ specItemId: '', specItemType: '' });
            setFlowModalOpen(true);
        } catch (e) {
            console.error("Failed to fetch flow details", e);
            const message = e instanceof Error ? e.message : 'Please try again.';
            toast.error(`Failed to load flow details: ${message}`);
        } finally {
            setLoadingFlowDetails(false);
        }
    };

    // Flow spec generation with async job polling
    const flowSpecPoller = useJobPoller({
        apiBase: API_BASE,
        urlPattern: '/api/agents/exploratory/flow-spec-jobs/{jobId}',
        interval: 3000,
        onComplete: (result, status) => {
            setFlowSpecError(null);
            if (result) {
                setGeneratedSpec({
                    spec_content: result.spec_content as string,
                    spec_file: result.spec_file as string,
                    filename: result.spec_file ? (result.spec_file as string).split('/').pop() : 'spec.md',
                    flow_title: result.flow_title as string,
                    summary: 'Generated with Intelligent Pipeline',
                    cached: false,
                    validated: result.validated as boolean || false,
                    test_code: result.test_code as string,
                    test_file: result.test_file as string,
                    pipeline: result.pipeline as string,
                    requires_auth: result.requires_auth as boolean,
                });
                setSpecModalOpen(true);
                setWorkspaceStatus('Test spec generated.');
            }
            const agentRunId = status.agent_run_id || flowSpecAgentRunId;
            if (agentRunId) {
                setFlowSpecAgentRunId(agentRunId);
                fetchFlowSpecAgentRun(agentRunId);
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
                fetchFlowSpecAgentRun(agentRunId);
            }
        },
    });

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

    // Generate spec for a single flow using Intelligent Pipeline
    const generateFlowSpec = async (flowId: string, forceRegenerate: boolean = false) => {
        if (!activeRun?.id) return;

        setGeneratingSpec(true);
        setSplitResult(null);
        flowSpecPoller.clear();
        setFlowSpecAgentRunId(null);
        setFlowSpecAgentRun(null);
        setFlowSpecAgentEvents([]);
        setFlowSpecError(null);
        try {
            const data = await generateExploratoryFlowSpec(activeRun.id, flowId, forceRegenerate);

            // Cached result → show immediately
            if (data.cached || data.status === 'success') {
                setGeneratedSpec({
                    spec_content: data.spec_content,
                    spec_file: data.spec_file,
                    filename: data.spec_file ? data.spec_file.split('/').pop() : 'spec.md',
                    flow_title: data.flow_title,
                    summary: data.status === 'success' ? 'Generated with Intelligent Pipeline' : data.status,
                    cached: data.cached || false,
                    validated: data.validated || false,
                    test_code: data.test_code,
                    test_file: data.test_file,
                    pipeline: data.pipeline,
                    requires_auth: data.requires_auth
                });
                setSpecModalOpen(true);
                setGeneratingSpec(false);
                return;
            }

            // Async job → start polling
            if (data.job_id) {
                if (data.agent_run_id) {
                    setFlowSpecAgentRunId(data.agent_run_id);
                    fetchFlowSpecAgentRun(data.agent_run_id);
                }
                flowSpecPoller.startPolling(data.job_id);
                return; // generatingSpec stays true until poll resolves
            }

            throw new Error('Unexpected response from server');
        } catch (e: unknown) {
            const message = e instanceof Error ? e.message : 'Please try again.';
            setFlowSpecError(message);
            setGeneratingSpec(false);
        }
    };

    const openSpecFromReportItem = (item: ReportFinding | ReportTestIdea, kind: 'finding' | 'test_idea') => {
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
        setFlowSpecAgentRunId(null);
        setFlowSpecAgentRun(null);
        setFlowSpecAgentEvents([]);
        setFlowSpecError(null);
        markAgentsAction({ action: 'reviewReportSpec', runId: activeRun.id, itemId: item.id, itemType: kind, phase: 'modal-open' });
    };

    const closeFlowModal = () => {
        setFlowModalOpen(false);
        setGeneratingSpec(false);
        setFlowSpecError(null);
        setSelectedFlow(null);
        if (agentActionIntent.type === 'reviewReportSpec') {
            setAgentActionIntent({ type: 'none' });
            updateWorkspaceQuery({ specItemId: '', specItemType: '' });
        }
        flowSpecPoller.clear();
        setFlowSpecAgentRunId(null);
        setFlowSpecAgentRun(null);
        setFlowSpecAgentEvents([]);
        markAgentsAction({ action: 'flowModal', phase: 'closed' });
    };

    const createSpecFromReportItem = async (item: ReportFinding | ReportTestIdea, kind: 'finding' | 'test_idea') => {
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
        setFlowSpecAgentRunId(null);
        setFlowSpecAgentRun(null);
        setFlowSpecAgentEvents([]);
        setFlowSpecError(null);
        setWorkspaceStatus(`Generating test spec from ${kind === 'finding' ? 'finding' : 'test idea'} ${item.id}.`);
        try {
            const data = await generateItemSpec({
                runId: activeRun.id,
                itemId: item.id,
                itemType: kind,
                body: reportSpecBrowserAuthBody(reportSpecAuthMode, reportSpecAuthSessionId),
            });
            if (data.agent_run_id) {
                setFlowSpecAgentRunId(data.agent_run_id);
                fetchFlowSpecAgentRun(data.agent_run_id);
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
    };

    const updateRunFromReportPatch = (updatedRun: AgentRun) => {
        setActiveRun(updatedRun);
        setHistory(prev => prev.map(run => run.id === updatedRun.id ? updatedRun : run));
    };

    const openReportOverviewEdit = (report: StructuredAgentReport) => {
        if (!activeRun?.id) return;
        setReportEditTarget({ type: 'overview', runId: activeRun.id });
        setReportEditForm({
            summary: report.summary || '',
            scope: report.scope || '',
        });
        setReportEditError(null);
    };

    const openReportItemEdit = (item: ReportFinding | ReportTestIdea | ReportRequirement, kind: ReportEditableItemType) => {
        if (!activeRun?.id) return;
        setReportEditTarget({ type: kind, runId: activeRun.id, itemId: item.id });
        if (kind === 'finding') {
            const finding = item as ReportFinding;
            setReportEditForm({
                title: finding.title || '',
                severity: finding.severity || '',
                page: finding.page || '',
                description: finding.description || '',
                evidence: finding.evidence || '',
                suggested_action: finding.suggested_action || '',
            });
        } else if (kind === 'test_idea') {
            const idea = item as ReportTestIdea;
            setReportEditForm({
                title: idea.title || '',
                priority: idea.priority || '',
                page: idea.page || '',
                steps: linesToText(idea.steps),
                expected: idea.expected || '',
                source_finding_id: idea.source_finding_id || '',
            });
        } else {
            const requirement = item as ReportRequirement;
            setReportEditForm({
                title: requirement.title || '',
                description: requirement.description || '',
                category: requirement.category || '',
                priority: requirement.priority || '',
                acceptance_criteria: linesToText(requirement.acceptance_criteria),
                page: requirement.page || '',
                evidence: requirement.evidence || '',
                confidence: requirement.confidence === undefined || requirement.confidence === null ? '' : String(requirement.confidence),
            });
        }
        setReportEditError(null);
    };

    const closeReportEditDialog = () => {
        if (savingReportEdit) return;
        setReportEditTarget(null);
        setReportEditForm({});
        setReportEditError(null);
    };

    const updateReportEditField = (field: string, value: string) => {
        setReportEditForm(prev => ({ ...prev, [field]: value }));
    };

    const reportEditFieldId = (field: string) => `agents-report-edit-${reportEditTarget?.type || 'report'}-${field}`;

    const reportEditKicker = () => {
        if (!reportEditTarget || reportEditTarget.type === 'overview') return 'Report summary';
        if (reportEditTarget.type === 'finding') return `Finding ${reportEditTarget.itemId}`;
        if (reportEditTarget.type === 'test_idea') return `Test idea ${reportEditTarget.itemId}`;
        return `Requirement ${reportEditTarget.itemId}`;
    };

    const reportEditSelectValue = (field: string, options: readonly string[]) => {
        const value = (reportEditForm[field] || '').trim();
        if (!value) return REPORT_SELECT_EMPTY_VALUE;
        const normalized = value.toLowerCase();
        return options.includes(normalized) ? normalized : value;
    };

    const renderReportTextField = (label: string, field: string, type = 'text') => {
        const id = reportEditFieldId(field);
        return (
            <div className="agents-report-edit-field">
                <Label htmlFor={id}>{label}</Label>
                <Input
                    id={id}
                    type={type}
                    className="agents-report-edit-input"
                    value={reportEditForm[field] || ''}
                    onChange={event => updateReportEditField(field, event.target.value)}
                />
            </div>
        );
    };

    const renderReportTextareaField = (label: string, field: string, rows: number, size: 'md' | 'lg' = 'md') => {
        const id = reportEditFieldId(field);
        return (
            <div className="agents-report-edit-field">
                <Label htmlFor={id}>{label}</Label>
                <textarea
                    id={id}
                    className="agents-report-edit-textarea"
                    data-size={size}
                    value={reportEditForm[field] || ''}
                    onChange={event => updateReportEditField(field, event.target.value)}
                    rows={rows}
                />
            </div>
        );
    };

    const renderReportSelectField = (label: string, field: 'priority' | 'severity', options: readonly string[]) => {
        const id = reportEditFieldId(field);
        const rawValue = (reportEditForm[field] || '').trim();
        const normalizedValue = rawValue.toLowerCase();
        const hasKnownValue = options.includes(normalizedValue);
        const selectValue = reportEditSelectValue(field, options);
        return (
            <div className="agents-report-edit-field">
                <Label htmlFor={id}>{label}</Label>
                <Select
                    value={selectValue}
                    onValueChange={value => updateReportEditField(field, value === REPORT_SELECT_EMPTY_VALUE ? '' : value)}
                >
                    <SelectTrigger id={id} className="agents-report-edit-select-trigger">
                        <SelectValue placeholder={`Select ${label.toLowerCase()}`} />
                    </SelectTrigger>
                    <SelectContent className="agents-report-edit-select-content" sideOffset={8}>
                        <SelectItem value={REPORT_SELECT_EMPTY_VALUE}>Not set</SelectItem>
                        {options.map(option => (
                            <SelectItem key={option} value={option}>{option.charAt(0).toUpperCase() + option.slice(1)}</SelectItem>
                        ))}
                        {rawValue && !hasKnownValue && (
                            <SelectItem value={rawValue}>{rawValue}</SelectItem>
                        )}
                    </SelectContent>
                </Select>
            </div>
        );
    };

    const reportEditPayload = () => {
        if (!reportEditTarget) return {};
        if (reportEditTarget.type === 'overview') {
            return {
                summary: reportEditForm.summary || '',
                scope: reportEditForm.scope || '',
            };
        }
        if (reportEditTarget.type === 'finding') {
            return {
                title: reportEditForm.title || '',
                severity: reportEditForm.severity || '',
                page: reportEditForm.page || '',
                description: reportEditForm.description || '',
                evidence: reportEditForm.evidence || '',
                suggested_action: reportEditForm.suggested_action || '',
            };
        }
        if (reportEditTarget.type === 'test_idea') {
            return {
                title: reportEditForm.title || '',
                priority: reportEditForm.priority || '',
                page: reportEditForm.page || '',
                steps: textToLines(reportEditForm.steps),
                expected: reportEditForm.expected || '',
                source_finding_id: reportEditForm.source_finding_id || '',
            };
        }
        return {
            title: reportEditForm.title || '',
            description: reportEditForm.description || '',
            category: reportEditForm.category || '',
            priority: reportEditForm.priority || '',
            acceptance_criteria: textToLines(reportEditForm.acceptance_criteria),
            page: reportEditForm.page || '',
            evidence: reportEditForm.evidence || '',
            confidence: reportEditForm.confidence || '',
        };
    };

    const saveReportEdit = async () => {
        if (!reportEditTarget || !activeRun?.id) return;
        setSavingReportEdit(true);
        setReportEditError(null);
        try {
            const data = await saveReportPatch(reportEditTarget, reportEditPayload());
            const updatedRun = normalizeReportPatchResponse(data);
            if (!updatedRun) throw new Error('The server did not return the updated run.');
            updateRunFromReportPatch(updatedRun);
            setReportEditTarget(null);
            setReportEditForm({});
            setWorkspaceStatus('Report content saved.');
        } catch (e: unknown) {
            const message = e instanceof Error ? e.message : 'Failed to save report content.';
            setReportEditError(message);
            setWorkspaceStatus(`Report edit failed: ${message}`);
        } finally {
            setSavingReportEdit(false);
        }
    };

    const importReportRequirements = async (itemIds?: string[]) => {
        if (!activeRun?.id) return;
        const selectedIds = (itemIds || []).filter(Boolean);
        const markers = selectedIds.length > 0 ? selectedIds : ['__all__'];
        setImportingRequirementIds(prev => Array.from(new Set([...prev, ...markers])));
        setReportImportError(null);
        try {
            const data = await importRequirements(activeRun.id, selectedIds);
            if (data.run) {
                setActiveRun(data.run);
                setHistory(prev => prev.map(run => run.id === data.run.id ? data.run : run));
            }
        } catch (e: unknown) {
            setReportImportError(e instanceof Error ? e.message : 'Failed to import requirements.');
        } finally {
            setImportingRequirementIds(prev => prev.filter(id => !markers.includes(id)));
        }
    };

    // Download generated spec as file
    const downloadSpec = (content?: string, filename?: string) => {
        // If no arguments provided, use state (for new flow spec generation)
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
    };

    // Split spec into individual tests
    const splitSpec = async () => {
        if (!generatedSpec?.spec_file) return;

        setSplittingSpec(true);
        setSplitResult(null);
        try {
            const data = await splitSpecFile(generatedSpec.spec_file);
            setSplitResult(data);
            setWorkspaceStatus(`Split spec into ${data.count} files.`);
            toast.success('Spec split into individual tests');
        } catch (e) {
            console.error("Failed to split spec", e);
            const message = e instanceof Error ? e.message : 'Please try again.';
            toast.error(`Failed to split spec: ${message}`);
        } finally {
            setSplittingSpec(false);
        }
    };

    const definitionById = useMemo(() => new Map(agentDefinitions.map(definition => [definition.id, definition])), [agentDefinitions]);
    const selectedDefinition = useMemo(() => definitionById.get(selectedDefinitionId), [definitionById, selectedDefinitionId]);
    const toolsByCategory = useMemo(() => toolCatalog.reduce<Record<string, AgentTool[]>>((acc, tool) => {
        acc[tool.category] = acc[tool.category] || [];
        acc[tool.category].push(tool);
        return acc;
    }, {}), [toolCatalog]);
    const toolById = useMemo(() => new Map(toolCatalog.map(tool => [tool.id, tool])), [toolCatalog]);

    const resetDefinitionForm = () => {
        setDefinitionForm(defaultDefinitionForm(agentRuntime));
        setDefinitionFormError(null);
        setDefinitionRuntimeOpen(false);
    };

    const openCreateAgentBuilder = () => {
        resetDefinitionForm();
        selectAgentMode('custom');
        setAgentActionIntent({ type: 'createAgent' });
        queryCreateOpenRef.current = true;
        setBuilderOpen(true);
        setWorkspaceStatus('Opening custom agent builder.');
        updateWorkspaceQuery({ agent: 'custom', create: true });
        markAgentsAction({ action: 'createAgent', phase: 'modal-open' });
    };

    const editDefinition = (definition: AgentDefinition) => {
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
    };

    const closeCustomAgentBuilder = () => {
        setBuilderOpen(false);
        setDefinitionRuntimeOpen(false);
        setDefinitionFormError(null);
        if (agentActionIntent.type === 'createAgent') {
            setAgentActionIntent({ type: 'none' });
        }
        queryCreateOpenRef.current = false;
        updateWorkspaceQuery({ create: false });
        markAgentsAction({ action: 'createAgent', phase: 'closed' });
    };

    const editDefinitionFromMenu = (definition: AgentDefinition, event?: Event) => {
        event?.preventDefault();
        event?.stopPropagation();
        setOpenDefinitionMenuId(null);
        editDefinition(definition);
    };

    const archiveDefinitionFromMenu = (definition: AgentDefinition, event?: Event) => {
        event?.preventDefault();
        event?.stopPropagation();
        setOpenDefinitionMenuId(null);
        setArchiveCandidate(definition);
    };

    const toggleDefinitionTool = (toolId: string) => {
        setDefinitionForm(prev => ({
            ...prev,
            tool_ids: prev.tool_ids.includes(toolId)
                ? prev.tool_ids.filter(id => id !== toolId)
                : [...prev.tool_ids, toolId],
        }));
    };

    const toggleCategoryTools = (tools: AgentTool[]) => {
        const ids = tools.map(tool => tool.id);
        const allSelected = ids.every(id => definitionForm.tool_ids.includes(id));
        setDefinitionForm(prev => ({
            ...prev,
            tool_ids: allSelected
                ? prev.tool_ids.filter(id => !ids.includes(id))
                : Array.from(new Set([...prev.tool_ids, ...ids])),
        }));
    };

    const saveDefinition = async () => {
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
                project_id: currentProject?.id,
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
    };

    const archiveDefinition = async (definition: AgentDefinition) => {
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
    };

    const handleRun = async (submittedTargetUrl?: string) => {
        const validationError = validateAgentRunInput({
            selectedAgent: 'custom',
            selectedDefinitionId,
            url,
            authType,
            sessionId,
            testData: '',
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

            const targetUrl = (submittedTargetUrl || '').trim() || url.trim() || targetUrlRef.current.trim() || (typeof document !== 'undefined'
                ? ((document.getElementById('agents-target-url') as HTMLInputElement | null)?.value || '').trim()
                : '');
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
                project_id: currentProject?.id,
            };

            const data = await startAgentDefinitionRun(selectedDefinitionId, body);
            // Refresh history but select the new run
            await fetchHistory();
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
    };

    const controlAgentRun = async (action: 'pause' | 'resume' | 'cancel') => {
        if (!activeRun) return;
        setRunControlPending(action);
        try {
            const data = await controlAgentRunApi(activeRun.id, action, currentProject?.id);
            setActiveRun(data);
            await fetchHistory();
            setWorkspaceStatus(`Run ${action} request sent.`);
            toast.success(`Run ${action} request sent`);
        } catch (e: any) {
            toast.error(e.message || `Failed to ${action} agent run`);
        } finally {
            setRunControlPending(null);
        }
    };

    const retryAgentRun = async () => {
        if (!activeRun || !isAgentRunTerminal(activeRun.status)) return;
        setRunControlPending('retry');
        try {
            const data = await retryAgentRunApi(activeRun.id, currentProject?.id);
            setActiveRun(data);
            await fetchHistory();
            selectRun(activeRun.id);
            setWorkspaceStatus('Retrying in same run using saved browser auth/session artifacts.');
            toast.success('Retrying in same run');
        } catch (e: any) {
            toast.error(e.message || 'Failed to retry agent run');
        } finally {
            setRunControlPending(null);
        }
    };

    const exportAgentTrace = () => {
        if (!activeRun) return;
        window.open(agentRunTraceExportUrl(activeRun.id, currentProject?.id), '_blank', 'noopener,noreferrer');
    };

    const handleSynthesize = async () => {
        if (!selectedRunId || !activeRun || activeRun.agent_type !== 'exploratory') {
            toast.error("Please select a completed exploratory run");
            return;
        }

        if (!['completed', 'completed_partial'].includes(activeRun.status)) {
            toast.error("Please wait for the exploration to complete");
            return;
        }
        if (!explorerCanGenerateSpecs) {
            toast.error("This exploration has no evidence-backed flows to synthesize");
            return;
        }

        setIsSynthesizing(true);
        try {
            await synthesizeExploratorySpecs(selectedRunId);

            // Poll for specs
            setTimeout(() => {
                fetchSpecs(selectedRunId!);
                setIsSynthesizing(false);
            }, 2000);

        } catch (e: any) {
            toast.error(e.message || 'Spec synthesis failed');
            setIsSynthesizing(false);
        }
    };

    const dateFormatter = useMemo(() => new Intl.DateTimeFormat(undefined, {
        hour: 'numeric',
        minute: 'numeric',
        day: 'numeric',
        month: 'short',
    }), []);

    const formatDate = (iso: string) => {
        return dateFormatter.format(new Date(iso));
    };

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
    }, [missingReportSpecItemMessage, agentActionIntent]);

    useEffect(() => {
        if (agentActionIntent.type !== 'reviewReportSpec' || !reportSpecReview?.item) return;
        const kind = agentActionIntent.itemType === 'finding' ? 'finding' : 'test idea';
        setWorkspaceStatus(`Reviewing ${kind} ${reportSpecReview.item.id} for spec generation.`);
    }, [agentActionIntent, reportSpecReview]);

    const flowSpecLatestImage = sortArtifactsByModifiedAt((flowSpecAgentRun?.artifacts || []).filter(artifact => artifact.type === 'image'))[0];
    const flowSpecRunLive = Boolean(flowSpecAgentRun && LIVE_AGENT_STATUSES.has(flowSpecAgentRun.status));
    const flowSpecShowBrowser = Boolean(flowSpecAgentRunId && (generatingSpec || flowSpecRunLive || flowSpecLatestImage));
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
    const explorerResult = activeRun?.agent_type === 'exploratory' ? activeRun.result || {} : {};
    const explorerDiagnostics = explorerResult?.diagnostics || {};
    const explorerFinalizerDiagnostics = explorerDiagnostics?.finalizer || {};
    const explorerEventCounts = explorerResult?.event_counts || {};
    const explorerEvidenceEventCount = explorerDiagnostics.evidence_event_count
        ?? Object.values(explorerEventCounts).reduce((sum: number, value: any) => sum + Number(value || 0), 0);
    const explorerArtifactEvidence = explorerResult?.artifact_evidence && typeof explorerResult.artifact_evidence === 'object'
        ? explorerResult.artifact_evidence
        : {};
    const explorerArtifactEvidenceItems = Array.isArray(explorerArtifactEvidence.artifacts)
        ? explorerArtifactEvidence.artifacts
        : [];
    const explorerRunArtifacts = (activeRun?.artifacts || []).length > 0
        ? activeRun?.artifacts || []
        : explorerArtifactEvidenceItems;
    const explorerCapturedArtifacts = sortArtifactsByModifiedAt(explorerRunArtifacts as AgentArtifact[]);
    const explorerScreenshotArtifacts = sortArtifactsByModifiedAt(
        explorerCapturedArtifacts.filter((artifact: AgentArtifact) => artifact.type === 'image' || /\.(png|jpe?g)$/i.test(artifact.name || ''))
    );
    const explorerArtifactCount = explorerFinalizerDiagnostics.artifact_count
        ?? explorerDiagnostics.artifact_count
        ?? explorerArtifactEvidence.artifact_count
        ?? explorerCapturedArtifacts.length;
    const explorerScreenshotCount = explorerFinalizerDiagnostics.screenshot_count
        ?? explorerDiagnostics.screenshot_count
        ?? explorerArtifactEvidence.screenshot_count
        ?? explorerScreenshotArtifacts.length;
    const explorerFlowSummaries = Array.isArray(explorerResult?.discovered_flow_summaries)
        ? explorerResult.discovered_flow_summaries
        : [];
    const explorerUnsupportedFlowCandidates = Array.isArray(explorerResult?.unsupported_flow_candidates)
        ? explorerResult.unsupported_flow_candidates
        : [];
    const explorerStructuredFlowCount = explorerFlowSummaries.length;
    const explorerContractWarnings = Array.from(new Set([
        explorerResult?.contract_warning,
        ...(Array.isArray(explorerResult?.contract_warnings) ? explorerResult.contract_warnings : []),
    ].filter(Boolean).map((warning: any) => String(warning).trim()).filter(Boolean)));
    const explorerCanGenerateSpecs = explorerStructuredFlowCount > 0;
    const visibleHistory = history;
    const queueWarnings = useMemo(() => {
        const stale = queueStatus?.stale_running ?? 0;
        const orphaned = queueStatus?.orphaned_tasks ?? 0;
        const noWorkers = (queueStatus?.active || queueStatus?.queued || 0) > 0 && (queueStatus?.workers_alive ?? queueStatus?.worker_processes_alive ?? 0) === 0;
        return {
            stale,
            orphaned,
            noWorkers,
            degraded: stale > 0 || orphaned > 0 || noWorkers,
        };
    }, [queueStatus]);
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
    const workspaceTabs: Array<{ key: AgentWorkspaceView; label: string; count?: number }> = [
        { key: 'run', label: 'Run' },
        { key: 'history', label: 'History', count: historyTotal || undefined },
        { key: 'library', label: 'Agent Library', count: agentDefinitions.length },
        { key: 'reports', label: 'Reports', count: reportSearchResults.length || undefined },
        { key: 'queue', label: 'Queue', count: (queueStatus?.active || 0) + (queueStatus?.queued || 0) || undefined },
    ];

    const renderExplorerCapturedEvidence = () => {
        if (explorerCapturedArtifacts.length === 0 && Number(explorerScreenshotCount || 0) === 0) return null;
        const previewImages = explorerScreenshotArtifacts.slice(0, 6);
        const otherArtifacts = explorerCapturedArtifacts
            .filter((artifact: AgentArtifact) => !previewImages.some((image: AgentArtifact) => image.path === artifact.path))
            .slice(0, 8);
        return (
            <div data-testid="explorer-captured-evidence" style={{ display: 'grid', gap: '0.75rem' }}>
                <div>
                    <h4 style={{ fontWeight: 600, fontSize: '1rem', margin: '0 0 0.25rem', color: 'var(--text)' }}>Captured Evidence</h4>
                    <p style={{ margin: 0, color: 'var(--text-secondary)', fontSize: '0.86rem', lineHeight: 1.45 }}>
                        Browser artifacts captured during the run are shown for review. They do not count as completed flows unless structured event IDs support a flow candidate.
                    </p>
                </div>
                {previewImages.length > 0 && (
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '0.75rem' }}>
                        {previewImages.map((artifact: AgentArtifact) => (
                            <a
                                key={artifact.path}
                                href={getArtifactUrl(artifact)}
                                target="_blank"
                                rel="noreferrer"
                                data-testid="explorer-captured-screenshot"
                                style={{ display: 'grid', gap: '0.45rem', padding: '0.6rem', background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: '8px', textDecoration: 'none' }}
                            >
                                <img
                                    src={getArtifactUrl(artifact)}
                                    alt={artifact.name}
                                    style={{ width: '100%', aspectRatio: '16 / 10', objectFit: 'cover', borderRadius: '6px', border: '1px solid var(--border)' }}
                                />
                                <span style={{ color: 'var(--text-secondary)', fontSize: '0.78rem', overflowWrap: 'anywhere' }}>{artifact.name}</span>
                            </a>
                        ))}
                    </div>
                )}
                {otherArtifacts.length > 0 && (
                    <div style={{ display: 'grid', gap: '0.4rem' }}>
                        {otherArtifacts.map((artifact: AgentArtifact) => (
                            <a
                                key={artifact.path}
                                href={getArtifactUrl(artifact)}
                                target="_blank"
                                rel="noreferrer"
                                data-testid="explorer-captured-artifact"
                                style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', padding: '0.65rem 0.75rem', background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: '8px', color: 'var(--text)', textDecoration: 'none', fontSize: '0.84rem' }}
                            >
                                {artifact.type === 'video' ? <VideoIcon size={15} /> : artifact.type === 'image' ? <ImageIcon size={15} /> : <FileText size={15} />}
                                <span style={{ overflowWrap: 'anywhere' }}>{artifact.name}</span>
                                <ExternalLink size={13} style={{ marginLeft: 'auto', color: 'var(--text-secondary)' }} />
                            </a>
                        ))}
                    </div>
                )}
            </div>
        );
    };

    const renderExplorerUnsupportedFlowCandidates = () => {
        if (explorerUnsupportedFlowCandidates.length === 0) return null;
        return (
            <div data-testid="explorer-unsupported-flow-candidates" style={{ display: 'grid', gap: '0.75rem' }}>
                <div>
                    <h4 style={{ fontWeight: 600, fontSize: '1rem', margin: '0 0 0.25rem', color: 'var(--text)' }}>Unsupported Flow Candidates ({explorerUnsupportedFlowCandidates.length})</h4>
                    <p style={{ margin: 0, color: 'var(--text-secondary)', fontSize: '0.86rem', lineHeight: 1.45 }}>
                        The model reported these candidates, but their cited evidence event IDs were missing or empty. They are visible for review and are not eligible for test generation.
                    </p>
                </div>
                <div style={{ display: 'grid', gap: '0.65rem' }}>
                    {explorerUnsupportedFlowCandidates.map((flow: any, i: number) => (
                        <div key={flow.id || i} data-testid="explorer-unsupported-flow-card" style={{ padding: '0.9rem', background: 'var(--surface)', borderRadius: '8px', border: '1px solid var(--border)' }}>
                            <h5 style={{ margin: '0 0 0.4rem', fontWeight: 650, color: 'var(--text)' }}>{flow.title || `Unsupported candidate ${i + 1}`}</h5>
                            <div style={{ color: 'var(--text-secondary)', fontSize: '0.82rem', lineHeight: 1.45, overflowWrap: 'anywhere' }}>
                                Missing evidence IDs: {(flow.missing_evidence_event_ids || []).join(', ') || 'not reported'}
                            </div>
                            {(flow.entry_point || flow.exit_point) && (
                                <div style={{ color: 'var(--text-secondary)', fontSize: '0.82rem', lineHeight: 1.45, overflowWrap: 'anywhere', marginTop: '0.3rem' }}>
                                    {flow.entry_point ? `Starts: ${flow.entry_point}` : ''}{flow.entry_point && flow.exit_point ? ' · ' : ''}{flow.exit_point ? `Ends: ${flow.exit_point}` : ''}
                                </div>
                            )}
                        </div>
                    ))}
                </div>
            </div>
        );
    };

    const renderHistoryWorkspace = () => (
        <div className="card agents-history-workspace">
            <div className="agents-history-workspace-header">
                <div>
                    <h2 style={{ margin: 0, fontSize: '1rem', fontWeight: 800 }}>Run History</h2>
                    <p style={{ margin: '0.25rem 0 0', color: 'var(--text-secondary)', fontSize: '0.85rem' }}>
                        {visibleHistory.length} of {historyTotal} runs
                    </p>
                </div>
                <button className="btn-icon agents-icon-button" type="button" onClick={() => void fetchHistory()} title="Refresh run history" aria-label="Refresh run history" disabled={historyLoading}>
                    {historyLoading ? <Loader2 className="spin" size={14} /> : <RotateCcw size={14} />}
                </button>
            </div>

            <div className="agents-history-toolbar">
                <Label htmlFor="agents-history-search" className="agents-visually-hidden">Search run history</Label>
                <div style={{ position: 'relative', minWidth: 0 }}>
                    <Search size={14} style={{ position: 'absolute', left: '0.65rem', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-secondary)' }} />
                    <Input
                        id="agents-history-search"
                        name="agents-history-search"
                        value={historySearch}
                        onChange={event => updateHistorySearch(event.target.value)}
                        placeholder="Search URL, name, or ID"
                        autoComplete="off"
                        style={{ paddingLeft: '2rem', minHeight: 40 }}
                    />
                </div>
                <div className="agents-history-filter-grid">
                    <div>
                        <Select value={historyStatusFilter} onValueChange={value => updateHistoryStatusFilter(value as AgentHistoryStatusFilter)}>
                            <SelectTrigger aria-label="Filter history by status" className="agents-history-filter-trigger">
                                <span className="truncate">Status: {AGENT_HISTORY_STATUS_FILTER_LABELS[historyStatusFilter]}</span>
                            </SelectTrigger>
                            <SelectContent>
                                <SelectItem value="all">All statuses ({historyCounts.status.all})</SelectItem>
                                <SelectItem value="active">Active ({historyCounts.status.active})</SelectItem>
                                <SelectItem value="completed">Completed ({historyCounts.status.completed})</SelectItem>
                                <SelectItem value="failed">Failed ({historyCounts.status.failed})</SelectItem>
                                <SelectItem value="cancelled">Cancelled ({historyCounts.status.cancelled})</SelectItem>
                                <SelectItem value="paused">Paused ({historyCounts.status.paused})</SelectItem>
                            </SelectContent>
                        </Select>
                    </div>
                    <div>
                        <Select value={historyTypeFilter} onValueChange={value => updateHistoryTypeFilter(value as AgentHistoryTypeFilter)}>
                            <SelectTrigger aria-label="Filter history by agent type" className="agents-history-filter-trigger">
                                <span className="truncate">Type: {AGENT_HISTORY_TYPE_FILTER_LABELS[historyTypeFilter]}</span>
                            </SelectTrigger>
                            <SelectContent>
                                <SelectItem value="all">All types ({historyCounts.type.all})</SelectItem>
                                <SelectItem value="exploratory">Explorer ({historyCounts.type.exploratory})</SelectItem>
                                <SelectItem value="custom">Custom ({historyCounts.type.custom})</SelectItem>
                                <SelectItem value="writer">Writer ({historyCounts.type.writer})</SelectItem>
                                <SelectItem value="spec_generation">Spec runs ({historyCounts.type.spec_generation})</SelectItem>
                            </SelectContent>
                        </Select>
                    </div>
                </div>
            </div>

            <div className="agents-history-list">
                {historyError ? (
                    <div style={{ padding: '1rem', color: 'var(--danger)', fontSize: '0.85rem' }}>
                        {historyError}
                    </div>
                ) : history.length === 0 && historyLoading ? (
                    <div style={{ padding: '2rem 1rem', textAlign: 'center', color: 'var(--text-secondary)', fontSize: '0.85rem' }}>
                        Loading runs...
                    </div>
                ) : history.length === 0 ? (
                    <div style={{ padding: '2rem 1rem', textAlign: 'center', color: 'var(--text-secondary)', fontSize: '0.85rem' }}>
                        No runs yet.
                    </div>
                ) : visibleHistory.length === 0 ? (
                    <div style={{ padding: '2rem 1rem', textAlign: 'center', color: 'var(--text-secondary)', fontSize: '0.85rem' }}>
                        No runs match the current filters.
                    </div>
                ) : (
                    <>
                        {visibleHistory.map(run => (
                            <button
                                key={run.id}
                                type="button"
                                className="agents-history-row agents-history-row-wide"
                                onClick={() => selectHistoryRun(run.id)}
                                aria-current={selectedRunId === run.id ? 'true' : undefined}
                                style={{
                                    background: selectedRunId === run.id ? 'rgba(59, 130, 246, 0.08)' : 'transparent',
                                    borderLeft: selectedRunId === run.id ? '3px solid var(--primary)' : '3px solid transparent'
                                }}
                            >
                                <div>
                                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.55rem', flexWrap: 'wrap' }}>
                                        <span style={{ fontWeight: 800, color: run.agent_type === 'custom' ? 'var(--success)' : run.agent_type === 'writer' || run.agent_type === 'spec_generation' ? 'var(--primary)' : 'var(--warning)' }}>
                                            {agentRunDisplayName(run)}
                                        </span>
                                        <StatusBadge status={run.status} />
                                    </div>
                                    <div style={{ marginTop: '0.35rem', fontSize: '0.85rem', overflow: 'hidden', textOverflow: 'ellipsis', color: 'var(--text)' }}>
                                        {run.config?.url?.replace('https://', '') || run.config?.agent_name || run.id}
                                    </div>
                                </div>
                                <div className="agents-history-row-meta">
                                    <span>{formatDate(run.created_at)}</span>
                                    <span>{run.id.slice(0, 8)}</span>
                                </div>
                            </button>
                        ))}
                        {historyNextCursor && (
                            <div style={{ padding: '0.9rem' }}>
                                <Button type="button" variant="outline" size="sm" onClick={loadMoreHistory} disabled={historyLoading} style={{ width: '100%' }}>
                                    {historyLoading ? <Loader2 className="spin" size={14} /> : <ChevronDown size={14} />} Load more
                                </Button>
                            </div>
                        )}
                    </>
                )}
            </div>
        </div>
    );

    return (
        <PageLayout tier="wide" style={{ paddingBottom: '4rem' }}>
            <style>{`
                .agents-workspace-grid {
                    display: grid;
                    grid-template-columns: minmax(320px, 0.85fr) minmax(0, 1.65fr);
                    gap: 1rem;
                    align-items: start;
                }
                .agents-panel {
                    min-width: 0;
                }
                .agents-panel-scroll {
                    max-height: calc(100vh - 11rem);
                    overflow-y: auto;
                }
                .agents-mobile-trigger {
                    display: none;
                }
                .agents-desktop-content {
                    display: block;
                }
                .agents-history-row {
                    width: 100%;
                    min-height: 44px;
                    text-align: left;
                    border: 0;
                    border-bottom: 1px solid var(--border);
                    background: transparent;
                    color: var(--text);
                    cursor: pointer;
                    transition: background 0.16s var(--ease-smooth), border-color 0.16s var(--ease-smooth);
                }
                .agents-history-workspace {
                    padding: 0;
                    overflow: hidden;
                }
                .agents-history-workspace-header {
                    padding: 0.9rem 1rem;
                    border-bottom: 1px solid var(--border);
                    background: var(--surface-hover);
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                    gap: 0.75rem;
                }
                .agents-history-toolbar {
                    padding: 0.9rem 1rem;
                    border-bottom: 1px solid var(--border);
                    display: grid;
                    grid-template-columns: minmax(280px, 1fr) minmax(300px, 0.75fr);
                    gap: 0.75rem;
                    align-items: center;
                }
                .agents-history-list {
                    display: grid;
                }
                .agents-history-row-wide {
                    padding: 0.9rem 1rem;
                    display: grid;
                    grid-template-columns: minmax(0, 1fr) auto;
                    gap: 1rem;
                    align-items: center;
                }
                .agents-history-row-meta {
                    display: grid;
                    gap: 0.3rem;
                    justify-items: end;
                    color: var(--text-secondary);
                    font-size: 0.76rem;
                    white-space: nowrap;
                }
                .agents-history-row:focus-visible,
                .agents-icon-button:focus-visible {
                    outline: 2px solid var(--primary);
                    outline-offset: 2px;
                }
                .agents-visually-hidden {
                    position: absolute;
                    width: 1px;
                    height: 1px;
                    padding: 0;
                    margin: -1px;
                    overflow: hidden;
                    clip: rect(0, 0, 0, 0);
                    white-space: nowrap;
                    border: 0;
                }
                .agents-action-status {
                    display: flex;
                    align-items: flex-start;
                    gap: 0.55rem;
                    margin: 0 0 1rem;
                    padding: 0.75rem 0.9rem;
                    border: 1px solid var(--border);
                    border-radius: 8px;
                    background: var(--surface-hover);
                    color: var(--text);
                    font-size: 0.86rem;
                    line-height: 1.4;
                }
                .agents-action-status[data-tone="error"] {
                    border-color: rgba(248, 113, 113, 0.35);
                    background: var(--danger-muted);
                    color: var(--danger);
                }
                .agents-action-status svg {
                    width: 16px;
                    height: 16px;
                    flex: 0 0 auto;
                    margin-top: 0.1rem;
                }
                .agents-history-filter-grid {
                    display: grid;
                    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
                    gap: 0.5rem;
                    min-width: 0;
                }
                .agents-history-filter-grid > div {
                    min-width: 0;
                }
                .agents-history-filter-trigger {
                    height: 36px !important;
                    min-height: 36px !important;
                    padding: 0 0.65rem !important;
                    font-size: 0.78rem;
                    line-height: 1;
                    white-space: nowrap;
                }
                .agents-history-filter-trigger > span {
                    min-width: 0;
                    overflow: hidden;
                    text-overflow: ellipsis;
                    white-space: nowrap;
                }
                .agents-history-filter-trigger svg {
                    width: 14px;
                    height: 14px;
                }
                .agents-workspace-tabs {
                    display: flex;
                    gap: 0.5rem;
                    flex-wrap: wrap;
                    margin-bottom: 1rem;
                }
                .agents-workspace-tab {
                    min-height: 40px;
                    padding: 0.5rem 0.75rem;
                    border: 1px solid var(--border);
                    border-radius: 8px;
                    background: var(--surface);
                    color: var(--text-secondary);
                    font-size: 0.86rem;
                    font-weight: 700;
                    cursor: pointer;
                    display: inline-flex;
                    align-items: center;
                    gap: 0.45rem;
                    transition: background 0.16s var(--ease-smooth), color 0.16s var(--ease-smooth), border-color 0.16s var(--ease-smooth);
                }
                .agents-workspace-tab[data-active="true"] {
                    background: var(--primary-glow);
                    color: var(--primary);
                    border-color: var(--primary);
                }
                .agents-workspace-tab-count {
                    display: inline-flex;
                    align-items: center;
                    align-self: center;
                    color: #8f9bb7;
                    font-size: 0.78em;
                    font-weight: 800;
                    font-variant-numeric: tabular-nums;
                    line-height: 1.2;
                }
                .agents-workspace-tab[data-active="true"] .agents-workspace-tab-count {
                    color: #8bb8ff;
                }
                .agents-workspace-tab:focus-visible,
                .agents-action-button:focus-visible {
                    outline: 2px solid var(--primary);
                    outline-offset: 2px;
                }
                .agents-setup-stack {
                    display: flex;
                    flex-direction: column;
                    gap: 0.8rem;
                    min-width: 0;
                }
                .agents-run-empty-compact {
                    display: flex;
                    align-items: center;
                    flex-wrap: wrap;
                    gap: 0.65rem;
                    padding: 0.65rem;
                    border: 1px solid var(--border);
                    border-radius: 8px;
                    background: var(--surface);
                    min-width: 0;
                }
                .agents-run-empty-icon {
                    width: 36px;
                    height: 36px;
                    border-radius: 8px;
                    display: inline-flex;
                    align-items: center;
                    justify-content: center;
                    color: var(--primary);
                    background: var(--primary-glow);
                    border: 1px solid rgba(59, 130, 246, 0.22);
                    flex: 0 0 auto;
                }
                .agents-run-empty-copy {
                    flex: 1 1 170px;
                    min-width: 0;
                }
                .agents-run-empty-copy strong {
                    display: block;
                    color: var(--text);
                    font-size: 0.82rem;
                    font-weight: 750;
                    line-height: 1.2;
                }
                .agents-run-empty-compact p {
                    margin: 0.18rem 0 0;
                    color: var(--text-secondary);
                    font-size: 0.72rem;
                    line-height: 1.35;
                    overflow-wrap: anywhere;
                }
                .agents-run-empty-action {
                    margin-left: auto;
                    min-height: 36px;
                    padding-left: 0.65rem;
                    padding-right: 0.65rem;
                }
                .agents-custom-picker-row {
                    display: grid;
                    grid-template-columns: minmax(0, 1fr) 40px;
                    gap: 0.5rem;
                    align-items: end;
                    min-width: 0;
                }
                .agents-run-details-card {
                    display: flex;
                    flex-direction: column;
                    min-width: 0;
                    overflow: hidden;
                }
                .agents-run-details-body {
                    padding: 0.85rem;
                    flex: 1 1 auto;
                    display: grid;
                    gap: 0.8rem;
                    min-height: 0;
                    min-width: 0;
                    padding-bottom: 0.85rem;
                }
                .agents-run-details-grid {
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
                    gap: 0.75rem;
                    align-items: start;
                    min-width: 0;
                }
                .agents-run-field {
                    min-width: 0;
                    display: grid;
                    gap: 0.42rem;
                }
                .agents-run-field label,
                .agents-run-field-label {
                    display: flex;
                    align-items: center;
                    gap: 0.4rem;
                    color: var(--text);
                    font-size: 0.78rem;
                    font-weight: 750;
                    line-height: 1.2;
                }
                .agents-run-field input,
                .agents-run-field select,
                .agents-run-field textarea {
                    box-sizing: border-box;
                    max-width: 100%;
                    min-width: 0;
                }
                .agents-run-field input,
                .agents-run-field select {
                    overflow: hidden;
                    text-overflow: ellipsis;
                    white-space: nowrap;
                }
                .agents-run-field-note {
                    margin: 0;
                    color: var(--text-secondary);
                    font-size: 0.7rem;
                    line-height: 1.35;
                    overflow-wrap: anywhere;
                    min-width: 0;
                }
                .agents-run-field-wide {
                    grid-column: 1 / -1;
                }
                .agents-task-prompt {
                    min-height: 74px;
                    max-height: 148px;
                    line-height: 1.4;
                }
                .agents-disclosure {
                    border: 1px solid var(--border);
                    border-radius: 8px;
                    background: var(--surface-hover);
                    display: grid;
                    grid-template-rows: auto;
                    overflow: hidden;
                    min-width: 0;
                    max-width: 100%;
                }
                .agents-disclosure-trigger {
                    width: 100%;
                    min-height: 40px;
                    padding: 0.55rem 0.7rem;
                    border: 0;
                    background: transparent;
                    color: var(--text);
                    display: flex;
                    align-items: center;
                    justify-content: space-between;
                    gap: 0.7rem;
                    cursor: pointer;
                    text-align: left;
                    font-size: 0.82rem;
                    font-weight: 800;
                }
                .agents-disclosure-trigger-main {
                    display: flex;
                    flex-direction: column;
                    gap: 0.12rem;
                    min-width: 0;
                }
                .agents-disclosure-trigger-label,
                .agents-disclosure-trigger-summary {
                    overflow: hidden;
                    text-overflow: ellipsis;
                    white-space: nowrap;
                }
                .agents-disclosure-trigger-summary {
                    color: var(--text-secondary);
                    font-size: 0.7rem;
                    font-weight: 700;
                }
                .agents-disclosure-trigger:focus-visible {
                    outline: 2px solid var(--primary);
                    outline-offset: -2px;
                }
                .agents-disclosure-body {
                    padding: 0 0.7rem 0.75rem;
                    display: grid;
                    gap: 0.55rem;
                    min-width: 0;
                }
                .agents-context-disclosure {
                    grid-column: 1 / -1;
                }
                .agents-context-disclosure-custom {
                    background: var(--background);
                }
                .agents-context-disclosure-open {
                    min-height: 250px;
                }
                .agents-run-summary {
                    display: flex;
                    flex-wrap: wrap;
                    gap: 0.45rem;
                    align-items: center;
                    min-width: 0;
                    max-width: 100%;
                    overflow: hidden;
                }
                .agents-run-chip {
                    flex: 0 1 auto;
                    min-width: 0;
                    max-width: 100%;
                    min-height: 28px;
                    padding: 0.3rem 0.55rem;
                    border: 1px solid var(--border);
                    border-radius: 999px;
                    background: var(--background);
                    color: var(--text-secondary);
                    font-size: 0.73rem;
                    font-weight: 750;
                    overflow: hidden;
                    text-overflow: ellipsis;
                    white-space: nowrap;
                }
                .agents-run-plan {
                    display: grid;
                    gap: 0.45rem;
                    padding-top: 0.2rem;
                    min-width: 0;
                }
                .agents-run-plan-row {
                    display: grid;
                    grid-template-columns: 92px minmax(0, 1fr);
                    gap: 0.5rem;
                    font-size: 0.78rem;
                    line-height: 1.35;
                }
                .agents-run-plan-row strong {
                    color: var(--text-secondary);
                    font-weight: 750;
                }
                .agents-run-plan-row span {
                    min-width: 0;
                    overflow-wrap: anywhere;
                }
                .agents-run-footer {
                    padding: 0.75rem 0.85rem;
                    border-top: 1px solid var(--border);
                    background: color-mix(in srgb, var(--background-raised) 92%, transparent);
                    backdrop-filter: blur(10px);
                }
                .agents-run-details-card-custom .agents-run-footer {
                    z-index: 2;
                    flex: 0 0 auto;
                }
                .agents-start-button {
                    width: 100%;
                    min-height: 44px;
                    padding: 0.75rem;
                    border-radius: 6px;
                    font-size: 0.9rem;
                    background: var(--primary);
                    color: white;
                    font-weight: 700;
                    border: none;
                    cursor: pointer;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    gap: 0.5rem;
                }
                .agents-start-button:disabled {
                    cursor: not-allowed;
                    opacity: 0.7;
                }
                .agents-builder-grid {
                    display: grid;
                    grid-template-columns: minmax(330px, 0.92fr) minmax(360px, 1.08fr);
                    gap: 1.1rem;
                    align-items: start;
                }
                .agents-builder-dialog {
                    padding: 1.35rem !important;
                }
                .agents-builder-form {
                    display: grid;
                    gap: 0.85rem;
                    align-content: start;
                    min-width: 0;
                }
                .agents-builder-field {
                    display: grid;
                    gap: 0.38rem;
                    min-width: 0;
                }
                .agents-builder-split {
                    display: grid;
                    grid-template-columns: minmax(0, 1fr) minmax(130px, 0.8fr);
                    gap: 0.7rem;
                }
                .agents-runtime-select-content {
                    width: var(--radix-select-trigger-width) !important;
                    min-width: var(--radix-select-trigger-width) !important;
                }
                .agents-builder-textarea {
                    width: 100%;
                    min-height: 178px;
                    padding: 0.75rem;
                    border-radius: var(--radius);
                    font-size: 0.86rem;
                    border: 1px solid var(--border);
                    background: var(--background-raised);
                    color: var(--text);
                    resize: vertical;
                    line-height: 1.35;
                }
                .agents-builder-tools {
                    display: grid;
                    gap: 0.65rem;
                    align-content: start;
                    min-width: 0;
                }
                .agents-builder-tools-header {
                    display: flex;
                    justify-content: space-between;
                    gap: 0.75rem;
                    align-items: center;
                    min-width: 0;
                }
                .agents-builder-selected-count {
                    min-height: 26px;
                    padding: 0.25rem 0.6rem;
                    border-radius: 999px;
                    background: var(--surface-hover);
                    color: var(--text-secondary);
                    font-size: 0.78rem;
                    font-weight: 750;
                    white-space: nowrap;
                }
                .agents-builder-tools-list {
                    max-height: min(520px, calc(86vh - 210px));
                    overflow-y: auto;
                    border: 1px solid var(--border);
                    border-radius: 10px;
                    padding: 0.8rem;
                    display: grid;
                    gap: 1rem;
                    background: rgba(15, 22, 41, 0.32);
                }
                .agents-tool-category-header {
                    display: flex;
                    align-items: center;
                    justify-content: space-between;
                    gap: 0.5rem;
                }
                .agents-tool-category-title {
                    font-size: 0.74rem;
                    color: var(--text-secondary);
                    font-weight: 800;
                    text-transform: uppercase;
                    letter-spacing: 0;
                }
                .agents-tool-row {
                    display: grid;
                    grid-template-columns: 24px minmax(0, 1fr);
                    gap: 0.55rem;
                    align-items: start;
                    min-height: 48px;
                    cursor: pointer;
                }
                .agents-tool-row input {
                    width: 16px;
                    height: 16px;
                    margin-top: 0.18rem;
                    accent-color: var(--primary);
                }
                .agents-tool-title-line {
                    display: flex;
                    gap: 0.45rem;
                    align-items: center;
                    flex-wrap: wrap;
                    min-width: 0;
                }
                .agents-tool-label {
                    font-weight: 750;
                    font-size: 0.83rem;
                    line-height: 1.2;
                }
                .agents-tool-risk-pill {
                    display: inline-flex;
                    align-items: center;
                    min-height: 22px;
                    padding: 0.18rem 0.52rem;
                    border: 1px solid;
                    border-radius: 999px;
                    font-size: 0.68rem;
                    font-weight: 800;
                    line-height: 1;
                    text-transform: lowercase;
                }
                .agents-tool-description {
                    display: block;
                    margin-top: 0.18rem;
                    color: var(--text-secondary);
                    line-height: 1.35;
                    font-size: 0.78rem;
                }
                .agents-builder-footer {
                    gap: 0.6rem;
                }
                .agents-report-edit-dialog {
                    background: linear-gradient(180deg, rgba(21, 29, 48, 0.98), rgba(15, 22, 41, 0.98)) !important;
                    border-color: var(--border-bright) !important;
                    box-shadow: 0 28px 80px rgba(0, 0, 0, 0.48), 0 0 0 1px rgba(148, 163, 184, 0.05) !important;
                }
                .agents-report-edit-header {
                    padding: 1.35rem 4.5rem 1rem 1.35rem;
                    border-bottom: 1px solid var(--border);
                    background: rgba(10, 15, 26, 0.24);
                    text-align: left;
                    gap: 0.3rem;
                }
                .agents-report-edit-kicker {
                    width: fit-content;
                    max-width: 100%;
                    padding: 0.24rem 0.55rem;
                    border: 1px solid rgba(147, 197, 253, 0.22);
                    border-radius: 999px;
                    background: rgba(59, 130, 246, 0.11);
                    color: #bfdbfe;
                    font-size: 0.72rem;
                    font-weight: 800;
                    line-height: 1;
                    letter-spacing: 0;
                    overflow: hidden;
                    text-overflow: ellipsis;
                    white-space: nowrap;
                }
                .agents-report-edit-title {
                    margin: 0.15rem 0 0;
                    font-size: 1.05rem;
                    line-height: 1.25;
                    letter-spacing: 0;
                }
                .agents-report-edit-description {
                    margin: 0;
                    max-width: 560px;
                    color: var(--text-secondary) !important;
                    font-size: 0.86rem;
                    line-height: 1.45;
                    letter-spacing: 0;
                }
                .agents-report-edit-body {
                    min-height: 0;
                    overflow-y: auto;
                    padding: 1.15rem 1.35rem 1.25rem;
                }
                .agents-report-edit-form {
                    display: grid;
                    gap: 0.9rem;
                }
                .agents-report-edit-grid {
                    display: grid;
                    grid-template-columns: repeat(2, minmax(0, 1fr));
                    gap: 0.85rem;
                    align-items: start;
                }
                .agents-report-edit-grid--title {
                    grid-template-columns: minmax(0, 1fr) minmax(150px, 190px);
                }
                .agents-report-edit-field {
                    display: grid;
                    gap: 0.42rem;
                    min-width: 0;
                }
                .agents-report-edit-field label {
                    color: var(--text);
                    font-size: 0.78rem;
                    font-weight: 800;
                    line-height: 1.2;
                    letter-spacing: 0;
                }
                .agents-report-edit-input,
                .agents-report-edit-select-trigger,
                .agents-report-edit-textarea {
                    border-color: var(--border-bright) !important;
                    background: rgba(10, 15, 26, 0.58) !important;
                    box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.02);
                }
                .agents-report-edit-input,
                .agents-report-edit-select-trigger {
                    min-height: 42px;
                    font-size: 0.88rem;
                }
                .agents-report-edit-select-trigger {
                    color: var(--text);
                    border-radius: var(--radius);
                }
                .agents-report-edit-textarea {
                    width: 100%;
                    min-height: 96px;
                    padding: 0.7rem 0.78rem;
                    border: 1px solid var(--border-bright);
                    border-radius: var(--radius);
                    color: var(--text);
                    font-family: inherit;
                    font-size: 0.88rem;
                    line-height: 1.5;
                    resize: vertical;
                    outline: none;
                }
                .agents-report-edit-textarea[data-size="lg"] {
                    min-height: 126px;
                }
                .agents-report-edit-input:focus,
                .agents-report-edit-textarea:focus,
                .agents-report-edit-select-trigger:focus,
                .agents-report-edit-select-trigger[data-state="open"] {
                    border-color: rgba(96, 165, 250, 0.82) !important;
                    box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.18), inset 0 1px 0 rgba(255, 255, 255, 0.03) !important;
                }
                .agents-report-edit-input:disabled,
                .agents-report-edit-textarea:disabled,
                .agents-report-edit-select-trigger:disabled {
                    cursor: not-allowed;
                    opacity: 0.58;
                }
                .agents-report-edit-select-content {
                    width: var(--radix-select-trigger-width) !important;
                    min-width: var(--radix-select-trigger-width) !important;
                }
                .agents-report-edit-footer {
                    gap: 0.65rem;
                    justify-content: flex-end;
                    padding: 1rem 1.35rem;
                    border-top: 1px solid var(--border);
                    background: rgba(10, 15, 26, 0.36);
                }
                .agents-report-search-grid {
                    display: grid;
                    grid-template-columns: minmax(220px, 1fr) repeat(2, minmax(150px, 0.35fr));
                    gap: 0.65rem;
                }
                .agents-definition-action-trigger {
                    width: 32px;
                    height: 32px;
                    margin-right: 0.45rem;
                    border-radius: 8px;
                    color: var(--text-secondary) !important;
                }
                .agents-definition-action-trigger:hover,
                .agents-definition-action-trigger[data-state="open"] {
                    background: var(--surface-active) !important;
                    color: var(--text) !important;
                }
                .agents-definition-action-trigger:focus-visible {
                    outline: 2px solid var(--primary);
                    outline-offset: 2px;
                }
                .agents-definition-action-menu {
                    min-width: 132px;
                    padding: 0.35rem;
                    background: var(--background-raised) !important;
                    border-color: var(--border) !important;
                    border-radius: 10px !important;
                    box-shadow: 0 14px 32px rgba(0, 0, 0, 0.35) !important;
                }
                .agents-definition-action-item {
                    min-height: 32px;
                    padding: 0.4rem 0.55rem;
                    border-radius: 7px;
                    font-size: 0.82rem;
                    font-weight: 650;
                    cursor: pointer;
                }
                .agents-definition-action-item[data-highlighted] {
                    background: var(--surface-hover);
                    color: var(--text);
                }
                .agents-definition-action-item svg {
                    width: 14px;
                    height: 14px;
                }
                .agents-definition-action-item-danger {
                    color: var(--danger) !important;
                }
                .agents-definition-action-item-danger[data-highlighted] {
                    background: var(--danger-muted);
                    color: var(--danger) !important;
                }
                .agents-library-panel {
                    padding: 1rem;
                    display: grid;
                    gap: 1rem;
                }
                .agents-library-header {
                    display: flex;
                    justify-content: space-between;
                    gap: 1rem;
                    align-items: flex-start;
                    flex-wrap: wrap;
                }
                .agents-library-grid {
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
                    gap: 0.85rem;
                }
                .agents-library-card {
                    min-width: 0;
                    padding: 1rem;
                    border: 1px solid var(--border);
                    border-radius: 10px;
                    background: linear-gradient(180deg, rgba(38, 52, 80, 0.72), rgba(30, 42, 66, 0.92));
                    display: grid;
                    gap: 0.85rem;
                    align-content: space-between;
                    transition: border-color 0.16s var(--ease-smooth), background 0.16s var(--ease-smooth), box-shadow 0.16s var(--ease-smooth);
                }
                .agents-library-card[data-selected="true"] {
                    border-color: var(--primary);
                    background: linear-gradient(180deg, rgba(59, 130, 246, 0.2), rgba(30, 42, 66, 0.94));
                    box-shadow: inset 0 0 0 1px rgba(59, 130, 246, 0.18);
                }
                .agents-library-card-header {
                    display: grid;
                    grid-template-columns: minmax(0, 1fr) auto;
                    gap: 0.7rem;
                    align-items: start;
                }
                .agents-library-card-title {
                    margin: 0;
                    font-size: 0.98rem;
                    font-weight: 800;
                    line-height: 1.25;
                    overflow-wrap: anywhere;
                }
                .agents-library-card-description {
                    margin: 0.28rem 0 0;
                    color: var(--text-secondary);
                    font-size: 0.82rem;
                    line-height: 1.45;
                    overflow-wrap: anywhere;
                }
                .agents-library-menu-trigger {
                    width: 36px;
                    height: 36px;
                    margin-right: 0;
                }
                .agents-library-card-meta {
                    display: flex;
                    gap: 0.45rem;
                    flex-wrap: wrap;
                    color: var(--text-secondary);
                    font-size: 0.78rem;
                }
                .agents-library-run-button {
                    width: 100%;
                    min-height: 44px;
                    padding: 0 1rem;
                    border: 1px solid rgba(147, 197, 253, 0.32) !important;
                    box-shadow: 0 10px 22px -16px rgba(59, 130, 246, 0.82);
                    font-size: 0.9rem;
                    font-weight: 800;
                }
                .agents-library-run-button:hover:not(:disabled) {
                    background: var(--primary-hover) !important;
                    border-color: rgba(191, 219, 254, 0.5) !important;
                }
                .agents-library-empty {
                    padding: 2rem;
                    text-align: center;
                    border: 1px solid var(--border);
                    border-radius: 8px;
                    color: var(--text-secondary);
                }
                @media (max-width: 1180px) {
                    .agents-workspace-grid {
                        grid-template-columns: minmax(300px, 0.85fr) minmax(0, 1.35fr);
                    }
                }
                @media (max-width: 860px) {
                    .agents-workspace-grid {
                        grid-template-columns: minmax(0, 1fr);
                    }
                    .agents-setup-panel,
                    .agents-output-panel {
                        grid-column: auto;
                        grid-row: auto;
                    }
                    .agents-setup-panel {
                        order: -1;
                    }
                    .agents-run-details-body {
                        padding: 0.65rem;
                        gap: 0.55rem;
                    }
                    .agents-panel-scroll {
                        max-height: none;
                        overflow: visible;
                    }
                    .agents-mobile-trigger {
                        display: inline-flex;
                    }
                    .agents-desktop-content[data-open="false"] {
                        display: none;
                    }
                    .agents-history-toolbar,
                    .agents-history-row-wide {
                        grid-template-columns: minmax(0, 1fr);
                    }
                    .agents-history-row-meta {
                        justify-items: start;
                    }
                }
                @media (max-width: 720px) {
                    .agents-run-details-grid {
                        grid-template-columns: minmax(0, 1fr);
                    }
                    .agents-run-empty-compact {
                        align-items: flex-start;
                    }
                    .agents-run-empty-icon {
                        width: 32px;
                        height: 32px;
                    }
                    .agents-run-empty-action {
                        width: 100%;
                        margin-left: 0;
                    }
                    .agents-builder-grid {
                        grid-template-columns: minmax(0, 1fr);
                    }
                    .agents-builder-split {
                        grid-template-columns: minmax(0, 1fr);
                    }
                    .agents-builder-tools-list {
                        max-height: 420px;
                    }
                    .agents-report-search-grid {
                        grid-template-columns: minmax(0, 1fr);
                    }
                    .agents-report-edit-header {
                        padding: 1.15rem 3.75rem 0.9rem 1rem;
                    }
                    .agents-report-edit-body {
                        padding: 1rem;
                    }
                    .agents-report-edit-grid,
                    .agents-report-edit-grid--title {
                        grid-template-columns: minmax(0, 1fr);
                    }
                    .agents-report-edit-footer {
                        padding: 0.9rem 1rem;
                        flex-direction: column-reverse;
                    }
                    .agents-report-edit-footer button {
                        width: 100%;
                    }
                    .agents-library-grid {
                        grid-template-columns: minmax(0, 1fr);
                    }
                    .agents-library-header .agents-library-create-button {
                        width: 100%;
                    }
                }
            `}</style>
            <PageHeader
                title="Autonomous Agents"
                subtitle="Deploy AI agents to explore, test, and specify your application autonomously."
                icon={<Bot size={20} />}
            />

            <div aria-live="polite" className="agents-visually-hidden">{workspaceStatus}</div>
            {workspaceStatus && (
                <div
                    role="status"
                    data-testid="agents-action-status"
                    className="agents-action-status"
                    data-tone={workspaceStatus.toLowerCase().includes('failed') || workspaceStatus.toLowerCase().includes('missing') || workspaceStatus.toLowerCase().includes('not found') ? 'error' : 'info'}
                >
                    {workspaceStatus.toLowerCase().includes('failed') || workspaceStatus.toLowerCase().includes('missing') || workspaceStatus.toLowerCase().includes('not found') ? (
                        <AlertTriangle aria-hidden="true" />
                    ) : (
                        <Info aria-hidden="true" />
                    )}
                    <span>{workspaceStatus}</span>
                </div>
            )}

            <div className="agents-workspace-tabs" role="tablist" aria-label="Agents workspace views">
                {workspaceTabs.map(tab => (
                    <button
                        key={tab.key}
                        type="button"
                        role="tab"
                        aria-selected={workspaceView === tab.key}
                        data-active={workspaceView === tab.key ? 'true' : 'false'}
                        className="agents-workspace-tab"
                        onClick={() => selectWorkspaceView(tab.key)}
                    >
                        {tab.label}
                        {tab.count ? <span className="agents-workspace-tab-count">{tab.count}</span> : null}
                    </button>
                ))}
            </div>

            {workspaceView === 'run' && (
            <div className="agents-workspace-grid">

                {/* Left Column: Configuration */}
                <Collapsible open={setupOpen} onOpenChange={setSetupOpen} className="agents-panel agents-setup-panel">
                    <div className="agents-setup-stack">
                    <div
                        id="agents-run-setup-panel"
                        className="card agents-run-details-card agents-run-details-card-custom"
                    >
                        <div style={{ padding: '0.8rem 0.85rem', borderBottom: '1px solid var(--border)', background: 'var(--surface-hover)', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '0.75rem' }}>
                            <div>
                                <h3 style={{ fontWeight: 700, fontSize: '0.9rem', margin: 0 }}>Run Setup</h3>
                                <p style={{ margin: '0.2rem 0 0', color: 'var(--text-secondary)', fontSize: '0.74rem' }}>
                                    {agentDefinitions.length} custom saved
                                </p>
                            </div>
                            <CollapsibleTrigger asChild>
                                <button className="btn-icon agents-icon-button agents-mobile-trigger" type="button" aria-label={setupOpen ? 'Collapse run setup' : 'Expand run setup'}>
                                    <ChevronDown size={14} />
                                </button>
                            </CollapsibleTrigger>
                        </div>
                        <CollapsibleContent forceMount>
                        <div className="agents-desktop-content" data-open={setupOpen ? 'true' : 'false'}>
                        <div className="agents-run-details-body">
                        <div className="agents-run-details-grid">
                        <div className="agents-run-field agents-run-field-wide">
                            {agentDefinitions.length === 0 ? (
                                <div className="agents-run-empty-compact">
                                    <span className="agents-run-empty-icon" aria-hidden="true">
                                        <PackageOpen size={16} />
                                    </span>
                                    <div className="agents-run-empty-copy">
                                        <strong>No runnable agents yet.</strong>
                                        <p>Create a saved custom agent to run it from this workspace.</p>
                                    </div>
                                    <Button type="button" size="sm" variant="outline" className="agents-run-empty-action" onClick={openCreateAgentBuilder} aria-label="Create custom agent">
                                        <Plus size={14} /> Create Agent
                                    </Button>
                                </div>
                            ) : (
                                <div className="agents-custom-picker-row">
                                    <div className="agents-run-field">
                                        <label htmlFor="agents-definition-select">Runnable Agent</label>
                                        <select
                                            id="agents-definition-select"
                                            name="definitionId"
                                            value={selectedDefinitionId}
                                            onChange={e => selectDefinition(e.target.value)}
                                            style={{ width: '100%', padding: '0.6rem', borderRadius: '6px', fontSize: '0.9rem', border: '1px solid var(--input-border)', background: 'var(--input-bg)', color: 'var(--text)' }}
                                        >
                                            <option value="">Select an agent</option>
                                            {agentDefinitions.map(definition => (
                                                <option key={definition.id} value={definition.id}>{definition.name}</option>
                                            ))}
                                        </select>
                                        {selectedDefinition && (
                                            <p className="agents-run-field-note">
                                                {selectedDefinition.description || `${selectedDefinition.tool_ids.length} selected tools`} · Runtime: Claude SDK
                                            </p>
                                        )}
                                    </div>
                                    <Button type="button" size="icon" variant="outline" onClick={openCreateAgentBuilder} title="Create agent" aria-label="Create custom agent">
                                        <Plus size={15} />
                                    </Button>
                                </div>
                            )}
                        </div>

                        {runSetupReady && (!selectedDefinitionId || selectedDefinition) && (
                            <div className="agents-run-field">
                                <label htmlFor="agents-target-url">Target URL</label>
                                <input
                                    id="agents-target-url"
                                    name="targetUrl"
                                    type="url"
                                    placeholder="Optional target URL"
                                    defaultValue={url}
                                    onChange={e => {
                                        targetUrlRef.current = e.target.value;
                                        setUrl(e.target.value);
                                    }}
                                    onInput={e => {
                                        targetUrlRef.current = e.currentTarget.value;
                                        setUrl(e.currentTarget.value);
                                    }}
                                    autoComplete="url"
                                    style={{
                                        width: '100%', padding: '0.6rem', borderRadius: '6px', fontSize: '0.9rem',
                                        border: '1px solid var(--input-border)', background: 'var(--input-bg)', color: 'var(--text)'
                                    }}
                                />
                            </div>
                        )}

                        <div className="agents-run-field">
                            <label htmlFor="agents-custom-session-select">Browser Login Session</label>
                            <select
                                id="agents-custom-session-select"
                                name="customBrowserAuthSession"
                                value={authType === 'session' ? sessionId : ''}
                                onChange={e => {
                                    setSessionId(e.target.value);
                                    setAuthType(e.target.value ? 'session' : 'none');
                                }}
                                style={{
                                    width: '100%', padding: '0.5rem', borderRadius: '4px', fontSize: '0.85rem',
                                    border: '1px solid var(--input-border)', background: 'var(--input-bg)', color: 'var(--text)'
                                }}
                            >
                                <option value="">No browser login session</option>
                                {sessions.map(s => (
                                    <option key={s.id} value={s.id} disabled={!isBrowserAuthSessionSelectable(s)}>
                                        {browserAuthSessionLabel(s)}
                                    </option>
                                ))}
                            </select>
                            <p style={{ fontSize: '0.7rem', color: 'var(--text-secondary)', marginTop: '0.5rem' }}>
                                {sessions.length === 0
                                    ? 'No browser login sessions found in Settings.'
                                    : `${sessions.filter(isBrowserAuthSessionSelectable).length} active browser login session${sessions.filter(isBrowserAuthSessionSelectable).length !== 1 ? 's' : ''} available`}
                            </p>
                        </div>

                        <div className="agents-run-field agents-run-field-wide">
                            <label htmlFor="agents-instructions">Task Prompt</label>
                            <textarea
                                className="agents-task-prompt"
                                id="agents-instructions"
                                name="instructions"
                                placeholder="Inspect the API calls triggered by the login and checkout flows."
                                value={instructions}
                                onChange={e => setInstructions(e.target.value)}
                                rows={3}
                                style={{
                                    width: '100%', padding: '0.6rem', borderRadius: '6px', fontSize: '0.9rem',
                                    border: '1px solid var(--input-border)', background: 'var(--input-bg)', color: 'var(--text)',
                                    resize: 'vertical'
                                }}
                            />
                        </div>
                        </div>

                        <div className={`agents-disclosure agents-context-disclosure agents-context-disclosure-custom${contextDataOpen ? ' agents-context-disclosure-open' : ''}`}>
                            <button
                                type="button"
                                className="agents-disclosure-trigger"
                                aria-expanded={contextDataOpen}
                                aria-controls="agents-context-test-data-panel"
                                onClick={() => setContextDataOpen(open => !open)}
                            >
                                <span className="agents-disclosure-trigger-main">
                                    <span className="agents-disclosure-trigger-label">Context & Test Data</span>
                                    <span className="agents-disclosure-trigger-summary">{testDataRefsSummary}</span>
                                </span>
                                <ChevronDown size={15} aria-hidden="true" />
                            </button>
                            {contextDataOpen && (
                                <div id="agents-context-test-data-panel" className="agents-disclosure-body">
                                    <div className="agents-run-field">
                                        <label htmlFor="agents-test-data-refs">Project Test Data Refs</label>
                                        <Input
                                            id="agents-test-data-refs"
                                            name="testDataRefs"
                                            value={testDataRefs}
                                            onChange={e => setTestDataRefs(e.target.value)}
                                            placeholder="Refs appear here after adding"
                                            autoComplete="off"
                                            style={{ height: '36px', minHeight: '36px', borderRadius: '8px', fontSize: '0.8rem' }}
                                        />
                                    </div>
                                    <TestDataPicker
                                        projectId={currentProject?.id}
                                        mode="ref"
                                        variant="sidebar"
                                        compact
                                        insertLabel="Add"
                                        editLabel="Edit"
                                        onInsert={(value: string) => setTestDataRefs(prev => prev ? `${prev}, ${value}` : value)}
                                    />
                                </div>
                            )}
                        </div>

                        {runFormError && (
                            <Alert variant="destructive" style={{ marginBottom: '0.85rem' }}>
                                <AlertTriangle size={16} />
                                <AlertDescription>{runFormError}</AlertDescription>
                            </Alert>
                        )}

                        <div className="agents-run-summary" aria-label="Run plan preview">
                            {runPlanRows.slice(0, 5).map(([label, value]) => (
                                <span key={label} className="agents-run-chip" title={`${label}: ${value || '-'}`}>
                                    {label}: {value || '-'}
                                </span>
                            ))}
                            {queueWarnings.degraded && <span className="agents-run-chip" style={{ color: 'var(--warning)' }}>Queue needs attention</span>}
                        </div>

                        <div className="agents-disclosure">
                            <button
                                type="button"
                                className="agents-disclosure-trigger"
                                aria-expanded={runPlanDetailsOpen}
                                aria-controls="agents-run-plan-details"
                                onClick={() => setRunPlanDetailsOpen(open => !open)}
                            >
                                <span>Run Plan Details</span>
                                <ChevronDown size={15} aria-hidden="true" />
                            </button>
                            {runPlanDetailsOpen && (
                                <div id="agents-run-plan-details" className="agents-disclosure-body">
                                    <div className="agents-run-plan">
                                        {runPlanRows.map(([label, value]) => (
                                            <div key={label} className="agents-run-plan-row">
                                                <strong>{label}</strong>
                                                <span>{value || '-'}</span>
                                            </div>
                                        ))}
                                    </div>
                                </div>
                            )}
                        </div>
                            </div>

                        <div className="agents-run-footer">
                        <button
                            className="agents-start-button"
                            onClick={() => {
                                const submittedTargetUrl = (document.getElementById('agents-target-url') as HTMLInputElement | null)?.value || '';
                                void handleRun(submittedTargetUrl);
                            }}
                            disabled={isStarting}
                        >
                            {isStarting ? <><Loader2 className="spin" size={16} /> Starting...</> : <><Play size={16} /> Start Agent</>}
                        </button>
                        </div>
                        </div>
                        </CollapsibleContent>
                    </div>
                    </div>
                </Collapsible>

                {/* Right Column: Output */}
                <div className="card agents-panel agents-output-panel" style={{ padding: '0', display: 'flex', flexDirection: 'column', minHeight: '640px', overflow: 'hidden' }}>
                    <div style={{ padding: '0.75rem 1rem', borderBottom: '1px solid var(--border)', background: 'var(--surface-hover)', display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '0.75rem', minHeight: '4.25rem' }}>
                        <h3
                            title={activeRun ? agentRunResultTitle(activeRun) : 'Agent Output'}
                            style={{
                                flex: 1,
                                minWidth: 0,
                                margin: 0,
                                fontWeight: 600,
                                fontSize: '0.9rem',
                                lineHeight: 1.25,
                                display: '-webkit-box',
                                WebkitLineClamp: 2,
                                WebkitBoxOrient: 'vertical',
                                overflow: 'hidden',
                                overflowWrap: 'anywhere'
                            }}
                        >
                            {activeRun ? `Result: ${agentRunResultTitle(activeRun)}` : 'Agent Output'}
                        </h3>
                        {activeRun && (
                            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: '0.5rem', flexShrink: 0, flexWrap: 'wrap', maxWidth: '58%' }}>
                                {LIVE_AGENT_STATUSES.has(activeRun.status) && activeRun.status !== 'paused' && (
                                    <button
                                        onClick={() => controlAgentRun('pause')}
                                        disabled={runControlPending !== null}
                                        title="Pause agent"
                                        aria-label="Pause agent run"
                                        style={{ border: '1px solid var(--border)', background: 'var(--background)', color: 'var(--text)', borderRadius: '6px', padding: '0.35rem 0.55rem', cursor: runControlPending ? 'not-allowed' : 'pointer', display: 'flex', alignItems: 'center', gap: '0.35rem', fontSize: '0.78rem', fontWeight: 600, opacity: runControlPending ? 0.65 : 1 }}
                                    >
                                        {runControlPending === 'pause' ? <Loader2 className="spin" size={14} /> : <Pause size={14} />} Pause
                                    </button>
                                )}
                                {activeRun.status === 'paused' && (
                                    <button
                                        onClick={() => controlAgentRun('resume')}
                                        disabled={runControlPending !== null}
                                        title="Resume agent"
                                        aria-label="Resume agent run"
                                        style={{ border: '1px solid var(--primary)', background: 'var(--primary)', color: 'white', borderRadius: '6px', padding: '0.35rem 0.55rem', cursor: runControlPending ? 'not-allowed' : 'pointer', display: 'flex', alignItems: 'center', gap: '0.35rem', fontSize: '0.78rem', fontWeight: 600, opacity: runControlPending ? 0.65 : 1 }}
                                    >
                                        {runControlPending === 'resume' ? <Loader2 className="spin" size={14} /> : <Play size={14} />} Resume
                                    </button>
                                )}
                                {LIVE_AGENT_STATUSES.has(activeRun.status) && (
                                    <button
                                        onClick={() => setCancelRunDialogOpen(true)}
                                        disabled={runControlPending !== null}
                                        title="Cancel agent"
                                        aria-label="Cancel agent run"
                                        style={{ border: '1px solid var(--danger)', background: 'var(--danger-muted)', color: 'var(--danger)', borderRadius: '6px', padding: '0.35rem 0.55rem', cursor: runControlPending ? 'not-allowed' : 'pointer', display: 'flex', alignItems: 'center', gap: '0.35rem', fontSize: '0.78rem', fontWeight: 600, opacity: runControlPending ? 0.65 : 1 }}
                                    >
                                        {runControlPending === 'cancel' ? <Loader2 className="spin" size={14} /> : <X size={14} />} Cancel
                                    </button>
                                )}
                                {isAgentRunTerminal(activeRun.status) && activeRun.status !== 'completed' && (
                                    <button
                                        onClick={retryAgentRun}
                                        disabled={runControlPending !== null}
                                        title="Retry agent run"
                                        aria-label="Retry agent run"
                                        data-testid="agents-retry-run"
                                        style={{ border: '1px solid var(--primary)', background: 'var(--primary)', color: 'white', borderRadius: '6px', padding: '0.35rem 0.55rem', cursor: runControlPending ? 'not-allowed' : 'pointer', display: 'flex', alignItems: 'center', gap: '0.35rem', fontSize: '0.78rem', fontWeight: 600, opacity: runControlPending ? 0.65 : 1 }}
                                    >
                                        {runControlPending === 'retry' ? <Loader2 className="spin" size={14} /> : <RotateCcw size={14} />} Retry
                                    </button>
                                )}
                                <button
                                    type="button"
                                    onClick={exportAgentTrace}
                                    title="Export redacted trace"
                                    aria-label="Export redacted trace"
                                    style={{ border: '1px solid var(--border)', background: 'var(--background)', color: 'var(--text)', borderRadius: '6px', padding: '0.35rem 0.55rem', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '0.35rem', fontSize: '0.78rem', fontWeight: 600 }}
                                >
                                    <Download size={14} /> Export
                                </button>
                                <StatusBadge status={activeRun.status} />
                            </div>
                        )}
                    </div>

                    <div style={{ padding: '1.5rem', flex: 1, overflowY: 'auto', background: 'var(--surface)' }}>
                        {!activeRun ? (
                            <div style={{ minHeight: '420px', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', color: 'var(--text-secondary)', textAlign: 'center', gap: '1rem' }}>
                                <Bot size={56} style={{ color: 'var(--primary)' }} />
                                <div>
                                    <h3 style={{ margin: 0, color: 'var(--text)', fontSize: '1.05rem', fontWeight: 800 }}>Start an agent run</h3>
                                    <p style={{ margin: '0.45rem auto 0', maxWidth: 460, lineHeight: 1.5 }}>Choose a saved custom agent to start a run, or open history to inspect previous results.</p>
                                </div>
                                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.6rem', justifyContent: 'center' }}>
                                    <Button type="button" variant="outline" onClick={() => selectWorkspaceView('history')}>
                                        <RotateCcw size={14} /> Open History
                                    </Button>
                                    <Button type="button" variant="outline" onClick={openCreateAgentBuilder}>
                                        <Plus size={14} /> Create Agent
                                    </Button>
                                    <Button type="button" variant="outline" onClick={() => openAssistantWithPrompt('Help me choose or draft an agent prompt for this project.')}>
                                        <MessageSquare size={14} /> Ask Assistant
                                    </Button>
                                    <Button type="button" variant="outline" asChild>
                                        <Link href={returnToAfterSave || '/workflow'}>
                                            <ArrowRight size={14} /> {returnToAfterSave ? 'Return to Workflow' : 'Workflow'}
                                        </Link>
                                    </Button>
                                </div>
                            </div>
                        ) : LIVE_AGENT_STATUSES.has(activeRun.status) && activeRun.agent_type === 'exploratory' ? (
                            <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                                {activeRun.status === 'paused' && (
                                    <div style={{ padding: '0.9rem 1rem', background: 'rgba(245, 158, 11, 0.12)', border: '1px solid rgba(245, 158, 11, 0.35)', borderRadius: '8px', color: 'var(--warning)', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                                        <Pause size={16} /> Agent is paused. Resume to continue from the current state.
                                    </div>
                                )}

                                <LiveBrowserView
                                    runId={activeRun.id}
                                    isActive={activeRun.status !== 'paused'}
                                    showHeader
                                    artifacts={activeRun.artifacts || []}
                                    latestImage={sortArtifactsByModifiedAt((activeRun.artifacts || []).filter(artifact => artifact.type === 'image'))[0]}
                                    statusMessage={activeRun.progress?.message}
                                    liveViewAvailable={Boolean(activeRun.progress?.live_view_available)}
                                    runtimeMessage={activeRun.progress?.runtime_message}
                                    vncUrl={activeRun.progress?.vnc_url}
                                />
                                <AgentRunCapturePanel activeRun={activeRun} mode="live" />
                                <AgentRunObservabilityPanel run={activeRun} events={agentEvents} trace={agentTrace} traceLoading={traceLoading} traceSearch={traceSearch} onTraceSearch={setTraceSearch} traceSpanType={traceSpanType} onTraceSpanType={setTraceSpanType} onExportTrace={exportAgentTrace} activeTraceTab={traceTab} onTraceTabChange={selectTraceTab} />
                                <p style={{ margin: 0, color: 'var(--text-secondary)', fontSize: '0.85rem', textAlign: 'center' }}>
                                    {activeRun.status === 'paused'
                                        ? 'Resume to continue from the current state.'
                                        : `Explorer agent is working. This may take up to ${timeLimitMinutes} minutes.`}
                                </p>
                            </div>
                        ) : LIVE_AGENT_STATUSES.has(activeRun.status) && activeRun.agent_type === 'spec_generation' ? (
                            <SpecGenerationRunPanel run={activeRun} events={agentEvents} />
                        ) : LIVE_AGENT_STATUSES.has(activeRun.status) && activeRun.agent_type === 'custom' ? (
                            (() => {
                                const progress = activeRun.progress || {};
                                const selectedTools = activeRun.config?.selected_tools || [];
                                const hasBrowserTools = Boolean(progress.has_browser_tools) || selectedTools.some((tool: AgentTool) => tool.tool_name?.startsWith('mcp__playwright'));
                                const latestImage = sortArtifactsByModifiedAt((activeRun.artifacts || []).filter(artifact => artifact.type === 'image'))[0];
                                const recentTools = progress.recent_tools || [];
                                const executionStarted = customAgentExecutionStarted(activeRun);
                                const waitingForWorker = (!executionStarted || progress.phase === 'queued') && activeRun.status !== 'paused';
                                const workerMessage = customAgentWorkerMessage(activeRun);
                                const toolCalls = Number(progress.tool_calls ?? 0);
                                const browserActions = Number(progress.browser_tool_calls ?? progress.interactions ?? 0);
                                return (
                                    <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                                        <div style={{
                                            display: 'grid',
                                            gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))',
                                            gap: '0.75rem',
                                            padding: '1rem',
                                            background: 'var(--surface-hover)',
                                            border: '1px solid var(--border)',
                                            borderRadius: '10px'
                                        }}>
                                            <div>
                                                <div style={{ fontSize: '0.72rem', color: 'var(--text-secondary)', textTransform: 'uppercase', marginBottom: '0.25rem' }}>Status</div>
                                                <div style={{ fontWeight: 700, textTransform: 'capitalize' }}>{activeRun.status}</div>
                                            </div>
                                            <div>
                                                <div style={{ fontSize: '0.72rem', color: 'var(--text-secondary)', textTransform: 'uppercase', marginBottom: '0.25rem' }}>Current Tool</div>
                                                <div style={{ fontWeight: 600, overflowWrap: 'anywhere' }}>{customAgentCurrentActivity(progress)}</div>
                                            </div>
	                                            <div>
	                                                <div style={{ fontSize: '0.72rem', color: 'var(--text-secondary)', textTransform: 'uppercase', marginBottom: '0.25rem' }}>Tool Calls</div>
	                                                <div style={{ fontWeight: 700 }}>{Number.isFinite(toolCalls) ? toolCalls : 0}</div>
	                                            </div>
	                                            <div>
	                                                <div style={{ fontSize: '0.72rem', color: 'var(--text-secondary)', textTransform: 'uppercase', marginBottom: '0.25rem' }}>Browser Actions</div>
	                                                <div style={{ fontWeight: 700 }}>{Number.isFinite(browserActions) ? browserActions : 0}</div>
	                                            </div>
                                        </div>

                                        {selectedTools.length > 0 && (
                                            <div style={{ border: '1px solid var(--border)', borderRadius: '10px', overflow: 'hidden', background: 'var(--background)' }}>
                                                <div style={{ padding: '0.75rem 1rem', borderBottom: '1px solid var(--border)', fontWeight: 600, display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '0.75rem' }}>
                                                    <span>Granted Tools</span>
                                                    <span style={{ color: 'var(--text-secondary)', fontSize: '0.78rem' }}>{selectedTools.length}</span>
                                                </div>
                                                <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap', padding: '0.75rem 1rem' }}>
                                                    {selectedTools.map((tool: AgentTool) => (
                                                        <span key={tool.id || tool.tool_name} title={tool.tool_name} style={{ display: 'inline-flex', alignItems: 'center', gap: '0.35rem', padding: '0.32rem 0.5rem', border: '1px solid var(--border)', borderRadius: '6px', background: 'var(--surface-hover)', color: 'var(--text-secondary)', fontSize: '0.78rem', fontWeight: 600 }}>
                                                            <Wrench size={12} /> {tool.label || formatToolName(tool.tool_name)}
                                                        </span>
                                                    ))}
                                                </div>
                                            </div>
                                        )}

                                        <AgentRunObservabilityPanel run={activeRun} events={agentEvents} trace={agentTrace} traceLoading={traceLoading} traceSearch={traceSearch} onTraceSearch={setTraceSearch} traceSpanType={traceSpanType} onTraceSpanType={setTraceSpanType} onExportTrace={exportAgentTrace} activeTraceTab={traceTab} onTraceTabChange={selectTraceTab} />

                                        {activeRun.status === 'paused' && (
                                            <div style={{ padding: '0.9rem 1rem', background: 'rgba(245, 158, 11, 0.12)', border: '1px solid rgba(245, 158, 11, 0.35)', borderRadius: '8px', color: 'var(--warning)', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                                                <Pause size={16} /> Agent is paused. Resume to continue from the current browser and CLI state.
                                            </div>
                                        )}

                                        {waitingForWorker ? (
                                            <div style={{
                                                padding: '1rem',
                                                background: activeRun.temporal?.error ? 'rgba(239, 68, 68, 0.12)' : 'var(--surface-hover)',
                                                border: `1px solid ${activeRun.temporal?.error ? 'rgba(239, 68, 68, 0.35)' : 'var(--border)'}`,
                                                borderRadius: '10px',
                                                color: activeRun.temporal?.error ? 'var(--danger)' : 'var(--text-secondary)',
                                                display: 'flex',
                                                alignItems: 'center',
                                                gap: '0.65rem',
                                                lineHeight: 1.45
                                            }}>
                                                {activeRun.temporal?.error ? <AlertTriangle size={18} /> : <Loader2 className="spin" size={18} />}
                                                <span>{workerMessage}</span>
                                            </div>
                                        ) : hasBrowserTools ? (
                                            <LiveBrowserView
                                                runId={activeRun.id}
                                                isActive={activeRun.status !== 'paused'}
                                                showHeader
                                                artifacts={activeRun.artifacts || []}
                                                latestImage={latestImage}
                                                statusMessage={progress.message}
                                                liveViewAvailable={Boolean(progress.live_view_available)}
                                                runtimeMessage={progress.runtime_message}
                                                vncUrl={progress.vnc_url}
                                            />
                                        ) : (
                                            <div style={{ padding: '1.25rem', background: 'var(--surface-hover)', border: '1px solid var(--border)', borderRadius: '10px', color: 'var(--text-secondary)', textAlign: 'center' }}>
                                                This custom agent does not have browser tools selected. Follow its tool activity below.
                                            </div>
                                        )}

                                        <div style={{ border: '1px solid var(--border)', borderRadius: '10px', overflow: 'hidden', background: 'var(--background)' }}>
                                            <div style={{ padding: '0.75rem 1rem', borderBottom: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', gap: '1rem' }}>
                                                <h4 style={{ margin: 0, fontSize: '0.95rem', fontWeight: 600 }}>Latest Screenshot</h4>
                                                {latestImage?.modified_at && (
                                                    <span style={{ fontSize: '0.78rem', color: 'var(--text-secondary)' }}>
                                                        {new Date(latestImage.modified_at).toLocaleTimeString()}
                                                    </span>
                                                )}
                                            </div>
                                            {latestImage ? (
                                                <a href={getArtifactUrl(latestImage)} target="_blank" rel="noreferrer" style={{ display: 'block' }}>
                                                    <img
                                                        src={getArtifactUrl(latestImage)}
                                                        alt="Latest custom agent screenshot"
                                                        style={{ width: '100%', display: 'block', aspectRatio: '16 / 9', maxHeight: '420px', objectFit: 'contain', background: '#000' }}
                                                    />
                                                </a>
                                            ) : (
                                                <div style={{ padding: '1.5rem', textAlign: 'center', color: 'var(--text-secondary)', fontSize: '0.9rem' }}>
                                                    No screenshots have been captured yet. Select the Screenshot tool for visual fallback.
                                                </div>
                                            )}
                                        </div>

                                        <div style={{ border: '1px solid var(--border)', borderRadius: '10px', overflow: 'hidden' }}>
                                            <div style={{ padding: '0.75rem 1rem', borderBottom: '1px solid var(--border)', fontWeight: 600 }}>
                                                Live Activity
                                            </div>
                                            {recentTools.length > 0 ? (
                                                <div style={{ display: 'grid' }}>
                                                    {recentTools.slice().reverse().map((tool: any, i: number) => (
                                                        <div key={`${tool.name}-${tool.at}-${i}`} style={{ padding: '0.65rem 1rem', borderBottom: i === recentTools.length - 1 ? 'none' : '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', gap: '1rem', fontSize: '0.85rem' }}>
                                                            <span style={{ fontWeight: 600 }}>{tool.label || formatToolName(tool.name)}</span>
                                                            {tool.at && <span style={{ color: 'var(--text-secondary)' }}>{new Date(tool.at).toLocaleTimeString()}</span>}
                                                        </div>
                                                    ))}
                                                </div>
                                            ) : (
                                                <div style={{ padding: '1rem', color: 'var(--text-secondary)', fontSize: '0.9rem' }}>
                                                    {progress.message || 'Waiting for the agent to use its first tool.'}
                                                </div>
                                            )}
                                        </div>

                                        <p style={{ margin: 0, color: 'var(--text-secondary)', fontSize: '0.85rem', textAlign: 'center' }}>
                                            {progress.message || `This may take up to ${Math.ceil((activeRun.config?.timeout_seconds || 1800) / 60)} minutes.`}
                                        </p>
                                    </div>
                                );
                            })()
                        ) : LIVE_AGENT_STATUSES.has(activeRun.status) ? (
                            <div style={{ height: '100%', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', color: 'var(--text-secondary)' }}>
                                {activeRun.status === 'paused' ? <Pause size={48} style={{ marginBottom: '1rem', color: 'var(--warning)' }} /> : <Loader2 size={48} className="spin" style={{ marginBottom: '1rem', color: 'var(--primary)' }} />}
                                <p>{activeRun.status === 'paused' ? 'Agent is paused.' : 'Agent is working...'}</p>
                                <p style={{ fontSize: '0.9rem', marginTop: '0.5rem' }}>
                                    {activeRun.status === 'paused'
                                        ? 'Resume to continue from the current state.'
                                        : `This may take up to ${activeRun.agent_type === 'custom' ? Math.ceil((activeRun.config?.timeout_seconds || 1800) / 60) : timeLimitMinutes} minutes.`}
                                </p>
                            </div>
                        ) : activeRun.status === 'failed' && activeRun.agent_type === 'spec_generation' ? (
                            <SpecGenerationRunPanel run={activeRun} events={agentEvents} />
                        ) : activeRun.status === 'failed' ? (
                            <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                                <div style={{ padding: '1rem', background: 'var(--danger-muted)', color: 'var(--danger)', borderRadius: '8px', border: '1px solid rgba(248, 113, 113, 0.2)' }}>
                                    <h4 style={{ fontWeight: 600, display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                                        <AlertTriangle size={18} /> Run Failed
                                    </h4>
                                    <p style={{ marginTop: '0.5rem', fontFamily: 'monospace' }}>
                                        {activeRun.result?.error || activeRun.health?.terminal_reason || "Unknown error occurred"}
                                    </p>
                                </div>
                                {activeRun.agent_type === 'exploratory' && activeRun.result && (
                                    <div data-testid="explorer-failed-recovery" style={{ display: 'grid', gap: '1rem' }}>
                                        <div
                                            data-testid="explorer-contract-warnings"
                                            style={{ padding: '1rem', background: explorerEvidenceEventCount > 0 ? 'var(--warning-muted)' : 'var(--danger-muted)', borderRadius: '10px', border: `1px solid ${explorerEvidenceEventCount > 0 ? 'rgba(251, 191, 36, 0.28)' : 'rgba(248, 113, 113, 0.22)'}`, display: 'grid', gap: '0.45rem' }}
                                        >
                                            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontWeight: 750, color: explorerEvidenceEventCount > 0 ? 'var(--warning)' : 'var(--danger)' }}>
                                                <AlertTriangle size={16} /> {explorerEvidenceEventCount > 0 ? 'Explorer recovered partial evidence' : 'Explorer recovered no structured evidence'}
                                            </div>
                                            {[activeRun.result.summary, activeRun.result.failure_reason, ...explorerContractWarnings].filter(Boolean).map((warning: any, index: number) => (
                                                <div key={`${warning}-${index}`} data-testid="explorer-contract-warning" style={{ color: 'var(--text-secondary)', fontSize: '0.86rem', lineHeight: 1.45 }}>
                                                    {String(warning)}
                                                </div>
                                            ))}
                                        </div>

                                        <div data-testid="explorer-quality-metrics" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))', gap: '0.75rem' }}>
                                            {[
                                                ['Evidence Events', explorerEvidenceEventCount, 'explorer-metric-evidence-events'],
                                                ['Screenshots', explorerScreenshotCount, 'explorer-metric-screenshots'],
                                                ['Artifacts', explorerArtifactCount, 'explorer-metric-artifacts'],
                                                ['Successful Browser Actions', explorerDiagnostics.successful_browser_tool_calls ?? 0, 'explorer-metric-successful-browser-actions'],
                                                ['Deduped Flows', explorerStructuredFlowCount, 'explorer-metric-deduped-flows'],
                                                ['Duplicate Flows Removed', explorerDiagnostics.dedupe_stats?.duplicate_flows_removed ?? 0, 'explorer-metric-duplicates-removed'],
                                            ].map(([label, value, testId]) => (
                                                <div key={String(testId)} data-testid={String(testId)} style={{ padding: '0.85rem', background: 'var(--background)', borderRadius: '8px', border: '1px solid var(--border)' }}>
                                                    <div style={{ fontSize: '1.35rem', fontWeight: 800, color: 'var(--text)' }}>{String(value)}</div>
                                                    <div style={{ fontSize: '0.78rem', color: 'var(--text-secondary)', marginTop: '0.2rem' }}>{String(label)}</div>
                                                </div>
                                            ))}
                                        </div>

                                        {renderExplorerCapturedEvidence()}
                                        {renderExplorerUnsupportedFlowCandidates()}

                                        {explorerFlowSummaries.length > 0 ? (
                                            <div style={{ display: 'grid', gap: '0.75rem' }}>
                                                {explorerFlowSummaries.map((flow: any, i: number) => (
                                                    <div key={flow.id || i} data-testid="explorer-flow-card" style={{ padding: '1rem', background: 'var(--surface)', borderRadius: '8px', border: '1px solid var(--border)' }}>
                                                        <h5 style={{ margin: '0 0 0.45rem', fontWeight: 650 }}>{flow.title || `Recovered flow ${i + 1}`}</h5>
                                                        <div style={{ color: 'var(--text-secondary)', fontSize: '0.82rem', overflowWrap: 'anywhere' }}>
                                                            {(flow.steps_count || 0)} steps{flow.entry_point ? ` · Starts: ${flow.entry_point}` : ''}{flow.exit_point ? ` · Ends: ${flow.exit_point}` : ''}
                                                        </div>
                                                    </div>
                                                ))}
                                            </div>
                                        ) : (
                                            <div data-testid="explorer-no-structured-flows" style={{ padding: '1rem', background: 'var(--surface-hover)', borderRadius: '8px', border: '1px solid var(--border)', color: 'var(--text-secondary)' }}>
                                                No evidence-backed flow summaries were recovered, so test spec generation is disabled for this run.
                                            </div>
                                        )}
                                    </div>
                                )}
                                <AgentRunObservabilityPanel run={activeRun} events={agentEvents} trace={agentTrace} traceLoading={traceLoading} traceSearch={traceSearch} onTraceSearch={setTraceSearch} traceSpanType={traceSpanType} onTraceSpanType={setTraceSpanType} onExportTrace={exportAgentTrace} activeTraceTab={traceTab} onTraceTabChange={selectTraceTab} />
                            </div>
                        ) : (
                            // Completed successfully
                            <div className="markdown-content">
                                {activeRun.agent_type !== 'spec_generation' && (
                                    <AgentRunObservabilityPanel run={activeRun} events={agentEvents} trace={agentTrace} traceLoading={traceLoading} traceSearch={traceSearch} onTraceSearch={setTraceSearch} traceSpanType={traceSpanType} onTraceSpanType={setTraceSpanType} onExportTrace={exportAgentTrace} activeTraceTab={traceTab} onTraceTabChange={selectTraceTab} />
                                )}
                                {activeRun.agent_type === 'spec_generation' ? (
                                    <SpecGenerationRunPanel run={activeRun} events={agentEvents} />
                                ) : activeRun.agent_type === 'writer' ? (
                                    <>
                                        <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: '1rem' }}>
                                            <button
                                                onClick={() => downloadSpec(activeRun.result.spec_content || '', 'spec.md')}
                                                style={{ fontSize: '0.85rem', padding: '0.4rem 0.8rem', background: 'var(--primary)', color: 'white', border: 'none', borderRadius: '4px', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '0.5rem' }}
                                            >
                                                <Download size={14} /> Download Spec
                                            </button>
                                        </div>
                                        <div style={{ background: '#1e1e1e', padding: '1.5rem', borderRadius: '8px', border: '1px solid var(--border)' }}>
                                            <pre style={{ whiteSpace: 'pre-wrap', fontFamily: 'monospace', fontSize: '0.9rem', color: '#e5e5e5' }}>
                                                {activeRun.result.spec_content || JSON.stringify(activeRun.result, null, 2)}
                                            </pre>
                                        </div>
                                    </>
                                ) : activeRun.agent_type === 'custom' ? (
                                    <CustomAgentReportView
                                        run={activeRun}
                                        activeTab={customResultTab}
                                        onTabChange={selectCustomResultTab}
                                        onAskAssistant={openAssistantWithPrompt}
                                        onCreateSpecFromReport={openSpecFromReportItem}
                                        onEditOverview={openReportOverviewEdit}
                                        onEditReportItem={openReportItemEdit}
                                        onImportRequirements={importReportRequirements}
                                        importingRequirementIds={importingRequirementIds}
                                        importError={reportImportError}
                                        reportStatusFilter={reportStatusFilter}
                                        onReportStatusFilterChange={updateReportStatusFilter}
                                        reportSeverityFilter={reportSeverityFilter}
                                        onReportSeverityFilterChange={updateReportSeverityFilter}
                                    />
                                ) : (
                                    // Exploratory Result - User Friendly Display
                                    <div style={{ display: 'flex', flexDirection: 'column', gap: '2rem' }}>
                                        {!activeRun.result ? (
                                            <div style={{ padding: '2rem', background: 'var(--primary-glow)', borderRadius: '12px', color: 'var(--primary)', textAlign: 'center' }}>
                                                <Loader2 size={32} className="spin" style={{ marginBottom: '1rem' }} />
                                                <p style={{ fontSize: '1rem', fontWeight: 500 }}>Loading exploration results...</p>
                                                <p style={{ fontSize: '0.9rem', color: 'var(--text-secondary)', marginTop: '0.5rem' }}>
                                                    This may take a moment while we compile the findings.
                                                </p>
                                            </div>
                                        ) : (
                                            <>
                                                <AgentRunCapturePanel activeRun={activeRun} mode="recording" />

                                                {/* Main Summary Card */}
                                                <div style={{ padding: '1.5rem', background: 'linear-gradient(135deg, var(--primary-glow) 0%, rgba(192, 132, 252, 0.1) 100%)', borderRadius: '12px', border: '1px solid rgba(59, 130, 246, 0.2)' }}>
                                                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '1rem' }}>
                                                        <div style={{ width: '40px', height: '40px', borderRadius: '10px', background: 'var(--primary)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                                                            <Sparkles size={20} style={{ color: 'white' }} />
                                                        </div>
                                                        <div>
                                                            <h3 style={{ fontWeight: 700, fontSize: '1.2rem', margin: 0 }}>Exploration Complete!</h3>
                                                            <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', margin: '0.5rem 0 0 0' }}>
                                                                {activeRun.result.elapsed_time_minutes ? `Completed in ${activeRun.result.elapsed_time_minutes.toFixed(1)} minutes` : 'Completed'}
                                                            </p>
                                                        </div>
                                                    </div>
                                                    <p style={{ fontSize: '1rem', lineHeight: '1.6', margin: 0 }}>
                                                        {activeRun.result.summary || 'The agent explored the application and discovered user flows.'}
                                                    </p>
                                                </div>

                                                {activeRun.status === 'completed_partial' && (
                                                    <div
                                                        data-testid="explorer-partial-warning"
                                                        style={{ padding: '1rem', background: 'var(--warning-muted)', borderRadius: '10px', border: '1px solid rgba(251, 191, 36, 0.28)', color: 'var(--text-secondary)', display: 'flex', gap: '0.6rem', alignItems: 'flex-start' }}
                                                    >
                                                        <AlertTriangle size={16} style={{ color: 'var(--warning)', marginTop: '0.1rem' }} />
                                                        <div>
                                                            <strong style={{ color: 'var(--warning)' }}>Partial Explorer result</strong>
                                                            <div style={{ fontSize: '0.86rem', lineHeight: 1.45, marginTop: '0.25rem' }}>
                                                                The run explored the app, but no completed evidence-backed flows were recovered. Review captured evidence and unsupported candidates before retrying or generating specs.
                                                            </div>
                                                        </div>
                                                    </div>
                                                )}

                                                {explorerContractWarnings.length > 0 && (
                                                    <div
                                                        data-testid="explorer-contract-warnings"
                                                        style={{ padding: '1rem', background: 'var(--warning-muted)', borderRadius: '10px', border: '1px solid rgba(251, 191, 36, 0.28)', display: 'grid', gap: '0.45rem' }}
                                                    >
                                                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontWeight: 750, color: 'var(--warning)' }}>
                                                            <AlertTriangle size={16} /> Explorer evidence warning
                                                        </div>
                                                        {explorerContractWarnings.map((warning: string, index: number) => (
                                                            <div key={`${warning}-${index}`} data-testid="explorer-contract-warning" style={{ color: 'var(--text-secondary)', fontSize: '0.86rem', lineHeight: 1.45 }}>
                                                                {warning}
                                                            </div>
                                                        ))}
                                                    </div>
                                                )}

                                                {/* Key Metrics */}
                                                {activeRun.result.coverage && (
                                                    <div>
                                                        <h4 style={{ fontWeight: 600, fontSize: '1rem', marginBottom: '1rem', color: 'var(--text)' }}>
                                                            📊 What Was Explored
                                                        </h4>
                                                        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: '1rem' }}>
                                                            <div data-testid="explorer-metric-pages" style={{ padding: '1rem', background: 'var(--surface-hover)', borderRadius: '10px', border: '1px solid var(--border)' }}>
                                                                <div style={{ fontSize: '2rem', fontWeight: 700, color: 'var(--primary)' }}>
                                                                    {activeRun.result.coverage.pages_visited || 0}
                                                                </div>
                                                                <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginTop: '0.25rem' }}>
                                                                    Pages Visited
                                                                </div>
                                                            </div>
                                                            <div data-testid="explorer-metric-flows" style={{ padding: '1rem', background: 'var(--surface-hover)', borderRadius: '10px', border: '1px solid var(--border)' }}>
                                                                <div style={{ fontSize: '2rem', fontWeight: 700, color: 'var(--success)' }}>
                                                                    {activeRun.result.coverage.flows_discovered || 0}
                                                                </div>
                                                                <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginTop: '0.25rem' }}>
                                                                    User Flows Found
                                                                </div>
                                                            </div>
                                                            <div data-testid="explorer-metric-forms" style={{ padding: '1rem', background: 'var(--surface-hover)', borderRadius: '10px', border: '1px solid var(--border)' }}>
                                                                <div style={{ fontSize: '2rem', fontWeight: 700, color: 'var(--warning)' }}>
                                                                    {activeRun.result.coverage.forms_interacted || 0}
                                                                </div>
                                                                <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginTop: '0.25rem' }}>
                                                                    Forms Tested
                                                                </div>
                                                            </div>
                                                            {activeRun.result.coverage.errors_found !== undefined && (
                                                                <div data-testid="explorer-metric-issues" style={{ padding: '1rem', background: 'var(--surface-hover)', borderRadius: '10px', border: '1px solid var(--border)' }}>
                                                                    <div style={{ fontSize: '2rem', fontWeight: 700, color: activeRun.result.coverage.errors_found > 0 ? 'var(--danger)' : 'var(--success)' }}>
                                                                        {activeRun.result.coverage.errors_found || 0}
                                                                    </div>
                                                                    <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginTop: '0.25rem' }}>
                                                                        Issues Found
                                                                    </div>
                                                                </div>
                                                            )}
                                                        </div>
                                                        <div data-testid="explorer-quality-metrics" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))', gap: '0.75rem', marginTop: '0.85rem' }}>
                                                            {[
                                                                ['Evidence Events', explorerEvidenceEventCount, 'explorer-metric-evidence-events'],
                                                                ['Screenshots', explorerScreenshotCount, 'explorer-metric-screenshots'],
                                                                ['Artifacts', explorerArtifactCount, 'explorer-metric-artifacts'],
                                                                ['Unsupported Candidates', explorerUnsupportedFlowCandidates.length, 'explorer-metric-unsupported-candidates'],
                                                                ['Successful Browser Actions', explorerDiagnostics.successful_browser_tool_calls ?? 0, 'explorer-metric-successful-browser-actions'],
                                                                ['Deduped Flows', explorerStructuredFlowCount, 'explorer-metric-deduped-flows'],
                                                                ['Duplicate Flows Removed', explorerDiagnostics.dedupe_stats?.duplicate_flows_removed ?? 0, 'explorer-metric-duplicates-removed'],
                                                            ].map(([label, value, testId]) => (
                                                                <div key={String(testId)} data-testid={String(testId)} style={{ padding: '0.85rem', background: 'var(--background)', borderRadius: '8px', border: '1px solid var(--border)' }}>
                                                                    <div style={{ fontSize: '1.35rem', fontWeight: 800, color: 'var(--text)' }}>{String(value)}</div>
                                                                    <div style={{ fontSize: '0.78rem', color: 'var(--text-secondary)', marginTop: '0.2rem' }}>{String(label)}</div>
                                                                </div>
                                                            ))}
                                                        </div>
                                                        {activeRun.result.coverage.coverage_score !== undefined && (
                                                            <div style={{ marginTop: '1rem', padding: '0.75rem', background: activeRun.result.coverage.coverage_score > 0.7 ? 'var(--success-muted)' : 'var(--warning-muted)', borderRadius: '8px', border: `1px solid ${activeRun.result.coverage.coverage_score > 0.7 ? 'rgba(52, 211, 153, 0.2)' : 'rgba(251, 191, 36, 0.2)'}` }}>
                                                                <span style={{ fontSize: '0.85rem', fontWeight: 500 }}>
                                                                    Coverage Score: <strong>{(activeRun.result.coverage.coverage_score * 100).toFixed(0)}%</strong>
                                                                    {activeRun.result.coverage.coverage_score > 0.7 ? ' ✅ Good coverage' : ' ⚠️ Consider exploring more'}
                                                                </span>
                                                            </div>
                                                        )}
                                                    </div>
                                                )}

                                                {renderExplorerCapturedEvidence()}

                                                {/* Discovered Flows - Clear Display */}
                                                {explorerFlowSummaries.length > 0 ? (
                                                    <div>
                                                        <h4 style={{ fontWeight: 600, fontSize: '1rem', marginBottom: '1rem', color: 'var(--text)' }}>
                                                            🔍 Discovered User Flows ({activeRun.result.total_flows_discovered || explorerFlowSummaries.length})
                                                        </h4>
                                                        <p style={{ fontSize: '0.9rem', color: 'var(--text-secondary)', marginBottom: '1rem' }}>
                                                            These are the complete user journeys the agent found. Each one can be turned into a test.
                                                        </p>
                                                        <div style={{ display: 'grid', gap: '1rem' }}>
                                                            {explorerFlowSummaries.map((flow: any, i: number) => (
                                                                <div key={flow.id || i} data-testid="explorer-flow-card" style={{
                                                                    padding: '1rem',
                                                                    background: 'var(--surface)',
                                                                    borderRadius: '10px',
                                                                    border: '1px solid var(--border)',
                                                                    transition: 'background 0.2s var(--ease-smooth), border-color 0.2s var(--ease-smooth)'
                                                                }}>
                                                                    <div style={{ display: 'flex', alignItems: 'flex-start', gap: '0.75rem' }}>
                                                                        <div style={{
                                                                            width: '32px',
                                                                            height: '32px',
                                                                            borderRadius: '8px',
                                                                            background: 'var(--primary-glow)',
                                                                            display: 'flex',
                                                                            alignItems: 'center',
                                                                            justifyContent: 'center',
                                                                            flexShrink: 0,
                                                                            fontSize: '1.2rem'
                                                                        }}>
                                                                            {i + 1}
                                                                        </div>
                                                                        <div style={{ flex: 1 }}>
                                                                            <h5 style={{ fontWeight: 600, fontSize: '1rem', margin: '0 0 0.5rem 0' }}>
                                                                                {flow.title}
                                                                            </h5>
                                                                            <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '0.5rem' }}>
                                                                                <span style={{ fontWeight: 500 }}>{flow.steps_count} steps</span>
                                                                                {flow.entry_point && <span> • Starts: {flow.entry_point}</span>}
                                                                                {flow.exit_point && <span> • Ends: {flow.exit_point}</span>}
                                                                            </div>
                                                                            {flow.pages && flow.pages.length > 0 && (
                                                                                <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '0.5rem' }}>
                                                                                    <span style={{ fontWeight: 500 }}>Pages:</span> {flow.pages.join(' → ')}
                                                                                </div>
                                                                            )}
                                                                            {flow.has_edge_cases && (
                                                                                <div style={{ marginTop: '0.5rem', padding: '0.5rem', background: 'var(--warning-muted)', borderRadius: '6px' }}>
                                                                                    <div style={{ fontSize: '0.75rem', fontWeight: 500, color: 'var(--warning)' }}>
                                                                                        ⚠️ Includes edge cases
                                                                                    </div>
                                                                                </div>
                                                                            )}
                                                                        </div>
                                                                        <button
                                                                            onClick={() => fetchFlowDetails(flow.id)}
                                                                            disabled={loadingFlowDetails}
                                                                            style={{
                                                                                padding: '0.5rem 1rem',
                                                                                background: 'var(--primary)',
                                                                                color: 'white',
                                                                                border: 'none',
                                                                                borderRadius: '6px',
                                                                                fontSize: '0.85rem',
                                                                                fontWeight: 500,
                                                                                cursor: loadingFlowDetails ? 'not-allowed' : 'pointer',
                                                                                opacity: loadingFlowDetails ? 0.6 : 1,
                                                                                whiteSpace: 'nowrap'
                                                                            }}
                                                                        >
                                                                            {loadingFlowDetails ? 'Loading...' : 'View Details'}
                                                                        </button>
                                                                    </div>
                                                                </div>
                                                            ))}
                                                        </div>
                                                    </div>
                                                ) : (
                                                    <div style={{ padding: '2rem', background: 'var(--warning-muted)', borderRadius: '12px', textAlign: 'center' }}>
                                                        <h4 style={{ margin: '0 0 0.5rem 0' }}>No flows discovered</h4>
                                                        <p style={{ fontSize: '0.9rem', color: 'var(--text-secondary)', margin: 0 }}>
                                                            The agent did not recover any complete evidence-backed flows. Try increasing the time limit or exploring a different area.
                                                        </p>
                                                    </div>
                                                )}

                                                {renderExplorerUnsupportedFlowCandidates()}

                                            {/* Next Steps */}
                                            {explorerCanGenerateSpecs && (
                                            <div style={{ marginTop: '1.5rem', padding: '1.25rem', background: 'linear-gradient(135deg, var(--success-muted) 0%, var(--primary-glow) 100%)', borderRadius: '12px', border: '1px solid rgba(52, 211, 153, 0.2)' }}>
                                                <h4 style={{ fontWeight: 600, fontSize: '1rem', marginBottom: '0.75rem', display: 'flex', alignItems: 'center', gap: '0.5rem', color: 'var(--text)' }}>
                                                    <ArrowRight size={18} style={{ color: 'var(--success)' }} /> Next Steps
                                                </h4>
                                                <div style={{ fontSize: '0.9rem', lineHeight: '1.6' }}>
                                                    <p style={{ margin: '0 0 0.5rem 0', color: 'var(--text)' }}>
                                                        <strong>1. Review the discovered flows above</strong> - Make sure they capture the user journeys you want to test
                                                    </p>
                                                    <p style={{ margin: '0 0 0.5rem 0', color: 'var(--text)' }}>
                                                        <strong>2. Click "Generate Test Specs" below</strong> - This creates detailed test specifications for each flow
                                                    </p>
                                                    <p style={{ margin: '0 0 0.75rem 0', color: 'var(--text)' }}>
                                                        <strong>3. Download and run the specs</strong> - Use them with the existing pipeline to generate Playwright tests
                                                    </p>
                                                    <div style={{ padding: '0.75rem', background: 'var(--primary-glow)', borderRadius: '8px', fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
                                                        <Info size={14} style={{ marginRight: '0.5rem', display: 'inline', verticalAlign: 'middle' }} />
                                                        <span style={{ fontStyle: 'italic' }}>Tip: Each discovered flow becomes a separate test spec. You can edit them before running if needed.</span>
                                                    </div>
                                                </div>
                                            </div>
                                            )}

                                            {/* Spec Synthesis Button */}
                                            {activeRun.agent_type === 'exploratory' && explorerCanGenerateSpecs && (
                                            <div style={{ display: 'flex', gap: '0.5rem' }}>
                                                <button
                                                    onClick={handleSynthesize}
                                                    disabled={isSynthesizing || !explorerCanGenerateSpecs}
                                                    data-testid="explorer-generate-test-specs"
                                                    style={{
                                                        flex: 1, padding: '0.75rem', borderRadius: '6px', fontSize: '0.9rem',
                                                        background: 'var(--primary)', color: 'white', fontWeight: 600, border: 'none',
                                                        cursor: isSynthesizing || !explorerCanGenerateSpecs ? 'not-allowed' : 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '0.5rem',
                                                        opacity: isSynthesizing || !explorerCanGenerateSpecs ? 0.7 : 1
                                                    }}
                                                >
                                                    {isSynthesizing ? <><Loader2 className="spin" size={16} /> Generating...</> : <><Sparkles size={16} /> Generate Test Specs</>}
                                                </button>
                                            </div>
                                        )}

                                        {/* Generated Specs */}
                                        {specResult && specResult.specs && (
                                            <div>
                                                <h4 style={{ fontWeight: 600, marginBottom: '0.5rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                                                    <FileText size={18} /> Generated Specs ({specResult.total_specs || 0})
                                                </h4>
                                                <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: '1rem' }}>{specResult.summary}</p>

                                                {/* Happy Path Specs */}
                                                {specResult.specs.happy_path && Object.keys(specResult.specs.happy_path).length > 0 && (
                                                    <div style={{ marginBottom: '1rem' }}>
                                                        <h5 style={{ fontSize: '0.85rem', color: 'var(--success)', marginBottom: '0.5rem' }}>Happy Path Specs</h5>
                                                        {Object.entries(specResult.specs.happy_path).map(([filename, content]) => (
                                                            <div key={filename} style={{ marginBottom: '0.5rem' }}>
                                                                <button
                                                                    onClick={() => downloadSpec(content, filename)}
                                                                    style={{
                                                                        fontSize: '0.8rem', padding: '0.3rem 0.6rem', background: 'var(--surface-hover)',
                                                                        border: '1px solid var(--border)', borderRadius: '4px', cursor: 'pointer',
                                                                        display: 'flex', alignItems: 'center', gap: '0.5rem', width: '100%'
                                                                    }}
                                                                >
                                                                    <Download size={12} /> {filename}
                                                                </button>
                                                            </div>
                                                        ))}
                                                    </div>
                                                )}

                                                {/* Edge Case Specs */}
                                                {specResult.specs.edge_cases && Object.keys(specResult.specs.edge_cases).length > 0 && (
                                                    <div>
                                                        <h5 style={{ fontSize: '0.85rem', color: 'var(--warning)', marginBottom: '0.5rem' }}>Edge Case Specs</h5>
                                                        {Object.entries(specResult.specs.edge_cases).map(([filename, content]) => (
                                                            <div key={filename} style={{ marginBottom: '0.5rem' }}>
                                                                <button
                                                                    onClick={() => downloadSpec(content, filename)}
                                                                    style={{
                                                                        fontSize: '0.8rem', padding: '0.3rem 0.6rem', background: 'var(--surface-hover)',
                                                                        border: '1px solid var(--border)', borderRadius: '4px', cursor: 'pointer',
                                                                        display: 'flex', alignItems: 'center', gap: '0.5rem', width: '100%'
                                                                    }}
                                                                >
                                                                    <Download size={12} /> {filename}
                                                                </button>
                                                            </div>
                                                        ))}
                                                    </div>
                                                )}
                                            </div>
                                        )}

                                        {/* Action Trace */}
                                        {activeRun.result.action_trace && activeRun.result.action_trace.length > 0 && (
                                            <details style={{ marginTop: '1.5rem' }}>
                                                <summary style={{ cursor: 'pointer', fontWeight: 600, fontSize: '0.9rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                                                    <Terminal size={16} /> What the Agent Did ({activeRun.result.action_trace.length} actions)
                                                </summary>
                                                <div style={{ marginTop: '0.5rem', background: '#0f0f0f', padding: '1rem', borderRadius: '8px', fontSize: '0.85rem', fontFamily: 'monospace', maxHeight: '250px', overflowY: 'auto' }}>
                                                    {activeRun.result.action_trace.map((action: any, i: number) => (
                                                        <div key={i} style={{ marginBottom: '0.25rem', color: '#a3a3a3', lineHeight: '1.4' }}>
                                                            <span style={{ color: 'var(--primary)', fontWeight: 500 }}>[{action.step}]</span> {action.action} {action.target} - {action.outcome}
                                                            {action.is_new_discovery && <span style={{ color: 'var(--success)', marginLeft: '0.5rem' }}>✨ New Discovery</span>}
                                                        </div>
                                                    ))}
                                                </div>
                                                <p style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginTop: '0.5rem', fontStyle: 'italic' }}>
                                                    This shows every action the agent took during exploration. "New Discovery" means the agent found something new.
                                                </p>
                                            </details>
                                        )}
                                        </>
                                    )}
                                    </div>
                                )}
                            </div>
                        )}
                    </div>
                </div>
            </div>
            )}

            {workspaceView === 'history' && renderHistoryWorkspace()}

                <Dialog open={builderOpen} onOpenChange={(open) => { if (open) setBuilderOpen(true); else closeCustomAgentBuilder(); }}>
                    <DialogContent className="agents-builder-dialog max-w-[960px]" style={{ width: 'min(960px, calc(100vw - 2rem))', maxHeight: '86vh', overflowY: 'auto' }}>
                        <DialogHeader>
                            <DialogTitle>{definitionForm.id ? 'Edit Custom Agent' : 'Create Custom Agent'}</DialogTitle>
                            <DialogDescription>
                                Configure the system prompt, runtime, default test data, and allowed tools.
                            </DialogDescription>
                        </DialogHeader>

                        {definitionFormError && (
                            <Alert variant="destructive">
                                <AlertTriangle size={16} />
                                <AlertDescription>{definitionFormError}</AlertDescription>
                            </Alert>
                        )}

                        <div className="agents-builder-grid">
                            <div className="agents-builder-form">
                                <div className="agents-builder-field">
                                    <Label htmlFor="definition-name">Name</Label>
                                    <Input id="definition-name" name="definitionName" value={definitionForm.name} onChange={e => setDefinitionForm({ ...definitionForm, name: e.target.value })} placeholder="API explorer" autoComplete="off" />
                                </div>
                                <div className="agents-builder-field">
                                    <Label htmlFor="definition-description">Description</Label>
                                    <Input id="definition-description" name="definitionDescription" value={definitionForm.description} onChange={e => setDefinitionForm({ ...definitionForm, description: e.target.value })} placeholder="Explores pages and reports API calls" autoComplete="off" />
                                </div>
                                <div className="agents-builder-field">
                                    <Label htmlFor="definition-system-prompt">System Prompt</Label>
                                    <textarea
                                        id="definition-system-prompt"
                                        name="definitionSystemPrompt"
                                        value={definitionForm.system_prompt}
                                        onChange={e => setDefinitionForm({ ...definitionForm, system_prompt: e.target.value })}
                                        rows={7}
                                        className="agents-builder-textarea"
                                    />
                                </div>
                                <div className="agents-builder-split">
                                    <div className="agents-builder-field">
                                        <Label htmlFor="definition-runtime">Runtime</Label>
                                        <div style={{ position: 'relative' }}>
                                            <button
                                                id="definition-runtime"
                                                type="button"
                                                aria-label="Runtime"
                                                aria-haspopup="listbox"
                                                aria-expanded={definitionRuntimeOpen}
                                                onClick={() => setDefinitionRuntimeOpen(open => !open)}
                                                className="agents-report-edit-select-trigger"
                                                style={{
                                                    width: '100%',
                                                    justifyContent: 'space-between',
                                                    display: 'inline-flex',
                                                    alignItems: 'center',
                                                }}
                                            >
                                                Claude SDK
                                                <ChevronDown size={14} />
                                            </button>
                                            {definitionRuntimeOpen && (
                                                <div
                                                    role="listbox"
                                                    aria-label="Options"
                                                    className="agents-runtime-select-content"
                                                    style={{
                                                        position: 'absolute',
                                                        zIndex: 60,
                                                        top: 'calc(100% + 0.35rem)',
                                                        left: 0,
                                                        right: 0,
                                                        padding: '0.25rem',
                                                    }}
                                                >
                                                    <button
                                                        type="button"
                                                        role="option"
                                                        aria-selected={definitionForm.runtime === 'claude_sdk'}
                                                        onClick={() => {
                                                            setDefinitionForm({ ...definitionForm, runtime: 'claude_sdk' });
                                                            setDefinitionRuntimeOpen(false);
                                                        }}
                                                        style={{
                                                            width: '100%',
                                                            border: 0,
                                                            background: 'transparent',
                                                            color: 'var(--text)',
                                                            padding: '0.45rem 0.55rem',
                                                            textAlign: 'left',
                                                            borderRadius: '6px',
                                                            cursor: 'pointer',
                                                        }}
                                                    >
                                                        Claude SDK
                                                    </button>
                                                </div>
                                            )}
                                        </div>
                                    </div>
                                    <div className="agents-builder-field">
                                        <Label htmlFor="definition-timeout">Timeout seconds</Label>
                                        <Input id="definition-timeout" name="definitionTimeoutSeconds" type="number" min={60} max={7200} value={definitionForm.timeout_seconds} onChange={e => setDefinitionForm({ ...definitionForm, timeout_seconds: parseInt(e.target.value) || 1800 })} />
                                    </div>
                                </div>
                                <div className="agents-builder-field">
                                    <Label htmlFor="definition-test-data-refs">Default Test Data Refs</Label>
                                    <Input id="definition-test-data-refs" name="definitionTestDataRefs" value={definitionForm.test_data_refs} onChange={e => setDefinitionForm({ ...definitionForm, test_data_refs: e.target.value })} placeholder="login-users.valid-admin" autoComplete="off" />
                                    <TestDataPicker
                                        projectId={currentProject?.id}
                                        mode="ref"
                                        compact
                                        onInsert={(value: string) => setDefinitionForm(prev => ({
                                            ...prev,
                                            test_data_refs: prev.test_data_refs ? `${prev.test_data_refs}, ${value}` : value,
                                        }))}
                                    />
                                </div>
                            </div>

                            <div className="agents-builder-tools">
                                <div className="agents-builder-tools-header">
                                    <Label>Tools</Label>
                                    <span className="agents-builder-selected-count">{definitionForm.tool_ids.length} of {toolCatalog.length} selected</span>
                                </div>
                                <div className="agents-builder-tools-list">
                                    {Object.entries(toolsByCategory).map(([category, tools]) => (
                                        <fieldset key={category} style={{ border: 0, margin: 0, padding: 0, display: 'grid', gap: '0.5rem' }}>
                                            <div className="agents-tool-category-header">
                                                <legend className="agents-tool-category-title">
                                                    {category} ({tools.length})
                                                </legend>
                                                <Button type="button" variant="ghost" size="sm" onClick={() => toggleCategoryTools(tools)}>
                                                    {tools.every(tool => definitionForm.tool_ids.includes(tool.id)) ? 'Clear' : 'Select all'}
                                                </Button>
                                            </div>
                                            {tools.map(tool => (
                                                <label key={tool.id} className="agents-tool-row">
                                                    <input
                                                        type="checkbox"
                                                        checked={definitionForm.tool_ids.includes(tool.id)}
                                                        onChange={() => toggleDefinitionTool(tool.id)}
                                                    />
                                                    <span style={{ minWidth: 0 }}>
                                                        <span className="agents-tool-title-line">
                                                            <span className="agents-tool-label">{tool.label}</span>
                                                            <span className="agents-tool-risk-pill" style={TOOL_RISK_PILL_STYLES[tool.risk]}>{tool.risk}</span>
                                                        </span>
                                                        <span className="agents-tool-description">{tool.description}</span>
                                                    </span>
                                                </label>
                                            ))}
                                        </fieldset>
                                    ))}
                                </div>
                            </div>
                        </div>

                        <DialogFooter className="agents-builder-footer">
                            <Button type="button" variant="outline" onClick={closeCustomAgentBuilder}>Cancel</Button>
                            <Button type="button" onClick={saveDefinition} disabled={savingDefinition}>
                                {savingDefinition ? <Loader2 className="spin" size={14} /> : <Save size={14} />} Save Agent
                            </Button>
                        </DialogFooter>
                    </DialogContent>
                </Dialog>

                <Dialog open={Boolean(reportEditTarget)} onOpenChange={(open) => { if (!open) closeReportEditDialog(); }}>
                    <DialogContent
                        className="agents-report-edit-dialog"
                        style={{
                            width: 'min(760px, calc(100vw - 2rem))',
                            maxWidth: '760px',
                            maxHeight: '88vh',
                            overflow: 'hidden',
                            display: 'flex',
                            flexDirection: 'column',
                            padding: 0,
                            gap: 0,
                        }}
                    >
                        <DialogHeader className="agents-report-edit-header">
                            <span className="agents-report-edit-kicker">{reportEditKicker()}</span>
                            <DialogTitle className="agents-report-edit-title">{reportEditDialogTitle(reportEditTarget)}</DialogTitle>
                            <DialogDescription className="agents-report-edit-description">
                                Update the stored report content for this custom agent run.
                            </DialogDescription>
                        </DialogHeader>

                        <div className="agents-report-edit-body">
                            {reportEditError && (
                                <Alert variant="destructive">
                                    <AlertDescription>{reportEditError}</AlertDescription>
                                </Alert>
                            )}

                            <div className="agents-report-edit-form">
                                {reportEditTarget?.type === 'overview' && (
                                    <>
                                        {renderReportTextareaField('Summary', 'summary', 4, 'lg')}
                                        {renderReportTextareaField('Scope', 'scope', 3)}
                                    </>
                                )}

                                {reportEditTarget?.type !== 'overview' && (
                                    <>
                                        <div className="agents-report-edit-grid agents-report-edit-grid--title">
                                            {renderReportTextField('Title', 'title')}
                                            {reportEditTarget?.type === 'finding'
                                                ? renderReportSelectField('Severity', 'severity', REPORT_SEVERITY_OPTIONS)
                                                : renderReportSelectField('Priority', 'priority', REPORT_PRIORITY_OPTIONS)}
                                        </div>
                                        {renderReportTextField('Page', 'page')}
                                    </>
                                )}

                                {reportEditTarget?.type === 'finding' && (
                                    <>
                                        {renderReportTextareaField('Description', 'description', 4, 'lg')}
                                        {renderReportTextareaField('Evidence', 'evidence', 3)}
                                        {renderReportTextField('Suggested Action', 'suggested_action')}
                                    </>
                                )}

                                {reportEditTarget?.type === 'test_idea' && (
                                    <>
                                        {renderReportTextareaField('Steps', 'steps', 5, 'lg')}
                                        {renderReportTextareaField('Expected', 'expected', 3)}
                                        {renderReportTextField('Source Finding ID', 'source_finding_id')}
                                    </>
                                )}

                                {reportEditTarget?.type === 'requirement' && (
                                    <>
                                        <div className="agents-report-edit-grid">
                                            {renderReportTextField('Category', 'category')}
                                            {renderReportTextField('Confidence', 'confidence')}
                                        </div>
                                        {renderReportTextareaField('Description', 'description', 4, 'lg')}
                                        {renderReportTextareaField('Acceptance Criteria', 'acceptance_criteria', 4, 'lg')}
                                        {renderReportTextareaField('Evidence', 'evidence', 3)}
                                    </>
                                )}
                            </div>
                        </div>

                        <DialogFooter className="agents-report-edit-footer">
                            <Button type="button" variant="outline" onClick={closeReportEditDialog} disabled={savingReportEdit}>Cancel</Button>
                            <Button type="button" onClick={saveReportEdit} disabled={savingReportEdit}>
                                {savingReportEdit ? <Loader2 className="spin" size={14} /> : <Save size={14} />} Save Changes
                            </Button>
                        </DialogFooter>
                    </DialogContent>
                </Dialog>

                <Dialog open={Boolean(archiveCandidate)} onOpenChange={(open) => !open && setArchiveCandidate(null)}>
                    <DialogContent>
                        <DialogHeader>
                            <DialogTitle>Archive Custom Agent</DialogTitle>
                            <DialogDescription>
                                Existing run history will remain. The agent will no longer appear as runnable.
                            </DialogDescription>
                        </DialogHeader>
                        <p style={{ margin: 0, color: 'var(--text)' }}>
                            Archive "{archiveCandidate?.name}"?
                        </p>
                        <DialogFooter style={{ gap: '0.6rem' }}>
                            <Button type="button" variant="outline" onClick={() => setArchiveCandidate(null)}>Cancel</Button>
                            <Button
                                type="button"
                                variant="destructive"
                                onClick={async () => {
                                    if (!archiveCandidate) return;
                                    await archiveDefinition(archiveCandidate);
                                    setArchiveCandidate(null);
                                }}
                            >
                                <Archive size={14} /> Archive
                            </Button>
                        </DialogFooter>
                    </DialogContent>
                </Dialog>

                <ConfirmDialog
                    open={cancelRunDialogOpen}
                    onOpenChange={setCancelRunDialogOpen}
                    title="Cancel Agent Run"
                    description={activeRun ? `Cancel ${agentRunResultTitle(activeRun)}? The run will stop and current evidence will remain available in history.` : 'Cancel this agent run?'}
                    confirmLabel="Cancel Run"
                    variant="danger"
                    loading={runControlPending === 'cancel'}
                    onConfirm={() => controlAgentRun('cancel')}
                />

                {/* Flow Details Modal */}
                <Dialog open={flowModalVisible} onOpenChange={(open) => { if (open) setFlowModalOpen(true); else closeFlowModal(); }}>
                    {activeFlow ? (
                        <DialogContent style={{ width: 'min(980px, calc(100vw - 2rem))', maxWidth: '980px', maxHeight: '84vh', overflowY: 'auto' }}>
                            <DialogHeader>
                                <DialogTitle>{activeFlow.title}</DialogTitle>
                                <DialogDescription>Review the discovered flow and generate a test spec.</DialogDescription>
                            </DialogHeader>

                            {activeFlow.pages && activeFlow.pages.length > 0 && (
                                <div style={{ marginBottom: '1rem' }}>
                                    <h4 style={{ fontSize: '0.9rem', fontWeight: 600, marginBottom: '0.5rem' }}>Pages</h4>
                                    <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
                                        {activeFlow.pages.map((page: string, i: number) => (
                                            <span key={i} style={{
                                                padding: '0.25rem 0.5rem',
                                                background: 'var(--surface-hover)',
                                                borderRadius: '4px',
                                                fontSize: '0.8rem'
                                            }}>
                                                {page}
                                            </span>
                                        ))}
                                    </div>
                                </div>
                            )}

                            {activeFlow.happy_path && (
                                <div style={{ marginBottom: '1rem' }}>
                                    <h4 style={{ fontSize: '0.9rem', fontWeight: 600, marginBottom: '0.5rem', color: 'var(--success)' }}>Happy Path</h4>
                                    <p style={{ fontSize: '0.9rem', lineHeight: '1.5', margin: 0 }}>
                                        {activeFlow.happy_path}
                                    </p>
                                </div>
                            )}

                            {activeFlow.edge_cases && activeFlow.edge_cases.length > 0 && (
                                <div style={{ marginBottom: '1rem' }}>
                                    <h4 style={{ fontSize: '0.9rem', fontWeight: 600, marginBottom: '0.5rem', color: 'var(--warning)' }}>Edge Cases</h4>
                                    <ul style={{ margin: 0, paddingLeft: '1.5rem' }}>
                                        {activeFlow.edge_cases.map((ec: string, i: number) => (
                                            <li key={i} style={{ fontSize: '0.9rem', marginBottom: '0.25rem' }}>{ec}</li>
                                        ))}
                                    </ul>
                                </div>
                            )}

                            {activeFlow.test_ideas && activeFlow.test_ideas.length > 0 && (
                                <div style={{ marginBottom: '1rem' }}>
                                    <h4 style={{ fontSize: '0.9rem', fontWeight: 600, marginBottom: '0.5rem' }}>Test Ideas</h4>
                                    <ul style={{ margin: 0, paddingLeft: '1.5rem' }}>
                                        {activeFlow.test_ideas.map((idea: string, i: number) => (
                                            <li key={i} style={{ fontSize: '0.9rem', marginBottom: '0.25rem' }}>{idea}</li>
                                        ))}
                                    </ul>
                                </div>
                            )}

                            {activeFlow.entry_point && (
                                <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '1rem' }}>
                                    Entry: {activeFlow.entry_point}
                                    {activeFlow.exit_point && ` -> Exit: ${activeFlow.exit_point}`}
                                </div>
                            )}

                            {activeFlow.source_type === 'custom_report' && (
                                <div style={{ marginBottom: '1rem', padding: '0.85rem', border: '1px solid var(--border)', borderRadius: '8px', background: 'var(--surface-hover)', display: 'grid', gap: '0.65rem' }}>
                                    <label style={{ display: 'grid', gap: '0.35rem', fontSize: '0.82rem', fontWeight: 700 }}>
                                        Browser login for spec generation
                                        <select
                                            value={reportSpecAuthMode === 'session' ? `session:${reportSpecAuthSessionId}` : reportSpecAuthMode}
                                            onChange={(event) => {
                                                const value = event.target.value;
                                                if (value.startsWith('session:')) {
                                                    setReportSpecAuthMode('session');
                                                    setReportSpecAuthSessionId(value.slice('session:'.length));
                                                } else {
                                                    setReportSpecAuthMode(value as ReportSpecBrowserAuthMode);
                                                    setReportSpecAuthSessionId('');
                                                }
                                            }}
                                            disabled={generatingSpec}
                                            style={{ minHeight: 38, borderRadius: '6px', border: '1px solid var(--border)', background: 'var(--background)', color: 'var(--text)', padding: '0.45rem 0.6rem', fontSize: '0.85rem' }}
                                        >
                                            <option value="project_default" disabled={!projectDefaultBrowserAuthSession}>
                                                {projectDefaultBrowserAuthSession ? `Project default: ${projectDefaultBrowserAuthSession.name || projectDefaultBrowserAuthSession.id}` : 'Project default unavailable'}
                                            </option>
                                            <option value="none">No auth</option>
                                            {activeBrowserAuthSessions.map(item => (
                                                <option key={item.id} value={`session:${item.id}`}>
                                                    {browserAuthSessionLabel(item)}
                                                </option>
                                            ))}
                                        </select>
                                    </label>
                                    {inheritedBrowserAuthUnavailable && (
                                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.45rem', color: 'var(--warning)', fontSize: '0.8rem', fontWeight: 600 }}>
                                            <AlertTriangle size={15} /> Original browser login session is no longer active.
                                        </div>
                                    )}
                                </div>
                            )}

                            {(generatingSpec || flowSpecAgentRun) && flowSpecAgentRunId && (
                                <div style={{ display: 'grid', gap: '1rem', margin: '1rem 0', padding: '1rem 0', borderTop: '1px solid var(--border)' }}>
                                    {flowSpecShowBrowser && (
                                        <LiveBrowserView
                                            runId={flowSpecAgentRunId}
                                            isActive={generatingSpec && flowSpecAgentRun?.status !== 'failed'}
                                            showHeader
                                            artifacts={flowSpecAgentRun?.artifacts || []}
                                            latestImage={flowSpecLatestImage}
                                            statusMessage={flowSpecAgentRun?.progress?.message || flowSpecPoller.status?.message}
                                            liveViewAvailable={Boolean(flowSpecAgentRun?.progress?.live_view_available ?? true)}
                                            runtimeMessage={flowSpecAgentRun?.progress?.runtime_message}
                                            vncUrl={flowSpecAgentRun?.progress?.vnc_url}
                                        />
                                    )}
                                    {flowSpecAgentRun?.status === 'completed' && !flowSpecShowBrowser && (
                                        <div style={{ padding: '0.85rem 1rem', background: 'var(--success-muted)', color: 'var(--success)', border: '1px solid rgba(52, 211, 153, 0.2)', borderRadius: '8px', display: 'flex', alignItems: 'center', gap: '0.5rem', fontWeight: 700 }}>
                                            <CheckCircle2 size={16} /> Spec generation completed.
                                        </div>
                                    )}
                                    {flowSpecAgentRun && (
                                        <AgentRunObservabilityPanel run={flowSpecAgentRun} events={flowSpecAgentEvents} />
                                    )}
                                </div>
                            )}

                            {(flowSpecError || flowSpecAgentRun?.status === 'failed') && (
                                <div style={{ margin: '1rem 0', padding: '1rem', background: 'var(--danger-muted)', color: 'var(--danger)', border: '1px solid rgba(248, 113, 113, 0.2)', borderRadius: '8px' }}>
                                    <h4 style={{ margin: 0, fontWeight: 700, display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                                        <AlertTriangle size={18} /> Spec Generation Failed
                                    </h4>
                                    <p style={{ margin: '0.5rem 0 0', fontFamily: 'monospace', overflowWrap: 'anywhere' }}>
                                        {flowSpecError || flowSpecAgentRun?.result?.error || flowSpecAgentRun?.progress?.message || 'Unknown error'}
                                    </p>
                                    {flowSpecBrowserAuthFailure && (
                                        <div style={{ marginTop: '0.75rem', fontWeight: 700 }}>
                                            Refresh or choose a browser login session.
                                        </div>
                                    )}
                                </div>
                            )}

                            <div style={{ display: 'flex', gap: '0.75rem', marginTop: '1rem', paddingTop: '1rem', borderTop: '1px solid var(--border)' }}>
                                <button
                                    type="button"
                                    onClick={() => {
                                        if (activeFlow.source_type === 'custom_report') {
                                            if (reportSpecReview && activeFlow.item_type) {
                                                createSpecFromReportItem(reportSpecReview.item, activeFlow.item_type);
                                            } else {
                                                const message = 'The selected report item is no longer available for spec generation.';
                                                setFlowSpecError(message);
                                                setWorkspaceStatus(message);
                                            }
                                        } else {
                                            generateFlowSpec(activeFlow.id);
                                        }
                                    }}
                                    disabled={generatingSpec}
                                    style={{
                                        flex: 1,
                                        padding: '0.75rem 1rem',
                                        background: 'var(--primary)',
                                        color: 'white',
                                        border: 'none',
                                        borderRadius: '8px',
                                        fontSize: '0.9rem',
                                        fontWeight: 500,
                                        cursor: generatingSpec ? 'not-allowed' : 'pointer',
                                        opacity: generatingSpec ? 0.6 : 1,
                                        display: 'flex',
                                        alignItems: 'center',
                                        justifyContent: 'center',
                                        gap: '0.5rem'
                                    }}
                                >
                                    {generatingSpec ? (
                                        <>
                                            <Loader2 size={16} className="spin" />
                                            {flowSpecPoller.status?.message || 'Generating...'}
                                        </>
                                    ) : activeFlow.generated_spec ? (
                                        <>
                                            <FileText size={16} />
                                            View Test Spec
                                        </>
                                    ) : (
                                        <>
                                            <FileText size={16} />
                                            Generate Test Spec
                                        </>
                                    )}
                                </button>
                                <button
                                    type="button"
                                    onClick={closeFlowModal}
                                    style={{
                                        padding: '0.75rem 1.5rem',
                                        background: 'transparent',
                                        color: 'var(--text-secondary)',
                                        border: '1px solid var(--border)',
                                        borderRadius: '8px',
                                        fontSize: '0.9rem',
                                        fontWeight: 500,
                                        cursor: 'pointer'
                                    }}
                                >
                                    Close
                                </button>
                            </div>
                        </DialogContent>
                    ) : agentActionIntent.type === 'reviewReportSpec' ? (
                        <DialogContent style={{ width: 'min(640px, calc(100vw - 2rem))', maxWidth: '640px' }}>
                            <DialogHeader>
                                <DialogTitle>Report Item Unavailable</DialogTitle>
                                <DialogDescription>
                                    {missingReportSpecItemMessage || 'Loading the selected report item for spec review.'}
                                </DialogDescription>
                            </DialogHeader>
                            <div style={{ padding: '0.9rem 1rem', border: '1px solid var(--border)', borderRadius: '8px', background: 'var(--surface-hover)', color: 'var(--text)' }}>
                                {missingReportSpecItemMessage || `Looking for ${agentActionIntent.itemType} ${agentActionIntent.itemId} in run ${agentActionIntent.runId}.`}
                            </div>
                            <DialogFooter>
                                <Button type="button" variant="outline" onClick={closeFlowModal}>Close</Button>
                            </DialogFooter>
                        </DialogContent>
                    ) : null}
                </Dialog>

                {/* Generated Spec Modal */}
                <Dialog open={specModalOpen && Boolean(generatedSpec)} onOpenChange={setSpecModalOpen}>
                    {generatedSpec && (
                        <DialogContent style={{
                            maxWidth: '800px',
                            maxHeight: '85vh',
                            width: 'min(800px, calc(100vw - 2rem))',
                            overflow: 'hidden',
                            display: 'flex',
                            flexDirection: 'column',
                            padding: 0
                        }}>
                            <DialogTitle className="sr-only">Generated test spec</DialogTitle>
                            <DialogDescription className="sr-only">Generated spec preview and export actions.</DialogDescription>
                            <div style={{
                                padding: '1.25rem 1.5rem',
                                borderBottom: '1px solid var(--border)',
                                display: 'flex',
                                alignItems: 'center',
                                justifyContent: 'space-between'
                            }}>
                                <div>
                                    <h3 style={{ margin: 0, fontSize: '1.2rem', fontWeight: 600 }}>
                                        {generatedSpec.flow_title}
                                    </h3>
                                    <div style={{ margin: '0.5rem 0 0 0', display: 'flex', gap: '0.5rem', alignItems: 'center', flexWrap: 'wrap' }}>
                                        {generatedSpec.cached && (
                                            <span style={{ background: 'var(--primary-glow)', color: 'var(--primary)', padding: '2px 8px', borderRadius: '4px', fontSize: '0.75rem' }}>Cached</span>
                                        )}
                                        {generatedSpec.pipeline === 'native_planner_generator' && (
                                            <span style={{ background: 'var(--success-muted)', color: 'var(--success)', padding: '2px 8px', borderRadius: '4px', fontSize: '0.75rem' }}>Intelligent Pipeline</span>
                                        )}
                                        {generatedSpec.validated && (
                                            <span style={{ background: 'var(--success-muted)', color: 'var(--success)', padding: '2px 8px', borderRadius: '4px', fontSize: '0.75rem' }}>✓ Validated</span>
                                        )}
                                        {generatedSpec.requires_auth && (
                                            <span style={{ background: 'var(--warning-muted)', color: 'var(--warning)', padding: '2px 8px', borderRadius: '4px', fontSize: '0.75rem' }}>Auth Required</span>
                                        )}
                                    </div>
                                    <p style={{ margin: '0.25rem 0 0 0', fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                                        {generatedSpec.cached
                                            ? 'Previously generated spec'
                                            : 'Generated with real browser exploration'}
                                    </p>
                                </div>
                                <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
                                    {generatedSpec.cached && (
                                        <button
                                            onClick={() => {
                                                if (activeFlow) {
                                                    generateFlowSpec(activeFlow.id, true);
                                                }
                                            }}
                                            disabled={generatingSpec}
                                            style={{
                                                padding: '0.5rem 0.75rem',
                                                background: 'transparent',
                                                color: 'var(--text)',
                                                border: '1px solid var(--border)',
                                                borderRadius: '6px',
                                                fontSize: '0.8rem',
                                                fontWeight: 500,
                                                cursor: generatingSpec ? 'not-allowed' : 'pointer',
                                                display: 'flex',
                                                alignItems: 'center',
                                                gap: '0.4rem'
                                            }}
                                            title="Generate new version"
                                        >
                                            <RefreshCw size={14} />
                                            Regenerate
                                        </button>
                                    )}
                                    <button
                                        onClick={() => setSpecModalOpen(false)}
                                        type="button"
                                        aria-label="Close generated spec"
                                        style={{
                                            background: 'transparent',
                                            border: 'none',
                                            cursor: 'pointer',
                                            color: 'var(--text-secondary)'
                                        }}
                                    >
                                        <X size={20} />
                                    </button>
                                </div>
                            </div>

                            <div style={{
                                padding: '1.5rem',
                                overflowY: 'auto',
                                flex: 1,
                                background: 'var(--code-bg)',
                                borderRadius: '8px',
                                margin: '1rem',
                                fontSize: '0.85rem',
                                lineHeight: '1.6',
                                whiteSpace: 'pre-wrap',
                                wordBreak: 'break-word',
                                fontFamily: 'var(--font-mono)'
                            }}>
                                {generatedSpec.spec_content}
                            </div>

                            {/* Split Results Section */}
                            {splitResult && (
                                <div style={{
                                    margin: '0 1rem 1rem 1rem',
                                    padding: '1rem',
                                    background: 'var(--success-muted)',
                                    borderRadius: '8px',
                                    border: '1px solid rgba(52, 211, 153, 0.2)'
                                }}>
                                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.75rem' }}>
                                        <CheckCircle2 size={16} style={{ color: 'var(--success)' }} />
                                        <span style={{ fontWeight: 600, color: 'var(--success)' }}>
                                            Split into {splitResult.count} individual test specs
                                        </span>
                                    </div>
                                    <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '0.5rem' }}>
                                        Output: specs/{splitResult.output_dir}/
                                    </div>
                                    <div style={{ maxHeight: '150px', overflowY: 'auto' }}>
                                        {splitResult.files.map((file, i) => (
                                            <div key={i} style={{
                                                display: 'flex',
                                                alignItems: 'center',
                                                gap: '0.5rem',
                                                padding: '0.35rem 0',
                                                fontSize: '0.8rem',
                                                borderBottom: i < splitResult.files.length - 1 ? '1px solid var(--border)' : 'none'
                                            }}>
                                                <FileText size={14} style={{ color: 'var(--primary)', flexShrink: 0 }} />
                                                <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                                    {file.split('/').pop()}
                                                </span>
                                                <Link
                                                    href={`/specs?file=${encodeURIComponent(file)}`}
                                                    style={{
                                                        color: 'var(--primary)',
                                                        display: 'flex',
                                                        alignItems: 'center',
                                                        gap: '0.25rem',
                                                        fontSize: '0.75rem',
                                                        textDecoration: 'none'
                                                    }}
                                                >
                                                    <ExternalLink size={12} />
                                                    View
                                                </Link>
                                            </div>
                                        ))}
                                    </div>
                                </div>
                            )}

                            <div style={{
                                padding: '1rem 1.5rem',
                                borderTop: '1px solid var(--border)',
                                display: 'flex',
                                gap: '0.75rem',
                                justifyContent: 'space-between',
                                flexWrap: 'wrap'
                            }}>
                                {/* Left side - Split button */}
                                <button
                                    onClick={splitSpec}
                                    disabled={splittingSpec || !generatedSpec.spec_file}
                                    style={{
                                        padding: '0.6rem 1rem',
                                        background: splitResult ? 'var(--success-muted)' : 'rgba(192, 132, 252, 0.1)',
                                        color: splitResult ? 'var(--success)' : '#a855f7',
                                        border: `1px solid ${splitResult ? 'rgba(52, 211, 153, 0.3)' : 'rgba(192, 132, 252, 0.3)'}`,
                                        borderRadius: '6px',
                                        fontSize: '0.85rem',
                                        fontWeight: 500,
                                        cursor: splittingSpec ? 'not-allowed' : 'pointer',
                                        opacity: splittingSpec ? 0.6 : 1,
                                        display: 'flex',
                                        alignItems: 'center',
                                        gap: '0.5rem'
                                    }}
                                    title="Split this multi-test spec into individual test files for easier automation"
                                >
                                    {splittingSpec ? (
                                        <>
                                            <Loader2 size={16} className="spin" />
                                            Splitting...
                                        </>
                                    ) : splitResult ? (
                                        <>
                                            <CheckCircle2 size={16} />
                                            Split Complete
                                        </>
                                    ) : (
                                        <>
                                            <Scissors size={16} />
                                            Split into Individual Tests
                                        </>
                                    )}
                                </button>

                                {/* Right side - Copy and Download */}
                                <div style={{ display: 'flex', gap: '0.75rem' }}>
                                    <button
                                        onClick={() => {
                                            navigator.clipboard.writeText(generatedSpec.spec_content);
                                            setWorkspaceStatus('Spec copied to clipboard.');
                                            toast.success('Spec copied to clipboard');
                                        }}
                                        style={{
                                            padding: '0.6rem 1rem',
                                            background: 'transparent',
                                            color: 'var(--text)',
                                            border: '1px solid var(--border)',
                                            borderRadius: '6px',
                                            fontSize: '0.85rem',
                                            fontWeight: 500,
                                            cursor: 'pointer'
                                        }}
                                    >
                                        Copy
                                    </button>
                                    <button
                                        onClick={() => downloadSpec()}
                                        style={{
                                            padding: '0.6rem 1rem',
                                            background: 'var(--primary)',
                                            color: 'white',
                                            border: 'none',
                                            borderRadius: '6px',
                                            fontSize: '0.85rem',
                                            fontWeight: 500,
                                            cursor: 'pointer',
                                            display: 'flex',
                                            alignItems: 'center',
                                            gap: '0.5rem'
                                        }}
                                    >
                                        <Download size={16} />
                                        Download
                                    </button>
                                </div>
                            </div>
                        </DialogContent>
                    )}
                </Dialog>

            {workspaceView === 'library' && (
                <div className="card agents-library-panel">
                    <div className="agents-library-header">
                        <div>
                            <h2 style={{ margin: 0, fontSize: '1rem', fontWeight: 800 }}>Agent Library</h2>
                            <p style={{ margin: '0.25rem 0 0', color: 'var(--text-secondary)', fontSize: '0.85rem' }}>Create, edit, archive, and choose reusable custom agents.</p>
                        </div>
                        <Button type="button" className="agents-library-create-button" onClick={openCreateAgentBuilder}>
                            <Plus size={14} /> Create Agent
                        </Button>
                    </div>
                    {returnToAfterSave && selectedDefinition && (
                        <div style={{ padding: '0.85rem', border: '1px solid var(--primary)', borderRadius: '8px', background: 'var(--primary-glow)', display: 'flex', justifyContent: 'space-between', gap: '0.75rem', alignItems: 'center', flexWrap: 'wrap' }}>
                            <span style={{ fontSize: '0.85rem', fontWeight: 700 }}>Saved {selectedDefinition.name}. It is ready for workflow use.</span>
                            <Link href={returnToAfterSave} style={{ color: 'var(--primary)', fontWeight: 800, textDecoration: 'none' }}>
                                {returnToAfterSave.includes('workflow') ? 'Return to Workflow' : 'Use in Workflow'}
                            </Link>
                        </div>
                    )}
                    {agentDefinitions.length === 0 ? (
                        <div className="agents-library-empty">
                            No custom agents yet.
                        </div>
                    ) : (
                        <div className="agents-library-grid">
                            {agentDefinitions.map(definition => (
                                <div
                                    key={definition.id}
                                    className="agents-library-card"
                                    data-selected={selectedDefinitionId === definition.id}
                                >
                                    <div className="agents-library-card-header">
                                        <div>
                                            <h3 className="agents-library-card-title">{definition.name}</h3>
                                            <p className="agents-library-card-description">{definition.description || 'No description provided.'}</p>
                                        </div>
                                        <DropdownMenu
                                            modal={false}
                                            open={openDefinitionMenuId === definition.id}
                                            onOpenChange={(open) => setOpenDefinitionMenuId(open ? definition.id : null)}
                                        >
                                            <DropdownMenuTrigger asChild>
                                                <Button
                                                    type="button"
                                                    variant="ghost"
                                                    size="icon"
                                                    aria-label={`Open actions for ${definition.name}`}
                                                    className="agents-definition-action-trigger agents-library-menu-trigger"
                                                    onClick={(event) => event.stopPropagation()}
                                                    onPointerDown={(event) => event.stopPropagation()}
                                                >
                                                    <MoreHorizontal size={15} />
                                                </Button>
                                            </DropdownMenuTrigger>
                                            <DropdownMenuContent
                                                align="end"
                                                sideOffset={6}
                                                className="agents-definition-action-menu"
                                                onClick={(event) => event.stopPropagation()}
                                            >
                                                <DropdownMenuItem
                                                    className="agents-definition-action-item"
                                                    onSelect={(event) => {
                                                        editDefinitionFromMenu(definition, event);
                                                    }}
                                                >
                                                    <Settings size={14} />
                                                    Edit
                                                </DropdownMenuItem>
                                                <DropdownMenuItem
                                                    className="agents-definition-action-item agents-definition-action-item-danger"
                                                    onSelect={(event) => {
                                                        archiveDefinitionFromMenu(definition, event);
                                                    }}
                                                >
                                                    <Archive size={14} />
                                                    Archive
                                                </DropdownMenuItem>
                                            </DropdownMenuContent>
                                        </DropdownMenu>
                                    </div>
                                    <div className="agents-library-card-meta">
                                        <Badge variant="secondary">{definition.tool_ids.length} tools</Badge>
                                        <Badge variant="secondary">Claude SDK</Badge>
                                        <Badge variant="secondary">{Math.ceil((definition.timeout_seconds || 1800) / 60)}m</Badge>
                                    </div>
                                    <div>
                                        <Button
                                            type="button"
                                            size="sm"
                                            className="agents-library-run-button"
                                            onClick={() => { selectDefinition(definition.id); selectAgentMode('custom'); selectWorkspaceView('run'); }}
                                        >
                                            <Play size={13} /> Run Agent
                                        </Button>
                                    </div>
                                </div>
                            ))}
                        </div>
                    )}
                </div>
            )}

            {workspaceView === 'reports' && (
                <ReportsSearchWorkspace
                    query={reportSearchQuery}
                    onQueryChange={updateReportSearchQuery}
                    type={reportSearchType}
                    onTypeChange={updateReportSearchType}
                    severity={reportSearchSeverity}
                    onSeverityChange={updateReportSearchSeverity}
                    loading={reportSearchLoading}
                    results={reportSearchResults}
                    onRefresh={fetchReportSearch}
                />
            )}

            {workspaceView === 'queue' && (
                <QueueStatusPanel
                    queue={queueStatus}
                    loading={queueLoading}
                    error={queueError}
                    onRefresh={fetchQueueStatus}
                    onCleanStaleTasks={cleanStaleQueueTasks}
                    cleaningStaleTasks={queueCleanupLoading}
                />
            )}
        </PageLayout>
    );
}
