# 24 — UI/UX Polish Pass v2 Status

**Milestone:** A second, deeper UI/UX polish pass (still between 4A and 4B — Milestone 4B has not started)
**Scope:** Visual design, information architecture, and interaction only. No architecture, database, service, or business-logic changes.

---

## 0. What Did Not Change

- **Zero changes** to `app/core/` (models, services, db, ai).
- **Zero changes** to `app/gui/context.py` (`ApplicationContext`) or `app/gui/settings.py` (`AppSettings`).
- **Zero new database migrations, zero new tables/columns.** Every new number on the Dashboard is computed from data the schema already stores.
- **Every quick-action handler's business logic is byte-for-byte the same** as the first polish pass (`docs/23`) — `_on_open_episode_001`, `_on_run_mock_ai`, `_on_create_episode`, `_on_import_asset`, `_on_open_review_queue` call the exact same services in the exact same order with the exact same error handling.
- **No fabricated data, anywhere.** Every secondary metric added in this pass — "3 in production," "Oldest: 2h ago," "2 blocked," "14 generated all-time" — is a real query result. Two things were deliberately *not* built because they'd require fabrication: an "estimated completion time" (no time-tracking data exists in the schema) and an "AI Queue Status" widget (no real async queue exists in the architecture, and this pass could not add one). See §10.

## 1. Dashboard Cards

**Decision:** Every `SummaryCard` gained a real secondary metric via a new `set_caption()` method, and the two most "alive" cards (AI Studio, Pending Review) were promoted to a `hero=True` variant — bigger icon chip (48px vs 40px), bigger value (`font_size_xxl`, 36px), and a wider footprint in the grid (see §6). Concretely:

| Card | Value | Caption (real, computed) |
|---|---|---|
| AI Studio (hero) | Assets generated *today* | "`N` generated all-time" + `set_subtitle("via <provider>")` + a Configured/Not-configured badge |
| Pending Review (hero) | Count of assets awaiting review | "Oldest: `<age>`" (or "Nothing waiting") + a Needs-attention/All-clear badge |
| Episodes | Episode count | "`N` in production" (pipeline_stage != PUBLISHED) |
| Characters | Character count | "`N` locked" (has an `active_version_id`) |
| Assets | Asset count | "`N` approved" |
| Production Tasks | Open task count | "`N` blocked" via `ProductionTaskService.list_overdue_tasks()` (existing since Milestone 3, previously never called from the GUI) + a thin progress bar (unchanged from `docs/23`) |

Values now **count up** from their previous value via `SummaryCard.set_value_animated()` (a `QVariantAnimation`, 550ms, `OutCubic`) instead of snapping instantly — a small but real "this number is alive" cue every time `refresh()` runs.

## 2. Production Progress

**Decision:** Each of the 7 stepper stages (`docs/23`'s `Script → Storyboard → Images → Voice → Video → SEO → Upload`) now carries its own icon (📝 🧩 🖼️ 🎙️ 🎞️ 🔍 🚀) instead of a bare number, and the current stage's dot **pulses** — a `QGraphicsDropShadowEffect` whose `blurRadius` loops between 6px and 22px via a `QPropertyAnimation` (`setLoopCount(-1)`, 1100ms) — so "this is where we are right now" reads immediately without a caption. A `StatusBadge` in the panel's header (`SectionHeader`'s `trailing` slot) shows `"{percent}%"` — the stage index as a fraction of the 7 display stages, honest about being a *pipeline-position* percentage, not a time estimate (see §0/§10). No estimated completion time was added — the schema has no start/duration data to compute one from.

## 3. Quick Actions

**Decision:** `ActionCard`'s icon now sits in the same tinted `iconChip` `SummaryCard` uses — one consistent icon treatment across the whole Dashboard instead of the previous action-only "bare-emoji-on-a-differently-styled-row" look — and its minimum height grew 104→128px for a bigger click target. `:hover` now also tints the card's background (`accent_soft`), not just its border, for a more tactile hover state. The description label got its own `actionCardDescription` QSS class (distinct size/color from generic `muted`) rather than reusing a catch-all style.

## 4. Header

**Decision:** The four raw technical fields that previously sat in one small consolidated line (`studio.db · production · mock_provider · v0.1.0`) are gone from the header entirely. In their place:

- An **episode chip** (`🎬 <title>  ·  <stage>`, or "No active episode") — the header now answers "what am I working on," not "what file is this."
- A small **"Details ▾" toggle** that opens a popover with the same four fields, still fully labeled (Database / Workspace / AI Provider / Version), one click away.
- The status bar keeps showing the same information in full, unabbreviated form, exactly as before — nothing was actually removed, just demoted out of the primary eye-path.

