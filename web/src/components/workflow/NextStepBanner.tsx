'use client';

import React, { useState, useCallback } from 'react';
import { usePathname, useRouter } from 'next/navigation';
import { ArrowRight, X } from 'lucide-react';
import { getNextSteps } from '@/lib/workflow';

const DISMISS_PREFIX = 'nextstep-dismissed-';
const DISMISS_TTL = 24 * 60 * 60 * 1000; // 24 hours

function isDismissedInStorage(path: string): boolean {
    if (typeof window === 'undefined') return false;
    try {
        const stored = localStorage.getItem(`${DISMISS_PREFIX}${path}`);
        if (!stored) return false;
        const timestamp = parseInt(stored, 10);
        if (Date.now() - timestamp > DISMISS_TTL) {
            localStorage.removeItem(`${DISMISS_PREFIX}${path}`);
            return false;
        }
        return true;
    } catch {
        return false;
    }
}

function dismissInStorage(path: string): void {
    if (typeof window === 'undefined') return;
    try {
        localStorage.setItem(`${DISMISS_PREFIX}${path}`, String(Date.now()));
    } catch {
        // Ignore storage errors
    }
}

export function NextStepBanner() {
    const pathname = usePathname();
    const router = useRouter();
    const [dismissed, setDismissed] = useState(() => isDismissedInStorage(pathname));

    const nextSteps = getNextSteps(pathname);

    const handleDismiss = useCallback(() => {
        dismissInStorage(pathname);
        setDismissed(true);
    }, [pathname]);

    if (nextSteps.length === 0 || dismissed) {
        return null;
    }

    return (
        <div style={{
            display: 'flex',
            alignItems: 'center',
            gap: '0.75rem',
            padding: '0.5rem 0.75rem',
            marginBottom: '1rem',
            borderRadius: 'var(--radius)',
            background: 'rgba(59, 130, 246, 0.05)',
            border: '1px solid rgba(59, 130, 246, 0.15)',
            fontSize: '0.8rem',
        }}>
            <span style={{ color: 'var(--text-secondary)', whiteSpace: 'nowrap' }}>Next:</span>
            <div style={{ display: 'flex', gap: '0.5rem', flex: 1, overflow: 'auto' }}>
                {nextSteps.map(step => (
                    <button
                        key={step.href}
                        onClick={() => router.push(step.href)}
                        style={{
                            display: 'flex',
                            alignItems: 'center',
                            gap: '0.35rem',
                            padding: '0.25rem 0.6rem',
                            borderRadius: '6px',
                            background: 'rgba(59, 130, 246, 0.1)',
                            color: 'var(--primary)',
                            fontWeight: 500,
                            fontSize: '0.8rem',
                            cursor: 'pointer',
                            whiteSpace: 'nowrap',
                            transition: 'background 0.15s',
                        }}
                        onMouseOver={e => { e.currentTarget.style.background = 'rgba(59, 130, 246, 0.2)'; }}
                        onMouseOut={e => { e.currentTarget.style.background = 'rgba(59, 130, 246, 0.1)'; }}
                        title={step.description}
                    >
                        {step.label}
                        <ArrowRight size={12} />
                    </button>
                ))}
            </div>
            <button
                onClick={handleDismiss}
                style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    width: '20px',
                    height: '20px',
                    borderRadius: '4px',
                    color: 'var(--text-secondary)',
                    cursor: 'pointer',
                    flexShrink: 0,
                }}
            >
                <X size={12} />
            </button>
        </div>
    );
}
