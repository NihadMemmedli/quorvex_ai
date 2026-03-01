import { NextRequest, NextResponse } from 'next/server';
import { MUTATING_TOOL_CONFIGS } from '@/lib/ai/tools';
import { backendFetch } from '@/lib/ai/backend-client';

export async function POST(req: NextRequest) {
  const { toolName, args } = await req.json();

  if (!toolName || !MUTATING_TOOL_CONFIGS[toolName]) {
    return NextResponse.json({ error: `Unknown tool: ${toolName}` }, { status: 400 });
  }

  const config = MUTATING_TOOL_CONFIGS[toolName];
  const authToken = req.headers.get('authorization')?.replace('Bearer ', '') || undefined;
  const projectId = (args?._projectId as string) || undefined;

  const path = config.getPath(args || {});
  const body = config.getBody ? config.getBody(args || {}, projectId) : undefined;

  const res = await backendFetch(path, {
    method: config.method,
    body,
    authToken,
    projectId,
  });

  if (!res.ok) {
    return NextResponse.json({ error: res.error }, { status: res.status || 500 });
  }

  return NextResponse.json(res.data);
}
