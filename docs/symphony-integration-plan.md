# AI PJM + OpenAI Symphony 融合方案

本文档用于约束 AI PJM 与 OpenAI Symphony 的结合方式。后续涉及执行器、worker、Codex 编排、真实 MR 和部署的开发，必须先对齐本文档。

官方参考：

- OpenAI Symphony: https://openai.com/index/open-source-codex-orchestration-symphony/

## 1. 结论

推荐采用：

```text
AI PJM = 交付控制平面
OpenAI Symphony = Codex 执行编排引擎
```

AI PJM 不改造成 Symphony clone。AI PJM 继续负责需求、上下文、方案、任务包、门禁、密钥、证据链、MR/部署/验收状态；Symphony 负责后台调度、任务领取、隔离 workspace、Codex 执行、日志流和运行状态回写。

这能复用 Symphony 在 daemon、workspace、Codex app-server、并发调度方面的工程能力，同时保留 AI PJM 的交付闭环价值。

## 2. 为什么要结合

AI PJM 当前缺口集中在：

- 执行仍主要由 HTTP dispatch 触发，不是生产级后台 worker。
- 多任务调度、运行恢复、心跳、取消、暂停、重试还未生产化。
- Codex 执行虽然已可用，但还缺更稳的 app-server/daemon 形态。
- 真实 MR、真实部署还需要和执行编排结果打通。

Symphony 的价值在于提供 Codex 编排参考：daemon、任务读取、隔离 workspace、agent 执行、运行状态管理。它适合承担 AI PJM 的执行引擎角色。

## 3. 不做什么

- 不把 AI PJM 的需求、Spec、任务包、验收证据迁移到 Symphony。
- 不让 Symphony 直接决定门禁、风险等级、验收通过或生产发布。
- 不把 issue tracker 变成 AI PJM 的唯一状态源。
- 不为了接 Symphony 重新设计整套业务模型。
- 不优先做多 Agent、知识图谱、自动生产发布。

## 4. 推荐架构

```mermaid
flowchart LR
    A["AI PJM Demand"] --> B["Repo Context / Spec / Impact"]
    B --> C["CodingTask"]
    C --> D["ExecutionRun queued"]
    D --> E["Symphony Bridge API"]
    E --> F["Symphony daemon"]
    F --> G["Isolated workspace"]
    G --> H["Codex app-server / Codex runner"]
    H --> I["Required checks"]
    I --> J["MR / patch / result"]
    J --> K["AI PJM evidence and gates"]
    K --> L["Deploy / verify / archive"]
```

## 5. 最佳集成模式

### 5.1 Bridge 模式

短期最快方案。

AI PJM 生成任务包后，把执行任务暴露给 Symphony。Symphony 领取任务、执行 Codex、回写执行结果。

优点：

- 改动小，最快验证 Symphony 是否适合。
- AI PJM 当前模型不用重构。
- 可以逐步替换现有 HTTP dispatch。

缺点：

- 如果先通过外部 issue tracker 中转，会出现双状态源。
- 需要明确回写合同，避免执行状态漂移。

使用建议：作为第一阶段实现。

### 5.2 Native Adapter 模式

中期推荐方案。

让 Symphony 通过 AI PJM API 读取 `ExecutionRun`，而不是读取外部 issue tracker。AI PJM 提供一个 Symphony-compatible task adapter。

优点：

- AI PJM 仍是唯一业务状态源。
- Symphony 负责执行编排，不接管业务流程。
- 后续可以接多 worker、多项目、并发调度。

缺点：

- 需要实现 claim、heartbeat、event、complete 等内部 API。
- 需要设计幂等和恢复策略。

使用建议：Bridge 验证通过后升级到该模式。

### 5.3 Direct App-Server Executor 模式

备选方案。

AI PJM 不引入完整 Symphony，只借鉴 Symphony 的 Codex app-server 调用方式，自己实现 worker。

优点：

- 依赖更少，状态更简单。

缺点：

- 要自己做 daemon、并发、恢复、workspace 生命周期。
- 节省工作量有限。

使用建议：只有 Symphony 难以嵌入时才采用。

## 6. 数据映射

| AI PJM | Symphony 侧概念 | 说明 |
| --- | --- | --- |
| `DemandItem` | issue context | 需求来源，只读上下文 |
| `RepoContext` | repository context | 仓库、文档、历史需求和配置摘要 |
| `SpecCard` | task requirements | 规格、验收标准、限制条件 |
| `ImpactAnalysis` | planning context | 影响范围、风险原因、建议检查 |
| `CodingTask` | executable task | prompt、allowed paths、forbidden actions、required checks |
| `ExecutionRun` | run / attempt | 一次执行尝试，Symphony 主要操作对象 |
| `ExecutionLog` | event stream | stdout/stderr 摘要、状态、错误、心跳 |
| `GateCheck` | gate result | AI PJM 计算和保存，Symphony 不绕过 |
| `MergeRequestRecord` | PR/MR output | 执行结果产生的远端 MR 记录 |

