#!/usr/bin/env bash
set -euo pipefail

# 获取飞书项目租户访问令牌

FEISHU_PROJECT_APP_ID="$1"
FEISHU_PROJECT_APP_SECRET="$2"

if [[ -z "${1:-}" || -z "${2:-}" ]]; then
  echo "错误: 缺少必需的参数" >&2
  echo "用法: $(basename "$0") <project_app_id> <project_app_secret>" >&2
  echo "如果缺少 project_app_id 或 project_app_secret: https://x0sgcptncj.feishu.cn/wiki/YPElwh0aPiokTtkEigacc7n6nkg#share-Xt6Adc9tIoRz3xxK0o8cyF4Unxd" >&2
  exit 1
fi

curl -X POST 'https://project.feishu.cn/open_api/authen/plugin_token' \
  -H 'Content-Type: application/json' \
  -d "$(cat <<EOF
{
  "plugin_id": "${FEISHU_PROJECT_APP_ID}",
  "plugin_secret": "${FEISHU_PROJECT_APP_SECRET}",
  "type": 0
}
EOF
)"

# 返回数据格式
# {
#     "data": {
#         "expire_time": 7200,
#         "token": "p-49257489-f7d7-4cd6-b34f-98c6b81d****"
#     },
#     "error": {
#         "code": 0,
#         "msg": "success"
#     }
# }
