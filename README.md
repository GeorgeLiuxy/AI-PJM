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
- 必要检查执行、失败证据记录、重试入口。
- 可配置 Codex command hook，支持执行前预检和变更范围校验。
- 真实 Codex CLI 首版接入：通过 npm 版 `@openai/codex` 在隔离 worktree 中执行。
- 中文化交付工作台页面。
- 前后端启动/关闭脚本。

尚未实现或未生产化：

- 真实本地代码上下文收集和任务范围推断已有首版，仍待增强语义匹配和历史需求读取。
- Dify/OpenAI Provider 尚未实现。
- Codex CLI 首版已可用，但仍需继续做自动修复闭环、性能优化和生产化运维配置。本机 WindowsApps 下的 `codex.exe` 仍会返回 `Access is denied`，当前使用全局 npm 版 `@openai/codex`。
- MR/PR 创建、远端评审拉取、测试环境部署、验收记录尚未完成。
- 多任务队列、默认子 Agent 评审、多仓库编排暂不做。

后续执行顺序以 [v2-execution-roadmap.md](docs/v2-execution-roadmap.md) 为准。

## 关键文档

- [V2 后续执行路线图](docs/v2-execution-roadmap.md)
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
python -m pytest tests/test_delivery_v2_units.py tests/test_delivery_v2.py tests/test_health.py -q
```

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
- 修改状态机、门禁、执行器前必须补测试。
- Provider 只能返回结构化草稿，不直接推进数据库状态。
- 平台负责状态、门禁、审计、权限、证据。
- AI/Codex 负责生成候选方案和在受限工作区执行任务。
