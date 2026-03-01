import { API_BASE } from '@/lib/api';
import { fetchWithAuth } from '@/contexts/AuthContext';

export interface Conversation {
  id: string;
  title: string;
  project_id: string | null;
  is_starred: boolean;
  created_at: string;
  updated_at: string;
  message_count?: number;
  summary?: string;
}

export interface ChatMessageRecord {
  id: number;
  role: string;
  content: string;
  content_json: string | null;
  tool_name: string | null;
  tool_args: Record<string, unknown> | null;
  tool_result: Record<string, unknown> | null;
  created_at: string;
}

export async function listConversations(projectId?: string, limit = 50): Promise<{ conversations: Conversation[]; total: number }> {
  const params = new URLSearchParams();
  if (projectId) params.set('project_id', projectId);
  params.set('limit', String(limit));
  const res = await fetchWithAuth(`${API_BASE}/chat/conversations?${params}`);
  if (!res.ok) throw new Error('Failed to list conversations');
  return res.json();
}

export async function createConversation(title?: string, projectId?: string): Promise<Conversation> {
  const res = await fetchWithAuth(`${API_BASE}/chat/conversations`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title, project_id: projectId }),
  });
  if (!res.ok) throw new Error('Failed to create conversation');
  return res.json();
}

export async function deleteConversation(id: string): Promise<void> {
  const res = await fetchWithAuth(`${API_BASE}/chat/conversations/${id}`, { method: 'DELETE' });
  if (!res.ok) throw new Error('Failed to delete conversation');
}

export async function getMessages(conversationId: string): Promise<{ messages: ChatMessageRecord[] }> {
  const res = await fetchWithAuth(`${API_BASE}/chat/conversations/${conversationId}/messages`);
  if (!res.ok) throw new Error('Failed to get messages');
  return res.json();
}

export async function saveMessagesBulk(conversationId: string, messages: Array<{ role: string; content: string; content_json?: string }>): Promise<void> {
  const res = await fetchWithAuth(`${API_BASE}/chat/conversations/${conversationId}/messages/bulk`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ messages }),
  });
  if (!res.ok) throw new Error('Failed to save messages');
}

export async function updateMessageContentJson(
  conversationId: string, messageId: number, contentJson: string
): Promise<void> {
  const res = await fetchWithAuth(
    `${API_BASE}/chat/conversations/${conversationId}/messages/${messageId}/content-json`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content_json: contentJson }),
    }
  );
  if (!res.ok) throw new Error('Failed to update message content');
}

export async function autoTitle(conversationId: string): Promise<{ title: string }> {
  const res = await fetchWithAuth(`${API_BASE}/chat/conversations/${conversationId}/auto-title`, {
    method: 'POST',
  });
  if (!res.ok) throw new Error('Failed to auto-title');
  return res.json();
}

export async function toggleConversationStar(conversationId: string): Promise<{ is_starred: boolean }> {
  const res = await fetchWithAuth(`${API_BASE}/chat/conversations/${conversationId}/star`, { method: 'PATCH' });
  if (!res.ok) throw new Error('Failed to toggle star');
  return res.json();
}

export async function submitFeedback(conversationId: string, messageIndex: number, rating: string, comment?: string): Promise<void> {
  const res = await fetchWithAuth(`${API_BASE}/chat/conversations/${conversationId}/feedback`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message_index: messageIndex, rating, comment }),
  });
  if (!res.ok) throw new Error('Failed to submit feedback');
}

export async function updateConversationTitle(conversationId: string, title: string): Promise<void> {
  const res = await fetchWithAuth(`${API_BASE}/chat/conversations/${conversationId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title }),
  });
  if (!res.ok) throw new Error('Failed to update title');
}

export async function searchConversations(query: string, projectId?: string): Promise<{ results: Array<{ id: string; title: string; snippet: string; updated_at: string }> }> {
  const params = new URLSearchParams({ q: query });
  if (projectId) params.set('project_id', projectId);
  const res = await fetchWithAuth(`${API_BASE}/chat/conversations/search?${params}`);
  if (!res.ok) throw new Error('Search failed');
  return res.json();
}

export async function generateSummary(conversationId: string): Promise<{ summary: string }> {
  const res = await fetchWithAuth(`${API_BASE}/chat/conversations/${conversationId}/generate-summary`, {
    method: 'POST',
  });
  if (!res.ok) throw new Error('Failed to generate summary');
  return res.json();
}

export async function getProjectContext(projectId?: string): Promise<{ recent_runs: number; recent_failures: number; total_requirements: number; recent_explorations: number }> {
  const params = new URLSearchParams();
  if (projectId) params.set('project_id', projectId);
  const res = await fetchWithAuth(`${API_BASE}/chat/project-context?${params}`);
  if (!res.ok) return { recent_runs: 0, recent_failures: 0, total_requirements: 0, recent_explorations: 0 };
  return res.json();
}
