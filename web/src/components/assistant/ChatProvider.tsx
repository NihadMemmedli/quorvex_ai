'use client';

import {
  ReactNode,
  createContext,
  useContext,
  useState,
  useCallback,
  useEffect,
  useRef,
} from 'react';
import { AssistantRuntimeProvider, useThread, SimpleImageAttachmentAdapter } from '@assistant-ui/react';
import { useChatRuntime } from '@assistant-ui/react-ai-sdk';
import { DefaultChatTransport, type UIMessage } from 'ai';
import { useAuth } from '@/contexts/AuthContext';
import { useProject } from '@/contexts/ProjectContext';
import { usePathname } from 'next/navigation';
import { toast } from 'sonner';
import {
  Conversation,
  ChatMessageRecord,
  listConversations,
  createConversation,
  deleteConversation as deleteConv,
  getMessages,
  saveMessagesBulk,
  autoTitle,
  generateSummary,
  updateMessageContentJson,
} from '@/lib/chat-api';

// Helper to generate unique IDs for UIMessage objects
let msgIdCounter = 0;
function genMsgId(): string {
  return `hist-${Date.now()}-${++msgIdCounter}`;
}

// Message type used for saving — includes content_json for round-trip fidelity
type SaveableMessage = { role: string; content: string; content_json?: string };

// Convert loaded DB messages to UIMessage format, restoring full parts from content_json
function toUIMessages(msgs: Array<{ role: string; content: string; content_json?: string | null }>): UIMessage[] {
  return msgs.map((m) => {
    // If content_json exists, restore the full parts array for round-trip fidelity
    if (m.content_json) {
      try {
        const rawParts = JSON.parse(m.content_json);
        if (Array.isArray(rawParts) && rawParts.length > 0) {
          // Normalize parts: convert any ThreadMessage format (tool-call/tool-result)
          // to UIMessage format (dynamic-tool) for correct round-trip through the SDK
          const parts = threadPartsToUIParts(rawParts);
          if (parts.length > 0) {
            return {
              id: genMsgId(),
              role: m.role as 'user' | 'assistant',
              parts,
            };
          }
        }
      } catch {
        // Fall through to plain text
      }
    }
    return {
      id: genMsgId(),
      role: m.role as 'user' | 'assistant',
      parts: [{ type: 'text' as const, text: m.content }],
    };
  });
}

// Extract text content from ThreadMessage content parts (for backwards-compatible text column)
function extractTextFromParts(contentParts: any[]): string {
  return contentParts
    .filter((p: any) => p.type === 'text')
    .map((p: any) => p.text)
    .join('\n');
}

// Convert ThreadMessage content parts (tool-call/tool-result) to UIMessage DynamicToolUIPart format.
// This bridges the format gap: @assistant-ui uses {type:'tool-call', toolName, args, result}
// while Vercel AI SDK expects {type:'dynamic-tool', toolName, state, input, output}.
// Parts already in correct format pass through unchanged.
function threadPartsToUIParts(parts: any[]): any[] {
  if (!Array.isArray(parts)) return parts;

  // Collect tool-result parts by toolCallId for merging into tool-call parts
  const resultMap = new Map<string, any>();
  for (const p of parts) {
    if (p.type === 'tool-result' && p.toolCallId) {
      resultMap.set(p.toolCallId, p.result);
    }
  }

  const converted: any[] = [];
  for (const p of parts) {
    if (p.type === 'tool-call') {
      // Convert tool-call → dynamic-tool
      const hasResult = p.result !== undefined || resultMap.has(p.toolCallId);
      const output = p.result !== undefined ? p.result : resultMap.get(p.toolCallId);
      converted.push({
        type: 'dynamic-tool',
        toolCallId: p.toolCallId,
        toolName: p.toolName,
        state: hasResult ? 'output-available' : 'input-available',
        input: p.args ?? p.input ?? {},
        output: hasResult ? output : undefined,
      });
    } else if (p.type === 'tool-result') {
      // Skip standalone tool-result if we already merged it into a tool-call above
      if (resultMap.has(p.toolCallId)) continue;
      // Orphan tool-result with no matching tool-call — convert to dynamic-tool
      converted.push({
        type: 'dynamic-tool',
        toolCallId: p.toolCallId,
        toolName: p.toolName,
        state: 'output-available',
        input: {},
        output: p.result,
      });
    } else if (p.type === 'text' && (!p.text || p.text.trim() === '')) {
      // Filter out empty text parts that could cause blank bubbles
      continue;
    } else {
      // Already correct format (dynamic-tool, text, etc.) — pass through
      converted.push(p);
    }
  }
  return converted;
}

