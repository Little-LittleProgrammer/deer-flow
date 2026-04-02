## 1. 配置与基础设施

- [x] 1.1 在 `config.yaml` 和 `config.example.yaml` 新增 `codeup.token`（`$CODEUP_TOKEN`）和 `codeup.clone_url_template`（`$CODEUP_CLONE_URL_TEMPLATE`）配置项
- [x] 1.2 在 `extensions_config.json` 新增 `feishu-project-mcp` SSE 类型 MCP Server 配置（含 FEISHU_APP_ID/SECRET 环境变量引用）
- [x] 1.3 在 `deerflow/config/` 中扩展 AppConfig，增加 `codeup` 配置段并支持环境变量解析
- [x] 1.4 确认 `config_version` 版本号递增，运行 `make config-upgrade` 验证合并流程

## 2. Codeup 客户端封装

- [x] 2.1 在 `deerflow/` 下创建 `codeup/client.py`，封装 `CodeupClient` 类，支持 `x-yunxiao-token` Header 认证
- [x] 2.2 实现 `CodeupClient.list_repositories()` 方法，调用 Codeup `ListRepositories` OpenAPI
- [x] 2.3 实现 `CodeupClient.get_repository(repo_id)` 方法，调用 Codeup `GetRepository` OpenAPI
- [x] 2.4 实现 `CodeupClient.create_change_request(repo_id, source_branch, target_branch, title, description)` 方法，调用 `CreateChangeRequest` OpenAPI
- [x] 2.5 为 `CodeupClient` 编写单元测试 `backend/tests/test_codeup_client.py`，覆盖正常路径和 Token 未配置异常

## 3. Gateway API 路由

- [x] 3.1 在 `app/gateway/routers/` 新增 `lark.py`，实现 `GET /api/lark/requirements` 路由，通过 FeishuProjectMcp 工具拉取需求列表
- [x] 3.2 在 `app/gateway/routers/` 新增 `codeup.py`，实现 `GET /api/codeup/repositories` 路由，调用 CodeupClient
- [x] 3.3 在 `app/gateway/app.py` 中注册上述两个新路由
- [x] 3.4 为两个路由编写集成测试，覆盖成功返回和外部服务不可用（503）场景

## 4. R&D Workflow LangGraph Graph

- [x] 4.1 在 `deerflow/agents/` 下新建 `rd_workflow/` 目录，创建 `graph.py` 定义 R&D Workflow StateGraph
- [x] 4.2 实现 `init_workspace_node`：解析 `codeup_repositories`，执行 `git clone`（超时 5 分钟），创建 `feature/{requirement_id}` 分支，更新 Graph State
- [x] 4.3 实现 `planning_node`：根据 `work_mode` 判断是否启动沙盒 Coding Agent，注入飞书凭据环境变量，Agent 调用 lark-cli 读取需求文档并生成技术方案
- [x] 4.4 实现 `human_approval_node`：调用 `interrupt()` 挂起线程，处理 Resume payload 中的 `approval` 字段（approved/rejected）
- [x] 4.5 实现 `development_node`：启动 Coding Agent 执行逐 Task 编码和自测，每 Task 完成后由框架执行 `git add . && git commit`
- [x] 4.6 实现 `delivery_node`：框架执行 `git push`，调用 CodeupClient 创建 MR，通过飞书 Bot 发送通知消息卡片
- [x] 4.7 在 LangGraph Router 中注册 R&D Workflow Graph，通过 metadata `type == "lark_requirement_task"` 路由触发
- [x] 4.8 为 Graph 节点编写单元测试 `backend/tests/test_rd_workflow_graph.py`

## 5. 沙盒增强：飞书凭据透传

- [x] 5.1 在 `deerflow/sandbox/` 的 SandboxProvider 中，新增将宿主机 `FEISHU_APP_ID`、`FEISHU_APP_SECRET`、`FEISHU_USER_ACCESS_TOKEN` 透传注入沙盒容器的能力
- [x] 5.2 在沙盒工具白名单中屏蔽 `git` CLI 工具（包括 git commit、git push 等），确保 Agent 无法直接操作 Git
- [x] 5.3 编写测试验证凭据透传行为和 Git CLI 屏蔽逻辑

## 6. 前端：研发需求页面

- [x] 6.1 在 `frontend/src/app/` 下新建 `requirements/page.tsx`，注册 `/requirements` 路由
- [x] 6.2 在左侧导航栏 `NavigationSidebar` 组件中新增"需求"导航入口（图标 + 文字）
- [x] 6.3 实现需求列表组件 `RequirementsListView`：调用 `GET /api/lark/requirements`，渲染需求卡片，支持状态筛选和关键词搜索（前端本地过滤）
- [x] 6.4 实现 `RequirementCard` 组件：展示标题、状态 badge、类型标签、负责人，包含"派发给 Agent"按钮
- [x] 6.5 在前端 `core/api/` 中添加 `fetchRequirements()` 和 `fetchCodeupRepositories()` API 函数

## 7. 前端：派发弹窗组件

- [x] 7.1 实现 `DispatchDialog` 组件：包含工作模式切换（规划/开发）、Codeup 仓库多选列表、Agent 选择下拉、启动/取消按钮
- [x] 7.2 弹窗打开时调用 `GET /api/codeup/repositories` 加载仓库列表，展示加载态和错误态
- [x] 7.3 实现"启动"按钮逻辑：调用 `POST /api/threads` 注入 `lark_requirement_task` metadata，成功后跳转到 Thread 会话页面
- [x] 7.4 实现工作模式切换时说明文案联动更新

## 8. 前端：研发工作流审批交互

- [x] 8.1 在 Thread 会话页面，识别 `thread.interrupt?.value?.type === "human_approval"` 的状态
- [x] 8.2 渲染审批操作区（`HumanApprovalBanner`）：展示"审批通过"和"拒绝"按钮，展示技术方案摘要
- [x] 8.3 实现"审批通过"逻辑：调用 `thread.submit({ command: { resume: "approved" } })` 恢复执行
- [x] 8.4 实现"拒绝"逻辑：调用 `thread.submit({ command: { resume: "rejected" } })`，后端展示拒绝消息

## 9. 集成验证与文档

- [ ] 9.1 本地端到端 Happy Path 冒烟测试：从需求列表拉取 → 规划模式派发 → 审批通过 → 开发完成 → MR 创建 → 飞书通知
- [x] 9.2 运行 `cd backend && make lint && make test` 确保后端全量测试通过
- [x] 9.3 运行 `cd frontend && pnpm lint && pnpm typecheck` 确保前端无 lint/类型错误
- [x] 9.4 更新 `README.md`，新增飞书和 Codeup 集成的环境变量配置说明
- [x] 9.5 更新 `backend/CLAUDE.md`，说明 R&D Workflow Graph 的架构位置和节点职责
