import { act, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { useState } from 'react';
import { useAgentRunDetail } from './use-agent-run-detail';
import type { AgentRun, AgentRunEvent, AgentTraceBundle, SpecResult } from './agents-model';
import {
    fetchAgentRunResolvingTestRun,
    fetchAgentRunEvents,
    fetchAgentRunTrace,
    fetchExploratorySpecs,
} from './agents-api';

vi.mock('./agents-api', () => ({
    fetchAgentRunResolvingTestRun: vi.fn(),
    fetchAgentRunEvents: vi.fn(() => Promise.resolve([])),
    fetchAgentRunTrace: vi.fn(() => Promise.resolve({ spans: [], events: [], memory_injections: [], artifacts: [] })),
    fetchExploratorySpecs: vi.fn(() => Promise.resolve({})),
}));

const baseRun: AgentRun = {
    id: 'run-1',
    agent_type: 'custom',
    status: 'running',
    created_at: '2026-06-21T10:00:00Z',
    config: {},
    progress: {},
    artifacts: [],
};

const fetchHistoryMock = vi.fn(() => Promise.resolve());

function Harness({ selectedRunId = 'run-1', onResolvedRunId }: { selectedRunId?: string | null; onResolvedRunId?: (runId: string) => void }) {
    const [activeRun, setActiveRun] = useState<AgentRun | null>(baseRun);
    const [, setAgentEvents] = useState<AgentRunEvent[]>([]);
    const [, setAgentTrace] = useState<AgentTraceBundle | null>(null);
    const [, setTraceLoading] = useState(false);
    const [, setSpecResult] = useState<SpecResult | null>(null);
    const [, setTraceSearch] = useState('');
    const [, setTraceSpanType] = useState('');

    const detail = useAgentRunDetail({
        selectedRunId,
        activeRun,
        traceTab: 'timeline',
        fetchHistory: fetchHistoryMock,
        setActiveRun,
        setAgentEvents,
        setAgentTrace,
        setTraceLoading,
        setSpecResult,
        setTraceSearch,
        setTraceSpanType,
        onResolvedRunId,
    });

    return (
        <div>
            <span data-testid="status">{activeRun?.status}</span>
            <span data-testid="run-id">{activeRun?.id}</span>
            <span data-testid="artifact-count">{activeRun?.artifacts?.length || 0}</span>
            <span data-testid="run-loading">{String(detail.runLoading)}</span>
            <span data-testid="run-error">{detail.runError || ''}</span>
        </div>
    );
}

describe('useAgentRunDetail', () => {
    afterEach(() => {
        vi.useRealTimers();
        vi.clearAllMocks();
    });

    it('polls active run details and updates screenshots without overlapping requests', async () => {
        vi.useFakeTimers();
        vi.mocked(fetchAgentRunResolvingTestRun)
            .mockResolvedValueOnce(baseRun)
            .mockResolvedValueOnce({
                ...baseRun,
                progress: { phase: 'tool_use', browser_tool_calls: 1 },
                artifacts: [{ name: 'screenshot.png', path: '/runs/run-1/screenshot.png', type: 'image' }],
            });

        render(<Harness />);

        await act(async () => {
            await Promise.resolve();
        });
        expect(fetchAgentRunResolvingTestRun).toHaveBeenCalledTimes(1);

        await act(async () => {
            await vi.advanceTimersByTimeAsync(3000);
        });

        expect(screen.getByTestId('artifact-count')).toHaveTextContent('1');
        expect(fetchAgentRunResolvingTestRun).toHaveBeenCalledTimes(2);
        expect(fetchAgentRunEvents).toHaveBeenCalledWith('run-1', expect.objectContaining({ limit: 200, afterSequence: 0 }));
        expect(fetchExploratorySpecs).toHaveBeenCalledWith('run-1');
        expect(fetchAgentRunTrace).not.toHaveBeenCalled();
    });

    it('exposes loading and visible error states when selected run fetch fails', async () => {
        vi.mocked(fetchAgentRunResolvingTestRun).mockRejectedValueOnce(new Error('HTTP 404'));

        render(<Harness selectedRunId="missing-run" />);

        expect(screen.getByTestId('run-loading')).toHaveTextContent('true');

        await act(async () => {
            await Promise.resolve();
        });

        expect(screen.getByTestId('run-loading')).toHaveTextContent('false');
        expect(screen.getByTestId('run-error')).toHaveTextContent('Run not found or unavailable. Check project selection.');
    });

    it('uses the resolved linked agent run id for events and specs', async () => {
        const onResolvedRunId = vi.fn();
        vi.mocked(fetchAgentRunResolvingTestRun).mockResolvedValueOnce({
            ...baseRun,
            id: 'agent-run-1',
            status: 'completed',
        });

        render(<Harness selectedRunId="2026-06-22_14-59-09" onResolvedRunId={onResolvedRunId} />);

        await act(async () => {
            await Promise.resolve();
        });

        expect(onResolvedRunId).toHaveBeenCalledWith('agent-run-1');
        expect(screen.getByTestId('run-id')).toHaveTextContent('agent-run-1');
        expect(fetchAgentRunEvents).toHaveBeenCalledWith('agent-run-1', expect.objectContaining({ limit: 200, afterSequence: 0 }));
        expect(fetchExploratorySpecs).toHaveBeenCalledWith('agent-run-1');
    });
});
