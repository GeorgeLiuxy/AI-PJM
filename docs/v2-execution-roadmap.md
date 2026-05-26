# AI PJM v2 后续执行路线图

本文档是后续实现的执行准绳。若聊天讨论与本文档冲突，以本文档为准；若需要调整顺序，先更新本文档，再改代码。

## 1. 当前已完成基线

已完成：

- V2 主链路框架：需求接收 -> Spec -> 仓库上下文 -> 影响分析 -> 编码任务包 -> 执行记录。
- SQLite 本地化运行。
- 低风险自动审批、高风险人工审批。
- Git worktree 隔离执行。
- 必要检查执行、失败证据记录、重试入口。
- 可配置 Codex command hook。
- 初版真实本地上下文收集 Provider。
- 中文化交付工作台页面。
- 前后端启动/关闭脚本。

当前仍是“可演示主框架”，不是完整生产闭环。

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
- 不先做复杂多 Agent、知识图谱、多仓库编排，除非主闭环已经稳定。

## 4. 阶段计划

### P0：基线整理与可协作化

目标：让后续多人协作不被临时改动、旧流程、脏状态误导。

任务：

- 整理当前未提交改动，按功能拆成可审查提交。
- 补充 README 中的启动、关闭、验证说明。
- 明确当前能力边界：mock provider、Codex 未真实启用、MR/部署未实现。
- 确认 `.runtime`、worktree、日志、截图等运行时产物不进入版本控制。

完成标准：

- `git status` 中只保留预期源码改动。
- `npm run build` 通过。
- 后端 delivery v2 测试通过。
- `git worktree list --porcelain` 只剩主工作区。

### P1：真实本地上下文收集

目标：先不用 Dify，先把“项目代码、文档、历史需求、测试命令”在本地收集准。

状态：初版已实现。当前 `local` provider 会扫描仓库结构、文档、前后端配置、测试目录、依赖引用和需求相关候选文件。后续仍需继续增强语义匹配和历史需求读取。

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

状态：首版已实现。低风险任务在检查失败后可调用自动修复接口，平台会把失败检查输出写入 `repair_context`，创建 `auto_repair` 执行记录并重新调用执行器；最大尝试次数由 `EXECUTION_AUTO_REPAIR_MAX_ATTEMPTS` 控制。L2/L3 风险和越权变更会阻断自动修复，要求人工处理。

任务：

- 为 `ExecutionRun` 增加迭代次数和父子关系，或记录 retry chain。
- 将失败检查输出追加给 Codex 作为修复输入。
- 设置最大自动修复次数。
- L2/L3 或越权变更必须停止并要求人工处理。

完成标准：

- 检查失败时系统能自动进入一次或多次修复尝试。
- 页面能展示每次尝试的检查结果和最终结论。
- 超过最大次数后阻塞并保留完整证据。

### P5：MR/PR 创建与评审记录

目标：把通过自测的结果交给代码评审系统。

状态：首版已实现本地 MR/PR 记录与评审门禁。当前默认 `local` Provider 不依赖 GitLab/GitHub Token，会记录源分支、目标分支、执行记录、链接占位、评审状态和 `review_passed` 门禁；真实 GitLab/GitHub 创建、评论拉取和阻塞意见同步仍作为后续 Provider 增强项。

任务：

- 增加 `MergeRequestRecord` 数据模型。（已完成）
- 实现 GitLab/GitHub Client 边界，优先 GitLab。（已建立 Provider 边界，当前仅启用 local）
- 支持创建 MR、记录 URL、源分支、目标分支、状态。（local 首版已完成）
- 支持拉取 MR 评论和阻塞性评审意见。（远端 Provider 待实现）
- 将 `review_passed` 做成门禁。（已完成）

完成标准：

- 自测通过后可创建 MR。
- 页面显示 MR 链接和评审状态。
- 评审阻塞时进入待修复或人工处理状态。
- 没有 Token 时给出明确配置提示，不让流程静默失败。

### P6：测试环境部署与验收

目标：MR 后能进入测试环境验证，而不是停在代码层。

状态：首版已实现本地测试环境记录与验收记录。当前 `local` 模式只记录测试环境 URL、环境名、验收状态和证据链接，不执行真实部署；真实测试环境部署入口后续通过 Deploy Provider 接入。

任务：

- 增加 `DeployRecord` 和 `VerificationRecord`。（已完成）
- 对接测试环境部署入口，初期可先记录外部部署 URL。（local 记录已完成，真实部署待接入）
- 支持人工验收：通过、拒绝、备注、截图或证据链接。（通过/失败和链接记录已完成）
- 将 `test_deployed`、`verification_passed` 做成门禁。（已完成）

完成标准：

- 页面能看到测试环境地址。
- 人工验收结果进入证据链。
- 验收失败能回到修复流程或标记阻塞。

### P7：队列化与多任务并行

目标：在主闭环稳定后，再做批量任务能力。

状态：首版已实现执行队列可见性和并发上限保护。当前可查询最近执行记录、按状态筛选，并在页面“队列”页签查看；`EXECUTION_MAX_CONCURRENCY` 会阻止超过上限的 dispatch，让执行记录保持 queued。后台自动 worker、取消、暂停、恢复和真正并行调度仍待实现。

任务：

- 引入任务队列和运行中状态管理。（执行记录队列查询已完成）
- 限制最大并发数，避免本地 CPU/内存被打满。（dispatch 并发保护已完成）
- 支持取消、暂停、恢复。（待实现）
- 页面增加多任务执行看板。（队列页签已完成）

完成标准：

- 多个需求可排队执行。
- worktree、分支、日志互相隔离。
- 资源限制可配置。

### P8：Dify/OpenAI Provider 集成

目标：在 Provider 合同稳定后，引入外部编排工具，而不是让 Dify 接管平台状态。

状态：Dify Provider 边界首版已实现，默认不启用。`ai_workflow_provider=dify` 时，Spec 和影响分析可通过 Dify workflow 获取结构化输出；仓库上下文和任务包仍可复用本地规则。缺少 Dify URL、API Key 或 workflow id 时会明确失败，不会静默推进门禁。OpenAI Provider 仍待实现。

任务：

- 实现 `DifyProvider`。（已完成首版）
- 实现 `OpenAIProvider` 或其他模型 Provider。（待实现）
- Provider 只返回结构化草稿，不直接改数据库状态。（已按合同约束）
- 加入 schema 校验、超时、重试、降级到本地规则。（结构化校验和超时已完成，重试/降级策略待细化）

完成标准：

- 可通过配置切换 `mock`、`local`、`dify`、`openai`。
- Provider 输出不合规时不会推进门禁。
- 页面展示 Provider 来源和置信度。

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
python -m pytest tests/test_delivery_v2_units.py tests/test_delivery_v2.py tests/test_health.py -q

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

下一步不直接上 Dify，也不先做 MR。

推荐顺序：

1. P0/P1/P2 已完成首版，继续以测试和页面验证守住基线。
2. 继续 P3：先解决真实 `codex.exe` 可执行入口，再固化 `EXECUTION_CODEX_COMMAND_TEMPLATE`。
3. P3 完成后再进入 P4：自测失败后的有限自动修复闭环。
4. P4 稳定后再做 P5/P6：MR/PR、测试环境部署与验收证据。

原因：如果上下文仍是 mock，直接接 Codex 或 Dify 只会把不可靠输入自动化，后续问题更难定位。
