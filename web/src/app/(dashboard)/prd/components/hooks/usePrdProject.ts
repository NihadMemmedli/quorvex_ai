'use client';

import { useState, useEffect, useCallback } from 'react';
import { API_BASE } from '@/lib/api';
import { useProject } from '@/contexts/ProjectContext';
import type { Feature, ExistingProject, ProjectInfo } from '../types';

const API = `${API_BASE}/api`;

export function usePrdProject() {
    const { currentProject, isLoading: projectLoading } = useProject();

    const [existingProjects, setExistingProjects] = useState<ExistingProject[]>([]);
    const [projectData, setProjectData] = useState<ProjectInfo | null>(null);
    const [isUploading, setIsUploading] = useState(false);
    const [error, setError] = useState('');

    // Fetch project list
    const fetchProjects = useCallback(async () => {
        if (projectLoading) return;
        try {
            let url = `${API}/prd/projects`;
            if (currentProject?.id) url += `?project_id=${encodeURIComponent(currentProject.id)}`;
            const res = await fetch(url);
            const data = await res.json();
            if (Array.isArray(data)) setExistingProjects(data);
        } catch (err) {
            console.error('Failed to fetch projects:', err);
        }
    }, [currentProject?.id, projectLoading]);

    useEffect(() => {
        if (!projectLoading) fetchProjects();
    }, [fetchProjects]);

    // Upload PDF
    const upload = useCallback(async (file: File, targetFeatures: number): Promise<ProjectInfo | null> => {
        setIsUploading(true);
        setError('');
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 600000);
        try {
            let url = `${API}/prd/upload?target_features=${targetFeatures}`;
            if (currentProject?.id) url += `&tenant_project_id=${encodeURIComponent(currentProject.id)}`;
            const formData = new FormData();
            formData.append('file', file);
            const res = await fetch(url, { method: 'POST', body: formData, signal: controller.signal });
            clearTimeout(timeoutId);
            if (!res.ok) {
                const d = await res.json();
                throw new Error(d.detail || 'Upload failed');
            }
            const data = await res.json();
            const info: ProjectInfo = {
                project: data.project,
                features: data.features || [],
                total_chunks: data.total_chunks || 0,
            };
            setProjectData(info);
            await fetchProjects();
            return info;
        } catch (err: any) {
            if (err.name === 'AbortError') setError('Processing timed out after 10 minutes.');
            else setError(err.message || 'Failed to process PDF');
            return null;
        } finally {
            clearTimeout(timeoutId);
            setIsUploading(false);
        }
    }, [currentProject?.id, fetchProjects]);

    // Load existing project
    const loadProject = useCallback(async (projectId: string) => {
        setError('');
        try {
            const res = await fetch(`${API}/prd/${projectId}/features`);
            if (!res.ok) throw new Error('Failed to load');
            const data = await res.json();
            setProjectData({
                project: projectId,
                features: data.features || [],
                total_chunks: 0,
            });
        } catch (e: any) {
            setError(e.message || 'Failed to load project');
        }
    }, []);

    // Delete project
    const deleteProject = useCallback(async (projectId: string) => {
        try {
            const res = await fetch(`${API}/prd/${projectId}`, { method: 'DELETE' });
            if (!res.ok) {
                const d = await res.json();
                throw new Error(d.detail || 'Delete failed');
            }
            setExistingProjects(prev => prev.filter(p => p.project !== projectId));
        } catch (err: any) {
            setError(err.message || 'Failed to delete project');
        }
    }, []);

    // Update requirements for a specific feature in local state (avoids full re-fetch)
    const updateFeatureRequirements = useCallback((featureSlug: string, newRequirements: string[]) => {
        setProjectData(prev => {
            if (!prev) return prev;
            return {
                ...prev,
                features: prev.features.map(f =>
                    f.slug === featureSlug ? { ...f, requirements: newRequirements } : f
                ),
            };
        });
    }, []);

    // Reset
    const reset = useCallback(() => {
        setProjectData(null);
        setError('');
    }, []);

    const testableFeatures = (projectData?.features || []).filter(
        (f: Feature) => f.requirements?.length > 0
    );

    return {
        existingProjects,
        projectData,
        testableFeatures,
        isUploading,
        error,
        setError,
        upload,
        loadProject,
        deleteProject,
        updateFeatureRequirements,
        reset,
        fetchProjects,
    };
}
