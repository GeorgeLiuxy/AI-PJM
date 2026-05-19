/**
 * Shared frontend types for the delivery workflow.
 */

export interface ApiResponse<T> {
  code: number;
  message: string;
  data: T;
}

export interface DeliveryDemand {
  id: number;
  raw_input: string;
  source_type: string;
  title: string | null;
  requester_ref: string | null;
  status: string;
  risk_level: 'L0' | 'L1' | 'L2' | 'L3' | null;
  confidence_score: number | null;
  context_payload: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
}

export interface DeliverySpecCard {
  id: number;
  demand_id: number;
  status: 'draft' | 'manual_review' | 'approved' | 'superseded';
  title: string;
  user_story: string;
  scope: string | null;
  acceptance_criteria_json: string[];
  constraints_json: string[];
  risks_json: string[];
  open_questions_json: string[];
  created_by: string;
  created_at: string;
  updated_at: string;
}

export interface DeliveryRepoContext {
  id: number;
  demand_id: number;
  status: 'ready' | 'insufficient';
  provider: string;
  summary: string;
  source_refs_json: string[];
  discovered_files_json: string[];
  dependency_refs_json: string[];
  confidence_score: number;
  provider_metadata_json: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
}

export interface DeliveryImpactAnalysis {
  id: number;
  demand_id: number;
  repo_context_id: number | null;
  status: 'ready' | 'manual_review';
  provider: string;
  summary: string;
  impacted_areas_json: string[];
  affected_files_json: string[];
  recommendations_json: string[];
  risk_level: 'L0' | 'L1' | 'L2' | 'L3';
  confidence_score: number;
  provider_metadata_json: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
}

export interface DeliveryCodingTask {
  id: number;
  demand_id: number;
  spec_card_id: number;
  status: 'draft' | 'ready' | 'running' | 'blocked' | 'completed';
  title: string;
  task_prompt: string;
  allowed_paths_json: string[];
  forbidden_actions_json: string[];
  required_checks_json: string[];
  expected_evidence_json: string[];
  created_at: string;
  updated_at: string;
}

export interface DeliveryExecutionLog {
  id: number;
  execution_run_id: number;
  level: 'info' | 'warning' | 'error';
  message: string;
  event_json: Record<string, unknown> | null;
  created_at: string;
}

export interface DeliveryExecutionRun {
  id: number;
  coding_task_id: number;
  status: 'queued' | 'running' | 'blocked' | 'failed' | 'succeeded';
  executor_type: string;
  trigger_mode: string;
  worktree_path: string | null;
  branch_name: string | null;
  commit_sha: string | null;
  result_summary: string | null;
  evidence_json: Record<string, unknown> | null;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
  updated_at: string;
  logs: DeliveryExecutionLog[];
}
