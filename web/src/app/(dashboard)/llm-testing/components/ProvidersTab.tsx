'use client';
import { useState, useEffect, useCallback, useMemo } from 'react';
import { API_BASE } from '@/lib/api';
import { cardStyleCompact, inputStyle, btnPrimary, btnSecondary, btnSmall, labelStyle } from '@/lib/styles';
import { toast } from 'sonner';
import { ConfirmDialog } from '@/components/ui/confirm-dialog';
import { Switch } from '@/components/ui/switch';
import { Check, KeyRound, Pencil, RefreshCw, Search, Sparkles, X } from 'lucide-react';
import type { Provider } from './types';

interface ProvidersTabProps {
    projectId: string;
}

const defaultForm = {
    name: '', base_url: 'https://api.openai.com/v1', api_key: '', model_id: 'gpt-4o-mini',
    temperature: '0.7', max_tokens: '4096',
};

interface OpenRouterModel {
    id: string;
    name: string;
    description: string;
    context_length: number | null;
    pricing: {
        prompt?: string | null;
        completion?: string | null;
    };
    supported_parameters: string[];
}

function pricePerMillion(value?: string | null): string {
    if (!value) return '-';
    const n = Number(value);
    if (!Number.isFinite(n)) return '-';
    if (n === 0) return 'Free';
    return `$${(n * 1_000_000).toFixed(n * 1_000_000 < 1 ? 3 : 2)}/1M`;
}

