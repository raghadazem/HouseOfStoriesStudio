"""Seed data: Melissa, Bilsan, Episode 001, and its three Shorts.

Everything here is either taken verbatim from the founder's approved
documentation (``docs/02_CHARACTER_BIBLE.md``) or the Milestone 2
approval message (Episode 001's titles/lesson/runtime), or is an
explicit placeholder pending approved artwork — no new creative content
is invented here. Safe to run more than once: existing rows are reused,
never duplicated.

This assumes the schema already exists (``alembic upgrade head`` has
been run) — seeding data is not a substitute for migrations.
"""

from __future__ import annotations

import logging

from sqlalchemy import inspect
from sqlalchemy.orm import Session

from app.core.db.enums import CharacterVersionStatus, ShortStatus
from app.core.models import Character, CharacterVersion, Episode, Short

logger = logging.getLogger("house_of_stories.seed")

MELISSA_SLUG = "melissa"
BILSAN_SLUG = "bilsan"
EPISODE_001_SLUG = "ep001_lost_little_turtle"

_PLACEHOLDER_REVIEW_NOTE = (
    "Awaiting approved reference artwork before this version can move to "
    "approved_canon."
)


def _get_or_create_character(session: Session, *, slug: str, **fields: object) -> Character:
    existing = session.query(Character).filter_by(slug=slug).one_or_none()
    if existing is not None:
        return existing
    character = Character(slug=slug, **fields)
    session.add(character)
    session.flush()
    return character


def _get_or_create_character_version(
    session: Session, *, character: Character, version_number: str, **fields: object
) -> CharacterVersion:
    existing = (
        session.query(CharacterVersion)
        .filter_by(character_id=character.id, version_number=version_number)
        .one_or_none()
    )
    if existing is not None:
        return existing
    version = CharacterVersion(
        character_id=character.id, version_number=version_number, **fields
    )
    session.add(version)
    session.flush()
    return version


def seed_melissa(session: Session) -> Character:
    """Seed Melissa's identity and a draft v01 Character Lock record.

    Traits and appearance come from ``docs/02_CHARACTER_BIBLE.md``.
    ``master_prompt``/``negative_prompt``/``color_palette`` are left
    empty and ``status`` stays ``DRAFT`` — no approved artwork exists
    yet, so nothing here should be treated as production-ready.
    """
    melissa = _get_or_create_character(
        session,
        slug=MELISSA_SLUG,
        name_ar="ميليسا",
        name_en="Melissa",
        age=6,
        role="older sister",
        traits=["brave", "curious", "kind", "loves nature"],
    )
    _get_or_create_character_version(
        session,
        character=melissa,
        version_number="v01",
        outfit_version="v01",
        description_of_change=(
            "Initial baseline from the approved Character Bible; no "
            "approved artwork yet."
        ),
        visual_summary=(
            "Two ponytails; denim dress; white shirt; red shoes "
            "(docs/02_CHARACTER_BIBLE.md). PLACEHOLDER pending approved "
            "animated model-sheet art — do not treat as final."
        ),
        color_palette=[],
        allowed_accessories=[],
        relative_height=None,
        master_prompt=None,
        negative_prompt=None,
        status=CharacterVersionStatus.DRAFT,
        review_notes=_PLACEHOLDER_REVIEW_NOTE,
    )
    return melissa


def seed_bilsan(session: Session) -> Character:
    """Seed Bilsan's identity and a draft v01 Character Lock record.

    See :func:`seed_melissa` for the placeholder rationale.
    """
    bilsan = _get_or_create_character(
        session,
        slug=BILSAN_SLUG,
        name_ar="بيلسان",
        name_en="Bilsan",
        age=4,
        role="younger sister",
        traits=["funny", "sweet", "loves singing", "curious"],
    )
    _get_or_create_character_version(
        session,
        character=bilsan,
        version_number="v01",
        outfit_version="v01",
        description_of_change=(
            "Initial baseline from the approved Character Bible; no "
            "approved artwork yet."
        ),
        visual_summary=(
            "Purple dress; curly hair; carries a teddy bear "
            "(docs/02_CHARACTER_BIBLE.md). PLACEHOLDER pending approved "
            "animated model-sheet art — do not treat as final."
        ),
        color_palette=[],
        allowed_accessories=["teddy bear"],
        relative_height=None,
        master_prompt=None,
        negative_prompt=None,
        status=CharacterVersionStatus.DRAFT,
        review_notes=_PLACEHOLDER_REVIEW_NOTE,
    )
    return bilsan


def seed_episode_001(session: Session, *, melissa: Character, bilsan: Character) -> Episode:
    """Seed Episode 001 (title/lesson from the founder's Milestone 2 approval) and its 3 Shorts."""
    episode = session.query(Episode).filter_by(slug=EPISODE_001_SLUG).one_or_none()
    if episode is None:
        episode = Episode(
            slug=EPISODE_001_SLUG,
            number=1,
            season=1,
            title_ar="ميليسا وبيلسان والسلحفاة الصغيرة الضائعة",
            title_en="Melissa and Bilsan and the Lost Little Turtle",
            lesson="Helping others",
            runtime_target_minutes_min=8,
            runtime_target_minutes_max=10,
            characters_featured=[melissa, bilsan],
        )
        session.add(episode)
        session.flush()

    existing_indexes = {short.short_index for short in episode.shorts}
    for index in (1, 2, 3):
        if index in existing_indexes:
            continue
        # Append to the relationship (not session.add()) so the
        # in-memory episode.shorts collection reflects the new rows
        # immediately, without needing an explicit refresh/expire.
        episode.shorts.append(Short(short_index=index, status=ShortStatus.PLANNED))
    session.flush()
    return episode


def seed_demo_data(session: Session) -> dict[str, object]:
    """Seed Melissa, Bilsan, Episode 001, and its three Shorts.

    Idempotent and safe to call against a database that already has
    some or all of this data. Commits on success.
    """
    melissa = seed_melissa(session)
    bilsan = seed_bilsan(session)
    episode = seed_episode_001(session, melissa=melissa, bilsan=bilsan)
    session.commit()
    logger.info(
        "Seed data ready: %s, %s, %s (%d shorts)",
        melissa.slug,
        bilsan.slug,
        episode.slug,
        len(episode.shorts),
    )
    return {"melissa": melissa, "bilsan": bilsan, "episode_001": episode}


def main() -> None:
    """CLI entry point: ``python -m app.core.db.seed``."""
    from app.core.db.engine import create_db_engine, create_session_factory
    from app.logging_setup import configure_logging

    configure_logging()
    engine = create_db_engine()

    if "characters" not in inspect(engine).get_table_names():
        raise RuntimeError(
            "Database schema not found. Run `alembic upgrade head` "
            "before seeding data."
        )

    session_factory = create_session_factory(engine)
    with session_factory() as session:
        seed_demo_data(session)


if __name__ == "__main__":
    main()
