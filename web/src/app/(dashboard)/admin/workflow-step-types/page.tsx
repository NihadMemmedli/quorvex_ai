'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import { AlertTriangle, RefreshCw, Search, Workflow } from 'lucide-react';
import { API_BASE } from '@/lib/api';
import { fetchWithAuth, useAuth } from '@/contexts/AuthContext';
import { PageLayout } from '@/components/ui/page-layout';
import { PageHeader } from '@/components/ui/page-header';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Skeleton } from '@/components/ui/skeleton';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';

interface StepType {
  type: string;
  version: number;
  label: string;
  description: string;
  category?: string;
  risk_level?: string;
  is_async?: boolean;
  handler_kind?: string;
  status?: string;
  input_schema?: Record<string, unknown>;
  ui_schema?: Record<string, unknown>;
  output_schema?: { tokens?: string[] };
  handler_config?: Record<string, unknown>;
}

export default function AdminWorkflowStepTypesPage() {
  const router = useRouter();
  const { user, isLoading: authLoading } = useAuth();
  const [steps, setSteps] = useState<StepType[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState('');

  useEffect(() => {
    if (!authLoading && (!user || !user.is_superuser)) {
      router.push('/');
    }
  }, [authLoading, router, user]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetchWithAuth(`${API_BASE}/workflows/admin/step-types`);
      if (res.status === 403) {
        router.push('/');
        return;
      }
      if (!res.ok) throw new Error('Failed to load workflow step types');
      const data = await res.json();
      setSteps(Array.isArray(data.steps) ? data.steps : []);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load workflow step types');
    } finally {
      setLoading(false);
    }
  }, [router]);

  useEffect(() => {
    if (user?.is_superuser) void load();
  }, [load, user?.is_superuser]);

  const filtered = useMemo(() => {
    const query = search.trim().toLowerCase();
    if (!query) return steps;
    return steps.filter(step => [step.type, step.label, step.description, step.category || '', step.handler_kind || ''].some(value => value.toLowerCase().includes(query)));
  }, [search, steps]);

  return (
    <PageLayout>
      <PageHeader
        title="Workflow Step Types"
        subtitle="Read-only registry metadata for workflow builder steps"
        icon={<Workflow size={22} />}
        actions={(
          <Button variant="outline" onClick={load} disabled={loading}>
            <RefreshCw size={15} /> Refresh
          </Button>
        )}
      />

      {error && (
        <Alert style={{ marginBottom: '1rem' }}>
          <AlertTriangle size={16} />
          <AlertTitle>Unable to load registry</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      <section className="card-elevated" style={{ padding: '1rem', display: 'grid', gap: '1rem' }}>
        <div style={{ position: 'relative', maxWidth: 420 }}>
          <Search size={15} style={{ position: 'absolute', left: 12, top: '50%', transform: 'translateY(-50%)', color: 'var(--text-secondary)' }} />
          <Input
            value={search}
            onChange={event => setSearch(event.target.value)}
            placeholder="Search registry"
            aria-label="Search workflow step registry"
            style={{ paddingLeft: 34 }}
          />
        </div>

        {loading ? (
          <div style={{ display: 'grid', gap: '0.65rem' }}>
            {Array.from({ length: 6 }).map((_, index) => <Skeleton key={index} style={{ height: 44 }} />)}
          </div>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Step</TableHead>
                <TableHead>Category</TableHead>
                <TableHead>Risk</TableHead>
                <TableHead>Handler</TableHead>
                <TableHead>Outputs</TableHead>
                <TableHead>Status</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filtered.map(step => (
                <TableRow key={`${step.type}-${step.version}`}>
                  <TableCell>
                    <div style={{ fontWeight: 700 }}>{step.label}</div>
                    <div style={{ color: 'var(--text-secondary)', fontSize: '0.78rem' }}>{step.type} v{step.version}</div>
                    <div style={{ color: 'var(--text-secondary)', fontSize: '0.78rem', maxWidth: 360 }}>{step.description}</div>
                  </TableCell>
                  <TableCell>{step.category || 'Utility'}</TableCell>
                  <TableCell><Badge variant="outline">{step.risk_level || 'low'}</Badge></TableCell>
                  <TableCell>
                    <div>{step.handler_kind || 'builtin'}</div>
                    {step.is_async && <div style={{ color: 'var(--primary)', fontSize: '0.75rem' }}>async</div>}
                  </TableCell>
                  <TableCell style={{ maxWidth: 320 }}>
                    <div style={{ display: 'flex', gap: '0.35rem', flexWrap: 'wrap' }}>
                      {(step.output_schema?.tokens || []).map(token => <Badge key={token} variant="secondary">{token}</Badge>)}
                    </div>
                  </TableCell>
                  <TableCell>{step.status || 'active'}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </section>
    </PageLayout>
  );
}
