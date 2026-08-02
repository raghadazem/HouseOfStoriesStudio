"""Tests for StorageService: path safety, atomic copy, checksums, cleanup."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config import AppConfig
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
