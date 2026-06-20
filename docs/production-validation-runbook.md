# AI PJM 生产化验证手册

本文档用于约束上线前验证顺序。目标是尽快进入可试点生产状态，同时避免把精力消耗在当前阶段不必要的企业治理能力上。

## 优先级排序

### P0：发布前硬基线

每次合并或发布前必须执行：

```powershell
.\scripts\check-production-suite.ps1
```

该脚本覆盖：

- 后端关键测试：认证、交付主链路、可观测性、迁移和健康检查。
- 本地 Provider 质量烟测：验证 Spec 生成质量下限。
- 前端安全审计：`npm audit --audit-level=high`，默认只执行一次，避免 npm registry 或安全审计接口异常时反复阻塞主线。
- 前端回归测试：Vitest。
- 前端生产构建：Vite build。

可选参数：

```powershell
.\scripts\check-production-suite.ps1 -IncludePostgres
.\scripts\check-production-suite.ps1 -Provider all
.\scripts\check-production-suite.ps1 -AuditRetries 3
.\scripts\check-production-readiness.ps1 -SkipFrontend
.\scripts\check-production-readiness.ps1 -SkipBackend
.\scripts\check-production-readiness.ps1 -ContinueOnError
.\scripts\check-production-readiness.ps1 -AuditRetries 3
.\scripts\check-production-compose.ps1
.\scripts\check-production-suite.ps1 -BuildComposeImages
.\scripts\check-production-compose.ps1 -SmokeUp
.\scripts\check-symphony-runner.ps1 -UseRecommendedCodexCommand -RequireCodex
.\scripts\check-production-suite.ps1 -CheckSymphonyRunner -UseRecommendedCodexRunner -RequireCodexRunner
.\scripts\check-merge-request-provider.ps1 -Provider github
.\scripts\check-production-suite.ps1 -CheckMergeRequestProvider -MergeRequestProvider github
```

验收标准：脚本所有选中检查通过，且工作区没有未提交的有效代码。若只有 `npm audit` 因 registry、代理或审计服务不可用失败，应记录为外部阻塞；本地功能验证可临时使用 `-SkipAudit`，修复外部网络或 registry 状态后再补跑审计。

Symphony/Codex runner 配置验证默认不执行 AI 编码任务，只生成样例 task package 和 prompt 文件，检查 `SYMPHONY_RUNNER_COMMAND` 或推荐 Codex 命令模板能否展开，并确认 Codex CLI 是否在 PATH 中。只有明确需要端到端执行命令时才增加 `-Execute`。

MR/PR Provider 预检默认只读仓库、目标分支和 MR/PR 列表，不创建 PR/MR、不推送分支。通过后仍需确认 token 具备创建 PR/MR 和源分支 push 权限，再进入真实低风险需求试点。

远端仓库提供可选 GitHub Actions 工作流 `.github/workflows/production-validation.yml`。该工作流只允许手动 `workflow_dispatch` 触发，不会在 push 或 pull request 时自动运行，避免 GitHub 账号计费状态或 Actions 配额阻塞主链路。正式合并前的最低门禁以本地 `check-production-suite.ps1`、生产等价 Compose 验证和目标环境试点证据为准。

推送后用固定脚本读取远端 workflow 状态，并保留 JSON 证据：

```powershell
$env:GITHUB_TOKEN="<github-token>"
.\scripts\check-github-actions.ps1 -Wait
```

该脚本默认读取当前 `HEAD`、`main` 分支和 `Production Validation` workflow，报告写入 `.runtime\github-actions\*.json`。如果 GitHub API 限流、Token 失效、Actions 未启用或账号计费锁定导致 workflow 未执行，脚本会把结果标记为外部阻塞；这类问题不应消耗主链路开发时间，修复 GitHub 侧状态后重新运行即可。

如团队当前不使用付费 GitHub Actions 或账号处于计费锁定状态，不需要为了试点生产强行处理；保持远端 CI 为可选增强项即可。

`GITHUB_TOKEN` 是默认必需项，避免未认证 API 被限流。只有明确需要验证匿名访问时，才使用 `-AllowAnonymous`。

本地或目标测试机可用 Docker Compose 启动一套生产等价最小栈：

```powershell
Copy-Item docker-compose.production.env.example .env.production.local
# 编辑 .env.production.local，替换数据库密码、管理员密码、SECRET_STORE_MASTER_KEY 和外部系统凭证。
docker compose --env-file .env.production.local -f docker-compose.production.yml up -d --build postgres migrate backend frontend
```

验证入口：

```powershell
Invoke-RestMethod http://127.0.0.1:8080/health
Invoke-WebRequest http://127.0.0.1:8080/ | Select-Object -ExpandProperty StatusCode
```

需要后台自动同步和告警时，在已配置 `SYMPHONY_BRIDGE_TOKEN`、`AI_PJM_API_TOKEN`、部署 webhook 和告警 webhook 后再打开 worker profile：

```powershell
docker compose --env-file .env.production.local -f docker-compose.production.yml --profile workers up -d
```

停机命令：

```powershell
docker compose --env-file .env.production.local -f docker-compose.production.yml down
```

验收标准：Compose 配置可解析，PostgreSQL 健康，迁移任务成功退出，后端 `/health` 健康，前端可访问，worker profile 只在凭证齐全时启用。

### P0：真实环境闭环验证

本地测试通过后，在目标测试环境执行以下验证：

1. 启动后端、前端、Symphony worker、部署同步 worker、告警 worker。
2. 打开 `/api/v2/observability/config-health`，确认没有 critical 项。
3. 创建一条低风险需求，完成 Spec、任务包、执行、自测、MR/PR、部署、验收归档。
4. 确认 MR/PR 链接、部署地址、检查结果、执行证据和审计事件都能在工作台看到。
5. 人为制造一次部署失败或评审阻塞，确认系统不会推进验收门禁，并能重新部署或触发修复。
6. 打开 `/api/v2/observability/summary` 和 `/api/v2/observability/metrics`，确认队列、执行失败、凭证健康、部署失败和敏感证据扫描有可观测输出。

