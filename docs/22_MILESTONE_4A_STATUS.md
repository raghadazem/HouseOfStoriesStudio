# 22 — Milestone 4A Status: Application Shell

**Milestone:** 4A — Application Shell (first slice of Milestone 4, GUI)
**Status:** Complete. Stopped before Milestone 4B per instructions.

---

## 1. What Was Completed

Exactly the scope requested — the desktop shell and its first (only) functional screen, nothing else:

- **ApplicationContext** (`app/gui/context.py`): the single object owning configuration, the database engine/session factory, every `app.core.services` instance (lazy, cached), the `AIOrchestrator`, logging, and paths. No GUI code instantiates a service directly — see `docs/20_GUI_ARCHITECTURE.md` §1-2.
- **Centralized theme**: `ThemeTokens`/`Metrics` (`app/gui/theme/tokens.py`) + `ThemeManager` (`app/gui/theme/manager.py`) — light and dark, toggleable, persisted, zero hardcoded colors in any widget file. See `docs/21_DESIGN_SYSTEM.md`.
- **Settings storage**: `AppSettings` (`app/gui/settings.py`) — window geometry (size/position/maximized), theme, last-opened workspace, all via `QSettings`.
- **MainWindow shell**: `TopBar` (title "House of Stories Studio" / subtitle "بيت الحكايات", database/workspace/AI-provider/version, theme + about buttons), `Sidebar` (7 items, only Dashboard functional), a `QStackedWidget` page area, and a native `QStatusBar` (database, AI provider, workspace, current state).
- **Dashboard** (`app/gui/pages/dashboard_page.py`): the one functional screen — 6 summary cards wired to real service calls, 5 quick actions (2 fully implemented against real services, 2 honest "not implemented yet" dialogs, 1 that navigates), and a Recent Activity panel reading the real `data/logs/app.log`.
- **Reusable widget library**: `SummaryCard`, `SectionHeader`, `StatusBadge`, `SearchBox`, `PlaceholderPage`, `EmptyState`, `LoadingSpinner`/`LoadingOverlay`, and the four dialog helpers — see `docs/21_DESIGN_SYSTEM.md` §4.
- **47 new GUI tests** (`tests/gui/`), using `pytest-qt` in offscreen mode — 326 tests total, up from 280 at the end of Milestone 3.5 minus the GUI ones + 47 = see §5 for the exact count.

### What quick actions actually do

| Action | Behavior |
|---|---|
| ➕ Create Episode | `show_not_implemented` — no episode-creation form exists yet (real business-workflow UI, Milestone 4B scope) |
| 📂 Open Episode 001 | **Real**: queries `Episode` by number, shows its live title/stage/lesson/task-progress via `EpisodeService.calculate_episode_progress` in a dialog |
| 📥 Import Asset | `show_not_implemented` — a real file-picker/association form is Milestone 4B scope |
| ✨ Run Mock AI | **Real**: gets-or-creates a small reusable `PromptTemplate`, then runs the real `AIOrchestrator.run_workflow("thumbnail", provider_name="mock_provider", ...)` against Episode 001 — a genuine, if deliberately minimal, end-to-end exercise of the Milestone 3.5 AI layer. A second click correctly hits `ConflictError` (MockProvider's determinism) and shows a friendly explanation rather than a raw error. |
| ✅ Open Review Queue | **Real**: emits a signal `MainWindow` turns into an actual sidebar click — same code path as a user clicking "Review Queue" themselves |

No quick action or dashboard card fabricates data — every number and every dialog comes from a real service call or a real "not built yet" state.

## 2. Files Created and Modified

**Created (`app/gui/`, 21 files):**
```
app/gui/app.py
app/gui/context.py
app/gui/settings.py
app/gui/theme/__init__.py
app/gui/theme/tokens.py
app/gui/theme/manager.py
app/gui/widgets/__init__.py
app/gui/widgets/summary_card.py
app/gui/widgets/section_header.py
app/gui/widgets/status_badge.py
app/gui/widgets/search_box.py
app/gui/widgets/placeholder_page.py
app/gui/widgets/empty_state.py
app/gui/widgets/loading.py
app/gui/widgets/dialogs.py
app/gui/windows/__init__.py
app/gui/windows/main_window.py
app/gui/windows/sidebar.py
app/gui/windows/top_bar.py
app/gui/pages/__init__.py
app/gui/pages/dashboard_page.py
```

**Created (tests, 9 files):**
```
tests/gui/conftest.py
tests/gui/test_startup.py
tests/gui/test_theme.py
tests/gui/test_window_persistence.py
tests/gui/test_sidebar_navigation.py
tests/gui/test_dashboard.py
tests/gui/test_summary_cards.py
tests/gui/test_status_bar.py
tests/gui/test_settings_persistence.py
```

**Created (docs + screenshots):**
```
docs/20_GUI_ARCHITECTURE.md
docs/21_DESIGN_SYSTEM.md
docs/22_MILESTONE_4A_STATUS.md   (this file)
docs/screenshots/milestone_4a/01_startup.png
docs/screenshots/milestone_4a/02_dashboard_light.png
docs/screenshots/milestone_4a/03_dashboard_dark.png
docs/screenshots/milestone_4a/04_dashboard_light_2.png
docs/screenshots/milestone_4a/05_sidebar.png
docs/screenshots/milestone_4a/06_status_bar.png
```

**Modified:**
```
app/gui/__init__.py             (was a Milestone 1 placeholder docstring; now describes the real package)
pyproject.toml                  (+ hos-gui script entry, + pyside6/pytest-qt already-declared gui/dev extras used, + qt_api pytest setting)
tests/unit/test_repo_structure.py  (+ new REQUIRED_FILES/REQUIRED_DOCS entries; replaced the Milestone 1
                                    "app/gui must stay a placeholder" guardrail — now obsolete — with a
                                    lightweight direct-DB-import guardrail for app/gui)
```

No Milestone 1–3.5 file outside `test_repo_structure.py` was touched. No database schema change; no `app.core` file was modified.

## 3. Screenshots

All captured headlessly (`QT_QPA_PLATFORM=offscreen`) against a real seeded database with one real Mock AI generation already run, so the Dashboard shows genuine non-zero data.

| | |
|---|---|
| **Startup** | `docs/screenshots/milestone_4a/01_startup.png` |
| **Dashboard (light)** | `docs/screenshots/milestone_4a/02_dashboard_light.png` |
| **Dashboard (dark)** | `docs/screenshots/milestone_4a/03_dashboard_dark.png` |
| **Sidebar** | `docs/screenshots/milestone_4a/05_sidebar.png` |
| **Status bar** | `docs/screenshots/milestone_4a/06_status_bar.png` |

A real bug was caught by comparing the light and dark captures side by side, not by any automated test: in the first capture, the Dashboard's "Dashboard" section title was **invisible in dark mode** — its `QScrollArea` content widget had no QSS selector matching it, so it silently kept a light background while the (now dark-themed) title text rendered near-white-on-light-gray. Fixed by giving that widget `objectName("scrollContent")` and adding it (plus a general `QScrollArea > QWidget` rule for the scroll viewport itself) to `ThemeManager`'s background rule. The same pass also caught and fixed an ugly forced horizontal scrollbar on the Recent Activity list (a long JSON log line) by disabling the horizontal scrollbar and enabling right-elide instead. Both fixes are reflected in the screenshots above and covered by `docs/21_DESIGN_SYSTEM.md` §3.

## 4. Test Count and Results

```
$ QT_QPA_PLATFORM=offscreen pytest -q
........................................................................ [ 22%]
........................................................................ [ 44%]
........................................................................ [ 66%]
........................................................................ [ 88%]
.......................................                                  [100%]
327 passed in ~40s

$ ruff check .
All checks passed!
```

327 total (280 at the end of Milestone 3.5 → 327: 47 new GUI tests). GUI test breakdown (`tests/gui/`, all using `pytest-qt` + offscreen platform):

| File | Covers |
|---|---|
| `test_startup.py` | Application/`MainWindow` construction, all shell regions present, Dashboard is the initial page |
| `test_theme.py` | Default/explicit/invalid initial theme, `toggle()`, `theme_changed` signal, stylesheet actually changes |
| `test_window_persistence.py` | Default size with no saved settings, full save→restore round trip, `closeEvent` persists geometry |
| `test_sidebar_navigation.py` | All 7 nav items present, Dashboard vs. placeholder routing, exclusive selection, status-bar state text |
| `test_dashboard.py` | Empty-state on a fresh DB, real counts after seeding, all 5 quick actions (including the Mock AI success + deterministic-conflict paths), review-queue navigation signal, recent-activity log reading |
| `test_summary_cards.py` | `SummaryCard` in isolation: initial values, default placeholder, `set_value`/`set_subtitle`/`set_badge` |
| `test_status_bar.py` | Database/workspace/provider/state labels, state updates on navigation |
| `test_settings_persistence.py` | `AppSettings` round trips for theme, window geometry, last workspace — independent of any window |

GUI tests are skipped cleanly (not failed) when PySide6 isn't installed (`pytest.importorskip("PySide6")` in `tests/gui/conftest.py`), so a Milestone-1-3-only checkout's `pytest -q` is unaffected.

## 5. Manual Verification

Beyond the automated suite, run by hand against a real (temp) project directory:

1. `alembic upgrade head` + `hos-cli seed-demo` — clean.
2. Launched the GUI headlessly, constructed the real `MainWindow` — Dashboard showed real counts (1 episode, 2 characters) immediately, no crash, no fake data.
3. Toggled the theme both directions — stylesheet changed, icon flipped 🌙↔☀, no visual breakage (after the fix in §3).
4. Clicked every sidebar item — Dashboard works, all 6 others show `PlaceholderPage` with "Coming in Milestone 4B", selection stayed visually exclusive.
5. Ran every quick action manually: `Open Episode 001` showed real episode data; `Run Mock AI` created a real draft `Asset` and logged a real structured `generation_attempt` line; running it a second time correctly reported the deterministic-conflict case instead of crashing; `Open Review Queue` navigated the sidebar for real; `Create Episode`/`Import Asset` showed the honest "not implemented" dialog.
6. Closed the window, reopened a new one against the same `AppSettings` — geometry and theme both restored correctly.

## 6. Assumptions Made

1. **Dashboard's "open" and "run" quick actions were scoped to what's genuinely already implemented**, per the founder's explicit "only connect actions that already have a working service behind them" instruction — `Open Episode 001` and `Run Mock AI` do real work; `Create Episode`/`Import Asset` do not get a stub form, since building even a minimal one would cross into "business workflow" territory the milestone explicitly excludes.
2. **"Run Mock AI" targets Episode #1 and the `thumbnail` workflow specifically** (not a picker) — the simplest concrete, real exercise of the AI layer without building any selection UI, which is next-milestone scope.
3. **Recent Activity reads the last 12 lines of `data/logs/app.log` directly** (not a dedicated activity table/service) — matches Milestone 3.5's decision to keep generation logging file-based; a real Milestone 4B "Activity" concept, if wanted, would likely still read this same file.
4. **No background threading** — every service/DB call in Milestone 4A runs on the GUI thread. `LoadingOverlay` exists and is wired into the one action with a (currently trivial) delay, but nothing here actually needs it yet; see §7.
5. **`ApplicationContext.__init__` forces logging reconfiguration** (`configure_logging(..., force=True)`) rather than relying on the default idempotent behavior — necessary for correctness once more than one `ApplicationContext` can exist in one process (every GUI test), and arguably the more correct behavior for the real app too (each context is one full app session).

## 7. Known Limitations

- **No background threading.** Every quick action and every dashboard refresh runs synchronously on the GUI thread. For Milestone 4A's data volumes this is imperceptible; a future screen with heavier queries (or a real, slow AI provider) will need `LoadingOverlay` paired with a `QThread`/`QRunnable`, not just cosmetic show/hide around a synchronous call as `Run Mock AI` currently does.
- **`AppSettings.load_last_workspace()`/`save_last_workspace()` exist but nothing calls `save_last_workspace()` yet** — there is exactly one workspace (from `AppConfig`/environment variables) in this milestone, so multi-workspace switching has nothing to persist yet.
- **The offscreen test platform's small virtual screen (800×800)** meant one geometry-persistence test had to use a window size that fits within it — real Windows displays are obviously bigger; the persistence *mechanism* (`saveGeometry`/`restoreGeometry`) is standard Qt behavior, not something this milestone re-implemented.
- **No keyboard shortcuts, no menu bar, no drag-and-drop** — not requested for this milestone; the sidebar/quick-action buttons are the only interaction surface.
- **Search box exists but is inert** — no list screen exists yet for it to search against (Milestone 4B).

## 8. Recommended Next Step

Awaiting approval before Milestone 4B — building out the real screens behind today's placeholders (Episodes, Characters, Assets, Prompts, Review Queue, Settings), each calling `ApplicationContext` services exactly the way `DashboardPage` already does, reusing every widget from `docs/21_DESIGN_SYSTEM.md` §4 rather than inventing new ones.
