"""Integration tests for ExportPackageService: preview vs. blocked final export, determinism, Arabic."""

from __future__ import annotations

import json

import pytest
from sqlalchemy.orm import Session

from app.config import AppConfig
from app.core.services.episode_service import EpisodeService
from app.core.services.exceptions import ExportBlockedError
from app.core.services.export_package_service import ExportPackageService


def _episode(session: Session):
    es = EpisodeService()
    return es.create_episode_from_template(
        session,
        slug="ep001_lost_little_turtle",
        number=1,
        title_ar="ميليسا وبيلسان والسلحفاة الصغيرة الضائعة",
        title_en="Melissa and Bilsan and the Lost Little Turtle",
        lesson="Helping others",
    )


def test_final_export_blocked_when_checklist_has_blocking_issues(
    session: Session, app_config: AppConfig
) -> None:
    episode = _episode(session)
    exporter = ExportPackageService(app_config)
    with pytest.raises(ExportBlockedError):
        exporter.build_export_package(session, episode.id, preview=False)


def test_preview_export_always_succeeds_and_is_marked_draft(
    session: Session, app_config: AppConfig
) -> None:
    episode = _episode(session)
    exporter = ExportPackageService(app_config)
    result = exporter.build_export_package(session, episode.id, preview=True)

    assert result.is_preview is True
    assert result.export_dir.is_dir()
    readme = (result.export_dir / "README.md").read_text(encoding="utf-8")
    assert "DRAFT PREVIEW" in readme

    checklist_md = (result.export_dir / "publishing_checklist.md").read_text(encoding="utf-8")
    assert "DRAFT PREVIEW EXPORT" in checklist_md


def test_preview_export_produces_expected_top_level_files(
    session: Session, app_config: AppConfig
) -> None:
    episode = _episode(session)
    exporter = ExportPackageService(app_config)
    result = exporter.build_export_package(session, episode.id, preview=True)

    expected_files = {
        "title_ar.txt",
        "title_en.txt",
        "description_ar.txt",
        "description_en.txt",
        "hashtags.txt",
        "credits.txt",
        "license_report.md",
        "publishing_checklist.md",
        "episode_metadata.json",
        "README.md",
    }
    actual_files = {p.name for p in result.export_dir.iterdir() if p.is_file()}
    assert expected_files <= actual_files
    assert (result.export_dir / "shorts").is_dir()
    for i in (1, 2, 3):
        short_dir = result.export_dir / "shorts" / f"short_{i:02d}"
        assert short_dir.is_dir()
        for name in (
            "working_title_ar.txt", "working_title_en.txt", "hook.txt", "caption.txt",
            "hashtags.txt", "source_scenes.txt", "metadata.json",
        ):
            assert (short_dir / name).exists()


def test_preview_export_uses_placeholders_when_no_final_video_or_thumbnail(
    session: Session, app_config: AppConfig
) -> None:
    episode = _episode(session)
    exporter = ExportPackageService(app_config)
    result = exporter.build_export_package(session, episode.id, preview=True)

    assert (result.export_dir / "final_video_PLACEHOLDER.txt").exists()
    assert (result.export_dir / "thumbnail_PLACEHOLDER.txt").exists()


def test_export_arabic_files_preserve_utf8_text(session: Session, app_config: AppConfig) -> None:
    episode = _episode(session)
    exporter = ExportPackageService(app_config)
    result = exporter.build_export_package(session, episode.id, preview=True)

    title_ar = (result.export_dir / "title_ar.txt").read_text(encoding="utf-8")
    assert title_ar == episode.title_ar

    metadata = json.loads((result.export_dir / "episode_metadata.json").read_text(encoding="utf-8"))
    assert metadata["title_ar"] == episode.title_ar
    # ensure_ascii=False means the raw file contains real Arabic characters,
    # not \uXXXX escapes.
    raw = (result.export_dir / "episode_metadata.json").read_text(encoding="utf-8")
    assert "\\u" not in raw
    assert "ميليسا" in raw


def test_export_never_mutates_managed_originals(session: Session, app_config: AppConfig) -> None:
    """Building an export twice must not change anything about the source episode/assets."""
    episode = _episode(session)
    exporter = ExportPackageService(app_config)
    exporter.build_export_package(session, episode.id, preview=True)
    title_before = episode.title_ar
    exporter.build_export_package(session, episode.id, preview=True)
    assert episode.title_ar == title_before


def test_export_structure_is_deterministic_across_runs(
    session: Session, app_config: AppConfig
) -> None:
    """Given unchanged episode state, re-running the export produces the same file set/content."""
    episode = _episode(session)
    exporter = ExportPackageService(app_config)

    result1 = exporter.build_export_package(session, episode.id, preview=True)
    files1 = {
        p.relative_to(result1.export_dir): p.read_bytes()
        for p in result1.export_dir.rglob("*")
        if p.is_file()
    }

    result2 = exporter.build_export_package(session, episode.id, preview=True)
    files2 = {
        p.relative_to(result2.export_dir): p.read_bytes()
        for p in result2.export_dir.rglob("*")
        if p.is_file()
    }

    assert result1.export_dir == result2.export_dir  # same deterministic path
    assert files1.keys() == files2.keys()
    assert files1 == files2
