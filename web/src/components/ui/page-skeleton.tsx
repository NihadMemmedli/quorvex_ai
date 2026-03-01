'use client';

import { Skeleton } from './skeleton';

interface SkeletonBlockProps {
    width: string;
    height: string;
}

function Block({ width, height }: SkeletonBlockProps) {
    return <Skeleton style={{ width, height }} />;
}

/** Header skeleton: title line + subtitle line */
function HeaderSkeleton() {
    return (
        <div style={{ marginBottom: '1.75rem', paddingBottom: '1.25rem', borderBottom: '1px solid var(--border-subtle)' }}>
            <Block width="200px" height="28px" />
            <div style={{ marginTop: '0.5rem' }}>
                <Block width="320px" height="14px" />
            </div>
        </div>
    );
}

/** List page skeleton: header + search bar + rows */
export function ListPageSkeleton({ rows = 6 }: { rows?: number }) {
    return (
        <div>
            <HeaderSkeleton />
            <div style={{ marginBottom: '1.5rem' }}>
                <Block width="100%" height="40px" />
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                {Array.from({ length: rows }).map((_, i) => (
                    <div key={i} className="card-elevated" style={{ padding: '1rem', display: 'flex', alignItems: 'center', gap: '1rem' }}>
                        <Block width="40px" height="40px" />
                        <div style={{ flex: 1 }}>
                            <Block width={`${60 + Math.random() * 30}%`} height="14px" />
                            <div style={{ marginTop: '0.5rem' }}>
                                <Block width={`${40 + Math.random() * 20}%`} height="10px" />
                            </div>
                        </div>
                        <Block width="60px" height="24px" />
                    </div>
                ))}
            </div>
        </div>
    );
}

/** Grid/card page skeleton: header + grid of card skeletons */
export function GridPageSkeleton({ cards = 6, columns = 3 }: { cards?: number; columns?: number }) {
    return (
        <div>
            <HeaderSkeleton />
            <div style={{
                display: 'grid',
                gridTemplateColumns: `repeat(${columns}, 1fr)`,
                gap: '1rem',
            }}>
                {Array.from({ length: cards }).map((_, i) => (
                    <div key={i} className="card-elevated" style={{ padding: '1.25rem' }}>
                        <Block width="80%" height="16px" />
                        <div style={{ marginTop: '0.75rem' }}>
                            <Block width="100%" height="10px" />
                        </div>
                        <div style={{ marginTop: '0.5rem' }}>
                            <Block width="60%" height="10px" />
                        </div>
                        <div style={{ marginTop: '1rem', display: 'flex', gap: '0.5rem' }}>
                            <Block width="50px" height="22px" />
                            <Block width="50px" height="22px" />
                        </div>
                    </div>
                ))}
            </div>
        </div>
    );
}

/** Form page skeleton: header + label/input rows */
export function FormPageSkeleton({ fields = 5 }: { fields?: number }) {
    return (
        <div>
            <HeaderSkeleton />
            <div className="card-elevated" style={{ padding: '1.5rem', display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
                {Array.from({ length: fields }).map((_, i) => (
                    <div key={i}>
                        <Block width="120px" height="12px" />
                        <div style={{ marginTop: '0.5rem' }}>
                            <Block width="100%" height="38px" />
                        </div>
                    </div>
                ))}
                <div style={{ marginTop: '0.5rem', display: 'flex', justifyContent: 'flex-end' }}>
                    <Block width="120px" height="38px" />
                </div>
            </div>
        </div>
    );
}

/** Dashboard/analytics skeleton: header + stat cards + chart area */
export function DashboardPageSkeleton() {
    return (
        <div>
            <HeaderSkeleton />
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '1rem', marginBottom: '1.5rem' }}>
                {Array.from({ length: 4 }).map((_, i) => (
                    <div key={i} className="card-elevated" style={{ padding: '1.25rem' }}>
                        <Block width="80px" height="10px" />
                        <div style={{ marginTop: '0.5rem' }}>
                            <Block width="50px" height="24px" />
                        </div>
                    </div>
                ))}
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: '1.5rem' }}>
                <div className="card-elevated" style={{ padding: '1.25rem', minHeight: '300px' }}>
                    <Block width="140px" height="16px" />
                    <div style={{ marginTop: '1rem' }}>
                        <Block width="100%" height="240px" />
                    </div>
                </div>
                <div className="card-elevated" style={{ padding: '1.25rem' }}>
                    <Block width="120px" height="16px" />
                    <div style={{ marginTop: '1rem', display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
                        {Array.from({ length: 4 }).map((_, i) => (
                            <Block key={i} width="100%" height="40px" />
                        ))}
                    </div>
                </div>
            </div>
        </div>
    );
}
