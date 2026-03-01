'use client';

import { useState, useRef, useCallback, useEffect } from 'react';
import {
  ThreadPrimitive,
  ComposerPrimitive,
  MessagePrimitive,
  ActionBarPrimitive,
  BranchPickerPrimitive,
  makeAssistantToolUI,
  useThread,
  useThreadRuntime,
  useMessage,
  useThreadComposerAttachment,
  useAttachmentRuntime,
} from '@assistant-ui/react';
import type { MessageStatus } from '@assistant-ui/react';
import type { TextMessagePartProps } from '@assistant-ui/react';
import { MUTATING_TOOL_NAMES, MUTATING_TOOL_CONFIGS } from '@/lib/ai/tools';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import {
  Send,
  Copy,
  Check,
  Code,
  ArrowDown,
  ThumbsUp,
  ThumbsDown,
  FlaskConical,
  Search,
  Shield,
  BarChart3,
  AlertTriangle,
  Clock,
  RefreshCw,
  Pencil,
  ChevronLeft,
  ChevronRight,
  ChevronDown,
  Brain,
  Paperclip,
  ImageIcon,
  X as XIcon,
} from 'lucide-react';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { useChatContext } from './ChatProvider';
import { useProject } from '@/contexts/ProjectContext';
import { getProjectContext } from '@/lib/chat-api';
import { fetchWithAuth } from '@/contexts/AuthContext';
import { API_BASE } from '@/lib/api';

interface MentionEntity {
  type: string;
  id: string;
  label: string;
  description: string;
}

// ===== Project Context Hook =====

function useProjectContext() {
  const { currentProject } = useProject();
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    getProjectContext(currentProject?.id)
      .then((d: any) => { if (!cancelled) setData(d); })
      .catch(() => {})
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [currentProject?.id]);
  return { data, loading };
}

// ===== Tool Loading & Error =====

function ToolLoading({ name }: { name: string }) {
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    const interval = setInterval(() => setElapsed((e) => e + 1), 1000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div style={{
      display: 'flex',
      alignItems: 'center',
      gap: '0.5rem',
      padding: '0.5rem 0.75rem',
      color: 'var(--text-secondary)',
      fontSize: '0.8rem',
    }}>
      <div className="loading-spinner" style={{ width: '16px', height: '16px', borderWidth: '2px' }} />
      <span>{name}</span>
      <span style={{ marginLeft: 'auto', fontSize: '0.7rem', opacity: 0.6 }}>
        {elapsed}s
        {elapsed > 10 && <span> · This may take a moment...</span>}
      </span>
    </div>
  );
}

function ToolError({ message }: { message: string }) {
  return (
    <div style={{
      padding: '0.75rem',
      background: 'rgba(239, 68, 68, 0.1)',
      border: '1px solid rgba(239, 68, 68, 0.2)',
      borderRadius: '8px',
      color: 'var(--danger)',
      fontSize: '0.85rem',
      marginTop: '0.5rem',
    }}>
      <span>{message}</span>
    </div>
  );
}

// ===== Tool Result Renderers =====

const NavigateToolUI = makeAssistantToolUI({
  toolName: 'navigateToPage',
  render: ({ result }) => {
    if (!result) return <ToolLoading name="Preparing navigation..." />;
    const data = result as { navigateTo?: string; reason?: string };
    return (
      <div style={{
        padding: '0.75rem 1rem',
        background: 'rgba(59, 130, 246, 0.1)',
        border: '1px solid rgba(59, 130, 246, 0.2)',
        borderRadius: '8px',
        marginTop: '0.5rem',
      }}>
        <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: '0.5rem' }}>
          {data.reason}
        </p>
        <Link href={data.navigateTo || '/'} style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: '0.5rem',
          padding: '0.5rem 1rem',
          background: 'var(--primary)',
          color: 'white',
          borderRadius: '6px',
          fontSize: '0.85rem',
          fontWeight: 600,
        }}>
          Go to {data.navigateTo}
        </Link>
      </div>
    );
  },
});

const DashboardStatsToolUI = makeAssistantToolUI({
  toolName: 'getDashboardStats',
  render: ({ result }) => {
    if (!result) return <ToolLoading name="Loading dashboard stats..." />;
    const data = result as Record<string, unknown>;
    if (data.error) return <ToolError message={String(data.error)} />;
    return (
      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fit, minmax(120px, 1fr))',
        gap: '0.75rem',
        padding: '0.75rem',
        background: 'var(--surface)',
        border: '1px solid var(--border)',
        borderRadius: '8px',
        marginTop: '0.5rem',
      }}>
        {Object.entries(data)
          .filter(([k, v]) => (typeof v === 'number' || (typeof v === 'string' && String(v).length <= 20)) && k !== 'period' && k !== 'last_run')
          .map(([key, value]) => (
          <div key={key} style={{ textAlign: 'center' }}>
            <div style={{ fontSize: '1.25rem', fontWeight: 700, color: 'var(--primary)' }}>
              {typeof value === 'number' ? value.toLocaleString() : String(value)}
            </div>
            <div style={{ fontSize: '0.7rem', color: 'var(--text-secondary)', textTransform: 'capitalize' }}>
              {key.replace(/_/g, ' ')}
            </div>
          </div>
        ))}
        <div style={{ gridColumn: '1 / -1', textAlign: 'right' }}>
          <Link href="/" style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: '0.25rem',
            marginTop: '0.5rem',
            fontSize: '0.75rem',
            color: 'var(--primary)',
          }}>
            Open Dashboard &rarr;
          </Link>
        </div>
      </div>
    );
  },
});

// ===== Specialized Tool Renderers =====

const statusColor = (status: string) => {
  const s = String(status).toLowerCase();
  if (s === 'passed' || s === 'pass' || s === 'success') return 'var(--success)';
  if (s === 'failed' || s === 'fail' || s === 'error') return 'var(--danger)';
  if (s === 'running' || s === 'in_progress') return 'var(--warning)';
  return 'var(--text-secondary)';
};

const RecentRunsToolUI = makeAssistantToolUI({
  toolName: 'getRecentRuns',
  render: ({ result }) => {
    if (!result) return <ToolLoading name="Fetching recent runs..." />;
    const data = result as { runs?: Array<Record<string, unknown>>; error?: string };
    if (data.error) return <ToolError message={String(data.error)} />;
    const runs = data.runs || (Array.isArray(result) ? result as Array<Record<string, unknown>> : []);
    if (runs.length === 0) return <div style={{ padding: '0.75rem', fontSize: '0.85rem', color: 'var(--text-secondary)' }}>No recent runs found.</div>;
    return (
      <div style={{
        border: '1px solid var(--border)',
        borderRadius: '8px',
        overflow: 'hidden',
        marginTop: '0.5rem',
        fontSize: '0.8rem',
      }}>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr style={{ background: 'var(--surface)', borderBottom: '1px solid var(--border)' }}>
              <th style={{ padding: '0.5rem 0.75rem', textAlign: 'left', fontWeight: 600, color: 'var(--text-secondary)' }}>Spec</th>
              <th style={{ padding: '0.5rem 0.75rem', textAlign: 'left', fontWeight: 600, color: 'var(--text-secondary)' }}>Status</th>
              <th style={{ padding: '0.5rem 0.75rem', textAlign: 'left', fontWeight: 600, color: 'var(--text-secondary)' }}>Duration</th>
              <th style={{ padding: '0.5rem 0.75rem', textAlign: 'left', fontWeight: 600, color: 'var(--text-secondary)' }}>Date</th>
            </tr>
          </thead>
          <tbody>
            {runs.slice(0, 10).map((run, i) => (
              <tr key={i} style={{ borderBottom: '1px solid var(--border)' }}>
                <td style={{ padding: '0.5rem 0.75rem' }}>
                  {(run.id || run.run_id) ? (
                    <Link href={`/runs/${run.id || run.run_id}`} style={{ color: 'var(--primary)', textDecoration: 'none' }}>
                      {String(run.test_name || run.spec_name || run.name || 'Unknown')}
                    </Link>
                  ) : String(run.test_name || run.spec_name || run.name || 'Unknown')}
                </td>
                <td style={{ padding: '0.5rem 0.75rem' }}>
                  <span style={{
                    display: 'inline-block',
                    padding: '0.15rem 0.5rem',
                    borderRadius: '999px',
                    fontSize: '0.7rem',
                    fontWeight: 600,
                    background: `color-mix(in srgb, ${statusColor(String(run.status || ''))} 15%, transparent)`,
                    color: statusColor(String(run.status || '')),
                  }}>
                    {String(run.status || 'unknown')}
                  </span>
                </td>
                <td style={{ padding: '0.5rem 0.75rem', color: 'var(--text-secondary)' }}>
                  {run.duration ? `${run.duration}s`
                    : (run.started_at && run.completed_at)
                      ? `${Math.round((new Date(String(run.completed_at)).getTime() - new Date(String(run.started_at)).getTime()) / 1000)}s`
                      : '-'}
                </td>
                <td style={{ padding: '0.5rem 0.75rem', color: 'var(--text-secondary)' }}>
                  {(run.started_at || run.created_at)
                    ? new Date(String(run.started_at || run.created_at)).toLocaleDateString()
                    : '-'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <div style={{ padding: '0.5rem 0.75rem', textAlign: 'right', background: 'var(--surface)' }}>
          <Link href="/runs" style={{ fontSize: '0.75rem', color: 'var(--primary)' }}>
            View all runs &rarr;
          </Link>
        </div>
      </div>
    );
  },
});

const ListSpecsToolUI = makeAssistantToolUI({
  toolName: 'listTestSpecs',
  render: ({ result }) => {
    if (!result) return <ToolLoading name="Loading specs..." />;
    const data = result as { specs?: Array<Record<string, unknown>>; error?: string };
    if (data.error) return <ToolError message={String(data.error)} />;
    const specs = data.specs || (Array.isArray(result) ? result as Array<Record<string, unknown>> : []);
    if (specs.length === 0) return <div style={{ padding: '0.75rem', fontSize: '0.85rem', color: 'var(--text-secondary)' }}>No specs found.</div>;
    return (
      <div style={{ marginTop: '0.5rem' }}>
        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))',
          gap: '0.5rem',
        }}>
          {specs.slice(0, 12).map((spec, i) => (
            <div key={i} style={{
              padding: '0.75rem',
              background: 'var(--surface)',
              border: '1px solid var(--border)',
              borderRadius: '8px',
              fontSize: '0.8rem',
            }}>
              <div style={{ fontWeight: 600, marginBottom: '0.25rem', color: 'var(--text)' }}>
                {String(spec.name || spec.title || spec.folder || 'Unnamed')}
              </div>
              {Array.isArray(spec.tags) && spec.tags.length > 0 && (
                <div style={{ display: 'flex', gap: '0.25rem', flexWrap: 'wrap', marginBottom: '0.25rem' }}>
                  {(spec.tags as string[]).slice(0, 3).map((tag: string, j: number) => (
                    <span key={j} style={{
                      padding: '0.1rem 0.4rem',
                      background: 'rgba(59, 130, 246, 0.1)',
                      borderRadius: '4px',
                      fontSize: '0.65rem',
                      color: 'var(--primary)',
                    }}>
                      {tag}
                    </span>
                  ))}
                </div>
              )}
              {typeof spec.last_status === 'string' && (
                <span style={{
                  display: 'inline-block',
                  width: '8px',
                  height: '8px',
                  borderRadius: '50%',
                  background: statusColor(spec.last_status),
                }} />
              )}
            </div>
          ))}
        </div>
        <div style={{ marginTop: '0.5rem', textAlign: 'right' }}>
          <Link href="/specs" style={{ fontSize: '0.75rem', color: 'var(--primary)' }}>
            View all specs &rarr;
          </Link>
        </div>
      </div>
    );
  },
});

