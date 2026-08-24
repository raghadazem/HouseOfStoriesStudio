"""House of Stories Studio developer CLI.

For development and operational testing of the service layer before
the GUI exists — not a full user-facing CLI. Every command is a thin
wrapper around the same ``app.core.services`` classes the GUI will
eventually call, so exercising a command here exercises real
production code paths.

Usage (from the repository root, inside the venv)::

    python -m app.cli.main --help
    python -m app.cli.main init-db
    python -m app.cli.main seed-demo
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import uuid
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from app.core.ai.orchestrator import AIOrchestrator
from app.core.ai.providers import PROVIDER_REGISTRY
from app.core.db.engine import create_db_engine, create_session_factory
from app.core.db.enums import AssetType
from app.core.db.episode_001_production import populate_episode_001_production_content
from app.core.db.seed import seed_demo_data
from app.core.models import Asset
from app.core.services.approval_service import ApprovalService
from app.core.services.asset_import_service import AssetImportService, ImportRequest
from app.core.services.episode_audio_mix_service import EpisodeAudioMixService
from app.core.services.episode_audio_preview_service import EpisodeAudioPreviewService
from app.core.services.episode_service import EpisodeService
from app.core.services.exceptions import ServiceError
from app.core.services.export_package_service import ExportPackageService
from app.core.services.production_task_service import ProductionTaskService
from app.core.services.scene_service import SceneService
from app.core.services.short_service import ShortService
from app.core.services.unit_of_work import session_scope
from app.logging_setup import configure_logging, get_logger

logger = get_logger("cli")


def _ensure_utf8_stdio() -> None:
    """Force stdout/stderr to UTF-8, once, before any command prints.

    Windows' default console/pipe encoding is a legacy codepage (e.g.
    cp1252) unless the user has set ``PYTHONUTF8``/``PYTHONIOENCODING``
    or run ``chcp 65001`` — none of which a founder running ``hos-cli``
    should ever need to know about for a CLI whose whole purpose is
    managing Arabic-language content (episode titles, etc. — see
    ``episode.title_ar`` in ``cmd_show_episode``). Without this, printing
    Arabic text raises ``UnicodeEncodeError`` and the command crashes.

    ``reconfigure()`` is each stream's own public API (Python 3.7+), not
    a replacement of ``sys.stdout``/``sys.stderr`` — so this is a one-time
    setup call, not global monkeypatching. Guarded on both ends: skipped
    entirely if a stream doesn't expose ``reconfigure`` at all (e.g. one
    substituted by a test harness), and never lets a failed reconfigure
    crash the CLI on any platform.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8")
        except (OSError, ValueError):
            pass


def _session_factory() -> sessionmaker[Session]:
    engine = create_db_engine()
    return create_session_factory(engine)


def _looks_like_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
    except ValueError:
        return False
    return True


def _resolve_episode(session: Session, slug_or_id: str):
    service = EpisodeService()
    if _looks_like_uuid(slug_or_id):
        return service.get_episode(session, uuid.UUID(slug_or_id))
    return service.get_episode_by_slug(session, slug_or_id)


# --- commands --------------------------------------------------------


def cmd_init_db(_args: argparse.Namespace) -> int:
    """Run ``alembic upgrade head`` — the schema lives in migrations, not here."""
    result = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], check=False)
    return result.returncode


def cmd_seed_demo(_args: argparse.Namespace) -> int:
    with _session_factory()() as session:
        result = seed_demo_data(session)
    episode = result["episode_001"]
    print(f"Seed data ready: melissa, bilsan, {episode.slug} (3 shorts).")
    return 0


def cmd_populate_episode_001(_args: argparse.Namespace) -> int:
    """Fill Episode 001 with its real Milestone 6 production content.

    Idempotent and safe to re-run: never overwrites a field a human has
    already edited (through the GUI or a previous run of this command).
    """
    with _session_factory()() as session:
        episode = populate_episode_001_production_content(session)
    print(
        f"Episode 001 production content ready: {len(episode.scenes)} scene(s), "
        f"{len(episode.shorts)} short(s), song={'yes' if episode.includes_song else 'no'}."
    )
    return 0


def cmd_create_episode(args: argparse.Namespace) -> int:
    with session_scope(_session_factory()) as session:
        episode = EpisodeService().create_episode_from_template(
            session,
            slug=args.slug,
            number=args.number,
            title_ar=args.title_ar,
            title_en=args.title_en,
            lesson=args.lesson,
        )
        print(f"Created episode #{episode.number}: {episode.slug} ({episode.id})")
    return 0


