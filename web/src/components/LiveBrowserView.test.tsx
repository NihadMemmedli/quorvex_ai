import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { LiveBrowserView, resolveLiveBrowserVncUrl } from './LiveBrowserView';

vi.mock('@/contexts/AuthContext', () => ({
    fetchWithAuth: vi.fn(),
    useAuth: () => ({ user: { is_superuser: true } }),
}));

vi.mock('@/lib/api', () => ({
    API_BASE: '',
}));

describe('resolveLiveBrowserVncUrl', () => {
    it('uses same-origin websockify for non-local browser hosts', () => {
        const url = resolveLiveBrowserVncUrl(null, {
            protocol: 'https:',
            host: 'quorvex.company.test',
            hostname: 'quorvex.company.test',
        });

        expect(url).toBe('wss://quorvex.company.test/websockify');
        expect(url).not.toContain('localhost');
        expect(url).not.toContain(':6080');
    });

    it('uses the direct local VNC port only for local browser hosts', () => {
        const url = resolveLiveBrowserVncUrl(null, {
            protocol: 'http:',
            host: 'localhost:3000',
            hostname: 'localhost',
        });

        expect(url).toBe('ws://localhost:6080/websockify');
    });
});

describe('LiveBrowserView diagnostics', () => {
    afterEach(() => {
        cleanup();
    });

    it('shows VNC server unavailable separately from missing browser windows', () => {
        render(
            <LiveBrowserView
                runId="run-1"
                isActive
                preferArtifactPreview
                liveViewAvailable
                displayDiagnostics={{
                    vnc_server_available: false,
                    browser_process_count: 0,
                    browser_window_count: 0,
                    browser_process_seen: false,
                    browser_window_seen: false,
                }}
            />,
        );

        expect(screen.getByText('VNC Server Unavailable')).toBeInTheDocument();
        expect(screen.queryByText('No Browser Window Detected')).not.toBeInTheDocument();
    });

    it('shows no browser window when VNC is available but no window exists', () => {
        render(
            <LiveBrowserView
                runId="run-2"
                isActive
                preferArtifactPreview
                liveViewAvailable
                displayDiagnostics={{
                    vnc_server_available: true,
                    browser_process_count: 1,
                    browser_window_count: 0,
                    browser_process_seen: true,
                    browser_window_seen: false,
                }}
            />,
        );

        expect(screen.getByText('No Browser Window Detected')).toBeInTheDocument();
        expect(screen.queryByText('VNC Server Unavailable')).not.toBeInTheDocument();
    });
});
