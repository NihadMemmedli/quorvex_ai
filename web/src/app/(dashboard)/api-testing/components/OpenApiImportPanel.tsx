'use client';

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
    AlertCircle,
    CheckCircle,
    ChevronDown,
    ChevronRight,
    Clock,
    FileText,
    Globe,
    Loader2,
    RefreshCw,
    Settings,
    Upload,
    X,
} from 'lucide-react';
import { API_BASE, withProjectBody, withProjectQuery } from '@/lib/api';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { EmptyState } from '@/components/ui/empty-state';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
} from '@/components/ui/table';
import { JobStatus, ImportHistoryRecord } from './types';

const OPENAPI_IMPORT_MODES = ['evidence_specs', 'plan_only', 'tests_only', 'plan_and_tests'] as const;
type OpenApiImportMode = typeof OPENAPI_IMPORT_MODES[number];
const DEFAULT_OPENAPI_IMPORT_MODE: OpenApiImportMode = 'plan_and_tests';
const HISTORY_PAGE_SIZE = 10;

interface OpenApiImportPanelProps {
    projectId: string;
    activeJobs: Record<string, JobStatus>;
    setActiveJobs: React.Dispatch<React.SetStateAction<Record<string, JobStatus>>>;
    setMessage: (msg: { type: 'success' | 'error'; text: string } | null) => void;
    pollJob: (jobId: string, onComplete?: () => void) => void;
    canEdit: boolean;
}

interface ImportFormProps {
    importUrl: string;
    serverUrl: string;
    importFile: File | null;
    featureFilter: string;
    importMode: 'url' | 'file';
    isImporting: boolean;
    submitAttempted: boolean;
    serverInputRef: React.RefObject<HTMLInputElement | null>;
    onImportUrlChange: (value: string) => void;
    onServerUrlChange: (value: string) => void;
    onFileChange: (file: File | null) => void;
    onFeatureFilterChange: (value: string) => void;
    onImportModeChange: (value: 'url' | 'file') => void;
    onSubmit: () => void;
    canEdit: boolean;
}

function timeAgo(dateStr: string): string {
    const now = Date.now();
    const then = new Date(dateStr).getTime();
    const diff = now - then;
    const seconds = Math.floor(diff / 1000);
    if (seconds < 60) return 'just now';
    const minutes = Math.floor(seconds / 60);
    if (minutes < 60) return `${minutes}m ago`;
    const hours = Math.floor(minutes / 60);
    if (hours < 24) return `${hours}h ago`;
    const days = Math.floor(hours / 24);
    return `${days}d ago`;
}

function formatDateTime(value?: string | null): string {
    if (!value) return '-';
    return new Date(value).toLocaleString();
}

function normalizeImportMode(mode: unknown): OpenApiImportMode {
    return typeof mode === 'string' && (OPENAPI_IMPORT_MODES as readonly string[]).includes(mode)
        ? mode as OpenApiImportMode
        : DEFAULT_OPENAPI_IMPORT_MODE;
}

function modeLabel(mode: unknown): string {
    const labels: Record<OpenApiImportMode, string> = {
        evidence_specs: 'Evidence + specs',
        plan_only: 'Plan only',
        tests_only: 'Tests only',
        plan_and_tests: 'Plan + tests',
    };
    return labels[normalizeImportMode(mode)];
}

function statusLabel(status: string): string {
    const labels: Record<string, string> = {
        running: 'Running',
        completed: 'Completed',
        failed: 'Failed',
        needs_input: 'Needs input',
    };
    return labels[status] || 'Failed';
}

function inferServerUrlFromSpecUrl(value: string): string {
    try {
        const url = new URL(value.trim());
        const path = url.pathname.replace(/\/+$/, '').toLowerCase();
        if (
            path.endsWith('/docs')
            || path.endsWith('/redoc')
            || path.endsWith('/openapi.json')
            || path.endsWith('/swagger.json')
            || path.endsWith('/api-docs')
            || path.endsWith('/swagger/v1/swagger.json')
        ) {
            return url.origin;
        }
    } catch {
        return '';
    }
    return '';
}

function hasValidUrl(value?: string | null): boolean {
    if (!value) return false;
    try {
        new URL(value);
        return true;
    } catch {
        return false;
    }
}

function fileName(path: string): string {
    return path.split('/').pop() || path;
}

function operationSummary(item: Record<string, unknown>): string {
    const method = String(item.method || '').toUpperCase();
    const path = String(item.path || '');
    const reason = String(item.reason || item.error || 'missing input');
    return `${method} ${path} (${reason})`.trim();
}

