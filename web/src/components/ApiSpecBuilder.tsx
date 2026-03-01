'use client';

import { useState, useEffect, useCallback } from 'react';
import dynamic from 'next/dynamic';
import { Plus, Trash2, ArrowUp, ArrowDown, ChevronDown, ChevronRight } from 'lucide-react';

const CodeEditor = dynamic(() => import('@/components/CodeEditor'), { ssr: false });

// ========== Types ==========

type HttpMethod = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
type AuthType = 'none' | 'bearer' | 'basic' | 'apikey';
type AssertionType = 'status_code' | 'body_contains' | 'body_has_property' | 'body_property_equals' | 'response_time' | 'header_contains';

interface HeaderEntry {
    id: string;
    key: string;
    value: string;
}

interface RequestStep {
    id: string;
    kind: 'request';
    method: HttpMethod;
    path: string;
    headers: HeaderEntry[];
    body: string;
}

interface AssertionStep {
    id: string;
    kind: 'assertion';
    assertionType: AssertionType;
    value: string;
}

type ApiStep = RequestStep | AssertionStep;

interface ApiSpecBuilderProps {
    content: string;
    onChange: (content: string) => void;
}

// ========== Constants ==========

const HTTP_METHODS: HttpMethod[] = ['GET', 'POST', 'PUT', 'PATCH', 'DELETE'];

const METHOD_COLORS: Record<HttpMethod, { bg: string; color: string }> = {
    GET: { bg: 'rgba(16, 185, 129, 0.1)', color: '#10b981' },
    POST: { bg: 'rgba(59, 130, 246, 0.1)', color: '#3b82f6' },
    PUT: { bg: 'rgba(245, 158, 11, 0.1)', color: '#f59e0b' },
    PATCH: { bg: 'rgba(139, 92, 246, 0.1)', color: '#8b5cf6' },
    DELETE: { bg: 'rgba(239, 68, 68, 0.1)', color: '#ef4444' },
};

const ASSERTION_TYPES: { value: AssertionType; label: string }[] = [
    { value: 'status_code', label: 'Status Code' },
    { value: 'body_contains', label: 'Body Contains' },
    { value: 'body_has_property', label: 'Body Has Property' },
    { value: 'body_property_equals', label: 'Body Property Equals' },
    { value: 'response_time', label: 'Response Time (ms)' },
    { value: 'header_contains', label: 'Header Contains' },
];

const AUTH_TYPES: { value: AuthType; label: string }[] = [
    { value: 'none', label: 'None' },
    { value: 'bearer', label: 'Bearer Token' },
    { value: 'basic', label: 'Basic Auth' },
    { value: 'apikey', label: 'API Key Header' },
];

// ========== Helpers ==========

function genId(): string {
    return Math.random().toString(36).substr(2, 9);
}

function methodHasBody(method: HttpMethod): boolean {
    return method === 'POST' || method === 'PUT' || method === 'PATCH';
}

// ========== Parser ==========

