import { NextRequest, NextResponse } from 'next/server';
import { backendFetch } from '@/lib/ai/backend-client';
import {
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
