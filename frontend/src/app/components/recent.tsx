/**
 * Recent Items/Outputs 组件
 */

import { Link } from 'react-router';
import { ArrowRight, FileText, Package } from 'lucide-react';
import type { RecentItem, RecentOutput } from '../types';
import { STATUS_LABELS } from '../types';

interface RecentItemRowProps {
  item: RecentItem;
}

export function RecentItemRow({ item }: RecentItemRowProps) {
  const statusLabel = STATUS_LABELS[item.status] || item.status;

  return (
    <Link to={`/items/${item.id}`} className="block">
      <div className="bg-white border border-gray-100 rounded-lg px-4 py-2.5 hover:border-blue-200 hover:shadow-sm transition-all group">
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-2 flex-1 min-w-0">
            <FileText className="w-4 h-4 text-gray-400 flex-shrink-0" />
            <span className="text-xs text-gray-500 truncate">{item.title_final || '未命名事项'}</span>
            <span className="px-2 py-0.5 rounded-full text-[10px] bg-blue-50 text-blue-700 whitespace-nowrap">
              {statusLabel}
            </span>
          </div>
          <ArrowRight className="w-3.5 h-3.5 text-gray-300 group-hover:text-blue-500 flex-shrink-0" />
        </div>
      </div>
    </Link>
  );
}

interface RecentOutputRowProps {
  output: RecentOutput;
}

export function RecentOutputRow({ output }: RecentOutputRowProps) {
  const statusLabel = STATUS_LABELS[output.status] || output.status;
  const typeLabel = {
    prd: 'PRD',
    test_points: '测试点',
    handling_advice: '处理建议',
  }[output.output_type] || output.output_type;

  return (
    <Link to={`/items/${output.item_id}`} className="block">
      <div className="bg-white border border-gray-100 rounded-lg px-4 py-2.5 hover:border-blue-200 hover:shadow-sm transition-all group">
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-2 flex-1 min-w-0">
            <Package className="w-4 h-4 text-gray-400 flex-shrink-0" />
            <span className="text-[10px] text-gray-400">{typeLabel}</span>
            <span className="text-xs text-gray-700 truncate">{output.title}</span>
            <span className="px-2 py-0.5 rounded-full text-[10px] bg-teal-50 text-teal-700 whitespace-nowrap">
              {statusLabel}
            </span>
          </div>
          <ArrowRight className="w-3.5 h-3.5 text-gray-300 group-hover:text-blue-500 flex-shrink-0" />
        </div>
      </div>
    </Link>
  );
}

interface RecentListProps<T> {
  items: T[];
  loading?: boolean;
  error?: string | null;
  renderItem: (item: T) => React.ReactNode;
  emptyMessage?: string;
}

// 不使用泛型的版本，避免 JSX 泛型语法问题
export function RecentItemList({ items, loading, error, renderItem, emptyMessage = '暂无数据' }: {
  items: RecentItem[];
  loading?: boolean;
  error?: string | null;
  renderItem: (item: RecentItem) => React.ReactNode;
  emptyMessage?: string;
}) {
  if (loading) {
    return (
      <div className="space-y-1.5">
        {[...Array(3)].map((_, i) => (
          <div key={i} className="bg-gray-50 rounded-lg px-4 py-2.5 animate-pulse">
            <div className="h-3 bg-gray-200 rounded w-3/4"></div>
          </div>
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <div className="border border-red-200 rounded-lg px-4 py-4 bg-red-50 text-center">
        <p className="text-sm text-red-600">加载失败: {error}</p>
      </div>
    );
  }

  if (items.length === 0) {
    return (
      <div className="border border-gray-200 rounded-lg px-4 py-4 bg-gray-50 text-center">
        <p className="text-sm text-gray-500">{emptyMessage}</p>
      </div>
    );
  }

  return <div className="space-y-1.5">{items.map((item) => renderItem(item))}</div>;
}

export function RecentOutputList({ items, loading, error, renderItem, emptyMessage = '暂无数据' }: {
  items: RecentOutput[];
  loading?: boolean;
  error?: string | null;
  renderItem: (item: RecentOutput) => React.ReactNode;
  emptyMessage?: string;
}) {
  if (loading) {
    return (
      <div className="space-y-1.5">
        {[...Array(3)].map((_, i) => (
          <div key={i} className="bg-gray-50 rounded-lg px-4 py-2.5 animate-pulse">
            <div className="h-3 bg-gray-200 rounded w-3/4"></div>
          </div>
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <div className="border border-red-200 rounded-lg px-4 py-4 bg-red-50 text-center">
        <p className="text-sm text-red-600">加载失败: {error}</p>
      </div>
    );
  }

  if (items.length === 0) {
    return (
      <div className="border border-gray-200 rounded-lg px-4 py-4 bg-gray-50 text-center">
        <p className="text-sm text-gray-500">{emptyMessage}</p>
      </div>
    );
  }

  return <div className="space-y-1.5">{items.map((item) => renderItem(item))}</div>;
}
