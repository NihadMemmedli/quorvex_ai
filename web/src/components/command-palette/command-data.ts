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

interface RankedCommand<T extends CommandItem> {
    item: T;
    score: number;
    index: number;
}

export const quickActions: CommandItem[] = [
    {
        id: 'start-autopilot',
        label: 'Start AutoPilot',
        icon: Rocket,
        href: '/autopilot',
        keywords: ['auto', 'autopilot', 'pilot', 'agent', 'automatic', 'start', 'mission', 'missions', 'agent runs'],
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
        keywords: ['regression', 'batch', 'batches', 'run', 'execute', 'suite'],
        category: 'quick-action',
    },
    {
        id: 'import-openapi',
        label: 'Import OpenAPI Spec',
        icon: Upload,
        href: '/api-testing',
        keywords: ['import', 'openapi', 'open api', 'swagger', 'api', 'upload'],
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
    { id: 'nav-autonomous', label: 'Autonomous', icon: Bot, href: '/autonomous', keywords: ['autonomous', 'agent', 'agents', 'missions', 'mission', 'agent runs', 'agent run', 'autonomous agents'], category: 'navigation', group: 'Primary' },
    { id: 'nav-specs', label: 'Test Specs', icon: FileText, href: '/specs', keywords: ['specs', 'specifications', 'test', 'cases'], category: 'navigation', group: 'Primary' },
    { id: 'nav-runs', label: 'Test Runs', icon: Play, href: '/runs', keywords: ['runs', 'execution', 'results', 'test'], category: 'navigation', group: 'Primary' },
    { id: 'nav-reporting', label: 'Reporting', icon: BarChart2, href: '/dashboard', keywords: ['reporting', 'report', 'charts', 'data'], category: 'navigation', group: 'Primary' },
    { id: 'nav-projects', label: 'Projects', icon: FolderOpen, href: '/projects', keywords: ['projects', 'project', 'workspace'], category: 'navigation', group: 'Primary' },

    // Supporting workflows
    { id: 'nav-prd', label: 'PRD', icon: ClipboardList, href: '/prd', keywords: ['prd', 'product', 'requirements', 'document'], category: 'navigation', group: 'Supporting Workflows' },
    { id: 'nav-recordings', label: 'Recorder', icon: MousePointerClick, href: '/recordings', keywords: ['recorder', 'recording', 'browser', 'capture'], category: 'navigation', group: 'Supporting Workflows' },
    { id: 'nav-templates', label: 'Templates', icon: FileText, href: '/templates', keywords: ['templates', 'template', 'reusable', 'spec'], category: 'navigation', group: 'Supporting Workflows' },
    { id: 'nav-test-data', label: 'Test Data', icon: Database, href: '/test-data', keywords: ['test data', 'dataset', 'datasets', 'fixture', 'fixtures', 'data set', 'test-data', 'td'], category: 'navigation', group: 'Supporting Workflows' },
    { id: 'nav-requirements', label: 'Requirements', icon: CheckSquare, href: '/requirements', keywords: ['requirements', 'req', 'rtm', 'traceability'], category: 'navigation', group: 'Supporting Workflows' },
    { id: 'nav-rtm', label: 'RTM', icon: GitBranch, href: '/rtm', keywords: ['rtm', 'traceability', 'matrix', 'requirements'], category: 'navigation', group: 'Supporting Workflows' },
    { id: 'nav-coverage', label: 'Coverage', icon: PieChart, href: '/coverage', keywords: ['coverage', 'traceability', 'gaps', 'quality'], category: 'navigation', group: 'Supporting Workflows' },
    { id: 'nav-regression', label: 'Regression', icon: FlaskConical, href: '/regression', keywords: ['regression', 'suite', 'batch', 'batches'], category: 'navigation', group: 'Supporting Workflows' },
    { id: 'nav-batches', label: 'Batch Reports', icon: Layers, href: '/regression/batches', keywords: ['batch', 'batches', 'reports', 'regression'], category: 'navigation', group: 'Supporting Workflows' },

    // Advanced tools
    { id: 'nav-workflow', label: 'Workflow Monitor', icon: Workflow, href: '/workflow', keywords: ['ai', 'workflow', 'workflows', 'automation', 'pipeline'], category: 'navigation', group: 'Advanced Tools' },
    { id: 'nav-exploration', label: 'Discovery', icon: Compass, href: '/exploration', keywords: ['discovery', 'exploration', 'explore', 'crawl', 'sessions', 'discovery sessions', 'exploration sessions'], category: 'navigation', group: 'Advanced Tools' },
    { id: 'nav-api-testing', label: 'API Testing', icon: Zap, href: '/api-testing', keywords: ['api', 'rest', 'http', 'endpoint', 'openapi', 'swagger'], category: 'navigation', group: 'Advanced Tools' },
    { id: 'nav-load-testing', label: 'Load Testing', icon: Activity, href: '/load-testing', keywords: ['load', 'performance', 'k6', 'stress'], category: 'navigation', group: 'Advanced Tools' },
    { id: 'nav-security', label: 'Security Testing', icon: Shield, href: '/security-testing', keywords: ['security', 'vulnerability', 'scan', 'zap'], category: 'navigation', group: 'Advanced Tools' },
    { id: 'nav-database', label: 'Database Testing', icon: Database, href: '/database-testing', keywords: ['database', 'db', 'sql', 'query'], category: 'navigation', group: 'Advanced Tools' },
    { id: 'nav-llm', label: 'LLM Testing', icon: BrainCircuit, href: '/llm-testing', keywords: ['llm', 'ai', 'model', 'prompt'], category: 'navigation', group: 'Advanced Tools' },
    { id: 'nav-analytics', label: 'Analytics', icon: TrendingUp, href: '/analytics', keywords: ['analytics', 'trends', 'flake', 'insights'], category: 'navigation', group: 'Advanced Tools' },
    { id: 'nav-schedules', label: 'Schedules', icon: Clock, href: '/schedules', keywords: ['schedule', 'cron', 'timer', 'recurring'], category: 'navigation', group: 'Advanced Tools' },
    { id: 'nav-cicd', label: 'CI/CD', icon: GitBranch, href: '/ci-cd', keywords: ['cicd', 'ci cd', 'ci/cd', 'pipeline', 'github', 'gitlab', 'quality gate', 'quality gates'], category: 'navigation', group: 'Advanced Tools' },
    { id: 'nav-pr-advisor', label: 'PR Advisor', icon: GitPullRequest, href: '/pr-advisor', keywords: ['pr', 'pull request', 'advisor', 'impact', 'test selection', 'github'], category: 'navigation', group: 'Advanced Tools' },
    { id: 'nav-memory', label: 'Memory', icon: Brain, href: '/memory', keywords: ['memory', 'semantic', 'patterns', 'knowledge'], category: 'navigation', group: 'Advanced Tools' },
    { id: 'nav-agents', label: 'Agents', icon: Bot, href: '/agents', keywords: ['agents', 'agent', 'worker', 'automation'], category: 'navigation', group: 'Advanced Tools' },
    { id: 'nav-assistant', label: 'AI Assistant', icon: MessageSquare, href: '/assistant', keywords: ['ai', 'assistant', 'chat'], category: 'navigation', group: 'Advanced Tools' },

    // Settings
    { id: 'nav-settings', label: 'Settings', icon: Settings, href: '/settings', keywords: ['settings', 'config', 'preferences'], category: 'navigation', group: 'Settings' },
];

export const adminItems: CommandItem[] = [
    { id: 'admin-users', label: 'User Management', icon: Users, href: '/admin/users', keywords: ['users', 'admin', 'manage', 'accounts'], category: 'admin', adminOnly: true },
    { id: 'admin-step-registry', label: 'Step Registry', icon: Workflow, href: '/admin/workflow-step-types', keywords: ['step registry', 'workflow step', 'workflow steps', 'step types', 'admin', 'registry'], category: 'admin', adminOnly: true },
];

/** Get all command items, optionally including admin items */
export function getAllCommands(isSuperuser: boolean): CommandItem[] {
    const items = [...quickActions, ...navigationItems];
    if (isSuperuser) {
        items.push(...adminItems);
    }
    return items;
}

const NON_WORD_SEPARATOR = /[^a-z0-9]+/g;

function normalizeSearchText(value: string): string {
    return value.toLowerCase().replace(NON_WORD_SEPARATOR, ' ').trim().replace(/\s+/g, ' ');
}

function compactSearchText(value: string): string {
    return normalizeSearchText(value).replace(/\s+/g, '');
}

function tokenize(value: string): string[] {
    return normalizeSearchText(value).split(' ').filter(Boolean);
}

function commandFields(item: CommandItem) {
    return [
        { value: item.label, weight: 1 },
        { value: item.href || '', weight: 0.8 },
        { value: item.group || '', weight: 0.7 },
        ...item.keywords.map(keyword => ({ value: keyword, weight: 0.95 })),
    ].filter(field => field.value);
}

function fieldMatchesToken(field: string, token: string): number {
    const normalized = normalizeSearchText(field);
    const compact = normalized.replace(/\s+/g, '');
    const words = normalized.split(' ').filter(Boolean);

    if (normalized === token || compact === token || words.includes(token)) return 80;
    if (words.some(word => word.startsWith(token)) || compact.startsWith(token)) return 55;
    if (normalized.includes(token) || compact.includes(token)) return 30;
    return 0;
}

/** Rank a command item for a query. Returns 0 when any query token is unmatched. */
export function rankCommandItem(item: CommandItem, query: string): number {
    const normalizedQuery = normalizeSearchText(query);
    if (!normalizedQuery) return 1;

    const compactQuery = compactSearchText(query);
    const fields = commandFields(item);
    const label = normalizeSearchText(item.label);
    const labelCompact = compactSearchText(item.label);
    const href = normalizeSearchText(item.href || '');
    const keywordValues = item.keywords.map(keyword => ({
        normalized: normalizeSearchText(keyword),
        compact: compactSearchText(keyword),
    }));

    let score = 0;
    if (label === normalizedQuery || labelCompact === compactQuery) score += 1000;
    if (keywordValues.some(keyword => keyword.normalized === normalizedQuery || keyword.compact === compactQuery)) score += 900;
    if (href === normalizedQuery || compactSearchText(item.href || '') === compactQuery) score += 700;
    if (label.split(' ').includes(normalizedQuery)) score += 600;
    if (keywordValues.some(keyword => keyword.normalized.split(' ').includes(normalizedQuery))) score += 550;
    if (label.startsWith(normalizedQuery)) score += 500;
    if (keywordValues.some(keyword => keyword.normalized.startsWith(normalizedQuery))) score += 450;

    for (const token of tokenize(query)) {
        let bestTokenScore = 0;
        for (const field of fields) {
            bestTokenScore = Math.max(bestTokenScore, fieldMatchesToken(field.value, token) * field.weight);
        }
        if (bestTokenScore === 0) return 0;
        score += bestTokenScore;
    }

    return Math.round(score);
}

/** Return matching commands sorted by rank while preserving declaration order for ties. */
export function rankCommandItems<T extends CommandItem>(items: T[], query: string): T[] {
    const ranked: RankedCommand<T>[] = items
        .map((item, index) => ({ item, index, score: rankCommandItem(item, query) }))
        .filter(result => result.score > 0);

    ranked.sort((a, b) => b.score - a.score || a.index - b.index);
    return ranked.map(result => result.item);
}

/** Query helper kept for tests and older call sites. */
export function matchesQuery(item: CommandItem, query: string): boolean {
    return rankCommandItem(item, query) > 0;
}
