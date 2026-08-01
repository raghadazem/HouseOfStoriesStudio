"""Tests for app.core.db.engine — specifically that foreign keys are enforced.

SQLite does not enforce foreign keys by default; without the
``PRAGMA foreign_keys=ON`` that :func:`register_sqlite_pragma` attaches,
this test would fail to raise and silently allow orphaned rows.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.models import Scene


def test_foreign_keys_pragma_is_enabled(engine) -> None:
    with engine.connect() as connection:
        result = connection.execute(text("PRAGMA foreign_keys")).scalar()
        assert result == 1


def test_inserting_scene_with_unknown_episode_id_is_rejected(session: Session) -> None:
    import uuid

    orphan_scene = Scene(episode_id=uuid.uuid4(), order_index=1)
    session.add(orphan_scene)
    with pytest.raises(IntegrityError, match="FOREIGN KEY"):
        session.commit()
