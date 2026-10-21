"""SQLite metadata store; do not store weights or dataset contents in SQL."""

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from backend.app.core.config import get_settings


class Base(DeclarativeBase):
    pass


def create_database_engine(url: str) -> Engine:
    bind = create_engine(
        url, connect_args={"check_same_thread": False} if url.startswith("sqlite") else {}
    )
    if url.startswith("sqlite"):
        @event.listens_for(bind, "connect")
        def configure_sqlite(dbapi_connection, _connection_record) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.close()
    return bind


engine = create_database_engine(get_settings().resolved_database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_db(bind: Engine = engine) -> None:
    # Import mappings, then reject legacy tables before creating any new tables.
    from backend.app.models import entities  # noqa: F401
    from backend.app.core.dataset_migration import require_dataset_schema

    require_dataset_schema(bind)
    Base.metadata.create_all(bind=bind)


def get_db():
    with SessionLocal() as session:
        yield session
