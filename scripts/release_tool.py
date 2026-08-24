from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from app.core.config import settings  # noqa: E402
from app.version import APP_VERSION  # noqa: E402

try:
    import pymysql
    from pymysql.constants import CLIENT
except Exception as exc:
    raise SystemExit(f"PyMySQL 未安装：{exc}。请先安装 backend/requirements.txt")


def _url_parts():
    url = settings.effective_database_url
    if isinstance(url, str):
        from sqlalchemy.engine import make_url
        url = make_url(url)
    return {
        "host": url.host or "127.0.0.1",
        "port": int(url.port or 3306),
        "user": url.username or "",
        "password": url.password or "",
        "database": url.database or "",
    }


def connect(database: bool = True):
    p = _url_parts()
    return pymysql.connect(
        host=p["host"], port=p["port"], user=p["user"], password=p["password"],
        database=p["database"] if database else None,
        charset="utf8mb4", autocommit=True, client_flag=CLIENT.MULTI_STATEMENTS,
    )


def sha256(path: Path) -> str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024*1024), b''):
            h.update(chunk)
    return h.hexdigest()


def migration_sha256(path: Path) -> str:
    """migration 专用 checksum：将 CRLF/CR 标准化为 LF 后再 hash。

    用于消除 Windows/Linux 换行符差异导致的 checksum drift，不影响 manifest 的通用 sha256。
    """
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024*1024), b''):
            normalized = chunk.replace(b'\r\n', b'\n').replace(b'\r', b'\n')
            h.update(normalized)
    return h.hexdigest()


def legacy_crlf_sha256(path: Path) -> str:
    """legacy 兼容 checksum：标准化为 LF 后再转成 CRLF 求 hash。

    用于兼容旧 Windows release_tool 按 raw CRLF 存的 checksum（新 Linux checkout 为 LF）。
    """
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024*1024), b''):
            normalized = chunk.replace(b'\r\n', b'\n').replace(b'\r', b'\n')
            crlf = normalized.replace(b'\n', b'\r\n')
            h.update(crlf)
    return h.hexdigest()


# manifest 中按文本处理的扩展名（换行符标准化），其余按二进制 raw 校验。
MANIFEST_TEXT_SUFFIXES = {
    ".py", ".sql", ".js", ".css", ".html", ".json", ".txt", ".md", ".sh",
    ".vue", ".yaml", ".yml", ".toml", ".ini", ".cfg",
}
# 无扩展名但按文本处理的文件
MANIFEST_TEXT_NAMES = {"VERSION", ".env.example", ".gitignore", ".gitattributes"}


def is_manifest_text_file(path: Path) -> bool:
    return path.suffix.lower() in MANIFEST_TEXT_SUFFIXES or path.name in MANIFEST_TEXT_NAMES


def manifest_canonical_sha256(path: Path) -> str:
    """manifest 文本文件 canonical hash：CRLF/CR 标准化为 LF 后 SHA256。"""
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024*1024), b''):
            h.update(chunk.replace(b'\r\n', b'\n').replace(b'\r', b'\n'))
    return h.hexdigest()


def manifest_legacy_crlf_sha256(path: Path) -> str:
    """manifest 文本文件 legacy CRLF hash：标准化 LF 后再转 CRLF 后 SHA256。"""
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024*1024), b''):
            normalized = chunk.replace(b'\r\n', b'\n').replace(b'\r', b'\n')
            h.update(normalized.replace(b'\n', b'\r\n'))
    return h.hexdigest()


def manifest_file_sha256(path: Path) -> str:
    """生成 manifest 用的 hash：文本文件用 canonical LF，二进制用 raw。"""
    if is_manifest_text_file(path):
        return manifest_canonical_sha256(path)
    return sha256(path)


