'use client';
import { useState, KeyboardEvent } from 'react';
import { X, Plus } from 'lucide-react';

interface TagEditorProps {
    tags: string[];
    onTagsChange: (tags: string[]) => void;
    allTags?: string[]; // All available tags for suggestions
    placeholder?: string;
}

export default function TagEditor({ tags, onTagsChange, allTags = [], placeholder = "Add tag..." }: TagEditorProps) {
    const [inputValue, setInputValue] = useState('');
    const [suggestions, setSuggestions] = useState<string[]>([]);
    const [showSuggestions, setShowSuggestions] = useState(false);

    const handleInputChange = (value: string) => {
        setInputValue(value);

        if (value.trim()) {
            // Filter suggestions based on input
            const filtered = allTags
                .filter(tag =>
                    tag.toLowerCase().includes(value.toLowerCase()) &&
                    !tags.includes(tag)
                )
                .slice(0, 5); // Limit to 5 suggestions
            setSuggestions(filtered);
            setShowSuggestions(filtered.length > 0);
        } else {
            setShowSuggestions(false);
        }
    };

    const addTag = (tag: string) => {
        const trimmedTag = tag.trim().toLowerCase();
        if (trimmedTag && !tags.includes(trimmedTag)) {
            onTagsChange([...tags, trimmedTag]);
            setInputValue('');
            setShowSuggestions(false);
        }
    };

    const removeTag = (tagToRemove: string) => {
        onTagsChange(tags.filter(tag => tag !== tagToRemove));
    };

    const handleKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            if (suggestions.length > 0 && showSuggestions) {
                addTag(suggestions[0]);
            } else {
                addTag(inputValue);
            }
        } else if (e.key === 'Backspace' && !inputValue && tags.length > 0) {
            removeTag(tags[tags.length - 1]);
        }
    };

    const getTagColor = (tag: string) => {
        // Color coding based on tag type
        if (tag === 'p0' || tag === 'critical') return { bg: 'rgba(239, 68, 68, 0.1)', color: '#ef4444' };
        if (tag === 'smoke' || tag === 'stable') return { bg: 'rgba(34, 197, 94, 0.1)', color: '#22c55e' };
        if (tag === 'auth' || tag === 'workflow') return { bg: 'rgba(168, 85, 247, 0.1)', color: '#a855f7' };
        return { bg: 'rgba(59, 130, 246, 0.1)', color: '#3b82f6' };
    };

    return (
        <div style={{ position: 'relative' }}>
            <div style={{
                display: 'flex',
                flexWrap: 'wrap',
                gap: '0.5rem',
                padding: '0.75rem',
                border: '1px solid var(--border)',
                borderRadius: '8px',
                minHeight: '48px',
                background: 'var(--surface)',
                cursor: 'text'
            }}>
                {tags.map(tag => {
                    const colors = getTagColor(tag);
                    return (
                        <span
                            key={tag}
                            style={{
                                display: 'flex',
                                alignItems: 'center',
                                gap: '0.25rem',
                                padding: '0.25rem 0.5rem',
                                borderRadius: '9999px',
                                background: colors.bg,
                                color: colors.color,
                                fontSize: '0.85rem',
                                fontWeight: 500
                            }}
                        >
                            {tag}
                            <button
                                onClick={() => removeTag(tag)}
                                style={{
                                    background: 'none',
                                    border: 'none',
                                    cursor: 'pointer',
                                    padding: '2px',
                                    display: 'flex',
                                    alignItems: 'center',
                                    color: 'inherit',
                                    opacity: 0.7
                                }}
                                onMouseEnter={(e) => e.currentTarget.style.opacity = '1'}
                                onMouseLeave={(e) => e.currentTarget.style.opacity = '0.7'}
                            >
                                <X size={14} />
                            </button>
                        </span>
                    );
                })}
                <input
                    type="text"
                    value={inputValue}
                    onChange={(e) => handleInputChange(e.target.value)}
                    onKeyDown={handleKeyDown}
                    onFocus={() => inputValue && setShowSuggestions(suggestions.length > 0)}
                    onBlur={() => setTimeout(() => setShowSuggestions(false), 200)}
                    placeholder={tags.length === 0 ? placeholder : ''}
                    style={{
                        flex: 1,
                        minWidth: '120px',
                        border: 'none',
                        outline: 'none',
                        background: 'transparent',
                        color: 'var(--text)',
                        fontSize: '0.9rem'
                    }}
                />
            </div>

            {/* Suggestions dropdown */}
            {showSuggestions && suggestions.length > 0 && (
                <div style={{
                    position: 'absolute',
                    top: '100%',
                    left: 0,
                    right: 0,
                    marginTop: '0.25rem',
                    background: 'var(--surface)',
                    border: '1px solid var(--border)',
                    borderRadius: '8px',
                    boxShadow: '0 4px 6px -1px rgba(0, 0, 0, 0.1)',
                    zIndex: 10,
                    maxHeight: '200px',
                    overflowY: 'auto'
                }}>
                    {suggestions.map(suggestion => {
                        const colors = getTagColor(suggestion);
                        return (
                            <div
                                key={suggestion}
                                onClick={() => addTag(suggestion)}
                                style={{
                                    padding: '0.75rem',
                                    cursor: 'pointer',
                                    borderBottom: '1px solid var(--border)',
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: '0.5rem',
                                    transition: 'background 0.2s'
                                }}
                                onMouseEnter={(e) => e.currentTarget.style.background = 'var(--surface-hover)'}
                                onMouseLeave={(e) => e.currentTarget.style.background = 'transparent'}
                            >
                                <span
                                    style={{
                                        padding: '0.25rem 0.5rem',
                                        borderRadius: '9999px',
                                        background: colors.bg,
                                        color: colors.color,
                                        fontSize: '0.85rem',
                                        fontWeight: 500
                                    }}
                                >
                                    {suggestion}
                                </span>
                            </div>
                        );
                    })}
                </div>
            )}

            <p style={{
                marginTop: '0.5rem',
                fontSize: '0.8rem',
                color: 'var(--text-secondary)'
            }}>
                Press Enter to add tag, Backspace to remove last tag
            </p>
        </div>
    );
}