## 7. 状态映射

| AI PJM `ExecutionRun` | Symphony 状态 | 处理规则 |
| --- | --- | --- |
| `queued` | ready | 可被 daemon claim |
| `running` | in_progress | 已被某个 worker 领取 |
| `succeeded` | completed / human_review | 自测通过，等待 MR/验收下一步 |
| `failed` | failed / needs_repair | 检查失败或执行异常，进入自动修复或人工处理 |
| `cancelled` | cancelled | 停止执行并保留证据 |
| `timed_out` | timed_out | 标记失败，允许按规则重试 |

AI PJM 是最终状态源。Symphony 回写的是事件和建议状态，是否推进门禁由 AI PJM 决定。

## 8. 内部 API 合同

先实现内部 API，不直接暴露给普通前端。

### 8.1 任务领取

```text
GET /api/internal/symphony/execution-runs?status=queued&limit=10
POST /api/internal/symphony/execution-runs/{run_id}/claim
```

要求：

- claim 必须原子化。
- claim 记录 `worker_id`、`claimed_at`、`lease_expires_at`。
- 已被 claim 且 lease 未过期的 run 不可重复领取。

### 8.2 任务包读取

```text
GET /api/internal/symphony/execution-runs/{run_id}/task-package
```

返回：

- task prompt
- allowed paths
- forbidden actions
- required checks
- expected evidence
- repo context 摘要
- repair context
- project execution config

不返回：

- 明文密钥
- 用户 token
- 数据库连接串
- 不必要的历史日志全文

### 8.3 事件回写

```text
POST /api/internal/symphony/execution-runs/{run_id}/events
POST /api/internal/symphony/execution-runs/{run_id}/heartbeat
```

事件类型：

- workspace_created
- codex_started
- codex_output
- check_started
- check_finished
- changed_files_detected
- mr_created
- run_failed
- run_succeeded

所有事件入库前继续走敏感信息脱敏。

### 8.4 完成回写

```text
POST /api/internal/symphony/execution-runs/{run_id}/complete
```

包含：

- final status
- summary
- check results
- changed files
- workspace path
- branch name
- commit sha
- patch or MR link
- evidence links

AI PJM 收到完成事件后再执行：

- allowed paths 校验
- required checks 校验
- self_test_passed 门禁
- 自动修复或人工处理决策

## 9. 安全边界

必须遵守：

- Symphony 不能读取明文密钥；需要外部凭证时通过 AI PJM 颁发短期执行上下文或由 Provider 服务端消费。
- 任务 prompt 不包含密钥。
- stdout/stderr/event_json 入库前走脱敏。
- allowed paths 由 AI PJM 生成并校验，Symphony 只能执行，不能扩大范围。
- 高风险任务没有人工审批，不允许进入 Symphony claim。
- 执行完成后 AI PJM 再做最终门禁判断。

## 10. 分阶段计划

### S0：调研和边界确认

目标：确认 Symphony 能在本地作为执行编排引擎运行。

任务：

- 拉取 Symphony 代码或固定版本引用。
- 跑通最小 daemon。
- 确认 Codex app-server 或 runner 调用方式。
- 记录所需配置、端口、依赖、日志位置。

完成标准：

- 能用一个示例任务触发 Symphony 创建 workspace 并调用 Codex。
- 明确哪些代码可复用，哪些只能借鉴。

### S1：AI PJM 内部执行桥

目标：让 AI PJM 暴露 Symphony 可消费的执行任务合同。

任务：

- 增加 internal API 鉴权。
- 增加 queued run 列表、claim、heartbeat、event、complete 接口。
- 增加 worker lease 字段或 metadata。
- 补并发和幂等测试。

完成标准：

- 不启动 Symphony 时，现有执行链路不受影响。
- 使用测试客户端可以 claim 一个 queued run 并回写完成。

### S2：Symphony Bridge Executor

目标：让 `executor_type = symphony` 的执行记录交给 Symphony。

状态：已完成首版。`get_execution_executor("symphony")` 已返回 `SymphonyBridgeExecutor`；HTTP dispatch 只记录后台投递并保持 run 为 queued，等待 worker claim，不直接运行 Codex 或本地检查。lease 过期的 running run 会被标记 failed，避免 worker 异常退出后永久卡住。平台已提供暂停、恢复、取消控制；同一 coding task 的 queued/running/paused run 会复用现有 active run，避免重复入队。

任务：

