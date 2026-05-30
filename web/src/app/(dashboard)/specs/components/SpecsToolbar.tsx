'use client';

import * as React from 'react';
import { Filter, Search, ToggleLeft, ToggleRight, X } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
    DropdownMenu,
    DropdownMenuCheckboxItem,
    DropdownMenuContent,
    DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { Input } from '@/components/ui/input';
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from '@/components/ui/select';

export interface SpecsToolbarOption {
    value: string;
    label: string;
    count?: number;
    disabled?: boolean;
}

export interface SpecsToolbarSelect {
    id: string;
    label: string;
    value: string;
    options: SpecsToolbarOption[];
    placeholder?: string;
    onChange: (value: string) => void;
}

export interface SpecsToolbarProps {
    searchValue: string;
    onSearchChange: (value: string) => void;
    searchPlaceholder?: string;
    resultLabel?: string;
    automatedOnly?: boolean;
    automatedCount?: number;
    onAutomatedOnlyChange?: (value: boolean) => void;
    tagOptions?: SpecsToolbarOption[];
    selectedTagValues?: string[];
    onSelectedTagValuesChange?: (values: string[]) => void;
    selects?: SpecsToolbarSelect[];
    disabled?: boolean;
    className?: string;
    style?: React.CSSProperties;
}

const shellStyle: React.CSSProperties = {
    display: 'grid',
    gap: '0.75rem',
    padding: '0.875rem',
    border: '1px solid var(--border)',
    borderRadius: '8px',
    background: 'var(--surface)',
};

const topRowStyle: React.CSSProperties = {
    display: 'flex',
    gap: '0.75rem',
    alignItems: 'center',
    flexWrap: 'wrap',
};

const filtersRowStyle: React.CSSProperties = {
    display: 'flex',
    gap: '0.5rem',
    alignItems: 'center',
    flexWrap: 'wrap',
};

const filterButtonStyle: React.CSSProperties = {
    minHeight: '36px',
    border: 'none',
    background: 'transparent',
    color: 'var(--text-secondary)',
    boxShadow: 'none',
};

const activeFilterButtonStyle: React.CSSProperties = {
    ...filterButtonStyle,
    color: 'var(--success)',
};

const countBadgeStyle: React.CSSProperties = {
    padding: '0.05rem 0.45rem',
    border: 'none',
    background: 'transparent',
    color: 'var(--text-secondary)',
    boxShadow: 'none',
    fontWeight: 600,
};

const tagMenuStyle: React.CSSProperties = {
    width: 'min(360px, calc(100vw - 2rem))',
    minWidth: 280,
    maxHeight: 'min(420px, calc(100vh - 220px))',
    overflowY: 'auto',
    overflowX: 'hidden',
    padding: '0.25rem',
    zIndex: 1200,
    background: 'var(--surface)',
    border: 'none',
    boxShadow: 'none',
};

const tagItemStyle: React.CSSProperties = {
    minHeight: 32,
    paddingTop: '0.4rem',
    paddingBottom: '0.4rem',
    fontSize: '0.82rem',
};

function toggleValue(values: string[], value: string): string[] {
    return values.includes(value)
        ? values.filter(item => item !== value)
        : [...values, value];
}

