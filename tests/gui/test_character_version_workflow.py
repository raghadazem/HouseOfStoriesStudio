"""Tests for the CharacterVersion workflow dialogs, worker wiring, and candidate review.

Every real-generation path here uses ``mock_provider`` — no automated
test calls the real Gemini API (see Milestone 7 testing policy). The
candidate-review tests exercise a real ``GenerationWorker`` QThread,
waited on via ``qtbot.waitSignal``, since that thread/session-safety
wiring is exactly what these tests must prove works.
"""

from __future__ import annotations

from PySide6.QtWidgets import QLabel, QPushButton

from app.core.db.enums import (
    ApprovalStatus,
    AssetType,
    CharacterVersionStatus,
    GenerationJobStatus,
    PromptCategory,
    PromptType,
)
from app.core.models import Asset, Character
from app.gui.context import ApplicationContext
from app.gui.pages import character_version_workflow as cvw
from app.gui.theme.manager import ThemeManager

_LOCK_FIELDS = {
    "visual_summary": "Two ponytails, denim dress.",
    "master_prompt": "Melissa: a cheerful 6-year-old girl.",
    "negative_prompt": "no extra characters",
    "color_palette": ["denim blue"],
    "relative_height": "taller than Bilsan",
}


def _find_combo_index(combo, data) -> int:
    """QComboBox.findData compares userData by identity for opaque Python
    objects (e.g. two value-equal but distinct uuid.UUID instances don't
    match) — a real PySide6 quirk, not a bug in the code under test.
    This helper compares by Python ``==`` instead."""
    for i in range(combo.count()):
        if combo.itemData(i) == data:
            return i
    return -1


def _character_id(gui_context: ApplicationContext) -> object:
    with gui_context.session_scope() as session:
        character = Character(slug="melissa", name_ar="م", name_en="Melissa")
        session.add(character)
        session.flush()
        return character.id


def _draft_version_id(gui_context: ApplicationContext, character_id, **fields) -> object:
    with gui_context.session_scope() as session:
        version = gui_context.character_version_service.create_character_version(
            session, character_id, **fields
        )
        return version.id


def _template_id(gui_context: ApplicationContext) -> object:
    with gui_context.session_scope() as session:
        template = gui_context.prompt_template_service.create_prompt_template(
            session,
            name="char_ref",
            category=PromptCategory.CHARACTER,
            prompt_type=PromptType.IMAGE,
            text_en="A picture of {{ character_master_prompt }}.",
        )
        return template.id


def _approved_reference_asset(gui_context: ApplicationContext, character_id, version_id) -> None:
    _add_reference(gui_context, character_id, version_id, suffix="a")


def _add_reference(gui_context: ApplicationContext, character_id, version_id, *, suffix: str) -> object:
    with gui_context.session_scope() as session:
        asset = Asset(
            asset_type=AssetType.IMAGE,
            original_filename=f"ref_{suffix}.png",
            relative_path=f"characters/melissa/ref_{suffix}.png",
            checksum=suffix * 64,
            approval_status=ApprovalStatus.APPROVED,
        )
        session.add(asset)
        session.flush()
        reference = gui_context.character_version_service.add_character_reference(
            session, character_id=character_id, character_version_id=version_id, asset_id=asset.id
        )
        return reference.id


# --- _EditCharacterVersionDialog --------------------------------------------


def test_edit_character_version_dialog_round_trips_fields() -> None:
    dialog = cvw._EditCharacterVersionDialog(None)
    dialog.visual_summary_field.setPlainText("Summary")
    dialog.master_prompt_field.setPlainText("Prompt")
    dialog.negative_prompt_field.setPlainText("Neg")
    dialog.color_palette_field.setText("red,  blue")
    dialog.relative_height_field.setText("tall")
    dialog.allowed_accessories_field.setText("hat")
    dialog.outfit_version_field.setText("v1")

    fields = dialog.result_fields()

    assert fields["visual_summary"] == "Summary"
    assert fields["master_prompt"] == "Prompt"
    assert fields["color_palette"] == ["red", "blue"]
    assert fields["allowed_accessories"] == ["hat"]
    assert fields["outfit_version"] == "v1"


