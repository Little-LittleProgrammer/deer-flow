# Codeup 配置指南

## 环境变量配置

### 必需变量

| 变量名 | 说明 | 示例 |
|--------|------|------|
| `CODEUP_TOKEN` | Personal Access Token | `your-token-here` |
| `CODEUP_DOMAIN` | API 域名 | `devops.aliyun.com` |

### 可选变量

| 变量名 | 说明 | 适用场景 |
|--------|------|----------|
| `CODEUP_ORGANIZATION_ID` | 组织 ID | 企业版 Codeup |

## 获取 Personal Access Token

1. 登录 Codeup 控制台
2. 进入「个人设置」→「个人访问令牌」
3. 点击「新建令牌」
4. 选择所需权限范围：
   - `read_repository` - 读取仓库
   - `write_repository` - 写入仓库
5. 生成并保存令牌

## Token 权限要求

执行本 skill 的克隆操作需要以下权限：
- **读取仓库**：克隆代码
- **写入仓库**：推送分支

创建 MR 需要额外权限：
- **创建变更请求**：提交 Merge Request

## 配置方式

### 方式一：环境变量

```bash
export CODEUP_TOKEN="your-token"
export CODEUP_DOMAIN="devops.aliyun.com"
```

### 方式二：config.yaml

在 DeerFlow 配置文件中设置：

```yaml
codeup:
  token: "$CODEUP_TOKEN"  # 引用环境变量
  domain: "devops.aliyun.com"
```

## Git 认证 URL 格式

克隆仓库时使用 OAuth2 token 认证：

```bash
# URL 格式
git clone https://oauth2:${CODEUP_TOKEN}@codeup.aliyun.com/${CODEUP_ORG}/${REPO_PATH}.git

# 示例
git clone https://oauth2:abc123@codeup.aliyun.com/qimao/myproject.git
```

## API 调用格式

### 标准版 API

```bash
POST https://${CODEUP_DOMAIN}/oapi/v1/codeup/repositories/${repo_path}/changeRequests
```

### 企业版 API（需要 organization_id）

```bash
POST https://${CODEUP_DOMAIN}/oapi/v1/codeup/organizations/${org_id}/repositories/${repo_path}/changeRequests
```

## 常见问题

### Q: 克隆失败提示 "Authentication failed"

**原因**：Token 无效或权限不足

**解决**：
1. 检查 Token 是否正确配置
2. 确认 Token 具有 `read_repository` 权限
3. 验证 Token 未过期

### Q: 推送失败提示 "Permission denied"

**原因**：Token 缺少写入权限

**解决**：重新生成 Token 并添加 `write_repository` 权限

### Q: 创建 MR 失败

**原因**：Token 缺少变更请求权限或 API 参数错误

**解决**：
1. 检查 Token 权限
2. 确认分支名称正确
3. 验证仓库路径格式

### Q: 企业版 API 返回 404

**原因**：缺少 `CODEUP_ORGANIZATION_ID`

**解决**：在环境变量中配置组织 ID

## 安全注意事项

1. **不要在代码中硬编码 Token**
2. **使用环境变量或配置文件存储敏感信息**
3. **定期轮换 Token**
4. **为不同用途创建不同 Token**（开发/CI/自动化）
5. **Token 泄露后立即撤销并重新生成**