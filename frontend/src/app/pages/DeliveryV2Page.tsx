import { useMemo, useState } from 'react';
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  ClipboardList,
  Code2,
  FileCheck2,
  FileText,
  GitBranch,
  Loader2,
  Play,
  RotateCcw,
  Settings2,
  ShieldCheck,
  Terminal,
} from 'lucide-react';
import { deliveryApi } from '../lib/api';
import type {
  DeliveryCodingTask,
  DeliveryDemand,
  DeliveryExecutionRun,
  DeliveryImpactAnalysis,
  DeliveryRepoContext,
  DeliverySpecCard,
} from '../types';

type StepKey = 'demand' | 'spec' | 'repo' | 'impact' | 'task' | 'run';
type StepState = 'idle' | 'running' | 'done' | 'failed';
type TabKey = 'summary' | 'spec' | 'execution' | 'taskPackage';

type DeliveryResult = {
  demand?: DeliveryDemand;
  spec?: DeliverySpecCard;
  repo?: DeliveryRepoContext;
  impact?: DeliveryImpactAnalysis;
  task?: DeliveryCodingTask;
  run?: DeliveryExecutionRun;
};

type CheckEvidence = {
  command: string;
  status: string;
  duration_ms: number;
  exit_code?: number | null;
  stdout_tail?: string;
  stderr_tail?: string;
  error?: string | null;
};

const defaultInput = 'Add a compact execution status badge to the delivery dashboard.';

const stepMeta: Array<{ key: StepKey; title: string; detail: string }> = [
  { key: 'demand', title: 'Demand', detail: 'Input' },
  { key: 'spec', title: 'Spec', detail: 'Story' },
  { key: 'repo', title: 'Context', detail: 'Repo' },
  { key: 'impact', title: 'Impact', detail: 'Risk' },
  { key: 'task', title: 'Task', detail: 'Package' },
  { key: 'run', title: 'Run', detail: 'Evidence' },
];

const tabs: Array<{ key: TabKey; label: string; icon: typeof Activity }> = [
  { key: 'summary', label: 'Summary', icon: Activity },
  { key: 'spec', label: 'Spec', icon: FileText },
  { key: 'execution', label: 'Execution', icon: Terminal },
  { key: 'taskPackage', label: 'Task Package', icon: Code2 },
];

const initialSteps = Object.fromEntries(stepMeta.map((step) => [step.key, 'idle'])) as Record<StepKey, StepState>;

