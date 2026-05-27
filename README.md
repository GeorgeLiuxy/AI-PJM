# AI PJM

AI PJM 是一个 AI 辅助工程交付编排平台。它不是通用项目管理工具，也不是替代 Codex 的编码器；它负责把业务输入转成可审计、可验证、可协作的工程交付链路。

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
- Dify Provider 边界首版，可通过配置接入 Spec/Impact workflow。
- 本地认证与项目权限首版：账号密码登录、Bearer Token、项目成员、角色权限、交付 API 权限保护。
- 中文化交付工作台页面。
- 前后端启动/关闭脚本。

尚未实现或未生产化：

- 真实本地代码上下文收集和任务范围推断已有首版，仍待增强语义匹配和历史需求读取。
- OpenAI Provider 尚未实现；Dify Provider 仍需生产联调、质量评估、降级策略和监控。
- Codex CLI 首版已可用，但仍需继续做自动修复闭环、性能优化和生产化运维配置。本机 WindowsApps 下的 `codex.exe` 仍会返回 `Access is denied`，当前使用全局 npm 版 `@openai/codex`。
- 当前 MR/PR、测试环境部署和验收是本地记录闭环；真实 GitLab/GitHub 创建、远端评审拉取、真实部署 Provider 仍待实现。
- 认证授权和项目权限已有本地首版，仍需补齐企业 SSO、细粒度按钮权限、人工动作操作者落库和审计报表。
- 密钥管理、PostgreSQL、数据库迁移、后台 Worker、审计和监控仍待实现。
- 默认子 Agent 评审、多仓库编排、自动生产发布暂不做。

后续功能执行顺序以 [v2-execution-roadmap.md](docs/v2-execution-roadmap.md) 为准；生产级落地以 [production-readiness-plan.md](docs/production-readiness-plan.md) 为准。

## 关键文档

- [V2 后续执行路线图](docs/v2-execution-roadmap.md)
- [生产级落地计划](docs/production-readiness-plan.md)
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
- 平台负责状态、门禁、审计、权限、证据。
- AI/Codex 负责生成候选方案和在受限工作区执行任务。
