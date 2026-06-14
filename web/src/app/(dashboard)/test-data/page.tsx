'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import {
  Archive,
  Copy,
  Database,
  FileJson,
  KeyRound,
  Layers3,
  Loader2,
  Plus,
  RefreshCw,
  Save,
  ShieldCheck,
  Trash2,
} from 'lucide-react';
import { toast } from 'sonner';
import { API_BASE } from '@/lib/api';
import { fetchWithAuth } from '@/contexts/AuthContext';
import { useProject } from '@/contexts/ProjectContext';
import { PageLayout } from '@/components/ui/page-layout';
import { PageHeader } from '@/components/ui/page-header';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { EmptyState } from '@/components/ui/empty-state';
import { Skeleton } from '@/components/ui/skeleton';
import { ConfirmDialog } from '@/components/ui/confirm-dialog';
import { Switch } from '@/components/ui/switch';
import { cn } from '@/lib/utils';

type DataFormat = 'json' | 'text' | 'mixed';
type DataStatus = 'active' | 'archived';

interface TestDataSet {
  id: string;
  project_id: string;
  key: string;
  name: string;
  description: string;
  tags: string[];
  status: DataStatus;
  format: DataFormat;
  item_count?: number;
}

interface TestDataItem {
  id: string;
  dataset_id: string;
  dataset_key: string;
  ref: string;
  key: string;
  name: string;
  description: string;
  status: DataStatus;
  format: DataFormat;
  data: unknown;
  text?: string | null;
  sensitive_fields: string[];
  placeholders: Record<string, string>;
}

const emptyDataset = {
  key: '',
  name: '',
  description: '',
  tags: '',
  status: 'active' as DataStatus,
  format: 'json' as DataFormat,
};

const emptyItem = {
  key: 'valid-admin',
  name: 'Valid admin',
  description: '',
  status: 'active' as DataStatus,
  format: 'json' as DataFormat,
  dataText: '{\n  "email": "admin@example.com",\n  "password": "replace-me"\n}',
  text: '',
  sensitiveFields: '',
};

const selectableRowClass = 'test-data-selectable';

const textareaClass = 'test-data-textarea';

async function readError(response: Response, fallback: string) {
  const text = await response.text();
  if (!text) return fallback;
  try {
    const parsed = JSON.parse(text);
    return typeof parsed.detail === 'string' ? parsed.detail : fallback;
  } catch {
    return text;
  }
}

function parseSensitiveFields(value: string) {
  return value.split(',').map(field => field.trim()).filter(Boolean);
}

function formatSensitiveFields(fields: string[]) {
  return fields.join(', ');
}

function toggleSensitiveField(value: string, field: string, enabled: boolean) {
  const fields = parseSensitiveFields(value);
  const withoutField = fields.filter(candidate => candidate !== field);
  return enabled ? [...withoutField, field] : withoutField;
}

