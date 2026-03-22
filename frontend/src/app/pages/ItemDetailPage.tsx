/**
 * Item Detail Page - 事项详情页（含时间线）
 */

import { useState, useEffect } from 'react';
import { useParams, Link, useNavigate } from 'react-router';
import {
  ArrowLeft,
  Clock,
  User,
  Bot,
  Settings,
  Sparkles,
  AlertCircle,
  CheckCircle2,
  Loader2,
  FileText,
  TrendingUp,
} from 'lucide-react';
import { useItemTimeline } from '../hooks';
import { LoadingSpinner, ErrorState, EmptyState } from '../components/loading';
import { ACTION_TYPE_LABELS, STATUS_LABELS, PRIORITY_COLORS } from '../types';
import { itemApi } from '../lib/api';

export default function ItemDetailPage() {
  const { id } = useParams<{ id: string }>();
  const itemId = id ? parseInt(id, 10) : null;
  const navigate = useNavigate();

  // Timeline data (existing)
  const { data: timelineData, loading: timelineLoading, error: timelineError, refetch: refetchTimeline } = useItemTimeline(itemId);

  // Item detail data (new)
  const [itemData, setItemData] = useState<any>(null);
  const [itemLoading, setItemLoading] = useState(true);
  const [itemError, setItemError] = useState<string | null>(null);

  // Confirm action state
  const [confirming, setConfirming] = useState(false);
  const [confirmSuccess, setConfirmSuccess] = useState(false);

  // Start analysis action state
  const [startingAnalysis, setStartingAnalysis] = useState(false);
  const [startAnalysisSuccess, setStartAnalysisSuccess] = useState(false);

  // Fetch item detail
  useEffect(() => {
    if (!itemId) return;

    async function fetchItemDetail() {
      setItemLoading(true);
      setItemError(null);
      try {
        const response = await itemApi.getById(itemId) as any;
        if (response.code !== 200) {
          throw new Error(response.message || '获取事项详情失败');
        }
        setItemData(response.data);
      } catch (error: any) {
        console.error('Fetch item detail error:', error);
        setItemError(error.message || '获取事项详情失败');
      } finally {
        setItemLoading(false);
      }
    }

    fetchItemDetail();
  }, [itemId]);

  // Handle confirm action
  async function handleConfirm() {
    if (!itemId || confirming) return;

    setConfirming(true);
    setConfirmSuccess(false);

    try {
      const response = await itemApi.confirm(itemId, { confirm_mode: 'accept' }) as any;
      if (response.code !== 200) {
        throw new Error(response.message || '确认事项失败');
      }

      // Refresh item data
      const itemResponse = await itemApi.getById(itemId) as any;
      if (itemResponse.code === 200) {
        setItemData(itemResponse.data);
      }

      // Refresh timeline
      refetchTimeline();

      setConfirmSuccess(true);
      setTimeout(() => setConfirmSuccess(false), 3000);
    } catch (error: any) {
      console.error('Confirm error:', error);
      alert(error.message || '确认事项失败，请重试');
    } finally {
      setConfirming(false);
    }
  }

  // Handle start analysis action
  async function handleStartAnalysis() {
    if (!itemId || startingAnalysis) return;

    setStartingAnalysis(true);
    setStartAnalysisSuccess(false);

    try {
      const response = await itemApi.createAnalysis(itemId) as any;
      if (response.code !== 200) {
        throw new Error(response.message || '创建分析失败');
      }

      const analysisId = response.data.id;

      setStartAnalysisSuccess(true);
      setTimeout(() => {
        setStartAnalysisSuccess(false);
        navigate(`/impact/${analysisId}`);
      }, 500);
    } catch (error: any) {
      console.error('Start analysis error:', error);
      alert(error.message || '创建分析失败，请重试');
      setStartingAnalysis(false);
    }
  }

  // Loading states
  if (itemLoading || timelineLoading) {
    return (
      <main className="max-w-[1200px] mx-auto px-8 py-7">
        <LoadingSpinner />
      </main>
    );
  }

  // Error states
  if (itemError || timelineError) {
    return (
      <main className="max-w-[1200px] mx-auto px-8 py-7">
        <ErrorState message={itemError || timelineError || '加载失败'} />
      </main>
    );
  }

  if (!itemData || !itemId) {
    return (
      <main className="max-w-[1200px] mx-auto px-8 py-7">
        <EmptyState message="事项不存在" />
      </main>
    );
  }

  const { timeline } = timelineData || { timeline: [] };
  const isPendingConfirm = itemData.status === 'pending_confirm';
  const isConfirmed = itemData.status === 'confirmed';
  const isDecided = itemData.status === 'decided';
  const isOutputGenerated = itemData.status === 'output_generated';
  const isDone = itemData.status === 'done';

  return (
    <main className="max-w-[1200px] mx-auto px-8 py-7">
      {/* 返回按钮 */}
      <div className="mb-6">
        <Link
          to="/"
          className="inline-flex items-center gap-2 text-sm text-gray-600 hover:text-gray-900"
        >
          <ArrowLeft className="w-4 h-4" />
          返回首页
        </Link>
      </div>

      {/* 页面标题 */}
      <div className="mb-6">
        <div className="flex items-center gap-3 mb-2">
          <h1 className="text-2xl font-semibold text-gray-900">
            {itemData.title_final || `事项 #${itemId}`}
          </h1>
          <span className={`px-2.5 py-1 rounded-lg text-xs font-medium ${
            itemData.status === 'done' ? 'bg-green-100 text-green-700' :
            itemData.status === 'confirmed' ? 'bg-blue-100 text-blue-700' :
            itemData.status === 'pending_confirm' ? 'bg-yellow-100 text-yellow-700' :
            'bg-gray-100 text-gray-700'
          }`}>
            {STATUS_LABELS[itemData.status] || itemData.status}
          </span>
          {confirmSuccess && (
            <span className="flex items-center gap-1 text-sm text-green-600">
              <CheckCircle2 className="w-4 h-4" />
              已确认
            </span>
          )}
        </div>
        <p className="text-sm text-gray-500">
          查看事项的完整处理过程和时间线
        </p>
      </div>

      <div className="grid grid-cols-3 gap-6">
        {/* 左侧：事项详情和建议 */}
        <div className="col-span-2 space-y-6">
          {/* 基础信息 */}
          <div className="bg-white border border-gray-200 rounded-xl p-6">
            <h2 className="text-lg font-medium text-gray-900 mb-4">基础信息</h2>

            <div className="space-y-4">
              {/* 原始输入 */}
              <div>
                <div className="flex items-center gap-1.5 mb-2">
                  <FileText className="w-3.5 h-3.5 text-gray-400" />
                  <span className="text-xs text-gray-500">原始输入</span>
                </div>
                <div className="bg-gray-50 border border-gray-200 rounded-lg px-4 py-3 text-sm text-gray-900">
                  {itemData.raw_input}
                </div>
              </div>

              {/* 元信息 */}
              <div className="grid grid-cols-3 gap-4">
                <div>
                  <span className="text-xs text-gray-500 block mb-1">来源类型</span>
                  <span className="text-sm text-gray-900">
                    {itemData.source_type === 'customer_feedback' ? '客户反馈' :
                     itemData.source_type === 'new_requirement' ? '新需求' :
                     itemData.source_type === 'meeting_note' ? '会议内容' :
                     itemData.source_type === 'bug_report' ? 'Bug' :
                     itemData.source_type === 'ticket' ? '工单' :
                     itemData.source_type || '其他'}
                  </span>
                </div>
                {itemData.final_type && (
                  <div>
                    <span className="text-xs text-gray-500 block mb-1">类型</span>
                    <span className="text-sm text-gray-900">{itemData.final_type}</span>
                  </div>
                )}
                {itemData.final_priority && (
                  <div>
                    <span className="text-xs text-gray-500 block mb-1">优先级</span>
                    <span className={`inline-block text-xs px-2.5 py-1 rounded ${PRIORITY_COLORS[itemData.final_priority] || PRIORITY_COLORS.medium}`}>
                      {itemData.final_priority}
                    </span>
                  </div>
                )}
              </div>

              {itemData.final_project && (
                <div>
                  <span className="text-xs text-gray-500 block mb-1">项目</span>
                  <span className="text-sm text-gray-900">{itemData.final_project}</span>
                </div>
              )}
            </div>

            {/* 确认按钮 */}
            {isPendingConfirm && (
              <div className="mt-6 pt-6 border-t border-gray-100">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm font-medium text-gray-900">确认此事项</p>
                    <p className="text-xs text-gray-500 mt-0.5">确认后事项将进入后续处理流程</p>
                  </div>
                  <button
                    onClick={handleConfirm}
                    disabled={confirming}
                    className="px-5 py-2.5 bg-blue-600 text-white rounded-lg hover:bg-blue-700 text-sm font-medium disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2 transition-colors"
                  >
                    {confirming ? (
                      <>
                        <Loader2 className="w-4 h-4 animate-spin" />
                        确认中…
                      </>
                    ) : (
                      <>
                        <CheckCircle2 className="w-4 h-4" />
                        确认事项
                      </>
                    )}
                  </button>
                </div>
              </div>
            )}

            {/* 开始分析按钮 */}
            {isConfirmed && (
              <div className="mt-6 pt-6 border-t border-gray-100">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm font-medium text-gray-900">开始影响分析</p>
                    <p className="text-xs text-gray-500 mt-0.5">AI 将分析此事项的业务价值、技术影响和风险等级</p>
                  </div>
                  <button
                    onClick={handleStartAnalysis}
                    disabled={startingAnalysis}
                    className="px-5 py-2.5 bg-purple-600 text-white rounded-lg hover:bg-purple-700 text-sm font-medium disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2 transition-colors"
                  >
                    {startingAnalysis ? (
                      <>
                        <Loader2 className="w-4 h-4 animate-spin" />
                        创建中…
                      </>
                    ) : (
                      <>
                        <TrendingUp className="w-4 h-4" />
                        开始分析
                      </>
                    )}
                  </button>
                </div>
                {startAnalysisSuccess && (
                  <div className="mt-3 flex items-center gap-2 text-sm text-green-600">
                    <CheckCircle2 className="w-4 h-4" />
                    分析创建成功，正在跳转…
                  </div>
                )}
              </div>
            )}

            {/* 生成输出按钮 */}
            {(isDecided || isOutputGenerated) && (
              <div className="mt-6 pt-6 border-t border-gray-100">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm font-medium text-gray-900">
                      {isOutputGenerated ? '查看输出物' : '生成输出物'}
                    </p>
                    <p className="text-xs text-gray-500 mt-0.5">
                      {isOutputGenerated
                        ? '已生成 PRD、测试点等输出物，可查看详情'
                        : 'AI 可生成 PRD、测试点、处理建议等输出物'}
                    </p>
                  </div>
                  <Link
                    to={`/results/${itemId}`}
                    className="px-5 py-2.5 bg-green-600 text-white rounded-lg hover:bg-green-700 text-sm font-medium flex items-center gap-2 transition-colors"
                  >
                    <FileText className="w-4 h-4" />
                    {isOutputGenerated ? '查看输出' : '生成输出'}
                  </Link>
                </div>
              </div>
            )}

            {/* 已完成状态 */}
            {isDone && (
              <div className="mt-6 pt-6 border-t border-gray-100">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm font-medium text-gray-900">事项已完成</p>
                    <p className="text-xs text-gray-500 mt-0.5">所有输出物已采用，事项已归档</p>
                  </div>
                  <Link
                    to={`/results/${itemId}`}
                    className="px-5 py-2.5 bg-gray-100 text-gray-700 rounded-lg hover:bg-gray-200 text-sm font-medium flex items-center gap-2 transition-colors"
                  >
                    <FileText className="w-4 h-4" />
                    查看输出物
                  </Link>
                </div>
              </div>
            )}
          </div>

          {/* AI 建议 */}
          {itemData.suggestion && (
            <div className="bg-white border border-gray-200 rounded-xl p-6">
              <div className="flex items-center gap-2 mb-4">
                <Sparkles className="w-4 h-4 text-blue-600" />
                <h2 className="text-lg font-medium text-gray-900">AI 建议</h2>
                <span className="ml-auto inline-flex items-center gap-1 px-2 py-0.5 bg-blue-50 text-blue-600 rounded text-[10px]">
                  仅供参考
                </span>
              </div>

              <div className="space-y-4">
                {/* 标题建议 */}
                {itemData.suggestion.title_suggestion && (
                  <div>
                    <span className="text-xs text-gray-500 block mb-1">标题建议</span>
                    <div className="text-sm font-medium text-gray-900">
                      {itemData.suggestion.title_suggestion}
                    </div>
                  </div>
                )}

                {/* 类型和优先级 */}
                <div className="grid grid-cols-2 gap-4">
                  {itemData.suggestion.type_suggestion && (
                    <div>
                      <span className="text-xs text-gray-500 block mb-1">类型建议</span>
                      <span className="inline-block text-xs px-2.5 py-1 rounded bg-blue-50 text-blue-700">
                        {itemData.suggestion.type_suggestion}
                      </span>
                    </div>
                  )}
                  {itemData.suggestion.priority_suggestion && (
                    <div>
                      <span className="text-xs text-gray-500 block mb-1">优先级建议</span>
                      <span className={`inline-block text-xs px-2.5 py-1 rounded ${PRIORITY_COLORS[itemData.suggestion.priority_suggestion] || PRIORITY_COLORS.medium}`}>
                        {itemData.suggestion.priority_suggestion}
                      </span>
                    </div>
                  )}
                </div>

                {/* 项目建议 */}
                {itemData.suggestion.project_suggestion && (
                  <div>
                    <span className="text-xs text-gray-500 block mb-1">项目建议</span>
                    <span className="inline-block text-xs px-2.5 py-1 rounded bg-gray-100 text-gray-700">
                      {itemData.suggestion.project_suggestion}
                    </span>
                  </div>
                )}

                {/* 待确认问题 */}
                {itemData.suggestion.pending_questions_json && (
                  <div>
                    <div className="flex items-center gap-1.5 mb-2">
                      <AlertCircle className="w-3.5 h-3.5 text-yellow-600" />
                      <span className="text-xs text-gray-500">待确认问题</span>
                    </div>
                    <div className="bg-yellow-50 border border-yellow-200 rounded-lg px-4 py-3 text-xs text-yellow-900 space-y-1.5">
                      {(() => {
                        const questions = typeof itemData.suggestion.pending_questions_json === 'string'
                          ? JSON.parse(itemData.suggestion.pending_questions_json)
                          : itemData.suggestion.pending_questions_json;
                        return questions.map((q: string, idx: number) => (
                          <div key={idx} className="flex items-start gap-1.5">
                            <span className="text-yellow-500 flex-shrink-0">·</span>
                            {q}
                          </div>
                        ));
                      })()}
                    </div>
                  </div>
                )}

                {/* 推荐操作 */}
                {itemData.suggestion.recommendation_suggestion && (
                  <div>
                    <div className="flex items-center gap-1.5 mb-2">
                      <Sparkles className="w-3.5 h-3.5 text-blue-600" />
                      <span className="text-xs text-gray-500">推荐操作</span>
                    </div>
                    <div className="bg-blue-50 border border-blue-200 rounded-lg px-4 py-3 text-xs text-blue-900">
                      {itemData.suggestion.recommendation_suggestion}
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>

        {/* 右侧：时间线 */}
        <div className="col-span-1">
          <div className="bg-white border border-gray-200 rounded-xl p-6 sticky top-7">
            <div className="flex items-center justify-between mb-6">
              <h2 className="text-lg font-medium text-gray-900">处理时间线</h2>
              <span className="text-sm text-gray-500">
                {timeline.length} 条
              </span>
            </div>

            {timeline.length === 0 ? (
              <EmptyState message="暂无时间线记录" />
            ) : (
              <div className="relative">
                {/* 垂直线 */}
                <div className="absolute left-4 top-0 bottom-0 w-0.5 bg-gray-200"></div>

                <div className="space-y-6">
                  {timeline.map((event: any) => (
                    <TimelineEvent key={event.id} event={event} />
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </main>
  );
}

interface TimelineEventProps {
  event: {
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
  };
}

function TimelineEvent({ event }: TimelineEventProps) {
  const actionLabel = ACTION_TYPE_LABELS[event.action_type] || event.action_type;

  const operatorIcon = {
    user: <User className="w-3.5 h-3.5" />,
    ai: <Bot className="w-3.5 h-3.5" />,
    system: <Settings className="w-3.5 h-3.5" />,
  }[event.operator_type];

  const operatorColor = {
    user: 'bg-blue-100 text-blue-700',
    ai: 'bg-purple-100 text-purple-700',
    system: 'bg-gray-100 text-gray-700',
  }[event.operator_type];

  const bizTypeLabel = {
    item: '事项',
    analysis: '分析',
    output: '输出物',
  }[event.biz_type];

  // 格式化时间
  const formatTime = (dateString: string) => {
    const date = new Date(dateString);
    return date.toLocaleString('zh-CN', {
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  return (
    <div className="relative flex gap-4">
      {/* 时间点 */}
      <div className="relative z-10 flex-shrink-0">
        <div className={`w-8 h-8 rounded-full ${operatorColor} flex items-center justify-center border-2 border-white`}>
          {operatorIcon}
        </div>
      </div>

      {/* 内容 */}
      <div className="flex-1 pb-2">
        <div className="mb-2">
          <div className="flex items-center gap-2 mb-1">
            <span className="text-sm font-medium text-gray-900">{actionLabel}</span>
            {bizTypeLabel && (
              <span className="px-2 py-0.5 rounded text-[10px] font-medium bg-gray-100 text-gray-600">
                {bizTypeLabel} #{event.biz_id}
              </span>
            )}
          </div>

          {event.comment && (
            <p className="text-xs text-gray-600 mt-1">{event.comment}</p>
          )}

          {event.from_status || event.to_status ? (
            <div className="flex items-center gap-1 text-xs text-gray-500 mt-1">
              {event.from_status && (
                <span className="px-1.5 py-0.5 rounded bg-gray-100">
                  {STATUS_LABELS[event.from_status] || event.from_status}
                </span>
              )}
              {(event.from_status || event.to_status) && (
                <span>→</span>
              )}
              {event.to_status && (
                <span className="px-1.5 py-0.5 rounded bg-blue-50 text-blue-700">
                  {STATUS_LABELS[event.to_status] || event.to_status}
                </span>
              )}
            </div>
          ) : null}
        </div>

        <div className="flex items-center gap-1 text-xs text-gray-400">
          <Clock className="w-3 h-3" />
          <span>{formatTime(event.created_at)}</span>
        </div>
      </div>
    </div>
  );
}
