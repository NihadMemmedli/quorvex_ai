import React from 'react';
import { severityColor, severityBg } from '@/lib/colors';

interface SeverityBadgeProps {
    severity: string;
    count?: number;
}

export const SeverityBadge = React.memo(function SeverityBadge({ severity, count }: SeverityBadgeProps) {
    return (
        <span style={{
            display: 'inline-flex', alignItems: 'center', gap: '4px',
            padding: '2px 10px', borderRadius: '9999px', fontSize: '0.75rem', fontWeight: 600,
            color: severityColor(severity), background: severityBg(severity),
            transition: 'all 0.2s var(--ease-smooth)',
        }}>
            {severity.toUpperCase()}
            {count !== undefined && <span>({count})</span>}
        </span>
    );
});
