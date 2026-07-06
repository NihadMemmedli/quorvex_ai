import { describe, expect, it } from 'vitest';

import { bulkBatchHref, bulkRunStartedMessage, isScheduledBulkRun } from './bulk-runs';

describe('bulk run response helpers', () => {
  it('detects scheduled mode from either response shape', () => {
    expect(isScheduledBulkRun({ mode: 'scheduled' })).toBe(true);
    expect(isScheduledBulkRun({ scheduled: true })).toBe(true);
    expect(isScheduledBulkRun({ mode: 'batch' })).toBe(false);
  });

  it('adds scheduled batch metadata to batch detail links', () => {
    expect(
      bulkBatchHref('batch 1', {
        mode: 'scheduled',
        count: 125,
        chunk_size: 25,
        max_active_runs: 5,
      })
    ).toBe('/regression/batches/batch%201?bulk=scheduled&count=125&chunk_size=25&max_active_runs=5&mode=scheduled');
  });

  it('formats scheduled start messages with chunk details', () => {
    expect(bulkRunStartedMessage({ scheduled: true, count: 50, chunk_size: 10, max_active_runs: 2 })).toBe(
      'Scheduled 50 test runs (chunks of 10, 2 active at a time).'
    );
  });
});
