'use client';

import { useState, useRef, useEffect } from 'react';
import { ChevronDown, Plus, Settings, FolderKanban, Check } from 'lucide-react';
import Link from 'next/link';
import { useProject, Project } from '@/contexts/ProjectContext';

export function ProjectSelector() {
    const { currentProject, projects, setCurrentProject, isLoading } = useProject();
    const [isOpen, setIsOpen] = useState(false);
    const dropdownRef = useRef<HTMLDivElement>(null);

    // Close dropdown when clicking outside
    useEffect(() => {
        function handleClickOutside(event: MouseEvent) {
            if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
                setIsOpen(false);
            }
        }

        document.addEventListener('mousedown', handleClickOutside);
        return () => document.removeEventListener('mousedown', handleClickOutside);
    }, []);

    const handleSelectProject = (project: Project) => {
        setCurrentProject(project);
        setIsOpen(false);
    };

    if (isLoading) {
        return (
            <div style={{
                padding: '0.75rem 1rem',
                background: 'var(--surface)',
                borderRadius: 'var(--radius)',
                border: '1px solid var(--border)',
                display: 'flex',
                alignItems: 'center',
                gap: '0.5rem'
            }}>
                <div style={{
                    width: 24,
                    height: 24,
                    borderRadius: 6,
                    background: 'var(--surface-hover)',
                    animation: 'pulse 1.5s ease-in-out infinite'
                }} />
                <div style={{
                    flex: 1,
                    height: 16,
                    borderRadius: 4,
                    background: 'var(--surface-hover)',
                    animation: 'pulse 1.5s ease-in-out infinite'
                }} />
            </div>
        );
    }

    return (
        <div ref={dropdownRef} style={{ position: 'relative' }}>
            {/* Trigger Button */}
            <button
                onClick={() => setIsOpen(!isOpen)}
                style={{
                    width: '100%',
                    padding: '0.75rem 1rem',
                    background: 'var(--surface)',
                    borderRadius: 'var(--radius)',
                    border: '1px solid var(--border)',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '0.75rem',
                    cursor: 'pointer',
                    transition: 'all 0.2s',
                    textAlign: 'left'
                }}
                onMouseEnter={(e) => {
                    e.currentTarget.style.borderColor = 'var(--primary)';
                    e.currentTarget.style.background = 'var(--surface-hover)';
                }}
                onMouseLeave={(e) => {
                    e.currentTarget.style.borderColor = 'var(--border)';
                    e.currentTarget.style.background = 'var(--surface)';
                }}
            >
                <div style={{
                    width: 28,
                    height: 28,
                    borderRadius: 6,
                    background: 'var(--primary)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    color: 'white'
                }}>
                    <FolderKanban size={16} />
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{
                        fontSize: '0.85rem',
                        fontWeight: 600,
                        color: 'var(--text)',
                        whiteSpace: 'nowrap',
                        overflow: 'hidden',
                        textOverflow: 'ellipsis'
                    }}>
                        {currentProject?.name || 'Select Project'}
                    </div>
                    <div style={{
                        fontSize: '0.75rem',
                        color: 'var(--text-secondary)'
                    }}>
                        {currentProject ? `${currentProject.spec_count} specs` : 'No project selected'}
                    </div>
                </div>
                <ChevronDown
                    size={16}
                    style={{
                        color: 'var(--text-secondary)',
                        transform: isOpen ? 'rotate(180deg)' : 'rotate(0)',
                        transition: 'transform 0.2s'
                    }}
                />
            </button>

            {/* Dropdown Menu */}
            {isOpen && (
                <div style={{
                    position: 'absolute',
                    top: 'calc(100% + 4px)',
                    left: 0,
                    right: 0,
                    background: 'var(--surface)',
                    borderRadius: 'var(--radius)',
                    border: '1px solid var(--border)',
                    boxShadow: '0 4px 12px rgba(0, 0, 0, 0.15)',
                    zIndex: 1000,
                    maxHeight: '320px',
                    overflow: 'hidden',
                    display: 'flex',
                    flexDirection: 'column'
                }}>
                    {/* Project List */}
                    <div style={{
                        flex: 1,
                        overflowY: 'auto',
                        padding: '0.5rem'
                    }}>
                        {projects.map((project) => (
                            <button
                                key={project.id}
                                onClick={() => handleSelectProject(project)}
                                style={{
                                    width: '100%',
                                    padding: '0.75rem',
                                    background: currentProject?.id === project.id ? 'var(--primary-bg)' : 'transparent',
                                    borderRadius: 6,
                                    border: 'none',
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: '0.75rem',
                                    cursor: 'pointer',
                                    transition: 'background 0.15s',
                                    textAlign: 'left'
                                }}
                                onMouseEnter={(e) => {
                                    if (currentProject?.id !== project.id) {
                                        e.currentTarget.style.background = 'var(--surface-hover)';
                                    }
                                }}
                                onMouseLeave={(e) => {
                                    if (currentProject?.id !== project.id) {
                                        e.currentTarget.style.background = 'transparent';
                                    }
                                }}
                            >
                                <div style={{
                                    width: 24,
                                    height: 24,
                                    borderRadius: 4,
                                    background: currentProject?.id === project.id ? 'var(--primary)' : 'var(--surface-hover)',
                                    display: 'flex',
                                    alignItems: 'center',
                                    justifyContent: 'center',
                                    color: currentProject?.id === project.id ? 'white' : 'var(--text-secondary)'
                                }}>
                                    {currentProject?.id === project.id ? (
                                        <Check size={14} />
                                    ) : (
                                        <FolderKanban size={14} />
                                    )}
                                </div>
                                <div style={{ flex: 1, minWidth: 0 }}>
                                    <div style={{
                                        fontSize: '0.9rem',
                                        fontWeight: currentProject?.id === project.id ? 600 : 500,
                                        color: currentProject?.id === project.id ? 'var(--primary)' : 'var(--text)',
                                        whiteSpace: 'nowrap',
                                        overflow: 'hidden',
                                        textOverflow: 'ellipsis'
                                    }}>
                                        {project.name}
                                    </div>
                                    <div style={{
                                        fontSize: '0.75rem',
                                        color: 'var(--text-secondary)'
                                    }}>
                                        {project.spec_count} specs &middot; {project.run_count} runs
                                    </div>
                                </div>
                            </button>
                        ))}
                    </div>

                    {/* Divider */}
                    <div style={{
                        height: 1,
                        background: 'var(--border)',
                        margin: '0 0.5rem'
                    }} />

                    {/* Actions */}
                    <div style={{ padding: '0.5rem' }}>
                        <Link
                            href="/projects?action=create"
                            onClick={() => setIsOpen(false)}
                            style={{
                                display: 'flex',
                                alignItems: 'center',
                                gap: '0.75rem',
                                padding: '0.75rem',
                                borderRadius: 6,
                                color: 'var(--text)',
                                textDecoration: 'none',
                                transition: 'background 0.15s'
                            }}
                            onMouseEnter={(e) => {
                                e.currentTarget.style.background = 'var(--surface-hover)';
                            }}
                            onMouseLeave={(e) => {
                                e.currentTarget.style.background = 'transparent';
                            }}
                        >
                            <Plus size={16} color="var(--text-secondary)" />
                            <span style={{ fontSize: '0.9rem' }}>Create New Project</span>
                        </Link>

                        <Link
                            href="/projects"
                            onClick={() => setIsOpen(false)}
                            style={{
                                display: 'flex',
                                alignItems: 'center',
                                gap: '0.75rem',
                                padding: '0.75rem',
                                borderRadius: 6,
                                color: 'var(--text)',
                                textDecoration: 'none',
                                transition: 'background 0.15s'
                            }}
                            onMouseEnter={(e) => {
                                e.currentTarget.style.background = 'var(--surface-hover)';
                            }}
                            onMouseLeave={(e) => {
                                e.currentTarget.style.background = 'transparent';
                            }}
                        >
                            <Settings size={16} color="var(--text-secondary)" />
                            <span style={{ fontSize: '0.9rem' }}>Manage Projects</span>
                        </Link>
                    </div>
                </div>
            )}

            <style jsx>{`
                @keyframes pulse {
                    0%, 100% { opacity: 1; }
                    50% { opacity: 0.4; }
                }
            `}</style>
        </div>
    );
}
