# DeerFlow 智能研发工作流 V1 MVP 产品需求文档 (PRD)

## 1. 背景与目标

当前 DeerFlow 已具备强大的 Super Agent Harness 底座（LangGraph + Sandbox），但为了真正融入企业的日常研发流水线，需要将其与飞书（Lark）办公生态和阿里云 Codeup 代码托管平台深度集成，打造一个覆盖“产品规划 → 技术评审 → 代码开发 → 测试评估”的全生命周期智能研发工作流。

基于敏捷迭代与务实的工程策略，**V1 MVP 版本的核心目标是：“跑通闭环（Happy Path），屏蔽复杂交互”。** 
我们将采取拉取模式（Pull-based）与全局机器人身份（Bot Identity）的架构，避开复杂的 Webhook 状态同步地狱与用户级 OAuth 授权的坑。

---

## 2. 核心业务流程 (Happy Path)

V1 版本仅支持在 DeerFlow 前端平台进行完整的交互与审批操作：

1. **获取需求**：研发人员打开 DeerFlow UI，刷新页面，前端通过后端 API 从飞书项目主动拉取当前迭代的需求列表并展示。
2. **触发工作流**：研发人员勾选某个需求，点击“分配给 Agent 执行”。
3. **规划与评审生成**：LangGraph 状态机启动，Agent 开始读取需求上下文，自动生成技术方案（Spec / Design / Tasks）并在沙盒或上下文中准备完毕。
4. **人工审批 (Human-in-the-loop)**：LangGraph 运行至技术评审节点时自动挂起（Interrupt）。用户在 DeerFlow UI 查看生成的方案文档，点击“Approve（审批通过）”。
5. **编码与测试**：后端收到 UI 的审批指令，恢复状态机（Resume）。Coding Agent 和 Evaluation Agent 开始在 Sandbox 中编写代码、自我纠错并执行测试。
6. **交付与通知**：测试通过后，Agent 以“全局机器人”身份将代码 Push 到 Codeup 并创建 Merge Request（MR），同时向飞书工作群发送包含 MR 链接的通知消息卡片。

---

## 3. 关键技术决策

在探索阶段，我们明确了以下四大简化架构复杂度的技术决策：

### 决策 A：前端手动查询拉取 (Pull-based)
- **机制**：前端通过新增的 Backend API 代理请求（如 `GET /api/lark/requirements`），后端底层通过 `FeishuProjectMcp` 获取飞书需求数据。
- **收益**：避免了配置飞书项目的双向网络互通和验证，前后端数据流向清晰简单。

### 决策 B：手动更新保障一致性 (Forward-only Execution)
- **机制**：V1 版本不强依赖 Webhook 监听飞书端的需求状态变更（如“需求被删除/延期”）。
- **收益**：极大地降低了状态机回滚（Rewind）与补偿逻辑的开发成本，优先保障主流程能稳定跑到终点。后续可通过在阶段节点间加入轻量级的主动状态校验钩子（Sanity Check Node）来兜底。

### 决策 C：全局机器人身份 (Bot Identity)
- **机制**：所有向飞书发送的消息、在 Codeup 创建的分支和 MR，均统一使用环境变量配置的全局机器人凭据（飞书 App ID/Secret，Codeup 个人访问令牌 `x-yunxiao-token`）。
- **收益**：绕过复杂的基于 OAuth 2.0 的用户级授权机制（User Access Token），开箱即用。

### 决策 D：纯 UI 端审批复用现有机制 (Built-in Resume)
- **机制**：放弃 V1 版本在飞书消息卡片内直接点击审批的需求，将人工审批（Approve）入口收敛到 DeerFlow UI 上。
- **收益**：完美复用 DeerFlow 现有的 `threads/{thread_id}/state` 与 LangGraph Platform 兼容的中断/恢复协议。前端只需处理 `status: "interrupted"`，调用已有接口注入 `{"as_node": "tech_review", "values": {"approval": "approved"}}` 即可无缝唤醒状态机。

### 决策 E：代码仓库 Git Clone 挂载 (Stateful Mounting)
- **机制**：进入 Development 阶段前，后端使用全局机器人的 HTTPS 令牌（Deploy Key 或 PAT）执行 `git clone`，拉取目标仓库并创建 `feature/` 隔离分支，最后挂载到 Agent 的本地沙盒环境。
- **收益**：Agent 可以像在本地一样极速执行 `ls`、代码搜索及单元测试，无需通过缓慢的 API 接口读取文件，同时解决了沙盒与远端环境的认证隔离问题。

