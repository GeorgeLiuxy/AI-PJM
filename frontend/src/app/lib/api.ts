/**
 * API wrappers for the delivery workflow.
 */

import type {
  ApiResponse,
  AuthLoginResponse,
  AuthManagedUser,
  AuthProject,
  AuthUser,
  DeliveryAuditEvent,
  DeliveryCodingTask,
  DeliveryDemand,
  DeliveryDemandDetail,
  DeliveryDeployRecord,
  DeliveryExecutionQueueItem,
  DeliveryExecutionRun,
  DeliveryImpactAnalysis,
  DeliveryMergeRequestRecord,
  DeliveryObservabilitySummary,
  DeliveryRepoContext,
  DeliverySpecCard,
  DeliveryVerificationRecord,
  SecretRecord,
} from '../types';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8010';
const AUTH_TOKEN_KEY = 'ai_pjm_auth_token';

export function getAuthToken() {
  return window.localStorage.getItem(AUTH_TOKEN_KEY);
}

export function setAuthToken(token: string | null) {
  if (token) {
    window.localStorage.setItem(AUTH_TOKEN_KEY, token);
    return;
  }
  window.localStorage.removeItem(AUTH_TOKEN_KEY);
}

async function fetchAPI<T>(endpoint: string, options?: RequestInit): Promise<ApiResponse<T>> {
  const url = `${API_BASE_URL}${endpoint}`;
  const headers = new Headers(options?.headers);
  if (!headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }
  const token = getAuthToken();
  if (token) {
    headers.set('Authorization', `Bearer ${token}`);
  }

  const response = await fetch(url, {
    ...options,
    headers,
  });

  if (!response.ok) {
    if (response.status === 401) {
      setAuthToken(null);
    }
    const contentType = response.headers.get('content-type') || '';
    let message = response.statusText;

    if (contentType.includes('application/json')) {
      const error = await response.json().catch(() => ({ message: response.statusText }));
      message = error.message || error.detail || message;
    } else {
      const text = await response.text().catch(() => '');
      message = text.trim() || message;
    }

    throw new Error(message || `接口请求失败：${response.status}`);
  }

  return response.json();
}

async function fetchText(endpoint: string, options?: RequestInit): Promise<string> {
  const url = `${API_BASE_URL}${endpoint}`;
  const headers = new Headers(options?.headers);
  const token = getAuthToken();
  if (token) {
    headers.set('Authorization', `Bearer ${token}`);
  }

  const response = await fetch(url, {
    ...options,
    headers,
  });

  if (!response.ok) {
    if (response.status === 401) {
      setAuthToken(null);
    }
    throw new Error(response.statusText || `接口请求失败：${response.status}`);
  }

  return response.text();
}

function buildQuery(params: Record<string, unknown>) {
  const searchParams = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') {
      searchParams.set(key, String(value));
    }
  });
  const query = searchParams.toString();
  return query ? `?${query}` : '';
}

