import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { AgentRunObservabilityPanel, CustomAgentReportView, SpecGenerationRunPanel } from './agents-panels';
import { fetchAgentRunNotes } from './agents-api';
import type { AgentRun, AgentRunNote } from './agents-model';

vi.mock('next/dynamic', () => ({
    default: () => (props: any) => (
        <div
            data-testid="live-browser-view"
            data-live-view-available={String(props.liveViewAvailable)}
            data-is-active={String(props.isActive)}
            data-browser-activity-seen={String(props.browserActivitySeen)}
            data-browser-active={String(props.browserActive)}
            data-browser-last-tool={props.browserLastTool || ''}
        />
    ),
}));

vi.mock('./agents-api', () => ({
    fetchAgentRunNotes: vi.fn(() => Promise.resolve([
        {
            id: 'note-1',
            run_id: 'run-1',
            sequence: 7,
            note_type: 'observation',
            level: 'info',
            title: 'Fetched note',
            body: 'Backfilled from durable notes endpoint',
            source: 'runtime',
            actionable: false,
            tags: [],
            created_at: '2026-06-21T10:00:00Z',
        },
    ])),
}));

const run: AgentRun = {
    id: 'run-1',
    agent_type: 'custom',
    status: 'running',
    created_at: '2026-06-21T10:00:00Z',
    config: {},
    project_id: 'project-1',
    health: {},
    temporal: {},
};

describe('AgentRunObservabilityPanel', () => {
    afterEach(() => {
        cleanup();
        vi.clearAllMocks();
    });

    it('renders the notes tab with backfilled notes', async () => {
        render(<AgentRunObservabilityPanel run={run} events={[]} />);

        fireEvent.click(screen.getByRole('button', { name: /Notes/i }));

        expect(await screen.findByText('Fetched note')).toBeInTheDocument();
        expect(screen.getByText('Backfilled from durable notes endpoint')).toBeInTheDocument();
        expect(fetchAgentRunNotes).toHaveBeenCalledWith(
            'run-1',
            expect.objectContaining({ limit: 200, projectId: 'project-1' }),
        );
    });

    it('renders notes from endpoint, live progress tail, and agent_note events', async () => {
        const supplementalNotes: AgentRunNote[] = [
            {
                id: 'recovered-note',
                run_id: 'run-1',
                sequence: -1000000,
                note_type: 'observation',
                level: 'info',
                title: 'Recovered agent note',
                body: 'Recovered from parent test run log_sections.',
                source: 'projects/session.jsonl',
                actionable: false,
                tags: ['recovered', 'test-run-log'],
                created_at: '2026-06-21T10:03:00Z',
            },
        ];
        render(
            <AgentRunObservabilityPanel
                run={{
                    ...run,
                    progress: {
                        live_notes_tail: [
                            {
                                id: 'note-live',
                                run_id: 'run-1',
                                sequence: 8,
                                note_type: 'finding',
                                level: 'warning',
                                title: 'Live tail note',
                                body: 'Available before the notes endpoint catches up',
                                source: 'runtime',
                                actionable: true,
                                tags: [],
                                created_at: '2026-06-21T10:01:00Z',
                            },
                        ],
                    },
                }}
                events={[
                    {
                        id: 'event-note',
                        run_id: 'run-1',
                        sequence: 9,
                        event_type: 'agent_note',
                        level: 'info',
                        message: 'Event note',
                        payload: {
                            title: 'Event note',
                            body: 'Rendered immediately from the event stream',
                            note_type: 'validation',
                            source: 'agent',
                            tags: [],
                        },
                        created_at: '2026-06-21T10:02:00Z',
                    },
                ]}
                supplementalNotes={supplementalNotes}
            />,
        );

        fireEvent.click(screen.getByRole('button', { name: /Notes/i }));

        expect(await screen.findByText('Fetched note')).toBeInTheDocument();
        expect(screen.getByText('Live tail note')).toBeInTheDocument();
        expect(screen.getByText('Event note')).toBeInTheDocument();
        expect(screen.getByText('Recovered agent note')).toBeInTheDocument();
        expect(screen.getByText('Available before the notes endpoint catches up')).toBeInTheDocument();
        expect(screen.getByText('Rendered immediately from the event stream')).toBeInTheDocument();
        expect(screen.getByText('Recovered from parent test run log_sections.')).toBeInTheDocument();
    });

    it('renders supplemental notes when durable notes are empty', async () => {
        vi.mocked(fetchAgentRunNotes).mockResolvedValueOnce([]);

        render(
            <AgentRunObservabilityPanel
                run={run}
                events={[]}
                activeTraceTab="notes"
                supplementalNotes={[
                    {
                        id: 'recovered-only',
                        run_id: 'run-1',
                        sequence: -1000000,
                        note_type: 'observation',
                        level: 'info',
                        title: 'Recovered only note',
                        body: 'Visible without durable notes.',
                        source: 'projects/session.jsonl',
                        actionable: false,
                        tags: ['recovered', 'test-run-log'],
                        created_at: '2026-06-21T10:04:00Z',
                    },
                ]}
            />,
        );

        expect(await screen.findByText('Recovered only note')).toBeInTheDocument();
        expect(screen.getByText('Visible without durable notes.')).toBeInTheDocument();
        expect(screen.getByText('Agent Notes')).toBeInTheDocument();
    });

    it('shows the empty state only when all note sources are empty', async () => {
        vi.mocked(fetchAgentRunNotes).mockResolvedValueOnce([]);

        render(<AgentRunObservabilityPanel run={run} events={[]} activeTraceTab="notes" supplementalNotes={[]} />);

        expect(await screen.findByText('No agent notes recorded for this run.')).toBeInTheDocument();
    });

    it('renders tool events when trace spans are unavailable', () => {
        render(
            <AgentRunObservabilityPanel
                run={run}
                trace={{ spans: [], events: [], memory_injections: [], artifacts: [] }}
                events={[
                    {
                        id: 'synthetic-event-1',
                        run_id: 'run-1',
                        sequence: 1,
                        event_type: 'browser_action',
                        level: 'info',
                        message: 'CALL mcp__playwright__browser_click input={"selector":"button"}',
                        payload: {
                            tool_name: 'mcp__playwright__browser_click',
                            source: 'session_jsonl',
                            synthetic: true,
                        },
                        created_at: '2026-06-21T10:02:00Z',
                    },
                ]}
            />,
        );

        fireEvent.click(screen.getByRole('button', { name: /Tools/i }));

        expect(screen.getByText('click')).toBeInTheDocument();
        expect(screen.getAllByText(/CALL mcp__playwright__browser_click/).length).toBeGreaterThan(0);
        expect(screen.queryByText('No tool trace spans have been recorded yet.')).not.toBeInTheDocument();
    });
});

