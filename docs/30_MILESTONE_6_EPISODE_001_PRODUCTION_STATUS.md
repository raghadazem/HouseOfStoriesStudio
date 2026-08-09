# 30 — Milestone 6 Status: Real Episode 001 Production

**Milestone:** 6 — produce Episode 001 end-to-end as a real production package using the existing studio system, and prove the system honestly reports what is and isn't actually ready.
**Builds on:** Milestone 5's Episode Workspace (`docs/29`) — every field populated here is edited through the exact same tabs, no parallel workflow.

---

## 0. What This Milestone Is and Isn't

This is **real authored content**, not placeholder text: a full Arabic script, a 15-scene storyboard, an original song, three Shorts, and a YouTube SEO package for **ميليسا وبيلسان والسلحفاة الصغيرة الضائعة** (*Melissa and Bilsan and the Lost Little Turtle*).

It is deliberately **not** a finished, publishable episode. Nothing here calls a paid AI API, nothing approves a script/scene, and no `CharacterVersion` is marked `approved_canon`. The whole point of this milestone is that `ProductionChecklistService` reports the *true* state — mostly blocked, with exact reasons — rather than a green dashboard that doesn't reflect real production readiness. See §6.

## 1. Episode Structure

| | |
|---|---|
| Arabic title | ميليسا وبيلسان والسلحفاة الصغيرة الضائعة |
| English title | Melissa and Bilsan and the Lost Little Turtle |
| Lesson | Helping others |
| Language | Simple White Arabic (`dialogue_language`) |
| Runtime target | 8–10 minutes |
| Scenes | 15, summing to 535s (8:55) — inside the target range |
| Song | Yes — "معاً نستطيع" (Together We Can), ~60s |
| Characters | Melissa (older sister), Bilsan (younger sister) — both from `docs/02_CHARACTER_BIBLE.md` — plus **Tortor** (طُرطُر), a new supporting character: a small lost turtle, original design, no existing IP |

The episode already existed as `app.core.db.seed`'s demo data (`EPISODE_001_SLUG = "ep001_lost_little_turtle"`) with these exact title/lesson/runtime values from the founder's Milestone 2 approval — this milestone is what turns that skeleton into a real production package, not a new episode.

### Scene list (12-beat structure → 15 production scenes)

| # | Beat | Title (AR) | Location | Duration |
|---|---|---|---|---|
| 1 | Hook | صوت غريب عند البحيرة | Butterfly Lake | 25s |
| 2 | Introduction | صباح الأختين | Cottage Garden | 30s |
| 3 | Discovery | اكتشاف السلحفاة الصغيرة | Butterfly Lake | 40s |
| 4 | Decision to help | قرار المساعدة | Butterfly Lake | 30s |
| 5 | Search (1) | سؤال الغابة | The Forest | 45s |
| 6 | Search (2) | عبور جسر قوس قزح | Rainbow Bridge | 45s |
| 7 | Funny moment | لحظة مضحكة | Forest Clearing | 30s |
| 8 | Emotional moment | لحظة حزينة صغيرة | Under a Forest Tree | 35s |
| 9 | Song | أغنية معاً نستطيع | Meadow → Moon Garden | 60s |
| 10 | Solution (obstacle) | عائق الطريق | Moon Garden Edge | 45s |
| 11 | Solution (teamwork) | العمل معاً | Moon Garden Edge | 35s |
| 12 | Solution (reunion) | لمّ الشمل | Moon Garden Pond | 35s |
| 13 | Lesson | الدرس | Moon Garden Pond | 30s |
| 14 | Warm ending | عودة دافئة | Path Home | 30s |
| 15 | Teaser | تشويق للمغامرة القادمة | Cottage Doorstep | 20s |

Every scene has: `title`, `location`, `description` (English visual description — standard prompt-engineering practice, matching how `app.core.db.seed` already writes Melissa/Bilsan's `visual_summary` in English even though dialogue is Arabic), `dialogue_ar` (narration + dialogue, "Speaker: line" convention), `camera_direction` (shot type + motion + a transition note into the next scene), `voice_notes` (tone/pacing/pronunciation direction), `estimated_duration_seconds`, `characters_present`, and a real `prompt_text`/`negative_prompt_text` composed by `PromptComposerService` (§4). All locations are drawn from `docs/03_WORLD_BIBLE.md`'s existing location list.

**"Purpose" and "summary" were not added as new Scene columns.** They're the two extra per-scene fields the brief asked for that the current schema has no slot for — but `title` + `description` already carry that information for a human reading the storyboard (the beat is documented in `app/core/db/episode_001_production.py`'s comments for traceability, not as stored data), so no schema change was needed for them. "Production status" is likewise not a new field — it's the scene's real `ApprovalService.get_current_approval_state` (currently `None`/unapproved for all 15, honestly, since no human has reviewed them yet).

