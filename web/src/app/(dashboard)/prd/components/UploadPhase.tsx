'use client';

import React, { useState, useRef, useCallback } from 'react';
import { UploadCloud, FileText, X, Trash2, Loader2, ChevronRight, Layers } from 'lucide-react';
import type { ExistingProject } from './types';

interface UploadPhaseProps {
    onUpload: (file: File) => void;
    onLoadProject: (projectId: string) => void;
    onDeleteProject: (projectId: string) => void;
    existingProjects: ExistingProject[];
    isUploading: boolean;
    targetFeatures: number;
    onTargetFeaturesChange: (n: number) => void;
}

function formatFileSize(bytes: number): string {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function UploadPhase({
    onUpload,
    onLoadProject,
    onDeleteProject,
    existingProjects,
    isUploading,
    targetFeatures,
    onTargetFeaturesChange,
}: UploadPhaseProps) {
    const [file, setFile] = useState<File | null>(null);
    const [isDragOver, setIsDragOver] = useState(false);
    const inputRef = useRef<HTMLInputElement>(null);

    const handleFile = useCallback((f: File | null) => {
        if (f) {
            setFile(f);
        }
    }, []);

    const handleDragOver = useCallback((e: React.DragEvent) => {
        e.preventDefault();
        e.stopPropagation();
        setIsDragOver(true);
    }, []);

    const handleDragLeave = useCallback((e: React.DragEvent) => {
        e.preventDefault();
        e.stopPropagation();
        setIsDragOver(false);
    }, []);

    const handleDrop = useCallback((e: React.DragEvent) => {
        e.preventDefault();
        e.stopPropagation();
        setIsDragOver(false);
        const droppedFile = e.dataTransfer.files?.[0];
        if (droppedFile) {
            handleFile(droppedFile);
        }
    }, [handleFile]);

    const handleInputChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
        const selected = e.target.files?.[0];
        if (selected) {
            handleFile(selected);
        }
    }, [handleFile]);

    const clearFile = useCallback(() => {
        setFile(null);
        if (inputRef.current) {
            inputRef.current.value = '';
        }
    }, []);

    const handleStartAnalysis = useCallback(() => {
        if (file && !isUploading) {
            onUpload(file);
        }
    }, [file, isUploading, onUpload]);

    const canStart = file !== null && !isUploading;

    return (
        <div style={{ maxWidth: 640, margin: '0 auto' }}>
            {/* Upload Card */}
            <div className="card-elevated animate-in stagger-1" style={{ padding: '2rem' }}>
                {/* Drop Zone */}
                <div
                    onClick={() => inputRef.current?.click()}
                    onDragOver={handleDragOver}
                    onDragLeave={handleDragLeave}
                    onDrop={handleDrop}
                    style={{
                        height: 200,
                        border: '2px dashed',
                        borderColor: isDragOver ? 'var(--primary)' : 'var(--border)',
                        borderRadius: 'var(--radius-lg)',
                        background: isDragOver ? 'rgba(59,130,246,0.06)' : 'transparent',
                        transform: isDragOver ? 'scale(1.01)' : 'scale(1)',
                        transition: 'all 0.25s var(--ease-smooth)',
                        cursor: 'pointer',
                        display: 'flex',
                        flexDirection: 'column',
                        alignItems: 'center',
                        justifyContent: 'center',
                        gap: '0.5rem',
                        position: 'relative',
                    }}
                >
                    <input
                        ref={inputRef}
                        type="file"
                        accept=".pdf,.doc,.docx"
                        onChange={handleInputChange}
                        style={{ display: 'none' }}
                    />

                    {file ? (
                        <div style={{
                            display: 'flex',
                            flexDirection: 'column',
                            alignItems: 'center',
                            gap: '0.5rem',
                        }}>
                            <div style={{
                                width: 56,
                                height: 56,
                                borderRadius: 'var(--radius)',
                                background: 'rgba(59,130,246,0.1)',
                                display: 'flex',
                                alignItems: 'center',
                                justifyContent: 'center',
                            }}>
                                <FileText size={28} style={{ color: 'var(--primary)' }} />
                            </div>
                            <span style={{
                                fontSize: '0.875rem',
                                fontWeight: 600,
                                color: 'var(--text)',
                                maxWidth: 280,
                                textAlign: 'center',
                                overflow: 'hidden',
                                textOverflow: 'ellipsis',
                                whiteSpace: 'nowrap',
                            }}>
                                {file.name}
                            </span>
                            <span style={{
                                fontSize: '0.75rem',
                                color: 'var(--text-tertiary)',
                            }}>
                                {formatFileSize(file.size)} &middot; click to replace
                            </span>
                            <button
                                onClick={(e) => {
                                    e.stopPropagation();
                                    clearFile();
                                }}
                                style={{
                                    position: 'absolute',
                                    top: 12,
                                    right: 12,
                                    width: 28,
                                    height: 28,
                                    borderRadius: 'var(--radius-sm)',
                                    display: 'flex',
                                    alignItems: 'center',
                                    justifyContent: 'center',
                                    color: 'var(--text-secondary)',
                                    transition: 'all 0.2s',
                                }}
                                onMouseEnter={(e) => {
                                    e.currentTarget.style.background = 'rgba(248,113,113,0.1)';
                                    e.currentTarget.style.color = 'var(--danger)';
                                }}
                                onMouseLeave={(e) => {
                                    e.currentTarget.style.background = 'transparent';
                                    e.currentTarget.style.color = 'var(--text-secondary)';
                                }}
                            >
                                <X size={16} />
                            </button>
                        </div>
                    ) : (
                        <>
                            <UploadCloud
                                size={48}
                                style={{
                                    color: 'var(--primary)',
                                    opacity: 0.6,
                                    animation: 'subtleFloat 3s ease-in-out infinite',
                                }}
                            />
                            <span style={{
                                fontSize: '0.875rem',
                                fontWeight: 500,
                                color: 'var(--text)',
                                marginTop: 4,
                            }}>
                                Drop your file here or click to browse
                            </span>
                            <span style={{
                                fontSize: '0.75rem',
                                color: 'var(--text-tertiary)',
                            }}>
                                PDF, DOC, DOCX up to 50MB
                            </span>
                        </>
                    )}
                </div>

                {/* Target Features Row */}
                <div style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '0.75rem',
                    marginTop: '1rem',
                    padding: '0.625rem 0.875rem',
                    borderRadius: 'var(--radius)',
                    background: 'rgba(255,255,255,0.02)',
                    border: '1px solid var(--border)',
                }}>
                    <label
                        htmlFor="target-features"
                        style={{
                            fontSize: '0.8rem',
                            fontWeight: 500,
                            color: 'var(--text-secondary)',
                            whiteSpace: 'nowrap',
                        }}
                    >
                        Target Features
                    </label>
                    <input
                        id="target-features"
                        type="number"
                        min={5}
                        max={50}
                        value={targetFeatures}
                        onChange={(e) => {
                            const val = parseInt(e.target.value, 10);
                            if (!isNaN(val)) {
                                onTargetFeaturesChange(Math.max(5, Math.min(50, val)));
                            }
                        }}
                        style={{
                            width: 80,
                            height: 32,
                            padding: '0 0.5rem',
                            background: 'var(--background)',
                            border: '1px solid var(--border)',
                            borderRadius: 'var(--radius-sm)',
                            color: 'var(--text)',
                            fontSize: '0.8rem',
                            fontFamily: 'var(--font-mono)',
                            textAlign: 'center',
                            outline: 'none',
                        }}
                    />
                    <span style={{
                        fontSize: '0.7rem',
                        color: 'var(--text-tertiary)',
                    }}>
                        5-50 &middot; lower = more consolidated
                    </span>
                </div>

                {/* Start Analysis Button */}
                <button
                    onClick={handleStartAnalysis}
                    disabled={!canStart}
                    style={{
                        width: '100%',
                        height: 52,
                        marginTop: '1rem',
                        borderRadius: 'var(--radius)',
                        background: canStart
                            ? 'linear-gradient(135deg, var(--primary), #2563eb)'
                            : 'linear-gradient(135deg, var(--primary), #2563eb)',
                        color: 'white',
                        fontSize: '0.875rem',
                        fontWeight: 600,
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        gap: '0.5rem',
                        opacity: canStart ? 1 : 0.5,
                        boxShadow: canStart ? '0 0 24px rgba(59,130,246,0.3)' : 'none',
                        cursor: canStart ? 'pointer' : 'not-allowed',
                        transition: 'all 0.25s var(--ease-smooth)',
                        position: 'relative',
                        overflow: 'hidden',
                    }}
                >
                    {isUploading ? (
                        <>
                            <Loader2 size={18} style={{ animation: 'spin 1s linear infinite' }} />
                            Analyzing Document...
                        </>
                    ) : (
                        <>
                            Start Analysis
                            <ChevronRight size={18} />
                        </>
                    )}
                    {isUploading && (
                        <div className="progress-shimmer" style={{
                            position: 'absolute',
                            inset: 0,
                        }} />
                    )}
                </button>
            </div>

            {/* Recent Projects */}
            {existingProjects.length > 0 && (
                <div className="animate-in stagger-2" style={{ marginTop: '1.5rem' }}>
                    {/* Section Header */}
                    <div style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: '0.5rem',
                        marginBottom: '0.75rem',
                        paddingLeft: 4,
                    }}>
                        <Layers size={14} style={{ color: 'var(--text-tertiary)' }} />
                        <span style={{
                            fontSize: '0.7rem',
                            fontWeight: 600,
                            textTransform: 'uppercase',
                            letterSpacing: '0.06em',
                            color: 'var(--text-tertiary)',
                        }}>
                            Recent Projects
                        </span>
                    </div>

                    {/* Project List */}
                    <div className="animate-in stagger-3" style={{ display: 'flex', flexDirection: 'column', gap: '0.375rem' }}>
                        {existingProjects.map((p) => (
                            <ProjectItem
                                key={p.project}
                                project={p}
                                onLoad={() => onLoadProject(p.project)}
                                onDelete={() => {
                                    if (window.confirm(`Delete "${p.project}"? This cannot be undone.`)) {
                                        onDeleteProject(p.project);
                                    }
                                }}
                            />
                        ))}
                    </div>
                </div>
            )}
        </div>
    );
}

