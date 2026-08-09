"""ScriptService — the Episode Workspace's Script stage.

Mirrors ``CharacterVersionService``'s lifecycle shape exactly: a plain,
unreviewed self-transition for the author's own progress
(``draft`` -> ``ready``), then a reviewed transition recorded via
``ApprovalService`` (``ready`` -> ``approved``, or back to ``draft`` on
rejection). ``Script`` does not duplicate ``Episode.title_ar``/
``title_en``/``lesson``/``dialogue_language`` — those already exist on
``Episode`` and are edited via ``EpisodeService.update_episode``.
"""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.core.db.enums import ScriptStatus
from app.core.models import Episode, Script
from app.core.services.approval_service import ApprovalService
from app.core.services.exceptions import InvalidTransitionError, NotFoundError, ValidationError

_UPDATABLE_FIELDS = {"summary", "full_script", "notes"}


class ScriptService:
    """Manages the one-per-episode Script record and its status lifecycle."""

    def __init__(self, approval_service: ApprovalService | None = None) -> None:
        self._approvals = approval_service or ApprovalService()

    def get_or_create_script(self, session: Session, episode_id: uuid.UUID) -> Script:
        """Return this episode's Script, creating an empty draft one if needed.

        A Script always exists once the workspace's Script tab has been
        opened once — there is no separate "create script" action for
        the user to remember, since every episode has exactly one.
        """
        episode = session.get(Episode, episode_id)
        if episode is None:
            raise NotFoundError(f"Episode {episode_id} not found.")
        script = session.query(Script).filter_by(episode_id=episode_id).one_or_none()
        if script is None:
            script = Script(episode_id=episode_id, status=ScriptStatus.DRAFT)
            session.add(script)
            session.flush()
        return script

    def update_script(self, session: Session, script_id: uuid.UUID, **fields: object) -> Script:
        script = self._get(session, script_id)
        unknown = set(fields) - _UPDATABLE_FIELDS
        if unknown:
            raise ValidationError(f"Cannot update unknown Script fields: {sorted(unknown)}")
        for key, value in fields.items():
            setattr(script, key, value)
        session.flush()
        return script

    def submit_script_ready(self, session: Session, script_id: uuid.UUID) -> Script:
        script = self._get(session, script_id)
        if script.status != ScriptStatus.DRAFT:
            raise InvalidTransitionError(
                f"Only a draft script can be marked ready (current: {script.status.value})."
            )
        script.status = ScriptStatus.READY
        session.flush()
        return script

    def approve_script(
        self,
        session: Session,
        script_id: uuid.UUID,
        *,
        decided_by: str | None = None,
        notes: str | None = None,
    ) -> Script:
        script = self._get(session, script_id)
        if script.status != ScriptStatus.READY:
            raise InvalidTransitionError(
                f"Only a ready script can be approved (current: {script.status.value})."
            )
        script.status = ScriptStatus.APPROVED
        self._approvals.approve_entity(
            session, "script", script_id, decided_by=decided_by, notes=notes
        )
        session.flush()
        return script

    def reject_script(
        self,
        session: Session,
        script_id: uuid.UUID,
        *,
        notes: str,
        decided_by: str | None = None,
    ) -> Script:
        """Reject a ready (or already-approved) script, sending it back to draft.

        There is no dedicated "rejected" status — rejection is recorded
        permanently in the approval history, mirroring
        ``CharacterVersionService.reject_character_version`` exactly.
        """
        script = self._get(session, script_id)
        if script.status not in (ScriptStatus.READY, ScriptStatus.APPROVED):
            raise InvalidTransitionError(
                f"Only a ready or approved script can be rejected (current: {script.status.value})."
            )
        script.status = ScriptStatus.DRAFT
        self._approvals.reject_entity(
            session, "script", script_id, decided_by=decided_by, notes=notes
        )
        session.flush()
        return script

    @staticmethod
    def _get(session: Session, script_id: uuid.UUID) -> Script:
        script = session.get(Script, script_id)
        if script is None:
            raise NotFoundError(f"Script {script_id} not found.")
        return script
