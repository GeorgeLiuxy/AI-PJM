/**
 * Shared frontend types for the delivery workflow.
 */

export interface ApiResponse<T> {
  code: number;
  message: string;
  data: T;
}

export interface AuthProject {
  id: number;
  key: string;
  name: string;
  role: string;
  status: string;
  default_branch: string;
  repository_root: string | null;
  created_at: string | null;
}

export interface AuthUser {
  id: number | null;
  username: string;
  display_name: string;
  role: string;
  auth_enabled: boolean;
  projects: AuthProject[];
}

export interface AuthManagedUser extends AuthUser {
  email: string | null;
  status: string;
  created_at: string;
}

export interface AuthLoginResponse {
  access_token: string;
  token_type: 'bearer';
  user: AuthUser;
}

export interface DeploymentEnvironmentConfigItem {
  url?: string | null;
  log_url?: string | null;
  description?: string | null;
  environment_name?: string | null;
}

export interface ProjectDeploymentEnvironmentConfig {
  project_id: number;
  environments: Record<string, DeploymentEnvironmentConfigItem>;
}

export interface DeliveryDemand {
  id: number;
  trace_id: string | null;
  project_id: number | null;
  created_by_user_id: number | null;
  raw_input: string;
  source_type: string;
  title: string | null;
  requester_ref: string | null;
  status: string;
  risk_level: 'L0' | 'L1' | 'L2' | 'L3' | null;
  confidence_score: number | null;
  context_payload: Record<string, unknown> | null;
  manual_approval_status?: string | null;
  manual_approval_user_id?: number | null;
  manual_approval_ref?: string | null;
  manual_approval_note?: string | null;
  manual_approval_at?: string | null;
  created_at: string;
  updated_at: string;
}

export interface DeliverySpecCard {
  id: number;
  trace_id: string | null;
  demand_id: number;
  status: 'draft' | 'manual_review' | 'approved' | 'superseded';
  title: string;
  user_story: string;
  scope: string | null;
  acceptance_criteria_json: string[];
  constraints_json: string[];
  risks_json: string[];
  open_questions_json: string[];
  provider_metadata_json: Record<string, unknown> | null;
  created_by: string;
  created_at: string;
  updated_at: string;
}

export interface DeliveryRepoContext {
  id: number;
  trace_id: string | null;
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
  trace_id: string | null;
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
  trace_id: string | null;
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
  execution_runs?: DeliveryExecutionRun[];
  merge_requests?: DeliveryMergeRequestRecord[];
}

export interface DeliveryExecutionLog {
  id: number;
  trace_id: string | null;
  execution_run_id: number;
  level: 'info' | 'warning' | 'error';
  message: string;
  event_json: Record<string, unknown> | null;
  created_at: string;
}

export interface DeliveryExecutionRun {
  id: number;
  trace_id: string | null;
  coding_task_id: number;
  status: 'queued' | 'running' | 'paused' | 'cancelled' | 'blocked' | 'failed' | 'succeeded';
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

export interface DeliveryExecutionQueueItem extends DeliveryExecutionRun {
  coding_task_title: string;
  demand_id: number;
  demand_title: string | null;
  risk_level: 'L0' | 'L1' | 'L2' | 'L3' | null;
}

export interface DeliveryObservabilityAlert {
  id: string;
  category: 'worker' | 'queue' | 'secret' | 'deployment' | 'execution';
  severity: 'warning' | 'critical';
  title: string;
  summary: string;
  count: number;
  entity_type: string;
  entity_ids: number[];
}

export interface DeliveryObservabilitySummary {
  generated_at: string;
  status: 'healthy' | 'warning' | 'critical';
  metrics: Record<string, number>;
  alerts: DeliveryObservabilityAlert[];
}

export interface DeliveryAuditEvent {
  id: number;
  project_id: number | null;
  actor_user_id: number | null;
  actor_ref: string;
  action: string;
  entity_type: string;
  entity_id: number | null;
  summary: string;
  metadata_json: Record<string, unknown> | null;
  created_at: string;
}

export interface SecretRecord {
  id: number;
  project_id: number;
  name: string;
  provider: string;
  description: string | null;
  key_id: string;
  value_mask: string;
  status: string;
  metadata_json: Record<string, unknown> | null;
  expires_at: string | null;
  health_status: 'healthy' | 'expiring_soon' | 'expired' | 'invalid' | 'disabled' | 'unknown';
  health_reason: string | null;
  health_checked_at: string | null;
  created_by_user_id: number | null;
  updated_by_user_id: number | null;
  last_used_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface DeliveryMergeRequestRecord {
  id: number;
  trace_id: string | null;
  coding_task_id: number;
  execution_run_id: number;
  provider: string;
  status: 'created' | 'reviewing' | 'review_passed' | 'review_blocked' | 'closed';
  review_status: 'pending' | 'passed' | 'blocking';
  title: string;
  source_branch: string;
  target_branch: string;
  external_id: string | null;
  url: string | null;
  review_summary: string | null;
  review_comments_json: Array<Record<string, unknown>>;
  evidence_json: Record<string, unknown> | null;
  created_by_user_id?: number | null;
  created_by_ref?: string | null;
  reviewed_by_user_id?: number | null;
  reviewed_by_ref?: string | null;
  reviewed_at?: string | null;
  created_at: string;
  updated_at: string;
  deploy_records?: DeliveryDeployRecord[];
}

export interface DeliveryVerificationRecord {
  id: number;
  trace_id: string | null;
  deploy_record_id: number;
  status: 'passed' | 'failed';
  verifier_user_id?: number | null;
  verifier_ref: string | null;
  summary: string | null;
  evidence_links_json: string[];
  evidence_json: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
}

export interface DeliveryDeployRecord {
  id: number;
  trace_id: string | null;
  merge_request_id: number;
  coding_task_id: number;
  provider: string;
  status: 'pending' | 'deployed' | 'failed';
  environment: string;
  url: string | null;
  evidence_json: Record<string, unknown> | null;
  created_by_user_id?: number | null;
  created_by_ref?: string | null;
  created_at: string;
  updated_at: string;
  verification_records?: DeliveryVerificationRecord[];
}

export interface DeliveryGateCheck {
  id: number;
  trace_id: string | null;
  demand_id: number;
  gate_type: string;
  status: string;
  reason: string | null;
  evidence_json: Record<string, unknown> | null;
  created_at: string;
}

export interface DeliveryDemandDetail extends DeliveryDemand {
  spec_cards: DeliverySpecCard[];
  gate_checks: DeliveryGateCheck[];
  repo_contexts: DeliveryRepoContext[];
  impact_analyses: DeliveryImpactAnalysis[];
  coding_tasks: DeliveryCodingTask[];
}

export interface DeliveryCodingTaskDetail extends DeliveryCodingTask {
  execution_runs: DeliveryExecutionRun[];
  merge_requests: DeliveryMergeRequestRecord[];
}
