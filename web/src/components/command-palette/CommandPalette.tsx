'use client';

import React, { useState, useEffect, useRef, useMemo } from 'react';
import { useRouter } from 'next/navigation';
import { Command } from 'cmdk';
import { Search, Clock, Zap, ArrowRight, FileText, Play, CheckSquare, Loader2 } from 'lucide-react';
import { useAuth } from '@/contexts/AuthContext';
import { useCommandPalette } from './CommandPaletteProvider';
import { useRecentPages } from './useRecentPages';
import { useCommandSearch, SearchResult } from './useCommandSearch';
import { quickActions, navigationItems, adminItems, matchesQuery, CommandItem } from './command-data';

const typeIcons: Record<string, typeof FileText> = {
    spec: FileText,
    run: Play,
    requirement: CheckSquare,
};

export function CommandPalette() {
    const { isOpen, close } = useCommandPalette();
    const { user } = useAuth();
    const router = useRouter();
    const [query, setQuery] = useState('');
    const { recentPages } = useRecentPages();
    const { results: searchResults, isSearching } = useCommandSearch(query);
    const inputRef = useRef<HTMLInputElement>(null);

    // Reset query when opened
    useEffect(() => {
        if (isOpen) {
            setQuery('');
            // Focus input after mount
            requestAnimationFrame(() => {
                inputRef.current?.focus();
            });
        }
    }, [isOpen]);

    // Close on Escape
    useEffect(() => {
        if (!isOpen) return;
        function handleKeyDown(e: KeyboardEvent) {
            if (e.key === 'Escape') {
                close();
            }
        }
        window.addEventListener('keydown', handleKeyDown);
        return () => window.removeEventListener('keydown', handleKeyDown);
    }, [isOpen, close]);

    const handleSelect = (item: CommandItem | SearchResult | { href: string }) => {
        if ('action' in item && item.action) {
            window.dispatchEvent(new CustomEvent(item.action));
            close();
            return;
        }
        if ('href' in item && item.href) {
            router.push(item.href);
            close();
        }
    };

    // Filter static commands
    const filteredQuickActions = useMemo(() =>
        quickActions.filter(item => matchesQuery(item, query)),
    [query]);

    const filteredNavigation = useMemo(() =>
        navigationItems.filter(item => matchesQuery(item, query)),
    [query]);

    const filteredAdmin = useMemo(() =>
        user?.is_superuser ? adminItems.filter(item => matchesQuery(item, query)) : [],
    [query, user?.is_superuser]);

    // Group navigation by group
    const navGroups = useMemo(() => {
        const groups: Record<string, typeof filteredNavigation> = {};
        filteredNavigation.forEach(item => {
            const g = item.group || 'Other';
            if (!groups[g]) groups[g] = [];
            groups[g].push(item);
        });
        return groups;
    }, [filteredNavigation]);

    if (!isOpen) return null;

    return (
        <>
            {/* Backdrop */}
            <div
                onClick={close}
                style={{
                    position: 'fixed',
                    inset: 0,
                    background: 'rgba(0, 0, 0, 0.5)',
                    backdropFilter: 'blur(4px)',
                    zIndex: 9998,
                }}
            />

            {/* Dialog */}
            <div
                style={{
                    position: 'fixed',
                    top: '20%',
                    left: '50%',
                    transform: 'translateX(-50%)',
                    width: '100%',
                    maxWidth: '560px',
                    zIndex: 9999,
                    animation: 'cmdkFadeIn 0.15s ease-out',
                }}
            >
                <Command
                    label="Command palette"
                    className="cmdk-root"
                    shouldFilter={false}
                >
                    {/* Search Input */}
                    <div className="cmdk-input-wrapper">
                        <Search size={18} style={{ color: 'var(--text-secondary)', flexShrink: 0 }} />
                        <Command.Input
                            ref={inputRef}
                            className="cmdk-input"
                            placeholder="Search pages, specs, runs, or actions..."
                            value={query}
                            onValueChange={setQuery}
                        />
                        {isSearching && <Loader2 size={16} style={{ color: 'var(--text-secondary)', animation: 'spin 1s linear infinite' }} />}
                        <kbd className="cmdk-kbd">ESC</kbd>
                    </div>

                    {/* Results */}
                    <Command.List className="cmdk-list">
                        <Command.Empty className="cmdk-empty">
                            No results found.
                        </Command.Empty>

                        {/* Quick Actions */}
                        {filteredQuickActions.length > 0 && (
                            <Command.Group heading="Quick Actions" className="cmdk-group">
                                {filteredQuickActions.map(item => (
                                    <Command.Item
                                        key={item.id}
                                        value={item.id}
                                        onSelect={() => handleSelect(item)}
                                        className="cmdk-item"
                                    >
                                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flex: 1 }}>
                                            <div className="cmdk-item-icon" style={{ background: 'rgba(59, 130, 246, 0.1)', color: 'var(--primary)' }}>
                                                <item.icon size={16} />
                                            </div>
                                            <span>{item.label}</span>
                                        </div>
                                        <Zap size={14} style={{ color: 'var(--text-secondary)', opacity: 0.5 }} />
                                    </Command.Item>
                                ))}
                            </Command.Group>
                        )}

                        {/* Recent Pages */}
                        {!query && recentPages.length > 0 && (
                            <Command.Group heading="Recent" className="cmdk-group">
                                {recentPages.slice(0, 5).map(page => (
                                    <Command.Item
                                        key={page.href}
                                        value={`recent-${page.href}`}
                                        onSelect={() => handleSelect({ href: page.href })}
                                        className="cmdk-item"
                                    >
                                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flex: 1 }}>
                                            <div className="cmdk-item-icon">
                                                <Clock size={16} />
                                            </div>
                                            <span>{page.label}</span>
                                        </div>
                                        <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
                                            {page.href}
                                        </span>
                                    </Command.Item>
                                ))}
                            </Command.Group>
                        )}

                        {/* API Search Results */}
                        {searchResults.length > 0 && (
                            <Command.Group heading="Search Results" className="cmdk-group">
                                {searchResults.map(result => {
                                    const Icon = typeIcons[result.type] || FileText;
                                    return (
                                        <Command.Item
                                            key={result.id}
                                            value={result.id}
                                            onSelect={() => handleSelect(result)}
                                            className="cmdk-item"
                                        >
                                            <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flex: 1, minWidth: 0 }}>
                                                <div className="cmdk-item-icon">
                                                    <Icon size={16} />
                                                </div>
                                                <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                                    {result.label}
                                                </span>
                                            </div>
                                            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexShrink: 0 }}>
                                                {result.subtitle && (
                                                    <span className="cmdk-badge">{result.subtitle}</span>
                                                )}
                                                <span className="cmdk-badge">{result.type}</span>
                                            </div>
                                        </Command.Item>
                                    );
                                })}
                            </Command.Group>
                        )}

                        {/* Navigation */}
                        {Object.entries(navGroups).map(([group, items]) => (
                            <Command.Group key={group} heading={group} className="cmdk-group">
                                {items.map(item => (
                                    <Command.Item
                                        key={item.id}
                                        value={item.id}
                                        onSelect={() => handleSelect(item)}
                                        className="cmdk-item"
                                    >
                                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flex: 1 }}>
                                            <div className="cmdk-item-icon">
                                                <item.icon size={16} />
                                            </div>
                                            <span>{item.label}</span>
                                        </div>
                                        <ArrowRight size={14} style={{ color: 'var(--text-secondary)', opacity: 0.3 }} />
                                    </Command.Item>
                                ))}
                            </Command.Group>
                        ))}

                        {/* Admin */}
                        {filteredAdmin.length > 0 && (
                            <Command.Group heading="Admin" className="cmdk-group">
                                {filteredAdmin.map(item => (
                                    <Command.Item
                                        key={item.id}
                                        value={item.id}
                                        onSelect={() => handleSelect(item)}
                                        className="cmdk-item"
                                    >
                                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flex: 1 }}>
                                            <div className="cmdk-item-icon" style={{ background: 'rgba(245, 158, 11, 0.1)', color: '#f59e0b' }}>
                                                <item.icon size={16} />
                                            </div>
                                            <span style={{ color: '#f59e0b' }}>{item.label}</span>
                                        </div>
                                    </Command.Item>
                                ))}
                            </Command.Group>
                        )}
                    </Command.List>

                    {/* Footer */}
                    <div className="cmdk-footer">
                        <div style={{ display: 'flex', gap: '1rem', alignItems: 'center' }}>
                            <span style={{ display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
                                <kbd className="cmdk-kbd-sm">&uarr;</kbd>
                                <kbd className="cmdk-kbd-sm">&darr;</kbd>
                                <span>Navigate</span>
                            </span>
                            <span style={{ display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
                                <kbd className="cmdk-kbd-sm">&crarr;</kbd>
                                <span>Select</span>
                            </span>
                            <span style={{ display: 'flex', alignItems: 'center', gap: '0.35rem' }}>
                                <kbd className="cmdk-kbd-sm">esc</kbd>
                                <span>Close</span>
                            </span>
                        </div>
                    </div>
                </Command>
            </div>
        </>
    );
}
