'use client';

import { useState, useRef, useCallback, useEffect, useMemo } from 'react';
import type { CSSProperties, Dispatch, SetStateAction } from 'react';
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

function ToolStaleState({ toolName }: { toolName: string }) {
  return (
    <div style={{
      padding: '0.75rem',
      background: 'rgba(245, 158, 11, 0.08)',
      border: '1px solid rgba(245, 158, 11, 0.24)',
      borderRadius: '8px',
      color: 'var(--text-secondary)',
      fontSize: '0.85rem',
      marginTop: '0.5rem',
      lineHeight: 1.45,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.45rem', color: '#f59e0b', fontWeight: 600 }}>
        <AlertTriangle size={14} />
        <span>No tool result was received</span>
      </div>
      <div style={{ marginTop: '0.35rem' }}>
        The assistant started {toolDisplayName(toolName)}, but the chat stream did not return a result.
        Try the request again or open the related page to check the data directly.
      </div>
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
  if (['passed', 'pass', 'success', 'succeeded', 'completed', 'complete', 'done', 'finished', 'created', 'saved', 'synced'].includes(s)) return 'var(--success)';
  if (['failed', 'fail', 'error', 'errored', 'cancelled', 'canceled', 'timeout', 'timed_out'].includes(s)) return 'var(--danger)';
  if (['running', 'in_progress', 'processing', 'queued', 'pending', 'scheduled', 'starting', 'started', 'awaiting_input'].includes(s)) return 'var(--warning)';
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
  test_ideas: 'Test Ideas',
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
    const specTasks = (data.specTasks || []) as Array<Record<string, unknown>>;
    const testTasks = (data.testTasks || []) as Array<Record<string, unknown>>;

    const status = String(session.status || 'unknown');
    const progress = typeof session.overall_progress === 'number'
      ? session.overall_progress
      : typeof session.progress_pct === 'number'
        ? session.progress_pct
        : 0;
    const stats = (session.stats || {
      pages: session.total_pages_discovered,
      flows: session.total_flows_discovered,
      requirements: session.total_requirements_generated,
      specs: session.total_specs_generated,
      tests: session.total_tests_generated,
      passed: session.total_tests_passed,
      failed: session.total_tests_failed,
    }) as Record<string, unknown>;
    const summarizeStatus = (items: Array<Record<string, unknown>>) => items.reduce<Record<string, number>>((acc, item) => {
      const s = String(item.status || 'unknown');
      acc[s] = (acc[s] || 0) + 1;
      return acc;
    }, {});
    const specSummary = summarizeStatus(specTasks);
    const testSummary = summarizeStatus(testTasks);

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

        {(specTasks.length > 0 || testTasks.length > 0) && (
          <div style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(120px, 1fr))',
            gap: '0.5rem',
            marginBottom: '0.75rem',
          }}>
            {specTasks.length > 0 && (
              <div style={{ padding: '0.5rem', background: 'rgba(255,255,255,0.04)', borderRadius: '6px' }}>
                <div style={{ fontSize: '0.7rem', color: 'var(--text-secondary)', marginBottom: '0.25rem' }}>Spec tasks</div>
                <div style={{ fontSize: '0.8rem' }}>
                  {Object.entries(specSummary).map(([k, v]) => `${k}: ${v}`).join(' · ')}
                </div>
              </div>
            )}
            {testTasks.length > 0 && (
              <div style={{ padding: '0.5rem', background: 'rgba(255,255,255,0.04)', borderRadius: '6px' }}>
                <div style={{ fontSize: '0.7rem', color: 'var(--text-secondary)', marginBottom: '0.25rem' }}>Test tasks</div>
                <div style={{ fontSize: '0.8rem' }}>
                  {Object.entries(testSummary).map(([k, v]) => `${k}: ${v}`).join(' · ')}
                </div>
              </div>
            )}
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

function ciArray(value: unknown): Array<Record<string, unknown>> {
  return Array.isArray(value) ? value.filter((item) => item && typeof item === 'object') as Array<Record<string, unknown>> : [];
}

function ciStatusLabel(value: unknown) {
  return compactLabel(String(value || 'unknown'));
}

function ciProviderName(value: unknown) {
  const provider = String(value || '').toLowerCase();
  return provider === 'gitlab' ? 'GitLab' : provider === 'github' ? 'GitHub' : compactLabel(provider || 'provider');
}

function CiStatusBadge({ status }: { status: unknown }) {
  const value = String(status || 'unknown');
  return (
    <span style={{
      display: 'inline-flex',
      alignItems: 'center',
      padding: '0.15rem 0.45rem',
      borderRadius: '999px',
      fontSize: '0.68rem',
      fontWeight: 600,
      background: `color-mix(in srgb, ${statusColor(value)} 14%, transparent)`,
      color: statusColor(value),
      whiteSpace: 'nowrap',
    }}>
      {ciStatusLabel(value)}
    </span>
  );
}

function CiMetric({ label, value, tone }: { label: string; value: unknown; tone?: string }) {
  return (
    <div style={{ padding: '0.55rem', background: 'var(--code-bg)', borderRadius: '6px', minWidth: 0 }}>
      <div style={{ fontSize: '0.68rem', color: 'var(--text-secondary)', marginBottom: '0.15rem' }}>{label}</div>
      <div style={{
        fontSize: '0.9rem',
        fontWeight: 700,
        color: tone || 'var(--text)',
        overflow: 'hidden',
        textOverflow: 'ellipsis',
        whiteSpace: 'nowrap',
      }} title={String(value ?? '-')}>
        {String(value ?? '-')}
      </div>
    </div>
  );
}

function CiProvidersPanel({ providers }: { providers: Array<Record<string, unknown>> }) {
  if (providers.length === 0) {
    return <div style={{ color: 'var(--text-secondary)', fontSize: '0.8rem' }}>No CI providers are configured yet.</div>;
  }
  return (
    <div style={{ display: 'grid', gap: '0.5rem' }}>
      {providers.map((provider) => {
        const missing = Array.isArray(provider.missing_requirements) ? provider.missing_requirements as string[] : [];
        const next = asRecord(provider.recommended_next_action);
        const setupStatus = String(provider.setup_status || (provider.configured ? 'ready' : 'not_configured'));
        return (
          <div key={String(provider.provider)} style={{
            padding: '0.65rem',
            background: 'var(--code-bg)',
            border: '1px solid var(--border)',
            borderRadius: '6px',
          }}>
            <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', marginBottom: '0.35rem' }}>
              <strong style={{ fontSize: '0.85rem' }}>{ciProviderName(provider.provider)}</strong>
              <CiStatusBadge status={setupStatus} />
              <span style={{ marginLeft: 'auto', fontSize: '0.72rem', color: 'var(--text-secondary)' }}>
                {String(provider.repository || provider.base_url || '')}
              </span>
            </div>
            {missing.length > 0 && (
              <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', lineHeight: 1.45 }}>
                Missing: {missing.map((item) => compactLabel(item)).join(', ')}
              </div>
            )}
            {Boolean(next.label) && (
              <div style={{ marginTop: '0.35rem', fontSize: '0.75rem', color: 'var(--primary)' }}>
                Next: {String(next.label)}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

function CiRunsPanel({ runs }: { runs: Array<Record<string, unknown>> }) {
  if (runs.length === 0) {
    return <div style={{ color: 'var(--text-secondary)', fontSize: '0.8rem' }}>No synced CI runs found.</div>;
  }
  return (
    <div style={{ border: '1px solid var(--border)', borderRadius: '8px', overflow: 'hidden', fontSize: '0.78rem' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        <thead>
          <tr style={{ background: 'var(--surface)', borderBottom: '1px solid var(--border)' }}>
            <th style={{ padding: '0.5rem', textAlign: 'left' }}>Run</th>
            <th style={{ padding: '0.5rem', textAlign: 'left' }}>Provider</th>
            <th style={{ padding: '0.5rem', textAlign: 'left' }}>Status</th>
            <th style={{ padding: '0.5rem', textAlign: 'left' }}>Tests</th>
          </tr>
        </thead>
        <tbody>
          {runs.slice(0, 8).map((run, index) => {
            const passed = run.passed_tests ?? run.passed;
            const failed = run.failed_tests ?? run.failed;
            return (
              <tr key={`${run.provider}-${run.id || run.external_pipeline_id || index}`} style={{ borderBottom: index < Math.min(runs.length, 8) - 1 ? '1px solid var(--border)' : 'none' }}>
                <td style={{ padding: '0.5rem', minWidth: 0 }}>
                  <div style={{ fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {String(run.name || run.external_pipeline_id || run.id || 'Run')}
                  </div>
                  <div style={{ color: 'var(--text-secondary)', fontSize: '0.7rem' }}>{String(run.ref || '-')}</div>
                </td>
                <td style={{ padding: '0.5rem' }}>{ciProviderName(run.provider)}</td>
                <td style={{ padding: '0.5rem' }}><CiStatusBadge status={run.status} /></td>
                <td style={{ padding: '0.5rem', color: 'var(--text-secondary)' }}>
                  {String(passed ?? '-')} / {String(failed ?? '-')}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function CiWorkflowsPanel({ workflows }: { workflows: Array<Record<string, unknown>> }) {
  if (workflows.length === 0) {
    return <div style={{ color: 'var(--text-secondary)', fontSize: '0.8rem' }}>No workflows found for the configured provider.</div>;
  }
  return (
    <div style={{ display: 'grid', gap: '0.45rem' }}>
      {workflows.slice(0, 8).map((workflow, index) => (
        <div key={`${workflow.provider}-${workflow.id || workflow.path || index}`} style={{
          display: 'grid',
          gridTemplateColumns: '1fr auto',
          gap: '0.5rem',
          padding: '0.6rem',
          background: 'var(--code-bg)',
          border: '1px solid var(--border)',
          borderRadius: '6px',
        }}>
          <div style={{ minWidth: 0 }}>
            <div style={{ fontWeight: 600, fontSize: '0.82rem', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {String(workflow.name || workflow.id || 'Workflow')}
            </div>
            <div style={{ color: 'var(--text-secondary)', fontSize: '0.7rem', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {String(workflow.path || workflow.id || '')}
            </div>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
            <span style={{ fontSize: '0.72rem', color: 'var(--text-secondary)' }}>{ciProviderName(workflow.provider)}</span>
            <CiStatusBadge status={workflow.state || 'active'} />
          </div>
        </div>
      ))}
    </div>
  );
}

function CiOverviewCard({ result, title = 'CI/CD Control' }: { result: unknown; title?: string }) {
  const data = asRecord(result);
  if (data.error) return <ToolError message={String(data.error)} />;
  const providers = ciArray(data.providers);
  const workflows = ciArray(data.workflows);
  const runs = ciArray(data.runs);
  const gates = ciArray(data.quality_gates);
  const openPullRequests = ciArray(data.open_pull_requests);
  const summary = asRecord(data.summary);
  return (
    <div style={{
      padding: '0.75rem',
      background: 'var(--surface)',
      border: '1px solid var(--border)',
      borderRadius: '8px',
      marginTop: '0.5rem',
      fontSize: '0.85rem',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.65rem' }}>
        <strong>{title}</strong>
        <CiStatusBadge status={data.status || 'ready'} />
        <Link href="/ci-cd" style={{ marginLeft: 'auto', color: 'var(--primary)', fontSize: '0.75rem' }}>
          Open CI/CD &rarr;
        </Link>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(95px, 1fr))', gap: '0.5rem', marginBottom: '0.75rem' }}>
        <CiMetric label="Providers" value={summary.providers ?? providers.length} />
        <CiMetric label="Workflows" value={summary.workflows ?? workflows.length} />
        <CiMetric label="Runs" value={summary.runs ?? runs.length} />
        <CiMetric label="Active" value={summary.active_runs ?? 0} tone="var(--warning)" />
        <CiMetric label="Failed" value={summary.failed_runs ?? 0} tone={Number(summary.failed_runs ?? 0) > 0 ? 'var(--danger)' : 'var(--text)'} />
        <CiMetric label="Open PRs" value={summary.open_pull_requests ?? openPullRequests.length} />
        <CiMetric label="Quality Gates" value={gates.length} />
      </div>
      <div style={{ display: 'grid', gap: '0.75rem' }}>
        <section>
          <div style={{ fontWeight: 600, fontSize: '0.78rem', marginBottom: '0.4rem' }}>Providers</div>
          <CiProvidersPanel providers={providers} />
        </section>
        {workflows.length > 0 && (
          <section>
            <div style={{ fontWeight: 600, fontSize: '0.78rem', marginBottom: '0.4rem' }}>Workflows</div>
            <CiWorkflowsPanel workflows={workflows} />
          </section>
        )}
        {runs.length > 0 && (
          <section>
            <div style={{ fontWeight: 600, fontSize: '0.78rem', marginBottom: '0.4rem' }}>Recent Runs</div>
            <CiRunsPanel runs={runs} />
          </section>
        )}
        {openPullRequests.length > 0 && (
          <section>
            <div style={{ fontWeight: 600, fontSize: '0.78rem', marginBottom: '0.4rem' }}>Open Pull Requests</div>
            <PrListPanel pulls={openPullRequests} />
          </section>
        )}
      </div>
    </div>
  );
}

const CiOverviewToolUI = makeAssistantToolUI({
  toolName: 'getCiControlOverview',
  render: ({ result }) => {
    if (!result) return <ToolLoading name="Loading CI/CD overview..." />;
    return <CiOverviewCard result={result} />;
  },
});

const CiProvidersToolUI = makeAssistantToolUI({
  toolName: 'listCiProviders',
  render: ({ result }) => {
    if (!result) return <ToolLoading name="Loading CI providers..." />;
    const providers = ciArray(result);
    if (asRecord(result).error) return <ToolError message={String(asRecord(result).error)} />;
    return (
      <div style={{ padding: '0.75rem', background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: '8px', marginTop: '0.5rem' }}>
        <div style={{ fontWeight: 600, fontSize: '0.85rem', marginBottom: '0.5rem' }}>CI Providers</div>
        <CiProvidersPanel providers={providers} />
      </div>
    );
  },
});

const CiWorkflowsToolUI = makeAssistantToolUI({
  toolName: 'listCiWorkflows',
  render: ({ result }) => {
    if (!result) return <ToolLoading name="Loading CI workflows..." />;
    if (asRecord(result).error) return <ToolError message={String(asRecord(result).error)} />;
    return (
      <div style={{ padding: '0.75rem', background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: '8px', marginTop: '0.5rem' }}>
        <div style={{ fontWeight: 600, fontSize: '0.85rem', marginBottom: '0.5rem' }}>CI Workflows</div>
        <CiWorkflowsPanel workflows={ciArray(result)} />
      </div>
    );
  },
});

const CiRunsToolUI = makeAssistantToolUI({
  toolName: 'listCiRuns',
  render: ({ result }) => {
    if (!result) return <ToolLoading name="Loading CI runs..." />;
    if (asRecord(result).error) return <ToolError message={String(asRecord(result).error)} />;
    return (
      <div style={{ padding: '0.75rem', background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: '8px', marginTop: '0.5rem' }}>
        <div style={{ fontWeight: 600, fontSize: '0.85rem', marginBottom: '0.5rem' }}>CI Runs</div>
        <CiRunsPanel runs={ciArray(result)} />
      </div>
    );
  },
});

const CiRunDetailToolUI = makeAssistantToolUI({
  toolName: 'getCiRunDetail',
  render: ({ result }) => {
    if (!result) return <ToolLoading name="Loading CI run detail..." />;
    const data = asRecord(result);
    if (data.error) return <ToolError message={String(data.error)} />;
    const run = asRecord(data.run);
    const jobs = ciArray(data.jobs);
    const artifacts = ciArray(data.artifacts);
    return (
      <div style={{ padding: '0.75rem', background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: '8px', marginTop: '0.5rem', fontSize: '0.85rem' }}>
        <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', marginBottom: '0.65rem' }}>
          <strong>{String(run.name || run.external_pipeline_id || run.id || 'CI run')}</strong>
          <CiStatusBadge status={run.status} />
          {Boolean(run.external_url) && <a href={String(run.external_url)} target="_blank" rel="noreferrer" style={{ marginLeft: 'auto', color: 'var(--primary)', fontSize: '0.75rem' }}>Provider &rarr;</a>}
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(105px, 1fr))', gap: '0.5rem', marginBottom: '0.75rem' }}>
          <CiMetric label="Provider" value={ciProviderName(run.provider)} />
          <CiMetric label="Ref" value={run.ref || '-'} />
          <CiMetric label="Passed" value={run.passed_tests ?? '-'} tone="var(--success)" />
          <CiMetric label="Failed" value={run.failed_tests ?? '-'} tone={Number(run.failed_tests ?? 0) > 0 ? 'var(--danger)' : 'var(--text)'} />
          <CiMetric label="Jobs" value={jobs.length} />
          <CiMetric label="Artifacts" value={artifacts.length} />
        </div>
        {jobs.length > 0 && <CiRunsPanel runs={jobs.map((job) => ({ ...job, provider: run.provider, ref: job.stage || job.name }))} />}
      </div>
    );
  },
});

const CiRunLogsToolUI = makeAssistantToolUI({
  toolName: 'getCiRunLogs',
  render: ({ result }) => {
    if (!result) return <ToolLoading name="Loading CI logs..." />;
    const data = asRecord(result);
    if (data.error) return <ToolError message={String(data.error)} />;
    if (data.type === 'archive_url' && data.url) {
      return (
        <div style={{ padding: '0.75rem', background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: '8px', marginTop: '0.5rem', fontSize: '0.85rem' }}>
          <strong>CI Logs</strong>
          <div style={{ marginTop: '0.35rem', color: 'var(--text-secondary)' }}>GitHub returned a downloadable log archive.</div>
          <a href={String(data.url)} target="_blank" rel="noreferrer" style={{ display: 'inline-flex', marginTop: '0.5rem', color: 'var(--primary)', fontSize: '0.8rem' }}>Open log archive &rarr;</a>
        </div>
      );
    }
    const content = String(data.content || '');
    return (
      <div style={{ marginTop: '0.5rem', border: '1px solid var(--border)', borderRadius: '8px', overflow: 'hidden' }}>
        <div style={{ padding: '0.5rem 0.75rem', background: 'var(--surface)', borderBottom: '1px solid var(--border)', fontWeight: 600, fontSize: '0.8rem' }}>CI Logs</div>
        <pre style={{ margin: 0, padding: '0.75rem', maxHeight: '280px', overflow: 'auto', background: 'var(--code-bg)', color: 'var(--text)', fontSize: '0.75rem', whiteSpace: 'pre-wrap' }}>
          {content || 'No log content returned.'}
        </pre>
      </div>
    );
  },
});

const CiWorkflowChangeToolUI = makeAssistantToolUI({
  toolName: 'generateCiWorkflowChange',
  render: ({ result }) => {
    if (!result) return <ToolLoading name="Generating workflow change..." />;
    const data = asRecord(result);
    if (data.error) return <ToolError message={String(data.error)} />;
    const errors = Array.isArray(data.validation_errors) ? data.validation_errors as unknown[] : [];
    const warnings = Array.isArray(data.validation_warnings) ? data.validation_warnings as unknown[] : [];
    return (
      <div style={{ padding: '0.75rem', background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: '8px', marginTop: '0.5rem', fontSize: '0.85rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.5rem' }}>
          <strong>{String(data.workflow_name || 'Generated workflow')}</strong>
          <CiStatusBadge status={errors.length ? 'blocked' : data.status || 'draft'} />
        </div>
        <div style={{ color: 'var(--text-secondary)', fontSize: '0.78rem', marginBottom: '0.5rem' }}>
          {String(data.workflow_path || '')}
        </div>
        {errors.length > 0 && <ToolError message={`Validation errors: ${errors.map(String).join('; ')}`} />}
        {warnings.length > 0 && (
          <div style={{ padding: '0.55rem', background: 'rgba(245, 158, 11, 0.08)', border: '1px solid rgba(245, 158, 11, 0.22)', borderRadius: '6px', color: 'var(--text-secondary)', fontSize: '0.78rem', marginBottom: '0.5rem' }}>
            Warnings: {warnings.map(String).join('; ')}
          </div>
        )}
        {Boolean(data.pull_request_url) && <a href={String(data.pull_request_url)} target="_blank" rel="noreferrer" style={{ color: 'var(--primary)', fontSize: '0.78rem' }}>Open pull request &rarr;</a>}
        {Boolean(data.generated_yaml) && (
          <details style={{ marginTop: '0.5rem' }}>
            <summary style={{ cursor: 'pointer', color: 'var(--text-secondary)', fontSize: '0.78rem' }}>Preview workflow YAML</summary>
            <pre style={{ marginTop: '0.45rem', padding: '0.65rem', maxHeight: '260px', overflow: 'auto', background: 'var(--code-bg)', borderRadius: '6px', fontSize: '0.72rem', whiteSpace: 'pre-wrap' }}>
              {String(data.generated_yaml)}
            </pre>
          </details>
        )}
      </div>
    );
  },
});

function PrListPanel({ pulls }: { pulls: Array<Record<string, unknown>> }) {
  if (pulls.length === 0) {
    return <div style={{ color: 'var(--text-secondary)', fontSize: '0.8rem' }}>No pull requests found.</div>;
  }
  return (
    <div style={{ display: 'grid', gap: '0.5rem' }}>
      {pulls.slice(0, 10).map((pr) => (
        <div key={String(pr.number)} style={{
          padding: '0.65rem',
          background: 'var(--code-bg)',
          border: '1px solid var(--border)',
          borderRadius: '6px',
          fontSize: '0.8rem',
        }}>
          <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', marginBottom: '0.25rem' }}>
            <strong>#{String(pr.number || '?')}</strong>
            <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{String(pr.title || 'Untitled PR')}</span>
            <CiStatusBadge status={pr.draft ? 'draft' : pr.state || 'open'} />
          </div>
          <div style={{ color: 'var(--text-secondary)', fontSize: '0.72rem' }}>
            {String(pr.head_ref || '-')} &rarr; {String(pr.base_ref || '-')}
            {pr.user ? ` · ${String(pr.user)}` : ''}
          </div>
        </div>
      ))}
    </div>
  );
}

function SelectedTestsPanel({ tests }: { tests: Array<Record<string, unknown>> }) {
  if (tests.length === 0) {
    return <div style={{ color: 'var(--text-secondary)', fontSize: '0.8rem' }}>No selected generated tests.</div>;
  }
  return (
    <div style={{ display: 'grid', gap: '0.45rem' }}>
      {tests.slice(0, 12).map((test, index) => (
        <div key={`${test.spec_name || index}`} style={{
          padding: '0.6rem',
          background: 'var(--code-bg)',
          border: '1px solid var(--border)',
          borderRadius: '6px',
          fontSize: '0.78rem',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.45rem', marginBottom: '0.25rem' }}>
            <strong style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {String(test.spec_name || test.test_path || 'Selected test')}
            </strong>
            <CiStatusBadge status={test.risk_level || 'selected'} />
            <span style={{ marginLeft: 'auto', color: 'var(--text-secondary)', fontSize: '0.7rem' }}>
              {String(test.confidence || '')}
            </span>
          </div>
          <div style={{ color: 'var(--text-secondary)', lineHeight: 1.4 }}>
            {String(test.reason || 'Selected by PR impact analysis')}
          </div>
        </div>
      ))}
    </div>
  );
}

function PrAnalysisCard({ result, title = 'PR Advisor Analysis' }: { result: unknown; title?: string }) {
  const data = asRecord(result);
  if (data.error) return <ToolError message={String(data.error)} />;
  const selectedTests = ciArray(data.selected_tests);
  return (
    <div style={{ padding: '0.75rem', background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: '8px', marginTop: '0.5rem', fontSize: '0.85rem' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.65rem' }}>
        <strong>{title}</strong>
        {Boolean(data.pr_number) && <span style={{ color: 'var(--text-secondary)', fontSize: '0.78rem' }}>PR #{String(data.pr_number)}</span>}
        <CiStatusBadge status={data.risk_level || data.status || 'analyzed'} />
        <Link href="/pr-advisor" style={{ marginLeft: 'auto', color: 'var(--primary)', fontSize: '0.75rem' }}>
          Open PR Advisor &rarr;
        </Link>
      </div>
      {Boolean(data.summary) && (
        <div style={{ color: 'var(--text-secondary)', fontSize: '0.8rem', lineHeight: 1.45, marginBottom: '0.65rem' }}>
          {String(data.summary)}
        </div>
      )}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(105px, 1fr))', gap: '0.5rem', marginBottom: '0.75rem' }}>
        <CiMetric label="Changed Files" value={data.changed_files_count ?? '-'} />
        <CiMetric label="Selected" value={`${String(data.selected_tests_count ?? selectedTests.length)}/${String(data.total_candidate_tests ?? '-')}`} />
        <CiMetric label="Confidence" value={data.confidence || '-'} />
        <CiMetric label="Saved" value={data.saved_tests_count ?? '-'} />
      </div>
      <div style={{ fontWeight: 600, fontSize: '0.78rem', marginBottom: '0.4rem' }}>Selected Generated Tests</div>
      <SelectedTestsPanel tests={selectedTests} />
    </div>
  );
}

const OpenPullRequestsToolUI = makeAssistantToolUI({
  toolName: 'listOpenPullRequests',
  render: ({ result }) => {
    if (!result) return <ToolLoading name="Loading open pull requests..." />;
    if (asRecord(result).error) return <ToolError message={String(asRecord(result).error)} />;
    return (
      <div style={{ padding: '0.75rem', background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: '8px', marginTop: '0.5rem' }}>
        <div style={{ fontWeight: 600, fontSize: '0.85rem', marginBottom: '0.5rem' }}>Pull Requests</div>
        <PrListPanel pulls={ciArray(result)} />
      </div>
    );
  },
});

const PrAdvisorAnalysesToolUI = makeAssistantToolUI({
  toolName: 'listPrAdvisorAnalyses',
  render: ({ result }) => {
    if (!result) return <ToolLoading name="Loading PR analyses..." />;
    if (asRecord(result).error) return <ToolError message={String(asRecord(result).error)} />;
    const analyses = ciArray(result);
    return (
      <div style={{ padding: '0.75rem', background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: '8px', marginTop: '0.5rem' }}>
        <div style={{ fontWeight: 600, fontSize: '0.85rem', marginBottom: '0.5rem' }}>Recent PR Analyses</div>
        {analyses.length === 0 ? (
          <div style={{ color: 'var(--text-secondary)', fontSize: '0.8rem' }}>No PR Advisor analyses yet.</div>
        ) : (
          <div style={{ display: 'grid', gap: '0.45rem' }}>
            {analyses.slice(0, 8).map((analysis) => (
              <div key={String(analysis.id)} style={{ padding: '0.6rem', background: 'var(--code-bg)', border: '1px solid var(--border)', borderRadius: '6px', fontSize: '0.78rem' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.45rem' }}>
                  <strong>PR #{String(analysis.pr_number || '?')}</strong>
                  <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{String(analysis.title || analysis.summary || '')}</span>
                  <CiStatusBadge status={analysis.risk_level || 'analyzed'} />
                </div>
                <div style={{ color: 'var(--text-secondary)', marginTop: '0.2rem' }}>
                  Selected {String(analysis.selected_tests_count ?? 0)} of {String(analysis.total_candidate_tests ?? '-')} generated tests
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    );
  },
});

const PrAdvisorAnalysisToolUI = makeAssistantToolUI({
  toolName: 'getPrAdvisorAnalysis',
  render: ({ result }) => {
    if (!result) return <ToolLoading name="Loading PR analysis..." />;
    return <PrAnalysisCard result={result} />;
  },
});

// ===== Generic Tool UI (Wildcard - must be registered last) =====

const toolPageMap: Record<string, string> = {
  getWorkflowCapabilities: '/assistant',
  getTestRuns: '/runs',
  getRecentTestResults: '/runs',
  getRecentRuns: '/runs',
  getTestRunDetails: '/runs',
  pollRunStatus: '/runs',
  runTestSpec: '/runs',
  getSpecList: '/specs',
  listTestSpecs: '/specs',
  getSpecContent: '/specs',
  getSpecGeneratedCode: '/specs',
  createTestSpec: '/specs',
  updateTestSpec: '/specs',
  runRegressionBatch: '/regression',
  startDiscoveryExploration: '/exploration',
  listSpecTemplates: '/specs',
  getExplorationSessions: '/exploration',
  listExplorations: '/exploration',
  getExplorationDetails: '/exploration',
  startExplorerAgent: '/exploration',
  listAgentRuns: '/agents',
  getAgentRunReport: '/agents',
  searchAgentReports: '/agents',
  startAdhocCustomAgent: '/agents',
  createCustomAgentDefinition: '/agents',
  startCustomAgentFromReport: '/agents',
  createTestSpecFromAgentReport: '/specs',
  getRequirements: '/requirements',
  generateRequirements: '/requirements',
  getRequirementDetails: '/requirements',
  getRequirementStats: '/requirements',
  getRequirementHealth: '/requirements',
  listRequirementCategories: '/requirements',
  findDuplicateRequirements: '/requirements',
  checkRequirementDuplicate: '/requirements',
  getRequirementsGenerateJob: '/requirements',
  getBulkSpecGenerationJob: '/requirements',
  getRequirementSpecStatus: '/requirements',
  createRequirement: '/requirements',
  bulkCreateRequirements: '/requirements',
  updateRequirement: '/requirements',
  deleteRequirement: '/requirements',
  generateSpecFromRequirement: '/requirements',
  bulkGenerateRequirementSpecs: '/requirements',
  mergeRequirements: '/requirements',
  getRtmCoverage: '/rtm',
  getRTMSummary: '/rtm',
  getRTMMatrix: '/rtm',
  getRTMGenerateJob: '/rtm',
  listRTMSnapshots: '/rtm',
  getRTMSnapshotDetail: '/rtm',
  getRequirementTests: '/rtm',
  getTestRequirements: '/rtm',
  generateRTM: '/rtm',
  createRTMSnapshot: '/rtm',
  createRTMEntry: '/rtm',
  deleteRTMEntry: '/rtm',
  getDashboardStats: '/',
  getBrowserPoolStatus: '/',
  getSecurityFindings: '/security-testing',
  getSecurityCapabilities: '/security-testing',
  getSecurityTargets: '/security-testing',
  listSecuritySpecs: '/security-testing',
  getSecuritySpec: '/security-testing',
  getSecurityJobStatus: '/security-testing',
  listSecurityFindings: '/security-testing',
  getSecurityRunFindings: '/security-testing',
  getPassRateTrends: '/analytics',
  getFlakeDetection: '/analytics',
  getFailureClassification: '/analytics',
  getSpecPerformance: '/analytics',
  getCoverageOverview: '/analytics',
  quarantineSpec: '/analytics',
  unquarantineSpec: '/analytics',
  getRunLogs: '/runs',
  healFailedRun: '/runs',
  retryFailedRun: '/runs',
  stopRun: '/runs',
  stopAllJobs: '/runs',
  clearQueue: '/runs',
  startExploration: '/exploration',
  stopExploration: '/exploration',
  getLlmProviders: '/llm-testing',
  getLlmTestRuns: '/llm-testing',
  getLlmAnalytics: '/llm-testing',
  listSchedules: '/schedules',
  triggerScheduleNow: '/schedules',
  getApiTestRuns: '/api-testing',
  listApiSpecs: '/api-testing',
  getApiSpec: '/api-testing',
  getApiJobStatus: '/api-testing',
  getDatabaseTestSummary: '/database-testing',
  listDatabaseConnections: '/database-testing',
  listDatabaseSpecs: '/database-testing',
  getDatabaseJobStatus: '/database-testing',
  saveGeneratedDatabaseSpec: '/database-testing',
  // Regression tools
  getRegressionBatches: '/regression',
  compareBatches: '/regression',
  getBatchTrend: '/regression',
  getBatchErrorSummary: '/regression',
  rerunFailedTests: '/regression',
  getRegressionFlakyTests: '/regression',
  // Load testing tools
  compareLoadTestRuns: '/load-testing',
  getLoadTestResults: '/load-testing',
  listLoadSpecs: '/load-testing',
  getLoadSpec: '/load-testing',
  listLoadScripts: '/load-testing',
  getLoadScript: '/load-testing',
  listLoadTestJobs: '/load-testing',
  getLoadTestJobStatus: '/load-testing',
  getLoadTestJobLogs: '/load-testing',
  getLatestLoadRunsBySpec: '/load-testing',
  getLoadTestRunDetails: '/load-testing',
  getLoadTestTimeseries: '/load-testing',
  getLoadTestingStatus: '/load-testing',
  getLoadTestDashboard: '/load-testing',
  getLoadTestTrends: '/load-testing',
  analyzeLoadTestRun: '/load-testing',
  stopLoadTestRun: '/load-testing',
  forceUnlockLoadTesting: '/load-testing',
  createLoadSpec: '/load-testing',
  updateLoadSpec: '/load-testing',
  deleteLoadSpec: '/load-testing',
  generateLoadScript: '/load-testing',
  runLoadTest: '/load-testing',
  runLoadTestFromSpec: '/load-testing',
  getLoadTestSystemLimits: '/load-testing',
  // Security testing tools
  getSecurityRunDetails: '/security-testing',
  triggerSecurityScan: '/security-testing',
  runSecurityScan: '/security-testing',
  stopSecurityScan: '/security-testing',
  createSecuritySpec: '/security-testing',
  updateSecuritySpec: '/security-testing',
  deleteSecuritySpec: '/security-testing',
  analyzeSecurityRun: '/security-testing',
  triageSecurityFinding: '/security-testing',
  compareSecurityScans: '/security-testing',
  generateSecuritySpecFromExploration: '/security-testing',
  // RTM tools
  getRTMGaps: '/rtm',
  exportRTM: '/rtm',
  getRTMTrend: '/rtm',
  // LLM testing tools
  getLlmComparisonMatrix: '/llm-testing',
  getLlmGoldenDashboard: '/llm-testing',
  getLlmCostTracking: '/llm-testing',
  suggestLlmSpecImprovements: '/llm-testing',
  // Database testing tools
  getDbSchemaAnalysis: '/database-testing',
  getDbChecks: '/database-testing',
  suggestDbFixes: '/database-testing',
  generateDatabaseSpec: '/database-testing',
  createApiSpec: '/api-testing',
  createAndGenerateApiTest: '/api-testing',
  importOpenApiSpec: '/api-testing',
  updateApiSpec: '/api-testing',
  deleteApiSpec: '/api-testing',
  generateApiTest: '/api-testing',
  runApiTest: '/api-testing',
  runApiTestDirect: '/api-testing',
  generateApiEdgeCases: '/api-testing',
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
  pauseAutoPilot: '/autopilot',
  resumeAutoPilot: '/autopilot',
  answerAutoPilotQuestion: '/autopilot',
  stopAutoPilotTestTask: '/autopilot',
  cancelAutoPilot: '/autopilot',
  listAutoPilotSessions: '/autopilot',
  // Project tools
  listProjects: '/projects',
  getProject: '/projects',
  listProjectMembers: '/projects',
  listProjectCredentials: '/projects',
  createProject: '/projects',
  updateProject: '/projects',
  deleteProject: '/projects',
  assignSpecToProject: '/projects',
  bulkAssignSpecsToProject: '/projects',
  setProjectCredential: '/projects',
  removeProjectCredential: '/projects',
  // Recording tools
  listRecordings: '/recordings',
  getRecording: '/recordings',
  getRecordingCode: '/recordings',
  startRecording: '/recordings',
  stopRecording: '/recordings',
  importRecording: '/recordings',
  // Settings tools
  getAssistantSettings: '/settings',
  testAssistantSettingsConnection: '/settings',
  updateAssistantSettings: '/settings',
  // Extended schedule tools
  getSchedule: '/schedules',
  validateCronExpression: '/schedules',
  listScheduleExecutions: '/schedules',
  listProjectScheduleExecutions: '/schedules',
  getNextScheduleRuns: '/schedules',
  createSchedule: '/schedules',
  updateSchedule: '/schedules',
  deleteSchedule: '/schedules',
  toggleSchedule: '/schedules',
  // PRD tools
  listPrdProjects: '/prd',
  listPrdFeatures: '/prd',
  listPrdGenerations: '/prd',
  getPrdGenerationStatus: '/prd',
  getPrdQueueStatus: '/prd',
  generatePrdPlan: '/prd',
  stopPrdGeneration: '/prd',
  generatePrdTest: '/prd',
  healPrdTest: '/prd',
  runPrdTest: '/prd',
  // CI/CD and PR Advisor tools
  getCiControlOverview: '/ci-cd',
  listOpenPullRequests: '/pr-advisor',
  listCiProviders: '/ci-cd',
  listCiWorkflows: '/ci-cd',
  listCiRuns: '/ci-cd',
  getCiRunDetail: '/ci-cd',
  getCiRunLogs: '/ci-cd',
  listCiAuditEvents: '/ci-cd',
  listGeneratedCiTests: '/ci-cd',
  listCiTestSubsets: '/ci-cd',
  getCiTestSubset: '/ci-cd',
  previewCiTestSubset: '/ci-cd',
  syncCiRuns: '/ci-cd',
  dispatchCiWorkflow: '/ci-cd',
  cancelCiRun: '/ci-cd',
  rerunCiRun: '/ci-cd',
  generateCiWorkflowChange: '/ci-cd',
  openCiWorkflowPullRequest: '/ci-cd',
  updateCiProviderDefaults: '/ci-cd',
  createCiTestSubset: '/ci-cd',
  updateCiTestSubset: '/ci-cd',
  deleteCiTestSubset: '/ci-cd',
  openCiTestSubsetPullRequest: '/ci-cd',
  dispatchCiTestSubset: '/ci-cd',
  analyzePullRequestTests: '/pr-advisor',
  listPrAdvisorAnalyses: '/pr-advisor',
  getPrAdvisorAnalysis: '/pr-advisor',
  runPrAdvisorRecommendedTests: '/pr-advisor',
  // Chat control and coverage planning
  getChatControlAudit: '/assistant',
  planUiTestCoverage: '/analytics',
  analyzeUiTestRunArtifacts: '/runs',
  executeUiTestCoveragePlan: '/runs',
  listWorkflows: '/workflow',
  listWorkflowCatalog: '/workflow',
  getWorkflow: '/workflow',
  createWorkflow: '/workflow',
  updateWorkflow: '/workflow',
  duplicateWorkflow: '/workflow',
  archiveWorkflow: '/workflow',
  startWorkflow: '/workflow',
  startWorkflowFromStep: '/workflow',
  getWorkflowStatus: '/workflow',
  retryWorkflowFailedStep: '/workflow',
  pauseWorkflowRun: '/workflow',
  resumeWorkflowRun: '/workflow',
  cancelWorkflowRun: '/workflow',
  // Extended spec management
  listSpecFolders: '/specs',
  listAutomatedSpecs: '/specs',
  getSpecMetadata: '/specs',
  getSpecInfo: '/specs',
  updateGeneratedCode: '/specs',
  updateSpecMetadata: '/specs',
  moveSpec: '/specs',
  renameSpec: '/specs',
  splitSpec: '/specs',
  createSpecFolder: '/specs',
  // Extended exploration and Explorer Agent control
  getExplorationHealth: '/exploration',
  getExplorationQueueStatus: '/exploration',
  getExplorationArtifacts: '/exploration',
  getExplorationResults: '/exploration',
  getExplorationFlows: '/exploration',
  getExplorationApis: '/exploration',
  getExplorationIssues: '/exploration',
  getAgentQueueStatus: '/agents',
  listAgentToolCatalog: '/agents',
  listAgentDefinitions: '/agents',
  getAgentDefinition: '/agents',
  getAgentRun: '/agents',
  getExplorerGeneratedSpecs: '/exploration',
  getExplorerFlowDetails: '/exploration',
  getExplorerFlowSpecJob: '/exploration',
  listExplorerSessions: '/exploration',
  synthesizeExplorerSpecs: '/exploration',
  analyzeExplorerPrerequisites: '/exploration',
  generateExplorerFlowSpec: '/exploration',
  generateExplorerFlowTest: '/exploration',
  updateExplorerFlow: '/exploration',
  deleteExplorerFlow: '/exploration',
  saveExplorerSession: '/exploration',
  deleteExplorerSession: '/exploration',
  generateApiSpecsFromExploration: '/api-testing',
  generateApiTestsFromExploration: '/api-testing',
  // Extended regression control
  getRegressionBatchDetail: '/regression',
  getSpecHistory: '/regression',
  exportRegressionBatch: '/regression',
  refreshRegressionBatch: '/regression',
  cancelRegressionBatch: '/regression',
  renameRegressionBatch: '/regression',
  deleteRegressionBatch: '/regression',
  // Quality gates and external integrations
  getQualityGateConfig: '/ci-cd',
  listPrQualityGates: '/ci-cd',
  getPrQualityGate: '/ci-cd',
  getPrQualityGateStatus: '/ci-cd',
  startPrQualityGate: '/ci-cd',
  getJiraConfig: '/settings',
  testJiraConnection: '/settings',
  getJiraBugReportJob: '/runs',
  listJiraIssues: '/runs',
  getJiraIssueForRun: '/runs',
  generateJiraBugReport: '/runs',
  createJiraIssue: '/runs',
  getTestRailConfig: '/settings',
  testTestRailConnection: '/settings',
  listTestRailMappings: '/settings',
  getTestRailSyncPreview: '/regression',
  pushTestRailCases: '/settings',
  syncTestRailResults: '/regression',
  deleteTestRailMapping: '/settings',
};

type AgentToolOption = {
  id: string;
  label: string;
  description?: string;
  category: string;
  risk?: string;
};

const DEFAULT_CUSTOM_AGENT_TOOL_IDS = [
  'browser_navigate',
  'browser_snapshot',
  'browser_click',
  'browser_type',
  'browser_select',
  'browser_press_key',
  'browser_hover',
  'browser_network',
  'browser_console',
  'browser_screenshot',
  'browser_wait',
  'browser_navigate_back',
  'browser_close',
];

function normalizeCustomAgentArgs(args: Record<string, unknown>): Record<string, unknown> {
  return {
    ...args,
    agentName: typeof args.agentName === 'string' ? args.agentName : 'Custom QA Agent',
    description: typeof args.description === 'string' ? args.description : '',
    url: typeof args.url === 'string' ? args.url : '',
    systemPrompt: typeof args.systemPrompt === 'string' ? args.systemPrompt : '',
    prompt: typeof args.prompt === 'string' ? args.prompt : '',
    timeoutSeconds: typeof args.timeoutSeconds === 'number' ? args.timeoutSeconds : Number(args.timeoutSeconds || 1800),
    toolIds: Array.isArray(args.toolIds) && args.toolIds.every((toolId) => typeof toolId === 'string')
      ? args.toolIds
      : DEFAULT_CUSTOM_AGENT_TOOL_IDS,
  };
}

function normalizeWorkflowArgs(args: Record<string, unknown>): Record<string, unknown> {
  const definition = isRecord(args.definition) ? args.definition : {};
  const steps = Array.isArray(args.steps)
    ? args.steps
    : Array.isArray(definition.steps)
      ? definition.steps
      : [];
  return {
    ...args,
    name: typeof args.name === 'string' ? args.name : 'Chat-created workflow',
    description: typeof args.description === 'string' ? args.description : '',
    steps,
  };
}

function groupedAgentTools(tools: AgentToolOption[]) {
  return tools.reduce<Record<string, AgentToolOption[]>>((acc, tool) => {
    const category = tool.category || 'Other';
    acc[category] = acc[category] || [];
    acc[category].push(tool);
    return acc;
  }, {});
}

const approvalInputStyle: CSSProperties = {
  width: '100%',
  padding: '0.45rem 0.5rem',
  borderRadius: '6px',
  border: '1px solid var(--input-border)',
  background: 'var(--input-bg)',
  color: 'var(--text)',
  fontSize: '0.78rem',
};

const approvalTextareaStyle: CSSProperties = {
  ...approvalInputStyle,
  resize: 'vertical',
  lineHeight: 1.45,
};

function CustomAgentApprovalEditor({
  args,
  setArgs,
  tools,
  toolsLoading,
  toolsExpanded,
  setToolsExpanded,
  disabled,
}: {
  args: Record<string, unknown>;
  setArgs: Dispatch<SetStateAction<Record<string, unknown>>>;
  tools: AgentToolOption[];
  toolsLoading: boolean;
  toolsExpanded: boolean;
  setToolsExpanded: (value: boolean) => void;
  disabled: boolean;
}) {
  const selectedToolIds = Array.isArray(args.toolIds) ? args.toolIds.filter((id): id is string => typeof id === 'string') : [];
  const toolGroups = groupedAgentTools(tools);

  const updateField = (key: string, value: unknown) => {
    setArgs((prev) => ({ ...prev, [key]: value }));
  };

  const toggleTool = (toolId: string) => {
    setArgs((prev) => {
      const current = Array.isArray(prev.toolIds) ? prev.toolIds.filter((id): id is string => typeof id === 'string') : [];
      return {
        ...prev,
        toolIds: current.includes(toolId) ? current.filter((id) => id !== toolId) : [...current, toolId],
      };
    });
  };

  const toggleCategory = (categoryTools: AgentToolOption[]) => {
    const ids = categoryTools.map((tool) => tool.id);
    const allSelected = ids.every((id) => selectedToolIds.includes(id));
    setArgs((prev) => {
      const current = Array.isArray(prev.toolIds) ? prev.toolIds.filter((id): id is string => typeof id === 'string') : [];
      return {
        ...prev,
        toolIds: allSelected
          ? current.filter((id) => !ids.includes(id))
          : Array.from(new Set([...current, ...ids])),
      };
    });
  };

  return (
    <div style={{
      padding: '0.65rem',
      background: 'var(--code-bg)',
      borderRadius: '6px',
      marginBottom: '0.65rem',
      fontSize: '0.75rem',
    }}>
      <div style={{ display: 'grid', gap: '0.55rem' }}>
        <label style={{ display: 'grid', gap: '0.25rem' }}>
          <span style={{ color: 'var(--text-secondary)', fontWeight: 600 }}>Agent name</span>
          <input
            value={String(args.agentName || '')}
            onChange={(e) => updateField('agentName', e.target.value)}
            disabled={disabled}
            style={approvalInputStyle}
          />
        </label>

        <label style={{ display: 'grid', gap: '0.25rem' }}>
          <span style={{ color: 'var(--text-secondary)', fontWeight: 600 }}>Target URL</span>
          <input
            value={String(args.url || '')}
            onChange={(e) => updateField('url', e.target.value)}
            disabled={disabled}
            style={approvalInputStyle}
          />
        </label>

        <label style={{ display: 'grid', gap: '0.25rem' }}>
          <span style={{ color: 'var(--text-secondary)', fontWeight: 600 }}>Task prompt</span>
          <textarea
            value={String(args.prompt || '')}
            onChange={(e) => updateField('prompt', e.target.value)}
            disabled={disabled}
            rows={8}
            style={approvalTextareaStyle}
          />
        </label>

        <label style={{ display: 'grid', gap: '0.25rem' }}>
          <span style={{ color: 'var(--text-secondary)', fontWeight: 600 }}>System prompt</span>
          <textarea
            value={String(args.systemPrompt || '')}
            onChange={(e) => updateField('systemPrompt', e.target.value)}
            disabled={disabled}
            rows={5}
            style={approvalTextareaStyle}
          />
        </label>

        <label style={{ display: 'grid', gap: '0.25rem' }}>
          <span style={{ color: 'var(--text-secondary)', fontWeight: 600 }}>Timeout seconds</span>
          <input
            type="number"
            min={60}
            max={7200}
            value={Number(args.timeoutSeconds || 1800)}
            onChange={(e) => updateField('timeoutSeconds', Number(e.target.value || 1800))}
            disabled={disabled}
            style={approvalInputStyle}
          />
        </label>

        <div>
          <button
            type="button"
            onClick={() => setToolsExpanded(!toolsExpanded)}
            disabled={disabled}
            style={{
              width: '100%',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              gap: '0.5rem',
              border: '1px solid var(--border)',
              borderRadius: '6px',
              padding: '0.45rem 0.55rem',
              background: 'var(--surface-hover)',
              color: 'var(--text)',
              cursor: disabled ? 'not-allowed' : 'pointer',
              fontSize: '0.75rem',
              fontWeight: 600,
            }}
          >
            <span>Tools selected: {selectedToolIds.length}</span>
            <ChevronDown size={14} style={{ transform: toolsExpanded ? 'rotate(180deg)' : 'rotate(0deg)' }} />
          </button>

          {toolsExpanded && (
            <div style={{
              maxHeight: '280px',
              overflowY: 'auto',
              border: '1px solid var(--border)',
              borderRadius: '6px',
              padding: '0.5rem',
              marginTop: '0.45rem',
              background: 'var(--surface)',
            }}>
              {toolsLoading && <div style={{ color: 'var(--text-secondary)' }}>Loading tools...</div>}
              {!toolsLoading && tools.length === 0 && (
                <div style={{ color: 'var(--text-secondary)' }}>Tool catalog unavailable. Default selected tool IDs will be used.</div>
              )}
              {Object.entries(toolGroups).map(([category, categoryTools]) => (
                <div key={category} style={{ marginBottom: '0.7rem' }}>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '0.5rem', marginBottom: '0.3rem' }}>
                    <span style={{ color: 'var(--text-secondary)', fontWeight: 700, textTransform: 'uppercase', fontSize: '0.68rem' }}>
                      {category} ({categoryTools.length})
                    </span>
                    <button
                      type="button"
                      onClick={() => toggleCategory(categoryTools)}
                      disabled={disabled}
                      style={{ border: 'none', background: 'transparent', color: 'var(--primary)', cursor: disabled ? 'not-allowed' : 'pointer', fontSize: '0.68rem' }}
                    >
                      {categoryTools.every((tool) => selectedToolIds.includes(tool.id)) ? 'Clear' : 'Select all'}
                    </button>
                  </div>
                  {categoryTools.map((tool) => (
                    <label key={tool.id} style={{ display: 'flex', gap: '0.45rem', alignItems: 'flex-start', marginBottom: '0.38rem', cursor: disabled ? 'not-allowed' : 'pointer' }}>
                      <input
                        type="checkbox"
                        checked={selectedToolIds.includes(tool.id)}
                        onChange={() => toggleTool(tool.id)}
                        disabled={disabled}
                        style={{ marginTop: '0.1rem' }}
                      />
                      <span style={{ flex: 1 }}>
                        <span style={{ fontWeight: 600 }}>{tool.label}</span>
                        <span style={{
                          marginLeft: '0.35rem',
                          color: tool.risk === 'high' || tool.risk === 'destructive' ? 'var(--danger)' : tool.risk === 'medium' ? 'var(--warning)' : 'var(--success)',
                          fontSize: '0.68rem',
                        }}>
                          {tool.risk || 'low'}
                        </span>
                        {tool.description && <span style={{ display: 'block', color: 'var(--text-secondary)', lineHeight: 1.35 }}>{tool.description}</span>}
                      </span>
                    </label>
                  ))}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function workflowStepRows(steps: unknown[]): Array<{ key: string; type: string; label: string }> {
  return steps
    .filter(isRecord)
    .map((step, index) => ({
      key: typeof step.key === 'string' && step.key ? step.key : `step_${index + 1}`,
      type: typeof step.type === 'string' && step.type ? step.type : 'unknown',
      label: typeof step.label === 'string' && step.label ? step.label : compactLabel(String(step.type || `Step ${index + 1}`)),
    }));
}

function WorkflowApprovalEditor({
  args,
  setArgs,
  disabled,
}: {
  args: Record<string, unknown>;
  setArgs: Dispatch<SetStateAction<Record<string, unknown>>>;
  disabled: boolean;
}) {
  const steps = Array.isArray(args.steps) ? args.steps : [];
  const rows = workflowStepRows(steps);
  const updateField = (key: string, value: unknown) => {
    setArgs((prev) => ({ ...prev, [key]: value }));
  };

  return (
    <div style={{
      padding: '0.65rem',
      background: 'var(--code-bg)',
      borderRadius: '6px',
      marginBottom: '0.65rem',
      fontSize: '0.75rem',
    }}>
      <div style={{ display: 'grid', gap: '0.55rem' }}>
        <label style={{ display: 'grid', gap: '0.25rem' }}>
          <span style={{ color: 'var(--text-secondary)', fontWeight: 600 }}>Workflow name</span>
          <input
            value={String(args.name || '')}
            onChange={(e) => updateField('name', e.target.value)}
            disabled={disabled}
            style={approvalInputStyle}
          />
        </label>

        <label style={{ display: 'grid', gap: '0.25rem' }}>
          <span style={{ color: 'var(--text-secondary)', fontWeight: 600 }}>Description</span>
          <textarea
            value={String(args.description || '')}
            onChange={(e) => updateField('description', e.target.value)}
            disabled={disabled}
            rows={3}
            style={approvalTextareaStyle}
          />
        </label>

        <div>
          <div style={{ color: 'var(--text-secondary)', fontWeight: 700, textTransform: 'uppercase', fontSize: '0.68rem', marginBottom: '0.35rem' }}>
            Steps ({rows.length})
          </div>
          <div style={{ display: 'grid', gap: '0.35rem' }}>
            {rows.map((step, index) => (
              <div key={`${step.key}-${index}`} style={{
                display: 'grid',
                gridTemplateColumns: '1.25rem minmax(0, 1fr)',
                gap: '0.45rem',
                alignItems: 'start',
                padding: '0.45rem',
                border: '1px solid var(--border)',
                borderRadius: '6px',
                background: 'var(--surface)',
              }}>
                <span style={{
                  width: '1.25rem',
                  height: '1.25rem',
                  borderRadius: '999px',
                  display: 'inline-flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  background: 'rgba(59, 130, 246, 0.12)',
                  color: 'var(--primary)',
                  fontWeight: 700,
                  fontSize: '0.68rem',
                }}>
                  {index + 1}
                </span>
                <span style={{ minWidth: 0 }}>
                  <span style={{ display: 'block', fontWeight: 650, color: 'var(--text)' }}>{step.label}</span>
                  <span style={{ display: 'block', color: 'var(--text-secondary)', overflowWrap: 'anywhere' }}>
                    {step.key} · {step.type}
                  </span>
                </span>
              </div>
            ))}
            {rows.length === 0 && (
              <div style={{ color: 'var(--danger)' }}>No workflow steps were provided.</div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function ApprovalCard({ toolName, args, addResult, toolCallId }: {
  toolName: string;
  args: Record<string, unknown>;
  addResult: (result: unknown) => void;
  toolCallId?: string;
}) {
  const [status, setStatus] = useState<'pending' | 'executing' | 'done'>('pending');
  const [customArgs, setCustomArgs] = useState<Record<string, unknown>>(() => normalizeCustomAgentArgs(args));
  const [workflowArgs, setWorkflowArgs] = useState<Record<string, unknown>>(() => normalizeWorkflowArgs(args));
  const [agentTools, setAgentTools] = useState<AgentToolOption[]>([]);
  const [toolsLoading, setToolsLoading] = useState(false);
  const [toolsExpanded, setToolsExpanded] = useState(true);
  const { currentProject } = useProject();
  const { persistToolResult, registerTrackedJob } = useChatContext();
  const config = MUTATING_TOOL_CONFIGS[toolName];
  const label = config?.label || toolName;
  const isCustomAgentApproval = toolName === 'startAdhocCustomAgent' || toolName === 'createCustomAgentDefinition';
  const isWorkflowApproval = toolName === 'createWorkflow';

  useEffect(() => {
    if (!isCustomAgentApproval) return;
    setCustomArgs(normalizeCustomAgentArgs(args));
  }, [args, isCustomAgentApproval]);

  useEffect(() => {
    if (!isWorkflowApproval) return;
    setWorkflowArgs(normalizeWorkflowArgs(args));
  }, [args, isWorkflowApproval]);

  useEffect(() => {
    if (!isCustomAgentApproval) return;
    let cancelled = false;
    setToolsLoading(true);
    fetchWithAuth(`${API_BASE}/api/agents/tools/catalog`)
      .then(async (res) => {
        const data = await res.json().catch(() => ({}));
        if (!cancelled && res.ok) setAgentTools(Array.isArray(data.tools) ? data.tools : []);
      })
      .catch(() => {
        if (!cancelled) setAgentTools([]);
      })
      .finally(() => {
        if (!cancelled) setToolsLoading(false);
      });
    return () => { cancelled = true; };
  }, [isCustomAgentApproval]);

  const approvalArgs = isCustomAgentApproval ? customArgs : isWorkflowApproval ? workflowArgs : args;
  const displayArgs = Object.entries(approvalArgs || {}).filter(
    ([k]) => !k.startsWith('_')
  );
  const displayValue = (key: string, val: unknown): string => {
    if (/password|token|secret|credential/i.test(key)) return val ? '[redacted]' : '';
    if (key === 'credentials' && val && typeof val === 'object') return '[redacted]';
    const text = typeof val === 'string' ? val : JSON.stringify(val) ?? '';
    return text.length > 500 ? `${text.slice(0, 500)}...` : text;
  };

  const handleApprove = async () => {
    setStatus('executing');
    try {
      const enrichedArgs = { ...approvalArgs, _projectId: currentProject?.id };
      const pendingRes = await fetchWithAuth('/api/chat/pending-action', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ toolName, args: enrichedArgs }),
      });
      const pendingData = await pendingRes.json();
      if (!pendingRes.ok || !pendingData.actionToken) {
        const errorResult = { error: pendingData.error || 'Approval failed' };
        addResult(errorResult);
        if (toolCallId) persistToolResult(toolCallId, toolName, errorResult);
        setStatus('done');
        return;
      }

      const res = await fetchWithAuth('/api/chat/execute-tool', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ actionToken: pendingData.actionToken }),
      });
      const data = await res.json();
      if (!res.ok) {
        const errorResult = { error: data.error || 'Execution failed' };
        addResult(errorResult);
        if (toolCallId) persistToolResult(toolCallId, toolName, errorResult);
      } else {
        addResult(data);
        if (toolCallId) persistToolResult(toolCallId, toolName, data);
        registerTrackedJob(toolName, data, enrichedArgs, label);
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

      {isCustomAgentApproval ? (
        <CustomAgentApprovalEditor
          args={customArgs}
          setArgs={setCustomArgs}
          tools={agentTools}
          toolsLoading={toolsLoading}
          toolsExpanded={toolsExpanded}
          setToolsExpanded={setToolsExpanded}
          disabled={status !== 'pending'}
        />
      ) : isWorkflowApproval ? (
        <WorkflowApprovalEditor
          args={workflowArgs}
          setArgs={setWorkflowArgs}
          disabled={status !== 'pending'}
        />
      ) : displayArgs.length > 0 && (
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
              <span>{displayValue(key, val)}</span>
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

type ToolSummaryRow = {
  label: string;
  value: string;
  color?: string;
};

type ToolResultSummary = {
  title: string;
  status?: string;
  message?: string;
  rows: ToolSummaryRow[];
  nextActions: string[];
  pageLink?: string;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function asRecord(value: unknown): Record<string, unknown> {
  return isRecord(value) ? value : { value };
}

function compactLabel(value: string) {
  return value
    .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
    .replace(/[_-]+/g, ' ')
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function toolDisplayName(toolName: string) {
  return MUTATING_TOOL_CONFIGS[toolName]?.label || compactLabel(toolName);
}

function truncateText(value: string, max = 180) {
  return value.length > max ? `${value.slice(0, max - 1)}...` : value;
}

function nestedRecords(data: Record<string, unknown>) {
  return [
    data,
    data.result,
    data.data,
    data.summary,
    data.session,
    data.run,
    data.job,
    data.report,
    data.structured_report,
  ].filter(isRecord);
}

function firstField(data: Record<string, unknown>, keys: string[]): unknown {
  for (const source of nestedRecords(data)) {
    for (const key of keys) {
      const value = source[key];
      if (value !== undefined && value !== null && value !== '') return value;
    }
  }
  return undefined;
}

function stringField(data: Record<string, unknown>, keys: string[]) {
  const value = firstField(data, keys);
  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  return undefined;
}

function numberField(data: Record<string, unknown>, keys: string[]) {
  const value = firstField(data, keys);
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value === 'string' && value.trim() !== '' && Number.isFinite(Number(value))) return Number(value);
  return undefined;
}

function normalizeToolStatus(status?: string) {
  if (!status) return undefined;
  return status.trim().toLowerCase().replace(/\s+/g, '_').replace(/-/g, '_');
}

function getToolStatus(data?: Record<string, unknown>) {
  if (!data) return undefined;
  return normalizeToolStatus(stringField(data, ['status', 'state', 'run_status', 'job_status', 'phase_status', 'parse_status']));
}

function isFailureStatus(status?: string) {
  return Boolean(status && ['failed', 'fail', 'error', 'errored', 'cancelled', 'canceled', 'timeout', 'timed_out'].includes(status));
}

function isActiveStatus(status?: string) {
  return Boolean(status && ['running', 'in_progress', 'processing', 'queued', 'pending', 'scheduled', 'starting', 'started', 'awaiting_input'].includes(status));
}

function isAwaitingInput(data?: Record<string, unknown>) {
  const status = getToolStatus(data);
  if (status === 'awaiting_input') return true;
  const pendingQuestions = numberField(data || {}, ['pending_questions', 'questions_pending', 'unanswered_questions']);
  return Boolean(pendingQuestions && pendingQuestions > 0);
}

function countArrayField(data: Record<string, unknown>, keys: string[]) {
  for (const source of nestedRecords(data)) {
    for (const key of keys) {
      const value = source[key];
      if (Array.isArray(value)) return value.length;
    }
  }
  return undefined;
}

function addRow(rows: ToolSummaryRow[], label: string, value: unknown, color?: string) {
  if (value === undefined || value === null || value === '') return;
  rows.push({ label, value: String(value), color });
}

function getStateAwareFollowUps(toolName: string, result?: unknown): string[] {
  const fallback = toolFollowUps[toolName] || ['Show dashboard stats', 'What can I do next?'];
  const data = result ? asRecord(result) : undefined;
  const status = getToolStatus(data);
  const pageLabel = toolPageMap[toolName] ? 'Open related page' : 'Show dashboard stats';

  if (data && (data.error || isFailureStatus(status))) {
    if (toolName.toLowerCase().includes('run')) {
      return ['Show run logs', 'Analyze failure artifacts', 'Retry or heal this run'];
    }
    return ['Show details', 'Retry this action', pageLabel];
  }

  if (isAwaitingInput(data)) {
    return ['Answer the pending question', 'Check status again', pageLabel];
  }

  if (isActiveStatus(status)) {
    if (toolName.toLowerCase().includes('autopilot')) {
      return ['Check Auto Pilot status', 'View Auto Pilot dashboard', 'List Auto Pilot sessions'];
    }
    return ['Check status again', pageLabel, 'Show recent activity'];
  }

  return fallback;
}

function buildToolResultSummary(toolName: string, data: Record<string, unknown>): ToolResultSummary {
  const rows: ToolSummaryRow[] = [];
  const status = getToolStatus(data);
  const id = stringField(data, [
    'run_id',
    'job_id',
    'session_id',
    'agent_run_id',
    'generation_id',
    'batch_id',
    'scan_id',
    'issue_id',
    'spec_id',
    'id',
  ]);
  const message = stringField(data, ['message', 'detail', 'summary', 'description', 'note']);
  const progress = numberField(data, ['progress', 'progress_percent', 'percent_complete', 'coverage', 'coverage_percent', 'pass_rate']);
  const currentPhase = stringField(data, ['current_phase', 'phase', 'stage']);

  addRow(rows, 'Status', status ? compactLabel(status) : undefined, status ? statusColor(status) : undefined);
  addRow(rows, 'ID', id);
  addRow(rows, 'Phase', currentPhase ? compactLabel(currentPhase) : undefined);
  addRow(rows, 'Progress', progress !== undefined ? `${Math.round(progress)}%` : undefined);

  const scalarRows: Array<[string, string[]]> = [
    ['Created', ['created', 'created_count', 'specs_created', 'tests_created', 'generated_count']],
    ['Updated', ['updated', 'updated_count']],
    ['Passed', ['passed', 'passed_count', 'tests_passed']],
    ['Failed', ['failed', 'failed_count', 'tests_failed', 'failure_count']],
    ['Total', ['total', 'total_count', 'run_count', 'test_count']],
  ];
  for (const [label, keys] of scalarRows) {
    addRow(rows, label, numberField(data, keys));
  }

  const arrayRows: Array<[string, string[]]> = [
    ['Runs', ['runs', 'test_runs']],
    ['Specs', ['specs', 'generated_specs']],
    ['Findings', ['findings', 'issues', 'vulnerabilities']],
    ['Test Ideas', ['test_ideas', 'testIdeas']],
    ['Pages', ['pages_checked', 'pages', 'visited_pages']],
    ['Flows', ['flows', 'discovered_flows']],
    ['APIs', ['apis', 'endpoints']],
    ['Questions', ['questions', 'pending_questions']],
    ['Evidence', ['evidence', 'artifacts']],
  ];
  for (const [label, keys] of arrayRows) {
    addRow(rows, label, countArrayField(data, keys));
  }

  if (toolName.toLowerCase().includes('ci') || toolName.toLowerCase().includes('qualitygate')) {
    const run = asRecord(data.run);
    const source = Object.keys(run).length > 0 ? run : data;
    addRow(rows, 'Provider', source.provider ? ciProviderName(source.provider) : undefined);
    addRow(rows, 'Ref', stringField(source, ['ref', 'base_ref', 'branch']));
    addRow(rows, 'Run', stringField(source, ['external_pipeline_id', 'run_id', 'id']));
    addRow(rows, 'Workflow', stringField(source, ['workflow_name', 'workflow_path', 'default_workflow']));
    addRow(rows, 'PR', stringField(data, ['pull_request_url', 'pull_request_number']));
    addRow(rows, 'Passed', numberField(source, ['passed_tests', 'passed']));
    addRow(rows, 'Failed', numberField(source, ['failed_tests', 'failed']), Number(source.failed_tests ?? source.failed ?? 0) > 0 ? 'var(--danger)' : undefined);
  }

  return {
    title: toolDisplayName(toolName),
    status,
    message: message ? truncateText(message) : undefined,
    rows: rows.slice(0, 8),
    nextActions: getStateAwareFollowUps(toolName, data),
    pageLink: toolPageMap[toolName],
  };
}

function ToolSummaryCard({ summary }: { summary: ToolResultSummary }) {
  return (
    <div style={{
      padding: '0.75rem',
      background: 'var(--surface)',
      border: '1px solid var(--border)',
      borderRadius: '8px',
      marginTop: '0.5rem',
      fontSize: '0.85rem',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: summary.message || summary.rows.length ? '0.5rem' : 0 }}>
        <span style={{ fontWeight: 600, color: 'var(--text)' }}>{summary.title}</span>
        {summary.status && (
          <span style={{
            padding: '0.15rem 0.45rem',
            borderRadius: '999px',
            fontSize: '0.68rem',
            fontWeight: 600,
            background: `color-mix(in srgb, ${statusColor(summary.status)} 14%, transparent)`,
            color: statusColor(summary.status),
          }}>
            {compactLabel(summary.status)}
          </span>
        )}
      </div>
      {summary.message && (
        <div style={{ color: 'var(--text-secondary)', fontSize: '0.8rem', lineHeight: 1.45, marginBottom: '0.5rem' }}>
          {summary.message}
        </div>
      )}
      {summary.rows.length > 0 && (
        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(110px, 1fr))',
          gap: '0.5rem',
        }}>
          {summary.rows.map((row) => (
            <div key={`${row.label}:${row.value}`} style={{
              padding: '0.5rem',
              background: 'var(--code-bg)',
              borderRadius: '6px',
              minWidth: 0,
            }}>
              <div style={{ fontSize: '0.68rem', color: 'var(--text-secondary)', marginBottom: '0.15rem' }}>
                {row.label}
              </div>
              <div style={{
                fontSize: '0.8rem',
                fontWeight: 600,
                color: row.color || 'var(--text)',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
              }} title={row.value}>
                {row.value}
              </div>
            </div>
          ))}
        </div>
      )}
      {(summary.nextActions.length > 0 || summary.pageLink) && (
        <div style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: '0.75rem',
          marginTop: '0.6rem',
          flexWrap: 'wrap',
        }}>
          <div style={{ fontSize: '0.72rem', color: 'var(--text-secondary)' }}>
            Next: {summary.nextActions.slice(0, 2).join(' · ')}
          </div>
          {summary.pageLink && (
            <Link href={summary.pageLink} style={{
              fontSize: '0.75rem',
              color: 'var(--primary)',
              whiteSpace: 'nowrap',
            }}>
              Open page &rarr;
            </Link>
          )}
        </div>
      )}
    </div>
  );
}

function stringArrayField(data: Record<string, unknown>, keys: string[]) {
  for (const key of keys) {
    const value = data[key];
    if (Array.isArray(value)) {
      return value
        .map((item) => (typeof item === 'string' ? item : undefined))
        .filter((item): item is string => Boolean(item));
    }
  }
  return [];
}

function specFileLink(specName: string) {
  return `/specs?file=${encodeURIComponent(specName)}`;
}

function specsSearchLink(search: string) {
  return `/specs?search=${encodeURIComponent(search)}`;
}

function SplitSpecResultCard({ data }: { data: Record<string, unknown> }) {
  const files = stringArrayField(data, ['files', 'specs', 'generated_specs']);
  const outputDir = stringField(data, ['output_dir', 'outputDir']);
  const count = numberField(data, ['count', 'created_count', 'specs_created']) ?? files.length;
  const visibleFiles = files.slice(0, 12);
  const remainingCount = Math.max(files.length - visibleFiles.length, 0);

  if (count === 0 && files.length === 0 && !outputDir) return null;

  return (
    <div style={{
      padding: '0.75rem',
      background: 'var(--surface)',
      border: '1px solid var(--border)',
      borderRadius: '8px',
      marginTop: '0.5rem',
      fontSize: '0.85rem',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '0.75rem', marginBottom: files.length > 0 ? '0.6rem' : 0, flexWrap: 'wrap' }}>
        <div>
          <div style={{ fontWeight: 600, color: 'var(--text)' }}>
            {count > 0 ? `Created ${count} split spec${count === 1 ? '' : 's'}` : 'Split completed'}
          </div>
          {outputDir && (
            <div style={{ color: 'var(--text-secondary)', fontSize: '0.78rem', marginTop: '0.15rem' }}>
              Output: {outputDir}
            </div>
          )}
        </div>
        {outputDir && (
          <Link href={specsSearchLink(outputDir)} style={{ fontSize: '0.75rem', color: 'var(--primary)', whiteSpace: 'nowrap' }}>
            View output folder &rarr;
          </Link>
        )}
      </div>

      {visibleFiles.length > 0 && (
        <div style={{ display: 'grid', gap: '0.35rem' }}>
          {visibleFiles.map((file) => (
            <Link
              key={file}
              href={specFileLink(file)}
              style={{
                display: 'block',
                padding: '0.45rem 0.55rem',
                background: 'var(--code-bg)',
                border: '1px solid var(--border-subtle)',
                borderRadius: '6px',
                color: 'var(--text)',
                fontSize: '0.78rem',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
              }}
              title={file}
            >
              {file}
            </Link>
          ))}
          {remainingCount > 0 && (
            <div style={{ color: 'var(--text-secondary)', fontSize: '0.75rem', padding: '0.2rem 0.1rem' }}>
              {remainingCount} more split spec{remainingCount === 1 ? '' : 's'} in this output folder.
            </div>
          )}
        </div>
      )}
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
  const [stale, setStale] = useState(false);

  useEffect(() => {
    if (result) {
      setStale(false);
      return;
    }

    setStale(false);
    const timeout = window.setTimeout(() => setStale(true), 35000);
    return () => window.clearTimeout(timeout);
  }, [result, toolCallId, toolName]);

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

  if (!result) {
    return stale ? <ToolStaleState toolName={toolName} /> : <ToolLoading name={`Running ${toolName}...`} />;
  }

  const data = asRecord(result);
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
  const summary = buildToolResultSummary(toolName, data);
  return (
    <div>
      <ToolSummaryCard summary={summary} />
      {toolName === 'splitSpec' && <SplitSpecResultCard data={data} />}
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
          body: JSON.stringify({ message_index: 0, rating: newRating }),
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
  getWorkflowCapabilities: ['Show missing workflow gaps', 'Open AI Assistant page', 'Run a full health check'],
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
  listApiSpecs: ['Generate API test', 'Import OpenAPI spec', 'View generated tests'],
  getApiSpec: ['Generate API test', 'Run API test', 'Show API specs'],
  getApiJobStatus: ['Show API specs', 'Run API test', 'Check job status again'],
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
  stopLoadTestRun: ['Show load test dashboard', 'View system limits', 'List recent load runs'],
  forceUnlockLoadTesting: ['Show system limits', 'Show load test dashboard'],
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
  createAndGenerateApiTest: ['Check API job status', 'Show API specs', 'Run API test'],
  importOpenApiSpec: ['Check API job status', 'Show API specs', 'View generated tests'],
  generateApiTest: ['Check API job status', 'Run API test', 'Show API specs'],
  runApiTest: ['Check API run history', 'Show API specs'],
  generateApiEdgeCases: ['Check API job status', 'Show API specs'],
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
  startAdhocCustomAgent: ['View agent run', 'Check agent status', 'Show custom agent reports'],
  createCustomAgentDefinition: ['Open agents dashboard', 'Run saved custom agent', 'Show custom agent reports'],
  createWorkflow: ['Open workflow dashboard', 'Start saved workflow', 'List workflow catalog'],
  startWorkflow: ['Check workflow status', 'Open workflow dashboard', 'Show workflow run steps'],
  getAutoPilotStatus: ['Answer a pending question', 'Pause Auto Pilot', 'Check status again later'],
  pauseAutoPilot: ['Resume Auto Pilot', 'Check Auto Pilot status', 'View Auto Pilot dashboard'],
  resumeAutoPilot: ['Check Auto Pilot status', 'View Auto Pilot dashboard'],
  answerAutoPilotQuestion: ['Check Auto Pilot status', 'View Auto Pilot dashboard'],
  stopAutoPilotTestTask: ['Check Auto Pilot status', 'View Auto Pilot dashboard'],
  cancelAutoPilot: ['List Auto Pilot sessions', 'Start a new Auto Pilot'],
  listAutoPilotSessions: ['Check status of a session', 'Start a new Auto Pilot', 'View Auto Pilot dashboard'],
  listProjects: ['Show current project details', 'List project credentials', 'Create a new project'],
  getProject: ['List project members', 'Assign specs to this project', 'Show dashboard stats'],
  listProjectCredentials: ['Set a project credential', 'Open project settings', 'List projects'],
  createProject: ['List projects', 'Set project credentials', 'Assign specs'],
  listRecordings: ['Start a recording', 'Import a recording', 'Show latest recording code'],
  getRecording: ['Stop this recording', 'Import this recording', 'Show recording code'],
  startRecording: ['Check recording status', 'Stop recording', 'Open recorder'],
  importRecording: ['Run imported spec', 'Show specs', 'View recording'],
  getAssistantSettings: ['Test connection', 'Update model settings', 'Open settings'],
  testAssistantSettingsConnection: ['Show settings', 'Update settings', 'Run health check'],
  listScheduleExecutions: ['Show schedules', 'Get next run times', 'Trigger schedule now'],
  listProjectScheduleExecutions: ['Show schedules', 'Check failures', 'Create schedule'],
  getNextScheduleRuns: ['Update schedule', 'Trigger schedule now', 'Show executions'],
  validateCronExpression: ['Create schedule', 'Show schedules', 'Try another cron'],
  createSchedule: ['Show schedules', 'Get next run times', 'Run schedule now'],
  updateSchedule: ['Show schedule', 'Get next run times', 'List executions'],
  toggleSchedule: ['Show schedules', 'List executions', 'Get next run times'],
  listPrdProjects: ['Show PRD features', 'Check PRD queue', 'Show generation history'],
  listPrdFeatures: ['Generate test plan', 'Show PRD generations', 'Check queue status'],
  getPrdGenerationStatus: ['Generate Playwright test', 'Stop generation', 'Show generation history'],
  generatePrdPlan: ['Check generation status', 'Show PRD generations', 'Open PRD page'],
  getCiControlOverview: ['List CI workflows', 'Sync CI runs', 'Show failed CI logs'],
  listOpenPullRequests: ['Analyze a PR', 'Run selected generated tests', 'Open PR Advisor'],
  listCiProviders: ['List CI workflows', 'Sync CI runs', 'Update CI defaults'],
  listCiWorkflows: ['Dispatch workflow', 'Generate workflow change', 'List CI runs'],
  listGeneratedCiTests: ['Create CI test subset', 'Preview selected tests', 'Open CI/CD'],
  listCiTestSubsets: ['Open subset PR', 'Dispatch subset workflow', 'List generated CI tests'],
  getCiTestSubset: ['Preview subset files', 'Open subset PR', 'Dispatch subset workflow'],
  previewCiTestSubset: ['Open subset PR', 'Update subset', 'Open CI/CD'],
  listCiRuns: ['Show CI run detail', 'Get CI logs', 'Sync CI runs'],
  getCiRunDetail: ['Get CI logs', 'Rerun CI run', 'Cancel CI run'],
  getCiRunLogs: ['Show CI run detail', 'Rerun CI run', 'Open CI/CD'],
  generateCiWorkflowChange: ['Open workflow PR', 'List CI workflows', 'Open CI/CD'],
  createCiTestSubset: ['Open subset PR', 'Preview subset files', 'List generated CI tests'],
  updateCiTestSubset: ['Open subset PR', 'Preview subset files', 'List subsets'],
  openCiTestSubsetPullRequest: ['Open CI/CD', 'List subsets', 'Set default workflow'],
  dispatchCiTestSubset: ['Sync CI runs', 'Show CI run detail', 'Open CI/CD'],
  updateCiProviderDefaults: ['Show CI/CD overview', 'List workflows', 'Open CI/CD'],
  listPrAdvisorAnalyses: ['Analyze a PR', 'Run recommended tests', 'Show latest analysis'],
  getPrAdvisorAnalysis: ['Run recommended tests', 'Show changed files', 'Open PR Advisor'],
  analyzePullRequestTests: ['Run recommended tests', 'Show analysis details', 'Open PR Advisor'],
  getChatControlAudit: ['Plan UI test coverage', 'Show Explorer Agent gaps', 'Open AI Assistant'],
  planUiTestCoverage: ['Execute selected specs', 'Create missing specs', 'Analyze latest failures'],
  analyzeUiTestRunArtifacts: ['Generate Jira bug report', 'Heal and rerun', 'Show generated code'],
  executeUiTestCoveragePlan: ['Check run status', 'Open test runs', 'Analyze failures'],
  listSpecFolders: ['List automated specs', 'Create a folder', 'Move a spec'],
  listAutomatedSpecs: ['Plan UI test coverage', 'Run selected specs', 'Show spec history'],
  getSpecMetadata: ['Update metadata', 'Show spec content', 'Run this spec'],
  getSpecInfo: ['Show generated code', 'Show run history', 'Update metadata'],
  updateGeneratedCode: ['Run this spec', 'Show generated code', 'Open specs'],
  updateSpecMetadata: ['Show metadata', 'Run this spec', 'Open specs'],
  moveSpec: ['Show spec folders', 'List specs', 'Open specs'],
  renameSpec: ['Show spec info', 'List specs', 'Open specs'],
  splitSpec: ['Show generated specs', 'Run selected specs', 'Open specs'],
  createSpecFolder: ['Move specs here', 'List folders', 'Open specs'],
  getExplorationHealth: ['Show exploration queue', 'List explorations', 'Start Explorer Agent'],
  getExplorationQueueStatus: ['Show exploration health', 'Start exploration', 'Open exploration'],
  getExplorationArtifacts: ['Show flows', 'Show issues', 'Generate API specs'],
  getExplorationResults: ['Show artifacts', 'Show discovered APIs', 'Generate tests'],
  getExplorationFlows: ['Generate flow specs', 'Show flow details', 'Create tests from flows'],
  getExplorationApis: ['Generate API specs', 'Generate API tests', 'Open API testing'],
  getExplorationIssues: ['Create Jira issue', 'Show artifacts', 'Plan coverage'],
  getAgentQueueStatus: ['List agent runs', 'Start Explorer Agent', 'Open agents'],
  listAgentToolCatalog: ['List agent definitions', 'Start custom agent', 'Open agents'],
  listAgentDefinitions: ['Start an agent', 'Show tool catalog', 'Open agents'],
  getAgentDefinition: ['Start this agent', 'List agent runs', 'Open agents'],
  getAgentRun: ['Show agent report', 'Search reports', 'Create specs'],
  getExplorerGeneratedSpecs: ['Run generated specs', 'Show Explorer flows', 'Open specs'],
  getExplorerFlowDetails: ['Generate flow spec', 'Generate flow test', 'Update flow'],
  getExplorerFlowSpecJob: ['Check job again', 'Show generated specs', 'Open exploration'],
  listExplorerSessions: ['Save browser session', 'Delete old sessions', 'Start Explorer Agent'],
  synthesizeExplorerSpecs: ['Show generated specs', 'Run selected specs', 'Open exploration'],
  analyzeExplorerPrerequisites: ['Generate flow spec', 'Show flow details', 'Open exploration'],
  generateExplorerFlowSpec: ['Check spec job', 'Generate Playwright test', 'Open specs'],
  generateExplorerFlowTest: ['Run generated test', 'Show generated code', 'Open runs'],
  updateExplorerFlow: ['Show flow details', 'Generate flow spec', 'Open exploration'],
  deleteExplorerFlow: ['List remaining flows', 'Open exploration', 'Plan coverage'],
  saveExplorerSession: ['List sessions', 'Start Explorer Agent', 'Open exploration'],
  deleteExplorerSession: ['List sessions', 'Open exploration'],
  generateApiSpecsFromExploration: ['Open API testing', 'Generate API tests', 'Run API tests'],
  generateApiTestsFromExploration: ['Open API testing', 'Run API tests', 'Show API specs'],
  getRegressionBatchDetail: ['Rerun failed tests', 'Export batch', 'Show spec history'],
  getSpecHistory: ['Plan coverage', 'Run this spec', 'Show recent failures'],
  exportRegressionBatch: ['Open regression', 'Compare batches', 'Show latest batch'],
  refreshRegressionBatch: ['Show batch detail', 'Rerun failed tests', 'Export batch'],
  cancelRegressionBatch: ['Show regression batches', 'Open regression'],
  renameRegressionBatch: ['Show batch detail', 'Open regression'],
  deleteRegressionBatch: ['Show regression batches', 'Open regression'],
  getQualityGateConfig: ['Start PR quality gate', 'List quality gates', 'Open CI/CD'],
  listPrQualityGates: ['Show gate status', 'Start PR quality gate', 'Open CI/CD'],
  getPrQualityGate: ['Check gate status', 'Run recommended tests', 'Open CI/CD'],
  getPrQualityGateStatus: ['Show gate details', 'List quality gates', 'Open CI/CD'],
  startPrQualityGate: ['Check gate status', 'Open CI/CD', 'Run recommended tests'],
  getJiraConfig: ['Test Jira connection', 'Create issue from run', 'Open settings'],
  testJiraConnection: ['Show Jira config', 'Generate bug report', 'Open settings'],
  getJiraBugReportJob: ['Create Jira issue', 'Show run artifacts', 'Open runs'],
  listJiraIssues: ['Show run issue', 'Generate bug report', 'Open runs'],
  getJiraIssueForRun: ['Show run artifacts', 'Create another issue', 'Open runs'],
  generateJiraBugReport: ['Create Jira issue', 'Show job status', 'Analyze run artifacts'],
  createJiraIssue: ['Show issue for run', 'Open runs', 'Analyze failures'],
  getTestRailConfig: ['Test TestRail connection', 'List mappings', 'Open settings'],
  testTestRailConnection: ['Show TestRail config', 'Push test cases', 'Open settings'],
  listTestRailMappings: ['Push test cases', 'Preview result sync', 'Open settings'],
  getTestRailSyncPreview: ['Sync results', 'Show regression batch', 'Open regression'],
  pushTestRailCases: ['List mappings', 'Preview result sync', 'Open settings'],
  syncTestRailResults: ['Preview sync', 'Show regression batch', 'Open regression'],
  deleteTestRailMapping: ['List mappings', 'Push test cases', 'Open settings'],
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
          suggestions = getStateAwareFollowUps(p.toolName, p.result ?? p.output ?? p.toolResult);
          break;
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
  { command: '/control', label: 'Chat Control', description: 'Show chatbot workflow coverage', prompt: 'Show me everything the chatbot can control for UI testing workflows' },
  { command: '/audit', label: 'Control Audit', description: 'Find chatbot control gaps', prompt: 'Audit chatbot control coverage for UI testing and tell me what is missing or weak' },
  { command: '/coverage-plan', label: 'Coverage Plan', description: 'Plan UI test coverage', prompt: 'Plan UI test coverage from current specs, explorations, recent runs, and known gaps' },
  { command: '/artifacts', label: 'Run Artifacts', description: 'Analyze run evidence', prompt: 'Analyze the latest failed UI test run artifacts and suggest the next action' },
  { command: '/bug', label: 'Jira Bug', description: 'Create bug report from a run', prompt: 'Generate a Jira-ready bug report from the latest failed UI test run' },
  { command: '/testrail', label: 'TestRail Sync', description: 'Preview or sync TestRail', prompt: 'Show TestRail configuration, mappings, and the safest next sync action' },
  { command: '/run', label: 'Run Tests', description: 'Run a test spec', prompt: 'Run the test spec: ' },
  { command: '/status', label: 'Dashboard Status', description: 'Show dashboard stats', prompt: 'Show me the current dashboard stats and test status' },
  { command: '/explore', label: 'Start Exploration', description: 'Explore a web app', prompt: 'Start a new AI exploration of ' },
  { command: '/record', label: 'Record UI Flow', description: 'Start or inspect recordings', prompt: 'Help me record a UI flow for ' },
  { command: '/autopilot', label: 'Auto Pilot', description: 'Control Auto Pilot', prompt: 'Show my Auto Pilot sessions and pending work' },
  { command: '/stop', label: 'Stop Work', description: 'Stop a run or session', prompt: 'Help me stop a running job or session' },
  { command: '/ci', label: 'CI/CD Control', description: 'Inspect or run CI workflows', prompt: 'Show my CI/CD providers, workflows, and recent runs' },
  { command: '/prd', label: 'PRD Workflow', description: 'Inspect PRD plans and generations', prompt: 'Show my PRD projects, features, and generation queue status' },
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
  { command: '/security-audit', label: 'Security Audit', description: 'Security posture review', prompt: 'Give me a security posture review — findings summary, recent scans, and comparison of the latest two scans' },
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

  useEffect(() => {
    function handleAssistantPrefill(event: Event) {
      const detail = (event as CustomEvent<{ prompt?: string; send?: boolean }>).detail;
      const prompt = detail?.prompt;
      if (!prompt) return;
      setInputText(prompt);
      runtime.composer.setText(prompt);
      setTimeout(() => inputRef.current?.focus(), 0);
      if (detail?.send) {
        setTimeout(() => runtime.composer.send(), 0);
      }
    }
    window.addEventListener('assistant-prefill', handleAssistantPrefill);
    return () => window.removeEventListener('assistant-prefill', handleAssistantPrefill);
  }, [runtime]);

  // Filter commands based on current input
  const filtered = useMemo(
    () => inputText.startsWith('/')
      ? slashCommands.filter(cmd => cmd.command.startsWith(inputText.toLowerCase()))
      : [],
    [inputText]
  );

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
      <CiOverviewToolUI />
      <CiProvidersToolUI />
      <CiWorkflowsToolUI />
      <CiRunsToolUI />
      <CiRunDetailToolUI />
      <CiRunLogsToolUI />
      <CiWorkflowChangeToolUI />
      <OpenPullRequestsToolUI />
      <PrAdvisorAnalysesToolUI />
      <PrAdvisorAnalysisToolUI />

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
