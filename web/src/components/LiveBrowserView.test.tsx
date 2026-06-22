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

vi.mock('@novnc/novnc/lib/rfb', () => ({
    default: class MockRFB {
        private listeners: Record<string, (event: any) => void> = {};

        constructor(container: HTMLElement) {
            const canvas = container.ownerDocument.createElement('canvas');
            canvas.width = 100;
            canvas.height = 100;
            container.appendChild(canvas);
        }

        set viewOnly(_value: boolean) {}
        set scaleViewport(_value: boolean) {}
        set resizeSession(_value: boolean) {}
        set showDotCursor(_value: boolean) {}

        addEventListener(type: string, callback: (event: any) => void) {
            this.listeners[type] = callback;
            if (type === 'connect') {
                window.setTimeout(() => callback({ detail: {} }), 0);
            }
        }

        disconnect() {
            this.listeners.disconnect?.({ detail: { clean: true } });
        }
    },
}));

function stubAvailableWebSocket() {
    vi.stubGlobal('WebSocket', class MockWebSocket {
        onopen: (() => void) | null = null;
        onerror: (() => void) | null = null;

        constructor() {
            window.setTimeout(() => this.onopen?.(), 0);
        }

        close() {}
    });
}

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
        vi.unstubAllGlobals();
        vi.restoreAllMocks();
    });

    it('renders the latest browser capture immediately for inactive runs', () => {
        render(
            <LiveBrowserView
                runId="run-inactive"
                isActive={false}
                artifacts={[]}
                latestImage={{
                    name: 'capture.png',
                    path: '/api/agents/runs/run-inactive/artifacts/capture.png',
                    type: 'image',
                    modified_at: '2026-06-21T10:00:00Z',
                }}
            />,
        );

        expect(screen.getByText('Latest Browser Capture')).toBeInTheDocument();
        expect(screen.getByAltText('Latest browser capture')).toHaveAttribute('src', '/api/agents/runs/run-inactive/artifacts/capture.png');
        expect(screen.queryByText('Live Browser Standby')).not.toBeInTheDocument();
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

    it('shows browser dialog blockage only when telemetry indicates it', () => {
        render(
            <LiveBrowserView
                runId="run-3"
                isActive
                preferArtifactPreview
                liveViewAvailable
                statusMessage="Browser tool timed out"
                suspectedBrowserDialogBlock
                displayDiagnostics={{ vnc_server_available: true }}
            />,
        );

        expect(screen.getByText('Blocked by Browser Dialog')).toBeInTheDocument();
        expect(screen.queryByText('Live Browser Standby')).not.toBeInTheDocument();
    });

    it('shows auth challenge before generic live browser connection states', () => {
        render(
            <LiveBrowserView
                runId="run-auth"
                isActive
                preferArtifactPreview
                liveViewAvailable
                statusMessage="Connected"
                authPreflightStatus="failed"
                authPreflightFailureReason="Saved browser session was attached, but target opened a security challenge."
                displayDiagnostics={{ vnc_server_available: true }}
            />,
        );

        expect(screen.getByText('Auth challenge')).toBeInTheDocument();
        expect(screen.getByText(/target opened a security challenge/i)).toBeInTheDocument();
    });

    it('labels connected VNC without browser activity as desktop standby', async () => {
        stubAvailableWebSocket();
        vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null);

        render(
            <LiveBrowserView
                runId="run-vnc"
                isActive
                showHeader
                artifacts={[]}
                liveViewAvailable
                browserActive={false}
            />,
        );

        expect(await screen.findByText('Desktop connected')).toBeInTheDocument();
    });

    it('shows the latest capture during connected desktop standby', async () => {
        stubAvailableWebSocket();
        vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null);

        render(
            <LiveBrowserView
                runId="run-vnc-capture"
                isActive
                showHeader
                artifacts={[]}
                latestImage={{
                    name: 'latest.png',
                    path: '/api/agents/runs/run-vnc-capture/artifacts/latest.png',
                    type: 'image',
                    modified_at: '2026-06-21T10:01:00Z',
                }}
                liveViewAvailable
                browserActive={false}
            />,
        );

        expect(await screen.findByText('Waiting for Browser Window')).toBeInTheDocument();
        expect(screen.getByText('Latest Browser Capture')).toBeInTheDocument();
    });
});
