# 23 — UI/UX Polish Status

**Milestone:** Dedicated UI/UX polish pass (between 4A and 4B)
**Scope:** Visual design and interaction only. No architecture, database, service, or business-logic changes.

---

## 0. What Did Not Change

Confirmed before anything else, since it's the hard constraint this whole pass worked inside:

- **Zero changes** to `app/core/` (models, services, db, ai).
- **Zero changes** to `app/gui/context.py` (`ApplicationContext`) or `app/gui/settings.py` (`AppSettings`) — the architecture from `docs/20_GUI_ARCHITECTURE.md` is untouched.
- **Zero new database migrations.** The Production Progress panel (§3) reads the existing `Episode.pipeline_stage` column through the existing query pattern already used by the "Open Episode 001" quick action — nothing new is stored.
- **Every quick-action handler's business logic is byte-for-byte the same** as Milestone 4A — `_on_open_episode_001`, `_on_run_mock_ai`, `_on_create_episode`, `_on_import_asset`, `_on_open_review_queue` all call the exact same services in the exact same order with the exact same error handling. Only the widget they're wired to changed (`ActionCard` instead of `QPushButton`).

## 1. Better Space Utilization

**Decision:** Widen the content margins from `spacing_lg` (24px) to `spacing_xl` (32px) on the sides while *tightening* the vertical rhythm between sections, and give both the Production Progress and Recent Activity sections their own bordered card container (previously they sat directly on the bare background). A page of naked whitespace between floating elements reads as "unfinished"; the same whitespace organized into clearly bounded zones reads as "structured." Nothing was shrunk to "fit more in" — the fix was organizing the existing space, not cramming.

## 2. Improved Summary Cards

**Decision:** Each card now has:
- A **32×32px icon chip** (tinted rounded square, using the new `accent_soft` token) instead of a bare emoji glyph — establishes a consistent "icon has a home" pattern seen in Notion/Linear.
- **Hover elevation** (see §9) — every card now visibly lifts on hover, communicating "this card represents something," even though not all of them are currently clickable.
- An **optional thin progress bar** (`SummaryCard.set_progress()`) — wired into the Production Tasks card (`(total - open) / total`), the one card where "how much is done" is more informative than the raw open-task count alone.
- Kept the existing title → value → subtitle/badge hierarchy from Milestone 4A (it already had reasonable hierarchy) but increased the icon's visual weight and added the chip background so the header row doesn't read as flat text.

## 3. Production Progress

