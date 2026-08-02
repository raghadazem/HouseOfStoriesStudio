"""Session lifecycle: a small unit-of-work helper for the service layer.

**Convention:** service methods take an already-open
:class:`~sqlalchemy.orm.Session` and only ``flush()`` it (so constraint
violations surface immediately as exceptions) — they do not call
``commit()``. The *caller* (CLI command, test, or a future GUI event
handler) decides transaction boundaries by wrapping one or more service
calls in :func:`session_scope`, so multiple service calls can be
composed into one atomic transaction.

**The one documented exception** is
``AssetImportService.import_asset``: it spans the filesystem *and* the
database, and must keep the two in sync even if the caller never wraps
it in a scope, so it manages its own commit/rollback (and matching
filesystem cleanup) internally. See ``docs/14_ASSET_IMPORT_WORKFLOW.md``.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy.orm import Session, sessionmaker


@contextmanager
def session_scope(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    """Open a session, commit on success, roll back and re-raise on error.

    Usage::

        with session_scope(session_factory) as session:
            episode = EpisodeService().create_episode(session, ...)
            SceneService().add_scene(session, episode.id, ...)
        # both commit together, or neither does
    """
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
