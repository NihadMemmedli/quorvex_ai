'use client';

import { useState, useRef, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '@/contexts/AuthContext';
import { User, LogOut, Settings, Shield, ChevronUp } from 'lucide-react';

/**
 * User menu component for the sidebar.
 * Shows login button when not authenticated, or user dropdown when authenticated.
 */
export function UserMenu() {
    const router = useRouter();
    const { user, isAuthenticated, isLoading, logout } = useAuth();
    const [isLoggingOut, setIsLoggingOut] = useState(false);
    const [isOpen, setIsOpen] = useState(false);
    const menuRef = useRef<HTMLDivElement>(null);

    const handleLogout = async () => {
        setIsLoggingOut(true);
        try {
            await logout();
            router.push('/login');
        } catch (error) {
            console.error('Logout failed:', error);
        } finally {
            setIsLoggingOut(false);
            setIsOpen(false);
        }
    };

    // Close dropdown when clicking outside
    useEffect(() => {
        const handleClickOutside = (event: MouseEvent) => {
            if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
                setIsOpen(false);
            }
        };

        document.addEventListener('mousedown', handleClickOutside);
        return () => document.removeEventListener('mousedown', handleClickOutside);
    }, []);

    // Show loading skeleton
    if (isLoading) {
        return (
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', padding: '0.5rem' }}>
                <div style={{
                    width: '36px',
                    height: '36px',
                    borderRadius: '8px',
                    background: 'var(--surface-hover)',
                    animation: 'pulse 2s infinite'
                }} />
                <div style={{ flex: 1 }}>
                    <div style={{
                        height: '14px',
                        width: '80px',
                        borderRadius: '4px',
                        background: 'var(--surface-hover)',
                        marginBottom: '4px'
                    }} />
                    <div style={{
                        height: '12px',
                        width: '120px',
                        borderRadius: '4px',
                        background: 'var(--surface-hover)'
                    }} />
                </div>
            </div>
        );
    }

    // Show login button if not authenticated
    if (!isAuthenticated) {
        return (
            <button
                onClick={() => router.push('/login')}
                style={{
                    display: 'flex',
                    width: '100%',
                    alignItems: 'center',
                    gap: '0.75rem',
                    padding: '0.75rem',
                    borderRadius: 'var(--radius)',
                    border: 'none',
                    background: 'transparent',
                    color: 'var(--text-secondary)',
                    cursor: 'pointer',
                    transition: 'all 0.2s',
                    fontSize: '0.875rem',
                    fontWeight: 500,
                }}
                onMouseEnter={(e) => {
                    e.currentTarget.style.background = 'rgba(59, 130, 246, 0.1)';
                    e.currentTarget.style.color = 'var(--primary)';
                }}
                onMouseLeave={(e) => {
                    e.currentTarget.style.background = 'transparent';
                    e.currentTarget.style.color = 'var(--text-secondary)';
                }}
            >
                <User size={20} />
                Sign in
            </button>
        );
    }

    // Get initials for avatar
    const getInitials = (name: string | null, email: string) => {
        if (name) {
            const parts = name.split(' ');
            if (parts.length >= 2) {
                return `${parts[0][0]}${parts[1][0]}`.toUpperCase();
            }
            return name.substring(0, 2).toUpperCase();
        }
        return email.substring(0, 2).toUpperCase();
    };

    const initials = getInitials(user?.full_name || null, user?.email || '');
    const displayName = user?.full_name || user?.email?.split('@')[0] || 'User';

    return (
        <div ref={menuRef} style={{ position: 'relative' }}>
            {/* Dropdown Menu - positioned above the trigger */}
            {isOpen && (
                <div
                    style={{
                        position: 'absolute',
                        bottom: '100%',
                        left: 0,
                        right: 0,
                        marginBottom: '8px',
                        background: 'var(--surface)',
                        border: '1px solid var(--border)',
                        borderRadius: 'var(--radius)',
                        boxShadow: '0 -4px 20px rgba(0, 0, 0, 0.3)',
                        overflow: 'hidden',
                        zIndex: 50,
                    }}
                >
                    {/* User Info Header */}
                    <div style={{
                        padding: '0.75rem 1rem',
                        borderBottom: '1px solid var(--border)',
                    }}>
                        <div style={{ fontWeight: 600, fontSize: '0.875rem', color: 'var(--text)' }}>
                            {displayName}
                        </div>
                        <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', marginTop: '2px' }}>
                            {user?.email}
                        </div>
                        {user?.is_superuser && (
                            <div style={{
                                display: 'inline-flex',
                                alignItems: 'center',
                                gap: '4px',
                                marginTop: '6px',
                                padding: '2px 8px',
                                background: 'rgba(245, 158, 11, 0.1)',
                                borderRadius: '4px',
                                fontSize: '0.7rem',
                                color: '#f59e0b',
                                fontWeight: 500,
                            }}>
                                <Shield size={12} />
                                Admin
                            </div>
                        )}
                    </div>

                    {/* Menu Items */}
                    <div style={{ padding: '0.5rem' }}>
                        <button
                            onClick={() => {
                                router.push('/settings');
                                setIsOpen(false);
                            }}
                            style={{
                                display: 'flex',
                                width: '100%',
                                alignItems: 'center',
                                gap: '0.75rem',
                                padding: '0.625rem 0.75rem',
                                borderRadius: '6px',
                                border: 'none',
                                background: 'transparent',
                                color: 'var(--text-secondary)',
                                cursor: 'pointer',
                                transition: 'all 0.15s',
                                fontSize: '0.875rem',
                            }}
                            onMouseEnter={(e) => {
                                e.currentTarget.style.background = 'var(--surface-hover)';
                                e.currentTarget.style.color = 'var(--text)';
                            }}
                            onMouseLeave={(e) => {
                                e.currentTarget.style.background = 'transparent';
                                e.currentTarget.style.color = 'var(--text-secondary)';
                            }}
                        >
                            <Settings size={16} />
                            Settings
                        </button>

                        <button
                            onClick={handleLogout}
                            disabled={isLoggingOut}
                            style={{
                                display: 'flex',
                                width: '100%',
                                alignItems: 'center',
                                gap: '0.75rem',
                                padding: '0.625rem 0.75rem',
                                borderRadius: '6px',
                                border: 'none',
                                background: 'transparent',
                                color: '#ef4444',
                                cursor: isLoggingOut ? 'not-allowed' : 'pointer',
                                transition: 'all 0.15s',
                                fontSize: '0.875rem',
                                opacity: isLoggingOut ? 0.6 : 1,
                            }}
                            onMouseEnter={(e) => {
                                if (!isLoggingOut) {
                                    e.currentTarget.style.background = 'rgba(239, 68, 68, 0.1)';
                                }
                            }}
                            onMouseLeave={(e) => {
                                e.currentTarget.style.background = 'transparent';
                            }}
                        >
                            <LogOut size={16} />
                            {isLoggingOut ? 'Signing out...' : 'Sign out'}
                        </button>
                    </div>
                </div>
            )}

            {/* Trigger Button */}
            <button
                onClick={() => setIsOpen(!isOpen)}
                data-testid="user-menu"
                style={{
                    display: 'flex',
                    width: '100%',
                    alignItems: 'center',
                    gap: '0.75rem',
                    padding: '0.625rem',
                    borderRadius: 'var(--radius)',
                    border: 'none',
                    background: isOpen ? 'var(--surface-hover)' : 'transparent',
                    cursor: 'pointer',
                    transition: 'all 0.2s',
                }}
                onMouseEnter={(e) => {
                    if (!isOpen) {
                        e.currentTarget.style.background = 'var(--surface-hover)';
                    }
                }}
                onMouseLeave={(e) => {
                    if (!isOpen) {
                        e.currentTarget.style.background = 'transparent';
                    }
                }}
            >
                {/* Avatar */}
                <div style={{
                    width: '36px',
                    height: '36px',
                    borderRadius: '8px',
                    background: 'var(--primary)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    color: 'white',
                    fontSize: '0.875rem',
                    fontWeight: 600,
                    flexShrink: 0,
                }}>
                    {initials}
                </div>

                {/* User Info */}
                <div style={{ flex: 1, minWidth: 0, textAlign: 'left' }}>
                    <div style={{
                        fontSize: '0.875rem',
                        fontWeight: 500,
                        color: 'var(--text)',
                        whiteSpace: 'nowrap',
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                    }}>
                        {displayName}
                    </div>
                    <div style={{
                        fontSize: '0.75rem',
                        color: 'var(--text-secondary)',
                        whiteSpace: 'nowrap',
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                    }}>
                        {user?.email}
                    </div>
                </div>

                {/* Chevron */}
                <ChevronUp
                    size={16}
                    style={{
                        color: 'var(--text-secondary)',
                        transition: 'transform 0.2s',
                        transform: isOpen ? 'rotate(180deg)' : 'rotate(0deg)',
                        flexShrink: 0,
                    }}
                />
            </button>
        </div>
    );
}
