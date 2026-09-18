"""Unit tests for softmax horse confidence and race confidence helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from hkjc_predictor.confidence import (
    attach_confidence,
    compute_race_confidence,
    softmax_probabilities,
)
from hkjc_predictor.models import FactorBreakdown, Runner, ScoredRunner
from hkjc_predictor.parse import load_meeting_json
from hkjc_predictor.score import load_weights, score_meeting

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "weights.yaml"
SAMPLE = ROOT / "data" / "sample_meeting.json"


def _factors() -> FactorBreakdown:
    return FactorBreakdown(
        recent_form=50,
        course_distance_fit=50,
        draw_bias=50,
        jockey=50,
        trainer=50,
        rating=50,
        weight_claim=50,
        going_gear=50,
    )


def _scored(total: float, no: int = 1, name: str = "H") -> ScoredRunner:
    return ScoredRunner(
        runner=Runner(
            horse_no=no,
            name=name,
            draw=no,
            jockey="J",
            trainer="T",
            rating=50,
            weight_kg=126,
        ),
        total=total,
        factors=_factors(),
    )


def test_softmax_sums_to_one():
    probs = softmax_probabilities([70, 65, 60, 55], temperature=8.0)
    assert len(probs) == 4
    assert abs(sum(probs) - 1.0) < 1e-9
    assert all(0 < p < 1 for p in probs)


def test_softmax_higher_score_higher_prob():
    probs = softmax_probabilities([80, 60, 50], temperature=8.0)
    assert probs[0] > probs[1] > probs[2]


def test_softmax_lower_temperature_sharper():
    scores = [75, 70, 65]
    sharp = softmax_probabilities(scores, temperature=4.0)
    flat = softmax_probabilities(scores, temperature=20.0)
    assert sharp[0] > flat[0]


def test_softmax_empty_and_single():
    assert softmax_probabilities([]) == []
    assert softmax_probabilities([50.0]) == [1.0]


def test_race_confidence_clear_favourite_high():
    # Large gap + peaked distribution
    scores = [85.0, 60.0, 55.0, 50.0]
    probs = softmax_probabilities(scores, temperature=6.0)
    pct, label = compute_race_confidence(scores, probs, {"gap_scale": 10.0})
    assert pct >= 70
    assert label == "High"


def test_race_confidence_bunched_field_low():
    scores = [62.0, 61.5, 61.0, 60.5, 60.0, 59.5]
    probs = softmax_probabilities(scores, temperature=8.0)
    pct, label = compute_race_confidence(
        scores, probs, {"gap_scale": 10.0, "high_threshold": 70, "med_threshold": 45}
    )
    assert pct < 45
    assert label == "Low"


def test_attach_confidence_sets_horse_and_race():
    scored = [_scored(78, 1, "A"), _scored(70, 2, "B"), _scored(62, 3, "C")]
    cfg = {"confidence": {"temperature": 8.0, "gap_scale": 10.0}}
    race_pct, label = attach_confidence(scored, cfg)
    assert abs(sum(s.confidence for s in scored) - 100.0) < 0.2
    assert scored[0].confidence > scored[1].confidence > scored[2].confidence
    assert 0 <= race_pct <= 100
    assert label in {"High", "Med", "Low"}


def test_score_meeting_includes_confidence():
    cfg = load_weights(CONFIG)
    meeting = load_meeting_json(SAMPLE)
    sheet = score_meeting(meeting, cfg, config_path=str(CONFIG))
    assert "confidence" in cfg
    for sr in sheet.scored_races:
        assert 0 <= sr.race_confidence <= 100
        assert sr.race_confidence_label in {"High", "Med", "Low"}
        confs = [s.confidence for s in sr.scored]
        assert abs(sum(confs) - 100.0) < 0.5
        assert all(0 <= c <= 100 for c in confs)
        # Top ranked should have highest conf among field (same order as score)
        assert sr.scored[0].confidence == max(confs)
