# AI PJM v2 后续执行路线图

本文档是 V2 主链路功能演进的执行准绳。若聊天讨论与本文档冲突，以本文档为准；若需要调整顺序，先更新本文档，再改代码。

生产级落地、上线门槛、必要安全护栏、运维和团队试点计划以 `docs/production-readiness-plan.md` 为准。本文只跟踪交付链路功能状态，避免把 MVP 功能进度和生产化要求混在一起。

## 1. 当前已完成基线

已完成：

- V2 主链路框架：需求接收 -> Spec -> 仓库上下文 -> 影响分析 -> 编码任务包 -> 执行记录。
- SQLite 本地化运行。
- 低风险自动审批、高风险人工审批。
- Git worktree 隔离执行。
- 必要检查执行、失败证据记录、重试入口。
- 可配置 Codex command hook。
- 初版真实本地上下文收集 Provider。
- 低风险自动修复闭环首版。
- 本地 MR/PR 记录、评审门禁、测试环境记录和验收记录。
- 执行队列可见性、基础并发上限保护和本地后台 worker 启停脚本。
- Dify/OpenAI Provider、GitLab MR provider、webhook 部署 provider 边界首版，相关凭证可按项目从 SecretStore 读取。
- 本地认证、Bearer Token、项目成员、用户维护和交付 API 权限保护首版。
- 前端按钮级权限首版，工作台动作和权限管理入口按角色显示或拦截。
- 人工审批、MR 创建/评审、测试部署、验收的操作者已写入业务表结构化字段。
- 审计查询增强首版，支持多条件筛选和 CSV 导出。
- 本地 SecretStore 首版：项目级密钥服务端加密存储、掩码展示、创建/轮换/禁用审计、访问管理页轮换修复入口和停用/启用入口。
- 密钥健康检查首版：过期时间、健康状态、可解密性检查、OpenAI/GitLab/GitHub 只读远端探测和最近使用时间展示。
- 中文化交付工作台页面。
- 前后端启动/关闭脚本。
- 后端结构化日志开关：`LOG_FORMAT=json` 输出 JSON Lines 应用日志。

当前是“本地 MVP 闭环”，不是完整生产级系统。近期生产化缺口集中在主链路：真实上游 Symphony daemon 目标环境联调、目标 CI/CD 平台专用 payload/日志解析、生产数据库容量基准和 Provider 生产联调/质量评估。企业 SSO、复杂业务角色和审计报表平台化不是近期主线。

## 2. 总体目标

目标是形成一条尽量少人工干预、但关键风险点强约束的交付链路：

```text
业务输入
-> 自动收集代码/文档/历史需求上下文
-> AI 生成需求规格、影响分析、实现方案
-> 平台门禁判定
-> Codex 在隔离 worktree 中执行编码
-> 自测和自动修复循环
-> 创建 MR/PR
-> 拉取评审意见并修复
-> 发布测试环境
-> 人工或自动验收
-> 归档证据
```

## 3. 执行原则

- 先打通主链路，再扩展高级能力。
- 平台负责状态、门禁、审计、权限和证据；AI 只负责生成候选内容和执行受限任务。
- 所有外部能力都必须挂在明确边界后面：Provider、Executor、MR Client、Deploy Client。
- 每个阶段完成后必须有测试、页面验证和证据记录。
- 不为了追求“全自动”绕过安全门禁。
- 不把权限、审计、组织治理做成主产品；它们只作为 AI 交付链路的必要护栏。
- Codex 编排优先参考 `docs/symphony-integration-plan.md`，避免重复自研 worker、workspace 和 daemon。
- 不先做复杂多 Agent、知识图谱、多仓库编排，除非主闭环已经稳定。

## 4. 阶段计划

### P0：基线整理与可协作化

目标：让后续多人协作不被临时改动、旧流程、脏状态误导。

任务：

- 整理当前未提交改动，按功能拆成可审查提交。
- 补充 README 中的启动、关闭、验证说明。
- 明确当前能力边界：本地 MVP 已打通；Codex、Dify、MR/PR、测试部署和验收均为首版或本地 Provider，生产级真实集成另见 `docs/production-readiness-plan.md`。
- 确认 `.runtime`、worktree、日志、截图等运行时产物不进入版本控制。

完成标准：

