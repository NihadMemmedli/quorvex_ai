import { describe, expect, it } from 'vitest';
import { projectQuery, rtmGenerateJobStatusUrl } from './rtm-api';

describe('RTM API URL helpers', () => {
    it('adds the active project to RTM generation job status polling URLs', () => {
        expect(rtmGenerateJobStatusUrl('/backend', 'job 1', 'project-a')).toBe(
            '/backend/rtm/generate-jobs/job%201?project_id=project-a'
        );
    });

    it('encodes project query values', () => {
        expect(projectQuery('project/a b')).toBe('?project_id=project%2Fa%20b');
    });
});
