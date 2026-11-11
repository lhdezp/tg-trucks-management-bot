from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.models import Base, BotSettings

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        settings = get_settings()
        settings.db_path.parent.mkdir(parents=True, exist_ok=True)
        url = f"sqlite:///{settings.db_path.resolve().as_posix()}"
        _engine = create_engine(url, future=True)

        @event.listens_for(_engine, "connect")
        def set_sqlite_pragma(dbapi_connection, _connection_record) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()

    return _engine


def get_session_factory() -> sessionmaker[Session]:
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(
            bind=get_engine(),
            autoflush=False,
            expire_on_commit=False,
        )
    return _session_factory


@contextmanager
def session_scope() -> Iterator[Session]:
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _ensure_ticket_columns(engine: Engine) -> None:
    inspector = inspect(engine)
    if "tickets" not in inspector.get_table_names():
        return
    existing = {column["name"] for column in inspector.get_columns("tickets")}
    migrations = {
        "amount": "NUMERIC(12, 2)",
        "amount_source": "VARCHAR(16)",
        "ai_model": "VARCHAR(64)",
        "ai_processed_at": "DATETIME",
    }
    missing = {
        name: definition
        for name, definition in migrations.items()
        if name not in existing
    }
    if not missing:
        return
    with engine.begin() as connection:
        for name, definition in missing.items():
            connection.execute(
                text(f"ALTER TABLE tickets ADD COLUMN {name} {definition}")
            )


def init_db() -> None:
    engine = get_engine()
    Base.metadata.create_all(engine)
    _ensure_ticket_columns(engine)
    with session_scope() as db:
        if db.get(BotSettings, 1) is None:
            db.add(BotSettings(id=1))
