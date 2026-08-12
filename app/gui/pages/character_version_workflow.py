"""CharacterVersion (Character Lock) workflow: create/edit, review, real generation.

Opened from ``CharactersPage``'s version list rather than inlined into
that file — this is a large, self-contained workflow (editing a
design revision, validating its Character Lock, running real AI
generation, and reviewing candidates) layered on top of the roster
page, not a rewrite of it. Every dialog here reuses the existing
``FormDialog``/``StatusBadge``/``ResponsiveGrid`` design system —
no new visual language.

Generation itself always runs on a background ``GenerationWorker``
(see ``app.gui.workers.generation_worker``) so the GUI never freezes;
this module only ever talks to core services/``AIOrchestrator``
through ``ApplicationContext``, never a provider class directly.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)
from sqlalchemy.exc import OperationalError

from app.core.ai.generation_runner import (
    MAX_CANDIDATE_COUNT,
    MIN_CANDIDATE_COUNT,
    CandidateBatchRequest,
    render_preview,
    run_character_reference_batch,
)
from app.core.db.enums import (
    ApprovalStatus,
    CharacterVersionStatus,
    PromptCategory,
    PromptType,
)
from app.core.models import Character, CharacterVersion
from app.core.services.exceptions import (
    CharacterLockIncompleteError,
    ConflictError,
    InvalidTransitionError,
    ServiceError,
    ValidationError,
)
from app.gui.context import ApplicationContext
from app.gui.theme.manager import ThemeManager
from app.gui.theme.tokens import METRICS
from app.gui.widgets import (
    CandidateReviewDialogBase,
    FormDialog,
    SectionHeader,
    StatusBadge,
    confirm,
    show_error,
    show_warning,
)

_VERSION_STATUS_VARIANT = {
    "draft": "neutral",
    "in_review": "info",
    "approved_canon": "success",
    "archived": "neutral",
}

_LOCK_FIELD_LABELS = {
    "visual_summary": "Visual summary",
    "master_prompt": "Master prompt",
    "negative_prompt": "Negative prompt",
    "color_palette": "Color palette",
    "relative_height": "Relative height",
    "approved_reference_assets": "At least one approved reference image",
}

_UPDATABLE_FIELDS = (
    "visual_summary",
    "master_prompt",
    "negative_prompt",
    "color_palette",
    "allowed_accessories",
    "relative_height",
    "outfit_version",
)


def _clear_layout(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.setParent(None)
            widget.deleteLater()
        elif item.layout() is not None:
            _clear_layout(item.layout())


def _csv_field(value: list[str]) -> str:
    return ", ".join(value)


def _parse_csv_field(text: str) -> list[str]:
    return [part.strip() for part in text.split(",") if part.strip()]


# --- create / edit a draft version's fields --------------------------------


class _EditCharacterVersionDialog(FormDialog):
    """Create a new draft version, or edit an existing draft's fields."""

    def __init__(self, version: CharacterVersion | None, parent: QWidget | None = None) -> None:
        is_new = version is None
        super().__init__(
            "New Design Version" if is_new else f"Edit {version.version_number}",
            icon="🎨",
            subtitle="Character Lock fields used for real AI reference generation",
            save_label="Create" if is_new else "Save",
            min_width=520,
            parent=parent,
        )

        self.visual_summary_field = QPlainTextEdit(version.visual_summary if version else "")
        self.visual_summary_field.setPlaceholderText(
            "Two ponytails, denim dress, always smiling…"
        )
        self.visual_summary_field.setFixedHeight(70)
        self.add_row("Visual summary", self.visual_summary_field)

        self.master_prompt_field = QPlainTextEdit(version.master_prompt if version else "")
        self.master_prompt_field.setPlaceholderText(
            "The full descriptive prompt sent to the image generator…"
        )
        self.master_prompt_field.setFixedHeight(90)
        self.add_row("Master prompt", self.master_prompt_field)

        self.negative_prompt_field = QPlainTextEdit(version.negative_prompt if version else "")
        self.negative_prompt_field.setPlaceholderText("no extra characters, no text overlays…")
        self.negative_prompt_field.setFixedHeight(70)
        self.add_row("Negative prompt", self.negative_prompt_field)

        self.color_palette_field = QLineEdit(_csv_field(version.color_palette) if version else "")
        self.color_palette_field.setPlaceholderText("denim blue, sunshine yellow (comma-separated)")
        self.add_row("Color palette", self.color_palette_field)

        self.relative_height_field = QLineEdit(version.relative_height if version else "")
        self.relative_height_field.setPlaceholderText("taller than Bilsan")
        self.add_row("Relative height", self.relative_height_field)

        self.allowed_accessories_field = QLineEdit(
            _csv_field(version.allowed_accessories) if version else ""
        )
        self.allowed_accessories_field.setPlaceholderText("backpack, hair bow (comma-separated)")
        self.add_row("Allowed accessories", self.allowed_accessories_field)

        self.outfit_version_field = QLineEdit(version.outfit_version or "" if version else "")
        self.outfit_version_field.setPlaceholderText("e.g. summer_v1")
        self.add_row("Outfit version", self.outfit_version_field)

    def result_fields(self) -> dict[str, object]:
        return {
            "visual_summary": self.visual_summary_field.toPlainText().strip() or None,
            "master_prompt": self.master_prompt_field.toPlainText().strip() or None,
            "negative_prompt": self.negative_prompt_field.toPlainText().strip() or None,
            "color_palette": _parse_csv_field(self.color_palette_field.text()),
            "relative_height": self.relative_height_field.text().strip() or None,
            "allowed_accessories": _parse_csv_field(self.allowed_accessories_field.text()),
            "outfit_version": self.outfit_version_field.text().strip() or None,
        }


