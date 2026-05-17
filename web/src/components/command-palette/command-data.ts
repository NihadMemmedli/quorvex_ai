import {
    Home, FileText, Play, Settings, BarChart2, ClipboardList, FlaskConical,
    Compass, CheckSquare, Users, Shield, Zap, Activity, Database, BrainCircuit,
    TrendingUp, Clock, GitBranch, GitPullRequest, MessageSquare, Plus, Upload, Layers,
    Workflow, FolderOpen, Rocket, PieChart, Brain, Bot, MousePointerClick,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';

export interface CommandItem {
    id: string;
    label: string;
    icon: LucideIcon;
    href?: string;
    action?: string; // custom event name
    keywords: string[];
    category: 'quick-action' | 'navigation' | 'admin';
    group?: string;
    adminOnly?: boolean;
}

export const quickActions: CommandItem[] = [
    {
        id: 'start-autopilot',
        label: 'Start AutoPilot',
        icon: Rocket,
        href: '/autopilot',
        keywords: ['auto', 'autopilot', 'pilot', 'agent', 'automatic', 'start'],
        category: 'quick-action',
    },
    {
        id: 'create-spec',
        label: 'Create New Spec',
        icon: Plus,
        href: '/specs/new',
        keywords: ['create', 'new', 'spec', 'test', 'write'],
        category: 'quick-action',
    },
    {
        id: 'run-regression',
        label: 'Run Regression',
        icon: FlaskConical,
        href: '/regression',
        keywords: ['regression', 'batch', 'run', 'execute', 'suite'],
        category: 'quick-action',
    },
    {
        id: 'import-openapi',
        label: 'Import OpenAPI Spec',
        icon: Upload,
        href: '/api-testing',
        keywords: ['import', 'openapi', 'swagger', 'api', 'upload'],
        category: 'quick-action',
    },
    {
        id: 'run-security-scan',
        label: 'Run Security Scan',
        icon: Shield,
        href: '/security-testing',
        keywords: ['security', 'scan', 'vulnerability', 'zap', 'nuclei'],
        category: 'quick-action',
    },
    {
        id: 'open-ai-assistant',
        label: 'Open AI Assistant',
        icon: MessageSquare,
        action: 'open-ai-assistant',
        keywords: ['ai', 'assistant', 'chat', 'help', 'ask'],
        category: 'quick-action',
    },
];

export const navigationItems: CommandItem[] = [
    // Top-level
    { id: 'nav-overview', label: 'Overview', icon: Home, href: '/', keywords: ['home', 'overview', 'dashboard', 'main', 'command center'], category: 'navigation', group: 'Primary' },
    { id: 'nav-autopilot', label: 'AutoPilot', icon: Rocket, href: '/autopilot', keywords: ['auto', 'autopilot', 'pilot', 'agent', 'automatic'], category: 'navigation', group: 'Primary' },
    { id: 'nav-specs', label: 'Test Specs', icon: FileText, href: '/specs', keywords: ['specs', 'specifications', 'test', 'cases'], category: 'navigation', group: 'Primary' },
    { id: 'nav-runs', label: 'Test Runs', icon: Play, href: '/runs', keywords: ['runs', 'execution', 'results', 'test'], category: 'navigation', group: 'Primary' },
    { id: 'nav-reporting', label: 'Reporting', icon: BarChart2, href: '/dashboard', keywords: ['reporting', 'report', 'charts', 'data'], category: 'navigation', group: 'Primary' },
    { id: 'nav-projects', label: 'Projects', icon: FolderOpen, href: '/projects', keywords: ['projects', 'project', 'workspace'], category: 'navigation', group: 'Primary' },

    // Supporting workflows
    { id: 'nav-prd', label: 'PRD', icon: ClipboardList, href: '/prd', keywords: ['prd', 'product', 'requirements', 'document'], category: 'navigation', group: 'Supporting Workflows' },
    { id: 'nav-recordings', label: 'Recorder', icon: MousePointerClick, href: '/recordings', keywords: ['recorder', 'recording', 'browser', 'capture'], category: 'navigation', group: 'Supporting Workflows' },
    { id: 'nav-templates', label: 'Templates', icon: FileText, href: '/templates', keywords: ['templates', 'template', 'reusable', 'spec'], category: 'navigation', group: 'Supporting Workflows' },
    { id: 'nav-requirements', label: 'Requirements', icon: CheckSquare, href: '/requirements', keywords: ['requirements', 'req', 'rtm', 'traceability'], category: 'navigation', group: 'Supporting Workflows' },
    { id: 'nav-rtm', label: 'RTM', icon: GitBranch, href: '/rtm', keywords: ['rtm', 'traceability', 'matrix', 'requirements'], category: 'navigation', group: 'Supporting Workflows' },
    { id: 'nav-coverage', label: 'Coverage', icon: PieChart, href: '/coverage', keywords: ['coverage', 'traceability', 'gaps', 'quality'], category: 'navigation', group: 'Supporting Workflows' },
    { id: 'nav-regression', label: 'Regression', icon: FlaskConical, href: '/regression', keywords: ['regression', 'suite', 'batch'], category: 'navigation', group: 'Supporting Workflows' },
    { id: 'nav-batches', label: 'Batch Reports', icon: Layers, href: '/regression/batches', keywords: ['batch', 'reports', 'regression'], category: 'navigation', group: 'Supporting Workflows' },

    // Advanced tools
    { id: 'nav-workflow', label: 'Workflow Monitor', icon: Workflow, href: '/workflow', keywords: ['ai', 'workflow', 'workflows', 'automation', 'pipeline'], category: 'navigation', group: 'Advanced Tools' },
    { id: 'nav-exploration', label: 'Discovery', icon: Compass, href: '/exploration', keywords: ['discovery', 'exploration', 'explore', 'crawl'], category: 'navigation', group: 'Advanced Tools' },
    { id: 'nav-api-testing', label: 'API Testing', icon: Zap, href: '/api-testing', keywords: ['api', 'rest', 'http', 'endpoint'], category: 'navigation', group: 'Advanced Tools' },
    { id: 'nav-load-testing', label: 'Load Testing', icon: Activity, href: '/load-testing', keywords: ['load', 'performance', 'k6', 'stress'], category: 'navigation', group: 'Advanced Tools' },
    { id: 'nav-security', label: 'Security Testing', icon: Shield, href: '/security-testing', keywords: ['security', 'vulnerability', 'scan', 'zap'], category: 'navigation', group: 'Advanced Tools' },
    { id: 'nav-database', label: 'Database Testing', icon: Database, href: '/database-testing', keywords: ['database', 'db', 'sql', 'query'], category: 'navigation', group: 'Advanced Tools' },
    { id: 'nav-llm', label: 'LLM Testing', icon: BrainCircuit, href: '/llm-testing', keywords: ['llm', 'ai', 'model', 'prompt'], category: 'navigation', group: 'Advanced Tools' },
    { id: 'nav-analytics', label: 'Analytics', icon: TrendingUp, href: '/analytics', keywords: ['analytics', 'trends', 'flake', 'insights'], category: 'navigation', group: 'Advanced Tools' },
    { id: 'nav-schedules', label: 'Schedules', icon: Clock, href: '/schedules', keywords: ['schedule', 'cron', 'timer', 'recurring'], category: 'navigation', group: 'Advanced Tools' },
    { id: 'nav-cicd', label: 'CI/CD', icon: GitBranch, href: '/ci-cd', keywords: ['cicd', 'ci', 'cd', 'pipeline', 'github', 'gitlab'], category: 'navigation', group: 'Advanced Tools' },
    { id: 'nav-pr-advisor', label: 'PR Advisor', icon: GitPullRequest, href: '/pr-advisor', keywords: ['pr', 'pull request', 'advisor', 'impact', 'test selection', 'github'], category: 'navigation', group: 'Advanced Tools' },
    { id: 'nav-memory', label: 'Memory', icon: Brain, href: '/memory', keywords: ['memory', 'semantic', 'patterns', 'knowledge'], category: 'navigation', group: 'Advanced Tools' },
    { id: 'nav-agents', label: 'Agents', icon: Bot, href: '/agents', keywords: ['agents', 'agent', 'worker', 'automation'], category: 'navigation', group: 'Advanced Tools' },
    { id: 'nav-assistant', label: 'AI Assistant', icon: MessageSquare, href: '/assistant', keywords: ['ai', 'assistant', 'chat'], category: 'navigation', group: 'Advanced Tools' },

    // Settings
    { id: 'nav-settings', label: 'Settings', icon: Settings, href: '/settings', keywords: ['settings', 'config', 'preferences'], category: 'navigation', group: 'Settings' },
];

export const adminItems: CommandItem[] = [
    { id: 'admin-users', label: 'User Management', icon: Users, href: '/admin/users', keywords: ['users', 'admin', 'manage', 'accounts'], category: 'admin', adminOnly: true },
];

/** Get all command items, optionally including admin items */
export function getAllCommands(isSuperuser: boolean): CommandItem[] {
    const items = [...quickActions, ...navigationItems];
    if (isSuperuser) {
        items.push(...adminItems);
    }
    return items;
}

/** Simple fuzzy match: check if query words appear in label or keywords */
export function matchesQuery(item: CommandItem, query: string): boolean {
    const q = query.toLowerCase().trim();
    if (!q) return true;
    const searchable = [item.label.toLowerCase(), ...item.keywords].join(' ');
    return q.split(/\s+/).every(word => searchable.includes(word));
}
