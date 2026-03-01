'use client';

import { useState, useEffect } from 'react';
import { Save, AlertCircle, CheckCircle, Key, Globe, Box, Eye, EyeOff, Server, Layers, Monitor, Database, Zap, HardDrive, Lock, Link2, Mail, Loader2, ChevronDown, Bug, GitBranch, GitMerge, Shield, Settings } from 'lucide-react';
import { useProject } from '@/contexts/ProjectContext';
import { useAuth } from '@/contexts/AuthContext';
import { CredentialsManager } from '@/components/CredentialsManager';
import { API_BASE } from '@/lib/api';
import { PageLayout } from '@/components/ui/page-layout';
import { PageHeader } from '@/components/ui/page-header';
import { FormPageSkeleton } from '@/components/ui/page-skeleton';

interface ExecutionSettings {
    parallelism: number;
    parallel_mode_enabled: boolean;
    headless_in_parallel: boolean;
    memory_enabled: boolean;
    database_type: string;
    parallel_mode_available: boolean;
}

interface TestrailConfig {
    configured: boolean;
    base_url: string;
    email: string;
    api_key_masked: string;
    project_id: number | null;
    suite_id: number | null;
}

interface RemoteProject {
    id: number;
    name: string;
    is_completed: boolean;
}

interface RemoteSuite {
    id: number;
    name: string;
}

