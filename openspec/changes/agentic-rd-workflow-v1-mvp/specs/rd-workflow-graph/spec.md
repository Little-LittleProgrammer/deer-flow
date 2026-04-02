## ADDED Requirements

### Requirement: 定义研发工作流 LangGraph Graph
后端 SHALL 在 `deerflow/agents/` 下新增一条专属的 R&D Workflow Graph，包含五个有序节点：`init_workspace_node → planning_node → human_approval_node → development_node → delivery_node`。

#### Scenario: Graph 通过线程 metadata 路由触发
- **WHEN** 新建线程时 metadata 包含 `{"type": "lark_requirement_task"}`
- **THEN** LangGraph Router 将该线程路由到 R&D Workflow Graph，而非默认 Lead Agent Graph

#### Scenario: Graph 节点顺序执行
- **WHEN** R&D Workflow Graph 启动
- **THEN** 节点按 `init_workspace_node → planning_node → human_approval_node → development_node → delivery_node` 顺序执行，每个节点完成后流转至下一节点

### Requirement: init_workspace_node 克隆代码仓库并挂载沙盒
`init_workspace_node` SHALL 解析 `codeup_repositories` 列表，使用 `CODEUP_CLONE_URL_TEMPLATE` 执行 `git clone`，将仓库克隆到物理路径 `backend/.deer-flow/threads/{thread_id}/user-data/workspace/{repo_name}`，并创建 `feature/{requirement_id}` 隔离分支。

#### Scenario: 成功克隆单个仓库
- **WHEN** `codeup_repositories` 包含一个仓库名
- **THEN** `init_workspace_node` 克隆该仓库到对应物理目录，创建 feature 分支，在 Graph State 中记录克隆成功状态，前端 stream event 收到进度更新

#### Scenario: 克隆多个仓库
- **WHEN** `codeup_repositories` 包含多个仓库名
- **THEN** 逐一克隆每个仓库到各自独立子目录，Agent 后续可在 `/mnt/user-data/workspace/` 下多仓协作

#### Scenario: 克隆超时处理
- **WHEN** `git clone` 执行超时（默认 5 分钟）
- **THEN** 节点中断 Graph 执行，向前端发送错误 stream event，线程状态设为 error

### Requirement: planning_node 在沙盒中读取需求并生成技术方案
`planning_node` SHALL 以 `work_mode == "planning"` 条件触发，在沙盒中使用 lark-cli Skill（预装 `@larksuite/cli`）读取飞书需求关联文档和知识库，结合代码仓库现有架构，生成技术设计文档和可行性报告，写入沙盒 Workspace。

#### Scenario: 规划模式下执行 planning_node
- **WHEN** `work_mode == "planning"` 且 init_workspace_node 成功
- **THEN** planning_node 启动沙盒，注入 FEISHU_APP_ID/FEISHU_APP_SECRET 环境变量，Agent 调用 lark-cli 读取需求文档，在 `/mnt/user-data/workspace/` 生成 `design.md` 和 `tasks.md`

#### Scenario: 开发模式下跳过 planning_node
- **WHEN** `work_mode == "development"`
- **THEN** planning_node 被跳过（或快速通过），直接进入 human_approval_node

#### Scenario: 飞书凭据透传到沙盒
- **WHEN** planning_node 启动沙盒容器
- **THEN** SandboxProvider 将宿主机 `FEISHU_APP_ID`、`FEISHU_APP_SECRET`、`FEISHU_USER_ACCESS_TOKEN` 等环境变量注入容器，lark-cli 无需重新登录即可调用飞书 API

### Requirement: human_approval_node 触发 interrupt 等待人工审批
`human_approval_node` SHALL 调用 LangGraph `interrupt()` 挂起线程，前端收到 `status: "interrupted"` 后展示审批 UI，用户通过 Resume API 注入审批结果继续流程。

#### Scenario: 触发 interrupt
- **WHEN** planning_node 完成（或 work_mode=="development" 时直接到达此节点）
- **THEN** human_approval_node 调用 `interrupt()`，线程状态变为 interrupted，前端收到挂起信号并展示审批按钮

#### Scenario: 审批通过恢复执行
- **WHEN** 前端调用 Resume API 注入 `{"as_node": "human_approval_node", "values": {"approval": "approved"}}`
- **THEN** Graph 从 human_approval_node 恢复，继续执行 development_node

#### Scenario: 审批拒绝终止 Graph
- **WHEN** 前端调用 Resume API 注入 `{"as_node": "human_approval_node", "values": {"approval": "rejected"}}`
- **THEN** Graph 终止执行，线程状态设为 completed（已取消），前端显示拒绝提示

### Requirement: development_node 在沙盒中执行编码与自测
`development_node` SHALL 启动 Coding Agent，在沙盒中按 planning 产出的 tasks 逐步编码、执行 lint 和单元测试，每完成一个 Task 通过框架代劳执行 `git add . && git commit -m "Task N: <desc>"`。

#### Scenario: 逐 Task 增量提交
- **WHEN** development_node 中 Agent 完成一个子任务
- **THEN** 后端 Python 节点（非 Agent）执行 `git add . && git commit -m "Task N: <description>"`，commit 成功后继续下一 Task

#### Scenario: Agent 无 Git CLI 权限
- **WHEN** Agent 在沙盒中尝试执行任何 git 命令
- **THEN** 沙盒工具白名单屏蔽 git CLI，操作被拒绝；Git 提交由后端节点代劳

#### Scenario: 编码完成后进入交付阶段
- **WHEN** 所有 Task 编码和自测通过
- **THEN** development_node 完成，Graph 流转到 delivery_node