- `git status` 中只保留预期源码改动。
- `npm run build` 通过。
- 后端 delivery v2 测试通过。
- `git worktree list --porcelain` 只剩主工作区。

### P1：真实本地上下文收集

目标：先不用 Dify，先把“项目代码、文档、历史需求、测试命令”在本地收集准。

状态：初版已实现。当前 `local` provider 会扫描仓库结构、文档、前后端配置、测试目录、依赖引用和需求相关候选文件；创建需求时会检索同项目近期需求，把 Top 相似历史需求写入 `context_payload.historical_demands`，Dify/OpenAI/Local Provider 都能沿用这份上下文。`local` provider 已基于需求文本和历史需求摘要做路径 + 文件内容的轻量 token 匹配；如需更强召回，后续再接入 embedding/向量检索。

任务：

- 实现本地 `RepoContextProvider`。
- 扫描仓库结构、关键配置、README、docs、测试目录、package 脚本。
- 读取最近 Git 变更摘要和当前分支信息。
- 识别候选影响文件和候选检查命令。
- 将上下文输出为结构化 `RepoContext`，并记录来源引用。

完成标准：

- 新需求进入后，Repo Context 不再是纯 mock 文案。
- 页面能看到真实发现文件、测试命令、仓库摘要。
- Provider 输出有置信度和 source refs。
- 有单元测试覆盖空仓库、前端项目、后端项目、混合项目。

### P2：真实影响分析与任务包生成

目标：让 AI 或规则基于真实上下文生成更可信的影响分析和任务包。

状态：首版已实现。影响分析会基于本地上下文筛选候选受影响文件，任务包在未手工填写时会自动推断 allowed paths 和 required checks；参考文件不会直接扩大任务执行范围。

任务：

- 将 `ImpactAnalysis` 输入改为真实需求 + 本地上下文。
- 先实现本地规则增强版，后接 AI Provider。
- 生成受影响区域、建议路径、风险原因、必要检查。
- 让 `CodingTask` 明确 allowed paths、forbidden actions、required checks、expected evidence。

完成标准：

- 任务包不再固定落到 `frontend/src/app/components`。
- 不同需求能产生不同影响区域和检查命令。
- L2/L3 风险原因可解释。
- 页面可以清楚展示“为什么这样拆任务”。

### P3：真实 Codex 执行接入

目标：Codex 不再只是配置占位，而是真正执行编码任务。

状态：首版已打通。WindowsApps 下的 `codex.exe` 仍会返回 `Access is denied`，但已通过全局 npm 版 `@openai/codex` 解决命令行入口问题。平台已实现 prompt、worktree、branch、run id、task id 传递、`EXECUTION_CODEX_PREFLIGHT_COMMAND` 预检、Codex 命令执行证据记录、changed files 与 allowed paths 硬校验；已覆盖成功执行、预检失败、命令失败、超时、越权改文件测试。2026-05-26 已用真实 `codex exec` 在隔离 worktree 中生成探针文件，并通过 `python -m compileall app`。

任务：

- 解决本机 `codex.exe Access is denied` 问题，确认可执行入口。首选全局 npm 版 `@openai/codex`。
- 使用 `EXECUTION_CODEX_PREFLIGHT_COMMAND` 在真实执行前确认 Codex 入口可运行。
- 固化 `EXECUTION_CODEX_COMMAND_TEMPLATE` 推荐模板。
- 将 prompt 文件、workspace、branch、run id、task id 传给 Codex。
- 执行后校验变更文件是否在 allowed paths 内。
- 捕获 Codex stdout/stderr、退出码、变更文件、残余风险。

完成标准：

- `Codex 调用` 页面显示真实执行状态，而不是“未启用”。
- Codex 能在隔离 worktree 中产生代码变更。
- 违反 allowed paths 时执行失败并记录证据。
- 测试覆盖：成功执行、预检失败、命令失败、超时、越权改文件。

### P4：自测与自动修复闭环

目标：形成“执行 -> 检查失败 -> 修复 -> 再检查”的有限自动闭环。

状态：首版已实现。低风险任务在检查失败后可调用自动修复接口，平台会把失败检查输出写入 `repair_context`，创建 `auto_repair` 执行记录并重新调用执行器；手动重试会写入 `retry_context`，记录 source run、source status、summary 和 `retry_chain`，重复触发时复用同一任务的 active run，避免重复入队；最大尝试次数由 `EXECUTION_AUTO_REPAIR_MAX_ATTEMPTS` 控制。L2/L3 风险和越权变更会阻断自动修复，要求人工处理。

