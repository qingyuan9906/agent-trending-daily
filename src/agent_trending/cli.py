from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

from agent_trending.articles import OfficialBlogSource
from agent_trending.config import load_config, validate_environment
from agent_trending.llm import DashScopeAnalyzer
from agent_trending.models import DailySnapshot, WeeklySnapshot
from agent_trending.observations import ObservationStore
from agent_trending.publish import AtomicPublisher
from agent_trending.render import render_report
from agent_trending.render_html import render_html_report
from agent_trending.render_weekly import render_weekly_html, render_weekly_report
from agent_trending.sources import GitHubClient, HttpRequester, TrendingSource
from agent_trending.weekly import WeeklyPipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agent-trending")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="collect daily and publish on Mondays")
    run_parser.add_argument("--dry-run", action="store_true", help="validate without publishing")

    collect_parser = subparsers.add_parser("collect", help="collect today's daily observation")
    collect_parser.add_argument(
        "--dry-run", action="store_true", help="validate without publishing"
    )

    weekly_parser = subparsers.add_parser(
        "publish-weekly", help="publish the previous complete natural week"
    )
    weekly_parser.add_argument("--dry-run", action="store_true", help="validate without publishing")

    subparsers.add_parser("validate-config", help="validate config and required environment")

    render_parser = subparsers.add_parser("render", help="render a validated JSON snapshot")
    render_parser.add_argument("snapshot", type=Path)
    return parser


def main(argv: list[str] | None = None, *, root: Path | None = None) -> int:
    args = build_parser().parse_args(argv)
    project_root = (root or Path.cwd()).resolve()
    config = load_config(project_root / "config" / "relevance.yaml")

    if args.command == "validate-config":
        validate_environment()
        print("configuration is valid")
        return 0

    if args.command == "render":
        snapshot_path = args.snapshot
        if not snapshot_path.is_absolute():
            snapshot_path = project_root / snapshot_path
        payload = snapshot_path.read_text(encoding="utf-8")
        raw = json.loads(payload)
        if raw.get("schema_version") == 3:
            snapshot = WeeklySnapshot.model_validate_json(payload, strict=True)
            report = render_weekly_report(snapshot, config)
            html_report = render_weekly_html(snapshot, config)
            artifact_date = snapshot.published_date
        else:
            snapshot = DailySnapshot.model_validate_json(payload, strict=True)
            report = render_report(snapshot, config)
            html_report = render_html_report(snapshot, config)
            artifact_date = snapshot.run_date
        AtomicPublisher(project_root).publish_reports(
            run_date=artifact_date,
            report=report,
            html_report=html_report,
            update_latest=_is_latest_snapshot(project_root, artifact_date),
        )
        print(f"rendered Markdown and HTML reports for {artifact_date}")
        return 0

    now = datetime.now(ZoneInfo(config.timezone))
    with httpx.Client(timeout=20.0, follow_redirects=True) as http_client:
        requester = HttpRequester(http_client)
        if args.command in {"run", "collect"}:
            observation = ObservationStore(project_root).collect(
                TrendingSource(requester).fetch(), now=now, dry_run=args.dry_run
            )
            verb = "validated" if args.dry_run else "collected"
            print(f"{verb} daily observation {observation.observed_date}")
            if args.command == "collect" or now.weekday() != 0:
                return 0

        validate_environment()
        analyzer = DashScopeAnalyzer(
            api_key=os.environ["DASHSCOPE_API_KEY"],
            workspace_id=os.environ["DASHSCOPE_WORKSPACE_ID"],
            config=config,
        )
        result = WeeklyPipeline(
            root=project_root,
            config=config,
            weekly_provider=TrendingSource(requester, period="weekly"),
            repository_provider=GitHubClient(
                requester,
                token=os.getenv("GITHUB_TOKEN"),
                readme_char_limit=config.readme_char_limit,
            ),
            article_provider=OfficialBlogSource(requester),
            analyzer=analyzer,
            clock=lambda: now,
        ).run(dry_run=args.dry_run)
    verb = "validated" if args.dry_run else "published"
    print(
        f"{verb} weekly report {result.snapshot.published_date}: "
        f"{result.snapshot.selected_count}/{result.snapshot.candidate_count} selected"
    )
    return 0


def _is_latest_snapshot(project_root: Path, run_date: str) -> bool:
    snapshot_dates = [path.stem for path in (project_root / "data").glob("????-??-??.json")]
    return not snapshot_dates or run_date >= max(snapshot_dates)


def entrypoint() -> None:
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        raise SystemExit(130) from None
    except Exception as error:
        print(f"error: {type(error).__name__}: {error}", file=sys.stderr)
        raise SystemExit(1) from None
