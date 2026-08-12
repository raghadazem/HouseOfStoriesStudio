# 32 — Milestone 8 Status: Real Scene Image Generation

**Milestone:** 8 — real, multi-character scene image generation for Episode 001, built on Milestone 7's Character Lock / `GeminiProvider` / `GenerationJob` architecture.
**Builds on:** `docs/18` (AI architecture), `docs/31` (Milestone 7 — real character reference generation). Scene *video* generation stays explicitly out of scope, deferred to a future milestone.

---

## 1. Architecture

Milestone 7 built the whole real-generation pipeline (`GeminiProvider`, `GenerationJob`/`GenerationJobService`, `generation_runner`, `AIOrchestrator`) for exactly one workflow: character-reference images, locked to at most one character per call, rendered from a `PromptTemplate`. Milestone 8 extends this same pipeline to scene images — a fundamentally multi-character request — **without changing any of Milestone 7's own code paths**. `CharacterReferenceWorkflow`, `run_character_reference_batch`, and every Milestone 7 test are untouched.

The extension is additive throughout:

```
Scene.prompt_text (authored, human-edited)
  → SceneGenerationReadinessService  (can this scene generate right now?)
  → ReferenceSelectionService        (exactly one canon reference per present character)
  → run_scene_image_batch            (new sibling to run_character_reference_batch)
  → GenerationJob                    (same table, same lifecycle, zero schema change)
  → AIOrchestrator.run_workflow      (prompt_template_id now optional)
  → SceneImageWorkflow               (new direct-prompt path, template path kept as fallback)
  → GeminiProvider                   (image_size support added; capacity metadata added)
  → AssetImportService               (unchanged)
  → DRAFT Asset
```

## 2. Prompt Path

`SceneImageWorkflow` no longer calls `PromptEngine`/`PromptTemplate` for scene images. `WorkflowContext` gained three optional fields — `rendered_prompt_text`, `rendered_negative_prompt_text`, `rendered_reference_asset_paths` — and `prompt_template_id` became optional (`uuid.UUID | None = None`). When `rendered_prompt_text` is set, `SceneImageWorkflow` builds `GenerationRequest` directly from it, bypassing template rendering entirely; when it's `None`, the original template-based path still runs unchanged (proven by `test_scene_image_workflow_legacy_template_path_still_works`).

`Scene.prompt_text`/`negative_prompt_text` — composed by `PromptComposerService`, freely hand-edited afterward via the Storyboard tab — are sent **verbatim**. No `PromptTemplate` row is ever created per scene. `AIOrchestrator._template_version` was given a `None`-safety guard (`session.get(PromptTemplate, None)` is never called).

## 3. Canon Reference Semantics

Milestone 7's `CharacterVersionService.validate_character_lock` is **unchanged** — it still only requires *some* approved reference to exist. Milestone 8 layers a strictly stronger rule on top, used only for scene generation:

- `CharacterVersionService.get_canon_reference(session, version_id)` — returns the one `CharacterReference` with `is_current_canon=True`, or `None` if zero or (an ambiguous, should-never-happen) more than one are flagged.
- `CharacterVersionService.set_canon_reference(session, reference_id)` — the only path that may ever set the flag; unsets every sibling reference for the same version first, in the same call, guaranteeing at most one canon reference per version going forward.
- **No fallback to an earliest/oldest reference exists anywhere.** A character with no deterministic canon reference is reported as unresolved, naming the character, never silently filled in.

**GUI**: `_CharacterVersionDetailDialog` (Character Version workflow) now lists every reference image with a "★ Canon" badge on the current one and a "Make Canon" button on every other approved reference — no separate management screen.

## 4. Provider Capability Handling

```python
@dataclass(frozen=True)
class ProviderCapabilities:
    max_character_references: int | None = None
```

`AIProvider.capabilities: ClassVar[ProviderCapabilities]`. `GeminiProvider.capabilities = ProviderCapabilities(max_character_references=4)` — verified against `ai.google.dev/gemini-api/docs/image-generation`: `gemini-3.1-flash-image` documents "Up to 4 images of characters to maintain character consistency" as a category distinct from its object (10) and style (3) reference quotas, neither of which this codebase sends. `MockProvider` leaves the default (`None`, unconstrained). **Nowhere else** — no GUI code, no domain model — hardcodes this number; only `SceneGenerationReadinessService` reads it, to block a scene before ever exceeding it.

