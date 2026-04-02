## ADDED Requirements

### Requirement: delivery_node 创建 Codeup MR 并通知飞书
`delivery_node` SHALL 使用 Codeup OpenAPI（`x-yunxiao-token` 认证）将 feature 分支推送到远端，创建 Merge Request，并通过飞书机器人向工作群发送包含 MR 链接的通知消息卡片。

#### Scenario: 成功创建 MR
- **WHEN** development_node 所有编码与测试通过
- **THEN** delivery_node 调用 Codeup `CreateChangeRequest` API，以 Bot 全局凭据创建 MR，title 包含需求 ID 和标题，描述包含 Task 完成摘要

#### Scenario: 发送飞书通知
- **WHEN** MR 创建成功
- **THEN** 后端通过飞书 Bot 凭据向预配置的工作群发送消息卡片，卡片包含需求标题、MR 链接、分支名、commit 数量等信息

#### Scenario: Codeup API 调用失败重试
- **WHEN** Codeup API 调用失败（网络错误或 5xx）
- **THEN** delivery_node 最多重试 3 次，超过后将错误信息写入线程状态，前端展示失败提示，不重复创建 MR

### Requirement: delivery_node 使用框架代劳 Push 代码
delivery_node SHALL 在创建 MR 前由后端 Python 节点执行 `git push origin feature/{requirement_id}`，Agent 沙盒内无 push 权限。

#### Scenario: 框架代劳 Push
- **WHEN** delivery_node 开始执行
- **THEN** 后端 Python 节点使用 `CODEUP_CLONE_URL_TEMPLATE`（含 PAT）执行 `git push`，成功后调用 Codeup CreateMR API

#### Scenario: Push 冲突处理
- **WHEN** `git push` 遭遇远端冲突（分支已存在且有分歧）
- **THEN** 节点报错，线程状态设为 error，前端提示需人工处理冲突，不强制 push

### Requirement: Codeup OpenAPI 封装工具类
后端 SHALL 在 `deerflow/` 或 `app/` 下提供 `CodeupClient` 工具类，封装 `ListRepositories`、`GetRepository`、`CreateChangeRequest` 三个 Codeup OpenAPI，统一使用 `x-yunxiao-token` Header 认证。

#### Scenario: 获取仓库列表
- **WHEN** `CodeupClient.list_repositories()` 被调用
- **THEN** 发送 HTTP GET 到 Codeup API endpoint，返回仓库列表数据结构

#### Scenario: 创建 MR
- **WHEN** `CodeupClient.create_change_request(repo_id, source_branch, target_branch, title, description)` 被调用
- **THEN** 发送 HTTP POST 到 Codeup CreateChangeRequest endpoint，返回 MR URL 和 MR ID

#### Scenario: Token 未配置
- **WHEN** `CODEUP_TOKEN` 环境变量未设置
- **THEN** CodeupClient 初始化时抛出 `ConfigurationError`，明确提示缺少 `CODEUP_TOKEN`

### Requirement: 配置新增 Codeup 和飞书凭据引用
`config.yaml` SHALL 新增 `codeup.token`（引用 `$CODEUP_TOKEN`）和 `codeup.clone_url_template`（引用 `$CODEUP_CLONE_URL_TEMPLATE`）配置项，`config.example.yaml` 同步更新示例值。

#### Scenario: 配置从环境变量读取
- **WHEN** DeerFlow 服务启动
- **THEN** `get_app_config()` 能读取 `codeup.token` 和 `codeup.clone_url_template`，值以 `$` 前缀标识时自动解析为对应环境变量值

#### Scenario: 缺少配置时给出明确错误
- **WHEN** `CODEUP_TOKEN` 或 `CODEUP_CLONE_URL_TEMPLATE` 环境变量未设置
- **THEN** 相关节点在执行前进行前置校验，返回明确的配置缺失错误信息
