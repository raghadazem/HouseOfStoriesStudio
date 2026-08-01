# 09 — Domain Model

**Milestone:** 2 — Domain Model & Database
**Scope:** the 11 SQLAlchemy 2.x models in `app/core/models/`, what each represents, and why it's shaped the way it is.

All models inherit two mixins from `app/core/db/base.py`:

- `UUIDPrimaryKeyMixin` — a UUID `id` primary key (stored as a 32-char hex string on SQLite; there's no native SQLite UUID type).
- `TimestampMixin` — `created_at` / `updated_at`, both timezone-aware UTC, set in Python (not a DB server default) so behavior is identical regardless of backend.

Enums live in `app/core/db/enums.py` and are plain `str` subclasses, so they compare equal to their string value and serialize cleanly.

---

## Character

The stable identity of a main character (Melissa, Bilsan). Holds only what doesn't change design-to-design: name (Arabic/English), age, role, and a free-text `traits` list (JSON column).

Deliberately does **not** hold visual design details (outfit, palette, prompt blocks) — those live on `CharacterVersion`, because a character's *design* can be revised over the life of the show while its *identity* doesn't change.

**Relationships:** `versions` (one-to-many, cascade delete), `references` (one-to-many, cascade delete).

## CharacterVersion

One design revision — the actual Character Lock record from the founder's approved Milestone 2 workflow. Every field the founder specified is present:

`visual_specification` → `visual_summary`, `color_palette` (JSON list), `allowed_accessories` (JSON list), `relative_height`
`master_prompt` / `negative_prompt`
`approved_reference_assets` → via the `CharacterReference` join table (see below), not a column here
`reference_version` → `version_number`
`outfit_version` → `outfit_version`
`approval_status` → `status` (`draft` / `in_review` / `approved_canon` / `archived`)
`review_notes` → `review_notes`

Also: `description_of_change`, `decided_at`, `decided_by`.

**Unique constraint:** `(character_id, version_number)` — the same character can't have two `v01`s, but different characters can each have their own `v01` independently.

Why version history matters: an episode produced against `v01` should always be traceable to exactly what "on-model" meant at that time, even after the design moves to `v02` — nothing here is overwritten in place.

## CharacterReference

A thin join between one approved `Asset` (artwork file) and the character/version it's canon reference art for, with a `label` (e.g. `"front_view"`, `"outfit_closeup"`) and an `is_current_canon` flag.

Deliberately thin: the asset row itself (path, checksum, license, approval status) is the single source of truth for the file. This table only answers "which character/version is this file reference art for."

**Constraint:** `asset_id` is unique — one asset can't be linked as reference art twice.

## Episode

One long-form (8–10 minute) episode and its position in the production pipeline (`pipeline_stage`, matching `docs/04_PRODUCTION_PIPELINE.md`). Carries the approved production spec fields: `dialogue_language` (defaults to `"simple_white_arabic"`), `runtime_target_minutes_min/max` (defaults 8/10), `includes_song`.

**Relationships:** `scenes` (one-to-many, ordered, cascade delete), `shorts` (one-to-many, ordered, cascade delete), `characters_featured` (many-to-many via `episode_characters`).

**Uniqueness:** `slug` and `number` are both unique — an episode is addressable by either.

## Scene

One entry in an episode's script/storyboard breakdown: `order_index`, `location` (free text — no `Location` model yet, see Open Questions in `docs/12`), `description`, `dialogue_ar`, and `characters_present` (many-to-many via `scene_characters`).

**Constraint:** `(episode_id, order_index)` unique — no two scenes in the same episode can claim the same position.

## Short

One of the three YouTube Shorts a long episode produces (per the founder's approved production spec). `short_index` (1/2/3), `title_ar`, `source_timestamp_range` (where in the long episode it's cut from), `status` (`planned` / `edited` / `exported` / `published`), and an optional `export_asset_id` pointing at the final exported clip once it exists.

**Constraint:** `(episode_id, short_index)` unique.

## Asset

Metadata for one imported file — **never the file itself**. See `docs/11_STORAGE_RULES.md` for the full storage rule. Carries every field the founder's approved decisions required an asset to record: `asset_type`, `original_filename`, `relative_path`, `checksum`, `source_tool`, `license_status`, `commercial_use_status`, `prompt_used_id`, `character_version_id`, `episode_id`, `approval_status`, `notes`. `created_at` (from the timestamp mixin) doubles as "imported date."

**Validation** (via SQLAlchemy `@validates`, not just a DB constraint — so the error surfaces immediately in Python, not only on flush):
- `relative_path` must not be absolute (checked against both POSIX and Windows conventions, since the app must run on Windows but its tests run on Linux) and must not contain `..` traversal. Backslashes are normalized to forward slashes.
- `checksum` must be a 64-character lowercase sha256 hex digest.

**Uniqueness:** `relative_path` (two assets can't occupy the same file location) and `checksum` (the database-level half of duplicate-import detection — importing the same bytes under a different filename raises `IntegrityError` immediately rather than silently creating a second copy).

## PromptTemplate

A named, versioned prompt for an image/video/voice/music/text generator. `text_en` is always English (generators perform best that way) even when the scene it illustrates is Arabic. `is_reusable=True` marks character-lock/style-lock blocks meant to be pasted into many prompts; `is_reusable=False` (default) is for one-off, scene-specific prompts.

**Uniqueness:** `(name, version)` — the same prompt name can have multiple versions, but not two `v01`s.

## ProductionTask

One checklist item tied to an episode's production (`task_type` is a free-text string, not an enum — the set of possible tasks is defined by the founder's own workflow, not the schema). `status`: `pending` / `in_progress` / `blocked` / `done`.

## ApprovalRecord

A polymorphic audit-trail entry for any approve/reject/needs-changes decision (`entity_type` + `entity_id`, e.g. `("character_version", <uuid>)`). Deliberately **not** a foreign key — `entity_id` can point at rows in different tables depending on `entity_type`, which can't be expressed as a single FK constraint. One small table here beats a growing family of near-identical `*_approval` tables per approvable entity.

## LicenseRecord

Fuller license/commercial-use documentation for an asset than the quick-glance `license_status`/`commercial_use_status` fields already on `Asset` — `license_type`, `source_url`, `terms_summary`, `commercial_use_allowed`, `verified`/`verified_at`, `notes`. Exists because a monetized upload needs a real rights trail, not just a one-word status.

---

## Entity-Relationship Summary

```
Character 1──* CharacterVersion 1──* CharacterReference *──1 Asset
Character *──* Episode (episode_characters)
Character *──* Scene (scene_characters)
Episode 1──* Scene
Episode 1──* Short ──1 Asset (export_asset, nullable)
Episode 1──* ProductionTask
Character/Episode/Scene 1──* PromptTemplate (each FK nullable/independent)
Asset *──1 PromptTemplate (prompt_used, nullable)
Asset *──1 CharacterVersion (nullable)
Asset *──1 Episode (nullable)
Asset 1──* LicenseRecord
(any entity) 1──* ApprovalRecord   [polymorphic, no FK]
```

See `docs/10_DATABASE_SCHEMA.md` for the literal table/column/constraint reference, and `docs/11_STORAGE_RULES.md` for what does and doesn't belong in the database versus the filesystem.