## 2. Script

Stored through `ScriptService` exactly like Milestone 5's Episode Workspace models it — never bypassed:

- `Script.full_script`: the complete ~2,750-character screenplay, all 15 scenes' narration/dialogue in order.
- `Script.summary`: a 3-sentence logline.
- `Script.notes`: documents this as a draft-v1 first pass, written to the Character Bible/World Bible constraints (no violence, no frightening scenes, ages 3-7, one lesson), explicitly awaiting human review.
- `Script.status` stays `DRAFT` — nothing calls `submit_script_ready`/`approve_script`. A human reviews and advances it through the Script tab's existing Mark Ready / Approve buttons.

## 3. Storyboard & Character References

All 15 scenes are created through `SceneService.add_scene`/`update_scene` — the same service every other Workspace edit uses. Every scene references **existing** `Character` rows via `characters_present` (no character data is duplicated onto the scene) — Melissa and Bilsan (already in the Character Bible) plus the new Tortor:

- **Tortor** (`app/core/db/episode_001_production.py::_get_or_create_tortor`) is seeded the same way `app.core.db.seed.seed_melissa`/`seed_bilsan` are: a `Character` row plus one `DRAFT` `CharacterVersion` with a `PLACEHOLDER pending approved animated model-sheet art` visual summary — no `master_prompt`, no approval. Kept **out of** `app.core.db.seed` deliberately: `seed_demo_data` has its own tested contract (exactly 2 characters), and Tortor is real content specific to this episode, not generic demo data.
- No `CharacterVersion` for any of the three characters is `approved_canon`, and none has an `active_version_id` set. This is not an oversight — see §6.

## 4. Prompt Composition

Every scene's `prompt_text`/`negative_prompt_text` is produced by a real call to `PromptComposerService.compose_scene_prompt` (via `SceneService.generate_and_store_prompt`) — **not hand-written**. A shared manual negative-prompt baseline (`"scary imagery, violence, weapons, dark horror lighting, realistic photography, adult body proportions"`) is set on every scene first, encoding the World/Brand Bible's "no violence, no frightening scenes" rule directly into the composed output, not just into documentation.

Because no character has an approved active version yet, every composed prompt **correctly and automatically omits** the `"Characters: ..."` section `PromptComposerService` would otherwise add — the prompt is genuinely incomplete in exactly the way the current production state is incomplete, not padded out to look more finished than it is. Composed prompts can be freely hand-edited afterward through the same Storyboard tab as any other scene.

## 5. Song Package

**New `Song` model** (`app/core/models/episode.py`), one row per Episode — same 1:1 shape as `Script`, but deliberately with **no status/approval lifecycle**, since nothing in this milestone reviews lyrics:

| Field | Content |
|---|---|
| `lyrics_ar` | Full lyrics for "معاً نستطيع" — two verses (Melissa/Bilsan, then Tortor) + repeated chorus + outro |
| `purpose` | Reinforces the episode's lesson via a catchy, repeatable sing-along chorus |
| `duration_seconds` | 60 (within the 45–75s target) |
| `production_notes` | Tempo, key, instrumentation, who sings which verse |
| `suno_style_prompt` | A genre/instrumentation/vocal-style description for Suno or manual production — describes *style*, not any specific existing song, so it doesn't imitate copyrighted material |

