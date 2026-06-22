# AI PJM 生产级落地计划

本文档用于约束 AI PJM 从本地 MVP 走向生产可用的实施路径。目标不是做企业治理平台，也不是堆功能，而是让平台真实降低 AI 辅助研发交付成本、减少人工搬运、保留关键安全控制，并能被团队长期稳定使用。Codex 编排优先参考 [symphony-integration-plan.md](symphony-integration-plan.md)，避免重复自研 worker、workspace 和 daemon 能力。

如果本文档与聊天讨论冲突，以本文档为准；如果实施优先级变化，先更新本文档，再改代码。

## 1. 生产级目标

AI PJM 的生产级目标：

- 让业务需求可以进入一条可审计、可恢复、可验证的工程交付链路。
- 让 AI 负责上下文收集、方案生成、任务拆分、受限编码、自测修复、证据整理。
- 让平台负责权限、门禁、状态流转、密钥安全、审计、队列、外部系统集成。
- 让人工只介入高风险审批、关键评审、验收判断和异常仲裁。

生产级系统必须做到：

- 操作者知道当前任务卡在哪、下一步做什么、是否需要人工介入。
- 管理者能追踪每个需求从输入到验收的完整证据链。
- 开发团队能并发处理多个低风险任务，而不互相污染代码和上下文。
- 安全风险不会因为 AI 输出、提示词遗漏、页面误点而绕过。
- 外部系统失败时，平台能明确失败、保留证据、支持重试或人工接管。

## 2. 目标用户和核心场景

### 2.1 主要用户

| 用户 | 目标 | 平台应解决的问题 |
| --- | --- | --- |
| AI 协作操作员 | 批量驱动 AI 完成低风险交付 | 少复制粘贴、少手工建分支、少手工整理证据 |
| 评审/验收人员 | 判断高风险任务和测试结果 | 看清影响范围、MR、测试环境、验收证据 |
| 开发人员 | 接管 AI 失败或高风险任务 | 获得完整上下文、失败原因和修复入口 |
| 管理员 | 管理项目、密钥和外部集成 | 安全配置凭证、执行入口和项目边界 |

### 2.2 必须优先优化的工作流

```text
业务输入
-> 自动收集项目代码、文档、历史需求和配置
-> 生成规格、影响分析和任务包
-> 门禁判断风险和执行权限
-> AI 在隔离环境编码
-> 自动自测和有限修复
-> 创建 MR/PR
-> 拉取评审意见并修复
-> 部署测试环境
-> 人工或自动验收
-> 归档完整证据
```

任何生产级改造都必须服务这条主链路。权限、密钥、审计、数据库、队列都是支撑能力，只做到让主链路安全稳定即可，不能反客为主。不能优先做炫技型能力，例如复杂组织治理、知识图谱、大规模多 Agent、自动生产发布。

## 3. 当前状态

当前已完成本地 MVP 主链路：

- 本地 SQLite 可运行。
- 本地仓库上下文收集、同项目历史需求上下文和轻量内容匹配。
- 规格、影响分析、任务包生成。
- Codex 命令行执行首版。
- Git worktree 隔离。
- 必要检查和失败证据。
- 自动修复首版。
- 本地 MR/PR 记录和评审门禁。
- 本地测试环境记录和验收门禁。
- 执行队列可见性和并发上限保护。
- Dify Provider 边界首版。
- 交付工作台首屏可用性优化。
- 认证、授权和项目权限首版：本地用户、密码登录、Bearer Token、项目、项目成员、角色权限、业务 API 权限保护。
- 权限管理页面首版：管理员可查看项目和用户，创建项目，创建本地用户，维护用户状态/全局角色，重置密码，并设置或移除项目角色。
- 前端按钮级权限首版：工作台动作、人工审批和权限管理入口按后端角色能力模型显示或拦截。
- 人工动作操作者结构化落库首版：人工审批、MR 创建/评审、测试部署、验收记录已写入业务表操作者字段，并保留审计事件。
- 审计查询增强首版：审计 API 和工作台页签支持操作者、动作、对象、时间范围、关键词筛选，并支持 CSV 导出。
- 审计事件首版：创建需求、人工审批、创建 MR、记录评审、测试部署、验收、创建项目、创建用户等动作已落库，并可在工作台审计页签查看。
- 密钥管理首版：项目级凭证已通过服务端加密存储，API 和访问管理页只返回掩码，不返回明文，并记录创建/轮换审计事件；Dify、GitLab MR 和 webhook 部署 provider 已可按项目从 SecretStore 读取凭证。

当前仍不是生产级：

