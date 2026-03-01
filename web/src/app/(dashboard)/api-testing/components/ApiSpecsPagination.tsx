'use client';
import React from 'react';
import { ChevronLeft, ChevronRight } from 'lucide-react';

interface ApiSpecsPaginationProps {
    currentPage: number;
    totalPages: number;
    pageSize: number;
    totalItems: number;
    onPageChange: (page: number) => void;
    onPageSizeChange: (size: number) => void;
}

const PAGE_SIZES = [25, 50, 100];

function getPageNumbers(current: number, total: number): (number | 'ellipsis')[] {
    if (total <= 7) {
        return Array.from({ length: total }, (_, i) => i + 1);
    }
    const pages: (number | 'ellipsis')[] = [1];
    if (current > 3) pages.push('ellipsis');
    const start = Math.max(2, current - 1);
    const end = Math.min(total - 1, current + 1);
    for (let i = start; i <= end; i++) pages.push(i);
    if (current < total - 2) pages.push('ellipsis');
    if (total > 1) pages.push(total);
    return pages;
}

const pageBtn: React.CSSProperties = {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    minWidth: '28px',
    height: '28px',
    padding: '0 0.4rem',
    border: '1px solid var(--border)',
    borderRadius: 'var(--radius)',
    background: 'var(--surface)',
    cursor: 'pointer',
    fontSize: '0.75rem',
    color: 'var(--text-secondary)',
};

const activeBtnStyle: React.CSSProperties = {
    ...pageBtn,
    background: 'var(--primary)',
    color: '#fff',
    borderColor: 'var(--primary)',
    fontWeight: 600,
};

export default function ApiSpecsPagination({
    currentPage,
    totalPages,
    pageSize,
    totalItems,
    onPageChange,
    onPageSizeChange,
}: ApiSpecsPaginationProps) {
    if (totalPages <= 1 && totalItems <= PAGE_SIZES[0]) return null;

    const pages = getPageNumbers(currentPage, totalPages);

    return (
        <div style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: '0.35rem',
            padding: '0.75rem 0',
            marginTop: '0.5rem',
        }}>
            {/* Prev */}
            <button
                onClick={() => onPageChange(currentPage - 1)}
                disabled={currentPage <= 1}
                style={{
                    ...pageBtn,
                    opacity: currentPage <= 1 ? 0.4 : 1,
                    cursor: currentPage <= 1 ? 'not-allowed' : 'pointer',
                }}
            >
                <ChevronLeft size={14} />
            </button>

            {/* Page numbers */}
            {pages.map((p, i) =>
                p === 'ellipsis' ? (
                    <span key={`e-${i}`} style={{ padding: '0 0.25rem', color: 'var(--text-secondary)', fontSize: '0.75rem' }}>
                        ...
                    </span>
                ) : (
                    <button
                        key={p}
                        onClick={() => onPageChange(p)}
                        style={currentPage === p ? activeBtnStyle : pageBtn}
                    >
                        {p}
                    </button>
                )
            )}

            {/* Next */}
            <button
                onClick={() => onPageChange(currentPage + 1)}
                disabled={currentPage >= totalPages}
                style={{
                    ...pageBtn,
                    opacity: currentPage >= totalPages ? 0.4 : 1,
                    cursor: currentPage >= totalPages ? 'not-allowed' : 'pointer',
                }}
            >
                <ChevronRight size={14} />
            </button>

            {/* Separator */}
            <div style={{ width: '1px', height: '20px', background: 'var(--border)', margin: '0 0.5rem' }} />

            {/* Page size selector */}
            <select
                value={pageSize}
                onChange={e => onPageSizeChange(Number(e.target.value))}
                style={{
                    padding: '0.3rem 0.5rem',
                    background: 'var(--surface)',
                    border: '1px solid var(--border)',
                    borderRadius: 'var(--radius)',
                    color: 'var(--text-secondary)',
                    fontSize: '0.75rem',
                    cursor: 'pointer',
                }}
            >
                {PAGE_SIZES.map(s => (
                    <option key={s} value={s}>{s}/page</option>
                ))}
            </select>
        </div>
    );
}
