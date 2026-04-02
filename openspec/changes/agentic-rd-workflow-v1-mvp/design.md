## Context

DeerFlow 现有架构：Browser → nginx:2026 → Frontend:3000 / Gateway:8001 / LangGraph:2024，以 LangGraph + Sandbox 为核心提供通用 Super Agent Harness 能力。当前系统已支持多模型、MCP 集成、沙盒执行和线程中断/恢复，但缺少与飞书项目（需求管理）和 Codeup（代码托管）的集成，无法支撑企业研发流水线场景。

本设计在不破坏现有架构的前提下，以"最小侵入"方式新增研发工作流路径：扩展 Gateway API、新增一条 LangGraph Graph、新增前端页面。

## Goals / Non-Goals

**Goals:**
- 在 DeerFlow UI 中实现从"拉取飞书需求"到"Codeup 创建 MR"的完整 Happy Path
- 复用现有 LangGraph interrupt/resume 机制实现人工审批节点
- Agent 在沙盒中以 lark-cli Skill 访问飞书文档/知识库（规划模式）
- 以增量提交方式（每个 Task 一次 commit）记录开发过程

**Non-Goals:**
- V1 不支持飞书卡片内直接点击审批（Webhook 回调）
- V1 不监听飞书需求状态变更（不处理需求被取消/延期的 Webhook 事件）
- V1 不支持 OAuth 2.0 用户级授权，所有外部操作均使用 Bot 全局凭据

## Decisions

### 决策 A：Pull-based 需求获取（前端主动拉取）
前端通过 Gateway `GET /api/lark/requirements` 按需拉取，而非 Webhook 推送。

- **选择理由**：避免配置飞书项目双向网络互通和 Webhook 验签逻辑，数据流向单向清晰。
- **备选方案**：飞书 Webhook 推送 + 本地数据库缓存——需要公网可达的回调地址和持久化层，复杂度高，V1 不值得投入。

### 决策 B：Bot 全局身份（统一凭据）
所有外部操作（飞书消息、Codeup 分支/MR）统一使用环境变量中的机器人凭据（`FEISHU_APP_ID/SECRET`、`CODEUP_TOKEN`），不走用户级 OAuth。

- **选择理由**：绕过 OAuth 2.0 授权流程，开箱即用，极大降低集成复杂度。
- **备选方案**：用户 OAuth Token——需要额外的授权页面、Token 刷新逻辑，V1 阶段不必要。

### 决策 C：UI 端审批复用现有 interrupt/resume
人工审批通过 DeerFlow UI 操作，后端调用 LangGraph Platform 的 `POST /threads/{thread_id}/runs` 注入 resume payload，不在飞书端新增审批入口。

- **选择理由**：完美复用现有线程中断/恢复协议，无需额外开发。前端已有 `status: "interrupted"` 处理逻辑。
- **Resume Payload 契约**：`{"as_node": "human_approval_node", "values": {"approval": "approved"}}`

### 决策 D：Framework-Delegated Git（框架代劳提交）
Agent 在沙盒内**不具备** Git CLI 执行权限（通过沙盒工具白名单屏蔽）。每完成一个 Task，LangGraph 后端节点代劳执行 `git add . && git commit -m "Task N: <description>"`。

- **选择理由**：防止 LLM 幻觉执行破坏性 Git 操作（如 force reset）；确保每次 Push 的标准化。
- **备选方案**：让 Agent 自行执行 Git 命令——安全风险高，不可控。

### 决策 E：仓库 Git Clone 挂载到沙盒
在进入规划/开发节点前，`init_workspace_node` 使用 `CODEUP_CLONE_URL_TEMPLATE` 执行 `git clone`，克隆到物理路径 `backend/.deer-flow/threads/{thread_id}/user-data/workspace/{repo_name}`，沙盒挂载后 Agent 通过 `/mnt/user-data/workspace/` 访问。

- **选择理由**：Agent 可以极速执行本地文件操作（ls、grep、测试），无需通过缓慢的 API 接口读取代码。
- **多仓库支持**：`codeup_repositories` 列表中的每个仓库均克隆到独立子目录，Agent 在 `/mnt/user-data/workspace/` 下多仓协作。

### 决策 F：线程 Metadata 作为工作流触发契约
`POST /api/threads` 时注入特殊 metadata，LangGraph Graph Router 据此识别并路由到研发工作流：
```json
{
  "type": "lark_requirement_task",
  "lark_requirement_id": "<id>",
  "work_mode": "planning" | "development",
  "codeup_repositories": ["repo-a", "repo-b"]
}
```
- **选择理由**：复用现有线程创建接口，无需新增 API 端点；metadata 解耦触发参数与 Graph 内部状态。

### 决策 G：沙盒 lark-cli Skill 凭据透传
规划模式下，Agent 通过沙盒内预装的 `@larksuite/cli` 访问飞书文档/Wiki。SandboxProvider 在启动容器时将宿主机的 `FEISHU_APP_ID`、`FEISHU_APP_SECRET` 等环境变量注入容器。

- **选择理由**：lark-cli 认证机制依赖环境变量，透传是最低侵入的实现方式；无需在沙盒内重新登录。

## Risks / Trade-offs

- **[风险] 飞书 MCP SSE 连接稳定性** → 在 Gateway 层加入超时重试（最多 3 次），拉取失败时返回 503 错误码，前端展示友好提示。
- **[风险] Codeup 仓库 Clone 耗时过长** → `init_workspace_node` 作为异步节点运行，前端通过 stream event 展示进度；超时（默认 5 分钟）后中断并通知用户。
- **[风险] LLM 幻觉产生破坏性代码** → 增量提交机制（每 Task 一个 commit）提供精准回滚点；Delivery 节点创建 MR 而非直接 merge，人工可最终把关。
- **[取舍] UI 审批 vs. 飞书卡片审批** → V1 仅支持 UI 审批，降低集成复杂度；V2 再追加飞书卡片 Webhook 回调路径。
- **[取舍] Forward-only 执行** → 不监听飞书端需求状态变更，极端情况下 Agent 可能处理已废弃的需求；可通过每阶段开始前增加轻量 Sanity Check Node 兜底（V2 规划）。
- **[取舍] 全局 Bot 凭据** → 所有操作以同一机器人身份出现在飞书/Codeup，无法区分操作归属；对 V1 场景（单团队内部使用）可接受。

## Migration Plan

1. 新增配置项（`config.yaml`）：`FEISHU_APP_ID`、`FEISHU_APP_SECRET`、`CODEUP_TOKEN`、`CODEUP_CLONE_URL_TEMPLATE`
2. 新增 FeishuProjectMcp SSE server 到 `extensions_config.json`
3. 后端新增 Graph 和 Gateway 路由（不修改现有路由）
4. 前端新增独立页面路由 `/requirements`（不修改现有页面）
5. 无数据迁移、无 breaking change，可独立部署和回滚

## Open Questions

- `CODEUP_CLONE_URL_TEMPLATE` 的具体格式如何？需确认阿里云 Codeup HTTPS clone URL 结构（含 token 嵌入方式）。
- FeishuProjectMcp SSE server 的具体 endpoint 和认证参数格式需与飞书项目负责人确认。
- 规划模式下 Agent 生成的架构设计文档存储位置——写入沙盒 Workspace 后是否需要自动同步到飞书文档？（V1 暂定仅存沙盒，在 UI 中展示）