## 5. Sidebar

**Decision:** The 7 nav items are now grouped under small uppercase section labels with hairline separators — **Workspace** (Dashboard) / **Production** (Episodes, Characters, Assets, Prompts) / **Review** (Review Queue) / **System** (Settings) — instead of one flat list. Selection is tracked by a **sliding indicator bar** (an absolutely-positioned `QFrame` whose `geometry` animates via `QPropertyAnimation`, 220ms `OutCubic`, to the newly-selected row) rather than an instant background swap. Review Queue carries a real notification badge — the actual pending-review count from `ApprovalService.list_pending_review_assets()`, never a placeholder number; it hides itself at 0 and caps its display at "99+".

## 6. Visual Hierarchy

**Decision:** The Overview section became an asymmetric **bento grid** instead of a uniform 3-column/2-row grid: row 0 holds the two hero cards (AI Studio, Pending Review), each spanning 2 of 4 grid columns; row 1 holds the four smaller, equally-weighted supporting cards (Episodes, Characters, Assets, Production Tasks). The two cards that get more visual weight are deliberately the two that answer "what does an AI studio actually want to know right now" (§10) — not an arbitrary choice.

## 7. Typography

**Decision:** Two new tokens widen the type scale: `font_size_xs` (10px — sidebar section labels, diagnostics captions, uppercase + letter-spaced) and `font_size_xxl` (36px — hero card values only). Existing weights were sharpened rather than just resized: `cardTitle` set to an explicit 500, `sectionTitle` bumped to 700 with `letter-spacing: -0.2px`, and every new label class (`cardCaption`, `actionCardDescription`, `diagnosticsLabel`/`diagnosticsValue`, `episodeChip`) got its own distinct size/weight/color instead of falling back to a shared generic class — titles, subtitles, captions, values, and descriptions are now visually distinguishable from each other at a glance, not just by position.

## 8. Icons

**Decision:** A small custom vector icon set (`app/gui/widgets/nav_icon.py`, `render_nav_icon()`) replaces emoji for the 7 sidebar items — the one piece of chrome visible on every screen in every state, and therefore the highest-leverage place to fix "mixed icon styles" (emoji render differently per platform/font; a hand-drawn `QPainterPath` glyph is pixel-consistent). Building a matching custom icon for every icon in the app (20+ across cards and quick actions) was judged out of scope for a polish pass — card/action icons still use emoji, a deliberate, documented scope decision, not an oversight.

`render_nav_icon()` renders into an offscreen `QPixmap`/`QIcon` rather than being a live custom-painted `QWidget`, specifically so `Sidebar` can keep using plain, checkable `QPushButton`s — preserving their built-in keyboard focus/Tab-navigation/Space-Enter activation. A live custom widget embedded as a button's visual would have broken that, which would have violated the explicit "keep accessibility" requirement for this pass.

## 9. Animations

Same honest framing as `docs/23` §9 — QSS has no `transition` equivalent; every entry below marked "real" is an actual `QPropertyAnimation`/`QVariantAnimation`, not an instant QSS state swap.

| What | How | Real animation? |
|---|---|---|
| Card value updates | `SummaryCard.set_value_animated()` — count up/down via `QVariantAnimation`, 550ms `OutCubic` | **Yes** |
| Current pipeline stage | `ProgressStepper`'s pulsing glow — `QGraphicsDropShadowEffect.blurRadius` looped via `QPropertyAnimation`, 1100ms | **Yes** |
| Sidebar selection | The indicator bar's `geometry` animates to the new row, 220ms `OutCubic` | **Yes** |
| Card hover elevation | Unchanged from `docs/23` — `ElevatedCard`'s shadow blur/offset | **Yes** (pre-existing) |
| Page transitions | Unchanged from `docs/23` — opacity fade, 180ms | **Yes** (pre-existing) |
| Action-card hover background | `accent_soft` tint on `:hover` | QSS instant swap |

## 10. AI Feeling

**Decision:** Three ideas from the brief's list were considered and rejected as fabrication (§0): a fake "Current AI Generation" progress indicator (no real in-flight generation state exists to show), a fake "AI Queue Status" (no real async queue exists in the architecture — the mock provider runs synchronously), and a fabricated ETA. What *is* real and was built instead:

