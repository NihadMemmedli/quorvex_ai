import { describe, expect, it } from 'vitest';
import {
  buildAssistantArtifactPageLinkForTool,
  getAssistantArtifactContext,
} from './assistant-artifact-links';

describe('assistant artifact links', () => {
  it('builds a load testing history link from a completed job snapshot', () => {
    const result = {
      job_id: 'load-job-1',
      result: {
        run_id: 'run-123',
        spec_name: 'checkout-load.md',
      },
      _assistantAction: {
        projectId: 'project-a',
      },
    };

    expect(buildAssistantArtifactPageLinkForTool('runLoadTestFromSpec', result)).toBe(
      '/load-testing?project_id=project-a&job_id=load-job-1&tab=history&run_id=run-123',
    );
  });

  it('builds a database spec link from an AI generation result', () => {
    const result = {
      job_id: 'db-job-1',
      result: {
        spec_name: 'orders-quality.md',
      },
      _assistantAction: {
        projectId: 'project-a',
      },
    };

    expect(buildAssistantArtifactPageLinkForTool('generateDatabaseSpec', result)).toBe(
      '/database-testing?project_id=project-a&jobId=db-job-1&tab=specs&specName=orders-quality.md',
    );
  });

  it('builds a security findings link from a scan result', () => {
    const result = {
      run_id: 'scan-1',
      finding_id: 42,
      _assistantAction: {
        projectId: 'project-a',
      },
    };

    expect(buildAssistantArtifactPageLinkForTool('triageSecurityFinding', result)).toBe(
      '/security-testing?project_id=project-a&tab=findings&findingId=42&runId=scan-1',
    );
  });

  it('preserves explorer run and flow context', () => {
    const context = getAssistantArtifactContext('generateExplorerFlowSpec', {
      job_id: 'flow-job-1',
      _assistantAction: {
        projectId: 'project-a',
        args: {
          runId: 'agent-run-1',
          flowId: 'flow-7',
        },
      },
    });

    expect(context).toMatchObject({
      projectId: 'project-a',
      jobId: 'flow-job-1',
      runId: 'agent-run-1',
      flowId: 'flow-7',
    });
    expect(buildAssistantArtifactPageLinkForTool('generateExplorerFlowSpec', { job_id: 'flow-job-1' }, {
      runId: 'agent-run-1',
      flowId: 'flow-7',
    }, 'project-a')).toBe(
      '/exploration?project_id=project-a&tab=explorer&runId=agent-run-1&flowId=flow-7&jobId=flow-job-1',
    );
  });

  it('builds requirement and generated spec links', () => {
    expect(buildAssistantArtifactPageLinkForTool('generateRequirements', {
      job_id: 'req-job-1',
      _assistantAction: {
        projectId: 'project-a',
        args: { sessionId: 'session-1' },
      },
    })).toBe('/requirements?project_id=project-a&jobId=req-job-1&sourceSessionId=session-1');

    expect(buildAssistantArtifactPageLinkForTool('generateSpecFromRequirement', {
      result: { spec_file: 'specs/generated/login-flow.md' },
      _assistantAction: {
        projectId: 'project-a',
        args: { requirementId: 12 },
      },
    })).toBe('/specs/generated/login-flow.md?project_id=project-a&tab=generated');
  });
});
