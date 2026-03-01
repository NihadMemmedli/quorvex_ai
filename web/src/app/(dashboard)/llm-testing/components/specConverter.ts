export interface VisualSpec {
    name: string;
    description: string;
    systemPrompt: string;
    defaults: { temperature?: number; max_tokens?: number; [key: string]: any };
    testCases: VisualTestCase[];
}

export interface VisualTestCase {
    id: string;
    name: string;
    inputPrompt: string;
    expectedOutput: string;
    context: string[];
    assertions: VisualAssertion[];
    metrics: Record<string, number>;
}

export interface VisualAssertion {
    type: string;
    value: string;
}

/**
 * Parse a markdown LLM test spec into a VisualSpec structure.
 */
export function markdownToVisualSpec(md: string): VisualSpec {
    const spec: VisualSpec = {
        name: '',
        description: '',
        systemPrompt: '',
        defaults: {},
        testCases: [],
    };

    // Extract suite name from title
    const titleMatch = md.match(/^#\s+(?:LLM Test Suite:\s*)?(.+)$/m);
    if (titleMatch) {
        spec.name = titleMatch[1].trim();
    }

    // Split into top-level sections by ## headers
    const sections = splitSections(md, '## ');

    for (const [header, body] of sections) {
        const h = header.toLowerCase().trim();
        if (h === 'description') {
            spec.description = body.trim();
        } else if (h === 'system prompt') {
            spec.systemPrompt = body.trim();
        } else if (h === 'defaults') {
            spec.defaults = parseDefaults(body);
        } else if (h === 'test cases') {
            spec.testCases = parseTestCases(body);
        }
    }

    return spec;
}

/**
 * Convert a VisualSpec back to valid markdown.
 */
export function visualSpecToMarkdown(spec: VisualSpec): string {
    const lines: string[] = [];

    lines.push(`# LLM Test Suite: ${spec.name}`);
    lines.push('');
    lines.push('## Description');
    lines.push(spec.description);
    lines.push('');
    lines.push('## System Prompt');
    lines.push(spec.systemPrompt);
    lines.push('');

    if (Object.keys(spec.defaults).length > 0) {
        lines.push('## Defaults');
        for (const [key, value] of Object.entries(spec.defaults)) {
            if (value !== undefined && value !== null && value !== '') {
                lines.push(`- ${key}: ${value}`);
            }
        }
        lines.push('');
    }

    if (spec.testCases.length > 0) {
        lines.push('## Test Cases');
        lines.push('');
        for (const tc of spec.testCases) {
            lines.push(`### ${tc.id}: ${tc.name}`);
            lines.push(`**Input:** ${tc.inputPrompt}`);
            lines.push(`**Expected Output:** ${tc.expectedOutput}`);
            if (tc.assertions.length > 0) {
                lines.push('**Assertions:**');
                for (const a of tc.assertions) {
                    lines.push(`- ${a.type}: ${a.value}`);
                }
            }
            lines.push('');
        }
    }

    return lines.join('\n');
}

// --- Internal helpers ---

function splitSections(md: string, prefix: string): [string, string][] {
    const result: [string, string][] = [];
    const regex = new RegExp(`^${escapeRegex(prefix)}(.+)$`, 'gm');
    const matches: { index: number; header: string }[] = [];

    let m: RegExpExecArray | null;
    while ((m = regex.exec(md)) !== null) {
        matches.push({ index: m.index, header: m[1] });
    }

    for (let i = 0; i < matches.length; i++) {
        const start = matches[i].index + prefix.length + matches[i].header.length;
        const end = i + 1 < matches.length ? matches[i + 1].index : md.length;
        const body = md.slice(start, end).replace(/^\n+/, '');
        result.push([matches[i].header, body]);
    }

    return result;
}

function escapeRegex(s: string): string {
    return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function parseDefaults(body: string): Record<string, any> {
    const defaults: Record<string, any> = {};
    const lines = body.split('\n');
    for (const line of lines) {
        const match = line.match(/^-\s+(\S+):\s*(.+)$/);
        if (match) {
            const key = match[1].trim();
            const raw = match[2].trim();
            const num = Number(raw);
            defaults[key] = isNaN(num) ? raw : num;
        }
    }
    return defaults;
}

function parseTestCases(body: string): VisualTestCase[] {
    const cases: VisualTestCase[] = [];
    const caseSections = splitSections(body, '### ');

    for (const [header, caseBody] of caseSections) {
        const idMatch = header.match(/^(TC-\d+):\s*(.+)$/);
        const id = idMatch ? idMatch[1] : header.split(':')[0]?.trim() || `TC-${cases.length + 1}`;
        const name = idMatch ? idMatch[2].trim() : header.replace(/^[^:]+:\s*/, '').trim() || header.trim();

        const inputMatch = caseBody.match(/\*\*Input:\*\*\s*([\s\S]+?)(?=\n\*\*|\n*$)/);
        const expectedMatch = caseBody.match(/\*\*Expected Output:\*\*\s*([\s\S]+?)(?=\n\*\*|\n*$)/);

        const assertions: VisualAssertion[] = [];
        const assertionBlock = caseBody.match(/\*\*Assertions:\*\*\s*\n((?:\s*-\s*.+\n?)*)/);
        if (assertionBlock) {
            const assertionLines = assertionBlock[1].split('\n');
            for (const line of assertionLines) {
                const aMatch = line.match(/^-\s+(\S+):\s*(.+)$/);
                if (aMatch) {
                    assertions.push({ type: aMatch[1].trim(), value: aMatch[2].trim() });
                }
            }
        }

        cases.push({
            id,
            name,
            inputPrompt: inputMatch ? inputMatch[1].trim() : '',
            expectedOutput: expectedMatch ? expectedMatch[1].trim() : '',
            context: [],
            assertions,
            metrics: {},
        });
    }

    return cases;
}
