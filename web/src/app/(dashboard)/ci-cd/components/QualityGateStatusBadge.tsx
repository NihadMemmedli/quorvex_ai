import { AlertTriangle, CheckCircle, Loader2, ShieldCheck, XCircle } from 'lucide-react';

export function getGateColor(state: string): string {
    switch (state) {
        case 'passed': return 'var(--success)';
        case 'failed':
        case 'blocked': return 'var(--danger)';
        case 'running':
        case 'analyzed': return 'var(--primary)';
        case 'needs-full-suite': return 'var(--warning)';
        default: return 'var(--text-secondary)';
    }
}

function getGateIcon(state: string) {
    switch (state) {
        case 'passed': return <CheckCircle size={15} />;
        case 'failed':
        case 'blocked': return <XCircle size={15} />;
        case 'running':
        case 'analyzed': return <Loader2 size={15} style={{ animation: 'spin 1s linear infinite' }} />;
        case 'needs-full-suite': return <AlertTriangle size={15} />;
        default: return <ShieldCheck size={15} />;
    }
}

export function formatGateState(state: string): string {
    return state.replaceAll('-', ' ');
}

export function QualityGateStatusBadge({ state }: { state: string }) {
    const color = getGateColor(state);
    return (
        <span style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: '0.3rem',
            padding: '0.18rem 0.5rem',
            borderRadius: '999px',
            color,
            background: `color-mix(in srgb, ${color} 12%, transparent)`,
            fontSize: '0.72rem',
            fontWeight: 750,
            textTransform: 'capitalize',
            flexShrink: 0,
            whiteSpace: 'nowrap',
        }}>
            {getGateIcon(state)}
            {formatGateState(state)}
        </span>
    );
}