function StatusBadge({ status }: { status: string }) {
    const styles: Record<string, React.CSSProperties> = {
        completed: { background: 'var(--success-muted)', color: 'var(--success)', borderColor: 'transparent' },
        running: { background: 'var(--primary-glow)', color: 'var(--primary)', borderColor: 'transparent' },
        needs_input: { background: 'var(--warning-muted)', color: 'var(--warning)', borderColor: 'transparent' },
        failed: { background: 'var(--danger-muted)', color: 'var(--danger)', borderColor: 'transparent' },
    };
    return (
        <Badge
            variant="outline"
            style={{
                ...(styles[status] || styles.failed),
                display: 'inline-flex',
                alignItems: 'center',
                justifyContent: 'center',
                minHeight: '1.5rem',
                minWidth: '5.5rem',
                padding: '0 0.65rem',
                lineHeight: 1,
                whiteSpace: 'nowrap',
            }}
        >
            {statusLabel(status)}
        </Badge>
    );
}

function ImportForm({
    importUrl,
    serverUrl,
    importFile,
    featureFilter,
    importMode,
    isImporting,
    submitAttempted,
    serverInputRef,
    onImportUrlChange,
    onServerUrlChange,
    onFileChange,
    onFeatureFilterChange,
    onImportModeChange,
    onSubmit,
    canEdit,
}: ImportFormProps) {
    const sourceMissing = submitAttempted && (importMode === 'url' ? !importUrl.trim() : !importFile);
    const serverMissing = submitAttempted && !serverUrl.trim();
    const disabled = !canEdit || isImporting || !serverUrl.trim() || (importMode === 'url' ? !importUrl.trim() : !importFile);
    const sourceOptions: Array<{ value: 'url' | 'file'; label: string; icon: React.ReactNode }> = [
        { value: 'url', label: 'From URL', icon: <Globe size={14} aria-hidden="true" /> },
        { value: 'file', label: 'Upload File', icon: <FileText size={14} aria-hidden="true" /> },
    ];

    return (
        <section style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 'var(--radius)', padding: '1.5rem' }}>
            <h3 style={{ fontSize: '1rem', fontWeight: 600, marginBottom: '1rem' }}>Import OpenAPI / Swagger Specification</h3>

            <div
                role="group"
                aria-label="Import source"
                style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: '0.125rem',
                    maxWidth: '100%',
                    marginBottom: '1.25rem',
                    padding: '0.1875rem',
                    border: '1px solid var(--border)',
                    borderRadius: '8px',
                    background: 'var(--background)',
                }}
            >
                {sourceOptions.map(option => {
                    const selected = importMode === option.value;
                    return (
                        <button
                            key={option.value}
                            type="button"
                            aria-pressed={selected}
                            onClick={() => onImportModeChange(option.value)}
                            disabled={!canEdit || isImporting}
                            onMouseEnter={event => {
                                if (!selected) event.currentTarget.style.background = 'var(--surface-hover)';
                            }}
                            onMouseLeave={event => {
                                if (!selected) event.currentTarget.style.background = 'transparent';
                            }}
                            onFocus={event => {
                                event.currentTarget.style.outline = '2px solid var(--primary)';
                            }}
                            onBlur={event => {
                                event.currentTarget.style.outline = 'none';
                            }}
                            style={{
                                display: 'inline-flex',
                                alignItems: 'center',
                                justifyContent: 'center',
                                flex: '0 0 auto',
                                gap: '0.375rem',
                                height: '2rem',
                                minWidth: '7.25rem',
                                padding: '0 0.75rem',
                                border: 0,
                                borderRadius: '6px',
                                background: selected ? 'var(--primary)' : 'transparent',
                                color: selected ? '#fff' : 'var(--text-secondary)',
                                fontSize: '0.875rem',
                                fontWeight: 600,
                                lineHeight: 1,
                                boxShadow: selected ? 'var(--shadow-glow-sm)' : 'none',
                                opacity: isImporting ? 0.6 : 1,
                                pointerEvents: isImporting ? 'none' : 'auto',
                                transition: 'background 0.16s var(--ease-smooth), color 0.16s var(--ease-smooth), box-shadow 0.16s var(--ease-smooth)',
                                whiteSpace: 'nowrap',
                            }}
                        >
                            {option.icon}
                            {option.label}
                        </button>
                    );
                })}
            </div>

            {importMode === 'url' ? (
                <div style={{ marginBottom: '1rem' }}>
                    <Label htmlFor="openapi-spec-url">OpenAPI Spec URL</Label>
                    <Input
                        id="openapi-spec-url"
                        type="url"
                        placeholder="https://api.example.com/openapi.json"
                        value={importUrl}
                        onChange={e => onImportUrlChange(e.target.value)}
                        disabled={!canEdit || isImporting}
                        aria-invalid={sourceMissing}
                        aria-describedby={sourceMissing ? 'openapi-spec-url-error' : undefined}
                        style={{ marginTop: '0.4rem' }}
                    />
                    {sourceMissing && <p id="openapi-spec-url-error" style={{ color: 'var(--danger)', fontSize: '0.75rem', marginTop: '0.35rem' }}>Enter an OpenAPI spec URL.</p>}
                </div>
            ) : (
                <div style={{ marginBottom: '1rem' }}>
                    <Label htmlFor="openapi-spec-file">Upload JSON or YAML File</Label>
                    <Input
                        id="openapi-spec-file"
                        type="file"
                        accept=".json,.yaml,.yml"
                        onChange={e => onFileChange(e.target.files?.[0] || null)}
                        disabled={!canEdit || isImporting}
                        aria-invalid={sourceMissing}
                        aria-describedby={sourceMissing ? 'openapi-spec-file-error' : undefined}
                        style={{ marginTop: '0.4rem' }}
                    />
                    {sourceMissing && <p id="openapi-spec-file-error" style={{ color: 'var(--danger)', fontSize: '0.75rem', marginTop: '0.35rem' }}>Choose a JSON or YAML OpenAPI file.</p>}
                </div>
            )}

            <div style={{ marginBottom: '1rem' }}>
                <Label htmlFor="openapi-server-url">API Server URL</Label>
                <Input
                    id="openapi-server-url"
                    ref={serverInputRef}
                    type="url"
                    placeholder="http://localhost:8001"
                    value={serverUrl}
                    onChange={e => onServerUrlChange(e.target.value)}
                    disabled={!canEdit || isImporting}
                    aria-invalid={serverMissing}
                    aria-describedby="openapi-server-url-help"
                    style={{ marginTop: '0.4rem' }}
                />
                <p id="openapi-server-url-help" style={{ fontSize: '0.75rem', color: serverMissing ? 'var(--danger)' : 'var(--text-secondary)', marginTop: '0.35rem' }}>
                    {serverMissing ? 'Enter the target server URL before importing.' : 'Used as the target server for generated Playwright API tests.'}
                </p>
            </div>

            <div style={{ marginBottom: '1.25rem' }}>
                <Label htmlFor="openapi-feature-filter">Feature Filter (optional)</Label>
                <Input
                    id="openapi-feature-filter"
                    type="text"
                    placeholder="e.g., users, auth, orders"
                    value={featureFilter}
                    onChange={e => onFeatureFilterChange(e.target.value)}
                    disabled={!canEdit || isImporting}
                    style={{ marginTop: '0.4rem' }}
                />
                <p style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', marginTop: '0.35rem' }}>
                    Comma-separated tags or path prefixes to focus on specific API areas.
                </p>
            </div>

            <Button type="button" onClick={onSubmit} disabled={disabled} aria-busy={isImporting}>
                {isImporting ? <Loader2 size={16} className="animate-spin" /> : <Upload size={16} />}
                {isImporting ? 'Starting import...' : 'Import & Generate Tests'}
            </Button>
        </section>
    );
}

