# 14 — Asset Import Workflow

**Milestone:** 3 — Core Services
**Services:** `AssetImportService` + `StorageService` (`app/core/services/asset_import_service.py`, `storage_service.py`)

---

## 1. Why This Import Workflow Exists Without a GUI

Milestone 3 explicitly excludes GUI work. `AssetImportService.import_asset()` is the entire import pipeline the future Character Library / Asset Importer screens (Milestone 4) will call — every validation, safety check, and rollback behavior described here is already real, tested code, not a placeholder.

## 2. The Import Lifecycle

`import_asset(session, request: ImportRequest) -> Asset` runs these steps, in order, stopping at the first failure:

1. **Validate the source path.** Must exist, must be a file (not a directory), must be a regular file.
2. **Privacy check.** If the resolved source path falls inside any directory listed in `AppConfig.restricted_import_dirs` (configured via `HOS_RESTRICTED_IMPORT_DIRS`), raise `PrivacyViolationError` immediately — before any hashing or copying happens. This is the enforcement point for "original personal reference photographs must never enter this project."
3. **Classification check.** `request.asset_type` must be a real `AssetType` enum member. There is no `personal_photo` value in that enum — by construction, no asset can ever be classified that way (see §5).
4. **Compute the sha256 checksum** of the source file (streamed, not loaded fully into memory).
5. **Duplicate detection.** Query `Asset.checksum` for an existing match; if found, raise `ConflictError` naming the existing asset — nothing is copied or written.
6. **Resolve associations.** Validate any given `episode_id`/`scene_id`/`short_id`/`prompt_used_id`/`character_id`/`character_version_id` actually exist, and that a given `scene_id`/`short_id` belongs to the given `episode_id`. If only `character_id` is given (no explicit version), resolve to that character's current *active* version — raising `ValidationError` if it has none yet.
7. **Compute the destination path.** A normalized, collision-safe filename (see `docs/07_DEVELOPMENT_PLAN.md`'s snake_case rule) under a destination folder derived from the association (`characters/<slug>/versions/<version>/`, `episodes/<slug>/<type_folder>/`, or `_imports/<type_folder>/` if unassociated).
8. **Copy the file atomically** (`StorageService.copy_file_atomic`): copy to a temp file in the destination directory, then `os.replace` into place. An interrupted copy never leaves a half-written file at the final path.
9. **Verify the checksum of the copy** matches the checksum computed from the source — catches silent corruption during copy.
10. **Insert the `Asset` row**, `flush()`, then `commit()`.
11. **On any exception from step 8 onward:** `session.rollback()`, then `StorageService.cleanup()` the copied file if one exists, then raise `AssetImportError` wrapping the original exception (`raise ... from err`).

The **source file is never deleted or modified**, at any step, on any path — including failure paths.

## 3. Why `import_asset` Owns Its Own Transaction

Every other service in this codebase follows the "flush only, caller commits via `session_scope`" convention (`docs/13_CORE_SERVICES.md` §2). `AssetImportService.import_asset` is the one documented exception: it spans two resources — the filesystem and the database — that must stay in sync. If it only flushed and left `commit()`/`rollback()` to the caller, a caller that forgot to wrap the call in `session_scope` could end up with a copied file and no matching database row (or vice versa). Owning the transaction end-to-end guarantees atomicity regardless of what the caller does.

## 4. Rollback Behavior in Detail

| Failure point | Database state after | Filesystem state after |
|---|---|---|
| Source validation fails (missing/directory/restricted dir) | No row ever created | No file ever copied |
| Duplicate detected | No row ever created | No file ever copied |
| Association validation fails (unknown episode/scene/etc.) | No row ever created | No file ever copied |
| Copy or checksum-verify fails | Rolled back — no row | Copied file deleted via `StorageService.cleanup()` |
| `Asset` row insert fails (e.g. race-condition unique-constraint hit) | Rolled back — no row | Copied file deleted |

Verified by `tests/unit/test_asset_import_service.py::test_import_asset_rolls_back_db_and_filesystem_on_failure`, which monkeypatches a post-copy step to fail and asserts both the DB and filesystem end up clean.

## 5. Why There Is No "Personal Photo" Classification

The founder's rule — "do not allow a personal-photo asset classification" — is enforced structurally, not by a runtime check that could be bypassed:

- `AssetType` (`app/core/db/enums.py`) has exactly six values: `image`, `video`, `voice`, `music`, `thumbnail`, `document`. There is no `personal_photo` member to select, at the type level.
- `import_asset` additionally guards with `isinstance(request.asset_type, AssetType)`, so even a caller that bypasses type checking (e.g. a raw string from an untrusted source) and passes something like `"personal_photo"` is rejected with a clear `ValidationError` before anything else runs.
- Combined with the restricted-directory check in step 2, no image of a real person from the founder's private reference folder can become an `Asset` row: either it's inside a restricted directory (rejected at step 2) or it's simply imported as an ordinary `image` asset the founder chose to bring in deliberately — the system has no way to distinguish "personal photo" from "any other image" except by directory, which is exactly the control point the founder specified.

`CharacterVersionService.add_character_reference` (see `docs/13`) then only accepts already-`approved` `image`/`video` assets as character reference art — by the time an asset reaches that gate, it has already passed the import-time privacy check.

## 6. StorageService: the Filesystem Primitives

Everything above sits on `StorageService`, which is the *only* place in the codebase that touches the filesystem for managed assets:

- `resolve_managed_path(relative_path)` — joins against `AppConfig.production_dir`, resolves symlinks/`..`, and raises `ValidationError` if the result falls outside `production_dir`. This is the path-traversal guard.
- `copy_file_atomic` — temp-file-then-`os.replace` pattern (§2 step 8).
- `compute_checksum` / `verify_checksum` — sha256, streamed.
- `collision_safe_relative_path` — if the desired filename already exists in the destination directory, appends `_2`, `_3`, ... (`app/core/naming.py::collision_safe_name`).
- `cleanup(path)` — idempotent delete, refuses (silently) to delete anything outside `production_dir`, as defense-in-depth even though every caller is expected to only ever pass a managed path.
- `find_duplicate_by_checksum` — the query behind step 5.
- `prepare_export_copy` — used by `ExportPackageService` (`docs/16`) to copy a managed asset into an export folder without mutating the original.

## 7. Filename Normalization

`app/core/naming.py::normalize_filename` converts any source filename into `lowercase_snake_case.ext`:

- ASCII text is slugified directly (`"Melissa Front (1).PNG"` → `"melissa_front_1.png"`).
- Non-ASCII text (e.g. an Arabic filename like `"ميليسا.png"`) has no ASCII-safe content to slugify, so it falls back to a **stable, content-derived** name (`"file_<8-char-sha1-hex>.png"`) rather than crashing or producing an empty/unsafe filename. The same input always produces the same fallback name.
- The **original filename is never lost** — it's stored verbatim (including Arabic) in `Asset.original_filename`; only the on-disk path uses the normalized form.

## 8. What Metadata Every Import Records

Per the founder's approved requirements, every `Asset` row carries: `asset_type`, `original_filename`, `relative_path` (managed, relative), `checksum`, `source_tool`, `license_status`, `commercial_use_status`, `role`, `prompt_used_id`, `character_version_id`, `episode_id`/`scene_id`/`short_id`, `approval_status` (defaults to `draft`), and `notes`. `created_at` (from the timestamp mixin) doubles as "imported date." Fuller license documentation and history lives in `LicenseRecord` — see `docs/15_APPROVAL_AND_LICENSE_WORKFLOW.md`.
