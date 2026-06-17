# 生产开放项

本文只记录当前无法在本地代码侧闭环的生产化事项，避免后续开发把外部环境问题误判成产品功能缺失。主链路计划仍以 `production-readiness-plan.md` 和 `v2-execution-roadmap.md` 为准。

## 当前外部阻塞

这些事项需要目标环境、真实凭证或外部平台状态，不能靠继续硬改本仓库解决：

1. GitHub Actions 远端 CI 验证
   - 当前应通过 `scripts/check-github-actions.ps1` 读取 `Production Validation` workflow 状态。
   - 如果报告显示 API 限流、Token 失效、Actions 未启用或账号计费锁定，先修复 GitHub 侧状态，再重新验证。

2. 真实 MR/PR Provider
   - 需要在目标环境配置 GitLab/GitHub 仓库、目标分支、项目级 `gitlab_token` 或 `github_token`。
   - 本地已具备创建、同步评审、webhook 回写和修复后推回源分支能力；目标环境要验证的是凭证权限和仓库策略。

3. 真实测试环境部署 Provider
   - 需要目标 CI/CD 或部署平台提供 webhook URL、状态 URL、日志 URL 和失败 payload 样例。
   - 通用状态解析已覆盖常见 `pipeline/job/stage/step/check/task` 结构；专用字段应在拿到真实 payload 后再补。

4. 上游 Symphony daemon 联调
   - 当前已有 AI PJM Bridge、最小 worker、Compose worker profile 和 `SYMPHONY_RUNNER_COMMAND` adapter。
   - 如果接入真实 daemon，必须让 daemon 通过 bridge claim/event/complete 回写，不能绕过 AI PJM 门禁。

5. Dify/OpenAI 生产质量评估
   - 需要真实 workflow、API Key 和脱敏样例需求。
   - 接入后运行 `scripts/check-provider-quality.ps1 -Provider all`，只允许 Provider 返回结构化草稿，不允许直接推进流程状态。

6. 集中监控和告警渠道
   - 本地已有 Prometheus 文本指标和通用 webhook 告警 worker。
   - 目标环境需要接入实际 Prometheus/日志平台/通知渠道，并验证一条测试告警可被接收和定位。

## 非阻塞停车场

以下事项不阻塞当前试点生产，除非真实试点暴露明确需求：

- 企业 SSO 或复杂组织治理。
- 多层级业务角色、批量成员维护、复杂授权视图。
- 自动生产发布。
- 多仓库联合开发。
- 大规模多 Agent 自动评审。
- 知识图谱或长期语义记忆体系。
- 进一步 UI 视觉打磨。

## 当前优先验证顺序

1. 本地固定基线：`scripts/check-production-suite.ps1`。
2. 生产等价 Compose：`scripts/check-production-compose.ps1 -BuildImages`。
3. 远端 CI：`scripts/check-github-actions.ps1 -Wait`。
4. 目标试点门禁：`scripts/check-target-pilot.ps1`。
5. 目标容量烟测：`scripts/check-capacity-smoke.ps1`。
6. 真实低风险需求闭环：输入 -> Spec -> 任务包 -> Symphony/Codex 执行 -> MR/PR -> 测试部署 -> 验收归档。
