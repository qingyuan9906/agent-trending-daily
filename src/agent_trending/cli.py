from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import httpx

from agent_trending.config import load_config, validate_environment
from agent_trending.llm import DashScopeAnalyzer
from agent_trending.models import DailySnapshot
from agent_trending.pipeline import DailyPipeline
from agent_trending.publish import AtomicPublisher
from agent_trending.render import render_report
from agent_trending.render_html import render_html_report
from agent_trending.sources import GitHubClient, HttpRequester, TrendingSource


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agent-trending")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="run the current daily pipeline")
    run_parser.add_argument("--dry-run", action="store_true", help="validate without publishing")

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
        snapshot = DailySnapshot.model_validate_json(
            snapshot_path.read_text(encoding="utf-8"), strict=True
        )
        report = render_report(snapshot, config)
        html_report = render_html_report(snapshot, config)
        AtomicPublisher(project_root).publish_reports(
            run_date=snapshot.run_date,
            report=report,
            html_report=html_report,
        )
        print(f"rendered Markdown and HTML reports for {snapshot.run_date}")
        return 0

    validate_environment()
    with httpx.Client(timeout=20.0, follow_redirects=True) as http_client:
        requester = HttpRequester(http_client)
        analyzer = DashScopeAnalyzer(
            api_key=os.environ["DASHSCOPE_API_KEY"],
            workspace_id=os.environ["DASHSCOPE_WORKSPACE_ID"],
            config=config,
        )
        pipeline = DailyPipeline(
            root=project_root,
            config=config,
            trending_provider=TrendingSource(requester),
            repository_provider=GitHubClient(
                requester,
                token=os.getenv("GITHUB_TOKEN"),
                readme_char_limit=config.readme_char_limit,
            ),
            analyzer=analyzer,
        )
        result = pipeline.run(dry_run=args.dry_run)
    verb = "validated" if args.dry_run else "published"
    print(
        f"{verb} {result.snapshot.run_date}: "
        f"{result.snapshot.included_count}/{result.snapshot.candidate_count} included"
    )
    return 0


def entrypoint() -> None:
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        raise SystemExit(130) from None
    except Exception as error:
        print(f"error: {type(error).__name__}: {error}", file=sys.stderr)
        raise SystemExit(1) from None
