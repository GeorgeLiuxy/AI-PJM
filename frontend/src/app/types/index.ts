/**
 * API 响应类型定义
 */

// 统一 API 响应格式
export interface ApiResponse<T> {
  code: number;
  message: string;
  data: T;
}

// ==================== Workbench 相关类型 ====================

export interface WorkbenchSummary {
  pending_item_confirm_count: number;
  pending_analysis_review_count: number;
  pending_output_confirm_count: number;
  done_item_count: number;
}

export interface WorkbenchTodo {
  todo_type: 'pending_item_confirm' | 'pending_analysis_review' | 'pending_output_confirm' | 'pending_output_adopt';
  biz_type: 'item' | 'analysis' | 'output';
  biz_id: number;
  item_id: number;
  title: string;
  priority: 'low' | 'medium' | 'high' | 'critical';
  updated_at: string;
}

export interface RecentItem {
  id: number;
  title_final: string | null;
  status: string;
  final_type: string | null;
  final_priority: string | null;
  updated_at: string;
}

export interface RecentOutput {
  id: number;
  item_id: number;
  output_type: string;
  title: string;
  status: string;
  created_at: string;
}

export interface WorkbenchHomeData {
  summary: WorkbenchSummary;
  todo_queue: WorkbenchTodo[];
  recent_items: RecentItem[];
  recent_outputs: RecentOutput[];
}

export interface TodosData {
  todos: WorkbenchTodo[];
  total: number;
  breakdown: {
    pending_item_confirm: number;
    pending_analysis_review: number;
    pending_output_confirm: number;
    pending_output_adopt: number;
  };
}

// ==================== Timeline 相关类型 ====================

export interface TimelineEvent {
  id: number;
  action_type: string;
  biz_type: 'item' | 'analysis' | 'output';
  biz_id: number;
  operator_type: 'user' | 'ai' | 'system';
  operator_ref: string | null;
  from_status: string | null;
  to_status: string | null;
  comment: string | null;
  created_at: string;
}

export interface ItemTimelineData {
  item_id: number;
  timeline: TimelineEvent[];
  total: number;
}

// ==================== 类型映射工具 ====================

// Todo 类型中文映射
export const TODO_TYPE_LABELS: Record<WorkbenchTodo['todo_type'], string> = {
  pending_item_confirm: '待确认事项',
  pending_analysis_review: '待复核分析',
  pending_output_confirm: '待确认输出',
  pending_output_adopt: '待采用输出',
};

// Action type 中文映射
export const ACTION_TYPE_LABELS: Record<string, string> = {
  // Item actions
  item_created: '创建事项',
  item_understood: 'AI 理解事项',
  item_confirmed: '确认事项',
  item_status_changed_to_analyzing: '开始分析',
  item_status_changed_to_decided: '分析完成',
  item_status_changed_to_output_generated: '生成输出物',
  item_status_changed_to_done: '事项完成',

  // Analysis actions
  analysis_created: '创建分析',
  analysis_started: '开始分析',
  analysis_completed: '完成分析',
  analysis_confirmed: '确认分析',
  analysis_rejected: '驳回分析',

  // Output actions
  output_generated: '生成输出物',
  output_confirmed: '确认输出物',
  output_adopted: '采用输出物',
};

// 优先级中文映射
export const PRIORITY_LABELS: Record<string, string> = {
  low: '低',
  medium: '中',
  high: '高',
  critical: '紧急',
};

// 状态中文映射
export const STATUS_LABELS: Record<string, string> = {
  // Item statuses
  draft: '草稿',
  pending_confirm: '待确认',
  confirmed: '已确认',
  analyzing: '分析中',
  decided: '待决策',
  output_generated: '已生成',
  done: '已完成',

  // Analysis statuses
  pending: '待处理',
  running: '进行中',
  pending_review: '待复核',

  // Output statuses
  adopted: '已采用',
};

// 优先级颜色映射
export const PRIORITY_COLORS: Record<string, string> = {
  low: 'bg-gray-100 text-gray-700',
  medium: 'bg-blue-100 text-blue-700',
  high: 'bg-yellow-100 text-yellow-700',
  critical: 'bg-red-100 text-red-700',
};

// ==================== Analysis 相关类型 ====================

