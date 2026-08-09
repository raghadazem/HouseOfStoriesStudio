# 29 — Episode Workspace Status

**Milestone:** 5 — the Episode Workspace (Script, Storyboard, Images, Voice, Music, Video, SEO, Export)
**Builds on:** Milestone 4B's production screens (`docs/25`) — same widget library, same `ApplicationContext`-only architecture, same design tokens (`docs/21`). `SceneService` and `ProductionChecklistService` already existed; this milestone gives them their first real GUI surface.

---

## 1. What Changed

Before this milestone, opening an episode showed a read-only summary dialog (`EpisodesPage._EpisodeDetailDialog`): title, status badges, task progress, and the readiness checklist. There was no scene/storyboard screen anywhere in the app, no GUI control for an episode's own script fields, and no way to move an episode through the pipeline from the GUI.

Opening an episode now opens the full **Episode Workspace** — a dedicated page with 8 tabs, each owning real data and a real completion state:

| Tab | What it edits | Backing service |
|---|---|---|
| **Script** | `Episode.title_ar/title_en/lesson/dialogue_language` (existing fields) + `Script.summary/full_script/notes/status` (new) | `EpisodeService`, new `ScriptService` |
| **Storyboard** | Ordered `Scene` list — add/duplicate/delete/reorder, per-scene fields, cast, prompt, approval | `SceneService` (extended) |
| **Images / Voice / Music / Video** | That `AssetType`'s `Asset` rows linked to the episode, with a real import action | `AssetImportService` (unchanged) |
| **SEO** | `Episode.description_ar/description_en/hashtags/credits_text` (existing fields, first GUI surface) | `EpisodeService` |
| **Export** | Readiness checklist (moved from the old detail dialog) + the new 8-stage summary + Ready-to-Publish/Publish buttons | `ProductionChecklistService`, `EpisodeService` |

## 2. Why Each New Field Is New (and Why Most Aren't)

Every design choice here was checked against the existing schema first, specifically to reuse rather than duplicate:

- **"Narration" / "Visual description" / "Environment" / "Duration" are relabeled existing `Scene` columns** (`dialogue_ar`, `description`, `location`, `estimated_duration_seconds`) — not new columns.
- **Only genuinely new per-scene data got a new column**: `title`, `camera_direction`, `prompt_text`, `negative_prompt_text`.
- **Scene "status" is not a column at all.** `Scene` was already a supported `ApprovalService` entity type (`ENTITY_TYPE_MODELS["scene"]`); status is `ApprovalService.get_current_approval_state(session, "scene", scene.id)` — one source of truth, the same pattern `CharacterVersion`/`Asset` already use.
- **`Script` is a new table**, one row per episode (`episode_id` is a unique FK, enforcing the 1:1), because a script's own lifecycle (draft → ready → approved) doesn't belong on `Episode` itself. It deliberately does **not** duplicate `title_ar`/`title_en`/`lesson`/`dialogue_language` — those stay on `Episode` and are still edited through `EpisodeService.update_episode`.
- **No new "visual style lock" model.** The Prompt Composer's style input reuses `PromptTemplateService.resolve_global_and_contextual_prompts(category=, episode_id=)`, which already resolved global-reusable + episode-contextual `PromptTemplate` rows and had no caller before this milestone.
- **No Asset "version" column.** Versioning today is checksum-based re-import + `approval_status`, which is already extensible; adding a speculative version integer with no consumer isn't part of this milestone's scope.

## 3. Database

One migration, `ab044c62bc0e` (revises `1017c6c7ae38`), entirely additive:

- New table `scripts` — `id`, timestamps, `episode_id` (FK CASCADE, **unique**), `summary`/`full_script`/`notes` (nullable text), `status` (`ScriptStatus`: DRAFT/READY/APPROVED, default DRAFT). `Episode.script` is the reverse `uselist=False` relationship, cascading delete-orphan.
- `Scene` gains 4 nullable columns: `title` (String(256)), `camera_direction`, `prompt_text`, `negative_prompt_text` (all Text).
- Added the missing `Scene.assets` / `Asset.scene` relationship pair — `Asset.scene_id` was a plain FK column with no relationship on either side before this milestone. ORM-only, no schema change.

Verified: `alembic upgrade head` from empty, `alembic upgrade head` against a database with a pre-existing scene row (the 4 new columns backfill `NULL`, no data loss), `alembic downgrade -1` (drops `scripts` and the 4 columns, the pre-existing scene row survives with its original columns intact), re-`upgrade head`, and `alembic check` (no drift).

## 4. Service Layer

