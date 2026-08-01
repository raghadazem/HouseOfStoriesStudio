"""Tests for PromptTemplate, ProductionTask, ApprovalRecord, and LicenseRecord."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.db.enums import (
    ApprovalDecision,
    AssetType,
    ProductionTaskStatus,
    PromptType,
)
from app.core.models import (
    Asset,
    Character,
    Episode,
    LicenseRecord,
    ProductionTask,
    PromptTemplate,
)
from app.core.models.approval import ApprovalRecord


def _make_episode() -> Episode:
    return Episode(
        slug="ep001_lost_little_turtle",
        number=1,
        title_ar="ميليسا وبيلسان والسلحفاة الصغيرة الضائعة",
        title_en="Melissa and Bilsan and the Lost Little Turtle",
        lesson="Helping others",
    )


# --- PromptTemplate -----------------------------------------------------


def test_prompt_template_reusable_character_lock_block(session: Session) -> None:
    melissa = Character(slug="melissa", name_ar="ميليسا", name_en="Melissa")
    session.add(melissa)
    session.flush()

    prompt = PromptTemplate(
        name="melissa_master_prompt",
        version="v01",
        prompt_type=PromptType.IMAGE,
        text_en="Melissa: 6-year-old girl, two ponytails, denim dress...",
        is_reusable=True,
        character_id=melissa.id,
    )
    session.add(prompt)
    session.commit()

    assert prompt.character.slug == "melissa"
    assert prompt.is_reusable is True


def test_prompt_template_name_and_version_must_be_unique_together(session: Session) -> None:
    session.add(
        PromptTemplate(
            name="melissa_master_prompt",
            version="v01",
            prompt_type=PromptType.IMAGE,
            text_en="v1 text",
        )
    )
    session.commit()

    session.add(
        PromptTemplate(
            name="melissa_master_prompt",
            version="v01",
            prompt_type=PromptType.IMAGE,
            text_en="duplicate name+version",
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()


def test_prompt_template_same_name_different_version_allowed(session: Session) -> None:
    session.add(
        PromptTemplate(
            name="melissa_master_prompt",
            version="v01",
            prompt_type=PromptType.IMAGE,
            text_en="v1 text",
        )
    )
    session.add(
        PromptTemplate(
            name="melissa_master_prompt",
            version="v02",
            prompt_type=PromptType.IMAGE,
            text_en="v2 text",
        )
    )
    session.commit()  # must not raise


# --- ProductionTask -------------------------------------------------------


def test_production_task_defaults_to_pending(session: Session) -> None:
    episode = _make_episode()
    session.add(episode)
    session.flush()

    task = ProductionTask(
        episode_id=episode.id,
        task_type="write_script",
        title="Write scene 1 script",
    )
    session.add(task)
    session.commit()

    assert task.status == ProductionTaskStatus.PENDING
    assert task.episode.slug == "ep001_lost_little_turtle"


# --- ApprovalRecord ---------------------------------------------------


def test_approval_record_is_polymorphic_and_not_a_foreign_key(session: Session) -> None:
    """entity_id intentionally has no FK — it can reference any approvable table."""
    fake_entity_id = uuid.uuid4()
    record = ApprovalRecord(
        entity_type="character_version",
        entity_id=fake_entity_id,
        decision=ApprovalDecision.NEEDS_CHANGES,
        decided_by="founder",
        notes="Outfit color needs to match the approved palette.",
    )
    session.add(record)
    session.commit()  # must not raise even though nothing with this id exists

    assert record.entity_id == fake_entity_id
    assert record.decision == ApprovalDecision.NEEDS_CHANGES


# --- LicenseRecord ---------------------------------------------------------


def test_license_record_links_to_asset(session: Session) -> None:
    asset = Asset(
        asset_type=AssetType.MUSIC,
        original_filename="episode_theme_v01.mp3",
        relative_path="episodes/ep001/audio/music/episode_theme_v01.mp3",
        checksum="d" * 64,
    )
    session.add(asset)
    session.flush()

    license_record = LicenseRecord(
        asset_id=asset.id,
        license_type="royalty_free",
        source_url="https://example.com/license",
        commercial_use_allowed=True,
        verified=True,
    )
    session.add(license_record)
    session.commit()

    assert asset.id == license_record.asset.id
    assert license_record.commercial_use_allowed is True
