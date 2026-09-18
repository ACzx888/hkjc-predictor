"""Tests for fundamental scorer — no odds involved."""

from __future__ import annotations

from pathlib import Path

import pytest

from hkjc_predictor.models import Meeting, Race, Runner
from hkjc_predictor.parse import load_meeting_json
from hkjc_predictor.score import (
    FORBIDDEN_KEYS,
    load_weights,
    parse_form,
    score_course_distance,
    score_draw_bias,
    score_meeting,
    score_recent_form,
    score_runner,
)

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "weights.yaml"
SAMPLE = ROOT / "data" / "sample_meeting.json"


@pytest.fixture(scope="module")
def cfg():
    return load_weights(CONFIG)


@pytest.fixture(scope="module")
def sample_meeting():
    return load_meeting_json(SAMPLE)


def test_weights_load(cfg):
    assert "weights" in cfg
    w = cfg["weights"]
    total = sum(float(v) for v in w.values())
    assert 0.95 <= total <= 1.05
    for key in (
        "recent_form",
        "course_distance_fit",
        "draw_bias",
        "jockey",
        "trainer",
        "rating",
        "weight_claim",
        "going_gear",
    ):
        assert key in w


def test_no_odds_keys_in_config(cfg):
    flat = str(cfg).lower()
    for bad in ("odds", "win_odds", "place_odds", "quinella", "pool"):
        assert bad not in flat


def test_forbidden_keys_constant():
    assert "odds" in FORBIDDEN_KEYS


def test_parse_form(cfg):
    assert parse_form("1/3/5/8/2/4", cfg) == [1, 3, 5, 8, 2, 4]
    assert parse_form("", cfg) == []
    assert parse_form("2-1-4", cfg) == [2, 1, 4]


def test_recent_form_better_placings_score_higher(cfg):
    good = Runner(
        horse_no=1, name="A", draw=1, jockey="X", trainer="Y",
        rating=50, weight_kg=126, form="1/1/2/3/1/2",
    )
    bad = Runner(
        horse_no=2, name="B", draw=1, jockey="X", trainer="Y",
        rating=50, weight_kg=126, form="10/9/8/11/12/9",
    )
    assert score_recent_form(good, cfg) > score_recent_form(bad, cfg)


def test_draw_bias_hv_turf_prefers_low(cfg):
    meeting = Meeting(
        date="2026-09-17", venue="HV", venue_name="Happy Valley",
        going="GOOD", surface="turf",
    )
    race = Race(
        race_no=1, name="T", class_="C4", distance_m=1200,
        surface="turf", going="GOOD",
    )
    inner = Runner(
        horse_no=1, name="In", draw=1, jockey="X", trainer="Y",
        rating=50, weight_kg=126,
    )
    outer = Runner(
        horse_no=2, name="Out", draw=12, jockey="X", trainer="Y",
        rating=50, weight_kg=126,
    )
    assert score_draw_bias(inner, race, meeting, cfg) > score_draw_bias(
        outer, race, meeting, cfg
    )


def test_course_distance_rewards_cd_wins(cfg):
    strong = Runner(
        horse_no=1, name="A", draw=1, jockey="X", trainer="Y",
        rating=50, weight_kg=126, cd_wins=2, cd_places=3, c_wins=1, d_wins=1,
    )
    weak = Runner(
        horse_no=2, name="B", draw=1, jockey="X", trainer="Y",
        rating=50, weight_kg=126, cd_wins=0, cd_places=0, c_wins=0, d_wins=0,
    )
    assert score_course_distance(strong, cfg) > score_course_distance(weak, cfg)


def test_score_runner_range(cfg, sample_meeting):
    race = sample_meeting.races[0]
    runner = race.runners[0]
    scored = score_runner(runner, race, sample_meeting, cfg)
    assert 0 <= scored.total <= 100
    d = scored.factors.as_dict()
    assert set(d.keys()) == {
        "recent_form",
        "course_distance_fit",
        "draw_bias",
        "jockey",
        "trainer",
        "rating",
        "weight_claim",
        "going_gear",
    }
    for v in d.values():
        assert 0 <= v <= 100


def test_score_meeting_ranks(sample_meeting, cfg):
    sheet = score_meeting(sample_meeting, cfg, config_path=str(CONFIG))
    assert len(sheet.scored_races) == 2
    for sr in sheet.scored_races:
        assert len(sr.scored) >= 8
        ranks = [s.rank for s in sr.scored]
        assert ranks == list(range(1, len(sr.scored) + 1))
        scores = [s.total for s in sr.scored]
        assert scores == sorted(scores, reverse=True)
    assert "NOT betting advice" in sheet.disclaimer
    # Ensure tip sheet path mentions no odds dependency in disclaimer study context
    assert "study" in sheet.disclaimer.lower() or "entertainment" in sheet.disclaimer.lower()


def test_sample_json_structure(sample_meeting):
    assert sample_meeting.venue == "HV"
    assert len(sample_meeting.races) == 2
    for race in sample_meeting.races:
        assert 8 <= len(race.runners) <= 12
        for r in race.runners:
            assert r.form
            assert r.draw >= 1