const severityConfig: Record<string, { color: string; label: string }> = {
  critical: { color: '#dc2626', label: 'Critical' },
  high: { color: '#ea580c', label: 'High' },
  medium: { color: '#ca8a04', label: 'Medium' },
  low: { color: '#2563eb', label: 'Low' },
  info: { color: '#6b7280', label: 'Info' },
};

const SecurityFindingsToolUI = makeAssistantToolUI({
  toolName: 'getSecurityFindings',
  render: ({ result }) => {
    if (!result) return <ToolLoading name="Loading security findings..." />;
    const data = result as Record<string, unknown>;
    if (data.error) return <ToolError message={String(data.error)} />;
    const findings = (data.findings || data.summary || data) as Record<string, unknown>;
    const counts: Record<string, number> = {};
    let total = 0;
    for (const [sev, cfg] of Object.entries(severityConfig)) {
      const val = Number(findings[sev] || findings[`${sev}_count`] || 0);
      counts[sev] = val;
      total += val;
      void cfg;
    }
    if (total === 0 && typeof findings === 'object') {
      // Try to extract from an array of findings
      const arr = Array.isArray(findings) ? findings : (data.findings && Array.isArray(data.findings) ? data.findings as Array<Record<string, unknown>> : []);
      for (const f of arr) {
        const sev = String(f.severity || 'info').toLowerCase();
        counts[sev] = (counts[sev] || 0) + 1;
        total++;
      }
    }
    return (
      <div style={{
        padding: '0.75rem',
        background: 'var(--surface)',
        border: '1px solid var(--border)',
        borderRadius: '8px',
        marginTop: '0.5rem',
      }}>
        <div style={{ fontSize: '0.8rem', fontWeight: 600, marginBottom: '0.5rem' }}>
          Security Findings ({total} total)
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.35rem' }}>
          {Object.entries(severityConfig).map(([sev, cfg]) => {
            const count = counts[sev] || 0;
            const pct = total > 0 ? (count / total) * 100 : 0;
            return (
              <div key={sev} style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '0.75rem' }}>
                <span style={{ width: '55px', color: cfg.color, fontWeight: 600 }}>{cfg.label}</span>
                <div style={{ flex: 1, height: '6px', background: 'var(--code-bg)', borderRadius: '3px', overflow: 'hidden' }}>
                  <div style={{ width: `${pct}%`, height: '100%', background: cfg.color, borderRadius: '3px', transition: 'width 0.3s' }} />
                </div>
                <span style={{ width: '24px', textAlign: 'right', color: 'var(--text-secondary)' }}>{count}</span>
              </div>
            );
          })}
        </div>
        <div style={{ marginTop: '0.5rem', textAlign: 'right' }}>
          <Link href="/security-testing" style={{ fontSize: '0.75rem', color: 'var(--primary)' }}>
            View findings &rarr;
          </Link>
        </div>
      </div>
    );
  },
});

const RTMSummaryToolUI = makeAssistantToolUI({
  toolName: 'getRTMSummary',
  render: ({ result }) => {
    if (!result) return <ToolLoading name="Loading RTM coverage..." />;
    const data = result as Record<string, unknown>;
    if (data.error) return <ToolError message={String(data.error)} />;
    const covered = Number(data.covered || 0);
    const partial = Number(data.partial || 0);
    const uncovered = Number(data.uncovered || 0);
    const total = covered + partial + uncovered || 1;
    const pct = Math.round((covered / total) * 100);
    return (
      <div style={{
        padding: '0.75rem',
        background: 'var(--surface)',
        border: '1px solid var(--border)',
        borderRadius: '8px',
        marginTop: '0.5rem',
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
          <span style={{ fontSize: '0.8rem', fontWeight: 600 }}>RTM Coverage</span>
          <span style={{ fontSize: '1.1rem', fontWeight: 700, color: pct >= 80 ? 'var(--success)' : pct >= 50 ? 'var(--warning)' : 'var(--danger)' }}>
            {pct}%
          </span>
        </div>
        <div style={{ height: '8px', background: 'var(--code-bg)', borderRadius: '4px', overflow: 'hidden', marginBottom: '0.5rem' }}>
          <div style={{
            display: 'flex',
            height: '100%',
          }}>
            <div style={{ width: `${(covered / total) * 100}%`, background: 'var(--success)', transition: 'width 0.3s' }} />
            <div style={{ width: `${(partial / total) * 100}%`, background: 'var(--warning)', transition: 'width 0.3s' }} />
          </div>
        </div>
        <div style={{ display: 'flex', gap: '1rem', fontSize: '0.7rem', color: 'var(--text-secondary)' }}>
          <span>{covered} covered</span>
          <span>{partial} partial</span>
          <span>{uncovered} uncovered</span>
        </div>
        <div style={{ marginTop: '0.5rem', textAlign: 'right' }}>
          <Link href="/requirements" style={{ fontSize: '0.75rem', color: 'var(--primary)' }}>
            View RTM &rarr;
          </Link>
        </div>
      </div>
    );
  },
});

const SpecContentToolUI = makeAssistantToolUI({
  toolName: 'getSpecContent',
  render: ({ result }) => {
    if (!result) return <ToolLoading name="Loading spec content..." />;
    const data = result as Record<string, unknown>;
    if (data.error) return <ToolError message={String(data.error)} />;
    const content = String(data.content || data.spec || data.markdown || '');
    if (!content) return null;
    return (
      <div style={{
        marginTop: '0.5rem',
        border: '1px solid var(--border)',
        borderRadius: '8px',
        overflow: 'hidden',
      }}>
        <div style={{
          padding: '0.5rem 0.75rem',
          background: 'var(--surface)',
          borderBottom: '1px solid var(--border)',
          fontSize: '0.75rem',
          fontWeight: 600,
          color: 'var(--text-secondary)',
        }}>
          Spec Content
        </div>
        <pre style={{
          padding: '0.75rem',
          background: 'var(--code-bg)',
          overflow: 'auto',
          maxHeight: '300px',
          fontSize: '0.75rem',
          lineHeight: 1.5,
          color: 'var(--text)',
          margin: 0,
          whiteSpace: 'pre-wrap',
          wordBreak: 'break-word',
        }}>
          {content}
        </pre>
      </div>
    );
  },
});

const PassRateTrendsToolUI = makeAssistantToolUI({
  toolName: 'getPassRateTrends',
  render: ({ result }) => {
    if (!result) return <ToolLoading name="Loading pass rate trends..." />;
    const data = result as Record<string, unknown>;
    if (data.error) return <ToolError message={String(data.error)} />;
    // Backend returns { data_points: [...], summary: { avg_pass_rate, total_runs, trend_direction } }
    const trends = (data.data_points || data.trends || data.data || (Array.isArray(result) ? result : [])) as Array<Record<string, unknown>>;
    const summary = data.summary as Record<string, unknown> | undefined;
    const avgRate = summary ? Number(summary.avg_pass_rate ?? 0) : 0;
    const trendDir = summary ? String(summary.trend_direction ?? 'flat') : 'flat';
    // Use summary avg_pass_rate if available, otherwise derive from last data point
    const currentRate = avgRate > 0 ? avgRate : (trends.length > 0 ? Number(trends[trends.length - 1]?.pass_rate ?? trends[trends.length - 1]?.rate ?? 0) : 0);
    const maxRate = Math.max(...trends.map((t) => Number(t.pass_rate ?? t.rate ?? 0)), 1);
    const trendArrow = trendDir === 'up' ? ' \u2191' : trendDir === 'down' ? ' \u2193' : '';
    return (
      <div style={{
        padding: '0.75rem',
        background: 'var(--surface)',
        border: '1px solid var(--border)',
        borderRadius: '8px',
        marginTop: '0.5rem',
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
          <span style={{ fontSize: '0.8rem', fontWeight: 600 }}>Pass Rate Trends</span>
          <span style={{ fontSize: '1.25rem', fontWeight: 700, color: currentRate >= 80 ? 'var(--success)' : currentRate >= 50 ? 'var(--warning)' : 'var(--danger)' }}>
            {Math.round(currentRate)}%{trendArrow}
          </span>
        </div>
        {trends.length > 0 ? (
          <div style={{ display: 'flex', alignItems: 'flex-end', gap: '2px', height: '40px' }}>
            {trends.slice(-20).map((t, i) => {
              const rate = Number(t.pass_rate ?? t.rate ?? 0);
              const height = maxRate > 0 ? (rate / maxRate) * 100 : 0;
              return (
                <div
                  key={i}
                  title={`${String(t.date || '')}: ${Math.round(rate)}%`}
                  style={{
                    flex: 1,
                    height: `${height}%`,
                    minHeight: '2px',
                    background: rate >= 80 ? 'var(--success)' : rate >= 50 ? 'var(--warning)' : 'var(--danger)',
                    borderRadius: '2px 2px 0 0',
                    opacity: 0.8,
                    transition: 'height 0.3s',
                  }}
                />
              );
            })}
          </div>
        ) : (
          <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', padding: '0.5rem 0' }}>
            No test runs found in this period.
          </div>
        )}
      </div>
    );
  },
});

const FailureClassificationToolUI = makeAssistantToolUI({
  toolName: 'getFailureClassification',
  render: ({ result }) => {
    if (!result) return <ToolLoading name="Classifying failures..." />;
    const data = result as Record<string, unknown>;
    if (data.error) return <ToolError message={String(data.error)} />;
    const categories = (data.distribution || data.categories || data.classifications) as Record<string, unknown> | undefined;
    const categoryColors = ['#3b82f6', '#8b5cf6', '#ec4899', '#f59e0b', '#10b981', '#6366f1'];
    const entries = Object.entries(categories ?? {}).filter(([k]) => k !== 'error' && k !== 'total');
    if (entries.length === 0) return null;
    return (
      <div style={{ marginTop: '0.5rem' }}>
        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))',
          gap: '0.5rem',
        }}>
          {entries.map(([category, count], i) => (
            <div key={category} style={{
              padding: '0.75rem',
              background: 'var(--surface)',
              border: '1px solid var(--border)',
              borderLeft: `3px solid ${categoryColors[i % categoryColors.length]}`,
              borderRadius: '4px 8px 8px 4px',
              fontSize: '0.8rem',
            }}>
              <div style={{ fontSize: '1.1rem', fontWeight: 700, color: categoryColors[i % categoryColors.length] }}>
                {typeof count === 'number' ? count : String(count)}
              </div>
              <div style={{ color: 'var(--text-secondary)', fontSize: '0.7rem', textTransform: 'capitalize' }}>
                {category.replace(/_/g, ' ')}
              </div>
            </div>
          ))}
        </div>
      </div>
    );
  },
});

// ===== Run Logs Tool Renderer =====

