# UI Design Principles

The GUI should always feel like a **premium desktop application** — closer
to Notion, Figma, or Canva Desktop than to a default-Qt developer tool or an
enterprise-grey internal app. Every future screen must follow the design
system already established in `app/gui/theme/` and `app/gui/widgets/`, not
introduce a parallel visual language. This document is the standing
reference; `docs/21_DESIGN_SYSTEM.md` is the authoritative, more detailed
source it summarizes.

---

## 1. Design System Philosophy

- **One design system, applied everywhere.** Soft neutral backgrounds,
  rounded cards, a single accent color used sparingly for primary actions
  and selection state, small colorful status badges rather than heavy
  decoration. No gradients, no illustrations, no per-screen bespoke
  styling.
- **Tokens, not literals.** Every color in `app/gui` is a named token from
  `ThemeTokens` (`app/gui/theme/tokens.py`) — a hex code or `rgba(...)`
  literal has no business appearing in a widget file. This is what makes a
  consistent light/dark theme possible without per-widget rework.
- **One place turns tokens into pixels.** `ThemeManager`
  (`app/gui/theme/manager.py`) is the only code that calls
  `QApplication.setStyleSheet(...)`. Switching themes is "rebuild the QSS
  string from tokens, re-apply it" — never a scattered set of per-widget
  overrides.

---

## 2. Typography

- Type scale lives in `Metrics` (`app/gui/theme/tokens.py`), shared by both
  themes — only *color* differs between light and dark, never spacing or
  type scale.
- Use the existing scale (including `font_size_xs` for captions/section
  labels and `font_size_xxl` reserved for hero metric values) rather than
  introducing a new size. If a screen seems to need a size the scale
  doesn't have, that is a signal to extend `Metrics` deliberately — not to
  hardcode a one-off value in a widget.
- Text hierarchy is expressed through the `text_primary` /
  `text_secondary` / `text_muted` tokens, not through arbitrary font-weight
  or size changes.

---

## 3. Colors

- One accent color (violet — `#6C5CE7` light / `#8A7CF0` dark), used
  sparingly: primary actions, the sidebar's selected state, focus rings.
- Status color tokens (`success` / `warning` / `danger` / `info`) are
  reserved for `StatusBadge` and summary-card indicators — they communicate
  state, not decoration.
- The sidebar is a deliberately distinct (darker) surface from the main
  content area in both themes, via its own token group
  (`sidebar_background`, `sidebar_text`, `sidebar_selected_background`,
  …) — this separation is intentional visual structure, not an
  inconsistency to "fix."
- Any new token must be added to `ThemeTokens` for **both** light and dark
  variants in the same change — a color that exists in only one theme is a
  bug, not a valid intermediate state.

---

## 4. Spacing

- All spacing/radius values live in `Metrics`, shared by both themes.
  Reuse an existing spacing value before introducing a new one; a new value
  should represent a genuinely new rhythm in the layout, not a one-off
  pixel adjustment to make one screen "feel right."
- Cards, panels, and form rows follow the existing padding/gap conventions
  already visible across `SummaryCard`, `EntityRow`, `FormDialog`, etc. —
  a new screen should be visually indistinguishable in its spacing rhythm
  from an existing one.

---

## 5. Components

**Reuse before creating — this is the same discipline as
[ARCHITECTURE_PRINCIPLES.md](ARCHITECTURE_PRINCIPLES.md) §5–6, applied to
the widget catalog.** The reusable catalog in `app/gui/widgets/` (full
reference: `docs/21_DESIGN_SYSTEM.md` §4) currently includes, among others:

| Need | Use |
|---|---|
| A dashboard metric | `SummaryCard` |
| A clickable shortcut card | `ActionCard` |
| A stage/step indicator | `ProgressStepper` |
| A list row | `EntityRow` |
| A grid tile | `EntityCard` |
| A reflowing card grid | `ResponsiveGrid` |
| A create/edit/detail dialog | `FormDialog` |
| A page title bar | `PageHeader` |
| A search+filter toolbar | `ToolbarRow` |
| A nothing-here state | `EmptyState` |
| A something-went-wrong state | `ErrorState` |
| A colored status pill | `StatusBadge` |
| A non-blocking success/failure message | `Toast` / `ToastHost` |
| A blocking modal message | `dialogs.show_info/show_warning/show_error/confirm` |

Two card widgets, two dialog helpers, or two `QSettings` touchpoints in
this codebase is a defect to fix, not a pattern to repeat. If a screen
needs a capability the catalog doesn't have, extend the existing widget (a
new `StatusBadge` variant, a new `SummaryCard` mode) — see
`docs/21_DESIGN_SYSTEM.md` §5.

