"""Tests for AssetsPage: empty state, real data, thumbnails, search/filter, import flow."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QColor, QPixmap

from app.core.db.enums import ApprovalStatus, AssetType
from app.core.models import Asset
from app.core.services.asset_import_service import ImportRequest
from app.gui.context import ApplicationContext
from app.gui.pages.assets_page import AssetsPage, _ImportAssetDialog
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
    page = AssetsPage(gui_context, theme)
    qtbot.addWidget(page)
    page.show()  # isVisible() only reflects reality once the widget chain is shown
    assert page._empty_state.isVisible()
    assert page._cards == []


def test_shows_real_assets_after_seeding(
    qtbot, gui_context: ApplicationContext, theme: ThemeManager
) -> None:
    with gui_context.session_scope() as session:
        session.add(_asset(original_filename="draft.png"))

    page = AssetsPage(gui_context, theme)
    qtbot.addWidget(page)

    assert len(page._cards) == 1
    _asset_obj, card = page._cards[0]
    assert card._title_label.text() == "draft.png"


def test_search_filters_cards_live(qtbot, gui_context: ApplicationContext, theme: ThemeManager) -> None:
    with gui_context.session_scope() as session:
        session.add(
            _asset(original_filename="cat.png", relative_path="episodes/ep001/images/cat.png", checksum="a" * 64)
        )
        session.add(
            _asset(original_filename="dog.png", relative_path="episodes/ep001/images/dog.png", checksum="b" * 64)
        )

    page = AssetsPage(gui_context, theme)
    qtbot.addWidget(page)
    page.show()  # isVisible() only reflects reality once the widget chain is shown

    page._search._field.setText("cat")
    visible = [a.original_filename for a, card in page._cards if card.isVisible()]
    assert visible == ["cat.png"]


def test_status_filter_narrows_cards(qtbot, gui_context: ApplicationContext, theme: ThemeManager) -> None:
    with gui_context.session_scope() as session:
        session.add(
            _asset(
                original_filename="draft.png", relative_path="episodes/ep001/images/draft.png",
                checksum="a" * 64,
            )
        )
        session.add(
            _asset(
                original_filename="approved.png", relative_path="episodes/ep001/images/approved.png",
                checksum="b" * 64, approval_status=ApprovalStatus.APPROVED,
            )
        )

    page = AssetsPage(gui_context, theme)
    qtbot.addWidget(page)
    page.show()  # isVisible() only reflects reality once the widget chain is shown

    index = page._status_filter.findData(ApprovalStatus.APPROVED)
    page._status_filter.setCurrentIndex(index)
    visible = [a.original_filename for a, card in page._cards if card.isVisible()]
    assert visible == ["approved.png"]


def test_load_thumbnail_returns_none_for_missing_file(
    qtbot, gui_context: ApplicationContext, theme: ThemeManager
) -> None:
    page = AssetsPage(gui_context, theme)
    qtbot.addWidget(page)
    asset = _asset(relative_path="episodes/ep001/images/does_not_exist.png")
    assert page._load_thumbnail(asset) is None


def test_load_thumbnail_returns_none_for_non_previewable_type(
    qtbot, gui_context: ApplicationContext, theme: ThemeManager
) -> None:
    page = AssetsPage(gui_context, theme)
    qtbot.addWidget(page)
    asset = _asset(asset_type=AssetType.DOCUMENT)
    assert page._load_thumbnail(asset) is None


def test_load_thumbnail_loads_a_real_image_from_managed_storage(
    qtbot, gui_context: ApplicationContext, theme: ThemeManager, tmp_path: Path
) -> None:
    source = tmp_path / "source.png"
    pixmap = QPixmap(40, 40)
    pixmap.fill(QColor("#6C5CE7"))
    pixmap.save(str(source))

    with gui_context.open_session() as session:
        imported = gui_context.asset_import_service.import_asset(
            session, ImportRequest(source_path=source, asset_type=AssetType.IMAGE)
        )

    page = AssetsPage(gui_context, theme)
    qtbot.addWidget(page)
    result = page._load_thumbnail(imported)
    assert result is not None
    assert not result.isNull()


def test_import_asset_dialog_requires_a_file() -> None:
    dialog = _ImportAssetDialog()
    assert dialog.validate() == "Choose a file to import first."


def test_import_asset_dialog_validates_once_a_file_is_chosen(tmp_path: Path) -> None:
    source = tmp_path / "a.png"
    source.write_bytes(b"not a real png, just bytes")
    dialog = _ImportAssetDialog()
    dialog.selected_path = source
    assert dialog.validate() is None


def test_on_import_asset_adds_a_real_card(
    qtbot, gui_context: ApplicationContext, theme: ThemeManager, monkeypatch, tmp_path: Path
) -> None:
    source = tmp_path / "new_asset.png"
    pixmap = QPixmap(20, 20)
    pixmap.fill(QColor("red"))
    pixmap.save(str(source))

    page = AssetsPage(gui_context, theme)
    qtbot.addWidget(page)
    assert page._cards == []

    def fake_exec(self):
        self.selected_path = source
        return _ImportAssetDialog.DialogCode.Accepted

    monkeypatch.setattr(_ImportAssetDialog, "exec", fake_exec)
    page._on_import_asset()

    assert len(page._cards) == 1
    assert page._cards[0][0].original_filename == "new_asset.png"


def test_on_import_asset_shows_error_on_duplicate(
    qtbot, gui_context: ApplicationContext, theme: ThemeManager, monkeypatch, tmp_path: Path
) -> None:
    source = tmp_path / "dup.png"
    pixmap = QPixmap(20, 20)
    pixmap.fill(QColor("blue"))
    pixmap.save(str(source))

    with gui_context.open_session() as session:
        gui_context.asset_import_service.import_asset(
            session, ImportRequest(source_path=source, asset_type=AssetType.IMAGE)
        )

    page = AssetsPage(gui_context, theme)
    qtbot.addWidget(page)

    def fake_exec(self):
        self.selected_path = source
        return _ImportAssetDialog.DialogCode.Accepted

    monkeypatch.setattr(_ImportAssetDialog, "exec", fake_exec)

    errors = []
    monkeypatch.setattr(
        "app.gui.pages.assets_page.show_error",
        lambda _parent, title, message: errors.append((title, message)),
    )
    page._on_import_asset()

    assert len(errors) == 1
    assert "already imported" in errors[0][1]
