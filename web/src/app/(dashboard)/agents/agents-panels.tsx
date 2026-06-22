'use client';
import { useEffect, useMemo, useState } from 'react';
import type React from 'react';
import dynamic from 'next/dynamic';
import Link from 'next/link';
import Bot from 'lucide-react/dist/esm/icons/bot';
import FileText from 'lucide-react/dist/esm/icons/file-text';
import Terminal from 'lucide-react/dist/esm/icons/terminal';
import CheckCircle2 from 'lucide-react/dist/esm/icons/check-circle-2';
import AlertTriangle from 'lucide-react/dist/esm/icons/alert-triangle';
import Loader2 from 'lucide-react/dist/esm/icons/loader-2';
import Clock from 'lucide-react/dist/esm/icons/clock';
import RotateCcw from 'lucide-react/dist/esm/icons/rotate-ccw';
import Download from 'lucide-react/dist/esm/icons/download';
import List from 'lucide-react/dist/esm/icons/list';
import ArrowRight from 'lucide-react/dist/esm/icons/arrow-right';
import Info from 'lucide-react/dist/esm/icons/info';
import RefreshCw from 'lucide-react/dist/esm/icons/refresh-cw';
import ExternalLink from 'lucide-react/dist/esm/icons/external-link';
import Wrench from 'lucide-react/dist/esm/icons/wrench';
import MessageSquare from 'lucide-react/dist/esm/icons/message-square';
import Bug from 'lucide-react/dist/esm/icons/bug';
import Lightbulb from 'lucide-react/dist/esm/icons/lightbulb';
import Eye from 'lucide-react/dist/esm/icons/eye';
import VideoIcon from 'lucide-react/dist/esm/icons/video';
import Monitor from 'lucide-react/dist/esm/icons/monitor';
import ImageIcon from 'lucide-react/dist/esm/icons/image';
import Copy from 'lucide-react/dist/esm/icons/copy';
import Search from 'lucide-react/dist/esm/icons/search';
import Database from 'lucide-react/dist/esm/icons/database';
import Cpu from 'lucide-react/dist/esm/icons/cpu';
import PackageOpen from 'lucide-react/dist/esm/icons/package-open';
import Pencil from 'lucide-react/dist/esm/icons/pencil';
import { toast } from 'sonner';
import { API_BASE } from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Alert, AlertDescription } from '@/components/ui/alert';
import {
    LIVE_AGENT_STATUSES,
    agentRunPartialReason,
    formatQueueAge,
    formatToolName,
    getArtifactUrl,
    getStructuredReport,
    itemPrompt,
    queueStateLabel,
    reportItemReviewState,
    reportItemSeverity,
    reportSearchResultHref,
    reportStatusColor,
    severityColor,
    sortArtifactsByModifiedAt,
    agentRunNoteFromEvent,
    filterAgentRunNotes,
    mergeAgentRunNotes,
    type AgentQueueStatus,
    type AgentReportSearchItem,
    type AgentRun,
    type AgentRunEvent,
    type AgentRunNote,
    type AgentTraceBundle,
    type CustomResultTab,
    type ReportEditableItemType,
    type ReportFinding,
    type ReportRequirement,
    type ReportTestIdea,
    type StructuredAgentReport,
    type TraceTab,
} from './agents-model';
import { fetchAgentRunNotes } from './agents-api';
import type { ReportReviewFilter, ReportSearchTypeFilter } from './agents-workspace-state';

const LiveBrowserView = dynamic<any>(() => import('@/components/LiveBrowserView').then(mod => mod.LiveBrowserView), { ssr: false });

export function AgentRunCapturePanel({
    activeRun,
    mode,
}: {
    activeRun: AgentRun;
    mode: 'live' | 'recording';
}) {
    const artifacts = activeRun.artifacts || [];
    const latestVideo = sortArtifactsByModifiedAt(artifacts.filter(artifact => artifact.type === 'video'))[0];
    const latestImage = sortArtifactsByModifiedAt(artifacts.filter(artifact => artifact.type === 'image'))[0];

    if (!latestVideo && !latestImage && mode === 'recording') {
        return null;
    }

    return (
        <div style={{
            border: '1px solid var(--border)',
            borderRadius: '8px',
            overflow: 'hidden',
            background: 'var(--surface-hover)'
        }}>
            <div style={{
                padding: '0.75rem 1rem',
                borderBottom: '1px solid var(--border)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                gap: '0.75rem'
            }}>
                <h4 style={{
                    margin: 0,
                    fontSize: '0.9rem',
                    fontWeight: 600,
                    display: 'flex',
                    alignItems: 'center',
                    gap: '0.5rem'
                }}>
                    {mode === 'live' ? <Monitor size={16} /> : <VideoIcon size={16} />}
                    {mode === 'live' ? 'Live Capture' : 'Recording'}
                </h4>
                {latestVideo && (
                    <a
                        href={getArtifactUrl(latestVideo)}
                        target="_blank"
                        rel="noreferrer"
                        style={{
                            display: 'inline-flex',
                            alignItems: 'center',
                            gap: '0.35rem',
                            color: 'var(--primary)',
                            fontSize: '0.8rem',
                            textDecoration: 'none',
                            flexShrink: 0
                        }}
                    >
                        Open <ExternalLink size={13} />
                    </a>
                )}
            </div>

            <div style={{ padding: '1rem' }}>
                {latestVideo ? (
                    <div style={{ border: '1px solid var(--border)', borderRadius: '8px', overflow: 'hidden', background: '#000' }}>
                        <video
                            controls
                            preload="metadata"
                            src={getArtifactUrl(latestVideo)}
                            style={{ width: '100%', display: 'block', aspectRatio: '16/9', background: '#000' }}
                        />
                        <div style={{
                            padding: '0.65rem 0.85rem',
                            background: 'var(--surface)',
                            borderTop: '1px solid var(--border)',
                            fontSize: '0.82rem',
                            color: 'var(--text-secondary)',
                            whiteSpace: 'nowrap',
                            overflow: 'hidden',
                            textOverflow: 'ellipsis'
                        }}>
                            {latestVideo.name}
                        </div>
                    </div>
                ) : latestImage ? (
                    <div>
                        <div style={{
                            display: 'flex',
                            alignItems: 'center',
                            gap: '0.4rem',
                            color: 'var(--text-secondary)',
                            fontSize: '0.82rem',
                            marginBottom: '0.75rem'
                        }}>
                            <ImageIcon size={14} />
                            Latest screenshot
                        </div>
                        <img
                            src={getArtifactUrl(latestImage)}
                            alt="Latest agent browser screenshot"
                            style={{
                                width: '100%',
                                display: 'block',
                                aspectRatio: '16 / 9',
                                objectFit: 'contain',
                                borderRadius: '8px',
                                border: '1px solid var(--border)',
                                background: '#000'
                            }}
                        />
                    </div>
                ) : (
                    <div style={{
                        minHeight: '90px',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        color: 'var(--text-secondary)',
                        fontSize: '0.9rem',
                        textAlign: 'center'
                    }}>
                        Waiting for the first browser capture...
                    </div>
                )}
            </div>
        </div>
    );
}

