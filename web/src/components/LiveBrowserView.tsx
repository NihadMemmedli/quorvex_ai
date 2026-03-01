'use client';

import React, { useState, useEffect, useRef, useCallback } from 'react';
import { Maximize2, Minimize2, Monitor, Wifi, WifiOff, Shield, Server, Terminal } from 'lucide-react';
import { useAuth } from '@/contexts/AuthContext';
import { API_BASE } from '@/lib/api';

interface LiveBrowserViewProps {
    runId: string;
    isActive: boolean;
    showHeader?: boolean; // Whether to show internal header (default: false for embedded use)
}

export function LiveBrowserView({ runId, isActive, showHeader = false }: LiveBrowserViewProps) {
    const { user } = useAuth();
    const [isConnected, setIsConnected] = useState(false);
    const [isFullscreen, setIsFullscreen] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [isLoading, setIsLoading] = useState(true);
    const [vncAvailable, setVncAvailable] = useState<boolean | null>(null);
    const [connectionAttempts, setConnectionAttempts] = useState(0);

    const containerRef = useRef<HTMLDivElement>(null);
    const rfbRef = useRef<any>(null);
    const canvasContainerRef = useRef<HTMLDivElement>(null);

    // Only admins can see VNC
    const isAdmin = user?.is_superuser === true;

    // Build WebSocket URL for VNC
    const vncHost = typeof window !== 'undefined' ? window.location.hostname : 'localhost';
    const vncPort = 6080;
    const vncUrl = `ws://${vncHost}:${vncPort}/websockify`;

    // Check if VNC server is available
    const checkVncAvailability = useCallback(async () => {
        try {
            // Try to establish a WebSocket connection to check if VNC is running
            const ws = new WebSocket(vncUrl);

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
    }, [vncUrl]);

    // Initialize noVNC connection
    const initVNC = useCallback(async () => {
        if (!isAdmin || !isActive || !canvasContainerRef.current) {
            return;
        }

        setIsLoading(true);
        setError(null);
        setConnectionAttempts(prev => prev + 1);

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
            const rfb = new RFB(canvasContainerRef.current, vncUrl, {
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
                setIsConnected(true);
                setIsLoading(false);
                setError(null);
            });

            rfb.addEventListener('disconnect', (e: any) => {
                setIsConnected(false);
                if (e.detail.clean) {
                    // Clean disconnect
                } else {
                    setError('Connection lost');
                }
            });

            rfb.addEventListener('securityfailure', (e: any) => {
                setError(`Security error: ${e.detail.reason}`);
                setIsLoading(false);
            });

            rfbRef.current = rfb;
        } catch (err) {
            console.error('Failed to initialize VNC:', err);
            setError('Failed to connect to browser view');
            setIsLoading(false);
        }
    }, [isAdmin, isActive, vncUrl, checkVncAvailability]);

    // Connect when component mounts and isActive changes
    useEffect(() => {
        if (isAdmin && isActive) {
            initVNC();
        }

        return () => {
            if (rfbRef.current) {
                rfbRef.current.disconnect();
                rfbRef.current = null;
            }
        };
    }, [isAdmin, isActive, initVNC]);

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
                    Browser view available when test is running
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
                                background: isConnected
                                    ? 'rgba(16, 185, 129, 0.1)'
                                    : 'rgba(239, 68, 68, 0.1)',
                                color: isConnected ? 'var(--success)' : 'var(--danger)',
                                border: `1px solid ${isConnected ? 'rgba(16, 185, 129, 0.3)' : 'rgba(239, 68, 68, 0.3)'}`,
                            }}
                        >
                            {isConnected ? <Wifi size={12} /> : <WifiOff size={12} />}
                            {isConnected ? 'Connected' : isLoading ? 'Connecting...' : 'Disconnected'}
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
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    padding: '0.5rem',
                    minHeight: isFullscreen ? 'calc(100vh - 60px)' : '500px',
                    background: '#000',
                }}
            >
                {vncAvailable === false ? (
                    // VNC not available - show local dev message
                    <div
                        style={{
                            display: 'flex',
                            flexDirection: 'column',
                            alignItems: 'center',
                            gap: '1.5rem',
                            color: 'var(--text-secondary)',
                            maxWidth: '400px',
                            textAlign: 'center',
                            padding: '2rem',
                        }}
                    >
                        <Server size={48} color="var(--primary)" />
                        <div>
                            <h3 style={{ color: 'var(--text-primary)', marginBottom: '0.5rem', fontSize: '1.1rem' }}>
                                VNC Not Available
                            </h3>
                            <p style={{ fontSize: '0.9rem', lineHeight: 1.6 }}>
                                Live browser view requires the VNC server which runs in Docker production mode.
                            </p>
                        </div>
                        <div
                            style={{
                                background: 'rgba(59, 130, 246, 0.1)',
                                border: '1px solid rgba(59, 130, 246, 0.3)',
                                borderRadius: '8px',
                                padding: '1rem',
                                width: '100%',
                            }}
                        >
                            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.5rem' }}>
                                <Terminal size={16} color="var(--primary)" />
                                <span style={{ fontWeight: 600, color: 'var(--primary)', fontSize: '0.85rem' }}>
                                    For Docker production:
                                </span>
                            </div>
                            <code
                                style={{
                                    display: 'block',
                                    background: 'rgba(0,0,0,0.3)',
                                    padding: '0.5rem',
                                    borderRadius: '4px',
                                    fontSize: '0.8rem',
                                    color: '#e6edf3',
                                }}
                            >
                                docker compose -f docker-compose.prod.yml up
                            </code>
                        </div>
                        <p style={{ fontSize: '0.8rem', opacity: 0.7 }}>
                            Switch to the <strong>Log</strong> tab to view execution output.
                        </p>
                    </div>
                ) : error ? (
                    <div
                        style={{
                            display: 'flex',
                            flexDirection: 'column',
                            alignItems: 'center',
                            gap: '1rem',
                            color: 'var(--text-secondary)',
                        }}
                    >
                        <WifiOff size={32} color="var(--danger)" />
                        <span style={{ color: 'var(--danger)' }}>{error}</span>
                        <button
                            onClick={initVNC}
                            className="btn btn-secondary"
                            style={{ fontSize: '0.85rem' }}
                        >
                            Retry Connection
                        </button>
                    </div>
                ) : isLoading && !isConnected ? (
                    <div
                        style={{
                            display: 'flex',
                            flexDirection: 'column',
                            alignItems: 'center',
                            gap: '1rem',
                            color: 'var(--text-secondary)',
                        }}
                    >
                        <div className="loading-spinner" style={{ width: '32px', height: '32px' }} />
                        <span>Connecting to browser...</span>
                    </div>
                ) : (
                    <div
                        ref={canvasContainerRef}
                        style={{
                            width: '100%',
                            height: '100%',
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                        }}
                    />
                )}
            </div>
        </div>
    );
}

export default LiveBrowserView;