任务：

- 为 `ExecutionRun` 增加迭代次数和父子关系，或记录 retry chain。（`repair_context` 和手动 `retry_context.retry_chain` 首版已完成）
- 将失败检查输出追加给 Codex 作为修复输入。
- 设置最大自动修复次数。
- L2/L3 或越权变更必须停止并要求人工处理。

完成标准：

- 检查失败时系统能自动进入一次或多次修复尝试。
- 页面能展示每次尝试的检查结果和最终结论。
- 超过最大次数后阻塞并保留完整证据。

### P5：MR/PR 创建与评审记录

目标：把通过自测的结果交给代码评审系统。

状态：首版已实现本地 MR/PR 记录与评审门禁。当前默认 `local` Provider 不依赖 GitLab/GitHub Token，会记录源分支、目标分支、执行记录、链接占位、评审状态和 `review_passed` 门禁；`gitlab` Provider 已可按项目读取 `gitlab_token`，创建 MR 前自动推送执行分支，并调用 GitLab API 创建 MR；`github` Provider 已可按项目读取 `github_token`，创建 PR 前自动推送执行分支，并调用 GitHub API 创建 PR。远端评审同步首版已实现，可拉取 GitLab MR 状态、讨论评论、commit CI 状态，以及 GitHub PR review、review comment、issue comment、check run 和 combined status，并写回 MR/PR、门禁、审计和证据链；交付工作台已提供远端 MR/PR 的“同步评审”入口，本地 MR 保留人工评审通过入口。评审阻塞自动修复串联首版已实现，可把远端阻塞项写入修复 run 的 `repair_context.review_issues`，修复成功后把修复分支推回原 GitLab/GitHub 源分支。GitLab/GitHub 默认 reviewer/assignee/label 配置、GitLab webhook 更新原 MR 记录和 GitHub webhook 更新原 PR 记录已完成首版。

任务：

- 增加 `MergeRequestRecord` 数据模型。（已完成）
- 实现 GitLab/GitHub Client 边界，优先 GitLab。（GitLab MR 和 GitHub PR 首版已完成）
- 支持创建 MR、记录 URL、源分支、目标分支、状态。（local/GitLab 首版已完成）
- 支持拉取 MR/PR 评论和阻塞性评审意见。（GitLab/GitHub 手动同步接口首版已完成）
- 支持评审阻塞自动修复。（首版已完成，修复后推回原 GitLab MR 源分支已完成）
- 将 `review_passed` 做成门禁。（已完成）

完成标准：

- 自测通过后可创建 MR。
- 页面显示 MR 链接和评审状态。
- 评审阻塞时进入待修复或人工处理状态。
- 没有 Token 时给出明确配置提示，不让流程静默失败。

### P6：测试环境部署与验收

目标：MR 后能进入测试环境验证，而不是停在代码层。

状态：首版已实现本地测试环境记录与验收记录。当前 `local` 模式只记录测试环境 URL、环境名、验收状态和证据链接；`webhook` 部署 Provider 已可按项目读取 `deploy_token` 调用外部部署入口，并把部署 URL、状态和证据写入 `DeployRecord`。webhook 返回 `status_url` 时，工作台可手动同步单条部署状态并回写门禁、审计和证据；后端提供 `POST /api/v2/deployments/sync-pending` 批量同步 pending 部署，`scripts/deployment_sync_worker.py --loop` 可后台定时同步 pending 部署，项目根目录已提供 `scripts/start-deployment-sync-worker.ps1`、`scripts/stop-deployment-sync-worker.ps1` 和 `scripts/start-dev.ps1 -WithDeploymentSync`。失败部署可从工作台重新部署并保留来源证据。`GET/PUT /api/v2/projects/{project_id}/deployment-environments` 已支持项目级测试环境 URL、日志 URL 和说明配置，访问管理页已提供最小项目测试环境配置入口；创建部署时优先使用项目配置，缺省再回退到 `DEPLOY_ENVIRONMENT_CONFIG_JSON`。部署 provider 返回的日志 URL 和日志尾部会脱敏进入证据。webhook provider 已支持常见 CI/CD 状态字段、ArgoCD sync/health、嵌套 pipeline/job/stage/step/check/task 状态、状态词归一化、运行标识、失败原因、日志链接和 links/_links 解析，并保留原始状态、状态路径、失败/等待节点摘要证据。目标 CI/CD 平台专用 payload/日志解析待在真实环境增强。