function ProjectItem({
    project,
    onLoad,
    onDelete,
}: {
    project: ExistingProject;
    onLoad: () => void;
    onDelete: () => void;
}) {
    const [hovered, setHovered] = useState(false);

    return (
        <div
            onClick={onLoad}
            onMouseEnter={() => setHovered(true)}
            onMouseLeave={() => setHovered(false)}
            style={{
                display: 'flex',
                alignItems: 'center',
                gap: '0.75rem',
                padding: '0.75rem 1rem',
                background: hovered ? 'var(--surface-hover)' : 'var(--surface)',
                border: '1px solid',
                borderColor: hovered ? 'var(--border-bright)' : 'var(--border-subtle)',
                borderRadius: 'var(--radius)',
                cursor: 'pointer',
                transition: 'all 0.2s var(--ease-smooth)',
            }}
        >
            <div style={{
                width: 32,
                height: 32,
                borderRadius: 'var(--radius-sm)',
                background: 'rgba(59,130,246,0.08)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                flexShrink: 0,
            }}>
                <FileText size={16} style={{ color: 'var(--primary)', opacity: 0.7 }} />
            </div>

            <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{
                    fontSize: '0.8rem',
                    fontWeight: 600,
                    color: 'var(--text)',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                }}>
                    {project.project}
                </div>
            </div>

            <span style={{
                fontSize: '0.7rem',
                fontFamily: 'var(--font-mono)',
                color: 'var(--text-tertiary)',
                padding: '0.15rem 0.5rem',
                borderRadius: 'var(--radius-sm)',
                background: 'rgba(255,255,255,0.04)',
                border: '1px solid var(--border)',
                whiteSpace: 'nowrap',
                flexShrink: 0,
            }}>
                {project.feature_count} feature{project.feature_count !== 1 ? 's' : ''}
            </span>

            <button
                onClick={(e) => {
                    e.stopPropagation();
                    onDelete();
                }}
                style={{
                    width: 28,
                    height: 28,
                    borderRadius: 'var(--radius-sm)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    color: 'var(--text-tertiary)',
                    opacity: hovered ? 1 : 0,
                    transition: 'all 0.2s',
                    flexShrink: 0,
                }}
                onMouseEnter={(e) => {
                    e.currentTarget.style.background = 'rgba(248,113,113,0.1)';
                    e.currentTarget.style.color = '#f87171';
                }}
                onMouseLeave={(e) => {
                    e.currentTarget.style.background = 'transparent';
                    e.currentTarget.style.color = 'var(--text-tertiary)';
                }}
            >
                <Trash2 size={14} />
            </button>

            <ChevronRight size={14} style={{
                color: 'var(--text-tertiary)',
                opacity: hovered ? 1 : 0.4,
                transition: 'opacity 0.2s',
                flexShrink: 0,
            }} />
        </div>
    );
}
