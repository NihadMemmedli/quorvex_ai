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
    runtimeMessage?: string | null;
    vncUrl?: string | null;
    displayDiagnostics?: BrowserDisplayDiagnostics | null;
}

const VNC_CONNECT_TIMEOUT_MS = 8000;
const VNC_FRAME_PROBE_MS = 500;
const VNC_FRAME_PROBE_ATTEMPTS = 16;

interface AgentArtifact {
    name: string;
    path: string;
    type: 'image' | 'video' | string;
    modified_at?: string | null;
}

interface BrowserDisplayDiagnostics {
    browser_process_count?: number | null;
    browser_window_count?: number | null;
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
    runtimeMessage,
    vncUrl,
    displayDiagnostics,
}: LiveBrowserViewProps) {
    const { user } = useAuth();
    const [isConnected, setIsConnected] = useState(false);
    const [isFullscreen, setIsFullscreen] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [isLoading, setIsLoading] = useState(true);
    const [vncAvailable, setVncAvailable] = useState<boolean | null>(null);
    const [artifacts, setArtifacts] = useState<AgentArtifact[]>([]);
    const [liveReady, setLiveReady] = useState(false);

    const containerRef = useRef<HTMLDivElement>(null);
    const rfbRef = useRef<any>(null);
    const canvasContainerRef = useRef<HTMLDivElement>(null);
    const connectionTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
    const frameProbeRef = useRef<ReturnType<typeof setInterval> | null>(null);

    // Only admins can see VNC
    const isAdmin = user?.is_superuser === true;

    const resolvedVncUrl = (() => {
        if (typeof window === 'undefined') return vncUrl || 'ws://localhost:6080/websockify';
        if (vncUrl?.startsWith('/')) {
            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            return `${protocol}//${window.location.host}${vncUrl}`;
        }
        if (vncUrl) return vncUrl;
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        return `${protocol}//${window.location.hostname}:6080/websockify`;
    })();
    const effectiveArtifacts = providedArtifacts ?? artifacts;
    const fallbackImage = providedLatestImage ?? latestImageArtifact(effectiveArtifacts);
    const preferQueryArtifactPreview = typeof window !== 'undefined'
        && new URLSearchParams(window.location.search).get('demoCapture') === '1';
    const forceArtifactPreview = preferProvidedArtifactPreview || preferQueryArtifactPreview || !liveViewAvailable;
    const pendingMessage = runtimeMessage?.trim() || statusMessage?.trim();
    const hasNoBrowserWindow = displayDiagnostics?.browser_window_count === 0;
    const hasNoUsableVncFrame = !liveReady;
    const waitingForBrowserWindow = Boolean(
        hasNoUsableVncFrame && hasNoBrowserWindow
    );
    const liveCanvasMounted = isConnected && !forceArtifactPreview;
    const liveStreamVisible = liveCanvasMounted && liveReady && !waitingForBrowserWindow;
    const showingFallbackCapture = forceArtifactPreview
        || Boolean(fallbackImage && !liveStreamVisible)
        || (isConnected && !liveReady && !isLoading)
        || waitingForBrowserWindow;
    const isProviderRetry = Boolean(pendingMessage && /rate limit|rate-limited|retry/i.test(pendingMessage));
    const statusColor = liveStreamVisible
        ? 'var(--success)'
        : showingFallbackCapture
            ? fallbackImage ? 'var(--primary)' : 'var(--text-secondary)'
            : 'var(--danger)';
    const statusBackground = liveStreamVisible
        ? 'rgba(16, 185, 129, 0.1)'
        : showingFallbackCapture
            ? 'var(--primary-glow)'
            : 'rgba(239, 68, 68, 0.1)';
    const statusBorder = liveStreamVisible
        ? 'rgba(16, 185, 129, 0.3)'
        : showingFallbackCapture
            ? 'rgba(59, 130, 246, 0.35)'
            : 'rgba(239, 68, 68, 0.3)';

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
        if (!isAdmin || !isActive || !liveViewAvailable || !canvasContainerRef.current) {
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
    }, [isAdmin, isActive, liveViewAvailable, resolvedVncUrl, checkVncAvailability, forceArtifactPreview]);

    // Connect when component mounts and isActive changes
    useEffect(() => {
        if (isAdmin && isActive && liveViewAvailable) {
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
    }, [isAdmin, isActive, liveViewAvailable, initVNC]);

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
                    Live browser view is available for administrators only.
                </p>
            </div>
        );
    }

    // Not active message
    if (!isActive) {
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
                            {liveStreamVisible ? <Wifi size={12} /> : showingFallbackCapture ? <Monitor size={12} /> : <WifiOff size={12} />}
                            {liveStreamVisible
                                ? 'Connected'
                                : showingFallbackCapture
                                    ? fallbackImage
                                        ? 'Latest capture'
                                        : isProviderRetry
                                            ? 'Provider retry'
                                            : 'Waiting for capture'
                                    : isLoading
                                        ? 'Connecting...'
                                        : 'Disconnected'}
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
                        opacity: liveStreamVisible ? 1 : 0,
                        position: 'absolute',
                        inset: '0.5rem',
                        pointerEvents: liveStreamVisible ? 'auto' : 'none',
                        zIndex: liveStreamVisible ? 1 : 0,
                        alignItems: 'center',
                        justifyContent: 'center',
                    }}
                />

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
                                <p style={{ fontSize: '0.82rem', lineHeight: 1.5, margin: '0.85rem 0 0' }}>
                                    Live stream is not connected in this environment, so the latest agent browser capture is shown for review.
                                </p>
                            </div>
                        ) : (
                            <Server size={48} color="var(--primary)" />
                        )}
                        <div>
                            <h3 style={{ color: 'var(--text-primary)', marginBottom: '0.5rem', fontSize: '1.1rem' }}>
                                {fallbackImage
                                    ? 'Browser Evidence Available'
                                    : waitingForBrowserWindow
                                        ? 'Waiting for Browser Window'
                                        : isProviderRetry
                                            ? 'Waiting on Provider'
                                            : 'Live Browser Standby'}
                            </h3>
                            {!fallbackImage && (
                                <p style={{ fontSize: '0.9rem', lineHeight: 1.6 }}>
                                    {pendingMessage || 'The agent can continue to publish screenshots and recordings while the live stream initializes.'}
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
