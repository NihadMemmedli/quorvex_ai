import { useCallback, useRef, type Dispatch, type SetStateAction } from 'react';
import {
    archiveAgentDefinition as archiveAgentDefinitionApi,
    fetchAgentDefinitions,
    fetchAgentToolCatalog,
    saveAgentDefinition,
    type AgentDefinitionPayload,
} from './agents-api';
import type { AgentDefinition, AgentTool } from './agents-model';

export function useAgentDefinitions(options: {
    projectId?: string | null;
    projectLoading: boolean;
    agentDefinitionsLength: number;
    toolCatalogLength: number;
    selectedDefinitionId: string;
    setAgentDefinitions: Dispatch<SetStateAction<AgentDefinition[]>>;
    setToolCatalog: Dispatch<SetStateAction<AgentTool[]>>;
    setSelectedDefinitionId: Dispatch<SetStateAction<string>>;
}) {
    const {
        projectId,
        projectLoading,
        agentDefinitionsLength,
        toolCatalogLength,
        selectedDefinitionId,
        setAgentDefinitions,
        setToolCatalog,
        setSelectedDefinitionId,
    } = options;
    const toolCatalogLoadedProjectRef = useRef<string | null>(null);
    const definitionsLoadedProjectRef = useRef<string | null>(null);

    const resetAgentLibraryLoadedProjects = useCallback(() => {
        toolCatalogLoadedProjectRef.current = null;
        definitionsLoadedProjectRef.current = null;
    }, []);

    const loadToolCatalog = useCallback(async () => {
        if (projectLoading) return;
        const projectKey = projectId || 'unscoped';
        if (toolCatalogLoadedProjectRef.current === projectKey && toolCatalogLength > 0) return;
        try {
            setToolCatalog(await fetchAgentToolCatalog());
            toolCatalogLoadedProjectRef.current = projectKey;
        } catch (e) {
            console.error('Failed to fetch agent tool catalog', e);
        }
    }, [projectId, projectLoading, setToolCatalog, toolCatalogLength]);

    const loadAgentDefinitions = useCallback(async () => {
        if (projectLoading) return;
        const projectKey = projectId || 'unscoped';
        if (definitionsLoadedProjectRef.current === projectKey && agentDefinitionsLength > 0) return;
        try {
            const data = await fetchAgentDefinitions(projectId);
            setAgentDefinitions(data);
            definitionsLoadedProjectRef.current = projectKey;
            if (!selectedDefinitionId && data.length) {
                setSelectedDefinitionId(data[0].id);
            }
        } catch (e) {
            console.error('Failed to fetch agent definitions', e);
        }
    }, [agentDefinitionsLength, projectId, projectLoading, selectedDefinitionId, setAgentDefinitions, setSelectedDefinitionId]);

    const loadAgentDefinitionsFresh = useCallback(async () => {
        definitionsLoadedProjectRef.current = null;
        if (projectLoading) return;
        try {
            const data = await fetchAgentDefinitions(projectId);
            setAgentDefinitions(data);
            definitionsLoadedProjectRef.current = projectId || 'unscoped';
            if (!selectedDefinitionId && data.length) {
                setSelectedDefinitionId(data[0].id);
            }
        } catch (e) {
            console.error('Failed to fetch agent definitions', e);
        }
    }, [projectId, projectLoading, selectedDefinitionId, setAgentDefinitions, setSelectedDefinitionId]);

    const ensureAgentLibraryData = useCallback(async () => {
        await Promise.all([loadToolCatalog(), loadAgentDefinitions()]);
    }, [loadAgentDefinitions, loadToolCatalog]);

    const saveDefinitionRecord = useCallback((definitionId: string | null, payload: AgentDefinitionPayload) => {
        return saveAgentDefinition({ definitionId, payload, projectId });
    }, [projectId]);

    const archiveDefinitionRecord = useCallback((definitionId: string) => {
        return archiveAgentDefinitionApi(definitionId, projectId);
    }, [projectId]);

    return {
        resetAgentLibraryLoadedProjects,
        loadToolCatalog,
        loadAgentDefinitions,
        loadAgentDefinitionsFresh,
        ensureAgentLibraryData,
        saveDefinitionRecord,
        archiveDefinitionRecord,
    };
}
