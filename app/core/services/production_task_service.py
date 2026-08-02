"""ProductionTaskService — the per-episode production checklist.

``task_type`` is a free-text string, not an enum (see the model
docstring): the set of possible tasks is defined by the founder's own
workflow, not fixed by the schema. :data:`DEFAULT_EPISODE_TASK_TYPES`
is just a starting checklist, not an exhaustive list of allowed values.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.db.enums import ProductionTaskStatus
from app.core.models import Episode, ProductionTask
from app.core.services.exceptions import NotFoundError, ValidationError

# (task_type, default title) — covers every stage the founder listed:
# story, script, storyboard, image prompts, video prompts, voice, song,
# image assets, video assets, editing, thumbnail, seo, licensing, final
# review, export.
DEFAULT_EPISODE_TASK_TYPES: tuple[tuple[str, str], ...] = (
    ("story", "Write story / idea"),
    ("script", "Write script"),
    ("storyboard", "Create storyboard"),
    ("image_prompts", "Write image prompts"),
    ("video_prompts", "Write video prompts"),
    ("voice", "Record / generate voice"),
    ("song", "Produce original song"),
    ("image_assets", "Generate / import image assets"),
    ("video_assets", "Generate / import video assets"),
    ("editing", "Edit final video"),
    ("thumbnail", "Create thumbnail"),
    ("seo", "Write SEO metadata"),
    ("licensing", "Confirm licensing / commercial-use status"),
    ("final_review", "Final review"),
    ("export", "Generate export package"),
)

_UPDATABLE_FIELDS = {"title", "description", "task_type", "status"}


@dataclass(frozen=True)
class TaskProgress:
    """Result of :meth:`ProductionTaskService.calculate_task_progress`."""

    total: int
    completed: int
    percent: float


class ProductionTaskService:
    """CRUD and progress tracking for an episode's production checklist."""

    def create_task(
        self,
        session: Session,
        episode_id: uuid.UUID,
        *,
        task_type: str,
        title: str,
        description: str | None = None,
        status: ProductionTaskStatus = ProductionTaskStatus.PENDING,
    ) -> ProductionTask:
        if session.get(Episode, episode_id) is None:
            raise NotFoundError(f"Episode {episode_id} not found.")
        task = ProductionTask(
            episode_id=episode_id,
            task_type=task_type,
            title=title,
            description=description,
            status=status,
        )
        session.add(task)
        session.flush()
        return task

    def get_task(self, session: Session, task_id: uuid.UUID) -> ProductionTask:
        task = session.get(ProductionTask, task_id)
        if task is None:
            raise NotFoundError(f"ProductionTask {task_id} not found.")
        return task

    def update_task(self, session: Session, task_id: uuid.UUID, **fields: object) -> ProductionTask:
        task = self.get_task(session, task_id)
        unknown = set(fields) - _UPDATABLE_FIELDS
        if unknown:
            raise ValidationError(f"Cannot update unknown ProductionTask fields: {sorted(unknown)}")
        for key, value in fields.items():
            setattr(task, key, value)
        session.flush()
        return task

    def complete_task(self, session: Session, task_id: uuid.UUID) -> ProductionTask:
        task = self.get_task(session, task_id)
        task.status = ProductionTaskStatus.DONE
        session.flush()
        return task

    def reopen_task(self, session: Session, task_id: uuid.UUID) -> ProductionTask:
        task = self.get_task(session, task_id)
        task.status = ProductionTaskStatus.PENDING
        session.flush()
        return task

    def delete_task(self, session: Session, task_id: uuid.UUID) -> None:
        task = self.get_task(session, task_id)
        session.delete(task)
        session.flush()

    def list_tasks(
        self,
        session: Session,
        episode_id: uuid.UUID,
        *,
        status: ProductionTaskStatus | None = None,
    ) -> list[ProductionTask]:
        query = session.query(ProductionTask).filter_by(episode_id=episode_id)
        if status is not None:
            query = query.filter_by(status=status)
        return query.order_by(ProductionTask.created_at).all()

    def list_overdue_tasks(
        self, session: Session, episode_id: uuid.UUID | None = None
    ) -> list[ProductionTask]:
        """Tasks currently marked ``blocked``.

        There is no due-date column on ``ProductionTask`` — for a solo
        creator with no formal scheduling, "blocked" (something is
        stopping this task from moving) is the actionable "needs
        attention" signal, so that's what this treats as overdue.
        """
        query = session.query(ProductionTask).filter(
            ProductionTask.status == ProductionTaskStatus.BLOCKED
        )
        if episode_id is not None:
            query = query.filter_by(episode_id=episode_id)
        return query.order_by(ProductionTask.created_at).all()

    def create_default_episode_tasks(
        self, session: Session, episode_id: uuid.UUID
    ) -> list[ProductionTask]:
        """Create the standard checklist for an episode, skipping any task_type that already exists."""
        if session.get(Episode, episode_id) is None:
            raise NotFoundError(f"Episode {episode_id} not found.")
        existing_types = {task.task_type for task in self.list_tasks(session, episode_id)}
        created: list[ProductionTask] = []
        for task_type, title in DEFAULT_EPISODE_TASK_TYPES:
            if task_type in existing_types:
                continue
            task = ProductionTask(
                episode_id=episode_id,
                task_type=task_type,
                title=title,
                status=ProductionTaskStatus.PENDING,
            )
            session.add(task)
            created.append(task)
        session.flush()
        return created

    def calculate_task_progress(self, session: Session, episode_id: uuid.UUID) -> TaskProgress:
        tasks = self.list_tasks(session, episode_id)
        total = len(tasks)
        completed = sum(1 for task in tasks if task.status == ProductionTaskStatus.DONE)
        percent = round((completed / total * 100), 1) if total else 0.0
        return TaskProgress(total=total, completed=completed, percent=percent)
