'use client';
import { useState, useEffect } from 'react';
import { ArrowLeft, Save } from 'lucide-react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import TagEditor from '@/components/TagEditor';
import SpecBuilder from '@/components/SpecBuilder';
import { useProject } from '@/contexts/ProjectContext';
import { API_BASE } from '@/lib/api';
import { PageLayout } from '@/components/ui/page-layout';
import { PageHeader } from '@/components/ui/page-header';

export default function NewTemplatePage() {
    const router = useRouter();
    const { currentProject } = useProject();
    const [name, setName] = useState('');
    const [content, setContent] = useState('');
    const [tags, setTags] = useState<string[]>([]);
    const [allTags, setAllTags] = useState<string[]>([]);
    const [loading, setLoading] = useState(false);
    const [mode, setMode] = useState<'code' | 'visual'>('visual');

    // Default template for templates
    const template = `# Template: [Name]

## Purpose
[Describe what this template automates, e.g., "Login flow for MyApp"]

## Steps
1. Navigate to [URL]
2. [Action]
3. [Verification]

## Expected Outcome
- [Expected result after running this template]
`;

    useEffect(() => {
        setContent(template);
        fetch(`${API_BASE}/spec-metadata`)
            .then(res => res.json())
            .then(metadata => {
                const tagsSet = new Set<string>();
                Object.values(metadata).forEach((meta: any) => {
                    meta.tags?.forEach((tag: string) => tagsSet.add(tag));
                });
                setAllTags(Array.from(tagsSet).sort());
            })
            .catch(err => console.error('Failed to load tags:', err));
    }, []);

    const handleSave = async () => {
        if (!name || !content) {
            alert('Please fill in name and content');
            return;
        }

        // Auto-prefix with templates/ if not already
        let saveName = name;
        if (!saveName.startsWith('templates/')) {
            saveName = `templates/${saveName}`;
        }
        // Ensure .md extension
        if (!saveName.endsWith('.md')) {
            saveName = `${saveName}.md`;
        }

        setLoading(true);
        try {
            const res = await fetch(`${API_BASE}/specs`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name: saveName, content, project_id: currentProject?.id })
            });

            if (res.ok) {
                if (tags.length > 0) {
                    await fetch(`${API_BASE}/spec-metadata/${saveName}`, {
                        method: 'PUT',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ tags })
                    });
                }
                router.push('/templates');
            } else {
                alert('Failed to save template');
            }
        } catch (e) {
            console.error(e);
            alert('Error saving template');
        } finally {
            setLoading(false);
        }
    };

    return (
        <PageLayout tier="narrow">
            <PageHeader
                title="New Template"
                breadcrumb={
                    <Link href="/templates" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', color: 'var(--text-secondary)' }}>
                        <ArrowLeft size={16} /> Back to Templates
                    </Link>
                }
                actions={
                    <div style={{ display: 'flex', gap: '1rem', alignItems: 'center' }}>
                        <div style={{ background: 'var(--surface)', borderRadius: 'var(--radius)', padding: '4px', display: 'flex', border: '1px solid var(--border)' }}>
                            <button
                                onClick={() => setMode('code')}
                                style={{
                                    padding: '4px 12px',
                                    background: mode === 'code' ? 'var(--primary)' : 'transparent',
                                    color: mode === 'code' ? 'white' : 'var(--text-secondary)',
                                    borderRadius: '4px',
                                    border: 'none',
                                    fontSize: '0.8rem',
                                    cursor: 'pointer'
                                }}
                            >
                                Code
                            </button>
                            <button
                                onClick={() => setMode('visual')}
                                style={{
                                    padding: '4px 12px',
                                    background: mode === 'visual' ? 'var(--primary)' : 'transparent',
                                    color: mode === 'visual' ? 'white' : 'var(--text-secondary)',
                                    borderRadius: '4px',
                                    border: 'none',
                                    fontSize: '0.8rem',
                                    cursor: 'pointer'
                                }}
                            >
                                Visual
                            </button>
                        </div>
                        <button className="btn btn-primary" onClick={handleSave} disabled={loading}>
                            <Save size={18} />
                            {loading ? 'Saving...' : 'Save Template'}
                        </button>
                    </div>
                }
            />

            <div className="animate-in stagger-2" style={{ display: 'grid', gap: '2rem', maxWidth: '800px' }}>
                <div className="card">
                    <label style={{ display: 'block', marginBottom: '0.75rem', fontWeight: 600, fontSize: '0.95rem', color: 'var(--text)' }}>
                        Template Name (e.g. login-flow)
                    </label>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                        <span style={{ color: 'var(--text-secondary)', fontSize: '0.9rem', fontFamily: 'monospace' }}>templates/</span>
                        <input
                            type="text"
                            value={name}
                            onChange={e => setName(e.target.value)}
                            placeholder="my-template.md"
                            style={{
                                flex: 1, padding: '0.75rem',
                                background: 'rgba(0,0,0,0.2)',
                                border: '1px solid var(--border)',
                                borderRadius: 'var(--radius)',
                                color: 'white',
                                fontSize: '1rem',
                                transition: 'border-color 0.2s ease'
                            }}
                            onFocus={(e) => e.target.style.borderColor = 'var(--primary)'}
                            onBlur={(e) => e.target.style.borderColor = 'var(--border)'}
                        />
                    </div>
                </div>

                <div className="card">
                    <label style={{ display: 'block', marginBottom: '0.75rem', fontWeight: 600, fontSize: '0.95rem', color: 'var(--text)' }}>Tags</label>
                    <TagEditor
                        tags={tags}
                        onTagsChange={setTags}
                        allTags={allTags}
                        placeholder="Add tags (reusable, auth, setup...)"
                    />
                </div>

                <div className="card" style={{ height: 'calc(100vh - 450px)', display: 'flex', flexDirection: 'column', padding: 0, overflow: 'hidden' }}>
                    <div style={{ padding: '1rem', borderBottom: '1px solid var(--border)', fontWeight: 600, fontSize: '0.95rem', color: 'var(--text)' }}>
                        Content
                    </div>
                    <div style={{ flex: 1, overflow: 'auto', background: 'var(--code-bg)' }}>
                        {mode === 'visual' ? (
                            <SpecBuilder content={content} onChange={setContent} />
                        ) : (
                            <textarea
                                value={content}
                                onChange={e => setContent(e.target.value)}
                                style={{
                                    width: '100%', height: '100%', padding: '1rem',
                                    background: 'transparent',
                                    border: 'none',
                                    color: 'white',
                                    fontFamily: 'monospace',
                                    fontSize: '0.95rem',
                                    lineHeight: '1.6',
                                    resize: 'none',
                                    outline: 'none'
                                }}
                            />
                        )}
                    </div>
                </div>
            </div>
        </PageLayout>
    );
}
