import { beforeEach, describe, expect, it, vi } from 'vitest';

import { authApi, deliveryApi, getAuthToken } from '../app/lib/api';

global.fetch = vi.fn();

describe('delivery API flow', () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.mocked(global.fetch).mockReset();
  });

  it('stores auth token after login and sends it on following delivery calls', async () => {
    vi.mocked(global.fetch)
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ access_token: 'test_token_123' }),
      } as Response)
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ id: 1, raw_input: 'Add a test feature', source_type: 'new_requirement' }),
    } as Response);

    const login = await authApi.login({ username: 'testuser', password: 'password' });
    window.localStorage.setItem('ai_pjm_auth_token', login.access_token);
    const demand = await deliveryApi.createDemand({ raw_input: 'Add a test feature' });

    expect(getAuthToken()).toBe('test_token_123');
    expect(demand.id).toBe(1);
    const secondCall = vi.mocked(global.fetch).mock.calls[1];
    expect(secondCall[1]?.headers).toEqual(expect.any(Headers));
    expect((secondCall[1]?.headers as Headers).get('Authorization')).toBe('Bearer test_token_123');
  });

  it('clears auth token when an authenticated request returns 401', async () => {
    window.localStorage.setItem('ai_pjm_auth_token', 'existing_token');
    vi.mocked(global.fetch).mockResolvedValueOnce({
      ok: false,
      status: 401,
      statusText: 'Unauthorized',
      headers: new Headers({ 'content-type': 'application/json' }),
      json: async () => ({ message: 'Token expired' }),
    } as Response);

    await expect(authApi.me()).rejects.toThrow('Token expired');

    expect(getAuthToken()).toBeNull();
  });

  it('runs the main demand-to-run API call sequence with typed wrappers', async () => {
    vi.mocked(global.fetch)
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ id: 1, status: 'intake', raw_input: 'Add feature' }),
      } as Response)
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ id: 2, demand_id: 1, status: 'approved' }),
      } as Response)
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ id: 3, demand_id: 1, status: 'ready' }),
      } as Response)
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ id: 4, coding_task_id: 3, status: 'queued' }),
      } as Response);

    await deliveryApi.createDemand({ raw_input: 'Add feature' });
    await deliveryApi.generateSpec(1);
    await deliveryApi.createCodingTask(1);
    const run = await deliveryApi.createExecutionRun(3);

    expect(run.status).toBe('queued');
    expect(vi.mocked(global.fetch).mock.calls.map((call) => call[0])).toEqual([
      'http://localhost:8010/api/v2/demands',
      'http://localhost:8010/api/v2/demands/1/spec',
      'http://localhost:8010/api/v2/spec-cards/1/coding-task',
      'http://localhost:8010/api/v2/coding-tasks/3/runs',
    ]);
  });
});
