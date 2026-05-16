export type GateState = 'all' | 'running' | 'failed' | 'passed' | 'needs-full-suite';

export interface QualityGateBatchFailedTest {
    run_id: string;
    spec_name: string;
    status: string;
    error_message?: string | null;
}

export interface QualityGateBatch {
    id: string;
    name?: string;
    status: string;
    total_tests: number;
    passed: number;
    failed: number;
    stopped?: number;
    running: number;
    queued: number;
    success_rate: number;
    created_at?: string;
    started_at?: string;
    completed_at?: string;
    failed_tests?: QualityGateBatchFailedTest[];
}

export interface QualityGateSelectedTest {
    spec_name: string;
    test_path?: string;
    reason: string;
    confidence: string;
    risk_level: string;
    selection_source: string;
    estimated_duration_seconds?: number;
    tags: string[];
    categories: string[];
}

export interface QualityGateChangedFile {
    path: string;
    status: string;
    additions: number;
    deletions: number;
    changes: number;
    area: string;
    risk_level: string;
    reason?: string;
}

export interface QualityGateFeedback {
    comment?: { action?: string; url?: string } | null;
    commit_status?: { state?: string; url?: string } | null;
    errors?: string[];
}

export interface QualityGate {
    id: string;
    pr_number: number;
    title?: string;
    owner: string;
    repo: string;
    head_ref?: string;
    base_ref?: string;
    risk_level: string;
    confidence: string;
    summary?: string;
    changed_files_count: number;
    selected_tests_count: number;
    total_candidate_tests: number;
    estimated_duration_seconds?: number;
    saved_tests_count?: number;
    fallback_reason?: string | null;
    repository_index_snapshot?: string;
    batch_id?: string | null;
    created_at?: string;
    changed_files?: QualityGateChangedFile[];
    selected_tests?: QualityGateSelectedTest[];
    feedback?: QualityGateFeedback;
    run_request?: {
        batch_created?: boolean;
        batch_id?: string;
        run_ids?: string[];
        count?: number;
        reason?: string;
    } | null;
    quality_gate: {
        gate_id?: string;
        state: string;
        github_state?: string;
        description: string;
        batch_url?: string | null;
        analysis_url?: string | null;
        batch?: QualityGateBatch | null;
        feedback_comment_url?: string | null;
        commit_status_url?: string | null;
        last_feedback_state?: string | null;
        feedback_errors?: string[];
        final_feedback_published_at?: string | null;
    };
}

export interface QualityGateDefaults {
    ensure_indexed: boolean;
    force_reindex: boolean;
    run_recommended: boolean;
    post_feedback: boolean;
    create_commit_status: boolean;
    browser: string;
    hybrid: boolean;
    max_iterations: number;
}

export const FALLBACK_QUALITY_GATE_DEFAULTS: QualityGateDefaults = {
    ensure_indexed: true,
    force_reindex: false,
    run_recommended: true,
    post_feedback: true,
    create_commit_status: true,
    browser: 'chromium',
    hybrid: false,
    max_iterations: 20,
};

type QualityGateConfigPayload = {
    enabled: boolean;
    ensure_indexed: boolean;
    force_reindex: boolean;
    run_recommended: boolean;
    post_feedback: boolean;
    create_commit_status: boolean;
    default_browser: string;
    hybrid: boolean;
    max_iterations: number;
    timeout_minutes: number;
};

function asRecord(value: unknown): Record<string, unknown> {
    if (!value || typeof value !== 'object' || Array.isArray(value)) return {};
    return value as Record<string, unknown>;
}

function asBoolean(value: unknown, fallback: boolean): boolean {
    return typeof value === 'boolean' ? value : fallback;
}

function asPositiveInteger(value: unknown, fallback: number): number {
    const parsed = typeof value === 'number' ? value : Number(value);
    if (!Number.isFinite(parsed)) return fallback;
    return Math.max(1, Math.floor(parsed));
}

function asBrowser(value: unknown, fallback: string): string {
    return typeof value === 'string' && ['chromium', 'firefox', 'webkit'].includes(value) ? value : fallback;
}

export function resolveQualityGateDefaults(config: unknown): QualityGateDefaults {
    const root = asRecord(config);
    const source = asRecord(
        root.quality_gate
        ?? root.quality_gate_defaults
        ?? root.pr_quality_gate_defaults
        ?? root.qualityGateDefaults,
    );
    const fallback = FALLBACK_QUALITY_GATE_DEFAULTS;
    return {
        ensure_indexed: asBoolean(source.ensure_indexed, fallback.ensure_indexed),
        force_reindex: asBoolean(source.force_reindex, fallback.force_reindex),
        run_recommended: asBoolean(source.run_recommended, fallback.run_recommended),
        post_feedback: asBoolean(source.post_feedback, fallback.post_feedback),
        create_commit_status: asBoolean(source.create_commit_status, fallback.create_commit_status),
        browser: asBrowser(source.browser ?? source.default_browser, fallback.browser),
        hybrid: asBoolean(source.hybrid, fallback.hybrid),
        max_iterations: asPositiveInteger(source.max_iterations, fallback.max_iterations),
    };
}

export function qualityGateConfigPayload(defaults: QualityGateDefaults): QualityGateConfigPayload {
    return {
        enabled: true,
        ensure_indexed: defaults.ensure_indexed,
        force_reindex: defaults.force_reindex,
        run_recommended: defaults.run_recommended,
        post_feedback: defaults.post_feedback,
        create_commit_status: defaults.create_commit_status,
        default_browser: defaults.browser,
        hybrid: defaults.hybrid,
        max_iterations: defaults.max_iterations,
        timeout_minutes: 120,
    };
}
