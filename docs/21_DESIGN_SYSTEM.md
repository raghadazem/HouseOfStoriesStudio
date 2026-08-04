# 21 — Design System

**Milestone:** 4A — Application Shell (updated by the UI/UX polish pass, `docs/23_UI_UX_POLISH_STATUS.md`, and the v2 polish pass, `docs/24_UI_UX_POLISH_V2_STATUS.md`)
**Package:** `app/gui/theme/`, `app/gui/widgets/`

---

## 1. Look and Feel

A modern creative-production tool — closer to Notion/Figma/Canva Desktop than to a childish or an enterprise-grey interface, per the founder's brief. Soft neutral backgrounds, rounded cards, a single accent color (violet, `#6C5CE7` light / `#8A7CF0` dark) used sparingly for primary actions and the sidebar's selected state, and small colorful status badges rather than heavy decoration. No gradients, no illustrations, no per-screen bespoke styling.

## 2. Design Tokens (`app/gui/theme/tokens.py`)

**Every color in `app/gui` is a named token — nowhere else in the codebase is a hex code or `rgba(...)` literal allowed to appear in a widget file.** `ThemeTokens` is a frozen dataclass with one instance for light and one for dark:

| Token | Purpose |
|---|---|
| `background` / `surface` / `surface_alt` / `border` | Page background, card/panel surfaces, a slightly-different surface for footers/dividers, hairline borders |
| `text_primary` / `text_secondary` / `text_muted` / `text_on_accent` | Body text hierarchy; `text_on_accent` for text drawn on a filled accent-color button |
| `accent` / `accent_hover` / `accent_pressed` / `accent_soft` | The one brand color, its two interaction states, and a tinted background (icon chips, the "current" step dot) |
| `success` / `warning` / `danger` / `info` | `StatusBadge` and summary-card indicator colors |
| `sidebar_background` / `sidebar_text` / `sidebar_text_muted` / `sidebar_selected_background` / `sidebar_selected_text` | The sidebar is deliberately a separate (darker) surface from the main content area in both themes, like Notion/Figma's side rail |
| `overlay` / `shadow` | `LoadingOverlay`'s scrim; reserved for future drop-shadow use |

