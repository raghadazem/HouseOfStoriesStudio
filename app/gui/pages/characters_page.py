"""CharactersPage — browse, search, and create characters.

Also hosts the Character *design* workflow (Character Lock — creating/
editing draft versions, real AI reference generation, review/approval,
and activation), delegated to
:mod:`app.gui.pages.character_version_workflow` — this page owns the
roster grid and the character-identity CRUD ``CharacterService``
provides; the version detail dialog opened from here is where a
version's own lifecycle (owned by ``CharacterVersionService``) lives.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy.exc import OperationalError

from app.core.models import Character
from app.core.naming import slugify
from app.core.services.exceptions import ConflictError, ValidationError
from app.gui.context import ApplicationContext
from app.gui.pages.character_version_workflow import (
    create_character_version,
    open_character_version_detail,
)
from app.gui.theme.manager import ThemeManager
from app.gui.theme.tokens import METRICS
from app.gui.widgets import (
    EmptyState,
    EntityCard,
    EntityRow,
    ErrorState,
    FormDialog,
    LoadingOverlay,
    PageHeader,
    ResponsiveGrid,
    SearchBox,
    StatusBadge,
    ToolbarRow,
    show_error,
)

_LOCK_ALL = "all"
_LOCK_LOCKED = "locked"
_LOCK_UNLOCKED = "unlocked"

_VERSION_STATUS_VARIANT = {
    "draft": "neutral",
    "in_review": "info",
    "approved_canon": "success",
    "archived": "neutral",
}


class _CreateCharacterDialog(FormDialog):
    def __init__(self, existing_slugs: set[str], parent: QWidget | None = None) -> None:
        super().__init__(
            "New Character", icon="🧒", subtitle="Add them to the studio's roster",
            save_label="Create", parent=parent,
        )
        self._existing_slugs = existing_slugs

        self.name_en_field = QLineEdit()
        self.name_en_field.setPlaceholderText("Melissa")
        self.add_row("Name (English)", self.name_en_field)

        self.name_ar_field = QLineEdit()
        self.name_ar_field.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.name_ar_field.setPlaceholderText("ميليسا")
        self.add_row("Name (Arabic)", self.name_ar_field)

        self.role_field = QLineEdit()
        self.role_field.setPlaceholderText("Hero, best friend, mentor, ...")
        self.add_row("Role", self.role_field)

        self.age_field = QSpinBox()
        self.age_field.setRange(0, 999)
        self.age_field.setSpecialValueText("Not set")
        self.add_row("Age", self.age_field)

        self.traits_field = QLineEdit()
        self.traits_field.setPlaceholderText("curious, kind, brave (comma-separated)")
        self.add_row("Traits", self.traits_field)

    def validate(self) -> str | None:
        if not self.name_en_field.text().strip():
            return "Name (English) is required."
        if not self.name_ar_field.text().strip():
            return "Name (Arabic) is required."
        if slugify(self.name_en_field.text().strip(), fallback_prefix="character") in self._existing_slugs:
            return "A character with a matching name already exists."
        return None

    def result_fields(self) -> dict[str, object]:
        traits = [t.strip() for t in self.traits_field.text().split(",") if t.strip()]
        return {
            "slug": slugify(self.name_en_field.text().strip(), fallback_prefix="character"),
            "name_en": self.name_en_field.text().strip(),
            "name_ar": self.name_ar_field.text().strip(),
            "role": self.role_field.text().strip() or None,
            "age": self.age_field.value() or None,
            "traits": traits,
        }


class _CharacterDetailDialog(FormDialog):
    def __init__(
        self,
        ctx: ApplicationContext,
        theme: ThemeManager,
        character: Character,
        parent: QWidget | None = None,
        *,
        on_feedback: Callable[[str, str], None] | None = None,
    ) -> None:
        super().__init__(character.name_en, show_save=False, min_width=480, parent=parent)
        self._ctx = ctx
        self._theme = theme
        self._character_id = character.id
        self._on_feedback = on_feedback
        self.needs_refresh = False

        name_ar_field = QLineEdit(character.name_ar)
        name_ar_field.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        name_ar_field.setReadOnly(True)
        self.add_row("Name (Arabic)", name_ar_field)

        self._status_wrap = QWidget()
        self.add_row("Status", self._status_wrap)

        if character.traits:
            traits_field = QLineEdit(", ".join(character.traits))
            traits_field.setReadOnly(True)
            self.add_row("Traits", traits_field)

        versions_header = QHBoxLayout()
        versions_header.addWidget(QLabel("Design versions"))
        versions_header.addStretch(1)
        new_version_btn = QPushButton("+ New Version")
        new_version_btn.clicked.connect(self._on_new_version)
        versions_header.addWidget(new_version_btn)
        header_wrap = QWidget()
        header_wrap.setLayout(versions_header)
        self.content_layout.addWidget(header_wrap)

        self._versions_panel = QFrame()
        self._versions_panel.setProperty("class", "card")
        self._versions_layout = QVBoxLayout(self._versions_panel)
        self._versions_layout.setContentsMargins(
            METRICS.spacing_md, METRICS.spacing_md, METRICS.spacing_md, METRICS.spacing_md
        )
        self._versions_layout.setSpacing(METRICS.spacing_xs)
        self.content_layout.addWidget(self._versions_panel)

        self._render_versions(character)

    def _render_versions(self, character: Character) -> None:
        while self._versions_layout.count():
            item = self._versions_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

        meta_row = QHBoxLayout()
        if character.role:
            meta_row.addWidget(StatusBadge(character.role, "info"))
        if character.age is not None:
            meta_row.addWidget(StatusBadge(f"Age {character.age}", "neutral"))
        meta_row.addWidget(
            StatusBadge("Locked" if character.active_version_id else "No locked version",
                        "success" if character.active_version_id else "warning")
        )
        meta_row.addStretch(1)
        for i in reversed(range(self._status_wrap.layout().count() if self._status_wrap.layout() else 0)):
            self._status_wrap.layout().takeAt(i)
        self._status_wrap.setLayout(meta_row)

        if character.versions:
            for version in sorted(character.versions, key=lambda v: v.version_number, reverse=True):
                is_active = version.id == character.active_version_id
                row = EntityRow(
                    "🎨",
                    f"{version.version_number}" + ("  ★ active" if is_active else ""),
                )
                row.add_trailing_widget(
                    StatusBadge(
                        version.status.value.replace("_", " ").title(),
                        _VERSION_STATUS_VARIANT.get(version.status.value, "neutral"),
                    )
                )
                row.clicked.connect(lambda _checked=False, v=version.id: self._on_manage_version(v))
                self._versions_layout.addWidget(row)
        else:
            self._versions_layout.addWidget(EmptyState("No design versions yet.", icon="🎨"))

    def _reload(self) -> None:
        with self._ctx.open_session() as session:
            character = self._ctx.character_service.get_character(session, self._character_id)
            self._render_versions(character)

    def _on_new_version(self) -> None:
        version_id = create_character_version(self._ctx, self._character_id, self)
        if version_id is None:
            return
        self.needs_refresh = True
        self._reload()
        if self._on_feedback:
            self._on_feedback("New design version created.", "success")
        self._on_manage_version(version_id)

    def _on_manage_version(self, version_id: uuid.UUID) -> None:
        refreshed = open_character_version_detail(
            self._ctx, self._theme, self._character_id, version_id, self, on_feedback=self._on_feedback
        )
        if refreshed:
            self.needs_refresh = True
            self._reload()


class CharactersPage(QWidget):
    def __init__(
        self,
        ctx: ApplicationContext,
        theme: ThemeManager,
        parent: QWidget | None = None,
        *,
        on_feedback: Callable[[str, str], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("charactersPage")
        self._ctx = ctx
        self._theme = theme
        self._on_feedback = on_feedback
        self._characters: list[Character] = []
        self._cards: list[tuple[Character, EntityCard]] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        outer.addWidget(scroll)

        content = QWidget()
        content.setObjectName("scrollContent")
        scroll.setWidget(content)

        layout = QVBoxLayout(content)
        layout.setContentsMargins(
            METRICS.spacing_xl, METRICS.spacing_lg, METRICS.spacing_xl, METRICS.spacing_xl
        )
        layout.setSpacing(METRICS.spacing_lg)

        self._header = PageHeader(
            "Characters", "The studio's character roster", primary_label="+ New Character"
        )
        self._header.primary_action_triggered.connect(self._on_create_character)
        layout.addWidget(self._header)

        toolbar = ToolbarRow()
        self._search = SearchBox("Search characters…")
        self._search.text_changed.connect(self._apply_filters)
        toolbar.add_widget(self._search, stretch=1)

        self._lock_filter = QComboBox()
        self._lock_filter.addItem("All characters", _LOCK_ALL)
        self._lock_filter.addItem("Locked", _LOCK_LOCKED)
        self._lock_filter.addItem("Not locked", _LOCK_UNLOCKED)
        self._lock_filter.currentIndexChanged.connect(self._apply_filters)
        toolbar.add_widget(self._lock_filter)
        layout.addWidget(toolbar)

        self._count_label = QLabel("")
        self._count_label.setProperty("class", "resultCount")
        layout.addWidget(self._count_label)

        self._grid = ResponsiveGrid(card_min_width=180)
        layout.addWidget(self._grid)

        self._empty_state = EmptyState(
            "No characters yet — add the first one to start building your cast.",
            icon="🧒",
            action_label="+ New Character",
        )
        self._empty_state.action_triggered.connect(self._on_create_character)
        layout.addWidget(self._empty_state)

        self._error_state = ErrorState("The database has no tables yet.")
        self._error_state.retry_requested.connect(self.refresh)
        layout.addWidget(self._error_state)

        layout.addStretch(1)

        self._overlay = LoadingOverlay(self, theme)

        QShortcut(QKeySequence("Ctrl+N"), self, activated=self._on_create_character)
        QShortcut(QKeySequence("F5"), self, activated=self.refresh)

        self.refresh()

    # --- data loading -----------------------------------------------------

    def refresh(self) -> None:
        try:
            with self._ctx.open_session() as session:
                self._characters = self._ctx.character_service.list_characters(session)
        except OperationalError:
            self._show_error_state()
            return

        self._error_state.setVisible(False)
        self._rebuild_cards()
        self._apply_filters()

    def _rebuild_cards(self) -> None:
        cards: list[tuple[Character, EntityCard]] = []
        for character in self._characters:
            subtitle = character.role or "No role set"
            card = EntityCard("🧒", character.name_en, subtitle)
            card.add_trailing_widget(
                StatusBadge(
                    "Locked" if character.active_version_id else "Unlocked",
                    "success" if character.active_version_id else "neutral",
                )
            )
            card.clicked.connect(lambda _checked=False, c=character: self._open_detail(c))
            cards.append((character, card))
        self._cards = cards
        self._grid.set_cards([card for _character, card in cards])

    def _show_error_state(self) -> None:
        self._empty_state.setVisible(False)
        self._error_state.setVisible(True)
        self._cards = []
        self._grid.set_cards([])

    # --- search / filter ---------------------------------------------------

    def _apply_filters(self, *_args: object) -> None:
        query = self._search.text().strip().lower()
        lock_state = self._lock_filter.currentData()

        visible_count = 0
        for character, card in self._cards:
            matches_query = (
                not query
                or query in character.name_en.lower()
                or query in character.name_ar
                or any(query in trait.lower() for trait in character.traits)
            )
            is_locked = character.active_version_id is not None
            matches_lock = (
                lock_state == _LOCK_ALL
                or (lock_state == _LOCK_LOCKED and is_locked)
                or (lock_state == _LOCK_UNLOCKED and not is_locked)
            )
            visible = matches_query and matches_lock
            card.setVisible(visible)
            visible_count += int(visible)

        self._empty_state.setVisible(visible_count == 0 and not self._error_state.isVisible())
        if self._characters:
            self._empty_state.set_message("No characters match your search.", show_action=False)
        else:
            self._empty_state.set_message(
                "No characters yet — add the first one to start building your cast."
            )
        self._count_label.setVisible(bool(self._characters))
        self._count_label.setText(f"{visible_count} of {len(self._characters)} characters")

    # --- detail / create ----------------------------------------------------

    def _open_detail(self, character: Character) -> None:
        try:
            with self._ctx.open_session() as session:
                fresh = self._ctx.character_service.get_character(session, character.id)
                dialog = _CharacterDetailDialog(
                    self._ctx, self._theme, fresh, parent=self, on_feedback=self._on_feedback
                )
        except OperationalError:
            self._show_error_state()
            return
        dialog.exec()
        if dialog.needs_refresh:
            self.refresh()

    def _on_create_character(self) -> None:
        existing_slugs = {character.slug for character in self._characters}
        dialog = _CreateCharacterDialog(existing_slugs, parent=self)
        if dialog.exec() != FormDialog.DialogCode.Accepted:
            return

        fields = dialog.result_fields()
        self._overlay.start("Creating character…")
        try:
            with self._ctx.session_scope() as session:
                self._ctx.character_service.create_character(session, **fields)
        except (ConflictError, ValidationError) as err:
            show_error(self, "Create Character", str(err))
            return
        except OperationalError:
            self._show_error_state()
            return
        finally:
            self._overlay.stop()

        self.refresh()
        if self._on_feedback:
            self._on_feedback(f"{fields['name_en']} added to the roster.", "success")
