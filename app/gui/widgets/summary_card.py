"""SummaryCard — a rounded, hover-elevated card showing one dashboard metric.

v2 polish: a secondary "caption" line for a real secondary metric (never
a fabricated trend — see ``docs/24_UI_UX_POLISH_V2_STATUS.md`` §1), an
animated count-up when the value changes, and an optional ``hero``
variant (bigger icon/value) for the one or two cards that should carry
more visual weight than the rest — see §6 (visual hierarchy) of the
same doc.
"""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, Qt, QVariantAnimation
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.gui.theme.tokens import METRICS
from app.gui.widgets.elevated_card import ElevatedCard
from app.gui.widgets.status_badge import StatusBadge, Variant

_VALUE_ANIM_DURATION_MS = 550


class SummaryCard(ElevatedCard):
    """Icon chip + title, a large value, an optional caption/progress bar, and a footer.

    ``set_value``/``set_subtitle``/``set_badge``/``set_progress`` let the
    Dashboard update an already-built card in place (e.g. on refresh)
    instead of rebuilding it. ``set_value_animated`` additionally
    animates numeric changes with a brief count-up.
    """

    def __init__(
        self,
        icon: str,
        title: str,
        value: str = "—",
        subtitle: str | None = None,
        *,
        hero: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setProperty("class", "card-hero" if hero else "card")
        self._hero = hero
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setMinimumHeight(168 if hero else 148)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            METRICS.spacing_lg, METRICS.spacing_md, METRICS.spacing_lg, METRICS.spacing_md
        )
        layout.setSpacing(METRICS.spacing_xs)

        header = QHBoxLayout()
        header.setSpacing(METRICS.spacing_sm)

        chip_size = 48 if hero else 40
        self._icon_chip = QLabel(icon)
        self._icon_chip.setProperty("class", "iconChip-hero" if hero else "iconChip")
        self._icon_chip.setFixedSize(chip_size, chip_size)
        self._icon_chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header.addWidget(self._icon_chip)

        self._title_label = QLabel(title)
        self._title_label.setProperty("class", "cardTitle")
        header.addWidget(self._title_label)
        header.addStretch(1)
        layout.addLayout(header)
        layout.addSpacing(METRICS.spacing_xs)

        self._value_label = QLabel(value)
        self._value_label.setProperty("class", "cardValue-hero" if hero else "cardValue")
        layout.addWidget(self._value_label)

        self._caption_label = QLabel("")
        self._caption_label.setProperty("class", "cardCaption")
        self._caption_label.setVisible(False)
        layout.addWidget(self._caption_label)

        self._progress_bar = QProgressBar()
        self._progress_bar.setProperty("class", "cardProgress")
        self._progress_bar.setTextVisible(False)
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setFixedHeight(6)
        self._progress_bar.setVisible(False)
        layout.addWidget(self._progress_bar)

        layout.addStretch(1)

        footer = QHBoxLayout()
        footer.setSpacing(METRICS.spacing_sm)
        self._subtitle_label = QLabel(subtitle or "")
        self._subtitle_label.setProperty("class", "muted")
        self._subtitle_label.setVisible(bool(subtitle))
        footer.addWidget(self._subtitle_label)
        footer.addStretch(1)
        self._badge: StatusBadge | None = None
        self._footer_layout = footer
        layout.addLayout(footer)

        self._value_anim: QVariantAnimation | None = None

    def set_value(self, value: str) -> None:
        self._value_label.setText(value)

    def set_value_animated(self, target: int) -> None:
        """Count up (or down) from whatever numeric value is currently shown.

        Falls back to an instant ``set_value`` if the current text isn't
        a plain integer (e.g. still the initial "—" placeholder is
        treated as 0, which produces a pleasant count-up-from-zero on
        first load rather than a special case).
        """
        try:
            start = int(self._value_label.text())
        except ValueError:
            start = 0
        if start == target:
            self._value_label.setText(str(target))
            return

        if self._value_anim is not None:
            self._value_anim.stop()

        anim = QVariantAnimation(self)
        anim.setStartValue(start)
        anim.setEndValue(target)
        anim.setDuration(_VALUE_ANIM_DURATION_MS)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.valueChanged.connect(lambda v: self._value_label.setText(str(int(v))))
        self._value_anim = anim
        anim.start()

    def set_caption(self, text: str) -> None:
        """A real secondary metric line (e.g. "3 in production", "oldest: 2h ago").

        Never a fabricated trend/percentage-change — only ever text
        built from data the caller actually queried.
        """
        self._caption_label.setText(text)
        self._caption_label.setVisible(bool(text))

    def set_subtitle(self, subtitle: str) -> None:
        self._subtitle_label.setText(subtitle)
        self._subtitle_label.setVisible(bool(subtitle))

    def set_progress(self, ratio: float) -> None:
        """Show a thin progress bar. ``ratio`` is clamped to [0, 1]."""
        self._progress_bar.setValue(round(max(0.0, min(1.0, ratio)) * 100))
        self._progress_bar.setVisible(True)

    def set_badge(self, text: str, variant: Variant = "neutral") -> None:
        if self._badge is None:
            self._badge = StatusBadge(text, variant)
            self._footer_layout.addWidget(self._badge)
        else:
            self._badge.set_text(text)
            self._badge.set_variant(variant)
        self._badge.setVisible(True)
