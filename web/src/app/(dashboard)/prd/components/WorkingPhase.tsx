'use client';

import { useState, useEffect } from 'react';
import type { Feature, GenerationResult, TestResult, FeatureStats, PrdSettings } from './types';
import { ProjectInfoBar } from './ProjectInfoBar';
import { ConfigPanel } from './ConfigPanel';
import { ProgressDashboard } from './ProgressDashboard';
import { FeatureSidebar } from './FeatureSidebar';
import { FeatureWorkspace } from './FeatureWorkspace';
import { TestGenerationPanel } from './TestGenerationPanel';

interface ImportRequirementsResult {
    created: number;
    skipped: number;
    total: number;
}

interface WorkingPhaseProps {
    projectName: string;
    currentProjectId: string | null;
    features: Feature[];
    testableFeatures: Feature[];
    stats: FeatureStats;
    generationResults: Record<string, GenerationResult>;
    generatedSpecs: string[];
    testResults: TestResult[];
    settings: PrdSettings;
    onUpdateSetting: <K extends keyof PrdSettings>(key: K, value: PrdSettings[K]) => void;
    onGenerate: (name: string) => Promise<boolean>;
    onBatchGenerate: (features: Feature[]) => void;
    onStop: (id: number) => Promise<void>;
    onGenerateTests: () => void;
    testPipelineStatus: 'idle' | 'running' | 'complete';
    onReset: () => void;
    onImportRequirements: () => Promise<void>;
    isImportingRequirements: boolean;
    importRequirementsResult: ImportRequirementsResult | null;
    onAddRequirement: (featureSlug: string, text: string) => Promise<void>;
    onEditRequirement: (featureSlug: string, index: number, text: string) => Promise<void>;
    onDeleteRequirement: (featureSlug: string, index: number) => Promise<void>;
}

export function WorkingPhase({
    projectName,
    currentProjectId,
    features,
    testableFeatures,
    stats,
    generationResults,
    generatedSpecs,
    testResults,
    settings,
    onUpdateSetting,
    onGenerate,
    onBatchGenerate,
    onStop,
    onGenerateTests,
    testPipelineStatus,
    onReset,
    onImportRequirements,
    isImportingRequirements,
    importRequirementsResult,
    onAddRequirement,
    onEditRequirement,
    onDeleteRequirement,
}: WorkingPhaseProps) {
    const [selectedFeature, setSelectedFeature] = useState<Feature | null>(null);

    // Auto-select first feature when project loads
    useEffect(() => {
        if (testableFeatures.length > 0 && !selectedFeature) {
            setSelectedFeature(testableFeatures[0]);
        }
    }, [selectedFeature, testableFeatures]);

    // Sync selectedFeature when features array updates (e.g. after CRUD)
    useEffect(() => {
        if (selectedFeature) {
            const updated = features.find(f => f.slug === selectedFeature.slug);
            if (updated && updated !== selectedFeature) {
                setSelectedFeature(updated);
            }
        }
    }, [features, selectedFeature]);

    // Check if any feature is generating
    const isGenerating = Object.values(generationResults).some(
        r => r.status === 'running' || r.status === 'pending' || r.status === 'queued'
    );
    const generationBlockedReason =
        settings.useLiveValidation && !settings.targetUrl.trim()
            ? 'Target URL is required for Live Browser Validation.'
            : null;

    return (
        <div className="animate-in stagger-2 prd-working-phase">
            <style>{`
                .prd-working-phase {
                    display: flex;
                    flex-direction: column;
                    gap: 0.75rem;
                    min-width: 0;
                }

                .prd-workspace-shell {
                    display: flex;
                    flex-direction: row;
                    min-width: 0;
                    min-height: 0;
                    height: clamp(600px, calc(100vh - 260px), 920px);
                    overflow: hidden;
                    border: 1px solid var(--border-subtle);
                    border-radius: 10px;
                    background: var(--surface);
                    box-shadow: 0 8px 24px rgba(0,0,0,0.28);
                }

                .prd-feature-sidebar {
                    width: 290px;
                    flex: 0 0 290px;
                    min-height: 0;
                    overflow: hidden;
                    border-right: 1px solid var(--border-subtle);
                }

                .prd-feature-detail {
                    flex: 1 1 auto;
                    min-width: 0;
                    min-height: 0;
                    overflow: hidden;
                }

                @media (max-width: 1040px) {
                    .prd-workspace-shell {
                        flex-direction: column;
                        height: auto;
                        min-height: 720px;
                    }

                    .prd-feature-sidebar {
                        width: 100%;
                        flex: 0 0 auto;
                        max-height: 360px;
                        border-right: 0;
                        border-bottom: 1px solid var(--border-subtle);
                    }

                    .prd-feature-detail {
                        min-height: 520px;
                    }
                }
            `}</style>
            {/* Project Info Bar — full width */}
            <ProjectInfoBar
                projectName={projectName}
                currentProjectId={currentProjectId}
                onReset={onReset}
                onImportRequirements={onImportRequirements}
                isImportingRequirements={isImportingRequirements}
                importRequirementsResult={importRequirementsResult}
                hasRequirements={testableFeatures.length > 0}
            />

            {/* Config Panel — full width, collapsible */}
            <ConfigPanel
                settings={settings}
                onUpdate={onUpdateSetting}
            />

            {/* Progress Dashboard — full width */}
            <ProgressDashboard stats={stats} />

            {/* Sidebar + Workspace — two-column layout */}
            <div className="animate-in stagger-3 prd-workspace-shell">
                <FeatureSidebar
                    features={features}
                    selectedFeature={selectedFeature}
                    onSelect={setSelectedFeature}
                    generationResults={generationResults}
                    onBatchGenerate={() => onBatchGenerate(testableFeatures)}
                    isGenerating={isGenerating}
                    generationBlockedReason={generationBlockedReason}
                />
                <FeatureWorkspace
                    feature={selectedFeature}
                    generationResult={selectedFeature ? generationResults[selectedFeature.name] : undefined}
                    onGenerate={onGenerate}
                    onStop={onStop}
                    isGenerating={isGenerating}
                    generationBlockedReason={generationBlockedReason}
                    currentTargetUrl={settings.targetUrl}
                    onAddRequirement={onAddRequirement}
                    onEditRequirement={onEditRequirement}
                    onDeleteRequirement={onDeleteRequirement}
                />
            </div>

            {/* Test Generation Panel — full width */}
            <div className="animate-in stagger-4">
                <TestGenerationPanel
                    generatedSpecs={generatedSpecs}
                    onGenerateTests={onGenerateTests}
                    testResults={testResults}
                    useNativeAgents={settings.useNativeAgents}
                    onToggleNativeAgents={(v) => onUpdateSetting('useNativeAgents', v)}
                    pipelineStatus={testPipelineStatus}
                />
            </div>
        </div>
    );
}
