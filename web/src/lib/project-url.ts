import type { Project } from '@/contexts/ProjectContext';

export function trimUrlInput(value: string | null | undefined): string {
    return (value || '').trim();
}

export function isHttpUrl(value: string | null | undefined): boolean {
    const url = trimUrlInput(value);
    if (!url) return false;

    try {
        const parsed = new URL(url);
        return (parsed.protocol === 'http:' || parsed.protocol === 'https:') && Boolean(parsed.hostname);
    } catch {
        return false;
    }
}

export function getProjectDefaultUrl(project: Pick<Project, 'base_url'> | null | undefined): string {
    return trimUrlInput(project?.base_url);
}

export function validateOptionalHttpUrl(value: string | null | undefined, label = 'URL'): string | null {
    const url = trimUrlInput(value);
    if (!url) return null;
    return isHttpUrl(url) ? null : `${label} must start with http:// or https://`;
}

export function applyProjectDefaultUrl(currentValue: string, nextDefaultUrl: string, previousDefaultUrl: string): string {
    const current = trimUrlInput(currentValue);
    const nextDefault = trimUrlInput(nextDefaultUrl);
    const previousDefault = trimUrlInput(previousDefaultUrl);

    if (!current || (previousDefault && current === previousDefault)) {
        return nextDefault;
    }

    return currentValue;
}
