'use client';
import { useState, useEffect, useCallback } from 'react';
import { API_BASE } from '@/lib/api';
import { cardStyleCompact, inputStyle, btnPrimary } from '@/lib/styles';
import { usePolling } from '@/hooks/usePolling';
import { toast } from 'sonner';
import { ConfirmDialog } from '@/components/ui/confirm-dialog';
import { EmptyState } from '@/components/ui/empty-state';
import { ScrollArea } from '@/components/ui/scroll-area';
import { DropdownMenu, DropdownMenuTrigger, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator } from '@/components/ui/dropdown-menu';
import { Progress } from '@/components/ui/progress';
import CodeEditor from '@/components/CodeEditor';
import { MousePointerClick, MoreVertical, Copy, Trash2, Save, Search } from 'lucide-react';
import type { Spec } from './types';
import VisualSpecBuilder from './VisualSpecBuilder';
import TemplateGallery from './TemplateGallery';

function timeAgo(dateStr: string | number): string {
    const now = Date.now();
    const date = typeof dateStr === 'number' ? dateStr : new Date(dateStr).getTime();
    const diff = now - date;
    const mins = Math.floor(diff / 60000);
    if (mins < 1) return 'just now';
    if (mins < 60) return `${mins}m ago`;
    const hrs = Math.floor(mins / 60);
    if (hrs < 24) return `${hrs}h ago`;
    const days = Math.floor(hrs / 24);
    if (days < 30) return `${days}d ago`;
    return `${Math.floor(days / 30)}mo ago`;
}

