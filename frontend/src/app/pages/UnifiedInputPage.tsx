import { useState } from 'react';
import { useNavigate, Link } from 'react-router';
import {
  Sparkles,
  MessageSquare,
  FileText,
  Calendar,
  Bug,
  Ticket,
  AlertCircle,
  CheckCircle2,
  Loader2,
  ArrowRight,
  ChevronDown,
  ChevronUp,
  GitBranch,
  XCircle,
} from 'lucide-react';
import { itemApi } from '../lib/api';

type InputState = 'empty' | 'analyzing' | 'completed' | 'error';

// Source type mapping
const SOURCE_TYPE_MAP = {
  '客户反馈': 'customer_feedback',
  '新需求': 'new_requirement',
  '会议内容': 'meeting_note',
  'Bug': 'bug_report',
  '工单': 'ticket',
} as const;

type SourceTypeKey = keyof typeof SOURCE_TYPE_MAP;
type SourceTypeValue = typeof SOURCE_TYPE_MAP[SourceTypeKey];

export default function UnifiedInputPage() {
  const navigate = useNavigate();
  const [inputState, setInputState] = useState<InputState>('empty');
  const [inputText, setInputText] = useState('');
  const [showMoreActions, setShowMoreActions] = useState(false);
  const [selectedSource, setSelectedSource] = useState<SourceTypeKey | null>(null);
  const [errorMessage, setErrorMessage] = useState('');
  const [createdItemId, setCreatedItemId] = useState<number | null>(null);
  const [aiSuggestion, setAiSuggestion] = useState<any>(null);

  const exampleInput =
    '客户希望审批节点支持抄送，并且通知内容要能区分审批人和抄送人，目前老流程里通知经常看不清。';

  async function handleAnalyze() {
    if (!inputText.trim()) return;

    setInputState('analyzing');
    setErrorMessage('');

    try {
      // Step 1: Create draft
      const sourceType: SourceTypeValue = selectedSource
        ? SOURCE_TYPE_MAP[selectedSource]
        : 'other';

      const draftResponse = await itemApi.createDraft({
        raw_input: inputText.trim(),
        source_type: sourceType,
      }) as any;

      if (draftResponse.code !== 201) {
        throw new Error(draftResponse.message || '创建事项失败');
      }

      const itemId = draftResponse.data.id;
      setCreatedItemId(itemId);

      // Step 2: Call understand API
      const understandResponse = await itemApi.understand(itemId) as any;

      if (understandResponse.code !== 200) {
        throw new Error(understandResponse.message || 'AI 分析失败');
      }

      // Store AI suggestion for display
      setAiSuggestion(understandResponse.data.suggestion);
      setInputState('completed');

    } catch (error: any) {
      console.error('Analysis error:', error);
      setErrorMessage(error.message || '处理失败，请重试');
      setInputState('error');
    }
  }

  function handleClear() {
    setInputText('');
    setInputState('empty');
    setErrorMessage('');
    setCreatedItemId(null);
    setAiSuggestion(null);
  }

  function handleContinue() {
    if (createdItemId) {
      navigate(`/items/${createdItemId}`);
    }
  }

  function handleRetry() {
    setErrorMessage('');
    setInputState('empty');
  }

  return (
    <main className="max-w-[1400px] mx-auto px-8 py-7">
      {/* Page Header */}
      <div className="mb-5">
        <h1 className="text-lg font-medium text-gray-900 mb-0.5">统一输入</h1>
        <p className="text-sm text-gray-500">把内容粘贴进来，AI 自动帮你整理分析</p>
      </div>

      <div className="grid grid-cols-3 gap-5">
        {/* ── Left: Input Area ── */}
        <div className="col-span-2 space-y-4">
          <div className="bg-white rounded-xl border border-gray-200 p-5 shadow-sm">
            {/* Header */}
            <div className="flex items-center gap-3 mb-4">
              <div className="w-8 h-8 bg-blue-50 rounded-lg flex items-center justify-center flex-shrink-0">
                <Sparkles className="w-4 h-4 text-blue-600" />
              </div>
              <div className="flex-1">
                <h2 className="text-sm font-medium text-gray-900">输入内容</h2>
                <p className="text-xs text-gray-400">粘贴任何内容，AI 会自动识别类型并给出建议</p>
              </div>
            </div>

            {/* Textarea */}
            <textarea
              value={inputText}
              onChange={(e) => setInputText(e.target.value)}
              placeholder="把客户反馈、需求描述、会议内容或问题粘贴到这里，我会自动帮你整理"
              className="w-full h-44 px-4 py-3 bg-gray-50 border border-gray-200 rounded-lg resize-none text-sm text-gray-900 placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              disabled={inputState === 'analyzing'}
            />

            {/* Light hint */}
            <p className="text-xs text-gray-400 mt-2 mb-4 flex items-center gap-1">
              <ArrowRight className="w-3 h-3 flex-shrink-0" />
              提交后将生成一个「待确认事项」，并自动给出类型、优先级和下一步建议
            </p>

            {/* Actions row */}
            <div className="flex items-center justify-between">
              <button
                onClick={() => setInputText(exampleInput)}
                className="text-xs text-gray-400 hover:text-gray-700 transition-colors"
              >
                加载示例
              </button>
              <div className="flex items-center gap-2">
                {inputText && (
                  <button
                    onClick={handleClear}
                    className="px-3 py-1.5 text-xs text-gray-500 hover:text-gray-800 transition-colors"
                    disabled={inputState === 'analyzing'}
                  >
                    清空
                  </button>
                )}
                <button
                  onClick={handleAnalyze}
                  disabled={!inputText.trim() || inputState === 'analyzing'}
                  className="px-5 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 text-sm font-medium disabled:opacity-40 disabled:cursor-not-allowed flex items-center gap-2 transition-colors"
                >
                  {inputState === 'analyzing' ? (
                    <>
                      <Loader2 className="w-3.5 h-3.5 animate-spin" />
                      分析中…
                    </>
                  ) : (
                    '开始分析'
                  )}
                </button>
              </div>
            </div>
          </div>

          {/* Input source tags — compact and selectable */}
          <div className="flex items-center gap-2 flex-wrap px-1">
            <span className="text-xs text-gray-400">选择类型（可选）：</span>
            {[
              { icon: MessageSquare, label: '客户反馈' as SourceTypeKey },
              { icon: FileText,      label: '新需求' as SourceTypeKey },
              { icon: Calendar,      label: '会议内容' as SourceTypeKey },
              { icon: Bug,           label: 'Bug' as SourceTypeKey },
              { icon: Ticket,        label: '工单' as SourceTypeKey },
            ].map(({ icon: Icon, label }) => {
              const isSelected = selectedSource === label;
              return (
                <button
                  key={label}
                  onClick={() => setSelectedSource(isSelected ? null : label)}
                  disabled={inputState === 'analyzing'}
                  className={`inline-flex items-center gap-1.5 px-2.5 py-1 border rounded-lg text-xs transition-all ${
                    isSelected
                      ? 'bg-blue-50 border-blue-300 text-blue-700'
                      : 'bg-gray-50 border-gray-200 text-gray-600 hover:bg-gray-100'
                  } disabled:opacity-50 disabled:cursor-not-allowed`}
                >
                  <Icon className="w-3 h-3" />
                  {label}
                </button>
              );
            })}
            {selectedSource && (
              <button
                onClick={() => setSelectedSource(null)}
                disabled={inputState === 'analyzing'}
                className="text-xs text-gray-400 hover:text-gray-600 disabled:opacity-50"
              >
                清除选择
              </button>
            )}
          </div>
        </div>

        {/* ── Right: AI Result / States ── */}
        <div className="space-y-4">
          {inputState === 'empty' && <EmptyState />}
          {inputState === 'analyzing' && <AnalyzingState />}
          {inputState === 'error' && (
            <ErrorState
              message={errorMessage}
              onRetry={handleRetry}
            />
          )}
          {inputState === 'completed' && (
            <CompletedState
              suggestion={aiSuggestion}
              onContinue={handleContinue}
              showMoreActions={showMoreActions}
              setShowMoreActions={setShowMoreActions}
            />
          )}
        </div>
      </div>
    </main>
  );
}

