"""Shared pytest fixtures for the domain/database/service test suite."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.config import AppConfig, load_config
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


@pytest.fixture()
def app_config(tmp_path: Path) -> AppConfig:
    """An isolated :class:`AppConfig` with real (temp-dir) production/data paths.

    For services that touch the filesystem (``StorageService``,
    ``AssetImportService``, ``ExportPackageService``) — independent of
    the in-memory ``session``/``engine`` fixtures, which cover the
    database side only.
    """
    production_dir = tmp_path / "production"
    data_dir = tmp_path / "data"
    production_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)
    return load_config(
        env={
            "HOS_PROJECT_ROOT": str(tmp_path),
            "HOS_DATA_DIR": str(data_dir),
            "HOS_PRODUCTION_DIR": str(production_dir),
        }
    )


@pytest.fixture()
def source_file(tmp_path: Path) -> Path:
    """A small real file outside the managed storage root, safe to import."""
    path = tmp_path / "sources" / "test_image.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"fake png bytes for testing")
    return path
