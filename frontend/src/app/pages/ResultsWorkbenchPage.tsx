import { useState, useEffect } from 'react';
import { useParams, Link, useNavigate } from 'react-router';
import {
  FileText,
  ClipboardList,
  Sparkles,
  CheckCircle2,
  Edit3,
  Copy,
  Download,
  FolderUp,
  ArrowLeft,
  Clock,
  ArrowRight,
  AlertCircle,
  Tag,
  Loader2,
  Plus,
  Lightbulb,
} from 'lucide-react';
import { useOutputsByItem, useOutput } from '../hooks';
import { LoadingSpinner, ErrorState, EmptyState } from '../components/loading';
import {
  OUTPUT_TYPE_LABELS,
  OUTPUT_STATUS_LABELS,
  OUTPUT_STATUS_COLORS,
  ADOPTED_TARGET_LABELS,
  OUTPUT_TYPE_TO_ADOPTED_TARGET,
  type Output,
  type OutputListItem,
} from '../types';
import { outputApi } from '../lib/api';

export default function ResultsWorkbenchPage() {
  const { itemId } = useParams<{ itemId: string }>();
  const id = itemId ? parseInt(itemId, 10) : null;
  const navigate = useNavigate();

  // UI state
  const [selectedOutputId, setSelectedOutputId] = useState<number | null>(null);
  const [isEditing, setIsEditing] = useState(false);
  const [showCreateModal, setShowCreateModal] = useState(false);

  // Action states
  const [confirming, setConfirming] = useState(false);
  const [adopting, setAdopting] = useState(false);
  const [creating, setCreating] = useState(false);

  // Fetch data
  const { data: outputs, loading: outputsLoading, error: outputsError, refetch: refetchOutputs } = useOutputsByItem(id);
  const { data: selectedOutput, loading: outputLoading, error: outputError, refetch: refetchOutput } = useOutput(selectedOutputId);

  // Auto-select first output when list loads
  useEffect(() => {
    if (outputs && outputs.length > 0 && !selectedOutputId) {
      setSelectedOutputId(outputs[0].id);
    }
  }, [outputs, selectedOutputId]);

  // Filter
  const [selectedType, setSelectedType] = useState<'all' | 'prd' | 'test_points' | 'handling_advice'>('all');
  const filteredOutputs = outputs
    ? selectedType === 'all'
      ? outputs
      : outputs.filter((o) => o.output_type === selectedType)
    : [];

  // Handle create output
  async function handleCreate(outputType: 'prd' | 'test_points' | 'handling_advice') {
    if (!id || creating) return;

    setCreating(true);
    try {
      const response = await outputApi.create(id, { output_type: outputType }) as any;
      if (response.code !== 200) {
        throw new Error(response.message || '创建输出失败');
      }
      await refetchOutputs();
      // Select the newly created output
      if (response.data?.id) {
        setSelectedOutputId(response.data.id);
      }
      setShowCreateModal(false);
    } catch (err: any) {
      console.error('Create output error:', err);
      alert(err.message || '创建输出失败，请重试');
    } finally {
      setCreating(false);
    }
  }

  // Handle confirm output
  async function handleConfirm() {
    if (!selectedOutputId || confirming || !selectedOutput) return;

    setConfirming(true);
    try {
      const response = await outputApi.confirm(selectedOutputId) as any;
      if (response.code !== 200) {
        throw new Error(response.message || '确认输出失败');
      }
      await refetchOutput();
      await refetchOutputs();
    } catch (err: any) {
      console.error('Confirm output error:', err);
      alert(err.message || '确认输出失败，请重试');
    } finally {
      setConfirming(false);
    }
  }

  // Handle adopt output
  async function handleAdopt() {
    if (!selectedOutputId || adopting || !selectedOutput) return;

    const adoptedTarget = OUTPUT_TYPE_TO_ADOPTED_TARGET[selectedOutput.output_type];
    if (!adoptedTarget) {
      alert('无法确定采用目标');
      return;
    }

    setAdopting(true);
    try {
      const response = await outputApi.adopt(selectedOutputId, { adopted_target: adoptedTarget }) as any;
      if (response.code !== 200) {
        throw new Error(response.message || '采用输出失败');
      }
      await refetchOutput();
      await refetchOutputs();
    } catch (err: any) {
      console.error('Adopt output error:', err);
      alert(err.message || '采用输出失败，请重试');
    } finally {
      setAdopting(false);
    }
  }

  // Loading state
  if (outputsLoading) {
    return (
      <main className="h-screen flex items-center justify-center">
        <LoadingSpinner />
      </main>
    );
  }

  // Error state
  if (outputsError) {
    return (
      <main className="h-screen flex items-center justify-center px-8">
        <ErrorState message={outputsError} />
      </main>
    );
  }

  // No itemId
  if (!id) {
    return (
      <main className="h-screen flex items-center justify-center px-8">
        <ErrorState message="缺少事项 ID" />
      </main>
    );
  }

  const filterBtns = [
    { key: 'all', label: '全部' },
    { key: 'prd', label: 'PRD 初稿' },
    { key: 'test_points', label: '测试点' },
    { key: 'handling_advice', label: '处理建议' },
  ] as const;

  return (
    <main className="h-screen flex flex-col">
      {/* ── Top Header ── */}
      <div className="border-b border-gray-200 bg-white px-8 py-3">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-4">
            <Link
              to={`/items/${id}`}
              className="flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-900"
            >
              <ArrowLeft className="w-3.5 h-3.5" />
              返回事项详情
            </Link>
            <div className="w-px h-4 bg-gray-200" />
            <h1 className="text-base font-medium text-gray-900">输出物工作台</h1>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setShowCreateModal(true)}
              className="px-3 py-1.5 bg-blue-600 text-white text-xs rounded-lg hover:bg-blue-700 flex items-center gap-1.5"
            >
              <Plus className="w-3.5 h-3.5" />
              生成输出
            </button>
            <span className="text-xs text-gray-400">{filteredOutputs.length} 个输出物</span>
          </div>
        </div>

        {/* Type Filters */}
        <div className="flex items-center gap-1.5">
          {filterBtns.map(({ key, label }) => (
            <button
              key={key}
              onClick={() => setSelectedType(key)}
              className={`px-3 py-1 text-xs rounded-lg transition-colors ${
                selectedType === key
                  ? 'bg-blue-600 text-white'
                  : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {/* ── Split View ── */}
      <div className="flex-1 flex overflow-hidden">
        {/* ── Left: Outputs Queue ── */}
        <div className="w-80 border-r border-gray-200 bg-gray-50 overflow-y-auto flex-shrink-0">
          {filteredOutputs.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full text-center px-6">
              <FileText className="w-8 h-8 text-gray-300 mb-3" />
              <p className="text-xs text-gray-500">暂无输出物</p>
              <button
                onClick={() => setShowCreateModal(true)}
                className="mt-3 px-3 py-1.5 bg-blue-600 text-white text-xs rounded-lg hover:bg-blue-700"
              >
                生成第一个输出
              </button>
            </div>
          ) : (
            <div className="p-3 space-y-1.5">
              <div className="px-1 py-1 text-[10px] text-gray-400 uppercase tracking-wide">
                输出物列表
              </div>
              {filteredOutputs.map((output) => (
                <OutputCard
                  key={output.id}
                  output={output}
                  selected={output.id === selectedOutputId}
                  onClick={() => {
                    setSelectedOutputId(output.id);
                    setIsEditing(false);
                  }}
                />
              ))}
            </div>
          )}
        </div>

        {/* ── Right: Detail ── */}
        {selectedOutput ? (
          <OutputDetail
            output={selectedOutput}
            loading={outputLoading}
            error={outputError}
            isEditing={isEditing}
            setIsEditing={setIsEditing}
            confirming={confirming}
            adopting={adopting}
            onConfirm={handleConfirm}
            onAdopt={handleAdopt}
            onRefetch={refetchOutput}
          />
        ) : (
          <div className="flex-1 flex items-center justify-center bg-gray-50">
            <div className="text-center">
              <FileText className="w-8 h-8 text-gray-300 mx-auto mb-3" />
              <p className="text-sm text-gray-500">请选择一个输出物查看详情</p>
            </div>
          </div>
        )}
      </div>

      {/* ── Create Modal ── */}
      {showCreateModal && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white rounded-xl p-6 w-full max-w-md">
            <h2 className="text-lg font-medium text-gray-900 mb-4">生成输出物</h2>
            <div className="space-y-2">
              <button
                onClick={() => handleCreate('prd')}
                disabled={creating}
                className="w-full px-4 py-3 bg-white border border-gray-200 rounded-lg hover:border-blue-400 hover:bg-blue-50 text-left flex items-center gap-3 transition-colors disabled:opacity-50"
              >
                <div className="w-8 h-8 bg-blue-100 rounded-lg flex items-center justify-center flex-shrink-0">
                  <FileText className="w-4 h-4 text-blue-600" />
                </div>
                <div>
                  <div className="text-sm font-medium text-gray-900">PRD 初稿</div>
                  <div className="text-xs text-gray-500">产品需求文档</div>
                </div>
              </button>
              <button
                onClick={() => handleCreate('test_points')}
                disabled={creating}
                className="w-full px-4 py-3 bg-white border border-gray-200 rounded-lg hover:border-blue-400 hover:bg-blue-50 text-left flex items-center gap-3 transition-colors disabled:opacity-50"
              >
                <div className="w-8 h-8 bg-green-100 rounded-lg flex items-center justify-center flex-shrink-0">
                  <ClipboardList className="w-4 h-4 text-green-600" />
                </div>
                <div>
                  <div className="text-sm font-medium text-gray-900">测试点</div>
                  <div className="text-xs text-gray-500">测试要点清单</div>
                </div>
              </button>
              <button
                onClick={() => handleCreate('handling_advice')}
                disabled={creating}
                className="w-full px-4 py-3 bg-white border border-gray-200 rounded-lg hover:border-blue-400 hover:bg-blue-50 text-left flex items-center gap-3 transition-colors disabled:opacity-50"
              >
                <div className="w-8 h-8 bg-yellow-100 rounded-lg flex items-center justify-center flex-shrink-0">
                  <Lightbulb className="w-4 h-4 text-yellow-600" />
                </div>
                <div>
                  <div className="text-sm font-medium text-gray-900">处理建议</div>
                  <div className="text-xs text-gray-500">处理方案建议</div>
                </div>
              </button>
            </div>
            <div className="mt-4 pt-4 border-t border-gray-100 flex justify-end">
              <button
                onClick={() => setShowCreateModal(false)}
                disabled={creating}
                className="px-4 py-2 text-sm text-gray-700 hover:text-gray-900 disabled:opacity-50"
              >
                取消
              </button>
            </div>
            {creating && (
              <div className="mt-2 text-center text-xs text-gray-500">正在生成...</div>
            )}
          </div>
        </div>
      )}
    </main>
  );
}

/* ── Output Card (left list) ── */
function OutputCard({
  output,
  selected,
  onClick,
}: {
  output: OutputListItem;
  selected: boolean;
  onClick: () => void;
}) {
  const sc = OUTPUT_STATUS_COLORS[output.status];
  const sl = OUTPUT_STATUS_LABELS[output.status];

  return (
    <button
      onClick={onClick}
      className={`w-full text-left px-3 py-2.5 rounded-lg border transition-all ${
        selected
          ? 'bg-white border-blue-400 shadow-sm'
          : 'bg-white border-transparent hover:border-gray-300'
      }`}
    >
      <div className="flex items-start gap-2.5">
        <div className="w-6 h-6 bg-gray-100 rounded flex items-center justify-center flex-shrink-0 mt-0.5 text-xs">
          {output.output_type === 'prd' ? '📄' : output.output_type === 'test_points' ? '✅' : '💡'}
        </div>
        <div className="flex-1 min-w-0">
          {/* Title + status */}
          <div className="flex items-start justify-between gap-2 mb-1">
            <h3 className="text-xs font-medium text-gray-900 leading-snug line-clamp-2 flex-1">{output.title}</h3>
            <span className={`text-[10px] px-1.5 py-0.5 rounded-full flex-shrink-0 ${sc}`}>
              {sl}
            </span>
          </div>
          {/* Type */}
          <div className="flex items-center gap-1.5">
            <span className="text-[10px] px-1.5 py-0.5 bg-gray-100 text-gray-500 rounded">
              {OUTPUT_TYPE_LABELS[output.output_type]}
            </span>
          </div>
          {/* Time */}
          <div className="flex items-center gap-1 mt-1 text-[10px] text-gray-400">
            <Clock className="w-2.5 h-2.5" />
            {new Date(output.created_at).toLocaleString('zh-CN', {
              month: '2-digit',
              day: '2-digit',
              hour: '2-digit',
              minute: '2-digit',
            })}
          </div>
        </div>
      </div>
    </button>
  );
}

/* ── Output Detail Component ── */
function OutputDetail({
  output,
  loading,
  error,
  isEditing,
  setIsEditing,
  confirming,
  adopting,
  onConfirm,
  onAdopt,
  onRefetch,
}: {
  output: Output;
  loading?: boolean;
  error?: string | null;
  isEditing: boolean;
  setIsEditing: (val: boolean) => void;
  confirming: boolean;
  adopting: boolean;
  onConfirm: () => void;
  onAdopt: () => void;
  onRefetch: () => void;
}) {
  if (loading) {
    return (
      <div className="flex-1 flex items-center justify-center bg-white">
        <Loader2 className="w-6 h-6 text-gray-400 animate-spin" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex-1 flex items-center justify-center bg-white">
        <ErrorState message={error} />
      </div>
    );
  }

  const sc = OUTPUT_STATUS_COLORS[output.status];
  const sl = OUTPUT_STATUS_LABELS[output.status];
  const adoptedTargetLabel = output.adopted_target ? ADOPTED_TARGET_LABELS[output.adopted_target] : null;

  return (
    <div className="flex-1 flex flex-col bg-white overflow-hidden">
      {/* ── 输出物状态条 ── */}
      <div className="border-b border-gray-100 bg-gray-50 px-6 py-2.5 flex items-center gap-0 flex-wrap">
        <div className="flex items-center gap-2 mr-4 flex-shrink-0">
          <span className="text-xs text-gray-400">对象类型</span>
          <span className="px-2 py-0.5 text-xs bg-gray-200 text-gray-700 rounded-full">输出物</span>
        </div>

        <div className="w-px h-3.5 bg-gray-200 mr-4 flex-shrink-0" />

        {/* Status */}
        <div className="flex items-center gap-1.5 mr-4 flex-shrink-0">
          <span className="text-xs text-gray-400">当前状态</span>
          <span className={`px-2 py-0.5 text-xs rounded-full ${sc}`}>
            {sl}
          </span>
        </div>

        <div className="w-px h-3.5 bg-gray-200 mr-4 flex-shrink-0" />

        {/* Source item */}
        <div className="flex items-center gap-1.5 mr-4 flex-shrink-0">
          <span className="text-xs text-gray-400">来源事项</span>
          <Link to={`/items/${output.item_id}`} className="text-xs text-blue-600 hover:text-blue-700">
            #{output.item_id}
          </Link>
        </div>

        {output.analysis_id && (
          <>
            <div className="w-px h-3.5 bg-gray-200 mr-4 flex-shrink-0" />
            <div className="flex items-center gap-1.5 mr-4 flex-shrink-0">
              <span className="text-xs text-gray-400">来源分析</span>
              <Link to={`/impact/${output.analysis_id}`} className="text-xs text-blue-600 hover:text-blue-700">
                #{output.analysis_id}
              </Link>
            </div>
          </>
        )}

        {adoptedTargetLabel && (
          <>
            <div className="w-px h-3.5 bg-gray-200 mr-4 flex-shrink-0" />
            <div className="flex items-center gap-1.5 flex-shrink-0">
              <span className="text-xs text-gray-400">采用去向</span>
              <ArrowRight className="w-3 h-3 text-gray-300" />
              <span className="px-2 py-0.5 text-xs bg-blue-50 text-blue-700 rounded-full">
                {adoptedTargetLabel}
              </span>
            </div>
          </>
        )}
      </div>

      {/* Detail Header */}
      <div className="border-b border-gray-200 px-6 py-4">
        <div className="flex items-start gap-3 mb-3">
          <div className="w-8 h-8 bg-gray-100 rounded-lg flex items-center justify-center flex-shrink-0 mt-0.5 text-lg">
            {output.output_type === 'prd' ? '📄' : output.output_type === 'test_points' ? '✅' : '💡'}
          </div>
          <div className="flex-1 min-w-0">
            <h2 className="text-base font-medium text-gray-900 mb-1">{output.title}</h2>
            <div className="flex items-center gap-3 text-xs text-gray-400 flex-wrap">
              <span className="px-2 py-0.5 bg-gray-100 text-gray-600 rounded">
                {OUTPUT_TYPE_LABELS[output.output_type]}
              </span>
              <div className="flex items-center gap-1">
                <Clock className="w-3 h-3" />
                <span>
                  {new Date(output.created_at).toLocaleString('zh-CN', {
                    month: '2-digit',
                    day: '2-digit',
                    hour: '2-digit',
                    minute: '2-digit',
                  })}
                </span>
              </div>
              {output.confirmed_at && (
                <div className="flex items-center gap-1">
                  <CheckCircle2 className="w-3 h-3 text-blue-500" />
                  <span>确认于 {new Date(output.confirmed_at).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit' })}</span>
                </div>
              )}
              {output.adopted_at && (
                <div className="flex items-center gap-1">
                  <FolderUp className="w-3 h-3 text-green-500" />
                  <span>采用于 {new Date(output.adopted_at).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit' })}</span>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* AI Summary */}
        {output.summary && (
          <div className="bg-blue-50 border border-blue-100 rounded-lg px-3 py-2.5 flex items-start gap-2">
            <Sparkles className="w-3.5 h-3.5 text-blue-600 flex-shrink-0 mt-0.5" />
            <p className="text-xs text-blue-800">{output.summary}</p>
          </div>
        )}
      </div>

      {/* Detail Content */}
      <div className="flex-1 overflow-y-auto px-6 py-5">
        {/* Content */}
        <div className="mb-5">
          <div className="flex items-center justify-between mb-2">
            <h3 className="text-xs font-medium text-gray-500 uppercase tracking-wide">正文内容</h3>
            {!isEditing && (
              <button
                onClick={() => setIsEditing(true)}
                className="flex items-center gap-1 text-xs text-blue-600 hover:text-blue-700"
              >
                <Edit3 className="w-3.5 h-3.5" />
                编辑
              </button>
            )}
          </div>
          {isEditing ? (
            <div>
              <textarea
                className="w-full h-80 px-4 py-3 border border-gray-300 rounded-lg text-sm font-mono resize-none focus:outline-none focus:ring-2 focus:ring-blue-500"
                defaultValue={output.content}
              />
              <div className="flex items-center gap-2 mt-2">
                <button
                  onClick={() => setIsEditing(false)}
                  className="px-4 py-1.5 bg-blue-600 text-white text-xs rounded-lg hover:bg-blue-700"
                >
                  保存
                </button>
                <button
                  onClick={() => setIsEditing(false)}
                  className="px-4 py-1.5 bg-white border border-gray-300 text-gray-700 text-xs rounded-lg hover:bg-gray-50"
                >
                  取消
                </button>
              </div>
            </div>
          ) : (
            <div className="bg-gray-50 rounded-lg p-4 border border-gray-200">
              <pre className="text-sm text-gray-900 whitespace-pre-wrap font-sans leading-relaxed">
                {output.content}
              </pre>
            </div>
          )}
        </div>

        {/* AI Notes */}
        <div className="bg-gray-50 rounded-lg px-3 py-2.5 border border-gray-100 flex items-start gap-2">
          <Tag className="w-3.5 h-3.5 text-gray-400 flex-shrink-0 mt-0.5" />
          <p className="text-xs text-gray-500">AI 基于事项和分析结果自动生成</p>
        </div>
      </div>

      {/* ── Action Bar ── */}
      <div className="border-t border-gray-200 px-6 py-3.5 bg-white">
        <div className="flex items-center gap-3">
          {/* Primary: Confirm */}
          {output.status === 'pending_confirm' && (
            <button
              onClick={onConfirm}
              disabled={confirming}
              className="flex items-center gap-1.5 px-5 py-2.5 bg-blue-600 text-white rounded-xl hover:bg-blue-700 font-medium text-sm shadow-sm transition-all disabled:opacity-50"
            >
              {confirming ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  确认中…
                </>
              ) : (
                <>
                  <CheckCircle2 className="w-4 h-4" />
                  确认输出
                </>
              )}
            </button>
          )}

          {/* Primary: Adopt */}
          {output.status === 'confirmed' && (
            <button
              onClick={onAdopt}
              disabled={adopting}
              className="flex items-center gap-1.5 px-5 py-2.5 bg-green-600 text-white rounded-xl hover:bg-green-700 font-medium text-sm shadow-sm transition-all disabled:opacity-50"
            >
              {adopting ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  采用中…
                </>
              ) : (
                <>
                  <FolderUp className="w-4 h-4" />
                  采用 · 转{ADOPTED_TARGET_LABELS[OUTPUT_TYPE_TO_ADOPTED_TARGET[output.output_type]]}
                </>
              )}
            </button>
          )}

          {/* Already adopted */}
          {output.status === 'adopted' && (
            <div className="flex items-center gap-1.5 px-4 py-2.5 bg-green-50 text-green-700 rounded-xl border border-green-200 text-sm">
              <CheckCircle2 className="w-4 h-4" />
              已采用 · 事项已完成
            </div>
          )}

          {/* Action hints */}
          <div className="ml-1 flex-1">
            {output.status === 'pending_confirm' && (
              <div className="flex items-center gap-1 text-xs text-gray-400">
                <ArrowRight className="w-3 h-3 flex-shrink-0" />
                <span>
                  确认后状态变为
                  <span className="text-blue-600 font-medium mx-1">已确认</span>；
                  可继续采用或生成其他输出
                </span>
              </div>
            )}
            {output.status === 'confirmed' && (
              <div className="flex items-center gap-1 text-xs text-gray-400">
                <ArrowRight className="w-3 h-3 flex-shrink-0" />
                <span>
                  采用后状态变为
                  <span className="text-green-600 font-medium mx-1">已采用</span>
                  ，事项将标记为完成
                </span>
              </div>
            )}
            {output.status === 'adopted' && (
              <div className="flex items-center gap-1 text-xs text-gray-400">
                <CheckCircle2 className="w-3 h-3 flex-shrink-0" />
                <span>事项已完成，输出物已正式生效</span>
              </div>
            )}
          </div>

          {/* Weak: copy / export */}
          <div className="flex items-center gap-1 ml-auto">
            <button className="p-2 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-lg transition-colors" title="复制">
              <Copy className="w-3.5 h-3.5" />
            </button>
            <button className="p-2 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-lg transition-colors" title="导出">
              <Download className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
