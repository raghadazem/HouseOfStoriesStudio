# 27 — Windows & Test Stabilization Status

**Milestone:** Windows environment verification + test stabilization, following the
`docs/engineering/` standards milestone (see git history). Not a product/feature
milestone — no new user-facing capability.
**Scope:** Establish a correct local Windows/Python 3.12 dev environment, then fix
four specific, previously-reported test failures for legitimate, root-caused reasons.

---

## 0. What Did Not Change

- No new user-facing GUI behavior, no new CLI subcommands, no new AI provider/workflow.
- `app/gui/` widget behavior is unchanged (only the flaky *test*'s wait strategy changed).
- `app/core/ai/` orchestration/workflow logic is unchanged (only a *test fixture's*
  temp-path handling changed).
- The pre-existing `SAWarning: Cannot correctly sort tables; there are unresolvable
  cycles...` (FK cycles between `assets`/`character_versions`/`characters`/`shorts`,
  surfaced by `alembic check`) is **not addressed by this milestone** — still present,
  not claimed fixed.

---

## 1. Environment Established

- **Python 3.12.10** installed via the official python.org installer, user-scoped, with
  the `py` launcher — not the Microsoft Store package (see
  `docs/engineering/WINDOWS_DEVELOPMENT.md` for why).
- Project-local `.venv/` created and is now the standing local dev environment
  (git-ignored, not a throwaway).
- `.vscode/settings.json` created, **local-only, git-ignored by explicit decision** —
  `.gitignore` was not touched for this.
- Full dependency install verified: `pip install -e ".[dev,gui]"` — the two extras
  actually defined in `pyproject.toml`, confirmed by inspection before installing, not
  assumed.

---

## 2. Fix 1 — Windows Temp Path in `test_ai_orchestrator.py`

**Root cause:** `_FakeConfiguredProvider.generate()` (test-only double) hardcoded
`Path("/tmp/fake_{uuid}.png")`. On Windows this resolves to `\tmp\...` off the current
drive root — a directory that was never created — so anything reading that path failed.

**Fix:** Use `tempfile.gettempdir()`, mirroring the real
`app/core/ai/providers/mock_provider.py`'s already-correct pattern. Test-only; zero
production AI behavior changed.

**New/strengthened coverage** (`tests/unit/test_ai_orchestrator.py`):
- `test_fake_provider_generate_writes_a_real_temp_file` — the file exists immediately
  after `generate()`, with the expected bytes (the "exists when expected" case).
- `test_run_workflow_cleans_up_temp_file_after_success` — new. Existing coverage only
  ever exercised cleanup-after-*failure* — `_FakeSucceedingWorkflow` never set
  `ctx.last_generation_result`, unlike every real workflow, so the orchestrator's
  cleanup path was silently never exercised on the success path. Fixed the fake to
  match real workflow behavior, then added this test.
- `test_run_workflow_cleans_up_temp_file_even_when_import_fails_after_generate` —
  pre-existing, now passing on Windows (the "cleaned up after failed import" case).

---

## 3. Fix 2 — CLI UTF-8 Output (real product bug, not just a test artifact)

**Root cause:** `app/cli/main.py::cmd_show_episode` prints `episode.title_ar` via the
plain `print()` builtin. On Windows, when stdout isn't explicitly UTF-8 (the default
for a console/pipe unless the user sets `PYTHONUTF8`/`PYTHONIOENCODING` or runs
`chcp 65001`), Python encodes through the legacy console codepage, which cannot
represent Arabic — `UnicodeEncodeError`, command crashes, non-zero exit.
**This is a real bug a founder could hit running `hos-cli show-episode` on an ordinary
Windows terminal** — not only a CI/test artifact.

**Fix:** `app/cli/main.py::_ensure_utf8_stdio()` — reconfigures `sys.stdout`/`sys.stderr`
to UTF-8 once, at the top of `main()`. Windows-safe, a no-op in effect on
already-UTF-8 platforms, gracefully skips streams without `reconfigure()`, and is a
single call site (no per-command duplication, no monkeypatching).