- **New `ScriptService`** (`app/core/services/script_service.py`) mirrors `CharacterVersionService`'s lifecycle shape exactly: `get_or_create_script` (a Script always exists once the Script tab has been opened once — no separate "create" action), `update_script` (allowlisted `summary`/`full_script`/`notes`), `submit_script_ready` (DRAFT→READY, no audit record — an unreviewed self-transition, same as `submit_character_version_for_review`), `approve_script`/`reject_script` (READY→APPROVED or back to DRAFT, both recorded via `ApprovalService.approve_entity`/`reject_entity`). `Script` is now an 8th entity type in `ApprovalService.ENTITY_TYPE_MODELS`.
- **`SceneService` extended**: `title`/`camera_direction`/`prompt_text`/`negative_prompt_text` joined `update_scene`'s allowlist; new `set_scene_characters` (the confirmed missing piece — a scene's cast was previously only settable at creation); new `approve_scene`/`reject_scene`/`request_scene_changes` following the same approve/reject-through-`ApprovalService` pattern; new `generate_and_store_prompt` (calls `PromptComposerService`, persists through the same `update_scene` path so there's still exactly one place that mutates a scene row).
- **New `PromptComposerService`** (`app/core/services/prompt_composer_service.py`) — pure string assembly, **no AI provider call, no template rendering**: scene visual description + camera + environment, every character present in the scene (loops over *all* of them — this is text for a human to read/edit, not the single-character constraint an actual generation call has), plus any global/episode-reusable style templates. Negative prompt merges the scene's manually-edited value with every present character's locked negative prompt, de-duplicated. Deliberately a separate service from `PromptEngine` (which always renders a Jinja `PromptTemplate` into a provider-facing `GenerationRequest`) — bolting this onto `PromptEngine` would have blurred what that service's one job is.
- **`ProductionChecklistService` extended**: two new blocking checks in `evaluate()` — `script_ready_for_production` (script exists and is APPROVED) and `all_scenes_approved` (every scene's current approval decision is APPROVED). This is a real behavior change: **Ready-to-Publish now genuinely requires an approved script and approved scenes.** New `evaluate_stage_summary(session, episode_id) -> list[StageStatus]` re-buckets `evaluate()`'s existing `CheckResult`s per workspace stage (see `_CHECK_STAGE` in `production_checklist_service.py`) — it validates nothing new itself, except the small "has this even started" distinction a flat pass/fail list can't express (e.g. zero scenes vs. incomplete scenes) and the per-scene voice-stage reason, which reads exactly `"Scene {order_index} has no narration."`.
- **`ApplicationContext`** gained `script_service` and `prompt_composer_service` cached properties, following the existing pattern.

## 5. GUI

- **New `app/gui/widgets/scene_card.py`** (`SceneCard`, `ElevatedCard`-based). A plain `QFrame` + real buttons, not `EntityRow` — the same reason `ReviewQueuePage` built its own row (`docs/25` §3): a scene needs several independent inline actions at once (▲/▼ reorder, duplicate, delete, expand/collapse, approve/request-changes/reject), and `EntityRow` is documented as read-only-trailing-content only. Collapsed: scene number, title, duration, `StatusBadge` from the scene's approval state, the action buttons. Expanded: narration, visual description, camera, location, duration, a character checkbox list (not a chip-picker — cast size stays small), prompt/negative-prompt text areas, Compose Prompt, Save, and the three approval actions. The widget only edits and emits (`save_requested`, `characters_changed_requested`, `compose_prompt_requested`, etc.) — it never touches `ApplicationContext` itself; `EpisodeWorkspacePage` owns every actual service call, exactly like every other page's dialogs already do.
- **New `app/gui/pages/episode_workspace_page.py`** (`EpisodeWorkspacePage`): `PageHeader` + a "← Episodes" back action → an 8-tab `QTabWidget`. Reorder is ▲/▼ buttons, not drag-and-drop — `SceneService.reorder_scenes` already existed and a full DnD list is materially more risk/complexity for the same functional outcome. The Images/Voice/Music/Video tabs are real, working `EntityRow` lists + import forms today — no generation UI. They are also exactly where a future `AIOrchestrator` workflow's output will land, via the same `Asset` rows and approval flow (see §7).
- **Full page, not a dialog.** Every existing "detail" view in this app is a `FormDialog`; none hosts anywhere near 8 tabs and a full scene editor. The workspace is pushed onto `MainWindow`'s existing `QStackedWidget`, the same mechanism sidebar pages use — but it's the app's first **ad-hoc, parameterized** page (sidebar navigation only ever supported fixed keys before this). `MainWindow.open_episode_workspace(episode_id)` builds the page once and re-targets it (`EpisodeWorkspacePage.set_episode`) on every subsequent open, rather than accumulating one stacked page per episode ever opened.
- **`EpisodesPage`**: `_EpisodeDetailDialog` is removed entirely (fully superseded). A row click now emits `episode_opened(uuid.UUID)`.
- **`DashboardPage`**: `_on_open_episode_001` is rewired from a `show_info` placeholder to `open_episode_requested(uuid.UUID)`.
- Both signals are wired in `MainWindow.__init__` to `open_episode_workspace`.

## 6. Workflow: What "Done" Means Per Stage

`evaluate_stage_summary` reports each stage as one of `StageState.NOT_STARTED / IN_PROGRESS / BLOCKED / READY / COMPLETED`:

- **Script** — not started until `full_script` has content; blocked/ready/completed follow the underlying title/lesson/runtime/script-approval checks.
- **Storyboard** — not started with zero scenes; blocked on an invalid sequence or unapproved scenes; a warning (not blocking) for scenes missing description/dialogue.
- **Images** — not started until a thumbnail asset exists; blocked/completed from thumbnail-exists/approved.
- **Voice** — a specialized check ahead of the generic one: any scene missing narration blocks with `"Scene {N} has no narration."` before falling through to the final-voice-asset-approved check.
- **Music** — automatically `COMPLETED` ("Episode does not include a song.") when `Episode.includes_song` is false; otherwise gated on a final music asset existing and being approved.
- **Video** — not started until either the final video or the three initial Shorts exist.
- **SEO** — not started with no description/hashtag fields set at all; in progress once any are set but incomplete; completed once `export_metadata_complete` passes.
- **Export** — `COMPLETED` once `Episode.pipeline_stage == PUBLISHED`; `READY` once the full checklist has no blocking issues; otherwise `BLOCKED` with the first blocking check's message.

## 7. Future AI Integration Points

No AI provider is called anywhere in this milestone's code. This was deliberately built as the plumbing future generation workflows plug into:

- **Images/Voice/Music/Video tabs** are exactly where an `AIOrchestrator` workflow (OpenAI/Claude/Gemini image generation, ElevenLabs voice, a music provider, Runway-style video) will land its output — through the same `AssetImportService`-adjacent path and the same `Asset` rows/approval flow already wired up, not a new pipeline.
- **`PromptComposerService.compose_scene_prompt`** is the human-editable text a future "Generate Image" button would hand to a real provider call — the composer itself never calls a provider and never will; that's `PromptEngine`'s job once a `GenerationRequest` is actually built from this text.
- **Script tab** — `full_script`/`summary`/`notes` are the natural input to a future AI script-drafting assist; nothing about the `Script` model or its DRAFT→READY→APPROVED lifecycle assumes a human wrote every word.

## 8. Extension Points

- **A 9th workspace stage**: add its `CheckResult`s to `_CHECK_STAGE` in `production_checklist_service.py`, write a `_stage_status_<name>` handler, add it to `_STAGES_IN_ORDER`, and give it a tab in `EpisodeWorkspacePage`. No other stage's logic needs to change — `evaluate_stage_summary` re-buckets, it doesn't cross-reference.
- **Real generation in an asset tab**: the tab's "Import" button becomes "Generate" (or both survive as separate actions) and calls an `AIOrchestrator` workflow instead of `AssetImportService.import_asset` directly — the resulting `Asset` row lands through the exact same list/approval code already there.
- **A new style-lock category**: `PromptComposerService` already resolves `PromptCategory.IMAGE` templates; a new category (e.g. a video-specific style) is a new `PromptCategory` member plus a second `resolve_global_and_contextual_prompts` call in the composer — no new model.

## 9. Tests

- **Unit**: `test_script_service.py` (create/update/status lattice, audit trail on approve/reject), extended `test_scene_service.py` (`set_scene_characters`, approve/reject/request-changes, the new allowlist fields), `test_prompt_composer_service.py` (zero/one/many characters, with/without style templates, negative-prompt de-duplication, missing-active-version characters ignored).
- **Integration**: `test_production_checklist_service.py`'s "fully ready" fixture extended with an approved script + approved scenes (needed to keep `is_ready=True` given the two new blocking checks), plus `evaluate_stage_summary` coverage across an incomplete and a fully-ready episode, including the exact `"Scene N has no narration."` reason text.
- **GUI**: `test_episode_workspace_page.py` (new) — all 8 tabs present; add/duplicate/delete/move a `SceneCard`; expand/collapse; Compose Prompt populates the card's prompt fields; SEO save round-trips through `EpisodeService`; Export tab's Ready/Publish buttons are disabled for a fresh episode; `set_episode` re-targets the page. `test_episodes_page.py`/`test_dashboard.py` updated in place: a row click / "Open Episode" now assert the new `episode_opened`/`open_episode_requested` signals instead of building the removed dialog / showing a placeholder message.

```
$ QT_QPA_PLATFORM=offscreen pytest -q
514 passed

$ ruff check .
All checks passed!
```

## 10. Known Limitations

- The character checkbox list in `SceneCard` has no search/filter — fine at today's cast sizes, would need one if a show's character roster grows large.
- The Images/Voice/Music/Video tabs list assets by `episode_id` + `asset_type` only, with no scene-level association picker in the import form — an asset that should link to a specific scene still needs a separate step. `Asset.scene_id`/`Scene.assets` now exist for exactly this, but no GUI writes `scene_id` yet.
- `evaluate_stage_summary` makes one extra `SceneService.list_episode_scenes` query for the voice stage's per-scene narration check, on top of the query `evaluate()` already made for the storyboard checks — acceptable at today's per-episode scene counts, not memoized.

## 11. Recommended Next Step

Awaiting approval. The natural follow-on is wiring a real `AIOrchestrator` workflow into one of the Images/Voice/Music/Video tabs (§7) now that every non-AI piece — asset storage, approval, prompt composition, readiness gating — is real and tested.
