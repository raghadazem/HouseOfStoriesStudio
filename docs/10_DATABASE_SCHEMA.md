# 10 — Database Schema

**Milestone:** 2 — Domain Model & Database
**Engine:** SQLite, via SQLAlchemy 2.x + Alembic. `PRAGMA foreign_keys=ON` is enabled on every connection (`app/core/db/engine.py::register_sqlite_pragma`) — SQLite does not enforce foreign keys by default, and SQLAlchemy does not turn this on automatically.
**Migration strategy:** Alembic, `alembic/versions/`. Current head: `37154bea36d1` ("initial schema"). Migrations always operate against the database path resolved by `app.config.get_config()` (respecting `HOS_DATA_DIR`), not a hardcoded path — see `alembic/env.py`.
**Enums:** stored as `VARCHAR` with a CHECK constraint (`native_enum=False`), not SQLite's nonexistent native enum type — this keeps the column trivially readable with any SQLite browser.

All 13 tables below also carry `id` (`CHAR(32)`, UUID primary key), `created_at`, and `updated_at` (`DATETIME`, timezone-aware), omitted from the per-table column lists for brevity.

---

## characters

| Column | Type | Constraints |
|---|---|---|
| slug | VARCHAR(64) | UNIQUE, NOT NULL |
| name_ar | VARCHAR(128) | NOT NULL |
| name_en | VARCHAR(128) | NOT NULL |
| age | INTEGER | nullable |
| role | VARCHAR(128) | nullable |
| traits | JSON | NOT NULL (default `[]`) |

## character_versions

| Column | Type | Constraints |
|---|---|---|
| character_id | UUID | FK → characters.id, ON DELETE CASCADE |
| version_number | VARCHAR(16) | NOT NULL |
| outfit_version | VARCHAR(16) | nullable |
| description_of_change | TEXT | nullable |
| visual_summary | TEXT | nullable |
| color_palette | JSON | NOT NULL (default `[]`) |
| allowed_accessories | JSON | NOT NULL (default `[]`) |
| relative_height | VARCHAR(64) | nullable |
| master_prompt | TEXT | nullable |
| negative_prompt | TEXT | nullable |
| status | ENUM(draft, in_review, approved_canon, archived) | NOT NULL, default `draft` |
| decided_at | DATETIME | nullable |
| decided_by | VARCHAR(128) | nullable |
| review_notes | TEXT | nullable |

**Unique:** `(character_id, version_number)` — `uq_character_version_number`.

## character_references

| Column | Type | Constraints |
|---|---|---|
| character_id | UUID | FK → characters.id, ON DELETE CASCADE |
| character_version_id | UUID | FK → character_versions.id, ON DELETE SET NULL, nullable |
| asset_id | UUID | FK → assets.id, ON DELETE CASCADE, **UNIQUE** |
| label | VARCHAR(64) | nullable |
| is_current_canon | BOOLEAN | NOT NULL, default `false` |

## episodes

| Column | Type | Constraints |
|---|---|---|
| slug | VARCHAR(128) | UNIQUE, NOT NULL |
| number | INTEGER | UNIQUE, NOT NULL |
| season | INTEGER | NOT NULL, default `1` |
| title_ar | VARCHAR(256) | NOT NULL |
| title_en | VARCHAR(256) | NOT NULL |
| lesson | VARCHAR(256) | NOT NULL |
| logline_ar | TEXT | nullable |
| dialogue_language | VARCHAR(64) | NOT NULL, default `simple_white_arabic` |
| runtime_target_minutes_min | INTEGER | NOT NULL, default `8` |
| runtime_target_minutes_max | INTEGER | NOT NULL, default `10` |
| includes_song | BOOLEAN | NOT NULL, default `false` |
| pipeline_stage | ENUM(idea..published, 14 values) | NOT NULL, default `idea` |
| published_at | DATETIME | nullable |
| youtube_url | VARCHAR(512) | nullable |

## scenes

| Column | Type | Constraints |
|---|---|---|
| episode_id | UUID | FK → episodes.id, ON DELETE CASCADE |
| order_index | INTEGER | NOT NULL |
| location | VARCHAR(128) | nullable |
| description | TEXT | nullable |
| dialogue_ar | TEXT | nullable |

**Unique:** `(episode_id, order_index)` — `uq_scene_order_per_episode`.

## shorts

