## Why

DeerFlow 已具备强大的 Super Agent Harness 底座，但缺乏与企业研发流水线的打通。通过集成飞书项目（需求来源）和阿里云 Codeup（代码托管），可以将"产品规划 → 技术评审 → 代码开发 → 交付"整个生命周期串联为一条由 AI 驱动的智能工作流，V1 MVP 聚焦于跑通 Happy Path、屏蔽复杂交互。

## What Changes

- 新增 Backend API `GET /api/lark/requirements`，通过 FeishuProjectMcp 拉取飞书项目需求列表
- 新增 Backend API `GET /api/codeup/repositories`，获取可用的 Codeup 仓库列表
- 新增前端"研发需求"页面，支持查看需求、选择工作模式（规划/开发）、多选目标仓库并派发给 Agent
- 新增 LangGraph R&D Workflow Graph，包含 `init_workspace_node → planning_node → human_approval_node → development_node → delivery_node` 五个节点
- `POST /api/threads` 扩展：支持通过 metadata 注入 `type: lark_requirement_task` 触发研发工作流
- 新增 Codeup 交付能力：自动 git clone 仓库、创建 feature 分支、逐 Task 增量提交、创建 MR 并通知飞书群

## Capabilities

### New Capabilities

- `lark-requirements-pull`: 通过 FeishuProjectMcp（SSE 模式）从飞书项目拉取需求列表，由 Backend Gateway 统一代理暴露为 REST API
- `requirements-dispatch-ui`: 前端"研发需求"页面——需求卡片展示、工作模式切换（规划 / 开发）、多仓库多选、派发 Agent 线程的完整 UI 交互
- `rd-workflow-graph`: LangGraph 状态机定义，涵盖规划、人工审批（Human-in-the-loop interrupt）、开发沙盒执行的完整图节点编排
- `codeup-delivery`: Codeup OpenAPI 封装，支持仓库克隆挂载、feature 分支创建、增量 Task 提交（Framework-Delegated Git）、MR 创建及飞书通知

### Modified Capabilities

（无——当前 openspec/specs/ 中无已有 spec 需要变更）

## Impact

- **Backend (`deerflow/agents/`)**: 新增 R&D Workflow Graph 定义及五个节点实现
- **Backend (`app/gateway/`)**: 新增 `/api/lark/requirements` 和 `/api/codeup/repositories` 路由
- **Backend (`deerflow/sandbox/`)**: SandboxProvider 需支持将飞书凭据环境变量透传到沙盒容器
- **Frontend (`src/app/`, `src/components/`)**: 新增需求列表页面及派发弹窗组件
- **配置 (`extensions_config.json`)**: 新增 FeishuProjectMcp SSE server 配置
- **配置 (`config.yaml`)**: 新增 Codeup PAT（`CODEUP_TOKEN`）、飞书 App 凭据（`FEISHU_APP_ID`/`FEISHU_APP_SECRET`）环境变量引用
- **依赖**: 无新增 Python/npm 包，复用现有 LangGraph、MCP SDK、lark-cli
