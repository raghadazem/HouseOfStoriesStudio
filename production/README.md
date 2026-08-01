# Production

This directory holds House of Stories Studio's actual creative/working
content — as opposed to `app/` (application source code) and `docs/`
(project documentation).

| Folder | Purpose |
|---|---|
| `brand/` | Logo, channel art, intro/outro bumpers, shared fonts. |
| `characters/` | One folder per main character (Melissa, Bilsan, ...), each holding approved reference artwork and a `character_meta.yaml` Character Lock record. |
| `world/` | Locations from the World Bible (`docs/03_WORLD_BIBLE.md`) and their reference art. |
| `prompts/` | Reusable prompt fragments not tied to a single episode — character-lock and style-lock blocks, reused across every prompt that involves a given character. |
| `episodes/` | One folder per episode, scaffolded from `app/core/templates/episode/`. |
| `channel/` | Cross-episode / channel-level assets (banner, trailer). |

**Privacy rule:** original personal reference photographs must never be
placed anywhere under `production/`. Only approved, original animated
character artwork belongs here. See `docs/07_DEVELOPMENT_PLAN.md` §23.

**Large binaries** (final renders, raw voice/image/video takes) are not
committed to Git — see the backup strategy in `docs/07_DEVELOPMENT_PLAN.md`
§25. This directory's `.md`/`.yaml` metadata files are tracked; media
files are covered by `.gitignore` rules to keep the repository small.

Content here is created starting in Milestone 5 (seed data); Milestone 1
only establishes this folder structure.
