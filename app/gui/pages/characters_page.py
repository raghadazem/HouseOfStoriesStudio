"""CharactersPage — browse, search, and create characters.

Character *design* (Character Lock — versions, master prompts, canon
approval) is a separate, much larger workflow owned by
``CharacterVersionService``; this page covers the identity-level CRUD
``CharacterService`` already provides plus a read-only view of each
character's version history — creating/approving a new version is a
big enough workflow of its own to stay out of this pass's scope (see
``docs/25_MILESTONE_4B_STATUS.md``).
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
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
from app.gui.theme.manager import ThemeManager
from app.gui.theme.tokens import METRICS
from app.gui.widgets import (
    EmptyState,
    EntityCard,
    ErrorState,
    FormDialog,
    LoadingOverlay,
    PageHeader,
    ResponsiveGrid,
    SearchBox,
    StatusBadge,
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
        super().__init__("New Character", save_label="Create", parent=parent)
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
    def __init__(self, character: Character, parent: QWidget | None = None) -> None:
        super().__init__(character.name_en, show_save=False, min_width=480, parent=parent)

        name_ar_field = QLineEdit(character.name_ar)
        name_ar_field.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        name_ar_field.setReadOnly(True)
        self.add_row("Name (Arabic)", name_ar_field)

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
        meta_wrap = QWidget()
        meta_wrap.setLayout(meta_row)
        self.add_row("Status", meta_wrap)

        if character.traits:
            traits_field = QLineEdit(", ".join(character.traits))
            traits_field.setReadOnly(True)
            self.add_row("Traits", traits_field)

        versions_panel = QFrame()
        versions_panel.setProperty("class", "card")
        versions_layout = QVBoxLayout(versions_panel)
        versions_layout.setContentsMargins(
            METRICS.spacing_md, METRICS.spacing_md, METRICS.spacing_md, METRICS.spacing_md
        )
        versions_layout.setSpacing(METRICS.spacing_xs)
        if character.versions:
            for version in sorted(character.versions, key=lambda v: v.version_number, reverse=True):
                row = QHBoxLayout()
                is_active = version.id == character.active_version_id
                label = QLabel(f"{version.version_number}" + ("  ★ active" if is_active else ""))
                row.addWidget(label)
                row.addStretch(1)
                row.addWidget(
                    StatusBadge(
                        version.status.value.replace("_", " ").title(),
                        _VERSION_STATUS_VARIANT.get(version.status.value, "neutral"),
                    )
                )
                row_wrap = QWidget()
                row_wrap.setLayout(row)
                versions_layout.addWidget(row_wrap)
        else:
            versions_layout.addWidget(EmptyState("No design versions yet.", icon="🎨"))
        self.add_row("Design versions", versions_panel)


class CharactersPage(QWidget):
    def __init__(
        self, ctx: ApplicationContext, theme: ThemeManager, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setObjectName("charactersPage")
        self._ctx = ctx
        self._theme = theme
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

        toolbar = QHBoxLayout()
        toolbar.setSpacing(METRICS.spacing_sm)
        self._search = SearchBox("Search characters…")
        self._search.text_changed.connect(self._apply_filters)
        toolbar.addWidget(self._search, stretch=1)

        self._lock_filter = QComboBox()
        self._lock_filter.addItem("All characters", _LOCK_ALL)
        self._lock_filter.addItem("Locked", _LOCK_LOCKED)
        self._lock_filter.addItem("Not locked", _LOCK_UNLOCKED)
        self._lock_filter.currentIndexChanged.connect(self._apply_filters)
        toolbar.addWidget(self._lock_filter)
        layout.addLayout(toolbar)

        self._grid = ResponsiveGrid(card_min_width=180)
        layout.addWidget(self._grid)

        self._empty_state = EmptyState(
            "No characters yet — add the first one to start building your cast.", icon="🧒"
        )
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
            self._empty_state.set_message("No characters match your search.")
        else:
            self._empty_state.set_message(
                "No characters yet — add the first one to start building your cast."
            )

    # --- detail / create ----------------------------------------------------

    def _open_detail(self, character: Character) -> None:
        try:
            with self._ctx.open_session() as session:
                fresh = self._ctx.character_service.get_character(session, character.id)
                dialog = _CharacterDetailDialog(fresh, parent=self)
        except OperationalError:
            self._show_error_state()
            return
        dialog.exec()

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
