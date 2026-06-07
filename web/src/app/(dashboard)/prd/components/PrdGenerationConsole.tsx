'use client';

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import {
    Activity,
    Archive,
    AlertCircle,
    Check,
    ChevronDown,
    ChevronRight,
    Clock,
    Copy,
    FileText,
    Globe,
    Monitor,
    Terminal,
    Wrench,
    XCircle,
} from 'lucide-react';

import { LiveBrowserView } from '@/components/LiveBrowserView';
import { ScrollArea } from '@/components/ui/scroll-area';
import { API_BASE } from '@/lib/api';
import type { GenerationResult, PrdArtifact, PrdGenerationEvent } from './types';
import { getStageDisplay } from './types';

const API_BASE_API = `${API_BASE}/api`;

type ConsoleTab = 'summary' | 'browser' | 'timeline' | 'logs' | 'files';

interface PrdGenerationConsoleProps {
    generation: GenerationResult | undefined;
    isRunning: boolean;
    currentTargetUrl?: string;
}

function resolveArtifactHref(path: string): string {
    return path.startsWith('/artifacts') ? `${API_BASE}${path}` : path;
}

function formatEventTime(value: string): string {
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? '' : date.toLocaleTimeString();
}

function formatElapsed(start?: Date, end?: Date): string {
    if (!start) return 'Not started';
    const stop = end || new Date();
    const seconds = Math.max(0, Math.floor((stop.getTime() - start.getTime()) / 1000));
    const minutes = Math.floor(seconds / 60);
    const remainder = seconds % 60;
    return minutes > 0 ? `${minutes}m ${remainder}s` : `${remainder}s`;
}

function eventAccent(event: PrdGenerationEvent): string {
    if (event.level === 'error' || event.event_type === 'failed') return '#ef4444';
    if (event.level === 'warning' || event.event_type === 'cancelled') return '#f59e0b';
    if (event.event_type === 'completed') return '#22c55e';
    if (event.role === 'browser_agent') return '#38bdf8';
    if (event.role === 'context_retriever') return '#a78bfa';
    return 'var(--primary)';
}

function latestTool(events: PrdGenerationEvent[]): string | null {
    for (const event of [...events].reverse()) {
        const payload = event.payload || {};
        if (typeof payload.tool_label === 'string') return payload.tool_label;
        if (typeof payload.last_tool === 'string') return payload.last_tool;
    }
    return null;
}

function groupByRole(events: PrdGenerationEvent[]): Record<string, PrdGenerationEvent[]> {
    return events.reduce<Record<string, PrdGenerationEvent[]>>((acc, event) => {
        const role = event.role || 'agent';
        acc[role] = acc[role] || [];
        acc[role].push(event);
        return acc;
    }, {});
}

