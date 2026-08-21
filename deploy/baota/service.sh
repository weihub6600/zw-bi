#!/usr/bin/env bash
set -euo pipefail
APP_ROOT="${APP_ROOT:-/www/wwwroot/baijiarui-bi}"
PID_FILE="$APP_ROOT/shared/run/backend.pid"
LOG_FILE="$APP_ROOT/shared/logs/backend.log"
PY="$APP_ROOT/.venv/bin/python"
CURRENT="$APP_ROOT/current"
export BJR_ENV_FILE="$APP_ROOT/shared/.env"
mkdir -p "$APP_ROOT/shared/run" "$APP_ROOT/shared/logs"

is_running(){
  [ -f "$PID_FILE" ] || return 1
  local p; p="$(cat "$PID_FILE" 2>/dev/null || true)"
  [ -n "$p" ] && kill -0 "$p" 2>/dev/null
}
start(){
  if is_running; then echo "backend already running pid=$(cat "$PID_FILE")"; return 0; fi
  [ -x "$PY" ] || { echo "missing venv: $PY"; exit 1; }
  [ -d "$CURRENT/backend" ] || { echo "missing current release"; exit 1; }
  nohup "$PY" -m uvicorn app.main:app --app-dir "$CURRENT/backend" --host 127.0.0.1 --port 8000 >>"$LOG_FILE" 2>&1 &
  echo $! > "$PID_FILE"
  sleep 2
  is_running || { tail -n 80 "$LOG_FILE" || true; exit 1; }
  echo "backend started pid=$(cat "$PID_FILE")"
}
stop(){
  if ! is_running; then rm -f "$PID_FILE"; echo "backend not running"; return 0; fi
  local p; p="$(cat "$PID_FILE")"; kill "$p" || true
  for _ in $(seq 1 20); do kill -0 "$p" 2>/dev/null || break; sleep .5; done
  kill -9 "$p" 2>/dev/null || true; rm -f "$PID_FILE"; echo "backend stopped"
}
status(){ if is_running; then echo "RUNNING pid=$(cat "$PID_FILE")"; else echo "STOPPED"; return 1; fi; }
case "${1:-status}" in start) start;; stop) stop;; restart) stop; start;; status) status;; *) echo "usage: $0 start|stop|restart|status"; exit 2;; esac
