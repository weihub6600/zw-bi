#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
if [ -f "$SCRIPT_DIR/VERSION" ]; then SOURCE_DIR="$SCRIPT_DIR"; else SOURCE_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"; fi
APP_ROOT="${1:-/www/wwwroot/baijiarui-bi}"
NEW_VERSION="$(cat "$SOURCE_DIR/VERSION")"
NEW_RELEASE="$APP_ROOT/releases/v$NEW_VERSION"
CURRENT_LINK="$APP_ROOT/current"
MAINTENANCE_FILE="$APP_ROOT/shared/run/maintenance"

if ! printf '%s' "$NEW_VERSION" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+$'; then
  echo "版本号不合法（必须是 X.Y.Z）：$NEW_VERSION" >&2
  exit 5
fi
case "$APP_ROOT" in
  /*) ;;
  *) echo "APP_ROOT 必须是绝对路径：$APP_ROOT" >&2; exit 5 ;;
esac
case "$NEW_RELEASE" in
  "$APP_ROOT/releases/v"*) ;;
  *) echo "发布目录越界：$NEW_RELEASE" >&2; exit 5 ;;
esac
[ "$NEW_RELEASE" != "$APP_ROOT" ] && [ "$NEW_RELEASE" != "$APP_ROOT/releases" ] || { echo "拒绝使用根目录作为发布目录" >&2; exit 5; }

if [ -e "$NEW_RELEASE" ] || [ -L "$NEW_RELEASE" ]; then
  echo "目标版本目录已存在，拒绝覆盖：$NEW_RELEASE" >&2
  exit 6
fi
if [ -L "$CURRENT_LINK" ] && [ "$(readlink -f "$CURRENT_LINK")" = "$NEW_RELEASE" ]; then
  echo "目标版本已经是 current，拒绝重复升级：$NEW_RELEASE" >&2
  exit 6
fi

OLD_RELEASE="$(readlink -f "$CURRENT_LINK" 2>/dev/null || true)"
OLD_VERSION=""
[ -n "$OLD_RELEASE" ] && [ -f "$OLD_RELEASE/VERSION" ] && OLD_VERSION="$(cat "$OLD_RELEASE/VERSION")"
export BJR_ENV_FILE="$APP_ROOT/shared/.env"
PY="$APP_ROOT/.venv/bin/python"
STAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP="$APP_ROOT/shared/backups/db_${OLD_VERSION:-unknown}_before_${NEW_VERSION}_$STAMP.sql"
SUPERVISOR_PROGRAM="${BJR_SUPERVISOR_PROGRAM:-baijiarui-bi}"
SUPERVISOR_MANAGED=false
if command -v supervisorctl >/dev/null 2>&1; then
  SUPERVISOR_STATUS="$(supervisorctl status "$SUPERVISOR_PROGRAM" 2>&1 || true)"
  if printf '%s\n' "$SUPERVISOR_STATUS" | grep -q "^$SUPERVISOR_PROGRAM[[:space:]]"; then
    SUPERVISOR_MANAGED=true
  fi
fi

stop_backend(){
  if [ "$SUPERVISOR_MANAGED" = true ]; then supervisorctl stop "$SUPERVISOR_PROGRAM"
  elif [ -n "$OLD_RELEASE" ] && [ -x "$OLD_RELEASE/deploy/baota/service.sh" ]; then APP_ROOT="$APP_ROOT" bash "$OLD_RELEASE/deploy/baota/service.sh" stop
  else echo "找不到可控的后端停止方式" >&2; return 1; fi
  if command -v ss >/dev/null 2>&1 && ss -ltn 2>/dev/null | grep -q ':8000'; then
    echo "后端端口 8000 仍在监听，停止失败，终止升级" >&2
    return 1
  fi
}

start_backend(){
  if [ "$SUPERVISOR_MANAGED" = true ]; then supervisorctl start "$SUPERVISOR_PROGRAM"
  else APP_ROOT="$APP_ROOT" bash "$1/deploy/baota/service.sh" restart; fi
}

echo "=== 百嘉瑞BI 升级 ${OLD_VERSION:-unknown} -> $NEW_VERSION ==="
[ -f "$APP_ROOT/shared/.env" ] || { echo "缺少 shared/.env"; exit 2; }
[ -x "$PY" ] || { echo "缺少共享 Python venv：$PY"; exit 3; }
[ -f "$SOURCE_DIR/frontend-dist/index.html" ] || { echo "升级包缺少 frontend-dist/index.html；请从 Windows 发布脚本生成生产包。"; exit 4; }
"$PY" "$SOURCE_DIR/scripts/release_tool.py" verify
"$PY" "$SOURCE_DIR/scripts/release_tool.py" db-ping
mkdir -p "$APP_ROOT/shared/backups" "$APP_ROOT/releases" "$APP_ROOT/shared/run"
touch "$MAINTENANCE_FILE"
trap 'rm -f "$MAINTENANCE_FILE"' EXIT
stop_backend
"$PY" "$SOURCE_DIR/scripts/release_tool.py" backup-db "$BACKUP"
[ -s "$BACKUP" ] || { echo "数据库备份为空，终止升级：$BACKUP" >&2; exit 7; }
mkdir -p "$NEW_RELEASE"
for x in backend frontend-dist templates deploy scripts VERSION manifest.json; do [ -e "$SOURCE_DIR/$x" ] && cp -a "$SOURCE_DIR/$x" "$NEW_RELEASE/"; done

rollback(){
  trap - ERR
  set +e
  echo "升级失败，开始回切应用版本；不会自动恢复数据库。"
  [ -n "$OLD_RELEASE" ] && ln -sfn "$OLD_RELEASE" "$CURRENT_LINK"
  [ -n "$OLD_RELEASE" ] && start_backend "$OLD_RELEASE" || true
  [ -n "$OLD_RELEASE" ] && "$PY" "$OLD_RELEASE/scripts/release_tool.py" record-release rollback failed --from-version "$NEW_VERSION" --backup-path "$BACKUP" --note "application rollback only; database restore requires manual review" || true
  echo "如需恢复数据库，请人工确认备份文件：$BACKUP"
}
trap rollback ERR

"$PY" -m pip install -r "$NEW_RELEASE/backend/requirements.txt"
"$PY" "$NEW_RELEASE/scripts/release_tool.py" migrate
ln -sfn "$NEW_RELEASE" "$CURRENT_LINK"
start_backend "$NEW_RELEASE"
sleep 3
HEALTH="$(curl -fsS http://127.0.0.1:8000/api/health)"
echo "$HEALTH"
echo "$HEALTH" | grep -q '"ok":true\|"ok": true'
echo "$HEALTH" | grep -q "$NEW_VERSION"
trap - ERR
"$PY" "$NEW_RELEASE/scripts/release_tool.py" record-release upgrade success --from-version "$OLD_VERSION" --backup-path "$BACKUP" --note "upgrade complete"
echo "升级成功：$OLD_VERSION -> $NEW_VERSION"
echo "数据库备份：$BACKUP"
