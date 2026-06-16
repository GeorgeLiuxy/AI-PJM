# 目标环境验证清单

本文档用于真实试点环境联调，不替代本地 `docs/v2-verification-guide.md`。本地已完成的 SQLite、Alembic、工作台、trace、可观测性和 Provider 首版能力，不应在这里重复验证；这里聚焦必须接入真实外部系统后才能判断的生产可用性。

## 1. 前置条件

- 使用非默认管理员密码。
- 使用目标环境数据库，执行 `backend/scripts/migrate.py upgrade head`。
- 配置项目级 `openai_api_key`、`dify_api_key`、`gitlab_token` 或 `github_token`、`deploy_token`。
- 配置真实代码仓库路径、默认分支、MR/PR 目标仓库和测试环境地址。
- 启动后端、前端、Symphony worker、部署同步 worker、可观测告警 worker。
- 若暂未接入上游 Symphony daemon，先把 `SYMPHONY_RUNNER_COMMAND` 配置为目标环境可用的 Codex/Symphony 命令模板；该命令会收到 `{workspace}`、`{task_package_file}` 和 `{task_prompt_file}`。

## 2. Symphony 执行联调

验收目标：低风险任务能从 AI PJM 入队，由 Symphony/Codex 执行并回写证据。

执行步骤：

1. 创建 L0/L1 低风险需求。
2. 生成 Spec、上下文、影响分析和任务包。
3. 创建 `executor_type=symphony` 的执行 run。
4. 确认 HTTP dispatch 不长时间阻塞，run 保持 queued。
5. 确认 worker claim、heartbeat、complete 都写入证据。
6. 确认成功 run 包含 changed files、commit、required checks 和 allowed paths 校验结果。
7. 如果使用真实上游 Symphony daemon，确认 daemon 通过 AI PJM bridge contract 读取任务、回写事件和完成状态，而不是绕过 AI PJM 门禁。

失败验收：

- worker 异常退出后，lease 过期 run 会恢复为 failed。
- cancelled run 的 late complete 会被拒绝。
- changed files 超出 allowed paths 时，run 不得进入 succeeded。

## 3. Dify/OpenAI 生产质量评估

验收目标：远端 Provider 只生成草稿，不绕过门禁，并能量化输出质量。

执行步骤：

1. 运行 `scripts/provider_quality_smoke.py --provider all --output-file .runtime/provider-quality-report.json`，一次覆盖 local、Dify、OpenAI；必要时也可分别运行单个 provider。
2. 每个 Provider 至少验证 10 条真实历史需求或脱敏样例需求。
3. 记录 Spec/Impact 的 schema 版本、prompt 版本、workflow/model 和质量分。
4. 人工抽检低分样例，确认扣分项能解释问题。

通过标准：

- Provider 失败会在质量报告中记录脱敏错误，并在平台流程中降级或进入人工处理，不直接修改数据库终态。
- 输出缺少必填字段、风险等级异常或置信度过低时，不自动推进执行。
- 明文 Token、Key、Authorization 不进入日志、证据或前端。

## 4. MR/PR 与远端评审

验收目标：自测通过后能创建真实 MR/PR，远端评审和 CI 状态能回写平台。

执行步骤：

1. 使用真实仓库创建低风险变更。
2. 自测通过后创建 GitLab MR 或 GitHub PR。
3. 确认源分支已推送到远端。
4. 在远端制造一条阻塞评论或失败 CI。
5. 同步远端评审，确认平台记录 blocking 状态和证据。
6. 对低风险任务触发自动修复，确认修复分支推回原 MR/PR 源分支。

通过标准：

- MR/PR 链接、iid/number、目标分支、review 状态和 CI/check 状态可见。
- webhook 或手动同步都不能绕过 `review_passed` 门禁。

## 5. 真实测试环境部署

验收目标：MR/PR 评审通过后可触发目标测试环境部署，并能追踪状态。

执行步骤：

1. 配置项目级测试环境 URL、日志 URL、部署 webhook。
2. 创建测试部署记录。
3. 确认 webhook 返回 deployment URL、status URL、commit 或流水线标识。
4. 执行单条状态同步和 pending 批量同步。
5. 制造失败部署，确认可重新部署并保留来源证据。
6. 确认目标 CI/CD 返回的 pipeline/job/stage/step/check 状态、失败原因、日志链接和运行标识会进入部署证据；若目标平台字段不在通用解析范围内，在 webhook adapter 中先转成通用字段。

通过标准：

- deployed 才能进入验收。
- failed 不得推进验收。
- 日志 URL 和日志尾部已脱敏。

## 6. 容量基准

验收目标：试点规模下核心读写接口可接受。

执行步骤：

1. 使用根目录脚本生成接近真实规模的数据并测量核心读接口 p95 和错误率。
2. 在真实数据库连接池、真实网络和真实 worker 并发下重复测试。
3. 保存 `.runtime/capacity` 下的 seed/performance JSON 作为上线证据。

```powershell
.\scripts\check-capacity-smoke.ps1 -Count 10000 -IncludeDeliveryRecords -BaseUrl http://127.0.0.1:8010 -Requests 120 -Concurrency 12 -MaxP95Ms 1000 -MaxErrorRatePercent 1
```

如果目标环境已经由其他方式准备好数据，只跑只读性能烟测：

```powershell
.\scripts\check-capacity-smoke.ps1 -SkipSeed -BaseUrl https://ai-pjm-test.example.com -Requests 120 -Concurrency 12
```

建议记录：

- 数据量：需求数、任务数、run 数、日志数、MR/PR 数。
- 并发：worker 数、队列长度、同时执行 run 数。
- 指标：p50、p95、p99、错误率、数据库 CPU/内存/连接数。

## 7. 集中监控和告警

验收目标：生产故障可以被发现、定位和恢复。

执行步骤：

1. 接入 `/api/v2/observability/metrics` 到目标指标平台。
2. 接入 JSON Lines 应用日志到集中日志平台。
3. 配置 queue、worker lease、凭证、部署失败和近期失败率告警。
4. 触发一条测试告警，确认通知渠道收到并能定位到项目或 trace。

Prometheus 接入样例：

```text
ops/prometheus/prometheus.example.yml
ops/prometheus/ai-pjm-alerts.yml
```

如果 `AUTH_ENABLED=true`，为 Prometheus 配置只读监控 token，并按 `prometheus.example.yml` 中的 `authorization` 注释接入。

通过标准：

- 告警包含项目、类别、严重级别、数量和建议动作。
- 任一失败需求可以从工作台 trace 时间线定位到失败阶段和证据。
- 告警恢复后指标回落，工作台状态同步恢复。

## 8. 发布判定

满足以下条件后，才能进入真实试点：

- 一个 L0/L1 需求完成从输入到 MR/PR、测试部署、验收的闭环。
- 一个失败执行能被定位、修复或人工接管。
- 一个高风险需求被人工拦截并保留审批证据。
- 一个部署失败不会推进验收，并能重新部署。
- 监控能发现 worker 异常、队列积压、凭证失效和部署失败。
