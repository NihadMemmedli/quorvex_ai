'use client';
import { useState, useEffect, useCallback } from 'react';
import { Home, FileText, Play, Settings, BarChart2, ClipboardList, FlaskConical, Layers, Compass, CheckSquare, Users, Shield, Zap, Activity, Database, BrainCircuit, TrendingUp, Clock, GitBranch, ChevronRight, MessageSquare, Search, Command, Brain, Bot, FolderOpen, PieChart, Rocket } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { ProjectSelector } from './ProjectSelector';
import { UserMenu } from './auth/UserMenu';
import { useAuth } from '@/contexts/AuthContext';
import { useCommandPalette } from './command-palette/CommandPaletteProvider';

interface NavItem {
    href: string;
    label: string;
    icon: LucideIcon;
}

interface NavGroup {
    id: string;
    label: string;
    icon: LucideIcon;
    items: NavItem[];
}

const topLinks: NavItem[] = [
    { href: '/', label: 'Overview', icon: Home },
    { href: '/dashboard', label: 'Reporting', icon: BarChart2 },
    { href: '/assistant', label: 'AI Assistant', icon: MessageSquare },
    { href: '/projects', label: 'Projects', icon: FolderOpen },
];

const navGroups: NavGroup[] = [
    {
        id: 'test-management',
        label: 'Test Management',
        icon: FlaskConical,
        items: [
            { href: '/prd', label: 'PRD', icon: ClipboardList },
            { href: '/specs', label: 'Test Specs', icon: FileText },
            { href: '/templates', label: 'Templates', icon: FileText },
            { href: '/runs', label: 'Test Runs', icon: Play },
            { href: '/regression', label: 'Regression', icon: FlaskConical },
            { href: '/regression/batches', label: 'Batch Reports', icon: Layers },
        ],
    },
    {
        id: 'discovery',
        label: 'Discovery',
        icon: Compass,
        items: [
            { href: '/autopilot', label: 'Auto Pilot', icon: Rocket },
            { href: '/exploration', label: 'Discovery', icon: Compass },
            { href: '/requirements', label: 'Requirements', icon: CheckSquare },
            { href: '/coverage', label: 'Coverage', icon: PieChart },
        ],
    },
    {
        id: 'specialized-testing',
        label: 'Specialized Testing',
        icon: Zap,
        items: [
            { href: '/api-testing', label: 'API Testing', icon: Zap },
            { href: '/load-testing', label: 'Load Testing', icon: Activity },
            { href: '/security-testing', label: 'Security', icon: Shield },
            { href: '/database-testing', label: 'Database', icon: Database },
            { href: '/llm-testing', label: 'LLM Testing', icon: BrainCircuit },
        ],
    },
    {
        id: 'operations',
        label: 'Operations',
        icon: TrendingUp,
        items: [
            { href: '/analytics', label: 'Analytics', icon: TrendingUp },
            { href: '/schedules', label: 'Schedules', icon: Clock },
            { href: '/ci-cd', label: 'CI/CD', icon: GitBranch },
            { href: '/memory', label: 'Memory', icon: Brain },
            { href: '/agents', label: 'Agents', icon: Bot },
        ],
    },
];

const bottomLinks: NavItem[] = [
    { href: '/settings', label: 'Settings', icon: Settings },
];

const STORAGE_KEY = 'sidebar-collapsed-groups';

function isItemActive(href: string, pathname: string): boolean {
    if (href === '/regression/batches') {
        return pathname === href || pathname.startsWith('/regression/batches/');
    }
    if (href === '/schedules') {
        return pathname === href || pathname.startsWith('/schedules/');
    }
    if (href === '/ci-cd') {
        return pathname === href || pathname.startsWith('/ci-cd/');
    }
    if (href === '/assistant') {
        return pathname === href;
    }
    return pathname === href;
}