const RunLogsToolUI = makeAssistantToolUI({
  toolName: 'getRunLogs',
  render: ({ result }) => {
    if (!result) return <ToolLoading name="Fetching run logs..." />;
    const data = result as Record<string, unknown>;
    if (data.error) return <ToolError message={String(data.error)} />;
    const status = String(data.status || 'unknown');
    const specName = String(data.test_name || data.spec_name || data.name || 'Unknown');
    const errorMsg = data.error_message ? String(data.error_message) : null;
    const validation = data.validation as Record<string, unknown> | null;
    const steps = (validation?.steps || validation?.results) as Array<Record<string, unknown>> | undefined;
    return (
      <div style={{
        border: '1px solid var(--border)',
        borderRadius: '8px',
        overflow: 'hidden',
        marginTop: '0.5rem',
        fontSize: '0.8rem',
      }}>
        <div style={{
          padding: '0.5rem 0.75rem',
          background: 'var(--surface)',
          borderBottom: '1px solid var(--border)',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
        }}>
          <span style={{ fontWeight: 600 }}>Run Logs: {specName}</span>
          <span style={{
            padding: '0.15rem 0.5rem',
            borderRadius: '999px',
            fontSize: '0.7rem',
            fontWeight: 600,
            background: `color-mix(in srgb, ${statusColor(status)} 15%, transparent)`,
            color: statusColor(status),
          }}>
            {status}
          </span>
        </div>
        {errorMsg && (
          <div style={{
            padding: '0.5rem 0.75rem',
            background: 'rgba(239, 68, 68, 0.05)',
            borderBottom: '1px solid var(--border)',
            color: 'var(--danger)',
            fontSize: '0.75rem',
            fontFamily: 'monospace',
            whiteSpace: 'pre-wrap',
            maxHeight: '150px',
            overflow: 'auto',
          }}>
            {errorMsg}
          </div>
        )}
        {steps && steps.length > 0 && (
          <div style={{ padding: '0.5rem 0.75rem' }}>
            {steps.map((step, i) => {
              const stepStatus = String(step.status || step.result || 'unknown');
              return (
                <div key={i} style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '0.5rem',
                  padding: '0.25rem 0',
                  borderBottom: i < steps.length - 1 ? '1px solid var(--border)' : 'none',
                }}>
                  <span style={{
                    width: '8px',
                    height: '8px',
                    borderRadius: '50%',
                    background: statusColor(stepStatus),
                    flexShrink: 0,
                  }} />
                  <span style={{ flex: 1 }}>{String(step.name || step.description || `Step ${i + 1}`)}</span>
                  <span style={{ fontSize: '0.7rem', color: 'var(--text-secondary)' }}>{stepStatus}</span>
                </div>
              );
            })}
          </div>
        )}
        <div style={{ padding: '0.5rem 0.75rem', textAlign: 'right', background: 'var(--surface)' }}>
          <Link href={`/runs/${data.id || data.run_id || ''}`} style={{ fontSize: '0.75rem', color: 'var(--primary)' }}>
            View full details &rarr;
          </Link>
        </div>
      </div>
    );
  },
});

// ===== Schedule List Tool Renderer =====

const ScheduleListToolUI = makeAssistantToolUI({
  toolName: 'listSchedules',
  render: ({ result }) => {
    if (!result) return <ToolLoading name="Loading schedules..." />;
    const data = result as Record<string, unknown>;
    if (data.error) return <ToolError message={String(data.error)} />;
    const schedules = (data.schedules || (Array.isArray(result) ? result : [])) as Array<Record<string, unknown>>;
    if (schedules.length === 0) return <div style={{ padding: '0.75rem', fontSize: '0.85rem', color: 'var(--text-secondary)' }}>No schedules configured.</div>;
    return (
      <div style={{
        border: '1px solid var(--border)',
        borderRadius: '8px',
        overflow: 'hidden',
        marginTop: '0.5rem',
        fontSize: '0.8rem',
      }}>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr style={{ background: 'var(--surface)', borderBottom: '1px solid var(--border)' }}>
              <th style={{ padding: '0.5rem 0.75rem', textAlign: 'left', fontWeight: 600, color: 'var(--text-secondary)' }}>Name</th>
              <th style={{ padding: '0.5rem 0.75rem', textAlign: 'left', fontWeight: 600, color: 'var(--text-secondary)' }}>Cron</th>
              <th style={{ padding: '0.5rem 0.75rem', textAlign: 'left', fontWeight: 600, color: 'var(--text-secondary)' }}>Status</th>
            </tr>
          </thead>
          <tbody>
            {schedules.slice(0, 10).map((sched, i) => (
              <tr key={i} style={{ borderBottom: '1px solid var(--border)' }}>
                <td style={{ padding: '0.5rem 0.75rem', fontWeight: 500 }}>{String(sched.name || sched.label || `Schedule ${sched.id || i + 1}`)}</td>
                <td style={{ padding: '0.5rem 0.75rem', fontFamily: 'monospace', fontSize: '0.75rem', color: 'var(--text-secondary)' }}>{String(sched.cron_expression || sched.cron || '-')}</td>
                <td style={{ padding: '0.5rem 0.75rem' }}>
                  <span style={{
                    display: 'inline-block',
                    padding: '0.15rem 0.5rem',
                    borderRadius: '999px',
                    fontSize: '0.7rem',
                    fontWeight: 600,
                    background: sched.enabled || sched.is_active ? 'rgba(16, 185, 129, 0.15)' : 'rgba(107, 114, 128, 0.15)',
                    color: sched.enabled || sched.is_active ? 'var(--success)' : 'var(--text-secondary)',
                  }}>
                    {sched.enabled || sched.is_active ? 'Active' : 'Disabled'}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <div style={{ padding: '0.5rem 0.75rem', textAlign: 'right', background: 'var(--surface)' }}>
          <Link href="/schedules" style={{ fontSize: '0.75rem', color: 'var(--primary)' }}>
            Manage schedules &rarr;
          </Link>
        </div>
      </div>
    );
  },
});

// ===== LLM Analytics Tool Renderer =====

const LlmAnalyticsToolUI = makeAssistantToolUI({
  toolName: 'getLlmAnalytics',
  render: ({ result }) => {
    if (!result) return <ToolLoading name="Loading LLM analytics..." />;
    const data = result as Record<string, unknown>;
    if (data.error) return <ToolError message={String(data.error)} />;
    return (
      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fit, minmax(120px, 1fr))',
        gap: '0.75rem',
        padding: '0.75rem',
        background: 'var(--surface)',
        border: '1px solid var(--border)',
        borderRadius: '8px',
        marginTop: '0.5rem',
      }}>
        {Object.entries(data)
          .filter(([k, v]) => (typeof v === 'number' || (typeof v === 'string' && String(v).length <= 20)) && !k.startsWith('_'))
          .slice(0, 8)
          .map(([key, value]) => (
          <div key={key} style={{ textAlign: 'center' }}>
            <div style={{ fontSize: '1.25rem', fontWeight: 700, color: 'var(--primary)' }}>
              {typeof value === 'number' ? (Number.isInteger(value) ? value.toLocaleString() : value.toFixed(2)) : String(value)}
            </div>
            <div style={{ fontSize: '0.7rem', color: 'var(--text-secondary)', textTransform: 'capitalize' }}>
              {key.replace(/_/g, ' ')}
            </div>
          </div>
        ))}
        <div style={{ gridColumn: '1 / -1', textAlign: 'right' }}>
          <Link href="/llm-testing" style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: '0.25rem',
            marginTop: '0.5rem',
            fontSize: '0.75rem',
            color: 'var(--primary)',
          }}>
            Open LLM Testing &rarr;
          </Link>
        </div>
      </div>
    );
  },
});

// ===== Auto Pilot Status Tool UI =====

const phaseLabels: Record<string, string> = {
  exploration: 'Exploration',
  requirements: 'Requirements',
  spec_generation: 'Spec Generation',
  test_generation: 'Test Generation',
  reporting: 'Reporting',
};

const phaseStatusIcon = (status: string) => {
  if (status === 'completed') return '\u2705';
  if (status === 'running' || status === 'in_progress') return '\u23F3';
  if (status === 'failed') return '\u274C';
  return '\u2B55';
};

const AutoPilotStatusToolUI = makeAssistantToolUI({
  toolName: 'getAutoPilotStatus',
  render: ({ result }) => {
    if (!result) return <ToolLoading name="Loading Auto Pilot status..." />;
    const data = result as Record<string, unknown>;
    if (data.error) return <ToolError message={String(data.error)} />;

    const session = (data.session || {}) as Record<string, unknown>;
    const phases = (data.phases || []) as Array<Record<string, unknown>>;
    const pendingQuestions = (data.pendingQuestions || []) as Array<Record<string, unknown>>;

    const status = String(session.status || 'unknown');
    const progress = typeof session.progress_pct === 'number' ? session.progress_pct : 0;
    const stats = (session.stats || {}) as Record<string, unknown>;

    const statusBadgeColor = status === 'completed' ? '#10b981'
      : status === 'running' ? '#f59e0b'
      : status === 'failed' ? '#ef4444'
      : status === 'paused' ? '#8b5cf6'
      : '#6b7280';

    return (
      <div style={{
        padding: '0.75rem',
        background: 'var(--surface)',
        border: '1px solid var(--border)',
        borderRadius: '8px',
        marginTop: '0.5rem',
      }}>
        {/* Header with status badge */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.75rem' }}>
          <span style={{ fontSize: '1rem' }}>&#x1F916;</span>
          <span style={{ fontWeight: 600, fontSize: '0.9rem' }}>Auto Pilot</span>
          <span style={{
            marginLeft: 'auto',
            padding: '0.15rem 0.5rem',
            borderRadius: '999px',
            fontSize: '0.7rem',
            fontWeight: 600,
            color: 'white',
            background: statusBadgeColor,
            textTransform: 'capitalize',
          }}>{status}</span>
        </div>

        {/* Progress bar */}
        <div style={{
          height: '6px',
          background: 'rgba(255,255,255,0.1)',
          borderRadius: '3px',
          marginBottom: '0.75rem',
        }}>
          <div style={{
            height: '100%',
            width: `${Math.min(progress, 100)}%`,
            background: statusBadgeColor,
            borderRadius: '3px',
            transition: 'width 0.3s ease',
          }} />
        </div>

        {/* Phase stepper */}
        {phases.length > 0 && (
          <div style={{
            display: 'flex',
            gap: '0.25rem',
            flexWrap: 'wrap',
            marginBottom: '0.75rem',
          }}>
            {phases.map((phase, i) => {
              const phaseName = String(phase.phase_name || phase.name || `Phase ${i + 1}`);
              const phaseStatus = String(phase.status || 'pending');
              return (
                <div key={i} style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '0.25rem',
                  padding: '0.2rem 0.5rem',
                  borderRadius: '4px',
                  fontSize: '0.7rem',
                  background: phaseStatus === 'running' ? 'rgba(245, 158, 11, 0.1)' : 'rgba(255,255,255,0.05)',
                  border: phaseStatus === 'running' ? '1px solid rgba(245, 158, 11, 0.3)' : '1px solid transparent',
                }}>
                  <span>{phaseStatusIcon(phaseStatus)}</span>
                  <span>{phaseLabels[phaseName] || phaseName}</span>
                </div>
              );
            })}
          </div>
        )}

        {/* Stats row */}
        {Object.keys(stats).length > 0 && (
          <div style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(90px, 1fr))',
            gap: '0.5rem',
            marginBottom: '0.75rem',
          }}>
            {Object.entries(stats)
              .filter(([, v]) => typeof v === 'number')
              .map(([key, value]) => (
                <div key={key} style={{ textAlign: 'center' }}>
                  <div style={{ fontSize: '1rem', fontWeight: 700, color: 'var(--primary)' }}>
                    {(value as number).toLocaleString()}
                  </div>
                  <div style={{ fontSize: '0.65rem', color: 'var(--text-secondary)', textTransform: 'capitalize' }}>
                    {key.replace(/_/g, ' ')}
                  </div>
                </div>
              ))}
          </div>
        )}

        {/* Pending questions callout */}
        {Array.isArray(pendingQuestions) && pendingQuestions.length > 0 && (
          <div style={{
            padding: '0.6rem',
            background: 'rgba(245, 158, 11, 0.08)',
            border: '1px solid rgba(245, 158, 11, 0.25)',
            borderRadius: '6px',
            marginBottom: '0.5rem',
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem', marginBottom: '0.35rem' }}>
              <AlertTriangle size={14} style={{ color: '#f59e0b' }} />
              <span style={{ fontWeight: 600, fontSize: '0.8rem', color: '#f59e0b' }}>
                Waiting for your input
              </span>
            </div>
            {pendingQuestions.map((q, i) => (
              <div key={i} style={{ fontSize: '0.8rem', color: 'var(--text-primary)', marginTop: '0.25rem' }}>
                {String(q.question_text || q.question || '')}
              </div>
            ))}
          </div>
        )}

        {/* Footer link */}
        <div style={{ textAlign: 'right' }}>
          <Link href="/autopilot" style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: '0.25rem',
            fontSize: '0.75rem',
            color: 'var(--primary)',
          }}>
            View full details &rarr;
          </Link>
        </div>
      </div>
    );
  },
});

