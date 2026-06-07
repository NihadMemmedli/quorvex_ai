import { expect, Page, Route, test } from '@playwright/test';

const API_BASE = (process.env.API_BASE || process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8001').replace(/\/$/, '');
const PROJECT = {
  id: 'project-1',
  name: 'Project One',
  base_url: 'https://example.test',
  created_at: '2026-06-07T00:00:00',
  spec_count: 0,
  run_count: 0,
  batch_count: 0,
};

interface Dataset {
  id: string;
  project_id: string;
  key: string;
  name: string;
  description: string;
  tags: string[];
  status: 'active' | 'archived';
  format: 'json' | 'text' | 'mixed';
  item_count: number;
}

interface Item {
  id: string;
  dataset_id: string;
  dataset_key: string;
  ref: string;
  key: string;
  name: string;
  description: string;
  status: 'active' | 'archived';
  format: 'json' | 'text' | 'mixed';
  data: Record<string, unknown> | null;
  text: string | null;
  sensitive_fields: string[];
  placeholders: Record<string, string>;
}

function apiPath(url: string) {
  const parsed = new URL(url);
  return parsed.pathname.replace(/^\/backend-proxy/, '');
}

function envPart(value: string) {
  return value.toUpperCase().replace(/[^A-Z0-9]+/g, '_').replace(/^_+|_+$/g, '');
}

async function routeCoreApi(page: Page) {
  await page.route(`${API_BASE}/auth/refresh`, route =>
    route.fulfill({ status: 200, json: { access_token: 'access-token', refresh_token: 'refresh-token' } }),
  );
  await page.route(`${API_BASE}/auth/me`, route =>
    route.fulfill({
      status: 200,
      json: {
        id: 'user-1',
        email: 'qa@example.com',
        full_name: 'QA User',
        is_active: true,
        is_superuser: true,
        email_verified: true,
        created_at: '2026-06-07T00:00:00',
        last_login: null,
      },
    }),
  );
  await page.route(`${API_BASE}/projects`, route => route.fulfill({ status: 200, json: { projects: [PROJECT] } }));
  await page.route(`${API_BASE}/spec-metadata**`, route => route.fulfill({ status: 200, json: {} }));
  await page.route(`${API_BASE}/requirements**`, route => route.fulfill({ status: 200, json: { items: [] } }));
  await page.route(`${API_BASE}/chat/project-context`, route => route.fulfill({ status: 200, json: {} }));
  await page.route(`${API_BASE}/api/agents/tools/catalog`, route => route.fulfill({ status: 200, json: { tools: [] } }));
}

async function routeTestDataApi(
  page: Page,
  state?: { datasets: Dataset[]; items: Item[] },
  options?: { failDatasetDelete?: boolean; failItemDelete?: boolean },
) {
  const dataState = state || { datasets: [] as Dataset[], items: [] as Item[] };

  await page.route(`${API_BASE}/test-data/**`, async (route: Route) => {
    const request = route.request();
    const path = apiPath(request.url());
    const method = request.method();

    if (path === '/test-data/datasets' && method === 'GET') {
      return route.fulfill({
        status: 200,
        json: {
          datasets: dataState.datasets.map(dataset => ({
            ...dataset,
            item_count: dataState.items.filter(item => item.dataset_id === dataset.id).length,
          })),
          total: dataState.datasets.length,
        },
      });
    }

    if (path === '/test-data/datasets' && method === 'POST') {
      const body = request.postDataJSON();
      const dataset: Dataset = {
        id: `dataset-${dataState.datasets.length + 1}`,
        project_id: body.project_id,
        key: body.key,
        name: body.name || body.key,
        description: body.description || '',
        tags: body.tags || [],
        status: body.status || 'active',
        format: body.format || 'json',
        item_count: 0,
      };
      dataState.datasets.push(dataset);
      return route.fulfill({ status: 201, json: dataset });
    }

    const datasetMatch = path.match(/^\/test-data\/datasets\/([^/]+)$/);
    if (datasetMatch && method === 'DELETE') {
      const datasetId = decodeURIComponent(datasetMatch[1]);
      if (options?.failDatasetDelete) {
        return route.fulfill({ status: 500, json: { detail: 'Dataset delete failed' } });
      }
      dataState.datasets = dataState.datasets.filter(dataset => dataset.id !== datasetId);
      dataState.items = dataState.items.filter(item => item.dataset_id !== datasetId);
      return route.fulfill({ status: 200, json: { status: 'deleted', id: datasetId } });
    }

    const itemListMatch = path.match(/^\/test-data\/datasets\/([^/]+)\/items$/);
    if (itemListMatch && method === 'GET') {
      const datasetId = decodeURIComponent(itemListMatch[1]);
      const datasetItems = dataState.items.filter(item => item.dataset_id === datasetId);
      return route.fulfill({ status: 200, json: { items: datasetItems, total: datasetItems.length } });
    }

    if (itemListMatch && method === 'POST') {
      const datasetId = decodeURIComponent(itemListMatch[1]);
      const dataset = dataState.datasets.find(candidate => candidate.id === datasetId);
      const body = request.postDataJSON();
      const ref = `${dataset?.key}.${body.key}`;
      const placeholders = Object.fromEntries(
        (body.sensitive_fields || []).map((field: string) => [
          field,
          `{{TESTDATA_${envPart(dataset?.key || '')}_${envPart(body.key)}_${envPart(field)}}}`,
        ]),
      );
      const item: Item = {
        id: `item-${dataState.items.length + 1}`,
        dataset_id: datasetId,
        dataset_key: dataset?.key || '',
        ref,
        key: body.key,
        name: body.name || '',
        description: body.description || '',
        status: body.status || 'active',
        format: body.format || 'json',
        data: body.data ? { ...body.data, ...Object.fromEntries(Object.entries(placeholders).map(([key, value]) => [key, value])) } : null,
        text: body.text || null,
        sensitive_fields: body.sensitive_fields || [],
        placeholders,
      };
      dataState.items.push(item);
      return route.fulfill({ status: 201, json: item });
    }

    const itemMatch = path.match(/^\/test-data\/datasets\/([^/]+)\/items\/([^/]+)$/);
    if (itemMatch && method === 'PUT') {
      const itemId = decodeURIComponent(itemMatch[2]);
      const body = request.postDataJSON();
      const item = dataState.items.find(candidate => candidate.id === itemId);
      if (!item) return route.fulfill({ status: 404, json: { detail: 'Not found' } });
      item.key = body.key;
      item.name = body.name || '';
      item.description = body.description || '';
      item.status = body.status || 'active';
      item.format = body.format || 'json';
      item.data = body.data || null;
      item.text = body.text || null;
      item.sensitive_fields = body.sensitive_fields || [];
      item.ref = `${item.dataset_key}.${item.key}`;
      return route.fulfill({ status: 200, json: item });
    }

    if (itemMatch && method === 'DELETE') {
      const itemId = decodeURIComponent(itemMatch[2]);
      if (options?.failItemDelete) {
        return route.fulfill({ status: 500, json: { detail: 'Item delete failed' } });
      }
      dataState.items = dataState.items.filter(item => item.id !== itemId);
      return route.fulfill({ status: 200, json: { status: 'deleted', id: itemId } });
    }

    return route.fulfill({ status: 404, json: { detail: `Unhandled ${method} ${path}` } });
  });

  return dataState;
}

async function authenticate(page: Page) {
  await page.addInitScript(() => {
    window.localStorage.setItem('refresh_token', 'refresh-token');
    window.localStorage.setItem('we-test-current-project-id', 'project-1');
  });
}

test.describe('Test data', () => {
  test('creates, reloads, edits, and deletes an item from the default editor values', async ({ page }) => {
    await authenticate(page);
    await routeCoreApi(page);
    await routeTestDataApi(page);

    await page.goto('/test-data');
    await expect(page.getByRole('heading', { name: 'Test Data' })).toBeVisible();

    await page.getByTestId('test-data-dataset-key').fill('auth-users');
    await page.getByTestId('test-data-dataset-name').fill('Auth Users');
    await page.getByTestId('test-data-create-dataset').click();

    await expect(page.getByTestId('test-data-dataset-card').filter({ hasText: 'Auth Users' })).toBeVisible();
    await expect(page.getByTestId('test-data-item-key')).toHaveValue('valid-admin');
    await expect(page.getByTestId('test-data-item-name')).toHaveValue('Valid admin');

    await page.getByTestId('test-data-save-item').click();

    const itemCard = page.getByTestId('test-data-item-card').filter({ hasText: 'auth-users.valid-admin' });
    await expect(itemCard).toBeVisible();
    await expect(page.getByTestId('test-data-password-sensitive')).toHaveAttribute('data-state', 'unchecked');
    await expect(page.locator('textarea')).toContainText('"password": "replace-me"');
    await expect(page.getByText('{{TESTDATA_AUTH_USERS_VALID_ADMIN_PASSWORD}}')).toHaveCount(0);
    await expect(page.getByTestId('test-data-dataset-card').filter({ hasText: '1 items' })).toBeVisible();

    await page.reload();
    await expect(page.getByTestId('test-data-item-card').filter({ hasText: 'auth-users.valid-admin' })).toBeVisible();

    await page.getByTestId('test-data-item-name').fill('Valid admin updated');
    await page.getByTestId('test-data-save-item').click();
    await expect(page.getByTestId('test-data-item-card').filter({ hasText: 'Valid admin updated' })).toBeVisible();

    await page.getByTestId('test-data-delete-item').click();
    await expect(page.getByRole('dialog').getByText('Delete test data item?')).toBeVisible();
    await page.getByRole('dialog').getByRole('button', { name: 'Delete item' }).click();

    await expect(page.getByTestId('test-data-item-card')).toHaveCount(0);
    await expect(page.getByText('No items in this dataset yet')).toBeVisible();
  });

  test('optionally protects password fields from the item editor', async ({ page }) => {
    await authenticate(page);
    await routeCoreApi(page);
    await routeTestDataApi(page);

    await page.goto('/test-data');
    await expect(page.getByRole('heading', { name: 'Test Data' })).toBeVisible();

    await page.getByTestId('test-data-dataset-key').fill('auth-users');
    await page.getByTestId('test-data-dataset-name').fill('Auth Users');
    await page.getByTestId('test-data-create-dataset').click();
    await expect(page.getByTestId('test-data-dataset-card').filter({ hasText: 'Auth Users' })).toBeVisible();

    await page.getByTestId('test-data-password-sensitive').click();
    await expect(page.getByTestId('test-data-password-sensitive')).toHaveAttribute('data-state', 'checked');
    await page.getByTestId('test-data-save-item').click();

    await expect(page.getByTestId('test-data-item-card').filter({ hasText: 'auth-users.valid-admin' })).toBeVisible();
    await expect(page.getByText('{{TESTDATA_AUTH_USERS_VALID_ADMIN_PASSWORD}}')).toBeVisible();
    await expect(page.locator('textarea')).not.toContainText('"password": "replace-me"');
  });

  test('deletes a dataset and all of its items from the UI', async ({ page }) => {
    await authenticate(page);
    await routeCoreApi(page);
    await routeTestDataApi(page, {
      datasets: [{
        id: 'dataset-1',
        project_id: PROJECT.id,
        key: 'auth-users',
        name: 'Auth Users',
        description: 'Reusable auth fixtures',
        tags: ['auth'],
        status: 'active',
        format: 'json',
        item_count: 2,
      }],
      items: [{
        id: 'item-1',
        dataset_id: 'dataset-1',
        dataset_key: 'auth-users',
        ref: 'auth-users.valid-admin',
        key: 'valid-admin',
        name: 'Valid admin',
        description: '',
        status: 'active',
        format: 'json',
        data: { email: 'admin@example.com' },
        text: null,
        sensitive_fields: [],
        placeholders: {},
      }, {
        id: 'item-2',
        dataset_id: 'dataset-1',
        dataset_key: 'auth-users',
        ref: 'auth-users.locked-user',
        key: 'locked-user',
        name: 'Locked user',
        description: '',
        status: 'active',
        format: 'json',
        data: { email: 'locked@example.com' },
        text: null,
        sensitive_fields: [],
        placeholders: {},
      }],
    });

    await page.goto('/test-data');
    await expect(page.getByTestId('test-data-dataset-card').filter({ hasText: 'Auth Users' })).toBeVisible();
    await expect(page.getByTestId('test-data-item-card')).toHaveCount(2);

    await page.getByTestId('test-data-delete-dataset').click();
    await expect(page.getByRole('dialog').getByText('Delete test data dataset?')).toBeVisible();
    await expect(page.getByRole('dialog').getByText('This will permanently delete "Auth Users" and 2 items.')).toBeVisible();
    await page.getByRole('dialog').getByRole('button', { name: 'Delete dataset' }).click();

    await expect(page.getByTestId('test-data-dataset-card')).toHaveCount(0);
    await expect(page.getByTestId('test-data-item-card')).toHaveCount(0);
    await expect(page.getByText('No datasets yet')).toBeVisible();
    await expect(page.getByText('Choose a dataset')).toBeVisible();
  });

  test('keeps the dataset delete dialog open when delete fails', async ({ page }) => {
    await authenticate(page);
    await routeCoreApi(page);
    await routeTestDataApi(page, {
      datasets: [{
        id: 'dataset-1',
        project_id: PROJECT.id,
        key: 'auth-users',
        name: 'Auth Users',
        description: 'Reusable auth fixtures',
        tags: ['auth'],
        status: 'active',
        format: 'json',
        item_count: 1,
      }],
      items: [{
        id: 'item-1',
        dataset_id: 'dataset-1',
        dataset_key: 'auth-users',
        ref: 'auth-users.valid-admin',
        key: 'valid-admin',
        name: 'Valid admin',
        description: '',
        status: 'active',
        format: 'json',
        data: { email: 'admin@example.com' },
        text: null,
        sensitive_fields: [],
        placeholders: {},
      }],
    }, { failDatasetDelete: true });

    await page.goto('/test-data');
    await expect(page.getByTestId('test-data-dataset-card').filter({ hasText: 'Auth Users' })).toBeVisible();

    await page.getByTestId('test-data-delete-dataset').click();
    const dialog = page.getByRole('dialog');
    await dialog.getByRole('button', { name: 'Delete dataset' }).click();

    await expect(dialog.getByText('Delete test data dataset?')).toBeVisible();
    await expect(page.getByText('Dataset delete failed')).toBeVisible();
    await expect(page.getByTestId('test-data-dataset-card').filter({ hasText: 'Auth Users' })).toBeVisible();
    await expect(page.getByTestId('test-data-item-card')).toHaveCount(1);
  });

  test('inserts an active picker item as a directive', async ({ page }) => {
    await authenticate(page);
    await routeCoreApi(page);
    await routeTestDataApi(page, {
      datasets: [{
        id: 'dataset-1',
        project_id: PROJECT.id,
        key: 'auth-users',
        name: 'Auth Users',
        description: '',
        tags: [],
        status: 'active',
        format: 'json',
        item_count: 1,
      }],
      items: [{
        id: 'item-1',
        dataset_id: 'dataset-1',
        dataset_key: 'auth-users',
        ref: 'auth-users.valid-admin',
        key: 'valid-admin',
        name: 'Valid admin',
        description: '',
        status: 'active',
        format: 'json',
        data: { email: 'admin@example.com' },
        text: null,
        sensitive_fields: [],
        placeholders: {},
      }],
    });

    await page.goto('/specs/new');
    await expect(page.getByRole('heading', { name: 'New Test Spec' })).toBeVisible();
    await page.getByRole('button', { name: 'Code' }).click();

    const picker = page.getByTestId('test-data-picker-directive');
    await expect(picker.getByText('Auth Users')).toBeVisible();
    await expect(picker.getByText('auth-users.valid-admin')).toBeVisible();
    await picker.getByTestId('test-data-picker-insert').click();

    await expect(page.locator('textarea')).toContainText('@testdata "auth-users.valid-admin"');
    await picker.getByTestId('test-data-picker-edit').click();
    await expect(page).toHaveURL(/\/test-data\?ref=auth-users\.valid-admin/);
    await expect(page.getByRole('heading', { name: 'Test Data' })).toBeVisible();
    await expect(page.getByTestId('test-data-item-key')).toHaveValue('valid-admin');
    await expect(page.getByTestId('test-data-item-name')).toHaveValue('Valid admin');
  });
});
