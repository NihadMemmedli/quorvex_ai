'use client';

import { useState, useRef, useEffect, useCallback } from 'react';
import { Plus, Trash2, MessageSquare, Search, Star, Download } from 'lucide-react';
import { toast } from 'sonner';
import { useChatContext } from './ChatProvider';
import { useProject } from '@/contexts/ProjectContext';
import { toggleConversationStar, getMessages, updateConversationTitle, searchConversations } from '@/lib/chat-api';
import type { Conversation } from '@/lib/chat-api';

function relativeTime(dateStr: string): string {
  const now = Date.now();
  const then = new Date(dateStr).getTime();
  const diff = Math.max(0, now - then);
  const minutes = Math.floor(diff / 60000);
  if (minutes < 1) return 'just now';
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days}d ago`;
  return new Date(dateStr).toLocaleDateString();
}

async function exportConversation(conv: Conversation) {
  const data = await getMessages(conv.id);
  const md = data.messages.map(m => `## ${m.role}\n\n${m.content}\n`).join('\n---\n\n');
  const blob = new Blob([`# ${conv.title}\n\n${md}`], { type: 'text/markdown' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `${conv.title.replace(/[^a-zA-Z0-9]/g, '-')}.md`;
  a.click();
  URL.revokeObjectURL(url);
}

export function ConversationList() {
  const {
    conversationId,
    conversations,
    createNewConversation,
    switchConversation,
    deleteConversation,
    refreshConversations,
  } = useChatContext();
  const { currentProject } = useProject();
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState('');
  const [focusedIndex, setFocusedIndex] = useState(-1);
  const [searchResults, setSearchResults] = useState<Array<{ id: string; title: string; snippet: string; updated_at: string }> | null>(null);
  const [isSearching, setIsSearching] = useState(false);
  const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const editInputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const searchInputRef = useRef<HTMLInputElement>(null);

  // Listen for Cmd+K focus-search event
  useEffect(() => {
    function handleFocusSearch() {
      searchInputRef.current?.focus();
    }
    window.addEventListener('focus-chat-search', handleFocusSearch);
    return () => window.removeEventListener('focus-chat-search', handleFocusSearch);
  }, []);

  // Debounced full-text search
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);

    if (searchQuery.length >= 3) {
      setIsSearching(true);
      debounceRef.current = setTimeout(async () => {
        try {
          const data = await searchConversations(searchQuery, currentProject?.id);
          setSearchResults(data.results);
        } catch {
          setSearchResults(null);
        } finally {
          setIsSearching(false);
        }
      }, 300);
    } else {
      setSearchResults(null);
      setIsSearching(false);
    }

    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [searchQuery, currentProject?.id]);

  // Focus the edit input when entering edit mode
  useEffect(() => {
    if (editingId && editInputRef.current) {
      editInputRef.current.focus();
      editInputRef.current.select();
    }
  }, [editingId]);

  const handleSaveTitle = useCallback(async () => {
    if (!editingId || !editTitle.trim()) {
      setEditingId(null);
      return;
    }
    try {
      await updateConversationTitle(editingId, editTitle.trim());
      await refreshConversations();
    } catch (err) {
      console.error('Failed to rename conversation:', err);
      toast.error('Failed to rename conversation');
    }
    setEditingId(null);
  }, [editingId, editTitle, refreshConversations]);

  // Local filtering for short queries, server search for 3+ chars
  const filteredConversations = searchResults !== null
    ? [] // When using server search, don't show local results
    : conversations.filter(c =>
        !searchQuery || c.title.toLowerCase().includes(searchQuery.toLowerCase())
      );

  const sortedConversations = [...filteredConversations].sort((a, b) => {
    if (a.is_starred && !b.is_starred) return -1;
    if (!a.is_starred && b.is_starred) return 1;
    return new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime();
  });

  // Determine which list to display
  const displayList = searchResults !== null ? searchResults : sortedConversations;

  async function handleToggleStar(e: React.MouseEvent, conv: Conversation) {
    e.stopPropagation();
    try {
      await toggleConversationStar(conv.id);
      await refreshConversations();
    } catch (err) {
      console.error('Failed to toggle star:', err);
      toast.error('Failed to update star');
    }
  }

  async function handleExport(e: React.MouseEvent, conv: Conversation) {
    e.stopPropagation();
    try {
      await exportConversation(conv);
    } catch {
      // silently fail
    }
  }

  function handleListKeyDown(e: React.KeyboardEvent) {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setFocusedIndex(i => Math.min(i + 1, displayList.length - 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setFocusedIndex(i => Math.max(i - 1, 0));
    } else if (e.key === 'Enter' && focusedIndex >= 0 && focusedIndex < displayList.length) {
      e.preventDefault();
      switchConversation(displayList[focusedIndex].id);
    }
  }

  function highlightSnippet(snippet: string, query: string) {
    if (!query) return snippet;
    const idx = snippet.toLowerCase().indexOf(query.toLowerCase());
    if (idx === -1) return snippet;
    return (
      <>
        {snippet.slice(0, idx)}
        <mark style={{ background: 'rgba(59, 130, 246, 0.25)', color: 'inherit', borderRadius: '2px', padding: '0 1px' }}>
          {snippet.slice(idx, idx + query.length)}
        </mark>
        {snippet.slice(idx + query.length)}
      </>
    );
  }

  return (
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      height: '100%',
      background: 'var(--background)',
      borderRight: '1px solid var(--border)',
    }}>
      {/* New Chat Button */}
      <div style={{ padding: '0.75rem' }}>
        <button
          onClick={createNewConversation}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '0.5rem',
            width: '100%',
            padding: '0.6rem 0.75rem',
            background: 'rgba(59, 130, 246, 0.1)',
            border: '1px solid rgba(59, 130, 246, 0.2)',
            borderRadius: '8px',
            color: 'var(--primary)',
            fontSize: '0.85rem',
            fontWeight: 600,
            cursor: 'pointer',
            transition: 'background 0.2s',
          }}
        >
          <Plus size={16} />
          New Chat
        </button>
      </div>

      {/* Search Input */}
      <div style={{ padding: '0 0.75rem 0.5rem' }}>
        <div style={{
          display: 'flex',
          alignItems: 'center',
          gap: '0.4rem',
          padding: '0.4rem 0.6rem',
          background: 'var(--surface)',
          border: '1px solid var(--border)',
          borderRadius: '6px',
        }}>
          <Search size={13} style={{ color: 'var(--text-secondary)', flexShrink: 0 }} />
          <input
            ref={searchInputRef}
            type="text"
            placeholder="Search conversations..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            aria-label="Search conversations"
            style={{
              flex: 1,
              border: 'none',
              outline: 'none',
              background: 'transparent',
              color: 'var(--text)',
              fontSize: '0.78rem',
            }}
          />
          {isSearching && (
            <div className="loading-spinner" style={{ width: '12px', height: '12px', borderWidth: '1.5px', flexShrink: 0 }} />
          )}
        </div>
      </div>

      {/* Conversation List */}
      <div
        ref={listRef}
        role="listbox"
        tabIndex={0}
        onKeyDown={handleListKeyDown}
        style={{
          flex: 1,
          overflowY: 'auto',
          padding: '0 0.5rem 0.5rem',
          outline: 'none',
        }}
      >
        {displayList.length === 0 && (
          <div style={{
            padding: '2rem 1rem',
            textAlign: 'center',
            color: 'var(--text-secondary)',
            fontSize: '0.8rem',
          }}>
            {searchQuery ? 'No matching conversations' : 'No conversations yet'}
          </div>
        )}

        {/* Server search results */}
        {searchResults !== null && searchResults.map((result, index) => {
          const isActive = result.id === conversationId;
          const isFocused = index === focusedIndex;
          return (
            <div
              key={result.id}
              role="option"
              aria-selected={isActive}
              onClick={() => switchConversation(result.id)}
              style={{
                display: 'flex',
                flexDirection: 'column',
                gap: '0.2rem',
                padding: '0.6rem 0.75rem',
                borderRadius: '8px',
                cursor: 'pointer',
                background: isActive
                  ? 'rgba(59, 130, 246, 0.15)'
                  : isFocused
                    ? 'var(--surface-hover)'
                    : 'transparent',
                marginBottom: '2px',
                transition: 'background 0.15s',
              }}
            >
              <div style={{
                fontSize: '0.82rem',
                fontWeight: isActive ? 600 : 400,
                color: 'var(--text)',
                whiteSpace: 'nowrap',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
              }}>
                {result.title}
              </div>
              {result.snippet && (
                <div style={{
                  fontSize: '0.7rem',
                  color: 'var(--text-secondary)',
                  whiteSpace: 'nowrap',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  lineHeight: 1.3,
                }}>
                  {highlightSnippet(result.snippet, searchQuery)}
                </div>
              )}
            </div>
          );
        })}

        {/* Local conversation list */}
        {searchResults === null && sortedConversations.map((conv, index) => {
          const isActive = conv.id === conversationId;
          const isHovered = conv.id === hoveredId;
          const isFocused = index === focusedIndex;
          const isEditing = conv.id === editingId;
          return (
            <div
              key={conv.id}
              role="option"
              aria-selected={isActive}
              onClick={() => { if (!isEditing) switchConversation(conv.id); }}
              onMouseEnter={() => setHoveredId(conv.id)}
              onMouseLeave={() => setHoveredId(null)}
              style={{
                position: 'relative',
                display: 'flex',
                alignItems: 'center',
                gap: '0.5rem',
                padding: '0.6rem 0.75rem',
                borderRadius: '8px',
                cursor: isEditing ? 'default' : 'pointer',
                background: isActive
                  ? 'rgba(59, 130, 246, 0.15)'
                  : (isHovered || isFocused)
                    ? 'var(--surface-hover)'
                    : 'transparent',
                marginBottom: '2px',
                transition: 'background 0.15s',
              }}
            >
              <MessageSquare size={14} style={{ color: 'var(--text-secondary)', flexShrink: 0 }} />
              <div style={{ flex: 1, minWidth: 0 }}>
                {isEditing ? (
                  <input
                    ref={editInputRef}
                    type="text"
                    value={editTitle}
                    onChange={(e) => setEditTitle(e.target.value)}
                    onBlur={handleSaveTitle}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') {
                        e.preventDefault();
                        handleSaveTitle();
                      } else if (e.key === 'Escape') {
                        e.preventDefault();
                        setEditingId(null);
                      }
                    }}
                    onClick={(e) => e.stopPropagation()}
                    style={{
                      width: '100%',
                      fontSize: '0.82rem',
                      fontWeight: isActive ? 600 : 400,
                      color: 'var(--text)',
                      background: 'transparent',
                      border: 'none',
                      outline: 'none',
                      padding: 0,
                      margin: 0,
                      lineHeight: 'inherit',
                    }}
                  />
                ) : (
                  <div
                    onDoubleClick={(e) => {
                      e.stopPropagation();
                      setEditingId(conv.id);
                      setEditTitle(conv.title);
                    }}
                    style={{
                      fontSize: '0.82rem',
                      fontWeight: isActive ? 600 : 400,
                      color: 'var(--text)',
                      whiteSpace: 'nowrap',
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                    }}
                  >
                    {conv.title}
                  </div>
                )}
                <div style={{
                  fontSize: '0.7rem',
                  color: 'var(--text-secondary)',
                  marginTop: '1px',
                }}>
                  {relativeTime(conv.updated_at)}{conv.message_count ? ` · ${conv.message_count} msgs` : ''}
                </div>
              </div>
              {/* Star button - visible on hover or if starred */}
              {(isHovered || conv.is_starred) && (
                <button
                  onClick={(e) => handleToggleStar(e, conv)}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    width: '24px',
                    height: '24px',
                    borderRadius: '4px',
                    color: conv.is_starred ? '#f59e0b' : 'var(--text-secondary)',
                    cursor: 'pointer',
                    flexShrink: 0,
                    background: 'transparent',
                    border: 'none',
                    padding: 0,
                  }}
                  title={conv.is_starred ? 'Unstar conversation' : 'Star conversation'}
                >
                  <Star size={13} fill={conv.is_starred ? '#f59e0b' : 'none'} />
                </button>
              )}
              {/* Export button - visible on hover */}
              {isHovered && (
                <button
                  onClick={(e) => handleExport(e, conv)}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    width: '24px',
                    height: '24px',
                    borderRadius: '4px',
                    color: 'var(--text-secondary)',
                    cursor: 'pointer',
                    flexShrink: 0,
                    background: 'transparent',
                    border: 'none',
                    padding: 0,
                  }}
                  title="Export conversation"
                >
                  <Download size={13} />
                </button>
              )}
              {/* Delete button - visible on hover */}
              {isHovered && pendingDeleteId !== conv.id && (
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    setPendingDeleteId(conv.id);
                  }}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    width: '24px',
                    height: '24px',
                    borderRadius: '4px',
                    color: 'var(--text-secondary)',
                    cursor: 'pointer',
                    flexShrink: 0,
                    background: 'transparent',
                    border: 'none',
                    padding: 0,
                  }}
                  title="Delete conversation"
                >
                  <Trash2 size={13} />
                </button>
              )}
              {/* Delete confirmation */}
              {pendingDeleteId === conv.id && (
                <div
                  onClick={(e) => e.stopPropagation()}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '0.25rem',
                    flexShrink: 0,
                  }}
                >
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      deleteConversation(conv.id);
                      setPendingDeleteId(null);
                    }}
                    style={{
                      fontSize: '0.65rem',
                      fontWeight: 600,
                      padding: '0.15rem 0.4rem',
                      borderRadius: '4px',
                      border: 'none',
                      background: 'rgba(239, 68, 68, 0.15)',
                      color: 'var(--danger)',
                      cursor: 'pointer',
                    }}
                  >
                    Delete
                  </button>
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      setPendingDeleteId(null);
                    }}
                    style={{
                      fontSize: '0.65rem',
                      padding: '0.15rem 0.4rem',
                      borderRadius: '4px',
                      border: 'none',
                      background: 'var(--surface)',
                      color: 'var(--text-secondary)',
                      cursor: 'pointer',
                    }}
                  >
                    Cancel
                  </button>
                </div>
              )}
              {isHovered && (conv as Conversation).summary && (
                <div style={{
                  position: 'absolute',
                  top: '100%',
                  left: '0.5rem',
                  right: '0.5rem',
                  zIndex: 20,
                  marginTop: '2px',
                  padding: '0.4rem 0.6rem',
                  background: 'var(--surface)',
                  border: '1px solid var(--border)',
                  borderRadius: '6px',
                  boxShadow: '0 4px 12px rgba(0,0,0,0.15)',
                  fontSize: '0.7rem',
                  color: 'var(--text-secondary)',
                  lineHeight: 1.4,
                  whiteSpace: 'normal',
                  pointerEvents: 'none',
                }}>
                  {(conv as Conversation).summary}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