- 权限仍是本地首版，但当前阶段只需要最小角色模型；企业 SSO、复杂组织角色和审计报表平台化不作为近期主线。
- 密钥和 Token 已有本地加密存储、健康检查和过期提示首版，Dify、OpenAI、GitLab MR、GitHub PR 和 webhook 部署已接入项目级消费；OpenAI/GitLab/GitHub 凭证已有只读远端探测和失败原因写回，Dify 支持通过显式 `DIFY_HEALTH_CHECK_URL` 配置安全只读探测。尚未接 Vault/KMS 和集中轮换策略。
- GitLab MR 创建、GitHub PR 创建、源分支自动推送、远端评审同步、阻塞意见自动修复、reviewer/assignee/label 配置和 GitLab/GitHub webhook 更新原 MR/PR 记录已有首版。
- webhook 测试部署 client 已有首版，失败部署重新部署入口、环境级 URL 配置、部署日志证据归档、后台同步启停脚本、常见 CI/CD 状态语义归一化、通用状态节点证据、运行标识、失败原因、日志链接和 links/_links 解析已完成；仍缺目标 CI/CD 平台专用 payload/日志解析。
- Symphony Bridge、生产 Compose worker profile、`SYMPHONY_RUNNER_COMMAND` 兼容 adapter、worker 循环异常不中断、lease 恢复、过期队列恢复脚本、失败重试幂等首版和暂停/恢复/取消控制已有首版；真实上游 Symphony daemon 联调和生产容量阈值仍待目标环境验证。
- Alembic 迁移链路首版已完成，并已通过 Docker PostgreSQL 真库升级到 head 演练；Docker Compose 生产等价最小栈已补齐 PostgreSQL、迁移、后端、前端和可选 worker profile；SQLite/PostgreSQL 最小备份恢复脚本已完成，后端只读性能烟测入口已完成。
- 没有完整审计和集中运行指标平台；Prometheus 文本指标出口、集中告警通用 webhook 转发脚本和本地告警 worker 启停脚本已有首版。
- Dify/OpenAI 本地质量评分和只读质量烟测脚本已完成；真实 Dify/OpenAI 环境生产联调仍待在目标环境执行。

## 4. 生产级架构原则

### 4.1 平台管状态，AI 管候选结果

AI 可以生成：

- 规格草稿。
- 影响分析草稿。
- 任务包草稿。
- 代码变更。
- 修复建议。
- 评审修复方案。

AI 不允许直接决定：

- 是否绕过门禁。
- 是否扩大修改范围。
- 是否写入密钥、权限、生产数据。
- 是否合并 MR。
- 是否生产发布。
- 是否删除审计证据。

### 4.2 所有外部能力必须有边界

必须通过明确接口接入：

- `WorkflowProvider`: Dify/OpenAI/本地规则。
- `ExecutionExecutor`: Codex/其他编码执行器。
- `SymphonyBridge`: Codex 编排和后台执行桥。
- `MergeRequestClient`: GitLab/GitHub。
- `DeployClient`: 测试环境部署系统。
- `SecretStore`: 密钥管理。
- `AuditSink`: 审计日志。

外部能力失败时，平台必须：

- 明确记录失败阶段。
- 保留错误信息和上下文。
- 不推进下一门禁。
- 支持重试或人工接管。

### 4.3 支撑能力不得反客为主

近期只保留四类角色：管理员、操作员、评审员、只读。更细的交付负责人、技术负责人、测试人员先作为任务职责或审批配置，不写死进权限模型。

以下能力只在真实试点规模需要时再做：

- 企业 SSO 或统一身份源。
- 批量成员维护和复杂项目授权视图。
- 审计报表平台和集中告警中心。
- 多部门、多团队组织映射。

近期要优先投入的不是组织治理，而是让主链路更少人工介入：上下文更准、任务包更准、Codex 执行更稳、MR 和测试环境更真实、失败可自动回到修复。

### 4.4 高风险强约束，低风险少干预

低风险任务应尽量自动化：

- 普通 Bug 修复。
- UI 文案、小组件、低影响前端调整。
- 测试补充。
- 文档更新。
- 明确范围内的小逻辑修复。

高风险任务必须人工强干预：

- 登录、权限、审计。
- 支付、资金、订单。
- 密钥、Token、凭证。
- 生产数据迁移或删除。
- 基础设施、CI/CD、部署权限。
- 大规模重构。
- 多仓库联动。

## 5. 生产化阶段计划

### P0：生产基线和文档口径清理

目标：让团队知道当前能力边界、上线标准和下一步优先级。

实施内容：

- 清理 README、路线图、验证指南中的过期描述。
- 明确 MVP、试点生产、正式生产三个阶段的差异。
- 增加生产配置样例，不包含真实密钥。
- 固定每阶段验收命令和人工验证清单。

验收标准：

- 文档中不再出现与当前实现冲突的状态描述。
- 新成员能通过 README 找到启动、验证、路线图和生产化计划。
- 每个未完成能力都有明确阶段和验收标准。

不做风险：

- 后续多人协作会反复误判“已完成”和“只是本地首版”。

### P1：最小权限和人工责任

目标：用最小权限模型保证试点安全，不把系统做成企业身份治理平台。

当前状态：已完成首版。已有本地账号、密码登录、Bearer Token、项目、项目成员、全局角色、项目角色、交付 API 权限保护、前端登录入口、权限管理页面、用户状态/角色维护、密码重置、项目角色维护、前端按钮级权限、人工动作操作者结构化字段、审计事件、审计查询增强、审计 CSV 导出和基础权限测试。

实施内容：

- 增加用户、角色、项目成员模型。（首版已完成）
- 近期只保留管理员、操作员、评审员、只读四类角色。（首版已完成）
- API 增加认证中间件。（首版已完成）
- 页面按权限显示动作。（登录、用户态和按钮级权限首版已完成）
- 高风险审批必须绑定真实用户。
- 任务、MR、部署、验收都记录操作者。

近期角色权限：

| 动作 | 管理员 | 操作员 | 评审员 | 只读 |
| --- | --- | --- | --- | --- |
| 配置项目和密钥 | 是 | 否 | 否 | 否 |
| 创建需求 | 是 | 是 | 是 | 否 |
| 执行低风险任务 | 是 | 是 | 否 | 否 |
| 审批高风险任务 | 是 | 否 | 是 | 否 |
| 创建 MR | 是 | 是 | 否 | 否 |
| 部署测试环境 | 是 | 是 | 是 | 否 |
| 验收 | 是 | 否 | 是 | 否 |
| 查看证据 | 是 | 是 | 是 | 是 |