def cmd_list_episodes(_args: argparse.Namespace) -> int:
    with _session_factory()() as session:
        for episode in EpisodeService().list_episodes(session):
            print(f"#{episode.number:03d}  {episode.slug:32s}  [{episode.pipeline_stage.value:16s}]  {episode.title_en}")
    return 0


def cmd_show_episode(args: argparse.Namespace) -> int:
    with _session_factory()() as session:
        episode = _resolve_episode(session, args.slug)
        es = EpisodeService()
        progress = es.calculate_episode_progress(session, episode.id)
        scenes = SceneService().list_episode_scenes(session, episode.id)
        shorts = ShortService().list_episode_shorts(session, episode.id)

        print(f"Episode #{episode.number}: {episode.title_en} / {episode.title_ar}")
        print(f"  id: {episode.id}")
        print(f"  slug: {episode.slug}")
        print(f"  pipeline stage: {episode.pipeline_stage.value}")
        print(f"  lesson: {episode.lesson}")
        print(
            f"  task progress: {progress.completed_tasks}/{progress.total_tasks} "
            f"({progress.percent}%)"
        )
        print(f"  scenes: {len(scenes)}")
        print(f"  shorts: {len(shorts)}")
        print(f"  featured characters: {[c.slug for c in episode.characters_featured]}")
    return 0


def cmd_import_asset(args: argparse.Namespace) -> int:
    with _session_factory()() as session:
        request = ImportRequest(
            source_path=Path(args.source),
            asset_type=AssetType(args.asset_type),
            episode_id=uuid.UUID(args.episode_id) if args.episode_id else None,
            source_tool=args.source_tool,
            role=args.role,
            license_status=args.license_status,
            commercial_use_status=args.commercial_use_status,
        )
        asset = AssetImportService().import_asset(session, request)
        print(f"Imported asset {asset.id} -> {asset.relative_path}")
    return 0


def cmd_list_assets(args: argparse.Namespace) -> int:
    with _session_factory()() as session:
        query = session.query(Asset)
        if args.episode_id:
            query = query.filter_by(episode_id=uuid.UUID(args.episode_id))
        for asset in query.order_by(Asset.created_at).all():
            role = asset.role or "-"
            print(
                f"{asset.id}  {asset.asset_type.value:10s} {asset.approval_status.value:10s} "
                f"role={role:16s} {asset.relative_path}"
            )
    return 0


def cmd_check_episode(args: argparse.Namespace) -> int:
    with _session_factory()() as session:
        episode = _resolve_episode(session, args.slug)
        report = EpisodeService().validate_episode_readiness(session, episode.id)
        status = "READY" if report.is_ready else "NOT READY"
        print(f"Readiness: {report.readiness_percent}% ({status})")
        for check in report.checks:
            marker = "PASS " if check.passed else ("BLOCK" if check.blocking else "WARN ")
            print(f"  [{marker}] {check.name}: {check.message}")
    return 0


def cmd_export_episode(args: argparse.Namespace) -> int:
    with session_scope(_session_factory()) as session:
        episode = _resolve_episode(session, args.slug)
        result = ExportPackageService().build_export_package(session, episode.id, preview=args.preview)
        print(f"Export written to: {result.export_dir}")
        print(f"Readiness at export time: {result.checklist.readiness_percent}%")
    return 0


def cmd_render_audio_preview(args: argparse.Namespace) -> int:
    with _session_factory()() as session:
        episode = _resolve_episode(session, args.slug)
        result = EpisodeAudioPreviewService().render_preview(
            session, episode.id, Path(args.output)
        )
        print(f"Preview rendered: {result.output_path}")
        print(
            f"clips={result.clip_count}  same_scene_gaps={result.same_scene_gap_count}  "
            f"scene_boundary_gaps={result.scene_boundary_gap_count}"
        )
        print(
            f"codec={result.codec_name}  sample_rate={result.sample_rate}  "
            f"channels={result.channels}  bit_rate={result.bit_rate}"
        )
        print(
            f"expected={result.expected_duration_seconds:.3f}s  "
            f"measured={result.measured_duration_seconds:.3f}s  "
            f"delta={result.duration_delta_seconds:+.3f}s"
        )
    return 0


