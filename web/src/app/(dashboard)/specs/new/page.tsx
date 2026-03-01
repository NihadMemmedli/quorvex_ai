'use client';
import { useState, useEffect, Suspense, useRef } from 'react';
import { ArrowLeft, Save, Link as LinkIcon, AlertCircle, Search, X, ChevronDown } from 'lucide-react';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import TagEditor from '@/components/TagEditor';
import SpecBuilder from '@/components/SpecBuilder';
import { useProject } from '@/contexts/ProjectContext';
import { API_BASE } from '@/lib/api';
import { PageLayout } from '@/components/ui/page-layout';
import { PageHeader } from '@/components/ui/page-header';
import { FormPageSkeleton } from '@/components/ui/page-skeleton';

interface Requirement {
    id: number;
    req_code: string;
    title: string;
    description: string | null;
    category: string;
    priority: string;
    status: string;
    acceptance_criteria: string[];
}

function NewSpecPageContent() {
    const router = useRouter();
    const searchParams = useSearchParams();
    const { currentProject } = useProject();

    // Read requirement context from URL params
    const requirementId = searchParams.get('requirement_id');
    const requirementCode = searchParams.get('requirement_code');

    const [name, setName] = useState('');
    const [content, setContent] = useState('');
    const [tags, setTags] = useState<string[]>([]);
    const [allTags, setAllTags] = useState<string[]>([]);
    const [loading, setLoading] = useState(false);
    const [mode, setMode] = useState<'code' | 'visual'>('visual');

    // Requirement state
    const [requirement, setRequirement] = useState<Requirement | null>(null);
    const [loadingRequirement, setLoadingRequirement] = useState(false);

    // Requirements list for selector
    const [requirements, setRequirements] = useState<Requirement[]>([]);
    const [loadingRequirements, setLoadingRequirements] = useState(false);
    const [requirementSearch, setRequirementSearch] = useState('');
    const [showRequirementDropdown, setShowRequirementDropdown] = useState(false);
    const dropdownRef = useRef<HTMLDivElement>(null);

    // Build template from requirement
    const buildTemplateFromRequirement = (req: Requirement) => {
        const acceptanceCriteriaSteps = req.acceptance_criteria
            .map((ac, i) => `${i + 3}. Verify: ${ac}`)
            .join('\n');

        return `# Test: ${req.req_code} - ${req.title}

## Description
${req.description || 'Tests the functionality described in requirement ' + req.req_code}

## Requirement
- **Code:** ${req.req_code}
- **Category:** ${req.category}
- **Priority:** ${req.priority}

## Steps
1. Navigate to [URL]
2. [Initial setup/precondition]
${acceptanceCriteriaSteps || '3. [Action]\n4. [Assertion]'}

## Expected Outcome
${req.acceptance_criteria.map(ac => `- ${ac}`).join('\n') || '- [Expected result]'}
`;
    };

    // Default template (when no requirement)
    const defaultTemplate = `# Test: [Name]

## Description
[Description of what the test does]

## Steps
1. Navigate to [URL]
2. [Action]
3. [Assertion]

## Expected Outcome
- [Expected result]
`;

    // Fetch requirement data if requirement_id is provided
    useEffect(() => {
        if (requirementId) {
            setLoadingRequirement(true);
            const projectParam = currentProject?.id
                ? `?project_id=${encodeURIComponent(currentProject.id)}`
                : '';

            fetch(`${API_BASE}/requirements/${requirementId}${projectParam}`)
                .then(res => {
                    if (res.ok) return res.json();
                    throw new Error('Requirement not found');
                })
                .then((req: Requirement) => {
                    setRequirement(req);
                    // Pre-fill content from requirement
                    setContent(buildTemplateFromRequirement(req));
                    // Auto-generate filename
                    const slug = req.title.toLowerCase()
                        .replace(/[^a-z0-9]+/g, '-')
                        .replace(/(^-|-$)/g, '')
                        .substring(0, 50);
                    setName(`${req.req_code.toLowerCase()}-${slug}.md`);
                    // Add requirement-related tags
                    setTags([req.category, req.priority].filter(Boolean));
                })
                .catch(err => {
                    console.error('Failed to load requirement:', err);
                    // Fall back to default template
                    setContent(defaultTemplate);
                })
                .finally(() => setLoadingRequirement(false));
        } else {
            setContent(defaultTemplate);
        }

        // Fetch all existing tags for autocomplete
        fetch(`${API_BASE}/spec-metadata`)
            .then(res => res.json())
            .then(metadata => {
                const tagsSet = new Set<string>();
                Object.values(metadata).forEach((meta: any) => {
                    meta.tags?.forEach((tag: string) => tagsSet.add(tag));
                });
                setAllTags(Array.from(tagsSet).sort());
            })
            .catch(err => console.error('Failed to load tags:', err));
    }, [requirementId, currentProject?.id]);

    // Fetch requirements filtered by current project
    useEffect(() => {
        if (!currentProject?.id) return;

        console.log('[NewSpec] Fetching requirements for project:', currentProject.id);
        setLoadingRequirements(true);

        const projectParam = `?project_id=${encodeURIComponent(currentProject.id)}&limit=200`;
        fetch(`${API_BASE}/requirements${projectParam}`)
            .then(res => {
                console.log('[NewSpec] Response status:', res.status);
                return res.json();
            })
            .then(data => {
                console.log('[NewSpec] Data received:', data);
                // Handle paginated response - ensure we always get an array
                const reqs = data.items || data || [];
                console.log('[NewSpec] Requirements count:', reqs.length);
                setRequirements(Array.isArray(reqs) ? reqs : []);
            })
            .catch(err => {
                console.error('[NewSpec] Failed to load requirements:', err);
                setRequirements([]);
            })
            .finally(() => setLoadingRequirements(false));
    }, [currentProject?.id]);

    // Click outside handler to close dropdown
    useEffect(() => {
        const handleClickOutside = (event: MouseEvent) => {
            if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
                setShowRequirementDropdown(false);
            }
        };
        document.addEventListener('mousedown', handleClickOutside);
        return () => document.removeEventListener('mousedown', handleClickOutside);
    }, []);

    // Filter requirements based on search (with array guard)
    console.log('[NewSpec Render] requirements.length:', requirements.length, 'isArray:', Array.isArray(requirements));
    const filteredRequirements = Array.isArray(requirements) ? requirements.filter(req => {
        const searchLower = requirementSearch.toLowerCase();
        return req.req_code?.toLowerCase().includes(searchLower) ||
               req.title?.toLowerCase().includes(searchLower) ||
               req.category?.toLowerCase().includes(searchLower);
    }) : [];
    console.log('[NewSpec Render] filteredRequirements.length:', filteredRequirements.length);

    // Handle selecting a requirement from the dropdown
    const handleSelectRequirement = (req: Requirement) => {
        setRequirement(req);
        setShowRequirementDropdown(false);
        setRequirementSearch('');

        // Pre-fill content from requirement
        setContent(buildTemplateFromRequirement(req));

        // Auto-generate filename
        const slug = req.title.toLowerCase()
            .replace(/[^a-z0-9]+/g, '-')
            .replace(/(^-|-$)/g, '')
            .substring(0, 50);
        setName(`${req.req_code.toLowerCase()}-${slug}.md`);

        // Add requirement-related tags
        setTags([req.category, req.priority].filter(Boolean));
    };

    // Handle clearing the linked requirement
    const handleClearRequirement = () => {
        setRequirement(null);
        setContent(defaultTemplate);
        setName('');
        setTags([]);
    };

    const handleSave = async () => {
        if (!name || !content) {
            alert('Please fill in name and content');
            return;
        }

        setLoading(true);
        try {
            const res = await fetch(`${API_BASE}/specs`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name, content, project_id: currentProject?.id })
            });

            if (res.ok) {
                // Save tags if any
                if (tags.length > 0) {
                    await fetch(`${API_BASE}/spec-metadata/${name}`, {
                        method: 'PUT',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ tags })
                    });
                }

                // Create RTM entry if linked to a requirement (from URL or dropdown selection)
                if (requirement) {
                    const projectParam = currentProject?.id
                        ? `?project_id=${encodeURIComponent(currentProject.id)}`
                        : '';

                    try {
                        await fetch(`${API_BASE}/rtm/entry${projectParam}`, {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({
                                requirement_id: requirement.id,
                                test_spec_name: name,
                                test_spec_path: `specs/${name}`,
                                mapping_type: 'full',
                                confidence: 1.0,
                                coverage_notes: `Manually created from requirement ${requirement.req_code}`
                            })
                        });
                    } catch (rtmErr) {
                        console.error('Failed to create RTM entry:', rtmErr);
                        // Don't block navigation if RTM entry fails
                    }
                }

                router.push('/specs');
            } else {
                alert('Failed to save spec');
            }
        } catch (e) {
            console.error(e);
            alert('Error saving spec');
        } finally {
            setLoading(false);
        }
    };

    return (
        <PageLayout tier="narrow">
            <PageHeader
                title="New Test Spec"
                breadcrumb={
                    <Link href="/specs" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', color: 'var(--text-secondary)' }}>
                        <ArrowLeft size={16} /> Back to Specs
                    </Link>
                }
                actions={
                    <div style={{ display: 'flex', gap: '1rem', alignItems: 'center' }}>
                        <div style={{ background: 'var(--surface)', borderRadius: 'var(--radius)', padding: '4px', display: 'flex', border: '1px solid var(--border)' }}>
                            <button
                                onClick={() => setMode('code')}
                                style={{
                                    padding: '4px 12px',
                                    background: mode === 'code' ? 'var(--primary)' : 'transparent',
                                    color: mode === 'code' ? 'white' : 'var(--text-secondary)',
                                    borderRadius: '4px',
                                    border: 'none',
                                    fontSize: '0.8rem',
                                    cursor: 'pointer'
                                }}
                            >
                                Code
                            </button>
                            <button
                                onClick={() => setMode('visual')}
                                style={{
                                    padding: '4px 12px',
                                    background: mode === 'visual' ? 'var(--primary)' : 'transparent',
                                    color: mode === 'visual' ? 'white' : 'var(--text-secondary)',
                                    borderRadius: '4px',
                                    border: 'none',
                                    fontSize: '0.8rem',
                                    cursor: 'pointer'
                                }}
                            >
                                Visual
                            </button>
                        </div>
                        <button className="btn btn-primary" onClick={handleSave} disabled={loading || loadingRequirement}>
                            <Save size={18} />
                            {loading ? 'Saving...' : 'Save Spec'}
                        </button>
                    </div>
                }
            />

            {/* Linked Requirement Banner */}
            {requirement && (
                <div style={{
                    padding: '1rem',
                    background: 'var(--primary-glow)',
                    border: '1px solid rgba(59, 130, 246, 0.3)',
                    borderRadius: '8px',
                    marginBottom: '1.5rem',
                    display: 'flex',
                    alignItems: 'flex-start',
                    gap: '0.75rem'
                }}>
                    <LinkIcon size={20} color="var(--primary)" style={{ flexShrink: 0, marginTop: '2px' }} />
                    <div style={{ flex: 1 }}>
                        <div style={{ fontWeight: 600, marginBottom: '0.25rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                            Linked to Requirement
                            <span style={{
                                padding: '0.125rem 0.5rem',
                                background: 'var(--primary)',
                                color: 'white',
                                borderRadius: '4px',
                                fontSize: '0.75rem',
                                fontWeight: 600
                            }}>
                                {requirement.req_code}
                            </span>
                        </div>
                        <div style={{ fontSize: '0.9rem', color: 'var(--text-secondary)' }}>
                            {requirement.title}
                        </div>
                        <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginTop: '0.5rem' }}>
                            An RTM entry will be created automatically when you save this spec.
                        </div>
                    </div>
                </div>
            )}

            {loadingRequirement && (
                <div style={{
                    padding: '1rem',
                    background: 'var(--surface-hover)',
                    borderRadius: '8px',
                    marginBottom: '1.5rem',
                    textAlign: 'center',
                    color: 'var(--text-secondary)'
                }}>
                    Loading requirement details...
                </div>
            )}

            <div className="animate-in stagger-2" style={{ display: 'grid', gap: '2rem', maxWidth: '800px' }}>
                <div className="card">
                    <label style={{ display: 'block', marginBottom: '0.75rem', fontWeight: 600, fontSize: '0.95rem', color: 'var(--text)' }}>Filename (e.g. login.md)</label>
                    <input
                        type="text"
                        value={name}
                        onChange={e => setName(e.target.value)}
                        placeholder="my-test.md"
                        style={{
                            width: '100%', padding: '0.75rem',
                            background: 'rgba(0,0,0,0.2)',
                            border: '1px solid var(--border)',
                            borderRadius: 'var(--radius)',
                            color: 'white',
                            fontSize: '1rem',
                            transition: 'border-color 0.2s ease'
                        }}
                        onFocus={(e) => e.target.style.borderColor = 'var(--primary)'}
                        onBlur={(e) => e.target.style.borderColor = 'var(--border)'}
                    />
                </div>

                {/* Requirement Selector - only show if not already linked via URL */}
                {!requirementId && (
                    <div className="card" style={{ position: 'relative', zIndex: 10 }}>
                        <label style={{ display: 'block', marginBottom: '0.75rem', fontWeight: 600, fontSize: '0.95rem', color: 'var(--text)' }}>
                            Link to Requirement (optional)
                        </label>

                        {requirement ? (
                            // Show selected requirement with clear button
                            <div style={{
                                display: 'flex',
                                alignItems: 'center',
                                gap: '0.75rem',
                                padding: '0.75rem',
                                background: 'var(--primary-glow)',
                                border: '1px solid rgba(59, 130, 246, 0.3)',
                                borderRadius: 'var(--radius)'
                            }}>
                                <LinkIcon size={18} color="var(--primary)" />
                                <div style={{ flex: 1 }}>
                                    <span style={{
                                        padding: '0.125rem 0.5rem',
                                        background: 'var(--primary)',
                                        color: 'white',
                                        borderRadius: '4px',
                                        fontSize: '0.75rem',
                                        fontWeight: 600,
                                        marginRight: '0.5rem'
                                    }}>
                                        {requirement.req_code}
                                    </span>
                                    <span style={{ color: 'var(--text)' }}>{requirement.title}</span>
                                </div>
                                <button
                                    onClick={handleClearRequirement}
                                    style={{
                                        background: 'none',
                                        border: 'none',
                                        cursor: 'pointer',
                                        padding: '4px',
                                        borderRadius: '4px',
                                        color: 'var(--text-secondary)',
                                        display: 'flex',
                                        alignItems: 'center'
                                    }}
                                    title="Clear linked requirement"
                                >
                                    <X size={18} />
                                </button>
                            </div>
                        ) : (
                            // Show searchable dropdown
                            <div ref={dropdownRef} style={{ position: 'relative' }}>
                                <div style={{
                                    display: 'flex',
                                    alignItems: 'center',
                                    background: 'rgba(0,0,0,0.2)',
                                    border: '1px solid var(--border)',
                                    borderRadius: 'var(--radius)',
                                    transition: 'border-color 0.2s ease'
                                }}>
                                    <Search size={18} style={{ marginLeft: '0.75rem', color: 'var(--text-secondary)' }} />
                                    <input
                                        type="text"
                                        value={requirementSearch}
                                        onChange={e => {
                                            setRequirementSearch(e.target.value);
                                            setShowRequirementDropdown(true);
                                        }}
                                        onFocus={() => setShowRequirementDropdown(true)}
                                        placeholder="Search requirements by code, title, or category..."
                                        style={{
                                            flex: 1,
                                            padding: '0.75rem',
                                            background: 'transparent',
                                            border: 'none',
                                            color: 'white',
                                            fontSize: '1rem',
                                            outline: 'none'
                                        }}
                                    />
                                    <ChevronDown
                                        size={18}
                                        style={{
                                            marginRight: '0.75rem',
                                            color: 'var(--text-secondary)',
                                            cursor: 'pointer',
                                            transform: showRequirementDropdown ? 'rotate(180deg)' : 'none',
                                            transition: 'transform 0.2s ease'
                                        }}
                                        onClick={() => setShowRequirementDropdown(!showRequirementDropdown)}
                                    />
                                </div>

                                {/* Dropdown list */}
                                {showRequirementDropdown && (
                                    <div style={{
                                        position: 'absolute',
                                        top: '100%',
                                        left: 0,
                                        right: 0,
                                        marginTop: '4px',
                                        background: 'var(--surface)',
                                        border: '1px solid var(--border)',
                                        borderRadius: 'var(--radius)',
                                        maxHeight: '300px',
                                        overflowY: 'auto',
                                        zIndex: 1000,
                                        boxShadow: '0 4px 12px rgba(0,0,0,0.3)'
                                    }}>
                                        {loadingRequirements ? (
                                            <div style={{ padding: '1rem', textAlign: 'center', color: 'var(--text-secondary)' }}>
                                                Loading requirements...
                                            </div>
                                        ) : filteredRequirements.length === 0 ? (
                                            <div style={{ padding: '1rem', textAlign: 'center', color: 'var(--text-secondary)' }}>
                                                {requirements.length === 0
                                                    ? 'No requirements found. Create requirements first.'
                                                    : 'No matching requirements found.'}
                                            </div>
                                        ) : (
                                            filteredRequirements.slice(0, 50).map(req => (
                                                <div
                                                    key={req.id}
                                                    onClick={() => handleSelectRequirement(req)}
                                                    style={{
                                                        padding: '0.75rem 1rem',
                                                        cursor: 'pointer',
                                                        borderBottom: '1px solid var(--border)',
                                                        transition: 'background 0.15s ease'
                                                    }}
                                                    onMouseEnter={e => (e.currentTarget.style.background = 'var(--surface-hover)')}
                                                    onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
                                                >
                                                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.25rem' }}>
                                                        <span style={{
                                                            padding: '0.125rem 0.5rem',
                                                            background: 'var(--primary)',
                                                            color: 'white',
                                                            borderRadius: '4px',
                                                            fontSize: '0.7rem',
                                                            fontWeight: 600
                                                        }}>
                                                            {req.req_code}
                                                        </span>
                                                        <span style={{
                                                            padding: '0.125rem 0.375rem',
                                                            background: req.priority === 'Critical' ? 'var(--danger-muted)' :
                                                                       req.priority === 'High' ? 'var(--warning-muted)' :
                                                                       req.priority === 'Medium' ? 'var(--warning-muted)' :
                                                                       'var(--success-muted)',
                                                            color: req.priority === 'Critical' ? 'var(--danger)' :
                                                                   req.priority === 'High' ? 'var(--warning)' :
                                                                   req.priority === 'Medium' ? 'var(--warning)' :
                                                                   'var(--success)',
                                                            borderRadius: '4px',
                                                            fontSize: '0.65rem',
                                                            fontWeight: 500
                                                        }}>
                                                            {req.priority}
                                                        </span>
                                                        <span style={{
                                                            padding: '0.125rem 0.375rem',
                                                            background: 'rgba(78, 85, 120, 0.2)',
                                                            color: 'var(--text-secondary)',
                                                            borderRadius: '4px',
                                                            fontSize: '0.65rem',
                                                            fontWeight: 500
                                                        }}>
                                                            {req.category}
                                                        </span>
                                                    </div>
                                                    <div style={{ fontSize: '0.9rem', color: 'var(--text)' }}>
                                                        {req.title}
                                                    </div>
                                                </div>
                                            ))
                                        )}
                                        {filteredRequirements.length > 50 && (
                                            <div style={{ padding: '0.75rem 1rem', textAlign: 'center', color: 'var(--text-secondary)', fontSize: '0.85rem' }}>
                                                Showing 50 of {filteredRequirements.length} results. Type to narrow down.
                                            </div>
                                        )}
                                    </div>
                                )}
                            </div>
                        )}
                    </div>
                )}

                <div className="card">
                    <label style={{ display: 'block', marginBottom: '0.75rem', fontWeight: 600, fontSize: '0.95rem', color: 'var(--text)' }}>Tags</label>
                    <TagEditor
                        tags={tags}
                        onTagsChange={setTags}
                        allTags={allTags}
                        placeholder="Add tags (smoke, p0, auth...)"
                    />
                </div>

                <div className="card" style={{ height: 'calc(100vh - 450px)', display: 'flex', flexDirection: 'column', padding: 0, overflow: 'hidden' }}>
                    <div style={{ padding: '1rem', borderBottom: '1px solid var(--border)', fontWeight: 600, fontSize: '0.95rem', color: 'var(--text)' }}>
                        Content
                    </div>
                    <div style={{ flex: 1, overflow: 'auto', background: 'var(--code-bg)' }}>
                        {mode === 'visual' ? (
                            <SpecBuilder content={content} onChange={setContent} />
                        ) : (
                            <textarea
                                value={content}
                                onChange={e => setContent(e.target.value)}
                                style={{
                                    width: '100%', height: '100%', padding: '1rem',
                                    background: 'transparent',
                                    border: 'none',
                                    color: 'white',
                                    fontFamily: 'monospace',
                                    fontSize: '0.95rem',
                                    lineHeight: '1.6',
                                    resize: 'none',
                                    outline: 'none'
                                }}
                            />
                        )}
                    </div>
                </div>
            </div>
        </PageLayout>
    );
}

// Wrap with Suspense for useSearchParams
export default function NewSpecPage() {
    return (
        <Suspense fallback={
            <PageLayout tier="narrow">
                <FormPageSkeleton fields={4} />
            </PageLayout>
        }>
            <NewSpecPageContent />
        </Suspense>
    );
}
