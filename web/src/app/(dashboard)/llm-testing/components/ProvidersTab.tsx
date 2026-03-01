'use client';
import { useState, useEffect, useCallback } from 'react';
import { API_BASE } from '@/lib/api';
import { cardStyleCompact, inputStyle, btnPrimary, btnSmall, labelStyle } from '@/lib/styles';
import { toast } from 'sonner';
import { ConfirmDialog } from '@/components/ui/confirm-dialog';
import { Switch } from '@/components/ui/switch';
import { Pencil } from 'lucide-react';
import type { Provider } from './types';

interface ProvidersTabProps {
    projectId: string;
}

const defaultForm = {
    name: '', base_url: 'https://api.openai.com/v1', api_key: '', model_id: 'gpt-4o-mini',
    temperature: '0.7', max_tokens: '4096',
};

export default function ProvidersTab({ projectId }: ProvidersTabProps) {
    const [providers, setProviders] = useState<Provider[]>([]);
    const [loading, setLoading] = useState(true);
    const [showForm, setShowForm] = useState(false);
    const [healthResults, setHealthResults] = useState<Record<string, any>>({});
    const [editingId, setEditingId] = useState<number | null>(null);
    const [confirmState, setConfirmState] = useState<{ open: boolean; id: string | null }>({ open: false, id: null });

    const [form, setForm] = useState({ ...defaultForm });

    const fetchProviders = useCallback(async () => {
        try {
            const res = await fetch(`${API_BASE}/llm-testing/providers?project_id=${projectId}`);
            if (res.ok) setProviders(await res.json());
        } catch (e) { toast.error('Failed to load providers'); }
        setLoading(false);
    }, [projectId]);

    useEffect(() => { fetchProviders(); }, [fetchProviders]);

    const createProvider = useCallback(async () => {
        try {
            const res = await fetch(`${API_BASE}/llm-testing/providers`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    name: form.name, base_url: form.base_url, api_key: form.api_key, model_id: form.model_id,
                    default_params: { temperature: parseFloat(form.temperature), max_tokens: parseInt(form.max_tokens) },
                    project_id: projectId,
                }),
            });
            if (res.ok) {
                setShowForm(false);
                setForm({ ...defaultForm });
                fetchProviders();
                toast.success('Provider created');
            } else {
                toast.error('Failed to create provider');
            }
        } catch (e) { toast.error('Failed to create provider'); }
    }, [form, projectId, fetchProviders]);

    const updateProvider = useCallback(async () => {
        if (editingId === null) return;
        try {
            const res = await fetch(`${API_BASE}/llm-testing/providers/${editingId}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    name: form.name, base_url: form.base_url, api_key: form.api_key, model_id: form.model_id,
                    default_params: { temperature: parseFloat(form.temperature), max_tokens: parseInt(form.max_tokens) },
                }),
            });
            if (res.ok) {
                setShowForm(false);
                setForm({ ...defaultForm });
                setEditingId(null);
                fetchProviders();
                toast.success('Provider updated');
            } else {
                toast.error('Failed to update provider');
            }
        } catch (e) { toast.error('Failed to update provider'); }
    }, [editingId, form, fetchProviders]);

    const deleteProvider = useCallback(async (id: string) => {
        try {
            await fetch(`${API_BASE}/llm-testing/providers/${id}`, { method: 'DELETE' });
            fetchProviders();
            toast.success('Provider deleted');
        } catch (e) {
            toast.error('Failed to delete provider');
        }
    }, [fetchProviders]);

    const toggleActive = useCallback(async (id: string, checked: boolean) => {
        try {
            const res = await fetch(`${API_BASE}/llm-testing/providers/${id}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ is_active: checked }),
            });
            if (res.ok) {
                fetchProviders();
                toast.success(checked ? 'Provider enabled' : 'Provider disabled');
            } else {
                toast.error('Failed to toggle provider');
            }
        } catch (e) { toast.error('Failed to toggle provider'); }
    }, [fetchProviders]);

    const startEditing = useCallback((p: Provider) => {
        setForm({
            name: p.name,
            base_url: p.base_url,
            api_key: '',
            model_id: p.model_id,
            temperature: String(p.default_params?.temperature ?? '0.7'),
            max_tokens: String(p.default_params?.max_tokens ?? '4096'),
        });
        setEditingId(Number(p.id));
        setShowForm(true);
    }, []);

    const cancelForm = useCallback(() => {
        setShowForm(false);
        setForm({ ...defaultForm });
        setEditingId(null);
    }, []);

    const healthCheck = useCallback(async (id: string) => {
        setHealthResults(prev => ({ ...prev, [id]: { checking: true } }));
        try {
            const res = await fetch(`${API_BASE}/llm-testing/providers/${id}/health-check`, { method: 'POST' });
            const data = await res.json();
            setHealthResults(prev => ({ ...prev, [id]: data }));
        } catch (e) {
            setHealthResults(prev => ({ ...prev, [id]: { healthy: false, error: String(e) } }));
        }
    }, []);

    return (
        <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '1rem' }}>
                <h2 style={{ fontSize: '1.1rem', fontWeight: 600 }}>LLM Providers</h2>
                <button onClick={() => showForm ? cancelForm() : setShowForm(true)} style={btnPrimary}>
                    {showForm ? 'Cancel' : '+ Add Provider'}
                </button>
            </div>

            {showForm && (
                <div style={cardStyleCompact}>
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem' }}>
                        <div>
                            <label style={labelStyle}>Provider Name</label>
                            <input placeholder="e.g. OpenAI GPT-4o" value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} style={inputStyle} />
                        </div>
                        <div>
                            <label style={labelStyle}>Base URL</label>
                            <input placeholder="https://api.openai.com/v1" value={form.base_url} onChange={e => setForm({ ...form, base_url: e.target.value })} style={inputStyle} />
                        </div>
                        <div>
                            <label style={labelStyle}>API Key</label>
                            <input placeholder={editingId ? 'Leave blank to keep current' : 'sk-...'} type="password" value={form.api_key} onChange={e => setForm({ ...form, api_key: e.target.value })} style={inputStyle} />
                        </div>
                        <div>
                            <label style={labelStyle}>Model</label>
                            <input placeholder="gpt-4o-mini" value={form.model_id} onChange={e => setForm({ ...form, model_id: e.target.value })} style={inputStyle} />
                        </div>
                        <div>
                            <label style={labelStyle}>Temperature</label>
                            <input placeholder="0.7" value={form.temperature} onChange={e => setForm({ ...form, temperature: e.target.value })} style={inputStyle} />
                        </div>
                        <div>
                            <label style={labelStyle}>Max Tokens</label>
                            <input placeholder="4096" value={form.max_tokens} onChange={e => setForm({ ...form, max_tokens: e.target.value })} style={inputStyle} />
                        </div>
                    </div>
                    <button
                        onClick={editingId !== null ? updateProvider : createProvider}
                        style={{ ...btnPrimary, marginTop: '0.75rem' }}
                        disabled={!form.name || (!editingId && !form.api_key)}
                    >
                        {editingId !== null ? 'Update Provider' : 'Create Provider'}
                    </button>
                </div>
            )}

            {loading ? <p>Loading...</p> : providers.length === 0 ? (
                <div style={{ ...cardStyleCompact, textAlign: 'center', color: 'var(--text-secondary)' }}>
                    <p>No providers configured. Add one to get started.</p>
                </div>
            ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                    {providers.map(p => {
                        const health = healthResults[p.id];
                        const isActive = p.is_active !== false;
                        return (
                            <div key={p.id} style={{ ...cardStyleCompact, opacity: isActive ? 1 : 0.5, transition: 'all 0.2s var(--ease-smooth)' }}>
                                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                                        <Switch
                                            checked={isActive}
                                            onCheckedChange={(checked) => toggleActive(p.id, checked)}
                                            style={{ background: isActive ? 'var(--primary)' : 'var(--surface-active)' }}
                                        />
                                        <div>
                                            <strong>{p.name}</strong>
                                            <span style={{ marginLeft: '0.75rem', color: 'var(--text-secondary)', fontSize: '0.85rem' }}>{p.model_id}</span>
                                        </div>
                                    </div>
                                    <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
                                        {health && !health.checking && (
                                            <span style={{ fontSize: '0.8rem', color: health.healthy ? 'var(--success)' : 'var(--danger)' }}>
                                                {health.healthy ? `Healthy (${health.latency_ms}ms)` : `Error: ${health.error?.slice(0, 50)}`}
                                            </span>
                                        )}
                                        {health?.checking && <span style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Checking...</span>}
                                        <button onClick={() => healthCheck(p.id)} style={btnSmall}>Health Check</button>
                                        <button onClick={() => startEditing(p)} style={btnSmall} title="Edit provider">
                                            <Pencil size={14} />
                                        </button>
                                        <button onClick={() => setConfirmState({ open: true, id: p.id })} style={{ ...btnSmall, color: 'var(--danger)' }}>Delete</button>
                                    </div>
                                </div>
                                <p style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginTop: '0.25rem' }}>{p.base_url}</p>
                            </div>
                        );
                    })}
                </div>
            )}

            <ConfirmDialog
                open={confirmState.open}
                onOpenChange={(open) => setConfirmState({ open, id: open ? confirmState.id : null })}
                title="Delete Provider"
                description="This will permanently delete this provider. Any runs referencing it will lose their provider association."
                confirmLabel="Delete"
                variant="danger"
                onConfirm={() => {
                    if (confirmState.id) deleteProvider(confirmState.id);
                }}
            />
        </div>
    );
}