// ===== Generic Tool UI (Wildcard - must be registered last) =====

const toolPageMap: Record<string, string> = {
  getTestRuns: '/runs',
  getRecentTestResults: '/runs',
  getRecentRuns: '/runs',
  getSpecList: '/specs',
  listTestSpecs: '/specs',
  updateTestSpec: '/specs',
  listSpecTemplates: '/specs',
  getExplorationSessions: '/exploration',
  getRequirements: '/requirements',
  getRtmCoverage: '/requirements',
  getRTMSummary: '/requirements',
  getDashboardStats: '/',
  getSecurityFindings: '/security-testing',
  getPassRateTrends: '/analytics',
  getFailureClassification: '/analytics',
  getRunLogs: '/runs',
  healFailedRun: '/runs',
  getLlmProviders: '/llm-testing',
  getLlmTestRuns: '/llm-testing',
  getLlmAnalytics: '/llm-testing',
  listSchedules: '/schedules',
  triggerScheduleNow: '/schedules',
  getApiTestRuns: '/api-testing',
  getDatabaseTestSummary: '/database-testing',
  // Regression tools
  compareBatches: '/regression',
  getBatchTrend: '/regression',
  getBatchErrorSummary: '/regression',
  rerunFailedTests: '/regression',
  getRegressionFlakyTests: '/regression',
  // Load testing tools
  compareLoadTestRuns: '/load-testing',
  getLoadTestDashboard: '/load-testing',
  getLoadTestTrends: '/load-testing',
  analyzeLoadTestRun: '/load-testing',
  getLoadTestSystemLimits: '/load-testing',
  // Security testing tools
  analyzeSecurityRun: '/security-testing',
  triageSecurityFinding: '/security-testing',
  compareSecurityScans: '/security-testing',
  // RTM tools
  getRTMGaps: '/requirements',
  exportRTM: '/requirements',
  getRTMTrend: '/requirements',
  // LLM testing tools
  getLlmComparisonMatrix: '/llm-testing',
  getLlmGoldenDashboard: '/llm-testing',
  getLlmCostTracking: '/llm-testing',
  suggestLlmSpecImprovements: '/llm-testing',
  // Database testing tools
  getDbSchemaAnalysis: '/database-testing',
  getDbChecks: '/database-testing',
  suggestDbFixes: '/database-testing',
  // Memory tools
  searchMemory: '/memory',
  getProvenSelectors: '/memory',
  getCoverageGaps: '/memory',
  getTestSuggestions: '/memory',
  // Composite tools
  analyzeFailures: '/analytics',
  fullHealthCheck: '/',
  securityAudit: '/security-testing',
  // Auto Pilot tools
  startAutoPilot: '/autopilot',
  getAutoPilotStatus: '/autopilot',
  answerAutoPilotQuestion: '/autopilot',
  cancelAutoPilot: '/autopilot',
  listAutoPilotSessions: '/autopilot',
};

function ApprovalCard({ toolName, args, addResult, toolCallId }: {
  toolName: string;
  args: Record<string, unknown>;
  addResult: (result: unknown) => void;
  toolCallId?: string;
}) {
  const [status, setStatus] = useState<'pending' | 'executing' | 'done'>('pending');
  const { currentProject } = useProject();
  const { persistToolResult } = useChatContext();
  const config = MUTATING_TOOL_CONFIGS[toolName];
  const label = config?.label || toolName;

  const displayArgs = Object.entries(args || {}).filter(
    ([k]) => !k.startsWith('_')
  );

  const handleApprove = async () => {
    setStatus('executing');
    try {
      const enrichedArgs = { ...args, _projectId: currentProject?.id };
      const res = await fetchWithAuth('/api/chat/execute-tool', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ toolName, args: enrichedArgs }),
      });
      const data = await res.json();
      if (!res.ok) {
        const errorResult = { error: data.error || 'Execution failed' };
        addResult(errorResult);
        if (toolCallId) persistToolResult(toolCallId, toolName, errorResult);
      } else {
        addResult(data);
        if (toolCallId) persistToolResult(toolCallId, toolName, data);
      }
    } catch (err) {
      const errorResult = { error: err instanceof Error ? err.message : 'Network error' };
      addResult(errorResult);
      if (toolCallId) persistToolResult(toolCallId, toolName, errorResult);
    }
    setStatus('done');
  };

  const handleReject = () => {
    const rejectResult = { cancelled: true, message: `User declined: ${label}` };
    addResult(rejectResult);
    if (toolCallId) persistToolResult(toolCallId, toolName, rejectResult);
    setStatus('done');
  };

  if (status === 'executing') {
    return <ToolLoading name={`Executing ${label}...`} />;
  }

  return (
    <div style={{
      padding: '0.75rem',
      background: 'rgba(59, 130, 246, 0.05)',
      border: '1px solid rgba(59, 130, 246, 0.2)',
      borderRadius: '8px',
      marginTop: '0.5rem',
    }}>
      <div style={{
        display: 'flex',
        alignItems: 'center',
        gap: '0.5rem',
        marginBottom: '0.5rem',
      }}>
        <span style={{
          display: 'inline-flex',
          alignItems: 'center',
          justifyContent: 'center',
          width: '20px',
          height: '20px',
          borderRadius: '50%',
          background: 'rgba(59, 130, 246, 0.15)',
          fontSize: '0.7rem',
        }}>&#x26A1;</span>
        <span style={{ fontWeight: 600, fontSize: '0.85rem' }}>{label}</span>
      </div>

      {displayArgs.length > 0 && (
        <div style={{
          padding: '0.5rem',
          background: 'var(--code-bg)',
          borderRadius: '4px',
          marginBottom: '0.5rem',
          fontSize: '0.75rem',
        }}>
          {displayArgs.map(([key, val]) => (
            <div key={key} style={{ marginBottom: '0.15rem' }}>
              <span style={{ color: 'var(--text-secondary)' }}>{key}:</span>{' '}
              <span>{typeof val === 'string' ? val : JSON.stringify(val)}</span>
            </div>
          ))}
        </div>
      )}

      <div style={{ display: 'flex', gap: '0.5rem' }}>
        <button
          onClick={handleApprove}
          disabled={status !== 'pending'}
          style={{
            padding: '0.35rem 0.75rem',
            background: '#10b981',
            color: 'white',
            border: 'none',
            borderRadius: '6px',
            fontSize: '0.8rem',
            fontWeight: 500,
            cursor: 'pointer',
          }}
        >
          Approve
        </button>
        <button
          onClick={handleReject}
          disabled={status !== 'pending'}
          style={{
            padding: '0.35rem 0.75rem',
            background: 'transparent',
            color: '#ef4444',
            border: '1px solid rgba(239, 68, 68, 0.3)',
            borderRadius: '6px',
            fontSize: '0.8rem',
            fontWeight: 500,
            cursor: 'pointer',
          }}
        >
          Reject
        </button>
      </div>
    </div>
  );
}

function ToolCallFallback({ toolName, args, result, addResult, toolCallId }: {
  toolName: string;
  args: Record<string, unknown>;
  result?: unknown;
  addResult: (result: unknown) => void;
  toolCallId?: string;
  [key: string]: unknown;
}) {
  if (!result && MUTATING_TOOL_NAMES.has(toolName)) {
    return (
      <ApprovalCard
        toolName={toolName}
        args={args as Record<string, unknown>}
        addResult={addResult}
        toolCallId={toolCallId}
      />
    );
  }

  if (!result) return <ToolLoading name={`Running ${toolName}...`} />;
  const data = result as Record<string, unknown>;
  if (data.error) return <ToolError message={String(data.error)} />;
  if (data.cancelled) return (
    <div style={{
      padding: '0.75rem',
      background: 'rgba(239, 68, 68, 0.05)',
      border: '1px solid rgba(239, 68, 68, 0.15)',
      borderRadius: '8px',
      marginTop: '0.5rem',
      fontSize: '0.85rem',
      color: 'var(--text-secondary)',
    }}>
      Action declined by user
    </div>
  );
  const pageLink = toolPageMap[toolName];
  return (
    <div>
      <details style={{
        padding: '0.75rem',
        background: 'var(--surface)',
        border: '1px solid var(--border)',
        borderRadius: '8px',
        marginTop: '0.5rem',
        fontSize: '0.85rem',
      }}>
        <summary style={{
          cursor: 'pointer',
          color: 'var(--text-secondary)',
          fontWeight: 500,
          fontSize: '0.8rem',
        }}>
          Tool result: {toolName}
        </summary>
        <pre style={{
          marginTop: '0.5rem',
          padding: '0.5rem',
          background: 'var(--code-bg)',
          borderRadius: '4px',
          overflow: 'auto',
          maxHeight: '200px',
          fontSize: '0.75rem',
          color: 'var(--text)',
        }}>
          {JSON.stringify(data, null, 2)}
        </pre>
      </details>
      {pageLink && (
        <Link href={pageLink} style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: '0.25rem',
          marginTop: '0.25rem',
          marginLeft: '0.75rem',
          fontSize: '0.75rem',
          color: 'var(--primary)',
        }}>
          View in Dashboard &rarr;
        </Link>
      )}
    </div>
  );
}

// ===== Message Components =====

function UserEditComposer() {
  return (
    <div style={{
      display: 'flex',
      justifyContent: 'flex-end',
      marginBottom: '1rem',
      padding: '0 1rem',
    }}>
      <ComposerPrimitive.Root style={{
        display: 'flex',
        flexDirection: 'column',
        gap: '0.5rem',
        maxWidth: '80%',
        width: '100%',
      }}>
        <div style={{ minHeight: '60px' }}>
          <ComposerPrimitive.Input
            style={{
              padding: '0.75rem 1rem',
              background: 'rgba(59, 130, 246, 0.08)',
              border: '1px solid rgba(59, 130, 246, 0.3)',
              borderRadius: '12px',
              fontSize: '0.9rem',
              lineHeight: 1.5,
              color: 'var(--text)',
              outline: 'none',
              fontFamily: 'inherit',
            }}
          />
        </div>
        <div style={{ display: 'flex', gap: '0.35rem', justifyContent: 'flex-end' }}>
          <ComposerPrimitive.Cancel asChild>
            <button style={{
              display: 'flex',
              alignItems: 'center',
              gap: '0.25rem',
              padding: '0.3rem 0.6rem',
              background: 'var(--surface)',
              border: '1px solid var(--border)',
              borderRadius: '6px',
              color: 'var(--text-secondary)',
              fontSize: '0.75rem',
              fontWeight: 500,
              cursor: 'pointer',
            }}>
              <XIcon size={12} />
              Cancel
            </button>
          </ComposerPrimitive.Cancel>
          <ComposerPrimitive.Send asChild>
            <button style={{
              display: 'flex',
              alignItems: 'center',
              gap: '0.25rem',
              padding: '0.3rem 0.6rem',
              background: 'var(--primary)',
              border: 'none',
              borderRadius: '6px',
              color: 'white',
              fontSize: '0.75rem',
              fontWeight: 500,
              cursor: 'pointer',
            }}>
              <Send size={12} />
              Save & Send
            </button>
          </ComposerPrimitive.Send>
        </div>
      </ComposerPrimitive.Root>
    </div>
  );
}