export default function ProvidersTab({ projectId }: ProvidersTabProps) {
    const [providers, setProviders] = useState<Provider[]>([]);
    const [loading, setLoading] = useState(true);
    const [showForm, setShowForm] = useState(false);
    const [healthResults, setHealthResults] = useState<Record<string, any>>({});
    const [editingId, setEditingId] = useState<number | null>(null);
    const [confirmState, setConfirmState] = useState<{ open: boolean; id: string | null }>({ open: false, id: null });
    const [showOpenRouterDemo, setShowOpenRouterDemo] = useState(false);
    const [openRouterKey, setOpenRouterKey] = useState('');
    const [openRouterModels, setOpenRouterModels] = useState<OpenRouterModel[]>([]);
    const [openRouterLoading, setOpenRouterLoading] = useState(false);
    const [openRouterSetupLoading, setOpenRouterSetupLoading] = useState(false);
    const [openRouterSearch, setOpenRouterSearch] = useState('');
    const [selectedOpenRouterModels, setSelectedOpenRouterModels] = useState<string[]>([]);
    const [openRouterResult, setOpenRouterResult] = useState<{
        created: number;
        updated: number;
        specs?: { name: string; created: boolean }[];
        datasets?: { id: string; name: string; created: boolean; total_cases: number }[];
    } | null>(null);

    const [form, setForm] = useState({ ...defaultForm });

    const fetchProviders = useCallback(async () => {
        try {
            const res = await fetch(`${API_BASE}/llm-testing/providers?project_id=${projectId}`);
            if (res.ok) setProviders(await res.json());
        } catch (e) { toast.error('Failed to load providers'); }
        setLoading(false);
    }, [projectId]);

    useEffect(() => { fetchProviders(); }, [fetchProviders]);

    const fetchOpenRouterModels = useCallback(async () => {
        setOpenRouterLoading(true);
        try {
            const res = await fetch(`${API_BASE}/llm-testing/openrouter/models`);
            if (!res.ok) throw new Error('Failed to load OpenRouter models');
            const data = await res.json();
            setOpenRouterModels(data.models || []);
        } catch {
            toast.error('Failed to load OpenRouter models');
        }
        setOpenRouterLoading(false);
    }, []);

    useEffect(() => {
        if (showOpenRouterDemo && openRouterModels.length === 0 && !openRouterLoading) {
            fetchOpenRouterModels();
        }
    }, [showOpenRouterDemo, openRouterModels.length, openRouterLoading, fetchOpenRouterModels]);

    const filteredOpenRouterModels = useMemo(() => {
        const query = openRouterSearch.trim().toLowerCase();
        const models = query
            ? openRouterModels.filter(m => `${m.name} ${m.id}`.toLowerCase().includes(query))
            : openRouterModels;
        return models.slice(0, 80);
    }, [openRouterModels, openRouterSearch]);

    const selectedOpenRouterSet = useMemo(() => new Set(selectedOpenRouterModels), [selectedOpenRouterModels]);

    const toggleOpenRouterModel = useCallback((modelId: string) => {
        setOpenRouterResult(null);
        setSelectedOpenRouterModels(prev => {
            if (prev.includes(modelId)) return prev.filter(id => id !== modelId);
            if (prev.length >= 4) {
                toast.info('Select up to 4 models for the demo');
                return prev;
            }
            return [...prev, modelId];
        });
    }, []);

    const setupOpenRouterDemo = useCallback(async () => {
        if (!openRouterKey.trim()) {
            toast.error('Enter an OpenRouter API key');
            return;
        }
        if (selectedOpenRouterModels.length < 2) {
            toast.error('Select at least 2 OpenRouter models');
            return;
        }
        setOpenRouterSetupLoading(true);
        setOpenRouterResult(null);
        try {
            const res = await fetch(`${API_BASE}/llm-testing/openrouter/demo`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    api_key: openRouterKey.trim(),
                    model_ids: selectedOpenRouterModels,
                    project_id: projectId,
                }),
            });
            if (!res.ok) {
                const data = await res.json().catch(() => ({}));
                throw new Error(data.detail || 'Failed to create OpenRouter demo');
            }
            const data = await res.json();
            setOpenRouterResult({
                created: data.created || 0,
                updated: data.updated || 0,
                specs: data.specs || [],
                datasets: data.datasets || [],
            });
            setOpenRouterKey('');
            await fetchProviders();
            toast.success('OpenRouter demo providers created');
        } catch (e) {
            toast.error(e instanceof Error ? e.message : 'Failed to create OpenRouter demo');
        }
        setOpenRouterSetupLoading(false);
    }, [openRouterKey, selectedOpenRouterModels, projectId, fetchProviders]);

    const setupDemoContent = useCallback(async () => {
        setOpenRouterSetupLoading(true);
        setOpenRouterResult(null);
        try {
            const res = await fetch(`${API_BASE}/llm-testing/demo-content`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ project_id: projectId }),
            });
            if (!res.ok) {
                const data = await res.json().catch(() => ({}));
                throw new Error(data.detail || 'Failed to create demo content');
            }
            const data = await res.json();
            setOpenRouterResult({
                created: 0,
                updated: 0,
                specs: data.specs || [],
                datasets: data.datasets || [],
            });
            toast.success('Demo specs and datasets are ready');
        } catch (e) {
            toast.error(e instanceof Error ? e.message : 'Failed to create demo content');
        }
        setOpenRouterSetupLoading(false);
    }, [projectId]);

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
            const body: Record<string, any> = {
                name: form.name,
                base_url: form.base_url,
                model_id: form.model_id,
                default_params: { temperature: parseFloat(form.temperature), max_tokens: parseInt(form.max_tokens) },
            };
            if (form.api_key.trim()) body.api_key = form.api_key.trim();

            const res = await fetch(`${API_BASE}/llm-testing/providers/${editingId}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
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
                <div style={{ display: 'flex', gap: '0.5rem' }}>
                    <button
                        onClick={() => setShowOpenRouterDemo(prev => !prev)}
                        style={showOpenRouterDemo ? btnSecondary : btnPrimary}
                    >
                        <Sparkles size={14} />
                        OpenRouter Demo
                    </button>
                    <button onClick={() => showForm ? cancelForm() : setShowForm(true)} style={btnPrimary}>
                        {showForm ? 'Cancel' : '+ Add Provider'}
                    </button>
                </div>
            </div>

            {showOpenRouterDemo && (
                <div style={{ ...cardStyleCompact, marginBottom: '1rem' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', gap: '1rem', alignItems: 'flex-start', marginBottom: '0.75rem' }}>
                        <div>
                            <h3 style={{ fontWeight: 600, marginBottom: '0.25rem', display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                                <KeyRound size={16} /> OpenRouter demo setup
                            </h3>
                            <p style={{ color: 'var(--text-secondary)', fontSize: '0.85rem', margin: 0 }}>
                                Create model-specific providers and a sample spec. Runs and comparisons stay manual.
                            </p>
                        </div>
                        <button onClick={fetchOpenRouterModels} disabled={openRouterLoading} style={btnSmall}>
                            <RefreshCw size={14} className={openRouterLoading ? 'animate-spin' : ''} />
                            Refresh
                        </button>
                    </div>

                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: '0.75rem', alignItems: 'end' }}>
                        <div>
                            <label style={labelStyle}>OpenRouter API Key</label>
                            <input
                                placeholder="sk-or-v1-..."
                                type="password"
                                value={openRouterKey}
                                onChange={e => setOpenRouterKey(e.target.value)}
                                style={inputStyle}
                            />
                        </div>
                        <div>
                            <label style={labelStyle}>Search Models</label>
                            <div style={{ position: 'relative' }}>
                                <Search size={14} style={{ position: 'absolute', left: 10, top: '50%', transform: 'translateY(-50%)', color: 'var(--text-secondary)' }} />
                                <input
                                    placeholder="Search by model name or id"
                                    value={openRouterSearch}
                                    onChange={e => setOpenRouterSearch(e.target.value)}
                                    style={{ ...inputStyle, paddingLeft: '2rem' }}
                                />
                            </div>
                        </div>
                    </div>

                    {selectedOpenRouterModels.length > 0 && (
                        <div style={{ display: 'flex', gap: '0.4rem', flexWrap: 'wrap', marginTop: '0.75rem' }}>
                            {selectedOpenRouterModels.map(id => {
                                const model = openRouterModels.find(m => m.id === id);
                                return (
                                    <button
                                        key={id}
                                        onClick={() => toggleOpenRouterModel(id)}
                                        style={{
                                            ...btnSmall,
                                            borderColor: 'var(--primary)',
                                            color: 'var(--primary)',
                                            background: 'var(--primary-glow, rgba(99, 102, 241, 0.08))',
                                        }}
                                    >
                                        {model?.name || id}
                                        <X size={12} />
                                    </button>
                                );
                            })}
                        </div>
                    )}

                    <div style={{ marginTop: '0.75rem', border: '1px solid var(--border)', borderRadius: 'var(--radius)', overflow: 'hidden' }}>
                        {openRouterLoading ? (
                            <div style={{ padding: '1rem', color: 'var(--text-secondary)', fontSize: '0.85rem' }}>Loading models...</div>
                        ) : filteredOpenRouterModels.length === 0 ? (
                            <div style={{ padding: '1rem', color: 'var(--text-secondary)', fontSize: '0.85rem' }}>No matching models found.</div>
                        ) : (
                            <div style={{ maxHeight: 360, overflowY: 'auto' }}>
                                {filteredOpenRouterModels.map(model => {
                                    const selected = selectedOpenRouterSet.has(model.id);
                                    return (
                                        <button
                                            key={model.id}
                                            type="button"
                                            onClick={() => toggleOpenRouterModel(model.id)}
                                            style={{
                                                width: '100%',
                                                textAlign: 'left',
                                                padding: '0.75rem',
                                                border: 0,
                                                borderBottom: '1px solid var(--border-subtle)',
                                                background: selected ? 'var(--primary-glow, rgba(99, 102, 241, 0.08))' : 'transparent',
                                                color: 'var(--text)',
                                                cursor: 'pointer',
                                            }}
                                        >
                                            <div style={{ display: 'flex', justifyContent: 'space-between', gap: '0.75rem', alignItems: 'center' }}>
                                                <div style={{ minWidth: 0 }}>
                                                    <div style={{ fontWeight: 600, fontSize: '0.9rem', display: 'flex', gap: '0.4rem', alignItems: 'center' }}>
                                                        {selected && <Check size={14} style={{ color: 'var(--primary)', flexShrink: 0 }} />}
                                                        <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{model.name}</span>
                                                    </div>
                                                    <div style={{ color: 'var(--text-secondary)', fontSize: '0.78rem', marginTop: '0.15rem', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                                        {model.id}
                                                    </div>
                                                </div>
                                                <div style={{ flexShrink: 0, color: 'var(--text-secondary)', fontSize: '0.75rem', textAlign: 'right' }}>
                                                    <div>{model.context_length ? `${model.context_length.toLocaleString()} ctx` : 'Context n/a'}</div>
                                                    <div>In {pricePerMillion(model.pricing?.prompt)} · Out {pricePerMillion(model.pricing?.completion)}</div>
                                                </div>
                                            </div>
                                        </button>
                                    );
                                })}
                            </div>
                        )}
                    </div>

                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '1rem', marginTop: '0.75rem', flexWrap: 'wrap' }}>
                        <div style={{ color: selectedOpenRouterModels.length < 2 ? 'var(--text-tertiary)' : 'var(--text-secondary)', fontSize: '0.8rem' }}>
                            {selectedOpenRouterModels.length}/4 selected. Select at least 2 models.
                            {openRouterResult && (
                                <span style={{ marginLeft: '0.5rem', color: 'var(--success)' }}>
                                    Ready: {openRouterResult.created} providers created, {openRouterResult.updated} updated, {openRouterResult.specs?.length || 0} specs, {openRouterResult.datasets?.length || 0} datasets.
                                </span>
                            )}
                        </div>
                        <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
                            <button
                                onClick={setupDemoContent}
                                disabled={openRouterSetupLoading}
                                style={{ ...btnSecondary, opacity: openRouterSetupLoading ? 0.5 : 1 }}
                            >
                                Add Example Specs & Datasets
                            </button>
                            <button
                                onClick={setupOpenRouterDemo}
                                disabled={openRouterSetupLoading || !openRouterKey.trim() || selectedOpenRouterModels.length < 2}
                                style={{
                                    ...btnPrimary,
                                    opacity: (openRouterSetupLoading || !openRouterKey.trim() || selectedOpenRouterModels.length < 2) ? 0.5 : 1,
                                    cursor: (openRouterSetupLoading || !openRouterKey.trim() || selectedOpenRouterModels.length < 2) ? 'not-allowed' : 'pointer',
                                }}
                            >
                                {openRouterSetupLoading ? 'Creating...' : 'Create Demo Providers'}
                            </button>
                        </div>
                    </div>
                </div>
            )}

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
