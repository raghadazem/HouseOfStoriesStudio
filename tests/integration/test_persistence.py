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
from app.core.db.enums import ApprovalDecision, AssetType
from app.core.db.seed import seed_demo_data
from app.core.models import Asset, Character, Episode, Short
from app.core.services.approval_service import ApprovalService


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


def test_approval_revision_state_persists_across_engine_close_and_reopen(
    tmp_path: Path,
) -> None:
    """Several rapid approval decisions, then a real close/reopen — the
    revision-based "current state" (see ApprovalService and
    docs/engineering/WINDOWS_DEVELOPMENT.md) must read back identically
    to what was true right before the app closed."""
    db_path = tmp_path / "studio.db"
    db_url = f"sqlite:///{db_path}"

    engine1 = create_db_engine(database_url=db_url)
    Base.metadata.create_all(engine1)
    session_factory1 = create_session_factory(engine1)
    asset_id = None
    with session_factory1() as session1:
        asset = Asset(
            asset_type=AssetType.IMAGE, original_filename="f.png",
            relative_path="episodes/ep001/images/f.png", checksum="a" * 64,
        )
        session1.add(asset)
        session1.flush()
        asset_id = asset.id

        service = ApprovalService()
        service.approve_entity(session1, "asset", asset_id, decided_by="founder")
        service.request_changes(session1, "asset", asset_id, notes="fix palette")
        service.reject_entity(session1, "asset", asset_id, notes="never mind")
        session1.commit()
    engine1.dispose()

    engine2 = create_db_engine(database_url=db_url)
    session_factory2 = create_session_factory(engine2)
    with session_factory2() as session2:
        service = ApprovalService()
        history = service.list_approval_history(session2, "asset", asset_id)
        assert [r.revision for r in history] == [1, 2, 3]
        assert [r.decision for r in history] == [
            ApprovalDecision.APPROVED, ApprovalDecision.NEEDS_CHANGES, ApprovalDecision.REJECTED,
        ]
        assert (
            service.get_current_approval_state(session2, "asset", asset_id)
            == ApprovalDecision.REJECTED
        )
    engine2.dispose()
