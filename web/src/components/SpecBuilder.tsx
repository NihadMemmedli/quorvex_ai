'use client';

import { useState, useEffect } from 'react';
import { Plus, Trash2, ArrowUp, ArrowDown, MousePointer, Type, Globe, CheckCircle, HelpCircle, LayoutTemplate, Lock, Search } from 'lucide-react';
import { useProject } from '@/contexts/ProjectContext';
import { API_BASE } from '@/lib/api';

interface SpecStep {
    id: string;
    type: 'navigate' | 'click' | 'fill' | 'assert' | 'custom' | 'include';
    description: string;
}

interface SpecBuilderProps {
    content: string;
    onChange: (newContent: string) => void;
}

interface TemplateSpec {
    name: string;
    is_automated?: boolean;
    metadata?: { tags: string[] };
}

export default function SpecBuilder({ content, onChange }: SpecBuilderProps) {
    const { currentProject } = useProject();
    const [title, setTitle] = useState('');
    const [description, setDescription] = useState('');
    const [steps, setSteps] = useState<SpecStep[]>([]);

    // Templates state
    const [templates, setTemplates] = useState<TemplateSpec[]>([]);
    const [templateModalOpen, setTemplateModalOpen] = useState(false);
    const [templateSearch, setTemplateSearch] = useState('');

    // Parse content on mount or when switching to visual mode
    useEffect(() => {
        parseContent(content);
    }, []);

    // Fetch templates when project changes
    useEffect(() => {
        fetchTemplates();
    }, [currentProject?.id]);

    const fetchTemplates = async () => {
        try {
            const projectParam = currentProject?.id
                ? `?project_id=${encodeURIComponent(currentProject.id)}`
                : '';
            const res = await fetch(`${API_BASE}/specs/list${projectParam}`);
            const data = await res.json();
            // Filter only templates — handle both paginated and legacy response shapes
            const specsList = data.items || data;
            setTemplates(specsList.filter((s: any) => s.name.startsWith('templates/')));
        } catch (e) {
            console.error("Failed to fetch templates", e);
        }
    };

    const parseContent = (md: string = '') => {
        if (!md) md = '';
        const lines = md.split('\n');
        let parsedTitle = '';
        let parsedDesc = [];
        let parsedSteps: SpecStep[] = [];
        let isStepsStart = false;

        for (const line of lines) {
            const trimmed = line.trim();
            if (!trimmed) continue;

            if (trimmed.startsWith('# ')) {
                parsedTitle = trimmed.replace('# ', '').trim();
            } else if (trimmed.startsWith('Test:')) {
                // Support legacy format
                parsedTitle = trimmed.replace('Test:', '').trim();
            } else if (/^\d+\./.test(trimmed)) {
                isStepsStart = true;
                // Parse step
                const text = trimmed.replace(/^\d+\.\s*/, '');
                parsedSteps.push({
                    id: Math.random().toString(36).substr(2, 9),
                    type: inferType(text),
                    description: text
                });
            } else if (!isStepsStart) {
                parsedDesc.push(trimmed);
            }
        }

        setTitle(parsedTitle);
        setDescription(parsedDesc.join('\n'));
        setSteps(parsedSteps);
    };

    const inferType = (text: string): SpecStep['type'] => {
        const lower = text.toLowerCase();
        if (lower.startsWith('@include')) return 'include';
        if (lower.includes('go to') || lower.includes('navigate') || lower.includes('open')) return 'navigate';
        if (lower.includes('click') || lower.includes('press') || lower.includes('select')) return 'click';
        if (lower.includes('type') || lower.includes('fill') || lower.includes('enter')) return 'fill';
        if (lower.includes('assert') || lower.includes('verify') || lower.includes('check')) return 'assert';
        return 'custom';
    };

    const serialize = (currentTitle: string, currentDesc: string, currentSteps: SpecStep[]) => {
        let md = '';
        if (currentTitle) md += `# ${currentTitle}\n\n`;
        if (currentDesc) md += `${currentDesc}\n\n`;

        currentSteps.forEach((step, index) => {
            md += `${index + 1}. ${step.description}\n`;
        });

        return md;
    };

    const update = (newTitle: string, newDesc: string, newSteps: SpecStep[]) => {
        setTitle(newTitle);
        setDescription(newDesc);
        setSteps(newSteps);
        onChange(serialize(newTitle, newDesc, newSteps));
    };

    const addStep = () => {
        const newStep: SpecStep = {
            id: Math.random().toString(36).substr(2, 9),
            type: 'custom',
            description: ''
        };
        const newSteps: SpecStep[] = [...steps, newStep];
        update(title, description, newSteps);
    };

    const insertTemplate = (templateName: string) => {
        const newStep: SpecStep = {
            id: Math.random().toString(36).substr(2, 9),
            type: 'include',
            description: `@include "${templateName}"`
        };
        const newSteps: SpecStep[] = [...steps, newStep];
        update(title, description, newSteps);
        setTemplateModalOpen(false);
    };

    const removeStep = (index: number) => {
        const newSteps = steps.filter((_, i) => i !== index);
        update(title, description, newSteps);
    };

    const updateStep = (index: number, val: string) => {
        const newSteps = [...steps];
        newSteps[index].description = val;
        newSteps[index].type = inferType(val);
        update(title, description, newSteps);
    };

    const moveStep = (index: number, direction: 'up' | 'down') => {
        if (direction === 'up' && index === 0) return;
        if (direction === 'down' && index === steps.length - 1) return;

        const newSteps = [...steps];
        const swapIndex = direction === 'up' ? index - 1 : index + 1;
        [newSteps[index], newSteps[swapIndex]] = [newSteps[swapIndex], newSteps[index]];
        update(title, description, newSteps);
    };

    const getIcon = (type: SpecStep['type']) => {
        switch (type) {
            case 'navigate': return <Globe size={16} className="text-blue-400" />;
            case 'click': return <MousePointer size={16} className="text-green-400" />;
            case 'fill': return <Type size={16} className="text-yellow-400" />;
            case 'assert': return <CheckCircle size={16} className="text-purple-400" />;
            case 'include': return <LayoutTemplate size={16} className="text-cyan-400" />;
            default: return <HelpCircle size={16} className="text-gray-400" />;
        }
    };

    return (
        <div style={{ padding: '2rem', maxWidth: '800px', margin: '0 auto', color: '#e6edf3' }}>
            <div style={{ marginBottom: '2rem' }}>
                <label style={{ display: 'block', fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: '0.5rem' }}>
                    Test Name
                </label>
                <input
                    type="text"
                    value={title}
                    onChange={(e) => update(e.target.value, description, steps)}
                    placeholder="e.g. User Login Flow"
                    style={{
                        width: '100%',
                        padding: '0.75rem',
                        background: 'var(--surface)',
                        border: '1px solid var(--border)',
                        borderRadius: 'var(--radius)',
                        color: 'white',
                        fontSize: '1.2rem',
                        fontWeight: 600
                    }}
                />
            </div>

            <div style={{ marginBottom: '2rem' }}>
                <label style={{ display: 'block', fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: '0.5rem' }}>
                    Description
                </label>
                <textarea
                    value={description}
                    onChange={(e) => update(title, e.target.value, steps)}
                    placeholder="Describe what this test does..."
                    style={{
                        width: '100%',
                        padding: '0.75rem',
                        background: 'var(--surface)',
                        border: '1px solid var(--border)',
                        borderRadius: 'var(--radius)',
                        color: '#e6edf3',
                        minHeight: '80px',
                        fontSize: '0.9rem'
                    }}
                />
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <h3 style={{ fontSize: '1.1rem', fontWeight: 600 }}>Test Steps</h3>
                </div>

                {steps.map((step, index) => (
                    <div key={step.id} style={{
                        display: 'flex',
                        alignItems: 'flex-start',
                        gap: '1rem',
                        padding: '1rem',
                        background: step.type === 'include' ? 'rgba(6, 182, 212, 0.05)' : 'var(--surface)',
                        border: step.type === 'include' ? '1px solid rgba(6, 182, 212, 0.2)' : '1px solid var(--border)',
                        borderRadius: 'var(--radius)',
                        transition: 'border-color 0.2s'
                    }}>
                        <div style={{
                            width: '24px',
                            height: '24px',
                            borderRadius: '50%',
                            background: 'rgba(255,255,255,0.1)',
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            fontSize: '0.8rem',
                            fontWeight: 600,
                            marginTop: '0.5rem'
                        }}>
                            {index + 1}
                        </div>

                        <div style={{ flex: 1 }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.5rem' }}>
                                {getIcon(step.type)}
                                <span style={{
                                    textTransform: 'uppercase',
                                    fontSize: '0.7rem',
                                    letterSpacing: '0.05em',
                                    color: step.type === 'include' ? 'var(--cyan-400)' : 'var(--text-secondary)',
                                    fontWeight: 600
                                }}>
                                    {step.type === 'include' ? 'Template Include' : step.type}
                                </span>
                            </div>
                            <input
                                type="text"
                                value={step.description}
                                onChange={(e) => updateStep(index, e.target.value)}
                                placeholder="Describe the step..."
                                style={{
                                    width: '100%',
                                    background: 'transparent',
                                    border: 'none',
                                    color: 'white',
                                    fontSize: '1rem',
                                    outline: 'none',
                                    fontFamily: step.type === 'include' ? 'monospace' : 'inherit'
                                }}
                            />
                        </div>

                        <div style={{ display: 'flex', gap: '0.25rem' }}>
                            <button onClick={() => moveStep(index, 'up')} className="btn-icon" title="Move Up" disabled={index === 0}>
                                <ArrowUp size={14} />
                            </button>
                            <button onClick={() => moveStep(index, 'down')} className="btn-icon" title="Move Down" disabled={index === steps.length - 1}>
                                <ArrowDown size={14} />
                            </button>
                            <button onClick={() => removeStep(index)} className="btn-icon" title="Delete Step" style={{ color: 'var(--danger)' }}>
                                <Trash2 size={14} />
                            </button>
                        </div>
                    </div>
                ))}

                <div style={{ display: 'flex', gap: '1rem' }}>
                    <button
                        onClick={addStep}
                        className="btn btn-secondary"
                        style={{
                            flex: 1,
                            borderStyle: 'dashed',
                            justifyContent: 'center',
                            marginTop: '0.5rem',
                            color: 'var(--text-secondary)'
                        }}
                    >
                        <Plus size={16} /> Add Step
                    </button>

                    <button
                        onClick={() => setTemplateModalOpen(true)}
                        className="btn btn-secondary"
                        style={{
                            flex: 1,
                            borderStyle: 'dashed',
                            justifyContent: 'center',
                            marginTop: '0.5rem',
                            color: 'var(--text-secondary)',
                            background: 'rgba(59, 130, 246, 0.05)',
                            borderColor: 'rgba(59, 130, 246, 0.2)'
                        }}
                    >
                        <LayoutTemplate size={16} className="text-blue-400" /> Insert Template
                    </button>
                </div>
            </div>

            {/* Template Selection Modal */}
            {templateModalOpen && (
                <div style={{
                    position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
                    background: 'rgba(0,0,0,0.7)', zIndex: 1000,
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    backdropFilter: 'blur(4px)'
                }} onClick={() => setTemplateModalOpen(false)}>
                    <div style={{
                        background: 'var(--surface)', width: '500px', maxHeight: '80vh',
                        borderRadius: '12px', border: '1px solid var(--border)',
                        display: 'flex', flexDirection: 'column',
                        boxShadow: '0 25px 50px -12px rgba(0, 0, 0, 0.5)'
                    }} onClick={e => e.stopPropagation()}>
                        <div style={{ padding: '1.5rem', borderBottom: '1px solid var(--border)' }}>
                            <h3 style={{ fontSize: '1.25rem', fontWeight: 600, marginBottom: '0.5rem' }}>Select Template</h3>
                            <div className="input-group">
                                <div className="input-icon"><Search size={16} /></div>
                                <input
                                    type="text"
                                    placeholder="Search templates..."
                                    value={templateSearch}
                                    onChange={e => setTemplateSearch(e.target.value)}
                                    className="input has-icon"
                                    autoFocus
                                />
                            </div>
                        </div>

                        <div style={{ overflowY: 'auto', padding: '0.5rem', maxHeight: '400px' }}>
                            {templates.length === 0 ? (
                                <div style={{ padding: '2rem', textAlign: 'center', color: 'var(--text-secondary)' }}>
                                    No templates found in specs/templates/
                                </div>
                            ) : (
                                templates
                                    .filter(t => t.name.toLowerCase().includes(templateSearch.toLowerCase()))
                                    .map(t => {
                                        const isAutomated = t.is_automated;
                                        return (
                                            <button
                                                key={t.name}
                                                disabled={!isAutomated}
                                                onClick={() => isAutomated && insertTemplate(t.name)}
                                                style={{
                                                    width: '100%',
                                                    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                                                    padding: '1rem',
                                                    background: 'transparent',
                                                    border: 'none',
                                                    borderRadius: '6px',
                                                    cursor: isAutomated ? 'pointer' : 'not-allowed',
                                                    textAlign: 'left',
                                                    opacity: isAutomated ? 1 : 0.6
                                                }}
                                                className="hover-bg-surface-hover"
                                            >
                                                <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
                                                    <div style={{
                                                        width: 32, height: 32,
                                                        background: 'rgba(6, 182, 212, 0.1)',
                                                        color: 'var(--cyan-400)',
                                                        borderRadius: '6px',
                                                        display: 'flex', alignItems: 'center', justifyContent: 'center'
                                                    }}>
                                                        <LayoutTemplate size={16} />
                                                    </div>
                                                    <div>
                                                        <div style={{ fontWeight: 500, color: 'var(--text)', marginBottom: '0.25rem' }}>
                                                            {t.name}
                                                        </div>
                                                        <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                                                            {t.metadata?.tags?.join(', ') || 'No tags'}
                                                        </div>
                                                    </div>
                                                </div>

                                                {isAutomated ? (
                                                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.25rem', color: 'var(--success)', fontSize: '0.8rem', fontWeight: 600 }}>
                                                        <CheckCircle size={14} /> Ready
                                                    </div>
                                                ) : (
                                                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.25rem', color: 'var(--text-secondary)', fontSize: '0.8rem' }}>
                                                        <Lock size={14} /> Not Automated
                                                    </div>
                                                )}
                                            </button>
                                        );
                                    })
                            )}
                        </div>

                        <div style={{ padding: '1rem', borderTop: '1px solid var(--border)', display: 'flex', justifyContent: 'flex-end' }}>
                            <button className="btn btn-secondary" onClick={() => setTemplateModalOpen(false)}>Cancel</button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
}