export const authApi = {
  me: () => fetchAPI<AuthUser>('/api/v2/auth/me'),
  login: (params: { username: string; password: string }) => {
    return fetchAPI<AuthLoginResponse>('/api/v2/auth/login', {
      method: 'POST',
      body: JSON.stringify(params),
    });
  },
  listProjects: () => fetchAPI<AuthProject[]>('/api/v2/auth/projects'),
  createProject: (params: {
    key: string;
    name: string;
    repository_root?: string | null;
    default_branch?: string;
  }) => {
    return fetchAPI<AuthProject>('/api/v2/auth/projects', {
      method: 'POST',
      body: JSON.stringify(params),
    });
  },
  listUsers: () => fetchAPI<AuthManagedUser[]>('/api/v2/auth/users'),
  createUser: (params: {
    username: string;
    password: string;
    display_name: string;
    email?: string | null;
    role?: string;
    project_id?: number | null;
    project_role?: string;
  }) => {
    return fetchAPI<AuthManagedUser>('/api/v2/auth/users', {
      method: 'POST',
      body: JSON.stringify(params),
    });
  },
  updateUser: (
    userId: number,
    params: {
      display_name?: string;
      email?: string | null;
      role?: string;
      status?: string;
    },
  ) => {
    return fetchAPI<AuthManagedUser>(`/api/v2/auth/users/${userId}`, {
      method: 'PATCH',
      body: JSON.stringify(params),
    });
  },
  resetUserPassword: (userId: number, params: { password: string }) => {
    return fetchAPI<AuthManagedUser>(`/api/v2/auth/users/${userId}/password`, {
      method: 'POST',
      body: JSON.stringify(params),
    });
  },
  upsertUserMembership: (userId: number, params: { project_id: number; role: string }) => {
    return fetchAPI<AuthManagedUser>(`/api/v2/auth/users/${userId}/memberships`, {
      method: 'PUT',
      body: JSON.stringify(params),
    });
  },
  removeUserMembership: (userId: number, projectId: number) => {
    return fetchAPI<AuthManagedUser>(`/api/v2/auth/users/${userId}/memberships/${projectId}`, {
      method: 'DELETE',
    });
  },
  listSecrets: (params: { project_id?: number; provider?: string } = {}) => {
    const searchParams = new URLSearchParams();
    if (params.project_id !== undefined) {
      searchParams.set('project_id', String(params.project_id));
    }
    if (params.provider) {
      searchParams.set('provider', params.provider);
    }
    const query = searchParams.toString();
    return fetchAPI<SecretRecord[]>(`/api/v2/secrets${query ? `?${query}` : ''}`);
  },
  createSecret: (params: {
    project_id: number;
    name: string;
    provider: string;
    value: string;
    description?: string | null;
    expires_at?: string | null;
  }) => {
    return fetchAPI<SecretRecord>('/api/v2/secrets', {
      method: 'POST',
      body: JSON.stringify(params),
    });
  },
  rotateSecret: (secretId: number, params: { value: string; description?: string | null; expires_at?: string | null }) => {
    return fetchAPI<SecretRecord>(`/api/v2/secrets/${secretId}/rotate`, {
      method: 'POST',
      body: JSON.stringify(params),
    });
  },
  checkSecretHealth: (secretId: number, remote = true) => {
    return fetchAPI<SecretRecord>(`/api/v2/secrets/${secretId}/health${remote ? '?remote=true' : ''}`);
  },
};

