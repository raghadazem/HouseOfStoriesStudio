# 26 — UI/UX Polish Pass v3 Status

**Milestone:** A third UI/UX polish pass, after Milestone 4B (all seven screens now exist and are real).
**Scope:** Visual design, information architecture, and interaction only. No architecture, database, service, or business-logic changes — every checklist item below is either a shared-widget change (touches every page at once) or a mechanical per-page wiring of an existing widget's new capability.

---

## 0. What Did Not Change

- **Zero changes** to `app/core/` (models, services, db, ai).
- **Zero changes** to `app/gui/context.py` (`ApplicationContext`) or `app/gui/settings.py` (`AppSettings`).
- **Zero new database migrations, zero new tables/columns, zero new services.**
- Every page's `refresh()`/create/approve/reject business logic calls the exact same service methods in the exact same order as `docs/25`. The only additions are: an optional `on_feedback` callback invoked *after* a call that already succeeded, and cosmetic widget wiring (`ToolbarRow` instead of a raw `QHBoxLayout`, an `action_label` on an already-existing `EmptyState`).

## 1. Visual feedback after actions — `Toast` / `ToastHost`

**Decision:** Before this pass, a successful create/approve/reject gave the user nothing but a silent list refresh — only failures got a visible response (`dialogs.show_error`, a blocking `QMessageBox`). `app/gui/widgets/toast.py` adds `Toast` (a small, color-coded, auto-dismissing bubble — success/warning/danger/info, left-edge accent bar, close button, 200ms fade in/out, 4s display) and `ToastHost` (stacks 0+ active toasts in a window's top-right corner, repositions on resize). `MainWindow` owns one `ToastHost` anchored to the whole window (not just the page stack, so a toast survives navigating away) and exposes `show_toast()`; every page that creates/decides something now takes an optional `on_feedback: Callable[[str, str], None] | None = None` constructor parameter — `None` by default, so every existing direct-construction call site (all 60+ in `tests/gui/`) needed no changes. Episodes, Characters, Assets, Prompts, and Review Queue all wire it: "Episode #3 created.", "Melissa added to the roster.", "Asset imported.", "Prompt template 'x' created.", "file.png approved."/"rejected."

**Caught during visual QA:** the host's width was a flat 340px, which at the app's 640px minimum window width ate over half the window and sat directly on top of the (left-aligned) page title. `ToastHost._reposition()` now shrinks toward a third of the anchor's width once the window gets narrow (`max(220, min(340, anchor.width() // 3))`) — unchanged at any normal desktop width. A second bug from the same QA pass: a toast added and screenshotted in the same tick measured as zero-height (`adjustSize()` under-reporting a fresh, never-laid-out word-wrapped label) — fixed by calling `self._layout.activate()` before `adjustSize()` and explicitly `.show()`-ing both the host and each toast rather than relying on inherited parent visibility.

## 2. Better empty states — `EmptyState` v2 + `ErrorState`

**Decision:** `EmptyState`'s icon went from a bare, unbadged emoji to the same 64px tinted circular chip treatment (`emptyStateIcon`) used everywhere else in the app (`EntityRow`, `ActionCard`, `SummaryCard` all already used a tinted chip — `EmptyState` was the one outlier). An optional `action_label` gives the empty state its own primary-action button (`action_triggered` signal) — Episodes, Characters, Assets, and Prompts all wire their "+ New X" empty-state button straight into the same handler the page header's button already calls; the button hides itself when the empty state is showing because a *search/filter* matched nothing (`set_message(..., show_action=False)`) rather than because the list is genuinely empty, since "clear your filters" is the real next step there, not "create another one." `ErrorState` picked up the identical icon-badge treatment for the same "nothing/something's-wrong-here" state to read as one visual language instead of two.

## 3. Less form-like dialogs — `FormDialog`

**Decision:** Every `FormDialog` subclass (`New Episode`, `New Character`, `Import Asset`, `New Prompt Template`, `Reject <asset>`) now has an optional `icon` + `subtitle` header (an icon chip identical to every other icon-chip in the app, a title, and a one-line subtitle) instead of a bare title label — "New Episode" 🎬 "Add it to the production pipeline", "New Character" 🧒 "Add them to the studio's roster", "Import Asset" 📥 "Bring a file into managed storage", "New Prompt Template" ✍️ "Reusable across episodes and characters". A 3px accent-colored top edge and a divider before the footer give the dialog a defined shape; the whole content area fades in on open (`QGraphicsOpacityEffect` + 160ms `OutCubic`, applied to an inner content widget rather than the top-level `QDialog` itself — a `QGraphicsOpacityEffect` on a real OS window can flicker/misbehave on some platforms, one on a plain child widget never does). `add_row()`/`content_layout` — the API every page's dialog subclass already calls — are unchanged.

## 4. Hover / focus / pressed / disabled states

**Decision:** Every interactive QSS class gained the states it was missing rather than only `:hover`:

| Widget | Added |
|---|---|
| `QPushButton` (default + `primary`) | `:hover` border tint, `:focus` accent border, `:disabled` muted colors |
| `entityRow` / `entityCard` | `:pressed` (was hover + focus only) |
| `QLineEdit` / `QComboBox` / `QTextEdit` / `QPlainTextEdit` / `QSpinBox` | `:hover` border tint *before* focus, `:disabled` muted background |
| `QLineEdit:read-only` | a distinct muted background, so a read-only detail-dialog field reads as non-editable at a glance |
| `QCheckBox::indicator` | `:hover` accent border |
| `QScrollBar` handle | `:hover` / `:pressed` color states (was a flat, state-less bar) |

`ActionCard` (a `QFrame`, not a real `QAbstractButton`, so it gets no QSS `:pressed` for free) gets a manual "sink on press, lift on release" using the hover-elevation animation it already has via `ElevatedCard` — exposed as two new public methods, `animate_hover()`/`animate_resting()`, so the click-emits-on-press timing (existing, deliberate) didn't need to change.

## 5. Responsive layout at narrow widths

**Decision:** Two new small layout widgets, used by every list/grid page:

- **`ToolbarRow`** (`app/gui/widgets/toolbar_row.py`) — every page's search box + 1–2 filter `QComboBox`es now live in this instead of a raw `QHBoxLayout`; below 640px width it switches to stacking them vertically (search full-width, filters below) instead of squeezing three controls into an unreadable row.
- **`PageHeader`** — below 420px width the primary "+ New X" button drops onto its own line under the title instead of colliding with it.

`MainWindow.setMinimumSize(640, 480)` gives the window a floor low enough not to fight the existing geometry-persistence test (which resizes to 700×500) while keeping the app from being resized into something neither of the above can save.

A **result count** (`"2 of 2 episodes"`, `"1 of 1 assets"`, …) was added to every list/grid page's toolbar — a small, honest touch for "long lists/cards feel less empty": even a single-item list now visibly says how many things exist and how many are currently showing, instead of leaving the user to count.

## 6. Icon consistency

**Decision:** Same scope boundary as `docs/24` §8 (building a full custom vector icon for all 20+ emoji across every card/row/header was judged out of scope for a polish pass then, and still is now) — but the *treatment* is now consistent everywhere an icon appears: `EmptyState`/`ErrorState` icons now sit in the same 64px tinted circular chip every other icon-bearing widget uses, and every page's create-dialog header uses the same icon-chip component as `EntityRow`/`ActionCard`/`SummaryCard`. What was previously "some icons have a badge, some don't" is now "every icon has the same badge, scaled to context."

## 7. Animations

| What | How | Real animation? |
|---|---|---|
| Toast fade in/out | `QGraphicsOpacityEffect` + `QPropertyAnimation`, 200ms, `OutCubic`/`InCubic` | **Yes** |
| Dialog open | `QGraphicsOpacityEffect` on the dialog's inner shell + `QPropertyAnimation`, 160ms `OutCubic` | **Yes** |
| ActionCard press/release | Reuses `ElevatedCard`'s existing shadow animation | **Yes** (pre-existing mechanism, new call sites) |
| Toolbar/header narrow-width reflow | Layout swap on resize | Instant, not animated (a reflow, not a transition — animating a layout swap would fight the OS resize itself) |

## 8. Testing

`tests/gui/test_ui_polish_v3_widgets.py` (13 tests) covers: `EmptyState`'s action button (present/absent, shown/hidden via `set_message`), `ErrorState`'s shared icon-badge class, `FormDialog` with/without an icon (and that its open-fade animation actually reaches full opacity), `ToolbarRow` and `PageHeader`'s wrap threshold in both directions, and `ToastHost`'s add/dismiss lifecycle and anchor-relative repositioning. Full suite: **460/460 passing**, `ruff check .` clean.

## 9. Screenshots

`docs/screenshots/ui_polish_v3/` — every page in light and dark, the New Episode dialog in both themes, a live toast after creating an episode, and the app at 680×760 (below the toolbar/header wrap thresholds) to show the responsive behavior described in §5.
