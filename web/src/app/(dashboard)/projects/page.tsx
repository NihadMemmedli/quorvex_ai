'use client';

import { useState, useEffect } from 'react';
import { useSearchParams, useRouter } from 'next/navigation';
import { FolderKanban, Plus, Pencil, Trash2, X, Check, AlertTriangle, FileText, Play, Layers } from 'lucide-react';
import { useProject, Project } from '@/contexts/ProjectContext';
import { PageLayout } from '@/components/ui/page-layout';
import { PageHeader } from '@/components/ui/page-header';
import { EmptyState } from '@/components/ui/empty-state';
import { ListPageSkeleton } from '@/components/ui/page-skeleton';

export default function ProjectsPage() {
    const router = useRouter();
    const searchParams = useSearchParams();
    const { projects, currentProject, setCurrentProject, createProject, updateProject, deleteProject, refreshProjects, isLoading } = useProject();

    // Modal states
    const [showCreateModal, setShowCreateModal] = useState(false);
    const [showEditModal, setShowEditModal] = useState(false);
    const [showDeleteModal, setShowDeleteModal] = useState(false);
    const [selectedProject, setSelectedProject] = useState<Project | null>(null);

    // Form states
    const [formName, setFormName] = useState('');
    const [formDescription, setFormDescription] = useState('');
    const [formBaseUrl, setFormBaseUrl] = useState('');
    const [formError, setFormError] = useState('');
    const [isSubmitting, setIsSubmitting] = useState(false);

    // Check URL for action parameter
    useEffect(() => {
        if (searchParams.get('action') === 'create') {
            setShowCreateModal(true);
            // Clear the URL parameter
            router.replace('/projects');
        }
    }, [searchParams, router]);

    const handleOpenCreate = () => {
        setFormName('');
        setFormDescription('');
        setFormBaseUrl('');
        setFormError('');
        setShowCreateModal(true);
    };

    const handleOpenEdit = (project: Project) => {
        setSelectedProject(project);
        setFormName(project.name);
        setFormDescription(project.description || '');
        setFormBaseUrl(project.base_url || '');
        setFormError('');
        setShowEditModal(true);
    };

    const handleOpenDelete = (project: Project) => {
        setSelectedProject(project);
        setShowDeleteModal(true);
    };

    const handleCreate = async () => {
        if (!formName.trim()) {
            setFormError('Project name is required');
            return;
        }

        setIsSubmitting(true);
        setFormError('');

        try {
            const newProject = await createProject(formName.trim(), formDescription.trim() || undefined, formBaseUrl.trim() || undefined);
            setShowCreateModal(false);
            setCurrentProject(newProject);
        } catch (err) {
            setFormError(err instanceof Error ? err.message : 'Failed to create project');
        } finally {
            setIsSubmitting(false);
        }
    };

    const handleUpdate = async () => {
        if (!selectedProject || !formName.trim()) {
            setFormError('Project name is required');
            return;
        }

        setIsSubmitting(true);
        setFormError('');

        try {
            await updateProject(selectedProject.id, {
                name: formName.trim(),
                description: formDescription.trim() || undefined,
                base_url: formBaseUrl.trim() || undefined
            });
            setShowEditModal(false);
            setSelectedProject(null);
        } catch (err) {
            setFormError(err instanceof Error ? err.message : 'Failed to update project');
        } finally {
            setIsSubmitting(false);
        }
    };

    const handleDelete = async () => {
        if (!selectedProject) return;

        setIsSubmitting(true);

        try {
            await deleteProject(selectedProject.id);
            setShowDeleteModal(false);
            setSelectedProject(null);
        } catch (err) {
            console.error('Failed to delete project:', err);
        } finally {
            setIsSubmitting(false);
        }
    };

    if (isLoading) {
        return (
            <PageLayout tier="narrow">
                <ListPageSkeleton rows={3} />
            </PageLayout>
        );
    }

    return (
        <PageLayout tier="narrow">
            <PageHeader
                title="Projects"
                subtitle="Manage your test projects and organize specs, runs, and batches."
                icon={<FolderKanban size={20} />}
                actions={
                    <button
                        onClick={handleOpenCreate}
                        className="btn btn-primary"
                        style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}
                    >
                        <Plus size={20} />
                        New Project
                    </button>
                }
            />

            {/* Projects List */}
            <div className="animate-in stagger-2" style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                {projects.length === 0 ? (
                    <EmptyState
                        icon={<FolderKanban size={32} />}
                        title="No projects yet"
                        description="Create your first project to organize your tests."
                        action={
                            <button onClick={handleOpenCreate} className="btn btn-primary">
                                Create Project
                            </button>
                        }
                    />
                ) : (
                    projects.map((project) => (
                        <div
                            key={project.id}
                            style={{
                                padding: '1.5rem',
                                background: currentProject?.id === project.id ? 'var(--primary-bg)' : 'var(--surface)',
                                borderRadius: 'var(--radius)',
                                border: `1px solid ${currentProject?.id === project.id ? 'var(--primary)' : 'var(--border)'}`,
                                transition: 'all 0.2s var(--ease-smooth)',
                                boxShadow: 'var(--shadow-card)',
                            }}
                        >
                            <div style={{ display: 'flex', gap: '1rem', alignItems: 'flex-start' }}>
                                {/* Icon */}
                                <div style={{
                                    width: 48,
                                    height: 48,
                                    borderRadius: 8,
                                    background: currentProject?.id === project.id ? 'var(--primary)' : 'var(--surface-hover)',
                                    display: 'flex',
                                    alignItems: 'center',
                                    justifyContent: 'center',
                                    color: currentProject?.id === project.id ? 'white' : 'var(--text-secondary)',
                                    flexShrink: 0
                                }}>
                                    <FolderKanban size={24} />
                                </div>

                                {/* Info */}
                                <div style={{ flex: 1, minWidth: 0 }}>
                                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '0.25rem' }}>
                                        <h3 style={{
                                            fontSize: '1.2rem',
                                            fontWeight: 600,
                                            color: currentProject?.id === project.id ? 'var(--primary)' : 'var(--text)'
                                        }}>
                                            {project.name}
                                        </h3>
                                        {currentProject?.id === project.id && (
                                            <span style={{
                                                fontSize: '0.75rem',
                                                padding: '0.2rem 0.6rem',
                                                borderRadius: '999px',
                                                background: 'var(--primary)',
                                                color: 'white',
                                                fontWeight: 600
                                            }}>
                                                Current
                                            </span>
                                        )}
                                        {project.id === 'default' && (
                                            <span style={{
                                                fontSize: '0.75rem',
                                                padding: '0.2rem 0.6rem',
                                                borderRadius: '999px',
                                                background: 'var(--surface-hover)',
                                                color: 'var(--text-secondary)',
                                                fontWeight: 500
                                            }}>
                                                Default
                                            </span>
                                        )}
                                    </div>

                                    {project.description && (
                                        <p style={{
                                            color: 'var(--text-secondary)',
                                            fontSize: '0.9rem',
                                            marginBottom: '0.75rem'
                                        }}>
                                            {project.description}
                                        </p>
                                    )}

                                    {/* Stats */}
                                    <div style={{ display: 'flex', gap: '1.5rem', fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
                                        <span style={{ display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
                                            <FileText size={14} />
                                            {project.spec_count} specs
                                        </span>
                                        <span style={{ display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
                                            <Play size={14} />
                                            {project.run_count} runs
                                        </span>
                                        <span style={{ display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
                                            <Layers size={14} />
                                            {project.batch_count} batches
                                        </span>
                                    </div>
                                </div>

                                {/* Actions */}
                                <div style={{ display: 'flex', gap: '0.5rem' }}>
                                    {currentProject?.id !== project.id && (
                                        <button
                                            onClick={() => setCurrentProject(project)}
                                            className="btn btn-secondary"
                                            style={{ padding: '0.5rem 1rem', fontSize: '0.85rem' }}
                                        >
                                            Switch
                                        </button>
                                    )}
                                    <button
                                        onClick={() => handleOpenEdit(project)}
                                        style={{
                                            padding: '0.5rem',
                                            background: 'transparent',
                                            border: '1px solid var(--border)',
                                            borderRadius: 6,
                                            cursor: 'pointer',
                                            color: 'var(--text-secondary)',
                                            transition: 'all 0.2s'
                                        }}
                                        onMouseEnter={(e) => {
                                            e.currentTarget.style.borderColor = 'var(--primary)';
                                            e.currentTarget.style.color = 'var(--primary)';
                                        }}
                                        onMouseLeave={(e) => {
                                            e.currentTarget.style.borderColor = 'var(--border)';
                                            e.currentTarget.style.color = 'var(--text-secondary)';
                                        }}
                                    >
                                        <Pencil size={16} />
                                    </button>
                                    {project.id !== 'default' && (
                                        <button
                                            onClick={() => handleOpenDelete(project)}
                                            style={{
                                                padding: '0.5rem',
                                                background: 'transparent',
                                                border: '1px solid var(--border)',
                                                borderRadius: 6,
                                                cursor: 'pointer',
                                                color: 'var(--text-secondary)',
                                                transition: 'all 0.2s'
                                            }}
                                            onMouseEnter={(e) => {
                                                e.currentTarget.style.borderColor = 'var(--danger)';
                                                e.currentTarget.style.color = 'var(--danger)';
                                            }}
                                            onMouseLeave={(e) => {
                                                e.currentTarget.style.borderColor = 'var(--border)';
                                                e.currentTarget.style.color = 'var(--text-secondary)';
                                            }}
                                        >
                                            <Trash2 size={16} />
                                        </button>
                                    )}
                                </div>
                            </div>
                        </div>
                    ))
                )}
            </div>

            {/* Create Modal */}
            {showCreateModal && (
                <div style={{
                    position: 'fixed',
                    inset: 0,
                    background: 'rgba(0, 0, 0, 0.5)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    zIndex: 1000,
                    backdropFilter: 'blur(4px)'
                }} onClick={() => setShowCreateModal(false)}>
                    <div
                        className="card"
                        style={{
                            width: '100%',
                            maxWidth: '500px',
                            padding: '2rem',
                            animation: 'slideUp 0.2s ease-out'
                        }}
                        onClick={(e) => e.stopPropagation()}
                    >
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.5rem' }}>
                            <h2 style={{ fontSize: '1.3rem', fontWeight: 600 }}>Create New Project</h2>
                            <button
                                onClick={() => setShowCreateModal(false)}
                                style={{
                                    background: 'transparent',
                                    border: 'none',
                                    cursor: 'pointer',
                                    color: 'var(--text-secondary)',
                                    padding: '0.25rem'
                                }}
                            >
                                <X size={20} />
                            </button>
                        </div>

                        <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                            <div>
                                <label style={{ display: 'block', marginBottom: '0.5rem', fontWeight: 500 }}>
                                    Project Name <span style={{ color: 'var(--danger)' }}>*</span>
                                </label>
                                <input
                                    type="text"
                                    value={formName}
                                    onChange={(e) => setFormName(e.target.value)}
                                    placeholder="My Test Project"
                                    style={{
                                        width: '100%',
                                        padding: '0.75rem 1rem',
                                        borderRadius: 'var(--radius)',
                                        border: '1px solid var(--border)',
                                        background: 'var(--surface)',
                                        color: 'var(--text)',
                                        fontSize: '1rem'
                                    }}
                                    autoFocus
                                />
                            </div>

                            <div>
                                <label style={{ display: 'block', marginBottom: '0.5rem', fontWeight: 500 }}>
                                    Description
                                </label>
                                <textarea
                                    value={formDescription}
                                    onChange={(e) => setFormDescription(e.target.value)}
                                    placeholder="Optional description for this project"
                                    rows={3}
                                    style={{
                                        width: '100%',
                                        padding: '0.75rem 1rem',
                                        borderRadius: 'var(--radius)',
                                        border: '1px solid var(--border)',
                                        background: 'var(--surface)',
                                        color: 'var(--text)',
                                        fontSize: '1rem',
                                        resize: 'vertical'
                                    }}
                                />
                            </div>

                            <div>
                                <label style={{ display: 'block', marginBottom: '0.5rem', fontWeight: 500 }}>
                                    Base URL
                                </label>
                                <input
                                    type="url"
                                    value={formBaseUrl}
                                    onChange={(e) => setFormBaseUrl(e.target.value)}
                                    placeholder="https://example.com"
                                    style={{
                                        width: '100%',
                                        padding: '0.75rem 1rem',
                                        borderRadius: 'var(--radius)',
                                        border: '1px solid var(--border)',
                                        background: 'var(--surface)',
                                        color: 'var(--text)',
                                        fontSize: '1rem'
                                    }}
                                />
                            </div>

                            {formError && (
                                <div style={{
                                    padding: '0.75rem 1rem',
                                    borderRadius: 'var(--radius)',
                                    background: 'var(--danger-muted)',
                                    border: '1px solid rgba(248, 113, 113, 0.2)',
                                    color: 'var(--danger)',
                                    fontSize: '0.9rem'
                                }}>
                                    {formError}
                                </div>
                            )}

                            <div style={{ display: 'flex', gap: '1rem', justifyContent: 'flex-end', marginTop: '0.5rem' }}>
                                <button
                                    onClick={() => setShowCreateModal(false)}
                                    className="btn btn-secondary"
                                    disabled={isSubmitting}
                                >
                                    Cancel
                                </button>
                                <button
                                    onClick={handleCreate}
                                    className="btn btn-primary"
                                    disabled={isSubmitting}
                                    style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}
                                >
                                    {isSubmitting ? (
                                        <>
                                            <div className="loading-spinner" style={{ width: 16, height: 16 }} />
                                            Creating...
                                        </>
                                    ) : (
                                        <>
                                            <Check size={16} />
                                            Create Project
                                        </>
                                    )}
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
            )}

            {/* Edit Modal */}
            {showEditModal && selectedProject && (
                <div style={{
                    position: 'fixed',
                    inset: 0,
                    background: 'rgba(0, 0, 0, 0.5)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    zIndex: 1000,
                    backdropFilter: 'blur(4px)'
                }} onClick={() => setShowEditModal(false)}>
                    <div
                        className="card"
                        style={{
                            width: '100%',
                            maxWidth: '500px',
                            padding: '2rem',
                            animation: 'slideUp 0.2s ease-out'
                        }}
                        onClick={(e) => e.stopPropagation()}
                    >
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.5rem' }}>
                            <h2 style={{ fontSize: '1.3rem', fontWeight: 600 }}>Edit Project</h2>
                            <button
                                onClick={() => setShowEditModal(false)}
                                style={{
                                    background: 'transparent',
                                    border: 'none',
                                    cursor: 'pointer',
                                    color: 'var(--text-secondary)',
                                    padding: '0.25rem'
                                }}
                            >
                                <X size={20} />
                            </button>
                        </div>

                        <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                            <div>
                                <label style={{ display: 'block', marginBottom: '0.5rem', fontWeight: 500 }}>
                                    Project Name <span style={{ color: 'var(--danger)' }}>*</span>
                                </label>
                                <input
                                    type="text"
                                    value={formName}
                                    onChange={(e) => setFormName(e.target.value)}
                                    style={{
                                        width: '100%',
                                        padding: '0.75rem 1rem',
                                        borderRadius: 'var(--radius)',
                                        border: '1px solid var(--border)',
                                        background: 'var(--surface)',
                                        color: 'var(--text)',
                                        fontSize: '1rem'
                                    }}
                                    autoFocus
                                />
                            </div>

                            <div>
                                <label style={{ display: 'block', marginBottom: '0.5rem', fontWeight: 500 }}>
                                    Description
                                </label>
                                <textarea
                                    value={formDescription}
                                    onChange={(e) => setFormDescription(e.target.value)}
                                    rows={3}
                                    style={{
                                        width: '100%',
                                        padding: '0.75rem 1rem',
                                        borderRadius: 'var(--radius)',
                                        border: '1px solid var(--border)',
                                        background: 'var(--surface)',
                                        color: 'var(--text)',
                                        fontSize: '1rem',
                                        resize: 'vertical'
                                    }}
                                />
                            </div>

                            <div>
                                <label style={{ display: 'block', marginBottom: '0.5rem', fontWeight: 500 }}>
                                    Base URL
                                </label>
                                <input
                                    type="url"
                                    value={formBaseUrl}
                                    onChange={(e) => setFormBaseUrl(e.target.value)}
                                    placeholder="https://example.com"
                                    style={{
                                        width: '100%',
                                        padding: '0.75rem 1rem',
                                        borderRadius: 'var(--radius)',
                                        border: '1px solid var(--border)',
                                        background: 'var(--surface)',
                                        color: 'var(--text)',
                                        fontSize: '1rem'
                                    }}
                                />
                            </div>

                            {formError && (
                                <div style={{
                                    padding: '0.75rem 1rem',
                                    borderRadius: 'var(--radius)',
                                    background: 'var(--danger-muted)',
                                    border: '1px solid rgba(248, 113, 113, 0.2)',
                                    color: 'var(--danger)',
                                    fontSize: '0.9rem'
                                }}>
                                    {formError}
                                </div>
                            )}

                            <div style={{ display: 'flex', gap: '1rem', justifyContent: 'flex-end', marginTop: '0.5rem' }}>
                                <button
                                    onClick={() => setShowEditModal(false)}
                                    className="btn btn-secondary"
                                    disabled={isSubmitting}
                                >
                                    Cancel
                                </button>
                                <button
                                    onClick={handleUpdate}
                                    className="btn btn-primary"
                                    disabled={isSubmitting}
                                    style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}
                                >
                                    {isSubmitting ? (
                                        <>
                                            <div className="loading-spinner" style={{ width: 16, height: 16 }} />
                                            Saving...
                                        </>
                                    ) : (
                                        <>
                                            <Check size={16} />
                                            Save Changes
                                        </>
                                    )}
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
            )}

            {/* Delete Confirmation Modal */}
            {showDeleteModal && selectedProject && (
                <div style={{
                    position: 'fixed',
                    inset: 0,
                    background: 'rgba(0, 0, 0, 0.5)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    zIndex: 1000,
                    backdropFilter: 'blur(4px)'
                }} onClick={() => setShowDeleteModal(false)}>
                    <div
                        className="card"
                        style={{
                            width: '100%',
                            maxWidth: '450px',
                            padding: '2rem',
                            animation: 'slideUp 0.2s ease-out'
                        }}
                        onClick={(e) => e.stopPropagation()}
                    >
                        <div style={{
                            width: 48,
                            height: 48,
                            borderRadius: '50%',
                            background: 'var(--danger-muted)',
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            marginBottom: '1rem',
                            border: '1px solid rgba(248, 113, 113, 0.2)'
                        }}>
                            <AlertTriangle size={24} color="var(--danger)" />
                        </div>

                        <h2 style={{ fontSize: '1.3rem', fontWeight: 600, marginBottom: '0.75rem' }}>
                            Delete Project?
                        </h2>

                        <p style={{ color: 'var(--text-secondary)', marginBottom: '1rem', lineHeight: 1.6 }}>
                            Are you sure you want to delete <strong>{selectedProject.name}</strong>?
                        </p>

                        <p style={{
                            padding: '0.75rem 1rem',
                            borderRadius: 'var(--radius)',
                            background: 'var(--surface-hover)',
                            fontSize: '0.9rem',
                            color: 'var(--text-secondary)',
                            marginBottom: '1.5rem'
                        }}>
                            All specs, runs, and batches will be reassigned to the Default Project.
                        </p>

                        <div style={{ display: 'flex', gap: '1rem', justifyContent: 'flex-end' }}>
                            <button
                                onClick={() => setShowDeleteModal(false)}
                                className="btn btn-secondary"
                                disabled={isSubmitting}
                            >
                                Cancel
                            </button>
                            <button
                                onClick={handleDelete}
                                className="btn btn-primary"
                                disabled={isSubmitting}
                                style={{
                                    background: 'var(--danger)',
                                    borderColor: 'var(--danger)',
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: '0.5rem'
                                }}
                            >
                                {isSubmitting ? (
                                    <>
                                        <div className="loading-spinner" style={{ width: 16, height: 16 }} />
                                        Deleting...
                                    </>
                                ) : (
                                    <>
                                        <Trash2 size={16} />
                                        Delete Project
                                    </>
                                )}
                            </button>
                        </div>
                    </div>
                </div>
            )}

            <style jsx>{`
                @keyframes slideUp {
                    from {
                        opacity: 0;
                        transform: translateY(10px);
                    }
                    to {
                        opacity: 1;
                        transform: translateY(0);
                    }
                }
            `}</style>
        </PageLayout>
    );
}
