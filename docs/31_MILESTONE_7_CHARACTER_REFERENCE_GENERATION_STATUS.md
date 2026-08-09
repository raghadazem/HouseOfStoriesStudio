# 31 — Milestone 7 Status: Real Character Reference Generation

**Milestone:** 7 — the first real (paid, network) AI generation vertical slice: Character → CharacterVersion → Character Lock → real Gemini reference-image generation → candidate assets → review → approved reference → approved/active CharacterVersion.
**Builds on:** Milestone 3.5's AI architecture (`docs/18`) — `AIProvider`, `PromptEngine`, `Workflow`/`AIOrchestrator`, `MockProvider` — and Milestone 3's Character Lock (`docs/13`). Scene Image Generation is explicitly **out of scope**, deferred to Milestone 8.

---

## 1. What Changed

Before this milestone, `CharacterReferenceWorkflow` existed and worked end-to-end against `MockProvider`, but there was no real provider, no persistent record of a generation *attempt* (only the existing supplemental log file), no enforcement that a CharacterVersion becoming canon actually had a complete Character Lock, and no GUI for any of it.

This milestone adds, in order:

1. **`GeminiProvider`** — a real `AIProvider` using the official `google-genai` SDK, model configurable via environment variable, never hardcoded.
2. **`GenerationJob`** — a new persistent table that is the source of truth for one generation attempt's lifecycle and provenance (the existing log file remains supplemental/operational).
3. **`GenerationJobService`** — owns the job lifecycle (`PENDING → RUNNING → SUCCEEDED/FAILED`, plus honest cancellation semantics).
4. **`generation_runner`** — the one function that ties `GenerationJobService` + `AIOrchestrator` together for "generate N character-reference candidates," usable identically from the GUI worker thread or a future CLI command.
5. **Character Lock enforcement** — `approve_character_version` now requires `validate_character_lock().is_complete`; a new, narrower `validate_prompt_completeness()` gates real generation itself (see §3 for why these are two different checks).
6. **Full GUI**: CharacterVersion create/edit/submit/approve/reject/activate, a Generate Reference flow with a live candidate grid (approve/reject/retry/cancel), and a Gemini status section in Settings.

## 2. Provider: `GeminiProvider`

`app/core/ai/providers/gemini_provider.py`. Registered in `PROVIDER_REGISTRY` alongside `MockProvider` — per `docs/18`, adding a real provider is exactly "one new file, one registry entry," confirmed true here.

- **SDK:** official `google-genai` (added to `pyproject.toml` dependencies; no unofficial wrapper).
- **Model is configuration, never hardcoded**: constructor `model` argument → `HOS_GEMINI_IMAGE_MODEL` env var → default `gemini-3.1-flash-image` (module constant `DEFAULT_MODEL`). Switching to the approved fallback (`gemini-2.5-flash-image`) or future high-quality tier (`gemini-3-pro-image`) is a config change only, per the founder's explicit requirement.
- **Credential**: `GEMINI_API_KEY` environment variable. Never stored in the database, source, tests, fixtures, or `QSettings`.
- **Reference images**: `GenerationRequest.reference_asset_paths` (managed-relative paths) are resolved through `StorageService.resolve_managed_path` — the same path every other reader of managed files uses — and sent as `types.Part.from_bytes(...)`, never a raw filesystem path.
- **Error mapping** (`app/core/ai/exceptions.py` extended): `ProviderRequestError` is now a base class with six specific subclasses — `ProviderAuthenticationError`, `ProviderRateLimitError`, `ProviderTimeoutError`, `ProviderRejectionError` (safety/policy refusal), `ProviderMalformedResponseError`, `ProviderNetworkError` — mapped from `google.genai.errors.ClientError`/`ServerError` HTTP codes, `httpx` timeout/network exceptions, and response-level safety blocks/non-`STOP` finish reasons. The GUI never parses a provider-specific string; it catches these types.
- **Cost**: `GenerationResult` carries no cost figure — Gemini's response reports token usage, not a dollar amount, and converting that ourselves would be exactly the "invented/estimated cost" the founder ruled out. `GenerationJob.cost_usd` stays `NULL` for every Gemini job today.

## 3. Character Lock: Two Checks, Not One

`CharacterVersionService.validate_character_lock()` (existing, unchanged behavior) remains the single source of truth for full lock completeness: 5 prompt fields + at least one approved reference asset.

