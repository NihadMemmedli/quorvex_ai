'use client';

import { useState } from 'react';
import { useProjectMembers, ProjectMember, ProjectRole } from '@/hooks/useProjectRole';
import { useAuth } from '@/contexts/AuthContext';
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogHeader,
    DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from '@/components/ui/select';
import { Alert, AlertDescription } from '@/components/ui/alert';
import {
    Users,
    UserPlus,
    Trash2,
    Crown,
    Edit,
    Eye,
    Loader2,
    AlertCircle,
} from 'lucide-react';

interface MembersModalProps {
    projectId: string;
    projectName: string;
    isOpen: boolean;
    onClose: () => void;
    canManageMembers: boolean;
}

const roleIcons: Record<string, React.ReactNode> = {
    admin: <Crown className="h-4 w-4 text-amber-500" />,
    editor: <Edit className="h-4 w-4 text-blue-500" />,
    viewer: <Eye className="h-4 w-4 text-gray-500" />,
};

const roleLabels: Record<string, string> = {
    admin: 'Admin',
    editor: 'Editor',
    viewer: 'Viewer',
};

export function MembersModal({
    projectId,
    projectName,
    isOpen,
    onClose,
    canManageMembers,
}: MembersModalProps) {
    const { user: currentUser } = useAuth();
    const {
        members,
        isLoading,
        error: fetchError,
        addMember,
        updateMemberRole,
        removeMember,
    } = useProjectMembers(projectId);

    const [newEmail, setNewEmail] = useState('');
    const [newRole, setNewRole] = useState<ProjectRole>('viewer');
    const [isAdding, setIsAdding] = useState(false);
    const [actionError, setActionError] = useState<string | null>(null);
    const [updatingUserId, setUpdatingUserId] = useState<string | null>(null);
    const [removingUserId, setRemovingUserId] = useState<string | null>(null);

    const handleAddMember = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!newEmail.trim()) return;

        setIsAdding(true);
        setActionError(null);

        try {
            await addMember(newEmail.trim(), newRole);
            setNewEmail('');
            setNewRole('viewer');
        } catch (err) {
            setActionError(err instanceof Error ? err.message : 'Failed to add member');
        } finally {
            setIsAdding(false);
        }
    };

    const handleUpdateRole = async (userId: string, role: ProjectRole) => {
        setUpdatingUserId(userId);
        setActionError(null);

        try {
            await updateMemberRole(userId, role);
        } catch (err) {
            setActionError(err instanceof Error ? err.message : 'Failed to update role');
        } finally {
            setUpdatingUserId(null);
        }
    };

    const handleRemoveMember = async (userId: string) => {
        if (!confirm('Are you sure you want to remove this member?')) return;

        setRemovingUserId(userId);
        setActionError(null);

        try {
            await removeMember(userId);
        } catch (err) {
            setActionError(err instanceof Error ? err.message : 'Failed to remove member');
        } finally {
            setRemovingUserId(null);
        }
    };

    return (
        <Dialog open={isOpen} onOpenChange={(open) => !open && onClose()}>
            <DialogContent className="max-w-2xl">
                <DialogHeader>
                    <DialogTitle className="flex items-center gap-2">
                        <Users className="h-5 w-5" />
                        Team Members - {projectName}
                    </DialogTitle>
                    <DialogDescription>
                        {canManageMembers
                            ? 'Manage who has access to this project and their permissions.'
                            : 'View team members who have access to this project.'}
                    </DialogDescription>
                </DialogHeader>

                {(fetchError || actionError) && (
                    <Alert variant="destructive">
                        <AlertCircle className="h-4 w-4" />
                        <AlertDescription>{fetchError || actionError}</AlertDescription>
                    </Alert>
                )}

                {/* Add member form */}
                {canManageMembers && (
                    <form onSubmit={handleAddMember} className="flex gap-2">
                        <div className="flex-1">
                            <Label htmlFor="email" className="sr-only">
                                Email address
                            </Label>
                            <Input
                                id="email"
                                type="email"
                                placeholder="Enter email address"
                                value={newEmail}
                                onChange={(e) => setNewEmail(e.target.value)}
                                disabled={isAdding}
                            />
                        </div>
                        <Select
                            value={newRole || 'viewer'}
                            onValueChange={(value) => setNewRole(value as ProjectRole)}
                            disabled={isAdding}
                        >
                            <SelectTrigger className="w-32">
                                <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                                <SelectItem value="admin">Admin</SelectItem>
                                <SelectItem value="editor">Editor</SelectItem>
                                <SelectItem value="viewer">Viewer</SelectItem>
                            </SelectContent>
                        </Select>
                        <Button type="submit" disabled={isAdding || !newEmail.trim()}>
                            {isAdding ? (
                                <Loader2 className="h-4 w-4 animate-spin" />
                            ) : (
                                <UserPlus className="h-4 w-4" />
                            )}
                            <span className="ml-2">Add</span>
                        </Button>
                    </form>
                )}

                {/* Members list */}
                <div className="space-y-2 max-h-[400px] overflow-y-auto">
                    {isLoading ? (
                        <div className="flex items-center justify-center py-8">
                            <Loader2 className="h-6 w-6 animate-spin text-gray-400" />
                        </div>
                    ) : members.length === 0 ? (
                        <div className="text-center py-8 text-gray-500">
                            No members yet. Add team members to collaborate on this project.
                        </div>
                    ) : (
                        members.map((member) => (
                            <MemberRow
                                key={member.user_id}
                                member={member}
                                isCurrentUser={member.user_id === currentUser?.id}
                                canManage={canManageMembers}
                                isUpdating={updatingUserId === member.user_id}
                                isRemoving={removingUserId === member.user_id}
                                onUpdateRole={(role) => handleUpdateRole(member.user_id, role)}
                                onRemove={() => handleRemoveMember(member.user_id)}
                            />
                        ))
                    )}
                </div>

                {/* Role descriptions */}
                <div className="mt-4 pt-4 border-t text-xs text-gray-500">
                    <p className="font-medium mb-2">Role Permissions:</p>
                    <ul className="space-y-1">
                        <li className="flex items-center gap-2">
                            {roleIcons.admin}
                            <strong>Admin:</strong> Full access, manage members, delete project
                        </li>
                        <li className="flex items-center gap-2">
                            {roleIcons.editor}
                            <strong>Editor:</strong> Create and edit specs, run tests
                        </li>
                        <li className="flex items-center gap-2">
                            {roleIcons.viewer}
                            <strong>Viewer:</strong> View specs and results only
                        </li>
                    </ul>
                </div>
            </DialogContent>
        </Dialog>
    );
}

