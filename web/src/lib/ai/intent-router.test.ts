import { describe, expect, it } from 'vitest';
import { enforceMutatingActionApproval } from './intent-router';

function user(text: string) {
  return { role: 'user', parts: [{ type: 'text', text }] };
}

describe('server-side mutating approval enforcement', () => {
  it('generates an approval action for nightly Baku schedule creation', () => {
    const route = enforceMutatingActionApproval([
      user('Every day at 21:30 Baku time, full regression suite'),
    ]);

    expect(route).toMatchObject({
      kind: 'action',
      toolName: 'createSchedule',
      input: {
        cronExpression: '30 21 * * *',
        timezone: 'Asia/Baku',
        specNames: undefined,
        enabled: true,
      },
    });
  });

  it('recovers the pending action when the follow-up only confirms', () => {
    const route = enforceMutatingActionApproval([
      user('Every day at 21:30 Baku time, full regression suite'),
      user('Confirmed'),
    ]);

    expect(route).toMatchObject({
      kind: 'action',
      toolName: 'createSchedule',
      input: {
        cronExpression: '30 21 * * *',
        timezone: 'Asia/Baku',
      },
    });
  });

  it('does not allow approval prose when required fields are missing', () => {
    const route = enforceMutatingActionApproval([
      user('Please confirm schedule creation for the regression suite'),
    ]);

    expect(route).toMatchObject({
      kind: 'clarify',
      text: 'I could not create an approval card because required fields are missing.',
    });
  });

  it.each([
    ['Run spec checkout/login.md', 'runTestSpec', { specName: 'checkout/login.md' }],
    ['Create spec "checkout/new-flow.md" that verifies checkout happy path', 'createTestSpec', { specName: 'checkout/new-flow.md' }],
    ['Run full regression suite now', 'runRegressionBatch', { specNames: undefined }],
    ['Start Explorer Agent for https://example.com/app', 'startExplorerAgent', { url: 'https://example.com/app' }],
    ['Create Jira issue for run run-123 titled "Checkout fails"', 'createJiraIssue', { runId: 'run-123', title: 'Checkout fails' }],
    ['Sync TestRail results for batch batch-456', 'syncTestRailResults', { batchId: 'batch-456' }],
    ['Dispatch GitHub Actions workflow nightly.yml on branch main', 'dispatchCiWorkflow', { provider: 'github', workflowId: 'nightly.yml' }],
    ['Delete schedule schedule-789', 'deleteSchedule', { scheduleId: 'schedule-789' }],
  ])('routes %s to %s', (text, toolName, input) => {
    const route = enforceMutatingActionApproval([user(text)]);

    expect(route).toMatchObject({
      kind: 'action',
      toolName,
      input,
    });
  });
});