### 决策 F：框架代办 Git 提交 (Framework-Delegated Git)
- **机制**：在沙盒中，Agent **不具备** 任何 Git CLI 的执行权限（不能自己敲 `git commit`）。Git 提交流程由后端的 Python 节点在特定的时机代劳执行。
- **收益**：防止大模型产生幻觉执行破坏性命令（如强制回滚）。一切交付行为收敛于后端代码控制，确保每次 Push 的标准化和绝对安全。

### 决策 G：步步为营的增量提交 (Incremental Task Commits)
- **机制**：在多步骤开发中，Agent 每完成一个细分的子任务（Task），就显式调用完成状态；LangGraph 后端立即捕获状态，并在沙盒执行 `git add . && git commit -m "Task N Done"` 进行一次快照存档。
- **收益**：MR 记录中包含了开发过程的完整细粒度历史。如果后续步骤发生代码损坏，可以基于 Commit 记录精准回滚，避免“毕其功于一役”导致进度全毁的风险。

---

## 4. 功能模块拆解

### 4.1 飞书 MCP Server 配置接入
- **功能**：在 `extensions_config.json` 中配置并启用 `FeishuProjectMcp` (Type: `sse`)。
- **目标**：使 LangGraph 和 Backend 具备调用飞书项目 API 读取工作项详情、获取视图列表的能力。

### 4.2 前端需求列表与派发面板
- **功能**：新增一个专门的“飞书需求”页面/组件。
- **依赖接口**：
  - `GET /api/lark/requirements`：拉取飞书项目需求列表。
  - `GET /api/codeup/repositories`：获取用户的有权限的仓库列表供选择。
- **交互**：
  - 点击“刷新”调用后端接口加载需求列表（名称、状态、类型、关联的飞书需求文档链接）。
  - 支持选中一条需求并弹出派发弹窗 (Dispatch Dialog)。
  - **支持选择工作模式**：
    - **规划模式 (Planning Mode)**：Agent 的核心目标是“反向评估”。结合飞书需求文档链接和相关的代码仓库，利用 `@larksuite/cli` 的搜索工具查找历史设计与关联文档，评估需求设计是否合理、是否存在逻辑遗漏。
    - **开发模式 (Development Mode)**：跳过/基于已有规划，直接开始编码与执行测试。
  - **支持选择目标仓库 (多选)**：在派发弹窗中，允许用户同时勾选多个 Codeup 仓库（例如一个需求同时涉及到 `frontend-repo` 和 `backend-repo`）。
  - 创建一个绑定了该需求、选中的工作模式和选中仓库组合的 Agent 线程（Thread）。

**前端页面 UI 设计草图**：

```text
┌────────────────────────────────────────────────────────────────────────┐
│ 🦌 鹿流 Workspace                                                      │
├────────┬───────────────────────────────────────────────────────────────┤
│        │                                                               │
│ 💬 会话 │  研发需求 (Lark Project)                                      │
│ 🤖 智能体│  [ 所有状态 ▾ ] [ 所有迭代 ▾ ] [ 🔍 搜索需求... ]    (↻ 刷新列表)   │
│ 📚 记忆 │                                                               │
│ 🚀 需求 │  ┌─────────────────────────┐  ┌─────────────────────────┐     │
│        │  │ 📘 REQ-001             │  │ 🐞 BUG-102             │     │
│ ⚙️ 设置 │  │ 智能研发工作流集成         │  │ 修复沙盒挂载路径权限问题     │     │
│        │  │ [ 状态: 进行中 ]          │  │ [ 状态: 待排期 ]          │     │
│        │  │ 👤 产品经理: 张三          │  │ 👤 测试: 李四             │     │
│        │  │                         │  │                         │     │
│        │  │     [🚀 派发给 Agent]     │  │     [🚀 派发给 Agent]     │     │
│        │  └────────────┬────────────┘  └─────────────────────────┘     │
│        │               │                                               │
│        │   ┌───────────▼──────────────────────────────────────────┐    │
│        │   │ 派发需求：REQ-001 (基于大模型重构认证模块)               │    │
│        │   ├──────────────────────────────────────────────────────┤    │
│        │   │ 选择工作模式：                                         │    │
│        │   │ ┌──────────────────────────────────────────────────┐ │    │
│        │   │ │ [ 🔍 规划与反向评估 ]   |   [ 💻 直接开发与测试 ]  │ │    │
│        │   │ └──────────────────────────────────────────────────┘ │    │
│        │   │                                                      │    │
│        │   │ 📝 模式说明：                                        │    │
│        │   │ Agent 将读取飞书关联需求文档，搜索历史知识库与群聊讨论， │    │
│        │   │ 结合目标代码仓库现有逻辑，评估设计合理性，产出架构设计。 │    │
│        │   │                                                      │    │
│        │   │ 请选择目标代码仓库 (多选)：                             │    │
│        │   │ [☑] deer-flow-frontend (前端)                        │    │
│        │   │ [☑] deer-flow-backend  (后端)                        │    │
│        │   │ [ ] deer-flow-docs     (文档)                        │    │
│        │   │                                                      │    │
│        │   │ 选择负责处理该需求的 Agent：                             │    │
│        │   │ [ 主导智能体 (Lead Agent) ▾ ]                          │    │
│        │   │                                                      │    │
│        │   │              [ 取消 ]  [ 🚀 启动智能规划 ]             │    │
│        │   └──────────────────────────────────────────────────────┘    │
└────────┴───────────────────────────────────────────────────────────────┘
```

