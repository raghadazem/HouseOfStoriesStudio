"""AssetImportService — the complete non-GUI asset import workflow.

Validates a source file, computes its checksum, detects duplicates,
copies it into managed storage under a normalized filename, and
records an :class:`~app.core.models.asset.Asset` row — as a single
atomic operation. See ``docs/14_ASSET_IMPORT_WORKFLOW.md`` for the full
lifecycle and why this service (uniquely) owns its own transaction
instead of leaving that to the caller.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import AppConfig, get_config
from app.core.db.enums import ApprovalStatus, AssetType
from app.core.models import (
    Asset,
    Character,
    CharacterVersion,
    Episode,
    PromptTemplate,
    Scene,
    Short,
)
from app.core.models.asset import ROLE_FINAL_SCENE_IMAGE
from app.core.naming import normalize_filename
from app.core.services.exceptions import (
    AssetImportError,
    ConflictError,
    NotFoundError,
    PrivacyViolationError,
    ValidationError,
)
from app.core.services.storage_service import StorageService

_TYPE_FOLDER = {
    AssetType.IMAGE: "images",
    AssetType.VIDEO: "videos",
    AssetType.VOICE: "audio/voice",
    AssetType.MUSIC: "audio/music",
    AssetType.THUMBNAIL: "thumbnails",
    AssetType.DOCUMENT: "documents",
}


@dataclass(frozen=True)
class ImportRequest:
    """Everything needed to import one file, gathered up front for a single call.

    At most one of ``character_id`` / ``character_version_id`` should be
    given — if only ``character_id`` is given, the import resolves to
    that character's current *active* version (raising if it has none).
    """

    source_path: Path
    asset_type: AssetType
    episode_id: uuid.UUID | None = None
    scene_id: uuid.UUID | None = None
    short_id: uuid.UUID | None = None
    character_id: uuid.UUID | None = None
    character_version_id: uuid.UUID | None = None
    role: str | None = None
    source_tool: str | None = None
    prompt_used_id: uuid.UUID | None = None
    license_status: str | None = None
    commercial_use_status: str | None = None
    notes: str | None = None
    destination_subdir: str | None = None  # relative dir under production_dir; auto-derived if None


class AssetImportService:
    """Imports one external file into managed storage and records its Asset row.

    Unlike most services in this layer, :meth:`import_asset` manages its
    own transaction (commit/rollback) rather than leaving that to the
    caller's ``session_scope`` — it spans the filesystem *and* the
    database, and must keep both in sync even if the caller forgets to
    wrap the call in a scope.
    """

    def __init__(
        self,
        config: AppConfig | None = None,
        storage: StorageService | None = None,
    ) -> None:
        self._config = config or get_config()
        self._storage = storage or StorageService(self._config)

    def import_asset(self, session: Session, request: ImportRequest) -> Asset:
        """Validate, copy, and record one asset. Atomic: all-or-nothing.

        Raises:
            ValidationError: Missing/invalid source file, directory
                given instead of a file, or an association (scene/short)
                that doesn't belong to the given episode.
            PrivacyViolationError: The source file lives inside a
                configured restricted (personal reference photo) directory.
            NotFoundError: A referenced episode/scene/short/prompt/
                character/character-version doesn't exist.
            ConflictError: A byte-identical file has already been imported.
            AssetImportError: Any failure *after* the file copy began —
                both the copied file and any database change are rolled
                back before this is raised.
        """
        source = request.source_path
        self._validate_source_path(source)
        if not isinstance(request.asset_type, AssetType):
            raise ValidationError(f"Unsupported asset classification: {request.asset_type!r}")
        if request.role == ROLE_FINAL_SCENE_IMAGE:
            raise ValidationError(
                f"role={ROLE_FINAL_SCENE_IMAGE!r} is reserved and cannot be assigned through "
                "import_asset — it may only be assigned via SceneService.set_scene_key_image, "
                "which guarantees at most one Asset holds it per scene."
            )

        checksum = self._storage.compute_checksum(source)
        duplicate = self._storage.find_duplicate_by_checksum(session, checksum)
        if duplicate is not None:
            raise ConflictError(
                f"File is already imported as asset {duplicate.id} "
                f"({duplicate.relative_path}); checksum {checksum} matches an "
                f"existing asset."
            )

        effective_character_version_id = self._resolve_and_validate_associations(
            session, request
        )

        dest_subdir = request.destination_subdir or self._default_subdir(
            session, request, effective_character_version_id
        )
        normalized_name = normalize_filename(source.name)
        dest_relative_path = self._storage.collision_safe_relative_path(
            dest_subdir, normalized_name
        )

        copied_path: Path | None = None
        try:
            copied_path = self._storage.copy_file_atomic(source, dest_relative_path)
            self._storage.verify_checksum(copied_path, checksum)

            asset = Asset(
                asset_type=request.asset_type,
                original_filename=source.name,
                relative_path=dest_relative_path,
                checksum=checksum,
                source_tool=request.source_tool,
                license_status=request.license_status,
                commercial_use_status=request.commercial_use_status,
                role=request.role,
                prompt_used_id=request.prompt_used_id,
                character_version_id=effective_character_version_id,
                episode_id=request.episode_id,
                scene_id=request.scene_id,
                short_id=request.short_id,
                approval_status=ApprovalStatus.DRAFT,
                notes=request.notes,
            )
            session.add(asset)
            session.flush()
            session.commit()
        except Exception as err:
            session.rollback()
            if copied_path is not None:
                self._storage.cleanup(copied_path)
            raise AssetImportError(f"Failed to import {source}: {err}") from err

        return asset

    def _validate_source_path(self, source: Path) -> None:
        if not source.exists():
            raise ValidationError(f"Source file does not exist: {source}")
        if source.is_dir():
            raise ValidationError(f"Source path is a directory, not a file: {source}")
        if not source.is_file():
            raise ValidationError(f"Source path is not a regular file: {source}")

        resolved = source.resolve()
        for restricted in self._config.restricted_import_dirs:
            restricted_resolved = restricted.resolve()
            try:
                resolved.relative_to(restricted_resolved)
            except ValueError:
                continue
            raise PrivacyViolationError(
                f"Refusing to import from a restricted reference-photo directory: "
                f"{resolved} is inside {restricted_resolved}. Original personal "
                f"reference photographs must never enter this project — see "
                f"docs/11_STORAGE_RULES.md."
            )

    def _resolve_and_validate_associations(
        self, session: Session, request: ImportRequest
    ) -> uuid.UUID | None:
        """Validate episode/scene/short/prompt/character links; return the
        effective ``character_version_id`` to store (resolving from
        ``character_id`` -> that character's active version, if needed).
        """
        if request.episode_id is not None and session.get(Episode, request.episode_id) is None:
            raise NotFoundError(f"Episode {request.episode_id} not found.")

        if request.scene_id is not None:
            scene = session.get(Scene, request.scene_id)
            if scene is None:
                raise NotFoundError(f"Scene {request.scene_id} not found.")
            if request.episode_id is not None and scene.episode_id != request.episode_id:
                raise ValidationError("scene_id does not belong to the given episode_id.")

        if request.short_id is not None:
            short = session.get(Short, request.short_id)
            if short is None:
                raise NotFoundError(f"Short {request.short_id} not found.")
            if request.episode_id is not None and short.episode_id != request.episode_id:
                raise ValidationError("short_id does not belong to the given episode_id.")

        if (
            request.prompt_used_id is not None
            and session.get(PromptTemplate, request.prompt_used_id) is None
        ):
            raise NotFoundError(f"PromptTemplate {request.prompt_used_id} not found.")

        if request.character_version_id is not None:
            if session.get(CharacterVersion, request.character_version_id) is None:
                raise NotFoundError(
                    f"CharacterVersion {request.character_version_id} not found."
                )
            return request.character_version_id

        if request.character_id is not None:
            character = session.get(Character, request.character_id)
            if character is None:
                raise NotFoundError(f"Character {request.character_id} not found.")
            if character.active_version_id is None:
                raise ValidationError(
                    f"Character {character.slug!r} has no active version yet; "
                    "pass character_version_id explicitly or set an active "
                    "version first."
                )
            return character.active_version_id

        return None

    def _default_subdir(
        self,
        session: Session,
        request: ImportRequest,
        effective_character_version_id: uuid.UUID | None,
    ) -> str:
        type_folder = _TYPE_FOLDER[request.asset_type]

        if effective_character_version_id is not None:
            version = session.get(CharacterVersion, effective_character_version_id)
            character = session.get(Character, version.character_id)
            return f"characters/{character.slug}/versions/{version.version_number}"

        if request.episode_id is not None:
            episode = session.get(Episode, request.episode_id)
            return f"episodes/{episode.slug}/{type_folder}"

        return f"_imports/{type_folder}"
