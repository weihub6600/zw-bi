from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from .core.config import settings

engine = create_engine(settings.effective_database_url, pool_pre_ping=True, future=True)


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
