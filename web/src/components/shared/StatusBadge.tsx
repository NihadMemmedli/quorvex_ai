'use client';
import React from 'react';
import { Loader2, CheckCircle, AlertCircle, AlertTriangle, Clock, XCircle } from 'lucide-react';
import { statusColor } from '@/lib/colors';

interface StatusBadgeProps {
    status: string;
}

const STATUS_ICONS: Record<string, React.ReactNode> = {
    running: <Loader2 size={12} className="animate-spin" />,
    pending: <Clock size={12} />,
    completed: <CheckCircle size={12} />,
    passed: <CheckCircle size={12} />,
    failed: <AlertCircle size={12} />,
    error: <AlertTriangle size={12} />,
    cancelled: <XCircle size={12} />,
};

export const StatusBadge = React.memo(function StatusBadge({ status }: StatusBadgeProps) {
    const color = statusColor(status);
    const icon = STATUS_ICONS[status?.toLowerCase()];

    return (
        <span style={{
            display: 'inline-flex', alignItems: 'center', gap: '4px',
            padding: '2px 10px', borderRadius: '9999px', fontSize: '0.75rem', fontWeight: 600,
            color, background: `${color}18`,
            transition: 'all 0.2s var(--ease-smooth)',
        }}>
            {icon}
            {status.toUpperCase()}
        </span>
    );
});
