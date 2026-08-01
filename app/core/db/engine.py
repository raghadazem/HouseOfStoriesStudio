"""SQLite engine and session construction.

SQLite does not enforce foreign keys unless ``PRAGMA foreign_keys=ON``
is issued on every connection — SQLAlchemy does not do this
automatically. :func:`register_sqlite_pragma` attaches a per-connection
listener so it's never possible to accidentally get an engine with
foreign-key enforcement silently off.
"""

from __future__ import annotations

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.config import AppConfig, get_config


def register_sqlite_pragma(engine: Engine) -> Engine:
    """Attach a ``PRAGMA foreign_keys=ON`` listener to ``engine`` and return it.

    Registered per-engine (not globally on the ``Engine`` class) so this
    never affects unrelated engines a test or tool might create in the
    same process.
    """

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


def create_db_engine(
    config: AppConfig | None = None,
    *,
    database_url: str | None = None,
    echo: bool = False,
) -> Engine:
    """Create a SQLite engine with foreign-key enforcement enabled.

    Args:
        config: Configuration to read ``db_path`` from when
            ``database_url`` is not given. Defaults to
            :func:`app.config.get_config`.
        database_url: Explicit SQLAlchemy URL, e.g. ``"sqlite:///:memory:"``
            for tests. Overrides ``config`` entirely when given.
        echo: Passed through to :func:`sqlalchemy.create_engine` for SQL
            statement logging while debugging.
    """
    if database_url is None:
        cfg = config or get_config()
        cfg.ensure_runtime_dirs()
        database_url = f"sqlite:///{cfg.db_path}"

    engine = create_engine(database_url, echo=echo, future=True)
    return register_sqlite_pragma(engine)


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Return a session factory bound to ``engine``.

    ``expire_on_commit=False`` so objects (e.g. a freshly seeded
    ``Episode``) remain usable after commit without triggering a new
    query, which matters for a single-user desktop app with short-lived
    sessions.
    """
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)
