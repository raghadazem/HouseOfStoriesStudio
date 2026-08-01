"""Shared pytest fixtures for the domain/database test suite."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.core import models  # noqa: F401  registers every table on Base.metadata
from app.core.db.base import Base
from app.core.db.engine import create_db_engine, create_session_factory


@pytest.fixture()
def engine() -> Iterator[Engine]:
    """An isolated in-memory SQLite engine with foreign keys enabled.

    Uses the same :func:`app.core.db.engine.create_db_engine` code path
    the real application uses (including the foreign-key pragma), so
    these tests exercise the actual production wiring rather than a
    parallel test-only setup.
    """
    eng = create_db_engine(database_url="sqlite:///:memory:")
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture()
def session(engine: Engine) -> Iterator[Session]:
    session_factory = create_session_factory(engine)
    with session_factory() as s:
        yield s
