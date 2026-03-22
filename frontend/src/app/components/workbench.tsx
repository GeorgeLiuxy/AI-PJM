/**
 * 工作台组件 - Summary Cards
 */

import { CheckCircle2, AlertTriangle, Clock, FileText } from 'lucide-react';

interface SummaryCardProps {
  label: string;
  count: number;
  icon: React.ReactNode;
  color: string;
  bgColor: string;
}

export function SummaryCard({ label, count, icon, color, bgColor }: SummaryCardProps) {
  return (
    <div className={`${bgColor} rounded-xl p-4 border border-gray-100`}>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className={`w-8 h-8 ${color} rounded-lg flex items-center justify-center`}>
            {icon}
          </div>
          <span className="text-sm font-medium text-gray-700">{label}</span>
        </div>
        <span className="text-2xl font-bold text-gray-900">{count}</span>
      </div>
    </div>
  );
}

export function WorkbenchSummary({ summary }: { summary: { pending_item_confirm_count: number; pending_analysis_review_count: number; pending_output_confirm_count: number; done_item_count: number } }) {
  return (
    <div className="grid grid-cols-4 gap-4 mb-6">
      <SummaryCard
        label="待确认事项"
        count={summary.pending_item_confirm_count}
        icon={<Clock className="w-4 h-4 text-yellow-600" />}
        color="bg-yellow-100"
        bgColor="bg-yellow-50"
      />
      <SummaryCard
        label="待复核分析"
        count={summary.pending_analysis_review_count}
        icon={<AlertTriangle className="w-4 h-4 text-purple-600" />}
        color="bg-purple-100"
        bgColor="bg-purple-50"
      />
      <SummaryCard
        label="待确认输出"
        count={summary.pending_output_confirm_count}
        icon={<FileText className="w-4 h-4 text-blue-600" />}
        color="bg-blue-100"
        bgColor="bg-blue-50"
      />
      <SummaryCard
        label="已完成事项"
        count={summary.done_item_count}
        icon={<CheckCircle2 className="w-4 h-4 text-green-600" />}
        color="bg-green-100"
        bgColor="bg-green-50"
      />
    </div>
  );
}
