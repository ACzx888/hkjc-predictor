"""CLI entry point for HKJC fundamental tip sheets (local + overseas)."""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from hkjc_predictor.fetch import FetchError, fetch_meeting, try_fetch_next_meeting
from hkjc_predictor.parse import load_meeting_json
from hkjc_predictor.report import export_tip_sheet, render_txt, summary_lines
from hkjc_predictor.score import load_weights, score_meeting

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = PACKAGE_ROOT / "config" / "weights.yaml"
DEFAULT_OVERSEAS_CONFIG = PACKAGE_ROOT / "config" / "weights_overseas.yaml"
DEFAULT_SAMPLE = PACKAGE_ROOT / "data" / "sample_meeting.json"
DEFAULT_OVERSEAS_SAMPLE = PACKAGE_ROOT / "data" / "sample_overseas_meeting.json"
DEFAULT_OUTPUT = PACKAGE_ROOT / "output"


def _resolve_path(p: str | Path) -> Path:
    path = Path(p)
    if path.is_file() or path.is_dir():
        return path.resolve()
    alt = PACKAGE_ROOT / p
    if alt.exists():
        return alt.resolve()
    return path.resolve()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="hkjc_predictor",
        description=(
            "HKJC horse racing tip sheets from fundamental condition analysis. "
            "No odds or pools are used. Local and overseas use separate paths. "
            "Live schedule via public GraphQL horseQuery."
        ),
    )
    p.add_argument(
        "command",
        nargs="?",
        choices=["pages"],
        help="Optional: 'pages' regenerates output/pages HTML (same as --build-pages)",
    )
    p.add_argument(
        "--live",
        action="store_true",
        help=(
            "Fetch active meeting(s) via HKJC GraphQL, score, write tip sheets, "
            "and rebuild pages (local and/or overseas)"
        ),
    )
    p.add_argument(
        "--demo",
        action="store_true",
        help="Score offline local sample meeting (data/sample_meeting.json)",
    )
    p.add_argument(
        "--demo-overseas",
        action="store_true",
        help="Score offline overseas/simulcast sample (data/sample_overseas_meeting.json)",
    )
    p.add_argument(
        "--overseas",
        action="store_true",
        help="Run overseas / simulcast pipeline (separate from local)",
    )
    p.add_argument(
        "--page",
        choices=["local", "overseas"],
        help="Select pipeline page: local (default) or overseas",
    )
    p.add_argument(
        "--source",
        default="hkjc_simulcast",
        metavar="NAME",
        help="Overseas source adapter (default: hkjc_simulcast; also: external)",
    )
    p.add_argument(
        "--build-pages",
        action="store_true",
        help="Regenerate output/pages/index.html, local.html, overseas.html",
    )
    p.add_argument("--date", metavar="YYYY-MM-DD", help="Meeting date for live fetch")
    p.add_argument(
        "--venue",
        choices=["ST", "HV", "S1", "S2", "S3"],
        help="Venue: ST/HV (local) or S1/S2/S3 (simulcast)",
    )
    p.add_argument("--race", type=int, metavar="N", help="Limit output to race number N")
    p.add_argument(
        "--config",
        default=None,
        help="Path to weights YAML (default: local or overseas config by mode)",
    )
    p.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT),
        help=f"Output directory for tip sheets (default: {DEFAULT_OUTPUT})",
    )
    return p


def _want_overseas(args: argparse.Namespace) -> bool:
    if args.demo_overseas:
        return True
    if args.overseas:
        return True
    if getattr(args, "page", None) == "overseas":
        return True
    return False


def _resolve_config(args: argparse.Namespace, overseas: bool) -> Path:
    if args.config:
        config_path = _resolve_path(args.config)
        if config_path.is_file():
            return config_path
    default = DEFAULT_OVERSEAS_CONFIG if overseas else DEFAULT_CONFIG
    if default.is_file():
        return default.resolve()
    rel = (
        Path("config/weights_overseas.yaml")
        if overseas
        else Path("config/weights.yaml")
    )
    for candidate in (rel, PACKAGE_ROOT / rel):
        if candidate.is_file():
            return candidate.resolve()
    raise FileNotFoundError(str(default))


def _filter_race(meeting, race_no: int | None):
    if race_no is None:
        return meeting
    meeting.races = [r for r in meeting.races if r.race_no == race_no]
    return meeting


