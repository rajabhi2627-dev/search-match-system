"""Database connection management (SQLite + SQLAlchemy).

Usage
-----
    from database.database import init_db, get_session

    init_db()                       # creates tables if missing
    with get_session() as session:  # commits on success, rolls back on error
        ...
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from database.models import Base
from utils.helpers import PROJECT_ROOT, load_config

_engine: Engine | None = None
_SessionLocal: sessionmaker | None = None
_current_path: str | None = None


def _resolve_path(db_path: str | None) -> str:
    """Return the database path: explicit arg > env var > config.yaml."""
    if db_path:
        return db_path
    env_path = os.environ.get("SMM_DB_PATH")
    if env_path:
        return env_path
    cfg_path = load_config()["database"]["path"]
    return str((PROJECT_ROOT / cfg_path).resolve())


def get_engine(db_path: str | None = None) -> Engine:
    """Create (once) and return the SQLAlchemy engine."""
    global _engine, _SessionLocal, _current_path
    path = _resolve_path(db_path)
    if _engine is not None and path == _current_path:
        return _engine

    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        url = f"sqlite:///{path}"
    else:
        url = "sqlite://"

    _engine = create_engine(url, future=True, connect_args={"check_same_thread": False})

    @event.listens_for(_engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, _):  # pragma: no cover - driver hook
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()

    _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False, future=True)
    _current_path = path
    return _engine


def init_db(db_path: str | None = None) -> Engine:
    """Create all tables (idempotent) and return the engine."""
    engine = get_engine(db_path)
    Base.metadata.create_all(engine)
    return engine


def reset_engine() -> None:
    """Forget the current engine (used by tests to switch databases)."""
    global _engine, _SessionLocal, _current_path
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None
    _current_path = None


@contextmanager
def get_session() -> Iterator[Session]:
    """Context-managed session: commit on success, rollback on exception."""
    if _SessionLocal is None:
        init_db()
    assert _SessionLocal is not None
    session: Session = _SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
