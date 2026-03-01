'use client';
import { useState, useEffect, useMemo, useCallback, useRef } from 'react';
import { FileText, Plus, Play, Folder, FolderOpen, ChevronRight, ChevronDown, Search, FolderClosed, Tag, X, Edit, Check, Split, TestTube, Trash2, CheckCircle, ToggleLeft, ToggleRight, LayoutTemplate, Zap, AlertCircle, GripVertical, ArrowDownToLine, Upload, Link2, Loader2, Pencil, FolderPlus } from 'lucide-react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import TagEditor from '@/components/TagEditor';
import { useProject } from '@/contexts/ProjectContext';
import { API_BASE } from '@/lib/api';
import { WorkflowBreadcrumb } from '@/components/workflow/WorkflowBreadcrumb';
import { PageLayout } from '@/components/ui/page-layout';
import { PageHeader } from '@/components/ui/page-header';
import { EmptyState } from '@/components/ui/empty-state';

interface Spec {
    name: string;
    path: string;
    content?: string;  // Optional - not needed for list view
    spec_type?: 'standard' | 'prd' | 'native_plan' | 'standard_multi' | 'template';
    test_count?: number;
    categories?: string[];
    is_automated?: boolean;
    code_path?: string;
    metadata?: {
        tags: string[];
        description?: string;
        author?: string;
        lastModified?: string;
    };
}

interface TreeNode {
    name: string;
    path: string;
    type: 'file' | 'folder';
    children?: Record<string, TreeNode>;
    spec?: Spec;
}

type TabType = 'specs' | 'templates';

function formatFolderName(name: string): string {
    return name
        .replace(/-/g, ' ')
        .replace(/\b\w/g, c => c.toUpperCase());
}

