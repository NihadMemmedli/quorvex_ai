export type ProcessingStep = 'upload' | 'extracted' | 'generate-plan' | 'generate-tests' | 'complete';

export interface Feature {
    name: string;
    slug: string;
    requirements: string[];
    content?: string;
    merged_from?: string[];
}

export interface GenerationResult {
    success: boolean;
    timestamp?: Date;
    error?: string;
    status?: string;      // pending, running, completed, failed, cancelled
    stage?: string;       // current stage name
    message?: string;     // progress message
    generationId?: number;
}

export interface TestResult {
    spec: string;
    status: string;
    message?: string;
    test_path?: string;
    passed?: boolean;
    attempts?: number;
    healed?: boolean;
    error_log?: string;
    native?: boolean;
}

export interface ProjectInfo {
    project: string;
    features: Feature[];
    total_chunks: number;
}

export interface ExistingProject {
    project: string;
    processed_at?: string;
    feature_count: number;
}

export interface PrdSettings {
    targetUrl: string;
    loginUrl: string;
    username: string;
    password: string;
    useLiveValidation: boolean;
    useNativeAgents: boolean;
    targetFeatures: number;
}

export interface FeatureStats {
    total: number;
    completed: number;
    running: number;
    failed: number;
    pending: number;
}

export function computeStats(
    features: Feature[],
    results: Record<string, GenerationResult>
): FeatureStats {
    const testable = features.filter(f => f.requirements?.length > 0);
    let completed = 0;
    let running = 0;
    let failed = 0;
    let pending = 0;

    for (const f of testable) {
        const r = results[f.name];
        if (!r) { pending++; continue; }
        if (r.status === 'completed' || r.success) completed++;
        else if (r.status === 'running' || r.status === 'pending') running++;
        else if (r.status === 'failed' || (r.success === false && r.error)) failed++;
        else pending++;
    }

    return { total: testable.length, completed, running, failed, pending };
}

export function getFeatureStatus(result: GenerationResult | undefined): 'completed' | 'running' | 'failed' | 'pending' {
    if (!result) return 'pending';
    if (result.status === 'running' || result.status === 'pending') return 'running';
    if (result.status === 'failed' || (result.success === false && result.error)) return 'failed';
    if (result.success || result.status === 'completed') return 'completed';
    return 'pending';
}

export function getStageDisplay(stage: string | undefined, message: string | undefined): string {
    if (message) return message;
    switch (stage) {
        case 'queued': return 'Generation queued...';
        case 'initializing': return 'Setting up environment...';
        case 'retrieving_context': return 'Retrieving PRD context...';
        case 'invoking_agent': return 'Invoking Playwright agent...';
        case 'saving_spec': return 'Saving generated spec...';
        case 'complete': return 'Generation complete';
        case 'error': return 'Generation failed';
        case 'cancelled': return 'Cancelled';
        default: return 'Generating...';
    }
}

export function formatTimeAgo(date: Date): string {
    const seconds = Math.floor((new Date().getTime() - date.getTime()) / 1000);
    if (seconds < 60) return 'just now';
    const minutes = Math.floor(seconds / 60);
    if (minutes < 60) return `${minutes}m ago`;
    const hours = Math.floor(minutes / 60);
    if (hours < 24) return `${hours}h ago`;
    return date.toLocaleDateString();
}
