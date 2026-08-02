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
import subprocess
import sys
import uuid
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from app.core.db.engine import create_db_engine, create_session_factory
from app.core.db.enums import AssetType
from app.core.db.seed import seed_demo_data
from app.core.models import Asset
from app.core.services.asset_import_service import AssetImportService, ImportRequest
from app.core.services.episode_service import EpisodeService
from app.core.services.exceptions import ServiceError
from app.core.services.export_package_service import ExportPackageService
from app.core.services.production_task_service import ProductionTaskService
from app.core.services.scene_service import SceneService
from app.core.services.short_service import ShortService
from app.core.services.unit_of_work import session_scope
from app.logging_setup import configure_logging, get_logger

logger = get_logger("cli")


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


def cmd_create_default_tasks(args: argparse.Namespace) -> int:
    with session_scope(_session_factory()) as session:
        episode = _resolve_episode(session, args.slug)
        tasks = ProductionTaskService().create_default_episode_tasks(session, episode.id)
        print(f"Created {len(tasks)} task(s) for {episode.slug}.")
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
        "create-default-tasks", help="Create the standard production checklist for an episode."
    )
    p.add_argument("slug", help="Episode slug or UUID.")
    p.set_defaults(func=cmd_create_default_tasks)

    return parser


def main(argv: list[str] | None = None) -> int:
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
