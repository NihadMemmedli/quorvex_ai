'use client';

import { useState, useEffect } from 'react';
import { X, Save, Loader2 } from 'lucide-react';
import { CronExpressionBuilder } from './CronExpressionBuilder';
import { API_BASE } from '@/lib/api';

interface ScheduleModalProps {
    isOpen: boolean;
    onClose: () => void;
    onSave: (schedule: any) => void;
    schedule?: any;
    projectId: string;
}

const COMMON_TIMEZONES = [
    'UTC',
    'America/New_York',
    'America/Chicago',
    'America/Denver',
    'America/Los_Angeles',
    'Europe/London',
    'Europe/Paris',
    'Europe/Berlin',
    'Europe/Istanbul',
    'Asia/Dubai',
    'Asia/Kolkata',
    'Asia/Shanghai',
    'Asia/Tokyo',
    'Asia/Singapore',
    'Australia/Sydney',
    'Pacific/Auckland',
];

export function ScheduleModal({ isOpen, onClose, onSave, schedule, projectId }: ScheduleModalProps) {
    const [name, setName] = useState('');
    const [description, setDescription] = useState('');
    const [cronExpression, setCronExpression] = useState('0 8 * * *');
    const [timezone, setTimezone] = useState('UTC');
    const [tagFilter, setTagFilter] = useState('');
    const [automatedOnly, setAutomatedOnly] = useState(true);
    const [browser, setBrowser] = useState('chromium');
    const [hybridMode, setHybridMode] = useState(false);
    const [enabled, setEnabled] = useState(true);
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState<string | null>(null);

    // Populate form when editing
    useEffect(() => {
        if (schedule) {
            setName(schedule.name || '');
            setDescription(schedule.description || '');
            setCronExpression(schedule.cron_expression || '0 8 * * *');
            setTimezone(schedule.timezone || 'UTC');
            setTagFilter(schedule.tags ? schedule.tags.join(', ') : '');
            setAutomatedOnly(schedule.automated_only ?? true);
            setBrowser(schedule.browser || 'chromium');
            setHybridMode(schedule.hybrid_mode ?? false);
            setEnabled(schedule.enabled ?? true);
        } else {
            setName('');
            setDescription('');
            setCronExpression('0 8 * * *');
            setTimezone('UTC');
            setTagFilter('');
            setAutomatedOnly(true);
            setBrowser('chromium');
            setHybridMode(false);
            setEnabled(true);
        }
        setError(null);
    }, [schedule, isOpen]);

    const handleSave = async () => {
        if (!name.trim()) {
            setError('Schedule name is required');
            return;
        }

        setSaving(true);
        setError(null);

        const tags = tagFilter.trim()
            ? tagFilter.split(',').map(t => t.trim()).filter(Boolean)
            : [];

        const body = {
            name: name.trim(),
            description: description.trim(),
            cron_expression: cronExpression,
            timezone,
            tags: tags.length > 0 ? tags : null,
            automated_only: automatedOnly,
            browser,
            hybrid_mode: hybridMode,
            enabled,
        };

        try {
            const url = schedule
                ? `${API_BASE}/scheduling/${encodeURIComponent(projectId)}/schedules/${schedule.id}`
                : `${API_BASE}/scheduling/${encodeURIComponent(projectId)}/schedules`;

            const res = await fetch(url, {
                method: schedule ? 'PUT' : 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });

            if (res.ok) {
                const data = await res.json();
                onSave(data);
                onClose();
            } else {
                const data = await res.json();
                setError(data.detail || 'Failed to save schedule');
            }
        } catch (err: any) {
            setError(err.message || 'Network error');
        } finally {
            setSaving(false);
        }
    };

    if (!isOpen) return null;

    const overlayStyle: React.CSSProperties = {
        position: 'fixed',
        inset: 0,
        background: 'rgba(0, 0, 0, 0.6)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 1000,
        padding: '2rem',
    };

    const modalStyle: React.CSSProperties = {
        background: 'var(--surface)',
        border: '1px solid var(--border)',
        borderRadius: 'var(--radius)',
        width: '100%',
        maxWidth: '640px',
        maxHeight: '90vh',
        overflow: 'auto',
        padding: '1.5rem',
    };

    const inputStyle: React.CSSProperties = {
        width: '100%',
        padding: '0.5rem 0.75rem',
        borderRadius: 'var(--radius)',
        border: '1px solid var(--border)',
        background: 'var(--background)',
        color: 'var(--text)',
        fontSize: '0.9rem',
    };

    const labelStyle: React.CSSProperties = {
        display: 'block',
        fontSize: '0.85rem',
        fontWeight: 500,
        marginBottom: '0.35rem',
    };

    return (
        <div style={overlayStyle} onClick={onClose}>
            <div style={modalStyle} onClick={e => e.stopPropagation()}>
                {/* Header */}
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.5rem' }}>
                    <h2 style={{ fontSize: '1.25rem', fontWeight: 600, margin: 0 }}>
                        {schedule ? 'Edit Schedule' : 'New Schedule'}
                    </h2>
                    <button
                        onClick={onClose}
                        style={{
                            background: 'none',
                            border: 'none',
                            cursor: 'pointer',
                            color: 'var(--text-secondary)',
                            padding: '0.25rem',
                        }}
                    >
                        <X size={20} />
                    </button>
                </div>

                {error && (
                    <div style={{
                        padding: '0.75rem 1rem',
                        marginBottom: '1rem',
                        borderRadius: 'var(--radius)',
                        background: 'rgba(239, 68, 68, 0.1)',
                        border: '1px solid rgba(239, 68, 68, 0.2)',
                        color: 'var(--danger)',
                        fontSize: '0.9rem',
                    }}>
                        {error}
                    </div>
                )}

                <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
                    {/* Name */}
                    <div>
                        <label style={labelStyle}>Name</label>
                        <input
                            type="text"
                            value={name}
                            onChange={e => setName(e.target.value)}
                            placeholder="e.g., Nightly Regression"
                            style={inputStyle}
                        />
                    </div>

                    {/* Description */}
                    <div>
                        <label style={labelStyle}>Description</label>
                        <textarea
                            value={description}
                            onChange={e => setDescription(e.target.value)}
                            placeholder="Optional description of what this schedule runs..."
                            rows={2}
                            style={{ ...inputStyle, resize: 'vertical' }}
                        />
                    </div>

                    {/* Cron Expression */}
                    <div>
                        <label style={labelStyle}>Schedule</label>
                        <CronExpressionBuilder value={cronExpression} onChange={setCronExpression} />
                    </div>

                    {/* Timezone */}
                    <div>
                        <label style={labelStyle}>Timezone</label>
                        <select value={timezone} onChange={e => setTimezone(e.target.value)} style={inputStyle}>
                            {COMMON_TIMEZONES.map(tz => (
                                <option key={tz} value={tz}>{tz}</option>
                            ))}
                        </select>
                    </div>

                    {/* Tag filter */}
                    <div>
                        <label style={labelStyle}>Tag Filter</label>
                        <input
                            type="text"
                            value={tagFilter}
                            onChange={e => setTagFilter(e.target.value)}
                            placeholder="e.g., smoke, login, checkout (comma-separated)"
                            style={inputStyle}
                        />
                        <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', marginTop: '0.25rem' }}>
                            Only run specs matching these tags. Leave empty to run all specs.
                        </div>
                    </div>

                    {/* Toggles row */}
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '1.5rem' }}>
                        <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'pointer', fontSize: '0.9rem' }}>
                            <input type="checkbox" checked={automatedOnly} onChange={e => setAutomatedOnly(e.target.checked)} style={{ width: '16px', height: '16px' }} />
                            Automated only
                        </label>
                        <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'pointer', fontSize: '0.9rem' }}>
                            <input type="checkbox" checked={hybridMode} onChange={e => setHybridMode(e.target.checked)} style={{ width: '16px', height: '16px' }} />
                            Hybrid mode
                        </label>
                        <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'pointer', fontSize: '0.9rem' }}>
                            <input type="checkbox" checked={enabled} onChange={e => setEnabled(e.target.checked)} style={{ width: '16px', height: '16px' }} />
                            Enabled
                        </label>
                    </div>

                    {/* Browser */}
                    <div>
                        <label style={labelStyle}>Browser</label>
                        <select value={browser} onChange={e => setBrowser(e.target.value)} style={inputStyle}>
                            <option value="chromium">Chromium</option>
                            <option value="firefox">Firefox</option>
                            <option value="webkit">WebKit</option>
                        </select>
                    </div>
                </div>

                {/* Footer */}
                <div style={{
                    display: 'flex',
                    justifyContent: 'flex-end',
                    gap: '0.75rem',
                    marginTop: '1.5rem',
                    paddingTop: '1.25rem',
                    borderTop: '1px solid var(--border)',
                }}>
                    <button
                        type="button"
                        onClick={onClose}
                        style={{
                            padding: '0.5rem 1rem',
                            background: 'transparent',
                            border: '1px solid var(--border)',
                            borderRadius: 'var(--radius)',
                            cursor: 'pointer',
                            color: 'var(--text)',
                            fontSize: '0.9rem',
                        }}
                    >
                        Cancel
                    </button>
                    <button
                        type="button"
                        onClick={handleSave}
                        disabled={saving}
                        style={{
                            padding: '0.5rem 1.25rem',
                            background: 'var(--primary)',
                            color: 'white',
                            border: 'none',
                            borderRadius: 'var(--radius)',
                            cursor: saving ? 'not-allowed' : 'pointer',
                            fontWeight: 600,
                            fontSize: '0.9rem',
                            display: 'flex',
                            alignItems: 'center',
                            gap: '0.5rem',
                            opacity: saving ? 0.7 : 1,
                        }}
                    >
                        {saving ? (
                            <>
                                <Loader2 size={16} style={{ animation: 'spin 1s linear infinite' }} />
                                Saving...
                            </>
                        ) : (
                            <>
                                <Save size={16} />
                                {schedule ? 'Update' : 'Create'} Schedule
                            </>
                        )}
                    </button>
                </div>

                <style jsx>{`
                    @keyframes spin {
                        from { transform: rotate(0deg); }
                        to { transform: rotate(360deg); }
                    }
                `}</style>
            </div>
        </div>
    );
}