function ImportJobsList({
    jobs,
    onDismiss,
}: {
    jobs: Array<[string, JobStatus]>;
    onDismiss: (jobId: string) => void;
}) {
    if (!jobs.length) return null;

    return (
        <section style={{ marginTop: '1rem' }}>
            <h4 style={{ fontSize: '0.875rem', fontWeight: 600, marginBottom: '0.5rem' }}>Import Jobs</h4>
            <div style={{ display: 'grid', gap: '0.5rem' }}>
                {jobs.map(([id, job]) => (
                    <div
                        key={id}
                        style={{
                            padding: '0.75rem',
                            background: 'var(--surface)',
                            border: '1px solid var(--border)',
                            borderRadius: 'var(--radius)',
                            display: 'grid',
                            gridTemplateColumns: 'auto minmax(0, 1fr) auto auto',
                            alignItems: 'center',
                            gap: '0.75rem',
                        }}
                    >
                        {job.status === 'running' ? (
                            <Loader2 size={16} style={{ color: 'var(--primary)' }} className="animate-spin" />
                        ) : job.status === 'completed' ? (
                            <CheckCircle size={16} style={{ color: 'var(--success)' }} />
                        ) : (
                            <AlertCircle size={16} style={{ color: job.status === 'needs_input' ? 'var(--warning)' : 'var(--danger)' }} />
                        )}
                        <div style={{ minWidth: 0 }}>
                            <div style={{ fontSize: '0.8rem', fontWeight: 500, overflowWrap: 'anywhere' }}>{job.message}</div>
                            {typeof job.result?.matched_operations === 'number' && (
                                <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', marginTop: '0.25rem' }}>
                                    Matched {job.result.matched_operations} operation(s)
                                    {typeof job.result.executed_operations === 'number' ? `, executed ${job.result.executed_operations}` : ''}
                                    {typeof job.result.chunk_count === 'number' ? ` across ${job.result.chunk_count} chunk(s)` : ''}
                                </div>
                            )}
                        </div>
                        <StatusBadge status={job.status} />
                        {job.status !== 'running' && (
                            <Button type="button" variant="ghost" size="icon" aria-label="Dismiss import job" onClick={() => onDismiss(id)}>
                                <X size={14} />
                            </Button>
                        )}
                    </div>
                ))}
            </div>
        </section>
    );
}

