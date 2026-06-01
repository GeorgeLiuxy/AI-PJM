# AI PJM

AI PJM 是一个 AI 辅助工程交付编排平台。它不是通用项目管理工具，不是企业治理平台，也不是替代 Codex 的编码器；它负责把业务输入转成可审计、可验证、可协作的工程交付链路。

当前主流程：

```text
业务输入
-> 上下文收集
-> SpecCard
-> 风险与门禁判断
-> CodingTask 任务包
-> Codex/执行器执行记录
-> 自测证据
-> MR/PR
-> 测试环境部署
-> 验收归档
```

## 当前能力

已实现：

- V2 主链路 API 和前端交付工作台。
- SQLite 本地数据库。
- 低风险自动审批、高风险人工审批。
- Git worktree 隔离执行。
- 必要检查执行、失败证据记录、重试入口和低风险自动修复首版。
- 可配置 Codex command hook，支持执行前预检和变更范围校验。
- 真实 Codex CLI 首版接入：通过 npm 版 `@openai/codex` 在隔离 worktree 中执行。
- 本地 MR/PR 记录、评审门禁、测试环境记录和验收记录。
- 执行队列可见性和基础并发上限保护。
- Dify Provider 边界首版，可通过配置接入 Spec/Impact workflow，并优先按项目从 SecretStore 读取 `dify_api_key`。
- Symphony 融合方案已落地到文档，后续 Codex 编排优先采用 AI PJM 控制平面 + Symphony 执行编排引擎。
- 本地认证与项目权限首版：账号密码登录、Bearer Token、项目成员、角色权限、交付 API 权限保护。
- 权限管理页面首版：查看项目/用户、创建项目、创建本地用户、维护用户状态/角色、重置密码并调整项目角色。
- 前端按钮级权限首版：工作台动作和权限管理入口按角色显示或拦截。
- 人工动作操作者结构化落库首版：人工审批、MR 创建/评审、测试部署、验收记录写入业务表操作者字段。
- 审计查询增强首版：支持操作者、动作、对象、时间范围、关键词筛选，并可导出 CSV。
- 审计事件首版：关键人工/敏感动作落库，并在工作台审计页签展示。
- 项目密钥管理首版：服务端加密存储项目级凭证，访问管理页只展示掩码，不回显明文。
- 密钥健康检查首版：支持登记过期时间、展示健康状态、手动检查可解密性，不返回明文。
- 执行日志和执行证据脱敏首版：持久化前清洗 Token、API Key、密码、Authorization 等敏感片段。
- 中文化交付工作台页面。
- 前后端启动/关闭脚本。

尚未实现或未生产化：

- 真实本地代码上下文收集和任务范围推断已有首版，仍待增强语义匹配和历史需求读取。
- OpenAI Provider 尚未实现；Dify Provider 仍需生产联调、质量评估、降级策略和监控。
- Codex CLI 首版已可用，但仍需继续做自动修复闭环、性能优化和生产化运维配置。本机 WindowsApps 下的 `codex.exe` 仍会返回 `Access is denied`，当前使用全局 npm 版 `@openai/codex`。
- 当前 MR/PR、测试环境部署和验收是本地记录闭环；真实 GitLab/GitHub 创建、远端评审拉取、真实部署 Provider 仍待实现，这是近期主线。
- Symphony Bridge 尚未实现；当前执行仍是 AI PJM 本地执行器路径，后续按融合方案接入后台 daemon/workspace 编排。
- 认证授权和项目权限保留最小角色模型；企业 SSO、复杂业务角色和审计报表平台化不作为近期主线。
- 密钥管理已有本地加密存储、健康检查和执行证据脱敏首版，Dify API Key 已可按项目读取；近期重点是让 GitLab/OpenAI/部署 Provider 按项目消费凭证。
- PostgreSQL、数据库迁移、后台 Worker 和最小可观测性仍待实现。
- 默认子 Agent 评审、多仓库编排、自动生产发布暂不做。

后续功能执行顺序以 [v2-execution-roadmap.md](docs/v2-execution-roadmap.md) 为准；生产级落地以 [production-readiness-plan.md](docs/production-readiness-plan.md) 为准。

## 关键文档

- [V2 后续执行路线图](docs/v2-execution-roadmap.md)
- [生产级落地计划](docs/production-readiness-plan.md)
- [AI PJM + OpenAI Symphony 融合方案](docs/symphony-integration-plan.md)
- [V2 交付蓝图](docs/v2-delivery-blueprint.md)
- [V2 实现计划](docs/v2-implementation-plan.md)
- [V2 交互流程](docs/v2-interaction-flow.md)
- [V2 验证指南](docs/v2-verification-guide.md)
- [V2 中文术语表](docs/v2-localization-glossary.md)

## 本地启动

启动后端和前端：

```powershell
.\scripts\start-dev.ps1
```

如果 `5173` 被其他项目占用，可以指定端口：

```powershell
.\scripts\start-dev.ps1 -FrontendPort 5174
```

关闭本地服务：

```powershell
.\scripts\stop-dev.ps1
```

常用地址：

- 前端工作台：http://127.0.0.1:5174
- 后端接口文档：http://127.0.0.1:8010/docs
- 健康检查：http://127.0.0.1:8010/health

如果使用默认端口启动，前端地址可能是 `http://127.0.0.1:5173`。实际端口以启动脚本输出为准。

## 固定验证命令

后端：

```powershell
cd backend
python -m pytest tests/test_auth.py tests/test_delivery_v2_units.py tests/test_delivery_v2.py tests/test_health.py -q
```

启用本地账号登录：

```powershell
cd backend
$env:AUTH_ENABLED="true"
$env:AUTH_BOOTSTRAP_ADMIN_PASSWORD="change-me-before-production"
```

首次启动 SQLite 开发库时会创建 `admin` 用户和默认项目。生产环境必须更换默认密码，并接入后续的密钥管理和审计能力。

启用项目密钥写入前必须设置主密钥：

```powershell
cd backend
$env:SECRET_STORE_MASTER_KEY="replace-with-a-long-random-secret"
```

密钥 API 和访问管理页只返回掩码，例如 `****alue`；明文只在服务端按项目权限解析，不进入前端响应。

Dify 项目级凭证约定密钥名为 `dify_api_key`，可通过 `DIFY_API_KEY_SECRET_NAME` 调整。项目未配置该密钥时，Dify Provider 回退使用全局 `DIFY_API_KEY`，便于本地调试。

前端：

```powershell
cd frontend
npm run build
```

运行时清理检查：

```powershell
git worktree list --porcelain
Get-ChildItem .runtime\worktrees -Force -ErrorAction SilentlyContinue
Get-ChildItem .runtime\codex-prompts -Force -ErrorAction SilentlyContinue
```

## 运行时文件

以下目录或文件不应进入版本控制：

- `.runtime/`
- `logs/`
- `data/`
- `backend/data/`
- `node_modules/`
- `.venv/`
- `*.db`
- `*.log`

如果后续出现新的临时产物，先更新 `.gitignore`，再继续编码。

## 协作约束

- 新功能先对齐 [v2-execution-roadmap.md](docs/v2-execution-roadmap.md) 的阶段顺序。
- 生产化能力先对齐 [production-readiness-plan.md](docs/production-readiness-plan.md) 的阶段顺序和上线门槛。
- 修改状态机、门禁、执行器前必须补测试。
- Provider 只能返回结构化草稿，不直接推进数据库状态。
- 平台负责状态、门禁、最小权限、密钥、审计和证据。
- AI/Codex 负责生成候选方案和在受限工作区执行任务。
- 低风险任务尽量自动流转，高风险任务保留人工确认。
