import fs from 'fs';
import path from 'path';
import { expect, test as base } from '@playwright/test';

type RuntimePayload = Record<string, unknown>;
type RuntimeFixtures = Record<string, RuntimePayload>;

export type TestDataAccessor = {
  get<T = unknown>(ref: string): T;
  field<T = unknown>(ref: string, fieldPath: string): T;
};

type TestDataFixtures = {
  testData: TestDataAccessor;
};

let cachedFilePath: string | undefined;
let cachedFixtures: RuntimeFixtures | undefined;

export function createTestDataAccessor(fixtures: RuntimeFixtures): TestDataAccessor {
  return {
    get<T = unknown>(ref: string): T {
      if (!ref || typeof ref !== 'string') {
        throw new Error('testData.get(ref) requires a non-empty fixture ref');
      }
      const payload = fixtures[ref];
      if (payload === undefined) {
        throw new Error(`Test data fixture ref not found: ${ref}`);
      }
      if (
        isRecord(payload)
        && Object.prototype.hasOwnProperty.call(payload, 'data')
        && payload.data !== null
        && payload.data !== undefined
      ) {
        return payload.data as T;
      }
      if (isRecord(payload) && Object.prototype.hasOwnProperty.call(payload, 'text')) {
        return payload.text as T;
      }
      return payload as T;
    },

    field<T = unknown>(ref: string, fieldPath: string): T {
      if (!fieldPath || typeof fieldPath !== 'string') {
        throw new Error('testData.field(ref, path) requires a non-empty field path');
      }
      const root = this.get(ref);
      const value = readPath(root, fieldPath);
      if (value === undefined) {
        throw new Error(`Test data field not found: ${ref}.${fieldPath}`);
      }
      return value as T;
    },
  };
}

export function loadRuntimeTestDataFromEnv(): RuntimeFixtures {
  const filePath = process.env.QUORVEX_TEST_DATA_FILE;
  if (!filePath) {
    throw new Error('QUORVEX_TEST_DATA_FILE is required to use the testData fixture');
  }

  const absolutePath = path.resolve(filePath);
  if (cachedFilePath === absolutePath && cachedFixtures) {
    return cachedFixtures;
  }
  if (!fs.existsSync(absolutePath)) {
    throw new Error(`QUORVEX_TEST_DATA_FILE does not exist: ${absolutePath}`);
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(fs.readFileSync(absolutePath, 'utf8'));
  } catch (error) {
    throw new Error(
      `Unable to read QUORVEX_TEST_DATA_FILE ${absolutePath}: ${error instanceof Error ? error.message : String(error)}`,
    );
  }

  const fixtures = normalizeRuntimeFixtures(parsed);
  cachedFilePath = absolutePath;
  cachedFixtures = fixtures;
  return fixtures;
}

export const test = base.extend<TestDataFixtures>({
  testData: async ({}, use) => {
    await use(createTestDataAccessor(loadRuntimeTestDataFromEnv()));
  },
});

export { expect };

function normalizeRuntimeFixtures(parsed: unknown): RuntimeFixtures {
  if (!isRecord(parsed)) {
    throw new Error('QUORVEX_TEST_DATA_FILE must contain a JSON object');
  }
  const items = isRecord(parsed.items) ? parsed.items : parsed;
  const fixtures: RuntimeFixtures = {};
  for (const [ref, value] of Object.entries(items)) {
    if (!isRecord(value)) {
      throw new Error(`Test data fixture payload for ${ref} must be an object`);
    }
    fixtures[ref] = value;
  }
  return fixtures;
}

function readPath(root: unknown, fieldPath: string): unknown {
  let current = root;
  for (const segment of parsePath(fieldPath)) {
    if (current === null || current === undefined) {
      return undefined;
    }
    if (typeof segment === 'number') {
      if (!Array.isArray(current)) {
        return undefined;
      }
      current = current[segment];
      continue;
    }
    if (!isRecord(current) || !Object.prototype.hasOwnProperty.call(current, segment)) {
      return undefined;
    }
    current = current[segment];
  }
  return current;
}

function parsePath(fieldPath: string): Array<string | number> {
  const segments: Array<string | number> = [];
  for (const part of fieldPath.split('.')) {
    const match = /^([A-Za-z0-9_-]+)(?:\[(\d+)])?$/.exec(part);
    if (!match) {
      segments.push(part);
      continue;
    }
    segments.push(match[1]);
    if (match[2] !== undefined) {
      segments.push(Number(match[2]));
    }
  }
  return segments;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}
