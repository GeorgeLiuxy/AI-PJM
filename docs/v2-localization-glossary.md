# AI PJM v2 Localization Glossary

This glossary keeps product wording consistent across backend APIs, frontend pages, prompts, and documentation.

## Product Terms

| English | Chinese | Notes |
| --- | --- | --- |
| Demand Item | 需求项 | Raw business input normalized into a trackable item. |
| Spec Card | Spec 卡 | The confirmed or draft engineering specification. |
| Repo Context | 仓库上下文 | Repository, branch, module, and test command context. |
| Impact Analysis | 影响分析 | Code and delivery impact, not only business impact. |
| Coding Task | 编码任务 | Codex-ready execution package. |
| Execution Run | 执行记录 | One executor attempt, including logs and result. |
| Gate Check | 门禁检查 | Hard rule result. It is not a prompt suggestion. |
| Evidence | 证据 | Logs, test output, MR links, approval records, deployment links. |
| Test Deployment | 测试环境部署 | Deployment for verification, not production release. |
| Verification | 验证 | Human or automatic validation against acceptance criteria. |

## Status Terms

| Status | Chinese | Meaning |
| --- | --- | --- |
| `intake` | 已录入 | Demand has been captured. |
| `context_ready` | 上下文就绪 | Project/repo/context has been collected. |
| `spec_generated` | Spec 已生成 | AI generated a draft spec. |
| `spec_manual_required` | Spec 待人工确认 | Manual approval is required. |
| `spec_approved` | Spec 已确认 | Spec is allowed to continue. |
| `planned` | 已形成方案 | Implementation plan or coding task is ready. |
| `coding` | 编码中 | Executor is modifying code. |
| `self_testing` | 自测中 | Required local checks are running. |
| `fixing` | 修复中 | AI is fixing failed checks or review issues. |
| `mr_created` | MR 已创建 | Merge request or pull request exists. |
| `reviewing` | 评审中 | AI or human review is in progress. |
| `test_deployed` | 测试环境已发布 | Test environment is available. |
| `verifying` | 验证中 | Acceptance verification is in progress. |
| `verified` | 验证通过 | Verification passed. |
| `done` | 已完成 | Delivery is archived as complete. |
| `blocked` | 已阻塞 | Requires human decision or external fix. |

## Risk Terms

| Risk | Chinese | Automation Rule |
| --- | --- | --- |
| `L0` | 低风险自动任务 | Can proceed automatically after gates pass. |
| `L1` | 普通风险任务 | Can execute automatically; may notify before MR/deploy. |
| `L2` | 高风险任务 | Requires manual spec or plan approval. |
| `L3` | 强管控任务 | Requires explicit approval; auto-merge/deploy disabled. |

## UI Copy Rules

- Use "自动推进" instead of "全自动" unless the flow truly has no human gate.
- Use "门禁" for hard system checks.
- Use "建议" only for AI-generated, non-binding content.
- Use "确认" for manual approval.
- Use "验证" for acceptance checks after deployment or execution.
- Use "证据" for logs, test results, review results, MR links, and deployment URLs.

## API Naming Rules

- Prefer English snake_case for persisted fields.
- Use Chinese only in display labels and documentation.
- Keep risk levels and statuses as stable English enum values.
- Do not reuse old `item done` semantics for delivery completion unless verification has passed.
