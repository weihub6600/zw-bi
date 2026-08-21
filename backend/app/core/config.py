import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL


PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _resolve_env_file() -> Path:
    explicit = os.getenv("BJR_ENV_FILE", "").strip()
    if explicit:
        return Path(explicit)

    local_env = PROJECT_ROOT / ".env"
    if local_env.exists():
        return local_env

    # Production release layout:
    # /www/wwwroot/baijiarui-bi/releases/vX.Y.Z/backend/...
    # /www/wwwroot/baijiarui-bi/shared/.env
    if PROJECT_ROOT.parent.name == "releases":
        shared_env = PROJECT_ROOT.parent.parent / "shared" / ".env"
        if shared_env.exists():
            return shared_env

    return local_env


ENV_FILE = _resolve_env_file()


class Settings(BaseSettings):
    database_url: str = ""
    mysql_host: str = "127.0.0.1"
    mysql_port: int = 3306
    mysql_database: str = "baijiarui_bi"
    mysql_user: str = "baijiarui"
    mysql_password: str = "change_me"

    app_secret: str = "dev-secret"
    cors_origins: str = ""
    session_cookie_name: str = "bjr_session"
    session_hours: int = 12
    remember_session_days: int = 7
    session_cookie_secure: bool = False

    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def effective_database_url(self):
        if self.database_url.strip():
            return self.database_url.strip()
        return URL.create(
            "mysql+pymysql",
            username=self.mysql_user,
            password=self.mysql_password,
            host=self.mysql_host,
            port=self.mysql_port,
            database=self.mysql_database,
            query={"charset": "utf8mb4"},
        )


settings = Settings()
