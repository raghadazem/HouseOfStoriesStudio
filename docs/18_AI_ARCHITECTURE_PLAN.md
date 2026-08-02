# 18 — AI Architecture & Workflow Engine Plan (Milestone 3.5)

**Status:** Draft for founder approval — no implementation yet.
**Depends on:** Milestone 3 (`docs/13`–`docs/17`).
**Precedes:** Milestone 4 (GUI).

---

## 1. Why This Milestone Exists

The founder's own reasoning (recorded here so it's not lost):

> If we build the GUI now, in a month we'll want to add AI provider switching, workflows, and orchestration — and we'll have to rewrite half the code. If we add the AI/orchestrator layer first, the GUI can talk only to these services, without depending on any specific provider.

This is the same principle Milestone 3 already followed for storage (`StorageService` is the only thing that touches the filesystem) and approvals (`ApprovalService` is the only thing that writes an `ApprovalRecord`). Milestone 3.5 applies it one layer up: **the GUI should never import a provider SDK, and never know which AI vendor is in use.**

**Explicitly not in scope:** no real generation happens in this milestone. No provider makes a real network call. No paid API is integrated. This is architecture only — an interface every future provider must satisfy, one fully-working reference implementation (`MockProvider`) to build and test workflows against, and the orchestration layer that will one day sit between the GUI and whichever real providers the founder chooses to wire up.

## 2. A Schema Observation Worth Naming

Milestones 2–3 already anticipated most of this without knowing it: `Asset.prompt_used_id` (which `PromptTemplate` produced this file) and `Asset.source_tool` (free text — which external tool/provider produced it) already exist. **This milestone needs no new database tables.** Generated assets flow through the exact same `AssetImportService.import_asset()` every manually-imported asset already uses, just with the source file coming from a provider call instead of a human's download folder, and `source_tool` set to the provider's name (e.g. `"mock_provider"`, `"openai_dall_e_3"`) instead of something like `"bing_image_creator"`.

## 3. Architecture Overview

```
                    ┌─────────────────────┐
                    │   AIOrchestrator      │   top-level entry point
                    └──────────┬───────────┘
                               │
              ┌────────────────┼────────────────┐
              ▼                ▼                 ▼
      ┌───────────────┐ ┌─────────────┐  ┌───────────────┐
      │ PromptEngine   │ │  Workflow    │  │ Provider       │
      │ (wraps existing│ │  (one per    │  │ Registry       │
      │ PromptTemplate │ │  generation  │  │ (name -> class)│
      │ Service)       │ │  task)       │  │                │
      └───────────────┘ └──────┬───────┘  └───────┬────────┘
                                │                   │
                                ▼                   ▼
                        ┌───────────────────────────────┐
                        │      AIProvider (interface)     │
                        │  MockProvider | OpenAIProvider   │
                        │  ClaudeProvider | GeminiProvider │
                        │  SunoProvider | GoogleTTSProvider│
                        └───────────────┬───────────────┘
                                        │ generated file (temp path)
                                        ▼
                        ┌───────────────────────────────┐
                        │   AssetImportService (existing) │  → Asset row, approval_status=draft
                        └───────────────┬───────────────┘
                                        │
                                        ▼
                        ┌───────────────────────────────┐
                        │  ApprovalService (existing)     │  "Review Queue" = query for draft assets
                        └───────────────────────────────┘
```

Nothing below the `AIProvider` line is new work; nothing above the `AssetImportService` line touches the filesystem or database directly.

## 4. Proposed Module Layout

```
app/core/ai/
├── __init__.py
├── exceptions.py            # ProviderError, ProviderNotConfiguredError, WorkflowError
├── provider_interface.py    # AIProvider ABC + GenerationRequest/GenerationResult dataclasses
├── providers/
│   ├── __init__.py          # PROVIDER_REGISTRY: dict[str, type[AIProvider]]
│   ├── mock_provider.py     # fully implemented, deterministic
│   ├── openai_provider.py   # structural stub
│   ├── claude_provider.py   # structural stub
│   ├── gemini_provider.py   # structural stub
│   ├── suno_provider.py     # structural stub
│   └── google_tts_provider.py  # structural stub
├── prompt_engine.py         # PromptEngine — resolves + renders a prompt for a generation request
├── workflows/
│   ├── __init__.py
│   ├── base.py               # Workflow ABC, WorkflowContext, WorkflowResult
│   ├── character_reference_workflow.py
│   ├── scene_image_workflow.py
│   └── voice_line_workflow.py
└── orchestrator.py          # AIOrchestrator — the GUI's one entry point into all of this
```

