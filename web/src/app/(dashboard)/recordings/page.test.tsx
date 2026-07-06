import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { ReactNode } from 'react';
import RecordingsPage, { recorderBrowserUrl } from './page';

vi.mock('@/contexts/ProjectContext', () => ({
    useProject: () => ({
        currentProject: { id: 'default', name: 'Default Project' },
        isLoading: false,
    }),
}));

vi.mock('@/hooks/useProjectRole', () => ({
    useProjectRole: () => ({
        canEdit: true,
        isLoading: false,
    }),
}));

vi.mock('@/lib/api', () => ({
    API_BASE: '',
}));

vi.mock('@/components/LiveBrowserView', () => ({
    LiveBrowserView: (props: {
        runId: string;
        isActive: boolean;
        vncUrl?: string | null;
        browserActive?: boolean;
    }) => (
        <div
            data-testid="recording-live-browser"
            data-run-id={props.runId}
            data-active={String(props.isActive)}
            data-vnc-url={props.vncUrl ?? 'same-origin'}
            data-browser-active={String(props.browserActive)}
        />
    ),
}));

vi.mock('@/components/ui/page-header', () => ({
    PageHeader: ({ title }: { title: string }) => <h1>{title}</h1>,
}));

vi.mock('@/components/ui/page-layout', () => ({
    PageLayout: ({ children }: { children: ReactNode }) => <div>{children}</div>,
}));

describe('recorderBrowserUrl', () => {
    afterEach(() => {
        cleanup();
        vi.restoreAllMocks();
    });

    it('does not invent a recorder URL when backend leaves browser_url blank', () => {
        expect(recorderBrowserUrl({ browser_url: null })).toBeNull();
    });

    it('keeps explicit recorder URLs available', () => {
        expect(
            recorderBrowserUrl({
                browser_url: 'https://mytest.idda.az/vnc.html?autoconnect=true&resize=scale',
            }),
        ).toBe('https://mytest.idda.az/vnc.html?autoconnect=true&resize=scale');
    });
});

describe('RecordingsPage active recording', () => {
    afterEach(() => {
        cleanup();
        vi.unstubAllGlobals();
        vi.restoreAllMocks();
    });

    it('embeds the live browser for an active recording without an external recorder URL', async () => {
        vi.stubGlobal('fetch', vi.fn(async () => ({
            ok: true,
            json: async () => ({
                total: 1,
                items: [
                    {
                        id: 'recording_20260706_161200_abc12345',
                        project_id: 'default',
                        status: 'recording',
                        target_url: 'https://example.com/login',
                        engine: 'playwright-codegen',
                        name: 'Login flow',
                        output_spec_path: null,
                        output_code_path: 'runs/recordings/recording_20260706_161200_abc12345/recording.spec.ts',
                        artifact_dir: 'runs/recordings/recording_20260706_161200_abc12345',
                        process_id: 123,
                        browser_url: null,
                        error: null,
                        config: {},
                        created_at: '2026-07-06T16:12:00',
                        started_at: '2026-07-06T16:12:00',
                        completed_at: null,
                        duration_seconds: null,
                    },
                ],
            }),
        })));

        render(<RecordingsPage />);

        const liveBrowser = await screen.findByTestId('recording-live-browser');
        expect(liveBrowser).toHaveAttribute('data-run-id', 'recording_20260706_161200_abc12345');
        expect(liveBrowser).toHaveAttribute('data-active', 'true');
        expect(liveBrowser).toHaveAttribute('data-vnc-url', 'same-origin');
        expect(liveBrowser).toHaveAttribute('data-browser-active', 'true');
        expect(screen.queryByRole('link', { name: /open recorder/i })).not.toBeInTheDocument();

        await waitFor(() => {
            expect(fetch).toHaveBeenCalledWith('/recordings?project_id=default', undefined);
        });
    });
});
