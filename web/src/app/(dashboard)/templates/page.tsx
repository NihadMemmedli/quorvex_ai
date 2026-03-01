'use client';
import { useState, useEffect, useMemo } from 'react';
import { FileText, Plus, Play, Folder, FolderOpen, ChevronRight, ChevronDown, Search, FolderClosed, Tag, X, Edit, Check, Zap, AlertCircle } from 'lucide-react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import TagEditor from '@/components/TagEditor';
import { useProject } from '@/contexts/ProjectContext';
import { API_BASE } from '@/lib/api';
import { PageLayout } from '@/components/ui/page-layout';
import { PageHeader } from '@/components/ui/page-header';
import { EmptyState } from '@/components/ui/empty-state';
import { ListPageSkeleton } from '@/components/ui/page-skeleton';

interface Spec {
    name: string;
    path: string;
    content?: string;  // Optional - not needed for list view
    is_automated?: boolean;
    code_path?: string;
    metadata?: {
        tags: string[];
        description?: string;
        author?: string;
        lastModified?: string;
    };
}

interface TreeNode {
    name: string;
    path: string;
    type: 'file' | 'folder';
    children?: Record<string, TreeNode>;
    spec?: Spec;
}

export default function TemplatesPage() {
    const router = useRouter();
    const { currentProject, isLoading: projectLoading } = useProject();
    const [specs, setSpecs] = useState<Spec[]>([]);
    const [metadata, setMetadata] = useState<Record<string, any>>({});
    const [loading, setLoading] = useState(true);
    const [searchTerm, setSearchTerm] = useState('');
    const [selectedTags, setSelectedTags] = useState<string[]>([]);
    const [expandedFolders, setExpandedFolders] = useState<Set<string>>(new Set());

    useEffect(() => {
        // Wait for project context to finish loading
        if (projectLoading) return;

        setLoading(true);
        const projectParam = currentProject?.id ? `?project_id=${encodeURIComponent(currentProject.id)}` : '';

        Promise.all([
            fetch(`${API_BASE}/specs/list${projectParam}`).then(res => res.json()),
            fetch(`${API_BASE}/spec-metadata${projectParam}`).then(res => res.json())
        ])
            .then(([specsData, metadataData]) => {
                // Filter for templates only (in specs/templates/) — handle paginated response
                const specsList = specsData.items || specsData;
                const templateSpecs = specsList.filter((s: Spec) => s.name.startsWith('templates/'));

                // Merge metadata into specs
                const specsWithMetadata = templateSpecs.map((spec: Spec) => ({
                    ...spec,
                    metadata: metadataData[spec.name] || { tags: [] }
                }));
                setSpecs(specsWithMetadata);
                setMetadata(metadataData);
                setLoading(false);
                const topLevelFolders = new Set<string>();
                templateSpecs.forEach((s: Spec) => {
                    const parts = s.name.split('/');
                    if (parts.length > 1) topLevelFolders.add(parts[0]);
                });
                setExpandedFolders(topLevelFolders);
            })
            .catch(err => {
                console.error(err);
                setLoading(false);
            });
    }, [currentProject?.id, projectLoading]);

    const toggleFolder = (path: string) => {
        const next = new Set(expandedFolders);
        if (next.has(path)) next.delete(path);
        else next.add(path);
        setExpandedFolders(next);
    };

    const [runModalOpen, setRunModalOpen] = useState(false);
    const [selectedSpec, setSelectedSpec] = useState<string | null>(null);
    const [selectedBrowser, setSelectedBrowser] = useState('chromium');

    const openRunModal = (specName: string, e: React.MouseEvent) => {
        e.preventDefault();
        e.stopPropagation();
        setSelectedSpec(specName);
        setRunModalOpen(true);
    };

    const confirmRun = async () => {
        if (!selectedSpec) return;

        try {
            const res = await fetch(`${API_BASE}/runs`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    spec_name: selectedSpec,
                    browser: selectedBrowser,
                    project_id: currentProject?.id  // Project isolation
                })
            });
            const data = await res.json();
            if (data.status === 'started' || data.status === 'queued') {
                console.log('Run started');
                setRunModalOpen(false);
                setSelectedSpec(null);
                // Redirect to runs to see progress, which will update is_automated eventually
                router.push('/runs');
            }
        } catch (e) {
            console.error('Failed to start run');
        }
    };

    const tree = useMemo(() => {
        const root: Record<string, TreeNode> = {};

        specs
            .filter(s => s.name.toLowerCase().includes(searchTerm.toLowerCase()))
            .filter(s => selectedTags.length === 0 || selectedTags.some(tag => s.metadata?.tags?.includes(tag)))
            .forEach(spec => {
                // Remove 'templates/' prefix for display if we want, but keeping hierarchy is likely better for now
                // Actually, if everything is in 'templates/', top level folder is redundant. 
                // Let's strip 'templates/' from the path parts for cleaner display?
                // Or just show it. Let's show relative to 'specs/templates'.

                const relativeName = spec.name.startsWith('templates/') ? spec.name.substring(10) : spec.name;
                const parts = relativeName.split('/').filter(p => p); // filter empty

                let currentLevel = root;
                // If it's just 'templates/login.md', relativeName is 'login.md', parts=['login.md']

                parts.forEach((part, index) => {
                    const isFile = index === parts.length - 1;
                    const path = parts.slice(0, index + 1).join('/');

                    if (!currentLevel[part]) {
                        currentLevel[part] = {
                            name: part,
                            path: path,
                            type: isFile ? 'file' : 'folder',
                            children: isFile ? undefined : {},
                            spec: isFile ? spec : undefined
                        };
                    }

                    if (!isFile && currentLevel[part].children) {
                        currentLevel = currentLevel[part].children!;
                    }
                });
            });

        return root;
    }, [specs, searchTerm, selectedTags]);

    const renderNode = (node: TreeNode, depth: number = 0) => {
        const isExpanded = expandedFolders.has(node.path) || searchTerm.length > 0;

        if (node.type === 'file') {
            const isAutomated = node.spec?.is_automated;
            return (
                <div key={node.path} style={{ display: 'flex', alignItems: 'center', borderBottom: '1px solid var(--border)' }}>
                    <div style={{ padding: '0 0.5rem 0 1rem', display: 'flex', alignItems: 'center' }}>
                        <div style={{ width: 18 }}></div>
                    </div>
                    <Link
                        href={`/specs/${node.spec?.name}`}
                        className="list-item"
                        style={{
                            flex: 1,
                            padding: '0.875rem 1rem',
                            paddingLeft: '0.5rem',
                            marginBottom: 0,
                            borderRadius: 0,
                            border: 'none',
                            background: 'transparent'
                        }}
                    >
                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flex: 1 }}>
                            <div style={{
                                width: 32, height: 32,
                                background: 'var(--primary-glow)',
                                borderRadius: 6,
                                display: 'flex', alignItems: 'center', justifyContent: 'center',
                                color: 'var(--primary)'
                            }}>
                                <FileText size={16} />
                            </div>
                            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem', flex: 1 }}>
                                <span style={{ fontSize: '0.9rem', color: 'var(--text)' }}>{node.name}</span>
                                {node.spec?.metadata?.tags && node.spec.metadata.tags.length > 0 && (
                                    <div style={{ display: 'flex', gap: '0.375rem', flexWrap: 'wrap' }}>
                                        {node.spec.metadata.tags.map(tag => (
                                            <span
                                                key={tag}
                                                style={{
                                                    fontSize: '0.7rem',
                                                    padding: '0.125rem 0.5rem',
                                                    borderRadius: '9999px',
                                                    background: 'var(--primary-glow)',
                                                    color: 'var(--primary)',
                                                    fontWeight: 500
                                                }}
                                            >
                                                {tag}
                                            </span>
                                        ))}
                                    </div>
                                )}
                            </div>

                            {/* Automation Status Badge */}
                            <div style={{ marginRight: '1rem' }}>
                                {isAutomated ? (
                                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.25rem', padding: '0.25rem 0.5rem', background: 'var(--success-muted)', color: 'var(--success)', borderRadius: '4px', fontSize: '0.75rem', fontWeight: 600 }}>
                                        <Zap size={12} fill="currentColor" />
                                        <span>Automated</span>
                                    </div>
                                ) : (
                                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.25rem', padding: '0.25rem 0.5rem', background: 'var(--danger-muted)', color: 'var(--error)', borderRadius: '4px', fontSize: '0.75rem', fontWeight: 600 }}>
                                        <AlertCircle size={12} />
                                        <span>Draft</span>
                                    </div>
                                )}
                            </div>
                        </div>

                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                            <button
                                className="btn-icon"
                                title="Run to Automate"
                                onClick={(e) => node.spec && openRunModal(node.spec.name, e)}
                                style={{
                                    width: 32, height: 32,
                                    color: 'var(--success)',
                                    background: 'var(--success-muted)'
                                }}
                            >
                                <Play size={14} fill="currentColor" />
                            </button>
                            <ChevronRight size={18} color="var(--text-secondary)" />
                        </div>
                    </Link>
                </div>
            );
        }

        // Folder
        return (
            <div key={node.path}>
                <div
                    style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: '0.75rem',
                        padding: '0.75rem 1rem',
                        paddingLeft: `${depth * 1.5 + 0.5}rem`,
                        cursor: 'pointer',
                        userSelect: 'none',
                        color: 'var(--text)',
                        background: 'transparent',
                        fontSize: '0.85rem',
                        fontWeight: 700,
                        letterSpacing: '0.05em',
                        borderBottom: '1px solid var(--border)',
                        borderTop: depth === 0 && node.path !== Array.from(expandedFolders)[0] ? '1px solid var(--border)' : 'none'
                    }}
                    onClick={() => toggleFolder(node.path)}
                >
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', width: 20, height: 20 }}>
                        {expandedFolders.has(node.path) ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', color: expandedFolders.has(node.path) ? 'var(--text)' : 'inherit', flex: 1 }}>
                        {expandedFolders.has(node.path) ? <FolderOpen size={16} /> : <FolderClosed size={16} />}
                        <span style={{ textTransform: 'uppercase' }}>{node.name}</span>
                    </div>
                </div>
                {expandedFolders.has(node.path) && node.children && (
                    <div style={{ background: 'var(--surface)' }}>
                        {Object.values(node.children)
                            .sort((a, b) => {
                                if (a.type !== b.type) return a.type === 'folder' ? -1 : 1;
                                return a.name.localeCompare(b.name);
                            })
                            .map(child => renderNode(child, depth + 1))
                        }
                    </div>
                )}
            </div>
        );
    };

    // Skeleton loading component
    const SkeletonRow = ({ depth = 0 }: { depth?: number }) => (
        <div style={{
            display: 'flex',
            alignItems: 'center',
            padding: '0.875rem 1rem',
            paddingLeft: `${depth * 1.5 + 1}rem`,
            borderBottom: '1px solid var(--border)',
            gap: '0.75rem'
        }}>
            <div style={{ width: 18 }} />
            <div style={{
                width: 32,
                height: 32,
                borderRadius: 6,
                background: 'var(--surface-hover)',
                animation: 'pulse 1.5s ease-in-out infinite'
            }} />
            <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                <div style={{
                    height: 14,
                    width: `${Math.random() * 30 + 40}%`,
                    borderRadius: 4,
                    background: 'var(--surface-hover)',
                    animation: 'pulse 1.5s ease-in-out infinite'
                }} />
            </div>
            <div style={{
                width: 70,
                height: 24,
                borderRadius: 4,
                background: 'var(--surface-hover)',
                animation: 'pulse 1.5s ease-in-out infinite'
            }} />
            <div style={{
                width: 32,
                height: 32,
                borderRadius: 6,
                background: 'var(--surface-hover)',
                animation: 'pulse 1.5s ease-in-out infinite'
            }} />
        </div>
    );

    if (loading) return (
        <PageLayout tier="narrow">
            <ListPageSkeleton rows={6} />
        </PageLayout>
    );

    return (
        <PageLayout tier="narrow">
            <PageHeader
                title="Templates"
                subtitle="Manage reusable test templates."
                icon={<FileText size={20} />}
                actions={
                    <Link href="/templates/new" className="btn btn-primary" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', textDecoration: 'none', padding: '0.6rem 1.25rem' }}>
                        <Plus size={18} />
                        New Template
                    </Link>
                }
            />

            <div className="animate-in stagger-2" style={{ marginBottom: '1.5rem' }}>
                <div className="input-group">
                    <div className="input-icon">
                        <Search size={18} />
                    </div>
                    <input
                        type="text"
                        placeholder="Search templates..."
                        value={searchTerm}
                        onChange={(e) => setSearchTerm(e.target.value)}
                        className="input has-icon"
                        style={{ paddingTop: '0.875rem', paddingBottom: '0.875rem' }}
                    />
                </div>
            </div>

            <div className="card animate-in stagger-3" style={{ padding: 0, overflow: 'hidden', border: '1px solid var(--border)' }}>
                {Object.keys(tree).length === 0 && (
                    <EmptyState
                        icon={<FileText size={32} />}
                        title="No templates found"
                        description="Create one in specs/templates/ to get started."
                        className=""
                    />
                )}

                {Object.values(tree)
                    .sort((a, b) => {
                        if (a.type !== b.type) return a.type === 'folder' ? -1 : 1;
                        return a.name.localeCompare(b.name);
                    })
                    .map(node => renderNode(node))}
            </div>

            {/* Run Configuration Modal */}
            {runModalOpen && (
                <div className="modal-overlay" onClick={() => setRunModalOpen(false)}>
                    <div className="modal-content" onClick={e => e.stopPropagation()} style={{ width: '450px' }}>
                        <h2 style={{ marginBottom: '1.5rem' }}>Generate/Run Template</h2>
                        <div style={{ marginBottom: '1.5rem' }}>
                            <div style={{ padding: '0.75rem', background: 'var(--surface-hover)', borderRadius: '6px', fontSize: '0.95rem' }}>
                                {selectedSpec}
                            </div>
                        </div>
                        <p style={{ color: 'var(--text-secondary)', marginBottom: '2rem' }}>
                            Run this template to generate its automation code. Once successful, it can be reused in other specs.
                        </p>
                        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '1rem' }}>
                            <button className="btn btn-secondary" onClick={() => setRunModalOpen(false)}>Cancel</button>
                            <button className="btn btn-primary" onClick={confirmRun}>Run & Automate</button>
                        </div>
                    </div>
                </div>
            )}

            <style jsx>{`
                .modal-overlay {
                    position: fixed;
                    top: 0; left: 0; right: 0; bottom: 0;
                    background: rgba(0,0,0,0.5);
                    display: flex;
                    alignItems: center;
                    justifyContent: center;
                    z-index: 1000;
                    backdrop-filter: blur(4px);
                }
                .modal-content {
                    background: var(--surface);
                    padding: 2rem;
                    borderRadius: 12px;
                    border: 1px solid var(--border);
                    box-shadow: 0 20px 25px -5px rgba(0,0,0,0.3);
                }
            `}</style>
        </PageLayout>
    );
}
