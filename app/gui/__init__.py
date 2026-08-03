"""PySide6 desktop UI layer.

Milestone 4A (the application shell): ``ApplicationContext``, the
centralized theme, the main window (top bar / sidebar / status bar),
and one functional screen (Dashboard). Every other sidebar section is
a placeholder until Milestone 4B.

This package must only call into ``app.core`` services (through
``ApplicationContext`` — never instantiate a service directly) and must
never touch the filesystem or database directly.
"""