**Decision:** A new full-width panel above the summary cards, showing a 7-stage horizontal stepper: **Script → Storyboard → Images → Voice → Video → SEO → Upload** (the founder's own example stages), with the current stage's dot highlighted, completed stages checked and filled, and upcoming stages muted.

This reads **Episode #1's existing `pipeline_stage` field** (`app/core/db/enums.py::PipelineStage`, unchanged, 14 possible values from Milestone 2) through the same `session.query(Episode).filter_by(number=1)` pattern the Dashboard already used for "Open Episode 001." The 14 real values are grouped into the 7 display stages by a **GUI-only constant dict** (`_STAGE_TO_STEP_INDEX` in `dashboard_page.py`) — e.g. `IDEA`/`LESSON`/`OUTLINE`/`SCRIPT` all map to step 0 ("Script"), `IMAGE_PROMPTS`/`VIDEO_PROMPTS`/`THUMBNAIL` all map to step 2 ("Images"). This is a display grouping, not a new business rule: it doesn't change what's stored, doesn't validate anything, and doesn't affect `change_production_stage`/`change_episode_status` in `EpisodeService`. If there's no active episode, the panel shows an `EmptyState` instead of a stepper — never a fake/zeroed progress bar.

## 4. Recent Activity

**Decision:** Replaced the raw-log-line `QListWidget` with `ActivityTimeline`, which parses the exact same `data/logs/app.log` lines (format unchanged, `app/logging_setup.py` untouched) into icon + friendly title + relative timestamp rows:

- AI generation attempts (the JSON payload after `"generation_attempt "`, written by `app/core/ai/generation_logger.py` — also unchanged) are decoded into a plain sentence: `✨ Generated thumbnail via mock_provider` on success, `⚠️ Thumbnail generation failed (ConflictError)` on failure — instead of a wall of raw JSON.
- Seed-data lines get 🌱, warnings ⚠️, errors ❌, everything else ℹ️.
- Timestamps render as "just now" / "5m ago" / "3h ago" / "2d ago" (falling back to an absolute date past a week) instead of a raw `2026-08-03 12:00:00`.
- All parsing lives in `app/gui/widgets/activity_timeline.py` — a pure GUI-layer read of an existing file format, not a new logging concept.

## 5. Quick Actions

**Decision:** Replaced the plain `QPushButton` row with `ActionCard` — a bigger icon, a bold title, and a one-line description ("Generate a test thumbnail", "See what's pending"), styled and hover-elevated like the summary cards so the whole Dashboard reads as one consistent card language rather than "cards up top, buttons below." Every card still emits one plain `clicked` signal — the click semantics and the five handlers behind them are unchanged from Milestone 4A.

## 6. Top Bar

**Decision:**
- **Branding promoted**: added the new `AppLogo` mark (§7) at the left, and increased the title from 15px/600-weight to 21px/700-weight.
- **Technical metadata demoted**: the three separate labeled fields (`🗄 studio.db`, `📁 production`, `🤖 mock_provider`) plus dividers plus version were consolidated into **one small, muted line** (`studio.db · production · mock_provider · v0.1.0`) with no icons. The information is unchanged and still fully visible — it just no longer visually competes with the brand for the eye's first stop. The same details remain in full, labeled form in the status bar (`Database: studio.db`, `AI Provider: mock_provider`, `Workspace: <path>`), which is where a "what exactly is this instance connected to" question is answered in full.

## 7. Branding

**Decision:** A small custom-painted mark (`app/gui/widgets/app_logo.py`) — a rounded accent-colored badge with a minimal geometric glyph (a roofline meeting a spine, reading as both a simple house silhouette and an open book) drawn with `QPainterPath`. Deliberately **not** an external image file: no PNG/SVG asset is added to the repository, it re-colors itself automatically when the theme changes (reads `ThemeManager.tokens` at paint time, same pattern as `LoadingSpinner`), and it stays crisp at any size. No cartoon/storybook illustration — flat geometry only, matching the "elegant and minimal, no childish graphics" brief.

## 8. Dashboard Hierarchy

**Decision:** Rebuilt `DashboardPage`'s layout in exactly the requested reading order:

1. **Branding** — lives in the top bar, above the page, not duplicated inside it.
2. **Production Progress** — first thing inside the scrollable content.
3. **Dashboard Summary** ("Overview") — the 6 cards.
4. **Quick Actions** — the 5 action cards.
5. **Recent Activity** — last.

Verified visually in both themes (screenshots below) and by an explicit widget-order assertion isn't necessary here since Qt layout order *is* visual order — checked by eye against both screenshots.

## 9. Animations — What Qt Actually Allows, Honestly

Qt Style Sheets have **no equivalent of CSS `transition`** — a `:hover` rule swaps a style instantly, it cannot ease between two values. Where "animation" below means a real `QPropertyAnimation`, it's called out explicitly; where it means an instant QSS state change (still valuable interaction feedback, just not eased), that's called out too.

| Requested | What was built | Real animation? |
|---|---|---|
| Hover transitions | `ActionCard`/`SummaryCard` border color change on hover | QSS instant state change |
| Card elevation | `ElevatedCard` — every card's drop-shadow blur radius (0→24px) and vertical offset animate on hover enter/leave via `QGraphicsDropShadowEffect` + `QPropertyAnimation`, 160ms, `OutCubic` easing | **Yes** — real animation |
| Button animations | Standard `QPushButton`s (none remain on the Dashboard — all became `ActionCard`s) keep QSS hover/press states | QSS instant state change |
| Smooth page transitions | Every sidebar navigation (and the very first Dashboard view) fades the new page in from 0→1 opacity over 180ms via `QGraphicsOpacityEffect` + `QPropertyAnimation`, in `MainWindow._animate_page_transition` | **Yes** — real animation |

This is a genuine, if Qt-appropriate, reading of "subtle professional animations" — not an overclaim. A real CSS-`transition`-equivalent for every hover state would require animating a custom property on every single widget individually; done here only where it earns its cost (cards, page switches), not sprinkled everywhere for its own sake.

## 10. Polish

- **Corner radius** increased across the board (`radius_sm` 6→8, `radius_md` 10→12, `radius_lg` 14→16) for a softer, more premium feel.
- **Type scale** adjusted (`font_size_lg` 20→21, `font_size_xl` 26→28) to give the app title and card values slightly more presence without breaking the existing scale's proportions.
- **Top bar height** increased 56→64px to give the new logo mark room to breathe.
- **New `accent_soft` token** (a tinted accent background, distinct per theme) added to `ThemeTokens` — used by icon chips and the "current" step dot, the one new color this pass needed that the existing 19-token palette didn't already cover.
- **Icon consistency**: every card/action/step icon now sits inside a fixed-size container (chip, dot, or the action card's own icon row) instead of floating at inconsistent baseline positions.

## 11. A Real Bug Found and Fixed During This Pass

Both `ProgressStepper.set_progress()` and `ActivityTimeline.set_entries()` need to be callable more than once (the Dashboard rebuilds them on every `refresh()`). Their `_clear()` methods originally only called `widget.deleteLater()` on the old child widgets after `takeAt()`-ing them out of the layout. `deleteLater()` only *schedules* destruction for the next event-loop turn — a widget that's been pulled out of a layout but not yet destroyed **keeps its last computed geometry and stays visible**, so the very next `set_progress()`/`set_entries()` call (which `DashboardPage.__init__` triggers immediately via `refresh()`, before the event loop gets a turn) built a second set of widgets on top of the first, still-visible one. This showed up unmistakably in an early screenshot: the stepper's dots read "1, 2, 2, 3, 4, 3, 5, 6, 4, 7, 5, 6, 7" — two overlapping renders. Fixed by calling `widget.setParent(None)` immediately in both `_clear()` methods, before scheduling `deleteLater()`. Caught by comparing screenshots before writing a single test — a good reminder that visual review catches a category of bug automated tests (which happily passed throughout) do not.

## 12. Files Created and Modified

**Created:**
```
app/gui/widgets/app_logo.py
app/gui/widgets/elevated_card.py
app/gui/widgets/progress_stepper.py
app/gui/widgets/action_card.py
app/gui/widgets/activity_timeline.py
tests/gui/test_ui_polish_widgets.py
docs/23_UI_UX_POLISH_STATUS.md   (this file)
docs/screenshots/ui_polish/01_startup.png
docs/screenshots/ui_polish/02_dashboard_light.png
docs/screenshots/ui_polish/03_dashboard_dark.png
docs/screenshots/ui_polish/04_dashboard_light_2.png
docs/screenshots/ui_polish/05_sidebar.png
docs/screenshots/ui_polish/06_status_bar.png
```

**Modified:**
```
app/gui/theme/tokens.py            (+ accent_soft token; radius/font-size/topbar_height tuning)
app/gui/theme/manager.py           (+ QSS for iconChip, cardProgress, actionCard*, stepDot-*/stepLabel-*/stepConnector*, activityRow/Icon/Title; appTitle size/weight bump)
app/gui/widgets/summary_card.py    (now extends ElevatedCard; + icon chip, + set_progress())
app/gui/widgets/__init__.py        (+ new widget exports)
app/gui/windows/top_bar.py         (+ AppLogo; consolidated meta line; requires ThemeManager now)
app/gui/windows/main_window.py     (+ page-transition fade animation; passes theme to TopBar)
app/gui/pages/dashboard_page.py    (full layout restructure to the new hierarchy; Production Progress panel; ActionCard/ActivityTimeline wiring — quick-action handler bodies unchanged)
tests/gui/test_dashboard.py        (updated for renamed/replaced widgets; + Production Progress test)
tests/gui/test_status_bar.py       (updated for TopBar's consolidated meta label)
docs/21_DESIGN_SYSTEM.md           (updated widget catalog and tokens)
tests/unit/test_repo_structure.py  (+ this doc in REQUIRED_DOCS)
```

No file under `app/core/`, `alembic/`, or `app/cli/` was touched.

## 13. Before / After

Same seeded data, same window size, same theme-toggle sequence, for a fair comparison — the earlier ("before") screenshots are `docs/screenshots/milestone_4a/`, sent again for reference:

| | Before (Milestone 4A) | After (this pass) |
|---|---|---|
| Dashboard, light | `docs/screenshots/milestone_4a/02_dashboard_light.png` | `docs/screenshots/ui_polish/02_dashboard_light.png` |
| Dashboard, dark | `docs/screenshots/milestone_4a/03_dashboard_dark.png` | `docs/screenshots/ui_polish/03_dashboard_dark.png` |
| Sidebar | `docs/screenshots/milestone_4a/05_sidebar.png` | `docs/screenshots/ui_polish/05_sidebar.png` |
| Status bar | `docs/screenshots/milestone_4a/06_status_bar.png` | `docs/screenshots/ui_polish/06_status_bar.png` |

## 14. Test Count and Results

```
$ QT_QPA_PLATFORM=offscreen pytest -q
349 passed in ~47s

$ ruff check .
All checks passed!
```

349 total (327 at the end of Milestone 4A → 349: 22 new tests, all in `tests/gui/`). Breakdown of what's new:

- `tests/gui/test_ui_polish_widgets.py` (20 tests): `AppLogo` construction and paint-in-both-themes, `ElevatedCard`'s card class/shadow effect and hover-animation target values, `SummaryCard.set_progress` (default hidden, shows + sets value, clamps out-of-range), `ProgressStepper` (widget count, done/current/upcoming state mapping, `None`-index all-upcoming, rebuild-doesn't-leak), `ActionCard` click signal, and the full `parse_log_line`/`format_relative_time` matrix (plain/seed/warning/error lines, successful and failed generation-attempt JSON, malformed lines, all four relative-time buckets).
- `tests/gui/test_dashboard.py` (+2): Production Progress panel reflects a seeded episode's real `pipeline_stage` correctly mapped to the stepper; fresh-database empty state now also asserts the progress panel's empty state.
- `tests/gui/test_status_bar.py` (updated, not net-new): top-bar assertion updated for the consolidated meta label.

## 15. Known Limitations

- Real CSS-style hover transitions on ordinary buttons/links are not implemented (see §9) — a genuine Qt Style Sheet limitation, not an oversight.
- `ProgressStepper`/`ActivityTimeline` rebuild their entire contents on every `set_progress()`/`set_entries()` call rather than diffing — acceptable at today's scale (7 steps, ≤12 activity rows); would need revisiting if either list grows to hundreds of items.
- The Production Progress panel only ever shows Episode #1 (same scope limitation the "Open Episode 001"/"Run Mock AI" quick actions already had in Milestone 4A) — a real episode picker is Milestone 4B scope, not touched here.

## 16. Recommended Next Step

Awaiting approval before Milestone 4B. This pass changed presentation only — every Milestone 4B screen can build on exactly the same `ApplicationContext`/service-access pattern, and should reuse `ElevatedCard`/`ActionCard`/`ProgressStepper`/`ActivityTimeline` wherever they fit rather than introducing parallel one-off widgets.
