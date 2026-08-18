"""Async SQLAlchemy engine/session factory."""
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings

# pool_size/max_overflow read from Settings (db_pool_size/db_pool_max_overflow)
# rather than hardcoded -- see config.py's own comment on those two fields for
# the full rationale: this module is imported by app-backend, app-celery_worker,
# AND app-celery_beat (three separate processes, three separate engines/pools),
# but only app-backend serves concurrent user-facing HTTP traffic, so
# docker-compose.yml gives it a larger explicit DB_POOL_SIZE/DB_POOL_MAX_OVERFLOW
# override while the celery processes fall back to these conservative defaults.
_settings = get_settings()
_engine = create_async_engine(
    _settings.database_url,
    pool_pre_ping=True,
    echo=False,
    pool_size=_settings.db_pool_size,
    max_overflow=_settings.db_pool_max_overflow,
)
_SessionLocal = async_sessionmaker(bind=_engine, expire_on_commit=False, class_=AsyncSession)


async def get_db() -> AsyncIterator[AsyncSession]:
    async with _SessionLocal() as session:
        yield session


def new_session() -> AsyncSession:
    """For callers outside a FastAPI request (Celery tasks, scripts) that
    can't use get_db()'s dependency-injected generator. Caller owns the
    session's lifecycle -- use as `async with new_session() as db:`.
    """
    return _SessionLocal()
