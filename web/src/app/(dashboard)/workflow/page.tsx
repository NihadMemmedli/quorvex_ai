'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import Link from 'next/link';
import { AlertTriangle, Bot, CheckCircle2, Clock, Loader2, PlayCircle, Rocket, Workflow, XCircle } from 'lucide-react';
import { API_BASE } from '@/lib/api';
import { useProject } from '@/contexts/ProjectContext';
import { PageLayout } from '@/components/ui/page-layout';
import { PageHeader } from '@/components/ui/page-header';
import { EmptyState } from '@/components/ui/empty-state';

interface AutoPilotSession {
  id: string;
  project_id: string | null;
  entry_urls: string[];
  status: string;
  current_phase: string | null;
  overall_progress: number;
  current_phase_progress: number;
  total_pages_discovered: number;
  total_flows_discovered: number;
  total_requirements_generated: number;
  total_specs_generated: number;
  total_tests_generated: number;
  total_tests_passed: number;
  total_tests_failed: number;
  error_message: string | null;
  created_at: string;
  completed_at: string | null;
}

interface AutoPilotQuestion {
  id: number;
  session_id: string;
  phase_name: string;
  question_text: string;
  status: string;
  auto_continue_at: string | null;
}

interface AgentQueueStatus {
  mode?: string;
  active?: number;
  queued?: number;
  workers_alive?: number;
  stale_running?: number;
  oldest_queued_age_seconds?: number | null;
  by_status?: Record<string, number>;
  worker_health?: {
    worker_count?: number;
    running_tasks?: number;
    alive_tasks?: number;
  };
}

const statusColor: Record<string, string> = {
  pending: '#94a3b8',
  running: '#3b82f6',
  awaiting_input: '#f59e0b',
  paused: '#f59e0b',
  completed: '#22c55e',
  failed: '#ef4444',
  cancelled: '#94a3b8',
};

function progressPercent(value: number | null | undefined): number {
  const numeric = typeof value === 'number' && Number.isFinite(value) ? value : 0;
  return Math.max(0, Math.min(100, numeric <= 1 ? numeric * 100 : numeric));
}

function formatAge(iso: string): string {
  const created = new Date(iso.endsWith('Z') ? iso : `${iso}Z`).getTime();
  const seconds = Math.max(0, Math.floor((Date.now() - created) / 1000));
  if (seconds < 60) return 'just now';
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}

function SessionIcon({ status }: { status: string }) {
  if (status === 'completed') return <CheckCircle2 size={18} style={{ color: statusColor.completed }} />;
  if (status === 'failed') return <XCircle size={18} style={{ color: statusColor.failed }} />;
  if (status === 'awaiting_input') return <AlertTriangle size={18} style={{ color: statusColor.awaiting_input }} />;
  if (status === 'running') return <Loader2 size={18} style={{ color: statusColor.running, animation: 'spin 1s linear infinite' }} />;
  return <PlayCircle size={18} style={{ color: statusColor[status] || 'var(--text-secondary)' }} />;
}