function UserMessage() {
  return (
    <MessagePrimitive.Root style={{
      display: 'flex',
      justifyContent: 'flex-end',
      marginBottom: '1rem',
      padding: '0 1rem',
    }}>
      <div style={{
        maxWidth: '80%',
        position: 'relative',
      }}>
        <div style={{
          padding: '0.75rem 1rem',
          background: 'rgba(59, 130, 246, 0.15)',
          borderRadius: '12px 12px 4px 12px',
          fontSize: '0.9rem',
          lineHeight: 1.5,
        }}>
          <MessagePrimitive.Parts components={{ Text: TextPart, Reasoning: ReasoningPart, ReasoningGroup: ReasoningGroupWrapper }} />
        </div>
        <div style={{
          position: 'absolute',
          top: '-8px',
          right: '-8px',
          opacity: 0.3,
          transition: 'opacity 0.15s',
        }}>
          <ActionBarPrimitive.Edit asChild>
            <button
              title="Edit message"
              aria-label="Edit message"
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                width: '24px',
                height: '24px',
                borderRadius: '6px',
                border: '1px solid var(--border)',
                background: 'var(--surface)',
                color: 'var(--text-secondary)',
                cursor: 'pointer',
                padding: 0,
              }}
            >
              <Pencil size={12} />
            </button>
          </ActionBarPrimitive.Edit>
        </div>
      </div>
    </MessagePrimitive.Root>
  );
}

function ActionButton({ icon, label, onClick, active, activeIcon }: {
  icon: React.ReactNode;
  label: string;
  onClick: () => void;
  active?: boolean;
  activeIcon?: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      title={label}
      aria-label={label}
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        width: '28px',
        height: '28px',
        borderRadius: '6px',
        border: 'none',
        background: 'transparent',
        color: active ? 'var(--success)' : 'var(--text-secondary)',
        cursor: 'pointer',
        padding: 0,
        transition: 'background 0.15s, color 0.15s',
      }}
    >
      {active && activeIcon ? activeIcon : icon}
    </button>
  );
}

function MessageErrorDisplay() {
  const message = useMessage();
  const status = (message as any)?.status as MessageStatus | undefined;

  // Only render when the message has an error status
  if (!status || status.type !== 'incomplete' || status.reason !== 'error') return null;

  const errorText = (status as any).error instanceof Error
    ? (status as any).error.message
    : typeof (status as any).error === 'string'
      ? (status as any).error
      : 'Something went wrong. Please try again.';

  return (
    <div style={{
      display: 'flex',
      alignItems: 'flex-start',
      gap: '0.5rem',
      padding: '0.75rem 1rem',
      marginTop: '0.5rem',
      background: 'rgba(239, 68, 68, 0.08)',
      border: '1px solid rgba(239, 68, 68, 0.2)',
      borderRadius: '8px',
      fontSize: '0.85rem',
      color: 'var(--danger, #ef4444)',
      lineHeight: 1.5,
    }}>
      <AlertTriangle size={16} style={{ flexShrink: 0, marginTop: '2px' }} />
      <div style={{ flex: 1 }}>
        <div>{errorText}</div>
        <ActionBarPrimitive.Reload
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: '0.35rem',
            marginTop: '0.5rem',
            padding: '0.3rem 0.6rem',
            background: 'rgba(239, 68, 68, 0.12)',
            border: '1px solid rgba(239, 68, 68, 0.25)',
            borderRadius: '6px',
            color: 'var(--danger, #ef4444)',
            fontSize: '0.78rem',
            fontWeight: 500,
            cursor: 'pointer',
          }}
        >
          <RefreshCw size={12} />
          Try Again
        </ActionBarPrimitive.Reload>
      </div>
    </div>
  );
}

function BranchPicker() {
  return (
    <BranchPickerPrimitive.Root hideWhenSingleBranch style={{
      display: 'inline-flex',
      alignItems: 'center',
      gap: '0.15rem',
      fontSize: '0.7rem',
      color: 'var(--text-secondary)',
    }}>
      <BranchPickerPrimitive.Previous asChild>
        <button
          title="Previous branch"
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            width: '20px',
            height: '20px',
            borderRadius: '4px',
            border: 'none',
            background: 'transparent',
            color: 'var(--text-secondary)',
            cursor: 'pointer',
            padding: 0,
          }}
        >
          <ChevronLeft size={14} />
        </button>
      </BranchPickerPrimitive.Previous>
      <span style={{ fontSize: '0.65rem', minWidth: '2rem', textAlign: 'center' }}>
        <BranchPickerPrimitive.Number /> / <BranchPickerPrimitive.Count />
      </span>
      <BranchPickerPrimitive.Next asChild>
        <button
          title="Next branch"
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            width: '20px',
            height: '20px',
            borderRadius: '4px',
            border: 'none',
            background: 'transparent',
            color: 'var(--text-secondary)',
            cursor: 'pointer',
            padding: 0,
          }}
        >
          <ChevronRight size={14} />
        </button>
      </BranchPickerPrimitive.Next>
    </BranchPickerPrimitive.Root>
  );
}

function AssistantMessage() {
  const [copied, setCopied] = useState(false);
  const [codeCopied, setCodeCopied] = useState(false);
  const [feedbackSaved, setFeedbackSaved] = useState(false);
  const contentRef = useRef<HTMLDivElement>(null);
  const [rating, setRating] = useState<'up' | 'down' | null>(null);
  const { conversationId } = useChatContext();

  const handleCopy = useCallback(() => {
    const text = contentRef.current?.textContent || '';
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }, []);

  const handleCopyCode = useCallback(() => {
    const codeBlocks = contentRef.current?.querySelectorAll('pre code');
    if (codeBlocks && codeBlocks.length > 0) {
      const code = Array.from(codeBlocks).map(el => el.textContent).join('\n\n');
      navigator.clipboard.writeText(code).then(() => {
        setCodeCopied(true);
        setTimeout(() => setCodeCopied(false), 2000);
      });
    }
  }, []);

  const handleRate = useCallback(async (value: 'up' | 'down') => {
    const newRating = rating === value ? null : value;
    setRating(newRating);
    if (conversationId && newRating) {
      try {
        await fetchWithAuth(`${API_BASE}/chat/conversations/${conversationId}/feedback`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ messageIndex: 0, rating: newRating }),
        });
        setFeedbackSaved(true);
        setTimeout(() => setFeedbackSaved(false), 1500);
      } catch {
        setRating(null);
      }
    }
  }, [rating, conversationId]);

  return (
    <MessagePrimitive.Root style={{
      display: 'flex',
      justifyContent: 'flex-start',
      marginBottom: '1rem',
      padding: '0 1rem',
    }}>
      <div className="assistant-msg-wrapper" style={{
        maxWidth: '85%',
        position: 'relative',
      }}>
        <div ref={contentRef} style={{
          padding: '0.75rem 1rem',
          background: 'var(--surface)',
          border: '1px solid var(--border)',
          borderRadius: '12px 12px 12px 4px',
          fontSize: '0.9rem',
          lineHeight: 1.6,
        }}>
          <MessagePrimitive.Parts components={{
            Text: TextPart,
            Reasoning: ReasoningPart,
            ReasoningGroup: ReasoningGroupWrapper,
            tools: {
              Fallback: ToolCallFallback,
            },
          }} />
        </div>
        <MessageErrorDisplay />
        {/* Rich action bar */}
        <div className="msg-action-bar" style={{
          display: 'flex',
          alignItems: 'center',
          gap: '0.25rem',
          marginTop: '0.35rem',
          paddingLeft: '0.25rem',
          opacity: 0.5,
          transition: 'opacity 0.15s',
        }}>
          <ActionButton
            icon={<Copy size={13} />}
            label="Copy text"
            onClick={handleCopy}
            active={copied}
            activeIcon={<Check size={13} />}
          />
          <ActionButton
            icon={<Code size={13} />}
            label="Copy code blocks"
            onClick={handleCopyCode}
            active={codeCopied}
            activeIcon={<Check size={13} />}
          />
          <BranchPicker />
          <MessagePrimitive.If last>
            <ActionBarPrimitive.Reload
              title="Regenerate response"
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                width: '28px',
                height: '28px',
                borderRadius: '6px',
                border: 'none',
                background: 'transparent',
                color: 'var(--text-secondary)',
                cursor: 'pointer',
                padding: 0,
                transition: 'background 0.15s, color 0.15s',
              }}
            >
              <RefreshCw size={13} />
            </ActionBarPrimitive.Reload>
          </MessagePrimitive.If>
          <ActionButton
            icon={<ThumbsUp size={13} />}
            label="Helpful"
            onClick={() => handleRate('up')}
            active={rating === 'up'}
          />
          <ActionButton
            icon={<ThumbsDown size={13} />}
            label="Not helpful"
            onClick={() => handleRate('down')}
            active={rating === 'down'}
          />
          {feedbackSaved && (
            <span style={{
              fontSize: '0.65rem',
              color: 'var(--success)',
              fontWeight: 500,
              marginLeft: '0.15rem',
              animation: 'fadeIn 0.2s ease-out',
            }}>
              Saved
            </span>
          )}
        </div>
        <FollowUpSuggestions />
      </div>
    </MessagePrimitive.Root>
  );
}

function ReasoningPart({ text, status }: { text: string; status: { type: string }; [key: string]: unknown }) {
  const [expanded, setExpanded] = useState(false);

  if (!text) return null;

  return (
    <div style={{
      background: 'rgba(139, 92, 246, 0.08)',
      border: '1px solid rgba(139, 92, 246, 0.15)',
      borderRadius: '8px',
      marginBottom: '0.5rem',
      overflow: 'hidden',
    }}>
      <button
        onClick={() => setExpanded(!expanded)}
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: '0.4rem',
          width: '100%',
          padding: '0.5rem 0.75rem',
          background: 'transparent',
          border: 'none',
          cursor: 'pointer',
          color: 'var(--text-secondary)',
          fontSize: '0.78rem',
          fontWeight: 500,
        }}
      >
        <Brain size={14} style={{ color: 'rgba(139, 92, 246, 0.7)' }} />
        <span>{status.type === 'running' ? 'Thinking...' : 'Thinking'}</span>
        <ChevronDown
          size={14}
          style={{
            marginLeft: 'auto',
            transform: expanded ? 'rotate(180deg)' : 'none',
            transition: 'transform 0.2s',
          }}
        />
      </button>
      {expanded && (
        <div style={{
          padding: '0.5rem 0.75rem',
          borderTop: '1px solid rgba(139, 92, 246, 0.1)',
          fontFamily: 'var(--font-mono, monospace)',
          fontSize: '0.78rem',
          lineHeight: 1.5,
          color: 'var(--text-secondary)',
          whiteSpace: 'pre-wrap',
          maxHeight: '300px',
          overflowY: 'auto',
        }}>
          {text}
        </div>
      )}
    </div>
  );
}

function ReasoningGroupWrapper({ children }: { children?: React.ReactNode; startIndex: number; endIndex: number }) {
  return <div style={{ marginBottom: '0.5rem' }}>{children}</div>;
}

function TextPart({ text }: TextMessagePartProps) {
  return (
    <div className="assistant-markdown">
      <Markdown remarkPlugins={[remarkGfm]}>{text}</Markdown>
    </div>
  );
}

// ===== Follow-Up Suggestions =====

