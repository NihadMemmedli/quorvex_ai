'use client';
import React from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';
import { SeverityBadge, StatusBadge } from '@/components/shared';
import type { DbTestCheck } from './types';

interface CheckResultRowProps {
    check: DbTestCheck;
    isExpanded: boolean;
    onToggle: () => void;
}

export default React.memo(function CheckResultRow({ check, isExpanded, onToggle }: CheckResultRowProps) {
    return (
        <React.Fragment>
            <tr onClick={onToggle}
                style={{ borderBottom: '1px solid var(--border)', cursor: 'pointer' }}>
                <td style={{ padding: '0.5rem' }}>
                    <StatusBadge status={check.status} />
                </td>
                <td style={{ padding: '0.5rem', fontSize: '0.85rem' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                        {isExpanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                        {check.check_name}
                    </div>
                </td>
                <td style={{ padding: '0.5rem', fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                    {check.check_type}
                </td>
                <td style={{ padding: '0.5rem', fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                    {check.table_name || '-'}
                </td>
                <td style={{ padding: '0.5rem' }}>
                    <SeverityBadge severity={check.severity} />
                </td>
                <td style={{ padding: '0.5rem', fontSize: '0.8rem', color: 'var(--text-secondary)', textAlign: 'right' }}>
                    {check.execution_time_ms != null ? `${check.execution_time_ms}ms` : '-'}
                </td>
            </tr>
            {isExpanded && (
                <tr>
                    <td colSpan={6} style={{ padding: 0 }}>
                        <div style={{
                            padding: '0.75rem 1rem',
                            background: 'rgba(0,0,0,0.02)',
                            borderBottom: '1px solid var(--border)',
                            fontSize: '0.8rem',
                        }}>
                            {check.description && (
                                <p style={{ marginBottom: '0.5rem' }}><strong>Description:</strong> {check.description}</p>
                            )}
                            <div style={{ marginBottom: '0.5rem' }}>
                                <strong>SQL Query:</strong>
                                <pre style={{
                                    background: 'var(--bg)', padding: '0.5rem',
                                    borderRadius: '4px', overflow: 'auto',
                                    marginTop: '4px', fontSize: '0.75rem',
                                }}>
                                    {check.sql_query}
                                </pre>
                            </div>
                            {check.expected_result && (
                                <p style={{ marginBottom: '0.5rem' }}>
                                    <strong>Expected:</strong> {check.expected_result}
                                </p>
                            )}
                            {check.actual_result && (
                                <p style={{ marginBottom: '0.5rem' }}>
                                    <strong>Actual:</strong> {check.actual_result}
                                </p>
                            )}
                            {check.error_message && (
                                <p style={{ color: 'var(--danger)', marginBottom: '0.5rem' }}>
                                    <strong>Error:</strong> {check.error_message}
                                </p>
                            )}
                            {check.row_count != null && (
                                <p style={{ marginBottom: '0.5rem' }}>
                                    <strong>Row Count:</strong> {check.row_count}
                                </p>
                            )}
                            {check.sample_data && check.sample_data.length > 0 && (
                                <div>
                                    <strong>Sample Data:</strong>
                                    <div style={{ overflow: 'auto', marginTop: '4px' }}>
                                        <table style={{ borderCollapse: 'collapse', fontSize: '0.75rem', width: '100%' }}>
                                            <thead>
                                                <tr>
                                                    {Object.keys(check.sample_data[0]).map(col => (
                                                        <th key={col} style={{
                                                            padding: '4px 8px', borderBottom: '1px solid var(--border)',
                                                            textAlign: 'left', whiteSpace: 'nowrap',
                                                            background: 'var(--bg)',
                                                        }}>
                                                            {col}
                                                        </th>
                                                    ))}
                                                </tr>
                                            </thead>
                                            <tbody>
                                                {check.sample_data.map((row, ri) => (
                                                    <tr key={ri}>
                                                        {Object.values(row).map((val, ci) => (
                                                            <td key={ci} style={{
                                                                padding: '4px 8px',
                                                                borderBottom: '1px solid var(--border)',
                                                                whiteSpace: 'nowrap',
                                                            }}>
                                                                {val == null ? <span style={{ color: 'var(--text-secondary)' }}>NULL</span> : String(val)}
                                                            </td>
                                                        ))}
                                                    </tr>
                                                ))}
                                            </tbody>
                                        </table>
                                    </div>
                                </div>
                            )}
                        </div>
                    </td>
                </tr>
            )}
        </React.Fragment>
    );
});
