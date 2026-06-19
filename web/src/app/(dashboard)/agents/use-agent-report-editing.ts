import { useCallback, useState, type Dispatch, type SetStateAction } from 'react';
import {
    linesToText,
    normalizeReportPatchResponse,
    textToLines,
    type AgentRun,
    type ReportEditableItemType,
    type ReportEditTarget,
    type ReportFinding,
    type ReportRequirement,
    type ReportTestIdea,
    type StructuredAgentReport,
} from './agents-model';
import { useAgentReportActions } from './use-agent-report-actions';

interface UseAgentReportEditingOptions {
    activeRun: AgentRun | null;
    projectId?: string | null;
    setActiveRun: Dispatch<SetStateAction<AgentRun | null>>;
    setHistory: Dispatch<SetStateAction<AgentRun[]>>;
    setWorkspaceStatus: Dispatch<SetStateAction<string>>;
}

function reportEditPayload(target: ReportEditTarget | null, form: Record<string, string>) {
    if (!target) return {};
    if (target.type === 'overview') {
        return {
            summary: form.summary || '',
            scope: form.scope || '',
        };
    }
    if (target.type === 'finding') {
        return {
            title: form.title || '',
            severity: form.severity || '',
            page: form.page || '',
            description: form.description || '',
            evidence: form.evidence || '',
            suggested_action: form.suggested_action || '',
        };
    }
    if (target.type === 'test_idea') {
        return {
            title: form.title || '',
            priority: form.priority || '',
            page: form.page || '',
            steps: textToLines(form.steps),
            expected: form.expected || '',
            source_finding_id: form.source_finding_id || '',
        };
    }
    return {
        title: form.title || '',
        description: form.description || '',
        category: form.category || '',
        priority: form.priority || '',
        acceptance_criteria: textToLines(form.acceptance_criteria),
        page: form.page || '',
        evidence: form.evidence || '',
        confidence: form.confidence || '',
    };
}

export function useAgentReportEditing({
    activeRun,
    projectId,
    setActiveRun,
    setHistory,
    setWorkspaceStatus,
}: UseAgentReportEditingOptions) {
    const [importingRequirementIds, setImportingRequirementIds] = useState<string[]>([]);
    const [reportImportError, setReportImportError] = useState<string | null>(null);
    const [reportEditTarget, setReportEditTarget] = useState<ReportEditTarget | null>(null);
    const [reportEditForm, setReportEditForm] = useState<Record<string, string>>({});
    const [reportEditError, setReportEditError] = useState<string | null>(null);
    const [savingReportEdit, setSavingReportEdit] = useState(false);

    const {
        saveReportPatch,
        importRequirements,
    } = useAgentReportActions(projectId);

    const updateRunFromReportPatch = useCallback((updatedRun: AgentRun) => {
        setActiveRun(updatedRun);
        setHistory(prev => prev.map(run => run.id === updatedRun.id ? updatedRun : run));
    }, [setActiveRun, setHistory]);

    const openReportOverviewEdit = useCallback((report: StructuredAgentReport) => {
        if (!activeRun?.id) return;
        setReportEditTarget({ type: 'overview', runId: activeRun.id });
        setReportEditForm({
            summary: report.summary || '',
            scope: report.scope || '',
        });
        setReportEditError(null);
    }, [activeRun?.id]);

    const openReportItemEdit = useCallback((item: ReportFinding | ReportTestIdea | ReportRequirement, kind: ReportEditableItemType) => {
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
    }, [activeRun?.id]);

    const closeReportEditDialog = useCallback(() => {
        if (savingReportEdit) return;
        setReportEditTarget(null);
        setReportEditForm({});
        setReportEditError(null);
    }, [savingReportEdit]);

    const updateReportEditField = useCallback((field: string, value: string) => {
        setReportEditForm(prev => ({ ...prev, [field]: value }));
    }, []);

    const saveReportEdit = useCallback(async () => {
        if (!reportEditTarget || !activeRun?.id) return;
        setSavingReportEdit(true);
        setReportEditError(null);
        try {
            const data = await saveReportPatch(reportEditTarget, reportEditPayload(reportEditTarget, reportEditForm));
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
    }, [activeRun?.id, reportEditForm, reportEditTarget, saveReportPatch, setWorkspaceStatus, updateRunFromReportPatch]);

    const importReportRequirements = useCallback(async (itemIds?: string[]) => {
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
    }, [activeRun?.id, importRequirements, setActiveRun, setHistory]);

    return {
        importingRequirementIds,
        reportImportError,
        reportEditTarget,
        reportEditForm,
        reportEditError,
        savingReportEdit,
        openReportOverviewEdit,
        openReportItemEdit,
        closeReportEditDialog,
        updateReportEditField,
        saveReportEdit,
        importReportRequirements,
    };
}