const toolFollowUps: Record<string, string[]> = {
  getRecentRuns: ['Show details for the latest failure', 'What are the flaky tests?', 'Run regression batch'],
  getDashboardStats: ['Show recent failures', 'Check RTM coverage', 'View analytics'],
  getSecurityFindings: ['Show critical findings detail', 'Run a new scan'],
  getRTMSummary: ['Show uncovered requirements', 'Generate requirements from exploration'],
  getPassRateTrends: ['What tests are flaky?', 'Show failure categories'],
  getFailureClassification: ['Show details for top failure category', 'Show recent failing runs'],
  listTestSpecs: ['Run all specs', 'Show failing specs', 'Create a new spec'],
  getSpecContent: ['Run this spec', 'Edit this spec', 'Show similar specs'],
  navigateToPage: ['What can I do here?', 'Show dashboard stats'],
  getRunLogs: ['Heal this failed test', 'Show the spec content', 'Update the spec'],
  updateTestSpec: ['Run this spec', 'Show spec content', 'View recent runs'],
  healFailedRun: ['Check run status', 'Show recent runs', 'View spec content'],
  listSpecTemplates: ['Create a new spec', 'Show all specs'],
  getLlmProviders: ['Run an LLM test', 'View LLM analytics', 'Compare providers'],
  getLlmTestRuns: ['View LLM analytics', 'Compare runs', 'Check providers'],
  getLlmAnalytics: ['Show LLM providers', 'View test runs', 'Compare models'],
  listSchedules: ['Trigger a schedule now', 'View recent runs', 'Dashboard stats'],
  triggerScheduleNow: ['Check run status', 'View schedules', 'Show recent runs'],
  getApiTestRuns: ['View run details', 'Dashboard stats', 'Show API specs'],
  getDatabaseTestSummary: ['View failed checks', 'Run data quality checks', 'Dashboard stats'],
  compareBatches: ['Analyze failures in detail', 'Show batch error summary', 'Rerun failed tests'],
  getBatchTrend: ['Compare specific batches', 'Show flaky tests', 'View failure categories'],
  getBatchErrorSummary: ['Heal the failing tests', 'Show spec content', 'Rerun failed tests'],
  rerunFailedTests: ['Check run status', 'View batch results', 'Show recent runs'],
  getRegressionFlakyTests: ['Show details for a flaky test', 'View pass rate trends', 'Run regression batch'],
  compareLoadTestRuns: ['Analyze a specific run', 'Show system limits', 'View load test trends'],
  getLoadTestDashboard: ['Compare load test runs', 'Show system limits', 'Analyze a run'],
  getLoadTestTrends: ['Compare runs', 'Show dashboard', 'View system limits'],
  analyzeLoadTestRun: ['Compare with another run', 'Show trends', 'View system limits'],
  getLoadTestSystemLimits: ['Show load test dashboard', 'Run a load test', 'View trends'],
  analyzeSecurityRun: ['Triage a finding', 'Compare scans', 'View findings summary'],
  triageSecurityFinding: ['Show security findings', 'Analyze the scan', 'Compare scans'],
  compareSecurityScans: ['Analyze a scan', 'Triage findings', 'View findings summary'],
  getRTMGaps: ['Export RTM', 'Show coverage trend', 'Generate requirements'],
  exportRTM: ['Show coverage gaps', 'View trend', 'Check coverage summary'],
  getRTMTrend: ['Show gaps', 'Export RTM', 'Check coverage summary'],
  getLlmComparisonMatrix: ['View cost tracking', 'Show golden dashboard', 'Suggest spec improvements'],
  getLlmGoldenDashboard: ['View cost tracking', 'Compare providers', 'Suggest improvements'],
  getLlmCostTracking: ['Show golden dashboard', 'Compare providers', 'View test runs'],
  suggestLlmSpecImprovements: ['View LLM analytics', 'Run an LLM test', 'Show providers'],
  getDbSchemaAnalysis: ['View failed checks', 'Suggest fixes', 'Run data quality checks'],
  getDbChecks: ['Suggest fixes', 'View schema analysis', 'Dashboard stats'],
  suggestDbFixes: ['View checks', 'Schema analysis', 'Dashboard stats'],
  analyzeFailures: ['Show specific failure details', 'Heal failing tests', 'View flaky tests'],
  fullHealthCheck: ['Analyze failures', 'View security posture', 'Check RTM gaps'],
  securityAudit: ['Triage a finding', 'Run a new scan', 'Analyze specific scan'],
  searchMemory: ['Show proven selectors', 'Check coverage gaps', 'Get test suggestions'],
  getProvenSelectors: ['Search similar patterns', 'Show coverage gaps'],
  getCoverageGaps: ['Get test suggestions', 'Create test specs for gaps'],
  getTestSuggestions: ['Create a test spec', 'Check coverage gaps'],
  // Mutating tools
  runTestSpec: ['Check run status', 'Show test results', 'Show recent runs'],
  retryFailedRun: ['Check run status', 'View run logs', 'Show recent runs'],
  createTestSpec: ['Run this test', 'View spec content', 'List all specs'],
  runRegressionBatch: ['View batch results', 'Compare batches', 'Show batch errors'],
  triggerSecurityScan: ['Check scan findings', 'View security summary', 'Analyze scan results'],
  // Auto Pilot
  startAutoPilot: ['Check Auto Pilot status', 'List all Auto Pilot sessions', 'View Auto Pilot dashboard'],
  getAutoPilotStatus: ['Answer a pending question', 'Cancel Auto Pilot', 'Check status again later'],
  answerAutoPilotQuestion: ['Check Auto Pilot status', 'View Auto Pilot dashboard'],
  cancelAutoPilot: ['List Auto Pilot sessions', 'Start a new Auto Pilot'],
  listAutoPilotSessions: ['Check status of a session', 'Start a new Auto Pilot', 'View Auto Pilot dashboard'],
};

function FollowUpSuggestions() {
  // Use useMessage() to access the current message's parts within the MessagePrimitive context
  const message = useMessage();

  let suggestions: string[] = ['Tell me more', 'Show dashboard stats'];

  if (message) {
    // ThreadMessage uses `content` for the parts array
    const parts = (message as any).content || [];
    if (Array.isArray(parts)) {
      for (const p of parts) {
        if ((p.type === 'tool-call' || p.type === 'tool-result') && p.toolName) {
          const specific = toolFollowUps[p.toolName];
          if (specific) {
            suggestions = specific;
            break;
          }
        }
      }
    }
  }

  return (
    <div style={{
      display: 'flex',
      flexWrap: 'wrap',
      gap: '0.35rem',
      marginTop: '0.5rem',
      paddingLeft: '0.25rem',
    }}>
      {suggestions.map((s) => (
        <ThreadPrimitive.Suggestion key={s} prompt={s} method="replace" autoSend>
          <span style={{
            display: 'inline-block',
            padding: '0.3rem 0.6rem',
            background: 'rgba(59, 130, 246, 0.08)',
            border: '1px solid rgba(59, 130, 246, 0.15)',
            borderRadius: '999px',
            color: 'var(--primary)',
            fontSize: '0.7rem',
            fontWeight: 500,
            cursor: 'pointer',
            transition: 'background 0.15s',
          }}>
            {s}
          </span>
        </ThreadPrimitive.Suggestion>
      ))}
    </div>
  );
}

// ===== Typing Indicator =====

function TypingIndicator() {
  const thread = useThread();
  if (!thread.isRunning) return null;

  return (
    <div style={{
      display: 'flex',
      justifyContent: 'flex-start',
      padding: '0 1rem',
      marginBottom: '1rem',
    }}>
      <div style={{
        display: 'flex',
        alignItems: 'center',
        gap: '4px',
        padding: '0.75rem 1rem',
        background: 'var(--surface)',
        border: '1px solid var(--border)',
        borderRadius: '12px 12px 12px 4px',
      }}>
        {[0, 1, 2].map((i) => (
          <span key={i} style={{
            width: '6px',
            height: '6px',
            borderRadius: '50%',
            background: 'var(--text-secondary)',
            animation: `typingBounce 1.4s ease-in-out ${i * 0.2}s infinite`,
          }} />
        ))}
      </div>
    </div>
  );
}

// ===== Slash Commands =====

const slashCommands: Array<{ command: string; label: string; description: string; prompt: string }> = [
  { command: '/run', label: 'Run Tests', description: 'Run a test spec', prompt: 'Run the test spec: ' },
  { command: '/status', label: 'Dashboard Status', description: 'Show dashboard stats', prompt: 'Show me the current dashboard stats and test status' },
  { command: '/explore', label: 'Start Exploration', description: 'Explore a web app', prompt: 'Start a new AI exploration of ' },
  { command: '/trends', label: 'Pass Rate Trends', description: 'Show test trends', prompt: 'Show me the pass rate trends for the last 7 days' },
  { command: '/security', label: 'Security Findings', description: 'View security scan results', prompt: 'Show me the latest security findings' },
  { command: '/coverage', label: 'RTM Coverage', description: 'Check test coverage', prompt: 'Show me the RTM coverage summary' },
  { command: '/specs', label: 'List Specs', description: 'Show test specifications', prompt: 'List all test specifications' },
  { command: '/runs', label: 'Recent Runs', description: 'Show recent test runs', prompt: 'Show me the recent test runs' },
  { command: '/flaky', label: 'Flaky Tests', description: 'Detect flaky tests', prompt: 'Show me the flaky test detection analysis' },
  { command: '/failures', label: 'Failure Analysis', description: 'Classify failures', prompt: 'Show me the failure classification for recent test runs' },
  { command: '/health', label: 'System Health', description: 'Full system health check', prompt: 'Give me a full system health check — dashboard stats, pass rate trends, browser pool status, flaky tests, RTM coverage, and load test system limits' },
  { command: '/batch', label: 'Batch Results', description: 'Latest regression batch', prompt: 'Show me the latest regression batch results with pass/fail breakdown' },
  { command: '/load', label: 'Load Dashboard', description: 'Load testing overview', prompt: 'Show me the load testing dashboard with recent runs and system limits' },
  { command: '/compare', label: 'Compare Batches', description: 'Compare regression batches', prompt: 'Compare the two most recent regression batches side by side' },
  { command: '/gaps', label: 'Coverage Gaps', description: 'RTM coverage gaps', prompt: 'Show me the RTM coverage gaps — which requirements have no tests?' },
  { command: '/costs', label: 'LLM Costs', description: 'LLM cost breakdown', prompt: 'Show me the LLM cost tracking breakdown for the last 30 days' },
  { command: '/audit', label: 'Security Audit', description: 'Security posture review', prompt: 'Give me a security posture review — findings summary, recent scans, and comparison of the latest two scans' },
];

// ===== Step Counter =====

function StepCounter() {
  const thread = useThread();
  if (!thread.isRunning) return null;

  const lastMsg = thread.messages[thread.messages.length - 1];
  if (!lastMsg || lastMsg.role !== 'assistant') return null;

  const parts = (lastMsg as any).content || (lastMsg as any).parts || [];
  const toolCallCount = Array.isArray(parts)
    ? parts.filter((p: any) => p.type === 'tool-call' || p.type === 'tool-result').length
    : 0;
  if (toolCallCount === 0) return null;

  return (
    <div style={{
      display: 'flex',
      justifyContent: 'center',
      padding: '0.25rem',
    }}>
      <span style={{
        fontSize: '0.65rem',
        color: 'var(--text-secondary)',
        background: 'var(--surface)',
        border: '1px solid var(--border)',
        borderRadius: '999px',
        padding: '0.15rem 0.5rem',
      }}>
        Step {toolCallCount}/20
      </span>
    </div>
  );
}

// ===== Continue Button =====

function ContinueButton() {
  const thread = useThread();
  const runtime = useThreadRuntime();

  if (thread.isRunning) return null;
  if (thread.messages.length === 0) return null;

  const lastMsg = thread.messages[thread.messages.length - 1];
  if (!lastMsg || lastMsg.role !== 'assistant') return null;

  const parts = (lastMsg as any).content || [];
  const toolCallCount = Array.isArray(parts)
    ? parts.filter((p: any) => p.type === 'tool-call' || p.type === 'tool-result').length
    : 0;

  if (toolCallCount < 15) return null;

  return (
    <div style={{
      display: 'flex',
      justifyContent: 'center',
      padding: '0.5rem',
    }}>
      <button
        onClick={() => {
          runtime.composer.setText('Please continue from where you left off.');
          runtime.composer.send();
        }}
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: '0.4rem',
          padding: '0.4rem 0.75rem',
          background: 'rgba(59, 130, 246, 0.1)',
          border: '1px solid rgba(59, 130, 246, 0.2)',
          borderRadius: '999px',
          color: 'var(--primary)',
          fontSize: '0.78rem',
          fontWeight: 500,
          cursor: 'pointer',
          transition: 'background 0.15s',
        }}
      >
        <RefreshCw size={13} />
        Continue analysis...
      </button>
    </div>
  );
}

// ===== Attachment Preview =====

