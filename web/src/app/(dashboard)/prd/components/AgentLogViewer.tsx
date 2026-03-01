'use client';

import React, { useState, useEffect, useRef, useCallback } from 'react';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Terminal, ChevronRight, ChevronDown, Copy, Check } from 'lucide-react';
import { API_BASE } from '@/lib/api';

const API_BASE_API = `${API_BASE}/api`;

interface AgentLogViewerProps {
    generationId: number | undefined;
    isRunning: boolean;
}

export function AgentLogViewer({ generationId, isRunning }: AgentLogViewerProps) {
    const [streamingLog, setStreamingLog] = useState<string>('');
    const [isStreaming, setIsStreaming] = useState(false);
    const [showLogs, setShowLogs] = useState(false);
    const [copied, setCopied] = useState(false);
    const logEndRef = useRef<HTMLDivElement>(null);
    const eventSourceRef = useRef<EventSource | null>(null);

    // Auto-scroll log to bottom
    useEffect(() => {
        if (logEndRef.current && showLogs) {
            logEndRef.current.scrollIntoView({ behavior: 'smooth' });
        }
    }, [streamingLog, showLogs]);

    // Connect to SSE when generation starts
    useEffect(() => {
        if (isRunning && generationId && !eventSourceRef.current) {
            setShowLogs(true);
            setStreamingLog('Connecting to log stream...\n');
            setIsStreaming(true);

            const eventSource = new EventSource(`${API_BASE_API}/prd/generation/${generationId}/log/stream`);
            eventSourceRef.current = eventSource;

            eventSource.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data);

                    if (data.status === 'connected') {
                        setStreamingLog(prev => prev + '--- Connected to agent ---\n');
                    } else if (data.status === 'waiting') {
                        // Skip keepalive messages
                    } else if (data.log) {
                        setStreamingLog(prev => prev + data.log);
                    }

                    if (data.status === 'complete' || data.status === 'timeout' || data.status === 'error') {
                        setIsStreaming(false);
                        if (data.status === 'complete') {
                            setStreamingLog(prev => prev + `\n--- Generation ${data.final_status} ---\n`);
                        }
                        eventSource.close();
                        eventSourceRef.current = null;
                    }
                } catch (e) {
                    console.error('Error parsing SSE data:', e);
                }
            };

            eventSource.onerror = () => {
                setStreamingLog(prev => prev + '\n--- Connection lost ---\n');
                setIsStreaming(false);
                eventSource.close();
                eventSourceRef.current = null;
            };
        }

        // Cleanup when generation completes
        if (!isRunning && eventSourceRef.current) {
            eventSourceRef.current.close();
            eventSourceRef.current = null;
            setIsStreaming(false);
        }

        return () => {
            if (eventSourceRef.current) {
                eventSourceRef.current.close();
                eventSourceRef.current = null;
            }
        };
    }, [isRunning, generationId]);

    // Clear logs when generationId changes
    useEffect(() => {
        setStreamingLog('');
        setShowLogs(false);
    }, [generationId]);

    const handleCopy = useCallback(() => {
        if (streamingLog) {
            navigator.clipboard.writeText(streamingLog);
            setCopied(true);
            setTimeout(() => setCopied(false), 2000);
        }
    }, [streamingLog]);

    const lineCount = streamingLog ? streamingLog.split('\n').filter(Boolean).length : 0;

    if (!showLogs && !streamingLog) return null;

    return (
        <div className="mx-5 mt-3">
            <div className="flex items-center justify-between mb-2">
                <button
                    onClick={() => setShowLogs(!showLogs)}
                    className="flex items-center gap-2 text-sm transition-colors"
                    style={{ color: 'var(--text-secondary)' }}
                    onMouseEnter={(e) => (e.currentTarget.style.color = 'var(--text)')}
                    onMouseLeave={(e) => (e.currentTarget.style.color = 'var(--text-secondary)')}
                >
                    {showLogs ? (
                        <ChevronDown className="h-4 w-4" />
                    ) : (
                        <ChevronRight className="h-4 w-4" />
                    )}
                    <Terminal className="h-4 w-4" />
                    <span>Agent Logs</span>
                    {lineCount > 0 && (
                        <span className="text-xs" style={{ color: 'var(--text-tertiary)' }}>
                            ({lineCount} lines)
                        </span>
                    )}
                    {isStreaming && (
                        <span className="inline-flex items-center gap-1.5 ml-2 px-2 py-0.5 rounded-full bg-green-500/10 text-xs text-green-400">
                            <span className="relative flex h-2 w-2">
                                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75" />
                                <span className="relative inline-flex rounded-full h-2 w-2 bg-green-500" />
                            </span>
                            Live
                        </span>
                    )}
                </button>
                {showLogs && streamingLog && (
                    <button
                        onClick={handleCopy}
                        className="flex items-center gap-1.5 text-xs transition-colors"
                        style={{ color: 'var(--text-tertiary)' }}
                        onMouseEnter={(e) => (e.currentTarget.style.color = 'var(--text-secondary)')}
                        onMouseLeave={(e) => (e.currentTarget.style.color = 'var(--text-tertiary)')}
                    >
                        {copied ? (
                            <Check className="h-3.5 w-3.5 text-green-400" />
                        ) : (
                            <Copy className="h-3.5 w-3.5" />
                        )}
                        {copied ? 'Copied' : 'Copy'}
                    </button>
                )}
            </div>
            {showLogs && (
                <div
                    className="rounded-xl overflow-hidden"
                    style={{
                        background: 'var(--code-bg)',
                        border: '1px solid var(--border-subtle)',
                    }}
                >
                    {/* Terminal header bar */}
                    <div
                        className="h-8 flex items-center justify-between px-3"
                        style={{
                            borderBottom: '1px solid var(--border-subtle)',
                            background: 'rgba(255,255,255,0.02)',
                        }}
                    >
                        <div className="terminal-dots">
                            <div className="terminal-dot terminal-dot-red" />
                            <div className="terminal-dot terminal-dot-yellow" />
                            <div className="terminal-dot terminal-dot-green" />
                        </div>
                        <span
                            className="text-[10px] font-mono uppercase tracking-wider"
                            style={{ color: 'var(--text-tertiary)' }}
                        >
                            Agent Output
                        </span>
                        <div className="w-[54px]" /> {/* Spacer for centering */}
                    </div>
                    <ScrollArea className="h-56">
                        <pre
                            className="p-4 text-[12px] leading-5 font-mono whitespace-pre-wrap break-words"
                            style={{ color: 'var(--text-secondary)' }}
                        >
                            {streamingLog || 'Waiting for logs...'}
                            <div ref={logEndRef} />
                        </pre>
                    </ScrollArea>
                </div>
            )}
        </div>
    );
}