class _RejectVersionDialog(FormDialog):
    def __init__(self, version_number: str, parent: QWidget | None = None) -> None:
        super().__init__(f"Reject {version_number}", icon="✕", save_label="Reject", parent=parent)
        self.reason_field = QPlainTextEdit()
        self.reason_field.setPlaceholderText("What needs to change before this can be approved?")
        self.reason_field.setFixedHeight(90)
        self.add_row("Reason", self.reason_field)

    def validate(self) -> str | None:
        if not self.reason_field.toPlainText().strip():
            return "A reason is required to reject a version."
        return None

    def reason(self) -> str:
        return self.reason_field.toPlainText().strip()


# --- Generate Reference: candidate count, provider, prompt preview ---------


class _GenerateReferenceDialog(FormDialog):
    def __init__(
        self,
        ctx: ApplicationContext,
        version_id: uuid.UUID,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(
            "Generate Reference",
            icon="✨",
            subtitle="Real AI-generated character reference candidates",
            save_label="Generate",
            min_width=520,
            parent=parent,
        )
        self._ctx = ctx
        self._version_id = version_id

        self.provider_field = QComboBox()
        providers = ctx.ai_orchestrator.list_available_providers("image")
        for name in providers:
            self.provider_field.addItem(name, name)
        self.add_row("Provider", self.provider_field)
        if not providers:
            self.show_form_error(
                "No image provider is configured. Set one up in Settings → AI Providers."
            )

        self.template_field = QComboBox()
        with ctx.open_session() as session:
            templates = ctx.prompt_template_service.list_prompt_templates(
                session, category=PromptCategory.CHARACTER, prompt_type=PromptType.IMAGE
            )
            for template in templates:
                self.template_field.addItem(f"{template.name} ({template.version})", template.id)
        self.add_row("Prompt template", self.template_field)
        if not templates:
            self.show_form_error(
                "No character-reference prompt template exists yet. Create one on the "
                "Prompts page first (category: Character, type: Image)."
            )
        self.template_field.currentIndexChanged.connect(self._update_preview)

        self.candidate_count_field = QSpinBox()
        self.candidate_count_field.setRange(MIN_CANDIDATE_COUNT, MAX_CANDIDATE_COUNT)
        self.candidate_count_field.setValue(1)
        self.add_row("Candidates to generate", self.candidate_count_field)

        self.preview_field = QPlainTextEdit()
        self.preview_field.setReadOnly(True)
        self.preview_field.setFixedHeight(120)
        self.preview_field.setPlaceholderText("Select a prompt template to preview the final prompt.")
        self.add_row("Final prompt preview", self.preview_field)

        self._update_preview()

    def _update_preview(self, *_args: object) -> None:
        template_id = self.template_field.currentData()
        if template_id is None:
            self.preview_field.setPlainText("")
            return
        try:
            with self._ctx.open_session() as session:
                request = CandidateBatchRequest(
                    provider_name="__preview__",
                    prompt_template_id=template_id,
                    character_version_id=self._version_id,
                )
                rendered = render_preview(session, request)
        except ServiceError as err:
            self.preview_field.setPlainText(f"Could not render preview: {err}")
            return
        text = rendered.prompt_text
        if rendered.negative_prompt_text:
            text += f"\n\nAvoid: {rendered.negative_prompt_text}"
        self.preview_field.setPlainText(text)

    def validate(self) -> str | None:
        if self.provider_field.currentData() is None:
            return "No image provider is configured."
        if self.template_field.currentData() is None:
            return "No prompt template is available."
        return None

    def build_request(self, character_id: uuid.UUID) -> CandidateBatchRequest:
        return CandidateBatchRequest(
            provider_name=self.provider_field.currentData(),
            prompt_template_id=self.template_field.currentData(),
            character_version_id=self._version_id,
            character_id=character_id,
            candidate_count=self.candidate_count_field.value(),
        )


# --- candidate review grid --------------------------------------------------


class _CandidateReviewDialog(CandidateReviewDialogBase):
    """Character-reference candidates: Approve/Reject plus "Add as
    Reference" for an approved candidate not yet linked as reference art.

    Behavior-preserving extraction (Milestone 8): the grid, worker
    orchestration, and approve/reject/retry/cancel flow now live in
    ``CandidateReviewDialogBase`` (``app/gui/widgets/candidate_review.py``),
    shared with the Scene Images review dialog — only "Add as Reference"
    (this class's one caller-specific action) stays here.
    """

    def __init__(
        self,
        ctx: ApplicationContext,
        theme: ThemeManager,
        character: Character,
        version_id: uuid.UUID,
        base_request: CandidateBatchRequest,
        parent: QWidget | None = None,
    ) -> None:
        self._character = character
        self._version_id = version_id
        super().__init__(
            "Reference Candidates",
            ctx,
            theme,
            base_request,
            runner=run_character_reference_batch,
            parent=parent,
        )

    def _tertiary_state(self, session, job, asset):
        if asset is None:
            return None, None
        references = {
            ref.asset_id
            for ref in self._ctx.character_version_service.list_character_references(
                session, self._character.id, version_id=self._version_id
            )
        }
        is_reference = asset.id in references
        badge = "Reference" if is_reference else None
        action = None
        if asset.approval_status == ApprovalStatus.APPROVED and not is_reference:
            action = ("Add as Reference", self._on_add_reference)
        return badge, action

    def _show_error(self, title: str, message: str) -> None:
        # Routes through this module's own show_error (rather than the
        # base class's) so tests that monkeypatch cvw.show_error keep
        # intercepting every error this dialog surfaces, unchanged from
        # before the Milestone 8 candidate-review extraction.
        show_error(self, title, message)

    def _on_add_reference(self, asset_id: uuid.UUID) -> None:
        try:
            with self._ctx.session_scope() as session:
                self._ctx.character_version_service.add_character_reference(
                    session,
                    character_id=self._character.id,
                    character_version_id=self._version_id,
                    asset_id=asset_id,
                )
        except ServiceError as err:
            show_error(self, "Add Reference", str(err))
            return
        self.changed = True
        self._refresh()


# --- version detail / action hub -------------------------------------------


class _CharacterVersionDetailDialog(FormDialog):
    def __init__(
        self,
        ctx: ApplicationContext,
        theme: ThemeManager,
        character: Character,
        version_id: uuid.UUID,
        parent: QWidget | None = None,
        *,
        on_feedback: Callable[[str, str], None] | None = None,
    ) -> None:
        version = _find_version(character, version_id)
        super().__init__(
            version.version_number, icon="🎨", show_save=False, min_width=560, parent=parent
        )
        self._ctx = ctx
        self._theme = theme
        self._character_id = character.id
        self._version_id = version_id
        self._on_feedback = on_feedback
        self.needs_refresh = False

        self._body = QVBoxLayout()
        self._body.setSpacing(METRICS.spacing_md)
        self.content_layout.addLayout(self._body)

        self._reload_and_render()

    def _reload_and_render(self) -> None:
        try:
            with self._ctx.open_session() as session:
                character = self._ctx.character_service.get_character(session, self._character_id)
                version = _find_version(character, self._version_id)
                lock = self._ctx.character_version_service.validate_character_lock(
                    session, self._version_id
                )
                references = self._ctx.character_version_service.list_character_references(
                    session, self._character_id, version_id=self._version_id
                )
                # Detach the plain values this dialog needs after the
                # session closes — reference.asset is a lazy relationship,
                # so it must be read here, not later (see
                # episode_workspace_page.py's same pattern).
                reference_rows = [
                    (ref.id, ref.label, ref.is_current_canon, ref.asset.original_filename)
                    for ref in references
                ]
        except OperationalError:
            show_error(self, "Character Version", "The database is unavailable.")
            self.reject()
            return
        self._render(character, version, lock, reference_rows)

    def _render(self, character: Character, version: CharacterVersion, lock, reference_rows: list) -> None:
        self._version_number = version.version_number
        _clear_layout(self._body)

        status_row = QHBoxLayout()
        status_row.addWidget(
            StatusBadge(
                version.status.value.replace("_", " ").title(),
                _VERSION_STATUS_VARIANT.get(version.status.value, "neutral"),
            )
        )
        if version.id == character.active_version_id:
            status_row.addWidget(StatusBadge("★ Active", "success"))
        status_row.addWidget(
            StatusBadge(
                "Lock complete" if lock.is_complete else "Lock incomplete",
                "success" if lock.is_complete else "warning",
            )
        )
        status_row.addStretch(1)
        self._body.addLayout(status_row)

        if not lock.is_complete:
            missing = ", ".join(_LOCK_FIELD_LABELS.get(f, f) for f in lock.missing_fields)
            missing_label = QLabel(f"Missing: {missing}")
            missing_label.setWordWrap(True)
            missing_label.setProperty("class", "formError")
            self._body.addWidget(missing_label)

        self._body.addWidget(SectionHeader("Design fields"))
        for label, value in (
            ("Visual summary", version.visual_summary),
            ("Master prompt", version.master_prompt),
            ("Negative prompt", version.negative_prompt),
            ("Color palette", _csv_field(version.color_palette)),
            ("Relative height", version.relative_height),
            ("Allowed accessories", _csv_field(version.allowed_accessories)),
            ("Outfit version", version.outfit_version),
        ):
            row = QLabel(f"{label}: {value or '—'}")
            row.setWordWrap(True)
            self._body.addWidget(row)

        self._body.addWidget(SectionHeader(f"Reference Images ({len(reference_rows)})"))
        if reference_rows:
            for reference_id, label, is_canon, filename in reference_rows:
                self._body.addWidget(
                    self._build_reference_row(reference_id, label, is_canon, filename)
                )
        else:
            empty_label = QLabel("No reference images yet — use Generate Reference below.")
            empty_label.setProperty("class", "muted")
            self._body.addWidget(empty_label)

        actions = QHBoxLayout()
        is_draft = version.status == CharacterVersionStatus.DRAFT
        is_in_review = version.status == CharacterVersionStatus.IN_REVIEW
        is_approved = version.status == CharacterVersionStatus.APPROVED_CANON

        if is_draft:
            edit_btn = QPushButton("Edit Fields")
            edit_btn.clicked.connect(self._on_edit)
            actions.addWidget(edit_btn)

        generate_btn = QPushButton("Generate Reference")
        generate_btn.setProperty("class", "primary")
        generate_btn.clicked.connect(self._on_generate)
        actions.addWidget(generate_btn)

        if is_draft:
            submit_btn = QPushButton("Submit for Review")
            submit_btn.clicked.connect(self._on_submit)
            actions.addWidget(submit_btn)

        if is_in_review:
            reject_btn = QPushButton("Reject")
            reject_btn.setProperty("class", "danger")
            reject_btn.clicked.connect(self._on_reject)
            actions.addWidget(reject_btn)
            approve_btn = QPushButton("Approve")
            approve_btn.setProperty("class", "primary")
            approve_btn.clicked.connect(self._on_approve)
            actions.addWidget(approve_btn)

        if is_approved and version.id != character.active_version_id:
            activate_btn = QPushButton("Set Active")
            activate_btn.setProperty("class", "primary")
            activate_btn.clicked.connect(self._on_set_active)
            actions.addWidget(activate_btn)

        actions.addStretch(1)
        self._body.addLayout(actions)

    def _build_reference_row(
        self, reference_id: uuid.UUID, label: str | None, is_canon: bool, filename: str
    ) -> QFrame:
        """One reference image row: which one is Canon, and a one-click
        way to make another one Canon instead (Milestone 8's Canon
        Reference action — see ``CharacterVersionService.set_canon_reference``,
        which unsets any previous canon reference in the same call, so
        exactly one reference is ever canon)."""
        row = QFrame()
        row.setProperty("class", "reviewRow")
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(
            METRICS.spacing_md, METRICS.spacing_sm, METRICS.spacing_md, METRICS.spacing_sm
        )
        row_layout.setSpacing(METRICS.spacing_md)

        icon = QLabel("🖼")
        icon.setProperty("class", "iconChip")
        icon.setFixedSize(40, 40)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row_layout.addWidget(icon)

        text_column = QVBoxLayout()
        text_column.setSpacing(2)
        title = QLabel(label or filename)
        title.setProperty("class", "entityRowTitle")
        text_column.addWidget(title)
        subtitle = QLabel(filename)
        subtitle.setProperty("class", "entityRowSubtitle")
        text_column.addWidget(subtitle)
        row_layout.addLayout(text_column, stretch=1)

        if is_canon:
            row_layout.addWidget(StatusBadge("★ Canon", "success"))
        else:
            make_canon_btn = QPushButton("Make Canon")
            make_canon_btn.clicked.connect(
                lambda _checked=False, rid=reference_id: self._on_make_canon(rid)
            )
            row_layout.addWidget(make_canon_btn)

        return row

    def _on_make_canon(self, reference_id: uuid.UUID) -> None:
        try:
            with self._ctx.session_scope() as session:
                self._ctx.character_version_service.set_canon_reference(session, reference_id)
        except ServiceError as err:
            show_error(self, "Make Canon", str(err))
            return
        self.needs_refresh = True
        self._reload_and_render()
        if self._on_feedback:
            self._on_feedback("Canon reference updated.", "success")

    def _on_edit(self) -> None:
        with self._ctx.open_session() as session:
            character = self._ctx.character_service.get_character(session, self._character_id)
            version = _find_version(character, self._version_id)
            dialog = _EditCharacterVersionDialog(version, parent=self)
        if dialog.exec() != FormDialog.DialogCode.Accepted:
            return
        try:
            with self._ctx.session_scope() as session:
                self._ctx.character_version_service.update_character_version(
                    session, self._version_id, **dialog.result_fields()
                )
        except (ValidationError, InvalidTransitionError) as err:
            show_error(self, "Edit Version", str(err))
            return
        self.needs_refresh = True
        self._reload_and_render()

    def _on_generate(self) -> None:
        dialog = _GenerateReferenceDialog(self._ctx, self._version_id, parent=self)
        if dialog.exec() != FormDialog.DialogCode.Accepted:
            return
        with self._ctx.open_session() as session:
            character = self._ctx.character_service.get_character(session, self._character_id)
        request = dialog.build_request(character.id)
        review_dialog = _CandidateReviewDialog(
            self._ctx, self._theme, character, self._version_id, request, parent=self
        )
        review_dialog.exec()
        if review_dialog.changed:
            self.needs_refresh = True
        self._reload_and_render()

    def _on_submit(self) -> None:
        try:
            with self._ctx.session_scope() as session:
                self._ctx.character_version_service.submit_character_version_for_review(
                    session, self._version_id
                )
        except InvalidTransitionError as err:
            show_error(self, "Submit for Review", str(err))
            return
        self.needs_refresh = True
        self._reload_and_render()

    def _on_approve(self) -> None:
        try:
            with self._ctx.session_scope() as session:
                self._ctx.character_version_service.approve_character_version(
                    session, self._version_id, decided_by="founder"
                )
        except CharacterLockIncompleteError as err:
            missing = ", ".join(_LOCK_FIELD_LABELS.get(f, f) for f in err.missing_fields)
            show_warning(self, "Character Lock Incomplete", f"Missing: {missing}")
            return
        except InvalidTransitionError as err:
            show_error(self, "Approve Version", str(err))
            return
        self.needs_refresh = True
        self._reload_and_render()
        if self._on_feedback:
            self._on_feedback("Version approved.", "success")

    def _on_reject(self) -> None:
        dialog = _RejectVersionDialog(self._version_number, parent=self)
        if dialog.exec() != FormDialog.DialogCode.Accepted:
            return
        try:
            with self._ctx.session_scope() as session:
                self._ctx.character_version_service.reject_character_version(
                    session, self._version_id, notes=dialog.reason()
                )
        except (InvalidTransitionError, ValidationError) as err:
            show_error(self, "Reject Version", str(err))
            return
        self.needs_refresh = True
        self._reload_and_render()

    def _on_set_active(self) -> None:
        if not confirm(self, "Set Active", "Make this the character's active design version?"):
            return
        try:
            with self._ctx.session_scope() as session:
                self._ctx.character_version_service.set_active_character_version(
                    session, self._character_id, self._version_id
                )
        except (InvalidTransitionError, ValidationError) as err:
            show_error(self, "Set Active", str(err))
            return
        self.needs_refresh = True
        self._reload_and_render()
        if self._on_feedback:
            self._on_feedback("Active version updated.", "success")


def _find_version(character: Character, version_id: uuid.UUID) -> CharacterVersion:
    for version in character.versions:
        if version.id == version_id:
            return version
    raise ValidationError(f"CharacterVersion {version_id} not found on {character.slug!r}.")


# --- public entry points -----------------------------------------------------


def open_character_version_detail(
    ctx: ApplicationContext,
    theme: ThemeManager,
    character_id: uuid.UUID,
    version_id: uuid.UUID,
    parent: QWidget,
    *,
    on_feedback: Callable[[str, str], None] | None = None,
) -> bool:
    """Opens the version action-hub dialog. Returns whether the caller should refresh."""
    with ctx.open_session() as session:
        character = ctx.character_service.get_character(session, character_id)
        dialog = _CharacterVersionDetailDialog(
            ctx, theme, character, version_id, parent=parent, on_feedback=on_feedback
        )
    dialog.exec()
    return dialog.needs_refresh


def create_character_version(
    ctx: ApplicationContext,
    character_id: uuid.UUID,
    parent: QWidget,
) -> uuid.UUID | None:
    """Creates a new draft version via the edit dialog. Returns its id, or None if cancelled."""
    dialog = _EditCharacterVersionDialog(None, parent=parent)
    if dialog.exec() != FormDialog.DialogCode.Accepted:
        return None
    try:
        with ctx.session_scope() as session:
            version = ctx.character_version_service.create_character_version(
                session, character_id, **dialog.result_fields()
            )
            return version.id
    except (ConflictError, ValidationError) as err:
        show_error(parent, "New Design Version", str(err))
        return None
