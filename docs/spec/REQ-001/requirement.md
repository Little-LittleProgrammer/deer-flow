# DeerFlow 智能研发工作流 (Agentic R&D Workflow) 需求文档

## 1. 需求背景与目标

随着大模型能力的提升，软件研发正在从“人类编写代码，工具辅助”向“人类掌舵（Steer），智能体执行（Execute）”的范式转变。
本项目旨在基于现有的 `deer-flow`（Super Agent Harness）底座，深度接入飞书（Lark）办公生态与阿里云 Codeup 代码托管平台，打造一个覆盖**产品规划、需求评审、代码开发、自动化测试**全生命周期的智能研发工作流。

**核心目标：**

1. **全链路自动化**：通过 Ultra 模式（深度思考与执行模式），让 Agent 能够自主完成从需求分析到代码测试的闭环。
2. **无缝生态融合**：打通飞书文档、飞书项目与 Codeup 代码仓库，实现需求与代码的实时联动。
3. **高可靠执行**：借鉴业界最佳实践，构建具备持久化、人在回路（Human-in-the-loop）和完善评估机制的 Agent Harness。

---

## 2. 核心理念与参考架构 (业界最佳实践)

为了确保系统的可靠性与可扩展性，本需求深度融合了以下头部 AI 公司的 Harness 理念：

1. **OpenAI - Harness Engineering (治理工程)**
  - **理念**："Humans steer, Agents execute"（人类掌舵，智能体执行）。
  - **应用**：系统不只是调用大模型，而是为 Agent 提供一个健壮的“执行环境”（Harness），包含沙盒（Sandbox）、工具链和反馈循环（Feedback loops）。在规划和开发阶段，Agent 通过 Trace grading 机制不断自我纠错。
2. **LangChain (LangGraph) - Durable Orchestration (持久化编排)**
  - **理念**：状态机驱动的持久化与人在回路。
  - **应用**：基于 LangGraph 底座，工作流中的每一步（规划、评审、开发、测试）都是持久化的。如果 Agent 在开发阶段遇到环境崩溃，可以从断点恢复（Durable execution）；在关键节点（如需求评审完、代码提交前）支持人类介入审批和修改（Human-in-the-loop）；同时具备短期工作记忆和长期跨会话记忆。
3. **Anthropic - Evaluation Harness (评估与测试治理)**
  - **理念**：多轮 Agent 交互的端到端评估框架。
  - **应用**：在测试阶段，引入 Anthropic 的 Evals 概念。不仅看 Agent 说了什么（Transcript），更看环境的最终状态（Outcome）。引入多维度的 Graders（代码静态分析、LLM 逻辑打分、人类抽查），确保 Agent 输出的代码在多轮工具调用后依然符合预期。

---

## 3. 核心功能模块

### 3.1 飞书生态深度接入 (Lark Integration)

- **飞书项目 MCP (Model Context Protocol)**：
  - 通过 HTTP MCP Server (`lark-project-dev-docs-mcp`) 实时读取和关联飞书项目中的需求状态、迭代计划和关联文档。
- **飞书文档与消息 CLI**：
  - 集成 `@larksuite/cli`，使 Agent 具备创建云文档、读取文档内容、在指定段落发表评论（Comment API）以及发送群组消息通知的能力。

### 3.2 阿里云 Codeup 深度接入 (Codeup Integration)

- **代码库上下文获取**：通过 Codeup OpenAPI 获取指定仓库的目录结构、核心文件内容及 Commit 历史。
- **分支与代码管理**：支持 Agent 自动创建特性分支（Feature Branch）、提交代码（Commit & Push）。
- **代码评审联动**：支持自动创建合并请求（Merge Request / PR），并由 Reviewer Sub-agent 进行自动化的代码审查（Code Review）。

### 3.3 Ultra 模式 (深度思考与执行引擎)

- 基于 `deer-flow` 已有的 ultra 模式
- 在该模式下，Agent 拥有完整的代码库上下文、需求文档上下文，并被授权进行多步骤的复杂推理、沙盒验证和自我反思。

---

## 4. 研发工作流详细设计