def bootstrap_migration_table(conn):
    with conn.cursor() as cur:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
          id BIGINT PRIMARY KEY AUTO_INCREMENT,
          migration_id VARCHAR(128) NOT NULL UNIQUE,
          app_version VARCHAR(32) NULL,
          checksum CHAR(64) NOT NULL,
          applied_by VARCHAR(64) NOT NULL DEFAULT 'release_tool',
          applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""")
        cur.execute("SELECT COUNT(*) FROM schema_migrations")
        count=cur.fetchone()[0]
        if count == 0:
            cur.execute("SHOW TABLES LIKE 'users'")
            if cur.fetchone():
                # 旧版数据库（有 users 等历史基础表，但没有 schema_migrations）。
                # 只 baseline 确定属于历史基础库的 0141~0147；0151 及之后的 migration
                # 必须由 migrate() 正常执行，否则升级会缺失 release_history /
                # product_name_aliases / task_shops / task_warehouses / task_no_sequences 等表。
                baseline=[
                    ('0141_import_pipeline','14.1.0'),
                    ('0142_dashboard_indexes','14.2.0'),
                    ('0145_import_center_indexes','14.5.0'),
                    ('0146_auth_sessions','14.6.0'),
                    ('0147_audit_indexes','14.7.0'),
                ]
                cur.executemany(
                    "INSERT IGNORE INTO schema_migrations(migration_id,app_version,checksum,applied_by) VALUES(%s,%s,%s,'baseline')",
                    [(mid,ver,'0'*64) for mid,ver in baseline]
                )


def apply_sql(conn, sql: str):
    with conn.cursor() as cur:
        cur.execute(sql)
        while cur.nextset():
            pass


def migrate():
    mig_dir = ROOT / 'backend' / 'sql' / 'migrations'
    files = sorted(mig_dir.glob('*.sql'))
    conn = connect()
    try:
        bootstrap_migration_table(conn)
        with conn.cursor() as cur:
            cur.execute("SELECT migration_id, checksum FROM schema_migrations")
            done={r[0]: r[1] for r in cur.fetchall()}
        applied=[]
        for path in files:
            mid=path.stem
            if mid in done:
                # checksum drift 检查：已执行 migration 的 checksum 与当前文件不一致，
                # 说明 migration 文件已被修改，必须报错（历史 baseline checksum 全 0 兼容跳过）。
                # 跨平台：兼容 raw LF / raw CRLF / canonical（LF 标准化）三种历史值。
                recorded = done[mid]
                if recorded and recorded != '0'*64:
                    current = migration_sha256(path)
                    raw = sha256(path)
                    legacy_crlf = legacy_crlf_sha256(path)
                    accepted = {current, raw, legacy_crlf}
                    if recorded not in accepted:
                        raise SystemExit(
                            f"migration 文件被修改：{mid}（记录 checksum={recorded[:12]}…，"
                            f"当前文件 checksum={current[:12]}…）。请勿修改已应用的 migration。"
                        )
                continue
            sql=path.read_text(encoding='utf-8')
            # 每个 migration 文件独立事务：成功则连同版本记录一并提交，
            # 失败则整体回滚，确保不留半状态、可安全重跑（幂等）。
            conn.autocommit(False)
            try:
                apply_sql(conn, sql)
                checksum=migration_sha256(path)
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO schema_migrations(migration_id,app_version,checksum,applied_by) VALUES(%s,%s,%s,'release_tool')",
                        (mid, APP_VERSION, checksum),
                    )
                conn.commit()
                applied.append(mid)
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.autocommit(True)
        return applied
    finally:
        conn.close()


def init_schema():
    schema=ROOT/'backend/sql/schema_tables.sql'
    conn = connect()
    try:
        apply_sql(conn, schema.read_text(encoding='utf-8'))
    finally:
        conn.close()
    print(f"schema initialized: {schema}")


def db_ping():
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT DATABASE(), VERSION()')
            row=cur.fetchone()
    finally:
        conn.close()
    print(json.dumps({'ok':True,'database':row[0],'mysql_version':row[1]}, ensure_ascii=False))


def find_client(name: str) -> str:
    exe_name = name + ('.exe' if os.name == 'nt' and not name.lower().endswith('.exe') else '')
    candidates = []

    # 允许显式指定 MySQL bin 目录，优先级最高。
    mysql_bin = os.environ.get('BJR_MYSQL_BIN') or os.environ.get('MYSQL_BIN')
    if mysql_bin:
        candidates.append(str(Path(mysql_bin) / exe_name))

    # PATH 与常见固定位置。绝不递归扫描整块磁盘，避免 Windows 上卡在 D:/ 搜索。
    candidates += [
        shutil.which(name),
        shutil.which(exe_name),
        f'/www/server/mysql/bin/{name}',
        f'/usr/bin/{name}',
        f'/usr/local/bin/{name}',
    ]
    if os.name == 'nt':
        candidates += [
            f'D:/mysql84/bin/{exe_name}',
            f'D:/MYsql8.4/bin/{exe_name}',
            f'C:/Program Files/MySQL/MySQL Server 8.4/bin/{exe_name}',
            f'C:/Program Files/MySQL/MySQL Server 8.0/bin/{exe_name}',
        ]
    for c in candidates:
        if c and Path(c).is_file():
            return str(c)
    raise SystemExit(
        f"找不到 {name}。Windows 可设置环境变量 BJR_MYSQL_BIN，例如 D:\\mysql84\\bin；"
        "宝塔请确认 MySQL 已安装。"
    )


def backup_db(out: Path):
    p=_url_parts(); out.parent.mkdir(parents=True, exist_ok=True)
    exe=find_client('mysqldump')
    print(f'mysqldump: {exe}', flush=True)
    env=os.environ.copy(); env['MYSQL_PWD']=p['password']
    cmd=[exe,'-h',p['host'],'-P',str(p['port']),'-u',p['user'],
         '--protocol=TCP','--single-transaction','--routines','--triggers','--no-tablespaces',
         '--default-character-set=utf8mb4',p['database']]
    with out.open('wb') as f:
        cp=subprocess.run(cmd, env=env, stdout=f, stderr=subprocess.PIPE)
    if cp.returncode != 0:
        out.unlink(missing_ok=True)
        raise SystemExit('数据库备份失败：'+cp.stderr.decode('utf-8','ignore'))
    print(str(out))


def restore_db(src: Path):
    p=_url_parts(); exe=find_client('mysql')
    env=os.environ.copy(); env['MYSQL_PWD']=p['password']
    cmd=[exe,'-h',p['host'],'-P',str(p['port']),'-u',p['user'],'--default-character-set=utf8mb4',p['database']]
    with src.open('rb') as f:
        cp=subprocess.run(cmd, env=env, stdin=f)
    if cp.returncode != 0:
        raise SystemExit('数据库恢复失败')


def record_release(action, status, from_version='', backup_path='', note=''):
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO release_history(app_version,from_version,action,status,db_backup_path,note)
                VALUES(%s,%s,%s,%s,%s,%s)
            """, (APP_VERSION, from_version or None, action, status, backup_path or None, note or None))
    finally:
        conn.close()


