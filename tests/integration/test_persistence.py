"""Integration test: data survives closing the database and reopening it.

Uses a real file-based SQLite database (not the in-memory ``session``
fixture) so this actually exercises what happens when the app is
closed and relaunched — the scenario the founder's acceptance
criteria describes as "close and reopen the application without
losing metadata."
"""

from __future__ import annotations

from pathlib import Path

from app.core.db.base import Base
from app.core.db.engine import create_db_engine, create_session_factory
from app.core.db.seed import seed_demo_data
from app.core.models import Character, Episode, Short


def test_data_persists_across_engine_close_and_reopen(tmp_path: Path) -> None:
    db_path = tmp_path / "studio.db"
    db_url = f"sqlite:///{db_path}"

    # "First app launch": create the schema and seed data, then close everything.
    engine1 = create_db_engine(database_url=db_url)
    Base.metadata.create_all(engine1)
    session_factory1 = create_session_factory(engine1)
    with session_factory1() as session1:
        seed_demo_data(session1)
    engine1.dispose()

    # "App relaunch": a brand-new engine/session pointed at the same file.
    engine2 = create_db_engine(database_url=db_url)
    session_factory2 = create_session_factory(engine2)
    with session_factory2() as session2:
        melissa = session2.query(Character).filter_by(slug="melissa").one()
        bilsan = session2.query(Character).filter_by(slug="bilsan").one()
        episode = session2.query(Episode).filter_by(slug="ep001_lost_little_turtle").one()
        shorts = session2.query(Short).filter_by(episode_id=episode.id).all()

        assert melissa.name_ar == "ميليسا"
        assert bilsan.name_ar == "بيلسان"
        assert episode.title_ar == "ميليسا وبيلسان والسلحفاة الصغيرة الضائعة"
        assert len(shorts) == 3
    engine2.dispose()

    assert db_path.exists()
    assert db_path.stat().st_size > 0
