from sqlalchemy import create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from .core.config import settings

database_url = make_url(settings.effective_database_url) if isinstance(settings.effective_database_url, str) else settings.effective_database_url
engine_kwargs = {"pool_pre_ping": True, "future": True}
if database_url.get_backend_name() == "mysql":
    engine_kwargs.update(
        pool_size=max(1, settings.db_pool_size),
        max_overflow=max(0, settings.db_max_overflow),
        pool_recycle=max(60, settings.db_pool_recycle),
    )
engine = create_engine(database_url, **engine_kwargs)


if engine.dialect.name == "mysql":
    @event.listens_for(engine, "connect")
    def _set_mysql_timezone(dbapi_connection, connection_record):
        """Make MySQL CURRENT_TIMESTAMP use the application timezone."""

        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("SET time_zone = '+08:00'")
        finally:
            cursor.close()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
