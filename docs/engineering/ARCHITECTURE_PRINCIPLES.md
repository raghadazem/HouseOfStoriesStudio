# Architecture Principles

HouseOfStoriesStudio is a long-term commercial product, not a prototype.
Every architectural decision should be made as if the codebase will still be
read, extended, and depended on two years from now — because it is meant to
be. These principles apply to `app/core` and `app/gui` alike, and to any
future service (a real AI provider integration, a packaging step, a second
front end) built on top of them.

---

## 1. Clean Architecture: `core` never depends on `gui`

The foundational rule of this codebase, already enforced in practice since
Milestone 1 and checked mechanically by
`tests/unit/test_repo_structure.py::test_gui_never_imports_db_or_core_services_internals_directly`:

```
 ┌─────────────┐        ┌──────────────┐        ┌────────────┐
 │   gui/      │  calls │   services   │  uses  │   db/       │
 │ (PySide6)   │ ─────▶ │ (core logic) │ ─────▶ │ (SQLite)    │
 └─────────────┘        └──────────────┘        └────────────┘
```

- `app/core/` contains all business logic (models, services, db, AI
  orchestration, naming rules) and must never import anything from
  `app/gui/`.
- `app/gui/` is a thin presentation layer. It reaches services, the
  database, configuration, logging, and the AI orchestrator through exactly
  one object: `ApplicationContext` (`app/gui/context.py`) — see
  `docs/20_GUI_ARCHITECTURE.md` §1–2 for the full rationale and API.
- A page never constructs a service itself
  (`EpisodeService()` inside a GUI file is always wrong); it always goes
  through `ctx.episode_service`.
- The same discipline applies one layer down: `StorageService` is the only
  thing that touches the filesystem; `ApprovalService` is the only thing
  that writes an `ApprovalRecord`. **One concern, one owner** — this pattern
  repeats at every layer of the system, not just the GUI/core boundary.

**Why this matters commercially:** it keeps the business logic testable
without a GUI harness, keeps a free CLI (`app/cli`) usable against the exact
same services, and means a future front end (web, mobile, a different
desktop toolkit) would only require writing a new presentation layer — not
touching a single line of `app/core`.

---

## 2. Scalability

"Scalability" here does not mean web-scale — this is a single-user desktop
tool. It means: **the codebase scales with the product's ambition without
requiring a rewrite.**

- The AI layer (`app/core/ai/`) is provider-agnostic by construction: an
  `AIProvider` interface, a `PROVIDER_REGISTRY`, and an `AIOrchestrator` that
  the GUI is the only consumer of — see `docs/18_AI_ARCHITECTURE_PLAN.md`.
  Adding a real provider (OpenAI, Claude, a local model) means writing one
  new class against an existing interface, never touching the orchestrator,
  the GUI, or the workflow layer.
- The data layer uses Alembic migrations (`alembic/versions/`) from
  Milestone 2 onward specifically so schema changes are incremental and
  reversible, not destructive rewrites.
- Widgets and pages are built to be reused by *future* screens without
  modification — see [UI_DESIGN_PRINCIPLES.md](UI_DESIGN_PRINCIPLES.md) §7.

---

## 3. Maintainability

- Prefer explicit, typed, readable code over clever code. This codebase
  favors Pydantic/SQLAlchemy models with clear field names over ad-hoc
  dicts, and named design tokens over inline literals (see
  [UI_DESIGN_PRINCIPLES.md](UI_DESIGN_PRINCIPLES.md)).
- Every non-obvious decision gets recorded where a future reader will
  actually find it: a docstring/comment for a local *why*, a
  `docs/NN_..._STATUS.md` entry for a milestone-level *why* (see
  [ENGINEERING_WORKFLOW.md](ENGINEERING_WORKFLOW.md) §7).
- Typed exceptions at service boundaries (`DuplicateAssetError`,
  `InvalidPipelineTransition`, etc.) rather than bare `Exception` or silent
  `None` returns — a maintainer six months from now should be able to tell
  what can go wrong from the type signature.