验收标准：

- 未登录不能访问业务 API。
- 无权限用户看不到或不能触发受限动作。
- 所有人工动作都能追溯到用户。
- 高风险任务没有审批不能执行。

剩余工作：

- 增强危险操作二次确认，例如删除、禁用密钥、高风险执行、覆盖外部状态。（访问管理页密钥停用、用户停用、密码重置、项目角色移除已增加输入对象名称确认）
- 让审批人、验收人、接管人作为任务级责任字段，而不是新增硬编码角色。
- 企业 SSO、批量成员维护、复杂授权视图、审计报表聚合移到规模化阶段，不进入近期主线。

不做风险：

- 生产中无法追责，密钥和高风险操作容易被误用。

### P2：密钥和凭证安全

目标：让 Git、AI、部署系统凭证可安全使用。

当前状态：已完成本地首版。已有 `SecretStore` 服务端接口、项目级密钥表、Fernet 加密存储、密钥掩码响应、创建/轮换/禁用审计事件、访问管理页配置入口、轮换修复入口、停用/启用入口和基础权限测试。Dify Provider 会优先按项目读取 `dify_api_key`，OpenAI Provider 会优先按项目读取 `openai_api_key`，GitLab MR provider 会读取 `gitlab_token`，GitHub PR provider 会读取 `github_token`，webhook 部署 provider 会读取 `deploy_token`；项目未配置时分别回退到全局 `DIFY_API_KEY`、`OPENAI_API_KEY`、`GITLAB_TOKEN`、`GITHUB_TOKEN`、`DEPLOY_TOKEN`。主密钥通过 `SECRET_STORE_MASTER_KEY` 注入，未配置时禁止写入密钥。执行日志、执行证据和自测门禁证据已在持久化前进行敏感信息脱敏，已覆盖常见 OpenAI、GitHub、GitLab、Slack、Google、Stripe、Dify 风格 Token、Bearer、URL 参数、URL 内嵌密码、JWT、AWS Access Key、平台内部 token 和 PEM 私钥块。密钥列表和健康检查接口已支持过期时间、健康状态、可解密性检查、OpenAI/GitLab/GitHub 只读远端探测、最近失败原因写回、最近使用时间展示、健康状态分布和脱敏失败原因聚合。可观测性 summary 已扫描最近执行日志和证据，发现疑似未脱敏凭证时输出 `sensitive-evidence-leak` 告警；Prometheus 指标已输出凭证 invalid/expired/disabled/unknown/expiring 分布和敏感证据扫描结果。

实施内容：

- 增加 `SecretStore` 接口。（首版已完成）
- 本地开发支持 `.env`，生产必须接 Vault、云密钥服务或数据库加密存储。（本地加密存储首版已完成）
- 密钥只在服务端使用，不进入前端。（首版已完成）
- 日志和证据链做脱敏。（API 响应、运行日志、执行证据和常见 Provider 凭证格式首版已完成）
- Token 配置支持项目级隔离。（Dify/OpenAI/GitLab/GitHub/webhook 部署消费首版已完成）
- 增加凭证健康检查和过期提示。（首版已完成）

验收标准：

- 前端和 API 响应不会返回明文密钥。（首版已验证）
- 日志中不会出现 Token。（已增加 Provider token、URL 凭证和 PEM 私钥块回归用例）
- GitLab/Dify/OpenAI/部署凭证可按项目配置并由 provider 服务端消费。
- 凭证失效时页面显示明确错误和修复入口。（健康状态展示、访问管理页轮换入口和停用/启用入口首版已完成）
- 日志和证据疑似残留明文凭证时能进入可观测性告警。（最近执行扫描首版已完成）

剩余工作：

- 接入 Vault/KMS 或生产级密钥后端，支持主密钥轮换。
- 增加更多 Provider 的安全远端可用性探测；OpenAI/GitLab/GitHub 只读远端探测已完成，Dify 显式安全 URL 探测已完成。
- 扩展密钥健康检查：增加更多 Provider 远端探测和生产告警处理闭环；最近失败原因聚合、健康状态分布和过期告警联动首版已完成。
- 增强日志/证据敏感信息扫描：增加历史全量扫描、集中日志平台规则、告警去重和处理闭环。
- 增加密钥删除策略、审批门禁和集中轮换策略。

不做风险：

- 密钥泄露会直接阻断生产使用。

### P3：生产数据库和迁移体系

目标：替换 SQLite，保证可升级、可备份、可恢复。

当前状态：迁移链路首版已完成。开发环境继续使用 SQLite、`create_all` 和少量幂等补列兼容已有本地库；生产路径提供 `backend/scripts/migrate.py` 执行 Alembic `upgrade head/current`，当前迁移可从空库升级到 head，并由 `tests/test_migrations.py` 覆盖 SQLite 干净库验证。非 SQLite 启动会在 `DATABASE_VALIDATE_MIGRATIONS=true` 时校验数据库是否到达 Alembic head。2026-06-04 已用 Docker PostgreSQL 16 真库验证 `upgrade head` 到 `012`，并确认交付主链路表已具备 `trace_id` 字段。根目录已提供 `docker-compose.production.yml` 和 `docker-compose.production.env.example`，可启动 PostgreSQL、迁移任务、后端、前端反向代理，并通过 `workers` profile 按需启动部署同步、告警和 Symphony worker。`scripts/database_backup.py` 和 `scripts/database_restore.py` 已提供 SQLite/PostgreSQL 最小备份恢复入口。`scripts/seed_delivery_capacity.py` 可安全生成容量基准所需的合成交付数据，`scripts/performance_smoke.py` 已提供后端只读性能烟测入口，根目录 `scripts/check-capacity-smoke.ps1` 已把 seed、性能烟测和 `.runtime/capacity` 证据留存串成统一入口；1 万条任务规模的正式容量基准仍需在目标生产环境执行并固化阈值。