export function PrdGenerationConsole({ generation, isRunning, currentTargetUrl = '' }: PrdGenerationConsoleProps) {
    const generationId = generation?.generationId;
    const [activeTab, setActiveTab] = useState<ConsoleTab>('summary');
    const [isExpanded, setIsExpanded] = useState(false);
    const [events, setEvents] = useState<PrdGenerationEvent[]>([]);
    const [streamingLog, setStreamingLog] = useState('');
    const [copied, setCopied] = useState(false);
    const eventSourceRef = useRef<EventSource | null>(null);
    const logSourceRef = useRef<EventSource | null>(null);
    const logEndRef = useRef<HTMLDivElement>(null);
    const tabRefs = useRef<Array<HTMLButtonElement | null>>([]);
    const eventsRef = useRef<PrdGenerationEvent[]>([]);
    const eventReconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

    useEffect(() => {
        setEvents([]);
        eventsRef.current = [];
        setStreamingLog('');
        setActiveTab('summary');
        setIsExpanded(isRunning || generation?.status === 'failed' || generation?.status === 'cancelled');
    }, [generationId, generation?.status, isRunning]);

    useEffect(() => {
        eventsRef.current = events;
    }, [events]);

    useEffect(() => {
        if (!generationId) return;
        let cancelled = false;
        fetch(`${API_BASE_API}/prd/generation/${generationId}/events`)
            .then(res => res.ok ? res.json() : [])
            .then((data) => {
                if (!cancelled && Array.isArray(data)) {
                    setEvents(prev => {
                        const bySequence = new Map<number, PrdGenerationEvent>();
                        [...data, ...prev].forEach(item => bySequence.set(item.sequence, item));
                        return [...bySequence.values()].sort((a, b) => a.sequence - b.sequence);
                    });
                }
            })
            .catch(() => {
                if (!cancelled) setEvents([]);
            });
        return () => {
            cancelled = true;
        };
    }, [generationId]);

    useEffect(() => {
        if (!generationId || !isRunning) return;
        let cancelled = false;
        let attempts = 0;

        const mergeEvents = (incoming: PrdGenerationEvent[]) => {
            setEvents(prev => {
                const bySequence = new Map<number, PrdGenerationEvent>();
                [...prev, ...incoming].forEach(item => bySequence.set(item.sequence, item));
                return [...bySequence.values()].sort((a, b) => a.sequence - b.sequence);
            });
        };

        const backfillEvents = async () => {
            const lastSequence = eventsRef.current.reduce((max, item) => Math.max(max, item.sequence), 0);
            try {
                const res = await fetch(`${API_BASE_API}/prd/generation/${generationId}/events?after_sequence=${lastSequence}`);
                if (!cancelled && res.ok) {
                    const data = await res.json();
                    if (Array.isArray(data)) mergeEvents(data);
                }
            } catch {
                // Polling still owns generation status; SSE backfill can retry.
            }
        };

        const connect = () => {
            if (cancelled || eventSourceRef.current) return;
            const lastSequence = eventsRef.current.reduce((max, item) => Math.max(max, item.sequence), 0);
            const source = new EventSource(`${API_BASE_API}/prd/generation/${generationId}/events/stream?after_sequence=${lastSequence}`);
            eventSourceRef.current = source;
            source.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data);
                    if (data.event) {
                        attempts = 0;
                        mergeEvents([data.event]);
                    }
                    if (data.status === 'complete' || data.status === 'error') {
                        source.close();
                        eventSourceRef.current = null;
                    }
                } catch {
                    source.close();
                    eventSourceRef.current = null;
                    scheduleReconnect();
                }
            };
            source.onerror = () => {
                source.close();
                eventSourceRef.current = null;
                scheduleReconnect();
            };
        };

        const scheduleReconnect = () => {
            if (cancelled) return;
            if (eventReconnectTimerRef.current) clearTimeout(eventReconnectTimerRef.current);
            attempts += 1;
            const delay = Math.min(15000, 750 * Math.pow(2, Math.min(attempts, 5)));
            eventReconnectTimerRef.current = setTimeout(async () => {
                eventReconnectTimerRef.current = null;
                await backfillEvents();
                connect();
            }, delay);
        };

        void backfillEvents();
        connect();
        return () => {
            cancelled = true;
            if (eventReconnectTimerRef.current) clearTimeout(eventReconnectTimerRef.current);
            eventReconnectTimerRef.current = null;
            eventSourceRef.current?.close();
            eventSourceRef.current = null;
        };
    }, [generationId, isRunning]);

    useEffect(() => {
        if (!generationId || !isExpanded || logSourceRef.current) return;
        setStreamingLog('Connecting to log stream...\n');
        const source = new EventSource(`${API_BASE_API}/prd/generation/${generationId}/log/stream`);
        logSourceRef.current = source;
        source.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                if (data.status === 'connected') {
                    setStreamingLog(prev => prev + '--- Connected to agent ---\n');
                } else if (data.log) {
                    setStreamingLog(prev => prev + data.log);
                }
                if (data.status === 'reconnecting') {
                    setStreamingLog(prev => prev + '\n--- No new log output; reconnecting status remains active ---\n');
                }
                if (data.status === 'complete' || data.status === 'error') {
                    source.close();
                    logSourceRef.current = null;
                }
            } catch {
                source.close();
                logSourceRef.current = null;
            }
        };
        source.onerror = () => {
            setStreamingLog(prev => prev + '\n--- Connection lost ---\n');
            source.close();
            logSourceRef.current = null;
        };
        return () => {
            source.close();
            logSourceRef.current = null;
        };
    }, [generationId, isExpanded]);

    useEffect(() => {
        if (activeTab === 'logs') {
            logEndRef.current?.scrollIntoView({ behavior: 'smooth' });
        }
    }, [activeTab, streamingLog]);

    const artifacts = generation?.artifacts || [];
    const imageArtifacts = artifacts.filter(artifact => artifact.type === 'image');
    const groupedEvents = useMemo(() => groupByRole(events), [events]);
    const lastEvent = events[events.length - 1] || generation?.latestEvent || null;
    const lastTool = latestTool(events) || generation?.browserLastTool || generation?.queueTelemetry?.progress?.last_tool || null;
    const failedEvent = [...events].reverse().find(event => event.level === 'error' || event.event_type === 'failed');
    const elapsed = formatElapsed(generation?.startedAt || generation?.createdAt, generation?.completedAt);
    const eventCount = events.length || generation?.eventsCount || 0;
    const lastEventTime = lastEvent ? formatEventTime(lastEvent.created_at) : null;
    const queueHealth = generation?.agentQueueHealth
        ? `${generation.agentQueueHealth.worker_count ?? 0} workers, ${generation.agentQueueHealth.running_tasks ?? 0} running`
        : 'No queue telemetry';
    const hasUsefulDetails =
        isRunning ||
        generation?.status === 'failed' ||
        generation?.status === 'cancelled' ||
        eventCount > 0 ||
        artifacts.length > 0 ||
        Boolean(generation?.latestImage) ||
        Boolean(streamingLog);
    const settingsTargetUrl = currentTargetUrl.trim();
    const hasSettingsTargetUrl = settingsTargetUrl.length > 0;
    const isPrdOnlyRun = generation?.liveBrowserRequested !== true;
    const shouldWarnStaleLiveIntent = isPrdOnlyRun && hasSettingsTargetUrl;

    const tabs = useMemo<Array<{ key: ConsoleTab; label: string; icon: React.ComponentType<{ className?: string }> }>>(() => [
        { key: 'summary', label: 'Summary', icon: Activity },
        { key: 'browser', label: 'Browser', icon: Monitor },
        { key: 'timeline', label: 'Timeline', icon: Clock },
        { key: 'logs', label: 'Logs', icon: Terminal },
        { key: 'files', label: 'Files', icon: Archive },
    ], []);

    const handleCopy = useCallback(() => {
        if (!streamingLog) return;
        navigator.clipboard.writeText(streamingLog);
        setCopied(true);
        setTimeout(() => setCopied(false), 1600);
    }, [streamingLog]);

    const handleTabKey = useCallback((event: React.KeyboardEvent<HTMLButtonElement>, index: number) => {
        if (event.key !== 'ArrowRight' && event.key !== 'ArrowLeft' && event.key !== 'Home' && event.key !== 'End') return;
        event.preventDefault();

        let nextIndex = index;
        if (event.key === 'ArrowRight') nextIndex = (index + 1) % tabs.length;
        if (event.key === 'ArrowLeft') nextIndex = (index - 1 + tabs.length) % tabs.length;
        if (event.key === 'Home') nextIndex = 0;
        if (event.key === 'End') nextIndex = tabs.length - 1;

        setActiveTab(tabs[nextIndex].key);
        tabRefs.current[nextIndex]?.focus();
    }, [tabs]);

    if (!generationId || !hasUsefulDetails) return null;

    return (
        <div className="prd-console-shell">
            <style>{`
                .prd-console-shell {
                    overflow: hidden;
                    border: 1px solid var(--border-subtle);
                    border-radius: 8px;
                    background: rgba(255,255,255,0.018);
                }

                .prd-console-toggle:focus-visible,
                .prd-console-tab:focus-visible,
                .prd-console-button:focus-visible,
                .prd-console-file:focus-visible {
                    outline: none;
                    box-shadow: 0 0 0 2px rgba(59,130,246,0.45);
                }

                .prd-console-toggle {
                    display: flex;
                    width: 100%;
                    align-items: center;
                    justify-content: space-between;
                    gap: 0.75rem;
                    padding: 0.625rem 0.75rem;
                    border: 0;
                    background: transparent;
                    text-align: left;
                    transition: background-color 0.2s;
                }

                .prd-console-toggle:hover {
                    background: rgba(255,255,255,0.03);
                }

                .prd-console-toggle-main {
                    display: flex;
                    min-width: 0;
                    align-items: center;
                    gap: 0.5rem;
                }

                .prd-console-toggle-icon {
                    width: 16px;
                    height: 16px;
                    flex: 0 0 16px;
                }

                .prd-console-title-stack {
                    min-width: 0;
                }

                .prd-console-title {
                    color: var(--text);
                    font-size: 0.875rem;
                    font-weight: 650;
                    line-height: 1.2;
                }

                .prd-console-subtitle {
                    margin-top: 0.125rem;
                    overflow: hidden;
                    color: var(--text-tertiary);
                    font-size: 0.75rem;
                    line-height: 1.25;
                    text-overflow: ellipsis;
                    white-space: nowrap;
                }

                .prd-console-counts {
                    display: flex;
                    flex: 0 0 auto;
                    align-items: center;
                    gap: 0.5rem;
                    color: var(--text-tertiary);
                    font-size: 0.6875rem;
                    line-height: 1;
                    white-space: nowrap;
                }

                .prd-console-live-dot {
                    width: 8px;
                    height: 8px;
                    flex: 0 0 8px;
                    border-radius: 999px;
                    background: #3b82f6;
                    animation: pulse 2s ease-in-out infinite;
                }

                .prd-console-tabs-shell {
                    border-top: 1px solid var(--border-subtle);
                    border-bottom: 1px solid var(--border-subtle);
                    padding: 0.5rem 0.75rem;
                }

                .prd-console-tablist {
                    display: flex;
                    align-items: center;
                    gap: 0.25rem;
                    overflow-x: auto;
                    scrollbar-width: thin;
                }

                .prd-console-tab {
                    display: inline-flex;
                    height: 32px;
                    flex: 0 0 auto;
                    align-items: center;
                    justify-content: center;
                    gap: 0.375rem;
                    padding: 0 0.625rem;
                    border: 1px solid transparent;
                    border-radius: 7px;
                    background: transparent;
                    color: var(--text-secondary);
                    font-size: 0.75rem;
                    font-weight: 650;
                    line-height: 1;
                    white-space: nowrap;
                    transition: background-color 0.2s, color 0.2s;
                }

                .prd-console-tab:hover {
                    background: rgba(255,255,255,0.035);
                }

                .prd-console-tab.is-active {
                    background: var(--primary-glow);
                    color: var(--primary);
                }

                .prd-console-tab-icon {
                    width: 16px;
                    height: 16px;
                    flex: 0 0 16px;
                }

                .prd-console-panel {
                    padding: 0.75rem;
                }

                .prd-console-summary-grid {
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
                    gap: 0.75rem;
                    padding: 0.75rem;
                }

                .prd-console-summary-card {
                    min-width: 0;
                    border: 1px solid var(--border-subtle);
                    border-radius: 8px;
                    background: var(--surface);
                    padding: 0.5rem 0.75rem;
                }

                .prd-console-summary-label,
                .prd-console-role-label,
                .prd-console-log-title {
                    color: var(--text-tertiary);
                    font-family: var(--font-mono);
                    font-size: 0.625rem;
                    font-weight: 700;
                    letter-spacing: 0.04em;
                    line-height: 1.2;
                    text-transform: uppercase;
                }

                .prd-console-summary-value {
                    margin-top: 0.25rem;
                    color: var(--text);
                    font-size: 14px;
                    line-height: 1.35;
                    overflow-wrap: anywhere;
                }

                .prd-console-alert {
                    display: flex;
                    grid-column: 1 / -1;
                    align-items: flex-start;
                    gap: 0.5rem;
                    border: 1px solid;
                    border-radius: 8px;
                    padding: 0.5rem 0.75rem;
                }

                .prd-console-alert-icon,
                .prd-console-file-icon {
                    width: 16px;
                    height: 16px;
                    flex: 0 0 16px;
                }

                .prd-console-alert-icon {
                    margin-top: 0.125rem;
                }

                .prd-console-alert-body {
                    min-width: 0;
                }

                .prd-console-alert-title {
                    color: var(--text);
                    font-size: 0.875rem;
                    line-height: 1.25;
                }

                .prd-console-alert-copy {
                    margin-top: 0.125rem;
                    color: var(--text-secondary);
                    font-size: 0.75rem;
                    line-height: 1.35;
                }

                .prd-console-browser-note,
                .prd-console-empty,
                .prd-console-file-empty {
                    color: var(--text-tertiary);
                    font-size: 0.8125rem;
                    line-height: 1.4;
                }

                .prd-console-browser-note {
                    margin-top: 0.75rem;
                    font-size: 0.75rem;
                }

                .prd-console-browser-diagnostics {
                    display: flex;
                    flex-wrap: wrap;
                    gap: 0.5rem;
                    margin-top: 0.75rem;
                    color: var(--text-tertiary);
                    font-size: 0.72rem;
                }

                .prd-console-browser-diagnostics span {
                    display: inline-flex;
                    align-items: center;
                    gap: 0.35rem;
                    min-height: 1.5rem;
                    padding: 0.2rem 0.45rem;
                    border: 1px solid rgba(255,255,255,0.08);
                    border-radius: 6px;
                    background: rgba(255,255,255,0.03);
                }

                .prd-console-browser-diagnostics strong {
                    color: var(--text-secondary);
                    font-weight: 600;
                }

                .prd-console-timeline-scroll {
                    height: 320px;
                }

                .prd-console-timeline-content {
                    display: flex;
                    flex-direction: column;
                    gap: 1rem;
                    padding: 0.75rem;
                }

                .prd-console-role-label {
                    margin-bottom: 0.5rem;
                }

                .prd-console-event-list {
                    display: flex;
                    flex-direction: column;
                    gap: 0.5rem;
                }

                .prd-console-event-row {
                    display: flex;
                    min-width: 0;
                    gap: 0.5rem;
                    border: 1px solid var(--border-subtle);
                    border-radius: 8px;
                    background: var(--surface);
                    padding: 0.5rem 0.75rem;
                }

                .prd-console-event-dot {
                    width: 8px;
                    height: 8px;
                    flex: 0 0 8px;
                    margin-top: 0.375rem;
                    border-radius: 999px;
                }

                .prd-console-event-main {
                    min-width: 0;
                    flex: 1 1 auto;
                }

                .prd-console-event-header {
                    display: flex;
                    min-width: 0;
                    align-items: flex-start;
                    gap: 0.5rem;
                }

                .prd-console-event-message {
                    min-width: 0;
                    color: var(--text);
                    font-size: 0.875rem;
                    line-height: 1.35;
                    overflow-wrap: anywhere;
                    white-space: normal;
                }

                .prd-console-event-time {
                    flex: 0 0 auto;
                    color: var(--text-tertiary);
                    font-size: 0.625rem;
                    line-height: 1;
                }

                .prd-console-event-meta {
                    display: flex;
                    min-width: 0;
                    flex-wrap: wrap;
                    align-items: center;
                    gap: 0.375rem;
                    margin-top: 0.25rem;
                    color: var(--text-tertiary);
                    font-size: 0.6875rem;
                    line-height: 1.25;
                }

                .prd-console-event-meta-icon {
                    width: 12px;
                    height: 12px;
                    flex: 0 0 12px;
                }

                .prd-console-logs-header {
                    display: flex;
                    height: 32px;
                    align-items: center;
                    justify-content: space-between;
                    gap: 0.75rem;
                    border-bottom: 1px solid var(--border-subtle);
                    padding: 0 0.75rem;
                }

                .prd-console-button {
                    display: inline-flex;
                    align-items: center;
                    justify-content: center;
                    gap: 0.375rem;
                    height: 28px;
                    padding: 0 0.5rem;
                    border: 1px solid transparent;
                    border-radius: 7px;
                    background: transparent;
                    color: var(--text-tertiary);
                    font-size: 0.75rem;
                    line-height: 1;
                    transition: background-color 0.2s, color 0.2s;
                }

                .prd-console-button:hover {
                    background: rgba(255,255,255,0.04);
                    color: var(--text-secondary);
                }

                .prd-console-copy-icon {
                    width: 16px;
                    height: 16px;
                    flex: 0 0 16px;
                }

                .prd-console-copy-icon.is-success {
                    color: #4ade80;
                }

                .prd-console-log-scroll {
                    height: 288px;
                }

                .prd-console-log-body {
                    min-width: 0;
                }

                .prd-console-log-pre {
                    margin: 0;
                    padding: 1rem;
                    color: var(--text-secondary);
                    font-family: var(--font-mono);
                    font-size: 12px;
                    line-height: 1.65;
                    white-space: pre-wrap;
                    overflow-wrap: anywhere;
                }

                .prd-console-file-empty {
                    border: 1px solid var(--border-subtle);
                    border-radius: 8px;
                    padding: 1rem;
                }

                .prd-console-file-grid {
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
                    gap: 0.5rem;
                }

                .prd-console-file {
                    display: flex;
                    min-width: 0;
                    align-items: center;
                    gap: 0.5rem;
                    border: 1px solid var(--border-subtle);
                    border-radius: 8px;
                    padding: 0.5rem 0.75rem;
                    color: var(--text-secondary);
                    text-decoration: none;
                    transition: background-color 0.2s, color 0.2s;
                }

                .prd-console-file:hover {
                    background: rgba(255,255,255,0.05);
                    color: var(--text);
                }

                .prd-console-file-name {
                    min-width: 0;
                    overflow: hidden;
                    color: inherit;
                    font-size: 0.875rem;
                    line-height: 1.25;
                    text-overflow: ellipsis;
                    white-space: nowrap;
                }

                .prd-console-file-type {
                    margin-left: auto;
                    color: var(--text-tertiary);
                    font-size: 0.625rem;
                    line-height: 1;
                    text-transform: uppercase;
                }

                @media (max-width: 720px) {
                    .prd-console-toggle {
                        align-items: flex-start;
                    }

                    .prd-console-counts {
                        flex-direction: column;
                        align-items: flex-end;
                        gap: 0.375rem;
                    }
                }
            `}</style>
            <button
                type="button"
                onClick={() => setIsExpanded(prev => !prev)}
                className="prd-console-toggle"
                aria-expanded={isExpanded}
            >
                <div className="prd-console-toggle-main">
                    {isExpanded ? (
                        <ChevronDown className="prd-console-toggle-icon" style={{ color: 'var(--text-secondary)' }} />
                    ) : (
                        <ChevronRight className="prd-console-toggle-icon" style={{ color: 'var(--text-secondary)' }} />
                    )}
                    <Activity className="prd-console-toggle-icon" style={{ color: isRunning ? 'var(--primary)' : 'var(--text-secondary)' }} />
                    <div className="prd-console-title-stack">
                        <div className="prd-console-title">
                            Run Details
                        </div>
                        <div className="prd-console-subtitle">
                            {generation.status === 'completed'
                                ? artifacts.length || eventCount
                                    ? 'Review captured timeline, logs, and files.'
                                    : 'Generated successfully without extra run artifacts.'
                                : generation.status === 'failed'
                                    ? failedEvent?.message || generation.error || 'Generation failed.'
                                    : generation.status === 'cancelled'
                                        ? 'Generation was cancelled. Timeline and logs remain available.'
                                        : generation.message || 'Generation is in progress.'}
                        </div>
                    </div>
                </div>
                <div className="prd-console-counts">
                    {isRunning && <span className="prd-console-live-dot" />}
                    {eventCount > 0 && <span>{eventCount} events</span>}
                    {artifacts.length > 0 && <span>{artifacts.length} files</span>}
                </div>
            </button>

            {isExpanded && (
                <>
            <div className="prd-console-tabs-shell">
                <div className="prd-console-tablist" role="tablist" aria-label="PRD run details">
                    {tabs.map((tab, index) => {
                        const Icon = tab.icon;
                        const isActive = activeTab === tab.key;
                        const tabId = `prd-console-${generationId}-${tab.key}-tab`;
                        const panelId = `prd-console-${generationId}-${tab.key}-panel`;
                        return (
                            <button
                                type="button"
                                key={tab.key}
                                id={tabId}
                                role="tab"
                                aria-selected={isActive}
                                aria-controls={panelId}
                                tabIndex={isActive ? 0 : -1}
                                ref={(element) => {
                                    tabRefs.current[index] = element;
                                }}
                                onClick={() => setActiveTab(tab.key)}
                                onKeyDown={(event) => handleTabKey(event, index)}
                                className={`prd-console-tab${isActive ? ' is-active' : ''}`}
                            >
                                <Icon className="prd-console-tab-icon" />
                                {tab.label}
                            </button>
                        );
                    })}
                </div>
            </div>

            {activeTab === 'summary' && (
                <div
                    id={`prd-console-${generationId}-summary-panel`}
                    role="tabpanel"
                    aria-labelledby={`prd-console-${generationId}-summary-tab`}
                    className="prd-console-summary-grid"
                >
                    {[
                        ['Status', generation.status === 'completed' ? 'Generated successfully' : getStageDisplay(generation.stage, generation.message)],
                        ['Elapsed', elapsed],
                        ['Last activity', lastTool || lastEvent?.message || 'No tool calls recorded'],
                        ['Browser captures', imageArtifacts.length ? `${imageArtifacts.length} screenshots` : 'No screenshots captured'],
                        ['Agent task', generation.agentTaskStatus || generation.agentTaskId || 'Not enqueued'],
                        ['Worker', generation.agentWorkerId || 'Not assigned'],
                        ['Queue health', queueHealth],
                        ['Last event', lastEventTime || 'No events yet'],
                        ['Runtime', generation.runtimeMessage || (isPrdOnlyRun ? 'PRD-only generation' : 'Ready')],
                    ].map(([label, value]) => (
                        <div key={label} className="prd-console-summary-card">
                            <div className="prd-console-summary-label">{label}</div>
                            <div className="prd-console-summary-value">{value}</div>
                        </div>
                    ))}
                    {(generation.status === 'failed' || generation.status === 'cancelled') && (
                        <div className="prd-console-alert" style={{ borderColor: generation.status === 'failed' ? 'rgba(239,68,68,0.35)' : 'rgba(245,158,11,0.35)', background: generation.status === 'failed' ? 'rgba(239,68,68,0.08)' : 'rgba(245,158,11,0.08)' }}>
                            <XCircle className="prd-console-alert-icon" style={{ color: generation.status === 'failed' ? '#ef4444' : '#f59e0b' }} />
                            <div className="prd-console-alert-body">
                                <div className="prd-console-alert-title">{generation.status === 'failed' ? 'Failed run' : 'Cancelled run'}</div>
                                <div className="prd-console-alert-copy">
                                    {failedEvent?.message || generation.error || generation.message || 'Timeline, logs, and artifacts remain available for review.'}
                                </div>
                            </div>
                        </div>
                    )}
                </div>
            )}

            {activeTab === 'browser' && (
                <div
                    id={`prd-console-${generationId}-browser-panel`}
                    role="tabpanel"
                    aria-labelledby={`prd-console-${generationId}-browser-tab`}
                    className="prd-console-panel"
                >
                    {shouldWarnStaleLiveIntent ? (
                        <div className="prd-console-alert" style={{ borderColor: 'rgba(245,158,11,0.35)', background: 'rgba(245,158,11,0.08)' }}>
                            <AlertCircle className="prd-console-alert-icon" style={{ color: '#f59e0b' }} />
                            <div className="prd-console-alert-body">
                                <div className="prd-console-alert-title">Live browser not active for this run</div>
                                <div className="prd-console-alert-copy">
                                    This run was started without live browser validation. Stop and regenerate to use the Target URL.
                                </div>
                                <div className="prd-console-alert-copy" style={{ marginTop: '0.35rem', color: 'var(--text-tertiary)' }}>
                                    Current Target URL: {settingsTargetUrl}
                                </div>
                            </div>
                        </div>
                    ) : (
                        <>
                            <LiveBrowserView
                                runId={`prd-generation-${generationId}`}
                                isActive={isRunning}
                                showHeader
                                onShowLog={() => setActiveTab('logs')}
                                artifacts={artifacts}
                                latestImage={generation.latestImage || null}
                                preferArtifactPreview={generation.liveViewAvailable === false}
                                statusMessage={generation.message || null}
                                liveViewAvailable={generation.liveViewAvailable === true}
                                liveBrowserRequested={generation.liveBrowserRequested === true}
                                runtimeMessage={generation.runtimeMessage || null}
                                vncUrl={generation.vncUrl || null}
                                displayDiagnostics={generation.displayDiagnostics || null}
                                browserActivitySeen={generation.browserActivitySeen === true}
                                browserActive={generation.browserActive === true}
                                browserLastTool={generation.browserLastTool || null}
                            />
                            <div className="prd-console-browser-diagnostics">
                                {[
                                    ['Runtime', generation.browserRuntime || 'unknown'],
                                    ['Live workers', String(generation.agentQueueHealth?.live_browser_worker_count ?? 'unknown')],
                                    ['Agent task', generation.agentTaskStatus || generation.agentTaskId || 'none'],
                                    ['Display', generation.displayDiagnostics?.display || 'none'],
                                    ['Processes', String(generation.displayDiagnostics?.browser_process_count ?? 0)],
                                    ['Windows', String(generation.displayDiagnostics?.browser_window_count ?? 0)],
                                    ['Last tool', generation.browserLastTool || 'none'],
                                ].map(([label, value]) => (
                                    <span key={label}>
                                        <strong>{label}</strong>
                                        {value}
                                    </span>
                                ))}
                            </div>
                            {artifacts.length === 0 && (
                                <div className="prd-console-browser-note">
                                    {isPrdOnlyRun
                                        ? 'This run was generated from PRD context only. A Target URL is required for a live browser window.'
                                        : generation.status === 'completed'
                                        ? 'No browser captures were produced for this completed run.'
                                        : 'Browser workspace is standing by. Screenshots and videos will appear here once the planner captures them.'}
                                </div>
                            )}
                        </>
                    )}
                </div>
            )}

            {activeTab === 'timeline' && (
                <ScrollArea
                    id={`prd-console-${generationId}-timeline-panel`}
                    role="tabpanel"
                    aria-labelledby={`prd-console-${generationId}-timeline-tab`}
                    className="prd-console-timeline-scroll"
                >
                    <div className="prd-console-timeline-content">
                        {events.length === 0 && (
                            <div className="prd-console-empty">
                                {generation.status === 'completed' ? 'No timeline events were recorded for this run.' : 'Waiting for structured events...'}
                            </div>
                        )}
                        {Object.entries(groupedEvents).map(([role, roleEvents]) => (
                            <div key={role}>
                                <div className="prd-console-role-label">{role.replaceAll('_', ' ')}</div>
                                <div className="prd-console-event-list">
                                    {roleEvents.map(event => (
                                        <div key={event.sequence} className="prd-console-event-row">
                                            <div className="prd-console-event-dot" style={{ background: eventAccent(event) }} />
                                            <div className="prd-console-event-main">
                                                <div className="prd-console-event-header">
                                                    <span className="prd-console-event-message">{event.message}</span>
                                                    <span className="prd-console-event-time">{formatEventTime(event.created_at)}</span>
                                                </div>
                                                <div className="prd-console-event-meta">
                                                    <span>#{event.sequence}</span>
                                                    <ChevronRight className="prd-console-event-meta-icon" />
                                                    <span>{event.event_type}</span>
                                                    {event.payload?.tool_label && (
                                                        <>
                                                            <Wrench className="prd-console-event-meta-icon" />
                                                            <span>{String(event.payload.tool_label)}</span>
                                                        </>
                                                    )}
                                                </div>
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            </div>
                        ))}
                    </div>
                </ScrollArea>
            )}

            {activeTab === 'logs' && (
                <div
                    id={`prd-console-${generationId}-logs-panel`}
                    role="tabpanel"
                    aria-labelledby={`prd-console-${generationId}-logs-tab`}
                >
                    <div className="prd-console-logs-header">
                        <span className="prd-console-log-title">Agent Output</span>
                        <button type="button" onClick={handleCopy} className="prd-console-button">
                            {copied ? <Check className="prd-console-copy-icon is-success" /> : <Copy className="prd-console-copy-icon" />}
                            {copied ? 'Copied' : 'Copy'}
                        </button>
                    </div>
                    <ScrollArea className="prd-console-log-scroll">
                        <div className="prd-console-log-body">
                            <pre className="prd-console-log-pre">{streamingLog || 'Waiting for logs...'}</pre>
                            <div ref={logEndRef} />
                        </div>
                    </ScrollArea>
                </div>
            )}

            {activeTab === 'files' && (
                <div
                    id={`prd-console-${generationId}-files-panel`}
                    role="tabpanel"
                    aria-labelledby={`prd-console-${generationId}-files-tab`}
                    className="prd-console-panel"
                >
                    {artifacts.length === 0 ? (
                        <div className="prd-console-file-empty">
                            {generation.status === 'completed'
                                ? 'No files were captured for this completed run.'
                                : 'No files yet. Screenshots, videos, and logs will appear here as the planner works.'}
                        </div>
                    ) : (
                        <div className="prd-console-file-grid">
                            {artifacts.map((artifact: PrdArtifact) => (
                                <a
                                    key={`${artifact.path}-${artifact.modified_at || ''}`}
                                    href={resolveArtifactHref(artifact.path)}
                                    target="_blank"
                                    rel="noreferrer"
                                    className="prd-console-file"
                                >
                                    {artifact.type === 'image' ? <Globe className="prd-console-file-icon" /> : <FileText className="prd-console-file-icon" />}
                                    <span className="prd-console-file-name">{artifact.name}</span>
                                    <span className="prd-console-file-type">{artifact.type}</span>
                                </a>
                            ))}
                        </div>
                    )}
                </div>
            )}
                </>
            )}
        </div>
    );
}
