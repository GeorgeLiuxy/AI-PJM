/**
 * 通用加载和状态组件
 */

import { RefreshCw } from 'lucide-react';

export function LoadingSpinner({ size = 'default' }: { size?: 'small' | 'default' | 'large' }) {
  const sizeClasses = {
    small: 'w-4 h-4',
    default: 'w-6 h-6',
    large: 'w-8 h-8',
  };

  return (
    <div className="flex items-center justify-center py-8">
      <RefreshCw className={`${sizeClasses[size]} text-blue-600 animate-spin`} />
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="flex flex-col items-center justify-center py-8 px-4">
      <p className="text-sm text-red-600 mb-2">{message}</p>
      {onRetry && (
        <button
          onClick={onRetry}
          className="px-4 py-2 bg-red-100 text-red-700 rounded-lg hover:bg-red-200 text-sm"
        >
          重试
        </button>
      )}
    </div>
  );
}

export function EmptyState({ message }: { message: string }) {
  return (
    <div className="flex items-center justify-center py-8 px-4">
      <p className="text-sm text-gray-500">{message}</p>
    </div>
  );
}