- 增加 `SymphonyBridgeExecutor`。（已完成首版）
- `get_execution_executor("symphony")` 返回桥接执行器。（已完成首版）
- 桥接执行器只负责投递/等待/收集结果，不直接跑 Codex。（已完成投递部分；等待/收集由 worker complete 回写负责）
- 支持超时、失败、取消和状态回收。（lease 过期失败恢复、暂停、恢复、取消已完成首版；常驻 worker 待完成）

完成标准：

- AI PJM 页面能看到 Symphony 执行中的状态。
- 失败时保留 Symphony 事件和错误摘要。

### S3：Codex 执行和检查回写

目标：Symphony 真正执行 Codex，并把检查结果回写 AI PJM。

任务：

- 将 AI PJM task package 转成 Symphony task prompt。
- Symphony 创建隔离 workspace。
- Codex 执行后运行 required checks。
- 回写 changed files、check results、stdout/stderr tail。

完成标准：

- 一个低风险任务能通过 Symphony 执行并完成自测。
- 越权文件变更仍由 AI PJM 阻断。

### S4：真实 MR 集成

目标：自测通过后自动创建真实 GitLab/GitHub MR。

状态：GitLab MR provider 首版已实现，可通过 AI PJM 服务端按项目读取 `gitlab_token`，创建 MR 前自动 push 执行分支，并创建 MR。GitLab 远端评审同步首版已实现，可拉取 MR 状态、讨论评论和 commit CI 状态，并回写 MR、门禁、审计和证据链；交付工作台已提供远端 MR 的“同步评审”入口。评审阻塞自动修复串联首版已实现，可把远端阻塞项写入修复 run 的 `repair_context.review_issues`，再由 Codex/Symphony 受控执行。后续重点是修复后更新原 MR、支持 GitLab webhook 和补 GitHub provider。

任务：

- GitLab/GitHub Provider 从项目 SecretStore 读取凭证。（GitLab 首版已完成，GitHub 待实现）
- Symphony 或 AI PJM 推送分支。（AI PJM 服务端自动 push 首版已完成）
- AI PJM 创建 `MergeRequestRecord` 并记录远端 URL。
- 远端失败原因、评论和 CI 状态回写证据。（GitLab 手动同步接口首版已完成）
- 远端阻塞意见触发受控自动修复 run。（首版已完成，更新原 MR 待实现）

完成标准：

- 低风险任务可从需求进入真实 MR。

### S5：真实部署和验收闭环

目标：MR 后进入测试环境，完成业务验收。

状态：`DeployClient` 和 webhook 部署 provider 首版已实现，可通过 AI PJM 服务端按项目读取 `deploy_token` 并回写 `DeployRecord`；环境级配置、CI/CD 状态轮询、重新部署和日志归档待实现。

任务：

- 增加 DeployClient。（已完成首版）
- 支持脚本型、本地 webhook 型或 CI/CD 型部署入口。（webhook 首版已完成）
- 部署结果回写 DeployRecord。（首版已完成）
- 验收失败回到修复或人工处理。

完成标准：

- 一个任务从需求到测试环境地址再到验收记录完成闭环。

### S6：生产化加固

目标：小团队试点稳定运行。

任务：

- worker heartbeat、lease 过期恢复。
- 任务取消、暂停、恢复。
- 队列积压和失败原因可见。
- PostgreSQL/Alembic。
- 最小可观测性。

完成标准：

- worker 重启后任务不会永久卡住。
- 失败任务有明确原因和下一步动作。

## 11. 近期执行顺序

近期按以下顺序执行：

1. S0：拉通 Symphony 本地运行和 Codex 调用方式。
2. S1：实现 AI PJM 内部执行桥 API。
3. S2：实现 `SymphonyBridgeExecutor`。
4. S3：用 Symphony 执行一个真实低风险任务并回写证据。
5. S4：接 GitLab/GitHub MR。
6. S5：接测试环境部署。
7. S6：再补 PostgreSQL、队列恢复和可观测性。

## 12. 验证清单

每一阶段都必须保留以下验证：

```powershell
cd backend
python -m pytest tests/test_auth.py tests/test_delivery_v2_units.py tests/test_delivery_v2.py tests/test_health.py -q

cd ..\frontend
npm run build
```

新增 Symphony 阶段还必须验证：

- claim 同一 run 不会重复领取。
- worker 心跳超时后 run 可恢复或失败。
- Symphony 回写日志不会泄露 token。
- allowed paths 违规仍失败。
- required checks 失败不会创建 MR。
- 人工审批缺失时高风险任务不能被 Symphony 领取。

## 13. 决策记录

- 采用 Bridge -> Native Adapter 的渐进策略。
- AI PJM 仍是业务状态源。
- Symphony 只负责执行编排，不负责业务门禁。
- 不把外部 issue tracker 作为长期状态源。
- 真实 MR 和真实部署优先于企业 SSO、复杂角色和审计报表平台化。
