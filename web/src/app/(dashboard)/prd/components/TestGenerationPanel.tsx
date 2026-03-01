'use client';

import { Play, CheckCircle, Loader2, Zap, Sparkles } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Switch } from '@/components/ui/switch';
import type { TestResult } from './types';

interface TestGenerationPanelProps {
    generatedSpecs: string[];
    onGenerateTests: () => void;
    testResults: TestResult[];
    useNativeAgents: boolean;
    onToggleNativeAgents: (value: boolean) => void;
    pipelineStatus: 'idle' | 'running' | 'complete';
}

export function TestGenerationPanel({
    generatedSpecs,
    onGenerateTests,
    testResults,
    useNativeAgents,
    onToggleNativeAgents,
    pipelineStatus,
}: TestGenerationPanelProps) {
    if (generatedSpecs.length === 0) return null;

    const isComplete = pipelineStatus === 'complete';
    const isRunning = pipelineStatus === 'running';

    return (
        <div
            className={`card-elevated overflow-hidden relative ${isComplete ? 'gradient-border-success' : 'gradient-border'}`}
        >
            {/* Top accent line */}
            <div
                className="absolute top-0 left-0 right-0 h-[1px]"
                style={{
                    background: isComplete
                        ? 'linear-gradient(90deg, transparent, rgba(34,197,94,0.4), transparent)'
                        : 'linear-gradient(90deg, transparent, rgba(59,130,246,0.4), transparent)',
                }}
            />

            {/* Header */}
            <div className="mb-1">
                <h3
                    className="text-lg font-semibold"
                    style={{ color: 'var(--text)' }}
                >
                    {isComplete ? 'Generation Complete' : 'Generate Tests'}
                </h3>
                <p
                    className="text-sm mt-1"
                    style={{ color: 'var(--text-secondary)' }}
                >
                    {generatedSpecs.length} test plan{generatedSpecs.length !== 1 ? 's' : ''} ready.
                    {!isComplete && ' This will generate Playwright code for all plans.'}
                </p>
            </div>

            {/* AI-Powered Generation Toggle */}
            <div
                className="flex items-center justify-between p-3 rounded-lg mb-4 mt-4"
                style={{
                    background: 'rgba(255,255,255,0.02)',
                    border: '1px solid rgba(255,255,255,0.06)',
                }}
            >
                <div className="flex items-center gap-3">
                    <div
                        className="p-1.5 rounded-lg transition-all duration-300"
                        style={{
                            background: useNativeAgents ? 'rgba(251,191,36,0.2)' : 'rgba(100,116,139,0.1)',
                            color: useNativeAgents ? '#facc15' : 'var(--text-tertiary)',
                            boxShadow: useNativeAgents ? '0 0 12px rgba(251,191,36,0.2)' : 'none',
                        }}
                    >
                        <Zap size={16} />
                    </div>
                    <div className="flex flex-col">
                        <span className="text-sm font-medium" style={{ color: 'var(--text)' }}>
                            AI-Powered Generation
                        </span>
                        <span className="text-[10px]" style={{ color: 'var(--text-tertiary)' }}>
                            {useNativeAgents
                                ? 'Live browser generation & intelligent repair'
                                : 'Static code generation only'}
                        </span>
                    </div>
                </div>
                <Switch
                    checked={useNativeAgents}
                    onCheckedChange={onToggleNativeAgents}
                />
            </div>

            {/* Action Button */}
            <button
                onClick={onGenerateTests}
                disabled={isRunning || isComplete}
                className="w-full h-[52px] rounded-lg font-semibold text-base transition-all duration-300 relative overflow-hidden disabled:cursor-not-allowed flex items-center justify-center gap-2"
                style={
                    isComplete
                        ? {
                              background: 'linear-gradient(135deg, #16a34a, #34d399)',
                              color: '#fff',
                              cursor: 'default',
                          }
                        : isRunning
                          ? {
                                background: 'var(--primary)',
                                color: '#fff',
                            }
                          : {
                                background: 'linear-gradient(135deg, var(--primary), #2563eb)',
                                color: '#fff',
                                boxShadow: '0 0 20px rgba(59,130,246,0.2)',
                            }
                }
                onMouseEnter={(e) => {
                    if (!isRunning && !isComplete) {
                        e.currentTarget.style.boxShadow = '0 0 30px rgba(59,130,246,0.3)';
                        e.currentTarget.style.transform = 'translateY(-1px)';
                    }
                }}
                onMouseLeave={(e) => {
                    if (!isRunning && !isComplete) {
                        e.currentTarget.style.boxShadow = '0 0 20px rgba(59,130,246,0.2)';
                        e.currentTarget.style.transform = 'translateY(0)';
                    }
                }}
            >
                {isRunning ? (
                    <>
                        Generating Code <Loader2 className="h-4 w-4 animate-spin" />
                    </>
                ) : isComplete ? (
                    <>
                        Tests Generated <CheckCircle className="h-4 w-4" />
                    </>
                ) : (
                    <>
                        Generate Code <Play className="h-4 w-4" />
                    </>
                )}
                {isRunning && <div className="absolute inset-0 progress-shimmer" />}
            </button>

            {/* Results List */}
            {testResults.length > 0 && (
                <div className="mt-6 flex flex-col gap-2">
                    <div
                        className="text-xs font-semibold uppercase tracking-widest mb-1"
                        style={{ color: 'var(--text-tertiary)' }}
                    >
                        Results
                    </div>
                    <div className="flex flex-col gap-2 max-h-[300px] overflow-y-auto custom-scrollbar">
                        {testResults.map((res, i) => {
                            const statusColorMap: Record<string, { bg: string; text: string; accent: string }> = {
                                passed: {
                                    bg: 'rgba(34,197,94,0.1)',
                                    text: 'var(--success)',
                                    accent: 'var(--success)',
                                },
                                success: {
                                    bg: 'rgba(34,197,94,0.1)',
                                    text: 'var(--success)',
                                    accent: 'var(--success)',
                                },
                                running: {
                                    bg: 'rgba(59,130,246,0.1)',
                                    text: 'var(--primary)',
                                    accent: 'var(--primary)',
                                },
                                failed: {
                                    bg: 'rgba(248,113,113,0.1)',
                                    text: 'var(--danger)',
                                    accent: 'var(--danger)',
                                },
                                error: {
                                    bg: 'rgba(248,113,113,0.1)',
                                    text: 'var(--danger)',
                                    accent: 'var(--danger)',
                                },
                            };

                            const colors = statusColorMap[res.status] || {
                                bg: 'rgba(251,191,36,0.1)',
                                text: 'var(--warning)',
                                accent: 'var(--warning)',
                            };

                            return (
                                <div
                                    key={i}
                                    className="flex justify-between items-center p-3 rounded-lg relative overflow-hidden transition-colors duration-200"
                                    style={{
                                        background: 'var(--surface)',
                                        border: '1px solid rgba(255,255,255,0.06)',
                                    }}
                                    onMouseEnter={(e) =>
                                        (e.currentTarget.style.borderColor = 'rgba(255,255,255,0.1)')
                                    }
                                    onMouseLeave={(e) =>
                                        (e.currentTarget.style.borderColor = 'rgba(255,255,255,0.06)')
                                    }
                                >
                                    {/* Left accent bar */}
                                    <div
                                        className="absolute left-0 top-0 bottom-0 w-[3px] rounded-l"
                                        style={{ background: colors.accent }}
                                    />
                                    <div className="flex flex-col gap-1 overflow-hidden pl-2">
                                        <span
                                            className="text-xs font-mono truncate max-w-[180px]"
                                            style={{ color: 'var(--text-secondary)' }}
                                            title={res.spec}
                                        >
                                            {res.spec?.split('prd-')[1] || res.spec}
                                        </span>
                                        {res.attempts && (
                                            <span
                                                className="text-[10px]"
                                                style={{ color: 'var(--text-tertiary)' }}
                                            >
                                                {res.attempts} attempt{res.attempts > 1 ? 's' : ''}
                                                {res.healed && (
                                                    <span
                                                        className="ml-1.5 inline-flex items-center gap-0.5"
                                                        style={{ color: '#facc15' }}
                                                    >
                                                        <Sparkles className="h-2.5 w-2.5" />
                                                        healed
                                                    </span>
                                                )}
                                            </span>
                                        )}
                                    </div>
                                    <div className="flex items-center gap-2">
                                        {res.status === 'running' && (
                                            <Loader2
                                                className="h-3 w-3 animate-spin"
                                                style={{ color: 'var(--primary)' }}
                                            />
                                        )}
                                        <Badge
                                            className="text-[10px] h-5"
                                            style={{
                                                background: colors.bg,
                                                color: colors.text,
                                            }}
                                        >
                                            {res.status}
                                        </Badge>
                                    </div>
                                </div>
                            );
                        })}
                    </div>
                </div>
            )}
        </div>
    );
}