**A second, related bug found while verifying the fix:** the *test harness's*
`subprocess.run(..., text=True)` decodes the child's captured stdout using the
**parent's** system locale codepage by default — on this machine (`cp1255`), that
failed to decode the now-correctly-UTF-8-encoded child output. Fixed
`tests/integration/test_cli.py::_run` to pass `encoding="utf-8"` explicitly, matching
what the CLI now guarantees to emit. Documented in
`docs/engineering/WINDOWS_DEVELOPMENT.md` so it isn't rediscovered per-machine.

**New regression coverage** (`tests/integration/test_cli.py`):
- `test_show_episode_prints_arabic_text_without_encoding_error` — full episode title,
  no `UnicodeEncodeError`/`Traceback` in stderr, exit 0. Deliberately does **not** set
  `PYTHONUTF8`/`PYTHONIOENCODING` — the point is a user should never have to.
- `test_run_ai_workflow_path_survives_arabic_output_upstream` — the id-parsing path
  that used to fail downstream of the encoding crash with an unrelated-looking
  `StopIteration`.

---

## 4. Fix 3 — GUI Timing Flake (`test_ui_polish_v3_widgets.py`)

**Root cause:** `qtbot.wait(20)` (a fixed sleep) after a resize, before asserting the
resulting reflow state — not a real synchronization primitive for a Qt layout event.

**Fix:** Replaced every `qtbot.wait(20)` + assert pair (`ToolbarRow` and `PageHeader`
wrap tests) with `qtbot.waitUntil(lambda: widget._wrapped is <expected>, timeout=1000)`
— pytest-qt's own recommended pattern: poll for the actual expected state instead of
guessing a delay. No production GUI code changed or slowed down.

**Verified:** all 13 tests in the file pass repeatedly in isolation, and the *other*
12 previously-passing tests in the file remain unaffected.

**Known, unfixed residual:** `test_page_header_wraps_button_below_threshold`
specifically still fails intermittently when run as part of the full `tests/gui/`
suite (not in isolation), even with `waitUntil` and timeouts up to 5s. Diagnostic
instrumentation showed the widget's actual post-resize width is 437px instead of the
requested 300px under that specific run ordering — evidence of a **shared, session-scoped
`QApplication` carrying stylesheet/styling state across tests** (not reset between
tests), rather than anything `waitUntil` can address. This is a distinct, pre-existing
test-isolation issue, unrelated to the fixed-wait problem this fix targeted. **Not
fixed in this milestone** — see `docs/engineering/WINDOWS_DEVELOPMENT.md` and §6 below.

---

## 5. Fix 4 — Deterministic Approval "Current State" (`ApprovalRecord.revision`)

**Root cause:** `ApprovalService.get_current_approval_state` ordered by
`ApprovalRecord.decided_at.desc()` alone. `decided_at` is a Python-computed timestamp;
two decisions recorded close enough together (exactly what
`test_get_current_approval_state_returns_latest` does — approve immediately followed
by request-changes) can land on the same value, making "current state" not
deterministic. Reproduced under both Python 3.11 and 3.12 — not a platform issue, a
real ordering bug.

**Design:** Added `ApprovalRecord.revision: int` — a monotonically increasing integer,
scoped per `(entity_type, entity_id)`, assigned transactionally by
`ApprovalService._record` (query-then-insert; a single-user desktop app has no
concurrent-writer race to defend against, and the new unique constraint is the
backstop if that assumption is ever wrong). `get_current_approval_state` and
`list_approval_history` now order by `revision`, not `decided_at`. `decided_at` is
unchanged and still recorded — for display/audit purposes, no longer for ordering.

**Schema change — migration `1017c6c7ae38` ("approval record revision ordering"),
revises `8ed8cbd56eee`:**
1. Add `revision` nullable (no data loss risk).
2. Backfill every existing `(entity_type, entity_id)` group in `decided_at` order,
   with `id` as a tiebreaker for rows that already share a timestamp — assigning
   1, 2, 3, ... . Uses Core table reflection (`sa.table(...)`), not the ORM model, so
   the migration stays valid independent of future model changes.
3. Make `revision` `NOT NULL`; add `uq_approval_records_entity_revision` unique
   constraint on `(entity_type, entity_id, revision)`.

