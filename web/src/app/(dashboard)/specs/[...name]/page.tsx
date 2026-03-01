'use client';
import { useState, useEffect } from 'react';
import { ArrowLeft, Edit, Save, Play, Code, FileText, Eye, X } from 'lucide-react';
import Link from 'next/link';
import { useParams, useRouter } from 'next/navigation';
import SpecBuilder from '@/components/SpecBuilder';
import CodeEditor from '@/components/CodeEditor';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { vscDarkPlus } from 'react-syntax-highlighter/dist/esm/styles/prism';
import { useProject } from '@/contexts/ProjectContext';
import { API_BASE } from '@/lib/api';
import { PageLayout } from '@/components/ui/page-layout';
import { PageHeader } from '@/components/ui/page-header';

function extractDisplayTitle(fullPath: string): { title: string; folder: string } {
    const parts = fullPath.split('/');
    const filename = parts[parts.length - 1];
    const folder = parts.length > 1 ? parts.slice(0, -1).join(' / ') : '';
    const title = filename
        .replace(/\.md$/i, '')
        .replace(/-/g, ' ')
        .replace(/\b(tc)\b/gi, 'TC')
        .replace(/\b\w/g, c => c.toUpperCase());
    return { title, folder };
}

export default function SpecDetailPage() {
    const params = useParams();
    const router = useRouter();
    const { currentProject } = useProject();

    const nameParam = params?.name;
    const rawName = Array.isArray(nameParam) ? nameParam.join('/') : (nameParam as string);
    const decodedName = decodeURIComponent(rawName || '');
    const { title: displayTitle, folder } = extractDisplayTitle(decodedName);

    const projectParam = currentProject?.id ? `?project_id=${encodeURIComponent(currentProject.id)}` : '';

    const [content, setContent] = useState('');
    const [originalContent, setOriginalContent] = useState('');
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);
    const [isEditing, setIsEditing] = useState(false);
    const [mode, setMode] = useState<'code' | 'visual'>('code');

    const [activeTab, setActiveTab] = useState<'spec' | 'generated'>('spec');
    const [isAutomated, setIsAutomated] = useState(false);
    const [codePath, setCodePath] = useState<string | null>(null);
    const [generatedCode, setGeneratedCode] = useState<string | null>(null);
    const [originalGeneratedCode, setOriginalGeneratedCode] = useState<string | null>(null);
    const [loadingCode, setLoadingCode] = useState(false);
    const [savingCode, setSavingCode] = useState(false);
    const [isEditingCode, setIsEditingCode] = useState(false);
    const [isRunning, setIsRunning] = useState(false);

    useEffect(() => {
        if (!decodedName) return;
        fetch(`${API_BASE}/specs/${decodedName}${projectParam}`)
            .then(res => res.json())
            .then(data => {
                setContent(data.content);
                setOriginalContent(data.content);
                setIsAutomated(data.is_automated || false);
                setCodePath(data.code_path || null);
                setLoading(false);
            })
            .catch(err => {
                console.error(err);
                setLoading(false);
            });
    }, [decodedName, projectParam]);

    const loadGeneratedCode = async () => {
        if (generatedCode !== null) return;
        setLoadingCode(true);
        try {
            const res = await fetch(`${API_BASE}/specs/${decodedName}/generated-code${projectParam}`);
            if (res.ok) {
                const data = await res.json();
                setGeneratedCode(data.content);
                setOriginalGeneratedCode(data.content);
                setCodePath(data.code_path);
            }
        } catch (e) {
            console.error('Failed to load generated code');
        } finally {
            setLoadingCode(false);
        }
    };

    useEffect(() => {
        if (activeTab === 'generated' && isAutomated) {
            loadGeneratedCode();
        }
    }, [activeTab, isAutomated]);

    const handleSaveGeneratedCode = async () => {
        if (!generatedCode) return;
        setSavingCode(true);
        try {
            const res = await fetch(`${API_BASE}/specs/${decodedName}/generated-code${projectParam}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ content: generatedCode })
            });
            if (res.ok) {
                setOriginalGeneratedCode(generatedCode);
                setIsEditingCode(false);
            } else {
                alert('Failed to save generated code');
            }
        } catch (e) {
            alert('Failed to save');
        } finally {
            setSavingCode(false);
        }
    };

    const handleSave = async () => {
        setSaving(true);
        try {
            const res = await fetch(`${API_BASE}/specs/${decodedName}${projectParam}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ content })
            });

            if (res.ok) {
                setOriginalContent(content);
                setIsEditing(false);
                setMode('code');
            } else {
                alert('Failed to save');
            }
        } catch (e) {
            alert('Failed to save');
        } finally {
            setSaving(false);
        }
    };

    const runTest = async () => {
        if (isRunning) return;

        setIsRunning(true);
        try {
            const res = await fetch(`${API_BASE}/runs`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    spec_name: decodedName,
                    project_id: currentProject?.id
                })
            });
            const data = await res.json();
            if (data.id) {
                router.push('/runs');
            }
        } catch (e) {
            alert('Failed to start run');
            setIsRunning(false);
        }
    };

    if (loading) return (
        <PageLayout tier="standard">
            <div style={{ display: 'flex', justifyContent: 'center', padding: '4rem' }}>
                <div className="loading-spinner" style={{ width: 40, height: 40 }}></div>
            </div>
        </PageLayout>
    );

    const hasChanges = content !== originalContent;

    return (
        <PageLayout tier="standard">
            <PageHeader
                title={displayTitle}
                subtitle={folder || 'Test specification'}
                icon={<FileText size={20} />}
                breadcrumb={
                    <Link href="/specs" className="link-hover" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', color: 'var(--text-secondary)' }}>
                        <ArrowLeft size={16} /> Back to Specs
                    </Link>
                }
                actions={
                    <button
                        className="btn btn-primary"
                        onClick={runTest}
                        disabled={isRunning}
                        style={{ opacity: isRunning ? 0.7 : 1, cursor: isRunning ? 'not-allowed' : 'pointer' }}
                    >
                        {isRunning ? (
                            <>
                                <span className="loading-spinner" style={{ width: '18px', height: '18px' }}></span>
                                Starting...
                            </>
                        ) : (
                            <>
                                <Play size={18} /> Run Test
                            </>
                        )}
                    </button>
                }
            />

            {/* Toolbar row */}
            <div
                className="card-elevated animate-in stagger-2"
                style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    height: '3rem',
                    padding: '0 1rem',
                    marginBottom: '1rem',
                }}
            >
                {/* Left: toggles */}
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                    {activeTab === 'spec' && (
                        <div style={{ background: 'var(--surface)', borderRadius: 'var(--radius)', padding: '3px', display: 'flex', border: '1px solid var(--border)' }}>
                            <button
                                onClick={() => setMode('code')}
                                style={{
                                    padding: '3px 10px',
                                    background: mode === 'code' ? 'var(--primary)' : 'transparent',
                                    color: mode === 'code' ? 'white' : 'var(--text-secondary)',
                                    borderRadius: '4px',
                                    border: 'none',
                                    fontSize: '0.8rem',
                                    cursor: 'pointer',
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: '0.375rem',
                                }}
                            >
                                <Code size={13} />
                                Code
                            </button>
                            <button
                                onClick={() => { setMode('visual'); setIsEditing(true); }}
                                style={{
                                    padding: '3px 10px',
                                    background: mode === 'visual' ? 'var(--primary)' : 'transparent',
                                    color: mode === 'visual' ? 'white' : 'var(--text-secondary)',
                                    borderRadius: '4px',
                                    border: 'none',
                                    fontSize: '0.8rem',
                                    cursor: 'pointer',
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: '0.375rem',
                                }}
                            >
                                <Eye size={13} />
                                Visual
                            </button>
                        </div>
                    )}

                    {isAutomated && (
                        <div style={{ background: 'var(--surface)', borderRadius: 'var(--radius)', padding: '3px', display: 'flex', border: '1px solid var(--border)' }}>
                            <button
                                onClick={() => setActiveTab('spec')}
                                style={{
                                    padding: '3px 10px',
                                    background: activeTab === 'spec' ? 'var(--primary)' : 'transparent',
                                    color: activeTab === 'spec' ? 'white' : 'var(--text-secondary)',
                                    borderRadius: '4px',
                                    border: 'none',
                                    fontSize: '0.8rem',
                                    cursor: 'pointer',
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: '0.375rem',
                                }}
                            >
                                <FileText size={13} />
                                Spec
                            </button>
                            <button
                                onClick={() => setActiveTab('generated')}
                                style={{
                                    padding: '3px 10px',
                                    background: activeTab === 'generated' ? 'var(--success)' : 'transparent',
                                    color: activeTab === 'generated' ? 'white' : 'var(--text-secondary)',
                                    borderRadius: '4px',
                                    border: 'none',
                                    fontSize: '0.8rem',
                                    cursor: 'pointer',
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: '0.375rem',
                                }}
                            >
                                <Code size={13} />
                                Generated Test
                            </button>
                        </div>
                    )}
                </div>

                {/* Right: edit/save controls */}
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                    {activeTab === 'spec' && mode === 'code' && (
                        <button
                            className="btn btn-secondary btn-sm"
                            onClick={() => {
                                if (isEditing) {
                                    setContent(originalContent);
                                    setIsEditing(false);
                                } else {
                                    setIsEditing(true);
                                }
                            }}
                        >
                            {isEditing ? <><X size={14} /> Cancel</> : <><Edit size={14} /> Edit</>}
                        </button>
                    )}
                    {activeTab === 'spec' && (isEditing || hasChanges) && (
                        <button className="btn btn-primary btn-sm" onClick={handleSave} disabled={saving}>
                            {saving ? 'Saving...' : <><Save size={14} /> Save</>}
                        </button>
                    )}
                </div>
            </div>

            {/* Content area */}
            <div className="animate-in stagger-3" style={{ display: 'flex', flexDirection: 'column', flex: 1, minHeight: '500px' }}>
                {activeTab === 'spec' ? (
                    <div className="card-elevated" style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column', padding: 0 }}>
                        <div style={{ flex: 1, overflow: 'hidden', position: 'relative', background: 'var(--code-bg)', borderRadius: 'var(--radius)' }}>
                            {mode === 'visual' ? (
                                <div style={{ position: 'absolute', inset: 0, overflow: 'auto' }}>
                                    <SpecBuilder content={content} onChange={setContent} />
                                </div>
                            ) : (
                                isEditing ? (
                                    <div style={{ position: 'absolute', inset: 0 }}>
                                        <CodeEditor
                                            value={content}
                                            onChange={setContent}
                                            language="markdown"
                                        />
                                    </div>
                                ) : (
                                    <div style={{ position: 'absolute', inset: 0, overflow: 'auto' }}>
                                        <SyntaxHighlighter
                                            language="markdown"
                                            style={vscDarkPlus}
                                            customStyle={{ margin: 0, padding: '1.5rem', fontSize: '0.9rem', background: 'var(--code-bg)', minHeight: '100%' }}
                                            showLineNumbers={true}
                                            wrapLines={true}
                                        >
                                            {content || ''}
                                        </SyntaxHighlighter>
                                    </div>
                                )
                            )}
                        </div>
                    </div>
                ) : (
                    <div className="card-elevated" style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column', padding: 0 }}>
                        {loadingCode ? (
                            <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-secondary)' }}>
                                <div style={{ textAlign: 'center' }}>
                                    <div className="loading-spinner" style={{ width: '32px', height: '32px', margin: '0 auto 1rem' }}></div>
                                    <p>Loading generated test code...</p>
                                </div>
                            </div>
                        ) : generatedCode ? (
                            <>
                                <div style={{
                                    display: 'flex',
                                    justifyContent: 'space-between',
                                    alignItems: 'center',
                                    padding: '0.75rem 1rem',
                                    borderBottom: '1px solid var(--border)',
                                    background: 'var(--surface)',
                                }}>
                                    <code style={{ color: 'var(--text-secondary)', fontSize: '0.8rem' }}>{codePath}</code>
                                    <div style={{ display: 'flex', gap: '0.5rem' }}>
                                        {isEditingCode ? (
                                            <>
                                                <button
                                                    className="btn btn-secondary btn-sm"
                                                    onClick={() => {
                                                        setGeneratedCode(originalGeneratedCode);
                                                        setIsEditingCode(false);
                                                    }}
                                                >
                                                    Cancel
                                                </button>
                                                <button
                                                    className="btn btn-primary btn-sm"
                                                    onClick={handleSaveGeneratedCode}
                                                    disabled={savingCode}
                                                >
                                                    {savingCode ? 'Saving...' : <><Save size={14} /> Save</>}
                                                </button>
                                            </>
                                        ) : (
                                            <button
                                                className="btn btn-secondary btn-sm"
                                                onClick={() => setIsEditingCode(true)}
                                            >
                                                <Edit size={14} /> Edit
                                            </button>
                                        )}
                                    </div>
                                </div>
                                <div style={{ flex: 1, overflow: 'hidden', position: 'relative', background: 'var(--code-bg)' }}>
                                    {isEditingCode ? (
                                        <div style={{ position: 'absolute', inset: 0 }}>
                                            <CodeEditor
                                                value={generatedCode || ''}
                                                onChange={(val) => setGeneratedCode(val)}
                                                language="typescript"
                                            />
                                        </div>
                                    ) : (
                                        <div style={{ position: 'absolute', inset: 0, overflow: 'auto' }}>
                                            <SyntaxHighlighter
                                                language="typescript"
                                                style={vscDarkPlus}
                                                customStyle={{ margin: 0, padding: '1.5rem', fontSize: '0.85rem', background: 'var(--code-bg)', minHeight: '100%' }}
                                                showLineNumbers={true}
                                                wrapLines={true}
                                            >
                                                {generatedCode}
                                            </SyntaxHighlighter>
                                        </div>
                                    )}
                                </div>
                            </>
                        ) : (
                            <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-secondary)' }}>
                                <div style={{ textAlign: 'center' }}>
                                    <Code size={48} style={{ marginBottom: '1rem', opacity: 0.5 }} />
                                    <p>No generated test available</p>
                                    <p style={{ fontSize: '0.85rem', marginTop: '0.5rem' }}>Run this spec to generate a Playwright test.</p>
                                </div>
                            </div>
                        )}
                    </div>
                )}
            </div>
        </PageLayout>
    );
}
