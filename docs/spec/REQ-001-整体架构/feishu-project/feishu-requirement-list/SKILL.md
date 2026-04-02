---
name: feishu-requirement-list
description: 获取飞书项目中的需求/工作项列表。通过飞书项目 API 获取租户访问令牌，然后获取指定视图下的工作项列表。当用户需要查看飞书项目中的需求、任务或工作项时使用。
---

# 获取飞书项目需求列表

本指南介绍了使用 shell 脚本，通过飞书项目 API 获取租户访问令牌和工作项列表。支持三种输出模式，便于 Claude 解析和用户交互。

## Claude 使用流程

**重要**: Claude 执行此 skill 时，必须按以下流程操作：

1. **获取租户访问令牌** - 调用 `get_tenant_access_token.sh`
2. **获取工作项列表** - 调用 `get_user_project.sh --list` 获取 JSON 格式列表
3. **用户选择** - 使用 `AskUserQuestion` 工具让用户选择工作项, 需要展示全部的数据
4. **获取详情** - 调用 `get_user_project.sh --detail <id>` 获取选中工作项详情

### Claude 执行示例

```bash
# 步骤 1: 获取令牌
TOKEN_RESPONSE=$(./scripts/get_tenant_access_token.sh "$APP_ID" "$APP_SECRET")
TOKEN=$(echo "$TOKEN_RESPONSE" | jq -r '.data.token')

# 步骤 2: 获取列表（--list 模式输出 JSON）
./scripts/get_user_project.sh --list "$TOKEN" "$USER_KEY" "$PROJECT_KEY" "$VIEW_ID"

# 步骤 3: 获取详情（用户选择后）
./scripts/get_user_project.sh --detail "12345" "$TOKEN" "$USER_KEY" "$PROJECT_KEY" "$VIEW_ID"
```

## 步骤

1. 获取飞书项目租户访问令牌，使用 `scripts/get_tenant_access_token.sh` 脚本
2. 获取工作项列表，使用 `scripts/get_user_project.sh` 脚本

## 脚本模式说明

### get_user_project.sh 支持三种模式

| 模式 | 参数 | 说明 | 输出格式 |
|------|------|------|----------|
| 列表模式 | `--list` | 输出工作项列表 | JSON |
| 详情模式 | `--detail <id>` | 输出指定工作项详情 | JSON |
| 交互模式 | 无模式参数 | 输出表格供命令行查看 | 文本表格 |

### --list 模式输出示例

```json
{
  "total": 10,
  "items": [
    {
      "id": 12345,
      "name": "用户登录功能优化",
      "type": "story",
      "project_key": "64ef2ed840972e4aef06d820",
      "status": "进行中"
    }
  ]
}
```

### --detail 模式输出示例

```json
{
  "id": 12345,
  "name": "用户登录功能优化",
  "type": "story",
  "project_key": "64ef2ed840972e4aef06d820",
  "simple_name": "myproject",
  "pattern": "Node",
  "current_nodes": [...],
  "fields": [...]
}
```

## 参数说明

### 飞书项目 API 参数

| 参数 | 说明 | 来源 |
| --- | --- | --- |
| `project_app_id` | 飞书项目应用 ID | 环境变量获取 |
| `project_app_secret` | 飞书项目应用密钥 | 环境变量获取 |
| `tenant_access_token` | 租户访问令牌 | 步骤 1 获取 |
| `feishu_project_user_key` | 飞书项目用户 key | 环境变量获取 |
| `project_key` | 项目空间 key | `64ef2ed840972e4aef06d820` |
| `view_id` | 视图 ID | `dXlxf-Fvg` |
| `page_num` | 页码（可选，默认 1） | 用户指定 |
| `page_size` | 每页数量（可选，默认 20，最大 100） | 用户指定 |

## 使用示例

### Claude 模式（推荐）

```bash
# 1. 获取租户访问令牌
./scripts/get_tenant_access_token.sh "$FEISHU_PROJECT_APP_ID" "$FEISHU_PROJECT_APP_SECRET"
# 返回: {"data": {"token": "p-xxxx-xxxx-xxxx", "expire_time": 7200}, ...}

# 2. 获取工作项列表（JSON 格式，供 Claude 解析）
./scripts/get_user_project.sh --list "$TENANT_ACCESS_TOKEN" "$FEISHU_PROJECT_USER_KEY" "$PROJECT_KEY" "$VIEW_ID"
# 返回: {"total": 10, "items": [...]}

# 3. 获取指定工作项详情
./scripts/get_user_project.sh --detail "12345" "$TENANT_ACCESS_TOKEN" "$FEISHU_PROJECT_USER_KEY" "$PROJECT_KEY" "$VIEW_ID"
```

### 从飞书项目 URL 获取参数

飞书项目视图 URL 格式：

```text
https://project.feishu.cn/[project_key]/view/[view_id]
```

例如 URL `https://project.feishu.cn/64ef2ed840972e4aef06d820/view/dXlxf-Fvg`：

- `project_key`: `64ef2ed840972e4aef06d820`
- `view_id`: `dXlxf-Fvg`

## 返回数据格式

```json
{
    "data": [
        {
            "id": 1,
            "name": "需求名称",
            "work_item_type_key": "story",
            "project_key": "60acd5610444ba031b50xxxx",
            "simple_name": "test",
            "template_id": 12345,
            "template": "control",
            "pattern": "Node",
            "current_nodes": [
                {
                    "id": "state_1",
                    "name": "node1",
                    "owners": ["701251455513382xxxx"]
                }
            ],
            "created_by": "700914671966122xxxx",
            "updated_by": "700914671966122xxxx",
            "created_at": 1633776613033,
            "updated_at": 1633776613033,
            "fields": [...]
        }
    ],
    "err_code": 0
}
```

### 关键字段说明

| 字段 | 说明 |
| --- | --- |
| `id` | 工作项 ID |
| `name` | 工作项名称 |
| `work_item_type_key` | 工作项类型（如 story, task, bug 等） |
| `project_key` | 项目空间 ID |
| `simple_name` | 空间域名 |
| `pattern` | 工作流模式（Node 节点流, State 状态流） |
| `current_nodes` | 当前进行中节点（仅节点流有值） |
| `created_by` | 创建者 userKey |
| `updated_by` | 更新者 userKey |
| `created_at` | 创建时间（毫秒时间戳） |
| `updated_at` | 更新时间（毫秒时间戳） |
| `fields` | 工作项自定义字段 |

## 依赖

- `jq` - JSON 解析工具

安装方式：

```bash
# macOS
brew install jq

# Ubuntu/Debian
apt install jq
```

## 注意事项

1. **令牌有效期**：租户访问令牌有效期为 2 小时，过期后需重新获取
2. **API 频率限制**：飞书 API 有调用频率限制，避免短时间内大量请求
3. **分页查询**：当工作项数量较多时，建议使用分页参数分批获取
4. **错误处理**：返回数据中的 `err_code` 为 0 表示成功，非 0 表示错误