function ArtifactGroup({
    title,
    paths,
    onGenerateSpec,
    generatingSpecs,
}: {
    title: string;
    paths: string[];
    onGenerateSpec?: (path: string) => void;
    generatingSpecs: Set<string>;
}) {
    if (!paths.length) return null;
    return (
        <div>
            <div style={{ fontSize: '0.72rem', color: 'var(--text-secondary)', fontWeight: 600, marginBottom: '0.25rem' }}>{title}</div>
            <div style={{ display: 'grid', gap: '0.25rem' }}>
                {paths.map(path => {
                    const isGenerating = generatingSpecs.has(path);
                    return (
                        <div key={`${title}-${path}`} style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', minWidth: 0 }}>
                            <FileText size={12} style={{ color: 'var(--text-secondary)', flexShrink: 0 }} />
                            <span title={path} style={{ fontSize: '0.75rem', overflowWrap: 'anywhere', flex: 1 }}>{fileName(path)}</span>
                            {onGenerateSpec && (
                                <Button type="button" variant="outline" size="sm" disabled={isGenerating} onClick={() => onGenerateSpec(path)}>
                                    {isGenerating && <Loader2 size={12} className="animate-spin" />}
                                    Generate tests
                                </Button>
                            )}
                        </div>
                    );
                })}
            </div>
        </div>
    );
}

function DetailBlock({ title, children }: { title: string; children: React.ReactNode }) {
    return (
        <div style={{ minWidth: 0 }}>
            <div style={{ fontSize: '0.72rem', color: 'var(--text-secondary)', fontWeight: 600, marginBottom: '0.25rem' }}>{title}</div>
            <div style={{ fontSize: '0.75rem', color: 'var(--text-primary)', overflowWrap: 'anywhere' }}>{children}</div>
        </div>
    );
}

