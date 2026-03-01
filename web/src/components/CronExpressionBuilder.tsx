'use client';

import { useState, useEffect, useCallback } from 'react';
import { Clock, Calendar, Loader2 } from 'lucide-react';
import { API_BASE } from '@/lib/api';

interface CronExpressionBuilderProps {
    value: string;
    onChange: (cron: string) => void;
}

const PRESETS = [
    { label: 'Daily at 8am', cron: '0 8 * * *' },
    { label: 'Weekdays at 6am', cron: '0 6 * * 1-5' },
    { label: 'Every Monday 9am', cron: '0 9 * * 1' },
    { label: 'Every 6 hours', cron: '0 */6 * * *' },
    { label: 'Every hour', cron: '0 * * * *' },
];

const DAYS_OF_WEEK: Record<string, string> = {
    '*': 'Every day',
    '0': 'Sunday',
    '1': 'Monday',
    '2': 'Tuesday',
    '3': 'Wednesday',
    '4': 'Thursday',
    '5': 'Friday',
    '6': 'Saturday',
    '1-5': 'Weekdays',
};

function parseCronToEnglish(cron: string): string {
    const parts = cron.trim().split(/\s+/);
    if (parts.length !== 5) return 'Invalid cron expression';

    const [minute, hour, dom, month, dow] = parts;

    let timeStr = '';
    if (hour === '*' && minute === '0') {
        timeStr = 'every hour';
    } else if (hour.startsWith('*/')) {
        timeStr = `every ${hour.slice(2)} hours`;
    } else if (hour === '*') {
        timeStr = `every hour at minute ${minute}`;
    } else {
        timeStr = `at ${hour.padStart(2, '0')}:${minute.padStart(2, '0')} UTC`;
    }

    let dateStr = '';
    if (dow !== '*') {
        dateStr = DAYS_OF_WEEK[dow] || `day-of-week ${dow}`;
    } else if (dom !== '*') {
        dateStr = `day ${dom} of the month`;
    }

    if (month !== '*') {
        const months = ['', 'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
        dateStr += ` in ${months[parseInt(month)] || `month ${month}`}`;
    }

    if (dateStr) {
        return `${dateStr}, ${timeStr}`;
    }
    return timeStr.charAt(0).toUpperCase() + timeStr.slice(1);
}

export function CronExpressionBuilder({ value, onChange }: CronExpressionBuilderProps) {
    const parts = value.trim().split(/\s+/);
    const [minute, setMinute] = useState(parts[0] || '0');
    const [hour, setHour] = useState(parts[1] || '8');
    const [dom, setDom] = useState(parts[2] || '*');
    const [month, setMonth] = useState(parts[3] || '*');
    const [dow, setDow] = useState(parts[4] || '*');
    const [nextRuns, setNextRuns] = useState<string[]>([]);
    const [loadingRuns, setLoadingRuns] = useState(false);

    // Sync fields when value prop changes externally
    useEffect(() => {
        const p = value.trim().split(/\s+/);
        if (p.length === 5) {
            setMinute(p[0]);
            setHour(p[1]);
            setDom(p[2]);
            setMonth(p[3]);
            setDow(p[4]);
        }
    }, [value]);

    const updateCron = useCallback((m: string, h: string, d: string, mo: string, dw: string) => {
        const newCron = `${m} ${h} ${d} ${mo} ${dw}`;
        onChange(newCron);
    }, [onChange]);

    // Fetch next 5 runs when cron changes
    useEffect(() => {
        const cronExpr = `${minute} ${hour} ${dom} ${month} ${dow}`;
        const timer = setTimeout(async () => {
            setLoadingRuns(true);
            try {
                const res = await fetch(`${API_BASE}/scheduling/validate-cron`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ cron_expression: cronExpr, count: 5 }),
                });
                if (res.ok) {
                    const data = await res.json();
                    setNextRuns(data.next_runs || []);
                } else {
                    setNextRuns([]);
                }
            } catch {
                setNextRuns([]);
            } finally {
                setLoadingRuns(false);
            }
        }, 500);

        return () => clearTimeout(timer);
    }, [minute, hour, dom, month, dow]);

    const selectStyle: React.CSSProperties = {
        padding: '0.4rem 0.5rem',
        borderRadius: 'var(--radius)',
        border: '1px solid var(--border)',
        background: 'var(--background)',
        color: 'var(--text)',
        fontSize: '0.85rem',
        flex: 1,
        minWidth: 0,
    };

    const presetBtnStyle = (isActive: boolean): React.CSSProperties => ({
        padding: '0.35rem 0.75rem',
        borderRadius: 'var(--radius)',
        border: '1px solid var(--border)',
        background: isActive ? 'rgba(59, 130, 246, 0.15)' : 'transparent',
        color: isActive ? 'var(--primary)' : 'var(--text-secondary)',
        cursor: 'pointer',
        fontSize: '0.8rem',
        fontWeight: isActive ? 600 : 400,
        transition: 'all 0.2s',
        whiteSpace: 'nowrap' as const,
    });

    const currentCron = `${minute} ${hour} ${dom} ${month} ${dow}`;

    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
            {/* Presets */}
            <div>
                <div style={{ fontSize: '0.85rem', fontWeight: 500, marginBottom: '0.5rem' }}>Quick Presets</div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem' }}>
                    {PRESETS.map(preset => (
                        <button
                            key={preset.cron}
                            type="button"
                            style={presetBtnStyle(currentCron === preset.cron)}
                            onClick={() => {
                                const p = preset.cron.split(' ');
                                setMinute(p[0]); setHour(p[1]); setDom(p[2]); setMonth(p[3]); setDow(p[4]);
                                onChange(preset.cron);
                            }}
                        >
                            {preset.label}
                        </button>
                    ))}
                </div>
            </div>

            {/* Cron fields */}
            <div>
                <div style={{ fontSize: '0.85rem', fontWeight: 500, marginBottom: '0.5rem' }}>Custom Expression</div>
                <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'flex-end' }}>
                    <div style={{ flex: 1, minWidth: 0 }}>
                        <label style={{ fontSize: '0.7rem', color: 'var(--text-secondary)', display: 'block', marginBottom: '0.2rem' }}>Minute</label>
                        <select style={selectStyle} value={minute} onChange={e => { setMinute(e.target.value); updateCron(e.target.value, hour, dom, month, dow); }}>
                            <option value="0">0</option>
                            <option value="15">15</option>
                            <option value="30">30</option>
                            <option value="45">45</option>
                            {Array.from({ length: 60 }, (_, i) => i).filter(i => ![0, 15, 30, 45].includes(i)).map(i => (
                                <option key={i} value={String(i)}>{i}</option>
                            ))}
                        </select>
                    </div>
                    <div style={{ flex: 1, minWidth: 0 }}>
                        <label style={{ fontSize: '0.7rem', color: 'var(--text-secondary)', display: 'block', marginBottom: '0.2rem' }}>Hour</label>
                        <select style={selectStyle} value={hour} onChange={e => { setHour(e.target.value); updateCron(minute, e.target.value, dom, month, dow); }}>
                            <option value="*">Every (*)</option>
                            <option value="*/2">Every 2h</option>
                            <option value="*/4">Every 4h</option>
                            <option value="*/6">Every 6h</option>
                            <option value="*/8">Every 8h</option>
                            <option value="*/12">Every 12h</option>
                            {Array.from({ length: 24 }, (_, i) => (
                                <option key={i} value={String(i)}>{String(i).padStart(2, '0')}</option>
                            ))}
                        </select>
                    </div>
                    <div style={{ flex: 1, minWidth: 0 }}>
                        <label style={{ fontSize: '0.7rem', color: 'var(--text-secondary)', display: 'block', marginBottom: '0.2rem' }}>Day</label>
                        <select style={selectStyle} value={dom} onChange={e => { setDom(e.target.value); updateCron(minute, hour, e.target.value, month, dow); }}>
                            <option value="*">Every (*)</option>
                            {Array.from({ length: 31 }, (_, i) => (
                                <option key={i + 1} value={String(i + 1)}>{i + 1}</option>
                            ))}
                        </select>
                    </div>
                    <div style={{ flex: 1, minWidth: 0 }}>
                        <label style={{ fontSize: '0.7rem', color: 'var(--text-secondary)', display: 'block', marginBottom: '0.2rem' }}>Month</label>
                        <select style={selectStyle} value={month} onChange={e => { setMonth(e.target.value); updateCron(minute, hour, dom, e.target.value, dow); }}>
                            <option value="*">Every (*)</option>
                            {['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'].map((m, i) => (
                                <option key={i + 1} value={String(i + 1)}>{m}</option>
                            ))}
                        </select>
                    </div>
                    <div style={{ flex: 1, minWidth: 0 }}>
                        <label style={{ fontSize: '0.7rem', color: 'var(--text-secondary)', display: 'block', marginBottom: '0.2rem' }}>Weekday</label>
                        <select style={selectStyle} value={dow} onChange={e => { setDow(e.target.value); updateCron(minute, hour, dom, month, e.target.value); }}>
                            <option value="*">Every (*)</option>
                            <option value="1-5">Weekdays</option>
                            <option value="0">Sunday</option>
                            <option value="1">Monday</option>
                            <option value="2">Tuesday</option>
                            <option value="3">Wednesday</option>
                            <option value="4">Thursday</option>
                            <option value="5">Friday</option>
                            <option value="6">Saturday</option>
                        </select>
                    </div>
                </div>
                <div style={{
                    marginTop: '0.5rem',
                    padding: '0.5rem 0.75rem',
                    background: 'rgba(0,0,0,0.1)',
                    borderRadius: 'var(--radius)',
                    fontSize: '0.8rem',
                    fontFamily: 'monospace',
                    color: 'var(--text-secondary)',
                }}>
                    {currentCron}
                </div>
            </div>

            {/* Human-readable preview */}
            <div style={{
                padding: '0.75rem 1rem',
                background: 'rgba(59, 130, 246, 0.08)',
                borderRadius: 'var(--radius)',
                border: '1px solid rgba(59, 130, 246, 0.15)',
                display: 'flex',
                alignItems: 'center',
                gap: '0.5rem',
            }}>
                <Calendar size={16} style={{ color: 'var(--primary)', flexShrink: 0 }} />
                <span style={{ fontSize: '0.9rem', fontWeight: 500 }}>
                    {parseCronToEnglish(currentCron)}
                </span>
            </div>

            {/* Next 5 runs */}
            <div>
                <div style={{ fontSize: '0.85rem', fontWeight: 500, marginBottom: '0.5rem', display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                    <Clock size={14} />
                    Next 5 Runs
                </div>
                {loadingRuns ? (
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', color: 'var(--text-secondary)', fontSize: '0.85rem' }}>
                        <Loader2 size={14} style={{ animation: 'spin 1s linear infinite' }} />
                        Calculating...
                    </div>
                ) : nextRuns.length > 0 ? (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem' }}>
                        {nextRuns.map((run, i) => (
                            <div key={i} style={{
                                padding: '0.3rem 0.6rem',
                                background: i === 0 ? 'rgba(16, 185, 129, 0.08)' : 'transparent',
                                borderRadius: 'var(--radius)',
                                fontSize: '0.8rem',
                                color: i === 0 ? 'var(--success)' : 'var(--text-secondary)',
                                fontWeight: i === 0 ? 500 : 400,
                            }}>
                                {new Date(run).toLocaleString()}
                            </div>
                        ))}
                    </div>
                ) : (
                    <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                        Unable to calculate next runs
                    </div>
                )}
            </div>

            <style jsx>{`
                @keyframes spin {
                    from { transform: rotate(0deg); }
                    to { transform: rotate(360deg); }
                }
            `}</style>
        </div>
    );
}
