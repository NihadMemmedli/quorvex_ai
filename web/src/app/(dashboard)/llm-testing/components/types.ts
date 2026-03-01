export interface Provider {
    id: string;
    name: string;
    base_url: string;
    model_id: string;
    default_params: Record<string, any>;
    custom_pricing: [number, number] | null;
    is_active: boolean;
    created_at: string;
}

export interface Spec {
    name: string;
    title: string;
    path: string;
    size: number;
    modified: number;
}

export interface Run {
    id: string;
    provider_id: string;
    comparison_id: string | null;
    dataset_id: string | null;
    dataset_name: string | null;
    spec_name: string;
    status: string;
    total_cases: number;
    passed_cases: number;
    failed_cases: number;
    error_cases: number;
    pass_rate: number;
    avg_latency_ms: number | null;
    total_cost_usd: number;
    progress_current: number;
    progress_total: number;
    error_message: string | null;
    created_at: string;
    duration_seconds: number | null;
}

export interface Comparison {
    id: string;
    name: string;
    spec_name: string;
    provider_ids: string[];
    status: string;
    winner_provider_id: string | null;
    comparison_summary: Record<string, any>;
    created_at: string;
    completed_at: string | null;
}

export interface TestResult {
    id: number;
    test_case_id: string;
    test_case_name: string;
    input_prompt: string;
    expected_output: string;
    actual_output: string;
    model_id: string;
    latency_ms: number;
    tokens_in: number;
    tokens_out: number;
    estimated_cost_usd: number;
    overall_passed: boolean;
    assertions: any[];
    scores: Record<string, number>;
}

export interface AnalyticsOverview {
    total_runs: number;
    total_cost: number;
    avg_pass_rate: number;
    avg_latency: number | null;
    top_provider: string | null;
    recent_regression: boolean;
}

export interface TrendDataPoint {
    date: string;
    pass_rate: number;
    runs: number;
    avg_latency: number | null;
    cost: number;
}

export interface LatencyDistribution {
    provider_id: string;
    provider_name: string;
    histogram: { bucket: string; count: number }[];
    percentiles: { p50: number; p75: number; p90: number; p95: number; p99: number };
}

export interface CostDataPoint {
    date: string;
    total_cost: number;
    by_provider: Record<string, number>;
}

export interface Regression {
    spec_name: string;
    provider_id: string;
    previous_pass_rate: number;
    current_pass_rate: number;
    drop_percentage: number;
    run_id: string;
}

export interface Dataset {
    id: string;
    name: string;
    description: string;
    version: number;
    tags: string[];
    total_cases: number;
    is_golden: boolean;
    created_at: string;
    updated_at: string;
}

export interface DatasetCase {
    id: number;
    dataset_id: string;
    case_index: number;
    input_prompt: string;
    expected_output: string;
    context: string[];
    assertions: { type: string; value: string }[];
    tags: string[];
    created_at: string;
}

export interface SpecVersion {
    id: number;
    spec_name: string;
    version: number;
    content: string;
    change_summary: string;
    system_prompt_hash: string;
    run_ids: string[];
    created_at: string;
}

export interface PromptIteration {
    id: string;
    spec_name: string;
    name: string;
    version_a: number;
    version_b: number;
    provider_id: string;
    run_id_a: string | null;
    run_id_b: string | null;
    status: string;
    winner: string | null;
    summary: Record<string, any>;
    ai_suggestions: string | null;
    created_at: string;
    completed_at: string | null;
}

export interface DatasetVersion {
    id: number;
    dataset_id: string;
    version: number;
    change_type: string;
    change_summary: string;
    total_cases: number;
    created_at: string;
}

export interface LlmSchedule {
    id: string;
    name: string;
    dataset_id: string;
    dataset_name?: string;
    provider_ids: string[];
    cron_expression: string;
    timezone: string;
    enabled: boolean;
    notify_on_regression: boolean;
    regression_threshold: number;
    last_run_at: string | null;
    next_run_at: string | null;
    total_executions: number;
    created_at: string;
}

export interface LlmScheduleExecution {
    id: number;
    schedule_id: string;
    status: string;
    run_ids: string[];
    dataset_version: number;
    error_message: string | null;
    started_at: string | null;
    completed_at: string | null;
    created_at: string;
}

export interface DatasetPerformance {
    dataset_id: string;
    dataset_name: string;
    is_golden: boolean;
    total_runs: number;
    avg_pass_rate: number;
    avg_latency_ms: number | null;
    total_cost: number;
    best_provider_id: string | null;
    best_provider_name: string | null;
}

export interface GoldenDashboardEntry {
    dataset_id: string;
    dataset_name: string;
    latest_pass_rate: number;
    trend: 'improving' | 'degrading' | 'stable';
    last_run_at: string | null;
    total_runs: number;
}