A new `validate_prompt_completeness()` was factored out of it — the same 5 prompt fields, **without** the reference-asset requirement — because requiring an approved reference before allowing generation would make it impossible to ever produce a version's *first* reference image. `validate_character_lock()` now composes `validate_prompt_completeness()` plus the reference check, so the field list is defined exactly once.

Enforcement, at two points:

- **`CharacterVersionService.approve_character_version`** now raises the new `CharacterLockIncompleteError` (in `app/core/services/exceptions.py`, carries `missing_fields`) if `validate_character_lock()` isn't complete. A version can no longer reach `approved_canon` — and therefore can never become `active` either, since `set_active_character_version` already required `approved_canon` — with an incomplete lock.
- **`CharacterReferenceWorkflow.run()`** requires `validate_prompt_completeness()` before calling `ctx.provider.generate()` — enforced identically for every provider, including `MockProvider`. This is deliberate: the rule is "production generation must never consume an unfinished draft," not "the provider is real vs. mock" — there is no `if provider != mock_provider` anywhere in this codebase. `tests/unit/test_ai_workflows.py::test_character_reference_workflow_rejects_incomplete_character_lock` exercises this exact rule with `MockProvider`.

## 4. Database

One migration, `70415d0caa93` (revises `29891cfbf82f`), additive only:

- New table `generation_jobs`: `id`, `workflow_name`, `provider_name`, `provider_model`, `status` (`GenerationJobStatus`, native_enum=False), `batch_id` (indexed, not a FK — a grouping concept), `prompt_text`/`negative_prompt_text`/`parameters`/`reference_asset_ids` (immutable snapshot — see §5), `character_id`/`character_version_id`/`episode_id`/`scene_id`/`short_id` (nullable FKs, SET NULL), `requested_at`/`started_at`/`completed_at`, `error_category`/`error_message`, `result_asset_id` (FK → `assets.id`, SET NULL), `retry_of_job_id` (self-FK, SET NULL), `cost_usd` (`Numeric(10,4)`, nullable).
- `assets` gains one nullable column: `generation_job_id` (FK → `generation_jobs.id`, SET NULL). Existing/manually-imported assets are unaffected (`NULL`).
- `assets` ↔ `generation_jobs` is a genuine mutual-FK pair (a job points at the asset it produced; an asset points at the job that produced it) — SQLAlchemy logs a table-sort warning on autogenerate because of this, which is expected and harmless: the cycle is broken correctly at the DDL level (`generation_jobs.result_asset_id` is created inline since `assets` already exists; `assets.generation_job_id` is added via a later `ALTER TABLE`, after `generation_jobs` exists).

Verified: clean `alembic upgrade head` from empty, `alembic upgrade head` against the real, pre-existing development database (Episode 001 content from Milestone 6), `alembic check` (no drift both times), `alembic downgrade -1` then re-`upgrade head` (idempotent), `alembic downgrade base` (drops every table cleanly) — all covered by `tests/integration/test_migrations.py` (updated `EXPECTED_TABLES`).

## 5. `GenerationJob` Lifecycle and Honest Cancellation

Owned exclusively by `GenerationJobService` (`app/core/ai/generation_job_service.py`) — Qt/QThread never touches a status transition; the GUI worker only invokes core operations and emits signals of what already happened.

```
PENDING --------------------------> CANCELLED   (cancelled before any provider call)
   |
   v
RUNNING ----> SUCCEEDED
   |
   +--------> FAILED
   |
   +--------> CANCEL_REQUESTED ----> CANCELLED  (once the in-flight call resolves)
```

A provider call, once started, cannot be interrupted mid-flight (no server-side cancel API assumed) — so a job is never reported `CANCELLED` while its call could still be running:

- `PENDING → CANCELLED` is immediate and direct — no provider call was ever made.
- `RUNNING → CANCEL_REQUESTED` records the *request* only; the in-flight call keeps running because nothing in this application can stop it.
- `CANCEL_REQUESTED → CANCELLED` (`finalize_cancelled_after_running`) only happens once the caller has observed the call actually return — successfully or not. A result that arrives after cancellation was requested is never silently promoted to `SUCCEEDED`: `result_asset_id` is still recorded (the asset genuinely exists — money may have been spent) but the job stays `CANCELLED`, and review/candidate-grid queries (which only surface `SUCCEEDED` jobs) never offer it.

