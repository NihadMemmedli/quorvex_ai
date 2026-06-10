import { describe, expect, it } from 'vitest';

import {
  applyProjectDefaultUrl,
  getProjectDefaultUrl,
  isHttpUrl,
  trimUrlInput,
  validateOptionalHttpUrl,
} from './project-url';

describe('project URL utilities', () => {
  it('normalizes and validates optional HTTP URLs', () => {
    expect(trimUrlInput('  https://app.example.test  ')).toBe('https://app.example.test');
    expect(isHttpUrl('https://app.example.test')).toBe(true);
    expect(isHttpUrl('ftp://app.example.test')).toBe(false);
    expect(validateOptionalHttpUrl('', 'Base URL')).toBeNull();
    expect(validateOptionalHttpUrl('example.test', 'Base URL')).toBe('Base URL must start with http:// or https://');
  });

  it('applies project defaults only when the current value is empty or unchanged', () => {
    expect(getProjectDefaultUrl({ base_url: ' https://default.example.test ' })).toBe('https://default.example.test');
    expect(applyProjectDefaultUrl('', 'https://next.example.test', '')).toBe('https://next.example.test');
    expect(
      applyProjectDefaultUrl('https://old.example.test', 'https://next.example.test', 'https://old.example.test')
    ).toBe('https://next.example.test');
    expect(
      applyProjectDefaultUrl('https://custom.example.test', 'https://next.example.test', 'https://old.example.test')
    ).toBe('https://custom.example.test');
  });
});
