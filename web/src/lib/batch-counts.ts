export interface BatchCountFields {
  status?: string | null;
  total_tests: number;
  passed: number;
  failed: number;
  actual_total_tests?: number | null;
  actual_passed?: number | null;
  actual_failed?: number | null;
  actual_skipped?: number | null;
  actual_other?: number | null;
}

export interface BatchDisplayCounts {
  total: number;
  passed: number;
  failed: number;
  skipped: number;
  other: number;
  successRate: number;
}

export function deriveBatchDisplayCounts(batch: BatchCountFields): BatchDisplayCounts {
  const total = batch.actual_total_tests ?? batch.total_tests;
  const passed = batch.actual_passed ?? batch.passed;
  const failed = batch.actual_failed ?? batch.failed;
  const oldCompletedBatchRemainder =
    batch.status === 'completed' ? Math.max(0, total - passed - failed) : 0;
  const skipped = batch.actual_skipped ?? oldCompletedBatchRemainder;
  const other = batch.actual_other ?? 0;
  const successRate = total ? Math.round((passed / total) * 1000) / 10 : 0;

  return { total, passed, failed, skipped, other, successRate };
}
