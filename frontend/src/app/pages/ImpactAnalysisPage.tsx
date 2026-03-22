import { useState } from 'react';
import { useParams, Link, useNavigate } from 'react-router';
import {
  ArrowLeft,
  Sparkles,
  TrendingUp,
  Code,
  CheckCircle2,
  AlertTriangle,
  XCircle,
  ChevronDown,
  ChevronUp,
  Clock,
  ArrowRight,
  FileText,
  ClipboardList,
  Lightbulb,
  Search,
  Circle,
  Loader2,
} from 'lucide-react';
import { useAnalysis } from '../hooks';
import { LoadingSpinner, ErrorState, EmptyState } from '../components/loading';
import {
  ANALYSIS_STATUS_LABELS,
  RECOMMENDATION_LABELS,
  RISK_LEVEL_LABELS,
  RISK_LEVEL_COLORS,
  STATUS_LABELS,
} from '../types';
import { analysisApi } from '../lib/api';

export default function ImpactAnalysisPage() {
  const { analysisId } = useParams<{ analysisId: string }>();
  const id = analysisId ? parseInt(analysisId, 10) : null;
  const navigate = useNavigate();

  // UI state
  const [showTechnicalDetails, setShowTechnicalDetails] = useState(false);
  const [showWhyReasoning, setShowWhyReasoning] = useState(false);

  // Action states
  const [running, setRunning] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [rejecting, setRejecting] = useState(false);
  const [rejectComment, setRejectComment] = useState('');

  // Fetch analysis data
  const { data: analysis, loading, error, refetch } = useAnalysis(id);

  // Handle run analysis
  async function handleRun() {
    if (!id || running) return;

    setRunning(true);
    try {
      const response = await analysisApi.run(id) as any;
      if (response.code !== 200) {
        throw new Error(response.message || '运行分析失败');
      }
      await refetch();
    } catch (err: any) {
      console.error('Run analysis error:', err);
      alert(err.message || '运行分析失败，请重试');
    } finally {
      setRunning(false);
    }
  }

  // Handle confirm analysis
  async function handleConfirm() {
    if (!id || confirming || !analysis) return;

    setConfirming(true);
    try {
      const params = {
        final_recommendation: analysis.ai_recommendation || 'evaluate_first',
      };
      const response = await analysisApi.confirm(id, params) as any;
      if (response.code !== 200) {
        throw new Error(response.message || '确认分析失败');
      }
      await refetch();
    } catch (err: any) {
      console.error('Confirm analysis error:', err);
      alert(err.message || '确认分析失败，请重试');
    } finally {
      setConfirming(false);
    }
  }

  // Handle reject analysis
  async function handleReject() {
    if (!id || rejecting) return;

    const comment = rejectComment.trim() || '用户驳回';
    setRejecting(true);
    try {
      const response = await analysisApi.reject(id, { review_comment: comment }) as any;
      if (response.code !== 200) {
        throw new Error(response.message || '驳回分析失败');
      }
      await refetch();
    } catch (err: any) {
      console.error('Reject analysis error:', err);
      alert(err.message || '驳回分析失败，请重试');
    } finally {
      setRejecting(false);
      setRejectComment('');
    }
  }

  // Helper: parse JSON fields
  const parseJsonField = <T,>(value: string | T | null | undefined, defaultValue: T): T => {
    if (value === null || value === undefined) return defaultValue;
    if (typeof value === 'string') {
      try {
        return JSON.parse(value) as T;
      } catch {
        return defaultValue;
      }
    }
    return value;
  };

  // Helper: format time
  const formatTime = (dateString: string) => {
    const date = new Date(dateString);
    return date.toLocaleString('zh-CN', {
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  // Loading state
  if (loading) {
    return (
      <main className="max-w-[1200px] mx-auto px-8 py-6">
        <LoadingSpinner />
      </main>
    );
  }

  // Error state
  if (error) {
    return (
      <main className="max-w-[1200px] mx-auto px-8 py-6">
        <ErrorState message={error} />
      </main>
    );
  }

  // Empty state
  if (!analysis) {
    return (
      <main className="max-w-[1200px] mx-auto px-8 py-6">
        <EmptyState message="分析不存在" />
      </main>
    );
  }

  // Parse JSON fields
  const candidateCapabilities = parseJsonField<string[]>(analysis.candidate_capabilities_json, []);
  const candidateModules = parseJsonField<string[]>(analysis.candidate_modules_json, []);
  const similarCases = parseJsonField<Array<{ title: string; similarity: number; risk_level: string; outcome: string }>>(
    analysis.similar_cases_json,
    []
  );

  // Status helpers
  const isPending = analysis.status === 'pending';
  const isRunning = analysis.status === 'running';
  const isPendingReview = analysis.status === 'pending_review';
  const isConfirmed = analysis.status === 'confirmed';

  return (
    <main className="max-w-[1200px] mx-auto px-8 py-6">
      {/* Back */}
      <Link
        to={`/items/${analysis.item_id}`}
        className="inline-flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-800 mb-4"
      >
        <ArrowLeft className="w-3.5 h-3.5" />
        返回事项详情
      </Link>

      {/* ── 分析状态条 ── */}
      <div className="bg-white border border-gray-200 rounded-xl px-5 py-3 mb-4 flex items-center gap-0 flex-wrap">
        {/* Object type */}
        <div className="flex items-center gap-2 mr-5 flex-shrink-0">
          <span className="text-xs text-gray-400">对象类型</span>
          <span className="px-2.5 py-0.5 text-xs bg-gray-100 text-gray-700 rounded-full">分析</span>
        </div>

        <div className="w-px h-4 bg-gray-200 mr-5 flex-shrink-0" />

        {/* Analysis flow */}
        <div className="flex items-center gap-0">
          <StepPill label="待分析" done={isPendingReview || isConfirmed} />
          <StepConnector />
          <StepPill label="分析中" done={isPendingReview || isConfirmed} active={isRunning} />
          <StepConnector />
          <StepPill label="待复核" done={isConfirmed} active={isPendingReview} />
          <StepConnector />
          <StepPill label="已确认" done={isConfirmed} />
        </div>

        <div className="w-px h-4 bg-gray-200 mx-5 flex-shrink-0" />

        {/* Linked item state transition */}
        <div className="flex items-center gap-2 text-xs flex-shrink-0">
          <span className="text-gray-400">关联事项</span>
          <span className="px-2 py-0.5 bg-blue-50 text-blue-700 rounded-full">分析中</span>
          <ArrowRight className="w-3 h-3 text-gray-300" />
          <span className="text-gray-400">确认后变为</span>
          <span className="px-2 py-0.5 bg-green-50 text-green-700 rounded-full">已形成结论</span>
        </div>
      </div>

      {/* ── Compact Header ── */}
      <div className="bg-white rounded-lg border border-gray-200 px-5 py-3.5 mb-4">
        <div className="flex items-center gap-3 flex-wrap">
          <h1 className="text-base font-medium text-gray-900">
            影响分析 #{analysis.id}
          </h1>
          <span className="text-xs px-2 py-0.5 bg-blue-50 text-blue-700 rounded">
            {analysis.analysis_type || 'impact'}
          </span>
          <span className={`text-xs px-2 py-0.5 rounded ${RISK_LEVEL_COLORS[analysis.risk_level || 'medium']}`}>
            {RISK_LEVEL_LABELS[analysis.risk_level || 'medium']}风险
          </span>
          <span className="text-xs text-gray-400">
            创建于 {formatTime(analysis.created_at)}
          </span>
        </div>
      </div>

      {/* ── 空状态：待运行 ── */}
      {isPending && (
        <div className="bg-white rounded-xl border border-gray-200 p-8 mb-4 text-center">
          <Sparkles className="w-12 h-12 text-gray-300 mx-auto mb-4" />
          <h2 className="text-lg font-medium text-gray-900 mb-2">分析尚未开始</h2>
          <p className="text-sm text-gray-500 mb-6">点击下方按钮开始 AI 影响分析</p>
          <button
            onClick={handleRun}
            disabled={running}
            className="px-6 py-2.5 bg-blue-600 text-white rounded-lg hover:bg-blue-700 text-sm font-medium disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2 mx-auto transition-colors"
          >
            {running ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                启动中…
              </>
            ) : (
              <>
                <Sparkles className="w-4 h-4" />
                开始分析
              </>
            )}
          </button>
        </div>
      )}

      {/* ── 运行中状态 ── */}
      {isRunning && (
        <div className="bg-white rounded-xl border border-blue-200 p-8 mb-4 text-center">
          <Loader2 className="w-12 h-12 text-blue-500 mx-auto mb-4 animate-spin" />
          <h2 className="text-lg font-medium text-gray-900 mb-2">AI 正在分析中…</h2>
          <p className="text-sm text-gray-500">这可能需要几秒钟，请稍候</p>
        </div>
      )}

      {/* ── 分析结果展示（仅在 pending_review 及之后显示） ── */}
      {(isPendingReview || isConfirmed) && (
        <>
          {/* ── AI 推荐结论区（核心） ── */}
          <div className={`rounded-2xl border-2 p-6 mb-4 shadow-sm ${
            isConfirmed ? 'bg-green-50 border-green-200' : 'bg-gradient-to-br from-blue-50 to-white border-blue-200'
          }`}>
            {/* Header row */}
            <div className="flex items-center gap-3 mb-5">
              <div className={`w-9 h-9 rounded-xl flex items-center justify-center flex-shrink-0 ${
                isConfirmed ? 'bg-green-600' : 'bg-blue-600'
              }`}>
                <Sparkles className="w-4 h-4 text-white" />
              </div>
              <div className="flex-1">
                <div className="flex items-center gap-2 flex-wrap">
                  <h2 className="text-base font-medium text-gray-900">AI 推荐结论</h2>
                  <span className="px-2 py-0.5 text-xs bg-blue-100 text-blue-700 rounded-full">AI 推荐结论</span>
                  {isConfirmed ? (
                    <span className="px-2 py-0.5 text-xs bg-green-100 text-green-700 rounded-full">已确认</span>
                  ) : (
                    <span className="px-2 py-0.5 text-xs bg-yellow-100 text-yellow-700 rounded-full">
                      人工确认结论：待确认
                    </span>
                  )}
                </div>
                <p className="text-xs text-gray-500 mt-0.5">基于业务价值、技术影响和历史数据的综合分析</p>
              </div>
            </div>

            {/* Decision Cards */}
            <div className="grid grid-cols-3 gap-4 mb-5">
              <div className="bg-white rounded-xl p-4 border-2 border-yellow-200">
                <div className="text-xs text-gray-400 mb-2">推荐决策</div>
                <div className="inline-flex items-center gap-1.5 px-3 py-2 bg-yellow-100 text-yellow-900 rounded-lg font-medium mb-2">
                  <AlertTriangle className="w-4 h-4" />
                  <span>{RECOMMENDATION_LABELS[analysis.ai_recommendation || 'evaluate_first']}</span>
                </div>
                <p className="text-xs text-gray-600 leading-relaxed">
                  AI 基于业务价值、技术影响和历史案例的综合判断
                </p>
              </div>
              <div className="bg-white rounded-xl p-4 border-2 border-green-200">
                <div className="flex items-center gap-1.5 mb-2">
                  <TrendingUp className="w-3.5 h-3.5 text-gray-400" />
                  <div className="text-xs text-gray-400">业务价值评估</div>
                </div>
                <div className="inline-flex items-center px-3 py-1.5 bg-green-100 text-green-900 rounded-lg font-semibold text-xl mb-2">
                  {analysis.business_value_score || 0}/5
                </div>
                <p className="text-xs text-gray-600 leading-relaxed">
                  {analysis.business_value_score && analysis.business_value_score >= 4 ? '高价值，建议优先处理' : '中等价值，可适当延后'}
                </p>
              </div>
              <div className="bg-white rounded-xl p-4 border-2 border-blue-200">
                <div className="flex items-center gap-1.5 mb-2">
                  <Code className="w-3.5 h-3.5 text-gray-400" />
                  <div className="text-xs text-gray-400">技术影响评估</div>
                </div>
                <div className="inline-flex items-center px-3 py-1.5 bg-blue-100 text-blue-900 rounded-lg font-semibold text-xl mb-2">
                  {analysis.technical_impact_score || 0}/5
                </div>
                <p className="text-xs text-gray-600 leading-relaxed">
                  {analysis.technical_impact_score && analysis.technical_impact_score >= 4 ? '影响较大，需谨慎评估' : '影响可控，可正常推进'}
                </p>
              </div>
            </div>

            {/* 确认后会发生什么 */}
            <div className="bg-white border border-blue-100 rounded-xl p-4">
              <div className="text-xs font-medium text-gray-600 mb-3">确认后将发生</div>
              <div className="flex items-start gap-6 flex-wrap">
                <div className="flex items-center gap-2">
                  <ArrowRight className="w-3.5 h-3.5 text-blue-500 flex-shrink-0" />
                  <span className="text-xs text-gray-700">
                    事项状态 → <span className="text-green-700 font-medium">已形成结论</span>
                  </span>
                </div>
                <div className="flex items-center gap-2">
                  <CheckCircle2 className="w-3.5 h-3.5 text-green-500 flex-shrink-0" />
                  <span className="text-xs text-gray-700">结论正式生效，可生成后续输出物</span>
                </div>
              </div>
              <div className="mt-3 pt-3 border-t border-gray-100">
                <div className="text-xs text-gray-400 mb-2">推荐后续动作</div>
                <div className="flex flex-wrap gap-2">
                  <NextActionChip icon={FileText} label="生成 PRD 初稿" />
                  <NextActionChip icon={ClipboardList} label="生成测试点" />
                  <NextActionChip icon={Lightbulb} label="生成处理建议" />
                  {analysis.needs_deep_analysis && (
                    <NextActionChip icon={Search} label="发起深度分析" highlighted />
                  )}
                </div>
              </div>
            </div>
          </div>

          {/* ── 关键影响范围 ── */}
          <div className="bg-white rounded-xl border border-gray-200 p-5 mb-4">
            <h3 className="text-sm font-medium text-gray-900 mb-4">关键影响范围</h3>

            <div className="grid grid-cols-2 gap-5">
              <div>
                {/* Business capabilities */}
                {candidateCapabilities.length > 0 && (
                  <div className="mb-4">
                    <div className="text-xs text-gray-400 mb-2">疑似影响业务能力</div>
                    <div className="flex flex-wrap gap-1.5">
                      {candidateCapabilities.map((cap, idx) => (
                        <span key={idx} className="px-2.5 py-1 bg-blue-50 text-blue-700 rounded text-xs border border-blue-200">
                          {cap}
                        </span>
                      ))}
                    </div>
                  </div>
                )}

                {/* Risk warning */}
                {analysis.risk_level && analysis.risk_level !== 'low' && (
                  <div>
                    <div className="text-xs text-gray-400 mb-2">风险提示</div>
                    <div className={`border rounded-lg p-3 ${
                      analysis.risk_level === 'high'
                        ? 'bg-red-50 border-red-200'
                        : 'bg-yellow-50 border-yellow-200'
                    }`}>
                      <div className="flex items-start gap-2">
                        <AlertTriangle className={`w-3.5 h-3.5 flex-shrink-0 mt-0.5 ${
                          analysis.risk_level === 'high' ? 'text-red-600' : 'text-yellow-600'
                        }`} />
                        <div>
                          <div className={`text-xs font-medium mb-0.5 ${
                            analysis.risk_level === 'high' ? 'text-red-900' : 'text-yellow-900'
                          }`}>
                            {RISK_LEVEL_LABELS[analysis.risk_level]}风险提示
                          </div>
                          <p className={`text-xs leading-relaxed ${
                            analysis.risk_level === 'high' ? 'text-red-800' : 'text-yellow-800'
                          }`}>
                            {analysis.evidence_summary || '该事项可能对现有系统产生较大影响，建议仔细评估'}
                          </p>
                        </div>
                      </div>
                    </div>
                  </div>
                )}
              </div>

              <div>
                {/* Modules */}
                {candidateModules.length > 0 && (
                  <div className="mb-4">
                    <div className="text-xs text-gray-400 mb-2">疑似影响模块</div>
                    <div className="space-y-1.5">
                      {candidateModules.slice(0, 5).map((module, idx) => (
                        <div
                          key={idx}
                          className="flex items-center justify-between px-3 py-2 rounded-lg border border-gray-200 bg-gray-50"
                        >
                          <span className="text-xs font-medium text-gray-800">{module}</span>
                          <span className="text-[10px] px-2 py-0.5 rounded-full bg-blue-100 text-blue-700">
                            待确认
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </div>

            {/* Historical cases */}
            {similarCases.length > 0 && (
              <div className="border-t border-gray-100 pt-4">
                <div className="text-xs text-gray-400 mb-2">辅助证据·历史相似案例</div>
                <div className="grid grid-cols-2 gap-3">
                  {similarCases.map((case_, idx) => (
                    <SimilarCaseCard
                      key={idx}
                      similarity={`${Math.round(case_.similarity * 100)}%`}
                      title={case_.title}
                      modules={[]}
                      risk={case_.risk_level}
                      result={case_.outcome}
                    />
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* ── 依据与人工复核 ── */}
          <div className="bg-white rounded-xl border border-gray-200 p-5 mb-4">
            <h3 className="text-sm font-medium text-gray-900 mb-4">依据与人工复核</h3>

            {/* Confidence + Sources */}
            <div className="grid grid-cols-2 gap-5 mb-4">
              <div>
                <div className="text-xs text-gray-400 mb-2">AI 置信度</div>
                <div className="flex items-center gap-3">
                  <div className="flex-1 bg-gray-100 rounded-full h-2 overflow-hidden">
                    <div
                      className="bg-blue-500 h-full rounded-full"
                      style={{ width: `${analysis.confidence_score || 0}%` }}
                    />
                  </div>
                  <span className="text-base font-semibold text-gray-900 flex-shrink-0">
                    {Math.round(analysis.confidence_score || 0)}%
                  </span>
                </div>
                <p className="text-xs text-gray-400 mt-1">基于历史数据和模块映射关系</p>
              </div>
              <div>
                <div className="text-xs text-gray-400 mb-2">证据来源</div>
                <div className="flex flex-wrap gap-1.5">
                  {['历史相似改动', '模块映射', '影响分析'].map((s) => (
                    <span key={s} className="px-2 py-1 bg-gray-100 text-gray-600 rounded text-xs">
                      {s}
                    </span>
                  ))}
                </div>
              </div>
            </div>

            {/* Why conclusion - summary */}
            {analysis.evidence_summary && (
              <div className="mb-4 bg-gray-50 rounded-lg p-3 border border-gray-100">
                <div className="text-xs text-gray-400 mb-2">结论摘要</div>
                <p className="text-xs text-gray-700 leading-relaxed">{analysis.evidence_summary}</p>
              </div>
            )}

            {/* Additional info needed */}
            {analysis.missing_information && (
              <div className="mb-4">
                <div className="text-xs text-gray-400 mb-2">还需补充</div>
                <p className="text-xs text-gray-700 leading-relaxed">{analysis.missing_information}</p>
              </div>
            )}

            {/* Toggles */}
            <div className="flex items-center gap-4 border-t border-gray-100 pt-3">
              <button
                onClick={() => setShowWhyReasoning(!showWhyReasoning)}
                className="flex items-center gap-1.5 text-xs text-gray-500 hover:text-gray-700"
              >
                {showWhyReasoning ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
                为什么得出这个结论
              </button>
              <button
                onClick={() => setShowTechnicalDetails(!showTechnicalDetails)}
                className="flex items-center gap-1.5 text-xs text-gray-500 hover:text-gray-700"
              >
                {showTechnicalDetails ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
                详细技术依据（接口 / 数据表）
              </button>
            </div>

            {showWhyReasoning && (
              <div className="mt-3 bg-gray-50 rounded-lg p-4 border border-gray-100 text-xs text-gray-700 space-y-2">
                <div>
                  <span className="font-medium text-gray-800">分析依据：</span>
                  AI 基于事项的描述信息、历史相似案例和模块映射关系进行综合分析。
                </div>
                <div>
                  <span className="font-medium text-gray-800">风险判断：</span>
                  {analysis.risk_level === 'high'
                    ? '该事项涉及核心模块或高风险区域，建议谨慎评估。'
                    : '该事项影响范围可控，可按正常流程推进。'}
                </div>
              </div>
            )}

            {showTechnicalDetails && (
              <div className="mt-3 bg-gray-50 rounded-lg p-4 border border-gray-100">
                <div className="grid grid-cols-2 gap-4 text-xs">
                  <div>
                    <div className="font-medium text-gray-700 mb-1.5">涉及接口（示例）</div>
                    <div className="space-y-1 font-mono text-gray-500">
                      <div>GET /api/v1/items/{analysis.item_id}</div>
                      <div>GET /api/v1/analysis/{analysis.id}</div>
                    </div>
                  </div>
                  <div>
                    <div className="font-medium text-gray-700 mb-1.5">涉及数据表（示例）</div>
                    <div className="space-y-1 font-mono text-gray-500">
                      <div>items (id: {analysis.item_id})</div>
                      <div>analysis (id: {analysis.id})</div>
                    </div>
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* ── 动作区 ── */}
          {isPendingReview && (
            <div className="bg-white rounded-xl border border-gray-200 p-5">
              <div className="flex items-center gap-3 flex-wrap">
                {/* Primary - Confirm */}
                <button
                  onClick={handleConfirm}
                  disabled={confirming}
                  className="px-6 py-2.5 rounded-xl font-medium text-sm transition-all shadow-sm flex items-center gap-2 bg-blue-600 text-white hover:bg-blue-700 hover:shadow-md disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {confirming ? (
                    <>
                      <Loader2 className="w-4 h-4 animate-spin" />
                      确认中…
                    </>
                  ) : (
                    <>
                      <CheckCircle2 className="w-4 h-4" />
                      确认分析结论
                    </>
                  )}
                </button>

                {/* Action result hint */}
                <div className="flex items-center gap-1.5 text-xs text-gray-400">
                  <ArrowRight className="w-3 h-3" />
                  确认后，事项状态将变为
                  <span className="text-green-600 font-medium">已形成结论</span>，结论正式生效
                </div>

                <div className="ml-auto flex items-center gap-2">
                  {/* Reject */}
                  <button
                    onClick={() => {
                      if (rejectComment.trim() || window.confirm('确定要驳回此分析吗？')) {
                        handleReject();
                      }
                    }}
                    disabled={rejecting}
                    className="px-4 py-2.5 bg-white border border-red-300 text-red-700 rounded-xl hover:border-red-400 hover:bg-red-50 text-sm transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {rejecting ? (
                      <>
                        <Loader2 className="w-4 h-4 animate-spin inline mr-1" />
                        驳回中…
                      </>
                    ) : (
                      <>
                        <XCircle className="w-4 h-4 inline mr-1" />
                        驳回
                      </>
                    )}
                  </button>
                </div>
              </div>

              {/* Reject comment input */}
              <div className="mt-4 pt-4 border-t border-gray-100">
                <label className="text-xs text-gray-500 block mb-2">驳回原因（可选）</label>
                <input
                  type="text"
                  value={rejectComment}
                  onChange={(e) => setRejectComment(e.target.value)}
                  placeholder="请输入驳回原因，如：分析结果不准确、需要补充更多信息等"
                  className="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
            </div>
          )}

          {/* ── 已确认状态 ── */}
          {isConfirmed && (
            <div className="bg-white rounded-xl border border-green-200 p-5">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 bg-green-100 rounded-full flex items-center justify-center">
                  <CheckCircle2 className="w-5 h-5 text-green-600" />
                </div>
                <div className="flex-1">
                  <div className="text-sm font-medium text-gray-900">分析结论已确认</div>
                  <div className="text-xs text-gray-500">事项已进入"已形成结论"状态，可以生成后续输出物</div>
                </div>
                <Link
                  to={`/items/${analysis.item_id}`}
                  className="px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 text-sm font-medium transition-colors"
                >
                  返回事项
                </Link>
              </div>
            </div>
          )}
        </>
      )}
    </main>
  );
}

/* ── Sub-components ── */

function StepPill({
  label,
  done,
  active,
  upcoming,
}: {
  label: string;
  done?: boolean;
  active?: boolean;
  upcoming?: boolean;
}) {
  return (
    <div className="flex items-center gap-1.5 flex-shrink-0">
      <span
        className={`w-2 h-2 rounded-full flex-shrink-0 ${
          done
            ? 'bg-green-500'
            : active
            ? 'bg-blue-500 ring-2 ring-blue-200'
            : 'bg-gray-300'
        }`}
      />
      <span
        className={`text-xs ${
          active ? 'text-gray-900 font-medium' : done ? 'text-gray-600' : 'text-gray-400'
        }`}
      >
        {label}
      </span>
    </div>
  );
}

function StepConnector() {
  return <ArrowRight className="w-3 h-3 text-gray-300 flex-shrink-0 mx-2" />;
}

function NextActionChip({
  icon: Icon,
  label,
  highlighted,
}: {
  icon: any;
  label: string;
  highlighted?: boolean;
}) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs border ${
        highlighted
          ? 'border-blue-200 bg-blue-50 text-blue-700'
          : 'border-gray-200 bg-gray-50 text-gray-600'
      }`}
    >
      <Icon className="w-3 h-3" />
      {label}
      {highlighted && (
        <span className="px-1 py-0.5 text-[10px] bg-blue-200 text-blue-800 rounded">推荐</span>
      )}
    </span>
  );
}

function SimilarCaseCard({
  similarity,
  title,
  modules,
  risk,
  result,
}: {
  similarity: string;
  title: string;
  modules: string[];
  risk: string;
  result: string;
}) {
  return (
    <div className="bg-gray-50 border border-gray-200 rounded-lg p-3">
      <div className="flex items-center gap-2 mb-2">
        <span className="text-[10px] px-1.5 py-0.5 bg-blue-100 text-blue-700 rounded">
          相似度 {similarity}
        </span>
        <span className="text-xs font-medium text-gray-800">{title}</span>
        <span className="ml-auto text-[10px] px-1.5 py-0.5 bg-yellow-100 text-yellow-700 rounded flex-shrink-0">
          风险 {risk}
        </span>
      </div>
      {modules.length > 0 && (
        <div className="flex flex-wrap gap-1 mb-1.5">
          {modules.map((m) => (
            <span key={m} className="text-[10px] px-1.5 py-0.5 bg-white text-gray-500 rounded border border-gray-200">
              {m}
            </span>
          ))}
        </div>
      )}
      <div className="text-[10px] text-gray-500">
        <span className="font-medium">结果：</span>
        {result}
      </div>
    </div>
  );
}