export default function WorkflowPage() {
  const { currentProject } = useProject();
  const [sessions, setSessions] = useState<AutoPilotSession[]>([]);
  const [questionsBySession, setQuestionsBySession] = useState<Record<string, AutoPilotQuestion[]>>({});
  const [queueStatus, setQueueStatus] = useState<AgentQueueStatus | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    const projectParam = currentProject?.id ? `?project_id=${encodeURIComponent(currentProject.id)}` : '';
    const sessionsRes = await fetch(`${API_BASE}/autopilot/sessions${projectParam}`);
    const sessionsData = sessionsRes.ok ? await sessionsRes.json() : [];
    const visibleSessions = Array.isArray(sessionsData) ? sessionsData.slice(0, 8) : [];
    setSessions(visibleSessions);

    const questionPairs = await Promise.all(
      visibleSessions
        .filter((session: AutoPilotSession) => ['running', 'awaiting_input', 'paused'].includes(session.status))
        .map(async (session: AutoPilotSession) => {
          const res = await fetch(`${API_BASE}/autopilot/${session.id}/questions?status=pending`);
          const questions = res.ok ? await res.json() : [];
          return [session.id, Array.isArray(questions) ? questions : []] as const;
        })
    );
    setQuestionsBySession(Object.fromEntries(questionPairs));

    const queueRes = await fetch(`${API_BASE}/api/agents/queue-status`);
    setQueueStatus(queueRes.ok ? await queueRes.json() : null);
    setLoading(false);
  }, [currentProject?.id]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    load().catch(() => {
      if (!cancelled) setLoading(false);
    });
    const interval = setInterval(() => {
      if (!cancelled) load().catch(() => {});
    }, 10000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [load]);

  const pendingQuestions = useMemo(
    () => Object.values(questionsBySession).flat().filter(question => question.status === 'pending'),
    [questionsBySession]
  );

  const activeSessions = sessions.filter(session => ['pending', 'running', 'awaiting_input', 'paused'].includes(session.status));
  const failedSessions = sessions.filter(session => session.status === 'failed');

  return (
    <PageLayout>
      <PageHeader
        title="AI Workflows"
        subtitle="Active automation, review gates, and agent execution health."
        icon={<Workflow size={20} />}
        actions={(
          <Link href="/autopilot" style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: '0.5rem',
            padding: '0.55rem 0.85rem',
            borderRadius: '8px',
            background: 'var(--primary)',
            color: 'white',
            textDecoration: 'none',
            fontSize: '0.85rem',
            fontWeight: 600,
          }}>
            <Rocket size={16} />
            Auto Pilot
          </Link>
        )}
      />

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '1rem' }}>
        {[
          { label: 'Active Sessions', value: activeSessions.length, icon: Rocket, color: '#3b82f6' },
          { label: 'Pending Reviews', value: pendingQuestions.length, icon: AlertTriangle, color: '#f59e0b' },
          { label: 'Agent Queue', value: queueStatus?.queued ?? 0, icon: Bot, color: '#8b5cf6' },
          { label: 'Failures', value: failedSessions.length, icon: XCircle, color: '#ef4444' },
        ].map(item => {
          const Icon = item.icon;
          return (
            <div key={item.label} style={{
              padding: '1rem',
              border: '1px solid var(--border-subtle)',
              borderRadius: '8px',
              background: 'var(--background-raised)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
            }}>
              <div>
                <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', marginBottom: '0.35rem' }}>{item.label}</div>
                <div style={{ fontSize: '1.7rem', fontWeight: 800, color: 'var(--text)' }}>{item.value}</div>
              </div>
              <Icon size={22} style={{ color: item.color }} />
            </div>
          );
        })}
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1.6fr) minmax(280px, 0.8fr)', gap: '1rem', marginTop: '1rem' }}>
        <section style={{ border: '1px solid var(--border-subtle)', borderRadius: '8px', background: 'var(--background-raised)' }}>
          <div style={{ padding: '1rem', borderBottom: '1px solid var(--border-subtle)', display: 'flex', justifyContent: 'space-between' }}>
            <div style={{ fontWeight: 700 }}>Recent AutoPilot Work</div>
            <Link href="/autopilot" style={{ color: 'var(--primary)', fontSize: '0.85rem', textDecoration: 'none' }}>View all</Link>
          </div>
          {loading ? (
            <div style={{ padding: '2rem', color: 'var(--text-secondary)' }}>Loading workflows...</div>
          ) : sessions.length === 0 ? (
            <EmptyState title="No AI workflow runs" description="Start Auto Pilot to discover flows, generate specs, and run tests." icon={Rocket} />
          ) : (
            <div>
              {sessions.map(session => {
                const color = statusColor[session.status] || 'var(--text-secondary)';
                const pending = questionsBySession[session.id]?.length || 0;
                return (
                  <Link
                    key={session.id}
                    href={`/autopilot?session=${encodeURIComponent(session.id)}`}
                    style={{
                      display: 'grid',
                      gridTemplateColumns: 'auto minmax(0, 1fr) auto',
                      gap: '0.85rem',
                      padding: '1rem',
                      borderBottom: '1px solid var(--border-subtle)',
                      textDecoration: 'none',
                      color: 'inherit',
                    }}
                  >
                    <SessionIcon status={session.status} />
                    <div style={{ minWidth: 0 }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.35rem' }}>
                        <span style={{ fontWeight: 700, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                          {session.entry_urls[0] || session.id}
                        </span>
                        <span style={{ padding: '0.15rem 0.45rem', borderRadius: '999px', fontSize: '0.7rem', color, background: `${color}18` }}>
                          {session.status.replace('_', ' ')}
                        </span>
                        {pending > 0 && (
                          <span style={{ padding: '0.15rem 0.45rem', borderRadius: '999px', fontSize: '0.7rem', color: '#f59e0b', background: 'rgba(245,158,11,0.12)' }}>
                            review
                          </span>
                        )}
                      </div>
                      <div style={{ height: '6px', borderRadius: '999px', background: 'var(--surface)', overflow: 'hidden' }}>
                        <div style={{ width: `${progressPercent(session.overall_progress)}%`, height: '100%', background: color }} />
                      </div>
                      <div style={{ marginTop: '0.45rem', fontSize: '0.78rem', color: 'var(--text-secondary)' }}>
                        {session.current_phase || 'queued'} · {session.total_flows_discovered} flows · {session.total_specs_generated} specs · {formatAge(session.created_at)}
                      </div>
                    </div>
                    <div style={{ textAlign: 'right', fontSize: '0.78rem', color: 'var(--text-secondary)' }}>
                      {Math.round(progressPercent(session.overall_progress))}%
                    </div>
                  </Link>
                );
              })}
            </div>
          )}
        </section>

        <aside style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
          <section style={{ border: '1px solid var(--border-subtle)', borderRadius: '8px', background: 'var(--background-raised)', padding: '1rem' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontWeight: 700, marginBottom: '0.85rem' }}>
              <AlertTriangle size={17} style={{ color: pendingQuestions.length ? '#f59e0b' : 'var(--text-secondary)' }} />
              Review Gates
            </div>
            {pendingQuestions.length === 0 ? (
              <div style={{ color: 'var(--text-secondary)', fontSize: '0.85rem' }}>No pending reviews.</div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                {pendingQuestions.slice(0, 5).map(question => (
                  <Link key={question.id} href={`/autopilot?session=${encodeURIComponent(question.session_id)}`} style={{
                    padding: '0.75rem',
                    borderRadius: '8px',
                    border: '1px solid rgba(245,158,11,0.22)',
                    background: 'rgba(245,158,11,0.08)',
                    textDecoration: 'none',
                    color: 'inherit',
                  }}>
                    <div style={{ fontSize: '0.75rem', color: '#f59e0b', marginBottom: '0.35rem' }}>{question.phase_name.replace('_', ' ')}</div>
                    <div style={{ fontSize: '0.85rem', lineHeight: 1.4 }}>{question.question_text}</div>
                  </Link>
                ))}
              </div>
            )}
          </section>

          <section style={{ border: '1px solid var(--border-subtle)', borderRadius: '8px', background: 'var(--background-raised)', padding: '1rem' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontWeight: 700, marginBottom: '0.85rem' }}>
              <Bot size={17} style={{ color: '#8b5cf6' }} />
              Agent Queue
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem', fontSize: '0.85rem' }}>
              <Metric label="Mode" value={queueStatus?.mode || '-'} />
              <Metric label="Workers" value={String(queueStatus?.workers_alive ?? queueStatus?.worker_health?.worker_count ?? 0)} />
              <Metric label="Running" value={String(queueStatus?.active ?? 0)} />
              <Metric label="Queued" value={String(queueStatus?.queued ?? 0)} />
              <Metric label="Stale" value={String(queueStatus?.stale_running ?? 0)} />
              <Metric label="Oldest" value={queueStatus?.oldest_queued_age_seconds ? `${Math.round(queueStatus.oldest_queued_age_seconds)}s` : '-'} />
            </div>
            <div style={{ marginTop: '0.85rem', display: 'flex', alignItems: 'center', gap: '0.45rem', color: 'var(--text-secondary)', fontSize: '0.78rem' }}>
              <Clock size={14} />
              Refreshes every 10s
            </div>
          </section>
        </aside>
      </div>
    </PageLayout>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ padding: '0.65rem', borderRadius: '8px', background: 'var(--surface)' }}>
      <div style={{ color: 'var(--text-secondary)', fontSize: '0.72rem', marginBottom: '0.25rem' }}>{label}</div>
      <div style={{ fontWeight: 700, color: 'var(--text)' }}>{value}</div>
    </div>
  );
}
