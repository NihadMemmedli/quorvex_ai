export interface TrendDataPoint {
    date: string;
    total_runs: number;
    passed: number;
    failed: number;
    pass_rate: number;
}

export interface TrendSummary {
    avg_pass_rate: number;
    total_runs: number;
    trend_direction: 'up' | 'down' | 'flat';
}

export interface PassRateTrendsResponse {
    data_points: TrendDataPoint[];
    summary: TrendSummary;
}

export interface FlakySpec {
    spec_name: string;
    flakiness_score: number;
    is_flaky: boolean;
    total_runs: number;
    passed: number;
    failed: number;
    recent_results: string[];
    is_quarantined: boolean;
}

export interface FlakeDetectionResponse {
    flaky_specs: FlakySpec[];
    total_flaky: number;
    threshold: number;
}

export interface FailureDistribution {
    defect: number;
    flaky: number;
    environment: number;
    timeout: number;
}

export interface RecentFailure {
    run_id: string;
    spec_name: string;
    classification: string;
    error_message: string;
    created_at: string;
}

export interface FailureClassificationResponse {
    distribution: FailureDistribution;
    recent_failures: RecentFailure[];
}

export interface SpecPerformance {
    spec_name: string;
    total_runs: number;
    passed: number;
    failed: number;
    pass_rate: number;
    last_run_at: string;
    trend: 'up' | 'down' | 'flat';
}

export interface SpecPerformanceResponse {
    specs: SpecPerformance[];
}

export interface TagCount {
    tag: string;
    count: number;
}

export interface CoverageOverview {
    total_specs: number;
    total_test_files: number;
    specs_with_tests: number;
    specs_run_at_least_once: number;
    run_coverage_percent: number;
    tags_distribution: TagCount[];
}