/* ── Empty state — minimal ── */
function EmptyState() {
  return (
    <div className="bg-gray-50 border border-dashed border-gray-200 rounded-xl p-6 text-center">
      <Sparkles className="w-5 h-5 text-gray-300 mx-auto mb-2" />
      <p className="text-xs text-gray-400">输入内容后，AI 会自动分析并给出建议</p>
    </div>
  );
}

/* ── Error state ── */
function ErrorState({
  message,
  onRetry,
}: {
  message: string;
  onRetry: () => void;
}) {
  return (
    <div className="bg-red-50 border border-red-200 rounded-xl p-6 text-center">
      <XCircle className="w-5 h-5 text-red-500 mx-auto mb-2" />
      <p className="text-sm font-medium text-red-800 mb-1">处理失败</p>
      <p className="text-xs text-red-600 mb-3">{message}</p>
      <button
        onClick={onRetry}
        className="px-4 py-1.5 bg-red-100 text-red-700 rounded-lg hover:bg-red-200 text-xs font-medium transition-colors"
      >
        重试
      </button>
    </div>
  );
}

/* ── Analyzing state ── */
function AnalyzingState() {
  return (
    <div className="bg-white border border-gray-200 rounded-xl p-6 text-center">
      <div className="w-9 h-9 bg-blue-50 rounded-lg flex items-center justify-center mx-auto mb-3">
        <Loader2 className="w-5 h-5 text-blue-600 animate-spin" />
      </div>
      <p className="text-sm font-medium text-gray-800 mb-1">AI 分析中…</p>
      <p className="text-xs text-gray-400">正在识别内容并生成事项建议</p>
    </div>
  );
}

