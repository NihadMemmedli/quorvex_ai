import { describe, expect, it } from 'vitest';
import { deriveBatchDisplayCounts } from './batch-counts';

describe('deriveBatchDisplayCounts', () => {
  it('falls back to the completed-batch remainder for old responses without skipped counts', () => {
    expect(
      deriveBatchDisplayCounts({
        status: 'completed',
        total_tests: 1,
        passed: 1,
        failed: 0,
        actual_total_tests: 1105,
        actual_passed: 977,
        actual_failed: 82,
      }),
    ).toEqual({
      total: 1105,
      passed: 977,
      failed: 82,
      skipped: 46,
      other: 0,
      successRate: 88.4,
    });
  });

  it('uses explicit skipped and other counts from new responses', () => {
    expect(
      deriveBatchDisplayCounts({
        status: 'completed',
        total_tests: 1,
        passed: 0,
        failed: 1,
        actual_total_tests: 4,
        actual_passed: 1,
        actual_failed: 1,
        actual_skipped: 1,
        actual_other: 1,
      }),
    ).toMatchObject({
      total: 4,
      passed: 1,
      failed: 1,
      skipped: 1,
      other: 1,
    });
  });

  it('shows zero skipped for running old responses instead of treating active tests as skipped', () => {
    expect(
      deriveBatchDisplayCounts({
        status: 'running',
        total_tests: 100,
        passed: 10,
        failed: 2,
      }).skipped,
    ).toBe(0);
  });
});
