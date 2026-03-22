import {
  Sparkles,
  ArrowRight,
  FolderOpen,
  Clock,
  FileText,
  GitBranch,
  Package,
} from 'lucide-react';
import { Link } from 'react-router';
import { useWorkbenchHome } from '../hooks';
import { WorkbenchSummary } from '../components/workbench';
import { TodoList } from '../components/todo';
import { RecentItemList, RecentOutputList, RecentItemRow, RecentOutputRow } from '../components/recent';
import { LoadingSpinner, ErrorState } from '../components/loading';

export default function HomePage() {
  const { data, loading, error } = useWorkbenchHome();

  // 首次加载显示骨架屏
  if (loading) {
    return (
      <main className="max-w-[1200px] mx-auto px-8 py-7">
        <div className="bg-gradient-to-br from-blue-50 to-white rounded-2xl border-2 border-blue-200 p-7 mb-6 shadow-lg animate-pulse">
          <div className="h-20 bg-gray-200 rounded-xl"></div>
        </div>
        <LoadingSpinner />
      </main>
    );
  }

  // 错误状态
  if (error) {
    return (
      <main className="max-w-[1200px] mx-auto px-8 py-7">
        <ErrorState message={error} />
      </main>
    );
  }

  // 无数据状态（理论上不会出现）
  if (!data) {
    return (
      <main className="max-w-[1200px] mx-auto px-8 py-7">
        <div className="text-center py-12">
          <p className="text-gray-500">暂无数据</p>
        </div>
      </main>
    );
  }

  const { summary, todo_queue, recent_items, recent_outputs } = data;

  // 定义 renderItem 函数
  const renderRecentItem = (item: typeof recent_items[0]) => <RecentItemRow key={item.id} item={item} />;
  const renderRecentOutput = (output: typeof recent_outputs[0]) => <RecentOutputRow key={output.id} output={output} />;

  return (
    <main className="max-w-[1200px] mx-auto px-8 py-7">

      {/* ── 1. Main AI Input ── */}
      <div className="bg-gradient-to-br from-blue-50 to-white rounded-2xl border-2 border-blue-200 p-7 mb-6 shadow-lg">
        <div className="flex items-start gap-4 mb-5">
          <div className="w-10 h-10 bg-blue-600 rounded-xl flex items-center justify-center flex-shrink-0">
            <Sparkles className="w-5 h-5 text-white" />
          </div>
          <div className="flex-1">
            <h1 className="text-base font-medium text-gray-900 mb-0.5">开始处理今天的工作</h1>
            <p className="text-sm text-gray-500">粘贴客户反馈、需求描述或问题，AI 帮你理解并推荐下一步</p>
          </div>
        </div>

        <Link to="/input">
          <textarea
            placeholder="粘贴客户反馈、会议内容、需求描述或问题，我来帮你整理并推荐下一步"
            className="w-full h-28 px-4 py-3.5 bg-white border-2 border-gray-200 rounded-xl resize-none text-gray-900 placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent cursor-pointer text-sm mb-2"
            readOnly
          />
        </Link>

        {/* Light hint */}
        <p className="text-xs text-gray-400 mb-4 pl-0.5">
          提交后将生成一个「待确认事项」，AI 先判断，你再确认
        </p>

        <div className="flex items-center gap-2.5">
          <Link to="/input">
            <button className="px-5 py-2.5 bg-blue-600 text-white rounded-xl hover:bg-blue-700 font-medium shadow-sm text-sm">
              开始处理
            </button>
          </Link>
          <Link to="/impact">
            <button className="px-4 py-2.5 bg-white border border-gray-200 text-gray-700 rounded-xl hover:border-gray-300 hover:bg-gray-50 text-sm">
              发起影响分析
            </button>
          </Link>
          <Link to="/results">
            <button className="px-4 py-2.5 bg-white border border-gray-200 text-gray-700 rounded-xl hover:border-gray-300 hover:bg-gray-50 text-sm">
              生成会议纪要
            </button>
          </Link>
        </div>
      </div>

      {/* ── 2. Summary Cards ── */}
      <WorkbenchSummary summary={summary} />

      {/* ── 3. 待办列表 ── */}
      <section className="mb-6">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-medium text-gray-900">待办列表</h2>
          <span className="text-xs text-gray-400">
            {todo_queue.length > 0 ? `${todo_queue.length} 项需要处理` : '暂无待办'}
          </span>
        </div>

        <TodoList todos={todo_queue} />
      </section>

      {/* ── 4. 最近事项 ── */}
      <section className="mb-6">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-medium text-gray-900">最近事项</h2>
        </div>

        <RecentItemList
          items={recent_items}
          renderItem={renderRecentItem}
          emptyMessage="暂无最近事项"
        />
      </section>

      {/* ── 5. 最近 AI 生成结果 ── */}
      <section>
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-medium text-gray-900">最近 AI 生成结果</h2>
          <Link to="/results" className="text-xs text-blue-600 hover:text-blue-700">
            查看全部 →
          </Link>
        </div>

        <RecentOutputList
          items={recent_outputs}
          renderItem={renderRecentOutput}
          emptyMessage="暂无生成结果"
        />
      </section>
    </main>
  );
}
