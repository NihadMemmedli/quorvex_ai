'use client';
import { useState, useEffect, useCallback, useMemo } from 'react';
import { API_BASE } from '@/lib/api';
import { cardStyleCompact, inputStyle, btnPrimary, btnSecondary, labelStyle, thStyle, tdStyle } from '@/lib/styles';
import { toast } from 'sonner';
import { StatusBadge } from '@/components/shared';
import { ConfirmDialog } from '@/components/ui/confirm-dialog';
import {
    Clock, Play, Pause, Trash2, ChevronDown, ChevronUp,
    Plus, Loader2, Calendar, ArrowLeft,
} from 'lucide-react';
import type { Provider, Dataset, LlmSchedule, LlmScheduleExecution } from './types';

interface SchedulesTabProps {
    projectId: string;
}

const COMMON_TIMEZONES = [
    'UTC',
    'America/New_York',
    'America/Chicago',
    'America/Denver',
    'America/Los_Angeles',
    'Europe/London',
    'Europe/Berlin',
    'Europe/Paris',
    'Asia/Tokyo',
    'Asia/Shanghai',
    'Asia/Kolkata',
    'Australia/Sydney',
];

function cronToHuman(cron: string): string {
    const parts = cron.split(/\s+/);
    if (parts.length < 5) return cron;
    const [min, hour, dom, mon, dow] = parts;

    if (min === '0' && hour === '*') return 'Every hour';
    if (min === '*/15') return 'Every 15 minutes';
    if (min === '*/30') return 'Every 30 minutes';
    if (dom === '*' && mon === '*' && dow === '*' && hour !== '*') {
        return `Daily at ${hour.padStart(2, '0')}:${min.padStart(2, '0')}`;
    }
    if (dom === '*' && mon === '*' && dow !== '*' && hour !== '*') {
        const days: Record<string, string> = { '1': 'Mon', '2': 'Tue', '3': 'Wed', '4': 'Thu', '5': 'Fri', '6': 'Sat', '0': 'Sun' };
        const dayStr = dow.split(',').map(d => days[d] || d).join(', ');
        return `${dayStr} at ${hour.padStart(2, '0')}:${min.padStart(2, '0')}`;
    }
    return cron;
}

