'use client';

import { useState, useEffect } from 'react';
import type { Feature, GenerationResult, TestResult, FeatureStats, PrdSettings } from './types';
import { ProjectInfoBar } from './ProjectInfoBar';
import { ConfigPanel } from './ConfigPanel';
import { ProgressDashboard } from './ProgressDashboard';
import { FeatureSidebar } from './FeatureSidebar';
import { FeatureWorkspace } from './FeatureWorkspace';
import { TestGenerationPanel } from './TestGenerationPanel';

interface WorkingPhaseProps {
    projectName: string;
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
    onAddRequirement: (featureSlug: string, text: string) => Promise<void>;
    onEditRequirement: (featureSlug: string, index: number, text: string) => Promise<void>;
    onDeleteRequirement: (featureSlug: string, index: number) => Promise<void>;
}

export function WorkingPhase({
    projectName,
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
    }, [testableFeatures.length]);

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
        r => r.status === 'running' || r.status === 'pending'
    );

    return (
        <div className="animate-in stagger-2 flex flex-col gap-4">
            {/* Project Info Bar — full width */}
            <ProjectInfoBar
                projectName={projectName}
                featureCount={stats.total}
                completedCount={stats.completed}
                onReset={onReset}
            />

            {/* Config Panel — full width, collapsible */}
            <ConfigPanel
                settings={settings}
                onUpdate={onUpdateSetting}
            />

            {/* Progress Dashboard — full width */}
            <ProgressDashboard stats={stats} />

            {/* Sidebar + Workspace — two-column layout */}
            <div
                className="flex rounded-2xl border animate-in stagger-3"
                style={{
                    borderColor: 'var(--border-subtle)',
                    boxShadow: '0 8px 32px rgba(0,0,0,0.3)',
                    height: 'clamp(400px, calc(100vh - 420px), calc(100vh - 300px))',
                    overflow: 'hidden',
                }}
            >
                <FeatureSidebar
                    features={features}
                    selectedFeature={selectedFeature}
                    onSelect={setSelectedFeature}
                    generationResults={generationResults}
                    onBatchGenerate={() => onBatchGenerate(testableFeatures)}
                    isGenerating={isGenerating}
                />
                <FeatureWorkspace
                    feature={selectedFeature}
                    generationResult={selectedFeature ? generationResults[selectedFeature.name] : undefined}
                    onGenerate={onGenerate}
                    onStop={onStop}
                    isGenerating={isGenerating}
                    project={projectName}
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
