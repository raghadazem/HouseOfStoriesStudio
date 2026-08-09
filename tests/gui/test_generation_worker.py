"""Tests for GenerationWorker: the QThread bridge around generation_runner.

Uses ``mock_provider`` only — no automated test calls the real Gemini
API. Focuses on exactly what a worker must get right: it runs off the
main thread, emits plain ``JobSnapshot`` values (never a SQLAlchemy ORM
object tied to its own closed session), and turns a pre-flight failure
into ``batch_failed`` with a safe message instead of a crash.
"""

from __future__ import annotations

import threading

from app.core.db.enums import GenerationJobStatus, PromptCategory, PromptType
from app.core.models import Character
from app.gui.context import ApplicationContext
from app.gui.workers.generation_worker import CandidateBatchRequest, GenerationWorker, JobSnapshot


def _character_id(gui_context: ApplicationContext):
    with gui_context.session_scope() as session:
        character = Character(slug="melissa", name_ar="م", name_en="Melissa")
        session.add(character)
        session.flush()
        return character.id


def _template_id(gui_context: ApplicationContext):
    with gui_context.session_scope() as session:
        template = gui_context.prompt_template_service.create_prompt_template(
            session,
            name="char_ref",
            category=PromptCategory.CHARACTER,
            prompt_type=PromptType.IMAGE,
            text_en="A picture of {{ character_master_prompt }}.",
        )
        return template.id


def test_worker_runs_batch_off_the_main_thread_and_emits_snapshots(
    qtbot, gui_context: ApplicationContext
) -> None:
    character_id = _character_id(gui_context)
    with gui_context.session_scope() as session:
        version = gui_context.character_version_service.create_character_version(
            session,
            character_id,
            visual_summary="Two ponytails.",
            master_prompt="A cheerful girl.",
            negative_prompt="no extras",
            color_palette=["denim blue"],
            relative_height="taller than Bilsan",
        )
        version_id = version.id
    template_id = _template_id(gui_context)

    request = CandidateBatchRequest(
        provider_name="mock_provider",
        prompt_template_id=template_id,
        character_version_id=version_id,
        character_id=character_id,
        candidate_count=2,
    )
    run_thread_ids: list[int] = []

    class _ObservedWorker(GenerationWorker):
        def run(self) -> None:
            run_thread_ids.append(threading.get_ident())
            super().run()

    worker = _ObservedWorker(gui_context, request)

    updates: list[JobSnapshot] = []
    worker.job_updated.connect(lambda snap: updates.append(snap))

    main_thread_id = threading.get_ident()
    with qtbot.waitSignal(worker.batch_finished, timeout=5000) as blocker:
        worker.start()

    finished_snapshots = blocker.args[0]
    assert len(finished_snapshots) == 2
    assert all(isinstance(s, JobSnapshot) for s in finished_snapshots)
    assert all(s.status == GenerationJobStatus.SUCCEEDED for s in finished_snapshots)
    assert all(s.provider_name == "mock_provider" for s in finished_snapshots)
    assert len({s.id for s in finished_snapshots}) == 2
    assert len({s.batch_id for s in finished_snapshots}) == 1
    assert len(updates) >= 2  # at least one PENDING->RUNNING update per job

    # run() itself executed on a different OS thread than the test —
    # proving the worker actually did its work in the background, not
    # inline on the GUI thread.
    assert run_thread_ids[0] != main_thread_id

    # Snapshots are real data classes, never live ORM objects — safe to
    # read after the worker's own session has closed.
    for snap in updates:
        assert isinstance(snap.status, GenerationJobStatus)


def test_worker_emits_batch_failed_for_incomplete_character_lock(
    qtbot, gui_context: ApplicationContext
) -> None:
    character_id = _character_id(gui_context)
    with gui_context.session_scope() as session:
        version = gui_context.character_version_service.create_character_version(session, character_id)
        version_id = version.id  # every prompt field left empty
    template_id = _template_id(gui_context)

    request = CandidateBatchRequest(
        provider_name="mock_provider",
        prompt_template_id=template_id,
        character_version_id=version_id,
        character_id=character_id,
        candidate_count=1,
    )
    worker = GenerationWorker(gui_context, request)

    with qtbot.waitSignal(worker.batch_failed, timeout=5000) as blocker:
        worker.start()

    assert "missing" in blocker.args[0].lower() or "cannot be used" in blocker.args[0].lower()

    with gui_context.open_session() as session:
        jobs = gui_context.generation_job_service.list_jobs(session)
    assert jobs == []  # fails fast, before creating any job row


def test_worker_emits_batch_failed_for_unconfigured_provider(
    qtbot, gui_context: ApplicationContext, monkeypatch
) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    character_id = _character_id(gui_context)
    with gui_context.session_scope() as session:
        version = gui_context.character_version_service.create_character_version(
            session,
            character_id,
            visual_summary="Two ponytails.",
            master_prompt="A cheerful girl.",
            negative_prompt="no extras",
            color_palette=["denim blue"],
            relative_height="taller than Bilsan",
        )
        version_id = version.id
    template_id = _template_id(gui_context)

    request = CandidateBatchRequest(
        provider_name="gemini",
        prompt_template_id=template_id,
        character_version_id=version_id,
        character_id=character_id,
        candidate_count=1,
    )
    worker = GenerationWorker(gui_context, request)

    with qtbot.waitSignal(worker.batch_failed, timeout=5000) as blocker:
        worker.start()

    assert "not configured" in blocker.args[0].lower()