实施内容：

- 引入 PostgreSQL。（Docker 真库迁移演练已完成，生产连接池和运维参数待按目标环境调优）
- 引入 Alembic 数据库迁移。（首版已完成）
- 为当前所有模型生成初始 migration。（首版已完成）
- 增加索引：项目、需求、状态、任务、执行记录、门禁、创建时间。（随当前迁移首版完成）
- 增加数据保留策略。
- 增加备份和恢复流程。（SQLite/PostgreSQL 最小脚本已完成，定期调度和异地归档待接入）

验收标准：

- 新环境可一键执行 migration 初始化。（SQLite 干净库验证、Docker PostgreSQL 真库验证和 Compose 迁移服务配置已覆盖）
- 旧版本升级不会丢数据。
- 测试覆盖 SQLite 和 PostgreSQL 至少一种生产等价路径。（SQLite 迁移链路、Docker PostgreSQL 真库升级演练和 Compose 配置解析已覆盖）
- 关键列表接口在 1 万条任务下仍可接受。（容量数据准备脚本、只读性能烟测和统一容量验证脚本已完成，正式容量基准待在目标生产环境执行）

不做风险：

- 生产数据不可演进，升级时容易手工改库。

### P4：Symphony Bridge 和可靠执行队列

目标：复用 OpenAI Symphony 的 Codex 编排模式，让长任务脱离页面请求，支持稳定批量执行。

当前状态：已完成首版 internal bridge API、最小命令行 worker、`SymphonyBridgeExecutor`、lease 过期失败恢复、暂停/恢复/取消控制、同一任务活跃 run 幂等保护、手动重试 `retry_context.retry_chain` 证据，以及本地常驻 worker 启停脚本和 status 文件。生产 Compose 已提供 `symphony-worker` profile，并通过 `SYMPHONY_RUNNER_COMMAND` 支持把底层执行替换为真实 Symphony/Codex 命令。`executor_type=symphony` 的执行记录可以保持 queued，等待 worker claim；worker complete 后由 AI PJM 校验 required checks、allowed paths 和必要变更证据，再决定最终门禁。运行中 worker 如果超过 lease 未 heartbeat，会被标记 failed 并保留恢复证据，避免永久卡在 running；`scripts/recover_symphony_runs.py` 可手动或定时恢复过期 running run，并输出状态文件。操作者可以暂停 queued run、恢复 paused run、取消 queued/paused/running run；取消后的 worker late complete 会被拒绝。真实上游 Symphony daemon 接入只需要按该 bridge contract 消费任务和回写结果，剩余工作是目标环境联调与容量阈值固化。

实施内容：

- 按 [symphony-integration-plan.md](symphony-integration-plan.md) 完成 S0-S3。（S0-S2 已完成，S3 已有最小 worker、lease 过期失败恢复和本地常驻启停脚本）
- 增加 AI PJM internal execution bridge API：claim、heartbeat、event、complete。（已完成首版）
- 增加 `SymphonyBridgeExecutor`，支持 `executor_type = symphony`。（已完成首版）
- 引入 Symphony daemon 或兼容 adapter。（兼容 adapter 和生产 Compose worker profile 已完成；真实上游 daemon 待目标环境联调）
- 执行任务入队，不在 HTTP 请求里长时间运行。（symphony executor 首版已完成）
- 支持排队、运行、成功、失败、取消、暂停、恢复、超时。（取消/暂停/恢复和 lease 过期失败恢复首版已完成）
- 支持最大并发、项目级并发、任务级超时。
- 支持失败重试和幂等锁。（同一任务活跃 run 幂等保护、手动重试 retry chain 和重复重试复用 active run 首版已完成）
- worker 异常退出后能恢复 running 状态。（lease 过期标记 failed 首版已完成）

建议技术方案：

- 短期方案：AI PJM internal API + Symphony Bridge Executor。
- 中期方案：Symphony Native Adapter 直接消费 AI PJM `ExecutionRun`。
- 备用方案：仅借鉴 Symphony app-server 调用方式，自研最小 worker。

验收标准：

- 页面关闭后任务仍继续执行。
- 同一任务不会被多个 worker 重复执行。
- worker 重启后可恢复或标记异常任务。
- 队列积压、失败、超时有明确状态。
- Symphony 回写事件和执行证据不会绕过 AI PJM 门禁。

不做风险：

- 生产任务会被 HTTP 超时、页面刷新、进程重启打断。

### P5：执行隔离和安全沙箱

目标：控制 AI 编码执行的影响范围。

实施内容：

- Codex 执行进入受控 runner。
- 每个任务独立 worktree、分支、日志目录。
- 限制允许修改路径。
- 限制危险命令。
- 限制网络访问策略。
- 限制运行时长、输出大小、文件数量。
- 自动清理失败 worktree。
- 保留必要证据，不保留敏感数据。

