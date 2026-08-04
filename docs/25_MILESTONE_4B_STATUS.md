# 25 — Milestone 4B Status: Production Screens

**Milestone:** 4B — the six real production screens (Episodes, Characters, Assets, Prompt Manager, Review Queue, Settings)
**Builds on:** Milestone 4A's application shell (`docs/20_GUI_ARCHITECTURE.md`) and both UI/UX polish passes (`docs/23`, `docs/24`) — same design language, same widget library, same architecture rules.

---

## 0. What Did Not Change

- **Architecture is unchanged.** Every page still gets its data exclusively through `ApplicationContext` — no page imports `app.core.db` or instantiates a service directly. `app/gui/context.py` and `app/gui/settings.py` were not touched except passing `AppSettings` through to `SettingsPage`.
- **Design system is unchanged, only extended.** No existing token, QSS class, or widget was redesigned — this pass added new shared widgets and QSS classes for forms/lists/grids/dialogs and reused everything from `docs/21_DESIGN_SYSTEM.md` (`ElevatedCard`, `StatusBadge`, `PageHeader`... ) elsewhere unmodified.
- **Dashboard is unchanged**, except that its "Import Asset" quick action's target (a working Assets page) now exists — the quick action itself still calls the same `show_not_implemented`-free... actually see §5, it still shows a dialog since it doesn't navigate anywhere; that remains exactly as it was in Milestone 4A/the polish passes.

## 1. Scope: What Each Screen Actually Does

Every screen follows the same structure: `PageHeader` (title + primary action) → search/filter toolbar → content (list or grid) → `EmptyState` / `ErrorState` inline (not a modal) → optional `LoadingOverlay` during a write action.

