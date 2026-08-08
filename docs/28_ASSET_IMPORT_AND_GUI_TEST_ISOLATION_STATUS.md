# 28 — Asset Import (WinError 3) & GUI Test Isolation Status

**Milestone:** Focused follow-up to `docs/27_WINDOWS_TEST_STABILIZATION_STATUS.md` §6 —
resolves the two issues that milestone found and deliberately left open.
**Scope:** Exactly two bugs. No product feature work, no SQLAlchemy FK-cycle warning
work (still present, still not addressed here — see `docs/27` §0 for why).

---

## 1. Fix 1 — `AssetImportService.copy_file_atomic` (`WinError 3`)

### Root Cause

Not timing, not antivirus, not a race — a plain **Windows `MAX_PATH` (260-character)
limit** violation, found by instrumenting the failure and reading the exact path
lengths involved:

- `dest` (the real destination path): **227 characters** — comfortably under the limit.
- `temp_path` (the old scratch-file name, `.{dest.name}.{uuid.uuid4().hex}.tmp`):
  **265 characters** — over it.

The old temp-naming scheme re-embedded the destination's own filename (already long —
`mock_image_` + a 64-hex-char sha256 digest + `.png`, from `MockProvider`) inside the
temp file's name, on top of a `.`, a 32-hex-char UUID, and `.tmp` — a fixed +37
characters no matter what. Whenever a destination path landed within 37 characters of
the limit (easy with deep episode/asset-type directories, especially under pytest's
own already-deep `tmp_path`), the *temp* file — never the real destination — silently
crossed 260, and `shutil.copy2()`'s underlying Windows API call failed with
`WinError 3` (`ERROR_PATH_NOT_FOUND`). This is exactly why it looked "intermittent" in
practice: it wasn't random, it was a fixed threshold that different test/production
path combinations happened to land on either side of.

Confirmed directly (not just inferred): a plain, isolated manual repro of the identical
code path always succeeded (short path, comfortably under the limit); the real
`pytest`-driven case, with its longer `tmp_path`, failed consistently. Diagnostic
instrumentation on `copy_file_atomic` itself (temporarily added, then removed once
root-caused) confirmed `source.exists()` and `dest.parent.exists()` were both `True` at
the moment of failure — ruling out "missing directory," "cleanup ordering," and
"test setup" as the cause, and confirming it was specifically the temp path's own
length.

### Which category (per the investigation requirements)

- **Not** destination-directory creation (the directory existed).
- **Not** temp-file lifecycle/cleanup ordering (nothing raced; the temp path itself was
  simply too long to ever be created).
- **Yes** — path length, a genuine **Windows-specific `pathlib`/`shutil` behavior**:
  Windows file APIs reject an absolute path over `MAX_PATH` unless it carries the
  `\\?\` extended-length prefix; `shutil.copy2`/`os.replace`/`Path.mkdir` don't add
  that prefix automatically.
- This is a **real production bug**, not a test artifact — fixed in production code
  (`app/core/services/storage_service.py`), not by patching the test.

### Fix

`app/core/services/storage_service.py`:

1. **Shorter temp filename.** `copy_file_atomic`'s scratch file is now
   `.{uuid.uuid4().hex}.tmp` — no longer re-embeds the destination's own (already
   long) filename. This alone removes the specific overhead that caused the reported
   failure.
2. **`_win_long_path()` helper**, applied to every filesystem call inside
   `copy_file_atomic` (`os.makedirs` for the destination directory, `shutil.copy2`,
   `os.replace`, and the failure-path `os.remove`): prefixes a resolved absolute
   Windows path with `\\?\` (raising the effective limit to ~32,767 characters, no
   admin rights or OS "enable long paths" setting required — the prefix alone does
   it). A no-op on non-Windows platforms and for already-prefixed paths.

**Every requirement checked:**

| Requirement | How satisfied |
|---|---|
| Windows-safe | `\\?\` prefix is the standard, no-admin-required Windows long-path mechanism |
| Linux-safe | `_win_long_path` returns the plain path unchanged when `os.name != "nt"` |
| Atomic-copy semantics preserved | Still copy-to-temp-then-`os.replace`; unchanged |
| Source file never deleted | Untouched — `copy_file_atomic` never removes `source` |
| Rollback behavior preserved | Failure path still removes the temp scratch file, still re-raises |
| No path traversal regression | `resolve_managed_path` (path-escape validation) runs *before* this, unchanged; `_win_long_path` only changes how an already-validated path is passed to the OS, not which path it is |
| No duplicate-detection regression | `find_duplicate_by_checksum` runs in `AssetImportService.import_asset`, before `copy_file_atomic` is ever called — untouched |
| No private-reference import regression | `_validate_source_path`'s restricted-directory check also runs before this, in `import_asset` — untouched |
| No silent directory creation outside managed storage | `os.makedirs` still only ever targets `dest.parent`, which is always inside the already-validated `production_dir` |

**A known, explicitly out-of-scope boundary:** for a destination path itself over
`MAX_PATH` (not just the old temp file), plain `pathlib` calls *elsewhere* in
`StorageService` (`compute_checksum`, `verify_checksum`, etc., all called right after
`copy_file_atomic` in `AssetImportService.import_asset`) would still need the same
`_win_long_path` treatment to work. The actually-reported bug's `dest` was 227
characters — under the limit — so this doesn't affect the fix for the reported issue.
Confirmed via a direct experiment (not guessed): writing a file at a path over 260
characters via the `\\?\`-prefixed API succeeds and is visible via
`os.path.exists()`/`os.listdir()` with the same prefix, but plain `Path.exists()`/
`Path.is_file()` (no prefix) return `False` for it — i.e., extending long-path safety
to genuinely-over-limit *destinations* is a real, separate, larger piece of work
(propagating `_win_long_path` through more of `StorageService`), deliberately not done
here since it's beyond what was reported and approved.

### Regression Test

`tests/unit/test_storage_service.py::test_copy_file_atomic_succeeds_when_old_temp_naming_would_have_exceeded_max_path`

Deterministic by construction — not dependent on pytest's own (variable-length)
`tmp_path`: builds its own short `tempfile.mkdtemp()`-based `StorageService`, then
computes a destination path length precisely (240 characters — comfortably under 260,
so the test's own plain-`pathlib` assertions stay meaningful) such that the *old*
`.{name}.{uuid}.tmp` scheme's fixed +37-character overhead would have pushed it past
260, while the fix's shorter scheme does not.

**Verified the test is real, not a tautology:** temporarily reverted
`storage_service.py` to the pre-fix version and reran — the test fails with the exact
same `WinError 3` / `FileNotFoundError` the real bug produced. Restored the fix; it
passes again.

Also re-verified the originally-reported test,
`tests/integration/test_cli.py::test_run_ai_workflow_thumbnail_and_review_queue`,
5/5 consecutive runs, and manually via the CLI (§4 below).

---

## 2. Fix 2 — GUI Test Isolation (`PageHeader` / shared `QApplication` styling)

### Root Cause

Confirmed via diagnostic instrumentation (temporarily printing widget state on
failure, then removed): under a full-suite run,
`header.resize(300, 100)` produced an actual measured width of **437px**, not 300 —
Qt was clamping the resize to a larger natural minimum size than in isolation.

`ThemeManager.__init__`/`apply` (`docs/21_DESIGN_SYSTEM.md` §3) is the *only* place
anything calls `QApplication.setStyleSheet(...)`. The `QApplication` itself is a
single process-wide singleton every GUI test shares — pytest-qt's `qapp` fixture
can't create a second one per process. Several test files (`test_theme.py`,
`test_startup.py`, `test_sidebar_navigation.py`, `test_status_bar.py`,
`test_ui_polish_widgets.py`, `test_window_persistence.py`, plus the shared `theme`
fixture in `conftest.py`) each construct their own `ThemeManager` directly — none of
them ever reset the stylesheet afterward. Whichever one ran most recently left its
QSS (padding/sizing rules for buttons, etc.) applied globally for every subsequent
test in the same process — including `PageHeader`'s own test, which never touches
theming at all and had no way to know or defend against it.

### Fix

`tests/gui/conftest.py`: one new **autouse** fixture, `_reset_qapplication_style`,
that resets `qapp.setStyleSheet("")` in teardown after every test under `tests/gui/`.
Autouse specifically because the contamination could come from *any* test file
constructing a `ThemeManager` directly — a per-file or per-test opt-in fixture would
have needed every current and future GUI test file to remember to use it. This is the
smallest fix that closes the actual shared point of contamination (the one thing
`ThemeManager` touches on the shared `QApplication`) rather than working around its
symptom in one test.

**Every requirement checked:**

- Responsive layout behavior (`PageHeader`'s own wrap logic) — **not touched.**
- Production breakpoints (`_WRAP_BELOW_WIDTH` etc.) — **not touched.**
- No arbitrary sleeps — the existing `qtbot.waitUntil` from `docs/27`'s Fix 3 is
  untouched and still correct; this fix addresses a different, additional problem
  (state, not timing).
- No reliance on test execution order to *pass* — the fix is what removes the
  order-dependency; the new regression tests (below) *use* deliberate ordering only to
  *prove* the fix, which is a different thing from depending on it for correctness.

### Regression Tests

New file: `tests/gui/test_gui_test_isolation.py` (order-dependent by design, and
documented as such — this is the one place in the suite where that's the point):

1. `test_a_apply_a_dark_theme_to_the_shared_qapplication` — deliberately contaminates
   global state, the way an ordinary theme test does.
2. `test_b_qapplication_style_is_reset_after_the_previous_test` — directly proves the
   autouse fixture's teardown ran (would fail on the old `conftest.py`).
3. `test_c_page_header_wraps_correctly_standalone` — baseline, no theme touched.
4. `test_d_apply_several_theme_changes_including_a_toggle` — a heavier, more realistic
   simulation of a `test_theme.py`-style run (light → dark → toggle → light).
5. `test_e_page_header_wraps_identically_after_theme_churn` — same widget, same
   thresholds, same assertions as (3), including asserting the *actual* width
   (`== 300`, not just "wrapped") — directly reproducing what used to measure 437px.

**Verified the tests are real, not tautologies:** temporarily reverted
`tests/gui/conftest.py`'s new fixture and reran the full `tests/gui/` suite — 4 tests
failed with exactly the predicted symptoms: `test_b` (stylesheet not reset),
`test_c`/`test_e` (wrap threshold not reached — the same `TimeoutError` as the
original bug report), and the pre-existing
`tests/gui/test_ui_polish_v3_widgets.py::test_page_header_wraps_button_below_threshold`.
Restored the fixture; all pass again, repeatably.

---

## 3. Testing

`.venv\Scripts\python.exe` (Python 3.12.10):

- **`pytest`: 478 passed, 0 failed** (472 from `docs/27` + 1 new storage regression
  test + 5 new isolation regression tests = 478 — every test that exists now passes).
- **`ruff check .`:** clean.
- **`alembic upgrade head` / `alembic check`** (clean scratch DB): clean, no drift.
  The pre-existing `SAWarning: Cannot correctly sort tables; there are unresolvable
  cycles...` is still present — **not addressed by this milestone**, per instruction.

## 4. Manual Windows Verification

- Ran `hos-cli run-ai-workflow thumbnail` **5 times in a row**, fresh prompt template
  each time, same episode: all 5 succeeded (`Generated asset ...`, exit 0) — no
  intermittent failure across repeated real invocations.
- Launched the real `MainWindow` (offscreen, real `ThemeManager`/QSS applied — not a
  bare test widget) via a scratch script, navigated to the Episodes page, resized the
  window between 1000×700 and the app's enforced 640×480 floor: no crash, layout
  stayed coherent, `PageHeader._wrapped` stayed `False` at both sizes (screenshots
  captured and visually reviewed).
- **Observation, not a bug fixed here:** at the app's enforced 640px minimum window
  width, the sidebar's own width budget means `PageHeader` inside the Episodes page
  never actually narrows below its own 400px wrap threshold in the *embedded* app —
  the 300px-wrap behavior is a property of the widget itself, correctly exercised at
  the widget level (bare `PageHeader` in `qtbot.addWidget()`), which is why it's tested
  that way rather than by embedding in a full window. Noted for awareness; no
  production breakpoint was touched, per instruction.

## 5. Remaining Warnings

- `SAWarning: Cannot correctly sort tables; there are unresolvable cycles between
  tables "assets, character_versions, characters, shorts"...` — pre-existing, from
  `alembic/env.py`'s autogenerate/check path. **Not claimed fixed. Not addressed by
  this milestone.**
