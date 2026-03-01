'use client';
import { useState, useEffect, useCallback, useRef } from 'react';
import { API_BASE } from '@/lib/api';
import { inputStyle, btnPrimary, btnSecondary, cardStyleCompact, thStyle, tdStyle, labelStyle } from '@/lib/styles';
import { toast } from 'sonner';
import { ConfirmDialog } from '@/components/ui/confirm-dialog';
import { Progress } from '@/components/ui/progress';
import { usePolling } from '@/hooks/usePolling';
import {
    Star, Play, GitCompare, Wand2, Loader2,
    ChevronDown, ChevronUp, Check,
} from 'lucide-react';
import type { Dataset, DatasetCase, DatasetVersion, Provider } from './types';

interface DatasetsTabProps {
    projectId: string;
}

export default function DatasetsTab({ projectId }: DatasetsTabProps) {
    const [datasets, setDatasets] = useState<Dataset[]>([]);
    const [selectedId, setSelectedId] = useState<string | null>(null);
    const [cases, setCases] = useState<DatasetCase[]>([]);
    const [selectedDataset, setSelectedDataset] = useState<Dataset | null>(null);
    const [loading, setLoading] = useState(true);
    const [casesLoading, setCasesLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);

    // Editing state
    const [editingName, setEditingName] = useState(false);
    const [editName, setEditName] = useState('');
    const [editDesc, setEditDesc] = useState('');
    const [editTags, setEditTags] = useState('');

    // Inline case editing
    const [expandedCaseId, setExpandedCaseId] = useState<number | null>(null);
    const [caseForm, setCaseForm] = useState({ input_prompt: '', expected_output: '', assertions: '', tags: '' });

    // New case form
    const [showAddCase, setShowAddCase] = useState(false);
    const [newCase, setNewCase] = useState({ input_prompt: '', expected_output: '', assertions: '', tags: '' });

    // New dataset form
    const [showNewDataset, setShowNewDataset] = useState(false);
    const [newDataset, setNewDataset] = useState({ name: '', description: '', tags: '' });

    // Bulk selection (cases)
    const [selectedCaseIds, setSelectedCaseIds] = useState<Set<number>>(new Set());

    // Bulk selection (datasets for bulk run)
    const [selectedDatasetIds, setSelectedDatasetIds] = useState<Set<string>>(new Set());

    // Spec selector for from-spec import
    const [specs, setSpecs] = useState<{ name: string }[]>([]);
    const [showSpecSelector, setShowSpecSelector] = useState(false);

    // Confirm dialogs
    const [confirmDelete, setConfirmDelete] = useState<{ open: boolean; id: string; name: string }>({ open: false, id: '', name: '' });
    const [confirmBulkDelete, setConfirmBulkDelete] = useState(false);

    // Providers
    const [providers, setProviders] = useState<Provider[]>([]);

    // Run dataset
    const [showRunPanel, setShowRunPanel] = useState(false);
    const [runProviderId, setRunProviderId] = useState('');
    const [runJobId, setRunJobId] = useState<string | null>(null);
    const [runProgress, setRunProgress] = useState<any>(null);
    const [isRunning, setIsRunning] = useState(false);

    // Compare dataset
    const [showComparePanel, setShowComparePanel] = useState(false);
    const [compareProviderIds, setCompareProviderIds] = useState<string[]>([]);

    // AI Augment
    const [showAugmentPanel, setShowAugmentPanel] = useState(false);
    const [augmentFocus, setAugmentFocus] = useState('edge_cases');
    const [augmentCount, setAugmentCount] = useState(5);
    const [augmentJobId, setAugmentJobId] = useState<string | null>(null);
    const [augmentResults, setAugmentResults] = useState<any[]>([]);
    const [augmentSelected, setAugmentSelected] = useState<Set<number>>(new Set());
    const [isAugmenting, setIsAugmenting] = useState(false);

    // Bulk run
    const [showBulkRunPanel, setShowBulkRunPanel] = useState(false);
    const [bulkRunProviderId, setBulkRunProviderId] = useState('');

    // Version history
    const [showVersions, setShowVersions] = useState(false);
    const [versions, setVersions] = useState<DatasetVersion[]>([]);
    const [versionsLoading, setVersionsLoading] = useState(false);

    const csvInputRef = useRef<HTMLInputElement>(null);

    const fetchDatasets = useCallback(async () => {
        try {
            const res = await fetch(`${API_BASE}/llm-testing/datasets?project_id=${projectId}`);
            if (res.ok) {
                const data = await res.json();
                setDatasets(data);
            }
        } catch {
            toast.error('Failed to load datasets');
        }
        setLoading(false);
    }, [projectId]);

    const fetchCases = useCallback(async (datasetId: string) => {
        setCasesLoading(true);
        try {
            const res = await fetch(`${API_BASE}/llm-testing/datasets/${datasetId}`);
            if (res.ok) {
                const data = await res.json();
                setCases(data.cases || []);
                setSelectedDataset(data);
                setEditName(data.name);
                setEditDesc(data.description || '');
                setEditTags((data.tags || []).join(', '));
            }
        } catch {
            toast.error('Failed to load cases');
        }
        setCasesLoading(false);
    }, []);

    const fetchSpecs = useCallback(async () => {
        try {
            const res = await fetch(`${API_BASE}/llm-testing/specs?project_id=${projectId}`);
            if (res.ok) setSpecs(await res.json());
        } catch {
            toast.error('Failed to load specs');
        }
    }, [projectId]);

    const fetchProviders = useCallback(async () => {
        try {
            const res = await fetch(`${API_BASE}/llm-testing/providers?project_id=${projectId}`);
            if (res.ok) setProviders(await res.json());
        } catch {}
    }, [projectId]);

    const fetchVersions = useCallback(async (datasetId: string) => {
        setVersionsLoading(true);
        try {
            const res = await fetch(`${API_BASE}/llm-testing/datasets/${datasetId}/versions`);
            if (res.ok) setVersions(await res.json());
        } catch {
            toast.error('Failed to load versions');
        }
        setVersionsLoading(false);
    }, []);

    useEffect(() => { fetchDatasets(); fetchProviders(); }, [fetchDatasets, fetchProviders]);

    useEffect(() => {
        if (selectedId) fetchCases(selectedId);
    }, [selectedId, fetchCases]);

    const selectDataset = (id: string) => {
        setSelectedId(id);
        setExpandedCaseId(null);
        setShowAddCase(false);
        setSelectedCaseIds(new Set());
        setShowRunPanel(false);
        setShowComparePanel(false);
        setShowAugmentPanel(false);
        setShowVersions(false);
    };

    const createDataset = async () => {
        try {
            const res = await fetch(`${API_BASE}/llm-testing/datasets`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    name: newDataset.name,
                    description: newDataset.description,
                    tags: newDataset.tags ? newDataset.tags.split(',').map(t => t.trim()).filter(Boolean) : [],
                    project_id: projectId,
                }),
            });
            if (res.ok) {
                const data = await res.json();
                setShowNewDataset(false);
                setNewDataset({ name: '', description: '', tags: '' });
                await fetchDatasets();
                selectDataset(data.id);
            }
        } catch (e) { setError(String(e)); }
    };

    const deleteDataset = async (id: string) => {
        try {
            await fetch(`${API_BASE}/llm-testing/datasets/${id}`, { method: 'DELETE' });
            if (selectedId === id) {
                setSelectedId(null);
                setCases([]);
                setSelectedDataset(null);
            }
            toast.success('Dataset deleted');
            fetchDatasets();
        } catch {
            toast.error('Failed to delete dataset');
        }
    };

    const updateDatasetMeta = async () => {
        if (!selectedId) return;
        await fetch(`${API_BASE}/llm-testing/datasets/${selectedId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                name: editName,
                description: editDesc,
                tags: editTags ? editTags.split(',').map(t => t.trim()).filter(Boolean) : [],
            }),
        });
        setEditingName(false);
        fetchDatasets();
        fetchCases(selectedId);
    };

    const addCase = async () => {
        if (!selectedId || !newCase.input_prompt.trim()) return;
        const assertions: { type: string; value: string }[] = [];
        if (newCase.assertions.trim()) {
            for (const part of newCase.assertions.split(';')) {
                const [type, ...rest] = part.split(':');
                if (type && rest.length) assertions.push({ type: type.trim(), value: rest.join(':').trim() });
            }
        }
        const tags = newCase.tags ? newCase.tags.split(',').map(t => t.trim()).filter(Boolean) : [];
        await fetch(`${API_BASE}/llm-testing/datasets/${selectedId}/cases`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify([{ input_prompt: newCase.input_prompt, expected_output: newCase.expected_output, assertions, tags }]),
        });
        setNewCase({ input_prompt: '', expected_output: '', assertions: '', tags: '' });
        setShowAddCase(false);
        fetchCases(selectedId);
        fetchDatasets();
    };

    const updateCase = async (caseId: number) => {
        if (!selectedId) return;
        const assertions: { type: string; value: string }[] = [];
        if (caseForm.assertions.trim()) {
            for (const part of caseForm.assertions.split(';')) {
                const [type, ...rest] = part.split(':');
                if (type && rest.length) assertions.push({ type: type.trim(), value: rest.join(':').trim() });
            }
        }
        const tags = caseForm.tags ? caseForm.tags.split(',').map(t => t.trim()).filter(Boolean) : [];
        await fetch(`${API_BASE}/llm-testing/datasets/${selectedId}/cases/${caseId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ input_prompt: caseForm.input_prompt, expected_output: caseForm.expected_output, assertions, tags }),
        });
        setExpandedCaseId(null);
        fetchCases(selectedId);
    };

    const deleteCase = async (caseId: number) => {
        if (!selectedId) return;
        await fetch(`${API_BASE}/llm-testing/datasets/${selectedId}/cases/${caseId}`, { method: 'DELETE' });
        fetchCases(selectedId);
        fetchDatasets();
    };

    const bulkDelete = async () => {
        if (!selectedId || selectedCaseIds.size === 0) return;
        for (const caseId of selectedCaseIds) {
            await fetch(`${API_BASE}/llm-testing/datasets/${selectedId}/cases/${caseId}`, { method: 'DELETE' });
        }
        setSelectedCaseIds(new Set());
        toast.success(`${selectedCaseIds.size} cases deleted`);
        fetchCases(selectedId);
        fetchDatasets();
    };

    const expandCase = (c: DatasetCase) => {
        setExpandedCaseId(c.id);
        setCaseForm({
            input_prompt: c.input_prompt,
            expected_output: c.expected_output,
            assertions: c.assertions.map(a => `${a.type}:${a.value}`).join('; '),
            tags: c.tags.join(', '),
        });
    };

    const handleCsvImport = async (e: React.ChangeEvent<HTMLInputElement>) => {
        const file = e.target.files?.[0];
        if (!file) return;
        const formData = new FormData();
        formData.append('file', file);
        try {
            const res = await fetch(`${API_BASE}/llm-testing/datasets/import-csv?name=${encodeURIComponent(file.name.replace('.csv', ''))}&project_id=${projectId}`, {
                method: 'POST',
                body: formData,
            });
            if (res.ok) {
                const data = await res.json();
                await fetchDatasets();
                selectDataset(data.id);
            }
        } catch (err) { setError(String(err)); }
        if (csvInputRef.current) csvInputRef.current.value = '';
    };

    const importFromSpec = async (specName: string) => {
        try {
            const res = await fetch(`${API_BASE}/llm-testing/datasets/from-spec/${specName}?project_id=${projectId}`, { method: 'POST' });
            if (res.ok) {
                const data = await res.json();
                setShowSpecSelector(false);
                await fetchDatasets();
                selectDataset(data.id);
            }
        } catch (err) { setError(String(err)); }
    };

    const exportDataset = async (fmt: 'csv' | 'json') => {
        if (!selectedId) return;
        const res = await fetch(`${API_BASE}/llm-testing/datasets/${selectedId}/export?format=${fmt}`);
        if (!res.ok) return;
        if (fmt === 'csv') {
            const blob = await res.blob();
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url; a.download = `${selectedId}.csv`; a.click();
            URL.revokeObjectURL(url);
        } else {
            const data = await res.json();
            const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url; a.download = `${selectedId}.json`; a.click();
            URL.revokeObjectURL(url);
        }
    };

    const convertToSpec = async () => {
        if (!selectedId) return;
        try {
            const res = await fetch(`${API_BASE}/llm-testing/datasets/${selectedId}/to-spec?project_id=${projectId}`, { method: 'POST' });
            if (res.ok) {
                const data = await res.json();
                toast.success(`Spec created: ${data.spec_name}`);
            }
        } catch {
            toast.error('Failed to convert to spec');
        }
    };

    const duplicateDataset = async () => {
        if (!selectedId) return;
        const res = await fetch(`${API_BASE}/llm-testing/datasets/${selectedId}/duplicate`, { method: 'POST' });
        if (res.ok) {
            const data = await res.json();
            await fetchDatasets();
            selectDataset(data.id);
        }
    };

    const toggleCaseSelect = (id: number) => {
        setSelectedCaseIds(prev => {
            const next = new Set(prev);
            if (next.has(id)) next.delete(id); else next.add(id);
            return next;
        });
    };

    const toggleAllCases = () => {
        if (selectedCaseIds.size === cases.length) {
            setSelectedCaseIds(new Set());
        } else {
            setSelectedCaseIds(new Set(cases.map(c => c.id)));
        }
    };

    // Golden toggle
    const toggleGolden = async (dataset: Dataset, e: React.MouseEvent) => {
        e.stopPropagation();
        try {
            const res = await fetch(`${API_BASE}/llm-testing/datasets/${dataset.id}/golden?is_golden=${!dataset.is_golden}`, { method: 'POST' });
            if (res.ok) {
                toast.success(dataset.is_golden ? 'Removed from golden baselines' : 'Marked as golden baseline');
                fetchDatasets();
                if (selectedId === dataset.id && selectedDataset) {
                    setSelectedDataset({ ...selectedDataset, is_golden: !dataset.is_golden });
                }
            }
        } catch {
            toast.error('Failed to toggle golden status');
        }
    };

    // Run dataset
    const startDatasetRun = async () => {
        if (!selectedId || !runProviderId) return;
        setIsRunning(true);
        setRunProgress(null);
        try {
            const res = await fetch(`${API_BASE}/llm-testing/datasets/${selectedId}/run`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ provider_id: runProviderId, project_id: projectId }),
            });
            if (res.ok) {
                const data = await res.json();
                setRunJobId(data.job_id);
                toast.success('Dataset run started');
            } else {
                toast.error('Failed to start run');
                setIsRunning(false);
            }
        } catch {
            toast.error('Failed to start run');
            setIsRunning(false);
        }
    };

    // Poll run progress
    const runPollFn = useCallback(async () => {
        if (!runJobId) return;
        const res = await fetch(`${API_BASE}/llm-testing/jobs/${runJobId}`);
        if (res.ok) {
            const job = await res.json();
            setRunProgress(job);
            if (job.status === 'completed' || job.status === 'failed') {
                setRunJobId(null);
                setIsRunning(false);
                if (job.status === 'completed') toast.success('Dataset run completed');
                if (job.status === 'failed') toast.error(job.error || 'Run failed');
            }
        }
    }, [runJobId]);

    const { stop: stopRunPoll } = usePolling(runPollFn, { interval: 1500, enabled: !!runJobId });
    useEffect(() => { if (!runJobId) stopRunPoll(); }, [runJobId, stopRunPoll]);

    // Compare dataset
    const toggleCompareProvider = (id: string) => {
        setCompareProviderIds(prev => prev.includes(id) ? prev.filter(p => p !== id) : [...prev, id]);
    };

    const startDatasetCompare = async () => {
        if (!selectedId || compareProviderIds.length < 2) return;
        try {
            const res = await fetch(`${API_BASE}/llm-testing/datasets/${selectedId}/compare`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ provider_ids: compareProviderIds, project_id: projectId }),
            });
            if (res.ok) {
                toast.success('Dataset comparison started');
                setShowComparePanel(false);
                setCompareProviderIds([]);
            } else {
                toast.error('Failed to start comparison');
            }
        } catch {
            toast.error('Failed to start comparison');
        }
    };

    // AI Augment
    const startAugment = async () => {
        if (!selectedId) return;
        setIsAugmenting(true);
        setAugmentResults([]);
        try {
            const res = await fetch(`${API_BASE}/llm-testing/datasets/${selectedId}/augment`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ focus: augmentFocus, count: augmentCount }),
            });
            if (res.ok) {
                const data = await res.json();
                setAugmentJobId(data.job_id);
            } else {
                toast.error('Failed to start augmentation');
                setIsAugmenting(false);
            }
        } catch {
            toast.error('Failed to start augmentation');
            setIsAugmenting(false);
        }
    };

    // Poll augment job
    const augmentPollFn = useCallback(async () => {
        if (!augmentJobId) return;
        const res = await fetch(`${API_BASE}/llm-testing/jobs/${augmentJobId}`);
        if (res.ok) {
            const job = await res.json();
            if (job.status === 'completed') {
                setAugmentJobId(null);
                setIsAugmenting(false);
                const generated = job.result?.cases || job.cases || [];
                setAugmentResults(generated);
                setAugmentSelected(new Set(generated.map((_: any, i: number) => i)));
                toast.success(`Generated ${generated.length} cases`);
            } else if (job.status === 'failed') {
                setAugmentJobId(null);
                setIsAugmenting(false);
                toast.error(job.error || 'Augmentation failed');
            }
        }
    }, [augmentJobId]);

    const { stop: stopAugmentPoll } = usePolling(augmentPollFn, { interval: 2000, enabled: !!augmentJobId });
    useEffect(() => { if (!augmentJobId) stopAugmentPoll(); }, [augmentJobId, stopAugmentPoll]);

    const acceptAugmented = async () => {
        if (!selectedId || augmentResults.length === 0) return;
        const selected = augmentResults.filter((_, i) => augmentSelected.has(i));
        if (selected.length === 0) { toast.error('No cases selected'); return; }
        try {
            const endpoint = augmentJobId
                ? `${API_BASE}/llm-testing/datasets/${selectedId}/augment/${augmentJobId}/accept`
                : `${API_BASE}/llm-testing/datasets/${selectedId}/cases`;
            const res = await fetch(endpoint, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(selected),
            });
            if (res.ok) {
                toast.success(`Added ${selected.length} cases`);
                setAugmentResults([]);
                setAugmentSelected(new Set());
                setShowAugmentPanel(false);
                fetchCases(selectedId);
                fetchDatasets();
            }
        } catch {
            toast.error('Failed to add cases');
        }
    };

    // Bulk dataset run
    const toggleDatasetSelect = (id: string, e: React.MouseEvent) => {
        e.stopPropagation();
        setSelectedDatasetIds(prev => {
            const next = new Set(prev);
            if (next.has(id)) next.delete(id); else next.add(id);
            return next;
        });
    };

    const startBulkRun = async () => {
        if (selectedDatasetIds.size === 0 || !bulkRunProviderId) return;
        for (const dsId of selectedDatasetIds) {
            try {
                await fetch(`${API_BASE}/llm-testing/datasets/${dsId}/run`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ provider_id: bulkRunProviderId, project_id: projectId }),
                });
            } catch {}
        }
        toast.success(`Started runs for ${selectedDatasetIds.size} datasets`);
        setShowBulkRunPanel(false);
        setSelectedDatasetIds(new Set());
        setBulkRunProviderId('');
    };

    const runPct = runProgress && runProgress.progress_total > 0
        ? Math.round((runProgress.progress_current / runProgress.progress_total) * 100) : 0;

    if (loading) return <div style={{ padding: '2rem', color: 'var(--text-secondary)' }}>Loading datasets...</div>;

    return (
        <div style={{ display: 'flex', gap: '1rem', height: 'calc(100vh - 220px)', minHeight: '500px' }}>
            {/* Left Panel - Dataset List */}
            <div style={{ width: '300px', flexShrink: 0, display: 'flex', flexDirection: 'column', borderRight: '1px solid var(--border)', paddingRight: '1rem' }}>
                {/* Toolbar */}
                <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '0.75rem', flexWrap: 'wrap' }}>
                    <button onClick={() => setShowNewDataset(true)} style={{ ...btnPrimary, fontSize: '0.8rem', padding: '0.35rem 0.75rem' }}>+ New</button>
                    <button onClick={() => csvInputRef.current?.click()} style={{ ...btnSecondary, fontSize: '0.8rem', padding: '0.35rem 0.75rem' }}>Import CSV</button>
                    <button onClick={() => { fetchSpecs(); setShowSpecSelector(true); }} style={{ ...btnSecondary, fontSize: '0.8rem', padding: '0.35rem 0.75rem' }}>From Spec</button>
                    <input ref={csvInputRef} type="file" accept=".csv" onChange={handleCsvImport} style={{ display: 'none' }} />
                </div>

                {/* Bulk Run Button */}
                {selectedDatasetIds.size > 0 && (
                    <button onClick={() => { fetchProviders(); setShowBulkRunPanel(true); }}
                        style={{ ...btnPrimary, fontSize: '0.8rem', padding: '0.35rem 0.75rem', marginBottom: '0.5rem', background: 'var(--success)' }}>
                        <Play size={14} /> Run Selected ({selectedDatasetIds.size})
                    </button>
                )}

                {/* Bulk Run Provider Selector */}
                {showBulkRunPanel && (
                    <div style={{ ...cardStyleCompact, marginBottom: '0.5rem' }}>
                        <div style={{ fontSize: '0.8rem', fontWeight: 600, marginBottom: '0.5rem' }}>Select provider for bulk run:</div>
                        <select value={bulkRunProviderId} onChange={e => setBulkRunProviderId(e.target.value)} style={{ ...inputStyle, marginBottom: '0.5rem' }}>
                            <option value="">Select provider...</option>
                            {providers.map(p => <option key={p.id} value={p.id}>{p.name} ({p.model_id})</option>)}
                        </select>
                        <div style={{ display: 'flex', gap: '0.5rem' }}>
                            <button onClick={startBulkRun} disabled={!bulkRunProviderId} style={{ ...btnPrimary, fontSize: '0.8rem', padding: '0.3rem 0.6rem', opacity: bulkRunProviderId ? 1 : 0.5 }}>Start</button>
                            <button onClick={() => setShowBulkRunPanel(false)} style={{ ...btnSecondary, fontSize: '0.8rem', padding: '0.3rem 0.6rem' }}>Cancel</button>
                        </div>
                    </div>
                )}

                {/* New Dataset Form */}
                {showNewDataset && (
                    <div style={{ ...cardStyleCompact, marginBottom: '0.5rem' }}>
                        <input placeholder="Dataset name" value={newDataset.name} onChange={e => setNewDataset({ ...newDataset, name: e.target.value })} style={{ ...inputStyle, marginBottom: '0.5rem' }} />
                        <input placeholder="Description" value={newDataset.description} onChange={e => setNewDataset({ ...newDataset, description: e.target.value })} style={{ ...inputStyle, marginBottom: '0.5rem' }} />
                        <input placeholder="Tags (comma-separated)" value={newDataset.tags} onChange={e => setNewDataset({ ...newDataset, tags: e.target.value })} style={{ ...inputStyle, marginBottom: '0.5rem' }} />
                        <div style={{ display: 'flex', gap: '0.5rem' }}>
                            <button onClick={createDataset} style={{ ...btnPrimary, fontSize: '0.8rem', padding: '0.3rem 0.6rem' }}>Create</button>
                            <button onClick={() => setShowNewDataset(false)} style={{ ...btnSecondary, fontSize: '0.8rem', padding: '0.3rem 0.6rem' }}>Cancel</button>
                        </div>
                    </div>
                )}

                {/* Spec Selector Modal */}
                {showSpecSelector && (
                    <div style={{ ...cardStyleCompact, marginBottom: '0.5rem', maxHeight: '200px', overflowY: 'auto' }}>
                        <div style={{ fontSize: '0.8rem', fontWeight: 600, marginBottom: '0.5rem' }}>Select a spec:</div>
                        {specs.length === 0 && <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>No specs found</div>}
                        {specs.map(s => (
                            <div key={s.name} onClick={() => importFromSpec(s.name)} style={{ padding: '0.3rem 0.5rem', cursor: 'pointer', borderRadius: 'var(--radius)', fontSize: '0.8rem' }}
                                onMouseEnter={e => (e.currentTarget.style.background = 'var(--surface-hover)')}
                                onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}>
                                {s.name}
                            </div>
                        ))}
                        <button onClick={() => setShowSpecSelector(false)} style={{ ...btnSecondary, fontSize: '0.75rem', padding: '0.2rem 0.5rem', marginTop: '0.5rem' }}>Cancel</button>
                    </div>
                )}

                {/* Dataset List */}
                <div style={{ flex: 1, overflowY: 'auto' }}>
                    {datasets.length === 0 && (
                        <div style={{ padding: '1rem', color: 'var(--text-secondary)', fontSize: '0.85rem' }}>
                            No datasets yet. Create one or import from CSV.
                        </div>
                    )}
                    {datasets.map(d => (
                        <div key={d.id} onClick={() => selectDataset(d.id)}
                            style={{
                                padding: '0.6rem 0.75rem',
                                cursor: 'pointer',
                                borderRadius: 'var(--radius)',
                                marginBottom: '0.25rem',
                                background: selectedId === d.id ? 'var(--primary-light, rgba(59,130,246,0.1))' : 'transparent',
                                border: selectedId === d.id ? '1px solid var(--primary)' : '1px solid transparent',
                            }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem', flex: 1, overflow: 'hidden' }}>
                                    <input type="checkbox" checked={selectedDatasetIds.has(d.id)}
                                        onClick={e => e.stopPropagation()}
                                        onChange={e => toggleDatasetSelect(d.id, e as any)}
                                        style={{ flexShrink: 0 }} />
                                    <button onClick={e => toggleGolden(d, e)}
                                        style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 0, flexShrink: 0, lineHeight: 1 }}
                                        title={d.is_golden ? 'Remove golden baseline' : 'Mark as golden baseline'}>
                                        <Star size={14} style={{ color: '#f59e0b', fill: d.is_golden ? '#f59e0b' : 'none' }} />
                                    </button>
                                    <span style={{ fontSize: '0.85rem', fontWeight: selectedId === d.id ? 600 : 400, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                        {d.name}
                                    </span>
                                </div>
                                <button onClick={(e) => {
                                    e.stopPropagation();
                                    setConfirmDelete({ open: true, id: d.id, name: d.name });
                                }}
                                    style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-secondary)', fontSize: '0.9rem', padding: '0 0.25rem', lineHeight: 1 }}
                                    title="Delete dataset">
                                    x
                                </button>
                            </div>
                            <div style={{ display: 'flex', gap: '0.5rem', marginTop: '0.25rem', alignItems: 'center', paddingLeft: '2.5rem' }}>
                                <span style={{ fontSize: '0.7rem', background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: '4px', padding: '0.1rem 0.4rem' }}>
                                    {d.total_cases} cases
                                </span>
                                <span style={{ fontSize: '0.7rem', color: 'var(--text-secondary)' }}>v{d.version}</span>
                                {d.tags.slice(0, 2).map(t => (
                                    <span key={t} style={{ fontSize: '0.65rem', background: 'var(--primary-light, rgba(59,130,246,0.1))', color: 'var(--primary)', borderRadius: '4px', padding: '0.1rem 0.3rem' }}>
                                        {t}
                                    </span>
                                ))}
                            </div>
                        </div>
                    ))}
                </div>
            </div>

            {/* Right Panel - Dataset Details */}
            <div style={{ flex: 1, overflowY: 'auto', minWidth: 0 }}>
                {!selectedId && (
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', color: 'var(--text-secondary)' }}>
                        Select a dataset from the left panel
                    </div>
                )}

                {selectedId && selectedDataset && (
                    <div>
                        {/* Dataset Header */}
                        <div style={{ marginBottom: '1rem' }}>
                            {editingName ? (
                                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                                    <input value={editName} onChange={e => setEditName(e.target.value)} style={{ ...inputStyle, fontWeight: 600, fontSize: '1.1rem' }} />
                                    <input value={editDesc} onChange={e => setEditDesc(e.target.value)} placeholder="Description" style={inputStyle} />
                                    <input value={editTags} onChange={e => setEditTags(e.target.value)} placeholder="Tags (comma-separated)" style={inputStyle} />
                                    <div style={{ display: 'flex', gap: '0.5rem' }}>
                                        <button onClick={updateDatasetMeta} style={{ ...btnPrimary, fontSize: '0.8rem', padding: '0.3rem 0.6rem' }}>Save</button>
                                        <button onClick={() => setEditingName(false)} style={{ ...btnSecondary, fontSize: '0.8rem', padding: '0.3rem 0.6rem' }}>Cancel</button>
                                    </div>
                                </div>
                            ) : (
                                <div>
                                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                                        <button onClick={e => toggleGolden(selectedDataset, e)}
                                            style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 0, lineHeight: 1 }}
                                            title={selectedDataset.is_golden ? 'Remove golden baseline' : 'Mark as golden baseline'}>
                                            <Star size={18} style={{ color: '#f59e0b', fill: selectedDataset.is_golden ? '#f59e0b' : 'none' }} />
                                        </button>
                                        <h2 style={{ fontSize: '1.1rem', fontWeight: 600, margin: 0, cursor: 'pointer' }} onClick={() => setEditingName(true)} title="Click to edit">
                                            {selectedDataset.name}
                                        </h2>
                                        <button onClick={() => setEditingName(true)} style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-secondary)', fontSize: '0.8rem' }}>edit</button>
                                    </div>
                                    {selectedDataset.description && <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginTop: '0.25rem' }}>{selectedDataset.description}</div>}
                                    {selectedDataset.tags.length > 0 && (
                                        <div style={{ display: 'flex', gap: '0.25rem', marginTop: '0.25rem', flexWrap: 'wrap' }}>
                                            {selectedDataset.tags.map(t => (
                                                <span key={t} style={{ fontSize: '0.7rem', background: 'var(--primary-light, rgba(59,130,246,0.1))', color: 'var(--primary)', borderRadius: '4px', padding: '0.1rem 0.4rem' }}>{t}</span>
                                            ))}
                                        </div>
                                    )}
                                </div>
                            )}
                        </div>

                        {/* Action Toolbar */}
                        <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '1rem', flexWrap: 'wrap' }}>
                            <button onClick={() => { fetchProviders(); setShowRunPanel(!showRunPanel); setShowComparePanel(false); setShowAugmentPanel(false); }}
                                style={{ ...btnPrimary, fontSize: '0.8rem', padding: '0.3rem 0.6rem', background: 'var(--success)' }}>
                                <Play size={14} /> Run
                            </button>
                            <button onClick={() => { fetchProviders(); setShowComparePanel(!showComparePanel); setShowRunPanel(false); setShowAugmentPanel(false); }}
                                style={{ ...btnSecondary, fontSize: '0.8rem', padding: '0.3rem 0.6rem' }}>
                                <GitCompare size={14} /> Compare
                            </button>
                            <button onClick={() => { setShowAugmentPanel(!showAugmentPanel); setShowRunPanel(false); setShowComparePanel(false); }}
                                style={{ ...btnSecondary, fontSize: '0.8rem', padding: '0.3rem 0.6rem' }}>
                                <Wand2 size={14} /> AI Augment
                            </button>
                            <button onClick={() => exportDataset('csv')} style={{ ...btnSecondary, fontSize: '0.8rem', padding: '0.3rem 0.6rem' }}>Export CSV</button>
                            <button onClick={() => exportDataset('json')} style={{ ...btnSecondary, fontSize: '0.8rem', padding: '0.3rem 0.6rem' }}>Export JSON</button>
                            <button onClick={convertToSpec} style={{ ...btnSecondary, fontSize: '0.8rem', padding: '0.3rem 0.6rem' }}>Convert to Spec</button>
                            <button onClick={duplicateDataset} style={{ ...btnSecondary, fontSize: '0.8rem', padding: '0.3rem 0.6rem' }}>Duplicate</button>
                            {selectedCaseIds.size > 0 && (
                                <button onClick={() => setConfirmBulkDelete(true)} style={{ ...btnSecondary, fontSize: '0.8rem', padding: '0.3rem 0.6rem', color: 'var(--danger)', borderColor: 'var(--danger)' }}>
                                    Delete Selected ({selectedCaseIds.size})
                                </button>
                            )}
                        </div>

                        {/* Run Panel */}
                        {showRunPanel && (
                            <div style={{ ...cardStyleCompact, marginBottom: '0.75rem' }}>
                                <div style={{ fontSize: '0.85rem', fontWeight: 600, marginBottom: '0.5rem' }}>Run Dataset</div>
                                <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'flex-end' }}>
                                    <div style={{ flex: 1 }}>
                                        <select value={runProviderId} onChange={e => setRunProviderId(e.target.value)} disabled={isRunning} style={inputStyle}>
                                            <option value="">Select provider...</option>
                                            {providers.map(p => <option key={p.id} value={p.id}>{p.name} ({p.model_id})</option>)}
                                        </select>
                                    </div>
                                    <button onClick={startDatasetRun} disabled={isRunning || !runProviderId}
                                        style={{ ...btnPrimary, fontSize: '0.8rem', padding: '0.4rem 0.75rem', opacity: (isRunning || !runProviderId) ? 0.5 : 1 }}>
                                        {isRunning ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />}
                                        {isRunning ? 'Running...' : 'Start'}
                                    </button>
                                </div>
                                {isRunning && runProgress && runProgress.progress_total > 0 && (
                                    <div style={{ marginTop: '0.5rem' }}>
                                        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '0.25rem' }}>
                                            <span>{runProgress.progress_current}/{runProgress.progress_total}</span>
                                            <span>{runPct}%</span>
                                        </div>
                                        <Progress value={runPct} className="h-2" />
                                        {runProgress.passed != null && (
                                            <div style={{ display: 'flex', gap: '0.75rem', fontSize: '0.8rem', marginTop: '0.35rem' }}>
                                                <span style={{ color: 'var(--success)', fontWeight: 500 }}>Passed: {runProgress.passed}</span>
                                                <span style={{ color: 'var(--danger)', fontWeight: 500 }}>Failed: {runProgress.failed}</span>
                                            </div>
                                        )}
                                    </div>
                                )}
                                {!isRunning && runProgress?.status === 'completed' && (
                                    <div style={{ marginTop: '0.5rem', fontSize: '0.85rem', color: 'var(--success)', fontWeight: 500 }}>
                                        Run completed - check History tab for details
                                    </div>
                                )}
                            </div>
                        )}

                        {/* Compare Panel */}
                        {showComparePanel && (
                            <div style={{ ...cardStyleCompact, marginBottom: '0.75rem' }}>
                                <div style={{ fontSize: '0.85rem', fontWeight: 600, marginBottom: '0.5rem' }}>Compare Providers (select 2+)</div>
                                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.35rem', marginBottom: '0.5rem' }}>
                                    {providers.map(p => (
                                        <label key={p.id} style={{ display: 'flex', alignItems: 'center', gap: '0.35rem', fontSize: '0.85rem', cursor: 'pointer' }}>
                                            <input type="checkbox" checked={compareProviderIds.includes(p.id)} onChange={() => toggleCompareProvider(p.id)} />
                                            {p.name} ({p.model_id})
                                        </label>
                                    ))}
                                </div>
                                <button onClick={startDatasetCompare} disabled={compareProviderIds.length < 2}
                                    style={{ ...btnPrimary, fontSize: '0.8rem', padding: '0.3rem 0.6rem', opacity: compareProviderIds.length < 2 ? 0.5 : 1 }}>
                                    <GitCompare size={14} /> Start Comparison
                                </button>
                            </div>
                        )}

                        {/* AI Augment Panel */}
                        {showAugmentPanel && (
                            <div style={{ ...cardStyleCompact, marginBottom: '0.75rem' }}>
                                <div style={{ fontSize: '0.85rem', fontWeight: 600, marginBottom: '0.5rem' }}>AI Augmentation</div>
                                <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'flex-end', flexWrap: 'wrap', marginBottom: '0.5rem' }}>
                                    <div style={{ flex: '1 1 150px' }}>
                                        <label style={{ ...labelStyle, fontSize: '0.8rem' }}>Focus</label>
                                        <select value={augmentFocus} onChange={e => setAugmentFocus(e.target.value)} style={inputStyle} disabled={isAugmenting}>
                                            <option value="edge_cases">Edge Cases</option>
                                            <option value="adversarial">Adversarial</option>
                                            <option value="boundary">Boundary</option>
                                            <option value="rephrase">Rephrase</option>
                                        </select>
                                    </div>
                                    <div style={{ width: '80px' }}>
                                        <label style={{ ...labelStyle, fontSize: '0.8rem' }}>Count</label>
                                        <input type="number" min={1} max={20} value={augmentCount} onChange={e => setAugmentCount(Number(e.target.value))}
                                            style={inputStyle} disabled={isAugmenting} />
                                    </div>
                                    <button onClick={startAugment} disabled={isAugmenting}
                                        style={{ ...btnPrimary, fontSize: '0.8rem', padding: '0.4rem 0.75rem', opacity: isAugmenting ? 0.5 : 1 }}>
                                        {isAugmenting ? <Loader2 size={14} className="animate-spin" /> : <Wand2 size={14} />}
                                        {isAugmenting ? 'Generating...' : 'Generate'}
                                    </button>
                                </div>

                                {/* Augment Preview */}
                                {augmentResults.length > 0 && (
                                    <div>
                                        <div style={{ fontSize: '0.8rem', fontWeight: 600, marginBottom: '0.35rem' }}>
                                            Preview ({augmentResults.length} generated)
                                        </div>
                                        <div style={{ maxHeight: '250px', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '0.35rem' }}>
                                            {augmentResults.map((c: any, i: number) => (
                                                <div key={i} style={{
                                                    padding: '0.5rem 0.75rem', borderRadius: 'var(--radius)',
                                                    border: '1px solid var(--border-subtle)', background: 'var(--background-raised)',
                                                    display: 'flex', gap: '0.5rem', alignItems: 'flex-start',
                                                }}>
                                                    <input type="checkbox" checked={augmentSelected.has(i)}
                                                        onChange={() => {
                                                            setAugmentSelected(prev => {
                                                                const next = new Set(prev);
                                                                if (next.has(i)) next.delete(i); else next.add(i);
                                                                return next;
                                                            });
                                                        }}
                                                        style={{ marginTop: '0.15rem', flexShrink: 0 }} />
                                                    <div style={{ fontSize: '0.8rem', flex: 1 }}>
                                                        <div style={{ fontWeight: 500, marginBottom: '0.15rem' }}>
                                                            {(c.input_prompt || '').length > 100 ? (c.input_prompt || '').substring(0, 100) + '...' : c.input_prompt}
                                                        </div>
                                                        {c.expected_output && (
                                                            <div style={{ color: 'var(--text-secondary)', fontSize: '0.75rem' }}>
                                                                Expected: {c.expected_output.length > 60 ? c.expected_output.substring(0, 60) + '...' : c.expected_output}
                                                            </div>
                                                        )}
                                                    </div>
                                                </div>
                                            ))}
                                        </div>
                                        <div style={{ display: 'flex', gap: '0.5rem', marginTop: '0.5rem' }}>
                                            <button onClick={acceptAugmented}
                                                style={{ ...btnPrimary, fontSize: '0.8rem', padding: '0.3rem 0.6rem' }}>
                                                <Check size={14} /> Add Selected ({augmentSelected.size})
                                            </button>
                                            <button onClick={() => { setAugmentResults([]); setAugmentSelected(new Set()); }}
                                                style={{ ...btnSecondary, fontSize: '0.8rem', padding: '0.3rem 0.6rem' }}>Discard</button>
                                        </div>
                                    </div>
                                )}
                            </div>
                        )}

                        {/* Version History (collapsible) */}
                        <div style={{ marginBottom: '0.75rem' }}>
                            <button
                                onClick={() => {
                                    if (!showVersions && selectedId) fetchVersions(selectedId);
                                    setShowVersions(!showVersions);
                                }}
                                style={{ ...btnSecondary, fontSize: '0.8rem', padding: '0.3rem 0.6rem' }}>
                                {showVersions ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                                Version History (v{selectedDataset.version})
                            </button>
                            {showVersions && (
                                <div style={{ marginTop: '0.5rem' }}>
                                    {versionsLoading ? (
                                        <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Loading versions...</div>
                                    ) : versions.length === 0 ? (
                                        <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>No version history yet.</div>
                                    ) : (
                                        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem' }}>
                                            {versions.map(v => (
                                                <div key={v.id} style={{
                                                    padding: '0.4rem 0.6rem', borderRadius: 'var(--radius)',
                                                    border: '1px solid var(--border-subtle)', background: 'var(--background-raised)',
                                                    fontSize: '0.8rem', display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                                                }}>
                                                    <div>
                                                        <span style={{
                                                            display: 'inline-block', padding: '0.1rem 0.35rem', borderRadius: '4px',
                                                            background: 'var(--primary-light, rgba(59,130,246,0.1))', color: 'var(--primary)',
                                                            fontSize: '0.72rem', fontWeight: 600, marginRight: '0.35rem',
                                                        }}>
                                                            v{v.version}
                                                        </span>
                                                        <span style={{ color: 'var(--text-secondary)' }}>{v.change_type}</span>
                                                        {v.change_summary && (
                                                            <span style={{ marginLeft: '0.35rem', color: 'var(--text-secondary)' }}>- {v.change_summary}</span>
                                                        )}
                                                    </div>
                                                    <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
                                                        <span style={{ fontSize: '0.72rem', color: 'var(--text-secondary)' }}>{v.total_cases} cases</span>
                                                        <span style={{ fontSize: '0.72rem', color: 'var(--text-secondary)' }}>{new Date(v.created_at).toLocaleDateString()}</span>
                                                    </div>
                                                </div>
                                            ))}
                                        </div>
                                    )}
                                </div>
                            )}
                        </div>

                        {/* Cases Table */}
                        {casesLoading ? (
                            <div style={{ color: 'var(--text-secondary)' }}>Loading cases...</div>
                        ) : (
                            <div style={{ overflowX: 'auto' }}>
                                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.85rem' }}>
                                    <thead>
                                        <tr>
                                            <th style={{ ...thStyle, width: '30px' }}>
                                                <input type="checkbox" checked={cases.length > 0 && selectedCaseIds.size === cases.length} onChange={toggleAllCases} />
                                            </th>
                                            <th style={{ ...thStyle, width: '40px' }}>#</th>
                                            <th style={thStyle}>Input Prompt</th>
                                            <th style={thStyle}>Expected Output</th>
                                            <th style={{ ...thStyle, width: '120px' }}>Assertions</th>
                                            <th style={{ ...thStyle, width: '80px' }}>Actions</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {cases.map(c => (
                                            <tr key={c.id}>
                                                {expandedCaseId === c.id ? (
                                                    <td colSpan={6} style={{ ...tdStyle, padding: '0.75rem' }}>
                                                        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                                                            <label style={{ fontSize: '0.8rem', fontWeight: 500 }}>Input Prompt</label>
                                                            <textarea value={caseForm.input_prompt} onChange={e => setCaseForm({ ...caseForm, input_prompt: e.target.value })}
                                                                style={{ ...inputStyle, minHeight: '80px', resize: 'vertical' }} />
                                                            <label style={{ fontSize: '0.8rem', fontWeight: 500 }}>Expected Output</label>
                                                            <textarea value={caseForm.expected_output} onChange={e => setCaseForm({ ...caseForm, expected_output: e.target.value })}
                                                                style={{ ...inputStyle, minHeight: '60px', resize: 'vertical' }} />
                                                            <label style={{ fontSize: '0.8rem', fontWeight: 500 }}>Assertions (semicolon-separated, e.g. contains:hello; not-contains:error)</label>
                                                            <input value={caseForm.assertions} onChange={e => setCaseForm({ ...caseForm, assertions: e.target.value })} style={inputStyle} />
                                                            <label style={{ fontSize: '0.8rem', fontWeight: 500 }}>Tags (comma-separated)</label>
                                                            <input value={caseForm.tags} onChange={e => setCaseForm({ ...caseForm, tags: e.target.value })} style={inputStyle} />
                                                            <div style={{ display: 'flex', gap: '0.5rem' }}>
                                                                <button onClick={() => updateCase(c.id)} style={{ ...btnPrimary, fontSize: '0.8rem', padding: '0.3rem 0.6rem' }}>Save</button>
                                                                <button onClick={() => setExpandedCaseId(null)} style={{ ...btnSecondary, fontSize: '0.8rem', padding: '0.3rem 0.6rem' }}>Cancel</button>
                                                            </div>
                                                        </div>
                                                    </td>
                                                ) : (
                                                    <>
                                                        <td style={tdStyle}>
                                                            <input type="checkbox" checked={selectedCaseIds.has(c.id)} onChange={() => toggleCaseSelect(c.id)} />
                                                        </td>
                                                        <td style={tdStyle}>{c.case_index + 1}</td>
                                                        <td style={{ ...tdStyle, maxWidth: '300px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', cursor: 'pointer' }}
                                                            onClick={() => expandCase(c)} title={c.input_prompt}>
                                                            {c.input_prompt.length > 80 ? c.input_prompt.substring(0, 80) + '...' : c.input_prompt}
                                                        </td>
                                                        <td style={{ ...tdStyle, maxWidth: '200px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                                                            title={c.expected_output}>
                                                            {c.expected_output.length > 60 ? c.expected_output.substring(0, 60) + '...' : c.expected_output || '-'}
                                                        </td>
                                                        <td style={tdStyle}>
                                                            {c.assertions.length > 0 ? (
                                                                <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
                                                                    {c.assertions.length} rule{c.assertions.length !== 1 ? 's' : ''}
                                                                </span>
                                                            ) : '-'}
                                                        </td>
                                                        <td style={tdStyle}>
                                                            <div style={{ display: 'flex', gap: '0.25rem' }}>
                                                                <button onClick={() => expandCase(c)} style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--primary)', fontSize: '0.8rem' }}>edit</button>
                                                                <button onClick={() => deleteCase(c.id)} style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--danger)', fontSize: '0.8rem' }}>del</button>
                                                            </div>
                                                        </td>
                                                    </>
                                                )}
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                                {cases.length === 0 && (
                                    <div style={{ padding: '2rem', textAlign: 'center', color: 'var(--text-secondary)', fontSize: '0.85rem' }}>
                                        No cases yet. Add one below.
                                    </div>
                                )}
                            </div>
                        )}

                        {/* Add Case */}
                        {showAddCase ? (
                            <div style={{ ...cardStyleCompact, marginTop: '0.75rem' }}>
                                <div style={{ fontSize: '0.85rem', fontWeight: 600, marginBottom: '0.5rem' }}>Add New Case</div>
                                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                                    <textarea placeholder="Input prompt..." value={newCase.input_prompt} onChange={e => setNewCase({ ...newCase, input_prompt: e.target.value })}
                                        style={{ ...inputStyle, minHeight: '70px', resize: 'vertical' }} />
                                    <textarea placeholder="Expected output (optional)..." value={newCase.expected_output} onChange={e => setNewCase({ ...newCase, expected_output: e.target.value })}
                                        style={{ ...inputStyle, minHeight: '50px', resize: 'vertical' }} />
                                    <input placeholder="Assertions (e.g. contains:hello; not-contains:error)" value={newCase.assertions} onChange={e => setNewCase({ ...newCase, assertions: e.target.value })} style={inputStyle} />
                                    <input placeholder="Tags (comma-separated)" value={newCase.tags} onChange={e => setNewCase({ ...newCase, tags: e.target.value })} style={inputStyle} />
                                    <div style={{ display: 'flex', gap: '0.5rem' }}>
                                        <button onClick={addCase} style={{ ...btnPrimary, fontSize: '0.8rem', padding: '0.3rem 0.6rem' }}>Add Case</button>
                                        <button onClick={() => setShowAddCase(false)} style={{ ...btnSecondary, fontSize: '0.8rem', padding: '0.3rem 0.6rem' }}>Cancel</button>
                                    </div>
                                </div>
                            </div>
                        ) : (
                            <button onClick={() => setShowAddCase(true)} style={{ ...btnSecondary, fontSize: '0.8rem', padding: '0.35rem 0.75rem', marginTop: '0.75rem' }}>+ Add Case</button>
                        )}

                        {error && <div style={{ color: 'var(--danger)', marginTop: '0.5rem', fontSize: '0.8rem' }}>{error}</div>}
                    </div>
                )}
            </div>

            <ConfirmDialog
                open={confirmDelete.open}
                onOpenChange={(open) => setConfirmDelete(s => ({ ...s, open }))}
                title="Delete Dataset"
                description={`Delete "${confirmDelete.name}" and all its cases? This action cannot be undone.`}
                confirmLabel="Delete"
                variant="danger"
                onConfirm={() => deleteDataset(confirmDelete.id)}
            />

            <ConfirmDialog
                open={confirmBulkDelete}
                onOpenChange={setConfirmBulkDelete}
                title="Delete Selected Cases"
                description={`Delete ${selectedCaseIds.size} selected case${selectedCaseIds.size !== 1 ? 's' : ''}? This action cannot be undone.`}
                confirmLabel="Delete"
                variant="danger"
                onConfirm={bulkDelete}
            />
        </div>
    );
}