function ImportHistoryTable({
    history,
    historyTotal,
    historyOffset,
    historyLoading,
    historyError,
    expandedRows,
    generatingSpecs,
    onRefresh,
    onLoadMore,
    onToggleRow,
    onUseSettings,
    onReimport,
    onGenerateSpec,
    canEdit,
}: {
    history: ImportHistoryRecord[];
    historyTotal: number;
    historyOffset: number;
    historyLoading: boolean;
    historyError: string | null;
    expandedRows: Set<string>;
    generatingSpecs: Set<string>;
    onRefresh: () => void;
    onLoadMore: () => void;
    onToggleRow: (id: string) => void;
    onUseSettings: (record: ImportHistoryRecord) => void;
    onReimport: (record: ImportHistoryRecord) => void;
    onGenerateSpec: (specPath: string) => void;
    canEdit: boolean;
}) {
    if (history.length === 0 && !historyLoading) {
        return (
            <section style={{ marginTop: '1.5rem' }}>
                <HistoryHeader historyTotal={historyTotal} historyLoading={historyLoading} onRefresh={onRefresh} />
                {historyError && <HistoryError message={historyError} />}
                <EmptyState
                    icon={<Clock size={24} />}
                    title={historyError ? 'Import history unavailable' : 'No imports yet'}
                    description={historyError ? 'The API Testing page can still be used.' : 'Import an OpenAPI spec above to create generated artifacts.'}
                />
            </section>
        );
    }

    return (
        <section style={{ marginTop: '1.5rem' }}>
            <HistoryHeader historyTotal={historyTotal} historyLoading={historyLoading} onRefresh={onRefresh} />
            {historyError && <HistoryError message={historyError} />}
            <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 'var(--radius)', overflow: 'hidden' }}>
                <Table style={{ minWidth: '940px', tableLayout: 'fixed' }}>
                    <TableHeader>
                        <TableRow>
                            <TableHead style={{ width: 185 }}>Source</TableHead>
                            <TableHead style={{ width: 115 }}>Mode / Filter</TableHead>
                            <TableHead style={{ width: 95 }}>Status</TableHead>
                            <TableHead style={{ width: 80 }}>Generated</TableHead>
                            <TableHead style={{ width: 185 }}>Next action</TableHead>
                            <TableHead style={{ width: 85 }}>Created</TableHead>
                            <TableHead style={{ width: 85 }}>Completed</TableHead>
                            <TableHead style={{ width: 110 }}>Actions</TableHead>
                        </TableRow>
                    </TableHeader>
                    <TableBody>
                        {history.map(record => {
                            const isExpanded = expandedRows.has(record.id);
                            const specs = record.spec_paths || [];
                            const tests = record.test_paths || record.generated_paths || [];
                            const evidence = record.evidence_paths || [];
                            const plan = record.plan_path ? [record.plan_path] : [];
                            const hasDiagnostics = Boolean(
                                record.error_message
                                || record.missing_fields?.length
                                || record.failed_operations?.length
                                || record.blocked_operations?.length
                                || record.warnings?.length
                                || (record.diagnostics && Object.keys(record.diagnostics).length)
                            );
                            const hasDetails = plan.length || evidence.length || specs.length || tests.length || hasDiagnostics;
                            const useSettings = record.status === 'needs_input' || !hasValidUrl(record.base_url);
                            const source = record.source_type === 'url' ? record.source_url : record.source_filename;
                            const nextAction = record.error_message
                                || (record.needs_input ? 'Enter API Server URL and re-import.' : record.recommended_next_action)
                                || '-';

                            return (
                                <React.Fragment key={record.id}>
                                    <TableRow>
                                        <TableCell>
                                            <div style={{ display: 'flex', gap: '0.45rem', minWidth: 0 }}>
                                                {record.source_type === 'url' ? <Globe size={14} style={{ color: 'var(--primary)', flexShrink: 0 }} /> : <FileText size={14} style={{ color: 'var(--text-secondary)', flexShrink: 0 }} />}
                                                <span title={source || ''} style={{ fontSize: '0.8rem', overflowWrap: 'anywhere' }}>{source || 'Uploaded file'}</span>
                                            </div>
                                        </TableCell>
                                        <TableCell>
                                            <div style={{ fontSize: '0.8rem' }}>{modeLabel(record.mode)}</div>
                                            <div style={{ fontSize: '0.72rem', color: 'var(--text-secondary)', marginTop: '0.15rem', overflowWrap: 'anywhere' }}>
                                                {record.feature_filter || 'All features'}
                                                {record.method_filter?.length ? ` / ${record.method_filter.join(', ')}` : ''}
                                            </div>
                                        </TableCell>
                                        <TableCell>
                                            <div style={{ display: 'flex', justifyContent: 'center' }}>
                                                <StatusBadge status={record.status} />
                                            </div>
                                        </TableCell>
                                        <TableCell>
                                            <div style={{ fontSize: '0.8rem', fontVariantNumeric: 'tabular-nums' }}>{specs.length} specs</div>
                                            <div style={{ fontSize: '0.72rem', color: 'var(--text-secondary)', fontVariantNumeric: 'tabular-nums' }}>{tests.length} tests</div>
                                        </TableCell>
                                        <TableCell>
                                            <div title={nextAction} style={{ fontSize: '0.78rem', color: 'var(--text-secondary)', whiteSpace: 'normal', overflowWrap: 'anywhere', lineHeight: 1.45 }}>
                                                {nextAction}
                                            </div>
                                        </TableCell>
                                        <TableCell>
                                            <div style={{ fontSize: '0.78rem' }}>{record.created_at ? timeAgo(record.created_at) : '-'}</div>
                                            <div style={{ fontSize: '0.7rem', color: 'var(--text-secondary)', marginTop: '0.15rem' }}>{formatDateTime(record.created_at)}</div>
                                        </TableCell>
                                        <TableCell>
                                            <div style={{ fontSize: '0.7rem', color: 'var(--text-secondary)' }}>{formatDateTime(record.completed_at)}</div>
                                        </TableCell>
                                        <TableCell>
                                            <div style={{ display: 'flex', gap: '0.4rem', flexWrap: 'wrap' }}>
                                                {hasDetails && (
                                                    <Button type="button" variant="ghost" size="sm" onClick={() => onToggleRow(record.id)} title="Details">
                                                        Details {isExpanded ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
                                                    </Button>
                                                )}
                                                {canEdit && record.source_type === 'url' && record.source_url && (
                                                    useSettings ? (
                                                        <Button type="button" variant="outline" size="sm" onClick={() => onUseSettings(record)}>
                                                            <Settings size={13} /> Use settings
                                                        </Button>
                                                    ) : (
                                                        <Button type="button" variant="outline" size="sm" onClick={() => onReimport(record)}>
                                                            <RefreshCw size={13} /> Re-import
                                                        </Button>
                                                    )
                                                )}
                                            </div>
                                        </TableCell>
                                    </TableRow>
                                    {isExpanded && hasDetails && (
                                        <TableRow>
                                            <TableCell colSpan={8} style={{ background: 'var(--background)', padding: '1rem 1.25rem' }}>
                                                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: '1rem' }}>
                                                    <ArtifactGroup title="Plan" paths={plan} generatingSpecs={generatingSpecs} />
                                                    <ArtifactGroup title="Evidence" paths={evidence} generatingSpecs={generatingSpecs} />
                                                    <ArtifactGroup title="Specs" paths={specs} generatingSpecs={generatingSpecs} onGenerateSpec={canEdit ? onGenerateSpec : undefined} />
                                                    <ArtifactGroup title="Tests" paths={tests} generatingSpecs={generatingSpecs} />
                                                    <DetailBlock title="Run summary">
                                                        Matched {record.matched_operations ?? 0} operation(s)
                                                        {typeof record.executed_operations === 'number' ? `, executed ${record.executed_operations}` : ''}
                                                        {typeof record.skipped_operations === 'number' ? `, skipped ${record.skipped_operations}` : ''}
                                                        {typeof record.chunk_count === 'number' ? `, ${record.chunk_count} chunk(s)` : ''}
                                                    </DetailBlock>
                                                    {record.error_message && <DetailBlock title="Error">{record.error_message}</DetailBlock>}
                                                    {record.missing_fields?.length ? <DetailBlock title="Missing fields">{record.missing_fields.join(', ')}</DetailBlock> : null}
                                                    {record.warnings?.length ? <DetailBlock title="Warnings">{record.warnings.join(' ')}</DetailBlock> : null}
                                                    {record.blocked_operations?.length ? <DetailBlock title="Blocked operations">{record.blocked_operations.map(operationSummary).join('; ')}</DetailBlock> : null}
                                                    {record.failed_operations?.length ? <DetailBlock title="Failed operations">{record.failed_operations.map(operationSummary).join('; ')}</DetailBlock> : null}
                                                    {record.diagnostics && Object.keys(record.diagnostics).length > 0 && (
                                                        <DetailBlock title="Diagnostics">{JSON.stringify(record.diagnostics)}</DetailBlock>
                                                    )}
                                                </div>
                                            </TableCell>
                                        </TableRow>
                                    )}
                                </React.Fragment>
                            );
                        })}
                    </TableBody>
                </Table>
                {historyOffset < historyTotal && (
                    <div style={{ padding: '0.75rem', textAlign: 'center', borderTop: '1px solid var(--border)' }}>
                        <Button type="button" variant="outline" size="sm" onClick={onLoadMore} disabled={historyLoading}>
                            {historyLoading && <Loader2 size={13} className="animate-spin" />}
                            {historyLoading ? 'Loading...' : `Load More (${historyTotal - historyOffset} remaining)`}
                        </Button>
                    </div>
                )}
            </div>
        </section>
    );
}

