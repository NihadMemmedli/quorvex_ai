'use client';
import React from 'react';
import { Activity, AlertCircle, ChevronDown, ChevronRight, Clock, Info, Server, Zap } from 'lucide-react';
import type { SystemLimits } from './types';

interface SystemInfoPanelProps {
    systemLimits: SystemLimits;
    showSystemInfo: boolean;
    onToggle: () => void;
}

export default React.memo(function SystemInfoPanel({ systemLimits, showSystemInfo, onToggle }: SystemInfoPanelProps) {
    return (
        <div style={{
            marginBottom: '1rem', borderRadius: 'var(--radius)',
            border: '1px solid var(--border)', background: 'var(--surface)',
            overflow: 'hidden',
        }}>
            {/* Collapsed header row */}
            <button
                onClick={onToggle}
                style={{
                    width: '100%', display: 'flex', alignItems: 'center', gap: '0.5rem',
                    padding: '0.6rem 1rem', background: 'none', border: 'none',
                    cursor: 'pointer', color: 'var(--text-primary)',
                }}
            >
                {showSystemInfo ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                <Info size={14} style={{ color: 'var(--text-secondary)' }} />
                <span style={{ fontSize: '0.8rem', fontWeight: 500 }}>System Limits &amp; Resources</span>
                <span style={{
                    marginLeft: '0.5rem', display: 'inline-flex', alignItems: 'center', gap: '0.25rem',
                    padding: '0.1rem 0.5rem', borderRadius: '999px', fontSize: '0.7rem', fontWeight: 500,
                    background: systemLimits.execution_mode === 'distributed' ? 'rgba(34,197,94,0.1)' : 'rgba(234,179,8,0.1)',
                    color: systemLimits.execution_mode === 'distributed' ? 'var(--success)' : 'var(--warning)',
                    border: `1px solid ${systemLimits.execution_mode === 'distributed' ? 'rgba(34,197,94,0.2)' : 'rgba(234,179,8,0.2)'}`,
                }}>
                    {systemLimits.execution_mode === 'distributed'
                        ? `Distributed (${systemLimits.workers_connected} workers)`
                        : 'Local'}
                </span>
                <span style={{ marginLeft: 'auto', fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
                    Max {systemLimits.effective_max_vus.toLocaleString()} VUs
                </span>
            </button>

            {/* Expanded content */}
            {showSystemInfo && (
                <div style={{ borderTop: '1px solid var(--border)', padding: '1rem' }}>
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '0.75rem' }}>
                        {/* Mode */}
                        <div style={{ padding: '0.75rem', borderRadius: 'var(--radius)', background: 'var(--background)', border: '1px solid var(--border)' }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', marginBottom: '0.4rem' }}>
                                <Server size={13} style={{ color: 'var(--text-secondary)' }} />
                                <span style={{ fontSize: '0.7rem', color: 'var(--text-secondary)', fontWeight: 500 }}>Execution Mode</span>
                            </div>
                            <div style={{ fontSize: '1rem', fontWeight: 600 }}>
                                {systemLimits.execution_mode === 'distributed' ? 'Distributed' : 'Local'}
                            </div>
                            <div style={{ fontSize: '0.7rem', color: 'var(--text-secondary)', marginTop: '0.2rem' }}>
                                {systemLimits.execution_mode === 'distributed'
                                    ? `${systemLimits.workers_connected} worker${systemLimits.workers_connected !== 1 ? 's' : ''} connected`
                                    : 'Single instance'}
                            </div>
                        </div>

                        {/* Max VUs */}
                        <div style={{ padding: '0.75rem', borderRadius: 'var(--radius)', background: 'var(--background)', border: '1px solid var(--border)' }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', marginBottom: '0.4rem' }}>
                                <Zap size={13} style={{ color: 'var(--text-secondary)' }} />
                                <span style={{ fontSize: '0.7rem', color: 'var(--text-secondary)', fontWeight: 500 }}>Max Virtual Users</span>
                            </div>
                            <div style={{ fontSize: '1rem', fontWeight: 600 }}>
                                {systemLimits.effective_max_vus.toLocaleString()}
                            </div>
                            <div style={{ fontSize: '0.7rem', color: 'var(--text-secondary)', marginTop: '0.2rem' }}>
                                {systemLimits.execution_mode === 'distributed'
                                    ? `${systemLimits.k6_max_vus.toLocaleString()}/worker × ${systemLimits.workers_connected}`
                                    : `${systemLimits.k6_max_vus.toLocaleString()} per instance`}
                            </div>
                        </div>

                        {/* Max Duration */}
                        <div style={{ padding: '0.75rem', borderRadius: 'var(--radius)', background: 'var(--background)', border: '1px solid var(--border)' }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', marginBottom: '0.4rem' }}>
                                <Clock size={13} style={{ color: 'var(--text-secondary)' }} />
                                <span style={{ fontSize: '0.7rem', color: 'var(--text-secondary)', fontWeight: 500 }}>Max Duration</span>
                            </div>
                            <div style={{ fontSize: '1rem', fontWeight: 600 }}>
                                {systemLimits.k6_max_duration}
                            </div>
                            <div style={{ fontSize: '0.7rem', color: 'var(--text-secondary)', marginTop: '0.2rem' }}>
                                Timeout: {Math.floor(systemLimits.k6_timeout_seconds / 60)}m
                            </div>
                        </div>

                        {/* Browser Pool */}
                        <div style={{ padding: '0.75rem', borderRadius: 'var(--radius)', background: 'var(--background)', border: '1px solid var(--border)' }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', marginBottom: '0.4rem' }}>
                                <Activity size={13} style={{ color: 'var(--text-secondary)' }} />
                                <span style={{ fontSize: '0.7rem', color: 'var(--text-secondary)', fontWeight: 500 }}>Browser Pool</span>
                            </div>
                            <div style={{ fontSize: '1rem', fontWeight: 600 }}>
                                {systemLimits.browser_slots_available}/{systemLimits.max_browser_instances} available
                            </div>
                            <div style={{ fontSize: '0.7rem', color: 'var(--text-secondary)', marginTop: '0.2rem' }}>
                                {systemLimits.browser_slots_running} running
                            </div>
                        </div>
                    </div>

                    {/* Warning bar */}
                    <div style={{
                        marginTop: '0.75rem', padding: '0.5rem 0.75rem', borderRadius: 'var(--radius)',
                        background: 'rgba(245, 158, 11, 0.08)', border: '1px solid rgba(245, 158, 11, 0.2)',
                        display: 'flex', alignItems: 'center', gap: '0.5rem',
                    }}>
                        <AlertCircle size={14} style={{ color: 'var(--warning)', flexShrink: 0 }} />
                        <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
                            Running a load test acquires an exclusive lock and pauses all browser operations (explorations, test runs, agents) until completion.
                        </span>
                    </div>
                </div>
            )}
        </div>
    );
});
