import { expect, Locator, Page, Route, test } from '@playwright/test';

const API_BASE = (process.env.API_BASE || process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8001').replace(/\/$/, '');
const API_PREFIXES = Array.from(new Set([API_BASE, '/backend-proxy', '**/backend-proxy']));

const allSpecs = [
  { name: 'Api/login.md', path: 'Api/login.md', spec_type: 'standard', test_count: 1, is_automated: false },
  { name: 'Api/profile.md', path: 'Api/profile.md', spec_type: 'standard', test_count: 1, is_automated: false },
  { name: 'Api/settings.md', path: 'Api/settings.md', spec_type: 'standard', test_count: 1, is_automated: false },
  { name: 'Autopilot/launch.md', path: 'Autopilot/launch.md', spec_type: 'standard', test_count: 1, is_automated: true },
  { name: 'Autopilot/recover.md', path: 'Autopilot/recover.md', spec_type: 'standard', test_count: 1, is_automated: true },
];

const metadata = Object.fromEntries(allSpecs.map(spec => [spec.name, { tags: [] }]));
const browserAuthSessions = [
  { id: 'auth-default', name: 'Default Login', status: 'active', is_default: true },
  { id: 'auth-expired', name: 'Expired Login', status: 'expired', is_default: false },
  { id: 'auth-alt', name: 'Alt Login', status: 'active', is_default: false },
];

class SpecsSelectionPage {
  constructor(private readonly page: Page) {}

  async routeApi(path: string, handler: (route: Route) => void | Promise<void>) {
    const normalizedPath = path.startsWith('/') ? path : `/${path}`;
    await Promise.all(API_PREFIXES.map(prefix => this.page.route(`${prefix}${normalizedPath}`, handler)));
  }

  async mockBackend() {
    await this.routeApi('/auth/refresh', route =>
      route.fulfill({ status: 200, json: { access_token: 'access-token', refresh_token: 'refresh-token' } }),
    );
    await this.routeApi('/auth/me', route =>
      route.fulfill({
        status: 200,
        json: {
          id: 'user-1',
          email: 'qa@example.com',
          full_name: 'QA User',
          is_active: true,
          is_superuser: true,
          email_verified: true,
          created_at: '2026-05-30T09:00:00',
          last_login: null,
        },
      }),
    );
    await this.routeApi('/projects', route =>
      route.fulfill({
        status: 200,
        json: {
          projects: [
            {
              id: 'default',
              name: 'Default',
              base_url: 'https://example.test',
              created_at: '2026-05-30T09:00:00',
              spec_count: allSpecs.length,
              run_count: 0,
              batch_count: 0,
            },
          ],
        },
      }),
    );
    await this.routeApi('/specs/list?*', route => {
      const url = new URL(route.request().url());
      const templatesOnly = url.searchParams.get('templates_only') === 'true';
      const search = (url.searchParams.get('search') || '').toLowerCase();
      const items = templatesOnly
        ? []
        : allSpecs.filter(spec => !search || spec.name.toLowerCase().includes(search));

      return route.fulfill({
        status: 200,
        json: {
          items,
          total: items.length,
          has_more: false,
          summary: {
            total_all: allSpecs.length,
            automated_count: allSpecs.filter(spec => spec.is_automated).length,
            all_tags: [],
          },
        },
      });
    });
    await this.routeApi('/spec-metadata?*', route => route.fulfill({ status: 200, json: metadata }));
    await this.routeApi('/testrail/default/config', route =>
      route.fulfill({ status: 200, json: { configured: false, project_id: null, suite_id: null } }),
    );
    await this.routeApi('/testrail/default/mappings', route => route.fulfill({ status: 200, json: [] }));
    await this.routeApi('/projects/default/browser-auth-sessions', route =>
      route.fulfill({ status: 200, json: { project_id: 'default', sessions: browserAuthSessions } }),
    );
  }

  async open() {
    await this.page.addInitScript(() => {
      window.localStorage.setItem('refresh_token', 'refresh-token');
      window.localStorage.setItem('we-test-current-project-id', 'default');
    });
    await this.page.goto('/specs');
    await expect(this.page.getByRole('heading', { name: 'Test Specifications' })).toBeVisible();
    await expect(this.folderCheckbox('Api')).toBeVisible();
  }

  async authenticate() {
    await this.page.addInitScript(() => {
      window.localStorage.setItem('refresh_token', 'refresh-token');
      window.localStorage.setItem('we-test-current-project-id', 'default');
    });
  }

  folderCheckbox(folderName: string) {
    return this.page.getByLabel(`Select folder ${folderName}`);
  }

  specCheckbox(specName: string) {
    return this.page.getByLabel(`Select ${specName}`);
  }

  bulkBar() {
    return this.page.getByTestId('specs-bulk-action-bar');
  }

  async expectVisuallySelected(checkbox: Locator) {
    const styles = await checkbox.evaluate(element => {
      const computed = window.getComputedStyle(element);
      return {
        backgroundColor: computed.backgroundColor,
        borderColor: computed.borderColor,
      };
    });

    expect(styles.backgroundColor).not.toBe('rgba(0, 0, 0, 0)');
    expect(styles.backgroundColor).not.toBe('transparent');
    expect(styles.borderColor).not.toBe('rgba(0, 0, 0, 0)');
  }
}

test.describe('Specs selection', () => {
  test('selects a folder, shows selected visual state, and clears the bulk bar', async ({ page }) => {
    const specs = new SpecsSelectionPage(page);
    await specs.mockBackend();
    await specs.open();

    const apiFolderCheckbox = specs.folderCheckbox('Api');
    await apiFolderCheckbox.click();

    await expect(apiFolderCheckbox).toBeChecked();
    await specs.expectVisuallySelected(apiFolderCheckbox);

    const bulkBar = specs.bulkBar();
    await expect(bulkBar).toBeVisible();
    await expect(bulkBar.getByText('3', { exact: true })).toBeVisible();
    await expect(bulkBar.getByText('Specs Selected')).toBeVisible();
    await expect(bulkBar.getByRole('button', { name: 'Export (3)' })).toBeVisible();
    await expect(bulkBar.getByRole('button', { name: 'Run All (3)' })).toBeVisible();

    await bulkBar.getByRole('button', { name: 'Clear' }).click();

    await expect(apiFolderCheckbox).not.toBeChecked();
    await expect(specs.folderCheckbox('Autopilot')).not.toBeChecked();
    await expect(bulkBar).toBeHidden();
  });

  test('marks a parent folder mixed when one child spec is selected', async ({ page }) => {
    const specs = new SpecsSelectionPage(page);
    await specs.mockBackend();
    await specs.open();

    await page.getByRole('button', { name: 'Expand Api' }).click();
    const loginCheckbox = specs.specCheckbox('login.md');
    await loginCheckbox.click();

    await expect(loginCheckbox).toBeChecked();
    const apiFolderCheckbox = specs.folderCheckbox('Api');
    await expect(apiFolderCheckbox).not.toBeChecked();
    await expect(apiFolderCheckbox).toHaveJSProperty('indeterminate', true);
    await specs.expectVisuallySelected(apiFolderCheckbox);
  });

  test('does not count stale selections after a fresh search reload', async ({ page }) => {
    const specs = new SpecsSelectionPage(page);
    await specs.mockBackend();
    await specs.open();

    await specs.folderCheckbox('Api').click();
    await expect(specs.bulkBar().getByText('3', { exact: true })).toBeVisible();

    await page.getByLabel('Search specs...').fill('autopilot');

    await expect(specs.folderCheckbox('Api')).toHaveCount(0);
    await expect(specs.folderCheckbox('Autopilot')).toBeVisible();
    await expect(specs.folderCheckbox('Autopilot')).not.toBeChecked();
    await expect(specs.bulkBar()).toBeHidden();
  });

  test('redirects file query links to the spec detail page', async ({ page }) => {
    const specs = new SpecsSelectionPage(page);
    await specs.mockBackend();
    await specs.authenticate();

    await specs.routeApi('/specs/wetravel-manage-rooms/trip-publishing-customer-trip-page.md?*', route =>
      route.fulfill({
        status: 200,
        json: {
          name: 'wetravel-manage-rooms/trip-publishing-customer-trip-page.md',
          content: '# Trip Publishing Customer Trip Page\n\n## Steps\n1. Open the customer trip page.',
          is_automated: false,
          code_path: null,
        },
      }),
    );

    await page.goto('/specs?file=wetravel-manage-rooms%2Ftrip-publishing-customer-trip-page.md');

    await expect(page).toHaveURL(/\/specs\/wetravel-manage-rooms\/trip-publishing-customer-trip-page\.md$/);
    await expect(page.getByRole('heading', { name: 'Trip Publishing Customer Trip Page' })).toBeVisible();
  });

  test('prefills search query links and filters the specs list', async ({ page }) => {
    const specs = new SpecsSelectionPage(page);
    await specs.mockBackend();
    await specs.authenticate();

    await page.goto('/specs?search=Autopilot');

    await expect(page.getByRole('heading', { name: 'Test Specifications' })).toBeVisible();
    await expect(page.getByLabel('Search specs...')).toHaveValue('Autopilot');
    await expect(specs.folderCheckbox('Autopilot')).toBeVisible();
    await expect(specs.folderCheckbox('Api')).toHaveCount(0);
  });

  test('preselects project default browser auth and disables unusable sessions in run modal', async ({ page }) => {
    const specs = new SpecsSelectionPage(page);
    await specs.mockBackend();
    await specs.open();

    await page.getByRole('button', { name: 'Expand Api' }).click();
    await page.getByLabel('Run login.md').click();

    const authSelect = page.getByLabel('Browser login session');
    await expect(authSelect).toHaveValue('project_default');
    await expect(authSelect.locator('option[value="session:auth-expired"]')).toBeDisabled();
  });

  test('sends selected browser auth for bulk runs', async ({ page }) => {
    const specs = new SpecsSelectionPage(page);
    await specs.mockBackend();
    let bulkPayload: any = null;
    page.on('dialog', dialog => dialog.accept());
    await specs.routeApi('/runs/bulk', async route => {
      bulkPayload = route.request().postDataJSON();
      await route.fulfill({ status: 200, json: { batch_id: 'batch-auth', run_ids: ['run-1'], count: 1 } });
    });
    await specs.open();

    await page.getByRole('button', { name: 'Expand Autopilot' }).click();
    await specs.specCheckbox('Autopilot/launch.md').click();
    await page.getByLabel('Bulk browser login session').selectOption('session:auth-alt');
    await specs.bulkBar().getByRole('button', { name: 'Run All (1)' }).click();

    expect(bulkPayload).toMatchObject({
      browser_auth_session_id: 'auth-alt',
      project_id: 'default',
    });
    expect(bulkPayload.use_project_default_browser_auth).toBeUndefined();
  });
});
