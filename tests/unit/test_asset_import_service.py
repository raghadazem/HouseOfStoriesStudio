"""Tests for AssetImportService: validation, duplicate detection, rollback, privacy."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.config import AppConfig, load_config
from app.core.db.enums import ApprovalStatus, AssetType
from app.core.models import Asset, Episode
from app.core.services.asset_import_service import AssetImportService, ImportRequest
from app.core.services.exceptions import (
    AssetImportError,
    ConflictError,
    NotFoundError,
    PrivacyViolationError,
    ValidationError,
)
from app.core.services.scene_service import SceneService
from app.core.services.storage_service import StorageService


def _service(app_config: AppConfig) -> AssetImportService:
    return AssetImportService(app_config, StorageService(app_config))


def test_import_asset_success(session: Session, app_config: AppConfig, source_file: Path) -> None:
    service = _service(app_config)
    request = ImportRequest(source_path=source_file, asset_type=AssetType.IMAGE, source_tool="test_tool")

    asset = service.import_asset(session, request)

    assert asset.id is not None
    assert asset.asset_type == AssetType.IMAGE
    assert asset.original_filename == source_file.name
    assert asset.approval_status == ApprovalStatus.DRAFT
    assert asset.source_tool == "test_tool"
    stored_path = app_config.production_dir / asset.relative_path
    assert stored_path.is_file()
    assert stored_path.read_bytes() == source_file.read_bytes()
    assert source_file.exists()  # source is never deleted


def test_import_asset_rejects_missing_file(
    session: Session, app_config: AppConfig, tmp_path: Path
) -> None:
    service = _service(app_config)
    request = ImportRequest(source_path=tmp_path / "nope.png", asset_type=AssetType.IMAGE)
    with pytest.raises(ValidationError, match="does not exist"):
        service.import_asset(session, request)


def test_import_asset_rejects_directory(
    session: Session, app_config: AppConfig, tmp_path: Path
) -> None:
    directory = tmp_path / "a_directory"
    directory.mkdir()
    service = _service(app_config)
    request = ImportRequest(source_path=directory, asset_type=AssetType.IMAGE)
    with pytest.raises(ValidationError, match="directory"):
        service.import_asset(session, request)


def test_import_asset_rejects_restricted_reference_photo_directory(
    session: Session, tmp_path: Path
) -> None:
    private_dir = tmp_path / "private_photos"
    private_dir.mkdir()
    photo = private_dir / "family.jpg"
    photo.write_bytes(b"personal photo bytes")

    config = load_config(
        env={
            "HOS_PROJECT_ROOT": str(tmp_path),
            "HOS_DATA_DIR": str(tmp_path / "data"),
            "HOS_PRODUCTION_DIR": str(tmp_path / "production"),
            "HOS_RESTRICTED_IMPORT_DIRS": str(private_dir),
        }
    )
    (tmp_path / "production").mkdir()
    service = _service(config)
    request = ImportRequest(source_path=photo, asset_type=AssetType.IMAGE)

    with pytest.raises(PrivacyViolationError, match="restricted"):
        service.import_asset(session, request)

    # Nothing was imported: no DB row, no file copied anywhere under production/.
    assert session.query(Asset).count() == 0


def test_import_asset_rejects_unsupported_classification(
    session: Session, app_config: AppConfig, source_file: Path
) -> None:
    service = _service(app_config)
    request = ImportRequest(source_path=source_file, asset_type="personal_photo")  # type: ignore[arg-type]
    with pytest.raises(ValidationError, match="Unsupported asset classification"):
        service.import_asset(session, request)


def test_import_asset_rejects_reserved_scene_key_image_role(
    session: Session, app_config: AppConfig, source_file: Path
) -> None:
    """The generic/manual import path must never be able to assign
    "final_scene_image" — only SceneService.set_scene_key_image may,
    since that's what guarantees at most one Asset holds it per scene
    (see docs/32_MILESTONE_8_SCENE_IMAGE_GENERATION_STATUS.md)."""
    service = _service(app_config)
    request = ImportRequest(
        source_path=source_file, asset_type=AssetType.IMAGE, role="final_scene_image"
    )
    with pytest.raises(ValidationError, match="reserved"):
        service.import_asset(session, request)

    # Nothing was imported: no DB row, no file copied anywhere under production/.
    assert session.query(Asset).count() == 0


def test_import_asset_rejects_reserved_line_voice_role(
    session: Session, app_config: AppConfig, source_file: Path
) -> None:
    """Mirrors the final_scene_image regression test: the generic/manual
    import path must never be able to assign "final_line_voice" —
    only SceneService.set_line_final_take may (see
    docs/33_MILESTONE_9_REAL_VOICE_PRODUCTION_STATUS.md)."""
    service = _service(app_config)
    request = ImportRequest(
        source_path=source_file, asset_type=AssetType.VOICE, role="final_line_voice"
    )
    with pytest.raises(ValidationError, match="reserved"):
        service.import_asset(session, request)

    assert session.query(Asset).count() == 0


def test_import_asset_stores_dialogue_line_id_and_duration(
    session: Session, app_config: AppConfig, source_file: Path
) -> None:
    episode = Episode(slug="ep001_test", number=1, title_ar="ع", title_en="Test", lesson="Sharing")
    session.add(episode)
    session.flush()
    scene = SceneService().add_scene(session, episode.id, dialogue_ar="ميليسا: مرحباً")
    line = SceneService().sync_dialogue_lines(session, scene.id)[0]
    service = _service(app_config)
    request = ImportRequest(
        source_path=source_file,
        asset_type=AssetType.VOICE,
        scene_id=scene.id,
        dialogue_line_id=line.id,
        duration_seconds=2.75,
    )

    asset = service.import_asset(session, request)

    assert asset.dialogue_line_id == line.id
    assert asset.duration_seconds == 2.75


def test_import_asset_rejects_dialogue_line_from_another_scene(
    session: Session, app_config: AppConfig, source_file: Path
) -> None:
    episode = Episode(slug="ep001_test", number=1, title_ar="ع", title_en="Test", lesson="Sharing")
    session.add(episode)
    session.flush()
    ss = SceneService()
    scene_a = ss.add_scene(session, episode.id, dialogue_ar="ميليسا: مرحباً")
    scene_b = ss.add_scene(session, episode.id)
    line = ss.sync_dialogue_lines(session, scene_a.id)[0]
    service = _service(app_config)
    request = ImportRequest(
        source_path=source_file,
        asset_type=AssetType.VOICE,
        scene_id=scene_b.id,
        dialogue_line_id=line.id,
    )

    with pytest.raises(ValidationError, match="does not belong"):
        service.import_asset(session, request)


def test_import_asset_rejects_unknown_dialogue_line(
    session: Session, app_config: AppConfig, source_file: Path
) -> None:
    service = _service(app_config)
    request = ImportRequest(
        source_path=source_file, asset_type=AssetType.VOICE, dialogue_line_id=uuid.uuid4()
    )

    with pytest.raises(NotFoundError):
        service.import_asset(session, request)


def test_import_asset_detects_duplicate_by_checksum(
    session: Session, app_config: AppConfig, source_file: Path
) -> None:
    service = _service(app_config)
    request = ImportRequest(source_path=source_file, asset_type=AssetType.IMAGE)
    service.import_asset(session, request)
    session.commit()

    with pytest.raises(ConflictError, match="already imported"):
        service.import_asset(session, request)

    assert session.query(Asset).count() == 1


def test_import_asset_normalizes_filename(
    session: Session, app_config: AppConfig, tmp_path: Path
) -> None:
    weird_name = tmp_path / "Melissa Front (1).PNG"
    weird_name.write_bytes(b"content")
    service = _service(app_config)
    asset = service.import_asset(
        session, ImportRequest(source_path=weird_name, asset_type=AssetType.IMAGE)
    )
    assert asset.original_filename == "Melissa Front (1).PNG"  # preserved verbatim
    assert Path(asset.relative_path).name == "melissa_front_1.png"  # normalized on disk


def test_import_asset_arabic_filename_is_handled_safely(
    session: Session, app_config: AppConfig, tmp_path: Path
) -> None:
    arabic_name = tmp_path / "ميليسا.png"
    arabic_name.write_bytes(b"content")
    service = _service(app_config)
    asset = service.import_asset(
        session, ImportRequest(source_path=arabic_name, asset_type=AssetType.IMAGE)
    )
    assert asset.original_filename == "ميليسا.png"  # Arabic preserved in the DB field
    stored_name = Path(asset.relative_path).name
    assert stored_name.isascii()  # but the on-disk filename stays ASCII snake_case
    assert (app_config.production_dir / asset.relative_path).is_file()


def test_import_asset_rejects_unknown_episode(
    session: Session, app_config: AppConfig, source_file: Path
) -> None:
    import uuid

    service = _service(app_config)
    request = ImportRequest(
        source_path=source_file, asset_type=AssetType.IMAGE, episode_id=uuid.uuid4()
    )
    with pytest.raises(NotFoundError):
        service.import_asset(session, request)


def test_import_asset_associates_with_episode(
    session: Session, app_config: AppConfig, source_file: Path
) -> None:
    episode = Episode(
        slug="ep001_test", number=1, title_ar="ع", title_en="Test", lesson="Sharing"
    )
    session.add(episode)
    session.flush()

    service = _service(app_config)
    asset = service.import_asset(
        session,
        ImportRequest(source_path=source_file, asset_type=AssetType.IMAGE, episode_id=episode.id),
    )
    assert asset.episode_id == episode.id
    assert f"episodes/{episode.slug}/images" in asset.relative_path


def test_import_asset_rolls_back_db_and_filesystem_on_failure(
    session: Session, app_config: AppConfig, source_file: Path, monkeypatch
) -> None:
    """If something fails after the file copy, neither the DB row nor the copied file survive."""
    service = _service(app_config)

    original_verify = StorageService.verify_checksum

    def _boom(self, path, expected_checksum):
        raise RuntimeError("simulated post-copy failure")

    monkeypatch.setattr(StorageService, "verify_checksum", _boom)

    request = ImportRequest(source_path=source_file, asset_type=AssetType.IMAGE)
    with pytest.raises(AssetImportError, match="simulated post-copy failure"):
        service.import_asset(session, request)

    monkeypatch.setattr(StorageService, "verify_checksum", original_verify)

    assert session.query(Asset).count() == 0
    copied_files = list((app_config.production_dir / "_imports" / "images").glob("*")) if (
        app_config.production_dir / "_imports" / "images"
    ).exists() else []
    assert copied_files == []
    assert source_file.exists()  # the original is always left alone
