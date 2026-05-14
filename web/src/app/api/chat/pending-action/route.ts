import { NextRequest, NextResponse } from 'next/server';
import {
  createPendingActionToken,
  getAssistantActionConfig,
  redactAssistantActionArgs,
} from '@/lib/ai/action-registry';

export async function POST(req: NextRequest) {
  const { toolName, args } = await req.json();

  if (!toolName || !getAssistantActionConfig(toolName)) {
    return NextResponse.json({ error: `Unknown assistant action: ${toolName}` }, { status: 400 });
  }

  const authToken = req.headers.get('authorization')?.replace('Bearer ', '') || undefined;
  const projectId = (args?._projectId as string) || undefined;
  const token = createPendingActionToken({
    toolName,
    args: args || {},
    projectId,
    authToken,
  });

  const config = getAssistantActionConfig(toolName)!;
  console.info('[assistant-action] proposed', {
    toolName,
    risk: config.risk,
    requiredRole: config.requiredRole,
    projectId,
  });

  return NextResponse.json({
    actionToken: token,
    toolName,
    label: config.label,
    risk: config.risk,
    requiredRole: config.requiredRole,
    confirmationRequired: config.confirmationRequired,
    args: redactAssistantActionArgs(args || {}),
  });
}
