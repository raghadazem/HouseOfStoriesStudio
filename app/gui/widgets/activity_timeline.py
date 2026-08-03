"""ActivityTimeline — a friendly, iconified read of the existing app log.

No new logging concept and no new file: this parses the exact same
``data/logs/app.log`` lines ``app/logging_setup.py`` and
``app/core/ai/generation_logger.py`` already write (format:
``"%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"``, with AI
generation attempts additionally carrying a JSON payload after
``"generation_attempt "``) and renders them as a readable timeline
instead of raw text. Parsing lives entirely in this GUI module — no
core file changed to support it.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from app.gui.theme.tokens import METRICS

_LOG_LINE_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) \| (?P<level>\w+)\s*\| "
    r"(?P<logger>\S+) \| (?P<message>.*)$"
)
_GENERATION_PREFIX = "generation_attempt "


@dataclass(frozen=True)
class ActivityEntry:
    icon: str
    title: str
    timestamp: datetime | None


def parse_log_line(line: str) -> ActivityEntry | None:
    """Parse one raw log line into a friendly :class:`ActivityEntry`, or ``None``."""
    match = _LOG_LINE_RE.match(line.strip())
    if not match:
        return None

    try:
        # Naive on purpose: app/logging_setup.py's Formatter writes
        # %(asctime)s in local time with no offset — parsing it as
        # "aware" would require guessing a timezone the log line
        # doesn't actually carry.
        timestamp = datetime.strptime(match.group("ts"), "%Y-%m-%d %H:%M:%S")  # noqa: DTZ007
    except ValueError:
        timestamp = None

    icon, title = _describe(match.group("logger"), match.group("level").strip(), match.group("message"))
    return ActivityEntry(icon=icon, title=title, timestamp=timestamp)


def _describe(logger_name: str, level: str, message: str) -> tuple[str, str]:
    if logger_name.endswith("ai_generation") and message.startswith(_GENERATION_PREFIX):
        described = _describe_generation_attempt(message[len(_GENERATION_PREFIX) :])
        if described is not None:
            return described

    if logger_name.endswith(".seed"):
        return "🌱", message
    if level == "ERROR":
        return "❌", message
    if level == "WARNING":
        return "⚠️", message
    return "ℹ️", message


def _describe_generation_attempt(payload_text: str) -> tuple[str, str] | None:
    try:
        payload = json.loads(payload_text)
    except json.JSONDecodeError:
        return None

    workflow = str(payload.get("workflow_name", "generation")).replace("_", " ")
    provider = payload.get("provider_name", "the provider")
    if payload.get("outcome") == "success":
        return "✨", f"Generated {workflow} via {provider}"
    error_category = payload.get("error_category") or "an error"
    return "⚠️", f"{workflow.capitalize()} generation failed ({error_category})"


def format_relative_time(timestamp: datetime | None) -> str:
    if timestamp is None:
        return ""
    # Compared against another naive-local `now()` to match `timestamp`
    # above — see the noqa note in parse_log_line().
    seconds = max(0.0, (datetime.now() - timestamp).total_seconds())  # noqa: DTZ005
    if seconds < 60:
        return "just now"
    minutes = int(seconds // 60)
    if minutes < 60:
        return f"{minutes}m ago"
    hours = int(minutes // 60)
    if hours < 24:
        return f"{hours}h ago"
    days = int(hours // 24)
    if days < 7:
        return f"{days}d ago"
    return timestamp.strftime("%b %d, %H:%M")


class ActivityTimeline(QWidget):
    """Renders a list of :class:`ActivityEntry` as icon + title + relative time rows."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(2)
        self._entries: list[ActivityEntry] = []

    @property
    def entries(self) -> list[ActivityEntry]:
        """The entries currently rendered — read-only, mainly for tests."""
        return list(self._entries)

    def set_entries(self, entries: list[ActivityEntry]) -> None:
        self._entries = list(entries)
        self._clear()
        for entry in entries:
            self._layout.addWidget(self._row(entry))

    def _clear(self) -> None:
        # See the matching comment in ProgressStepper._clear() — reparent
        # immediately, don't rely on deleteLater() alone to stop a
        # taken-out-of-layout widget from still being painted.
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

    @staticmethod
    def _row(entry: ActivityEntry) -> QWidget:
        row = QWidget()
        row.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        row.setProperty("class", "activityRow")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(
            METRICS.spacing_sm, METRICS.spacing_sm, METRICS.spacing_sm, METRICS.spacing_sm
        )
        layout.setSpacing(METRICS.spacing_sm)

        icon_label = QLabel(entry.icon)
        icon_label.setProperty("class", "activityIcon")
        icon_label.setFixedWidth(28)
        layout.addWidget(icon_label)

        title_label = QLabel(entry.title)
        title_label.setProperty("class", "activityTitle")
        title_label.setWordWrap(True)
        layout.addWidget(title_label, stretch=1)

        time_label = QLabel(format_relative_time(entry.timestamp))
        time_label.setProperty("class", "muted")
        layout.addWidget(time_label)

        return row