| Screen | List/grid | Search + filters | Create | Detail/actions |
|---|---|---|---|---|
| **Episodes** | Row list (`EntityRow`) | Text search, pipeline-stage filter | Real form → `EpisodeService.create_episode_from_template` (also seeds the default 3 Shorts + task checklist) | Row click → read-only dialog: metadata, task progress, and the full `ProductionChecklistService` readiness report (pass/fail/blocking per check) |
| **Characters** | Card grid (`EntityCard`, `ResponsiveGrid`) | Text search, locked/unlocked filter | Real form → `CharacterService.create_character` | Card click → read-only dialog: traits, lock status, every design version with its status |
| **Assets** | Card grid, real thumbnails | Text search, type filter, approval-status filter | Real file import (native file picker) → `AssetImportService.import_asset` | Card click → preview dialog (real image where the type is previewable) + full metadata |
| **Prompt Manager** | Row list, grouped by category via filter | Text search (name + prompt text), category filter | Real form → `PromptTemplateService.create_prompt_template` | Row click → read-only dialog with the full prompt text |
| **Review Queue** | Plain `QFrame` rows (see §3) | Text search, source filter (per-provider + "Manually imported") | — (queue is populated by imports/generation, not created here) | Inline **Approve**/**Reject** buttons → `ApprovalService.decide_asset_review` (new — see §2). Reject requires a reason (a small required-text dialog), matching the service's existing notes requirement. |
| **Settings** | — (a form/diagnostics page, not a list) | — | — | Real theme toggle (same `AppSettings`/`ThemeManager` the top bar already uses), read-only workspace/database paths from `AppConfig`, per-modality AI provider status from `AIOrchestrator`, app version/about |

Nothing here is placeholder-only where real functionality was available — including two screens (Assets' Import, and the Review Queue's Approve/Reject) that had **never** had a working entry point anywhere in the app before this milestone, not even the CLI (the CLI's `list-review-queue` only ever listed; nothing previously decided).

## 2. One Core-Layer Addition: `ApprovalService.decide_asset_review`

`ApprovalService.approve_entity`/`reject_entity` only ever write an audit-trail `ApprovalRecord` — by design, the service docstring says entity-specific status transitions belong to that entity's own service (e.g. `CharacterVersionService.approve_character_version` mutates `CharacterVersion.status` *and* calls `approve_entity`). No such entity-specific wrapper existed for `Asset` — so nothing in the entire codebase, GUI or CLI, could actually move an asset out of `draft`. This is a real gap that made the Review Queue unbuildable as anything but a list.

**Added**, following the exact pattern `CharacterVersionService.approve_character_version`/`reject_character_version` already established:

```python
ApprovalService.decide_asset_review(session, asset_id, decision, *, notes=None, decided_by=None) -> Asset
```

Validates the asset is currently `draft`, moves `Asset.approval_status` to `approved`/`rejected`, and records the same `ApprovalRecord` audit row `approve_entity`/`reject_entity` already write — never one without the other. Raises `ValidationError` for a non-draft asset, an unsupported decision (`needs_changes` doesn't apply to assets — there's no "send back to draft" state, only reject-and-reimport), or a rejection without notes (reusing the same `_require_notes` the generic service already enforces). 6 new unit tests in `tests/unit/test_approval_service.py`.

## 3. Why Review Queue Rows Are Not `EntityRow`

Every other list screen uses `EntityRow`/`EntityCard` — both built as `QPushButton` subclasses specifically so the whole row/card is one keyboard-accessible click target (see `docs/21` §4's note on floating widgets, and the original accessibility rationale in `nav_icon.py`). Review Queue rows need **two independent interactive actions** (Approve, Reject) inline — Qt does not cleanly support a clickable child widget inside a `QPushButton` (the outer button's own click handling and the inner buttons' don't compose safely). So Review Queue rows are a plain `QFrame` (styled with a new `reviewRow` QSS class matching `EntityRow`'s look) containing two real `QPushButton`s, each independently focusable and keyboard-activatable. `EntityRow`'s own docstring now states this "read-only trailing content only" rule explicitly, so the next screen that needs inline actions doesn't try to force them into `EntityRow` either.

## 4. New Shared Widgets (`app/gui/widgets/`)

| Widget | Purpose |
|---|---|
| `ErrorState` | Inline "something went wrong" block + Retry button — used by every list page's DB-not-ready state instead of a modal dialog on every `refresh()` |
| `PageHeader` | The one-per-page title bar (title, subtitle, optional primary action button) — distinct from `SectionHeader`, which titles a sub-section *within* a page (Dashboard's "Overview") |
| `EntityRow` | Accessible (`QPushButton`-based) clickable list row — icon chip, title, subtitle, read-only trailing content |
| `EntityCard` | Accessible clickable grid tile — icon chip or a real thumbnail (`set_thumbnail`), title, subtitle, read-only trailing content |
| `ResponsiveGrid` | Reflows a list of cards into however many columns fit the current width on every resize — shared by Characters and Assets instead of two copies of the same flow-layout logic |
| `FormDialog` | Base for every create-form and read-only detail dialog: title, scrollable content area, inline validation-error line, Cancel/Save or single Close footer. `validate()` is the one method a subclass overrides. |
| `render_nav_icon` *(pre-existing, unchanged)* | — |
| `age_label` (`relative_time.py`) | Moved out of `dashboard_page.py` (was private `_age_label`) into a shared module once Review Queue needed the identical "how long has this been waiting" calculation — one implementation, not two copies drifting apart |

`SearchBox` gained a `text_changed` signal (live filter-as-you-type) — every list page connects it; Milestone 4A only ever wired `return_pressed`, since no list screen existed yet to filter live.

## 5. QSS Additions

New classes only — nothing existing was restyled: `pageTitle`/`pageSubtitle`, `entityRow`/`entityRowTitle`/`entityRowSubtitle` (+ hover/focus), `entityCard`/`entityCardThumb`/`entityCardThumb-image`/`entityCardTitle`/`entityCardSubtitle` (+ hover/focus), `reviewRow`, a `danger` button variant (Reject), `dialogTitle`/`formLabel`/`formError`, and base styling for `QComboBox` (+ its dropdown popup), `QTextEdit`/`QPlainTextEdit`, `QSpinBox`, and `QCheckBox` — none of these input types had any styling before this pass since no form existed to need them.

## 6. A Real Bug Found and Fixed: `QComboBox.currentData()` Silently Drops Enum Identity

**The bug:** Every `AssetType`/`PromptCategory`/`PromptType`/`PipelineStage` value in this codebase is a `str`-subclassed Python `enum.Enum` (`class AssetType(str, enum.Enum)`). When such a value is stored as a `QComboBox` item's data (`addItem(text, AssetType.IMAGE)`) and read back via `currentData()`, PySide6/shiboken's `QVariant` packing sees the `str` base type and returns a **plain `str`** (`'image'`), not the enum member — silently, with no error or warning at the point of loss.

This didn't break every combo box equally:
- **Filter combo boxes** (episodes' stage filter, assets' type/status filters, prompts' category filter) compare the retrieved value with `==` against a real model field (`asset.asset_type == asset_type`). Since a `str`-subclassed enum equals any plain string matching its `.value`, these comparisons happen to evaluate correctly regardless — filtering was never actually broken.
- **The two create-dialogs that feed a real service call** were broken outright: `_ImportAssetDialog.result_request()` built `ImportRequest(asset_type=self.type_field.currentData())` — a plain string — and `AssetImportService.import_asset` explicitly checks `isinstance(request.asset_type, AssetType)`, raising `ValidationError` on *every single import attempt*. `_CreatePromptDialog.result_fields()` had the identical shape for `category`/`prompt_type` feeding `PromptTemplateService.create_prompt_template`.

**How it was found:** not by reading the code — by writing a GUI test for `AssetsPage._on_import_asset()` that exercised the real dialog-construction-and-read path (rather than constructing `ImportRequest` directly with a real enum, which is what an earlier, less careful manual smoke test had done and which masked the bug completely). That test **hung** — `ValidationError` was correctly caught by `_on_import_asset`'s exception handler, which called `show_error()`, which opens a real native `QMessageBox.critical()` — a *blocking modal dialog* with no user present under the offscreen test platform, hanging forever with no traceback and no crash. Tracked down via a binary-search of debug prints across the exact call chain (`app/core/services/asset_import_service.py`'s `import_asset`, temporarily instrumented and reverted) until the exact line was isolated, then confirmed by reproducing the same sequence outside the GUI layer with a hand-built `ImportRequest` (worked fine) versus through the real `QComboBox` (`ValidationError`, immediately obvious once reproduced without the blocking dialog in the way).

**The fix:** re-wrap `currentData()` through the enum constructor at the two call sites that need a real instance — `AssetType(self.type_field.currentData())`, `PromptCategory(...)`/`PromptType(...)` — restoring the actual enum member. Filter combo boxes were left as-is (already correct by str-enum equality, confirmed by dedicated tests), rather than changed defensively everywhere for its own sake.

Two regression tests lock this in: `test_assets_page.py::test_on_import_asset_adds_a_real_card` (exercises the real dialog → real service call → real DB write, would hang again without the fix) and `test_prompts_page.py::test_create_prompt_dialog_result_fields_use_real_enum_members` (asserts `isinstance(fields["category"], PromptCategory)` directly).

## 7. Files Created and Modified

**Created:**
```
app/gui/widgets/entity_row.py
app/gui/widgets/entity_card.py
app/gui/widgets/error_state.py
app/gui/widgets/page_header.py
app/gui/widgets/form_dialog.py
app/gui/widgets/responsive_grid.py
app/gui/widgets/relative_time.py
app/gui/pages/episodes_page.py
app/gui/pages/characters_page.py
app/gui/pages/assets_page.py
app/gui/pages/prompts_page.py
app/gui/pages/review_queue_page.py
app/gui/pages/settings_page.py
tests/gui/test_milestone_4b_widgets.py
tests/gui/test_episodes_page.py
tests/gui/test_characters_page.py
tests/gui/test_assets_page.py
tests/gui/test_prompts_page.py
tests/gui/test_review_queue_page.py
tests/gui/test_settings_page.py
docs/25_MILESTONE_4B_STATUS.md   (this file)
docs/screenshots/milestone_4b/*.png   (12 files — 6 screens × light/dark)
```

**Modified:**
```
app/core/services/approval_service.py   (+ decide_asset_review)
app/gui/pages/dashboard_page.py         (_age_label moved to relative_time.age_label; no behavior change)
app/gui/widgets/__init__.py             (+ new widget/helper exports)
app/gui/widgets/search_box.py           (+ text_changed signal)
app/gui/theme/manager.py                (+ QSS for pages/entity rows/cards/dialogs/forms — see §5)
app/gui/windows/main_window.py          (6 PlaceholderPage instances replaced with the real pages; every page refreshes on navigation, not just Dashboard; review_queue_page wired into the sidebar badge alongside dashboard_page)
app/gui/windows/sidebar.py              (all 6 NavItems now implemented=True)
tests/gui/test_sidebar_navigation.py    (updated: every nav item now asserts its own real page, not PlaceholderPage)
tests/unit/test_approval_service.py     (+ 6 tests for decide_asset_review)
tests/unit/test_repo_structure.py       (+ this doc in REQUIRED_DOCS)
docs/21_DESIGN_SYSTEM.md                (+ ErrorState/PageHeader/EntityRow/EntityCard/ResponsiveGrid/FormDialog/age_label in the widget catalog; SearchBox row updated for text_changed)
```

No file under `alembic/` or `app/cli/` was touched. `app/core/models/` was not touched — `decide_asset_review` only adds a service method, no schema change.

## 8. Test Count and Results

```
$ QT_QPA_PLATFORM=offscreen pytest -q
447 passed in ~53s

$ ruff check .
All checks passed!
```

447 total (370 at the end of the second UI/UX polish pass → 447: 77 net-new):
- `tests/unit/test_approval_service.py` (+6): `decide_asset_review` approve/reject/non-draft/bad-decision/missing-asset.
- `tests/gui/test_milestone_4b_widgets.py` (21, new file): `ErrorState`, `PageHeader`, `EntityRow`/`EntityCard` (accessibility — real `QPushButton`, real `clicked` signal), `FormDialog` (validate-blocks-accept, accept-path, close-only mode), `ResponsiveGrid` (column count follows width), `age_label` (aware + naive-treated-as-UTC).
- `tests/gui/test_episodes_page.py` (9), `test_characters_page.py` (9), `test_assets_page.py` (11), `test_prompts_page.py` (8), `test_review_queue_page.py` (8), `test_settings_page.py` (6): empty/real-data states, live search, every filter, create-form validation, the create → real DB row flow, detail-dialog construction, and (Review Queue) approve/reject actually flipping `Asset.approval_status` in the database.
- `tests/gui/test_sidebar_navigation.py`: updated in place (no net count change) for six real pages instead of `PlaceholderPage`.

## 9. Known Limitations

- Character *design* versions (Character Lock — creating/approving a new `CharacterVersion` with a master prompt, color palette, etc.) are not editable from the Characters page — only browsable read-only. `CharacterVersionService`'s workflow is substantial enough to be its own future screen rather than a tab bolted onto this one.
- Episode/Character/Prompt create forms cover the fields each service's `create_*` method actually requires plus a handful of common optional ones — not every column on the model (e.g. Episode's `runtime_target_minutes_min/max`, `dialogue_language`). Consistent with the "a form a person can fill in thirty seconds" scope decision, not an oversight.
- The Assets page's Import flow classifies by `AssetType` only (no episode/scene/character association picker) — an import that should link to a specific episode still needs the CLI or a future "Import into this episode" entry point from the Episode detail view.
- `ResponsiveGrid` recomputes columns on every `resizeEvent`, which is O(n) re-parenting of every card — fine at today's scale (a handful to a few dozen characters/assets), would need a smarter diff if a studio's asset library grows into the thousands.

## 10. Recommended Next Step

Awaiting approval before Milestone 5. Every new page reused the existing widget library and architecture without exception — Milestone 5 (whatever it covers next) should keep doing the same: extend `EntityRow`/`EntityCard`/`FormDialog`/`ResponsiveGrid` rather than building parallel one-off list/form patterns, and if a future screen needs an entity-specific status transition the generic `ApprovalService` doesn't yet own, follow the same pattern §2 used — a small, tested, entity-specific method that mutates state *and* records the audit trail in one call, never one without the other.