export default function DeliveryV2Page() {
  const [rawInput, setRawInput] = useState(defaultInput);
  const [allowedPaths, setAllowedPaths] = useState('frontend/src/app/components');
  const [requiredChecks, setRequiredChecks] = useState('npm run build');
  const [steps, setSteps] = useState<Record<StepKey, StepState>>(initialSteps);
  const [result, setResult] = useState<DeliveryResult>({});
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [activeTab, setActiveTab] = useState<TabKey>('summary');
  const [settingsOpen, setSettingsOpen] = useState(false);

  const canRun = useMemo(() => rawInput.trim().length > 0 && !running, [rawInput, running]);
  const checks = useMemo(() => extractCheckEvidence(result.run), [result.run]);
  const passedChecks = checks.filter((check) => check.status === 'passed').length;
  const outcome = result.run?.status || result.task?.status || result.spec?.status || 'idle';

  const setStep = (key: StepKey, state: StepState) => {
    setSteps((current) => ({ ...current, [key]: state }));
  };

  const reset = () => {
    setRawInput(defaultInput);
    setAllowedPaths('frontend/src/app/components');
    setRequiredChecks('npm run build');
    setSteps(initialSteps);
    setResult({});
    setError(null);
    setActiveTab('summary');
  };

  const runWorkflow = async () => {
    if (!canRun) {
      return;
    }

    setRunning(true);
    setError(null);
    setResult({});
    setSteps(initialSteps);
    setActiveTab('summary');

    const executeStep = async <T,>(key: StepKey, action: () => Promise<T>): Promise<T> => {
      setStep(key, 'running');
      try {
        const value = await action();
        setStep(key, 'done');
        return value;
      } catch (stepError) {
        setStep(key, 'failed');
        throw stepError;
      }
    };

    try {
      const demand = await executeStep('demand', async () => {
        return (await deliveryApi.createDemand({
          raw_input: rawInput.trim(),
          source_type: 'new_requirement',
        })).data;
      });
      setResult((current) => ({ ...current, demand }));

      const spec = await executeStep('spec', async () => {
        return (await deliveryApi.generateSpec(demand.id, { auto_approve_low_risk: true })).data;
      });
      setResult((current) => ({ ...current, spec }));

      const repo = await executeStep('repo', async () => {
        return (await deliveryApi.collectRepoContext(demand.id)).data;
      });
      setResult((current) => ({ ...current, repo }));

      const impact = await executeStep('impact', async () => {
        return (await deliveryApi.analyzeImpact(demand.id, { repo_context_id: repo.id })).data;
      });
      setResult((current) => ({ ...current, impact }));

      const task = await executeStep('task', async () => {
        return (await deliveryApi.createCodingTask(spec.id, {
          allowed_paths: splitLines(allowedPaths),
          required_checks: splitLines(requiredChecks),
        })).data;
      });
      setResult((current) => ({ ...current, task }));

      const run = await executeStep('run', async () => {
        const queuedRun = (await deliveryApi.createExecutionRun(task.id, {
          executor_type: 'codex',
          trigger_mode: 'manual',
        })).data;
        setResult((current) => ({ ...current, run: queuedRun }));
        const dispatchedRun = (await deliveryApi.dispatchExecutionRun(queuedRun.id)).data;
        const refreshedTask = (await deliveryApi.getCodingTask(task.id)).data;
        setResult((current) => ({ ...current, run: dispatchedRun, task: refreshedTask }));
        return dispatchedRun;
      });
      setResult((current) => ({ ...current, run }));
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Workflow failed';
      setError(message);
      setActiveTab('execution');
    } finally {
      setRunning(false);
    }
  };

  return (
    <main className="mx-auto max-w-[1440px] px-3 py-3 lg:px-6">
      <section className="mb-3 grid gap-3 min-[560px]:grid-cols-[minmax(0,1fr)_220px] xl:grid-cols-[minmax(0,1fr)_360px]">
        <div className="rounded border border-slate-200 bg-white">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 px-3 py-2">
            <div className="min-w-0">
              <div className="flex items-center gap-2 text-sm font-medium text-blue-700">
                <GitBranch className="h-4 w-4" />
                Delivery workflow
              </div>
              <h1 className="mt-0.5 text-base font-semibold text-slate-950">AI delivery orchestration</h1>
            </div>
            <div className="flex shrink-0 items-center gap-2">
              <button
                type="button"
                onClick={() => setSettingsOpen((open) => !open)}
                className="inline-flex h-8 items-center gap-1.5 rounded border border-slate-200 bg-white px-2.5 text-sm text-slate-700 hover:bg-slate-50"
              >
                <Settings2 className="h-4 w-4" />
                Settings
              </button>
              <button
                type="button"
                onClick={reset}
                className="inline-flex h-8 items-center gap-1.5 rounded border border-slate-200 bg-white px-2.5 text-sm text-slate-700 hover:bg-slate-50"
              >
                <RotateCcw className="h-4 w-4" />
                Reset
              </button>
              <button
                type="button"
                onClick={runWorkflow}
                disabled={!canRun}
                className="inline-flex h-8 items-center gap-1.5 rounded bg-blue-600 px-3 text-sm font-medium text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-slate-300"
              >
                {running ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
                Run
              </button>
            </div>
          </div>

          <div className="p-3">
            <label className="block">
              <span className="mb-1.5 block text-sm font-medium text-slate-800">Business input</span>
              <textarea
                value={rawInput}
                onChange={(event) => setRawInput(event.target.value)}
                className="h-20 w-full resize-none rounded border border-slate-200 bg-white px-3 py-2 text-sm leading-6 text-slate-900 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
              />
            </label>

            {settingsOpen && (
              <div className="mt-3 grid gap-3 rounded border border-slate-200 bg-slate-50 p-3 lg:grid-cols-2">
                <label className="block">
                  <span className="mb-1 block text-xs font-medium text-slate-600">Allowed paths</span>
                  <textarea
                    value={allowedPaths}
                    onChange={(event) => setAllowedPaths(event.target.value)}
                    className="h-16 w-full resize-none rounded border border-slate-200 bg-white px-2 py-2 text-xs leading-5 text-slate-900 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
                  />
                </label>
                <label className="block">
                  <span className="mb-1 block text-xs font-medium text-slate-600">Required checks</span>
                  <textarea
                    value={requiredChecks}
                    onChange={(event) => setRequiredChecks(event.target.value)}
                    className="h-16 w-full resize-none rounded border border-slate-200 bg-white px-2 py-2 text-xs leading-5 text-slate-900 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
                  />
                </label>
              </div>
            )}
          </div>

          {error && (
            <div className="mx-3 mb-3 rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
              {error}
            </div>
          )}
        </div>

        <RunSummary
          outcome={outcome}
          result={result}
          checkCount={checks.length}
          passedChecks={passedChecks}
          running={running}
        />
      </section>

      <Pipeline steps={steps} />

      <section className="mt-3 rounded border border-slate-200 bg-white">
        <div className="flex flex-wrap items-center gap-1 border-b border-slate-200 px-3 py-2">
          {tabs.map((tab) => (
            <TabButton
              key={tab.key}
              active={activeTab === tab.key}
              icon={tab.icon}
              label={tab.label}
              onClick={() => setActiveTab(tab.key)}
            />
          ))}
        </div>

        <div className="p-4">
          {activeTab === 'summary' && <SummaryTab result={result} checks={checks} />}
          {activeTab === 'spec' && <SpecTab result={result} />}
          {activeTab === 'execution' && <ExecutionTab result={result} checks={checks} />}
          {activeTab === 'taskPackage' && <TaskPackageTab result={result} />}
        </div>
      </section>
    </main>
  );
}

function Pipeline({ steps }: { steps: Record<StepKey, StepState> }) {
  return (
    <section className="rounded border border-slate-200 bg-white p-2">
      <div className="grid grid-cols-3 gap-2 xl:grid-cols-6">
        {stepMeta.map((step) => (
          <div key={step.key} className="min-h-[58px] rounded bg-slate-50 px-2 py-2">
            <div className="mb-1 flex min-w-0 items-center gap-2">
              <StepIcon state={steps[step.key]} />
              <div className="min-w-0 truncate text-sm font-medium text-slate-950">{step.title}</div>
            </div>
            <div className="flex items-center justify-between gap-2">
              <div className="truncate text-xs text-slate-500">{step.detail}</div>
              <StatusBadge value={steps[step.key]} />
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

function RunSummary({
  outcome,
  result,
  checkCount,
  passedChecks,
  running,
}: {
  outcome: string;
  result: DeliveryResult;
  checkCount: number;
  passedChecks: number;
  running: boolean;
}) {
  return (
    <aside className="rounded border border-slate-200 bg-white">
      <div className="flex items-center gap-2 border-b border-slate-200 px-4 py-3 text-sm font-medium text-slate-900">
        <ShieldCheck className="h-4 w-4 text-emerald-600" />
        Current result
      </div>
      <div className="grid grid-cols-2 gap-px bg-slate-100">
        <SummaryRow label="Outcome" value={running ? 'running' : outcome} />
        <SummaryRow label="Risk" value={result.demand?.risk_level || result.impact?.risk_level || 'empty'} />
        <SummaryRow label="Spec" value={result.spec?.status || 'empty'} />
        <SummaryRow label="Task" value={result.task?.status || 'empty'} />
        <SummaryRow label="Run" value={result.run?.status || 'empty'} />
        <SummaryRow label="Checks" value={checkCount > 0 ? `${passedChecks}/${checkCount} passed` : 'empty'} />
      </div>
    </aside>
  );
}

function SummaryRow({ label, value }: { label: string; value?: string | number | null }) {
  return (
    <div className="flex min-h-[46px] items-center justify-between gap-3 bg-white px-3 py-2">
      <div className="text-sm text-slate-500">{label}</div>
      <StatusBadge value={value} />
    </div>
  );
}

function SummaryTab({ result, checks }: { result: DeliveryResult; checks: CheckEvidence[] }) {
  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        <Metric label="Demand" value={result.demand?.id} />
        <Metric label="Risk" value={result.demand?.risk_level || result.impact?.risk_level} />
        <Metric label="Confidence" value={formatConfidence(result.impact?.confidence_score)} />
        <Metric label="Spec" value={result.spec?.status} />
        <Metric label="Task" value={result.task?.status} />
        <Metric label="Run" value={result.run?.status} />
      </div>
      <div className="rounded border border-slate-200">
        <div className="flex items-center gap-2 border-b border-slate-200 px-3 py-2 text-sm font-medium text-slate-900">
          <FileCheck2 className="h-4 w-4 text-emerald-600" />
          Evidence
        </div>
        <div className="space-y-3 p-3">
          <TextBlock title="Execution result" value={result.run?.result_summary} compact />
          <ListBlock
            title="Checks"
            items={checks.map((check) => {
              const exitCode = check.exit_code === null || check.exit_code === undefined ? 'n/a' : check.exit_code;
              return `${check.status}: ${check.command} (${check.duration_ms}ms, exit ${exitCode})`;
            })}
          />
        </div>
      </div>
    </div>
  );
}

function SpecTab({ result }: { result: DeliveryResult }) {
  return (
    <div className="grid gap-4 xl:grid-cols-2">
      <TextBlock title="User story" value={result.spec?.user_story} />
      <TextBlock title="Repository context" value={result.repo?.summary} />
      <ListBlock title="Acceptance criteria" items={result.spec?.acceptance_criteria_json} />
      <ListBlock title="Open questions" items={result.spec?.open_questions_json} />
    </div>
  );
}

function ExecutionTab({ result, checks }: { result: DeliveryResult; checks: CheckEvidence[] }) {
  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
      <div className="overflow-hidden rounded border border-slate-200">
        <div className="border-b border-slate-200 px-3 py-2 text-sm font-medium text-slate-900">Check evidence</div>
        <div className="max-h-[360px] overflow-auto">
          <table className="w-full table-fixed text-left text-sm">
            <thead className="bg-slate-50 text-xs font-medium uppercase text-slate-500">
              <tr>
                <th className="w-[44%] px-3 py-2">Command</th>
                <th className="w-[20%] px-3 py-2">Status</th>
                <th className="w-[18%] px-3 py-2">Exit</th>
                <th className="w-[18%] px-3 py-2">Time</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {checks.length > 0 ? (
                checks.map((check, index) => (
                  <tr key={`${check.command}-${index}`}>
                    <td className="break-words px-3 py-2 font-mono text-xs text-slate-700">{check.command}</td>
                    <td className="px-3 py-2">
                      <StatusBadge value={check.status} />
                    </td>
                    <td className="px-3 py-2 text-slate-700">{check.exit_code ?? 'n/a'}</td>
                    <td className="px-3 py-2 text-slate-700">{check.duration_ms}ms</td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td className="px-3 py-6 text-sm text-slate-400" colSpan={4}>
                    No checks recorded
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      <div className="space-y-4">
        <TextBlock title="Execution result" value={result.run?.result_summary} compact />
        <ListBlock title="Execution logs" items={result.run?.logs.map((log) => `${log.level}: ${log.message}`)} />
      </div>
    </div>
  );
}

function TaskPackageTab({ result }: { result: DeliveryResult }) {
  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
      <TextBlock title="Codex task prompt" value={result.task?.task_prompt} mono />
      <div className="space-y-4">
        <ListBlock title="Allowed paths" items={result.task?.allowed_paths_json} />
        <ListBlock title="Required checks" items={result.task?.required_checks_json} />
        <ListBlock title="Forbidden actions" items={result.task?.forbidden_actions_json} />
        <ListBlock title="Expected evidence" items={result.task?.expected_evidence_json} />
      </div>
    </div>
  );
}

function TabButton({
  active,
  icon: Icon,
  label,
  onClick,
}: {
  active: boolean;
  icon: typeof Activity;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`inline-flex h-9 items-center gap-2 rounded px-3 text-sm transition-colors ${
        active ? 'bg-blue-50 font-medium text-blue-700' : 'text-slate-600 hover:bg-slate-50 hover:text-slate-950'
      }`}
    >
      <Icon className="h-4 w-4" />
      {label}
    </button>
  );
}

function StatusBadge({ value }: { value?: string | number | null }) {
  const label = value === undefined || value === null || value === '' ? 'empty' : String(value);
  const tone = label.includes('manual') || label.includes('blocked') || label.includes('failed')
    ? 'bg-amber-50 text-amber-700 border-amber-200'
    : label.includes('ready') ||
        label.includes('approved') ||
        label.includes('queued') ||
        label.includes('succeeded') ||
        label.includes('completed') ||
        label.includes('passed')
      ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
      : label.includes('running')
        ? 'bg-blue-50 text-blue-700 border-blue-200'
        : 'bg-slate-50 text-slate-700 border-slate-200';

  return (
    <span className={`inline-flex min-w-0 items-center rounded border px-2 py-0.5 text-xs font-medium ${tone}`}>
      <span className="truncate">{label}</span>
    </span>
  );
}

function StepIcon({ state }: { state: StepState }) {
  if (state === 'running') {
    return <Loader2 className="h-4 w-4 shrink-0 animate-spin text-blue-600" />;
  }
  if (state === 'done') {
    return <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-600" />;
  }
  if (state === 'failed') {
    return <AlertTriangle className="h-4 w-4 shrink-0 text-red-600" />;
  }
  return <ClipboardList className="h-4 w-4 shrink-0 text-slate-400" />;
}

function ListBlock({ title, items }: { title: string; items?: string[] }) {
  return (
    <div>
      <div className="mb-1 text-xs font-medium uppercase tracking-wide text-slate-500">{title}</div>
      {items && items.length > 0 ? (
        <ul className="max-h-[260px] space-y-1 overflow-auto pr-1 text-sm text-slate-700">
          {items.map((item, index) => (
            <li key={`${title}-${index}`} className="break-words leading-6">
              {item}
            </li>
          ))}
        </ul>
      ) : (
        <div className="text-sm text-slate-400">No items</div>
      )}
    </div>
  );
}

function Metric({ label, value }: { label: string; value?: string | number | null }) {
  return (
    <div className="min-h-[68px] rounded border border-slate-200 bg-slate-50 px-3 py-2">
      <div className="text-xs text-slate-500">{label}</div>
      <div className="mt-2">
        <StatusBadge value={value} />
      </div>
    </div>
  );
}

function TextBlock({
  title,
  value,
  mono = false,
  compact = false,
}: {
  title: string;
  value?: string | null;
  mono?: boolean;
  compact?: boolean;
}) {
  return (
    <div>
      <div className="mb-1 text-xs font-medium uppercase tracking-wide text-slate-500">{title}</div>
      <div
        className={`${mono ? 'font-mono text-xs' : 'text-sm'} ${
          compact ? 'max-h-[120px]' : 'max-h-[360px]'
        } overflow-auto whitespace-pre-wrap break-words leading-6 text-slate-700`}
      >
        {value || 'No content yet'}
      </div>
    </div>
  );
}

function splitLines(value: string): string[] {
  return value
    .split(/\r?\n|,/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function extractCheckEvidence(run?: DeliveryExecutionRun): CheckEvidence[] {
  const evidence = run?.evidence_json;
  if (!isRecord(evidence) || !isRecord(evidence.dispatch)) {
    return [];
  }

  const results = evidence.dispatch.check_results;
  if (!Array.isArray(results)) {
    return [];
  }

  return results.filter(isCheckEvidence);
}

function isCheckEvidence(value: unknown): value is CheckEvidence {
  if (!value || typeof value !== 'object') {
    return false;
  }
  const candidate = value as Record<string, unknown>;
  return (
    typeof candidate.command === 'string' &&
    typeof candidate.status === 'string' &&
    typeof candidate.duration_ms === 'number'
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object';
}

function formatConfidence(value?: number | null): string | null {
  if (value === undefined || value === null) {
    return null;
  }
  return `${Math.round(value * 100)}%`;
}