## 5. Multi-Character Provenance

`GenerationJob.reference_asset_ids` (existing column) still stores the flat list of every selected reference `Asset.id`. Additionally, `GenerationJob.parameters` (existing generic `JSON` column, already used for `candidate_index`) now also carries a structured, immutable snapshot:

```json
"character_references": [
  {"character_id": "...", "character_version_id": "...",
   "reference_asset_id": "...", "reference_label": "front view"}
]
```

captured once, at batch-creation time, from `ReferenceSelectionService`'s result — and proven (`test_scene_batch_provenance_survives_later_canon_reference_change`) to stay unchanged even if the canon reference for that character/version changes afterward. No new column or table was needed.

## 6. Reference Selection

`ReferenceSelectionService.select_references(session, scene)` — for each present character (sorted by slug for determinism, since `Scene.characters_present` has no ordering column): requires an active `CharacterVersion` in `APPROVED_CANON` status, then a deterministic canon reference via `get_canon_reference`. Returns `selected` (character → reference) and `unresolved` (character, reason) — never raises, safe to call for a free GUI preview.

## 7. Readiness

`SceneGenerationReadinessService.evaluate(session, scene_id, *, provider_name, orchestrator)` — a new, small, scene-scoped service (not folded into the 24-check, episode-wide `ProductionChecklistService`, and not a `SceneService` method, since it composes `ReferenceSelectionService`/`GenerationJobService`/`AIOrchestrator`). Checks, each with an actionable message: prompt composed; every present character resolved (named individually when not); provider configured; reference count within the provider's documented capacity; no `GenerationJob` already `PENDING`/`RUNNING`/`CANCEL_REQUESTED` for this scene. Returns a `SceneReadinessReport` (`is_ready`, `blocking_messages`) — never a bare boolean.

## 8. Candidate Lifecycle

`generation_runner.run_scene_image_batch`/`SceneImageBatchRequest` mirror `run_character_reference_batch`/`CandidateBatchRequest` exactly: fail-fast readiness check before any row is created, one shared `batch_id`, one `GenerationJob` per candidate (never assumes multi-candidate-per-call), `candidate_index` differentiates candidates, commit after every durable transition. Retry (`GenerationJobService.retry_job`) and cancellation (`request_cancel`/`finalize_cancelled_after_running`) needed **zero changes** — both were already workflow-agnostic.

## 9. Image-Size Semantics

Verified via `ai.google.dev`: `gemini-3.1-flash-image` supports `image_size` ∈ {512px, 1K, 2K, 4K}, default 1K; 4K costs ~2.25× the output tokens of 1K. `GeminiProvider.generate()` now builds `image_config=types.ImageConfig(image_size=...)`, reading `request.parameters.get("image_size", "1K")` — an unrecognized value falls back to `"1K"` rather than being sent as-is. The GUI's Generate dialog exposes exactly two choices — **Standard (1K)**, the default, and **High Quality (2K)**, opt-in — never 512px or 4K. **2K is a new, independent generation, not an upscale**: every 2K result is its own `GenerationJob`/DRAFT `Asset`, goes through the same review/approve/Set-as-Key-Image flow, and approving a 1K candidate never triggers a 2K call automatically.

## 10. Scene Key-Image Semantics

`Asset.scene_id` + a new role constant `role="final_scene_image"` (`ROLE_FINAL_SCENE_IMAGE` in `app/core/models/asset.py`) identify a scene's current approved key image — no `SceneAsset` table. **Reserved role, enforced, not just documented**: `AssetImportService.import_asset` raises `ValidationError` if a caller tries to assign this exact role string (regression test: `test_import_asset_rejects_reserved_scene_key_image_role`). The only path that may assign it is `SceneService.set_scene_key_image(session, scene_id, asset_id)`, which — in one transaction — clears the role from whatever `Asset` currently holds it (leaving it `APPROVED`, fully preserved, never deleted) before assigning it to the new one. Regeneration never automatically replaces a key image; only an explicit "Set as Key Image" click does.

## 11. GUI Workflow