`Metrics` (also in `tokens.py`) holds every spacing/radius/font-size value, shared by both themes — only *color* differs between light and dark, never spacing or type scale. The v2 polish pass added `font_size_xs` (10px — sidebar section labels, diagnostics captions) and `font_size_xxl` (36px — the two "hero" summary cards' value) to widen the type scale for the deeper hierarchy described in `docs/24_UI_UX_POLISH_V2_STATUS.md` §7, and bumped `sidebar_width` 232→240 to fit the wider grouped layout.

## 3. How Tokens Become Pixels: `ThemeManager`

`app/gui/theme/manager.py::ThemeManager` is the **only** place that turns tokens into an actual Qt stylesheet (`QApplication.setStyleSheet(...)`). It builds one QSS string per theme from an f-string template over `ThemeTokens`/`Metrics`, so switching themes is exactly "rebuild the string, re-apply it" — no per-widget re-styling code anywhere.

Two mechanisms widgets use to receive themed styling from that one stylesheet:

1. **Object names**, for one-off named elements: `self.setObjectName("topBar")` → `QWidget#topBar { ... }` in the QSS.
2. **The `class` dynamic property**, for variant styling of an otherwise-generic widget type — e.g. every `SummaryCard` sets `self.setProperty("class", "card")`, matched by `QFrame[class="card"] { ... }`. A `StatusBadge` sets `class` to `badge-success`/`badge-warning`/`badge-danger`/`badge-info`/`badge-neutral` depending on its variant, and calls `style().unpolish(self); style().polish(self)` after changing it — Qt caches computed style per widget, so changing a dynamic property used in a selector requires this repolish to actually take effect immediately.

A custom-painted widget (`LoadingSpinner`, `LoadingOverlay`, `AppLogo` — QSS can't style a hand-drawn `QPainter` arc, a translucent scrim, or a geometric brand mark) reads `ThemeManager.tokens` directly at paint time and listens to `ThemeManager.theme_changed` to repaint when the user switches themes.

### Real animation vs. QSS state changes

QSS `:hover`/`:checked` selectors swap styles *instantly* — Qt Style Sheets have no `transition` equivalent. Where an actual eased animation was wanted (card hover elevation, page-switch fade), it's built with `QPropertyAnimation` directly in Python, not QSS: `ElevatedCard` (`app/gui/widgets/elevated_card.py`) animates its `QGraphicsDropShadowEffect`'s blur radius and offset on hover enter/leave, and `MainWindow._animate_page_transition` fades each newly shown page in via a `QGraphicsOpacityEffect`. Every other hover/pressed state in the app is a QSS instant swap — a real, deliberate distinction, not an inconsistency. See `docs/23_UI_UX_POLISH_STATUS.md` §9.

### The one gotcha this milestone hit and documented

A QSS selector only applies to a widget that actually matches it — a plain `QWidget` with no object name and no relevant type selector keeps Qt's default palette background, invisible to the "just add another selector" approach if you forget to name it. `DashboardPage`'s `QScrollArea` content widget originally had no `objectName`, so it silently stayed light-themed under the dark theme (readable-on-light `text_primary` white text became invisible white-on-white — actually white-on-light-gray). Fixed by giving it `objectName("scrollContent")` and adding both `QWidget#scrollContent` and the more general `QScrollArea > QWidget` (covers the scroll viewport too) to the background rule. See `docs/22_MILESTONE_4A_STATUS.md` §3 for the before/after screenshots.

## 4. Reusable Widget Catalog (`app/gui/widgets/`)

| Widget | What it's for | Key API |
|---|---|---|
| `ElevatedCard` | Base class for every card: `class="card"` QSS + animated hover elevation (see above) | subclass it; `_animate_to(blur, offset)` if you need to trigger it manually |
| `SummaryCard` | One dashboard metric: icon chip, title, big value, optional caption/progress bar/subtitle/badge, optional `hero` variant (bigger icon/value, spans more grid columns). Extends `ElevatedCard`. | `set_value(str)`, `set_value_animated(int)` (count-up), `set_caption(str)` (a real secondary metric — never a fabricated trend, see `docs/24` §1), `set_subtitle(str)`, `set_badge(text, variant)`, `set_progress(ratio: float)` |
| `ActionCard` | One clickable "production shortcut": icon (shares `SummaryCard`'s `iconChip` styling), title, optional description. Extends `ElevatedCard`. Minimum height 128px for a larger click target. | `clicked` signal |
| `ProgressStepper` | A horizontal done/current/upcoming stage indicator, each step with its own icon and the current step pulsing via a looping `QGraphicsDropShadowEffect` animation. Purely presentational — no domain knowledge. | `set_progress(steps: list[str], current_index: int \| None, icons: list[str] \| None = None)` |
| `ActivityTimeline` | Icon + friendly title + relative-time rows, built from parsed log lines | `set_entries(list[ActivityEntry])`, `entries` (read-only); module-level `parse_log_line(line)`/`format_relative_time(dt)` |
| `AppLogo` | The custom-painted brand mark (see §7 of `docs/23`) | constructor only: `theme`, `size` |
| `render_nav_icon` | A small custom vector icon set (`app/gui/widgets/nav_icon.py`) for the 7 sidebar items — renders to a `QIcon` (not a live widget) specifically so `Sidebar` keeps plain, keyboard-accessible `QPushButton`s. See `docs/24` §8 for why this scope (sidebar only) was chosen over a full icon set. | `render_nav_icon(glyph: str, color: QColor \| str, size: int = 18) -> QIcon`; `GLYPHS` for the valid glyph names |
| `SectionHeader` | A page/section title + optional subtitle + optional trailing widget (e.g. a button or `StatusBadge`) | `set_title`, `set_subtitle` |
| `StatusBadge` | A small colored pill (`success`/`warning`/`danger`/`info`/`neutral`) | `set_text`, `set_variant` |
| `SearchBox` | A labeled search input with a leading icon | `text()`, `clear()`, `text_changed` signal (live filter-as-you-type, every Milestone 4B list page), `return_pressed`, `set_focus()`, and a built-in Ctrl+F shortcut to focus it |
| `PlaceholderPage` | A full-page "not built yet" screen — now only used for genuinely future sidebar destinations, none exist post-4B | constructor only: `title`, `message`, `icon` |
| `EmptyState` | A small "nothing here" block embedded inside a card/panel (smaller than `PlaceholderPage`) | `set_message` |
| `ErrorState` | An inline "something went wrong" block + Retry button — every Milestone 4B list page uses this instead of a modal dialog when its initial DB read fails | `retry_requested` signal, `set_message` |
| `LoadingSpinner` / `LoadingOverlay` | A rotating-arc spinner and a full-cover semi-transparent scrim+spinner+message | `start()`, `stop()`, `set_message` |
| `PageHeader` | The one-per-page title bar: title, optional subtitle, optional primary action button. One per screen, above the search/filter toolbar the page builds itself. Distinct from `SectionHeader`, which titles a sub-section *within* a page. | `primary_action_triggered` signal, `set_subtitle`, `set_primary_enabled` |
| `EntityRow` | An accessible (`QPushButton`-based, not `QFrame` + mouse handler) clickable list row: icon chip, title, subtitle, read-only trailing content. Used by Episodes and Prompt Manager. | `clicked` signal (native), `set_title`, `set_subtitle`, `add_trailing_widget(widget)` — trailing content must be read-only (labels/badges), never another interactive widget (see `docs/25` §3) |
| `EntityCard` | The grid-tile counterpart to `EntityRow` — same accessibility rationale, same read-only-trailing-content rule. Used by Characters and Assets inside `ResponsiveGrid`. | `clicked` signal, `set_title`, `set_subtitle`, `add_trailing_widget`, `set_thumbnail(QPixmap)` (swaps the icon-chip glyph for a real image) |
| `ResponsiveGrid` | Reflows a list of cards into however many columns fit the current width, recomputed on every resize | `set_cards(list[QWidget])` |
| `FormDialog` | The base for every create-form and read-only detail dialog: title, scrollable content area, inline validation-error line, Cancel/Save or single Close footer | override `validate() -> str \| None`; `add_row(label, widget)`, `show_form_error(message)` |
| `age_label` (`relative_time.py`) | "How long ago" for `TimestampMixin`'s timezone-aware UTC columns — handles SQLite's naive-but-UTC round-trip. Distinct from `activity_timeline.format_relative_time`, which buckets naive-*local* log-line timestamps (a different clock, deliberately not unified — see that module's docstring). | `age_label(timestamp: datetime) -> str` |
| `dialogs.show_info/show_warning/show_error/confirm/show_not_implemented` | The only way any page shows a message dialog | plain functions, not classes |

### Floating/overlay widgets must be real top-level windows, not clipped children

`TopBar`'s diagnostics popover (`docs/24` §4) is a `QFrame` that needs to render outside its parent's bounds — `TopBar` is only `topbar_height` tall, and Qt clips a plain child widget's painting to its parent's rectangle. The fix: give the popover real window flags (`Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint`, `WA_TranslucentBackground` for the rounded corners) so it becomes its own top-level window instead of a clipped child — positioned with `mapToGlobal`, not `mapTo(parent, ...)`. Any future floating/overlay widget that needs to draw beyond its logical parent's bounds (a dropdown, a tooltip-like panel) should follow the same pattern rather than being added as a plain child.

Nothing here is used speculatively without a real call site: `LoadingOverlay` is wired into `DashboardPage`'s "Run Mock AI" quick action (a real, if brief, async-feeling operation); `EmptyState` backs every summary card's zero-data subtitle text, the Production Progress panel's no-episode state, and the Recent Activity panel; `dialogs.show_not_implemented` backs `Create Episode`/`Import Asset`/every placeholder sidebar page; `ProgressStepper`/`ActivityTimeline` are both driven by real data the Dashboard already reads (`Episode.pipeline_stage`, `data/logs/app.log`) — neither has a mode that shows fabricated content.

## 5. What Milestone 4B Inherits

Every one of these widgets, `ThemeManager`, `AppSettings`, and `ApplicationContext` are meant to be reused as-is by every future screen — Milestone 4B should not need to add a second card widget, a second dialog helper, or a second QSettings touchpoint. If a future screen needs a variant this catalog doesn't cover, extend the existing widget (a new `StatusBadge` variant, a new `SummaryCard` mode) rather than building a parallel one-off.
