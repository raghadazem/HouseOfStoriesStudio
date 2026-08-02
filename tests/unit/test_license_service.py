"""Tests for LicenseService: history, commercial readiness, attribution."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.orm import Session

from app.core.db.enums import AssetType
from app.core.models import Asset
from app.core.services.exceptions import NotFoundError, ValidationError
from app.core.services.license_service import LicenseService


def _asset(session: Session) -> Asset:
    asset = Asset(
        asset_type=AssetType.MUSIC,
        original_filename="song.mp3",
        relative_path="episodes/ep001/audio/music/song.mp3",
        checksum="a" * 64,
    )
    session.add(asset)
    session.flush()
    return asset


def test_add_license_record_requires_existing_asset(session: Session) -> None:
    service = LicenseService()
    with pytest.raises(NotFoundError):
        service.add_license_record(session, uuid.uuid4(), license_type="royalty_free")


def test_multiple_license_records_form_a_history(session: Session) -> None:
    service = LicenseService()
    asset = _asset(session)
    service.add_license_record(session, asset.id, license_type="royalty_free", commercial_use_allowed=True)
    service.add_license_record(session, asset.id, license_type="revised_terms", commercial_use_allowed=False)

    history = service.list_asset_license_history(session, asset.id)
    assert len(history) == 2
    assert history[0].license_type == "royalty_free"
    assert history[1].license_type == "revised_terms"


def test_commercial_readiness_unknown_without_any_record(session: Session) -> None:
    service = LicenseService()
    asset = _asset(session)
    result = service.calculate_asset_commercial_readiness(session, asset.id)
    assert result.is_ready is False
    assert "unknown" in result.reason.lower()


def test_commercial_readiness_false_when_forbidden(session: Session) -> None:
    service = LicenseService()
    asset = _asset(session)
    service.add_license_record(session, asset.id, license_type="restricted", commercial_use_allowed=False)
    result = service.calculate_asset_commercial_readiness(session, asset.id)
    assert result.is_ready is False
    assert "forbidden" in result.reason.lower()


def test_commercial_readiness_false_when_attribution_missing(session: Session) -> None:
    service = LicenseService()
    asset = _asset(session)
    service.add_license_record(
        session, asset.id, license_type="cc_by", commercial_use_allowed=True, attribution_required=True
    )
    result = service.calculate_asset_commercial_readiness(session, asset.id)
    assert result.is_ready is False
    assert "attribution" in result.reason.lower()


def test_commercial_readiness_true_when_all_satisfied(session: Session) -> None:
    service = LicenseService()
    asset = _asset(session)
    service.add_license_record(
        session,
        asset.id,
        license_type="cc_by",
        commercial_use_allowed=True,
        attribution_required=True,
        attribution_text="Music by Example Artist",
    )
    result = service.calculate_asset_commercial_readiness(session, asset.id)
    assert result.is_ready is True


def test_commercial_readiness_uses_most_recent_record(session: Session) -> None:
    service = LicenseService()
    asset = _asset(session)
    service.add_license_record(session, asset.id, license_type="old", commercial_use_allowed=False)
    service.add_license_record(session, asset.id, license_type="renegotiated", commercial_use_allowed=True)
    result = service.calculate_asset_commercial_readiness(session, asset.id)
    assert result.is_ready is True


def test_verify_license_sets_verified_flag(session: Session) -> None:
    service = LicenseService()
    asset = _asset(session)
    record = service.add_license_record(session, asset.id, license_type="royalty_free")
    assert record.verified is False
    service.verify_license(session, record.id, verified_by="founder")
    assert record.verified is True
    assert record.verified_at is not None


def test_invalidate_license_requires_reason(session: Session) -> None:
    service = LicenseService()
    asset = _asset(session)
    record = service.add_license_record(session, asset.id, license_type="royalty_free", commercial_use_allowed=True)
    with pytest.raises(ValidationError):
        service.invalidate_license(session, record.id, reason="")


def test_invalidate_license_preserves_the_record_but_flips_commercial_use(
    session: Session,
) -> None:
    service = LicenseService()
    asset = _asset(session)
    record = service.add_license_record(
        session, asset.id, license_type="royalty_free", commercial_use_allowed=True
    )
    service.invalidate_license(session, record.id, reason="license expired")

    assert record.commercial_use_allowed is False
    assert "INVALIDATED" in record.notes
    # never deleted — still present in history
    assert record in service.list_asset_license_history(session, asset.id)


def test_generate_attribution_text_combines_required_entries(session: Session) -> None:
    service = LicenseService()
    asset = _asset(session)
    service.add_license_record(
        session, asset.id, license_type="a", attribution_required=True, attribution_text="Credit A"
    )
    service.add_license_record(
        session, asset.id, license_type="b", attribution_required=False, attribution_text="Should not appear"
    )
    text = service.generate_attribution_text(session, asset.id)
    assert text == "Credit A"