function loadCollapsedGroups(): Record<string, boolean> {
    if (typeof window === 'undefined') return {};
    try {
        const stored = localStorage.getItem(STORAGE_KEY);
        return stored ? JSON.parse(stored) : {};
    } catch {
        return {};
    }
}

/* ------------------------------------------------------------------ */
/*  Inline keyframes injected once via <style> tag                    */
/* ------------------------------------------------------------------ */
const SIDEBAR_STYLE_ID = 'sidebar-precision-styles';

function ensureSidebarStyles() {
    if (typeof document === 'undefined') return;
    if (document.getElementById(SIDEBAR_STYLE_ID)) return;
    const style = document.createElement('style');
    style.id = SIDEBAR_STYLE_ID;
    style.textContent = `
        @keyframes sidebarPulse {
            0%, 100% { opacity: 1; transform: scale(1); }
            50% { opacity: 0.5; transform: scale(1.3); }
        }
        .sidebar-nav-item:hover {
            background: rgba(255,255,255,0.03) !important;
        }
        .sidebar-group-header:hover {
            background: rgba(255,255,255,0.025) !important;
        }
        .sidebar-search-trigger:hover {
            border-color: var(--text-tertiary) !important;
            box-shadow: inset 0 0 12px rgba(59, 130, 246, 0.06) !important;
        }
        .sidebar-search-trigger:focus-visible {
            border-color: var(--primary) !important;
            box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.15) !important;
            outline: none !important;
        }
        .sidebar-admin-item:hover {
            background: rgba(245, 158, 11, 0.06) !important;
        }
    `;
    document.head.appendChild(style);
}

/* ------------------------------------------------------------------ */
/*  Component                                                         */
/* ------------------------------------------------------------------ */

