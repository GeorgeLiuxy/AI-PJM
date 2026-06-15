/**
 * Tests for api.ts
 */

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { getAuthToken, setAuthToken, authApi, deliveryApi } from './api'

// Mock fetch
global.fetch = vi.fn()

// Mock localStorage
const localStorageMock = (() => {
  let store: Record<string, string> = {}
  return {
    getItem: (key: string) => store[key] || null,
    setItem: (key: string, value: string) => { store[key] = value.toString() },
    removeItem: (key: string) => { delete store[key] },
    clear: () => { store = {} }
  }
})()

Object.defineProperty(window, 'localStorage', { value: localStorageMock })

describe('api.ts - Token Management', () => {
  afterEach(() => {
    localStorageMock.clear()
  })

  it('getAuthToken should return token from localStorage', () => {
    localStorageMock.setItem('ai_pjm_auth_token', 'test-token')
    expect(getAuthToken()).toBe('test-token')
  })

  it('getAuthToken should return null when no token exists', () => {
    expect(getAuthToken()).toBeNull()
  })

  it('setAuthToken should save token to localStorage', () => {
    setAuthToken('new-token')
    expect(localStorageMock.getItem('ai_pjm_auth_token')).toBe('new-token')
  })

  it('setAuthToken should remove token when null is passed', () => {
    localStorageMock.setItem('ai_pjm_auth_token', 'existing-token')
    setAuthToken(null)
    expect(localStorageMock.getItem('ai_pjm_auth_token')).toBeNull()
  })
})

describe('api.ts - Internal Function Behavior', () => {
  beforeEach(() => {
    localStorageMock.clear()
    vi.clearAllMocks()
  })

  it('should handle 401 error and clear token on auth API call', async () => {
    localStorageMock.setItem('ai_pjm_auth_token', 'test-token')
    vi.mocked(global.fetch).mockResolvedValueOnce({
      ok: false,
      status: 401,
      statusText: 'Unauthorized',
      headers: new Headers({ 'content-type': 'application/json' }),
      json: async () => ({ message: 'Unauthorized' })
    } as Response)

    await expect(authApi.me()).rejects.toThrow('Unauthorized')
    expect(getAuthToken()).toBeNull()
  })

  it('should build query parameters correctly', async () => {
    vi.mocked(global.fetch).mockResolvedValueOnce({
      ok: true,
      json: async () => []
    } as Response)

    await deliveryApi.listDemands({ limit: 10, offset: 5 })

    const fetchCall = vi.mocked(global.fetch).mock.calls[0]
    const url = fetchCall[0] as string
    expect(url).toContain('limit=10')
    expect(url).toContain('offset=5')
  })
})

describe('api.ts - authApi structure', () => {
  it('should have all expected auth methods', () => {
    expect(authApi).toHaveProperty('me')
    expect(authApi).toHaveProperty('login')
    expect(authApi).toHaveProperty('listProjects')
    expect(authApi).toHaveProperty('createProject')
    expect(authApi).toHaveProperty('listUsers')
    expect(authApi).toHaveProperty('createUser')
    expect(authApi).toHaveProperty('updateUser')
    expect(authApi).toHaveProperty('resetUserPassword')
    expect(authApi).toHaveProperty('upsertUserMembership')
    expect(authApi).toHaveProperty('removeUserMembership')
    expect(authApi).toHaveProperty('listSecrets')
    expect(authApi).toHaveProperty('createSecret')
    expect(authApi).toHaveProperty('rotateSecret')
    expect(authApi).toHaveProperty('updateSecretStatus')
    expect(authApi).toHaveProperty('checkSecretHealth')
  })

  it('login should make POST request with credentials', async () => {
    const mockResponse = { access_token: 'token123' }
    vi.mocked(global.fetch).mockResolvedValueOnce({
      ok: true,
      json: async () => mockResponse
    } as Response)

    const result = await authApi.login({ username: 'test', password: 'pass' })
    expect(result).toEqual(mockResponse)
    expect(global.fetch).toHaveBeenCalledWith(
      'http://localhost:8010/api/v2/auth/login',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ username: 'test', password: 'pass' })
      })
    )
  })
})

describe('api.ts - deliveryApi structure', () => {
  it('should have all expected delivery methods', () => {
    expect(deliveryApi).toHaveProperty('getObservabilitySummary')
    expect(deliveryApi).toHaveProperty('getProjectObservabilitySummaries')
    expect(deliveryApi).toHaveProperty('getConfigHealth')
    expect(deliveryApi).toHaveProperty('getTraceDetail')
    expect(deliveryApi).toHaveProperty('getProjectOnboarding')
    expect(deliveryApi).toHaveProperty('getProjectDeploymentEnvironments')
    expect(deliveryApi).toHaveProperty('updateProjectDeploymentEnvironments')
    expect(deliveryApi).toHaveProperty('listAuditEvents')
    expect(deliveryApi).toHaveProperty('exportAuditEvents')
    expect(deliveryApi).toHaveProperty('listDemands')
    expect(deliveryApi).toHaveProperty('getDemand')
    expect(deliveryApi).toHaveProperty('recordManualApproval')
    expect(deliveryApi).toHaveProperty('createDemand')
    expect(deliveryApi).toHaveProperty('generateSpec')
    expect(deliveryApi).toHaveProperty('collectRepoContext')
    expect(deliveryApi).toHaveProperty('analyzeImpact')
    expect(deliveryApi).toHaveProperty('createCodingTask')
    expect(deliveryApi).toHaveProperty('createExecutionRun')
    expect(deliveryApi).toHaveProperty('listExecutionRuns')
    expect(deliveryApi).toHaveProperty('dispatchExecutionRun')
    expect(deliveryApi).toHaveProperty('pauseExecutionRun')
    expect(deliveryApi).toHaveProperty('resumeExecutionRun')
    expect(deliveryApi).toHaveProperty('cancelExecutionRun')
    expect(deliveryApi).toHaveProperty('retryCodingTaskExecution')
    expect(deliveryApi).toHaveProperty('autoRepairCodingTaskExecution')
    expect(deliveryApi).toHaveProperty('createMergeRequestRecord')
    expect(deliveryApi).toHaveProperty('recordMergeRequestReview')
    expect(deliveryApi).toHaveProperty('syncMergeRequestReview')
    expect(deliveryApi).toHaveProperty('autoRepairMergeRequestReview')
    expect(deliveryApi).toHaveProperty('createDeployRecord')
    expect(deliveryApi).toHaveProperty('syncDeployRecordStatus')
    expect(deliveryApi).toHaveProperty('redeployDeployRecord')
    expect(deliveryApi).toHaveProperty('recordVerification')
    expect(deliveryApi).toHaveProperty('getCodingTask')
  })

  it('createDemand should use correct default parameters', async () => {
    const mockDemand = { id: 1, raw_input: 'add feature', source_type: 'new_requirement' }
    vi.mocked(global.fetch).mockResolvedValueOnce({
      ok: true,
      json: async () => mockDemand
    } as Response)

    const result = await deliveryApi.createDemand({
      raw_input: 'add feature'
    })

    expect(result).toEqual(mockDemand)
    expect(global.fetch).toHaveBeenCalledWith(
      'http://localhost:8010/api/v2/demands',
      expect.objectContaining({
        method: 'POST',
        body: expect.stringContaining('source_type')
      })
    )
  })
})