`app/gui/` (Milestone 4) will only ever import `AIOrchestrator` and read-only query helpers (e.g. "list pending review assets") — never a provider class directly.

## 5. The `AIProvider` Interface

```python
class GenerationRequest:
    modality: Literal["text", "image", "video", "voice", "song"]
    prompt_text: str                 # already-rendered, from PromptEngine
    negative_prompt_text: str | None
    reference_asset_paths: list[str]  # managed-relative paths, e.g. character lock reference images
    parameters: dict[str, object]     # provider-specific knobs (size, voice_id, duration, ...); optional

class GenerationResult:
    output_path: Path                 # a local temp file the orchestrator hands to AssetImportService
    provider_name: str
    raw_response_summary: str | None  # short, loggable — never the full raw payload

class AIProvider(ABC):
    name: ClassVar[str]
    supported_modalities: ClassVar[set[str]]

    def is_configured(self) -> bool: ...
    def generate(self, request: GenerationRequest) -> GenerationResult: ...
```

- `is_configured()` lets the orchestrator/GUI show "not available" instead of a stack trace.
- Every real provider's `generate()` in this milestone raises `ProviderNotConfiguredError` unconditionally — no network code exists yet. `is_configured()` always returns `False` for them.
- `MockProvider.generate()` is fully implemented: for `image`/`video`/`thumbnail` it copies a tiny placeholder file from `app/core/ai/providers/_fixtures/`; for `text`/`voice`/`song` it returns deterministic generated text/silence based on a hash of the prompt, so the same prompt always produces the same result (useful for tests and for exercising workflows end-to-end without any real generation).

## 6. Providers: Proposed Scope (my answer to the open question)

**Build all 6 as real files now** (interface + `MockProvider` fully working; `OpenAIProvider`/`ClaudeProvider`/`GeminiProvider`/`SunoProvider`/`GoogleTTSProvider` as structural stubs), rather than interface + Mock only. Reasoning: the stub bodies are a handful of lines each (`is_configured` → `False`, `generate` → raise), so the marginal cost is small, while it lets the GUI's provider-picker (Milestone 4) show the full intended list today with an honest "not configured" state, instead of the list itself needing a code change later. Flagging this as a decision to confirm, not assuming it's obviously right.

## 7. Prompt Engine

Thin wrapper around the existing `PromptTemplateService` — does not duplicate rendering logic:

```python
class PromptEngine:
    def build_request(
        self, session, *, workflow_name: str, prompt_template_id: UUID,
        variables: dict, character_version_id: UUID | None = None,
    ) -> GenerationRequest:
        ...
```

If `character_version_id` is given, it pulls `master_prompt`/`negative_prompt`/`color_palette`/reference asset paths from `CharacterVersionService` (already built) and merges them into the rendered template's variables — this is the actual mechanism for "Character Lock" consistency: the workflow can't build an image/video prompt for a character without the orchestrator handing it that character's locked prompt block.

## 8. Workflow Engine: Proposed Scope (my answer to the open question)

**Fixed, code-defined workflow classes — not a generic config/DSL-driven engine.** A generic engine (steps described in JSON/DB, arbitrary branching) is real complexity with no validated need yet; three concrete workflows cover everything Milestone 3.5 needs to prove the architecture. If a fourth or fifth workflow later reveals a genuine common shape worth generalizing, that's a cheap refactor once real usage patterns exist — premature generality here would be exactly the kind of complexity the project's stated principles warn against.

```python
class WorkflowContext:
    session: Session
    provider: AIProvider
    episode_id: UUID | None
    scene_id: UUID | None
    character_version_id: UUID | None
    extra: dict

class WorkflowResult:
    asset: Asset            # the row AssetImportService created
    generation_request: GenerationRequest
    generation_result: GenerationResult

class Workflow(ABC):
    name: ClassVar[str]
    def run(self, ctx: WorkflowContext) -> WorkflowResult: ...
```

Three workflows to start:

| Workflow | Steps |
|---|---|
| `CharacterReferenceWorkflow` | PromptEngine (character-locked prompt) → Provider.generate(image) → AssetImportService.import_asset(role=None, character_version_id=...) — lands in the same review queue as a manually imported reference image; **does not** auto-create a `CharacterReference` row (that stays an explicit human action via `CharacterVersionService.add_character_reference`, per the existing "only approved assets" rule). |
| `SceneImageWorkflow` | PromptEngine (scene + style-lock + any character-locked blocks for characters in the scene) → Provider.generate(image) → AssetImportService.import_asset(episode_id=..., scene_id=...). |
| `VoiceLineWorkflow` | PromptEngine (line text + character voice profile notes) → Provider.generate(voice) → AssetImportService.import_asset(episode_id=..., character_version_id=...). |

