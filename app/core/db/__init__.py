"""Database layer: declarative base, mixins, enums, and engine/session setup.

Domain models live in ``app.core.models``, not here — this package only
provides the shared plumbing they're built on.
"""

from app.core.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.core.db.engine import create_db_engine, create_session_factory, register_sqlite_pragma

__all__ = [
    "Base",
    "TimestampMixin",
    "UUIDPrimaryKeyMixin",
    "create_db_engine",
    "create_session_factory",
    "register_sqlite_pragma",
]
