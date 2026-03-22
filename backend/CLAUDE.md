# 项目约束说明

## 项目定位
本项目是“安全型团队提效 AI 工作台”的后端实现。

目标不是构建传统 ERP、项目管理系统、工单系统或大而全工作流平台。
目标是围绕最小业务闭环实现后端能力：

输入 -> Item（事项）-> Analysis（分析）-> Output（输出物）-> Adopted（采用）

系统必须服务于以下原则：
1. 少配置，重默认
2. AI 先给建议，用户再确认
3. 轻对象模型，避免大而全扩展
4. 状态流转清晰、可审计、可回写
5. 不改变既定产品初衷

## 不可变更的核心主对象
系统主对象只有以下三个：

### 1. Item
所有输入先落为事项。
来源可以包括：客户反馈、新需求、会议内容、Bug、工单内容。

### 2. Analysis
用于承载对 Item 的影响分析、优先级分析和判断结论。
Analysis 必须归属于 Item。

### 3. Output
用于承载 AI 生成的输出物，例如：
- PRD
- 测试点
- 会议纪要
- 上线说明
- 处理建议
- 周报摘要

Output 必须归属于 Item，可选关联 Analysis。

## 严格禁止
禁止新增平行主对象替代或稀释 Item / Analysis / Output。
特别禁止在未明确批准前引入以下对象作为新的主闭环对象：
- requirement
- task
- ticket
- workflow
- job
- pipeline
- review_case

## 状态机约束

### Item 状态
- draft
- pending_confirm
- confirmed
- analyzing
- decided
- output_generated
- done

### Analysis 状态
- pending
- running
- pending_review
- confirmed
- rejected

### Output 状态
- draft
- pending_confirm
- confirmed
- adopted

禁止跳过状态机进行任意赋值。
所有状态变化必须由明确动作触发，并记录日志。

## 建议值与最终值分离
AI 建议值与人工确认值必须分离存储。

必须支持：
- suggestion
- final

禁止：
1. 直接用 AI 建议值覆盖最终值
2. 把 suggestion 与 final 混存在同一字段
3. 将“确认”实现成简单覆盖 suggestion

## 实现原则
1. 先实现最小闭环，不做大而全扩展
2. 每次只实现一个垂直切片
3. 所有状态变更必须通过明确动作触发
4. 所有关键动作必须记录 action log
5. 模型调用必须通过统一抽象层，不允许业务代码直接绑定具体模型
6. 不要提前实现复杂配置系统、复杂权限系统、复杂审批系统
7. 不要主动增加额外能力，除非明确要求

## 模型调用约束
所有 AI / LLM 调用必须通过统一抽象层完成，例如：
- llm_client
- understanding_service
- analysis_service
- generation_service

禁止在业务 service、controller、repository 中直接绑定某个具体模型供应商或具体模型名称。

## 强制开发流程
每次开始实现前，必须先输出：
1. 实现计划
2. 文件变更清单
3. 数据表变更
4. API 清单
5. 测试清单
6. 潜在跑偏风险

在得到确认前，不要直接写代码。

## 禁止事项
禁止做以下事情：
1. 擅自重构产品对象模型
2. 擅自新增主业务对象
3. 擅自扩展复杂权限系统
4. 擅自扩展复杂工作流引擎
5. 擅自修改既定状态机
6. 擅自将 UI 展示逻辑硬编码进后端主模型
7. 擅自把 AI 建议值视为最终值
8. 擅自让一个接口完成多个业务阶段，破坏闭环可追踪性

## 代码与测试要求
1. 核心状态流转必须有测试
2. 核心 API 必须有 request/response 契约
3. 所有关键动作必须记录 action log
4. 失败路径必须可测试
5. 代码优先清晰稳定，不追求过度抽象
6. DTO / serializer / response schema 可以服务页面，但不能污染主领域模型

## 当前实现优先级
严格按以下顺序推进：
1. Item 闭环
2. Analysis 闭环
3. Output 闭环
4. Workbench 聚合
5. Timeline / 审计

禁止跳级做“看起来更酷”的功能。