def test_create_character_version_creates_draft(gui_context: ApplicationContext, monkeypatch) -> None:
    character_id = _character_id(gui_context)

    def fake_exec(self):
        self.master_prompt_field.setPlainText("A hand-authored prompt")
        return cvw.FormDialog.DialogCode.Accepted

    monkeypatch.setattr(cvw._EditCharacterVersionDialog, "exec", fake_exec)

    version_id = cvw.create_character_version(gui_context, character_id, None)

    assert version_id is not None
    with gui_context.open_session() as session:
        character = gui_context.character_service.get_character(session, character_id)
        version = next(v for v in character.versions if v.id == version_id)
        assert version.master_prompt == "A hand-authored prompt"
        assert version.status == CharacterVersionStatus.DRAFT


# --- _CharacterVersionDetailDialog ------------------------------------------


def test_detail_dialog_shows_missing_lock_fields(
    qtbot, gui_context: ApplicationContext, theme: ThemeManager
) -> None:
    character_id = _character_id(gui_context)
    version_id = _draft_version_id(gui_context, character_id)  # everything empty

    with gui_context.open_session() as session:
        character = gui_context.character_service.get_character(session, character_id)
        dialog = cvw._CharacterVersionDetailDialog(gui_context, theme, character, version_id)
    qtbot.addWidget(dialog)

    labels = [label.text() for label in dialog.findChildren(QLabel)]
    assert any("Missing:" in text for text in labels)
    assert any("Master prompt" in text for text in labels)


def test_detail_dialog_submit_approve_and_activate_flow(
    qtbot, gui_context: ApplicationContext, theme: ThemeManager, monkeypatch
) -> None:
    character_id = _character_id(gui_context)
    version_id = _draft_version_id(gui_context, character_id, **_LOCK_FIELDS)
    _approved_reference_asset(gui_context, character_id, version_id)

    with gui_context.open_session() as session:
        character = gui_context.character_service.get_character(session, character_id)
        dialog = cvw._CharacterVersionDetailDialog(gui_context, theme, character, version_id)
    qtbot.addWidget(dialog)

    dialog._on_submit()
    with gui_context.open_session() as session:
        character = gui_context.character_service.get_character(session, character_id)
        version = next(v for v in character.versions if v.id == version_id)
        assert version.status == CharacterVersionStatus.IN_REVIEW

    dialog._on_approve()
    with gui_context.open_session() as session:
        character = gui_context.character_service.get_character(session, character_id)
        version = next(v for v in character.versions if v.id == version_id)
        assert version.status == CharacterVersionStatus.APPROVED_CANON

    monkeypatch.setattr(cvw, "confirm", lambda *args, **kwargs: True)
    dialog._on_set_active()
    with gui_context.open_session() as session:
        character = gui_context.character_service.get_character(session, character_id)
        assert character.active_version_id == version_id

    assert dialog.needs_refresh is True


def test_detail_dialog_reject_returns_to_draft(
    qtbot, gui_context: ApplicationContext, theme: ThemeManager, monkeypatch
) -> None:
    character_id = _character_id(gui_context)
    version_id = _draft_version_id(gui_context, character_id, **_LOCK_FIELDS)
    _approved_reference_asset(gui_context, character_id, version_id)

    with gui_context.open_session() as session:
        character = gui_context.character_service.get_character(session, character_id)
        dialog = cvw._CharacterVersionDetailDialog(gui_context, theme, character, version_id)
    qtbot.addWidget(dialog)
    dialog._on_submit()

    def fake_exec(self):
        self.reason_field.setPlainText("Off-model colors.")
        return cvw.FormDialog.DialogCode.Accepted

    monkeypatch.setattr(cvw._RejectVersionDialog, "exec", fake_exec)
    dialog._on_reject()

    with gui_context.open_session() as session:
        character = gui_context.character_service.get_character(session, character_id)
        version = next(v for v in character.versions if v.id == version_id)
        assert version.status == CharacterVersionStatus.DRAFT
        assert version.review_notes == "Off-model colors."


# --- _GenerateReferenceDialog -------------------------------------------------


def test_generate_reference_dialog_lists_mock_provider_and_previews_prompt(
    gui_context: ApplicationContext, monkeypatch
) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    character_id = _character_id(gui_context)
    version_id = _draft_version_id(gui_context, character_id, **_LOCK_FIELDS)
    template_id = _template_id(gui_context)

    dialog = cvw._GenerateReferenceDialog(gui_context, version_id)

    provider_index = _find_combo_index(dialog.provider_field, "mock_provider")
    assert provider_index != -1
    dialog.provider_field.setCurrentIndex(provider_index)

    template_index = _find_combo_index(dialog.template_field, template_id)
    assert template_index != -1
    dialog.template_field.setCurrentIndex(template_index)

    assert "cheerful" in dialog.preview_field.toPlainText()

    request = dialog.build_request(character_id)
    assert request.provider_name == "mock_provider"
    assert request.prompt_template_id == template_id
    assert request.character_version_id == version_id