def run_live(args: argparse.Namespace) -> int:
    """Fetch active GraphQL meeting(s), score, write tip sheets, rebuild pages."""
    from hkjc_predictor.live import run_live_pipeline
    from hkjc_predictor.web.app import save_state

    result = run_live_pipeline(
        date=args.date,
        venue=args.venue,
        race=args.race,
        output_dir=args.output,
        source=args.source or "hkjc_simulcast",
        config=args.config,
        quiet=False,
    )
    payload = result.to_api_dict()
    payload["refreshing"] = False
    try:
        save_state(payload)
    except OSError as e:
        print(f"WARN: could not write web_state.json: {e}", file=sys.stderr)
    if not result.ok:
        print(f"ERROR: {result.error}", file=sys.stderr)
        # Config missing -> exit 2 to match prior behaviour
        if result.error and "config not found" in result.error:
            return 2
        return 1
    return 0


def run_local(args: argparse.Namespace) -> int:
    try:
        config_path = _resolve_config(args, overseas=False)
    except FileNotFoundError as e:
        print(f"ERROR: weights config not found: {e}", file=sys.stderr)
        return 2

    cfg = load_weights(config_path)
    output_dir = Path(args.output)
    messages: list[str] = []
    meeting = None

    if args.demo:
        sample = DEFAULT_SAMPLE
        if not sample.is_file():
            sample = Path("data/sample_meeting.json")
        meeting = load_meeting_json(sample)
        messages.append(f"Demo mode: loaded sample meeting from {sample}")
    elif args.date:
        venue = args.venue or "ST"
        if venue.upper() in {"S1", "S2", "S3"}:
            print(
                "ERROR: S1/S2/S3 are overseas venues; use --live or --overseas",
                file=sys.stderr,
            )
            return 2
        try:
            meeting = fetch_meeting(args.date, venue)
            messages.append(
                f"Live fetch: {meeting.date} {meeting.venue} "
                f"({len(meeting.races)} races, source={meeting.source})"
            )
        except FetchError as e:
            print(f"ERROR: {e}", file=sys.stderr)
            print("Tip: use --demo or --live for offline/active data.", file=sys.stderr)
            return 1
        except Exception as e:  # noqa: BLE001
            print(f"ERROR: live fetch failed: {e}", file=sys.stderr)
            print("Tip: use --demo or --live for offline/active data.", file=sys.stderr)
            return 1
    else:
        after = date.today()
        live, status = try_fetch_next_meeting(after)
        messages.append(status)
        if live is not None:
            meeting = live
        else:
            sample = DEFAULT_SAMPLE
            if not sample.is_file():
                sample = Path("data/sample_meeting.json")
            meeting = load_meeting_json(sample)
            messages.append(f"Falling back to demo sample: {sample}")

    if args.race is not None:
        meeting.races = [r for r in meeting.races if r.race_no == args.race]
        if not meeting.races:
            print(f"ERROR: race {args.race} not found in meeting", file=sys.stderr)
            return 1

    sheet = score_meeting(meeting, cfg, config_path=str(config_path))
    md_path, txt_path = export_tip_sheet(sheet, output_dir)

    for msg in messages:
        print(msg)
    print()
    for line in summary_lines(sheet):
        print(line)
    print()
    print(f"Wrote: {md_path}")
    print(f"Wrote: {txt_path}")
    print()
    print(render_txt(sheet))

    if args.build_pages or args.command == "pages":
        from hkjc_predictor.overseas.report_overseas import build_pages

        paths = build_pages(output_dir)
        print(f"Pages: {paths['index']}")
        print(f"Pages: {paths['local']}")
        print(f"Pages: {paths['overseas']}")

    return 0