export function CustomAgentReportView({
    run,
    activeTab,
    onTabChange,
    onAskAssistant,
    onCreateSpecFromReport,
    onEditOverview,
    onEditReportItem,
    onImportRequirements,
    importingRequirementIds,
    importError,
    reportStatusFilter,
    onReportStatusFilterChange,
    reportSeverityFilter,
    onReportSeverityFilterChange,
}: {
    run: AgentRun;
    activeTab: CustomResultTab;
    onTabChange: (tab: CustomResultTab) => void;
    onAskAssistant: (prompt: string) => void;
    onCreateSpecFromReport: (item: ReportFinding | ReportTestIdea, kind: 'finding' | 'test_idea') => void;
    onEditOverview: (report: StructuredAgentReport) => void;
    onEditReportItem: (item: ReportFinding | ReportTestIdea | ReportRequirement, kind: ReportEditableItemType) => void;
    onImportRequirements: (itemIds?: string[]) => void;
    importingRequirementIds: string[];
    importError?: string | null;
    reportStatusFilter: ReportReviewFilter;
    onReportStatusFilterChange: (value: ReportReviewFilter) => void;
    reportSeverityFilter: string;
    onReportSeverityFilterChange: (value: string) => void;
}) {
    const report = getStructuredReport(run);
    const partialReason = agentRunPartialReason(run);
    const findings = report.findings || [];
    const testIdeas = report.test_ideas || [];
    const requirements = report.requirements || [];
    const filteredFindings = findings.filter(item => (
        (reportStatusFilter === 'all' || reportItemReviewState(item as unknown as Record<string, any>, 'finding') === reportStatusFilter) &&
        (reportSeverityFilter === 'all' || reportItemSeverity(item as unknown as Record<string, any>) === reportSeverityFilter)
    ));
    const filteredTestIdeas = testIdeas.filter(item => (
        (reportStatusFilter === 'all' || reportItemReviewState(item as unknown as Record<string, any>, 'test_idea') === reportStatusFilter) &&
        (reportSeverityFilter === 'all' || reportItemSeverity(item as unknown as Record<string, any>) === reportSeverityFilter)
    ));
    const filteredRequirements = requirements.filter(item => (
        (reportStatusFilter === 'all' || reportItemReviewState(item as unknown as Record<string, any>, 'requirement') === reportStatusFilter) &&
        (reportSeverityFilter === 'all' || reportItemSeverity(item as unknown as Record<string, any>) === reportSeverityFilter)
    ));
    const unimportedRequirements = requirements.filter(item => !item.imported_requirement_id && !item.imported_requirement_code);
    const pages = report.pages_checked || [];
    const evidence = report.evidence || [];
    const tabs: { key: CustomResultTab; label: string }[] = [
        { key: 'overview', label: 'Overview' },
        { key: 'findings', label: `Findings ${findings.length}` },
        { key: 'test_ideas', label: `Test Ideas ${testIdeas.length}` },
        { key: 'requirements', label: `Requirements ${requirements.length}` },
        { key: 'evidence', label: `Evidence ${evidence.length}` },
        { key: 'raw', label: 'Raw Output' },
    ];
    const basePrompt = `Analyze custom agent run ${run.id} (${run.config?.agent_name || 'Custom Agent'}). Focus on findings, test ideas, and useful follow-up actions.`;
    const selectedTabIndex = tabs.findIndex(tab => tab.key === activeTab);
    const handleReportTabKeyDown = (event: React.KeyboardEvent<HTMLButtonElement>) => {
        if (!['ArrowRight', 'ArrowDown', 'ArrowLeft', 'ArrowUp', 'Home', 'End'].includes(event.key)) return;
        event.preventDefault();
        const lastIndex = tabs.length - 1;
        const nextIndex = event.key === 'Home'
            ? 0
            : event.key === 'End'
            ? lastIndex
            : event.key === 'ArrowRight' || event.key === 'ArrowDown'
            ? (selectedTabIndex + 1) % tabs.length
            : (selectedTabIndex - 1 + tabs.length) % tabs.length;
        onTabChange(tabs[nextIndex].key);
        window.requestAnimationFrame(() => {
            document.getElementById(`agents-report-tab-${tabs[nextIndex].key}`)?.focus();
        });
    };

    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
            <AgentRunCapturePanel activeRun={run} mode="recording" />

            <div style={{ padding: '1rem', background: 'var(--surface-hover)', borderRadius: '8px', border: '1px solid var(--border)' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: '1rem', alignItems: 'flex-start', flexWrap: 'wrap' }}>
                    <div style={{ minWidth: 0 }}>
                        <h3 style={{ fontWeight: 700, fontSize: '1rem', margin: '0 0 0.35rem' }}>
                            {run.config?.agent_name || 'Custom Agent'}
                        </h3>
                        <p style={{ margin: 0, color: 'var(--text-secondary)', fontSize: '0.85rem' }}>
                            {run.result?.duration_seconds ? `Completed in ${run.result.duration_seconds.toFixed(1)} seconds` : 'Completed'}
                            {report.parse_status ? ` · ${report.parse_status} report` : ''}
                        </p>
                    </div>
                    <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
                        <button
                            type="button"
                            onClick={() => onEditOverview(report)}
                            style={{ border: '1px solid var(--border)', background: 'var(--background)', color: 'var(--text)', borderRadius: '6px', padding: '0.45rem 0.7rem', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '0.4rem', fontSize: '0.82rem', fontWeight: 600 }}
                        >
                            <Pencil size={14} /> Edit Report Summary
                        </button>
                        <button
                            type="button"
                            onClick={() => onAskAssistant(basePrompt)}
                            style={{ border: '1px solid var(--border)', background: 'var(--background)', color: 'var(--text)', borderRadius: '6px', padding: '0.45rem 0.7rem', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '0.4rem', fontSize: '0.82rem', fontWeight: 600 }}
                        >
                            <MessageSquare size={14} /> Ask Assistant
                        </button>
                    </div>
                </div>
                {report.summary && (
                    <p style={{ margin: '0.85rem 0 0', color: 'var(--text)', lineHeight: 1.55, fontSize: '0.92rem' }}>
                        {report.summary}
                    </p>
                )}
                {partialReason && (
                    <div data-testid="custom-agent-partial-reason" style={{ marginTop: '0.85rem', padding: '0.75rem 0.85rem', border: '1px solid rgba(251, 191, 36, 0.28)', borderRadius: '8px', background: 'var(--warning-muted)', color: 'var(--text-secondary)', display: 'flex', gap: '0.5rem', alignItems: 'flex-start', fontSize: '0.84rem', lineHeight: 1.45 }}>
                        <AlertTriangle size={15} style={{ color: 'var(--warning)', marginTop: '0.1rem', flexShrink: 0 }} />
                        <span>{partialReason}</span>
                    </div>
                )}
            </div>

            <div role="tablist" aria-label="Report sections" style={{ display: 'flex', gap: '0.4rem', flexWrap: 'wrap', borderBottom: '1px solid var(--border)', paddingBottom: '0.6rem' }}>
                {tabs.map(tab => (
                    <button
                        key={tab.key}
                        id={`agents-report-tab-${tab.key}`}
                        type="button"
                        role="tab"
                        aria-selected={activeTab === tab.key}
                        aria-controls={`agents-report-panel-${tab.key}`}
                        tabIndex={activeTab === tab.key ? 0 : -1}
                        onKeyDown={handleReportTabKeyDown}
                        onClick={() => onTabChange(tab.key)}
                        style={{
                            border: '1px solid var(--border)',
                            background: activeTab === tab.key ? 'var(--primary-glow)' : 'var(--background)',
                            color: activeTab === tab.key ? 'var(--primary)' : 'var(--text-secondary)',
                            borderRadius: '6px',
                            padding: '0.4rem 0.65rem',
                            cursor: 'pointer',
                            fontSize: '0.8rem',
                            fontWeight: 600,
                        }}
                    >
                        {tab.label}
                    </button>
                ))}
            </div>

            {activeTab !== 'overview' && activeTab !== 'raw' && activeTab !== 'evidence' && (
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))', gap: '0.65rem', padding: '0.75rem', border: '1px solid var(--border)', borderRadius: '8px', background: 'var(--surface-hover)' }}>
                    <label style={{ display: 'grid', gap: '0.35rem', fontSize: '0.78rem', fontWeight: 700 }}>
                        Review state
                        <select
                            value={reportStatusFilter}
                            onChange={event => onReportStatusFilterChange(event.target.value as ReportReviewFilter)}
                            style={{ minHeight: 36, borderRadius: '6px', border: '1px solid var(--input-border)', background: 'var(--input-bg)', color: 'var(--text)', padding: '0.4rem 0.55rem' }}
                        >
                            <option value="all">All review states</option>
                            <option value="needs_action">Needs action</option>
                            <option value="unreviewed">Unreviewed</option>
                            <option value="imported">Imported</option>
                            <option value="spec_created">Spec created</option>
                        </select>
                    </label>
                    <label style={{ display: 'grid', gap: '0.35rem', fontSize: '0.78rem', fontWeight: 700 }}>
                        Severity or priority
                        <select
                            value={reportSeverityFilter}
                            onChange={event => onReportSeverityFilterChange(event.target.value)}
                            style={{ minHeight: 36, borderRadius: '6px', border: '1px solid var(--input-border)', background: 'var(--input-bg)', color: 'var(--text)', padding: '0.4rem 0.55rem' }}
                        >
                            <option value="all">All severities</option>
                            <option value="critical">Critical</option>
                            <option value="high">High</option>
                            <option value="medium">Medium</option>
                            <option value="low">Low</option>
                            <option value="info">Info</option>
                        </select>
                    </label>
                </div>
            )}

            {activeTab === 'overview' && (
                <div id="agents-report-panel-overview" role="tabpanel" aria-labelledby="agents-report-tab-overview" style={{ display: 'grid', gap: '1rem' }}>
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: '0.75rem' }}>
                        {[
                            { label: 'Pages Checked', value: pages.length, icon: Eye },
                            { label: 'Findings', value: findings.length, icon: Bug },
                            { label: 'Test Ideas', value: testIdeas.length, icon: Lightbulb },
                            { label: 'Requirements', value: requirements.length, icon: CheckCircle2 },
                            { label: 'Tool Calls', value: run.result?.tool_calls?.length || 0, icon: Wrench },
                        ].map(item => {
                            const Icon = item.icon;
                            return (
                                <div key={item.label} style={{ padding: '0.9rem', border: '1px solid var(--border)', borderRadius: '8px', background: 'var(--background)' }}>
                                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.45rem', color: 'var(--text-secondary)', fontSize: '0.75rem', marginBottom: '0.45rem' }}>
                                        <Icon size={14} /> {item.label}
                                    </div>
                                    <div style={{ fontWeight: 800, fontSize: '1.4rem' }}>{item.value}</div>
                                </div>
                            );
                        })}
                    </div>
                    {report.scope && (
                        <div style={{ padding: '0.9rem', border: '1px solid var(--border)', borderRadius: '8px', background: 'var(--background)' }}>
                            <div style={{ fontWeight: 700, fontSize: '0.85rem', marginBottom: '0.35rem' }}>Scope</div>
                            <p style={{ margin: 0, color: 'var(--text-secondary)', fontSize: '0.85rem', lineHeight: 1.5 }}>{report.scope}</p>
                        </div>
                    )}
                    {pages.length > 0 && (
                        <div style={{ border: '1px solid var(--border)', borderRadius: '8px', overflow: 'hidden', background: 'var(--background)' }}>
                            <div style={{ padding: '0.7rem 0.9rem', borderBottom: '1px solid var(--border)', fontWeight: 700, fontSize: '0.85rem' }}>Pages Checked</div>
                            {pages.slice(0, 12).map((page, i) => (
                                <div key={`${page.url}-${i}`} style={{ padding: '0.65rem 0.9rem', borderBottom: i === Math.min(pages.length, 12) - 1 ? 'none' : '1px solid var(--border)', display: 'grid', gridTemplateColumns: '1fr auto', gap: '0.8rem', fontSize: '0.82rem' }}>
                                    <span style={{ overflowWrap: 'anywhere' }}>{page.url}</span>
                                    <span style={{ color: reportStatusColor(page.status), fontWeight: 700, textTransform: 'capitalize' }}>{page.status || 'unknown'}</span>
                                </div>
                            ))}
                        </div>
                    )}
                </div>
            )}

            {activeTab === 'findings' && (
                <div id="agents-report-panel-findings" role="tabpanel" aria-labelledby="agents-report-tab-findings" style={{ display: 'grid', gap: '0.75rem' }}>
                    {filteredFindings.length === 0 ? (
                        <EmptyReportState text="No structured findings were reported." />
                    ) : filteredFindings.map(finding => (
                        <div key={finding.id} style={{ padding: '0.9rem', border: '1px solid var(--border)', borderRadius: '8px', background: 'var(--background)' }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', gap: '0.75rem', flexWrap: 'wrap', marginBottom: '0.45rem' }}>
                                <div style={{ fontWeight: 700, fontSize: '0.92rem' }}>{finding.id}: {finding.title}</div>
                                <span style={{ color: severityColor(finding.severity), fontWeight: 800, fontSize: '0.78rem', textTransform: 'uppercase' }}>{finding.severity || 'info'}</span>
                            </div>
                            {finding.page && <div style={{ fontSize: '0.78rem', color: 'var(--primary)', marginBottom: '0.35rem', overflowWrap: 'anywhere' }}>{finding.page}</div>}
                            {finding.description && <p style={{ margin: '0 0 0.45rem', color: 'var(--text-secondary)', fontSize: '0.85rem', lineHeight: 1.5 }}>{finding.description}</p>}
                            {finding.evidence && <p style={{ margin: '0 0 0.7rem', color: 'var(--text)', fontSize: '0.82rem', lineHeight: 1.45 }}><strong>Evidence:</strong> {finding.evidence}</p>}
                            <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
                                <ReportActionButton onClick={() => onEditReportItem(finding, 'finding')} label={`Edit finding ${finding.id}`} icon={Pencil} />
                                <ReportActionButton onClick={() => onAskAssistant(itemPrompt(run, finding, 'finding'))} label="Use in Assistant" icon={MessageSquare} />
                                <ReportActionButton onClick={() => onCreateSpecFromReport(finding, 'finding')} label="Create Spec" icon={FileText} />
                                <ReportActionButton onClick={() => onAskAssistant(`Start a follow-up custom agent from finding ${finding.id} in run ${run.id}. Verify whether this issue still reproduces and collect evidence. Use approval before starting the agent.`)} label="Follow Up Agent" icon={Bot} />
                            </div>
                        </div>
                    ))}
                </div>
            )}

            {activeTab === 'test_ideas' && (
                <div id="agents-report-panel-test_ideas" role="tabpanel" aria-labelledby="agents-report-tab-test_ideas" style={{ display: 'grid', gap: '0.75rem' }}>
                    {filteredTestIdeas.length === 0 ? (
                        <EmptyReportState text="No structured test ideas were reported." />
                    ) : filteredTestIdeas.map(idea => (
                        <div key={idea.id} style={{ padding: '0.9rem', border: '1px solid var(--border)', borderRadius: '8px', background: 'var(--background)' }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', gap: '0.75rem', flexWrap: 'wrap', marginBottom: '0.45rem' }}>
                                <div style={{ fontWeight: 700, fontSize: '0.92rem' }}>{idea.id}: {idea.title}</div>
                                <span style={{ color: severityColor(idea.priority), fontWeight: 800, fontSize: '0.78rem', textTransform: 'uppercase' }}>{idea.priority || 'medium'}</span>
                            </div>
                            {idea.page && <div style={{ fontSize: '0.78rem', color: 'var(--primary)', marginBottom: '0.35rem', overflowWrap: 'anywhere' }}>{idea.page}</div>}
                            {idea.steps && idea.steps.length > 0 && (
                                <ol style={{ margin: '0.35rem 0 0.55rem 1.15rem', color: 'var(--text-secondary)', fontSize: '0.84rem', lineHeight: 1.45 }}>
                                    {idea.steps.map((step, i) => <li key={`${idea.id}-step-${i}`}>{step}</li>)}
                                </ol>
                            )}
                            {idea.expected && <p style={{ margin: '0 0 0.7rem', color: 'var(--text)', fontSize: '0.82rem' }}><strong>Expected:</strong> {idea.expected}</p>}
                            <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
                                <ReportActionButton onClick={() => onEditReportItem(idea, 'test_idea')} label={`Edit test idea ${idea.id}`} icon={Pencil} />
                                <ReportActionButton onClick={() => onAskAssistant(itemPrompt(run, idea, 'test idea'))} label="Use in Assistant" icon={MessageSquare} />
                                <ReportActionButton onClick={() => onCreateSpecFromReport(idea, 'test_idea')} label="Create Spec" icon={FileText} />
                            </div>
                        </div>
                    ))}
                </div>
            )}

            {activeTab === 'requirements' && (
                <div id="agents-report-panel-requirements" role="tabpanel" aria-labelledby="agents-report-tab-requirements" style={{ display: 'grid', gap: '0.75rem' }}>
                    {importError && (
                        <div style={{ padding: '0.75rem 0.9rem', border: '1px solid var(--danger)', borderRadius: '8px', color: 'var(--danger)', background: 'var(--danger-muted)', fontSize: '0.84rem' }}>
                            {importError}
                        </div>
                    )}
                    {requirements.length > 0 && (
                        <div style={{ display: 'flex', justifyContent: 'space-between', gap: '0.75rem', flexWrap: 'wrap', alignItems: 'center' }}>
                            <div style={{ color: 'var(--text-secondary)', fontSize: '0.82rem' }}>
                                {unimportedRequirements.length} candidate{unimportedRequirements.length === 1 ? '' : 's'} ready for review import.
                            </div>
                            <ReportActionButton
                                onClick={() => onImportRequirements()}
                                label={importingRequirementIds.includes('__all__') ? 'Importing...' : 'Import Requirements'}
                                icon={CheckCircle2}
                                disabled={unimportedRequirements.length === 0 || importingRequirementIds.includes('__all__')}
                            />
                        </div>
                    )}
                    {filteredRequirements.length === 0 ? (
                        <EmptyReportState text="No structured requirements were reported." />
                    ) : filteredRequirements.map(requirement => {
                        const imported = Boolean(requirement.imported_requirement_id || requirement.imported_requirement_code);
                        const pending = importingRequirementIds.includes('__all__') || importingRequirementIds.includes(requirement.id);
                        return (
                            <div key={requirement.id} style={{ padding: '0.9rem', border: '1px solid var(--border)', borderRadius: '8px', background: 'var(--background)' }}>
                                <div style={{ display: 'flex', justifyContent: 'space-between', gap: '0.75rem', flexWrap: 'wrap', marginBottom: '0.45rem' }}>
                                    <div style={{ fontWeight: 700, fontSize: '0.92rem' }}>{requirement.id}: {requirement.title}</div>
                                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.45rem', flexWrap: 'wrap' }}>
                                        {requirement.category && <span style={{ color: 'var(--text-secondary)', fontWeight: 700, fontSize: '0.74rem', textTransform: 'uppercase' }}>{requirement.category}</span>}
                                        <span style={{ color: severityColor(requirement.priority), fontWeight: 800, fontSize: '0.78rem', textTransform: 'uppercase' }}>{requirement.priority || 'medium'}</span>
                                    </div>
                                </div>
                                {requirement.page && <div style={{ fontSize: '0.78rem', color: 'var(--primary)', marginBottom: '0.35rem', overflowWrap: 'anywhere' }}>{requirement.page}</div>}
                                {requirement.description && <p style={{ margin: '0 0 0.45rem', color: 'var(--text-secondary)', fontSize: '0.85rem', lineHeight: 1.5 }}>{requirement.description}</p>}
                                {requirement.acceptance_criteria && requirement.acceptance_criteria.length > 0 && (
                                    <ul style={{ margin: '0.35rem 0 0.55rem 1.15rem', color: 'var(--text-secondary)', fontSize: '0.84rem', lineHeight: 1.45 }}>
                                        {requirement.acceptance_criteria.map((criterion, i) => <li key={`${requirement.id}-criterion-${i}`}>{criterion}</li>)}
                                    </ul>
                                )}
                                {requirement.evidence && <p style={{ margin: '0 0 0.7rem', color: 'var(--text)', fontSize: '0.82rem', lineHeight: 1.45 }}><strong>Evidence:</strong> {requirement.evidence}</p>}
                                {imported && (
                                    <div style={{ marginBottom: '0.7rem', fontSize: '0.82rem', color: 'var(--success)', display: 'flex', alignItems: 'center', gap: '0.4rem', flexWrap: 'wrap' }}>
                                        <CheckCircle2 size={14} />
                                        Imported as
                                        <Link href={`/requirements${requirement.imported_requirement_id ? `?highlight=${requirement.imported_requirement_id}` : ''}`} style={{ color: 'var(--primary)', fontWeight: 700 }}>
                                            {requirement.imported_requirement_code || `REQ-${requirement.imported_requirement_id}`}
                                        </Link>
                                    </div>
                                )}
                                <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
                                    <ReportActionButton
                                        onClick={() => onEditReportItem(requirement, 'requirement')}
                                        label={`Edit requirement ${requirement.id}`}
                                        icon={Pencil}
                                        disabled={imported}
                                    />
                                    <ReportActionButton onClick={() => onAskAssistant(`Review candidate requirement ${requirement.id} from custom agent run ${run.id}: ${requirement.title}`)} label="Use in Assistant" icon={MessageSquare} />
                                    <ReportActionButton
                                        onClick={() => onImportRequirements([requirement.id])}
                                        label={pending ? 'Importing...' : imported ? 'Imported' : 'Import'}
                                        icon={CheckCircle2}
                                        disabled={imported || pending}
                                    />
                                </div>
                            </div>
                        );
                    })}
                </div>
            )}

            {activeTab === 'evidence' && (
                <div id="agents-report-panel-evidence" role="tabpanel" aria-labelledby="agents-report-tab-evidence" style={{ display: 'grid', gap: '0.6rem' }}>
                    {evidence.length === 0 ? (
                        <EmptyReportState text="No structured evidence was reported." />
                    ) : evidence.map((item, i) => (
                        <div key={item.id || `${item.label}-${i}`} style={{ padding: '0.75rem 0.9rem', border: '1px solid var(--border)', borderRadius: '8px', background: 'var(--background)', display: 'grid', gap: '0.3rem' }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', gap: '0.75rem', fontSize: '0.84rem' }}>
                                <strong>{item.label || item.id || `Evidence ${i + 1}`}</strong>
                                <span style={{ color: 'var(--text-secondary)', textTransform: 'capitalize' }}>{item.type || 'note'}</span>
                            </div>
                            {item.value && (
                                item.value.startsWith('/api/') ? (
                                    <a href={`${API_BASE}${item.value}`} target="_blank" rel="noreferrer" style={{ color: 'var(--primary)', fontSize: '0.8rem', overflowWrap: 'anywhere' }}>{item.value}</a>
                                ) : (
                                    <span style={{ color: 'var(--text-secondary)', fontSize: '0.8rem', overflowWrap: 'anywhere' }}>{item.value}</span>
                                )
                            )}
                        </div>
                    ))}
                </div>
            )}

            {activeTab === 'raw' && (
                <div id="agents-report-panel-raw" role="tabpanel" aria-labelledby="agents-report-tab-raw" style={{ display: 'grid', gap: '1rem' }}>
                    <div style={{ background: '#111827', padding: '1rem', borderRadius: '8px', border: '1px solid var(--border)' }}>
                        <pre style={{ whiteSpace: 'pre-wrap', fontFamily: 'monospace', fontSize: '0.84rem', color: '#e5e7eb', margin: 0 }}>
                            {run.result?.output || JSON.stringify(run.result, null, 2)}
                        </pre>
                    </div>
                    {run.result?.tool_calls?.length > 0 && (
                        <details>
                            <summary style={{ cursor: 'pointer', fontWeight: 600, fontSize: '0.9rem' }}>
                                Tool Calls ({run.result.tool_calls.length})
                            </summary>
                            <div style={{ marginTop: '0.5rem', display: 'grid', gap: '0.4rem' }}>
                                {run.result.tool_calls.map((call: any, i: number) => (
                                    <div key={`${call.name}-${i}`} style={{ padding: '0.5rem', background: 'var(--surface-hover)', border: '1px solid var(--border)', borderRadius: '6px', fontSize: '0.78rem' }}>
                                        <strong>{call.name}</strong>
                                        {call.duration_ms !== undefined && <span style={{ color: 'var(--text-secondary)' }}> · {Math.round(call.duration_ms)}ms</span>}
                                        {call.error && <div style={{ color: 'var(--danger)', marginTop: '0.25rem' }}>{call.error}</div>}
                                    </div>
                                ))}
                            </div>
                        </details>
                    )}
                </div>
            )}
        </div>
    );
}

export function EmptyReportState({ text }: { text: string }) {
    return (
        <div style={{ padding: '1.25rem', border: '1px solid var(--border)', borderRadius: '8px', background: 'var(--background)', color: 'var(--text-secondary)', textAlign: 'center', fontSize: '0.86rem' }}>
            {text}
        </div>
    );
}

export function ReportActionButton({ onClick, label, icon: Icon, disabled = false }: { onClick: () => void | Promise<void>; label: string; icon: any; disabled?: boolean }) {
    const handleClick = async () => {
        try {
            await onClick();
        } catch (e: unknown) {
            const message = e instanceof Error ? e.message : 'Action failed. Please try again.';
            toast.error(message);
        }
    };

    return (
        <button
            type="button"
            onClick={handleClick}
            disabled={disabled}
            style={{ border: '1px solid var(--border)', background: 'var(--surface-hover)', color: disabled ? 'var(--text-secondary)' : 'var(--text)', borderRadius: '6px', padding: '0.38rem 0.6rem', cursor: disabled ? 'not-allowed' : 'pointer', display: 'flex', alignItems: 'center', gap: '0.35rem', fontSize: '0.78rem', fontWeight: 600, opacity: disabled ? 0.65 : 1 }}
        >
            <Icon size={13} /> {label}
        </button>
    );
}

export function TraceJsonBlock({ title, value }: { title: string; value: any }) {
    if (value === undefined || value === null || value === '') return null;
    return (
        <details style={{ border: '1px solid var(--border)', borderRadius: '6px', background: 'var(--surface-hover)', overflow: 'hidden' }}>
            <summary style={{ cursor: 'pointer', padding: '0.55rem 0.7rem', fontWeight: 700, fontSize: '0.78rem' }}>{title}</summary>
            <pre style={{ margin: 0, padding: '0.7rem', borderTop: '1px solid var(--border)', overflowX: 'auto', whiteSpace: 'pre-wrap', fontSize: '0.74rem', lineHeight: 1.45, color: 'var(--text-secondary)' }}>
                {typeof value === 'string' ? value : JSON.stringify(value, null, 2)}
            </pre>
        </details>
    );
}

export function TracePill({ label, value }: { label: string; value: any }) {
    if (value === undefined || value === null || value === '') return null;
    return (
        <span style={{ display: 'inline-flex', gap: '0.35rem', alignItems: 'center', padding: '0.32rem 0.48rem', border: '1px solid var(--border)', borderRadius: '6px', background: 'var(--surface-hover)', fontSize: '0.75rem', maxWidth: '100%' }}>
            <strong style={{ color: 'var(--text-secondary)' }}>{label}</strong>
            <span style={{ overflowWrap: 'anywhere' }}>{String(value)}</span>
        </span>
    );
}

export function AgentRunNotesPanel({
    run,
    events,
    supplementalNotes = [],
}: {
    run: AgentRun;
    events: AgentRunEvent[];
    supplementalNotes?: AgentRunNote[];
}) {
    const [backfilledNotes, setBackfilledNotes] = useState<AgentRunNote[]>([]);
    const [search, setSearch] = useState('');
    const [noteType, setNoteType] = useState('all');
    const [level, setLevel] = useState('all');
    const [source, setSource] = useState('all');
    const [actionableOnly, setActionableOnly] = useState(false);
    const [sort, setSort] = useState<'newest' | 'chronological'>('newest');

    useEffect(() => {
        const controller = new AbortController();
        setBackfilledNotes([]);
        fetchAgentRunNotes(run.id, { limit: 200, projectId: run.project_id, signal: controller.signal })
            .then(setBackfilledNotes)
            .catch(() => {
                if (!controller.signal.aborted) setBackfilledNotes([]);
            });
        return () => controller.abort();
    }, [run.id, run.project_id]);

    const notes = useMemo(() => {
        const liveTail = Array.isArray(run.progress?.live_notes_tail) ? run.progress.live_notes_tail as AgentRunNote[] : [];
        const eventNotes = events.map(agentRunNoteFromEvent).filter(Boolean) as AgentRunNote[];
        const runtimeNotes = mergeAgentRunNotes(mergeAgentRunNotes(backfilledNotes, liveTail), eventNotes);
        return mergeAgentRunNotes(runtimeNotes, supplementalNotes);
    }, [backfilledNotes, events, run.progress?.live_notes_tail, supplementalNotes]);

    const noteTypes = useMemo(() => Array.from(new Set(notes.map(note => String(note.note_type || 'observation')))).sort(), [notes]);
    const levels = useMemo(() => Array.from(new Set(notes.map(note => String(note.level || 'info')))).sort(), [notes]);
    const sources = useMemo(() => Array.from(new Set(notes.map(note => String(note.source || 'runtime')))).sort(), [notes]);
    const visibleNotes = useMemo(() => filterAgentRunNotes(notes, {
        search,
        noteType,
        level,
        source,
        actionableOnly,
        sort,
    }), [actionableOnly, level, noteType, notes, search, sort, source]);

    return (
        <section style={{ display: 'grid', gap: '0.75rem', padding: '1rem', border: '1px solid var(--border)', borderRadius: '8px', background: 'var(--background)' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '0.75rem', flexWrap: 'wrap' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.45rem', minWidth: 0 }}>
                    <MessageSquare size={16} style={{ color: 'var(--primary)' }} />
                    <strong>Agent Notes</strong>
                    <span style={{ color: 'var(--text-secondary)', fontSize: '0.78rem' }}>{visibleNotes.length}/{notes.length}</span>
                </div>
                <label style={{ display: 'inline-flex', alignItems: 'center', gap: '0.35rem', color: 'var(--text-secondary)', fontSize: '0.78rem', fontWeight: 650 }}>
                    <input type="checkbox" checked={actionableOnly} onChange={event => setActionableOnly(event.target.checked)} />
                    Actionable
                </label>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: '0.5rem' }}>
                <div style={{ position: 'relative', minWidth: 0 }}>
                    <Search size={14} style={{ position: 'absolute', left: '0.6rem', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-secondary)' }} />
                    <Input value={search} onChange={event => setSearch(event.target.value)} placeholder="Search notes" style={{ paddingLeft: '1.9rem' }} />
                </div>
                <select value={noteType} onChange={event => setNoteType(event.target.value)} style={{ minWidth: 0, border: '1px solid var(--border)', borderRadius: '6px', padding: '0.48rem 0.55rem', background: 'var(--surface)', color: 'var(--text)' }}>
                    <option value="all">All types</option>
                    {noteTypes.map(type => <option key={type} value={type}>{type.replaceAll('_', ' ')}</option>)}
                </select>
                <select value={level} onChange={event => setLevel(event.target.value)} style={{ minWidth: 0, border: '1px solid var(--border)', borderRadius: '6px', padding: '0.48rem 0.55rem', background: 'var(--surface)', color: 'var(--text)' }}>
                    <option value="all">All levels</option>
                    {levels.map(item => <option key={item} value={item}>{item}</option>)}
                </select>
                <select value={source} onChange={event => setSource(event.target.value)} style={{ minWidth: 0, border: '1px solid var(--border)', borderRadius: '6px', padding: '0.48rem 0.55rem', background: 'var(--surface)', color: 'var(--text)' }}>
                    <option value="all">All sources</option>
                    {sources.map(item => <option key={item} value={item}>{item}</option>)}
                </select>
                <select value={sort} onChange={event => setSort(event.target.value as 'newest' | 'chronological')} style={{ minWidth: 0, border: '1px solid var(--border)', borderRadius: '6px', padding: '0.48rem 0.55rem', background: 'var(--surface)', color: 'var(--text)' }}>
                    <option value="newest">Newest</option>
                    <option value="chronological">Chronological</option>
                </select>
            </div>

            {visibleNotes.length === 0 ? (
                <div style={{ padding: '1rem', border: '1px dashed var(--border)', borderRadius: '8px', color: 'var(--text-secondary)', background: 'var(--surface-hover)' }}>
                    No agent notes recorded for this run.
                </div>
            ) : (
                <div style={{ display: 'grid', gap: '0.55rem', maxHeight: '360px', overflowY: 'auto', paddingRight: '0.1rem' }}>
                    {visibleNotes.map(note => (
                        <article key={`${note.sequence}-${note.id}`} style={{ display: 'grid', gap: '0.45rem', padding: '0.75rem', border: '1px solid var(--border)', borderRadius: '8px', background: 'var(--surface)' }}>
                            <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: '0.75rem' }}>
                                <div style={{ minWidth: 0 }}>
                                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', flexWrap: 'wrap' }}>
                                        <strong style={{ overflowWrap: 'anywhere' }}>{note.title}</strong>
                                        <span style={{ padding: '0.16rem 0.38rem', border: '1px solid var(--border)', borderRadius: '999px', color: 'var(--text-secondary)', fontSize: '0.68rem', textTransform: 'capitalize' }}>{String(note.note_type).replaceAll('_', ' ')}</span>
                                        <span style={{ color: note.level === 'error' ? 'var(--danger)' : note.level === 'warning' ? 'var(--warning)' : 'var(--text-secondary)', fontSize: '0.72rem', fontWeight: 700 }}>{note.level}</span>
                                    </div>
                                    {note.body && <p style={{ margin: '0.35rem 0 0', color: 'var(--text-secondary)', fontSize: '0.82rem', lineHeight: 1.45, overflowWrap: 'anywhere' }}>{note.body}</p>}
                                </div>
                                <span style={{ color: 'var(--text-secondary)', fontSize: '0.72rem', whiteSpace: 'nowrap' }}>#{note.sequence}</span>
                            </div>
                            <div style={{ display: 'flex', gap: '0.4rem', flexWrap: 'wrap', color: 'var(--text-secondary)', fontSize: '0.72rem' }}>
                                {note.source && <span>Source: {note.source}</span>}
                                {note.tool_name && <span>Tool: {formatToolName(note.tool_name)}</span>}
                                {note.confidence !== null && note.confidence !== undefined && <span>Confidence: {Math.round(Number(note.confidence) * 100)}%</span>}
                                {note.url && <a href={note.url} target="_blank" rel="noreferrer" style={{ color: 'var(--primary)', overflowWrap: 'anywhere' }}>{note.url}</a>}
                                {note.artifact_path && <span style={{ overflowWrap: 'anywhere' }}>Artifact: {note.artifact_path}</span>}
                            </div>
                            {(note.tags || []).length > 0 && (
                                <div style={{ display: 'flex', gap: '0.35rem', flexWrap: 'wrap' }}>
                                    {(note.tags || []).map(tag => (
                                        <span key={tag} style={{ padding: '0.14rem 0.34rem', borderRadius: '6px', background: 'var(--surface-hover)', color: 'var(--text-secondary)', fontSize: '0.68rem' }}>{tag}</span>
                                    ))}
                                </div>
                            )}
                        </article>
                    ))}
                </div>
            )}
        </section>
    );
}

