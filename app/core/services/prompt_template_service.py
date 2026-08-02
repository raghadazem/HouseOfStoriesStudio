"""PromptTemplateService — reusable and contextual prompt management.

Rendering uses a Jinja2 :class:`~jinja2.sandbox.SandboxedEnvironment`
(blocks attribute access to dangerous builtins/dunder attributes —
"do not execute arbitrary Python expressions") with
:class:`~jinja2.StrictUndefined`, so a missing variable raises a clear,
caught :class:`~app.core.services.exceptions.TemplateRenderError`
naming exactly which variables are missing, instead of rendering
silently wrong text or a cryptic Jinja2 traceback.
"""

from __future__ import annotations

import uuid

import jinja2
from jinja2 import meta
from jinja2.sandbox import SandboxedEnvironment
from sqlalchemy.orm import Session

from app.core.db.enums import ApprovalDecision, PromptCategory, PromptType
from app.core.models import PromptTemplate
from app.core.services.approval_service import ApprovalService
from app.core.services.exceptions import (
    ConflictError,
    InvalidTransitionError,
    NotFoundError,
    TemplateRenderError,
    ValidationError,
)

_UPDATABLE_FIELDS = {
    "text_en",
    "target_tool",
    "is_reusable",
    "category",
    "prompt_type",
    "character_id",
    "episode_id",
    "scene_id",
}

_jinja_env = SandboxedEnvironment(undefined=jinja2.StrictUndefined)


