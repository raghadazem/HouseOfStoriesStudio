"""Tests for ReviewQueuePage: empty state, real data, search/filter, approve/reject."""

from __future__ import annotations

from app.core.db.enums import ApprovalStatus, AssetType
from app.core.models import Asset
from app.gui.context import ApplicationContext
from app.gui.pages.review_queue_page import ReviewQueuePage, _RejectReasonDialog
from app.gui.theme.manager import ThemeManager


def _asset(**overrides: object) -> Asset:
    defaults: dict[str, object] = {
        "asset_type": AssetType.IMAGE,
        "original_filename": "f.png",
        "relative_path": "episodes/ep001/images/f.png",
        "checksum": "a" * 64,
    }
    defaults.update(overrides)
    return Asset(**defaults)


def test_shows_empty_state_on_fresh_database(
    qtbot, gui_context: ApplicationContext, theme: ThemeManager
) -> None:
    page = ReviewQueuePage(gui_context, theme)
    qtbot.addWidget(page)
    page.show()  # isVisible() only reflects reality once the widget chain is shown
    assert page._empty_state.isVisible()
    assert page._rows == []


def test_shows_only_draft_assets(qtbot, gui_context: ApplicationContext, theme: ThemeManager) -> None:
    with gui_context.session_scope() as session:
        session.add(_asset(original_filename="pending.png", relative_path="episodes/ep001/images/pending.png"))
        session.add(
            _asset(
                original_filename="approved.png", relative_path="episodes/ep001/images/approved.png",
                checksum="b" * 64, approval_status=ApprovalStatus.APPROVED,
            )
        )

    page = ReviewQueuePage(gui_context, theme)
    qtbot.addWidget(page)

    assert len(page._rows) == 1
    assert page._rows[0][0].original_filename == "pending.png"


def test_refresh_emits_review_count_updated(
    qtbot, gui_context: ApplicationContext, theme: ThemeManager
) -> None:
    with gui_context.session_scope() as session:
        session.add(_asset())

    page = ReviewQueuePage(gui_context, theme)
    qtbot.addWidget(page)

    with qtbot.waitSignal(page.review_count_updated, timeout=1000) as blocker:
        page.refresh()
    assert blocker.args == [1]


def test_search_filters_rows_live(qtbot, gui_context: ApplicationContext, theme: ThemeManager) -> None:
    with gui_context.session_scope() as session:
        session.add(_asset(original_filename="cat.png", relative_path="episodes/ep001/images/cat.png"))
        session.add(
            _asset(
                original_filename="dog.png", relative_path="episodes/ep001/images/dog.png",
                checksum="b" * 64,
            )
        )

    page = ReviewQueuePage(gui_context, theme)
    qtbot.addWidget(page)
    page.show()  # isVisible() only reflects reality once the widget chain is shown

    page._search._field.setText("cat")
    visible = [a.original_filename for a, row in page._rows if row.isVisible()]
    assert visible == ["cat.png"]


def test_source_filter_narrows_rows(qtbot, gui_context: ApplicationContext, theme: ThemeManager) -> None:
    with gui_context.session_scope() as session:
        session.add(
            _asset(
                original_filename="ai.png", relative_path="episodes/ep001/images/ai.png",
                source_tool="mock_provider",
            )
        )
        session.add(
            _asset(original_filename="manual.png", relative_path="episodes/ep001/images/manual.png", checksum="b" * 64)
        )

    page = ReviewQueuePage(gui_context, theme)
    qtbot.addWidget(page)
    page.show()  # isVisible() only reflects reality once the widget chain is shown

    from app.gui.pages.review_queue_page import _SOURCE_MANUAL

    index = page._source_filter.findData(_SOURCE_MANUAL)
    page._source_filter.setCurrentIndex(index)
    visible = [a.original_filename for a, row in page._rows if row.isVisible()]
    assert visible == ["manual.png"]


def test_reject_reason_dialog_requires_notes() -> None:
    dialog = _RejectReasonDialog("f.png")
    assert dialog.validate() == "A reason is required to reject an asset."
    dialog.reason_field.setPlainText("blurry")
    assert dialog.validate() is None


def test_on_approve_updates_status_and_removes_row(
    qtbot, gui_context: ApplicationContext, theme: ThemeManager
) -> None:
    with gui_context.session_scope() as session:
        session.add(_asset())

    page = ReviewQueuePage(gui_context, theme)
    qtbot.addWidget(page)
    asset, _row = page._rows[0]

    page._on_approve(asset)

    assert page._rows == []
    with gui_context.open_session() as session:
        refreshed = session.get(Asset, asset.id)
        assert refreshed.approval_status == ApprovalStatus.APPROVED


def test_on_reject_updates_status_with_notes(
    qtbot, gui_context: ApplicationContext, theme: ThemeManager, monkeypatch
) -> None:
    with gui_context.session_scope() as session:
        session.add(_asset())

    page = ReviewQueuePage(gui_context, theme)
    qtbot.addWidget(page)
    asset, _row = page._rows[0]

    def fake_exec(self):
        self.reason_field.setPlainText("blurry, redo")
        return _RejectReasonDialog.DialogCode.Accepted

    monkeypatch.setattr(_RejectReasonDialog, "exec", fake_exec)
    page._on_reject(asset)

    assert page._rows == []
    with gui_context.open_session() as session:
        refreshed = session.get(Asset, asset.id)
        assert refreshed.approval_status == ApprovalStatus.REJECTED