def cmd_render_audio_mix_preview(args: argparse.Namespace) -> int:
    with _session_factory()() as session:
        episode = _resolve_episode(session, args.slug)
        result = EpisodeAudioMixService().render_mix_preview(
            session, episode.id, Path(args.output)
        )
        print(f"Mix preview rendered: {result.output_path}")
        print(
            f"spoken_clips={result.spoken_clip_count}  same_scene_gaps={result.same_scene_gap_count}  "
            f"scene_boundary_gaps={result.scene_boundary_gap_count}  "
            f"song_transition_gaps={result.song_transition_gap_count}"
        )
        print(
            f"codec={result.codec_name}  sample_rate={result.sample_rate}  "
            f"channels={result.channels}  bit_rate={result.bit_rate}"
        )
        print(
            f"spoken_total={result.total_spoken_duration_seconds:.3f}s  "
            f"song={result.song_duration_seconds:.3f}s  gaps={result.total_gap_seconds:.3f}s"
        )
        print(
            f"expected={result.expected_duration_seconds:.3f}s  "
            f"measured={result.measured_duration_seconds:.3f}s  "
            f"delta={result.duration_delta_seconds:+.3f}s"
        )
    return 0


def cmd_create_default_tasks(args: argparse.Namespace) -> int:
    with session_scope(_session_factory()) as session:
        episode = _resolve_episode(session, args.slug)
        tasks = ProductionTaskService().create_default_episode_tasks(session, episode.id)
        print(f"Created {len(tasks)} task(s) for {episode.slug}.")
    return 0


def cmd_list_ai_workflows(_args: argparse.Namespace) -> int:
    for name in AIOrchestrator().list_workflows():
        print(name)
    return 0


def cmd_list_ai_providers(args: argparse.Namespace) -> int:
    orchestrator = AIOrchestrator()
    if args.modality:
        for name in orchestrator.list_available_providers(args.modality):
            print(name)
        return 0
    for name, provider_cls in PROVIDER_REGISTRY.items():
        provider = provider_cls()
        modalities = ",".join(sorted(provider.supported_modalities))
        print(f"{name}  configured={provider.is_configured()}  modalities={modalities}")
    return 0


def cmd_run_ai_workflow(args: argparse.Namespace) -> int:
    # AIOrchestrator.run_workflow ultimately calls AssetImportService.import_asset,
    # which owns its own transaction (see docs/14) — a plain session here,
    # not session_scope, matching cmd_import_asset above.
    with _session_factory()() as session:
        variables = json.loads(args.variables) if args.variables else {}
        parameters = json.loads(args.parameters) if args.parameters else {}
        result = AIOrchestrator().run_workflow(
            session,
            args.workflow,
            provider_name=args.provider,
            prompt_template_id=uuid.UUID(args.prompt_template_id),
            variables=variables,
            parameters=parameters,
            episode_id=uuid.UUID(args.episode_id) if args.episode_id else None,
            scene_id=uuid.UUID(args.scene_id) if args.scene_id else None,
            short_id=uuid.UUID(args.short_id) if args.short_id else None,
            character_id=uuid.UUID(args.character_id) if args.character_id else None,
            character_version_id=(
                uuid.UUID(args.character_version_id) if args.character_version_id else None
            ),
            notes=args.notes,
        )
        print(f"Generated asset {result.asset.id} -> {result.asset.relative_path}")
        print(f"Provider: {result.generation_result.provider_name}  (status: draft, awaiting review)")
    return 0


def cmd_list_review_queue(args: argparse.Namespace) -> int:
    with _session_factory()() as session:
        assets = ApprovalService().list_pending_review_assets(
            session,
            episode_id=uuid.UUID(args.episode_id) if args.episode_id else None,
            source_tool=args.source_tool,
        )
        for asset in assets:
            source = asset.source_tool or "-"
            print(f"{asset.id}  {asset.asset_type.value:10s} source_tool={source:16s} {asset.relative_path}")
    return 0


