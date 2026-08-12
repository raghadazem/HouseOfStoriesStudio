"""Tests for text_normalization.normalize_arabic_line: pure function, no side effects."""

from __future__ import annotations

from app.core.ai.text_normalization import normalize_arabic_line


def test_collapses_whitespace_and_strips() -> None:
    assert normalize_arabic_line("  مرحباً   يا   أصدقاء  ") == "مرحباً يا أصدقاء"


def test_applies_pronunciation_override() -> None:
    result = normalize_arabic_line(
        "تورتور صديقي", pronunciation_overrides={"تورتور": "طُرطُر"}
    )
    assert result == "طُرطُر صديقي"


def test_no_overrides_leaves_text_otherwise_unchanged() -> None:
    assert normalize_arabic_line("نص عادي بدون أسماء") == "نص عادي بدون أسماء"


def test_idempotent_on_already_clean_text() -> None:
    text = "ميليسا وبيلسان يلعبان"
    once = normalize_arabic_line(text)
    twice = normalize_arabic_line(once)
    assert once == twice == text


def test_longer_term_applied_before_shorter_contained_term() -> None:
    overrides = {"تور": "WRONG", "تورتور": "طُرطُر"}
    result = normalize_arabic_line("تورتور", pronunciation_overrides=overrides)
    assert result == "طُرطُر"


def test_authored_text_object_never_mutated() -> None:
    original = "نص أصلي"
    normalize_arabic_line(original, pronunciation_overrides={"نص": "X"})
    assert original == "نص أصلي"  # the input string itself is untouched
