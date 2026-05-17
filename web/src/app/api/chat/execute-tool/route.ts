import { NextRequest, NextResponse } from 'next/server';
import { backendFetch } from '@/lib/ai/backend-client';
import {
  buildAdhocCustomAgentRunBody,
  getAssistantActionConfig,
  markPendingActionRedeemed,
  redactAssistantActionArgs,
  verifyPendingActionToken,
} from '@/lib/ai/action-registry';

export async function POST(req: NextRequest) {
  const { actionToken } = await req.json();

  if (!actionToken || typeof actionToken !== 'string') {
    return NextResponse.json({ error: 'Missing approved action token' }, { status: 428 });
  }

  const authToken = req.headers.get('authorization')?.replace('Bearer ', '') || undefined;

  let payload;
  try {
    payload = verifyPendingActionToken(actionToken, authToken);
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : 'Invalid approval token' },
      { status: 403 }
    );
  }

  const config = getAssistantActionConfig(payload.toolName);
  if (!config) {
    return NextResponse.json({ error: `Unknown assistant action: ${payload.toolName}` }, { status: 400 });
  }

  const roleError = await validateActionRole(config.requiredRole, authToken);
  if (roleError) {
    return NextResponse.json({ error: roleError }, { status: 403 });
  }

  const projectId = payload.projectId;
  const args = payload.args || {};
  const path = config.getPath(args, projectId);
  const body = config.getBody ? config.getBody(args, projectId) : undefined;
  markPendingActionRedeemed(payload.id);

  if (payload.toolName === 'startAdhocCustomAgent') {
    return executeAdhocCustomAgentAction({
      actionId: payload.id,
      args,
      authToken,
      body,
      path,
      projectId,
    });
  }

  console.info('[assistant-action] approved', {
    id: payload.id,
    toolName: payload.toolName,
    risk: config.risk,
    projectId,
    path,
  });

  const res = await backendFetch(path, {
    method: config.method,
    body,
    authToken,
    projectId,
  });

  if (!res.ok) {
    console.warn('[assistant-action] failed', {
      id: payload.id,
      toolName: payload.toolName,
      status: res.status,
      error: res.error,
    });
    return NextResponse.json({ error: res.error }, { status: res.status || 500 });
  }

  console.info('[assistant-action] executed', {
    id: payload.id,
    toolName: payload.toolName,
    projectId,
  });

  return NextResponse.json({
    ...(res.data && typeof res.data === 'object' ? res.data : { result: res.data }),
    _assistantAction: {
      id: payload.id,
      toolName: payload.toolName,
      label: config.label,
      risk: config.risk,
      projectId,
      args: redactAssistantActionArgs(args),
    },
  });
}

async function validateActionRole(requiredRole: string, authToken?: string) {
  if (requiredRole !== 'admin') return null;

  // Preserve unauthenticated local/dev deployments where REQUIRE_AUTH=false.
  if (!authToken) return null;

  const userRes = await backendFetch<{ is_superuser?: boolean }>('/auth/me', {
    authToken,
    timeoutMs: 5000,
  });

  if (!userRes.ok) return 'Could not verify user permissions for this assistant action';
  if (!userRes.data?.is_superuser) return 'This assistant action requires an administrator';
  return null;
}

async function executeAdhocCustomAgentAction({
  actionId,
  args,
  authToken,
  body,
  path,
  projectId,
}: {
  actionId: string;
  args: Record<string, unknown>;
  authToken?: string;
  body?: unknown;
  path: string;
  projectId?: string;
}) {
  console.info('[assistant-action] approved', {
    id: actionId,
    toolName: 'startAdhocCustomAgent',
    risk: 'medium',
    projectId,
    path,
  });

  const definitionRes = await backendFetch<{ id?: string }>(path, {
    method: 'POST',
    body,
    authToken,
    projectId,
  });

  if (!definitionRes.ok || !definitionRes.data?.id) {
    console.warn('[assistant-action] adhoc custom agent definition failed', {
      id: actionId,
      status: definitionRes.status,
      error: definitionRes.error,
    });
    return NextResponse.json(
      { error: definitionRes.error || 'Failed to create custom agent definition' },
      { status: definitionRes.status || 500 }
    );
  }

  const definitionId = definitionRes.data.id;
  const runPath = `/api/agents/definitions/${encodeURIComponent(definitionId)}/runs`;
  const runBody = buildAdhocCustomAgentRunBody(args, projectId);
  const runRes = await backendFetch(runPath, {
    method: 'POST',
    body: runBody,
    authToken,
    projectId,
  });

  if (!runRes.ok) {
    console.warn('[assistant-action] adhoc custom agent run failed', {
      id: actionId,
      definitionId,
      status: runRes.status,
      error: runRes.error,
    });
    return NextResponse.json(
      {
        error: runRes.error || 'Failed to start custom agent run',
        definition_id: definitionId,
      },
      { status: runRes.status || 500 }
    );
  }

  console.info('[assistant-action] executed', {
    id: actionId,
    toolName: 'startAdhocCustomAgent',
    projectId,
    definitionId,
  });

  return NextResponse.json({
    ...(runRes.data && typeof runRes.data === 'object' ? runRes.data : { result: runRes.data }),
    definition_id: definitionId,
    _assistantAction: {
      id: actionId,
      toolName: 'startAdhocCustomAgent',
      label: 'Start Custom Agent',
      risk: 'medium',
      projectId,
      args: redactAssistantActionArgs(args),
    },
  });
}