验收标准：

- 越权文件变更必定失败。
- 危险命令不会执行或会被拦截。
- runner 超时后任务可恢复或标记失败。
- 任务残留可自动清理。

不做风险：

- AI 执行会污染仓库、泄露敏感信息或破坏环境。

### P6：真实 GitLab/GitHub MR 集成

目标：让自测通过的代码进入真实代码评审系统。

当前状态：GitLab `MergeRequestClient` 首版已实现，可用项目级 `gitlab_token` 或全局 `GITLAB_TOKEN` 调用 GitLab API 创建 MR，并把远端 URL、iid、源分支、目标分支和凭据来源写入证据。GitHub `PullRequestClient` 首版已实现，可用项目级 `github_token` 或全局 `GITHUB_TOKEN` 调用 GitHub API 创建 PR，并同步 PR review、review comment、issue comment、check run 和 combined status。创建 MR/PR 前可自动 `git push` 执行分支到配置的远端，push 失败会阻断创建并保留脱敏错误。可通过 `GITLAB_DEFAULT_LABELS`、`GITLAB_REVIEWER_IDS`、`GITLAB_ASSIGNEE_IDS` 配置 GitLab 默认标签、reviewer 和 assignee；可通过 `GITHUB_DEFAULT_LABELS`、`GITHUB_REVIEWERS`、`GITHUB_ASSIGNEES` 配置 GitHub 默认标签、reviewer 和 assignee，并写入证据。远端评审同步首版已实现，可通过 `POST /api/v2/merge-requests/{id}/sync-review` 拉取远端评审和 CI/check 状态，写回 MR/PR 状态、`review_passed` 门禁、审计事件和脱敏证据；交付工作台已提供远端 MR/PR 的“同步评审”入口，本地 MR 仍保留人工评审通过入口。`POST /api/v2/gitlab/webhook` 已支持用 `GITLAB_WEBHOOK_SECRET_TOKEN` 校验 GitLab MR、pipeline 和 note 事件，按 MR iid 更新已有 MR 记录、门禁、审计和 webhook 证据；`POST /api/v2/github/webhook` 已支持用 `GITHUB_WEBHOOK_SECRET` 校验 GitHub `X-Hub-Signature-256`，按 PR number 更新已有 PR 记录、门禁、审计和 webhook 证据，减少人工轮询。评审阻塞自动修复串联首版已实现，可通过 `POST /api/v2/merge-requests/{id}/auto-repair` 把远端阻塞项写入 `repair_context.review_issues` 并触发受控修复 run；修复成功后会把修复分支推回原 GitLab/GitHub 源分支，并把 MR/PR 状态重置为待同步远端评审。

实施内容：

- 增加 GitLab/GitHub `MergeRequestClient`。（GitLab MR 和 GitHub PR 首版已完成）
- 创建真实 MR/PR。（GitLab 首版已完成，源分支自动 push 首版已完成）
- 设置标题、描述、源分支、目标分支、标签、reviewer。（首版已支持默认 label/reviewer/assignee 配置）
- MR 描述自动包含需求、风险、变更范围、检查结果、证据链接。（需求、风险、分支、commit、检查结果、变更文件和 AI PJM 深链证据链接首版已完成）
- 同步 CI 状态。（GitLab 手动同步接口首版已完成）
- 拉取评论和阻塞意见。（GitLab 手动同步接口首版已完成）
- 阻塞意见进入自动修复或人工处理。（状态、门禁回写、自动修复串联和修复后推回原 MR 首版已完成）
- 支持 webhook，减少轮询。（GitLab webhook 更新已有 MR 记录、GitHub webhook 更新已有 PR 记录首版已完成）

验收标准：

- 自测通过后可创建真实 MR。
- 页面展示真实 MR 链接和远端状态。
- 远端阻塞评论能进入平台证据链。（GitLab 手动同步接口首版已完成）
- 修复后能重新推送并更新 MR。（首版已完成）
- 没有 Token 或权限不足时明确失败。

不做风险：

- 仍然需要人工复制代码、手工建 MR，效率提升有限。

### P7：真实测试环境部署 Provider

目标：让 MR 后的结果进入可验证环境。

当前状态：`DeployClient` 边界和 `webhook` 部署 provider 首版已实现，可用项目级 `deploy_token` 或全局 `DEPLOY_TOKEN` 调用外部 webhook，并把部署 URL、状态、commit 和凭据来源写入 `DeployRecord` 证据。webhook 返回 `status_url` 时，可通过 `POST /api/v2/deployments/{id}/sync-status` 手动同步部署状态，也可通过 `POST /api/v2/deployments/sync-pending` 批量同步 pending 部署；`scripts/deployment_sync_worker.py --loop` 可后台定时调用服务层同步 pending 部署，项目根目录的 `scripts/start-deployment-sync-worker.ps1` 和 `scripts/stop-deployment-sync-worker.ps1` 已提供本地启停入口，`scripts/start-dev.ps1 -WithDeploymentSync` 可随开发环境联动启动。同步会写回 `test_deployed` 门禁、审计事件和脱敏证据。失败状态会写入失败门禁，不会推进验收；失败部署可通过 `POST /api/v2/deployments/{id}/redeploy` 创建新部署记录并保留来源证据。`GET/PUT /api/v2/projects/{project_id}/deployment-environments` 已支持项目级测试环境 URL、日志 URL 和说明配置，访问管理页已提供最小项目测试环境配置入口；创建部署时优先使用项目配置，缺省再回退到 `DEPLOY_ENVIRONMENT_CONFIG_JSON`。provider 返回的 `log_url/logs` 会脱敏归档到部署证据。webhook provider 已能识别常见 CI/CD 状态字段、ArgoCD sync/health、嵌套 pipeline/job/stage/step/check/task 状态和状态词，并把原始状态、归一化状态、状态路径、失败/等待节点、运行标识、失败原因、日志链接和 links/_links 解析结果写入证据。目标 CI/CD 平台专用 payload/日志解析和更完整日志归档策略仍待在真实环境增强。