function parseMarkdown(md: string): {
    testName: string;
    baseUrl: string;
    authType: AuthType;
    authValue: string;
    authHeaderName: string;
    steps: ApiStep[];
    expectedOutcome: string;
} {
    const lines = md.split('\n');
    let testName = '';
    let baseUrl = '';
    let authType: AuthType = 'none';
    let authValue = '';
    let authHeaderName = '';
    const steps: ApiStep[] = [];
    let expectedOutcome = '';
    let inExpectedOutcome = false;
    let inCodeBlock = false;
    let codeBlockContent = '';
    let pendingRequestStep: RequestStep | null = null;

    for (let i = 0; i < lines.length; i++) {
        const line = lines[i];
        const trimmed = line.trim();

        // Handle code blocks within steps
        if (inCodeBlock) {
            if (trimmed === '```') {
                // End of code block - attach to pending request
                if (pendingRequestStep) {
                    pendingRequestStep.body = codeBlockContent.trim();
                    steps.push(pendingRequestStep);
                    pendingRequestStep = null;
                }
                inCodeBlock = false;
                codeBlockContent = '';
            } else {
                codeBlockContent += (codeBlockContent ? '\n' : '') + line;
            }
            continue;
        }

        if (inExpectedOutcome) {
            expectedOutcome += (expectedOutcome ? '\n' : '') + line;
            continue;
        }

        // # Test: Name
        if (trimmed.startsWith('# Test:') || trimmed.startsWith('# ')) {
            testName = trimmed.replace(/^#\s*Test:\s*/, '').replace(/^#\s*/, '').trim();
            continue;
        }

        // ## Type: API (skip, preserved in serialization)
        if (trimmed.startsWith('## Type:')) continue;

        // ## Base URL: ...
        if (trimmed.startsWith('## Base URL:')) {
            baseUrl = trimmed.replace('## Base URL:', '').trim();
            continue;
        }

        // ## Auth: ...
        if (trimmed.startsWith('## Auth:')) {
            const authStr = trimmed.replace('## Auth:', '').trim();
            if (authStr.toLowerCase() === 'none' || !authStr) {
                authType = 'none';
            } else if (authStr.startsWith('Bearer ')) {
                authType = 'bearer';
                authValue = authStr.replace('Bearer ', '');
            } else if (authStr.startsWith('Basic ')) {
                authType = 'basic';
                authValue = authStr.replace('Basic ', '');
            } else if (authStr.includes(':')) {
                authType = 'apikey';
                const colonIdx = authStr.indexOf(':');
                authHeaderName = authStr.substring(0, colonIdx).trim();
                authValue = authStr.substring(colonIdx + 1).trim();
            }
            continue;
        }

        // ## Steps (section header, skip)
        if (trimmed === '## Steps') continue;

        // ## Expected Outcome
        if (trimmed === '## Expected Outcome') {
            inExpectedOutcome = true;
            continue;
        }

        // Numbered steps
        const stepMatch = trimmed.match(/^(\d+)\.\s*(.*)/);
        if (stepMatch) {
            const stepText = stepMatch[2];

            // Check for Verify/Assert steps
            if (/^Verify\s/i.test(stepText)) {
                const assertion = parseAssertionText(stepText);
                steps.push({
                    id: genId(),
                    kind: 'assertion',
                    ...assertion,
                });
                continue;
            }

            // Check for HTTP method steps
            const httpMatch = stepText.match(/^(GET|POST|PUT|PATCH|DELETE)\s+(\S+)(.*)/i);
            if (httpMatch) {
                const method = httpMatch[1].toUpperCase() as HttpMethod;
                const path = httpMatch[2];
                const rest = httpMatch[3].trim();

                let headers: HeaderEntry[] = [];
                let body = '';

                // Parse "with headers {...} with body {...}" or "with body {...}" or "with body:"
                let remaining = rest;

                // Extract headers
                const headersMatch = remaining.match(/with headers\s*(\{[^}]*\})/i);
                if (headersMatch) {
                    try {
                        const parsed = JSON.parse(headersMatch[1]);
                        headers = Object.entries(parsed).map(([k, v]) => ({
                            id: genId(),
                            key: k,
                            value: String(v),
                        }));
                    } catch { /* ignore parse errors */ }
                    remaining = remaining.replace(headersMatch[0], '').trim();
                }

                // Extract body
                const bodyInlineMatch = remaining.match(/with body\s+(.+)/i);
                const bodyBlockMatch = remaining.match(/with body:\s*$/i);

                if (bodyBlockMatch) {
                    // Multi-line body: next lines should be a code block
                    // Look ahead for ```json or ```
                    const nextLine = i + 1 < lines.length ? lines[i + 1].trim() : '';
                    if (nextLine.startsWith('```')) {
                        inCodeBlock = true;
                        codeBlockContent = '';
                        i++; // skip the ``` line
                        pendingRequestStep = {
                            id: genId(),
                            kind: 'request',
                            method,
                            path,
                            headers,
                            body: '',
                        };
                        continue;
                    }
                } else if (bodyInlineMatch) {
                    body = bodyInlineMatch[1].trim();
                    // Try to pretty-print if it's valid JSON
                    try {
                        const parsed = JSON.parse(body);
                        body = JSON.stringify(parsed, null, 2);
                    } catch { /* keep as-is */ }
                }

                steps.push({
                    id: genId(),
                    kind: 'request',
                    method,
                    path,
                    headers,
                    body,
                });
                continue;
            }
        }
    }

    return { testName, baseUrl, authType, authValue, authHeaderName, steps, expectedOutcome: expectedOutcome.trim() };
}

