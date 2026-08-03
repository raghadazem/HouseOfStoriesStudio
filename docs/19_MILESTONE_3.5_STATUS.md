# 19 — Milestone 3.5 Status: AI Architecture & Workflow Engine

**Milestone:** 3.5 — AI Architecture & Workflow Engine
**Status:** Complete. Stopped before Milestone 4 (GUI) per instructions.
**Not pushed to GitHub as part of this session's local work** — committed locally, per instruction; see `docs/18_AI_ARCHITECTURE_PLAN.md` for the approved plan this milestone implements.

---

## 1. What Was Completed

Per the founder's approved decisions on the five open questions in `docs/18_AI_ARCHITECTURE_PLAN.md` §15:

1. **Provider scope**: only the `AIProvider` interface + a fully-working `MockProvider`. No structural stub files for OpenAI/Claude/Gemini/Suno/Google TTS — those are added later, one file + one registry entry each, when a provider is actually chosen.
2. **Workflow engine shape**: fixed, code-defined `Workflow` subclasses — not a generic config/DSL-driven engine.
3. **Generation logging**: structured JSON log lines through the existing `app/logging_setup.py` logger (no new `GenerationLog` table), carrying every field the founder listed.
4. **Initial workflow set**: `character_reference_image`, `scene_image`, `voice_line`, `thumbnail` (four, not three — thumbnail added per the founder's revised list; song remains manual, deferred).
5. **Review queue location**: extended the existing `ApprovalService` with `list_pending_review_assets()` — no new module.

New package: `app/core/ai/` (provider interface, `MockProvider`, `PromptEngine`, four workflows, `AIOrchestrator`, generation logger, exceptions). No database migration — confirmed unnecessary, per `docs/18` §2 (`Asset.prompt_used_id`/`Asset.source_tool` already covered everything needed).

Plus:
- 6 new CLI commands (`list-ai-workflows`, `list-ai-providers`, `run-ai-workflow`, `list-review-queue`) reusing the exact same `AIOrchestrator`/`ApprovalService` the GUI will eventually call.
- 43 new tests (280 total, up from 237 at the end of Milestone 3).
- `ApprovalService.list_pending_review_assets()` — the review queue, a read-only query over the same `Asset.approval_status` concept Milestone 3 already owns.

### No schema changes

Zero new tables, zero new columns, zero new Alembic migrations. Every generated asset is a completely ordinary `Asset` row (`approval_status=draft`, `source_tool="mock_provider"`, `prompt_used_id` set) — indistinguishable in the schema from a manually imported draft asset, exactly as designed.

## 2. Files Created and Modified

**Created:**
```
app/core/ai/__init__.py
app/core/ai/exceptions.py
app/core/ai/provider_interface.py
app/core/ai/prompt_engine.py
app/core/ai/generation_logger.py
app/core/ai/orchestrator.py
app/core/ai/providers/__init__.py
app/core/ai/providers/mock_provider.py
app/core/ai/workflows/__init__.py
app/core/ai/workflows/base.py
app/core/ai/workflows/character_reference_workflow.py
app/core/ai/workflows/scene_image_workflow.py
app/core/ai/workflows/voice_line_workflow.py
app/core/ai/workflows/thumbnail_workflow.py
docs/19_MILESTONE_3.5_STATUS.md   (this file)
tests/unit/test_ai_provider_interface.py
tests/unit/test_ai_prompt_engine.py
tests/unit/test_ai_workflows.py
tests/unit/test_ai_orchestrator.py
tests/unit/test_ai_generation_logger.py
```

**Modified:**
```
app/cli/main.py                    (+ list-ai-workflows, list-ai-providers, run-ai-workflow, list-review-queue commands)
app/core/services/approval_service.py  (+ list_pending_review_assets)
tests/unit/test_approval_service.py    (+ review-queue tests; _asset() helper generalized to accept overrides)
tests/integration/test_cli.py          (+ AI workflow CLI smoke tests, full subprocess stack)
```

No Milestone 1–3 file outside these two `Modified` entries was touched.

## 3. Architecture, As Built

```
AIOrchestrator.run_workflow(session, workflow_name, provider_name=..., prompt_template_id=..., ...)
        │
        ├─ looks up Workflow class + AIProvider instance (registries, dependency-injectable)
        ├─ builds a WorkflowContext
        ├─ workflow.run(ctx):
        │     PromptEngine.build_request(...)   # renders PromptTemplateService template,
        │                                       # merges CharacterVersion lock fields if given
        │       → GenerationRequest
        │     ctx.provider.generate(request)    # MockProvider: deterministic, offline
        │       → GenerationResult (temp file path)
        │     AssetImportService.import_asset(...)  # existing Milestone 3 service, unchanged
        │       → Asset row, approval_status=draft
        └─ finally: logs one structured JSON line, deletes the provider's temp file
```

`ApprovalService.list_pending_review_assets()` is how a human (CLI today, GUI later) finds every generated asset awaiting a decision — the review queue is just `Asset.approval_status == draft`, filterable by episode/character-version/source_tool.

### Deviations from the draft plan (`docs/18`), and why

- **`PromptEngine.build_request()` derives `modality` from the chosen `PromptTemplate.prompt_type`** rather than taking a separate `workflow_name`/`modality` parameter. A template's `prompt_type` (image/video/voice/music/text) already determines the only sensible modality for it — accepting a second, independently-settable `modality` argument would only create a way for a caller to pass a mismatched value. Simplification, not a scope change.
- **`MockProvider` does not copy a static fixture file.** The original sketch described copying a fixture from `providers/_fixtures/`; implementing it that way would make two *different* prompts (e.g. two different scenes) produce byte-identical output, which `AssetImportService`'s duplicate-checksum detection would then wrongly reject as a re-import of the same file. Instead, `MockProvider` derives its output bytes from a sha256 of the full request (modality, prompt, negative prompt, reference paths, parameters) — same request → same bytes (deterministic, as specified), different request → different bytes (no false duplicate). This is the same principle the plan already specified for text/voice/song, applied consistently to every modality.
- **`SceneImageWorkflow` locks to at most one `character_version_id` per call**, not "every character present in the scene" as the plan's prose suggested. Merging multiple characters' locked prompt blocks into one scene prompt needs a concrete multi-character template to validate the merge shape against, which doesn't exist yet — building that now would be speculative. Extending `PromptEngine` to accept multiple character versions is a small, additive change once a real template needs it.
- **A real bug found via manual CLI testing, fixed same-day**: if `AssetImportService.import_asset` failed *after* `provider.generate()` already produced a temp file (e.g. `ConflictError` on a duplicate — a real, reachable case, not hypothetical), the orchestrator had no way to find that temp file to delete it, because it only read the output path from a *successful* workflow return value. Fixed by having each workflow record its `GenerationResult` onto `WorkflowContext.last_generation_result` immediately after `provider.generate()` succeeds, before calling `import_asset` — so the orchestrator's cleanup (in a `finally` block) always finds it, success or failure. Covered by `test_ai_orchestrator.py::test_run_workflow_cleans_up_temp_file_even_when_import_fails_after_generate` and reproduced manually via the CLI (see §4).

## 4. Manual Verification

Run by hand against a real (temp) project directory, not test fixtures:

1. `init-db` + `seed-demo` — clean.
2. `list-ai-workflows` → `character_reference_image`, `scene_image`, `thumbnail`, `voice_line`.
3. `list-ai-providers` → `mock_provider  configured=True  modalities=image,song,text,video,voice`.
4. Created a real `PromptTemplate` (category `thumbnail`, type `image`) via the service layer directly.
5. `run-ai-workflow thumbnail --prompt-template-id ... --episode-id ...` → real `Asset` row created (`draft`, `source_tool=mock_provider`), file present under `production/episodes/<slug>/thumbnails/`, one `INFO`-level `generation_attempt` JSON line written to `data/logs/app.log` with every required field (`workflow_name`, `provider_name`, `request_id`, entity ids, `prompt_template_version`, `started_at`/`ended_at`/`duration_seconds`, `outcome`, `error_category`, `temp_file_name`, `imported_asset_id`) — and no full/absolute file path anywhere in it, only the temp file's basename.
6. Ran the exact same workflow call again (identical prompt) → correctly rejected with `ConflictError` (duplicate checksum, same as a manual re-import would be) — proving `MockProvider`'s determinism actually engages Milestone 3's existing duplicate-detection rule, and logged as `outcome=failure`, `error_category=ConflictError`, `WARNING` level.
7. Confirmed (before and after fixing the bug in §3) that the `MockProvider` temp directory does **not** accumulate files across both the successful run and the rejected duplicate run — the leak found and fixed during this pass.
8. `list-review-queue --source-tool mock_provider` → the generated thumbnail asset, correctly listed, still in `draft`.
9. `run-ai-workflow not_a_real_workflow ...` → clean `Error: Unknown workflow ...` message, exit code 1, no traceback.

## 5. Test Count and Results

```
$ pytest -q
........................................................................ [ 25%]
........................................................................ [ 51%]
........................................................................ [ 77%]
................................................................         [100%]
280 passed in ~32s

$ ruff check .
All checks passed!
```

43 new tests since Milestone 3 (237 → 280): `MockProvider` contract (determinism, distinctness per prompt/parameters, unsupported-modality rejection), `PromptEngine` (simple rendering, modality derivation, missing-variable/unknown-template passthrough errors, Character Lock field merge including reference-asset paths and negative-prompt precedence), all four workflows end-to-end (real `AssetImportService`, real temp `MockProvider` files, required-field validation, no-checksum-collision between two different scenes), `AIOrchestrator` (workflow/provider lookup errors, unconfigured-provider handling, successful run + log record, unexpected-exception wrapping, the temp-file-leak regression), the generation logger (JSON shape, INFO/WARNING level by outcome, basename-only temp path), and `ApprovalService.list_pending_review_assets` (draft-only, episode filter, source_tool filter) — plus CLI smoke tests for all four new commands, including one true full-stack run through a fresh subprocess (`run-ai-workflow` → real orchestrator → real `MockProvider` → real `AssetImportService` → `list-review-queue`).

## 6. Assumptions Made

1. **No stub provider files this milestone**, per the founder's decision — `PROVIDER_REGISTRY` currently has exactly one entry (`mock_provider`). Adding `OpenAIProvider` etc. later is additive; nothing here changes shape when that happens.
2. **Song generation stays entirely manual** — no `SongWorkflow`, no `PromptCategory.SONG` special-cased anywhere in this layer, per the founder's explicit Suno-integration-not-ready reasoning.
3. **Generated assets are never auto-promoted.** Every workflow imports with `role=None` — including `ThumbnailWorkflow`, which does *not* set `role="final_thumbnail"` even though that's an obviously tempting shortcut. Promoting a draft to a `final_*` role remains an explicit human action, same as Milestone 3's character-reference rule.
4. **`VoiceLineWorkflow`'s "character voice profile" is whatever locked `CharacterVersion` fields a template author chooses to reference** — `CharacterVersion` has no dedicated voice-profile column yet (not requested, not added). Worth revisiting once a real voice provider makes "what actually matters for a voice prompt" concrete.
5. **The CLI's `run-ai-workflow` command uses a plain session (not `session_scope`)**, mirroring `import-asset` — because the workflow's only write is one `AssetImportService.import_asset()` call, which already owns its own transaction (Milestone 3, `docs/14`).

## 7. Unresolved / Deferred (unchanged from `docs/18`, reconfirmed)

- No real provider is wired up; `is_configured()` has only ever been exercised as `True` (Mock) in this milestone. The `ProviderNotConfiguredError` path is tested via a fake provider double, not a real one — there isn't a real "not configured" provider to test against yet.
- No persistent `GenerationLog` table — revisit once a real provider makes cost-per-call tracking a real question, per the founder's own stated trigger for revisiting this decision.
- Multi-character prompt merging in `SceneImageWorkflow` (see §3) — deferred until a concrete template needs it.
- Song and video generation workflows — deferred; the `AIProvider`/`GenerationRequest` interface already supports both modalities, so adding them later needs no interface change.

## 8. Recommended Next Step

Awaiting approval before Milestone 4 — the minimal PySide6 GUI (Dashboard, Episode Manager, Character Library, Asset Importer, Prompt Manager, and now an AI Generation/Review screen calling `AIOrchestrator` + `ApprovalService.list_pending_review_assets`) — calling these exact services and `AIOrchestrator`, and nothing else.
