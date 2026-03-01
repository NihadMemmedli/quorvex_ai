/**
 * Shared style constants and factory functions.
 * Module-level objects avoid re-creation on every render.
 */
import type { CSSProperties } from 'react';

export const cardStyle: CSSProperties = {
    background: 'var(--surface)',
    border: '1px solid var(--border-subtle)',
    borderRadius: 'var(--radius-lg)',
    padding: '1.5rem',
    boxShadow: 'var(--shadow-card)',
    transition: 'all 0.2s var(--ease-smooth)',
};

export const cardStyleCompact: CSSProperties = {
    padding: '1rem',
    background: 'var(--surface)',
    border: '1px solid var(--border-subtle)',
    borderRadius: 'var(--radius)',
    marginBottom: '0.75rem',
    boxShadow: 'var(--shadow-card)',
    transition: 'all 0.2s var(--ease-smooth)',
};

export const inputStyle: CSSProperties = {
    width: '100%',
    padding: '0.5rem 0.75rem',
    borderRadius: 'var(--radius)',
    border: '1px solid var(--border)',
    background: 'var(--background-raised)',
    color: 'var(--text)',
    fontSize: '0.9rem',
    transition: 'all 0.2s var(--ease-smooth)',
    outline: 'none',
};

export const btnPrimary: CSSProperties = {
    padding: '0.5rem 1rem',
    background: 'var(--primary)',
    color: 'white',
    border: 'none',
    borderRadius: 'var(--radius)',
    cursor: 'pointer',
    fontWeight: 600,
    fontSize: '0.85rem',
    display: 'flex',
    alignItems: 'center',
    gap: '0.5rem',
    transition: 'all 0.2s var(--ease-smooth)',
};

export const btnSecondary: CSSProperties = {
    padding: '0.5rem 1rem',
    background: 'transparent',
    color: 'var(--text)',
    border: '1px solid var(--border)',
    borderRadius: 'var(--radius)',
    cursor: 'pointer',
    fontWeight: 500,
    fontSize: '0.85rem',
    display: 'flex',
    alignItems: 'center',
    gap: '0.5rem',
    transition: 'all 0.2s var(--ease-smooth)',
};

export const btnSmall: CSSProperties = {
    padding: '0.25rem 0.5rem',
    background: 'none',
    border: '1px solid var(--border)',
    borderRadius: 'var(--radius-sm)',
    cursor: 'pointer',
    fontSize: '0.8rem',
    color: 'var(--text-secondary)',
    transition: 'all 0.2s var(--ease-smooth)',
};

export const labelStyle: CSSProperties = {
    display: 'block',
    fontSize: '0.85rem',
    fontWeight: 500,
    marginBottom: '0.25rem',
    color: 'var(--text)',
};

export const thStyle: CSSProperties = {
    padding: '0.5rem 0.75rem',
    textAlign: 'left' as const,
    borderBottom: '2px solid var(--border-subtle)',
    fontWeight: 600,
    background: 'var(--surface)',
    color: 'var(--text-secondary)',
};

export const tdStyle: CSSProperties = {
    padding: '0.5rem 0.75rem',
    borderBottom: '1px solid var(--border-subtle)',
    verticalAlign: 'top' as const,
};

export function createTabStyle(activeTab: string, tab: string): CSSProperties {
    const isActive = activeTab === tab;
    return {
        padding: '0.75rem 1.5rem',
        cursor: 'pointer',
        borderTop: 'none',
        borderRight: 'none',
        borderLeft: 'none',
        borderBottom: isActive ? '2px solid var(--primary)' : '2px solid transparent',
        color: isActive ? 'var(--text)' : 'var(--text-secondary)',
        fontWeight: isActive ? 600 : 400,
        background: 'transparent',
        fontSize: '0.9rem',
        transition: 'all 0.2s var(--ease-smooth)',
    };
}

export function getAuthHeaders(): Record<string, string> {
    const token = typeof window !== 'undefined' ? localStorage.getItem('auth_token') : null;
    return token ? { 'Authorization': `Bearer ${token}` } : {};
}