实施内容：

- 增加 `DeployClient` 接口。（已完成首版）
- 对接现有 CI/CD、测试环境平台或脚本入口。（webhook 首版已完成）
- 支持按项目配置部署环境。（项目级配置 API、访问管理页最小入口和全局环境 JSON 兜底已完成）
- 记录部署 URL、版本、commit、日志、状态。（部署 URL、状态、commit、日志 URL、日志尾部、运行标识、失败原因和通用 CI/CD 状态节点证据首版已完成）
- webhook `status_url` 同步部署状态。（单条同步、pending 批量同步入口、后台轮询脚本和项目根目录启停脚本首版已完成）
- 部署失败保留日志并阻断验收。
- 支持重新部署。（失败部署重新部署首版已完成）

验收标准：

- 评审通过后可触发真实测试环境部署。
- 页面展示真实测试地址。
- 部署状态能自动回写。（单条同步、pending 批量同步入口、后台轮询脚本和项目根目录启停脚本首版已完成）
- 部署失败不会推进验收门禁。

不做风险：

- 交付链路停留在代码层，无法真正闭环到业务验收。

### P8：验收和证据归档

目标：让每个需求都有可追溯的验收结论。

实施内容：

- 验收标准与 Spec 绑定。
- 测试人员可记录通过、失败、备注、截图、链接。
- 验收失败可回到自动修复或人工处理。
- 验收通过后归档证据。
- 生成交付摘要。

验收标准：

- 每个完成需求都有完整证据链。
- 失败验收不会被标记为完成。
- 归档内容包含：需求、规格、任务包、执行、检查、MR、部署、验收。

不做风险：

- 管理者无法判断 AI 交付是否真的可用。

### P9：质量门禁和工程治理

目标：让质量保障从个人习惯变成平台机制。

实施内容：

- 支持项目级必跑检查：单测、构建、lint、类型检查、覆盖率。
- 支持代码扫描和依赖漏洞扫描。
- 支持文件大小、方法长度、复杂度、禁止路径规则。
- 支持门禁规则配置版本化。
- MR 合并前检查证据齐全。

验收标准：

- 必跑检查失败不能创建或通过 MR。
- 规则变更有审计记录。
- 高风险任务必须有人工审批记录。

不做风险：

- AI 会放大低质量变更的交付速度。

### P10：可选 Dify/OpenAI 质量增强

目标：在固定研发流程之外需要质量对照或特殊分析增强时，让外部 AI Provider 提供结构化草稿；默认试点生产不依赖 Dify/OpenAI。

当前状态：Dify/OpenAI Provider 首版已完成，默认不启用。Dify 使用配置的 workflow 生成 Spec/Impact 结构化草稿；OpenAI 使用 Responses API 的 JSON Schema 结构化输出生成 Spec/Impact 草稿。两者都只返回草稿，不直接改数据库状态、不执行代码、不绕过门禁。已具备必填字段、列表字段、风险等级和置信度校验；超时、平台级重试和本地规则降级首版已完成。降级会记录失败 provider、尝试次数和脱敏错误，并在 Spec open questions、门禁 evidence 或 Impact metadata 中可追溯。固定研发流程下，主路径优先使用本地规则 Provider、任务包和门禁；远端 Dify/OpenAI 生产联调只作为可选质量增强，不作为试点生产硬门槛。

实施内容：

- 固化 Dify Spec workflow schema。（首版已完成）
- 固化 Dify Impact workflow schema。（首版已完成）
- 增加 OpenAI Provider。（首版已完成）
- 增加 Provider 输出校验。（首版已完成）
- 增加超时、重试、降级策略。（首版已完成）
- 记录 workflow/model/prompt 版本。（workflow/model、schema name、schema version、prompt version 首版已完成）
- 评估 Provider 输出质量。（本地确定性质量评分、只读质量烟测脚本、批量 provider 报告和 JSON 留痕已完成，远端生产联调待在目标环境执行）

验收标准：

- Provider 输出不合规时不会推进流程。（首版已完成）
- 同一需求可追溯使用了哪个 workflow/model、schema 和 prompt 版本。（首版已完成）
- 同一需求可追溯 Provider 输出质量评分、是否达标和扣分项。（首版已完成）
- Dify/OpenAI 不直接修改数据库状态。（已按 Provider 合同约束）
- Provider 失败可降级到本地规则或进入人工处理。（本地规则降级首版已完成，人工处理策略待产品化）

不做风险：

- 如果把 Dify/OpenAI 放入主路径，容易引入额外凭证、workflow 漂移和外部平台可用性风险，反而降低试点落地速度。

### P11：可观测性和运维

目标：让生产问题可发现、可定位、可恢复。