- **AI Studio hero card** — today's + all-time real generation counts (`Asset.source_tool IS NOT NULL`, filtered by `created_at`), which provider is active, and a Configured/Not-configured badge.
- **Recent Activity** (unchanged from `docs/23`, already AI-aware) — every generation attempt already renders as `✨ Generated thumbnail via mock_provider` / `⚠️ Thumbnail generation failed (...)`.
- **Percent-through-pipeline badge** on Production Progress — an honest "how far along," not a time estimate.

Together these communicate "this is an AI-driven production tool" through real numbers, not a decorative widget with no data behind it.

## 11. Two Real Bugs Found and Fixed During This Pass

**Bug 1 — the diagnostics popover was clipped to a blank sliver.** `_DiagnosticsPopover` was originally a plain child `QWidget` of `TopBar`, which is only `topbar_height` (64px) tall. Qt clips a child widget's painting to its parent's rectangle — a well-known but easy-to-forget gotcha — so the popover's 4-row, ~160px-tall content only ever showed the top ~4px of itself: a near-invisible white sliver, confirmed by an offscreen `window.grab()` screenshot during manual verification. **Fixed** by giving the popover real window flags (`Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint`, plus `WA_TranslucentBackground` so its QSS-drawn rounded corners render correctly against a transparent surround) so it becomes its own top-level window, positioned via `mapToGlobal` instead of `mapTo(parent, ...)`. Caught by rendering the popover to its own image and comparing against the intended 4-row layout — the same "actually look at a screenshot" discipline that caught the overlapping-stepper bug in `docs/23` §11; automated tests never exercised this because none of them asserted on the popover's rendered geometry before this pass. A regression test (`test_diagnostics_popover_is_a_top_level_window_not_clipped_by_topbar`) now asserts `popover.isWindow()` and the `Qt.WindowType.Tool` flag.

**Bug 2 — the sidebar's review-queue badge and the header's episode chip were blank on first launch.** `DashboardPage.refresh()` runs once automatically at the end of `DashboardPage.__init__` (so the widget is self-sufficient and testable standalone), and it emits `review_count_updated`/`episode_updated` at the end of that same `refresh()`. But `MainWindow._wire_signals()` — which connects those two signals to the sidebar badge and header chip — only runs *after* `DashboardPage` has already been constructed inside `MainWindow._build_layout()`. That first, real-data emission therefore had no listener yet: on a freshly opened app with actual pending-review assets, the sidebar badge stayed hidden and the header showed "No active episode" until the user navigated away from and back to the Dashboard. **Fixed** by calling `self.dashboard_page.refresh()` once more in `MainWindow.__init__`, immediately after `_wire_signals()` — a second, cheap read-only query at startup, now with listeners attached, so the very first frame the user sees is correct. Caught the same way: an offscreen screenshot of a freshly-seeded window showed the badge missing despite two pending-review assets existing. A regression test (`test_review_queue_badge_shows_real_count_on_first_launch`) constructs `MainWindow` directly (no manual `refresh()`/navigation) against a database with 3 pending-review assets and asserts the sidebar badge already reads "3".

## 12. Files Created and Modified

**Created:**
```
app/gui/widgets/nav_icon.py
tests/gui/test_ui_polish_v2_widgets.py
docs/24_UI_UX_POLISH_V2_STATUS.md   (this file)
docs/screenshots/ui_polish_v2/01_dashboard_light.png
docs/screenshots/ui_polish_v2/02_dashboard_dark.png
docs/screenshots/ui_polish_v2/03_sidebar_grouped.png
docs/screenshots/ui_polish_v2/04_diagnostics_popover.png
```

**Modified:**
```
app/gui/theme/tokens.py            (+ font_size_xs, font_size_xxl; sidebar_width 232->240)
app/gui/theme/manager.py           (+ QSS for episodeChip, diagnosticsToggle/Popover/Label/Value, sidebarSectionLabel/Separator/Indicator/Badge, card-hero/cardValue-hero/cardCaption/iconChip-hero, actionCard hover tint + actionCardDescription)
app/gui/widgets/summary_card.py    (+ hero variant, set_value_animated(), set_caption())
app/gui/widgets/action_card.py     (icon reuses iconChip; taller min height; actionCardDescription class)
app/gui/widgets/progress_stepper.py (+ per-step icons, current-stage pulse animation)
app/gui/windows/top_bar.py         (episode chip + diagnostics popover replace the consolidated meta line; popover is now a real top-level window, not a clipped child — bug 1 above)
app/gui/windows/sidebar.py         (+ grouping/separators, sliding selection indicator, notification badge, custom vector icons; NavItem gained `group`, `icon` renamed `glyph`; now requires a ThemeManager)
app/gui/windows/main_window.py     (wires episode_updated/review_count_updated to TopBar/Sidebar; refreshes the dashboard once more after wiring — bug 2 above)
app/gui/pages/dashboard_page.py    (bento-grid Overview; real secondary-metric captions; AI Studio hero card replaces the old provider card; percent-complete badge on Production Progress; new episode_updated/review_count_updated signals; _age_label() UTC-aware relative-time helper)
tests/gui/test_dashboard.py        (updated for caption-based captions, hero AI card, animated values)
tests/gui/test_status_bar.py       (updated: header no longer shows the meta line — the assertion now checks the diagnostics popover instead)
tests/gui/test_sidebar_navigation.py (+ first-launch review-badge regression test — bug 2 above)
docs/21_DESIGN_SYSTEM.md           (updated widget catalog, tokens, + a note on floating widgets needing real window flags)
tests/unit/test_repo_structure.py  (+ this doc in REQUIRED_DOCS)
```

