'use client';

import { useState, useCallback } from 'react';
import { UploadCloud, AlertCircle } from 'lucide-react';
import { PageLayout } from '@/components/ui/page-layout';
import { PageHeader } from '@/components/ui/page-header';
import { API_BASE } from '@/lib/api';
import { getProjectDefaultUrl } from '@/lib/project-url';

import { computeStats } from './components/types';
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
        const result = await project.upload(selectedFile, settings.targetFeatures);
        if (result) setFile(null);
    }, [project, settings.targetFeatures]);

    const handleReset = useCallback(() => {
        setFile(null);
        project.reset();
        generation.resetGeneration();
        testRunner.resetTests();
        resetSettings();
    }, [project, generation, testRunner, resetSettings]);

    const handleGenerateTests = useCallback(() => {
        testRunner.runTests(generation.generatedSpecs);
    }, [testRunner, generation.generatedSpecs]);

    const handleImportRequirements = useCallback(async () => {
        if (!project.projectData) return;

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
    }, [project]);

    // --- Requirements CRUD ---
    const handleAddRequirement = useCallback(async (featureSlug: string, text: string) => {
        const res = await fetch(
            `${API_BASE}/api/prd/${project.projectData!.project}/features/${encodeURIComponent(featureSlug)}/requirements`,
            { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text }) }
        );
        if (!res.ok) throw new Error('Failed to add requirement');
        const data = await res.json();
        project.updateFeatureRequirements(featureSlug, data.requirements);
    }, [project]);

    const handleEditRequirement = useCallback(async (featureSlug: string, index: number, text: string) => {
        const res = await fetch(
            `${API_BASE}/api/prd/${project.projectData!.project}/features/${encodeURIComponent(featureSlug)}/requirements/${index}`,
            { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text }) }
        );
        if (!res.ok) throw new Error('Failed to edit requirement');
        const data = await res.json();
        project.updateFeatureRequirements(featureSlug, data.requirements);
    }, [project]);

    const handleDeleteRequirement = useCallback(async (featureSlug: string, index: number) => {
        const res = await fetch(
            `${API_BASE}/api/prd/${project.projectData!.project}/features/${encodeURIComponent(featureSlug)}/requirements/${index}`,
            { method: 'DELETE' }
        );
        if (!res.ok) throw new Error('Failed to delete requirement');
        const data = await res.json();
        project.updateFeatureRequirements(featureSlug, data.requirements);
    }, [project]);

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
                    onUpload={handleUpload}
                    onLoadProject={project.loadProject}
                    onDeleteProject={project.deleteProject}
                    existingProjects={project.existingProjects}
                    isUploading={project.isUploading}
                    targetFeatures={settings.targetFeatures}
                    onTargetFeaturesChange={(n) => updateSetting('targetFeatures', n)}
                />
            ) : (
                <WorkingPhase
                    projectName={project.projectData!.project}
                    currentProjectId={project.currentProjectId}
                    features={project.projectData!.features}
                    testableFeatures={project.testableFeatures}
                    stats={stats}
                    generationResults={generation.results}
                    generatedSpecs={generation.generatedSpecs}
                    testResults={testRunner.testResults}
                    settings={settings}
                    onUpdateSetting={updateSetting}
                    onGenerate={generation.generate}
                    onBatchGenerate={(features) => generation.batchGenerate(features)}
                    onStop={generation.stop}
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
