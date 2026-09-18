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
    app_environment: str = "development"
    cors_origins: str = ""
    session_cookie_name: str = "bjr_session"
    session_hours: int = 12
    remember_session_days: int = 7
    session_cookie_secure: bool = False
    # Forwarded headers are trusted only when the immediate peer is allow-listed.
    trusted_proxy_ips: str = ""
    login_rate_limit_attempts: int = 5
    login_rate_limit_ip_attempts: int = 20
    login_rate_limit_window_seconds: int = 900
    login_rate_limit_lockout_seconds: int = 900

    # Import/export resource boundaries. Values are configurable through the
    # matching upper-case environment variables.
    max_upload_bytes: int = 50 * 1024 * 1024
    max_import_rows: int = 200_000
    max_import_worksheets: int = 20
    max_xlsx_uncompressed_bytes: int = 500 * 1024 * 1024
    max_export_rows: int = 200_000
    db_pool_size: int = 5
    db_max_overflow: int = 10
    db_pool_recycle: int = 1800

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


def validate_runtime_security() -> None:
    """Reject explicitly production-mode deployments with unsafe cookie/CORS settings."""
    if settings.app_environment.strip().lower() != "production":
        return
    if not settings.session_cookie_secure:
        raise RuntimeError("生产环境必须设置 SESSION_COOKIE_SECURE=true 并通过 HTTPS 访问")
    origins = [value.strip() for value in settings.cors_origins.split(",") if value.strip()]
    if "*" in origins or any(not origin.lower().startswith("https://") for origin in origins):
        raise RuntimeError("生产环境 CORS_ORIGINS 只能配置明确的 HTTPS 来源，不能使用通配符")
