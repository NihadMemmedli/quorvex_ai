import { useCallback } from 'react';
import {
    generateReportItemSpec,
    importAgentReportRequirements,
    patchAgentReport,
} from './agents-api';
import type { ReportEditTarget } from './agents-model';
import type { ReportSpecItemType } from './agents-workspace-state';

export function useAgentReportActions(projectId?: string | null) {
    const saveReportPatch = useCallback((target: ReportEditTarget, payload: Record<string, any>) => {
        return patchAgentReport({ target, payload, projectId });
    }, [projectId]);

    const importRequirements = useCallback((runId: string, itemIds?: string[]) => {
        return importAgentReportRequirements({ runId, itemIds, projectId });
    }, [projectId]);

    const generateItemSpec = useCallback((options: {
        runId: string;
        itemId: string;
        itemType: ReportSpecItemType;
        body: Record<string, any>;
    }) => {
        return generateReportItemSpec({ ...options, projectId });
    }, [projectId]);

    return {
        saveReportPatch,
        importRequirements,
        generateItemSpec,
    };
}