export function AgentRunObservabilityPanel({
    run,
    events,
    supplementalNotes = [],
    trace,
    traceLoading = false,
    traceSearch = '',
    onTraceSearch,
    traceSpanType = '',
    onTraceSpanType,
    onExportTrace,
    activeTraceTab = 'timeline',
    onTraceTabChange,
}: {
    run: AgentRun;
    events: AgentRunEvent[];
    supplementalNotes?: AgentRunNote[];
    trace?: AgentTraceBundle | null;
    traceLoading?: boolean;
    traceSearch?: string;
    onTraceSearch?: (value: string) => void;
    traceSpanType?: string;
    onTraceSpanType?: (value: string) => void;
    onExportTrace?: () => void;
    activeTraceTab?: TraceTab;
    onTraceTabChange?: (value: TraceTab) => void;
}) {
    const health = run.health || {};
    const temporal = run.temporal || {};
    const partialReason = agentRunPartialReason(run);
    const [internalTraceTab, setInternalTraceTab] = useState<TraceTab>(activeTraceTab);
    const selectedTraceTab = onTraceTabChange ? activeTraceTab : internalTraceTab;
    const changeTraceTab = (tab: TraceTab) => {
        if (onTraceTabChange) onTraceTabChange(tab);
        else setInternalTraceTab(tab);
    };
    const traceSpans = useMemo(() => trace?.spans || [], [trace?.spans]);
    const searchableTraceSpans = useMemo(() => traceSpans.map(span => ({
        span,
        searchText: [
            span.name,
            span.message,
            span.span_type,
            span.tool_name,
            span.content_hash,
            span.payload ? JSON.stringify(span.payload) : '',
            span.input_preview ? JSON.stringify(span.input_preview) : '',
            span.output_preview ? JSON.stringify(span.output_preview) : '',
        ].join(' ').toLowerCase(),
    })), [traceSpans]);
    const filteredSpans = useMemo(() => searchableTraceSpans.filter(({ span, searchText }) => {
        if (traceSpanType && span.span_type !== traceSpanType) return false;
        if (!traceSearch.trim()) return true;
        const query = traceSearch.toLowerCase();
        return searchText.includes(query);
    }).map(item => item.span), [searchableTraceSpans, traceSearch, traceSpanType]);
    const recentEvents = events.slice(-12).reverse();
    const visibleSpans = filteredSpans.slice(-80).reverse();
    const toolSpans = filteredSpans.filter(span => span.span_type === 'tool_call' || span.span_type === 'tool_result');
    const allToolEvents = useMemo(() => events.filter(event => event.event_type === 'tool_call' || event.event_type === 'browser_action'), [events]);
    const toolEvents = useMemo(() => allToolEvents.filter(event => {
        if (!traceSearch.trim()) return true;
        const query = traceSearch.toLowerCase();
        return [
            event.event_type,
            event.message,
            event.payload ? JSON.stringify(event.payload) : '',
        ].join(' ').toLowerCase().includes(query);
    }), [allToolEvents, traceSearch]);
    const spanTypes = Array.from(new Set(traceSpans.map(span => span.span_type))).sort();
    const logArtifacts = sortArtifactsByModifiedAt((run.artifacts || []).filter(artifact => artifact.type === 'log'));
    const traceArtifacts = trace?.artifacts || [];
    const snapshot = trace?.snapshot;
    const memoryInjections = trace?.memory_injections || [];
    const traceTabs: Array<{ key: TraceTab; label: string; icon: any }> = [
        { key: 'notes', label: 'Notes', icon: MessageSquare },
        { key: 'timeline', label: 'Timeline', icon: Clock },
        { key: 'context', label: 'Context', icon: FileText },
        { key: 'tools', label: 'Tools', icon: Wrench },
        { key: 'memory', label: 'Memory', icon: Database },
        { key: 'runtime', label: 'Runtime', icon: Cpu },
        { key: 'artifacts', label: 'Artifacts', icon: PackageOpen },
    ];
    const copyText = (value: string | null | undefined) => {
        if (!value || typeof navigator === 'undefined') return;
        void navigator.clipboard?.writeText(value);
    };

    return (
        <div style={{ display: 'grid', gap: '0.75rem' }}>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))', gap: '0.65rem' }}>
                {[
                    { label: 'Events', value: health.event_count ?? events.length, icon: List },
                    { label: 'Tool Events', value: Number(health.tool_event_count || 0) > 0 ? health.tool_event_count : allToolEvents.length, icon: Wrench },
                    { label: 'Errors', value: health.error_event_count ?? 0, icon: AlertTriangle },
                    { label: 'Temporal', value: temporal.error ? 'Error' : temporal.workflow_status || (run.temporal_workflow_id ? 'Scheduled' : 'Not linked'), icon: RotateCcw },
                    { label: 'Task', value: run.agent_task_id ? run.agent_task_id.slice(0, 12) : 'Not queued', icon: Terminal },
                ].map(item => {
                    const Icon = item.icon;
                    return (
                        <div key={item.label} style={{ padding: '0.75rem', border: '1px solid var(--border)', borderRadius: '8px', background: 'var(--background)', minWidth: 0 }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '0.35rem', color: 'var(--text-secondary)', fontSize: '0.72rem', marginBottom: '0.35rem', textTransform: 'uppercase' }}>
                                <Icon size={13} /> {item.label}
                            </div>
                            <div style={{ fontWeight: 800, fontSize: '0.95rem', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{item.value}</div>
                        </div>
                    );
                })}
            </div>

            {(run.temporal_workflow_id || temporal.error) && (
                <div style={{ padding: '0.75rem 0.85rem', border: '1px solid var(--border)', borderRadius: '8px', background: 'var(--background)', display: 'grid', gap: '0.35rem', fontSize: '0.8rem' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', gap: '0.75rem', flexWrap: 'wrap' }}>
                        <strong>Temporal workflow</strong>
                        <span style={{ color: temporal.available ? 'var(--success)' : 'var(--text-secondary)', fontWeight: 700 }}>
                            {temporal.workflow_status || (temporal.available ? 'Available' : 'Unknown')}
                        </span>
                    </div>
                    {run.temporal_workflow_id && (
                        <div style={{ color: 'var(--text-secondary)', overflowWrap: 'anywhere' }}>{run.temporal_workflow_id}</div>
                    )}
                    {(temporal.temporal_namespace || temporal.task_queue) && (
                        <div style={{ color: 'var(--text-secondary)', fontSize: '0.74rem', display: 'flex', gap: '0.55rem', flexWrap: 'wrap' }}>
                            {temporal.temporal_namespace && <span>Namespace: {temporal.temporal_namespace}</span>}
                            {temporal.task_queue && <span>Queue: {temporal.task_queue}</span>}
                        </div>
                    )}
                    {temporal.summary && (
                        <div style={{ color: 'var(--text-secondary)', fontSize: '0.74rem', display: 'flex', gap: '0.55rem', flexWrap: 'wrap' }}>
                            <span>Activities: {temporal.summary.total_activities ?? 0}</span>
                            <span>Retries: {temporal.summary.retry_count ?? 0}</span>
                            <span>Failures: {temporal.summary.failed_activities ?? 0}</span>
                        </div>
                    )}
                    {temporal.task_queue_status && (
                        <div style={{ color: 'var(--text-secondary)', fontSize: '0.74rem', display: 'flex', gap: '0.55rem', flexWrap: 'wrap' }}>
                            <span>Workflow pollers: {temporal.task_queue_status.workflow_pollers ?? 0}</span>
                            <span>Activity pollers: {temporal.task_queue_status.activity_pollers ?? 0}</span>
                        </div>
                    )}
                    {(temporal.activities || []).length > 0 && (
                        <div style={{ color: 'var(--text-secondary)', fontSize: '0.74rem', display: 'flex', gap: '0.55rem', flexWrap: 'wrap' }}>
                            {(temporal.activities || []).slice(-3).map((activity, index) => (
                                <span key={`${activity.activity_type}-${index}`}>
                                    {activity.activity_type}: {activity.status}
                                </span>
                            ))}
                        </div>
                    )}
                    {temporal.summary?.last_failure && (
                        <div style={{ color: 'var(--danger)', overflowWrap: 'anywhere' }}>Last failure: {temporal.summary.last_failure}</div>
                    )}
                    {temporal.error && (
                        <div style={{ color: 'var(--warning)', overflowWrap: 'anywhere' }}>{temporal.error}</div>
                    )}
                    {partialReason && (
                        <div data-testid="temporal-app-partial-note" style={{ color: 'var(--warning)', overflowWrap: 'anywhere' }}>
                            Temporal completed; agent result is partial: {partialReason}
                        </div>
                    )}
                    {(temporal.temporal_ui_workflow_url || temporal.temporal_ui_url) && run.temporal_workflow_id && (
                        <a href={temporal.temporal_ui_workflow_url || temporal.temporal_ui_url || '#'} target="_blank" rel="noreferrer" style={{ color: 'var(--primary)', textDecoration: 'none', display: 'inline-flex', alignItems: 'center', gap: '0.3rem', fontWeight: 600 }}>
                            Open Temporal UI <ExternalLink size={13} />
                        </a>
                    )}
                </div>
            )}

            <div style={{ border: '1px solid var(--border)', borderRadius: '8px', overflow: 'hidden', background: 'var(--background)' }}>
                <div style={{ padding: '0.65rem 0.85rem', borderBottom: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', gap: '0.75rem', alignItems: 'center', flexWrap: 'wrap' }}>
                    <div style={{ display: 'flex', gap: '0.35rem', flexWrap: 'wrap' }}>
                        {traceTabs.map(tab => {
                            const Icon = tab.icon;
                            return (
                                <button key={tab.key} type="button" onClick={() => changeTraceTab(tab.key)} style={{ border: '1px solid var(--border)', background: selectedTraceTab === tab.key ? 'var(--primary-glow)' : 'var(--surface-hover)', color: selectedTraceTab === tab.key ? 'var(--primary)' : 'var(--text)', borderRadius: '6px', padding: '0.38rem 0.55rem', cursor: 'pointer', display: 'inline-flex', alignItems: 'center', gap: '0.32rem', fontSize: '0.76rem', fontWeight: 700 }}>
                                    <Icon size={13} /> {tab.label}
                                </button>
                            );
                        })}
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.45rem', flexWrap: 'wrap' }}>
                        {traceLoading && <Loader2 size={14} className="spin" style={{ color: 'var(--primary)' }} />}
                        {onExportTrace && (
                            <button type="button" onClick={onExportTrace} title="Export redacted trace" style={{ border: '1px solid var(--border)', background: 'var(--surface-hover)', color: 'var(--text)', borderRadius: '6px', padding: '0.38rem 0.55rem', cursor: 'pointer', display: 'inline-flex', alignItems: 'center', gap: '0.32rem', fontSize: '0.76rem', fontWeight: 700 }}>
                                <Download size={13} /> Export
                            </button>
                        )}
                    </div>
                </div>

                <div style={{ padding: '0.75rem', display: 'grid', gap: '0.65rem' }}>
                    {(selectedTraceTab === 'timeline' || selectedTraceTab === 'tools') && (
                        <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap', alignItems: 'center' }}>
                            <div style={{ position: 'relative', flex: '1 1 220px' }}>
                                <Search size={13} style={{ position: 'absolute', left: '0.55rem', top: '50%', transform: 'translateY(-50%)', color: 'var(--text-secondary)' }} />
                                <label htmlFor={`agent-trace-search-${run.id}`} className="agents-visually-hidden">Search trace events and spans</label>
                                <input id={`agent-trace-search-${run.id}`} aria-label="Search trace events and spans" value={traceSearch} onChange={event => onTraceSearch?.(event.target.value)} placeholder="Search trace" style={{ width: '100%', padding: '0.42rem 0.55rem 0.42rem 1.8rem', borderRadius: '6px', border: '1px solid var(--input-border)', background: 'var(--input-bg)', color: 'var(--text)', fontSize: '0.78rem' }} />
                            </div>
                            <label htmlFor={`agent-trace-span-type-${run.id}`} className="agents-visually-hidden">Filter trace by span type</label>
                            <select id={`agent-trace-span-type-${run.id}`} aria-label="Filter trace by span type" value={traceSpanType} onChange={event => onTraceSpanType?.(event.target.value)} style={{ padding: '0.42rem 0.55rem', borderRadius: '6px', border: '1px solid var(--input-border)', background: 'var(--input-bg)', color: 'var(--text)', fontSize: '0.78rem' }}>
                                <option value="">All spans</option>
                                {spanTypes.map(type => <option key={type} value={type}>{type.replace(/_/g, ' ')}</option>)}
                            </select>
                        </div>
                    )}

                    {selectedTraceTab === 'notes' && (
                        <AgentRunNotesPanel run={run} events={events} supplementalNotes={supplementalNotes} />
                    )}

                    {selectedTraceTab === 'timeline' && (
                        traceSpans.length > 0 ? (
                            <div style={{ display: 'grid', gap: '0.45rem' }}>
                                {visibleSpans.map(span => (
                                    <details key={span.id} style={{ border: '1px solid var(--border)', borderRadius: '6px', background: 'var(--surface-hover)', overflow: 'hidden' }}>
                                        <summary style={{ cursor: 'pointer', padding: '0.58rem 0.7rem', display: 'grid', gridTemplateColumns: 'auto 1fr auto', gap: '0.6rem', alignItems: 'center', fontSize: '0.8rem' }}>
                                            <span style={{ color: span.level === 'error' ? 'var(--danger)' : span.level === 'warning' ? 'var(--warning)' : 'var(--primary)', fontWeight: 800 }}>#{span.sequence}</span>
                                            <span style={{ minWidth: 0 }}>
                                                <strong style={{ textTransform: 'capitalize' }}>{span.name || span.span_type.replace(/_/g, ' ')}</strong>
                                                <span style={{ color: 'var(--text-secondary)' }}> · {span.span_type.replace(/_/g, ' ')}</span>
                                                {span.tool_name && <span style={{ color: 'var(--text-secondary)' }}> · {formatToolName(span.tool_name)}</span>}
                                            </span>
                                            <span style={{ color: 'var(--text-secondary)', whiteSpace: 'nowrap' }}>{new Date(span.created_at).toLocaleTimeString()}</span>
                                        </summary>
                                        <div style={{ padding: '0 0.7rem 0.7rem', display: 'grid', gap: '0.45rem' }}>
                                            {span.message && <div style={{ color: 'var(--text-secondary)', fontSize: '0.78rem', overflowWrap: 'anywhere' }}>{span.message}</div>}
                                            <div style={{ display: 'flex', gap: '0.35rem', flexWrap: 'wrap' }}>
                                                <TracePill label="duration" value={span.duration_ms != null ? `${Math.round(span.duration_ms)}ms` : null} />
                                                <TracePill label="hash" value={span.content_hash?.slice(0, 16)} />
                                                <TracePill label="event" value={span.agent_run_event_id} />
                                            </div>
                                            <TraceJsonBlock title="Input preview" value={span.input_preview} />
                                            <TraceJsonBlock title="Output preview" value={span.output_preview} />
                                            <TraceJsonBlock title="Payload" value={span.payload} />
                                        </div>
                                    </details>
                                ))}
                            </div>
                        ) : recentEvents.length > 0 ? (
                            <div style={{ display: 'grid' }}>
                                {recentEvents.map((event, index) => (
                                    <div key={event.id} style={{ padding: '0.6rem 0', borderBottom: index === recentEvents.length - 1 ? 'none' : '1px solid var(--border)', display: 'grid', gridTemplateColumns: 'auto 1fr auto', gap: '0.6rem', alignItems: 'start', fontSize: '0.8rem' }}>
                                        <span style={{ color: event.level === 'error' ? 'var(--danger)' : event.level === 'warning' ? 'var(--warning)' : 'var(--primary)', fontWeight: 800 }}>#{event.sequence}</span>
                                        <div style={{ minWidth: 0 }}>
                                            <div style={{ fontWeight: 700, textTransform: 'capitalize' }}>{event.event_type.replace(/_/g, ' ')}</div>
                                            <div style={{ color: 'var(--text-secondary)', overflowWrap: 'anywhere', marginTop: '0.15rem' }}>{event.message}</div>
                                        </div>
                                        <span style={{ color: 'var(--text-secondary)', whiteSpace: 'nowrap' }}>{new Date(event.created_at).toLocaleTimeString()}</span>
                                    </div>
                                ))}
                            </div>
                        ) : (
                            <div style={{ color: 'var(--text-secondary)', fontSize: '0.85rem' }}>No durable events have been recorded yet.</div>
                        )
                    )}

                    {selectedTraceTab === 'context' && (
                        <div style={{ display: 'grid', gap: '0.65rem' }}>
                            <div style={{ display: 'flex', gap: '0.4rem', flexWrap: 'wrap' }}>
                                <TracePill label="trace" value={snapshot?.trace_id} />
                                <TracePill label="prompt" value={snapshot?.prompt_hash?.slice(0, 20)} />
                                <TracePill label="context" value={snapshot?.context_hash?.slice(0, 20)} />
                                <TracePill label="memory" value={snapshot?.memory_block_hash?.slice(0, 20)} />
                            </div>
                            {snapshot?.trace_id && <button type="button" onClick={() => copyText(snapshot.trace_id)} style={{ justifySelf: 'start', border: '1px solid var(--border)', background: 'var(--surface-hover)', color: 'var(--text)', borderRadius: '6px', padding: '0.38rem 0.55rem', cursor: 'pointer', display: 'inline-flex', alignItems: 'center', gap: '0.32rem', fontSize: '0.76rem', fontWeight: 700 }}><Copy size={13} /> Copy trace ID</button>}
                            <TraceJsonBlock title="Prompt preview" value={snapshot?.prompt_preview || 'No prompt snapshot captured yet.'} />
                            <TraceJsonBlock title="Memory/context preview" value={snapshot?.memory_preview} />
                            <TraceJsonBlock title="Allowed tools" value={snapshot?.allowed_tools || []} />
                            <TraceJsonBlock title="Test data refs" value={snapshot?.test_data_refs || []} />
                            {(snapshot?.prompt_artifact_path || snapshot?.context_artifact_path) && (
                                <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
                                    {snapshot.prompt_artifact_path && <a href={`${API_BASE}${snapshot.prompt_artifact_path}`} target="_blank" rel="noreferrer" style={{ color: 'var(--primary)', fontWeight: 700, fontSize: '0.78rem', textDecoration: 'none' }}>Open redacted prompt</a>}
                                    {snapshot.context_artifact_path && <a href={`${API_BASE}${snapshot.context_artifact_path}`} target="_blank" rel="noreferrer" style={{ color: 'var(--primary)', fontWeight: 700, fontSize: '0.78rem', textDecoration: 'none' }}>Open redacted context</a>}
                                </div>
                            )}
                        </div>
                    )}

                    {selectedTraceTab === 'tools' && (
                        <div style={{ display: 'grid', gap: '0.45rem' }}>
                            {toolSpans.length > 0 ? toolSpans.slice(-80).reverse().map(span => (
                                <details key={span.id} style={{ border: '1px solid var(--border)', borderRadius: '6px', background: 'var(--surface-hover)', overflow: 'hidden' }}>
                                    <summary style={{ cursor: 'pointer', padding: '0.58rem 0.7rem', display: 'flex', justifyContent: 'space-between', gap: '0.75rem', alignItems: 'center', fontSize: '0.8rem' }}>
                                        <strong>{formatToolName(span.tool_name || span.name)}</strong>
                                        <span style={{ color: span.success === false ? 'var(--danger)' : 'var(--text-secondary)' }}>{span.duration_ms != null ? `${Math.round(span.duration_ms)}ms` : span.span_type}</span>
                                    </summary>
                                    <div style={{ padding: '0 0.7rem 0.7rem', display: 'grid', gap: '0.45rem' }}>
                                        {span.message && <div style={{ color: 'var(--text-secondary)', fontSize: '0.78rem' }}>{span.message}</div>}
                                        <TraceJsonBlock title="Input" value={span.input_preview} />
                                        <TraceJsonBlock title="Output" value={span.output_preview} />
                                        <TraceJsonBlock title="Raw span" value={span} />
                                    </div>
                                </details>
                            )) : toolEvents.length > 0 ? toolEvents.slice(-80).reverse().map(event => (
                                <details key={event.id} style={{ border: '1px solid var(--border)', borderRadius: '6px', background: 'var(--surface-hover)', overflow: 'hidden' }}>
                                    <summary style={{ cursor: 'pointer', padding: '0.58rem 0.7rem', display: 'flex', justifyContent: 'space-between', gap: '0.75rem', alignItems: 'center', fontSize: '0.8rem' }}>
                                        <strong>{formatToolName(String(event.payload?.tool_name || event.event_type))}</strong>
                                        <span style={{ color: event.level === 'error' ? 'var(--danger)' : 'var(--text-secondary)' }}>#{event.sequence}</span>
                                    </summary>
                                    <div style={{ padding: '0 0.7rem 0.7rem', display: 'grid', gap: '0.45rem' }}>
                                        <div style={{ color: 'var(--text-secondary)', fontSize: '0.78rem', overflowWrap: 'anywhere' }}>{event.message}</div>
                                        <TraceJsonBlock title="Event payload" value={event.payload} />
                                        <TraceJsonBlock title="Raw event" value={event} />
                                    </div>
                                </details>
                            )) : <div style={{ color: 'var(--text-secondary)', fontSize: '0.85rem' }}>No tool trace spans have been recorded yet.</div>}
                        </div>
                    )}

                    {selectedTraceTab === 'memory' && (
                        <div style={{ display: 'grid', gap: '0.5rem' }}>
                            {memoryInjections.length > 0 ? memoryInjections.map(item => (
                                <details key={item.id} style={{ border: '1px solid var(--border)', borderRadius: '6px', background: 'var(--surface-hover)', overflow: 'hidden' }}>
                                    <summary style={{ cursor: 'pointer', padding: '0.58rem 0.7rem', display: 'flex', justifyContent: 'space-between', gap: '0.75rem', fontSize: '0.8rem' }}>
                                        <strong>{item.stage || 'memory injection'}</strong>
                                        <span style={{ color: 'var(--text-secondary)' }}>{(item.memory_ids || []).length} memories</span>
                                    </summary>
                                    <div style={{ padding: '0 0.7rem 0.7rem', display: 'grid', gap: '0.45rem' }}>
                                        <TraceJsonBlock title="Context preview" value={item.context_preview} />
                                        <TraceJsonBlock title="Memory IDs" value={item.memory_ids || []} />
                                        <TraceJsonBlock title="Telemetry" value={item.extra_data || {}} />
                                    </div>
                                </details>
                            )) : <div style={{ color: 'var(--text-secondary)', fontSize: '0.85rem' }}>No linked memory injections were found for this run.</div>}
                        </div>
                    )}

                    {selectedTraceTab === 'runtime' && (
                        <div style={{ display: 'grid', gap: '0.65rem' }}>
                            <div style={{ display: 'flex', gap: '0.4rem', flexWrap: 'wrap' }}>
                                <TracePill label="runtime" value={snapshot?.runtime || run.runtime} />
                                <TracePill label="model" value={snapshot?.model} />
                                <TracePill label="tier" value={snapshot?.model_tier} />
                                <TracePill label="task" value={run.agent_task_id} />
                                <TracePill label="workflow" value={run.temporal_workflow_id} />
                            </div>
                            <TraceJsonBlock title="Runtime diagnostics" value={snapshot?.runtime_diagnostics || {}} />
                            <TraceJsonBlock title="Temporal summary" value={trace?.temporal || temporal || {}} />
                            <TraceJsonBlock title="Correlation IDs" value={trace?.correlation || { run_id: run.id, agent_task_id: run.agent_task_id, temporal_workflow_id: run.temporal_workflow_id }} />
                        </div>
                    )}

                    {selectedTraceTab === 'artifacts' && (
                        <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
                            {[...traceArtifacts, ...logArtifacts].length > 0 ? [...traceArtifacts, ...logArtifacts].map(artifact => (
                                <a key={`${artifact.type}-${artifact.path}`} href={getArtifactUrl(artifact)} target="_blank" rel="noreferrer" style={{ display: 'inline-flex', alignItems: 'center', gap: '0.35rem', padding: '0.38rem 0.6rem', border: '1px solid var(--border)', borderRadius: '6px', color: 'var(--primary)', textDecoration: 'none', fontSize: '0.78rem', fontWeight: 600 }}>
                                    <FileText size={13} /> {artifact.name}
                                </a>
                            )) : <div style={{ color: 'var(--text-secondary)', fontSize: '0.85rem' }}>No trace artifacts are available yet.</div>}
                        </div>
                    )}
                </div>
            </div>

            {logArtifacts.length > 0 && (
                <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
                    {logArtifacts.slice(0, 4).map(artifact => (
                        <a key={artifact.path} href={getArtifactUrl(artifact)} target="_blank" rel="noreferrer" style={{ display: 'inline-flex', alignItems: 'center', gap: '0.35rem', padding: '0.38rem 0.6rem', border: '1px solid var(--border)', borderRadius: '6px', color: 'var(--primary)', textDecoration: 'none', fontSize: '0.78rem', fontWeight: 600 }}>
                            <FileText size={13} /> {artifact.name}
                        </a>
                    ))}
                </div>
            )}
        </div>
    );
}

export function SpecGenerationRunPanel({ run, events }: { run: AgentRun; events: AgentRunEvent[] }) {
    const progress = run.progress || {};
    const latestImage = sortArtifactsByModifiedAt((run.artifacts || []).filter(artifact => artifact.type === 'image'))[0];
    const recentTools = progress.recent_tools || [];
    const errorMessage = run.result?.error || (run.status === 'failed' ? progress.message : null);
    const specFile = run.result?.spec_file;
    const specContent = run.result?.spec_content;

    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
            <div style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fit, minmax(120px, 1fr))',
                gap: '0.5rem',
                padding: '0.75rem',
                background: 'var(--surface-hover)',
                border: '1px solid var(--border)',
                borderRadius: '8px'
            }}>
                {[
                    { label: 'Status', value: run.status },
                    { label: 'Phase', value: progress.phase || 'queued' },
                    { label: 'Current Step', value: progress.last_tool_label || progress.message || 'Preparing browser' },
                    { label: 'Browser Actions', value: progress.browser_tool_calls ?? 0 },
                ].map(item => (
                    <div key={item.label} style={{ minWidth: 0, padding: '0.65rem', border: '1px solid var(--border)', borderRadius: '6px', background: 'var(--background)' }}>
                        <div style={{ fontSize: '0.72rem', color: 'var(--text-secondary)', textTransform: 'uppercase', marginBottom: '0.25rem' }}>{item.label}</div>
                        <div style={{ fontWeight: 700, overflowWrap: 'anywhere', textTransform: item.label === 'Status' || item.label === 'Phase' ? 'capitalize' : 'none', lineHeight: 1.3, display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}>{item.value}</div>
                    </div>
                ))}
            </div>

            {errorMessage && (
                <div style={{ padding: '1rem', background: 'var(--danger-muted)', color: 'var(--danger)', borderRadius: '8px', border: '1px solid rgba(248, 113, 113, 0.2)' }}>
                    <h4 style={{ margin: 0, fontWeight: 700, display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                        <AlertTriangle size={18} /> Spec Generation Failed
                    </h4>
                    <p style={{ margin: '0.5rem 0 0', fontFamily: 'monospace', overflowWrap: 'anywhere' }}>{errorMessage}</p>
                </div>
            )}

            <LiveBrowserView
                runId={run.id}
                isActive={LIVE_AGENT_STATUSES.has(run.status) && run.status !== 'paused'}
                showHeader
                artifacts={run.artifacts || []}
                latestImage={latestImage}
                statusMessage={progress.message}
                liveViewAvailable={progress.live_view_available !== false}
                runtimeMessage={progress.runtime_message}
                vncUrl={progress.vnc_url}
                browserActivitySeen={Boolean(progress.browser_activity_seen || progress.browser_tool_calls || progress.interactions)}
                browserActive={Boolean(progress.browser_tool_calls || progress.interactions)}
                browserLastTool={progress.last_tool_label || progress.last_tool}
                suspectedBrowserDialogBlock={progress.suspected_browser_dialog_block === true}
                authPreflightStatus={progress.auth_preflight_status}
                authPreflightFailureReason={progress.auth_preflight_failure_reason}
            />

            <AgentRunCapturePanel activeRun={run} mode={LIVE_AGENT_STATUSES.has(run.status) ? 'live' : 'recording'} />
            <AgentRunObservabilityPanel run={run} events={events} />

            {latestImage && (
                <div style={{ border: '1px solid var(--border)', borderRadius: '8px', overflow: 'hidden', background: 'var(--background)' }}>
                    <div style={{ padding: '0.75rem 1rem', borderBottom: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', gap: '1rem' }}>
                        <h4 style={{ margin: 0, fontSize: '0.95rem', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                            <ImageIcon size={15} /> Latest Screenshot
                        </h4>
                        {latestImage.modified_at && <span style={{ fontSize: '0.78rem', color: 'var(--text-secondary)' }}>{new Date(latestImage.modified_at).toLocaleTimeString()}</span>}
                    </div>
                    <a href={getArtifactUrl(latestImage)} target="_blank" rel="noreferrer" style={{ display: 'block' }}>
                        <img src={getArtifactUrl(latestImage)} alt="Latest spec generation screenshot" style={{ width: '100%', display: 'block', aspectRatio: '16 / 9', maxHeight: '420px', objectFit: 'contain', background: '#000' }} />
                    </a>
                </div>
            )}

            {recentTools.length > 0 && (
                <div style={{ border: '1px solid var(--border)', borderRadius: '8px', overflow: 'hidden', background: 'var(--background)' }}>
                    <div style={{ padding: '0.75rem 1rem', borderBottom: '1px solid var(--border)', fontWeight: 600 }}>Live Activity</div>
                    {recentTools.slice().reverse().map((tool: any, i: number) => (
                        <div key={`${tool.name}-${tool.at}-${i}`} style={{ padding: '0.65rem 1rem', borderBottom: i === recentTools.length - 1 ? 'none' : '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', gap: '1rem', fontSize: '0.85rem' }}>
                            <span style={{ fontWeight: 600 }}>{tool.label || formatToolName(tool.name)}</span>
                            {tool.at && <span style={{ color: 'var(--text-secondary)' }}>{new Date(tool.at).toLocaleTimeString()}</span>}
                        </div>
                    ))}
                </div>
            )}

            {run.status === 'completed' && (
                <div style={{ border: '1px solid var(--border)', borderRadius: '8px', overflow: 'hidden', background: 'var(--background)' }}>
                    <div style={{ padding: '0.75rem 1rem', borderBottom: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', gap: '1rem', alignItems: 'center' }}>
                        <h4 style={{ margin: 0, fontSize: '0.95rem', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                            <FileText size={15} /> Generated Spec
                        </h4>
                        {specFile && <span style={{ fontSize: '0.78rem', color: 'var(--text-secondary)', overflowWrap: 'anywhere' }}>{specFile}</span>}
                    </div>
                    {specContent ? (
                        <pre style={{ margin: 0, padding: '1rem', whiteSpace: 'pre-wrap', fontFamily: 'var(--font-mono)', fontSize: '0.85rem', lineHeight: 1.6, maxHeight: '420px', overflow: 'auto', background: 'var(--code-bg)' }}>{specContent}</pre>
                    ) : (
                        <div style={{ padding: '1rem', color: 'var(--text-secondary)', fontSize: '0.9rem' }}>
                            Spec generated. Open the artifact or specs page to inspect the file.
                        </div>
                    )}
                </div>
            )}
        </div>
    );
}

export function QueueStatusPanel({
    queue,
    loading,
    error,
    onRefresh,
    onCleanStaleTasks,
    cleaningStaleTasks,
}: {
    queue: AgentQueueStatus | null;
    loading: boolean;
    error: string | null;
    onRefresh: () => void;
    onCleanStaleTasks: () => Promise<void>;
    cleaningStaleTasks: boolean;
}) {
    const stale = queue?.stale_running ?? 0;
    const orphaned = queue?.orphaned_tasks ?? 0;
    const hasCleanupWork = stale > 0 || orphaned > 0;
    const workerCount = queue?.workers_alive ?? queue?.worker_processes_alive ?? 0;
    const browserPool = queue?.browser_pool || {};
    const browserMax = Number(browserPool.max_browsers ?? queue?.max ?? 0);
    const browserRunning = Number(browserPool.running ?? queue?.pool_status?.total_running ?? 0);
    const browserAvailable = Number(browserPool.available ?? queue?.available ?? Math.max(0, browserMax - browserRunning));
    const warnings = [
        stale > 0 ? `${stale} stale running task${stale === 1 ? '' : 's'}` : '',
        orphaned > 0 ? `${orphaned} orphaned task${orphaned === 1 ? '' : 's'}` : '',
        (queue?.active || queue?.queued || 0) > 0 && workerCount === 0 ? 'No live workers for active queue work' : '',
    ].filter(Boolean);

    return (
        <div className="card" style={{ padding: '1rem', display: 'grid', gap: '1rem' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '1rem', flexWrap: 'wrap' }}>
                <div>
                    <h2 style={{ margin: 0, fontSize: '1rem', fontWeight: 800 }}>Queue Capacity</h2>
                    <p style={{ margin: '0.25rem 0 0', color: 'var(--text-secondary)', fontSize: '0.85rem' }}>
                        {queue ? `${queue.mode || 'agent'} mode · ${queueStateLabel(queue)}` : 'Queue status has not loaded yet.'}
                    </p>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
                    {hasCleanupWork && (
                        <Button type="button" variant="outline" onClick={onCleanStaleTasks} disabled={loading || cleaningStaleTasks}>
                            {cleaningStaleTasks ? <Loader2 className="spin" size={14} /> : <Wrench size={14} />} Clean stale tasks
                        </Button>
                    )}
                    <Button type="button" variant="outline" onClick={onRefresh} disabled={loading}>
                        {loading ? <Loader2 className="spin" size={14} /> : <RefreshCw size={14} />} Refresh
                    </Button>
                </div>
            </div>
            {error && (
                <Alert variant="destructive">
                    <AlertTriangle size={16} />
                    <AlertDescription>{error}</AlertDescription>
                </Alert>
            )}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: '0.75rem' }}>
                {[
                    ['Active runs', queue?.active ?? 0],
                    ['Queued runs', queue?.queued ?? 0],
                    ['Workers alive', workerCount],
                    ['Workers idle', queue?.workers_idle ?? 0],
                    ['Browser slots', browserMax ? `${browserRunning}/${browserMax}` : `${browserRunning}`],
                    ['Available slots', browserAvailable],
                    ['Oldest queued', formatQueueAge(queue?.oldest_queued_age_seconds)],
                    ['Health', warnings.length ? 'Watch' : 'Stable'],
                ].map(([label, value]) => (
                    <div key={label} style={{ padding: '0.9rem', border: '1px solid var(--border)', borderRadius: '8px', background: 'var(--surface-hover)', minWidth: 0 }}>
                        <div style={{ color: 'var(--text-secondary)', fontSize: '0.72rem', textTransform: 'uppercase', fontWeight: 800, marginBottom: '0.35rem' }}>{label}</div>
                        <div style={{ fontWeight: 850, fontSize: '1.1rem', overflowWrap: 'anywhere', color: label === 'Health' && warnings.length ? 'var(--warning)' : 'var(--text)' }}>{String(value)}</div>
                    </div>
                ))}
            </div>
            {warnings.length > 0 && (
                <div style={{ padding: '0.85rem', border: '1px solid rgba(245, 158, 11, 0.35)', borderRadius: '8px', background: 'rgba(245, 158, 11, 0.12)', color: 'var(--warning)', display: 'grid', gap: '0.35rem', fontSize: '0.85rem', fontWeight: 700 }}>
                    {warnings.map(item => <div key={item}>{item}</div>)}
                </div>
            )}
            {(queue?.running_tasks || []).length > 0 && (
                <div style={{ border: '1px solid var(--border)', borderRadius: '8px', overflow: 'hidden' }}>
                    <div style={{ padding: '0.75rem 0.9rem', borderBottom: '1px solid var(--border)', fontWeight: 800 }}>Running tasks</div>
                    {(queue?.running_tasks || []).slice(0, 8).map((task, index) => (
                        <div key={String(task.id || index)} style={{ padding: '0.65rem 0.9rem', borderBottom: index === Math.min((queue?.running_tasks || []).length, 8) - 1 ? 'none' : '1px solid var(--border)', display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) auto', gap: '0.75rem', fontSize: '0.82rem' }}>
                            <span style={{ overflowWrap: 'anywhere' }}>
                                {String(task.agent_type || task.operation_type || 'agent task')}
                                {task.id ? ` · ${String(task.id)}` : ''}
                            </span>
                            <span style={{ color: task.orphaned ? 'var(--warning)' : 'var(--text-secondary)', fontWeight: 700 }}>{String(task.status || 'running')}</span>
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
}

export function ReportsSearchWorkspace({
    query,
    onQueryChange,
    type,
    onTypeChange,
    severity,
    onSeverityChange,
    loading,
    results,
    onRefresh,
    onOpenResult,
}: {
    query: string;
    onQueryChange: (value: string) => void;
    type: ReportSearchTypeFilter;
    onTypeChange: (value: ReportSearchTypeFilter) => void;
    severity: string;
    onSeverityChange: (value: string) => void;
    loading: boolean;
    results: AgentReportSearchItem[];
    onRefresh: () => void;
    onOpenResult?: (result: AgentReportSearchItem) => void;
}) {
    return (
        <div className="card" style={{ padding: '1rem', display: 'grid', gap: '1rem' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '1rem', flexWrap: 'wrap' }}>
                <div>
                    <h2 style={{ margin: 0, fontSize: '1rem', fontWeight: 800 }}>Search Reports</h2>
                    <p style={{ margin: '0.25rem 0 0', color: 'var(--text-secondary)', fontSize: '0.85rem' }}>Findings, test ideas, requirements, evidence, and checked pages.</p>
                </div>
                <Button type="button" variant="outline" onClick={onRefresh} disabled={loading}>
                    {loading ? <Loader2 className="spin" size={14} /> : <Search size={14} />} Search
                </Button>
            </div>
            <div className="agents-report-search-grid">
                <label style={{ display: 'grid', gap: '0.35rem', fontSize: '0.78rem', fontWeight: 700 }}>
                    Search reports
                    <Input value={query} onChange={event => onQueryChange(event.target.value)} placeholder="Checkout, REQ, selector, URL" />
                </label>
                <label style={{ display: 'grid', gap: '0.35rem', fontSize: '0.78rem', fontWeight: 700 }}>
                    Type
                    <select value={type} onChange={event => onTypeChange(event.target.value as ReportSearchTypeFilter)} style={{ minHeight: 40, borderRadius: 'var(--radius)', border: '1px solid var(--border)', background: 'var(--background-raised)', color: 'var(--text)', padding: '0.5rem' }}>
                        <option value="all">All types</option>
                        <option value="finding">Findings</option>
                        <option value="test_idea">Test ideas</option>
                        <option value="requirement">Requirements</option>
                        <option value="page">Pages checked</option>
                        <option value="evidence">Evidence</option>
                        <option value="action">Actions</option>
                    </select>
                </label>
                <label style={{ display: 'grid', gap: '0.35rem', fontSize: '0.78rem', fontWeight: 700 }}>
                    Severity
                    <select value={severity} onChange={event => onSeverityChange(event.target.value)} style={{ minHeight: 40, borderRadius: 'var(--radius)', border: '1px solid var(--border)', background: 'var(--background-raised)', color: 'var(--text)', padding: '0.5rem' }}>
                        <option value="all">All</option>
                        <option value="critical">Critical</option>
                        <option value="high">High</option>
                        <option value="medium">Medium</option>
                        <option value="low">Low</option>
                    </select>
                </label>
            </div>
            <div style={{ display: 'grid', gap: '0.65rem' }}>
                {loading ? (
                    <div style={{ padding: '2rem', color: 'var(--text-secondary)', textAlign: 'center' }}><Loader2 className="spin" size={18} /> Searching reports...</div>
                ) : results.length === 0 ? (
                    <EmptyReportState text="No report items match the current search." />
                ) : results.map(result => {
                    const item = result.item || {};
                    const title = item.title || item.label || item.url || item.id || result.type;
                    const state = reportItemReviewState(item, result.type);
                    return (
                        <div key={`${result.run_id}-${result.type}-${item.id || title}`} style={{ padding: '0.9rem', border: '1px solid var(--border)', borderRadius: '8px', background: 'var(--background)', display: 'grid', gap: '0.45rem' }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', gap: '0.75rem', flexWrap: 'wrap' }}>
                                <strong style={{ overflowWrap: 'anywhere' }}>{title}</strong>
                                <span style={{ color: severityColor(item.severity || item.priority), fontWeight: 800, textTransform: 'uppercase', fontSize: '0.76rem' }}>{item.severity || item.priority || state}</span>
                            </div>
                            <div style={{ color: 'var(--text-secondary)', fontSize: '0.8rem', display: 'flex', gap: '0.6rem', flexWrap: 'wrap' }}>
                                <span>{result.type.replace(/_/g, ' ')}</span>
                                <span>{result.agent_name || 'Custom Agent'}</span>
                                {result.created_at && <span>{new Date(result.created_at).toLocaleString()}</span>}
                            </div>
                            {(item.description || item.evidence || item.value) && (
                                <div style={{ color: 'var(--text-secondary)', fontSize: '0.84rem', lineHeight: 1.45, overflowWrap: 'anywhere' }}>{item.description || item.evidence || item.value}</div>
                            )}
                            <div>
                                <a
                                    href={reportSearchResultHref(result)}
                                    onClick={(event) => {
                                        if (!onOpenResult || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
                                        event.preventDefault();
                                        onOpenResult(result);
                                    }}
                                    style={{ color: 'var(--primary)', fontWeight: 700, fontSize: '0.82rem' }}
                                >
                                    Open report
                                </a>
                            </div>
                        </div>
                    );
                })}
            </div>
        </div>
    );
}
