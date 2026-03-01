export interface DbConnection {
    id: string;
    project_id: string;
    name: string;
    host: string;
    port: number;
    database: string;
    username: string;
    ssl_mode: string;
    schema_name: string;
    is_read_only: boolean;
    last_tested_at?: string;
    last_test_success?: boolean;
    last_test_error?: string;
    created_at: string;
    updated_at: string;
}

export interface DbTestRun {
    id: string;
    connection_id: string;
    project_id: string;
    spec_name?: string;
    run_type: string;
    status: string;
    current_stage?: string;
    stage_message?: string;
    total_checks: number;
    passed_checks: number;
    failed_checks: number;
    error_checks: number;
    critical_count: number;
    high_count: number;
    medium_count: number;
    low_count: number;
    info_count: number;
    ai_summary?: string;
    pass_rate: number;
    error_message?: string;
    created_at: string;
    started_at?: string;
    completed_at?: string;
    duration_seconds?: number;
}

export interface DbTestCheck {
    id: number;
    run_id: string;
    check_name: string;
    check_type: string;
    table_name?: string;
    column_name?: string;
    description?: string;
    sql_query: string;
    status: string;
    severity: string;
    expected_result?: string;
    actual_result?: string;
    row_count?: number;
    sample_data?: Record<string, unknown>[];
    error_message?: string;
    execution_time_ms?: number;
}

export interface SchemaFinding {
    severity: string;
    category: string;
    table_name?: string;
    column_name?: string;
    title: string;
    description: string;
    recommendation?: string;
}

export interface AiSuggestion {
    check_name: string;
    check_type: string;
    table_name: string;
    column_name: string;
    description: string;
    severity: string;
    sql_query: string;
    expected_result: string;
    approved?: boolean;
}

export interface DbSpec {
    name: string;
    path: string;
    content?: string;
    modified_at?: string;
}

export interface JobStatus {
    job_id: string;
    status: 'pending' | 'running' | 'completed' | 'failed';
    run_id?: string;
    result?: Record<string, unknown>;
    error?: string;
    stage_message?: string;
}

export type TabType = 'connections' | 'analyzer' | 'specs' | 'history' | 'dashboard';
