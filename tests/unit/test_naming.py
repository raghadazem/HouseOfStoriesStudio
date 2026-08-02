"""Tests for app.core.naming — slugify, filename normalization, and collision safety."""

from __future__ import annotations

from app.core.naming import collision_safe_name, normalize_filename, slugify


def test_slugify_ascii_title() -> None:
    assert slugify("Melissa and Bilsan and the Lost Little Turtle") == (
        "melissa_and_bilsan_and_the_lost_little_turtle"
    )


def test_slugify_collapses_punctuation_and_whitespace() -> None:
    assert slugify("Melissa   Front (1) - v01!!") == "melissa_front_1_v01"


def test_slugify_arabic_text_falls_back_to_stable_hash() -> None:
    """Arabic text has no ASCII-safe content — must not crash or produce an empty slug."""
    result = slugify("ميليسا وبيلسان")
    assert result
    assert result.replace("_", "").isascii()
    # Same input -> same fallback, every time.
    assert result == slugify("ميليسا وبيلسان")


def test_slugify_different_arabic_text_gives_different_fallback() -> None:
    assert slugify("ميليسا") != slugify("بيلسان")


def test_normalize_filename_ascii() -> None:
    assert normalize_filename("Melissa Front (1).PNG") == "melissa_front_1.png"


def test_normalize_filename_preserves_extension_case_lowered() -> None:
    assert normalize_filename("episode_theme.MP3") == "episode_theme.mp3"


def test_normalize_filename_arabic_source_name_is_still_a_safe_ascii_filename() -> None:
    """The original Arabic name is never lost — it belongs in Asset.original_filename,
    not in the normalized on-disk filename this function produces."""
    result = normalize_filename("ميليسا.png")
    assert result.endswith(".png")
    stem = result[: -len(".png")]
    assert stem.isascii()
    assert stem  # not empty


def test_normalize_filename_already_normalized_is_unchanged() -> None:
    assert normalize_filename("melissa_front_v01.png") == "melissa_front_v01.png"


def test_collision_safe_name_returns_desired_when_free() -> None:
    assert collision_safe_name("a.png", set()) == "a.png"


def test_collision_safe_name_increments_on_collision() -> None:
    assert collision_safe_name("a.png", {"a.png"}) == "a_2.png"
    assert collision_safe_name("a.png", {"a.png", "a_2.png"}) == "a_3.png"


def test_collision_safe_name_preserves_extension() -> None:
    result = collision_safe_name("melissa_v01.png", {"melissa_v01.png"})
    assert result == "melissa_v01_2.png"