整个工作流分为四个核心阶段，由 LangGraph 状态机进行状态流转与持久化管理。

### 阶段一：产品规划阶段 (Product Planning)

**触发条件**：用户在系统中选择当前迭代的需求（飞书链接）及目标代码仓库（Codeup）。
**Agent 行为 (Ultra 模式)**：

1. **上下文摄取**：通过 MCP 读取飞书需求文档，通过 Codeup API 读取代码库当前状态。
2. **可行性分析**：分析需求与现有架构的兼容性，识别潜在的技术难点、遗漏的边缘场景（Edge cases）或逻辑冲突。
3. **反馈输出**：将分析结果整理为结构化的评审意见，通过飞书云文档 Comment API，直接在原需求文档的对应段落发布高亮评论，供产品经理确认。

### 阶段二：技术评审阶段 (Technical Review)

**触发条件**：产品经理确认需求并解决规划阶段的评论后，推进状态。
**Agent 行为 (Ultra 模式)**：

1. **文档生成**：基于完善后的需求和代码库现状，自动生成研发所需的标准文档集：
  - **Spec 文档**：详细的功能规格说明。
  - **Design 文档**：系统架构设计、数据库变更、API 接口定义（参考 OpenAI 的环境定义）。
  - **Task 文档**：将需求拆解为可执行的开发任务列表（WBS）。
  - **Test 文档**：定义验收标准和测试用例（参考 Anthropic 的 Tasks & Trials 定义）。
2. **飞书同步**：通过飞书 API 将上述文档创建为关联的云文档，并绑定到飞书项目中。
3. **Human-in-the-loop**：暂停执行，等待技术负责人在飞书或系统中点击“审批通过”。

### 阶段三：代码开发阶段 (Development)

**触发条件**：技术评审通过，任务分配完成。
**Agent 行为 (Ultra 模式)**：

1. **任务摄取**：读取 Task 文档和 Design 文档。
2. **沙盒编码**：在 `deer-flow` 的安全沙盒中进行代码编写。利用 LangGraph 的持久化特性，Agent 可以分步骤实现 Task，每完成一个 Task 进行一次本地 Commit。
3. **自我纠错**：开发过程中，Agent 自动运行 Linter 和基础编译，利用反馈循环（Feedback loop）自我修复语法和依赖错误。

### 阶段四：测试与评估阶段 (Testing & Evaluation)

**触发条件**：开发阶段的 Task 全部完成。
**Agent 行为 (Ultra 模式 - 引入 Anthropic Eval 理念)**：

1. **测试用例生成与执行**：基于 Test 文档，生成自动化测试脚本（单元测试、集成测试）并在沙盒中运行。
2. **多维 Grader 评估**：
  - *Code-based Grader*：检查测试覆盖率、静态代码扫描（SonarQube 等）、API 契约测试。
  - *LLM-based Grader*：由独立的 Reviewer Sub-agent 检查代码规范、架构一致性和潜在的安全漏洞。
3. **分支与合并**：
  - 如果测试失败（Outcome 不达标），将错误 Trace 喂回给开发 Agent 进行修复（多轮流转）。
  - 如果测试通过，将代码 Push 到 Codeup 特性分支，并自动创建 Merge Request (MR)。
4. **结果输出**：生成测试与执行报告，通过飞书消息通知相关人员进行最终的人工 Code Review。

---

## 5. 非功能性需求与系统要求

1. **状态持久化与可恢复性 (Durability)**：
  - 任何阶段的 Agent 崩溃或超时，都必须能从 LangGraph 的 Checkpoint 恢复，不丢失已生成的代码或文档。
2. **权限与安全隔离 (Security)**：
  - Agent 的代码执行必须严格限制在 `deer-flow` 的 Sandbox 中。
  - 飞书 API 和 Codeup API 的调用需遵循最小权限原则（仅限指定项目、文档和仓库的读写）。
3. **可观测性 (Observability)**：
  - 记录 Agent 的完整思考过程（Transcripts）、工具调用日志和沙盒终端输出，以便于后续的 Trace grading 和人工审计。

