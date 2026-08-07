# Contributing to HouseOfStoriesStudio

HouseOfStoriesStudio is a long-term commercial product
([docs/engineering/PRODUCT_VISION.md](docs/engineering/PRODUCT_VISION.md)),
developed with the discipline of a small commercial team even while it has a
single contributor today. This document is the practical guide to working in
the repository; the full standards it's built on live in
[docs/engineering/](docs/engineering/) and are linked throughout.

---

## Repository Structure

```
app/            Python application source (core business logic + GUI + CLI)
├── core/       Framework-agnostic business logic — never imports app/gui
├── gui/        PySide6 desktop UI — a thin layer over app/core, reached
│               only through ApplicationContext
└── cli/        Command-line entry points using the same core services
production/     The studio's actual creative content (characters, episodes,
                prompts, world, brand, channel) — text/metadata is tracked
                in Git, large binaries are not (see .gitignore)
docs/           Project documentation
├── 00-26_*.md  Numbered project docs: creative bibles, architecture plans,
│               and per-milestone status reports, in chronological order
└── engineering/  Standing engineering standards (this file's companion set)
tests/          Automated tests, mirroring app/'s layout
├── unit/         app/core models and services in isolation
├── integration/  cross-service flows against a real temp database
└── gui/          app/gui via pytest-qt, run headless
data/           Runtime data (SQLite DB, logs) — git-ignored, not committed
alembic/        Database migrations
```

See [docs/engineering/ARCHITECTURE_PRINCIPLES.md](docs/engineering/ARCHITECTURE_PRINCIPLES.md)
for why the `app/core` / `app/gui` split exists and what it protects.

---

## Setup

```bash
python3.12 -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

Requires Python 3.12 and, for GUI work, the `gui` extra (`pip install -e
".[dev,gui]"`) plus [ffmpeg](https://ffmpeg.org/download.html) on `PATH` for
export/normalization features. See `README.md` for full setup detail.

---

## Coding Standards

- Follow [docs/engineering/ARCHITECTURE_PRINCIPLES.md](docs/engineering/ARCHITECTURE_PRINCIPLES.md):
  `app/core` never imports `app/gui`; the GUI reaches services only through
  `ApplicationContext`; prefer extending an existing service/widget over
  creating a new one.
- Follow [docs/engineering/UI_DESIGN_PRINCIPLES.md](docs/engineering/UI_DESIGN_PRINCIPLES.md)
  for anything in `app/gui/`: no hardcoded colors (use `ThemeTokens`), reuse
  the existing widget catalog, keep interactive states (`hover`/`focus`/
  `pressed`/`disabled`) complete.
- Match the style already present in the file/module you're editing. This
  project does not run an opinionated auto-formatter beyond `ruff`'s own
  rules — consistency comes from following the surrounding code, not from
  a formatter enforcing it.
- Filenames for generated/production content follow the project's
  established convention: English, lowercase, `snake_case`, versioned with
  a two-digit suffix (`melissa_face_ref_v01.png`) — see
  `docs/07_DEVELOPMENT_PLAN.md` §4.
- Every non-obvious decision is documented where a future reader will find
  it — a short comment for a local *why*, a milestone status doc
  (`docs/NN_..._STATUS.md`) for a milestone-level *why*.
- No dead code, no speculative configuration options, no abstractions built
  for a hypothetical future requirement — see
  [docs/engineering/QUALITY_BAR.md](docs/engineering/QUALITY_BAR.md) item 6.

---

## Branching Strategy

Today, development happens on a single long-lived branch tracked against
`origin` (the founder is the sole contributor and reviewer). A
`backup/<milestone-name>` branch may be cut before a large or risky
milestone as a restore point — it is a safety snapshot, not a merge target.

If/when additional contributors join, the model expands to:

- `main` — always releasable; protected; only updated via reviewed pull
  request.
- `feature/<short-description>` (or `fix/<short-description>`) branches per
  unit of work, opened from and merged back into `main` via PR.
- No direct pushes to `main`, no force-pushes to shared branches, no
  history rewriting on anything already pushed — this is already the rule
  for the single-branch model today (see
  [docs/engineering/ENGINEERING_WORKFLOW.md §2](docs/engineering/ENGINEERING_WORKFLOW.md#2-git-workflow))
  and does not change with more contributors.

---

## Commit Conventions

- One commit per completed, working milestone or unit of work — not one
  commit per file, not a string of "wip" commits.
- Commit messages describe what changed and why, at the depth of the
  existing history (see `git log` for real examples) — enough for a future
  reader to understand scope and rationale without opening the diff.
- Include test/lint status in the message when relevant (e.g. "460/460
  tests pass, ruff clean").
- AI-assisted commits carry a `Co-Authored-By:` trailer, matching existing
  convention.

Full detail: [docs/engineering/ENGINEERING_WORKFLOW.md §3](docs/engineering/ENGINEERING_WORKFLOW.md#3-commit-process).

---

## Testing Expectations

- `pytest` must pass in full before any commit — no exceptions for
  "unrelated" failures; if a pre-existing failure blocks you, fix or flag
  it first.
- `ruff check .` must be clean.
- New behavior ships with new tests in the matching layer (`tests/unit`,
  `tests/integration`, `tests/gui`) in the same change that introduces it.
- Changes to `app/gui/` require manual verification in the running app
  (both light and dark themes, and narrow-window behavior if layout is
  affected) in addition to automated tests — see
  [docs/engineering/ENGINEERING_WORKFLOW.md](docs/engineering/ENGINEERING_WORKFLOW.md#gui-verification-process).

---

## Pull Request Expectations

(Applies once PRs are the active workflow — see Branching Strategy above.)

- One PR per milestone/unit of work, matching the commit conventions above.
- PR description states: what changed, why, what deliberately did not
  change, and test/lint status.
- CI (once configured) must be green; local `pytest` + `ruff check .` must
  already be green before opening the PR.
- No PR merges without review approval, regardless of how confident the
  author is — see Review Expectations.

---

## Review Expectations

- Every change is reviewed against
  [docs/engineering/QUALITY_BAR.md](docs/engineering/QUALITY_BAR.md)'s eight
  questions before it's considered ready, whether the review is a formal PR
  review or the founder reviewing a milestone commit directly.
- A reviewer (human or AI) checks: does this preserve the `core`/`gui`
  boundary, does it reuse existing components rather than duplicate them,
  is the UI consistent with the existing design system, are tests present
  and passing, is the commit message accurate.
- Approval is explicit. Silence, or moving on to the next topic, is not
  approval — see
  [docs/engineering/ENGINEERING_WORKFLOW.md §4](docs/engineering/ENGINEERING_WORKFLOW.md#4-review-process).
- Nothing is pushed/merged without that explicit approval, and pushes are
  never forced.

---

## Working With an AI Assistant

If you are (or are directing) an AI coding assistant in this repository,
start with
[docs/engineering/AI_COLLABORATION_GUIDE.md](docs/engineering/AI_COLLABORATION_GUIDE.md) —
it is the AI-agnostic collaboration contract every assistant is expected to
follow here, independent of which vendor's tool is being used.
