# 20 — GUI Architecture

**Milestone:** 4A — Application Shell
**Package:** `app/gui/`

---

## 1. The One Rule

`app/gui` never touches the filesystem or the database directly, and never instantiates a `app.core.services.*` class itself. Every page/widget reaches services, the database, configuration, logging, and the AI orchestrator through exactly one object: `ApplicationContext` (`app/gui/context.py`).

```python
class DashboardPage(QWidget):
    def __init__(self, ctx: ApplicationContext, theme: ThemeManager, parent=None):
        ...
        episode_count = len(self._ctx.episode_service.list_episodes(session))
```

Never:

```python
episode_count = len(EpisodeService().list_episodes(session))  # ✗ — GUI must not do this
```

This is the same discipline Milestone 3 already applies to the filesystem (`StorageService` is the only thing that touches disk) and to approvals (`ApprovalService` is the only thing that writes an `ApprovalRecord`) — Milestone 4A applies it one layer up: the GUI is a thin presentation layer over the exact same service layer the CLI already uses. Nothing in `app/core` changed to make this possible — Milestone 4A adds zero new business logic, only presentation.

A cheap static guardrail (`tests/unit/test_repo_structure.py::test_gui_never_imports_db_or_core_services_internals_directly`) greps `app/gui/*.py` for direct imports of `app.core.db.engine`/`app.core.db.seed` outside `context.py`, catching an obvious violation early — it is not a full import-boundary analysis.

## 2. ApplicationContext

```python
ctx = ApplicationContext()          # or ApplicationContext(config) for a specific AppConfig

ctx.config                          # AppConfig — paths, log level, restricted dirs
ctx.engine, ctx.session_factory     # SQLAlchemy engine/sessionmaker
ctx.logger                          # "house_of_stories.gui" logger

ctx.episode_service                 # EpisodeService() — lazy, cached per context
ctx.character_service               # CharacterService()
ctx.character_version_service       # CharacterVersionService()
ctx.storage_service                 # StorageService(ctx.config)
ctx.asset_import_service            # AssetImportService(ctx.config, ctx.storage_service)
ctx.prompt_template_service         # PromptTemplateService()
ctx.approval_service                # ApprovalService()
ctx.license_service                 # LicenseService()
ctx.production_task_service         # ProductionTaskService()
ctx.production_checklist_service    # ProductionChecklistService()
ctx.export_package_service          # ExportPackageService()
ctx.scene_service, ctx.short_service
ctx.ai_orchestrator                 # AIOrchestrator()

ctx.session_scope()                 # contextmanager — commit on success, rollback on error
ctx.open_session()                  # a plain, caller-managed Session — for read-only queries
```

Every service property is a `functools.cached_property`: built once per `ApplicationContext` instance (a "session" of the running app), not once per call. Since every Milestone 3 service is stateless and cheap to construct, this is mostly about having **one place** to change if a service ever needs shared state later — not a performance optimization.

### Session usage pattern

Pages follow the exact same unit-of-work convention `app/core/services` already documents:

- **Read-only work** → `with ctx.open_session() as session:` — no commit, just closes.
- **Writes** → `with ctx.session_scope() as session:` — commits at the end, rolls back and re-raises on any exception.
- `AssetImportService.import_asset` (and, through it, every `AIOrchestrator.run_workflow` call) still owns its own transaction, exactly as in Milestone 3/3.5 — a page wrapping such a call in `session_scope()` just adds a second, effectively-no-op commit afterward; it does **not** create a second real transaction boundary.