当前状态：最小可观测性首版已完成。后端提供 `GET /api/v2/observability/summary`，按项目权限汇总 worker lease 过期、执行队列积压、凭证过期/禁用/未知/即将过期、测试部署失败、近期执行失败率异常和最近执行证据疑似明文凭证告警；`GET /api/v2/observability/projects` 已提供项目维度健康摘要，返回项目状态、告警数、关键指标和前三条告警；`GET /api/v2/observability/metrics` 已提供 Prometheus 0.0.4 文本指标出口，复用 summary 统计口径输出队列、worker、部署、凭证状态分布、近期失败率、敏感证据扫描和告警计数。`ops/prometheus/prometheus.example.yml` 和 `ops/prometheus/ai-pjm-alerts.yml` 已提供最小 scrape 与告警规则样例。`scripts/observability_alert_worker.py` 可轮询 summary API，并在 warning/critical 时转发到外部 webhook，项目根目录的 `scripts/start-observability-alert-worker.ps1` 和 `scripts/stop-observability-alert-worker.ps1` 已提供本地启停入口，`scripts/start-dev.ps1 -WithObservabilityAlert` 可随开发环境联动启动。交付工作台顶部展示运行告警、核心计数、前两条告警摘要、系统配置健康和当前项目接入状态。需求、Spec、门禁、上下文、影响分析、任务、执行、日志、MR、部署和验收已具备同一 `trace_id` 首版贯穿能力；`scripts/backfill_delivery_trace_ids.py` 可 dry-run 或正式回填历史记录。后端 `LOG_FORMAT=json` 已提供 JSON Lines 结构化应用日志开关，可输出 timestamp、level、logger、message、位置和 extra 字段。集中指标平台接入仍待生产环境完成。

实施内容：

- 结构化日志。（`LOG_FORMAT=json` JSON Lines 首版已完成，集中日志平台接入待完成）
- trace id 贯穿需求、任务、执行、MR、部署、验收。（新记录首版、历史记录回填脚本、`GET /api/v2/observability/traces/{trace_id}` 只读时间线查询和工作台证据页签展示已完成）
- 指标：任务数量、成功率、失败率、平均耗时、队列积压、自动修复率。（队列、部署、凭证状态分布、worker、近期执行失败率、敏感证据扫描和 Prometheus 文本出口首版已完成）
- 告警：worker 停止、队列积压、凭证失效、凭证健康未知、部署失败、异常失败率、疑似敏感证据泄漏。（worker lease、队列积压、凭证、部署失败、近期执行失败率、敏感证据扫描和本地告警 worker 启停脚本首版已完成）
- 管理后台查看系统健康。（工作台告警条、配置健康/项目接入可见化、项目健康摘要 API、Prometheus 文本指标出口和通用 webhook 转发脚本首版已完成，完整管理后台页面待增强）

验收标准：

- 任一失败任务可通过 trace id 找到完整日志。（平台内 trace 时间线查询和工作台证据页签已覆盖需求、Spec、门禁、上下文、影响分析、任务、执行日志、MR/PR、部署和验收；集中日志平台接入待增强）
- 队列积压和 worker 异常能告警。（summary API、工作台摘要和本地告警 worker 启停脚本首版已完成）
- 管理员能看到各项目健康状态。（项目健康摘要 API、工作台告警和就绪状态首版、Prometheus 文本指标出口和通用 webhook 告警转发已完成，完整管理后台页面待增强）

不做风险：

- 生产故障只能靠人工翻日志，无法规模化运维。

### P12：产品化交互

目标：让平台真正提高操作效率。

实施内容：

- 项目接入向导。（`GET /api/v2/projects/{project_id}/onboarding` 和工作台就绪展示首版已完成）
- 配置健康检查。（`GET /api/v2/observability/config-health` 和工作台就绪展示首版已完成）
- 当前任务下一步动作明确化。（`DemandDetailResponse.next_actions` 首版已完成）
- 证据时间线。（`GET /api/v2/observability/traces/{trace_id}` 和工作台证据页签首版已完成）
- 多项目看板。（`GET /api/v2/observability/projects` 和工作台“项目”页签首版已完成）
- 批量任务看板。（工作台“批量”页签已展示最近 100 条需求、关键计数和详情入口）
- 高风险任务审批台。（工作台“审批”页签已聚合 L2/L3 且未审批/未拒绝的需求，并提供查看审批入口）
- 失败任务处理台。（工作台“失败”页签已按 failed/blocked/cancelled 聚合并提供查看处理入口）

验收标准：

- 新项目接入不需要读代码。（项目 onboarding checklist API 和工作台摘要首版已完成）
- 操作者打开页面能看到下一步最应该做什么。（后端 detail 已返回结构化 next actions，工作台下一步卡片已优先展示后端建议）
- 管理者能看到交付吞吐、失败原因和瓶颈。（项目健康摘要 API、Prometheus 指标和工作台“项目”页签首版已完成，生产集中看板待目标环境接入）

不做风险：

- 功能存在但不好用，实际效率提升有限。

## 6. 阶段性交付顺序

### 阶段 A：试点生产基础

优先级最高。完成后可在小团队、低风险任务中试点。

1. P0 文档口径清理。
2. P4 Symphony Bridge：复用 Symphony 编排 Codex 执行，长任务脱离 HTTP 请求。
3. P2 密钥安全：Provider 按项目读取凭证，密钥不外泄。
4. P6 真实 GitLab/GitHub MR：自测通过后自动创建真实 MR。
5. P7 真实测试环境部署：MR 后能进入可验证环境。
6. P3 PostgreSQL 和迁移：支撑试点数据可升级、可恢复。

阶段 A 验收：

