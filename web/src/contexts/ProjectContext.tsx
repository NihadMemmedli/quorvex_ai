'use client';

import React, { createContext, useContext, useState, useEffect, useCallback, ReactNode } from 'react';
import { fetchWithAuth, useAuth } from './AuthContext';
import { API_BASE } from '@/lib/api';

export interface Project {
    id: string;
    name: string;
    base_url?: string;
    description?: string;
    created_at: string;
    last_active?: string;
    spec_count: number;
    run_count: number;
    batch_count: number;
}

interface ProjectContextType {
    currentProject: Project | null;
    projects: Project[];
    isLoading: boolean;
    error: string | null;
    setCurrentProject: (project: Project | null) => void;
    refreshProjects: () => Promise<Project[]>;
    createProject: (name: string, description?: string, base_url?: string) => Promise<Project>;
    updateProject: (id: string, updates: { name?: string; description?: string; base_url?: string }) => Promise<Project>;
    deleteProject: (id: string) => Promise<void>;
}

const ProjectContext = createContext<ProjectContextType | undefined>(undefined);

const STORAGE_KEY = 'we-test-current-project-id';

export function ProjectProvider({ children }: { children: ReactNode }) {
    const { user, isLoading: authLoading } = useAuth();
    const [projects, setProjects] = useState<Project[]>([]);
    const [currentProject, setCurrentProjectState] = useState<Project | null>(null);
    const [isLoading, setIsLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    // Fetch projects from API (with auth token for filtering by membership)
    const refreshProjects = useCallback(async () => {
        try {
            setError(null);
            const response = await fetchWithAuth(`${API_BASE}/projects`);
            if (!response.ok) {
                throw new Error('Failed to fetch projects');
            }
            const data = await response.json();
            setProjects(data.projects);
            return data.projects as Project[];
        } catch (err) {
            console.error('Error fetching projects:', err);
            setError(err instanceof Error ? err.message : 'Failed to fetch projects');
            return [];
        }
    }, []);

    // Set current project and persist to localStorage
    const setCurrentProject = useCallback((project: Project | null) => {
        setCurrentProjectState(project);
        if (project) {
            localStorage.setItem(STORAGE_KEY, project.id);
        } else {
            localStorage.removeItem(STORAGE_KEY);
        }
    }, []);

    // Create a new project
    const createProject = useCallback(async (name: string, description?: string, base_url?: string): Promise<Project> => {
        const response = await fetchWithAuth(`${API_BASE}/projects`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name, description, base_url })
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to create project');
        }

        const newProject = await response.json();
        await refreshProjects();
        return newProject;
    }, [refreshProjects]);

    // Update a project
    const updateProject = useCallback(async (
        id: string,
        updates: { name?: string; description?: string; base_url?: string }
    ): Promise<Project> => {
        const response = await fetchWithAuth(`${API_BASE}/projects/${id}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(updates)
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to update project');
        }

        const updatedProject = await response.json();
        await refreshProjects();

        // Update current project if it was the one being edited
        if (currentProject?.id === id) {
            setCurrentProjectState(updatedProject);
        }

        return updatedProject;
    }, [currentProject, refreshProjects]);

    // Delete a project
    const deleteProject = useCallback(async (id: string): Promise<void> => {
        const response = await fetchWithAuth(`${API_BASE}/projects/${id}`, {
            method: 'DELETE'
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to delete project');
        }

        // If deleted project was current, switch to default
        if (currentProject?.id === id) {
            const remaining = await refreshProjects();
            const defaultProject = remaining.find(p => p.id === 'default') || remaining[0];
            if (defaultProject) {
                setCurrentProject(defaultProject);
            }
        } else {
            await refreshProjects();
        }
    }, [currentProject, refreshProjects, setCurrentProject]);

    // Initialize on mount and re-fetch when auth state changes
    useEffect(() => {
        // Wait for auth to finish loading before fetching projects
        if (authLoading) {
            return;
        }

        async function initialize() {
            setIsLoading(true);
            try {
                const fetchedProjects = await refreshProjects();

                // Restore saved project from localStorage
                const savedProjectId = localStorage.getItem(STORAGE_KEY);
                let projectToSelect: Project | null = null;

                if (savedProjectId) {
                    projectToSelect = fetchedProjects.find(p => p.id === savedProjectId) || null;
                }

                // Fall back to default project if saved one not found
                if (!projectToSelect) {
                    projectToSelect = fetchedProjects.find(p => p.id === 'default') || fetchedProjects[0] || null;
                }

                if (projectToSelect) {
                    setCurrentProjectState(projectToSelect);
                    localStorage.setItem(STORAGE_KEY, projectToSelect.id);
                } else {
                    // No projects available - clear selection
                    setCurrentProjectState(null);
                    localStorage.removeItem(STORAGE_KEY);
                }
            } catch (err) {
                console.error('Error initializing projects:', err);
            } finally {
                setIsLoading(false);
            }
        }

        initialize();
    }, [authLoading, user?.id, refreshProjects]); // Re-run when auth loads or user changes

    return (
        <ProjectContext.Provider
            value={{
                currentProject,
                projects,
                isLoading,
                error,
                setCurrentProject,
                refreshProjects,
                createProject,
                updateProject,
                deleteProject
            }}
        >
            {children}
        </ProjectContext.Provider>
    );
}

export function useProject() {
    const context = useContext(ProjectContext);
    if (context === undefined) {
        throw new Error('useProject must be used within a ProjectProvider');
    }
    return context;
}
