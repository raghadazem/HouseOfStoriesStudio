"""Tests for the Scene Images workspace: readiness, generation, key-image selection.

Every real-generation path here uses ``mock_provider`` — no automated
test calls the real Gemini API (see Milestone 7/8 testing policy).
"""

from __future__ import annotations

import uuid

import pytest
from PySide6.QtWidgets import QLabel, QPushButton

from app.core.db.enums import ApprovalStatus, AssetType
from app.core.models import Asset, Character, Episode
from app.gui.context import ApplicationContext
from app.gui.pages import scene_image_workflow as siw
from app.gui.theme.manager import ThemeManager

_LOCK_FIELDS = {
    "visual_summary": "Two ponytails, denim dress.",
    "master_prompt": "Melissa: a cheerful 6-year-old girl.",
    "negative_prompt": "no extra characters",
    "color_palette": ["denim blue"],
    "relative_height": "taller than Bilsan",
}


def _episode(gui_context: ApplicationContext) -> uuid.UUID:
    with gui_context.session_scope() as session:
        episode = Episode(
            slug=f"ep-{uuid.uuid4().hex[:8]}", number=1, title_ar="ح", title_en="Ep", lesson="L"
        )
        session.add(episode)
        session.flush()
        return episode.id


def _ready_character(gui_context: ApplicationContext, slug: str, name_en: str) -> uuid.UUID:
    with gui_context.session_scope() as session:
        character = Character(slug=slug, name_ar=slug, name_en=name_en)
        session.add(character)
        session.flush()
        version = gui_context.character_version_service.create_character_version(
            session, character.id, **_LOCK_FIELDS
        )
        asset = Asset(
            asset_type=AssetType.IMAGE,
            original_filename="ref.png",
            relative_path=f"characters/{slug}/versions/{version.id}/ref.png",
            checksum=uuid.uuid4().hex.ljust(64, "0"),
            approval_status=ApprovalStatus.APPROVED,
        )
        session.add(asset)
        session.flush()
        reference = gui_context.character_version_service.add_character_reference(
            session, character_id=character.id, character_version_id=version.id, asset_id=asset.id
        )
        gui_context.character_version_service.set_canon_reference(session, reference.id)
        gui_context.character_version_service.submit_character_version_for_review(session, version.id)
        gui_context.character_version_service.approve_character_version(
            session, version.id, decided_by="founder"
        )
        gui_context.character_version_service.set_active_character_version(
            session, character.id, version.id
        )
        return character.id


def _scene(
    gui_context: ApplicationContext, episode_id: uuid.UUID, character_ids: list[uuid.UUID], **overrides
) -> uuid.UUID:
    prompt_text = overrides.pop("prompt_text", "A quiet forest at dawn.")
    with gui_context.session_scope() as session:
        scene = gui_context.scene_service.add_scene(
            session, episode_id, character_ids=character_ids, **overrides
        )
        if prompt_text is not None:
            gui_context.scene_service.update_scene(session, scene.id, prompt_text=prompt_text)
        return scene.id


@pytest.fixture(autouse=True)
def _no_real_gemini_key(monkeypatch: pytest.MonkeyPatch) -> None:
    # Hermetic regardless of the real machine's ambient environment —
    # see tests/gui/test_dashboard.py's dashboard fixture for the same
    # established pattern.
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)


# --- panel rendering ---------------------------------------------------------


def test_panel_shows_empty_state_with_no_scenes(
    qtbot, gui_context: ApplicationContext, theme: ThemeManager
) -> None:
    episode_id = _episode(gui_context)
    panel = siw.SceneImagesPanel(gui_context, theme)
    qtbot.addWidget(panel)
    panel.show()  # isVisible() only reflects reality once the widget chain is shown

    panel.refresh(episode_id)

    assert panel._empty_state.isVisible()


def test_panel_shows_blocked_scene_with_named_character(
    qtbot, gui_context: ApplicationContext, theme: ThemeManager
) -> None:
    episode_id = _episode(gui_context)
    with gui_context.session_scope() as session:
        character = Character(slug="melissa", name_ar="م", name_en="Melissa")
        session.add(character)
        session.flush()
        character_id = character.id
    _scene(gui_context, episode_id, [character_id])

    panel = siw.SceneImagesPanel(gui_context, theme)
    qtbot.addWidget(panel)
    panel.refresh(episode_id)

    labels = [label.text() for label in panel.findChildren(QLabel)]
    assert any("Blocked" in text for text in labels)
    assert any("Melissa" in text for text in labels)
    buttons = {btn.text(): btn for btn in panel.findChildren(QPushButton)}
    assert buttons["Generate"].isEnabled() is False


