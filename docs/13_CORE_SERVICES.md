# 13 — Core Services

**Milestone:** 3 — Core Services
**Location:** `app/core/services/`
**Scope:** what each service is responsible for, how transactions are managed, and the exception hierarchy every service raises against.

---

## 1. Architecture Principles

- **Models stay thin.** `app/core/models/*.py` holds columns, relationships, and only the validation that's intrinsic to a field's shape (e.g. `Asset.relative_path` can't be absolute). Every actual business rule — "only an approved_canon version may become active," "an episode can't be marked ready to publish when checks fail" — lives in a service, not a model method.
- **Services are (mostly) stateless classes.** Each is instantiated with no required arguments (`EpisodeService()`) and every method takes an already-open SQLAlchemy `Session` as its first parameter. A few services that touch the filesystem (`StorageService`, `AssetImportService`, `ExportPackageService`) also accept an optional `AppConfig` in `__init__`, defaulting to `get_config()`.
- **No GUI imports anywhere in `app/core/`.** Milestone 4's GUI will call these same services; nothing here assumes a UI exists.
- **No generic repository layer.** Each service queries its own models directly (`session.query(Episode)...`) rather than routing through an abstract repository interface — with one service class per aggregate, that indirection would add a layer without adding flexibility (see `docs/07_DEVELOPMENT_PLAN.md`'s "avoid unnecessary complexity" principle).

## 2. Transaction Boundaries (Unit of Work)

`app/core/services/unit_of_work.py` defines the convention:

- Service methods `flush()` but never `commit()`. A `flush()` sends pending SQL to the database (so unique-constraint violations, foreign-key errors, etc. surface immediately as exceptions) without ending the transaction.
- The **caller** decides transaction boundaries via `session_scope(session_factory)`, a context manager that commits on success and rolls back (re-raising) on any exception. This lets a caller compose several service calls — e.g. create an episode, then add scenes, then generate default Shorts — into one atomic transaction.
- **The one documented exception:** `AssetImportService.import_asset` manages its own commit/rollback internally, because it spans both the database and the filesystem and must keep the two in sync regardless of whether the caller remembered to use `session_scope`. See `docs/14_ASSET_IMPORT_WORKFLOW.md`.

```python
from app.core.services.unit_of_work import session_scope

with session_scope(session_factory) as session:
    episode = EpisodeService().create_episode_from_template(session, ...)
    SceneService().add_scene(session, episode.id, ...)
# both commit together, or neither does
```

## 3. Exception Hierarchy

`app/core/services/exceptions.py` — every service raises one of these; nothing is ever silently swallowed.

```
ServiceError                    (base — catch this for "something in the service layer failed")
├── NotFoundError                the requested entity doesn't exist
├── ValidationError               input failed domain validation
│   └── PrivacyViolationError      would violate the personal-reference-photo rule
├── ConflictError                  conflicts with existing state (duplicate slug, checksum, ...)
├── InvalidTransitionError          an invalid state transition was attempted
├── ChecklistError                  a readiness checklist blocked a gated operation
├── ExportBlockedError               a final export was requested with blocking checklist issues
├── TemplateRenderError               prompt rendering failed (missing var, unsafe syntax)
└── AssetImportError                  an asset import failed after DB+filesystem rollback
```

## 4. Service-by-Service Summary

| Service | File | Responsibility |
|---|---|---|
| `EpisodeService` | `episode_service.py` | Episode CRUD, pipeline-stage transitions (free-form vs. gated), template scaffolding, structural duplication, progress. |
| `SceneService` | `scene_service.py` | Ordered scene CRUD with contiguous `order_index`, duplication, deletion protection. |
| `ShortService` | `short_service.py` | The 3 default Shorts + later additions, ordering, source-scene linking, readiness. |
| `CharacterService` | `character_service.py` | Character identity CRUD (name, age, role, traits) and archiving. |
| `CharacterVersionService` | `character_version_service.py` | The Character Lock lifecycle: versions, review/approval, active-version switching, reference artwork, lock-completeness validation. |
| `AssetImportService` | `asset_import_service.py` | The full non-GUI import workflow — see `docs/14`. |
| `StorageService` | `storage_service.py` | Safe filesystem primitives underneath `AssetImportService`/`ExportPackageService`: path resolution, atomic copy, checksums, cleanup. |
| `PromptTemplateService` | `prompt_template_service.py` | Prompt CRUD, versioning, sandboxed Jinja2 rendering, global/contextual resolution. |
| `ApprovalService` | `approval_service.py` | The generic, immutable approval audit trail across 7 entity types — see `docs/15`. |
| `LicenseService` | `license_service.py` | License/commercial-use history and readiness per asset — see `docs/15`. |
| `ProductionTaskService` | `production_task_service.py` | Per-episode checklist tasks, default set, progress, overdue (blocked) tasks. |
| `ProductionChecklistService` | `production_checklist_service.py` | The full "is this episode ready to publish" evaluation — one structured report. |
| `ExportPackageService` | `export_package_service.py` | Builds the manual YouTube export package — see `docs/16`. |

## 5. Episode Status vs. Production Stage

`Episode.pipeline_stage` is a single column, but two different methods change it, on purpose:

- `EpisodeService.change_production_stage()` moves freely through the day-to-day steps (`idea` → `lesson` → ... → `seo`) — no validation beyond "not one of the two gated stages" and "episode isn't already published."
- `EpisodeService.change_episode_status()` gates the two significant transitions:
  - `ready_to_publish` — only succeeds if `ProductionChecklistService.evaluate()` reports no blocking issues; raises `ChecklistError` otherwise.
  - `published` — only succeeds if the episode is currently `ready_to_publish`; sets `published_at`.

This directly implements "an episode cannot be marked Ready to Publish when required checks fail" without needing a second status column.

## 6. Character-Version Active Pointer

`Character.active_version_id` (added this milestone) is the single source of truth for "which version is current." `CharacterVersionService.set_active_character_version()`:

1. Validates the target version belongs to the character and is `approved_canon`.
2. Sets the pointer in one `flush()` within the caller's transaction — genuinely transactional (an exception anywhere in that transaction rolls the pointer change back with everything else).
3. Never touches the previously active version's row — it stays `approved_canon` and remains in `character.versions` history, satisfying "the previous active version should remain in history."

## 7. Free-Text `role` Convention on Asset

`Asset.role` (added this milestone) is a plain nullable string, not an enum — values like `"final_video"`, `"final_thumbnail"`, `"final_voice"`, `"final_music"` (constants in `app/core/models/asset.py`) mark which asset is *the* current deliverable of its kind for an episode or Short. `ProductionChecklistService` and `ExportPackageService` both key off `role.like("final_%")`. Kept a free string (not an enum) so a new role can be introduced without a migration — only the two services that interpret the convention need updating.

See also: `docs/14_ASSET_IMPORT_WORKFLOW.md`, `docs/15_APPROVAL_AND_LICENSE_WORKFLOW.md`, `docs/16_EXPORT_PACKAGE.md`.
