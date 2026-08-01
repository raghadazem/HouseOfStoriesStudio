"""Verifies the Milestone 1 production templates exist and are valid Jinja2.

Rendering these templates is implemented in Milestone 3
(episode_service / character_service); this only checks the template
files themselves are present and syntactically parseable so a typo
isn't discovered only once that service code is written.
"""

from __future__ import annotations

from pathlib import Path

import jinja2
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TEMPLATES_DIR = REPO_ROOT / "app" / "core" / "templates"

EPISODE_TEMPLATES = [
    "00_meta.yaml.j2",
    "01_script.md.j2",
    "02_storyboard.md.j2",
    "03_image_prompts.md.j2",
    "04_video_prompts.md.j2",
    "05_voice.md.j2",
    "06_song.md.j2",
    "07_seo.md.j2",
    "08_shorts.md.j2",
]


@pytest.mark.parametrize("filename", EPISODE_TEMPLATES)
def test_episode_template_exists_and_parses(filename: str) -> None:
    path = TEMPLATES_DIR / "episode" / filename
    assert path.is_file(), f"Missing episode template: {filename}"

    env = jinja2.Environment()
    env.parse(path.read_text(encoding="utf-8"))


def test_character_template_exists_and_parses() -> None:
    path = TEMPLATES_DIR / "character" / "character_meta.yaml.j2"
    assert path.is_file(), "Missing character_meta.yaml.j2 template"

    env = jinja2.Environment()
    env.parse(path.read_text(encoding="utf-8"))


def test_character_template_covers_approved_lock_fields() -> None:
    """Guards against silently dropping an approved Character Lock field.

    The founder's Milestone-approval message enumerates the required
    fields for every main character; this test keeps the template
    honest against that list without needing the rendering service to
    exist yet.
    """
    required_field_markers = [
        "visual_specification",
        "master_prompt",
        "negative_prompt",
        "approved_reference_assets",
        "reference_version",
        "outfit_version",
        "color_palette",
        "allowed_accessories",
        "relative_height",
        "approval",
        "review_notes",
    ]

    content = (TEMPLATES_DIR / "character" / "character_meta.yaml.j2").read_text(
        encoding="utf-8"
    )
    missing = [field for field in required_field_markers if field not in content]
    assert not missing, f"character_meta.yaml.j2 is missing fields: {missing}"