# --- _CandidateReviewDialog + real GenerationWorker (mock_provider) --------


def test_candidate_review_dialog_runs_batch_and_review_actions(
    qtbot, gui_context: ApplicationContext, theme: ThemeManager, monkeypatch
) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    character_id = _character_id(gui_context)
    version_id = _draft_version_id(gui_context, character_id, **_LOCK_FIELDS)
    template_id = _template_id(gui_context)

    with gui_context.open_session() as session:
        character = gui_context.character_service.get_character(session, character_id)

    request = cvw.CandidateBatchRequest(
        provider_name="mock_provider",
        prompt_template_id=template_id,
        character_version_id=version_id,
        character_id=character_id,
        candidate_count=2,
    )
    dialog = cvw._CandidateReviewDialog(gui_context, theme, character, version_id, request)
    qtbot.addWidget(dialog)

    with qtbot.waitSignal(dialog._worker.batch_finished, timeout=5000):
        pass

    assert "2 of 2" in dialog._status_label.text()
    with gui_context.open_session() as session:
        jobs = gui_context.generation_job_service.list_jobs_for_batch(session, dialog._batch_id)
    assert len(jobs) == 2
    assert all(job.status == GenerationJobStatus.SUCCEEDED for job in jobs)

    asset_id = jobs[0].result_asset_id
    dialog._on_approve(asset_id)
    with gui_context.open_session() as session:
        asset = session.get(Asset, asset_id)
        assert asset.approval_status == ApprovalStatus.APPROVED
    assert dialog.changed is True

    dialog._on_add_reference(asset_id)
    with gui_context.open_session() as session:
        refs = gui_context.character_version_service.list_character_references(
            session, character_id, version_id=version_id
        )
    assert any(ref.asset_id == asset_id for ref in refs)

    rejected_asset_id = jobs[1].result_asset_id
    dialog._on_reject(rejected_asset_id)
    with gui_context.open_session() as session:
        asset = session.get(Asset, rejected_asset_id)
        assert asset.approval_status == ApprovalStatus.REJECTED


