import { expect, Page, Route, test } from '@playwright/test';

const API_BASE = (process.env.API_BASE || process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8001').replace(/\/$/, '');
const API_PREFIXES = Array.from(new Set([API_BASE, '/backend-proxy', '**/backend-proxy']));

const PROJECT = {
  id: 'default',
  name: 'Default',
  base_url: 'https://example.test',
  created_at: '2026-06-07T00:00:00',
  spec_count: 2,
  run_count: 0,
  batch_count: 0,
};

const automatedSpecs = [
  {
    name: 'checkout.md',
    path: '/specs/checkout.md',
    code_path: '/tests/generated/checkout.spec.ts',
    spec_type: 'standard',
    test_count: 1,
    categories: [],
    tags: ['smoke'],
    last_run_status: null,
    last_run_id: null,
    last_run_at: null,
    required_test_data_refs: ['auth-users.valid-admin'],
  },
  {
    name: 'profile.md',
    path: '/specs/profile.md',
    code_path: '/tests/generated/profile.spec.ts',
    spec_type: 'standard',
    test_count: 1,
    categories: [],
    tags: [],
    last_run_status: null,
    last_run_id: null,
    last_run_at: null,
    required_test_data_refs: [],
  },
];

const browserAuthSessions = [
  { id: 'auth-default', name: 'Default Login', status: 'active', is_default: true },
  { id: 'auth-alt', name: 'Alt Login', status: 'active', is_default: false },
];

async function routeApi(page: Page, path: string, handler: (route: Route) => void | Promise<void>) {
  const normalizedPath = path.startsWith('/') ? path : `/${path}`;
  await Promise.all(API_PREFIXES.map(prefix => page.route(`${prefix}${normalizedPath}`, handler)));
}

async function mockRegressionBackend(
  page: Page,
  options?: {
    emptyTestData?: boolean;
    onBulkRun?: (payload: any) => void;
    specs?: typeof automatedSpecs;
    onAutomatedSpecsRequest?: (url: URL) => void;
  },
) {
  const specsFixture = options?.specs || automatedSpecs;
  await routeApi(page, '/auth/refresh', route =>
    route.fulfill({ status: 200, json: { access_token: 'access-token', refresh_token: 'refresh-token' } }),
  );
  await routeApi(page, '/auth/me', route =>
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
  await routeApi(page, '/projects', route => route.fulfill({ status: 200, json: { projects: [PROJECT] } }));
  await routeApi(page, '/specs/folders?*', route =>
    route.fulfill({ status: 200, json: { folders: [], total_specs: specsFixture.length } }),
  );
  await routeApi(page, '/regression/batches?*', route =>
    route.fulfill({ status: 200, json: { batches: [], total: 0 } }),
  );
  await routeApi(page, '/specs/automated?*', route => {
    const url = new URL(route.request().url());
    options?.onAutomatedSpecsRequest?.(url);
    const search = (url.searchParams.get('search') || '').toLowerCase();
    const folder = url.searchParams.get('folder');
    const limit = Number(url.searchParams.get('limit') || 50);
    const offset = Number(url.searchParams.get('offset') || 0);
    const specs = specsFixture.filter(spec => {
      if (folder && !spec.name.startsWith(`${folder}/`)) return false;
      return !search || spec.name.toLowerCase().includes(search);
    });
    const pageSpecs = specs.slice(offset, offset + limit);
    return route.fulfill({
      status: 200,
      json: {
        specs: pageSpecs,
        total: specs.length,
        limit,
        offset,
        has_more: offset + limit < specs.length,
        filtered_folder: folder,
        filtered_by_tags: null,
        filtered_by_project: 'default',
      },
    });
  });
  await routeApi(page, '/projects/default/browser-auth-sessions', route =>
    route.fulfill({ status: 200, json: { project_id: 'default', sessions: browserAuthSessions } }),
  );
  await routeApi(page, '/test-data/datasets?*', route =>
    route.fulfill({
      status: 200,
      json: {
        datasets: options?.emptyTestData ? [] : [{ id: 'dataset-auth', key: 'auth-users', name: 'Auth Users', item_count: 1 }],
        total: options?.emptyTestData ? 0 : 1,
      },
    }),
  );
  await routeApi(page, '/test-data/datasets/dataset-auth/items?*', route =>
    route.fulfill({
      status: 200,
      json: {
        items: options?.emptyTestData
          ? []
          : [{ id: 'item-admin', key: 'valid-admin', ref: 'auth-users.valid-admin', name: 'Valid Admin' }],
        total: options?.emptyTestData ? 0 : 1,
      },
    }),
  );
  await routeApi(page, '/runs/bulk', async route => {
    options?.onBulkRun?.(route.request().postDataJSON());
    await route.fulfill({ status: 200, json: { batch_id: 'batch-regression-data', run_ids: ['run-1'], count: 1 } });
  });
}

async function openRegression(page: Page, path = '/regression') {
  await page.addInitScript(() => {
    window.localStorage.setItem('refresh_token', 'refresh-token');
    window.localStorage.setItem('we-test-current-project-id', 'default');
  });
  await page.goto(path);
  await expect(page.getByRole('heading', { name: 'Regression Testing' })).toBeVisible();
}

test.describe('Regression test-data setup', () => {
  test('run all posts server-side automated selection instead of loaded spec names', async ({ page }) => {
    let bulkPayload: any = null;
    await mockRegressionBackend(page, { onBulkRun: payload => (bulkPayload = payload) });
    await openRegression(page);

    await page.getByRole('button', { name: 'Run All (2)' }).click();
    await page.getByTestId('regression-run-setup').getByRole('button', { name: 'Start Run' }).click();

    expect(bulkPayload).toMatchObject({
      automated_only: true,
      project_id: 'default',
    });
    expect(bulkPayload.spec_names).toBeUndefined();
  });

  test('folder-filtered run all fetches all matching specs before bulk run', async ({ page }) => {
    let bulkPayload: any = null;
    const automatedUrls: URL[] = [];
    const folderSpecs = Array.from({ length: 125 }, (_, index) => ({
      ...automatedSpecs[1],
      name: `flows/case-${String(index).padStart(3, '0')}.md`,
      path: `/specs/flows/case-${String(index).padStart(3, '0')}.md`,
      code_path: `/tests/generated/flows-case-${String(index).padStart(3, '0')}.spec.ts`,
    }));
    await mockRegressionBackend(page, {
      specs: folderSpecs,
      onBulkRun: payload => (bulkPayload = payload),
      onAutomatedSpecsRequest: url => automatedUrls.push(url),
    });
    await openRegression(page, '/regression?folder=flows');

    await page.getByRole('button', { name: 'Run All (125)' }).click();
    await page.getByTestId('regression-run-setup').getByRole('button', { name: 'Start Run' }).click();

    expect(automatedUrls.some(url => url.searchParams.get('folder') === 'flows' && url.searchParams.get('limit') === '100')).toBeTruthy();
    expect(bulkPayload.spec_names).toHaveLength(125);
    expect(bulkPayload.spec_names[0]).toBe('flows/case-000.md');
    expect(bulkPayload.automated_only).toBeUndefined();
  });

  test('sends browser auth and selected test-data refs in bulk payload', async ({ page }) => {
    let bulkPayload: any = null;
    await mockRegressionBackend(page, { onBulkRun: payload => (bulkPayload = payload) });
    await openRegression(page);

    await page.getByPlaceholder('Search tests...').fill('checkout');
    await page.getByRole('button', { name: 'Run All (1)' }).click();

    const drawer = page.getByTestId('regression-run-setup');
    await expect(drawer).toBeVisible();
    await expect(drawer.getByRole('button', { name: 'auth-users.valid-admin' })).toBeVisible();
    await drawer.getByLabel('Regression browser login session').selectOption('session:auth-alt');
    await drawer.getByRole('button', { name: 'Start Run' }).click();

    expect(bulkPayload).toMatchObject({
      spec_names: ['checkout.md'],
      project_id: 'default',
      browser_auth_session_id: 'auth-alt',
      test_data_refs: ['auth-users.valid-admin'],
    });
    expect(bulkPayload.use_project_default_browser_auth).toBeUndefined();
  });

  test('shows empty state when the project has no active test data', async ({ page }) => {
    await mockRegressionBackend(page, { emptyTestData: true });
    await openRegression(page);

    await page.getByPlaceholder('Search tests...').fill('checkout');
    await page.getByRole('button', { name: 'Run All (1)' }).click();

    await expect(page.getByTestId('regression-run-setup')).toContainText('No active test data datasets for this project.');
  });
});
