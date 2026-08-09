"""ApplicationContext — the GUI's single source of configuration/services/AI/logging/paths.

Per the founder's rule, **GUI code never instantiates a service
directly** (no ``EpisodeService()`` inside a page/widget). Every page
asks ``ApplicationContext`` instead. Today that mostly means "construct
the stateless service class" (every service in ``app.core.services`` is
cheap and stateless, per Milestone 3's design) — but centralizing it
here means a future need (shared caching, a different session strategy,
a mocked service in tests) changes one file, not every page.

Also owns the one thing every page needs to read data at all: a
SQLAlchemy session factory, wrapped in :meth:`session_scope` (the same
unit-of-work convention ``app.core.services`` already uses).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from functools import cached_property

from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import AppConfig, get_config
from app.core.ai.generation_job_service import GenerationJobService
from app.core.ai.orchestrator import AIOrchestrator
from app.core.ai.workflows import (
    CharacterReferenceWorkflow,
    SceneImageWorkflow,
    ThumbnailWorkflow,
    VoiceLineWorkflow,
    Workflow,
)
from app.core.db.engine import create_db_engine, create_session_factory
from app.core.services.approval_service import ApprovalService
from app.core.services.asset_import_service import AssetImportService
from app.core.services.character_service import CharacterService
from app.core.services.character_version_service import CharacterVersionService
from app.core.services.episode_service import EpisodeService
from app.core.services.export_package_service import ExportPackageService
from app.core.services.license_service import LicenseService
from app.core.services.production_checklist_service import ProductionChecklistService
from app.core.services.production_task_service import ProductionTaskService
from app.core.services.prompt_composer_service import PromptComposerService
from app.core.services.prompt_template_service import PromptTemplateService
from app.core.services.scene_service import SceneService
from app.core.services.script_service import ScriptService
from app.core.services.short_service import ShortService
from app.core.services.song_service import SongService
from app.core.services.storage_service import StorageService
from app.core.services.unit_of_work import session_scope as _service_session_scope
from app.logging_setup import configure_logging, get_logger


class ApplicationContext:
    """Everything a GUI page needs, constructed once at application startup."""

    def __init__(self, config: AppConfig | None = None) -> None:
        self.config: AppConfig = config or get_config()
        self.config.ensure_runtime_dirs()
        # force=True: each ApplicationContext represents one app session
        # with its own paths — logging must always point at *this*
        # config's log_dir, never a stale one from an earlier context
        # constructed in the same process (e.g. across GUI tests).
        configure_logging(self.config, force=True)
        self.logger = get_logger("gui")

        self.engine: Engine = create_db_engine(self.config)
        self.session_factory: sessionmaker[Session] = create_session_factory(self.engine)

    # --- session lifecycle -------------------------------------------------

    @contextmanager
    def session_scope(self) -> Iterator[Session]:
        """Commit-on-success / rollback-on-error session, for write operations."""
        with _service_session_scope(self.session_factory) as session:
            yield session

    def open_session(self) -> Session:
        """A plain, caller-managed session — for read-only queries (e.g. Dashboard counts)."""
        return self.session_factory()

    # --- paths (for the top/status bar) -------------------------------------

    @property
    def database_label(self) -> str:
        return self.config.db_path.name

    @property
    def workspace_label(self) -> str:
        return str(self.config.production_dir)

    # --- services (lazy, cached per context instance) -----------------------

    @cached_property
    def episode_service(self) -> EpisodeService:
        return EpisodeService()

    @cached_property
    def scene_service(self) -> SceneService:
        return SceneService()

    @cached_property
    def short_service(self) -> ShortService:
        return ShortService()

    @cached_property
    def script_service(self) -> ScriptService:
        return ScriptService()

    @cached_property
    def prompt_composer_service(self) -> PromptComposerService:
        return PromptComposerService()

    @cached_property
    def song_service(self) -> SongService:
        return SongService()

    @cached_property
    def character_service(self) -> CharacterService:
        return CharacterService()

    @cached_property
    def character_version_service(self) -> CharacterVersionService:
        return CharacterVersionService()

    @cached_property
    def storage_service(self) -> StorageService:
        return StorageService(self.config)

    @cached_property
    def asset_import_service(self) -> AssetImportService:
        return AssetImportService(self.config, self.storage_service)

    @cached_property
    def prompt_template_service(self) -> PromptTemplateService:
        return PromptTemplateService()

    @cached_property
    def approval_service(self) -> ApprovalService:
        return ApprovalService()

    @cached_property
    def license_service(self) -> LicenseService:
        return LicenseService()

    @cached_property
    def production_task_service(self) -> ProductionTaskService:
        return ProductionTaskService()

    @cached_property
    def production_checklist_service(self) -> ProductionChecklistService:
        return ProductionChecklistService()

    @cached_property
    def export_package_service(self) -> ExportPackageService:
        return ExportPackageService()

    @cached_property
    def ai_orchestrator(self) -> AIOrchestrator:
        """An orchestrator whose workflows import into *this* context's storage.

        Every real ``Workflow`` (``CharacterReferenceWorkflow`` and
        friends) defaults its ``AssetImportService`` to the process-wide
        cached ``get_config()`` when none is given — correct for the
        CLI/tests, which bind that cache explicitly, but wrong here: the
        GUI's own ``AppConfig`` (``self.config``, already used by every
        other service on this context) must be what generated files are
        imported against, not whatever config happened to be cached
        first in this process. Each workflow class is rebound with a
        zero-arg ``__init__`` (the shape ``AIOrchestrator``'s registry
        requires) that supplies this context's own
        ``asset_import_service``.
        """
        asset_import = self.asset_import_service

        def _bind(workflow_cls: type[Workflow]) -> type[Workflow]:
            return type(
                workflow_cls.__name__,
                (workflow_cls,),
                {"__init__": lambda self: workflow_cls.__init__(self, asset_import=asset_import)},
            )

        workflow_registry = {
            cls.name: _bind(cls)
            for cls in (
                CharacterReferenceWorkflow,
                SceneImageWorkflow,
                ThumbnailWorkflow,
                VoiceLineWorkflow,
            )
        }
        return AIOrchestrator(workflow_registry=workflow_registry)

    @cached_property
    def generation_job_service(self) -> GenerationJobService:
        return GenerationJobService()

    def dispose(self) -> None:
        """Release the database engine's connections (called on app exit)."""
        self.engine.dispose()