The Images tab (`EpisodeWorkspacePage`) is no longer a generic import list — it's `SceneImagesPanel` (`app/gui/pages/scene_image_workflow.py`), one card per scene showing: character chips, Ready/Blocked status with the exact blocking reason as a tooltip on a disabled Generate button, current key-image thumbnail if set, and a generation-attempt count. Clicking Generate opens `_GenerateSceneImageDialog` (provider picker, read-only prompt preview, resolved-reference preview, candidate count, Standard/High Quality choice), then `_SceneCandidateReviewDialog` — a thin subclass of the **shared** `CandidateReviewDialogBase`.

**Shared candidate-review extraction**: Milestone 7's `_CandidateTile`/`_CandidateReviewDialog` (character-reference-specific) were extracted into `app/gui/widgets/candidate_review.py` as `CandidateTile`/`CandidateReviewDialogBase`, with the one caller-specific action (Milestone 7: "Add as Reference"; Milestone 8: "Set as Key Image") made pluggable via an overridable `_tertiary_state` hook. `character_version_workflow.py`'s `_CandidateReviewDialog` kept its exact class name, module, and constructor signature, now as a thin subclass. `GenerationWorker` gained one optional `runner=` keyword (default `run_character_reference_batch`, unchanged for every existing call site). **Regression gate**: the full pre-existing Milestone 7 GUI suite (`tests/gui/test_character_version_workflow.py`, `tests/gui/test_generation_worker.py`) was run **unmodified** before any Milestone 8 GUI code was written, and again after, both times fully green (12/12) — proving the extraction alone caused zero behavior change. One real regression was caught and fixed during the extraction: `_on_cancel`'s error path had moved to a different module's `show_error` binding, breaking a test's `monkeypatch.setattr(cvw, "show_error", ...)` and hanging on a real modal dialog in headless mode; fixed with an overridable `_show_error` hook so each subclass routes errors through its own module.

## 12. Real Gemini Smoke-Test Result

One isolated scratch environment (never the real `data/`/`production/` folders), same discipline as Milestone 7's. Two real, Pillow-generated, `Image.verify()`-checked placeholder PNGs stood in for Melissa/Bilsan reference art (no personal photos, no copyrighted art). Exactly one real paid call: provider `gemini`, model `gemini-3.1-flash-image`, 1 scene, 2 characters, 1 candidate, `image_size="1K"`.

- First attempt failed before any request reached Gemini's servers — a bug in the throwaway test fixture (fabricated, non-decodable JPEG-like bytes), not a product defect. Fixed by generating real, `PIL`-verified PNGs instead; reported and approved before retrying, per the founder's no-silent-retry policy.
- Second attempt: **SUCCEEDED.** `GenerationJob.status = SUCCEEDED`; `scene_id`/`episode_id` correct; `reference_asset_ids` held both references; `parameters["character_references"]` held both character/version/reference/label mappings; `parameters["image_size"] = "1K"`; `prompt_text` was the exact multi-character composed text ("Characters: Bilsan: ... | Melissa: ..."). Resulting `Asset`: DRAFT, `role=None` (no auto key-image assignment). `character_references` table count stayed at exactly 2 (no auto-promotion of the generated candidate). Verified via a **separate, fresh `ApplicationContext`** (new engine/session, different process invocation) that everything persisted correctly, and via a real `PIL.Image.open().verify()`/reopen that the generated file is a genuinely valid image (1024×1024 JPEG). Boolean-only secret-leak audit: `NO LEAK DETECTED` across the scratch database, production folder, source images, and every changed file in the real repo's working tree.

## 13. Testing Strategy

All offline (`MockProvider`), except the one manual real-API smoke test above. New/extended:

- `tests/unit/test_reference_selection_service.py` (7) — single/multi-character, deterministic order, strict-block on missing canon reference, missing active version, non-canon-status version, partial resolution naming only the blocked character, empty cast.
- `tests/unit/test_scene_generation_readiness_service.py` (7) — every blocking check individually, plus the fully-ready path.
- `tests/unit/test_ai_workflows.py` — 3 new `SceneImageWorkflow` tests: direct-text single-character, direct-text multi-character (proving no cap at one), legacy template path unchanged.
- `tests/unit/test_generation_runner.py` — 10 new `run_scene_image_batch` tests mirroring every `run_character_reference_batch` case: fail-fast (no rows created), unknown scene, strict-block naming the character, multi-character provenance, provenance survives a later canon-reference change, unconfigured provider, `image_size` snapshot, retry `batch_id` inheritance, provider failure, cancel-while-generating.
- `tests/unit/test_character_version_service.py` — 6 new Canon Reference tests.
- `tests/unit/test_scene_service.py` — 5 new `set_scene_key_image` tests including the uniqueness-on-replace guarantee.
- `tests/unit/test_asset_import_service.py` — 1 new reserved-role regression test.
- `tests/unit/test_generation_job_service.py` / `test_approval_service.py` — `scene_id` filter tests.
- `tests/gui/test_character_version_workflow.py` — 2 new Canon Reference GUI tests, 9 pre-existing kept unmodified.
- `tests/gui/test_scene_image_workflow.py` (new, 6) — empty state, blocked scene naming the character, ready scene, generate-dialog contents, full worker-driven batch + Set as Key Image, cancel-error-surfacing (proving the shared dialog's error routing).

Offline suite: **675 passed**, 0 failed (up from Milestone 7's 622). `ruff check .`: clean. `alembic check`: no drift — **zero migrations in this milestone**, confirming the design decision that every extension fit into existing generic columns.

## 14. Episode 001 Verification (Read-Only, No Paid Calls)

A dedicated isolated-scratch script seeded the real Episode 001 content (15 scenes, real Arabic titles/dialogue, real cast combinations), approved+canon-referenced Melissa and Bilsan (leaving Tortor deliberately incomplete, matching real current production state), and re-composed every scene's prompt. Result: exactly 15 scenes detected; the 4 scenes cast as Melissa+Bilsan only were correctly READY; the 11 scenes also featuring Tortor were correctly BLOCKED, each naming Tortor specifically; every resolved reference matched the right character; every scene's real `Scene.prompt_text` was confirmed non-empty and, for ready scenes, included the correct multi-character composed blocks. The real `SceneImagesPanel` GUI widget, instantiated against this same data, rendered identically to the service-layer computation (4 Ready/11 Blocked labels, 4 enabled/11 disabled Generate buttons) — full GUI-to-service consistency against real production data. No paid API call was made anywhere in this verification (`mock_provider` only, `GEMINI_API_KEY` explicitly removed from the process environment).

## 15. Migration / Backward Compatibility

**No schema migration in this milestone.** `alembic check` confirms no drift both before and after implementation. Every extension — Canon Reference helpers, the structured provenance snapshot, `image_size`, `ProviderCapabilities`, the reserved scene-key-image role, the shared GUI base, `GenerationWorker.runner` — is additive Python using existing generic columns (`GenerationJob.parameters`, `Asset.role`) or new optional dataclass fields. `CharacterReferenceWorkflow` and every Milestone 7 code path, test, and GUI flow are unchanged.

## 16. Future Video Handoff

A future Video milestone locates "the approved image for Scene X" via the exact same `(scene_id, role="final_scene_image")` query this milestone establishes — no new lookup mechanism to invent. `GenerationJob`'s shape is now proven to extend to a second real workflow without any schema change, the same way it will extend to a third (video). `ReferenceSelectionService`/`SceneGenerationReadinessService` are scene/image-scoped by design; a future video-generation readiness check is expected to be a new, analogous service, not a forced generalization of these two.

## 17. Known Limitations

- `max_character_references` (4, for `gemini-3.1-flash-image`) is the only capability field — object/style reference capacity are real, separately-documented Gemini limits that this codebase never needs, so no field exists for them yet; adding one later is a pure additive change to `ProviderCapabilities`.
- Scene revisioning was deliberately not introduced — `Scene` stays a single mutable row. `GenerationJob`'s immutable prompt/reference/provider/parameter snapshot is the provenance record; there is no way to see a scene's prompt history independent of its generation attempts.
- `ReferenceSelectionService`'s deterministic ordering (`Character.slug`, alphabetical) has no concept of a "primary" character for a scene — acceptable for Episode 001's cast sizes, worth revisiting if a future episode's ordering ever matters visually.
- The Images tab computes readiness against the first alphabetically-available configured image provider when more than one is configured — consistent with the existing Dashboard convention (`dashboard_page.py`), not a new pattern, but worth a real provider-picker if a second real image provider is ever added.
- Cost is not tracked (`GenerationJob.cost_usd` stays `NULL`) — Gemini's response reports token usage, not a dollar figure, and this project's policy is never to estimate cost locally (unchanged from Milestone 7).