// Types for the chat context
interface ChatContextType {
  conversationId: string | null;
  conversations: Conversation[];
  createNewConversation: () => void;
  switchConversation: (id: string) => void;
  deleteConversation: (id: string) => Promise<void>;
  refreshConversations: () => Promise<Conversation[] | void>;
  isLoadingHistory: boolean;
  persistToolResult: (toolCallId: string, toolName: string, result: unknown) => void;
}

const ChatContext = createContext<ChatContextType | null>(null);

export function useChatContext() {
  const ctx = useContext(ChatContext);
  if (!ctx) throw new Error('useChatContext must be used within ChatProvider');
  return ctx;
}

// Child component that subscribes to thread state via useThread hook.
// Must be rendered inside AssistantRuntimeProvider.
function ThreadMessageTracker({
  onNewMessages,
}: {
  onNewMessages: (messages: SaveableMessage[]) => void;
}) {
  const thread = useThread();
  const lastSavedIndexRef = useRef(0);
  const wasRunningRef = useRef(false);
  const initializedRef = useRef(false);

  useEffect(() => {
    const { isRunning, messages } = thread;

    // On first render with pre-loaded messages (restored conversation),
    // skip already-saved messages to prevent duplicate saving
    if (!initializedRef.current && messages.length > 0) {
      initializedRef.current = true;
      if (!isRunning) {
        lastSavedIndexRef.current = messages.length;
        return;
      }
    }

    // Detect run completion: was running, now stopped
    if (wasRunningRef.current && !isRunning && messages.length > 0) {
      // Save all unsaved messages
      const unsaved: SaveableMessage[] = [];
      for (let i = lastSavedIndexRef.current; i < messages.length; i++) {
        const msg = messages[i];
        if (!msg) continue;
        const role = msg.role;
        if (role !== 'user' && role !== 'assistant') continue;
        // ThreadMessage uses `content` for parts array
        const contentParts = (msg as any).content || [];
        const textContent = extractTextFromParts(contentParts);
        // Convert ThreadMessage parts to UIMessage format before saving
        const uiParts = threadPartsToUIParts(contentParts);
        unsaved.push({
          role,
          content: textContent,
          content_json: JSON.stringify(uiParts),
        });
      }
      if (unsaved.length > 0) {
        lastSavedIndexRef.current = messages.length;
        onNewMessages(unsaved);
      }
    }

    wasRunningRef.current = isRunning;
  }, [thread, thread.isRunning, thread.messages, onNewMessages]);

  return null;
}

// Extract entity context from the current URL pathname
interface PageContext {
  section?: string;
  viewingRunId?: string;
  viewingSpecName?: string;
  viewingBatchId?: string;
  viewingSessionId?: string;
  viewingLoadRunId?: string;
  viewingSecurityRunId?: string;
  viewingDbRunId?: string;
}

function usePageContext(pathname: string): PageContext {
  const ctx: PageContext = {};

  // Detect section from URL
  const segments = pathname.split('/').filter(Boolean);
  if (segments.length > 0) {
    ctx.section = segments[0];
  }

  // Extract entity IDs from URL patterns
  const patterns: Array<{ regex: RegExp; key: keyof PageContext }> = [
    { regex: /^\/runs\/([^/]+)/, key: 'viewingRunId' },
    { regex: /^\/specs\/([^/]+)/, key: 'viewingSpecName' },
    { regex: /^\/regression\/batches\/([^/]+)/, key: 'viewingBatchId' },
    { regex: /^\/exploration\/([^/]+)/, key: 'viewingSessionId' },
    { regex: /^\/load-testing\/runs\/([^/]+)/, key: 'viewingLoadRunId' },
    { regex: /^\/security-testing\/runs\/([^/]+)/, key: 'viewingSecurityRunId' },
    { regex: /^\/database-testing\/runs\/([^/]+)/, key: 'viewingDbRunId' },
  ];

  for (const { regex, key } of patterns) {
    const match = pathname.match(regex);
    if (match && match[1]) {
      ctx[key] = decodeURIComponent(match[1]);
      break;
    }
  }

  return ctx;
}

