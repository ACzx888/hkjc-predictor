"""Tests for overseas scorer + separate report path from local."""

from __future__ import annotations

from pathlib import Path

import pytest

from hkjc_predictor.models import Meeting, Race, Runner
from hkjc_predictor.parse import load_meeting_json
from hkjc_predictor.overseas.report_overseas import (
    build_pages,
    export_overseas_tip_sheet,
    render_overseas_html_page,
)
from hkjc_predictor.overseas.score_overseas import (
    FORBIDDEN_KEYS,
    load_overseas_weights,
    score_generic_draw,
    score_overseas_meeting,
    score_overseas_runner,
)
from hkjc_predictor.overseas.sources import get_source, list_sources
from hkjc_predictor.report import export_tip_sheet
from hkjc_predictor.score import load_weights, score_meeting

ROOT = Path(__file__).resolve().parents[1]
LOCAL_CONFIG = ROOT / "config" / "weights.yaml"
OVERSEAS_CONFIG = ROOT / "config" / "weights_overseas.yaml"
LOCAL_SAMPLE = ROOT / "data" / "sample_meeting.json"
OVERSEAS_SAMPLE = ROOT / "data" / "sample_overseas_meeting.json"


@pytest.fixture(scope="module")
def ocfg():
    return load_overseas_weights(OVERSEAS_CONFIG)


@pytest.fixture(scope="module")
def overseas_meeting():
    return load_meeting_json(OVERSEAS_SAMPLE)


def test_overseas_weights_load(ocfg):
    assert "weights" in ocfg
    w = ocfg["weights"]
    total = sum(float(v) for v in w.values())
    assert 0.95 <= total <= 1.05
    assert "draw_generic" in w
    assert "HV" not in ocfg.get("draw_generic", {})
    assert "ST" not in ocfg.get("draw_generic", {})
    # Must not ship local draw_bias venue tables
    assert "HV" not in (ocfg.get("draw_bias") or {})
    assert "ST" not in (ocfg.get("draw_bias") or {})


def test_overseas_no_odds_keys(ocfg):
    flat = str(ocfg).lower()
    for bad in ("odds", "win_odds", "place_odds", "quinella", "pool"):
        assert bad not in flat
    assert "odds" in FORBIDDEN_KEYS


def test_generic_draw_prefers_inner_on_sprint(ocfg):
    race = Race(
        race_no=1,
        name="Sprint",
        class_="Allow",
        distance_m=1200,
        surface="turf",
        going="GOOD",
        runners=[],
    )
    # Attach field for field_size
    runners = [
        Runner(
            horse_no=i,
            name=f"H{i}",
            draw=i,
            jockey="X",
            trainer="Y",
            rating=90,
            weight_kg=55,
        )
        for i in range(1, 13)
    ]
    race.runners = runners
    inner = runners[0]
    outer = runners[-1]
    assert score_generic_draw(inner, race, ocfg) > score_generic_draw(outer, race, ocfg)


def test_score_overseas_runner_range(ocfg, overseas_meeting):
    race = overseas_meeting.races[0]
    runner = race.runners[0]
    scored = score_overseas_runner(runner, race, overseas_meeting, ocfg)
    assert 0 <= scored.total <= 100
    for v in scored.factors.as_dict().values():
        assert 0 <= v <= 100


def test_score_overseas_meeting_ranks(overseas_meeting, ocfg):
    sheet = score_overseas_meeting(
        overseas_meeting, ocfg, config_path=str(OVERSEAS_CONFIG)
    )
    assert len(sheet.scored_races) == 2
    assert overseas_meeting.races[0].race_id == "S2-1"
    assert overseas_meeting.races[1].race_id == "S2-2"
    for sr in sheet.scored_races:
        assert len(sr.scored) >= 8
        ranks = [s.rank for s in sr.scored]
        assert ranks == list(range(1, len(sr.scored) + 1))
        scores = [s.total for s in sr.scored]
        assert scores == sorted(scores, reverse=True)
    assert "HV/ST" in sheet.disclaimer or "generic" in sheet.disclaimer.lower()