function HistoryHeader({ historyTotal, historyLoading, onRefresh }: { historyTotal: number; historyLoading: boolean; onRefresh: () => void }) {
    return (
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.75rem', gap: '1rem', flexWrap: 'wrap' }}>
            <h4 style={{ fontSize: '0.875rem', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                <Clock size={14} /> Import History
                {historyTotal > 0 && <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', fontWeight: 400 }}>({historyTotal})</span>}
            </h4>
            <Button type="button" variant="outline" size="sm" onClick={onRefresh} disabled={historyLoading}>
                <RefreshCw size={13} className={historyLoading ? 'animate-spin' : undefined} /> Refresh
            </Button>
        </div>
    );
}

function HistoryError({ message }: { message: string }) {
    return (
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', padding: '0.75rem', marginBottom: '0.75rem', background: 'var(--danger-muted)', border: '1px solid var(--danger)', borderRadius: 'var(--radius)', color: 'var(--danger)', fontSize: '0.8rem' }}>
            <AlertCircle size={14} /> {message}
        </div>
    );
}

export default function OpenApiImportPanel({
    projectId,
    activeJobs,
    setActiveJobs,
    setMessage,
    pollJob,
    canEdit,
}: OpenApiImportPanelProps) {
    const [importUrl, setImportUrl] = useState('');
    const [serverUrl, setServerUrl] = useState('');
    const [serverUrlTouched, setServerUrlTouched] = useState(false);
    const [importFile, setImportFile] = useState<File | null>(null);
    const [featureFilter, setFeatureFilter] = useState('');
    const [importMode, setImportMode] = useState<'url' | 'file'>('url');
    const [isImporting, setIsImporting] = useState(false);
    const [submitAttempted, setSubmitAttempted] = useState(false);
    const [generatingSpecs, setGeneratingSpecs] = useState<Set<string>>(new Set());
    const serverInputRef = useRef<HTMLInputElement | null>(null);

    const [history, setHistory] = useState<ImportHistoryRecord[]>([]);
    const [historyTotal, setHistoryTotal] = useState(0);
    const [historyLoading, setHistoryLoading] = useState(false);
    const [historyError, setHistoryError] = useState<string | null>(null);
    const [historyOffset, setHistoryOffset] = useState(0);
    const [expandedRows, setExpandedRows] = useState<Set<string>>(new Set());

    const importJobs = useMemo(
        () => Object.entries(activeJobs).filter(([, job]) => job.type === 'openapi_import' && job.status === 'running'),
        [activeJobs],
    );

    const fetchHistory = useCallback(async (offset = 0, append = false) => {
        setHistoryLoading(true);
        setHistoryError(null);
        try {
            const res = await fetch(`${API_BASE}${withProjectQuery(`/api-testing/import-history?limit=${HISTORY_PAGE_SIZE}&offset=${offset}`, projectId)}`);
            const data = await res.json().catch(() => ({}));
            if (!res.ok) throw new Error(data.detail || data.error || `Import history failed with ${res.status}`);
            if (data.error) setHistoryError(data.error);
            const items = Array.isArray(data.items) ? data.items : [];
            setHistory(prev => append ? [...prev, ...items] : items);
            setHistoryTotal(Number.isFinite(data.total) ? data.total : items.length);
            setHistoryOffset(offset + items.length);
            setActiveJobs(prev => {
                const next = { ...prev };
                for (const [jobId, job] of Object.entries(next)) {
                    if (job.type === 'openapi_import' && job.status !== 'running') delete next[jobId];
                }
                return next;
            });
        } catch (err) {
            setHistoryError(err instanceof Error ? err.message : 'Failed to load import history');
            if (!append) {
                setHistory([]);
                setHistoryTotal(0);
                setHistoryOffset(0);
            }
        } finally {
            setHistoryLoading(false);
        }
    }, [projectId, setActiveJobs]);

    useEffect(() => {
        fetchHistory(0, false);
    }, [fetchHistory]);

    useEffect(() => {
        if (serverUrlTouched || importMode !== 'url') return;
        setServerUrl(inferServerUrlFromSpecUrl(importUrl));
    }, [importMode, importUrl, serverUrlTouched]);

    const toggleRow = (id: string) => {
        setExpandedRows(prev => {
            const next = new Set(prev);
            if (next.has(id)) next.delete(id); else next.add(id);
            return next;
        });
    };

    const readError = async (res: Response, fallback: string) => {
        const text = await res.text().catch(() => '');
        if (!text) return `${fallback} (${res.status})`;
        try {
            const parsed = JSON.parse(text);
            return parsed.detail || parsed.error || parsed.message || `${fallback} (${res.status})`;
        } catch {
            return text.slice(0, 500);
        }
    };

    const networkErrorText = (action: string, err: unknown) => {
        const detail = err instanceof Error && err.message ? ` ${err.message}` : '';
        return `${action}. Check that the backend is reachable at ${API_BASE}.${detail}`;
    };

    const dismissJob = (jobId: string) => {
        setActiveJobs(prev => {
            const next = { ...prev };
            delete next[jobId];
            return next;
        });
    };

    const startJob = (jobId: string, message: string) => {
        setActiveJobs(prev => ({
            ...prev,
            [jobId]: { job_id: jobId, status: 'running', message, type: 'openapi_import' },
        }));
        pollJob(jobId, () => {
            fetchHistory(0, false);
            setActiveJobs(prev => {
                const job = prev[jobId];
                if (!job || job.status === 'running') return prev;
                const next = { ...prev };
                delete next[jobId];
                return next;
            });
        });
    };

    const handleImport = async () => {
        if (!canEdit || isImporting) return;
        setSubmitAttempted(true);
        setMessage(null);
        if (!serverUrl.trim() || (importMode === 'url' ? !importUrl.trim() : !importFile)) return;

        setIsImporting(true);
        if (importMode === 'url') {
            try {
                const res = await fetch(`${API_BASE}${withProjectQuery('/api-testing/import-openapi', projectId)}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(withProjectBody({
                        url: importUrl,
                        base_url: serverUrl,
                        feature_filter: featureFilter || undefined,
                        mode: DEFAULT_OPENAPI_IMPORT_MODE,
                    }, projectId)),
                });
                if (res.ok) {
                    const data = await res.json();
                    startJob(data.job_id, data.message || 'OpenAPI import started');
                    setMessage({ type: 'success', text: 'OpenAPI import and test generation started' });
                } else {
                    setMessage({ type: 'error', text: await readError(res, 'Import failed') });
                }
            } catch (err) {
                setMessage({ type: 'error', text: networkErrorText('Failed to start import', err) });
            } finally {
                setIsImporting(false);
            }
            return;
        }

        const selectedFile = importFile;
        if (!selectedFile) return;

        const formData = new FormData();
        formData.append('file', selectedFile);
        const params = new URLSearchParams();
        params.set('project_id', projectId);
        params.set('mode', DEFAULT_OPENAPI_IMPORT_MODE);
        params.set('base_url', serverUrl);
        if (featureFilter) params.set('feature_filter', featureFilter);
        try {
            const res = await fetch(`${API_BASE}/api-testing/import-openapi-file?${params}`, {
                method: 'POST',
                body: formData,
            });
            if (res.ok) {
                const data = await res.json();
                startJob(data.job_id, data.message || 'OpenAPI file import started');
                setMessage({ type: 'success', text: 'OpenAPI file import and test generation started' });
            } else {
                setMessage({ type: 'error', text: await readError(res, 'Import failed') });
            }
        } catch (err) {
            setMessage({ type: 'error', text: networkErrorText('Failed to start file import', err) });
        } finally {
            setIsImporting(false);
        }
    };

    const handleUseSettings = (record: ImportHistoryRecord) => {
        if (!canEdit) return;
        if (record.source_type === 'url' && record.source_url) {
            setImportUrl(record.source_url);
            setServerUrl(record.base_url || inferServerUrlFromSpecUrl(record.source_url));
            setServerUrlTouched(Boolean(record.base_url));
            setImportMode('url');
        }
        setFeatureFilter(record.feature_filter || '');
        setSubmitAttempted(false);
        setMessage(null);
        window.requestAnimationFrame(() => serverInputRef.current?.focus());
    };

    const handleReimport = async (record: ImportHistoryRecord) => {
        if (!canEdit) return;
        if (record.source_type !== 'url' || !record.source_url) return;
        if (!hasValidUrl(record.base_url)) {
            handleUseSettings(record);
            return;
        }
        setImportUrl(record.source_url);
        setServerUrl(record.base_url || '');
        setServerUrlTouched(true);
        setFeatureFilter(record.feature_filter || '');
        setImportMode('url');
        setMessage(null);
        setIsImporting(true);

        try {
            const res = await fetch(`${API_BASE}${withProjectQuery('/api-testing/import-openapi', projectId)}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(withProjectBody({
                    url: record.source_url,
                    base_url: record.base_url,
                    feature_filter: record.feature_filter || undefined,
                    mode: DEFAULT_OPENAPI_IMPORT_MODE,
                }, projectId)),
            });
            if (res.ok) {
                const data = await res.json();
                startJob(data.job_id, data.message || 'Re-import started');
                setMessage({ type: 'success', text: 'Re-import started' });
            } else {
                setMessage({ type: 'error', text: await readError(res, 'Re-import failed') });
            }
        } catch (err) {
            setMessage({ type: 'error', text: networkErrorText('Failed to start re-import', err) });
        } finally {
            setIsImporting(false);
        }
    };

    const handleGenerateSpec = async (specPath: string) => {
        if (!canEdit) return;
        const specName = fileName(specPath);
        if (!specName || generatingSpecs.has(specPath)) return;

        setGeneratingSpecs(prev => new Set(prev).add(specPath));
        setMessage(null);
        try {
            const res = await fetch(`${API_BASE}${withProjectQuery('/api-testing/generate', projectId)}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(withProjectBody({ spec_name: specName }, projectId)),
            });
            if (!res.ok) {
                setMessage({ type: 'error', text: await readError(res, 'Failed to start test generation') });
                return;
            }
            const data = await res.json();
            setActiveJobs(prev => ({
                ...prev,
                [data.job_id]: { job_id: data.job_id, status: 'running', message: data.message },
            }));
            pollJob(data.job_id, () => fetchHistory(0, false));
            setMessage({ type: 'success', text: `Test generation started for ${specName}` });
        } catch (err) {
            setMessage({ type: 'error', text: networkErrorText('Failed to start test generation', err) });
        } finally {
            setGeneratingSpecs(prev => {
                const next = new Set(prev);
                next.delete(specPath);
                return next;
            });
        }
    };

    return (
        <div style={{ width: '100%' }}>
            {canEdit && (
                <ImportForm
                    importUrl={importUrl}
                    serverUrl={serverUrl}
                    importFile={importFile}
                    featureFilter={featureFilter}
                    importMode={importMode}
                    isImporting={isImporting}
                    submitAttempted={submitAttempted}
                    serverInputRef={serverInputRef}
                    onImportUrlChange={setImportUrl}
                    onServerUrlChange={value => {
                        setServerUrlTouched(true);
                        setServerUrl(value);
                    }}
                    onFileChange={setImportFile}
                    onFeatureFilterChange={setFeatureFilter}
                    onImportModeChange={setImportMode}
                    onSubmit={handleImport}
                    canEdit={canEdit}
                />
            )}
            <ImportJobsList jobs={importJobs} onDismiss={dismissJob} />
            <ImportHistoryTable
                history={history}
                historyTotal={historyTotal}
                historyOffset={historyOffset}
                historyLoading={historyLoading}
                historyError={historyError}
                expandedRows={expandedRows}
                generatingSpecs={generatingSpecs}
                onRefresh={() => fetchHistory(0, false)}
                onLoadMore={() => fetchHistory(historyOffset, true)}
                onToggleRow={toggleRow}
                onUseSettings={handleUseSettings}
                onReimport={handleReimport}
                onGenerateSpec={handleGenerateSpec}
                canEdit={canEdit}
            />
        </div>
    );
}
