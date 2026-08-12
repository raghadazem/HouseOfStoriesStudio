"""Tests for SceneService.sync_dialogue_lines: stable DialogueLine identity.

The core Milestone 9 requirement: a dialogue line must retain stable
identity across reordering/insertion, while an edit to its own words
correctly supersedes it. See
docs/33_MILESTONE_9_REAL_VOICE_PRODUCTION_STATUS.md.
"""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.core.models import Character, DialogueLine, Episode
from app.core.models.voice_profile import SPEAKER_KEY_NARRATOR
from app.core.services.scene_service import SceneService


def _episode(session: Session) -> Episode:
    episode = Episode(
        slug=f"ep-{uuid.uuid4().hex[:8]}", number=int(uuid.uuid4().int % 100000),
        title_ar="ح", title_en="Ep", lesson="L",
    )
    session.add(episode)
    session.flush()
    return episode


def _melissa(session: Session) -> Character:
    character = Character(slug="melissa", name_ar="ميليسا", name_en="Melissa")
    session.add(character)
    session.flush()
    return character


def _current(session: Session, scene_id: uuid.UUID) -> list[DialogueLine]:
    return (
        session.query(DialogueLine)
        .filter_by(scene_id=scene_id, is_current=True)
        .order_by(DialogueLine.order_index)
        .all()
    )


def test_initial_sync_creates_lines_in_order(session: Session) -> None:
    ss = SceneService()
    episode = _episode(session)
    scene = ss.add_scene(session, episode.id, dialogue_ar="ميليسا: مرحباً\nبيلسان: أهلاً")

    lines = ss.sync_dialogue_lines(session, scene.id)

    assert [(line.speaker_raw, line.authored_text) for line in lines] == [
        ("ميليسا", "مرحباً"),
        ("بيلسان", "أهلاً"),
    ]
    assert [line.order_index for line in lines] == [0, 1]


def test_reorder_a_b_c_to_c_a_b_keeps_same_ids(session: Session) -> None:
    ss = SceneService()
    episode = _episode(session)
    scene = ss.add_scene(
        session, episode.id, dialogue_ar="ميليسا: A\nبيلسان: B\nتورتور: C"
    )
    a, b, c = ss.sync_dialogue_lines(session, scene.id)

    ss.update_scene(session, scene.id, dialogue_ar="تورتور: C\nميليسا: A\nبيلسان: B")
    reordered = _current(session, scene.id)

    assert {line.id for line in reordered} == {a.id, b.id, c.id}
    assert [line.authored_text for line in reordered] == ["C", "A", "B"]
    # order_index reflects the new position for each preserved id.
    by_id = {line.id: line for line in reordered}
    assert by_id[c.id].order_index == 0
    assert by_id[a.id].order_index == 1
    assert by_id[b.id].order_index == 2


def test_insert_x_keeps_a_b_c_ids_and_creates_only_x(session: Session) -> None:
    ss = SceneService()
    episode = _episode(session)
    scene = ss.add_scene(
        session, episode.id, dialogue_ar="ميليسا: A\nبيلسان: B\nتورتور: C"
    )
    a, b, c = ss.sync_dialogue_lines(session, scene.id)

    ss.update_scene(
        session, scene.id, dialogue_ar="ميليسا: A\nبيلسان: X\nبيلسان: B\nتورتور: C"
    )
    result = _current(session, scene.id)

    assert len(result) == 4
    ids = {line.id for line in result}
    assert {a.id, b.id, c.id}.issubset(ids)
    new_lines = [line for line in result if line.id not in {a.id, b.id, c.id}]
    assert len(new_lines) == 1
    assert new_lines[0].authored_text == "X"


def test_editing_line_text_supersedes_old_line_not_reattached(session: Session) -> None:
    ss = SceneService()
    episode = _episode(session)
    scene = ss.add_scene(session, episode.id, dialogue_ar="ميليسا: A\nبيلسان: B\nتورتور: C")
    a, b, c = ss.sync_dialogue_lines(session, scene.id)

    ss.update_scene(session, scene.id, dialogue_ar="ميليسا: A\nبيلسان: B, fixed\nتورتور: C")
    result = _current(session, scene.id)

    # A and C survive unchanged; the old B row is superseded, not reused.
    result_ids = {line.id for line in result}
    assert a.id in result_ids
    assert c.id in result_ids
    assert b.id not in result_ids

    session.refresh(b)
    assert b.is_current is False  # never deleted -- still queryable history
    assert b.authored_text == "B"  # old text preserved on the superseded row

    new_b = next(line for line in result if line.authored_text == "B, fixed")
    assert new_b.id != b.id