# --- argument parser --------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hos-cli",
        description=(
            "House of Stories Studio developer CLI. For development and "
            "operational testing of the service layer only — not a "
            "full user-facing tool."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    p = subparsers.add_parser("init-db", help="Run Alembic migrations (alembic upgrade head).")
    p.set_defaults(func=cmd_init_db)

    p = subparsers.add_parser("seed-demo", help="Seed Melissa, Bilsan, Episode 001, and its 3 Shorts.")
    p.set_defaults(func=cmd_seed_demo)

    p = subparsers.add_parser(
        "populate-episode-001",
        help="Fill Episode 001 with its real Milestone 6 production content (idempotent).",
    )
    p.set_defaults(func=cmd_populate_episode_001)

    p = subparsers.add_parser("create-episode", help="Create a new episode from the standard template.")
    p.add_argument("--slug", required=True)
    p.add_argument("--number", required=True, type=int)
    p.add_argument("--title-ar", required=True)
    p.add_argument("--title-en", required=True)
    p.add_argument("--lesson", required=True)
    p.set_defaults(func=cmd_create_episode)

    p = subparsers.add_parser("list-episodes", help="List all episodes.")
    p.set_defaults(func=cmd_list_episodes)

    p = subparsers.add_parser("show-episode", help="Show details for one episode (slug or id).")
    p.add_argument("slug", help="Episode slug or UUID.")
    p.set_defaults(func=cmd_show_episode)

    p = subparsers.add_parser("import-asset", help="Import a file into managed storage.")
    p.add_argument("--source", required=True, help="Path to the source file.")
    p.add_argument("--asset-type", required=True, choices=[t.value for t in AssetType])
    p.add_argument("--episode-id", help="Episode UUID to associate this asset with.")
    p.add_argument("--source-tool", help="Name of the external tool that produced this file.")
    p.add_argument("--role", help='e.g. "final_video", "final_thumbnail".')
    p.add_argument("--license-status")
    p.add_argument("--commercial-use-status")
    p.set_defaults(func=cmd_import_asset)

    p = subparsers.add_parser("list-assets", help="List imported assets.")
    p.add_argument("--episode-id", help="Filter to one episode's assets.")
    p.set_defaults(func=cmd_list_assets)

    p = subparsers.add_parser("check-episode", help="Run the readiness checklist for an episode.")
    p.add_argument("slug", help="Episode slug or UUID.")
    p.set_defaults(func=cmd_check_episode)

    p = subparsers.add_parser("export-episode", help="Build an export package for an episode.")
    p.add_argument("slug", help="Episode slug or UUID.")
    p.add_argument(
        "--preview", action="store_true",
        help="Build a draft preview export even if the readiness checklist has blocking issues.",
    )
    p.set_defaults(func=cmd_export_episode)

    p = subparsers.add_parser(
        "render-audio-preview",
        help="Render a dialogue-only audio preview MP3 for an episode's approved final voice takes.",
    )
    p.add_argument("slug", help="Episode slug or UUID.")
    p.add_argument("--output", required=True, help="Output MP3 path.")
    p.set_defaults(func=cmd_render_audio_preview)

    p = subparsers.add_parser(
        "render-audio-mix-preview",
        help="Render the dialogue+song mix preview MP3 for an episode (requires is_mix_ready).",
    )
    p.add_argument("slug", help="Episode slug or UUID.")
    p.add_argument("--output", required=True, help="Output MP3 path.")
    p.set_defaults(func=cmd_render_audio_mix_preview)

    p = subparsers.add_parser(
        "create-default-tasks", help="Create the standard production checklist for an episode."
    )
    p.add_argument("slug", help="Episode slug or UUID.")
    p.set_defaults(func=cmd_create_default_tasks)

    p = subparsers.add_parser("list-ai-workflows", help="List available AI workflow names.")
    p.set_defaults(func=cmd_list_ai_workflows)

    p = subparsers.add_parser(
        "list-ai-providers", help="List registered AI providers and their configured status."
    )
    p.add_argument(
        "--modality", choices=["text", "image", "video", "voice", "song"],
        help="Only show providers available for this modality.",
    )
    p.set_defaults(func=cmd_list_ai_providers)

    p = subparsers.add_parser(
        "run-ai-workflow",
        help="Run an AI generation workflow (mock provider only in Milestone 3.5).",
    )
    p.add_argument("workflow", help='e.g. "character_reference_image", "scene_image".')
    p.add_argument("--provider", default="mock_provider")
    p.add_argument("--prompt-template-id", required=True)
    p.add_argument("--variables", help="JSON object of template variables.")
    p.add_argument("--parameters", help="JSON object of provider parameters.")
    p.add_argument("--episode-id")
    p.add_argument("--scene-id")
    p.add_argument("--short-id")
    p.add_argument("--character-id")
    p.add_argument("--character-version-id")
    p.add_argument("--notes")
    p.set_defaults(func=cmd_run_ai_workflow)

    p = subparsers.add_parser(
        "list-review-queue", help="List draft assets awaiting review (manual or AI-generated)."
    )
    p.add_argument("--episode-id", help="Filter to one episode's assets.")
    p.add_argument("--source-tool", help='Filter to one source, e.g. "mock_provider".')
    p.set_defaults(func=cmd_list_review_queue)

    return parser


def main(argv: list[str] | None = None) -> int:
    _ensure_utf8_stdio()
    configure_logging()
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except ServiceError as err:
        print(f"Error: {err}", file=sys.stderr)
        logger.error("CLI command failed: %s", err)
        return 1


if __name__ == "__main__":
    sys.exit(main())
