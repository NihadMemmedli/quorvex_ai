export function splitErrorHint(message: string): string {
    const value = message.toLowerCase();
    if (/(api key|credential|auth|unauthorized|forbidden|401|403)/.test(value)) {
        return 'Check the AI provider and API key saved in Settings.';
    }
    if (/(http \d{3}|provider returned)/.test(value)) {
        return 'The AI provider rejected the split request. Test the same provider in Settings.';
    }
    if (/(timeout|timed out|connect|dns|enotfound|proxy|certificate|ssl|network)/.test(value)) {
        return 'Check server network, proxy, DNS, and certificate access to the AI provider.';
    }
    if (/(empty response|empty choices|no response)/.test(value)) {
        return 'The AI provider returned no usable text. Check model availability and token limits.';
    }
    return '';
}

export function parseSplitErrorPayload(payload: unknown, fallback: string): string {
    let message = fallback;
    if (typeof payload === 'string' && payload.trim()) {
        message = payload.trim();
    } else if (payload && typeof payload === 'object') {
        const data = payload as Record<string, any>;
        if (typeof data.detail === 'string' && data.detail.trim()) {
            message = data.detail.trim();
        } else if (typeof data.detail?.message === 'string' && data.detail.message.trim()) {
            message = data.detail.message.trim();
        } else if (typeof data.message === 'string' && data.message.trim()) {
            message = data.message.trim();
        }
    }

    const hint = splitErrorHint(message);
    return hint ? `${message}\n\n${hint}` : message;
}

export function parseSplitErrorText(text: string, fallback: string): string {
    const trimmed = text.trim();
    if (!trimmed) return parseSplitErrorPayload(null, fallback);
    try {
        return parseSplitErrorPayload(JSON.parse(trimmed), fallback);
    } catch {
        if (/^\s*</.test(trimmed)) {
            return parseSplitErrorPayload(null, fallback);
        }
        return parseSplitErrorPayload(trimmed, fallback);
    }
}

export async function readSplitErrorResponse(res: Response, fallback = 'Failed to split spec.'): Promise<string> {
    const fallbackMessage = fallback === 'Unknown error' || !fallback
        ? `HTTP ${res.status}${res.statusText ? ` ${res.statusText}` : ''}`
        : fallback;
    try {
        return parseSplitErrorText(await res.text(), fallbackMessage);
    } catch {
        return parseSplitErrorPayload(null, fallbackMessage);
    }
}
