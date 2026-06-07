import { API_BASE } from '@/lib/api';
import { getAuthHeaders } from '@/lib/styles';

export interface BrowserAuthSession {
    id: string;
    name: string;
    status: string;
    is_default: boolean;
}

export async function fetchProjectBrowserAuthSessions(projectId: string): Promise<BrowserAuthSession[]> {
    const res = await fetch(`${API_BASE}/projects/${encodeURIComponent(projectId)}/browser-auth-sessions`, {
        headers: getAuthHeaders(),
    });
    if (!res.ok) {
        throw new Error('Failed to load browser login sessions');
    }
    const data = await res.json();
    return data.sessions || [];
}

export function isBrowserAuthSessionSelectable(session: BrowserAuthSession) {
    return session.status === 'active';
}

export function browserAuthSessionLabel(session: BrowserAuthSession) {
    const status = session.status ? session.status.replace(/_/g, ' ') : 'unknown';
    const suffix = session.is_default ? `Default, ${status}` : status;
    return `${session.name || session.id} (${suffix})`;
}