/* ── Completed state ── */
function CompletedState({
  suggestion,
  onContinue,
  showMoreActions,
  setShowMoreActions,
}: {
  suggestion: any;
  onContinue: () => void;
  showMoreActions: boolean;
  setShowMoreActions: (v: boolean) => void;
}) {
  // Helper function to get priority badge color
  const getPriorityColor = (priority: string) => {
    const colorMap: Record<string, 'blue' | 'red' | 'green' | 'gray'> = {
      low: 'blue',
      medium: 'blue',
      high: 'red',
      critical: 'red',
    };
    return colorMap[priority] || 'blue';
  };

  // Parse pending questions from JSON if available
  const pendingQuestions = suggestion?.pending_questions_json
    ? (typeof suggestion.pending_questions_json === 'string'
        ? JSON.parse(suggestion.pending_questions_json)
        : suggestion.pending_questions_json)
    : [];

  return (
    <div className="space-y-3">
      {/* AI Suggestions Card */}
      <div className="bg-white rounded-xl border border-gray-200 p-5">
        <div className="flex items-center gap-2 mb-4">
          <CheckCircle2 className="w-4 h-4 text-green-600" />
          <span className="text-sm font-medium text-gray-900">AI 识别结果</span>
          <span className="ml-auto inline-flex items-center gap-1 px-2 py-0.5 bg-blue-50 text-blue-600 rounded text-[10px]">
            <Sparkles className="w-2.5 h-2.5" />
            AI 建议
          </span>
        </div>

        <div className="space-y-3">
          {/* Title */}
          <AiField
            label="AI 标题建议"
            value={suggestion?.title_suggestion || '暂无建议'}
          />

          {/* Type and Priority */}
          <div className="grid grid-cols-2 gap-3">
            <AiField
              label="AI 类型建议"
              value={suggestion?.type_suggestion || '暂无建议'}
              badge
              badgeColor="blue"
            />
            <AiField
              label="AI 优先级建议"
              value={suggestion?.priority_suggestion || '暂无建议'}
              badge
              badgeColor={suggestion?.priority_suggestion ? getPriorityColor(suggestion.priority_suggestion) : 'blue'}
            />
          </div>

          {/* Project */}
          {suggestion?.project_suggestion && (
            <AiField
              label="AI 项目建议"
              value={suggestion.project_suggestion}
              badge
              badgeColor="gray"
            />
          )}

          {/* Pending Questions */}
          {pendingQuestions.length > 0 && (
            <div>
              <div className="flex items-center gap-1.5 mb-1.5">
                <AlertCircle className="w-3 h-3 text-yellow-600" />
                <span className="text-xs text-gray-400">AI 待确认问题</span>
              </div>
              <div className="bg-yellow-50 border border-yellow-200 rounded-lg px-3 py-2.5 text-xs text-yellow-900 space-y-1">
                {pendingQuestions.map((question: string, idx: number) => (
                  <div key={idx} className="flex items-start gap-1.5">
                    <span className="text-yellow-500 flex-shrink-0">·</span>
                    {question}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Recommendation */}
          {suggestion?.recommendation_suggestion && (
            <div>
              <div className="flex items-center gap-1.5 mb-1.5">
                <Sparkles className="w-3 h-3 text-blue-600" />
                <span className="text-xs text-gray-400">AI 推荐操作</span>
              </div>
              <div className="bg-blue-50 border border-blue-200 rounded-lg px-3 py-2.5 text-xs text-blue-900">
                {suggestion.recommendation_suggestion}
              </div>
            </div>
          )}
        </div>

        <p className="text-[10px] text-gray-400 mt-3 leading-relaxed">
          以上为 AI 建议，不是最终结果，进入事项处理页后可修改
        </p>
      </div>

      {/* Actions Card */}
      <div className="bg-white rounded-xl border border-gray-200 p-4">
        <div className="text-xs text-gray-400 mb-3">推进下一步</div>

        <div className="space-y-2">
          {/* Primary */}
          <button
            onClick={onContinue}
            className="w-full flex items-center justify-center gap-2 px-4 py-2.5 bg-blue-600 text-white rounded-xl hover:bg-blue-700 text-sm font-medium shadow-sm transition-all"
          >
            <CheckCircle2 className="w-4 h-4" />
            继续处理
          </button>

          {/* Action hint */}
          <div className="flex items-start gap-1.5 px-0.5">
            <ArrowRight className="w-3 h-3 text-gray-400 flex-shrink-0 mt-0.5" />
            <p className="text-[10px] text-gray-400 leading-relaxed">
              进入事项处理页，当前内容将以「待确认事项」方式继续推进
            </p>
          </div>

          {/* Secondary */}
          <Link to="/impact">
            <button className="w-full flex items-center gap-2 px-4 py-2 bg-blue-50 text-blue-700 border border-blue-200 rounded-lg hover:bg-blue-100 text-xs font-medium transition-colors mt-1">
              <GitBranch className="w-3.5 h-3.5" />
              发起影响分析
            </button>
          </Link>

          {/* More actions toggle */}
          <button
            onClick={() => setShowMoreActions(!showMoreActions)}
            className="w-full flex items-center justify-between px-3 py-1.5 text-xs text-gray-400 hover:text-gray-600 transition-colors"
          >
            <span>更多操作</span>
            {showMoreActions
              ? <ChevronUp className="w-3.5 h-3.5" />
              : <ChevronDown className="w-3.5 h-3.5" />
            }
          </button>

          {showMoreActions && (
            <div className="border-t border-gray-100 pt-2 space-y-1">
              {['保存草稿', '生成纪要', '生成测试点'].map((label) => (
                <button
                  key={label}
                  className="w-full px-3 py-2 text-xs text-gray-500 hover:bg-gray-50 rounded-lg transition-colors text-left"
                >
                  {label}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

/* ── AI field ── */
function AiField({
  label,
  value,
  badge,
  badgeColor = 'blue',
}: {
  label: string;
  value: string;
  badge?: boolean;
  badgeColor?: 'blue' | 'red' | 'green' | 'gray';
}) {
  const badgeCls: Record<string, string> = {
    blue:  'bg-blue-50 text-blue-700',
    red:   'bg-red-50 text-red-700',
    green: 'bg-green-50 text-green-700',
    gray:  'bg-gray-100 text-gray-600',
  };

  return (
    <div>
      <div className="flex items-center gap-1 mb-1">
        <Sparkles className="w-2.5 h-2.5 text-blue-400" />
        <span className="text-[10px] text-gray-400">{label}</span>
      </div>
      {badge ? (
        <span className={`inline-block text-xs px-2.5 py-1 rounded ${badgeCls[badgeColor]}`}>
          {value}
        </span>
      ) : (
        <div className="text-sm font-medium text-gray-900">{value}</div>
      )}
    </div>
  );
}