- 最小角色模型可支撑多人试点。
- 密钥不泄露。
- 任务可通过 Symphony Bridge 后台执行。
- 低风险任务可自动创建真实 MR。
- 所有人工动作可审计。
- `scripts/check-target-pilot.ps1` 在目标环境无 blocker，或 blocker 已明确记录为外部环境待配置项并有责任人。

### 阶段 B：完整测试闭环

完成后可以支撑真实需求从输入到测试验收。

1. P8 验收和证据归档。
2. P9 质量门禁。
3. P11 可观测性基础。
4. P1 增强项：危险操作二次确认和任务级责任字段。

阶段 B 验收：

- MR 通过后能部署测试环境。
- 验收结论进入证据链。
- 失败能回到修复或人工处理。
- 管理者能看到任务健康状态。

### 阶段 C：规模化效率提升

完成后可以扩大到多项目、多任务。

1. P12 产品化交互。
2. 队列取消、暂停、恢复。
3. 多项目看板。
4. 批量任务调度。
5. 可选 Dify/OpenAI 质量增强。
6. 企业 SSO、复杂角色、审计报表聚合。

阶段 C 验收：

- 多项目接入成本低。
- 低风险任务批量处理稳定。
- AI 生成方案质量可评估。
- 操作者日常操作明显减少。

## 7. 生产上线硬性门槛

未满足以下条件，不应进入真实生产：

- 有登录和项目权限。
- 密钥不在前端、不在普通日志、不在证据明文中。
- 真实 MR/PR 集成可用。
- 可触发真实测试环境或记录可验收的外部测试地址。
- Symphony Bridge / worker 可恢复。
- 使用 migration 管理数据库结构。
- 高风险任务有人工审批门禁。
- 必要检查失败不能推进。
- 每个完成任务有完整证据链。
- 关键操作有审计记录。
- 有基本监控和告警。（工作台最小告警、Prometheus 指标出口和 Prometheus 告警规则样例已完成，目标平台接入待验证）
- 目标环境试点门禁脚本 `scripts/check-target-pilot.ps1` 输出 `status=ready`；若为 `blocked`，只处理 `blockers`，非阻塞 follow-up 不拖慢试点。

## 8. 生产验收清单

上线前必须逐项验证：

| 类别 | 验收项 |
| --- | --- |
| 权限 | 未授权用户不能访问项目和任务 |
| 权限 | 操作按钮按角色显示和拦截 |
| 密钥 | 前端、日志、证据无明文 Token |
| 执行 | 越权文件变更被阻断 |
| 执行 | 超时任务被标记失败并保留证据 |
| MR | 可创建真实 MR/PR |
| MR | 阻塞评论可同步回平台 |
| 部署 | 可触发真实测试环境部署 |
| 队列 | Symphony Bridge / worker 重启后任务状态可恢复 |
| 数据库 | migration 可从空库创建完整结构 |
| 验收 | 验收失败不会进入完成状态 |
| 审计 | 人工审批、部署、验收都有操作者 |
| 观测 | 队列积压、凭证失效、worker 异常可告警 |

## 9. 效率指标

生产化不是只看功能完成，还要看效率提升。建议跟踪：

- 需求到任务包平均耗时。
- 任务包到 MR 平均耗时。
- MR 到测试环境平均耗时。
- 低风险任务自动完成比例。
- 自动修复成功率。
- 人工审批数量和原因。
- 失败任务 Top 原因。
- 每周完成 MR 数。
- 每个操作者平均处理任务数。

目标参考：

- 低风险任务从录入到 MR 小于 30 分钟。
- 自动上下文收集和任务包生成小于 3 分钟。
- 低风险任务人工介入次数不超过 1 次。
- 所有完成任务 100% 有证据链。

## 10. 近期建议执行清单

下一步建议按以下顺序实施：

1. 校准文档口径，明确项目不是企业治理平台。
2. 按 `docs/symphony-integration-plan.md` 做 S0：拉通 Symphony 本地运行和 Codex 调用方式。
3. 做 S1/S2：实现 AI PJM internal execution bridge API 和 `SymphonyBridgeExecutor`。
4. 完善 SecretStore Provider 消费：Dify/OpenAI/GitLab/GitHub/webhook 部署已完成首版项目级读取；OpenAI/GitLab/GitHub 凭证远端探测和失败原因写回首版已完成，Dify 显式安全 URL 探测首版已完成。
5. 做 S3/S4：用 Symphony 执行低风险任务，并增强真实 GitLab/GitHub MR。
6. 做 S5：增强真实测试环境部署 Provider，补目标 CI/CD 平台深度状态轮询；重新部署、项目级环境配置 API、访问管理页最小入口、环境 JSON 兜底、日志证据和常见 CI/CD 状态语义归一化首版已完成。
7. 做 S6：补目标生产容量基准和集中指标平台接入；备份恢复、过期队列恢复、历史 trace 回填、Alembic、Docker PostgreSQL 真库演练、trace id、容量数据准备脚本、只读性能烟测、统一容量验证脚本、异常失败率、Prometheus 文本指标出口、Prometheus 告警规则样例、通用 webhook 告警转发和最小可观测性首版已完成。
8. 按 [目标环境验证清单](target-environment-validation.md) 执行真实试点联调，重点覆盖 Symphony、Dify/OpenAI、MR/PR、部署、容量和集中监控。

目标环境联调通过后，AI PJM 才具备小团队低风险任务试点价值。企业 SSO、复杂角色、审计报表平台化不作为试点前置条件。
