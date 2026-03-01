import type { LucideIcon } from 'lucide-react';
import { Compass, CheckSquare, GitBranch, FileText, Play, TrendingUp } from 'lucide-react';

export interface WorkflowNode {
    id: string;
    label: string;
    shortLabel: string;
    href: string;
    icon: LucideIcon;
    color: string;
}

export interface WorkflowEdge {
    from: string;
    to: string;
}

export interface NextStep {
    label: string;
    href: string;
    description: string;
}

/** Core pipeline nodes */
export const pipelineNodes: WorkflowNode[] = [
    { id: 'exploration', label: 'Exploration', shortLabel: 'Explore', href: '/exploration', icon: Compass, color: '#8b5cf6' },
    { id: 'requirements', label: 'Requirements', shortLabel: 'Reqs', href: '/requirements', icon: CheckSquare, color: '#f59e0b' },
    { id: 'rtm', label: 'RTM', shortLabel: 'RTM', href: '/requirements?tab=rtm', icon: GitBranch, color: '#06b6d4' },
    { id: 'specs', label: 'Test Specs', shortLabel: 'Specs', href: '/specs', icon: FileText, color: '#3b82f6' },
    { id: 'runs', label: 'Test Runs', shortLabel: 'Runs', href: '/runs', icon: Play, color: '#10b981' },
    { id: 'analytics', label: 'Analytics', shortLabel: 'Analytics', href: '/analytics', icon: TrendingUp, color: '#ec4899' },
];

export const pipelineEdges: WorkflowEdge[] = [
    { from: 'exploration', to: 'requirements' },
    { from: 'requirements', to: 'rtm' },
    { from: 'rtm', to: 'specs' },
    { from: 'specs', to: 'runs' },
    { from: 'runs', to: 'analytics' },
];

/** Map pathname to pipeline node id */
export function getNodeForPath(pathname: string): string | null {
    if (pathname === '/exploration') return 'exploration';
    if (pathname === '/requirements') return 'requirements';
    if (pathname === '/specs' || pathname.startsWith('/specs/')) return 'specs';
    if (pathname === '/runs' || pathname.startsWith('/runs/')) return 'runs';
    if (pathname === '/analytics') return 'analytics';
    return null;
}

/** Get contextual next steps for a given pathname */
export function getNextSteps(pathname: string): NextStep[] {
    const node = getNodeForPath(pathname);

    switch (node) {
        case 'exploration':
            return [
                { label: 'Generate Requirements', href: '/requirements', description: 'Extract structured requirements from exploration data' },
            ];
        case 'requirements':
            return [
                { label: 'Build RTM', href: '/requirements?tab=rtm', description: 'Map requirements to test coverage' },
                { label: 'Create Test Specs', href: '/specs/new', description: 'Write test specifications from requirements' },
            ];
        case 'specs':
            return [
                { label: 'Run Tests', href: '/runs', description: 'Execute your test specifications' },
            ];
        case 'runs':
            return [
                { label: 'View Analytics', href: '/analytics', description: 'Analyze test results and trends' },
                { label: 'Schedule Regression', href: '/schedules', description: 'Set up recurring test runs' },
            ];
        default:
            return [];
    }
}

/** Get node by id */
export function getNodeById(id: string): WorkflowNode | undefined {
    return pipelineNodes.find(n => n.id === id);
}
