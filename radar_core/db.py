"""Engine y sesiones de SQLAlchemy (sync, psycopg 3)."""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from .config import get_settings

_engine = None
_SessionLocal: sessionmaker | None = None


def engine():
    global _engine, _SessionLocal
    if _engine is None:
        _engine = create_engine(get_settings().database_url, pool_size=10, max_overflow=20, pool_pre_ping=True)
        _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def session_factory() -> sessionmaker:
    engine()
    assert _SessionLocal is not None
    return _SessionLocal


def get_session() -> Iterator[Session]:
    s = session_factory()()
    try:
        yield s
    finally:
        s.close()


def reset_engine() -> None:
    """Para tests: fuerza a releer settings.database_url."""
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None
