'use client';
import React, { useEffect, useMemo, useState } from 'react';
import { Database, Loader2, Play, RefreshCw, Table2 } from 'lucide-react';
import { cardStyle, inputStyle, btnPrimary, btnSecondary } from '@/lib/styles';
import { getAuthHeaders } from '@/lib/styles';
import { API_BASE, withProjectBody, withProjectQuery } from '@/lib/api';
import type { DbConnection, DbSchema, DbTable } from './types';

interface DbViewerTabProps {
    connections: DbConnection[];
    projectId: string;
    preferredConnectionId?: string;
    selectedConnectionId?: string;
    selectedTableName?: string;
    onSelectConnection: (connectionId: string) => void;
    onSelectTable: (tableName: string) => void;
    canEdit: boolean;
}

function quoteIdent(value: string) {
    return `"${value.replace(/"/g, '""')}"`;
}

export default function DbViewerTab({
    connections,
    projectId,
    preferredConnectionId,
    selectedConnectionId,
    selectedTableName,
    onSelectConnection,
    onSelectTable,
    canEdit,
}: DbViewerTabProps) {
    const [schemaData, setSchemaData] = useState<DbSchema | null>(null);
    const [loadingSchema, setLoadingSchema] = useState(false);
    const [schemaError, setSchemaError] = useState('');
    const [sql, setSql] = useState('SELECT 1');
    const [queryLimit, setQueryLimit] = useState(100);
    const [queryRows, setQueryRows] = useState<Record<string, unknown>[]>([]);
    const [queryMeta, setQueryMeta] = useState<{ row_count?: number; total_row_count?: number; execution_time_ms?: number; truncated?: boolean } | null>(null);
    const [queryError, setQueryError] = useState('');
    const [runningQuery, setRunningQuery] = useState(false);

    const connectionId = selectedConnectionId || preferredConnectionId || connections[0]?.id || '';
    const selectedTable = useMemo(() => {
        if (!schemaData?.tables.length) return null;
        return schemaData.tables.find(t => t.table_name === selectedTableName) || schemaData.tables[0];
    }, [schemaData, selectedTableName]);

    const fetchSchema = async (connId: string) => {
        if (!connId) return;
        setLoadingSchema(true);
        setSchemaError('');
        try {
            const res = await fetch(`${API_BASE}${withProjectQuery(`/database-testing/connections/${connId}/schema`, projectId)}`, {
                headers: getAuthHeaders(),
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) throw new Error(data.detail || 'Failed to load schema');
            setSchemaData(data.schema || null);
            const firstTable = data.schema?.tables?.[0]?.table_name;
            if (!selectedTableName && firstTable) onSelectTable(firstTable);
        } catch (e) {
            setSchemaError(e instanceof Error ? e.message : String(e));
            setSchemaData(null);
        }
        setLoadingSchema(false);
    };

    useEffect(() => {
        if (!connectionId) return;
        if (selectedConnectionId !== connectionId) onSelectConnection(connectionId);
        fetchSchema(connectionId);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [connectionId]);

    useEffect(() => {
        if (!schemaData || !selectedTable) return;
        const schemaName = schemaData.schema || 'public';
        setSql(`SELECT * FROM ${quoteIdent(schemaName)}.${quoteIdent(selectedTable.table_name)}`);
    }, [schemaData, selectedTable]);

    const runQuery = async () => {
        if (!canEdit) return;
        if (!connectionId || !sql.trim()) return;
        setRunningQuery(true);
        setQueryError('');
        setQueryRows([]);
        setQueryMeta(null);
        try {
            const res = await fetch(`${API_BASE}${withProjectQuery(`/database-testing/connections/${connectionId}/query`, projectId)}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
                body: JSON.stringify(withProjectBody({ sql, limit: queryLimit }, projectId)),
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) throw new Error(data.detail || 'Query failed');
            setQueryRows(Array.isArray(data.rows) ? data.rows : []);
            setQueryMeta({
                row_count: data.row_count,
                total_row_count: data.total_row_count,
                execution_time_ms: data.execution_time_ms,
                truncated: data.truncated,
            });
        } catch (e) {
            setQueryError(e instanceof Error ? e.message : String(e));
        }
        setRunningQuery(false);
    };

    const columns = queryRows.length > 0 ? Object.keys(queryRows[0]) : [];
    const indexes = schemaData?.indexes?.filter(idx => idx.table_name === selectedTable?.table_name) || [];
    const foreignKeys = schemaData?.foreign_keys?.filter(fk => fk.from_table === selectedTable?.table_name || fk.to_table === selectedTable?.table_name) || [];

    return (
        <div style={{ display: 'grid', gridTemplateColumns: '320px 1fr', gap: '1rem' }}>
            <div style={cardStyle}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
                    <h3 style={{ fontWeight: 600, display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                        <Database size={16} /> Database
                    </h3>
                    <button onClick={() => fetchSchema(connectionId)} disabled={!connectionId || loadingSchema} style={{ ...btnSecondary, padding: '4px 8px' }}>
                        {loadingSchema ? <Loader2 size={14} style={{ animation: 'spin 1s linear infinite' }} /> : <RefreshCw size={14} />}
                    </button>
                </div>

                <label style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginBottom: '4px', display: 'block' }}>Connection</label>
                <select value={connectionId} onChange={e => onSelectConnection(e.target.value)} style={{ ...inputStyle, marginBottom: '1rem' }}>
                    <option value="">Select a connection...</option>
                    {connections.map(c => (
                        <option key={c.id} value={c.id}>{c.name} ({c.database})</option>
                    ))}
                </select>

                {schemaError && (
                    <div style={{ color: 'var(--danger)', fontSize: '0.85rem', marginBottom: '1rem' }}>{schemaError}</div>
                )}

                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.35rem', maxHeight: '520px', overflow: 'auto' }}>
                    {(schemaData?.tables || []).map(table => (
                        <button key={table.table_name}
                            onClick={() => onSelectTable(table.table_name)}
                            style={{
                                border: '1px solid var(--border)',
                                background: selectedTable?.table_name === table.table_name ? 'var(--primary-glow)' : 'transparent',
                                color: 'var(--text-primary)',
                                borderRadius: 'var(--radius)',
                                padding: '0.55rem 0.65rem',
                                textAlign: 'left',
                                cursor: 'pointer',
                                display: 'flex',
                                alignItems: 'center',
                                gap: '0.5rem',
                            }}>
                            <Table2 size={14} style={{ color: 'var(--primary-hover)', flexShrink: 0 }} />
                            <span style={{ flex: 1, minWidth: 0 }}>
                                <span style={{ display: 'block', fontSize: '0.85rem', fontWeight: 500, overflow: 'hidden', textOverflow: 'ellipsis' }}>{table.table_name}</span>
                                <span style={{ display: 'block', fontSize: '0.72rem', color: 'var(--text-secondary)' }}>{table.columns?.length || 0} columns | {table.estimated_rows ?? 0} rows</span>
                            </span>
                        </button>
                    ))}
                    {loadingSchema && (
                        <div style={{ color: 'var(--text-secondary)', fontSize: '0.85rem', display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
                            <Loader2 size={14} style={{ animation: 'spin 1s linear infinite' }} /> Loading schema...
                        </div>
                    )}
                </div>
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                <div style={cardStyle}>
                    <h3 style={{ fontWeight: 600, marginBottom: '0.75rem' }}>{selectedTable?.table_name || 'No table selected'}</h3>
                    {selectedTable ? (
                        <div style={{ display: 'grid', gridTemplateColumns: '1.2fr 0.8fr', gap: '1rem' }}>
                            <div>
                                <h4 style={{ fontSize: '0.85rem', fontWeight: 600, marginBottom: '0.5rem' }}>Columns</h4>
                                <TablePreview table={selectedTable} />
                            </div>
                            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                                <MetaList title="Indexes" items={indexes} emptyText="No indexes found" />
                                <MetaList title="Relationships" items={foreignKeys} emptyText="No foreign keys found" />
                            </div>
                        </div>
                    ) : (
                        <p style={{ color: 'var(--text-secondary)', fontSize: '0.9rem' }}>Select a connection to inspect its schema.</p>
                    )}
                </div>

                <div style={cardStyle}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.75rem' }}>
                        <h3 style={{ fontWeight: 600 }}>Read-only Query</h3>
                        <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
                            <input type="number" min={1} max={500} value={queryLimit}
                                onChange={e => setQueryLimit(Math.max(1, Math.min(500, Number(e.target.value) || 100)))}
                                style={{ ...inputStyle, width: '90px', padding: '0.45rem 0.5rem' }} />
                            {canEdit && (
                                <button onClick={runQuery} disabled={runningQuery || !connectionId || !sql.trim()} style={btnPrimary}>
                                    {runningQuery ? <Loader2 size={14} style={{ animation: 'spin 1s linear infinite' }} /> : <Play size={14} />}
                                    Run
                                </button>
                            )}
                        </div>
                    </div>
                    <textarea value={sql} onChange={e => setSql(e.target.value)} rows={5}
                        readOnly={!canEdit}
                        style={{ ...inputStyle, fontFamily: 'monospace', resize: 'vertical', marginBottom: '0.75rem' }} />
                    {queryError && <div style={{ color: 'var(--danger)', fontSize: '0.85rem', marginBottom: '0.75rem' }}>{queryError}</div>}
                    {queryMeta && (
                        <div style={{ color: 'var(--text-secondary)', fontSize: '0.8rem', marginBottom: '0.75rem' }}>
                            {queryMeta.row_count ?? 0} rows | {queryMeta.execution_time_ms ?? 0}ms{queryMeta.truncated ? ' | truncated' : ''}
                        </div>
                    )}
                    <ResultTable columns={columns} rows={queryRows} />
                </div>
            </div>
        </div>
    );
}

function TablePreview({ table }: { table: DbTable }) {
    return (
        <div style={{ overflow: 'auto', border: '1px solid var(--border)', borderRadius: 'var(--radius)' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.8rem' }}>
                <thead>
                    <tr style={{ background: 'rgba(148, 163, 184, 0.08)' }}>
                        <th style={{ textAlign: 'left', padding: '0.5rem' }}>Name</th>
                        <th style={{ textAlign: 'left', padding: '0.5rem' }}>Type</th>
                        <th style={{ textAlign: 'left', padding: '0.5rem' }}>Nullable</th>
                    </tr>
                </thead>
                <tbody>
                    {table.columns.map(column => (
                        <tr key={column.column_name} style={{ borderTop: '1px solid var(--border)' }}>
                            <td style={{ padding: '0.5rem', fontFamily: 'monospace' }}>{column.column_name}</td>
                            <td style={{ padding: '0.5rem', color: 'var(--text-secondary)' }}>{column.data_type}</td>
                            <td style={{ padding: '0.5rem', color: column.is_nullable === 'NO' ? 'var(--success)' : 'var(--text-secondary)' }}>{column.is_nullable}</td>
                        </tr>
                    ))}
                </tbody>
            </table>
        </div>
    );
}

function MetaList({ title, items, emptyText }: { title: string; items: Array<Record<string, unknown>>; emptyText: string }) {
    return (
        <div>
            <h4 style={{ fontSize: '0.85rem', fontWeight: 600, marginBottom: '0.5rem' }}>{title}</h4>
            {items.length === 0 ? (
                <p style={{ color: 'var(--text-secondary)', fontSize: '0.8rem' }}>{emptyText}</p>
            ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.35rem', maxHeight: '180px', overflow: 'auto' }}>
                    {items.map((item, idx) => (
                        <pre key={idx} style={{
                            margin: 0,
                            padding: '0.5rem',
                            border: '1px solid var(--border)',
                            borderRadius: 'var(--radius)',
                            color: 'var(--text-secondary)',
                            fontSize: '0.72rem',
                            whiteSpace: 'pre-wrap',
                        }}>{JSON.stringify(item, null, 2)}</pre>
                    ))}
                </div>
            )}
        </div>
    );
}

function ResultTable({ columns, rows }: { columns: string[]; rows: Record<string, unknown>[] }) {
    if (rows.length === 0) {
        return <p style={{ color: 'var(--text-secondary)', fontSize: '0.85rem' }}>No rows to display.</p>;
    }
    return (
        <div style={{ overflow: 'auto', maxHeight: '380px', border: '1px solid var(--border)', borderRadius: 'var(--radius)' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.8rem' }}>
                <thead>
                    <tr style={{ background: 'rgba(148, 163, 184, 0.08)' }}>
                        {columns.map(column => (
                            <th key={column} style={{ textAlign: 'left', padding: '0.5rem', whiteSpace: 'nowrap' }}>{column}</th>
                        ))}
                    </tr>
                </thead>
                <tbody>
                    {rows.map((row, rowIdx) => (
                        <tr key={rowIdx} style={{ borderTop: '1px solid var(--border)' }}>
                            {columns.map(column => (
                                <td key={column} style={{ padding: '0.5rem', color: 'var(--text-secondary)', maxWidth: '260px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                    {row[column] == null ? 'NULL' : String(row[column])}
                                </td>
                            ))}
                        </tr>
                    ))}
                </tbody>
            </table>
        </div>
    );
}
