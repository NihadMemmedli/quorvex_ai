import { describe, expect, it } from 'vitest';
import {
  buildApiTestingPageLinkForTool,
  getApiTestingArtifactContext,
} from './api-testing-links';

describe('API testing assistant links', () => {
  it('builds a project and spec scoped link for chat-created API specs', () => {
    const result = {
      name: 'products-api-demo.md',
      path: 'specs/project-a/api/products-api-demo.md',
      job_id: '20fa9b2e',
      _assistantAction: {
        projectId: 'project-a',
      },
    };

    expect(buildApiTestingPageLinkForTool('createAndGenerateApiTest', result)).toBe(
      '/api-testing?project_id=project-a&tab=specs&spec=products-api-demo.md&job_id=20fa9b2e',
    );
  });

  it('extracts generated test paths from completed API job snapshots', () => {
    const context = getApiTestingArtifactContext('generateApiTest', {
      job_id: 'job-1',
      result: {
        spec_paths: ['specs/project-a/api/products-api-demo.md'],
        test_paths: ['tests/generated/project-a/products-api-demo.api.spec.ts'],
      },
      _assistantAction: {
        projectId: 'project-a',
      },
    });

    expect(context).toMatchObject({
      projectId: 'project-a',
      specName: 'products-api-demo.md',
      specPath: 'specs/project-a/api/products-api-demo.md',
      testPath: 'tests/generated/project-a/products-api-demo.api.spec.ts',
      jobId: 'job-1',
    });
  });
});
