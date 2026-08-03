"""Centralized theme: design tokens + the manager that applies them.

No widget outside this package should write a literal color — see
``docs/21_DESIGN_SYSTEM.md``.
"""

from __future__ import annotations

from app.gui.theme.manager import ThemeManager
from app.gui.theme.tokens import METRICS, ThemeTokens

__all__ = ["METRICS", "ThemeManager", "ThemeTokens"]