// Inner component that manages the assistant-ui runtime.
// Keyed by conversationId so it remounts when conversation changes.
function RuntimeProvider({
  children,
  conversationId,
  initialMessages,
  onNewMessages,
}: {
  children: ReactNode;
  conversationId: string | null;
  initialMessages?: Array<{ role: string; content: string; content_json?: string | null }>;
  onNewMessages?: (messages: SaveableMessage[]) => void;
}) {
  const { getAccessToken } = useAuth();
  const { currentProject } = useProject();
  const pathname = usePathname();
  const pageContext = usePageContext(pathname);

  // Convert DB messages to UIMessage format (with content_json restoration)
  const uiMessages = initialMessages ? toUIMessages(initialMessages) : undefined;

  const runtime = useChatRuntime({
    transport: new DefaultChatTransport({
      api: '/api/chat',
      body: {
        projectId: currentProject?.id,
        projectName: currentProject?.name,
        currentPage: pathname,
        conversationId,
        pageContext,
      },
      headers: (): Record<string, string> => {
        const token = getAccessToken();
        return token ? { Authorization: `Bearer ${token}` } : {};
      },
    }),
    adapters: {
      attachments: new SimpleImageAttachmentAdapter(),
    },
    messages: uiMessages,
  });

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      {onNewMessages && <ThreadMessageTracker onNewMessages={onNewMessages} />}
      {children}
    </AssistantRuntimeProvider>
  );
}

const LAST_CONVERSATION_KEY = 'chat-last-conversation-id';