### 4.3 智能研发工作流 (LangGraph 图定义)
- **Phase 1: Planning / Tech Review** (若选择“规划模式”启动)：
  - Agent 通过 MCP 读取飞书项目中的需求关联文档。
  - 对于飞书文档、Wiki、表格和知识库搜索等深度功能，Agent 利用通过沙盒环境自动挂载的 `lark-wiki` 等 Skill（底层依赖预装的 `@larksuite/cli`，运行时由沙盒环境变量提供认证）来完成调用，从而查找历史设计与关联逻辑。
  - Agent 在挂载的代码仓库中检查现有架构，反向评估需求可行性，找出边界遗漏或逻辑冲突。
  - 产出架构设计文档与可行性报告（可写在虚拟挂载的 Workspace 中）。
- **Phase 2: Human-in-the-loop**：使用 `interrupt()` 挂起线程，抛出等待前端审批的信号（产品/技术负责人确认架构与评估结果）。
- **Phase 3: Development / Sandbox** (若选择“开发模式”或规划审批通过后)：基于已通过的技术设计，Coding Agent 挂载仓库并开始执行真正的代码编写、Lint 和自测。
- **Phase 4: Codeup Delivery**：封装 Codeup OpenAPI，自动拉分支、逐个 Task 提 Commit 并建 MR，通知关联人。使用 Codeup 的 OpenAPI 服务接入点 (`{domain}`) 及个人访问令牌 (`x-yunxiao-token`)。

### 4.4 核心技术实现约束与细节 (供开发阶段参考)

为了保障后续无缝进入代码实现，特补充以下架构级细节与数据结构：

- **线程 Metadata 数据契约**：当前端 UI 点击“启动研发工作流”时，调用现有的 `POST /api/threads` 接口，并注入以下特殊标识的 `metadata`，以供 LangGraph 后端状态机识别并接管：
  ```json
  {
    "metadata": {
      "type": "lark_requirement_task",
      "lark_requirement_id": "123456",
      "work_mode": "planning", // 规划模式 "planning" 或 开发模式 "development"
      "codeup_repositories": ["repo-name-1", "repo-name-2"] // 用户勾选的目标仓库列表
    }
  }
  ```
- **Codeup 代码挂载物理路径**：LangGraph 状态机在进入规划或开发阶段前，对应的预处理 Python 节点需解析上述 `codeup_repositories`。使用 `$CODEUP_CLONE_URL_TEMPLATE` 凭据执行 `git clone`，并将代码克隆到对应的物理隔离目录：`backend/.deer-flow/threads/{thread_id}/user-data/workspace/{repo_name}`。Agent 唤醒后，直接在 `/mnt/user-data/workspace/` 下进行多仓协作。
- **沙盒环境变量注入**：针对“规划模式”下 Agent 使用 `lark-wiki` 等 Skill 进行搜索的能力，底层依赖沙盒环境（Docker）中预装的 `@larksuite/cli`。因此后端的 SandboxProvider 需确保将宿主机的飞书 API 凭据（如 `FEISHU_APP_ID`, `FEISHU_APP_SECRET` 等环境变量）透传注入到沙盒容器中。
- **状态机编排 (Graph Nodes)**：后端需在 `deerflow/agents/` 体系内设计一条专属的 Graph（或使用 Router Agent），流转链路必须包含：`init_workspace_node` -> `planning_node` -> `human_approval_node` (触发 `interrupt`) -> `development_node` -> `delivery_node` (执行代办提 Commit/MR)。

---

## 5. 后续迭代规划 (Future Work - V2)

- **异常流与补偿机制**：当代码在 Codeup 提 MR 后被真实 Reviewer 打回时，捕获 Webhook 事件并重启 Coding Agent 修复问题。
- **双端审批支持**：实现飞书卡片的回调 Webhook 接口，使得用户在飞书聊天框点击“Approve”也能直接唤醒后端的 LangGraph 状态机。
- **动态状态校验**：在每个核心 Phase 启动前，自动拉取并校验一次飞书原需求状态，如果已作废则提前终止线程。