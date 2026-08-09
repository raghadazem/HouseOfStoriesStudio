"""MainWindow — the application shell: top bar, sidebar, page stack, status bar."""

from __future__ import annotations

import uuid

from PySide6.QtCore import QEasingCurve, QPropertyAnimation
from PySide6.QtWidgets import (
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app import __version__
from app.gui.context import ApplicationContext
from app.gui.pages.assets_page import AssetsPage
from app.gui.pages.characters_page import CharactersPage
from app.gui.pages.dashboard_page import DashboardPage
from app.gui.pages.episode_workspace_page import EpisodeWorkspacePage
from app.gui.pages.episodes_page import EpisodesPage
from app.gui.pages.prompts_page import PromptsPage
from app.gui.pages.review_queue_page import ReviewQueuePage
from app.gui.pages.settings_page import SettingsPage
from app.gui.settings import AppSettings
from app.gui.theme.manager import ThemeManager
from app.gui.theme.tokens import METRICS
from app.gui.widgets.toast import ToastHost, Variant
from app.gui.windows.sidebar import NAV_ITEMS, Sidebar
from app.gui.windows.top_bar import APP_TITLE, TopBar

_MIN_WINDOW_SIZE = (640, 480)


class MainWindow(QMainWindow):
    """Composes the shell around whatever page is active in the central stack."""

    def __init__(
        self,
        ctx: ApplicationContext,
        theme: ThemeManager,
        settings: AppSettings,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._ctx = ctx
        self._theme = theme
        self._settings = settings

        self.setWindowTitle(APP_TITLE)
        self.resize(1440, 900)
        self.setMinimumSize(*_MIN_WINDOW_SIZE)

        self._build_layout()
        self._build_status_bar()
        self._wire_signals()
        # Every page refreshes itself once during its own __init__ (so
        # each is a usable standalone widget in tests), which happens
        # before the signal connections just above exist — that first
        # episode_updated/review_count_updated emission has no listener
        # yet, so the top bar's episode chip and the sidebar's review
        # badge would otherwise stay unset until the next navigation.
        # Refresh both review-count sources once more now that they're wired.
        self.dashboard_page.refresh()
        self.review_queue_page.refresh()

        self._theme.theme_changed.connect(self._on_theme_changed)
        self._on_theme_changed(self._theme.theme_name)

        self._restore_geometry()
        self.set_state("Ready")

    # --- layout ------------------------------------------------------------

    def _build_layout(self) -> None:
        central = QWidget()
        central.setObjectName("centralArea")

        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.top_bar = TopBar(version=__version__, theme=self._theme)
        outer.addWidget(self.top_bar)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        self.sidebar = Sidebar(self._theme)
        body.addWidget(self.sidebar)

        self.stack = QStackedWidget()
        self._pages: dict[str, QWidget] = {}
        self._episode_workspace_page: EpisodeWorkspacePage | None = None
        self.dashboard_page = DashboardPage(self._ctx, self._theme, self)
        self.episodes_page = EpisodesPage(self._ctx, self._theme, self, on_feedback=self.show_toast)
        self.characters_page = CharactersPage(self._ctx, self._theme, self, on_feedback=self.show_toast)
        self.assets_page = AssetsPage(self._ctx, self._theme, self, on_feedback=self.show_toast)
        self.prompts_page = PromptsPage(self._ctx, self._theme, self, on_feedback=self.show_toast)
        self.review_queue_page = ReviewQueuePage(self._ctx, self._theme, self, on_feedback=self.show_toast)
        self.settings_page = SettingsPage(self._ctx, self._theme, self._settings, self)
        self._add_page("dashboard", self.dashboard_page)
        self._add_page("episodes", self.episodes_page)
        self._add_page("characters", self.characters_page)
        self._add_page("assets", self.assets_page)
        self._add_page("prompts", self.prompts_page)
        self._add_page("review_queue", self.review_queue_page)
        self._add_page("settings", self.settings_page)
        body.addWidget(self.stack, stretch=1)

        outer.addLayout(body, stretch=1)
        self.setCentralWidget(central)

        # Anchored to the whole window (not just the page stack) so a
        # toast stays visible across navigation instead of disappearing
        # with the page that triggered it; offset below the top bar so
        # it never covers the branding/theme toggle.
        self._toast_host = ToastHost(self, top_offset=METRICS.topbar_height)

    def _add_page(self, key: str, page: QWidget) -> None:
        self._pages[key] = page
        self.stack.addWidget(page)

    def _build_status_bar(self) -> None:
        bar = self.statusBar()
        self._status_database = QLabel()
        self._status_provider = QLabel()
        self._status_workspace = QLabel()
        self._status_state = QLabel()
        bar.addWidget(self._status_database)
        bar.addWidget(self._status_provider)
        bar.addWidget(self._status_workspace)
        bar.addPermanentWidget(self._status_state)

        self._status_database.setText(f"Database: {self._ctx.database_label}")
        self._status_workspace.setText(f"Workspace: {self._ctx.workspace_label}")
        providers = self._ctx.ai_orchestrator.list_available_providers("image")
        provider_text = ", ".join(providers) if providers else "none configured"
        self._status_provider.setText(f"AI Provider: {provider_text}")

        self.top_bar.set_database_label(self._ctx.database_label)
        self.top_bar.set_workspace_label(self._ctx.config.production_dir.name)
        self.top_bar.set_provider_label(provider_text)

    def set_state(self, text: str) -> None:
        self._status_state.setText(text)

    def show_toast(self, message: str, variant: Variant = "success") -> None:
        """Passed to every page as ``on_feedback`` — a non-blocking confirmation
        after a successful create/approve/reject, where a page previously gave
        the user nothing but a silent list refresh."""
        self._toast_host.show_toast(message, variant)

    # --- signals -------------------------------------------------------------

    def _wire_signals(self) -> None:
        self.sidebar.item_selected.connect(self._on_nav_selected)
        self.top_bar.theme_toggle_requested.connect(self._on_theme_toggle)
        self.top_bar.about_requested.connect(self._on_about)
        self.dashboard_page.navigate_requested.connect(self.navigate_to)
        self.dashboard_page.episode_updated.connect(self.top_bar.set_current_episode)
        self.dashboard_page.review_count_updated.connect(self._on_review_count_updated)
        self.review_queue_page.review_count_updated.connect(self._on_review_count_updated)
        self.dashboard_page.open_episode_requested.connect(self.open_episode_workspace)
        self.episodes_page.episode_opened.connect(self.open_episode_workspace)

    def _on_review_count_updated(self, count: int) -> None:
        self.sidebar.set_badge("review_queue", count)

    def navigate_to(self, key: str) -> None:
        """Programmatic navigation (e.g. a Dashboard quick action) — goes
        through the real sidebar button click, not a shortcut around it."""
        button = self.sidebar.button_for(key)
        if button is not None:
            button.click()

    def open_episode_workspace(self, episode_id: uuid.UUID) -> None:
        """Open the full Episode Workspace for ``episode_id``.

        Not a fixed sidebar item — episodes are opened ad hoc (an
        Episodes row click, a Dashboard quick action), so this page is
        built once and re-targeted at whichever episode was opened most
        recently, rather than accumulating one stacked page per episode
        ever opened.
        """
        if self._episode_workspace_page is None:
            self._episode_workspace_page = EpisodeWorkspacePage(
                self._ctx, self._theme, episode_id, self, on_feedback=self.show_toast,
            )
            self._episode_workspace_page.back_requested.connect(lambda: self.navigate_to("episodes"))
            self._add_page("episode_workspace", self._episode_workspace_page)
        else:
            self._episode_workspace_page.set_episode(episode_id)
        self.stack.setCurrentWidget(self._episode_workspace_page)
        self._animate_page_transition(self._episode_workspace_page)
        self.set_state("Viewing Episode Workspace")

    def _on_nav_selected(self, key: str) -> None:
        page = self._pages.get(key)
        if page is not None:
            self.stack.setCurrentWidget(page)
            self._animate_page_transition(page)
            # Every page owns its own data — re-fetch on every visit so
            # a change made elsewhere (e.g. approving an asset from the
            # Review Queue) is reflected immediately, not just on the
            # first navigation.
            refresh = getattr(page, "refresh", None)
            if callable(refresh):
                refresh()
        label = next((item.label for item in NAV_ITEMS if item.key == key), key)
        self.set_state(f"Viewing {label}")

    def _animate_page_transition(self, page: QWidget) -> None:
        """A brief fade-in on the newly shown page — QStackedWidget has no
        built-in transition, and this is cheap enough to run on every
        navigation without feeling like it's slowing anything down."""
        effect = QGraphicsOpacityEffect(page)
        page.setGraphicsEffect(effect)
        animation = QPropertyAnimation(effect, b"opacity", page)
        animation.setDuration(180)
        animation.setStartValue(0.0)
        animation.setEndValue(1.0)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        animation.finished.connect(lambda: page.setGraphicsEffect(None))
        self._page_transition_anim = animation  # keep a live reference
        animation.start()

    def _on_theme_toggle(self) -> None:
        new_theme = self._theme.toggle()
        self._settings.save_theme(new_theme)

    def _on_theme_changed(self, theme_name: str) -> None:
        self.top_bar.set_theme_icon(is_dark=(theme_name == "dark"))

    def _on_about(self) -> None:
        QMessageBox.about(
            self,
            "About House of Stories Studio",
            f"<b>{APP_TITLE}</b><br>بيت الحكايات<br><br>"
            f"Version {__version__}<br>"
            "A production-management desktop app for an Arabic children's "
            "YouTube studio.",
        )

    # --- window geometry persistence -------------------------------------------

    def _restore_geometry(self) -> None:
        geometry = self._settings.load_window_geometry()
        if geometry is not None:
            self.restoreGeometry(geometry)

    def closeEvent(self, event) -> None:
        self._settings.save_window_geometry(self.saveGeometry())
        self._settings.sync()
        self._ctx.dispose()
        super().closeEvent(event)