describe('SpecGenerationRunPanel', () => {
    afterEach(() => {
        cleanup();
        vi.clearAllMocks();
    });

    it('treats missing live_view_available as available and passes browser activity signals', () => {
        render(
            <SpecGenerationRunPanel
                run={{
                    ...run,
                    id: 'spec-run-1',
                    agent_type: 'spec_generation',
                    progress: {
                        browser_activity_seen: true,
                        browser_tool_calls: 2,
                        last_tool_label: 'browser_click',
                    },
                }}
                events={[]}
            />,
        );

        const live = screen.getByTestId('live-browser-view');
        expect(live).toHaveAttribute('data-live-view-available', 'true');
        expect(live).toHaveAttribute('data-browser-activity-seen', 'true');
        expect(live).toHaveAttribute('data-browser-active', 'true');
        expect(live).toHaveAttribute('data-browser-last-tool', 'browser_click');
    });

    it('passes inactive state to completed spec-generation runs', () => {
        render(
            <SpecGenerationRunPanel
                run={{
                    ...run,
                    id: 'spec-run-completed',
                    agent_type: 'spec_generation',
                    status: 'completed',
                    progress: {
                        browser_tool_calls: 3,
                        interactions: 3,
                    },
                }}
                events={[]}
            />,
        );

        expect(screen.getByTestId('live-browser-view')).toHaveAttribute('data-is-active', 'false');
    });
});

describe('CustomAgentReportView', () => {
    afterEach(() => {
        cleanup();
        vi.clearAllMocks();
    });

    it('shows the completed partial timeout reason', () => {
        render(
            <CustomAgentReportView
                run={{
                    ...run,
                    status: 'completed_partial',
                    result: {
                        partial_reason: 'Recovered partial evidence after browser_click timed out after 30s/45s.',
                        structured_report: {
                            summary: 'Recovered checkout evidence.',
                            scope: 'checkout',
                            findings: [],
                            test_ideas: [],
                            requirements: [],
                            evidence: [],
                            pages_checked: [],
                            follow_up_actions: [],
                        },
                    },
                }}
                activeTab="overview"
                onTabChange={vi.fn()}
                onAskAssistant={vi.fn()}
                onCreateSpecFromReport={vi.fn()}
                onEditOverview={vi.fn()}
                onEditReportItem={vi.fn()}
                onImportRequirements={vi.fn()}
                importingRequirementIds={[]}
                reportStatusFilter="all"
                onReportStatusFilterChange={vi.fn()}
                reportSeverityFilter="all"
                onReportSeverityFilterChange={vi.fn()}
            />,
        );

        expect(screen.getByTestId('custom-agent-partial-reason')).toHaveTextContent(
            'Recovered partial evidence after browser_click timed out after 30s/45s.',
        );
    });

    it('shows captured browser evidence before the completed custom report', () => {
        const { container } = render(
            <CustomAgentReportView
                run={{
                    ...run,
                    status: 'completed',
                    artifacts: [
                        {
                            name: 'latest.png',
                            path: '/api/agents/runs/run-1/artifacts/latest.png',
                            type: 'image',
                            modified_at: '2026-06-21T10:02:00Z',
                        },
                    ],
                    result: {
                        structured_report: {
                            summary: 'Recovered checkout evidence.',
                            scope: 'checkout',
                            findings: [],
                            test_ideas: [],
                            requirements: [],
                            evidence: [],
                            pages_checked: [],
                            follow_up_actions: [],
                        },
                    },
                }}
                activeTab="overview"
                onTabChange={vi.fn()}
                onAskAssistant={vi.fn()}
                onCreateSpecFromReport={vi.fn()}
                onEditOverview={vi.fn()}
                onEditReportItem={vi.fn()}
                onImportRequirements={vi.fn()}
                importingRequirementIds={[]}
                reportStatusFilter="all"
                onReportStatusFilterChange={vi.fn()}
                reportSeverityFilter="all"
                onReportSeverityFilterChange={vi.fn()}
            />,
        );

        const capture = screen.getByText('Latest screenshot');
        const reportHeading = screen.getByRole('heading', { name: 'Custom Agent' });
        expect(capture.compareDocumentPosition(reportHeading) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
        expect(container.querySelector('img[alt="Latest agent browser screenshot"]')).toHaveAttribute('src', expect.stringContaining('/api/agents/runs/run-1/artifacts/latest.png'));
    });
});
