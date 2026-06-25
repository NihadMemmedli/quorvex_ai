'use client';

import { useState, useCallback } from 'react';
import { UploadCloud, AlertCircle } from 'lucide-react';
import { PageLayout } from '@/components/ui/page-layout';
import { PageHeader } from '@/components/ui/page-header';
import { useProjectRole } from '@/hooks/useProjectRole';
import { API_BASE } from '@/lib/api';
import { getProjectDefaultUrl } from '@/lib/project-url';

import { computeStats, type Feature, type PrdSettings } from './components/types';
import { usePrdSettings } from './components/hooks/usePrdSettings';
import { usePrdProject } from './components/hooks/usePrdProject';
import { usePrdGeneration } from './components/hooks/usePrdGeneration';
import { usePrdTestRunner } from './components/hooks/usePrdTestRunner';
import { UploadPhase } from './components/UploadPhase';
import { WorkingPhase } from './components/WorkingPhase';

interface ImportRequirementsResult {
    created: number;
    skipped: number;
    total: number;
}

async function readResponseJson(response: Response): Promise<any> {
    const text = await response.text();
    if (!text) return null;

    try {
        return JSON.parse(text);
    } catch {
        return null;
    }
}

export default function PrdPage() {
    const project = usePrdProject();
    const { canEdit: canEditProject } = useProjectRole(project.currentProjectId);
    const canEdit = !project.currentProjectId || canEditProject;
    const { settings, updateSetting, resetSettings } = usePrdSettings(
        project.projectData?.project,
        getProjectDefaultUrl(project.currentProject)
    );

    const generation = usePrdGeneration(project.projectData?.project, settings);
    const testRunner = usePrdTestRunner(
        settings.targetUrl,
        settings.useLiveValidation,
        settings.useNativeAgents
    );

    const [file, setFile] = useState<File | null>(null);
    const [isImportingRequirements, setIsImportingRequirements] = useState(false);
    const [importRequirementsResult, setImportRequirementsResult] = useState<ImportRequirementsResult | null>(null);

    // Computed stats
    const stats = computeStats(
        project.projectData?.features || [],
        generation.results
    );

    // Phase detection
    const hasProject = !!project.projectData;

    // --- Handlers ---
    const handleUpload = useCallback(async (selectedFile: File) => {
        if (!canEdit) return;
        const result = await project.upload(selectedFile, settings.targetFeatures);
        if (result) setFile(null);
    }, [canEdit, project, settings.targetFeatures]);

    const handleUpdateSetting = useCallback(<K extends keyof PrdSettings>(key: K, value: PrdSettings[K]) => {
        if (!canEdit) return;
        updateSetting(key, value);
    }, [canEdit, updateSetting]);

    const handleReset = useCallback(() => {
        setFile(null);
        project.reset();
        generation.resetGeneration();
        testRunner.resetTests();
        resetSettings();
    }, [project, generation, testRunner, resetSettings]);

    const handleGenerateTests = useCallback(() => {
        if (!canEdit) return;
        testRunner.runTests(generation.generatedSpecs);
    }, [canEdit, testRunner, generation.generatedSpecs]);

    const handleImportRequirements = useCallback(async () => {
        if (!canEdit || !project.projectData) return;

        setIsImportingRequirements(true);
        setImportRequirementsResult(null);
        project.setError('');

        try {
            const params = new URLSearchParams();
            if (project.currentProjectId) params.set('tenant_project_id', project.currentProjectId);
            const query = params.toString() ? `?${params.toString()}` : '';
            const res = await fetch(
                `${API_BASE}/api/prd/${encodeURIComponent(project.projectData.project)}/import-requirements${query}`,
                { method: 'POST' }
            );
            const data = await readResponseJson(res);
            if (!res.ok) {
                const detail = data?.detail || data?.message;
                const fallback =
                    res.status === 404
                        ? 'PRD requirements import endpoint was not found. Restart the backend and try again.'
                        : 'Failed to import requirements';
                throw new Error(detail && detail !== 'Not Found' ? detail : fallback);
            }
            setImportRequirementsResult({
                created: data.created || 0,
                skipped: data.skipped || 0,
                total: data.total || 0,
            });
        } catch (err: any) {
            project.setError(err.message || 'Failed to import requirements');
        } finally {
            setIsImportingRequirements(false);
        }
    }, [canEdit, project]);

    // --- Requirements CRUD ---
    const handleAddRequirement = useCallback(async (featureSlug: string, text: string) => {
        if (!canEdit) return;
        const res = await fetch(
            `${API_BASE}/api/prd/${project.projectData!.project}/features/${encodeURIComponent(featureSlug)}/requirements`,
            { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text }) }
        );
        if (!res.ok) throw new Error('Failed to add requirement');
        const data = await res.json();
        project.updateFeatureRequirements(featureSlug, data.requirements);
    }, [canEdit, project]);

    const handleEditRequirement = useCallback(async (featureSlug: string, index: number, text: string) => {
        if (!canEdit) return;
        const res = await fetch(
            `${API_BASE}/api/prd/${project.projectData!.project}/features/${encodeURIComponent(featureSlug)}/requirements/${index}`,
            { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text }) }
        );
        if (!res.ok) throw new Error('Failed to edit requirement');
        const data = await res.json();
        project.updateFeatureRequirements(featureSlug, data.requirements);
    }, [canEdit, project]);

    const handleDeleteRequirement = useCallback(async (featureSlug: string, index: number) => {
        if (!canEdit) return;
        const res = await fetch(
            `${API_BASE}/api/prd/${project.projectData!.project}/features/${encodeURIComponent(featureSlug)}/requirements/${index}`,
            { method: 'DELETE' }
        );
        if (!res.ok) throw new Error('Failed to delete requirement');
        const data = await res.json();
        project.updateFeatureRequirements(featureSlug, data.requirements);
    }, [canEdit, project]);

    const handleDeleteProject = useCallback((projectId: string) => {
        if (!canEdit) return;
        project.deleteProject(projectId);
    }, [canEdit, project]);

    const handleGenerate = useCallback(async (name: string) => {
        if (!canEdit) return false;
        return generation.generate(name);
    }, [canEdit, generation]);

    const handleBatchGenerate = useCallback((features: Feature[]) => {
        if (!canEdit) return;
        generation.batchGenerate(features);
    }, [canEdit, generation]);

    const handleStop = useCallback(async (id: number) => {
        if (!canEdit) return;
        await generation.stop(id);
    }, [canEdit, generation]);

    // Combined error from any source
    const error = project.error;

    return (
        <PageLayout tier="wide">
            <PageHeader
                title="PRD Processing"
                subtitle="Automated analysis and test generation from your requirement documents"
                icon={<UploadCloud size={20} />}
            />

            {/* Error Display */}
            {error && (
                <div className="mb-6 flex items-center gap-3 p-4 rounded-xl bg-red-500/[0.06] border border-red-500/15 relative overflow-hidden animate-in stagger-1 fade-in slide-in-from-top-2">
                    <div className="absolute left-0 top-0 bottom-0 w-1 bg-red-500 rounded-l" />
                    <div className="pl-2">
                        <AlertCircle className="h-5 w-5 text-red-400 animate-[pulse_2s_ease-in-out_infinite]" />
                    </div>
                    <span className="font-medium text-sm text-red-400">{error}</span>
                    <button
                        onClick={() => project.setError('')}
                        className="ml-auto text-red-400/60 hover:text-red-400 transition-colors text-xs"
                    >
                        Dismiss
                    </button>
                </div>
            )}

            {!hasProject ? (
                <UploadPhase
                    canEdit={canEdit}
                    onUpload={handleUpload}
                    onLoadProject={project.loadProject}
                    onDeleteProject={handleDeleteProject}
                    existingProjects={project.existingProjects}
                    isUploading={project.isUploading}
                    targetFeatures={settings.targetFeatures}
                    onTargetFeaturesChange={(n) => handleUpdateSetting('targetFeatures', n)}
                />
            ) : (
                <WorkingPhase
                    canEdit={canEdit}
                    projectName={project.projectData!.project}
                    currentProjectId={project.currentProjectId}
                    features={project.projectData!.features}
                    testableFeatures={project.testableFeatures}
                    stats={stats}
                    generationResults={generation.results}
                    generatedSpecs={generation.generatedSpecs}
                    testResults={testRunner.testResults}
                    settings={settings}
                    onUpdateSetting={handleUpdateSetting}
                    onGenerate={handleGenerate}
                    onBatchGenerate={handleBatchGenerate}
                    onStop={handleStop}
                    onGenerateTests={handleGenerateTests}
                    testPipelineStatus={testRunner.pipelineStatus}
                    onReset={handleReset}
                    onImportRequirements={handleImportRequirements}
                    isImportingRequirements={isImportingRequirements}
                    importRequirementsResult={importRequirementsResult}
                    onAddRequirement={handleAddRequirement}
                    onEditRequirement={handleEditRequirement}
                    onDeleteRequirement={handleDeleteRequirement}
                />
            )}
        </PageLayout>
    );
}
