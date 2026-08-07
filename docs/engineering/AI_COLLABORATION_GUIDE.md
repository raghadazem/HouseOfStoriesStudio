# AI Collaboration Guide

This document explains how **any AI coding assistant** — regardless of
vendor or tool — should work inside this repository. It is written to be
AI-agnostic: it applies equally whether the assistant in use is Claude,
GitHub Copilot, Cursor, Gemini, Codex, or a future system not yet released.
Nothing here depends on any tool's memory, session, or vendor-specific
feature — the repository itself is the source of truth (see
[ENGINEERING_WORKFLOW.md](ENGINEERING_WORKFLOW.md) §0).

If you are an AI assistant reading this at the start of a session: read this
file, then read the five documents it links to, before making any change.

---

## 1. How to Inspect the Project

Before writing any code, build an accurate picture of what already exists.
Do not assume — verify:

1. **Read the standing engineering docs**, in this order:
   [PRODUCT_VISION.md](PRODUCT_VISION.md) (why this exists),
   [ARCHITECTURE_PRINCIPLES.md](ARCHITECTURE_PRINCIPLES.md) (how it's built),
   [UI_DESIGN_PRINCIPLES.md](UI_DESIGN_PRINCIPLES.md) (how it looks/feels),
   [QUALITY_BAR.md](QUALITY_BAR.md) (what "done" means),
   [ENGINEERING_WORKFLOW.md](ENGINEERING_WORKFLOW.md) (how work moves
   through the repo).
2. **Read `README.md`** for the current project layout and setup.
3. **Read the numbered `docs/` files relevant to the area you're touching**
   (e.g. `docs/20_GUI_ARCHITECTURE.md` and `docs/21_DESIGN_SYSTEM.md` before
   any GUI work; `docs/18_AI_ARCHITECTURE_PLAN.md` before any AI-provider
   work). The most recent numbered status doc for an area reflects its
   *current* state — earlier docs may describe a since-superseded plan.
4. **Read the actual code**, not just docs about it — docs describe intent
   and rationale; the code is the ground truth for current behavior.
   `app/core/` for business logic, `app/gui/` for presentation,
   `tests/` for both expected behavior and usage examples.
5. **Check `git log` and `git status`** to understand what's already in
   flight and what the most recent milestones actually changed.
6. When genuinely uncertain what a piece of code or a past decision was
   *for*, search for it before guessing — a wrong assumption compounds
   into a wrong implementation.

---

## 2. How to Start a Milestone

Follow [ENGINEERING_WORKFLOW.md §1](ENGINEERING_WORKFLOW.md#1-milestone-workflow)
exactly:

1. `git status` — confirm a clean working tree before starting.
2. Confirm you understand the milestone's actual scope. If the request is
   ambiguous in a way that would materially change what gets built, ask
   before writing code — a clarifying question costs a few seconds; a
   wrong implementation costs a rewrite.
3. Identify which existing services/widgets/modules are relevant (§1 above)
   before designing anything new.

---

## 3. How to Preserve Architecture

- Never let `app/gui/` import database or service internals directly — all
  access goes through `ApplicationContext`. See
  [ARCHITECTURE_PRINCIPLES.md §1](ARCHITECTURE_PRINCIPLES.md#1-clean-architecture-core-never-depends-on-gui).
- Never let `app/core/` import from `app/gui/` — the dependency direction
  is one-way.
- Keep one concern owned by one module (the storage service owns the
  filesystem, the approval service owns approval records, etc.) — do not
  reach around an existing owner to do its job from somewhere else.
- Keep the AI layer provider-agnostic: a new generative capability is a new
  `AIProvider` implementation or a new `Workflow`, never a new path that
  bypasses `AIOrchestrator`.
- If a change seems to require breaking one of these rules, stop and raise
  it explicitly (§5) rather than making the exception silently — the rule
  is almost certainly there on purpose (see the "one gotcha" writeups in
  `docs/20`/`docs/21` for real examples of what breaks when it isn't
  followed).

---

## 4. How to Avoid Duplicate Code

Before writing a new function, service, widget, or page:

1. Search the codebase for something that already does this or something
   close to it.
2. If something close exists, extend it (a new parameter, a new variant, a
   new method) rather than copying it and modifying the copy.
3. Only write something new when nothing existing can reasonably be
   extended — and place it where the existing module structure expects it
   (see [ARCHITECTURE_PRINCIPLES.md §6](ARCHITECTURE_PRINCIPLES.md#6-extension-before-creation)).

This is not a style preference — duplicated logic is where this codebase's
consistency and correctness guarantees (naming rules, approval gating,
theme tokens) silently drift apart over time.

---

## 5. When to Propose vs. When to Just Do It

**The task as given is the task to do.** Don't quietly expand or narrow it.
But if, while working, you notice any of the following, **do not
implement it automatically:**

- A significantly better architectural approach than what the task
  implies.
- A UX improvement outside the current task's scope.
- A bug unrelated to the current task.

Instead, **propose it**, in this exact structure, then stop and wait:

- **The issue** — what's wrong or suboptimal, concretely.
- **The proposed improvement** — what you'd change.
- **Why it is better** — the concrete reasoning (maintainability, user
  experience, consistency, correctness — tie it back to
  [QUALITY_BAR.md](QUALITY_BAR.md) where relevant).
- **Estimated impact** — how much code/how many files this touches, and
  any risk.

Wait for approval before making any change outside the current task's
explicit scope. This applies even when you are confident you're right —
confidence is not the same as authorization, and unrelated changes bundled
into a task's diff make it harder to review and riskier to ship.

---

## 6. How to Perform Testing

Follow [ENGINEERING_WORKFLOW.md §5](ENGINEERING_WORKFLOW.md#5-testing-process):

- Run the full suite (`pytest`) before considering any change complete.
- New behavior ships with a new test in the same change, in the matching
  layer (`tests/unit/` for isolated service/model logic, `tests/integration/`
  for cross-service flows, `tests/gui/` for `app/gui/` via `pytest-qt`).
- Never mark a task complete with a failing or newly-skipped test unless
  the skip is a pre-existing, documented, intentional environment gap
  (e.g. an optional GUI dependency not installed).
- For anything touching `app/gui/`, also perform the manual GUI
  verification steps in
  [ENGINEERING_WORKFLOW.md](ENGINEERING_WORKFLOW.md#gui-verification-process)
  — automated tests confirm wiring, not visual/interaction quality. If you
  cannot run the app in your current environment, say so explicitly rather
  than inferring visual correctness from passing tests.

---

## 7. How to Perform Reviews

- Before presenting any task as complete, run it through
  [QUALITY_BAR.md](QUALITY_BAR.md)'s eight questions yourself. Fix what
  fails before handing it off — don't hand off a "no" and call it done.
- Summarize what changed and why in terms a reviewer who wasn't watching
  you work can verify — file paths, the actual behavior change, what was
  deliberately left unchanged (see the "What Did Not Change" pattern in
  recent milestone status docs, e.g. `docs/26_UI_UX_POLISH_V3_STATUS.md`
  §0, for the expected tone).
- Reviewing your own diff before presenting it is not optional: check for
  leftover debug code, accidental unrelated changes, and consistency with
  the surrounding style.

---

## 8. When to Commit

Per [ENGINEERING_WORKFLOW.md §1 and §3](ENGINEERING_WORKFLOW.md#3-commit-process):

- One commit per completed milestone — not partial, not multiple
  fragments for one milestone.
- Only after: the full test suite passes, `ruff check .` is clean, GUI
  verification is done where relevant, and the change satisfies
  [QUALITY_BAR.md](QUALITY_BAR.md).
- Write a commit message that explains what changed and why, at the depth
  of the existing commit history — not a one-line mechanical summary.
- **After committing, stop.** Do not continue to the next milestone or push
  without being asked. The founder reviews the commit before anything else
  happens to it.

---

## 9. When to Push

- **Never push without explicit, per-commit approval.** A prior approval
  for a different commit does not carry forward.
- **Never force-push. Never rewrite history. Never modify a previous
  milestone's commit** unless explicitly asked to. See
  [ENGINEERING_WORKFLOW.md §2](ENGINEERING_WORKFLOW.md#2-git-workflow).
- Once approved, push is a plain fast-forward push to the tracked branch —
  nothing more elaborate.

---

## Summary

Read before writing. Reuse before creating. Propose before assuming. Test
before claiming done. Commit, then stop. Push only when told. This is the
entire contract — every section above is a concrete elaboration of these
six sentences, and it holds regardless of which AI system is doing the
work.
