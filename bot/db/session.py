from __future__ import annotations

from pathlib import Path

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from bot.db.models import Base

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None

_SQLITE_PREFIX = "sqlite+aiosqlite:///"


def _prepare_sqlite_path(database_url: str) -> None:
    if not database_url.startswith(_SQLITE_PREFIX):
        return
    raw_path = database_url[len(_SQLITE_PREFIX) :]
    if not raw_path or raw_path == ":memory:":
        return
    Path(raw_path).parent.mkdir(parents=True, exist_ok=True)


async def init_db(database_url: str) -> None:
    global _engine, _session_factory

    _prepare_sqlite_path(database_url)
    _engine = create_async_engine(database_url, echo=False, pool_pre_ping=True)

    if database_url.startswith("sqlite"):
        @event.listens_for(_engine.sync_engine, "connect")
        def _enable_foreign_keys(dbapi_connection, _connection_record) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    _session_factory = async_sessionmaker(_engine, expire_on_commit=False)

    async with _engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    if _session_factory is None:
        raise RuntimeError("База данных не инициализирована: вызовите init_db()")
    return _session_factory


async def close_db() -> None:
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None
