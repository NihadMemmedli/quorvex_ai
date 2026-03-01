'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth, fetchWithAuth } from '@/contexts/AuthContext';
import {
    Users, Shield, ShieldOff, UserCheck, UserX,
    Trash2, AlertCircle, CheckCircle, Search, RefreshCw, Eye,
    Plus, X, ChevronDown, UserPlus
} from 'lucide-react';
import { API_BASE } from '@/lib/api';
import { PageLayout } from '@/components/ui/page-layout';
import { PageHeader } from '@/components/ui/page-header';
import { ListPageSkeleton } from '@/components/ui/page-skeleton';

interface User {
    id: string;
    email: string;
    full_name: string | null;
    is_active: boolean;
    is_superuser: boolean;
    email_verified: boolean;
    created_at: string;
    last_login: string | null;
}

interface UserListResponse {
    users: User[];
    total: number;
}

interface Project {
    id: string;
    name: string;
    description: string | null;
}

interface UserProjectMembership {
    project_id: string;
    project_name: string;
    role: string;
    granted_at: string | null;
}

interface UserProjectsResponse {
    user_id: string;
    user_email: string;
    projects: UserProjectMembership[];
}

export default function AdminUsersPage() {
    const router = useRouter();
    const { user: currentUser, isLoading: authLoading } = useAuth();
    const [users, setUsers] = useState<User[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [message, setMessage] = useState<{ type: 'success' | 'error', text: string } | null>(null);
    const [searchTerm, setSearchTerm] = useState('');
    const [selectedUser, setSelectedUser] = useState<UserProjectsResponse | null>(null);
    const [showDeleteConfirm, setShowDeleteConfirm] = useState<string | null>(null);
    const [actionLoading, setActionLoading] = useState<string | null>(null);

    // Project membership management state
    const [allProjects, setAllProjects] = useState<Project[]>([]);
    const [showAddProject, setShowAddProject] = useState(false);
    const [addProjectForm, setAddProjectForm] = useState({ projectId: '', role: 'viewer' });
    const [membershipLoading, setMembershipLoading] = useState(false);
    const [showRemoveConfirm, setShowRemoveConfirm] = useState<string | null>(null);

    // Create user state
    const [showCreateUser, setShowCreateUser] = useState(false);
    const [createUserForm, setCreateUserForm] = useState({
        email: '',
        password: '',
        full_name: '',
        is_superuser: false
    });
    const [createUserLoading, setCreateUserLoading] = useState(false);

    // Check superuser access
    useEffect(() => {
        if (!authLoading && (!currentUser || !currentUser.is_superuser)) {
            router.push('/');
        }
    }, [authLoading, currentUser, router]);

    const fetchUsers = async () => {
        setLoading(true);
        setError(null);
        try {
            const res = await fetchWithAuth(`${API_BASE}/users`);
            if (!res.ok) {
                if (res.status === 403) {
                    router.push('/');
                    return;
                }
                throw new Error('Failed to fetch users');
            }
            const data: UserListResponse = await res.json();
            setUsers(data.users);
        } catch (err: any) {
            setError(err.message);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        if (currentUser?.is_superuser) {
            fetchUsers();
        }
    }, [currentUser]);

    const fetchUserProjects = async (userId: string) => {
        try {
            const res = await fetchWithAuth(`${API_BASE}/users/${userId}/projects`);
            if (res.ok) {
                const data: UserProjectsResponse = await res.json();
                setSelectedUser(data);
            }
        } catch (err) {
            console.error('Failed to fetch user projects:', err);
        }
    };

    const fetchAllProjects = async () => {
        try {
            const res = await fetchWithAuth(`${API_BASE}/projects`);
            if (res.ok) {
                const data = await res.json();
                // API returns { projects: [...], total: int }
                setAllProjects(data.projects || []);
            }
        } catch (err) {
            console.error('Failed to fetch projects:', err);
        }
    };

    // Fetch projects when component mounts
    useEffect(() => {
        if (currentUser?.is_superuser) {
            fetchAllProjects();
        }
    }, [currentUser]);

    const createUser = async () => {
        setCreateUserLoading(true);
        try {
            const res = await fetchWithAuth(`${API_BASE}/users`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    email: createUserForm.email,
                    password: createUserForm.password,
                    full_name: createUserForm.full_name || null,
                    is_superuser: createUserForm.is_superuser
                })
            });
            if (!res.ok) {
                const data = await res.json();
                throw new Error(data.detail || 'Failed to create user');
            }
            setMessage({ type: 'success', text: 'User created successfully' });
            setTimeout(() => setMessage(null), 3000);
            setShowCreateUser(false);
            setCreateUserForm({ email: '', password: '', full_name: '', is_superuser: false });
            fetchUsers();
        } catch (err: any) {
            setMessage({ type: 'error', text: err.message });
        } finally {
            setCreateUserLoading(false);
        }
    };

    const addUserToProject = async (userId: string, projectId: string, role: string) => {
        setMembershipLoading(true);
        try {
            const res = await fetchWithAuth(`${API_BASE}/users/${userId}/projects/${projectId}?role=${role}`, {
                method: 'POST'
            });
            if (!res.ok) {
                const data = await res.json();
                throw new Error(data.detail || 'Failed to add user to project');
            }
            setMessage({ type: 'success', text: 'User added to project successfully' });
            setTimeout(() => setMessage(null), 3000);
            // Refresh user projects
            await fetchUserProjects(userId);
            setShowAddProject(false);
            setAddProjectForm({ projectId: '', role: 'viewer' });
        } catch (err: any) {
            setMessage({ type: 'error', text: err.message });
        } finally {
            setMembershipLoading(false);
        }
    };

    const updateUserRole = async (userId: string, projectId: string, role: string) => {
        setMembershipLoading(true);
        try {
            const res = await fetchWithAuth(`${API_BASE}/projects/${projectId}/members/${userId}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ role })
            });
            if (!res.ok) {
                const data = await res.json();
                throw new Error(data.detail || 'Failed to update role');
            }
            setMessage({ type: 'success', text: 'Role updated successfully' });
            setTimeout(() => setMessage(null), 3000);
            // Refresh user projects
            await fetchUserProjects(userId);
        } catch (err: any) {
            setMessage({ type: 'error', text: err.message });
        } finally {
            setMembershipLoading(false);
        }
    };

    const removeUserFromProject = async (userId: string, projectId: string) => {
        setMembershipLoading(true);
        try {
            const res = await fetchWithAuth(`${API_BASE}/users/${userId}/projects/${projectId}`, {
                method: 'DELETE'
            });
            if (!res.ok) {
                const data = await res.json();
                throw new Error(data.detail || 'Failed to remove user from project');
            }
            setMessage({ type: 'success', text: 'User removed from project successfully' });
            setTimeout(() => setMessage(null), 3000);
            setShowRemoveConfirm(null);
            // Refresh user projects
            await fetchUserProjects(userId);
        } catch (err: any) {
            setMessage({ type: 'error', text: err.message });
        } finally {
            setMembershipLoading(false);
        }
    };

    // Get available projects (projects user is NOT a member of)
    const getAvailableProjects = () => {
        if (!selectedUser) return allProjects;
        const memberProjectIds = new Set(selectedUser.projects.map(p => p.project_id));
        return allProjects.filter(p => !memberProjectIds.has(p.id));
    };

    const updateUser = async (userId: string, updates: { is_active?: boolean; is_superuser?: boolean }) => {
        setActionLoading(userId);
        try {
            const res = await fetchWithAuth(`${API_BASE}/users/${userId}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(updates)
            });
            if (!res.ok) {
                const data = await res.json();
                throw new Error(data.detail || 'Failed to update user');
            }
            setMessage({ type: 'success', text: 'User updated successfully' });
            setTimeout(() => setMessage(null), 3000);
            fetchUsers();
        } catch (err: any) {
            setMessage({ type: 'error', text: err.message });
        } finally {
            setActionLoading(null);
        }
    };

    const deleteUser = async (userId: string) => {
        setActionLoading(userId);
        try {
            const res = await fetchWithAuth(`${API_BASE}/users/${userId}`, {
                method: 'DELETE'
            });
            if (!res.ok) {
                const data = await res.json();
                throw new Error(data.detail || 'Failed to delete user');
            }
            setMessage({ type: 'success', text: 'User deleted successfully' });
            setTimeout(() => setMessage(null), 3000);
            setShowDeleteConfirm(null);
            fetchUsers();
        } catch (err: any) {
            setMessage({ type: 'error', text: err.message });
        } finally {
            setActionLoading(null);
        }
    };

    const filteredUsers = users.filter(u =>
        u.email.toLowerCase().includes(searchTerm.toLowerCase()) ||
        (u.full_name?.toLowerCase().includes(searchTerm.toLowerCase()))
    );

    const formatDate = (dateStr: string | null) => {
        if (!dateStr) return 'Never';
        return new Date(dateStr).toLocaleString();
    };

    if (authLoading || !currentUser?.is_superuser) {
        return (
            <PageLayout tier="standard">
                <ListPageSkeleton rows={5} />
            </PageLayout>
        );
    }

    return (
        <PageLayout tier="standard">
            <PageHeader
                title="User Management"
                subtitle="Manage platform users, roles, and permissions"
                icon={<Users size={20} />}
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
                    gap: '0.75rem'
                }}>
                    {message.type === 'success' ? <CheckCircle size={20} /> : <AlertCircle size={20} />}
                    {message.text}
                </div>
            )}

            {/* Search and Refresh */}
            <div style={{ display: 'flex', gap: '1rem', marginBottom: '1.5rem' }}>
                <div style={{ flex: 1, position: 'relative' }}>
                    <Search size={18} style={{
                        position: 'absolute',
                        left: '12px',
                        top: '50%',
                        transform: 'translateY(-50%)',
                        color: 'var(--text-secondary)'
                    }} />
                    <input
                        type="text"
                        placeholder="Search users by email or name..."
                        value={searchTerm}
                        onChange={(e) => setSearchTerm(e.target.value)}
                        className="input"
                        style={{ paddingLeft: '40px', width: '100%' }}
                    />
                </div>
                <button
                    onClick={fetchUsers}
                    className="btn btn-secondary"
                    disabled={loading}
                    style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}
                >
                    <RefreshCw size={18} className={loading ? 'spin' : ''} />
                    Refresh
                </button>
                <button
                    onClick={() => setShowCreateUser(true)}
                    className="btn btn-primary"
                    style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}
                >
                    <UserPlus size={18} />
                    Add User
                </button>
            </div>

            {error && (
                <div style={{
                    padding: '1rem',
                    marginBottom: '1.5rem',
                    borderRadius: 'var(--radius)',
                    background: 'var(--danger-muted)',
                    border: '1px solid rgba(248, 113, 113, 0.2)',
                    color: 'var(--danger)'
                }}>
                    {error}
                </div>
            )}

            {/* Users Table */}
            <div className="card animate-in stagger-2" style={{ padding: 0, overflow: 'hidden' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                    <thead>
                        <tr style={{ background: 'var(--surface-hover)', borderBottom: '1px solid var(--border)' }}>
                            <th style={{ padding: '1rem', textAlign: 'left', fontWeight: 600 }}>User</th>
                            <th style={{ padding: '1rem', textAlign: 'center', fontWeight: 600 }}>Status</th>
                            <th style={{ padding: '1rem', textAlign: 'center', fontWeight: 600 }}>Role</th>
                            <th style={{ padding: '1rem', textAlign: 'left', fontWeight: 600 }}>Last Login</th>
                            <th style={{ padding: '1rem', textAlign: 'center', fontWeight: 600 }}>Actions</th>
                        </tr>
                    </thead>
                    <tbody>
                        {loading ? (
                            <tr>
                                <td colSpan={5} style={{ padding: '3rem', textAlign: 'center' }}>
                                    <div className="loading-spinner" style={{ margin: '0 auto' }}></div>
                                </td>
                            </tr>
                        ) : filteredUsers.length === 0 ? (
                            <tr>
                                <td colSpan={5} style={{ padding: '3rem', textAlign: 'center', color: 'var(--text-secondary)' }}>
                                    No users found
                                </td>
                            </tr>
                        ) : (
                            filteredUsers.map(user => (
                                <tr
                                    key={user.id}
                                    style={{
                                        borderBottom: '1px solid var(--border)',
                                        opacity: user.is_active ? 1 : 0.6
                                    }}
                                >
                                    <td style={{ padding: '1rem' }}>
                                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                                            <div style={{
                                                width: '40px',
                                                height: '40px',
                                                borderRadius: '8px',
                                                background: user.is_superuser ? 'linear-gradient(135deg, var(--warning), #d97706)' : 'linear-gradient(135deg, var(--primary), var(--primary-hover))',
                                                display: 'flex',
                                                alignItems: 'center',
                                                justifyContent: 'center',
                                                color: 'white',
                                                fontWeight: 600,
                                                fontSize: '0.875rem'
                                            }}>
                                                {(user.full_name || user.email).substring(0, 2).toUpperCase()}
                                            </div>
                                            <div>
                                                <div style={{ fontWeight: 500 }}>
                                                    {user.full_name || user.email.split('@')[0]}
                                                </div>
                                                <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
                                                    {user.email}
                                                </div>
                                            </div>
                                        </div>
                                    </td>
                                    <td style={{ padding: '1rem', textAlign: 'center' }}>
                                        <span style={{
                                            padding: '4px 12px',
                                            borderRadius: '12px',
                                            fontSize: '0.8rem',
                                            fontWeight: 500,
                                            background: user.is_active ? 'var(--success-muted)' : 'var(--danger-muted)',
                                            color: user.is_active ? 'var(--success)' : 'var(--danger)'
                                        }}>
                                            {user.is_active ? 'Active' : 'Inactive'}
                                        </span>
                                    </td>
                                    <td style={{ padding: '1rem', textAlign: 'center' }}>
                                        {user.is_superuser ? (
                                            <span style={{
                                                display: 'inline-flex',
                                                alignItems: 'center',
                                                gap: '4px',
                                                padding: '4px 12px',
                                                borderRadius: '12px',
                                                fontSize: '0.8rem',
                                                fontWeight: 500,
                                                background: 'var(--warning-muted)',
                                                color: 'var(--warning)'
                                            }}>
                                                <Shield size={14} />
                                                Superuser
                                            </span>
                                        ) : (
                                            <span style={{
                                                padding: '4px 12px',
                                                borderRadius: '12px',
                                                fontSize: '0.8rem',
                                                fontWeight: 500,
                                                background: 'rgba(100, 116, 139, 0.1)',
                                                color: 'var(--text-secondary)'
                                            }}>
                                                User
                                            </span>
                                        )}
                                    </td>
                                    <td style={{ padding: '1rem', fontSize: '0.9rem', color: 'var(--text-secondary)' }}>
                                        {formatDate(user.last_login)}
                                    </td>
                                    <td style={{ padding: '1rem' }}>
                                        <div style={{ display: 'flex', justifyContent: 'center', gap: '0.5rem' }}>
                                            {/* View Projects */}
                                            <button
                                                onClick={() => fetchUserProjects(user.id)}
                                                className="btn btn-secondary"
                                                style={{ padding: '6px 10px', fontSize: '0.85rem' }}
                                                title="View projects"
                                            >
                                                <Eye size={16} />
                                            </button>

                                            {/* Toggle Active */}
                                            <button
                                                onClick={() => updateUser(user.id, { is_active: !user.is_active })}
                                                className="btn btn-secondary"
                                                disabled={actionLoading === user.id || user.id === currentUser?.id}
                                                style={{ padding: '6px 10px', fontSize: '0.85rem' }}
                                                title={user.is_active ? 'Deactivate' : 'Activate'}
                                            >
                                                {user.is_active ? <UserX size={16} /> : <UserCheck size={16} />}
                                            </button>

                                            {/* Toggle Superuser */}
                                            <button
                                                onClick={() => updateUser(user.id, { is_superuser: !user.is_superuser })}
                                                className="btn btn-secondary"
                                                disabled={actionLoading === user.id || user.id === currentUser?.id}
                                                style={{
                                                    padding: '6px 10px',
                                                    fontSize: '0.85rem',
                                                    color: user.is_superuser ? 'var(--warning)' : undefined
                                                }}
                                                title={user.is_superuser ? 'Remove superuser' : 'Make superuser'}
                                            >
                                                {user.is_superuser ? <ShieldOff size={16} /> : <Shield size={16} />}
                                            </button>

                                            {/* Delete */}
                                            <button
                                                onClick={() => setShowDeleteConfirm(user.id)}
                                                className="btn btn-danger"
                                                disabled={actionLoading === user.id || user.id === currentUser?.id}
                                                style={{ padding: '6px 10px', fontSize: '0.85rem' }}
                                                title="Delete user"
                                            >
                                                <Trash2 size={16} />
                                            </button>
                                        </div>
                                    </td>
                                </tr>
                            ))
                        )}
                    </tbody>
                </table>
            </div>

            {/* User Projects Modal - Interactive Management */}
            {selectedUser && (
                <div style={{
                    position: 'fixed',
                    top: 0,
                    left: 0,
                    right: 0,
                    bottom: 0,
                    background: 'rgba(0,0,0,0.5)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    zIndex: 1000
                }}
                    onClick={() => {
                        setSelectedUser(null);
                        setShowAddProject(false);
                        setShowRemoveConfirm(null);
                    }}
                >
                    <div
                        className="card"
                        style={{ width: '550px', maxHeight: '80vh', overflow: 'auto' }}
                        onClick={(e) => e.stopPropagation()}
                    >
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '1rem' }}>
                            <div>
                                <h2 style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.25rem' }}>
                                    <Users size={20} />
                                    Project Memberships
                                </h2>
                                <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem' }}>
                                    {selectedUser.user_email}
                                </p>
                            </div>
                            <button
                                onClick={() => {
                                    setSelectedUser(null);
                                    setShowAddProject(false);
                                    setShowRemoveConfirm(null);
                                }}
                                style={{
                                    background: 'none',
                                    border: 'none',
                                    cursor: 'pointer',
                                    padding: '4px',
                                    color: 'var(--text-secondary)'
                                }}
                            >
                                <X size={20} />
                            </button>
                        </div>

                        {/* Add to Project Button / Form */}
                        {!showAddProject ? (
                            <button
                                onClick={() => setShowAddProject(true)}
                                className="btn btn-primary"
                                style={{
                                    width: '100%',
                                    marginBottom: '1rem',
                                    display: 'flex',
                                    alignItems: 'center',
                                    justifyContent: 'center',
                                    gap: '0.5rem'
                                }}
                                disabled={getAvailableProjects().length === 0}
                            >
                                <Plus size={18} />
                                Add to Project
                            </button>
                        ) : (
                            <div style={{
                                padding: '1rem',
                                background: 'var(--surface-hover)',
                                borderRadius: 'var(--radius)',
                                marginBottom: '1rem',
                                border: '1px solid var(--border)'
                            }}>
                                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
                                    <h3 style={{ fontSize: '0.95rem', fontWeight: 600 }}>Add to Project</h3>
                                    <button
                                        onClick={() => {
                                            setShowAddProject(false);
                                            setAddProjectForm({ projectId: '', role: 'viewer' });
                                        }}
                                        style={{
                                            background: 'none',
                                            border: 'none',
                                            cursor: 'pointer',
                                            padding: '2px',
                                            color: 'var(--text-secondary)'
                                        }}
                                    >
                                        <X size={16} />
                                    </button>
                                </div>
                                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                                    <div>
                                        <label style={{ display: 'block', fontSize: '0.85rem', fontWeight: 500, marginBottom: '0.25rem' }}>
                                            Project
                                        </label>
                                        <select
                                            value={addProjectForm.projectId}
                                            onChange={(e) => setAddProjectForm(prev => ({ ...prev, projectId: e.target.value }))}
                                            className="input"
                                            style={{ width: '100%' }}
                                        >
                                            <option value="">Select a project...</option>
                                            {getAvailableProjects().map(p => (
                                                <option key={p.id} value={p.id}>{p.name}</option>
                                            ))}
                                        </select>
                                    </div>
                                    <div>
                                        <label style={{ display: 'block', fontSize: '0.85rem', fontWeight: 500, marginBottom: '0.25rem' }}>
                                            Role
                                        </label>
                                        <select
                                            value={addProjectForm.role}
                                            onChange={(e) => setAddProjectForm(prev => ({ ...prev, role: e.target.value }))}
                                            className="input"
                                            style={{ width: '100%' }}
                                        >
                                            <option value="viewer">Viewer</option>
                                            <option value="editor">Editor</option>
                                            <option value="admin">Admin</option>
                                        </select>
                                    </div>
                                    <div style={{ display: 'flex', gap: '0.5rem', justifyContent: 'flex-end', marginTop: '0.5rem' }}>
                                        <button
                                            onClick={() => {
                                                setShowAddProject(false);
                                                setAddProjectForm({ projectId: '', role: 'viewer' });
                                            }}
                                            className="btn btn-secondary"
                                            disabled={membershipLoading}
                                        >
                                            Cancel
                                        </button>
                                        <button
                                            onClick={() => addUserToProject(selectedUser.user_id, addProjectForm.projectId, addProjectForm.role)}
                                            className="btn btn-primary"
                                            disabled={!addProjectForm.projectId || membershipLoading}
                                        >
                                            {membershipLoading ? 'Adding...' : 'Add'}
                                        </button>
                                    </div>
                                </div>
                            </div>
                        )}

                        {getAvailableProjects().length === 0 && !showAddProject && (
                            <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: '1rem', textAlign: 'center' }}>
                                User is a member of all projects
                            </p>
                        )}

                        {/* Project Memberships List */}
                        {selectedUser.projects.length === 0 ? (
                            <p style={{ color: 'var(--text-secondary)', textAlign: 'center', padding: '2rem' }}>
                                No project memberships
                            </p>
                        ) : (
                            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                                {selectedUser.projects.map(p => (
                                    <div
                                        key={p.project_id}
                                        style={{
                                            padding: '1rem',
                                            background: 'var(--surface-hover)',
                                            borderRadius: 'var(--radius)',
                                            border: showRemoveConfirm === p.project_id ? '1px solid var(--danger)' : '1px solid transparent'
                                        }}
                                    >
                                        {showRemoveConfirm === p.project_id ? (
                                            /* Remove Confirmation */
                                            <div>
                                                <p style={{ fontWeight: 500, marginBottom: '0.75rem' }}>
                                                    Remove from "{p.project_name}"?
                                                </p>
                                                <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: '1rem' }}>
                                                    User will lose access to this project.
                                                </p>
                                                <div style={{ display: 'flex', gap: '0.5rem', justifyContent: 'flex-end' }}>
                                                    <button
                                                        onClick={() => setShowRemoveConfirm(null)}
                                                        className="btn btn-secondary"
                                                        style={{ padding: '6px 12px', fontSize: '0.85rem' }}
                                                        disabled={membershipLoading}
                                                    >
                                                        Cancel
                                                    </button>
                                                    <button
                                                        onClick={() => removeUserFromProject(selectedUser.user_id, p.project_id)}
                                                        className="btn btn-danger"
                                                        style={{ padding: '6px 12px', fontSize: '0.85rem' }}
                                                        disabled={membershipLoading}
                                                    >
                                                        {membershipLoading ? 'Removing...' : 'Remove'}
                                                    </button>
                                                </div>
                                            </div>
                                        ) : (
                                            /* Normal View */
                                            <div style={{
                                                display: 'flex',
                                                justifyContent: 'space-between',
                                                alignItems: 'center',
                                                flexWrap: 'wrap',
                                                gap: '0.75rem'
                                            }}>
                                                <div style={{ flex: '1 1 auto', minWidth: '150px' }}>
                                                    <div style={{ fontWeight: 500 }}>{p.project_name}</div>
                                                    <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                                                        {p.granted_at ? `Added ${new Date(p.granted_at).toLocaleDateString()}` : ''}
                                                    </div>
                                                </div>
                                                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                                                    {/* Role Dropdown */}
                                                    <div style={{ position: 'relative' }}>
                                                        <select
                                                            value={p.role}
                                                            onChange={(e) => updateUserRole(selectedUser.user_id, p.project_id, e.target.value)}
                                                            disabled={membershipLoading}
                                                            style={{
                                                                padding: '6px 28px 6px 10px',
                                                                borderRadius: '8px',
                                                                fontSize: '0.8rem',
                                                                fontWeight: 500,
                                                                border: '1px solid var(--border)',
                                                                background: p.role === 'admin' ? 'var(--warning-muted)' :
                                                                    p.role === 'editor' ? 'var(--primary-glow)' : 'rgba(100, 116, 139, 0.1)',
                                                                color: p.role === 'admin' ? 'var(--warning)' :
                                                                    p.role === 'editor' ? 'var(--primary)' : 'var(--text-secondary)',
                                                                cursor: 'pointer',
                                                                appearance: 'none',
                                                                WebkitAppearance: 'none'
                                                            }}
                                                        >
                                                            <option value="viewer">Viewer</option>
                                                            <option value="editor">Editor</option>
                                                            <option value="admin">Admin</option>
                                                        </select>
                                                        <ChevronDown
                                                            size={14}
                                                            style={{
                                                                position: 'absolute',
                                                                right: '8px',
                                                                top: '50%',
                                                                transform: 'translateY(-50%)',
                                                                pointerEvents: 'none',
                                                                color: p.role === 'admin' ? 'var(--warning)' :
                                                                    p.role === 'editor' ? 'var(--primary)' : 'var(--text-secondary)'
                                                            }}
                                                        />
                                                    </div>
                                                    {/* Remove Button */}
                                                    <button
                                                        onClick={() => setShowRemoveConfirm(p.project_id)}
                                                        className="btn btn-danger"
                                                        style={{ padding: '6px 10px', fontSize: '0.8rem' }}
                                                        disabled={membershipLoading}
                                                        title="Remove from project"
                                                    >
                                                        <Trash2 size={14} />
                                                    </button>
                                                </div>
                                            </div>
                                        )}
                                    </div>
                                ))}
                            </div>
                        )}

                        <div style={{ marginTop: '1.5rem', display: 'flex', justifyContent: 'flex-end' }}>
                            <button
                                onClick={() => {
                                    setSelectedUser(null);
                                    setShowAddProject(false);
                                    setShowRemoveConfirm(null);
                                }}
                                className="btn btn-secondary"
                            >
                                Close
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {/* Delete Confirmation Modal */}
            {showDeleteConfirm && (
                <div style={{
                    position: 'fixed',
                    top: 0,
                    left: 0,
                    right: 0,
                    bottom: 0,
                    background: 'rgba(0,0,0,0.5)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    zIndex: 1000
                }}
                    onClick={() => setShowDeleteConfirm(null)}
                >
                    <div
                        className="card"
                        style={{ width: '400px' }}
                        onClick={(e) => e.stopPropagation()}
                    >
                        <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', marginBottom: '1rem' }}>
                            <div style={{
                                width: '48px',
                                height: '48px',
                                borderRadius: '12px',
                                background: 'var(--danger-muted)',
                                display: 'flex',
                                alignItems: 'center',
                                justifyContent: 'center'
                            }}>
                                <Trash2 size={24} color="var(--danger)" />
                            </div>
                            <div>
                                <h2 style={{ fontSize: '1.25rem', fontWeight: 600 }}>Delete User</h2>
                                <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem' }}>
                                    This action cannot be undone
                                </p>
                            </div>
                        </div>

                        <p style={{ marginBottom: '1.5rem', color: 'var(--text-secondary)' }}>
                            Are you sure you want to delete this user? All their project memberships and sessions will be removed.
                        </p>

                        <div style={{ display: 'flex', gap: '0.75rem', justifyContent: 'flex-end' }}>
                            <button
                                onClick={() => setShowDeleteConfirm(null)}
                                className="btn btn-secondary"
                            >
                                Cancel
                            </button>
                            <button
                                onClick={() => deleteUser(showDeleteConfirm)}
                                className="btn btn-danger"
                                disabled={actionLoading === showDeleteConfirm}
                            >
                                {actionLoading === showDeleteConfirm ? 'Deleting...' : 'Delete User'}
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {/* Create User Modal */}
            {showCreateUser && (
                <div style={{
                    position: 'fixed',
                    top: 0,
                    left: 0,
                    right: 0,
                    bottom: 0,
                    background: 'rgba(0,0,0,0.5)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    zIndex: 1000
                }}
                    onClick={() => setShowCreateUser(false)}
                >
                    <div
                        className="card"
                        style={{ width: '450px' }}
                        onClick={(e) => e.stopPropagation()}
                    >
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1.5rem' }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                                <div style={{
                                    width: '40px',
                                    height: '40px',
                                    borderRadius: '10px',
                                    background: 'linear-gradient(135deg, var(--primary), #2563eb)',
                                    display: 'flex',
                                    alignItems: 'center',
                                    justifyContent: 'center'
                                }}>
                                    <UserPlus size={20} color="white" />
                                </div>
                                <h2 style={{ fontSize: '1.25rem', fontWeight: 600 }}>Add New User</h2>
                            </div>
                            <button
                                onClick={() => setShowCreateUser(false)}
                                style={{
                                    background: 'none',
                                    border: 'none',
                                    cursor: 'pointer',
                                    padding: '4px',
                                    color: 'var(--text-secondary)'
                                }}
                            >
                                <X size={20} />
                            </button>
                        </div>

                        <form onSubmit={(e) => { e.preventDefault(); createUser(); }}>
                            <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                                <div>
                                    <label style={{ display: 'block', fontSize: '0.875rem', fontWeight: 500, marginBottom: '0.375rem' }}>
                                        Email *
                                    </label>
                                    <input
                                        type="email"
                                        value={createUserForm.email}
                                        onChange={(e) => setCreateUserForm(prev => ({ ...prev, email: e.target.value }))}
                                        className="input"
                                        style={{ width: '100%' }}
                                        placeholder="user@example.com"
                                        required
                                    />
                                </div>

                                <div>
                                    <label style={{ display: 'block', fontSize: '0.875rem', fontWeight: 500, marginBottom: '0.375rem' }}>
                                        Full Name
                                    </label>
                                    <input
                                        type="text"
                                        value={createUserForm.full_name}
                                        onChange={(e) => setCreateUserForm(prev => ({ ...prev, full_name: e.target.value }))}
                                        className="input"
                                        style={{ width: '100%' }}
                                        placeholder="John Doe"
                                    />
                                </div>

                                <div>
                                    <label style={{ display: 'block', fontSize: '0.875rem', fontWeight: 500, marginBottom: '0.375rem' }}>
                                        Password *
                                    </label>
                                    <input
                                        type="password"
                                        value={createUserForm.password}
                                        onChange={(e) => setCreateUserForm(prev => ({ ...prev, password: e.target.value }))}
                                        className="input"
                                        style={{ width: '100%' }}
                                        placeholder="Min 8 chars, uppercase, number, special"
                                        required
                                    />
                                    <p style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', marginTop: '0.25rem' }}>
                                        Must be at least 8 characters with uppercase, number, and special character
                                    </p>
                                </div>

                                <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', padding: '0.75rem', background: 'var(--surface-hover)', borderRadius: 'var(--radius)' }}>
                                    <input
                                        type="checkbox"
                                        id="is_superuser"
                                        checked={createUserForm.is_superuser}
                                        onChange={(e) => setCreateUserForm(prev => ({ ...prev, is_superuser: e.target.checked }))}
                                        style={{ width: '18px', height: '18px' }}
                                    />
                                    <label htmlFor="is_superuser" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'pointer' }}>
                                        <Shield size={16} color="var(--warning)" />
                                        <span style={{ fontWeight: 500 }}>Grant superuser privileges</span>
                                    </label>
                                </div>
                            </div>

                            <div style={{ display: 'flex', gap: '0.75rem', justifyContent: 'flex-end', marginTop: '1.5rem' }}>
                                <button
                                    type="button"
                                    onClick={() => {
                                        setShowCreateUser(false);
                                        setCreateUserForm({ email: '', password: '', full_name: '', is_superuser: false });
                                    }}
                                    className="btn btn-secondary"
                                    disabled={createUserLoading}
                                >
                                    Cancel
                                </button>
                                <button
                                    type="submit"
                                    className="btn btn-primary"
                                    disabled={createUserLoading || !createUserForm.email || !createUserForm.password}
                                >
                                    {createUserLoading ? 'Creating...' : 'Create User'}
                                </button>
                            </div>
                        </form>
                    </div>
                </div>
            )}
        </PageLayout>
    );
}
