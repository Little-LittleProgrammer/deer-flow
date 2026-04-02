## ADDED Requirements

### Requirement: 前端新增"研发需求"独立页面
前端 SHALL 在 `/requirements` 路由新增独立的研发需求页面，在左侧导航栏中以"需求"入口展示，与现有"会话"页面并列。

#### Scenario: 访问需求页面
- **WHEN** 用户点击左侧导航"需求"图标或直接访问 `/requirements`
- **THEN** 页面渲染需求列表视图，默认状态显示加载提示或空状态占位，不影响现有页面路由

#### Scenario: 刷新加载需求列表
- **WHEN** 用户点击页面顶部"刷新列表"按钮
- **THEN** 前端调用 `GET /api/lark/requirements`，加载期间显示骨架屏，成功后渲染需求卡片列表；失败时显示错误提示 Toast

### Requirement: 需求卡片展示需求基本信息
需求列表中每张卡片 SHALL 显示：需求标题、当前状态（badge）、类型、负责人姓名，以及"派发给 Agent"操作按钮。

#### Scenario: 卡片正常渲染
- **WHEN** 需求数据加载完成
- **THEN** 每条需求以卡片形式呈现，包含标题、状态 badge、类型标签、负责人信息和"派发给 Agent"按钮

#### Scenario: 需求列表支持状态筛选和搜索
- **WHEN** 用户在筛选下拉选择特定状态，或在搜索框输入关键词
- **THEN** 列表实时过滤，仅展示匹配的需求卡片（前端本地过滤）

### Requirement: 派发弹窗支持工作模式与仓库选择
点击"派发给 Agent"后，SHALL 弹出 Dispatch Dialog，包含工作模式切换（规划/开发）、Codeup 仓库多选列表、Agent 选择下拉框，以及"启动"和"取消"按钮。

#### Scenario: 打开派发弹窗
- **WHEN** 用户点击某需求卡片上的"派发给 Agent"按钮
- **THEN** 弹出 Dispatch Dialog，自动调用 `GET /api/codeup/repositories` 加载仓库列表，工作模式默认选中"规划与反向评估"

#### Scenario: 规划模式说明文案切换
- **WHEN** 用户切换工作模式选项
- **THEN** 弹窗中的模式说明文案相应更新，清晰描述该模式下 Agent 的行为

#### Scenario: 仓库多选
- **WHEN** 用户在仓库列表勾选/取消勾选多个仓库
- **THEN** 选中状态实时更新，至少需选中一个仓库才能激活"启动"按钮

#### Scenario: 启动 Agent 线程
- **WHEN** 用户选好模式和仓库后点击"启动智能规划"或"启动开发"
- **THEN** 前端调用 `POST /api/threads`，请求体 metadata 包含 `type: "lark_requirement_task"`、`lark_requirement_id`、`work_mode`、`codeup_repositories` 字段；成功后关闭弹窗并跳转到对应 Thread 会话页面

#### Scenario: 启动失败提示
- **WHEN** `POST /api/threads` 请求失败
- **THEN** 弹窗保持打开，显示错误提示，不重复创建线程

### Requirement: 前端处理研发工作流线程的 interrupted 状态
当研发工作流线程进入 `human_approval_node` 时，前端 SHALL 在会话界面展示审批操作按钮，允许用户点击 Approve 继续流程。

#### Scenario: 显示审批操作区
- **WHEN** 线程状态变为 `interrupted` 且 interrupt 原因为 `human_approval_node`
- **THEN** 前端在消息流末尾渲染"审批通过"和"拒绝"按钮，并展示 Agent 生成的技术方案摘要

#### Scenario: 用户审批通过
- **WHEN** 用户点击"审批通过"按钮
- **THEN** 前端调用 Resume 接口（`POST /threads/{thread_id}/runs`），注入 payload `{"as_node": "human_approval_node", "values": {"approval": "approved"}}`，线程恢复执行
