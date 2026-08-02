"""Tests for ProductionTaskService: CRUD, default checklist, progress, overdue."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.db.enums import ProductionTaskStatus
from app.core.models import Episode
from app.core.services.production_task_service import (
    DEFAULT_EPISODE_TASK_TYPES,
    ProductionTaskService,
)


def _episode(session: Session) -> Episode:
    episode = Episode(slug="ep001_test", number=1, title_ar="ع", title_en="Test", lesson="Sharing")
    session.add(episode)
    session.flush()
    return episode


def test_create_default_episode_tasks_covers_every_required_stage(session: Session) -> None:
    ts = ProductionTaskService()
    episode = _episode(session)
    tasks = ts.create_default_episode_tasks(session, episode.id)

    task_types = {t.task_type for t in tasks}
    expected_types = {t for t, _ in DEFAULT_EPISODE_TASK_TYPES}
    assert task_types == expected_types
    for required in (
        "story", "script", "storyboard", "image_prompts", "video_prompts", "voice", "song",
        "image_assets", "video_assets", "editing", "thumbnail", "seo", "licensing",
        "final_review", "export",
    ):
        assert required in task_types


def test_create_default_episode_tasks_is_idempotent(session: Session) -> None:
    ts = ProductionTaskService()
    episode = _episode(session)
    ts.create_default_episode_tasks(session, episode.id)
    second = ts.create_default_episode_tasks(session, episode.id)
    assert second == []
    assert len(ts.list_tasks(session, episode.id)) == len(DEFAULT_EPISODE_TASK_TYPES)


def test_complete_and_reopen_task(session: Session) -> None:
    ts = ProductionTaskService()
    episode = _episode(session)
    task = ts.create_task(session, episode.id, task_type="script", title="Write script")
    ts.complete_task(session, task.id)
    assert task.status == ProductionTaskStatus.DONE
    ts.reopen_task(session, task.id)
    assert task.status == ProductionTaskStatus.PENDING


def test_delete_task(session: Session) -> None:
    ts = ProductionTaskService()
    episode = _episode(session)
    task = ts.create_task(session, episode.id, task_type="script", title="Write script")
    ts.delete_task(session, task.id)
    assert ts.list_tasks(session, episode.id) == []


def test_calculate_task_progress(session: Session) -> None:
    ts = ProductionTaskService()
    episode = _episode(session)
    t1 = ts.create_task(session, episode.id, task_type="a", title="A")
    ts.create_task(session, episode.id, task_type="b", title="B")
    ts.complete_task(session, t1.id)

    progress = ts.calculate_task_progress(session, episode.id)
    assert progress.total == 2
    assert progress.completed == 1
    assert progress.percent == 50.0


def test_calculate_task_progress_zero_tasks(session: Session) -> None:
    ts = ProductionTaskService()
    episode = _episode(session)
    progress = ts.calculate_task_progress(session, episode.id)
    assert progress.total == 0
    assert progress.percent == 0.0


def test_list_overdue_tasks_returns_blocked_tasks(session: Session) -> None:
    ts = ProductionTaskService()
    episode = _episode(session)
    blocked = ts.create_task(
        session, episode.id, task_type="voice", title="Voice",
        status=ProductionTaskStatus.BLOCKED,
    )
    ts.create_task(session, episode.id, task_type="script", title="Script")

    overdue = ts.list_overdue_tasks(session, episode.id)
    assert [t.id for t in overdue] == [blocked.id]


def test_list_overdue_tasks_across_all_episodes_when_no_filter(session: Session) -> None:
    ts = ProductionTaskService()
    ep1 = _episode(session)
    ep2 = Episode(slug="ep002_test", number=2, title_ar="ع", title_en="Test2", lesson="Kindness")
    session.add(ep2)
    session.flush()

    ts.create_task(session, ep1.id, task_type="voice", title="V", status=ProductionTaskStatus.BLOCKED)
    ts.create_task(session, ep2.id, task_type="song", title="S", status=ProductionTaskStatus.BLOCKED)

    assert len(ts.list_overdue_tasks(session)) == 2
    assert len(ts.list_overdue_tasks(session, ep1.id)) == 1