def test_overseas_report_path_separate_from_local(tmp_path, overseas_meeting, ocfg):
    """Overseas tip files must use tips_overseas_* stem; local uses tips_*."""
    local_cfg = load_weights(LOCAL_CONFIG)
    local_meeting = load_meeting_json(LOCAL_SAMPLE)
    local_sheet = score_meeting(local_meeting, local_cfg, config_path=str(LOCAL_CONFIG))
    o_sheet = score_overseas_meeting(
        overseas_meeting, ocfg, config_path=str(OVERSEAS_CONFIG)
    )

    l_md, l_txt = export_tip_sheet(local_sheet, tmp_path)
    o_md, o_txt = export_overseas_tip_sheet(o_sheet, tmp_path)

    assert l_md.name.startswith("tips_")
    assert not l_md.name.startswith("tips_overseas_")
    assert o_md.name.startswith("tips_overseas_")
    assert o_txt.name.startswith("tips_overseas_")
    assert l_md.resolve() != o_md.resolve()
    assert "Overseas" in o_md.read_text(encoding="utf-8")
    assert "generic draw" in o_md.read_text(encoding="utf-8").lower() or "HV/ST" in o_md.read_text(
        encoding="utf-8"
    )


def test_hkjc_simulcast_demo_does_not_call_local_fetch(monkeypatch, overseas_meeting):
    """Overseas demo path must not invoke local fetch_meeting."""
    import hkjc_predictor.fetch as fetch_mod

    def boom(*_a, **_k):
        raise AssertionError("local fetch_meeting must not be called for overseas demo")

    monkeypatch.setattr(fetch_mod, "fetch_meeting", boom)
    src = get_source("hkjc_simulcast")
    meeting = src.load_meeting(demo=True, sample_path=str(OVERSEAS_SAMPLE))
    assert meeting.venue == "JPN"
    assert len(meeting.races) == 2


def test_external_source_is_stub():
    src = get_source("external")
    with pytest.raises(NotImplementedError):
        src.load_meeting(demo=True)


def test_list_sources():
    names = list_sources()
    assert "hkjc_simulcast" in names
    assert "external" in names


def test_build_pages_creates_distinct_html(tmp_path, overseas_meeting, ocfg):
    local_cfg = load_weights(LOCAL_CONFIG)
    local_meeting = load_meeting_json(LOCAL_SAMPLE)
    local_sheet = score_meeting(local_meeting, local_cfg)
    o_sheet = score_overseas_meeting(overseas_meeting, ocfg)
    export_tip_sheet(local_sheet, tmp_path)
    export_overseas_tip_sheet(o_sheet, tmp_path)

    paths = build_pages(
        tmp_path,
        overseas_sheet=o_sheet,
        source_adapter="hkjc_simulcast",
        source_label="HKJC Simulcast sample",
    )
    assert paths["index"].is_file()
    assert paths["local"].is_file()
    assert paths["overseas"].is_file()
    index = paths["index"].read_text(encoding="utf-8")
    assert "local.html" in index
    assert "overseas.html" in index
    overseas_html = paths["overseas"].read_text(encoding="utf-8")
    assert "海外" in overseas_html or "Overseas" in overseas_html
    assert "hkjc_simulcast" in overseas_html
    assert "DISCLAIMER" in overseas_html or "免責" in overseas_html
    local_html = paths["local"].read_text(encoding="utf-8")
    assert "本地" in local_html or "Local" in local_html
    # Distinct pages
    assert paths["local"].resolve() != paths["overseas"].resolve()


def test_render_overseas_html_includes_source(overseas_meeting, ocfg):
    sheet = score_overseas_meeting(overseas_meeting, ocfg)
    html = render_overseas_html_page(
        sheet,
        source_adapter="hkjc_simulcast",
        source_label="HKJC Simulcast sample",
    )
    assert "Source adapter" in html
    assert "hkjc_simulcast" in html
    assert "S2-1" in html