function parseAssertionText(text: string): { assertionType: AssertionType; value: string } {
    const lower = text.toLowerCase();
    if (lower.includes('response status is') || lower.includes('status code is') || lower.includes('response status code is')) {
        const match = text.match(/(?:status(?:\s+code)?\s+is)\s+(\S+)/i);
        return { assertionType: 'status_code', value: match?.[1] || '' };
    }
    if (lower.includes('response body contains')) {
        const match = text.match(/body contains\s+"?([^"]*)"?/i);
        return { assertionType: 'body_contains', value: match?.[1] || '' };
    }
    if (lower.includes('body has property')) {
        const match = text.match(/has property\s+"?([^"]*)"?/i);
        return { assertionType: 'body_has_property', value: match?.[1] || '' };
    }
    if (lower.includes('body property')) {
        const match = text.match(/body property\s+"?([^"]*)"?/i);
        return { assertionType: 'body_property_equals', value: match?.[1] || '' };
    }
    if (lower.includes('response time')) {
        const match = text.match(/less than\s+(\d+)/i);
        return { assertionType: 'response_time', value: match?.[1] || '' };
    }
    if (lower.includes('header contains')) {
        const match = text.match(/header contains\s+"?([^"]*)"?/i);
        return { assertionType: 'header_contains', value: match?.[1] || '' };
    }
    // Fallback
    return { assertionType: 'status_code', value: text.replace(/^Verify\s+/i, '') };
}

// ========== Serializer ==========

function serializeMarkdown(
    testName: string,
    baseUrl: string,
    authType: AuthType,
    authValue: string,
    authHeaderName: string,
    steps: ApiStep[],
    expectedOutcome: string,
): string {
    let md = '';

    md += `# Test: ${testName || 'API Test Name'}\n\n`;
    md += `## Type: API\n`;
    md += `## Base URL: ${baseUrl || 'https://api.example.com'}\n`;

    // Auth line
    if (authType === 'none') {
        md += `## Auth: None\n`;
    } else if (authType === 'bearer') {
        md += `## Auth: Bearer ${authValue}\n`;
    } else if (authType === 'basic') {
        md += `## Auth: Basic ${authValue}\n`;
    } else if (authType === 'apikey') {
        md += `## Auth: ${authHeaderName || 'X-API-Key'}: ${authValue}\n`;
    }

    md += `\n## Steps\n`;

    steps.forEach((step, index) => {
        const num = index + 1;
        if (step.kind === 'request') {
            let line = `${num}. ${step.method} ${step.path || '/'}`;

            // Headers
            if (step.headers.length > 0) {
                const headerObj: Record<string, string> = {};
                step.headers.forEach(h => {
                    if (h.key.trim()) headerObj[h.key] = h.value;
                });
                if (Object.keys(headerObj).length > 0) {
                    line += ` with headers ${JSON.stringify(headerObj)}`;
                }
            }

            // Body
            const body = step.body.trim();
            if (body) {
                const isMultiline = body.includes('\n') || body.length > 120;
                if (isMultiline) {
                    line += ` with body:`;
                    md += `${line}\n`;
                    md += `    \`\`\`json\n`;
                    // Indent body lines
                    body.split('\n').forEach(bLine => {
                        md += `    ${bLine}\n`;
                    });
                    md += `    \`\`\`\n`;
                    return; // skip the normal md += line below
                } else {
                    line += ` with body ${body}`;
                }
            }

            md += `${line}\n`;
        } else {
            // Assertion step
            md += `${num}. ${serializeAssertion(step)}\n`;
        }
    });

    if (expectedOutcome.trim()) {
        md += `\n## Expected Outcome\n${expectedOutcome.trim()}\n`;
    }

    return md;
}

