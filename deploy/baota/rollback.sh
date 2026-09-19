#!/usr/bin/env bash
set -euo pipefail
APP_ROOT="${APP_ROOT:-/www/wwwroot/baijiarui-bi}"
TARGET="${1:-}"
[ -n "$TARGET" ] || { echo "用法: $0 15.0.0 [db_backup.sql]"; exit 2; }
if ! printf '%s' "$TARGET" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+$'; then
  echo "目标版本号不合法（必须是 X.Y.Z）：$TARGET" >&2
  exit 2
fi
TARGET_DIR="$APP_ROOT/releases/v$TARGET"
[ -d "$TARGET_DIR" ] || { echo "版本不存在: $TARGET_DIR"; exit 3; }
CURRENT="$(readlink -f "$APP_ROOT/current")"
FROM="$(cat "$CURRENT/VERSION" 2>/dev/null || true)"
export BJR_ENV_FILE="$APP_ROOT/shared/.env"
PY="$APP_ROOT/.venv/bin/python"
APP_ROOT="$APP_ROOT" bash "$CURRENT/deploy/baota/service.sh" stop
if command -v ss >/dev/null 2>&1 && ss -ltn 2>/dev/null | grep -q ':8000'; then
  echo "后端端口 8000 仍在监听，拒绝回滚" >&2
  exit 4
fi
if [ -n "${2:-}" ]; then "$PY" "$TARGET_DIR/scripts/release_tool.py" restore-db "$2"; fi
ln -sfn "$TARGET_DIR" "$APP_ROOT/current"
APP_ROOT="$APP_ROOT" bash "$TARGET_DIR/deploy/baota/service.sh" start
"$PY" "$TARGET_DIR/scripts/release_tool.py" record-release rollback success --from-version "$FROM" --backup-path "${2:-}" --note "manual rollback"
echo "已回滚：$FROM -> $TARGET"