class PromptTemplateService:
    """Create, version, resolve, and safely render prompt templates."""

    def __init__(self, approval_service: ApprovalService | None = None) -> None:
        self._approvals = approval_service or ApprovalService()

    def create_prompt_template(
        self,
        session: Session,
        *,
        name: str,
        category: PromptCategory,
        prompt_type: PromptType,
        text_en: str,
        version: str = "v01",
        is_reusable: bool = False,
        target_tool: str | None = None,
        character_id: uuid.UUID | None = None,
        episode_id: uuid.UUID | None = None,
        scene_id: uuid.UUID | None = None,
    ) -> PromptTemplate:
        """Create a prompt template. Global (no character/episode/scene) is valid."""
        if session.query(PromptTemplate).filter_by(name=name, version=version).count() > 0:
            raise ConflictError(f"PromptTemplate {name!r} version {version!r} already exists.")
        template = PromptTemplate(
            name=name,
            version=version,
            category=category,
            prompt_type=prompt_type,
            text_en=text_en,
            is_reusable=is_reusable,
            target_tool=target_tool,
            character_id=character_id,
            episode_id=episode_id,
            scene_id=scene_id,
        )
        session.add(template)
        session.flush()
        return template

    def get_prompt_template(self, session: Session, template_id: uuid.UUID) -> PromptTemplate:
        template = session.get(PromptTemplate, template_id)
        if template is None:
            raise NotFoundError(f"PromptTemplate {template_id} not found.")
        return template

    def update_prompt_template(
        self, session: Session, template_id: uuid.UUID, **fields: object
    ) -> PromptTemplate:
        """Edit a template in place.

        Raises:
            InvalidTransitionError: If the template's latest approval
                decision is ``approved`` — call
                :meth:`increment_template_version` instead of overwriting
                an approved historical version.
        """
        template = self.get_prompt_template(session, template_id)
        state = self._approvals.get_current_approval_state(session, "prompt_template", template_id)
        if state == ApprovalDecision.APPROVED:
            raise InvalidTransitionError(
                f"PromptTemplate {template_id} is approved; call "
                "increment_template_version() instead of editing it in place."
            )
        unknown = set(fields) - _UPDATABLE_FIELDS
        if unknown:
            raise ValidationError(f"Cannot update unknown PromptTemplate fields: {sorted(unknown)}")
        for key, value in fields.items():
            setattr(template, key, value)
        session.flush()
        return template

    def archive_prompt_template(self, session: Session, template_id: uuid.UUID) -> PromptTemplate:
        template = self.get_prompt_template(session, template_id)
        template.is_archived = True
        session.flush()
        return template

    def duplicate_prompt_template(
        self,
        session: Session,
        template_id: uuid.UUID,
        *,
        new_version: str | None = None,
        text_en: str | None = None,
    ) -> PromptTemplate:
        """Copy a template into a new version row, leaving the original untouched."""
        source = self.get_prompt_template(session, template_id)
        if new_version is None:
            new_version = self._next_version(session, source.name)
        return self.create_prompt_template(
            session,
            name=source.name,
            category=source.category,
            prompt_type=source.prompt_type,
            text_en=text_en if text_en is not None else source.text_en,
            version=new_version,
            is_reusable=source.is_reusable,
            target_tool=source.target_tool,
            character_id=source.character_id,
            episode_id=source.episode_id,
            scene_id=source.scene_id,
        )

    def increment_template_version(
        self, session: Session, template_id: uuid.UUID, *, text_en: str | None = None
    ) -> PromptTemplate:
        """Create the next version of a template. Never mutates the source row."""
        return self.duplicate_prompt_template(session, template_id, text_en=text_en)

    @staticmethod
    def _next_version(session: Session, name: str) -> str:
        existing = session.query(PromptTemplate).filter_by(name=name).count()
        return f"v{existing + 1:02d}"

    def list_prompt_templates(
        self,
        session: Session,
        *,
        category: PromptCategory | None = None,
        prompt_type: PromptType | None = None,
        is_reusable: bool | None = None,
        character_id: uuid.UUID | None = None,
        episode_id: uuid.UUID | None = None,
        scene_id: uuid.UUID | None = None,
        include_archived: bool = False,
    ) -> list[PromptTemplate]:
        query = session.query(PromptTemplate)
        if not include_archived:
            query = query.filter_by(is_archived=False)
        if category is not None:
            query = query.filter_by(category=category)
        if prompt_type is not None:
            query = query.filter_by(prompt_type=prompt_type)
        if is_reusable is not None:
            query = query.filter_by(is_reusable=is_reusable)
        if character_id is not None:
            query = query.filter_by(character_id=character_id)
        if episode_id is not None:
            query = query.filter_by(episode_id=episode_id)
        if scene_id is not None:
            query = query.filter_by(scene_id=scene_id)
        return query.order_by(PromptTemplate.name, PromptTemplate.version).all()

    def resolve_global_and_contextual_prompts(
        self,
        session: Session,
        *,
        category: PromptCategory | None = None,
        character_id: uuid.UUID | None = None,
        episode_id: uuid.UUID | None = None,
        scene_id: uuid.UUID | None = None,
    ) -> list[PromptTemplate]:
        """Global reusable templates plus any matching the given context, de-duplicated."""
        base = session.query(PromptTemplate).filter_by(is_archived=False)
        if category is not None:
            base = base.filter_by(category=category)

        results: list[PromptTemplate] = list(
            base.filter(
                PromptTemplate.is_reusable.is_(True),
                PromptTemplate.character_id.is_(None),
                PromptTemplate.episode_id.is_(None),
                PromptTemplate.scene_id.is_(None),
            ).all()
        )
        if character_id is not None:
            results += base.filter_by(character_id=character_id).all()
        if episode_id is not None:
            results += base.filter_by(episode_id=episode_id).all()
        if scene_id is not None:
            results += base.filter_by(scene_id=scene_id).all()

        seen: set[uuid.UUID] = set()
        deduped: list[PromptTemplate] = []
        for template in results:
            if template.id not in seen:
                seen.add(template.id)
                deduped.append(template)
        return deduped

    @staticmethod
    def validate_template_variables(text_en: str, provided_variables: dict[str, object]) -> list[str]:
        """Return the names of every variable ``text_en`` references but ``provided_variables`` lacks."""
        try:
            ast = _jinja_env.parse(text_en)
        except jinja2.TemplateSyntaxError as err:
            raise TemplateRenderError(f"Invalid template syntax: {err}") from err
        declared = meta.find_undeclared_variables(ast)
        return sorted(declared - set(provided_variables.keys()))

    def render_prompt_template(
        self,
        session: Session,
        template_id: uuid.UUID,
        variables: dict[str, object] | None = None,
    ) -> str:
        """Render a template with ``variables``, in a sandboxed Jinja2 environment.

        Raises:
            TemplateRenderError: If any referenced variable is missing,
                or rendering otherwise fails (bad syntax, sandbox
                violation).
        """
        template = self.get_prompt_template(session, template_id)
        variables = variables or {}
        missing = self.validate_template_variables(template.text_en, variables)
        if missing:
            raise TemplateRenderError(
                f"PromptTemplate {template.name!r} {template.version} is missing "
                f"variables: {missing}"
            )
        try:
            jinja_template = _jinja_env.from_string(template.text_en)
            return jinja_template.render(**variables)
        except jinja2.TemplateError as err:
            raise TemplateRenderError(
                f"Failed to render PromptTemplate {template.name!r}: {err}"
            ) from err
