'use client';

import { useState, useEffect, useRef, useCallback } from 'react';
import { Maximize2, Minimize2, Monitor, Wifi, WifiOff, Shield, Server } from 'lucide-react';
import { fetchWithAuth, useAuth } from '@/contexts/AuthContext';
import { API_BASE } from '@/lib/api';

interface LiveBrowserViewProps {
    runId: string;
    isActive: boolean;
    showHeader?: boolean; // Whether to show internal header (default: false for embedded use)
    onShowLog?: () => void;
    artifacts?: AgentArtifact[];
    latestImage?: AgentArtifact | null;
    preferArtifactPreview?: boolean;
    statusMessage?: string | null;
    liveViewAvailable?: boolean;
    liveBrowserRequested?: boolean;
    runtimeMessage?: string | null;
    vncUrl?: string | null;
    displayDiagnostics?: BrowserDisplayDiagnostics | null;
    browserActivitySeen?: boolean;
    browserActive?: boolean;
    browserLastTool?: string | null;
    suspectedBrowserDialogBlock?: boolean;
    authPreflightStatus?: string | null;
    authPreflightFailureReason?: string | null;
}

const VNC_CONNECT_TIMEOUT_MS = 8000;
const VNC_FRAME_PROBE_MS = 500;
const VNC_FRAME_PROBE_ATTEMPTS = 16;
const LIVE_STATUS_OVERLAY_VISIBLE_MS = 4000;

interface AgentArtifact {
    name: string;
    path: string;
    type: 'image' | 'video' | string;
    modified_at?: string | null;
}

interface BrowserDisplayDiagnostics {
    vnc_server_available?: boolean | null;
    vnc_server_error?: string | null;
    vnc_server_host?: string | null;
    vnc_server_port?: number | null;
    browser_process_count?: number | null;
    browser_window_count?: number | null;
    browser_process_seen?: boolean | null;
    browser_window_seen?: boolean | null;
    display?: string | null;
    probed_at?: string | null;
}

function latestImageArtifact(artifacts: AgentArtifact[]): AgentArtifact | null {
    return artifacts
        .filter((artifact) => artifact.type === 'image')
        .sort((a, b) => {
            const bTime = b.modified_at ? new Date(b.modified_at).getTime() : 0;
            const aTime = a.modified_at ? new Date(a.modified_at).getTime() : 0;
            return bTime - aTime;
        })[0] || null;
}

function canvasHasVisibleFrame(container: HTMLDivElement | null): boolean {
    const canvas = container?.querySelector('canvas');
    if (!canvas || canvas.width === 0 || canvas.height === 0) {
        return false;
    }

    const context = canvas.getContext('2d', { willReadFrequently: true });
    if (!context) {
        return true;
    }

    try {
        const sampleWidth = Math.min(canvas.width, 64);
        const sampleHeight = Math.min(canvas.height, 64);
        const xPositions = [0, Math.max(0, Math.floor((canvas.width - sampleWidth) / 2)), Math.max(0, canvas.width - sampleWidth)];
        const yPositions = [0, Math.max(0, Math.floor((canvas.height - sampleHeight) / 2)), Math.max(0, canvas.height - sampleHeight)];

        for (const x of xPositions) {
            for (const y of yPositions) {
                const image = context.getImageData(x, y, sampleWidth, sampleHeight).data;
                for (let index = 0; index < image.length; index += 4) {
                    if (image[index + 3] > 0 && (image[index] > 8 || image[index + 1] > 8 || image[index + 2] > 8)) {
                        return true;
                    }
                }
            }
        }
        return false;
    } catch {
        return true;
    }
}

export function resolveLiveBrowserVncUrl(vncUrl?: string | null, locationLike?: Pick<Location, 'protocol' | 'host' | 'hostname'>): string {
    const currentLocation = locationLike ?? (typeof window !== 'undefined' ? window.location : null);
    if (!currentLocation) return vncUrl || '/websockify';

    const protocol = currentLocation.protocol === 'https:' ? 'wss:' : 'ws:';
    if (vncUrl?.startsWith('/')) {
        return `${protocol}//${currentLocation.host}${vncUrl}`;
    }
    if (vncUrl) return vncUrl;
    if (currentLocation.hostname !== 'localhost' && currentLocation.hostname !== '127.0.0.1') {
        return `${protocol}//${currentLocation.host}/websockify`;
    }
    return `${protocol}//${currentLocation.hostname}:6080/websockify`;
}