New minimal `SongService` (`get_or_create_song`/`update_song`, mirroring `ScriptService`'s shape without the status lattice) and a new **Music tab section** in `EpisodeWorkspacePage` (`_build_song_fields`/`_refresh_song_fields`/`_on_save_song`) — added *above* the tab's existing produced-audio `Asset` list, not replacing it. The Music tab now shows both the written song package and, unchanged, the real "+ Import Music" flow for whatever audio file eventually gets produced from this package.

## 6. Voice Package

No new voice-script model. `SceneService.build_voice_package(session, episode_id) -> list[VoiceLine]` is a small, pure derivation (~25 lines) that parses each scene's existing `dialogue_ar` for its already-established `"Speaker: line"` convention and returns one `VoiceLine(scene_order_index, scene_title, speaker, text, voice_notes)` per line — grouping the result by `speaker` (e.g. via `itertools.groupby`) gives exactly the "Melissa / Bilsan / Narrator / Tortor" breakdown Phase 6 asked for, without a second copy of the same dialogue text living in a separate table. Real content: 15 scenes' worth of dialogue produces well over 20 attributed lines across all four speakers.

Per-scene `voice_notes` (new nullable `Scene` column) carries the emotional tone, pacing, and pronunciation guidance a voice performer needs — kept as one short paragraph per scene rather than three separate columns, since that's how this kind of direction is normally authored.

No voice is synthesized — the deliverable is the script above, ready for a human voice actor or an external tool.

## 7. Image/Video Production Plan

No new fields — the plan is the storyboard itself, reusing what's already there: `description` = required key visual (including props described inline, e.g. the teddy bear, the fallen branch), `camera_direction` = shot type + motion + a transition note into the next scene, `estimated_duration_seconds` = target clip length, `characters_present` = required characters, `location` = background. Nothing here is generated automatically — assets produced in external tools import through the existing `AssetImportService`/Asset pipeline, exactly like every other episode's assets do.

## 8. Three Shorts

`Short` gained 4 new nullable columns (`spoken_text_ar`, `on_screen_text_ar`, `target_duration_seconds`, `editing_notes`) — a Short's own edit script, distinct from its source Scenes' full dialogue. All three of Episode 001's pre-existing `PLANNED` Shorts (from `seed_episode_001`) are filled in and linked to real source scenes via `ShortService.link_source_scenes`:

| # | Title (AR) | Source scenes | Target | Hook |
|---|---|---|---|---|
| 1 | الاكتشاف! | 1, 3 | 30s | "سلحفاة صغيرة... وحيدة تماماً. ماذا سيحدث بعد ذلك؟" |
| 2 | أغنية معاً نستطيع | 9 | 40s | "أغنية جديدة وممتعة... هل تستطيعون الغناء معنا؟" |
| 3 | لمّ الشمل | 11, 12 | 40s | "بعد كل هذه المساعدة... هل ستصل السلحفاة إلى بيتها أخيراً؟" |

`ShortService.validate_short` reports all three as content-complete.

## 9. YouTube SEO Package

Stored on `Episode`'s existing SEO columns (`description_ar`, `description_en`, `hashtags`, `credits_text`) — first real, non-empty content in these fields for this episode:

- Arabic + English descriptions (warm, lesson-forward, with a subscribe call-to-action — no clickbait).
- Shared hashtag set: `بيت_الحكايات`, `ميليسا_وبيلسان`, `قصص_اطفال_بالعربي`, `HouseOfStories`, `مساعدة_الاخرين`, `ArabicKidsShow`.
- `credits_text` documents authorship and explicitly states no AI-generated or third-party imagery was used.

**Thumbnail concept/Arabic overlay text/prompt** needed no schema change at all: `PromptTemplate` already has a `THUMBNAIL` category and an `episode_id` scope built for exactly this. One `is_reusable=False` `PromptTemplate` row (`category=THUMBNAIL`) holds the concept, the Arabic overlay text, the prompt, and an explicit `STATUS: BLOCKED` note — it cannot be rendered as a final asset until Melissa and Bilsan have approved reference art. Using `THUMBNAIL` (not `IMAGE`) keeps it fully isolated from `PromptComposerService`'s scene-prompt resolution, which only ever looks at `PromptCategory.IMAGE`.

## 10. Production Readiness (the honest result)

```
Readiness: 52.0% (NOT READY)
```

### 8-stage summary (`ProductionChecklistService.evaluate_stage_summary`)

| Stage | Status | Reason |
|---|---|---|
| Script | **BLOCKED** | Script is draft, not yet approved. |
| Storyboard | **BLOCKED** | 15 scene(s) not yet approved: [1..15]. |
| Images | **BLOCKED** | Missing approved character reference art for: melissa, tortor, bilsan. |
| Voice | **BLOCKED** | Final voice asset is missing or not approved. |
| Music | **IN_PROGRESS** | Song lyrics and production notes are written; awaiting final produced audio. |
| Video | **BLOCKED** | Missing approved character reference art for: melissa, tortor, bilsan. |
| SEO | **COMPLETED** | — |
| Export | **BLOCKED** | Script is draft, not yet approved. |

Only SEO is genuinely complete. Nothing here was massaged to look more finished — this is the true state of a real script/storyboard/song/Shorts pass with zero human review and zero approved character art yet.

### Two real `ProductionChecklistService` fixes made to get here honestly

1. **Images/Video now check character references directly.** Before this milestone, `evaluate_stage_summary` only bucketed `character_versions_approved_and_active` under **Storyboard** — Images/Video had no visibility into it at all, so they would have shown `NOT_STARTED` (technically true, but not the *specific*, actionable reason). A shared `ProductionChecklistService._characters_missing_approved_version` helper (factored out of the existing `_check_characters` check, not duplicated) is now also consulted by `_stage_status_images`/`_stage_status_video`, which report `BLOCKED` naming exactly which character(s) are missing approved reference art.
2. **Music now distinguishes "written" from "nothing done."** `_stage_status_music` previously only checked for a final produced `Asset`, so a fully-written, unrecorded song and a completely blank Music tab looked identical (`NOT_STARTED`). It now checks the new `Song.lyrics_ar` too, reporting `IN_PROGRESS` with an honest reason once real content exists but no audio has been produced yet.

### A real bug found and fixed along the way: a hang on a brand-new episode's first Save

Writing the GUI test for the Music tab's save round-trip (on a *freshly created* episode) hung indefinitely under the offscreen test platform — the same failure shape `docs/25`'s Milestone 4B bug had: an uncaught `ServiceError` subclass reaching `show_error()`, which opens a real blocking `QMessageBox` with no user present to dismiss it.

**Root cause:** `EpisodeWorkspacePage.refresh()`/`_refresh_song_fields()` called `ScriptService.get_or_create_script`/`SongService.get_or_create_song` inside `ApplicationContext.open_session()` — a plain, **non-committing** session meant for read-only queries. The very first time a Script/Song tab opens, `get_or_create_*` inserts a new row and `flush()`es it, but since the session is never committed, closing it at the end of the `with` block silently **rolls the insert back**. The page still remembers that row's UUID (`self._script_id`/`self._song_id`) — so the *next* Save calls `update_script`/`update_song` against an id that was never actually persisted, raising `NotFoundError` (a `ServiceError`), which the page's own error handler turns into the blocking dialog.

This was a **pre-existing Milestone 5 bug**, not new to this milestone — the Script tab had the identical latent issue, just never exercised by a test (there was no GUI test for `_on_save_script` before now). **Fix:** both call sites now use `session_scope()` (commit-on-success) instead of `open_session()`, so the get-or-create's insert actually persists. A regression test (`test_save_script_on_a_brand_new_episode_persists_without_error`) locks this in for the Script tab; the Music tab's own round-trip test covers the Song side.

## 11. Seed / Demo Data Policy

Episode 001 is real studio production data now, not a placeholder. `app/core/db/episode_001_production.py::populate_episode_001_production_content(session)` is the one idempotent entry point (new `populate-episode-001` CLI command) that fills it in — every section (script, scenes, song, Shorts, SEO, thumbnail concept) independently checks "is this field already non-empty?" before writing anything, so:

- Re-running it is always safe — verified by an automated idempotency test and a live re-run against the real database.
- A human edit made through the GUI (e.g. rewriting the SEO description) **survives** a subsequent re-run untouched — verified by both an automated test and a manual check with a real database.
- It never deletes or resets anything; it only ever fills in what's still empty.

`app.core.db.seed.seed_demo_data`'s own tested contract (exactly 2 characters, generic dev/demo bootstrap) was **not** changed — Tortor and all of this episode's real content live in the new module, layered on top.

## 12. Future External-Tool Handoff

- **Images/Video**: once Melissa, Bilsan, and Tortor have approved reference art (a human decision, via the existing Character Lock workflow — `CharacterVersionService.approve_character_version`), each scene's composed prompt automatically gains its `"Characters: ..."` section on the next re-composition. Key images/clips produced in external tools import through the Images/Video tabs' existing `AssetImportService` flow — no new import path needed.
- **Voice**: `SceneService.build_voice_package` output is handed to a voice actor (or an external TTS tool) as-is; the resulting audio imports through the Voice tab exactly like any other asset.
- **Music**: the `Song` package (lyrics + Suno-style prompt) is pasted into Suno or handed to a composer; the resulting audio imports through the Music tab.
- **Shorts/Export**: once the long-form video and audio assets exist and are approved, `ExportPackageService`/the Shorts' own `export_asset_id` linking take over exactly as already built.

## 13. Future Real-AI-Provider Integration Points

Unchanged from `docs/29` §7 — this milestone adds real *content* to plug into those points, not new plumbing:

- `PromptComposerService.compose_scene_prompt`'s output (now real, per-scene) is exactly what a future `AIOrchestrator` image-generation workflow would hand to a real provider once character art is approved.
- The `Song` package's `suno_style_prompt` is what a future Suno-API integration (or a human) would submit as-is.
- `SceneService.build_voice_package`'s output is what a future ElevenLabs-style TTS workflow would iterate over, one `VoiceLine` at a time.

## 14. Files Created and Modified

**Created:**
```
alembic/versions/29891cfbf82f_episode_001_production_song_table_short_.py
app/core/db/episode_001_production.py
app/core/services/song_service.py
tests/unit/test_song_service.py
tests/integration/test_episode_001_production.py
docs/30_MILESTONE_6_EPISODE_001_PRODUCTION_STATUS.md   (this file)
```

**Modified:**
```
app/core/models/episode.py               (+ Song model, Scene.voice_notes, Short's 4 new columns)
app/core/models/__init__.py              (+ Song export)
app/core/services/scene_service.py       (+ voice_notes in allowlist, + build_voice_package/VoiceLine)
app/core/services/short_service.py       (+ 4 new fields in allowlist)
app/core/services/production_checklist_service.py  (+ character-reference blocking for Images/Video,
                                                       + Song-aware Music IN_PROGRESS, + shared
                                                       _characters_missing_approved_version helper)
app/gui/context.py                       (+ song_service)
app/gui/pages/episode_workspace_page.py  (+ Song package fields in Music tab; refresh()/
                                             _refresh_song_fields fixed to use session_scope,
                                             not open_session — see §10's bug writeup)
app/cli/main.py                          (+ populate-episode-001 command)
tests/integration/test_migrations.py     (+ "songs" in EXPECTED_TABLES)
tests/unit/test_scene_service.py         (+ voice_notes, build_voice_package tests)
tests/unit/test_short_service.py         (+ new-field test)
tests/integration/test_production_checklist_service.py  (+ blocked-reason and music-in-progress tests)
tests/gui/test_episode_workspace_page.py (+ Music tab tests, real-Episode-001 content test,
                                             Script-tab-on-a-fresh-episode regression test)
```

## 15. Test Count and Verification

```
$ QT_QPA_PLATFORM=offscreen pytest -q
545 passed

$ ruff check .
All checks passed!

$ alembic upgrade head / alembic check
Clean scratch DB: OK. DB with pre-existing scene/short rows: new columns
backfill NULL correctly. downgrade -1 / re-upgrade head: OK. alembic
check: no drift.
```

Manual verification (offscreen Qt — no physical display in this environment; screenshots stand in for an interactive session): launched the real app against the real `data/studio.db`, opened Episode 001, confirmed the real script/15 ordered scenes/composed prompts/Voice tab/Music tab lyrics/SEO metadata/3 Shorts, ran the readiness checklist and confirmed Images/Video report BLOCKED with the exact missing-character reason, then closed the `ApplicationContext` and opened a brand-new one against the same database — every field persisted correctly. All 16 steps passed.

## 16. Known Limitations

- Shorts have no dedicated Workspace tab yet — they're fully modeled and content-complete, but only reachable through the service layer/CLI, not a GUI tab (out of scope for this milestone; `docs/29`'s extension points already describe how a 9th stage/tab would be added).
- `SceneService.build_voice_package`'s speaker-splitting depends on the `"Speaker: line"` convention every scene's `dialogue_ar` already follows; a scene written without that convention just contributes no lines, not an error.
- The Music tab's Song fields have no character limit or lyrics-formatting validation — acceptable for a single written package today, would need a firmer content contract if this scales to many episodes with different lyrical structures.

## 17. Recommended Next Step

Awaiting approval. The natural follow-on is a human review pass through the GUI itself — approving the script, approving scenes, and (separately, whenever real reference art exists) approving Melissa/Bilsan/Tortor's `CharacterVersion`s — which would flip Script/Storyboard/Images/Video from `BLOCKED` to their next honest state, with no code changes required to make that happen.
