'use client';

import { useState, useEffect, useCallback } from 'react';
import { fetchWithAuth } from '@/contexts/AuthContext';
import { API_BASE } from '@/lib/api';

export type ProjectRole = 'admin' | 'editor' | 'viewer' | null;

interface ProjectRoleInfo {
    project_id: string;
    user_id: string | null;
    role: ProjectRole;
    is_superuser: boolean;
    auth_required: boolean;
}

interface UseProjectRoleResult {
    role: ProjectRole;
    isSuperuser: boolean;
    isAdmin: boolean;
    isEditor: boolean;
    isViewer: boolean;
    canEdit: boolean;
    canManageMembers: boolean;
    isLoading: boolean;
    error: string | null;
    refetch: () => Promise<void>;
}

/**
 * Hook to get the current user's role in a specific project.
 *
 * @param projectId - The project ID to check role for
 * @returns Role information and permission flags
 *
 * Usage:
 * ```tsx
 * const { role, canEdit, canManageMembers, isLoading } = useProjectRole(projectId);
 *
 * if (isLoading) return <Spinner />;
 * if (!canEdit) return <ReadOnlyView />;
 * return <EditorView />;
 * ```
 */
export function useProjectRole(projectId: string | null): UseProjectRoleResult {
    const [roleInfo, setRoleInfo] = useState<ProjectRoleInfo | null>(null);
    const [isLoading, setIsLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    const fetchRole = useCallback(async () => {
        if (!projectId) {
            setRoleInfo(null);
            setIsLoading(false);
            return;
        }

        setIsLoading(true);
        setError(null);

        try {
            const response = await fetchWithAuth(
                `${API_BASE}/projects/${projectId}/my-role`
            );

            if (!response.ok) {
                if (response.status === 404) {
                    setError('Project not found');
                } else {
                    setError('Failed to fetch role');
                }
                setRoleInfo(null);
                return;
            }

            const data: ProjectRoleInfo = await response.json();
            setRoleInfo(data);
        } catch (err) {
            console.error('Failed to fetch project role:', err);
            setError(err instanceof Error ? err.message : 'Failed to fetch role');
            setRoleInfo(null);
        } finally {
            setIsLoading(false);
        }
    }, [projectId]);

    useEffect(() => {
        fetchRole();
    }, [fetchRole]);

    const role = roleInfo?.role ?? null;
    const isSuperuser = roleInfo?.is_superuser ?? false;

    return {
        role,
        isSuperuser,
        isAdmin: role === 'admin' || isSuperuser,
        isEditor: role === 'editor',
        isViewer: role === 'viewer',
        canEdit: role === 'admin' || role === 'editor' || isSuperuser,
        canManageMembers: role === 'admin' || isSuperuser,
        isLoading,
        error,
        refetch: fetchRole,
    };
}

/**
 * Hook to manage project members.
 *
 * @param projectId - The project ID to manage members for
 */
export function useProjectMembers(projectId: string | null) {
    const [members, setMembers] = useState<ProjectMember[]>([]);
    const [isLoading, setIsLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);

    const fetchMembers = useCallback(async () => {
        if (!projectId) {
            setMembers([]);
            return;
        }

        setIsLoading(true);
        setError(null);

        try {
            const response = await fetchWithAuth(
                `${API_BASE}/projects/${projectId}/members`
            );

            if (!response.ok) {
                throw new Error('Failed to fetch members');
            }

            const data = await response.json();
            setMembers(data);
        } catch (err) {
            console.error('Failed to fetch members:', err);
            setError(err instanceof Error ? err.message : 'Failed to fetch members');
        } finally {
            setIsLoading(false);
        }
    }, [projectId]);

    useEffect(() => {
        fetchMembers();
    }, [fetchMembers]);

    const addMember = async (email: string, role: ProjectRole = 'viewer') => {
        if (!projectId) return;

        const response = await fetchWithAuth(
            `${API_BASE}/projects/${projectId}/members`,
            {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ email, role }),
            }
        );

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to add member');
        }

        await fetchMembers();
        return response.json();
    };

    const updateMemberRole = async (userId: string, role: ProjectRole) => {
        if (!projectId) return;

        const response = await fetchWithAuth(
            `${API_BASE}/projects/${projectId}/members/${userId}`,
            {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ role }),
            }
        );

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to update role');
        }

        await fetchMembers();
        return response.json();
    };

    const removeMember = async (userId: string) => {
        if (!projectId) return;

        const response = await fetchWithAuth(
            `${API_BASE}/projects/${projectId}/members/${userId}`,
            {
                method: 'DELETE',
            }
        );

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to remove member');
        }

        await fetchMembers();
    };

    return {
        members,
        isLoading,
        error,
        refetch: fetchMembers,
        addMember,
        updateMemberRole,
        removeMember,
    };
}

export interface ProjectMember {
    user_id: string;
    email: string;
    full_name: string | null;
    role: ProjectRole;
    granted_at: string;
    granted_by: string | null;
}
