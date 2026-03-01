'use client';

import type { ReactNode, CSSProperties } from 'react';

type LayoutTier = 'narrow' | 'standard' | 'wide' | 'full';

interface PageLayoutProps {
    tier?: LayoutTier;
    children: ReactNode;
    className?: string;
    style?: CSSProperties;
}

const tierClasses: Record<LayoutTier, string> = {
    narrow: 'page-narrow',
    standard: 'page-standard',
    wide: 'page-wide',
    full: 'page-full',
};

/**
 * Standardized page layout wrapper with width tiers.
 * - narrow: 800px (settings, forms, templates)
 * - standard: 1200px (most pages — specs, runs, requirements)
 * - wide: 1400px (dashboards, analytics, data-heavy pages)
 * - full: 100% (special layouts)
 *
 * Note: The dashboard layout already provides 2rem padding,
 * so this component does NOT add extra padding.
 */
export function PageLayout({
    tier = 'standard',
    children,
    className = '',
    style,
}: PageLayoutProps) {
    return (
        <div
            className={`${tierClasses[tier]} ${className}`}
            style={{ paddingTop: '0.5rem', ...style }}
        >
            {children}
        </div>
    );
}