def test_candidate_review_dialog_retry_after_provider_failure(
    qtbot, gui_context: ApplicationContext, theme: ThemeManager, monkeypatch
) -> None:
    """A failed candidate offers Retry; retrying creates a NEW job linked
    via retry_of_job_id, in the same batch."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    character_id = _character_id(gui_context)
    version_id = _draft_version_id(gui_context, character_id, **_LOCK_FIELDS)
    template_id = _template_id(gui_context)

    from app.core.ai.exceptions import ProviderRequestError
    from app.core.ai.provider_interface import AIProvider, GenerationRequest, GenerationResult

    class _FailingProvider(AIProvider):
        name = "failing_gui_test_provider"
        supported_modalities = frozenset({"image"})

        def is_configured(self) -> bool:
            return True

        def generate(self, request: GenerationRequest) -> GenerationResult:
            raise ProviderRequestError("simulated failure")

    monkeypatch.setitem(
        gui_context.ai_orchestrator._provider_registry, _FailingProvider.name, _FailingProvider
    )

    with gui_context.open_session() as session:
        character = gui_context.character_service.get_character(session, character_id)

    request = cvw.CandidateBatchRequest(
        provider_name=_FailingProvider.name,
        prompt_template_id=template_id,
        character_version_id=version_id,
        character_id=character_id,
        candidate_count=1,
    )
    dialog = cvw._CandidateReviewDialog(gui_context, theme, character, version_id, request)
    qtbot.addWidget(dialog)
    with qtbot.waitSignal(dialog._worker.batch_finished, timeout=5000):
        pass

    with gui_context.open_session() as session:
        jobs = gui_context.generation_job_service.list_jobs_for_batch(session, dialog._batch_id)
    assert len(jobs) == 1
    assert jobs[0].status == GenerationJobStatus.FAILED
    failed_job_id = jobs[0].id

    dialog._on_retry(failed_job_id)
    with qtbot.waitSignal(dialog._worker.batch_finished, timeout=5000):
        pass

    with gui_context.open_session() as session:
        jobs = gui_context.generation_job_service.list_jobs_for_batch(session, dialog._batch_id)
    assert len(jobs) == 2
    retry_job = next(j for j in jobs if j.retry_of_job_id == failed_job_id)
    assert retry_job.status == GenerationJobStatus.FAILED  # same failing provider


def test_candidate_review_dialog_cancel_pending_job(
    qtbot, gui_context: ApplicationContext, theme: ThemeManager, monkeypatch
) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    character_id = _character_id(gui_context)
    version_id = _draft_version_id(gui_context, character_id, **_LOCK_FIELDS)
    template_id = _template_id(gui_context)

    with gui_context.open_session() as session:
        character = gui_context.character_service.get_character(session, character_id)

    request = cvw.CandidateBatchRequest(
        provider_name="mock_provider",
        prompt_template_id=template_id,
        character_version_id=version_id,
        character_id=character_id,
        candidate_count=1,
    )
    dialog = cvw._CandidateReviewDialog(gui_context, theme, character, version_id, request)
    qtbot.addWidget(dialog)
    with qtbot.waitSignal(dialog._worker.batch_finished, timeout=5000):
        pass

    with gui_context.open_session() as session:
        jobs = gui_context.generation_job_service.list_jobs_for_batch(session, dialog._batch_id)
    job_id = jobs[0].id

    # Already succeeded jobs can't be cancelled — proves the dialog's
    # cancel handler surfaces the domain error (via a non-blocking fake
    # show_error, since the real QMessageBox is modal) rather than
    # crashing.
    errors = []
    monkeypatch.setattr(
        cvw, "show_error", lambda _parent, title, message: errors.append((title, message))
    )
    dialog._on_cancel(job_id)
    assert len(errors) == 1
    with gui_context.open_session() as session:
        job = gui_context.generation_job_service.get_job(session, job_id)
    assert job.status == GenerationJobStatus.SUCCEEDED


# --- Canon Reference action (Milestone 8) -----------------------------------


def test_detail_dialog_shows_canon_badge_and_make_canon_button(
    qtbot, gui_context: ApplicationContext, theme: ThemeManager
) -> None:
    character_id = _character_id(gui_context)
    version_id = _draft_version_id(gui_context, character_id, **_LOCK_FIELDS)
    reference_id = _add_reference(gui_context, character_id, version_id, suffix="a")
    with gui_context.session_scope() as session:
        gui_context.character_version_service.set_canon_reference(session, reference_id)
    _add_reference(gui_context, character_id, version_id, suffix="b")  # not canon

    with gui_context.open_session() as session:
        character = gui_context.character_service.get_character(session, character_id)
        dialog = cvw._CharacterVersionDetailDialog(gui_context, theme, character, version_id)
    qtbot.addWidget(dialog)

    labels = [label.text() for label in dialog.findChildren(QLabel)]
    assert any("Canon" in text for text in labels)
    buttons = [btn.text() for btn in dialog.findChildren(QPushButton)]
    # Exactly one non-canon reference exists, so exactly one Make Canon button.
    assert buttons.count("Make Canon") == 1


def test_detail_dialog_make_canon_switches_canon_reference(
    qtbot, gui_context: ApplicationContext, theme: ThemeManager
) -> None:
    character_id = _character_id(gui_context)
    version_id = _draft_version_id(gui_context, character_id, **_LOCK_FIELDS)
    reference_a = _add_reference(gui_context, character_id, version_id, suffix="a")
    with gui_context.session_scope() as session:
        gui_context.character_version_service.set_canon_reference(session, reference_a)
    reference_b = _add_reference(gui_context, character_id, version_id, suffix="b")

    with gui_context.open_session() as session:
        character = gui_context.character_service.get_character(session, character_id)
        dialog = cvw._CharacterVersionDetailDialog(gui_context, theme, character, version_id)
    qtbot.addWidget(dialog)

    dialog._on_make_canon(reference_b)

    with gui_context.open_session() as session:
        canon = gui_context.character_version_service.get_canon_reference(session, version_id)
        assert canon.id == reference_b
    assert dialog.needs_refresh is True
    # Exactly one canon badge remains — never both references marked canon.
    labels = [label.text() for label in dialog.findChildren(QLabel)]
    assert labels.count("★ Canon") == 1
