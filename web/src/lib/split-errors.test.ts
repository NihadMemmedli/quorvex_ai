import { describe, expect, it } from 'vitest';
import { parseSplitErrorText } from './split-errors';

describe('split error parsing', () => {
    it('uses JSON detail and adds deployment hints', () => {
        const message = parseSplitErrorText(
            JSON.stringify({ detail: 'Provider returned HTTP 401: invalid API key' }),
            'Fallback',
        );

        expect(message).toContain('Provider returned HTTP 401');
        expect(message).toContain('Check the AI provider and API key saved in Settings.');
    });

    it('uses plain text errors and adds network hints', () => {
        const message = parseSplitErrorText('DNS lookup timed out while connecting to provider', 'Fallback');

        expect(message).toContain('DNS lookup timed out');
        expect(message).toContain('Check server network, proxy, DNS, and certificate access');
    });

    it('falls back for empty or HTML error bodies', () => {
        expect(parseSplitErrorText('', 'Fallback message')).toBe('Fallback message');
        expect(parseSplitErrorText('<html>Bad gateway</html>', 'Fallback message')).toBe('Fallback message');
    });
});