function ComposerAttachmentPreview() {
  const attachment = useThreadComposerAttachment();
  const attachmentRuntime = useAttachmentRuntime();

  if (!attachment) return null;

  const isImage = attachment.type === 'image';
  const previewUrl = attachment.file ? URL.createObjectURL(attachment.file) : undefined;

  return (
    <div style={{
      position: 'relative',
      display: 'inline-flex',
      alignItems: 'center',
      gap: '0.4rem',
      padding: '0.35rem 0.5rem',
      background: 'rgba(59, 130, 246, 0.08)',
      border: '1px solid rgba(59, 130, 246, 0.15)',
      borderRadius: '8px',
      fontSize: '0.75rem',
      maxWidth: '200px',
    }}>
      {isImage && previewUrl ? (
        <img
          src={previewUrl}
          alt={attachment.name}
          style={{
            width: '32px',
            height: '32px',
            borderRadius: '4px',
            objectFit: 'cover',
          }}
        />
      ) : (
        <ImageIcon size={16} style={{ color: 'var(--text-secondary)', flexShrink: 0 }} />
      )}
      <span style={{
        overflow: 'hidden',
        textOverflow: 'ellipsis',
        whiteSpace: 'nowrap',
        color: 'var(--text-primary)',
      }}>
        {attachment.name}
      </span>
      <button
        onClick={() => attachmentRuntime.remove()}
        style={{
          display: 'flex',
          alignItems: 'center',
          background: 'none',
          border: 'none',
          cursor: 'pointer',
          padding: '2px',
          color: 'var(--text-secondary)',
          flexShrink: 0,
        }}
      >
        <XIcon size={12} />
      </button>
    </div>
  );
}

// ===== Composer =====

function Composer() {
  const runtime = useThreadRuntime();
  const [inputText, setInputText] = useState('');
  const [showCommands, setShowCommands] = useState(false);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // @-mention state
  const [showMentions, setShowMentions] = useState(false);
  const [mentionQuery, setMentionQuery] = useState('');
  const [mentionResults, setMentionResults] = useState<MentionEntity[]>([]);
  const [mentionIndex, setMentionIndex] = useState(0);
  const [selectedMentions, setSelectedMentions] = useState<MentionEntity[]>([]);
  const mentionStartRef = useRef<number>(-1);
  const mentionDebounceRef = useRef<ReturnType<typeof setTimeout>>(undefined);

  const { currentProject } = useProject();

  // Filter commands based on current input
  const filtered = inputText.startsWith('/')
    ? slashCommands.filter(cmd => cmd.command.startsWith(inputText.toLowerCase()))
    : [];

  useEffect(() => {
    if (filtered.length > 0 && inputText.startsWith('/')) {
      setShowCommands(true);
      setSelectedIndex(0);
    } else {
      setShowCommands(false);
    }
  }, [inputText, filtered.length]);

  // @-mention search
  useEffect(() => {
    if (!mentionQuery || mentionQuery.length < 1) {
      setMentionResults([]);
      return;
    }
    if (mentionDebounceRef.current) clearTimeout(mentionDebounceRef.current);
    mentionDebounceRef.current = setTimeout(async () => {
      try {
        const params = new URLSearchParams({ q: mentionQuery, limit: '8' });
        if (currentProject?.id) params.set('project_id', currentProject.id);
        const res = await fetch(`/api/chat/entities?${params.toString()}`);
        if (res.ok) {
          const data = await res.json();
          setMentionResults(data.entities || []);
        }
      } catch { /* ignore */ }
    }, 200);
    return () => { if (mentionDebounceRef.current) clearTimeout(mentionDebounceRef.current); };
  }, [mentionQuery, currentProject?.id]);

  const selectCommand = useCallback((cmd: typeof slashCommands[0]) => {
    setShowCommands(false);
    setInputText('');
    // Check if the prompt ends with a space (expects user completion) or is complete
    const needsUserInput = cmd.prompt.endsWith(': ') || cmd.prompt.endsWith('of ');
    if (needsUserInput) {
      runtime.composer.setText(cmd.prompt);
      // Focus the input after setting text
      setTimeout(() => inputRef.current?.focus(), 0);
    } else {
      runtime.composer.setText(cmd.prompt);
      runtime.composer.send();
    }
  }, [runtime]);

  const selectMention = useCallback(async (entity: MentionEntity) => {
    setShowMentions(false);
    setMentionQuery('');
    setSelectedMentions(prev => {
      // Don't add duplicates
      if (prev.some(m => m.type === entity.type && m.id === entity.id)) return prev;
      return [...prev, entity];
    });
    // Replace @query with empty (user sees it as chip instead)
    if (mentionStartRef.current >= 0) {
      const before = inputText.slice(0, mentionStartRef.current);
      const afterAt = inputText.slice(mentionStartRef.current + 1);
      const spaceIndex = afterAt.search(/[\s\n]/);
      const after = spaceIndex >= 0 ? afterAt.slice(spaceIndex) : '';
      const newText = before + after;
      setInputText(newText);
      runtime.composer.setText(newText);
    }
    mentionStartRef.current = -1;
  }, [inputText, runtime]);

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    // Mention dropdown navigation
    if (showMentions && mentionResults.length > 0) {
      if (e.key === 'ArrowUp') {
        e.preventDefault();
        setMentionIndex(i => Math.max(0, i - 1));
        return;
      } else if (e.key === 'ArrowDown') {
        e.preventDefault();
        setMentionIndex(i => Math.min(mentionResults.length - 1, i + 1));
        return;
      } else if ((e.key === 'Enter' || e.key === 'Tab') && mentionResults[mentionIndex]) {
        e.preventDefault();
        selectMention(mentionResults[mentionIndex]);
        return;
      } else if (e.key === 'Escape') {
        setShowMentions(false);
        return;
      }
    }

    // Slash command navigation (existing)
    if (!showCommands) return;
    if (e.key === 'ArrowUp') {
      e.preventDefault();
      setSelectedIndex(i => Math.max(0, i - 1));
    } else if (e.key === 'ArrowDown') {
      e.preventDefault();
      setSelectedIndex(i => Math.min(filtered.length - 1, i + 1));
    } else if (e.key === 'Enter' && filtered[selectedIndex]) {
      e.preventDefault();
      selectCommand(filtered[selectedIndex]);
    } else if (e.key === 'Escape') {
      setShowCommands(false);
    }
  }, [showCommands, filtered, selectedIndex, selectCommand, showMentions, mentionResults, mentionIndex, selectMention]);

  const handleInput = useCallback((e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const value = e.target.value;
    setInputText(value);

    // Detect @ for mentions
    const cursorPos = e.target.selectionStart || 0;
    const textBeforeCursor = value.slice(0, cursorPos);
    const atIndex = textBeforeCursor.lastIndexOf('@');

    if (atIndex >= 0) {
      const textAfterAt = textBeforeCursor.slice(atIndex + 1);
      // Only trigger if no space in the query (user is still typing the mention)
      if (!textAfterAt.includes(' ') && !textAfterAt.includes('\n')) {
        mentionStartRef.current = atIndex;
        setMentionQuery(textAfterAt);
        setShowMentions(true);
        setMentionIndex(0);
        return;
      }
    }
    setShowMentions(false);
    setMentionQuery('');
  }, []);

  const handleSend = useCallback(async () => {
    if (!inputText.trim() && selectedMentions.length === 0) return;

    let finalMessage = inputText;

    // Resolve mention content and prepend
    if (selectedMentions.length > 0) {
      const contextParts: string[] = [];
      for (const mention of selectedMentions) {
        try {
          const params = new URLSearchParams({ type: mention.type, id: mention.id });
          if (currentProject?.id) params.set('project_id', currentProject.id);
          const res = await fetch(`/api/chat/entities/resolve?${params.toString()}`);
          if (res.ok) {
            const data = await res.json();
            if (data.content) {
              contextParts.push(`[Referenced: ${mention.label}]\n${data.content}`);
            }
          }
        } catch { /* skip failed resolves */ }
      }
      if (contextParts.length > 0) {
        finalMessage = contextParts.join('\n\n') + '\n\n---\n\n' + inputText;
      }
    }

    runtime.composer.setText(finalMessage);
    runtime.composer.send();
    setInputText('');
    setSelectedMentions([]);
  }, [inputText, selectedMentions, currentProject?.id, runtime]);

  return (
    <ComposerPrimitive.Root style={{
      display: 'flex',
      flexDirection: 'column',
      gap: '0.25rem',
      padding: '0.75rem 1rem',
      borderTop: '1px solid var(--border)',
      background: 'var(--surface)',
      position: 'relative',
    }}>
      {/* Selected mention chips */}
      {selectedMentions.length > 0 && (
        <div style={{
          display: 'flex',
          flexWrap: 'wrap',
          gap: '0.25rem',
          padding: '0.25rem 0',
          width: '100%',
        }}>
          {selectedMentions.map((m, i) => (
            <span key={`${m.type}-${m.id}-${i}`} style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: '0.25rem',
              padding: '0.15rem 0.5rem',
              background: 'rgba(59, 130, 246, 0.1)',
              border: '1px solid rgba(59, 130, 246, 0.2)',
              borderRadius: '999px',
              fontSize: '0.7rem',
              color: 'var(--primary)',
              fontWeight: 500,
            }}>
              <span style={{
                fontSize: '0.6rem',
                opacity: 0.7,
                textTransform: 'uppercase',
              }}>{m.type}</span>
              {m.label}
              <button
                onClick={() => setSelectedMentions(prev => prev.filter((_, j) => j !== i))}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  background: 'none',
                  border: 'none',
                  cursor: 'pointer',
                  padding: 0,
                  color: 'var(--text-secondary)',
                }}
              >
                <XIcon size={10} />
              </button>
            </span>
          ))}
        </div>
      )}

      {/* Attachment previews */}
      <ComposerPrimitive.Attachments
        components={{
          Image: ComposerAttachmentPreview,
          Document: ComposerAttachmentPreview,
          File: ComposerAttachmentPreview,
        }}
      />

      <div style={{ display: 'flex', alignItems: 'flex-end', gap: '0.5rem', width: '100%', position: 'relative' }}>
        {/* Slash command dropdown */}
        {showCommands && filtered.length > 0 && (
          <div style={{
            position: 'absolute',
            bottom: '100%',
            left: 0,
            right: 0,
            maxHeight: '200px',
            overflowY: 'auto',
            background: 'var(--surface)',
            border: '1px solid var(--border)',
            borderRadius: '8px',
            boxShadow: '0 -4px 12px rgba(0,0,0,0.15)',
            marginBottom: '4px',
            zIndex: 10,
          }}>
            {filtered.map((cmd, i) => (
              <button
                key={cmd.command}
                onClick={() => selectCommand(cmd)}
                style={{
                  display: 'flex',
                  flexDirection: 'column',
                  width: '100%',
                  padding: '0.5rem 0.75rem',
                  background: i === selectedIndex ? 'rgba(59, 130, 246, 0.1)' : 'transparent',
                  border: 'none',
                  textAlign: 'left',
                  cursor: 'pointer',
                }}
              >
                <span style={{ fontSize: '0.8rem', fontWeight: 600, color: 'var(--primary)' }}>{cmd.command}</span>
                <span style={{ fontSize: '0.7rem', color: 'var(--text-secondary)' }}>{cmd.description}</span>
              </button>
            ))}
          </div>
        )}

        {/* @-mention dropdown */}
        {showMentions && mentionResults.length > 0 && (
          <div style={{
            position: 'absolute',
            bottom: '100%',
            left: 0,
            right: 0,
            maxHeight: '200px',
            overflowY: 'auto',
            background: 'var(--surface)',
            border: '1px solid var(--border)',
            borderRadius: '8px',
            boxShadow: '0 -4px 12px rgba(0,0,0,0.15)',
            marginBottom: '4px',
            zIndex: 10,
          }}>
            {mentionResults.map((entity, i) => (
              <button
                key={`${entity.type}-${entity.id}`}
                onClick={() => selectMention(entity)}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '0.5rem',
                  width: '100%',
                  padding: '0.5rem 0.75rem',
                  background: i === mentionIndex ? 'rgba(59, 130, 246, 0.1)' : 'transparent',
                  border: 'none',
                  textAlign: 'left',
                  cursor: 'pointer',
                }}
              >
                <span style={{
                  fontSize: '0.6rem',
                  fontWeight: 600,
                  textTransform: 'uppercase',
                  padding: '0.1rem 0.3rem',
                  borderRadius: '3px',
                  background: 'rgba(139, 92, 246, 0.1)',
                  color: 'rgba(139, 92, 246, 0.8)',
                }}>{entity.type}</span>
                <div style={{ display: 'flex', flexDirection: 'column', minWidth: 0 }}>
                  <span style={{ fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-primary)' }}>{entity.label}</span>
                  <span style={{ fontSize: '0.7rem', color: 'var(--text-secondary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{entity.description}</span>
                </div>
              </button>
            ))}
          </div>
        )}

        <ComposerPrimitive.AddAttachment
          aria-label="Attach image"
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            width: '36px',
            height: '36px',
            borderRadius: '8px',
            border: 'none',
            background: 'transparent',
            color: 'var(--text-secondary)',
            cursor: 'pointer',
            flexShrink: 0,
            transition: 'color 0.15s, background 0.15s',
          }}
        >
          <Paperclip size={16} />
        </ComposerPrimitive.AddAttachment>
        <ComposerPrimitive.Input
          ref={inputRef}
          placeholder="Ask anything... (/ commands, @ mentions)"
          className="aui-composer-input"
          onKeyDown={handleKeyDown}
          onChange={handleInput}
          addAttachmentOnPaste
        />
        <ComposerPrimitive.Send
          aria-label="Send message"
          onClick={selectedMentions.length > 0 ? (e: React.MouseEvent) => { e.preventDefault(); handleSend(); } : undefined}
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            width: '36px',
            height: '36px',
            borderRadius: '8px',
            background: 'var(--primary)',
            color: 'white',
            cursor: 'pointer',
            flexShrink: 0,
          }}
        >
          <Send size={16} />
        </ComposerPrimitive.Send>
      </div>
    </ComposerPrimitive.Root>
  );
}

