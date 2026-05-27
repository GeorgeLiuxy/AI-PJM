import { useEffect, useMemo, useState } from 'react';
import { useOutletContext } from 'react-router';
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  ClipboardList,
  Code2,
  ExternalLink,
  FileCheck2,
  FileText,
  GitBranch,
  GitPullRequest,
  Loader2,
  Play,
  RefreshCw,
  RotateCcw,
  Settings2,
  ShieldCheck,
  Terminal,
  Wrench,
} from 'lucide-react';
import { deliveryApi } from '../lib/api';
import { canOperate, canReview } from '../lib/permissions';
import type {
  DeliveryAuditEvent,
  DeliveryCodingTask,
  DeliveryDemand,
  DeliveryDemandDetail,
  DeliveryDeployRecord,
  DeliveryExecutionQueueItem,
  DeliveryExecutionRun,
  DeliveryImpactAnalysis,
  DeliveryMergeRequestRecord,
  DeliveryRepoContext,
  DeliverySpecCard,
  DeliveryVerificationRecord,
} from '../types';
import type { AppOutletContext } from '../Root';

type StepKey = 'demand' | 'spec' | 'repo' | 'impact' | 'task' | 'run' | 'mr' | 'deploy' | 'verify';
type StepState = 'idle' | 'running' | 'done' | 'failed';
type TabKey = 'summary' | 'spec' | 'execution' | 'taskPackage' | 'evidence' | 'queue' | 'audit';