Deferred (not built this milestone, added the same way once needed): song generation workflow, thumbnail workflow, video workflow. The interface already supports all five modalities — adding a workflow later is additive, not a rework.

## 9. AI Orchestrator

The one class the GUI (and the CLI, for testing) will call:

```python
class AIOrchestrator:
    def __init__(self, provider_registry: dict[str, type[AIProvider]] | None = None): ...

    def list_available_providers(self, modality: str) -> list[str]:
        """Providers that both support this modality and report is_configured()."""

    def run_workflow(
        self, session: Session, workflow_name: str, *, provider_name: str, **context_kwargs,
    ) -> WorkflowResult:
        """Look up the workflow and provider, build a WorkflowContext, run it."""
```

`AssetImportService.import_asset` already owns its own transaction (Milestone 3, `docs/14`) — `run_workflow` does not add another transaction layer around it; the workflow's DB write is exactly one `import_asset` call, same guarantees as a manual import.

## 10. Review Queue

No new concept. "Pending review" is simply `Asset.approval_status == draft`. Milestone 3.5 adds one small, obviously-scoped read-only helper (proposed location: a `list_pending_review_assets(session, *, episode_id=None)` function on `ApprovalService` or a new tiny `review_queue.py` — leaning toward adding it to `ApprovalService` since it's a query over the same approval-state concept that service already owns) rather than a new service class for a single query method.

## 11. Generation Logging: Open Question

Should every `run_workflow()` call be recorded somewhere (provider used, success/failure, timestamp), beyond what's already implied by the resulting `Asset` row (or lack of one, on failure)? Two options:
- **(A) Log only** — write to the existing `app/logging_setup.py` logger; no new table. Simplest, consistent with "avoid unnecessary complexity."
- **(B) Persistent `GenerationLog` table** — useful later for cost/usage tracking once real providers are wired up, but adds a table with no consumer yet.

**My recommendation: (A) for now**, revisit (B) once a real provider is actually wired up and cost-per-call becomes a real question worth tracking in the database rather than the log file.

## 12. Exceptions

Extends the Milestone 3 hierarchy rather than starting a new one:

```
ServiceError (existing)
├── ProviderNotConfiguredError   (a provider's generate() was called without being set up)
├── ProviderRequestError          (a real provider call failed — unused until real providers exist)
└── WorkflowError                  (a workflow step failed for a reason not covered above)
```

## 13. Testing Strategy

Every workflow test runs against `MockProvider` — deterministic, no network, no real generation, matching the rest of the test suite's style. Coverage to add: provider interface contract (every stub reports `is_configured() is False` and raises on `generate()`), each of the 3 workflows end-to-end (prompt → mock generation → real `Asset` row via the real `AssetImportService`, landing in `draft` with correct `source_tool`/`prompt_used_id`/associations), `AIOrchestrator.run_workflow` provider/workflow lookup errors, and `list_pending_review_assets`.

## 14. What This Milestone Explicitly Does Not Do

- No real network call to any AI provider.
- No paid API integration.
- No image/video/voice/song is actually generated by anything other than `MockProvider`'s deterministic placeholders.
- No GUI code.
- No new database tables (per §2).
- No automatic promotion of a generated asset to "approved" or "character reference" — every generated asset still requires the same explicit human review Milestone 3 already built.

## 15. Open Questions for Approval

1. **Provider scope** (§6): build all 6 provider files now (stubs for 5), or interface + `MockProvider` only, adding real stub files when a provider is actually chosen?
2. **Workflow engine shape** (§8): fixed code-defined workflows (proposed), or do you want the generic/config-driven engine now even though nothing requires it yet?
3. **Generation logging** (§11): log-file only (recommended), or a persistent `GenerationLog` table starting now?
4. **Workflow set**: are the 3 proposed workflows (character reference image, scene image, voice line) the right starting set, or would you rather start with a different one (e.g. thumbnail, or song)?
5. **Review queue location** (§10): a method on the existing `ApprovalService`, or a new small dedicated module — any preference?

Once these are confirmed, implementation proceeds the same way Milestones 1–3 did: build, test, verify manually, document, commit locally, stop for your review before Milestone 4.
