export interface LoadSpec {
    name: string;
    path: string;
    content?: string;
    has_script?: boolean;
    script_path?: string;
    modified_at?: string;
}

export interface K6Script {
    name: string;
    path: string;
    size_bytes: number;
    modified_at: string;
    spec_name?: string;
}

export interface LoadTestRun {
    id: string;
    spec_name?: string;
    script_path?: string;
    status: string;
    vus?: number;
    duration?: string;
    duration_seconds?: number;
    total_requests?: number;
    failed_requests?: number;
    avg_response_time_ms?: number;
    p50_response_time_ms?: number;
    p95_response_time_ms?: number;
    p99_response_time_ms?: number;
    max_response_time_ms?: number;
    min_response_time_ms?: number;
    requests_per_second?: number;
    peak_rps?: number;
    peak_vus?: number;
    data_received_bytes?: number;
    data_sent_bytes?: number;
    error_rate?: number;
    http_status_counts?: Record<string, number>;
    thresholds_passed?: boolean;
    thresholds_detail?: Array<{ name: string; value: number; limit: number; passed: boolean }>;
    checks?: Array<{ name: string; passes: number; fails: number; rate: number }>;
    metrics_summary?: {
        per_endpoint?: Array<{
            endpoint: string;
            count: number;
            avg_ms: number;
            p95_ms: number;
            error_rate: number;
        }>;
    };
    current_stage?: string;
    error_message?: string;
    worker_count?: number;
    created_at: string;
    started_at?: string;
    completed_at?: string;
    ai_analysis?: LoadTestAnalysis;
    project_id?: string;
}

export interface TimeseriesPoint {
    timestamp: string;
    response_time_avg: number;
    response_time_p95: number;
    throughput: number;
    vus: number;
    error_rate: number;
}

export interface TimeseriesData {
    run_id: string;
    timeseries: TimeseriesPoint[];
    point_count: number;
}

export interface JobStatus {
    job_id: string;
    status: 'pending' | 'running' | 'completed' | 'failed';
    stage?: string;
    message?: string;
    result?: Record<string, unknown>;
    execution_mode?: string;
    worker_count?: number;
}

export type TabType = 'overview' | 'scenarios' | 'scripts' | 'history';

export interface K6ExecutionStatus {
    mode: 'distributed' | 'local';
    workers_connected: number;
    queue_length: number;
    running_tasks: number;
    load_test_active: boolean;
    active_run?: {
        run_id: string;
        started_at: number;
        vus: number | null;
        duration: string | null;
    };
}

export interface ComparisonDelta {
    value: number;
    pct: number | null;
    direction: 'up' | 'down' | 'same';
    improved?: boolean;
}

export interface ComparisonData {
    run_a: LoadTestRun;
    run_b: LoadTestRun;
    run_a_timeseries: Array<TimeseriesPoint & { elapsed_seconds: number }>;
    run_b_timeseries: Array<TimeseriesPoint & { elapsed_seconds: number }>;
    deltas: Record<string, ComparisonDelta>;
}

export interface SystemLimits {
    k6_max_vus: number;
    k6_max_duration: string;
    k6_timeout_seconds: number;
    max_browser_instances: number;
    browser_slots_available: number;
    browser_slots_running: number;
    execution_mode: 'local' | 'distributed';
    workers_connected: number;
    effective_max_vus: number;
    load_test_lock_active: boolean;
    lock_ttl_seconds: number;
}

export interface TrendData {
    run_id: string;
    spec_name: string;
    created_at: string;
    status: string;
    p95_response_time_ms: number | null;
    avg_response_time_ms: number | null;
    requests_per_second: number | null;
    error_rate: number | null;
    total_requests: number | null;
    vus: number | null;
}

export interface LoadTestAnalysis {
    summary: string;
    performance_grade: string;
    bottlenecks: Array<{
        area: string;
        issue: string;
        severity: string;
        recommendation: string;
    }>;
    anomalies: Array<{
        metric: string;
        observation: string;
        possible_cause: string;
    }>;
    recommendations: Array<{
        priority: number | string;
        title: string;
        description: string;
        expected_impact: string;
    }>;
    capacity_estimate: {
        current_max_rps: number;
        estimated_breaking_point_vus: number;
        confidence: string;
    };
}

export interface DashboardData {
    total_runs: number;
    completed_runs: number;
    failed_runs: number;
    pass_rate: number;
    avg_p95_ms: number;
    avg_rps: number;
    total_requests_all_time: number;
    recent_runs: LoadTestRun[];
    p95_trend: Array<{ date: string; p95: number; count: number }>;
    top_slow_endpoints: Array<{ endpoint: string; avg_p95_ms: number; occurrence_count: number }>;
}

export const LOAD_SPEC_TEMPLATE = `# Test: Load Test Name

## Type: Load
## Target URL: https://example.com

## Description
Describe the load test scenario.

## Endpoints
- GET /api/health
- GET /api/users
- POST /api/login with body {"email": "test@example.com", "password": "pass"}

## Load Profile
- Virtual Users: 10
- Duration: 30s
- Ramp Up: 5s

## Thresholds
- http_req_duration p(95) < 500ms
- http_req_failed rate < 0.01
`;
