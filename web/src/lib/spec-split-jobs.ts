import { API_BASE } from '@/lib/api';
import { parseSplitErrorPayload, readSplitErrorResponse } from '@/lib/split-errors';

export interface SplitSpecRequestBody {
    spec_name: string;
    output_dir?: string;
    project_id?: string | null;
    mode?: 'individual' | 'grouped';
    extraction_method?: 'ai' | 'regex';
}

export interface SplitSpecResult {
    count: number;
    files: string[];
    output_dir: string;
    groups?: Array<Record<string, any>> | null;
    extraction_method?: string;
    ai_used?: boolean;
    warning?: string | null;
}

interface SplitSpecJobStart {
    job_id: string;
    status: string;
}

interface SplitSpecJobStatus {
    job_id: string;
    status: 'queued' | 'running' | 'completed' | 'failed' | string;
    result?: SplitSpecResult;
    error?: string;
}

const DEFAULT_POLL_INTERVAL_MS = 2000;
const DEFAULT_TIMEOUT_MS = 15 * 60 * 1000;

function sleep(ms: number) {
    return new Promise(resolve => globalThis.setTimeout(resolve, ms));
}

export async function splitSpecWithJob(
    body: SplitSpecRequestBody,
    options: { timeoutMs?: number; pollIntervalMs?: number } = {},
): Promise<SplitSpecResult> {
    const startRes = await fetch(`${API_BASE}/specs/split-jobs`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
    });
    if (!startRes.ok) {
        throw new Error(await readSplitErrorResponse(startRes, 'Failed to start split job.'));
    }

    const startData = await startRes.json() as SplitSpecJobStart;
    if (!startData.job_id) {
        throw new Error('Split job did not return a job id.');
    }

    const timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;
    const pollIntervalMs = options.pollIntervalMs ?? DEFAULT_POLL_INTERVAL_MS;
    const deadline = Date.now() + timeoutMs;

    while (Date.now() < deadline) {
        await sleep(pollIntervalMs);
        const pollRes = await fetch(`${API_BASE}/specs/split-jobs/${encodeURIComponent(startData.job_id)}`);
        if (!pollRes.ok) {
            throw new Error(await readSplitErrorResponse(pollRes, `Failed to poll split job ${startData.job_id}.`));
        }

        const job = await pollRes.json() as SplitSpecJobStatus;
        if (job.status === 'completed') {
            if (!job.result) {
                throw new Error('Split job completed without a result.');
            }
            return job.result;
        }
        if (job.status === 'failed') {
            throw new Error(parseSplitErrorPayload({ detail: job.error }, 'Failed to split spec.'));
        }
    }

    throw new Error('Split job is still running. Check the Specs page again in a few minutes.');
}