验收标准：一条需求可以从业务输入走到验收归档，失败分支可被明确阻断并恢复。

### P1：生产配置验证

必须在真实环境确认：

- `DATABASE_URL` 指向 PostgreSQL。
- `DATABASE_VALIDATE_MIGRATIONS=true`。
- `SECRET_STORE_MASTER_KEY` 由安全渠道注入。
- GitLab/GitHub、部署系统、Dify/OpenAI 凭证优先走项目级 SecretStore。
- webhook secret 已配置，且外部系统回调可以更新原 MR/PR 或部署记录。
- 备份和恢复脚本在目标数据库上可执行。

验收标准：新环境可迁移、可启动、可配置凭证、可创建真实 MR/PR、可触发测试环境部署、可恢复备份。

本地可用 Docker 先做一次生产等价迁移烟测：

```powershell
.\scripts\check-postgres-migrations.ps1
```

该脚本会启动临时 PostgreSQL 16 容器，执行 `backend/scripts/migrate.py upgrade head` 和 `current`，然后自动清理容器。

生产等价服务栈使用根目录的 `docker-compose.production.yml`。该 Compose 文件把迁移、后端、前端和 PostgreSQL 拆开，默认只启动主链路；`deployment-sync-worker`、`observability-alert-worker` 和 `symphony-worker` 放在 `workers` profile，避免未配置外部凭证时误启动失败。

Compose 配置进入固定门禁：

```powershell
.\scripts\check-production-compose.ps1
```

需要验证镜像构建、迁移、后端健康和前端反向代理时，执行隔离实跑烟测：

```powershell
.\scripts\check-production-compose.ps1 -SmokeUp
```

该命令默认使用 Compose project `ai-pjm-smoke`、后端端口 `18010`、前端端口 `18080`，完成健康检查后自动 `down --remove-orphans --volumes`，不影响默认开发端口，并保证下次从干净 PostgreSQL 数据卷验证。若需要保留现场排查，可增加 `-KeepRunning`；若只想保留烟测数据卷，可增加 `-PreserveSmokeVolumes`。

如果当前网络可拉取 Docker Hub 基础镜像，可增加镜像构建验证：

```powershell
.\scripts\check-production-compose.ps1 -BuildImages
```

### P1：外部 Provider 质量验证

本地规则 Provider 只能证明平台链路可用，不能证明生产 AI 质量。接入真实 Dify/OpenAI 后执行：

```powershell
.\scripts\check-provider-quality.ps1 -Provider all
```

`-Provider all` 会预检 Dify/OpenAI 的外部配置。缺少 `DIFY_API_BASE_URL`、`DIFY_API_KEY`、`DIFY_SPEC_WORKFLOW_ID`、`DIFY_IMPACT_WORKFLOW_ID` 或 `OPENAI_API_KEY` 时，脚本会生成 `status=blocked` 的报告并返回可识别的外部阻塞错误；这属于外部条件缺失，不要反复重试。

验收标准：

- local、Dify、OpenAI 的结果都有结构化输出或脱敏失败原因。
- 真实 Provider 输出包含需求摘要、目标、范围、风险、验收标准和任务拆分。
- 不允许 Provider 直接推进数据库状态或绕过门禁。

本地无真实凭证时可先执行：

```powershell
.\scripts\check-provider-quality.ps1 -Provider local
```

接入真实 Dify/OpenAI 后，不要只用默认单条需求冒烟。使用脱敏样例文件批量验证：

```powershell
.\scripts\check-provider-quality.ps1 `
  -Provider all `
  -DemandFile docs\provider-quality-samples.example.json `
  -IncludeImpact
```

真实试点前可把 `docs/provider-quality-samples.example.json` 替换为目标团队的脱敏历史需求样本。报告会按 provider 和样本逐条输出质量分、扣分项、结构化草稿或脱敏失败原因。

### P2：容量和运维验证

进入试点生产前执行：

- 使用合成数据准备脚本生成至少 1 万条交付数据。
- 对只读核心接口执行性能烟测。
- 将 Prometheus 文本指标接入现有监控系统。
- 将告警 worker 接入团队真实通知渠道。
- 固化备份调度、恢复演练和日志保留策略。

Prometheus 最小接入样例位于：

```text
ops/prometheus/prometheus.example.yml
ops/prometheus/ai-pjm-alerts.yml
```

容量基准统一入口：

```powershell
.\scripts\check-capacity-smoke.ps1 -Count 10000 -IncludeDeliveryRecords -BaseUrl http://127.0.0.1:8010 -Requests 120 -Concurrency 12 -MaxP95Ms 1000 -MaxErrorRatePercent 1
```

该脚本会把 seed 和 performance 输出写入 `.runtime/capacity`，便于上线评审留痕。若目标环境已存在压测数据，可加 `-SkipSeed` 只执行只读性能烟测。

验收标准：核心读接口 p95、错误率、队列积压、worker 异常、凭证失效和部署失败都有明确阈值、告警和处理人。

## 当前不优先做

以下能力不阻塞当前生产化试点，除非真实试点暴露明确需求：

- 企业 SSO 或复杂组织治理。
- 多部门、多层级角色体系。
- 大规模多 Agent 自动评审。
- 多仓库联合开发。
- 自动生产发布。
- 复杂知识图谱。

当前阶段优先保证主链路真实可用：上下文收集、任务生成、受控执行、自测、MR/PR、测试部署、验收、证据归档。
