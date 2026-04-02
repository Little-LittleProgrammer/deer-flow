## ADDED Requirements

### Requirement: 后端通过 FeishuProjectMcp 拉取飞书需求列表
后端 Gateway SHALL 提供 `GET /api/lark/requirements` 接口，通过 FeishuProjectMcp SSE 模式连接飞书项目，返回当前迭代的需求工作项列表。

#### Scenario: 成功拉取需求列表
- **WHEN** 前端调用 `GET /api/lark/requirements`
- **THEN** 后端通过 FeishuProjectMcp 工具查询飞书项目工作项，返回包含 `id`、`title`、`status`、`type`、`assignee`、`doc_url` 字段的 JSON 数组，HTTP 200

#### Scenario: FeishuProjectMcp 连接失败时返回错误
- **WHEN** FeishuProjectMcp SSE 连接超时或请求失败（重试 3 次后仍失败）
- **THEN** 后端返回 HTTP 503，响应体包含 `{"error": "feishu_mcp_unavailable", "message": "..."}`

#### Scenario: 按迭代筛选需求
- **WHEN** 前端调用 `GET /api/lark/requirements?iteration=<iteration_id>`
- **THEN** 后端将 iteration_id 作为过滤条件传入 MCP 工具，仅返回该迭代下的工作项

### Requirement: 后端通过 Codeup OpenAPI 获取仓库列表
后端 Gateway SHALL 提供 `GET /api/codeup/repositories` 接口，使用 `CODEUP_TOKEN` 调用 Codeup OpenAPI 返回用户有权访问的代码仓库列表。

#### Scenario: 成功获取仓库列表
- **WHEN** 前端调用 `GET /api/codeup/repositories`
- **THEN** 后端使用 `x-yunxiao-token` 请求 Codeup API，返回包含 `id`、`name`、`full_name`、`description` 字段的仓库 JSON 数组，HTTP 200

#### Scenario: Codeup Token 未配置
- **WHEN** 环境变量 `CODEUP_TOKEN` 未设置
- **THEN** 接口返回 HTTP 503，响应体包含 `{"error": "codeup_not_configured"}`

### Requirement: FeishuProjectMcp 在 extensions_config.json 中配置
`extensions_config.json` SHALL 包含 FeishuProjectMcp 的 SSE 类型 MCP Server 配置，Gateway 启动时自动加载。

#### Scenario: 配置存在且格式正确
- **WHEN** DeerFlow 服务启动
- **THEN** Gateway 能够识别并连接 `feishu-project-mcp` SSE server，连接状态在 `/api/mcp` 接口中可查询

#### Scenario: 飞书凭据通过环境变量注入
- **WHEN** FeishuProjectMcp 服务启动
- **THEN** 服务使用 `FEISHU_APP_ID`、`FEISHU_APP_SECRET` 环境变量进行认证，不在配置文件中硬编码凭据
