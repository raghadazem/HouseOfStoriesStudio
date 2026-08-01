# 07 — Development Plan

**Author role:** Technical Director & Lead Software Architect
**Status:** Draft for founder approval — no implementation has started
**Depends on:** `00_PROJECT_OVERVIEW.md`, `01_BRAND_BIBLE.md`, `02_CHARACTER_BIBLE.md`, `03_WORLD_BIBLE.md`, `04_PRODUCTION_PIPELINE.md`, `05_TECHNICAL_ARCHITECTURE.md`, `06_CLAUDE_FIRST_TASK.md`

---

## 1. Executive Summary

House of Stories (بيت الحكايات) is a solo-founder, AI-assisted Arabic children's animation studio whose first product is a YouTube channel starring two original sisters, **Melissa** and **Bilsan**. The existing documentation set is a good *creative* foundation (brand, characters, world, pipeline) but contains almost no *production tooling* — there is no system yet for keeping the characters visually consistent across episodes, no structured way to manage the dozens of AI-generated assets each episode will need, and no software to support the pipeline described in `04_PRODUCTION_PIPELINE.md`.

This plan proposes a **local Windows desktop application**, written in Python, that sits on top of a well-organized **production repository**. The app does not generate art, video, voice, or music itself — no such automation is assumed to be free or reliable today. Instead, it is a **production-management and consistency-enforcement tool**: it scaffolds episodes, stores the character "canon," manages prompts, tracks every asset's origin/version/approval status, and gates an episode from being marked "ready to publish" until everything required is present and approved.

The MVP is scoped tightly: **produce and manage the first three episodes**, running entirely on free/local tools, with zero required paid services. Everything more ambitious (LoRA-trained consistent character generation, YouTube API upload automation, analytics) is explicitly deferred to Version 2 and flagged as optional.

---

## 2. Understanding of the Project

- **Product:** Arabic-language, educational, values-driven children's video series (ages 3–7) for YouTube, under the brand بيت الحكايات, set in وادي الحكايات ("Valley of Stories").
- **Cast:** Two sisters — Melissa (6, older, brave/curious/nature-loving) and Bilsan (4, younger, funny/sweet/singer), with defined but minimal appearance descriptions and a small set of recurring locations.
- **Style:** Original stylized 3D-look animation, warm colors, expressive characters — explicitly **not** a copy of any existing franchise, and explicitly **inspired by**, not a direct render of, real reference photographs.
- **Production model:** A single founder (CS background) using a mix of external AI tools (image/video/voice/music generators) plus manual editing, orchestrated through a documented pipeline: Idea → Lesson → Outline → Script → Storyboard → Image Prompts → Video Prompts → Voice → Song → Editing → Thumbnail → SEO → Publish.
- **Constraint reality check:** No paid API budget is assumed. No tool on the market today can reliably keep a custom character's face/outfit 100% consistent across dozens of independently generated images/videos without either (a) a trained model (LoRA/DreamBooth) or (b) tight human curation. Since (a) requires GPU/time investment not yet committed, the MVP must lean on **(b): rigorous manual curation, reference locking, and metadata tracking**, with the tooling built to make that curation fast rather than to fake full automation.
- **Sequencing note:** `06_CLAUDE_FIRST_TASK.md` asks Claude to build the repo/templates/Asset Manager immediately. The founder's instructions for *this* task explicitly supersede that — this document is the planning deliverable, and no folders, templates, or code beyond this file (and relocating the uploaded docs into `docs/`) have been created. Implementation begins only after this plan is approved.

---

## 3. Repository Architecture

