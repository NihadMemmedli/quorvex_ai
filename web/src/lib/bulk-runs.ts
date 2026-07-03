export interface BulkRunResponse {
  batch_id?: string;
  run_ids?: string[];
  count?: number;
  mode?: string;
  scheduled?: boolean;
  chunk_size?: number;
  max_active_runs?: number;
  detail?: unknown;
}

export function isScheduledBulkRun(data: BulkRunResponse): boolean {
  return data.scheduled === true || String(data.mode || '').toLowerCase() === 'scheduled';
}

export function bulkRunCount(data: BulkRunResponse): number {
  return data.count ?? data.run_ids?.length ?? 0;
}

export function bulkRunErrorMessage(data: BulkRunResponse, fallback: string): string {
  if (typeof data.detail === 'string') return data.detail;
  if (data.detail && typeof data.detail === 'object' && 'message' in data.detail) {
    const message = (data.detail as { message?: unknown }).message;
    if (typeof message === 'string') return message;
  }
  return fallback;
}

export function bulkRunStartedMessage(data: BulkRunResponse, label = 'test run'): string {
  const count = bulkRunCount(data);
  const plural = count === 1 ? label : `${label}s`;

  if (!isScheduledBulkRun(data)) {
    return `Started ${count} ${plural}.`;
  }

  const details = [
    data.chunk_size ? `chunks of ${data.chunk_size}` : null,
    data.max_active_runs ? `${data.max_active_runs} active at a time` : null,
  ].filter(Boolean);

  return `Scheduled ${count} ${plural}${details.length ? ` (${details.join(', ')})` : ''}.`;
}

export function bulkBatchHref(batchId: string, data: BulkRunResponse): string {
  if (!isScheduledBulkRun(data)) return `/regression/batches/${encodeURIComponent(batchId)}`;

  const params = new URLSearchParams({ bulk: 'scheduled' });
  const count = bulkRunCount(data);
  if (count > 0) params.set('count', String(count));
  if (data.chunk_size) params.set('chunk_size', String(data.chunk_size));
  if (data.max_active_runs) params.set('max_active_runs', String(data.max_active_runs));
  if (data.mode) params.set('mode', data.mode);

  return `/regression/batches/${encodeURIComponent(batchId)}?${params.toString()}`;
}
