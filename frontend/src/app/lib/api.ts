/**
 * API wrappers for the delivery workflow.
 */

import type {
  ApiResponse,
  DeliveryCodingTask,
  DeliveryDemand,
  DeliveryExecutionRun,
  DeliveryImpactAnalysis,
  DeliveryRepoContext,
  DeliverySpecCard,
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

    throw new Error(message || `API Error: ${response.status}`);
  }

  return response.json();
}

export const deliveryApi = {
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
  dispatchExecutionRun: (executionRunId: number) => {
    return fetchAPI<DeliveryExecutionRun>(`/api/v2/execution-runs/${executionRunId}/dispatch`, {
      method: 'POST',
      body: JSON.stringify({}),
    });
  },
  getCodingTask: (codingTaskId: number) => {
    return fetchAPI<DeliveryCodingTask>(`/api/v2/coding-tasks/${codingTaskId}`);
  },
};

export default { deliveryApi };
