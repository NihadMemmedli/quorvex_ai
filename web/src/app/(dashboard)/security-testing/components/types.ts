export interface SecuritySpec {
    name: string;
    path: string;
    content?: string;
    modified_at?: string;
}

export interface SecurityScanRun {
    id: string;
    spec_name?: string;
    target_url: string;
    scan_type: string;
    status: string;
    total_findings: number;
    critical_count: number;
    high_count: number;
    medium_count: number;
    low_count: number;
    info_count: number;
    quick_scan_completed: boolean;
    nuclei_scan_completed: boolean;
    zap_scan_completed: boolean;
    current_stage?: string;
    stage_message?: string;
    error_message?: string;
    source_test_run_id?: string;
    created_at: string;
    started_at?: string;
    completed_at?: string;
    duration_seconds?: number;
}

export interface SecurityCapabilities {
    quick: { available: boolean; message: string };
    nuclei: { available: boolean; path?: string | null; message: string };
    zap: { available: boolean; version?: string | null; host: string; port: number; message: string; error?: string | null };
    defaults: { active_scan_level: string; security_scan_timeout: number; nuclei_timeout: number };
}

export interface SecurityTarget {
    url: string;
    host: string;
    sources: string[];
    endpoint_count: number;
    sample_endpoints: { method: string; url: string }[];
    latest_session_id?: string;
}

export interface CredentialOption {
    key: string;
    masked_value: string;
    source: string;
}

export interface SecurityFinding {
    id: number;
    scan_id: string;
    severity: string;
    finding_type: string;
    category: string;
    scanner: string;
    title: string;
    description: string;
    url: string;
    evidence?: string;
    remediation?: string;
    reference_urls?: string[];
    reference_urls_json?: string;
    template_id?: string;
    zap_alert_ref?: string;
    zap_cweid?: number;
    finding_hash: string;
    status: string;
    notes?: string;
    created_at: string;
}

export interface JobStatus {
    job_id: string;
    run_id?: string;
    status: 'pending' | 'running' | 'completed' | 'failed';
    stage?: string;
    current_stage?: string;
    message?: string;
    stage_message?: string;
    error?: string;
    error_message?: string;
    result?: Record<string, unknown>;
    quick_scan_completed?: boolean;
    nuclei_scan_completed?: boolean;
    zap_scan_completed?: boolean;
}

export interface FindingSummary {
    total: number;
    critical: number;
    high: number;
    medium: number;
    low: number;
    info: number;
    open: number;
    false_positive: number;
    fixed: number;
    accepted_risk: number;
}

export type TabType = 'scanner' | 'specs' | 'history' | 'findings';
