/**
 * Shared formatting utilities used across testing module pages.
 */

export function parseDateMs(dateStr?: string | null): number | null {
    if (!dateStr) return null;
    const trimmed = dateStr.trim();
    if (!trimmed) return null;
    const hasTimezone = /(?:z|[+-]\d{2}:?\d{2})$/i.test(trimmed);
    const normalized = hasTimezone ? trimmed : `${trimmed}Z`;
    const parsed = new Date(normalized).getTime();
    if (Number.isFinite(parsed)) return parsed;
    const fallback = new Date(trimmed).getTime();
    return Number.isFinite(fallback) ? fallback : null;
}

export function timeAgo(dateStr: string): string {
    const now = Date.now();
    const then = parseDateMs(dateStr);
    if (then === null) return '-';
    const diff = Math.max(0, now - then);
    const seconds = Math.floor(diff / 1000);
    if (seconds < 10) return 'just now';
    if (seconds < 60) return `${seconds}s ago`;
    const minutes = Math.floor(seconds / 60);
    if (minutes < 60) return `${minutes}m ago`;
    const hours = Math.floor(minutes / 60);
    if (hours < 24) return `${hours}h ago`;
    const days = Math.floor(hours / 24);
    return `${days}d ago`;
}

export function formatDate(dateStr: string): string {
    const parsed = parseDateMs(dateStr);
    return parsed === null ? '-' : new Date(parsed).toLocaleString();
}

export function formatDuration(seconds?: number): string {
    if (!seconds) return '-';
    if (seconds < 60) return `${Math.round(seconds)}s`;
    const min = Math.floor(seconds / 60);
    const sec = Math.round(seconds % 60);
    return `${min}m ${sec}s`;
}

export function formatBytes(bytes: number): string {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
}

export function formatTimestamp(ts: string): string {
    const parsed = parseDateMs(ts);
    if (parsed === null) return '-';
    const d = new Date(parsed);
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}
