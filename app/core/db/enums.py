"""Enumerations shared across domain models.

Each is a ``str`` subclass so values serialize cleanly to/from JSON and
compare equal to plain strings, while still giving type-checked,
autocompletable members in application code.
"""

from __future__ import annotations

import enum


class PipelineStage(str, enum.Enum):
    """An episode's position in the production pipeline.

    Matches the pipeline in ``docs/04_PRODUCTION_PIPELINE.md`` and
    ``docs/07_DEVELOPMENT_PLAN.md`` §15.
    """

    IDEA = "idea"
    LESSON = "lesson"
    OUTLINE = "outline"
    SCRIPT = "script"
    STORYBOARD = "storyboard"
    IMAGE_PROMPTS = "image_prompts"
    VIDEO_PROMPTS = "video_prompts"
    VOICE = "voice"
    SONG = "song"
    EDITING = "editing"
    THUMBNAIL = "thumbnail"
    SEO = "seo"
    READY_TO_PUBLISH = "ready_to_publish"
    PUBLISHED = "published"


class CharacterVersionStatus(str, enum.Enum):
    """Approval state of a character design revision (Character Lock)."""

    DRAFT = "draft"
    IN_REVIEW = "in_review"
    APPROVED_CANON = "approved_canon"
    ARCHIVED = "archived"


class AssetType(str, enum.Enum):
    """The kind of file an :class:`~app.core.models.asset.Asset` row describes."""

    IMAGE = "image"
    VIDEO = "video"
    VOICE = "voice"
    MUSIC = "music"
    THUMBNAIL = "thumbnail"
    DOCUMENT = "document"


class ApprovalStatus(str, enum.Enum):
    """Review state of an imported asset."""

    DRAFT = "draft"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    REJECTED = "rejected"


class PromptType(str, enum.Enum):
    """What kind of generator a prompt is written for."""

    IMAGE = "image"
    VIDEO = "video"
    VOICE = "voice"
    MUSIC = "music"
    TEXT = "text"


class ShortStatus(str, enum.Enum):
    """Production state of a YouTube Short cut from a long episode."""

    PLANNED = "planned"
    EDITED = "edited"
    EXPORTED = "exported"
    PUBLISHED = "published"


class ProductionTaskStatus(str, enum.Enum):
    """State of a single checklist item within an episode's production."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    DONE = "done"


class ApprovalDecision(str, enum.Enum):
    """The outcome recorded by an :class:`~app.core.models.approval.ApprovalRecord`."""

    APPROVED = "approved"
    REJECTED = "rejected"
    NEEDS_CHANGES = "needs_changes"


class ScriptStatus(str, enum.Enum):
    """Lifecycle of an episode's :class:`~app.core.models.episode.Script`.

    Mirrors :class:`CharacterVersionStatus`'s shape: a plain, linear
    status the author moves through themselves (``DRAFT`` -> ``READY``),
    then a reviewed transition into ``APPROVED`` recorded via
    :class:`~app.core.models.approval.ApprovalRecord` (see
    ``ScriptService.approve_script``) — the same split
    ``CharacterVersionService`` already uses for character locks.
    """

    DRAFT = "draft"
    READY = "ready"
    APPROVED = "approved"


class StageState(str, enum.Enum):
    """A workspace stage's own completion state (Episode Workspace).

    Distinct from :class:`PipelineStage` (the episode's single overall
    position) — this is the per-stage summary
    ``ProductionChecklistService.evaluate_stage_summary`` computes for
    each of the workspace's 8 stages (script/storyboard/images/voice/
    music/video/seo/export), re-bucketing existing
    :class:`~app.core.services.production_checklist_service.CheckResult`
    data rather than storing anything new.
    """

    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    READY = "ready"
    BLOCKED = "blocked"
    COMPLETED = "completed"


class PromptCategory(str, enum.Enum):
    """Which stage of production a prompt belongs to.

    Distinct from :class:`PromptType` (which *generator* a prompt targets):
    a prompt's category is about where it fits in the pipeline
    (``docs/04_PRODUCTION_PIPELINE.md``), independent of which tool will
    consume it.
    """

    STORY = "story"
    STORYBOARD = "storyboard"
    CHARACTER = "character"
    BACKGROUND = "background"
    IMAGE = "image"
    VIDEO = "video"
    VOICE = "voice"
    SONG = "song"
    THUMBNAIL = "thumbnail"
    SEO = "seo"
    PUBLISHING = "publishing"
