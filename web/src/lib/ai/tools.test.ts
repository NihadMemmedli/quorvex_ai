import { beforeEach, describe, expect, it, vi } from 'vitest';

const backendFetch = vi.fn();

vi.mock('./backend-client', () => ({
  backendFetch,
}));

describe('assistant memory tools', () => {
  beforeEach(() => {
    backendFetch.mockReset();
  });

  it('passes project ID and bounded options to retrieveAgenticContext', async () => {
    backendFetch.mockResolvedValueOnce({
      ok: true,
      data: { answer_context: '## Retrieved Knowledge', citations: [] },
    });
    const { createAssistantTools } = await import('./tools');
    const tools = createAssistantTools('token-1', 'project-a');

    const result = await tools.retrieveAgenticContext.execute?.(
      {
        query: 'debug login failure',
        intent: 'debugging',
        sources: ['agent_memories', 'run_summaries'],
        runId: 'run-1',
        maxItems: 4,
        includeDebug: true,
      },
      { toolCallId: 'tool-1', messages: [] }
    );

    expect(result).toEqual({ answer_context: '## Retrieved Knowledge', citations: [] });
    expect(backendFetch).toHaveBeenCalledWith('/api/memory/agentic-context', {
      authToken: 'token-1',
      projectId: 'project-a',
      method: 'POST',
      body: {
        query: 'debug login failure',
        intent: 'debugging',
        sources: ['agent_memories', 'run_summaries'],
        project_id: 'project-a',
        url: undefined,
        specName: undefined,
        runId: 'run-1',
        max_items: 4,
        include_debug: true,
      },
    });
  });

  it('returns backend errors from retrieveAgenticContext', async () => {
    backendFetch.mockResolvedValueOnce({ ok: false, error: 'backend down' });
    const { createAssistantTools } = await import('./tools');
    const tools = createAssistantTools(undefined, 'project-a');

    const result = await tools.retrieveAgenticContext.execute?.(
      { query: 'coverage gaps', maxItems: 8, includeDebug: false },
      { toolCallId: 'tool-2', messages: [] }
    );

    expect(result).toEqual({ error: 'backend down' });
  });

  it('passes project ID to RTM generation job status polling', async () => {
    backendFetch.mockResolvedValueOnce({
      ok: true,
      data: { job_id: 'job-1', status: 'completed' },
    });
    const { createAssistantTools } = await import('./tools');
    const tools = createAssistantTools('token-1', 'project-a');

    const result = await tools.getRTMGenerateJob.execute?.(
      { jobId: 'job-1' },
      { toolCallId: 'tool-3', messages: [] }
    );

    expect(result).toEqual({ job_id: 'job-1', status: 'completed' });
    expect(backendFetch).toHaveBeenCalledWith('/rtm/generate-jobs/job-1?project_id=project-a', {
      authToken: 'token-1',
      projectId: 'project-a',
      method: 'GET',
      body: undefined,
    });
  });
});