任务：

- 增加 `DeployRecord` 和 `VerificationRecord`。（已完成）
- 对接测试环境部署入口，初期可先记录外部部署 URL。（local 记录和 webhook 部署首版已完成）
- 支持 webhook 部署状态同步。（单条手动同步、pending 批量同步入口和本地 worker 启停脚本已完成，生产调度待增强）
- 支持人工验收：通过、拒绝、备注、截图或证据链接。（通过/失败和链接记录已完成）
- 将 `test_deployed`、`verification_passed` 做成门禁。（已完成）

完成标准：

- 页面能看到测试环境地址。
- 人工验收结果进入证据链。
- 验收失败能回到修复流程或标记阻塞。

### P7：Symphony Bridge、队列化与多任务并行

目标：通过 Symphony Bridge 把执行从 HTTP 请求迁移到后台编排，并支撑批量任务能力。

状态：首版已实现执行队列可见性、并发上限保护、Symphony internal bridge API、最小命令行 worker、生产 Compose worker profile、`SYMPHONY_RUNNER_COMMAND` 兼容 adapter、`SymphonyBridgeExecutor`、lease 过期失败恢复、暂停/恢复/取消控制、同一任务活跃 run 幂等保护、手动重试 retry chain，以及本地常驻 worker 启停脚本和 status 文件。常驻 worker 循环默认会在单次异常后记录 `error` 状态并继续轮询，显式 `--fail-fast` 才会在异常时退出。`executor_type=symphony` 的 dispatch 不再退回本地检查，也不会在 HTTP 请求中长时间执行；它会保持 queued，等待 worker claim 后通过 bridge complete 回写最终状态。真实上游 Symphony daemon 联调和真正并行调度容量阈值仍待目标环境验证。

任务：

- 按 `docs/symphony-integration-plan.md` 完成 S0-S3。（S0-S2 已完成，S3 已有最小 worker、生产 Compose worker profile、`SYMPHONY_RUNNER_COMMAND` 兼容 adapter、lease 过期失败恢复、本地常驻启停脚本和 worker 循环异常不中断）
- 引入任务队列和运行中状态管理。（执行记录队列查询已完成）
- 增加 internal claim、heartbeat、event、complete API。（已完成首版）
- 增加 `SymphonyBridgeExecutor`，支持 `executor_type = symphony`。（已完成首版）
- 限制最大并发数，避免本地 CPU/内存被打满。（dispatch 并发保护已完成）
- 支持取消、暂停、恢复。（首版已完成）
- 同一任务活跃执行记录幂等保护，避免重复入队。（首版已完成）
- 页面增加多任务执行看板。（队列页签已完成）

完成标准：

- 多个需求可排队执行。
- worktree、分支、日志互相隔离。
- 资源限制可配置。
- Symphony 回写结果后仍由 AI PJM 执行门禁判断。

### P8：Dify/OpenAI Provider 集成

目标：在 Provider 合同稳定后，引入外部编排工具，而不是让 Dify 接管平台状态。

状态：Dify/OpenAI Provider 边界首版已实现，默认不启用。`ai_workflow_provider=dify` 时，Spec 和影响分析可通过 Dify workflow 获取结构化输出；`ai_workflow_provider=openai` 时，Spec 和影响分析可通过 OpenAI Responses API 获取结构化输出。仓库上下文和任务包仍复用本地规则。Dify API Key 会优先按项目从 SecretStore 读取 `dify_api_key`，OpenAI API Key 会优先按项目读取 `openai_api_key`，项目未配置时分别回退到全局 `DIFY_API_KEY` / `OPENAI_API_KEY`。缺少必要配置或输出不合规时会明确失败；启用平台降级时，连续失败会转为本地规则 Provider，并在 Spec open questions、门禁 evidence 或 Impact metadata 里记录脱敏恢复证据。Spec/Impact 元数据会记录 workflow/model、schema name、schema version、prompt version 和本地确定性质量评分，便于后续质量评估与回溯。

