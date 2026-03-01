'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import { MessageSquare, X, History, MessageCircle } from 'lucide-react';
import { Toaster } from 'sonner';
import { AssistantThread } from './AssistantThread';
import { ConversationList } from './ConversationList';
import { API_BASE } from '@/lib/api';
import { fetchWithAuth } from '@/contexts/AuthContext';

const DEFAULT_PANEL_SIZE = { width: 420, height: 600 };
const MIN_WIDTH = 320;
const MIN_HEIGHT = 400;

function loadPanelSize(): { width: number; height: number } {
  if (typeof window === 'undefined') return DEFAULT_PANEL_SIZE;
  try {
    const saved = localStorage.getItem('chat-bubble-size');
    if (saved) {
      const parsed = JSON.parse(saved);
      if (parsed.width >= MIN_WIDTH && parsed.height >= MIN_HEIGHT) return parsed;
    }
  } catch { /* ignore */ }
  return DEFAULT_PANEL_SIZE;
}

export function ChatBubble() {
  const [isOpen, setIsOpen] = useState(false);
  const [hasFailures, setHasFailures] = useState(false);
  const [isMobile, setIsMobile] = useState(false);
  const [bubbleTab, setBubbleTab] = useState<'chat' | 'history'>('chat');
  const [panelSize, setPanelSize] = useState(loadPanelSize);
  const isResizing = useRef(false);
  const resizeStart = useRef({ x: 0, y: 0, w: 0, h: 0 });

  const toggle = useCallback(() => setIsOpen((prev) => !prev), []);

  // Keyboard shortcut: Cmd+Shift+K (Mac) / Ctrl+Shift+K (Windows)
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.shiftKey && e.key === 'K') {
        e.preventDefault();
        toggle();
      }
    }
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [toggle]);

  // Listen for custom event from command palette
  useEffect(() => {
    function handleOpenAssistant() {
      setIsOpen(true);
    }
    window.addEventListener('open-ai-assistant', handleOpenAssistant);
    return () => window.removeEventListener('open-ai-assistant', handleOpenAssistant);
  }, []);

  // Fetch project context for notification dot
  useEffect(() => {
    async function checkFailures() {
      try {
        const res = await fetchWithAuth(`${API_BASE}/chat/project-context`);
        if (res.ok) {
          const data = await res.json();
          setHasFailures(data.recent_failures > 0);
        }
      } catch { /* ignore */ }
    }
    checkFailures();
    const interval = setInterval(checkFailures, 5 * 60 * 1000);
    return () => clearInterval(interval);
  }, []);

  // Mobile detection for full-screen panel
  useEffect(() => {
    function handleResize() {
      setIsMobile(window.innerWidth < 768);
    }
    handleResize();
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  // Resize handlers
  const handleResizeMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    isResizing.current = true;
    resizeStart.current = { x: e.clientX, y: e.clientY, w: panelSize.width, h: panelSize.height };

    function onMouseMove(ev: MouseEvent) {
      if (!isResizing.current) return;
      const dx = resizeStart.current.x - ev.clientX;
      const dy = resizeStart.current.y - ev.clientY;
      const maxW = Math.floor(window.innerWidth * 0.8);
      const maxH = Math.floor(window.innerHeight * 0.8);
      const newW = Math.min(maxW, Math.max(MIN_WIDTH, resizeStart.current.w + dx));
      const newH = Math.min(maxH, Math.max(MIN_HEIGHT, resizeStart.current.h + dy));
      setPanelSize({ width: newW, height: newH });
    }

    function onMouseUp() {
      if (isResizing.current) {
        isResizing.current = false;
        setPanelSize((current) => {
          try {
            localStorage.setItem('chat-bubble-size', JSON.stringify(current));
          } catch { /* ignore */ }
          return current;
        });
      }
      document.removeEventListener('mousemove', onMouseMove);
      document.removeEventListener('mouseup', onMouseUp);
    }

    document.addEventListener('mousemove', onMouseMove);
    document.addEventListener('mouseup', onMouseUp);
  }, [panelSize]);

  // Reset tab to chat when opening
  useEffect(() => {
    if (isOpen) setBubbleTab('chat');
  }, [isOpen]);

  const panelStyle = isMobile && isOpen
    ? {
        position: 'fixed' as const,
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        width: '100%',
        height: '100%',
        background: 'var(--background)',
        borderRadius: 0,
        border: 'none',
        display: 'flex' as const,
        flexDirection: 'column' as const,
        overflow: 'hidden' as const,
        zIndex: 1000,
      }
    : {
        position: 'fixed' as const,
        bottom: '88px',
        right: '24px',
        width: `${panelSize.width}px`,
        height: `${panelSize.height}px`,
        maxHeight: 'calc(100vh - 120px)',
        background: 'var(--background)',
        border: '1px solid var(--border)',
        borderRadius: '16px',
        boxShadow: '0 20px 60px rgba(0, 0, 0, 0.4)',
        display: 'flex' as const,
        flexDirection: 'column' as const,
        overflow: 'hidden' as const,
        zIndex: 1000,
        animation: 'chatSlideUp 0.2s ease-out',
      };

  const tabButtonStyle = (active: boolean) => ({
    display: 'flex' as const,
    alignItems: 'center' as const,
    gap: '0.3rem',
    padding: '0.25rem 0.5rem',
    fontSize: '0.75rem',
    fontWeight: active ? 600 : 400,
    color: active ? 'var(--primary)' : 'var(--text-secondary)',
    background: active ? 'rgba(59, 130, 246, 0.1)' : 'transparent',
    border: 'none',
    borderRadius: '4px',
    cursor: 'pointer' as const,
  });

  return (
    <>
      {/* Chat Panel */}
      {isOpen && (
        <div role="dialog" aria-label="AI Assistant" style={panelStyle}>
          {/* Resize handle (top-left corner) - desktop only */}
          {!isMobile && (
            <div
              onMouseDown={handleResizeMouseDown}
              style={{
                position: 'absolute',
                top: 0,
                left: 0,
                width: '16px',
                height: '16px',
                cursor: 'nw-resize',
                zIndex: 10,
              }}
              title="Drag to resize"
            >
              <svg width="10" height="10" viewBox="0 0 10 10" style={{ position: 'absolute', top: '3px', left: '3px', opacity: 0.3 }}>
                <line x1="0" y1="10" x2="10" y2="0" stroke="var(--text-secondary)" strokeWidth="1.5" />
                <line x1="0" y1="6" x2="6" y2="0" stroke="var(--text-secondary)" strokeWidth="1.5" />
              </svg>
            </div>
          )}

          {/* Header */}
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              padding: '0.75rem 1rem',
              borderBottom: '1px solid var(--border)',
              background: 'var(--surface)',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <div
                style={{
                  width: '28px',
                  height: '28px',
                  borderRadius: '8px',
                  background: 'rgba(59, 130, 246, 0.15)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  fontSize: '0.7rem',
                  fontWeight: 700,
                  color: 'var(--primary)',
                }}
              >
                AI
              </div>
              <span style={{ fontWeight: 600, fontSize: '0.9rem' }}>AI Assistant</span>
              {/* Tab toggle */}
              <div role="tablist" style={{ display: 'flex', alignItems: 'center', gap: '0.15rem', marginLeft: '0.25rem' }}>
                <button role="tab" aria-selected={bubbleTab === 'chat'} onClick={() => setBubbleTab('chat')} style={tabButtonStyle(bubbleTab === 'chat')}>
                  <MessageCircle size={12} />
                  Chat
                </button>
                <button role="tab" aria-selected={bubbleTab === 'history'} onClick={() => setBubbleTab('history')} style={tabButtonStyle(bubbleTab === 'history')}>
                  <History size={12} />
                  History
                </button>
              </div>
            </div>
            <button
              onClick={toggle}
              aria-label="Close assistant"
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                width: '28px',
                height: '28px',
                borderRadius: '6px',
                cursor: 'pointer',
                color: 'var(--text-secondary)',
              }}
            >
              <X size={16} />
            </button>
          </div>

          {/* Content: Thread or History */}
          <div style={{ flex: 1, overflow: 'hidden' }}>
            {bubbleTab === 'chat' ? (
              <AssistantThread />
            ) : (
              <ConversationList />
            )}
          </div>
          <Toaster position="top-center" richColors closeButton duration={3000} />
        </div>
      )}

      {/* Floating Button */}
      <button
        onClick={toggle}
        aria-label={isOpen ? 'Close AI assistant' : 'Open AI assistant'}
        title="AI Assistant (Cmd+Shift+K)"
        style={{
          position: 'fixed',
          bottom: '24px',
          right: '24px',
          width: '52px',
          height: '52px',
          borderRadius: '50%',
          background: 'var(--primary)',
          color: 'white',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          boxShadow: '0 4px 12px rgba(59, 130, 246, 0.4)',
          cursor: 'pointer',
          transition: 'transform 0.2s, box-shadow 0.2s',
          zIndex: 1001,
        }}
        onMouseOver={(e) => {
          e.currentTarget.style.transform = 'scale(1.05)';
          e.currentTarget.style.boxShadow = '0 6px 20px rgba(59, 130, 246, 0.5)';
        }}
        onMouseOut={(e) => {
          e.currentTarget.style.transform = 'scale(1)';
          e.currentTarget.style.boxShadow = '0 4px 12px rgba(59, 130, 246, 0.4)';
        }}
      >
        {/* Notification dot */}
        {hasFailures && !isOpen && (
          <span style={{
            position: 'absolute',
            top: '-2px',
            right: '-2px',
            width: '12px',
            height: '12px',
            borderRadius: '50%',
            background: 'var(--danger)',
            border: '2px solid var(--background)',
            animation: 'pulse 2s ease-in-out infinite',
          }} />
        )}
        {isOpen ? <X size={22} /> : <MessageSquare size={22} />}
      </button>

      {/* Keyboard shortcut badge - visible when bubble is closed */}
      {!isOpen && (
        <div style={{
          position: 'fixed',
          bottom: '8px',
          right: '24px',
          width: '52px',
          textAlign: 'center',
          zIndex: 1001,
          pointerEvents: 'none',
        }}>
          <kbd style={{
            fontSize: '0.6rem',
            color: 'var(--text-secondary)',
            background: 'var(--surface)',
            border: '1px solid var(--border)',
            borderRadius: '3px',
            padding: '1px 4px',
            opacity: 0.7,
          }}>
            {typeof navigator !== 'undefined' && /Mac/.test(navigator.userAgent) ? '\u2318\u21E7K' : 'Ctrl+Shift+K'}
          </kbd>
        </div>
      )}
    </>
  );
}
