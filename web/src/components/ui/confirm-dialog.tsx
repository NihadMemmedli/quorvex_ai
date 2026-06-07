'use client';

import { useEffect, useState } from 'react';

interface ConfirmDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description: string;
  confirmLabel?: string;
  cancelLabel?: string;
  variant?: 'danger' | 'default';
  onConfirm: () => void | Promise<void>;
  loading?: boolean;
}

export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  confirmLabel = 'Confirm',
  cancelLabel = 'Cancel',
  variant = 'default',
  onConfirm,
  loading = false,
}: ConfirmDialogProps) {
  const [confirming, setConfirming] = useState(false);
  const isLoading = loading || confirming;

  useEffect(() => {
    if (!open) return;

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !isLoading) {
        onOpenChange(false);
      }
    };

    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [isLoading, onOpenChange, open]);

  const handleOpenChange = (nextOpen: boolean) => {
    if (isLoading && !nextOpen) return;
    onOpenChange(nextOpen);
  };

  const handleConfirm = async () => {
    if (isLoading) return;
    setConfirming(true);
    try {
      await onConfirm();
      onOpenChange(false);
    } catch {
      // Callers own error presentation; keep the dialog open so users can retry.
    } finally {
      setConfirming(false);
    }
  };

  if (!open) return null;

  return (
    <div
      role="presentation"
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 20000,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '1rem',
      }}
    >
      <button
        type="button"
        aria-label="Close confirmation"
        onClick={() => handleOpenChange(false)}
        disabled={isLoading}
        style={{
          position: 'fixed',
          inset: 0,
          zIndex: 20000,
          background: 'rgba(0, 0, 0, 0.85)',
          backdropFilter: 'blur(4px)',
          border: 0,
          cursor: isLoading ? 'not-allowed' : 'default',
        }}
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="confirm-dialog-title"
        aria-describedby="confirm-dialog-description"
        style={{
          position: 'relative',
          zIndex: 20001,
          width: 'min(420px, 100%)',
          display: 'grid',
          gap: '1rem',
          background: 'var(--surface)',
          border: '1px solid var(--border-subtle)',
          borderRadius: 'var(--radius-lg)',
          boxShadow: 'var(--shadow-card)',
          color: 'var(--text)',
          padding: '1.5rem',
        }}
      >
        <button
          type="button"
          aria-label="Close"
          onClick={() => handleOpenChange(false)}
          disabled={isLoading}
          style={{
            position: 'absolute',
            right: '1rem',
            top: '1rem',
            width: '1.75rem',
            height: '1.75rem',
            display: 'inline-flex',
            alignItems: 'center',
            justifyContent: 'center',
            background: 'transparent',
            color: 'var(--text-secondary)',
            border: 0,
            borderRadius: 'var(--radius-sm)',
            cursor: isLoading ? 'not-allowed' : 'pointer',
            fontSize: '1rem',
            lineHeight: 1,
            opacity: 0.8,
          }}
        >
          X
        </button>
        <div style={{ display: 'grid', gap: '0.5rem', paddingRight: '1.75rem' }}>
          <h2
            id="confirm-dialog-title"
            style={{ margin: 0, fontSize: '1.125rem', fontWeight: 600, lineHeight: 1.2, letterSpacing: 0 }}
          >
            {title}
          </h2>
          <p
            id="confirm-dialog-description"
            style={{ margin: 0, color: 'var(--text-secondary)', fontSize: '0.875rem', lineHeight: 1.5 }}
          >
            {description}
          </p>
        </div>
        <div style={{ display: 'flex', flexWrap: 'wrap', justifyContent: 'flex-end', gap: '0.5rem' }}>
          <button
            type="button"
            onClick={() => handleOpenChange(false)}
            disabled={isLoading}
            style={{
              padding: '0.5rem 1rem',
              background: 'transparent',
              color: 'var(--text-secondary)',
              border: '1px solid var(--border)',
              borderRadius: 'var(--radius)',
              cursor: 'pointer',
              fontWeight: 500,
              fontSize: '0.85rem',
              transition: 'all 0.2s var(--ease-smooth)',
            }}
          >
            {cancelLabel}
          </button>
          <button
            type="button"
            onClick={handleConfirm}
            disabled={isLoading}
            style={{
              padding: '0.5rem 1rem',
              background: variant === 'danger' ? 'var(--danger)' : 'var(--primary)',
              color: 'white',
              border: 'none',
              borderRadius: 'var(--radius)',
              cursor: isLoading ? 'not-allowed' : 'pointer',
              fontWeight: 600,
              fontSize: '0.85rem',
              opacity: isLoading ? 0.7 : 1,
              transition: 'all 0.2s var(--ease-smooth)',
            }}
          >
            {isLoading ? 'Processing...' : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