No file under `app/core/`, `alembic/`, or `app/cli/` was touched.

## 13. Before / After

Same seeded data (Episode 001 moved to the "Image Prompts" stage and given 2 extra pending-review assets, so the stepper/badges/hero cards all show a representative non-empty state), same window size, for a fair comparison against the first polish pass:

| | After pass 1 (`docs/23`) | After pass 2 (this pass) |
|---|---|---|
| Dashboard, light | `docs/screenshots/ui_polish/02_dashboard_light.png` | `docs/screenshots/ui_polish_v2/01_dashboard_light.png` |
| Dashboard, dark | `docs/screenshots/ui_polish/03_dashboard_dark.png` | `docs/screenshots/ui_polish_v2/02_dashboard_dark.png` |
| Sidebar | `docs/screenshots/ui_polish/05_sidebar.png` | `docs/screenshots/ui_polish_v2/03_sidebar_grouped.png` |
| Diagnostics (new) | — (didn't exist) | `docs/screenshots/ui_polish_v2/04_diagnostics_popover.png` |

## 14. Test Count and Results

```
$ QT_QPA_PLATFORM=offscreen pytest -q
370 passed in ~47s

$ ruff check .
All checks passed!
```

370 total (349 at the end of the first polish pass → 370: 21 net-new, all in `tests/gui/`):

- `tests/gui/test_ui_polish_v2_widgets.py` (20 tests, new file): `SummaryCard` hero-vs-regular classes/sizes, `set_caption` show/hide, `set_value_animated` (instant-when-equal, eventually-reaches-target, replaces-a-running-animation), `ProgressStepper` per-step icons (done still checkmarks, current/upcoming show their own icon, numeric fallback without icons), the current-stage pulse effect (only the current dot gets a `QGraphicsDropShadowEffect`, rebuilding stops the old animation), `render_nav_icon` (non-null `QIcon` for every glyph, raises on an unknown glyph), `Sidebar` (groups match `NAV_ITEMS`, badge show/hide/cap-at-99+, selection moves the indicator's animation target), and the `TopBar` diagnostics popover (is a real top-level `Qt.WindowType.Tool` window — bug 1 regression test — and toggles visibility correctly).
- `tests/gui/test_sidebar_navigation.py` (+1): first-launch review-badge regression test (bug 2).
- `tests/gui/test_dashboard.py` / `tests/gui/test_status_bar.py`: updated in place for the new `SummaryCard`/`TopBar` APIs (no net test-count change from these two files).

## 15. Known Limitations

- Card/action icons are still emoji, not custom vector art (§8) — a deliberate scope decision, not an oversight; emoji rendering is platform/font-dependent in a way the sidebar's new vector glyphs are not.
- The "percent through pipeline" badge is a position-in-7-stages percentage, not a time-based ETA — there is genuinely no duration data in the schema to compute a real ETA from (§0, §2).
- `ProgressStepper`/`ActivityTimeline` still rebuild their entire contents on every call rather than diffing (unchanged limitation from `docs/23`) — still fine at today's scale (7 steps, ≤12 activity rows).
- The Production Progress panel and the header's episode chip still only ever show Episode #1 — a real multi-episode picker remains Milestone 4B scope, untouched here.

## 16. Recommended Next Step

Awaiting approval before Milestone 4B, per the explicit instruction this pass was scoped under. This pass changed presentation and information architecture only — every future screen should keep reusing `ElevatedCard`/`SummaryCard`/`ActionCard`/`ProgressStepper`/`ActivityTimeline`/`render_nav_icon` rather than introducing parallel one-off widgets, and any future floating/overlay widget should follow the diagnostics popover's real-top-level-window pattern (§11, `docs/21` §4) rather than being added as a plain clipped child.
