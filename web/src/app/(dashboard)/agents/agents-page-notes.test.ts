import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

describe('agents page notes placement', () => {
    it('does not render standalone notes panels outside observability', () => {
        const source = readFileSync(join(dirname(fileURLToPath(import.meta.url)), 'page.tsx'), 'utf8');

        expect(source).not.toContain('AgentRunNotesPanel');
    });

    it('refetches run detail after agent_note stream events', () => {
        const source = readFileSync(join(dirname(fileURLToPath(import.meta.url)), 'use-agent-run-events-stream.ts'), 'utf8');

        expect(source).toContain("data.event_type === 'agent_note'");
        expect(source).toContain('void fetchRun(selectedRunId)');
    });
});
