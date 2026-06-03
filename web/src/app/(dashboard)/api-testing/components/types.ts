export interface GeneratedTestRef {
    path: string;
    name: string;
    test_count: number;
}

export interface ApiSpec {
    name: string;
    path: string;
    spec_type: string;
    has_generated_test: boolean;
    generated_test_path?: string;
    generated_tests?: GeneratedTestRef[];
    test_count?: number;
    file_count?: number;
    defined_cases?: number;
    content?: string;
    folder?: string;
    last_run_status?: 'passed' | 'failed' | null;
    last_run_at?: string | null;
    base_url?: string;
    tags?: string[];
    modified_at?: string;
}

export interface GeneratedTest {
    name: string;
    path: string;
    size_bytes: number;
    modified_at: string;
    source_spec?: string;
    source_spec_path?: string;
    test_count?: number;
    folder?: string;
    last_run_status?: 'passed' | 'failed' | 'running' | null;
    last_run_at?: string | null;
}

export interface GeneratedTestsSummary {
    total_files: number;
    total_tests: number;
    passed: number;
    failed: number;
    not_run: number;
}

export interface JobResult {
    test_path?: string;
    files?: string[];
    plan_path?: string | null;
    evidence_paths?: string[];
    spec_paths?: string[];
    test_paths?: string[];
    base_url?: string | null;
    needs_input?: boolean;
    missing_fields?: string[];
    matched_operations?: number;
    executed_operations?: number;
    blocked_operations?: Array<Record<string, unknown>>;
    failed_operations?: Array<Record<string, unknown>>;
    skipped_operations?: number;
    chunk_count?: number;
    recommended_mode?: 'evidence_specs' | 'plan_only' | 'tests_only' | 'plan_and_tests';
    recommended_next_action?: string;
    warnings?: string[];
    diagnostics?: Record<string, unknown>;
    run_id?: string;
    run_dir?: string;
    passed?: boolean;
    healed?: boolean;
    healing_attempts?: number;
    exit_code?: number;
    final_status?: string;
    first_failure?: string;
}

export interface JobStatus {
    job_id: string;
    status: 'running' | 'completed' | 'failed' | 'needs_input';
    stage?: string;
    message?: string;
    result?: JobResult;
    type?: string;
}

export interface ApiTestRun {
    id: string;
    spec_name: string;
    status: string;
    test_type: string;
    created_at: string;
    started_at?: string;
    completed_at?: string;
    project_id?: string;
    error_message?: string;
    current_stage?: string;
    stage_message?: string;
    healing_attempt?: number;
    browser?: string;
}

// ========== Run Detail Types ==========

export interface TestResultError {
    message: string;
    stack?: string;
    category: string;
}

export interface TestResultDetail {
    title: string;
    full_title: string;
    status: 'passed' | 'failed' | 'skipped' | 'timedOut' | 'flaky';
    duration_ms: number;
    error?: TestResultError;
    retry: number;
    file?: string;
}

export interface TestResultsSummary {
    total: number;
    passed: number;
    failed: number;
    skipped: number;
    flaky: number;
}

export interface HealingAttempt {
    attempt: number;
    error_before: string;
    code_changed: boolean;
    result: string;
}

export interface ApiRunDetail {
    id: string;
    spec_name: string;
    status: string;
    test_type: string;
    created_at?: string;
    started_at?: string;
    completed_at?: string;
    project_id?: string;
    error_message?: string;
    current_stage?: string;
    stage_message?: string;
    healing_attempt?: number;
    test_results?: {
        summary: TestResultsSummary;
        duration_ms: number;
        tests: TestResultDetail[];
        error_summary: Record<string, number>;
        first_failure?: string;
    };
    generated_code?: string;
    spec_content?: string;
    execution_log?: string;
    validation?: Record<string, unknown>;
    healing_history?: HealingAttempt[];
}

export interface ImportHistoryRecord {
    id: string;
    job_id?: string | null;
    source_type: 'url' | 'file';
    source_url?: string;
    source_filename?: string;
    feature_filter?: string;
    method_filter?: string[];
    mode?: 'evidence_specs' | 'plan_only' | 'tests_only' | 'plan_and_tests';
    status: 'running' | 'completed' | 'failed' | 'needs_input';
    base_url?: string | null;
    needs_input?: boolean;
    missing_fields?: string[];
    files_generated: number;
    generated_paths: string[];
    plan_path?: string | null;
    evidence_paths?: string[];
    spec_paths?: string[];
    test_paths?: string[];
    matched_operations?: number;
    executed_operations?: number;
    blocked_operations?: Array<Record<string, unknown>>;
    failed_operations?: Array<Record<string, unknown>>;
    skipped_operations?: number;
    chunk_count?: number;
    recommended_mode?: 'evidence_specs' | 'plan_only' | 'tests_only' | 'plan_and_tests';
    recommended_next_action?: string;
    warnings?: string[];
    diagnostics?: Record<string, unknown>;
    error_message?: string;
    created_at: string;
    completed_at?: string;
}

export interface ApiSpecsSummary {
    total_specs: number;
    with_tests: number;
    passed: number;
    failed: number;
    not_run: number;
    no_tests: number;
    total_defined_cases: number;
    total_generated_tests: number;
    coverage_pct: number;
}

export interface ApiSpecsResponse {
    items: ApiSpec[];
    total: number;
    has_more: boolean;
    folders: string[];
    summary: ApiSpecsSummary;
}

export type ApiSpecSortOption = 'name' | 'status' | 'last_run' | 'test_count' | 'modified';
export type ApiSpecStatusFilter = 'all' | 'passed' | 'failed' | 'not_run' | 'no_tests';

export type TabType = 'specs' | 'generated' | 'import' | 'history';

export const API_SPEC_TEMPLATE = `# Test: API Test Name

## Type: API
## Base URL: https://api.example.com
## Auth: Bearer {{API_TOKEN}}

## Steps
1. GET /health
2. Verify response status is 200
3. POST /users with body {"name": "John", "email": "john@example.com"}
4. Verify response status is 201
5. Verify response body has property "id"
6. GET /users
7. Verify response status is 200

## Expected Outcome
- Health endpoint returns 200
- User creation returns 201 with ID
- User list is accessible
`;