export function Sidebar() {
    const pathname = usePathname();
    const { user } = useAuth();
    const { open: openCommandPalette } = useCommandPalette();
    const [collapsed, setCollapsed] = useState<Record<string, boolean>>(loadCollapsedGroups);

    // Inject keyframe styles once
    useEffect(() => {
        ensureSidebarStyles();
    }, []);

    const toggleGroup = useCallback((id: string) => {
        setCollapsed(prev => {
            const next = { ...prev, [id]: !prev[id] };
            localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
            return next;
        });
    }, []);

    // Auto-expand group when navigating to a route inside a collapsed group
    useEffect(() => {
        for (const group of navGroups) {
            if (collapsed[group.id] && group.items.some(item => isItemActive(item.href, pathname))) {
                setCollapsed(prev => {
                    const next = { ...prev, [group.id]: false };
                    localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
                    return next;
                });
                break;
            }
        }
    }, [pathname, collapsed]);

    /* ---- Render helpers ---- */

    const renderNavItem = (item: NavItem, isAdmin = false) => {
        const active = isItemActive(item.href, pathname);
        return (
            <Link
                key={item.href}
                href={item.href}
                className="sidebar-nav-item"
                style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '0.65rem',
                    padding: '0.55rem 0.75rem',
                    borderRadius: 'var(--radius-sm)',
                    position: 'relative',
                    background: active
                        ? (isAdmin
                            ? 'linear-gradient(90deg, rgba(245, 158, 11, 0.1), rgba(245, 158, 11, 0.03))'
                            : 'linear-gradient(90deg, rgba(59, 130, 246, 0.12), transparent)')
                        : 'transparent',
                    color: active
                        ? (isAdmin ? '#f59e0b' : 'var(--primary)')
                        : 'var(--text-secondary)',
                    fontWeight: active ? 600 : 500,
                    fontSize: '0.875rem',
                    letterSpacing: '-0.01em',
                    transition: 'all 0.2s var(--ease-smooth)',
                    textDecoration: 'none',
                    borderLeft: active
                        ? (isAdmin
                            ? '3px solid #f59e0b'
                            : '3px solid var(--primary)')
                        : '3px solid transparent',
                    boxShadow: active && !isAdmin
                        ? '-1px 0 8px rgba(59, 130, 246, 0.2)'
                        : active && isAdmin
                        ? '-1px 0 8px rgba(245, 158, 11, 0.15)'
                        : 'none',
                }}
            >
                <item.icon size={18} style={{ flexShrink: 0, opacity: active ? 1 : 0.7 }} />
                <span>{item.label}</span>
            </Link>
        );
    };

    const renderGroupItem = (item: NavItem) => {
        const active = isItemActive(item.href, pathname);
        return (
            <Link
                key={item.href}
                href={item.href}
                className="sidebar-nav-item"
                style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '0.6rem',
                    padding: '0.45rem 0.75rem 0.45rem 2.25rem',
                    borderRadius: 'var(--radius-sm)',
                    position: 'relative',
                    background: active
                        ? 'linear-gradient(90deg, rgba(59, 130, 246, 0.12), transparent)'
                        : 'transparent',
                    color: active ? 'var(--primary)' : 'var(--text-secondary)',
                    fontWeight: active ? 600 : 500,
                    fontSize: '0.875rem',
                    letterSpacing: '-0.01em',
                    transition: 'all 0.2s var(--ease-smooth)',
                    textDecoration: 'none',
                    borderLeft: active ? '3px solid var(--primary)' : '3px solid transparent',
                    boxShadow: active ? '-1px 0 8px rgba(59, 130, 246, 0.2)' : 'none',
                }}
            >
                <item.icon size={16} style={{ flexShrink: 0, opacity: active ? 1 : 0.65 }} />
                <span>{item.label}</span>
            </Link>
        );
    };

    return (
        <aside style={{
            width: 'var(--sidebar-width)',
            background: 'rgba(15, 22, 41, 0.85)',
            backdropFilter: 'blur(16px) saturate(1.3)',
            WebkitBackdropFilter: 'blur(16px) saturate(1.3)',
            borderRight: '1px solid transparent',
            borderImage: 'linear-gradient(to bottom, var(--border-bright), var(--border-subtle), transparent) 1',
            height: '100vh',
            display: 'flex',
            flexDirection: 'column',
            padding: '1rem 0.75rem',
            position: 'relative',
            zIndex: 30,
        }}>
            {/* ---- Logo ---- */}
            <div style={{
                marginBottom: '1.25rem',
                display: 'flex',
                alignItems: 'center',
                gap: '0.7rem',
                padding: '0.15rem 0.25rem',
            }}>
                <img src="/quorvex-logo.svg" alt="Quorvex AI" width={36} height={36} style={{ flexShrink: 0 }} />
                <div style={{ minWidth: 0 }}>
                    <h1 style={{
                        fontSize: '1.05rem',
                        fontWeight: 800,
                        letterSpacing: '-0.03em',
                        lineHeight: 1.2,
                        background: 'linear-gradient(135deg, #f0f4fc, #7e8ba8)',
                        WebkitBackgroundClip: 'text',
                        WebkitTextFillColor: 'transparent',
                        margin: 0,
                    }}>Quorvex AI</h1>
                    <span style={{
                        fontSize: '0.68rem',
                        color: 'var(--text-tertiary)',
                        letterSpacing: '0.01em',
                        lineHeight: 1.3,
                        display: 'block',
                        marginTop: '1px',
                    }}>Intelligent Test Automation Platform</span>
                </div>
            </div>

            {/* ---- Project Selector ---- */}
            <div style={{ marginBottom: '0.75rem', padding: '0 0.1rem' }}>
                <ProjectSelector />
            </div>

            {/* ---- Search Trigger ---- */}
            <button
                onClick={openCommandPalette}
                className="sidebar-search-trigger"
                style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '0.5rem',
                    width: '100%',
                    height: '38px',
                    padding: '0 0.75rem',
                    marginBottom: '0.85rem',
                    borderRadius: 'var(--radius-sm)',
                    border: '1px solid var(--border-subtle)',
                    background: 'rgba(10, 15, 26, 0.5)',
                    color: 'var(--text-tertiary)',
                    fontSize: '0.8rem',
                    cursor: 'pointer',
                    transition: 'all 0.2s var(--ease-smooth)',
                    outline: 'none',
                }}
            >
                <Search size={14} style={{ opacity: 0.6 }} />
                <span style={{ flex: 1, textAlign: 'left' }}>Search...</span>
                <kbd style={{
                    fontSize: '0.6rem',
                    padding: '0.15rem 0.4rem',
                    borderRadius: '4px',
                    background: 'rgba(255,255,255,0.06)',
                    border: '1px solid var(--border)',
                    fontFamily: 'var(--font-mono, monospace)',
                    color: 'var(--text-tertiary)',
                    lineHeight: 1.4,
                    letterSpacing: '0.02em',
                }}>
                    {'\u2318'}K
                </kbd>
            </button>

            {/* ---- Navigation ---- */}
            <nav style={{
                display: 'flex',
                flexDirection: 'column',
                gap: '2px',
                flex: 1,
                overflow: 'auto',
                marginRight: '-0.25rem',
                paddingRight: '0.25rem',
            }}>
                {/* Top-level links */}
                {topLinks.map(link => renderNavItem(link))}

                {/* Gradient Separator */}
                <div style={{
                    height: '1px',
                    background: 'linear-gradient(90deg, transparent, var(--border-bright), transparent)',
                    margin: '0.5rem 0.5rem',
                }} />

                {/* Collapsible groups */}
                {navGroups.map(group => {
                    const isExpanded = !collapsed[group.id];
                    return (
                        <div key={group.id} style={{ marginBottom: '2px' }}>
                            {/* Group header */}
                            <div
                                onClick={() => toggleGroup(group.id)}
                                className="sidebar-group-header"
                                style={{
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: '0.45rem',
                                    padding: '0.45rem 0.75rem',
                                    cursor: 'pointer',
                                    userSelect: 'none',
                                    borderRadius: 'var(--radius-sm)',
                                    transition: 'background 0.2s var(--ease-smooth)',
                                }}
                            >
                                <group.icon size={13} style={{ color: 'var(--text-tertiary)', flexShrink: 0 }} />
                                <span style={{
                                    fontSize: '0.68rem',
                                    fontWeight: 600,
                                    textTransform: 'uppercase',
                                    letterSpacing: '0.06em',
                                    color: 'var(--text-tertiary)',
                                    flex: 1,
                                }}>
                                    {group.label}
                                </span>
                                <ChevronRight
                                    size={13}
                                    style={{
                                        color: 'var(--text-tertiary)',
                                        transform: isExpanded ? 'rotate(90deg)' : 'rotate(0deg)',
                                        transition: 'transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1)',
                                        flexShrink: 0,
                                    }}
                                />
                            </div>
                            {/* Animated group items container */}
                            <div style={{
                                maxHeight: isExpanded ? `${group.items.length * 42}px` : '0px',
                                opacity: isExpanded ? 1 : 0,
                                overflow: 'hidden',
                                transition: 'max-height 0.3s var(--ease-out-expo), opacity 0.25s var(--ease-smooth)',
                            }}>
                                <div style={{
                                    display: 'flex',
                                    flexDirection: 'column',
                                    gap: '1px',
                                    paddingTop: '2px',
                                }}>
                                    {group.items.map(item => renderGroupItem(item))}
                                </div>
                            </div>
                        </div>
                    );
                })}

                {/* Gradient Separator */}
                <div style={{
                    height: '1px',
                    background: 'linear-gradient(90deg, transparent, var(--border-bright), transparent)',
                    margin: '0.5rem 0.5rem',
                }} />

                {/* Settings */}
                {bottomLinks.map(link => renderNavItem(link))}

                {/* Admin Section - Only visible to superusers */}
                {user?.is_superuser && (
                    <>
                        {/* Admin separator */}
                        <div style={{
                            height: '1px',
                            background: 'linear-gradient(90deg, transparent, rgba(245, 158, 11, 0.25), transparent)',
                            margin: '0.5rem 0.5rem',
                        }} />

                        {/* Admin header with premium amber strip */}
                        <div style={{
                            display: 'flex',
                            alignItems: 'center',
                            gap: '0.45rem',
                            padding: '0.4rem 0.75rem',
                            fontSize: '0.68rem',
                            fontWeight: 700,
                            textTransform: 'uppercase',
                            letterSpacing: '0.06em',
                            borderRadius: 'var(--radius-sm)',
                            background: 'linear-gradient(90deg, rgba(245, 158, 11, 0.08), rgba(245, 158, 11, 0.02))',
                            color: '#f59e0b',
                        }}>
                            <Shield size={13} />
                            Admin
                        </div>

                        <Link
                            href="/admin/users"
                            className="sidebar-admin-item sidebar-nav-item"
                            style={{
                                display: 'flex',
                                alignItems: 'center',
                                gap: '0.65rem',
                                padding: '0.55rem 0.75rem',
                                borderRadius: 'var(--radius-sm)',
                                position: 'relative',
                                background: (pathname === '/admin/users' || pathname.startsWith('/admin/users/'))
                                    ? 'linear-gradient(90deg, rgba(245, 158, 11, 0.1), rgba(245, 158, 11, 0.03))'
                                    : 'transparent',
                                color: (pathname === '/admin/users' || pathname.startsWith('/admin/users/'))
                                    ? '#f59e0b' : 'var(--text-secondary)',
                                fontWeight: (pathname === '/admin/users' || pathname.startsWith('/admin/users/')) ? 600 : 500,
                                fontSize: '0.875rem',
                                letterSpacing: '-0.01em',
                                transition: 'all 0.2s var(--ease-smooth)',
                                textDecoration: 'none',
                                borderLeft: (pathname === '/admin/users' || pathname.startsWith('/admin/users/'))
                                    ? '3px solid #f59e0b'
                                    : '3px solid transparent',
                                boxShadow: (pathname === '/admin/users' || pathname.startsWith('/admin/users/'))
                                    ? '-1px 0 8px rgba(245, 158, 11, 0.15)'
                                    : 'none',
                            }}
                        >
                            <Users size={18} style={{ flexShrink: 0 }} />
                            <span>User Management</span>
                        </Link>
                    </>
                )}
            </nav>

            {/* ---- Footer ---- */}
            <div style={{
                marginTop: 'auto',
                display: 'flex',
                flexDirection: 'column',
                gap: '0.75rem',
                paddingTop: '0.5rem',
            }}>
                {/* User Menu separator */}
                <div style={{
                    height: '1px',
                    background: 'linear-gradient(90deg, transparent, var(--border-bright), transparent)',
                }} />
                <UserMenu />

                {/* Status footer */}
                <div style={{
                    padding: '0.6rem 0.65rem',
                    background: 'rgba(0, 0, 0, 0.15)',
                    borderRadius: 'var(--radius-sm)',
                    border: '1px solid rgba(255,255,255,0.03)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                }}>
                    <div style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: '0.4rem',
                        fontSize: '0.7rem',
                        color: 'var(--text-secondary)',
                    }}>
                        <span style={{
                            width: '6px',
                            height: '6px',
                            borderRadius: '50%',
                            background: 'var(--success)',
                            display: 'inline-block',
                            animation: 'sidebarPulse 2.5s ease-in-out infinite',
                            boxShadow: '0 0 6px rgba(52, 211, 153, 0.4)',
                        }} />
                        <span>Online</span>
                    </div>
                    <span style={{
                        fontSize: '0.62rem',
                        color: 'var(--text-tertiary)',
                        letterSpacing: '0.02em',
                    }}>v0.1.0</span>
                </div>
            </div>
        </aside>
    );
}
