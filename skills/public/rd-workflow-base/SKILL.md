---
name: rd-workflow-base
description: This skill should be used when the user asks to "开始研发工作流", "初始化需求工作区", "克隆需求仓库", "准备开发环境", "克隆代码仓库", "创建功能分支", or provides a requirement ID (format: "REQ-12345") with repository URLs. Provides R&D workflow initialization: clone Codeup repositories, fetch Feishu requirement documents, and setup feature branches.
allowed-tools: bash, read_file, write_file, str_replace, ask_clarification
---

# R&D Workflow Base - 初始化阶段

## 概述

为研发需求提供工作流初始化能力：解析任务参数、克隆代码仓库、获取飞书需求文档、创建功能分支。

## 触发场景

当用户提供以下信息时触发：
- 需求 ID（如 `REQ-12345`）
- 工作模式（`check`/`planning`/`development`）
- Codeup 仓库 URL 列表

## 工作流

### Step 1: 解析任务参数

从用户消息中提取：
- `requirement_id`：需求 ID
- `work_mode`：工作模式
- `repositories`：仓库 Web URL 列表

验证环境变量：
```bash
echo "CODEUP_TOKEN=$(printenv CODEUP_TOKEN | head -c 8)..."
```

若缺失配置，停止并提示：
> ⚠️ 缺少 Codeup 配置，请设置 CODEUP_TOKEN、CODEUP_DOMAIN 环境变量。

### Step 2: 克隆仓库

对每个仓库执行克隆并创建分支：

克隆命令格式, 严格按照下面的格式：
```bash
git clone https://oauth2:${CODEUP_TOKEN}@codeup.aliyun.com/${CODEUP_ORG}/${REPO_PATH}.git
```

克隆完成后切换到 `feature/${requirement_id}` 分支。

工作区路径：`/mnt/user-data/workspace/<repo_name>`

若克隆失败，记录错误并继续处理其他仓库；所有仓库均失败时停止流程。

### Step 3: 获取需求文档

1. 使用 `FeishuProjectMcp` 工具的 `get_workitem_brief` 获取需求详情，进而获取需求文档链接
2. 使用 `lark-doc` skill 读取文档内容, 如果需要认证，返回认证链接让用户打开
3. 保存到本地：`/mnt/user-data/workspace/docs/${requirement_id}.md`


## 配置要求

必须配置以下环境变量：
- `CODEUP_TOKEN` - Codeup Personal Access Token

可选：
- `CODEUP_ORGANIZATION_ID` - 企业版组织 ID

## 详细配置指南

For Codeup authentication setup and API details, refer to `references/codeup-setup.md`.


╰─ 