| Column | Type | Constraints |
|---|---|---|
| episode_id | UUID | FK → episodes.id, ON DELETE CASCADE |
| short_index | INTEGER | NOT NULL (1, 2, or 3) |
| title_ar | VARCHAR(256) | nullable |
| source_timestamp_range | VARCHAR(64) | nullable |
| status | ENUM(planned, edited, exported, published) | NOT NULL, default `planned` |
| export_asset_id | UUID | FK → assets.id, ON DELETE SET NULL, nullable |

**Unique:** `(episode_id, short_index)` — `uq_short_index_per_episode`.

## assets

| Column | Type | Constraints |
|---|---|---|
| asset_type | ENUM(image, video, voice, music, thumbnail, document) | NOT NULL |
| original_filename | VARCHAR(256) | NOT NULL |
| relative_path | VARCHAR(1024) | **UNIQUE**, NOT NULL |
| checksum | VARCHAR(64) | **UNIQUE**, NOT NULL (sha256 hex) |
| source_tool | VARCHAR(128) | nullable |
| license_status | VARCHAR(128) | nullable |
| commercial_use_status | VARCHAR(64) | nullable |
| prompt_used_id | UUID | FK → prompt_templates.id, ON DELETE SET NULL, nullable |
| character_version_id | UUID | FK → character_versions.id, ON DELETE SET NULL, nullable |
| episode_id | UUID | FK → episodes.id, ON DELETE SET NULL, nullable |
| approval_status | ENUM(draft, in_review, approved, rejected) | NOT NULL, default `draft` |
| notes | TEXT | nullable |

**Never stores binary data** — `relative_path` points to a file under `production/` (see `docs/11_STORAGE_RULES.md`).

## prompt_templates

| Column | Type | Constraints |
|---|---|---|
| name | VARCHAR(128) | NOT NULL |
| version | VARCHAR(16) | NOT NULL, default `v01` |
| prompt_type | ENUM(image, video, voice, music, text) | NOT NULL |
| text_en | TEXT | NOT NULL |
| is_reusable | BOOLEAN | NOT NULL, default `false` |
| target_tool | VARCHAR(128) | nullable |
| character_id | UUID | FK → characters.id, ON DELETE SET NULL, nullable |
| episode_id | UUID | FK → episodes.id, ON DELETE SET NULL, nullable |
| scene_id | UUID | FK → scenes.id, ON DELETE SET NULL, nullable |

**Unique:** `(name, version)` — `uq_prompt_name_version`.

## production_tasks

| Column | Type | Constraints |
|---|---|---|
| episode_id | UUID | FK → episodes.id, ON DELETE CASCADE |
| task_type | VARCHAR(64) | NOT NULL |
| title | VARCHAR(256) | NOT NULL |
| description | TEXT | nullable |
| status | ENUM(pending, in_progress, blocked, done) | NOT NULL, default `pending` |

## approval_records

| Column | Type | Constraints |
|---|---|---|
| entity_type | VARCHAR(64) | NOT NULL |
| entity_id | UUID | NOT NULL, **not a foreign key** (polymorphic) |
| decision | ENUM(approved, rejected, needs_changes) | NOT NULL |
| decided_by | VARCHAR(128) | nullable |
| decided_at | DATETIME | NOT NULL |
| notes | TEXT | nullable |

**Index:** `ix_approval_records_entity` on `(entity_type, entity_id)` for lookup.

## license_records

| Column | Type | Constraints |
|---|---|---|
| asset_id | UUID | FK → assets.id, ON DELETE CASCADE |
| license_type | VARCHAR(64) | NOT NULL |
| source_url | VARCHAR(512) | nullable |
| terms_summary | TEXT | nullable |
| commercial_use_allowed | BOOLEAN | nullable |
| verified | BOOLEAN | NOT NULL, default `false` |
| verified_at | DATETIME | nullable |
| notes | TEXT | nullable |

## Association (many-to-many) tables

**episode_characters** — `(episode_id, character_id)`, both FK CASCADE, composite PK.
**scene_characters** — `(scene_id, character_id)`, both FK CASCADE, composite PK.

---

## Running migrations

```bash
# Apply all migrations (creates data/studio.db if it doesn't exist)
alembic upgrade head

# Roll back everything (drops all tables except alembic_version)
alembic downgrade base

# Check for model changes not yet captured in a migration
alembic check

# After changing a model, generate the next migration
alembic revision --autogenerate -m "describe the change"
```

Alembic is configured with `render_as_batch=True` (`alembic/env.py`), which is required for SQLite: it can't `ALTER TABLE` most column changes in place, so batch mode has Alembic recreate the table under the hood instead.