See `app/gui/pages/dashboard_page.py::_on_run_mock_ai` for a worked example (and a real bug this exact reasoning caught: an earlier version used `open_session()` for a call path that also creates a `PromptTemplate` row, which could have left that row uncommitted if a later step raised before `AssetImportService`'s own internal commit — fixed by switching to `session_scope()`).

## 3. Module Layout

```
app/gui/
├── app.py                    # main() — builds QApplication, ApplicationContext, ThemeManager, MainWindow
├── context.py                 # ApplicationContext
├── settings.py                 # AppSettings — the only QSettings touchpoint
├── theme/
│   ├── tokens.py                # ThemeTokens (light/dark), Metrics — every literal color/spacing lives here
│   └── manager.py               # ThemeManager — builds + applies the QSS stylesheet, owns theme_changed signal
├── widgets/                    # reusable, page-agnostic components (see docs/21)
│   ├── summary_card.py, section_header.py, status_badge.py, search_box.py,
│   ├── placeholder_page.py, empty_state.py, loading.py, dialogs.py
├── windows/
│   ├── main_window.py           # MainWindow — top bar + sidebar + page stack + status bar
│   ├── sidebar.py                # Sidebar + NAV_ITEMS (the one place nav entries are listed)
│   └── top_bar.py                # TopBar
└── pages/
    └── dashboard_page.py         # the one functional screen this milestone builds
```

Every other sidebar section (`Episodes`, `Characters`, `Assets`, `Prompts`, `Review Queue`, `Settings`) currently renders `PlaceholderPage(item.label)` — see §5.

## 4. MainWindow Composition

```
QMainWindow
└── centralWidget (QVBoxLayout)
    ├── TopBar               (title/subtitle, database/workspace/provider/version, theme + about buttons)
    └── body (QHBoxLayout)
        ├── Sidebar           (fixed width, 7 nav buttons)
        └── QStackedWidget    (one page per nav item)
QStatusBar (native, via self.statusBar())
    ├── "Database: <name>"
    ├── "AI Provider: <providers or 'none configured'>"
    ├── "Workspace: <production_dir>"
    └── (permanent, right-aligned) current application state, e.g. "Viewing Dashboard"
```

`Sidebar.item_selected(str)` is the single source of navigation truth — `MainWindow._on_nav_selected` switches the stack page and updates the status bar's state label. A Dashboard quick action that needs to navigate (`Open Review Queue`) does **not** call `stack.setCurrentWidget` itself; it emits `DashboardPage.navigate_requested(key)`, which `MainWindow.navigate_to` turns into a real `sidebar.button_for(key).click()` — the same code path a user's actual click takes, not a shortcut around it.

## 5. Placeholder Pages (Milestone 4B scope)

Every sidebar item except Dashboard renders a `PlaceholderPage` reading "Coming in Milestone 4B." Quick actions with no working screen behind them yet (`Create Episode`, `Import Asset`) show the same message via `widgets.dialogs.show_not_implemented`. Nothing about this milestone pretends unbuilt functionality exists — every placeholder is honest about being unbuilt.

## 6. Settings Persistence

`app/gui/settings.py::AppSettings` is the **only** file that constructs a `QSettings`. It persists:

- window geometry (size, position, maximized state) — via `QMainWindow.saveGeometry()`/`restoreGeometry()`, which Qt already encodes maximized/full-screen state into
- the active theme name
- the last-opened workspace path (stored, not yet read anywhere — no multi-workspace switching exists yet; wiring it up is Milestone 4B+ scope)

Backed by `QSettings("HouseOfStoriesStudio", "Studio")` in the real app (native OS storage: registry on Windows, plist on macOS, ini on Linux) — tests instead construct `AppSettings` with an explicit ini-file-backed `QSettings`, fully isolated per test (`tests/gui/conftest.py::gui_settings`).

## 7. Theme Integration

`ThemeManager` (owned by `app.py`, threaded through to `MainWindow` and `DashboardPage`) is the only thing that calls `QApplication.setStyleSheet()`. See `docs/21_DESIGN_SYSTEM.md` for the full token/QSS mechanism. The one thing worth calling out here: **the theme is applied to the whole window tree**, including the `QScrollArea` viewport inside `DashboardPage` — every themed container needs either a QSS type selector or an explicit `objectName`/`class` property; a widget with neither silently keeps Qt's default palette background regardless of the active theme. (A real instance of this was caught and fixed during this milestone: the Dashboard's scroll content area had no matching selector, so its background stayed light-themed even in dark mode, making dark-themed text on it unreadable — see `docs/22_MILESTONE_4A_STATUS.md` §3.)

## 8. Testing

`tests/gui/` uses `pytest-qt` (the `qtbot`/`qapp` fixtures) with `QT_QPA_PLATFORM=offscreen`, set in `tests/gui/conftest.py` before PySide6 is imported — no real display needed, works identically in CI and on a Windows dev machine with a display. GUI tests are skipped cleanly (`pytest.importorskip("PySide6")`) when the `gui`/`dev` extras aren't installed, so `pytest -q` on a Milestone 1-3-only checkout still passes.

Fixtures (`tests/gui/conftest.py`):

- `gui_app_config` — isolated `AppConfig` (tmp_path-backed), same pattern as the core suite's `app_config`.
- `gui_context` — a real `ApplicationContext` with a freshly migrated (empty) schema.
- `gui_settings` — `AppSettings` backed by a throwaway ini file.
- `theme` — a `ThemeManager` bound to the shared `qapp`.

One real cross-test bug this suite caught: `ApplicationContext.__init__` originally called `configure_logging(self.config)` without `force=True` — since `configure_logging` is intentionally idempotent by default (see `app/logging_setup.py`), every `ApplicationContext` constructed after the *first* one in the same process (i.e. across GUI tests) would silently keep logging to the first test's temp log directory. Fixed by passing `force=True` — every context now always points logging at its own config, which is also the semantically correct behavior for the real app (each `ApplicationContext` is one app session).
