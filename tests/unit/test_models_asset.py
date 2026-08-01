"""Tests for Asset: validation, duplicate detection, and relative-path rules."""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.db.enums import ApprovalStatus, AssetType
from app.core.models import Asset


def _make_asset(**overrides: object) -> Asset:
    defaults: dict[str, object] = {
        "asset_type": AssetType.IMAGE,
        "original_filename": "melissa_front_v01.png",
        "relative_path": "characters/melissa/reference/melissa_front_v01.png",
        "checksum": "a" * 64,
    }
    defaults.update(overrides)
    return Asset(**defaults)


def test_asset_defaults_to_draft_approval(session: Session) -> None:
    asset = _make_asset()
    session.add(asset)
    session.commit()

    assert asset.approval_status == ApprovalStatus.DRAFT


def test_asset_relative_path_is_stored_relative(session: Session) -> None:
    asset = _make_asset(relative_path="episodes/ep001/images/scene01_v01.png")
    session.add(asset)
    session.commit()

    assert asset.relative_path == "episodes/ep001/images/scene01_v01.png"


@pytest.mark.parametrize(
    "bad_path",
    [
        "/etc/passwd",
        "C:\\Users\\founder\\Desktop\\photo.png",
        "\\\\network\\share\\file.png",
    ],
)
def test_asset_rejects_absolute_paths(bad_path: str) -> None:
    with pytest.raises(ValueError, match="relative"):
        _make_asset(relative_path=bad_path)


def test_asset_rejects_parent_directory_traversal() -> None:
    with pytest.raises(ValueError, match="\\.\\."):
        _make_asset(relative_path="characters/../../etc/passwd")


def test_asset_rejects_empty_relative_path() -> None:
    with pytest.raises(ValueError):
        _make_asset(relative_path="")


def test_asset_normalizes_windows_separators_to_posix(session: Session) -> None:
    asset = _make_asset(relative_path="characters\\melissa\\reference\\front.png")
    session.add(asset)
    session.commit()

    assert asset.relative_path == "characters/melissa/reference/front.png"


def test_asset_checksum_must_be_64_char_hex() -> None:
    with pytest.raises(ValueError, match="sha256"):
        _make_asset(checksum="not-a-real-checksum")


def test_asset_checksum_is_lowercased(session: Session) -> None:
    asset = _make_asset(checksum="A" * 64)
    session.add(asset)
    session.commit()

    assert asset.checksum == "a" * 64


def test_duplicate_relative_path_rejected(session: Session) -> None:
    session.add(_make_asset(relative_path="episodes/ep001/images/scene01_v01.png", checksum="a" * 64))
    session.commit()

    session.add(_make_asset(relative_path="episodes/ep001/images/scene01_v01.png", checksum="b" * 64))
    with pytest.raises(IntegrityError):
        session.commit()


def test_duplicate_checksum_rejected(session: Session) -> None:
    """Importing the same bytes under a different filename must be caught.

    This is the database-level half of the founder's "duplicate
    detection" requirement — the (future) import service can catch this
    IntegrityError and turn it into a friendly message.
    """
    session.add(_make_asset(relative_path="episodes/ep001/images/scene01_v01.png", checksum="c" * 64))
    session.commit()

    session.add(_make_asset(relative_path="episodes/ep001/images/scene01_v02_renamed.png", checksum="c" * 64))
    with pytest.raises(IntegrityError):
        session.commit()


def test_asset_records_provenance_and_license_fields(session: Session) -> None:
    asset = _make_asset(
        source_tool="bing_image_creator",
        license_status="tool_terms_permit_commercial_use",
        commercial_use_status="allowed",
        notes="Generated for scene 1, approved on first pass.",
    )
    session.add(asset)
    session.commit()

    session.expunge_all()
    reloaded = session.get(Asset, asset.id)
    assert reloaded is not None
    assert reloaded.source_tool == "bing_image_creator"
    assert reloaded.commercial_use_status == "allowed"