def test_duplicate_identical_lines_do_not_collapse(session: Session) -> None:
    ss = SceneService()
    episode = _episode(session)
    scene = ss.add_scene(
        session, episode.id, dialogue_ar="ميليسا: نعم\nبيلسان: حسناً\nميليسا: نعم"
    )

    lines = ss.sync_dialogue_lines(session, scene.id)

    melissa_lines = [line for line in lines if line.speaker_raw == "ميليسا"]
    assert len(melissa_lines) == 2
    assert melissa_lines[0].id != melissa_lines[1].id

    # Re-syncing the identical text again must pair rows 1:1, not
    # collapse both onto a single survivor.
    resynced = ss.sync_dialogue_lines(session, scene.id)
    resynced_melissa = [line for line in resynced if line.speaker_raw == "ميليسا"]
    assert {line.id for line in resynced_melissa} == {line.id for line in melissa_lines}


def test_duplicate_lines_partial_removal_supersedes_only_the_extra_one(
    session: Session,
) -> None:
    ss = SceneService()
    episode = _episode(session)
    scene = ss.add_scene(
        session, episode.id, dialogue_ar="ميليسا: نعم\nميليسا: نعم\nميليسا: نعم"
    )
    first, second, third = ss.sync_dialogue_lines(session, scene.id)

    # Drop one occurrence -- exactly one of the three rows must be
    # superseded, the other two must keep their ids (FIFO, deterministic).
    ss.update_scene(session, scene.id, dialogue_ar="ميليسا: نعم\nميليسا: نعم")
    result = _current(session, scene.id)

    assert len(result) == 2
    result_ids = {line.id for line in result}
    assert result_ids == {first.id, second.id}
    session.refresh(third)
    assert third.is_current is False


def test_removed_line_marked_not_current_never_deleted(session: Session) -> None:
    ss = SceneService()
    episode = _episode(session)
    scene = ss.add_scene(session, episode.id, dialogue_ar="ميليسا: A\nبيلسان: B")
    a, b = ss.sync_dialogue_lines(session, scene.id)

    ss.update_scene(session, scene.id, dialogue_ar="ميليسا: A")
    result = _current(session, scene.id)

    assert [line.id for line in result] == [a.id]
    session.refresh(b)
    assert b.is_current is False
    # Still a real, queryable row -- not deleted.
    assert session.get(DialogueLine, b.id) is not None


def test_resolve_speaker_matches_character_by_name_ar(session: Session) -> None:
    ss = SceneService()
    melissa = _melissa(session)

    character_id, speaker_key = ss.resolve_speaker(session, "ميليسا")

    assert character_id == melissa.id
    assert speaker_key is None


def test_resolve_speaker_matches_narrator_alias(session: Session) -> None:
    ss = SceneService()

    character_id, speaker_key = ss.resolve_speaker(session, "Narrator")

    assert character_id is None
    assert speaker_key == SPEAKER_KEY_NARRATOR


def test_resolve_speaker_unresolved_returns_none_none(session: Session) -> None:
    ss = SceneService()

    character_id, speaker_key = ss.resolve_speaker(session, "شخصية غير معروفة")

    assert character_id is None
    assert speaker_key is None


def test_sync_resolves_speakers_on_each_line(session: Session) -> None:
    ss = SceneService()
    episode = _episode(session)
    melissa = _melissa(session)
    scene = ss.add_scene(
        session, episode.id, dialogue_ar="ميليسا: مرحباً\nNarrator: كان يا ما كان"
    )

    lines = ss.sync_dialogue_lines(session, scene.id)

    melissa_line, narrator_line = lines
    assert melissa_line.character_id == melissa.id
    assert melissa_line.speaker_key is None
    assert narrator_line.character_id is None
    assert narrator_line.speaker_key == SPEAKER_KEY_NARRATOR


def test_update_scene_without_dialogue_ar_does_not_resync(session: Session) -> None:
    ss = SceneService()
    episode = _episode(session)
    scene = ss.add_scene(session, episode.id, dialogue_ar="ميليسا: A")
    a = ss.sync_dialogue_lines(session, scene.id)[0]

    ss.update_scene(session, scene.id, title="New Title")

    # Untouched -- still exactly the one synced line, same id.
    result = _current(session, scene.id)
    assert [line.id for line in result] == [a.id]


def test_empty_dialogue_ar_syncs_to_no_current_lines(session: Session) -> None:
    ss = SceneService()
    episode = _episode(session)
    scene = ss.add_scene(session, episode.id)

    result = ss.sync_dialogue_lines(session, scene.id)

    assert result == []
