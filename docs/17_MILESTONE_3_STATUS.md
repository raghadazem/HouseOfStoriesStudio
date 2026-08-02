# 17 — Milestone 3 Status

**Milestone:** 3 — Core Services
**Status:** Complete. Stopped before Milestone 4 (GUI) per instructions.
**Not pushed to GitHub** — committed locally only, per instruction.

---

## 1. What Was Completed

All 13 requested services, built in dependency order (character services before the checklist that reads them; scene/short/task services before the episode service and checklist that orchestrate them; the checklist before the export service that gates on it):

`StorageService`, `AssetImportService`, `CharacterService`, `CharacterVersionService`, `PromptTemplateService`, `ApprovalService`, `LicenseService`, `ProductionTaskService`, `SceneService`, `ShortService`, `EpisodeService`, `ProductionChecklistService`, `ExportPackageService` — every method named in the milestone spec is implemented; see `docs/13_CORE_SERVICES.md` for the full responsibility table.

Plus:
- A small **developer CLI** (`app/cli/main.py`, `python -m app.cli.main --help`) with all 10 requested commands, reusing the exact same services.
- A **unit-of-work convention** (`app/core/services/unit_of_work.py::session_scope`) and a **7-class exception hierarchy** (`app/core/services/exceptions.py`) shared by every service.
- `app/core/naming.py`: `slugify`/`normalize_filename`/`collision_safe_name` — the English-snake_case filename convention, with a stable fallback for non-ASCII (Arabic) source filenames.
- Three schema-additive Alembic migrations (below), needed because several requested behaviors had no column to store their state in yet.
- 163 new tests (237 total, up from 74 at the end of Milestone 2).

### Schema additions this milestone

No Milestone 1/2 table was altered destructively — every change is a new nullable/defaulted column or a new table, applied via three migrations (`98db36ba39d7`, `8ed8cbd56eee`, plus the Milestone 2 baseline `37154bea36d1`):

| Table | Added | Why |
|---|---|---|
| `characters` | `is_archived`, `active_version_id` | `archive_character`; "at most one active version per Character." |
| `character_versions` | *(none — already had everything)* | |
| `prompt_templates` | `category`, `is_archived` | The founder's approved prompt-category list; `archive_prompt_template`. |
| `license_records` | `proof_relative_path`, `attribution_required`, `attribution_text` | "proof files must use managed relative paths"; attribution requirement/text. |
| `episodes` | `description_ar`, `description_en`, `hashtags`, `credits_text` | Deterministic export metadata without parsing hand-edited Markdown. |
| `assets` | `scene_id`, `short_id`, `role` | "associate asset with Episode, Scene, Short, ..."; the `final_*` role convention `ProductionChecklistService`/`ExportPackageService` both key off. |
| `shorts` | `working_title_en`, `hook_ar`, `caption_ar`, `hashtags` | Every field `ExportPackageService` needs to write per Short. |
| *(new table)* `short_scenes` | — | Many-to-many `Short` ↔ `Scene`, for `link_source_scenes`/`unlink_source_scene`. |
| `scenes` | `estimated_duration_seconds` | `calculate_total_scene_duration` needed a real data source, not a heuristic. |

Full column-level reference: run `alembic history` or see the migration files under `alembic/versions/`; `docs/10_DATABASE_SCHEMA.md` (Milestone 2) is not re-published here — treat it as superseded by the current models for these tables.

## 2. Files Created and Modified

