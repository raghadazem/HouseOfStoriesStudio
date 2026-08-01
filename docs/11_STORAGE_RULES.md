# 11 — Storage Rules

**Milestone:** 2 — Domain Model & Database
**Purpose:** the non-negotiable rules for where data lives, restated here as a single reference because they're enforced across the database layer, the filesystem layout, and (in later milestones) the import/GUI code.

## 1. The database never stores binary media

`SQLite` (`data/studio.db`) holds **metadata only**: text, numbers, UUIDs, timestamps, JSON lists of strings, and `relative_path` strings pointing at files. It never holds image/video/audio bytes.

Enforced by the `Asset` model itself — there is no `BLOB`/binary column anywhere in the schema (see `docs/10_DATABASE_SCHEMA.md`). Large creative files live under `production/` on the filesystem, per `docs/07_DEVELOPMENT_PLAN.md` §4 and §12.

## 2. Asset paths are always relative, never absolute

`Asset.relative_path` is relative to `AppConfig.production_dir`, never an absolute filesystem path. This is enforced in code, not just convention: `Asset.validate_relative_path` (in `app/core/models/asset.py`) rejects:

- Absolute POSIX paths (`/etc/passwd`)
- Absolute Windows paths (`C:\Users\...`, `\\network\share\...`) — checked explicitly because the app must run on Windows even though this codebase is developed/tested on Linux, where `pathlib.PurePath("C:\\foo").is_absolute()` returns `False` and would silently miss the case
- `..` parent-directory traversal
- Empty strings

Backslashes are normalized to forward slashes on write, so the stored value is always POSIX-style regardless of which OS the founder is on when they import a file. This is what makes the project folder portable — an absolute path baked into the database would break the instant the project folder moved (a new PC, a renamed drive letter, a synced cloud folder).

## 3. Duplicate imports are rejected at the database level

`Asset.checksum` (a sha256 hex digest) is a **unique** column. Importing the same file content under a different filename raises an `IntegrityError` immediately rather than silently creating a duplicate asset record. `Asset.relative_path` is also unique, so two assets can never claim the same file location.

This is deliberately a hard database constraint, not just an application-level check, because it's the last line of defense — any future import path (GUI drag-drop, CLI, a batch script) goes through the same table and gets the same guarantee for free.

## 4. Original personal reference photographs never enter this project

This is the founder's privacy rule (from the Milestone 1 approval message), restated here because it governs storage specifically:

- Original reference photographs (real people, used only as design inspiration) must **never** be committed to the repository, imported into `production/`, referenced by an `Asset` row, used in test fixtures, written to logs, or included in any generated export.
- They are kept entirely outside this project, in a private local location the founder manages themselves.
- Only **approved, original animated character artwork** may ever become an `Asset` row under `production/characters/<slug>/`.
- `.gitignore` additionally excludes common image/video/audio extensions under `production/` project-wide as a backstop (see `docs/07_DEVELOPMENT_PLAN.md` and the root `.gitignore`), so even an accidental `git add` of a media file requires deliberately overriding the ignore rule.
- The (future, Milestone 3+) Asset Importer must show a privacy warning at the point of importing anything into a character's reference set, per the founder's explicit instruction. Not yet implemented — Milestone 2 has no import UI, only the schema this rule is checked against.

## 5. Filenames are English, lowercase, snake_case

Per the founder's project-wide convention (`docs/07_DEVELOPMENT_PLAN.md`): `melissa_front_v01.png`, not `Melissa Front (1).png`. `Asset.original_filename` records whatever the source tool actually produced (for provenance); `Asset.relative_path` is where the *normalized* name is expected to live once a future import service renames it on the way in. Milestone 2 does not yet implement that renaming logic — it only defines the column that will hold the result.

## 6. Migrations own the schema; seed data never creates tables

`app/core/db/seed.py` assumes `alembic upgrade head` has already run and raises a clear `RuntimeError` if the expected tables aren't present, rather than silently calling `Base.metadata.create_all()` as a fallback. Schema changes always go through an Alembic migration — see `docs/10_DATABASE_SCHEMA.md`.

## 7. Foreign keys are always enforced

`PRAGMA foreign_keys=ON` is set on every connection this application opens (`app/core/db/engine.py::register_sqlite_pragma`), including inside Alembic (`alembic/env.py`). SQLite silently ignores foreign key violations unless this pragma is set — leaving it off would let, e.g., a `Scene` reference a deleted `Episode` with no error. This is verified by an automated test (`tests/unit/test_db_engine.py`).