def run_overseas(args: argparse.Namespace) -> int:
    from hkjc_predictor.overseas.hkjc_simulcast import SimulcastFetchError
    from hkjc_predictor.overseas.report_overseas import (
        build_pages,
        export_overseas_tip_sheet,
        render_overseas_txt,
        summary_lines_overseas,
    )
    from hkjc_predictor.overseas.score_overseas import (
        load_overseas_weights,
        score_overseas_meeting,
    )
    from hkjc_predictor.overseas.sources import get_source

    try:
        config_path = _resolve_config(args, overseas=True)
    except FileNotFoundError as e:
        print(f"ERROR: overseas weights config not found: {e}", file=sys.stderr)
        return 2

    cfg = load_overseas_weights(config_path)
    output_dir = Path(args.output)
    messages: list[str] = []

    try:
        source = get_source(args.source)
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    demo = bool(args.demo_overseas or args.demo)
    # With --date or explicit live intent, try GraphQL; else demo for reliability
    if not demo and not args.date and not args.live:
        demo = True
        messages.append(
            "Overseas mode: no --date/--live given; using offline demo sample "
            "(pass --date or --live to attempt live GraphQL simulcast)."
        )

    try:
        meeting = source.load_meeting(demo=demo, date=args.date)
        messages.append(
            f"Overseas source={source.name}: loaded {meeting.date} {meeting.venue} "
            f"({len(meeting.races)} races) from {meeting.source}"
        )
    except NotImplementedError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    except (SimulcastFetchError, FileNotFoundError, Exception) as e:  # noqa: BLE001
        if demo:
            print(f"ERROR: {e}", file=sys.stderr)
            return 1
        print(f"ERROR: overseas live fetch failed: {e}", file=sys.stderr)
        print("Tip: use --demo-overseas or --live.", file=sys.stderr)
        return 1

    if args.race is not None:
        meeting.races = [r for r in meeting.races if r.race_no == args.race]
        if not meeting.races:
            print(f"ERROR: race {args.race} not found in overseas meeting", file=sys.stderr)
            return 1

    sheet = score_overseas_meeting(meeting, cfg, config_path=str(config_path))
    source_label = meeting.source or source.label
    md_path, txt_path = export_overseas_tip_sheet(
        sheet, output_dir, source_label=source_label
    )

    for msg in messages:
        print(msg)
    print()
    for line in summary_lines_overseas(sheet):
        print(line)
    print()
    print(f"Wrote: {md_path}")
    print(f"Wrote: {txt_path}")
    print()
    print(render_overseas_txt(sheet, source_label=source_label))

    paths = build_pages(
        output_dir,
        overseas_sheet=sheet,
        source_adapter=source.name,
        source_label=source_label,
    )
    print(f"Pages: {paths['index']}")
    print(f"Pages: {paths['local']}")
    print(f"Pages: {paths['overseas']}")
    return 0


def run_build_pages_only(args: argparse.Namespace) -> int:
    from hkjc_predictor.overseas.report_overseas import build_pages

    output_dir = Path(args.output)
    paths = build_pages(output_dir, source_adapter=args.source or "hkjc_simulcast")
    print(f"Wrote: {paths['index']}")
    print(f"Wrote: {paths['local']}")
    print(f"Wrote: {paths['overseas']}")
    return 0


def run_default(args: argparse.Namespace) -> int:
    """Default: try --live first; if no runners, fall back with a clear message."""
    from hkjc_predictor.graphql_client import GraphQLError, fetch_live_meetings

    try:
        meetings = fetch_live_meetings(
            date=args.date, venue_code=args.venue, cache=True
        )
        n_runners = sum(len(r.runners) for m in meetings for r in m.races)
        if meetings and n_runners > 0:
            args.live = True
            print(
                f"Default: live GraphQL found {len(meetings)} meeting(s), "
                f"{n_runners} runners — running --live"
            )
            return run_live(args)
        print(
            "Default: live GraphQL returned no runners; "
            "falling back to local demo sample."
        )
    except (GraphQLError, Exception) as e:  # noqa: BLE001
        print(
            f"Default: live GraphQL unavailable ({e}); "
            "falling back to local demo sample."
        )
    args.demo = True
    return run_local(args)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.live:
        return run_live(args)

    # pages-only command
    if args.command == "pages" and not _want_overseas(args) and not args.demo:
        return run_build_pages_only(args)
    if args.build_pages and not _want_overseas(args) and not args.demo and not args.date:
        return run_build_pages_only(args)

    if _want_overseas(args):
        return run_overseas(args)

    # Bare invocation (no demo/date/venue flags): try live then fall back
    if (
        not args.demo
        and not args.date
        and not args.venue
        and args.command is None
        and not args.build_pages
    ):
        return run_default(args)

    return run_local(args)


if __name__ == "__main__":
    raise SystemExit(main())
