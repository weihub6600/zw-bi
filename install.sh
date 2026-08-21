#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
if [ -f "$SCRIPT_DIR/VERSION" ]; then SOURCE_DIR="$SCRIPT_DIR"; else SOURCE_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"; fi
APP_ROOT="${1:-/www/wwwroot/baijiarui-bi}"
VERSION="$(cat "$SOURCE_DIR/VERSION")"
RELEASE_DIR="$APP_ROOT/releases/v$VERSION"
export BJR_ENV_FILE="$APP_ROOT/shared/.env"

echo "=== 百嘉瑞BI 首次安装 V$VERSION ==="
mkdir -p "$APP_ROOT/releases" "$APP_ROOT/shared/uploads" "$APP_ROOT/shared/import_files" "$APP_ROOT/shared/logs" "$APP_ROOT/shared/backups" "$APP_ROOT/shared/run"
if [ ! -f "$APP_ROOT/shared/.env" ]; then
  cp "$SOURCE_DIR/.env.example" "$APP_ROOT/shared/.env"
  echo "已创建 $APP_ROOT/shared/.env"
  echo "请先在宝塔创建数据库/用户，然后编辑该 .env，修改 MYSQL_PASSWORD 和 APP_SECRET，再重新执行本脚本。"
  exit 10
fi
if grep -qE '^(MYSQL_PASSWORD=change_me|APP_SECRET=dev-secret)' "$APP_ROOT/shared/.env"; then
  echo "shared/.env 仍是默认密码/密钥，请先修改。"; exit 11
fi
rm -rf "$RELEASE_DIR"; mkdir -p "$RELEASE_DIR"
for x in backend frontend-dist templates deploy scripts VERSION manifest.json .env.example install.sh README_DEPLOY.txt; do [ -e "$SOURCE_DIR/$x" ] && cp -a "$SOURCE_DIR/$x" "$RELEASE_DIR/"; done
if [ ! -f "$RELEASE_DIR/frontend-dist/index.html" ]; then
  echo "生产包没有 frontend-dist/index.html。请在 Windows 开发机运行 发布生产包.cmd 生成正式安装包。"; exit 12
fi
python3 -m venv "$APP_ROOT/.venv"
"$APP_ROOT/.venv/bin/python" -m pip install --upgrade pip
"$APP_ROOT/.venv/bin/python" -m pip install -r "$RELEASE_DIR/backend/requirements.txt"
ln -sfn "$RELEASE_DIR" "$APP_ROOT/current"
"$APP_ROOT/.venv/bin/python" "$RELEASE_DIR/scripts/release_tool.py" verify
"$APP_ROOT/.venv/bin/python" "$RELEASE_DIR/scripts/release_tool.py" db-ping
"$APP_ROOT/.venv/bin/python" "$RELEASE_DIR/scripts/release_tool.py" init-schema
"$APP_ROOT/.venv/bin/python" "$RELEASE_DIR/scripts/release_tool.py" migrate
APP_ROOT="$APP_ROOT" bash "$RELEASE_DIR/deploy/baota/service.sh" restart
sleep 2
curl -fsS http://127.0.0.1:8000/api/health; echo
"$APP_ROOT/.venv/bin/python" "$RELEASE_DIR/scripts/release_tool.py" record-release install success --note "first install"
echo "安装完成。Nginx root 指向：$APP_ROOT/current/frontend-dist"