export function SpecsToolbar({
    searchValue,
    onSearchChange,
    searchPlaceholder = 'Search specs...',
    resultLabel,
    automatedOnly = false,
    automatedCount,
    onAutomatedOnlyChange,
    tagOptions = [],
    selectedTagValues = [],
    onSelectedTagValuesChange,
    selects = [],
    disabled = false,
    className,
    style,
}: SpecsToolbarProps) {
    const hasSelectedTags = selectedTagValues.length > 0;
    const canFilterTags = tagOptions.length > 0 && Boolean(onSelectedTagValuesChange);

    return (
        <>
            <section className={className} style={{ ...shellStyle, ...style }} aria-label="Specs filters">
                <div style={topRowStyle}>
                    <div style={{ position: 'relative', minWidth: '220px', flex: '1 1 280px' }}>
                        <Search
                            size={16}
                            aria-hidden="true"
                            style={{
                                position: 'absolute',
                                left: '0.75rem',
                                top: '50%',
                                transform: 'translateY(-50%)',
                                color: 'var(--text-secondary)',
                                pointerEvents: 'none',
                            }}
                        />
                        <Input
                            value={searchValue}
                            onChange={event => onSearchChange(event.target.value)}
                            placeholder={searchPlaceholder}
                            disabled={disabled}
                            aria-label={searchPlaceholder}
                            style={{ paddingLeft: '2.25rem', paddingRight: searchValue ? '2.25rem' : undefined }}
                        />
                        {searchValue && (
                            <Button
                                type="button"
                                variant="ghost"
                                size="icon"
                                title="Clear search"
                                aria-label="Clear search"
                                onClick={() => onSearchChange('')}
                                disabled={disabled}
                                style={{
                                    position: 'absolute',
                                    right: '0.25rem',
                                    top: '50%',
                                    transform: 'translateY(-50%)',
                                    width: '32px',
                                    height: '32px',
                                    color: 'var(--text-secondary)',
                                }}
                            >
                                <X size={15} />
                            </Button>
                        )}
                    </div>

                    {resultLabel && (
                        <span
                            style={{
                                color: 'var(--text-secondary)',
                                fontSize: '0.82rem',
                                whiteSpace: 'nowrap',
                            }}
                        >
                            {resultLabel}
                        </span>
                    )}
                </div>

                <div style={filtersRowStyle}>
                    {onAutomatedOnlyChange && (
                        <Button
                            type="button"
                            className="specs-toolbar-flat-control focus-ring"
                            variant={automatedOnly ? 'default' : 'secondary'}
                            size="sm"
                            onClick={() => onAutomatedOnlyChange(!automatedOnly)}
                            disabled={disabled}
                            aria-pressed={automatedOnly}
                            title="Toggle automated specs"
                            style={{
                                ...(automatedOnly ? activeFilterButtonStyle : filterButtonStyle),
                            }}
                        >
                            {automatedOnly ? <ToggleRight size={16} /> : <ToggleLeft size={16} />}
                            Automated
                            {typeof automatedCount === 'number' && (
                                <Badge
                                    variant={automatedOnly ? 'secondary' : 'outline'}
                                    style={{
                                        ...countBadgeStyle,
                                        color: automatedOnly ? 'var(--success)' : 'var(--text-secondary)',
                                    }}
                                >
                                    {automatedCount}
                                </Badge>
                            )}
                        </Button>
                    )}

                    {selects.map(select => (
                        <div key={select.id} style={{ minWidth: '150px' }}>
                            <Select value={select.value} onValueChange={select.onChange} disabled={disabled}>
                                <SelectTrigger
                                    aria-label={select.label}
                                    style={{ height: '36px', minHeight: '36px' }}
                                >
                                    <SelectValue placeholder={select.placeholder ?? select.label} />
                                </SelectTrigger>
                                <SelectContent>
                                    {select.options.map(option => (
                                        <SelectItem
                                            key={option.value}
                                            value={option.value}
                                            disabled={option.disabled}
                                        >
                                            {option.label}
                                            {typeof option.count === 'number' ? ` (${option.count})` : ''}
                                        </SelectItem>
                                    ))}
                                </SelectContent>
                            </Select>
                        </div>
                    ))}

                    {canFilterTags && (
                        <DropdownMenu>
                            <DropdownMenuTrigger asChild>
                                <Button
                                    type="button"
                                    className="specs-toolbar-flat-control focus-ring"
                                    variant="secondary"
                                    size="sm"
                                    disabled={disabled}
                                    style={filterButtonStyle}
                                >
                                    <Filter size={15} />
                                    Tags
                                    {hasSelectedTags && (
                                        <Badge
                                            variant="default"
                                            style={{
                                                ...countBadgeStyle,
                                                color: 'var(--primary)',
                                            }}
                                        >
                                            {selectedTagValues.length}
                                        </Badge>
                                    )}
                                </Button>
                            </DropdownMenuTrigger>
                            <DropdownMenuContent
                                align="start"
                                sideOffset={6}
                                collisionPadding={16}
                                style={tagMenuStyle}
                            >
                                {tagOptions.map(tag => (
                                    <DropdownMenuCheckboxItem
                                        key={tag.value}
                                        checked={selectedTagValues.includes(tag.value)}
                                        disabled={tag.disabled}
                                        style={tagItemStyle}
                                        onCheckedChange={() => {
                                            onSelectedTagValuesChange?.(toggleValue(selectedTagValues, tag.value));
                                        }}
                                    >
                                        <span style={{ display: 'flex', justifyContent: 'space-between', width: '100%', gap: '1rem', minWidth: 0 }}>
                                            <span style={{ minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{tag.label}</span>
                                            {typeof tag.count === 'number' && (
                                                <span style={{ color: 'var(--text-secondary)' }}>{tag.count}</span>
                                            )}
                                        </span>
                                    </DropdownMenuCheckboxItem>
                                ))}
                                {hasSelectedTags && (
                                    <Button
                                        type="button"
                                        className="specs-toolbar-clear-tags focus-ring"
                                        variant="ghost"
                                        size="sm"
                                        onClick={() => onSelectedTagValuesChange?.([])}
                                        style={{
                                            width: '100%',
                                            justifyContent: 'flex-start',
                                            border: 'none',
                                            background: 'transparent',
                                            color: 'var(--text-secondary)',
                                            fontSize: '0.82rem',
                                            marginTop: '0.125rem',
                                        }}
                                    >
                                        <X size={14} />
                                        Clear tags
                                    </Button>
                                )}
                            </DropdownMenuContent>
                        </DropdownMenu>
                    )}

                    {hasSelectedTags && (
                        <div style={{ display: 'flex', gap: '0.375rem', flexWrap: 'wrap', minWidth: 0 }}>
                            {selectedTagValues.map(value => {
                                const tag = tagOptions.find(option => option.value === value);
                                return (
                                    <Button
                                        key={value}
                                        type="button"
                                        className="specs-toolbar-flat-control focus-ring"
                                        variant="ghost"
                                        size="sm"
                                        onClick={() => onSelectedTagValuesChange?.(selectedTagValues.filter(item => item !== value))}
                                        disabled={disabled}
                                        title={`Remove ${tag?.label ?? value}`}
                                        style={{
                                            height: '30px',
                                            fontSize: '0.78rem',
                                            border: 'none',
                                            background: 'transparent',
                                            boxShadow: 'none',
                                            color: 'var(--text-secondary)',
                                        }}
                                    >
                                        {tag?.label ?? value}
                                        <X size={13} />
                                    </Button>
                                );
                            })}
                        </div>
                    )}
                </div>
            </section>
            <style jsx global>{`
                .specs-toolbar-flat-control:hover:not(:disabled),
                .specs-toolbar-clear-tags:hover:not(:disabled) {
                    background: var(--surface-hover) !important;
                }

                .specs-toolbar-flat-control:focus-visible,
                .specs-toolbar-clear-tags:focus-visible {
                    outline: 2px solid var(--primary);
                    outline-offset: 2px;
                    box-shadow: none !important;
                }
            `}</style>
        </>
    );
}
