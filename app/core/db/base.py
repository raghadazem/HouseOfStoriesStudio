"""Shared SQLAlchemy declarative base and mixins for all domain models.

Every domain model (``app.core.models.*``) inherits :class:`Base` plus
the two mixins here, so a UUID primary key and ``created_at``/
``updated_at`` timestamps never have to be hand-written per model.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Uuid
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative base shared by every House of Stories Studio model."""


def utc_now() -> datetime:
    """Return the current time as a timezone-aware UTC ``datetime``.

    Used as the default/onupdate for timestamp columns instead of a
    database-side ``CURRENT_TIMESTAMP`` so behavior is identical across
    SQLite and any future backend, and so tests can freeze/inspect it
    without touching the database.
    """
    return datetime.now(UTC)


class UUIDPrimaryKeyMixin:
    """Adds a UUID primary key column named ``id``.

    Stored via SQLAlchemy's cross-backend ``Uuid`` type, which SQLite
    persists as a 32-character hex string — there is no native SQLite
    UUID type.
    """

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )


class TimestampMixin:
    """Adds ``created_at`` and ``updated_at`` timezone-aware columns.

    Both are set in Python (not via database server defaults) so the
    value is identical regardless of backend and immediately visible on
    the in-memory object before a flush.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )
