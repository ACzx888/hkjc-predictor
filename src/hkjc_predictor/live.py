"""Shared live GraphQL pipeline used by CLI and web refresh."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from hkjc_predictor.report import export_tip_sheet, render_txt, summary_lines
from hkjc_predictor.score import load_weights, score_meeting

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = PACKAGE_ROOT / "config" / "weights.yaml"
DEFAULT_OVERSEAS_CONFIG = PACKAGE_ROOT / "config" / "weights_overseas.yaml"
DEFAULT_OUTPUT = PACKAGE_ROOT / "output"


@dataclass
class LiveResult:
    """Structured result of a live refresh (fundamentals only, no odds)."""

    ok: bool
    meeting: str = ""
    races: int = 0
    refreshed_at: str = ""
    error: Optional[str] = None
    messages: list[str] = field(default_factory=list)
    local_declared: bool = False
    overseas_declared: bool = False
    meetings: list[dict[str, Any]] = field(default_factory=list)
    wrote: list[str] = field(default_factory=list)
    pages: dict[str, str] = field(default_factory=dict)

    def to_api_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "ok": self.ok,
            "meeting": self.meeting,
            "races": self.races,
            "refreshed_at": self.refreshed_at,
            "local_declared": self.local_declared,
            "overseas_declared": self.overseas_declared,
            "meetings": self.meetings,
            "messages": self.messages,
        }
        if self.error:
            out["error"] = self.error
        return out


def _now_hkt() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S HKT")


def _resolve_config_path(
    config: Optional[str | Path],
    *,
    overseas: bool,
) -> Path:
    if config:
        path = Path(config)
        if path.is_file():
            return path.resolve()
        alt = PACKAGE_ROOT / config
        if alt.is_file():
            return alt.resolve()
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


def run_live_pipeline(
    *,
    date: Optional[str] = None,
    venue: Optional[str] = None,
    race: Optional[int] = None,
    output_dir: Optional[str | Path] = None,
    source: str = "hkjc_simulcast",
    config: Optional[str | Path] = None,
    quiet: bool = False,
) -> LiveResult:
    """Fetch active GraphQL meeting(s), score (no odds), write tip sheets, rebuild pages.

    Same code path as CLI ``--live``.
    """
    from hkjc_predictor.graphql_client import (
        GraphQLError,
        fetch_live_meetings,
        note_next_local_fixture,
        split_local_overseas,
    )
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

    refreshed_at = _now_hkt()
    out_dir = Path(output_dir) if output_dir else DEFAULT_OUTPUT
    messages: list[str] = []
    wrote: list[str] = []
    meetings_meta: list[dict[str, Any]] = []

    try:
        meetings = fetch_live_meetings(
            date=date,
            venue_code=venue,
            cache=True,
        )
    except GraphQLError as e:
        return LiveResult(
            ok=False,
            refreshed_at=refreshed_at,
            error=f"GraphQL live fetch failed: {e}",
        )
    except Exception as e:  # noqa: BLE001
        return LiveResult(
            ok=False,
            refreshed_at=refreshed_at,
            error=f"live fetch failed: {e}",
        )

    if not meetings:
        return LiveResult(
            ok=False,
            refreshed_at=refreshed_at,
            error="No active meetings with runners from GraphQL.",
        )

    local_meetings, overseas_meetings = split_local_overseas(meetings)
    if venue and venue.upper() in {"S1", "S2", "S3"}:
        if not overseas_meetings and meetings:
            overseas_meetings = list(meetings)
            local_meetings = []

    overseas_sheet = None
    source_label = ""
    local_fixture_note = note_next_local_fixture()
    local_declared = bool(local_meetings)
    total_races = 0
    meeting_labels: list[str] = []

    # --- Overseas ---
    if overseas_meetings:
        try:
            o_cfg_path = _resolve_config_path(config, overseas=True)
        except FileNotFoundError as e:
            return LiveResult(
                ok=False,
                refreshed_at=refreshed_at,
                error=f"overseas weights config not found: {e}",
            )
        o_cfg = load_overseas_weights(o_cfg_path)
        for meeting in overseas_meetings:
            if race is not None:
                _filter_race(meeting, race)
                if not meeting.races:
                    return LiveResult(
                        ok=False,
                        refreshed_at=refreshed_at,
                        error=f"race {race} not found in overseas meeting",
                    )
            sheet = score_overseas_meeting(
                meeting, o_cfg, config_path=str(o_cfg_path)
            )
            overseas_sheet = sheet
            source_label = meeting.source or "HKJC GraphQL"
            md_path, txt_path = export_overseas_tip_sheet(
                sheet, out_dir, source_label=source_label
            )
            n_runners = sum(len(r.runners) for r in meeting.races)
            msg = (
                f"Live overseas: {meeting.date} {meeting.venue} "
                f"({len(meeting.races)} races, {n_runners} runners) "
                f"source={meeting.source}"
            )
            messages.append(msg)
            wrote.extend([str(md_path), str(txt_path)])
            total_races += len(meeting.races)
            label = f"{meeting.date} {meeting.venue}"
            meeting_labels.append(label)
            meetings_meta.append(
                {
                    "kind": "overseas",
                    "date": meeting.date,
                    "venue": meeting.venue,
                    "venue_name": meeting.venue_name,
                    "races": len(meeting.races),
                    "runners": n_runners,
                    "source": meeting.source,
                }
            )
            if not quiet:
                print()
                for line in summary_lines_overseas(sheet):
                    print(line)
                print()
                print(render_overseas_txt(sheet, source_label=source_label))

    # --- Local ---
    if local_meetings:
        try:
            l_cfg_path = _resolve_config_path(config, overseas=False)
        except FileNotFoundError as e:
            return LiveResult(
                ok=False,
                refreshed_at=refreshed_at,
                error=f"weights config not found: {e}",
            )
        l_cfg = load_weights(l_cfg_path)
        for meeting in local_meetings:
            if race is not None:
                _filter_race(meeting, race)
                if not meeting.races:
                    return LiveResult(
                        ok=False,
                        refreshed_at=refreshed_at,
                        error=f"race {race} not found in local meeting",
                    )
            sheet = score_meeting(meeting, l_cfg, config_path=str(l_cfg_path))
            md_path, txt_path = export_tip_sheet(sheet, out_dir)
            msg = (
                f"Live local: {meeting.date} {meeting.venue} "
                f"({len(meeting.races)} races) source={meeting.source}"
            )
            messages.append(msg)
            wrote.extend([str(md_path), str(txt_path)])
            total_races += len(meeting.races)
            label = f"{meeting.date} {meeting.venue}"
            meeting_labels.append(label)
            meetings_meta.append(
                {
                    "kind": "local",
                    "date": meeting.date,
                    "venue": meeting.venue,
                    "venue_name": meeting.venue_name,
                    "races": len(meeting.races),
                    "runners": sum(len(r.runners) for r in meeting.races),
                    "source": meeting.source,
                }
            )
            if not quiet:
                print()
                for line in summary_lines(sheet):
                    print(line)
                print()
                print(render_txt(sheet))
    else:
        messages.append(
            "No local ST/HV card declared in GraphQL active meetings. "
            + local_fixture_note
        )

    if not overseas_meetings and not local_meetings:
        return LiveResult(
            ok=False,
            refreshed_at=refreshed_at,
            error="Active meetings mapped but none scored.",
            messages=messages,
        )

    if not quiet:
        for msg in messages:
            print(msg)
        for path in wrote:
            print(f"Wrote: {path}")

    paths = build_pages(
        out_dir,
        overseas_sheet=overseas_sheet,
        source_adapter=source or "hkjc_simulcast",
        source_label=source_label,
        local_fixture_note=None if local_declared else local_fixture_note,
        local_card_declared=local_declared,
    )
    if not quiet:
        print(f"Pages: {paths['index']}")
        print(f"Pages: {paths['local']}")
        print(f"Pages: {paths['overseas']}")

    meeting_summary = " | ".join(meeting_labels) if meeting_labels else ""
    return LiveResult(
        ok=True,
        meeting=meeting_summary,
        races=total_races,
        refreshed_at=refreshed_at,
        messages=messages,
        local_declared=local_declared,
        overseas_declared=bool(overseas_meetings),
        meetings=meetings_meta,
        wrote=wrote,
        pages={k: str(v) for k, v in paths.items()},
    )