**Created:**
```
app/core/naming.py
app/core/models/_path_validation.py
app/core/services/__init__.py
app/core/services/exceptions.py
app/core/services/unit_of_work.py
app/core/services/storage_service.py
app/core/services/asset_import_service.py
app/core/services/character_service.py
app/core/services/character_version_service.py
app/core/services/prompt_template_service.py
app/core/services/approval_service.py
app/core/services/license_service.py
app/core/services/production_task_service.py
app/core/services/scene_service.py
app/core/services/short_service.py
app/core/services/episode_service.py
app/core/services/production_checklist_service.py
app/core/services/export_package_service.py
app/cli/main.py
alembic/versions/98db36ba39d7_milestone_3_schema_additions.py
alembic/versions/8ed8cbd56eee_scene_estimated_duration.py
docs/13_CORE_SERVICES.md
docs/14_ASSET_IMPORT_WORKFLOW.md
docs/15_APPROVAL_AND_LICENSE_WORKFLOW.md
docs/16_EXPORT_PACKAGE.md
docs/17_MILESTONE_3_STATUS.md   (this file)
tests/unit/test_naming.py
tests/unit/test_storage_service.py
tests/unit/test_asset_import_service.py
tests/unit/test_episode_service.py
tests/unit/test_scene_service.py
tests/unit/test_short_service.py
tests/unit/test_character_service.py
tests/unit/test_character_version_service.py
tests/unit/test_prompt_template_service.py
tests/unit/test_approval_service.py
tests/unit/test_license_service.py
tests/unit/test_production_task_service.py
tests/integration/test_production_checklist_service.py
tests/integration/test_export_package_service.py
tests/integration/test_persistence.py
tests/integration/test_cli.py
```

**Modified:**
```
app/config.py                     (+ restricted_import_dirs / HOS_RESTRICTED_IMPORT_DIRS)
app/core/db/enums.py               (+ PromptCategory)
app/core/models/__init__.py        (+ short_scenes export)
app/core/models/asset.py           (+ scene_id, short_id, role, ROLE_* constants; relative_path validator now shared)
app/core/models/character.py       (+ is_archived, active_version_id, active_version relationship)
app/core/models/episode.py         (+ Episode SEO fields; Short new fields; short_scenes table; Scene.estimated_duration_seconds)
app/core/models/license.py         (+ proof_relative_path, attribution_required, attribution_text)
app/core/models/prompt.py          (+ category, is_archived)
app/cli/__init__.py                (docstring update — no longer a placeholder)
pyproject.toml                     (+ [project.scripts] hos-cli entry point)
tests/conftest.py                  (+ app_config, source_file fixtures for filesystem-touching services)
tests/integration/test_migrations.py  (+ short_scenes in expected table set)
```

## 3. Test Count and Results

```
$ pytest -q
........................................................................ [ 30%]
........................................................................ [ 60%]
........................................................................ [ 91%]
.....................                                                    [100%]
237 passed in ~25s

$ ruff check .
All checks passed!
```

163 new tests since Milestone 2 (74 → 237), covering every category the founder listed: successful operations, invalid transitions, transaction rollback, active-version switching, rejected reference types, duplicate detection, checksum verification, filename normalization (including Arabic), private-directory rejection, path traversal, failed-import cleanup, prompt rendering + missing variables + version history, approval-history immutability, required rejection notes, license history, commercial-readiness decisions, task progress/overdue, scene reorder normalization, Short source-scene validation, readiness failure *and* success (a full integration test builds a genuinely 100%-ready episode end to end and then walks it through `ready_to_publish` → `published`), preview export, blocked final export, deterministic export structure, Arabic export files, database persistence across close/reopen, and CLI smoke tests.

One real bug was caught and fixed during this pass: `SceneService.delete_scene`/`ShortService.delete_short` decremented sibling `order_index`/`short_index` values one row at a time, which is safe in isolation but not guaranteed safe once SQLAlchemy batches multiple UPDATEs in a flush — a full-suite run (not an isolated one) hit a transient unique-constraint collision because flush order didn't match loop order. Fixed by applying the same two-phase negative-then-final update pattern already used in `reorder_scenes`/`reorder_shorts` and `_shift_up`. Full detail in the commit; all 237 tests (including two full-suite runs) now pass consistently.

## 4. Manual Completion-Checklist Verification

Beyond the automated suite, every step the founder listed was run by hand against the real project (not test fixtures):

