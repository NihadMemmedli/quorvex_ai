import { NextRequest, NextResponse } from 'next/server';
import { backendFetch } from '@/lib/ai/backend-client';

export async function GET(req: NextRequest) {
  const { searchParams } = new URL(req.url);
  const type = searchParams.get('type') || '';
  const id = searchParams.get('id') || '';
  const projectId = searchParams.get('project_id') || '';

  const authToken = req.headers.get('authorization')?.replace('Bearer ', '') || undefined;

  const params = new URLSearchParams();
  if (type) params.set('type', type);
  if (id) params.set('id', id);
  if (projectId) params.set('project_id', projectId);

  const result = await backendFetch(`/chat/resolve-entity?${params.toString()}`, { authToken });

  if (!result.ok) {
    return NextResponse.json({ error: result.error }, { status: result.status || 500 });
  }
  return NextResponse.json(result.data);
}