// ===== Welcome Screen =====

function getSuggestionsForPage(pathname: string): string[] {
  if (pathname?.includes('/specs')) return ['Run all tests', 'Show failing specs', 'Create new spec', 'Dashboard stats'];
  if (pathname?.includes('/exploration')) return ['Generate requirements', 'Start new exploration', 'Show discoveries', 'Dashboard stats'];
  if (pathname?.includes('/requirements')) return ['Check RTM coverage', 'Find gaps', 'Export requirements', 'Dashboard stats'];
  if (pathname?.includes('/security')) return ['Show critical findings', 'Generate remediation', 'Run quick scan', 'Dashboard stats'];
  if (pathname?.includes('/load-testing')) return ['Compare load test runs', 'Show recent results', 'Generate K6 script', 'Dashboard stats'];
  if (pathname?.includes('/runs')) return ['Show failing tests', 'Rerun failed tests', 'View latest run', 'Dashboard stats'];
  return ['What can you do?', 'Show recent test results', 'Dashboard stats', 'Check coverage'];
}

const welcomeCategories = [
  {
    icon: FlaskConical,
    label: 'Test Management',
    desc: 'Run, view, and analyze tests',
    suggestion: 'Show recent test results',
    color: '#3b82f6',
  },
  {
    icon: Search,
    label: 'Discovery',
    desc: 'Explore apps and generate requirements',
    suggestion: 'Start new exploration',
    color: '#8b5cf6',
  },
  {
    icon: Shield,
    label: 'Security',
    desc: 'Scan for vulnerabilities',
    suggestion: 'Run a security scan',
    color: '#ef4444',
  },
  {
    icon: BarChart3,
    label: 'Analytics',
    desc: 'Track trends and performance',
    suggestion: 'Show pass rate trends',
    color: '#10b981',
  },
];

function WelcomeScreen() {
  const pathname = usePathname();
  const { data, loading } = useProjectContext();

  const iconMap: Record<string, any> = {
    FlaskConical, Search, Shield, BarChart3, AlertTriangle, Clock, RefreshCw,
  };

  // Use API cards or fallback to static
  const cards = data?.welcome_cards?.length > 0
    ? data.welcome_cards
    : welcomeCategories.map((c: any) => ({ icon: c.icon.displayName || c.icon.name || 'FlaskConical', label: c.label, desc: c.desc, suggestion: c.suggestion, color: c.color, metric: null }));

  const suggestions = data?.dynamic_suggestions?.length > 0
    ? data.dynamic_suggestions
    : getSuggestionsForPage(pathname);

  return (
    <ThreadPrimitive.Empty>
      <style>{`@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }`}</style>
      <div className="animate-in" style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '2rem 1rem',
        textAlign: 'center',
        gap: '1.5rem',
        height: '100%',
      }}>
        <div style={{
          width: '48px',
          height: '48px',
          borderRadius: '12px',
          background: 'rgba(59, 130, 246, 0.15)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          fontSize: '0.9rem',
          fontWeight: 700,
          color: 'var(--primary)',
        }}>
          AI
        </div>
        <div>
          <h3 style={{ fontSize: '1.1rem', fontWeight: 600, marginBottom: '0.5rem' }}>
            Welcome back
          </h3>
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.85rem', maxWidth: '360px' }}>
            I can help you run tests, explore apps, analyze results, and navigate the platform.
          </p>
        </div>

        {/* Category cards */}
        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(2, 1fr)',
          gap: '0.5rem',
          maxWidth: '400px',
          width: '100%',
        }}>
          {loading ? (
            // Shimmer skeleton cards
            Array.from({ length: 4 }).map((_, i) => (
              <div key={i} style={{
                padding: '0.75rem',
                background: 'var(--surface)',
                border: '1px solid var(--border)',
                borderRadius: '8px',
                height: '90px',
                animation: 'pulse 1.5s ease-in-out infinite',
                animationDelay: `${i * 0.15}s`,
              }}>
                <div style={{ width: '18px', height: '18px', borderRadius: '4px', background: 'var(--border)', marginBottom: '0.5rem' }} />
                <div style={{ width: '60%', height: '0.7rem', borderRadius: '3px', background: 'var(--border)', marginBottom: '0.3rem' }} />
                <div style={{ width: '85%', height: '0.6rem', borderRadius: '3px', background: 'var(--border)' }} />
              </div>
            ))
          ) : (
            cards.map((card: any) => {
              // Resolve icon: if it's a string, look up in map; if it's already a component, use directly
              const Icon = typeof card.icon === 'string' ? iconMap[card.icon] || FlaskConical : card.icon;
              return (
                <ThreadPrimitive.Suggestion key={card.label} prompt={card.suggestion} method="replace" autoSend>
                  <div style={{
                    display: 'flex',
                    flexDirection: 'column',
                    alignItems: 'flex-start',
                    gap: '0.35rem',
                    padding: '0.75rem',
                    background: 'var(--surface)',
                    border: '1px solid var(--border)',
                    borderRadius: '8px',
                    cursor: 'pointer',
                    textAlign: 'left',
                    transition: 'border-color 0.15s, background 0.15s',
                    position: 'relative',
                  }}>
                    <Icon size={18} style={{ color: card.color }} />
                    <div style={{ fontSize: '0.8rem', fontWeight: 600, color: 'var(--text)' }}>
                      {card.label}
                    </div>
                    <div style={{ fontSize: '0.7rem', color: 'var(--text-secondary)', lineHeight: 1.3 }}>
                      {card.desc}
                    </div>
                    {card.metric && (
                      <span style={{
                        position: 'absolute',
                        top: '0.5rem',
                        right: '0.5rem',
                        fontSize: '0.65rem',
                        fontWeight: 700,
                        padding: '0.1rem 0.4rem',
                        borderRadius: '999px',
                        background: `${card.color}20`,
                        color: card.color,
                      }}>
                        {card.metric}
                      </span>
                    )}
                  </div>
                </ThreadPrimitive.Suggestion>
              );
            })
          )}
        </div>

        {/* Context-aware suggestion chips */}
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.5rem', justifyContent: 'center' }}>
          {suggestions.map((s: string) => (
            <ThreadPrimitive.Suggestion key={s} prompt={s} method="replace" autoSend>
              <span style={{
                display: 'inline-block',
                padding: '0.5rem 0.75rem',
                background: 'rgba(59, 130, 246, 0.1)',
                border: '1px solid rgba(59, 130, 246, 0.2)',
                borderRadius: '999px',
                color: 'var(--primary)',
                fontSize: '0.8rem',
                fontWeight: 500,
                cursor: 'pointer',
              }}>
                {s}
              </span>
            </ThreadPrimitive.Suggestion>
          ))}
        </div>
      </div>
    </ThreadPrimitive.Empty>
  );
}

// ===== Message Skeleton =====

function MessageSkeleton({ align }: { align: 'left' | 'right' }) {
  return (
    <div style={{
      display: 'flex',
      justifyContent: align === 'right' ? 'flex-end' : 'flex-start',
      padding: '0 1rem',
      marginBottom: '1rem',
    }}>
      <div style={{
        width: align === 'right' ? '60%' : '75%',
        padding: '0.75rem 1rem',
        background: 'var(--surface)',
        border: '1px solid var(--border)',
        borderRadius: '12px',
        animation: 'pulse 1.5s ease-in-out infinite',
      }}>
        <div style={{ height: '0.8rem', background: 'var(--border)', borderRadius: '4px', marginBottom: '0.5rem', width: '80%' }} />
        <div style={{ height: '0.8rem', background: 'var(--border)', borderRadius: '4px', width: '60%' }} />
      </div>
    </div>
  );
}

// ===== Main Thread Component =====

export function AssistantThread({ className }: { className?: string }) {
  const { isLoadingHistory } = useChatContext();

  return (
    <ThreadPrimitive.Root className={className} style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      {/* Tool UIs registered at top */}
      <NavigateToolUI />
      <DashboardStatsToolUI />
      <RecentRunsToolUI />
      <ListSpecsToolUI />
      <SecurityFindingsToolUI />
      <RTMSummaryToolUI />
      <SpecContentToolUI />
      <PassRateTrendsToolUI />
      <FailureClassificationToolUI />
      <RunLogsToolUI />
      <ScheduleListToolUI />
      <LlmAnalyticsToolUI />
      <AutoPilotStatusToolUI />

      {isLoadingHistory ? (
        <div style={{ flex: 1, overflow: 'hidden', padding: '1rem 0' }}>
          <style>{`@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }`}</style>
          <MessageSkeleton align="right" />
          <MessageSkeleton align="left" />
          <MessageSkeleton align="right" />
          <MessageSkeleton align="left" />
        </div>
      ) : (
        <div style={{ flex: 1, position: 'relative', overflow: 'hidden' }}>
          <ThreadPrimitive.Viewport style={{ height: '100%', overflow: 'auto' }}>
            <WelcomeScreen />
            <ThreadPrimitive.Messages
              components={{
                UserMessage,
                AssistantMessage,
                UserEditComposer,
              }}
            />
            <TypingIndicator />
          </ThreadPrimitive.Viewport>

          <ThreadPrimitive.ScrollToBottom
            style={{
              position: 'absolute',
              bottom: '8px',
              left: '50%',
              transform: 'translateX(-50%)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              width: '32px',
              height: '32px',
              borderRadius: '50%',
              background: 'var(--surface)',
              border: '1px solid var(--border)',
              color: 'var(--text-secondary)',
              cursor: 'pointer',
              boxShadow: '0 2px 8px rgba(0, 0, 0, 0.2)',
              zIndex: 10,
            }}
          >
            <ArrowDown size={16} />
          </ThreadPrimitive.ScrollToBottom>
        </div>
      )}

      <StepCounter />
      <ContinueButton />
      <Composer />
    </ThreadPrimitive.Root>
  );
}
