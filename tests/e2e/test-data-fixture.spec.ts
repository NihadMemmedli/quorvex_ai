import fs from 'fs';
import os from 'os';
import path from 'path';
import { expect, test, createTestDataAccessor, loadRuntimeTestDataFromEnv } from '../fixtures/test-data';

test.describe('runtime test data fixture helper', () => {
  test('loads canonical refs and fields from runtime JSON', () => {
    const testData = createTestDataAccessor({
      'wetravel-auth.valid-user': {
        data: {
          username: 'user@example.com',
          password: 'secret-pass',
          profile: { roles: ['traveler'] },
        },
        text: null,
      },
    });

    const user = testData.get<{ username: string; password: string }>('wetravel-auth.valid-user');
    expect(user.username).toBe('user@example.com');
    expect(testData.field('wetravel-auth.valid-user', 'password')).toBe('secret-pass');
    expect(testData.field('wetravel-auth.valid-user', 'profile.roles[0]')).toBe('traveler');
  });

  test('throws clear errors for missing env, ref, and field', () => {
    const previousFile = process.env.QUORVEX_TEST_DATA_FILE;
    delete process.env.QUORVEX_TEST_DATA_FILE;
    expect(() => loadRuntimeTestDataFromEnv()).toThrow(/QUORVEX_TEST_DATA_FILE is required/);
    if (previousFile) {
      process.env.QUORVEX_TEST_DATA_FILE = previousFile;
    }

    const testData = createTestDataAccessor({
      'wetravel-auth.valid-user': { data: { username: 'user@example.com' } },
    });
    expect(() => testData.get('wetravel-auth.missing')).toThrow(
      /Test data fixture ref not found: wetravel-auth\.missing/,
    );
    expect(() => testData.field('wetravel-auth.valid-user', 'password')).toThrow(
      /Test data field not found: wetravel-auth\.valid-user\.password/,
    );
  });

  test('loads runtime file from QUORVEX_TEST_DATA_FILE', () => {
    const previousFile = process.env.QUORVEX_TEST_DATA_FILE;
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'quorvex-test-data-'));
    const fixtureFile = path.join(dir, 'resolved-fixtures.json');
    fs.writeFileSync(
      fixtureFile,
      JSON.stringify({
        items: {
          'wetravel-auth.valid-user': {
            data: { username: 'file-user@example.com', password: 'file-secret' },
          },
        },
      }),
    );

    process.env.QUORVEX_TEST_DATA_FILE = fixtureFile;
    try {
      const testData = createTestDataAccessor(loadRuntimeTestDataFromEnv());
      expect(testData.field('wetravel-auth.valid-user', 'username')).toBe('file-user@example.com');
    } finally {
      if (previousFile) {
        process.env.QUORVEX_TEST_DATA_FILE = previousFile;
      } else {
        delete process.env.QUORVEX_TEST_DATA_FILE;
      }
      fs.rmSync(dir, { recursive: true, force: true });
    }
  });
});