def test_panel_shows_ready_scene_with_generate_enabled(
    qtbot, gui_context: ApplicationContext, theme: ThemeManager
) -> None:
    episode_id = _episode(gui_context)
    melissa_id = _ready_character(gui_context, "melissa", "Melissa")
    bilsan_id = _ready_character(gui_context, "bilsan", "Bilsan")
    _scene(gui_context, episode_id, [melissa_id, bilsan_id])

    panel = siw.SceneImagesPanel(gui_context, theme)
    qtbot.addWidget(panel)
    panel.refresh(episode_id)

    labels = [label.text() for label in panel.findChildren(QLabel)]
    assert any("Ready" in text for text in labels)
    assert any("Melissa" in text for text in labels)
    assert any("Bilsan" in text for text in labels)
    buttons = {btn.text(): btn for btn in panel.findChildren(QPushButton)}
    assert buttons["Generate"].isEnabled() is True


# --- generate dialog ---------------------------------------------------------


def test_generate_dialog_lists_mock_provider_and_shows_prompt(
    qtbot, gui_context: ApplicationContext
) -> None:
    episode_id = _episode(gui_context)
    melissa_id = _ready_character(gui_context, "melissa", "Melissa")
    scene_id = _scene(gui_context, episode_id, [melissa_id])

    dialog = siw._GenerateSceneImageDialog(gui_context, scene_id)
    qtbot.addWidget(dialog)

    provider_names = [dialog.provider_field.itemData(i) for i in range(dialog.provider_field.count())]
    assert "mock_provider" in provider_names

    request = dialog.build_request(episode_id)
    assert request.scene_id == scene_id
    assert request.image_size == "1K"  # Standard is the default selection


# --- candidate review + set as key image -------------------------------------


def test_scene_candidate_review_runs_batch_and_set_as_key_image(
    qtbot, gui_context: ApplicationContext, theme: ThemeManager
) -> None:
    episode_id = _episode(gui_context)
    melissa_id = _ready_character(gui_context, "melissa", "Melissa")
    scene_id = _scene(gui_context, episode_id, [melissa_id])

    request = siw.SceneImageBatchRequest(
        provider_name="mock_provider", scene_id=scene_id, episode_id=episode_id, candidate_count=1
    )
    dialog = siw._SceneCandidateReviewDialog(gui_context, theme, scene_id, request)
    qtbot.addWidget(dialog)
    with qtbot.waitSignal(dialog._worker.batch_finished, timeout=5000):
        pass

    with gui_context.open_session() as session:
        jobs = gui_context.generation_job_service.list_jobs_for_batch(session, dialog._batch_id)
    job = jobs[0]
    assert job.parameters["image_size"] == "1K"
    assert job.parameters["character_references"][0]["character_id"] == str(melissa_id)

    dialog._on_approve(job.result_asset_id)
    dialog._on_set_key_image(job.result_asset_id)

    with gui_context.open_session() as session:
        asset = session.get(Asset, job.result_asset_id)
        assert asset.role == "final_scene_image"
    assert dialog.changed is True


def test_scene_candidate_review_cancel_pending_job_surfaces_error_without_hanging(
    qtbot, gui_context: ApplicationContext, theme: ThemeManager, monkeypatch
) -> None:
    """Proves _show_error's override routes through this module (not a
    blocking real QMessageBox) — the same hang this module's dialog
    would hit if the CandidateReviewDialogBase extraction regressed."""
    episode_id = _episode(gui_context)
    melissa_id = _ready_character(gui_context, "melissa", "Melissa")
    scene_id = _scene(gui_context, episode_id, [melissa_id])

    request = siw.SceneImageBatchRequest(
        provider_name="mock_provider", scene_id=scene_id, episode_id=episode_id, candidate_count=1
    )
    dialog = siw._SceneCandidateReviewDialog(gui_context, theme, scene_id, request)
    qtbot.addWidget(dialog)
    with qtbot.waitSignal(dialog._worker.batch_finished, timeout=5000):
        pass

    with gui_context.open_session() as session:
        jobs = gui_context.generation_job_service.list_jobs_for_batch(session, dialog._batch_id)
    job_id = jobs[0].id

    errors = []
    monkeypatch.setattr(
        siw, "show_error", lambda _parent, title, message: errors.append((title, message))
    )
    dialog._on_cancel(job_id)  # already succeeded -> can't cancel -> domain error
    assert len(errors) == 1
