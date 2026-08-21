from __future__ import annotations
import argparse, getpass, os
from sqlalchemy import text
from ..db import SessionLocal
from ..services.auth_service import hash_password


def main():
    p=argparse.ArgumentParser(description="创建/重置百嘉瑞BI系统管理员（仅本地数据库）")
    p.add_argument("--user-id",default="SYS0001")
    p.add_argument("--username",default="admin")
    p.add_argument("--password-env",default="BOOTSTRAP_ADMIN_PASSWORD")
    args=p.parse_args()
    password=os.getenv(args.password_env) or getpass.getpass("管理员密码（至少8位）: ")
    encoded=hash_password(password)
    with SessionLocal() as db:
        row=db.execute(text("SELECT id FROM users WHERE user_id=:uid"),{"uid":args.user_id}).first()
        if row:
            db.execute(text("UPDATE users SET username=:name,password_hash=:pw,is_system_admin=1,status='enabled' WHERE user_id=:uid"),{"name":args.username,"pw":encoded,"uid":args.user_id})
        else:
            db.execute(text("INSERT INTO users(user_id,username,password_hash,is_system_admin,status) VALUES(:uid,:name,:pw,1,'enabled')"),{"uid":args.user_id,"name":args.username,"pw":encoded})
        db.commit()
    print(f"system admin ready: {args.user_id} / {args.username}")

if __name__ == "__main__": main()
