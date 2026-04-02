#!/usr/bin/env bash
set -euo pipefail

# 获取用户有权限的项目列表
# API 文档: https://x0sgcptncj.feishu.cn/wiki/YPElwh0aPiokTtkEigacc7n6nkg#share-Xt6Adc9tIoRz3xxK0o8cyF4Unxd
#
# 使用模式:
# 1. --list: 输出工作项列表 JSON（供 Claude 解析）
# 2. --detail <work_item_id>: 输出指定工作项详情 JSON
# 3. 默认（无模式参数）: 输出简化列表供用户选择

# 检查依赖
command -v jq >/dev/null 2>&1 || {
  echo "错误: 需要 jq 工具来解析 JSON 数据" >&2
  echo "请安装: brew install jq 或 apt install jq" >&2
  exit 1
}

# 解析模式参数
MODE="interactive"
WORK_ITEM_ID=""

while [[ $# -gt 0 ]]; do
  case $1 in
    --list)
      MODE="list"
      shift
      ;;
    --detail)
      MODE="detail"
      WORK_ITEM_ID="$2"
      shift 2
      ;;
    *)
      # 非模式参数，保持原位置
      break
      ;;
  esac
done

# 参数说明（位置参数）
TENANT_ACCESS_TOKEN="${1:-}"
FEISHU_PROJECT_USER_KEY="${2:-}"
PROJECT_KEY="${3:-}"
VIEW_ID="${4:-}"
PAGE_NUM="${5:-1}"
PAGE_SIZE="${6:-50}"

# 参数校验
if [[ -z "${TENANT_ACCESS_TOKEN}" ]]; then
  echo '{"error": "缺少必需参数 tenant_access_token"}' >&2
  exit 1
fi

if [[ -z "${FEISHU_PROJECT_USER_KEY}" ]]; then
  echo '{"error": "缺少必需参数 feishu_project_user_key"}' >&2
  exit 1
fi

if [[ -z "${PROJECT_KEY}" ]]; then
  echo '{"error": "缺少必需参数 project_key"}' >&2
  exit 1
fi

if [[ -z "${VIEW_ID}" ]]; then
  echo '{"error": "缺少必需参数 view_id"}' >&2
  exit 1
fi

# 验证分页参数
if ! [[ "${PAGE_NUM}" =~ ^[0-9]+$ ]] || [[ "${PAGE_NUM}" -lt 1 ]]; then
  echo '{"error": "page_num 必须是大于 0 的整数"}' >&2
  exit 1
fi

if ! [[ "${PAGE_SIZE}" =~ ^[0-9]+$ ]] || [[ "${PAGE_SIZE}" -lt 1 ]] || [[ "${PAGE_SIZE}" -gt 100 ]]; then
  echo '{"error": "page_size 必须是 1-100 之间的整数"}' >&2
  exit 1
fi

# ============================================================
# 调用 API 获取工作项列表
# ============================================================
RESPONSE=$(curl -s -X POST "https://project.feishu.cn/open_api/${PROJECT_KEY}/view/${VIEW_ID}" \
  -H 'Content-Type: application/json' \
  -H "X-PLUGIN-TOKEN: ${TENANT_ACCESS_TOKEN}" \
  -H "X-USER-KEY: ${FEISHU_PROJECT_USER_KEY}" \
  -d "$(cat <<EOF
{
  "page_num": ${PAGE_NUM},
  "page_size": ${PAGE_SIZE}
}
EOF
)")

# 检查 API 响应
ERR_CODE=$(echo "$RESPONSE" | jq -r '.err_code // 0')
if [[ "$ERR_CODE" != "0" ]]; then
  ERR_MSG=$(echo "$RESPONSE" | jq -r '.err_msg // "未知错误"')
  echo "错误: API 调用失败 (err_code: $ERR_CODE)" >&2
  echo "错误信息: $ERR_MSG" >&2
  exit 1
fi

TOTAL_COUNT=$(echo "$RESPONSE" | jq -r '.data | length')

if [[ "$TOTAL_COUNT" -eq 0 ]]; then
  echo '{"error": "当前视图下没有工作项", "data": []}'
  exit 0