- `tests/unit/test_repo_structure.py` exists specifically so structural
  drift (an accidentally deleted required module, an accidentally broken
  boundary) is caught immediately, not discovered months later.

---

## 4. Modularity

- `app/core/services/` is organized one service per concern
  (`episode_service`, `character_service`, `asset_import_service`,
  `storage_service`, `prompt_template_service`, `approval_service`,
  `license_service`, `export_package_service`, …). Each service has a single
  clear responsibility and is the sole owner of the resource it manages.
- `app/gui/widgets/` is a catalog of small, page-agnostic, independently
  testable components (`SummaryCard`, `EntityRow`, `FormDialog`, `Toast`,
  …) — see the full catalog in `docs/21_DESIGN_SYSTEM.md` §4. Pages compose
  these; they do not reimplement them.
- `app/core/ai/workflows/` follows the same pattern one level up: each
  generation task (`character_reference_workflow`, `scene_image_workflow`,
  `voice_line_workflow`) is its own module against a shared `Workflow` base.

---

## 5. Composition Over Duplication

**Before writing a new component, service, or workflow, check whether an
existing one can be extended or composed instead.** This is not a soft
suggestion — it is the standing rule this codebase already follows:

- A new card variant is a new `SummaryCard`/`ElevatedCard` mode, not a new
  card class.
- A new status pill is a new `StatusBadge` variant, not a new widget.
- A new list/grid screen reuses `EntityRow`/`EntityCard`/`ResponsiveGrid`
  and `PageHeader`/`ToolbarRow`, not a bespoke layout.
- A new create/edit screen is a new `FormDialog` subclass, not a new dialog
  base.
- A new generation task is a new `Workflow` subclass against the existing
  `AIProvider` interface, not a parallel pipeline.

`docs/21_DESIGN_SYSTEM.md` §5 states this explicitly for the widget
catalog: *"Milestone 4B should not need to add a second card widget, a
second dialog helper, or a second QSettings touchpoint."* That standard
applies to every future milestone, not just 4B.

---

## 6. Extension Before Creation

Concretely, before adding anything new, ask in this order:

1. Does an existing service/widget/module already do this? Use it.
2. Can an existing service/widget/module be extended (a new method, a new
   parameter, a new variant) to do this? Extend it.
3. Only if neither applies — create something new, and place it in the
   module structure this repo already uses (a new service in
   `app/core/services/`, a new reusable widget in `app/gui/widgets/`, a new
   page in `app/gui/pages/`, a new provider in `app/core/ai/providers/`).

Creating a new component when an existing one could have been extended is
itself a form of duplication, and is treated as such.

---

## 7. Technical Debt Policy

- **Never implement a shortcut that creates technical debt unless the
  founder explicitly requests it.** "Faster" is not sufficient justification
  on its own — see [PRODUCT_VISION.md](PRODUCT_VISION.md) on optimizing for
  quality over speed.
- When uncertain between a quick implementation and a better architecture,
  **prefer the better architecture.**
- If a shortcut is explicitly requested and taken, it is recorded — a
  comment at the point of the shortcut plus a note in that milestone's
  status doc — so it is discoverable later, not silently forgotten.
- Debt already recorded in `docs/07_DEVELOPMENT_PLAN.md` (§28 Missing
  Documents, §29 Open Questions, "Explicitly excluded from MVP") is
  deliberate, scoped deferral — not an invitation to add more without the
  same explicit reasoning.

---

## See Also

- [ENGINEERING_WORKFLOW.md](ENGINEERING_WORKFLOW.md) — how these principles
  are enforced through the milestone/commit/review process.
- [UI_DESIGN_PRINCIPLES.md](UI_DESIGN_PRINCIPLES.md) — the same
  composition-over-duplication discipline applied to the GUI layer
  specifically.
- [QUALITY_BAR.md](QUALITY_BAR.md) — the checklist that operationalizes
  these principles at the point a task is considered complete.
- `docs/20_GUI_ARCHITECTURE.md`, `docs/21_DESIGN_SYSTEM.md`,
  `docs/18_AI_ARCHITECTURE_PLAN.md` — the primary source documents this file
  summarizes; consult them for full detail and code examples.
