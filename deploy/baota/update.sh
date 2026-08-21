#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
if [ -f "$SCRIPT_DIR/VERSION" ]; then SOURCE_DIR="$SCRIPT_DIR"; else SOURCE_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"; fi
APP_ROOT="${1:-/www/wwwroot/baijiarui-bi}"
NEW_VERSION="$(cat "$SOURCE_DIR/VERSION")"
NEW_RELEASE="$APP_ROOT/releases/v$NEW_VERSION"
CURRENT_LINK="$APP_ROOT/current"
OLD_RELEASE="$(readlink -f "$CURRENT_LINK" 2>/dev/null || true)"
OLD_VERSION=""
[ -n "$OLD_RELEASE" ] && [ -f "$OLD_RELEASE/VERSION" ] && OLD_VERSION="$(cat "$OLD_RELEASE/VERSION")"
export BJR_ENV_FILE="$APP_ROOT/shared/.env"
PY="$APP_ROOT/.venv/bin/python"
STAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP="$APP_ROOT/shared/backups/db_${OLD_VERSION:-unknown}_before_${NEW_VERSION}_$STAMP.sql"

echo "=== 百嘉瑞BI 升级 ${OLD_VERSION:-unknown} -> $NEW_VERSION ==="
[ -f "$APP_ROOT/shared/.env" ] || { echo "缺少 shared/.env"; exit 2; }
[ -x "$PY" ] || { echo "缺少共享 Python venv：$PY"; exit 3; }
[ -f "$SOURCE_DIR/frontend-dist/index.html" ] || { echo "升级包缺少 frontend-dist/index.html；请从 Windows 发布脚本生成生产包。"; exit 4; }
"$PY" "$SOURCE_DIR/scripts/release_tool.py" verify
"$PY" "$SOURCE_DIR/scripts/release_tool.py" db-ping
mkdir -p "$APP_ROOT/shared/backups" "$APP_ROOT/releases"
"$PY" "$SOURCE_DIR/scripts/release_tool.py" backup-db "$BACKUP"
APP_ROOT="$APP_ROOT" bash "$OLD_RELEASE/deploy/baota/service.sh" stop || true
rm -rf "$NEW_RELEASE"; mkdir -p "$NEW_RELEASE"
for x in backend frontend-dist templates deploy scripts VERSION manifest.json; do [ -e "$SOURCE_DIR/$x" ] && cp -a "$SOURCE_DIR/$x" "$NEW_RELEASE/"; done

rollback(){
  echo "升级失败，开始自动回滚..."
  [ -n "$OLD_RELEASE" ] && ln -sfn "$OLD_RELEASE" "$CURRENT_LINK"
  "$PY" "$OLD_RELEASE/scripts/release_tool.py" restore-db "$BACKUP" || true
  APP_ROOT="$APP_ROOT" bash "$OLD_RELEASE/deploy/baota/service.sh" restart || true
  "$PY" "$OLD_RELEASE/scripts/release_tool.py" record-release rollback success --from-version "$NEW_VERSION" --backup-path "$BACKUP" --note "automatic rollback after failed upgrade" || true
}
trap rollback ERR

"$PY" -m pip install -r "$NEW_RELEASE/backend/requirements.txt"
"$PY" "$NEW_RELEASE/scripts/release_tool.py" migrate
ln -sfn "$NEW_RELEASE" "$CURRENT_LINK"
APP_ROOT="$APP_ROOT" bash "$NEW_RELEASE/deploy/baota/service.sh" restart
sleep 3
HEALTH="$(curl -fsS http://127.0.0.1:8000/api/health)"
echo "$HEALTH"
echo "$HEALTH" | grep -q '"ok":true\|"ok": true'
echo "$HEALTH" | grep -q "$NEW_VERSION"
trap - ERR
"$PY" "$NEW_RELEASE/scripts/release_tool.py" record-release upgrade success --from-version "$OLD_VERSION" --backup-path "$BACKUP" --note "upgrade complete"
echo "升级成功：$OLD_VERSION -> $NEW_VERSION"
echo "数据库备份：$BACKUP"