interface MemberRowProps {
    member: ProjectMember;
    isCurrentUser: boolean;
    canManage: boolean;
    isUpdating: boolean;
    isRemoving: boolean;
    onUpdateRole: (role: ProjectRole) => void;
    onRemove: () => void;
}

function MemberRow({
    member,
    isCurrentUser,
    canManage,
    isUpdating,
    isRemoving,
    onUpdateRole,
    onRemove,
}: MemberRowProps) {
    return (
        <div className="flex items-center justify-between p-3 rounded-lg border bg-card hover:bg-accent/50 transition-colors">
            <div className="flex items-center gap-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-full bg-primary/10 text-primary text-sm font-medium">
                    {member.full_name
                        ? member.full_name.split(' ').map((n) => n[0]).join('').toUpperCase().slice(0, 2)
                        : member.email.substring(0, 2).toUpperCase()}
                </div>
                <div>
                    <div className="flex items-center gap-2">
                        <span className="font-medium">
                            {member.full_name || member.email.split('@')[0]}
                        </span>
                        {isCurrentUser && (
                            <span className="text-xs bg-primary/10 text-primary px-2 py-0.5 rounded">
                                You
                            </span>
                        )}
                    </div>
                    <div className="text-sm text-muted-foreground">{member.email}</div>
                </div>
            </div>

            <div className="flex items-center gap-2">
                {canManage && !isCurrentUser ? (
                    <>
                        <Select
                            value={member.role || 'viewer'}
                            onValueChange={(value) => onUpdateRole(value as ProjectRole)}
                            disabled={isUpdating || isRemoving}
                        >
                            <SelectTrigger className="w-28">
                                {isUpdating ? (
                                    <Loader2 className="h-4 w-4 animate-spin" />
                                ) : (
                                    <SelectValue />
                                )}
                            </SelectTrigger>
                            <SelectContent>
                                <SelectItem value="admin">
                                    <div className="flex items-center gap-2">
                                        {roleIcons.admin}
                                        Admin
                                    </div>
                                </SelectItem>
                                <SelectItem value="editor">
                                    <div className="flex items-center gap-2">
                                        {roleIcons.editor}
                                        Editor
                                    </div>
                                </SelectItem>
                                <SelectItem value="viewer">
                                    <div className="flex items-center gap-2">
                                        {roleIcons.viewer}
                                        Viewer
                                    </div>
                                </SelectItem>
                            </SelectContent>
                        </Select>
                        <Button
                            variant="ghost"
                            size="icon"
                            onClick={onRemove}
                            disabled={isRemoving || isUpdating}
                            className="text-red-500 hover:text-red-600 hover:bg-red-50"
                        >
                            {isRemoving ? (
                                <Loader2 className="h-4 w-4 animate-spin" />
                            ) : (
                                <Trash2 className="h-4 w-4" />
                            )}
                        </Button>
                    </>
                ) : (
                    <div className="flex items-center gap-2 px-3 py-1.5 bg-muted rounded text-sm">
                        {roleIcons[member.role || 'viewer']}
                        <span>{roleLabels[member.role || 'viewer']}</span>
                    </div>
                )}
            </div>
        </div>
    );
}