---

## 6. Accessibility

- Every clickable row/card is a real `QAbstractButton` subclass (see
  `EntityRow`, `EntityCard`), not a `QFrame` with a mouse-event handler
  bolted on — this is what makes them keyboard-navigable and
  screen-reader-visible for free.
- Trailing content on a row/card (badges, labels) is read-only. A second
  interactive widget nested inside a clickable row creates an
  accessibility trap (nested focusable elements, ambiguous click targets)
  — see `docs/25_MILESTONE_4B_STATUS.md` §3.
- Interactive states are complete, not partial: `:hover`, `:focus`,
  `:pressed`, and `:disabled` are all defined for every interactive QSS
  class (buttons, inputs, checkboxes, scrollbars) — see
  `docs/26_UI_UX_POLISH_V3_STATUS.md` §4. A new interactive widget is not
  finished until all four states are styled.
- The app's RTL/Arabic text handling (Qt's native RTL layout for UI, plus
  `python-bidi`/`arabic-reshaper` for any custom-drawn text) is a real
  accessibility requirement for this product's actual users, not an
  edge case — see `docs/07_DEVELOPMENT_PLAN.md` §5.

---

## 7. Responsive Layouts

- The application window has a floor of 640×480
  (`MainWindow.setMinimumSize`); every layout must degrade gracefully
  down to that floor, not just at a "normal" desktop width.
- `ToolbarRow` (search box + filters) switches from a horizontal row to a
  stacked vertical layout below 640px width instead of squeezing controls
  into an unreadable row.
- `PageHeader`'s primary action button drops to its own line below the
  title below 420px width instead of colliding with it.
- `ResponsiveGrid` recomputes its column count on every resize rather than
  fixing a column count per breakpoint.
- Any new list/grid screen reuses `ToolbarRow`/`PageHeader`/
  `ResponsiveGrid` specifically so this responsive behavior is inherited,
  not reimplemented per screen.

---

## 8. Visual Hierarchy

- One `PageHeader` per screen (page-level title); `SectionHeader` for
  sub-sections *within* a page — these are deliberately distinct widgets
  with distinct visual weight, not interchangeable.
- Icons use a single consistent treatment: a tinted circular icon-chip,
  used identically by `EntityRow`, `ActionCard`, `SummaryCard`,
  `EmptyState`, `ErrorState`, and every `FormDialog` header — one visual
  language for "this is an icon," not several (see
  `docs/26_UI_UX_POLISH_V3_STATUS.md` §6).
- A result count (`"2 of 2 episodes"`) on every list/grid screen's toolbar
  is the established convention for showing scale honestly — carry it
  forward on new list screens rather than omitting it.
- Never fabricate content to fill hierarchy (a fake trend line, a made-up
  secondary metric) — every optional field on a widget like `SummaryCard`
  is only ever set from real data, or left unset. See
  `docs/21_DESIGN_SYSTEM.md` §4's closing note.

---

## 9. Animation Philosophy

- QSS `:hover`/`:checked`/`:pressed` selectors handle **instant** state
  changes — this is the default for the large majority of interactive
  feedback, and is a deliberate choice, not a limitation to work around.
- Real eased animation (`QPropertyAnimation`) is reserved for moments that
  benefit from motion specifically: card hover elevation (`ElevatedCard`),
  toast fade in/out, dialog open-fade, page-transition fade. Each is tied
  to a real, already-existing interaction — never added speculatively with
  no call site.
- A custom-painted widget (`LoadingSpinner`, `LoadingOverlay`, `AppLogo`)
  reads tokens directly at paint time and listens to
  `ThemeManager.theme_changed`, since QSS cannot style a hand-drawn
  `QPainter` surface.
- A layout reflow at a responsive breakpoint (§7) is instant, not
  animated — animating a layout swap would fight the OS's own resize
  handling.

---

## See Also

- [ARCHITECTURE_PRINCIPLES.md](ARCHITECTURE_PRINCIPLES.md) — the same
  reuse/composition discipline, applied architecture-wide.
- [PRODUCT_VISION.md](PRODUCT_VISION.md) — why "premium desktop app" is the
  bar, not "functional internal tool."
- `docs/21_DESIGN_SYSTEM.md` — the full, authoritative design system
  reference with code-level detail this document summarizes.
- `docs/20_GUI_ARCHITECTURE.md` — how the GUI layer is structured
  architecturally (module layout, `ApplicationContext`, session handling).
