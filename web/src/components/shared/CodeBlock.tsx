'use client';
import React, { Suspense } from 'react';
import dynamic from 'next/dynamic';

const SyntaxHighlighter = dynamic(
    () => import('react-syntax-highlighter/dist/esm/prism').then(mod => mod.default || mod),
    { ssr: false }
);

const vscDarkPlusPromise = import('react-syntax-highlighter/dist/esm/styles/prism').then(
    mod => (mod as Record<string, unknown>).vscDarkPlus
);

interface CodeBlockProps {
    code: string;
    language?: string;
    maxHeight?: string;
}

function CodeBlockFallback({ code }: { code: string }) {
    return (
        <pre style={{
            background: '#1e1e1e', color: '#d4d4d4',
            padding: '1rem', borderRadius: 'var(--radius)',
            overflow: 'auto', fontSize: '0.85rem',
        }}>
            {code}
        </pre>
    );
}

export const CodeBlock = React.memo(function CodeBlock({ code, language = 'typescript', maxHeight = '400px' }: CodeBlockProps) {
    const [style, setStyle] = React.useState<Record<string, unknown> | null>(null);

    React.useEffect(() => {
        vscDarkPlusPromise.then(s => setStyle(s as Record<string, unknown>));
    }, []);

    if (!style) {
        return <CodeBlockFallback code={code} />;
    }

    return (
        <Suspense fallback={<CodeBlockFallback code={code} />}>
            <div style={{ maxHeight, overflow: 'auto' }}>
                {/* eslint-disable-next-line @typescript-eslint/no-explicit-any */}
                <SyntaxHighlighter language={language} style={style as any} customStyle={{
                    margin: 0, borderRadius: 'var(--radius)', fontSize: '0.85rem',
                }}>
                    {code}
                </SyntaxHighlighter>
            </div>
        </Suspense>
    );
});
