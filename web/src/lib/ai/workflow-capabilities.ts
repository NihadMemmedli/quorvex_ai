export interface AssistantWorkflowCapability {
  section: string;
  page: string;
  status: 'supported' | 'partial' | 'missing';
  read: string[];
  actions: string[];
  missing?: string[];
  nextTools?: string[];
}

export const ASSISTANT_WORKFLOW_CAPABILITIES: AssistantWorkflowCapability[] = [
  {
    section: 'Overview',
    page: '/',
    status: 'supported',
    read: ['dashboard stats', 'health check', 'recent runs', 'project status'],
    actions: ['navigate to focused workflows'],
  },
  {
    section: 'Projects',
    page: '/projects',
    status: 'supported',
    read: ['list projects', 'project details', 'members', 'credentials'],
    actions: ['create project', 'update project', 'delete project', 'assign specs', 'manage credentials'],
  },
  {
    section: 'Specs and Templates',
    page: '/specs',
    status: 'supported',
    read: ['list specs', 'read spec content', 'read generated Playwright code', 'list templates'],
    actions: ['create spec', 'update spec', 'run spec', 'run regression batch'],
  },
  {
    section: 'Runs and Regression',
    page: '/runs',
    status: 'supported',
    read: ['recent runs', 'run details', 'run logs', 'batch trends', 'batch error summaries'],
    actions: ['retry failed run', 'heal failed run', 'stop run', 'rerun failed batch tests'],
  },
  {
    section: 'Discovery and Recordings',
    page: '/exploration',
    status: 'supported',
    read: ['exploration sessions', 'exploration details', 'artifacts', 'flows', 'APIs', 'issues', 'recording sessions', 'recording code', 'Explorer Agent runs', 'Explorer Agent sessions'],
    actions: ['start exploration', 'start explorer agent', 'stop exploration', 'generate API specs/tests', 'synthesize explorer specs', 'generate flow specs/tests', 'manage explorer sessions', 'start recording', 'stop recording', 'import recording'],
  },
  {
    section: 'Requirements and Coverage',
    page: '/requirements',
    status: 'supported',
    read: ['requirements', 'duplicates', 'stats', 'RTM coverage', 'RTM gaps', 'coverage trends'],
    actions: ['generate requirements', 'create requirement', 'update requirement', 'delete requirement', 'merge duplicates', 'generate specs from requirements', 'manage RTM entries and snapshots'],
  },
  {
    section: 'PRD',
    page: '/prd',
    status: 'supported',
    read: ['PRD projects', 'features', 'generation history', 'generation status', 'queue status'],
    actions: ['generate test plan', 'stop generation', 'generate Playwright test', 'heal generated test', 'run generated test'],
  },
  {
    section: 'API, Load, Security, Database, and LLM Testing',
    page: '/api-testing',
    status: 'supported',
    read: ['specialized specs', 'runs', 'analytics', 'findings', 'checks', 'providers'],
    actions: ['create/import/generate/run specialized tests', 'analyze runs', 'triage findings', 'save generated specs', 'manage security specs', 'run targeted scans'],
  },
  {
    section: 'Schedules',
    page: '/schedules',
    status: 'supported',
    read: ['schedules', 'schedule detail', 'execution history', 'next run times', 'cron validation'],
    actions: ['create schedule', 'update schedule', 'toggle schedule', 'delete schedule', 'run schedule now'],
  },
  {
    section: 'Custom Workflows',
    page: '/workflow',
    status: 'supported',
    read: ['workflow definitions', 'workflow catalog', 'recent workflow runs', 'workflow run steps'],
    actions: ['create workflow from chat', 'create agent-to-requirements/specs workflow', 'update workflow', 'duplicate workflow', 'archive workflow', 'start workflow', 'start workflow from a specific step', 'retry failed workflow step', 'pause/resume/cancel workflow run'],
  },
  {
    section: 'CI/CD and PR Advisor',
    page: '/ci-cd',
    status: 'supported',
    read: ['CI providers', 'workflows', 'runs', 'logs', 'audit events', 'open pull requests', 'PR analyses', 'quality gates'],
    actions: ['configure non-secret provider defaults', 'sync CI runs', 'dispatch workflow', 'cancel run', 'rerun run', 'generate workflow change', 'open workflow PR', 'analyze PR', 'run all or subset recommended tests', 'start PR quality gate'],
    missing: ['CI access tokens, trigger tokens, and webhook secrets stay in Settings'],
  },
  {
    section: 'External Integrations',
    page: '/settings',
    status: 'partial',
    read: ['Jira config', 'Jira issues', 'Jira bug report jobs', 'TestRail config', 'TestRail mappings', 'TestRail sync preview'],
    actions: ['generate Jira bug report', 'create Jira issue', 'push TestRail cases', 'sync TestRail results', 'delete TestRail mapping'],
    missing: ['Jira, TestRail, GitHub credential setup remains dashboard-led unless explicitly requested'],
    nextTools: ['configure Jira from chat', 'configure TestRail from chat'],
  },
  {
    section: 'Settings and Admin',
    page: '/settings',
    status: 'partial',
    read: ['AI settings', 'connection health', 'users'],
    actions: ['update AI settings', 'test connection'],
    missing: ['User administration is read-only from chatbot'],
    nextTools: ['invite user', 'update user role', 'disable user'],
  },
];

export function formatWorkflowCapabilitiesForPrompt() {
  return ASSISTANT_WORKFLOW_CAPABILITIES.map((capability) => {
    return [
      `- ${capability.section} (${capability.page}) [${capability.status}]`,
      `  Read: ${capability.read.join(', ')}`,
      `  Actions: ${capability.actions.join(', ')}`,
      capability.missing?.length ? `  Missing/partial: ${capability.missing.join(', ')}` : '',
      capability.nextTools?.length ? `  Next useful tools: ${capability.nextTools.join(', ')}` : '',
    ].filter(Boolean).join('\n');
  }).join('\n');
}