export default function TestDataPage() {
  const { currentProject } = useProject();
  const [datasets, setDatasets] = useState<TestDataSet[]>([]);
  const [selectedDatasetId, setSelectedDatasetId] = useState<string>('');
  const [items, setItems] = useState<TestDataItem[]>([]);
  const [selectedItemId, setSelectedItemId] = useState<string>('');
  const [loading, setLoading] = useState(false);
  const [itemsLoading, setItemsLoading] = useState(false);
  const [savingDataset, setSavingDataset] = useState(false);
  const [savingItem, setSavingItem] = useState(false);
  const [deletingDataset, setDeletingDataset] = useState(false);
  const [deletingItem, setDeletingItem] = useState(false);
  const [deleteDatasetOpen, setDeleteDatasetOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [datasetForm, setDatasetForm] = useState(emptyDataset);
  const [itemForm, setItemForm] = useState(emptyItem);
  const itemKeyInputRef = useRef<HTMLInputElement | null>(null);
  const [requestedRef, setRequestedRef] = useState('');
  const requestedDatasetKey = requestedRef.includes('.') ? requestedRef.split('.', 1)[0] : '';

  const selectedDataset = useMemo(
    () => datasets.find(dataset => dataset.id === selectedDatasetId) || null,
    [datasets, selectedDatasetId],
  );

  const selectedItem = useMemo(
    () => items.find(item => item.id === selectedItemId) || null,
    [items, selectedItemId],
  );

  const activeDatasets = useMemo(
    () => datasets.filter(dataset => dataset.status === 'active').length,
    [datasets],
  );

  const totalItems = useMemo(
    () => datasets.reduce((total, dataset) => total + (dataset.item_count || 0), 0),
    [datasets],
  );
  const canSaveItem = Boolean(selectedDataset) && !savingItem && Boolean(itemForm.key.trim()) && Boolean(itemForm.name.trim());
  const sensitiveFieldList = useMemo(() => parseSensitiveFields(itemForm.sensitiveFields), [itemForm.sensitiveFields]);
  const passwordProtected = sensitiveFieldList.includes('password');

  const loadDatasets = useCallback(async () => {
    if (!currentProject?.id) return;
    setLoading(true);
    try {
      const response = await fetchWithAuth(`${API_BASE}/test-data/datasets?project_id=${encodeURIComponent(currentProject.id)}`);
      if (!response.ok) throw new Error(await readError(response, 'Failed to load test data'));
      const data = await response.json();
      const next: TestDataSet[] = data.datasets || [];
      setDatasets(next);
      setSelectedDatasetId(prev => {
        const requestedDataset = requestedDatasetKey
          ? next.find(dataset => dataset.key === requestedDatasetKey)
          : null;
        if (requestedDataset) return requestedDataset.id;
        if (prev && next.some(dataset => dataset.id === prev)) return prev;
        return next[0]?.id || '';
      });
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Failed to load test data');
    } finally {
      setLoading(false);
    }
  }, [currentProject?.id, requestedDatasetKey]);

  const loadItems = useCallback(async (datasetId: string) => {
    if (!datasetId || !currentProject?.id) {
      setItems([]);
      setSelectedItemId('');
      return;
    }
    setItemsLoading(true);
    try {
      const response = await fetchWithAuth(`${API_BASE}/test-data/datasets/${encodeURIComponent(datasetId)}/items?project_id=${encodeURIComponent(currentProject.id)}`);
      if (!response.ok) throw new Error(await readError(response, 'Failed to load items'));
      const data = await response.json();
      const next: TestDataItem[] = data.items || [];
      setItems(next);
      setSelectedItemId(prev => {
        const requestedItem = requestedRef
          ? next.find(item => item.ref === requestedRef)
          : null;
        if (requestedItem) return requestedItem.id;
        if (prev && next.some(item => item.id === prev)) return prev;
        return next[0]?.id || '';
      });
    } finally {
      setItemsLoading(false);
    }
  }, [currentProject?.id, requestedRef]);

  useEffect(() => {
    setRequestedRef(new URLSearchParams(window.location.search).get('ref') || '');
  }, []);

  useEffect(() => {
    loadDatasets();
  }, [loadDatasets]);

  useEffect(() => {
    loadItems(selectedDatasetId).catch(error => toast.error(error instanceof Error ? error.message : 'Failed to load items'));
  }, [selectedDatasetId, loadItems]);

  useEffect(() => {
    if (!selectedItem) {
      setItemForm(emptyItem);
      return;
    }
    setItemForm({
      key: selectedItem.key,
      name: selectedItem.name || '',
      description: selectedItem.description || '',
      status: selectedItem.status,
      format: selectedItem.format,
      dataText: selectedItem.data ? JSON.stringify(selectedItem.data, null, 2) : emptyItem.dataText,
      text: selectedItem.text || '',
      sensitiveFields: (selectedItem.sensitive_fields || []).join(', '),
    });
  }, [selectedItem]);

  async function saveDataset() {
    if (!currentProject?.id || savingDataset) return;
    const key = datasetForm.key.trim();
    if (!key) {
      toast.error('Dataset key is required');
      return;
    }

    setSavingDataset(true);
    try {
      const body = {
        project_id: currentProject.id,
        key,
        name: datasetForm.name.trim() || key,
        description: datasetForm.description.trim(),
        tags: datasetForm.tags.split(',').map(tag => tag.trim()).filter(Boolean),
        status: datasetForm.status,
        format: datasetForm.format,
      };
      const response = await fetchWithAuth(`${API_BASE}/test-data/datasets`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (!response.ok) {
        toast.error(await readError(response, 'Failed to create dataset'));
        return;
      }
      setDatasetForm(emptyDataset);
      await loadDatasets();
      toast.success('Dataset created');
    } finally {
      setSavingDataset(false);
    }
  }

  async function saveItem() {
    if (!selectedDataset || savingItem) return;
    const key = itemForm.key.trim();
    if (!key) {
      toast.error('Item key is required');
      itemKeyInputRef.current?.focus();
      return;
    }

    let parsedData: unknown = null;
    if (itemForm.format !== 'text') {
      try {
        parsedData = itemForm.dataText.trim() ? JSON.parse(itemForm.dataText) : null;
      } catch {
        toast.error('JSON content is invalid');
        return;
      }
    }

    setSavingItem(true);
    try {
      const body = {
        key,
        name: itemForm.name.trim(),
        description: itemForm.description.trim(),
        status: itemForm.status,
        format: itemForm.format,
        data: itemForm.format === 'text' ? null : parsedData,
        text: itemForm.format === 'json' ? null : itemForm.text,
        sensitive_fields: parseSensitiveFields(itemForm.sensitiveFields),
      };
      const isUpdate = Boolean(selectedItem);
      if (!currentProject?.id) return;
      const projectParam = `?project_id=${encodeURIComponent(currentProject.id)}`;
      const url = isUpdate
        ? `${API_BASE}/test-data/datasets/${encodeURIComponent(selectedDataset.id)}/items/${encodeURIComponent(selectedItem!.id)}${projectParam}`
        : `${API_BASE}/test-data/datasets/${encodeURIComponent(selectedDataset.id)}/items${projectParam}`;
      const response = await fetchWithAuth(url, {
        method: isUpdate ? 'PUT' : 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (!response.ok) {
        toast.error(await readError(response, 'Failed to save item'));
        return;
      }
      const savedItem: TestDataItem = await response.json();
      await loadItems(selectedDataset.id);
      await loadDatasets();
      setSelectedItemId(savedItem.id);
      toast.success(isUpdate ? 'Item updated' : 'Item created');
    } finally {
      setSavingItem(false);
    }
  }

  async function deleteItem() {
    if (!currentProject?.id || !selectedDataset || !selectedItem || deletingItem) return;
    setDeletingItem(true);
    try {
      const response = await fetchWithAuth(`${API_BASE}/test-data/datasets/${encodeURIComponent(selectedDataset.id)}/items/${encodeURIComponent(selectedItem.id)}?project_id=${encodeURIComponent(currentProject.id)}`, { method: 'DELETE' });
      if (!response.ok) {
        const message = await readError(response, 'Failed to delete item');
        toast.error(message);
        throw new Error(message);
      }
      await loadItems(selectedDataset.id);
      await loadDatasets();
      setDeleteOpen(false);
      toast.success('Item deleted');
    } finally {
      setDeletingItem(false);
    }
  }

  async function deleteDataset() {
    if (!currentProject?.id || !selectedDataset || deletingDataset) return;
    const datasetId = selectedDataset.id;
    setDeletingDataset(true);
    try {
      const response = await fetchWithAuth(`${API_BASE}/test-data/datasets/${encodeURIComponent(datasetId)}?project_id=${encodeURIComponent(currentProject.id)}`, { method: 'DELETE' });
      if (!response.ok) {
        const message = await readError(response, 'Failed to delete dataset');
        toast.error(message);
        throw new Error(message);
      }
      setSelectedDatasetId(prev => (prev === datasetId ? '' : prev));
      setSelectedItemId('');
      setItems([]);
      await loadDatasets();
      setDeleteDatasetOpen(false);
      toast.success('Dataset deleted');
    } finally {
      setDeletingDataset(false);
    }
  }

  function copy(text: string) {
    navigator.clipboard.writeText(text).then(() => toast.success('Copied'));
  }

  function setPasswordProtected(checked: boolean) {
    setItemForm(prev => ({
      ...prev,
      sensitiveFields: formatSensitiveFields(toggleSensitiveField(prev.sensitiveFields, 'password', checked)),
    }));
  }

  return (
    <PageLayout tier="wide">
      <PageHeader
        title="Test Data"
        subtitle="Project-isolated fixtures for specs, agents, PRD generation, and workflows."
        icon={<Database size={20} />}
        className="test-data-header"
        actions={(
          <Button variant="outline" size="sm" onClick={loadDatasets} disabled={loading}>
            {loading ? <Loader2 size={16} className="animate-spin" /> : <RefreshCw size={16} />}
            Refresh
          </Button>
        )}
      />

      {!currentProject ? (
        <EmptyState title="No project selected" description="Choose a project to manage its test data." icon={<Database size={28} />} />
      ) : (
        <div className="test-data-workspace">
          <aside className="test-data-sidebar">
            <Card>
              <CardHeader className="test-data-card-header">
                <div className="test-data-header-row">
                  <div className="test-data-min">
                    <CardTitle className="test-data-card-title">Datasets</CardTitle>
                    <p className="test-data-muted test-data-compact-line">
                      {datasets.length} total, {activeDatasets} active, {totalItems} items
                    </p>
                  </div>
                  <Badge
                    variant="outline"
                    className="test-data-project-badge test-data-shrink border-0"
                    style={{ border: 0 }}
                  >
                    {currentProject.name || 'Project'}
                  </Badge>
                </div>
              </CardHeader>
              <CardContent className="test-data-card-content test-data-stack-tight">
                {loading ? (
                  <div className="test-data-stack-tight" aria-label="Loading datasets">
                    <DatasetSkeleton />
                    <DatasetSkeleton />
                    <DatasetSkeleton />
                  </div>
                ) : null}

                {!loading && datasets.map(dataset => (
                  <DatasetRow
                    key={dataset.id}
                    dataset={dataset}
                    selected={dataset.id === selectedDatasetId}
                    onSelect={() => setSelectedDatasetId(dataset.id)}
                  />
                ))}

                {!datasets.length && !loading ? (
                  <CompactEmpty
                    icon={<Layers3 size={18} />}
                    title="No datasets yet"
                    description="Create the first fixture collection below."
                  />
                ) : null}
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="test-data-card-header">
                <CardTitle className="test-data-card-title">Create Dataset</CardTitle>
              </CardHeader>
              <CardContent className="test-data-card-content test-data-stack">
                <Field id="dataset-key" label="Key">
                  <Input
                    id="dataset-key"
                    data-testid="test-data-dataset-key"
                    value={datasetForm.key}
                    onChange={event => setDatasetForm(prev => ({ ...prev, key: event.target.value }))}
                    placeholder="login-users"
                  />
                </Field>
                <Field id="dataset-name" label="Name">
                  <Input
                    id="dataset-name"
                    data-testid="test-data-dataset-name"
                    value={datasetForm.name}
                    onChange={event => setDatasetForm(prev => ({ ...prev, name: event.target.value }))}
                    placeholder="Login Users"
                  />
                </Field>
                <Field id="dataset-description" label="Description">
                  <Input
                    id="dataset-description"
                    value={datasetForm.description}
                    onChange={event => setDatasetForm(prev => ({ ...prev, description: event.target.value }))}
                    placeholder="Reusable login fixtures"
                  />
                </Field>
                <Field id="dataset-tags" label="Tags" hint="Separate tags with commas.">
                  <Input
                    id="dataset-tags"
                    value={datasetForm.tags}
                    onChange={event => setDatasetForm(prev => ({ ...prev, tags: event.target.value }))}
                    placeholder="auth, smoke"
                  />
                </Field>
                <div className="test-data-create-select-grid">
                  <SelectField
                    id="dataset-format"
                    label="Format"
                    value={datasetForm.format}
                    onValueChange={value => setDatasetForm(prev => ({ ...prev, format: value as DataFormat }))}
                    values={['json', 'text', 'mixed']}
                  />
                  <SelectField
                    id="dataset-status"
                    label="Status"
                    value={datasetForm.status}
                    onValueChange={value => setDatasetForm(prev => ({ ...prev, status: value as DataStatus }))}
                    values={['active', 'archived']}
                  />
                </div>
                <Button className="w-full" onClick={saveDataset} disabled={savingDataset} data-testid="test-data-create-dataset">
                  {savingDataset ? <Loader2 size={16} className="animate-spin" /> : <Plus size={16} />}
                  Create dataset
                </Button>
              </CardContent>
            </Card>
          </aside>

          <main className="test-data-main">
            {selectedDataset ? (
              <>
                <DatasetSummary
                  dataset={selectedDataset}
                  itemCount={items.length}
                  deleting={deletingDataset}
                  onDelete={() => setDeleteDatasetOpen(true)}
                />

                <Card>
                  <CardHeader className="test-data-card-header">
                    <div className="test-data-header-row">
                      <div className="test-data-min">
                        <CardTitle className="test-data-card-title">Items</CardTitle>
                        <p className="test-data-muted test-data-compact-line">
                          Select an item to edit it, or start a new fixture.
                        </p>
                      </div>
                      <Button
                        variant="ghost"
                        size="sm"
                        className="test-data-new-item-button"
                        onClick={() => setSelectedItemId('')}
                      >
                        <Plus size={16} />
                        New item
                      </Button>
                    </div>
                  </CardHeader>
                  <CardContent className="test-data-card-content">
                    {itemsLoading ? (
                      <div className="test-data-item-list" aria-label="Loading items">
                        <ItemSkeleton />
                        <ItemSkeleton />
                        <ItemSkeleton />
                      </div>
                    ) : items.length ? (
                      <div className="test-data-item-list">
                        {items.map(item => (
                          <ItemCard
                            key={item.id}
                            item={item}
                            selected={item.id === selectedItemId}
                            onSelect={() => setSelectedItemId(item.id)}
                          />
                        ))}
                      </div>
                    ) : (
                      <CompactEmpty
                        icon={<FileJson size={18} />}
                        title="No items in this dataset yet"
                        description="Use the editor below to add the first fixture."
                      />
                    )}
                  </CardContent>
                </Card>

                <Card>
                  <CardHeader className="test-data-card-header">
                    <div className="test-data-header-row">
                      <div className="test-data-min">
                        <CardTitle className="test-data-card-title">
                          {selectedItem ? 'Edit Item' : 'New Item'}
                        </CardTitle>
                        <p className="test-data-code-muted test-data-compact-line">
                          {selectedItem ? selectedItem.ref : `${selectedDataset.key}.<item-key>`}
                        </p>
                      </div>
                      <div className="test-data-actions">
                        {selectedItem ? (
                          <Button variant="outline" size="sm" onClick={() => copy(`@testdata "${selectedItem.ref}"`)}>
                            <Copy size={16} />
                            Directive
                          </Button>
                        ) : null}
                        {selectedItem ? (
                          <Button variant="outline" size="sm" onClick={() => setSelectedItemId('')}>
                            <Plus size={16} />
                            New
                          </Button>
                        ) : null}
                      </div>
                    </div>
                  </CardHeader>
                  <CardContent className="test-data-card-content test-data-stack">
                    <div className="test-data-item-form-grid">
                      <Field id="item-key" label="Key">
                        <Input
                          id="item-key"
                          ref={itemKeyInputRef}
                          data-testid="test-data-item-key"
                          value={itemForm.key}
                          onChange={event => setItemForm(prev => ({ ...prev, key: event.target.value }))}
                          placeholder="valid-admin"
                        />
                      </Field>
                      <Field id="item-name" label="Name">
                        <Input
                          id="item-name"
                          data-testid="test-data-item-name"
                          value={itemForm.name}
                          onChange={event => setItemForm(prev => ({ ...prev, name: event.target.value }))}
                          placeholder="Valid admin"
                        />
                      </Field>
                      <SelectField
                        id="item-format"
                        label="Format"
                        value={itemForm.format}
                        onValueChange={value => setItemForm(prev => ({ ...prev, format: value as DataFormat }))}
                        values={['json', 'text', 'mixed']}
                      />
                      <SelectField
                        id="item-status"
                        label="Status"
                        value={itemForm.status}
                        onValueChange={value => setItemForm(prev => ({ ...prev, status: value as DataStatus }))}
                        values={['active', 'archived']}
                      />
                    </div>

                    <Field id="item-description" label="Description">
                      <Input
                        id="item-description"
                        value={itemForm.description}
                        onChange={event => setItemForm(prev => ({ ...prev, description: event.target.value }))}
                        placeholder="Admin user credentials for login specs"
                      />
                    </Field>

                    <Field id="item-sensitive-fields" label="Sensitive fields" hint="Use commas for paths such as password, token, profile.ssn, or $text.">
                      <Input
                        id="item-sensitive-fields"
                        value={itemForm.sensitiveFields}
                        onChange={event => setItemForm(prev => ({ ...prev, sensitiveFields: event.target.value }))}
                        placeholder="password, token, profile.ssn, $text"
                      />
                    </Field>

                    <div className={cn('test-data-sensitive-toggle', passwordProtected ? 'test-data-sensitive-toggle-on' : '')}>
                      <div className="test-data-min">
                        <Label htmlFor="item-password-sensitive" className="test-data-label">Protect password</Label>
                        <p className="test-data-hint">Adds password to sensitive fields.</p>
                      </div>
                      <Switch
                        id="item-password-sensitive"
                        data-testid="test-data-password-sensitive"
                        checked={passwordProtected}
                        onCheckedChange={setPasswordProtected}
                        aria-label="Protect password"
                      />
                    </div>

                    {itemForm.format !== 'text' ? (
                      <Field id="item-json" label="JSON">
                        <textarea
                          id="item-json"
                          data-testid="test-data-item-json"
                          className={cn(textareaClass, 'test-data-json-editor')}
                          value={itemForm.dataText}
                          onChange={event => setItemForm(prev => ({ ...prev, dataText: event.target.value }))}
                          spellCheck={false}
                        />
                      </Field>
                    ) : null}

                    {itemForm.format !== 'json' ? (
                      <Field id="item-text" label="Text">
                        <textarea
                          id="item-text"
                          className={cn(textareaClass, 'test-data-text-editor')}
                          value={itemForm.text}
                          onChange={event => setItemForm(prev => ({ ...prev, text: event.target.value }))}
                        />
                      </Field>
                    ) : null}

                    {selectedItem?.placeholders && Object.keys(selectedItem.placeholders).length ? (
                      <div className="test-data-secret-box">
                        <div className="test-data-secret-title">
                          <ShieldCheck size={16} style={{ color: 'var(--success)' }} />
                          Secret placeholders
                        </div>
                        <div className="test-data-stack-tight">
                          {Object.entries(selectedItem.placeholders).map(([path, placeholder]) => (
                            <div key={path} className="test-data-secret-row">
                              <code className="test-data-code-muted">{path}</code>
                              <button
                                type="button"
                                className="test-data-copy-token"
                                onClick={() => copy(placeholder)}
                              >
                                {placeholder}
                              </button>
                            </div>
                          ))}
                        </div>
                      </div>
                    ) : null}

                    <div className="test-data-actions">
                      <Button onClick={saveItem} disabled={!canSaveItem} data-testid="test-data-save-item">
                        {savingItem ? <Loader2 size={16} className="animate-spin" /> : <Save size={16} />}
                        Save item
                      </Button>
                      {selectedItem ? (
                        <Button
                          variant="outline"
                          onClick={() => setDeleteOpen(true)}
                          disabled={deletingItem}
                          data-testid="test-data-delete-item"
                        >
                          <Trash2 size={16} />
                          Delete item
                        </Button>
                      ) : null}
                      {selectedItem?.status === 'archived' ? (
                        <Badge variant="outline" className="gap-1">
                          <Archive size={12} />
                          Archived
                        </Badge>
                      ) : null}
                    </div>
                  </CardContent>
                </Card>
              </>
            ) : (
              <EmptyState title="Choose a dataset" description="Create or select a dataset to manage fixture items." icon={<Database size={28} />} />
            )}
          </main>
        </div>
      )}

      <ConfirmDialog
        open={deleteDatasetOpen}
        onOpenChange={setDeleteDatasetOpen}
        title="Delete test data dataset?"
        description={selectedDataset ? `This will permanently delete "${selectedDataset.name || selectedDataset.key}" and ${items.length} item${items.length === 1 ? '' : 's'}.` : 'This dataset and its items will be permanently deleted.'}
        confirmLabel="Delete dataset"
        variant="danger"
        loading={deletingDataset}
        onConfirm={deleteDataset}
      />

      <ConfirmDialog
        open={deleteOpen}
        onOpenChange={setDeleteOpen}
        title="Delete test data item?"
        description={selectedItem ? `This will permanently delete "${selectedItem.name || selectedItem.key}" from ${selectedDataset?.name || 'this dataset'}.` : 'This item will be permanently deleted.'}
        confirmLabel="Delete item"
        variant="danger"
        loading={deletingItem}
        onConfirm={deleteItem}
      />

      <style jsx global>{`
        .test-data-header p {
          color: var(--text-secondary);
        }

        .test-data-header h1 {
          letter-spacing: 0;
        }

        .test-data-workspace {
          display: grid;
          grid-template-columns: minmax(0, 1fr);
          gap: 1rem;
          align-items: start;
        }

        @media (min-width: 1100px) {
          .test-data-workspace {
            grid-template-columns: 360px minmax(0, 1fr);
          }

          .test-data-sidebar {
            position: sticky;
            top: 1rem;
          }
        }

        .test-data-sidebar,
        .test-data-main,
        .test-data-stack {
          display: flex;
          flex-direction: column;
          gap: 1rem;
          min-width: 0;
        }

        .test-data-stack-tight {
          display: flex;
          flex-direction: column;
          gap: 0.5rem;
        }

        .test-data-card-header {
          padding: 1rem 1rem 0.75rem;
        }

        .test-data-card-content {
          padding: 0 1rem 1rem;
        }

        .test-data-card-title {
          color: var(--text);
          font-size: 1rem;
          font-weight: 650;
          line-height: 1.2;
          letter-spacing: 0;
        }

        .test-data-header-row,
        .test-data-row-top,
        .test-data-title-row {
          display: flex;
          align-items: flex-start;
          justify-content: space-between;
          gap: 0.75rem;
          min-width: 0;
        }

        .test-data-header-row,
        .test-data-title-row {
          flex-wrap: wrap;
        }

        .test-data-min {
          min-width: 0;
        }

        .test-data-shrink {
          flex-shrink: 0;
        }

        .test-data-project-badge {
          background: rgba(148, 163, 184, 0.12) !important;
          color: var(--text-secondary) !important;
          box-shadow: none !important;
        }

        .test-data-new-item-button {
          border: 0 !important;
          background: transparent !important;
          color: var(--text) !important;
          box-shadow: none !important;
        }

        .test-data-new-item-button:hover {
          background: rgba(148, 163, 184, 0.1) !important;
        }

        .test-data-new-item-button:focus-visible {
          outline: 2px solid var(--primary);
          outline-offset: 2px;
        }

        .test-data-muted {
          color: var(--text-secondary);
        }

        .test-data-code-muted {
          color: var(--text-secondary);
          font-family: var(--font-mono);
          font-size: 0.75rem;
          line-height: 1.45;
          overflow-wrap: anywhere;
        }

        .test-data-compact-line {
          margin-top: 0.25rem;
        }

        .test-data-create-select-grid,
        .test-data-item-form-grid,
        .test-data-summary-metrics,
        .test-data-item-list {
          display: grid;
          gap: 0.75rem;
          min-width: 0;
        }

        .test-data-create-select-grid {
          grid-template-columns: repeat(2, minmax(0, 1fr));
        }

        .test-data-item-form-grid {
          grid-template-columns: repeat(4, minmax(0, 1fr));
        }

        .test-data-item-list {
          grid-template-columns: repeat(3, minmax(0, 1fr));
        }

        @media (max-width: 1280px) {
          .test-data-item-list {
            grid-template-columns: repeat(2, minmax(0, 1fr));
          }

          .test-data-item-form-grid {
            grid-template-columns: repeat(2, minmax(0, 1fr));
          }
        }

        @media (max-width: 720px) {
          .test-data-create-select-grid,
          .test-data-item-form-grid,
          .test-data-item-list {
            grid-template-columns: minmax(0, 1fr);
          }
        }

        .test-data-selectable {
          width: 100%;
          border: 1px solid var(--border);
          border-radius: 10px;
          padding: 0.8rem;
          color: var(--text);
          text-align: left;
          transition: background 0.16s var(--ease-smooth), border-color 0.16s var(--ease-smooth), box-shadow 0.16s var(--ease-smooth);
        }

        .test-data-selectable:hover {
          background: var(--surface-hover) !important;
        }

        .test-data-selectable:focus-visible,
        .test-data-copy-token:focus-visible,
        .test-data-textarea:focus-visible {
          outline: 2px solid var(--primary);
          outline-offset: 2px;
        }

        .test-data-row-title {
          color: var(--text);
          font-size: 0.9rem;
          font-weight: 650;
          line-height: 1.25;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }

        .test-data-row-meta {
          display: flex;
          align-items: center;
          gap: 0.35rem;
          min-width: 0;
          margin-top: 0.35rem;
          color: var(--text-secondary);
          font-family: var(--font-mono);
          font-size: 0.75rem;
        }

        .test-data-row-meta span {
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }

        .test-data-pill-row,
        .test-data-tag-row,
        .test-data-actions {
          display: flex;
          flex-wrap: wrap;
          align-items: center;
          gap: 0.5rem;
        }

        .test-data-pill-row,
        .test-data-tag-row {
          margin-top: 0.8rem;
        }

        .test-data-tag,
        .test-data-meta-pill {
          display: inline-flex;
          align-items: center;
          gap: 0.3rem;
          border: 1px solid var(--border);
          border-radius: 999px;
          color: var(--text-secondary);
          background: rgba(148, 163, 184, 0.06);
          font-size: 0.74rem;
          line-height: 1;
          padding: 0.28rem 0.52rem;
        }

        .test-data-summary {
          padding: 1rem;
        }

        .test-data-summary-inner {
          display: flex;
          align-items: flex-start;
          justify-content: space-between;
          gap: 1rem;
        }

        .test-data-summary-title {
          color: var(--text);
          font-size: 1.1rem;
          line-height: 1.25;
          font-weight: 700;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
          max-width: 100%;
          margin: 0;
        }

        .test-data-summary-description {
          max-width: 54rem;
          margin-top: 0.5rem;
          font-size: 0.875rem;
          line-height: 1.5;
        }

        .test-data-summary-metrics {
          grid-template-columns: repeat(3, minmax(0, 1fr));
          min-width: 320px;
        }

        .test-data-summary-side {
          display: flex;
          flex-direction: column;
          align-items: flex-end;
          gap: 0.75rem;
          min-width: 320px;
        }

        @media (max-width: 820px) {
          .test-data-summary-inner {
            flex-direction: column;
          }

          .test-data-summary-side {
            align-items: stretch;
            width: 100%;
            min-width: 0;
          }

          .test-data-summary-metrics {
            width: 100%;
            min-width: 0;
          }
        }

        .test-data-metric {
          border: 1px solid var(--border);
          border-radius: 10px;
          background: var(--background-raised);
          padding: 0.65rem 0.75rem;
          min-width: 0;
        }

        .test-data-metric-label {
          color: var(--text-secondary);
          font-size: 0.68rem;
          font-weight: 700;
          line-height: 1;
          text-transform: uppercase;
          letter-spacing: 0;
        }

        .test-data-metric-value {
          margin-top: 0.35rem;
          color: var(--text);
          font-size: 0.9rem;
          font-weight: 700;
          overflow: hidden;
          text-overflow: ellipsis;
          white-space: nowrap;
        }

        .test-data-item-card {
          min-height: 132px;
        }

        .test-data-item-description {
          display: -webkit-box;
          -webkit-line-clamp: 2;
          -webkit-box-orient: vertical;
          overflow: hidden;
          margin-top: 0.75rem;
          font-size: 0.78rem;
          line-height: 1.45;
        }

        .test-data-field {
          display: flex;
          flex-direction: column;
          gap: 0.35rem;
          min-width: 0;
        }

        .test-data-label {
          color: var(--text);
          font-size: 0.85rem;
          font-weight: 650;
          line-height: 1.2;
        }

        .test-data-hint {
          color: var(--text-secondary);
          font-size: 0.78rem;
          line-height: 1.35;
        }

        .test-data-textarea {
          width: 100%;
          border: 1px solid var(--border);
          border-radius: 10px;
          background: var(--background-raised);
          color: var(--text);
          padding: 0.85rem;
          font-size: 0.9rem;
          line-height: 1.55;
          resize: vertical;
          box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.02);
        }

        .test-data-textarea::placeholder {
          color: var(--text-secondary);
          opacity: 0.7;
        }

        .test-data-json-editor {
          min-height: 260px;
          font-family: var(--font-mono);
        }

        .test-data-text-editor {
          min-height: 160px;
        }

        .test-data-secret-box,
        .test-data-sensitive-toggle,
        .test-data-empty,
        .test-data-skeleton-card {
          border: 1px solid var(--border);
          border-radius: 10px;
          background: var(--background-raised);
          padding: 0.9rem;
        }

        .test-data-sensitive-toggle {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 0.9rem;
          min-width: 0;
          transition: border-color 0.16s var(--ease-smooth), background 0.16s var(--ease-smooth);
        }

        .test-data-sensitive-toggle-on {
          border-color: rgba(52, 211, 153, 0.45);
          background: rgba(52, 211, 153, 0.08);
        }

        .test-data-secret-title {
          display: flex;
          align-items: center;
          gap: 0.5rem;
          margin-bottom: 0.6rem;
          color: var(--text);
          font-size: 0.875rem;
          font-weight: 650;
        }

        .test-data-secret-row {
          display: flex;
          flex-wrap: wrap;
          align-items: center;
          justify-content: space-between;
          gap: 0.5rem;
          border-radius: 8px;
          padding: 0.35rem 0.5rem;
        }

        .test-data-copy-token {
          border: 0;
          background: transparent;
          color: var(--primary);
          font-family: var(--font-mono);
          font-size: 0.75rem;
          overflow-wrap: anywhere;
        }

        .test-data-empty {
          border-style: dashed;
          text-align: center;
          padding: 1.5rem;
        }

        .test-data-empty-icon {
          display: inline-flex;
          align-items: center;
          justify-content: center;
          width: 2.25rem;
          height: 2.25rem;
          border-radius: 10px;
          background: var(--primary-glow);
          color: var(--primary);
        }

        .test-data-empty-title {
          margin-top: 0.75rem;
          color: var(--text);
          font-size: 0.9rem;
          font-weight: 700;
        }

        .test-data-empty-description {
          margin-top: 0.3rem;
          color: var(--text-secondary);
          font-size: 0.8rem;
          line-height: 1.45;
        }
      `}</style>
    </PageLayout>
  );
}

function DatasetRow({ dataset, selected, onSelect }: { dataset: TestDataSet; selected: boolean; onSelect: () => void }) {
  return (
    <button
      type="button"
      data-testid="test-data-dataset-card"
      aria-pressed={selected}
      className={selectableRowClass}
      style={{
        background: selected ? 'rgba(59, 130, 246, 0.10)' : 'var(--background-raised)',
        borderColor: selected ? 'var(--primary)' : 'var(--border)',
        boxShadow: selected ? 'inset 3px 0 0 var(--primary)' : 'none',
      }}
      onClick={onSelect}
    >
      <div className="test-data-row-top">
        <div className="test-data-min">
          <div className="test-data-row-title">{dataset.name || dataset.key}</div>
          <div className="test-data-row-meta">
            <KeyRound size={12} />
            <span>{dataset.key}</span>
          </div>
        </div>
        <StatusBadge status={dataset.status} />
      </div>

      <div className="test-data-pill-row">
        <MetaPill icon={<FileJson size={12} />} label={dataset.format} />
        <MetaPill icon={<Layers3 size={12} />} label={`${dataset.item_count || 0} items`} />
      </div>

      {dataset.tags?.length ? (
        <div className="test-data-tag-row">
          {dataset.tags.slice(0, 4).map(tag => (
            <span key={tag} className="test-data-tag">
              {tag}
            </span>
          ))}
          {dataset.tags.length > 4 ? (
            <span className="test-data-tag">
              +{dataset.tags.length - 4}
            </span>
          ) : null}
        </div>
      ) : null}
    </button>
  );
}

function DatasetSummary({
  dataset,
  itemCount,
  deleting,
  onDelete,
}: {
  dataset: TestDataSet;
  itemCount: number;
  deleting: boolean;
  onDelete: () => void;
}) {
  return (
    <Card>
      <CardContent className="test-data-summary">
        <div className="test-data-summary-inner">
          <div className="test-data-min">
            <div className="test-data-title-row">
              <h2 className="test-data-summary-title">{dataset.name || dataset.key}</h2>
              <StatusBadge status={dataset.status} />
              <FormatBadge format={dataset.format} />
            </div>
            <p className="test-data-code-muted test-data-compact-line">{dataset.key}</p>
            {dataset.description ? (
              <p className="test-data-muted test-data-summary-description">{dataset.description}</p>
            ) : null}
          </div>
          <div className="test-data-summary-side">
            <div className="test-data-summary-metrics">
              <SummaryMetric label="Items" value={String(itemCount)} />
              <SummaryMetric label="Format" value={dataset.format} />
              <SummaryMetric label="Tags" value={String(dataset.tags?.length || 0)} />
            </div>
            <Button
              variant="outline"
              size="sm"
              onClick={onDelete}
              disabled={deleting}
              data-testid="test-data-delete-dataset"
            >
              {deleting ? <Loader2 size={16} className="animate-spin" /> : <Trash2 size={16} />}
              Delete dataset
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

function ItemCard({ item, selected, onSelect }: { item: TestDataItem; selected: boolean; onSelect: () => void }) {
  const sensitiveCount = item.sensitive_fields?.length || 0;

  return (
    <button
      type="button"
      data-testid="test-data-item-card"
      aria-pressed={selected}
      className={cn(selectableRowClass, 'test-data-item-card')}
      style={{
        background: selected ? 'rgba(59, 130, 246, 0.10)' : 'var(--background-raised)',
        borderColor: selected ? 'var(--primary)' : 'var(--border)',
        boxShadow: selected ? 'inset 3px 0 0 var(--primary)' : 'none',
      }}
      onClick={onSelect}
    >
      <div className="test-data-row-top">
        <div className="test-data-min">
          <div className="test-data-row-title">{item.name || item.key}</div>
          <div className="test-data-code-muted test-data-compact-line">{item.ref}</div>
        </div>
        <FormatBadge format={item.format} />
      </div>
      <div className="test-data-pill-row">
        <StatusBadge status={item.status} />
        {sensitiveCount ? <MetaPill icon={<ShieldCheck size={12} />} label={`${sensitiveCount} sensitive`} /> : null}
      </div>
      {item.description ? (
        <p className="test-data-muted test-data-item-description">{item.description}</p>
      ) : null}
    </button>
  );
}

function Field({ id, label, hint, children }: { id: string; label: string; hint?: string; children: ReactNode }) {
  return (
    <div className="test-data-field">
      <Label htmlFor={id} className="test-data-label">{label}</Label>
      {children}
      {hint ? <p className="test-data-hint">{hint}</p> : null}
    </div>
  );
}

function SelectField({
  id,
  label,
  value,
  values,
  onValueChange,
}: {
  id: string;
  label: string;
  value: string;
  values: string[];
  onValueChange: (value: string) => void;
}) {
  return (
    <Field id={id} label={label}>
      <Select value={value} onValueChange={onValueChange}>
        <SelectTrigger id={id}><SelectValue /></SelectTrigger>
        <SelectContent>
          {values.map(item => <SelectItem key={item} value={item}>{item}</SelectItem>)}
        </SelectContent>
      </Select>
    </Field>
  );
}

function StatusBadge({ status }: { status: DataStatus }) {
  const active = status === 'active';
  return (
    <Badge
      variant="outline"
      className="shrink-0 border-0 capitalize"
      style={{
        background: active ? 'rgba(52, 211, 153, 0.12)' : 'rgba(126, 139, 168, 0.12)',
        border: 0,
        color: active ? '#a7f3d0' : 'var(--text-secondary)',
      }}
    >
      {status}
    </Badge>
  );
}

function FormatBadge({ format }: { format: DataFormat }) {
  return (
    <Badge
      variant="outline"
      className="shrink-0 border-0 uppercase"
      style={{
        background: 'rgba(59, 130, 246, 0.12)',
        border: 0,
        color: '#bfdbfe',
      }}
    >
      {format}
    </Badge>
  );
}

function MetaPill({ icon, label }: { icon: ReactNode; label: string }) {
  return (
    <span className="test-data-meta-pill">
      {icon}
      {label}
    </span>
  );
}

function SummaryMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="test-data-metric">
      <div className="test-data-metric-label">{label}</div>
      <div className="test-data-metric-value">{value}</div>
    </div>
  );
}

function CompactEmpty({ icon, title, description }: { icon: ReactNode; title: string; description: string }) {
  return (
    <div className="test-data-empty">
      <div className="test-data-empty-icon">
        {icon}
      </div>
      <div className="test-data-empty-title">{title}</div>
      <p className="test-data-empty-description">{description}</p>
    </div>
  );
}

function DatasetSkeleton() {
  return (
    <div className="test-data-skeleton-card">
      <div className="test-data-row-top">
        <Skeleton className="h-4 w-36" />
        <Skeleton className="h-5 w-14 rounded-full" />
      </div>
      <Skeleton className="mt-3 h-3 w-48" />
      <div className="mt-3 flex gap-2">
        <Skeleton className="h-5 w-16 rounded-full" />
        <Skeleton className="h-5 w-20 rounded-full" />
      </div>
    </div>
  );
}

function ItemSkeleton() {
  return (
    <div className="test-data-skeleton-card test-data-item-card">
      <div className="test-data-row-top">
        <Skeleton className="h-4 w-32" />
        <Skeleton className="h-5 w-14 rounded-full" />
      </div>
      <Skeleton className="mt-3 h-3 w-full" />
      <Skeleton className="mt-2 h-3 w-2/3" />
      <div className="mt-4 flex gap-2">
        <Skeleton className="h-5 w-16 rounded-full" />
        <Skeleton className="h-5 w-24 rounded-full" />
      </div>
    </div>
  );
}