export default function SpecsPage() {
    const router = useRouter();
    const { currentProject, isLoading: projectLoading } = useProject();

    const [activeTab, setActiveTab] = useState<TabType>('specs');
    const [specs, setSpecs] = useState<Spec[]>([]);
    const [metadata, setMetadata] = useState<Record<string, any>>({});
    const [loading, setLoading] = useState(true);
    const [searchTerm, setSearchTerm] = useState('');
    const [templatesSearchTerm, setTemplatesSearchTerm] = useState('');
    const [selectedTags, setSelectedTags] = useState<string[]>([]);
    const [automatedOnly, setAutomatedOnly] = useState(false);
    const [expandedFolders, setExpandedFolders] = useState<Set<string>>(new Set());
    const [templatesExpandedFolders, setTemplatesExpandedFolders] = useState<Set<string>>(new Set());

    // Pagination state
    const [totalCount, setTotalCount] = useState(0);
    const [hasMore, setHasMore] = useState(false);
    const [isLoadingMore, setIsLoadingMore] = useState(false);
    const [specsSummary, setSpecsSummary] = useState<{ total_all: number; automated_count: number; all_tags: string[] } | null>(null);

    // Debounced search
    const [debouncedSearchTerm, setDebouncedSearchTerm] = useState('');
    const searchDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

    // Debounce search term (300ms)
    useEffect(() => {
        if (searchDebounceRef.current) {
            clearTimeout(searchDebounceRef.current);
        }
        searchDebounceRef.current = setTimeout(() => {
            setDebouncedSearchTerm(searchTerm);
        }, 300);
        return () => {
            if (searchDebounceRef.current) {
                clearTimeout(searchDebounceRef.current);
            }
        };
    }, [searchTerm]);

    const fetchSpecs = useCallback(async (offset: number, append: boolean) => {
        if (projectLoading) return;

        if (!append) {
            setLoading(true);
        } else {
            setIsLoadingMore(true);
        }

        try {
            const params = new URLSearchParams();
            if (currentProject?.id) params.set('project_id', currentProject.id);
            params.set('limit', '50');
            params.set('offset', String(offset));
            if (debouncedSearchTerm) params.set('search', debouncedSearchTerm);
            if (selectedTags.length > 0) params.set('tags', selectedTags.join(','));
            if (automatedOnly) params.set('automated_only', 'true');

            const queryString = params.toString();

            // Fetch paginated specs and metadata in parallel (metadata only on initial load)
            const fetches: Promise<any>[] = [
                fetch(`${API_BASE}/specs/list?${queryString}`).then(res => {
                    if (!res.ok) throw new Error(`Specs fetch failed: ${res.status}`);
                    return res.json();
                })
            ];
            if (!append) {
                const metadataParam = currentProject?.id ? `?project_id=${encodeURIComponent(currentProject.id)}` : '';
                fetches.push(
                    fetch(`${API_BASE}/spec-metadata${metadataParam}`).then(res => {
                        if (!res.ok) throw new Error(`Metadata fetch failed: ${res.status}`);
                        return res.json();
                    })
                );
            }

            const results = await Promise.all(fetches);
            const specsResponse = results[0];
            const metadataData = !append ? results[1] : metadata;

            // Handle both paginated response { items, total, ... } and legacy array response
            const isPaginated = specsResponse && !Array.isArray(specsResponse) && Array.isArray(specsResponse.items);
            const specsList: Spec[] = isPaginated ? specsResponse.items : (Array.isArray(specsResponse) ? specsResponse : []);

            // Merge metadata into specs items
            const specsWithMetadata = specsList.map((spec: Spec) => ({
                ...spec,
                metadata: metadataData[spec.name] || { tags: [] }
            }));

            if (append) {
                setSpecs(prev => [...prev, ...specsWithMetadata]);
            } else {
                setSpecs(specsWithMetadata);
                setMetadata(metadataData);
                setExpandedFolders(new Set());
            }

            if (isPaginated) {
                setTotalCount(specsResponse.total);
                setHasMore(specsResponse.has_more);
                setSpecsSummary(specsResponse.summary);
            } else {
                // Legacy fallback — compute from loaded data
                const nonTemplateSpecs = specsWithMetadata.filter((s: Spec) => !s.name.startsWith('templates/'));
                setTotalCount(nonTemplateSpecs.length);
                setHasMore(false);
                setSpecsSummary({
                    total_all: nonTemplateSpecs.length,
                    automated_count: nonTemplateSpecs.filter((s: Spec) => s.is_automated).length,
                    all_tags: Array.from(new Set(nonTemplateSpecs.flatMap((s: Spec) => s.metadata?.tags || []))).sort() as string[]
                });
            }
        } catch (err) {
            console.error(err);
        } finally {
            setLoading(false);
            setIsLoadingMore(false);
        }
    }, [currentProject?.id, projectLoading, debouncedSearchTerm, selectedTags, automatedOnly]);

    // Fetch specs when filters change
    useEffect(() => {
        if (projectLoading) return;
        fetchSpecs(0, false);
    }, [fetchSpecs]);

    // Check TestRail config and load mappings
    useEffect(() => {
        if (!currentProject?.id) return;
        fetch(`${API_BASE}/testrail/${encodeURIComponent(currentProject.id)}/config`)
            .then(res => res.json())
            .then(data => {
                setTrConfigured(data.configured === true);
                if (data.configured) {
                    setTrConfig({ project_id: data.project_id, suite_id: data.suite_id });
                    // Load mappings
                    fetch(`${API_BASE}/testrail/${encodeURIComponent(currentProject.id)}/mappings`)
                        .then(r => r.json())
                        .then((mappings: any[]) => {
                            setTrMappings(new Set(mappings.map(m => m.spec_name)));
                        })
                        .catch(() => {});
                }
            })
            .catch(() => {});
    }, [currentProject?.id]);

    const toggleFolder = (path: string) => {
        const next = new Set(expandedFolders);
        if (next.has(path)) next.delete(path);
        else next.add(path);
        setExpandedFolders(next);
    };

    const toggleTemplatesFolder = (path: string) => {
        const next = new Set(templatesExpandedFolders);
        if (next.has(path)) next.delete(path);
        else next.add(path);
        setTemplatesExpandedFolders(next);
    };

    const [runModalOpen, setRunModalOpen] = useState(false);
    const [selectedSpec, setSelectedSpec] = useState<string | null>(null);
    const [selectedBrowser, setSelectedBrowser] = useState('chromium');
    const [hybridHealing, setHybridHealing] = useState(false);  // false = Automated Repair, true = Extended Recovery
    const [maxIterations, setMaxIterations] = useState(20);
    const [isStartingRun, setIsStartingRun] = useState(false);

    const [tagEditModalOpen, setTagEditModalOpen] = useState(false);
    const [editingSpecName, setEditingSpecName] = useState<string | null>(null);
    const [editingTags, setEditingTags] = useState<string[]>([]);

    const [splitModalOpen, setSplitModalOpen] = useState(false);
    const [splitSpecName, setSplitSpecName] = useState<string | null>(null);
    const [splitting, setSplitting] = useState(false);
    const [splitMode, setSplitMode] = useState<'individual' | 'grouped'>('individual');

    const [deleteModalOpen, setDeleteModalOpen] = useState(false);
    const [deleteSpecName, setDeleteSpecName] = useState<string | null>(null);
    const [deleteSpecHasCode, setDeleteSpecHasCode] = useState(false);
    const [deleteGeneratedTest, setDeleteGeneratedTest] = useState(false);
    const [deleting, setDeleting] = useState(false);

    const [deleteFolderModalOpen, setDeleteFolderModalOpen] = useState(false);
    const [deleteFolderPath, setDeleteFolderPath] = useState<string | null>(null);
    const [deleteFolderSpecCount, setDeleteFolderSpecCount] = useState(0);
    const [deleteFolderGeneratedTests, setDeleteFolderGeneratedTests] = useState(false);
    const [deletingFolder, setDeletingFolder] = useState(false);

    const [selectedSpecs, setSelectedSpecs] = useState<Set<string>>(new Set());

    const [exportModalOpen, setExportModalOpen] = useState(false);
    const [exportFormat, setExportFormat] = useState<'xml' | 'csv'>('xml');
    const [exportSeparatedSteps, setExportSeparatedSteps] = useState(true);
    const [exporting, setExporting] = useState(false);

    // TestRail push state
    const [trConfigured, setTrConfigured] = useState(false);
    const [trConfig, setTrConfig] = useState<{ project_id: number | null; suite_id: number | null }>({ project_id: null, suite_id: null });
    const [pushModalOpen, setPushModalOpen] = useState(false);
    const [pushing, setPushing] = useState(false);
    const [pushResult, setPushResult] = useState<{ pushed: number; updated: number; failed: number; errors: string[] } | null>(null);
    const [trMappings, setTrMappings] = useState<Set<string>>(new Set());

    // Rename state
    const [renamingPath, setRenamingPath] = useState<string | null>(null);
    const [renameValue, setRenameValue] = useState('');
    const [renameIsFolder, setRenameIsFolder] = useState(false);
    const [renameLoading, setRenameLoading] = useState(false);
    const [renameError, setRenameError] = useState<string | null>(null);

    // Create folder state
    const [createFolderModalOpen, setCreateFolderModalOpen] = useState(false);
    const [newFolderName, setNewFolderName] = useState('');
    const [newFolderParent, setNewFolderParent] = useState('');
    const [creatingFolder, setCreatingFolder] = useState(false);
    const [createFolderError, setCreateFolderError] = useState<string | null>(null);

    // Track manually created empty folders so they appear in tree
    const [emptyFolders, setEmptyFolders] = useState<Set<string>>(new Set());

    // Drag-and-drop state
    const [draggedItem, setDraggedItem] = useState<{
        path: string;
        type: 'file' | 'folder';
        isTemplate: boolean;
    } | null>(null);
    const [dropTarget, setDropTarget] = useState<string | null>(null);
    const [isMoving, setIsMoving] = useState(false);

    // Drag-and-drop handlers
    const handleDragStart = (e: React.DragEvent, path: string, type: 'file' | 'folder', isTemplate: boolean) => {
        e.stopPropagation();
        setDraggedItem({ path, type, isTemplate });
        e.dataTransfer.effectAllowed = 'move';
        e.dataTransfer.setData('text/plain', path);
    };

    const handleDragOver = (e: React.DragEvent, targetPath: string, isFolder: boolean, isTemplate: boolean) => {
        e.preventDefault();
        e.stopPropagation();

        if (!draggedItem) return;

        // Can only drop on folders
        if (!isFolder) return;

        // Prevent dropping on self or into children of self (for folders)
        if (draggedItem.path === targetPath) return;
        if (draggedItem.type === 'folder' && targetPath.startsWith(draggedItem.path + '/')) return;

        // Prevent cross-type moves (specs to templates or vice versa)
        if (draggedItem.isTemplate !== isTemplate) return;

        e.dataTransfer.dropEffect = 'move';
        // Only update state if target actually changed to avoid unnecessary re-renders
        if (dropTarget !== targetPath) {
            setDropTarget(targetPath);
        }
    };

    const handleDragLeave = (e: React.DragEvent) => {
        e.preventDefault();
        e.stopPropagation();
        // Don't clear on leave - let dragover set the new target
        // The complex relatedTarget check causes rapid state oscillations
        // State is cleared on dragend instead
    };

    const handleDrop = async (e: React.DragEvent, targetFolder: string, isTemplate: boolean) => {
        e.preventDefault();
        e.stopPropagation();

        if (!draggedItem || isMoving) return;

        // Validate same type (templates vs specs)
        if (draggedItem.isTemplate !== isTemplate) {
            setDraggedItem(null);
            setDropTarget(null);
            return;
        }

        // Prevent dropping on self
        if (draggedItem.path === targetFolder) {
            setDraggedItem(null);
            setDropTarget(null);
            return;
        }

        // Prevent moving folder into itself
        if (draggedItem.type === 'folder' && targetFolder.startsWith(draggedItem.path + '/')) {
            setDraggedItem(null);
            setDropTarget(null);
            return;
        }

        setIsMoving(true);

        try {
            // For templates, we need to add 'templates/' prefix back
            const sourcePath = isTemplate ? `templates/${draggedItem.path}` : draggedItem.path;
            const destFolder = isTemplate ? (targetFolder ? `templates/${targetFolder}` : 'templates') : targetFolder;

            const res = await fetch(`${API_BASE}/specs/move`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    source_path: sourcePath,
                    destination_folder: destFolder,
                    is_folder: draggedItem.type === 'folder',
                    project_id: currentProject?.id
                })
            });

            if (!res.ok) {
                const error = await res.json();
                alert(error.detail || 'Failed to move item');
            } else {
                // Refresh specs list
                await refetchSpecs();
            }
        } catch (error) {
            console.error('Move failed:', error);
            alert('Failed to move item');
        } finally {
            setIsMoving(false);
            setDraggedItem(null);
            setDropTarget(null);
        }
    };

    const handleDragEnd = () => {
        setDraggedItem(null);
        setDropTarget(null);
    };

    // Handle drop to root level
    const handleRootDrop = async (e: React.DragEvent, isTemplate: boolean) => {
        e.preventDefault();
        e.stopPropagation();
        await handleDrop(e, '', isTemplate);
    };

    const openRunModal = (specName: string, e: React.MouseEvent) => {
        e.preventDefault();
        e.stopPropagation();
        setSelectedSpec(specName);
        setRunModalOpen(true);
    };

    const confirmRun = async () => {
        if (!selectedSpec || isStartingRun) return;

        setIsStartingRun(true);
        try {
            const res = await fetch(`${API_BASE}/runs`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    spec_name: selectedSpec,
                    browser: selectedBrowser,
                    hybrid: hybridHealing,
                    max_iterations: hybridHealing ? maxIterations : undefined,
                    project_id: currentProject?.id
                })
            });
            const data = await res.json();
            if (data.status === 'started') {
                console.log('Run started', data.mode);
            }
        } catch (e) {
            console.error('Failed to start run');
        } finally {
            setRunModalOpen(false);
            setSelectedSpec(null);
            setHybridHealing(false);
            setIsStartingRun(false);
        }
    };

    const openSplitModal = (specName: string, e: React.MouseEvent) => {
        e.preventDefault();
        e.stopPropagation();
        setSplitSpecName(specName);
        setSplitModalOpen(true);
    };

    const confirmSplit = async () => {
        if (!splitSpecName) return;
        setSplitting(true);

        try {
            const res = await fetch(`${API_BASE}/specs/split`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    spec_name: splitSpecName,
                    project_id: currentProject?.id,
                    mode: splitMode
                })
            });
            const data = await res.json();

            if (!res.ok) {
                // API returned an error
                alert(`Failed to split spec: ${data.detail || 'Unknown error'}`);
                return;
            }

            if (data.count > 0) {
                const modeText = splitMode === 'grouped'
                    ? `Successfully created ${data.count} grouped specs!`
                    : `Successfully split into ${data.count} individual test specs!`;
                const groupInfo = data.groups?.length
                    ? `\n\nGroups: ${data.groups.map((g: any) => `${g.name} (${g.test_ids?.length || 0} tests)`).join(', ')}`
                    : '';
                alert(`${modeText}${groupInfo}\n\nOutput: ${data.output_dir}`);

                // Refresh specs list
                await refetchSpecs();

                setSplitModalOpen(false);
                setSplitSpecName(null);
                setSplitMode('individual');
            } else {
                alert('No test cases found in this spec to split.');
            }
        } catch (e) {
            console.error('Failed to split spec:', e);
            alert('Failed to split spec. See console for details.');
        } finally {
            setSplitting(false);
        }
    };

    const openDeleteModal = (specName: string, hasCode: boolean, e: React.MouseEvent) => {
        e.preventDefault();
        e.stopPropagation();
        setDeleteSpecName(specName);
        setDeleteSpecHasCode(hasCode);
        setDeleteGeneratedTest(false);
        setDeleteModalOpen(true);
    };

    const confirmDelete = async () => {
        if (!deleteSpecName) return;
        setDeleting(true);
        try {
            const res = await fetch(
                `${API_BASE}/specs/${deleteSpecName}?delete_generated_test=${deleteGeneratedTest}`,
                { method: 'DELETE' }
            );
            if (res.ok) {
                setSpecs(specs.filter(s => s.name !== deleteSpecName));
                setDeleteModalOpen(false);
                setDeleteSpecName(null);
            } else {
                const err = await res.json();
                alert(`Failed to delete: ${err.detail}`);
            }
        } catch (e) {
            alert('Failed to delete spec');
        } finally {
            setDeleting(false);
        }
    };

    const openDeleteFolderModal = (folderPath: string, specCount: number, e: React.MouseEvent) => {
        e.preventDefault();
        e.stopPropagation();
        setDeleteFolderPath(folderPath);
        setDeleteFolderSpecCount(specCount);
        setDeleteFolderGeneratedTests(false);
        setDeleteFolderModalOpen(true);
    };

    const confirmDeleteFolder = async () => {
        if (!deleteFolderPath) return;
        setDeletingFolder(true);
        try {
            const res = await fetch(
                `${API_BASE}/specs/folder/${deleteFolderPath}?delete_generated_tests=${deleteFolderGeneratedTests}`,
                { method: 'DELETE' }
            );
            if (res.ok) {
                const data = await res.json();
                // Remove all deleted specs from state
                setSpecs(specs.filter(s => !data.deleted_specs.includes(s.name)));
                setDeleteFolderModalOpen(false);
                setDeleteFolderPath(null);
            } else {
                const err = await res.json();
                alert(`Failed to delete folder: ${err.detail}`);
            }
        } catch (e) {
            alert('Failed to delete folder');
        } finally {
            setDeletingFolder(false);
        }
    };

    const openTagEditor = (specName: string, currentTags: string[], e: React.MouseEvent) => {
        e.preventDefault();
        e.stopPropagation();
        setEditingSpecName(specName);
        setEditingTags([...currentTags]);
        setTagEditModalOpen(true);
    };

    const saveTags = async () => {
        if (!editingSpecName) return;

        try {
            await fetch(`${API_BASE}/spec-metadata/${editingSpecName}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ tags: editingTags })
            });

            // Update local state
            setSpecs(specs.map(spec =>
                spec.name === editingSpecName
                    ? { ...spec, metadata: { ...spec.metadata, tags: editingTags } }
                    : spec
            ));

            setTagEditModalOpen(false);
            setEditingSpecName(null);
        } catch (e) {
            console.error('Failed to save tags');
            alert('Failed to save tags');
        }
    };

    const toggleSpecSelection = (specName: string, e?: React.MouseEvent) => {
        if (e) {
            e.preventDefault();
            e.stopPropagation();
        }

        const next = new Set(selectedSpecs);
        if (next.has(specName)) {
            next.delete(specName);
        } else {
            next.add(specName);
        }
        setSelectedSpecs(next);
    };

    const getAllSpecsInNode = (node: TreeNode): string[] => {
        if (node.type === 'file') return [node.spec!.name];
        return Object.values(node.children || {}).flatMap(child => getAllSpecsInNode(child));
    };

    const toggleFolderSelection = (node: TreeNode, e: React.MouseEvent) => {
        e.preventDefault();
        e.stopPropagation();

        const folderSpecs = getAllSpecsInNode(node);
        const next = new Set(selectedSpecs);

        const allInFolderSelected = folderSpecs.every(s => next.has(s));

        if (allInFolderSelected) {
            folderSpecs.forEach(s => next.delete(s));
        } else {
            folderSpecs.forEach(s => next.add(s));
        }

        setSelectedSpecs(next);
    };

    const clearSelection = () => {
        setSelectedSpecs(new Set());
    };

    const handleExport = async () => {
        if (selectedSpecs.size === 0) return;
        setExporting(true);
        try {
            const res = await fetch(`${API_BASE}/export/testrail`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    spec_names: Array.from(selectedSpecs),
                    format: exportFormat,
                    separated_steps: exportSeparatedSteps,
                    project_id: currentProject?.id
                })
            });
            if (!res.ok) {
                const err = await res.json().catch(() => ({ detail: 'Export failed' }));
                alert(err.detail || 'Export failed');
                return;
            }
            const blob = await res.blob();
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = exportFormat === 'xml' ? 'testrail-export.xml' : 'testrail-export.csv';
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            window.URL.revokeObjectURL(url);
            setExportModalOpen(false);
        } catch (e) {
            console.error('Export failed', e);
            alert('Export failed');
        } finally {
            setExporting(false);
        }
    };

    const handlePushToTestrail = async () => {
        if (selectedSpecs.size === 0 || !currentProject?.id || !trConfig.project_id || !trConfig.suite_id) return;
        setPushing(true);
        setPushResult(null);
        try {
            const res = await fetch(`${API_BASE}/testrail/${encodeURIComponent(currentProject.id)}/push-cases`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    spec_names: Array.from(selectedSpecs),
                    testrail_project_id: trConfig.project_id,
                    testrail_suite_id: trConfig.suite_id,
                })
            });
            const data = await res.json();
            if (res.ok) {
                setPushResult(data);
                // Refresh mappings
                const mappingsRes = await fetch(`${API_BASE}/testrail/${encodeURIComponent(currentProject.id)}/mappings`);
                if (mappingsRes.ok) {
                    const mappings = await mappingsRes.json();
                    setTrMappings(new Set(mappings.map((m: any) => m.spec_name)));
                }
            } else {
                setPushResult({ pushed: 0, updated: 0, failed: selectedSpecs.size, errors: [data.detail || 'Push failed'] });
            }
        } catch (e: any) {
            setPushResult({ pushed: 0, updated: 0, failed: selectedSpecs.size, errors: [e.message || 'Push failed'] });
        } finally {
            setPushing(false);
        }
    };

    // Helper to refetch specs + metadata
    const refetchSpecs = async () => {
        await fetchSpecs(0, false);
    };

    const startRename = (path: string, isFolder: boolean, currentName: string, e: React.MouseEvent) => {
        e.preventDefault();
        e.stopPropagation();
        setRenamingPath(path);
        setRenameIsFolder(isFolder);
        // For files, strip .md extension for editing
        setRenameValue(isFolder ? currentName : currentName.replace(/\.md$/, ''));
        setRenameError(null);
    };

    const cancelRename = () => {
        setRenamingPath(null);
        setRenameValue('');
        setRenameError(null);
    };

    const confirmRename = async () => {
        if (!renamingPath || !renameValue.trim() || renameLoading) return;

        setRenameLoading(true);
        setRenameError(null);

        try {
            const newName = renameIsFolder ? renameValue.trim() : renameValue.trim() + '.md';
            const res = await fetch(`${API_BASE}/specs/rename`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    old_path: renamingPath,
                    new_name: newName,
                    is_folder: renameIsFolder,
                    project_id: currentProject?.id
                })
            });

            if (!res.ok) {
                const error = await res.json();
                setRenameError(error.detail || 'Rename failed');
                return;
            }

            // Refresh specs list and clear rename state
            await refetchSpecs();
            setRenamingPath(null);
            setRenameValue('');
        } catch (error) {
            console.error('Rename failed:', error);
            setRenameError('Rename failed');
        } finally {
            setRenameLoading(false);
        }
    };

    const confirmCreateFolder = async () => {
        if (!newFolderName.trim() || creatingFolder) return;

        setCreatingFolder(true);
        setCreateFolderError(null);

        try {
            const res = await fetch(`${API_BASE}/specs/create-folder`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    folder_name: newFolderName.trim(),
                    parent_path: newFolderParent,
                    project_id: currentProject?.id
                })
            });

            if (!res.ok) {
                const error = await res.json();
                setCreateFolderError(error.detail || 'Create folder failed');
                return;
            }

            const data = await res.json();
            // Add to empty folders set so it appears in tree immediately
            setEmptyFolders(prev => new Set([...prev, data.path]));
            setCreateFolderModalOpen(false);
            setNewFolderName('');
            setNewFolderParent('');
        } catch (error) {
            console.error('Create folder failed:', error);
            setCreateFolderError('Create folder failed');
        } finally {
            setCreatingFolder(false);
        }
    };

    const handleBulkRun = async () => {
        if (selectedSpecs.size === 0) return;

        try {
            const res = await fetch(`${API_BASE}/runs/bulk`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    spec_names: Array.from(selectedSpecs),
                    browser: selectedBrowser,
                    hybrid: hybridHealing,
                    max_iterations: hybridHealing ? maxIterations : undefined,
                    project_id: currentProject?.id
                })
            });

            const data = await res.json();
            if (data.batch_id) {
                alert(`Successfully started ${data.count} test runs!`);
                clearSelection();
                router.push(`/regression/batches/${data.batch_id}`);
            } else if (data.run_ids) {
                alert(`Successfully started ${data.count} test runs!`);
                clearSelection();
                router.push('/runs');
            }
        } catch (e) {
            console.error('Bulk run failed');
            alert('Bulk run failed to start');
        }
    };

    // Tags and automated count from server summary (no client-side computation needed)
    const allTags = specsSummary?.all_tags || [];
    const automatedCount = specsSummary?.automated_count || 0;

    // Count automated specs in current selection
    const selectedAutomatedCount = useMemo(() => {
        return Array.from(selectedSpecs).filter(name => {
            const spec = specs.find(s => s.name === name);
            return spec?.is_automated;
        }).length;
    }, [selectedSpecs, specs]);

    const tree = useMemo(() => {
        const root: Record<string, TreeNode> = {};

        specs
            .filter(s => !s.name.startsWith('templates/'))  // Exclude templates from specs tab
            .forEach(spec => {
                const parts = spec.name.split('/');
                let currentLevel = root;

                parts.forEach((part, index) => {
                    const isFile = index === parts.length - 1;
                    const path = parts.slice(0, index + 1).join('/');

                    if (!currentLevel[part]) {
                        currentLevel[part] = {
                            name: part,
                            path: path,
                            type: isFile ? 'file' : 'folder',
                            children: isFile ? undefined : {},
                            spec: isFile ? spec : undefined
                        };
                    }

                    if (!isFile && currentLevel[part].children) {
                        currentLevel = currentLevel[part].children!;
                    }
                });
            });

        // Inject manually created empty folders
        emptyFolders.forEach(folderPath => {
            const parts = folderPath.split('/');
            let currentLevel = root;

            parts.forEach((part, index) => {
                const path = parts.slice(0, index + 1).join('/');
                if (!currentLevel[part]) {
                    currentLevel[part] = {
                        name: part,
                        path: path,
                        type: 'folder',
                        children: {}
                    };
                }
                if (currentLevel[part].children) {
                    currentLevel = currentLevel[part].children!;
                }
            });
        });

        return root;
    }, [specs, emptyFolders]);

    // Templates tree - show only templates with stripped prefix
    const templatesTree = useMemo(() => {
        const root: Record<string, TreeNode> = {};

        specs
            .filter(s => s.name.startsWith('templates/'))  // Only templates
            .filter(s => s.name.toLowerCase().includes(templatesSearchTerm.toLowerCase()))
            .forEach(spec => {
                // Strip 'templates/' prefix for cleaner display
                const relativeName = spec.name.substring(10);
                const parts = relativeName.split('/').filter(p => p);

                let currentLevel = root;

                parts.forEach((part, index) => {
                    const isFile = index === parts.length - 1;
                    const path = parts.slice(0, index + 1).join('/');

                    if (!currentLevel[part]) {
                        currentLevel[part] = {
                            name: part,
                            path: path,
                            type: isFile ? 'file' : 'folder',
                            children: isFile ? undefined : {},
                            spec: isFile ? spec : undefined
                        };
                    }

                    if (!isFile && currentLevel[part].children) {
                        currentLevel = currentLevel[part].children!;
                    }
                });
            });

        return root;
    }, [specs, templatesSearchTerm]);

    const renderNode = (node: TreeNode, depth: number = 0) => {
        const isExpanded = expandedFolders.has(node.path) || debouncedSearchTerm.length > 0;
        const isDragging = draggedItem?.path === node.path && !draggedItem?.isTemplate;
        const isDropTarget = dropTarget === node.path && !draggedItem?.isTemplate;

        if (node.type === 'file') {
            const isSelected = selectedSpecs.has(node.spec!.name);
            return (
                <div
                    key={node.path}
                    draggable
                    onDragStart={(e) => handleDragStart(e, node.path, 'file', false)}
                    onDragEnd={handleDragEnd}
                    style={{
                        display: 'flex',
                        alignItems: 'center',
                        borderBottom: '1px solid var(--border)',
                        background: isSelected ? 'rgba(96, 165, 250, 0.04)' : 'transparent',
                        paddingLeft: `${depth * 1.5}rem`,
                        opacity: isDragging ? 0.5 : 1,
                        cursor: 'grab'
                    }}
                >
                    <div
                        onClick={(e) => toggleSpecSelection(node.spec!.name, e)}
                        style={{ padding: '0 0.5rem 0 1rem', cursor: 'pointer', display: 'flex', alignItems: 'center' }}
                    >
                        <div style={{
                            width: '18px',
                            height: '18px',
                            borderRadius: '4px',
                            border: isSelected ? '2px solid var(--primary)' : '2px solid var(--border)',
                            background: isSelected ? 'var(--primary)' : 'transparent',
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            transition: 'all 0.2s var(--ease-smooth)',
                            color: 'white'
                        }}>
                            {isSelected && <Check size={12} strokeWidth={4} />}
                        </div>
                    </div>
                    <div
                        className="list-item"
                        onClick={() => {
                            if (renamingPath !== node.path) {
                                router.push(`/specs/${node.spec?.name}`);
                            }
                        }}
                        style={{
                            flex: 1,
                            padding: '0.875rem 1rem',
                            paddingLeft: '0.5rem',
                            marginBottom: 0,
                            borderRadius: 0,
                            border: 'none',
                            background: 'transparent',
                            cursor: renamingPath === node.path ? 'default' : 'pointer'
                        }}
                    >
                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flex: 1 }}>
                            <div style={{
                                width: 32, height: 32,
                                background: 'var(--primary-glow)',
                                borderRadius: 6,
                                display: 'flex', alignItems: 'center', justifyContent: 'center',
                                color: 'var(--primary)'
                            }}>
                                <FileText size={16} />
                            </div>
                            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem', flex: 1 }}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
                                    {renamingPath === node.path ? (
                                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.25rem' }} onClick={e => { e.preventDefault(); e.stopPropagation(); }}>
                                            <input
                                                autoFocus
                                                value={renameValue}
                                                onChange={e => { setRenameValue(e.target.value); setRenameError(null); }}
                                                onKeyDown={e => {
                                                    if (e.key === 'Enter') { e.preventDefault(); e.stopPropagation(); confirmRename(); }
                                                    if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); cancelRename(); }
                                                }}
                                                onClick={e => { e.preventDefault(); e.stopPropagation(); }}
                                                style={{
                                                    fontSize: '0.9rem',
                                                    padding: '0.2rem 0.5rem',
                                                    border: renameError ? '1px solid var(--danger)' : '1px solid var(--primary)',
                                                    borderRadius: '4px',
                                                    background: 'var(--surface)',
                                                    color: 'var(--text)',
                                                    outline: 'none',
                                                    width: '200px'
                                                }}
                                                disabled={renameLoading}
                                            />
                                            <span style={{ fontSize: '0.9rem', color: 'var(--text-secondary)' }}>.md</span>
                                            <button onClick={(e) => { e.preventDefault(); e.stopPropagation(); confirmRename(); }} className="btn-icon" style={{ width: 24, height: 24, color: 'var(--success)' }} disabled={renameLoading}>
                                                <Check size={14} />
                                            </button>
                                            <button onClick={(e) => { e.preventDefault(); e.stopPropagation(); cancelRename(); }} className="btn-icon" style={{ width: 24, height: 24, color: 'var(--text-secondary)' }} disabled={renameLoading}>
                                                <X size={14} />
                                            </button>
                                            {renameError && <span style={{ fontSize: '0.75rem', color: 'var(--danger)' }}>{renameError}</span>}
                                        </div>
                                    ) : (
                                        <span style={{ fontSize: '0.9rem', color: 'var(--text)' }}>{node.name}</span>
                                    )}
                                    {(node.spec?.spec_type === 'prd' || node.spec?.spec_type === 'native_plan' || node.spec?.spec_type === 'standard_multi') && (
                                        <>
                                            <span style={{
                                                padding: '0.125rem 0.5rem',
                                                borderRadius: '9999px',
                                                background: node.spec?.spec_type === 'native_plan' ? 'var(--success-muted)' : node.spec?.spec_type === 'standard_multi' ? 'var(--primary-glow)' : 'rgba(192, 132, 252, 0.12)',
                                                color: node.spec?.spec_type === 'native_plan' ? 'var(--success)' : node.spec?.spec_type === 'standard_multi' ? 'var(--primary)' : 'var(--accent)',
                                                fontSize: '0.7rem',
                                                fontWeight: 600,
                                                textTransform: 'uppercase',
                                                letterSpacing: '0.05em'
                                            }}>
                                                {node.spec?.spec_type === 'native_plan' ? 'Test Plan' : node.spec?.spec_type === 'standard_multi' ? 'Multi-Test' : 'PRD'}
                                            </span>
                                            {(node.spec.test_count ?? 0) > 1 && (
                                                <span style={{
                                                    padding: '0.125rem 0.5rem',
                                                    borderRadius: '9999px',
                                                    background: 'var(--primary-glow)',
                                                    color: 'var(--primary)',
                                                    fontSize: '0.7rem',
                                                    fontWeight: 600,
                                                    display: 'flex',
                                                    alignItems: 'center',
                                                    gap: '0.25rem'
                                                }}>
                                                    <TestTube size={10} />
                                                    {node.spec.test_count} tests
                                                </span>
                                            )}
                                        </>
                                    )}
                                    {node.spec?.is_automated && (
                                        <span style={{
                                            padding: '0.125rem 0.5rem',
                                            borderRadius: '9999px',
                                            background: 'var(--success-muted)',
                                            color: 'var(--success)',
                                            fontSize: '0.7rem',
                                            fontWeight: 600,
                                            display: 'flex',
                                            alignItems: 'center',
                                            gap: '0.25rem'
                                        }}>
                                            <CheckCircle size={10} />
                                            Automated
                                        </span>
                                    )}
                                    {node.spec && trMappings.has(node.spec.name) && (
                                        <span style={{
                                            padding: '0.125rem 0.5rem',
                                            borderRadius: '9999px',
                                            background: 'var(--primary-glow)',
                                            color: 'var(--primary)',
                                            fontSize: '0.7rem',
                                            fontWeight: 600,
                                            display: 'flex',
                                            alignItems: 'center',
                                            gap: '0.25rem'
                                        }}>
                                            <Link2 size={10} />
                                            TestRail
                                        </span>
                                    )}
                                </div>
                                {node.spec?.metadata?.tags && node.spec.metadata.tags.length > 0 && (
                                    <div style={{ display: 'flex', gap: '0.375rem', flexWrap: 'wrap' }}>
                                        {node.spec.metadata.tags.map(tag => (
                                            <span
                                                key={tag}
                                                style={{
                                                    fontSize: '0.7rem',
                                                    padding: '0.125rem 0.5rem',
                                                    borderRadius: '9999px',
                                                    background: 'var(--primary-glow)',
                                                    color: 'var(--primary)',
                                                    fontWeight: 500
                                                }}
                                            >
                                                {tag}
                                            </span>
                                        ))}
                                    </div>
                                )}
                            </div>
                        </div>

                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                            <button
                                className="btn-icon"
                                title="Rename Spec"
                                onClick={(e) => node.spec && startRename(node.path, false, node.name, e)}
                                style={{
                                    width: 32, height: 32,
                                    color: 'var(--text-secondary)',
                                    background: 'rgba(255, 255, 255, 0.05)'
                                }}
                            >
                                <Pencil size={14} />
                            </button>
                            <button
                                className="btn-icon"
                                title="Edit Tags"
                                onClick={(e) => node.spec && openTagEditor(node.spec.name, node.spec.metadata?.tags || [], e)}
                                style={{
                                    width: 32, height: 32,
                                    color: 'var(--text-secondary)',
                                    background: 'rgba(255, 255, 255, 0.05)'
                                }}
                            >
                                <Edit size={14} />
                            </button>
                            {(node.spec?.spec_type === 'prd' || node.spec?.spec_type === 'native_plan' || node.spec?.spec_type === 'standard_multi' || ((node.spec?.test_count ?? 0) > 1 && node.spec?.spec_type === 'standard')) && (
                                <button
                                    className="btn-icon"
                                    title="Split into individual tests"
                                    onClick={(e) => node.spec && openSplitModal(node.spec.name, e)}
                                    style={{
                                        width: 32, height: 32,
                                        color: node.spec?.spec_type === 'native_plan' ? 'var(--success)' : node.spec?.spec_type === 'standard_multi' ? 'var(--primary)' : 'var(--accent)',
                                        background: node.spec?.spec_type === 'native_plan' ? 'var(--success-muted)' : node.spec?.spec_type === 'standard_multi' ? 'var(--primary-glow)' : 'rgba(192, 132, 252, 0.12)'
                                    }}
                                >
                                    <Split size={14} />
                                </button>
                            )}
                            <button
                                className="btn-icon"
                                title="Delete Spec"
                                onClick={(e) => node.spec && openDeleteModal(node.spec.name, !!node.spec.is_automated, e)}
                                style={{
                                    width: 32, height: 32,
                                    color: 'var(--danger)',
                                    background: 'var(--danger-muted)'
                                }}
                            >
                                <Trash2 size={14} />
                            </button>
                            <button
                                className="btn-icon"
                                title="Run Spec"
                                onClick={(e) => node.spec && openRunModal(node.spec.name, e)}
                                style={{
                                    width: 32, height: 32,
                                    color: 'var(--success)',
                                    background: 'var(--success-muted)'
                                }}
                            >
                                <Play size={14} fill="currentColor" />
                            </button>
                            <ChevronRight size={18} color="var(--text-secondary)" />
                        </div>
                    </div>
                </div>
            );
        }

        // Folder
        const folderSpecs = getAllSpecsInNode(node);
        const folderIsSelected = folderSpecs.length > 0 && folderSpecs.every(s => selectedSpecs.has(s));
        const folderIsIndeterminate = !folderIsSelected && folderSpecs.some(s => selectedSpecs.has(s));

        return (
            <div
                key={node.path}
                draggable
                onDragStart={(e) => handleDragStart(e, node.path, 'folder', false)}
                onDragEnd={handleDragEnd}
                onDragOver={(e) => handleDragOver(e, node.path, true, false)}
                onDragLeave={handleDragLeave}
                onDrop={(e) => handleDrop(e, node.path, false)}
                style={{ opacity: isDragging ? 0.5 : 1 }}
            >
                <div
                    style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: '0.75rem',
                        padding: '0.75rem 1rem',
                        paddingLeft: `${depth * 1.5 + 0.5}rem`,
                        cursor: 'grab',
                        userSelect: 'none',
                        color: 'var(--text)',
                        background: isDropTarget ? 'rgba(96, 165, 250, 0.15)' : 'transparent',
                        fontSize: '0.85rem',
                        fontWeight: 700,
                        letterSpacing: '0.05em',
                        borderBottom: '1px solid var(--border)',
                        borderTop: depth === 0 && node.path !== Array.from(expandedFolders)[0] ? '1px solid var(--border)' : 'none',
                        boxShadow: isDropTarget ? 'inset 0 0 0 2px var(--primary)' : 'none'
                    }}
                    onClick={() => { if (renamingPath !== node.path) toggleFolder(node.path); }}
                >
                    <div
                        onClick={(e) => toggleFolderSelection(node, e)}
                        style={{ display: 'flex', alignItems: 'center', padding: '0 0.25rem' }}
                    >
                        <div style={{
                            width: '18px',
                            height: '18px',
                            borderRadius: '4px',
                            border: folderIsSelected || folderIsIndeterminate ? '2px solid var(--primary)' : '2px solid var(--border)',
                            background: folderIsSelected ? 'var(--primary)' : 'transparent',
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            transition: 'all 0.2s var(--ease-smooth)',
                            color: 'white'
                        }}>
                            {folderIsSelected && <Check size={12} strokeWidth={4} />}
                            {folderIsIndeterminate && (
                                <div style={{ width: '10px', height: '2px', background: 'var(--primary)', borderRadius: '1px' }}></div>
                            )}
                        </div>
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', width: 20, height: 20 }}>
                        {isExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', color: isExpanded ? 'var(--text)' : 'inherit', flex: 1 }}>
                        {isExpanded ? <FolderOpen size={16} /> : <FolderClosed size={16} />}
                        {renamingPath === node.path ? (
                            <div style={{ display: 'flex', alignItems: 'center', gap: '0.25rem' }} onClick={e => { e.stopPropagation(); }}>
                                <input
                                    autoFocus
                                    value={renameValue}
                                    onChange={e => { setRenameValue(e.target.value); setRenameError(null); }}
                                    onKeyDown={e => {
                                        if (e.key === 'Enter') { e.preventDefault(); e.stopPropagation(); confirmRename(); }
                                        if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); cancelRename(); }
                                    }}
                                    onClick={e => { e.preventDefault(); e.stopPropagation(); }}
                                    style={{
                                        fontSize: '0.85rem',
                                        padding: '0.2rem 0.5rem',
                                        border: renameError ? '1px solid var(--danger)' : '1px solid var(--primary)',
                                        borderRadius: '4px',
                                        background: 'var(--surface)',
                                        color: 'var(--text)',
                                        outline: 'none',
                                        fontWeight: 700,
                                        width: '180px'
                                    }}
                                    disabled={renameLoading}
                                />
                                <button onClick={(e) => { e.preventDefault(); e.stopPropagation(); confirmRename(); }} className="btn-icon" style={{ width: 24, height: 24, color: 'var(--success)' }} disabled={renameLoading}>
                                    <Check size={14} />
                                </button>
                                <button onClick={(e) => { e.preventDefault(); e.stopPropagation(); cancelRename(); }} className="btn-icon" style={{ width: 24, height: 24, color: 'var(--text-secondary)' }} disabled={renameLoading}>
                                    <X size={14} />
                                </button>
                                {renameError && <span style={{ fontSize: '0.75rem', color: 'var(--danger)' }}>{renameError}</span>}
                            </div>
                        ) : (
                            <span>{formatFolderName(node.name)}</span>
                        )}
                    </div>
                    <button
                        className="btn btn-secondary btn-sm"
                        onClick={async (e) => {
                            e.stopPropagation();
                            const folderSpecs = getAllSpecsInNode(node);
                            if (folderSpecs.length > 0) {
                                if (confirm(`Run all ${folderSpecs.length} specs in '${node.name}'?`)) {
                                    try {
                                        const res = await fetch(`${API_BASE}/runs/bulk`, {
                                            method: 'POST',
                                            headers: { 'Content-Type': 'application/json' },
                                            body: JSON.stringify({
                                                spec_names: folderSpecs,
                                                browser: selectedBrowser,
                                                project_id: currentProject?.id
                                            })
                                        });

                                        const data = await res.json();
                                        if (data.batch_id) {
                                            alert(`Successfully started ${data.count} test runs!`);
                                            router.push(`/regression/batches/${data.batch_id}`);
                                        } else if (data.run_ids) {
                                            alert(`Successfully started ${data.count} test runs!`);
                                            router.push('/runs');
                                        }
                                    } catch (e) {
                                        console.error('Bulk run failed');
                                        alert('Bulk run failed to start');
                                    }
                                }
                            }
                        }}
                        style={{ padding: '0.25rem 0.5rem', fontSize: '0.75rem' }}
                    >
                        Run All
                    </button>
                    <button
                        className="btn-icon"
                        title="Rename Folder"
                        onClick={(e) => startRename(node.path, true, node.name, e)}
                        style={{
                            width: 32, height: 32,
                            color: 'var(--text-secondary)',
                            background: 'rgba(255, 255, 255, 0.05)'
                        }}
                    >
                        <Pencil size={14} />
                    </button>
                    <button
                        className="btn-icon"
                        title="Delete Folder"
                        onClick={(e) => openDeleteFolderModal(node.path, folderSpecs.length, e)}
                        style={{
                            width: 32, height: 32,
                            color: 'var(--danger)',
                            background: 'var(--danger-muted)'
                        }}
                    >
                        <Trash2 size={14} />
                    </button>
                </div>
                {isExpanded && node.children && (
                    <div style={{ background: 'var(--surface)' }}>
                        {Object.values(node.children)
                            .sort((a, b) => {
                                if (a.type !== b.type) return a.type === 'folder' ? -1 : 1;
                                return a.name.localeCompare(b.name);
                            })
                            .map(child => renderNode(child, depth + 1))
                        }
                    </div>
                )}
            </div>
        );
    };

    // Simplified render function for templates tab (no bulk selection, delete, split)
    const renderTemplateNode = (node: TreeNode, depth: number = 0) => {
        const isExpanded = templatesExpandedFolders.has(node.path) || templatesSearchTerm.length > 0;
        const isDraggingTemplate = draggedItem?.path === node.path && draggedItem?.isTemplate;
        const isDropTargetTemplate = dropTarget === node.path && draggedItem?.isTemplate;

        if (node.type === 'file') {
            const isAutomated = node.spec?.is_automated;
            return (
                <div
                    key={node.path}
                    draggable
                    onDragStart={(e) => handleDragStart(e, node.path, 'file', true)}
                    onDragEnd={handleDragEnd}
                    style={{
                        display: 'flex',
                        alignItems: 'center',
                        borderBottom: '1px solid var(--border)',
                        paddingLeft: `${depth * 1.5}rem`,
                        opacity: isDraggingTemplate ? 0.5 : 1,
                        cursor: 'grab'
                    }}
                >
                    <div style={{ padding: '0 0.5rem 0 1rem', display: 'flex', alignItems: 'center' }}>
                        <div style={{ width: 18 }}></div>
                    </div>
                    <Link
                        href={`/specs/${node.spec?.name}`}
                        className="list-item"
                        style={{
                            flex: 1,
                            padding: '0.875rem 1rem',
                            paddingLeft: '0.5rem',
                            marginBottom: 0,
                            borderRadius: 0,
                            border: 'none',
                            background: 'transparent'
                        }}
                    >
                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flex: 1 }}>
                            <div style={{
                                width: 32, height: 32,
                                background: 'var(--primary-glow)',
                                borderRadius: 6,
                                display: 'flex', alignItems: 'center', justifyContent: 'center',
                                color: 'var(--primary)'
                            }}>
                                <FileText size={16} />
                            </div>
                            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem', flex: 1 }}>
                                <span style={{ fontSize: '0.9rem', color: 'var(--text)' }}>{node.name}</span>
                                {node.spec?.metadata?.tags && node.spec.metadata.tags.length > 0 && (
                                    <div style={{ display: 'flex', gap: '0.375rem', flexWrap: 'wrap' }}>
                                        {node.spec.metadata.tags.map(tag => (
                                            <span
                                                key={tag}
                                                style={{
                                                    fontSize: '0.7rem',
                                                    padding: '0.125rem 0.5rem',
                                                    borderRadius: '9999px',
                                                    background: 'var(--primary-glow)',
                                                    color: 'var(--primary)',
                                                    fontWeight: 500
                                                }}
                                            >
                                                {tag}
                                            </span>
                                        ))}
                                    </div>
                                )}
                            </div>

                            {/* Automation Status Badge */}
                            <div style={{ marginRight: '1rem' }}>
                                {isAutomated ? (
                                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.25rem', padding: '0.25rem 0.5rem', background: 'var(--success-muted)', color: 'var(--success)', borderRadius: '4px', fontSize: '0.75rem', fontWeight: 600 }}>
                                        <Zap size={12} fill="currentColor" />
                                        <span>Automated</span>
                                    </div>
                                ) : (
                                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.25rem', padding: '0.25rem 0.5rem', background: 'var(--danger-muted)', color: 'var(--error)', borderRadius: '4px', fontSize: '0.75rem', fontWeight: 600 }}>
                                        <AlertCircle size={12} />
                                        <span>Draft</span>
                                    </div>
                                )}
                            </div>
                        </div>

                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                            <button
                                className="btn-icon"
                                title="Run to Automate"
                                onClick={(e) => node.spec && openRunModal(node.spec.name, e)}
                                style={{
                                    width: 32, height: 32,
                                    color: 'var(--success)',
                                    background: 'var(--success-muted)'
                                }}
                            >
                                <Play size={14} fill="currentColor" />
                            </button>
                            <ChevronRight size={18} color="var(--text-secondary)" />
                        </div>
                    </Link>
                </div>
            );
        }

        // Folder
        return (
            <div
                key={node.path}
                draggable
                onDragStart={(e) => handleDragStart(e, node.path, 'folder', true)}
                onDragEnd={handleDragEnd}
                onDragOver={(e) => handleDragOver(e, node.path, true, true)}
                onDragLeave={handleDragLeave}
                onDrop={(e) => handleDrop(e, node.path, true)}
                style={{ opacity: isDraggingTemplate ? 0.5 : 1 }}
            >
                <div
                    style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: '0.75rem',
                        padding: '0.75rem 1rem',
                        paddingLeft: `${depth * 1.5 + 0.5}rem`,
                        cursor: 'grab',
                        userSelect: 'none',
                        color: 'var(--text)',
                        background: isDropTargetTemplate ? 'rgba(96, 165, 250, 0.15)' : 'transparent',
                        fontSize: '0.85rem',
                        fontWeight: 700,
                        letterSpacing: '0.05em',
                        borderBottom: '1px solid var(--border)',
                        borderTop: depth === 0 && node.path !== Array.from(templatesExpandedFolders)[0] ? '1px solid var(--border)' : 'none',
                        boxShadow: isDropTargetTemplate ? 'inset 0 0 0 2px var(--primary)' : 'none'
                    }}
                    onClick={() => toggleTemplatesFolder(node.path)}
                >
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', width: 20, height: 20 }}>
                        {isExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', color: isExpanded ? 'var(--text)' : 'inherit', flex: 1 }}>
                        {isExpanded ? <FolderOpen size={16} /> : <FolderClosed size={16} />}
                        <span>{formatFolderName(node.name)}</span>
                    </div>
                </div>
                {isExpanded && node.children && (
                    <div style={{ background: 'var(--surface)' }}>
                        {Object.values(node.children)
                            .sort((a, b) => {
                                if (a.type !== b.type) return a.type === 'folder' ? -1 : 1;
                                return a.name.localeCompare(b.name);
                            })
                            .map(child => renderTemplateNode(child, depth + 1))
                        }
                    </div>
                )}
            </div>
        );
    };

    // Skeleton loading component
    const SkeletonRow = ({ depth = 0 }: { depth?: number }) => (
        <div style={{
            display: 'flex',
            alignItems: 'center',
            padding: '0.875rem 1rem',
            paddingLeft: `${depth * 1.5 + 1}rem`,
            borderBottom: '1px solid var(--border)',
            gap: '0.75rem'
        }}>
            <div style={{
                width: 18,
                height: 18,
                borderRadius: 4,
                background: 'var(--surface-hover)',
                animation: 'pulse 1.5s ease-in-out infinite'
            }} />
            <div style={{
                width: 32,
                height: 32,
                borderRadius: 6,
                background: 'var(--surface-hover)',
                animation: 'pulse 1.5s ease-in-out infinite'
            }} />
            <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                <div style={{
                    height: 14,
                    width: `${Math.random() * 30 + 40}%`,
                    borderRadius: 4,
                    background: 'var(--surface-hover)',
                    animation: 'pulse 1.5s ease-in-out infinite'
                }} />
                <div style={{
                    height: 10,
                    width: `${Math.random() * 20 + 20}%`,
                    borderRadius: 4,
                    background: 'var(--surface-hover)',
                    animation: 'pulse 1.5s ease-in-out infinite'
                }} />
            </div>
            <div style={{
                width: 32,
                height: 32,
                borderRadius: 6,
                background: 'var(--surface-hover)',
                animation: 'pulse 1.5s ease-in-out infinite'
            }} />
        </div>
    );

    if (loading || projectLoading) return (
        <PageLayout tier="standard">
            <PageHeader title="Test Specs" subtitle="Manage and execute your test specifications and templates." />
            <div style={{ marginBottom: '1.5rem' }}>
                <div style={{
                    height: 48,
                    borderRadius: 8,
                    background: 'var(--surface-hover)',
                    animation: 'pulse 1.5s ease-in-out infinite'
                }} />
            </div>

            <div className="card" style={{ padding: 0, overflow: 'hidden', border: '1px solid var(--border)' }}>
                {/* Skeleton folder */}
                <div style={{
                    display: 'flex',
                    alignItems: 'center',
                    padding: '0.75rem 1rem',
                    borderBottom: '1px solid var(--border)',
                    gap: '0.75rem'
                }}>
                    <div style={{ width: 18, height: 18, borderRadius: 4, background: 'var(--surface-hover)', animation: 'pulse 1.5s ease-in-out infinite' }} />
                    <div style={{ width: 20, height: 20, borderRadius: 4, background: 'var(--surface-hover)', animation: 'pulse 1.5s ease-in-out infinite' }} />
                    <div style={{ height: 14, width: '20%', borderRadius: 4, background: 'var(--surface-hover)', animation: 'pulse 1.5s ease-in-out infinite' }} />
                </div>
                {/* Skeleton rows */}
                {[...Array(8)].map((_, i) => <SkeletonRow key={i} depth={1} />)}
            </div>

            <style jsx>{`
                @keyframes pulse {
                    0%, 100% { opacity: 1; }
                    50% { opacity: 0.4; }
                }
            `}</style>
        </PageLayout>
    );

    return (
        <PageLayout tier="standard">
            <PageHeader
                title="Test Specs"
                subtitle="Manage and execute your test specifications and templates."
                breadcrumb={<WorkflowBreadcrumb />}
                actions={
                    activeTab === 'specs' ? (
                        <>
                            <button
                                className="btn btn-secondary"
                                onClick={() => { setCreateFolderModalOpen(true); setNewFolderName(''); setNewFolderParent(''); setCreateFolderError(null); }}
                                style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', padding: '0.6rem 1.25rem' }}
                            >
                                <FolderPlus size={18} />
                                New Folder
                            </button>
                            <Link href="/specs/new" className="btn btn-primary" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', textDecoration: 'none', padding: '0.6rem 1.25rem' }}>
                                <Plus size={18} />
                                New Spec
                            </Link>
                        </>
                    ) : (
                        <Link href="/templates/new" className="btn btn-primary" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', textDecoration: 'none', padding: '0.6rem 1.25rem' }}>
                            <Plus size={18} />
                            New Template
                        </Link>
                    )
                }
            />

            <header style={{ marginBottom: '2.5rem' }}>

                {/* Tabs */}
                <div className="animate-in stagger-2" style={{ display: 'flex', gap: '0.5rem', marginBottom: '1.5rem', borderBottom: '1px solid var(--border-subtle)', paddingBottom: '1rem' }}>
                    {[
                        { id: 'specs' as TabType, label: 'Specs', icon: FileText },
                        { id: 'templates' as TabType, label: 'Templates', icon: LayoutTemplate }
                    ].map(tab => (
                        <button
                            key={tab.id}
                            onClick={() => setActiveTab(tab.id)}
                            style={{
                                display: 'flex',
                                alignItems: 'center',
                                gap: '0.5rem',
                                padding: '0.75rem 1.25rem',
                                borderRadius: 'var(--radius)',
                                border: activeTab === tab.id ? '2px solid var(--primary)' : '1px solid var(--border)',
                                background: activeTab === tab.id ? 'var(--primary-glow)' : 'transparent',
                                color: activeTab === tab.id ? 'var(--primary)' : 'var(--text-secondary)',
                                fontSize: '0.9rem',
                                fontWeight: 600,
                                cursor: 'pointer',
                                transition: 'all 0.2s var(--ease-smooth)'
                            }}
                        >
                            <tab.icon size={18} />
                            {tab.label}
                        </button>
                    ))}
                </div>

                {/* Specs Tab Filters */}
                {activeTab === 'specs' && (
                    <>
                        {/* Filters Row */}
                <div style={{ marginBottom: '1.5rem', display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                    {/* Automated Only Toggle */}
                    <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
                        <button
                            onClick={() => setAutomatedOnly(!automatedOnly)}
                            style={{
                                display: 'flex',
                                alignItems: 'center',
                                gap: '0.5rem',
                                padding: '0.5rem 1rem',
                                borderRadius: '8px',
                                border: automatedOnly ? '2px solid var(--success)' : '1px solid var(--border)',
                                background: automatedOnly ? 'var(--success-muted)' : 'transparent',
                                color: automatedOnly ? 'var(--success)' : 'var(--text-secondary)',
                                fontSize: '0.85rem',
                                fontWeight: 500,
                                cursor: 'pointer',
                                transition: 'all 0.2s var(--ease-smooth)'
                            }}
                        >
                            {automatedOnly ? <ToggleRight size={18} /> : <ToggleLeft size={18} />}
                            <span>Automated Only</span>
                            <span style={{
                                padding: '0.125rem 0.5rem',
                                borderRadius: '9999px',
                                background: automatedOnly ? 'var(--success)' : 'var(--surface-hover)',
                                color: automatedOnly ? 'white' : 'var(--text-secondary)',
                                fontSize: '0.75rem',
                                fontWeight: 600
                            }}>
                                {automatedCount}
                            </span>
                        </button>
                        {automatedOnly && (
                            <span style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
                                Showing {automatedCount} automated tests
                            </span>
                        )}
                    </div>

                    {/* Tag Filters */}
                    {allTags.length > 0 && (
                        <div>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.75rem' }}>
                                <Tag size={16} color="var(--text-secondary)" />
                                <span style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', fontWeight: 500 }}>Filter by tags:</span>
                            </div>
                            <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
                                {allTags.map(tag => {
                                    const isSelected = selectedTags.includes(tag);
                                    return (
                                        <button
                                            key={tag}
                                            onClick={() => {
                                                if (isSelected) {
                                                    setSelectedTags(selectedTags.filter(t => t !== tag));
                                                } else {
                                                    setSelectedTags([...selectedTags, tag]);
                                                }
                                            }}
                                            style={{
                                                padding: '0.5rem 1rem',
                                                borderRadius: '9999px',
                                                border: isSelected ? '2px solid var(--primary)' : '1px solid var(--border)',
                                                background: isSelected ? 'var(--primary-glow)' : 'transparent',
                                                color: isSelected ? 'var(--primary)' : 'var(--text-secondary)',
                                                fontSize: '0.85rem',
                                                fontWeight: 500,
                                                cursor: 'pointer',
                                                transition: 'all 0.2s var(--ease-smooth)',
                                                display: 'flex',
                                                alignItems: 'center',
                                                gap: '0.375rem'
                                            }}
                                        >
                                            {tag}
                                            {isSelected && <X size={14} />}
                                        </button>
                                    );
                                })}
                            </div>
                        </div>
                    )}
                </div>

                <div className="input-group">
                    <div className="input-icon">
                        <Search size={18} />
                    </div>
                    <input
                        type="text"
                        placeholder="Search specs..."
                        value={searchTerm}
                        onChange={(e) => setSearchTerm(e.target.value)}
                        className="input has-icon"
                        style={{ paddingTop: '0.875rem', paddingBottom: '0.875rem' }}
                    />
                </div>
                    </>
                )}

                {/* Templates Tab Search */}
                {activeTab === 'templates' && (
                    <div className="input-group">
                        <div className="input-icon">
                            <Search size={18} />
                        </div>
                        <input
                            type="text"
                            placeholder="Search templates..."
                            value={templatesSearchTerm}
                            onChange={(e) => setTemplatesSearchTerm(e.target.value)}
                            className="input has-icon"
                            style={{ paddingTop: '0.875rem', paddingBottom: '0.875rem' }}
                        />
                    </div>
                )}
            </header>

            {/* Specs Tab Content */}
            {activeTab === 'specs' && (
                <div className="card animate-in stagger-3" style={{ padding: 0, overflow: 'hidden', border: '1px solid var(--border)' }}>
                    {Object.keys(tree).length === 0 && (
                        <EmptyState
                            icon={<Search size={32} />}
                            title="No specs found"
                            description="Create your first spec to get started."
                        />
                    )}

                    {Object.values(tree)
                        .sort((a, b) => {
                            if (a.type !== b.type) return a.type === 'folder' ? -1 : 1;
                            return a.name.localeCompare(b.name);
                        })
                        .map(node => renderNode(node))}

                    {/* Root Drop Zone for Specs */}
                    {draggedItem && !draggedItem.isTemplate && (
                        <div
                            onDragOver={(e) => {
                                e.preventDefault();
                                e.stopPropagation();
                                if (dropTarget !== '__root__') {
                                    setDropTarget('__root__');
                                }
                            }}
                            onDragLeave={(e) => {
                                e.preventDefault();
                                // Don't clear - let dragend handle cleanup
                            }}
                            onDrop={(e) => handleRootDrop(e, false)}
                            style={{
                                padding: '1rem',
                                margin: '0.5rem',
                                border: dropTarget === '__root__' ? '2px solid var(--primary)' : '2px dashed var(--border)',
                                borderRadius: '8px',
                                background: dropTarget === '__root__' ? 'var(--primary-glow)' : 'transparent',
                                display: 'flex',
                                alignItems: 'center',
                                justifyContent: 'center',
                                gap: '0.5rem',
                                color: dropTarget === '__root__' ? 'var(--primary)' : 'var(--text-secondary)',
                                fontSize: '0.85rem'
                            }}
                        >
                            <ArrowDownToLine size={16} />
                            Drop here to move to root
                        </div>
                    )}

                    {/* Load More / Pagination Footer */}
                    {(hasMore || specs.filter(s => !s.name.startsWith('templates/')).length > 0) && (
                        <div style={{
                            padding: '1rem',
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'space-between',
                            borderTop: '1px solid var(--border)',
                            background: 'var(--surface)'
                        }}>
                            <span style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
                                Showing {specs.filter(s => !s.name.startsWith('templates/')).length} of {totalCount} specs
                                {specsSummary && totalCount !== specsSummary.total_all && (
                                    <span> (filtered from {specsSummary.total_all} total)</span>
                                )}
                            </span>
                            {hasMore && (
                                <button
                                    className="btn btn-secondary"
                                    onClick={() => fetchSpecs(specs.filter(s => !s.name.startsWith('templates/')).length, true)}
                                    disabled={isLoadingMore}
                                    style={{
                                        display: 'flex',
                                        alignItems: 'center',
                                        gap: '0.5rem',
                                        padding: '0.5rem 1rem',
                                        fontSize: '0.85rem'
                                    }}
                                >
                                    {isLoadingMore ? (
                                        <>
                                            <Loader2 size={14} className="animate-spin" style={{ animation: 'spin 1s linear infinite' }} />
                                            Loading...
                                        </>
                                    ) : (
                                        <>Load More</>
                                    )}
                                </button>
                            )}
                        </div>
                    )}
                </div>
            )}

            {/* Templates Tab Content */}
            {activeTab === 'templates' && (
                <div className="card animate-in stagger-3" style={{ padding: 0, overflow: 'hidden', border: '1px solid var(--border)' }}>
                    {Object.keys(templatesTree).length === 0 && (
                        <EmptyState
                            icon={<FileText size={32} />}
                            title="No templates found"
                            description="Create one in specs/templates/ to get started."
                        />
                    )}

                    {Object.values(templatesTree)
                        .sort((a, b) => {
                            if (a.type !== b.type) return a.type === 'folder' ? -1 : 1;
                            return a.name.localeCompare(b.name);
                        })
                        .map(node => renderTemplateNode(node))}

                    {/* Root Drop Zone for Templates */}
                    {draggedItem && draggedItem.isTemplate && (
                        <div
                            onDragOver={(e) => {
                                e.preventDefault();
                                e.stopPropagation();
                                if (dropTarget !== '__root__') {
                                    setDropTarget('__root__');
                                }
                            }}
                            onDragLeave={(e) => {
                                e.preventDefault();
                                // Don't clear - let dragend handle cleanup
                            }}
                            onDrop={(e) => handleRootDrop(e, true)}
                            style={{
                                padding: '1rem',
                                margin: '0.5rem',
                                border: dropTarget === '__root__' ? '2px solid var(--primary)' : '2px dashed var(--border)',
                                borderRadius: '8px',
                                background: dropTarget === '__root__' ? 'var(--primary-glow)' : 'transparent',
                                display: 'flex',
                                alignItems: 'center',
                                justifyContent: 'center',
                                gap: '0.5rem',
                                color: dropTarget === '__root__' ? 'var(--primary)' : 'var(--text-secondary)',
                                fontSize: '0.85rem'
                            }}
                        >
                            <ArrowDownToLine size={16} />
                            Drop here to move to templates root
                        </div>
                    )}
                </div>
            )}

            {/* Tag Edit Modal */}
            {tagEditModalOpen && (
                <div className="modal-overlay" onClick={() => setTagEditModalOpen(false)}>
                    <div className="modal-content" onClick={e => e.stopPropagation()} style={{ width: '500px' }}>
                        <h2 style={{ marginBottom: '1.5rem', display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                            <Tag size={24} />
                            Edit Tags
                        </h2>

                        <div style={{ marginBottom: '1.5rem' }}>
                            <label style={{ display: 'block', marginBottom: '0.5rem', color: 'var(--text-secondary)', fontSize: '0.9rem' }}>
                                Spec
                            </label>
                            <div style={{ padding: '0.75rem', background: 'var(--surface-hover)', borderRadius: '6px', fontSize: '0.95rem', fontWeight: 500 }}>
                                {editingSpecName}
                            </div>
                        </div>

                        <div style={{ marginBottom: '2rem' }}>
                            <label style={{ display: 'block', marginBottom: '0.75rem', color: 'var(--text-secondary)', fontSize: '0.9rem' }}>
                                Tags
                            </label>
                            <TagEditor
                                tags={editingTags}
                                onTagsChange={setEditingTags}
                                allTags={allTags}
                                placeholder="Add tags..."
                            />
                        </div>

                        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '1rem' }}>
                            <button className="btn btn-secondary" onClick={() => setTagEditModalOpen(false)}>
                                Cancel
                            </button>
                            <button className="btn btn-primary" onClick={saveTags}>
                                Save Changes
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {/* Split Multi-Test Spec Modal */}
            {splitModalOpen && (
                <div className="modal-overlay" onClick={() => { if (!splitting) { setSplitModalOpen(false); setSplitMode('individual'); } }}>
                    <div className="modal-content" onClick={e => e.stopPropagation()} style={{ width: '500px' }}>
                        <h2 style={{ marginBottom: '1.5rem', display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                            <Split size={24} />
                            Split Multi-Test Spec
                        </h2>

                        <div style={{ marginBottom: '1.5rem' }}>
                            <label style={{ display: 'block', marginBottom: '0.5rem', color: 'var(--text-secondary)', fontSize: '0.9rem' }}>
                                Spec
                            </label>
                            <div style={{ padding: '0.75rem', background: 'var(--surface-hover)', borderRadius: '6px', fontSize: '0.95rem', fontWeight: 500 }}>
                                {splitSpecName}
                            </div>
                        </div>

                        <div style={{
                            padding: '1rem',
                            background: 'rgba(192, 132, 252, 0.06)',
                            border: '1px solid rgba(192, 132, 252, 0.2)',
                            borderRadius: '8px',
                            marginBottom: '1.5rem'
                        }}>
                            <div style={{ fontSize: '0.9rem', color: 'var(--text)', marginBottom: '0.75rem' }}>
                                <strong>What is splitting?</strong>
                            </div>
                            <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', lineHeight: '1.6' }}>
                                This spec contains multiple test cases. Splitting will create individual test files for each test case, allowing you to run and debug them separately. AI-powered extraction is used when the format is non-standard.
                            </div>
                        </div>

                        {/* Split Mode Selection */}
                        <div style={{ marginBottom: '1.5rem' }}>
                            <label style={{ display: 'block', marginBottom: '0.75rem', color: 'var(--text-secondary)', fontSize: '0.9rem' }}>
                                Split Mode
                            </label>
                            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                                <label
                                    style={{
                                        display: 'flex',
                                        alignItems: 'flex-start',
                                        gap: '0.75rem',
                                        padding: '0.75rem',
                                        border: `1px solid ${splitMode === 'individual' ? 'var(--accent)' : 'var(--border)'}`,
                                        borderRadius: '8px',
                                        cursor: splitting ? 'default' : 'pointer',
                                        background: splitMode === 'individual' ? 'rgba(192, 132, 252, 0.06)' : 'transparent',
                                        transition: 'all 0.15s ease',
                                        opacity: splitting ? 0.6 : 1
                                    }}
                                >
                                    <input
                                        type="radio"
                                        name="splitMode"
                                        value="individual"
                                        checked={splitMode === 'individual'}
                                        onChange={() => setSplitMode('individual')}
                                        disabled={splitting}
                                        style={{ marginTop: '2px' }}
                                    />
                                    <div>
                                        <div style={{ fontWeight: 500, fontSize: '0.9rem', color: 'var(--text)' }}>
                                            Individual Tests
                                        </div>
                                        <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginTop: '2px' }}>
                                            Create one spec file per test case
                                        </div>
                                    </div>
                                </label>
                                <label
                                    style={{
                                        display: 'flex',
                                        alignItems: 'flex-start',
                                        gap: '0.75rem',
                                        padding: '0.75rem',
                                        border: `1px solid ${splitMode === 'grouped' ? 'var(--accent)' : 'var(--border)'}`,
                                        borderRadius: '8px',
                                        cursor: splitting ? 'default' : 'pointer',
                                        background: splitMode === 'grouped' ? 'rgba(192, 132, 252, 0.06)' : 'transparent',
                                        transition: 'all 0.15s ease',
                                        opacity: splitting ? 0.6 : 1
                                    }}
                                >
                                    <input
                                        type="radio"
                                        name="splitMode"
                                        value="grouped"
                                        checked={splitMode === 'grouped'}
                                        onChange={() => setSplitMode('grouped')}
                                        disabled={splitting}
                                        style={{ marginTop: '2px' }}
                                    />
                                    <div>
                                        <div style={{ fontWeight: 500, fontSize: '0.9rem', color: 'var(--text)' }}>
                                            Smart Groups
                                        </div>
                                        <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginTop: '2px' }}>
                                            AI groups related test cases together
                                        </div>
                                    </div>
                                </label>
                            </div>
                        </div>

                        {splitting && (
                            <div style={{
                                padding: '1rem',
                                background: 'rgba(96, 165, 250, 0.06)',
                                borderRadius: '8px',
                                marginBottom: '1.5rem',
                                textAlign: 'center'
                            }}>
                                <div className="loading-spinner" style={{ width: '24px', height: '24px', margin: '0 auto 0.5rem' }}></div>
                                <div style={{ fontSize: '0.9rem', color: 'var(--text-secondary)' }}>
                                    {splitMode === 'grouped' ? 'Grouping and splitting tests...' : 'Splitting tests...'}
                                </div>
                            </div>
                        )}

                        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '1rem' }}>
                            <button
                                className="btn btn-secondary"
                                onClick={() => { setSplitModalOpen(false); setSplitMode('individual'); }}
                                disabled={splitting}
                            >
                                Cancel
                            </button>
                            <button
                                className="btn btn-primary"
                                onClick={confirmSplit}
                                disabled={splitting}
                                style={{
                                    background: 'var(--accent)',
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: '0.5rem'
                                }}
                            >
                                <Split size={16} />
                                Split Tests
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {/* Delete Spec Modal */}
            {deleteModalOpen && (
                <div className="modal-overlay" onClick={() => !deleting && setDeleteModalOpen(false)}>
                    <div className="modal-content" onClick={e => e.stopPropagation()} style={{ width: '450px' }}>
                        <h2 style={{ marginBottom: '1.5rem', display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                            <Trash2 size={24} color="var(--danger)" />
                            Delete Spec
                        </h2>

                        <div style={{ marginBottom: '1.5rem' }}>
                            <p style={{ color: 'var(--text)', marginBottom: '0.5rem' }}>
                                Are you sure you want to delete this spec?
                            </p>
                            <div style={{ padding: '0.75rem', background: 'var(--surface-hover)', borderRadius: '6px', fontSize: '0.95rem', fontWeight: 500 }}>
                                {deleteSpecName}
                            </div>
                        </div>

                        {deleteSpecHasCode && (
                            <div style={{
                                padding: '1rem',
                                background: 'rgba(248, 113, 113, 0.06)',
                                border: '1px solid rgba(248, 113, 113, 0.2)',
                                borderRadius: '8px',
                                marginBottom: '1.5rem'
                            }}>
                                <label style={{ display: 'flex', alignItems: 'flex-start', gap: '0.75rem', cursor: 'pointer' }}>
                                    <input
                                        type="checkbox"
                                        checked={deleteGeneratedTest}
                                        onChange={(e) => setDeleteGeneratedTest(e.target.checked)}
                                        style={{ marginTop: '3px', accentColor: 'var(--danger)' }}
                                    />
                                    <div>
                                        <div style={{ fontWeight: 500, color: 'var(--text)', marginBottom: '0.25rem' }}>
                                            Also delete generated test file
                                        </div>
                                        <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
                                            This spec has an associated generated Playwright test. Check this to delete it as well.
                                        </div>
                                    </div>
                                </label>
                            </div>
                        )}

                        {deleting && (
                            <div style={{
                                padding: '1rem',
                                background: 'rgba(96, 165, 250, 0.06)',
                                borderRadius: '8px',
                                marginBottom: '1.5rem',
                                textAlign: 'center'
                            }}>
                                <div className="loading-spinner" style={{ width: '24px', height: '24px', margin: '0 auto 0.5rem' }}></div>
                                <div style={{ fontSize: '0.9rem', color: 'var(--text-secondary)' }}>
                                    Deleting...
                                </div>
                            </div>
                        )}

                        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '1rem' }}>
                            <button
                                className="btn btn-secondary"
                                onClick={() => setDeleteModalOpen(false)}
                                disabled={deleting}
                            >
                                Cancel
                            </button>
                            <button
                                className="btn"
                                onClick={confirmDelete}
                                disabled={deleting}
                                style={{
                                    background: 'var(--danger)',
                                    color: 'white',
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: '0.5rem'
                                }}
                            >
                                <Trash2 size={16} />
                                {deleting ? 'Deleting...' : 'Delete'}
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {/* Delete Folder Modal */}
            {deleteFolderModalOpen && (
                <div className="modal-overlay" onClick={() => !deletingFolder && setDeleteFolderModalOpen(false)}>
                    <div className="modal-content" onClick={e => e.stopPropagation()} style={{ width: '450px' }}>
                        <h2 style={{ marginBottom: '1.5rem', display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                            <Trash2 size={24} color="var(--danger)" />
                            Delete Folder
                        </h2>

                        <div style={{ marginBottom: '1.5rem' }}>
                            <p style={{ color: 'var(--text)', marginBottom: '0.5rem' }}>
                                Are you sure you want to delete this folder?
                            </p>
                            <div style={{ padding: '0.75rem', background: 'var(--surface-hover)', borderRadius: '6px', fontSize: '0.95rem', fontWeight: 500 }}>
                                {deleteFolderPath}
                            </div>
                        </div>

                        <div style={{
                            padding: '1rem',
                            background: 'var(--danger-muted)',
                            borderRadius: '8px',
                            marginBottom: '1.5rem'
                        }}>
                            <strong style={{ color: 'var(--danger)' }}>Warning:</strong> This will permanently delete <strong>{deleteFolderSpecCount} spec(s)</strong> inside this folder.
                        </div>

                        <label style={{
                            display: 'flex',
                            alignItems: 'flex-start',
                            gap: '0.75rem',
                            marginBottom: '1.5rem',
                            cursor: 'pointer'
                        }}>
                            <input
                                type="checkbox"
                                checked={deleteFolderGeneratedTests}
                                onChange={(e) => setDeleteFolderGeneratedTests(e.target.checked)}
                                style={{ marginTop: '3px', accentColor: 'var(--danger)' }}
                            />
                            <div>
                                <div style={{ fontWeight: 500, color: 'var(--text)', marginBottom: '0.25rem' }}>
                                    Also delete generated test files
                                </div>
                                <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
                                    Delete any Playwright tests generated from specs in this folder.
                                </div>
                            </div>
                        </label>

                        {deletingFolder && (
                            <div style={{
                                padding: '1rem',
                                background: 'rgba(96, 165, 250, 0.06)',
                                borderRadius: '8px',
                                marginBottom: '1.5rem',
                                textAlign: 'center'
                            }}>
                                <div className="loading-spinner" style={{ width: '24px', height: '24px', margin: '0 auto 0.5rem' }}></div>
                                <div style={{ fontSize: '0.9rem', color: 'var(--text-secondary)' }}>
                                    Deleting folder...
                                </div>
                            </div>
                        )}

                        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '1rem' }}>
                            <button
                                className="btn btn-secondary"
                                onClick={() => setDeleteFolderModalOpen(false)}
                                disabled={deletingFolder}
                            >
                                Cancel
                            </button>
                            <button
                                className="btn"
                                onClick={confirmDeleteFolder}
                                disabled={deletingFolder}
                                style={{
                                    background: 'var(--danger)',
                                    color: 'white',
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: '0.5rem'
                                }}
                            >
                                <Trash2 size={16} />
                                {deletingFolder ? 'Deleting...' : `Delete ${deleteFolderSpecCount} Specs`}
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {/* Create Folder Modal */}
            {createFolderModalOpen && (
                <div className="modal-overlay" onClick={() => !creatingFolder && setCreateFolderModalOpen(false)}>
                    <div className="modal-content" onClick={e => e.stopPropagation()} style={{ width: '450px' }}>
                        <h2 style={{ marginBottom: '1.5rem', display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                            <FolderPlus size={24} />
                            Create Folder
                        </h2>

                        <div style={{ marginBottom: '1.5rem' }}>
                            <label style={{ display: 'block', marginBottom: '0.5rem', color: 'var(--text-secondary)', fontSize: '0.9rem' }}>
                                Folder Name
                            </label>
                            <input
                                autoFocus
                                type="text"
                                value={newFolderName}
                                onChange={(e) => { setNewFolderName(e.target.value); setCreateFolderError(null); }}
                                onKeyDown={(e) => { if (e.key === 'Enter') confirmCreateFolder(); }}
                                placeholder="my-folder-name"
                                className="input"
                                style={{ width: '100%' }}
                                disabled={creatingFolder}
                            />
                            <p style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginTop: '0.5rem' }}>
                                Use lowercase letters, numbers, hyphens, and underscores.
                            </p>
                        </div>

                        {createFolderError && (
                            <div style={{
                                padding: '0.75rem 1rem',
                                background: 'var(--danger-muted)',
                                border: '1px solid rgba(248, 113, 113, 0.2)',
                                borderRadius: '8px',
                                marginBottom: '1.5rem',
                                fontSize: '0.85rem',
                                color: 'var(--danger)'
                            }}>
                                {createFolderError}
                            </div>
                        )}

                        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '1rem' }}>
                            <button
                                className="btn btn-secondary"
                                onClick={() => setCreateFolderModalOpen(false)}
                                disabled={creatingFolder}
                            >
                                Cancel
                            </button>
                            <button
                                className="btn btn-primary"
                                onClick={confirmCreateFolder}
                                disabled={creatingFolder || !newFolderName.trim()}
                                style={{
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: '0.5rem'
                                }}
                            >
                                <FolderPlus size={16} />
                                {creatingFolder ? 'Creating...' : 'Create Folder'}
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {/* Run Configuration Modal */}
            {runModalOpen && (
                <div className="modal-overlay" onClick={() => !isStartingRun && setRunModalOpen(false)}>
                    <div className="modal-content" onClick={e => e.stopPropagation()} style={{ width: '450px' }}>
                        <h2 style={{ marginBottom: '1.5rem' }}>Run Configuration</h2>

                        <div style={{ marginBottom: '1.5rem' }}>
                            <label style={{ display: 'block', marginBottom: '0.5rem', color: 'var(--text-secondary)', fontSize: '0.9rem' }}>
                                Spec
                            </label>
                            <div style={{ padding: '0.75rem', background: 'var(--surface-hover)', borderRadius: '6px', fontSize: '0.95rem' }}>
                                {selectedSpec}
                            </div>
                        </div>

                        <div style={{ marginBottom: '1.5rem' }}>
                            <label style={{ display: 'block', marginBottom: '0.5rem', color: 'var(--text-secondary)', fontSize: '0.9rem' }}>
                                Browser
                            </label>
                            <div style={{ display: 'flex', gap: '0.75rem' }}>
                                {['chromium', 'firefox', 'webkit'].map(browser => (
                                    <button
                                        key={browser}
                                        onClick={() => setSelectedBrowser(browser)}
                                        style={{
                                            flex: 1,
                                            padding: '0.75rem',
                                            borderRadius: '8px',
                                            border: selectedBrowser === browser ? '2px solid var(--primary)' : '1px solid var(--border)',
                                            background: selectedBrowser === browser ? 'var(--primary-glow)' : 'transparent',
                                            color: selectedBrowser === browser ? 'var(--primary)' : 'var(--text)',
                                            textTransform: 'capitalize',
                                            cursor: 'pointer',
                                            transition: 'all 0.2s var(--ease-smooth)'
                                        }}
                                    >
                                        {browser === 'chromium' ? 'Chrome' : browser === 'webkit' ? 'Safari' : 'Firefox'}
                                    </button>
                                ))}
                            </div>
                        </div>

                        {/* Pipeline Info */}
                        <div style={{
                            marginBottom: '1.5rem',
                            padding: '0.75rem 1rem',
                            background: 'var(--success-muted)',
                            border: '1px solid rgba(52, 211, 153, 0.3)',
                            borderRadius: '8px'
                        }}>
                            <div style={{ fontSize: '0.85rem', color: 'var(--success)', fontWeight: 600, marginBottom: '0.25rem' }}>
                                Intelligent Pipeline
                            </div>
                            <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                                AI-powered browser exploration for reliable test generation.
                            </div>
                        </div>

                        {/* Repair Mode Selection */}
                        <div style={{ marginBottom: '1.5rem' }}>
                            <label style={{ display: 'block', marginBottom: '0.75rem', color: 'var(--text-secondary)', fontSize: '0.9rem' }}>
                                Repair Mode
                            </label>

                            {/* Automated Repair Option */}
                            <div
                                onClick={() => setHybridHealing(false)}
                                style={{
                                    padding: '1rem',
                                    marginBottom: '0.75rem',
                                    borderRadius: '8px',
                                    border: !hybridHealing ? '2px solid var(--primary)' : '1px solid var(--border)',
                                    background: !hybridHealing ? 'rgba(96, 165, 250, 0.06)' : 'var(--surface-hover)',
                                    cursor: 'pointer',
                                    transition: 'all 0.2s var(--ease-smooth)'
                                }}
                            >
                                <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                                    <div style={{
                                        width: 20,
                                        height: 20,
                                        borderRadius: '50%',
                                        border: !hybridHealing ? '6px solid var(--primary)' : '2px solid var(--border)',
                                        background: 'transparent'
                                    }} />
                                    <div>
                                        <div style={{ fontWeight: 600, marginBottom: '0.25rem' }}>
                                            Automated Repair
                                            <span style={{
                                                marginLeft: '0.5rem',
                                                fontSize: '0.7rem',
                                                background: 'var(--primary)',
                                                color: 'white',
                                                padding: '2px 6px',
                                                borderRadius: '4px'
                                            }}>
                                                RECOMMENDED
                                            </span>
                                        </div>
                                        <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                                            3 repair attempts with intelligent debugging. Fast and focused.
                                        </div>
                                    </div>
                                </div>
                            </div>

                            {/* Extended Recovery Option */}
                            <div
                                onClick={() => setHybridHealing(true)}
                                style={{
                                    padding: '1rem',
                                    borderRadius: '8px',
                                    border: hybridHealing ? '2px solid var(--accent)' : '1px solid var(--border)',
                                    background: hybridHealing ? 'rgba(192, 132, 252, 0.06)' : 'var(--surface-hover)',
                                    cursor: 'pointer',
                                    transition: 'all 0.2s var(--ease-smooth)'
                                }}
                            >
                                <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                                    <div style={{
                                        width: 20,
                                        height: 20,
                                        borderRadius: '50%',
                                        border: hybridHealing ? '6px solid var(--accent)' : '2px solid var(--border)',
                                        background: 'transparent'
                                    }} />
                                    <div style={{ flex: 1 }}>
                                        <div style={{ fontWeight: 600, marginBottom: '0.25rem' }}>
                                            Extended Recovery
                                        </div>
                                        <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                                            Standard repair (3) + deep iteration (up to {maxIterations - 3} more). For complex failures.
                                        </div>
                                    </div>
                                </div>

                                {hybridHealing && (
                                    <div style={{ marginTop: '1rem', marginLeft: '2rem' }}>
                                        <div style={{ padding: '0.75rem', background: 'var(--surface)', borderRadius: '6px', fontSize: '0.85rem', marginBottom: '0.75rem' }}>
                                            <div style={{ marginBottom: '0.5rem' }}>
                                                <strong>Phase 1:</strong> Automated Repair (1-3 attempts)
                                            </div>
                                            <div>
                                                <strong>Phase 2:</strong> Extended Recovery (4-{maxIterations} attempts)
                                            </div>
                                        </div>

                                        <label style={{ display: 'block', marginBottom: '0.5rem', fontSize: '0.85rem' }}>
                                            Max Total Iterations: {maxIterations}
                                        </label>
                                        <input
                                            type="range"
                                            min="5"
                                            max="30"
                                            value={maxIterations}
                                            onChange={(e) => setMaxIterations(parseInt(e.target.value))}
                                            onClick={(e) => e.stopPropagation()}
                                            style={{
                                                width: '100%',
                                                accentColor: 'var(--accent)'
                                            }}
                                        />
                                    </div>
                                )}
                            </div>
                        </div>

                        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '1rem' }}>
                            <button
                                className="btn btn-secondary"
                                onClick={() => setRunModalOpen(false)}
                                disabled={isStartingRun}
                            >
                                Cancel
                            </button>
                            <button
                                className="btn btn-primary"
                                onClick={confirmRun}
                                disabled={isStartingRun}
                                style={{
                                    background: hybridHealing ? 'linear-gradient(135deg, var(--primary) 0%, var(--accent) 100%)' : undefined,
                                    opacity: isStartingRun ? 0.7 : 1,
                                    cursor: isStartingRun ? 'not-allowed' : 'pointer'
                                }}
                            >
                                {isStartingRun ? 'Starting...' : (hybridHealing ? 'Start (Extended)' : 'Start Run')}
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {/* Bulk Action Bar - Only show on specs tab */}
            {activeTab === 'specs' && selectedSpecs.size > 0 && (
                <div style={{
                    position: 'fixed',
                    bottom: '2rem',
                    left: '50%',
                    transform: 'translateX(-50%)',
                    background: 'var(--surface)',
                    border: '1px solid var(--primary)',
                    borderRadius: '12px',
                    padding: '1rem 2rem',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '2rem',
                    boxShadow: '0 20px 25px -5px rgba(0, 0, 0, 0.3)',
                    zIndex: 100,
                    animation: 'slideUp 0.3s ease-out'
                }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
                        <span style={{
                            background: 'var(--primary)',
                            color: 'white',
                            padding: '0.2rem 0.6rem',
                            borderRadius: '6px',
                            fontWeight: 700,
                            fontSize: '0.9rem'
                        }}>
                            {selectedSpecs.size}
                        </span>
                        <span style={{ fontWeight: 600 }}>
                            Specs Selected
                            {selectedAutomatedCount > 0 && (
                                <span style={{ color: 'var(--success)', marginLeft: '0.5rem' }}>
                                    ({selectedAutomatedCount} automated)
                                </span>
                            )}
                        </span>
                    </div>

                    <div style={{ height: '24px', width: '1px', background: 'var(--border)' }}></div>

                    <div style={{ display: 'flex', gap: '1rem' }}>
                        <button
                            className="btn btn-secondary"
                            onClick={clearSelection}
                            style={{ padding: '0.5rem 1rem' }}
                        >
                            Clear
                        </button>
                        <button
                            className="btn"
                            onClick={() => setExportModalOpen(true)}
                            style={{
                                background: 'var(--accent)',
                                color: 'white',
                                display: 'flex',
                                alignItems: 'center',
                                gap: '0.5rem'
                            }}
                        >
                            <ArrowDownToLine size={16} />
                            Export ({selectedSpecs.size})
                        </button>
                        {trConfigured && trConfig.project_id && trConfig.suite_id && (
                            <button
                                className="btn"
                                onClick={() => { setPushResult(null); setPushModalOpen(true); }}
                                style={{
                                    background: 'var(--primary)',
                                    color: 'white',
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: '0.5rem'
                                }}
                            >
                                <Upload size={16} />
                                Push to TestRail ({selectedSpecs.size})
                            </button>
                        )}
                        {selectedAutomatedCount > 0 && selectedAutomatedCount < selectedSpecs.size && (
                            <button
                                className="btn"
                                onClick={async () => {
                                    const automatedSpecs = Array.from(selectedSpecs).filter(name => {
                                        const spec = specs.find(s => s.name === name);
                                        return spec?.is_automated;
                                    });
                                    try {
                                        const res = await fetch(`${API_BASE}/runs/bulk`, {
                                            method: 'POST',
                                            headers: { 'Content-Type': 'application/json' },
                                            body: JSON.stringify({
                                                spec_names: automatedSpecs,
                                                browser: selectedBrowser,
                                                hybrid: hybridHealing,
                                                max_iterations: hybridHealing ? maxIterations : undefined,
                                                project_id: currentProject?.id
                                            })
                                        });
                                        const data = await res.json();
                                        if (data.batch_id) {
                                            alert(`Successfully started ${data.count} automated test runs!`);
                                            clearSelection();
                                            router.push(`/regression/batches/${data.batch_id}`);
                                        } else if (data.run_ids) {
                                            alert(`Successfully started ${data.count} automated test runs!`);
                                            clearSelection();
                                            router.push('/runs');
                                        }
                                    } catch (e) {
                                        alert('Failed to start automated tests');
                                    }
                                }}
                                style={{
                                    background: 'var(--success)',
                                    color: 'white',
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: '0.5rem'
                                }}
                            >
                                <CheckCircle size={16} />
                                Run {selectedAutomatedCount} Automated
                            </button>
                        )}
                        <button
                            className="btn btn-primary"
                            onClick={handleBulkRun}
                        >
                            <Play size={16} fill="currentColor" />
                            Run All ({selectedSpecs.size})
                        </button>
                    </div>
                </div>
            )}

            {/* Export Modal */}
            {exportModalOpen && (
                <div className="modal-overlay" onClick={() => setExportModalOpen(false)}>
                    <div className="modal-content" onClick={e => e.stopPropagation()} style={{ width: '420px' }}>
                        <h3 style={{ marginTop: 0, marginBottom: '1.5rem' }}>Export to TestRail</h3>
                        <p style={{ color: 'var(--text-secondary)', marginBottom: '1.5rem', fontSize: '0.9rem' }}>
                            Export {selectedSpecs.size} spec{selectedSpecs.size !== 1 ? 's' : ''} as a TestRail import file.
                        </p>

                        <div style={{ marginBottom: '1.5rem' }}>
                            <label style={{ fontWeight: 600, display: 'block', marginBottom: '0.5rem' }}>Format</label>
                            <div style={{ display: 'flex', gap: '0.5rem' }}>
                                <button
                                    className={`btn ${exportFormat === 'xml' ? 'btn-primary' : 'btn-secondary'}`}
                                    onClick={() => setExportFormat('xml')}
                                    style={{ flex: 1 }}
                                >
                                    XML (Recommended)
                                </button>
                                <button
                                    className={`btn ${exportFormat === 'csv' ? 'btn-primary' : 'btn-secondary'}`}
                                    onClick={() => setExportFormat('csv')}
                                    style={{ flex: 1 }}
                                >
                                    CSV
                                </button>
                            </div>
                            {exportFormat === 'xml' && (
                                <p style={{ color: 'var(--text-secondary)', fontSize: '0.8rem', marginTop: '0.5rem' }}>
                                    Supports hierarchical sections and separated steps natively.
                                </p>
                            )}
                        </div>

                        {exportFormat === 'csv' && (
                            <div style={{ marginBottom: '1.5rem' }}>
                                <label style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', cursor: 'pointer' }}>
                                    <input
                                        type="checkbox"
                                        checked={exportSeparatedSteps}
                                        onChange={e => setExportSeparatedSteps(e.target.checked)}
                                    />
                                    <span>Separated steps (one row per step)</span>
                                </label>
                            </div>
                        )}

                        <div style={{ display: 'flex', gap: '1rem', justifyContent: 'flex-end' }}>
                            <button
                                className="btn btn-secondary"
                                onClick={() => setExportModalOpen(false)}
                            >
                                Cancel
                            </button>
                            <button
                                className="btn"
                                onClick={handleExport}
                                disabled={exporting}
                                style={{
                                    background: 'var(--accent)',
                                    color: 'white',
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: '0.5rem'
                                }}
                            >
                                <ArrowDownToLine size={16} />
                                {exporting ? 'Exporting...' : 'Download'}
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {/* Push to TestRail Modal */}
            {pushModalOpen && (
                <div className="modal-overlay" onClick={() => setPushModalOpen(false)}>
                    <div className="modal-content" onClick={e => e.stopPropagation()} style={{ width: '460px' }}>
                        <h3 style={{ marginTop: 0, marginBottom: '1rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                            <Upload size={20} />
                            Push to TestRail
                        </h3>

                        {!pushResult ? (
                            <>
                                <p style={{ color: 'var(--text-secondary)', marginBottom: '1.5rem', fontSize: '0.9rem' }}>
                                    Push {selectedSpecs.size} spec{selectedSpecs.size !== 1 ? 's' : ''} to TestRail as test cases.
                                    {Array.from(selectedSpecs).some(n => trMappings.has(n)) && (
                                        <span style={{ display: 'block', marginTop: '0.5rem', color: 'var(--primary)' }}>
                                            Specs with existing mappings will be updated.
                                        </span>
                                    )}
                                </p>

                                <div style={{
                                    padding: '1rem',
                                    borderRadius: 'var(--radius)',
                                    background: 'rgba(96, 165, 250, 0.08)',
                                    border: '1px solid rgba(96, 165, 250, 0.15)',
                                    marginBottom: '1.5rem',
                                    fontSize: '0.9rem',
                                }}>
                                    <div><strong>Project ID:</strong> {trConfig.project_id}</div>
                                    <div><strong>Suite ID:</strong> {trConfig.suite_id}</div>
                                </div>

                                <div style={{ display: 'flex', gap: '1rem', justifyContent: 'flex-end' }}>
                                    <button className="btn btn-secondary" onClick={() => setPushModalOpen(false)}>
                                        Cancel
                                    </button>
                                    <button
                                        className="btn"
                                        onClick={handlePushToTestrail}
                                        disabled={pushing}
                                        style={{
                                            background: 'var(--primary)',
                                            color: 'white',
                                            display: 'flex',
                                            alignItems: 'center',
                                            gap: '0.5rem'
                                        }}
                                    >
                                        {pushing ? (
                                            <><Loader2 size={16} style={{ animation: 'spin 1s linear infinite' }} /> Pushing...</>
                                        ) : (
                                            <><Upload size={16} /> Push Cases</>
                                        )}
                                    </button>
                                </div>
                            </>
                        ) : (
                            <>
                                <div style={{ marginBottom: '1.5rem' }}>
                                    <div style={{ display: 'flex', gap: '1.5rem', marginBottom: '1rem' }}>
                                        {pushResult.pushed > 0 && (
                                            <div style={{ textAlign: 'center' }}>
                                                <div style={{ fontSize: '1.5rem', fontWeight: 700, color: 'var(--success)' }}>{pushResult.pushed}</div>
                                                <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Created</div>
                                            </div>
                                        )}
                                        {pushResult.updated > 0 && (
                                            <div style={{ textAlign: 'center' }}>
                                                <div style={{ fontSize: '1.5rem', fontWeight: 700, color: 'var(--primary)' }}>{pushResult.updated}</div>
                                                <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Updated</div>
                                            </div>
                                        )}
                                        {pushResult.failed > 0 && (
                                            <div style={{ textAlign: 'center' }}>
                                                <div style={{ fontSize: '1.5rem', fontWeight: 700, color: 'var(--danger)' }}>{pushResult.failed}</div>
                                                <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>Failed</div>
                                            </div>
                                        )}
                                    </div>
                                    {pushResult.errors.length > 0 && (
                                        <div style={{
                                            padding: '0.75rem',
                                            borderRadius: 'var(--radius)',
                                            background: 'rgba(248, 113, 113, 0.08)',
                                            border: '1px solid rgba(248, 113, 113, 0.15)',
                                            fontSize: '0.85rem',
                                            maxHeight: '120px',
                                            overflow: 'auto',
                                        }}>
                                            {pushResult.errors.map((err, i) => (
                                                <div key={i} style={{ color: 'var(--danger)', marginBottom: '0.25rem' }}>{err}</div>
                                            ))}
                                        </div>
                                    )}
                                </div>
                                <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
                                    <button className="btn btn-primary" onClick={() => setPushModalOpen(false)}>
                                        Done
                                    </button>
                                </div>
                            </>
                        )}
                    </div>
                </div>
            )}

            <style jsx>{`
                @keyframes slideUp {
                    from { transform: translate(-50%, 100%); opacity: 0; }
                    to { transform: translate(-50%, 0); opacity: 1; }
                }
                @keyframes slideDown {
                    from { opacity: 0; transform: translateY(-10px); }
                    to { opacity: 1; transform: translateY(0); }
                }
                @keyframes spin {
                    from { transform: rotate(0deg); }
                    to { transform: rotate(360deg); }
                }
                .modal-overlay {
                    position: fixed;
                    top: 0; left: 0; right: 0; bottom: 0;
                    background: rgba(0,0,0,0.5);
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    z-index: 1000;
                    backdrop-filter: blur(2px);
                }
                .modal-content {
                    background: var(--surface);
                    padding: 2rem;
                    border-radius: 12px;
                    border: 1px solid var(--border);
                    box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.1), 0 10px 10px -5px rgba(0, 0, 0, 0.04);
                }
            `}</style>
        </PageLayout>
    );
}
