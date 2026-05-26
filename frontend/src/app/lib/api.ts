/**
 * API wrappers for the delivery workflow.
 */

import type {
  ApiResponse,
  DeliveryCodingTask,
  DeliveryDemand,
  DeliveryDemandDetail,
  DeliveryDeployRecord,
  DeliveryExecutionQueueItem,
  DeliveryExecutionRun,
  DeliveryImpactAnalysis,
  DeliveryMergeRequestRecord,
  DeliveryRepoContext,
  DeliverySpecCard,
  DeliveryVerificationRecord,
} from '../types';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8010';

async function fetchAPI<T>(endpoint: string, options?: RequestInit): Promise<ApiResponse<T>> {
  const url = `${API_BASE_URL}${endpoint}`;
  const response = await fetch(url, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...options?.headers,
    },
  });

  if (!response.ok) {
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

export const deliveryApi = {
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

export default { deliveryApi };
