import { describe, expect, it } from 'vitest';
import { buildTrackedJobPagePath, makeTrackedJob } from './ChatProvider';

describe('assistant tracked job links', () => {
  it('deep-links custom agent jobs to the selected run and project', () => {
    const job = makeTrackedJob(
      'startAdhocCustomAgent',
      { run_id: 'run-1' },
      undefined,
      'Custom agent',
      'project-a',
      'conversation-1',
      true
    );

    expect(job?.pagePath).toBe('/agents?runId=run-1&view=run&project_id=project-a');
    expect(job ? buildTrackedJobPagePath(job) : '').toBe('/agents?runId=run-1&view=run&project_id=project-a');
  });
});
