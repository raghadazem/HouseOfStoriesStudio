"""Tests for StorageService: path safety, atomic copy, checksums, cleanup."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from app.config import AppConfig, load_config
from app.core.services.exceptions import ValidationError
from app.core.services.storage_service import StorageService


@pytest.mark.parametrize(
    "bad_relative_path",
    ["../../etc/passwd", "characters/../../../etc/passwd", "/etc/passwd"],
)
def test_resolve_managed_path_rejects_traversal(app_config: AppConfig, bad_relative_path: str) -> None:
    storage = StorageService(app_config)
    with pytest.raises(ValidationError):
        storage.resolve_managed_path(bad_relative_path)


def test_resolve_managed_path_accepts_normal_relative_path(app_config: AppConfig) -> None:
    storage = StorageService(app_config)
    resolved = storage.resolve_managed_path("episodes/ep001/images/scene01.png")
    assert resolved == (app_config.production_dir / "episodes/ep001/images/scene01.png").resolve()


def test_ensure_dir_creates_nested_directories(app_config: AppConfig) -> None:
    storage = StorageService(app_config)
    created = storage.ensure_dir("characters/melissa/versions/v01")
    assert created.is_dir()


def test_compute_checksum_is_deterministic(app_config: AppConfig, source_file: Path) -> None:
    storage = StorageService(app_config)
    first = storage.compute_checksum(source_file)
    second = storage.compute_checksum(source_file)
    assert first == second
    assert len(first) == 64


def test_verify_checksum_passes_for_correct_checksum(app_config: AppConfig, source_file: Path) -> None:
    storage = StorageService(app_config)
    checksum = storage.compute_checksum(source_file)
    storage.verify_checksum(source_file, checksum)  # must not raise


def test_verify_checksum_fails_for_wrong_checksum(app_config: AppConfig, source_file: Path) -> None:
    storage = StorageService(app_config)
    with pytest.raises(ValidationError, match="Checksum mismatch"):
        storage.verify_checksum(source_file, "0" * 64)


def test_copy_file_atomic_copies_content_and_preserves_source(
    app_config: AppConfig, source_file: Path
) -> None:
    storage = StorageService(app_config)
    dest = storage.copy_file_atomic(source_file, "episodes/ep001/images/scene01.png")

    assert dest.is_file()
    assert dest.read_bytes() == source_file.read_bytes()
    assert source_file.exists()  # never deletes the source


def test_copy_file_atomic_leaves_no_temp_file_behind(app_config: AppConfig, source_file: Path) -> None:
    storage = StorageService(app_config)
    dest = storage.copy_file_atomic(source_file, "episodes/ep001/images/scene01.png")
    remaining = list(dest.parent.iterdir())
    assert remaining == [dest]


def test_collision_safe_relative_path_avoids_existing_file(
    app_config: AppConfig, source_file: Path
) -> None:
    storage = StorageService(app_config)
    storage.copy_file_atomic(source_file, "episodes/ep001/images/scene01.png")
    safe_path = storage.collision_safe_relative_path("episodes/ep001/images", "scene01.png")
    assert safe_path == "episodes/ep001/images/scene01_2.png"


def test_cleanup_removes_file_inside_managed_root(app_config: AppConfig, source_file: Path) -> None:
    storage = StorageService(app_config)
    dest = storage.copy_file_atomic(source_file, "episodes/ep001/images/scene01.png")
    assert dest.exists()
    storage.cleanup(dest)
    assert not dest.exists()


def test_cleanup_is_idempotent_on_missing_file(app_config: AppConfig) -> None:
    storage = StorageService(app_config)
    missing = app_config.production_dir / "episodes/ep001/images/does_not_exist.png"
    storage.cleanup(missing)  # must not raise


def test_cleanup_refuses_to_delete_outside_managed_root(
    app_config: AppConfig, source_file: Path
) -> None:
    storage = StorageService(app_config)
    assert source_file.exists()
    storage.cleanup(source_file)  # outside production_dir -> silently refused
    assert source_file.exists()


# --- Windows MAX_PATH regression (docs/28_ASSET_IMPORT_AND_GUI_TEST_ISOLATION_STATUS.md) ---
# copy_file_atomic used to build its scratch temp filename by wrapping
# the *destination's own* filename (".{dest.name}.{uuid}.tmp"): always
# exactly 37 characters longer than the destination path itself (a
# leading ".", the 32-hex-char uuid, ".tmp", plus the extra "." before
# it). For a destination path already within about 37 characters of
# Windows' legacy 260-character MAX_PATH -- easy to reach with a deep
# episode/asset-type directory plus MockProvider's 64-hex-char
# content-digest filenames -- that fixed overhead alone pushed the
# *temp* file (never the destination itself) over the limit, producing
# an intermittent-looking WinError 3 that had nothing to do with
# timing, antivirus, or concurrency.
#
# Uses its own short tempfile.mkdtemp() base (not the `app_config`
# fixture's pytest tmp_path, whose length varies by test name and
# isn't under this test's control) so the destination length is
# precisely, deterministically engineered: comfortably under 260 (so
# this test's own plain-pathlib assertions are meaningful) while what
# the *old* temp-naming scheme would have produced is reliably over it.


def _short_storage_service(tmp_path_str: str) -> StorageService:
    config = load_config(
        env={
            "HOS_PROJECT_ROOT": tmp_path_str,
            "HOS_DATA_DIR": f"{tmp_path_str}\\data",
            "HOS_PRODUCTION_DIR": f"{tmp_path_str}\\production",
        }
    )
    return StorageService(config)


def test_copy_file_atomic_succeeds_when_old_temp_naming_would_have_exceeded_max_path(
    source_file: Path,
) -> None:
    short_base = tempfile.mkdtemp()
    storage = _short_storage_service(short_base)

    # A realistic MockProvider-shaped filename (see mock_provider.py):
    # "mock_image_" + a 64-hex-char sha256 digest + ".png".
    filename = "mock_image_" + ("e17166e4f6721b44254804fbfddb9d669f4e186326413e06a8fb19f8b8aff7a") + ".png"
    production_dir_len = len(str(storage.root))
    # Solve for a nesting depth that lands the destination path at 240
    # characters: comfortably under MAX_PATH on its own, but only 20
    # characters of headroom -- well within the old scheme's fixed
    # 37-character temp-name overhead, so the old scheme would reliably
    # have failed here while the new one must still succeed.
    target_dest_len = 240
    filler_len = max(0, target_dest_len - production_dir_len - len(filename) - 2)
    deep_dir = "d" * filler_len
    dest_relative_path = f"{deep_dir}/{filename}"

    dest = storage.copy_file_atomic(source_file, dest_relative_path)

    assert len(str(dest)) < 260  # this test's own assertions stay meaningful
    old_temp_name_len = len(str(dest)) + 37  # the exact old .{name}.{uuid}.tmp overhead
    assert old_temp_name_len > 260  # confirms the old scheme really would have failed here
    assert dest.is_file()
    assert dest.read_bytes() == source_file.read_bytes()
    assert source_file.exists()  # still never deletes the source
    assert list(dest.parent.iterdir()) == [dest]  # no leftover .tmp scratch file