def verify_manifest():
    mf=ROOT/'manifest.json'
    if not mf.exists():
        print('manifest.json not present; skip')
        return
    data=json.loads(mf.read_text(encoding='utf-8'))
    bad=[]
    for rel, expected in data.get('files',{}).items():
        p=ROOT/rel
        if not p.exists():
            bad.append(rel)
            continue
        if is_manifest_text_file(p):
            # 文本文件跨平台兼容：接受 raw / canonical LF / legacy CRLF 三种 hash。
            accepted = {sha256(p), manifest_canonical_sha256(p), manifest_legacy_crlf_sha256(p)}
            if expected not in accepted:
                bad.append(rel)
        else:
            # 二进制文件严格 raw byte 校验。
            if sha256(p) != expected:
                bad.append(rel)
    if bad:
        raise SystemExit('文件校验失败：'+', '.join(bad[:20]))
    print(f"manifest ok: {len(data.get('files',{}))} files")


def main():
    ap=argparse.ArgumentParser()
    sp=ap.add_subparsers(dest='cmd', required=True)
    sp.add_parser('version'); sp.add_parser('db-ping'); sp.add_parser('migrate'); sp.add_parser('init-schema'); sp.add_parser('verify')
    b=sp.add_parser('backup-db'); b.add_argument('outfile')
    r=sp.add_parser('restore-db'); r.add_argument('infile')
    rr=sp.add_parser('record-release'); rr.add_argument('action'); rr.add_argument('status'); rr.add_argument('--from-version',default=''); rr.add_argument('--backup-path',default=''); rr.add_argument('--note',default='')
    a=ap.parse_args()
    if a.cmd=='version': print(APP_VERSION)
    elif a.cmd=='db-ping': db_ping()
    elif a.cmd=='migrate': print(json.dumps({'applied':migrate()},ensure_ascii=False))
    elif a.cmd=='init-schema': init_schema()
    elif a.cmd=='backup-db': backup_db(Path(a.outfile))
    elif a.cmd=='restore-db': restore_db(Path(a.infile))
    elif a.cmd=='verify': verify_manifest()
    elif a.cmd=='record-release': record_release(a.action,a.status,a.from_version,a.backup_path,a.note)

if __name__=='__main__':
    main()
