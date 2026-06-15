# AI PJM 生产化验证手册

本文档用于约束上线前验证顺序。目标是尽快进入可试点生产状态，同时避免把精力消耗在当前阶段不必要的企业治理能力上。

## 优先级排序

### P0：发布前硬基线

每次合并或发布前必须执行：

```powershell
.\scripts\check-production-readiness.ps1
```

该脚本覆盖：

- 后端关键测试：认证、交付主链路、可观测性、迁移和健康检查。
- 本地 Provider 质量烟测：验证 Spec 生成质量下限。
- 前端安全审计：`npm audit --audit-level=high`。
- 前端回归测试：Vitest。
- 前端生产构建：Vite build。

可选参数：

```powershell
.\scripts\check-production-readiness.ps1 -SkipFrontend
.\scripts\check-production-readiness.ps1 -SkipBackend
.\scripts\check-production-readiness.ps1 -ContinueOnError
```

验收标准：脚本所有选中检查通过，且工作区没有未提交的有效代码。

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

### P1：外部 Provider 质量验证

本地规则 Provider 只能证明平台链路可用，不能证明生产 AI 质量。接入真实 Dify/OpenAI 后执行：

```powershell
cd backend
python scripts/provider_quality_smoke.py --provider all --spec-only --min-score 0.75 --output-file ..\.runtime\provider-quality.json
```

验收标准：

- local、Dify、OpenAI 的结果都有结构化输出或脱敏失败原因。
- 真实 Provider 输出包含需求摘要、目标、范围、风险、验收标准和任务拆分。
- 不允许 Provider 直接推进数据库状态或绕过门禁。

### P2：容量和运维验证

进入试点生产前执行：

- 使用合成数据准备脚本生成至少 1 万条交付数据。
- 对只读核心接口执行性能烟测。
- 将 Prometheus 文本指标接入现有监控系统。
- 将告警 worker 接入团队真实通知渠道。
- 固化备份调度、恢复演练和日志保留策略。

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
