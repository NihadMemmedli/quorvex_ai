'use client';

import { useEffect, useMemo, useState } from 'react';
import { Database, Edit, Plus } from 'lucide-react';
import { useRouter } from 'next/navigation';
import { API_BASE } from '@/lib/api';
import { fetchWithAuth } from '@/contexts/AuthContext';
import { Button } from '@/components/ui/button';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';

interface Dataset {
  id: string;
  key: string;
  name: string;
}

interface Item {
  id: string;
  key: string;
  ref: string;
  name?: string;
}

interface TestDataPickerProps {
  projectId?: string | null;
  mode?: 'directive' | 'ref';
  variant?: 'default' | 'sidebar';
  insertLabel?: string;
  editLabel?: string;
  compact?: boolean;
  onInsert: (value: string) => void;
  onInserted?: () => void;
}

export function TestDataPicker({
  projectId,
  mode = 'directive',
  variant = 'default',
  insertLabel = 'Insert',
  editLabel = 'Edit',
  compact = false,
  onInsert,
  onInserted,
}: TestDataPickerProps) {
  const router = useRouter();
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [items, setItems] = useState<Item[]>([]);
  const [datasetId, setDatasetId] = useState('');
  const [itemRef, setItemRef] = useState('');

  const selectedDataset = useMemo(() => datasets.find(dataset => dataset.id === datasetId), [datasets, datasetId]);
  const selectedItem = useMemo(() => items.find(item => item.ref === itemRef), [items, itemRef]);

  useEffect(() => {
    if (!projectId) return;
    fetchWithAuth(`${API_BASE}/test-data/datasets?project_id=${encodeURIComponent(projectId)}&status=active`)
      .then(async response => (response.ok ? response.json() : { datasets: [] }))
      .then(data => {
        const next = data.datasets || [];
        setDatasets(next);
        setDatasetId(next[0]?.id || '');
      })
      .catch(() => setDatasets([]));
  }, [projectId]);

  useEffect(() => {
    if (!datasetId) {
      setItems([]);
      setItemRef('');
      return;
    }
    fetchWithAuth(`${API_BASE}/test-data/datasets/${encodeURIComponent(datasetId)}/items?status=active`)
      .then(async response => (response.ok ? response.json() : { items: [] }))
      .then(data => {
        const next = data.items || [];
        setItems(next);
        setItemRef(next[0]?.ref || '');
      })
      .catch(() => setItems([]));
  }, [datasetId]);

  const handleInsert = () => {
    onInsert(mode === 'directive' ? `@testdata "${itemRef}"` : itemRef);
    onInserted?.();
  };

  if (!projectId || !datasets.length) return null;

  const isSidebar = variant === 'sidebar';
  const sidebarDatasetLabel = selectedDataset?.name || selectedDataset?.key || 'Dataset';
  const sidebarItemLabel = selectedItem?.name || selectedItem?.key || itemRef.split('.').pop() || 'Item';
  const sidebarItemRef = selectedItem?.ref || itemRef;
  const triggerTextStyle = {
    display: 'block',
    minWidth: 0,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
    textAlign: 'left' as const,
  };
  const triggerStyle = isSidebar
    ? {
        height: '36px',
        minHeight: '36px',
        borderRadius: '8px',
        background: 'var(--background-raised)',
        fontSize: '0.8rem',
        overflow: 'hidden',
      }
    : undefined;
  const actionStyle = isSidebar
    ? {
        height: '34px',
        minHeight: '34px',
        borderRadius: '8px',
        fontSize: '0.78rem',
        padding: '0 0.65rem',
        width: '100%',
      }
    : undefined;
  const sidebarContentStyle = {
    background: 'var(--background-raised)',
    border: '1px solid var(--border-bright)',
    borderRadius: '10px',
    boxShadow: '0 16px 36px rgba(0, 0, 0, 0.48)',
    width: 'var(--radix-select-trigger-width)',
    minWidth: 'var(--radix-select-trigger-width)',
    maxWidth: 'min(420px, calc(100vw - 2rem))',
    zIndex: 1000,
  };
  const sidebarItemStyle = {
    minHeight: '34px',
    whiteSpace: 'nowrap',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    fontSize: '0.8rem',
  };

  if (isSidebar) {
    return (
      <div
        style={{ display: 'grid', gap: '0.5rem', width: '100%' }}
        data-testid={`test-data-picker-${mode}`}
      >
        <div style={{ display: 'grid', gap: '0.45rem', minWidth: 0 }}>
          {datasets.length <= 1 ? (
            <div
              data-testid="test-data-picker-dataset"
              title={sidebarDatasetLabel}
              aria-label="Test data dataset"
              style={{
                ...triggerStyle,
                display: 'flex',
                alignItems: 'center',
                padding: '0 12px',
                border: '1px solid var(--border)',
                color: 'var(--text)',
              }}
            >
              <span style={triggerTextStyle}>
                {sidebarDatasetLabel}
              </span>
            </div>
          ) : (
            <Select value={datasetId} onValueChange={setDatasetId}>
              <SelectTrigger
                style={triggerStyle}
                data-testid="test-data-picker-dataset"
                aria-label="Test data dataset"
              >
                <span title={sidebarDatasetLabel} style={triggerTextStyle}>
                  {sidebarDatasetLabel}
                </span>
              </SelectTrigger>
              <SelectContent style={sidebarContentStyle}>
                {datasets.map(dataset => {
                  const label = dataset.name || dataset.key;
                  return (
                    <SelectItem
                      key={dataset.id}
                      value={dataset.id}
                      textValue={label}
                      style={sidebarItemStyle}
                    >
                      {label}
                    </SelectItem>
                  );
                })}
              </SelectContent>
            </Select>
          )}
          {items.length <= 1 ? (
            <div
              data-testid="test-data-picker-item"
              title={sidebarItemRef}
              aria-label="Test data item"
              style={{
                ...triggerStyle,
                display: 'flex',
                alignItems: 'center',
                padding: '0 12px',
                border: '1px solid var(--border)',
                color: 'var(--text)',
              }}
            >
              <span style={triggerTextStyle}>
                {sidebarItemLabel}
              </span>
            </div>
          ) : (
            <Select value={itemRef} onValueChange={setItemRef}>
              <SelectTrigger
                style={triggerStyle}
                data-testid="test-data-picker-item"
                aria-label="Test data item"
              >
                <span title={sidebarItemRef} style={triggerTextStyle}>
                  {sidebarItemLabel}
                </span>
              </SelectTrigger>
              <SelectContent style={sidebarContentStyle}>
                {items.map(item => {
                  const label = item.name || item.key;
                  return (
                    <SelectItem
                      key={item.id}
                      value={item.ref}
                      textValue={label}
                      title={item.ref}
                      style={sidebarItemStyle}
                    >
                      {label}
                    </SelectItem>
                  );
                })}
              </SelectContent>
            </Select>
          )}
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 1fr)', gap: '0.45rem', minWidth: 0 }}>
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={!itemRef}
            data-testid="test-data-picker-insert"
            onClick={handleInsert}
            style={actionStyle}
          >
            <Plus size={14} /> {insertLabel}
          </Button>
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={!itemRef}
            data-testid="test-data-picker-edit"
            onClick={() => itemRef && router.push(`/test-data?ref=${encodeURIComponent(itemRef)}`)}
            style={actionStyle}
          >
            <Edit size={14} /> {editLabel}
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div
      className="flex flex-wrap items-center gap-2"
      style={compact ? { width: '100%' } : undefined}
      data-testid={`test-data-picker-${mode}`}
    >
      {!compact && <Database size={16} style={{ color: 'var(--text-secondary)' }} />}
      <Select value={datasetId} onValueChange={setDatasetId}>
        <SelectTrigger className={compact ? 'h-9 min-w-[160px] flex-1' : 'h-9 w-[180px]'} data-testid="test-data-picker-dataset"><SelectValue placeholder="Dataset" /></SelectTrigger>
        <SelectContent>
          {datasets.map(dataset => <SelectItem key={dataset.id} value={dataset.id}>{dataset.name || dataset.key}</SelectItem>)}
        </SelectContent>
      </Select>
      <Select value={itemRef} onValueChange={setItemRef}>
        <SelectTrigger className={compact ? 'h-9 min-w-[180px] flex-[1.2]' : 'h-9 w-[220px]'} data-testid="test-data-picker-item"><SelectValue placeholder="Item" /></SelectTrigger>
        <SelectContent>
          {items.map(item => <SelectItem key={item.id} value={item.ref}>{selectedDataset?.key}.{item.key}</SelectItem>)}
        </SelectContent>
      </Select>
      <Button
        type="button"
        size="sm"
        variant={compact ? 'ghost' : 'outline'}
        disabled={!itemRef}
        data-testid="test-data-picker-insert"
        onClick={handleInsert}
      >
        <Plus size={16} /> {insertLabel}
      </Button>
      <Button
        type="button"
        size="sm"
        variant="ghost"
        disabled={!itemRef}
        data-testid="test-data-picker-edit"
        onClick={() => itemRef && router.push(`/test-data?ref=${encodeURIComponent(itemRef)}`)}
      >
        <Edit size={16} /> {editLabel}
      </Button>
    </div>
  );
}
