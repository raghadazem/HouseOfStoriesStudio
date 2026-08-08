"""StorageService — safe filesystem operations under the managed storage root.

Every path this service touches is resolved relative to
``AppConfig.production_dir`` (the "managed storage root"). Nothing here
ever writes outside it — any attempt to escape it (via ``..``, an
absolute path, or a symlink resolving outside) is rejected before any
filesystem operation happens. This is the one place in the codebase
that touches the filesystem for asset storage; every other service
that needs to read/write a managed file goes through this one.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import uuid
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import AppConfig, get_config
from app.core.models import Asset
from app.core.naming import collision_safe_name
from app.core.services.exceptions import ValidationError

_CHECKSUM_CHUNK_SIZE = 1024 * 1024  # 1 MB


def _win_long_path(path: Path) -> str:
    """A path string safe to pass to ``shutil``/``os`` file operations on
    Windows even when it exceeds the legacy 260-character ``MAX_PATH``.

    Windows file APIs reject an absolute path longer than ``MAX_PATH``
    unless it carries the ``\\\\?\\`` extended-length prefix (no admin
    rights or OS-level "enable long paths" setting required — that
    prefix alone is what raises the limit, from the calling process's
    side, to ~32,767 characters). Found via
    ``copy_file_atomic`` intermittently raising ``WinError 3`` — not a
    race or antivirus interference, but a plain over-the-limit path
    (deep pytest tmp dirs + a 64-hex-char content-digest filename
    reliably crossed it). A no-op everywhere except Windows, and even
    there, a no-op for a path already under the limit or already
    prefixed. See ``docs/28_ASSET_IMPORT_AND_GUI_TEST_ISOLATION_STATUS.md``.
    """
    if os.name != "nt":
        return str(path)
    resolved = str(path.resolve())
    if resolved.startswith("\\\\?\\"):
        return resolved
    return "\\\\?\\" + resolved


class StorageService:
    """Filesystem operations scoped to ``AppConfig.production_dir``."""

    def __init__(self, config: AppConfig | None = None) -> None:
        self._config = config or get_config()

    @property
    def root(self) -> Path:
        """The managed storage root — ``AppConfig.production_dir``."""
        return self._config.production_dir

    def resolve_managed_path(self, relative_path: str) -> Path:
        """Resolve ``relative_path`` under the managed storage root.

        Raises:
            ValidationError: If the resolved path would fall outside
                ``production_dir`` (path traversal, an absolute path
                slipped through, or similar).
        """
        root_resolved = self.root.resolve()
        candidate = (self.root / relative_path).resolve()
        try:
            candidate.relative_to(root_resolved)
        except ValueError as err:
            raise ValidationError(
                f"Path {relative_path!r} escapes the managed storage root "
                f"{root_resolved}."
            ) from err
        return candidate

    def ensure_dir(self, relative_dir: str) -> Path:
        """Create ``relative_dir`` (and parents) under the managed root, return it."""
        path = self.resolve_managed_path(relative_dir)
        path.mkdir(parents=True, exist_ok=True)
        return path

    @staticmethod
    def compute_checksum(path: Path) -> str:
        """Compute the sha256 hex digest of the file at ``path``, streaming in chunks."""
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(_CHECKSUM_CHUNK_SIZE), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def verify_checksum(self, path: Path, expected_checksum: str) -> None:
        """Confirm the file at ``path`` hashes to ``expected_checksum``.

        Raises:
            ValidationError: On mismatch — this is what catches a copy
                that was silently corrupted or truncated in transit.
        """
        actual = self.compute_checksum(path)
        if actual.lower() != expected_checksum.lower():
            raise ValidationError(
                f"Checksum mismatch for {path}: expected {expected_checksum}, got {actual}."
            )

    def collision_safe_relative_path(self, relative_dir: str, desired_filename: str) -> str:
        """Return a relative path under ``relative_dir`` that won't overwrite an existing file."""
        dir_path = self.resolve_managed_path(relative_dir)
        existing = {p.name for p in dir_path.iterdir()} if dir_path.is_dir() else set()
        safe_name = collision_safe_name(desired_filename, existing)
        return f"{relative_dir.rstrip('/')}/{safe_name}" if relative_dir else safe_name

    def copy_file_atomic(self, source: Path, dest_relative_path: str) -> Path:
        """Copy ``source`` into managed storage at ``dest_relative_path``, atomically.

        Copies to a temporary file in the destination directory first,
        then uses ``os.replace`` (atomic on the same filesystem) to move
        it into place — an interrupted copy never leaves a partially
        written file at the final destination path.
        """
        dest = self.resolve_managed_path(dest_relative_path)
        os.makedirs(_win_long_path(dest.parent), exist_ok=True)
        # Short and content-independent on purpose (see _win_long_path):
        # the old scheme embedded the full (already long, digest-based)
        # destination filename in the temp name too, which was enough on
        # its own to push some otherwise-fine destination paths over
        # Windows' legacy 260-character MAX_PATH.
        temp_path = dest.parent / f".{uuid.uuid4().hex}.tmp"
        try:
            shutil.copy2(_win_long_path(source), _win_long_path(temp_path))
            os.replace(_win_long_path(temp_path), _win_long_path(dest))
        except Exception:
            try:
                os.remove(_win_long_path(temp_path))
            except FileNotFoundError:
                pass
            raise
        return dest

    def cleanup(self, path: Path) -> None:
        """Delete ``path`` if it exists and is inside the managed storage root.

        Idempotent (a missing file is not an error) — meant for undoing
        a partially completed import. Silently refuses to delete
        anything outside ``production_dir`` as a defense-in-depth guard,
        even though every caller is expected to only ever pass a managed
        path here.
        """
        root_resolved = self.root.resolve()
        resolved = path.resolve()
        try:
            resolved.relative_to(root_resolved)
        except ValueError:
            return
        resolved.unlink(missing_ok=True)

    def find_duplicate_by_checksum(self, session: Session, checksum: str) -> Asset | None:
        """Return the existing :class:`Asset` with this checksum, if any."""
        return session.query(Asset).filter_by(checksum=checksum.lower()).one_or_none()

    def prepare_export_copy(self, source_relative_path: str, dest_path: Path) -> Path:
        """Copy a managed asset to an export destination without mutating the original.

        ``dest_path`` is an absolute path the caller has already
        resolved (typically also under ``production_dir``, e.g. an
        episode's ``exports/`` folder) — this method does not further
        validate it, since :class:`~app.core.services.export_package_service.ExportPackageService`
        builds it via :meth:`resolve_managed_path` itself.
        """
        source = self.resolve_managed_path(source_relative_path)
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = dest_path.parent / f".{dest_path.name}.{uuid.uuid4().hex}.tmp"
        shutil.copy2(source, temp_path)
        os.replace(temp_path, dest_path)
        return dest_path
