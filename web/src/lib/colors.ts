/**
 * Shared color utilities for severity levels, statuses, and metric thresholds.
 * Uses design system tokens where applicable.
 */

const SEVERITY_COLORS: Record<string, string> = {
    critical: '#f87171',
    high: '#fb923c',
    medium: '#fbbf24',
    low: '#3b82f6',
    info: '#7e8ba8',
};

const SEVERITY_BG_COLORS: Record<string, string> = {
    critical: 'rgba(248, 113, 113, 0.12)',
    high: 'rgba(251, 146, 60, 0.12)',
    medium: 'rgba(251, 191, 36, 0.12)',
    low: 'rgba(59, 130, 246, 0.12)',
    info: 'rgba(126, 139, 168, 0.12)',
};

const STATUS_COLORS: Record<string, string> = {
    pending: '#7e8ba8',
    running: '#3b82f6',
    completed: '#34d399',
    failed: '#f87171',
    passed: '#34d399',
    error: '#fb923c',
    cancelled: '#c084fc',
};

export function severityColor(severity: string): string {
    return SEVERITY_COLORS[severity?.toLowerCase()] || '#7e8ba8';
}

export function severityBg(severity: string): string {
    return SEVERITY_BG_COLORS[severity?.toLowerCase()] || 'rgba(126, 139, 168, 0.12)';
}

export function statusColor(status: string): string {
    return STATUS_COLORS[status?.toLowerCase()] || '#7e8ba8';
}

export function getResponseTimeColor(ms: number): string {
    if (ms < 200) return '#34d399';
    if (ms < 500) return '#fbbf24';
    return '#f87171';
}

export function getErrorRateColor(rate: number): string {
    if (rate < 1) return '#34d399';
    if (rate < 5) return '#fbbf24';
    return '#f87171';
}

export function getStatusColor(code: string): string {
    if (code.startsWith('2')) return '#34d399';
    if (code.startsWith('3')) return '#3b82f6';
    if (code.startsWith('4')) return '#fbbf24';
    if (code.startsWith('5')) return '#f87171';
    return '#7e8ba8';
}