One repository, two clearly separated concerns: **content** (the studio's creative/production data) and **software** (the desktop app that manages it). Mixing these — as a flat `assets/ scripts/ songs/` layout would — makes it hard to grow the app later without content and code colliding, and makes `.gitignore`/backup rules (large binaries vs. tracked source) harder to reason about.

```
house_of_stories_studio/
├── app/            # the Python desktop application (source code)
├── production/     # the studio's actual creative output & working files
├── docs/           # project bibles + this plan + future docs
├── data/           # local SQLite DB + app config (mostly git-ignored)
├── tests/          # automated tests for app/
├── tools/          # small maintenance/dev scripts (backup, packaging)
├── .gitignore
├── pyproject.toml
└── README.md
```

Git tracks `app/`, `docs/`, `tests/`, `tools/`, and the *text* parts of `production/` (scripts, prompts, metadata YAML/JSON). Large binaries (final video renders, raw voice takes, high-res images) are **not** committed to Git by default — see §22 Backup Strategy for how they're protected instead. A tracked `production/**/README.md` per folder documents what belongs there so the exclusion doesn't hide structure.

---

## 4. Complete Proposed Folder Structure

```
house_of_stories_studio/
├── app/
│   ├── core/                       # framework-agnostic business logic (no GUI imports here)
│   │   ├── models/                 # Pydantic data models (episode, character, asset, prompt, scene...)
│   │   ├── services/               # episode_service, character_service, asset_service,
│   │   │                           # prompt_service, storyboard_service, export_service, seo_service
│   │   ├── db/                     # SQLite engine, schema, migrations (via a lightweight migrator)
│   │   ├── templates/              # Jinja2 templates: episode scaffold, prompt sheet, seo sheet
│   │   ├── naming.py                # canonical filename/slug rules (snake_case enforcement)
│   │   ├── rtl_text.py              # Arabic shaping/bidi helpers for previews & exports
│   │   ├── ffmpeg_ops.py            # thin wrapper over ffmpeg for normalize/proxy/mux
│   │   └── ai_provider.py           # pluggable interface; default = "manual/no-AI" no-op provider
│   ├── gui/                        # PySide6 desktop UI (thin layer over core/services)
│   │   ├── windows/                 # Dashboard, Episode, Character Library, Asset Importer, Prompt Manager
│   │   ├── widgets/
│   │   └── resources/               # qss stylesheet, icons, RTL-aware fonts
│   ├── cli/                        # optional command-line entry points using the same core services
│   └── main.py
├── docs/
│   ├── 00_PROJECT_OVERVIEW.md ... 06_CLAUDE_FIRST_TASK.md   (existing, untouched)
│   ├── 07_DEVELOPMENT_PLAN.md       (this file)
│   └── (future docs — see §26 Missing Documents)
├── production/
│   ├── brand/                      # logo, channel art, intro/outro bumpers, fonts, color palette file
│   ├── characters/
│   │   ├── melissa/
│   │   │   ├── character_meta.yaml
│   │   │   ├── reference/           # APPROVED canon images only (model sheet, turnarounds)
│   │   │   └── versions/v01, v02...  # historical/candidate designs, each with its own meta
│   │   └── bilsan/  (same shape)
│   ├── world/
│   │   ├── world_bible.yaml         # locations, rules — structured mirror of 03_WORLD_BIBLE.md
│   │   └── locations/<location_slug>/reference/
│   ├── prompts/                    # REUSABLE prompt fragments not tied to one episode
│   │   ├── character_lock/melissa_prompt_block.md, bilsan_prompt_block.md
│   │   └── style_lock/visual_style_block.md
│   ├── episodes/
│   │   └── ep01_<slug>/
│   │       ├── 00_meta.yaml          # id, title_ar/en, lesson, status, pipeline stage, dates
│   │       ├── 01_script.md
│   │       ├── 02_storyboard.md
│   │       ├── 03_image_prompts.md
│   │       ├── 04_video_prompts.md
│   │       ├── 05_voice.md
│   │       ├── 06_song.md
│   │       ├── 07_seo.md
│   │       ├── images/               # raw + approved, versioned via filename suffix
│   │       ├── videos/
│   │       ├── audio/voice/, audio/music/
│   │       ├── thumbnails/
│   │       └── exports/              # final render(s) ready for upload
│   └── channel/                    # cross-episode SEO/channel-level assets (banner, trailer)
├── data/
│   ├── studio.db                    # SQLite (git-ignored)
│   └── config.local.yaml            # local machine config incl. any optional API keys (git-ignored)
├── tests/
│   ├── unit/  integration/
├── tools/
│   ├── backup.py
│   └── new_episode.py               # thin CLI wrapper, mirrors GUI "New Episode"
├── .gitignore
├── pyproject.toml
└── README.md
```

Filename rule (applies everywhere): **English, lowercase, `snake_case`, versioned with a two-digit suffix**, e.g. `melissa_face_ref_v01.png`, `episode_01_thumbnail_v02.jpg`, `ep01_scene03_voice_melissa_take02.wav`. Arabic text lives *inside* files (scripts, metadata `title_ar` fields, SEO text) — never in filenames, to avoid encoding/RTL issues in tools, zips, and cross-platform paths.

---

## 5. Recommended Technology Stack and Justification

| Layer | Choice | Why |
|---|---|---|
| Language | **Python 3.11+** | Founder's preferred/known stack; best ecosystem for image/audio/video scripting (Pillow, pydub, ffmpeg wrappers); trivial to script one-off production tasks alongside the app. |
| Desktop GUI | **PySide6 (Qt)** | Native-feeling Windows app, free (LGPL), excellent built-in RTL/Arabic text + bidi rendering support, mature widget set, packages to a Windows `.exe` via PyInstaller. Chosen over Tkinter (too primitive for asset galleries/RTL forms) and over an Electron/web-based app (would require a JS stack, against "avoid unnecessary complexity" and the Python preference). |
| Local database | **SQLite** via `sqlalchemy` (or raw `sqlite3` if the ORM proves unnecessary) | Zero-install, zero-cost, single-file, perfectly suited to a single-user desktop tool; trivial to back up (copy the file). |
| Data validation | **Pydantic** | Typed data models shared between GUI, CLI, and DB layer; catches malformed metadata early. |
| Templating | **Jinja2** | Episode/prompt/SEO scaffolding from templates without hand-rolled string formatting. |
| Text/metadata format | **Markdown + YAML frontmatter** for human-edited creative docs; **YAML/JSON** for pure metadata | Git-diff-friendly, human-editable without the app, matches the existing docs' style. |
| Arabic RTL handling | **`python-bidi` + `arabic-reshaper`** for any custom-drawn text (thumbnail compositing, image overlays); Qt's native RTL layout for UI/forms | Qt handles RTL UI natively; Pillow does not shape Arabic text, so the reshaper/bidi pair is needed specifically for programmatic image text (e.g., thumbnail titles). |
| Media processing | **ffmpeg** (via subprocess) + `Pillow` | Free, industry-standard, handles export specs, loudness normalization, proxies, thumbnail resizing — no paid render tools needed. |
| Packaging | **PyInstaller** | One-command Windows executable for a non-technical daily workflow, even though the founder is technical — reduces friction to just opening the app. |
| Testing | **pytest** (+ `pytest-qt` later for GUI smoke tests) | Standard, low-overhead. |
| Version control | **Git** (existing GitHub repo) | Already in use; tracks code + text content, not large binaries (see §22). |
| Optional AI text assistance | Pluggable `ai_provider.py` interface; default implementation is a **no-op / manual mode** | Keeps the app 100% functional with zero API keys and zero cost. If the founder later wants LLM-assisted drafting (scripts, prompts, SEO copy), any provider (Claude, a local Ollama model, etc.) can be dropped in behind the same interface — never a hard dependency. |

**Why not a web app / SaaS architecture:** single user, single Windows machine, no need for multi-user auth, hosting, or a server — that would be scale-optimizing for a scale that doesn't exist yet, directly against the brief. A desktop app with a local DB is simpler to build, debug, back up, and run offline.

---

## 6. Desktop Application Architecture

**Principle: strict separation between `core` (business logic) and `gui` (presentation).** The GUI calls into `core.services`; it never touches the database or filesystem directly. This buys three things immediately relevant to a solo, evolving project:

1. **Testability** — services are tested with plain pytest, no GUI harness required.
2. **A free CLI** — `app/cli` re-uses the same services, so scripts like "scaffold episode 4" or "run a backup" work without opening the GUI.
3. **Future-proofing without over-building now** — if the app ever needs a different front end (or none), only `gui/` changes.

```
 ┌─────────────┐        ┌──────────────┐        ┌────────────┐
 │   gui/      │  calls │   services   │  uses  │   db/       │
 │ (PySide6)   │ ─────▶ │ (core logic) │ ─────▶ │ (SQLite)    │
 └─────────────┘        └──────────────┘        └────────────┘
        ▲                        │
        │                        ▼
   user actions            core/models (Pydantic)
                            + filesystem (production/)
```

**MVP screens (kept deliberately few):**
1. **Dashboard** — episode list with pipeline-stage status (per §14).
2. **Episode View** — the episode's checklist, linked prompts/assets, stage advance/rollback.
3. **Character Library** — canon reference gallery per character, version history, approve/reject.
4. **Asset Importer** — drag-and-drop or "watch downloads folder"; tags file to episode/character/type/prompt, generates the versioned filename, moves it into `production/`.
5. **Prompt Manager** — create/browse/reuse prompt entries, filter by character/episode/tool.

No user accounts, no network server, no multi-window complexity beyond this.

---

## 7. Main Modules and Responsibilities

| Module | Responsibility |
|---|---|
| `episode_service` | Create/scaffold episodes from template; track pipeline stage; validate "ready to publish" gate. |
| `character_service` | Manage canonical character records, reference asset sets, version history, approval workflow. |
| `asset_service` | Register imported files (image/video/voice/music/thumbnail), compute checksum, enforce naming, link to episode/character/prompt, track approval status and source-tool license. |
| `prompt_service` | CRUD for prompt entries; compose prompts by merging reusable "character lock" / "style lock" blocks with scene-specific text. |
| `storyboard_service` | Parse/generate `storyboard.md` shot tables; build a contact-sheet image from imported storyboard frames. |
| `seo_service` | Generate/store title, description, tags, thumbnail link per episode; validate Arabic text encoding/RTL. |
| `export_service` | Wrap ffmpeg for normalization (e.g., -16 LUFS), proxy generation, and final-spec validation (resolution/codec/aspect) before publish. |
| `naming` | Single source of truth for the snake_case + version-suffix filename convention; every other module calls into it rather than re-implementing string rules. |
| `ai_provider` | Optional pluggable text-AI hook (drafting help); default no-op. |
| `backup` (tools/) | Local + external-drive backup routine (see §22). |

---

## 8. Data Models

Represented as Pydantic models, persisted to SQLite; each also has a canonical on-disk YAML mirror for the fields that matter to Git/human review.

- **Character**: `id, name_ar, name_en, age, role, traits[], canon_appearance_summary, created_at`
- **CharacterVersion**: `id, character_id, version_number, description_of_change, reference_asset_ids[], status(draft/in_review/approved_canon/archived), decided_at, decided_by`
- **Location**: `id, name_ar, name_en, description, reference_asset_ids[]`
- **Episode**: `id, number, season, title_ar, title_en, lesson_value, logline, status, pipeline_stage, created_at, published_at, youtube_url, folder_path`
- **Scene**: `id, episode_id, order, description, dialogue_ar, characters_present[], location_id, prompt_ids[], asset_ids[]`
- **Prompt**: `id, type(image/video/voice/music/text), text_en, related_episode_id, related_scene_id, related_character_ids[], target_tool, version, resulting_asset_ids[]`
- **Asset**: `id, type(image/video/voice/music/thumbnail/document), file_path, checksum, episode_id(nullable), character_id(nullable), prompt_id(nullable), version, status(draft/approved/rejected), source_tool, source_license_note, created_at`
- **VoiceProfile**: `character_id, tool_used, voice_setting_notes, sample_asset_id`
- **SeoRecord**: `episode_id, title_ar, description_ar, tags[], thumbnail_asset_id`

---

## 9. Metadata Formats

- **Episode metadata** (`00_meta.yaml`): human-editable YAML — id, titles, lesson, pipeline stage, dates.
- **Character metadata** (`character_meta.yaml`): canon traits + pointers to current approved reference set.
- **Asset sidecar**: rather than one JSON file per asset (noisy at scale), asset metadata lives primarily in `studio.db`, with a periodic **export** to a flat `production/**/asset_manifest.yaml` per folder — human-readable, diffable, and a disaster-recovery fallback if the DB is ever lost (see §22).
- **Prompts**: stored in DB, exported to the relevant episode's `03_image_prompts.md` / `04_video_prompts.md` as readable Markdown so they're usable even outside the app.
- **Naming convention recap**: `english_lowercase_snake_case`, versioned as `_v01`, `_v02`, dated where relevant as `yyyymmdd`.

---

## 10. AI Integration Strategy

Two distinct categories, treated very differently:

1. **Generative media (image/video/voice/music)** — **not integrated via API in the MVP.** These are produced by the founder manually in external tools of their choosing (see §12) and *imported* into the system. The app's job is to make that import fast, well-tagged, and consistency-checked — not to call generation APIs, which are typically paid, rate-limited, and not guaranteed to preserve character likeness.
2. **Text assistance (brainstorming, script drafting, prompt phrasing, SEO copy)** — supported through the optional `ai_provider` interface. Default is a no-op "manual" provider (pure templates, no network calls, zero cost). If the founder chooses to enable an LLM (their own Claude/OpenAI/local Ollama key), it plugs into the same interface without touching the rest of the app. **Never required, never assumed.**

This keeps the "no paid APIs assumed" constraint absolute while leaving a clean door open for later.

---

## 11. Free-Tool-First Production Strategy

The app is deliberately agnostic about *which* external generator is used, since free tiers/tools change fast. Examples the pipeline is designed to accommodate (not endorsements, not commitments — founder should verify current ToS/commercial-use terms before relying on any of them):

- **Images:** Bing Image Creator, Leonardo.Ai (free tier), local Stable Diffusion via ComfyUI/Automatic1111 (fully free if the founder has a capable GPU).
- **Video:** free tiers of tools like Pika/Runway/Kling, or manual animation from generated stills.
- **Voice:** ElevenLabs (free tier, limited quota), or fully free/local options like Piper TTS / Coqui TTS for zero recurring cost at higher volume.
- **Music:** Suno (free tier), or royalty-free libraries (YouTube Audio Library, freesound.org with license tracking).
- **Editing:** DaVinci Resolve (free), Shotcut, CapCut.

Every asset's `source_tool` and licensing note is captured in metadata specifically so that, months later, the founder can answer "am I allowed to monetize this" per-asset rather than guessing.

---

## 12. Asset Management System

- Single entry point: **Import Asset** (GUI drag-drop, or a watched folder) → founder tags type, episode/character link, source tool, prompt used → system computes checksum, renames per convention, moves into `production/`, writes DB row.
- Every asset carries a **status**: `draft → in_review → approved → (archived/rejected)`. Only `approved` assets may be referenced by an episode marked ready-to-publish.
- Duplicate detection via checksum to avoid reimporting the same file under two names.
- A per-episode **asset checklist view** shows what's still missing against the episode template (e.g., "3 of 5 scenes have approved images").

---

## 13. Character Consistency System

This is the highest-risk, highest-value part of the system, so it gets explicit process, not just a folder:

1. **Canon reference set** per character: a small, locked set of "model sheet" images (front/side/back, key expressions, outfit close-up) that every future prompt and every future review checks against. Stored in `production/characters/<name>/reference/`, and never overwritten in place — only replaced via a new approved **CharacterVersion**.
2. **Prompt lock blocks**: a reusable text fragment (`production/prompts/character_lock/melissa_prompt_block.md`) capturing Melissa's fixed visual traits, meant to be pasted into every image/video prompt involving her — the single biggest lever for consistency without a trained model.
3. **Manual review gate**: newly generated candidate images/videos are imported as `draft`, displayed next to the canon reference in the Character Library / Asset Importer, and require explicit human approval before being usable in an episode.
4. **Traceability**: every approved asset records which CharacterVersion was canon at the time, so if the design evolves in episode 10, episodes 1–9 remain internally consistent and explainable rather than silently mismatched.
5. **v2 aspiration (not MVP):** training a small local LoRA on the approved reference set for materially better automatic consistency — flagged in §29 Version 2 Scope, not committed to now since it requires GPU time and validation the founder hasn't signed up for yet.

---

## 14. Versioning Strategy for Characters and Assets

- **Characters**: incrementing `vNN` per approved design revision; `reference/` always mirrors the *current* approved version; superseded versions move to `versions/vNN/` for history, never deleted.
- **Assets**: `_vNN` suffix per regeneration attempt for the same prompt/shot (e.g., `ep01_scene02_melissa_v01.png`, `_v02.png`); only one version per shot is ever `approved` at a time, others remain `draft`/`rejected` for audit trail.
- **Episodes**: no version suffix needed pre-publish; once published, any post-publish fix creates a dated re-export (`_reupload_yyyymmdd`) rather than overwriting the original export.

---

## 15. Episode Production Workflow

Maps directly onto `04_PRODUCTION_PIPELINE.md`, with the app tracking a `pipeline_stage` enum per episode and gating advancement:

`idea → lesson → outline → script → storyboard → image_prompts → video_prompts → voice → song → editing → thumbnail → seo → ready_to_publish → published`

Each stage transition in the Episode View shows what's required to move forward (e.g., cannot leave `image_prompts` until every scene has at least one linked prompt; cannot reach `ready_to_publish` until every scene has an `approved` image/video asset and `07_seo.md` is filled in). This is a soft gate (founder can override) — the point is visibility, not bureaucracy.

---

## 16. Episode Folder Template

```
episodes/epNN_<slug>/
├── 00_meta.yaml            # id, titles, lesson, pipeline_stage, dates
├── 01_script.md            # Arabic dialogue/narration, RTL-correct
├── 02_storyboard.md        # shot table: #, scene, description, characters, dialogue, camera note
├── 03_image_prompts.md     # per-shot prompts (English), each referencing character lock blocks
├── 04_video_prompts.md
├── 05_voice.md             # per-line voice direction + tool/settings used
├── 06_song.md               # theme/lyrics/mood notes if the episode has an original song
├── 07_seo.md                # title_ar, description_ar, tags, thumbnail reference
├── images/
├── videos/
├── audio/voice/, audio/music/
├── thumbnails/
└── exports/                 # final render(s), publish-ready
```

(Numbered filenames added vs. the original proposal in `05_TECHNICAL_ARCHITECTURE.md` purely so the pipeline order is visible directly in a file listing.)

---

## 17. Prompt Management System

- Prompts are written in **English** (current generators perform best that way) but always reference the **Arabic** creative content (scene, dialogue) they're illustrating — the Prompt entry stores both `related_scene_id` (Arabic dialogue lives there) and `text_en` (the actual generation prompt).
- Every character-involving prompt is composed by concatenating: `style_lock` block + relevant `character_lock` block(s) + scene-specific description — enforced by `prompt_service`, not left to manual copy-paste discipline alone.
- Prompts are versioned (`v01`, `v02`...) so the founder can see which exact prompt text produced which approved asset — critical for reproducing a "look" later.
- Reusable, non-episode-specific prompt fragments (character lock, style lock, location lock) live in `production/prompts/`; episode-specific prompts live in and export to that episode's `03_image_prompts.md` / `04_video_prompts.md`.

---

## 18. Storyboard Management

- `02_storyboard.md` is a Markdown shot table (shot #, scene, visual description, characters present, dialogue excerpt, camera/framing note, estimated duration).
- The Storyboard Manager screen (or, in MVP, just structured Markdown + a "contact sheet" generator) lets the founder import rough storyboard frame images and view them as a single composited grid image via Pillow — cheap, useful, and doesn't require building a drawing tool.
- Storyboard shots link forward to image/video prompts and assets, so the shot list is the backbone that ties script → prompts → final footage together.

---

## 19. Voice and Music Asset Management

- **Voice**: one `VoiceProfile` per character records which tool/model/settings were used, so the same "voice" can be reproduced episode to episode. Raw takes are imported, and `export_service` runs an ffmpeg loudness-normalization pass (target ~-16 LUFS, YouTube's approximate norm) into a `_normalized` file before it's usable in editing.
- **Music**: each track records mood tags and a **license note** (critical for monetization safety — see §24). Original/royalty-free preferred; nothing is imported without a recorded source and license.
- Both link to episodes via the same `asset_service` used for images/video — no separate subsystem needed.

---

## 20. Export Workflow for YouTube

1. Final cut assembled externally (DaVinci Resolve/Shotcut/CapCut) using approved assets only.
2. Exported per spec: **1920×1080 minimum (16:9), H.264 MP4, AAC audio**; app's `export_service` validates the file against this spec before allowing the "ready_to_publish" gate to close.
3. Thumbnail spec validated: **1280×720, JPEG/PNG, under 2 MB**.
4. `07_seo.md` reviewed: Arabic title/description render correctly RTL (validated via `rtl_text.py` in a preview), tags populated.
5. Captions (`.srt`) — **recommended, not required, for MVP**; noted as a strong v1 addition for accessibility/reach (see §27).
6. **Upload itself is manual** in the MVP (YouTube Studio) — see §21 for why this isn't automated yet.

---

## 21. Automation Opportunities

Realistic, in priority order:
- Episode folder + template scaffolding from a single "New Episode" action.
- Prompt composition (character/style lock merging) — removes manual copy-paste error.
- Asset import: checksum, rename, file, and DB-register in one step; optional "watch Downloads folder" convenience.
- ffmpeg-based loudness normalization, proxy generation, and export-spec validation.
- Thumbnail compositing (place character cutouts + Arabic title text onto a template) via Pillow + `rtl_text.py`.
- SEO draft generation from episode metadata (template-based; LLM-assisted only if the optional AI provider is enabled).
- "Ready to publish" checklist gate (prevents forgetting a step, not a creative automation).
- Scheduled local backup (see §22).

---

## 22. Manual Steps That Cannot Currently Be Automated

- Actual image/video generation in external tools (no reliable free, high-fidelity, character-consistent API exists to call automatically).
- Voice performance/AI voice generation execution — done in the external tool's own UI.
- Song composition/generation.
- All creative review: is this on-model, is this age-appropriate, does this teach the intended lesson.
- Final video editing/assembly (no free reliable programmatic editor for creative cuts).
- YouTube upload (deliberately manual in MVP — automating requires Google OAuth setup, API quota management, and carries real risk of a bad automated upload; revisit only once the manual workflow is proven, per §29 Version 2).

---

## 23. Security and Privacy Considerations

- No user accounts, no server, no data leaves the founder's machine in the MVP — smallest possible attack surface.
- If an optional AI API key is ever configured, it's stored in `data/config.local.yaml` (git-ignored) or the OS credential store (`keyring`), **never** committed, **never** hard-coded.
- **Reference photographs**: the character bible states designs are "inspired by reference photographs" of presumably real people. These source photos are personal/potentially sensitive data. Recommendation: keep raw reference photos in a folder that is **git-ignored and excluded from any public repo/backup sharing**, and only the *derived, stylized* character art should ever be considered for a public repository. This needs an explicit decision from the founder (see §31 Open Questions).
- If the GitHub repo is or becomes public, do a pass before each push to ensure no reference photos, no personal data, and no API keys are included (`.gitignore` covers this by default, but manual vigilance still matters).

---

## 24. Copyright and Licensing Considerations

- **Character originality risk**: AI image/video generators can unintentionally drift toward existing IP "style." Recommend a lightweight review checklist step before approving any character reference asset: does this resemble a known existing children's character too closely? (Visual review only — not a legal opinion; consult a professional before commercial launch if in doubt.)
- **Per-asset license tracking**: every imported asset records its `source_tool` and any known commercial-use terms, because YouTube monetization eligibility depends on the founder actually holding usable rights to every element in the video (art, voice, music).
- **Music**: strongly prefer original/AI-generated/explicitly royalty-free tracks with the license recorded; never import an untracked/unknown-license track.
- **Reference photos of real people**: separate from copyright, this is a personal-rights/consent question — see §23.

---

## 25. Backup Strategy

Scaled for a solo creator, not enterprise infra:
- **Text/metadata** (scripts, prompts, YAML, app source): Git is the backup — already replicated to GitHub.
- **Large binaries** (final renders, raw voice/image/video assets): **not** committed to Git (repo bloat, GitHub size limits). Instead: a local working copy on the studio PC + a scheduled copy to an external drive or a free-tier cloud-sync folder (OneDrive/Google Drive free tier) for at least the `approved` canon and published-episode exports.
- A simple `tools/backup.py` script (v1, not MVP-blocking) automates "copy everything marked approved + all exports to the backup destination," runnable on demand or via Windows Task Scheduler.
- The `asset_manifest.yaml` export (§9) is itself a disaster-recovery aid: even if `studio.db` is lost, the manifest lets the founder reconstruct what each file is.

---

## 26. Testing Strategy

- `pytest` unit tests for `core/services` and `core/models` — the business logic that must stay correct (naming rules, pipeline-stage gating, checksum/dedup logic).
- Integration tests for the import pipeline using temp directories and fixture files.
- GUI: manual QA in MVP; `pytest-qt` smoke tests introduced in v1 once the screen set stabilizes (not worth the overhead while screens are still being designed).
- A standing **manual QA checklist** for creative/consistency review (character on-model check, content-appropriateness check) — this is inherently human judgment, not something to pretend to automate.

---

## 27. Error Handling and Logging Strategy

- Python `logging` module, one rotating log file per run under `data/logs/`.
- Service-layer functions raise typed exceptions (e.g., `DuplicateAssetError`, `InvalidPipelineTransition`) caught at the GUI/CLI boundary and shown as clear messages — the founder is technical, so messages can be specific rather than dumbed down, but should always say *what to do next*.
- File operations (import/move) are checksum-verified and atomic where possible (copy-then-verify-then-remove-source) so an interrupted import can't silently corrupt or lose an asset.
- Startup validation: on launch, the app checks that `production/` folder structure and `studio.db` are consistent, and surfaces (not silently fixes) any drift.

---

## 28. Missing Documents

The current doc set is a strong creative skeleton but is missing several things a production system needs as inputs:

1. **Video technical spec** — target resolution/frame rate/episode length (this plan assumes ~1080p/16:9, but episode *length* target isn't defined anywhere and materially affects pipeline effort).
2. **Character model sheet / visual reference images** — the Character Bible is text-only; there are no reference photos or approved art in the repo yet for the app to manage.
3. **Arabic dialect decision** — Modern Standard Arabic vs. a specific spoken dialect (Khaleeji, Egyptian, Levantine, etc.) for narration/dialogue; affects voice tool choice and audience reach.
4. **Content/safety guidelines beyond "no violence"** — e.g., screen-time pacing, sound/flash limits for young children, guidance on scary content, diversity/representation guidelines.
5. **Channel & publishing strategy** — upload cadence, season/episode numbering scheme, monetization plan, YouTube Kids/COPPA-equivalent compliance stance.
6. **AI tool shortlist** — which specific tools the founder actually plans to use per pipeline stage (affects prompt formatting and licensing tracking).
7. **Budget/time constraints** — even "free-tool-first," some tools have paid tiers with meaningfully better output; knowing the ceiling helps prioritize.
8. **Legal/business basics** — business entity status, trademark check on "House of Stories"/"بيت الحكايات" name and character names, any collaborator agreements.
9. **Music/song style guide** — genre, instrumentation, whether songs are per-episode-original or from a recurring theme library.

These are listed as gaps, not blockers — the MVP can proceed using reasonable defaults noted throughout this plan, but items 1–3 in particular should be confirmed early since they affect the data model and export spec.

---

## 29. Open Questions

1. Should the founder's own reference photographs (source inspiration for Melissa/Bilsan) be stored inside this repository at all, even privately? (Recommendation: keep them outside the Git repo, in a local-only folder the app can point to — see §23.)
2. Target episode length and upload cadence?
3. Preferred Arabic dialect for dialogue/voice?
4. Is there a GPU available locally for any future local Stable Diffusion / voice / LoRA workflow, or is the founder tool-shopping entirely browser-based free tiers?
5. Any existing draft scripts, storyboards, or reference art not yet included in the uploaded doc set?
6. Should `production/` (working files) live in the *same* Git repo as `app/` (source code) long-term, or should content eventually move to a separate storage location as it grows large? (This plan assumes same-repo-for-now, split-later-if-needed.)

---

## 30. Technical Risks

- **Character consistency drift** across independently generated assets is the single biggest technical risk to output quality — mitigated by the reference-lock + approval-gate system in §13, but not eliminated without a trained model.
- **Metadata/DB and filesystem falling out of sync** (files moved/renamed outside the app) — mitigated by checksum validation and the manifest export, but any manual filesystem edits outside the app are a known risk vector.
- **ffmpeg/tooling availability on the founder's Windows machine** — needs to be bundled or clearly documented as a prerequisite install.
- **Scope creep in the GUI** — easy for a "production management tool" to balloon into a full DAM/NLE; the modular `core`/`gui` split and the MVP screen cap (§6) are the guardrails.

## 31. Production Risks

- **Manual bottleneck**: with no reliable automated generation, output volume is gated entirely by founder time — the tooling should optimize for *review/import speed*, not pretend to remove this bottleneck.
- **Free-tier tool instability**: free tiers of external AI tools change quotas/availability often; the tool-agnostic import design (§11) is specifically meant to absorb this churn.
- **Consistency fatigue**: reviewing every asset against canon is tedious at volume; if this becomes a real bottleneck post-MVP, it's the strongest justification for the v2 LoRA investment (§29 v2 scope).
- **IP/likeness risk** if generated art drifts toward existing franchises or too closely resembles the real reference photos of identifiable people (see §23–24).

---

## 32. Suggested Improvements (to the existing docs/creative foundation)

- Add a one-page **visual style guide** (palette swatches, line-weight/rendering notes) to `01_BRAND_BIBLE.md` or as a new doc — "warm colors, expressive characters" is a good start but not yet enough to brief an image generator consistently.
- Expand `02_CHARACTER_BIBLE.md` with a couple more locked details per character (eye color, skin tone, height relative to each other, teddy bear's name/appearance) — small gaps like this are exactly where AI generators improvise inconsistently between sessions.
- Add explicit **episode numbering/season structure** to `04_PRODUCTION_PIPELINE.md` or a new doc, since the app needs a stable identifier scheme from episode 1.
- Consider a short **"do not" list** for content (beyond "no violence") to make the review-gate checklist concrete rather than left to judgment call each time.

---

## 33. MVP Scope

**Goal: produce and manage the first three episodes, end to end, on free tools only.**

Included:
- Repo structure per §4 (created on approval).
- Core data models + SQLite persistence for Character, CharacterVersion, Episode, Scene, Prompt, Asset.
- "New Episode" scaffolding (folder + template files) for episodes 1–3.
- Character Library screen: canon reference storage + approval workflow for Melissa and Bilsan.
- Asset Importer: manual import with tagging, checksum, snake_case renaming, versioning.
- Prompt Manager: create/store/compose prompts with character/style lock blocks.
- Pipeline-stage tracking per episode (idea → ... → published) with a soft "ready to publish" checklist.
- Basic SEO record per episode (title/description/tags, Arabic-RTL-validated).
- ffmpeg-backed export spec validation + loudness normalization.
- Local backup script (manual run).
- Core unit tests for naming, pipeline gating, and asset dedup logic.

Explicitly excluded from MVP:
- Any generative AI API integration (image/video/voice/music/text) — manual import only, optional no-op AI hook present but unused by default.
- YouTube upload automation.
- Storyboard contact-sheet auto-compositing, thumbnail auto-compositing (nice-to-have, pushed to v1).
- Captions/subtitle workflow.
- Multi-user/collaboration anything.
- LoRA/trained-model consistency system.

---

## 34. Version 1 Scope

- Thumbnail compositing tool (template + character cutout + Arabic title, RTL-correct).
- Storyboard contact-sheet generator.
- SEO copy drafting assist (template-based; LLM-assisted if founder enables the optional AI provider).
- Captions/`.srt` workflow support.
- Automated local backup scheduling (Task Scheduler integration).
- Drag-and-drop + "watch folder" import convenience in the Asset Importer.
- Expanded episode/season numbering support for a growing catalog (beyond the first 3).
- `pytest-qt` GUI smoke tests once screens stabilize.

## 35. Version 2 Scope

- Optional local LoRA/fine-tuned model trained on the approved character reference set, for meaningfully better generation consistency (still manual import — the model produces candidates, humans still approve).
- YouTube Data API upload automation (explicit OAuth consent flow), with manual fallback retained.
- Basic analytics ingestion (view counts, retention) linked back to episode records.
- Multi-language/subtitle export automation if the channel expands beyond Arabic.
- Reconsidering repo split (content vs. app) if `production/` binary volume becomes unwieldy for the backup strategy in §25.

---

## 36. Prioritized Implementation Roadmap

1. Repo scaffolding (`app/`, `production/`, `data/`, `tests/`, `.gitignore`, `pyproject.toml`) — no creative content changes.
2. Core data models + SQLite schema + migrations.
3. `episode_service` + "New Episode" scaffolding, exercised via CLI first (fastest path to something usable, no GUI dependency yet).
4. `character_service` + populate Melissa/Bilsan canon records from `02_CHARACTER_BIBLE.md` (text fields only — reference images added once the founder supplies/generates them).
5. `asset_service` (import, checksum, naming, versioning, approval workflow).
6. `prompt_service` (character/style lock composition).
7. Minimal PySide6 GUI: Dashboard + Episode View wired to the above.
8. Character Library and Asset Importer GUI screens.
9. `export_service` (ffmpeg spec validation + normalization) + Prompt Manager GUI screen.
10. SEO record + pipeline-stage gating end-to-end.
11. Backup script + core unit test suite hardening.
12. Dry run: scaffold and fully manage episode 1 through the real pipeline using the app, fixing friction found along the way.
13. Repeat for episodes 2–3 → MVP acceptance review (§37).

---

## 37. Acceptance Criteria for the MVP

- [ ] App launches on Windows with no paid service, no internet-required account, and no manual dependency beyond a documented one-time setup (Python/ffmpeg/PyInstaller build).
- [ ] Three episode folders can be scaffolded from the template and are visible/manageable in the Dashboard.
- [ ] Melissa and Bilsan each have a Character Library entry with a canon reference set and a working approve/reject workflow for new candidate assets.
- [ ] At least one full prompt → import → approve → link-to-scene flow works end to end for both an image asset and a voice asset.
- [ ] Each of the 3 MVP episodes can be advanced through every pipeline stage in the app, and the "ready to publish" checklist correctly blocks/unblocks based on real asset approval state.
- [ ] SEO record renders Arabic title/description correctly RTL in the app's preview.
- [ ] Final export for at least one episode passes the automated spec validation (resolution/codec/aspect, loudness-normalized audio).
- [ ] All generated filenames conform to the English snake_case + version-suffix convention with zero manual renaming needed.
- [ ] Data persists correctly across app restarts (DB + filesystem stay in sync).
- [ ] Core service-layer unit tests pass in CI or locally via `pytest`.
- [ ] A local backup run successfully copies all `approved` assets + exports for the 3 episodes to a secondary location.

---

*End of Development Plan. No implementation, folder creation beyond `docs/`, or dependency installation has occurred. Awaiting founder approval before proceeding.*
