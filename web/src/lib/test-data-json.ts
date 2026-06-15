export interface JsonValidationError {
  message: string;
  line?: number;
  column?: number;
}

export interface JsonValidationResult {
  valid: boolean;
  value: unknown;
  error?: JsonValidationError;
}

export interface JsonRepairResult {
  valid: boolean;
  content: string;
  value?: unknown;
  error?: JsonValidationError;
}

const zeroWidthPattern = /[\u200B-\u200D\u2060\uFEFF]/g;
const smartDoubleQuotes = new Set(['\u201C', '\u201D', '\u201E', '\u201F']);

export function validateJsonContent(content: string, options: { allowEmpty?: boolean } = {}): JsonValidationResult {
  const allowEmpty = options.allowEmpty ?? true;
  if (allowEmpty && !content.trim()) {
    return { valid: true, value: null };
  }

  try {
    return { valid: true, value: JSON.parse(content) };
  } catch (error) {
    return {
      valid: false,
      value: null,
      error: describeJsonParseError(content, error),
    };
  }
}

export function formatJsonContent(content: string): JsonRepairResult {
  const validation = validateJsonContent(content, { allowEmpty: false });
  if (!validation.valid) {
    return { valid: false, content, error: validation.error };
  }

  return {
    valid: true,
    content: JSON.stringify(validation.value, null, 2),
    value: validation.value,
  };
}

export function repairJsonPasteContent(content: string): JsonRepairResult {
  if (!content.trim()) {
    return { valid: true, content: '', value: null };
  }

  const repaired = removeTrailingCommas(
    normalizeNbspOutsideStrings(
      normalizeSmartQuoteDelimiters(content.replace(zeroWidthPattern, '')),
    ),
  );
  const validation = validateJsonContent(repaired, { allowEmpty: false });

  if (!validation.valid) {
    return { valid: false, content, error: validation.error };
  }

  return {
    valid: true,
    content: JSON.stringify(validation.value, null, 2),
    value: validation.value,
  };
}

function describeJsonParseError(content: string, error: unknown): JsonValidationError {
  const fallback = 'Invalid JSON';
  const rawMessage = error instanceof Error ? error.message : '';
  const position = findErrorPosition(rawMessage);

  if (position !== null) {
    const { line, column } = getLineColumn(content, position);
    return {
      message: `Invalid JSON near line ${line}, column ${column}`,
      line,
      column,
    };
  }

  const explicitLineColumn = findLineColumn(rawMessage);
  if (explicitLineColumn) {
    return {
      message: `Invalid JSON near line ${explicitLineColumn.line}, column ${explicitLineColumn.column}`,
      line: explicitLineColumn.line,
      column: explicitLineColumn.column,
    };
  }

  return { message: fallback };
}

function findErrorPosition(message: string) {
  const match = message.match(/position\s+(\d+)/i);
  return match ? Number(match[1]) : null;
}

function findLineColumn(message: string) {
  const match = message.match(/line\s+(\d+)\s+column\s+(\d+)/i);
  return match ? { line: Number(match[1]), column: Number(match[2]) } : null;
}

function getLineColumn(content: string, position: number) {
  const prefix = content.slice(0, Math.max(0, position));
  const lines = prefix.split(/\n/);
  return {
    line: lines.length,
    column: lines[lines.length - 1].length + 1,
  };
}

function normalizeSmartQuoteDelimiters(content: string) {
  let output = '';
  let inString = false;
  let delimiter: '"' | 'smart' | null = null;
  let escaped = false;

  for (const char of content) {
    const isSmartQuote = smartDoubleQuotes.has(char);

    if (!inString && (char === '"' || isSmartQuote)) {
      output += '"';
      inString = true;
      delimiter = isSmartQuote ? 'smart' : '"';
      escaped = false;
      continue;
    }

    if (inString) {
      if (escaped) {
        output += char;
        escaped = false;
        continue;
      }

      if (char === '\\') {
        output += char;
        escaped = true;
        continue;
      }

      if ((delimiter === '"' && char === '"') || (delimiter === 'smart' && isSmartQuote)) {
        output += '"';
        inString = false;
        delimiter = null;
        continue;
      }
    }

    output += char;
  }

  return output;
}

function normalizeNbspOutsideStrings(content: string) {
  return transformOutsideStrings(content, char => (char === '\u00A0' ? ' ' : char));
}

function removeTrailingCommas(content: string) {
  let output = '';
  let inString = false;
  let escaped = false;

  for (let index = 0; index < content.length; index += 1) {
    const char = content[index];

    if (inString) {
      output += char;
      if (escaped) {
        escaped = false;
      } else if (char === '\\') {
        escaped = true;
      } else if (char === '"') {
        inString = false;
      }
      continue;
    }

    if (char === '"') {
      output += char;
      inString = true;
      escaped = false;
      continue;
    }

    if (char === ',') {
      let cursor = index + 1;
      while (cursor < content.length && /\s/.test(content[cursor])) cursor += 1;
      if (content[cursor] === '}' || content[cursor] === ']') {
        continue;
      }
    }

    output += char;
  }

  return output;
}

function transformOutsideStrings(content: string, transform: (char: string) => string) {
  let output = '';
  let inString = false;
  let escaped = false;

  for (const char of content) {
    if (inString) {
      output += char;
      if (escaped) {
        escaped = false;
      } else if (char === '\\') {
        escaped = true;
      } else if (char === '"') {
        inString = false;
      }
      continue;
    }

    if (char === '"') {
      output += char;
      inString = true;
      escaped = false;
      continue;
    }

    output += transform(char);
  }

  return output;
}
