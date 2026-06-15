import { describe, expect, it } from 'vitest';
import { repairJsonPasteContent, validateJsonContent } from './test-data-json';

describe('test data JSON helpers', () => {
  it('accepts valid JSON', () => {
    const result = validateJsonContent('{"email":"admin@example.com","roles":["admin"]}');

    expect(result.valid).toBe(true);
    expect(result.value).toEqual({ email: 'admin@example.com', roles: ['admin'] });
  });

  it('repairs smart quote delimiters', () => {
    const result = repairJsonPasteContent('{\n  “email”: “admin@example.com”\n}');

    expect(result.valid).toBe(true);
    expect(result.content).toBe('{\n  "email": "admin@example.com"\n}');
  });

  it('repairs NBSP and zero-width paste artifacts', () => {
    const result = repairJsonPasteContent('\uFEFF{\u00A0"email"\u200B:\u00A0"admin@example.com"\u00A0}');

    expect(result.valid).toBe(true);
    expect(result.content).toBe('{\n  "email": "admin@example.com"\n}');
  });

  it('repairs trailing commas', () => {
    const result = repairJsonPasteContent('{"email":"admin@example.com","roles":["admin",],}');

    expect(result.valid).toBe(true);
    expect(result.content).toBe('{\n  "email": "admin@example.com",\n  "roles": [\n    "admin"\n  ]\n}');
  });

  it('keeps irreparable JSON unchanged and reports an error', () => {
    const content = '{"email": }';
    const result = repairJsonPasteContent(content);

    expect(result.valid).toBe(false);
    expect(result.content).toBe(content);
    expect(result.error?.message).toMatch(/^Invalid JSON/);
  });
});