任务：

- 实现 `DifyProvider`。（已完成首版）
- 实现 `OpenAIProvider` 或其他模型 Provider。（OpenAI 首版已完成）
- Provider 只返回结构化草稿，不直接改数据库状态。（已按合同约束）
- Dify/OpenAI API Key 按项目从 SecretStore 读取。（已完成首版）
- 加入 schema 校验、超时、重试、降级到本地规则。（结构化校验、超时、平台级重试、本地降级、Provider schema/prompt 版本记录和质量评分首版已完成）

完成标准：

- 可通过配置切换 `mock`、`local`、`dify`、`openai`。
- Provider 输出不合规时不会推进门禁。
- 页面展示 Provider 来源和置信度。
- 同一需求可追溯使用了哪个 workflow/model、schema 和 prompt 版本。
- 同一需求可追溯 Provider 输出质量评分和扣分项。

## 5. 暂不做事项

以下事项暂不进入近期开发：

- 自动生产发布。
- 多仓库联合开发。
- 默认子 Agent 评审。
- 轻量知识图谱。
- 完全自治 Agent 模式。

这些能力不是不重要，而是必须等主闭环稳定后再做。

## 6. 每阶段固定验证清单

每个阶段完成前必须执行：

```powershell
cd backend
python -m pytest tests/test_auth.py tests/test_delivery_v2_units.py tests/test_delivery_v2.py tests/test_health.py -q

cd ..\frontend
npm run build
```

还必须人工或浏览器验证：

- 页面无 `failed to fetch`。
- 页面无明显遮挡、重叠、横向溢出。
- 新增状态能在交付工作台看到。
- `git worktree list --porcelain` 无遗留临时 worktree。
- `.runtime/worktrees`、`.runtime/codex-prompts` 无无关残留。

## 7. 下一步立即执行

V2 主链路已经完成本地 MVP 闭环，下一步应转入生产化基础建设，避免继续堆演示功能。

推荐顺序：

1. 完成文档口径清理，让 README、路线图、蓝图、交互说明和生产化计划一致。
2. 按 `docs/symphony-integration-plan.md` 做 S0：拉通 Symphony 本地运行和 Codex 调用方式。
3. 做 S1/S2：实现 AI PJM internal execution bridge API 和 `SymphonyBridgeExecutor`。
4. 完善 SecretStore Provider 消费：Dify/OpenAI/GitLab/GitHub/webhook 部署已完成首版项目级读取，Dify/OpenAI 已有平台级重试和本地降级，OpenAI/GitLab/GitHub 凭证已有只读远端探测、失败原因写回和访问管理页轮换修复入口，Dify 支持显式安全 URL 探测。
5. 做 S3/S4：用 Symphony 执行低风险任务，创建真实 GitLab/GitHub MR，并补远端评审同步；GitLab 创建、同步、webhook 更新原 MR、自动修复推回源分支已完成首版，GitHub PR 创建、同步、webhook 更新原 PR 和自动修复推回源分支已完成首版。
6. 做 S5：增强真实测试环境部署 Provider，补目标 CI/CD 平台深度状态轮询；重新部署入口、项目级环境配置 API、访问管理页最小入口、环境 JSON 兜底、日志证据、后台同步启停脚本、常见 CI/CD 状态语义归一化、通用状态节点证据、运行标识、失败原因和日志链接首版已完成。后续只针对目标 CI/CD 平台补专用 payload/日志解析。
7. 再补目标生产容量基准和集中指标平台接入；Dify/OpenAI 真实环境联调降为可选质量增强，只有在需要外部 AI 对照时再做。备份恢复、过期队列恢复、历史 trace 回填、trace 时间线查询、Alembic 迁移链路、Docker PostgreSQL 真库演练、Docker Compose 生产等价最小栈、生产 worker 兼容 adapter、trace id、只读性能烟测、容量数据准备脚本、统一容量验证脚本、异常失败率、Prometheus 文本指标出口、通用 webhook 告警转发、最小可观测性、OpenAI Provider 和产品化交互首版已完成。

原因：生产使用时最大的风险不是缺少复杂组织治理，而是主链路仍需人工搬运、真实 MR/部署没有打通、执行和证据不够可靠。先补这些直接影响交付效率的能力，平台才能真实减少人工介入。