export default function SchedulesTab({ projectId }: SchedulesTabProps) {
    const [schedules, setSchedules] = useState<LlmSchedule[]>([]);
    const [providers, setProviders] = useState<Provider[]>([]);
    const [datasets, setDatasets] = useState<Dataset[]>([]);
    const [loading, setLoading] = useState(true);

    // Create form
    const [showCreate, setShowCreate] = useState(false);
    const [formName, setFormName] = useState('');
    const [formDatasetId, setFormDatasetId] = useState('');
    const [formProviderIds, setFormProviderIds] = useState<string[]>([]);
    const [formCron, setFormCron] = useState('0 9 * * *');
    const [formTimezone, setFormTimezone] = useState('UTC');
    const [formNotify, setFormNotify] = useState(true);
    const [formThreshold, setFormThreshold] = useState(10);
    const [creating, setCreating] = useState(false);

    // Detail view
    const [selectedSchedule, setSelectedSchedule] = useState<LlmSchedule | null>(null);
    const [executions, setExecutions] = useState<LlmScheduleExecution[]>([]);
    const [executionsLoading, setExecutionsLoading] = useState(false);

    // Edit form
    const [editMode, setEditMode] = useState(false);
    const [editName, setEditName] = useState('');
    const [editCron, setEditCron] = useState('');
    const [editTimezone, setEditTimezone] = useState('');
    const [editNotify, setEditNotify] = useState(true);
    const [editThreshold, setEditThreshold] = useState(10);
    const [editProviderIds, setEditProviderIds] = useState<string[]>([]);

    // Confirm dialog
    const [confirmDelete, setConfirmDelete] = useState<{ open: boolean; id: string; name: string }>({ open: false, id: '', name: '' });

    const fetchSchedules = useCallback(async () => {
        try {
            const res = await fetch(`${API_BASE}/llm-testing/schedules?project_id=${projectId}`);
            if (res.ok) setSchedules(await res.json());
        } catch {
            toast.error('Failed to load schedules');
        }
        setLoading(false);
    }, [projectId]);

    useEffect(() => {
        fetchSchedules();
        fetch(`${API_BASE}/llm-testing/providers?project_id=${projectId}`)
            .then(r => r.json()).then(setProviders).catch(() => {});
        fetch(`${API_BASE}/llm-testing/datasets?project_id=${projectId}`)
            .then(r => r.json()).then(setDatasets).catch(() => {});
    }, [projectId, fetchSchedules]);

    const providerName = useCallback((id: string) => {
        const p = providers.find(pr => pr.id === id);
        return p ? p.name : id;
    }, [providers]);

    const toggleFormProvider = (id: string) => {
        setFormProviderIds(prev => prev.includes(id) ? prev.filter(p => p !== id) : [...prev, id]);
    };

    const toggleEditProvider = (id: string) => {
        setEditProviderIds(prev => prev.includes(id) ? prev.filter(p => p !== id) : [...prev, id]);
    };

    const createSchedule = async () => {
        if (!formName.trim() || !formDatasetId || formProviderIds.length === 0 || !formCron.trim()) {
            toast.error('Please fill in all required fields');
            return;
        }
        setCreating(true);
        try {
            const res = await fetch(`${API_BASE}/llm-testing/schedules`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    name: formName,
                    dataset_id: formDatasetId,
                    provider_ids: formProviderIds,
                    cron_expression: formCron,
                    timezone: formTimezone,
                    notify_on_regression: formNotify,
                    regression_threshold: formThreshold,
                    project_id: projectId,
                }),
            });
            if (res.ok) {
                toast.success('Schedule created');
                setShowCreate(false);
                setFormName('');
                setFormDatasetId('');
                setFormProviderIds([]);
                setFormCron('0 9 * * *');
                setFormTimezone('UTC');
                setFormNotify(true);
                setFormThreshold(10);
                fetchSchedules();
            } else {
                const err = await res.json().catch(() => ({}));
                toast.error(err.detail || 'Failed to create schedule');
            }
        } catch {
            toast.error('Failed to create schedule');
        }
        setCreating(false);
    };

    const toggleEnabled = async (schedule: LlmSchedule) => {
        try {
            const res = await fetch(`${API_BASE}/llm-testing/schedules/${schedule.id}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ enabled: !schedule.enabled }),
            });
            if (res.ok) {
                toast.success(schedule.enabled ? 'Schedule paused' : 'Schedule enabled');
                fetchSchedules();
                if (selectedSchedule?.id === schedule.id) {
                    setSelectedSchedule({ ...selectedSchedule, enabled: !schedule.enabled });
                }
            }
        } catch {
            toast.error('Failed to update schedule');
        }
    };

    const deleteSchedule = async (id: string) => {
        try {
            const res = await fetch(`${API_BASE}/llm-testing/schedules/${id}`, { method: 'DELETE' });
            if (res.ok) {
                toast.success('Schedule deleted');
                if (selectedSchedule?.id === id) setSelectedSchedule(null);
                fetchSchedules();
            }
        } catch {
            toast.error('Failed to delete schedule');
        }
    };

    const viewSchedule = async (schedule: LlmSchedule) => {
        setSelectedSchedule(schedule);
        setEditMode(false);
        setExecutionsLoading(true);
        try {
            const res = await fetch(`${API_BASE}/llm-testing/schedules/${schedule.id}/executions`);
            if (res.ok) setExecutions(await res.json());
        } catch {
            toast.error('Failed to load executions');
        }
        setExecutionsLoading(false);
    };

    const runNow = async (scheduleId: string) => {
        try {
            const res = await fetch(`${API_BASE}/llm-testing/schedules/${scheduleId}/run`, { method: 'POST' });
            if (res.ok) {
                toast.success('Manual run triggered');
                fetchSchedules();
                if (selectedSchedule?.id === scheduleId) {
                    viewSchedule(selectedSchedule);
                }
            } else {
                const err = await res.json().catch(() => ({}));
                toast.error(err.detail || 'Failed to trigger run');
            }
        } catch {
            toast.error('Failed to trigger run');
        }
    };

    const startEdit = (schedule: LlmSchedule) => {
        setEditMode(true);
        setEditName(schedule.name);
        setEditCron(schedule.cron_expression);
        setEditTimezone(schedule.timezone);
        setEditNotify(schedule.notify_on_regression);
        setEditThreshold(schedule.regression_threshold);
        setEditProviderIds([...schedule.provider_ids]);
    };

    const saveEdit = async () => {
        if (!selectedSchedule) return;
        try {
            const res = await fetch(`${API_BASE}/llm-testing/schedules/${selectedSchedule.id}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    name: editName,
                    cron_expression: editCron,
                    timezone: editTimezone,
                    provider_ids: editProviderIds,
                    notify_on_regression: editNotify,
                    regression_threshold: editThreshold,
                }),
            });
            if (res.ok) {
                toast.success('Schedule updated');
                setEditMode(false);
                fetchSchedules();
                const updated = await res.json();
                setSelectedSchedule(updated);
            } else {
                toast.error('Failed to update schedule');
            }
        } catch {
            toast.error('Failed to update schedule');
        }
    };

    if (loading) return <div style={{ padding: '2rem', color: 'var(--text-secondary)' }}>Loading schedules...</div>;

    // Detail view
    if (selectedSchedule) {
        return (
            <div>
                <button
                    onClick={() => setSelectedSchedule(null)}
                    style={{ ...btnSecondary, fontSize: '0.8rem', padding: '0.35rem 0.75rem', marginBottom: '1rem' }}
                >
                    <ArrowLeft size={14} /> Back to Schedules
                </button>

                <div style={{ ...cardStyleCompact, marginBottom: '1rem' }}>
                    {editMode ? (
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                            <div>
                                <label style={labelStyle}>Name</label>
                                <input value={editName} onChange={e => setEditName(e.target.value)} style={inputStyle} />
                            </div>
                            <div>
                                <label style={labelStyle}>Cron Expression</label>
                                <input value={editCron} onChange={e => setEditCron(e.target.value)} style={inputStyle} />
                                <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', marginTop: '0.25rem' }}>
                                    {cronToHuman(editCron)}
                                </div>
                            </div>
                            <div>
                                <label style={labelStyle}>Timezone</label>
                                <select value={editTimezone} onChange={e => setEditTimezone(e.target.value)} style={inputStyle}>
                                    {COMMON_TIMEZONES.map(tz => <option key={tz} value={tz}>{tz}</option>)}
                                </select>
                            </div>
                            <div>
                                <label style={labelStyle}>Providers</label>
                                <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
                                    {providers.map(p => (
                                        <label key={p.id} style={{ display: 'flex', alignItems: 'center', gap: '0.3rem', fontSize: '0.85rem', cursor: 'pointer' }}>
                                            <input type="checkbox" checked={editProviderIds.includes(p.id)} onChange={() => toggleEditProvider(p.id)} />
                                            {p.name}
                                        </label>
                                    ))}
                                </div>
                            </div>
                            <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center' }}>
                                <label style={{ display: 'flex', alignItems: 'center', gap: '0.3rem', fontSize: '0.85rem', cursor: 'pointer' }}>
                                    <input type="checkbox" checked={editNotify} onChange={e => setEditNotify(e.target.checked)} />
                                    Notify on regression
                                </label>
                                {editNotify && (
                                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.3rem' }}>
                                        <label style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Threshold:</label>
                                        <input type="number" min={1} max={100} value={editThreshold} onChange={e => setEditThreshold(Number(e.target.value))}
                                            style={{ ...inputStyle, width: '60px' }} />
                                        <span style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>%</span>
                                    </div>
                                )}
                            </div>
                            <div style={{ display: 'flex', gap: '0.5rem' }}>
                                <button onClick={saveEdit} style={{ ...btnPrimary, fontSize: '0.8rem', padding: '0.35rem 0.75rem' }}>Save</button>
                                <button onClick={() => setEditMode(false)} style={{ ...btnSecondary, fontSize: '0.8rem', padding: '0.35rem 0.75rem' }}>Cancel</button>
                            </div>
                        </div>
                    ) : (
                        <div>
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.75rem' }}>
                                <h2 style={{ fontSize: '1.1rem', fontWeight: 600, margin: 0 }}>{selectedSchedule.name}</h2>
                                <div style={{ display: 'flex', gap: '0.5rem' }}>
                                    <button onClick={() => runNow(selectedSchedule.id)} style={{ ...btnPrimary, fontSize: '0.8rem', padding: '0.35rem 0.75rem', background: 'var(--success)' }}>
                                        <Play size={14} /> Run Now
                                    </button>
                                    <button onClick={() => startEdit(selectedSchedule)} style={{ ...btnSecondary, fontSize: '0.8rem', padding: '0.35rem 0.75rem' }}>Edit</button>
                                    <button onClick={() => toggleEnabled(selectedSchedule)} style={{ ...btnSecondary, fontSize: '0.8rem', padding: '0.35rem 0.75rem' }}>
                                        {selectedSchedule.enabled ? <><Pause size={14} /> Pause</> : <><Play size={14} /> Enable</>}
                                    </button>
                                </div>
                            </div>
                            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: '0.5rem', fontSize: '0.85rem' }}>
                                <div><span style={{ color: 'var(--text-secondary)' }}>Dataset:</span> {selectedSchedule.dataset_name || selectedSchedule.dataset_id}</div>
                                <div><span style={{ color: 'var(--text-secondary)' }}>Cron:</span> {selectedSchedule.cron_expression} ({cronToHuman(selectedSchedule.cron_expression)})</div>
                                <div><span style={{ color: 'var(--text-secondary)' }}>Timezone:</span> {selectedSchedule.timezone}</div>
                                <div><span style={{ color: 'var(--text-secondary)' }}>Status:</span> {selectedSchedule.enabled ? 'Enabled' : 'Paused'}</div>
                                <div><span style={{ color: 'var(--text-secondary)' }}>Providers:</span> {selectedSchedule.provider_ids.map(id => providerName(id)).join(', ')}</div>
                                <div><span style={{ color: 'var(--text-secondary)' }}>Executions:</span> {selectedSchedule.total_executions}</div>
                                {selectedSchedule.next_run_at && (
                                    <div><span style={{ color: 'var(--text-secondary)' }}>Next Run:</span> {new Date(selectedSchedule.next_run_at).toLocaleString()}</div>
                                )}
                                {selectedSchedule.last_run_at && (
                                    <div><span style={{ color: 'var(--text-secondary)' }}>Last Run:</span> {new Date(selectedSchedule.last_run_at).toLocaleString()}</div>
                                )}
                            </div>
                        </div>
                    )}
                </div>

                {/* Execution History */}
                <h3 style={{ fontSize: '0.95rem', fontWeight: 600, marginBottom: '0.75rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                    <Calendar size={16} style={{ color: 'var(--text-secondary)' }} />
                    Execution History
                </h3>
                {executionsLoading ? (
                    <div style={{ color: 'var(--text-secondary)', fontSize: '0.85rem' }}>Loading executions...</div>
                ) : executions.length === 0 ? (
                    <div style={{ ...cardStyleCompact, textAlign: 'center', color: 'var(--text-secondary)' }}>
                        No executions yet.
                    </div>
                ) : (
                    <div style={{ overflowX: 'auto' }}>
                        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.85rem' }}>
                            <thead>
                                <tr>
                                    <th style={thStyle}>#</th>
                                    <th style={thStyle}>Status</th>
                                    <th style={thStyle}>Dataset Version</th>
                                    <th style={thStyle}>Runs</th>
                                    <th style={thStyle}>Started</th>
                                    <th style={thStyle}>Completed</th>
                                    <th style={thStyle}>Error</th>
                                </tr>
                            </thead>
                            <tbody>
                                {executions.map(ex => (
                                    <tr key={ex.id}>
                                        <td style={tdStyle}>{ex.id}</td>
                                        <td style={tdStyle}><StatusBadge status={ex.status} /></td>
                                        <td style={tdStyle}>v{ex.dataset_version}</td>
                                        <td style={tdStyle}>
                                            {ex.run_ids.length > 0 ? (
                                                <span style={{ fontSize: '0.8rem' }}>{ex.run_ids.length} run{ex.run_ids.length !== 1 ? 's' : ''}</span>
                                            ) : '-'}
                                        </td>
                                        <td style={tdStyle}>
                                            {ex.started_at ? new Date(ex.started_at).toLocaleString() : '-'}
                                        </td>
                                        <td style={tdStyle}>
                                            {ex.completed_at ? new Date(ex.completed_at).toLocaleString() : '-'}
                                        </td>
                                        <td style={{ ...tdStyle, maxWidth: '200px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                            {ex.error_message ? (
                                                <span style={{ color: 'var(--danger)', fontSize: '0.8rem' }} title={ex.error_message}>
                                                    {ex.error_message}
                                                </span>
                                            ) : '-'}
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                )}
            </div>
        );
    }

    // List view
    return (
        <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
                <h2 style={{ fontSize: '1.1rem', fontWeight: 600, margin: 0 }}>Schedules</h2>
                <button onClick={() => setShowCreate(!showCreate)} style={{ ...btnPrimary, fontSize: '0.8rem', padding: '0.35rem 0.75rem' }}>
                    <Plus size={14} /> New Schedule
                </button>
            </div>

            {/* Create Form */}
            {showCreate && (
                <div style={{ ...cardStyleCompact, marginBottom: '1rem' }}>
                    <h3 style={{ fontSize: '0.95rem', fontWeight: 600, marginBottom: '0.75rem' }}>Create Schedule</h3>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                        <div>
                            <label style={labelStyle}>Name *</label>
                            <input placeholder="e.g., Nightly Regression" value={formName} onChange={e => setFormName(e.target.value)} style={inputStyle} />
                        </div>
                        <div>
                            <label style={labelStyle}>Dataset *</label>
                            <select value={formDatasetId} onChange={e => setFormDatasetId(e.target.value)} style={inputStyle}>
                                <option value="">Select a dataset...</option>
                                {datasets.map(d => <option key={d.id} value={d.id}>{d.name} ({d.total_cases} cases)</option>)}
                            </select>
                        </div>
                        <div>
                            <label style={labelStyle}>Providers * (select 1+)</label>
                            <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
                                {providers.map(p => (
                                    <label key={p.id} style={{ display: 'flex', alignItems: 'center', gap: '0.3rem', fontSize: '0.85rem', cursor: 'pointer' }}>
                                        <input type="checkbox" checked={formProviderIds.includes(p.id)} onChange={() => toggleFormProvider(p.id)} />
                                        {p.name} ({p.model_id})
                                    </label>
                                ))}
                            </div>
                        </div>
                        <div style={{ display: 'flex', gap: '1rem', flexWrap: 'wrap' }}>
                            <div style={{ flex: '1 1 200px' }}>
                                <label style={labelStyle}>Cron Expression *</label>
                                <input value={formCron} onChange={e => setFormCron(e.target.value)} style={inputStyle} placeholder="0 9 * * *" />
                                <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', marginTop: '0.25rem' }}>
                                    {cronToHuman(formCron)}
                                </div>
                            </div>
                            <div style={{ flex: '1 1 200px' }}>
                                <label style={labelStyle}>Timezone</label>
                                <select value={formTimezone} onChange={e => setFormTimezone(e.target.value)} style={inputStyle}>
                                    {COMMON_TIMEZONES.map(tz => <option key={tz} value={tz}>{tz}</option>)}
                                </select>
                            </div>
                        </div>
                        <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center', flexWrap: 'wrap' }}>
                            <label style={{ display: 'flex', alignItems: 'center', gap: '0.3rem', fontSize: '0.85rem', cursor: 'pointer' }}>
                                <input type="checkbox" checked={formNotify} onChange={e => setFormNotify(e.target.checked)} />
                                Notify on regression
                            </label>
                            {formNotify && (
                                <div style={{ display: 'flex', alignItems: 'center', gap: '0.3rem' }}>
                                    <label style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Threshold:</label>
                                    <input type="number" min={1} max={100} value={formThreshold} onChange={e => setFormThreshold(Number(e.target.value))}
                                        style={{ ...inputStyle, width: '60px' }} />
                                    <span style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>%</span>
                                </div>
                            )}
                        </div>
                        <div style={{ display: 'flex', gap: '0.5rem' }}>
                            <button onClick={createSchedule} disabled={creating} style={{ ...btnPrimary, fontSize: '0.8rem', padding: '0.35rem 0.75rem', opacity: creating ? 0.5 : 1 }}>
                                {creating ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />}
                                Create
                            </button>
                            <button onClick={() => setShowCreate(false)} style={{ ...btnSecondary, fontSize: '0.8rem', padding: '0.35rem 0.75rem' }}>Cancel</button>
                        </div>
                    </div>
                </div>
            )}

            {/* Schedule List */}
            {schedules.length === 0 ? (
                <div style={{ ...cardStyleCompact, textAlign: 'center', color: 'var(--text-secondary)', padding: '2rem' }}>
                    No schedules yet. Create one to automate recurring test runs.
                </div>
            ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                    {schedules.map(s => (
                        <div key={s.id} onClick={() => viewSchedule(s)} style={{ ...cardStyleCompact, cursor: 'pointer', marginBottom: 0 }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                                    <div style={{
                                        width: 8, height: 8, borderRadius: '50%',
                                        background: s.enabled ? 'var(--success)' : 'var(--text-secondary)',
                                        flexShrink: 0,
                                    }} />
                                    <div>
                                        <div style={{ fontWeight: 600, fontSize: '0.9rem' }}>{s.name}</div>
                                        <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginTop: '0.15rem' }}>
                                            {s.dataset_name || s.dataset_id} | {cronToHuman(s.cron_expression)} ({s.timezone})
                                        </div>
                                    </div>
                                </div>
                                <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
                                    {s.next_run_at && (
                                        <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
                                            Next: {new Date(s.next_run_at).toLocaleString()}
                                        </span>
                                    )}
                                    <span style={{
                                        fontSize: '0.72rem', fontWeight: 500,
                                        padding: '0.15rem 0.5rem', borderRadius: '9999px',
                                        background: s.enabled ? 'rgba(34,197,94,0.1)' : 'var(--surface-hover)',
                                        color: s.enabled ? 'var(--success)' : 'var(--text-secondary)',
                                        border: `1px solid ${s.enabled ? 'rgba(34,197,94,0.3)' : 'var(--border-subtle)'}`,
                                    }}>
                                        {s.enabled ? 'Active' : 'Paused'}
                                    </span>
                                    <button
                                        onClick={e => { e.stopPropagation(); toggleEnabled(s); }}
                                        style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-secondary)', padding: '0.2rem' }}
                                        title={s.enabled ? 'Pause' : 'Enable'}
                                    >
                                        {s.enabled ? <Pause size={14} /> : <Play size={14} />}
                                    </button>
                                    <button
                                        onClick={e => { e.stopPropagation(); runNow(s.id); }}
                                        style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--success)', padding: '0.2rem' }}
                                        title="Run Now"
                                    >
                                        <Play size={14} />
                                    </button>
                                    <button
                                        onClick={e => { e.stopPropagation(); setConfirmDelete({ open: true, id: s.id, name: s.name }); }}
                                        style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-secondary)', padding: '0.2rem' }}
                                        title="Delete"
                                    >
                                        <Trash2 size={14} />
                                    </button>
                                </div>
                            </div>
                            <div style={{ display: 'flex', gap: '0.5rem', marginTop: '0.35rem', flexWrap: 'wrap' }}>
                                {s.provider_ids.map(pid => (
                                    <span key={pid} style={{
                                        fontSize: '0.7rem',
                                        background: 'var(--primary-light, rgba(59,130,246,0.1))',
                                        color: 'var(--primary)',
                                        borderRadius: '4px',
                                        padding: '0.1rem 0.35rem',
                                    }}>
                                        {providerName(pid)}
                                    </span>
                                ))}
                                <span style={{ fontSize: '0.7rem', color: 'var(--text-secondary)' }}>
                                    {s.total_executions} execution{s.total_executions !== 1 ? 's' : ''}
                                </span>
                            </div>
                        </div>
                    ))}
                </div>
            )}

            <ConfirmDialog
                open={confirmDelete.open}
                onOpenChange={open => setConfirmDelete(s => ({ ...s, open }))}
                title="Delete Schedule"
                description={`Delete schedule "${confirmDelete.name}"? This action cannot be undone.`}
                confirmLabel="Delete"
                variant="danger"
                onConfirm={() => deleteSchedule(confirmDelete.id)}
            />
        </div>
    );
}