**Verified directly** (not just via the test suite) against a database with
pre-existing approval history, including a deliberate `decided_at` tie:
- `alembic upgrade head` from `8ed8cbd56eee` — backfills correctly; the tied pair
  receives distinct, deterministic revisions.
- `alembic downgrade 8ed8cbd56eee` — drops the column and constraint, **all rows
  preserved** (row count unchanged).
- Re-`alembic upgrade head` — clean, re-runnable.
- `alembic check` — "No new upgrade operations detected" (no model/migration drift).

**New test coverage** (8 scenarios required, all present and passing):

| # | Scenario | Test |
|---|---|---|
| 1 | Multiple decisions, same entity | `test_revision_numbers_are_assigned_sequentially_and_deterministically` |
| 2 | Deterministic revision values | same, plus `test_approve_reject_and_history_ordering` (strengthened) |
| 3 | Current state = highest revision, even with tied timestamps | `test_current_state_returns_highest_revision_even_with_identical_timestamps` |
| 4 | History order deterministic under tied timestamps | `test_approval_history_order_is_deterministic_with_identical_timestamps` |
| 5 | Two entities, independent sequences | `test_two_entities_maintain_independent_revision_sequences` |
| 6 | Persists across DB close/reopen | `tests/integration/test_persistence.py::test_approval_revision_state_persists_across_engine_close_and_reopen` |
| 7 | Migration backfill of pre-existing history | `tests/integration/test_migrations.py::test_approval_records_revision_migration_backfills_existing_history` (+ a downgrade counterpart) |
| 8 | Uniqueness constraint enforcement | `test_duplicate_revision_for_same_entity_violates_unique_constraint` |

---

## 6. New Issues Found — Reported, Not Fixed This Milestone

Both were previously **masked** by failures this milestone fixed, not caused by this
milestone. Per the founder's explicit direction, they are documented here as known,
open issues rather than fixed now:

1. **`AssetImportService.copy_file_atomic` — intermittent `WinError 3`.**
   `test_run_ai_workflow_thumbnail_and_review_queue` now gets past the (fixed)
   encoding crash and reaches a real, separate bug: `shutil.copy2` intermittently
   raises `[WinError 3] The system cannot find the path specified` copying the
   `MockProvider`'s freshly-written temp file, specifically when several CLI
   subprocesses launch in rapid succession (as the test does — 5 in a few seconds).
   A single, isolated manual repro of the exact same code path succeeds every time;
   the failure is consistent (3/3) only under the rapid-subprocess pattern. Working
   theory: Windows file-access interference (e.g. real-time antivirus scanning) on a
   newly created temp file under I/O burst — not confirmed without deeper live
   tracing. `MockProvider`'s temp directory is also a fixed OS location, not
   test-isolated, which is a contributing design factor worth revisiting regardless
   of the immediate trigger.
2. **Shared `QApplication` styling state across GUI tests.** See §4. Diagnostic
   evidence (437px vs. requested 300px) points to global stylesheet/styling state
   leaking across tests via the session-scoped `QApplication`, not a `PageHeader`
   logic bug.

---

## 7. Testing

Final verification, `.venv\Scripts\python.exe` (Python 3.12.10):
- `pytest`: **470 passed, 2 failed** — the two issues in §6, both pre-existing/masked,
  neither caused by this milestone's changes.
- `ruff check .`: clean.
- `alembic upgrade head` / `alembic check` (clean scratch DB): clean, no drift.
- Migration-specific verification (§5): upgrade-with-backfill, downgrade-preserves-rows,
  re-upgrade, all confirmed directly against a database with pre-existing data, not
  only via the automated suite.

## 8. Manual Windows Verification

Performed directly against `.venv`'s Python 3.12.10, a real Windows filesystem, and a
real (non-in-memory) SQLite database:
- `hos-cli show-episode` printed `ميليسا`, `بيلسان`, and the full Arabic episode title
  with no `UnicodeEncodeError`, exit code 0.
- Four rapid sequential approval decisions (approve → request-changes → reject →
  approve) on one real imported asset, in one process: revisions assigned `1, 2, 3, 4`
  in order; current state correctly `APPROVED`.
- A **second, independent process** opening the same database file (simulating
  app close/reopen) read back the identical history and current state.
