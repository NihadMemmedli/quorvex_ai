import { NextRequest, NextResponse } from 'next/server';
import { backendFetch } from '@/lib/ai/backend-client';

export async function GET(req: NextRequest) {
  const { searchParams } = new URL(req.url);
  const q = searchParams.get('q') || '';
  const projectId = searchParams.get('project_id') || '';
  const limit = searchParams.get('limit') || '10';

  const authToken = req.headers.get('authorization')?.replace('Bearer ', '') || undefined;

  const params = new URLSearchParams();
  if (q) params.set('q', q);
  if (projectId) params.set('project_id', projectId);
  params.set('limit', limit);

  const result = await backendFetch(`/chat/search-entities?${params.toString()}`, { authToken });

  if (!result.ok) {
    return NextResponse.json({ error: result.error }, { status: result.status || 500 });
  }
  return NextResponse.json(result.data);
}