export function LiveBrowserView({
    runId,
    isActive,
    showHeader = false,
    onShowLog,
    artifacts: providedArtifacts,
    latestImage: providedLatestImage,
    preferArtifactPreview: preferProvidedArtifactPreview = false,
    statusMessage,
    liveViewAvailable = true,
    liveBrowserRequested = true,
    runtimeMessage,
    vncUrl,
    displayDiagnostics,
    browserActivitySeen = false,
    browserActive = false,
    browserLastTool,
    suspectedBrowserDialogBlock = false,
    authPreflightStatus,
    authPreflightFailureReason,
}: LiveBrowserViewProps) {
    const { user } = useAuth();
    const [isConnected, setIsConnected] = useState(false);
    const [isFullscreen, setIsFullscreen] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [isLoading, setIsLoading] = useState(true);
    const [vncAvailable, setVncAvailable] = useState<boolean | null>(null);
    const [artifacts, setArtifacts] = useState<AgentArtifact[]>([]);
    const [liveReady, setLiveReady] = useState(false);
    const [showLiveStatusOverlay, setShowLiveStatusOverlay] = useState(false);

    const containerRef = useRef<HTMLDivElement>(null);
    const rfbRef = useRef<any>(null);
    const canvasContainerRef = useRef<HTMLDivElement>(null);
    const connectionTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
    const frameProbeRef = useRef<ReturnType<typeof setInterval> | null>(null);

    // Only admins can see VNC
    const isAdmin = user?.is_superuser === true;

    const resolvedVncUrl = resolveLiveBrowserVncUrl(vncUrl);
    const effectiveArtifacts = providedArtifacts ?? artifacts;
    const fallbackImage = providedLatestImage ?? latestImageArtifact(effectiveArtifacts);
    const preferQueryArtifactPreview = typeof window !== 'undefined'
        && new URLSearchParams(window.location.search).get('demoCapture') === '1';
    const canUseLiveView = liveBrowserRequested && liveViewAvailable;
    const forceArtifactPreview = preferProvidedArtifactPreview || preferQueryArtifactPreview || !canUseLiveView;
    const pendingMessage = runtimeMessage?.trim() || statusMessage?.trim();
    const authPreflightFailed = String(authPreflightStatus || '').toLowerCase() === 'failed';
    const authChallenge = authPreflightFailed && /challenge|security|cloudflare|captcha|verify you are human|just a moment/i.test(authPreflightFailureReason || pendingMessage || '');
    const authFailureLabel = authChallenge ? 'Auth challenge' : 'Session validation failed';
    const authFailureMessage = authPreflightFailureReason?.trim() || pendingMessage || 'Saved browser session validation failed before the agent started.';
    const browserProcessCount = displayDiagnostics?.browser_process_count ?? 0;
    const browserWindowCount = displayDiagnostics?.browser_window_count ?? null;
    const browserProcessSeen = displayDiagnostics?.browser_process_seen ?? browserProcessCount > 0;
    const browserWindowSeen = displayDiagnostics?.browser_window_seen ?? (browserWindowCount ?? 0) > 0;
    const vncServerUnavailable = canUseLiveView && displayDiagnostics?.vnc_server_available === false;
    const hasNoBrowserWindow = !vncServerUnavailable && browserWindowCount === 0;
    const liveCanvasMounted = isConnected && !forceArtifactPreview;
    const liveStreamVisible = liveCanvasMounted && liveReady && browserActive;
    const desktopConnected = liveCanvasMounted && liveReady && !browserActive;
    const browserStarting = !vncServerUnavailable && liveBrowserRequested && browserProcessSeen && !browserWindowSeen;
    const noBrowserWindow = !vncServerUnavailable && liveBrowserRequested && browserActivitySeen && !browserProcessSeen && !browserWindowSeen;
    const isProviderRetry = Boolean(pendingMessage && /rate limit|rate-limited|retry/i.test(pendingMessage));
    const dialogBlocked = suspectedBrowserDialogBlock === true;
    const showingFallbackCapture = forceArtifactPreview
        || Boolean(fallbackImage && !isConnected)
        || Boolean(fallbackImage && desktopConnected)
        || (!isConnected && !isLoading);
    const statusLabel = !liveBrowserRequested
        ? 'PRD-only'
        : authPreflightFailed
            ? authFailureLabel
        : browserActive && liveStreamVisible
            ? 'Connected'
            : dialogBlocked
                ? 'Blocked by browser dialog'
                : vncServerUnavailable
                    ? 'VNC unavailable'
                    : fallbackImage && !isConnected
                        ? 'Latest capture'
                        : browserStarting
                            ? 'Browser starting'
                            : noBrowserWindow
                                ? 'No browser window'
                                : desktopConnected
                                    ? 'Desktop connected'
                                    : isProviderRetry
                                        ? 'Provider retry'
                                        : isLoading
                                            ? 'Connecting...'
                                            : isConnected
                                                ? 'Desktop connected'
                                                : 'Disconnected';
    const unavailableTitle = vncServerUnavailable
        ? 'VNC Server Unavailable'
        : authPreflightFailed
            ? authFailureLabel
        : dialogBlocked
            ? 'Blocked by Browser Dialog'
        : canUseLiveView
            ? 'Live Browser Standby'
            : liveBrowserRequested
                ? 'Live Browser Unavailable'
                : 'PRD-only Generation';
    const unavailableMessage = vncServerUnavailable
        ? pendingMessage || 'The WebSocket bridge is reachable, but the backend VNC server on port 5900 is not accepting connections.'
        : authPreflightFailed
            ? authFailureMessage
        : pendingMessage || (
            canUseLiveView
                ? 'The agent can continue to publish screenshots and recordings while the live stream initializes.'
                : liveBrowserRequested
                    ? 'Live browser validation was requested, but a visible browser stream is not available in this runtime.'
                    : 'This run was generated from PRD context only. Add a Target URL before generation to enable live browser validation.'
        );
    const statusColor = statusLabel === 'Connected'
        ? 'var(--success)'
        : statusLabel === 'Latest capture' || statusLabel === 'PRD-only' || statusLabel === 'Desktop connected'
            ? fallbackImage ? 'var(--primary)' : 'var(--text-secondary)'
            : 'var(--danger)';
    const statusBackground = statusLabel === 'Connected'
        ? 'rgba(16, 185, 129, 0.1)'
        : statusLabel === 'Latest capture' || statusLabel === 'PRD-only' || statusLabel === 'Desktop connected'
            ? 'var(--primary-glow)'
            : 'rgba(239, 68, 68, 0.1)';
    const statusBorder = statusLabel === 'Connected'
        ? 'rgba(16, 185, 129, 0.3)'
        : statusLabel === 'Latest capture' || statusLabel === 'PRD-only' || statusLabel === 'Desktop connected'
            ? 'rgba(59, 130, 246, 0.35)'
            : 'rgba(239, 68, 68, 0.3)';

    useEffect(() => {
        if (!liveCanvasMounted || statusLabel === 'Connected') {
            setShowLiveStatusOverlay(false);
            return;
        }

        setShowLiveStatusOverlay(true);
        const timeout = window.setTimeout(() => {
            setShowLiveStatusOverlay(false);
        }, LIVE_STATUS_OVERLAY_VISIBLE_MS);

        return () => window.clearTimeout(timeout);
    }, [liveCanvasMounted, statusLabel, pendingMessage, browserLastTool]);

    useEffect(() => {
        let cancelled = false;
        async function loadArtifacts() {
            if (providedArtifacts) {
                return;
            }
            if (!runId) {
                setArtifacts([]);
                return;
            }
            try {
                const response = await fetchWithAuth(`${API_BASE}/api/agents/runs/${encodeURIComponent(runId)}`);
                if (!response.ok) return;
                const data = await response.json();
                if (!cancelled) {
                    setArtifacts(Array.isArray(data.artifacts) ? data.artifacts : []);
                }
            } catch {
                if (!cancelled) setArtifacts([]);
            }
        }
        loadArtifacts();
        if (!isActive || providedArtifacts) {
            return () => {
                cancelled = true;
            };
        }
        const interval = window.setInterval(loadArtifacts, 3000);
        return () => {
            cancelled = true;
            window.clearInterval(interval);
        };
    }, [runId, isActive, providedArtifacts]);

    // Check if VNC server is available
    const checkVncAvailability = useCallback(async () => {
        try {
            // Try to establish a WebSocket connection to check if VNC is running
            const ws = new WebSocket(resolvedVncUrl);

            return new Promise<boolean>((resolve) => {
                const timeout = setTimeout(() => {
                    ws.close();
                    resolve(false);
                }, 3000); // 3 second timeout

                ws.onopen = () => {
                    clearTimeout(timeout);
                    ws.close();
                    resolve(true);
                };

                ws.onerror = () => {
                    clearTimeout(timeout);
                    resolve(false);
                };
            });
        } catch {
            return false;
        }
    }, [resolvedVncUrl]);

    // Initialize noVNC connection
    const initVNC = useCallback(async () => {
        if (!isAdmin || !isActive || !canUseLiveView || !canvasContainerRef.current) {
            return;
        }

        if (connectionTimeoutRef.current) {
            clearTimeout(connectionTimeoutRef.current);
            connectionTimeoutRef.current = null;
        }

        setIsLoading(true);
        setIsConnected(false);
        setLiveReady(false);
        setError(null);

        if (forceArtifactPreview) {
            setVncAvailable(false);
            setIsLoading(false);
            return;
        }

        if (vncServerUnavailable) {
            setVncAvailable(false);
            setIsLoading(false);
            setError(null);
            return;
        }

        // First check if VNC is available
        const available = await checkVncAvailability();
        setVncAvailable(available);

        if (!available) {
            setIsLoading(false);
            setError('VNC server not available');
            return;
        }

        try {
            // Dynamically import noVNC
            const { default: RFB } = await import('@novnc/novnc/lib/rfb');

            // Clean up existing connection
            if (rfbRef.current) {
                rfbRef.current.disconnect();
                rfbRef.current = null;
            }

            // Clear the canvas container
            if (canvasContainerRef.current) {
                canvasContainerRef.current.innerHTML = '';
            }

            // Create new RFB connection
            const rfb = new RFB(canvasContainerRef.current, resolvedVncUrl, {
                shared: true,
                credentials: { password: '' },
            });

            // Configure for view-only mode
            rfb.viewOnly = true;
            rfb.scaleViewport = true;
            rfb.resizeSession = false;
            rfb.showDotCursor = false;

            // Event handlers
            rfb.addEventListener('connect', () => {
                if (connectionTimeoutRef.current) {
                    clearTimeout(connectionTimeoutRef.current);
                    connectionTimeoutRef.current = null;
                }
                setIsConnected(true);
                setIsLoading(false);
                setError(null);
                setLiveReady(false);

                if (frameProbeRef.current) {
                    clearInterval(frameProbeRef.current);
                }
                let attempts = 0;
                frameProbeRef.current = setInterval(() => {
                    attempts += 1;
                    if (canvasHasVisibleFrame(canvasContainerRef.current)) {
                        setLiveReady(true);
                        if (frameProbeRef.current) {
                            clearInterval(frameProbeRef.current);
                            frameProbeRef.current = null;
                        }
                    } else if (attempts >= VNC_FRAME_PROBE_ATTEMPTS) {
                        if (frameProbeRef.current) {
                            clearInterval(frameProbeRef.current);
                            frameProbeRef.current = null;
                        }
                    }
                }, VNC_FRAME_PROBE_MS);
            });

            rfb.addEventListener('disconnect', (e: any) => {
                if (connectionTimeoutRef.current) {
                    clearTimeout(connectionTimeoutRef.current);
                    connectionTimeoutRef.current = null;
                }
                if (frameProbeRef.current) {
                    clearInterval(frameProbeRef.current);
                    frameProbeRef.current = null;
                }
                setIsConnected(false);
                setLiveReady(false);
                setIsLoading(false);
                if (e.detail.clean) {
                    // Clean disconnect
                } else {
                    setError('Connection lost');
                }
            });

            rfb.addEventListener('securityfailure', (e: any) => {
                if (connectionTimeoutRef.current) {
                    clearTimeout(connectionTimeoutRef.current);
                    connectionTimeoutRef.current = null;
                }
                if (frameProbeRef.current) {
                    clearInterval(frameProbeRef.current);
                    frameProbeRef.current = null;
                }
                setError(`Security error: ${e.detail.reason}`);
                setIsLoading(false);
            });

            rfbRef.current = rfb;
            connectionTimeoutRef.current = setTimeout(() => {
                if (rfbRef.current === rfb) {
                    rfb.disconnect();
                    rfbRef.current = null;
                    setIsConnected(false);
                    setLiveReady(false);
                    setIsLoading(false);
                    setError('Browser view did not become available. Use progress or screenshots to follow this work.');
                }
            }, VNC_CONNECT_TIMEOUT_MS);
        } catch (err) {
            console.error('Failed to initialize VNC:', err);
            setError('Failed to connect to browser view');
            setIsLoading(false);
        }
    }, [isAdmin, isActive, canUseLiveView, resolvedVncUrl, checkVncAvailability, forceArtifactPreview, vncServerUnavailable]);

    // Connect when component mounts and isActive changes
    useEffect(() => {
        if (isAdmin && isActive && canUseLiveView) {
            initVNC();
        }

        return () => {
            if (connectionTimeoutRef.current) {
                clearTimeout(connectionTimeoutRef.current);
                connectionTimeoutRef.current = null;
            }
            if (frameProbeRef.current) {
                clearInterval(frameProbeRef.current);
                frameProbeRef.current = null;
            }
            if (rfbRef.current) {
                rfbRef.current.disconnect();
                rfbRef.current = null;
            }
            setLiveReady(false);
        };
    }, [isAdmin, isActive, canUseLiveView, initVNC]);

    // Handle fullscreen toggle
    const toggleFullscreen = () => {
        if (!containerRef.current) return;

        if (!isFullscreen) {
            if (containerRef.current.requestFullscreen) {
                containerRef.current.requestFullscreen();
            }
        } else {
            if (document.exitFullscreen) {
                document.exitFullscreen();
            }
        }
        setIsFullscreen(!isFullscreen);
    };

    // Listen for fullscreen changes
    useEffect(() => {
        const handleFullscreenChange = () => {
            setIsFullscreen(!!document.fullscreenElement);
        };
        document.addEventListener('fullscreenchange', handleFullscreenChange);
        return () => document.removeEventListener('fullscreenchange', handleFullscreenChange);
    }, []);

    if (!liveBrowserRequested) {
        return (
            <div
                style={{
                    display: 'flex',
                    flexDirection: 'column',
                    alignItems: 'center',
                    justifyContent: 'center',
                    minHeight: '400px',
                    background: '#0d1117',
                    borderRadius: 'var(--radius)',
                    border: '1px solid var(--border)',
                    gap: '1rem',
                    padding: '1.5rem',
                    textAlign: 'center',
                }}
            >
                <Server size={42} color="var(--text-secondary)" />
                <div>
                    <h3 style={{ color: 'var(--text-primary)', margin: '0 0 0.5rem', fontSize: '1.05rem' }}>
                        PRD-only Generation
                    </h3>
                    <p style={{ color: 'var(--text-secondary)', maxWidth: '480px', margin: 0, lineHeight: 1.55 }}>
                        This run was generated from PRD context only. Add a Target URL before generation to enable live browser validation.
                    </p>
                </div>
                {onShowLog && (
                    <button
                        onClick={onShowLog}
                        className="btn btn-secondary"
                        style={{ fontSize: '0.85rem' }}
                    >
                        View Log
                    </button>
                )}
            </div>
        );
    }

    if (!canUseLiveView && !fallbackImage) {
        return (
            <div
                style={{
                    display: 'flex',
                    flexDirection: 'column',
                    alignItems: 'center',
                    justifyContent: 'center',
                    minHeight: '400px',
                    background: '#0d1117',
                    borderRadius: 'var(--radius)',
                    border: '1px solid var(--border)',
                    gap: '1rem',
                    padding: '1.5rem',
                    textAlign: 'center',
                }}
            >
                <Server size={42} color="var(--primary)" />
                <div>
                    <h3 style={{ color: 'var(--text-primary)', margin: '0 0 0.5rem', fontSize: '1.05rem' }}>
                        {unavailableTitle}
                    </h3>
                    <p style={{ color: 'var(--text-secondary)', maxWidth: '460px', margin: 0, lineHeight: 1.55 }}>
                        {unavailableMessage}
                    </p>
                </div>
                {onShowLog && (
                    <button
                        onClick={onShowLog}
                        className="btn btn-secondary"
                        style={{ fontSize: '0.85rem' }}
                    >
                        View Log
                    </button>
                )}
            </div>
        );
    }

    // Non-admin message
    if (!isAdmin) {
        if (fallbackImage) {
            return (
                <div
                    style={{
                        display: 'flex',
                        flexDirection: 'column',
                        alignItems: 'center',
                        justifyContent: 'center',
                        minHeight: '400px',
                        background: '#0d1117',
                        borderRadius: 'var(--radius)',
                        border: '1px solid var(--border)',
                        gap: '1rem',
                        padding: '1.25rem',
                }}
            >
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', color: 'var(--success)', fontWeight: 700 }}>
                    <Monitor size={18} />
                    Latest Browser Capture
                </div>
                <img
                    src={`${API_BASE}${fallbackImage.path}`}
                    alt="Latest browser capture"
                        style={{
                            width: '100%',
                            maxWidth: '920px',
                            maxHeight: '390px',
                            objectFit: 'contain',
                            borderRadius: '10px',
                            border: '1px solid var(--border)',
                            background: '#020617',
                        }}
                    />
                    <p style={{ color: 'var(--text-secondary)', textAlign: 'center', maxWidth: '520px', margin: 0 }}>
                        Live browser controls are available for administrators only. Showing the latest browser capture.
                    </p>
                </div>
            );
        }
        return (
            <div
                style={{
                    display: 'flex',
                    flexDirection: 'column',
                    alignItems: 'center',
                    justifyContent: 'center',
                    height: '400px',
                    background: '#0d1117',
                    borderRadius: 'var(--radius)',
                    border: '1px solid var(--border)',
                    gap: '1rem',
                }}
            >
                <Shield size={48} color="var(--text-secondary)" />
                <p style={{ color: 'var(--text-secondary)', textAlign: 'center', maxWidth: '300px' }}>
                    {pendingMessage || 'Live browser view is available for administrators only. Screenshots will appear here when the agent captures them.'}
                </p>
            </div>
        );
    }

    // Not active message
    if (!isActive) {
        if (fallbackImage) {
            return (
                <div
                    style={{
                        display: 'flex',
                        flexDirection: 'column',
                        alignItems: 'center',
                        justifyContent: 'center',
                        minHeight: '400px',
                        background: '#0d1117',
                        borderRadius: 'var(--radius)',
                        border: '1px solid var(--border)',
                        gap: '1rem',
                        padding: '1.25rem',
                }}
            >
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', color: 'var(--success)', fontWeight: 700 }}>
                    <Monitor size={18} />
                    Latest Browser Capture
                </div>
                <img
                    src={`${API_BASE}${fallbackImage.path}`}
                    alt="Latest browser capture"
                        style={{
                            width: '100%',
                            maxWidth: '920px',
                            maxHeight: '390px',
                            objectFit: 'contain',
                            borderRadius: '10px',
                            border: '1px solid var(--border)',
                            background: '#020617',
                        }}
                    />
                    <p style={{ color: 'var(--text-secondary)', textAlign: 'center', maxWidth: '560px', margin: 0 }}>
                        Browser work is no longer active. Showing the latest captured browser evidence.
                    </p>
                </div>
            );
        }
        return (
            <div
                style={{
                    display: 'flex',
                    flexDirection: 'column',
                    alignItems: 'center',
                    justifyContent: 'center',
                    height: '400px',
                    background: '#0d1117',
                    borderRadius: 'var(--radius)',
                    border: '1px solid var(--border)',
                    gap: '1rem',
                }}
            >
                <Monitor size={48} color="var(--text-secondary)" />
                <p style={{ color: 'var(--text-secondary)' }}>
                    Browser view available while browser work is running
                </p>
            </div>
        );
    }

    return (
        <div
            ref={containerRef}
            style={{
                background: '#0d1117',
                borderRadius: isFullscreen ? 0 : 'var(--radius)',
                border: isFullscreen ? 'none' : '1px solid var(--border)',
                overflow: 'hidden',
                display: 'flex',
                flexDirection: 'column',
                height: isFullscreen ? '100vh' : 'auto',
            }}
        >
            {/* Header - only shown when showHeader is true */}
            {showHeader && (
                <div
                    style={{
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        padding: '0.75rem 1rem',
                        borderBottom: '1px solid var(--border)',
                        background: 'rgba(255, 255, 255, 0.02)',
                    }}
                >
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                        <Monitor size={18} color="var(--primary)" />
                        <span style={{ fontWeight: 600, fontSize: '0.95rem' }}>Live Browser View</span>

                        {/* Connection status indicator */}
                        <div
                            style={{
                                display: 'flex',
                                alignItems: 'center',
                                gap: '0.4rem',
                                padding: '0.2rem 0.6rem',
                                borderRadius: '999px',
                                fontSize: '0.75rem',
                                background: statusBackground,
                                color: statusColor,
                                border: `1px solid ${statusBorder}`,
                            }}
                        >
                            {statusLabel === 'Connected' ? <Wifi size={12} /> : statusLabel === 'Latest capture' || statusLabel === 'Desktop connected' || statusLabel === 'PRD-only' ? <Monitor size={12} /> : <WifiOff size={12} />}
                            {statusLabel}
                        </div>
                    </div>

                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                        {/* Admin badge */}
                        <span
                            style={{
                                fontSize: '0.7rem',
                                padding: '0.15rem 0.5rem',
                                borderRadius: '4px',
                                background: 'rgba(147, 51, 234, 0.1)',
                                color: '#a855f7',
                                border: '1px solid rgba(147, 51, 234, 0.3)',
                            }}
                        >
                            Admin
                        </span>

                        {/* Fullscreen button */}
                        <button
                            onClick={toggleFullscreen}
                            className="btn btn-ghost"
                            style={{
                                padding: '0.4rem 0.6rem',
                                display: 'flex',
                                alignItems: 'center',
                                gap: '0.3rem',
                                fontSize: '0.8rem',
                            }}
                            title={isFullscreen ? 'Exit Fullscreen' : 'Fullscreen'}
                        >
                            {isFullscreen ? <Minimize2 size={14} /> : <Maximize2 size={14} />}
                        </button>
                    </div>
                </div>
            )}

            {/* VNC Display */}
            <div
                style={{
                    flex: 1,
                    position: 'relative',
                    padding: '0.5rem',
                    minHeight: isFullscreen ? 'calc(100vh - 60px)' : '500px',
                    background: '#000',
                }}
            >
                <div
                    ref={canvasContainerRef}
                    style={{
                        width: '100%',
                        height: '100%',
                        minHeight: isFullscreen ? 'calc(100vh - 76px)' : '484px',
                        display: liveCanvasMounted ? 'flex' : 'none',
                        opacity: liveCanvasMounted ? 1 : 0,
                        position: 'absolute',
                        inset: '0.5rem',
                        pointerEvents: 'none',
                        zIndex: 1,
                        alignItems: 'center',
                        justifyContent: 'center',
                    }}
                />

                {liveCanvasMounted && statusLabel !== 'Connected' && showLiveStatusOverlay && (
                    <div
                        style={{
                            position: 'absolute',
                            left: '1rem',
                            top: '1rem',
                            zIndex: 3,
                            maxWidth: '360px',
                            padding: '0.65rem 0.8rem',
                            borderRadius: '8px',
                            border: `1px solid ${statusBorder}`,
                            background: 'rgba(2, 6, 23, 0.86)',
                            color: 'var(--text-primary)',
                            boxShadow: '0 12px 32px rgba(0,0,0,0.35)',
                        }}
                    >
                        <div style={{ fontSize: '0.82rem', fontWeight: 700, marginBottom: '0.25rem' }}>
                            {statusLabel}
                        </div>
                        <div style={{ fontSize: '0.75rem', lineHeight: 1.45, color: 'var(--text-secondary)' }}>
                            {statusLabel === 'Browser starting'
                                ? 'A browser process exists, but no browser window has appeared on the display yet.'
                                : authPreflightFailed
                                    ? authFailureMessage
                                : statusLabel === 'Blocked by browser dialog'
                                    ? pendingMessage || 'Automatic browser dialog recovery ran, but the browser tool still timed out.'
                                : statusLabel === 'No browser window'
                                    ? 'Browser activity was expected, but no browser process or window was detected.'
                                    : statusLabel === 'Desktop connected'
                                        ? pendingMessage || 'The VNC desktop is connected; waiting for an active browser window.'
                                        : pendingMessage || 'Waiting for live browser activity.'}
                            {browserLastTool ? ` Last tool: ${browserLastTool}.` : ''}
                        </div>
                    </div>
                )}

                {showingFallbackCapture || vncAvailable === false ? (
                    // Show a captured browser preview when the live stream is not usable.
                    <div
                        style={{
                            display: 'flex',
                            flexDirection: 'column',
                            alignItems: 'center',
                            justifyContent: 'center',
                            gap: '1.5rem',
                            color: 'var(--text-secondary)',
                            maxWidth: fallbackImage ? '920px' : '420px',
                            textAlign: 'center',
                            padding: '2rem',
                            minHeight: isFullscreen ? 'calc(100vh - 76px)' : '484px',
                            margin: '0 auto',
                            position: 'relative',
                            zIndex: 2,
                        }}
                    >
                        {fallbackImage ? (
                            <div style={{ width: '100%' }}>
                                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '0.5rem', marginBottom: '1rem', color: 'var(--success)', fontWeight: 700 }}>
                                    <Monitor size={18} />
                                    Latest Browser Capture
                                </div>
                                <img
                                    src={`${API_BASE}${fallbackImage.path}`}
                                    alt="Latest browser capture"
                                    style={{
                                        width: '100%',
                                        display: 'block',
                                        borderRadius: '10px',
                                        border: '1px solid var(--border)',
                                        background: '#020617',
                                        maxHeight: '390px',
                                        objectFit: 'contain',
                                    }}
                                />
                            </div>
                        ) : (
                            <Server size={48} color="var(--primary)" />
                        )}
                        <div>
                            <h3 style={{ color: 'var(--text-primary)', marginBottom: '0.5rem', fontSize: '1.1rem' }}>
                                {fallbackImage
                                    ? vncServerUnavailable || authPreflightFailed || dialogBlocked || !liveViewAvailable
                                        ? unavailableTitle
                                        : desktopConnected
                                            ? 'Waiting for Browser Window'
                                            : 'Browser Evidence Available'
                                    : vncServerUnavailable
                                        ? unavailableTitle
                                        : authPreflightFailed
                                            ? unavailableTitle
                                        : dialogBlocked
                                            ? unavailableTitle
                                        : !liveViewAvailable
                                            ? unavailableTitle
                                            : hasNoBrowserWindow
                                                ? 'No Browser Window Detected'
                                                : isProviderRetry
                                                    ? 'Waiting on Provider'
                                                    : unavailableTitle}
                            </h3>
                            {fallbackImage ? (
                                <p style={{ fontSize: '0.9rem', lineHeight: 1.6 }}>
                                    {desktopConnected
                                        ? pendingMessage || 'The VNC desktop is connected, but no active browser window is visible. Showing the latest browser capture for review.'
                                        : vncServerUnavailable
                                            ? unavailableMessage
                                            : authPreflightFailed
                                                ? authFailureMessage
                                            : dialogBlocked
                                                ? pendingMessage || 'Automatic browser dialog recovery ran, but the browser tool still timed out.'
                                                : 'Live stream is not connected in this environment, so the latest agent browser capture is shown for review.'}
                                </p>
                            ) : (
                                <p style={{ fontSize: '0.9rem', lineHeight: 1.6 }}>
                                    {vncServerUnavailable
                                        ? unavailableMessage
                                        : authPreflightFailed
                                            ? authFailureMessage
                                        : dialogBlocked
                                            ? pendingMessage || 'Automatic browser dialog recovery ran, but the browser tool still timed out.'
                                        : hasNoBrowserWindow && canUseLiveView
                                            ? pendingMessage || 'The VNC display is connected, but no browser window was detected yet.'
                                            : unavailableMessage}
                                </p>
                            )}
                        </div>
                        {onShowLog && (
                            <button
                                onClick={onShowLog}
                                className="btn btn-secondary"
                                style={{ fontSize: '0.85rem' }}
                            >
                                View Log
                            </button>
                        )}
                    </div>
                ) : error ? (
                    <div
                        style={{
                            display: 'flex',
                            flexDirection: 'column',
                            alignItems: 'center',
                            justifyContent: 'center',
                            gap: '1rem',
                            color: 'var(--text-secondary)',
                            minHeight: isFullscreen ? 'calc(100vh - 76px)' : '484px',
                        }}
                    >
                        <WifiOff size={32} color="var(--danger)" />
                        <span style={{ color: 'var(--danger)' }}>{error}</span>
                        <div style={{ display: 'flex', gap: '0.75rem', flexWrap: 'wrap', justifyContent: 'center' }}>
                            <button
                                onClick={initVNC}
                                className="btn btn-secondary"
                                style={{ fontSize: '0.85rem' }}
                            >
                                Retry Connection
                            </button>
                            {onShowLog && (
                                <button
                                    onClick={onShowLog}
                                    className="btn btn-ghost"
                                    style={{ fontSize: '0.85rem' }}
                                >
                                    View Log
                                </button>
                            )}
                        </div>
                    </div>
                ) : isLoading && !isConnected ? (
                    <div
                        style={{
                            display: 'flex',
                            flexDirection: 'column',
                            alignItems: 'center',
                            justifyContent: 'center',
                            gap: '1rem',
                            color: 'var(--text-secondary)',
                            minHeight: isFullscreen ? 'calc(100vh - 76px)' : '484px',
                        }}
                    >
                        <div className="loading-spinner" style={{ width: '32px', height: '32px' }} />
                        <span>Connecting to browser...</span>
                    </div>
                ) : null}
            </div>
        </div>
    );
}

export default LiveBrowserView;