fi

# ============================================================
# 根据模式输出不同格式
# ============================================================
case "$MODE" in
  "list")
    # 输出列表 JSON（供 Claude 解析和让用户选择）
    echo "$RESPONSE" | jq '{
      total: (.data | length),
      items: [.data[] | {
        id: .id,
        name: .name,
        type: .work_item_type_key,
        project_key: .project_key,
        status: ((.fields[]? | select(.field_key == "status") | .value) // "unknown")
      }]
    }'
    ;;

  "detail")
    # 输出指定工作项的详细信息
    if [[ -z "$WORK_ITEM_ID" ]]; then
      echo '{"error": "缺少 work_item_id 参数"}' >&2
      exit 1
    fi

    DETAIL=$(echo "$RESPONSE" | jq --arg id "$WORK_ITEM_ID" '.data[] | select(.id == ($id | tonumber))')
    if [[ -z "$DETAIL" ]]; then
      echo "{\"error\": \"未找到工作项 ID: $WORK_ITEM_ID\"}" >&2
      exit 1
    fi

    # 输出详细信息
    echo "$DETAIL" | jq '{
      id: .id,
      name: .name,
      type: .work_item_type_key,
      project_key: .project_key,
      simple_name: .simple_name,
      pattern: .pattern,
      current_nodes: .current_nodes,
      created_by: .created_by,
      updated_by: .updated_by,
      created_at: .created_at,
      updated_at: .updated_at,
      fields: .fields
    }'
    ;;

  "interactive")
    # 交互模式：输出简化的选择列表
    echo "============================================"
    echo "获取到 $TOTAL_COUNT 个工作项"
    echo "============================================"
    echo ""
    echo "工作项列表:"
    echo "--------------------------------------------"
    printf "%-4s | %-12s | %-40s | %-10s\n" "序号" "ID" "名称" "类型"
    echo "--------------------------------------------"

    idx=1
    while IFS= read -r item; do
      ITEM_ID=$(echo "$item" | jq -r '.id')
      ITEM_NAME=$(echo "$item" | jq -r '.name')
      ITEM_TYPE=$(echo "$item" | jq -r '.work_item_type_key')

      # 截断过长的名称
      DISPLAY_NAME="${ITEM_NAME}"
      if [[ ${#DISPLAY_NAME} -gt 38 ]]; then
        DISPLAY_NAME="${DISPLAY_NAME:0:35}..."
      fi

      printf "%-4s | %-12s | %-40s | %-10s\n" "$idx" "$ITEM_ID" "$DISPLAY_NAME" "$ITEM_TYPE"
      ((idx++))
    done < <(echo "$RESPONSE" | jq -c '.data[]')

    echo "--------------------------------------------"
    echo ""
    echo "提示: 使用 --list 参数获取 JSON 列表，使用 --detail <id> 获取详情"
    ;;
esac

# ============================================================
# 返回数据格式说明（供参考）
# ============================================================
# {
#     "data": [
#         {
#             "id": 1,                              // 工作项 ID
#             "name": "item1",                      // 工作项名称
#             "work_item_type_key": "story",        // 工作项类型
#             "project_key": "60acd5610444ba031b50xxxx",  // 空间 ID
#             "simple_name": "test",                // 空间域名
#             "template_id": 12345,                 // 使用的模板 ID
#             "template": "control",                // 流程类型
#             "pattern": "Node",                    // 工作流模式; Node 节点流, State 状态流
#             "current_nodes": [                    // 当前进行中节点(仅节点流有值)
#                 {
#                     "id": "state_1",              // 节点 ID
#                     "name": "node1",              // 节点名称
#                     "owners": [...]               // 节点负责人 user_key 列表
#                 }
#             ],
#             "created_by": "700914671966122xxxx",  // 创建者 userKey
#             "updated_by": "700914671966122xxxx",  // 更新者 userKey
#             "created_at": 1633776613033,          // 创建时间(毫秒时间戳)
#             "updated_at": 1633776613033,          // 更新时间(毫秒时间戳)
#             "fields": [...]                       // 工作项字段
#         }
#     ],
#     "err_code": 0
# }