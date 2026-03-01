'use client';
import React, { useState } from 'react';
import { Folder, FolderOpen, FileCode, Plus, PanelLeftClose, PanelLeft } from 'lucide-react';
import { API_BASE } from '@/lib/api';

interface ApiSpecsFolderTreeProps {
    folders: string[];
    activeFolder: string;
    onFolderChange: (folder: string) => void;
    specCounts: Record<string, number>;
    totalCount: number;
    projectId: string;
    setMessage: (msg: { type: 'success' | 'error'; text: string } | null) => void;
}

const itemStyle: React.CSSProperties = {
    padding: '0.4rem 0.75rem',
    display: 'flex',
    alignItems: 'center',
    gap: '0.5rem',
    cursor: 'pointer',
    borderRadius: 'var(--radius)',
    fontSize: '0.8rem',
    transition: 'background 0.1s var(--ease-smooth)',
};

const activeItemStyle: React.CSSProperties = {
    ...itemStyle,
    background: 'var(--primary-glow)',
    color: 'var(--primary)',
};

export default function ApiSpecsFolderTree({
    folders,
    activeFolder,
    onFolderChange,
    specCounts,
    totalCount,
    projectId,
    setMessage,
}: ApiSpecsFolderTreeProps) {
    const [collapsed, setCollapsed] = useState(false);
    const [creatingFolder, setCreatingFolder] = useState(false);
    const [newFolderName, setNewFolderName] = useState('');

    const handleCreateFolder = async () => {
        if (!newFolderName.trim()) return;
        try {
            const res = await fetch(`${API_BASE}/api-testing/specs/folder`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ folder_name: newFolderName.trim(), project_id: projectId }),
            });
            if (res.ok) {
                setMessage({ type: 'success', text: `Folder "${newFolderName}" created` });
                setNewFolderName('');
                setCreatingFolder(false);
            } else {
                const err = await res.json();
                setMessage({ type: 'error', text: err.detail || 'Failed to create folder' });
            }
        } catch {
            setMessage({ type: 'error', text: 'Failed to create folder' });
        }
    };

    return (
        <div style={{
            width: collapsed ? '0' : '220px',
            minWidth: collapsed ? '0' : '220px',
            overflow: 'hidden',
            transition: 'width 0.2s var(--ease-smooth), min-width 0.2s var(--ease-smooth)',
            borderRight: collapsed ? 'none' : '1px solid var(--border)',
            display: 'flex',
            flexDirection: 'column',
        }}>
            {/* Toggle button */}
            <div style={{
                padding: '0.5rem',
                display: 'flex',
                justifyContent: collapsed ? 'center' : 'flex-end',
            }}>
                <button
                    onClick={() => setCollapsed(!collapsed)}
                    style={{
                        background: 'none',
                        border: 'none',
                        cursor: 'pointer',
                        color: 'var(--text-secondary)',
                        padding: '0.25rem',
                        display: 'flex',
                        alignItems: 'center',
                    }}
                    title={collapsed ? 'Show folder tree' : 'Hide folder tree'}
                >
                    {collapsed ? <PanelLeft size={16} /> : <PanelLeftClose size={16} />}
                </button>
            </div>

            {!collapsed && (
                <div style={{ padding: '0 0.5rem', flex: 1, overflow: 'auto' }}>
                    {/* All Specs */}
                    <div
                        onClick={() => onFolderChange('')}
                        style={activeFolder === '' ? activeItemStyle : itemStyle}
                        onMouseEnter={e => { if (activeFolder !== '') e.currentTarget.style.background = 'rgba(255,255,255,0.03)'; }}
                        onMouseLeave={e => { if (activeFolder !== '') e.currentTarget.style.background = 'transparent'; }}
                    >
                        <FileCode size={14} style={{ flexShrink: 0 }} />
                        <span style={{ flex: 1 }}>All Specs</span>
                        <span style={{
                            fontSize: '0.7rem',
                            padding: '0.1rem 0.4rem',
                            borderRadius: '999px',
                            background: 'rgba(156, 163, 175, 0.1)',
                            color: 'var(--text-secondary)',
                        }}>
                            {totalCount}
                        </span>
                    </div>

                    {/* Divider */}
                    {folders.length > 0 && (
                        <div style={{ height: '1px', background: 'var(--border)', margin: '0.5rem 0' }} />
                    )}

                    {/* Folder items */}
                    {folders.map(folder => {
                        const isActive = activeFolder === folder;
                        const count = specCounts[folder] || 0;

                        return (
                            <div
                                key={folder}
                                onClick={() => onFolderChange(folder)}
                                style={isActive ? activeItemStyle : itemStyle}
                                onMouseEnter={e => { if (!isActive) e.currentTarget.style.background = 'rgba(255,255,255,0.03)'; }}
                                onMouseLeave={e => { if (!isActive) e.currentTarget.style.background = 'transparent'; }}
                            >
                                {isActive
                                    ? <FolderOpen size={14} style={{ flexShrink: 0, color: 'var(--primary)' }} />
                                    : <Folder size={14} style={{ flexShrink: 0 }} />
                                }
                                <span style={{
                                    flex: 1,
                                    overflow: 'hidden',
                                    textOverflow: 'ellipsis',
                                    whiteSpace: 'nowrap',
                                }}>
                                    {folder}
                                </span>
                                <span style={{
                                    fontSize: '0.7rem',
                                    padding: '0.1rem 0.4rem',
                                    borderRadius: '999px',
                                    background: 'rgba(156, 163, 175, 0.1)',
                                    color: 'var(--text-secondary)',
                                }}>
                                    {count}
                                </span>
                            </div>
                        );
                    })}

                    {/* New folder */}
                    <div style={{ marginTop: '0.5rem' }}>
                        {creatingFolder ? (
                            <div style={{ display: 'flex', gap: '0.3rem', padding: '0.25rem' }}>
                                <input
                                    type="text"
                                    placeholder="Folder name"
                                    value={newFolderName}
                                    onChange={e => setNewFolderName(e.target.value)}
                                    onKeyDown={e => { if (e.key === 'Enter') handleCreateFolder(); if (e.key === 'Escape') setCreatingFolder(false); }}
                                    autoFocus
                                    style={{
                                        flex: 1,
                                        padding: '0.25rem 0.4rem',
                                        background: 'var(--background)',
                                        border: '1px solid var(--border)',
                                        borderRadius: 'var(--radius)',
                                        color: 'var(--text-primary)',
                                        fontSize: '0.75rem',
                                        minWidth: 0,
                                    }}
                                />
                                <button
                                    onClick={handleCreateFolder}
                                    style={{
                                        padding: '0.25rem 0.4rem',
                                        background: 'var(--primary)',
                                        color: '#fff',
                                        border: 'none',
                                        borderRadius: 'var(--radius)',
                                        cursor: 'pointer',
                                        fontSize: '0.7rem',
                                    }}
                                >
                                    Add
                                </button>
                            </div>
                        ) : (
                            <button
                                onClick={() => setCreatingFolder(true)}
                                style={{
                                    ...itemStyle,
                                    color: 'var(--text-secondary)',
                                    opacity: 0.7,
                                    width: '100%',
                                    border: 'none',
                                    background: 'none',
                                }}
                                onMouseEnter={e => { e.currentTarget.style.opacity = '1'; }}
                                onMouseLeave={e => { e.currentTarget.style.opacity = '0.7'; }}
                            >
                                <Plus size={14} style={{ flexShrink: 0 }} />
                                <span>New Folder</span>
                            </button>
                        )}
                    </div>
                </div>
            )}
        </div>
    );
}
