# Engineering Workflow

This is the operating procedure for all development work in this repository —
for the founder, and for any AI assistant (Claude, Copilot, Cursor, Gemini,
Codex, or otherwise) working inside it. It is the version-controlled source
of truth; it does not depend on any particular tool's memory or session
state. See [AI_COLLABORATION_GUIDE.md](AI_COLLABORATION_GUIDE.md) for the
tool-agnostic collaboration contract this workflow sits inside.

---

## 1. Milestone Workflow

Work is organized into **milestones** — a coherent, shippable unit of change
(a feature, a subsystem, a polish pass). Each milestone follows the same
four phases:

### Before starting a milestone

1. Run `git status`.
2. Confirm the working tree is clean (no uncommitted changes, nothing
   unexpectedly staged). If it isn't, investigate before proceeding — don't
   discard unfamiliar changes without understanding what they are.
3. Confirm the branch is up to date with `origin` (§2).

### During the milestone

- Preserve the existing architecture — see
  [ARCHITECTURE_PRINCIPLES.md](ARCHITECTURE_PRINCIPLES.md).
- Reuse existing components/services/widgets before writing new ones.
- Never duplicate code that already exists elsewhere in the project.
- Follow the coding style already established in the surrounding files
  (this repo does not use a code formatter beyond `ruff`; match the
  prevailing style file-by-file).
- If you discover an unrelated bug or a materially better design mid-task,
  do not implement it silently — follow the propose-first process in
  [AI_COLLABORATION_GUIDE.md](AI_COLLABORATION_GUIDE.md#5-when-to-propose-vs-when-to-just-do-it).

### Before every commit

1. Run the full test suite: `pytest`.
2. Run the linter: `ruff check .`.
3. If the change touches `app/gui/`, perform manual GUI verification (§5) —
   type-checking and the automated test suite verify correctness, not
   visual/interaction quality.
4. Update or add the relevant documentation (a milestone status doc under
   `docs/`, docstrings/comments only where the *why* is non-obvious).

### After a completed milestone

1. Create **one** descriptive local commit for the milestone (§3).
2. **Stop.** Do not push. Wait for review.
3. Only after the founder explicitly approves that specific commit, push to
   `origin` (§6).

---

## 2. Git Workflow

- Development happens on a single long-lived working branch tracked against
  `origin` (currently `claude/house-of-stories-dev-plan-gp2coh`). There is no
  multi-contributor branching model yet — see
  [CONTRIBUTING.md](../../CONTRIBUTING.md) for what changes once there is.
- Before a risky or large milestone, a `backup/<milestone-name>` branch may
  be cut from the current tip as a restore point (see `backup/milestone4b`
  for a real example). This is a safety net, not a merge target.
- **Never force-push.**
- **Never rewrite history** (`rebase -i`, `commit --amend` on an already-
  pushed commit, `reset --hard` past a pushed commit). If a commit needs
  correcting after the fact, add a new commit that fixes it.
- **Never modify a previous milestone's commit** unless the founder
  explicitly asks for it. A milestone's commit is a checkpoint of record —
  treat it as immutable once made.

---

## 3. Commit Process

- One commit per completed milestone (not one commit per file, not one
  commit per hour of work). Sub-steps within a milestone stay uncommitted
  until the milestone is actually done and verified.
- Commit messages describe **what changed and why**, not a mechanical diff
  summary — see the existing commit history for the expected depth and tone
  (e.g. `bd86215`, `7143a0e`). A good commit message should let a future
  reader understand the milestone's scope, what deliberately did *not*
  change, and any real bug caught/fixed along the way, without opening the
  diff.
- Commits authored with AI assistance are attributed with a
  `Co-Authored-By:` trailer, matching existing history.
- Test/lint status belongs in the commit message when relevant (e.g. "460/460
  tests pass, ruff clean") — it's a fact about the change, not decoration.

---

## 4. Review Process

- The founder reviews every milestone's commit (diff + commit message)
  before it is pushed. This is a hard gate, not a formality — see
  [ENGINEERING_WORKFLOW.md §6](#6-push-policy).
- An AI assistant must not solicit "approve this" language it can act on
  itself — approval is the founder's decision, expressed however the
  founder chooses to express it, and the assistant waits for it rather than
  assuming silence or a topic change means approval.
- Once multiple contributors exist, review process expands to pull-request
  review — see [CONTRIBUTING.md](../../CONTRIBUTING.md).

---

## 5. Testing Process

- Full suite: `pytest` (see `pyproject.toml`'s `[tool.pytest.ini_options]`).
- Test layout mirrors the app layout:
  - `tests/unit/` — `app/core/models` and `app/core/services` in isolation.
  - `tests/integration/` — cross-service flows (CLI, migrations, seed data,
    export packaging) against a real (temp) SQLite database.
  - `tests/gui/` — `app/gui/` via `pytest-qt`, run headless
    (`QT_QPA_PLATFORM=offscreen`, set in `tests/gui/conftest.py`), skipped
    cleanly via `pytest.importorskip("PySide6")` when the `gui`/`dev` extra
    isn't installed.
- A milestone is not complete if any test is failing or skipped for a
  reason other than a documented, intentional environment gap (missing
  optional dependency).
- New behavior gets a new test in the same milestone that introduces it —
  not deferred to "later."

## GUI Verification Process

Automated GUI tests catch regressions in structure and wiring; they do not
catch whether a screen actually looks and feels right. For any milestone
that touches `app/gui/`:

1. Run the app locally (`hos-gui`, or `python -m app.gui.app`) and exercise
   every screen/flow the milestone touched.
2. Check both light and dark themes — see
   [UI_DESIGN_PRINCIPLES.md](UI_DESIGN_PRINCIPLES.md) for the token system
   that makes this a real risk (a widget with no matching QSS selector
   silently keeps the wrong theme's background — this has happened before,
   see `docs/22_MILESTONE_4A_STATUS.md` §3).
3. Check narrow-window behavior if the change touches layout (the app's
   floor is 640×480; `ToolbarRow`/`PageHeader` reflow below defined
   thresholds — see `docs/26_UI_UX_POLISH_V3_STATUS.md` §5).
4. Capture before/after screenshots into `docs/screenshots/<milestone>/`
   when the change is visual, matching the existing convention.
5. Report GUI verification honestly: if you could not run the app in the
   current environment, say so explicitly rather than inferring visual
   correctness from passing tests.

---

## 6. Push Policy

- Nothing is pushed to `origin` without the founder's explicit, per-commit
  approval. A prior approval does not carry forward to later commits.
- Pushes are always a plain `git push` (fast-forward) to the tracked
  branch — never `--force`, never `--force-with-lease`, unless the founder
  explicitly asks for it in that moment and understands the consequences.

---

## 7. Release Discipline

- Every milestone that changes `app/` gets a corresponding status document
  under `docs/` following the existing numbered convention
  (`docs/NN_MILESTONE_NAME_STATUS.md` — see `docs/17`, `docs/19`, `docs/22`–
  `docs/26` for the pattern). It records: scope, what deliberately did *not*
  change, real bugs caught during the milestone, test/lint results, and
  screenshots where relevant.
- `tests/unit/test_repo_structure.py` is a live guardrail: it asserts
  required directories/files/docs exist and that `app/gui` never imports DB
  internals directly. A milestone that removes or renames something this
  test checks must update the test deliberately, in the same commit, with a
  reason — not as a side effect.
- No milestone is "done" until §1's four phases have all completed for it.
  A milestone that is committed but not yet reviewed/pushed is **in
  progress**, not released.
