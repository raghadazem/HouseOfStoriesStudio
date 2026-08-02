"""ExportPackageService — manual YouTube export-package generator.

Builds a structured, deterministic export directory under
``production/episodes/<slug>/exports/<preview|final>/`` containing
everything the founder needs to manually upload an episode: text
metadata files, license/attribution summaries, a publishing checklist,
and copies (never the originals) of the final video/thumbnail and each
Short's assets. A **final** export refuses to run while blocking
checklist issues exist; a **preview** export always runs, clearly
marked as a draft, so the founder can see exactly what's still missing.

Nothing here uploads anything — see ``docs/16_EXPORT_PACKAGE.md``.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import AppConfig, get_config
from app.core.models import Asset, Episode, Short
from app.core.models.asset import ROLE_FINAL_THUMBNAIL, ROLE_FINAL_VIDEO
from app.core.services.exceptions import ExportBlockedError, NotFoundError
from app.core.services.license_service import LicenseService
from app.core.services.production_checklist_service import (
    ChecklistReport,
    ProductionChecklistService,
)
from app.core.services.short_service import ShortService
from app.core.services.storage_service import StorageService


@dataclass(frozen=True)
class ExportResult:
    """Result of :meth:`ExportPackageService.build_export_package`."""

    export_dir: Path
    is_preview: bool
    checklist: ChecklistReport


class ExportPackageService:
    """Generates a manual-upload export package for one episode."""

    def __init__(
        self,
        config: AppConfig | None = None,
        storage: StorageService | None = None,
        checklist_service: ProductionChecklistService | None = None,
        license_service: LicenseService | None = None,
        short_service: ShortService | None = None,
    ) -> None:
        self._config = config or get_config()
        self._storage = storage or StorageService(self._config)
        self._checklist = checklist_service or ProductionChecklistService()
        self._licenses = license_service or LicenseService()
        self._shorts = short_service or ShortService()

    def build_export_package(
        self, session: Session, episode_id: uuid.UUID, *, preview: bool
    ) -> ExportResult:
        """Build the export directory for ``episode_id``.

        Args:
            preview: If ``True``, always builds the package, clearly
                marked DRAFT, regardless of checklist state. If
                ``False`` (a *final* export), refuses to build unless
                the readiness checklist has no blocking issues.

        Raises:
            NotFoundError: The episode doesn't exist.
            ExportBlockedError: ``preview=False`` and blocking checklist
                issues exist.
        """
        episode = session.get(Episode, episode_id)
        if episode is None:
            raise NotFoundError(f"Episode {episode_id} not found.")

        report = self._checklist.evaluate(session, episode_id)
        if not preview and not report.is_ready:
            raise ExportBlockedError(
                f"Refusing final export for episode {episode_id}: blocking issues: "
                f"{[c.name for c in report.blocking_issues]}. Use preview=True for a draft export."
            )

        export_relative_dir = f"episodes/{episode.slug}/exports/{'preview' if preview else 'final'}"
        export_dir = self._storage.ensure_dir(export_relative_dir)

        self._write_text(export_dir / "title_ar.txt", episode.title_ar)
        self._write_text(export_dir / "title_en.txt", episode.title_en)
        self._write_text(export_dir / "description_ar.txt", episode.description_ar or "")
        self._write_text(export_dir / "description_en.txt", episode.description_en or "")
        self._write_text(export_dir / "hashtags.txt", "\n".join(episode.hashtags))
        self._write_text(export_dir / "credits.txt", episode.credits_text or "")

        self._write_final_media_or_placeholder(
            session, episode.id, None, ROLE_FINAL_VIDEO, export_dir, "final_video"
        )
        self._write_final_media_or_placeholder(
            session, episode.id, None, ROLE_FINAL_THUMBNAIL, export_dir, "thumbnail"
        )

        self._write_license_report(session, episode, export_dir)
        self._write_publishing_checklist(report, export_dir, preview)
        self._write_episode_metadata(episode, export_dir, preview, report)

        shorts_dir = export_dir / "shorts"
        shorts_dir.mkdir(parents=True, exist_ok=True)
        for short in self._shorts.list_episode_shorts(session, episode.id):
            self._write_short_export(session, short, shorts_dir)

        self._write_readme(export_dir, episode, preview)

        return ExportResult(export_dir=export_dir, is_preview=preview, checklist=report)

    # --- file writers -----------------------------------------------------

    @staticmethod
    def _write_text(path: Path, content: str) -> None:
        path.write_text(content, encoding="utf-8")

    def _write_final_media_or_placeholder(
        self,
        session: Session,
        episode_id: uuid.UUID | None,
        short_id: uuid.UUID | None,
        role: str,
        dest_dir: Path,
        base_name: str,
    ) -> None:
        asset = self._latest_role_asset(session, episode_id=episode_id, short_id=short_id, role=role)
        if asset is not None:
            suffix = Path(asset.relative_path).suffix
            self._storage.prepare_export_copy(asset.relative_path, dest_dir / f"{base_name}{suffix}")
        else:
            self._write_text(
                dest_dir / f"{base_name}_PLACEHOLDER.txt",
                f"DRAFT PLACEHOLDER: no {base_name.replace('_', ' ')} asset has been linked yet.",
            )

    def _write_license_report(self, session: Session, episode: Episode, export_dir: Path) -> None:
        lines = [f"# License Report — {episode.title_en}", ""]
        final_assets = self._final_assets(session, episode.id)
        if not final_assets:
            lines.append("No final assets are linked yet.")
        for asset in final_assets:
            readiness = self._licenses.calculate_asset_commercial_readiness(session, asset.id)
            lines.append(f"## {asset.role}")
            lines.append(f"- Managed file: `{asset.relative_path}`")
            lines.append(f"- Source tool: {asset.source_tool or 'unknown'}")
            lines.append(
                f"- Commercial-use ready: {'yes' if readiness.is_ready else 'NO'} — {readiness.reason}"
            )
            attribution = self._licenses.generate_attribution_text(session, asset.id)
            if attribution:
                lines.append(f"- Attribution required: {attribution}")
            lines.append("")
        self._write_text(export_dir / "license_report.md", "\n".join(lines))

    def _write_publishing_checklist(
        self, report: ChecklistReport, export_dir: Path, preview: bool
    ) -> None:
        lines = ["# Publishing Checklist", ""]
        if preview:
            lines += ["**DRAFT PREVIEW EXPORT — not all checks may pass.**", ""]
        lines.append(
            f"Readiness: {report.readiness_percent}% "
            f"({'READY' if report.is_ready else 'NOT READY'})"
        )
        lines += ["", "## Passed"]
        lines += [f"- [x] {c.name}: {c.message}" for c in report.passed_checks] or ["(none)"]
        lines += ["", "## Failed"]
        lines += [
            f"- [ ] ({'BLOCKING' if c.blocking else 'warning'}) {c.name}: {c.message}"
            for c in report.failed_checks
        ] or ["(none)"]
        self._write_text(export_dir / "publishing_checklist.md", "\n".join(lines))

    def _write_episode_metadata(
        self, episode: Episode, export_dir: Path, preview: bool, report: ChecklistReport
    ) -> None:
        data = {
            "episode_number": episode.number,
            "slug": episode.slug,
            "title_ar": episode.title_ar,
            "title_en": episode.title_en,
            "lesson": episode.lesson,
            "dialogue_language": episode.dialogue_language,
            "runtime_target_minutes": [
                episode.runtime_target_minutes_min,
                episode.runtime_target_minutes_max,
            ],
            "includes_song": episode.includes_song,
            "pipeline_stage": episode.pipeline_stage.value,
            "hashtags": episode.hashtags,
            "is_preview_export": preview,
            "readiness_percent": report.readiness_percent,
            "is_ready": report.is_ready,
        }
        # ensure_ascii=False: Arabic text is written as real UTF-8
        # characters, not \uXXXX escapes.
        self._write_text(
            export_dir / "episode_metadata.json", json.dumps(data, ensure_ascii=False, indent=2)
        )

    def _write_short_export(self, session: Session, short: Short, shorts_dir: Path) -> None:
        short_dir = shorts_dir / f"short_{short.short_index:02d}"
        short_dir.mkdir(parents=True, exist_ok=True)

        self._write_text(short_dir / "working_title_ar.txt", short.title_ar or "")
        self._write_text(short_dir / "working_title_en.txt", short.working_title_en or "")
        self._write_text(short_dir / "hook.txt", short.hook_ar or "")
        self._write_text(short_dir / "caption.txt", short.caption_ar or "")
        self._write_text(short_dir / "hashtags.txt", "\n".join(short.hashtags))

        source_scenes_text = "\n".join(
            f"scene_{scene.order_index:02d}: {scene.location or ''}" for scene in short.source_scenes
        )
        self._write_text(short_dir / "source_scenes.txt", source_scenes_text)

        video_asset = session.get(Asset, short.export_asset_id) if short.export_asset_id else None
        if video_asset is not None:
            suffix = Path(video_asset.relative_path).suffix
            self._storage.prepare_export_copy(video_asset.relative_path, short_dir / f"final_video{suffix}")
        else:
            self._write_final_media_or_placeholder(
                session, None, short.id, ROLE_FINAL_VIDEO, short_dir, "final_video"
            )
        self._write_final_media_or_placeholder(
            session, None, short.id, ROLE_FINAL_THUMBNAIL, short_dir, "thumbnail"
        )

        metadata = {
            "short_index": short.short_index,
            "status": short.status.value,
            "source_timestamp_range": short.source_timestamp_range,
            "hashtags": short.hashtags,
        }
        self._write_text(short_dir / "metadata.json", json.dumps(metadata, ensure_ascii=False, indent=2))

    def _write_readme(self, export_dir: Path, episode: Episode, preview: bool) -> None:
        lines = [
            f"# Export Package — {episode.title_en} / {episode.title_ar}",
            "",
            "DRAFT PREVIEW — some files may be placeholders and checklist items may be failing."
            if preview
            else "FINAL — all blocking checklist items passed at export time.",
            "",
            (
                "This folder contains copies only, generated by ExportPackageService. "
                "Nothing here is the source of truth; the managed assets under "
                "production/ are — do not edit files in this folder and expect the "
                "change to propagate anywhere."
            ),
        ]
        self._write_text(export_dir / "README.md", "\n".join(lines))

    # --- helpers -----------------------------------------------------

    @staticmethod
    def _latest_role_asset(
        session: Session,
        *,
        episode_id: uuid.UUID | None,
        short_id: uuid.UUID | None,
        role: str,
    ) -> Asset | None:
        query = session.query(Asset).filter(Asset.role == role)
        if episode_id is not None:
            query = query.filter(Asset.episode_id == episode_id)
        if short_id is not None:
            query = query.filter(Asset.short_id == short_id)
        return query.order_by(Asset.created_at.desc()).first()

    @staticmethod
    def _final_assets(session: Session, episode_id: uuid.UUID) -> list[Asset]:
        return (
            session.query(Asset)
            .filter(Asset.episode_id == episode_id, Asset.role.isnot(None), Asset.role.like("final_%"))
            .order_by(Asset.role)
            .all()
        )