export interface Analysis {
  id: number;
  item_id: number;
  analysis_type: string;
  status: 'pending' | 'running' | 'pending_review' | 'confirmed';

  // AI 分析结果
  business_value_score?: number; // 1-5
  technical_impact_score?: number; // 1-5
  risk_level?: 'low' | 'medium' | 'high';
  candidate_capabilities_json?: string | string[];
  candidate_modules_json?: string | string[];
  similar_cases_json?: string | SimilarCase[];
  ai_recommendation?: 'do_now' | 'evaluate_first' | 'plan_later' | 'hold';
  confidence_score?: number;
  evidence_summary?: string;
  missing_information?: string; // 文本类型，不是 JSON
  needs_deep_analysis?: boolean;

  // 人工确认结果
  final_recommendation?: 'do_now' | 'evaluate_first' | 'plan_later' | 'hold';
  review_comment?: string;

  // 时间戳
  created_at: string;
  updated_at: string;
}

export interface SimilarCase {
  title: string;
  similarity: number;
  risk_level: string;
  outcome: string;
}

// Analysis 状态中文映射
export const ANALYSIS_STATUS_LABELS: Record<Analysis['status'], string> = {
  pending: '待分析',
  running: '分析中',
  pending_review: '待复核',
  confirmed: '已确认',
};

// 决策类型中文映射
export const RECOMMENDATION_LABELS: Record<string, string> = {
  do_now: '立即执行',
  evaluate_first: '先评估后决策',
  plan_later: '延后规划',
  hold: '暂缓',
};

// 风险等级中文映射
export const RISK_LEVEL_LABELS: Record<string, string> = {
  low: '低',
  medium: '中',
  high: '高',
};

// 风险等级颜色映射
export const RISK_LEVEL_COLORS: Record<string, string> = {
  low: 'bg-green-100 text-green-700',
  medium: 'bg-blue-100 text-blue-700',
  high: 'bg-red-100 text-red-700',
};

// ==================== Output 相关类型 ====================

export interface Output {
  id: number;
  item_id: number;
  analysis_id: number | null;
  output_type: 'prd' | 'test_points' | 'handling_advice';
  status: 'pending_confirm' | 'confirmed' | 'adopted';

  // 输出内容
  title: string;
  content: string;
  summary: string | null;

  // 采用目标
  adopted_target: 'formal_prd' | 'test_task' | 'implementation_note' | null;

  // 时间戳
  created_at: string;
  updated_at: string;
  confirmed_at: string | null;
  adopted_at: string | null;
}

export interface OutputListItem {
  id: number;
  item_id: number;
  output_type: 'prd' | 'test_points' | 'handling_advice';
  title: string;
  status: 'pending_confirm' | 'confirmed' | 'adopted';
  summary: string | null;
  created_at: string;
}

// Output 状态中文映射
export const OUTPUT_STATUS_LABELS: Record<Output['status'], string> = {
  pending_confirm: '待确认',
  confirmed: '已确认',
  adopted: '已采用',
};

// Output 状态颜色映射
export const OUTPUT_STATUS_COLORS: Record<Output['status'], string> = {
  pending_confirm: 'bg-yellow-100 text-yellow-700',
  confirmed: 'bg-blue-100 text-blue-700',
  adopted: 'bg-green-100 text-green-700',
};

// Output 类型中文映射
export const OUTPUT_TYPE_LABELS: Record<Output['output_type'], string> = {
  prd: 'PRD 初稿',
  test_points: '测试点',
  handling_advice: '处理建议',
};

// Output 类型图标映射
export const OUTPUT_TYPE_ICONS: Record<Output['output_type'], string> = {
  prd: '📄',
  test_points: '✅',
  handling_advice: '💡',
};

// AdoptedTarget 中文映射
export const ADOPTED_TARGET_LABELS: Record<string, string> = {
  formal_prd: '正式 PRD',
  test_task: '测试任务',
  implementation_note: '实施说明',
};

// output_type 到 adopted_target 的映射
export const OUTPUT_TYPE_TO_ADOPTED_TARGET: Record<Output['output_type'], Output['adopted_target']> = {
  prd: 'formal_prd',
  test_points: 'test_task',
  handling_advice: 'implementation_note',
};
