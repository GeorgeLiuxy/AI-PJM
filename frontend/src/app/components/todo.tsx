/**
 * Todo 组件
 */

import { ArrowRight, Clock } from 'lucide-react';
import { Link } from 'react-router';
import type { WorkbenchTodo } from '../types';
import { TODO_TYPE_LABELS, PRIORITY_LABELS, PRIORITY_COLORS } from '../types';

interface TodoCardProps {
  todo: WorkbenchTodo;
}

export function TodoCard({ todo }: TodoCardProps) {
  const todoLabel = TODO_TYPE_LABELS[todo.todo_type];
  const priorityLabel = PRIORITY_LABELS[todo.priority];
  const priorityColor = PRIORITY_COLORS[todo.priority];

  // 计算相对时间
  const getTimeAgo = (dateString: string) => {
    const date = new Date(dateString);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMs / 3600000);
    const diffDays = Math.floor(diffMs / 86400000);

    if (diffMins < 60) return `${diffMins}分钟前`;
    if (diffHours < 24) return `${diffHours}小时前`;
    return `${diffDays}天前`;
  };

  return (
    <Link to={`/items/${todo.item_id}`} className="block">
      <div className="border border-gray-200 rounded-xl px-4 py-3 bg-white hover:border-blue-200 hover:shadow-sm transition-all cursor-pointer group">
        <div className="flex items-center gap-2 mb-1.5">
          <span className="px-2 py-0.5 rounded-full text-[10px] font-medium bg-blue-50 text-blue-700">
            {todoLabel}
          </span>
          <span className={`px-2 py-0.5 rounded-full text-[10px] font-medium ${priorityColor}`}>
            {priorityLabel}
          </span>
          <span className="ml-auto text-[10px] text-gray-400 flex items-center gap-1 flex-shrink-0">
            <Clock className="w-2.5 h-2.5" />
            {getTimeAgo(todo.updated_at)}
          </span>
        </div>
        <div className="flex items-center justify-between gap-3">
          <div className="flex-1 min-w-0">
            <span className="text-sm font-medium text-gray-900">{todo.title}</span>
          </div>
          <ArrowRight className="w-3.5 h-3.5 text-gray-400 group-hover:text-blue-500 group-hover:translate-x-0.5 transition-all flex-shrink-0" />
        </div>
      </div>
    </Link>
  );
}

interface TodoListProps {
  todos: WorkbenchTodo[];
  loading?: boolean;
  error?: string | null;
}

export function TodoList({ todos, loading, error }: TodoListProps) {
  if (loading) {
    return (
      <div className="space-y-2">
        {[...Array(3)].map((_, i) => (
          <div key={i} className="border border-gray-200 rounded-xl px-4 py-3 bg-gray-50 animate-pulse">
            <div className="h-4 bg-gray-200 rounded w-3/4 mb-2"></div>
            <div className="h-3 bg-gray-200 rounded w-1/2"></div>
          </div>
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <div className="border border-red-200 rounded-xl px-4 py-6 bg-red-50 text-center">
        <p className="text-sm text-red-600">加载失败: {error}</p>
      </div>
    );
  }

  if (todos.length === 0) {
    return (
      <div className="border border-gray-200 rounded-xl px-4 py-8 bg-gray-50 text-center">
        <p className="text-sm text-gray-500">暂无待办事项</p>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {todos.map((todo) => (
        <TodoCard key={`${todo.biz_type}-${todo.biz_id}`} todo={todo} />
      ))}
    </div>
  );
}