export function ChatProvider({ children }: { children: ReactNode }) {
  const { currentProject } = useProject();
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [initialMessages, setInitialMessages] = useState<
    Array<{ role: string; content: string; content_json?: string | null }> | undefined
  >(undefined);
  const [isLoadingHistory, setIsLoadingHistory] = useState(false);
  const [runtimeKey, setRuntimeKey] = useState<string>('new');
  const conversationCreatedRef = useRef(false);
  const creatingRef = useRef(false);
  const autoResumedRef = useRef(false);

  // Persist conversationId to localStorage whenever it changes
  useEffect(() => {
    if (conversationId) {
      try { localStorage.setItem(LAST_CONVERSATION_KEY, conversationId); } catch { /* noop */ }
    }
  }, [conversationId]);

  const refreshConversations = useCallback(async () => {
    try {
      const data = await listConversations(currentProject?.id);
      setConversations(data.conversations);
      return data.conversations;
    } catch (err) {
      console.error('Failed to load conversations:', err);
      toast.error('Failed to load conversations');
      return [];
    }
  }, [currentProject?.id]);

  const switchConversation = useCallback(async (id: string) => {
    setIsLoadingHistory(true);
    try {
      const data = await getMessages(id);
      // Preserve content_json for round-trip fidelity
      const msgs = data.messages.map((m: ChatMessageRecord) => ({
        role: m.role as 'user' | 'assistant',
        content: m.content,
        content_json: m.content_json || undefined,
      }));
      setConversationId(id);
      setInitialMessages(msgs);
      setRuntimeKey(`conv-${id}`);
      conversationCreatedRef.current = true;
    } catch (err) {
      console.error('Failed to load conversation history:', err);
      toast.error('Failed to load conversation history');
      setConversationId(id);
      setInitialMessages(undefined);
      setRuntimeKey(`conv-${id}`);
      conversationCreatedRef.current = true;
    } finally {
      setIsLoadingHistory(false);
    }
  }, []);

  // Load conversations on mount and auto-resume last conversation
  useEffect(() => {
    (async () => {
      const convos = await refreshConversations();
      if (autoResumedRef.current) return;
      autoResumedRef.current = true;
      try {
        const lastId = localStorage.getItem(LAST_CONVERSATION_KEY);
        if (lastId && convos.some((c: Conversation) => c.id === lastId)) {
          await switchConversation(lastId);
        }
      } catch (err) {
        console.error('Failed to auto-resume conversation:', err);
      }
    })();
  }, [refreshConversations, switchConversation]);

  const createNewConversation = useCallback(() => {
    setConversationId(null);
    setInitialMessages(undefined);
    setRuntimeKey(`new-${Date.now()}`);
    conversationCreatedRef.current = false;
    try { localStorage.removeItem(LAST_CONVERSATION_KEY); } catch { /* noop */ }
  }, []);

  const handleDeleteConversation = useCallback(async (id: string) => {
    try {
      await deleteConv(id);
      setConversations((prev) => prev.filter((c) => c.id !== id));
      if (conversationId === id) {
        createNewConversation();
      }
      // Clear stored ID if the deleted conversation was the last one
      try {
        if (localStorage.getItem(LAST_CONVERSATION_KEY) === id) {
          localStorage.removeItem(LAST_CONVERSATION_KEY);
        }
      } catch { /* noop */ }
    } catch (err) {
      console.error('Failed to delete conversation:', err);
      toast.error('Failed to delete conversation');
    }
  }, [conversationId, createNewConversation]);

  // Handle new messages: auto-create conversation and save with content_json
  const handleNewMessages = useCallback(async (messages: SaveableMessage[]) => {
    if (conversationCreatedRef.current) {
      // Already have a conversation, just save new messages
      if (conversationId) {
        try {
          await saveMessagesBulk(conversationId, messages);
        } catch (err) {
          console.error('Failed to save messages:', err);
          toast.error('Failed to save message');
        }
      }
      return;
    }

    // Prevent double-creation if called rapidly
    if (creatingRef.current) return;
    creatingRef.current = true;

    // Step 1: Create conversation
    let conv: { id: string } | null = null;
    try {
      conv = await createConversation('New Conversation', currentProject?.id);
    } catch (err) {
      console.error('Failed to create conversation:', err);
      toast.error('Failed to create conversation');
      creatingRef.current = false;
      return; // conversationCreatedRef stays false — allows retry
    }

    // Step 2: Mark as created (only after success) and update state
    conversationCreatedRef.current = true;
    creatingRef.current = false;
    setConversationId(conv.id);

    // Step 3: Save messages
    try {
      await saveMessagesBulk(conv.id, messages);
    } catch (err) {
      console.error('Failed to save messages:', err);
      toast.error('Failed to save messages');
    }

    // Step 4: Auto-title (cosmetic, silent failure)
    try {
      await autoTitle(conv.id);
    } catch (err) {
      console.error('Failed to auto-title conversation:', err);
    }

    // Step 4b: Auto-generate summary (cosmetic, silent failure)
    try {
      await generateSummary(conv.id);
    } catch (err) {
      console.error('Failed to generate summary:', err);
    }

    // Step 5: Refresh conversation list (silent failure)
    try {
      await refreshConversations();
    } catch (err) {
      console.error('Failed to refresh conversations:', err);
    }
  }, [conversationId, currentProject?.id, refreshConversations]);

  // Persist a tool result to the database immediately (for approve/reject durability)
  const persistToolResult = useCallback(async (toolCallId: string, toolName: string, result: unknown) => {
    if (!conversationId) return; // New conversation not yet created — ThreadMessageTracker will save later
    try {
      const data = await getMessages(conversationId);
      // Find the assistant message whose content_json contains a part with this toolCallId
      for (const msg of data.messages) {
        if (msg.role !== 'assistant' || !msg.content_json) continue;
        let parts: any[];
        try { parts = JSON.parse(msg.content_json); } catch { continue; }
        if (!Array.isArray(parts)) continue;

        let found = false;
        for (const part of parts) {
          if (part.toolCallId === toolCallId) {
            part.output = result;
            part.state = 'output-available';
            // Also update tool-call format if present
            if (part.type === 'tool-call') {
              part.result = result;
            }
            found = true;
            break;
          }
        }
        if (found) {
          await updateMessageContentJson(conversationId, msg.id, JSON.stringify(parts));
          return;
        }
      }
    } catch (err) {
      console.error('Failed to persist tool result:', err);
      // Non-fatal — ThreadMessageTracker will save at run completion as fallback
    }
  }, [conversationId]);

  // Global keyboard shortcuts
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      // Cmd+N or Ctrl+N: new chat
      if ((e.metaKey || e.ctrlKey) && e.key === 'n') {
        e.preventDefault();
        createNewConversation();
      }
      // Cmd+K or Ctrl+K: focus search
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        window.dispatchEvent(new CustomEvent('focus-chat-search'));
      }
    }
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [createNewConversation]);

  const contextValue: ChatContextType = {
    conversationId,
    conversations,
    createNewConversation,
    switchConversation,
    deleteConversation: handleDeleteConversation,
    refreshConversations,
    isLoadingHistory,
    persistToolResult,
  };

  return (
    <ChatContext.Provider value={contextValue}>
      <RuntimeProvider
        key={runtimeKey}
        conversationId={conversationId}
        initialMessages={initialMessages}
        onNewMessages={handleNewMessages}
      >
        {children}
      </RuntimeProvider>
    </ChatContext.Provider>
  );
}
