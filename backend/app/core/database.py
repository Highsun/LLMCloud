"""SQLite metadata store; do not store weights or dataset contents in SQL."""

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from backend.app.core.config import get_settings


class Base(DeclarativeBase):
    pass


url = get_settings().resolved_database_url
engine = create_engine(
    url, connect_args={"check_same_thread": False} if url.startswith("sqlite") else {}
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

if url.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def configure_sqlite(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()


def init_db() -> None:
    # Import all mapped tables before create_all. Migrations follow in a later phase.
    from backend.app.models import entities  # noqa: F401

    Base.metadata.create_all(bind=engine)


def get_db():
    with SessionLocal() as session:
        yield session