function formatBytes(bytes: number): string {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

interface SpecsTabProps {
    projectId: string;
}

export default function SpecsTab({ projectId }: SpecsTabProps) {
    const [specs, setSpecs] = useState<Spec[]>([]);
    const [loading, setLoading] = useState(true);
    const [editing, setEditing] = useState<string | null>(null);
    const [content, setContent] = useState('');
    const [savedContent, setSavedContent] = useState('');
    const [showCreate, setShowCreate] = useState(false);
    const [newName, setNewName] = useState('');
    const [generating, setGenerating] = useState(false);
    const [genForm, setGenForm] = useState({ system_prompt: '', app_description: '', num_cases: '10' });
    const [showGenerate, setShowGenerate] = useState(false);
    const [editorMode, setEditorMode] = useState<'markdown' | 'visual' | 'templates'>('markdown');
    const [searchQuery, setSearchQuery] = useState('');
    const [confirmState, setConfirmState] = useState<{ open: boolean; specName: string }>({ open: false, specName: '' });

    // Job polling state for AI generation
    const [genJobId, setGenJobId] = useState<string | null>(null);

    const fetchSpecs = useCallback(async () => {
        try {
            const res = await fetch(`${API_BASE}/llm-testing/specs?project_id=${projectId}`);
            if (res.ok) setSpecs(await res.json());
        } catch {
            toast.error('Failed to load specs');
        }
        setLoading(false);
    }, [projectId]);

    useEffect(() => { fetchSpecs(); }, [fetchSpecs]);

    const loadSpec = useCallback(async (name: string) => {
        try {
            const res = await fetch(`${API_BASE}/llm-testing/specs/${name}?project_id=${projectId}`);
            if (res.ok) {
                const data = await res.json();
                setContent(data.content);
                setSavedContent(data.content);
                setEditing(name);
            }
        } catch {
            toast.error('Failed to load spec');
        }
    }, [projectId]);

    const saveSpec = useCallback(async () => {
        if (!editing) return;
        try {
            await fetch(`${API_BASE}/llm-testing/specs/${editing}?project_id=${projectId}`, {
                method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ content }),
            });
            setSavedContent(content);
            toast.success('Spec saved');
            fetchSpecs();
        } catch {
            toast.error('Failed to save spec');
        }
    }, [editing, content, projectId, fetchSpecs]);

    const createSpec = useCallback(async () => {
        if (!newName) return;
        try {
            await fetch(`${API_BASE}/llm-testing/specs`, {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name: newName, content: `# LLM Test Suite: ${newName}\n\n## Description\n\n## System Prompt\n\n## Test Cases\n\n### TC-001: Basic Test\n**Input:** Hello\n**Expected Output:** A greeting\n**Assertions:**\n- contains: hello\n`, project_id: projectId }),
            });
            setShowCreate(false); setNewName(''); fetchSpecs();
        } catch {
            toast.error('Failed to create spec');
        }
    }, [newName, projectId, fetchSpecs]);

    const deleteSpec = useCallback(async (name: string) => {
        try {
            await fetch(`${API_BASE}/llm-testing/specs/${name}?project_id=${projectId}`, { method: 'DELETE' });
            if (editing === name) { setEditing(null); setContent(''); setSavedContent(''); }
            toast.success(`Spec "${name}" deleted`);
            fetchSpecs();
        } catch {
            toast.error('Failed to delete spec');
        }
    }, [projectId, editing, fetchSpecs]);

    // Poll for AI generation job completion
    const genPollFn = useCallback(async () => {
        if (!genJobId) return;
        const jr = await fetch(`${API_BASE}/llm-testing/jobs/${genJobId}`);
        if (jr.ok) {
            const job = await jr.json();
            if (job.status === 'completed') {
                setGenJobId(null);
                setShowGenerate(false);
                setGenerating(false);
                fetchSpecs();
                toast.success('Test suite generated successfully');
                if (job.result?.spec_name) loadSpec(job.result.spec_name);
            } else if (job.status === 'failed') {
                setGenJobId(null);
                setGenerating(false);
                toast.error(`Generation failed: ${job.error}`);
            }
        }
    }, [genJobId, fetchSpecs, loadSpec]);

    const { stop: stopGenPoll } = usePolling(genPollFn, {
        interval: 2000,
        enabled: !!genJobId,
    });

    // Stop polling when genJobId is cleared
    useEffect(() => {
        if (!genJobId) stopGenPoll();
    }, [genJobId, stopGenPoll]);

    const generateWithAI = useCallback(async () => {
        setGenerating(true);
        try {
            const res = await fetch(`${API_BASE}/llm-testing/generate-suite`, {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ ...genForm, num_cases: parseInt(genForm.num_cases), project_id: projectId }),
            });
            if (res.ok) {
                const data = await res.json();
                setGenJobId(data.job_id);
                toast.success('Generation started');
            }
        } catch {
            toast.error('Failed to start generation');
            setGenerating(false);
        }
    }, [genForm, projectId]);

    const filteredSpecs = specs.filter(s => s.name.toLowerCase().includes(searchQuery.toLowerCase()));
    const hasUnsaved = editing && content !== savedContent;

    return (
        <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '1rem' }}>
                <h2 style={{ fontSize: '1.1rem', fontWeight: 600 }}>Test Specs</h2>
                <div style={{ display: 'flex', gap: '0.5rem' }}>
                    <button onClick={() => setShowGenerate(!showGenerate)} style={btnPrimary}>Generate with AI</button>
                    <button onClick={() => setShowCreate(!showCreate)} style={btnPrimary}>+ New Spec</button>
                </div>
            </div>

            {showGenerate && (
                <div style={cardStyleCompact}>
                    <h3 style={{ fontWeight: 600, marginBottom: '0.5rem' }}>AI Test Suite Generator</h3>
                    <label style={{ fontSize: '0.8rem', fontWeight: 500, color: 'var(--text-secondary)', display: 'block', marginBottom: '0.2rem' }}>System Prompt</label>
                    <textarea placeholder="System prompt to test..." value={genForm.system_prompt} onChange={e => setGenForm({ ...genForm, system_prompt: e.target.value })} style={{ ...inputStyle, height: 80, fontFamily: 'monospace' }} />
                    <label style={{ fontSize: '0.8rem', fontWeight: 500, color: 'var(--text-secondary)', display: 'block', marginBottom: '0.2rem', marginTop: '0.5rem' }}>App Description</label>
                    <textarea placeholder="App description (optional)" value={genForm.app_description} onChange={e => setGenForm({ ...genForm, app_description: e.target.value })} style={{ ...inputStyle, height: 50 }} />
                    <label style={{ fontSize: '0.8rem', fontWeight: 500, color: 'var(--text-secondary)', display: 'block', marginBottom: '0.2rem', marginTop: '0.5rem' }}>Number of Test Cases</label>
                    <input placeholder="Number of test cases" value={genForm.num_cases} onChange={e => setGenForm({ ...genForm, num_cases: e.target.value })} style={{ ...inputStyle, width: 200 }} />
                    {generating && (
                        <div style={{ marginTop: '0.75rem' }}>
                            <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '0.35rem' }}>Generating test suite...</div>
                            <Progress value={undefined} className="animate-pulse" style={{ height: 6 }} />
                        </div>
                    )}
                    <button onClick={generateWithAI} disabled={!genForm.system_prompt || generating} style={{ ...btnPrimary, marginTop: '0.5rem' }}>
                        {generating ? 'Generating...' : 'Generate'}
                    </button>
                </div>
            )}

            {showCreate && (
                <div style={{ ...cardStyleCompact, display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
                    <input placeholder="Spec name" value={newName} onChange={e => setNewName(e.target.value)} style={inputStyle} />
                    <button onClick={createSpec} style={btnPrimary} disabled={!newName}>Create</button>
                </div>
            )}

            <div style={{ display: 'flex', gap: '1rem' }}>
                {/* Sidebar */}
                <div style={{ width: 300, flexShrink: 0 }}>
                    {/* Search */}
                    <div style={{ position: 'relative', marginBottom: '0.75rem' }}>
                        <Search size={14} style={{ position: 'absolute', left: 10, top: '50%', transform: 'translateY(-50%)', color: 'var(--text-secondary)' }} />
                        <input
                            placeholder="Search specs..."
                            value={searchQuery}
                            onChange={e => setSearchQuery(e.target.value)}
                            style={{ ...inputStyle, paddingLeft: 32, width: '100%' }}
                        />
                    </div>

                    <ScrollArea style={{ maxHeight: 'calc(100vh - 340px)' }}>
                        {loading ? (
                            <p style={{ color: 'var(--text-secondary)', padding: '0.5rem' }}>Loading...</p>
                        ) : filteredSpecs.length === 0 ? (
                            <p style={{ color: 'var(--text-secondary)', fontSize: '0.85rem', padding: '0.5rem' }}>
                                {specs.length === 0 ? 'No specs yet' : 'No matching specs'}
                            </p>
                        ) : filteredSpecs.map(s => (
                            <div
                                key={s.name}
                                onClick={() => loadSpec(s.name)}
                                style={{
                                    padding: '0.6rem 0.75rem',
                                    cursor: 'pointer',
                                    borderRadius: 'var(--radius)',
                                    marginBottom: '0.25rem',
                                    borderLeft: editing === s.name ? '3px solid var(--primary)' : '3px solid transparent',
                                    background: editing === s.name ? 'rgba(59,130,246,0.08)' : 'transparent',
                                    transition: 'all 0.15s var(--ease-smooth)',
                                }}
                            >
                                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                                    <span style={{
                                        fontSize: '0.9rem',
                                        fontWeight: editing === s.name ? 600 : 400,
                                        overflow: 'hidden',
                                        textOverflow: 'ellipsis',
                                        whiteSpace: 'nowrap',
                                        flex: 1,
                                    }}>
                                        {s.name}
                                    </span>
                                    <DropdownMenu>
                                        <DropdownMenuTrigger asChild>
                                            <button
                                                onClick={e => e.stopPropagation()}
                                                style={{
                                                    background: 'none',
                                                    border: 'none',
                                                    cursor: 'pointer',
                                                    color: 'var(--text-secondary)',
                                                    padding: '0.15rem',
                                                    borderRadius: 'var(--radius-sm)',
                                                    display: 'flex',
                                                    alignItems: 'center',
                                                }}
                                            >
                                                <MoreVertical size={14} />
                                            </button>
                                        </DropdownMenuTrigger>
                                        <DropdownMenuContent align="end">
                                            <DropdownMenuItem onClick={() => {
                                                navigator.clipboard.writeText(s.name);
                                                toast.success('Spec name copied');
                                            }}>
                                                <Copy size={14} />
                                                Duplicate
                                            </DropdownMenuItem>
                                            <DropdownMenuSeparator />
                                            <DropdownMenuItem
                                                onClick={() => setConfirmState({ open: true, specName: s.name })}
                                                style={{ color: 'var(--danger)' }}
                                            >
                                                <Trash2 size={14} />
                                                Delete
                                            </DropdownMenuItem>
                                        </DropdownMenuContent>
                                    </DropdownMenu>
                                </div>
                                <div style={{ display: 'flex', gap: '0.5rem', marginTop: '0.25rem', alignItems: 'center' }}>
                                    {s.size > 0 && (
                                        <span style={{
                                            fontSize: '0.7rem',
                                            background: 'var(--surface)',
                                            border: '1px solid var(--border)',
                                            borderRadius: '4px',
                                            padding: '0.05rem 0.35rem',
                                            color: 'var(--text-secondary)',
                                        }}>
                                            {formatBytes(s.size)}
                                        </span>
                                    )}
                                    {s.modified > 0 && (
                                        <span style={{ fontSize: '0.7rem', color: 'var(--text-secondary)' }}>
                                            {timeAgo(s.modified * 1000)}
                                        </span>
                                    )}
                                </div>
                            </div>
                        ))}
                    </ScrollArea>
                </div>

                {/* Editor Panel */}
                {editing ? (
                    <div style={{ flex: 1 }} onKeyDown={e => {
                        if ((e.metaKey || e.ctrlKey) && e.key === 's') {
                            e.preventDefault();
                            saveSpec();
                        }
                    }}>
                        <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '0.75rem', alignItems: 'center' }}>
                            {(['markdown', 'visual', 'templates'] as const).map(m => (
                                <button key={m} onClick={() => setEditorMode(m)} style={{
                                    padding: '0.4rem 1rem',
                                    borderRadius: 'var(--radius)',
                                    border: '1px solid var(--border)',
                                    background: editorMode === m ? 'var(--primary)' : 'var(--surface)',
                                    color: editorMode === m ? '#fff' : 'var(--text-secondary)',
                                    cursor: 'pointer', fontSize: '0.85rem', fontWeight: 500, textTransform: 'capitalize',
                                }}>
                                    {m === 'markdown' ? 'Markdown' : m === 'visual' ? 'Visual Builder' : 'Templates'}
                                </button>
                            ))}
                            {hasUnsaved && (
                                <span style={{
                                    width: 8,
                                    height: 8,
                                    borderRadius: '50%',
                                    background: 'var(--warning, #f59e0b)',
                                    display: 'inline-block',
                                    marginLeft: '0.25rem',
                                }} title="Unsaved changes" />
                            )}
                        </div>
                        {editorMode === 'markdown' && (
                            <div style={{ height: 500, border: '1px solid var(--border)', borderRadius: 'var(--radius)', overflow: 'hidden' }}>
                                <CodeEditor value={content} onChange={setContent} language="markdown" />
                            </div>
                        )}
                        {editorMode === 'visual' && (
                            <VisualSpecBuilder content={content} onChange={setContent} />
                        )}
                        {editorMode === 'templates' && (
                            <TemplateGallery onSelect={(md) => { setContent(md); setEditorMode('markdown'); }} />
                        )}
                        <button onClick={saveSpec} style={{ ...btnPrimary, marginTop: '0.5rem', display: 'inline-flex', alignItems: 'center', gap: '0.4rem' }}>
                            <Save size={14} />
                            Save
                        </button>
                    </div>
                ) : (
                    <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                        <EmptyState
                            icon={<MousePointerClick size={48} />}
                            title="Select a spec to start editing"
                            description="Choose a spec from the sidebar, or create a new one"
                            action={<button onClick={() => setShowCreate(true)} style={btnPrimary}>Create New Spec</button>}
                        />
                    </div>
                )}
            </div>

            <ConfirmDialog
                open={confirmState.open}
                onOpenChange={(open) => setConfirmState(s => ({ ...s, open }))}
                title="Delete Spec"
                description={`Are you sure you want to delete "${confirmState.specName}"? This action cannot be undone.`}
                confirmLabel="Delete"
                variant="danger"
                onConfirm={() => deleteSpec(confirmState.specName)}
            />
        </div>
    );
}