function serializeAssertion(step: AssertionStep): string {
    switch (step.assertionType) {
        case 'status_code':
            return `Verify response status is ${step.value}`;
        case 'body_contains':
            return `Verify response body contains "${step.value}"`;
        case 'body_has_property':
            return `Verify response body has property "${step.value}"`;
        case 'body_property_equals':
            return `Verify response body property "${step.value}"`;
        case 'response_time':
            return `Verify response time is less than ${step.value}ms`;
        case 'header_contains':
            return `Verify response header contains "${step.value}"`;
        default:
            return `Verify ${step.value}`;
    }
}

// ========== Component ==========

export default function ApiSpecBuilder({ content, onChange }: ApiSpecBuilderProps) {
    const [testName, setTestName] = useState('');
    const [baseUrl, setBaseUrl] = useState('');
    const [authType, setAuthType] = useState<AuthType>('none');
    const [authValue, setAuthValue] = useState('');
    const [authHeaderName, setAuthHeaderName] = useState('');
    const [steps, setSteps] = useState<ApiStep[]>([]);
    const [expectedOutcome, setExpectedOutcome] = useState('');
    const [expandedHeaders, setExpandedHeaders] = useState<Record<string, boolean>>({});

    // Parse on mount
    useEffect(() => {
        const parsed = parseMarkdown(content);
        setTestName(parsed.testName);
        setBaseUrl(parsed.baseUrl);
        setAuthType(parsed.authType);
        setAuthValue(parsed.authValue);
        setAuthHeaderName(parsed.authHeaderName);
        setSteps(parsed.steps);
        setExpectedOutcome(parsed.expectedOutcome);
    }, []);

    const serialize = useCallback((
        name: string, url: string, aType: AuthType, aVal: string, aHeader: string,
        stps: ApiStep[], outcome: string,
    ) => {
        return serializeMarkdown(name, url, aType, aVal, aHeader, stps, outcome);
    }, []);

    const emitChange = useCallback((
        name: string, url: string, aType: AuthType, aVal: string, aHeader: string,
        stps: ApiStep[], outcome: string,
    ) => {
        onChange(serialize(name, url, aType, aVal, aHeader, stps, outcome));
    }, [onChange, serialize]);

    // Field updaters
    const updateTestName = (val: string) => {
        setTestName(val);
        emitChange(val, baseUrl, authType, authValue, authHeaderName, steps, expectedOutcome);
    };

    const updateBaseUrl = (val: string) => {
        setBaseUrl(val);
        emitChange(testName, val, authType, authValue, authHeaderName, steps, expectedOutcome);
    };

    const updateAuthType = (val: AuthType) => {
        setAuthType(val);
        const newVal = val === 'none' ? '' : authValue;
        emitChange(testName, baseUrl, val, newVal, authHeaderName, steps, expectedOutcome);
    };

    const updateAuthValue = (val: string) => {
        setAuthValue(val);
        emitChange(testName, baseUrl, authType, val, authHeaderName, steps, expectedOutcome);
    };

    const updateAuthHeaderName = (val: string) => {
        setAuthHeaderName(val);
        emitChange(testName, baseUrl, authType, authValue, val, steps, expectedOutcome);
    };

    const updateExpectedOutcome = (val: string) => {
        setExpectedOutcome(val);
        emitChange(testName, baseUrl, authType, authValue, authHeaderName, steps, val);
    };

    const updateSteps = (newSteps: ApiStep[]) => {
        setSteps(newSteps);
        emitChange(testName, baseUrl, authType, authValue, authHeaderName, newSteps, expectedOutcome);
    };

    // Step operations
    const addRequestStep = () => {
        const newStep: RequestStep = {
            id: genId(),
            kind: 'request',
            method: 'GET',
            path: '/',
            headers: [],
            body: '',
        };
        updateSteps([...steps, newStep]);
    };

    const addAssertionStep = () => {
        const newStep: AssertionStep = {
            id: genId(),
            kind: 'assertion',
            assertionType: 'status_code',
            value: '200',
        };
        updateSteps([...steps, newStep]);
    };

    const removeStep = (index: number) => {
        updateSteps(steps.filter((_, i) => i !== index));
    };

    const moveStep = (index: number, direction: 'up' | 'down') => {
        if (direction === 'up' && index === 0) return;
        if (direction === 'down' && index === steps.length - 1) return;
        const newSteps = [...steps];
        const swapIndex = direction === 'up' ? index - 1 : index + 1;
        [newSteps[index], newSteps[swapIndex]] = [newSteps[swapIndex], newSteps[index]];
        updateSteps(newSteps);
    };

    const updateRequestField = (index: number, field: keyof RequestStep, value: any) => {
        const newSteps = [...steps];
        const step = { ...newSteps[index] } as RequestStep;
        (step as any)[field] = value;
        newSteps[index] = step;
        updateSteps(newSteps);
    };

    const updateAssertionField = (index: number, field: keyof AssertionStep, value: any) => {
        const newSteps = [...steps];
        const step = { ...newSteps[index] } as AssertionStep;
        (step as any)[field] = value;
        newSteps[index] = step;
        updateSteps(newSteps);
    };

    // Header operations
    const addHeader = (stepIndex: number) => {
        const newSteps = [...steps];
        const step = { ...newSteps[stepIndex] } as RequestStep;
        step.headers = [...step.headers, { id: genId(), key: '', value: '' }];
        newSteps[stepIndex] = step;
        updateSteps(newSteps);
    };

    const removeHeader = (stepIndex: number, headerIndex: number) => {
        const newSteps = [...steps];
        const step = { ...newSteps[stepIndex] } as RequestStep;
        step.headers = step.headers.filter((_, i) => i !== headerIndex);
        newSteps[stepIndex] = step;
        updateSteps(newSteps);
    };

    const updateHeader = (stepIndex: number, headerIndex: number, field: 'key' | 'value', val: string) => {
        const newSteps = [...steps];
        const step = { ...newSteps[stepIndex] } as RequestStep;
        step.headers = [...step.headers];
        step.headers[headerIndex] = { ...step.headers[headerIndex], [field]: val };
        newSteps[stepIndex] = step;
        updateSteps(newSteps);
    };

    const toggleHeaders = (stepId: string) => {
        setExpandedHeaders(prev => ({ ...prev, [stepId]: !prev[stepId] }));
    };

    // ========== Render ==========

    const inputStyle = {
        padding: '0.5rem 0.75rem',
        background: 'var(--background)',
        border: '1px solid var(--border)',
        borderRadius: 'var(--radius)',
        color: 'var(--text-primary)',
        fontSize: '0.875rem',
        width: '100%',
    };

    const labelStyle = {
        display: 'block' as const,
        fontSize: '0.8rem',
        fontWeight: 500,
        marginBottom: '0.4rem',
        color: 'var(--text-secondary)',
    };

    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>
            {/* Test Name */}
            <div>
                <label style={labelStyle}>Test Name</label>
                <input
                    type="text"
                    value={testName}
                    onChange={e => updateTestName(e.target.value)}
                    placeholder="e.g., User CRUD Operations"
                    style={inputStyle}
                />
            </div>

            {/* Base URL */}
            <div>
                <label style={labelStyle}>Base URL</label>
                <input
                    type="text"
                    value={baseUrl}
                    onChange={e => updateBaseUrl(e.target.value)}
                    placeholder="https://api.example.com"
                    style={{ ...inputStyle, fontFamily: 'monospace' }}
                />
            </div>

            {/* Auth */}
            <div>
                <label style={labelStyle}>Authentication</label>
                <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center', flexWrap: 'wrap' }}>
                    <select
                        value={authType}
                        onChange={e => updateAuthType(e.target.value as AuthType)}
                        style={{
                            ...inputStyle,
                            width: 'auto',
                            minWidth: '140px',
                            cursor: 'pointer',
                        }}
                    >
                        {AUTH_TYPES.map(at => (
                            <option key={at.value} value={at.value}>{at.label}</option>
                        ))}
                    </select>
                    {authType === 'apikey' && (
                        <input
                            type="text"
                            value={authHeaderName}
                            onChange={e => updateAuthHeaderName(e.target.value)}
                            placeholder="Header name (e.g., X-API-Key)"
                            style={{ ...inputStyle, flex: 1, minWidth: '160px' }}
                        />
                    )}
                    {authType !== 'none' && (
                        <input
                            type="text"
                            value={authValue}
                            onChange={e => updateAuthValue(e.target.value)}
                            placeholder={authType === 'bearer' ? '{{API_TOKEN}}' : authType === 'basic' ? 'user:password or {{BASIC_CRED}}' : '{{API_KEY}}'}
                            style={{ ...inputStyle, flex: 2, minWidth: '200px', fontFamily: 'monospace' }}
                        />
                    )}
                </div>
            </div>

            {/* Steps */}
            <div>
                <label style={labelStyle}>Steps</label>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                    {steps.map((step, index) => (
                        <div key={step.id} style={{
                            border: '1px solid var(--border)',
                            borderRadius: 'var(--radius)',
                            overflow: 'hidden',
                            background: step.kind === 'request'
                                ? METHOD_COLORS[(step as RequestStep).method].bg
                                : 'rgba(139, 92, 246, 0.05)',
                        }}>
                            {/* Step header row */}
                            <div style={{
                                display: 'flex',
                                alignItems: 'center',
                                gap: '0.5rem',
                                padding: '0.5rem 0.75rem',
                            }}>
                                {/* Step number */}
                                <span style={{
                                    width: '22px',
                                    height: '22px',
                                    borderRadius: '50%',
                                    background: 'rgba(255,255,255,0.1)',
                                    display: 'flex',
                                    alignItems: 'center',
                                    justifyContent: 'center',
                                    fontSize: '0.75rem',
                                    fontWeight: 600,
                                    flexShrink: 0,
                                }}>
                                    {index + 1}
                                </span>

                                {step.kind === 'request' ? (
                                    <>
                                        {/* Method dropdown */}
                                        <select
                                            value={(step as RequestStep).method}
                                            onChange={e => updateRequestField(index, 'method', e.target.value)}
                                            style={{
                                                padding: '0.3rem 0.5rem',
                                                background: METHOD_COLORS[(step as RequestStep).method].bg,
                                                color: METHOD_COLORS[(step as RequestStep).method].color,
                                                border: `1px solid ${METHOD_COLORS[(step as RequestStep).method].color}40`,
                                                borderRadius: 'var(--radius)',
                                                fontWeight: 700,
                                                fontSize: '0.75rem',
                                                cursor: 'pointer',
                                                width: 'auto',
                                            }}
                                        >
                                            {HTTP_METHODS.map(m => (
                                                <option key={m} value={m}>{m}</option>
                                            ))}
                                        </select>
                                        {/* Path input */}
                                        <input
                                            type="text"
                                            value={(step as RequestStep).path}
                                            onChange={e => updateRequestField(index, 'path', e.target.value)}
                                            placeholder="/endpoint"
                                            style={{
                                                flex: 1,
                                                padding: '0.3rem 0.5rem',
                                                background: 'transparent',
                                                border: '1px solid var(--border)',
                                                borderRadius: 'var(--radius)',
                                                color: 'var(--text-primary)',
                                                fontFamily: 'monospace',
                                                fontSize: '0.85rem',
                                            }}
                                        />
                                    </>
                                ) : (
                                    <>
                                        {/* Assertion type */}
                                        <select
                                            value={(step as AssertionStep).assertionType}
                                            onChange={e => updateAssertionField(index, 'assertionType', e.target.value)}
                                            style={{
                                                padding: '0.3rem 0.5rem',
                                                background: 'rgba(139, 92, 246, 0.1)',
                                                color: '#8b5cf6',
                                                border: '1px solid rgba(139, 92, 246, 0.3)',
                                                borderRadius: 'var(--radius)',
                                                fontWeight: 600,
                                                fontSize: '0.75rem',
                                                cursor: 'pointer',
                                                width: 'auto',
                                            }}
                                        >
                                            {ASSERTION_TYPES.map(at => (
                                                <option key={at.value} value={at.value}>{at.label}</option>
                                            ))}
                                        </select>
                                        {/* Assertion value */}
                                        <input
                                            type="text"
                                            value={(step as AssertionStep).value}
                                            onChange={e => updateAssertionField(index, 'value', e.target.value)}
                                            placeholder={
                                                (step as AssertionStep).assertionType === 'status_code' ? '200'
                                                : (step as AssertionStep).assertionType === 'response_time' ? '500'
                                                : 'value'
                                            }
                                            style={{
                                                flex: 1,
                                                padding: '0.3rem 0.5rem',
                                                background: 'transparent',
                                                border: '1px solid var(--border)',
                                                borderRadius: 'var(--radius)',
                                                color: 'var(--text-primary)',
                                                fontFamily: 'monospace',
                                                fontSize: '0.85rem',
                                            }}
                                        />
                                    </>
                                )}

                                {/* Move / Delete buttons */}
                                <div style={{ display: 'flex', gap: '0.15rem', flexShrink: 0 }}>
                                    <button onClick={() => moveStep(index, 'up')} disabled={index === 0}
                                        className="btn-icon" title="Move Up" style={{ padding: '0.2rem' }}>
                                        <ArrowUp size={13} />
                                    </button>
                                    <button onClick={() => moveStep(index, 'down')} disabled={index === steps.length - 1}
                                        className="btn-icon" title="Move Down" style={{ padding: '0.2rem' }}>
                                        <ArrowDown size={13} />
                                    </button>
                                    <button onClick={() => removeStep(index)}
                                        className="btn-icon" title="Delete Step" style={{ padding: '0.2rem', color: 'var(--danger)' }}>
                                        <Trash2 size={13} />
                                    </button>
                                </div>
                            </div>

                            {/* Request-specific sections: headers + body */}
                            {step.kind === 'request' && (
                                <div style={{ padding: '0 0.75rem 0.5rem' }}>
                                    {/* Headers toggle */}
                                    <button
                                        onClick={() => toggleHeaders(step.id)}
                                        style={{
                                            display: 'flex',
                                            alignItems: 'center',
                                            gap: '0.3rem',
                                            background: 'none',
                                            border: 'none',
                                            color: 'var(--text-secondary)',
                                            cursor: 'pointer',
                                            fontSize: '0.75rem',
                                            padding: '0.25rem 0',
                                            marginBottom: '0.25rem',
                                        }}
                                    >
                                        {expandedHeaders[step.id] ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                                        Headers
                                        {(step as RequestStep).headers.length > 0 && (
                                            <span style={{
                                                background: 'rgba(59, 130, 246, 0.15)',
                                                color: '#3b82f6',
                                                padding: '0 0.35rem',
                                                borderRadius: '999px',
                                                fontSize: '0.65rem',
                                                fontWeight: 600,
                                            }}>
                                                {(step as RequestStep).headers.length}
                                            </span>
                                        )}
                                    </button>

                                    {/* Headers list */}
                                    {expandedHeaders[step.id] && (
                                        <div style={{
                                            display: 'flex', flexDirection: 'column', gap: '0.3rem',
                                            marginBottom: '0.5rem', paddingLeft: '0.5rem',
                                        }}>
                                            {(step as RequestStep).headers.map((header, hIdx) => (
                                                <div key={header.id} style={{ display: 'flex', gap: '0.3rem', alignItems: 'center' }}>
                                                    <input
                                                        type="text"
                                                        value={header.key}
                                                        onChange={e => updateHeader(index, hIdx, 'key', e.target.value)}
                                                        placeholder="Header name"
                                                        style={{
                                                            flex: 1,
                                                            padding: '0.25rem 0.5rem',
                                                            background: 'var(--background)',
                                                            border: '1px solid var(--border)',
                                                            borderRadius: 'var(--radius)',
                                                            color: 'var(--text-primary)',
                                                            fontSize: '0.75rem',
                                                            fontFamily: 'monospace',
                                                        }}
                                                    />
                                                    <span style={{ color: 'var(--text-secondary)', fontSize: '0.75rem' }}>:</span>
                                                    <input
                                                        type="text"
                                                        value={header.value}
                                                        onChange={e => updateHeader(index, hIdx, 'value', e.target.value)}
                                                        placeholder="Header value"
                                                        style={{
                                                            flex: 2,
                                                            padding: '0.25rem 0.5rem',
                                                            background: 'var(--background)',
                                                            border: '1px solid var(--border)',
                                                            borderRadius: 'var(--radius)',
                                                            color: 'var(--text-primary)',
                                                            fontSize: '0.75rem',
                                                            fontFamily: 'monospace',
                                                        }}
                                                    />
                                                    <button
                                                        onClick={() => removeHeader(index, hIdx)}
                                                        className="btn-icon"
                                                        style={{ padding: '0.15rem', color: 'var(--danger)' }}
                                                    >
                                                        <Trash2 size={11} />
                                                    </button>
                                                </div>
                                            ))}
                                            <button
                                                onClick={() => addHeader(index)}
                                                style={{
                                                    display: 'flex',
                                                    alignItems: 'center',
                                                    gap: '0.3rem',
                                                    background: 'none',
                                                    border: '1px dashed var(--border)',
                                                    borderRadius: 'var(--radius)',
                                                    color: 'var(--text-secondary)',
                                                    cursor: 'pointer',
                                                    fontSize: '0.7rem',
                                                    padding: '0.25rem 0.5rem',
                                                }}
                                            >
                                                <Plus size={11} /> Add Header
                                            </button>
                                        </div>
                                    )}

                                    {/* Body editor (only for POST/PUT/PATCH) */}
                                    {methodHasBody((step as RequestStep).method) && (
                                        <div>
                                            <label style={{
                                                display: 'block',
                                                fontSize: '0.75rem',
                                                color: 'var(--text-secondary)',
                                                marginBottom: '0.25rem',
                                            }}>
                                                Request Body (JSON)
                                            </label>
                                            <div style={{
                                                height: '200px',
                                                borderRadius: 'var(--radius)',
                                                overflow: 'hidden',
                                                border: '1px solid var(--border)',
                                            }}>
                                                <CodeEditor
                                                    value={(step as RequestStep).body}
                                                    onChange={val => updateRequestField(index, 'body', val)}
                                                    language="json"
                                                />
                                            </div>
                                        </div>
                                    )}
                                </div>
                            )}
                        </div>
                    ))}

                    {/* Add step buttons */}
                    <div style={{ display: 'flex', gap: '0.5rem', marginTop: '0.25rem' }}>
                        <button
                            onClick={addRequestStep}
                            style={{
                                flex: 1,
                                display: 'flex',
                                alignItems: 'center',
                                justifyContent: 'center',
                                gap: '0.4rem',
                                padding: '0.5rem',
                                background: 'transparent',
                                border: '1px dashed var(--border)',
                                borderRadius: 'var(--radius)',
                                color: 'var(--text-secondary)',
                                cursor: 'pointer',
                                fontSize: '0.8rem',
                            }}
                        >
                            <Plus size={14} /> Add Request
                        </button>
                        <button
                            onClick={addAssertionStep}
                            style={{
                                flex: 1,
                                display: 'flex',
                                alignItems: 'center',
                                justifyContent: 'center',
                                gap: '0.4rem',
                                padding: '0.5rem',
                                background: 'rgba(139, 92, 246, 0.05)',
                                border: '1px dashed rgba(139, 92, 246, 0.3)',
                                borderRadius: 'var(--radius)',
                                color: '#8b5cf6',
                                cursor: 'pointer',
                                fontSize: '0.8rem',
                            }}
                        >
                            <Plus size={14} /> Add Assertion
                        </button>
                    </div>
                </div>
            </div>

            {/* Expected Outcome */}
            <div>
                <label style={labelStyle}>Expected Outcome (optional)</label>
                <textarea
                    value={expectedOutcome}
                    onChange={e => updateExpectedOutcome(e.target.value)}
                    placeholder="- Endpoint returns 200&#10;- Response contains expected data"
                    style={{
                        ...inputStyle,
                        minHeight: '80px',
                        fontFamily: 'monospace',
                        resize: 'vertical',
                    }}
                />
            </div>
        </div>
    );
}
