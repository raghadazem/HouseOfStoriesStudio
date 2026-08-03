# 21 — Design System

**Milestone:** 4A — Application Shell
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
| `accent` / `accent_hover` / `accent_pressed` | The one brand color and its two interaction states |
| `success` / `warning` / `danger` / `info` | `StatusBadge` and summary-card indicator colors |
| `sidebar_background` / `sidebar_text` / `sidebar_text_muted` / `sidebar_selected_background` / `sidebar_selected_text` | The sidebar is deliberately a separate (darker) surface from the main content area in both themes, like Notion/Figma's side rail |
| `overlay` / `shadow` | `LoadingOverlay`'s scrim; reserved for future drop-shadow use |

`Metrics` (also in `tokens.py`) holds every spacing/radius/font-size value, shared by both themes — only *color* differs between light and dark, never spacing or type scale.

## 3. How Tokens Become Pixels: `ThemeManager`

`app/gui/theme/manager.py::ThemeManager` is the **only** place that turns tokens into an actual Qt stylesheet (`QApplication.setStyleSheet(...)`). It builds one QSS string per theme from an f-string template over `ThemeTokens`/`Metrics`, so switching themes is exactly "rebuild the string, re-apply it" — no per-widget re-styling code anywhere.

Two mechanisms widgets use to receive themed styling from that one stylesheet:

1. **Object names**, for one-off named elements: `self.setObjectName("topBar")` → `QWidget#topBar { ... }` in the QSS.
2. **The `class` dynamic property**, for variant styling of an otherwise-generic widget type — e.g. every `SummaryCard` sets `self.setProperty("class", "card")`, matched by `QFrame[class="card"] { ... }`. A `StatusBadge` sets `class` to `badge-success`/`badge-warning`/`badge-danger`/`badge-info`/`badge-neutral` depending on its variant, and calls `style().unpolish(self); style().polish(self)` after changing it — Qt caches computed style per widget, so changing a dynamic property used in a selector requires this repolish to actually take effect immediately.

A custom-painted widget (there are exactly two: `LoadingSpinner`, `LoadingOverlay` — QSS can't style a hand-drawn `QPainter` arc or a translucent scrim) reads `ThemeManager.tokens` directly at paint time and listens to `ThemeManager.theme_changed` to repaint when the user switches themes.

### The one gotcha this milestone hit and documented

A QSS selector only applies to a widget that actually matches it — a plain `QWidget` with no object name and no relevant type selector keeps Qt's default palette background, invisible to the "just add another selector" approach if you forget to name it. `DashboardPage`'s `QScrollArea` content widget originally had no `objectName`, so it silently stayed light-themed under the dark theme (readable-on-light `text_primary` white text became invisible white-on-white — actually white-on-light-gray). Fixed by giving it `objectName("scrollContent")` and adding both `QWidget#scrollContent` and the more general `QScrollArea > QWidget` (covers the scroll viewport too) to the background rule. See `docs/22_MILESTONE_4A_STATUS.md` §3 for the before/after screenshots.

## 4. Reusable Widget Catalog (`app/gui/widgets/`)

| Widget | What it's for | Key API |
|---|---|---|
| `SummaryCard` | One dashboard metric: icon, title, big value, optional subtitle/badge | `set_value(str)`, `set_subtitle(str)`, `set_badge(text, variant)` |
| `SectionHeader` | A page/section title + optional subtitle + optional trailing widget (e.g. a button) | `set_title`, `set_subtitle` |
| `StatusBadge` | A small colored pill (`success`/`warning`/`danger`/`info`/`neutral`) | `set_text`, `set_variant` |
| `SearchBox` | A labeled search input with a leading icon | `text()`, `clear()`, `return_pressed` signal — not wired to any real search yet (no list screen exists in 4A to search) |
| `PlaceholderPage` | A full-page "not built yet" screen | constructor only: `title`, `message`, `icon` |
| `EmptyState` | A small "nothing here" block embedded inside a card/panel (smaller than `PlaceholderPage`) | `set_message` |
| `LoadingSpinner` / `LoadingOverlay` | A rotating-arc spinner and a full-cover semi-transparent scrim+spinner+message | `start()`, `stop()`, `set_message` |
| `dialogs.show_info/show_warning/show_error/confirm/show_not_implemented` | The only way any page shows a message dialog | plain functions, not classes |

Nothing here is used speculatively without a real call site: `LoadingOverlay` is wired into `DashboardPage`'s "Run Mock AI" quick action (a real, if brief, async-feeling operation); `EmptyState` backs every summary card's zero-data subtitle text and the Recent Activity panel; `dialogs.show_not_implemented` backs `Create Episode`/`Import Asset`/every placeholder sidebar page.

## 5. What Milestone 4B Inherits

Every one of these widgets, `ThemeManager`, `AppSettings`, and `ApplicationContext` are meant to be reused as-is by every future screen — Milestone 4B should not need to add a second card widget, a second dialog helper, or a second QSettings touchpoint. If a future screen needs a variant this catalog doesn't cover, extend the existing widget (a new `StatusBadge` variant, a new `SummaryCard` mode) rather than building a parallel one-off.
