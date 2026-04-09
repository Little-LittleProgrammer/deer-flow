#!/bin/sh
# Initialize lark-cli config from environment variables if provided.
# This avoids mounting ~/.lark-cli/config.json (which contains plaintext appsecret).
#
# Required env vars:
#   FEISHU_APP_ID     - Feishu/Lark App ID
#   FEISHU_APP_SECRET - Feishu/Lark App Secret (passed via stdin to avoid process list exposure)
# Optional:
#   LARK_BRAND        - feishu or lark (default: feishu)

if [ -n "$FEISHU_APP_ID" ] && [ -n "$FEISHU_APP_SECRET" ]; then
    echo "[entrypoint] Initializing lark-cli config for app: $FEISHU_APP_ID"
    printf '%s' "$FEISHU_APP_SECRET" \
        | lark-cli config init \
            --app-id "$FEISHU_APP_ID" \
            --app-secret-stdin \
            --brand "${LARK_BRAND:-feishu}" 2>&1 \
        && echo "[entrypoint] lark-cli config initialized." \
        || echo "[entrypoint] lark-cli config init failed (non-fatal)."
fi

exec "$@"
