'use client';

import { useState } from 'react';
import { Settings2, ChevronDown, Globe, LogIn, User, Key, Zap } from 'lucide-react';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import type { PrdSettings } from './types';

interface ConfigPanelProps {
    settings: PrdSettings;
    onUpdate: <K extends keyof PrdSettings>(key: K, value: PrdSettings[K]) => void;
}

export function ConfigPanel({ settings, onUpdate }: ConfigPanelProps) {
    const [isExpanded, setIsExpanded] = useState(!settings.targetUrl);

    return (
        <div className="card-elevated overflow-hidden" style={{ padding: 0 }}>
            {/* Collapsible Header */}
            <button
                onClick={() => setIsExpanded(!isExpanded)}
                className="w-full flex items-center justify-between px-4 py-3 transition-colors duration-200"
                style={{
                    cursor: 'pointer',
                    background: 'transparent',
                }}
                onMouseEnter={(e) => (e.currentTarget.style.background = 'rgba(255,255,255,0.03)')}
                onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
            >
                <div className="flex items-center" style={{ gap: '10px' }}>
                    <Settings2 size={16} style={{ color: 'var(--text-secondary)' }} />
                    <span className="text-sm font-medium" style={{ color: 'var(--text)' }}>
                        Configuration
                    </span>
                    {!isExpanded && settings.targetUrl && (
                        <span
                            className="text-xs font-mono truncate max-w-[200px]"
                            style={{ color: 'var(--text-tertiary)' }}
                        >
                            {settings.targetUrl}
                        </span>
                    )}
                </div>
                <ChevronDown
                    size={16}
                    style={{
                        color: 'var(--text-secondary)',
                        transition: 'transform 0.2s var(--ease-smooth)',
                        transform: isExpanded ? 'rotate(180deg)' : 'rotate(0deg)',
                    }}
                />
            </button>

            {/* Collapsible Content */}
            <div
                style={{
                    maxHeight: isExpanded ? '600px' : '0px',
                    overflow: 'hidden',
                    transition: 'max-height 0.3s var(--ease-smooth), opacity 0.2s var(--ease-smooth)',
                    opacity: isExpanded ? 1 : 0,
                }}
            >
                <div className="px-4 pb-4 flex flex-col gap-4">
                    {/* Divider */}
                    <div className="h-px" style={{ background: 'linear-gradient(90deg, transparent, rgba(255,255,255,0.06), transparent)' }} />

                    {/* Row 1 - Target Application */}
                    <div>
                        <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
                            <div className="flex flex-col" style={{ gap: '6px' }}>
                                <Label className="text-xs flex items-center" style={{ color: 'var(--text-secondary)', gap: '8px' }}>
                                    <Globe size={12} className="shrink-0" style={{ color: 'var(--text-tertiary)' }} />
                                    Target URL
                                </Label>
                                <Input
                                    value={settings.targetUrl}
                                    onChange={(e) => onUpdate('targetUrl', e.target.value)}
                                    placeholder="https://your-app.com"
                                    className="h-9 text-sm"
                                />
                            </div>
                            <div className="flex flex-col" style={{ gap: '6px' }}>
                                <Label className="text-xs flex items-center" style={{ color: 'var(--text-secondary)', gap: '8px' }}>
                                    <LogIn size={12} className="shrink-0" style={{ color: 'var(--text-tertiary)' }} />
                                    Login URL
                                </Label>
                                <Input
                                    value={settings.loginUrl}
                                    onChange={(e) => onUpdate('loginUrl', e.target.value)}
                                    placeholder="Leave empty if no login required"
                                    className="h-9 text-sm"
                                />
                            </div>
                        </div>
                    </div>

                    {/* Row 2 - Credentials (only when loginUrl is set) */}
                    {settings.loginUrl && (
                        <>
                            <div className="h-px" style={{ background: 'linear-gradient(90deg, transparent, rgba(255,255,255,0.06), transparent)' }} />
                            <div className="grid grid-cols-2 gap-3">
                                <div className="flex flex-col gap-2">
                                    <Label className="text-xs" style={{ color: 'var(--text-secondary)' }}>
                                        Username
                                    </Label>
                                    <div className="relative">
                                        <div className="absolute left-3 top-1/2 -translate-y-1/2 flex items-center pointer-events-none">
                                            <User size={14} style={{ color: 'var(--text-tertiary)' }} />
                                        </div>
                                        <Input
                                            value={settings.username}
                                            onChange={(e) => onUpdate('username', e.target.value)}
                                            placeholder="user@example.com"
                                            className="h-9 text-sm pl-10"
                                        />
                                    </div>
                                </div>
                                <div className="flex flex-col gap-2">
                                    <Label className="text-xs" style={{ color: 'var(--text-secondary)' }}>
                                        Password
                                    </Label>
                                    <div className="relative">
                                        <div className="absolute left-3 top-1/2 -translate-y-1/2 flex items-center pointer-events-none">
                                            <Key size={14} style={{ color: 'var(--text-tertiary)' }} />
                                        </div>
                                        <Input
                                            type="password"
                                            value={settings.password}
                                            onChange={(e) => onUpdate('password', e.target.value)}
                                            placeholder="••••••••"
                                            className="h-9 text-sm pl-10"
                                        />
                                    </div>
                                </div>
                            </div>
                        </>
                    )}

                    {/* Divider */}
                    <div className="h-px" style={{ background: 'linear-gradient(90deg, transparent, rgba(255,255,255,0.06), transparent)' }} />

                    {/* Row 3 - Toggles */}
                    <div className="flex flex-wrap gap-4 items-start">
                        {/* Live Browser Validation */}
                        <div
                            className="flex items-center gap-3 p-3 rounded-lg flex-1 min-w-[220px]"
                            style={{
                                background: 'rgba(255,255,255,0.02)',
                                border: '1px solid rgba(255,255,255,0.05)',
                            }}
                        >
                            <div className="flex flex-col flex-1">
                                <span className="text-sm font-medium" style={{ color: 'var(--text)' }}>
                                    Live Browser Validation
                                </span>
                                <span className="text-[10px]" style={{ color: 'var(--text-tertiary)' }}>
                                    {settings.useLiveValidation ? 'Agent will browse the target site' : 'PRD-only generation'}
                                </span>
                            </div>
                            <Switch
                                checked={settings.useLiveValidation}
                                onCheckedChange={(val) => onUpdate('useLiveValidation', val)}
                            />
                        </div>

                        {/* AI-Powered Generation */}
                        <div
                            className="flex items-center gap-3 p-3 rounded-lg flex-1 min-w-[220px]"
                            style={{
                                background: 'rgba(255,255,255,0.02)',
                                border: '1px solid rgba(255,255,255,0.05)',
                            }}
                        >
                            <div
                                className="p-1.5 rounded-lg transition-all duration-300"
                                style={{
                                    background: settings.useNativeAgents ? 'rgba(251,191,36,0.2)' : 'rgba(100,116,139,0.1)',
                                    color: settings.useNativeAgents ? '#facc15' : 'var(--text-tertiary)',
                                    boxShadow: settings.useNativeAgents ? '0 0 12px rgba(251,191,36,0.2)' : 'none',
                                }}
                            >
                                <Zap size={16} />
                            </div>
                            <div className="flex flex-col flex-1">
                                <span className="text-sm font-medium" style={{ color: 'var(--text)' }}>
                                    AI-Powered Generation
                                </span>
                                <span className="text-[10px]" style={{ color: 'var(--text-tertiary)' }}>
                                    {settings.useNativeAgents ? 'Live browser generation & repair' : 'Static code generation only'}
                                </span>
                            </div>
                            <Switch
                                checked={settings.useNativeAgents}
                                onCheckedChange={(val) => onUpdate('useNativeAgents', val)}
                            />
                        </div>

                        {/* Target Features */}
                        <div
                            className="flex items-center gap-3 p-3 rounded-lg"
                            style={{
                                background: 'rgba(255,255,255,0.02)',
                                border: '1px solid rgba(255,255,255,0.05)',
                            }}
                        >
                            <Label
                                htmlFor="config-target-features"
                                className="text-xs whitespace-nowrap"
                                style={{ color: 'var(--text-secondary)' }}
                            >
                                Target Features
                            </Label>
                            <Input
                                id="config-target-features"
                                type="number"
                                min={5}
                                max={50}
                                value={settings.targetFeatures}
                                onChange={(e) =>
                                    onUpdate('targetFeatures', Math.max(5, Math.min(50, parseInt(e.target.value) || 15)))
                                }
                                className="w-20 h-8 text-sm"
                            />
                            <span className="text-xs" style={{ color: 'var(--text-tertiary)' }}>
                                (5-50)
                            </span>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
}
