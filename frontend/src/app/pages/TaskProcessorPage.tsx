import { useState } from 'react';
import { Link, useNavigate } from 'react-router';
import {
  ChevronDown,
  ChevronUp,
  Sparkles,
  CheckCircle2,
  AlertCircle,
  FileText,
  GitBranch,
  ClipboardList,
  FolderOpen,
  Save,
  User,
  Calendar,
  Tag,
  ArrowRight,
  MoreHorizontal,
  Info,
} from 'lucide-react';

export default function TaskProcessorPage() {
  const [showReasoning, setShowReasoning] = useState(false);
  const [showMoreActions, setShowMoreActions] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const navigate = useNavigate();

  function handleConfirm() {
    setConfirmed(true);
    setTimeout(() => navigate('/impact'), 800);
  }

  return (
    <main className="max-w-[1600px] mx-auto px-8 py-6">
      {/* Page Header */}
      <div className="mb-4">
        <div className="flex items-center gap-2 mb-1">
          <span className="text-xs text-gray-400">事项处理</span>
          <span className="text-xs text-gray-300">/</span>
          <span className="text-xs text-gray-600">审批节点支持抄送并优化通知内容区分</span>
        </div>
        <h1 className="text-lg font-medium text-gray-900">事项处理</h1>
      </div>

      {/* ── 事项状态条 ── */}
      <div className="mb-5 bg-white border border-gray-200 rounded-xl px-5 py-3 flex items-center gap-0">
        {/* Step 1 */}
        <StatusStep label="输入" sublabel="已完成" done />
        <StepArrow />
        {/* Step 2 - active */}
        <StatusStep label="AI 理解" sublabel="AI 建议" done />
        <StepArrow />
        {/* Step 3 - current */}
        <StatusStep
          label="待确认"
          sublabel="当前步骤"
          active
          tag={{ text: '待确认', color: 'yellow' }}
        />
        <StepArrow />
        {/* Step 4 */}
        <StatusStep
          label="已确认"
          sublabel="确认后变更"
          upcoming
          tag={{ text: '已确认', color: 'green' }}
        />
        <StepArrow />
        {/* Step 5 */}
        <StatusStep label="发起影响分析 / 生成输出物" sublabel="下一步" upcoming />

        {/* Object type pill on the right */}
        <div className="ml-auto flex items-center gap-2 flex-shrink-0">
          <span className="text-xs text-gray-400">对象类型</span>
          <span className="px-2.5 py-0.5 text-xs bg-gray-100 text-gray-700 rounded-full">事项</span>
        </div>
      </div>

      {/* Three Column Layout */}
      <div className="grid grid-cols-12 gap-5">
        {/* ── Left Column - Original Input ── */}
        <div className="col-span-3 space-y-3">
          <div className="bg-white rounded-xl border border-gray-200 p-4">
            <h2 className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-3">原始输入</h2>

            <div className="text-sm text-gray-900 bg-gray-50 p-3 rounded-lg leading-relaxed mb-4">
              客户希望审批节点支持抄送，并且通知内容要能区分审批人和抄送人，目前老流程里通知经常看不清。
            </div>

            <div className="space-y-2.5 border-t border-gray-100 pt-3">
              <InfoRow icon={Tag} label="来源" value="客户反馈" />
              <InfoRow icon={FolderOpen} label="建议项目" value="流程审批重构" badge />
              <InfoRow icon={User} label="输入人" value="张明" />
              <InfoRow icon={Calendar} label="输入时间" value="2026-03-20 14:30" />
            </div>
          </div>
        </div>

        {/* ── Middle Column - AI Understanding ── */}
        <div className="col-span-6 space-y-3">
          {/* AI Suggestions Card */}
          <div className="bg-white rounded-xl border border-gray-200 p-5">
            <div className="flex items-center gap-2 mb-4">
              <Sparkles className="w-4 h-4 text-blue-600" />
              <h2 className="text-sm font-medium text-gray-900">AI 理解结果</h2>
              <span className="ml-auto text-xs text-gray-400">以下均为 AI 建议，确认后生效</span>
            </div>

            <div className="space-y-4">
              {/* Title */}
              <div className="flex items-start gap-3 p-3 bg-gray-50 rounded-lg">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-1.5 mb-1">
                    <span className="text-xs text-gray-400">标题</span>
                    <AiBadge />
                  </div>
                  <div className="text-sm font-medium text-gray-900">
                    审批节点支持抄送并优化通知内容区分
                  </div>
                </div>
                <CheckCircle2 className="w-4 h-4 text-green-500 flex-shrink-0 mt-0.5" />
              </div>

              {/* Type & Priority */}
              <div className="grid grid-cols-2 gap-3">
                <FieldCard
                  label="类型"
                  value="优化需求"
                  badge
                  badgeColor="blue"
                  status="confirmed"
                />
                <FieldCard
                  label="优先级"
                  value="高"
                  badge
                  badgeColor="red"
                  status="pending"
                  riskTag="建议复核"
                />
              </div>

              {/* Modules */}
              <div className="p-3 bg-gray-50 rounded-lg">
                <div className="flex items-center gap-1.5 mb-2">
                  <span className="text-xs text-gray-400">涉及模块</span>
                  <AiBadge />
                </div>
                <div className="flex flex-wrap gap-1.5">
                  <ModuleBadge name="审批流程引擎" />
                  <ModuleBadge name="消息通知中心" />
                </div>
              </div>

              {/* 待确认问题 + 需要补充的信息 — merged block */}
              <div className="border border-yellow-200 bg-yellow-50 rounded-lg p-4 space-y-3">
                <div>
                  <div className="flex items-center gap-2 mb-2">
                    <AlertCircle className="w-3.5 h-3.5 text-yellow-700" />
                    <span className="text-xs font-medium text-yellow-900">AI 待确认问题</span>
                  </div>
                  <ul className="text-sm text-yellow-900 space-y-1.5 pl-1">
                    <li className="flex items-start gap-2">
                      <span className="text-yellow-600 flex-shrink-0 mt-0.5">•</span>
                      <span>是否影响历史流程实例</span>
                    </li>
                    <li className="flex items-start gap-2">
                      <span className="text-yellow-600 flex-shrink-0 mt-0.5">•</span>
                      <span>是否需要抄送人权限控制</span>
                    </li>
                  </ul>
                </div>
                <div className="border-t border-yellow-200 pt-3">
                  <div className="flex items-center gap-1.5 mb-1.5">
                    <Info className="w-3.5 h-3.5 text-yellow-700" />
                    <span className="text-xs font-medium text-yellow-900">建议补充</span>
                  </div>
                  <ul className="text-xs text-yellow-800 space-y-1 pl-1">
                    <li className="flex items-start gap-1.5">
                      <span className="text-yellow-600 flex-shrink-0">·</span>
                      <span>期望上线时间</span>
                    </li>
                    <li className="flex items-start gap-1.5">
                      <span className="text-yellow-600 flex-shrink-0">·</span>
                      <span>是否有紧急客户场景</span>
                    </li>
                    <li className="flex items-start gap-1.5">
                      <span className="text-yellow-600 flex-shrink-0">·</span>
                      <span>预期受影响的流程数量</span>
                    </li>
                  </ul>
                </div>
              </div>

              {/* AI Recommended Action */}
              <div className="border border-blue-200 bg-blue-50 rounded-lg p-3">
                <div className="flex items-start gap-2">
                  <Sparkles className="w-3.5 h-3.5 text-blue-700 flex-shrink-0 mt-0.5" />
                  <div>
                    <span className="text-xs font-medium text-blue-900">AI 推荐动作：</span>
                    <span className="text-xs text-blue-800 ml-1">
                      建议先发起影响分析，确认对历史流程的影响后，再生成 PRD 初稿
                    </span>
                  </div>
                </div>
              </div>

              {/* Similar Cases */}
              <div>
                <div className="text-xs text-gray-400 mb-2">相似历史案例</div>
                <div className="space-y-1.5">
                  <SimilarCase title="审批抄送显示优化" date="2025-12" status="已完成" />
                  <SimilarCase title="通知模板区分改造" date="2025-11" status="已完成" />
                </div>
              </div>
            </div>
          </div>

          {/* Reasoning (Expandable) */}
          <div className="bg-white rounded-xl border border-gray-200">
            <button
              onClick={() => setShowReasoning(!showReasoning)}
              className="w-full px-5 py-3.5 flex items-center justify-between hover:bg-gray-50 transition-colors rounded-xl"
            >
              <span className="text-sm text-gray-600">为什么 AI 做出这个判断</span>
              {showReasoning ? (
                <ChevronUp className="w-4 h-4 text-gray-400" />
              ) : (
                <ChevronDown className="w-4 h-4 text-gray-400" />
              )}
            </button>

            {showReasoning && (
              <div className="px-5 pb-4 border-t border-gray-100">
                <div className="pt-4 space-y-3 text-sm text-gray-600">
                  <div>
                    <div className="text-xs font-medium text-gray-800 mb-1">优先级判断依据</div>
                    <p className="text-xs leading-relaxed">
                      客户明确提出当前流程存在问题（"通知经常看不清"），涉及核心审批功能，影响用户体验，判定为高优先级。
                    </p>
                  </div>
                  <div>
                    <div className="text-xs font-medium text-gray-800 mb-1">模块识别依据</div>
                    <p className="text-xs leading-relaxed">
                      "审批节点"关键词匹配到审批流程引擎，"通知内容"关键词匹配到消息通知中心。
                    </p>
                  </div>
                  <div>
                    <div className="text-xs font-medium text-gray-800 mb-1">相似案例匹配</div>
                    <p className="text-xs leading-relaxed">
                      历史中存在 2 个相似需求，均已成功上线，可参考实施方案。
                    </p>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* ── Right Column - Actions ── */}
        <div className="col-span-3 space-y-3">
          <div className="bg-white rounded-xl border border-gray-200 p-4">
            <h2 className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-4">推进动作</h2>

            <div className="space-y-2.5">
              {/* PRIMARY */}
              <button
                onClick={handleConfirm}
                disabled={confirmed}
                className={`w-full flex items-center justify-center gap-2 px-4 py-3 rounded-xl text-sm font-medium transition-all shadow-sm ${
                  confirmed
                    ? 'bg-green-600 text-white cursor-default'
                    : 'bg-blue-600 text-white hover:bg-blue-700 hover:shadow-md active:scale-[0.99]'
                }`}
              >
                <CheckCircle2 className="w-4 h-4" />
                <span>{confirmed ? '已确认，跳转中…' : '确认并继续'}</span>
              </button>

              {/* Action result hint */}
              <div className="flex items-start gap-1.5 px-1 py-1">
                <ArrowRight className="w-3 h-3 text-gray-400 flex-shrink-0 mt-0.5" />
                <p className="text-xs text-gray-400 leading-relaxed">
                  确认后，事项状态将从<span className="text-yellow-600 font-medium">待确认</span>变为
                  <span className="text-green-600 font-medium">已确认</span>，可继续发起影响分析或生成输出物
                </p>
              </div>

              {/* SECONDARY */}
              <Link
                to="/impact"
                className="w-full flex items-center gap-2 px-4 py-2.5 bg-blue-50 text-blue-700 border border-blue-200 rounded-lg hover:bg-blue-100 text-sm font-medium transition-colors"
              >
                <GitBranch className="w-4 h-4" />
                <span>发起影响分析</span>
                <span className="ml-auto text-xs bg-blue-200 text-blue-800 px-1.5 py-0.5 rounded">推荐</span>
              </Link>

              {/* More actions */}
              <div className="relative">
                <button
                  onClick={() => setShowMoreActions(!showMoreActions)}
                  className="w-full flex items-center gap-2 px-4 py-2 bg-gray-50 text-gray-500 rounded-lg hover:bg-gray-100 text-sm transition-colors"
                >
                  <MoreHorizontal className="w-4 h-4" />
                  <span>更多操作</span>
                  <ChevronDown
                    className={`w-3.5 h-3.5 ml-auto transition-transform ${showMoreActions ? 'rotate-180' : ''}`}
                  />
                </button>

                {showMoreActions && (
                  <div className="mt-1.5 border border-gray-200 rounded-lg bg-white overflow-hidden shadow-sm">
                    <MoreActionItem icon={FileText} label="生成 PRD 初稿" link="/results" />
                    <MoreActionItem icon={ClipboardList} label="生成测试点" />
                    <MoreActionItem icon={FolderOpen} label="转为项目事项" />
                    <MoreActionItem icon={Save} label="保存草稿" />
                  </div>
                )}
              </div>
            </div>
          </div>

          {/* Status summary card */}
          <div className="bg-gray-50 border border-gray-200 rounded-xl p-4">
            <div className="text-xs font-medium text-gray-500 mb-3">事项快照</div>
            <div className="space-y-2">
              <SnapshotRow label="当前状态">
                <span className="px-2 py-0.5 text-xs bg-yellow-100 text-yellow-700 rounded-full">待确认</span>
              </SnapshotRow>
              <SnapshotRow label="优先级">
                <span className="px-2 py-0.5 text-xs bg-red-50 text-red-700 rounded-full">高</span>
                <span className="ml-1 text-xs text-gray-400">建议复核</span>
              </SnapshotRow>
              <SnapshotRow label="涉及模块">
                <span className="text-xs text-gray-700">2 个模块</span>
              </SnapshotRow>
              <SnapshotRow label="待确认问题">
                <span className="text-xs text-yellow-700">2 条</span>
              </SnapshotRow>
            </div>
          </div>
        </div>
      </div>
    </main>
  );
}

/* ── Sub-components ── */

function StatusStep({
  label,
  sublabel,
  done,
  active,
  upcoming,
  tag,
}: {
  label: string;
  sublabel: string;
  done?: boolean;
  active?: boolean;
  upcoming?: boolean;
  tag?: { text: string; color: 'yellow' | 'green' };
}) {
  const dotClass = done
    ? 'w-2 h-2 rounded-full bg-green-500'
    : active
    ? 'w-2 h-2 rounded-full bg-blue-500 ring-2 ring-blue-200'
    : 'w-2 h-2 rounded-full bg-gray-300';

  const labelClass = active
    ? 'text-sm font-medium text-gray-900'
    : done
    ? 'text-sm text-gray-600'
    : 'text-sm text-gray-400';

  const tagColors = {
    yellow: 'bg-yellow-100 text-yellow-700',
    green: 'bg-green-100 text-green-700',
  };

  return (
    <div className="flex items-center gap-2 flex-shrink-0">
      <span className={dotClass} />
      <div>
        <div className="flex items-center gap-1.5">
          <span className={labelClass}>{label}</span>
          {tag && (
            <span className={`px-1.5 py-0.5 text-xs rounded-full ${tagColors[tag.color]}`}>
              {tag.text}
            </span>
          )}
        </div>
        <div className="text-xs text-gray-400">{sublabel}</div>
      </div>
    </div>
  );
}

function StepArrow() {
  return <ArrowRight className="w-3.5 h-3.5 text-gray-300 flex-shrink-0 mx-3" />;
}

function InfoRow({
  icon: Icon,
  label,
  value,
  badge,
}: {
  icon: any;
  label: string;
  value: string;
  badge?: boolean;
}) {
  return (
    <div className="flex items-center gap-2">
      <Icon className="w-3.5 h-3.5 text-gray-400 flex-shrink-0" />
      <div className="flex-1 min-w-0">
        <div className="text-xs text-gray-400">{label}</div>
        {badge ? (
          <span className="inline-block text-xs px-2 py-0.5 bg-blue-50 text-blue-700 rounded mt-0.5">
            {value}
          </span>
        ) : (
          <div className="text-xs text-gray-800">{value}</div>
        )}
      </div>
    </div>
  );
}

function AiBadge() {
  return (
    <span className="inline-flex items-center gap-0.5 px-1.5 py-0.5 bg-blue-50 text-blue-600 rounded text-[10px]">
      <Sparkles className="w-2.5 h-2.5" />
      AI 建议
    </span>
  );
}

function FieldCard({
  label,
  value,
  badge,
  badgeColor = 'blue',
  status,
  riskTag,
}: {
  label: string;
  value: string;
  badge?: boolean;
  badgeColor?: 'blue' | 'red' | 'yellow' | 'green';
  status?: 'confirmed' | 'pending';
  riskTag?: string;
}) {
  const badgeColors = {
    blue: 'bg-blue-50 text-blue-700',
    red: 'bg-red-50 text-red-700',
    yellow: 'bg-yellow-50 text-yellow-700',
    green: 'bg-green-50 text-green-700',
  };

  return (
    <div className="p-3 bg-gray-50 rounded-lg">
      <div className="flex items-center gap-1.5 mb-2">
        <span className="text-xs text-gray-400">{label}</span>
        <AiBadge />
        {status === 'confirmed' && <CheckCircle2 className="w-3 h-3 text-green-500 ml-auto" />}
        {status === 'pending' && <AlertCircle className="w-3 h-3 text-yellow-500 ml-auto" />}
      </div>
      <div className="flex items-center gap-2">
        {badge ? (
          <span className={`inline-block text-sm px-3 py-1 rounded font-medium ${badgeColors[badgeColor]}`}>
            {value}
          </span>
        ) : (
          <div className="text-sm font-medium text-gray-900">{value}</div>
        )}
        {riskTag && (
          <span className="text-xs text-orange-600 bg-orange-50 px-1.5 py-0.5 rounded">
            {riskTag}
          </span>
        )}
      </div>
    </div>
  );
}

function ModuleBadge({ name }: { name: string }) {
  return (
    <span className="inline-flex items-center px-2 py-1 bg-white border border-gray-200 text-gray-700 rounded text-xs">
      {name}
    </span>
  );
}

function SimilarCase({
  title,
  date,
  status,
}: {
  title: string;
  date: string;
  status: string;
}) {
  return (
    <div className="flex items-center justify-between px-3 py-2 bg-gray-50 rounded-lg hover:bg-gray-100 transition-colors cursor-pointer">
      <div>
        <div className="text-xs text-gray-800">{title}</div>
        <div className="text-xs text-gray-400 mt-0.5">{date}</div>
      </div>
      <span className="text-xs px-2 py-0.5 bg-green-50 text-green-700 rounded-full">{status}</span>
    </div>
  );
}

function MoreActionItem({
  icon: Icon,
  label,
  link,
}: {
  icon: any;
  label: string;
  link?: string;
}) {
  const cls =
    'w-full flex items-center gap-2 px-4 py-2.5 text-sm text-gray-600 hover:bg-gray-50 transition-colors text-left';
  if (link) {
    return (
      <Link to={link} className={cls}>
        <Icon className="w-4 h-4 text-gray-400" />
        {label}
      </Link>
    );
  }
  return (
    <button className={cls}>
      <Icon className="w-4 h-4 text-gray-400" />
      {label}
    </button>
  );
}

function SnapshotRow({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-xs text-gray-400">{label}</span>
      <div className="flex items-center gap-1">{children}</div>
    </div>
  );
}