1. `alembic upgrade head` on a clean `data/studio.db` — all 3 migrations applied cleanly.
2. `python -m app.cli.main seed-demo` — Melissa, Bilsan, Episode 001, 3 Shorts created.
3. CLI exercised: `list-episodes`, `show-episode`, `create-default-tasks` (created 15 tasks), `check-episode`.
4. Imported one real (non-personal, hand-created test) asset via `import-asset` — succeeded, file copied to `production/_imports/images/`, source left untouched.
5. Re-imported the same file — `ConflictError`, correctly rejected as a duplicate by checksum.
6. Attempted to import a directory — rejected with a clear error; confirmed nothing was written to `production/` (file count unchanged before/after).
7. `check-episode` on the freshly seeded (still-empty) Episode 001 — correctly reported `NOT READY` at 43.5%, with the exact set of blocking issues expected (no scenes, no final video/thumbnail/voice, no license records, no approved active character versions, 15 incomplete tasks).
8. `export-episode ep001_lost_little_turtle --preview` — succeeded, produced the full file/folder structure described in `docs/16_EXPORT_PACKAGE.md`.
9. Closed the database engine entirely and opened a **new** engine against the same `studio.db` file — Melissa's Arabic name, the episode's Arabic title, and the imported asset were all present and correct, confirming persistence.
10. Manually inspected every file under `production/` and grepped the git status for image/video/audio extensions — found only the one manually-created test asset (plain text content, not a photo of any person), which was then deleted along with the test export before committing, so the actual commit contains no imported media at all — only the tracked `README.md` placeholders, exactly as before this milestone.

## 5. Assumptions Made

1. **Three new Alembic migrations, not one.** The founder's spec described several behaviors (`archive_character`, prompt categories, attribution, `role`, Short content fields, scene duration) that had no backing column in the Milestone 2 schema. Rather than skip or fake these, real columns were added — each migration is small, additive, and documented above.
2. **`list_overdue_tasks` treats `blocked` status as "overdue."** `ProductionTask` has no due-date column, and none was requested; for a solo creator with no formal scheduling, "blocked" is the closest real signal to "needs attention." Documented in the service's docstring.
3. **`Episode.pipeline_stage` is used for both `change_production_stage` and `change_episode_status`**, split by which values each accepts, rather than adding a second status column — see `docs/13_CORE_SERVICES.md` §5.
4. **`duplicate_episode_structure` copies scene *locations* and *count*, not descriptions/dialogue.** "Structure" was read as the skeleton, not the writing — copying actual dialogue would risk being read as generating creative content, which is out of scope for this milestone.
5. **`AssetImportService.import_asset` owns its own transaction**, as the one documented exception to the "services only flush, caller commits" convention — justified in `docs/14_ASSET_IMPORT_WORKFLOW.md` §3.
6. **No image content is ever inspected.** File "metadata inspection" is limited to path/size/extension — never opening a file as an image, never any face/identity detection, per the explicit prohibition.

## 6. Unresolved Decisions

- **Export folder retention**: `exports/preview/` and `exports/final/` are overwritten on every export (deterministic, single-slot). If the founder wants to keep a history of past exports (e.g. for comparing what was actually uploaded at different times), that would need a versioned or timestamped export folder scheme — not built, since "deterministic" and "keep every past export" are in tension and the spec asked for the former.
- **`ProductionTask.task_type` remains a free string.** This keeps the default checklist flexible, but means there's no schema-level guarantee a GUI dropdown (Milestone 4) will only ever show known types — worth a decision before that screen is built.
- **Whether `Scene.location` should eventually reference a `Location`/World Bible table** is still open from Milestone 2 (confirmed out of scope for Milestone 3 per your explicit instruction) — still worth flagging as the next natural schema extension once locations need their own reference art.

## 7. Recommended Next Step

Awaiting approval before Milestone 4 — the minimal PySide6 GUI (Dashboard, Episode Manager, Character Library, Asset Importer, Prompt Manager), calling these exact services and nothing else.
