"""age_label — "how long ago" for TimestampMixin's timezone-aware UTC columns.

Distinct from ``activity_timeline.format_relative_time``, which buckets
the *naive-local* timestamps ``app/logging_setup.py`` writes into log
lines — a different clock, deliberately not unified with this one (see
that module's own note). SQLite has no native tz-aware storage, so
SQLAlchemy round-trips a ``DateTime(timezone=True)`` column as a naive
datetime that still represents UTC; this treats a naive value as UTC
rather than assuming it's already tz-aware, so it's safe to call on a
raw ``TimestampMixin.created_at``/``updated_at`` regardless of backend.

Originally private to ``dashboard_page.py`` (as ``_age_label``); moved
here once the Review Queue page needed the exact same "how long has
this asset been waiting" calculation — one shared helper instead of
two copies drifting apart.
"""

from __future__ import annotations

from datetime import UTC, datetime


def age_label(timestamp: datetime) -> str:
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    seconds = max(0.0, (datetime.now(UTC) - timestamp).total_seconds())
    if seconds < 60:
        return "just now"
    minutes = int(seconds // 60)
    if minutes < 60:
        return f"{minutes}m ago"
    hours = int(minutes // 60)
    if hours < 24:
        return f"{hours}h ago"
    days = int(hours // 24)
    return f"{days}d ago"
