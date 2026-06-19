import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { TestDataPicker } from './TestDataPicker';
import { fetchWithAuth } from '@/contexts/AuthContext';

const { routerPushMock } = vi.hoisted(() => ({
  routerPushMock: vi.fn(),
}));

vi.mock('next/navigation', () => ({
  useRouter: () => ({
    push: routerPushMock,
  }),
}));

vi.mock('@/contexts/AuthContext', () => ({
  fetchWithAuth: vi.fn(),
}));

vi.mock('@/lib/api', () => ({
  API_BASE: '',
  withProjectQuery: (path: string, projectId?: string) =>
    projectId ? `${path}?project_id=${encodeURIComponent(projectId)}` : path,
}));

const fetchWithAuthMock = vi.mocked(fetchWithAuth);

describe('TestDataPicker', () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it('renders compact controls with a primary add action and a quiet manage action', async () => {
    const onInsert = vi.fn();
    fetchWithAuthMock
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          datasets: [{ id: 'dataset-1', key: 'general-data', name: 'General Data' }],
        }),
      } as Response)
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          items: [{ id: 'item-1', key: 'valid-user', ref: 'general-data.valid-user', name: 'Valid user' }],
        }),
      } as Response);

    render(
      <TestDataPicker
        projectId="project-1"
        mode="ref"
        compact
        insertLabel="Add"
        onInsert={onInsert}
      />,
    );

    const picker = await screen.findByTestId('test-data-picker-ref');
    expect(picker).toHaveStyle({ display: 'flex', flexWrap: 'wrap', width: '100%' });

    const addButton = screen.getByTestId('test-data-picker-insert');
    const manageButton = screen.getByTestId('test-data-picker-edit');
    await waitFor(() => expect(addButton).toBeEnabled());
    expect(addButton).toHaveTextContent('Add');
    expect(addButton).toHaveStyle({ minWidth: '84px' });
    expect(manageButton).toHaveTextContent('Manage Data');
    expect(manageButton).toHaveAccessibleName('Manage Data selected test data item');

    fireEvent.click(manageButton);
    expect(routerPushMock).toHaveBeenCalledWith('/test-data?ref=general-data.valid-user');
  });

  it('renders the sidebar variant with compact controls and inserts the selected ref', async () => {
    const onInsert = vi.fn();
    fetchWithAuthMock
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          datasets: [{ id: 'dataset-1', key: 'wetravel-login-users', name: 'Wetravel Login Users' }],
        }),
      } as Response)
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          items: [{ id: 'item-1', key: 'valid-user', ref: 'wetravel-login-users.valid-user', name: 'Valid user' }],
        }),
      } as Response);

    render(
      <TestDataPicker
        projectId="project-1"
        mode="ref"
        variant="sidebar"
        compact
        insertLabel="Add"
        editLabel="Edit"
        onInsert={onInsert}
      />,
    );

    const picker = await screen.findByTestId('test-data-picker-ref');
    expect(picker).toHaveStyle({ display: 'grid', width: '100%' });
    expect(screen.getByTestId('test-data-picker-dataset')).toHaveStyle({ height: '36px' });
    expect(screen.getByTestId('test-data-picker-item')).toHaveStyle({ height: '36px' });
    await waitFor(() => expect(screen.getByTestId('test-data-picker-item')).toHaveTextContent('Valid user'));
    expect(screen.getByTestId('test-data-picker-item')).not.toHaveTextContent('wetravel-login-users.valid-user');

    const addButton = screen.getByTestId('test-data-picker-insert');
    await waitFor(() => expect(addButton).toBeEnabled());
    expect(addButton).toHaveTextContent('Add');

    fireEvent.click(addButton);
    expect(onInsert).toHaveBeenCalledWith('wetravel-login-users.valid-user');
  });
});
