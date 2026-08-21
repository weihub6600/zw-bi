#!/usr/bin/env bash
set -euo pipefail
APP_ROOT="${APP_ROOT:-/www/wwwroot/baijiarui-bi}"
export BJR_ENV_FILE="$APP_ROOT/shared/.env"
PY="$APP_ROOT/.venv/bin/python"
echo "=== 百嘉瑞BI production check ==="
readlink -f "$APP_ROOT/current" || true
"$PY" "$APP_ROOT/current/scripts/release_tool.py" db-ping
curl -fsS http://127.0.0.1:8000/api/health; echo
[ -f "$APP_ROOT/current/frontend-dist/index.html" ] && echo "frontend OK" || { echo "frontend missing"; exit 1; }