**Provenance** is an immutable snapshot, never re-derived later from a live row that could have changed: `prompt_text`/`negative_prompt_text`/`parameters` are exactly what was sent, captured once per job. `reference_asset_ids` stores identifiers of the (already checksum-verified, immutable) `Asset` rows used — never a second copy of the bytes.

**Batching** (`generation_runner.run_character_reference_batch`, `app/core/ai/generation_runner.py`): one logical "generate N candidates" request creates N `GenerationJob` rows sharing one `batch_id` — never assumes a provider can return multiple candidates from one call; one provider call per job. Each candidate gets a distinguishing `candidate_index` parameter so `MockProvider` (a pure function of its request) doesn't produce checksum-colliding output for every candidate after the first — a real provider naturally varies its output and simply ignores the key.

**Commits, not just flushes**: unlike every other service (which only `flush()`, leaving `commit()` to the caller's `session_scope()`), `generation_runner` commits after each durable state transition — the second documented exception to that rule (the first being `AssetImportService.import_asset`). A `GenerationJob` exists specifically so a crash or a cross-thread cancellation mid-batch still leaves a truthful, queryable row behind; that guarantee is worthless if the row is only visible once the whole batch (including slow, failable network calls) finishes.

**Retry**: manual only, no automatic paid retries. `GenerationJobService.retry_job` creates a new `PENDING` job copying the original's immutable provenance, linked via `retry_of_job_id`, never mutating the original. The GUI's retry path re-renders through the normal prompt-template path (same `prompt_template_id`/`variables`/`character_version_id` as the original request) rather than replaying frozen bytes through a second execution path — a deliberate simplification consistent with leaving `AIOrchestrator.run_workflow`'s signature untouched (see §8); within one GUI review session the source data is unchanged, so the two are for all practical purposes the same request. The retried job stays grouped in the *original* batch (`batch_id` is inherited), so the candidate grid keeps showing it with its siblings.

## 6. `AIOrchestrator`: One New Public Method, One Real Bug Fixed

- `AIOrchestrator.get_provider(name)` — a thin public wrapper around the existing private provider cache, so `generation_runner` can read a real provider's `.model` for `GenerationJob` provenance using the exact same cached instance that will run `generate()`, rather than constructing a second one.
- **`ApplicationContext.ai_orchestrator` was rebinding workflows incorrectly** — discovered while wiring the first GUI-reachable real generation path. Every `Workflow` defaults its `AssetImportService` to the process-wide cached `get_config()` when none is given (correct for the CLI/tests, which bind that cache explicitly); `AIOrchestrator`'s registry always zero-arg-constructs workflow classes, so the GUI's own `AppConfig` was never actually reaching them. Harmless while only `MockProvider` existed (nothing GUI-reachable ever hit real generation); a real correctness bug now. Fixed by rebinding each workflow class with a zero-arg `__init__` closing over `self.asset_import_service` — the same pattern `asset_import_service` itself already uses.

## 7. GUI

- **`app/gui/pages/character_version_workflow.py`** (new, ~700 lines) — kept out of `characters_page.py` deliberately: this is a large, self-contained workflow layered on top of the roster page, not a rewrite of it. Every dialog reuses the existing `FormDialog`/`StatusBadge`/`ResponsiveGrid` design system; no new visual language.
  - `_EditCharacterVersionDialog` — create/edit a draft's fields (visual summary, master prompt, negative prompt, color palette, allowed accessories, relative height, outfit version).
  - `_CharacterVersionDetailDialog` — the action hub: live Character Lock readiness (exact missing fields, human-readable), approved-reference count, and every lifecycle action (Edit, Generate Reference, Submit for Review, Approve/Reject, Set Active) gated by the version's actual status.
  - `_GenerateReferenceDialog` — provider picker (only configured providers, via `list_available_providers`), prompt-template picker (existing `CHARACTER`/`IMAGE` templates — the Prompt-template path is left exactly as Milestone 3.5 built it, per the founder's explicit "don't redesign it" decision), candidate count (1–4), and a live final-prompt preview that reuses `generation_runner.render_preview` — the same call the batch itself uses, so the preview can never drift from what's actually sent.
  - `_CandidateReviewDialog` — owns the `GenerationWorker` for the initial batch and every manual retry; a `ResponsiveGrid` of candidate tiles (thumbnail, provider/model, status badge, generation time, error message if any) with per-candidate Approve/Reject/Retry/Cancel, driven entirely by re-querying the database after every worker signal — never holding a stale in-memory copy.
  - `create_character_version` / `open_character_version_detail` — the two public entry points `characters_page.py` calls.
- **`app/gui/workers/generation_worker.py`** (new) — `GenerationWorker(QThread)`. Opens and closes its own database session inside `run()` (never reuses the caller's, never shared across threads). Emits `JobSnapshot` — a plain, frozen dataclass, never the live SQLAlchemy `GenerationJob` object, which would be attached to a session that's closed by the time a Qt-queued slot runs on the main thread. `batch_failed` carries an already-safe, human-readable message (a `ServiceError`'s `str()`, or a generic fallback) — never a raw traceback.
- **`characters_page.py`** — the version list inside `_CharacterDetailDialog` is now real `EntityRow`s (clickable → opens the detail dialog) instead of static labels, plus a "+ New Version" action. The dialog re-renders its own version list in place after any nested action reports a change, rather than requiring the user to close and reopen it.
- **`settings_page.py`** — new "Google Gemini Image" section, following the exact `_info_row(label, value, badge_variant=...)` pattern the existing AI Providers section already uses (`success` when configured, `neutral` — not `danger`/`warning` — when not, matching this codebase's established convention). Shows Status (Configured/Not configured) and the configured Model; guidance text names the `GEMINI_API_KEY`/`HOS_GEMINI_IMAGE_MODEL` environment variables. **No editable secret field exists, and the key's value is never displayed** — confirmed by both an automated test and manual verification (§10).

## 8. What Was Deliberately Not Changed

- **`AIOrchestrator.run_workflow`'s signature** — untouched, including `prompt_template_id`. The founder's explicit decision was to leave the current prompt-template path intact for Milestone 7 and reconcile `Scene.prompt_text`/`PromptComposerService` only in Milestone 8, against real Episode 001 scenes.
- **Scene Image Generation** — no `SceneImageWorkflow` GUI, no scene-generation policy work. Explicitly Milestone 8.
- **No provider-identity business logic** — confirmed no `if provider_name != "mock_provider"` (or equivalent) exists anywhere; the production-generation policy in §3 is enforced identically regardless of provider.

## 9. Testing

All automated tests use `MockProvider` or an injected fake `google-genai` client/transport — **no automated test calls the real Gemini API.**

- `tests/unit/test_gemini_provider.py` (21 tests) — configuration, model resolution (constructor/env/default), success path (temp file, correct bytes, correct extension), and every error-mapping branch (auth, rate limit, generic client error, server error, timeout, network error, prompt-level safety block, non-`STOP` finish reason, no candidates, no image part) — all via a fake `client_factory`, never `google-genai`'s real transport.
- `tests/unit/test_generation_job_service.py` (22 tests) — every lifecycle transition, both honest-cancellation branches (discarded-success and failed-after-cancel-requested), retry lineage, batch/status query filtering, `NotFoundError`/`InvalidTransitionError` guards.
- `tests/unit/test_generation_runner.py` (12 tests) — fail-fast pre-checks (candidate-count range, incomplete lock, unconfigured provider — no job rows created), batch grouping (shared `batch_id`, distinct assets), provider-model provenance, provider-failure handling, both cancellation scenarios (cancelled-while-queued and cancelled-mid-flight, the latter via a provider double that requests cancellation on its own thread-of-control mid-`generate()`), retry `batch_id` inheritance.
- `tests/unit/test_character_version_service.py` — extended with `validate_prompt_completeness` tests and `approve_character_version`'s new `CharacterLockIncompleteError` guard (both "missing prompt fields" and "prompt-complete but no reference yet" cases); three pre-existing tests updated since they previously approved versions with empty lock fields, which the new guard now correctly rejects.
- `tests/unit/test_ai_workflows.py` — new production-policy test (`MockProvider`, incomplete version → `CharacterLockIncompleteError`).
- `tests/integration/test_character_reference_generation_flow.py` — the full vertical slice against the real service layer: Character → CharacterVersion (locked but no reference) → real generation batch (2 candidates) → both candidates land as draft assets tied to their `GenerationJob` → approve one, reject the other → promote the approved one to `CharacterReference` (explicit, separate action) → lock now complete → submit → approve → activate.
- `tests/integration/test_production_checklist_service.py` / `tests/integration/test_migrations.py` — updated for the new lock-completeness requirement and the new table, respectively.
- `tests/gui/test_generation_worker.py` (3 tests) — the worker genuinely runs `run()` on a different OS thread (verified via a subclass recording `threading.get_ident()` inside `run()`, not by relying on Qt's signal-marshaling behavior — see implementation note below), emits correct snapshots, and turns both kinds of pre-flight failure into `batch_failed`.
- `tests/gui/test_character_version_workflow.py` (9 tests) and `tests/gui/test_settings_page.py` (3 new tests) — full dialog flows including a real `GenerationWorker`/QThread run waited on via `qtbot.waitSignal`, retry-after-failure, cancel-of-a-terminal-job (proving the domain error surfaces via a non-blocking fake `show_error` rather than crashing or hanging on a real modal `QMessageBox`), and the Gemini Settings section's configured/not-configured/model-override states.

**Implementation note for future readers**: Qt automatically marshals a signal connected to a plain Python callable back onto the thread where `.connect()` was called (the GUI/main thread here), even when `.emit()` happens on a worker thread — this is the correct, desired behavior for GUI safety (it's why `_CandidateReviewDialog._on_job_updated` can safely touch widgets), but it means asserting "this callback ran on a different thread" by capturing `threading.get_ident()` *inside a connected slot* doesn't actually prove the worker ran in the background — it proves Qt marshaled the call, which happens regardless. The thread-identity test above captures the ID from inside `run()` itself instead.

Also found and fixed as a **test-writing footgun, not a production bug**: `QComboBox.findData()` compares Qt's stored `QVariant` userData by identity for opaque Python objects (e.g. two value-equal but separately-fetched `uuid.UUID` instances from two different ORM sessions do not match), so combo-box-driven GUI tests use a small `_find_combo_index()` helper that compares by Python `==` instead.

**Offline suite**: 412 core tests (`pytest --ignore=tests/gui`) + 210 GUI tests (`pytest tests/gui`, `QT_QPA_PLATFORM=offscreen`) = **622 passed**, 0 failed. `ruff check app/ tests/`: clean.

## 10. Manual Verification

### 10a. Everything not requiring the real Gemini API — PASSED

Driven end-to-end against a real, isolated `ApplicationContext` + real `MainWindow` (never the actual project's `production/`/`data/` folders), through the real page/dialog classes, `GEMINI_API_KEY` explicitly unset:

1. Settings → Google Gemini Image section reads **"Not configured"**, model **`gemini-3.1-flash-image`**, guidance names `GEMINI_API_KEY` — confirmed via direct text assertions on the live widgets. No editable secret field exists in the section at all.
2. Character "Melissa" created; a draft CharacterVersion created with complete prompt fields via the real `_EditCharacterVersionDialog`.
3. `validate_character_lock` correctly reports the single remaining gap (`approved_reference_assets`) before any reference exists.
4. Real Generate Reference flow (2 candidates, `mock_provider`, through the actual `GenerationWorker`/QThread) completed; both `GenerationJob` rows reached `SUCCEEDED` with `provider_name="mock_provider"`.
5. One candidate approved and explicitly promoted to `CharacterReference`; Character Lock then reports complete.
6. Version submitted → approved → set active through the real detail dialog; final state confirmed as `approved_canon` and the character's `active_version_id` pointing at it.
7. Searched the resulting SQLite database (every table/column), the log directory, and the `QSettings` ini file for anything resembling `GEMINI_API_KEY` — **none found anywhere**, consistent with the env-var-only secrets policy.

(Screenshots were attempted but discarded: this sandboxed session's Qt offscreen platform has zero font families registered — `QFontDatabase.families()` returns `[]` — so captured images rendered as unreadable placeholder glyphs, a sandbox font-availability artifact unrelated to the application. The verification above was done via direct widget-state/database assertions instead, which don't depend on font rendering and are the stronger evidence in any case.)

### 10b. Real Gemini API call — **BLOCKED — GEMINI_API_KEY not configured**

No `GEMINI_API_KEY` exists in this environment, the repository, or any config file reachable from this session. Per the founder's explicit instruction, this is reported truthfully rather than faked. `GeminiProvider.is_configured()` correctly returns `False` in this state (confirmed above), and `AIOrchestrator`/`generation_runner` correctly refuse to run (`ProviderNotConfiguredError`) rather than silently doing nothing — also covered by automated tests.

**To complete this verification yourself:**

1. Get a Gemini API key from Google AI Studio, on a **paid** tier (per your own instruction: do not use the free tier for anything that could become production content).
2. Set the environment variable before launching the app, e.g. (PowerShell): `$env:GEMINI_API_KEY = "your-key-here"` — or add it to your shell profile / a machine-level environment variable for persistence. Do not put it in any file inside this repository.
3. Optionally set `HOS_GEMINI_IMAGE_MODEL` to override the default (`gemini-3.1-flash-image`) — e.g. to test the approved fallback `gemini-2.5-flash-image`.
4. Launch the app (`hos-gui` or `python -m app.gui.app`) and open **Settings** — the Gemini section should now read "Configured."
5. Create (or open) a character with a draft CharacterVersion that has all five prompt fields filled in (Visual summary, Master prompt, Negative prompt, Color palette, Relative height).
6. From the version's detail dialog, click **Generate Reference**, pick **gemini** as the provider, choose **1** candidate (smallest practical call — do not batch-test with 4 on the first real run), and confirm.
7. Verify: the call returns a real image, a `GenerationJob` row exists with `status=succeeded`, `provider_name=gemini`, `provider_model` matching what Settings showed, and the candidate appears as a draft `Asset` in the review grid.
8. Check `data/logs/` and the database directly to confirm no part of the API key appears anywhere.
9. Only once that single-candidate check is confirmed, optionally try a real character-reference-conditioned generation (an approved reference image already attached to the version) to validate reference-image conditioning end to end, per the original provider-research recommendation.

## 11. Milestone 8 Handoff

- `SceneImageWorkflow` already exists (Milestone 3.5) and is now correctly config-bound via the `ApplicationContext.ai_orchestrator` fix (§6) — ready to receive real generation the same way `CharacterReferenceWorkflow` just did.
- `generation_runner.py`'s shape (fail-fast pre-checks, batch/job creation, honest cancellation) is intentionally not character-reference-specific in its *architecture*, only in its one public function's name and workflow choice — a `run_scene_image_batch` following the identical pattern is the expected extension point, not a redesign.
- The `AIOrchestrator.run_workflow(prompt_template_id=...)` / `Scene.prompt_text` / `PromptComposerService` reconciliation the founder deferred in Milestone 7 §7 of the original decisions is now Milestone 8's first real design question, to be settled against actual Episode 001 scenes rather than speculatively here.

## 12. Acceptance Criteria

| # | Criterion | Status |
|---|---|---|
| 1 | CharacterVersion fully preparable through the GUI | ✅ |
| 2 | Character Lock completeness enforced | ✅ (`approve_character_version`) |
| 3 | Real Gemini provider integrated behind `AIProvider` | ✅ |
| 4 | Real generation runs asynchronously, GUI never freezes | ✅ (`GenerationWorker`/QThread) |
| 5 | Every attempt creates persistent `GenerationJob` provenance | ✅ |
| 6 | Candidate batches represented correctly | ✅ (`batch_id` grouping, one job per candidate) |
| 7 | Candidate assets arrive as DRAFT | ✅ |
| 8 | Human review required | ✅ |
| 9 | Approved candidate can become `CharacterReference` | ✅ (explicit, separate action) |
| 10 | Approved complete version can become active | ✅ |
| 11 | Missing/incomplete versions cannot enter production | ✅ |
| 12 | Retry preserves history | ✅ (`retry_of_job_id`, original never mutated) |
| 13 | Cancellation semantics truthful | ✅ (§5) |
| 14 | No API key persisted or logged | ✅ (verified §10a) |
| 15 | All automated tests offline | ✅ |
| 16 | Full pytest passes | ✅ (622 passed) |
| 17 | Ruff passes | ✅ |
| 18 | Alembic has no drift | ✅ |
| 19 | Manual Windows verification passes, or blocker truthfully reported | ✅ non-API parts pass; real-API call **BLOCKED** (§10b) |
