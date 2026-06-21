import { describe, expect, it } from 'vitest';
import { extractLinkedAgentRunId, formatAge, resolveRunHealth } from './run-observability';

describe('run observability', () => {
  it('formats compact ages', () => {
    expect(formatAge(12)).toBe('12s');
    expect(formatAge(125)).toBe('2m');
    expect(formatAge(3700)).toBe('1h 1m');
  });

  it('warns when an active run has stale log output', () => {
    const health = resolveRunHealth({
      status: 'running',
      current_stage: 'planning',
      stage_started_at: '2026-06-20T16:00:00.000Z',
      health: {
        last_log_at: '2026-06-20T16:01:00.000Z',
        stale_after_seconds: 120,
      },
    }, new Date('2026-06-20T16:05:30.000Z'));

    expect(health.stage_age_seconds).toBe(330);
    expect(health.last_log_age_seconds).toBe(270);
    expect(health.has_recent_output).toBe(false);
    expect(health.stuck_warning).toContain('No new execution.log output');
  });

  it('warns when Temporal has a started activity and stale history', () => {
    const health = resolveRunHealth({
      status: 'running',
      health: {
        last_log_at: '2026-06-20T16:04:30.000Z',
        last_temporal_event_at: '2026-06-20T16:00:00.000Z',
        temporal_started_activities: [{ activity_type: 'execute_test_run', status: 'started' }],
        stale_after_seconds: 120,
      },
    }, new Date('2026-06-20T16:05:30.000Z'));

    expect(health.has_recent_output).toBe(true);
    expect(health.warnings?.join('\n')).toContain('Temporal activity is started');
  });

  it('warns when an active planner stream has messages but no parsed output', () => {
    const health = resolveRunHealth({
      status: 'running',
      current_stage: 'planning',
      health: {
        last_log_at: '2026-06-20T16:05:00.000Z',
        stale_after_seconds: 120,
      },
      diagnostics: {
        agent_progress: {
          messages_received: 600,
          text_blocks_received: 0,
          tool_calls: 0,
          output_chars: 0,
          elapsed_seconds: 240,
          unproductive_stream: true,
        },
      },
    }, new Date('2026-06-20T16:05:30.000Z'));

    expect(health.has_recent_output).toBe(true);
    expect(health.stuck_warning).toContain('Planner stream received 600 messages');
    expect(health.agent_progress?.unproductive_stream).toBe(true);
  });

  it('extracts linked agent run IDs from nested summaries', () => {
    expect(extractLinkedAgentRunId({
      stage_outcomes: {
        planner: { agent_run_id: 'agent-run-123' },
      },
    })).toBe('agent-run-123');
  });
});