export default function SettingsPage() {
    const { currentProject } = useProject();
    const { user } = useAuth();
    const [settings, setSettings] = useState({
        llm_provider: 'anthropic',
        api_key: '',
        base_url: '',
        model_name: ''
    });
    const [executionSettings, setExecutionSettings] = useState<ExecutionSettings>({
        parallelism: 2,
        parallel_mode_enabled: false,
        headless_in_parallel: true,
        memory_enabled: true,
        database_type: 'sqlite',
        parallel_mode_available: false
    });
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);
    const [savingExecution, setSavingExecution] = useState(false);
    const [message, setMessage] = useState<{ type: 'success' | 'error', text: string } | null>(null);
    const [showApiKey, setShowApiKey] = useState(false);

    // TestRail integration state
    const [trUrl, setTrUrl] = useState('');
    const [trEmail, setTrEmail] = useState('');
    const [trApiKey, setTrApiKey] = useState('');
    const [trApiKeyMasked, setTrApiKeyMasked] = useState('');
    const [showTrApiKey, setShowTrApiKey] = useState(false);
    const [trProjectId, setTrProjectId] = useState<number | null>(null);
    const [trSuiteId, setTrSuiteId] = useState<number | null>(null);
    const [trConfigured, setTrConfigured] = useState(false);
    const [trTesting, setTrTesting] = useState(false);
    const [trConnectionStatus, setTrConnectionStatus] = useState<{ ok: boolean; message: string } | null>(null);
    const [trSaving, setTrSaving] = useState(false);
    const [trRemoteProjects, setTrRemoteProjects] = useState<RemoteProject[]>([]);
    const [trRemoteSuites, setTrRemoteSuites] = useState<RemoteSuite[]>([]);
    const [trLoadingProjects, setTrLoadingProjects] = useState(false);
    const [trLoadingSuites, setTrLoadingSuites] = useState(false);

    // Jira integration state
    const [jiraUrl, setJiraUrl] = useState('');
    const [jiraEmail, setJiraEmail] = useState('');
    const [jiraApiToken, setJiraApiToken] = useState('');
    const [jiraApiTokenMasked, setJiraApiTokenMasked] = useState('');
    const [showJiraApiToken, setShowJiraApiToken] = useState(false);
    const [jiraProjectKey, setJiraProjectKey] = useState<string | null>(null);
    const [jiraIssueTypeId, setJiraIssueTypeId] = useState<string | null>(null);
    const [jiraConfigured, setJiraConfigured] = useState(false);
    const [jiraTesting, setJiraTesting] = useState(false);
    const [jiraConnectionStatus, setJiraConnectionStatus] = useState<{ ok: boolean; message: string } | null>(null);
    const [jiraSaving, setJiraSaving] = useState(false);
    const [jiraRemoteProjects, setJiraRemoteProjects] = useState<{ key: string; name: string; id: string }[]>([]);
    const [jiraRemoteIssueTypes, setJiraRemoteIssueTypes] = useState<{ id: string; name: string }[]>([]);
    const [jiraLoadingProjects, setJiraLoadingProjects] = useState(false);
    const [jiraLoadingIssueTypes, setJiraLoadingIssueTypes] = useState(false);

    // GitLab integration state
    const [glUrl, setGlUrl] = useState('');
    const [glToken, setGlToken] = useState('');
    const [glTokenMasked, setGlTokenMasked] = useState('');
    const [showGlToken, setShowGlToken] = useState(false);
    const [glProjectId, setGlProjectId] = useState<string | null>(null);
    const [glTriggerToken, setGlTriggerToken] = useState('');
    const [glTriggerTokenMasked, setGlTriggerTokenMasked] = useState('');
    const [showGlTriggerToken, setShowGlTriggerToken] = useState(false);
    const [glDefaultRef, setGlDefaultRef] = useState('main');
    const [glWebhookSecret, setGlWebhookSecret] = useState('');
    const [glConfigured, setGlConfigured] = useState(false);
    const [glTesting, setGlTesting] = useState(false);
    const [glConnectionStatus, setGlConnectionStatus] = useState<{ ok: boolean; message: string } | null>(null);
    const [glSaving, setGlSaving] = useState(false);
    const [glRemoteProjects, setGlRemoteProjects] = useState<{ id: number; name: string; path_with_namespace: string }[]>([]);
    const [glLoadingProjects, setGlLoadingProjects] = useState(false);

    // GitHub integration state
    const [ghOwner, setGhOwner] = useState('');
    const [ghRepo, setGhRepo] = useState('');
    const [ghToken, setGhToken] = useState('');
    const [ghTokenMasked, setGhTokenMasked] = useState('');
    const [showGhToken, setShowGhToken] = useState(false);
    const [ghDefaultWorkflow, setGhDefaultWorkflow] = useState('');
    const [ghDefaultRef, setGhDefaultRef] = useState('main');
    const [ghWebhookSecret, setGhWebhookSecret] = useState('');
    const [ghConfigured, setGhConfigured] = useState(false);
    const [ghTesting, setGhTesting] = useState(false);
    const [ghConnectionStatus, setGhConnectionStatus] = useState<{ ok: boolean; message: string } | null>(null);
    const [ghSaving, setGhSaving] = useState(false);
    const [ghRemoteRepos, setGhRemoteRepos] = useState<{ full_name: string; name: string }[]>([]);
    const [ghLoadingRepos, setGhLoadingRepos] = useState(false);
    const [ghRemoteWorkflows, setGhRemoteWorkflows] = useState<{ id: number; name: string; path: string }[]>([]);
    const [ghLoadingWorkflows, setGhLoadingWorkflows] = useState(false);

    useEffect(() => {
        Promise.all([
            fetch(`${API_BASE}/settings`).then(res => res.json()),
            fetch(`${API_BASE}/execution-settings`).then(res => res.json())
        ])
            .then(([settingsData, execData]) => {
                setSettings(prev => ({ ...prev, ...settingsData }));
                setExecutionSettings(execData);
                setLoading(false);
            })
            .catch(err => {
                console.error(err);
                setLoading(false);
            });
    }, []);

    // Load TestRail config when project changes — auto-restore full state
    useEffect(() => {
        if (!currentProject?.id) return;
        const pid = encodeURIComponent(currentProject.id);

        fetch(`${API_BASE}/testrail/${pid}/config`)
            .then(res => res.json())
            .then(async (data: TestrailConfig) => {
                setTrConfigured(data.configured);
                if (data.configured) {
                    setTrUrl(data.base_url || '');
                    setTrEmail(data.email || '');
                    setTrApiKey(''); // Don't populate — masked only
                    setTrApiKeyMasked(data.api_key_masked || '');
                    setTrProjectId(data.project_id);
                    setTrSuiteId(data.suite_id);

                    // Auto-verify connection and load remote data
                    try {
                        const connRes = await fetch(`${API_BASE}/testrail/${pid}/test-connection`, { method: 'POST' });
                        const connData = await connRes.json();
                        if (connRes.ok) {
                            setTrConnectionStatus({ ok: true, message: `Connected as ${connData.user}` });

                            // Load remote projects
                            const projRes = await fetch(`${API_BASE}/testrail/${pid}/remote-projects`);
                            if (projRes.ok) {
                                const projects = await projRes.json();
                                setTrRemoteProjects(projects);
                            }

                            // Load remote suites if project is selected
                            if (data.project_id) {
                                const suitesRes = await fetch(`${API_BASE}/testrail/${pid}/remote-suites/${data.project_id}`);
                                if (suitesRes.ok) {
                                    const suites = await suitesRes.json();
                                    setTrRemoteSuites(suites);
                                }
                            }
                        }
                    } catch {
                        // Silent — user can manually test connection
                    }
                } else {
                    setTrUrl('');
                    setTrEmail('');
                    setTrApiKey('');
                    setTrProjectId(null);
                    setTrSuiteId(null);
                    setTrConnectionStatus(null);
                    setTrRemoteProjects([]);
                    setTrRemoteSuites([]);
                }
            })
            .catch(() => { });
    }, [currentProject?.id]);

    // Load Jira config when project changes
    useEffect(() => {
        if (!currentProject?.id) return;
        const pid = encodeURIComponent(currentProject.id);

        fetch(`${API_BASE}/jira/${pid}/config`)
            .then(res => res.json())
            .then(async (data) => {
                setJiraConfigured(data.configured);
                if (data.configured) {
                    setJiraUrl(data.base_url || '');
                    setJiraEmail(data.email || '');
                    setJiraApiToken('');
                    setJiraApiTokenMasked(data.api_token_masked || '');
                    setJiraProjectKey(data.project_key || null);
                    setJiraIssueTypeId(data.issue_type_id || null);

                    // Auto-verify and load remote data
                    try {
                        const connRes = await fetch(`${API_BASE}/jira/${pid}/test-connection`, { method: 'POST' });
                        const connData = await connRes.json();
                        if (connRes.ok) {
                            setJiraConnectionStatus({ ok: true, message: `Connected as ${connData.user}` });
                            const projRes = await fetch(`${API_BASE}/jira/${pid}/remote-projects`);
                            if (projRes.ok) {
                                setJiraRemoteProjects(await projRes.json());
                            }
                            if (data.project_key) {
                                const itRes = await fetch(`${API_BASE}/jira/${pid}/remote-issue-types/${data.project_key}`);
                                if (itRes.ok) {
                                    setJiraRemoteIssueTypes(await itRes.json());
                                }
                            }
                        }
                    } catch {
                        // Silent — user can manually test connection
                    }
                } else {
                    setJiraUrl('');
                    setJiraEmail('');
                    setJiraApiToken('');
                    setJiraProjectKey(null);
                    setJiraIssueTypeId(null);
                    setJiraConnectionStatus(null);
                    setJiraRemoteProjects([]);
                    setJiraRemoteIssueTypes([]);
                }
            })
            .catch(() => { });
    }, [currentProject?.id]);

    // Load GitLab config when project changes
    useEffect(() => {
        if (!currentProject?.id) return;
        const pid = encodeURIComponent(currentProject.id);

        fetch(`${API_BASE}/gitlab/${pid}/config`)
            .then(res => res.json())
            .then(async (data) => {
                setGlConfigured(data.configured);
                if (data.configured) {
                    setGlUrl(data.gitlab_url || '');
                    setGlToken('');
                    setGlTokenMasked(data.token_masked || '');
                    setGlProjectId(data.project_id || null);
                    setGlTriggerToken('');
                    setGlTriggerTokenMasked(data.trigger_token_masked || '');
                    setGlDefaultRef(data.default_ref || 'main');
                    setGlWebhookSecret(data.webhook_secret || '');

                    try {
                        const connRes = await fetch(`${API_BASE}/gitlab/${pid}/test-connection`, { method: 'POST' });
                        const connData = await connRes.json();
                        if (connRes.ok) {
                            setGlConnectionStatus({ ok: true, message: `Connected as ${connData.user || connData.username || 'authenticated'}` });
                            const projRes = await fetch(`${API_BASE}/gitlab/${pid}/remote-projects`);
                            if (projRes.ok) {
                                setGlRemoteProjects(await projRes.json());
                            }
                        }
                    } catch {
                        // Silent
                    }
                } else {
                    setGlUrl('');
                    setGlToken('');
                    setGlTokenMasked('');
                    setGlProjectId(null);
                    setGlTriggerToken('');
                    setGlTriggerTokenMasked('');
                    setGlDefaultRef('main');
                    setGlWebhookSecret('');
                    setGlConnectionStatus(null);
                    setGlRemoteProjects([]);
                }
            })
            .catch(() => { });
    }, [currentProject?.id]);

    // Load GitHub config when project changes
    useEffect(() => {
        if (!currentProject?.id) return;
        const pid = encodeURIComponent(currentProject.id);

        fetch(`${API_BASE}/github/${pid}/config`)
            .then(res => res.json())
            .then(async (data) => {
                setGhConfigured(data.configured);
                if (data.configured) {
                    setGhOwner(data.owner || '');
                    setGhRepo(data.repo || '');
                    setGhToken('');
                    setGhTokenMasked(data.token_masked || '');
                    setGhDefaultWorkflow(data.default_workflow || '');
                    setGhDefaultRef(data.default_ref || 'main');
                    setGhWebhookSecret(data.webhook_secret || '');

                    try {
                        const connRes = await fetch(`${API_BASE}/github/${pid}/test-connection`, { method: 'POST' });
                        const connData = await connRes.json();
                        if (connRes.ok) {
                            setGhConnectionStatus({ ok: true, message: `Connected as ${connData.user || connData.login || 'authenticated'}` });
                            const repoRes = await fetch(`${API_BASE}/github/${pid}/remote-repos`);
                            if (repoRes.ok) {
                                setGhRemoteRepos(await repoRes.json());
                            }
                            if (data.owner && data.repo) {
                                const wfRes = await fetch(`${API_BASE}/github/${pid}/remote-workflows`);
                                if (wfRes.ok) {
                                    setGhRemoteWorkflows(await wfRes.json());
                                }
                            }
                        } else {
                            setGhConnectionStatus({ ok: false, message: connData.detail || 'Connection failed' });
                        }
                    } catch {
                        setGhConnectionStatus({ ok: false, message: 'Could not verify connection' });
                    }
                } else {
                    setGhOwner('');
                    setGhRepo('');
                    setGhToken('');
                    setGhTokenMasked('');
                    setGhDefaultWorkflow('');
                    setGhDefaultRef('main');
                    setGhWebhookSecret('');
                    setGhConnectionStatus(null);
                    setGhRemoteRepos([]);
                    setGhRemoteWorkflows([]);
                }
            })
            .catch(() => { });
    }, [currentProject?.id]);

    const handleChange = (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => {
        const { name, value } = e.target;

        // Auto-populate base_url and model when provider changes
        if (name === 'llm_provider') {
            const updates: any = { [name]: value };

            if (value === 'openrouter') {
                updates.base_url = 'https://openrouter.ai/api';
                updates.model_name = 'meta-llama/llama-3.2-3b-instruct:free';
            } else if (value === 'anthropic') {
                updates.base_url = 'https://api.anthropic.com';
                updates.model_name = 'claude-3-5-sonnet-20240620';
            }

            setSettings(prev => ({ ...prev, ...updates }));
        } else {
            setSettings(prev => ({ ...prev, [name]: value }));
        }
    };


    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        setSaving(true);
        setMessage(null);

        try {
            const res = await fetch(`${API_BASE}/settings`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(settings)
            });
            const data = await res.json();

            if (res.ok) {
                setMessage({ type: 'success', text: 'Settings saved successfully!' });
                setTimeout(() => setMessage(null), 3000);
            } else {
                throw new Error(data.detail || 'Failed to save settings');
            }
        } catch (err: any) {
            setMessage({ type: 'error', text: err.message });
        } finally {
            setSaving(false);
        }
    };

    const handleExecutionChange = (field: keyof ExecutionSettings, value: any) => {
        setExecutionSettings(prev => ({ ...prev, [field]: value }));
    };

    const handleExecutionSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        setSavingExecution(true);
        setMessage(null);

        try {
            const res = await fetch(`${API_BASE}/execution-settings`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    parallelism: executionSettings.parallelism,
                    parallel_mode_enabled: executionSettings.parallel_mode_enabled,
                    headless_in_parallel: executionSettings.headless_in_parallel,
                    memory_enabled: executionSettings.memory_enabled
                })
            });
            const data = await res.json();

            if (res.ok) {
                setExecutionSettings(data);
                setMessage({ type: 'success', text: 'Execution settings saved!' });
                setTimeout(() => setMessage(null), 3000);
            } else {
                throw new Error(data.detail || 'Failed to save execution settings');
            }
        } catch (err: any) {
            setMessage({ type: 'error', text: err.message });
        } finally {
            setSavingExecution(false);
        }
    };

    // ── TestRail handlers ──────────────────────────────────────

    const handleTrTestConnection = async () => {
        if (!currentProject?.id || !trUrl || !trEmail || (!trApiKey && !trConfigured)) return;
        setTrTesting(true);
        setTrConnectionStatus(null);

        try {
            // Save first so backend has credentials
            if (trApiKey) {
                await fetch(`${API_BASE}/testrail/${encodeURIComponent(currentProject.id)}/config`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        base_url: trUrl,
                        email: trEmail,
                        api_key: trApiKey,
                        project_id: trProjectId,
                        suite_id: trSuiteId,
                    })
                });
            }

            const res = await fetch(`${API_BASE}/testrail/${encodeURIComponent(currentProject.id)}/test-connection`, {
                method: 'POST',
            });
            const data = await res.json();

            if (res.ok) {
                setTrConnectionStatus({ ok: true, message: `Connected as ${data.user}` });
                setTrConfigured(true);
                // Load remote projects
                loadRemoteProjects();
            } else {
                setTrConnectionStatus({ ok: false, message: data.detail || 'Connection failed' });
            }
        } catch (err: any) {
            setTrConnectionStatus({ ok: false, message: err.message || 'Connection failed' });
        } finally {
            setTrTesting(false);
        }
    };

    const loadRemoteProjects = async () => {
        if (!currentProject?.id) return;
        setTrLoadingProjects(true);
        try {
            const res = await fetch(`${API_BASE}/testrail/${encodeURIComponent(currentProject.id)}/remote-projects`);
            if (res.ok) {
                const data = await res.json();
                setTrRemoteProjects(data);
            }
        } catch {
        } finally {
            setTrLoadingProjects(false);
        }
    };

    const loadRemoteSuites = async (trProjId: number) => {
        if (!currentProject?.id) return;
        setTrLoadingSuites(true);
        try {
            const res = await fetch(`${API_BASE}/testrail/${encodeURIComponent(currentProject.id)}/remote-suites/${trProjId}`);
            if (res.ok) {
                const data = await res.json();
                setTrRemoteSuites(data);
                // Auto-select if only one suite (single-suite projects)
                if (data.length === 1 && !trSuiteId) {
                    setTrSuiteId(data[0].id);
                }
            }
        } catch {
        } finally {
            setTrLoadingSuites(false);
        }
    };

    const handleTrSave = async () => {
        if (!currentProject?.id) return;
        setTrSaving(true);
        setMessage(null);

        try {
            const body: any = {
                base_url: trUrl,
                email: trEmail,
                project_id: trProjectId,
                suite_id: trSuiteId,
            };
            // Only include api_key if user entered a new one; backend preserves existing
            if (trApiKey) {
                body.api_key = trApiKey;
            }

            const res = await fetch(`${API_BASE}/testrail/${encodeURIComponent(currentProject.id)}/config`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });

            if (res.ok) {
                setTrConfigured(true);
                setMessage({ type: 'success', text: 'TestRail configuration saved!' });
                setTimeout(() => setMessage(null), 3000);
            } else {
                const data = await res.json();
                throw new Error(data.detail || 'Failed to save TestRail config');
            }
        } catch (err: any) {
            setMessage({ type: 'error', text: err.message });
        } finally {
            setTrSaving(false);
        }
    };

    const handleTrDelete = async () => {
        if (!currentProject?.id) return;
        try {
            await fetch(`${API_BASE}/testrail/${encodeURIComponent(currentProject.id)}/config`, { method: 'DELETE' });
            setTrConfigured(false);
            setTrUrl('');
            setTrEmail('');
            setTrApiKey('');
            setTrApiKeyMasked('');
            setTrProjectId(null);
            setTrSuiteId(null);
            setTrConnectionStatus(null);
            setTrRemoteProjects([]);
            setTrRemoteSuites([]);
            setMessage({ type: 'success', text: 'TestRail configuration removed.' });
            setTimeout(() => setMessage(null), 3000);
        } catch {
            setMessage({ type: 'error', text: 'Failed to remove TestRail config' });
        }
    };

    // ── Jira handlers ────────────────────────────────────────────

    const handleJiraTestConnection = async () => {
        if (!currentProject?.id || !jiraUrl || !jiraEmail || (!jiraApiToken && !jiraConfigured)) return;
        setJiraTesting(true);
        setJiraConnectionStatus(null);

        try {
            if (jiraApiToken) {
                await fetch(`${API_BASE}/jira/${encodeURIComponent(currentProject.id)}/config`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        base_url: jiraUrl,
                        email: jiraEmail,
                        api_token: jiraApiToken,
                        project_key: jiraProjectKey,
                        issue_type_id: jiraIssueTypeId,
                    })
                });
            }

            const res = await fetch(`${API_BASE}/jira/${encodeURIComponent(currentProject.id)}/test-connection`, {
                method: 'POST',
            });
            const data = await res.json();

            if (res.ok) {
                setJiraConnectionStatus({ ok: true, message: `Connected as ${data.user}` });
                setJiraConfigured(true);
                loadJiraRemoteProjects();
            } else {
                setJiraConnectionStatus({ ok: false, message: data.detail || 'Connection failed' });
            }
        } catch (err: any) {
            setJiraConnectionStatus({ ok: false, message: err.message || 'Connection failed' });
        } finally {
            setJiraTesting(false);
        }
    };

    const loadJiraRemoteProjects = async () => {
        if (!currentProject?.id) return;
        setJiraLoadingProjects(true);
        try {
            const res = await fetch(`${API_BASE}/jira/${encodeURIComponent(currentProject.id)}/remote-projects`);
            if (res.ok) {
                setJiraRemoteProjects(await res.json());
            }
        } catch {
        } finally {
            setJiraLoadingProjects(false);
        }
    };

    const loadJiraRemoteIssueTypes = async (projectKey: string) => {
        if (!currentProject?.id) return;
        setJiraLoadingIssueTypes(true);
        try {
            const res = await fetch(`${API_BASE}/jira/${encodeURIComponent(currentProject.id)}/remote-issue-types/${projectKey}`);
            if (res.ok) {
                const types = await res.json();
                setJiraRemoteIssueTypes(types);
                if (types.length > 0 && !jiraIssueTypeId) {
                    const bugType = types.find((t: any) => t.name.toLowerCase() === 'bug');
                    if (bugType) setJiraIssueTypeId(bugType.id);
                }
            }
        } catch {
        } finally {
            setJiraLoadingIssueTypes(false);
        }
    };

    const handleJiraSave = async () => {
        if (!currentProject?.id) return;
        setJiraSaving(true);
        setMessage(null);

        try {
            const body: any = {
                base_url: jiraUrl,
                email: jiraEmail,
                project_key: jiraProjectKey,
                issue_type_id: jiraIssueTypeId,
            };
            if (jiraApiToken) {
                body.api_token = jiraApiToken;
            }

            const res = await fetch(`${API_BASE}/jira/${encodeURIComponent(currentProject.id)}/config`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });

            if (res.ok) {
                setJiraConfigured(true);
                setMessage({ type: 'success', text: 'Jira configuration saved!' });
                setTimeout(() => setMessage(null), 3000);
            } else {
                const data = await res.json();
                throw new Error(data.detail || 'Failed to save Jira config');
            }
        } catch (err: any) {
            setMessage({ type: 'error', text: err.message });
        } finally {
            setJiraSaving(false);
        }
    };

    const handleJiraDelete = async () => {
        if (!currentProject?.id) return;
        try {
            await fetch(`${API_BASE}/jira/${encodeURIComponent(currentProject.id)}/config`, { method: 'DELETE' });
            setJiraConfigured(false);
            setJiraUrl('');
            setJiraEmail('');
            setJiraApiToken('');
            setJiraApiTokenMasked('');
            setJiraProjectKey(null);
            setJiraIssueTypeId(null);
            setJiraConnectionStatus(null);
            setJiraRemoteProjects([]);
            setJiraRemoteIssueTypes([]);
            setMessage({ type: 'success', text: 'Jira configuration removed.' });
            setTimeout(() => setMessage(null), 3000);
        } catch {
            setMessage({ type: 'error', text: 'Failed to remove Jira config' });
        }
    };

    // ── GitLab handlers ────────────────────────────────────────────

    const handleGlTestConnection = async () => {
        if (!currentProject?.id || !glUrl || (!glToken && !glConfigured)) return;
        setGlTesting(true);
        setGlConnectionStatus(null);

        try {
            if (glToken) {
                await fetch(`${API_BASE}/gitlab/${encodeURIComponent(currentProject.id)}/config`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        gitlab_url: glUrl,
                        token: glToken,
                        project_id: glProjectId,
                        trigger_token: glTriggerToken || undefined,
                        default_ref: glDefaultRef,
                        webhook_secret: glWebhookSecret || undefined,
                    })
                });
            }

            const res = await fetch(`${API_BASE}/gitlab/${encodeURIComponent(currentProject.id)}/test-connection`, {
                method: 'POST',
            });
            const data = await res.json();

            if (res.ok) {
                setGlConnectionStatus({ ok: true, message: `Connected as ${data.user || data.username || 'authenticated'}` });
                setGlConfigured(true);
                loadGlRemoteProjects();
            } else {
                setGlConnectionStatus({ ok: false, message: data.detail || 'Connection failed' });
            }
        } catch (err: any) {
            setGlConnectionStatus({ ok: false, message: err.message || 'Connection failed' });
        } finally {
            setGlTesting(false);
        }
    };

    const loadGlRemoteProjects = async () => {
        if (!currentProject?.id) return;
        setGlLoadingProjects(true);
        try {
            const res = await fetch(`${API_BASE}/gitlab/${encodeURIComponent(currentProject.id)}/remote-projects`);
            if (res.ok) {
                setGlRemoteProjects(await res.json());
            }
        } catch {
        } finally {
            setGlLoadingProjects(false);
        }
    };

    const handleGlSave = async () => {
        if (!currentProject?.id) return;
        setGlSaving(true);
        setMessage(null);

        try {
            const body: any = {
                gitlab_url: glUrl,
                project_id: glProjectId,
                default_ref: glDefaultRef,
                webhook_secret: glWebhookSecret || undefined,
            };
            if (glToken) body.token = glToken;
            if (glTriggerToken) body.trigger_token = glTriggerToken;

            const res = await fetch(`${API_BASE}/gitlab/${encodeURIComponent(currentProject.id)}/config`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });

            if (res.ok) {
                setGlConfigured(true);
                setMessage({ type: 'success', text: 'GitLab configuration saved!' });
                setTimeout(() => setMessage(null), 3000);
            } else {
                const data = await res.json();
                throw new Error(data.detail || 'Failed to save GitLab config');
            }
        } catch (err: any) {
            setMessage({ type: 'error', text: err.message });
        } finally {
            setGlSaving(false);
        }
    };

    const handleGlDelete = async () => {
        if (!currentProject?.id) return;
        try {
            await fetch(`${API_BASE}/gitlab/${encodeURIComponent(currentProject.id)}/config`, { method: 'DELETE' });
            setGlConfigured(false);
            setGlUrl('');
            setGlToken('');
            setGlTokenMasked('');
            setGlProjectId(null);
            setGlTriggerToken('');
            setGlTriggerTokenMasked('');
            setGlDefaultRef('main');
            setGlWebhookSecret('');
            setGlConnectionStatus(null);
            setGlRemoteProjects([]);
            setMessage({ type: 'success', text: 'GitLab configuration removed.' });
            setTimeout(() => setMessage(null), 3000);
        } catch {
            setMessage({ type: 'error', text: 'Failed to remove GitLab config' });
        }
    };

    // ── GitHub handlers ────────────────────────────────────────────

    const handleGhTestConnection = async () => {
        if (!currentProject?.id || !ghOwner || (!ghToken && !ghConfigured)) return;
        setGhTesting(true);
        setGhConnectionStatus(null);

        try {
            if (ghToken) {
                await fetch(`${API_BASE}/github/${encodeURIComponent(currentProject.id)}/config`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        owner: ghOwner,
                        repo: ghRepo || undefined,
                        token: ghToken,
                        default_workflow: ghDefaultWorkflow || undefined,
                        default_ref: ghDefaultRef,
                        webhook_secret: ghWebhookSecret || undefined,
                    })
                });
            }

            const res = await fetch(`${API_BASE}/github/${encodeURIComponent(currentProject.id)}/test-connection`, {
                method: 'POST',
            });
            const data = await res.json();

            if (res.ok) {
                setGhConnectionStatus({ ok: true, message: `Connected as ${data.user || data.login || 'authenticated'}` });
                setGhConfigured(true);
                loadGhRemoteRepos();
            } else {
                setGhConnectionStatus({ ok: false, message: data.detail || 'Connection failed' });
            }
        } catch (err: any) {
            setGhConnectionStatus({ ok: false, message: err.message || 'Connection failed' });
        } finally {
            setGhTesting(false);
        }
    };

    const loadGhRemoteRepos = async () => {
        if (!currentProject?.id) return;
        setGhLoadingRepos(true);
        try {
            const res = await fetch(`${API_BASE}/github/${encodeURIComponent(currentProject.id)}/remote-repos`);
            if (res.ok) {
                setGhRemoteRepos(await res.json());
            }
        } catch {
        } finally {
            setGhLoadingRepos(false);
        }
    };

    const loadGhRemoteWorkflows = async () => {
        if (!currentProject?.id) return;
        setGhLoadingWorkflows(true);
        try {
            const res = await fetch(`${API_BASE}/github/${encodeURIComponent(currentProject.id)}/remote-workflows`);
            if (res.ok) {
                setGhRemoteWorkflows(await res.json());
            }
        } catch {
        } finally {
            setGhLoadingWorkflows(false);
        }
    };

    const handleGhSave = async () => {
        if (!currentProject?.id) return;
        setGhSaving(true);
        setMessage(null);

        try {
            const body: any = {
                owner: ghOwner,
                repo: ghRepo || undefined,
                default_workflow: ghDefaultWorkflow || undefined,
                default_ref: ghDefaultRef,
                webhook_secret: ghWebhookSecret || undefined,
            };
            if (ghToken) body.token = ghToken;

            const res = await fetch(`${API_BASE}/github/${encodeURIComponent(currentProject.id)}/config`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });

            if (res.ok) {
                setGhConfigured(true);
                setMessage({ type: 'success', text: 'GitHub configuration saved!' });
                setTimeout(() => setMessage(null), 3000);
            } else {
                const data = await res.json();
                throw new Error(data.detail || 'Failed to save GitHub config');
            }
        } catch (err: any) {
            setMessage({ type: 'error', text: err.message });
        } finally {
            setGhSaving(false);
        }
    };

    const handleGhDelete = async () => {
        if (!currentProject?.id) return;
        try {
            await fetch(`${API_BASE}/github/${encodeURIComponent(currentProject.id)}/config`, { method: 'DELETE' });
            setGhConfigured(false);
            setGhOwner('');
            setGhRepo('');
            setGhToken('');
            setGhTokenMasked('');
            setGhDefaultWorkflow('');
            setGhDefaultRef('main');
            setGhWebhookSecret('');
            setGhConnectionStatus(null);
            setGhRemoteRepos([]);
            setGhRemoteWorkflows([]);
            setMessage({ type: 'success', text: 'GitHub configuration removed.' });
            setTimeout(() => setMessage(null), 3000);
        } catch {
            setMessage({ type: 'error', text: 'Failed to remove GitHub config' });
        }
    };

    if (loading) return (
        <PageLayout tier="narrow">
            <FormPageSkeleton fields={6} />
        </PageLayout>
    );

    return (
        <PageLayout tier="narrow">
            <PageHeader
                title="Settings"
                subtitle="Configure your AI agents and environment preferences."
                icon={<Settings size={20} />}
            />

            {message && (
                <div style={{
                    padding: '1rem',
                    marginBottom: '1.5rem',
                    borderRadius: 'var(--radius)',
                    background: message.type === 'success' ? 'var(--success-muted)' : 'var(--danger-muted)',
                    border: `1px solid ${message.type === 'success' ? 'rgba(52, 211, 153, 0.2)' : 'rgba(248, 113, 113, 0.2)'}`,
                    color: message.type === 'success' ? 'var(--success)' : 'var(--danger)',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '0.75rem',
                    fontWeight: 500
                }}>
                    {message.type === 'success' ? <CheckCircle size={20} /> : <AlertCircle size={20} />}
                    {message.text}
                </div>
            )}

            <form onSubmit={handleSubmit} className="card" style={{ display: 'flex', flexDirection: 'column', gap: '2rem', boxShadow: 'var(--shadow-card)' }}>
                <div className="form-group">
                    <label className="label">LLM Provider</label>
                    <div className="input-group">
                        <div className="input-icon">
                            <Server size={18} />
                        </div>
                        <select
                            name="llm_provider"
                            value={settings.llm_provider}
                            onChange={handleChange}
                            className="input has-icon"
                        >
                            <option value="anthropic">Anthropic (Claude)</option>
                            <option value="openrouter">OpenRouter (Free Models Available)</option>
                            <option value="custom">Custom</option>
                        </select>
                    </div>
                </div>

                <div className="form-group">
                    <label className="label">API Key</label>
                    <div className="input-group">
                        <div className="input-icon">
                            <Key size={18} />
                        </div>
                        <input
                            type={showApiKey ? "text" : "password"}
                            name="api_key"
                            value={settings.api_key}
                            onChange={handleChange}
                            placeholder={settings.llm_provider === 'openrouter' ? 'sk-or-v1-...' : 'sk-...'}
                            className="input has-icon"
                            style={{ paddingRight: '2.5rem' }}
                        />
                        <button
                            type="button"
                            className="visibility-toggle"
                            onClick={() => setShowApiKey(!showApiKey)}
                            title={showApiKey ? "Hide API Key" : "Show API Key"}
                        >
                            {showApiKey ? <EyeOff size={18} /> : <Eye size={18} />}
                        </button>
                    </div>
                    <p className="helper-text">
                        Stored locally in project .env file
                    </p>
                </div>

                <div className="form-group">
                    <label className="label">Base URL <span style={{ color: 'var(--text-secondary)', fontWeight: 400 }}>(Optional)</span></label>
                    <div className="input-group">
                        <div className="input-icon">
                            <Globe size={18} />
                        </div>
                        <input
                            type="text"
                            name="base_url"
                            value={settings.base_url}
                            onChange={handleChange}
                            placeholder={settings.llm_provider === 'openrouter' ? 'https://openrouter.ai/api' : 'https://api.anthropic.com'}
                            className="input has-icon"
                        />
                    </div>
                    {settings.llm_provider === 'openrouter' && (
                        <p className="helper-text" style={{ marginTop: '0.5rem' }}>
                            Use <strong>https://openrouter.ai/api</strong> to access free models.
                            <a href="https://openrouter.ai/models" target="_blank" rel="noopener noreferrer"
                                style={{ color: 'var(--primary)', textDecoration: 'underline', marginLeft: '0.25rem' }}>
                                Browse available models
                            </a>
                        </p>
                    )}
                </div>

                <div className="form-group">
                    <label className="label">Default Model</label>
                    <div className="input-group">
                        <div className="input-icon">
                            <Box size={18} />
                        </div>
                        <input
                            type="text"
                            name="model_name"
                            value={settings.model_name}
                            onChange={handleChange}
                            placeholder={
                                settings.llm_provider === 'openrouter'
                                    ? 'meta-llama/llama-3.2-3b-instruct:free'
                                    : 'claude-3-5-sonnet-20240620'
                            }
                            className="input has-icon"
                        />
                    </div>
                    {settings.llm_provider === 'openrouter' && (
                        <p className="helper-text" style={{ marginTop: '0.5rem' }}>
                            Free models: <code>meta-llama/llama-3.2-3b-instruct:free</code>,
                            <code>google/gemini-2.0-flash-exp:free</code>,
                            <code>microsoft/phi-3-mini-128k-instruct:free</code>
                        </p>
                    )}
                </div>

                <div style={{ paddingTop: '1.5rem', borderTop: '1px solid var(--border)', display: 'flex', justifyContent: 'flex-end' }}>
                    <button
                        type="submit"
                        className="btn btn-primary"
                        disabled={saving}
                        style={{
                            minWidth: '140px',
                            justifyContent: 'center',
                            opacity: saving ? 0.7 : 1
                        }}
                    >
                        {saving ? (
                            <>Saving...</>
                        ) : (
                            <>
                                <Save size={18} />
                                Save Settings
                            </>
                        )}
                    </button>
                </div>
            </form>

            {/* Execution Settings Section */}
            <div style={{ marginTop: '2rem' }}>
                <h2 style={{ fontSize: '1.5rem', marginBottom: '1rem', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                    <Layers size={24} />
                    Execution Settings
                </h2>

                <form onSubmit={handleExecutionSubmit} className="card" style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem', boxShadow: 'var(--shadow-card)' }}>

                    {/* Database Type Indicator */}
                    <div style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: '0.75rem',
                        padding: '1rem',
                        borderRadius: 'var(--radius)',
                        background: executionSettings.database_type === 'postgresql' ? 'var(--success-muted)' : 'var(--warning-muted)',
                        border: `1px solid ${executionSettings.database_type === 'postgresql' ? 'rgba(52, 211, 153, 0.2)' : 'rgba(251, 191, 36, 0.2)'}`
                    }}>
                        <Database size={20} color={executionSettings.database_type === 'postgresql' ? 'var(--success)' : 'var(--warning)'} />
                        <div>
                            <div style={{ fontWeight: 600, textTransform: 'capitalize' }}>
                                {executionSettings.database_type === 'postgresql' ? 'PostgreSQL' : 'SQLite'} Database
                            </div>
                            <div style={{ fontSize: '0.875rem', color: 'var(--text-secondary)' }}>
                                {executionSettings.database_type === 'postgresql'
                                    ? 'Full parallel execution support available'
                                    : 'Parallel execution limited due to write locking'}
                            </div>
                        </div>
                    </div>

                    {/* Parallelism Slider */}
                    <div className="form-group">
                        <label className="label" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                            <Zap size={18} />
                            Parallelism
                        </label>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
                            <input
                                type="range"
                                min="1"
                                max="5"
                                value={executionSettings.parallelism}
                                onChange={(e) => handleExecutionChange('parallelism', parseInt(e.target.value))}
                                disabled={!executionSettings.parallel_mode_available && executionSettings.parallelism > 1}
                                style={{ flex: 1 }}
                            />
                            <span style={{
                                minWidth: '40px',
                                textAlign: 'center',
                                fontWeight: 600,
                                fontSize: '1.1rem'
                            }}>
                                {executionSettings.parallelism}
                            </span>
                        </div>
                        <p className="helper-text">
                            Maximum concurrent test executions (1-5).
                            {!executionSettings.parallel_mode_available && executionSettings.parallelism > 1 && (
                                <span style={{ color: 'var(--warning)', display: 'block', marginTop: '0.25rem' }}>
                                    PostgreSQL required for parallelism &gt; 1
                                </span>
                            )}
                        </p>
                    </div>

                    {/* Headless Mode Toggle */}
                    <div className="form-group">
                        <label className="label" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                            <Monitor size={18} />
                            Headless Mode in Parallel
                        </label>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
                            <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'pointer' }}>
                                <input
                                    type="checkbox"
                                    checked={executionSettings.headless_in_parallel}
                                    onChange={(e) => handleExecutionChange('headless_in_parallel', e.target.checked)}
                                    style={{ width: '18px', height: '18px' }}
                                />
                                <span>Force headless mode when running multiple tests</span>
                            </label>
                        </div>
                        <p className="helper-text">
                            Recommended when parallelism &gt; 1 to avoid display conflicts.
                        </p>
                    </div>

                    {/* Memory System Toggle */}
                    <div className="form-group">
                        <label className="label" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                            <HardDrive size={18} />
                            Memory System
                        </label>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
                            <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'pointer' }}>
                                <input
                                    type="checkbox"
                                    checked={executionSettings.memory_enabled}
                                    onChange={(e) => handleExecutionChange('memory_enabled', e.target.checked)}
                                    style={{ width: '18px', height: '18px' }}
                                />
                                <span>Enable memory system</span>
                            </label>
                        </div>
                        <p className="helper-text">
                            Disable in parallel mode for better performance (ChromaDB singleton limitation).
                        </p>
                    </div>

                    <div style={{ paddingTop: '1.5rem', borderTop: '1px solid var(--border)', display: 'flex', justifyContent: 'flex-end' }}>
                        <button
                            type="submit"
                            className="btn btn-primary"
                            disabled={savingExecution || (!executionSettings.parallel_mode_available && executionSettings.parallelism > 1)}
                            style={{
                                minWidth: '180px',
                                justifyContent: 'center',
                                opacity: savingExecution ? 0.7 : 1
                            }}
                        >
                            {savingExecution ? (
                                <>Saving...</>
                            ) : (
                                <>
                                    <Save size={18} />
                                    Save Execution Settings
                                </>
                            )}
                        </button>
                    </div>
                </form>
            </div>

            {/* TestRail Integration Section */}
            <div style={{ marginTop: '2rem' }}>
                <h2 style={{ fontSize: '1.5rem', marginBottom: '1rem', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                    <Link2 size={24} />
                    TestRail Integration
                </h2>

                {currentProject ? (
                    <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem', boxShadow: 'var(--shadow-card)' }}>
                        <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem', margin: 0 }}>
                            Connect to TestRail to push test cases directly from your specs.
                        </p>

                        {/* TestRail URL */}
                        <div className="form-group">
                            <label className="label">TestRail URL</label>
                            <div className="input-group">
                                <div className="input-icon">
                                    <Globe size={18} />
                                </div>
                                <input
                                    type="text"
                                    value={trUrl}
                                    onChange={e => setTrUrl(e.target.value)}
                                    placeholder="https://company.testrail.io"
                                    className="input has-icon"
                                />
                            </div>
                        </div>

                        {/* Email */}
                        <div className="form-group">
                            <label className="label">Email</label>
                            <div className="input-group">
                                <div className="input-icon">
                                    <Mail size={18} />
                                </div>
                                <input
                                    type="email"
                                    value={trEmail}
                                    onChange={e => setTrEmail(e.target.value)}
                                    placeholder="user@company.com"
                                    className="input has-icon"
                                />
                            </div>
                        </div>

                        {/* API Key */}
                        <div className="form-group">
                            <label className="label">
                                API Key
                                {trConfigured && (
                                    <span style={{ color: 'var(--text-secondary)', fontWeight: 400, marginLeft: '0.5rem', fontSize: '0.85rem' }}>
                                        (enter new key to update)
                                    </span>
                                )}
                            </label>
                            <div className="input-group">
                                <div className="input-icon">
                                    <Key size={18} />
                                </div>
                                <input
                                    type={showTrApiKey ? "text" : "password"}
                                    value={trApiKey}
                                    onChange={e => setTrApiKey(e.target.value)}
                                    placeholder={trConfigured && trApiKeyMasked ? trApiKeyMasked : "Your TestRail API key"}
                                    className="input has-icon"
                                    style={{ paddingRight: '2.5rem' }}
                                />
                                <button
                                    type="button"
                                    className="visibility-toggle"
                                    onClick={() => setShowTrApiKey(!showTrApiKey)}
                                    title={showTrApiKey ? "Hide" : "Show"}
                                >
                                    {showTrApiKey ? <EyeOff size={18} /> : <Eye size={18} />}
                                </button>
                            </div>
                            <p className="helper-text">
                                Find your API key in TestRail under My Settings &gt; API Keys
                            </p>
                        </div>

                        {/* Test Connection */}
                        <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
                            <button
                                type="button"
                                className="btn btn-secondary"
                                onClick={handleTrTestConnection}
                                disabled={trTesting || !trUrl || !trEmail || (!trApiKey && !trConfigured)}
                                style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}
                            >
                                {trTesting ? <Loader2 size={16} className="animate-spin" style={{ animation: 'spin 1s linear infinite' }} /> : <Link2 size={16} />}
                                {trTesting ? 'Testing...' : 'Test Connection'}
                            </button>
                            {trConnectionStatus && (
                                <span style={{
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: '0.4rem',
                                    fontSize: '0.9rem',
                                    color: trConnectionStatus.ok ? 'var(--success)' : 'var(--danger)',
                                    fontWeight: 500,
                                }}>
                                    {trConnectionStatus.ok ? <CheckCircle size={16} /> : <AlertCircle size={16} />}
                                    {trConnectionStatus.message}
                                </span>
                            )}
                        </div>

                        {/* TestRail Project dropdown */}
                        {trConnectionStatus?.ok && (
                            <>
                                <div className="form-group">
                                    <label className="label">TestRail Project</label>
                                    <div className="input-group">
                                        <div className="input-icon">
                                            <ChevronDown size={18} />
                                        </div>
                                        <select
                                            value={trProjectId ?? ''}
                                            onChange={e => {
                                                const val = e.target.value ? parseInt(e.target.value) : null;
                                                setTrProjectId(val);
                                                setTrSuiteId(null);
                                                setTrRemoteSuites([]);
                                                if (val) loadRemoteSuites(val);
                                            }}
                                            className="input has-icon"
                                            disabled={trLoadingProjects}
                                        >
                                            <option value="">Select a project...</option>
                                            {trRemoteProjects.filter(p => !p.is_completed).map(p => (
                                                <option key={p.id} value={p.id}>{p.name}</option>
                                            ))}
                                        </select>
                                    </div>
                                </div>

                                {/* TestRail Suite dropdown */}
                                {trProjectId && (
                                    <div className="form-group">
                                        <label className="label">TestRail Suite</label>
                                        <div className="input-group">
                                            <div className="input-icon">
                                                <ChevronDown size={18} />
                                            </div>
                                            <select
                                                value={trSuiteId ?? ''}
                                                onChange={e => setTrSuiteId(e.target.value ? parseInt(e.target.value) : null)}
                                                className="input has-icon"
                                                disabled={trLoadingSuites}
                                            >
                                                <option value="">Select a suite...</option>
                                                {trRemoteSuites.map(s => (
                                                    <option key={s.id} value={s.id}>{s.name}</option>
                                                ))}
                                            </select>
                                        </div>
                                    </div>
                                )}
                            </>
                        )}

                        {/* Save / Delete */}
                        <div style={{ paddingTop: '1.5rem', borderTop: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between' }}>
                            {trConfigured && (
                                <button
                                    type="button"
                                    className="btn"
                                    onClick={handleTrDelete}
                                    style={{ color: 'var(--danger)', background: 'transparent', border: '1px solid var(--danger)' }}
                                >
                                    Remove
                                </button>
                            )}
                            <div style={{ marginLeft: 'auto' }}>
                                <button
                                    type="button"
                                    className="btn btn-primary"
                                    onClick={handleTrSave}
                                    disabled={trSaving || !trUrl || !trEmail}
                                    style={{
                                        minWidth: '140px',
                                        justifyContent: 'center',
                                        opacity: trSaving ? 0.7 : 1,
                                        display: 'flex',
                                        alignItems: 'center',
                                        gap: '0.5rem',
                                    }}
                                >
                                    {trSaving ? 'Saving...' : <><Save size={18} /> Save</>}
                                </button>
                            </div>
                        </div>
                    </div>
                ) : (
                    <div className="card" style={{
                        padding: '2rem',
                        textAlign: 'center',
                        color: 'var(--text-secondary)',
                        boxShadow: 'var(--shadow-card)'
                    }}>
                        <Link2 size={32} style={{ marginBottom: '0.75rem', opacity: 0.5 }} />
                        <div style={{ fontWeight: 500, marginBottom: '0.25rem' }}>No project selected</div>
                        <div style={{ fontSize: '0.875rem' }}>Select a project to configure TestRail integration</div>
                    </div>
                )}
            </div>

            {/* Jira Integration Section */}
            <div style={{ marginTop: '2rem' }}>
                <h2 style={{ fontSize: '1.5rem', marginBottom: '1rem', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                    <Bug size={24} />
                    Jira Integration
                </h2>

                {currentProject ? (
                    <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem', boxShadow: 'var(--shadow-card)' }}>
                        <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem', margin: 0 }}>
                            Connect to Jira to create bug reports from failed test runs with AI-generated descriptions.
                        </p>

                        {/* Jira URL */}
                        <div className="form-group">
                            <label className="label">Jira URL</label>
                            <div className="input-group">
                                <div className="input-icon">
                                    <Globe size={18} />
                                </div>
                                <input
                                    type="text"
                                    value={jiraUrl}
                                    onChange={e => setJiraUrl(e.target.value)}
                                    placeholder="https://company.atlassian.net"
                                    className="input has-icon"
                                />
                            </div>
                        </div>

                        {/* Email */}
                        <div className="form-group">
                            <label className="label">Email</label>
                            <div className="input-group">
                                <div className="input-icon">
                                    <Mail size={18} />
                                </div>
                                <input
                                    type="email"
                                    value={jiraEmail}
                                    onChange={e => setJiraEmail(e.target.value)}
                                    placeholder="user@company.com"
                                    className="input has-icon"
                                />
                            </div>
                        </div>

                        {/* API Token */}
                        <div className="form-group">
                            <label className="label">
                                API Token
                                {jiraConfigured && (
                                    <span style={{ color: 'var(--text-secondary)', fontWeight: 400, marginLeft: '0.5rem', fontSize: '0.85rem' }}>
                                        (enter new token to update)
                                    </span>
                                )}
                            </label>
                            <div className="input-group">
                                <div className="input-icon">
                                    <Key size={18} />
                                </div>
                                <input
                                    type={showJiraApiToken ? "text" : "password"}
                                    value={jiraApiToken}
                                    onChange={e => setJiraApiToken(e.target.value)}
                                    placeholder={jiraConfigured && jiraApiTokenMasked ? jiraApiTokenMasked : "Your Jira API token"}
                                    className="input has-icon"
                                    style={{ paddingRight: '2.5rem' }}
                                />
                                <button
                                    type="button"
                                    className="visibility-toggle"
                                    onClick={() => setShowJiraApiToken(!showJiraApiToken)}
                                    title={showJiraApiToken ? "Hide" : "Show"}
                                >
                                    {showJiraApiToken ? <EyeOff size={18} /> : <Eye size={18} />}
                                </button>
                            </div>
                            <p className="helper-text">
                                Generate an API token at <a href="https://id.atlassian.com/manage-profile/security/api-tokens" target="_blank" rel="noopener noreferrer" style={{ color: 'var(--primary)' }}>Atlassian Account Settings</a>
                            </p>
                        </div>

                        {/* Test Connection */}
                        <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
                            <button
                                type="button"
                                className="btn btn-secondary"
                                onClick={handleJiraTestConnection}
                                disabled={jiraTesting || !jiraUrl || !jiraEmail || (!jiraApiToken && !jiraConfigured)}
                                style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}
                            >
                                {jiraTesting ? <Loader2 size={16} className="animate-spin" style={{ animation: 'spin 1s linear infinite' }} /> : <Link2 size={16} />}
                                {jiraTesting ? 'Testing...' : 'Test Connection'}
                            </button>
                            {jiraConnectionStatus && (
                                <span style={{
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: '0.4rem',
                                    fontSize: '0.9rem',
                                    color: jiraConnectionStatus.ok ? 'var(--success)' : 'var(--danger)',
                                    fontWeight: 500,
                                }}>
                                    {jiraConnectionStatus.ok ? <CheckCircle size={16} /> : <AlertCircle size={16} />}
                                    {jiraConnectionStatus.message}
                                </span>
                            )}
                        </div>

                        {/* Jira Project + Issue Type dropdowns */}
                        {jiraConnectionStatus?.ok && (
                            <>
                                <div className="form-group">
                                    <label className="label">Jira Project</label>
                                    <div className="input-group">
                                        <div className="input-icon">
                                            <ChevronDown size={18} />
                                        </div>
                                        <select
                                            value={jiraProjectKey ?? ''}
                                            onChange={e => {
                                                const val = e.target.value || null;
                                                setJiraProjectKey(val);
                                                setJiraIssueTypeId(null);
                                                setJiraRemoteIssueTypes([]);
                                                if (val) loadJiraRemoteIssueTypes(val);
                                            }}
                                            className="input has-icon"
                                            disabled={jiraLoadingProjects}
                                        >
                                            <option value="">Select a project...</option>
                                            {jiraRemoteProjects.map(p => (
                                                <option key={p.key} value={p.key}>{p.name} ({p.key})</option>
                                            ))}
                                        </select>
                                    </div>
                                </div>

                                {jiraProjectKey && (
                                    <div className="form-group">
                                        <label className="label">Default Issue Type</label>
                                        <div className="input-group">
                                            <div className="input-icon">
                                                <ChevronDown size={18} />
                                            </div>
                                            <select
                                                value={jiraIssueTypeId ?? ''}
                                                onChange={e => setJiraIssueTypeId(e.target.value || null)}
                                                className="input has-icon"
                                                disabled={jiraLoadingIssueTypes}
                                            >
                                                <option value="">Select an issue type...</option>
                                                {jiraRemoteIssueTypes.map(it => (
                                                    <option key={it.id} value={it.id}>{it.name}</option>
                                                ))}
                                            </select>
                                        </div>
                                    </div>
                                )}
                            </>
                        )}

                        {/* Save / Delete */}
                        <div style={{ paddingTop: '1.5rem', borderTop: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between' }}>
                            {jiraConfigured && (
                                <button
                                    type="button"
                                    className="btn"
                                    onClick={handleJiraDelete}
                                    style={{ color: 'var(--danger)', background: 'transparent', border: '1px solid var(--danger)' }}
                                >
                                    Remove
                                </button>
                            )}
                            <div style={{ marginLeft: 'auto' }}>
                                <button
                                    type="button"
                                    className="btn btn-primary"
                                    onClick={handleJiraSave}
                                    disabled={jiraSaving || !jiraUrl || !jiraEmail}
                                    style={{
                                        minWidth: '140px',
                                        justifyContent: 'center',
                                        opacity: jiraSaving ? 0.7 : 1,
                                        display: 'flex',
                                        alignItems: 'center',
                                        gap: '0.5rem',
                                    }}
                                >
                                    {jiraSaving ? 'Saving...' : <><Save size={18} /> Save</>}
                                </button>
                            </div>
                        </div>
                    </div>
                ) : (
                    <div className="card" style={{
                        padding: '2rem',
                        textAlign: 'center',
                        color: 'var(--text-secondary)',
                        boxShadow: 'var(--shadow-card)'
                    }}>
                        <Bug size={32} style={{ marginBottom: '0.75rem', opacity: 0.5 }} />
                        <div style={{ fontWeight: 500, marginBottom: '0.25rem' }}>No project selected</div>
                        <div style={{ fontSize: '0.875rem' }}>Select a project to configure Jira integration</div>
                    </div>
                )}
            </div>

            {/* GitLab Integration Section */}
            <div style={{ marginTop: '2rem' }}>
                <h2 style={{ fontSize: '1.5rem', marginBottom: '1rem', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                    <GitBranch size={24} />
                    GitLab Integration
                </h2>

                {currentProject ? (
                    <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem', boxShadow: 'var(--shadow-card)' }}>
                        <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem', margin: 0 }}>
                            Connect to GitLab to trigger and track CI/CD pipelines.
                        </p>

                        {/* GitLab URL */}
                        <div className="form-group">
                            <label className="label">GitLab URL</label>
                            <div className="input-group">
                                <div className="input-icon">
                                    <Globe size={18} />
                                </div>
                                <input
                                    type="text"
                                    value={glUrl}
                                    onChange={e => setGlUrl(e.target.value)}
                                    placeholder="https://gitlab.com"
                                    className="input has-icon"
                                />
                            </div>
                        </div>

                        {/* Personal Access Token */}
                        <div className="form-group">
                            <label className="label">
                                Personal Access Token
                                {glConfigured && (
                                    <span style={{ color: 'var(--text-secondary)', fontWeight: 400, marginLeft: '0.5rem', fontSize: '0.85rem' }}>
                                        (enter new token to update)
                                    </span>
                                )}
                            </label>
                            <div className="input-group">
                                <div className="input-icon">
                                    <Key size={18} />
                                </div>
                                <input
                                    type={showGlToken ? "text" : "password"}
                                    value={glToken}
                                    onChange={e => setGlToken(e.target.value)}
                                    placeholder={glConfigured && glTokenMasked ? glTokenMasked : "glpat-..."}
                                    className="input has-icon"
                                    style={{ paddingRight: '2.5rem' }}
                                />
                                <button
                                    type="button"
                                    className="visibility-toggle"
                                    onClick={() => setShowGlToken(!showGlToken)}
                                    title={showGlToken ? "Hide" : "Show"}
                                >
                                    {showGlToken ? <EyeOff size={18} /> : <Eye size={18} />}
                                </button>
                            </div>
                            <p className="helper-text">
                                Requires <code>api</code> scope. Create at GitLab Settings &gt; Access Tokens.
                            </p>
                        </div>

                        {/* Test Connection */}
                        <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
                            <button
                                type="button"
                                className="btn btn-secondary"
                                onClick={handleGlTestConnection}
                                disabled={glTesting || !glUrl || (!glToken && !glConfigured)}
                                style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}
                            >
                                {glTesting ? <Loader2 size={16} className="animate-spin" style={{ animation: 'spin 1s linear infinite' }} /> : <Link2 size={16} />}
                                {glTesting ? 'Testing...' : 'Test Connection'}
                            </button>
                            {glConnectionStatus && (
                                <span style={{
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: '0.4rem',
                                    fontSize: '0.9rem',
                                    color: glConnectionStatus.ok ? 'var(--success)' : 'var(--danger)',
                                    fontWeight: 500,
                                }}>
                                    {glConnectionStatus.ok ? <CheckCircle size={16} /> : <AlertCircle size={16} />}
                                    {glConnectionStatus.message}
                                </span>
                            )}
                        </div>

                        {/* GitLab Project dropdown */}
                        {glConnectionStatus?.ok && (
                            <div className="form-group">
                                <label className="label">GitLab Project</label>
                                <div className="input-group">
                                    <div className="input-icon">
                                        <ChevronDown size={18} />
                                    </div>
                                    <select
                                        value={glProjectId ?? ''}
                                        onChange={e => setGlProjectId(e.target.value || null)}
                                        className="input has-icon"
                                        disabled={glLoadingProjects}
                                    >
                                        <option value="">Select a project...</option>
                                        {glRemoteProjects.map(p => (
                                            <option key={p.id} value={String(p.id)}>{p.name} ({p.path_with_namespace})</option>
                                        ))}
                                    </select>
                                </div>
                            </div>
                        )}

                        {/* Trigger Token */}
                        <div className="form-group">
                            <label className="label">
                                Trigger Token
                                {glConfigured && glTriggerTokenMasked && (
                                    <span style={{ color: 'var(--text-secondary)', fontWeight: 400, marginLeft: '0.5rem', fontSize: '0.85rem' }}>
                                        (enter new token to update)
                                    </span>
                                )}
                            </label>
                            <div className="input-group">
                                <div className="input-icon">
                                    <Key size={18} />
                                </div>
                                <input
                                    type={showGlTriggerToken ? "text" : "password"}
                                    value={glTriggerToken}
                                    onChange={e => setGlTriggerToken(e.target.value)}
                                    placeholder={glConfigured && glTriggerTokenMasked ? glTriggerTokenMasked : "Pipeline trigger token"}
                                    className="input has-icon"
                                    style={{ paddingRight: '2.5rem' }}
                                />
                                <button
                                    type="button"
                                    className="visibility-toggle"
                                    onClick={() => setShowGlTriggerToken(!showGlTriggerToken)}
                                    title={showGlTriggerToken ? "Hide" : "Show"}
                                >
                                    {showGlTriggerToken ? <EyeOff size={18} /> : <Eye size={18} />}
                                </button>
                            </div>
                            <p className="helper-text">
                                Used to trigger pipelines remotely. Create at CI/CD Settings &gt; Pipeline triggers.
                            </p>
                        </div>

                        {/* Default Branch */}
                        <div className="form-group">
                            <label className="label">Default Branch</label>
                            <div className="input-group">
                                <div className="input-icon">
                                    <GitMerge size={18} />
                                </div>
                                <input
                                    type="text"
                                    value={glDefaultRef}
                                    onChange={e => setGlDefaultRef(e.target.value)}
                                    placeholder="main"
                                    className="input has-icon"
                                />
                            </div>
                        </div>

                        {/* Webhook Secret */}
                        <div className="form-group">
                            <label className="label">Webhook Secret <span style={{ color: 'var(--text-secondary)', fontWeight: 400 }}>(Optional)</span></label>
                            <div className="input-group">
                                <div className="input-icon">
                                    <Lock size={18} />
                                </div>
                                <input
                                    type="text"
                                    value={glWebhookSecret}
                                    onChange={e => setGlWebhookSecret(e.target.value)}
                                    placeholder="Webhook secret token"
                                    className="input has-icon"
                                />
                            </div>
                        </div>

                        {/* Save / Delete */}
                        <div style={{ paddingTop: '1.5rem', borderTop: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between' }}>
                            {glConfigured && (
                                <button
                                    type="button"
                                    className="btn"
                                    onClick={handleGlDelete}
                                    style={{ color: 'var(--danger)', background: 'transparent', border: '1px solid var(--danger)' }}
                                >
                                    Remove
                                </button>
                            )}
                            <div style={{ marginLeft: 'auto' }}>
                                <button
                                    type="button"
                                    className="btn btn-primary"
                                    onClick={handleGlSave}
                                    disabled={glSaving || !glUrl}
                                    style={{
                                        minWidth: '140px',
                                        justifyContent: 'center',
                                        opacity: glSaving ? 0.7 : 1,
                                        display: 'flex',
                                        alignItems: 'center',
                                        gap: '0.5rem',
                                    }}
                                >
                                    {glSaving ? 'Saving...' : <><Save size={18} /> Save</>}
                                </button>
                            </div>
                        </div>
                    </div>
                ) : (
                    <div className="card" style={{
                        padding: '2rem',
                        textAlign: 'center',
                        color: 'var(--text-secondary)',
                        boxShadow: 'var(--shadow-card)'
                    }}>
                        <GitBranch size={32} style={{ marginBottom: '0.75rem', opacity: 0.5 }} />
                        <div style={{ fontWeight: 500, marginBottom: '0.25rem' }}>No project selected</div>
                        <div style={{ fontSize: '0.875rem' }}>Select a project to configure GitLab integration</div>
                    </div>
                )}
            </div>

            {/* GitHub Integration Section */}
            <div style={{ marginTop: '2rem' }}>
                <h2 style={{ fontSize: '1.5rem', marginBottom: '1rem', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                    <GitMerge size={24} />
                    GitHub Integration
                </h2>

                {currentProject ? (
                    <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem', boxShadow: 'var(--shadow-card)' }}>
                        <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem', margin: 0 }}>
                            Connect to GitHub to trigger and track Actions workflows.
                        </p>

                        {/* Owner / Organization */}
                        <div className="form-group">
                            <label className="label">Owner / Organization</label>
                            <div className="input-group">
                                <div className="input-icon">
                                    <Globe size={18} />
                                </div>
                                <input
                                    type="text"
                                    value={ghOwner}
                                    onChange={e => setGhOwner(e.target.value)}
                                    placeholder="e.g., my-org"
                                    className="input has-icon"
                                />
                            </div>
                        </div>

                        {/* Personal Access Token */}
                        <div className="form-group">
                            <label className="label">
                                Personal Access Token
                                {ghConfigured && (
                                    <span style={{ color: 'var(--text-secondary)', fontWeight: 400, marginLeft: '0.5rem', fontSize: '0.85rem' }}>
                                        (enter new token to update)
                                    </span>
                                )}
                            </label>
                            <div className="input-group">
                                <div className="input-icon">
                                    <Key size={18} />
                                </div>
                                <input
                                    type={showGhToken ? "text" : "password"}
                                    value={ghToken}
                                    onChange={e => setGhToken(e.target.value)}
                                    placeholder={ghConfigured && ghTokenMasked ? ghTokenMasked : "ghp_..."}
                                    className="input has-icon"
                                    style={{ paddingRight: '2.5rem' }}
                                />
                                <button
                                    type="button"
                                    className="visibility-toggle"
                                    onClick={() => setShowGhToken(!showGhToken)}
                                    title={showGhToken ? "Hide" : "Show"}
                                >
                                    {showGhToken ? <EyeOff size={18} /> : <Eye size={18} />}
                                </button>
                            </div>
                            <p className="helper-text">
                                Requires <code>repo</code> and <code>workflow</code> scopes.
                            </p>
                        </div>

                        {/* Test Connection */}
                        <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
                            <button
                                type="button"
                                className="btn btn-secondary"
                                onClick={handleGhTestConnection}
                                disabled={ghTesting || !ghOwner || (!ghToken && !ghConfigured)}
                                style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}
                            >
                                {ghTesting ? <Loader2 size={16} className="animate-spin" style={{ animation: 'spin 1s linear infinite' }} /> : <Link2 size={16} />}
                                {ghTesting ? 'Testing...' : 'Test Connection'}
                            </button>
                            {ghConnectionStatus && (
                                <span style={{
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: '0.4rem',
                                    fontSize: '0.9rem',
                                    color: ghConnectionStatus.ok ? 'var(--success)' : 'var(--danger)',
                                    fontWeight: 500,
                                }}>
                                    {ghConnectionStatus.ok ? <CheckCircle size={16} /> : <AlertCircle size={16} />}
                                    {ghConnectionStatus.message}
                                </span>
                            )}
                        </div>

                        {/* Repository dropdown */}
                        {ghConnectionStatus?.ok && (
                            <>
                                <div className="form-group">
                                    <label className="label">Repository</label>
                                    <div className="input-group">
                                        <div className="input-icon">
                                            <ChevronDown size={18} />
                                        </div>
                                        <select
                                            value={ghRepo}
                                            onChange={e => {
                                                setGhRepo(e.target.value);
                                                setGhRemoteWorkflows([]);
                                                setGhDefaultWorkflow('');
                                                if (e.target.value) {
                                                    // Reload workflows after repo change
                                                    setTimeout(loadGhRemoteWorkflows, 100);
                                                }
                                            }}
                                            className="input has-icon"
                                            disabled={ghLoadingRepos}
                                        >
                                            <option value="">Select a repository...</option>
                                            {ghRemoteRepos.map(r => (
                                                <option key={r.full_name} value={r.name}>{r.full_name}</option>
                                            ))}
                                        </select>
                                    </div>
                                </div>

                                {/* Default Workflow dropdown */}
                                {ghRepo && (
                                    <div className="form-group">
                                        <label className="label">Default Workflow</label>
                                        <div className="input-group">
                                            <div className="input-icon">
                                                <ChevronDown size={18} />
                                            </div>
                                            <select
                                                value={ghDefaultWorkflow}
                                                onChange={e => setGhDefaultWorkflow(e.target.value)}
                                                className="input has-icon"
                                                disabled={ghLoadingWorkflows}
                                            >
                                                <option value="">Select a workflow...</option>
                                                {ghRemoteWorkflows.map(wf => (
                                                    <option key={wf.id} value={wf.path}>{wf.name} ({wf.path})</option>
                                                ))}
                                            </select>
                                        </div>
                                    </div>
                                )}
                            </>
                        )}

                        {/* Default Branch */}
                        <div className="form-group">
                            <label className="label">Default Branch</label>
                            <div className="input-group">
                                <div className="input-icon">
                                    <GitMerge size={18} />
                                </div>
                                <input
                                    type="text"
                                    value={ghDefaultRef}
                                    onChange={e => setGhDefaultRef(e.target.value)}
                                    placeholder="main"
                                    className="input has-icon"
                                />
                            </div>
                        </div>

                        {/* Webhook Secret */}
                        <div className="form-group">
                            <label className="label">Webhook Secret <span style={{ color: 'var(--text-secondary)', fontWeight: 400 }}>(Optional)</span></label>
                            <div className="input-group">
                                <div className="input-icon">
                                    <Lock size={18} />
                                </div>
                                <input
                                    type="password"
                                    value={ghWebhookSecret}
                                    onChange={e => setGhWebhookSecret(e.target.value)}
                                    placeholder="Webhook secret"
                                    className="input has-icon"
                                />
                            </div>
                        </div>

                        {/* Save / Delete */}
                        <div style={{ paddingTop: '1.5rem', borderTop: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between' }}>
                            {ghConfigured && (
                                <button
                                    type="button"
                                    className="btn"
                                    onClick={handleGhDelete}
                                    style={{ color: 'var(--danger)', background: 'transparent', border: '1px solid var(--danger)' }}
                                >
                                    Remove
                                </button>
                            )}
                            <div style={{ marginLeft: 'auto' }}>
                                <button
                                    type="button"
                                    className="btn btn-primary"
                                    onClick={handleGhSave}
                                    disabled={ghSaving || !ghOwner}
                                    style={{
                                        minWidth: '140px',
                                        justifyContent: 'center',
                                        opacity: ghSaving ? 0.7 : 1,
                                        display: 'flex',
                                        alignItems: 'center',
                                        gap: '0.5rem',
                                    }}
                                >
                                    {ghSaving ? 'Saving...' : <><Save size={18} /> Save</>}
                                </button>
                            </div>
                        </div>
                    </div>
                ) : (
                    <div className="card" style={{
                        padding: '2rem',
                        textAlign: 'center',
                        color: 'var(--text-secondary)',
                        boxShadow: 'var(--shadow-card)'
                    }}>
                        <GitMerge size={32} style={{ marginBottom: '0.75rem', opacity: 0.5 }} />
                        <div style={{ fontWeight: 500, marginBottom: '0.25rem' }}>No project selected</div>
                        <div style={{ fontSize: '0.875rem' }}>Select a project to configure GitHub integration</div>
                    </div>
                )}
            </div>

            {/* Test Credentials Section */}
            <div style={{ marginTop: '2rem' }}>
                <h2 style={{ fontSize: '1.5rem', marginBottom: '1rem', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                    <Lock size={24} />
                    Test Credentials
                </h2>

                {currentProject ? (
                    <div className="card" style={{ boxShadow: 'var(--shadow-card)' }}>
                        <CredentialsManager
                            projectId={currentProject.id}
                            projectName={currentProject.name}
                        />
                    </div>
                ) : (
                    <div className="card" style={{
                        padding: '2rem',
                        textAlign: 'center',
                        color: 'var(--text-secondary)',
                        boxShadow: 'var(--shadow-card)'
                    }}>
                        <Lock size={32} style={{ marginBottom: '0.75rem', opacity: 0.5 }} />
                        <div style={{ fontWeight: 500, marginBottom: '0.25rem' }}>No project selected</div>
                        <div style={{ fontSize: '0.875rem' }}>Select a project to manage test credentials</div>
                    </div>
                )}
            </div>

            {user?.is_superuser && (
                <div style={{ marginTop: '2rem' }}>
                    <h2 style={{ fontSize: '1.5rem', marginBottom: '1rem', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                        <Shield size={24} />
                        Platform Administration
                    </h2>
                    <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem', boxShadow: 'var(--shadow-card)' }}>
                        <div style={{
                            padding: '1rem',
                            borderRadius: 'var(--radius)',
                            background: 'rgba(100, 116, 139, 0.1)',
                            border: '1px solid rgba(100, 116, 139, 0.2)'
                        }}>
                            <div style={{ fontWeight: 600, marginBottom: '0.5rem' }}>User Registration</div>
                            <p style={{ fontSize: '0.875rem', color: 'var(--text-secondary)', marginBottom: '1rem' }}>
                                Control whether new users can register on the platform. When disabled, only existing
                                users or users created by admins can access the system.
                            </p>
                            <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', fontStyle: 'italic' }}>
                                Note: Registration is controlled via ALLOW_REGISTRATION environment variable.
                                Current setting must be changed in the server configuration.
                            </p>
                        </div>
                        <div style={{
                            padding: '1rem',
                            borderRadius: 'var(--radius)',
                            background: 'rgba(100, 116, 139, 0.1)',
                            border: '1px solid rgba(100, 116, 139, 0.2)'
                        }}>
                            <div style={{ fontWeight: 600, marginBottom: '0.5rem' }}>Authentication Mode</div>
                            <p style={{ fontSize: '0.875rem', color: 'var(--text-secondary)' }}>
                                Authentication is currently optional (backward compatibility mode). Users can access
                                the platform without logging in, but will not have project-specific permissions.
                            </p>
                        </div>
                    </div>
                </div>
            )}

            <style jsx>{`
                @keyframes spin {
                    from { transform: rotate(0deg); }
                    to { transform: rotate(360deg); }
                }
            `}</style>
        </PageLayout>
    );
}
