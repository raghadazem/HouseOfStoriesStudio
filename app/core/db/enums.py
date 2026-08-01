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