export const deliveryApi = {
  getObservabilitySummary: () => fetchAPI<DeliveryObservabilitySummary>('/api/v2/observability/summary'),
  listAuditEvents: (params: {
    project_id?: number;
    entity_type?: string;
    entity_id?: number;
    action?: string;
    actor_user_id?: number;
    actor_ref?: string;
    created_from?: string;
    created_to?: string;
    query?: string;
    limit?: number;
    offset?: number;
  } = {}) => {
    return fetchAPI<DeliveryAuditEvent[]>(`/api/v2/audit/events${buildQuery(params)}`);
  },
  exportAuditEvents: (params: {
    project_id?: number;
    entity_type?: string;
    entity_id?: number;
    action?: string;
    actor_user_id?: number;
    actor_ref?: string;
    created_from?: string;
    created_to?: string;
    query?: string;
    limit?: number;
  } = {}) => {
    return fetchText(`/api/v2/audit/events/export${buildQuery(params)}`);
  },
  listDemands: (params: { limit?: number; offset?: number } = {}) => {
    const searchParams = new URLSearchParams();
    if (params.limit !== undefined) {
      searchParams.set('limit', String(params.limit));
    }
    if (params.offset !== undefined) {
      searchParams.set('offset', String(params.offset));
    }
    const query = searchParams.toString();
    return fetchAPI<DeliveryDemand[]>(`/api/v2/demands${query ? `?${query}` : ''}`);
  },
  getDemand: (demandId: number) => {
    return fetchAPI<DeliveryDemandDetail>(`/api/v2/demands/${demandId}`);
  },
  recordManualApproval: (
    demandId: number,
    params: { approved: boolean; approver_ref?: string | null; note?: string | null },
  ) => {
    return fetchAPI<DeliveryDemandDetail>(`/api/v2/demands/${demandId}/manual-approval`, {
      method: 'POST',
      body: JSON.stringify(params),
    });
  },
  createDemand: (params: {
    raw_input: string;
    source_type?: string;
    title?: string | null;
    requester_ref?: string | null;
    context_payload?: Record<string, unknown> | null;
  }) => {
    return fetchAPI<DeliveryDemand>('/api/v2/demands', {
      method: 'POST',
      body: JSON.stringify({
        source_type: 'new_requirement',
        ...params,
      }),
    });
  },
  generateSpec: (demandId: number, params: { auto_approve_low_risk?: boolean } = {}) => {
    return fetchAPI<DeliverySpecCard>(`/api/v2/demands/${demandId}/spec`, {
      method: 'POST',
      body: JSON.stringify({ auto_approve_low_risk: true, ...params }),
    });
  },
  collectRepoContext: (demandId: number, params: { force_refresh?: boolean } = {}) => {
    return fetchAPI<DeliveryRepoContext>(`/api/v2/demands/${demandId}/repo-context`, {
      method: 'POST',
      body: JSON.stringify(params),
    });
  },
  analyzeImpact: (demandId: number, params: { repo_context_id?: number | null } = {}) => {
    return fetchAPI<DeliveryImpactAnalysis>(`/api/v2/demands/${demandId}/impact-analysis`, {
      method: 'POST',
      body: JSON.stringify(params),
    });
  },
  createCodingTask: (
    specCardId: number,
    params: { allowed_paths?: string[]; required_checks?: string[] } = {},
  ) => {
    return fetchAPI<DeliveryCodingTask>(`/api/v2/spec-cards/${specCardId}/coding-task`, {
      method: 'POST',
      body: JSON.stringify(params),
    });
  },
  createExecutionRun: (
    codingTaskId: number,
    params: { executor_type?: string; trigger_mode?: string } = {},
  ) => {
    return fetchAPI<DeliveryExecutionRun>(`/api/v2/coding-tasks/${codingTaskId}/runs`, {
      method: 'POST',
      body: JSON.stringify({
        executor_type: 'codex',
        trigger_mode: 'manual',
        ...params,
      }),
    });
  },
  listExecutionRuns: (params: { statuses?: string[]; limit?: number; offset?: number } = {}) => {
    const searchParams = new URLSearchParams();
    if (params.statuses?.length) {
      searchParams.set('statuses', params.statuses.join(','));
    }
    if (params.limit !== undefined) {
      searchParams.set('limit', String(params.limit));
    }
    if (params.offset !== undefined) {
      searchParams.set('offset', String(params.offset));
    }
    const query = searchParams.toString();
    return fetchAPI<DeliveryExecutionQueueItem[]>(`/api/v2/execution-runs${query ? `?${query}` : ''}`);
  },
  dispatchExecutionRun: (executionRunId: number) => {
    return fetchAPI<DeliveryExecutionRun>(`/api/v2/execution-runs/${executionRunId}/dispatch`, {
      method: 'POST',
      body: JSON.stringify({}),
    });
  },
  pauseExecutionRun: (executionRunId: number, reason?: string) => {
    return fetchAPI<DeliveryExecutionRun>(`/api/v2/execution-runs/${executionRunId}/pause`, {
      method: 'POST',
      body: JSON.stringify({ reason }),
    });
  },
  resumeExecutionRun: (executionRunId: number, reason?: string) => {
    return fetchAPI<DeliveryExecutionRun>(`/api/v2/execution-runs/${executionRunId}/resume`, {
      method: 'POST',
      body: JSON.stringify({ reason }),
    });
  },
  cancelExecutionRun: (executionRunId: number, reason?: string) => {
    return fetchAPI<DeliveryExecutionRun>(`/api/v2/execution-runs/${executionRunId}/cancel`, {
      method: 'POST',
      body: JSON.stringify({ reason }),
    });
  },
  retryCodingTaskExecution: (codingTaskId: number) => {
    return fetchAPI<DeliveryExecutionRun>(`/api/v2/coding-tasks/${codingTaskId}/retry`, {
      method: 'POST',
      body: JSON.stringify({}),
    });
  },
  autoRepairCodingTaskExecution: (
    codingTaskId: number,
    params: { executor_type?: string; max_attempts?: number } = {},
  ) => {
    return fetchAPI<DeliveryExecutionRun[]>(`/api/v2/coding-tasks/${codingTaskId}/auto-repair`, {
      method: 'POST',
      body: JSON.stringify({
        executor_type: 'codex',
        max_attempts: 1,
        ...params,
      }),
    });
  },
  createMergeRequestRecord: (
    codingTaskId: number,
    params: {
      execution_run_id?: number;
      provider?: string;
      target_branch?: string;
      title?: string;
      url?: string;
    } = {},
  ) => {
    return fetchAPI<DeliveryMergeRequestRecord>(`/api/v2/coding-tasks/${codingTaskId}/merge-request`, {
      method: 'POST',
      body: JSON.stringify({
        provider: 'local',
        target_branch: 'main',
        ...params,
      }),
    });
  },
  recordMergeRequestReview: (
    mergeRequestId: number,
    params: {
      review_status?: 'passed' | 'blocking';
      review_summary?: string;
      review_comments?: Array<Record<string, unknown>>;
      blocking_issues?: string[];
    } = {},
  ) => {
    return fetchAPI<DeliveryMergeRequestRecord>(`/api/v2/merge-requests/${mergeRequestId}/review`, {
      method: 'POST',
      body: JSON.stringify({
        review_status: 'passed',
        review_summary: '本地评审通过。',
        review_comments: [],
        blocking_issues: [],
        ...params,
      }),
    });
  },
  syncMergeRequestReview: (mergeRequestId: number) => {
    return fetchAPI<DeliveryMergeRequestRecord>(`/api/v2/merge-requests/${mergeRequestId}/sync-review`, {
      method: 'POST',
      body: JSON.stringify({}),
    });
  },
  autoRepairMergeRequestReview: (
    mergeRequestId: number,
    params: { executor_type?: string; max_attempts?: number } = {},
  ) => {
    return fetchAPI<DeliveryExecutionRun[]>(`/api/v2/merge-requests/${mergeRequestId}/auto-repair`, {
      method: 'POST',
      body: JSON.stringify({
        executor_type: 'codex',
        max_attempts: 1,
        ...params,
      }),
    });
  },
  createDeployRecord: (
    mergeRequestId: number,
    params: {
      provider?: string;
      environment?: string;
      url?: string;
    } = {},
  ) => {
    return fetchAPI<DeliveryDeployRecord>(`/api/v2/merge-requests/${mergeRequestId}/deployments`, {
      method: 'POST',
      body: JSON.stringify({
        provider: 'local',
        environment: 'test',
        ...params,
      }),
    });
  },
  syncDeployRecordStatus: (deployRecordId: number) => {
    return fetchAPI<DeliveryDeployRecord>(`/api/v2/deployments/${deployRecordId}/sync-status`, {
      method: 'POST',
      body: JSON.stringify({}),
    });
  },
  redeployDeployRecord: (deployRecordId: number) => {
    return fetchAPI<DeliveryDeployRecord>(`/api/v2/deployments/${deployRecordId}/redeploy`, {
      method: 'POST',
      body: JSON.stringify({}),
    });
  },
  recordVerification: (
    deployRecordId: number,
    params: {
      status?: 'passed' | 'failed';
      verifier_ref?: string | null;
      summary?: string | null;
      evidence_links?: string[];
    } = {},
  ) => {
    return fetchAPI<DeliveryVerificationRecord>(`/api/v2/deployments/${deployRecordId}/verification`, {
      method: 'POST',
      body: JSON.stringify({
        status: 'passed',
        verifier_ref: 'local_operator',
        summary: '本地验收通过。',
        evidence_links: [],
        ...params,
      }),
    });
  },
  getCodingTask: (codingTaskId: number) => {
    return fetchAPI<DeliveryCodingTask>(`/api/v2/coding-tasks/${codingTaskId}`);
  },
};

export default { authApi, deliveryApi };
