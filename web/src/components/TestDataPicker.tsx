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
  insertLabel?: string;
  editLabel?: string;
  compact?: boolean;
  onInsert: (value: string) => void;
  onInserted?: () => void;
}

export function TestDataPicker({
  projectId,
  mode = 'directive',
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