type DeliveryResult = {
  demand?: DeliveryDemand;
  detail?: DeliveryDemandDetail;
  spec?: DeliverySpecCard;
  repo?: DeliveryRepoContext;
  impact?: DeliveryImpactAnalysis;
  task?: DeliveryCodingTask;
  run?: DeliveryExecutionRun;
  mergeRequest?: DeliveryMergeRequestRecord;
  deployRecord?: DeliveryDeployRecord;
  verificationRecord?: DeliveryVerificationRecord;
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

const defaultInput = '为交付工作台添加紧凑的执行状态标识。';

const stepMeta: Array<{ key: StepKey; title: string; detail: string }> = [
  { key: 'demand', title: '需求', detail: '输入' },
  { key: 'spec', title: '规格', detail: '故事' },
  { key: 'repo', title: '上下文', detail: '仓库' },
  { key: 'impact', title: '影响', detail: '风险' },
  { key: 'task', title: '任务', detail: '执行包' },
  { key: 'run', title: '执行', detail: '证据' },
  { key: 'mr', title: '评审', detail: 'MR' },
  { key: 'deploy', title: '部署', detail: '测试环境' },
  { key: 'verify', title: '验收', detail: '结果' },
];

const tabs: Array<{ key: TabKey; label: string; icon: typeof Activity }> = [
  { key: 'summary', label: '总览', icon: Activity },
  { key: 'spec', label: '规格', icon: FileText },
  { key: 'execution', label: '执行', icon: Terminal },
  { key: 'taskPackage', label: '任务包', icon: Code2 },
  { key: 'evidence', label: '证据', icon: FileCheck2 },
  { key: 'queue', label: '队列', icon: ClipboardList },
  { key: 'audit', label: '审计', icon: ShieldCheck },
];

const initialSteps = Object.fromEntries(stepMeta.map((step) => [step.key, 'idle'])) as Record<StepKey, StepState>;

export default function DeliveryV2Page() {
  const { user } = useOutletContext<AppOutletContext>();
  const [rawInput, setRawInput] = useState(defaultInput);
  const [allowedPaths, setAllowedPaths] = useState('');
  const [requiredChecks, setRequiredChecks] = useState('npm run build');
  const [demands, setDemands] = useState<DeliveryDemand[]>([]);
  const [queueItems, setQueueItems] = useState<DeliveryExecutionQueueItem[]>([]);
  const [auditEvents, setAuditEvents] = useState<DeliveryAuditEvent[]>([]);
  const [selectedDemandId, setSelectedDemandId] = useState<number | null>(null);
  const [listLoading, setListLoading] = useState(false);
  const [queueLoading, setQueueLoading] = useState(false);
  const [auditLoading, setAuditLoading] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [steps, setSteps] = useState<Record<StepKey, StepState>>(initialSteps);
  const [result, setResult] = useState<DeliveryResult>({});
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [recovering, setRecovering] = useState(false);
  const [activeTab, setActiveTab] = useState<TabKey>('summary');
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [approvalNote, setApprovalNote] = useState('');

  const busy = running || recovering || detailLoading;
  const defaultProjectId = user?.projects[0]?.id;
  const activeProjectId = result.demand?.project_id ?? defaultProjectId;
  const canOperateCurrent = canOperate(user, activeProjectId);
  const canReviewCurrent = canReview(user, activeProjectId);
  const canStartDelivery =
    canOperate(user, defaultProjectId) && (!user?.auth_enabled || user.role === 'admin' || defaultProjectId !== undefined);
  const canRun = useMemo(() => rawInput.trim().length > 0 && !busy && canStartDelivery, [rawInput, busy, canStartDelivery]);
  const checks = useMemo(() => extractCheckEvidence(result.run), [result.run]);
  const passedChecks = checks.filter((check) => check.status === 'passed').length;
  const outcome = result.run?.status || result.task?.status || result.spec?.status || result.demand?.status || 'idle';
  const manualApprovalRequired = needsManualApproval(result);
  const canContinue = Boolean(
    result.demand && hasResumableWork(result) && !manualApprovalRequired && !busy && canOperateCurrent,
  );
  const canRetryChecks = Boolean(
    result.task &&
      result.task.status !== 'running' &&
      result.task.status !== 'draft' &&
      !manualApprovalRequired &&
      !busy &&
      canOperateCurrent,
  );
  const canAutoRepairChecks = Boolean(
    canRetryChecks && result.run?.status === 'failed' && hasFailedCheckEvidence(result.run) && !isHighRiskResult(result),
  );
  const canCreateMergeRequest = Boolean(
    result.task &&
      result.run?.status === 'succeeded' &&
      !result.mergeRequest &&
      !manualApprovalRequired &&
      !busy &&
      canOperateCurrent,
  );
  const canMarkReviewPassed = Boolean(
    result.mergeRequest &&
      result.mergeRequest.review_status !== 'passed' &&
      result.mergeRequest.status !== 'closed' &&
      !busy &&
      canReviewCurrent,
  );
  const canCreateDeployment = Boolean(
    result.mergeRequest &&
      result.mergeRequest.review_status === 'passed' &&
      !result.deployRecord &&
      !manualApprovalRequired &&
      !busy &&
      canOperateCurrent,
  );
  const canRecordVerification = Boolean(
    result.deployRecord &&
      result.deployRecord.status === 'deployed' &&
      !result.verificationRecord &&
      !manualApprovalRequired &&
      !busy &&
      canReviewCurrent,
  );
  const canSubmitManualApproval = Boolean(result.demand && !busy && canReviewCurrent);

  const setStep = (key: StepKey, state: StepState) => {
    setSteps((current) => ({ ...current, [key]: state }));
  };

  const loadDemandDetail = async (demandId: number, tab: TabKey = 'summary') => {
    setDetailLoading(true);
    try {
      const detail = (await deliveryApi.getDemand(demandId)).data;
      const hydrated = hydrateDemandDetail(detail);
      setSelectedDemandId(demandId);
      setResult(hydrated);
      setSteps(deriveSteps(hydrated));
      setActiveTab(tab);
      setError(null);
    } catch (err) {
      const message = err instanceof Error ? err.message : '加载需求详情失败';
      setError(message);
    } finally {
      setDetailLoading(false);
    }
  };

  const loadDemandList = async (preferredDemandId?: number, tab: TabKey = 'summary') => {
    setListLoading(true);
    try {
      const list = (await deliveryApi.listDemands({ limit: 30 })).data;
      setDemands(list);
      const targetId = preferredDemandId ?? selectedDemandId ?? list[0]?.id;
      if (targetId) {
        await loadDemandDetail(targetId, tab);
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : '加载需求列表失败';
      setError(message);
    } finally {
      setListLoading(false);
    }
  };

  const loadExecutionQueue = async () => {
    setQueueLoading(true);
    try {
      const queue = (await deliveryApi.listExecutionRuns({ limit: 30 })).data;
      setQueueItems(queue);
    } catch (err) {
      const message = err instanceof Error ? err.message : '加载执行队列失败';
      setError(localizeText(message));
    } finally {
      setQueueLoading(false);
    }
  };

  const loadAuditEvents = async () => {
    setAuditLoading(true);
    try {
      const events = (await deliveryApi.listAuditEvents({ limit: 50 })).data;
      setAuditEvents(events);
    } catch (err) {
      const message = err instanceof Error ? err.message : '加载审计记录失败';
      setError(localizeText(message));
    } finally {
      setAuditLoading(false);
    }
  };

  useEffect(() => {
    void loadDemandList();
    void loadExecutionQueue();
    void loadAuditEvents();
    // The initial load intentionally runs once; user actions refresh the list explicitly.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const reset = () => {
    setRawInput(defaultInput);
    setAllowedPaths('');
    setRequiredChecks('npm run build');
    setSelectedDemandId(null);
    setSteps(initialSteps);
    setResult({});
    setError(null);
    setApprovalNote('');
    setActiveTab('summary');
  };

  const runWorkflow = async () => {
    if (!canRun) {
      return;
    }

    let workflowDemandId: number | undefined;
    setRunning(true);
    setError(null);
    setResult({});
    setSelectedDemandId(null);
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
      workflowDemandId = demand.id;
      setSelectedDemandId(demand.id);
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

      await executeStep('run', async () => {
        const queuedRun = (await deliveryApi.createExecutionRun(task.id, {
          executor_type: 'codex',
          trigger_mode: 'manual',
        })).data;
        setResult((current) => ({ ...current, run: queuedRun }));
        if (queuedRun.status !== 'queued') {
          throw new Error(queuedRun.result_summary || `执行状态：${formatStatusLabel(queuedRun.status)}`);
        }
        const dispatchedRun = (await deliveryApi.dispatchExecutionRun(queuedRun.id)).data;
        const refreshedTask = (await deliveryApi.getCodingTask(task.id)).data;
        setResult((current) => ({ ...current, run: dispatchedRun, task: refreshedTask }));
        if (dispatchedRun.status !== 'succeeded') {
          throw new Error(dispatchedRun.result_summary || `执行状态：${formatStatusLabel(dispatchedRun.status)}`);
        }
        return dispatchedRun;
      });

      await loadDemandList(demand.id);
    } catch (err) {
      const message = err instanceof Error ? err.message : '工作流执行失败';
      if (workflowDemandId) {
        await loadDemandList(workflowDemandId, 'execution');
      }
      setError(message);
      setActiveTab('execution');
    } finally {
      setRunning(false);
    }
  };

  const refreshCurrent = async () => {
    await loadDemandList(selectedDemandId ?? result.demand?.id, activeTab);
    await loadExecutionQueue();
    await loadAuditEvents();
  };

  const continueWorkflow = async () => {
    if (!result.demand || !canContinue) {
      return;
    }

    setRecovering(true);
    setError(null);

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
      let next: DeliveryResult = { ...result };
      const demand = result.demand;

      if (!next.spec) {
        const spec = await executeStep('spec', async () => {
          return (await deliveryApi.generateSpec(demand.id, { auto_approve_low_risk: true })).data;
        });
        next = { ...next, spec };
        setResult(next);
      }

      if (!next.repo) {
        const repo = await executeStep('repo', async () => {
          return (await deliveryApi.collectRepoContext(demand.id)).data;
        });
        next = { ...next, repo };
        setResult(next);
      }

      if (!next.impact) {
        const impact = await executeStep('impact', async () => {
          return (await deliveryApi.analyzeImpact(demand.id, { repo_context_id: next.repo?.id })).data;
        });
        next = { ...next, impact };
        setResult(next);
      }

      if (!next.task && next.spec) {
        const task = await executeStep('task', async () => {
          return (await deliveryApi.createCodingTask(next.spec!.id, {
            allowed_paths: splitLines(allowedPaths),
            required_checks: splitLines(requiredChecks),
          })).data;
        });
        next = { ...next, task };
        setResult(next);
      }

      if (next.task && shouldRunExecution(next)) {
        const run = await executeStep('run', async () => {
          if (next.run?.status === 'queued') {
            return (await deliveryApi.dispatchExecutionRun(next.run.id)).data;
          }
          return (await deliveryApi.retryCodingTaskExecution(next.task!.id)).data;
        });
        const refreshedTask = (await deliveryApi.getCodingTask(next.task.id)).data;
        next = { ...next, run, task: refreshedTask };
        setResult(next);
        if (run.status !== 'succeeded') {
          throw new Error(run.result_summary || `执行状态：${formatStatusLabel(run.status)}`);
        }
      }

      await loadDemandList(demand.id, 'execution');
    } catch (err) {
      const message = err instanceof Error ? err.message : '继续执行失败';
      await loadDemandList(result.demand.id, 'execution');
      setError(message);
      setActiveTab('execution');
    } finally {
      setRecovering(false);
    }
  };

  const retryChecks = async () => {
    if (!result.task || !canRetryChecks) {
      return;
    }

    setRecovering(true);
    setError(null);
    setActiveTab('execution');
    setStep('run', 'running');

    try {
      const run = (await deliveryApi.retryCodingTaskExecution(result.task.id)).data;
      const refreshedTask = (await deliveryApi.getCodingTask(result.task.id)).data;
      setResult((current) => ({ ...current, run, task: refreshedTask }));
      setSteps((current) => ({
        ...current,
        task: stepFromTask(refreshedTask),
        run: stepFromRun(run),
      }));
      await loadDemandList(result.task.demand_id, 'execution');
      if (run.status !== 'succeeded') {
        setError(run.result_summary || `执行状态：${formatStatusLabel(run.status)}`);
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : '重试检查失败';
      setError(message);
      setStep('run', 'failed');
    } finally {
      setRecovering(false);
    }
  };

  const autoRepairChecks = async () => {
    if (!result.task || !canAutoRepairChecks) {
      return;
    }

    setRecovering(true);
    setError(null);
    setActiveTab('execution');
    setStep('run', 'running');

    try {
      const runs = (await deliveryApi.autoRepairCodingTaskExecution(result.task.id, { max_attempts: 1 })).data;
      const latestRun = runs[runs.length - 1];
      const refreshedTask = (await deliveryApi.getCodingTask(result.task.id)).data;
      setResult((current) => ({ ...current, run: latestRun || current.run, task: refreshedTask }));
      setSteps((current) => ({
        ...current,
        task: stepFromTask(refreshedTask),
        run: latestRun ? stepFromRun(latestRun) : 'failed',
      }));
      await loadDemandList(result.task.demand_id, 'execution');
      if (!latestRun) {
        setError('自动修复没有产生新的执行记录。');
      } else if (latestRun.status !== 'succeeded') {
        setError(latestRun.result_summary || `执行状态：${formatStatusLabel(latestRun.status)}`);
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : '自动修复失败';
      setError(localizeText(message));
      setStep('run', 'failed');
    } finally {
      setRecovering(false);
    }
  };

  const createMergeRequest = async () => {
    if (!result.task || !result.run || !canCreateMergeRequest) {
      return;
    }

    setRecovering(true);
    setError(null);
    setActiveTab('evidence');

    try {
      const mergeRequest = (await deliveryApi.createMergeRequestRecord(result.task.id, {
        execution_run_id: result.run.id,
        provider: 'local',
        target_branch: 'main',
      })).data;
      setResult((current) => ({ ...current, mergeRequest }));
      setStep('mr', 'running');
      await loadDemandList(result.task.demand_id, 'evidence');
    } catch (err) {
      const message = err instanceof Error ? err.message : '创建合并请求记录失败';
      setError(localizeText(message));
      setStep('mr', 'failed');
    } finally {
      setRecovering(false);
    }
  };

  const markReviewPassed = async () => {
    if (!result.mergeRequest || !canMarkReviewPassed) {
      return;
    }

    setRecovering(true);
    setError(null);
    setActiveTab('evidence');

    try {
      const mergeRequest = (await deliveryApi.recordMergeRequestReview(result.mergeRequest.id, {
        review_status: 'passed',
        review_summary: '本地评审通过。',
      })).data;
      setResult((current) => ({ ...current, mergeRequest }));
      setStep('mr', 'done');
      await loadDemandList(result.task?.demand_id || result.demand?.id, 'evidence');
    } catch (err) {
      const message = err instanceof Error ? err.message : '记录评审结果失败';
      setError(localizeText(message));
      setStep('mr', 'failed');
    } finally {
      setRecovering(false);
    }
  };

  const createDeployment = async () => {
    if (!result.mergeRequest || !canCreateDeployment) {
      return;
    }

    setRecovering(true);
    setError(null);
    setActiveTab('evidence');

    try {
      const deployRecord = (await deliveryApi.createDeployRecord(result.mergeRequest.id, {
        provider: 'local',
        environment: 'test',
      })).data;
      setResult((current) => ({ ...current, deployRecord }));
      setStep('deploy', 'done');
      await loadDemandList(result.task?.demand_id || result.demand?.id, 'evidence');
    } catch (err) {
      const message = err instanceof Error ? err.message : '创建测试环境记录失败';
      setError(localizeText(message));
      setStep('deploy', 'failed');
    } finally {
      setRecovering(false);
    }
  };

  const recordVerification = async (status: 'passed' | 'failed') => {
    if (!result.deployRecord || !canRecordVerification) {
      return;
    }

    setRecovering(true);
    setError(null);
    setActiveTab('evidence');

    try {
      const verificationRecord = (await deliveryApi.recordVerification(result.deployRecord.id, {
        status,
        verifier_ref: 'local_operator',
        summary: status === 'passed' ? '本地验收通过。' : '本地验收未通过。',
        evidence_links: result.deployRecord.url ? [result.deployRecord.url] : [],
      })).data;
      setResult((current) => ({ ...current, verificationRecord }));
      setStep('verify', status === 'passed' ? 'done' : 'failed');
      await loadDemandList(result.task?.demand_id || result.demand?.id, 'evidence');
      if (status === 'failed') {
        setError('本地验收未通过，后续需要回到修复流程或人工处理。');
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : '记录验收结果失败';
      setError(localizeText(message));
      setStep('verify', 'failed');
    } finally {
      setRecovering(false);
    }
  };

  const submitManualApproval = async (approved: boolean) => {
    if (!result.demand || !canSubmitManualApproval) {
      return;
    }

    setRecovering(true);
    setError(null);
    try {
      const detail = (await deliveryApi.recordManualApproval(result.demand.id, {
        approved,
        approver_ref: 'local_operator',
        note: approvalNote.trim() || null,
      })).data;
      const hydrated = hydrateDemandDetail(detail);
      setResult(hydrated);
      setSteps(deriveSteps(hydrated));
      setSelectedDemandId(detail.id);
      setApprovalNote('');
      setActiveTab('evidence');
      await loadDemandList(detail.id, 'evidence');
      if (!approved) {
        setError('人工审批已拒绝该需求继续执行。');
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : '人工审批提交失败';
      setError(message);
    } finally {
      setRecovering(false);
    }
  };

  return (
    <main className="mx-auto max-w-[1500px] px-3 py-2 lg:px-4">
      <div className="grid gap-2 xl:grid-cols-[minmax(0,1fr)_300px]">
        <HistoryPanel
          demands={demands}
          selectedDemandId={selectedDemandId}
          loading={listLoading}
          disabled={busy}
          onRefresh={() => void refreshCurrent()}
          onSelect={(demandId) => void loadDemandDetail(demandId)}
        />

        <div className="order-1 min-w-0 xl:order-1">
          <section className="mb-2 grid gap-2 lg:grid-cols-[minmax(0,1fr)_300px]">
            <div className="rounded border border-slate-200 bg-white">
              <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 px-3 py-2">
                <div className="min-w-0">
                  <div className="flex items-center gap-2 text-sm font-medium text-blue-700">
                    <GitBranch className="h-4 w-4" />
                    交付流程
                  </div>
                  <h1 className="mt-0.5 text-base font-semibold text-slate-950">AI 交付编排工作台</h1>
                </div>
                <div className="flex min-w-0 flex-wrap items-center justify-end gap-2">
                  <button
                    type="button"
                    onClick={() => void refreshCurrent()}
                    disabled={busy || listLoading}
                    className="inline-flex h-8 items-center gap-1.5 rounded border border-slate-200 bg-white px-2.5 text-sm text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    <RefreshCw className={`h-4 w-4 ${listLoading || detailLoading ? 'animate-spin' : ''}`} />
                    刷新
                  </button>
                  <button
                    type="button"
                    onClick={() => void continueWorkflow()}
                    disabled={!canContinue}
                    className={`h-8 items-center gap-1.5 rounded border border-slate-200 bg-white px-2.5 text-sm text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50 ${canContinue ? 'inline-flex' : 'hidden'}`}
                  >
                    {recovering ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
                    继续
                  </button>
                  <button
                    type="button"
                    onClick={() => void retryChecks()}
                    disabled={!canRetryChecks}
                    className={`h-8 items-center gap-1.5 rounded border border-slate-200 bg-white px-2.5 text-sm text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50 ${canRetryChecks ? 'inline-flex' : 'hidden'}`}
                  >
                    <RefreshCw className={`h-4 w-4 ${recovering ? 'animate-spin' : ''}`} />
                    重试检查
                  </button>
                  <button
                    type="button"
                    onClick={() => void autoRepairChecks()}
                    disabled={!canAutoRepairChecks}
                    className={`h-8 items-center gap-1.5 rounded border border-slate-200 bg-white px-2.5 text-sm text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50 ${canAutoRepairChecks ? 'inline-flex' : 'hidden'}`}
                  >
                    {recovering ? <Loader2 className="h-4 w-4 animate-spin" /> : <Wrench className="h-4 w-4" />}
                    自动修复
                  </button>
                  <button
                    type="button"
                    onClick={() => void createMergeRequest()}
                    disabled={!canCreateMergeRequest}
                    className={`h-8 items-center gap-1.5 rounded border border-slate-200 bg-white px-2.5 text-sm text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50 ${canCreateMergeRequest ? 'inline-flex' : 'hidden'}`}
                  >
                    {recovering ? <Loader2 className="h-4 w-4 animate-spin" /> : <GitPullRequest className="h-4 w-4" />}
                    创建 MR
                  </button>
                  <button
                    type="button"
                    onClick={() => void markReviewPassed()}
                    disabled={!canMarkReviewPassed}
                    className={`h-8 items-center gap-1.5 rounded border border-slate-200 bg-white px-2.5 text-sm text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50 ${canMarkReviewPassed ? 'inline-flex' : 'hidden'}`}
                  >
                    {recovering ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />}
                    评审通过
                  </button>
                  <button
                    type="button"
                    onClick={() => void createDeployment()}
                    disabled={!canCreateDeployment}
                    className={`h-8 items-center gap-1.5 rounded border border-slate-200 bg-white px-2.5 text-sm text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50 ${canCreateDeployment ? 'inline-flex' : 'hidden'}`}
                  >
                    {recovering ? <Loader2 className="h-4 w-4 animate-spin" /> : <ExternalLink className="h-4 w-4" />}
                    部署测试
                  </button>
                  <button
                    type="button"
                    onClick={() => void recordVerification('passed')}
                    disabled={!canRecordVerification}
                    className={`h-8 items-center gap-1.5 rounded border border-slate-200 bg-white px-2.5 text-sm text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50 ${canRecordVerification ? 'inline-flex' : 'hidden'}`}
                  >
                    {recovering ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileCheck2 className="h-4 w-4" />}
                    验收通过
                  </button>
                  <button
                    type="button"
                    onClick={() => void recordVerification('failed')}
                    disabled={!canRecordVerification}
                    className={`h-8 items-center gap-1.5 rounded border border-slate-200 bg-white px-2.5 text-sm text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50 ${canRecordVerification ? 'inline-flex' : 'hidden'}`}
                  >
                    <AlertTriangle className="h-4 w-4" />
                    验收失败
                  </button>
                  <button
                    type="button"
                    onClick={() => setSettingsOpen((open) => !open)}
                    className="inline-flex h-8 items-center gap-1.5 rounded border border-slate-200 bg-white px-2.5 text-sm text-slate-700 hover:bg-slate-50"
                  >
                    <Settings2 className="h-4 w-4" />
                    设置
                  </button>
                  <button
                    type="button"
                    onClick={reset}
                    className="inline-flex h-8 items-center gap-1.5 rounded border border-slate-200 bg-white px-2.5 text-sm text-slate-700 hover:bg-slate-50"
                  >
                    <RotateCcw className="h-4 w-4" />
                    新建
                  </button>
                  <button
                    type="button"
                    onClick={runWorkflow}
                    disabled={!canRun}
                    className="inline-flex h-8 items-center gap-1.5 rounded bg-blue-600 px-3 text-sm font-medium text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-slate-300"
                  >
                    {running ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
                    执行
                  </button>
                </div>
              </div>

              <div className="p-2.5">
                <label className="block">
                  <span className="mb-1.5 block text-sm font-medium text-slate-800">业务需求输入</span>
                  <textarea
                    value={rawInput}
                    onChange={(event) => setRawInput(event.target.value)}
                    className="h-16 w-full resize-none rounded border border-slate-200 bg-white px-3 py-2 text-sm leading-6 text-slate-900 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
                  />
                </label>

                {settingsOpen && (
                  <div className="mt-3 grid gap-3 rounded border border-slate-200 bg-slate-50 p-3 lg:grid-cols-2">
                    <label className="block">
                      <span className="mb-1 block text-xs font-medium text-slate-600">允许修改路径</span>
                      <textarea
                        value={allowedPaths}
                        onChange={(event) => setAllowedPaths(event.target.value)}
                        placeholder="留空则根据本地上下文自动推断"
                        className="h-16 w-full resize-none rounded border border-slate-200 bg-white px-2 py-2 text-xs leading-5 text-slate-900 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
                      />
                    </label>
                    <label className="block">
                      <span className="mb-1 block text-xs font-medium text-slate-600">必要检查命令</span>
                      <textarea
                        value={requiredChecks}
                        onChange={(event) => setRequiredChecks(event.target.value)}
                        className="h-16 w-full resize-none rounded border border-slate-200 bg-white px-2 py-2 text-xs leading-5 text-slate-900 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
                      />
                    </label>
                  </div>
                )}
              </div>

              {error && <ErrorPanel message={error} result={result} checks={checks} />}
              {manualApprovalRequired && (
                <ManualApprovalPanel
                  result={result}
                  note={approvalNote}
                  busy={busy}
                  canApprove={canSubmitManualApproval}
                  onNoteChange={setApprovalNote}
                  onApprove={() => void submitManualApproval(true)}
                  onReject={() => void submitManualApproval(false)}
                />
              )}
            </div>

            <RunSummary
              outcome={detailLoading ? 'loading' : outcome}
              result={result}
              checkCount={checks.length}
              passedChecks={passedChecks}
              running={running || recovering}
            />
          </section>

          <Pipeline steps={steps} />

          <section className="mt-2 rounded border border-slate-200 bg-white">
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

            <div className="p-3">
              {activeTab === 'summary' && <SummaryTab result={result} />}
              {activeTab === 'spec' && <SpecTab result={result} />}
              {activeTab === 'execution' && <ExecutionTab result={result} checks={checks} />}
              {activeTab === 'taskPackage' && <TaskPackageTab result={result} />}
              {activeTab === 'evidence' && <EvidenceTab result={result} />}
              {activeTab === 'queue' && <QueueTab items={queueItems} loading={queueLoading} />}
              {activeTab === 'audit' && <AuditTab events={auditEvents} loading={auditLoading} />}
            </div>
          </section>
        </div>
      </div>
    </main>
  );
}

function HistoryPanel({
  demands,
  selectedDemandId,
  loading,
  disabled,
  onRefresh,
  onSelect,
}: {
  demands: DeliveryDemand[];
  selectedDemandId: number | null;
  loading: boolean;
  disabled: boolean;
  onRefresh: () => void;
  onSelect: (demandId: number) => void;
}) {
  return (
    <aside className="order-2 rounded border border-slate-200 bg-white xl:order-2">
      <div className="flex items-center justify-between gap-2 border-b border-slate-200 px-3 py-2">
        <div className="min-w-0">
          <div className="text-sm font-medium text-slate-950">最近任务</div>
          <div className="text-xs text-slate-500">显示 {Math.min(demands.length, 5)} / {demands.length} 条</div>
        </div>
        <button
          type="button"
          onClick={onRefresh}
          disabled={loading}
          className="inline-flex h-8 w-8 items-center justify-center rounded border border-slate-200 text-slate-600 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
          title="刷新历史"
        >
          <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
        </button>
      </div>

      <div className="p-2">
        {demands.length > 0 ? (
          <div className="space-y-1">
            {demands.slice(0, 5).map((demand) => (
              <button
                key={demand.id}
                type="button"
                onClick={() => onSelect(demand.id)}
                disabled={disabled}
                className={`block w-full rounded border px-2.5 py-1.5 text-left transition-colors ${
                  selectedDemandId === demand.id
                    ? 'border-blue-200 bg-blue-50'
                    : 'border-transparent hover:border-slate-200 hover:bg-slate-50'
                } disabled:cursor-not-allowed disabled:opacity-60`}
              >
                <div className="mb-1 flex items-center justify-between gap-2">
                  <span className="truncate text-sm font-medium text-slate-900">#{demand.id} {localizeText(demand.title)}</span>
                  <StatusBadge value={demand.risk_level || 'risk'} />
                </div>
                <div className="flex items-center justify-between gap-2">
                  <StatusBadge value={demand.status} />
                  <span className="text-xs text-slate-400">{formatDateTime(demand.updated_at)}</span>
                </div>
              </button>
            ))}
          </div>
        ) : (
          <div className="rounded border border-dashed border-slate-200 px-3 py-8 text-center text-sm text-slate-400">
            暂无交付记录
          </div>
        )}
      </div>
    </aside>
  );
}

function Pipeline({ steps }: { steps: Record<StepKey, StepState> }) {
  return (
    <section className="rounded border border-slate-200 bg-white p-2">
      <div className="grid grid-cols-3 gap-1.5 md:grid-cols-5 xl:grid-cols-9">
        {stepMeta.map((step) => (
          <div key={step.key} className="min-h-[50px] rounded bg-slate-50 px-2 py-1.5">
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
      <div className="flex items-center gap-2 border-b border-slate-200 px-3 py-2 text-sm font-medium text-slate-900">
        <ShieldCheck className="h-4 w-4 text-emerald-600" />
        当前结果
      </div>
      <div className="grid grid-cols-2 gap-px bg-slate-100">
        <SummaryRow label="结果" value={running ? 'running' : outcome} />
        <SummaryRow label="风险" value={result.demand?.risk_level || result.impact?.risk_level || 'empty'} />
        <SummaryRow label="执行" value={result.run?.status || 'empty'} />
        <SummaryRow label="检查" value={checkCount > 0 ? `${passedChecks}/${checkCount} 通过` : 'empty'} />
        <SummaryRow label="评审" value={result.mergeRequest?.review_status || result.mergeRequest?.status || 'empty'} />
        <SummaryRow label="验收" value={result.verificationRecord?.status || 'empty'} />
      </div>
    </aside>
  );
}

function ErrorPanel({
  message,
  result,
  checks,
}: {
  message: string;
  result: DeliveryResult;
  checks: CheckEvidence[];
}) {
  const details = collectFailureDetails(result, checks);

  return (
    <div className="mx-3 mb-3 rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
      <div className="flex items-start gap-2">
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
        <div className="min-w-0">
          <div className="break-words font-medium">{localizeText(message)}</div>
          {details.length > 0 && (
            <details className="mt-2">
              <summary className="cursor-pointer text-xs font-medium uppercase tracking-wide text-red-700">
                失败详情
              </summary>
              <div className="mt-2 space-y-2">
                {details.map((detail, index) => (
                  <div key={`${detail.title}-${index}`} className="rounded border border-red-100 bg-white/70 p-2">
                    <div className="mb-1 text-xs font-medium text-red-700">{localizeText(detail.title)}</div>
                    <pre className="max-h-[180px] overflow-auto whitespace-pre-wrap break-words font-mono text-xs leading-5 text-slate-800">
                      {localizeText(detail.content)}
                    </pre>
                  </div>
                ))}
              </div>
            </details>
          )}
        </div>
      </div>
    </div>
  );
}

function ManualApprovalPanel({
  result,
  note,
  busy,
  canApprove,
  onNoteChange,
  onApprove,
  onReject,
}: {
  result: DeliveryResult;
  note: string;
  busy: boolean;
  canApprove: boolean;
  onNoteChange: (value: string) => void;
  onApprove: () => void;
  onReject: () => void;
}) {
  return (
    <div className="mx-3 mb-3 rounded border border-amber-200 bg-amber-50 px-3 py-3 text-sm text-amber-900">
      <div className="mb-2 flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="font-medium">需要人工审批</div>
          <div className="mt-1 text-xs leading-5 text-amber-800">
            风险等级 {result.demand?.risk_level || result.impact?.risk_level || '未知'} 需要人工确认后才能继续执行。
          </div>
        </div>
        <StatusBadge value={result.spec?.status || result.task?.status || 'manual_required'} />
      </div>

      <textarea
        value={note}
        onChange={(event) => onNoteChange(event.target.value)}
        placeholder="审批说明、范围判断或拒绝原因"
        disabled={!canApprove || busy}
        className="h-16 w-full resize-none rounded border border-amber-200 bg-white px-2 py-2 text-xs leading-5 text-slate-900 outline-none focus:border-amber-500 focus:ring-2 focus:ring-amber-100"
      />
      {!canApprove ? <div className="mt-2 text-xs text-amber-800">当前账号没有审批权限。</div> : null}

      <div className="mt-2 flex flex-wrap items-center justify-end gap-2">
        <button
          type="button"
          onClick={onReject}
          disabled={busy || !canApprove}
          className="inline-flex h-8 items-center rounded border border-amber-300 bg-white px-3 text-sm text-amber-800 hover:bg-amber-100 disabled:cursor-not-allowed disabled:opacity-50"
        >
          拒绝
        </button>
        <button
          type="button"
          onClick={onApprove}
          disabled={busy || !canApprove}
          className="inline-flex h-8 items-center rounded bg-amber-600 px-3 text-sm font-medium text-white hover:bg-amber-700 disabled:cursor-not-allowed disabled:bg-slate-300"
        >
          批准
        </button>
      </div>
    </div>
  );
}

function SummaryRow({ label, value }: { label: string; value?: string | number | null }) {
  return (
    <div className="flex min-h-[36px] items-center justify-between gap-2 bg-white px-2.5 py-1.5">
      <div className="text-sm text-slate-500">{label}</div>
      <StatusBadge value={value} />
    </div>
  );
}

function SummaryTab({ result }: { result: DeliveryResult }) {
  return (
    <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
        <Metric label="需求" value={result.demand?.id} />
        <Metric label="风险" value={result.demand?.risk_level || result.impact?.risk_level} />
        <Metric label="置信度" value={formatConfidence(result.impact?.confidence_score || result.demand?.confidence_score)} />
        <Metric label="规格" value={result.spec?.status} />
        <Metric label="任务" value={result.task?.status} />
        <Metric label="执行" value={result.run?.status} />
        <Metric label="MR" value={result.mergeRequest?.status} />
        <Metric label="评审" value={result.mergeRequest?.review_status} />
        <Metric label="测试环境" value={result.deployRecord?.status} />
        <Metric label="验收" value={result.verificationRecord?.status} />
    </div>
  );
}

function MergeRequestSummary({ mergeRequest }: { mergeRequest?: DeliveryMergeRequestRecord }) {
  if (!mergeRequest) {
    return <TextBlock title="合并请求" value="暂无合并请求记录" compact />;
  }

  return (
    <div>
      <div className="mb-1 text-xs font-medium uppercase tracking-wide text-slate-500">合并请求</div>
      <div className="space-y-2 rounded border border-slate-200 bg-slate-50 p-2">
        <div className="flex flex-wrap items-center gap-2">
          <StatusBadge value={mergeRequest.status} />
          <StatusBadge value={mergeRequest.review_status} />
        </div>
        <div className="break-words text-sm text-slate-700">{localizeText(mergeRequest.title)}</div>
        <div className="break-words font-mono text-xs text-slate-500">
          {mergeRequest.source_branch}
          {' -> '}
          {mergeRequest.target_branch}
        </div>
        {mergeRequest.url ? (
          <a className="break-words text-sm text-blue-700 hover:underline" href={mergeRequest.url}>
            {mergeRequest.url}
          </a>
        ) : (
          <div className="text-sm text-slate-400">暂无链接</div>
        )}
      </div>
    </div>
  );
}

function DeploymentSummary({
  deployRecord,
  verificationRecord,
}: {
  deployRecord?: DeliveryDeployRecord;
  verificationRecord?: DeliveryVerificationRecord;
}) {
  if (!deployRecord) {
    return <TextBlock title="测试环境" value="暂无测试环境记录" compact />;
  }

  return (
    <div>
      <div className="mb-1 text-xs font-medium uppercase tracking-wide text-slate-500">测试环境</div>
      <div className="space-y-2 rounded border border-slate-200 bg-slate-50 p-2">
        <div className="flex flex-wrap items-center gap-2">
          <StatusBadge value={deployRecord.status} />
          <StatusBadge value={verificationRecord?.status || 'empty'} />
        </div>
        <div className="break-words text-sm text-slate-700">{deployRecord.environment}</div>
        {deployRecord.url ? (
          <a className="break-words text-sm text-blue-700 hover:underline" href={deployRecord.url}>
            {deployRecord.url}
          </a>
        ) : (
          <div className="text-sm text-slate-400">暂无地址</div>
        )}
        {verificationRecord?.summary && (
          <div className="break-words text-sm text-slate-700">{localizeText(verificationRecord.summary)}</div>
        )}
      </div>
    </div>
  );
}

function SpecTab({ result }: { result: DeliveryResult }) {
  return (
    <div className="grid gap-4 xl:grid-cols-2">
      <TextBlock title="用户故事" value={result.spec?.user_story} />
      <TextBlock title="仓库上下文" value={result.repo?.summary} />
      <ListBlock title="验收标准" items={result.spec?.acceptance_criteria_json} />
      <ListBlock title="待确认问题" items={result.spec?.open_questions_json} />
      <ListBlock title="发现文件" items={result.repo?.discovered_files_json} />
      <ListBlock title="受影响文件" items={result.impact?.affected_files_json} />
    </div>
  );
}

function ExecutionTab({ result, checks }: { result: DeliveryResult; checks: CheckEvidence[] }) {
  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
      <div className="overflow-hidden rounded border border-slate-200">
        <div className="border-b border-slate-200 px-3 py-2 text-sm font-medium text-slate-900">检查证据</div>
        <div className="max-h-[360px] overflow-auto">
          <table className="w-full table-fixed text-left text-sm">
            <thead className="bg-slate-50 text-xs font-medium uppercase text-slate-500">
              <tr>
                <th className="w-[44%] px-3 py-2">命令</th>
                <th className="w-[20%] px-3 py-2">状态</th>
                <th className="w-[18%] px-3 py-2">退出码</th>
                <th className="w-[18%] px-3 py-2">耗时</th>
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
                    <td className="px-3 py-2 text-slate-700">{check.exit_code ?? '无'}</td>
                    <td className="px-3 py-2 text-slate-700">{check.duration_ms}ms</td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td className="px-3 py-6 text-sm text-slate-400" colSpan={4}>
                    暂无检查记录
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      <div className="space-y-4">
        <TextBlock title="执行结果" value={result.run?.result_summary} compact />
        <TextBlock title="隔离工作区" value={result.run?.worktree_path} compact mono />
        <TextBlock title="分支" value={result.run?.branch_name} compact mono />
        <TextBlock title="提交" value={result.run?.commit_sha} compact mono />
        <TextBlock title="Codex 调用" value={formatCodexInvocation(result.run)} compact mono />
        <CheckFailureOutput checks={checks} />
        <ListBlock title="执行日志" items={result.run?.logs.map((log) => `${formatLogLevel(log.level)}：${log.message}`)} />
      </div>
    </div>
  );
}

function CheckFailureOutput({ checks }: { checks: CheckEvidence[] }) {
  const failedChecks = checks.filter((check) => check.status !== 'passed');

  if (failedChecks.length === 0) {
    return null;
  }

  return (
    <div>
      <div className="mb-1 text-xs font-medium uppercase tracking-wide text-slate-500">失败输出</div>
      <div className="space-y-2">
        {failedChecks.map((check, index) => {
          const output = [
            check.error ? `错误：${check.error}` : '',
            check.stdout_tail ? `标准输出：\n${check.stdout_tail}` : '',
            check.stderr_tail ? `错误输出：\n${check.stderr_tail}` : '',
          ].filter(Boolean).join('\n\n');

          return (
            <div key={`${check.command}-${index}`} className="rounded border border-red-100 bg-red-50 p-2">
              <div className="mb-1 break-words font-mono text-xs text-red-800">{check.command}</div>
              <pre className="max-h-[220px] overflow-auto whitespace-pre-wrap break-words font-mono text-xs leading-5 text-slate-800">
                {localizeText(output || '未捕获命令输出')}
              </pre>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function TaskPackageTab({ result }: { result: DeliveryResult }) {
  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
      <TextBlock title="Codex 任务提示" value={result.task?.task_prompt} mono />
      <div className="space-y-4">
        <ListBlock title="允许修改路径" items={result.task?.allowed_paths_json} />
        <ListBlock title="必要检查命令" items={result.task?.required_checks_json} />
        <ListBlock title="禁止动作" items={result.task?.forbidden_actions_json} />
        <ListBlock title="期望证据" items={result.task?.expected_evidence_json} />
      </div>
    </div>
  );
}

function EvidenceTab({ result }: { result: DeliveryResult }) {
  const gates = result.detail?.gate_checks || [];

  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
      <div className="overflow-hidden rounded border border-slate-200">
        <div className="border-b border-slate-200 px-3 py-2 text-sm font-medium text-slate-900">门禁检查</div>
        <div className="max-h-[420px] overflow-auto">
          <table className="w-full table-fixed text-left text-sm">
            <thead className="bg-slate-50 text-xs font-medium uppercase text-slate-500">
              <tr>
                <th className="w-[32%] px-3 py-2">门禁</th>
                <th className="w-[20%] px-3 py-2">状态</th>
                <th className="w-[48%] px-3 py-2">原因</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {gates.length > 0 ? (
                gates.map((gate) => (
                  <tr key={gate.id}>
                    <td className="break-words px-3 py-2 font-mono text-xs text-slate-700">{formatGateType(gate.gate_type)}</td>
                    <td className="px-3 py-2">
                      <StatusBadge value={gate.status} />
                    </td>
                    <td className="break-words px-3 py-2 text-slate-700">{localizeText(gate.reason || '暂无原因')}</td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td className="px-3 py-6 text-sm text-slate-400" colSpan={3}>
                    暂无门禁证据
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      <div className="space-y-4">
        <MergeRequestSummary mergeRequest={result.mergeRequest} />
        <DeploymentSummary deployRecord={result.deployRecord} verificationRecord={result.verificationRecord} />
        <StageBlock label="需求接收" status={result.demand?.status} time={result.demand?.created_at} />
        <StageBlock label="规格卡片" status={result.spec?.status} time={result.spec?.created_at} />
        <StageBlock label="仓库上下文" status={result.repo?.status} time={result.repo?.created_at} />
        <StageBlock label="影响分析" status={result.impact?.status} time={result.impact?.created_at} />
        <StageBlock label="编码任务" status={result.task?.status} time={result.task?.created_at} />
        <StageBlock label="执行记录" status={result.run?.status} time={result.run?.finished_at || result.run?.created_at} />
        <StageBlock
          label="合并评审"
          status={result.mergeRequest?.review_status || result.mergeRequest?.status}
          time={result.mergeRequest?.updated_at || result.mergeRequest?.created_at}
        />
        <StageBlock
          label="测试环境"
          status={result.deployRecord?.status}
          time={result.deployRecord?.updated_at || result.deployRecord?.created_at}
        />
        <StageBlock
          label="验收结果"
          status={result.verificationRecord?.status}
          time={result.verificationRecord?.updated_at || result.verificationRecord?.created_at}
        />
      </div>
    </div>
  );
}

function QueueTab({ items, loading }: { items: DeliveryExecutionQueueItem[]; loading: boolean }) {
  return (
    <div className="overflow-hidden rounded border border-slate-200">
      <div className="flex items-center justify-between gap-2 border-b border-slate-200 px-3 py-2">
        <div className="text-sm font-medium text-slate-900">执行队列</div>
        <StatusBadge value={loading ? 'loading' : `${items.length} 条`} />
      </div>
      <div className="max-h-[520px] overflow-auto">
        <table className="w-full table-fixed text-left text-sm">
          <thead className="bg-slate-50 text-xs font-medium uppercase text-slate-500">
            <tr>
              <th className="w-[12%] px-3 py-2">执行</th>
              <th className="w-[18%] px-3 py-2">状态</th>
              <th className="w-[34%] px-3 py-2">任务</th>
              <th className="w-[18%] px-3 py-2">触发</th>
              <th className="w-[18%] px-3 py-2">更新时间</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {items.length > 0 ? (
              items.map((item) => (
                <tr key={item.id}>
                  <td className="px-3 py-2 font-mono text-xs text-slate-700">#{item.id}</td>
                  <td className="px-3 py-2">
                    <StatusBadge value={item.status} />
                  </td>
                  <td className="break-words px-3 py-2 text-slate-700">
                    <div className="line-clamp-2">{localizeText(item.coding_task_title || item.demand_title || '未命名任务')}</div>
                    <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-slate-500">
                      <span>需求 #{item.demand_id}</span>
                      <StatusBadge value={item.risk_level || 'empty'} />
                    </div>
                  </td>
                  <td className="break-words px-3 py-2 text-slate-700">{localizeText(item.trigger_mode)}</td>
                  <td className="px-3 py-2 text-slate-700">{formatDateTime(item.updated_at)}</td>
                </tr>
              ))
            ) : (
              <tr>
                <td className="px-3 py-6 text-sm text-slate-400" colSpan={5}>
                  {loading ? '正在加载执行队列' : '暂无执行记录'}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function AuditTab({ events, loading }: { events: DeliveryAuditEvent[]; loading: boolean }) {
  return (
    <div className="overflow-hidden rounded border border-slate-200">
      <div className="flex items-center justify-between gap-2 border-b border-slate-200 px-3 py-2">
        <div className="text-sm font-medium text-slate-900">审计记录</div>
        <StatusBadge value={loading ? 'loading' : `${events.length} 条`} />
      </div>
      <div className="max-h-[520px] overflow-auto">
        <table className="w-full table-fixed text-left text-sm">
          <thead className="bg-slate-50 text-xs font-medium uppercase text-slate-500">
            <tr>
              <th className="w-[17%] px-3 py-2">时间</th>
              <th className="w-[16%] px-3 py-2">操作者</th>
              <th className="w-[20%] px-3 py-2">动作</th>
              <th className="w-[17%] px-3 py-2">对象</th>
              <th className="w-[30%] px-3 py-2">摘要</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {events.length > 0 ? (
              events.map((event) => (
                <tr key={event.id}>
                  <td className="px-3 py-2 text-xs text-slate-600">{formatDateTime(event.created_at)}</td>
                  <td className="break-words px-3 py-2 text-slate-700">{event.actor_ref}</td>
                  <td className="break-words px-3 py-2">
                    <StatusBadge value={formatAuditAction(event.action)} />
                  </td>
                  <td className="break-words px-3 py-2 text-slate-700">
                    {formatAuditEntity(event.entity_type, event.entity_id)}
                  </td>
                  <td className="break-words px-3 py-2 text-slate-700">
                    <div className="line-clamp-2">{localizeText(event.summary)}</div>
                  </td>
                </tr>
              ))
            ) : (
              <tr>
                <td className="px-3 py-6 text-sm text-slate-400" colSpan={5}>
                  {loading ? '正在加载审计记录' : '暂无审计记录'}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function StageBlock({ label, status, time }: { label: string; status?: string | null; time?: string | null }) {
  return (
    <div className="rounded border border-slate-200 bg-slate-50 px-3 py-2">
      <div className="mb-1 flex items-center justify-between gap-2">
        <div className="text-sm font-medium text-slate-900">{label}</div>
        <StatusBadge value={status} />
      </div>
      <div className="text-xs text-slate-500">{time ? formatDateTime(time) : '暂无时间戳'}</div>
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
  const rawLabel = value === undefined || value === null || value === '' ? 'empty' : String(value);
  const label = formatStatusLabel(rawLabel);
  const tone = rawLabel.includes('manual') || rawLabel.includes('blocked') || rawLabel.includes('failed')
    ? 'bg-amber-50 text-amber-700 border-amber-200'
    : rawLabel.includes('ready') ||
        rawLabel.includes('approved') ||
        rawLabel.includes('queued') ||
        rawLabel.includes('succeeded') ||
        rawLabel.includes('completed') ||
        rawLabel.includes('deployed') ||
        rawLabel.includes('passed')
      ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
      : rawLabel.includes('running') || rawLabel.includes('loading')
        ? 'bg-blue-50 text-blue-700 border-blue-200'
        : 'bg-slate-50 text-slate-700 border-slate-200';

  return (
    <span className={`inline-flex max-w-[11rem] shrink-0 items-center rounded border px-2 py-0.5 text-xs font-medium ${tone}`}>
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
              {localizeText(item)}
            </li>
          ))}
        </ul>
      ) : (
        <div className="text-sm text-slate-400">暂无条目</div>
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
        {localizeText(value || '暂无内容')}
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

function hydrateDemandDetail(detail: DeliveryDemandDetail): DeliveryResult {
  const spec = latestByDate(detail.spec_cards);
  const repo = latestByDate(detail.repo_contexts);
  const impact = latestByDate(detail.impact_analyses);
  const task = latestByDate(detail.coding_tasks);
  const run = latestByDate(task?.execution_runs || []);
  const mergeRequest = latestByDate(task?.merge_requests || []);
  const deployRecord = latestByDate(mergeRequest?.deploy_records || []);
  const verificationRecord = latestByDate(deployRecord?.verification_records || []);

  return {
    demand: detail,
    detail,
    spec,
    repo,
    impact,
    task,
    run,
    mergeRequest,
    deployRecord,
    verificationRecord,
  };
}

function deriveSteps(result: DeliveryResult): Record<StepKey, StepState> {
  return {
    demand: result.demand ? 'done' : 'idle',
    spec: result.spec ? 'done' : 'idle',
    repo: result.repo ? 'done' : 'idle',
    impact: result.impact ? 'done' : 'idle',
    task: result.task ? stepFromTask(result.task) : 'idle',
    run: result.run ? stepFromRun(result.run) : 'idle',
    mr: result.mergeRequest ? stepFromMergeRequest(result.mergeRequest) : 'idle',
    deploy: result.deployRecord ? stepFromDeployRecord(result.deployRecord) : 'idle',
    verify: result.verificationRecord ? stepFromVerificationRecord(result.verificationRecord) : 'idle',
  };
}

function hasResumableWork(result: DeliveryResult): boolean {
  if (!result.demand) {
    return false;
  }
  if (!result.spec || !result.repo || !result.impact || !result.task || !result.run) {
    return true;
  }
  if (result.task.status === 'running' || result.run.status === 'running') {
    return false;
  }
  return shouldRunExecution(result);
}

function needsManualApproval(result: DeliveryResult): boolean {
  if (!result.demand || result.demand.status === 'blocked' || hasManualApproval(result)) {
    return false;
  }
  const highRisk = result.demand.risk_level === 'L2' || result.demand.risk_level === 'L3';
  if (!highRisk) {
    return false;
  }
  const hasManualGate = (result.detail?.gate_checks || []).some((gate) => gate.status === 'manual_required');
  return (
    result.spec?.status === 'manual_review' ||
    result.task?.status === 'draft' ||
    result.run?.status === 'blocked' ||
    hasManualGate
  );
}

function hasManualApproval(result: DeliveryResult): boolean {
  return (result.detail?.gate_checks || []).some((gate) => {
    const evidence = gate.evidence_json || {};
    return (
      gate.gate_type === 'execution_allowed' &&
      gate.status === 'passed' &&
      evidence.approval_type === 'manual' &&
      evidence.approved === true
    );
  });
}

function isHighRiskResult(result: DeliveryResult): boolean {
  const riskLevel = result.demand?.risk_level || result.impact?.risk_level;
  return riskLevel === 'L2' || riskLevel === 'L3';
}

function hasFailedCheckEvidence(run?: DeliveryExecutionRun): boolean {
  return extractCheckEvidence(run).some((check) => check.status !== 'passed');
}

function shouldRunExecution(result: DeliveryResult): boolean {
  if (!result.task) {
    return false;
  }
  if (!result.run) {
    return true;
  }
  return (
    result.task.status === 'ready' ||
    result.task.status === 'blocked' ||
    result.run.status === 'queued' ||
    result.run.status === 'blocked' ||
    result.run.status === 'failed'
  );
}

function stepFromTask(task: DeliveryCodingTask): StepState {
  if (task.status === 'blocked') {
    return 'failed';
  }
  if (task.status === 'running') {
    return 'running';
  }
  return 'done';
}

function stepFromRun(run: DeliveryExecutionRun): StepState {
  if (run.status === 'failed' || run.status === 'blocked') {
    return 'failed';
  }
  if (run.status === 'running' || run.status === 'queued') {
    return 'running';
  }
  return 'done';
}

function stepFromMergeRequest(mergeRequest: DeliveryMergeRequestRecord): StepState {
  if (mergeRequest.status === 'review_blocked') {
    return 'failed';
  }
  if (mergeRequest.review_status === 'pending' || mergeRequest.status === 'created' || mergeRequest.status === 'reviewing') {
    return 'running';
  }
  return 'done';
}

function stepFromDeployRecord(deployRecord: DeliveryDeployRecord): StepState {
  return deployRecord.status === 'failed' ? 'failed' : 'done';
}

function stepFromVerificationRecord(verificationRecord: DeliveryVerificationRecord): StepState {
  return verificationRecord.status === 'failed' ? 'failed' : 'done';
}

function latestByDate<T extends { id: number; created_at: string }>(items: T[]): T | undefined {
  return [...items].sort((left, right) => {
    const timeDiff = new Date(right.created_at).getTime() - new Date(left.created_at).getTime();
    return timeDiff || right.id - left.id;
  })[0];
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

function formatCodexInvocation(run?: DeliveryExecutionRun): string | null {
  const evidence = run?.evidence_json;
  if (!isRecord(evidence) || !isRecord(evidence.dispatch) || !isRecord(evidence.dispatch.codex_invocation)) {
    return null;
  }
  const invocation = evidence.dispatch.codex_invocation;
  if (invocation.enabled === false) {
    return '未启用';
  }
  const preflight = isRecord(invocation.preflight) ? invocation.preflight : null;

  return [
    `状态：${formatStatusLabel(String(invocation.status || 'unknown'))}`,
    preflight
      ? `预检：${formatStatusLabel(String(preflight.status || 'unknown'))}${
          preflight.exit_code === undefined || preflight.exit_code === null ? '' : `，退出码 ${String(preflight.exit_code)}`
        }`
      : null,
    invocation.exit_code === undefined || invocation.exit_code === null ? null : `退出码：${String(invocation.exit_code)}`,
    invocation.prompt_file ? `提示文件：${String(invocation.prompt_file)}` : null,
    Array.isArray(invocation.changed_files) && invocation.changed_files.length > 0
      ? `变更文件：${invocation.changed_files.map(String).join(', ')}`
      : null,
    Array.isArray(invocation.changed_file_violations) && invocation.changed_file_violations.length > 0
      ? `越权文件：${invocation.changed_file_violations.map(String).join(', ')}`
      : null,
    invocation.error ? `错误：${String(invocation.error)}` : null,
  ].filter(Boolean).join('\n');
}

function collectFailureDetails(result: DeliveryResult, checks: CheckEvidence[]): Array<{ title: string; content: string }> {
  const details: Array<{ title: string; content: string }> = [];

  checks
    .filter((check) => check.status !== 'passed')
    .forEach((check) => {
      const fragments = [
        check.error ? `error: ${check.error}` : '',
        check.stdout_tail ? `stdout:\n${check.stdout_tail}` : '',
        check.stderr_tail ? `stderr:\n${check.stderr_tail}` : '',
      ].filter(Boolean);
      if (fragments.length > 0) {
        details.push({
          title: `${formatStatusLabel(check.status)}：${check.command}`,
          content: fragments.join('\n\n'),
        });
      }
    });

  const warningLogs = result.run?.logs.filter((log) => log.level !== 'info') || [];
  warningLogs.forEach((log) => {
    details.push({
      title: `${formatLogLevel(log.level)}：执行日志`,
      content: log.message,
    });
  });

  if (result.run?.result_summary && result.run.status !== 'succeeded') {
    details.push({
      title: '执行摘要',
      content: result.run.result_summary,
    });
  }

  return details;
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

function formatStatusLabel(value?: string | number | null): string {
  if (value === undefined || value === null || value === '') {
    return '无内容';
  }

  const raw = String(value);
  const statusLabels: Record<string, string> = {
    idle: '未开始',
    loading: '加载中',
    running: '运行中',
    done: '已完成',
    failed: '失败',
    empty: '无内容',
    intake: '已接收',
    planned: '已规划',
    draft: '草稿',
    manual_review: '待人工确认',
    manual_required: '需人工处理',
    spec_manual_required: '规格待确认',
    approved: '已确认',
    superseded: '已替换',
    ready: '就绪',
    insufficient: '信息不足',
    queued: '排队中',
    blocked: '已阻塞',
    completed: '已完成',
    created: '已创建',
    pending: '待处理',
    review_passed: '评审通过',
    review_blocked: '评审阻塞',
    reviewing: '评审中',
    blocking: '阻塞中',
    deployed: '已部署',
    closed: '已关闭',
    succeeded: '成功',
    passed: '通过',
    rejected: '已拒绝',
    risk: '风险',
    unknown: '未知',
  };

  return statusLabels[raw] || raw;
}

function formatGateType(value?: string | null): string {
  if (!value) {
    return '未知门禁';
  }

  const gateLabels: Record<string, string> = {
    spec_ready: '规格就绪',
    risk_classified: '风险已分级',
    repo_context_ready: '仓库上下文就绪',
    impact_analyzed: '影响分析完成',
    coding_task_ready: '编码任务就绪',
    execution_allowed: '允许执行',
    self_test_passed: '自测通过',
    review_passed: '评审通过',
    test_deployed: '测试环境已部署',
    verification_passed: '验收通过',
  };

  return gateLabels[value] || value;
}

function formatLogLevel(value?: string | null): string {
  const logLevelLabels: Record<string, string> = {
    debug: '调试',
    info: '信息',
    warn: '警告',
    warning: '警告',
    error: '错误',
  };

  return logLevelLabels[String(value || 'info')] || String(value || '信息');
}

function formatAuditAction(value: string): string {
  const labels: Record<string, string> = {
    'delivery.demand_created': '创建需求',
    'delivery.manual_approval_recorded': '人工审批',
    'delivery.merge_request_created': '创建 MR',
    'delivery.merge_request_review_recorded': '记录评审',
    'delivery.test_deployment_created': '测试部署',
    'delivery.verification_recorded': '记录验收',
    'auth.project_created': '创建项目',
    'auth.user_created': '创建用户',
  };

  return labels[value] || value;
}

function formatAuditEntity(entityType: string, entityId?: number | null): string {
  const labels: Record<string, string> = {
    demand: '需求',
    merge_request: 'MR',
    deployment: '部署',
    verification: '验收',
    project: '项目',
    user: '用户',
  };
  const label = labels[entityType] || entityType;
  return entityId ? `${label} #${entityId}` : label;
}

function localizeText(value: string): string {
  let output = value;
  const exactTranslations: Record<string, string> = {
    'Add a compact execution status badge to the delivery dashboard.': '为交付工作台添加紧凑的执行状态标识。',
    'Add a compact status badge to the workbench todo list.': '为工作台待办列表添加紧凑的状态标识。',
    'Add a test feature': '添加测试功能',
    'Change login permission logic and migrate production user tokens.': '调整登录权限逻辑并迁移生产用户令牌。',
    'Workflow failed': '工作流执行失败',
    'Continue failed': '继续执行失败',
    'Retry checks failed': '重试检查失败',
    'Manual approval failed': '人工审批提交失败',
    'Merge request record created': '合并请求记录已创建',
    'Merge request review recorded': '合并请求评审结果已记录',
    'Deployment record created': '测试环境记录已创建',
    'Verification record created': '验收结果已记录',
  };
  const trimmed = output.trim();
  if (exactTranslations[trimmed]) {
    return exactTranslations[trimmed];
  }

  const replacements: Array<[RegExp, string]> = [
    [/Add a compact execution status badge to the delivery dashboard\./g, '为交付工作台添加紧凑的执行状态标识。'],
    [/Add a compact status badge to the workbench todo list\./g, '为工作台待办列表添加紧凑的状态标识。'],
    [/Add a test feature/g, '添加测试功能'],
    [/Change login permission logic and migrate production user tokens\./g, '调整登录权限逻辑并迁移生产用户令牌。'],
    [/Required checks passed \((\d+)\/(\d+)\)\./g, '必要检查通过（$1/$2）。'],
    [/Required checks failed \((\d+)\/(\d+) passed\)\./g, '必要检查失败（$1/$2 通过）。'],
    [/Execution (queued|running|blocked|failed|succeeded|completed)/g, '执行状态：$1'],
    [/As a product or delivery owner, I want this request to be converted into a scoped engineering change so that an AI coding executor can implement it with clear acceptance criteria\. Original input:/g, '作为产品或交付负责人，我希望该需求被转化为边界清晰的工程变更，让 AI 编码执行器可以依据明确验收标准完成实现。原始输入：'],
    [/Implement the smallest safe change that satisfies the accepted user story\./g, '在满足已确认用户故事的前提下，实施最小且安全的变更。'],
    [/The requested behavior is implemented and demonstrable\./g, '已实现并可演示所请求的行为。'],
    [/Existing related behavior is not regressed\./g, '现有关联行为没有回归。'],
    [/Required checks pass and evidence is recorded\./g, '必要检查通过，并记录执行证据。'],
    [/Do not bypass hard gates\./g, '不得绕过硬性门禁。'],
    [/Do not perform production, secret, or irreversible data operations automatically\./g, '不得自动执行生产、密钥或不可逆数据操作。'],
    [/Keep changes scoped to the confirmed spec\./g, '变更必须限制在已确认规格范围内。'],
    [/No provider-specific high-risk evidence was found in the initial draft\./g, '初始草稿中未发现特定供应商相关的高风险证据。'],
    [/No high-risk keyword detected in the initial intake\./g, '初始录入中未检测到高风险关键词。'],
    [/Repository context was collected from demand text and provided context payload\./g, '仓库上下文已根据需求文本和提供的上下文载荷收集。'],
    [/No external code analysis provider has been invoked in mock mode\./g, '模拟模式下未调用外部代码分析服务。'],
    [/Local repository context was collected from the current workspace\./g, '本地仓库上下文已从当前工作区收集。'],
    [/Workspace root:/g, '工作区根目录：'],
    [/Scanned (\d+) candidate source and documentation files\./g, '已扫描 $1 个候选源码和文档文件。'],
    [/Top-level areas:/g, '顶层区域：'],
    [/Matched (\d+) candidate files for this demand\./g, '本需求匹配到 $1 个候选文件。'],
    [/Dependency and check references:/g, '依赖和检查引用：'],
    [/Impact analysis is based on the generated spec and repository context\./g, '影响分析基于已生成规格和仓库上下文。'],
    [/Impact analysis used the local repository context and demand-specific candidate files\./g, '影响分析已使用本地仓库上下文和需求相关候选文件。'],
    [/Impacted areas:/g, '影响区域：'],
    [/Affected candidate files: (\d+)\./g, '候选受影响文件：$1 个。'],
    [/Mock mode marks this as a planning aid, not a full static analysis result\./g, '模拟模式下该结果仅作为规划辅助，不代表完整静态分析结果。'],
    [/Keep implementation within the allowed paths declared on the coding task\./g, '实现必须限制在编码任务声明的允许路径内。'],
    [/Use the affected candidate files as the initial implementation scope\./g, '将候选受影响文件作为初始实现范围。'],
    [/Keep changes inside the derived allowed paths unless a human expands scope\./g, '除非人工扩大范围，否则变更必须保持在自动推导的允许路径内。'],
    [/Run the required checks before creating a merge request\./g, '创建合并请求前必须运行必要检查。'],
    [/Run npm run build before creating a merge request\./g, '创建合并请求前运行 npm run build。'],
    [/Run python -m pytest for backend changes\./g, '后端变更需要运行 python -m pytest。'],
    [/Escalate to human review if touched files exceed the analyzed scope\./g, '如果变更文件超出分析范围，必须升级为人工审查。'],
    [/You are implementing an AI PJM delivery task\./g, '你正在执行一个 AI PJM 交付任务。'],
    [/Demand ID:/g, '需求 ID：'],
    [/Spec ID:/g, '规格 ID：'],
    [/Task ID:/g, '任务 ID：'],
    [/Run ID:/g, '执行 ID：'],
    [/Title:/g, '标题：'],
    [/User story:/g, '用户故事：'],
    [/Scope:/g, '范围：'],
    [/Allowed paths:/g, '允许修改路径：'],
    [/Acceptance criteria:/g, '验收标准：'],
    [/Constraints:/g, '约束：'],
    [/Required checks:/g, '必要检查：'],
    [/Forbidden Actions/g, '禁止动作'],
    [/Required Checks/g, '必要检查'],
    [/Expected Evidence/g, '期望证据'],
    [/Task Prompt/g, '任务提示'],
    [/Before finishing, run the required checks and report changed files, test results, and residual risks\./g, '结束前，请运行必要检查，并报告变更文件、测试结果和剩余风险。'],
    [/Changed files summary/g, '变更文件摘要'],
    [/Test command output/g, '测试命令输出'],
    [/Known residual risk, if any/g, '已知剩余风险，如有'],
    [/Do not run production deployments\./g, '不得执行生产部署。'],
    [/Do not modify secrets or credentials\./g, '不得修改密钥或凭据。'],
    [/Do not perform destructive database operations\./g, '不得执行破坏性数据库操作。'],
    [/Do not bypass tests or gate checks\./g, '不得绕过测试或门禁检查。'],
    [/Spec contains user story, scope, acceptance criteria, constraints, and risks\./g, '规格包含用户故事、范围、验收标准、约束和风险。'],
    [/Risk classified as DeliveryRiskLevel\.([A-Z0-9]+)\./g, '风险已分级为 $1。'],
    [/Repository context is sufficient for impact analysis\./g, '仓库上下文足以支撑影响分析。'],
    [/Impact analysis completed\./g, '影响分析已完成。'],
    [/Coding task package was created\./g, '编码任务包已创建。'],
    [/Coding task can be queued for executor dispatch\./g, '编码任务可以进入执行器队列。'],
    [/Execution dispatch started\./g, '执行分发已开始。'],
    [/Isolated git worktree prepared\./g, '隔离 Git 工作区已准备完成。'],
    [/Runtime dependency cache linked\./g, '运行时依赖缓存已挂接。'],
    [/Check passed:/g, '检查通过：'],
    [/Check failed:/g, '检查失败：'],
    [/Codex execution command completed\./g, 'Codex 执行命令已完成。'],
    [/Codex execution command failed\./g, 'Codex 执行命令失败。'],
    [/Codex execution preflight completed\./g, 'Codex 执行预检已完成。'],
    [/Codex execution preflight failed\./g, 'Codex 执行预检失败。'],
    [/Codex execution preflight timed out\./g, 'Codex 执行预检超时。'],
    [/Codex execution preflight failed to start\./g, 'Codex 执行预检无法启动。'],
    [/Codex execution is enabled but no command template is configured\./g, '已启用 Codex 执行，但未配置命令模板。'],
    [/Automatic repair is blocked for L2\/L3 risk tasks/g, 'L2/L3 风险任务禁止自动修复'],
    [/Automatic repair requires a failed execution run/g, '自动修复需要先有失败的执行记录'],
    [/Automatic repair requires failed check evidence/g, '自动修复需要失败检查证据'],
    [/Automatic repair is blocked because changed files exceeded allowed paths/g, '变更文件超出允许路径，自动修复已阻断'],
    [/A completed coding task is required before creating a merge request/g, '创建合并请求前必须先完成编码任务'],
    [/A succeeded execution run is required before creating a merge request/g, '创建合并请求前必须先有成功的执行记录'],
    [/Execution run has no source branch for merge request creation/g, '执行记录缺少可创建合并请求的源分支'],
    [/Merge request review passed\./g, '合并请求评审已通过。'],
    [/Merge request review has blocking issues\./g, '合并请求评审存在阻塞问题。'],
    [/A passed merge request review is required before test deployment/g, '创建测试环境记录前必须先通过合并请求评审'],
    [/Test deployment record was created\./g, '测试环境记录已创建。'],
    [/Test deployment verification passed\./g, '测试环境验收已通过。'],
    [/Test deployment verification failed\./g, '测试环境验收未通过。'],
    [/Execution workspace preparation failed:/g, '执行工作区准备失败：'],
    [/Run summary/g, '执行摘要'],
    [/execution log/g, '执行日志'],
    [/status: ([a-z_]+)/g, '状态：$1'],
    [/exit: /g, '退出码：'],
    [/prompt: /g, '提示文件：'],
    [/changed: /g, '变更文件：'],
  ];

  replacements.forEach(([pattern, replacement]) => {
    output = output.replace(pattern, replacement);
  });

  Object.entries({
    idle: '未开始',
    loading: '加载中',
    running: '运行中',
    failed: '失败',
    passed: '通过',
    succeeded: '成功',
    queued: '排队中',
    approved: '已确认',
    planned: '已规划',
    completed: '已完成',
    blocked: '已阻塞',
    created: '已创建',
    pending: '待处理',
    review_passed: '评审通过',
    review_blocked: '评审阻塞',
    reviewing: '评审中',
    blocking: '阻塞中',
    deployed: '已部署',
    closed: '已关闭',
    disabled: '未启用',
    unknown: '未知',
  }).forEach(([raw, localized]) => {
    output = output.replace(new RegExp(`\\b${raw}\\b`, 'g'), localized);
  });

  return output;
}

function formatConfidence(value?: number | null): string | null {
  if (value === undefined || value === null) {
    return null;
  }
  return `${Math.round(value * 100)}%`;
}

function formatDateTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}
